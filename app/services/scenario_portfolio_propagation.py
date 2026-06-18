"""
Scenario Portfolio Propagation — Phase 14 · Slice 7.

Extends scenario propagation with portfolio-aware structural context.
Given a propagation result (from scenario_propagation_engine) and portfolio
data, this module computes how a conditional scenario structurally interacts
with a portfolio's holdings.

Core rule: Portfolio propagation adjusts relevance and impact context.
It does NOT alter scenario truth.

What this module does
---------------------
  - compute_exposure_chain      — trace how a ticker's propagation touches a portfolio
  - compute_concentration_modifier — derive a structural concentration factor
  - compute_portfolio_scenario_impact — combine propagation + portfolio context
  - propagate_to_portfolio      — enrich a propagation result with portfolio context

What this module does NOT do
-----------------------------
  - Does NOT predict outcomes or assert target values
  - Does NOT suggest any action, change, or adjustment to a portfolio
  - Does NOT size, advise on, or describe any trade
  - Does NOT import conviction, order, execution, or delivery modules
  - Does NOT write to any table
  - Does NOT modify the source propagation dict

SP-6 invariant: reads only; adds structural context; never advises.

Two-tier model
--------------
  user_id=None  : global portfolios (Portfolio.user_id IS NULL)
  user_id=<uid> : user-specific portfolios (Portfolio.user_id = uid)

  Global scenario truth is never altered by portfolio context.
  Portfolio context is derived and attached; callers may use or discard it.

Output shape added by propagate_to_portfolio
--------------------------------------------
  portfolio_contexts    list   — one entry per processed portfolio
  portfolio_impact_score float — max impact score across all portfolios [0,1]
  concentration_modifier float — max modifier across all portfolios [0.5,2.0]

Portfolio context entry shape
-----------------------------
  portfolio_id            str
  portfolio_impact_score  float   [0, 1]   — structural hit coverage × confidence
  held_tickers       list[str]        — tickers held that are in affected_entities
  concentration_modifier  float   [0.5, 2.0]
  exposure_chain          list[dict]       — [{entity_key, depth, channel, weight_pct}]
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Concentration thresholds: total weight of affected holdings vs portfolio
_CONC_HIGH     = 0.50   # combined affected weight ≥ 50%  → modifier 2.0
_CONC_ELEVATED = 0.30   # combined affected weight ≥ 30%  → modifier 1.5
_CONC_MODERATE = 0.15   # combined affected weight ≥ 15%  → modifier 1.0
# combined affected weight <  15%  → modifier 0.5 (attenuated)

_CONC_MODIFIER_NONE     = 0.5
_CONC_MODIFIER_LOW      = 1.0
_CONC_MODIFIER_ELEVATED = 1.5
_CONC_MODIFIER_HIGH     = 2.0

# DB query caps (mirrors propagation engine limits)
_MAX_CROSS_DEPTH1 = 20
_MAX_CROSS_DEPTH2 = 8
_MAX_DEPTH1_FOR_CHAIN = 5  # cap depth-1 pivots for chain expansion


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _equal_weight(n: int) -> float:
    """Return equal weight for n positions; avoids division by zero."""
    return round(1.0 / n, 6) if n > 0 else 0.0


def _get_active_pairs(positions: list) -> List[Tuple[str, Optional[float]]]:
    """Extract (ticker_upper, weight_or_None) from position objects or dicts.

    Skips inactive rows (active=False).
    """
    result = []
    for pos in positions:
        if hasattr(pos, "ticker"):
            if not getattr(pos, "active", True):
                continue
            result.append((pos.ticker.upper(), getattr(pos, "weight", None)))
        elif isinstance(pos, dict):
            t = pos.get("ticker", "")
            if not t or not pos.get("active", True):
                continue
            result.append((t.upper(), pos.get("weight")))
    return result


async def _cross_exposed_for_chain(
    session,
    ticker: str,
    limit: int = _MAX_CROSS_DEPTH1,
) -> List[Tuple[str, str]]:
    """Return (other_ticker, exposure_type) pairs cross-exposed to *ticker*.

    Returns [] on any error.
    """
    try:
        from sqlalchemy import select
        from app.db.models import CrossExposure

        ticker_up = ticker.upper()
        stmt = (
            select(CrossExposure)
            .where(
                (CrossExposure.ticker_a == ticker_up)
                | (CrossExposure.ticker_b == ticker_up)
            )
            .order_by(CrossExposure.strength.desc(), CrossExposure.id.asc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
        result = []
        for row in rows:
            other = row.ticker_b if row.ticker_a == ticker_up else row.ticker_a
            result.append((other, row.exposure_type or "cross_exposure"))
        return sorted(result, key=lambda x: x[0])
    except Exception as exc:
        logger.debug("[portfolio_propagation] _cross_exposed_for_chain(%s): %r", ticker, exc)
        return []


async def _user_portfolio_ids(
    session,
    user_id: Optional[str],
) -> List[str]:
    """Return sorted portfolio IDs owned by *user_id* (or global if None)."""
    try:
        from app.db.repositories.portfolio_repo import portfolio_list
        portfolios = await portfolio_list(session, user_id=user_id)
        return sorted(p.id for p in (portfolios or []))
    except Exception as exc:
        logger.debug("[portfolio_propagation] _user_portfolio_ids: %r", exc)
        return []


async def _portfolio_belongs_to_user(
    session,
    portfolio_id: str,
    user_id: Optional[str],
) -> bool:
    """Return True if *portfolio_id* belongs to *user_id*.

    For global context (user_id=None), only global portfolios pass.
    For user context, only portfolios owned by that user pass.
    """
    try:
        from app.db.repositories.portfolio_repo import portfolio_get
        row = await portfolio_get(session, portfolio_id)
        if row is None:
            return False
        row_user = getattr(row, "user_id", None)
        if user_id is None:
            return row_user is None
        return row_user == user_id
    except Exception as exc:
        logger.debug("[portfolio_propagation] _portfolio_belongs_to_user: %r", exc)
        return False


# ---------------------------------------------------------------------------
# Public: compute_exposure_chain
# ---------------------------------------------------------------------------

async def compute_exposure_chain(
    session,
    ticker: str,
    portfolio_id: str,
) -> List[Dict[str, Any]]:
    """Build an ordered chain showing how *ticker*'s scenario propagation
    touches the holdings in *portfolio_id*.

    Returns a list of dicts:
        [{entity_key, depth, channel, weight_pct}]

    depth=0: *ticker* itself is held directly.
    depth=1: a cross-exposed peer of *ticker* is held.
    depth=2: a further cross-exposed peer (from a depth-1 ticker) is held.

    weight_pct is the user-supplied weight from PortfolioPosition, or None
    when not provided.

    Returns [] when session is None, ticker/portfolio_id are empty, or on error.
    """
    if session is None or not ticker or not portfolio_id:
        return []
    try:
        from app.db.repositories.portfolio_repo import position_list

        positions = await position_list(session, portfolio_id)
        if not positions:
            return []

        pairs = _get_active_pairs(positions)
        if not pairs:
            return []

        held: Dict[str, Optional[float]] = {t: w for t, w in pairs}
        ticker_up = ticker.upper()
        chain: List[Dict[str, Any]] = []
        seen: set = set()

        # depth 0 — direct holding
        if ticker_up in held:
            chain.append({
                "entity_key": ticker_up,
                "depth":      0,
                "channel":    "direct",
                "weight_pct": held[ticker_up],
            })
            seen.add(ticker_up)

        # depth 1 — cross-exposed peers held in portfolio
        cross1 = await _cross_exposed_for_chain(session, ticker_up, limit=_MAX_CROSS_DEPTH1)
        for other, etype in cross1:
            if other in seen:
                continue
            if other in held:
                chain.append({
                    "entity_key": other,
                    "depth":      1,
                    "channel":    f"cross_exposure:{etype}",
                    "weight_pct": held[other],
                })
                seen.add(other)

        # depth 2 — cross-exposed peers of depth-1 tickers that are also held
        depth1_tickers = [e["entity_key"] for e in chain if e["depth"] == 1]
        for d1_ticker in depth1_tickers[:_MAX_DEPTH1_FOR_CHAIN]:
            cross2 = await _cross_exposed_for_chain(session, d1_ticker, limit=_MAX_CROSS_DEPTH2)
            for other, etype in cross2:
                if other in seen:
                    continue
                if other in held:
                    chain.append({
                        "entity_key": other,
                        "depth":      2,
                        "channel":    f"cross_exposure:{etype}",
                        "weight_pct": held[other],
                    })
                    seen.add(other)

        return chain
    except Exception as exc:
        logger.debug("[portfolio_propagation] compute_exposure_chain error: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Public: compute_concentration_modifier
# ---------------------------------------------------------------------------

def compute_concentration_modifier(
    positions: list,
    affected_tickers: list,
) -> float:
    """Return a structural concentration factor for the affected tickers.

    Computes the combined portfolio weight of the *affected_tickers* that are
    actively held, then maps to a modifier:
        combined weight ≥ 50%  → 2.0  (concentrated cluster)
        combined weight ≥ 30%  → 1.5  (elevated cluster)
        combined weight ≥ 15%  → 1.0  (moderate presence)
        combined weight <  15%  → 0.5  (minimal footprint)

    When no weight data is provided, equal weighting is assumed.
    Accepts ORM PortfolioPosition objects or dicts with 'ticker'/'weight' keys.
    Returns 0.5 when no affected tickers are held or input is empty.
    """
    if not positions or not affected_tickers:
        return _CONC_MODIFIER_NONE

    affected_up = {t.upper() for t in affected_tickers if t}
    if not affected_up:
        return _CONC_MODIFIER_NONE

    pairs = _get_active_pairs(positions)
    n = len(pairs)
    if n == 0:
        return _CONC_MODIFIER_NONE

    default_w = _equal_weight(n)
    total_affected_weight = 0.0
    held_count = 0

    for ticker_up, weight in pairs:
        if ticker_up in affected_up:
            held_count += 1
            total_affected_weight += float(weight) if weight is not None else default_w

    if held_count == 0:
        return _CONC_MODIFIER_NONE

    if total_affected_weight >= _CONC_HIGH:
        return _CONC_MODIFIER_HIGH
    if total_affected_weight >= _CONC_ELEVATED:
        return _CONC_MODIFIER_ELEVATED
    if total_affected_weight >= _CONC_MODERATE:
        return _CONC_MODIFIER_LOW
    return _CONC_MODIFIER_NONE


# ---------------------------------------------------------------------------
# Public: compute_portfolio_scenario_impact
# ---------------------------------------------------------------------------

async def compute_portfolio_scenario_impact(
    session,
    propagation: dict,
    portfolio_id: str,
) -> Dict[str, Any]:
    """Compute structural portfolio impact context for one portfolio.

    Takes the propagation result from scenario_propagation_engine and a
    portfolio ID.  Returns a portfolio context dict.

    Output shape:
        portfolio_id            str
        portfolio_impact_score  float  [0, 1]
        held_tickers       list[str]
        concentration_modifier  float  [0.5, 2.0]
        exposure_chain          list[dict]

    Returns empty context when session is None, propagation is empty,
    or portfolio_id is empty.  Never raises.
    """
    _empty: Dict[str, Any] = {
        "portfolio_id":           portfolio_id,
        "portfolio_impact_score": 0.0,
        "held_tickers":      [],
        "concentration_modifier": _CONC_MODIFIER_NONE,
        "exposure_chain":         [],
    }
    if session is None or not propagation or not portfolio_id:
        return _empty

    try:
        from app.db.repositories.portfolio_repo import position_list

        positions = await position_list(session, portfolio_id)
        if not positions:
            return _empty

        pairs = _get_active_pairs(positions)
        if not pairs:
            return _empty

        held_tickers = {t for t, _ in pairs}

        # Affected company tickers from the propagation result
        affected_company_tickers = {
            e["entity_key"].upper()
            for e in propagation.get("affected_entities", [])
            if e.get("entity_type") == "company" and e.get("entity_key")
        }

        held_tickers = sorted(affected_company_tickers & held_tickers)

        # Concentration modifier
        concentration_modifier = compute_concentration_modifier(
            positions, held_tickers
        )

        # Primary ticker from direct impacts (first direct entry)
        direct = propagation.get("direct_impacts", [])
        primary_ticker = (
            direct[0]["entity_key"].upper()
            if direct and direct[0].get("entity_key")
            else ""
        )

        # Exposure chain from primary ticker through portfolio holdings
        exposure_chain = (
            await compute_exposure_chain(session, primary_ticker, portfolio_id)
            if primary_ticker
            else []
        )

        # Portfolio impact score:
        #   (fraction of portfolio affected) × confidence × concentration_modifier
        # A minimum confidence floor of 0.10 prevents zero scores for low-confidence seeds
        n_total   = max(len(held_tickers), 1)
        n_affected = len(held_tickers)
        base_ratio = n_affected / n_total
        confidence = float(propagation.get("impact_confidence", 0.0))
        raw_score  = base_ratio * max(confidence, 0.10) * concentration_modifier
        portfolio_impact_score = round(min(raw_score, 1.0), 4)

        return {
            "portfolio_id":           portfolio_id,
            "portfolio_impact_score": portfolio_impact_score,
            "held_tickers":      held_tickers,
            "concentration_modifier": concentration_modifier,
            "exposure_chain":         exposure_chain,
        }
    except Exception as exc:
        logger.debug(
            "[portfolio_propagation] compute_portfolio_scenario_impact(%s): %r",
            portfolio_id, exc,
        )
        return _empty


# ---------------------------------------------------------------------------
# Public: propagate_to_portfolio
# ---------------------------------------------------------------------------

async def propagate_to_portfolio(
    session,
    propagation: dict,
    *,
    user_id: Optional[str] = None,
) -> dict:
    """Enrich a propagation result with portfolio-level structural context.

    For each portfolio in propagation["affected_portfolios"], compute the
    portfolio impact context (holdings coverage, concentration, exposure chain).
    When affected_portfolios is empty and user_id is supplied, discovers
    portfolios from the user tier.

    Two-tier model:
      user_id=None  — global context, processes only global portfolios
      user_id=<uid> — user context, processes only that user's portfolios

    The source propagation dict is never modified.
    Returns a new dict that mirrors all original keys and adds:
      portfolio_contexts      list   — context dicts, one per processed portfolio
      portfolio_impact_score  float  — max across portfolio_contexts (or 0.0)
      concentration_modifier  float  — max across portfolio_contexts (or 0.5)

    Never raises.
    """
    # Always return a new dict — the source is never mutated
    result: dict = dict(propagation)
    result.setdefault("portfolio_contexts",     [])
    result.setdefault("portfolio_impact_score", 0.0)
    result.setdefault("concentration_modifier", _CONC_MODIFIER_NONE)

    if session is None or not propagation:
        return result

    try:
        affected_portfolios: List[str] = list(propagation.get("affected_portfolios", []))

        # If no portfolios in the propagation and user_id provided, discover them
        if not affected_portfolios and user_id is not None:
            affected_portfolios = await _user_portfolio_ids(session, user_id)

        if not affected_portfolios:
            return result

        contexts: List[Dict[str, Any]] = []
        for portfolio_id in sorted(affected_portfolios):
            # Tenant isolation gate
            if not await _portfolio_belongs_to_user(session, portfolio_id, user_id):
                continue
            ctx = await compute_portfolio_scenario_impact(
                session, propagation, portfolio_id
            )
            contexts.append(ctx)

        result["portfolio_contexts"] = contexts

        if contexts:
            result["portfolio_impact_score"] = max(
                c["portfolio_impact_score"] for c in contexts
            )
            result["concentration_modifier"] = max(
                c["concentration_modifier"] for c in contexts
            )

        return result

    except Exception as exc:
        logger.debug("[portfolio_propagation] propagate_to_portfolio error: %r", exc)
        return result
