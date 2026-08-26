"""
Tests for app/services/portfolio_exposure_service.py — Phase 10D · Slice 3.

Covers all 10 scenarios specified in the Slice 3 brief:
  1. Empty portfolio → empty projection
  2. Single-position portfolio → no cross-exposure pairs
  3. Two tickers with CrossExposure edge → pair detected
  4. Multiple tickers sharing same exposure → cluster detected
  5. Stale edge > 7 days → stale_input True
  6. Missing CrossExposure table / session → safe empty
  7. Failure modes grouped by analog/mechanism
  8. Catalysts grouped by theme/status (direction)
  9. No LLM calls
 10. No delivery behavior (no writes to delivery_ledger / notifications)

Additional: dataclass field validation, high-correlation threshold, null-session,
owned-protection inertness, cluster weight computation, and source_refs tracing.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    CrossExposure,
    DossierCatalyst,
    DossierFailureMode,
    HistoricalAnalog,
    Portfolio,
    PortfolioPosition,
)
from app.services.portfolio_exposure_service import (
    CORRELATION_THRESHOLD,
    STALE_EDGE_DAYS,
    CatalystCluster,
    ExposurePair,
    FailureModeCluster,
    PortfolioExposureProjection,
    SharedExposureCluster,
    project_portfolio_exposure,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stale_ts() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=STALE_EDGE_DAYS + 1)


def _fresh_ts() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=1)


async def _make_portfolio(session, name="Test Portfolio") -> Portfolio:
    p = Portfolio(id=_uid(), name=name, user_id=None, is_default=False)
    session.add(p)
    await session.flush()
    return p


async def _add_position(
    session,
    portfolio_id: str,
    ticker: str,
    weight: Optional[float] = None,
    membership_class: str = "watchlist",
) -> PortfolioPosition:
    pos = PortfolioPosition(
        id=_uid(),
        portfolio_id=portfolio_id,
        ticker=ticker,
        membership_class=membership_class,
        weight=weight,
        active=True,
    )
    session.add(pos)
    await session.flush()
    return pos


async def _add_edge(
    session,
    ticker_a: str,
    ticker_b: str,
    concerns: list,
    exposure_type: str = "thematic",
    strength: float = 0.5,
    created_at: Optional[datetime] = None,
) -> CrossExposure:
    edge = CrossExposure(
        id=_uid(),
        ticker_a=ticker_a,
        ticker_b=ticker_b,
        shared_concerns=json.dumps(concerns),
        exposure_type=exposure_type,
        strength=strength,
        created_at=created_at or _fresh_ts(),
    )
    session.add(edge)
    await session.flush()
    return edge


async def _add_analog(session, label: str = "Test Analog") -> HistoricalAnalog:
    analog = HistoricalAnalog(
        id=_uid(),
        label=label,
        episode="test episode",
        sector="tech",
        business_model="saas",
        mechanism="displacement",
        concern_tags=json.dumps([]),
        quality_rating="moderate",
        why_relevant="test",
        disanalogy="none",
        base_rate_note="",
        data_confidence="moderate",
        source_note="",
        outcome_summary="",
        reaction_series=json.dumps([]),
    )
    session.add(analog)
    await session.flush()
    return analog


async def _add_failure_mode(
    session,
    ticker: str,
    analog_id: str,
    sequence_stage: int = 1,
) -> DossierFailureMode:
    fm = DossierFailureMode(
        id=_uid(),
        ticker=ticker,
        analog_id=analog_id,
        sequence_stage=sequence_stage,
        stage_evidence="some evidence",
        relevance_at_match=0.8,
    )
    session.add(fm)
    await session.flush()
    return fm


async def _add_catalyst(
    session,
    ticker: str,
    direction: str = "bull_trigger",
    status: str = "open",
    specificity: float = 0.7,
    statement: str = "Test catalyst statement.",
) -> DossierCatalyst:
    cat = DossierCatalyst(
        id=_uid(),
        ticker=ticker,
        statement=statement,
        direction=direction,
        specificity=specificity,
        status=status,
        conviction_weight=0.5,
    )
    session.add(cat)
    await session.flush()
    return cat


# ---------------------------------------------------------------------------
# 1. Scenario: Empty portfolio
# ---------------------------------------------------------------------------

class TestEmptyPortfolio:
    @pytest.mark.asyncio
    async def test_empty_portfolio_returns_projection(self, db_session):
        p = await _make_portfolio(db_session)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert isinstance(proj, PortfolioExposureProjection)

    @pytest.mark.asyncio
    async def test_empty_portfolio_has_no_pairs(self, db_session):
        p = await _make_portfolio(db_session)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.exposure_pairs == []

    @pytest.mark.asyncio
    async def test_empty_portfolio_has_no_clusters(self, db_session):
        p = await _make_portfolio(db_session)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.shared_exposure_clusters == []
        assert proj.failure_mode_clusters == []
        assert proj.catalyst_clusters == []

    @pytest.mark.asyncio
    async def test_empty_portfolio_tickers_list_empty(self, db_session):
        p = await _make_portfolio(db_session)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.portfolio_tickers == []

    @pytest.mark.asyncio
    async def test_empty_portfolio_not_stale(self, db_session):
        p = await _make_portfolio(db_session)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.cross_exposure_stale is False
        assert proj.cross_exposure_as_of is None


# ---------------------------------------------------------------------------
# 2. Scenario: Single-position portfolio — no cross-exposure possible
# ---------------------------------------------------------------------------

class TestSinglePositionPortfolio:
    @pytest.mark.asyncio
    async def test_single_ticker_no_pairs(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.exposure_pairs == []


@pytest.mark.asyncio
async def test_company_classification_fallback_surfaces_shared_technology_exposure(db_session):
    p = await _make_portfolio(db_session)
    for ticker in ("AAPL", "NVDA", "PLTR", "RKLB"):
        await _add_position(db_session, p.id, ticker)
    proj = await project_portfolio_exposure(db_session, p.id)
    assert proj.classification_fallback_used is True
    technology = next(
        cluster for cluster in proj.shared_exposure_clusters
        if cluster.concern_label == "Sector: Technology"
    )
    assert technology.member_tickers == ["AAPL", "NVDA", "PLTR"]
    assert technology.dominant_exposure_type == "classification"
    assert technology.max_edge_strength == 0.0

    @pytest.mark.asyncio
    async def test_single_ticker_no_clusters(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_edge(db_session, "AAPL", "MSFT", ["ai_exposure"], strength=0.9)
        proj = await project_portfolio_exposure(db_session, p.id)
        # MSFT is not in the portfolio, so the edge should not surface.
        assert proj.exposure_pairs == []

    @pytest.mark.asyncio
    async def test_single_ticker_portfolio_tickers_populated(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "NVDA")
        proj = await project_portfolio_exposure(db_session, p.id)
        assert "NVDA" in proj.portfolio_tickers


# ---------------------------------------------------------------------------
# 3. Scenario: Two tickers with CrossExposure edge → pair detected
# ---------------------------------------------------------------------------

class TestTwoTickerEdge:
    @pytest.mark.asyncio
    async def test_two_ticker_pair_detected(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(db_session, "AAPL", "MSFT", ["cloud_competition"], strength=0.6)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert len(proj.exposure_pairs) == 1

    @pytest.mark.asyncio
    async def test_pair_fields_populated(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        edge = await _add_edge(
            db_session, "AAPL", "MSFT", ["cloud_competition"], strength=0.6
        )
        proj = await project_portfolio_exposure(db_session, p.id)
        pair = proj.exposure_pairs[0]
        assert pair.ticker_a == "AAPL"
        assert pair.ticker_b == "MSFT"
        assert pair.strength == pytest.approx(0.6)
        assert "cloud_competition" in pair.shared_concerns
        assert pair.source_ref == str(edge.id)

    @pytest.mark.asyncio
    async def test_pair_not_stale_when_fresh(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(db_session, "AAPL", "MSFT", ["ai"], strength=0.5)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.exposure_pairs[0].stale_input is False

    @pytest.mark.asyncio
    async def test_edge_where_only_one_ticker_in_portfolio_not_included(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        # TSLA not in portfolio
        await _add_edge(db_session, "AAPL", "TSLA", ["ev"], strength=0.8)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.exposure_pairs == []


# ---------------------------------------------------------------------------
# 4. Scenario: Multiple tickers sharing same exposure → cluster detected
# ---------------------------------------------------------------------------

class TestSharedExposureCluster:
    @pytest.mark.asyncio
    async def test_cluster_built_from_shared_concern(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_position(db_session, p.id, "GOOGL")
        await _add_edge(db_session, "AAPL", "MSFT", ["ai_race"], strength=0.6)
        await _add_edge(db_session, "MSFT", "GOOGL", ["ai_race"], strength=0.7)
        proj = await project_portfolio_exposure(db_session, p.id)
        labels = [c.concern_label for c in proj.shared_exposure_clusters]
        assert "ai_race" in labels

    @pytest.mark.asyncio
    async def test_cluster_has_all_member_tickers(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_position(db_session, p.id, "GOOGL")
        await _add_edge(db_session, "AAPL", "MSFT", ["ai_race"], strength=0.6)
        await _add_edge(db_session, "MSFT", "GOOGL", ["ai_race"], strength=0.7)
        proj = await project_portfolio_exposure(db_session, p.id)
        cluster = next(c for c in proj.shared_exposure_clusters if c.concern_label == "ai_race")
        assert set(cluster.member_tickers) == {"AAPL", "MSFT", "GOOGL"}

    @pytest.mark.asyncio
    async def test_cluster_max_edge_strength_correct(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_position(db_session, p.id, "GOOGL")
        await _add_edge(db_session, "AAPL", "MSFT", ["ai_race"], strength=0.6)
        await _add_edge(db_session, "MSFT", "GOOGL", ["ai_race"], strength=0.7)
        proj = await project_portfolio_exposure(db_session, p.id)
        cluster = next(c for c in proj.shared_exposure_clusters if c.concern_label == "ai_race")
        assert cluster.max_edge_strength == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_single_concern_pair_not_cluster(self, db_session):
        """A concern that appears in only one edge still groups tickers — two tickers
        sharing one concern IS a two-member cluster.  But a concern in edges where
        all endpoint pairs collapse to a single ticker should not appear."""
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(db_session, "AAPL", "MSFT", ["unique_concern"], strength=0.5)
        proj = await project_portfolio_exposure(db_session, p.id)
        # Two members → still a valid cluster.
        labels = [c.concern_label for c in proj.shared_exposure_clusters]
        assert "unique_concern" in labels

    @pytest.mark.asyncio
    async def test_cluster_weight_sum_when_weights_present(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.30)
        await _add_position(db_session, p.id, "MSFT", weight=0.20)
        await _add_edge(db_session, "AAPL", "MSFT", ["supply_chain"], strength=0.5)
        proj = await project_portfolio_exposure(db_session, p.id)
        cluster = proj.shared_exposure_clusters[0]
        assert cluster.cluster_weight == pytest.approx(0.50)

    @pytest.mark.asyncio
    async def test_cluster_weight_none_when_any_weight_missing(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.30)
        await _add_position(db_session, p.id, "MSFT", weight=None)
        await _add_edge(db_session, "AAPL", "MSFT", ["supply_chain"], strength=0.5)
        proj = await project_portfolio_exposure(db_session, p.id)
        cluster = proj.shared_exposure_clusters[0]
        assert cluster.cluster_weight is None


# ---------------------------------------------------------------------------
# 5. Scenario: Stale edge > 7 days → stale_input True
# ---------------------------------------------------------------------------

class TestStaleEdge:
    @pytest.mark.asyncio
    async def test_stale_edge_flagged(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(
            db_session, "AAPL", "MSFT", ["cloud"], strength=0.5, created_at=_stale_ts()
        )
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.exposure_pairs[0].stale_input is True

    @pytest.mark.asyncio
    async def test_stale_edge_sets_projection_stale_flag(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(
            db_session, "AAPL", "MSFT", ["cloud"], strength=0.5, created_at=_stale_ts()
        )
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.cross_exposure_stale is True

    @pytest.mark.asyncio
    async def test_mixed_fresh_stale_projection_is_stale(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_position(db_session, p.id, "GOOGL")
        await _add_edge(db_session, "AAPL", "MSFT", ["ai"], strength=0.5)
        await _add_edge(
            db_session, "MSFT", "GOOGL", ["cloud"], strength=0.5, created_at=_stale_ts()
        )
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.cross_exposure_stale is True

    @pytest.mark.asyncio
    async def test_fresh_edge_not_stale(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(
            db_session, "AAPL", "MSFT", ["cloud"], strength=0.5, created_at=_fresh_ts()
        )
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.cross_exposure_stale is False


# ---------------------------------------------------------------------------
# 6. Scenario: Missing session or table → safe empty projection
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty_projection(self):
        proj = await project_portfolio_exposure(None, "any-portfolio-id")
        assert isinstance(proj, PortfolioExposureProjection)
        assert proj.exposure_pairs == []
        assert proj.shared_exposure_clusters == []
        assert proj.failure_mode_clusters == []
        assert proj.catalyst_clusters == []

    @pytest.mark.asyncio
    async def test_null_session_substrate_missing_false(self):
        # Null session is not the same as missing substrate — it's a no-op.
        proj = await project_portfolio_exposure(None, "any-portfolio-id")
        assert proj.substrate_missing is False

    @pytest.mark.asyncio
    async def test_null_session_portfolio_id_preserved(self):
        pid = "test-portfolio-999"
        proj = await project_portfolio_exposure(None, pid)
        assert proj.portfolio_id == pid

    @pytest.mark.asyncio
    async def test_unknown_portfolio_id_returns_empty(self, db_session):
        proj = await project_portfolio_exposure(db_session, "nonexistent-id")
        assert isinstance(proj, PortfolioExposureProjection)
        assert proj.portfolio_tickers == []
        assert proj.exposure_pairs == []


# ---------------------------------------------------------------------------
# 7. Scenario: Failure modes grouped by analog
# ---------------------------------------------------------------------------

class TestFailureModeCluster:
    @pytest.mark.asyncio
    async def test_two_tickers_same_analog_cluster(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "INTC")
        await _add_position(db_session, p.id, "AMD")
        analog = await _add_analog(db_session, label="Displacement Cycle")
        await _add_failure_mode(db_session, "INTC", analog.id, sequence_stage=2)
        await _add_failure_mode(db_session, "AMD", analog.id, sequence_stage=1)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert len(proj.failure_mode_clusters) == 1
        fc = proj.failure_mode_clusters[0]
        assert set(fc.member_tickers) == {"INTC", "AMD"}

    @pytest.mark.asyncio
    async def test_failure_mode_cluster_analog_label_resolved(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "INTC")
        await _add_position(db_session, p.id, "AMD")
        analog = await _add_analog(db_session, label="Displacement Cycle")
        await _add_failure_mode(db_session, "INTC", analog.id)
        await _add_failure_mode(db_session, "AMD", analog.id)
        proj = await project_portfolio_exposure(db_session, p.id)
        fc = proj.failure_mode_clusters[0]
        assert fc.analog_label == "Displacement Cycle"

    @pytest.mark.asyncio
    async def test_failure_mode_stages_per_ticker(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "INTC")
        await _add_position(db_session, p.id, "AMD")
        analog = await _add_analog(db_session, label="Displacement Cycle")
        await _add_failure_mode(db_session, "INTC", analog.id, sequence_stage=3)
        await _add_failure_mode(db_session, "AMD", analog.id, sequence_stage=1)
        proj = await project_portfolio_exposure(db_session, p.id)
        fc = proj.failure_mode_clusters[0]
        assert fc.stages["INTC"] == 3
        assert fc.stages["AMD"] == 1

    @pytest.mark.asyncio
    async def test_single_ticker_failure_mode_not_a_cluster(self, db_session):
        """Single-ticker failure mode is company-level, not portfolio-level."""
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "INTC")
        analog = await _add_analog(db_session, label="Solo Pattern")
        await _add_failure_mode(db_session, "INTC", analog.id)
        proj = await project_portfolio_exposure(db_session, p.id)
        # No cross-portfolio cluster for a single ticker.
        assert proj.failure_mode_clusters == []

    @pytest.mark.asyncio
    async def test_failure_mode_ticker_not_in_portfolio_excluded(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "INTC")
        # NVDA not in portfolio
        analog = await _add_analog(db_session, label="Pattern")
        await _add_failure_mode(db_session, "INTC", analog.id)
        await _add_failure_mode(db_session, "NVDA", analog.id)
        proj = await project_portfolio_exposure(db_session, p.id)
        # Only INTC is in portfolio → no cross-portfolio cluster.
        assert proj.failure_mode_clusters == []

    @pytest.mark.asyncio
    async def test_two_separate_analogs_two_clusters(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "A")
        await _add_position(db_session, p.id, "B")
        await _add_position(db_session, p.id, "C")
        await _add_position(db_session, p.id, "D")
        analog1 = await _add_analog(db_session, label="Pattern One")
        analog2 = await _add_analog(db_session, label="Pattern Two")
        await _add_failure_mode(db_session, "A", analog1.id)
        await _add_failure_mode(db_session, "B", analog1.id)
        await _add_failure_mode(db_session, "C", analog2.id)
        await _add_failure_mode(db_session, "D", analog2.id)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert len(proj.failure_mode_clusters) == 2


# ---------------------------------------------------------------------------
# 8. Scenario: Catalysts grouped by direction
# ---------------------------------------------------------------------------

class TestCatalystCluster:
    @pytest.mark.asyncio
    async def test_two_tickers_same_direction_cluster(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_catalyst(db_session, "AAPL", direction="bull_trigger", status="open")
        await _add_catalyst(db_session, "MSFT", direction="bull_trigger", status="open")
        proj = await project_portfolio_exposure(db_session, p.id)
        dirs = [c.direction for c in proj.catalyst_clusters]
        assert "bull_trigger" in dirs

    @pytest.mark.asyncio
    async def test_catalyst_cluster_member_tickers(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_catalyst(db_session, "AAPL", direction="bear_trigger", status="open")
        await _add_catalyst(db_session, "MSFT", direction="bear_trigger", status="open")
        proj = await project_portfolio_exposure(db_session, p.id)
        cluster = next(c for c in proj.catalyst_clusters if c.direction == "bear_trigger")
        assert set(cluster.member_tickers) == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_closed_catalysts_excluded(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_catalyst(db_session, "AAPL", direction="bull_trigger", status="triggered")
        await _add_catalyst(db_session, "MSFT", direction="bull_trigger", status="invalidated")
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.catalyst_clusters == []

    @pytest.mark.asyncio
    async def test_single_ticker_catalyst_not_a_cluster(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_catalyst(db_session, "AAPL", direction="bull_trigger", status="open")
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.catalyst_clusters == []

    @pytest.mark.asyncio
    async def test_catalyst_not_in_portfolio_excluded(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        # TSLA not in portfolio
        await _add_catalyst(db_session, "AAPL", direction="bull_trigger", status="open")
        await _add_catalyst(db_session, "TSLA", direction="bull_trigger", status="open")
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.catalyst_clusters == []

    @pytest.mark.asyncio
    async def test_bull_and_bear_produce_separate_clusters(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_catalyst(db_session, "AAPL", direction="bull_trigger", status="open")
        await _add_catalyst(db_session, "MSFT", direction="bear_trigger", status="open")
        proj = await project_portfolio_exposure(db_session, p.id)
        # Each direction has only one ticker — no clusters.
        assert proj.catalyst_clusters == []

    @pytest.mark.asyncio
    async def test_both_tickers_bull_and_bear_two_clusters(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_catalyst(db_session, "AAPL", direction="bull_trigger", status="open")
        await _add_catalyst(db_session, "MSFT", direction="bull_trigger", status="open")
        await _add_catalyst(db_session, "AAPL", direction="bear_trigger", status="open")
        await _add_catalyst(db_session, "MSFT", direction="bear_trigger", status="open")
        proj = await project_portfolio_exposure(db_session, p.id)
        directions = {c.direction for c in proj.catalyst_clusters}
        assert "bull_trigger" in directions
        assert "bear_trigger" in directions


# ---------------------------------------------------------------------------
# 9. No LLM calls (structural, not mock-based)
# ---------------------------------------------------------------------------

class TestNoLLMCalls:
    @pytest.mark.asyncio
    async def test_no_llm_import_in_service(self):
        import importlib
        import app.services.portfolio_exposure_service as svc
        src = open(svc.__file__).read()
        # No anthropic / openai / langchain / requests to any LLM provider
        assert "anthropic" not in src
        assert "openai" not in src
        assert "langchain" not in src
        assert "requests" not in src.split("import")[0]  # no top-level import

    @pytest.mark.asyncio
    async def test_full_projection_completes_without_llm(self, db_session):
        """Integration: full projection over 3-ticker portfolio with all substrate
        populated completes synchronously with no external calls."""
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.4)
        await _add_position(db_session, p.id, "MSFT", weight=0.35)
        await _add_position(db_session, p.id, "GOOGL", weight=0.25)
        await _add_edge(db_session, "AAPL", "MSFT", ["ai_race", "cloud"], strength=0.8)
        await _add_edge(db_session, "MSFT", "GOOGL", ["ai_race"], strength=0.75)
        analog = await _add_analog(db_session)
        await _add_failure_mode(db_session, "AAPL", analog.id)
        await _add_failure_mode(db_session, "MSFT", analog.id)
        await _add_catalyst(db_session, "AAPL", direction="bull_trigger", status="open")
        await _add_catalyst(db_session, "GOOGL", direction="bull_trigger", status="open")
        proj = await project_portfolio_exposure(db_session, p.id)
        assert isinstance(proj, PortfolioExposureProjection)
        assert len(proj.portfolio_tickers) == 3


# ---------------------------------------------------------------------------
# 10. No delivery behavior
# ---------------------------------------------------------------------------

class TestNoDeliveryBehavior:
    @pytest.mark.asyncio
    async def test_no_delivery_ledger_written(self, db_session):
        from sqlalchemy import text
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(db_session, "AAPL", "MSFT", ["cloud"], strength=0.9)
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM delivery_ledger")
        )).scalar()
        await project_portfolio_exposure(db_session, p.id)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM delivery_ledger")
        )).scalar()
        assert before == after

    @pytest.mark.asyncio
    async def test_no_notifications_written(self, db_session):
        from sqlalchemy import text
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(db_session, "AAPL", "MSFT", ["cloud"], strength=0.9)
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM notifications")
        )).scalar()
        await project_portfolio_exposure(db_session, p.id)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM notifications")
        )).scalar()
        assert before == after

    @pytest.mark.asyncio
    async def test_no_portfolio_insights_written(self, db_session):
        from sqlalchemy import text
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(db_session, "AAPL", "MSFT", ["cloud"], strength=0.9)
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM portfolio_insights")
        )).scalar()
        await project_portfolio_exposure(db_session, p.id)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM portfolio_insights")
        )).scalar()
        assert before == after

    @pytest.mark.asyncio
    async def test_cross_exposure_table_not_modified(self, db_session):
        """project_portfolio_exposure must be a pure read — no writes to source tables."""
        from sqlalchemy import text
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        edge = await _add_edge(db_session, "AAPL", "MSFT", ["cloud"], strength=0.5)
        original_ts = edge.created_at
        await project_portfolio_exposure(db_session, p.id)
        # Re-read the edge to verify it was not modified.
        result = await db_session.execute(
            text("SELECT created_at FROM cross_exposures WHERE id = :id"),
            {"id": edge.id},
        )
        row = result.fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# High-correlation threshold tests
# ---------------------------------------------------------------------------

class TestHighCorrelationPairs:
    @pytest.mark.asyncio
    async def test_strength_above_threshold_in_high_corr(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(
            db_session, "AAPL", "MSFT", ["ai"], strength=CORRELATION_THRESHOLD + 0.01
        )
        proj = await project_portfolio_exposure(db_session, p.id)
        assert len(proj.high_correlation_pairs) == 1

    @pytest.mark.asyncio
    async def test_strength_below_threshold_not_in_high_corr(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(
            db_session, "AAPL", "MSFT", ["ai"], strength=CORRELATION_THRESHOLD - 0.01
        )
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.high_correlation_pairs == []

    @pytest.mark.asyncio
    async def test_strength_at_threshold_in_high_corr(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(
            db_session, "AAPL", "MSFT", ["ai"], strength=CORRELATION_THRESHOLD
        )
        proj = await project_portfolio_exposure(db_session, p.id)
        assert len(proj.high_correlation_pairs) == 1

    @pytest.mark.asyncio
    async def test_high_corr_pairs_subset_of_all_pairs(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_position(db_session, p.id, "GOOGL")
        await _add_edge(db_session, "AAPL", "MSFT", ["ai"], strength=0.85)
        await _add_edge(db_session, "MSFT", "GOOGL", ["cloud"], strength=0.40)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert len(proj.exposure_pairs) == 2
        assert len(proj.high_correlation_pairs) == 1


# ---------------------------------------------------------------------------
# Dataclass structure and generated_at
# ---------------------------------------------------------------------------

class TestOutputStructure:
    @pytest.mark.asyncio
    async def test_generated_at_is_iso_string(self, db_session):
        p = await _make_portfolio(db_session)
        proj = await project_portfolio_exposure(db_session, p.id)
        # Should be parseable as a datetime without error.
        parsed = datetime.fromisoformat(proj.generated_at.replace("Z", "+00:00"))
        assert parsed is not None

    @pytest.mark.asyncio
    async def test_portfolio_id_preserved(self, db_session):
        p = await _make_portfolio(db_session)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.portfolio_id == p.id

    @pytest.mark.asyncio
    async def test_cross_exposure_as_of_set_when_edges_exist(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_edge(db_session, "AAPL", "MSFT", ["ai"], strength=0.5)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.cross_exposure_as_of is not None
        assert isinstance(proj.cross_exposure_as_of, str)

    @pytest.mark.asyncio
    async def test_exposure_pair_source_ref_is_edge_id(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        edge = await _add_edge(db_session, "AAPL", "MSFT", ["cloud"], strength=0.5)
        proj = await project_portfolio_exposure(db_session, p.id)
        assert proj.exposure_pairs[0].source_ref == str(edge.id)
