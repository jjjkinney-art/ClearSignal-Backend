"""
Phase 10A · Slice 6 — Shadow producer bindings.

Binds existing analytical services to the loop's producer registry in
shadow (no-delivery) mode.  Producers run real analysis logic but:

  - Do NOT create DeliveryLedger rows.
  - Do NOT create Notification rows.
  - Do NOT call any external API.
  - Do NOT make LLM calls.
  - Produce a payload_json summary that is logged but NOT persisted.

All three services used here are pure / deterministic / file-I/O only:
  - watchlist_service      — JSON file reads, no LLM
  - morning_brief_service  — pure deterministic, no LLM
  - watchlist_themes       — pure deterministic lookup

Producer signature (spec §2.3):
    async def producer(session, job, run_id, holder_id, fence_token) -> ProducerResult

Registered job types
--------------------
    watchlist_scan   — read watchlist, run enrichment, emit shadow summary
    morning_brief    — generate morning brief from watchlist state, no delivery
    timeline_rollup  — stub; not yet wired to timeline logic → skipped_stale

Usage
-----
Call `register_all_shadow_producers()` during application startup AFTER
`loop_enabled` is confirmed.  It is idempotent — safe to call twice.

    from app.services.loop_producers import register_all_shadow_producers
    register_all_shadow_producers()

Safety
------
LOOP_ENABLED defaults to False in settings — these producers only execute
when the gate is opened explicitly.  All failures are caught and returned
as ProducerResult(outcome="failed") so the scheduler never crashes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.loop_scheduler_service import (
    ProducerResult,
    register_producer,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Job-type constants
# ---------------------------------------------------------------------------

WATCHLIST_SCAN  = "watchlist_scan"
MORNING_BRIEF   = "morning_brief"
TIMELINE_ROLLUP = "timeline_rollup"

REGISTERED_JOB_TYPES = [WATCHLIST_SCAN, MORNING_BRIEF, TIMELINE_ROLLUP]


# ---------------------------------------------------------------------------
# Lazy service accessors
# (imported inside functions so that import-time failures don't break the
#  scheduler module — shadow producers degrade gracefully if their upstream
#  services are unavailable)
# ---------------------------------------------------------------------------

def _get_watchlist_service():
    from app.services.watchlist_service import watchlist_service as svc
    return svc


def _get_enrich_fn():
    from app.services.watchlist_service import enrich_watchlist_intelligence
    return enrich_watchlist_intelligence


def _get_brief_fn():
    from app.services.morning_brief_service import generate_morning_brief_v2
    return generate_morning_brief_v2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# § watchlist_scan producer
# ---------------------------------------------------------------------------

async def produce_watchlist_scan(
    session: Any,
    job: Any,
    run_id: str,
    holder_id: str,
    fence_token: int,
) -> ProducerResult:
    """
    Shadow watchlist scan.

    Reads the file-based watchlist, runs `enrich_watchlist_intelligence`,
    and returns a summary payload.  No notifications, no delivery rows.
    """
    try:
        wl_svc    = _get_watchlist_service()
        enrich_fn = _get_enrich_fn()

        entries = wl_svc.get_watchlist()
        if not entries:
            logger.debug("[producer:watchlist_scan] empty watchlist — skipped_stale")
            return ProducerResult(
                outcome="skipped_stale",
                items_emitted=0,
                payload_json={"reason": "empty_watchlist", "shadow": True},
            )

        changes = wl_svc.get_material_changes(limit=20)
        enriched = enrich_fn(entries)

        attention = [e.ticker for e in enriched if e.thesis_stability in ("breaking", "shifting")]
        drifting  = [e.ticker for e in enriched if e.thesis_stability == "drifting"]

        payload = {
            "ticker_count": len(entries),
            "tickers": [e.ticker for e in entries],
            "material_changes_found": len(changes),
            "attention_required": attention,
            "drifting": drifting,
            "generated_at": _now_iso(),
            "shadow": True,
        }

        logger.info(
            "[producer:watchlist_scan] shadow scan complete — "
            "tickers=%d changes=%d attention=%d",
            len(entries), len(changes), len(attention),
        )
        return ProducerResult(
            outcome="succeeded",
            items_emitted=len(entries),
            payload_json=payload,
        )

    except Exception as exc:
        logger.exception("[producer:watchlist_scan] failed: %r", exc)
        return ProducerResult(
            outcome="failed",
            error=f"watchlist_scan:{exc!r}",
        )


# ---------------------------------------------------------------------------
# § morning_brief producer
# ---------------------------------------------------------------------------

async def produce_morning_brief(
    session: Any,
    job: Any,
    run_id: str,
    holder_id: str,
    fence_token: int,
) -> ProducerResult:
    """
    Shadow morning brief generation.

    Calls `generate_morning_brief_v2` (pure deterministic, zero LLM calls)
    with current watchlist state.  Returns the brief as payload_json.
    No delivery, no notifications.
    """
    try:
        wl_svc   = _get_watchlist_service()
        brief_fn = _get_brief_fn()

        entries = wl_svc.get_watchlist()
        if not entries:
            logger.debug("[producer:morning_brief] empty watchlist — skipped_stale")
            return ProducerResult(
                outcome="skipped_stale",
                items_emitted=0,
                payload_json={"reason": "empty_watchlist", "shadow": True},
            )

        changes = wl_svc.get_material_changes(limit=50)

        brief = brief_fn(
            watchlist_entries=entries,
            recent_material_changes=changes,
        )

        payload = brief.model_dump()
        payload["shadow"] = True

        logger.info(
            "[producer:morning_brief] shadow brief generated — "
            "tickers=%d attention=%d top_movers=%s",
            len(entries),
            len(brief.attention_required),
            brief.top_movers[:3],
        )
        return ProducerResult(
            outcome="succeeded",
            items_emitted=len(entries),
            payload_json=payload,
        )

    except Exception as exc:
        logger.exception("[producer:morning_brief] failed: %r", exc)
        return ProducerResult(
            outcome="failed",
            error=f"morning_brief:{exc!r}",
        )


# ---------------------------------------------------------------------------
# § timeline_rollup producer (stub)
# ---------------------------------------------------------------------------

async def produce_timeline_rollup(
    session: Any,
    job: Any,
    run_id: str,
    holder_id: str,
    fence_token: int,
) -> ProducerResult:
    """
    Timeline rollup stub.

    Not yet wired to timeline roll-up logic.  Returns skipped_stale
    immediately so the job is visible in the scheduler trace without
    consuming resources or dead-lettering.  Wired in Slice 7+.
    """
    logger.debug("[producer:timeline_rollup] stub — skipped_stale")
    return ProducerResult(
        outcome="skipped_stale",
        items_emitted=0,
        payload_json={"reason": "timeline_rollup_not_implemented", "shadow": True},
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_all_shadow_producers() -> None:
    """
    Register all shadow producers into the scheduler's global registry.

    Idempotent — safe to call multiple times (each call overwrites the
    prior registration, which is a no-op if the same function is bound).

    Call this once during application startup, after confirming the loop
    settings are in place.

        from app.services.loop_producers import register_all_shadow_producers
        register_all_shadow_producers()
    """
    register_producer(WATCHLIST_SCAN,  produce_watchlist_scan)
    register_producer(MORNING_BRIEF,   produce_morning_brief)
    register_producer(TIMELINE_ROLLUP, produce_timeline_rollup)
    logger.info(
        "[producers] registered shadow producers: %s",
        ", ".join(REGISTERED_JOB_TYPES),
    )
