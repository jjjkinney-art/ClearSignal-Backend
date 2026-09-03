#!/usr/bin/env python3
"""Watchlist duplicate cleanup EXECUTOR — Section 0.8D.

Deactivates duplicate active watchlist memberships that a Section 0.8C
rehearsal identified and an operator approved. It never deletes a row.

Fail-closed by construction. Execution requires ALL of:

  * an explicit --execute flag (absent it refuses and exits 3);
  * all nine aggregate expectations, supplied explicitly;
  * the approved 64-character rehearsal fingerprint, supplied at runtime.

None of those values is hard-coded here. The fingerprint is an argument, not a
constant, so this script cannot be run against a plan nobody approved.

Selection semantics are NOT reimplemented. The plan and its fingerprint come
from the Section 0.8C rehearsal module, imported and reused verbatim, so the
executor cannot drift from the artifact that was approved.

One transaction, in this order
------------------------------
    1. BEGIN
    2. LOCK TABLE watched_tickers IN SHARE ROW EXCLUSIVE MODE
       -- taken BEFORE the plan is computed, so concurrent watchlist writes
          cannot change the plan between verification and mutation. Readers
          are unaffected; only writers wait.
    3. build the plan            (rehearsal module, verbatim)
    4. verify all nine expectations
    5. recompute the fingerprint and require an EXACT match
    6. write the durable audit trail (one row per candidate + a run row)
    7. UPDATE ... SET active = false WHERE id IN (candidates)
    8. assert the affected-row count equals the candidate count exactly
    9. recompute the aggregates and validate every postcondition
   10. COMMIT -- only if 6, 7, 8 and 9 all succeeded

Any mismatch or exception rolls the whole transaction back. A partial cleanup
is never committed.

Rollback
--------
Each deactivated row is recorded as one audit_log row:

    resource    = "watched_ticker"
    action      = "dedupe"
    resource_id = "<operation_ref>:<row_id>"

plus one run marker (resource="watchlist_dedupe_run", resource_id=<op ref>).
The compound resource_id keeps the correlation inside the column that already
means "identifier", rather than repurposing user_agent (an HTTP field) as a
batch key. Reactivating exactly this operation's rows needs only the opaque
operation reference; row identities never appear in output.

Exit codes
----------
    0  cleanup committed and every postcondition verified
    2  verification failed (expectations or fingerprint) -- nothing written
    3  usage / guard error (e.g. --execute or an expectation omitted)
    4  database unavailable, or the transaction was rolled back
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = str(_HERE.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

TOOL_NAME = "watchlist_duplicate_cleanup_execute"
TOOL_VERSION = "0.8d.1"

RESOURCE_ROW = "watched_ticker"
RESOURCE_RUN = "watchlist_dedupe_run"
ACTION_ROW = "dedupe"
ACTION_RUN = "dedupe_run"

FINGERPRINT_LENGTH = 64


def _rehearsal():
    """Load Section 0.8C's module and reuse its canonical implementation.

    Imported rather than copied: ranking, partitioning, ordering and the
    fingerprint must be byte-identical to what the rehearsal approved.
    """
    path = _HERE / "watchlist_duplicate_cleanup_rehearsal.py"
    spec = importlib.util.spec_from_file_location("_wl_rehearsal", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _rehearsal()
EXPECTATION_FIELDS = R.EXPECTATION_FIELDS

POSTCONDITION_FIELDS = (
    "active_rows",
    "distinct_tickers",
    "active_owners",
    "membership_duplicate_groups",
    "membership_candidate_rows",
    "legacy_duplicate_groups",
    "legacy_candidate_rows",
    "orphan_owners",
    "orphan_rows",
)


class VerificationError(Exception):
    """Verification failed before any write. Nothing was mutated."""


class ExecutionError(Exception):
    """A write-phase check failed. The transaction is rolled back."""


def _sanitise(exc: BaseException) -> str:
    """Exception class only. SQL, parameters, URLs and ids never escape."""
    return type(exc).__name__


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------

async def acquire_table_lock(session) -> str:
    """Lock watched_tickers against concurrent writers. Readers unaffected.

    SHARE ROW EXCLUSIVE blocks INSERT/UPDATE/DELETE and other lock holders,
    but not plain SELECT, so the product stays readable while cleanup runs.

    Must be called BEFORE the plan is built: the whole point is that the row
    set cannot change between the fingerprint check and the UPDATE.
    """
    from sqlalchemy import text
    try:
        dialect = session.bind.dialect.name  # type: ignore[union-attr]
    except Exception:
        return "unknown"
    if dialect == "postgresql":
        await session.execute(
            text("LOCK TABLE watched_tickers IN SHARE ROW EXCLUSIVE MODE"))
        return "postgresql:share_row_exclusive"
    return "%s:not_supported" % dialect


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

async def write_audit(session, operation_ref: str, plan) -> int:
    """Durable rollback record. Exceptions PROPAGATE — audit failure aborts.

    Deliberately NOT account_import_service._audit, which swallows exceptions
    so that audit failures never block a user action. That trade-off is wrong
    here: a cleanup whose rollback record failed to write must not commit.
    """
    from app.db.models import AuditLog

    candidates = [row for row in plan if row.rn > 1]
    session.add(AuditLog(
        id=uuid.uuid4().hex,
        user_id=None,
        resource=RESOURCE_RUN,
        resource_id=operation_ref,
        action=ACTION_RUN,
        created_at=_now(),
    ))
    for row in candidates:
        session.add(AuditLog(
            id=uuid.uuid4().hex,
            user_id=None,
            resource=RESOURCE_ROW,
            resource_id="%s:%s" % (operation_ref, row.row_id),
            action=ACTION_ROW,
            created_at=_now(),
        ))
    await session.flush()
    return len(candidates)


async def audited_row_ids(session, operation_ref: str) -> List[str]:
    """Row ids this operation deactivated. For the rollback path only.

    Never printed. Returned so an independently approved rollback can
    reactivate exactly these rows from the opaque operation reference alone.
    """
    from sqlalchemy import select
    from app.db.models import AuditLog

    prefix = "%s:" % operation_ref
    result = await session.execute(
        select(AuditLog.resource_id)
        .where(AuditLog.resource == RESOURCE_ROW)
        .where(AuditLog.action == ACTION_ROW)
        .where(AuditLog.resource_id.like(prefix + "%"))
    )
    return [rid[len(prefix):] for (rid,) in result.all() if rid]


# ---------------------------------------------------------------------------
# Verification (before any write)
# ---------------------------------------------------------------------------

async def verify(session, expected: Dict[str, Optional[int]],
                 approved_fingerprint: str):
    """Build the plan and prove it is exactly the approved one.

    Raises VerificationError before anything is written.
    """
    plan = await R.build_plan(session)
    report = R.summarise(plan)
    owners, rows = await R.orphan_counts(session)
    report["orphan_owner_count"] = owners
    report["orphan_active_row_count"] = rows
    report.update(R.compare_expectations(report, expected))

    if not report["expectation_match"]:
        raise VerificationError("expectation_mismatch")

    actual = R.plan_fingerprint(plan)
    if actual != approved_fingerprint:
        raise VerificationError("fingerprint_mismatch")
    return plan, report


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

async def execute_cleanup(session, expected: Dict[str, Optional[int]],
                          approved_fingerprint: str,
                          operation_ref: str) -> Dict[str, Any]:
    """One transaction: lock, verify, audit, deactivate, assert, validate.

    The caller owns the transaction: it commits only on a clean return and
    rolls back on any exception.
    """
    from sqlalchemy import update
    from app.db.models import WatchedTicker

    lock_mode = await acquire_table_lock(session)          # 2 — before the plan
    plan, before = await verify(session, expected,
                                approved_fingerprint)      # 3,4,5

    candidate_ids = [row.row_id for row in plan if row.rn > 1]
    audited = await write_audit(session, operation_ref, plan)   # 6
    if audited != len(candidate_ids):
        raise ExecutionError("audit_count_mismatch")

    result = await session.execute(                             # 7
        update(WatchedTicker)
        .where(WatchedTicker.id.in_(candidate_ids))
        .where(WatchedTicker.active.is_(True))
        .values(active=False, updated_at=_now())
        .execution_options(synchronize_session=False)
    )
    affected = int(result.rowcount or 0)
    if affected != len(candidate_ids):                          # 8
        raise ExecutionError("affected_row_count_mismatch")

    after_plan = await R.build_plan(session)                    # 9
    after = R.summarise(after_plan)
    a_owners, a_rows = await R.orphan_counts(session)
    after["orphan_owner_count"] = a_owners
    after["orphan_active_row_count"] = a_rows

    # (observed, required, comparison). Equality except where a value is
    # legitimately expected to shrink.
    eq = lambda got, want: got == want          # noqa: E731
    le = lambda got, want: got <= want          # noqa: E731

    postconditions = {
        "active_rows": (after["active_row_count_before"],
                        before["retained_active_rows"], eq),
        "membership_duplicate_groups": (after["membership_duplicate_groups"],
                                        0, eq),
        "membership_candidate_rows": (after["membership_candidate_rows"], 0, eq),
        "legacy_duplicate_groups": (after["legacy_duplicate_groups"], 0, eq),
        "legacy_candidate_rows": (after["legacy_candidate_rows"], 0, eq),
        "distinct_tickers": (after["distinct_ticker_count_before"],
                             before["projected_distinct_ticker_count_after"], eq),
        "active_owners": (after["active_owner_count_before"],
                          before["projected_active_owner_count_after"], eq),
        # Cleanup must never orphan an owner: every group retains one row, so
        # the set of owners holding active rows cannot shrink.
        "orphan_owners": (after["orphan_owner_count"],
                          before["orphan_owner_count"], eq),
        # orphan_active_row_count counts ACTIVE rows, so deactivating
        # duplicates legitimately reduces it. The invariant is that it may
        # never GROW: cleanup cannot manufacture a new unowned active row.
        "orphan_rows": (after["orphan_active_row_count"],
                        before["orphan_active_row_count"], le),
    }
    failed = sorted(k for k, (got, want, op) in postconditions.items()
                    if not op(got, want))
    if failed:
        raise ExecutionError("postcondition_failed")

    return {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "dry_run": False,
        "executed": True,
        "operation_ref": operation_ref,
        "lock_mode": lock_mode,
        "generated_at": _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active_row_count_before": before["active_row_count_before"],
        "candidate_rows": len(candidate_ids),
        "audit_rows_written": audited + 1,
        "affected_rows": affected,
        "active_row_count_after": after["active_row_count_before"],
        "distinct_ticker_count_after": after["distinct_ticker_count_before"],
        "active_owner_count_after": after["active_owner_count_before"],
        "membership_duplicate_groups_after": after["membership_duplicate_groups"],
        "membership_candidate_rows_after": after["membership_candidate_rows"],
        "legacy_duplicate_groups_after": after["legacy_duplicate_groups"],
        "legacy_candidate_rows_after": after["legacy_candidate_rows"],
        "orphan_owner_count_after": after["orphan_owner_count"],
        "orphan_active_row_count_after": after["orphan_active_row_count"],
        "postconditions_verified": True,
    }


async def run_owned(session_factory, expected, approved_fingerprint,
                    operation_ref) -> Dict[str, Any]:
    """Own the session and the transaction. Commit once, else roll back."""
    async with session_factory() as session:
        try:
            report = await execute_cleanup(session, expected,
                                           approved_fingerprint, operation_ref)
        except BaseException:
            await session.rollback()
            raise
        await session.commit()                                   # 10
        return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Execute an approved watchlist duplicate cleanup. "
                    "Requires --execute, all nine expectations and the "
                    "approved rehearsal fingerprint.")
    p.add_argument("--execute", action="store_true",
                   help="Required. Without it nothing runs.")
    p.add_argument("--approved-fingerprint", default=None,
                   help="The 64-character fingerprint from the approved "
                        "rehearsal. Never hard-coded.")
    for field in EXPECTATION_FIELDS:
        p.add_argument("--expect-" + field.replace("_", "-"),
                       dest="expect_" + field, type=int, default=None)
    return p


def _emit(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    base = {"tool": TOOL_NAME, "tool_version": TOOL_VERSION,
            "executed": False, "operation_ref": None}

    if not args.execute:
        _emit(dict(base, error="execute_flag_required")); return 3

    fp = (args.approved_fingerprint or "").strip()
    if len(fp) != FINGERPRINT_LENGTH or not all(
            c in "0123456789abcdef" for c in fp.lower()):
        _emit(dict(base, error="approved_fingerprint_required")); return 3

    expected = {f: getattr(args, "expect_" + f) for f in EXPECTATION_FIELDS}
    missing = sorted(f for f, v in expected.items() if v is None)
    if missing:
        _emit(dict(base, error="expectations_required",
                   missing_expectations=missing)); return 3

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        _emit(dict(base, error="database_url_not_set")); return 4

    operation_ref = uuid.uuid4().hex

    async def _run():
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        engine = create_async_engine(url, future=True)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            return await run_owned(maker, expected, fp.lower(), operation_ref)
        finally:
            await engine.dispose()

    try:
        prev = asyncio.get_event_loop()
    except RuntimeError:
        prev = None
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        report = loop.run_until_complete(_run())
    except VerificationError as exc:
        _emit(dict(base, error="verification_failed",
                   error_type=_sanitise(exc), reason=str(exc)))
        return 2
    except BaseException as exc:  # noqa: BLE001 — sanitised on purpose
        _emit(dict(base, error="execution_failed", error_type=_sanitise(exc)))
        return 4
    finally:
        loop.close()
        asyncio.set_event_loop(prev)

    _emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
