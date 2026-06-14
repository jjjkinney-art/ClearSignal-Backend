"""
Delivery Preferences API — Phase 10C · Slice 7 / Phase 16 · Slice 5.

Exposes two endpoints for reading and updating per-channel delivery
preferences stored in user_delivery_prefs.

    GET  /delivery/preferences
    PATCH /delivery/preferences

Authentication / ownership (Phase 16 · Slice 5)
--------------
When AUTH_ENABLED=false (bypass, the default), the effective user_id resolves
to SYSTEM_DEFAULT_USER_ID so the routes continue returning the system-owned
preference rows that Slice 2 claimed from NULL.  Behaviour is identical to
pre-Phase-16 for all existing callers.

When AUTH_ENABLED=true, user_id is resolved from request.state (stamped by
AuthMiddleware) rather than from a query-parameter.  The optional `user_id`
query-parameter is honoured as an admin override when explicitly provided.

Design invariants
-----------------
* GET always returns safe defaults even when no DB row exists yet.
* PATCH creates the row on first write (get_or_create_prefs).
* `min_severity` is normalised through severity_model — unknown values are
  refused with HTTP 422 rather than persisted silently.
* No real delivery, no notifications, no external sends.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.db.connection import get_session
from app.services.ownership_service import resolve_effective_user_id
from app.db.models import UserDeliveryPref
from app.db.repositories.delivery_prefs_repo import update_prefs
from app.services.severity_model import (
    to_canonical_severity,
    UnknownSeverityError,
    CANONICAL_SEVERITIES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/delivery", tags=["delivery"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_CHANNELS = frozenset({"in_app", "email", "push"})
_DAILY_CAP_MIN = 1
_DAILY_CAP_MAX = 200

# Column defaults — mirror UserDeliveryPref column defaults
_DEFAULT_ENABLED           = True
_DEFAULT_MIN_SEVERITY      = "info"
_DEFAULT_QUIET_HOURS_START = 22
_DEFAULT_QUIET_HOURS_END   = 7
_DEFAULT_TIMEZONE          = "UTC"
_DEFAULT_DAILY_CAP         = 20
_DEFAULT_MUTE_UNTIL        = None


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class DeliveryPrefsResponse(BaseModel):
    """Serialised view of a user_delivery_prefs row (or safe defaults)."""

    user_id:           Optional[str]      = Field(None, description="NULL = global prefs")
    channel:           str                = Field("in_app")
    enabled:           bool               = Field(_DEFAULT_ENABLED)
    min_severity:      str                = Field(_DEFAULT_MIN_SEVERITY)
    quiet_hours_start: int                = Field(_DEFAULT_QUIET_HOURS_START, ge=0, le=23)
    quiet_hours_end:   int                = Field(_DEFAULT_QUIET_HOURS_END,   ge=0, le=23)
    timezone:          str                = Field(_DEFAULT_TIMEZONE)
    daily_cap:         int                = Field(_DEFAULT_DAILY_CAP, ge=_DAILY_CAP_MIN, le=_DAILY_CAP_MAX)
    mute_until:        Optional[datetime] = Field(None)
    row_exists:        bool               = Field(False, description="False = returned safe defaults, no DB row yet")

    model_config = {"from_attributes": True}


class DeliveryPrefsPatch(BaseModel):
    """Fields accepted by PATCH.  All are optional — send only what you want to change."""

    enabled:           Optional[bool]     = None
    min_severity:      Optional[str]      = None
    quiet_hours_start: Optional[int]      = Field(None, ge=0, le=23)
    quiet_hours_end:   Optional[int]      = Field(None, ge=0, le=23)
    timezone:          Optional[str]      = None
    daily_cap:         Optional[int]      = Field(None, ge=_DAILY_CAP_MIN, le=_DAILY_CAP_MAX)
    mute_until:        Optional[datetime] = None

    @field_validator("min_severity", mode="before")
    @classmethod
    def _validate_min_severity(cls, v: Any) -> Any:
        if v is None:
            return v
        try:
            return to_canonical_severity(str(v), strict=True)
        except UnknownSeverityError:
            raise ValueError(
                f"invalid min_severity {v!r}; must be one of {list(CANONICAL_SEVERITIES)}"
            )

    @field_validator("timezone", mode="before")
    @classmethod
    def _validate_timezone(cls, v: Any) -> Any:
        if v is None:
            return v
        v = str(v).strip()
        if not v:
            return _DEFAULT_TIMEZONE
        return v

    @field_validator("mute_until", mode="before")
    @classmethod
    def _validate_mute_until(cls, v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, datetime) and v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v

    def non_null_fields(self) -> Dict[str, Any]:
        """Return only the explicitly-set (non-None) fields."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_response(row: Any, channel: str, user_id: Optional[str]) -> DeliveryPrefsResponse:
    """Map an ORM row to the response schema."""
    return DeliveryPrefsResponse(
        user_id=getattr(row, "user_id", user_id),
        channel=getattr(row, "channel", channel),
        enabled=getattr(row, "enabled", _DEFAULT_ENABLED),
        min_severity=getattr(row, "min_severity", _DEFAULT_MIN_SEVERITY),
        quiet_hours_start=getattr(row, "quiet_hours_start", _DEFAULT_QUIET_HOURS_START),
        quiet_hours_end=getattr(row, "quiet_hours_end", _DEFAULT_QUIET_HOURS_END),
        timezone=getattr(row, "timezone", _DEFAULT_TIMEZONE),
        daily_cap=getattr(row, "daily_cap", _DEFAULT_DAILY_CAP),
        mute_until=getattr(row, "mute_until", _DEFAULT_MUTE_UNTIL),
        row_exists=True,
    )


def _safe_defaults(channel: str, user_id: Optional[str]) -> DeliveryPrefsResponse:
    """Return a response populated entirely with safe defaults (no DB row)."""
    return DeliveryPrefsResponse(
        user_id=user_id,
        channel=channel,
        enabled=_DEFAULT_ENABLED,
        min_severity=_DEFAULT_MIN_SEVERITY,
        quiet_hours_start=_DEFAULT_QUIET_HOURS_START,
        quiet_hours_end=_DEFAULT_QUIET_HOURS_END,
        timezone=_DEFAULT_TIMEZONE,
        daily_cap=_DEFAULT_DAILY_CAP,
        mute_until=_DEFAULT_MUTE_UNTIL,
        row_exists=False,
    )


def _validate_channel(channel: str) -> str:
    channel = channel.strip().lower()
    if channel not in _VALID_CHANNELS:
        raise HTTPException(
            status_code=422,
            detail=f"invalid channel {channel!r}; must be one of {sorted(_VALID_CHANNELS)}",
        )
    return channel


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/preferences",
    response_model=DeliveryPrefsResponse,
    summary="Read delivery preferences",
)
async def get_delivery_preferences(
    request: Request,
    channel: str = Query(default="in_app", description="Delivery channel"),
    user_id: Optional[str] = Query(default=None, description="User ID (admin override; omit to use JWT identity)"),
) -> DeliveryPrefsResponse:
    """Return the current delivery preferences for the given channel / user.

    If no preference row exists the endpoint returns safe defaults without
    creating a DB row (GET must be non-mutating).  Use PATCH to persist
    custom preferences.

    `row_exists: false` in the response indicates that defaults were returned.

    Phase 16 · Slice 5: when `user_id` is not provided the effective owner is
    resolved from request.state (SYSTEM_DEFAULT_USER_ID in bypass mode, real
    user_id when AUTH_ENABLED=true).
    """
    channel = _validate_channel(channel)
    # Resolve ownership: explicit admin override → else JWT/bypass identity
    effective_uid: Optional[str] = user_id if user_id is not None else resolve_effective_user_id(request)

    try:
        async with get_session() as session:
            stmt = (
                select(UserDeliveryPref)
                .where(UserDeliveryPref.channel == channel)
                .where(
                    UserDeliveryPref.user_id == effective_uid
                    if effective_uid is not None
                    else UserDeliveryPref.user_id.is_(None)
                )
                .execution_options(populate_existing=True)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            return _safe_defaults(channel, effective_uid)
        return _row_to_response(row, channel, effective_uid)

    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[delivery_prefs] GET failed (returning defaults): %r", exc)
        return _safe_defaults(channel, effective_uid)


@router.patch(
    "/preferences",
    response_model=DeliveryPrefsResponse,
    summary="Update delivery preferences",
)
async def patch_delivery_preferences(
    request: Request,
    body: DeliveryPrefsPatch,
    channel: str = Query(default="in_app", description="Delivery channel"),
    user_id: Optional[str] = Query(default=None, description="User ID (admin override; omit to use JWT identity)"),
) -> DeliveryPrefsResponse:
    """Create-or-update delivery preferences for the given channel / user.

    Only fields present in the request body are written; omitted fields
    retain their current values.

    Validation
    ----------
    * `min_severity` is normalised to canonical form; unknown values → 422.
    * `daily_cap` must be between 1 and 200 inclusive.
    * `quiet_hours_start` / `quiet_hours_end` must be 0–23 (hour of day UTC).
    * `timezone` is stored as-is; unknown IANA zones default to UTC at
      delivery time (fail-safe).
    * `mute_until` is normalised to UTC if tz-naive.

    Phase 16 · Slice 5: ownership resolved from request.state when user_id not provided.
    """
    channel = _validate_channel(channel)
    effective_uid: Optional[str] = user_id if user_id is not None else resolve_effective_user_id(request)

    update_fields = body.non_null_fields()

    try:
        async with get_session() as session:
            row = await update_prefs(
                session,
                user_id=effective_uid,
                channel=channel,
                **update_fields,
            )
            await session.commit()

        if row is None:
            raise HTTPException(status_code=503, detail="database unavailable")
        return _row_to_response(row, channel, effective_uid)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[delivery_prefs] PATCH failed: %r", exc)
        raise HTTPException(status_code=500, detail=f"failed to update preferences: {exc}")
