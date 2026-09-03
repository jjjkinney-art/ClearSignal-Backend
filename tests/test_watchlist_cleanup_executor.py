"""Section 0.8D — fail-closed safety tests for the cleanup EXECUTOR.

The executor mutates, so every control that stands between "approved plan" and
"rows changed" is tested here, including the ordering of those controls.

All fixtures are synthetic. No production value, fingerprint or identity
appears in this file.

Python 3.9 compatible.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

OWNER_1 = "11111111-1111-1111-1111-111111111111"
OWNER_2 = "22222222-2222-2222-2222-222222222222"
OWNER_3 = "33333333-3333-3333-3333-333333333333"

_EXEC_PATH = Path(__file__).resolve().parents[1] / "scripts" / \
    "watchlist_duplicate_cleanup_execute.py"


def _load():
    spec = importlib.util.spec_from_file_location("_wl_exec", _EXEC_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


X = _load()
R = X.R                      # the Section 0.8C module, reused not reimplemented
BASE_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _run(body):
    async def _outer():
        from sqlalchemy.ext.asyncio import (
            create_async_engine, async_sessionmaker)
        from app.db.models import Base
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            await body(maker)
        finally:
            await engine.dispose()

    try:
        prev = asyncio.get_event_loop()
    except RuntimeError:
        prev = None
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_outer())
    finally:
        loop.close()
        asyncio.set_event_loop(prev)


async def _seed(maker, rows):
    """rows: list of (owner, ticker, minutes, active)."""
    from app.db.models import WatchedTicker
    async with maker() as db:
        for owner, ticker, minutes, active in rows:
            db.add(WatchedTicker(
                id=uuid.uuid4().hex, user_id=owner, ticker=ticker,
                company_name=ticker, active=active,
                added_at=BASE_TS + timedelta(minutes=minutes)))
        await db.commit()


async def _counts(maker):
    from sqlalchemy import select, func
    from app.db.models import WatchedTicker, AuditLog
    async with maker() as db:
        active = (await db.execute(
            select(func.count()).select_from(WatchedTicker)
            .where(WatchedTicker.active.is_(True)))).scalar()
        total = (await db.execute(
            select(func.count()).select_from(WatchedTicker))).scalar()
        audit = (await db.execute(
            select(func.count()).select_from(AuditLog))).scalar()
        return {"active": active, "total": total, "audit": audit}


async def _expectations(maker):
    """Derive the nine expectations from the current synthetic database."""
    async with maker() as db:
        plan = await R.build_plan(db)
        rep = R.summarise(plan)
        o, r = await R.orphan_counts(db)
        return {
            "active_rows": rep["active_row_count_before"],
            "distinct_tickers": rep["distinct_ticker_count_before"],
            "active_owners": rep["active_owner_count_before"],
            "membership_duplicate_groups": rep["membership_duplicate_groups"],
            "membership_candidate_rows": rep["membership_candidate_rows"],
            "legacy_duplicate_groups": rep["legacy_duplicate_groups"],
            "legacy_candidate_rows": rep["legacy_candidate_rows"],
            "orphan_owners": o,
            "orphan_rows": r,
        }, R.plan_fingerprint(plan)



class _PgProxy:
    """SQLite fixture presented as PostgreSQL, intercepting LOCK TABLE.

    Tests exercise the REAL dialect guard rather than bypassing it: the guard
    still runs, still demands postgresql, and still issues LOCK TABLE — only
    the statement itself is swallowed, because SQLite cannot execute it.
    """

    def __init__(self, inner, dialect="postgresql", lock_fails=False):
        self._inner = inner
        self.calls = []
        self.bind = self
        self.dialect = self
        self.name = dialect
        self._lock_fails = lock_fails

    async def execute(self, statement, *a, **k):
        text = " ".join(str(statement).split()).upper()
        if "LOCK TABLE" in text:
            self.calls.append("LOCK")
            if self._lock_fails:
                raise RuntimeError("could not obtain lock on watched_tickers")
            return _Empty()
        if text.startswith("UPDATE"):
            self.calls.append("UPDATE")
        elif text.startswith("SELECT"):
            self.calls.append("SELECT")
        return await self._inner.execute(statement, *a, **k)

    def add(self, obj):
        self.calls.append("AUDIT_ADD")
        return self._inner.add(obj)

    async def flush(self, *a, **k):
        return await self._inner.flush(*a, **k)

    async def commit(self):
        self.calls.append("COMMIT")
        return await self._inner.commit()

    async def rollback(self):
        self.calls.append("ROLLBACK")
        return await self._inner.rollback()


class _PgFactory:
    """async_sessionmaker() that yields a PostgreSQL-presenting session."""

    def __init__(self, maker, dialect="postgresql", lock_fails=False):
        self._maker = maker
        self._dialect = dialect
        self._lock_fails = lock_fails
        self.proxy = None
        self._cm = None

    def __call__(self):
        return self

    async def __aenter__(self):
        self._cm = self._maker()
        inner = await self._cm.__aenter__()
        self.proxy = _PgProxy(inner, self._dialect, self._lock_fails)
        return self.proxy

    async def __aexit__(self, *exc):
        return await self._cm.__aexit__(*exc)


def _pg(maker, dialect="postgresql", lock_fails=False):
    return _PgFactory(maker, dialect, lock_fails)


# ===========================================================================
# § VERIFICATION HAPPENS BEFORE ANY WRITE
# ===========================================================================

def test_fingerprint_mismatch_writes_nothing():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        before = await _counts(maker)
        exp, _fp = await _expectations(maker)
        with pytest.raises(X.VerificationError) as ei:
            await X.run_owned(_pg(maker), exp, "f" * 64, uuid.uuid4().hex)
        assert "fingerprint_mismatch" in str(ei.value)
        assert await _counts(maker) == before, "no row or audit row may change"

    _run(body)


def test_expectation_mismatch_writes_nothing():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        before = await _counts(maker)
        exp, fp = await _expectations(maker)
        exp["membership_candidate_rows"] = 999
        with pytest.raises(X.VerificationError) as ei:
            await X.run_owned(_pg(maker), exp, fp, uuid.uuid4().hex)
        assert "expectation_mismatch" in str(ei.value)
        assert await _counts(maker) == before

    _run(body)


def test_expectation_is_checked_before_the_fingerprint():
    """Both wrong: the cheaper aggregate check must report first."""
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(3)])
        exp, _ = await _expectations(maker)
        exp["active_rows"] = 1234
        with pytest.raises(X.VerificationError) as ei:
            await X.run_owned(_pg(maker), exp, "a" * 64, uuid.uuid4().hex)
        assert "expectation_mismatch" in str(ei.value)

    _run(body)


def test_candidate_set_change_after_approval_is_rejected():
    """A row added after the rehearsal invalidates the approved fingerprint."""
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(3)])
        exp, approved = await _expectations(maker)
        # Someone adds a watchlist row between approval and execution.
        await _seed(maker, [(OWNER_2, "BBB", 0, True)])
        before = await _counts(maker)
        with pytest.raises(X.VerificationError):
            await X.run_owned(_pg(maker), exp, approved, uuid.uuid4().hex)
        assert await _counts(maker) == before

    _run(body)


# ===========================================================================
# § LOCK ORDERING
# ===========================================================================

class _OrderRecorder:
    """Records the order of lock / select / update / audit operations."""

    def __init__(self, inner, dialect="postgresql"):
        self._inner = inner
        self.calls = []
        self.bind = self
        self.dialect = self
        self.name = dialect

    async def execute(self, statement, *a, **k):
        text = " ".join(str(statement).split()).upper()
        if "LOCK TABLE" in text:
            self.calls.append("LOCK")
            return _Empty()
        if text.startswith("UPDATE"):
            self.calls.append("UPDATE")
        elif text.startswith("SELECT"):
            self.calls.append("SELECT")
        return await self._inner.execute(statement, *a, **k)

    def add(self, obj):
        self.calls.append("AUDIT_ADD")
        return self._inner.add(obj)

    async def flush(self, *a, **k):
        return await self._inner.flush(*a, **k)

    async def commit(self):
        self.calls.append("COMMIT")
        return await self._inner.commit()

    async def rollback(self):
        self.calls.append("ROLLBACK")
        return await self._inner.rollback()


class _Empty:
    rowcount = 0

    def all(self):
        return []

    def one(self):
        return (0, 0)


def test_lock_is_acquired_before_any_plan_selection():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(3)])
        exp, fp = await _expectations(maker)
        async with maker() as inner:
            rec = _OrderRecorder(inner)
            await X.execute_cleanup(rec, exp, fp, uuid.uuid4().hex)
            await inner.rollback()
        assert rec.calls[0] == "LOCK", (
            "the table lock must precede every query; got %r" % (rec.calls[:4],)
        )
        assert "SELECT" in rec.calls
        assert rec.calls.index("LOCK") < rec.calls.index("SELECT")
        assert rec.calls.index("LOCK") < rec.calls.index("UPDATE")

    _run(body)


def test_audit_is_written_before_the_update():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(3)])
        exp, fp = await _expectations(maker)
        async with maker() as inner:
            rec = _OrderRecorder(inner)
            await X.execute_cleanup(rec, exp, fp, uuid.uuid4().hex)
            await inner.rollback()
        assert rec.calls.index("AUDIT_ADD") < rec.calls.index("UPDATE"), (
            "the rollback record must exist before rows change"
        )

    _run(body)


def test_sqlite_execution_is_refused_before_selection_or_mutation():
    """A mutating executor may NOT proceed without the table lock."""
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        before = await _counts(maker)
        exp, fp = await _expectations(maker)
        with pytest.raises(X.UnsupportedDialectError) as ei:
            await X.run_owned(maker, exp, fp, uuid.uuid4().hex)   # raw sqlite
        assert "unsupported_dialect" in str(ei.value)
        assert await _counts(maker) == before, (
            "a refused dialect must leave the database untouched"
        )

    _run(body)


@pytest.mark.parametrize("dialect", ["sqlite", "mysql", "oracle", "mssql", ""])
def test_non_postgresql_dialects_are_refused(dialect):
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(3)])
        before = await _counts(maker)
        exp, fp = await _expectations(maker)
        factory = _pg(maker, dialect=dialect)
        with pytest.raises(X.UnsupportedDialectError):
            await X.run_owned(factory, exp, fp, uuid.uuid4().hex)
        # A defensive rollback on the refused session is correct and expected;
        # nothing else may have happened.
        assert set(factory.proxy.calls) <= {"ROLLBACK"}, (
            "no lock, query, audit row or DML may run on a refused dialect; "
            "got %r" % (factory.proxy.calls,)
        )
        assert await _counts(maker) == before

    _run(body)


def test_dialect_detection_failure_is_refused():
    class _NoDialect:
        bind = None

    async def body(maker):
        with pytest.raises(X.UnsupportedDialectError) as ei:
            await X.acquire_table_lock(_NoDialect())
        assert "dialect_detection_failed" in str(ei.value)

    _run(body)


def test_postgresql_proceeds_only_after_the_lock_is_taken():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(3)])
        exp, fp = await _expectations(maker)
        factory = _pg(maker)
        report = await X.run_owned(factory, exp, fp, uuid.uuid4().hex)
        calls = factory.proxy.calls
        assert calls[0] == "LOCK", "nothing may precede the lock: %r" % (calls[:3],)
        assert report["lock_mode"] == "postgresql:share_row_exclusive"
        assert calls.index("LOCK") < calls.index("SELECT")
        assert calls.index("LOCK") < calls.index("UPDATE")

    _run(body)


def test_lock_acquisition_failure_writes_nothing_and_never_commits():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        before = await _counts(maker)
        exp, fp = await _expectations(maker)
        factory = _pg(maker, lock_fails=True)
        with pytest.raises(RuntimeError):
            await X.run_owned(factory, exp, fp, uuid.uuid4().hex)
        calls = factory.proxy.calls
        assert "SELECT" not in calls, "no plan selection after a failed lock"
        assert "AUDIT_ADD" not in calls, "no audit rows after a failed lock"
        assert "UPDATE" not in calls, "no DML after a failed lock"
        assert "COMMIT" not in calls, "must never commit"
        assert "ROLLBACK" in calls
        assert await _counts(maker) == before

    _run(body)


def test_cli_refuses_a_non_postgresql_database(monkeypatch, tmp_path):
    """The CLI boundary must reject SQLite even though fixtures use it."""
    db = tmp_path / "x.sqlite"
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///%s" % db)
    rc, out = _cli(["--execute", "--approved-fingerprint", "a" * 64]
                   + [arg for f in X.EXPECTATION_FIELDS
                      for arg in ("--expect-" + f.replace("_", "-"), "0")])
    payload = json.loads(out)
    assert rc == 4
    assert payload["error"] == "unsupported_database"
    assert payload["error_type"] == "UnsupportedDialectError"
    assert payload["executed"] is False


# ===========================================================================
# § PARTITIONING AND SELECTION (delegated to 0.8C, asserted end to end)
# ===========================================================================

def test_owned_and_legacy_partitions_are_cleaned_independently():
    async def body(maker):
        await _seed(maker, [
            (OWNER_1, "AAA", 0, True), (OWNER_1, "AAA", 1, True),   # 1 cand
            (OWNER_2, "AAA", 0, True),                              # clean
            (None, "BBB", 0, True), (None, "BBB", 1, True),         # legacy 1
        ])
        exp, fp = await _expectations(maker)
        assert exp["membership_candidate_rows"] == 1
        assert exp["legacy_candidate_rows"] == 1
        report = await X.run_owned(_pg(maker), exp, fp, uuid.uuid4().hex)
        assert report["affected_rows"] == 2
        assert report["active_row_count_after"] == 3
        assert report["membership_duplicate_groups_after"] == 0
        assert report["legacy_duplicate_groups_after"] == 0

    _run(body)


def test_same_ticker_under_different_owners_survives():
    async def body(maker):
        await _seed(maker, [
            (OWNER_1, "AAA", 0, True),
            (OWNER_2, "AAA", 0, True),
            (OWNER_3, "AAA", 0, True),
        ])
        exp, fp = await _expectations(maker)
        assert exp["membership_candidate_rows"] == 0
        report = await X.run_owned(_pg(maker), exp, fp, uuid.uuid4().hex)
        assert report["affected_rows"] == 0
        assert report["active_row_count_after"] == 3
        assert report["active_owner_count_after"] == 3

    _run(body)


def test_inactive_history_is_untouched():
    async def body(maker):
        from sqlalchemy import select
        from app.db.models import WatchedTicker
        await _seed(maker, [
            (OWNER_1, "AAA", 0, True), (OWNER_1, "AAA", 1, True),
            (OWNER_1, "AAA", 2, False), (OWNER_1, "AAA", 3, False),
        ])
        exp, fp = await _expectations(maker)
        await X.run_owned(_pg(maker), exp, fp, uuid.uuid4().hex)
        async with maker() as db:
            rows = (await db.execute(select(WatchedTicker))).scalars().all()
        assert len(rows) == 4, "no row may be deleted"
        assert sum(1 for r in rows if r.active) == 1
        assert sum(1 for r in rows if not r.active) == 3

    _run(body)


def test_exact_affected_row_accounting_at_scale():
    """Production-shaped: 24 groups, 1031 candidates, 124 retained."""
    async def body(maker):
        rows = []
        for n in range(24):                       # 23 x 44 + 1 x 43 = 1055
            for k in range(44 if n < 23 else 43):
                rows.append((OWNER_1, "T%02d" % n, k, True))
        for owner in (OWNER_2, OWNER_3, "44444444-4444-4444-4444-444444444444",
                      "55555555-5555-5555-5555-555555555555"):
            for n in range(24):
                rows.append((owner, "T%02d" % n, 0, True))
            rows.append((owner, "T99", 0, True))
        await _seed(maker, rows)

        exp, fp = await _expectations(maker)
        assert exp["active_rows"] == 1155
        assert exp["membership_duplicate_groups"] == 24
        assert exp["membership_candidate_rows"] == 1031

        report = await X.run_owned(_pg(maker), exp, fp, uuid.uuid4().hex)
        assert report["candidate_rows"] == 1031
        assert report["affected_rows"] == 1031
        assert report["active_row_count_after"] == 124
        assert report["distinct_ticker_count_after"] == 25
        assert report["active_owner_count_after"] == 5
        assert report["membership_candidate_rows_after"] == 0
        assert (await _counts(maker))["total"] == 1155, "nothing deleted"

    _run(body)


# ===========================================================================
# § FAILURE ROLLS EVERYTHING BACK
# ===========================================================================

def test_audit_failure_rolls_everything_back():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        before = await _counts(maker)
        exp, fp = await _expectations(maker)

        async def _boom(session, operation_ref, plan):
            raise RuntimeError("audit table unavailable")

        original = X.write_audit
        X.write_audit = _boom
        try:
            with pytest.raises(RuntimeError):
                await X.run_owned(_pg(maker), exp, fp, uuid.uuid4().hex)
        finally:
            X.write_audit = original
        assert await _counts(maker) == before, (
            "a failed audit write must leave no deactivated rows"
        )

    _run(body)


def test_affected_row_count_mismatch_rolls_everything_back():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        before = await _counts(maker)
        exp, fp = await _expectations(maker)

        class _ShortUpdate:
            """Reports fewer affected rows than candidates — a partial write."""
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            async def execute(self, statement, *a, **k):
                res = await self._inner.execute(statement, *a, **k)
                if " ".join(str(statement).split()).upper().startswith("UPDATE"):
                    class _R:
                        rowcount = 1
                    return _R()
                return res

        async with maker() as inner:
            wrapped = _ShortUpdate(_PgProxy(inner))
            with pytest.raises(X.ExecutionError) as ei:
                await X.execute_cleanup(wrapped, exp, fp, uuid.uuid4().hex)
            await inner.rollback()
        assert "affected_row_count_mismatch" in str(ei.value)
        assert await _counts(maker) == before

    _run(body)


def test_failed_postcondition_rolls_everything_back(monkeypatch):
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        before = await _counts(maker)
        exp, fp = await _expectations(maker)

        real_summarise = R.summarise
        state = {"calls": 0}

        def _poisoned(plan):
            state["calls"] += 1
            out = real_summarise(plan)
            if state["calls"] > 1:           # corrupt the AFTER snapshot only
                out["membership_candidate_rows"] = 7
            return out

        monkeypatch.setattr(R, "summarise", _poisoned)
        with pytest.raises(X.ExecutionError) as ei:
            await X.run_owned(_pg(maker), exp, fp, uuid.uuid4().hex)
        assert "postcondition_failed" in str(ei.value)
        assert await _counts(maker) == before

    _run(body)


# ===========================================================================
# § SUCCESS COMMITS ONCE; REPLAY FAILS CLOSED
# ===========================================================================

def test_success_commits_once_and_records_the_operation():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        exp, fp = await _expectations(maker)
        op = uuid.uuid4().hex
        report = await X.run_owned(_pg(maker), exp, fp, op)
        assert report["executed"] is True
        assert report["dry_run"] is False
        assert report["affected_rows"] == 3
        assert report["operation_ref"] == op
        assert report["postconditions_verified"] is True
        counts = await _counts(maker)
        assert counts["active"] == 1
        assert counts["total"] == 4, "nothing deleted"
        assert counts["audit"] == 4, "3 row records + 1 run marker"

    _run(body)


def test_second_execution_with_the_old_fingerprint_fails_closed():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        exp, fp = await _expectations(maker)
        await X.run_owned(_pg(maker), exp, fp, uuid.uuid4().hex)
        after_first = await _counts(maker)

        with pytest.raises(X.VerificationError):
            await X.run_owned(_pg(maker), exp, fp, uuid.uuid4().hex)
        assert await _counts(maker) == after_first, (
            "a replayed approval must change nothing"
        )

    _run(body)


# ===========================================================================
# § ROLLBACK BOUNDARY
# ===========================================================================

def test_operation_ref_alone_recovers_exactly_the_deactivated_rows():
    async def body(maker):
        from sqlalchemy import select
        from app.db.models import WatchedTicker
        await _seed(maker, [
            (OWNER_1, "AAA", 0, True), (OWNER_1, "AAA", 1, True),
            (OWNER_1, "AAA", 2, True), (OWNER_2, "BBB", 0, True),
            (OWNER_1, "CCC", 0, False),          # pre-existing history
        ])
        exp, fp = await _expectations(maker)
        op = uuid.uuid4().hex
        await X.run_owned(_pg(maker), exp, fp, op)

        async with maker() as db:
            recovered = await X.audited_row_ids(db, op)
            deactivated = [r.id for r in (await db.execute(
                select(WatchedTicker)
                .where(WatchedTicker.active.is_(False)))).scalars().all()]
        assert len(recovered) == 2
        # The pre-existing inactive row must NOT be attributed to this run.
        assert set(recovered) < set(deactivated)
        assert len(set(deactivated) - set(recovered)) == 1

    _run(body)


def test_rollback_reactivates_exactly_this_operations_rows():
    async def body(maker):
        from sqlalchemy import select, update
        from app.db.models import WatchedTicker
        await _seed(maker, [
            (OWNER_1, "AAA", 0, True), (OWNER_1, "AAA", 1, True),
            (OWNER_1, "AAA", 2, True), (OWNER_1, "CCC", 0, False),
        ])
        exp, fp = await _expectations(maker)
        op = uuid.uuid4().hex
        await X.run_owned(_pg(maker), exp, fp, op)
        assert (await _counts(maker))["active"] == 1

        # The rollback path, driven only by the opaque operation reference.
        async with maker() as db:
            ids = await X.audited_row_ids(db, op)
            await db.execute(
                update(WatchedTicker).where(WatchedTicker.id.in_(ids))
                .values(active=True).execution_options(
                    synchronize_session=False))
            await db.commit()

        counts = await _counts(maker)
        assert counts["active"] == 3, "exactly this run's rows come back"
        async with maker() as db:
            still_off = (await db.execute(
                select(WatchedTicker).where(WatchedTicker.active.is_(False))
            )).scalars().all()
        assert len(still_off) == 1, "unrelated history stays deactivated"

    _run(body)


def test_two_operations_do_not_share_a_rollback_scope():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(3)])
        exp, fp = await _expectations(maker)
        op1 = uuid.uuid4().hex
        await X.run_owned(_pg(maker), exp, fp, op1)

        await _seed(maker, [(OWNER_2, "BBB", i, True) for i in range(2)])
        exp2, fp2 = await _expectations(maker)
        op2 = uuid.uuid4().hex
        await X.run_owned(_pg(maker), exp2, fp2, op2)

        async with maker() as db:
            a = await X.audited_row_ids(db, op1)
            b = await X.audited_row_ids(db, op2)
        assert len(a) == 2 and len(b) == 1
        assert not (set(a) & set(b)), "operations must not overlap"

    _run(body)


# ===========================================================================
# § CLI GUARDS AND DISCLOSURE
# ===========================================================================

def _cli(argv):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = X.main(argv)
    return rc, buf.getvalue()


def test_execute_flag_is_required():
    rc, out = _cli(["--approved-fingerprint", "a" * 64])
    assert rc == 3
    assert json.loads(out)["error"] == "execute_flag_required"


def test_approved_fingerprint_is_required_and_validated():
    rc, out = _cli(["--execute"])
    assert rc == 3
    assert json.loads(out)["error"] == "approved_fingerprint_required"
    rc, out = _cli(["--execute", "--approved-fingerprint", "tooshort"])
    assert rc == 3
    rc, out = _cli(["--execute", "--approved-fingerprint", "z" * 64])
    assert rc == 3, "non-hex must be rejected"


def test_all_nine_expectations_are_required():
    rc, out = _cli(["--execute", "--approved-fingerprint", "a" * 64])
    payload = json.loads(out)
    assert rc == 3
    assert payload["error"] == "expectations_required"
    assert len(payload["missing_expectations"]) == 9


def test_no_production_fingerprint_or_counts_are_hard_coded():
    src = _EXEC_PATH.read_text()
    assert "5a905312" not in src, "the approved fingerprint must not be in source"
    assert not re.search(r"\b1031\b", src), "candidate count must not be hard-coded"
    assert not re.search(r"\b1155\b", src), "row count must not be hard-coded"
    assert not re.search(r"\b124\b", src)


def test_no_unique_index_or_migration_in_this_branch():
    src = _EXEC_PATH.read_text().lower()
    for token in ("create unique index", "create index", "alembic",
                  "uq_watched_tickers"):
        assert token not in src, "index/migration work belongs elsewhere: %s" % token


def test_output_is_aggregate_only():
    async def body(maker):
        await _seed(maker, [
            (OWNER_1, "AAA", 0, True), (OWNER_1, "AAA", 1, True),
            (OWNER_2, "BBB", 0, True),
        ])
        exp, fp = await _expectations(maker)
        report = await X.run_owned(_pg(maker), exp, fp, uuid.uuid4().hex)
        blob = json.dumps(report, default=str)
        assert OWNER_1 not in blob and OWNER_2 not in blob
        assert "AAA" not in blob and "BBB" not in blob
        assert "://" not in blob
        assert not re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            blob), "no uuid-style identifier may be emitted"
        for key in ("row_id", "candidate_ids", "user_id", "tickers"):
            assert key not in report

    _run(body)


def test_operation_ref_is_opaque_and_carries_no_row_identity():
    async def body(maker):
        from sqlalchemy import select
        from app.db.models import WatchedTicker
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(3)])
        exp, fp = await _expectations(maker)
        op = uuid.uuid4().hex
        report = await X.run_owned(_pg(maker), exp, fp, op)
        async with maker() as db:
            ids = [r.id for r in (await db.execute(
                select(WatchedTicker))).scalars().all()]
        for row_id in ids:
            assert row_id not in report["operation_ref"]

    _run(body)


def test_errors_are_sanitised_to_the_exception_class():
    class _Boom(Exception):
        pass
    msg = X._sanitise(_Boom("UPDATE watched_tickers SET ... user@example.test"))
    assert msg == "_Boom"
    assert "@" not in msg and "UPDATE" not in msg


def test_executor_reuses_the_rehearsal_module_not_a_copy():
    """Ranking semantics must not be reimplemented."""
    import io
    import tokenize
    code = []
    for tok in tokenize.generate_tokens(
            io.StringIO(_EXEC_PATH.read_text()).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        code.append(tok.string)
    joined = " ".join(code).lower()
    assert "row_number" not in joined, "must not reimplement ranking"
    assert "partition_by" not in joined
    assert X.R.build_plan is R.build_plan
    assert X.R.plan_fingerprint is R.plan_fingerprint


# ===========================================================================
# § AUDIT WRITE MUST NOT FAIL OPEN
#
# account_import_service._audit swallows exceptions so audit failures never
# block a user action. That trade-off is wrong for cleanup: a run whose
# rollback record failed to write must not commit. These tests exercise
# write_audit's OWN error propagation, not a substituted stub.
# ===========================================================================

class _FlushFails:
    """Session whose flush() fails — i.e. the audit INSERT is rejected."""

    def __init__(self, inner):
        self._inner = inner
        self.added = 0

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def add(self, obj):
        self.added += 1
        return self._inner.add(obj)

    async def flush(self, *a, **k):
        raise RuntimeError("audit insert rejected by the database")


def test_write_audit_propagates_a_flush_failure():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(3)])
        async with maker() as db:
            plan = await R.build_plan(db)
            with pytest.raises(RuntimeError):
                await X.write_audit(_FlushFails(_PgProxy(db)), uuid.uuid4().hex, plan)
            await db.rollback()

    _run(body)


def test_audit_flush_failure_rolls_the_whole_cleanup_back():
    """End to end: the audit INSERT fails, so no row may be deactivated."""
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        before = await _counts(maker)
        exp, fp = await _expectations(maker)

        async with maker() as inner:
            wrapped = _FlushFails(_PgProxy(inner))
            with pytest.raises(RuntimeError):
                await X.execute_cleanup(wrapped, exp, fp, uuid.uuid4().hex)
            await inner.rollback()

        assert await _counts(maker) == before, (
            "a rejected audit write must leave every row untouched"
        )

    _run(body)


def test_write_audit_contains_no_blanket_exception_suppression():
    """Guard the regression directly, in code rather than prose."""
    import io
    import tokenize

    src = _EXEC_PATH.read_text()
    start = src.index("async def write_audit(")
    end = src.index("async def audited_row_ids(")
    body = src[start:end]
    code = []
    for tok in tokenize.generate_tokens(io.StringIO(body).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        code.append(tok.string)
    joined = " ".join(code)
    assert "except" not in joined, (
        "write_audit must not catch anything — audit failure must abort"
    )


# ===========================================================================
# § ROLLBACK IS ATOMIC AND FAILS CLOSED
# ===========================================================================

def test_rollback_restores_every_audited_row_or_none():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        exp, fp = await _expectations(maker)
        op = uuid.uuid4().hex
        await X.run_owned(_pg(maker), exp, fp, op)
        assert (await _counts(maker))["active"] == 1

        async with maker() as db:
            restored = await X.rollback_operation(db, op)
            await db.commit()
        assert restored == 3
        assert (await _counts(maker))["active"] == 4

    _run(body)


def test_rollback_fails_closed_when_a_row_cannot_be_restored():
    """A partial restoration is never acceptable."""
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(4)])
        exp, fp = await _expectations(maker)
        op = uuid.uuid4().hex
        await X.run_owned(_pg(maker), exp, fp, op)
        after_cleanup = await _counts(maker)

        class _ShortRestore:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            async def execute(self, statement, *a, **k):
                res = await self._inner.execute(statement, *a, **k)
                if " ".join(str(statement).split()).upper().startswith("UPDATE"):
                    class _R:
                        rowcount = 1        # only one of three restored
                    return _R()
                return res

        async with maker() as inner:
            with pytest.raises(X.ExecutionError) as ei:
                await X.rollback_operation(_ShortRestore(inner), op)
            await inner.rollback()
        assert "rollback_row_count_mismatch" in str(ei.value)
        assert await _counts(maker) == after_cleanup, (
            "a failed rollback must leave the post-cleanup state intact"
        )

    _run(body)


def test_rollback_refuses_an_unknown_operation_reference():
    async def body(maker):
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(3)])
        async with maker() as db:
            with pytest.raises(X.ExecutionError) as ei:
                await X.rollback_operation(db, uuid.uuid4().hex)
        assert "no_audited_rows_for_operation" in str(ei.value)

    _run(body)


def test_rollback_would_violate_the_future_unique_indexes():
    """Ordering constraint: rollback RECREATES duplicates by design.

    Simulated with the same partial unique index Phase C will add. Reactivating
    this operation's rows must fail while that index exists — which is exactly
    why rollback after Phase C requires dropping the indexes first.
    """
    async def body(maker):
        from sqlalchemy import text
        await _seed(maker, [(OWNER_1, "AAA", i, True) for i in range(3)])
        exp, fp = await _expectations(maker)
        op = uuid.uuid4().hex
        await X.run_owned(_pg(maker), exp, fp, op)

        # Phase C's index, created here ONLY inside this throwaway fixture.
        async with maker() as db:
            await db.execute(text(
                "CREATE UNIQUE INDEX uq_owner_ticker_active "
                "ON watched_tickers (user_id, ticker) "
                "WHERE active AND user_id IS NOT NULL"))
            await db.commit()

        async with maker() as db:
            with pytest.raises(Exception) as ei:
                await X.rollback_operation(db, op)
                await db.commit()
            assert "UNIQUE" in str(ei.value).upper() or "unique" in str(ei.value)
            await db.rollback()

    _run(body)


def test_rollback_helper_is_not_exposed_through_the_cli():
    declared = {opt for action in X._parser()._actions
                for opt in action.option_strings}
    for flag in ("--rollback", "--restore", "--undo", "--reactivate"):
        assert flag not in declared, "rollback is its own approval: %s" % flag
