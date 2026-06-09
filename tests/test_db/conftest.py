"""
Shared fixtures for Phase 9A persistence tests.

Uses SQLite in-memory via aiosqlite so no PostgreSQL instance is needed.
All tables are created fresh for each test function via the ``db_session``
fixture.
"""

from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Event-loop scope: function (default for pytest-asyncio ≥ 0.21)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session():
    """Yield an AsyncSession backed by a fresh in-memory SQLite database.

    Tables are created from the ORM metadata before the test and the engine
    is disposed after.  The session is committed and closed by the fixture.

    Yields
    ------
    AsyncSession  (or None if aiosqlite / sqlalchemy is not installed)
    """
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
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


@pytest.fixture
def sample_thesis_data():
    """Return a representative InvestmentThesis-shaped dict for test use."""
    return {
        "ticker": "NVDA",
        "company_name": "NVIDIA Corporation",
        "directional_stance": "bullish",
        "confidence_score": 0.72,
        "bull_thesis": (
            "Blackwell architecture ramp drives data center revenue above consensus. "
            "Sovereign AI demand provides a structurally independent demand floor."
        ),
        "bear_thesis": (
            "Custom silicon from hyperscalers (Trainium, TPU) erodes NVIDIA's share "
            "of the capex pool even without top-line deceleration."
        ),
        "verdict_rationale": (
            "Conviction stays bullish given Blackwell momentum and sovereign AI, "
            "but custom-silicon concentration risk caps upside."
        ),
        "direct_answer": (
            "A 20pp capex deceleration implies a $31-38B revenue haircut at mid-range "
            "assumptions — material but not thesis-breaking given sovereign AI offset."
        ),
        "why_not": "Custom silicon share at 61% concentration makes this asymmetric.",
        "conclusion": "Hold with active monitoring of hyperscaler capex-to-AI-revenue ratio.",
        "key_drivers": ["Blackwell ramp", "sovereign AI", "inference expansion"],
        "key_risks": ["custom silicon share gains", "capex deceleration", "concentration risk"],
        "macro_sensitivity": {"rate_sensitivity": "low", "gdp_sensitivity": "medium"},
        "threshold_zones": {"bull_break": "capex/cloud ratio > 12x for 2 qtrs"},
    }
