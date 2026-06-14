"""
Delivery Inbox / Read API — Phase 10C · Slice 8.

Read-only (plus one mutation: mark-read) surfaces for inspecting shadow-
delivered intelligence and digest batches.

Endpoints
---------
    GET  /delivery/inbox                     — list ledger rows
    GET  /delivery/inbox/{delivery_id}       — single ledger row
    PATCH /delivery/inbox/{delivery_id}/read — mark read (via Notification)
    GET  /delivery/digests                   — list digest batches
    GET  /delivery/digests/{batch_id}        — single digest batch

Read-state strategy
-------------------
`DeliveryLedger` has no `read_at` column and we avoid schema churn.  Instead,
`PATCH /delivery/inbox/{id}/read` writes one `Notification` row with:
    kind    = "inbox_read_receipt"
    user_id = query-param `user_id` (or sentinel "admin")
    body_json = {"delivery_id": <id>, "content_key": <ck>}

GET endpoints cross-reference this table to populate `is_read`.

Authentication
--------------
Same admin/internal pattern as Slice 7: `user_id` is an optional query param.
No real notifications, no external sends, no frontend changes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, or_

from app.db.connection import get_session
from app.db.models import DeliveryLedger, DigestBatch, Notification
from app.services.ownership_service import resolve_effective_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/delivery", tags=["delivery"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_STATUSES = frozenset({
    "pending", "delivered", "delivered_shadow",
    "failed", "suppressed", "deferred",
})
_DEFAULT_LIMIT   = 50
_MAX_LIMIT       = 200
_READ_NOTIF_KIND = "inbox_read_receipt"
_ADMIN_SENTINEL  = "admin"


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------

class InboxItem(BaseModel):
    """One delivery_ledger row as seen by the inbox API."""

    delivery_id:        str
    content_key:        str
    target_key:         str
    channel:            str
    status:             str
    canonical_severity: Optional[str]
    severity_rank:      Optional[int]
    artifact_ref:       Optional[str]
    content_hash:       str
    attempts:           int
    not_before_utc:     Optional[datetime]
    created_at:         datetime
    delivered_at:       Optional[datetime]
    is_read:            bool = False

    model_config = {"from_attributes": True}


class DigestItem(BaseModel):
    """One digest_batches row."""

    batch_id:      str
    user_id:       Optional[str]
    channel:       str
    period_bucket: str
    status:        str
    item_count:    int
    payload_json:  Dict[str, Any]
    content_key:   Optional[str]
    created_at:    datetime
    updated_at:    datetime

    model_config = {"from_attributes": True}


class MarkReadResponse(BaseModel):
    delivery_id: str
    is_read:     bool
    read_at:     Optional[datetime]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_inbox(row: Any, read_ids: set) -> InboxItem:
    return InboxItem(
        delivery_id=row.id,
        content_key=row.content_key,
        target_key=row.target_key,
        channel=row.channel,
        status=row.status,
        canonical_severity=row.canonical_severity,
        severity_rank=row.severity_rank,
        artifact_ref=getattr(row, "artifact_ref", None),
        content_hash=row.content_hash,
        attempts=row.attempts,
        not_before_utc=getattr(row, "not_before_utc", None),
        created_at=row.created_at,
        delivered_at=getattr(row, "delivered_at", None),
        is_read=(row.id in read_ids),
    )


def _row_to_digest(row: Any) -> DigestItem:
    return DigestItem(
        batch_id=row.id,
        user_id=row.user_id,
        channel=row.channel,
        period_bucket=row.period_bucket,
        status=row.status,
        item_count=row.item_count,
        payload_json=row.payload_json if isinstance(row.payload_json, dict) else {},
        content_key=getattr(row, "content_key", None),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _read_ids_for(session, user_id: str, delivery_ids: List[str]) -> set:
    """Return the set of delivery_ids that are marked read for this user."""
    if not delivery_ids:
        return set()
    try:
        result = await session.execute(
            select(Notification.body_json)
            .where(Notification.user_id == user_id)
            .where(Notification.kind == _READ_NOTIF_KIND)
            .where(Notification.read_at.isnot(None))
        )
        read: set = set()
        for (body,) in result.all():
            did = (body or {}).get("delivery_id")
            if did in delivery_ids:
                read.add(did)
        return read
    except Exception as exc:
        logger.warning("[inbox] _read_ids_for failed (defaulting to unread): %r", exc)
        return set()


def _validate_status_filter(statuses_raw: Optional[str]) -> Optional[List[str]]:
    """Parse comma-separated status filter; raises 422 on unknown status."""
    if not statuses_raw:
        return None
    parts = [s.strip() for s in statuses_raw.split(",") if s.strip()]
    unknown = [p for p in parts if p not in _VALID_STATUSES]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown status(es) {unknown}; valid: {sorted(_VALID_STATUSES)}",
        )
    return parts


# ---------------------------------------------------------------------------
# Inbox endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/inbox",
    response_model=List[InboxItem],
    summary="List delivery inbox items",
)
async def list_inbox(
    request:     Request,
    status:      Optional[str] = Query(
        default="pending,delivered_shadow",
        description="Comma-separated status filter",
    ),
    channel:     Optional[str] = Query(default=None),
    target_key:  Optional[str] = Query(default=None),
    min_severity: Optional[str] = Query(
        default=None,
        description="Canonical severity floor (info/low/medium/high/critical)",
    ),
    user_id:     Optional[str] = Query(default=None, description="User ID (admin override; omit to use JWT identity)"),
    limit:       int           = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
) -> List[InboxItem]:
    """Return delivery_ledger rows ordered newest-first.

    Filters are ANDed.  `min_severity` requires `canonical_severity` to be
    set on the row (rows without it are included — fail-open).

    `is_read` is populated from the Notification table when `user_id` is given.
    """
    statuses = _validate_status_filter(status)

    min_rank: Optional[int] = None
    if min_severity:
        from app.services.severity_model import to_canonical_severity, severity_rank
        canonical = to_canonical_severity(min_severity, default="info")
        min_rank  = severity_rank(canonical)

    try:
        async with get_session() as session:
            stmt = select(DeliveryLedger)

            if statuses:
                stmt = stmt.where(DeliveryLedger.status.in_(statuses))
            if channel:
                stmt = stmt.where(DeliveryLedger.channel == channel)
            if target_key:
                stmt = stmt.where(DeliveryLedger.target_key == target_key)
            if min_rank is not None:
                stmt = stmt.where(
                    or_(
                        DeliveryLedger.severity_rank.is_(None),
                        DeliveryLedger.severity_rank >= min_rank,
                    )
                )

            stmt = stmt.order_by(DeliveryLedger.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()

            effective_uid = user_id if user_id is not None else resolve_effective_user_id(request)
            uid = effective_uid or _ADMIN_SENTINEL
            ids = [r.id for r in rows]
            read_set = await _read_ids_for(session, uid, ids)

        return [_row_to_inbox(r, read_set) for r in rows]

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[inbox] list_inbox failed: %r", exc)
        raise HTTPException(status_code=500, detail=f"inbox query failed: {exc}")


@router.get(
    "/inbox/{delivery_id}",
    response_model=InboxItem,
    summary="Get a single delivery inbox item",
)
async def get_inbox_item(
    request:     Request,
    delivery_id: str,
    user_id:     Optional[str] = Query(default=None, description="User ID (admin override; omit to use JWT identity)"),
) -> InboxItem:
    """Return one delivery_ledger row by ID."""
    try:
        async with get_session() as session:
            row = (await session.execute(
                select(DeliveryLedger)
                .where(DeliveryLedger.id == delivery_id)
                .execution_options(populate_existing=True)
            )).scalar_one_or_none()

            if row is None:
                raise HTTPException(status_code=404, detail=f"delivery {delivery_id!r} not found")

            effective_uid = user_id if user_id is not None else resolve_effective_user_id(request)
            uid      = effective_uid or _ADMIN_SENTINEL
            read_set = await _read_ids_for(session, uid, [delivery_id])

        return _row_to_inbox(row, read_set)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[inbox] get_inbox_item failed: %r", exc)
        raise HTTPException(status_code=500, detail=f"inbox item fetch failed: {exc}")


@router.patch(
    "/inbox/{delivery_id}/read",
    response_model=MarkReadResponse,
    summary="Mark a delivery inbox item as read",
)
async def mark_inbox_read(
    request:     Request,
    delivery_id: str,
    user_id:     Optional[str] = Query(default=None, description="User ID (admin override; omit to use JWT identity)"),
) -> MarkReadResponse:
    """Mark a delivery_ledger item as read.

    Writes a Notification row with kind='inbox_read_receipt' as the read-state
    record — no schema changes to DeliveryLedger required.  Idempotent: calling
    it multiple times has no additional effect beyond the first write.

    No real notification is dispatched; no external sends occur.
    """
    effective_uid = user_id if user_id is not None else resolve_effective_user_id(request)
    uid = effective_uid or _ADMIN_SENTINEL
    now = datetime.now(timezone.utc)

    try:
        async with get_session() as session:
            # Verify the delivery row exists
            row = (await session.execute(
                select(DeliveryLedger)
                .where(DeliveryLedger.id == delivery_id)
                .execution_options(populate_existing=True)
            )).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail=f"delivery {delivery_id!r} not found")

            # Check idempotency: already marked read?
            existing = (await session.execute(
                select(Notification)
                .where(Notification.user_id == uid)
                .where(Notification.kind == _READ_NOTIF_KIND)
                .where(Notification.body_json["delivery_id"].as_string() == delivery_id)
                .limit(1)
            )).scalar_one_or_none()

            if existing is not None:
                read_at = existing.read_at
            else:
                notif = Notification(
                    user_id=uid,
                    kind=_READ_NOTIF_KIND,
                    body_json={"delivery_id": delivery_id, "content_key": row.content_key},
                    read_at=now,
                )
                session.add(notif)
                await session.flush()
                read_at = now

            await session.commit()

        return MarkReadResponse(delivery_id=delivery_id, is_read=True, read_at=read_at)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[inbox] mark_inbox_read failed: %r", exc)
        raise HTTPException(status_code=500, detail=f"mark-read failed: {exc}")


# ---------------------------------------------------------------------------
# Digest endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/digests",
    response_model=List[DigestItem],
    summary="List digest batches",
)
async def list_digests(
    request:       Request,
    user_id:       Optional[str] = Query(default=None, description="User ID (admin override; omit to use JWT identity)"),
    channel:       Optional[str] = Query(default=None),
    status:        Optional[str] = Query(default=None, description="open|delivered_shadow|…"),
    period_bucket: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    limit:         int           = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
) -> List[DigestItem]:
    """Return digest_batches rows ordered by most-recently-updated.

    Phase 16 · Slice 5: user_id defaults to the request owner identity when
    not provided, ensuring users only see their own digest batches.
    """
    effective_uid = user_id if user_id is not None else resolve_effective_user_id(request)
    try:
        async with get_session() as session:
            stmt = select(DigestBatch)

            stmt = stmt.where(DigestBatch.user_id == effective_uid)
            if channel:
                stmt = stmt.where(DigestBatch.channel == channel)
            if status:
                stmt = stmt.where(DigestBatch.status == status)
            if period_bucket:
                stmt = stmt.where(DigestBatch.period_bucket == period_bucket)

            stmt = stmt.order_by(DigestBatch.updated_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()

        return [_row_to_digest(r) for r in rows]

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[inbox] list_digests failed: %r", exc)
        raise HTTPException(status_code=500, detail=f"digest list failed: {exc}")


@router.get(
    "/digests/{batch_id}",
    response_model=DigestItem,
    summary="Get a single digest batch",
)
async def get_digest(batch_id: str) -> DigestItem:
    """Return one digest_batches row by ID."""
    try:
        async with get_session() as session:
            row = (await session.execute(
                select(DigestBatch)
                .where(DigestBatch.id == batch_id)
                .execution_options(populate_existing=True)
            )).scalar_one_or_none()

        if row is None:
            raise HTTPException(status_code=404, detail=f"digest batch {batch_id!r} not found")
        return _row_to_digest(row)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[inbox] get_digest failed: %r", exc)
        raise HTTPException(status_code=500, detail=f"digest fetch failed: {exc}")
