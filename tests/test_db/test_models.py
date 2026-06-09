"""
Tests for Phase 9A ORM models — create tables, write and read objects.

Uses the db_session fixture (SQLite in-memory) from conftest.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio


@pytest.mark.asyncio
async def test_thesis_version_roundtrip(db_session):
    """Create a ThesisVersion, flush, then query it back."""
    from app.db.models import ThesisVersion

    row = ThesisVersion(
        id=str(uuid.uuid4()),
        ticker="NVDA",
        company_name="NVIDIA Corporation",
        session_id="sess-001",
        question="What is the capex sensitivity?",
        directional_stance="bullish",
        confidence_score=0.72,
        bull_thesis="Blackwell ramp accelerates.",
        bear_thesis="Custom silicon erodes share.",
        verdict_rationale="Conviction bullish.",
        direct_answer="~$31-38B revenue haircut.",
        why_not="Concentration risk caps upside.",
        conclusion="Hold with monitoring.",
        key_drivers=json.dumps(["Blackwell", "sovereign AI"]),
        key_risks=json.dumps(["custom silicon"]),
        macro_sensitivity=json.dumps({"rate_sensitivity": "low"}),
        threshold_zones=json.dumps({"bull_break": "capex ratio > 12x"}),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    await db_session.flush()

    from sqlalchemy import select
    result = await db_session.execute(
        select(ThesisVersion).where(ThesisVersion.ticker == "NVDA")
    )
    fetched = result.scalar_one()
    assert fetched.ticker == "NVDA"
    assert fetched.directional_stance == "bullish"
    assert abs(fetched.confidence_score - 0.72) < 0.001
    assert fetched.bull_thesis == "Blackwell ramp accelerates."


@pytest.mark.asyncio
async def test_thesis_delta_roundtrip(db_session):
    """Create two ThesisVersions and a ThesisDelta; verify fields."""
    from app.db.models import ThesisVersion, ThesisDelta

    v1 = ThesisVersion(
        id=str(uuid.uuid4()),
        ticker="COST",
        company_name="Costco",
        session_id="s1",
        question="Q1",
        directional_stance="bullish",
        confidence_score=0.65,
        bull_thesis="Membership fee moat.",
        bear_thesis="Margin compression risk.",
        verdict_rationale="Hold.",
        direct_answer="Strong.",
        why_not="Valuation premium.",
        conclusion="Buy.",
        key_drivers="[]", key_risks="[]",
        macro_sensitivity="{}", threshold_zones="{}",
        created_at=datetime.now(timezone.utc),
    )
    v2 = ThesisVersion(
        id=str(uuid.uuid4()),
        ticker="COST",
        company_name="Costco",
        session_id="s2",
        question="Q2",
        directional_stance="neutral",  # changed
        confidence_score=0.50,          # changed
        bull_thesis="Membership fee moat still intact.",
        bear_thesis="Margin compression accelerating.",
        verdict_rationale="Reassessing.",
        direct_answer="Mixed signals.",
        why_not="Valuation.",
        conclusion="Hold.",
        key_drivers="[]", key_risks="[]",
        macro_sensitivity="{}", threshold_zones="{}",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(v1)
    db_session.add(v2)
    await db_session.flush()

    delta = ThesisDelta(
        id=str(uuid.uuid4()),
        ticker="COST",
        from_version_id=v1.id,
        to_version_id=v2.id,
        stance_changed=True,
        conviction_delta=-0.15,
        bull_thesis_similarity=0.75,
        bear_thesis_similarity=0.60,
        magnitude="material",
        changed_fields=json.dumps(["directional_stance", "confidence_score", "bear_thesis"]),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(delta)
    await db_session.flush()

    from sqlalchemy import select
    result = await db_session.execute(
        select(ThesisDelta).where(ThesisDelta.ticker == "COST")
    )
    fetched = result.scalar_one()
    assert fetched.magnitude == "material"
    assert fetched.stance_changed is True
    assert abs(fetched.conviction_delta - (-0.15)) < 0.001


@pytest.mark.asyncio
async def test_ticker_memory_roundtrip(db_session):
    """Create and query TickerMemory."""
    from app.db.models import TickerMemory

    row = TickerMemory(
        id=str(uuid.uuid4()),
        ticker="AAPL",
        company_name="Apple Inc.",
        total_queries=5,
        version_count=3,
        last_stance="bullish",
        last_confidence=0.68,
        dominant_concern="regulatory_risk",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    await db_session.flush()

    from sqlalchemy import select
    result = await db_session.execute(
        select(TickerMemory).where(TickerMemory.ticker == "AAPL")
    )
    fetched = result.scalar_one()
    assert fetched.total_queries == 5
    assert fetched.dominant_concern == "regulatory_risk"


@pytest.mark.asyncio
async def test_concern_tag_unique_constraint(db_session):
    """Two ConcernTag rows with the same (ticker, tag_name) should violate unique constraint."""
    from app.db.models import ConcernTag

    tag1 = ConcernTag(
        id=str(uuid.uuid4()),
        ticker="JPM",
        tag_name="cre_credit_risk",
        mention_count=1,
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    tag2 = ConcernTag(
        id=str(uuid.uuid4()),
        ticker="JPM",
        tag_name="cre_credit_risk",  # duplicate
        mention_count=2,
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(tag1)
    db_session.add(tag2)
    with pytest.raises(Exception):  # IntegrityError on flush
        await db_session.flush()
    # Rollback so the session is clean for the fixture teardown
    await db_session.rollback()


@pytest.mark.asyncio
async def test_memory_entry_roundtrip(db_session):
    """Create a MemoryEntry and query it back."""
    from app.db.models import MemoryEntry

    row = MemoryEntry(
        id=str(uuid.uuid4()),
        ticker="MSFT",
        session_id="session-xyz",
        entry_type="analysis",
        content="Q: Azure Copilot materiality? Stance: bullish Conviction: 0.71",
        metadata_json=json.dumps({"directional_stance": "bullish", "confidence_score": 0.71}),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    await db_session.flush()

    from sqlalchemy import select
    result = await db_session.execute(
        select(MemoryEntry).where(MemoryEntry.ticker == "MSFT")
    )
    fetched = result.scalar_one()
    assert fetched.entry_type == "analysis"
    meta = json.loads(fetched.metadata_json)
    assert meta["directional_stance"] == "bullish"


@pytest.mark.asyncio
async def test_all_nine_tables_exist(db_session):
    """Verify all 9 ORM classes can be imported and flushed without error."""
    from app.db.models import (
        ThesisVersion, ThesisDelta, TickerMemory, MemoryEntry,
        ConcernTag, ThemeCluster, CrossExposure, PersonalizedInsight,
        BriefingSession,
    )
    from datetime import date

    now = datetime.now(timezone.utc)

    cluster = ThemeCluster(
        id=str(uuid.uuid4()),
        cluster_label="AI infrastructure",
        tickers=json.dumps(["NVDA", "MSFT"]),
        concern_overlap=json.dumps({"capex_cycle": 4}),
        created_at=now, updated_at=now,
    )
    exposure = CrossExposure(
        id=str(uuid.uuid4()),
        ticker_a="NVDA", ticker_b="MSFT",
        shared_concerns=json.dumps(["capex_cycle"]),
        exposure_type="thematic",
        strength=0.8,
        created_at=now,
    )
    insight = PersonalizedInsight(
        id=str(uuid.uuid4()),
        session_id="s1", ticker="NVDA",
        insight_type="recurring_concern",
        insight_text="capex_cycle mentioned 4 of last 5 sessions",
        supporting_data=json.dumps({}),
        created_at=now,
    )
    briefing = BriefingSession(
        id=str(uuid.uuid4()),
        session_date=date.today(),
        session_id="b1",
        tickers_covered=json.dumps(["NVDA"]),
        status="pending",
        metadata_json=json.dumps({}),
        created_at=now,
    )
    for obj in [cluster, exposure, insight, briefing]:
        db_session.add(obj)
    await db_session.flush()
    # If we get here without exception, all tables exist and accept writes.
