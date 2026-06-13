"""
Digest Batching Service — Phase 10C · Slice 5.

Accumulates digest-class intelligence into daily digest batches.
Serves two complementary goals:

  1. Digest routing — when the ranking engine classifies an item as
     delivery_class="digest", it is preserved in a digest_batches row
     rather than pushed immediately to the user.

  2. Overflow preservation — when the daily-cap guardrail in
     loop_delivery_service.flush_pending_shadow() would otherwise silently
     discard a pending item, that item is redirected here instead.

Design
------
* One batch per (user_id, channel, period_bucket) — the UNIQUE constraint
  in the schema is the idempotency anchor; two concurrent writers produce
  one batch row, never two.
* Items are stored as a list under payload_json["items"].
* Per-item deduplication is enforced by content_key: the same item never
  appears twice in the same batch.
* item_count mirrors len(payload_json["items"]) and is updated atomically
  with each append.
* No external sends.  No notifications.  Purely an accumulator.

Public API
----------
    period_bucket_for(now=None)   -> str               e.g. "2026-06-14"
    add_to_digest(session, *, user_id, channel,
                  period_bucket, item,
                  item_content_key)  -> DigestAddResult | None
    get_open_batch(session, *, user_id, channel,
                   period_bucket)    -> DigestBatch | None
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Batch status constants (10C spec §5.3)
# ---------------------------------------------------------------------------

BATCH_STATUS_OPEN             = "open"
BATCH_STATUS_DELIVERED_SHADOW = "delivered_shadow"

# Payload structure key
_ITEMS_KEY = "items"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class DigestAddResult:
    """Outcome of one add_to_digest() call.

    Attributes
    ----------
    batch_id      : DigestBatch.id that received (or skipped) the item.
    period_bucket : The bucket the batch belongs to.
    item_count    : Number of distinct items in the batch after this call.
    added         : True  — item was appended.
                    False — item was a duplicate; nothing changed.
    content_key   : The item's content_key (may be "" if not provided).
    """
    batch_id:      str
    period_bucket: str
    item_count:    int
    added:         bool
    content_key:   str


# ---------------------------------------------------------------------------
# Period bucket
# ---------------------------------------------------------------------------

def period_bucket_for(now: Optional[datetime] = None) -> str:
    """Return the UTC calendar-day period bucket as 'YYYY-MM-DD'.

    Items at 2026-06-14 23:59 UTC and 2026-06-15 00:01 UTC fall into
    different buckets.  Timezone-naive datetimes are treated as UTC.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

async def add_to_digest(
    session,
    *,
    user_id: Optional[str],
    channel: str,
    period_bucket: str,
    item: Dict[str, Any],
    item_content_key: Optional[str] = None,
) -> Optional[DigestAddResult]:
    """Add one item to the open digest batch for (user_id, channel, period_bucket).

    Behaviour
    ---------
    * If no open batch exists, one is created (UNIQUE-safe idempotent create).
    * If item_content_key (or item["content_key"]) is already present in the
      batch, the item is skipped and DigestAddResult.added is False.
    * On success the batch's payload_json["items"] list is extended and
      item_count is incremented.

    Non-fatal: returns None when session is None or on any unhandled error.
    """
    if session is None:
        return None

    try:
        from app.db.repositories.delivery_prefs_repo import create_digest_batch
        from app.db.models import DigestBatch as _DigestBatch

        # Get or create the batch for this (user_id, channel, period_bucket).
        batch = await create_digest_batch(
            session,
            user_id=user_id,
            period_bucket=period_bucket,
            channel=channel,
            status=BATCH_STATUS_OPEN,
        )
        if batch is None:
            return None

        # Normalise: embed content_key into the item dict.
        normalised: Dict[str, Any] = dict(item)
        ck = str(item_content_key or normalised.get("content_key") or "")
        if ck:
            normalised.setdefault("content_key", ck)

        # Read current items from the batch (defend against non-dict payload_json).
        pj = batch.payload_json if isinstance(batch.payload_json, dict) else {}
        current_items: List[Dict[str, Any]] = pj.get(_ITEMS_KEY, [])

        # Dedup: skip if this content_key already exists.
        if ck:
            existing_keys = {str(i.get("content_key", "")) for i in current_items}
            if ck in existing_keys:
                logger.debug(
                    "[digest] duplicate skipped  batch=%s ck=%.12s", batch.id, ck
                )
                return DigestAddResult(
                    batch_id=batch.id,
                    period_bucket=period_bucket,
                    item_count=batch.item_count,
                    added=False,
                    content_key=ck,
                )

        # Append: replace payload_json entirely so SQLAlchemy detects the change.
        new_items = list(current_items) + [normalised]
        new_count = len(new_items)

        batch.payload_json = {_ITEMS_KEY: new_items}
        batch.item_count   = new_count
        batch.updated_at   = datetime.now(timezone.utc)
        await session.flush()

        logger.debug(
            "[digest] item added  batch=%s ck=%.12s item_count=%d",
            batch.id, ck, new_count,
        )
        return DigestAddResult(
            batch_id=batch.id,
            period_bucket=period_bucket,
            item_count=new_count,
            added=True,
            content_key=ck,
        )

    except Exception as exc:
        logger.warning("[digest] add_to_digest failed (non-fatal): %r", exc)
        return None


async def get_open_batch(
    session,
    *,
    user_id: Optional[str],
    channel: str,
    period_bucket: str,
):
    """Return the open DigestBatch for (user_id, channel, period_bucket), or None.

    Non-fatal: returns None on error or when session is None.
    """
    if session is None:
        return None
    try:
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
        return (await session.execute(stmt)).scalar_one_or_none()
    except Exception as exc:
        logger.warning("[digest] get_open_batch failed: %r", exc)
        return None
