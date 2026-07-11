"""Pre-flight security/cost gate for the expensive /ask endpoint (Sprint 0).

``enforce_ask_preflight`` runs BEFORE any LLM work or streaming begins so it can
return a clean status code:

    401  auth required (AUTH_ENABLED=true and no/invalid JWT)
    403  entitlement denied, or entitlement/quota enforcement misconfigured
    413  question exceeds ASK_QUESTION_MAX_LENGTH
    429  per-IP or per-user rate limit exceeded, or daily quota exhausted

Fail-closed: when auth / entitlement / quota enforcement is ENABLED but the
backing data cannot be resolved, the request is denied rather than allowed.

Privacy: only opaque keys, counts, and status decisions are logged — never the
question text, tokens, secrets, or user financial data.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException
from starlette.requests import Request

from ..config import settings
from ..dependencies.auth import require_user_id, SYSTEM_DEFAULT_USER_ID
from ..services.usage_tracking import usage_tracker
from .rate_limit import rate_limiter, client_ip

logger = logging.getLogger(__name__)

# Account states that may use the service when entitlements are enforced.
_SERVICEABLE_PLAN_STATUS = frozenset(
    {"active", "trialing", "grace", "free_fallback", "system"}
)

_ASK_EVENT = "ask"


async def _resolve_entitlements_or_fail(user_id: str):
    """Resolve entitlements, failing CLOSED (403) when enforcement is on but the
    entitlement plumbing is unavailable or the account is not serviceable."""
    # System / bypass user is always unlimited and needs no DB.
    if user_id == SYSTEM_DEFAULT_USER_ID:
        return
    try:
        from ..db import get_session
        from ..services.entitlement_service import resolve_entitlements
    except Exception:
        logger.error("[ask] entitlement enforcement on but plumbing unavailable; failing closed")
        raise HTTPException(status_code=403, detail="Entitlement verification unavailable.")

    try:
        async with get_session() as db:
            if db is None:
                # Enforcement requested but persistence is disabled → misconfig.
                logger.error("[ask] entitlements enforced but no DB session; failing closed")
                raise HTTPException(status_code=403, detail="Entitlement verification unavailable.")
            ent = await resolve_entitlements(db, user_id)
    except HTTPException:
        raise
    except Exception:
        logger.error("[ask] entitlement resolution error; failing closed")
        raise HTTPException(status_code=403, detail="Entitlement verification unavailable.")

    if ent is None or getattr(ent, "plan_status", None) not in _SERVICEABLE_PLAN_STATUS:
        raise HTTPException(status_code=403, detail="Your plan does not permit this request.")


async def enforce_ask_preflight(http_request: Request, question: str) -> str:
    """Gate an /ask request.  Returns the acting user_id on success; raises
    HTTPException (401/403/413/429) otherwise.  On success, consumes one unit of
    the caller's daily quota."""
    cfg = settings

    # 1. Authentication (401 when AUTH_ENABLED and no valid token; safe bypass
    #    to the system user when auth is disabled or middleware absent).
    user_id = require_user_id(http_request)
    is_system = user_id == SYSTEM_DEFAULT_USER_ID

    # 2. Question length cap (413).
    if question is not None and len(question) > cfg.ask_question_max_length:
        raise HTTPException(status_code=413, detail="Question exceeds the maximum allowed length.")

    # 3. Entitlements (403) — only when explicitly enforced.
    if cfg.entitlements_enforced:
        await _resolve_entitlements_or_fail(user_id)

    # 4. Strict rate limits for /ask: per-IP and per-user (429).
    if cfg.rate_limit_enabled:
        ip = client_ip(http_request)
        allowed_ip, retry_ip = rate_limiter.check(
            f"ask:ip:{ip}", cfg.rate_limit_ask_per_ip_per_min, cfg.rate_limit_window_s
        )
        if not allowed_ip:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please slow down.",
                headers={"Retry-After": str(retry_ip)},
            )
        # Per-user limit does not apply to the shared system/bypass identity.
        if not is_system:
            allowed_user, retry_user = rate_limiter.check(
                f"ask:user:{user_id}",
                cfg.rate_limit_ask_per_user_per_min,
                cfg.rate_limit_window_s,
            )
            if not allowed_user:
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please slow down.",
                    headers={"Retry-After": str(retry_user)},
                )

    # 5. Per-user daily quota (429).  System/bypass user is unlimited.
    if not is_system and not usage_tracker.within_daily_quota(
        user_id, cfg.ask_daily_quota, _ASK_EVENT
    ):
        raise HTTPException(
            status_code=429,
            detail="Daily request quota reached. Try again tomorrow.",
        )

    # All gates passed — consume one quota unit (only for real users).
    if not is_system:
        usage_tracker.incr_daily(user_id, _ASK_EVENT)
    logger.info("[ask] preflight ok (user=%.8s system=%s)", user_id, is_system)
    return user_id
