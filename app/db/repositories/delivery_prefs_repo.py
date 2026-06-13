"""
Delivery preferences & digest/archive repository — Phase 10C · Slice 2.

Minimal persistence helpers over the three new 10C tables:
  * user_delivery_prefs       — get_or_create_prefs, update_prefs
  * digest_batches            — create_digest_batch
  * delivery_ledger_archive   — archive_delivery

All functions accept an AsyncSession as the first positional argument.  Passing
None is safe: every function returns a None/empty default instead of raising
(the null-object contract used across the loop/watchlist repos).

Phase 10C · Slice 2 is SCHEMA ONLY.  These helpers exist so the schema can be
round-tripped by tests, but NO delivery, ranking, batching, or archival code
path calls them yet.  Wiring happens in later slices (prefs → Slice 7,
digest → Slice 5, archive → Slice 10).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Fields a caller may update on a prefs row (id/user_id/channel/created_at are immutable).
_MUTABLE_PREF_FIELDS = frozenset({
    "enabled",
    "min_severity",
    "quiet_hours_start",
    "quiet_hours_end",
    "timezone",
    "daily_cap",
    "mute_until",
})


# ---------------------------------------------------------------------------
# user_delivery_prefs
# ---------------------------------------------------------------------------

async def get_or_create_prefs(
    session,
    user_id: Optional[str] = None,
    channel: str = "in_app",
):
    """Return the prefs row for (user_id, channel); create one with safe
    defaults if absent.  Idempotent: a second call returns the same row.

    Returns the UserDeliveryPref row, or None when session is None.
    """
    if session is None:
        return None

    from app.db.models import UserDeliveryPref
    from sqlalchemy import select

    stmt = (
        select(UserDeliveryPref)
        .where(UserDeliveryPref.channel == channel)
        .where(
            UserDeliveryPref.user_id == user_id
            if user_id is not None
            else UserDeliveryPref.user_id.is_(None)
        )
        .execution_options(populate_existing=True)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        return row

    # Column defaults supply the safe values (mirrors settings.delivery_*).
    row = UserDeliveryPref(user_id=user_id, channel=channel)
    session.add(row)
    await session.flush()
    return row


async def update_prefs(
    session,
    user_id: Optional[str] = None,
    channel: str = "in_app",
    **fields: Any,
):
    """Update mutable fields on a prefs row (creating it first if absent).

    Unknown field names are ignored (forward-compatible).  ``min_severity`` is
    normalized through the canonical severity_model so only canonical values
    are ever persisted.

    Returns the updated row, or None when session is None.
    """
    if session is None:
        return None

    row = await get_or_create_prefs(session, user_id=user_id, channel=channel)
    if row is None:
        return None

    for key, value in fields.items():
        if key not in _MUTABLE_PREF_FIELDS:
            continue
        if key == "min_severity" and value is not None:
            from app.services.severity_model import to_canonical_severity
            value = to_canonical_severity(str(value))
        setattr(row, key, value)

    row.updated_at = _now()
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# digest_batches
# ---------------------------------------------------------------------------

async def create_digest_batch(
    session,
    user_id: Optional[str],
    period_bucket: str,
    channel: str = "in_app",
    status: str = "open",
    item_count: int = 0,
    payload_json: Optional[Dict[str, Any]] = None,
    content_key: Optional[str] = None,
):
    """Create (or return the existing) digest batch for
    (user_id, channel, period_bucket).  Idempotent on that triple.

    Returns the DigestBatch row, or None when session is None.
    """
    if session is None:
        return None

    from app.db.models import DigestBatch
    from sqlalchemy import select

    stmt = (
        select(DigestBatch)
        .where(DigestBatch.channel == channel)
        .where(DigestBatch.period_bucket == period_bucket)
        .where(
            DigestBatch.user_id == user_id
            if user_id is not None
            else DigestBatch.user_id.is_(None)
        )
        .execution_options(populate_existing=True)
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    row = DigestBatch(
        user_id=user_id,
        channel=channel,
        period_bucket=period_bucket,
        status=status,
        item_count=item_count,
        payload_json=payload_json if payload_json is not None else {},
        content_key=content_key,
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# delivery_ledger_archive
# ---------------------------------------------------------------------------

async def archive_delivery(
    session,
    *,
    original_delivery_id: Optional[str] = None,
    user_id: Optional[str] = None,
    channel: str = "in_app",
    target_key: Optional[str] = None,
    status: Optional[str] = None,
    payload_json: Optional[Dict[str, Any]] = None,
    content_key: Optional[str] = None,
):
    """Append one row to delivery_ledger_archive.  Append-only — never updates
    or deletes (job_runs / dossier_revision audit discipline).

    Returns the DeliveryLedgerArchive row, or None when session is None.
    """
    if session is None:
        return None

    from app.db.models import DeliveryLedgerArchive

    row = DeliveryLedgerArchive(
        original_delivery_id=original_delivery_id,
        user_id=user_id,
        channel=channel,
        target_key=target_key,
        status=status,
        payload_json=payload_json if payload_json is not None else {},
        content_key=content_key,
    )
    session.add(row)
    await session.flush()
    return row
