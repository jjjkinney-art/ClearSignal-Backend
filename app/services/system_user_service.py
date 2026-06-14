"""
System user seed + NULL ownership claim — Phase 16 · Slice 2.

Provides three idempotent operations called at startup:

  ensure_system_user(session)
      Insert the well-known SYSTEM_DEFAULT_USER row if it does not exist.
      Idempotent — safe to call on every boot.

  claim_null_ownership(session)
      For every user-scoped table that has a nullable user_id column, run:
          UPDATE <table> SET user_id = SYSTEM_DEFAULT_USER_ID WHERE user_id IS NULL
      After one pass, every row has a non-NULL owner.  Re-running claims 0 rows.
      Returns a ClaimResult with per-table counts.

  restore_null_ownership(session)
      The exact inverse of claim_null_ownership:
          UPDATE <table> SET user_id = NULL WHERE user_id = SYSTEM_DEFAULT_USER_ID
      Reverses system-owned rows back to NULL.  Only valid for rollback before
      any real-user import (Slice 6) has run.
      Returns a RestoreResult with per-table counts.

Non-destructive guarantee
  Every ownership change is an UPDATE of the user_id field only.
  No rows are created or deleted by any function in this module.
  The system claim and restore are exact inverses of each other.

No-password guarantee
  This module never reads, writes, or validates any credential.
  Supabase Auth is the sole credential custodian.

Null-session safety
  All public functions return safe defaults when session is None.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_DEFAULT_USER_ID: str = "00000000-0000-0000-0000-000000000001"
SYSTEM_DEFAULT_EMAIL:   str = "system@clearsignal.internal"

# Tables whose user_id column is nullable and represents user-scoped content.
#
# Ordering: high-value ownership tables first (imported by Slice 6),
# then analysis/memory artifacts (stay on system user as audit baseline),
# then dossier tables, then delivery archive.
#
# Excluded intentionally:
#   notifications          — user_id NOT NULL; orphan rows impossible
#   briefing_sessions      — no user_id column
#   portfolio_positions    — ownership inherited via portfolio_id
#   portfolio_insights     — ownership inherited via portfolio_id
#   users                  — identity table; system user seeded separately
#   user_profiles          — user_id is the PK (1:1); seeded with the user row
#   user_settings          — user_id is the PK (1:1); seeded with the user row
#   audit_log              — actor field, not ownership; not claimed
_CLAIMABLE_TABLES: tuple = (
    # § Core user-scoped ownership (Slice 6 import candidates)
    "watched_tickers",
    "portfolios",
    "user_delivery_prefs",
    "digest_batches",
    # § Analysis / memory — stay on system user; excluded from Slice 6 real-user import
    "thesis_versions",
    "memory_entries",
    "personalized_insights",
    # § Dossier tables
    "company_dossier",
    "dossier_core_debate",
    "dossier_moat_dimension",
    "dossier_catalyst",
    "dossier_variant",
    "dossier_durability",
    "dossier_failure_mode",
    "dossier_revision",
    "dossier_evidence_ref",
    # § Delivery archive
    "delivery_ledger_archive",
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ClaimResult:
    """Result returned by claim_null_ownership."""
    claimed:        Dict[str, int] = field(default_factory=dict)
    total:          int = 0
    system_user_id: str = SYSTEM_DEFAULT_USER_ID


@dataclass
class RestoreResult:
    """Result returned by restore_null_ownership."""
    restored:       Dict[str, int] = field(default_factory=dict)
    total:          int = 0
    system_user_id: str = SYSTEM_DEFAULT_USER_ID


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def ensure_system_user(session) -> Optional[object]:
    """Insert the canonical system user row if it does not already exist.

    Uses get_or_create_system_user from account_repo so the operation is
    idempotent — calling it ten times produces exactly one row.

    Returns the User ORM row, or None when session is None.
    """
    if session is None:
        return None

    try:
        from app.db.repositories.account_repo import get_or_create_system_user
        user = await get_or_create_system_user(session)
        logger.debug(
            "[16.2] system user ready: id=%s account_type=%s",
            SYSTEM_DEFAULT_USER_ID,
            getattr(user, "account_type", "?"),
        )
        return user
    except Exception as exc:
        logger.warning("[16.2] ensure_system_user failed (non-fatal): %r", exc)
        return None


async def claim_null_ownership(session) -> ClaimResult:
    """Assign SYSTEM_DEFAULT_USER_ID to every NULL-owned user_id row.

    For each table in _CLAIMABLE_TABLES runs:
        UPDATE <table> SET user_id = :sys_id WHERE user_id IS NULL

    The operation is idempotent — re-running after a complete pass claims
    exactly 0 additional rows and logs 0 per table.

    Returns a ClaimResult with per-table row counts.
    """
    if session is None:
        return ClaimResult()

    claimed: Dict[str, int] = {}
    total = 0

    for table in _CLAIMABLE_TABLES:
        try:
            stmt = text(
                f"UPDATE {table} SET user_id = :sys_id WHERE user_id IS NULL"
            )
            result = await session.execute(stmt, {"sys_id": SYSTEM_DEFAULT_USER_ID})
            n = result.rowcount if result.rowcount is not None else 0
            claimed[table] = n
            total += n
            if n:
                logger.info("[16.2] claim_null_ownership: %s → %d rows claimed", table, n)
            else:
                logger.debug("[16.2] claim_null_ownership: %s → 0 (already clean)", table)
        except Exception as exc:
            logger.warning(
                "[16.2] claim_null_ownership: %s failed (non-fatal): %r", table, exc
            )
            claimed[table] = 0

    logger.info(
        "[16.2] claim_null_ownership complete: %d rows across %d tables",
        total, len(_CLAIMABLE_TABLES),
    )
    return ClaimResult(claimed=claimed, total=total)


async def restore_null_ownership(session) -> RestoreResult:
    """Reverse the system claim — set user_id back to NULL.

    For each table in _CLAIMABLE_TABLES runs:
        UPDATE <table> SET user_id = NULL WHERE user_id = :sys_id

    This is the exact inverse of claim_null_ownership.

    WARNING: only call this before any Slice 6 real-user import has run.
    After a real-user import, restoring would strip real-user ownership from
    analysis/memory rows that the user never explicitly imported — those rows
    were always system-owned and the restore remains safe, but watchlist /
    portfolio / prefs rows re-assigned by Slice 6 must NOT be included.

    For pre-Slice-6 rollback use this function as-is.  For post-Slice-6
    rollback see the data_claim_service (Slice 6) revert helper.

    Returns a RestoreResult with per-table row counts.
    """
    if session is None:
        return RestoreResult()

    restored: Dict[str, int] = {}
    total = 0

    for table in _CLAIMABLE_TABLES:
        try:
            stmt = text(
                f"UPDATE {table} SET user_id = NULL WHERE user_id = :sys_id"
            )
            result = await session.execute(stmt, {"sys_id": SYSTEM_DEFAULT_USER_ID})
            n = result.rowcount if result.rowcount is not None else 0
            restored[table] = n
            total += n
            if n:
                logger.info("[16.2] restore_null_ownership: %s → %d rows restored", table, n)
            else:
                logger.debug("[16.2] restore_null_ownership: %s → 0 (nothing to restore)", table)
        except Exception as exc:
            logger.warning(
                "[16.2] restore_null_ownership: %s failed (non-fatal): %r", table, exc
            )
            restored[table] = 0

    logger.info(
        "[16.2] restore_null_ownership complete: %d rows across %d tables",
        total, len(_CLAIMABLE_TABLES),
    )
    return RestoreResult(restored=restored, total=total)


async def count_orphan_rows(session) -> Dict[str, int]:
    """Return a dict of table → count of rows where user_id IS NULL.

    Used by the observability snapshot (Slice 8) and the production
    validation script to assert zero orphan rows after Slice 2 runs.
    Returns {} when session is None.
    """
    if session is None:
        return {}

    counts: Dict[str, int] = {}

    for table in _CLAIMABLE_TABLES:
        try:
            result = await session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL")
            )
            row = result.one()
            counts[table] = int(row[0])
        except Exception as exc:
            logger.warning(
                "[16.2] count_orphan_rows: %s failed (non-fatal): %r", table, exc
            )
            counts[table] = -1  # -1 signals a counting error, not a clean 0

    return counts


def claimable_tables() -> tuple:
    """Return the tuple of table names subject to the NULL claim.

    Exposed for observability and test assertions so callers don't need to
    import the private constant.
    """
    return _CLAIMABLE_TABLES
