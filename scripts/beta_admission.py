#!/usr/bin/env python3
"""Operator tool for controlled-beta admission grants — Section 0.15.

    python3 scripts/beta_admission.py status
    python3 scripts/beta_admission.py approve [--expires-days N] [--note-ref REF]
    python3 scripts/beta_admission.py revoke
    python3 scripts/beta_admission.py pending-invites
    python3 scripts/beta_admission.py revoke-invite --ref REF
    python3 scripts/beta_admission.py grandfather-existing [--execute]

An invitation can also be cleared WITHOUT its address. `pending-invites`
lists pending invitations by an opaque grant reference (a random UUID) plus
the operator's own --note-ref label, and `revoke-invite` revokes exactly one
of them after a visible typed confirmation. That path exists because a
locator lookup is impossible if the address spelling is unknown or the pepper
was rotated after the invitation was created. It can never select or modify a
subject grant: every guard is in the UPDATE's WHERE clause.

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
from typing import Any, Dict

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

def _aware_date(value) -> str:
    """Date only, for operator display. Never a time, never an identifier."""
    from app.services.access_grant_service import _aware
    value = _aware(value)
    return value.date().isoformat() if value is not None else "-"


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


async def cmd_approve(args, address: str) -> int:
    """Create an invite grant. ``address`` was confirmed by collect_address()."""
    from app.services.access_grant_service import create_invite_grant, grant_status_counts
    op = _operation_ref()
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


async def cmd_pending_invites(_args) -> int:
    """List pending invitations by opaque reference. Read-only."""
    from app.services.access_grant_service import grant_status_counts, list_pending_invites
    op = _operation_ref()
    async with open_session(read_only=True) as (session, mode):
        rows = await list_pending_invites(session)
        counts = await grant_status_counts(session)
    print(f"pending-invites  operation_ref={op}  mode={mode}  read_only=True")
    for row in rows:
        # ref is a random UUID; note_ref is the operator's own ledger label.
        print(f"  ref={row['ref']}  note_ref={row['note_ref'] or '-'}  "
              f"created={row['created']}  expires={row['expires']}")
    print(f"  {'pending_invitations':<22} {len(rows)}")
    print(f"  {'approved_pending':<22} {counts['approved_pending']}")
    return 0


async def preview_invite(args) -> Dict[str, Any]:
    """Stage 1: resolve the reference and read the before-counts. READ-ONLY."""
    from app.services.access_grant_service import grant_status_counts, resolve_pending_invite
    async with open_session(read_only=True) as (session, mode):
        row, state = await resolve_pending_invite(session, args.ref)
        if state != "ok":
            raise Refused({
                "none": "no pending invitation matches that reference",
                "ambiguous": "reference is ambiguous",
                "too_short": "reference too short",
            }[state])
        return {
            "id": str(row.id),
            "note_ref": row.note_ref or "-",
            "created": _aware_date(row.created_at),
            "mode": mode,
            "before": await grant_status_counts(session),
        }


async def cmd_revoke_invite(_args, grant_id: str) -> int:
    """Stage 3: revoke exactly that invitation, in one asserted transaction."""
    from app.services.access_grant_service import (
        count_approved_subject_grants, grant_status_counts, revoke_invite_by_id,
    )
    op = _operation_ref()
    async with open_session(read_only=False) as (session, mode):
        subjects_before = await count_approved_subject_grants(session)
        changed = await revoke_invite_by_id(session, grant_id)
        await session.flush()
        subjects_after = await count_approved_subject_grants(session)
        after = await grant_status_counts(session)
        if changed != 1 or subjects_after != subjects_before:
            # open_session rolls back on the way out: nothing partial survives.
            raise Refused("row-count mismatch; rolled back")
        await session.commit()
    _print_block(
        f"revoke-invite  operation_ref={op}  mode={mode}  state=EXECUTED  "
        f"committed=True  revoked=1",
        after,
    )
    return 0


def run_revoke_invite(args) -> int:
    """Preview, confirm, execute — the confirmation OUTSIDE any event loop.

    The reference is opaque and identifies nobody, so the confirmation is
    deliberately VISIBLE: seeing it is what lets the operator check they are
    revoking the invitation they meant. Hidden entry stays where it belongs,
    on the address prompts of approve/revoke.
    """
    _preflight_config()
    if not sys.stdin.isatty():
        raise Refused("confirmation must be typed interactively, not piped")

    preview = asyncio.run(preview_invite(args))
    print("about to revoke this pending invitation:")
    print(f"  ref={preview['id']}  note_ref={preview['note_ref']}  created={preview['created']}")
    print(f"  approved_pending {preview['before']['approved_pending']}  "
          f"revoked {preview['before']['revoked']}  "
          f"subject_grants {preview['before']['subject_grants']}")
    try:
        typed = input("re-type the full ref to confirm (anything else aborts): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        raise Refused("confirmation cancelled")
    if typed != preview["id"].lower():
        raise Refused("confirmation did not match; nothing changed")
    return asyncio.run(cmd_revoke_invite(args, preview["id"]))


async def cmd_revoke(_args, address: str) -> int:
    """Revoke by address. ``address`` was confirmed by collect_address()."""
    from app.services.access_grant_service import revoke_grant
    op = _operation_ref()
    async with open_session(read_only=False) as (session, mode):
        revoked = await revoke_grant(session, raw_email=address)
        del address
        await session.commit()
    _print_block(
        f"revoke  operation_ref={op}  mode={mode}  state=EXECUTED  committed=True",
        {"revoked": revoked},
    )
    return 0 if revoked else 2


# Commands that need an address typed at the terminal.
ADDRESS_COMMANDS = ("approve", "revoke")


def collect_address(command: str) -> str:
    """Refuse on configuration, then read and confirm the address. Synchronous.

    This MUST run before asyncio.run(), never inside a coroutine. Since
    Python 3.11 asyncio.run() installs its own SIGINT handler whose first
    Ctrl-C only schedules cancellation of the main task on the event loop; a
    blocking getpass() inside that loop never lets the cancellation run, so a
    single Ctrl-C would do nothing (production runs Python 3.11). Outside the
    loop, Ctrl-C raises KeyboardInterrupt in getpass() as the operator expects,
    and every refusal still happens before persistence is initialised.
    """
    _preflight_config()                       # refuse before prompting
    return _prompt_confirmed_email(command)


def run_command(args, handler) -> int:
    """Prompt (if needed) outside any event loop, then run the async handler."""
    if args.command in ADDRESS_COMMANDS:
        address = collect_address(args.command)
        return asyncio.run(handler(args, address))
    return asyncio.run(handler(args))


def main() -> int:
    _silence_logging()
    parser = argparse.ArgumentParser(description="Controlled-beta admission grants")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="aggregate grant counts (read-only)")

    approve = sub.add_parser("approve", help="approve an address (masked prompt)")
    approve.add_argument("--expires-days", type=int, default=None)
    approve.add_argument("--note-ref", default=None, help="opaque ledger reference")

    sub.add_parser("revoke", help="revoke by address (masked prompt)")

    sub.add_parser("pending-invites",
                   help="list pending invitations by opaque reference (read-only)")

    revoke_invite = sub.add_parser(
        "revoke-invite",
        help="revoke ONE pending invitation by its opaque reference",
    )
    revoke_invite.add_argument("--ref", required=True,
                               help="grant reference, or a prefix of at least 8 characters")

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
        "pending-invites": cmd_pending_invites,
        "grandfather-existing": cmd_grandfather,
    }
    handler = handlers.get(args.command)
    if handler is None and args.command != "revoke-invite":
        parser.print_help()
        return 3
    try:
        if args.command == "revoke-invite":
            return run_revoke_invite(args)
        return run_command(args, handler)
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
