"""Sprint 1A — Alembic migration system tests.

Covers the required scenarios:
  * fresh database migration to head
  * existing-schema baselining/stamping
  * upgrade idempotency
  * startup after migration (startup no longer mutates schema)
  * detection of a database behind head
  * preservation of representative rows and relationships across the delta

All tests are SYNC (no running event loop) because alembic's async env.py calls
asyncio.run(); the app-side async calls use asyncio.run() inside the sync test.
Each test uses a throwaway temp SQLite file — no network, no shared DB.
"""
from __future__ import annotations

import asyncio
import os
import tempfile

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Deliberately pinned rather than derived: adding a revision must be an
# explicit, acknowledged change here, not something a test silently absorbs.
_HEAD = "0005_watchlist_unique_active"
_BASELINE = "0001_baseline"
_PRE_BILLING_COLUMNS = "0002_delivery_ledger_severity"
_PRE_PORTFOLIO_ORG_ID = "0003_users_billing_columns"


def _model_table_count() -> int:
    from app.db.models import Base
    return len(Base.metadata.tables)


def _new_db_path() -> str:
    return os.path.join(tempfile.mkdtemp(), "test.db")


def _cfg(path: str) -> Config:
    c = Config(os.path.join(_ROOT, "alembic.ini"))
    c.set_main_option("script_location", os.path.join(_ROOT, "alembic"))
    c.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")
    return c


def _insp(path: str):
    return inspect(create_engine(f"sqlite:///{path}"))


def _rev(path: str):
    with create_engine(f"sqlite:///{path}").connect() as cn:
        return cn.execute(text("SELECT version_num FROM alembic_version")).scalar()


# ─────────────────────────────────────────────────────────────────────────────

class TestFreshDatabase:
    def test_upgrade_head_creates_full_schema(self):
        p = _new_db_path()
        command.upgrade(_cfg(p), "head")
        insp = _insp(p)
        tabs = set(insp.get_table_names())
        assert "alembic_version" in tabs
        assert len(tabs) == _model_table_count() + 1  # +alembic_version
        cols = {c["name"] for c in insp.get_columns("delivery_ledger")}
        assert {"canonical_severity", "severity_rank"} <= cols
        idx = {i["name"] for i in insp.get_indexes("delivery_ledger")}
        assert "ix_delivery_ledger_canonical_severity" in idx
        assert _rev(p) == _HEAD


class TestExistingSchemaBaselining:
    def test_stamp_head_marks_existing_db_without_ddl(self):
        # Simulate a DB created by the OLD startup create_all() path.
        p = _new_db_path()
        from app.db.models import Base
        Base.metadata.create_all(create_engine(f"sqlite:///{p}"))
        before = set(_insp(p).get_table_names())

        command.stamp(_cfg(p), "head")

        after = set(_insp(p).get_table_names())
        # Stamp only records the revision; it adds alembic_version and nothing else.
        assert after - before == {"alembic_version"}
        assert _rev(p) == _HEAD


class TestIdempotency:
    def test_upgrade_head_twice_is_noop(self):
        p = _new_db_path()
        command.upgrade(_cfg(p), "head")
        t1 = set(_insp(p).get_table_names())
        cols1 = {c["name"] for c in _insp(p).get_columns("delivery_ledger")}
        command.upgrade(_cfg(p), "head")  # must not error
        assert set(_insp(p).get_table_names()) == t1
        assert {c["name"] for c in _insp(p).get_columns("delivery_ledger")} == cols1
        assert _rev(p) == _HEAD


class TestLegacyUsersBillingColumns:
    def test_upgrade_repairs_existing_users_table_without_losing_rows(self):
        """Reproduce the production schema drift that blocked first login."""
        p = _new_db_path()
        from app.db.models import Base

        eng = create_engine(f"sqlite:///{p}")
        Base.metadata.create_all(eng)
        with eng.begin() as cn:
            cn.execute(text(
                "INSERT INTO users "
                "(id, email, email_verified, account_type, is_active, plan, plan_updated_at, created_at, updated_at) "
                "VALUES "
                "('00000000-0000-0000-0000-000000000001', "
                " 'system@clearsignal.internal', 1, 'system', 1, 'system', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "('legacy-user', 'legacy@example.com', 1, 'individual', 1, 'free', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            cn.execute(text("ALTER TABLE users DROP COLUMN plan_updated_at"))
            cn.execute(text("ALTER TABLE users DROP COLUMN plan"))

        command.stamp(_cfg(p), _PRE_BILLING_COLUMNS)
        command.upgrade(_cfg(p), "head")

        cols = {c["name"] for c in _insp(p).get_columns("users")}
        assert {"plan", "plan_updated_at"} <= cols
        with eng.connect() as cn:
            rows = dict(cn.execute(text("SELECT id, plan FROM users")).fetchall())
        assert rows["00000000-0000-0000-0000-000000000001"] == "system"
        assert rows["legacy-user"] == "free"
        assert _rev(p) == _HEAD


class TestLegacyPortfolioOrgId:
    def test_upgrade_repairs_existing_portfolios_table_without_losing_rows(self):
        """Reproduce the production schema drift that blocked account import."""
        p = _new_db_path()
        from app.db.models import Base

        eng = create_engine(f"sqlite:///{p}")
        Base.metadata.create_all(eng)
        with eng.begin() as cn:
            cn.execute(text(
                "INSERT INTO portfolios "
                "(id, user_id, name, description, is_default, created_at, updated_at, org_id) "
                "VALUES ('legacy-portfolio', "
                "'00000000-0000-0000-0000-000000000001', "
                "'Legacy Portfolio', 'preserve me', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)"
            ))
            cn.execute(text("ALTER TABLE portfolios DROP COLUMN org_id"))

        command.stamp(_cfg(p), _PRE_PORTFOLIO_ORG_ID)
        command.upgrade(_cfg(p), "head")

        cols = {c["name"] for c in _insp(p).get_columns("portfolios")}
        assert "org_id" in cols
        with eng.connect() as cn:
            row = cn.execute(text(
                "SELECT name, description, org_id FROM portfolios "
                "WHERE id = 'legacy-portfolio'"
            )).one()
        assert row.name == "Legacy Portfolio"
        assert row.description == "preserve me"
        assert row.org_id is None
        assert _rev(p) == _HEAD


class TestStartupAfterMigration:
    def test_startup_does_not_mutate_and_session_usable(self):
        p = _new_db_path()
        command.upgrade(_cfg(p), "head")
        before = set(_insp(p).get_table_names())

        from app.db import connection as conn

        async def _run():
            await conn.init_db(f"sqlite+aiosqlite:///{p}")
            async with conn.get_session() as s:
                assert s is not None
            await conn.close_db()

        asyncio.run(_run())
        assert set(_insp(p).get_table_names()) == before  # startup created/altered nothing

    def test_startup_on_empty_db_creates_no_schema(self):
        p = _new_db_path()
        from app.db import connection as conn

        async def _run():
            await conn.init_db(f"sqlite+aiosqlite:///{p}")
            await conn.close_db()

        asyncio.run(_run())
        # create_all removed → startup makes zero tables on an empty DB.
        assert set(_insp(p).get_table_names()) == set()


class TestBehindHeadDetection:
    def test_detects_db_one_revision_behind(self):
        p = _new_db_path()
        command.upgrade(_cfg(p), _BASELINE)  # deliberately one behind head

        from app.db.migration_check import (
            head_revision, current_db_revision, log_migration_status,
        )
        from sqlalchemy.ext.asyncio import create_async_engine

        async def _run():
            eng = create_async_engine(f"sqlite+aiosqlite:///{p}")
            status = await log_migration_status(eng)
            cur = await current_db_revision(eng)
            await eng.dispose()
            return status, cur

        status, cur = asyncio.run(_run())
        assert cur == _BASELINE
        assert head_revision() == _HEAD
        assert status == "behind"

    def test_unmanaged_db_is_flagged(self):
        p = _new_db_path()
        from app.db.models import Base
        Base.metadata.create_all(create_engine(f"sqlite:///{p}"))  # schema but no alembic_version
        from app.db.migration_check import log_migration_status
        from sqlalchemy.ext.asyncio import create_async_engine

        async def _run():
            eng = create_async_engine(f"sqlite+aiosqlite:///{p}")
            status = await log_migration_status(eng)
            await eng.dispose()
            return status

        assert asyncio.run(_run()) == "unmanaged"


class TestDataPreservation:
    def test_rows_and_relationships_survive_delta_roundtrip(self):
        p = _new_db_path()
        command.upgrade(_cfg(p), "head")
        eng = create_engine(f"sqlite:///{p}")

        # Insert via the ORM so model-level defaults fill the non-nullable columns.
        from sqlalchemy.orm import Session
        from app.db.models import Base
        by_table = {m.class_.__tablename__: m.class_ for m in Base.registry.mappers}
        with Session(eng) as s:
            s.add(by_table["users"](id="u1", email="a@b.co"))
            s.add(by_table["portfolios"](id="p1", user_id="u1"))
            s.add(by_table["portfolio_positions"](id="pp1", portfolio_id="p1", ticker="NVDA"))
            s.add(by_table["delivery_ledger"](
                id="d1", content_key="ck", target_key="tk", content_hash="hh",
                channel="inapp", status="pending",
                canonical_severity="high", severity_rank=3,
            ))
            s.commit()

        # Roundtrip the reversible delta: drop the severity columns then re-add.
        command.downgrade(_cfg(p), _BASELINE)   # 0002.downgrade drops severity cols
        command.upgrade(_cfg(p), "head")        # 0002.upgrade re-adds them (NULL)

        with eng.connect() as cn:
            # Rows preserved
            assert cn.execute(text("SELECT COUNT(*) FROM delivery_ledger")).scalar() == 1
            assert cn.execute(text("SELECT COUNT(*) FROM users")).scalar() == 1
            assert cn.execute(text("SELECT COUNT(*) FROM portfolios")).scalar() == 1
            assert cn.execute(text("SELECT COUNT(*) FROM portfolio_positions")).scalar() == 1
            # Relationships preserved (position → portfolio → user chain intact)
            row = cn.execute(text(
                "SELECT pp.ticker, po.user_id "
                "FROM portfolio_positions pp JOIN portfolios po ON pp.portfolio_id = po.id "
                "WHERE pp.id = 'pp1'"
            )).fetchone()
            assert row == ("NVDA", "u1")
            # Severity columns exist again (values were intentionally dropped on downgrade)
            cols = {c["name"] for c in inspect(eng).get_columns("delivery_ledger")}
            assert {"canonical_severity", "severity_rank"} <= cols
            sev = cn.execute(text("SELECT canonical_severity FROM delivery_ledger WHERE id='d1'")).scalar()
            assert sev is None  # documented: downgrade discards the column data, not the row
