"""
Scenario Seed Builder — Phase 14 · Slice 2.

Builds read-only scenario seeds from existing intelligence substrates.
No propagation, no scoring, no writes of any kind.

Each seed is a plain Python dict that captures the raw conditional-change
signal and the structured inputs the impact/explainability engine (Slices
14.3–14.5) will use to produce a full ScenarioSnapshot.

Seed types
----------
  company_scenario      — directional shift in a company-level forecast vector
  macro_scenario        — directional shift in a macro-level forecast vector
  sector_scenario       — directional shift in a sector-level forecast vector
  catalyst_scenario     — open dossier_catalyst row (event-driven trigger)
  failure_mode_scenario — active dossier_failure_mode row (risk-mode trigger)
  portfolio_scenario    — portfolio with active positions (cross-holding change)

Seed envelope (all six types share this shape)
----------------------------------------------
  scenario_type         str   — one of the six types above
  entity_type           str   — company | macro | sector | portfolio | failure_mode
  entity_id             str   — primary key of the source row
  ticker                str   — ticker symbol or ""
  scenario_name         str   — one-line human-readable condition label
  changed_assumption    str   — what assumption is shifting ("the if")
  source_type           str   — originating table name
  source_id             str   — PK of the originating row
  affected_tickers      list  — tickers downstream of this seed
  affected_portfolios   list  — portfolio IDs that hold affected tickers
  evidence_refs         list  — [{source_type, source_id, description}]
  transmission_inputs   dict  — raw inputs for transmission-path analysis (Slice 14.3)
  impact_inputs         dict  — raw inputs for impact-band model (Slice 14.5)
  confidence_inputs     dict  — inherited confidence from upstream substrates
  uncertainty_inputs    dict  — inherited uncertainty from upstream substrates
  source_versions       dict  — {table: row_id} for staleness detection
  user_id               str | None — pass-through scoping; no logic applied here

Missing-substrate behaviour
---------------------------
  Session None           → return []
  Missing primary row    → skip; no seed produced
  Missing secondary data → sparse seed with empty lists / zero-values
  Any unexpected error   → logged at debug level, sub-builder returns []

Safety invariants (SP-6)
------------------------
  - This module NEVER writes to any table whatsoever.
  - No import from conviction, recommendation, order, execution, delivery,
    or stance service modules.
  - No target-price, buy/sell/hold, position-size, trade, or advice field.
  - Forecast, decision, and similarity data are READ ONLY here.
    scenario_repo is NOT imported; no ScenarioSnapshot rows are created.
  - Seeds are inputs to later slices (14.3+), not outputs to users.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed type constants
# ---------------------------------------------------------------------------

SEED_TYPE_COMPANY      = "company_scenario"
SEED_TYPE_MACRO        = "macro_scenario"
SEED_TYPE_SECTOR       = "sector_scenario"
SEED_TYPE_CATALYST     = "catalyst_scenario"
SEED_TYPE_FAILURE_MODE = "failure_mode_scenario"
SEED_TYPE_PORTFOLIO    = "portfolio_scenario"

ALL_SEED_TYPES = (
    SEED_TYPE_COMPANY,
    SEED_TYPE_MACRO,
    SEED_TYPE_SECTOR,
    SEED_TYPE_CATALYST,
    SEED_TYPE_FAILURE_MODE,
    SEED_TYPE_PORTFOLIO,
)

# ---------------------------------------------------------------------------
# Per-sub-builder row limits
# ---------------------------------------------------------------------------

_LIMIT_FORECAST       = 200
_LIMIT_CATALYST       = 100
_LIMIT_FAILURE_MODE   = 100
_LIMIT_PORTFOLIO      = 500
_LIMIT_SIMILARITY     = 50
_LIMIT_CROSS_EXPOSURE = 20

# Forecast directional-signal floor — vectors weaker than this are skipped
_FORECAST_SIGNAL_FLOOR = 0.50


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Target eligibility
# ---------------------------------------------------------------------------

def _parse_targets(targets_str: str) -> Optional[frozenset]:
    """Return a frozenset of allowed tickers, or None (= all tickers allowed)."""
    if not targets_str or not targets_str.strip():
        return None
    return frozenset(t.strip().upper() for t in targets_str.split(",") if t.strip())


def _ticker_allowed(ticker: str, allowed: Optional[frozenset]) -> bool:
    if allowed is None:
        return True
    return bool(ticker) and ticker.upper() in allowed


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _days_since(dt) -> Optional[int]:
    if dt is None:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (_now() - dt).days)
    except Exception:
        return None


def _make_seed(
    *,
    scenario_type: str,
    entity_type: str,
    entity_id: str,
    ticker: str,
    scenario_name: str,
    changed_assumption: str,
    source_type: str,
    source_id: str,
    affected_tickers: list,
    affected_portfolios: list,
    evidence_refs: list,
    transmission_inputs: dict,
    impact_inputs: dict,
    confidence_inputs: dict,
    uncertainty_inputs: dict,
    source_versions: dict,
    user_id: Optional[str] = None,
) -> dict:
    return {
        "scenario_type":       scenario_type,
        "entity_type":         entity_type,
        "entity_id":           entity_id,
        "ticker":              ticker,
        "scenario_name":       scenario_name,
        "changed_assumption":  changed_assumption,
        "source_type":         source_type,
        "source_id":           source_id,
        "affected_tickers":    list(affected_tickers),
        "affected_portfolios": list(affected_portfolios),
        "evidence_refs":       list(evidence_refs),
        "transmission_inputs": dict(transmission_inputs),
        "impact_inputs":       dict(impact_inputs),
        "confidence_inputs":   dict(confidence_inputs),
        "uncertainty_inputs":  dict(uncertainty_inputs),
        "source_versions":     dict(source_versions),
        "user_id":             user_id,
    }


# ---------------------------------------------------------------------------
# Secondary substrate helpers
# ---------------------------------------------------------------------------

async def _portfolios_holding(session, ticker: str) -> List[str]:
    """Return portfolio IDs with an active position in *ticker*. Never raises."""
    if session is None or not ticker:
        return []
    try:
        from app.db.repositories import portfolio_repo
        positions = await portfolio_repo.position_list_by_ticker(
            session, ticker, active_only=True
        )
        return [p.portfolio_id for p in (positions or [])]
    except Exception:
        return []


async def _affected_tickers_from_cross_exposure(session, ticker: str) -> List[str]:
    """Return tickers cross-exposed to *ticker*. Never raises."""
    if session is None or not ticker:
        return []
    try:
        from sqlalchemy import select
        from app.db.models import CrossExposure

        stmt = select(CrossExposure).where(
            (CrossExposure.ticker_a == ticker.upper()) |
            (CrossExposure.ticker_b == ticker.upper())
        ).limit(_LIMIT_CROSS_EXPOSURE)
        rows = (await session.execute(stmt)).scalars().all()
        ticker_up = ticker.upper()
        result = []
        for row in rows:
            other = row.ticker_b if row.ticker_a == ticker_up else row.ticker_a
            if other and other not in result:
                result.append(other)
        return result
    except Exception:
        return []


async def _affected_tickers_from_similarity(
    session, entity_key: str, user_id: Optional[str]
) -> List[str]:
    """Return similar tickers for *entity_key* from floor-passed similarity edges."""
    if session is None:
        return []
    try:
        from app.db.repositories import similarity_repo
        edges = await similarity_repo.list_similarity_edges(
            session,
            query_key=entity_key,
            user_id=user_id,
            floor_passed_only=True,
            limit=_LIMIT_SIMILARITY,
        )
        return [e.candidate_key for e in (edges or []) if e.candidate_key != entity_key]
    except Exception:
        return []


async def _portfolio_tickers(session, portfolio_id: str) -> List[str]:
    """Return active tickers in a portfolio. Never raises."""
    if session is None:
        return []
    try:
        from app.db.repositories import portfolio_repo
        positions = await portfolio_repo.position_list(session, portfolio_id=portfolio_id)
        return [p.ticker for p in (positions or []) if p.active and p.ticker]
    except Exception:
        return []


async def _watchlist_tickers(session, user_id: Optional[str]) -> List[str]:
    """Return active watchlist tickers for user. Never raises."""
    if session is None:
        return []
    try:
        from app.db.repositories import watchlist_repo
        rows = await watchlist_repo.ticker_list_active(session, user_id=user_id)
        return [r.ticker for r in (rows or []) if r.ticker]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Sub-builder: company_scenario
# ---------------------------------------------------------------------------

async def _build_company_seeds(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One seed per company-type ForecastVector with directional signal >= floor."""
    results: List[dict] = []
    try:
        from app.db.repositories import forecast_repo

        vectors = await forecast_repo.list_forecast_vectors(
            session,
            entity_type="company",
            user_id=user_id,
            limit=_LIMIT_FORECAST,
        )
        for v in (vectors or []):
            ticker = v.entity_key
            if not _ticker_allowed(ticker, allowed):
                continue

            p_max = max(v.p_positive, v.p_negative)
            if p_max < _FORECAST_SIGNAL_FLOOR:
                continue

            direction = "strengthening" if v.p_positive >= v.p_negative else "weakening"
            ftype = v.forecast_type.replace("_", " ")
            scenario_name = (
                f"{ticker} {ftype} {direction} scenario ({v.horizon})"
            )
            changed_assumption = (
                f"If {ticker} {ftype} shifts {direction} over {v.horizon}"
            )

            evidence_items = await forecast_repo.list_forecast_evidence(
                session, forecast_id=v.id, limit=10
            )
            evidence_refs = [
                {
                    "source_type": e.source_type,
                    "source_id": e.source_id,
                    "description": e.description,
                }
                for e in (evidence_items or [])
            ]

            similar_tickers = await _affected_tickers_from_similarity(
                session, ticker, user_id
            )
            cross_tickers = await _affected_tickers_from_cross_exposure(session, ticker)
            affected_tickers = list(dict.fromkeys(similar_tickers + cross_tickers))

            affected_portfolios = await _portfolios_holding(session, ticker)

            results.append(_make_seed(
                scenario_type      = SEED_TYPE_COMPANY,
                entity_type        = "company",
                entity_id          = v.entity_key,
                ticker             = ticker,
                scenario_name      = scenario_name,
                changed_assumption = changed_assumption,
                source_type        = "forecast_vector",
                source_id          = v.id,
                affected_tickers   = affected_tickers,
                affected_portfolios= affected_portfolios,
                evidence_refs      = evidence_refs,
                transmission_inputs= {
                    "direction":    direction,
                    "horizon":      v.horizon,
                    "horizon_days": v.horizon_days,
                    "forecast_type":v.forecast_type,
                    "similar_tickers":   similar_tickers,
                    "cross_tickers":     cross_tickers,
                },
                impact_inputs      = {
                    "p_positive":          v.p_positive,
                    "p_negative":          v.p_negative,
                    "p_neutral":           v.p_neutral,
                    "confidence_band_low": v.confidence_band_low,
                    "confidence_band_high":v.confidence_band_high,
                    "forecast_type":       v.forecast_type,
                    "direction":           direction,
                },
                confidence_inputs  = {
                    "confidence_band_low":  v.confidence_band_low,
                    "confidence_band_high": v.confidence_band_high,
                    "p_max":                p_max,
                    "evidence_count":       len(evidence_refs),
                    "forecast_schema":      v.forecast_schema,
                },
                uncertainty_inputs = {
                    "band_width":           v.confidence_band_high - v.confidence_band_low,
                    "p_neutral":            v.p_neutral,
                    "built_days_ago":       _days_since(v.built_at),
                },
                source_versions    = dict(v.source_versions or {}),
                user_id            = user_id,
            ))
    except Exception as exc:
        logger.debug("[scenario_seed_builder] company sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Sub-builder: macro_scenario
# ---------------------------------------------------------------------------

async def _build_macro_seeds(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One seed per macro-type ForecastVector with directional signal >= floor."""
    results: List[dict] = []
    try:
        from app.db.repositories import forecast_repo

        vectors = await forecast_repo.list_forecast_vectors(
            session,
            entity_type="macro",
            user_id=user_id,
            limit=_LIMIT_FORECAST,
        )
        watchlist = await _watchlist_tickers(session, user_id)

        for v in (vectors or []):
            p_max = max(v.p_positive, v.p_negative)
            if p_max < _FORECAST_SIGNAL_FLOOR:
                continue

            direction = "accelerating" if v.p_positive >= v.p_negative else "decelerating"
            ftype = v.forecast_type.replace("_", " ")
            macro_key = v.entity_key
            scenario_name = f"Macro {macro_key} {ftype} {direction} ({v.horizon})"
            changed_assumption = (
                f"If macro condition {macro_key} shifts {direction} over {v.horizon}"
            )

            evidence_items = await forecast_repo.list_forecast_evidence(
                session, forecast_id=v.id, limit=10
            )
            evidence_refs = [
                {
                    "source_type": e.source_type,
                    "source_id": e.source_id,
                    "description": e.description,
                }
                for e in (evidence_items or [])
            ]

            # Macro affects all watchlist and portfolio tickers
            affected_tickers = list(watchlist)

            # Portfolios that hold any of those tickers
            portfolio_ids: List[str] = []
            for t in affected_tickers[:10]:
                for pid in await _portfolios_holding(session, t):
                    if pid not in portfolio_ids:
                        portfolio_ids.append(pid)

            results.append(_make_seed(
                scenario_type      = SEED_TYPE_MACRO,
                entity_type        = "macro",
                entity_id          = macro_key,
                ticker             = "",
                scenario_name      = scenario_name,
                changed_assumption = changed_assumption,
                source_type        = "forecast_vector",
                source_id          = v.id,
                affected_tickers   = affected_tickers,
                affected_portfolios= portfolio_ids,
                evidence_refs      = evidence_refs,
                transmission_inputs= {
                    "direction":     direction,
                    "horizon":       v.horizon,
                    "horizon_days":  v.horizon_days,
                    "forecast_type": v.forecast_type,
                    "macro_key":     macro_key,
                    "watchlist_count": len(watchlist),
                },
                impact_inputs      = {
                    "p_positive":           v.p_positive,
                    "p_negative":           v.p_negative,
                    "p_neutral":            v.p_neutral,
                    "confidence_band_low":  v.confidence_band_low,
                    "confidence_band_high": v.confidence_band_high,
                    "direction":            direction,
                    "macro_key":            macro_key,
                },
                confidence_inputs  = {
                    "confidence_band_low":  v.confidence_band_low,
                    "confidence_band_high": v.confidence_band_high,
                    "p_max":                p_max,
                    "evidence_count":       len(evidence_refs),
                    "forecast_schema":      v.forecast_schema,
                },
                uncertainty_inputs = {
                    "band_width":    v.confidence_band_high - v.confidence_band_low,
                    "p_neutral":     v.p_neutral,
                    "built_days_ago":_days_since(v.built_at),
                },
                source_versions    = dict(v.source_versions or {}),
                user_id            = user_id,
            ))
    except Exception as exc:
        logger.debug("[scenario_seed_builder] macro sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Sub-builder: sector_scenario
# ---------------------------------------------------------------------------

async def _build_sector_seeds(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One seed per sector-type ForecastVector with directional signal >= floor."""
    results: List[dict] = []
    try:
        from app.db.repositories import forecast_repo

        vectors = await forecast_repo.list_forecast_vectors(
            session,
            entity_type="sector",
            user_id=user_id,
            limit=_LIMIT_FORECAST,
        )
        for v in (vectors or []):
            p_max = max(v.p_positive, v.p_negative)
            if p_max < _FORECAST_SIGNAL_FLOOR:
                continue

            direction = "expanding" if v.p_positive >= v.p_negative else "contracting"
            ftype = v.forecast_type.replace("_", " ")
            sector_key = v.entity_key
            scenario_name = f"Sector {sector_key} {ftype} {direction} ({v.horizon})"
            changed_assumption = (
                f"If sector {sector_key} {ftype} shifts {direction} over {v.horizon}"
            )

            evidence_items = await forecast_repo.list_forecast_evidence(
                session, forecast_id=v.id, limit=10
            )
            evidence_refs = [
                {
                    "source_type": e.source_type,
                    "source_id": e.source_id,
                    "description": e.description,
                }
                for e in (evidence_items or [])
            ]

            # Cross-exposures name the tickers directly linked to this sector key
            cross_tickers = await _affected_tickers_from_cross_exposure(
                session, sector_key
            )
            # Filter cross_tickers by allowlist when present
            if allowed is not None:
                cross_tickers = [t for t in cross_tickers if _ticker_allowed(t, allowed)]

            portfolio_ids: List[str] = []
            for t in cross_tickers[:10]:
                for pid in await _portfolios_holding(session, t):
                    if pid not in portfolio_ids:
                        portfolio_ids.append(pid)

            results.append(_make_seed(
                scenario_type      = SEED_TYPE_SECTOR,
                entity_type        = "sector",
                entity_id          = sector_key,
                ticker             = "",
                scenario_name      = scenario_name,
                changed_assumption = changed_assumption,
                source_type        = "forecast_vector",
                source_id          = v.id,
                affected_tickers   = cross_tickers,
                affected_portfolios= portfolio_ids,
                evidence_refs      = evidence_refs,
                transmission_inputs= {
                    "direction":      direction,
                    "horizon":        v.horizon,
                    "horizon_days":   v.horizon_days,
                    "forecast_type":  v.forecast_type,
                    "sector_key":     sector_key,
                    "cross_tickers":  cross_tickers,
                },
                impact_inputs      = {
                    "p_positive":           v.p_positive,
                    "p_negative":           v.p_negative,
                    "p_neutral":            v.p_neutral,
                    "confidence_band_low":  v.confidence_band_low,
                    "confidence_band_high": v.confidence_band_high,
                    "direction":            direction,
                    "sector_key":           sector_key,
                },
                confidence_inputs  = {
                    "confidence_band_low":  v.confidence_band_low,
                    "confidence_band_high": v.confidence_band_high,
                    "p_max":                p_max,
                    "evidence_count":       len(evidence_refs),
                    "forecast_schema":      v.forecast_schema,
                },
                uncertainty_inputs = {
                    "band_width":     v.confidence_band_high - v.confidence_band_low,
                    "p_neutral":      v.p_neutral,
                    "built_days_ago": _days_since(v.built_at),
                },
                source_versions    = dict(v.source_versions or {}),
                user_id            = user_id,
            ))
    except Exception as exc:
        logger.debug("[scenario_seed_builder] sector sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Sub-builder: catalyst_scenario
# ---------------------------------------------------------------------------

async def _build_catalyst_seeds(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One seed per open dossier_catalyst row."""
    results: List[dict] = []
    try:
        from sqlalchemy import select
        from app.db.models import DossierCatalyst

        stmt = (
            select(DossierCatalyst)
            .where(DossierCatalyst.status == "open")
            .limit(_LIMIT_CATALYST)
        )
        rows = (await session.execute(stmt)).scalars().all()

        for cat in rows:
            ticker = cat.ticker or ""
            if ticker and not _ticker_allowed(ticker, allowed):
                continue

            direction_label = (
                "bull trigger" if cat.direction == "bull_trigger" else "bear trigger"
            )
            scenario_name = (
                f"{ticker} catalyst ({direction_label}) — {cat.expected_window or 'open'}"
            )
            changed_assumption = (
                f"If {ticker} catalyst ({cat.direction}) triggers within "
                f"{cat.expected_window or 'unspecified window'}"
            )

            cross_tickers = await _affected_tickers_from_cross_exposure(session, ticker)
            affected_portfolios = await _portfolios_holding(session, ticker)

            results.append(_make_seed(
                scenario_type      = SEED_TYPE_CATALYST,
                entity_type        = "company",
                entity_id          = cat.id,
                ticker             = ticker,
                scenario_name      = scenario_name,
                changed_assumption = changed_assumption,
                source_type        = "dossier_catalyst",
                source_id          = cat.id,
                affected_tickers   = cross_tickers,
                affected_portfolios= affected_portfolios,
                evidence_refs      = [{
                    "source_type": "dossier_catalyst",
                    "source_id":   cat.id,
                    "description": cat.statement or f"Open catalyst for {ticker}",
                }],
                transmission_inputs= {
                    "direction":        cat.direction,
                    "expected_window":  cat.expected_window or "",
                    "specificity":      cat.specificity,
                    "ticker":           ticker,
                    "cross_tickers":    cross_tickers,
                },
                impact_inputs      = {
                    "specificity":       cat.specificity,
                    "conviction_weight": cat.conviction_weight,
                    "direction":         cat.direction,
                    "expected_window":   cat.expected_window or "",
                },
                confidence_inputs  = {
                    "specificity":           cat.specificity,
                    "has_statement":         bool(cat.statement),
                    "has_expected_window":   bool(cat.expected_window),
                    "conviction_weight":     cat.conviction_weight,
                },
                uncertainty_inputs = {
                    "inverse_specificity": 1.0 - cat.specificity,
                    "created_days_ago":    _days_since(cat.created_at),
                },
                source_versions    = {"dossier_catalyst": cat.id},
                user_id            = user_id,
            ))
    except Exception as exc:
        logger.debug("[scenario_seed_builder] catalyst sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Sub-builder: failure_mode_scenario
# ---------------------------------------------------------------------------

async def _build_failure_mode_seeds(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One seed per active dossier_failure_mode row."""
    results: List[dict] = []
    try:
        from sqlalchemy import select
        from app.db.models import DossierFailureMode

        stmt = select(DossierFailureMode).limit(_LIMIT_FAILURE_MODE)
        rows = (await session.execute(stmt)).scalars().all()

        for fm in rows:
            ticker = fm.ticker or ""
            if ticker and not _ticker_allowed(ticker, allowed):
                continue

            stage_label = f"stage {fm.sequence_stage}"
            scenario_name = (
                f"{ticker} failure-mode risk — {fm.analog_id} ({stage_label})"
            )
            changed_assumption = (
                f"If {ticker} continues on the {fm.analog_id} failure-mode trajectory "
                f"at {stage_label}"
            )

            cross_tickers = await _affected_tickers_from_cross_exposure(session, ticker)
            affected_portfolios = await _portfolios_holding(session, ticker)

            results.append(_make_seed(
                scenario_type      = SEED_TYPE_FAILURE_MODE,
                entity_type        = "company",
                entity_id          = fm.id,
                ticker             = ticker,
                scenario_name      = scenario_name,
                changed_assumption = changed_assumption,
                source_type        = "dossier_failure_mode",
                source_id          = fm.id,
                affected_tickers   = cross_tickers,
                affected_portfolios= affected_portfolios,
                evidence_refs      = [{
                    "source_type": "dossier_failure_mode",
                    "source_id":   fm.id,
                    "description": fm.stage_evidence or f"Failure-mode match: {fm.analog_id}",
                }],
                transmission_inputs= {
                    "analog_id":       fm.analog_id,
                    "sequence_stage":  fm.sequence_stage,
                    "ticker":          ticker,
                    "cross_tickers":   cross_tickers,
                },
                impact_inputs      = {
                    "relevance_at_match": fm.relevance_at_match,
                    "sequence_stage":     fm.sequence_stage,
                    "analog_id":          fm.analog_id,
                },
                confidence_inputs  = {
                    "relevance_at_match": fm.relevance_at_match,
                    "has_stage_evidence": bool(fm.stage_evidence),
                    "sequence_stage":     fm.sequence_stage,
                },
                uncertainty_inputs = {
                    "matched_days_ago": _days_since(fm.matched_at),
                    "sequence_stage":   fm.sequence_stage,
                },
                source_versions    = {"dossier_failure_mode": fm.id},
                user_id            = user_id,
            ))
    except Exception as exc:
        logger.debug("[scenario_seed_builder] failure_mode sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Sub-builder: portfolio_scenario
# ---------------------------------------------------------------------------

async def _build_portfolio_seeds(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One seed per portfolio that has at least one active position."""
    results: List[dict] = []
    try:
        from app.db.repositories import portfolio_repo

        portfolios = await portfolio_repo.portfolio_list(session, user_id=user_id)

        for port in (portfolios or []):
            active_tickers = await _portfolio_tickers(session, port.id)
            if not active_tickers:
                continue

            # Apply allowlist to the primary holding context
            if allowed is not None:
                eligible = [t for t in active_tickers if _ticker_allowed(t, allowed)]
                if not eligible:
                    continue
                active_tickers_display = eligible
            else:
                active_tickers_display = active_tickers

            ticker_preview = ", ".join(active_tickers_display[:5])
            scenario_name = (
                f"Portfolio '{port.name}' cross-holding scenario "
                f"({len(active_tickers_display)} position{'s' if len(active_tickers_display)!=1 else ''})"
            )
            changed_assumption = (
                f"If a shared macro or sector condition affects multiple positions "
                f"in portfolio '{port.name}' simultaneously"
            )

            # Cross-portfolio correlation refs for top holdings
            evidence_refs = [
                {
                    "source_type": "portfolio_positions",
                    "source_id":   port.id,
                    "description": f"Active positions: {ticker_preview}"
                                   + (" ..." if len(active_tickers_display) > 5 else ""),
                }
            ]

            results.append(_make_seed(
                scenario_type      = SEED_TYPE_PORTFOLIO,
                entity_type        = "portfolio",
                entity_id          = port.id,
                ticker             = "",
                scenario_name      = scenario_name,
                changed_assumption = changed_assumption,
                source_type        = "portfolio_positions",
                source_id          = port.id,
                affected_tickers   = active_tickers_display,
                affected_portfolios= [port.id],
                evidence_refs      = evidence_refs,
                transmission_inputs= {
                    "portfolio_id":      port.id,
                    "portfolio_name":    port.name,
                    "position_count":    len(active_tickers),
                    "tickers":           active_tickers_display,
                    "is_default":        port.is_default,
                },
                impact_inputs      = {
                    "position_count":    len(active_tickers_display),
                    "portfolio_name":    port.name,
                    "is_default":        port.is_default,
                },
                confidence_inputs  = {
                    "has_positions":     True,
                    "position_count":    len(active_tickers_display),
                    "is_default":        port.is_default,
                },
                uncertainty_inputs = {
                    "position_count":    len(active_tickers_display),
                    "correlation_unknown": True,
                },
                source_versions    = {"portfolio": port.id},
                user_id            = user_id,
            ))
    except Exception as exc:
        logger.debug("[scenario_seed_builder] portfolio sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def build_seeds(
    session,
    *,
    user_id: Optional[str] = None,
    targets: Optional[str] = None,
    seed_types: Optional[tuple] = None,
) -> List[dict]:
    """Build all scenario seeds from existing intelligence substrates.

    Arguments
    ---------
    session    — AsyncSession or None. Returns [] when None.
    user_id    — Optional user scoping. Passed through to substrates that
                 support it (watchlist, portfolio, forecast, similarity).
                 No ranking or portfolio-adjustment logic is applied here.
    targets    — Optional comma-separated ticker override. When provided,
                 only seeds for those tickers are returned. When absent,
                 uses the scenario_targets_enabled config flag; empty flag
                 means all tickers are eligible.
    seed_types — Optional tuple of SEED_TYPE_* constants to restrict which
                 sub-builders run. When None all six are run.

    Returns a flat list of seed dicts. Writes nothing. Never raises.
    """
    if session is None:
        return []

    try:
        effective_targets = targets
        if effective_targets is None:
            try:
                from app.config import get_settings
                effective_targets = get_settings().scenario_targets_enabled or ""
            except Exception:
                effective_targets = ""

        allowed = _parse_targets(effective_targets)

        active_types = set(seed_types) if seed_types is not None else set(ALL_SEED_TYPES)

        _sub_builders = (
            (SEED_TYPE_COMPANY,      _build_company_seeds),
            (SEED_TYPE_MACRO,        _build_macro_seeds),
            (SEED_TYPE_SECTOR,       _build_sector_seeds),
            (SEED_TYPE_CATALYST,     _build_catalyst_seeds),
            (SEED_TYPE_FAILURE_MODE, _build_failure_mode_seeds),
            (SEED_TYPE_PORTFOLIO,    _build_portfolio_seeds),
        )

        all_seeds: List[dict] = []
        for stype, builder in _sub_builders:
            if stype not in active_types:
                continue
            try:
                batch = await builder(session, allowed, user_id)
                all_seeds.extend(batch)
            except Exception as exc:
                logger.debug(
                    "[scenario_seed_builder] sub-builder %s failed: %r",
                    builder.__name__, exc,
                )

        return all_seeds

    except Exception as exc:
        logger.debug("[scenario_seed_builder] build_seeds outer error: %r", exc)
        return []
