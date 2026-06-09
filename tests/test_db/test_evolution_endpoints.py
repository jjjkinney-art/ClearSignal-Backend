"""
Tests for Phase 9B evolution repository functions.

Tests the repository layer directly (not FastAPI endpoints) using the
in-memory SQLite db_session fixture from conftest.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_versions(db_session, ticker: str, n: int, stances: list[str] | None = None):
    """Insert n ThesisVersion rows for ticker and return them in order."""
    from app.db.models import ThesisVersion
    versions = []
    for i in range(n):
        stance = (stances[i] if stances and i < len(stances) else "bullish")
        row = ThesisVersion(
            id=str(uuid.uuid4()),
            ticker=ticker,
            company_name=f"{ticker} Corp",
            session_id=f"sess-{i}",
            question=f"Question {i}",
            directional_stance=stance,
            confidence_score=round(0.80 - i * 0.05, 2),
            bull_thesis=f"Bull thesis version {i} with unique words like {'alpha' * (i + 1)}",
            bear_thesis=f"Bear thesis version {i} with different content {'beta' * (i + 1)}",
            verdict_rationale=f"Rationale {i}",
            direct_answer=f"Direct answer {i}",
            why_not=f"Why not {i}",
            conclusion=f"Conclusion {i}",
            key_drivers="[]", key_risks="[]",
            macro_sensitivity="{}", threshold_zones="{}",
            created_at=datetime(2026, 6, i + 1, tzinfo=timezone.utc),
        )
        db_session.add(row)
        versions.append(row)
    await db_session.flush()
    return versions


async def _seed_memory(db_session, ticker: str, company_name: str = ""):
    """Insert a TickerMemory row."""
    from app.db.models import TickerMemory
    now = datetime.now(timezone.utc)
    row = TickerMemory(
        id=str(uuid.uuid4()),
        ticker=ticker,
        company_name=company_name or f"{ticker} Corp",
        total_queries=5,
        version_count=3,
        last_stance="bullish",
        last_confidence=0.70,
        dominant_concern="capex_cycle",
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    await db_session.flush()
    return row


# ---------------------------------------------------------------------------
# get_evolution_with_versions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evolution_returns_none_for_unknown_ticker(db_session):
    from app.db.repositories.evolution_repo import get_evolution_with_versions
    result = await get_evolution_with_versions(db_session, "ZZZZ")
    assert result is None


@pytest.mark.asyncio
async def test_evolution_returns_empty_deltas_for_single_version(db_session):
    """Ticker with memory but only one version → deltas list is empty."""
    from app.db.repositories.evolution_repo import get_evolution_with_versions
    from app.db.repositories.thesis_repo import create_version

    await _seed_memory(db_session, "NVDA")
    await create_version(db_session, "NVDA", "NVIDIA", "s1", "Q?",
                         {"directional_stance": "bullish", "confidence_score": 0.72})
    await db_session.flush()

    result = await get_evolution_with_versions(db_session, "NVDA")
    assert result is not None
    assert result["ticker"] == "NVDA"
    assert isinstance(result["deltas"], list)
    # No deltas yet because create_delta hasn't been called
    assert len(result["deltas"]) == 0


@pytest.mark.asyncio
async def test_evolution_with_delta_populated(db_session, sample_thesis_data):
    """Two versions + a delta → one item in deltas list with correct structure."""
    from app.db.repositories.evolution_repo import (
        get_evolution_with_versions,
        create_delta_with_debounce,
    )
    from app.db.repositories.thesis_repo import create_version

    await _seed_memory(db_session, "NVDA")
    v1 = await create_version(db_session, "NVDA", "NVIDIA", "s1", "Q1",
                               dict(sample_thesis_data, directional_stance="bullish", confidence_score=0.80))
    v2 = await create_version(db_session, "NVDA", "NVIDIA", "s2", "Q2",
                               dict(sample_thesis_data, directional_stance="neutral", confidence_score=0.55))
    await create_delta_with_debounce(db_session, v1, v2)
    await db_session.flush()

    result = await get_evolution_with_versions(db_session, "NVDA")
    assert result is not None
    assert len(result["deltas"]) == 1

    delta = result["deltas"][0]
    assert "delta_id" in delta
    assert "magnitude" in delta
    assert "from_version" in delta
    assert "to_version" in delta
    assert delta["stance_changed"] is True
    assert delta["from_version"]["directional_stance"] == "bullish"
    assert delta["to_version"]["directional_stance"] == "neutral"


@pytest.mark.asyncio
async def test_evolution_min_magnitude_filter(db_session, sample_thesis_data):
    """min_magnitude=material filters out minor/moderate deltas."""
    from app.db.repositories.evolution_repo import (
        get_evolution_with_versions,
        create_delta_with_debounce,
    )
    from app.db.repositories.thesis_repo import create_version

    await _seed_memory(db_session, "COST")
    v1 = await create_version(db_session, "COST", "Costco", "s1", "Q1",
                               dict(sample_thesis_data, ticker="COST", directional_stance="bullish", confidence_score=0.70))
    v2 = await create_version(db_session, "COST", "Costco", "s2", "Q2",
                               dict(sample_thesis_data, ticker="COST", directional_stance="bullish", confidence_score=0.68))
    await create_delta_with_debounce(db_session, v1, v2)
    await db_session.flush()

    # Small delta → magnitude minor or moderate
    result_minor = await get_evolution_with_versions(db_session, "COST", min_magnitude="minor")
    result_material = await get_evolution_with_versions(db_session, "COST", min_magnitude="material")

    # minor filter shows everything; material filter may show nothing
    assert result_minor is not None
    assert result_material is not None
    assert len(result_minor["deltas"]) >= len(result_material["deltas"])


# ---------------------------------------------------------------------------
# get_delta_full
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_delta_full_returns_full_text(db_session, sample_thesis_data):
    from app.db.repositories.evolution_repo import get_delta_full, create_delta_with_debounce
    from app.db.repositories.thesis_repo import create_version

    v1 = await create_version(db_session, "AAPL", "Apple", "s1", "Q1",
                               dict(sample_thesis_data, ticker="AAPL", directional_stance="bullish", confidence_score=0.70))
    v2 = await create_version(db_session, "AAPL", "Apple", "s2", "Q2",
                               dict(sample_thesis_data, ticker="AAPL", directional_stance="neutral", confidence_score=0.50))
    delta = await create_delta_with_debounce(db_session, v1, v2)
    assert delta is not None

    result = await get_delta_full(db_session, "AAPL", delta.id)
    assert result is not None
    assert result["delta_id"] == delta.id
    assert "bull_thesis" in result["from_version"]
    assert "bull_thesis" in result["to_version"]
    assert "inline_diff" in result
    assert "bull_thesis" in result["inline_diff"]
    assert "similarity" in result["inline_diff"]["bull_thesis"]
    assert "from_word_count" in result["inline_diff"]["bull_thesis"]


@pytest.mark.asyncio
async def test_get_delta_full_wrong_ticker_returns_none(db_session, sample_thesis_data):
    from app.db.repositories.evolution_repo import get_delta_full, create_delta_with_debounce
    from app.db.repositories.thesis_repo import create_version

    v1 = await create_version(db_session, "MSFT", "Microsoft", "s1", "Q1", sample_thesis_data)
    v2 = await create_version(db_session, "MSFT", "Microsoft", "s2", "Q2", sample_thesis_data)
    delta = await create_delta_with_debounce(db_session, v1, v2)

    result = await get_delta_full(db_session, "WRONG_TICKER", delta.id)
    assert result is None


# ---------------------------------------------------------------------------
# get_latest_change_card
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_latest_change_card_no_history_returns_none(db_session):
    from app.db.repositories.evolution_repo import get_latest_change_card
    assert await get_latest_change_card(db_session, "FAKE") is None


@pytest.mark.asyncio
async def test_get_latest_change_card_single_version_has_null_delta(db_session, sample_thesis_data):
    from app.db.repositories.evolution_repo import get_latest_change_card
    from app.db.repositories.thesis_repo import create_version

    await create_version(db_session, "JPM", "JPMorgan", "s1", "Q?",
                         dict(sample_thesis_data, ticker="JPM"))

    result = await get_latest_change_card(db_session, "JPM")
    assert result is not None
    assert result["ticker"] == "JPM"
    assert result["last_delta"] is None


@pytest.mark.asyncio
async def test_get_latest_change_card_with_delta(db_session, sample_thesis_data):
    from app.db.repositories.evolution_repo import get_latest_change_card, create_delta_with_debounce
    from app.db.repositories.thesis_repo import create_version

    v1 = await create_version(db_session, "V", "Visa", "s1", "Q1",
                               dict(sample_thesis_data, ticker="V", directional_stance="bullish", confidence_score=0.75))
    v2 = await create_version(db_session, "V", "Visa", "s2", "Q2",
                               dict(sample_thesis_data, ticker="V", directional_stance="neutral", confidence_score=0.52))
    await create_delta_with_debounce(db_session, v1, v2)

    result = await get_latest_change_card(db_session, "V")
    assert result is not None
    assert result["last_delta"] is not None
    assert result["last_delta"]["magnitude"] == "material"
    assert result["last_delta"]["stance_changed"] is True


# ---------------------------------------------------------------------------
# get_material_changes_feed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_material_feed_empty_when_no_data(db_session):
    from app.db.repositories.evolution_repo import get_material_changes_feed
    result = await get_material_changes_feed(db_session)
    assert result["feed"] == []
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_material_feed_contains_material_deltas(db_session, sample_thesis_data):
    from app.db.repositories.evolution_repo import get_material_changes_feed, create_delta_with_debounce
    from app.db.repositories.thesis_repo import create_version
    from app.db.repositories.memory_repo import get_or_create_memory

    await get_or_create_memory(db_session, "TSM", "TSMC")
    v1 = await create_version(db_session, "TSM", "TSMC", "s1", "Q1",
                               dict(sample_thesis_data, ticker="TSM", directional_stance="bullish", confidence_score=0.80))
    v2 = await create_version(db_session, "TSM", "TSMC", "s2", "Q2",
                               dict(sample_thesis_data, ticker="TSM", directional_stance="bearish", confidence_score=0.40))
    delta = await create_delta_with_debounce(db_session, v1, v2)
    assert delta is not None and delta.magnitude == "material"

    result = await get_material_changes_feed(db_session)
    assert len(result["feed"]) >= 1
    feed_item = result["feed"][0]
    assert feed_item["ticker"] == "TSM"
    assert feed_item["magnitude"] == "material"
    assert "headline" in feed_item
    assert len(feed_item["headline"]) > 0


@pytest.mark.asyncio
async def test_material_feed_ticker_filter(db_session, sample_thesis_data):
    from app.db.repositories.evolution_repo import get_material_changes_feed, create_delta_with_debounce
    from app.db.repositories.thesis_repo import create_version
    from app.db.repositories.memory_repo import get_or_create_memory

    for ticker, stance_from, stance_to in [("NVDA", "bullish", "neutral"), ("AAPL", "bullish", "bearish")]:
        await get_or_create_memory(db_session, ticker)
        v1 = await create_version(db_session, ticker, ticker, "s1", "Q1",
                                   dict(sample_thesis_data, ticker=ticker, directional_stance=stance_from, confidence_score=0.80))
        v2 = await create_version(db_session, ticker, ticker, "s2", "Q2",
                                   dict(sample_thesis_data, ticker=ticker, directional_stance=stance_to, confidence_score=0.45))
        await create_delta_with_debounce(db_session, v1, v2)

    result = await get_material_changes_feed(db_session, tickers=["NVDA"])
    tickers_in_feed = {item["ticker"] for item in result["feed"]}
    assert "NVDA" in tickers_in_feed
    assert "AAPL" not in tickers_in_feed
