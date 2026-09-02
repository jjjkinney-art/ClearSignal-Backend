"""Section 0.8C — safety tests for the DRY-RUN cleanup rehearsal tool.

The tool must be structurally incapable of mutating the database, must never
emit identifying data, and must withhold its authorising fingerprint whenever
observed state does not match the approved expectations.

All fixtures are synthetic. No production value appears here.

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
SYSTEMISH = "00000000-0000-0000-0000-000000000001"

_TOOL_PATH = Path(__file__).resolve().parents[1] / "scripts" / \
    "watchlist_duplicate_cleanup_rehearsal.py"


def _tool():
    spec = importlib.util.spec_from_file_location("_wl_rehearsal", _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = _tool()
BASE_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _make_session():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _run(body):
    """Run without disturbing the ambient event loop."""
    async def _outer():
        engine, maker = await _make_session()
        try:
            async with maker() as db:
                await body(db)
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


async def _add(db, owner, ticker, *, minutes=0, active=True, row_id=None):
    from app.db.models import WatchedTicker

    db.add(WatchedTicker(
        id=row_id or uuid.uuid4().hex, user_id=owner, ticker=ticker,
        company_name=ticker, active=active,
        added_at=BASE_TS + timedelta(minutes=minutes),
    ))
    await db.flush()


async def _report(db, **expected):
    exp = {f: expected.get(f) for f in T.EXPECTATION_FIELDS}
    return await T.analyse(db, exp)


# ===========================================================================
# § SELECTION CORRECTNESS
# ===========================================================================

def test_clean_singletons_produce_zero_candidates():
    async def body(db):
        await _add(db, OWNER_1, "AAA")
        await _add(db, OWNER_1, "BBB")
        await _add(db, OWNER_2, "AAA")
        r = await _report(db)
        assert r["total_candidate_rows"] == 0
        assert r["membership_duplicate_groups"] == 0
        assert r["retained_active_rows"] == 3
        assert r["projected_active_row_count_after"] == 3

    _run(body)


def test_duplicates_within_one_owner_are_selected():
    async def body(db):
        for i in range(4):
            await _add(db, OWNER_1, "AAA", minutes=i)
        r = await _report(db)
        assert r["membership_duplicate_groups"] == 1
        assert r["membership_candidate_rows"] == 3
        assert r["membership_duplicate_owner_count"] == 1
        assert r["retained_active_rows"] == 1

    _run(body)


def test_same_ticker_across_owners_is_not_a_duplicate():
    """The central false-positive guard — partition includes the owner."""
    async def body(db):
        for owner in (OWNER_1, OWNER_2, SYSTEMISH):
            await _add(db, owner, "AAA")
        r = await _report(db)
        assert r["membership_duplicate_groups"] == 0
        assert r["total_candidate_rows"] == 0
        assert r["active_owner_count_before"] == 3
        assert r["projected_active_owner_count_after"] == 3

    _run(body)


def test_null_owner_duplicates_use_the_legacy_partition():
    async def body(db):
        await _add(db, None, "AAA", minutes=0)
        await _add(db, None, "AAA", minutes=1)
        await _add(db, OWNER_1, "AAA")
        r = await _report(db)
        assert r["legacy_duplicate_groups"] == 1
        assert r["legacy_candidate_rows"] == 1
        assert r["membership_duplicate_groups"] == 0, (
            "a null-owner row must never join an owned partition"
        )
        assert r["active_owner_count_before"] == 1

    _run(body)


def test_inactive_rows_never_interact_with_active_rows():
    async def body(db):
        await _add(db, OWNER_1, "AAA", minutes=0, active=True)
        await _add(db, OWNER_1, "AAA", minutes=1, active=False)
        await _add(db, OWNER_1, "AAA", minutes=2, active=False)
        r = await _report(db)
        assert r["total_candidate_rows"] == 0, (
            "soft-deleted history must not be selected for cleanup"
        )
        assert r["active_row_count_before"] == 1

    _run(body)


def test_oldest_by_added_at_then_id_is_retained():
    async def body(db):
        # Same timestamp: the id tie-break must decide, ascending.
        await _add(db, OWNER_1, "AAA", minutes=5, row_id="bbbb")
        await _add(db, OWNER_1, "AAA", minutes=5, row_id="aaaa")
        await _add(db, OWNER_1, "AAA", minutes=0, row_id="zzzz")
        plan = await T.build_plan(db)
        retained = [p for p in plan if p.rn == 1]
        assert len(retained) == 1
        assert retained[0].row_id == "zzzz", "oldest added_at wins first"

    _run(body)


def test_id_tiebreak_is_ascending_when_timestamps_match():
    async def body(db):
        await _add(db, OWNER_1, "AAA", minutes=3, row_id="ccc")
        await _add(db, OWNER_1, "AAA", minutes=3, row_id="aaa")
        await _add(db, OWNER_1, "AAA", minutes=3, row_id="bbb")
        plan = await T.build_plan(db)
        retained = [p for p in plan if p.rn == 1]
        assert retained[0].row_id == "aaa"

    _run(body)


def test_multiple_owners_and_tickers_aggregate_correctly():
    async def body(db):
        for i in range(3):
            await _add(db, OWNER_1, "AAA", minutes=i)     # 2 candidates
        for i in range(2):
            await _add(db, OWNER_1, "BBB", minutes=i)     # 1 candidate
        for i in range(5):
            await _add(db, OWNER_2, "AAA", minutes=i)     # 4 candidates
        await _add(db, OWNER_2, "CCC")                    # clean
        for i in range(2):
            await _add(db, None, "DDD", minutes=i)        # legacy: 1 candidate
        r = await _report(db)
        assert r["membership_duplicate_groups"] == 3
        assert r["membership_candidate_rows"] == 2 + 1 + 4
        assert r["membership_duplicate_owner_count"] == 2
        assert r["legacy_duplicate_groups"] == 1
        assert r["legacy_candidate_rows"] == 1
        assert r["total_candidate_rows"] == 8
        assert r["active_row_count_before"] == 13   # 3+2+5+1+2
        assert r["retained_active_rows"] == 5      # 4 owned groups + 1 legacy
        assert r["projected_active_row_count_after"] == 5
        assert r["projected_distinct_ticker_count_after"] == 4
        assert r["projected_active_owner_count_after"] == 2

    _run(body)


def test_duplicate_owner_count_is_aggregate_only():
    async def body(db):
        for i in range(2):
            await _add(db, OWNER_1, "AAA", minutes=i)
        for i in range(2):
            await _add(db, OWNER_2, "BBB", minutes=i)
        r = await _report(db)
        assert r["membership_duplicate_owner_count"] == 2
        assert isinstance(r["membership_duplicate_owner_count"], int)

    _run(body)


# ===========================================================================
# § EXPECTATIONS
# ===========================================================================

def test_expectation_match_produces_a_fingerprint():
    async def body(db):
        for i in range(3):
            await _add(db, OWNER_1, "AAA", minutes=i)
        r = await _report(
            db, active_rows=3, distinct_tickers=1, active_owners=1,
            membership_duplicate_groups=1, membership_candidate_rows=2,
            legacy_duplicate_groups=0, legacy_candidate_rows=0,
            orphan_owners=1, orphan_rows=3,
        )
        assert r["expectation_match"] is True
        assert isinstance(r["plan_fingerprint"], str)
        assert len(r["plan_fingerprint"]) == 64

    _run(body)


def test_expectation_mismatch_withholds_the_fingerprint():
    async def body(db):
        for i in range(3):
            await _add(db, OWNER_1, "AAA", minutes=i)
        r = await _report(db, membership_candidate_rows=999)
        assert r["expectation_match"] is False
        assert r["plan_fingerprint"] is None, (
            "a mismatched run must not produce an authorizable plan"
        )
        chk = r["expectation_checks"]["membership_candidate_rows"]
        assert chk == {"expected": 999, "actual": 2, "delta": 2 - 999}

    _run(body)


def test_mismatch_exits_non_zero_and_match_exits_zero(monkeypatch, tmp_path):
    """CLI-level: exit code is the gate, not just the JSON field."""
    import io
    import contextlib

    db_path = tmp_path / "rehearsal.sqlite"
    url = "sqlite+aiosqlite:///%s" % db_path

    async def seed():
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from app.db.models import Base, WatchedTicker
        eng = create_async_engine(url, future=True)
        async with eng.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        mk = async_sessionmaker(eng, expire_on_commit=False)
        async with mk() as db:
            for i in range(3):
                db.add(WatchedTicker(
                    id=uuid.uuid4().hex, user_id=OWNER_1, ticker="AAA",
                    company_name="AAA", active=True,
                    added_at=BASE_TS + timedelta(minutes=i)))
            await db.commit()
        await eng.dispose()

    try:
        prev = asyncio.get_event_loop()
    except RuntimeError:
        prev = None
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(seed())
    finally:
        loop.close()
        asyncio.set_event_loop(prev)

    good = ["--database-url", url, "--expect-active-rows", "3",
            "--expect-distinct-tickers", "1", "--expect-active-owners", "1",
            "--expect-membership-duplicate-groups", "1",
            "--expect-membership-candidate-rows", "2",
            "--expect-legacy-duplicate-groups", "0",
            "--expect-legacy-candidate-rows", "0",
            "--expect-orphan-owners", "1", "--expect-orphan-rows", "3"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc_ok = T.main(good)
    assert rc_ok == 0
    payload = json.loads(buf.getvalue())
    assert payload["expectation_match"] is True
    assert payload["dry_run"] is True

    bad = list(good)
    bad[bad.index("--expect-membership-candidate-rows") + 1] = "7"
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rc_bad = T.main(bad)
    assert rc_bad == 2
    assert json.loads(buf2.getvalue())["plan_fingerprint"] is None


def test_omitting_expectations_exits_three():
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = T.main(["--database-url", "sqlite+aiosqlite:///:memory:"])
    assert rc == 3
    payload = json.loads(buf.getvalue())
    assert payload["error"] == "expectations_required"
    assert payload["plan_fingerprint"] is None


def test_no_expectations_is_refused_in_production(monkeypatch):
    import io
    import contextlib

    monkeypatch.setattr(T, "_is_production", lambda: True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = T.main(["--database-url", "sqlite+aiosqlite:///:memory:",
                     "--no-expectations"])
    assert rc == 3
    assert json.loads(buf.getvalue())["error"] == \
        "expectations_required_in_production"


# ===========================================================================
# § FINGERPRINT
# ===========================================================================

def test_fingerprint_is_stable_across_database_return_order():
    rows = [
        T.PlanRow(T.NS_OWNED, OWNER_1, "AAA", 1, "a", BASE_TS),
        T.PlanRow(T.NS_OWNED, OWNER_1, "AAA", 2, "b", BASE_TS),
        T.PlanRow(T.NS_LEGACY, "", "CCC", 1, "c", BASE_TS),
    ]
    assert T.plan_fingerprint(rows) == T.plan_fingerprint(list(reversed(rows)))


@pytest.mark.parametrize("mutate,label", [
    (lambda r: setattr(r[1], "rn", 1), "retain/candidate decision"),
    (lambda r: setattr(r[0], "owner_key", OWNER_2), "ownership namespace"),
    (lambda r: setattr(r[0], "ticker", "ZZZ"), "ticker grouping"),
    (lambda r: setattr(r[0], "row_id", "different"), "candidate row identity"),
    (lambda r: setattr(r[0], "namespace", T.NS_LEGACY), "namespace"),
    (lambda r: setattr(r[0], "added_at", BASE_TS + timedelta(days=1)),
     "ordering key"),
])
def test_fingerprint_changes_when_the_plan_changes(mutate, label):
    def fresh():
        return [
            T.PlanRow(T.NS_OWNED, OWNER_1, "AAA", 1, "a", BASE_TS),
            T.PlanRow(T.NS_OWNED, OWNER_1, "AAA", 2, "b", BASE_TS),
        ]

    before = T.plan_fingerprint(fresh())
    rows = fresh()
    mutate(rows)
    assert T.plan_fingerprint(rows) != before, (
        "fingerprint must detect a change in %s" % label
    )


def test_fingerprint_is_not_merely_a_count():
    """Two plans with identical counts but different rows must differ."""
    a = [T.PlanRow(T.NS_OWNED, OWNER_1, "AAA", 1, "a", BASE_TS),
         T.PlanRow(T.NS_OWNED, OWNER_1, "AAA", 2, "b", BASE_TS)]
    b = [T.PlanRow(T.NS_OWNED, OWNER_2, "BBB", 1, "c", BASE_TS),
         T.PlanRow(T.NS_OWNED, OWNER_2, "BBB", 2, "d", BASE_TS)]
    assert T.plan_fingerprint(a) != T.plan_fingerprint(b)


# ===========================================================================
# § NON-DISCLOSURE AND NON-MUTATION
# ===========================================================================

def test_output_contains_no_identifying_values():
    async def body(db):
        from app.db.models import User
        db.add(User(id=OWNER_1, email="someone@example.test"))
        await db.flush()
        for i in range(3):
            await _add(db, OWNER_1, "AAA", minutes=i)
        await _add(db, None, "BBB")
        r = await _report(db)
        blob = json.dumps(r, default=str)
        assert not re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            blob), "a uuid-like value reached the output"
        assert "@" not in blob, "an email-like value reached the output"
        assert "AAA" not in blob and "BBB" not in blob, (
            "ticker membership must not be listed"
        )
        assert "://" not in blob, "database URL must never be emitted"
        assert "@" not in blob
        # transaction_mode reports only the dialect name + whether a READ ONLY
        # transaction was obtained. It carries no host, database or credential.
        assert "://" not in r["transaction_mode"]
        for key in ("row_id", "candidate_ids", "retained_ids", "user_id",
                    "owner_key", "tickers"):
            assert key not in r

    _run(body)


def test_no_database_write_method_is_called():
    """Wrap the session and fail if anything but execute() is touched."""
    calls = []

    class _Recorder:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            calls.append(name)
            attr = getattr(self._inner, name)
            if name in ("add", "add_all", "delete", "merge", "commit",
                        "flush", "bulk_save_objects"):
                raise AssertionError("write method called: %s" % name)
            return attr

    async def body(db):
        for i in range(3):
            await _add(db, OWNER_1, "AAA", minutes=i)
        await _report(_Recorder(db))
        assert "execute" in calls
        assert not ({"add", "delete", "commit", "flush", "merge"} & set(calls))

    _run(body)


def test_tool_source_contains_no_mutation_or_executor_path():
    """Scan real CODE, not prose.

    Comments and string literals are stripped with tokenize, so the tool's own
    docstring may legitimately discuss the executor and audit writes while the
    executable body stays free of them. String literals are then scanned
    separately for DML statement text.
    """
    import io
    import tokenize

    src = _TOOL_PATH.read_text()
    code_tokens, string_literals = [], []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING:
            string_literals.append(tok.string.lower())
            continue
        code_tokens.append(tok.string)
    code = " ".join(code_tokens).lower()

    for token in ("session.add", "session.delete", "session.merge",
                  ".commit(", ".flush(", "add_all", "bulk_save_objects",
                  "audit_log"):
        assert token not in code, "dry-run tool must not contain %r" % token

    # No DML construct imported from SQLAlchemy.
    for verb in ("insert", "update", "delete"):
        assert not re.search(r"from sqlalchemy import[^\n]*\b%s\b" % verb, code)

    # No executor / apply / cleanup switch may be DECLARED. Interrogate the
    # real parser rather than the source text, so the docstring may state that
    # such flags do not exist without tripping its own check.
    declared = {opt for action in T._parser()._actions
                for opt in action.option_strings}
    for flag in ("--execute", "--apply", "--cleanup", "--commit", "--force",
                 "--yes", "--write", "--mutate"):
        assert flag not in declared, "no mutation flag may exist: %s" % flag
    allowed = {"-h", "--help", "--no-expectations", "--database-url"} | {
        "--expect-" + f.replace("_", "-") for f in T.EXPECTATION_FIELDS}
    assert declared <= allowed, "unexpected CLI option(s): %s" % (
        sorted(declared - allowed),)

    # No DML statement text inside any string literal.
    for lit in string_literals:
        assert not re.search(r"\b(insert\s+into|update\s+\w+\s+set|delete\s+from)\b",
                             lit), "DML statement text found in a literal"

    assert "row_number" in code
    assert "select" in code


def test_tool_declares_itself_dry_run():
    async def body(db):
        await _add(db, OWNER_1, "AAA")
        r = await _report(db)
        assert r["dry_run"] is True
        assert r["tool"] == T.TOOL_NAME
        assert r["tool_version"] == T.TOOL_VERSION
        assert "generated_at" in r

    _run(body)


def test_errors_are_sanitised_to_the_exception_class_only():
    class _Boom(Exception):
        pass

    msg = T._sanitise(_Boom("SELECT * FROM users WHERE email='a@b.c'"))
    assert msg == "_Boom"
    assert "@" not in msg and "SELECT" not in msg


# ===========================================================================
# § POSTGRESQL READ-ONLY ORDERING AND TRANSACTION CLEANUP (Section 0.8C.2)
#
# These use a RECORDING session with a synthetic dialect rather than scanning
# source text, so ordering is proven by observed call sequence. No PostgreSQL
# server and no new dependency is required.
# ===========================================================================

class _RecordingSession:
    """Records every database interaction in order. Never writes."""

    def __init__(self, dialect="postgresql", rows=None, fail_on_read_only=False):
        self.calls = []                      # ordered log of operations
        self._dialect = dialect
        self._rows = rows or []
        self._fail_on_read_only = fail_on_read_only
        self.bind = self                     # session.bind.dialect.name
        self.dialect = self
        self.name = dialect

    async def execute(self, statement, *a, **k):
        text = " ".join(str(statement).split()).upper()
        if "SET TRANSACTION READ ONLY" in text:
            self.calls.append("SET_READ_ONLY")
            if self._fail_on_read_only:
                raise RuntimeError(
                    "permission denied for relation watched_tickers "
                    "[SQL: SELECT secret FROM users WHERE email='leak@example.test']")
            return _FakeResult([])
        self.calls.append("SELECT")
        return _FakeResult(self._rows)

    async def rollback(self):
        self.calls.append("ROLLBACK")

    async def close(self):
        self.calls.append("CLOSE")

    # Forbidden operations — presence in `calls` fails the tests below.
    async def commit(self):
        self.calls.append("COMMIT")

    async def flush(self, *a, **k):
        self.calls.append("FLUSH")

    def add(self, *a, **k):
        self.calls.append("ADD")


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def one(self):
        return self._rows[0] if self._rows else (0, 0)


class _OwnedFactory:
    """Mimics async_sessionmaker(): the CLI owns and closes this session."""

    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        await self.session.close()
        return False


def _drive(coro_factory):
    try:
        prev = asyncio.get_event_loop()
    except RuntimeError:
        prev = None
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()
        asyncio.set_event_loop(prev)


def _no_expectations():
    return {f: None for f in T.EXPECTATION_FIELDS}


# --- A / B: read-only is issued, and issued FIRST -------------------------

def test_postgresql_issues_set_transaction_read_only_before_any_selection():
    s = _RecordingSession("postgresql")
    report = _drive(lambda: T.analyse(s, _no_expectations()))
    assert "SET_READ_ONLY" in s.calls, "READ ONLY was never issued"
    assert s.calls[0] == "SET_READ_ONLY", (
        "the FIRST statement must be SET TRANSACTION READ ONLY, got %r"
        % (s.calls[:3],)
    )
    assert "SELECT" in s.calls, "selection never ran"
    assert s.calls.index("SET_READ_ONLY") < s.calls.index("SELECT"), (
        "every candidate-selection query must follow READ ONLY"
    )
    assert report["transaction_mode"] == "postgresql:read_only"


def test_read_only_precedes_every_selection_not_just_the_first():
    s = _RecordingSession("postgresql")
    _drive(lambda: T.analyse(s, _no_expectations()))
    first_ro = s.calls.index("SET_READ_ONLY")
    for i, call in enumerate(s.calls):
        if call == "SELECT":
            assert i > first_ro, "a selection ran before READ ONLY"


# --- C: failure path ------------------------------------------------------

def test_read_only_failure_prevents_selection_and_still_releases():
    s = _RecordingSession("postgresql", fail_on_read_only=True)
    factory = _OwnedFactory(s)
    with pytest.raises(RuntimeError):
        _drive(lambda: T.analyse_with_owned_session(factory, _no_expectations()))
    assert "SELECT" not in s.calls, (
        "no selection may run when READ ONLY could not be established"
    )
    assert s.calls == ["SET_READ_ONLY", "ROLLBACK", "CLOSE"], (
        "failure path must roll back then close; got %r" % (s.calls,)
    )


def test_cli_failure_exit_is_non_zero_and_sanitised(monkeypatch):
    import contextlib
    import io

    s = _RecordingSession("postgresql", fail_on_read_only=True)

    async def _boom(*a, **k):
        raise RuntimeError(
            "connection to server at 'db.internal' failed "
            "[SQL: SELECT * FROM users] [parameters: ('secret@example.test',)]")

    monkeypatch.setattr(T, "analyse_with_owned_session", _boom)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = T.main(["--database-url", "sqlite+aiosqlite:///:memory:",
                     "--no-expectations"])
    assert rc == 4
    out = buf.getvalue()
    payload = json.loads(out)
    assert payload["error"] == "analysis_failed"
    assert payload["error_type"] == "RuntimeError"
    assert payload["plan_fingerprint"] is None
    for leak in ("SELECT", "parameters", "db.internal", "://", "@", "secret"):
        assert leak not in out, "sanitised error leaked %r" % leak


# --- D / E: success and mismatch both release, in the right order ---------

def test_success_rolls_back_before_close_and_never_commits():
    s = _RecordingSession("postgresql")
    factory = _OwnedFactory(s)
    report = _drive(
        lambda: T.analyse_with_owned_session(factory, _no_expectations()))
    assert report["dry_run"] is True
    assert "ROLLBACK" in s.calls and "CLOSE" in s.calls
    assert s.calls.index("ROLLBACK") < s.calls.index("CLOSE"), (
        "rollback must happen before the context manager closes the session"
    )
    assert "COMMIT" not in s.calls
    assert "FLUSH" not in s.calls
    assert "ADD" not in s.calls
    assert s.calls[-1] == "CLOSE"


def test_expectation_mismatch_still_releases_and_withholds_fingerprint():
    s = _RecordingSession("postgresql")
    factory = _OwnedFactory(s)
    expected = _no_expectations()
    expected["active_rows"] = 4242            # cannot match an empty plan
    report = _drive(lambda: T.analyse_with_owned_session(factory, expected))
    assert report["expectation_match"] is False
    assert report["plan_fingerprint"] is None
    assert s.calls.index("ROLLBACK") < s.calls.index("CLOSE")
    assert "COMMIT" not in s.calls


# --- F: non-PostgreSQL takes the documented no-op path --------------------

@pytest.mark.parametrize("dialect", ["sqlite", "mysql"])
def test_non_postgresql_dialects_take_the_no_op_path(dialect):
    s = _RecordingSession(dialect)
    report = _drive(lambda: T.analyse(s, _no_expectations()))
    assert "SET_READ_ONLY" not in s.calls, (
        "%s must not be sent a PostgreSQL-only statement" % dialect
    )
    assert report["transaction_mode"] == "%s:not_supported" % dialect
    assert "COMMIT" not in s.calls and "FLUSH" not in s.calls


# --- G: caller-owned sessions keep their own lifecycle --------------------

def test_analyse_does_not_close_or_roll_back_a_caller_owned_session():
    """analyse() must impose no lifecycle side effects on a borrowed session."""
    s = _RecordingSession("postgresql")
    _drive(lambda: T.analyse(s, _no_expectations()))
    assert "ROLLBACK" not in s.calls, (
        "analyse() must not roll back a session it does not own"
    )
    assert "CLOSE" not in s.calls, (
        "analyse() must not close a session it does not own"
    )


def test_release_transaction_is_safe_when_nothing_to_roll_back():
    class _NoTx:
        async def rollback(self):
            raise RuntimeError("no transaction is active")

    _drive(lambda: T._release_transaction(_NoTx()))   # must not raise


def test_owned_session_helper_does_not_use_autocommitting_begin():
    """session.begin() commits on success — forbidden for a dry-run tool.

    Scans executable code only: the tool's docstring legitimately explains why
    session.begin() is not used, and prose must not trip its own check.
    """
    import io
    import tokenize

    code = []
    for tok in tokenize.generate_tokens(
            io.StringIO(_TOOL_PATH.read_text()).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        code.append(tok.string)
    joined = " ".join(code)
    assert "session . begin" not in joined
    assert ".begin(" not in joined.replace(" ", "")
