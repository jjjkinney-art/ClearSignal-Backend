"""
Phase 10A · Slice 2 — Lease-based lock service for the Continuous Intelligence Loop.

This is the **exclusive owner** of lock semantics for the loop.  The scheduler
(Slice 4) calls acquire/renew/release/reap; no other module touches the
job_locks table or this service's API.

Spec reference: PHASE_10A_LOOP_SPEC.md §4 (The locking model).

Design principles carried from the spec:
  DP#5 — Single-flight is enforced by a lease, not a mutex.
          Every lock is a time-boxed lease that a crashed holder forfeits
          automatically.  No lock can deadlock if its holder dies.

  Lease semantics:
    * acquire() — conditional compare-and-swap: take iff unheld OR expired.
      Returns the fence_token on success, None if another holder has it.
    * renew()   — heartbeat: push lease_expires_utc forward while running.
      Validates both holder_id AND fence_token to reject zombie holders.
    * release() — clear the row on clean completion.
      Zombie-safe: mismatched token → no-op, returns False.
    * reap()    — recover expired leases; called at the top of each tick.

  Fence token:
    * Monotonic integer incremented on every successful acquire().
    * The holder carries its token; any write that asserts the token is
      rejected if another worker has since reclaimed the lease.
    * Starts at 1 (token 0 means "unacquired" in state snapshots).

  Null-object safety:
    * session=None → every function returns its safe default.
    * Callers never need to guard `if session is None`.

  No scheduler logic, no job logic, no delivery logic here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.db.repositories import loop_repo

logger = logging.getLogger(__name__)

# Default lease duration — matches spec §4 and config default loop_lock_lease_s=120.
_DEFAULT_LEASE_S: int = 120


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expires(lease_s: int) -> datetime:
    return _now() + timedelta(seconds=lease_s)


def _is_expired(db_dt: datetime) -> bool:
    """Return True if *db_dt* is in the past.

    SQLite returns naive UTC datetimes; Postgres returns timezone-aware.
    This helper normalises both sides before comparing so the service
    works correctly on either backend without modification.
    """
    now = datetime.now(timezone.utc)
    if db_dt.tzinfo is None:
        # SQLite: compare naive UTC to naive UTC
        return db_dt < now.replace(tzinfo=None)
    return db_dt < now


def _now_compat(db_dt: datetime) -> datetime:
    """Return a now() datetime with the same tzinfo state as *db_dt*.

    Used wherever a Python-level comparison is needed (not a SQL WHERE
    clause) so that naive and aware datetimes compare correctly.
    """
    now = datetime.now(timezone.utc)
    if db_dt.tzinfo is None:
        return now.replace(tzinfo=None)
    return now


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def acquire_lock(
    session,
    lock_name: str,
    holder_id: str,
    lease_s: int = _DEFAULT_LEASE_S,
) -> Optional[int]:
    """
    Acquire a named lease.

    Parameters
    ----------
    session    : AsyncSession or None
    lock_name  : Namespaced string — e.g. ``"loop:tick"``, ``"loop:job:{id}"``
    holder_id  : Stable worker identity — e.g. ``"{host}:{pid}:{boot_uuid}"``
    lease_s    : Lease duration in seconds (default 120).

    Returns
    -------
    int   — the fence_token for this lease generation (≥ 1).  The caller
            must carry this token for all subsequent renew/release calls.
    None  — another holder has a valid (non-expired) lease; back off.

    Algorithm
    ---------
    1. Read current lock state.
    2. If no row → INSERT (fence_token = 1).  Savepoint protects against
       concurrent INSERT races without poisoning the outer transaction.
    3. If row exists and lease has expired OR same holder → conditional
       UPDATE with fence_token CAS (expected = current, new = current + 1).
    4. If row exists and lease is active with a different holder → None.

    Postgres note: on the web tier with multiple instances, two concurrent
    workers may both read "no row" and race to INSERT.  The PK constraint
    catches the loser; the savepoint absorbs the error.  For the UPDATE
    path, the fence_token CAS ensures only one update wins.
    """
    if session is None:
        return None

    now = _now()
    expires = _expires(lease_s)

    existing = await loop_repo.lock_read(session, lock_name)

    # ── Case 1: No lock exists — insert fresh ────────────────────────────
    if existing is None:
        new_token = 1
        inserted = await loop_repo.lock_insert(
            session, lock_name, holder_id, now, expires, new_token
        )
        if inserted:
            logger.debug(
                "[lock_service] acquired %r by %r (fresh insert, token=%d)",
                lock_name, holder_id, new_token,
            )
            return new_token
        # INSERT race — another worker beat us; do not retry automatically
        logger.debug(
            "[lock_service] acquire race lost for %r by %r (concurrent insert)",
            lock_name, holder_id,
        )
        return None

    # ── Case 2: Row exists but lease has expired ─────────────────────────
    if _is_expired(existing.lease_expires_utc):
        new_token = existing.fence_token + 1
        updated = await loop_repo.lock_update_cas(
            session, lock_name,
            expected_fence_token=existing.fence_token,
            holder_id=holder_id,
            acquired_utc=now,
            lease_expires_utc=expires,
            new_fence_token=new_token,
        )
        if updated:
            logger.debug(
                "[lock_service] acquired %r by %r (expired reclaim, token=%d)",
                lock_name, holder_id, new_token,
            )
            return new_token
        # CAS failed — another worker reclaimed it between our read and update
        logger.debug(
            "[lock_service] acquire CAS lost for %r by %r (concurrent expiry claim)",
            lock_name, holder_id,
        )
        return None

    # ── Case 3: Same holder re-acquires ──────────────────────────────────
    # Allowed: acts like a renew-via-acquire, increments fence_token.
    if existing.holder_id == holder_id:
        new_token = existing.fence_token + 1
        updated = await loop_repo.lock_update_cas(
            session, lock_name,
            expected_fence_token=existing.fence_token,
            holder_id=holder_id,
            acquired_utc=now,
            lease_expires_utc=expires,
            new_fence_token=new_token,
        )
        if updated:
            logger.debug(
                "[lock_service] re-acquired %r by same holder %r (token=%d)",
                lock_name, holder_id, new_token,
            )
            return new_token
        return None

    # ── Case 4: Held by a different holder with a valid lease ────────────
    logger.debug(
        "[lock_service] %r is held by %r until %s — %r backs off",
        lock_name, existing.holder_id, existing.lease_expires_utc.isoformat(), holder_id,
    )
    return None


async def renew_lock(
    session,
    lock_name: str,
    holder_id: str,
    fence_token: int,
    lease_s: int = _DEFAULT_LEASE_S,
) -> bool:
    """
    Extend an active lease (heartbeat).

    Must be called on an interval well inside the lease duration
    (spec recommends every lease_s / 3) to keep a long-running job alive.

    Returns True if the lease was extended.
    Returns False if:
      - no lock row found (lock was reclaimed/reaped)
      - holder_id does not match (wrong process)
      - fence_token does not match (zombie: lease was reclaimed and the
        new holder has a higher token)

    The fence_token check is the zombie-protection layer: a paused process
    that resumes after its lease expired and another worker reclaimed it
    carries a stale token (current_db_token > its token) and is rejected.
    """
    if session is None:
        return False

    new_expires = _expires(lease_s)
    renewed = await loop_repo.lock_renew(
        session, lock_name, holder_id, fence_token, new_expires
    )
    if renewed:
        logger.debug(
            "[lock_service] renewed %r by %r (token=%d, expires=%s)",
            lock_name, holder_id, fence_token, new_expires.isoformat(),
        )
    else:
        logger.warning(
            "[lock_service] renew REJECTED for %r by %r (token=%d) — "
            "stale holder or lock reclaimed",
            lock_name, holder_id, fence_token,
        )
    return renewed


async def release_lock(
    session,
    lock_name: str,
    holder_id: str,
    fence_token: int,
) -> bool:
    """
    Release an active lease on clean completion.

    Returns True if the row was deleted (lock released).
    Returns False (silently) for all zombie / mismatch cases:
      - no row (already released — idempotent, caller may treat as success)
      - different holder_id
      - stale fence_token (zombie: lease was reclaimed by another worker)

    A zombie that calls release() after its lease was reclaimed and re-issued
    to another worker will get False here — its late release is a no-op and
    the new holder is unaffected.

    Callers: treat False as "already gone or not ours" — do not re-attempt.
    """
    if session is None:
        return False

    released = await loop_repo.lock_release(
        session, lock_name, holder_id, fence_token
    )
    if released:
        logger.debug(
            "[lock_service] released %r by %r (token=%d)",
            lock_name, holder_id, fence_token,
        )
    else:
        logger.debug(
            "[lock_service] release no-op for %r by %r (token=%d) — "
            "already gone, wrong holder, or stale token",
            lock_name, holder_id, fence_token,
        )
    return released


async def get_lock_state(
    session,
    lock_name: str,
) -> Optional[Dict[str, Any]]:
    """
    Return the current state of a named lock as a dict, or None if absent.

    Used by the observability endpoint and tests.  Read-only; never modifies
    the lock.

    Returned dict keys:
        lock_name, holder_id, acquired_utc, lease_expires_utc,
        fence_token, is_expired (bool)
    """
    if session is None:
        return None

    row = await loop_repo.lock_read(session, lock_name)
    if row is None:
        return None

    return {
        "lock_name":        row.lock_name,
        "holder_id":        row.holder_id,
        "acquired_utc":     row.acquired_utc.isoformat(),
        "lease_expires_utc": row.lease_expires_utc.isoformat(),
        "fence_token":      row.fence_token,
        "is_expired":       _is_expired(row.lease_expires_utc),
    }


async def reap_expired_locks(session) -> List[str]:
    """
    Delete all locks whose lease has expired.

    Called at the top of each tick() before selecting jobs (spec §2.2).
    Recovered lock_names are returned for telemetry / logging.
    Returns [] if session is None.
    """
    if session is None:
        return []

    now = _now()
    reclaimed = await loop_repo.lock_reap_expired(session, now)
    if reclaimed:
        logger.info(
            "[lock_service] reaped %d expired lock(s): %s",
            len(reclaimed), reclaimed,
        )
    return reclaimed


async def is_lock_free(session, lock_name: str) -> bool:
    """
    Return True if the named lock is currently unheld (or expired).

    Convenience predicate for tests and observability; does not acquire.
    """
    if session is None:
        return True  # safe default: if we can't check, assume free

    row = await loop_repo.lock_read(session, lock_name)
    if row is None:
        return True
    return _is_expired(row.lease_expires_utc)


async def fence_check(
    session,
    lock_name: str,
    holder_id: str,
    fence_token: int,
) -> bool:
    """
    Verify that the caller's (holder_id, fence_token) matches the current DB state.

    Returns True if the lock is held by this holder with this token.
    Returns False (zombie guard) if:
      - no row (lock reaped)
      - different holder
      - token mismatch (lock reclaimed and re-issued since we last acquired)

    Used by the delivery service before non-idempotent sends (spec §4.4).
    """
    if session is None:
        return False

    row = await loop_repo.lock_read(session, lock_name)
    if row is None:
        return False
    return row.holder_id == holder_id and row.fence_token == fence_token
