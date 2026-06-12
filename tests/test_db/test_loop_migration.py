"""
Phase 10A · Slice 1 — migration idempotency and structural tests.

Validates:
  1. All 24 ORM tables are created by Base.metadata.create_all (idempotent —
     running create_all twice raises no error).
  2. db_table_count is exactly 24 on a fresh in-memory SQLite database
     (19 Phase 9 tables + 5 Phase 10A loop tables).
  3. briefing_sessions gained content_hash and delivery_channel columns.
  4. Each loop table has the expected columns and constraints.
  5. The SQL migration file 005_continuous_loop.sql exists.

Uses in-memory SQLite via aiosqlite — no Postgres instance needed.
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fresh_engine():
    """Yield a fresh in-memory SQLite engine with all ORM tables created."""
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from app.db.models import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield engine
        await engine.dispose()

    except ImportError:
        pytest.skip("aiosqlite or sqlalchemy not installed")


# ---------------------------------------------------------------------------
# 1. Idempotency — create_all runs twice without error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_all_is_idempotent(fresh_engine):
    """Running Base.metadata.create_all twice raises no error."""
    from app.db.models import Base

    # Run a second time — IF NOT EXISTS semantics in Base.metadata.create_all
    async with fresh_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # second call — must not raise


# ---------------------------------------------------------------------------
# 2. Table count — 24 tables on a fresh DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_table_count_is_24(fresh_engine):
    """db_table_count must be 24 after Phase 10A Slice 1 models are applied."""
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        )
        count = result.scalar()

    # 19 Phase 9 tables + 5 Phase 10A loop tables = 24
    assert count == 24, (
        f"Expected 24 tables (19 Phase 9 + 5 Phase 10A), got {count}. "
        "Check that all 5 loop models are defined in app/db/models.py."
    )


# ---------------------------------------------------------------------------
# 3. briefing_sessions extension columns exist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_briefing_sessions_has_new_columns(fresh_engine):
    """briefing_sessions must have content_hash and delivery_channel columns."""
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(briefing_sessions)"))
        rows = result.fetchall()

    column_names = {row[1] for row in rows}  # SQLite PRAGMA: col[1] is name
    assert "content_hash" in column_names, (
        "briefing_sessions is missing content_hash column (Phase 10A extension)"
    )
    assert "delivery_channel" in column_names, (
        "briefing_sessions is missing delivery_channel column (Phase 10A extension)"
    )


# ---------------------------------------------------------------------------
# 4a. scheduled_jobs — columns and unique constraint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scheduled_jobs_schema(fresh_engine):
    """scheduled_jobs has all required columns."""
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(scheduled_jobs)"))
        rows = result.fetchall()

    columns = {row[1] for row in rows}
    required = {
        "id", "job_type", "target_key", "period_bucket", "state",
        "next_run_utc", "cadence", "catch_up_window_s", "attempts",
        "max_attempts", "holder_id", "lease_expires_utc", "fence_token",
        "payload_json", "last_generated_at", "created_at", "updated_at",
    }
    missing = required - columns
    assert not missing, f"scheduled_jobs missing columns: {missing}"


# ---------------------------------------------------------------------------
# 4b. job_locks — columns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_locks_schema(fresh_engine):
    """job_locks has all required columns."""
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(job_locks)"))
        rows = result.fetchall()

    columns = {row[1] for row in rows}
    required = {"lock_name", "holder_id", "acquired_utc", "lease_expires_utc", "fence_token"}
    missing = required - columns
    assert not missing, f"job_locks missing columns: {missing}"


# ---------------------------------------------------------------------------
# 4c. job_runs — columns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_runs_schema(fresh_engine):
    """job_runs has all required columns."""
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(job_runs)"))
        rows = result.fetchall()

    columns = {row[1] for row in rows}
    required = {
        "id", "job_id", "work_key", "job_type", "target_key", "period_bucket",
        "started_utc", "finished_utc", "outcome", "spent_llm_calls",
        "drift_hit", "error", "holder_id", "fence_token",
    }
    missing = required - columns
    assert not missing, f"job_runs missing columns: {missing}"


# ---------------------------------------------------------------------------
# 4d. delivery_ledger — columns and unique constraint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delivery_ledger_schema(fresh_engine):
    """delivery_ledger has all required columns."""
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(delivery_ledger)"))
        rows = result.fetchall()

    columns = {row[1] for row in rows}
    required = {
        "id", "content_key", "target_key", "channel", "content_hash",
        "artifact_ref", "status", "attempts", "not_before_utc",
        "created_at", "delivered_at",
    }
    missing = required - columns
    assert not missing, f"delivery_ledger missing columns: {missing}"


@pytest.mark.asyncio
async def test_delivery_ledger_content_key_unique(fresh_engine):
    """UNIQUE(content_key) is enforced at the DB level on delivery_ledger."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    insert_sql = text(
        "INSERT INTO delivery_ledger (id, content_key, target_key, channel, "
        "content_hash, status, attempts, created_at) "
        "VALUES (:id, :ck, :tk, 'in_app', 'h', 'pending', 0, '2026-01-01')"
    )
    async with fresh_engine.begin() as conn:
        await conn.execute(insert_sql, {"id": "id-1", "ck": "ck-test", "tk": "user-1"})

    with pytest.raises(Exception):
        async with fresh_engine.begin() as conn:
            await conn.execute(insert_sql, {"id": "id-2", "ck": "ck-test", "tk": "user-1"})


# ---------------------------------------------------------------------------
# 4e. notifications — columns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notifications_schema(fresh_engine):
    """notifications has all required columns."""
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(notifications)"))
        rows = result.fetchall()

    columns = {row[1] for row in rows}
    required = {"id", "user_id", "kind", "body_json", "read_at", "created_at"}
    missing = required - columns
    assert not missing, f"notifications missing columns: {missing}"


# ---------------------------------------------------------------------------
# 5. SQL migration file exists
# ---------------------------------------------------------------------------

def test_migration_file_exists():
    """005_continuous_loop.sql must exist in the migrations directory."""
    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "app", "db", "migrations", "005_continuous_loop.sql",
    )
    assert os.path.isfile(migration_path), (
        f"Migration file not found: {migration_path}"
    )


def test_migration_file_is_idempotent():
    """005_continuous_loop.sql must use IF NOT EXISTS throughout."""
    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "app", "db", "migrations", "005_continuous_loop.sql",
    )
    with open(migration_path) as f:
        content = f.read()

    # Every CREATE TABLE must be IF NOT EXISTS
    import re
    create_tables = re.findall(r"CREATE TABLE\b", content, re.IGNORECASE)
    create_tables_if = re.findall(r"CREATE TABLE IF NOT EXISTS\b", content, re.IGNORECASE)
    assert len(create_tables) == len(create_tables_if), (
        f"Not all CREATE TABLE statements use IF NOT EXISTS: "
        f"found {len(create_tables)} CREATE TABLE, {len(create_tables_if)} with IF NOT EXISTS"
    )

    # Every CREATE INDEX must be IF NOT EXISTS
    create_indexes = re.findall(r"CREATE INDEX\b", content, re.IGNORECASE)
    create_indexes_if = re.findall(r"CREATE INDEX IF NOT EXISTS\b", content, re.IGNORECASE)
    assert len(create_indexes) == len(create_indexes_if), (
        f"Not all CREATE INDEX statements use IF NOT EXISTS: "
        f"found {len(create_indexes)} CREATE INDEX, {len(create_indexes_if)} with IF NOT EXISTS"
    )


def test_migration_file_covers_all_loop_tables():
    """005_continuous_loop.sql must reference all 5 loop tables."""
    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "app", "db", "migrations", "005_continuous_loop.sql",
    )
    with open(migration_path) as f:
        content = f.read().lower()

    tables = ["scheduled_jobs", "job_locks", "job_runs", "delivery_ledger", "notifications"]
    for table in tables:
        assert table in content, (
            f"Migration file does not reference table '{table}'"
        )


def test_migration_file_extends_briefing_sessions():
    """005_continuous_loop.sql must ALTER briefing_sessions."""
    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "app", "db", "migrations", "005_continuous_loop.sql",
    )
    with open(migration_path) as f:
        content = f.read().lower()

    assert "alter table briefing_sessions" in content, (
        "Migration file does not contain ALTER TABLE briefing_sessions"
    )
    assert "content_hash" in content, (
        "Migration file does not add content_hash to briefing_sessions"
    )
    assert "delivery_channel" in content, (
        "Migration file does not add delivery_channel to briefing_sessions"
    )
