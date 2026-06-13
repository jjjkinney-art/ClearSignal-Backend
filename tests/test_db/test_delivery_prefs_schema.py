"""
Phase 10C · Slice 2 — Delivery Preferences Schema tests.

Covers (schema-only; no delivery behavior):
  - migration idempotency (create_all twice is a no-op)
  - table creation (3 new tables exist)
  - indexes present on the new tables
  - prefs round-trip (get_or_create + update, safe defaults)
  - digest batch round-trip (idempotent on user/channel/bucket)
  - archive round-trip (append-only)
  - delivery_ledger new columns (canonical_severity, severity_rank)
  - canonical severity values persist correctly (via severity_model)
  - defaults are safe (mirror settings.delivery_* globals)

All tests use the in-memory SQLite db_session fixture from tests/test_db/conftest.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from app.db.repositories.delivery_prefs_repo import (
    get_or_create_prefs,
    update_prefs,
    create_digest_batch,
    archive_delivery,
)


NEW_TABLES = ("user_delivery_prefs", "digest_batches", "delivery_ledger_archive")


# ---------------------------------------------------------------------------
# Migration / table creation / indexes
# ---------------------------------------------------------------------------

class TestSchemaCreation:
    @pytest.mark.asyncio
    async def test_new_tables_registered_in_metadata(self):
        from app.db.models import Base
        for t in NEW_TABLES:
            assert t in Base.metadata.tables, f"{t} missing from ORM metadata"

    @pytest.mark.asyncio
    async def test_tables_exist_in_db(self, db_session):
        from sqlalchemy import text
        rows = await db_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
        names = {r[0] for r in rows.all()}
        for t in NEW_TABLES:
            assert t in names, f"{t} not created in DB"

    @pytest.mark.asyncio
    async def test_create_all_is_idempotent(self, db_session):
        # Running create_all again against the same engine must not raise.
        from app.db.models import Base
        engine = db_session.bind
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        # tables still present, single copy each
        from sqlalchemy import text
        rows = await db_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
        names = [r[0] for r in rows.all()]
        for t in NEW_TABLES:
            assert names.count(t) == 1

    @pytest.mark.asyncio
    async def test_indexes_present(self, db_session):
        from sqlalchemy import text
        rows = await db_session.execute(
            text("SELECT name, tbl_name FROM sqlite_master WHERE type='index'")
        )
        idx = {(r[0], r[1]) for r in rows.all()}
        idx_names = {name for name, _ in idx}
        # A representative index per new table (created from ORM index=True / UniqueConstraint)
        tbls_with_index = {tbl for _, tbl in idx}
        for t in NEW_TABLES:
            assert t in tbls_with_index, f"no index found on {t}"
        # delivery_ledger canonical_severity index
        assert "delivery_ledger" in tbls_with_index


# ---------------------------------------------------------------------------
# user_delivery_prefs round-trip + safe defaults
# ---------------------------------------------------------------------------

class TestPrefsRoundTrip:
    @pytest.mark.asyncio
    async def test_get_or_create_safe_defaults(self, db_session):
        prefs = await get_or_create_prefs(db_session, user_id=None, channel="in_app")
        assert prefs is not None
        # Defaults mirror settings.delivery_* globals (safe defaults).
        assert prefs.enabled is True
        assert prefs.min_severity == "info"
        assert prefs.quiet_hours_start == 22
        assert prefs.quiet_hours_end == 7
        assert prefs.timezone == "UTC"
        assert prefs.daily_cap == 20
        assert prefs.mute_until is None
        assert prefs.channel == "in_app"

    @pytest.mark.asyncio
    async def test_get_or_create_is_idempotent(self, db_session):
        a = await get_or_create_prefs(db_session, user_id="u1", channel="in_app")
        b = await get_or_create_prefs(db_session, user_id="u1", channel="in_app")
        assert a.id == b.id  # same row, not a duplicate

    @pytest.mark.asyncio
    async def test_distinct_channels_are_distinct_rows(self, db_session):
        a = await get_or_create_prefs(db_session, user_id="u1", channel="in_app")
        b = await get_or_create_prefs(db_session, user_id="u1", channel="email")
        assert a.id != b.id

    @pytest.mark.asyncio
    async def test_update_prefs_round_trip(self, db_session):
        await update_prefs(
            db_session, user_id="u2", channel="in_app",
            enabled=False, quiet_hours_start=0, quiet_hours_end=6,
            timezone="America/New_York", daily_cap=5,
        )
        prefs = await get_or_create_prefs(db_session, user_id="u2", channel="in_app")
        assert prefs.enabled is False
        assert prefs.quiet_hours_start == 0
        assert prefs.quiet_hours_end == 6
        assert prefs.timezone == "America/New_York"
        assert prefs.daily_cap == 5

    @pytest.mark.asyncio
    async def test_update_ignores_unknown_fields(self, db_session):
        prefs = await update_prefs(
            db_session, user_id="u3", channel="in_app",
            not_a_field="x", id="hacked", user_id_override="y",
        )
        assert prefs is not None
        assert prefs.user_id == "u3"
        assert prefs.id != "hacked"

    @pytest.mark.asyncio
    async def test_mute_until_persists(self, db_session):
        when = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)
        await update_prefs(db_session, user_id="u4", channel="in_app", mute_until=when)
        prefs = await get_or_create_prefs(db_session, user_id="u4", channel="in_app")
        assert prefs.mute_until is not None

    @pytest.mark.asyncio
    async def test_null_session_safe(self):
        assert await get_or_create_prefs(None, user_id="u") is None
        assert await update_prefs(None, user_id="u", enabled=False) is None


# ---------------------------------------------------------------------------
# canonical severity values persist correctly
# ---------------------------------------------------------------------------

class TestSeverityPersistence:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw,expected", [
        ("critical", "critical"),
        ("high",     "high"),
        ("medium",   "medium"),
        ("low",      "low"),
        ("info",     "info"),
        ("warning",  "medium"),   # legacy delivery vocab → canonical (severity_model)
        ("alert",    "high"),
        ("ignore",   "info"),
        ("bogus",    "info"),     # unknown fails low
    ])
    async def test_min_severity_normalized_and_persisted(self, db_session, raw, expected):
        await update_prefs(db_session, user_id=f"sev-{raw}", channel="in_app", min_severity=raw)
        prefs = await get_or_create_prefs(db_session, user_id=f"sev-{raw}", channel="in_app")
        assert prefs.min_severity == expected


# ---------------------------------------------------------------------------
# digest_batches round-trip
# ---------------------------------------------------------------------------

class TestDigestBatchRoundTrip:
    @pytest.mark.asyncio
    async def test_create_and_read(self, db_session):
        batch = await create_digest_batch(
            db_session, user_id="d1", period_bucket="2026-06-13",
            item_count=3, payload_json={"items": ["a", "b", "c"]},
            content_key="ck1",
        )
        assert batch is not None
        assert batch.status == "open"
        assert batch.item_count == 3
        assert batch.payload_json == {"items": ["a", "b", "c"]}
        assert batch.content_key == "ck1"

    @pytest.mark.asyncio
    async def test_idempotent_on_user_channel_bucket(self, db_session):
        a = await create_digest_batch(db_session, user_id="d2", period_bucket="2026-06-13")
        b = await create_digest_batch(db_session, user_id="d2", period_bucket="2026-06-13")
        assert a.id == b.id  # same batch, append-idempotent

    @pytest.mark.asyncio
    async def test_distinct_buckets_distinct_rows(self, db_session):
        a = await create_digest_batch(db_session, user_id="d3", period_bucket="2026-06-13")
        b = await create_digest_batch(db_session, user_id="d3", period_bucket="2026-06-14")
        assert a.id != b.id

    @pytest.mark.asyncio
    async def test_default_payload_is_empty_dict(self, db_session):
        batch = await create_digest_batch(db_session, user_id="d4", period_bucket="2026-06-13")
        assert batch.payload_json == {}
        assert batch.item_count == 0

    @pytest.mark.asyncio
    async def test_null_session_safe(self):
        assert await create_digest_batch(None, user_id="d", period_bucket="2026-06-13") is None


# ---------------------------------------------------------------------------
# delivery_ledger_archive round-trip (append-only)
# ---------------------------------------------------------------------------

class TestArchiveRoundTrip:
    @pytest.mark.asyncio
    async def test_archive_append(self, db_session):
        row = await archive_delivery(
            db_session,
            original_delivery_id="del-1", user_id="a1", channel="in_app",
            target_key="AAPL", status="delivered",
            payload_json={"k": "v"}, content_key="ck-archive-1",
        )
        assert row is not None
        assert row.original_delivery_id == "del-1"
        assert row.target_key == "AAPL"
        assert row.status == "delivered"
        assert row.payload_json == {"k": "v"}
        assert row.archived_at is not None

    @pytest.mark.asyncio
    async def test_archive_is_append_only_multiple_rows(self, db_session):
        from app.db.models import DeliveryLedgerArchive
        from sqlalchemy import select, func
        for i in range(3):
            await archive_delivery(
                db_session, original_delivery_id=f"del-{i}", user_id="a2",
                content_key=f"ck-{i}",
            )
        count = (await db_session.execute(
            select(func.count()).select_from(DeliveryLedgerArchive)
            .where(DeliveryLedgerArchive.user_id == "a2")
        )).scalar()
        assert count == 3

    @pytest.mark.asyncio
    async def test_default_payload_is_empty_dict(self, db_session):
        row = await archive_delivery(db_session, original_delivery_id="del-x")
        assert row.payload_json == {}

    @pytest.mark.asyncio
    async def test_null_session_safe(self):
        assert await archive_delivery(None, original_delivery_id="x") is None


# ---------------------------------------------------------------------------
# delivery_ledger additive columns
# ---------------------------------------------------------------------------

class TestDeliveryLedgerNewColumns:
    @pytest.mark.asyncio
    async def test_columns_exist_and_default_null(self, db_session):
        from app.db.models import DeliveryLedger
        from sqlalchemy import select

        row = DeliveryLedger(
            content_key="ledger-ck-1", target_key="AAPL",
            channel="in_app", content_hash="h1", status="pending",
        )
        db_session.add(row)
        await db_session.flush()

        fetched = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.content_key == "ledger-ck-1")
        )).scalar_one()
        # Additive columns default to NULL (no rewrite of existing semantics).
        assert fetched.canonical_severity is None
        assert fetched.severity_rank is None

    @pytest.mark.asyncio
    async def test_canonical_severity_persists(self, db_session):
        from app.db.models import DeliveryLedger
        from app.services.severity_model import to_canonical_severity, severity_rank
        from sqlalchemy import select

        canon = to_canonical_severity("alert")   # → "high"
        row = DeliveryLedger(
            content_key="ledger-ck-2", target_key="MSFT",
            channel="in_app", content_hash="h2", status="pending",
            canonical_severity=canon, severity_rank=severity_rank(canon),
        )
        db_session.add(row)
        await db_session.flush()

        fetched = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.content_key == "ledger-ck-2")
        )).scalar_one()
        assert fetched.canonical_severity == "high"
        assert fetched.severity_rank == 3
