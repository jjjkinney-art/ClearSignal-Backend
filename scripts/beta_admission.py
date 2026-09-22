#!/usr/bin/env python3
"""Operator tool for controlled-beta admission grants — Section 0.15.

    python3 scripts/beta_admission.py status
    python3 scripts/beta_admission.py approve [--expires-days N] [--note-ref REF]
    python3 scripts/beta_admission.py revoke
    python3 scripts/beta_admission.py grandfather-existing [--execute]

Persistence
-----------
The tool initialises persistence through the APPLICATION'S OWN path:
``app.config.settings.database_url`` → ``app.db.init_db`` → the application's
session factory. There is no second configuration system and no URL parsing
here.

An earlier revision imported ``get_session`` without ever calling
``init_db``. ``get_session`` yields ``None`` until the engine exists, and only
the FastAPI lifespan created it, so every command refused with "persistence
unavailable" against a perfectly healthy production database.

Refusal order — nothing reaches a business SELECT until every step passes
------------------------------------------------------------------------------
  1. admission configuration valid (mode resolvable)
  2. pepper present and strong enough
  3. DATABASE_URL configured
  4. engine and session factory initialised
  5. transaction opened; for read-only commands, READ ONLY verified
  6. schema present: alembic_version populated, users + access_grants exist

Privacy
-------
* An email address is NEVER a command-line argument or environment variable.
  `approve` and `revoke` read it TWICE from masked prompts, refuse on any
  mismatch before touching the database, and hash it immediately. A single
  masked entry would hide a typo, and a typo is a live grant for someone
  else's address.
* Output is counts, booleans, the admission mode, the dry-run/executed state
  and an opaque per-run operation reference. Never an address, identity,
  subject, locator, token, credential or database URL.
* Application and driver logging is silenced for the run, because the
  persistence layer logs the database host at INFO and exception reprs on
  failure. Every failure is reported as a fixed category word only.

Exit codes: 0 ok · 2 refused/failed · 3 usage error.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Refused(Exception):
    """A guard failed. ``category`` is a fixed word, never derived from input."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _silence_logging() -> None:
    """Stop the persistence layer and drivers from printing connection details."""
    for name in ("app", "sqlalchemy", "asyncpg", "aiosqlite", "alembic"):
        logging.getLogger(name).setLevel(logging.CRITICAL + 1)
    logging.getLogger().setLevel(logging.CRITICAL + 1)


def _operation_ref() -> str:
    """Opaque, random, per-run reference. Derived from nothing."""
    return uuid.uuid4().hex[:12]


_ADDRESS_MAX_LENGTH = 320


def _read_masked(prompt: str) -> str:
    """One masked read. Refuses rather than ever falling back to echo.

    ``getpass`` silently degrades to reading with echo ON when it cannot
    control the terminal, emitting only a GetPassWarning. That would put the
    address on screen and in any terminal recording, so the warning is turned
    into a refusal.
    """
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass(prompt)
    except getpass.GetPassWarning:
        raise Refused("address entry cannot be masked on this terminal")
    except (EOFError, KeyboardInterrupt):
        raise Refused("address entry cancelled")


def _address_well_formed(value: str) -> bool:
    """A shape check only. It never reveals why an address was rejected."""
    if not value or len(value) > _ADDRESS_MAX_LENGTH:
        return False
    if any(ch.isspace() for ch in value) or value.count("@") != 1:
        return False
    local, domain = value.split("@")
    return bool(local) and "." in domain and not domain.startswith(".") \
        and not domain.endswith(".") and ".." not in domain


def _prompt_confirmed_email(purpose: str) -> str:
    """Read the address twice, masked, and return it only if both agree.

    Neither entry is ever echoed, printed, logged or placed in an exception.
    Both are captured before either is normalised, and the comparison is
    made on the normalised form the locator itself uses. Every failure is a
    fixed-word refusal raised BEFORE any database work begins, so a refused
    run never opens a connection, let alone a write transaction.
    """
    if not sys.stdin.isatty():
        raise Refused("address must be typed interactively, not piped")

    first = _read_masked(f"Address to {purpose} (input hidden): ")
    second = _read_masked(f"Confirm address to {purpose} (input hidden): ")

    from app.services.access_grant_service import normalize_email
    a, b = normalize_email(first), normalize_email(second)
    del first, second

    if not a or not b:
        raise Refused("address missing")
    if a != b:
        raise Refused("address entries do not match")
    if not _address_well_formed(a):
        raise Refused("address malformed")
    return a


def _preflight_config() -> str:
    """Steps 1–3. Pure configuration checks: no connection is attempted."""
    from app.config import (
        AdmissionConfigError, admission_pepper_ok, settings, validate_admission_config,
    )
    try:
        mode = validate_admission_config(settings)
    except AdmissionConfigError:
        raise Refused("admission configuration invalid")
    if not admission_pepper_ok(getattr(settings, "beta_admission_pepper", "")):
        raise Refused("pepper not configured")
    if not (getattr(settings, "database_url", "") or "").strip():
        raise Refused("persistence unavailable: database not configured")
    return mode


async def _verify_read_only(session, dialect: str) -> None:
    """Step 5 for read-only commands. The first statement of the transaction."""
    from sqlalchemy import text
    if dialect == "postgresql":
        await session.execute(text("SET TRANSACTION READ ONLY"))
        state = (await session.execute(text("SHOW transaction_read_only"))).scalar()
        if str(state).lower() != "on":
            raise Refused("read-only transaction could not be verified")
    elif dialect == "sqlite":
        await session.execute(text("PRAGMA query_only = ON"))
        state = (await session.execute(text("PRAGMA query_only"))).scalar()
        if int(state or 0) != 1:
            raise Refused("read-only transaction could not be verified")
    else:
        # Not knowing whether a read-only guard is in force is the same as
        # not having one.
        raise Refused("read-only transaction could not be verified")


def _code_head() -> str:
    """The Alembic head revision shipped with this checkout. Reads files only."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if len(heads) != 1:
        raise Refused("schema unavailable")
    return heads[0]


async def _verify_schema(session) -> None:
    """Step 6. Metadata only; no business table is read."""
    from sqlalchemy import text

    try:
        version = (await session.execute(
            text("SELECT version_num FROM alembic_version")
        )).scalar()
    except Exception:
        raise Refused("schema unavailable")
    if not version:
        raise Refused("schema unavailable")

    # Table presence alone is NOT proof of migration: 0001_baseline adopts the
    # full current model schema, so a database several revisions behind can
    # still contain access_grants. The database must be at exactly the head
    # revision shipped with THIS code — the same file set the deploy ran.
    if version != _code_head():
        raise Refused("schema unavailable")

    def _tables(sync_conn):
        from sqlalchemy import inspect
        names = set(inspect(sync_conn).get_table_names())
        return {"users", "access_grants"} <= names

    conn = await session.connection()
    if not await conn.run_sync(_tables):
        raise Refused("schema unavailable")


@asynccontextmanager
async def open_session(*, read_only: bool):
    """Yield a guarded session. Never commits: the caller decides, explicitly.

    Always rolls back what it did not explicitly commit, and always disposes
    the engine, on every path.
    """
    mode = _preflight_config()

    from app.config import settings
    from app.db.connection import close_db, get_session_factory, init_db

    await init_db(settings.database_url)
    try:
        factory = get_session_factory()
        if factory is None:
            raise Refused("persistence unavailable: engine not initialised")

        session = factory()
        try:
            try:
                dialect = session.bind.dialect.name
            except Exception:
                raise Refused("persistence unavailable: engine not initialised")
            try:
                if read_only:
                    await _verify_read_only(session, dialect)
                await _verify_schema(session)
            except Refused:
                raise
            except Exception:
                raise Refused("persistence unavailable: connection failed")
            yield session, mode
        finally:
            try:
                await session.rollback()
            finally:
                await session.close()
    finally:
        await close_db()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _print_block(title: str, values: dict) -> None:
    print(title)
    for key in sorted(values):
        print(f"  {key:<22} {values[key]}")


async def cmd_status(_args) -> int:
    from app.services.access_grant_service import grant_status_counts
    op = _operation_ref()
    async with open_session(read_only=True) as (session, mode):
        counts = await grant_status_counts(session)
    _print_block(f"status  operation_ref={op}  mode={mode}  read_only=True", counts)
    return 0


async def cmd_grandfather(args) -> int:
    """Authorise today's identities BY SUBJECT. Dry run unless --execute."""
    from app.services.access_grant_service import (
        count_subject_grants, grandfather_existing_subjects, plan_grandfather,
    )
    op = _operation_ref()

    if not args.execute:
        async with open_session(read_only=True) as (session, mode):
            plan = await plan_grandfather(session)
        _print_block(
            f"grandfather-existing  operation_ref={op}  mode={mode}  "
            f"state=DRY-RUN  read_only=True  written=0",
            plan,
        )
        print("  nothing written — pass --execute to commit")
        return 0

    async with open_session(read_only=False) as (session, mode):
        plan = await plan_grandfather(session)
        before = await count_subject_grants(session)
        result = await grandfather_existing_subjects(session, note_ref=args.note_ref)
        await session.flush()
        after = await count_subject_grants(session)

        delta = after - before
        if not (result["granted"] == plan["would_grant"] == delta):
            # open_session rolls back on exit: nothing partial survives.
            raise Refused("row-count mismatch; rolled back")
        await session.commit()

    _print_block(
        f"grandfather-existing  operation_ref={op}  mode={mode}  "
        f"state=EXECUTED  committed=True",
        {
            "examined": result["examined"],
            "granted": result["granted"],
            "already_granted": result["already_granted"],
            "skipped_unbound": result["skipped_unbound"],
            "subject_grants_after": after,
        },
    )
    return 0


async def cmd_approve(args) -> int:
    from app.services.access_grant_service import create_invite_grant, grant_status_counts
    op = _operation_ref()
    _preflight_config()                       # refuse before prompting
    # Both entries are captured and compared before any connection exists.
    address = _prompt_confirmed_email("approve")
    expires_at = None
    if args.expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=args.expires_days)

    async with open_session(read_only=False) as (session, mode):
        before = (await grant_status_counts(session))["approved_pending"]
        grant_id = await create_invite_grant(
            session, raw_email=address, expires_at=expires_at, note_ref=args.note_ref,
        )
        del address
        if grant_id is None:
            raise Refused("no grant created")
        await session.flush()
        after = (await grant_status_counts(session))["approved_pending"]
        if after not in (before, before + 1):     # +1 new, or reused an existing one
            raise Refused("row-count mismatch; rolled back")
        await session.commit()
    _print_block(
        f"approve  operation_ref={op}  mode={mode}  state=EXECUTED  committed=True",
        {"approved_pending": after, "created": after - before},
    )
    return 0


async def cmd_revoke(_args) -> int:
    from app.services.access_grant_service import revoke_grant
    op = _operation_ref()
    _preflight_config()
    # Both entries are captured and compared before any connection exists.
    address = _prompt_confirmed_email("revoke")
    async with open_session(read_only=False) as (session, mode):
        revoked = await revoke_grant(session, raw_email=address)
        del address
        await session.commit()
    _print_block(
        f"revoke  operation_ref={op}  mode={mode}  state=EXECUTED  committed=True",
        {"revoked": revoked},
    )
    return 0 if revoked else 2


def main() -> int:
    _silence_logging()
    parser = argparse.ArgumentParser(description="Controlled-beta admission grants")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="aggregate grant counts (read-only)")

    approve = sub.add_parser("approve", help="approve an address (masked prompt)")
    approve.add_argument("--expires-days", type=int, default=None)
    approve.add_argument("--note-ref", default=None, help="opaque ledger reference")

    sub.add_parser("revoke", help="revoke by address (masked prompt)")

    grandfather = sub.add_parser(
        "grandfather-existing",
        help="grant every already-bound identity, by subject (read-only dry run by default)",
    )
    grandfather.add_argument("--execute", action="store_true")
    grandfather.add_argument("--note-ref", default=None)

    args = parser.parse_args()
    handlers = {
        "status": cmd_status,
        "approve": cmd_approve,
        "revoke": cmd_revoke,
        "grandfather-existing": cmd_grandfather,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 3
    try:
        return asyncio.run(handler(args))
    except Refused as refusal:
        print(f"refused: {refusal.category}")
        return 2
    except KeyboardInterrupt:
        return 3
    except Exception as exc:
        # Sanitised: type only. A driver error must not echo a DSN or host.
        print(f"failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
