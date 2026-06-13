"""
Phase 10A · Slice 8 — Delivery boundary (shadow mode only).

Design principle
----------------
Generation and delivery are separate concerns.  A producer emits content;
delivery decides whether, when, and to whom it reaches a user.  In Slice 8
the channel is entirely dark: ledger records are created and drained in
shadow mode with no external transport.

Shadow flush ("delivered_shadow")
----------------------------------
flush_pending_shadow() processes every pending DeliveryLedger row through
the guardrail stack.  Rows that pass all guardrails are marked
"delivered_shadow" (a new status value not used outside this slice).  Rows
that fail a guardrail are marked "suppressed".  No external sends occur.
No Notification rows are created.

Guardrails (suppress, never send)
----------------------------------
Evaluated in order; first hit wins:

  1. quiet_hours   — delivery time falls in the quiet window
                     (configurable start/end UTC hour, default 22:00–07:00)
  2. daily_cap     — per-channel delivered count today already ≥ cap
                     (default 20 per channel per target_key per UTC day)
  3. mute_until    — not_before_utc is set and now < not_before_utc
  4. severity_floor — payload_json.severity is below the minimum required
                     (default floor "info"; only "alert"/"critical" survive
                     when the payload carries a severity field)

Guardrail checks in Slice 8 operate on the ledger row and any payload
metadata attached by the caller via enqueue().  They do NOT query user
preferences or external systems — those come in a later slice.

Public API
----------
    enqueue(session, user_id, channel, target_key, payload, *,
            artifact_ref, severity, not_before_utc)
        -> DeliveryResult         — creates pending ledger row or suppresses
                                    on duplicate content_key

    flush_pending_shadow(session, *, now, limit)
        -> List[DeliveryResult]   — drains pending rows, returns audit trail

    DeliveryResult(status, content_key, channel, target_key, reason,
                   payload_json, delivery_id)

Null-object safety
------------------
    session=None → enqueue returns DeliveryResult(status="skipped", …)
                   flush_pending_shadow returns []
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.repositories import loop_repo
from app.services.loop_idempotency_service import (
    build_content_key,
    build_payload_hash,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Delivery status constants
# ---------------------------------------------------------------------------

STATUS_DELIVERED_SHADOW     = "delivered_shadow"
STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
STATUS_FAILED               = "failed"
STATUS_SKIPPED              = "skipped"

# Guardrail reason constants
REASON_DUPLICATE            = "duplicate_content_key"
REASON_QUIET_HOURS          = "quiet_hours"
REASON_DAILY_CAP            = "daily_cap"
REASON_MUTE_UNTIL           = "mute_until"
REASON_SEVERITY_FLOOR       = "severity_floor"
REASON_NO_SESSION           = "no_session"
REASON_SHADOW_DRAIN         = "shadow_drain"
# Phase 10C · Slice 4: ranking triage reasons
REASON_RANKING_SUPPRESS     = "ranking_suppressed"
REASON_DELIVERY_DISABLED    = "delivery_disabled"
# Phase 10C · Slice 6: relevance recheck reasons (mirror delivery_relevance_service constants)
REASON_RECHECK              = "relevance_recheck"   # fallback if service returns no specific reason


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class DeliveryResult:
    """Outcome record from one enqueue() or flush_pending_shadow() operation.

    Attributes
    ----------
    status       : One of the STATUS_* constants above.
    content_key  : 64-hex content dedup key (empty string if not computed).
    channel      : "in_app" | "email" | "push" (or custom).
    target_key   : User or entity the delivery is addressed to.
    reason       : Human-readable reason string (guardrail name or empty).
    payload_json : Snapshot of the payload that was queued (may be None).
    delivery_id  : DeliveryLedger row id, or None if no row was created.
    """
    status:       str
    content_key:  str
    channel:      str
    target_key:   str
    reason:       str = ""
    payload_json: Optional[Dict] = None
    delivery_id:  Optional[str] = None


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _cfg_quiet_hours_start() -> int:
    try:
        from app.config import settings
        return settings.delivery_quiet_hours_start
    except Exception:
        return 22  # 10 PM UTC


def _cfg_quiet_hours_end() -> int:
    try:
        from app.config import settings
        return settings.delivery_quiet_hours_end
    except Exception:
        return 7   # 7 AM UTC


def _cfg_daily_cap() -> int:
    try:
        from app.config import settings
        return settings.delivery_daily_cap
    except Exception:
        return 20


def _cfg_severity_floor() -> str:
    try:
        from app.config import settings
        return settings.delivery_severity_floor
    except Exception:
        return "info"


# ---------------------------------------------------------------------------
# Guardrail helpers
# ---------------------------------------------------------------------------

_SEVERITY_RANK = {"info": 0, "warning": 1, "alert": 2, "critical": 3}


def _is_quiet_hour(now: datetime) -> bool:
    """Return True if *now* falls inside the configured quiet window."""
    start = _cfg_quiet_hours_start()
    end   = _cfg_quiet_hours_end()
    hour  = now.hour
    if start < end:
        # Same-day window e.g. 02:00–06:00
        return start <= hour < end
    else:
        # Overnight window e.g. 22:00–07:00 (wraps midnight)
        return hour >= start or hour < end


def _severity_passes(payload: Optional[Dict]) -> bool:
    """Return True if the payload severity meets or exceeds the floor.

    When the payload carries no severity field, the delivery passes —
    severity suppression only activates when the producer explicitly
    annotates severity.
    """
    if payload is None:
        return True
    sev = payload.get("severity")
    if sev is None:
        return True
    floor = _cfg_severity_floor()
    payload_rank = _SEVERITY_RANK.get(str(sev).lower(), 0)
    floor_rank   = _SEVERITY_RANK.get(floor.lower(), 0)
    return payload_rank >= floor_rank


async def _daily_cap_reached(
    session,
    channel: str,
    target_key: str,
    now: datetime,
) -> bool:
    """Return True if the per-channel daily delivery cap has been hit."""
    cap = _cfg_daily_cap()
    if cap <= 0:
        return False
    try:
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        # Compute UTC start-of-day
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if day_start.tzinfo is None:
            day_start = day_start.replace(tzinfo=timezone.utc)
        else:
            day_start = day_start.astimezone(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        # Count delivered (shadow or real) rows for this channel+target today
        result = await session.execute(
            select(func.count())
            .select_from(DeliveryLedger)
            .where(
                DeliveryLedger.channel == channel,
                DeliveryLedger.target_key == target_key,
                DeliveryLedger.status.in_([
                    "delivered", STATUS_DELIVERED_SHADOW,
                ]),
                DeliveryLedger.delivered_at >= day_start,
            )
        )
        count = result.scalar() or 0
        return count >= cap
    except Exception as exc:
        logger.warning("[delivery] _daily_cap_reached query failed: %r", exc)
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def enqueue(
    session,
    user_id: str,
    channel: str,
    target_key: str,
    payload: Dict,
    *,
    artifact_ref: Optional[str] = None,
    severity: Optional[str] = None,
    not_before_utc: Optional[datetime] = None,
) -> DeliveryResult:
    """
    Create a pending delivery ledger row for one artifact.

    Parameters
    ----------
    session       : AsyncSession or None.
    user_id       : Recipient identifier (user id or "global").
    channel       : "in_app" | "email" | "push".
    target_key    : Entity the delivery is about (ticker, user, …).
    payload       : JSON-serialisable dict; content is hashed for dedup.
    artifact_ref  : Optional FK to source artifact.
    severity      : Optional severity string annotated by the producer.
    not_before_utc: Delay delivery until this time (quiet hours / cap).

    Returns
    -------
    DeliveryResult — always returns, never raises.
    """
    if session is None:
        return DeliveryResult(
            status=STATUS_SKIPPED,
            content_key="",
            channel=channel,
            target_key=target_key,
            reason=REASON_NO_SESSION,
            payload_json=payload,
        )

    # Attach severity to payload snapshot so guardrails see it
    payload_snapshot = dict(payload)
    if severity is not None:
        payload_snapshot["severity"] = severity

    payload_hash = build_payload_hash(payload_snapshot)
    content_key  = build_content_key(user_id, channel, target_key, payload_hash)

    # Severity floor — check before creating any row (backward-compat guardrail)
    if not _severity_passes(payload_snapshot):
        logger.debug(
            "[delivery] severity_floor suppressed %s/%s sev=%r",
            channel, target_key, payload_snapshot.get("severity"),
        )
        return DeliveryResult(
            status=STATUS_SUPPRESSED_GUARDRAIL,
            content_key=content_key,
            channel=channel,
            target_key=target_key,
            reason=REASON_SEVERITY_FLOOR,
            payload_json=payload_snapshot,
        )

    # ── Phase 10C · Slice 4: ranking triage ──────────────────────────────────
    # Load user prefs, rank the payload, and decide delivery_class.
    # Non-fatal: any import/runtime error falls through to the old behaviour.
    _canonical_sev = None   # type: Optional[str]
    _sev_rank_int  = None   # type: Optional[int]
    _ranking_meta  = {}     # type: Dict[str, Any]
    try:
        from app.db.repositories.delivery_prefs_repo import get_or_create_prefs as _get_prefs
        from app.services.intelligence_ranking_service import (
            rank_item as _rank_item,
            RankingDecision as _RD,
        )
        from app.services import severity_model as _sm

        _prefs = await _get_prefs(session, user_id=user_id, channel=channel)
        _user_min_sev = (_prefs.min_severity if _prefs else None) or _sm.INFO
        _enabled = _prefs.enabled if _prefs is not None else True

        # enabled=False → hard suppress regardless of severity
        if not _enabled:
            logger.debug(
                "[delivery] delivery_disabled user=%r channel=%r", user_id, channel
            )
            return DeliveryResult(
                status=STATUS_SUPPRESSED_GUARDRAIL,
                content_key=content_key,
                channel=channel,
                target_key=target_key,
                reason=REASON_DELIVERY_DISABLED,
                payload_json=payload_snapshot,
            )

        # Build a ranking-compatible item from the payload snapshot.
        # content_key is already computed; don't include ranking metadata in it.
        _rank_input = dict(payload_snapshot)
        _rank_input.setdefault("ticker", target_key)
        _rank_input.setdefault("source", "delivery")
        if "created_at" not in _rank_input:
            _rank_input["created_at"] = datetime.now(timezone.utc).isoformat()

        _ranked = _rank_item(_rank_input, user_min_severity=_user_min_sev)
        _canonical_sev = _ranked.canonical_severity
        _sev_rank_int  = _ranked.severity_rank

        _ranking_meta = {
            "delivery_class":    _ranked.delivery_class,
            "priority_score":    _ranked.priority_score,
            "canonical_severity": _canonical_sev,
            "severity_rank":     _sev_rank_int,
            "reason_codes":      list(_ranked.reason_codes),
        }

        if _ranked.delivery_class == _RD.SUPPRESS:
            logger.debug(
                "[delivery] ranking_suppressed %s/%s sev=%r score=%.4f reasons=%r",
                channel, target_key, _canonical_sev,
                _ranked.priority_score, _ranked.reason_codes,
            )
            return DeliveryResult(
                status=STATUS_SUPPRESSED_GUARDRAIL,
                content_key=content_key,
                channel=channel,
                target_key=target_key,
                reason=REASON_RANKING_SUPPRESS,
                payload_json={**payload_snapshot, "ranking": _ranking_meta},
            )
    except (ImportError, AttributeError):
        pass
    except Exception as _rank_exc:
        logger.warning("[delivery] ranking triage error (non-fatal): %r", _rank_exc)

    # ── Phase 10C · Slice 5: digest routing ──────────────────────────────────
    # When the ranking engine classifies an item as "digest", preserve it in a
    # digest_batches row (in addition to the ledger row, which stays as the
    # dedup anchor and audit trail).  Non-fatal.
    if _ranking_meta.get("delivery_class") == "digest":
        try:
            from app.services.digest_batch_service import (
                add_to_digest as _add_dig,
                period_bucket_for as _bucket_for,
            )
            _bucket = _bucket_for(datetime.now(timezone.utc))
            _digest_item: Dict[str, Any] = dict(payload_snapshot)
            _digest_item.setdefault("content_key", content_key)
            _digest_item.setdefault("target_key",  target_key)
            _digest_item.setdefault("canonical_severity", _canonical_sev)
            _digest_item.setdefault("severity_rank", _sev_rank_int)
            _digest_item["source"] = _digest_item.get("source") or "digest_routing"
            await _add_dig(
                session,
                user_id=user_id,
                channel=channel,
                period_bucket=_bucket,
                item=_digest_item,
                item_content_key=content_key,
            )
        except Exception as _dig_exc:
            logger.warning("[delivery] digest routing error (non-fatal): %r", _dig_exc)

    # Build the enriched payload that callers receive (ranking metadata embedded).
    _enriched_payload = (
        {**payload_snapshot, "ranking": _ranking_meta}
        if _ranking_meta
        else payload_snapshot
    )

    # Delegate to guard_delivery for dedup + savepoint
    row = await loop_repo.delivery_create(
        session,
        content_key=content_key,
        target_key=target_key,
        channel=channel,
        content_hash=payload_hash,
        artifact_ref=artifact_ref,
        not_before_utc=not_before_utc,
        canonical_severity=_canonical_sev,
        severity_rank=_sev_rank_int,
    )

    if row is None:
        # UNIQUE conflict — already queued or delivered
        logger.debug(
            "[delivery] enqueue: duplicate suppressed content_key=%s…", content_key[:12]
        )
        return DeliveryResult(
            status=STATUS_SUPPRESSED_DUPLICATE,
            content_key=content_key,
            channel=channel,
            target_key=target_key,
            reason=REASON_DUPLICATE,
            payload_json=_enriched_payload,
        )

    logger.debug(
        "[delivery] enqueued id=%s content_key=%s… channel=%s target=%s sev=%r class=%r",
        row.id, content_key[:12], channel, target_key,
        _canonical_sev, _ranking_meta.get("delivery_class"),
    )
    return DeliveryResult(
        status="pending",
        content_key=content_key,
        channel=channel,
        target_key=target_key,
        payload_json=_enriched_payload,
        delivery_id=row.id,
    )


async def flush_pending_shadow(
    session,
    *,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> List[DeliveryResult]:
    """
    Drain pending delivery ledger rows in shadow mode.

    For each pending row:
      1. Run guardrail stack (quiet_hours → daily_cap → mute_until).
      2. Pass  → mark row status="delivered_shadow", delivered_at=now.
      3. Fail  → mark row status="suppressed".
      4. No external sends; no Notification rows created.

    Returns an audit list of DeliveryResult, one per row processed.
    """
    if session is None:
        return []

    now = now or datetime.now(timezone.utc)
    rows = await loop_repo.delivery_get_pending(session, now=now, limit=limit)
    results: List[DeliveryResult] = []

    for row in rows:
        result = await _process_shadow_row(session, row, now)
        results.append(result)

    logger.info(
        "[delivery] flush_pending_shadow: processed=%d delivered=%d suppressed=%d",
        len(results),
        sum(1 for r in results if r.status == STATUS_DELIVERED_SHADOW),
        sum(1 for r in results if r.status == STATUS_SUPPRESSED_GUARDRAIL),
    )
    return results


async def _process_shadow_row(
    session,
    row: Any,
    now: datetime,
) -> DeliveryResult:
    """Evaluate guardrails for one pending ledger row and update its status."""
    channel    = row.channel
    target_key = row.target_key

    def _fail(reason: str) -> DeliveryResult:
        return DeliveryResult(
            status=STATUS_SUPPRESSED_GUARDRAIL,
            content_key=row.content_key,
            channel=channel,
            target_key=target_key,
            reason=reason,
            delivery_id=row.id,
        )

    # ── Guardrail 1: quiet hours ─────────────────────────────────────────────
    if _is_quiet_hour(now):
        await loop_repo.delivery_mark_suppressed(session, row.id)
        logger.debug("[delivery] suppressed %s quiet_hours", row.id)
        return _fail(REASON_QUIET_HOURS)

    # ── Guardrail 2: daily cap ────────────────────────────────────────────────
    if await _daily_cap_reached(session, channel, target_key, now):
        # Phase 10C · Slice 5: redirect overflow to digest instead of discarding.
        try:
            from app.services.digest_batch_service import (
                add_to_digest as _add_dig,
                period_bucket_for as _bucket_for,
            )
            _overflow_item = {
                "content_key":        row.content_key,
                "target_key":         row.target_key,
                "canonical_severity": getattr(row, "canonical_severity", None),
                "severity_rank":      getattr(row, "severity_rank", None),
                "source":             "daily_cap_overflow",
            }
            await _add_dig(
                session,
                user_id=None,           # ledger row has no user_id; use global
                channel=channel,
                period_bucket=_bucket_for(now),
                item=_overflow_item,
                item_content_key=row.content_key,
            )
        except Exception as _ov_exc:
            logger.warning(
                "[delivery] daily_cap overflow→digest failed (non-fatal): %r", _ov_exc
            )
        await loop_repo.delivery_mark_suppressed(session, row.id)
        logger.debug("[delivery] suppressed %s daily_cap", row.id)
        return _fail(REASON_DAILY_CAP)

    # ── Guardrail 3: mute_until (not_before_utc) ──────────────────────────────
    if row.not_before_utc is not None:
        nbu = row.not_before_utc
        # Normalise both sides to naive UTC for SQLite compat
        nbu_cmp = nbu.replace(tzinfo=None) if nbu.tzinfo else nbu
        now_cmp = now.replace(tzinfo=None) if now.tzinfo else now
        if now_cmp < nbu_cmp:
            await loop_repo.delivery_mark_suppressed(session, row.id)
            logger.debug("[delivery] suppressed %s mute_until", row.id)
            return _fail(REASON_MUTE_UNTIL)

    # ── Phase 10C · Slice 6: relevance recheck ───────────────────────────────
    # Re-evaluate whether the item is still fresh and relevant at flush time.
    # Fail-open: if the recheck service raises, log and proceed to deliver.
    try:
        from app.services.delivery_relevance_service import relevance_recheck as _recheck
        _rc = await _recheck(session, row, now)
        if not _rc.should_deliver:
            await loop_repo.delivery_mark_suppressed(session, row.id)
            logger.debug(
                "[delivery] recheck_suppressed %s reason=%r detail=%r",
                row.id, _rc.suppress_reason, _rc.reason,
            )
            return _fail(_rc.suppress_reason or REASON_RECHECK)
    except Exception as _rc_exc:
        logger.warning(
            "[delivery] relevance_recheck error (fail-open, delivering anyway): %r",
            _rc_exc,
        )

    # ── All guardrails + recheck passed — shadow deliver ─────────────────────
    await _mark_shadow_delivered(session, row.id, now)
    logger.debug("[delivery] shadow_delivered %s channel=%s target=%s",
                 row.id, channel, target_key)
    return DeliveryResult(
        status=STATUS_DELIVERED_SHADOW,
        content_key=row.content_key,
        channel=channel,
        target_key=target_key,
        reason=REASON_SHADOW_DRAIN,
        delivery_id=row.id,
    )


async def _mark_shadow_delivered(session, delivery_id: str, now: datetime) -> None:
    """Set status=delivered_shadow and delivered_at=now on a ledger row."""
    try:
        from sqlalchemy import update
        from app.db.models import DeliveryLedger

        now_naive = now.replace(tzinfo=None) if now.tzinfo else now
        await session.execute(
            update(DeliveryLedger)
            .where(DeliveryLedger.id == delivery_id)
            .values(status=STATUS_DELIVERED_SHADOW, delivered_at=now_naive)
            .execution_options(synchronize_session=False)
        )
        await session.flush()
    except Exception as exc:
        logger.warning(
            "[delivery] _mark_shadow_delivered failed for %r: %r", delivery_id, exc
        )
