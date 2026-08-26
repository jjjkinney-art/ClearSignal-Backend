"""Portfolio routes — beta milestone 2.

Exposes the already-built portfolio services + repository as a user-facing REST
surface.  This router contains NO new business logic: it is a thin HTTP adapter
over

    * app.db.repositories.portfolio_repo    (positions CRUD, insight reads)
    * app.services.portfolio_mirror_service  (ensure_default_portfolio)
    * app.services.portfolio_health_service  (compute_portfolio_health)
    * app.services.portfolio_exposure_service (project_portfolio_exposure)

Endpoints
---------
    GET    /portfolio                      — default portfolio metadata + counts
    GET    /portfolio/positions            — list active positions
    POST   /portfolio/positions            — add / upsert a position
    DELETE /portfolio/positions/{ticker}   — soft-delete a position
    GET    /portfolio/health               — concentration / diversification / warnings
    GET    /portfolio/exposure             — shared-risk / failure-mode clusters
    GET    /portfolio/insights             — persisted portfolio insights

Design
------
* Read-only endpoints always work: when persistence is disabled (no DATABASE_URL)
  the services return safe empty defaults and these routes return empty/zeroed
  payloads rather than erroring.
* user_id is read from request.state (auth middleware / bypass user).  All
  reads/writes are scoped to the caller's default portfolio.
* No conviction-engine calls.  No scoring.  No new tables.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

_VALID_MEMBERSHIP = {"owned", "watchlist", "on_radar"}
_TICKER_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,4}$")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PositionRequest(BaseModel):
    ticker:           str
    membership_class: str = "owned"
    weight:           Optional[float] = None
    cost_basis:       Optional[float] = None
    shares:           Optional[float] = None
    notes:            Optional[str] = None

    @field_validator("ticker")
    @classmethod
    def _validate_ticker(cls, v: str) -> str:
        raw = (v or "").strip()
        if not raw:
            raise ValueError("ticker is required")
        symbol = raw.upper()
        if _TICKER_SYMBOL.fullmatch(symbol):
            return symbol

        # Company names and aliases are resolved to the canonical security
        # symbol before persistence (for example, "Palantir" -> "PLTR").
        from app.services.entity_resolution_service import resolve_query
        resolved = resolve_query(raw)
        if resolved.canonical_ticker and not resolved.needs_clarification:
            return resolved.canonical_ticker
        raise ValueError(
            "Enter a valid ticker symbol or a recognized company name."
        )

    @field_validator("membership_class")
    @classmethod
    def _validate_membership(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in _VALID_MEMBERSHIP:
            raise ValueError(
                f"Invalid membership_class {v!r}. Supported: {sorted(_VALID_MEMBERSHIP)}"
            )
        return v

    @field_validator("weight")
    @classmethod
    def _validate_weight(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not 0 < v <= 1:
            raise ValueError("weight must be greater than 0 and no more than 1")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_id(request: Optional[Request]) -> str:
    """Resolve the acting user (401 for unauthenticated enforcement-mode requests;
    bypass user only when auth is disabled or middleware is absent)."""
    from app.dependencies.auth import require_user_id
    return require_user_id(request)


def _position_dict(row) -> dict:
    return {
        "ticker":           row.ticker,
        "membership_class": row.membership_class,
        "weight":           row.weight,
        "cost_basis":       row.cost_basis,
        "shares":           row.shares,
        "notes":            row.notes,
        "added_at":         row.added_at.isoformat() if row.added_at else None,
    }


def _insight_dict(row) -> dict:
    try:
        members = json.loads(row.member_tickers or "[]")
    except Exception:
        members = []
    try:
        body = json.loads(row.body_json or "{}")
    except Exception:
        body = {}
    return {
        "insight_type":   row.insight_type,
        "cluster_label":  row.cluster_label,
        "member_tickers": members,
        "cluster_weight": row.cluster_weight,
        "severity":       row.severity,
        "rank_score":     row.rank_score,
        "body":           body,
        "stale_input":    row.stale_input,
        "created_at":     row.created_at.isoformat() if row.created_at else None,
    }


async def _default_portfolio_id(session, uid: Optional[str]) -> Optional[str]:
    """Return the caller's default portfolio id, creating it on first use."""
    from app.services.portfolio_mirror_service import ensure_default_portfolio
    pf = await ensure_default_portfolio(session, user_id=uid)
    return pf.id if pf is not None else None


# ---------------------------------------------------------------------------
# GET /portfolio
# ---------------------------------------------------------------------------

@router.get("", summary="Default portfolio metadata + position counts")
async def get_portfolio(request: Request = None) -> dict:
    from app.db import get_session
    from app.db.repositories.portfolio_repo import position_list

    uid = _user_id(request)
    async with get_session() as db:
        if db is None:
            return {"portfolio_id": None, "position_count": 0, "positions": {},
                    "persistence": "disabled"}
        pf = await _default_portfolio_id(db, uid)
        if pf is None:
            return {"portfolio_id": None, "position_count": 0, "positions": {}}
        positions = await position_list(db, pf)
        by_class: dict = {}
        for p in positions:
            by_class[p.membership_class] = by_class.get(p.membership_class, 0) + 1
        return {
            "portfolio_id":   pf,
            "position_count": len(positions),
            "positions":      by_class,
        }


# ---------------------------------------------------------------------------
# GET /portfolio/positions
# ---------------------------------------------------------------------------

@router.get("/positions", summary="List active portfolio positions")
async def list_positions(request: Request = None) -> list:
    from app.db import get_session
    from app.db.repositories.portfolio_repo import position_list

    uid = _user_id(request)
    async with get_session() as db:
        if db is None:
            return []
        pf = await _default_portfolio_id(db, uid)
        if pf is None:
            return []
        return [_position_dict(p) for p in await position_list(db, pf)]


# ---------------------------------------------------------------------------
# POST /portfolio/positions
# ---------------------------------------------------------------------------

@router.post("/positions", summary="Add or update a portfolio position")
async def add_position(body: PositionRequest, request: Request = None) -> dict:
    from app.db import get_session
    from app.db.repositories.portfolio_repo import position_add

    uid = _user_id(request)
    async with get_session() as db:
        if db is None:
            raise HTTPException(status_code=503, detail="Persistence disabled.")
        pf = await _default_portfolio_id(db, uid)
        if pf is None:
            raise HTTPException(status_code=503, detail="Portfolio unavailable.")
        row = await position_add(
            db, pf, body.ticker,
            membership_class=body.membership_class,
            weight=body.weight,
            cost_basis=body.cost_basis,
            shares=body.shares,
            notes=body.notes,
        )
        if row is None:
            raise HTTPException(status_code=503, detail="Position add failed.")
        return _position_dict(row)


@router.post("/positions/normalize", summary="Normalize legacy company-name positions")
async def normalize_positions(request: Request = None) -> dict:
    """Repair positions created before canonical ticker validation existed."""
    from app.db import get_session
    from app.db.repositories.portfolio_repo import position_add, position_list, position_remove
    from app.services.entity_resolution_service import resolve_query

    uid = _user_id(request)
    async with get_session() as db:
        if db is None:
            raise HTTPException(status_code=503, detail="Persistence disabled.")
        pf = await _default_portfolio_id(db, uid)
        if pf is None:
            raise HTTPException(status_code=503, detail="Portfolio unavailable.")

        normalized: list[dict[str, str]] = []
        for row in await position_list(db, pf):
            if _TICKER_SYMBOL.fullmatch(row.ticker):
                continue
            resolved = resolve_query(row.ticker)
            canonical = resolved.canonical_ticker
            if not canonical or resolved.needs_clarification or canonical == row.ticker:
                continue
            await position_add(
                db,
                pf,
                canonical,
                membership_class=row.membership_class,
                weight=row.weight,
                cost_basis=row.cost_basis,
                shares=row.shares,
                notes=row.notes,
            )
            await position_remove(db, pf, row.ticker)
            normalized.append({"from": row.ticker, "to": canonical})
        return {"normalized": normalized, "count": len(normalized)}


# ---------------------------------------------------------------------------
# DELETE /portfolio/positions/{ticker}
# ---------------------------------------------------------------------------

@router.delete("/positions/{ticker}", summary="Remove a portfolio position")
async def remove_position(ticker: str, request: Request = None) -> dict:
    from app.db import get_session
    from app.db.repositories.portfolio_repo import position_remove

    uid = _user_id(request)
    t = (ticker or "").strip().upper()
    async with get_session() as db:
        if db is None:
            return {"ticker": t, "removed": False, "persistence": "disabled"}
        pf = await _default_portfolio_id(db, uid)
        if pf is None:
            return {"ticker": t, "removed": False}
        removed = await position_remove(db, pf, t)
        return {"ticker": t, "removed": removed}


# ---------------------------------------------------------------------------
# GET /portfolio/health
# ---------------------------------------------------------------------------

@router.get("/health", summary="Portfolio concentration / diversification health")
async def portfolio_health(request: Request = None) -> dict:
    from app.db import get_session
    from app.services.portfolio_health_service import compute_portfolio_health

    uid = _user_id(request)
    async with get_session() as db:
        pf = await _default_portfolio_id(db, uid) if db is not None else None
        report = await compute_portfolio_health(db, pf or "")
        return dataclasses.asdict(report)


# ---------------------------------------------------------------------------
# GET /portfolio/exposure
# ---------------------------------------------------------------------------

@router.get("/exposure", summary="Portfolio shared-risk / failure-mode clusters")
async def portfolio_exposure(request: Request = None) -> dict:
    from app.db import get_session
    from app.services.portfolio_exposure_service import project_portfolio_exposure

    uid = _user_id(request)
    async with get_session() as db:
        pf = await _default_portfolio_id(db, uid) if db is not None else None
        projection = await project_portfolio_exposure(db, pf or "")
        return dataclasses.asdict(projection)


# ---------------------------------------------------------------------------
# GET /portfolio/insights
# ---------------------------------------------------------------------------

@router.get("/insights", summary="Persisted portfolio insights")
async def portfolio_insights(request: Request = None, limit: int = 50) -> list:
    from app.db import get_session
    from app.db.repositories.portfolio_repo import insight_list, position_list

    uid = _user_id(request)
    async with get_session() as db:
        if db is None:
            return []
        pf = await _default_portfolio_id(db, uid)
        if pf is None:
            return []
        active = {row.ticker for row in await position_list(db, pf)}
        current: list[dict] = []
        for row in await insight_list(db, pf, limit=limit):
            payload = _insight_dict(row)
            members = set(payload["member_tickers"])
            if members and members.issubset(active):
                current.append(payload)
        return current


@router.post("/insights/refresh", summary="Generate and rank current portfolio insights")
async def refresh_portfolio_insights(request: Request = None) -> dict:
    """Refresh persisted observations from the caller's current positions.

    This explicit write endpoint keeps GET /portfolio/insights read-only while
    ensuring the existing deterministic insight generator is actually invoked.
    """
    from app.db import get_session
    from app.services.portfolio_exposure_service import project_portfolio_exposure
    from app.services.portfolio_health_service import compute_portfolio_health
    from app.services.portfolio_insight_ranking_service import rank_portfolio_insights
    from app.services.portfolio_insight_service import generate_portfolio_insights

    uid = _user_id(request)
    async with get_session() as db:
        if db is None:
            raise HTTPException(status_code=503, detail="Persistence disabled.")
        pf = await _default_portfolio_id(db, uid)
        if pf is None:
            raise HTTPException(status_code=503, detail="Portfolio unavailable.")
        projection = await project_portfolio_exposure(db, pf)
        health = await compute_portfolio_health(db, pf)
        generated = await generate_portfolio_insights(db, projection, health)
        ranked = await rank_portfolio_insights(db, pf)
        return {
            "generated": dataclasses.asdict(generated),
            "ranked_count": len(ranked.insights),
            "rows_updated": ranked.rows_updated,
        }
