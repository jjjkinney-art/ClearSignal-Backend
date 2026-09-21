#!/usr/bin/env python3
"""Operator tool for controlled-beta admission grants — Section 0.15.

    python3 scripts/beta_admission.py status
    python3 scripts/beta_admission.py approve [--expires-days N] [--note-ref REF]
    python3 scripts/beta_admission.py revoke
    python3 scripts/beta_admission.py grandfather-existing [--execute]

Privacy rules this tool obeys
-----------------------------
* An email address is NEVER a command-line argument. `approve` and `revoke`
  read it from a masked prompt (no echo) and hash it immediately.
* No address, identity, user id or locator is ever printed or logged.
* Output is aggregate counts and opaque references only.
* `grandfather-existing` is a DRY RUN unless --execute is passed, and reads
  the existing identities out of the database at run time: no production
  identity is written into source, tests or documentation.

Connection
----------
DATABASE_URL comes from the environment, exactly as the application reads it.
It is never printed, and never taken as an argument.

Exit codes: 0 ok · 2 refused/failed · 3 usage error.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _prompt_email(purpose: str) -> str:
    """Read an address without echoing it. Never returned to stdout."""
    if not sys.stdin.isatty():
        print("refused: an address must be typed interactively, not piped")
        return ""
    value = getpass.getpass(f"Address to {purpose} (input hidden): ").strip()
    return value


async def _session():
    from app.db.connection import get_session
    return get_session()


async def cmd_status(_args) -> int:
    from app.services.access_grant_service import grant_status_counts
    async with (await _session()) as session:
        if session is None:
            print("refused: persistence unavailable")
            return 2
        counts = await grant_status_counts(session)
    for key in sorted(counts):
        print(f"  {key:<20} {counts[key]}")
    return 0


async def cmd_approve(args) -> int:
    from app.services.access_grant_service import create_invite_grant, grant_status_counts
    address = _prompt_email("approve")
    if not address:
        return 3
    expires_at = None
    if args.expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=args.expires_days)

    async with (await _session()) as session:
        if session is None:
            print("refused: persistence unavailable")
            return 2
        grant_id = await create_invite_grant(
            session, raw_email=address, expires_at=expires_at, note_ref=args.note_ref,
        )
        del address
        if grant_id is None:
            print("refused: no grant created")
            return 2
        await session.commit()
        counts = await grant_status_counts(session)
    # The grant id is an opaque random UUID, not derived from the address.
    print(f"grant recorded: {grant_id}")
    print(f"  approved_pending now {counts['approved_pending']}")
    return 0


async def cmd_revoke(args) -> int:
    from app.services.access_grant_service import revoke_grant, grant_status_counts
    address = _prompt_email("revoke")
    if not address:
        return 3
    async with (await _session()) as session:
        if session is None:
            print("refused: persistence unavailable")
            return 2
        revoked = await revoke_grant(session, raw_email=address)
        del address
        await session.commit()
        counts = await grant_status_counts(session)
    print(f"grants revoked: {revoked}")
    print(f"  revoked now {counts['revoked']}")
    return 0 if revoked else 2


async def cmd_grandfather(args) -> int:
    """Authorise the identities that already exist, by subject, never by email."""
    from app.services.access_grant_service import (
        grandfather_existing_subjects, grant_status_counts,
    )
    async with (await _session()) as session:
        if session is None:
            print("refused: persistence unavailable")
            return 2
        result = await grandfather_existing_subjects(session, note_ref=args.note_ref)
        if args.execute:
            await session.commit()
            print("committed")
        else:
            await session.rollback()
            print("DRY RUN — nothing written (pass --execute to commit)")
        for key in sorted(result):
            print(f"  {key:<20} {result[key]}")
        if not args.execute:
            return 0
        counts = await grant_status_counts(session)
    for key in sorted(counts):
        print(f"  {key:<20} {counts[key]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled-beta admission grants")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="aggregate grant counts")

    approve = sub.add_parser("approve", help="approve an address (masked prompt)")
    approve.add_argument("--expires-days", type=int, default=None)
    approve.add_argument("--note-ref", default=None, help="opaque ledger reference")

    sub.add_parser("revoke", help="revoke by address (masked prompt)")

    grandfather = sub.add_parser(
        "grandfather-existing",
        help="grant every already-bound identity, by subject (dry run by default)",
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
    except KeyboardInterrupt:
        return 3
    except Exception as exc:
        # Sanitised: type only. A connection error must not echo a DSN.
        print(f"failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
