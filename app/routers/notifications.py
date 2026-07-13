"""Notification routes — beta milestone 4.

A user-facing `/notifications` surface that is a THIN ADAPTER over the existing
shadow-deployed delivery layer.  No new business logic, no new tables, no
scoring: every endpoint delegates to the already-built + already-tested
functions in the delivery routers/services —

    * app.routers.delivery_inbox     : list_inbox, mark_inbox_read (DeliveryLedger
                                       + Notification read-receipts)
    * app.routers.delivery_preferences: get_delivery_preferences,
                                       patch_delivery_preferences (UserDeliveryPref)

Endpoints
---------
    GET   /notifications              — inbox items (delivery ledger, newest first)
    GET   /notifications/unread       — unread items + unread count
    POST  /notifications/read         — mark one or more items read (idempotent)
    GET   /notifications/preferences  — delivery preferences for a channel
    PATCH /notifications/preferences  — update delivery preferences

Design
------
* Rollout stays behind the existing delivery flags: when the delivery layer is
  in shadow (delivery_shadow=true) the ledger holds status="delivered_shadow"
  rows, which this inbox surfaces read-only.  No real sends occur here.
* Degrades gracefully when persistence is disabled: reads return empty, the
  read/mark endpoint reports {"marked": 0, "persistence": "disabled"}.
* Identity is resolved once (request.state.user_id -> bypass user) and passed
  explicitly to the delegated functions, so behaviour is consistent and the
  endpoints are unit-testable with request=None.
* No conviction-engine calls.  No scenario scoring.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

# Reuse the existing delivery-preferences patch model verbatim (same validation).
from app.routers.delivery_preferences import DeliveryPrefsPatch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class MarkReadRequest(BaseModel):
    # One or many delivery ids to mark read.  Accepts either shape for
    # convenience; `delivery_ids` takes precedence when both are given.
    delivery_ids: Optional[List[str]] = None
    delivery_id:  Optional[str] = None

    def ids(self) -> List[str]:
        if self.delivery_ids:
            return [d for d in self.delivery_ids if d]
        if self.delivery_id:
            return [self.delivery_id]
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_id(request: Optional[Request]) -> str:
    """Resolve the acting user (401 for unauthenticated enforcement-mode requests;
    bypass user only when auth is disabled or middleware is absent)."""
    from app.dependencies.auth import require_user_id
    return require_user_id(request)


async def _persistence_on() -> bool:
    from app.db import get_session
    async with get_session() as s:
        return s is not None


# ---------------------------------------------------------------------------
# GET /notifications
# ---------------------------------------------------------------------------

@router.get("", summary="List notification inbox items (newest first)")
async def list_notifications(
    request: Request = None,
    status: Optional[str] = "pending,delivered_shadow",
    min_severity: Optional[str] = None,
    limit: int = 50,
) -> list:
    if not await _persistence_on():
        return []
    from app.routers.delivery_inbox import list_inbox
    # Pass every filter explicitly — list_inbox's own defaults are FastAPI Query
    # objects that only resolve when it is served as an HTTP endpoint, not when
    # it is called directly as a function.
    items = await list_inbox(
        request, status=status, channel=None, target_key=None,
        min_severity=min_severity, user_id=_user_id(request), limit=limit,
    )
    return [i.model_dump() for i in items]


# ---------------------------------------------------------------------------
# GET /notifications/unread
# ---------------------------------------------------------------------------

@router.get("/unread", summary="Unread notifications + unread count")
async def unread_notifications(
    request: Request = None,
    status: Optional[str] = "pending,delivered_shadow",
    limit: int = 200,
) -> dict:
    if not await _persistence_on():
        return {"count": 0, "items": []}
    from app.routers.delivery_inbox import list_inbox
    items = await list_inbox(
        request, status=status, channel=None, target_key=None,
        min_severity=None, user_id=_user_id(request), limit=limit,
    )
    unread = [i for i in items if not i.is_read]
    return {"count": len(unread), "items": [i.model_dump() for i in unread]}


# ---------------------------------------------------------------------------
# POST /notifications/read
# ---------------------------------------------------------------------------

@router.post("/read", summary="Mark one or more notifications read (idempotent)")
async def mark_notifications_read(body: MarkReadRequest, request: Request = None) -> dict:
    ids = body.ids()
    if not ids:
        raise HTTPException(status_code=400, detail="delivery_ids (or delivery_id) is required.")
    if not await _persistence_on():
        return {"marked": 0, "delivery_ids": [], "persistence": "disabled"}

    from app.routers.delivery_inbox import mark_inbox_read
    uid = _user_id(request)
    marked: List[str] = []
    missing: List[str] = []
    for did in ids:
        try:
            await mark_inbox_read(request, did, user_id=uid)
            marked.append(did)
        except HTTPException as exc:
            if exc.status_code == 404:
                missing.append(did)
                continue
            raise
    return {"marked": len(marked), "delivery_ids": marked, "missing": missing}


# ---------------------------------------------------------------------------
# GET /notifications/preferences
# ---------------------------------------------------------------------------

@router.get("/preferences", summary="Read notification (delivery) preferences")
async def get_notification_preferences(
    request: Request = None,
    channel: str = "in_app",
) -> dict:
    from app.routers.delivery_preferences import get_delivery_preferences
    resp = await get_delivery_preferences(request, channel=channel, user_id=_user_id(request))
    return resp.model_dump()


# ---------------------------------------------------------------------------
# PATCH /notifications/preferences
# ---------------------------------------------------------------------------

@router.patch("/preferences", summary="Update notification (delivery) preferences")
async def patch_notification_preferences(
    body: DeliveryPrefsPatch,
    request: Request = None,
    channel: str = "in_app",
) -> dict:
    from app.routers.delivery_preferences import patch_delivery_preferences
    resp = await patch_delivery_preferences(
        request, body, channel=channel, user_id=_user_id(request),
    )
    return resp.model_dump()
