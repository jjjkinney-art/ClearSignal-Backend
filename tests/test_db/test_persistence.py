"""
Tests for the Phase 9A persistence orchestrator.

Tests run against an in-memory SQLite session so no external DB is needed.

Strategy
--------
Each test calls repository functions directly (not the full orchestrator)
to keep setup minimal and failures localised.  One integration-style test
exercises persist_analysis_result() end-to-end with a mock
AgentAnswerResponse.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_result(thesis_data: Dict[str, Any]) -> MagicMock:
    """Build a mock AgentAnswerResponse whose answer dict contains the given thesis."""
    result = MagicMock()
    result.answer = {"investment_thesis": thesis_data}
    result.company = thesis_data.get("company_name", "Test Corp")
    result.request_id = str(uuid.uuid4())
    result.agents_used = ["qfirst", "valuation"]
    result.routing = {}
    # model_dump returns a dict matching AgentAnswerResponse structure
    result.model_dump.return_value = {
        "company": result.company,
        "request_id": result.request_id,
        "agents_used": result.agents_used,
        "answer": {"investment_thesis": thesis_data},
        "routing": {},
    }
    return result


# ---------------------------------------------------------------------------
# thesis_repo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_version_and_get_latest(db_session, sample_thesis_data):
    """create_version + get_latest_version round-trip."""
    from app.db.repositories.thesis_repo import create_version, get_latest_version

    v = await create_version(
        session=db_session,
        ticker="NVDA",
        company_name="NVIDIA",
        session_id="s1",
        question="Capex sensitivity?",
        thesis_data=sample_thesis_data,
    )
    assert v is not None
    assert v.ticker == "NVDA"
    assert v.directional_stance == "bullish"
    assert abs(v.confidence_score - 0.72) < 0.001

    latest = await get_latest_version(db_session, "NVDA")
    assert latest is not None
    assert latest.id == v.id


@pytest.mark.asyncio
async def test_get_latest_version_returns_none_for_unknown_ticker(db_session):
    """get_latest_version returns None when no rows exist for the ticker."""
    from app.db.repositories.thesis_repo import get_latest_version

    result = await get_latest_version(db_session, "DOES_NOT_EXIST")
    assert result is None


@pytest.mark.asyncio
async def test_create_delta(db_session, sample_thesis_data):
    """create_delta computes correct magnitude for a material change."""
    from app.db.repositories.thesis_repo import create_version, create_delta

    v1_data = dict(sample_thesis_data, directional_stance="bullish", confidence_score=0.72)
    v2_data = dict(sample_thesis_data, directional_stance="neutral", confidence_score=0.50)

    v1 = await create_version(db_session, "NVDA", "NVIDIA", "s1", "Q1", v1_data)
    v2 = await create_version(db_session, "NVDA", "NVIDIA", "s2", "Q2", v2_data)

    delta = await create_delta(session=db_session, from_version=v1, to_version=v2)
    assert delta is not None
    assert delta.magnitude == "material"
    assert delta.stance_changed is True
    assert abs(delta.conviction_delta - (-0.22)) < 0.01


@pytest.mark.asyncio
async def test_get_evolution_returns_list(db_session, sample_thesis_data):
    """get_evolution returns a list of dicts for existing deltas."""
    from app.db.repositories.thesis_repo import create_version, create_delta, get_evolution

    v1 = await create_version(db_session, "AAPL", "Apple", "s1", "Q1",
                               dict(sample_thesis_data, ticker="AAPL", directional_stance="bullish", confidence_score=0.70))
    v2 = await create_version(db_session, "AAPL", "Apple", "s2", "Q2",
                               dict(sample_thesis_data, ticker="AAPL", directional_stance="bullish", confidence_score=0.65))
    await create_delta(db_session, v1, v2)

    evol = await get_evolution(db_session, "AAPL")
    assert isinstance(evol, list)
    assert len(evol) == 1
    assert "magnitude" in evol[0]
    assert "changed_fields" in evol[0]
    assert isinstance(evol[0]["changed_fields"], list)


@pytest.mark.asyncio
async def test_create_version_none_session_returns_none(sample_thesis_data):
    """create_version with session=None must not raise and must return None."""
    from app.db.repositories.thesis_repo import create_version

    result = await create_version(
        session=None,
        ticker="NVDA",
        company_name="NVIDIA",
        session_id="s1",
        question="test",
        thesis_data=sample_thesis_data,
    )
    assert result is None


# ---------------------------------------------------------------------------
# memory_repo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_create_memory_creates_new(db_session):
    """get_or_create_memory creates a row when none exists."""
    from app.db.repositories.memory_repo import get_or_create_memory

    row = await get_or_create_memory(db_session, ticker="COST", company_name="Costco")
    assert row is not None
    assert row.ticker == "COST"
    assert row.total_queries == 0


@pytest.mark.asyncio
async def test_get_or_create_memory_idempotent(db_session):
    """get_or_create_memory returns the same row on second call."""
    from app.db.repositories.memory_repo import get_or_create_memory

    r1 = await get_or_create_memory(db_session, ticker="MSFT", company_name="Microsoft")
    r2 = await get_or_create_memory(db_session, ticker="MSFT", company_name="Microsoft")
    assert r1.id == r2.id


@pytest.mark.asyncio
async def test_append_entry(db_session):
    """append_entry inserts a MemoryEntry and get_history returns it."""
    from app.db.repositories.memory_repo import append_entry, get_history

    entry = await append_entry(
        session=db_session,
        ticker="JPM",
        session_id="s-abc",
        entry_type="analysis",
        content="Stance: bearish. Conviction: 0.55",
        metadata={"confidence_score": 0.55},
    )
    assert entry is not None
    assert entry.entry_type == "analysis"

    history = await get_history(db_session, "JPM")
    assert len(history) == 1
    assert history[0]["ticker"] == "JPM"
    assert history[0]["metadata"]["confidence_score"] == 0.55


@pytest.mark.asyncio
async def test_get_history_empty_for_unknown_ticker(db_session):
    """get_history returns empty list for ticker with no entries."""
    from app.db.repositories.memory_repo import get_history

    result = await get_history(db_session, "ZZZZ")
    assert result == []


# ---------------------------------------------------------------------------
# concern_repo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_tag_creates_and_increments(db_session):
    """upsert_tag creates on first call, increments on second."""
    from app.db.repositories.concern_repo import upsert_tag, get_tags_for_ticker

    r1 = await upsert_tag(db_session, "TSM", "geopolitical_risk")
    assert r1 is not None
    assert r1.mention_count == 1

    r2 = await upsert_tag(db_session, "TSM", "geopolitical_risk")
    assert r2 is not None
    assert r2.mention_count == 2

    counts = await get_tags_for_ticker(db_session, "TSM")
    assert counts["geopolitical_risk"] == 2


@pytest.mark.asyncio
async def test_get_tags_for_ticker_empty(db_session):
    """get_tags_for_ticker returns empty dict for unknown ticker."""
    from app.db.repositories.concern_repo import get_tags_for_ticker

    result = await get_tags_for_ticker(db_session, "FAKE")
    assert result == {}


# ---------------------------------------------------------------------------
# Full persistence orchestrator integration test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_analysis_result_end_to_end(db_session, sample_thesis_data):
    """
    End-to-end: persist_analysis_result() writes thesis_version,
    ticker_memory, memory_entry, and concern_tags in one call.

    We monkey-patch get_session to yield the test db_session so the
    orchestrator uses SQLite in-memory instead of the real engine.
    """
    import app.db.connection as _conn_module
    from app.db.persistence import persist_analysis_result
    from contextlib import asynccontextmanager

    # Patch get_session so it yields our test session instead of None
    @asynccontextmanager
    async def _patched_get_session():
        yield db_session

    original_get_session = _conn_module.get_session
    _conn_module.get_session = _patched_get_session

    try:
        mock_result = _make_mock_result(sample_thesis_data)
        await persist_analysis_result(
            question="If hyperscalers cut capex by 20pp, what happens to NVDA revenue?",
            company_name="NVIDIA Corporation",
            session_id="test-session-001",
            result=mock_result,
        )
        await db_session.commit()

        # Verify thesis_version was created
        from app.db.repositories.thesis_repo import get_latest_version
        version = await get_latest_version(db_session, "NVDA")
        assert version is not None
        assert version.directional_stance == "bullish"

        # Verify ticker_memory was created and incremented
        from app.db.repositories.memory_repo import get_or_create_memory
        mem = await get_or_create_memory(db_session, "NVDA")
        assert mem is not None
        assert mem.total_queries >= 1

        # Verify concern tags were written (capex_cycle should fire on this question)
        from app.db.repositories.concern_repo import get_tags_for_ticker
        tags = await get_tags_for_ticker(db_session, "NVDA")
        assert len(tags) > 0
        assert "capex_cycle" in tags

        # Verify memory entry was appended
        from app.db.repositories.memory_repo import get_history
        history = await get_history(db_session, "NVDA")
        assert len(history) >= 1
        assert any(e["entry_type"] == "analysis" for e in history)

    finally:
        _conn_module.get_session = original_get_session


@pytest.mark.asyncio
async def test_persist_analysis_result_none_session_is_noop(sample_thesis_data):
    """persist_analysis_result must not raise when persistence is disabled."""
    import app.db.connection as _conn_module
    from app.db.persistence import persist_analysis_result
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _null_get_session():
        yield None  # simulate disabled persistence

    original = _conn_module.get_session
    _conn_module.get_session = _null_get_session

    try:
        mock_result = _make_mock_result(sample_thesis_data)
        # Must complete without raising
        await persist_analysis_result(
            question="test",
            company_name="NVIDIA",
            session_id="",
            result=mock_result,
        )
    finally:
        _conn_module.get_session = original


@pytest.mark.asyncio
async def test_persist_analysis_result_bad_result_is_noop():
    """persist_analysis_result must not raise when result has no thesis."""
    from app.db.persistence import persist_analysis_result

    bad_result = MagicMock()
    bad_result.answer = {}  # no investment_thesis key

    # Should complete silently
    await persist_analysis_result(
        question="test",
        company_name="NVDA",
        session_id="s1",
        result=bad_result,
    )


@pytest.mark.asyncio
async def test_persist_skips_wall_cap_fallback_thesis(db_session):
    """Wall-cap fallback theses (confidence_score=0.0, sentinel conclusion) must NOT be persisted.

    A fallback thesis saved to DB would corrupt conviction_trend on the next
    query, causing the banner to display "42% → 0%".
    """
    import app.db.connection as _conn_module
    from app.db.persistence import persist_analysis_result
    from app.db.repositories.thesis_repo import get_latest_version
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _patched_get_session():
        yield db_session

    original = _conn_module.get_session
    _conn_module.get_session = _patched_get_session

    fallback_thesis = {
        "ticker": "NVDA",
        "company_name": "NVIDIA Corporation",
        "directional_stance": "bullish",
        "confidence_score": 0.0,
        "bull_thesis": "Synthesis unavailable (wall cap exceeded).",
        "bear_thesis": "Synthesis unavailable (wall cap exceeded).",
        "conclusion": "Could not synthesize — wall cap exceeded.",
    }
    mock_result = _make_mock_result(fallback_thesis)

    try:
        await persist_analysis_result(
            question="test wall cap",
            company_name="NVIDIA Corporation",
            session_id="test-wallcap-001",
            result=mock_result,
        )
        await db_session.commit()
    finally:
        _conn_module.get_session = original

    # No ThesisVersion should have been written
    version = await get_latest_version(db_session, "NVDA")
    assert version is None, "Wall-cap fallback thesis must not create a ThesisVersion row"
