"""
Decision Calibration Service — Phase 13 · Slice 9.

Measures decision-priority quality over time by recording observed
significance outcomes against stored ranking snapshots, computing rank-order
agreement, stability, churn, false-prominence, and missed-importance metrics,
and detecting calibration drift.

Core rule: calibration OBSERVES rankings and outcomes; it never modifies any
stored decision_priority row, forecast_vector, conviction, or source table.

Immutability invariant
-----------------------
  record_decision_outcome() only ever calls add_ranking_log() — an
  insert-only function with snapshot_reason="calibration_outcome".  No
  update or delete path exists anywhere in this module.  Verified by AST
  inspection in tests.

Storage
-------
  All writes go to decision_ranking_log via add_ranking_log().
  All reads come from list_ranking_logs() / count_ranking_logs().
  No other table is written by this module.

Outcome attribution pattern
---------------------------
  When an outcome is observed (a high-priority item turned out to be material
  or immaterial), the caller appends a NEW row to decision_ranking_log keyed
  to the same priority_id with snapshot_reason="calibration_outcome" and
  realized_significance set.  The original snapshot row is never touched.

Metrics
-------
  rank_order_agreement
    Among decisions that received realized_significance="material", what
    fraction had their priority bucket in {critical, high} at the time the
    outcome was recorded?  High agreement = the engine correctly elevated
    important items.

  priority_stability
    For each priority_id that has ≥2 non-outcome snapshot rows, was the
    decision_priority bucket the same in the first snapshot as in the latest?
    Averaged across all such priorities.  High stability = the ranking is
    consistent over time, not flip-flopping.

  priority_churn
    1.0 - stability_rate.  High churn = the ranking oscillates between runs.

  false_prominence
    Among decisions that were ranked critical/high AND later received an
    outcome attribution, what fraction received realized_significance=
    "immaterial"?  High false_prominence = expensive attention on signals
    that did not matter.

  missed_importance
    Among decisions that received realized_significance="material", what
    fraction had their priority bucket in {low, informational}?  High
    missed_importance = the engine underranked signals that mattered.

Safety invariants (SP-5 / Phase 13 spec §0)
--------------------------------------------
  - No decision_priority row is written by this module.
  - No forecast_vector, conviction, stance, or LLM-prompt field is touched.
  - No delivery_ledger, Notification, or inbox row is written.
  - No buy/sell/hold, target price, position sizing, or recommendation
    language is present anywhere in this module.
  - Null-session safety: every function returns its safe empty default
    (None / {} / []) when session is None.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CALIBRATION_OUTCOME_REASON: str = "calibration_outcome"

SIGNIFICANCE_MATERIAL   = "material"
SIGNIFICANCE_IMMATERIAL = "immaterial"
SIGNIFICANCE_UNKNOWN    = "unknown"

SUPPORTED_SIGNIFICANCES = frozenset({
    SIGNIFICANCE_MATERIAL,
    SIGNIFICANCE_IMMATERIAL,
    SIGNIFICANCE_UNKNOWN,
})

_HIGH_ATTENTION_BUCKETS = frozenset({"critical", "high"})
_LOW_ATTENTION_BUCKETS  = frozenset({"low", "informational"})
_BUCKET_RANK: Dict[str, int] = {
    "critical": 4, "high": 3, "medium": 2, "low": 1, "informational": 0,
}

# Minimum outcome rows for a metric to be considered meaningful
MIN_SAMPLES: int = 5

# Minimum snapshot-pair count to report stability/churn meaningfully
MIN_STABILITY_SAMPLES: int = 3

CALIBRATION_SCHEMA_VERSION: int = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Outcome recording (append-only)
# ---------------------------------------------------------------------------

async def record_decision_outcome(
    session,
    *,
    priority_id: str,
    realized_significance: str,
    candidate_type: str = "",
    entity_type: str = "",
    entity_key: str = "",
    user_id: Optional[str] = None,
    decision_priority: str = "informational",
    decision_rank_score: float = 0.0,
    rank_position: int = 0,
    evaluated_at: Optional[datetime] = None,
) -> Optional[Any]:
    """Append one immutable outcome row to decision_ranking_log.

    Records that a previously-ranked decision turned out to be material,
    immaterial, or unknown.  Uses snapshot_reason="calibration_outcome" so
    readers can distinguish outcome rows from ranking snapshot rows.

    NEVER updates or deletes an existing row.

    Returns the new DecisionRankingLog ORM row, or None when session is None
    or an error occurs.
    """
    if session is None:
        return None
    if realized_significance not in SUPPORTED_SIGNIFICANCES:
        logger.debug(
            "[decision_calibration_service] unknown realized_significance %r — "
            "must be one of %s",
            realized_significance, sorted(SUPPORTED_SIGNIFICANCES),
        )
        return None
    try:
        from app.db.repositories.decision_repo import add_ranking_log
        return await add_ranking_log(
            session,
            priority_id           = priority_id,
            candidate_type        = candidate_type,
            entity_type           = entity_type,
            entity_key            = entity_key,
            user_id               = user_id,
            decision_priority     = decision_priority,
            decision_rank_score   = decision_rank_score,
            rank_position         = rank_position,
            snapshot_reason       = CALIBRATION_OUTCOME_REASON,
            realized_significance = realized_significance,
            evaluated_at          = evaluated_at,
        )
    except Exception as exc:
        logger.debug(
            "[decision_calibration_service] record_decision_outcome error: %r", exc
        )
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _field(row: Any, name: str, default=None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


async def _get_outcome_rows(
    session,
    candidate_type: Optional[str],
    limit: int,
) -> List[Any]:
    """Return calibration-outcome rows from decision_ranking_log."""
    from app.db.repositories.decision_repo import list_ranking_logs
    return await list_ranking_logs(
        session,
        candidate_type  = candidate_type,
        snapshot_reason = CALIBRATION_OUTCOME_REASON,
        limit           = limit,
    )


async def _get_snapshot_rows(
    session,
    candidate_type: Optional[str],
    limit: int,
) -> List[Any]:
    """Return non-outcome snapshot rows — all except calibration_outcome."""
    from app.db.repositories.decision_repo import list_ranking_logs
    from sqlalchemy import select
    from app.db.models import DecisionRankingLog

    # list_ranking_logs filters on snapshot_reason equality; we need !=.
    # Fall back to a direct query for this.
    if session is None:
        return []
    try:
        stmt = select(DecisionRankingLog).where(
            DecisionRankingLog.snapshot_reason != CALIBRATION_OUTCOME_REASON,
        )
        if candidate_type is not None:
            stmt = stmt.where(DecisionRankingLog.candidate_type == candidate_type)
        stmt = stmt.order_by(DecisionRankingLog.evaluated_at.asc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug(
            "[decision_calibration_service] _get_snapshot_rows error: %r", exc
        )
        return []


def _insufficient(sample_count: int, min_n: int = MIN_SAMPLES) -> bool:
    return sample_count < min_n


# ---------------------------------------------------------------------------
# Rank-order agreement
# ---------------------------------------------------------------------------

async def calculate_rank_order_agreement(
    session,
    *,
    candidate_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 500,
) -> Dict:
    """Compute rank-order agreement over recorded outcomes.

    Measures: among decisions that turned out to be material, what fraction
    were ranked critical or high at the time the outcome was recorded?

    Returns:
      {
        "agreement_rate":  float | None,
        "material_count":  int,
        "high_and_material": int,
        "sample_count":    int,
        "status":          "ok" | "insufficient_samples",
        "calibration_schema": int,
      }

    Returns {} when session is None.
    """
    if session is None:
        return {}
    try:
        rows = await _get_outcome_rows(session, candidate_type, limit)
        if entity_type is not None:
            rows = [r for r in rows if _field(r, "entity_type") == entity_type]

        material_rows = [
            r for r in rows
            if _field(r, "realized_significance") == SIGNIFICANCE_MATERIAL
        ]
        sample_count = len(material_rows)

        if _insufficient(sample_count):
            return {
                "agreement_rate":    None,
                "material_count":    sample_count,
                "high_and_material": 0,
                "sample_count":      sample_count,
                "status":            "insufficient_samples",
                "calibration_schema": CALIBRATION_SCHEMA_VERSION,
            }

        high_and_material = sum(
            1 for r in material_rows
            if _field(r, "decision_priority") in _HIGH_ATTENTION_BUCKETS
        )
        agreement_rate = round(high_and_material / sample_count, 6)

        return {
            "agreement_rate":    agreement_rate,
            "material_count":    sample_count,
            "high_and_material": high_and_material,
            "sample_count":      sample_count,
            "status":            "ok",
            "calibration_schema": CALIBRATION_SCHEMA_VERSION,
        }
    except Exception as exc:
        logger.debug(
            "[decision_calibration_service] calculate_rank_order_agreement error: %r", exc
        )
        return {}


# ---------------------------------------------------------------------------
# Priority stability
# ---------------------------------------------------------------------------

async def calculate_priority_stability(
    session,
    *,
    candidate_type: Optional[str] = None,
    limit: int = 1000,
) -> Dict:
    """Compute priority stability: fraction of priorities that kept the same
    bucket across their first and most-recent non-outcome snapshots.

    Returns:
      {
        "stability_rate":  float | None,
        "stable_count":    int,
        "unstable_count":  int,
        "sample_count":    int,    # priorities with ≥2 snapshots
        "status":          "ok" | "insufficient_samples",
        "calibration_schema": int,
      }

    Returns {} when session is None.
    """
    if session is None:
        return {}
    try:
        rows = await _get_snapshot_rows(session, candidate_type, limit)

        # Group by priority_id, sort by evaluated_at (already asc from query)
        by_priority: Dict[str, List[Any]] = {}
        for r in rows:
            pid = _field(r, "priority_id", "")
            by_priority.setdefault(pid, []).append(r)

        # Only consider priorities with ≥2 snapshot rows
        eligible = {
            pid: snaps for pid, snaps in by_priority.items() if len(snaps) >= 2
        }
        sample_count = len(eligible)

        if _insufficient(sample_count, MIN_STABILITY_SAMPLES):
            return {
                "stability_rate": None,
                "stable_count":   0,
                "unstable_count": 0,
                "sample_count":   sample_count,
                "status":         "insufficient_samples",
                "calibration_schema": CALIBRATION_SCHEMA_VERSION,
            }

        stable_count   = 0
        unstable_count = 0
        for snaps in eligible.values():
            first_bucket  = _field(snaps[0],  "decision_priority", "informational")
            latest_bucket = _field(snaps[-1], "decision_priority", "informational")
            if first_bucket == latest_bucket:
                stable_count += 1
            else:
                unstable_count += 1

        stability_rate = round(stable_count / sample_count, 6)

        return {
            "stability_rate": stability_rate,
            "stable_count":   stable_count,
            "unstable_count": unstable_count,
            "sample_count":   sample_count,
            "status":         "ok",
            "calibration_schema": CALIBRATION_SCHEMA_VERSION,
        }
    except Exception as exc:
        logger.debug(
            "[decision_calibration_service] calculate_priority_stability error: %r", exc
        )
        return {}


# ---------------------------------------------------------------------------
# Priority churn (inverse of stability)
# ---------------------------------------------------------------------------

async def calculate_priority_churn(
    session,
    *,
    candidate_type: Optional[str] = None,
    limit: int = 1000,
) -> Dict:
    """Compute priority churn: 1.0 - stability_rate.

    Returns:
      {
        "churn_rate":      float | None,
        "stable_count":    int,
        "unstable_count":  int,
        "sample_count":    int,
        "status":          "ok" | "insufficient_samples",
        "calibration_schema": int,
      }

    Returns {} when session is None.
    """
    if session is None:
        return {}
    try:
        stability = await calculate_priority_stability(
            session, candidate_type=candidate_type, limit=limit,
        )
        if not stability:
            return {}
        if stability.get("status") == "insufficient_samples":
            return {
                "churn_rate":    None,
                "stable_count":  stability.get("stable_count", 0),
                "unstable_count": stability.get("unstable_count", 0),
                "sample_count":  stability.get("sample_count", 0),
                "status":        "insufficient_samples",
                "calibration_schema": CALIBRATION_SCHEMA_VERSION,
            }
        sr = stability.get("stability_rate")
        churn_rate = round(1.0 - sr, 6) if sr is not None else None
        return {
            "churn_rate":    churn_rate,
            "stable_count":  stability.get("stable_count", 0),
            "unstable_count": stability.get("unstable_count", 0),
            "sample_count":  stability.get("sample_count", 0),
            "status":        "ok",
            "calibration_schema": CALIBRATION_SCHEMA_VERSION,
        }
    except Exception as exc:
        logger.debug(
            "[decision_calibration_service] calculate_priority_churn error: %r", exc
        )
        return {}


# ---------------------------------------------------------------------------
# False prominence
# ---------------------------------------------------------------------------

async def calculate_false_prominence(
    session,
    *,
    candidate_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 500,
) -> Dict:
    """Compute false-prominence rate: among decisions that were ranked
    critical/high AND later received an outcome, what fraction turned out to
    be immaterial?

    Returns:
      {
        "false_prominence_rate": float | None,
        "high_priority_count":   int,     # critical/high decisions with outcomes
        "false_prominent_count": int,     # those that were immaterial
        "sample_count":          int,
        "status":                "ok" | "insufficient_samples",
        "calibration_schema":    int,
      }

    Returns {} when session is None.
    """
    if session is None:
        return {}
    try:
        rows = await _get_outcome_rows(session, candidate_type, limit)
        if entity_type is not None:
            rows = [r for r in rows if _field(r, "entity_type") == entity_type]

        # Outcome rows for decisions that were ranked high/critical
        high_rows = [
            r for r in rows
            if _field(r, "decision_priority") in _HIGH_ATTENTION_BUCKETS
            and _field(r, "realized_significance") in {
                SIGNIFICANCE_MATERIAL, SIGNIFICANCE_IMMATERIAL
            }
        ]
        sample_count = len(high_rows)

        if _insufficient(sample_count):
            return {
                "false_prominence_rate": None,
                "high_priority_count":   sample_count,
                "false_prominent_count": 0,
                "sample_count":          sample_count,
                "status":                "insufficient_samples",
                "calibration_schema":    CALIBRATION_SCHEMA_VERSION,
            }

        false_count = sum(
            1 for r in high_rows
            if _field(r, "realized_significance") == SIGNIFICANCE_IMMATERIAL
        )
        rate = round(false_count / sample_count, 6)

        return {
            "false_prominence_rate": rate,
            "high_priority_count":   sample_count,
            "false_prominent_count": false_count,
            "sample_count":          sample_count,
            "status":                "ok",
            "calibration_schema":    CALIBRATION_SCHEMA_VERSION,
        }
    except Exception as exc:
        logger.debug(
            "[decision_calibration_service] calculate_false_prominence error: %r", exc
        )
        return {}


# ---------------------------------------------------------------------------
# Missed importance
# ---------------------------------------------------------------------------

async def calculate_missed_importance(
    session,
    *,
    candidate_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 500,
) -> Dict:
    """Compute missed-importance rate: among decisions that turned out to be
    material, what fraction were originally ranked low or informational?

    Returns:
      {
        "missed_importance_rate": float | None,
        "material_count":         int,
        "missed_count":           int,
        "sample_count":           int,
        "status":                 "ok" | "insufficient_samples",
        "calibration_schema":     int,
      }

    Returns {} when session is None.
    """
    if session is None:
        return {}
    try:
        rows = await _get_outcome_rows(session, candidate_type, limit)
        if entity_type is not None:
            rows = [r for r in rows if _field(r, "entity_type") == entity_type]

        material_rows = [
            r for r in rows
            if _field(r, "realized_significance") == SIGNIFICANCE_MATERIAL
        ]
        sample_count = len(material_rows)

        if _insufficient(sample_count):
            return {
                "missed_importance_rate": None,
                "material_count":         sample_count,
                "missed_count":           0,
                "sample_count":           sample_count,
                "status":                 "insufficient_samples",
                "calibration_schema":     CALIBRATION_SCHEMA_VERSION,
            }

        missed_count = sum(
            1 for r in material_rows
            if _field(r, "decision_priority") in _LOW_ATTENTION_BUCKETS
        )
        rate = round(missed_count / sample_count, 6)

        return {
            "missed_importance_rate": rate,
            "material_count":         sample_count,
            "missed_count":           missed_count,
            "sample_count":           sample_count,
            "status":                 "ok",
            "calibration_schema":     CALIBRATION_SCHEMA_VERSION,
        }
    except Exception as exc:
        logger.debug(
            "[decision_calibration_service] calculate_missed_importance error: %r", exc
        )
        return {}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

async def summarize_decision_calibration(
    session,
    *,
    candidate_type: Optional[str] = None,
    limit: int = 500,
) -> Dict:
    """Build a top-level calibration summary combining all metrics.

    Always returns a well-formed dict, even when session is None or no
    calibration data exists yet.

    Shape:
      {
        "total_outcomes_recorded": int,
        "rank_order_agreement":    <calculate_rank_order_agreement output>,
        "stability":               <calculate_priority_stability output>,
        "churn":                   <calculate_priority_churn output>,
        "false_prominence":        <calculate_false_prominence output>,
        "missed_importance":       <calculate_missed_importance output>,
        "calibration_schema":      int,
      }
    """
    empty: Dict = {
        "total_outcomes_recorded": 0,
        "rank_order_agreement":    {},
        "stability":               {},
        "churn":                   {},
        "false_prominence":        {},
        "missed_importance":       {},
        "calibration_schema":      CALIBRATION_SCHEMA_VERSION,
    }
    if session is None:
        return empty
    try:
        from app.db.repositories.decision_repo import count_ranking_logs

        total = await count_ranking_logs(
            session, snapshot_reason=CALIBRATION_OUTCOME_REASON,
        )

        (agreement, stability, churn, false_prom, missed) = (
            await calculate_rank_order_agreement(session, candidate_type=candidate_type, limit=limit),
            await calculate_priority_stability(session,   candidate_type=candidate_type, limit=limit * 2),
            await calculate_priority_churn(session,       candidate_type=candidate_type, limit=limit * 2),
            await calculate_false_prominence(session,     candidate_type=candidate_type, limit=limit),
            await calculate_missed_importance(session,    candidate_type=candidate_type, limit=limit),
        )

        return {
            "total_outcomes_recorded": total,
            "rank_order_agreement":    agreement,
            "stability":               stability,
            "churn":                   churn,
            "false_prominence":        false_prom,
            "missed_importance":       missed,
            "calibration_schema":      CALIBRATION_SCHEMA_VERSION,
        }
    except Exception as exc:
        logger.debug(
            "[decision_calibration_service] summarize_decision_calibration error: %r", exc
        )
        return empty
