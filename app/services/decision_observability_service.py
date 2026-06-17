"""
Decision Observability Service — Phase 13 · Slice 10.

Produces a single consistent, null-safe, DB-down-safe snapshot of the
entire Phase 13 Decision Intelligence subsystem.  Intended callers:

  - GET /admin/decision-status            (production admin endpoint)
  - tests/validate_13_decision_shadow.py  (deployment validation script)
  - integration tests

Design principles (mirrors forecast_observability_service.py)
-------------------------------------------------------------
  - Never raises.  All DB calls wrapped in try/except; degraded to 0/None.
  - No secrets — only booleans/strings/counts, never raw payloads or
    user content.
  - Read-only.  This module never builds, scores, rebuilds, or writes
    anything.  It only reads COUNT / MAX aggregates and flag values.
  - Deterministic schema.  All keys always present; missing data → 0/None.

Snapshot structure
------------------
  flags                        — all 6 decision_* settings
  db_available                 — False if DB was unreachable this call
  priority_count               — total decision_priority rows
  evidence_count               — total decision_evidence rows
  ranking_log_count            — total decision_ranking_log rows
  calibration_outcome_count    — ranking_log rows with snapshot_reason=
                                 "calibration_outcome"
  expired_priority_count       — decision_priority rows with expires_at <= now
  priority_count_by_bucket     — {critical: n, high: n, medium: n, low: n,
                                  informational: n}
  priority_count_by_type       — {forecast_candidate: n, risk_candidate: n, …}
  shadow_delivery_count        — delivery_ledger rows where channel=
                                 "decision_shadow"
  shadow_escalated_count       — those rows that reached status="delivered"
                                 (must be 0 in shadow mode)
  live_notification_count      — Notification rows of any kind created by the
                                 decision subsystem (must be 0 — no decision
                                 kind is registered)
  latest_priority_at           — max(decision_priority.built_at) ISO-8601 or None
  latest_calibration_at        — max(decision_ranking_log.evaluated_at) where
                                 snapshot_reason="calibration_outcome", or None
  safe_state                   — see below
  snapshot_utc                 — ISO-8601 timestamp of this snapshot

safe_state is True when ALL of:
  - decision_shadow == True
  - decision_delivery_enabled == False      (no live delivery)
  - shadow_escalated_count == 0             (no shadow row ever promoted)
  - live_notification_count == 0            (no decision Notification written)

SP-5 boundary
-------------
This module NEVER reads conviction, stance, verdict_rationale, or any
LLM-prompt field.  It NEVER writes decision_priority, decision_evidence,
decision_ranking_log, or any source table.  It only reads COUNT / MAX
aggregates from the decision_* tables plus delivery_ledger / notifications.
No buy/sell/hold, target price, or recommendation language is present.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (literals — not imported from delivery service to keep graph clean)
# ---------------------------------------------------------------------------

DECISION_DELIVERY_CHANNEL: str = "decision_shadow"
CALIBRATION_OUTCOME_REASON: str = "calibration_outcome"

_BUCKETS = ("critical", "high", "medium", "low", "informational")

_CANDIDATE_TYPES = (
    "forecast_candidate",
    "risk_candidate",
    "catalyst_candidate",
    "watchlist_candidate",
    "portfolio_exposure_candidate",
    "delivery_transition_candidate",
    "similarity_candidate",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_or_none(dt) -> Optional[str]:
    if dt is None:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _flags_section() -> Dict[str, Any]:
    try:
        from app.config import settings
        return {
            "decision_build_enabled":       bool(getattr(settings, "decision_build_enabled",       False)),
            "decision_scoring_enabled":     bool(getattr(settings, "decision_scoring_enabled",     False)),
            "decision_delivery_enabled":    bool(getattr(settings, "decision_delivery_enabled",    False)),
            "decision_shadow":              bool(getattr(settings, "decision_shadow",               True)),
            "decision_targets_enabled":     str( getattr(settings, "decision_targets_enabled",     "") or ""),
            "decision_calibration_enabled": bool(getattr(settings, "decision_calibration_enabled", False)),
        }
    except Exception as exc:
        logger.debug("[decision_observability] flags section failed: %r", exc)
        return {
            "decision_build_enabled":       False,
            "decision_scoring_enabled":     False,
            "decision_delivery_enabled":    False,
            "decision_shadow":              True,
            "decision_targets_enabled":     "",
            "decision_calibration_enabled": False,
        }


def _empty_by_bucket() -> Dict[str, int]:
    return {b: 0 for b in _BUCKETS}


def _empty_by_type() -> Dict[str, int]:
    return {t: 0 for t in _CANDIDATE_TYPES}


def _empty_snapshot(flags: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "flags":                     flags,
        "db_available":              False,
        "priority_count":            0,
        "evidence_count":            0,
        "ranking_log_count":         0,
        "calibration_outcome_count": 0,
        "expired_priority_count":    0,
        "priority_count_by_bucket":  _empty_by_bucket(),
        "priority_count_by_type":    _empty_by_type(),
        "shadow_delivery_count":     0,
        "shadow_escalated_count":    0,
        "live_notification_count":   0,
        "latest_priority_at":        None,
        "latest_calibration_at":     None,
        "safe_state":                True,
        "snapshot_utc":              _now_iso(),
    }


# ---------------------------------------------------------------------------
# Main snapshot builder
# ---------------------------------------------------------------------------

async def build_decision_observability_snapshot(session) -> Dict[str, Any]:
    """Build the full Phase 13 observability snapshot.  Never raises."""
    flags = _flags_section()

    if session is None:
        return _empty_snapshot(flags)

    try:
        from sqlalchemy import select, func
        from app.db.models import (
            DecisionPriority,
            DecisionEvidence,
            DecisionRankingLog,
            DeliveryLedger,
            Notification,
        )

        now = datetime.now(timezone.utc)

        # ── decision_priority ──────────────────────────────────────────────
        priority_count = int(
            (await session.execute(
                select(func.count()).select_from(DecisionPriority)
            )).scalar_one() or 0
        )

        expired_priority_count = int(
            (await session.execute(
                select(func.count()).select_from(DecisionPriority).where(
                    DecisionPriority.expires_at <= now
                )
            )).scalar_one() or 0
        )

        by_bucket = _empty_by_bucket()
        for bucket in _BUCKETS:
            count = (await session.execute(
                select(func.count()).select_from(DecisionPriority).where(
                    DecisionPriority.decision_priority == bucket
                )
            )).scalar_one()
            by_bucket[bucket] = int(count or 0)

        by_type = _empty_by_type()
        for ctype in _CANDIDATE_TYPES:
            count = (await session.execute(
                select(func.count()).select_from(DecisionPriority).where(
                    DecisionPriority.candidate_type == ctype
                )
            )).scalar_one()
            by_type[ctype] = int(count or 0)

        latest_priority_at = (
            await session.execute(select(func.max(DecisionPriority.built_at)))
        ).scalar_one()

        # ── decision_evidence ──────────────────────────────────────────────
        evidence_count = int(
            (await session.execute(
                select(func.count()).select_from(DecisionEvidence)
            )).scalar_one() or 0
        )

        # ── decision_ranking_log ───────────────────────────────────────────
        ranking_log_count = int(
            (await session.execute(
                select(func.count()).select_from(DecisionRankingLog)
            )).scalar_one() or 0
        )

        calibration_outcome_count = int(
            (await session.execute(
                select(func.count()).select_from(DecisionRankingLog).where(
                    DecisionRankingLog.snapshot_reason == CALIBRATION_OUTCOME_REASON
                )
            )).scalar_one() or 0
        )

        latest_calibration_at = (
            await session.execute(
                select(func.max(DecisionRankingLog.evaluated_at)).where(
                    DecisionRankingLog.snapshot_reason == CALIBRATION_OUTCOME_REASON
                )
            )
        ).scalar_one()

        # ── delivery_ledger ────────────────────────────────────────────────
        shadow_delivery_count = int(
            (await session.execute(
                select(func.count()).select_from(DeliveryLedger).where(
                    DeliveryLedger.channel == DECISION_DELIVERY_CHANNEL
                )
            )).scalar_one() or 0
        )

        shadow_escalated_count = int(
            (await session.execute(
                select(func.count()).select_from(DeliveryLedger).where(
                    DeliveryLedger.channel == DECISION_DELIVERY_CHANNEL,
                    DeliveryLedger.status == "delivered",
                )
            )).scalar_one() or 0
        )

        # ── notifications ──────────────────────────────────────────────────
        # No "decision" kind is ever registered; this must always return 0.
        live_notification_count = int(
            (await session.execute(
                select(func.count()).select_from(Notification).where(
                    Notification.kind.like("decision%")
                )
            )).scalar_one() or 0
        )

        # ── safe_state ─────────────────────────────────────────────────────
        safe_state = (
            flags["decision_shadow"] is True
            and flags["decision_delivery_enabled"] is False
            and shadow_escalated_count == 0
            and live_notification_count == 0
        )

        return {
            "flags":                     flags,
            "db_available":              True,
            "priority_count":            priority_count,
            "evidence_count":            evidence_count,
            "ranking_log_count":         ranking_log_count,
            "calibration_outcome_count": calibration_outcome_count,
            "expired_priority_count":    expired_priority_count,
            "priority_count_by_bucket":  by_bucket,
            "priority_count_by_type":    by_type,
            "shadow_delivery_count":     shadow_delivery_count,
            "shadow_escalated_count":    shadow_escalated_count,
            "live_notification_count":   live_notification_count,
            "latest_priority_at":        _iso_or_none(latest_priority_at),
            "latest_calibration_at":     _iso_or_none(latest_calibration_at),
            "safe_state":                safe_state,
            "snapshot_utc":              _now_iso(),
        }

    except Exception as exc:
        logger.debug(
            "[decision_observability] build_decision_observability_snapshot failed: %r", exc
        )
        return _empty_snapshot(flags)
