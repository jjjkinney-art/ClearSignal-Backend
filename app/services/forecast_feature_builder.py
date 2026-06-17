"""
Forecast Feature Builder — Phase 12 · Slice 2.

Builds structured forecast *input* objects for two entity types:
  T1 — company        (build_company_forecast_features)
  T4 — failure_mode   (build_failure_mode_forecast_features)

T2 (thesis) and portfolio features are deferred to Phase 13 per spec §16.

Output contract
---------------
Each builder returns a plain Python dict (the "feature object") or None.
This dict is the input to the probability engine (Phase 12 Slice 3) and the
explainability service (Slice 4).  Nothing is written to forecast_vector
here — storage is the invalidation/rebuild orchestration's responsibility
(Slice 5).

The feature object schema is versioned:
  COMPANY_FEATURE_VERSION  = 1
  FAILURE_MODE_FEATURE_VERSION = 1

Reads (read-only — this module NEVER writes to any source table)
------
  T1: company_dossier, dossier_core_debate, dossier_durability,
      thesis_versions (latest 2), dossier_failure_mode,
      historical_analogs (via failure_mode.analog_id),
      similarity_edge (floor_passed, target_type="company")
  T4: dossier_failure_mode, historical_analogs,
      similarity_edge (floor_passed, target_type="failure_mode")

Writes: NONE.

Missing-substrate behaviour
---------------------------
  - Primary entity missing (no company_dossier head, no dossier_failure_mode)
    → return None; nothing to build.
  - Any joined facet missing (no debate, no durability, no analogs, no peers)
    → sparse feature object; missing fields default to safe zero-values.
    Never raises; never returns None for a missing secondary facet.
  - Any unexpected error → logged at debug level, returns None.

Safety invariants (Phase 12 spec §0):
  - No target-price, buy/sell, recommendation, or advice field anywhere.
  - No opaque embeddings — every feature is human-interpretable.
  - Dependency direction: this module imports from Phase 11 (similarity_edge
    read) but Phase 11 NEVER imports from Phase 12.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

COMPANY_FEATURE_VERSION: int = 1
FAILURE_MODE_FEATURE_VERSION: int = 1

# Staleness threshold for "is the most recent thesis recent?"
_THESIS_RECENCY_DAYS: int = 90


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _days_ago(dt) -> Optional[int]:
    """Return days since dt, or None if dt is None / tz-unaware."""
    if dt is None:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = _now() - dt
        return max(0, delta.days)
    except Exception:
        return None


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _infer_analog_resolution(analog) -> str:
    """Infer outcome direction from HistoricalAnalog fields.

    Returns one of: "negative", "positive", "neutral", "unknown".

    Resolution rules (interpretable, not opaque):
      - drawdown_pct > 0.30  (30%) → "negative"
      - drawdown_pct <= 0.05 (5%)  → "positive"
      - 0.05 < drawdown_pct <= 0.30 → "neutral"
      - drawdown_pct is None → fall back to outcome_summary keyword scan
      - outcome_summary contains "recover", "resolved", "rebounded" → "positive"
      - outcome_summary contains "collapse", "bankrupt", "permanent", "fail" → "negative"
      - otherwise → "unknown"
    """
    if analog is None:
        return "unknown"

    drawdown = getattr(analog, "drawdown_pct", None)
    if drawdown is not None:
        pct = abs(_safe_float(drawdown))
        if pct > 0.30:
            return "negative"
        if pct <= 0.05:
            return "positive"
        return "neutral"

    summary = (getattr(analog, "outcome_summary", "") or "").lower()
    positive_words = {"recover", "resolved", "rebounded", "normalized", "stabilized"}
    negative_words = {"collapse", "bankrupt", "permanent", "fail", "default", "crisis"}
    if any(w in summary for w in positive_words):
        return "positive"
    if any(w in summary for w in negative_words):
        return "negative"
    return "unknown"


def _analog_feature(analog, relevance_weight: float = 1.0) -> dict:
    """Serialize one HistoricalAnalog into the analog_set entry format."""
    concern_tags = getattr(analog, "concern_tags", None)
    if not isinstance(concern_tags, list):
        concern_tags = []
    return {
        "analog_id": getattr(analog, "id", ""),
        "mechanism": getattr(analog, "mechanism", "") or "",
        "concern_tags": concern_tags,
        "quality_rating": getattr(analog, "quality_rating", "") or "",
        "outcome_summary": getattr(analog, "outcome_summary", "") or "",
        "drawdown_pct": getattr(analog, "drawdown_pct", None),
        "time_to_recover_days": getattr(analog, "time_to_recover_days", None),
        "valuation_regime": getattr(analog, "valuation_regime", "") or "",
        "growth_phase": getattr(analog, "growth_phase", "") or "",
        "macro_regime": getattr(analog, "macro_regime", "") or "",
        "sector": getattr(analog, "sector", "") or "",
        "business_model": getattr(analog, "business_model", "") or "",
        "relevance_weight": _safe_float(relevance_weight, 1.0),
        "resolution": _infer_analog_resolution(analog),
    }


def _similarity_peer_feature(edge) -> dict:
    """Serialize one SimilarityEdge into the similarity_peers entry format."""
    return {
        "candidate_key": getattr(edge, "candidate_key", "") or "",
        "score": _safe_float(getattr(edge, "score", 0.0)),
        "target_type": getattr(edge, "target_type", "") or "",
        "rank": _safe_int(getattr(edge, "rank", 0)),
    }


def _avg(values: list) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


# ---------------------------------------------------------------------------
# T1 — COMPANY
# ---------------------------------------------------------------------------

async def build_company_forecast_features(
    session,
    ticker: str,
    *,
    max_similarity_peers: int = 10,
) -> Optional[dict]:
    """Build T1 (company) forecast feature object for *ticker*.

    Returns a feature dict or None when session is None or no company_dossier
    head row exists for this ticker.

    The feature object fields:
      entity_type, entity_key
      analog_set         — analogs via active failure_mode rows
      analog_count
      similarity_peers   — floor_passed similarity edges (target_type="company")
      similarity_peer_count, similarity_avg_score
      thesis_trajectory  — confidence delta from last 2 thesis_versions
      debate_state       — current lean + version + confidence
      regime_context     — from dossier_durability
      durability         — catalyst_proximity_days, analog_time_to_trough_days
      source_versions    — row-version snapshot for staleness detection
      staleness_indicators
      feature_schema
    """
    if session is None:
        return None
    try:
        from sqlalchemy import select
        from app.db.models import (
            DossierFailureMode, HistoricalAnalog, ThesisVersion, SimilarityEdge,
        )
        from app.db.repositories.dossier_repo import get_head, get_debate, get_durability

        # ── Primary entity ────────────────────────────────────────────────────
        head = await get_head(session, ticker)
        if head is None:
            logger.debug(
                "[forecast_feature_builder] no company_dossier head for ticker=%s", ticker
            )
            return None

        ticker_norm = head.ticker  # normalized form from dossier

        # ── Core debate ───────────────────────────────────────────────────────
        debate = await get_debate(session, ticker_norm)
        debate_state = {
            "current_lean": getattr(debate, "current_lean", "balanced") or "balanced",
            "version": _safe_int(getattr(debate, "version", 1)),
            "confidence": _safe_float(getattr(debate, "confidence", 0.0)),
        } if debate else {
            "current_lean": "balanced",
            "version": 1,
            "confidence": 0.0,
        }

        # ── Durability / regime context ───────────────────────────────────────
        durability_row = await get_durability(session, ticker_norm)
        regime_context = {
            "conviction_trend": getattr(durability_row, "conviction_trend", "stable") or "stable",
            "cycle_position": getattr(durability_row, "cycle_position", "unknown") or "unknown",
            "horizon_hint": getattr(durability_row, "horizon_hint", "investment") or "investment",
            "staleness_state": getattr(head, "staleness_state", "fresh") or "fresh",
        } if durability_row else {
            "conviction_trend": "stable",
            "cycle_position": "unknown",
            "horizon_hint": "investment",
            "staleness_state": getattr(head, "staleness_state", "fresh") or "fresh",
        }
        durability = {
            "catalyst_proximity_days": getattr(durability_row, "catalyst_proximity_days", None)
                if durability_row else None,
            "analog_time_to_trough_days": getattr(durability_row, "analog_time_to_trough_days", None)
                if durability_row else None,
        }

        # ── Thesis trajectory (latest 2 versions) ────────────────────────────
        tv_stmt = (
            select(ThesisVersion)
            .where(ThesisVersion.ticker == ticker_norm)
            .order_by(ThesisVersion.created_at.desc())
            .limit(2)
        )
        tv_rows = list((await session.execute(tv_stmt)).scalars().all())

        confidence_current: float = 0.0
        confidence_previous: Optional[float] = None
        thesis_version_id: Optional[str] = None
        thesis_is_recent: bool = False
        thesis_stance: str = ""
        version_count: int = len(tv_rows)

        if tv_rows:
            latest_tv = tv_rows[0]
            confidence_current = _safe_float(getattr(latest_tv, "confidence_score", 0.0))
            thesis_version_id = latest_tv.id
            thesis_stance = getattr(latest_tv, "directional_stance", "") or ""
            age_days = _days_ago(getattr(latest_tv, "created_at", None))
            thesis_is_recent = (age_days is not None and age_days <= _THESIS_RECENCY_DAYS)
            if len(tv_rows) >= 2:
                confidence_previous = _safe_float(
                    getattr(tv_rows[1], "confidence_score", 0.0)
                )

        delta: float = (
            confidence_current - confidence_previous
            if confidence_previous is not None
            else 0.0
        )
        # confidence scores are 0–1; treat <5pp as flat, ≥5pp as directional
        if abs(delta) < 0.05:
            direction = "flat"
        elif delta > 0:
            direction = "rising"
        else:
            direction = "falling"

        thesis_trajectory = {
            "confidence_current": confidence_current,
            "confidence_previous": confidence_previous,
            "delta": delta,
            "direction": direction,
            "version_count": version_count,
            "stance": thesis_stance,
            "primary_concern": getattr(head, "primary_concern", "") or "",
        }

        # ── Analog set (via active failure_mode rows for this ticker) ─────────
        fm_stmt = (
            select(DossierFailureMode)
            .where(DossierFailureMode.ticker == ticker_norm)
        )
        fm_rows = list((await session.execute(fm_stmt)).scalars().all())

        analog_set: list = []
        for fm in fm_rows:
            if not fm.analog_id:
                continue
            analog = (
                await session.execute(
                    select(HistoricalAnalog).where(HistoricalAnalog.id == fm.analog_id)
                )
            ).scalar_one_or_none()
            if analog is not None:
                analog_set.append(
                    _analog_feature(analog, relevance_weight=fm.relevance_at_match or 1.0)
                )

        # ── Similarity peers (floor_passed T1 edges for this ticker) ──────────
        sim_stmt = (
            select(SimilarityEdge)
            .where(
                SimilarityEdge.target_type == "company",
                SimilarityEdge.query_key == ticker_norm,
                SimilarityEdge.floor_passed.is_(True),
                SimilarityEdge.expires_at > _now(),
            )
            .order_by(SimilarityEdge.rank.asc())
            .limit(max_similarity_peers)
        )
        peer_rows = list((await session.execute(sim_stmt)).scalars().all())
        similarity_peers = [_similarity_peer_feature(e) for e in peer_rows]
        peer_scores = [p["score"] for p in similarity_peers]

        # ── Source versions (for staleness detection in Slice 5) ──────────────
        source_versions = {
            "company_dossier_row_version": _safe_int(getattr(head, "row_version", 0)),
            "thesis_version_id": thesis_version_id or "",
            "core_debate_version": debate_state["version"],
            "feature_schema": COMPANY_FEATURE_VERSION,
        }

        # ── Staleness indicators ──────────────────────────────────────────────
        staleness_indicators = {
            "dossier_staleness_state": getattr(head, "staleness_state", "fresh") or "fresh",
            "has_similarity_peers": len(similarity_peers) > 0,
            "has_analogs": len(analog_set) > 0,
            "thesis_is_recent": thesis_is_recent,
            "debate_has_lean": debate_state["current_lean"] not in ("balanced", ""),
        }

        return {
            "entity_type": "company",
            "entity_key": ticker_norm,
            "analog_set": analog_set,
            "analog_count": len(analog_set),
            "similarity_peers": similarity_peers,
            "similarity_peer_count": len(similarity_peers),
            "similarity_avg_score": _avg(peer_scores),
            "thesis_trajectory": thesis_trajectory,
            "debate_state": debate_state,
            "regime_context": regime_context,
            "durability": durability,
            "source_versions": source_versions,
            "staleness_indicators": staleness_indicators,
            "feature_schema": COMPANY_FEATURE_VERSION,
        }

    except Exception as exc:
        logger.debug(
            "[forecast_feature_builder] build_company_forecast_features failed for %s: %r",
            ticker, exc,
        )
        return None


async def build_company_forecast_features_for_all(
    session,
    *,
    limit: Optional[int] = None,
) -> List[dict]:
    """Build T1 feature objects for every ticker with a company_dossier head.

    Returns a list of feature dicts (no None entries).  Returns [] when
    session is None or on error.
    """
    if session is None:
        return []
    try:
        from sqlalchemy import select
        from app.db.models import CompanyDossier

        stmt = select(CompanyDossier.ticker)
        if limit is not None:
            stmt = stmt.limit(limit)
        tickers = list((await session.execute(stmt)).scalars().all())

        results: List[dict] = []
        for t in tickers:
            features = await build_company_forecast_features(session, t)
            if features is not None:
                results.append(features)
        return results

    except Exception as exc:
        logger.debug(
            "[forecast_feature_builder] build_company_forecast_features_for_all failed: %r", exc
        )
        return []


# ---------------------------------------------------------------------------
# T4 — FAILURE MODE
# ---------------------------------------------------------------------------

async def build_failure_mode_forecast_features(
    session,
    failure_mode_id: str,
    *,
    max_similarity_peers: int = 10,
) -> Optional[dict]:
    """Build T4 (failure_mode) forecast feature object for *failure_mode_id*.

    Returns a feature dict or None when session is None or no
    dossier_failure_mode row exists with this id.

    A missing linked analog does NOT cause None — a sparse feature object is
    built from the dossier_failure_mode fields alone.

    The feature object fields:
      entity_type, entity_key
      failure_mode       — ticker, analog_id, mechanism, sequence_stage,
                           relevance_at_match, stage_evidence
      analog_set         — the linked analog (weight = relevance_at_match)
      analog_count
      similarity_peers   — floor_passed similarity edges for this fm.id
      similarity_peer_count, similarity_avg_score
      thesis_trajectory  — fetched from the company dossier for this ticker
      debate_state       — from this ticker's core_debate
      regime_context     — from this ticker's durability row
      durability
      source_versions    — snapshot for staleness detection
      staleness_indicators
      feature_schema
    """
    if session is None:
        return None
    try:
        from sqlalchemy import select
        from app.db.models import DossierFailureMode, HistoricalAnalog, SimilarityEdge

        # ── Primary entity ────────────────────────────────────────────────────
        fm = (
            await session.execute(
                select(DossierFailureMode).where(DossierFailureMode.id == failure_mode_id)
            )
        ).scalar_one_or_none()
        if fm is None:
            logger.debug(
                "[forecast_feature_builder] failure_mode_id=%s not found", failure_mode_id
            )
            return None

        ticker = fm.ticker

        # ── Linked analog ─────────────────────────────────────────────────────
        analog = None
        if fm.analog_id:
            analog = (
                await session.execute(
                    select(HistoricalAnalog).where(HistoricalAnalog.id == fm.analog_id)
                )
            ).scalar_one_or_none()
            if analog is None:
                logger.debug(
                    "[forecast_feature_builder] analog_id=%s missing for failure_mode_id=%s "
                    "— building sparse features",
                    fm.analog_id, failure_mode_id,
                )

        failure_mode_info = {
            "ticker": ticker,
            "analog_id": fm.analog_id or "",
            "mechanism": getattr(analog, "mechanism", "") or "" if analog else "",
            "sequence_stage": _safe_int(fm.sequence_stage, 1),
            "relevance_at_match": _safe_float(fm.relevance_at_match, 0.0),
            "stage_evidence": getattr(fm, "stage_evidence", "") or "",
        }

        analog_set: list = []
        if analog is not None:
            analog_set.append(
                _analog_feature(analog, relevance_weight=fm.relevance_at_match or 1.0)
            )

        # ── Similarity peers (floor_passed T4 edges for this failure_mode_id) ─
        sim_stmt = (
            select(SimilarityEdge)
            .where(
                SimilarityEdge.target_type == "failure_mode",
                SimilarityEdge.query_key == failure_mode_id,
                SimilarityEdge.floor_passed.is_(True),
                SimilarityEdge.expires_at > _now(),
            )
            .order_by(SimilarityEdge.rank.asc())
            .limit(max_similarity_peers)
        )
        peer_rows = list((await session.execute(sim_stmt)).scalars().all())
        similarity_peers = [_similarity_peer_feature(e) for e in peer_rows]
        peer_scores = [p["score"] for p in similarity_peers]

        # ── Company-level context (thesis + debate + durability for this ticker)
        #    Sparse-tolerant: all None → safe zero-value defaults.
        try:
            company_ctx = await build_company_forecast_features(session, ticker)
        except Exception:
            company_ctx = None

        if company_ctx is not None:
            thesis_trajectory = company_ctx["thesis_trajectory"]
            debate_state = company_ctx["debate_state"]
            regime_context = company_ctx["regime_context"]
            durability = company_ctx["durability"]
            head_row_version = company_ctx["source_versions"]["company_dossier_row_version"]
        else:
            thesis_trajectory = {
                "confidence_current": 0.0,
                "confidence_previous": None,
                "delta": 0.0,
                "direction": "unknown",
                "version_count": 0,
                "stance": "",
                "primary_concern": "",
            }
            debate_state = {"current_lean": "balanced", "version": 1, "confidence": 0.0}
            regime_context = {
                "conviction_trend": "stable",
                "cycle_position": "unknown",
                "horizon_hint": "investment",
                "staleness_state": "fresh",
            }
            durability = {"catalyst_proximity_days": None, "analog_time_to_trough_days": None}
            head_row_version = 0

        # ── Source versions ───────────────────────────────────────────────────
        source_versions = {
            "dossier_failure_mode_id": fm.id,
            "dossier_failure_mode_matched_at": (
                fm.matched_at.isoformat() if getattr(fm, "matched_at", None) else ""
            ),
            "failure_mode_sequence_stage": _safe_int(fm.sequence_stage, 1),
            "analog_id": fm.analog_id or "",
            "company_dossier_row_version": head_row_version,
            "feature_schema": FAILURE_MODE_FEATURE_VERSION,
        }

        # ── Staleness indicators ──────────────────────────────────────────────
        staleness_indicators = {
            "dossier_staleness_state": regime_context.get("staleness_state", "fresh"),
            "has_similarity_peers": len(similarity_peers) > 0,
            "has_analogs": len(analog_set) > 0,
            "thesis_is_recent": company_ctx["staleness_indicators"]["thesis_is_recent"]
                if company_ctx else False,
            "stage_is_advanced": _safe_int(fm.sequence_stage, 1) >= 3,
        }

        return {
            "entity_type": "failure_mode",
            "entity_key": failure_mode_id,
            "failure_mode": failure_mode_info,
            "analog_set": analog_set,
            "analog_count": len(analog_set),
            "similarity_peers": similarity_peers,
            "similarity_peer_count": len(similarity_peers),
            "similarity_avg_score": _avg(peer_scores),
            "thesis_trajectory": thesis_trajectory,
            "debate_state": debate_state,
            "regime_context": regime_context,
            "durability": durability,
            "source_versions": source_versions,
            "staleness_indicators": staleness_indicators,
            "feature_schema": FAILURE_MODE_FEATURE_VERSION,
        }

    except Exception as exc:
        logger.debug(
            "[forecast_feature_builder] build_failure_mode_forecast_features failed for %s: %r",
            failure_mode_id, exc,
        )
        return None


async def build_failure_mode_forecast_features_for_all(
    session,
    *,
    limit: Optional[int] = None,
) -> List[dict]:
    """Build T4 feature objects for every dossier_failure_mode row in the system.

    Returns a list of feature dicts (no None entries).  Returns [] when
    session is None or on error.
    """
    if session is None:
        return []
    try:
        from sqlalchemy import select
        from app.db.models import DossierFailureMode

        stmt = select(DossierFailureMode.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        ids = list((await session.execute(stmt)).scalars().all())

        results: List[dict] = []
        for fm_id in ids:
            features = await build_failure_mode_forecast_features(session, fm_id)
            if features is not None:
                results.append(features)
        return results

    except Exception as exc:
        logger.debug(
            "[forecast_feature_builder] build_failure_mode_forecast_features_for_all failed: %r",
            exc,
        )
        return []
