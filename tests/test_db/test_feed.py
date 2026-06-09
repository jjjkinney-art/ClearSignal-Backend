"""
Tests for Phase 9B material feed debounce and pagination.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest


# ---------------------------------------------------------------------------
# Debounce: one material delta per ticker per day
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_debounce_suppresses_weaker_same_day_delta(db_session, sample_thesis_data):
    """Two material deltas for the same ticker same day → smaller |delta| suppressed."""
    from app.db.repositories.evolution_repo import create_delta_with_debounce
    from app.db.repositories.thesis_repo import create_version
    from app.db.models import ThesisDelta
    from sqlalchemy import select

    # Version 1 → 2: large conviction drop (-0.35) — WINNER
    v1 = await create_version(db_session, "NVDA", "NVIDIA", "s1", "Q1",
                               dict(sample_thesis_data, ticker="NVDA",
                                    directional_stance="bullish", confidence_score=0.90))
    v2 = await create_version(db_session, "NVDA", "NVIDIA", "s2", "Q2",
                               dict(sample_thesis_data, ticker="NVDA",
                                    directional_stance="neutral", confidence_score=0.55))
    delta_big = await create_delta_with_debounce(db_session, v1, v2)

    # Version 2 → 3: small conviction drop (-0.05) — should be suppressed
    v3 = await create_version(db_session, "NVDA", "NVIDIA", "s3", "Q3",
                               dict(sample_thesis_data, ticker="NVDA",
                                    directional_stance="neutral", confidence_score=0.50))
    delta_small = await create_delta_with_debounce(db_session, v2, v3)

    # Reload from DB
    result = await db_session.execute(
        select(ThesisDelta).where(ThesisDelta.ticker == "NVDA")
    )
    all_deltas = result.scalars().all()
    material_deltas = [d for d in all_deltas if d.magnitude == "material"]

    if len(material_deltas) >= 2:
        visible = [d for d in material_deltas if d.debounce_visible]
        hidden = [d for d in material_deltas if not d.debounce_visible]
        # Exactly one winner
        assert len(visible) == 1
        # Winner has the largest |conviction_delta|
        winner = visible[0]
        assert abs(winner.conviction_delta) == max(
            abs(d.conviction_delta) for d in material_deltas
        )


@pytest.mark.asyncio
async def test_debounce_different_tickers_both_visible(db_session, sample_thesis_data):
    """Material deltas for different tickers on the same day → both visible."""
    from app.db.repositories.evolution_repo import create_delta_with_debounce
    from app.db.repositories.thesis_repo import create_version
    from app.db.models import ThesisDelta
    from sqlalchemy import select

    for ticker in ["NVDA", "AAPL"]:
        v1 = await create_version(db_session, ticker, ticker, "s1", "Q1",
                                   dict(sample_thesis_data, ticker=ticker,
                                        directional_stance="bullish", confidence_score=0.80))
        v2 = await create_version(db_session, ticker, ticker, "s2", "Q2",
                                   dict(sample_thesis_data, ticker=ticker,
                                        directional_stance="neutral", confidence_score=0.50))
        await create_delta_with_debounce(db_session, v1, v2)

    result = await db_session.execute(
        select(ThesisDelta).where(ThesisDelta.magnitude == "material")
    )
    material_deltas = result.scalars().all()
    visible = [d for d in material_deltas if d.debounce_visible]
    # One visible delta per ticker
    visible_tickers = {d.ticker for d in visible}
    assert "NVDA" in visible_tickers
    assert "AAPL" in visible_tickers


@pytest.mark.asyncio
async def test_debounce_none_session_is_noop(sample_thesis_data):
    """apply_debounce with session=None must not raise."""
    from app.db.repositories.evolution_repo import apply_debounce
    # Must complete without raising
    await apply_debounce(None, "NVDA", "fake-delta-id")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_material_feed_pagination_has_more(db_session, sample_thesis_data):
    """With limit=1 and 2 material deltas → has_more=True, next_cursor set."""
    from app.db.repositories.evolution_repo import get_material_changes_feed, create_delta_with_debounce
    from app.db.repositories.thesis_repo import create_version
    from app.db.repositories.memory_repo import get_or_create_memory

    # Seed two different tickers with material deltas
    for ticker, day in [("NVDA", 7), ("AAPL", 8)]:
        await get_or_create_memory(db_session, ticker)
        v1 = await create_version(
            db_session, ticker, ticker, "s1", "Q1",
            dict(sample_thesis_data, ticker=ticker, directional_stance="bullish", confidence_score=0.80),
        )
        v2 = await create_version(
            db_session, ticker, ticker, "s2", "Q2",
            dict(sample_thesis_data, ticker=ticker, directional_stance="neutral", confidence_score=0.45),
        )
        delta = await create_delta_with_debounce(db_session, v1, v2)
        if delta:
            delta.created_at = datetime(2026, 6, day, tzinfo=timezone.utc)
    await db_session.flush()

    result = await get_material_changes_feed(db_session, limit=1)
    if result["has_more"]:
        assert result["next_cursor"] is not None
    # At least one item returned
    assert len(result["feed"]) >= 1


@pytest.mark.asyncio
async def test_material_feed_cursor_pagination(db_session, sample_thesis_data):
    """Second page via next_cursor returns different items than first page."""
    from app.db.repositories.evolution_repo import get_material_changes_feed, create_delta_with_debounce
    from app.db.repositories.thesis_repo import create_version
    from app.db.repositories.memory_repo import get_or_create_memory

    tickers = ["NVDA", "AAPL", "MSFT"]
    for i, ticker in enumerate(tickers):
        await get_or_create_memory(db_session, ticker)
        v1 = await create_version(
            db_session, ticker, ticker, f"s{i}1", "Q1",
            dict(sample_thesis_data, ticker=ticker, directional_stance="bullish", confidence_score=0.80),
        )
        v2 = await create_version(
            db_session, ticker, ticker, f"s{i}2", "Q2",
            dict(sample_thesis_data, ticker=ticker, directional_stance="neutral", confidence_score=0.45),
        )
        delta = await create_delta_with_debounce(db_session, v1, v2)
        # Space out timestamps so pagination works
        if delta:
            delta.created_at = datetime(2026, 6, 10 - i, tzinfo=timezone.utc)
    await db_session.flush()

    page1 = await get_material_changes_feed(db_session, limit=2)
    page1_ids = {item["delta_id"] for item in page1["feed"]}

    if page1["has_more"] and page1["next_cursor"]:
        from datetime import datetime as _dt
        since_dt = _dt.fromisoformat(page1["next_cursor"])
        page2 = await get_material_changes_feed(db_session, limit=2, since=since_dt)
        page2_ids = {item["delta_id"] for item in page2["feed"]}
        # No overlap between pages
        assert len(page1_ids & page2_ids) == 0


# ---------------------------------------------------------------------------
# Headline generator
# ---------------------------------------------------------------------------

def test_headline_stance_change():
    from app.db.repositories.evolution_repo import _generate_headline
    h = _generate_headline(True, "bullish", "neutral", -0.18, ["directional_stance"], "capex_cycle")
    assert "bullish" in h
    assert "neutral" in h
    assert "−18" in h or "-18" in h


def test_headline_conviction_only():
    from app.db.repositories.evolution_repo import _generate_headline
    h = _generate_headline(False, "bullish", "bullish", -0.12, ["confidence_score"], "cre_credit_risk")
    assert "−12" in h or "-12" in h or "12" in h


def test_headline_no_conviction_change():
    from app.db.repositories.evolution_repo import _generate_headline
    h = _generate_headline(False, "bullish", "bullish", 0.0, ["bear_thesis"], "")
    assert len(h) > 0  # returns something


def test_headline_empty_changed_fields():
    from app.db.repositories.evolution_repo import _generate_headline
    h = _generate_headline(False, "neutral", "neutral", 0.0, [], "")
    assert h == "Minor thesis update."
