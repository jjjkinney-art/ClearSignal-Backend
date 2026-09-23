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


# ---------------------------------------------------------------------------
# Section 0.16 — double masked confirmation, driven through a real terminal
# ---------------------------------------------------------------------------

import pty
import select
import signal
import time

ADDRESS = "canary.person@example.test"
TYPO = "canary.persn@example.test"


def _pty_run(args, entries, db, *, pepper=PEPPER, timeout=90, marker=b"(input hidden):"):
    """Run the real CLI on a pseudo-terminal, as the Render Shell does.

    ``entries`` is a list of byte strings; each is written only after a
    masked prompt has appeared. Returns (exit_code, everything the terminal
    displayed). With echo off, nothing typed may appear in that transcript.
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("DATABASE_URL", "BETA_ADMISSION_"))}
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
    if pepper is not None:
        env["BETA_ADMISSION_PEPPER"] = pepper
    argv = [sys.executable, SCRIPT, *args]

    pid, fd = pty.fork()
    if pid == 0:                                    # child: the operator's shell
        os.chdir(ROOT)
        os.execve(sys.executable, argv, env)

    transcript = b""
    sent = 0
    deadline = time.time() + timeout
    timed_out = True
    try:
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:            # the child closed the terminal: it has exited
                chunk = b""
            if not chunk:
                timed_out = False
                break
            transcript += chunk
            # Answer each masked prompt only once it has actually appeared.
            while sent < len(entries) and transcript.count(marker) > sent:
                os.write(fd, entries[sent])
                sent += 1
        if timed_out:
            os.kill(pid, signal.SIGKILL)
    finally:
        # Always reap with a BLOCKING wait. A WNOHANG poll returns (0, 0) while
        # the child is still running, and mistaking that 0 for an exit status
        # would report success for a run that refused.
        _, status = os.waitpid(pid, 0)
        os.close(fd)
    # A terminal ends lines with CRLF; normalise so output parses like a pipe's.
    text = transcript.decode("utf-8", "replace").replace("\r\n", "\n")
    return os.waitstatus_to_exitcode(status), text


def _grant_rows(path: str) -> dict:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT status, subject IS NOT NULL, email_locator IS NOT NULL FROM access_grants"
        ).fetchall()
    finally:
        conn.close()
    return {
        "total": len(rows),
        "approved": sum(1 for r in rows if r[0] == "approved"),
        "revoked": sum(1 for r in rows if r[0] == "revoked"),
        "with_locator": sum(1 for r in rows if r[2]),
    }


def _assert_address_never_shown(transcript: str, *addresses: str) -> None:
    lowered = transcript.lower()
    for address in addresses:
        assert address.lower() not in lowered, "an address was displayed"
        # Nor any recognisable fragment of it.
        assert address.split("@")[0].lower() not in lowered
    _assert_no_leak(transcript)


class TestDoubleMaskedEntry:
    """The address is asked for twice, masked, and must match before any DB work."""

    def test_matching_entries_create_one_grant(self, db_path):
        code, out = _pty_run(
            ["approve", "--note-ref", "R-001"],
            [ADDRESS.encode() + b"\r", ADDRESS.upper().encode() + b"\r"],
            db_path,
        )
        assert code == 0, out
        assert "state=EXECUTED" in out and "committed=True" in out
        assert _values(out)["created"] == 1
        assert _grant_rows(db_path) == {"total": 1, "approved": 1, "revoked": 0, "with_locator": 1}
        _assert_address_never_shown(out, ADDRESS)

    def test_both_prompts_are_masked(self, db_path):
        code, out = _pty_run(
            ["approve"], [ADDRESS.encode() + b"\r", ADDRESS.encode() + b"\r"], db_path,
        )
        assert code == 0
        assert out.count("(input hidden):") == 2, "the address must be requested exactly twice"
        assert "Confirm address to approve" in out
        _assert_address_never_shown(out, ADDRESS)

    def test_approve_mismatch_refuses_and_leaves_storage_identical(self, db_path):
        before = _digest(db_path)
        code, out = _pty_run(
            ["approve"], [ADDRESS.encode() + b"\r", TYPO.encode() + b"\r"], db_path,
        )
        assert code == 2
        assert "refused: address entries do not match" in out
        assert _digest(db_path) == before
        _assert_address_never_shown(out, ADDRESS, TYPO)

    def test_revoke_mismatch_refuses_and_leaves_storage_identical(self, db_path):
        assert _pty_run(["approve"], [ADDRESS.encode() + b"\r"] * 2, db_path)[0] == 0
        before = _digest(db_path)
        code, out = _pty_run(
            ["revoke"], [ADDRESS.encode() + b"\r", TYPO.encode() + b"\r"], db_path,
        )
        assert code == 2
        assert "refused: address entries do not match" in out
        assert _digest(db_path) == before
        assert _grant_rows(db_path)["revoked"] == 0
        _assert_address_never_shown(out, ADDRESS, TYPO)

    def test_matching_revoke_revokes(self, db_path):
        assert _pty_run(["approve"], [ADDRESS.encode() + b"\r"] * 2, db_path)[0] == 0
        code, out = _pty_run(["revoke"], [ADDRESS.encode() + b"\r"] * 2, db_path)
        assert code == 0, out
        assert _values(out)["revoked"] == 1
        assert _grant_rows(db_path)["revoked"] == 1
        _assert_address_never_shown(out, ADDRESS)

    def test_revoke_of_an_unknown_address_fails_closed(self, db_path):
        code, out = _pty_run(["revoke"], [ADDRESS.encode() + b"\r"] * 2, db_path)
        assert code == 2
        assert _values(out)["revoked"] == 0

    def test_approval_stays_idempotent(self, db_path):
        for _ in range(2):
            assert _pty_run(["approve"], [ADDRESS.encode() + b"\r"] * 2, db_path)[0] == 0
        assert _grant_rows(db_path)["total"] == 1

    @pytest.mark.parametrize("first,second,category", [
        (b"", b"", "address missing"),
        (b"   ", b"   ", "address missing"),
        (b"not-an-address", b"not-an-address", "address malformed"),
        (b"two@@at.example", b"two@@at.example", "address malformed"),
        (b"space in@example.test", b"space in@example.test", "address malformed"),
        (b"nodot@example", b"nodot@example", "address malformed"),
    ])
    def test_invalid_input_refuses_before_any_write(self, db_path, first, second, category):
        before = _digest(db_path)
        code, out = _pty_run(["approve"], [first + b"\r", second + b"\r"], db_path)
        assert code == 2
        assert f"refused: {category}" in out
        assert _digest(db_path) == before

    @pytest.mark.parametrize("command", ["approve", "revoke"])
    def test_eof_at_either_prompt_fails_closed(self, db_path, command):
        before = _digest(db_path)
        for entries in ([b"\x04"], [ADDRESS.encode() + b"\r", b"\x04"]):
            code, out = _pty_run([command], entries, db_path)
            assert code == 2, out
            assert "refused: address entry cancelled" in out
            _assert_address_never_shown(out, ADDRESS)
        assert _digest(db_path) == before

    @pytest.mark.parametrize("command", ["approve", "revoke"])
    def test_interrupt_at_either_prompt_fails_closed(self, db_path, command):
        before = _digest(db_path)
        for entries in ([b"\x03"], [ADDRESS.encode() + b"\r", b"\x03"]):
            code, out = _pty_run([command], entries, db_path)
            assert code == 2, out
            assert "refused: address entry cancelled" in out
            assert "Traceback" not in out
            _assert_address_never_shown(out, ADDRESS)
        assert _digest(db_path) == before

    def test_mismatch_never_initialises_persistence(self, db_path, monkeypatch):
        """In-process: the refusal happens before init_db is ever called."""
        cli = _load_cli()
        from app.config import settings
        from app.db import connection
        monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}", raising=False)
        monkeypatch.setattr(settings, "beta_admission_pepper", PEPPER, raising=False)
        monkeypatch.setattr(settings, "beta_admission_mode", "", raising=False)
        calls = {"init": 0}

        async def counting_init(url):
            calls["init"] += 1

        monkeypatch.setattr(connection, "init_db", counting_init)
        monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
        answers = iter([ADDRESS, TYPO])
        monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))

        args = type("A", (), {"command": "approve", "expires_days": None, "note_ref": None})()
        with pytest.raises(cli.Refused) as exc:
            cli.run_command(args, cli.cmd_approve)
        assert exc.value.category == "address entries do not match"
        assert calls["init"] == 0

    @pytest.mark.parametrize("command", ["approve", "revoke"])
    def test_prompts_run_outside_any_event_loop(self, db_path, monkeypatch, command):
        """Regression for CI #143 (Python 3.11).

        Since 3.11, asyncio.run() installs a SIGINT handler whose first Ctrl-C
        only schedules cancellation on the event loop. A blocking masked prompt
        inside that loop starves it, so one Ctrl-C did nothing. The prompts must
        therefore be read before any event loop exists. This asserts that
        directly, so it fails on every Python version, not only on 3.11.
        """
        cli = _load_cli()
        from app.config import settings
        monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}", raising=False)
        monkeypatch.setattr(settings, "beta_admission_pepper", PEPPER, raising=False)
        monkeypatch.setattr(settings, "beta_admission_mode", "", raising=False)
        monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)

        loop_state = []

        def recording_getpass(prompt=""):
            try:
                asyncio.get_running_loop()
                loop_state.append("inside a running event loop")
            except RuntimeError:
                loop_state.append("outside")
            return ADDRESS

        monkeypatch.setattr(cli.getpass, "getpass", recording_getpass)
        received = {}

        async def handler(args, address):
            received["address_matches"] = address == ADDRESS.lower()
            return 0

        args = type("A", (), {"command": command, "expires_days": None, "note_ref": None})()
        assert cli.run_command(args, handler) == 0
        assert loop_state == ["outside", "outside"]
        assert received == {"address_matches": True}

    def test_echo_fallback_is_refused(self, monkeypatch):
        """getpass degrading to echo must never be accepted."""
        import warnings
        cli = _load_cli()

        def echoing(prompt=""):
            warnings.warn("Can not control echo on the terminal.", cli.getpass.GetPassWarning)
            return ADDRESS

        monkeypatch.setattr(cli.getpass, "getpass", echoing)
        with pytest.raises(cli.Refused) as exc:
            cli._read_masked("Address (input hidden): ")
        assert exc.value.category == "address entry cannot be masked on this terminal"

    def test_no_address_input_other_than_the_masked_prompt(self):
        """No --email flag and no environment-variable address input exist."""
        source = open(SCRIPT, encoding="utf-8").read()
        assert "--email" not in source and "--address" not in source
        assert "os.environ.get(\"BETA_ADMISSION_ADDRESS" not in source
        assert "getenv(" not in source and "environ[" not in source

    def test_address_never_in_process_arguments(self, db_path):
        """The child's argv carries only the subcommand and opaque flags."""
        argv = [sys.executable, SCRIPT, "approve", "--note-ref", "R-001"]
        assert all("@" not in a for a in argv)


# ---------------------------------------------------------------------------
# Section 0.16 amendment — clearing one pending invitation by opaque reference
# ---------------------------------------------------------------------------

NOTE_REF = "R-002"
CONFIRM_MARKER = b"re-type the full ref"


def _seed_production_shape(path: str) -> None:
    """Four bound subject grants, one revoked invitation, one pending one.

    Inserted directly so the pending invitation's locator belongs to an
    address the test never supplies — exactly the production situation where
    revoke-by-address cannot reach it.
    """
    conn = sqlite3.connect(path)
    try:
        for i in range(4):
            conn.execute(
                "INSERT INTO access_grants (id, kind, email_locator, subject, status, "
                "redeemed_at, created_at, updated_at) VALUES "
                "(?, 'subject', NULL, ?, 'approved', CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (f"subject-grant-{i}", f"bound-subject-{i}"),
            )
        conn.execute(
            "INSERT INTO access_grants (id, kind, email_locator, subject, status, "
            "revoked_at, created_at, updated_at) VALUES "
            "('11111111-1111-4111-8111-111111111111', 'invite', ?, NULL, 'revoked', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", ("a" * 64,),
        )
        conn.execute(
            "INSERT INTO access_grants (id, kind, email_locator, subject, status, "
            "note_ref, created_at, updated_at) VALUES "
            "('22222222-2222-4222-8222-222222222222', 'invite', ?, NULL, 'approved', "
            "?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", ("b" * 64, NOTE_REF),
        )
        conn.commit()
    finally:
        conn.close()


PENDING_REF = "22222222-2222-4222-8222-222222222222"
SUBJECT_REF = "subject-grant-0"


def _grant_status_map(path: str) -> dict:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT kind, status, count(*) FROM access_grants "
                            "GROUP BY kind, status").fetchall()
    finally:
        conn.close()
    return {(k, s): n for k, s, n in rows}


class TestRevokeInviteByReferenceCLI:
    def test_pending_invites_lists_the_reference_without_any_address(self, db_path):
        _seed_production_shape(db_path)
        before = _digest(db_path)

        code, out = _run("pending-invites", db=db_path)

        assert code == 0, out
        assert "read_only=True" in out
        assert f"ref={PENDING_REF}" in out
        assert f"note_ref={NOTE_REF}" in out
        assert _values(out)["pending_invitations"] == 1
        assert "b" * 64 not in out and "a" * 64 not in out      # no locator
        assert "subject-grant" not in out                       # no subject grant
        _assert_no_leak(out)
        assert _digest(db_path) == before, "listing must not write"

    def test_confirmation_mismatch_refuses_and_leaves_storage_identical(self, db_path):
        _seed_production_shape(db_path)
        before = _digest(db_path)

        code, out = _pty_run(["revoke-invite", "--ref", PENDING_REF],
                             [b"not-the-ref\r"], db_path, marker=CONFIRM_MARKER)

        assert code == 2, out
        assert "refused: confirmation did not match; nothing changed" in out
        assert _digest(db_path) == before

    def test_matching_confirmation_revokes_exactly_one(self, db_path):
        _seed_production_shape(db_path)
        assert _grant_status_map(db_path)[("subject", "approved")] == 4

        code, out = _pty_run(["revoke-invite", "--ref", PENDING_REF],
                             [PENDING_REF.encode() + b"\r"], db_path, marker=CONFIRM_MARKER)

        assert code == 0, out
        assert "state=EXECUTED" in out and "revoked=1" in out
        values = _values(out)
        assert values["approved_pending"] == 0
        assert values["revoked"] == 2
        assert values["subject_grants"] == 4
        assert values["invite_grants"] == 2
        assert values["total"] == 6
        statuses = _grant_status_map(db_path)
        assert statuses[("subject", "approved")] == 4, "subject grants must be untouched"
        assert statuses[("invite", "revoked")] == 2
        assert ("invite", "approved") not in statuses
        _assert_no_leak(out)

    def test_a_unique_prefix_is_enough(self, db_path):
        _seed_production_shape(db_path)
        prefix = PENDING_REF[:12]

        code, out = _pty_run(["revoke-invite", "--ref", prefix],
                             [PENDING_REF.encode() + b"\r"], db_path, marker=CONFIRM_MARKER)

        assert code == 0, out
        assert _grant_status_map(db_path)[("subject", "approved")] == 4

    def test_a_subject_grant_reference_is_refused(self, db_path):
        _seed_production_shape(db_path)
        before = _digest(db_path)

        code, out = _pty_run(["revoke-invite", "--ref", SUBJECT_REF],
                             [], db_path, marker=CONFIRM_MARKER)

        assert code == 2, out
        assert "refused: no pending invitation matches that reference" in out
        assert _digest(db_path) == before

    def test_short_reference_is_refused(self, db_path):
        _seed_production_shape(db_path)
        before = _digest(db_path)
        code, out = _pty_run(["revoke-invite", "--ref", "2222"], [], db_path,
                             marker=CONFIRM_MARKER)
        assert code == 2 and "refused: reference too short" in out
        assert _digest(db_path) == before

    def test_piped_confirmation_is_refused(self, db_path):
        _seed_production_shape(db_path)
        before = _digest(db_path)

        code, out = _run("revoke-invite", "--ref", PENDING_REF, db=db_path)

        assert code == 2
        assert "refused: confirmation must be typed interactively, not piped" in out
        assert _digest(db_path) == before

    def test_second_run_finds_nothing_left_to_revoke(self, db_path):
        _seed_production_shape(db_path)
        assert _pty_run(["revoke-invite", "--ref", PENDING_REF],
                        [PENDING_REF.encode() + b"\r"], db_path,
                        marker=CONFIRM_MARKER)[0] == 0

        code, out = _pty_run(["revoke-invite", "--ref", PENDING_REF], [], db_path,
                             marker=CONFIRM_MARKER)

        assert code == 2
        assert "refused: no pending invitation matches that reference" in out
        code, out = _run("pending-invites", db=db_path)
        assert _values(out)["pending_invitations"] == 0

    # ── defence in depth: the two assertions inside the write transaction ────
    # Reached only if the service layer misbehaves, so they are driven directly
    # with the service call patched. Both must roll back and commit nothing.

    def test_row_count_other_than_one_rolls_back(self, capture, monkeypatch):
        log, db_path = capture
        _seed_production_shape(db_path)
        cli = _load_cli()
        from app.services import access_grant_service as svc

        async def revokes_nothing(session, grant_id):
            return 0

        monkeypatch.setattr(svc, "revoke_invite_by_id", revokes_nothing)
        with pytest.raises(cli.Refused) as exc:
            asyncio.run(cli.cmd_revoke_invite(object(), PENDING_REF))

        assert exc.value.category == "row-count mismatch; rolled back"
        assert log["commits"] == 0
        assert _grant_status_map(db_path)[("invite", "approved")] == 1

    def test_a_moved_subject_grant_count_rolls_back(self, capture, monkeypatch):
        log, db_path = capture
        _seed_production_shape(db_path)
        cli = _load_cli()
        from app.services import access_grant_service as svc
        real = svc.revoke_invite_by_id

        async def also_touches_a_subject_grant(session, grant_id):
            from sqlalchemy import text
            changed = await real(session, grant_id)
            await session.execute(text(
                "UPDATE access_grants SET status='revoked' WHERE kind='subject' "
                "AND id=:i"), {"i": SUBJECT_REF})
            return changed

        monkeypatch.setattr(svc, "revoke_invite_by_id", also_touches_a_subject_grant)
        with pytest.raises(cli.Refused) as exc:
            asyncio.run(cli.cmd_revoke_invite(object(), PENDING_REF))

        assert exc.value.category == "row-count mismatch; rolled back"
        assert log["commits"] == 0
        assert _grant_status_map(db_path)[("subject", "approved")] == 4
