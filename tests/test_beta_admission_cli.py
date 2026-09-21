"""Section 0.15 — operator tool reaches persistence, and refuses correctly.

Regression for the production failure

    $ python3 scripts/beta_admission.py grandfather-existing
    refused: persistence unavailable

against a healthy, migrated production database. Root cause: the tool used
``get_session()`` without ever calling ``init_db()``; only the FastAPI
lifespan created the engine, so ``get_session()`` always yielded ``None``.

The earlier CLI tests only inspected the script's SOURCE and exercised the
service functions with an injected session, so nothing ever ran the command.
These tests do:

  * TestRenderShapedCommand — the real script as a SUBPROCESS, cwd = repo
    root, configuration only through environment variables, exactly the
    shape of a Render Shell invocation.
  * TestRefusals             — every guard, as a subprocess, proving the
    database is untouched (byte-identical file) when a guard refuses.
  * TestStatementCapture     — in-process, with SQLAlchemy engine events, to
    prove which statements are and are not issued.

Production is PostgreSQL + asyncpg. These tests use SQLite + aiosqlite through
the SAME application code path (settings.database_url → init_db → session
factory); the read-only guard has a dialect-specific branch for each.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "beta_admission.py")
PEPPER = "p" * 40
BOUND = ["subject-one", "subject-two", "subject-three"]

# Anything in this list appearing in CLI output is a leak.
FORBIDDEN_OUTPUT = BOUND + ["@example.test", "sqlite", "aiosqlite", ".db", PEPPER, "Traceback"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MIGRATE = """
import sys
from alembic import command
from alembic.config import Config
root, path, revision = sys.argv[1:4]
cfg = Config(root + "/alembic.ini")
cfg.set_main_option("script_location", root + "/alembic")
cfg.set_main_option("sqlalchemy.url", "sqlite+aiosqlite:///" + path)
command.upgrade(cfg, revision)
"""


def _migrate(path: str, revision: str = "head") -> None:
    """Migrate in a SEPARATE PROCESS, exactly as a deploy does.

    alembic/env.py calls logging.config.fileConfig(), whose default
    disable_existing_loggers=True silently disables every logger that already
    exists in the calling process. Running it inside pytest disabled
    app.db.repositories.watchlist_repo for every later test, which broke an
    unrelated caplog assertion in the full suite. Out of process, it can't.
    """
    subprocess.run(
        [sys.executable, "-c", _MIGRATE, ROOT, path, revision],
        cwd=ROOT, check=True, capture_output=True, timeout=120,
    )


def _seed(path: str) -> None:
    """Three bound identities and one unbound row."""
    conn = sqlite3.connect(path)
    for i, subject in enumerate(BOUND + [None]):
        conn.execute(
            "INSERT INTO users (id, email, email_verified, account_type, is_active, "
            "plan, auth_subject, created_at, updated_at) VALUES "
            "(?, ?, 1, 'individual', 1, 'free', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (f"user-{i}", f"user{i}@example.test", subject),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def db_path():
    path = os.path.join(tempfile.mkdtemp(), "render_shaped.db")
    _migrate(path)
    _seed(path)
    return path


def _digest(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _counts(path: str) -> dict:
    conn = sqlite3.connect(path)
    try:
        return {
            "grants": conn.execute("SELECT count(*) FROM access_grants").fetchone()[0],
            "audit": conn.execute("SELECT count(*) FROM audit_log").fetchone()[0],
            "users": conn.execute("SELECT count(*) FROM users").fetchone()[0],
        }
    finally:
        conn.close()


def _run(*args, db=None, pepper=PEPPER, mode=None, extra_env=None):
    """Run the real script the way the Render Shell does."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("DATABASE_URL", "BETA_ADMISSION_"))}
    if db is not None:
        env["DATABASE_URL"] = db if "://" in db else f"sqlite+aiosqlite:///{db}"
    if pepper is not None:
        env["BETA_ADMISSION_PEPPER"] = pepper
    if mode is not None:
        env["BETA_ADMISSION_MODE"] = mode
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, SCRIPT, *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _assert_no_leak(output: str) -> None:
    for token in FORBIDDEN_OUTPUT:
        assert token not in output, f"operator output leaked {token!r}"


def _values(output: str) -> dict:
    return {k: int(v) for k, v in re.findall(r"^\s+(\w+)\s+(\d+)$", output, re.M)}


# ---------------------------------------------------------------------------
# The production regression
# ---------------------------------------------------------------------------

class TestRenderShapedCommand:
    def test_dry_run_reaches_persistence(self, db_path):
        """The exact command that failed in production now reaches the DB."""
        code, out = _run("grandfather-existing", db=db_path)

        assert "persistence unavailable" not in out
        assert code == 0, out
        assert "state=DRY-RUN" in out and "read_only=True" in out
        assert _values(out) == {
            "examined": 4, "would_grant": 3, "already_granted": 0, "skipped_unbound": 1,
        }
        _assert_no_leak(out)

    def test_dry_run_writes_nothing_at_all(self, db_path):
        before = _digest(db_path)
        code, _ = _run("grandfather-existing", db=db_path)
        assert code == 0
        assert _digest(db_path) == before, "dry run must leave the database byte-identical"

    def test_execute_grants_exactly_the_bound_identities(self, db_path):
        code, out = _run("grandfather-existing", "--execute", db=db_path)

        assert code == 0, out
        assert "state=EXECUTED" in out and "committed=True" in out
        values = _values(out)
        assert values["granted"] == 3 and values["subject_grants_after"] == 3
        assert _counts(db_path)["grants"] == 3
        _assert_no_leak(out)

    def test_execute_is_idempotent(self, db_path):
        assert _run("grandfather-existing", "--execute", db=db_path)[0] == 0
        code, out = _run("grandfather-existing", "--execute", db=db_path)
        assert code == 0
        assert _values(out)["granted"] == 0
        assert _counts(db_path)["grants"] == 3

    def test_status_reaches_persistence(self, db_path):
        code, out = _run("status", db=db_path)
        assert code == 0, out
        assert "read_only=True" in out
        assert _values(out)["total"] == 0
        _assert_no_leak(out)

    def test_every_run_has_a_fresh_opaque_operation_ref(self, db_path):
        refs = set()
        for _ in range(2):
            _, out = _run("grandfather-existing", db=db_path)
            refs |= set(re.findall(r"operation_ref=([0-9a-f]{12})", out))
        assert len(refs) == 2


# ---------------------------------------------------------------------------
# Refusals — every guard, and nothing touched when it fires
# ---------------------------------------------------------------------------

class TestRefusals:
    def test_missing_database_url(self, db_path):
        before = _digest(db_path)
        code, out = _run("grandfather-existing", db=None)
        assert code == 2
        assert out.strip() == "refused: persistence unavailable: database not configured"
        assert _digest(db_path) == before

    def test_missing_pepper_refuses_before_connecting(self, db_path):
        before = _digest(db_path)
        code, out = _run("grandfather-existing", db=db_path, pepper="")
        assert code == 2
        assert out.strip() == "refused: pepper not configured"
        assert _digest(db_path) == before

    def test_weak_pepper_refuses(self, db_path):
        code, out = _run("grandfather-existing", db=db_path, pepper="short")
        assert code == 2 and "pepper not configured" in out
        assert "short" not in out

    def test_invalid_mode_refuses_without_echoing_it(self, db_path):
        code, out = _run("grandfather-existing", db=db_path, mode="enfore-XYZZY")
        assert code == 2
        assert out.strip() == "refused: admission configuration invalid"
        assert "XYZZY" not in out

    def test_unreachable_database_refuses_sanitised(self):
        code, out = _run(
            "grandfather-existing",
            db="sqlite+aiosqlite:////nonexistent-dir/secret-host-name/x.db",
        )
        assert code == 2
        assert out.strip().startswith("refused: persistence unavailable")
        assert "secret-host-name" not in out and "nonexistent-dir" not in out
        assert "Traceback" not in out

    def test_engine_that_cannot_initialise_refuses(self):
        """init_db swallows its own failure and leaves persistence disabled.

        The tool must read that as a refusal, not carry on and crash.
        """
        code, out = _run("grandfather-existing", db="nosuchdialect+nodriver://h/secret-db")
        assert code == 2
        assert out.strip() == "refused: persistence unavailable: engine not initialised"
        assert "secret-db" not in out

    def test_database_behind_head_refuses_and_is_untouched(self):
        path = os.path.join(tempfile.mkdtemp(), "behind.db")
        _migrate(path, "0005_watchlist_unique_active")
        before = _digest(path)

        code, out = _run("grandfather-existing", "--execute", db=path)

        assert code == 2
        assert out.strip() == "refused: schema unavailable"
        assert _digest(path) == before, "no table created, no row written"

    def test_unmigrated_database_refuses(self):
        path = os.path.join(tempfile.mkdtemp(), "empty.db")
        sqlite3.connect(path).close()
        code, out = _run("grandfather-existing", db=path)
        assert code == 2 and out.strip() == "refused: schema unavailable"

    def test_address_commands_refuse_a_piped_address(self, db_path):
        before = _digest(db_path)
        for command in ("approve", "revoke"):
            code, out = _run(command, db=db_path)
            assert code == 2
            assert "typed interactively" in out
        assert _digest(db_path) == before


# ---------------------------------------------------------------------------
# Statement capture — what SQL is actually issued
# ---------------------------------------------------------------------------

def _load_cli():
    import importlib
    import scripts.beta_admission as cli
    return importlib.reload(cli)


@pytest.fixture
def capture(monkeypatch, db_path):
    """Point the app settings at the throwaway DB and record every statement."""
    from sqlalchemy import event
    from app.config import settings
    from app.db import connection

    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}", raising=False)
    monkeypatch.setattr(settings, "beta_admission_pepper", PEPPER, raising=False)
    monkeypatch.setattr(settings, "beta_admission_mode", "", raising=False)

    log = {"statements": [], "commits": 0}
    real_init = connection.init_db

    async def recording_init(url):
        await real_init(url)
        if connection._engine is not None:
            sync = connection._engine.sync_engine

            @event.listens_for(sync, "before_cursor_execute")
            def _stmt(conn, cursor, statement, params, context, executemany):
                log["statements"].append(statement.strip().upper())

            @event.listens_for(sync, "commit")
            def _commit(conn):
                log["commits"] += 1

    monkeypatch.setattr(connection, "init_db", recording_init)
    return log, db_path


class _Args:
    def __init__(self, execute=False, note_ref=None):
        self.execute = execute
        self.note_ref = note_ref


WRITES = ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER")


class TestStatementCapture:
    def test_dry_run_issues_no_write_and_no_commit(self, capture):
        log, _ = capture
        cli = _load_cli()
        assert asyncio.run(cli.cmd_grandfather(_Args())) == 0

        assert log["statements"], "the command must actually reach the database"
        assert not [s for s in log["statements"] if s.startswith(WRITES)]
        assert log["commits"] == 0

    def test_read_only_guard_is_in_force(self, capture):
        """A write attempted inside a read-only session must fail."""
        from sqlalchemy import text
        log, db_path = capture
        cli = _load_cli()

        async def attempt():
            async with cli.open_session(read_only=True) as (session, _mode):
                await session.execute(text(
                    "INSERT INTO access_grants (id, kind, status, created_at, updated_at) "
                    "VALUES ('x', 'subject', 'approved', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ))

        with pytest.raises(Exception):
            asyncio.run(attempt())
        assert _counts(db_path)["grants"] == 0

    def test_read_only_verification_failure_refuses_before_any_business_select(
        self, capture, monkeypatch,
    ):
        log, _ = capture
        cli = _load_cli()

        async def failing(session, dialect):
            raise cli.Refused("read-only transaction could not be verified")

        monkeypatch.setattr(cli, "_verify_read_only", failing)
        with pytest.raises(cli.Refused):
            asyncio.run(cli.cmd_grandfather(_Args()))
        business = [s for s in log["statements"] if "FROM USERS" in s or "FROM ACCESS_GRANTS" in s]
        assert business == []

    def test_unknown_dialect_is_refused_for_read_only(self):
        cli = _load_cli()
        with pytest.raises(cli.Refused):
            asyncio.run(cli._verify_read_only(object(), "mysql"))

    def test_row_count_mismatch_rolls_back_everything(self, capture, monkeypatch):
        log, db_path = capture
        cli = _load_cli()
        from app.services import access_grant_service as svc
        real = svc.grandfather_existing_subjects

        async def overreporting(session, **kwargs):
            result = await real(session, **kwargs)
            result["granted"] += 1          # claims one more row than it wrote
            return result

        monkeypatch.setattr(svc, "grandfather_existing_subjects", overreporting)
        with pytest.raises(cli.Refused) as exc:
            asyncio.run(cli.cmd_grandfather(_Args(execute=True)))

        assert exc.value.category == "row-count mismatch; rolled back"
        assert log["commits"] == 0
        assert _counts(db_path)["grants"] == 0, "no partial state may survive"
        assert _counts(db_path)["audit"] == 0

    def test_execute_commits_exactly_once(self, capture):
        log, db_path = capture
        cli = _load_cli()
        assert asyncio.run(cli.cmd_grandfather(_Args(execute=True))) == 0
        assert log["commits"] == 1
        assert _counts(db_path)["grants"] == 3

    def test_missing_url_never_initialises_an_engine(self, capture, monkeypatch):
        log, _ = capture
        from app.config import settings
        from app.db import connection
        monkeypatch.setattr(settings, "database_url", "", raising=False)
        cli = _load_cli()
        with pytest.raises(cli.Refused):
            asyncio.run(cli.cmd_grandfather(_Args()))
        assert connection.get_session_factory() is None
        assert log["statements"] == []

    def test_engine_is_disposed_after_every_run(self, capture):
        from app.db import connection
        cli = _load_cli()
        asyncio.run(cli.cmd_grandfather(_Args()))
        assert connection.get_session_factory() is None
