"""
Delivery Relevance / Freshness Recheck — Phase 10C · Slice 6.

A deterministic, pure gatekeeper called by flush_pending_shadow() immediately
before marking a pending ledger row delivered_shadow.  It re-evaluates
whether the item is still worth delivering at flush time, catching items that
were valid when enqueued but have since become stale, superseded, or
irrelevant.

Checks (priority order; first failing check wins)
--------------------------------------------------
  1. stale_age         — row older than STALE_THRESHOLD_HOURS (72 h)
  2. dup_delivered     — same content_hash already marked delivered/delivered_shadow
  3. below_min_sev     — canonical_severity_rank < current global min_severity
  4. superseded        — artifact_ref signals supersession or invalidation

Fail-open policy
----------------
Any individual check that raises an exception is logged as a warning and skipped
(delivery proceeds).  Suppressing valid items is a worse failure mode than
delivering a slightly stale one.  The only hard stop is a structurally invalid
row (session=None or row=None), which also delivers (fail open).

Public API
----------
    relevance_recheck(session, row, now=None) -> RecheckResult

Suppress reason constants (mirrored here; also used in DeliveryResult.reason):
    REASON_RECHECK_STALE
    REASON_RECHECK_DUP_DELIVERED
    REASON_RECHECK_BELOW_MIN_SEV
    REASON_RECHECK_SUPERSEDED
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Items older than this at flush time are stale.  Deliberately more lenient
# than the ranking engine's 48 h so items don't expire between enqueue and a
# late-night flush.
STALE_THRESHOLD_HOURS: float = 72.0

# Half-life for the freshness_score field (informational only, not a gate).
RECENCY_HALF_LIFE_HOURS: float = 24.0

# ---------------------------------------------------------------------------
# Suppress reason constants
# ---------------------------------------------------------------------------

REASON_RECHECK_STALE       = "recheck_stale"
REASON_RECHECK_DUP_DELIVERED = "recheck_duplicate_delivered"
REASON_RECHECK_BELOW_MIN_SEV = "recheck_below_min_severity"
REASON_RECHECK_SUPERSEDED  = "recheck_superseded"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class RecheckResult:
    """Outcome of one relevance_recheck() call.

    Attributes
    ----------
    should_deliver  : True  → proceed to delivered_shadow.
                      False → mark suppressed with suppress_reason.
    freshness_score : Recency decay 0..1 (1 = just enqueued, 0 = very old).
                      Informational; not used as a gate.
    relevance_score : 0..1 overall relevance.  0.0 if any check failed.
    suppress_reason : One of REASON_RECHECK_* constants, or "" if delivering.
    reason          : Human-readable detail string.
    """
    should_deliver:  bool
    freshness_score: float
    relevance_score: float
    suppress_reason: str
    reason:          str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _age_hours(created_at: Any, now: datetime) -> float:
    """Return age of ``created_at`` in hours relative to ``now``.

    Returns -1.0 if the timestamp is absent or unparseable (treated as unknown
    age — will not trigger the stale check).
    """
    if created_at is None:
        return -1.0
    try:
        ts = created_at
        if isinstance(ts, str):
            s = ts.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            ts = datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now_utc = (
            now.replace(tzinfo=timezone.utc)
            if now.tzinfo is None
            else now.astimezone(timezone.utc)
        )
        return max(0.0, (now_utc - ts.astimezone(timezone.utc)).total_seconds() / 3600.0)
    except Exception:
        return -1.0


def _freshness_score(age_hours: float) -> float:
    """Exponential decay: 1.0 when fresh, halves every RECENCY_HALF_LIFE_HOURS."""
    if age_hours < 0:
        return 0.5    # unknown age → neutral
    if age_hours == 0:
        return 1.0
    return max(0.0, min(1.0, 0.5 ** (age_hours / RECENCY_HALF_LIFE_HOURS)))


# ---------------------------------------------------------------------------
# Individual checks
# Each returns (suppressed: bool, detail: str).
# They NEVER raise — callers wrap them in try/except anyway, but an inner
# guard_exception means the check fails open cleanly.
# ---------------------------------------------------------------------------

def _check_stale(age_hours: float) -> Tuple[bool, str]:
    if 0 <= age_hours and age_hours >= STALE_THRESHOLD_HOURS:
        return True, f"age {age_hours:.1f}h >= threshold {STALE_THRESHOLD_HOURS:.0f}h"
    return False, ""


async def _check_dup_delivered(session, row: Any) -> Tuple[bool, str]:
    """Suppress if the same content_hash appears in a delivered/delivered_shadow row."""
    try:
        content_hash = getattr(row, "content_hash", None)
        if not content_hash:
            return False, ""
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        result = await session.execute(
            select(func.count())
            .select_from(DeliveryLedger)
            .where(DeliveryLedger.content_hash == content_hash)
            .where(DeliveryLedger.status.in_(["delivered", "delivered_shadow"]))
            .where(DeliveryLedger.id != row.id)
        )
        count = result.scalar() or 0
        if count > 0:
            return True, f"content_hash already delivered in {count} other row(s)"
        return False, ""
    except Exception as exc:
        logger.warning("[recheck] dup_delivered inner error (fail-open): %r", exc)
        return False, ""


async def _check_below_min_sev(session, row: Any) -> Tuple[bool, str]:
    """Suppress if row.canonical_severity is below the current global min_severity."""
    try:
        canonical_sev = getattr(row, "canonical_severity", None)
        if not canonical_sev:
            return False, ""   # no severity info — don't suppress

        from app.db.repositories.delivery_prefs_repo import get_or_create_prefs
        from app.services.severity_model import severity_rank, to_canonical_severity

        channel = getattr(row, "channel", "in_app")
        prefs = await get_or_create_prefs(session, user_id=None, channel=channel)
        min_sev_str = (prefs.min_severity if prefs else None) or "info"

        item_rank  = severity_rank(canonical_sev)
        floor_rank = severity_rank(to_canonical_severity(min_sev_str))
        if item_rank < floor_rank:
            return True, (
                f"canonical_severity={canonical_sev!r} rank={item_rank} < "
                f"min_severity={min_sev_str!r} rank={floor_rank}"
            )
        return False, ""
    except Exception as exc:
        logger.warning("[recheck] below_min_sev inner error (fail-open): %r", exc)
        return False, ""


def _check_superseded(row: Any) -> Tuple[bool, str]:
    """Suppress if artifact_ref signals that this item has been superseded or invalidated."""
    artifact_ref = str(getattr(row, "artifact_ref", "") or "").lower()
    if artifact_ref.startswith("superseded") or artifact_ref.startswith("invalidated"):
        return True, f"artifact_ref={getattr(row, 'artifact_ref', '')!r}"
    return False, ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def relevance_recheck(
    session,
    row: Any,
    now: Optional[datetime] = None,
) -> RecheckResult:
    """Re-evaluate whether a pending delivery row is still worth delivering.

    Called from flush_pending_shadow() immediately before marking a row
    delivered_shadow.  All DB errors are fail-open.

    Parameters
    ----------
    session : AsyncSession or None.
    row     : DeliveryLedger ORM row (or duck-typed equivalent).
    now     : Reference time; defaults to datetime.now(timezone.utc).

    Returns
    -------
    RecheckResult — always returns, never raises.
    """
    if session is None or row is None:
        return RecheckResult(
            should_deliver=True,
            freshness_score=0.5,
            relevance_score=1.0,
            suppress_reason="",
            reason="null input; fail open",
        )

    now = now or datetime.now(timezone.utc)
    age   = _age_hours(getattr(row, "created_at", None), now)
    fresh = _freshness_score(age)

    def _suppress(suppress_reason: str, detail: str) -> RecheckResult:
        return RecheckResult(
            should_deliver=False,
            freshness_score=fresh,
            relevance_score=0.0,
            suppress_reason=suppress_reason,
            reason=detail,
        )

    # ── Check 1: stale age ──────────────────────────────────────────────────
    try:
        hit, detail = _check_stale(age)
        if hit:
            logger.debug("[recheck] stale id=%s %s", row.id, detail)
            return _suppress(REASON_RECHECK_STALE, detail)
    except Exception as exc:
        logger.warning("[recheck] stale check error (fail-open): %r", exc)

    # ── Check 2: duplicate already delivered ─────────────────────────────────
    try:
        hit, detail = await _check_dup_delivered(session, row)
        if hit:
            logger.debug("[recheck] dup_delivered id=%s %s", row.id, detail)
            return _suppress(REASON_RECHECK_DUP_DELIVERED, detail)
    except Exception as exc:
        logger.warning("[recheck] dup_delivered check error (fail-open): %r", exc)

    # ── Check 3: below current global min_severity ───────────────────────────
    try:
        hit, detail = await _check_below_min_sev(session, row)
        if hit:
            logger.debug("[recheck] below_min_sev id=%s %s", row.id, detail)
            return _suppress(REASON_RECHECK_BELOW_MIN_SEV, detail)
    except Exception as exc:
        logger.warning("[recheck] below_min_sev check error (fail-open): %r", exc)

    # ── Check 4: superseded / invalidated ────────────────────────────────────
    try:
        hit, detail = _check_superseded(row)
        if hit:
            logger.debug("[recheck] superseded id=%s %s", row.id, detail)
            return _suppress(REASON_RECHECK_SUPERSEDED, detail)
    except Exception as exc:
        logger.warning("[recheck] superseded check error (fail-open): %r", exc)

    # ── All checks passed ─────────────────────────────────────────────────────
    return RecheckResult(
        should_deliver=True,
        freshness_score=fresh,
        relevance_score=1.0,
        suppress_reason="",
        reason=f"all checks passed; age={age:.1f}h freshness={fresh:.3f}",
    )
