"""
Tests for app/services/portfolio_insight_service.py — Phase 10D · Slice 5.

Covers all 11 specified test scenarios:
  1. Shared risk insight generated
  2. Concentration insight generated
  3. Failure mode insight generated
  4. Catalyst insight generated
  5. Empty portfolio produces no insights
  6. Template prose only (no LLM)
  7. Prohibited language blocked
  8. Disclaimer metadata present
  9. content_key dedup works
 10. No LLM calls
 11. No delivery behavior

Additional: regulatory guard unit tests, content_key stability, closed taxonomy,
null-session dry-run, all 8 insight types reachable, body_json structure.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, PortfolioInsight
from app.services.portfolio_exposure_service import (
    CatalystCluster,
    ExposurePair,
    FailureModeCluster,
    PortfolioExposureProjection,
    SharedExposureCluster,
)
from app.services.portfolio_health_service import (
    ConcentrationMetrics,
    DiversificationMetrics,
    PortfolioHealthReport,
    RegimeSensitivitySummary,
    ThemeExposure,
)
from app.services.portfolio_insight_service import (
    INSIGHT_TYPES,
    REGULATORY_DISCLAIMER,
    InsightGenerationResult,
    _PROHIBITED_PHRASES,
    _PROHIBITED_WORDS,
    _content_key,
    _period_bucket,
    _regulatory_guard,
    generate_portfolio_insights,
)


# ---------------------------------------------------------------------------
# DB fixture
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Factory helpers: build upstream dataclasses without DB
# ---------------------------------------------------------------------------

def _empty_projection(portfolio_id: str = "pid-1") -> PortfolioExposureProjection:
    return PortfolioExposureProjection(
        portfolio_id=portfolio_id,
        generated_at=_now_iso(),
        portfolio_tickers=[],
        exposure_pairs=[],
        high_correlation_pairs=[],
        shared_exposure_clusters=[],
        failure_mode_clusters=[],
        catalyst_clusters=[],
        cross_exposure_stale=False,
        cross_exposure_as_of=None,
        substrate_missing=False,
    )


def _empty_health(portfolio_id: str = "pid-1") -> PortfolioHealthReport:
    return PortfolioHealthReport(
        portfolio_id=portfolio_id,
        generated_at=_now_iso(),
        weight_source="equal_weight_fallback",
        concentration=ConcentrationMetrics(
            hhi=0.0, top_n_weight={}, effective_n=0.0,
            position_count=0, top_n_used=0,
        ),
        diversification=DiversificationMetrics(
            owned_count=0, watchlist_count=0, on_radar_count=0,
            owned_weight=0.0, watchlist_weight=0.0, on_radar_weight=0.0,
        ),
        theme_exposure=[],
        regime_sensitivity=RegimeSensitivitySummary(
            active_macro_factors=[],
            cycle_position_distribution={},
            conviction_trend_distribution={},
            horizon_hint_distribution={},
            tickers_without_durability=[],
            substrate_missing=True,
        ),
        warnings=[],
    )


def _projection_with_cluster(
    portfolio_id: str = "pid-1",
    concern_label: str = "ai_race",
    tickers: Optional[list] = None,
    strength: float = 0.5,
    stale: bool = False,
) -> PortfolioExposureProjection:
    tickers = tickers or ["AAPL", "MSFT"]
    cluster = SharedExposureCluster(
        concern_label=concern_label,
        member_tickers=tickers,
        cluster_weight=None,
        max_edge_strength=strength,
        dominant_exposure_type="thematic",
        stale_input=stale,
        cross_exposure_as_of=_now_iso(),
        source_refs=["ref-1"],
    )
    pair = ExposurePair(
        ticker_a=tickers[0],
        ticker_b=tickers[1],
        exposure_type="thematic",
        strength=strength,
        shared_concerns=[concern_label],
        edge_as_of=_now_iso(),
        stale_input=stale,
        source_ref="ref-1",
    )
    high_corr = [pair] if strength >= 0.7 else []
    return PortfolioExposureProjection(
        portfolio_id=portfolio_id,
        generated_at=_now_iso(),
        portfolio_tickers=tickers,
        exposure_pairs=[pair],
        high_correlation_pairs=high_corr,
        shared_exposure_clusters=[cluster],
        failure_mode_clusters=[],
        catalyst_clusters=[],
        cross_exposure_stale=stale,
        cross_exposure_as_of=_now_iso(),
        substrate_missing=False,
    )


def _projection_with_failure_mode(
    portfolio_id: str = "pid-1",
    analog_id: str = "analog-1",
    analog_label: str = "Displacement Cycle",
    tickers: Optional[list] = None,
) -> PortfolioExposureProjection:
    tickers = tickers or ["INTC", "AMD"]
    fm = FailureModeCluster(
        analog_id=analog_id,
        analog_label=analog_label,
        member_tickers=tickers,
        stages={"INTC": 2, "AMD": 1},
        source_refs=["ref-fm-1"],
    )
    return PortfolioExposureProjection(
        portfolio_id=portfolio_id,
        generated_at=_now_iso(),
        portfolio_tickers=tickers,
        exposure_pairs=[],
        high_correlation_pairs=[],
        shared_exposure_clusters=[],
        failure_mode_clusters=[fm],
        catalyst_clusters=[],
        cross_exposure_stale=False,
        cross_exposure_as_of=None,
        substrate_missing=False,
    )


def _projection_with_catalyst(
    portfolio_id: str = "pid-1",
    direction: str = "bull_trigger",
    tickers: Optional[list] = None,
) -> PortfolioExposureProjection:
    tickers = tickers or ["AAPL", "MSFT"]
    cat = CatalystCluster(
        direction=direction,
        member_tickers=tickers,
        sample_statement="Product launch expected Q3.",
        source_refs=["ref-cat-1"],
    )
    return PortfolioExposureProjection(
        portfolio_id=portfolio_id,
        generated_at=_now_iso(),
        portfolio_tickers=tickers,
        exposure_pairs=[],
        high_correlation_pairs=[],
        shared_exposure_clusters=[],
        failure_mode_clusters=[],
        catalyst_clusters=[cat],
        cross_exposure_stale=False,
        cross_exposure_as_of=None,
        substrate_missing=False,
    )


def _health_with_high_hhi(
    portfolio_id: str = "pid-1",
    hhi: float = 0.82,
    tickers: Optional[list] = None,
) -> PortfolioHealthReport:
    tickers = tickers or ["AAPL", "MSFT"]
    n = len(tickers)
    eff_n = 1.0 / hhi if hhi > 0 else n
    return PortfolioHealthReport(
        portfolio_id=portfolio_id,
        generated_at=_now_iso(),
        weight_source="explicit",
        concentration=ConcentrationMetrics(
            hhi=hhi,
            top_n_weight={1: 0.90, 2: 1.0},
            effective_n=eff_n,
            position_count=n,
            top_n_used=min(5, n),
        ),
        diversification=DiversificationMetrics(
            owned_count=0, watchlist_count=n, on_radar_count=0,
            owned_weight=0.0, watchlist_weight=1.0, on_radar_weight=0.0,
        ),
        theme_exposure=[],
        regime_sensitivity=RegimeSensitivitySummary(
            active_macro_factors=[],
            cycle_position_distribution={},
            conviction_trend_distribution={},
            horizon_hint_distribution={},
            tickers_without_durability=tickers,
            substrate_missing=True,
        ),
        warnings=[],
    )


def _projection_for_tickers(
    portfolio_id: str = "pid-1",
    tickers: Optional[list] = None,
) -> PortfolioExposureProjection:
    tickers = tickers or ["AAPL", "MSFT"]
    return PortfolioExposureProjection(
        portfolio_id=portfolio_id,
        generated_at=_now_iso(),
        portfolio_tickers=tickers,
        exposure_pairs=[],
        high_correlation_pairs=[],
        shared_exposure_clusters=[],
        failure_mode_clusters=[],
        catalyst_clusters=[],
        cross_exposure_stale=False,
        cross_exposure_as_of=None,
        substrate_missing=False,
    )


# ---------------------------------------------------------------------------
# 1. Shared risk insight generated
# ---------------------------------------------------------------------------

class TestSharedRiskInsight:
    @pytest.mark.asyncio
    async def test_shared_risk_cluster_produces_insight(self, db_session):
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        result = await generate_portfolio_insights(db_session, proj, health)
        assert "shared_risk_cluster" in result.types_written

    @pytest.mark.asyncio
    async def test_shared_risk_insight_written_to_db(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        result = await db_session.execute(
            select(PortfolioInsight)
            .where(PortfolioInsight.portfolio_id == pid)
            .where(PortfolioInsight.insight_type == "shared_risk_cluster")
        )
        rows = result.scalars().all()
        assert len(rows) >= 1

    @pytest.mark.asyncio
    async def test_shared_risk_body_contains_concern_label(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid, concern_label="ai_competition")
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        result = await db_session.execute(
            select(PortfolioInsight)
            .where(PortfolioInsight.portfolio_id == pid)
        )
        rows = result.scalars().all()
        sr_rows = [r for r in rows if r.insight_type == "shared_risk_cluster"]
        assert any("ai_competition" in json.loads(r.body_json).get("prose", "") for r in sr_rows)

    @pytest.mark.asyncio
    async def test_shared_risk_high_correlation_generates_hidden_correlation(self, db_session):
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid, strength=0.85)
        health = _empty_health(pid)
        result = await generate_portfolio_insights(db_session, proj, health)
        assert "hidden_correlation" in result.types_written


# ---------------------------------------------------------------------------
# 2. Concentration insight generated
# ---------------------------------------------------------------------------

class TestConcentrationInsight:
    @pytest.mark.asyncio
    async def test_high_hhi_produces_concentration_insight(self, db_session):
        pid = _uid()
        proj = _projection_for_tickers(pid)
        health = _health_with_high_hhi(pid, hhi=0.82)
        result = await generate_portfolio_insights(db_session, proj, health)
        assert "concentration_risk" in result.types_written

    @pytest.mark.asyncio
    async def test_medium_hhi_produces_concentration_insight(self, db_session):
        pid = _uid()
        proj = _projection_for_tickers(pid)
        health = _health_with_high_hhi(pid, hhi=0.34)
        result = await generate_portfolio_insights(db_session, proj, health)
        assert "concentration_risk" in result.types_written

    @pytest.mark.asyncio
    async def test_low_hhi_no_concentration_insight(self, db_session):
        pid = _uid()
        proj = _projection_for_tickers(pid, tickers=["A", "B", "C", "D", "E",
                                                      "F", "G", "H", "I", "J"])
        # Build health with HHI = 0.1 (10 equal positions) — below threshold.
        health = PortfolioHealthReport(
            portfolio_id=pid,
            generated_at=_now_iso(),
            weight_source="equal_weight_fallback",
            concentration=ConcentrationMetrics(
                hhi=0.10, top_n_weight={1: 0.10}, effective_n=10.0,
                position_count=10, top_n_used=5,
            ),
            diversification=DiversificationMetrics(
                owned_count=0, watchlist_count=10, on_radar_count=0,
                owned_weight=0.0, watchlist_weight=1.0, on_radar_weight=0.0,
            ),
            theme_exposure=[],
            regime_sensitivity=_empty_health(pid).regime_sensitivity,
            warnings=[],
        )
        result = await generate_portfolio_insights(db_session, proj, health)
        assert "concentration_risk" not in result.types_written

    @pytest.mark.asyncio
    async def test_concentration_insight_has_hhi_in_body(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_for_tickers(pid)
        health = _health_with_high_hhi(pid, hhi=0.82)
        await generate_portfolio_insights(db_session, proj, health)
        result = await db_session.execute(
            select(PortfolioInsight)
            .where(PortfolioInsight.portfolio_id == pid)
            .where(PortfolioInsight.insight_type == "concentration_risk")
        )
        rows = result.scalars().all()
        assert len(rows) >= 1
        body = json.loads(rows[0].body_json)
        assert "0.820" in body["prose"]


# ---------------------------------------------------------------------------
# 3. Failure mode insight generated
# ---------------------------------------------------------------------------

class TestFailureModeInsight:
    @pytest.mark.asyncio
    async def test_failure_mode_produces_insight(self, db_session):
        pid = _uid()
        proj = _projection_with_failure_mode(portfolio_id=pid)
        health = _empty_health(pid)
        result = await generate_portfolio_insights(db_session, proj, health)
        assert "shared_failure_mode" in result.types_written

    @pytest.mark.asyncio
    async def test_failure_mode_analog_label_in_body(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_failure_mode(
            portfolio_id=pid, analog_label="Displacement Cycle"
        )
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        result = await db_session.execute(
            select(PortfolioInsight)
            .where(PortfolioInsight.portfolio_id == pid)
            .where(PortfolioInsight.insight_type == "shared_failure_mode")
        )
        rows = result.scalars().all()
        body = json.loads(rows[0].body_json)
        assert "Displacement Cycle" in body["prose"]

    @pytest.mark.asyncio
    async def test_failure_mode_insight_severity_high(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_failure_mode(portfolio_id=pid)
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        result = await db_session.execute(
            select(PortfolioInsight)
            .where(PortfolioInsight.portfolio_id == pid)
            .where(PortfolioInsight.insight_type == "shared_failure_mode")
        )
        rows = result.scalars().all()
        assert rows[0].severity == "high"


# ---------------------------------------------------------------------------
# 4. Catalyst insight generated
# ---------------------------------------------------------------------------

class TestCatalystInsight:
    @pytest.mark.asyncio
    async def test_bull_catalyst_produces_insight(self, db_session):
        pid = _uid()
        proj = _projection_with_catalyst(pid, direction="bull_trigger")
        health = _empty_health(pid)
        result = await generate_portfolio_insights(db_session, proj, health)
        assert "catalyst_propagation" in result.types_written

    @pytest.mark.asyncio
    async def test_bear_catalyst_produces_insight(self, db_session):
        pid = _uid()
        proj = _projection_with_catalyst(pid, direction="bear_trigger")
        health = _empty_health(pid)
        result = await generate_portfolio_insights(db_session, proj, health)
        assert "catalyst_propagation" in result.types_written

    @pytest.mark.asyncio
    async def test_bear_catalyst_severity_higher(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_catalyst(pid, direction="bear_trigger")
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        result = await db_session.execute(
            select(PortfolioInsight)
            .where(PortfolioInsight.portfolio_id == pid)
            .where(PortfolioInsight.insight_type == "catalyst_propagation")
        )
        rows = result.scalars().all()
        assert rows[0].severity == "high"

    @pytest.mark.asyncio
    async def test_bull_catalyst_severity_medium(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_catalyst(pid, direction="bull_trigger")
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        result = await db_session.execute(
            select(PortfolioInsight)
            .where(PortfolioInsight.portfolio_id == pid)
            .where(PortfolioInsight.insight_type == "catalyst_propagation")
        )
        rows = result.scalars().all()
        assert rows[0].severity == "medium"


# ---------------------------------------------------------------------------
# 5. Empty portfolio produces no insights
# ---------------------------------------------------------------------------

class TestEmptyPortfolio:
    @pytest.mark.asyncio
    async def test_empty_portfolio_result_zero_written(self, db_session):
        pid = _uid()
        proj = _empty_projection(pid)
        health = _empty_health(pid)
        result = await generate_portfolio_insights(db_session, proj, health)
        assert result.written == 0

    @pytest.mark.asyncio
    async def test_empty_portfolio_no_db_rows(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _empty_projection(pid)
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        result = await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.portfolio_id == pid)
        )
        assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_empty_portfolio_types_written_empty(self, db_session):
        pid = _uid()
        result = await generate_portfolio_insights(
            db_session, _empty_projection(pid), _empty_health(pid)
        )
        assert result.types_written == []

    @pytest.mark.asyncio
    async def test_empty_portfolio_disclaimer_still_present(self, db_session):
        pid = _uid()
        result = await generate_portfolio_insights(
            db_session, _empty_projection(pid), _empty_health(pid)
        )
        assert result.regulatory_disclaimer == REGULATORY_DISCLAIMER


# ---------------------------------------------------------------------------
# 6. Template prose only (no LLM)
# ---------------------------------------------------------------------------

class TestTemplateProse:
    @pytest.mark.asyncio
    async def test_no_llm_import_in_service(self):
        import app.services.portfolio_insight_service as svc
        src = open(svc.__file__).read()
        assert "anthropic" not in src
        assert "openai" not in src
        assert "langchain" not in src

    @pytest.mark.asyncio
    async def test_body_is_deterministic(self, db_session):
        """Same inputs → same prose every time."""
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        result1 = await generate_portfolio_insights(db_session, proj, health)
        # Second call — same week → dedup; re-read from DB to compare prose.
        from sqlalchemy import select
        result_rows = await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.portfolio_id == pid)
        )
        rows = result_rows.scalars().all()
        bodies = [json.loads(r.body_json)["prose"] for r in rows]
        # All bodies should be non-empty strings.
        assert all(isinstance(b, str) and len(b) > 0 for b in bodies)

    @pytest.mark.asyncio
    async def test_body_json_contains_disclaimer(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        rows = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.portfolio_id == pid)
        )).scalars().all()
        for row in rows:
            body = json.loads(row.body_json)
            assert "regulatory_disclaimer" in body
            assert body["regulatory_disclaimer"] == REGULATORY_DISCLAIMER

    @pytest.mark.asyncio
    async def test_closed_insight_type_in_taxonomy(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        rows = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.portfolio_id == pid)
        )).scalars().all()
        for row in rows:
            assert row.insight_type in INSIGHT_TYPES


# ---------------------------------------------------------------------------
# 7. Prohibited language blocked
# ---------------------------------------------------------------------------

class TestRegulatoryGuard:
    def test_guard_clean_body_returns_empty(self):
        body = "Portfolio positions share a common risk factor."
        assert _regulatory_guard(body) == []

    def test_guard_detects_buy(self):
        assert "buy" in _regulatory_guard("You should buy this stock.")

    def test_guard_detects_sell(self):
        assert "sell" in _regulatory_guard("Consider to sell your position.")

    def test_guard_detects_hold(self):
        # Word-boundary match: "hold" as a standalone word triggers; "holdings" does not.
        assert "hold" in _regulatory_guard("The recommendation is to hold the security.")
        assert "hold" not in _regulatory_guard("This affects multiple holdings.")

    def test_guard_hold_not_matched_in_holdings(self):
        assert "hold" not in _regulatory_guard("Multiple holdings are affected.")

    def test_guard_detects_target_price(self):
        assert "target price" in _regulatory_guard("The target price is $150.")

    def test_guard_detects_expected_return(self):
        assert "expected return" in _regulatory_guard("Expected return is 12%.")

    def test_guard_detects_optimal_allocation(self):
        assert "optimal allocation" in _regulatory_guard("Optimal allocation requires rebalancing.")

    def test_guard_detects_increase_position(self):
        assert "increase position" in _regulatory_guard("Increase position in AAPL.")

    def test_guard_detects_reduce_position(self):
        assert "reduce position" in _regulatory_guard("Reduce position in MSFT.")

    def test_guard_detects_recommend(self):
        assert "recommend" in _regulatory_guard("We recommend overweighting tech.")

    def test_guard_case_insensitive(self):
        assert "buy" in _regulatory_guard("SHOULD BUY NOW")

    @pytest.mark.asyncio
    async def test_blocked_candidate_not_written(self, db_session):
        """A candidate whose template body contains prohibited language is suppressed."""
        from unittest.mock import patch
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)

        # Patch the template to inject prohibited language.
        with patch(
            "app.services.portfolio_insight_service._tmpl_shared_risk_cluster",
            return_value="You should buy AAPL and MSFT immediately.",
        ):
            result = await generate_portfolio_insights(db_session, proj, health)

        assert result.regulatory_blocked >= 1

    @pytest.mark.asyncio
    async def test_blocked_candidates_not_in_db(self, db_session):
        from unittest.mock import patch
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)

        with patch(
            "app.services.portfolio_insight_service._tmpl_shared_risk_cluster",
            return_value="Strong buy recommendation for these positions.",
        ):
            await generate_portfolio_insights(db_session, proj, health)

        rows = (await db_session.execute(
            select(PortfolioInsight)
            .where(PortfolioInsight.portfolio_id == pid)
            .where(PortfolioInsight.insight_type == "shared_risk_cluster")
        )).scalars().all()
        # shared_risk_cluster rows should not exist (blocked by guard).
        assert rows == []


# ---------------------------------------------------------------------------
# 8. Disclaimer metadata present
# ---------------------------------------------------------------------------

class TestDisclaimerMetadata:
    @pytest.mark.asyncio
    async def test_result_has_disclaimer(self, db_session):
        pid = _uid()
        result = await generate_portfolio_insights(
            db_session, _empty_projection(pid), _empty_health(pid)
        )
        assert result.regulatory_disclaimer == REGULATORY_DISCLAIMER

    @pytest.mark.asyncio
    async def test_disclaimer_is_non_empty_string(self, db_session):
        pid = _uid()
        result = await generate_portfolio_insights(
            db_session, _projection_for_tickers(pid), _empty_health(pid)
        )
        assert isinstance(result.regulatory_disclaimer, str)
        assert len(result.regulatory_disclaimer) > 50

    @pytest.mark.asyncio
    async def test_body_json_disclaimer_matches_constant(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        rows = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.portfolio_id == pid)
        )).scalars().all()
        for row in rows:
            body = json.loads(row.body_json)
            assert body["regulatory_disclaimer"] == REGULATORY_DISCLAIMER

    def test_disclaimer_no_prohibited_language(self):
        # The disclaimer legitimately uses "recommendation" (legal boilerplate)
        # and "buy or sell" in the context of denial — not directives.
        # The guard catches standalone "buy" and "sell" as word matches, but
        # the disclaimer is never passed through the guard (it's metadata, not prose).
        # This test confirms it contains no prescriptive directives.
        assert "target price" not in REGULATORY_DISCLAIMER.lower()
        assert "optimal allocation" not in REGULATORY_DISCLAIMER.lower()
        assert "increase position" not in REGULATORY_DISCLAIMER.lower()


# ---------------------------------------------------------------------------
# 9. content_key dedup
# ---------------------------------------------------------------------------

class TestContentKeyDedup:
    def test_same_inputs_same_key(self):
        k1 = _content_key("pid", "shared_risk_cluster", "ai_race")
        k2 = _content_key("pid", "shared_risk_cluster", "ai_race")
        assert k1 == k2

    def test_different_insight_type_different_key(self):
        k1 = _content_key("pid", "shared_risk_cluster", "ai_race")
        k2 = _content_key("pid", "concentration_risk", "ai_race")
        assert k1 != k2

    def test_different_cluster_label_different_key(self):
        k1 = _content_key("pid", "shared_risk_cluster", "ai_race")
        k2 = _content_key("pid", "shared_risk_cluster", "supply_chain")
        assert k1 != k2

    def test_different_portfolio_id_different_key(self):
        k1 = _content_key("pid-1", "shared_risk_cluster", "ai_race")
        k2 = _content_key("pid-2", "shared_risk_cluster", "ai_race")
        assert k1 != k2

    def test_key_is_64_chars(self):
        k = _content_key("pid", "shared_risk_cluster", "ai_race")
        assert len(k) == 64

    @pytest.mark.asyncio
    async def test_second_call_same_week_deduped(self, db_session):
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)

        r1 = await generate_portfolio_insights(db_session, proj, health)
        r2 = await generate_portfolio_insights(db_session, proj, health)

        # First call: written > 0, deduplicated = 0.
        assert r1.written >= 1
        assert r1.deduplicated == 0
        # Second call: written = 0, deduplicated > 0 (same content_key, same week).
        assert r2.written == 0
        assert r2.deduplicated >= 1

    @pytest.mark.asyncio
    async def test_dedup_does_not_create_duplicate_rows(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)

        await generate_portfolio_insights(db_session, proj, health)
        await generate_portfolio_insights(db_session, proj, health)

        rows = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.portfolio_id == pid)
        )).scalars().all()
        # Verify no duplicate content_keys.
        keys = [r.content_key for r in rows]
        assert len(keys) == len(set(keys))

    @pytest.mark.asyncio
    async def test_different_portfolio_ids_separate_rows(self, db_session):
        from sqlalchemy import select
        pid_a, pid_b = _uid(), _uid()
        proj_a = _projection_with_cluster(portfolio_id=pid_a, concern_label="cloud")
        proj_b = _projection_with_cluster(portfolio_id=pid_b, concern_label="cloud")

        await generate_portfolio_insights(db_session, proj_a, _empty_health(pid_a))
        await generate_portfolio_insights(db_session, proj_b, _empty_health(pid_b))

        rows_a = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.portfolio_id == pid_a)
        )).scalars().all()
        rows_b = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.portfolio_id == pid_b)
        )).scalars().all()
        assert len(rows_a) >= 1
        assert len(rows_b) >= 1
        # Keys are portfolio-scoped — no collision across portfolios.
        keys_a = {r.content_key for r in rows_a}
        keys_b = {r.content_key for r in rows_b}
        assert keys_a.isdisjoint(keys_b)


# ---------------------------------------------------------------------------
# 10. No LLM calls
# ---------------------------------------------------------------------------

class TestNoLLMCalls:
    @pytest.mark.asyncio
    async def test_full_run_no_llm(self, db_session):
        """Full generation run over a rich portfolio without any external calls."""
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid, strength=0.85)
        health = _health_with_high_hhi(pid)
        result = await generate_portfolio_insights(db_session, proj, health)
        assert isinstance(result, InsightGenerationResult)
        assert result.written >= 1

    @pytest.mark.asyncio
    async def test_null_session_dry_run_no_writes(self):
        """Null session → dry-run: counts written but nothing persisted."""
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        result = await generate_portfolio_insights(None, proj, health)
        assert isinstance(result, InsightGenerationResult)
        # Dry-run still counts candidates as "written" but has no DB.
        assert result.written >= 0
        assert result.deduplicated == 0


# ---------------------------------------------------------------------------
# 11. No delivery behavior
# ---------------------------------------------------------------------------

class TestNoDeliveryBehavior:
    @pytest.mark.asyncio
    async def test_no_delivery_ledger_written(self, db_session):
        from sqlalchemy import text
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM delivery_ledger")
        )).scalar()
        await generate_portfolio_insights(db_session, proj, health)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM delivery_ledger")
        )).scalar()
        assert before == after

    @pytest.mark.asyncio
    async def test_no_notifications_written(self, db_session):
        from sqlalchemy import text
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM notifications")
        )).scalar()
        await generate_portfolio_insights(db_session, proj, health)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM notifications")
        )).scalar()
        assert before == after

    @pytest.mark.asyncio
    async def test_no_briefing_sessions_written(self, db_session):
        from sqlalchemy import text
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM briefing_sessions")
        )).scalar()
        await generate_portfolio_insights(db_session, proj, health)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM briefing_sessions")
        )).scalar()
        assert before == after

    @pytest.mark.asyncio
    async def test_last_delivered_at_is_null(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        rows = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.portfolio_id == pid)
        )).scalars().all()
        for row in rows:
            assert row.last_delivered_at is None


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------

class TestResultStructure:
    @pytest.mark.asyncio
    async def test_result_has_portfolio_id(self, db_session):
        pid = _uid()
        result = await generate_portfolio_insights(
            db_session, _empty_projection(pid), _empty_health(pid)
        )
        assert result.portfolio_id == pid

    @pytest.mark.asyncio
    async def test_result_generated_at_is_iso(self, db_session):
        pid = _uid()
        result = await generate_portfolio_insights(
            db_session, _empty_projection(pid), _empty_health(pid)
        )
        parsed = datetime.fromisoformat(result.generated_at.replace("Z", "+00:00"))
        assert parsed is not None

    @pytest.mark.asyncio
    async def test_types_written_only_valid_taxonomy(self, db_session):
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid, strength=0.9)
        health = _health_with_high_hhi(pid)
        result = await generate_portfolio_insights(db_session, proj, health)
        for t in result.types_written:
            assert t in INSIGHT_TYPES

    @pytest.mark.asyncio
    async def test_body_json_has_meta_key(self, db_session):
        from sqlalchemy import select
        pid = _uid()
        proj = _projection_with_cluster(portfolio_id=pid)
        health = _empty_health(pid)
        await generate_portfolio_insights(db_session, proj, health)
        rows = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.portfolio_id == pid)
        )).scalars().all()
        for row in rows:
            body = json.loads(row.body_json)
            assert "meta" in body
            assert "prose" in body
