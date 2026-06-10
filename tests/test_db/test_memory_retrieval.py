"""
Phase 9C — Investment Memory retrieval tests.

Covers:
  - get_memory_context() returns None for session=None
  - get_memory_context() returns None for ticker with fewer than 2 queries
  - get_memory_context() returns a populated dict for ticker with ≥ 2 queries
  - _conviction_direction() classification
  - format_memory_for_prompt() produces the correct sentinel boundaries
  - memory_context_for_response() strips version_ids
"""

from __future__ import annotations

import datetime
from typing import Any, Dict

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_version(ticker: str, stance: str, score: float, created_offset_days: int = 0):
    """Return a dict matching ThesisVersion columns (used to seed the DB)."""
    from app.db.models import ThesisVersion
    import datetime

    return ThesisVersion(
        ticker=ticker,
        company_name=ticker + " Corp",
        directional_stance=stance,
        confidence_score=score,
        bull_thesis="Bull.",
        bear_thesis="Bear.",
        conclusion="Conclusion.",
        created_at=datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=created_offset_days),
    )


def _make_memory(ticker: str, total_queries: int, dominant_concern: str = "valuation"):
    """Return a TickerMemory row."""
    from app.db.models import TickerMemory

    return TickerMemory(
        ticker=ticker,
        total_queries=total_queries,
        dominant_concern=dominant_concern,
        last_query_at=datetime.datetime.now(datetime.timezone.utc),
    )


# ---------------------------------------------------------------------------
# Unit tests — pure-Python helpers
# ---------------------------------------------------------------------------

def test_conviction_direction_stable():
    from app.db.repositories.memory_retrieval import _conviction_direction

    # Tiny variance → stable
    assert _conviction_direction([0.70, 0.72]) == "stable"


def test_conviction_direction_rising():
    from app.db.repositories.memory_retrieval import _conviction_direction

    # newest > oldest by >4pp → rising
    assert _conviction_direction([0.80, 0.65]) == "rising"


def test_conviction_direction_falling():
    from app.db.repositories.memory_retrieval import _conviction_direction

    # newest < oldest by >4pp → falling
    assert _conviction_direction([0.60, 0.80]) == "falling"


def test_conviction_direction_volatile():
    from app.db.repositories.memory_retrieval import _conviction_direction

    # Zigzag pattern → volatile
    assert _conviction_direction([0.75, 0.50, 0.80]) == "volatile"


def test_conviction_direction_single_value():
    from app.db.repositories.memory_retrieval import _conviction_direction

    assert _conviction_direction([0.70]) == "stable"


def test_conviction_direction_empty():
    from app.db.repositories.memory_retrieval import _conviction_direction

    assert _conviction_direction([]) == "stable"


# ---------------------------------------------------------------------------
# Async DB-backed tests (use conftest db_session fixture)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_memory_context_none_session():
    """Returns None immediately when session is None."""
    from app.db.repositories.memory_retrieval import get_memory_context

    result = await get_memory_context(None, "NVDA")
    assert result is None


@pytest.mark.asyncio
async def test_get_memory_context_no_memory_row(db_session):
    """Returns None when there is no TickerMemory row for the ticker."""
    from app.db.repositories.memory_retrieval import get_memory_context

    result = await get_memory_context(db_session, "NVDA")
    assert result is None


@pytest.mark.asyncio
async def test_get_memory_context_below_min_queries(db_session):
    """Returns None when total_queries < 2 (first-time analysis)."""
    from app.db.repositories.memory_retrieval import get_memory_context

    mem = _make_memory("NVDA", total_queries=1)
    db_session.add(mem)
    await db_session.commit()

    result = await get_memory_context(db_session, "NVDA")
    assert result is None


@pytest.mark.asyncio
async def test_get_memory_context_populated(db_session):
    """Returns a populated dict when ticker has ≥ 2 prior analyses."""
    from app.db.repositories.memory_retrieval import get_memory_context

    # Seed: TickerMemory + 2 versions
    mem = _make_memory("AAPL", total_queries=3, dominant_concern="valuation")
    v1 = _make_version("AAPL", "bullish", 0.75, created_offset_days=5)
    v2 = _make_version("AAPL", "bullish", 0.68, created_offset_days=10)
    db_session.add_all([mem, v1, v2])
    await db_session.commit()

    result = await get_memory_context(db_session, "AAPL")

    assert result is not None
    assert result["ticker"] == "AAPL"
    assert result["total_queries"] == 3
    assert result["dominant_concern"] == "valuation"
    # Newest version first (v1 is 5 days ago, v2 is 10 days ago)
    assert result["stance_history"][0] == "bullish"
    assert len(result["conviction_trend"]) == 2
    assert "conviction_direction" in result
    assert isinstance(result["days_in_coverage"], int)
    assert result["days_in_coverage"] >= 0
    assert "version_ids" in result


@pytest.mark.asyncio
async def test_get_memory_context_no_versions(db_session):
    """Returns None when TickerMemory exists but no ThesisVersion rows."""
    from app.db.repositories.memory_retrieval import get_memory_context

    mem = _make_memory("MSFT", total_queries=2)
    db_session.add(mem)
    await db_session.commit()

    result = await get_memory_context(db_session, "MSFT")
    assert result is None


@pytest.mark.asyncio
async def test_get_memory_context_filters_zero_conviction(db_session):
    """Versions with confidence_score=0.0 (wall-cap fallbacks) are excluded from trend."""
    from app.db.repositories.memory_retrieval import get_memory_context

    # Seed: 2 real versions + 1 fallback (confidence_score=0.0, newest)
    mem = _make_memory("TSLA", total_queries=3)
    v_real1 = _make_version("TSLA", "bullish", 0.72, created_offset_days=4)
    v_real2 = _make_version("TSLA", "neutral",  0.55, created_offset_days=8)
    v_fallback = _make_version("TSLA", "bullish", 0.0,  created_offset_days=0)  # wall-cap result
    db_session.add_all([mem, v_real1, v_real2, v_fallback])
    await db_session.commit()

    result = await get_memory_context(db_session, "TSLA")

    assert result is not None, "Should find real versions even when newest is a zero-conviction fallback"
    # Zero-conviction fallback must NOT appear in trend
    assert 0.0 not in result["conviction_trend"], "0.0 fallback must be filtered from conviction_trend"
    assert len(result["conviction_trend"]) == 2
    assert result["conviction_trend"][0] == 0.72  # newest valid (5d ago)
    assert result["conviction_trend"][1] == 0.55  # oldest valid


# ---------------------------------------------------------------------------
# format_memory_for_prompt tests
# ---------------------------------------------------------------------------

def _sample_ctx() -> Dict[str, Any]:
    return {
        "ticker": "NVDA",
        "total_queries": 4,
        "days_in_coverage": 12,
        "stance_history": ["bullish", "bullish", "neutral"],
        "conviction_trend": [0.78, 0.72, 0.64],
        "conviction_direction": "rising",
        "dominant_concern": "valuation",
        "concern_distribution": {"valuation": 3, "macro": 1},
        "last_delta_magnitude": "moderate",
        "last_delta_days_ago": 3,
        "stance_changes_total": 1,
        "notable_events": [],
        "version_ids": ["id-1", "id-2", "id-3"],
    }


def test_format_memory_for_prompt_sentinels():
    from app.memory_context import format_memory_for_prompt

    block = format_memory_for_prompt(_sample_ctx())
    assert block.startswith("=== CLEARSIGNAL MEMORY: NVDA ===")
    assert "=== END MEMORY ===" in block


def test_format_memory_for_prompt_empty():
    from app.memory_context import format_memory_for_prompt

    assert format_memory_for_prompt({}) == ""
    assert format_memory_for_prompt(None) == ""  # type: ignore[arg-type]


def test_format_memory_for_prompt_includes_direction():
    from app.memory_context import format_memory_for_prompt

    block = format_memory_for_prompt(_sample_ctx())
    assert "↑ rising" in block


def test_format_memory_for_prompt_includes_concern():
    from app.memory_context import format_memory_for_prompt

    block = format_memory_for_prompt(_sample_ctx())
    assert "valuation" in block


def test_format_memory_for_prompt_includes_llm_instructions():
    from app.memory_context import format_memory_for_prompt

    block = format_memory_for_prompt(_sample_ctx())
    # Single-line context note (verbose MUST-acknowledge block removed to
    # prevent output inflation that breached the synthesis wall cap).
    assert "new evidence takes precedence" in block


# ---------------------------------------------------------------------------
# memory_context_for_response tests
# ---------------------------------------------------------------------------

def test_memory_context_for_response_strips_version_ids():
    from app.memory_context import memory_context_for_response

    ctx = _sample_ctx()
    resp = memory_context_for_response(ctx)

    assert "version_ids" not in resp
    assert resp["ticker"] == "NVDA"
    assert resp["total_queries"] == 4
    assert resp["conviction_direction"] == "rising"


def test_memory_context_for_response_empty():
    from app.memory_context import memory_context_for_response

    assert memory_context_for_response({}) == {}
    assert memory_context_for_response(None) == {}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# MemoryContextSummary schema test
# ---------------------------------------------------------------------------

def test_memory_context_summary_schema():
    """MemoryContextSummary can be instantiated from a memory_context_for_response dict."""
    from app.memory_context import memory_context_for_response
    from app.schemas import MemoryContextSummary

    ctx = _sample_ctx()
    resp = memory_context_for_response(ctx)
    summary = MemoryContextSummary(**resp)

    assert summary.ticker == "NVDA"
    assert summary.total_queries == 4
    assert summary.conviction_direction == "rising"
    assert summary.dominant_concern == "valuation"
    assert summary.last_delta_magnitude == "moderate"
    assert summary.last_delta_days_ago == 3
