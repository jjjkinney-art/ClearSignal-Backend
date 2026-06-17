"""
Similarity Observability Service — Phase 11 · Slice 8.

Produces a single consistent, null-safe, DB-down-safe snapshot of the
Phase 11 similarity subsystem. Intended callers:

  - GET /admin/similarity-status          (production admin endpoint)
  - tests/validate_11_similarity_shadow.py (deployment validation script)
  - integration tests

Design principles (mirrors billing_observability_service.py /
delivery_observability_service.py / portfolio_observability_service.py)
--------------------------------------------------------------------------
  - Never raises. All DB calls wrapped in try/except; degraded to 0/null.
  - No secrets — there are none in Phase 11's flag set, but the same
    discipline applies: only booleans/strings/counts, never raw payloads.
  - Read-only. This module never builds, scores, rebuilds, or writes
    anything — it only counts and reads timestamps from existing rows.
  - Deterministic schema. All keys always present; missing data -> 0/null.

Snapshot structure
-------------------
  flags                       — the 4 Phase 11 similarity_* settings
  db_available                — False if DB was unreachable this call
  vector_counts                — {failure_mode, company, thesis} row counts
  edge_counts                  — {total, floor_passed, expired}
  edge_counts_by_target_type   — {failure_mode, company, thesis} edge counts
  shadow_delivery_count        — delivery_ledger rows with channel="similarity_shadow"
  shadow_escalated_count       — those rows that reached status="delivered" (should be 0 — see safe_state)
  live_notification_count      — notifications rows with kind="similarity" (should be 0 — nothing ever writes this kind)
  latest_vector_built_at       — max(similarity_feature_vector.built_at), ISO-8601 or None
  latest_edge_scored_at        — max(similarity_edge.built_at), ISO-8601 or None
  safe_state                  — see below
  snapshot_utc                — ISO-8601 timestamp of this snapshot

safe_state is True when ALL of:
  - similarity_shadow flag is True
  - shadow_escalated_count == 0  (no similarity_shadow row was ever promoted
    to "delivered" — public/live delivery for similarity has never fired)
  - live_notification_count == 0  (no Notification row has ever been
    tagged kind="similarity" — nothing currently in the codebase writes
    this, so a nonzero count here would itself indicate a regression)

"No forecasting consumers are active" is a structural invariant of the
Phase 11 codebase (no forecasting/conviction module imports any
similarity_* module) rather than something measurable at request time;
it is verified statically by tests/validate_11_similarity_shadow.py via
an import-graph check, not recomputed on every snapshot call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_KNOWN_TARGET_TYPES = ("failure_mode", "company", "thesis")

# Mirrors app.services.similarity_delivery_service.SIMILARITY_DELIVERY_CHANNEL.
# Duplicated as a literal (not imported) so this read-only observability
# module has zero dependency on the delivery module's import graph.
SIMILARITY_DELIVERY_CHANNEL = "similarity_shadow"


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
            "similarity_build_enabled": bool(settings.similarity_build_enabled),
            "similarity_scoring_enabled": bool(settings.similarity_scoring_enabled),
            "similarity_targets_enabled": str(settings.similarity_targets_enabled or ""),
            "similarity_shadow": bool(settings.similarity_shadow),
        }
    except Exception as exc:
        logger.debug("[similarity_observability] flags section failed: %r", exc)
        return {
            "similarity_build_enabled": False,
            "similarity_scoring_enabled": False,
            "similarity_targets_enabled": "",
            "similarity_shadow": True,
        }


def _empty_vector_counts() -> Dict[str, int]:
    return {t: 0 for t in _KNOWN_TARGET_TYPES}


def _empty_edge_counts_by_target() -> Dict[str, int]:
    return {t: 0 for t in _KNOWN_TARGET_TYPES}


async def build_similarity_observability_snapshot(session) -> Dict[str, Any]:
    """Build the full Phase 11 observability snapshot. Never raises."""
    flags = _flags_section()

    if session is None:
        return {
            "flags": flags,
            "db_available": False,
            "vector_counts": _empty_vector_counts(),
            "edge_counts": {"total": 0, "floor_passed": 0, "expired": 0},
            "edge_counts_by_target_type": _empty_edge_counts_by_target(),
            "shadow_delivery_count": 0,
            "shadow_escalated_count": 0,
            "live_notification_count": 0,
            "latest_vector_built_at": None,
            "latest_edge_scored_at": None,
            # Nothing is running at all -> trivially nothing unsafe is happening.
            "safe_state": True,
            "snapshot_utc": _now_iso(),
        }

    try:
        from sqlalchemy import select, func
        from app.db.models import SimilarityFeatureVector, SimilarityEdge, DeliveryLedger, Notification

        vector_counts = _empty_vector_counts()
        for target_type in _KNOWN_TARGET_TYPES:
            count = (
                await session.execute(
                    select(func.count()).select_from(SimilarityFeatureVector).where(
                        SimilarityFeatureVector.target_type == target_type
                    )
                )
            ).scalar_one()
            vector_counts[target_type] = int(count or 0)

        total_edges = (
            await session.execute(select(func.count()).select_from(SimilarityEdge))
        ).scalar_one()
        floor_passed_edges = (
            await session.execute(
                select(func.count()).select_from(SimilarityEdge).where(
                    SimilarityEdge.floor_passed.is_(True)
                )
            )
        ).scalar_one()

        now = datetime.now(timezone.utc)
        expired_edges = (
            await session.execute(
                select(func.count()).select_from(SimilarityEdge).where(
                    SimilarityEdge.expires_at <= now
                )
            )
        ).scalar_one()

        edge_counts_by_target = _empty_edge_counts_by_target()
        for target_type in _KNOWN_TARGET_TYPES:
            count = (
                await session.execute(
                    select(func.count()).select_from(SimilarityEdge).where(
                        SimilarityEdge.target_type == target_type
                    )
                )
            ).scalar_one()
            edge_counts_by_target[target_type] = int(count or 0)

        shadow_delivery_count = (
            await session.execute(
                select(func.count()).select_from(DeliveryLedger).where(
                    DeliveryLedger.channel == SIMILARITY_DELIVERY_CHANNEL
                )
            )
        ).scalar_one()
        shadow_escalated_count = (
            await session.execute(
                select(func.count()).select_from(DeliveryLedger).where(
                    DeliveryLedger.channel == SIMILARITY_DELIVERY_CHANNEL,
                    DeliveryLedger.status == "delivered",
                )
            )
        ).scalar_one()

        live_notification_count = (
            await session.execute(
                select(func.count()).select_from(Notification).where(
                    Notification.kind == "similarity"
                )
            )
        ).scalar_one()

        latest_vector_built_at = (
            await session.execute(select(func.max(SimilarityFeatureVector.built_at)))
        ).scalar_one()
        latest_edge_scored_at = (
            await session.execute(select(func.max(SimilarityEdge.built_at)))
        ).scalar_one()

        safe_state = (
            flags["similarity_shadow"] is True
            and int(shadow_escalated_count or 0) == 0
            and int(live_notification_count or 0) == 0
        )

        return {
            "flags": flags,
            "db_available": True,
            "vector_counts": vector_counts,
            "edge_counts": {
                "total": int(total_edges or 0),
                "floor_passed": int(floor_passed_edges or 0),
                "expired": int(expired_edges or 0),
            },
            "edge_counts_by_target_type": edge_counts_by_target,
            "shadow_delivery_count": int(shadow_delivery_count or 0),
            "shadow_escalated_count": int(shadow_escalated_count or 0),
            "live_notification_count": int(live_notification_count or 0),
            "latest_vector_built_at": _iso_or_none(latest_vector_built_at),
            "latest_edge_scored_at": _iso_or_none(latest_edge_scored_at),
            "safe_state": safe_state,
            "snapshot_utc": _now_iso(),
        }
    except Exception as exc:
        logger.debug("[similarity_observability] build_similarity_observability_snapshot failed: %r", exc)
        return {
            "flags": flags,
            "db_available": False,
            "vector_counts": _empty_vector_counts(),
            "edge_counts": {"total": 0, "floor_passed": 0, "expired": 0},
            "edge_counts_by_target_type": _empty_edge_counts_by_target(),
            "shadow_delivery_count": 0,
            "shadow_escalated_count": 0,
            "live_notification_count": 0,
            "latest_vector_built_at": None,
            "latest_edge_scored_at": None,
            "safe_state": True,
            "snapshot_utc": _now_iso(),
        }
