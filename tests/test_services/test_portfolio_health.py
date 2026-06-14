"""
Tests for app/services/portfolio_health_service.py — Phase 10D · Slice 4.

Covers all 11 specified test scenarios:
  1. Empty portfolio
  2. Single position
  3. Equal-weight fallback
  4. Explicit weights
  5. HHI correctness
  6. Top-N concentration correctness
  7. Effective-N correctness
  8. owned/watchlist/on_radar counts
  9. Missing regime substrate safe empty
 10. No price fields used (structural)
 11. No forbidden metrics present (structural)

Additional: weight normalization, theme exposure, regime sensitivity,
warning generation, null-session, no-write guarantees.
"""

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    CrossExposure,
    DossierDurability,
    Portfolio,
    PortfolioPosition,
    ThesisVersion,
)
from app.services.portfolio_health_service import (
    TOP_N,
    ConcentrationMetrics,
    DiversificationMetrics,
    HealthWarning,
    PortfolioHealthReport,
    RegimeSensitivitySummary,
    ThemeExposure,
    compute_portfolio_health,
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


async def _make_portfolio(session, name: str = "Test") -> Portfolio:
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
    strength: float = 0.5,
) -> CrossExposure:
    edge = CrossExposure(
        id=_uid(),
        ticker_a=ticker_a,
        ticker_b=ticker_b,
        shared_concerns=json.dumps(concerns),
        exposure_type="thematic",
        strength=strength,
        created_at=_now(),
    )
    session.add(edge)
    await session.flush()
    return edge


async def _add_durability(
    session,
    ticker: str,
    cycle_position: str = "mid",
    conviction_trend: str = "stable",
    horizon_hint: str = "investment",
) -> DossierDurability:
    row = DossierDurability(
        id=_uid(),
        ticker=ticker,
        cycle_position=cycle_position,
        conviction_trend=conviction_trend,
        horizon_hint=horizon_hint,
    )
    session.add(row)
    await session.flush()
    return row


async def _add_thesis(
    session,
    ticker: str,
    macro_sensitivity: Optional[dict] = None,
) -> ThesisVersion:
    tv = ThesisVersion(
        id=_uid(),
        ticker=ticker,
        company_name=ticker,
        session_id="test",
        macro_sensitivity=json.dumps(macro_sensitivity or {}),
        key_drivers="[]",
        key_risks="[]",
        threshold_zones="{}",
    )
    session.add(tv)
    await session.flush()
    return tv


# ---------------------------------------------------------------------------
# 1. Empty portfolio
# ---------------------------------------------------------------------------

class TestEmptyPortfolio:
    @pytest.mark.asyncio
    async def test_empty_returns_report(self, db_session):
        p = await _make_portfolio(db_session)
        report = await compute_portfolio_health(db_session, p.id)
        assert isinstance(report, PortfolioHealthReport)

    @pytest.mark.asyncio
    async def test_empty_position_count_zero(self, db_session):
        p = await _make_portfolio(db_session)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.concentration.position_count == 0

    @pytest.mark.asyncio
    async def test_empty_hhi_zero(self, db_session):
        p = await _make_portfolio(db_session)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.concentration.hhi == 0.0

    @pytest.mark.asyncio
    async def test_empty_theme_exposure_empty(self, db_session):
        p = await _make_portfolio(db_session)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.theme_exposure == []

    @pytest.mark.asyncio
    async def test_empty_warning_code_present(self, db_session):
        p = await _make_portfolio(db_session)
        report = await compute_portfolio_health(db_session, p.id)
        codes = [w.code for w in report.warnings]
        assert "EMPTY_PORTFOLIO" in codes

    @pytest.mark.asyncio
    async def test_empty_portfolio_id_preserved(self, db_session):
        p = await _make_portfolio(db_session)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.portfolio_id == p.id


# ---------------------------------------------------------------------------
# 2. Single position
# ---------------------------------------------------------------------------

class TestSinglePosition:
    @pytest.mark.asyncio
    async def test_single_position_count_one(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=1.0)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.concentration.position_count == 1

    @pytest.mark.asyncio
    async def test_single_position_hhi_is_one(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=1.0)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.concentration.hhi == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_single_position_effective_n_is_one(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=1.0)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.concentration.effective_n == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_single_position_warning_single_position(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=1.0)
        report = await compute_portfolio_health(db_session, p.id)
        codes = [w.code for w in report.warnings]
        assert "SINGLE_POSITION" in codes

    @pytest.mark.asyncio
    async def test_single_position_no_cross_exposure_pairs(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=1.0)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.theme_exposure == []


# ---------------------------------------------------------------------------
# 3. Equal-weight fallback
# ---------------------------------------------------------------------------

class TestEqualWeightFallback:
    @pytest.mark.asyncio
    async def test_no_weights_triggers_fallback(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=None)
        await _add_position(db_session, p.id, "MSFT", weight=None)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.weight_source == "equal_weight_fallback"

    @pytest.mark.asyncio
    async def test_partial_weights_triggers_fallback(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.6)
        await _add_position(db_session, p.id, "MSFT", weight=None)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.weight_source == "equal_weight_fallback"

    @pytest.mark.asyncio
    async def test_equal_weight_hhi_is_one_over_n(self, db_session):
        p = await _make_portfolio(db_session)
        for ticker in ["AAPL", "MSFT", "GOOGL", "AMZN"]:
            await _add_position(db_session, p.id, ticker, weight=None)
        report = await compute_portfolio_health(db_session, p.id)
        # Equal weight for 4 positions: HHI = 4 * (0.25)^2 = 0.25
        assert report.concentration.hhi == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_equal_weight_fallback_warning_emitted(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=None)
        await _add_position(db_session, p.id, "MSFT", weight=None)
        report = await compute_portfolio_health(db_session, p.id)
        codes = [w.code for w in report.warnings]
        assert "EQUAL_WEIGHT_FALLBACK" in codes

    @pytest.mark.asyncio
    async def test_equal_weight_theme_cumulative_weight_none(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=None)
        await _add_position(db_session, p.id, "MSFT", weight=None)
        await _add_edge(db_session, "AAPL", "MSFT", ["cloud"])
        report = await compute_portfolio_health(db_session, p.id)
        # With equal-weight fallback, cumulative_weight on theme is None.
        assert all(t.cumulative_weight is None for t in report.theme_exposure)


# ---------------------------------------------------------------------------
# 4. Explicit weights
# ---------------------------------------------------------------------------

class TestExplicitWeights:
    @pytest.mark.asyncio
    async def test_all_weights_present_explicit(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.60)
        await _add_position(db_session, p.id, "MSFT", weight=0.40)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.weight_source == "explicit"

    @pytest.mark.asyncio
    async def test_explicit_weights_normalized(self, db_session):
        """Weights that don't sum to 1.0 are normalized."""
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=60.0)
        await _add_position(db_session, p.id, "MSFT", weight=40.0)
        report = await compute_portfolio_health(db_session, p.id)
        # After normalization: 0.6 and 0.4.  HHI = 0.6^2 + 0.4^2 = 0.52
        assert report.concentration.hhi == pytest.approx(0.36 + 0.16)
        assert report.weight_source == "explicit"

    @pytest.mark.asyncio
    async def test_explicit_weights_theme_cumulative_weight_populated(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.60)
        await _add_position(db_session, p.id, "MSFT", weight=0.40)
        await _add_edge(db_session, "AAPL", "MSFT", ["cloud"])
        report = await compute_portfolio_health(db_session, p.id)
        assert len(report.theme_exposure) == 1
        # cumulative weight of AAPL (0.6) + MSFT (0.4) = 1.0
        assert report.theme_exposure[0].cumulative_weight == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 5. HHI correctness
# ---------------------------------------------------------------------------

class TestHHI:
    @pytest.mark.asyncio
    async def test_hhi_two_equal_positions(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.5)
        await _add_position(db_session, p.id, "MSFT", weight=0.5)
        report = await compute_portfolio_health(db_session, p.id)
        # HHI = 0.5^2 + 0.5^2 = 0.5
        assert report.concentration.hhi == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_hhi_three_equal_positions(self, db_session):
        p = await _make_portfolio(db_session)
        for t in ["A", "B", "C"]:
            await _add_position(db_session, p.id, t, weight=None)
        report = await compute_portfolio_health(db_session, p.id)
        # Equal weight: HHI = 3 * (1/3)^2 = 1/3
        assert report.concentration.hhi == pytest.approx(1.0 / 3.0, rel=1e-5)

    @pytest.mark.asyncio
    async def test_hhi_concentrated_portfolio(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.90)
        await _add_position(db_session, p.id, "MSFT", weight=0.10)
        report = await compute_portfolio_health(db_session, p.id)
        # HHI = 0.81 + 0.01 = 0.82
        assert report.concentration.hhi == pytest.approx(0.82)

    @pytest.mark.asyncio
    async def test_hhi_ten_equal_positions(self, db_session):
        p = await _make_portfolio(db_session)
        for i in range(10):
            await _add_position(db_session, p.id, f"T{i}", weight=None)
        report = await compute_portfolio_health(db_session, p.id)
        # HHI = 10 * 0.1^2 = 0.1
        assert report.concentration.hhi == pytest.approx(0.1, rel=1e-5)

    @pytest.mark.asyncio
    async def test_high_hhi_warning_emitted(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.90)
        await _add_position(db_session, p.id, "MSFT", weight=0.10)
        report = await compute_portfolio_health(db_session, p.id)
        codes = [w.code for w in report.warnings]
        assert "VERY_HIGH_CONCENTRATION" in codes

    @pytest.mark.asyncio
    async def test_medium_hhi_warning_emitted(self, db_session):
        p = await _make_portfolio(db_session)
        # 3 equal positions: HHI = 1/3 ≈ 0.333 > HIGH_HHI_THRESHOLD (0.25)
        for t in ["A", "B", "C"]:
            await _add_position(db_session, p.id, t, weight=None)
        report = await compute_portfolio_health(db_session, p.id)
        codes = [w.code for w in report.warnings]
        assert "HIGH_CONCENTRATION" in codes or "VERY_HIGH_CONCENTRATION" in codes

    @pytest.mark.asyncio
    async def test_low_hhi_no_concentration_warning(self, db_session):
        p = await _make_portfolio(db_session)
        # 10 equal positions: HHI = 0.1 < HIGH_HHI_THRESHOLD
        for i in range(10):
            await _add_position(db_session, p.id, f"T{i}", weight=None)
        report = await compute_portfolio_health(db_session, p.id)
        codes = [w.code for w in report.warnings]
        assert "HIGH_CONCENTRATION" not in codes
        assert "VERY_HIGH_CONCENTRATION" not in codes


# ---------------------------------------------------------------------------
# 6. Top-N concentration correctness
# ---------------------------------------------------------------------------

class TestTopNConcentration:
    @pytest.mark.asyncio
    async def test_top1_weight_is_largest_position(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.50)
        await _add_position(db_session, p.id, "MSFT", weight=0.30)
        await _add_position(db_session, p.id, "GOOGL", weight=0.20)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.concentration.top_n_weight[1] == pytest.approx(0.50)

    @pytest.mark.asyncio
    async def test_top3_cumulative_weight(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "A", weight=0.40)
        await _add_position(db_session, p.id, "B", weight=0.30)
        await _add_position(db_session, p.id, "C", weight=0.20)
        await _add_position(db_session, p.id, "D", weight=0.10)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.concentration.top_n_weight[3] == pytest.approx(0.90)

    @pytest.mark.asyncio
    async def test_top_n_capped_at_position_count(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.6)
        await _add_position(db_session, p.id, "MSFT", weight=0.4)
        report = await compute_portfolio_health(db_session, p.id)
        # Only 2 positions — top_n_used = 2, keys only go up to 2.
        assert report.concentration.top_n_used == 2
        assert 3 not in report.concentration.top_n_weight

    @pytest.mark.asyncio
    async def test_top5_weight_sum_to_one_for_five_positions(self, db_session):
        p = await _make_portfolio(db_session)
        for i, w in enumerate([0.30, 0.25, 0.20, 0.15, 0.10]):
            await _add_position(db_session, p.id, f"T{i}", weight=w)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.concentration.top_n_weight.get(5, None) == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_top_n_monotonically_increasing(self, db_session):
        p = await _make_portfolio(db_session)
        for i in range(8):
            await _add_position(db_session, p.id, f"T{i}", weight=None)
        report = await compute_portfolio_health(db_session, p.id)
        vals = list(report.concentration.top_n_weight.values())
        for i in range(len(vals) - 1):
            assert vals[i] <= vals[i + 1]


# ---------------------------------------------------------------------------
# 7. Effective-N correctness
# ---------------------------------------------------------------------------

class TestEffectiveN:
    @pytest.mark.asyncio
    async def test_effective_n_equals_n_for_equal_weight(self, db_session):
        p = await _make_portfolio(db_session)
        for t in ["A", "B", "C", "D"]:
            await _add_position(db_session, p.id, t, weight=None)
        report = await compute_portfolio_health(db_session, p.id)
        # Equal weight: effective_N = N = 4
        assert report.concentration.effective_n == pytest.approx(4.0, rel=1e-4)

    @pytest.mark.asyncio
    async def test_effective_n_less_than_n_for_concentrated(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.90)
        await _add_position(db_session, p.id, "MSFT", weight=0.10)
        report = await compute_portfolio_health(db_session, p.id)
        # effective_N = 1 / (0.81 + 0.01) = 1/0.82 ≈ 1.22
        assert report.concentration.effective_n == pytest.approx(1.0 / 0.82, rel=1e-4)
        assert report.concentration.effective_n < 2.0

    @pytest.mark.asyncio
    async def test_effective_n_is_one_for_single_position(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=1.0)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.concentration.effective_n == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 8. owned / watchlist / on_radar counts
# ---------------------------------------------------------------------------

class TestMembershipClassCounts:
    @pytest.mark.asyncio
    async def test_owned_count(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", membership_class="owned")
        await _add_position(db_session, p.id, "MSFT", membership_class="owned")
        await _add_position(db_session, p.id, "GOOGL", membership_class="watchlist")
        report = await compute_portfolio_health(db_session, p.id)
        assert report.diversification.owned_count == 2

    @pytest.mark.asyncio
    async def test_watchlist_count(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", membership_class="owned")
        await _add_position(db_session, p.id, "MSFT", membership_class="watchlist")
        await _add_position(db_session, p.id, "GOOGL", membership_class="watchlist")
        report = await compute_portfolio_health(db_session, p.id)
        assert report.diversification.watchlist_count == 2

    @pytest.mark.asyncio
    async def test_on_radar_count(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", membership_class="on_radar")
        await _add_position(db_session, p.id, "MSFT", membership_class="watchlist")
        report = await compute_portfolio_health(db_session, p.id)
        assert report.diversification.on_radar_count == 1
        assert report.diversification.watchlist_count == 1

    @pytest.mark.asyncio
    async def test_class_weights_sum_to_one(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "A", weight=0.5, membership_class="owned")
        await _add_position(db_session, p.id, "B", weight=0.3, membership_class="watchlist")
        await _add_position(db_session, p.id, "C", weight=0.2, membership_class="on_radar")
        report = await compute_portfolio_health(db_session, p.id)
        total = (
            report.diversification.owned_weight
            + report.diversification.watchlist_weight
            + report.diversification.on_radar_weight
        )
        assert total == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_inactive_positions_excluded(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", membership_class="owned")
        # Add an inactive position manually.
        inactive = PortfolioPosition(
            id=str(uuid.uuid4()),
            portfolio_id=p.id,
            ticker="INACTIVE",
            membership_class="owned",
            active=False,
        )
        db_session.add(inactive)
        await db_session.flush()
        report = await compute_portfolio_health(db_session, p.id)
        assert report.concentration.position_count == 1
        assert report.diversification.owned_count == 1


# ---------------------------------------------------------------------------
# 9. Missing regime substrate → safe empty
# ---------------------------------------------------------------------------

class TestRegimeSubstrateMissing:
    @pytest.mark.asyncio
    async def test_no_durability_rows_tickers_in_missing(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        report = await compute_portfolio_health(db_session, p.id)
        rs = report.regime_sensitivity
        assert set(rs.tickers_without_durability) == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_partial_durability_only_missing_in_list(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_durability(db_session, "AAPL", cycle_position="early")
        report = await compute_portfolio_health(db_session, p.id)
        assert "MSFT" in report.regime_sensitivity.tickers_without_durability
        assert "AAPL" not in report.regime_sensitivity.tickers_without_durability

    @pytest.mark.asyncio
    async def test_no_substrate_substrate_missing_true(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        # No thesis rows, no durability rows.
        report = await compute_portfolio_health(db_session, p.id)
        assert report.regime_sensitivity.substrate_missing is True

    @pytest.mark.asyncio
    async def test_empty_portfolio_regime_substrate_missing_true(self, db_session):
        p = await _make_portfolio(db_session)
        report = await compute_portfolio_health(db_session, p.id)
        assert report.regime_sensitivity.substrate_missing is True

    @pytest.mark.asyncio
    async def test_durability_present_substrate_missing_false(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_durability(db_session, "AAPL")
        report = await compute_portfolio_health(db_session, p.id)
        assert report.regime_sensitivity.substrate_missing is False

    @pytest.mark.asyncio
    async def test_cycle_position_distribution_populated(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_position(db_session, p.id, "MSFT")
        await _add_durability(db_session, "AAPL", cycle_position="early")
        await _add_durability(db_session, "MSFT", cycle_position="mid")
        report = await compute_portfolio_health(db_session, p.id)
        dist = report.regime_sensitivity.cycle_position_distribution
        assert dist.get("early") == 1
        assert dist.get("mid") == 1

    @pytest.mark.asyncio
    async def test_macro_factors_from_thesis(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_thesis(db_session, "AAPL", macro_sensitivity={"rates": "high", "usd": "low"})
        report = await compute_portfolio_health(db_session, p.id)
        factors = report.regime_sensitivity.active_macro_factors
        assert "rates" in factors
        assert "usd" in factors


# ---------------------------------------------------------------------------
# 10. No price fields used (structural)
# ---------------------------------------------------------------------------

class TestNoPriceFields:
    @pytest.mark.asyncio
    async def test_no_price_attribute_in_report(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        report = await compute_portfolio_health(db_session, p.id)
        report_dict = vars(report)
        forbidden = {"price", "volatility", "beta", "var", "sharpe", "return", "forecast"}
        for key in report_dict:
            assert key.lower() not in forbidden, f"Forbidden field found: {key}"

    @pytest.mark.asyncio
    async def test_service_source_has_no_price_dependency(self):
        import app.services.portfolio_health_service as svc
        # Check only import statements — these are unambiguous.
        import_lines = [
            line for line in open(svc.__file__).read().splitlines()
            if line.lstrip().startswith("import ") or line.lstrip().startswith("from ")
        ]
        import_block = "\n".join(import_lines).lower()
        assert "yfinance" not in import_block
        assert "pandas_datareader" not in import_block
        assert "alpha_vantage" not in import_block
        assert "scipy.stats" not in import_block


# ---------------------------------------------------------------------------
# 11. No forbidden metrics present
# ---------------------------------------------------------------------------

class TestNoForbiddenMetrics:
    @pytest.mark.asyncio
    async def test_concentration_has_no_volatility_field(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        report = await compute_portfolio_health(db_session, p.id)
        conc_fields = vars(report.concentration).keys()
        assert "volatility" not in conc_fields
        assert "beta" not in conc_fields
        assert "sharpe" not in conc_fields

    @pytest.mark.asyncio
    async def test_no_delivery_ledger_written(self, db_session):
        from sqlalchemy import text
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM delivery_ledger")
        )).scalar()
        await compute_portfolio_health(db_session, p.id)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM delivery_ledger")
        )).scalar()
        assert before == after

    @pytest.mark.asyncio
    async def test_no_portfolio_insights_written(self, db_session):
        from sqlalchemy import text
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM portfolio_insights")
        )).scalar()
        await compute_portfolio_health(db_session, p.id)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM portfolio_insights")
        )).scalar()
        assert before == after

    @pytest.mark.asyncio
    async def test_no_notifications_written(self, db_session):
        from sqlalchemy import text
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM notifications")
        )).scalar()
        await compute_portfolio_health(db_session, p.id)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM notifications")
        )).scalar()
        assert before == after

    @pytest.mark.asyncio
    async def test_no_llm_import_in_service(self):
        import app.services.portfolio_health_service as svc
        src = open(svc.__file__).read()
        assert "anthropic" not in src
        assert "openai" not in src
        assert "langchain" not in src


# ---------------------------------------------------------------------------
# Null session
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_null_session_returns_report(self):
        report = await compute_portfolio_health(None, "any-id")
        assert isinstance(report, PortfolioHealthReport)

    @pytest.mark.asyncio
    async def test_null_session_portfolio_id_preserved(self):
        report = await compute_portfolio_health(None, "pid-123")
        assert report.portfolio_id == "pid-123"

    @pytest.mark.asyncio
    async def test_null_session_no_session_warning(self):
        report = await compute_portfolio_health(None, "any-id")
        codes = [w.code for w in report.warnings]
        assert "NO_SESSION" in codes

    @pytest.mark.asyncio
    async def test_null_session_empty_positions(self):
        report = await compute_portfolio_health(None, "any-id")
        assert report.concentration.position_count == 0
        assert report.theme_exposure == []


# ---------------------------------------------------------------------------
# Theme exposure
# ---------------------------------------------------------------------------

class TestThemeExposure:
    @pytest.mark.asyncio
    async def test_shared_concern_produces_theme(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.5)
        await _add_position(db_session, p.id, "MSFT", weight=0.5)
        await _add_edge(db_session, "AAPL", "MSFT", ["ai_competition"])
        report = await compute_portfolio_health(db_session, p.id)
        labels = [t.concern_label for t in report.theme_exposure]
        assert "ai_competition" in labels

    @pytest.mark.asyncio
    async def test_theme_ticker_count_correct(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.4)
        await _add_position(db_session, p.id, "MSFT", weight=0.3)
        await _add_position(db_session, p.id, "GOOGL", weight=0.3)
        await _add_edge(db_session, "AAPL", "MSFT", ["cloud"])
        await _add_edge(db_session, "MSFT", "GOOGL", ["cloud"])
        report = await compute_portfolio_health(db_session, p.id)
        cloud_theme = next(t for t in report.theme_exposure if t.concern_label == "cloud")
        assert cloud_theme.ticker_count == 3

    @pytest.mark.asyncio
    async def test_edge_outside_portfolio_not_included(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL")
        await _add_edge(db_session, "AAPL", "NVDA", ["gpu"])  # NVDA not in portfolio
        report = await compute_portfolio_health(db_session, p.id)
        assert report.theme_exposure == []

    @pytest.mark.asyncio
    async def test_multiple_concerns_produce_multiple_themes(self, db_session):
        p = await _make_portfolio(db_session)
        await _add_position(db_session, p.id, "AAPL", weight=0.5)
        await _add_position(db_session, p.id, "MSFT", weight=0.5)
        await _add_edge(db_session, "AAPL", "MSFT", ["cloud", "ai"])
        report = await compute_portfolio_health(db_session, p.id)
        labels = {t.concern_label for t in report.theme_exposure}
        assert "cloud" in labels
        assert "ai" in labels


# ---------------------------------------------------------------------------
# generated_at
# ---------------------------------------------------------------------------

class TestOutputStructure:
    @pytest.mark.asyncio
    async def test_generated_at_is_iso_string(self, db_session):
        p = await _make_portfolio(db_session)
        report = await compute_portfolio_health(db_session, p.id)
        parsed = datetime.fromisoformat(report.generated_at.replace("Z", "+00:00"))
        assert parsed is not None

    @pytest.mark.asyncio
    async def test_report_has_all_required_fields(self, db_session):
        p = await _make_portfolio(db_session)
        report = await compute_portfolio_health(db_session, p.id)
        assert hasattr(report, "portfolio_id")
        assert hasattr(report, "generated_at")
        assert hasattr(report, "weight_source")
        assert hasattr(report, "concentration")
        assert hasattr(report, "diversification")
        assert hasattr(report, "theme_exposure")
        assert hasattr(report, "regime_sensitivity")
        assert hasattr(report, "warnings")
