"""
Decision Candidate Builder — Phase 13 · Slice 2.

Builds read-only decision candidate dicts from existing intelligence substrates.

Each candidate is a plain Python dict capturing the raw attention signal
and the structured inputs that the scoring engine (Slice 13.3) will use to
produce the five component scores.  No ranking, no scoring, no writes.

Candidate types
---------------
  forecast_candidate          — forecast_vector rows with directional signal
  risk_candidate              — active dossier_failure_mode rows
  catalyst_candidate          — open dossier_catalyst rows
  watchlist_candidate         — active watched_tickers rows
  portfolio_exposure_candidate — active portfolio_positions rows
  delivery_transition_candidate — pending/failed delivery_ledger rows
  similarity_candidate        — floor_passed similarity_edge rows

Candidate envelope (all seven types share this shape)
------------------------------------------------------
  candidate_type      str — one of the seven types above
  entity_type         str — company | thesis | failure_mode | portfolio
  entity_id           str — PK of the primary entity row
  ticker              str — ticker symbol or ""
  source_type         str — originating table name
  source_id           str — PK of the originating row
  headline            str — one-line human-readable description
  summary             str — longer description
  evidence_refs       list[dict] — [{source_type, source_id, description}]
  urgency_inputs      dict — raw inputs for urgency scoring (Slice 13.3)
  impact_inputs       dict — raw inputs for impact scoring (Slice 13.3)
  attention_inputs    dict — raw inputs for attention scoring (Slice 13.3)
  confidence_inputs   dict — raw inputs for confidence scoring (Slice 13.3)
  uncertainty_inputs  dict — raw inputs for uncertainty scoring (Slice 13.3)
  source_versions     dict — {table: row_id} for staleness detection
  user_id             str | None — pass-through only; no ranking logic applied

Missing-substrate behaviour
---------------------------
  Session None  → return []
  Entity missing → skip; no candidate produced
  Secondary facet missing → sparse candidate with safe zero-values
  Any unexpected error → logged at debug level, sub-builder returns []

Safety invariants (SP-5)
------------------------
  - This module NEVER writes to any source table or any decision table.
  - No import from conviction, recommendation, order, execution, or delivery
    service modules.
  - No target-price, buy/sell/hold, position-size, trade, or advice field.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Candidate type constants
# ---------------------------------------------------------------------------

CANDIDATE_TYPE_FORECAST            = "forecast_candidate"
CANDIDATE_TYPE_RISK                = "risk_candidate"
CANDIDATE_TYPE_CATALYST            = "catalyst_candidate"
CANDIDATE_TYPE_WATCHLIST           = "watchlist_candidate"
CANDIDATE_TYPE_PORTFOLIO_EXPOSURE  = "portfolio_exposure_candidate"
CANDIDATE_TYPE_DELIVERY_TRANSITION = "delivery_transition_candidate"
CANDIDATE_TYPE_SIMILARITY          = "similarity_candidate"

ALL_CANDIDATE_TYPES = (
    CANDIDATE_TYPE_FORECAST,
    CANDIDATE_TYPE_RISK,
    CANDIDATE_TYPE_CATALYST,
    CANDIDATE_TYPE_WATCHLIST,
    CANDIDATE_TYPE_PORTFOLIO_EXPOSURE,
    CANDIDATE_TYPE_DELIVERY_TRANSITION,
    CANDIDATE_TYPE_SIMILARITY,
)

# ---------------------------------------------------------------------------
# Per-sub-builder row limits — cap runaway scans on large substrates
# ---------------------------------------------------------------------------

_LIMIT_FORECAST   = 200
_LIMIT_RISK       = 100
_LIMIT_CATALYST   = 100
_LIMIT_WATCHLIST  = 500
_LIMIT_PORTFOLIO  = 500
_LIMIT_DELIVERY   = 100
_LIMIT_SIMILARITY = 200

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
    return ticker.upper() in allowed


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _days_since(dt) -> Optional[int]:
    """Days elapsed since *dt*, or None when dt is None or unrepresentable."""
    if dt is None:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (_now() - dt).days)
    except Exception:
        return None


def _make_candidate(
    *,
    candidate_type: str,
    entity_type: str,
    entity_id: str,
    ticker: str,
    source_type: str,
    source_id: str,
    headline: str,
    summary: str,
    evidence_refs: list,
    urgency_inputs: dict,
    impact_inputs: dict,
    attention_inputs: dict,
    confidence_inputs: dict,
    uncertainty_inputs: dict,
    source_versions: dict,
    user_id: Optional[str] = None,
) -> dict:
    return {
        "candidate_type": candidate_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "ticker": ticker,
        "source_type": source_type,
        "source_id": source_id,
        "headline": headline,
        "summary": summary,
        "evidence_refs": evidence_refs,
        "urgency_inputs": urgency_inputs,
        "impact_inputs": impact_inputs,
        "attention_inputs": attention_inputs,
        "confidence_inputs": confidence_inputs,
        "uncertainty_inputs": uncertainty_inputs,
        "source_versions": source_versions,
        "user_id": user_id,
    }


# ---------------------------------------------------------------------------
# Sub-builder: forecast_candidate
# ---------------------------------------------------------------------------

async def _build_forecast_candidates(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One candidate per forecast_vector row with a directional signal >= floor."""
    results: List[dict] = []
    try:
        from app.db.repositories import forecast_repo

        vectors = await forecast_repo.list_forecast_vectors(
            session,
            user_id=user_id,
            limit=_LIMIT_FORECAST,
        )
        for v in (vectors or []):
            ticker = v.entity_key if v.entity_type == "company" else ""
            if not _ticker_allowed(ticker or v.entity_key, allowed):
                continue

            p_max = max(v.p_positive, v.p_negative)
            if p_max < _FORECAST_SIGNAL_FLOOR:
                continue

            direction = "strengthening" if v.p_positive >= v.p_negative else "weakening"
            ftype = v.forecast_type.replace("_", " ")
            headline = f"{v.entity_key} {ftype} — {direction} ({v.horizon})"
            summary = v.why or f"{v.forecast_type} signal for {v.entity_key}"

            evidence_items = await forecast_repo.list_forecast_evidence(
                session,
                forecast_id=v.id,
                limit=10,
            )
            evidence_refs = [
                {
                    "source_type": e.source_type,
                    "source_id": e.source_id,
                    "description": e.description,
                }
                for e in (evidence_items or [])
            ]

            results.append(_make_candidate(
                candidate_type=CANDIDATE_TYPE_FORECAST,
                entity_type=v.entity_type,
                entity_id=v.entity_key,
                ticker=ticker,
                source_type="forecast_vector",
                source_id=v.id,
                headline=headline,
                summary=summary,
                evidence_refs=evidence_refs,
                urgency_inputs={
                    "horizon": v.horizon,
                    "horizon_days": v.horizon_days,
                    "built_days_ago": _days_since(v.built_at),
                    "p_max": p_max,
                },
                impact_inputs={
                    "p_positive": v.p_positive,
                    "p_negative": v.p_negative,
                    "p_neutral": v.p_neutral,
                    "confidence_band_low": v.confidence_band_low,
                    "confidence_band_high": v.confidence_band_high,
                    "forecast_type": v.forecast_type,
                },
                attention_inputs={
                    "forecast_type": v.forecast_type,
                    "entity_type": v.entity_type,
                    "direction": direction,
                },
                confidence_inputs={
                    "confidence_band_low": v.confidence_band_low,
                    "confidence_band_high": v.confidence_band_high,
                    "evidence_count": len(evidence_refs),
                    "forecast_schema": v.forecast_schema,
                },
                uncertainty_inputs={
                    "band_width": v.confidence_band_high - v.confidence_band_low,
                    "p_neutral": v.p_neutral,
                },
                source_versions=dict(v.source_versions or {}),
                user_id=user_id,
            ))
    except Exception as exc:
        logger.debug("[candidate_builder] forecast sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Sub-builder: risk_candidate
# ---------------------------------------------------------------------------

async def _build_risk_candidates(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One candidate per active dossier_failure_mode row."""
    results: List[dict] = []
    try:
        from sqlalchemy import select
        from app.db.models import DossierFailureMode, HistoricalAnalog

        stmt = select(DossierFailureMode).limit(_LIMIT_RISK)
        rows = (await session.execute(stmt)).scalars().all()

        for fm in rows:
            ticker = fm.ticker
            if not _ticker_allowed(ticker, allowed):
                continue

            analog_label = ""
            try:
                a_result = await session.execute(
                    select(HistoricalAnalog).where(HistoricalAnalog.id == fm.analog_id)
                )
                analog = a_result.scalar_one_or_none()
                if analog:
                    analog_label = analog.label
            except Exception:
                pass

            stage_label = f"Stage {fm.sequence_stage}"
            headline = f"{ticker} risk — {analog_label or fm.analog_id} ({stage_label})"
            summary = fm.stage_evidence or f"Active failure-mode match: {analog_label or fm.analog_id}"

            results.append(_make_candidate(
                candidate_type=CANDIDATE_TYPE_RISK,
                entity_type="failure_mode",
                entity_id=fm.id,
                ticker=ticker,
                source_type="dossier_failure_mode",
                source_id=fm.id,
                headline=headline,
                summary=summary,
                evidence_refs=[{
                    "source_type": "historical_analog",
                    "source_id": fm.analog_id,
                    "description": f"Analog match: {analog_label}" if analog_label
                                   else "Historical analog match",
                }],
                urgency_inputs={
                    "sequence_stage": fm.sequence_stage,
                    "matched_days_ago": _days_since(fm.matched_at),
                    "relevance_at_match": fm.relevance_at_match,
                },
                impact_inputs={
                    "relevance_at_match": fm.relevance_at_match,
                    "sequence_stage": fm.sequence_stage,
                    "analog_label": analog_label,
                },
                attention_inputs={
                    "ticker": ticker,
                    "analog_id": fm.analog_id,
                    "stage": fm.sequence_stage,
                },
                confidence_inputs={
                    "relevance_at_match": fm.relevance_at_match,
                    "has_analog_label": bool(analog_label),
                    "has_stage_evidence": bool(fm.stage_evidence),
                },
                uncertainty_inputs={
                    "matched_days_ago": _days_since(fm.matched_at),
                    "sequence_stage": fm.sequence_stage,
                },
                source_versions={"dossier_failure_mode": fm.id},
                user_id=user_id,
            ))
    except Exception as exc:
        logger.debug("[candidate_builder] risk sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Sub-builder: catalyst_candidate
# ---------------------------------------------------------------------------

async def _build_catalyst_candidates(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One candidate per open dossier_catalyst row."""
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
            ticker = cat.ticker
            if not _ticker_allowed(ticker, allowed):
                continue

            direction_label = (
                "bull trigger" if cat.direction == "bull_trigger" else "bear trigger"
            )
            headline = f"{ticker} catalyst ({direction_label}) — {cat.expected_window}"
            summary = cat.statement or f"Open catalyst for {ticker}"

            results.append(_make_candidate(
                candidate_type=CANDIDATE_TYPE_CATALYST,
                entity_type="company",
                entity_id=cat.id,
                ticker=ticker,
                source_type="dossier_catalyst",
                source_id=cat.id,
                headline=headline,
                summary=summary,
                evidence_refs=[{
                    "source_type": "dossier_catalyst",
                    "source_id": cat.id,
                    "description": cat.statement or "",
                }],
                urgency_inputs={
                    "direction": cat.direction,
                    "expected_window": cat.expected_window,
                    "specificity": cat.specificity,
                    "created_days_ago": _days_since(cat.created_at),
                },
                impact_inputs={
                    "specificity": cat.specificity,
                    "conviction_weight": cat.conviction_weight,
                    "direction": cat.direction,
                },
                attention_inputs={
                    "ticker": ticker,
                    "direction": cat.direction,
                    "expected_window": cat.expected_window,
                },
                confidence_inputs={
                    "specificity": cat.specificity,
                    "has_statement": bool(cat.statement),
                    "has_expected_window": bool(cat.expected_window),
                },
                uncertainty_inputs={
                    "inverse_specificity": 1.0 - cat.specificity,
                    "created_days_ago": _days_since(cat.created_at),
                },
                source_versions={"dossier_catalyst": cat.id},
                user_id=user_id,
            ))
    except Exception as exc:
        logger.debug("[candidate_builder] catalyst sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Sub-builder: watchlist_candidate
# ---------------------------------------------------------------------------

async def _build_watchlist_candidates(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One candidate per active watched_tickers row."""
    results: List[dict] = []
    try:
        from app.db.repositories import watchlist_repo

        tickers = await watchlist_repo.ticker_list_active(session, user_id=user_id)

        for wt in (tickers or []):
            ticker = wt.ticker
            if not _ticker_allowed(ticker, allowed):
                continue

            added_days = _days_since(wt.added_at)
            headline = f"{ticker} — watchlist item"
            summary = wt.company_name or ticker

            results.append(_make_candidate(
                candidate_type=CANDIDATE_TYPE_WATCHLIST,
                entity_type="company",
                entity_id=wt.id,
                ticker=ticker,
                source_type="watched_tickers",
                source_id=wt.id,
                headline=headline,
                summary=summary,
                evidence_refs=[{
                    "source_type": "watched_tickers",
                    "source_id": wt.id,
                    "description": f"Active watchlist entry for {ticker}",
                }],
                urgency_inputs={
                    "added_days_ago": added_days,
                },
                impact_inputs={
                    "ticker": ticker,
                },
                attention_inputs={
                    "ticker": ticker,
                    "company_name": wt.company_name or "",
                    "added_days_ago": added_days,
                },
                confidence_inputs={
                    "has_company_name": bool(wt.company_name),
                    "active": wt.active,
                },
                uncertainty_inputs={
                    "added_days_ago": added_days,
                },
                source_versions={"watched_tickers": wt.id},
                user_id=user_id,
            ))
    except Exception as exc:
        logger.debug("[candidate_builder] watchlist sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Sub-builder: portfolio_exposure_candidate
# ---------------------------------------------------------------------------

async def _build_portfolio_exposure_candidates(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One candidate per active portfolio_positions row."""
    results: List[dict] = []
    try:
        from app.db.repositories import portfolio_repo

        portfolios = await portfolio_repo.portfolio_list(session, user_id=user_id)
        for port in (portfolios or []):
            positions = await portfolio_repo.position_list(session, portfolio_id=port.id)
            for pos in (positions or []):
                if not pos.active:
                    continue
                ticker = pos.ticker
                if not _ticker_allowed(ticker, allowed):
                    continue

                membership_label = pos.membership_class or "watchlist"
                weight_str = f", weight={pos.weight:.1%}" if pos.weight is not None else ""
                headline = f"{ticker} portfolio exposure ({membership_label})"
                summary = f"Portfolio '{port.name}': {ticker} ({membership_label}){weight_str}"

                results.append(_make_candidate(
                    candidate_type=CANDIDATE_TYPE_PORTFOLIO_EXPOSURE,
                    entity_type="portfolio",
                    entity_id=pos.id,
                    ticker=ticker,
                    source_type="portfolio_positions",
                    source_id=pos.id,
                    headline=headline,
                    summary=summary,
                    evidence_refs=[{
                        "source_type": "portfolio_positions",
                        "source_id": pos.id,
                        "description": f"{membership_label} position in {ticker}",
                    }],
                    urgency_inputs={
                        "membership_class": membership_label,
                        "added_days_ago": _days_since(pos.added_at),
                    },
                    impact_inputs={
                        "weight": pos.weight,
                        "shares": pos.shares,
                        "cost_basis": pos.cost_basis,
                        "membership_class": membership_label,
                        "portfolio_name": port.name,
                    },
                    attention_inputs={
                        "ticker": ticker,
                        "membership_class": membership_label,
                        "portfolio_id": port.id,
                    },
                    confidence_inputs={
                        "has_weight": pos.weight is not None,
                        "has_cost_basis": pos.cost_basis is not None,
                        "is_default_portfolio": port.is_default,
                    },
                    uncertainty_inputs={
                        "weight": pos.weight,
                        "added_days_ago": _days_since(pos.added_at),
                    },
                    source_versions={"portfolio_positions": pos.id},
                    user_id=user_id,
                ))
    except Exception as exc:
        logger.debug("[candidate_builder] portfolio_exposure sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Sub-builder: delivery_transition_candidate
# ---------------------------------------------------------------------------

async def _build_delivery_transition_candidates(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One candidate per pending/failed delivery_ledger row."""
    results: List[dict] = []
    try:
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        stmt = (
            select(DeliveryLedger)
            .where(DeliveryLedger.status.in_(["pending", "failed"]))
            .order_by(DeliveryLedger.created_at.desc())
            .limit(_LIMIT_DELIVERY)
        )
        rows = (await session.execute(stmt)).scalars().all()

        for dl in rows:
            # target_key may be a ticker or a user/system key — best-effort
            ticker = dl.target_key if (dl.target_key and len(dl.target_key) <= 20) else ""
            if ticker and not _ticker_allowed(ticker, allowed):
                continue

            status_label = dl.status
            severity_label = dl.canonical_severity or "unknown"
            headline = f"Delivery transition — {status_label} ({severity_label})"
            summary = (
                f"Content pending delivery to {dl.target_key} via {dl.channel}"
                + (f" — {dl.canonical_severity}" if dl.canonical_severity else "")
            )

            results.append(_make_candidate(
                candidate_type=CANDIDATE_TYPE_DELIVERY_TRANSITION,
                entity_type="company",
                entity_id=dl.id,
                ticker=ticker,
                source_type="delivery_ledger",
                source_id=dl.id,
                headline=headline,
                summary=summary,
                evidence_refs=[{
                    "source_type": "delivery_ledger",
                    "source_id": dl.id,
                    "description": f"Delivery {dl.status} for {dl.target_key}",
                }],
                urgency_inputs={
                    "status": dl.status,
                    "attempts": dl.attempts,
                    "created_days_ago": _days_since(dl.created_at),
                    "canonical_severity": dl.canonical_severity,
                    "severity_rank": dl.severity_rank,
                },
                impact_inputs={
                    "canonical_severity": dl.canonical_severity,
                    "severity_rank": dl.severity_rank or 0,
                    "channel": dl.channel,
                },
                attention_inputs={
                    "target_key": dl.target_key,
                    "channel": dl.channel,
                    "status": dl.status,
                },
                confidence_inputs={
                    "has_severity": dl.canonical_severity is not None,
                    "attempts": dl.attempts,
                    "has_artifact_ref": dl.artifact_ref is not None,
                },
                uncertainty_inputs={
                    "attempts": dl.attempts,
                    "created_days_ago": _days_since(dl.created_at),
                },
                source_versions={"delivery_ledger": dl.id},
                user_id=user_id,
            ))
    except Exception as exc:
        logger.debug("[candidate_builder] delivery_transition sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Sub-builder: similarity_candidate
# ---------------------------------------------------------------------------

async def _build_similarity_candidates(
    session,
    allowed: Optional[frozenset],
    user_id: Optional[str],
) -> List[dict]:
    """One candidate per floor_passed similarity_edge row."""
    results: List[dict] = []
    try:
        from app.db.repositories import similarity_repo

        edges = await similarity_repo.list_similarity_edges(
            session,
            user_id=user_id,
            floor_passed_only=True,
            limit=_LIMIT_SIMILARITY,
        )

        for edge in (edges or []):
            query_key = edge.query_key
            candidate_key = edge.candidate_key
            ticker = query_key if len(query_key) <= 20 else ""
            if ticker and not _ticker_allowed(ticker, allowed):
                continue

            headline = edge.headline or f"{query_key} similar to {candidate_key}"
            summary = f"{query_key} ↔ {candidate_key}: {edge.headline or 'similarity match'}"

            contributions = edge.contributions or []
            evidence_refs = []
            for c in contributions[:5]:
                if isinstance(c, dict):
                    feat = c.get("feature", "")
                    val = c.get("shared_value", "")
                    desc = f"{feat}: {val}" if feat else str(val)
                else:
                    desc = str(c)
                evidence_refs.append({
                    "source_type": "similarity_edge",
                    "source_id": edge.id,
                    "description": desc,
                })

            results.append(_make_candidate(
                candidate_type=CANDIDATE_TYPE_SIMILARITY,
                entity_type="company",
                entity_id=edge.id,
                ticker=ticker,
                source_type="similarity_edge",
                source_id=edge.id,
                headline=headline,
                summary=summary,
                evidence_refs=evidence_refs,
                urgency_inputs={
                    "score": edge.score,
                    "rank": edge.rank,
                    "built_days_ago": _days_since(edge.built_at),
                },
                impact_inputs={
                    "score": edge.score,
                    "rank": edge.rank,
                    "query_key": query_key,
                    "candidate_key": candidate_key,
                    "target_type": edge.target_type,
                },
                attention_inputs={
                    "query_key": query_key,
                    "candidate_key": candidate_key,
                    "floor_passed": edge.floor_passed,
                    "score": edge.score,
                },
                confidence_inputs={
                    "score": edge.score,
                    "has_contributions": bool(contributions),
                    "has_disanalogy": bool(edge.disanalogy),
                    "score_schema": edge.score_schema,
                },
                uncertainty_inputs={
                    "inverse_score": 1.0 - edge.score,
                    "built_days_ago": _days_since(edge.built_at),
                    "disanalogy": edge.disanalogy or "",
                },
                source_versions={"similarity_edge": edge.id},
                user_id=user_id,
            ))
    except Exception as exc:
        logger.debug("[candidate_builder] similarity sub-builder error: %r", exc)
    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def build_candidates(
    session,
    *,
    user_id: Optional[str] = None,
    targets: Optional[str] = None,
) -> List[dict]:
    """Build all decision candidates from existing intelligence substrates.

    Arguments:
        session — AsyncSession or None. Returns [] when None.
        user_id — Optional user scoping. Passed through to substrates that
                  support it (watchlist, portfolio, forecast, similarity).
                  No ranking or portfolio-adjustment logic is applied here.
        targets — Optional comma-separated ticker override. When provided,
                  only candidates for those tickers are returned. When absent,
                  uses the decision_targets_enabled config flag; empty flag
                  means all tickers are eligible.

    Returns a flat list of candidate dicts. Writes nothing. Never raises.
    """
    if session is None:
        return []

    try:
        effective_targets = targets
        if effective_targets is None:
            try:
                from app.config import get_settings
                effective_targets = get_settings().decision_targets_enabled or ""
            except Exception:
                effective_targets = ""

        allowed = _parse_targets(effective_targets)

        all_candidates: List[dict] = []

        _sub_builders = (
            _build_forecast_candidates,
            _build_risk_candidates,
            _build_catalyst_candidates,
            _build_watchlist_candidates,
            _build_portfolio_exposure_candidates,
            _build_delivery_transition_candidates,
            _build_similarity_candidates,
        )

        for builder in _sub_builders:
            try:
                batch = await builder(session, allowed, user_id)
                all_candidates.extend(batch)
            except Exception as exc:
                logger.debug(
                    "[candidate_builder] sub-builder %s failed: %r",
                    builder.__name__, exc,
                )

        return all_candidates

    except Exception as exc:
        logger.debug("[candidate_builder] build_candidates outer error: %r", exc)
        return []
