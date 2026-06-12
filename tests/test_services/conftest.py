"""
Shared fixtures for test_services that require DB access.

Provides the same in-memory SQLite db_session fixture used by test_db/,
so loop lock service tests can write to the job_locks table without
a separate conftest inheritance chain.
"""

from __future__ import annotations

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db_session():
    """Yield an AsyncSession backed by a fresh in-memory SQLite database."""
    try:
        from sqlalchemy.ext.asyncio import (
            create_async_engine,
            async_sessionmaker,
            AsyncSession,
        )
        from app.db.models import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        async with factory() as session:
            yield session
            await session.commit()

        await engine.dispose()

    except ImportError:
        pytest.skip("aiosqlite or sqlalchemy not installed")
