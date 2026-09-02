#!/usr/bin/env python3
"""Watchlist duplicate cleanup REHEARSAL — Section 0.8C. DRY RUN ONLY.

This tool analyses duplicate active watchlist memberships and reports what a
future cleanup *would* do. It is structurally incapable of changing anything:

  * there is no --execute / --apply / --cleanup flag, and none may be added
    here (the executor is a separate, separately approved artifact);
  * the module contains no INSERT, UPDATE, DELETE, deactivate, commit, add or
    audit-write path — only SELECT;
  * on PostgreSQL it opens an explicitly READ ONLY transaction.

Output is deterministic, aggregate-only JSON. Owner ids, emails, ticker
membership lists, retained row ids and candidate row ids are computed in
memory to build the fingerprint and are never printed, logged or returned.

Selection rules (shared implementation, reused later by the executor)
---------------------------------------------------------------------
Active rows only. Inactive rows are excluded entirely and never interact with
active ones — soft-deleted history is preserved untouched.

  owned  namespace (user_id IS NOT NULL):
      ROW_NUMBER() OVER (PARTITION BY user_id, ticker
                         ORDER BY added_at ASC, id ASC)
  legacy namespace (user_id IS NULL):
      ROW_NUMBER() OVER (PARTITION BY ticker
                         ORDER BY added_at ASC, id ASC)

  rn = 1  -> RETAINED     rn > 1 -> CLEANUP CANDIDATE

The ordering mirrors ``watchlist_repo._membership_stmt`` exactly
(``added_at ASC, id ASC``), so the row this tool retains is the row the running
application already treats as authoritative via ``_resolve_one``.

``watched_tickers.added_at`` and ``id`` are both NOT NULL in the schema, so
there is no NULLS FIRST/LAST ambiguity and no dialect-dependent null ordering.
``id`` is a VARCHAR(36) uuid hex, compared lexicographically, which makes the
tie-break total and deterministic even when bulk-created rows share a
timestamp.

The same ticker under two different non-null owners is NEVER a duplicate: the
partition key includes the owner. No owner is assumed or hard-coded; the
system account is treated as an ordinary non-null owner.

Exit codes
----------
    0  analysis completed and every expectation matched
    2  expectation mismatch (no authorizable plan produced)
    3  usage / guard error (e.g. expectations omitted in production)
    4  database unavailable or analysis failed
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Operator CLI: running `python3 scripts/<this>.py` puts scripts/ on sys.path,
# not the repository root, so `app` would not import. Add the root explicitly.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

TOOL_NAME = "watchlist_duplicate_cleanup_rehearsal"
TOOL_VERSION = "0.8c.1"

NS_OWNED = "owned"
NS_LEGACY = "legacy"
ROLE_RETAIN = "retain"
ROLE_CANDIDATE = "candidate"

EXPECTATION_FIELDS = (
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


# ---------------------------------------------------------------------------
# Internal plan (never printed)
# ---------------------------------------------------------------------------

class PlanRow:
    """One active row and the decision made about it. Never serialised out."""

    __slots__ = ("namespace", "owner_key", "ticker", "rn", "row_id", "added_at")

    def __init__(self, namespace, owner_key, ticker, rn, row_id, added_at):
        self.namespace = namespace
        self.owner_key = owner_key
        self.ticker = ticker
        self.rn = int(rn)
        self.row_id = row_id
        self.added_at = added_at

    @property
    def role(self) -> str:
        return ROLE_RETAIN if self.rn == 1 else ROLE_CANDIDATE

    def canonical(self) -> str:
        """Deterministic line contributing to the fingerprint.

        Includes namespace, owner, ticker, rank, decision, row identity and
        the ordering key. A change to ANY of: the candidate set, the retained
        set, the ownership namespace, the ticker grouping, or the ordering
        decision, changes this line and therefore the fingerprint.
        """
        ts = self.added_at.isoformat() if hasattr(self.added_at, "isoformat") \
            else str(self.added_at)
        return "|".join((
            self.namespace, self.owner_key, self.ticker,
            str(self.rn), self.role, str(self.row_id), ts,
        ))


def plan_fingerprint(plan: List[PlanRow]) -> str:
    """SHA-256 over the deterministically ordered plan.

    Sorted in Python so the digest cannot depend on database return order.
    The executor MUST recompute this and require an exact match immediately
    before it mutates anything; a mismatch means the underlying rows moved
    since the rehearsal and the approved plan is void.
    """
    lines = sorted(row.canonical() for row in plan)
    digest = hashlib.sha256()
    digest.update(("%s\n%s\n" % (TOOL_NAME, TOOL_VERSION)).encode())
    for line in lines:
        digest.update(line.encode())
        digest.update(b"\n")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Selection — the single shared implementation
# ---------------------------------------------------------------------------

def _ranked_statement(namespace: str):
    """SELECT of active rows with their partition rank. SELECT only."""
    from sqlalchemy import select, func
    from app.db.models import WatchedTicker as W

    if namespace == NS_OWNED:
        partition = (W.user_id, W.ticker)
        owner_filter = W.user_id.isnot(None)
    else:
        partition = (W.ticker,)
        owner_filter = W.user_id.is_(None)

    rn = (
        func.row_number()
        .over(partition_by=list(partition),
              order_by=(W.added_at.asc(), W.id.asc()))
        .label("rn")
    )
    return (
        select(W.id, W.user_id, W.ticker, W.added_at, rn)
        .where(W.active.is_(True))
        .where(owner_filter)
    )


async def build_plan(session) -> List[PlanRow]:
    """Return the full internal plan for both namespaces. Read-only."""
    plan: List[PlanRow] = []
    for namespace in (NS_OWNED, NS_LEGACY):
        result = await session.execute(_ranked_statement(namespace))
        for row_id, user_id, ticker, added_at, rn in result.all():
            plan.append(PlanRow(
                namespace=namespace,
                owner_key=(user_id if namespace == NS_OWNED else ""),
                ticker=ticker,
                rn=rn,
                row_id=row_id,
                added_at=added_at,
            ))
    return plan


# ---------------------------------------------------------------------------
# Aggregation — the only thing allowed to leave the tool
# ---------------------------------------------------------------------------

def summarise(plan: List[PlanRow]) -> Dict[str, Any]:
    owned = [r for r in plan if r.namespace == NS_OWNED]
    legacy = [r for r in plan if r.namespace == NS_LEGACY]

    def dup_groups(rows, key) -> Tuple[int, int, set]:
        sizes: Dict[Any, int] = {}
        for r in rows:
            sizes[key(r)] = sizes.get(key(r), 0) + 1
        dup = {k: n for k, n in sizes.items() if n > 1}
        return len(dup), sum(n - 1 for n in dup.values()), set(dup)

    mem_groups, mem_candidates, mem_dup_keys = dup_groups(
        owned, lambda r: (r.owner_key, r.ticker))
    leg_groups, leg_candidates, _ = dup_groups(legacy, lambda r: r.ticker)

    active_before = len(plan)
    retained = sum(1 for r in plan if r.rn == 1)
    total_candidates = active_before - retained

    distinct_before = len({r.ticker for r in plan})
    owners_before = len({r.owner_key for r in owned})
    retained_rows = [r for r in plan if r.rn == 1]

    return {
        "active_row_count_before": active_before,
        "distinct_ticker_count_before": distinct_before,
        "active_owner_count_before": owners_before,
        "membership_duplicate_groups": mem_groups,
        "membership_candidate_rows": mem_candidates,
        "membership_duplicate_owner_count": len({k[0] for k in mem_dup_keys}),
        "legacy_duplicate_groups": leg_groups,
        "legacy_candidate_rows": leg_candidates,
        "total_candidate_rows": total_candidates,
        "retained_active_rows": retained,
        "projected_active_row_count_after": retained,
        "projected_distinct_ticker_count_after":
            len({r.ticker for r in retained_rows}),
        "projected_active_owner_count_after":
            len({r.owner_key for r in retained_rows
                 if r.namespace == NS_OWNED}),
    }


async def orphan_counts(session) -> Tuple[int, int]:
    """Active non-null owners with no users row. Unenforced: there is no FK."""
    from sqlalchemy import select, func
    from app.db.models import WatchedTicker as W, User

    row = (await session.execute(
        select(func.count(func.distinct(W.user_id)), func.count())
        .select_from(W.__table__.outerjoin(User.__table__, User.id == W.user_id))
        .where(W.active.is_(True))
        .where(W.user_id.isnot(None))
        .where(User.id.is_(None))
    )).one()
    return int(row[0] or 0), int(row[1] or 0)


# ---------------------------------------------------------------------------
# Expectations
# ---------------------------------------------------------------------------

def compare_expectations(report: Dict[str, Any],
                         expected: Dict[str, Optional[int]]) -> Dict[str, Any]:
    """Aggregate-only expected/actual/delta comparison."""
    observed = {
        "active_rows": report["active_row_count_before"],
        "distinct_tickers": report["distinct_ticker_count_before"],
        "active_owners": report["active_owner_count_before"],
        "membership_duplicate_groups": report["membership_duplicate_groups"],
        "membership_candidate_rows": report["membership_candidate_rows"],
        "legacy_duplicate_groups": report["legacy_duplicate_groups"],
        "legacy_candidate_rows": report["legacy_candidate_rows"],
        "orphan_owners": report["orphan_owner_count"],
        "orphan_rows": report["orphan_active_row_count"],
    }
    checks = {}
    matched = True
    for field in EXPECTATION_FIELDS:
        want = expected.get(field)
        got = observed[field]
        if want is None:
            checks[field] = {"expected": None, "actual": got, "delta": None}
            continue
        checks[field] = {"expected": want, "actual": got, "delta": got - want}
        if got != want:
            matched = False
    return {"expectation_checks": checks, "expectation_match": matched}


# ---------------------------------------------------------------------------
# Session / runner
# ---------------------------------------------------------------------------

async def _set_read_only(session) -> str:
    """Open an explicitly READ ONLY transaction where the dialect supports it."""
    from sqlalchemy import text
    try:
        dialect = session.bind.dialect.name  # type: ignore[union-attr]
    except Exception:
        return "unknown"
    if dialect == "postgresql":
        await session.execute(text("SET TRANSACTION READ ONLY"))
        return "postgresql:read_only"
    return "%s:not_supported" % dialect


async def _release_transaction(session) -> None:
    """Roll back the CLI-owned transaction. Never commits; never mutates.

    ROLLBACK is transaction cleanup, not a write: it discards the read
    snapshot this tool opened. It runs BEFORE the session context manager
    closes the session, so no transaction is left dangling for the pool to
    reclaim implicitly.

    Deliberately NOT wrapped in a blanket ``except``. This is a safety
    control, and a control that reports success when it failed is worse than
    no control at all. ``AsyncSession.rollback()`` is a no-op when no
    transaction is active, so suppression buys nothing and would only hide a
    genuine failure to release the read snapshot.

    A real failure therefore propagates: the CLI exits non-zero with a
    sanitised error, and no plan fingerprint or success result is emitted.
    The owned session is still closed, because this runs inside the session
    context manager's body.
    """
    await session.rollback()


async def analyse_with_owned_session(session_factory,
                                     expected: Dict[str, Optional[int]]
                                     ) -> Dict[str, Any]:
    """Analyse using a session this tool CREATES AND OWNS.

    The rollback belongs here, not in ``analyse``: ``analyse`` accepts a
    caller-owned session and must not impose lifecycle side effects on it.
    Ordering is deliberate — roll back inside the ``async with`` body so the
    release happens strictly before the context manager closes the session.

    Deliberately NOT ``session.begin()``: that context manager COMMITS on
    successful exit, which is exactly what a dry-run tool must never do.
    """
    async with session_factory() as session:
        try:
            return await analyse(session, expected)
        finally:
            await _release_transaction(session)


async def analyse(session, expected: Dict[str, Optional[int]]) -> Dict[str, Any]:
    """Read-only analysis against a CALLER-OWNED session.

    This function opens no transaction of its own beyond the implicit read
    transaction, and deliberately does NOT roll back or close: the caller owns
    that session and is responsible for its lifecycle. The CLI wraps this in
    ``analyse_with_owned_session``, which does release what it owns.
    """
    tx_mode = await _set_read_only(session)
    plan = await build_plan(session)
    report = summarise(plan)
    orphan_owners, orphan_rows = await orphan_counts(session)
    report["orphan_owner_count"] = orphan_owners
    report["orphan_active_row_count"] = orphan_rows
    report.update(compare_expectations(report, expected))
    report["transaction_mode"] = tx_mode
    report["generated_at"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    report["tool"] = TOOL_NAME
    report["tool_version"] = TOOL_VERSION
    report["dry_run"] = True
    # The fingerprint authorises a future executor. Withhold it when the
    # observed state does not match what was approved.
    report["plan_fingerprint"] = (
        plan_fingerprint(plan) if report["expectation_match"] else None
    )
    return report


def _sanitise(exc: BaseException) -> str:
    """Error class only. SQL text, bound parameters and URLs never escape."""
    return type(exc).__name__


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Dry-run rehearsal for watchlist duplicate cleanup. "
                    "Performs no writes and has no execute mode.")
    for field in EXPECTATION_FIELDS:
        p.add_argument("--expect-" + field.replace("_", "-"),
                       dest="expect_" + field, type=int, default=None)
    p.add_argument(
        "--no-expectations", action="store_true",
        help="Permit a run without expectation guards. Refused when the "
             "environment reports production.")
    p.add_argument("--database-url", default=None,
                   help="Override the database URL (never echoed).")
    return p


def _is_production() -> bool:
    """Canonical production signal. Never inferred from printed output."""
    try:
        from app.config import settings
        return bool(settings.is_production)
    except Exception:
        return bool(os.environ.get("RENDER_SERVICE_ID"))


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    expected = {f: getattr(args, "expect_" + f) for f in EXPECTATION_FIELDS}
    missing = [f for f, v in expected.items() if v is None]

    if missing and not args.no_expectations:
        print(json.dumps({
            "tool": TOOL_NAME, "tool_version": TOOL_VERSION, "dry_run": True,
            "error": "expectations_required",
            "missing_expectations": sorted(missing),
            "expectation_match": False, "plan_fingerprint": None,
        }, indent=2, sort_keys=True))
        return 3
    if missing and args.no_expectations and _is_production():
        print(json.dumps({
            "tool": TOOL_NAME, "tool_version": TOOL_VERSION, "dry_run": True,
            "error": "expectations_required_in_production",
            "expectation_match": False, "plan_fingerprint": None,
        }, indent=2, sort_keys=True))
        return 3

    url = args.database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        print(json.dumps({
            "tool": TOOL_NAME, "tool_version": TOOL_VERSION, "dry_run": True,
            "error": "database_url_not_set",
            "expectation_match": False, "plan_fingerprint": None,
        }, indent=2, sort_keys=True))
        return 4

    async def _run() -> Dict[str, Any]:
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        engine = create_async_engine(url, future=True)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            return await analyse_with_owned_session(maker, expected)
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
    except BaseException as exc:  # noqa: BLE001 — sanitised on purpose
        print(json.dumps({
            "tool": TOOL_NAME, "tool_version": TOOL_VERSION, "dry_run": True,
            "error": "analysis_failed", "error_type": _sanitise(exc),
            "expectation_match": False, "plan_fingerprint": None,
        }, indent=2, sort_keys=True))
        return 4
    finally:
        loop.close()
        asyncio.set_event_loop(prev)

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["expectation_match"] else 2


if __name__ == "__main__":
    sys.exit(main())
