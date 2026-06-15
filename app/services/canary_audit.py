"""
Canary telemetry persistence — Phase 9G reliability patch.

Writes dossier-injection canary events to the existing audit_log table.
This makes telemetry durable across process restarts, Render spin-downs,
and OOM recycles — all of which silently reset the in-memory counters in
dossier_canary_telemetry.py.

Schema mapping (no new table, no migration required):
  resource     = "dossier_injection"
  action       = "canary_decision" | "canary_outcome"
  resource_id  = session_id[:36]          (indexable, queryable by session)
  user_agent   = JSON-encoded telemetry   (Text field; no prompt/dossier/model output)
  user_id      = None                     (system-generated event, no user actor)
  ip_address   = None

NEVER stored:
  - prompt text
  - dossier block text
  - raw model output
  - user PII

All functions are null-session safe (return falsy when session is None).
All query functions degrade to zero/None on exception rather than raising.
All write functions are non-fatal: exceptions are logged and swallowed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_RESOURCE = "dossier_injection"
_ACTION_DECISION = "canary_decision"
_ACTION_OUTCOME  = "canary_outcome"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    import uuid as _uuid
    return str(_uuid.uuid4())


# ---------------------------------------------------------------------------
# § Write functions (non-fatal)
# ---------------------------------------------------------------------------

async def append_canary_decision(
    session,
    *,
    session_id: str,
    cohort: str,
    ticker: str,
    token_count: int,
    block_tokens: int,
) -> Optional[str]:
    """Append one canary_decision event to audit_log.

    Called immediately after cohort assignment, before synthesis starts.
    Returns the new row's id, or None on failure or when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import AuditLog

        payload: Dict[str, Any] = {
            "session_id":  session_id,
            "cohort":      cohort,
            "ticker":      ticker,
            "token_count": token_count,
            "block_tokens": block_tokens,
        }
        row = AuditLog(
            id=_new_id(),
            user_id=None,
            resource=_RESOURCE,
            resource_id=session_id[:36],
            action=_ACTION_DECISION,
            ip_address=None,
            user_agent=json.dumps(payload, default=str),
        )
        session.add(row)
        await session.flush()
        return row.id
    except Exception as exc:
        logger.warning("[canary_audit] decision write failed (non-fatal): %r", exc)
        return None


async def append_canary_outcome(
    session,
    *,
    session_id: str,
    cohort: str,
    ticker: str,
    injected: bool,
    fallback: bool,
    wall_cap_fallback: bool,
    conviction: Optional[float],
    specificity: Optional[float],
    cve: Optional[float],
    latency_ms: Optional[int],
) -> Optional[str]:
    """Append one canary_outcome event to audit_log.

    Called immediately after route_question returns (or wall-cap fallback
    is produced), before the streaming generator yields the response body.
    Returns the new row's id, or None on failure or when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import AuditLog

        payload: Dict[str, Any] = {
            "session_id":       session_id,
            "cohort":           cohort,
            "ticker":           ticker,
            "injected":         injected,
            "fallback":         fallback,
            "wall_cap_fallback": wall_cap_fallback,
            "conviction":       conviction,
            "specificity":      specificity,
            "cve":              cve,
            "latency_ms":       latency_ms,
        }
        row = AuditLog(
            id=_new_id(),
            user_id=None,
            resource=_RESOURCE,
            resource_id=session_id[:36],
            action=_ACTION_OUTCOME,
            ip_address=None,
            user_agent=json.dumps(payload, default=str),
        )
        session.add(row)
        await session.flush()
        return row.id
    except Exception as exc:
        logger.warning("[canary_audit] outcome write failed (non-fatal): %r", exc)
        return None


# ---------------------------------------------------------------------------
# § Fire-and-forget wrappers (create_task targets)
# ---------------------------------------------------------------------------

async def _persist_decision(
    session_id: str,
    cohort: str,
    ticker: str,
    token_count: int,
    block_tokens: int,
) -> None:
    """Open a DB session and write one canary_decision row.  Errors swallowed."""
    try:
        from app.db import get_session
        async with get_session() as s:
            if s is None:
                return
            await append_canary_decision(
                s,
                session_id=session_id,
                cohort=cohort,
                ticker=ticker,
                token_count=token_count,
                block_tokens=block_tokens,
            )
            await s.commit()
    except Exception as exc:
        logger.debug("[canary_audit] _persist_decision task error (non-fatal): %r", exc)


async def _persist_outcome(
    session_id: str,
    cohort: str,
    ticker: str,
    injected: bool,
    fallback: bool,
    wall_cap_fallback: bool,
    conviction: Optional[float],
    specificity: Optional[float],
    cve: Optional[float],
    latency_ms: Optional[int],
) -> None:
    """Open a DB session and write one canary_outcome row.  Errors swallowed."""
    try:
        from app.db import get_session
        async with get_session() as s:
            if s is None:
                return
            await append_canary_outcome(
                s,
                session_id=session_id,
                cohort=cohort,
                ticker=ticker,
                injected=injected,
                fallback=fallback,
                wall_cap_fallback=wall_cap_fallback,
                conviction=conviction,
                specificity=specificity,
                cve=cve,
                latency_ms=latency_ms,
            )
            await s.commit()
    except Exception as exc:
        logger.debug("[canary_audit] _persist_outcome task error (non-fatal): %r", exc)


def schedule_decision_persist(
    loop_or_create_task,
    *,
    session_id: str,
    cohort: str,
    ticker: str,
    token_count: int,
    block_tokens: int,
) -> None:
    """Schedule a fire-and-forget decision persistence task.

    `loop_or_create_task` should be `asyncio.create_task` (preferred in a
    running async context) or the event loop's `create_task` method.
    Errors creating the task are swallowed — telemetry must never block.
    """
    try:
        loop_or_create_task(
            _persist_decision(
                session_id=session_id,
                cohort=cohort,
                ticker=ticker,
                token_count=token_count,
                block_tokens=block_tokens,
            ),
            name=f"caud-dec-{session_id[:8]}",
        )
    except Exception as exc:
        logger.debug("[canary_audit] schedule_decision_persist failed (non-fatal): %r", exc)


def schedule_outcome_persist(
    loop_or_create_task,
    *,
    session_id: str,
    cohort: str,
    ticker: str,
    injected: bool,
    fallback: bool,
    wall_cap_fallback: bool,
    conviction: Optional[float],
    specificity: Optional[float],
    cve: Optional[float],
    latency_ms: Optional[int],
) -> None:
    """Schedule a fire-and-forget outcome persistence task.

    Call this as early as possible after route_question returns so the
    write is enqueued before the streaming generator can be torn down.
    """
    try:
        loop_or_create_task(
            _persist_outcome(
                session_id=session_id,
                cohort=cohort,
                ticker=ticker,
                injected=injected,
                fallback=fallback,
                wall_cap_fallback=wall_cap_fallback,
                conviction=conviction,
                specificity=specificity,
                cve=cve,
                latency_ms=latency_ms,
            ),
            name=f"caud-out-{session_id[:8]}",
        )
    except Exception as exc:
        logger.debug("[canary_audit] schedule_outcome_persist failed (non-fatal): %r", exc)


# ---------------------------------------------------------------------------
# § Read / count functions (admin observability)
# ---------------------------------------------------------------------------

async def count_decisions(session) -> int:
    """Count audit_log rows with action='canary_decision'."""
    if session is None:
        return 0
    try:
        from app.db.models import AuditLog
        from sqlalchemy import select, func

        result = await session.execute(
            select(func.count(AuditLog.id))
            .where(AuditLog.resource == _RESOURCE)
            .where(AuditLog.action == _ACTION_DECISION)
        )
        return result.scalar_one() or 0
    except Exception as exc:
        logger.debug("[canary_audit] count_decisions failed (non-fatal): %r", exc)
        return 0


async def count_outcomes(session) -> int:
    """Count audit_log rows with action='canary_outcome'."""
    if session is None:
        return 0
    try:
        from app.db.models import AuditLog
        from sqlalchemy import select, func

        result = await session.execute(
            select(func.count(AuditLog.id))
            .where(AuditLog.resource == _RESOURCE)
            .where(AuditLog.action == _ACTION_OUTCOME)
        )
        return result.scalar_one() or 0
    except Exception as exc:
        logger.debug("[canary_audit] count_outcomes failed (non-fatal): %r", exc)
        return 0


async def _load_outcome_payloads(session) -> list:
    """Fetch and parse user_agent JSON for all canary_outcome rows."""
    from app.db.models import AuditLog
    from sqlalchemy import select

    result = await session.execute(
        select(AuditLog.user_agent)
        .where(AuditLog.resource == _RESOURCE)
        .where(AuditLog.action == _ACTION_OUTCOME)
    )
    rows = result.scalars().all()
    parsed = []
    for raw in rows:
        try:
            parsed.append(json.loads(raw) if raw else {})
        except Exception:
            pass
    return parsed


async def count_injected_outcomes(session) -> int:
    """Count canary_outcome rows where cohort='injected'."""
    if session is None:
        return 0
    try:
        payloads = await _load_outcome_payloads(session)
        return sum(1 for p in payloads if p.get("cohort") == "injected")
    except Exception as exc:
        logger.debug("[canary_audit] count_injected_outcomes failed (non-fatal): %r", exc)
        return 0


async def count_control_outcomes(session) -> int:
    """Count canary_outcome rows where cohort='control'."""
    if session is None:
        return 0
    try:
        payloads = await _load_outcome_payloads(session)
        return sum(1 for p in payloads if p.get("cohort") == "control")
    except Exception as exc:
        logger.debug("[canary_audit] count_control_outcomes failed (non-fatal): %r", exc)
        return 0


async def count_wall_cap_fallbacks(session) -> int:
    """Count canary_outcome rows where wall_cap_fallback=True."""
    if session is None:
        return 0
    try:
        payloads = await _load_outcome_payloads(session)
        return sum(1 for p in payloads if p.get("wall_cap_fallback") is True)
    except Exception as exc:
        logger.debug("[canary_audit] count_wall_cap_fallbacks failed (non-fatal): %r", exc)
        return 0


async def latest_event_at(session) -> Optional[datetime]:
    """Return the created_at of the most recent dossier_injection event, or None."""
    if session is None:
        return None
    try:
        from app.db.models import AuditLog
        from sqlalchemy import select

        result = await session.execute(
            select(AuditLog.created_at)
            .where(AuditLog.resource == _RESOURCE)
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.debug("[canary_audit] latest_event_at failed (non-fatal): %r", exc)
        return None


async def build_persisted_snapshot(session) -> Dict[str, Any]:
    """Return a dict of persisted canary counts for the admin status endpoint.

    All values degrade to zero/None on error — never raises.
    """
    if session is None:
        return _empty_snapshot()
    try:
        dec   = await count_decisions(session)
        out   = await count_outcomes(session)
        inj   = await count_injected_outcomes(session)
        ctrl  = await count_control_outcomes(session)
        wall  = await count_wall_cap_fallbacks(session)
        latest = await latest_event_at(session)
        return {
            "decision_count":           dec,
            "outcome_count":            out,
            "injected_outcome_count":   inj,
            "control_outcome_count":    ctrl,
            "wall_cap_fallback_count":  wall,
            "latest_event_at": latest.isoformat() if latest else None,
        }
    except Exception as exc:
        logger.debug("[canary_audit] build_persisted_snapshot failed (non-fatal): %r", exc)
        return _empty_snapshot()


def _empty_snapshot() -> Dict[str, Any]:
    return {
        "decision_count":           0,
        "outcome_count":            0,
        "injected_outcome_count":   0,
        "control_outcome_count":    0,
        "wall_cap_fallback_count":  0,
        "latest_event_at":          None,
    }
