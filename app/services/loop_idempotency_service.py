"""
Phase 10A · Slice 5 — Idempotency enforcement.

Two idempotency keys protect the Continuous Intelligence Loop from
duplicating work or delivery across retries, restarts, and concurrent
workers.

  work_key
    Prevents double-execution of a job.
    Canon: SHA-256(job_type:target_key:period_bucket)[:64]
    Used by the scheduler before dispatching to a producer.  If a
    succeeded JobRun already exists for this key, the job is
    short-circuited (outcome=short_circuited) and no producer is called.

  content_key
    Prevents double-delivery of a generated artifact.
    Canon: SHA-256(user_id:channel:target_key:payload_hash)[:64]
    Enforced at the DB layer by delivery_ledger.UNIQUE(content_key).
    guard_delivery() also enforces it at the service layer before the
    INSERT, returning None instead of raising on conflict.

  payload_hash
    Stable SHA-256 of a JSON payload.  Keys are sorted recursively so
    insertion order never affects the hash.  Lets producers hash a
    generated brief's content to detect unchanged re-generation.

Public API
----------
    build_payload_hash(payload)                          -> str (64 hex)
    build_work_key(job_type, target_key, period_bucket)  -> str (64 hex)
    build_content_key(user_id, channel, target_key, payload_hash) -> str (64 hex)
    check_work_key_succeeded(session, work_key)          -> bool
    guard_delivery(session, user_id, channel, target_key,
                   payload_hash, *, artifact_ref, not_before_utc) -> Optional[row]

Null-object safety
------------------
  session=None → every async function returns its safe default (False, None, []).
  Callers never need to guard on session.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Optional

from app.db.repositories import loop_repo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hashing primitives
# ---------------------------------------------------------------------------

def build_payload_hash(payload: dict) -> str:
    """
    Stable SHA-256 digest of *payload*.

    Keys are sorted at every level of nesting so two dicts that contain
    the same data in different insertion order always produce the same hash.
    Returns a 64-character lowercase hex string.

    >>> build_payload_hash({"b": 1, "a": 2}) == build_payload_hash({"a": 2, "b": 1})
    True
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_work_key(job_type: str, target_key: str, period_bucket: str) -> str:
    """
    Canonical idempotency key for one job execution.

    Deterministic: identical inputs → identical 64-hex-char key.
    Stored on JobRun.work_key and used by the scheduler for the
    pre-dispatch short-circuit check (spec §3.1).

    Format of the raw string before hashing:
        "{job_type}:{target_key}:{period_bucket}"
    """
    raw = f"{job_type}:{target_key}:{period_bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def build_content_key(
    user_id: str,
    channel: str,
    target_key: str,
    payload_hash: str,
) -> str:
    """
    Canonical dedup key for one delivery artifact.

    Deterministic: identical inputs → identical 64-hex-char key.
    Stored on DeliveryLedger.content_key; UNIQUE constraint at the DB
    layer is the hard stop; guard_delivery() adds a service-layer guard.

    Format of the raw string before hashing:
        "{user_id}:{channel}:{target_key}:{payload_hash}"
    """
    raw = f"{user_id}:{channel}:{target_key}:{payload_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


# ---------------------------------------------------------------------------
# Async helpers (require a session)
# ---------------------------------------------------------------------------

async def check_work_key_succeeded(session, work_key: str) -> bool:
    """
    Return True if a JobRun with *work_key* and outcome='succeeded' exists.

    The scheduler calls this before dispatching to a producer.  A True
    result means the work is already done; dispatch should be skipped.

    Returns False when session is None (treat as "not yet done").
    """
    if session is None:
        return False
    run = await loop_repo.run_lookup_by_work_key(session, work_key, outcome="succeeded")
    return run is not None


async def guard_delivery(
    session,
    user_id: str,
    channel: str,
    target_key: str,
    payload_hash: str,
    *,
    artifact_ref: Optional[str] = None,
    not_before_utc: Optional[datetime] = None,
) -> Optional[Any]:
    """
    Idempotent delivery record creation.

    Computes the canonical content_key and calls delivery_create() with a
    savepoint.  On UNIQUE conflict (same content already queued or delivered)
    returns None — the caller should treat this as "already handled, do not
    re-send".

    Returns the new DeliveryLedger row on first creation.
    Returns None on duplicate or if session is None.

    Example
    -------
    row = await guard_delivery(session, user_id, "in_app", "user_001", phash)
    if row is None:
        # Already queued — no duplicate send
        return
    # ... proceed to send
    """
    if session is None:
        return None

    content_key = build_content_key(user_id, channel, target_key, payload_hash)
    row = await loop_repo.delivery_create(
        session,
        content_key=content_key,
        target_key=target_key,
        channel=channel,
        content_hash=payload_hash,
        artifact_ref=artifact_ref,
        not_before_utc=not_before_utc,
    )
    if row is None:
        logger.debug(
            "[idempotency] guard_delivery: suppressed duplicate for user=%r "
            "channel=%r target=%r (content_key=%s…)",
            user_id, channel, target_key, content_key[:12],
        )
    return row
