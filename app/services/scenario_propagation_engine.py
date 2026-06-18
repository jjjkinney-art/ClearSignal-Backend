"""
Scenario Propagation Engine — Phase 14 · Slice 3.

Transforms scenario seeds (produced by scenario_seed_builder) into
propagated scenario impacts.  Propagation is descriptive and conditional.
It is NOT predictive and NOT advisory.

What this module does
---------------------
  Given a seed dict, it traces how a conditional change in the seed's
  primary entity would *structurally connect* to other entities via
  cross-exposure links, similarity relationships, and portfolio co-holdings.
  The result is a transmission path and a set of impact entries that
  describe the propagation network — not an outcome prediction.

What this module does NOT do
-----------------------------
  - It does NOT predict whether the changed assumption will materialise.
  - It does NOT recommend any action.
  - It does NOT size or advise on any position.
  - It does NOT assert a target price or expected return.
  - It does NOT write to any table (pure read-only).
  - It does NOT import conviction, order, or execution modules.

SP-6 invariant: this module is a pure sink relative to all upstream tables.

Public API
----------
  propagate_scenario(session, seed)   → dict   (one seed → one propagation)
  propagate_all(session, seeds)       → list   (batch)

  Type-specific handlers (also public for direct testing):
    propagate_company_scenario(session, seed)
    propagate_macro_scenario(session, seed)
    propagate_sector_scenario(session, seed)
    propagate_catalyst_scenario(session, seed)
    propagate_failure_mode_scenario(session, seed)
    propagate_portfolio_scenario(session, seed)

Propagation output shape
------------------------
  scenario_type       str   — mirrors seed
  scenario_name       str   — mirrors seed
  transmission_path   list  — ordered [{step, cause, effect, channel}]
  direct_impacts      list  — [{entity_key, entity_type, impact_channel,
                                transmission_strength, depth=0}]
  indirect_impacts    list  — same shape, depth ∈ {1, 2}
  affected_entities   list  — deduped union of direct + indirect
  affected_portfolios list  — portfolio IDs
  impact_confidence   float — inherited from seed, decayed by depth
  impact_uncertainty  float — inherited from seed, grown by depth
  propagation_depth   int   — max depth reached (0 = direct only)
  source_versions     dict  — mirrors seed

Depth model
-----------
  depth 0 — direct:        the seed's own entity
  depth 1 — first-order:   entities linked via cross_exposure / similarity /
                            portfolio co-holding from the seed entity
  depth 2 — second-order:  entities linked from first-order entities via the
                            same channels; max depth — never exceeds 2

Missing-substrate behaviour
---------------------------
  session None    → return {}
  No links found  → sparse propagation with empty indirect lists
  Any error       → logged at debug, propagation returns {} or partial result
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_FIRST_ORDER       = 20   # cap first-order entities per seed
_MAX_SECOND_ORDER_PER  = 8    # cap second-order per first-order entity
_SIMILARITY_SCORE_FLOOR = 0.50

# Transmission strength thresholds applied to CrossExposure.strength
_STRONG_THRESHOLD   = 0.70
_MODERATE_THRESHOLD = 0.40

# Confidence decay per depth level
_CONFIDENCE_DECAY = {0: 1.0, 1: 0.75, 2: 0.55}
# Uncertainty growth per depth level (additive delta)
_UNCERTAINTY_GROWTH = {0: 0.0, 1: 0.10, 2: 0.20}

# Seed type constants (mirror scenario_seed_builder to avoid circular import)
_SEED_TYPE_COMPANY      = "company_scenario"
_SEED_TYPE_MACRO        = "macro_scenario"
_SEED_TYPE_SECTOR       = "sector_scenario"
_SEED_TYPE_CATALYST     = "catalyst_scenario"
_SEED_TYPE_FAILURE_MODE = "failure_mode_scenario"
_SEED_TYPE_PORTFOLIO    = "portfolio_scenario"


# ---------------------------------------------------------------------------
# Output constructors
# ---------------------------------------------------------------------------

def _make_impact(
    *,
    entity_key: str,
    entity_type: str = "company",
    impact_channel: str,
    transmission_strength: str,  # strong | moderate | weak
    depth: int,
) -> dict:
    return {
        "entity_key":           entity_key,
        "entity_type":          entity_type,
        "impact_channel":       impact_channel,
        "transmission_strength": transmission_strength,
        "depth":                depth,
    }


def _make_transmission_step(
    *,
    step: int,
    cause: str,
    effect: str,
    channel: str,
) -> dict:
    return {
        "step":    step,
        "cause":   cause,
        "effect":  effect,
        "channel": channel,
    }


def _make_propagation(
    *,
    scenario_type: str,
    scenario_name: str,
    transmission_path: list,
    direct_impacts: list,
    indirect_impacts: list,
    affected_entities: list,
    affected_portfolios: list,
    impact_confidence: float,
    impact_uncertainty: float,
    propagation_depth: int,
    source_versions: dict,
    user_id: Optional[str] = None,
) -> dict:
    return {
        "scenario_type":        scenario_type,
        "scenario_name":        scenario_name,
        "transmission_path":    list(transmission_path),
        "direct_impacts":       list(direct_impacts),
        "indirect_impacts":     list(indirect_impacts),
        "affected_entities":    list(affected_entities),
        "affected_portfolios":  list(affected_portfolios),
        "impact_confidence":    round(float(impact_confidence), 4),
        "impact_uncertainty":   round(float(impact_uncertainty), 4),
        "propagation_depth":    int(propagation_depth),
        "source_versions":      dict(source_versions),
        "user_id":              user_id,
    }


def _merge_impacts(direct: list, indirect: list) -> list:
    """Return deduplicated list of all impacted entities (direct first)."""
    seen: Dict[str, bool] = {}
    result = []
    for imp in direct + indirect:
        key = imp["entity_key"]
        if key not in seen:
            seen[key] = True
            result.append(imp)
    return result


# ---------------------------------------------------------------------------
# Score-to-strength mapping
# ---------------------------------------------------------------------------

def _cross_strength(raw_strength: float) -> str:
    if raw_strength >= _STRONG_THRESHOLD:
        return "strong"
    if raw_strength >= _MODERATE_THRESHOLD:
        return "moderate"
    return "weak"


def _sim_strength(score: float) -> str:
    if score >= 0.80:
        return "strong"
    if score >= 0.65:
        return "moderate"
    return "weak"


# ---------------------------------------------------------------------------
# Confidence / uncertainty inheritance
# ---------------------------------------------------------------------------

def _base_confidence(seed: dict) -> float:
    ci = seed.get("confidence_inputs", {})
    low  = ci.get("confidence_band_low", 0.0) or 0.0
    high = ci.get("confidence_band_high", 1.0) or 1.0
    mid  = low + (high - low) * 0.5
    return min(max(float(mid), 0.0), 1.0)


def _base_uncertainty(seed: dict) -> float:
    ui = seed.get("uncertainty_inputs", {})
    bw = ui.get("band_width") or ui.get("inverse_specificity")
    if bw is None:
        bw = 0.30
    return min(max(float(bw), 0.0), 1.0)


def _adjusted_confidence(seed: dict, depth: int) -> float:
    base  = _base_confidence(seed)
    decay = _CONFIDENCE_DECAY.get(depth, 0.40)
    return round(base * decay, 4)


def _adjusted_uncertainty(seed: dict, depth: int) -> float:
    base  = _base_uncertainty(seed)
    delta = _UNCERTAINTY_GROWTH.get(depth, 0.30)
    return round(min(base + delta, 1.0), 4)


# ---------------------------------------------------------------------------
# DB sub-queries  (all return sorted lists for determinism)
# ---------------------------------------------------------------------------

async def _cross_exposed(
    session,
    ticker: str,
    limit: int = _MAX_FIRST_ORDER,
) -> List[Tuple[str, str, str]]:
    """Return sorted [(other_ticker, strength_label, exposure_type)] for *ticker*."""
    if not ticker:
        return []
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
            label = _cross_strength(float(row.strength))
            etype = row.exposure_type or "cross_exposure"
            result.append((other, label, etype))
        # Secondary sort: alphabetical on ticker for full determinism
        return sorted(result, key=lambda x: (-["weak","moderate","strong"].index(x[1]), x[0]))
    except Exception as exc:
        logger.debug("[propagation] _cross_exposed(%s) error: %r", ticker, exc)
        return []


async def _similar_tickers(
    session,
    ticker: str,
    user_id: Optional[str],
    limit: int = 10,
) -> List[Tuple[str, str]]:
    """Return sorted [(other_ticker, strength_label)] for floor-passed similarity."""
    if not ticker:
        return []
    try:
        from app.db.repositories import similarity_repo

        edges = await similarity_repo.list_similarity_edges(
            session,
            query_key=ticker,
            user_id=user_id,
            floor_passed_only=True,
            limit=limit,
        )
        result = [
            (e.candidate_key, _sim_strength(float(e.score)))
            for e in (edges or [])
            if e.candidate_key != ticker and float(e.score) >= _SIMILARITY_SCORE_FLOOR
        ]
        return sorted(result, key=lambda x: (x[0],))
    except Exception as exc:
        logger.debug("[propagation] _similar_tickers(%s) error: %r", ticker, exc)
        return []


async def _portfolio_cotickers(
    session,
    ticker: str,
    limit: int = 20,
) -> List[Tuple[str, str]]:
    """Return sorted [(other_ticker, portfolio_id)] for co-holdings with *ticker*."""
    if not ticker:
        return []
    try:
        from app.db.repositories import portfolio_repo

        positions = await portfolio_repo.position_list_by_ticker(
            session, ticker, active_only=True
        )
        result: List[Tuple[str, str]] = []
        seen: Dict[str, bool] = {}
        for pos in (positions or []):
            co_positions = await portfolio_repo.position_list(
                session, portfolio_id=pos.portfolio_id
            )
            for cp in (co_positions or []):
                if not cp.active or cp.ticker == ticker:
                    continue
                key = (cp.ticker, pos.portfolio_id)
                if key not in seen:
                    seen[key] = True  # type: ignore[assignment]
                    result.append((cp.ticker, pos.portfolio_id))
                if len(result) >= limit:
                    return sorted(result, key=lambda x: x[0])
        return sorted(result, key=lambda x: x[0])
    except Exception as exc:
        logger.debug("[propagation] _portfolio_cotickers(%s) error: %r", ticker, exc)
        return []


async def _portfolio_ids_holding(
    session,
    ticker: str,
) -> List[str]:
    """Return sorted portfolio IDs that hold *ticker*."""
    if not ticker:
        return []
    try:
        from app.db.repositories import portfolio_repo
        positions = await portfolio_repo.position_list_by_ticker(
            session, ticker, active_only=True
        )
        ids = sorted({p.portfolio_id for p in (positions or [])})
        return ids
    except Exception as exc:
        logger.debug("[propagation] _portfolio_ids_holding(%s) error: %r", ticker, exc)
        return []


# ---------------------------------------------------------------------------
# Shared first-order expansion helper
# ---------------------------------------------------------------------------

async def _expand_first_order(
    session,
    ticker: str,
    user_id: Optional[str],
    step_offset: int,
    max_entities: int = _MAX_FIRST_ORDER,
) -> Tuple[List[dict], List[dict], int]:
    """Expand one ticker to its first-order impacts and transmission steps.

    Returns (first_order_impacts, transmission_steps, step_counter).
    """
    impacts: List[dict] = []
    steps:   List[dict] = []
    step     = step_offset
    seen:    Dict[str, bool] = {}

    cross = await _cross_exposed(session, ticker, limit=max_entities)
    for other, strength, exposure_type in cross:
        if other in seen or len(impacts) >= max_entities:
            break
        seen[other] = True
        impacts.append(_make_impact(
            entity_key           = other,
            entity_type          = "company",
            impact_channel       = "cross_exposure",
            transmission_strength= strength,
            depth                = 1,
        ))
        steps.append(_make_transmission_step(
            step    = step,
            cause   = ticker,
            effect  = other,
            channel = f"cross_exposure:{exposure_type}",
        ))
        step += 1

    similar = await _similar_tickers(session, ticker, user_id, limit=10)
    for other, strength in similar:
        if other in seen or len(impacts) >= max_entities:
            break
        seen[other] = True
        impacts.append(_make_impact(
            entity_key           = other,
            entity_type          = "company",
            impact_channel       = "similarity",
            transmission_strength= strength,
            depth                = 1,
        ))
        steps.append(_make_transmission_step(
            step    = step,
            cause   = ticker,
            effect  = other,
            channel = "similarity",
        ))
        step += 1

    cotickers = await _portfolio_cotickers(session, ticker, limit=10)
    for other, portfolio_id in cotickers:
        if other in seen or len(impacts) >= max_entities:
            break
        seen[other] = True
        impacts.append(_make_impact(
            entity_key           = other,
            entity_type          = "company",
            impact_channel       = "portfolio",
            transmission_strength= "moderate",
            depth                = 1,
        ))
        steps.append(_make_transmission_step(
            step    = step,
            cause   = ticker,
            effect  = other,
            channel = f"portfolio:{portfolio_id}",
        ))
        step += 1

    return impacts, steps, step


async def _expand_second_order(
    session,
    first_order_impacts: list,
    exclude_tickers: frozenset,
    user_id: Optional[str],
    step_offset: int,
) -> Tuple[List[dict], List[dict]]:
    """Expand first-order impacts to second-order via cross_exposure only."""
    impacts: List[dict] = []
    steps:   List[dict] = []
    step    = step_offset
    seen:   Dict[str, bool] = {}

    for fo_impact in first_order_impacts[:_MAX_FIRST_ORDER]:
        fo_ticker = fo_impact["entity_key"]
        cross = await _cross_exposed(
            session, fo_ticker, limit=_MAX_SECOND_ORDER_PER
        )
        for other, strength, exposure_type in cross:
            if other in seen or other in exclude_tickers:
                continue
            seen[other] = True
            impacts.append(_make_impact(
                entity_key           = other,
                entity_type          = "company",
                impact_channel       = "cross_exposure",
                transmission_strength= "weak",  # decayed by depth
                depth                = 2,
            ))
            steps.append(_make_transmission_step(
                step    = step,
                cause   = fo_ticker,
                effect  = other,
                channel = f"cross_exposure:{exposure_type}",
            ))
            step += 1

    return impacts, steps


# ---------------------------------------------------------------------------
# propagate_company_scenario
# ---------------------------------------------------------------------------

async def propagate_company_scenario(session, seed: dict) -> dict:
    """Propagate a company_scenario seed to impacted entities."""
    try:
        ticker   = seed.get("ticker", "")
        user_id  = seed.get("user_id")
        ti       = seed.get("transmission_inputs", {})
        direction = ti.get("direction", "changing")
        ftype    = ti.get("forecast_type", "").replace("_", " ")
        horizon  = ti.get("horizon", "")

        # ── Step 0: direct impact ──
        direct = [_make_impact(
            entity_key           = ticker or seed.get("entity_id", ""),
            entity_type          = "company",
            impact_channel       = "direct",
            transmission_strength= "strong",
            depth                = 0,
        )]
        path = [_make_transmission_step(
            step    = 0,
            cause   = seed.get("changed_assumption", ""),
            effect  = f"{ticker} {ftype} thesis is conditionally {direction}",
            channel = "direct",
        )]

        # ── First order ──
        fo_impacts, fo_steps, next_step = await _expand_first_order(
            session, ticker, user_id, step_offset=1
        )

        # ── Second order ──
        exclude = frozenset([ticker] + [i["entity_key"] for i in fo_impacts])
        so_impacts, so_steps = await _expand_second_order(
            session, fo_impacts, exclude, user_id, step_offset=next_step
        )

        all_indirect = fo_impacts + so_impacts
        path.extend(fo_steps + so_steps)

        max_depth = 2 if so_impacts else (1 if fo_impacts else 0)

        # ── Portfolios ──
        portfolios = sorted(set(
            seed.get("affected_portfolios", [])
            + await _portfolio_ids_holding(session, ticker)
        ))

        return _make_propagation(
            scenario_type       = seed["scenario_type"],
            scenario_name       = seed["scenario_name"],
            transmission_path   = path,
            direct_impacts      = direct,
            indirect_impacts    = all_indirect,
            affected_entities   = _merge_impacts(direct, all_indirect),
            affected_portfolios = portfolios,
            impact_confidence   = _adjusted_confidence(seed, max_depth),
            impact_uncertainty  = _adjusted_uncertainty(seed, max_depth),
            propagation_depth   = max_depth,
            source_versions     = seed.get("source_versions", {}),
            user_id             = user_id,
        )
    except Exception as exc:
        logger.debug("[propagation] propagate_company_scenario error: %r", exc)
        return {}


# ---------------------------------------------------------------------------
# propagate_macro_scenario
# ---------------------------------------------------------------------------

async def propagate_macro_scenario(session, seed: dict) -> dict:
    """Propagate a macro_scenario seed.

    Macro changes are broad: first-order = all watchlist tickers.
    Second-order is skipped to avoid an explosion across the full watchlist.
    """
    try:
        user_id   = seed.get("user_id")
        ti        = seed.get("transmission_inputs", {})
        macro_key = ti.get("macro_key", seed.get("entity_id", ""))
        direction = ti.get("direction", "shifting")
        ftype     = ti.get("forecast_type", "").replace("_", " ")
        horizon   = ti.get("horizon", "")

        # ── Direct ──
        direct = [_make_impact(
            entity_key           = macro_key,
            entity_type          = "macro",
            impact_channel       = "direct",
            transmission_strength= "strong",
            depth                = 0,
        )]
        path = [_make_transmission_step(
            step    = 0,
            cause   = seed.get("changed_assumption", ""),
            effect  = f"Macro condition {macro_key} is conditionally {direction}",
            channel = "direct",
        )]

        # ── First order: tickers from seed's affected_tickers (watchlist + portfolio) ──
        affected = sorted(seed.get("affected_tickers", []))[:_MAX_FIRST_ORDER]
        fo_impacts = []
        for idx, ticker in enumerate(affected):
            fo_impacts.append(_make_impact(
                entity_key           = ticker,
                entity_type          = "company",
                impact_channel       = "macro_transmission",
                transmission_strength= "moderate",
                depth                = 1,
            ))
            path.append(_make_transmission_step(
                step    = idx + 1,
                cause   = macro_key,
                effect  = ticker,
                channel = f"macro_transmission:{ftype}",
            ))

        max_depth = 1 if fo_impacts else 0

        # ── Portfolios ──
        portfolios = sorted(set(seed.get("affected_portfolios", [])))

        return _make_propagation(
            scenario_type       = seed["scenario_type"],
            scenario_name       = seed["scenario_name"],
            transmission_path   = path,
            direct_impacts      = direct,
            indirect_impacts    = fo_impacts,
            affected_entities   = _merge_impacts(direct, fo_impacts),
            affected_portfolios = portfolios,
            impact_confidence   = _adjusted_confidence(seed, max_depth),
            impact_uncertainty  = _adjusted_uncertainty(seed, max_depth),
            propagation_depth   = max_depth,
            source_versions     = seed.get("source_versions", {}),
            user_id             = user_id,
        )
    except Exception as exc:
        logger.debug("[propagation] propagate_macro_scenario error: %r", exc)
        return {}


# ---------------------------------------------------------------------------
# propagate_sector_scenario
# ---------------------------------------------------------------------------

async def propagate_sector_scenario(session, seed: dict) -> dict:
    """Propagate a sector_scenario seed.

    Sector changes propagate to cross-exposed tickers first; second-order
    via similarity from those tickers.
    """
    try:
        user_id    = seed.get("user_id")
        ti         = seed.get("transmission_inputs", {})
        sector_key = ti.get("sector_key", seed.get("entity_id", ""))
        direction  = ti.get("direction", "shifting")
        ftype      = ti.get("forecast_type", "").replace("_", " ")

        # ── Direct ──
        direct = [_make_impact(
            entity_key           = sector_key,
            entity_type          = "sector",
            impact_channel       = "direct",
            transmission_strength= "strong",
            depth                = 0,
        )]
        path = [_make_transmission_step(
            step    = 0,
            cause   = seed.get("changed_assumption", ""),
            effect  = f"Sector {sector_key} {ftype} is conditionally {direction}",
            channel = "direct",
        )]

        # ── First order: cross-exposed tickers from seed ──
        cross_tickers = sorted(ti.get("cross_tickers", seed.get("affected_tickers", [])))
        fo_impacts = []
        for idx, ticker in enumerate(cross_tickers[:_MAX_FIRST_ORDER]):
            fo_impacts.append(_make_impact(
                entity_key           = ticker,
                entity_type          = "company",
                impact_channel       = "sector_transmission",
                transmission_strength= "moderate",
                depth                = 1,
            ))
            path.append(_make_transmission_step(
                step    = idx + 1,
                cause   = sector_key,
                effect  = ticker,
                channel = f"sector_transmission:{ftype}",
            ))

        # ── Second order: similarity from first-order tickers ──
        so_impacts: List[dict] = []
        so_steps:   List[dict] = []
        seen = frozenset([sector_key] + [i["entity_key"] for i in fo_impacts])
        step = len(path)
        for fo_impact in fo_impacts[:5]:
            similar = await _similar_tickers(
                session, fo_impact["entity_key"], user_id, limit=4
            )
            for other, _ in similar:
                if other in seen:
                    continue
                seen = seen | {other}
                so_impacts.append(_make_impact(
                    entity_key           = other,
                    entity_type          = "company",
                    impact_channel       = "similarity",
                    transmission_strength= "weak",
                    depth                = 2,
                ))
                so_steps.append(_make_transmission_step(
                    step    = step,
                    cause   = fo_impact["entity_key"],
                    effect  = other,
                    channel = "similarity",
                ))
                step += 1

        all_indirect = fo_impacts + so_impacts
        path.extend(so_steps)
        max_depth = 2 if so_impacts else (1 if fo_impacts else 0)

        portfolios = sorted(set(seed.get("affected_portfolios", [])))

        return _make_propagation(
            scenario_type       = seed["scenario_type"],
            scenario_name       = seed["scenario_name"],
            transmission_path   = path,
            direct_impacts      = direct,
            indirect_impacts    = all_indirect,
            affected_entities   = _merge_impacts(direct, all_indirect),
            affected_portfolios = portfolios,
            impact_confidence   = _adjusted_confidence(seed, max_depth),
            impact_uncertainty  = _adjusted_uncertainty(seed, max_depth),
            propagation_depth   = max_depth,
            source_versions     = seed.get("source_versions", {}),
            user_id             = user_id,
        )
    except Exception as exc:
        logger.debug("[propagation] propagate_sector_scenario error: %r", exc)
        return {}


# ---------------------------------------------------------------------------
# propagate_catalyst_scenario
# ---------------------------------------------------------------------------

async def propagate_catalyst_scenario(session, seed: dict) -> dict:
    """Propagate a catalyst_scenario seed.

    Catalyst changes propagate directly from the catalyst ticker via
    cross-exposure (first-order) and then similarity (second-order).
    """
    try:
        ticker  = seed.get("ticker", "")
        user_id = seed.get("user_id")
        ti      = seed.get("transmission_inputs", {})
        direction = ti.get("direction", "open")
        window    = ti.get("expected_window", "unspecified")

        direct = [_make_impact(
            entity_key           = ticker or seed.get("entity_id", ""),
            entity_type          = "company",
            impact_channel       = "direct",
            transmission_strength= "strong",
            depth                = 0,
        )]
        path = [_make_transmission_step(
            step    = 0,
            cause   = seed.get("changed_assumption", ""),
            effect  = f"{ticker} catalyst ({direction}) conditionally triggers within {window}",
            channel = "direct",
        )]

        fo_impacts, fo_steps, next_step = await _expand_first_order(
            session, ticker, user_id, step_offset=1
        )

        exclude = frozenset([ticker] + [i["entity_key"] for i in fo_impacts])
        so_impacts, so_steps = await _expand_second_order(
            session, fo_impacts, exclude, user_id, step_offset=next_step
        )

        all_indirect = fo_impacts + so_impacts
        path.extend(fo_steps + so_steps)
        max_depth = 2 if so_impacts else (1 if fo_impacts else 0)

        portfolios = sorted(set(
            seed.get("affected_portfolios", [])
            + await _portfolio_ids_holding(session, ticker)
        ))

        return _make_propagation(
            scenario_type       = seed["scenario_type"],
            scenario_name       = seed["scenario_name"],
            transmission_path   = path,
            direct_impacts      = direct,
            indirect_impacts    = all_indirect,
            affected_entities   = _merge_impacts(direct, all_indirect),
            affected_portfolios = portfolios,
            impact_confidence   = _adjusted_confidence(seed, max_depth),
            impact_uncertainty  = _adjusted_uncertainty(seed, max_depth),
            propagation_depth   = max_depth,
            source_versions     = seed.get("source_versions", {}),
            user_id             = user_id,
        )
    except Exception as exc:
        logger.debug("[propagation] propagate_catalyst_scenario error: %r", exc)
        return {}


# ---------------------------------------------------------------------------
# propagate_failure_mode_scenario
# ---------------------------------------------------------------------------

async def propagate_failure_mode_scenario(session, seed: dict) -> dict:
    """Propagate a failure_mode_scenario seed.

    Failure-mode changes propagate from the primary company via cross-exposure
    (first-order) and then portfolio co-holdings (second-order).
    """
    try:
        ticker   = seed.get("ticker", "")
        user_id  = seed.get("user_id")
        ti       = seed.get("transmission_inputs", {})
        stage    = ti.get("sequence_stage", "?")
        analog   = ti.get("analog_id", "")

        direct = [_make_impact(
            entity_key           = ticker or seed.get("entity_id", ""),
            entity_type          = "company",
            impact_channel       = "direct",
            transmission_strength= "strong",
            depth                = 0,
        )]
        path = [_make_transmission_step(
            step    = 0,
            cause   = seed.get("changed_assumption", ""),
            effect  = (
                f"{ticker} conditionally follows {analog} failure-mode trajectory "
                f"at stage {stage}"
            ),
            channel = "direct",
        )]

        fo_impacts, fo_steps, next_step = await _expand_first_order(
            session, ticker, user_id, step_offset=1
        )

        exclude = frozenset([ticker] + [i["entity_key"] for i in fo_impacts])
        so_impacts, so_steps = await _expand_second_order(
            session, fo_impacts, exclude, user_id, step_offset=next_step
        )

        all_indirect = fo_impacts + so_impacts
        path.extend(fo_steps + so_steps)
        max_depth = 2 if so_impacts else (1 if fo_impacts else 0)

        portfolios = sorted(set(
            seed.get("affected_portfolios", [])
            + await _portfolio_ids_holding(session, ticker)
        ))

        return _make_propagation(
            scenario_type       = seed["scenario_type"],
            scenario_name       = seed["scenario_name"],
            transmission_path   = path,
            direct_impacts      = direct,
            indirect_impacts    = all_indirect,
            affected_entities   = _merge_impacts(direct, all_indirect),
            affected_portfolios = portfolios,
            impact_confidence   = _adjusted_confidence(seed, max_depth),
            impact_uncertainty  = _adjusted_uncertainty(seed, max_depth),
            propagation_depth   = max_depth,
            source_versions     = seed.get("source_versions", {}),
            user_id             = user_id,
        )
    except Exception as exc:
        logger.debug("[propagation] propagate_failure_mode_scenario error: %r", exc)
        return {}


# ---------------------------------------------------------------------------
# propagate_portfolio_scenario
# ---------------------------------------------------------------------------

async def propagate_portfolio_scenario(session, seed: dict) -> dict:
    """Propagate a portfolio_scenario seed.

    Portfolio changes propagate from the portfolio entity to its component
    tickers (first-order) and then to cross-exposures of those tickers
    (second-order).
    """
    try:
        portfolio_id = seed.get("entity_id", "")
        user_id      = seed.get("user_id")
        ti           = seed.get("transmission_inputs", {})
        port_name    = ti.get("portfolio_name", portfolio_id)
        tickers      = sorted(ti.get("tickers", seed.get("affected_tickers", [])))

        direct = [_make_impact(
            entity_key           = portfolio_id,
            entity_type          = "portfolio",
            impact_channel       = "direct",
            transmission_strength= "strong",
            depth                = 0,
        )]
        path = [_make_transmission_step(
            step    = 0,
            cause   = seed.get("changed_assumption", ""),
            effect  = (
                f"Portfolio '{port_name}' conditionally affected by a shared "
                f"macro or sector condition across its {len(tickers)} positions"
            ),
            channel = "direct",
        )]

        # ── First order: each position in the portfolio ──
        fo_impacts = []
        for idx, ticker in enumerate(tickers[:_MAX_FIRST_ORDER]):
            fo_impacts.append(_make_impact(
                entity_key           = ticker,
                entity_type          = "company",
                impact_channel       = "portfolio",
                transmission_strength= "moderate",
                depth                = 1,
            ))
            path.append(_make_transmission_step(
                step    = idx + 1,
                cause   = portfolio_id,
                effect  = ticker,
                channel = f"portfolio:{portfolio_id}",
            ))

        # ── Second order: cross-exposures from first-order tickers ──
        exclude = frozenset([portfolio_id] + tickers)
        so_impacts, so_steps = await _expand_second_order(
            session, fo_impacts, exclude, user_id, step_offset=len(path)
        )

        all_indirect = fo_impacts + so_impacts
        path.extend(so_steps)
        max_depth = 2 if so_impacts else (1 if fo_impacts else 0)

        portfolios = sorted(set(seed.get("affected_portfolios", [portfolio_id])))

        return _make_propagation(
            scenario_type       = seed["scenario_type"],
            scenario_name       = seed["scenario_name"],
            transmission_path   = path,
            direct_impacts      = direct,
            indirect_impacts    = all_indirect,
            affected_entities   = _merge_impacts(direct, all_indirect),
            affected_portfolios = portfolios,
            impact_confidence   = _adjusted_confidence(seed, max_depth),
            impact_uncertainty  = _adjusted_uncertainty(seed, max_depth),
            propagation_depth   = max_depth,
            source_versions     = seed.get("source_versions", {}),
            user_id             = user_id,
        )
    except Exception as exc:
        logger.debug("[propagation] propagate_portfolio_scenario error: %r", exc)
        return {}


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

_HANDLERS = {
    _SEED_TYPE_COMPANY:      propagate_company_scenario,
    _SEED_TYPE_MACRO:        propagate_macro_scenario,
    _SEED_TYPE_SECTOR:       propagate_sector_scenario,
    _SEED_TYPE_CATALYST:     propagate_catalyst_scenario,
    _SEED_TYPE_FAILURE_MODE: propagate_failure_mode_scenario,
    _SEED_TYPE_PORTFOLIO:    propagate_portfolio_scenario,
}


async def propagate_scenario(session, seed: dict) -> dict:
    """Propagate one scenario seed into a propagation result dict.

    Returns {} when session is None or when the seed type is unrecognised.
    Never raises.
    """
    if session is None:
        return {}
    if not seed:
        return {}
    try:
        handler = _HANDLERS.get(seed.get("scenario_type", ""))
        if handler is None:
            return {}
        return await handler(session, seed)
    except Exception as exc:
        logger.debug("[propagation] propagate_scenario outer error: %r", exc)
        return {}


async def propagate_all(session, seeds: list) -> List[dict]:
    """Propagate a list of seeds; returns a list of non-empty propagation dicts.

    Skips empty seeds and seeds with unrecognised types.
    Never raises.
    """
    if session is None:
        return []
    results: List[dict] = []
    for seed in (seeds or []):
        try:
            result = await propagate_scenario(session, seed)
            if result:
                results.append(result)
        except Exception as exc:
            logger.debug("[propagation] propagate_all item error: %r", exc)
    return results
