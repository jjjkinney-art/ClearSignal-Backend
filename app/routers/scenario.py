"""Scenario routes — beta milestone 3.

Exposes the already-built Scenario Engine read layer as a user-facing REST
surface.  Like the portfolio router, this is a thin HTTP adapter with NO new
business logic — it reuses

    * app.services.scenario_read_service        (formatted scenario reads)
    * app.services.scenario_portfolio_propagation (portfolio scenario impact)
    * app.services.portfolio_mirror_service       (ensure_default_portfolio)

Endpoints
---------
    GET /scenarios                     — top scenarios for the caller
    GET /scenarios/{ticker}            — scenarios for a ticker
    GET /scenarios/{ticker}/facet      — condensed scenario facet for a ticker

Portfolio-level scenario impact is deliberately deferred: it requires
orchestrating the propagation engine (scenario_propagation_engine ->
propagate_to_portfolio) rather than a thin read, and is a follow-up milestone.

Design
------
* Read-only and descriptive: the payloads carry NO conviction, stance,
  buy/sell/hold, or price-target fields (the scenario engine is a "what changes
  if X happens?" describer, not a recommender).
* Safe when the scenario engine is unbuilt/shadow: the read services return
  empty facets when no snapshots have been persisted, so these routes return
  empty payloads rather than erroring.  Activating scenario *building*
  (SCENARIO_BUILD_ENABLED / SCENARIO_SCORING_ENABLED) is an ops/env decision,
  deliberately NOT hardcoded here.
* All reads are scoped to the caller (request.state.user_id -> bypass user).
* No conviction-engine calls.  No new tables.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def _user_id(request: Optional[Request]) -> str:
    """Resolve the acting user (401 for unauthenticated enforcement-mode requests;
    bypass user only when auth is disabled or middleware is absent)."""
    from app.dependencies.auth import require_user_id
    return require_user_id(request)


# ---------------------------------------------------------------------------
# GET /scenarios — top scenarios for the caller
# ---------------------------------------------------------------------------

@router.get("", summary="Top scenarios for the caller")
async def list_scenarios(request: Request = None, limit: int = 20) -> dict:
    from app.db import get_session
    from app.services.scenario_read_service import get_top_scenarios

    uid = _user_id(request)
    async with get_session() as db:
        return await get_top_scenarios(db, limit=limit, user_id=uid)


# ---------------------------------------------------------------------------
# GET /scenarios/{ticker}/facet — condensed facet for a ticker
# ---------------------------------------------------------------------------

@router.get("/{ticker}/facet", summary="Condensed scenario facet for a ticker")
async def scenario_facet(ticker: str, request: Request = None) -> dict:
    from app.db import get_session
    from app.services.scenario_read_service import get_scenario_facet_for_ticker

    uid = _user_id(request)
    async with get_session() as db:
        return await get_scenario_facet_for_ticker(db, ticker.strip().upper(), user_id=uid)


# ---------------------------------------------------------------------------
# GET /scenarios/{ticker} — scenarios for a ticker
# ---------------------------------------------------------------------------

@router.get("/{ticker}", summary="Scenarios for a ticker")
async def scenarios_for_ticker(ticker: str, request: Request = None, limit: int = 10) -> dict:
    from app.db import get_session
    from app.services.scenario_read_service import get_scenarios_for_ticker

    uid = _user_id(request)
    async with get_session() as db:
        return await get_scenarios_for_ticker(db, ticker.strip().upper(), limit=limit, user_id=uid)
