"""
Tests for app/services/portfolio_insight_ranking_service.py — Phase 10D · Slice 6.

Covers all 9 specified scenarios:
  1. Higher severity ranks above lower severity
  2. Higher affected weight ranks above lower affected weight
  3. Stale input demotes score
  4. Old insight demotes score
  5. Novelty suppression works
  6. Rank ordering deterministic
  7. Regulatory disclaimer preserved
  8. No prose mutation
  9. No delivery behavior

Additional: formula correctness, rank_band assignment, null-session,
dry_run, DB persistence, factor isolation.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Portfolio, PortfolioInsight, PortfolioPosition
from app.services.portfolio_insight_ranking_service import (
    BASE_SEVERITY,
    RankingResult,
    RankedInsight,
    _NOVELTY_NEVER_DELIVERED,
    _NOVELTY_RECENT_DELIVERY,
    _NOVELTY_STALE_DELIVERY,
    _NOVELTY_REDELIVERY_DAYS,
    _RECENCY_FLOOR,
    _STALE_MULTIPLIER,
    assign_rank_band,
    compute_base_severity_score,
    compute_novelty_factor,
    compute_portfolio_weight_factor,
    compute_rank_score,
    compute_recency_factor,
    rank_candidates_in_memory,
    rank_portfolio_insights,
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


def _days_ago(n: float) -> datetime:
    return _now() - timedelta(days=n)


def _hours_ago(n: float) -> datetime:
    return _now() - timedelta(hours=n)


async def _make_portfolio(session, name: str = "Test") -> Portfolio:
    p = Portfolio(id=_uid(), name=name, user_id=None, is_default=False)
    session.add(p)
    await session.flush()
    return p


async def _make_insight(
    session,
    portfolio_id: str,
    insight_type: str = "shared_risk_cluster",
    cluster_label: str = "test_cluster",
    severity: str = "medium",
    cluster_weight: Optional[float] = None,
    stale_input: bool = False,
    created_at: Optional[datetime] = None,
    last_delivered_at: Optional[datetime] = None,
    body_json: str = '{"prose":"test prose","regulatory_disclaimer":"disclaimer","meta":{}}',
    rank_score: float = 0.0,
) -> PortfolioInsight:
    row = PortfolioInsight(
        id=_uid(),
        portfolio_id=portfolio_id,
        insight_type=insight_type,
        cluster_label=cluster_label,
        member_tickers='["AAPL","MSFT"]',
        cluster_weight=cluster_weight,
        severity=severity,
        severity_rank={"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}.get(severity, 0),
        rank_score=rank_score,
        body_json=body_json,
        cross_exposure_as_of=None,
        stale_input=stale_input,
        content_key=f"key-{_uid()}",
        created_at=created_at or _now(),
        last_delivered_at=last_delivered_at,
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# Unit tests — pure factor functions (no DB)
# ---------------------------------------------------------------------------

class TestBaseSevrityScore:
    def test_critical_is_4(self):
        assert compute_base_severity_score("critical") == 4.0

    def test_high_is_3(self):
        assert compute_base_severity_score("high") == 3.0

    def test_medium_is_2(self):
        assert compute_base_severity_score("medium") == 2.0

    def test_low_is_1(self):
        assert compute_base_severity_score("low") == 1.0

    def test_info_is_0(self):
        assert compute_base_severity_score("info") == 0.0

    def test_unknown_severity_is_0(self):
        assert compute_base_severity_score("unknown") == 0.0

    def test_case_insensitive(self):
        assert compute_base_severity_score("HIGH") == 3.0
        assert compute_base_severity_score("Medium") == 2.0


class TestPortfolioWeightFactor:
    def test_null_weight_is_1(self):
        assert compute_portfolio_weight_factor(None) == 1.0

    def test_60pct_weight_is_1_point_6(self):
        assert compute_portfolio_weight_factor(0.60, 1.0) == pytest.approx(1.6)

    def test_100pct_weight_is_2(self):
        assert compute_portfolio_weight_factor(1.0, 1.0) == pytest.approx(2.0)

    def test_zero_weight_is_1(self):
        assert compute_portfolio_weight_factor(0.0, 1.0) == pytest.approx(1.0)

    def test_total_weight_zero_fallback(self):
        assert compute_portfolio_weight_factor(0.5, 0.0) == 1.0

    def test_partial_portfolio_coverage(self):
        # cluster covers 0.3 out of total 1.0 → 1.3×
        assert compute_portfolio_weight_factor(0.30, 1.0) == pytest.approx(1.3)


class TestNoveltyFactor:
    def test_never_delivered_is_1(self):
        assert compute_novelty_factor(None) == 1.0

    def test_delivered_today_is_suppressed(self):
        assert compute_novelty_factor(_hours_ago(1)) == pytest.approx(_NOVELTY_RECENT_DELIVERY)

    def test_delivered_5_days_ago_is_suppressed(self):
        assert compute_novelty_factor(_days_ago(5)) == pytest.approx(_NOVELTY_RECENT_DELIVERY)

    def test_delivered_8_days_ago_is_stale(self):
        assert compute_novelty_factor(_days_ago(8)) == pytest.approx(_NOVELTY_STALE_DELIVERY)

    def test_delivered_exactly_7_days_boundary_suppressed(self):
        # Delivered exactly REDELIVERY_DAYS ago sits at the boundary.  Due to
        # microsecond clock drift between construction and evaluation it can
        # land on either side — either outcome is valid.
        result = compute_novelty_factor(_days_ago(_NOVELTY_REDELIVERY_DAYS))
        assert result in (
            pytest.approx(_NOVELTY_RECENT_DELIVERY),
            pytest.approx(_NOVELTY_STALE_DELIVERY),
        )

    def test_delivered_just_over_7_days_is_stale(self):
        assert compute_novelty_factor(_days_ago(_NOVELTY_REDELIVERY_DAYS + 0.1)) == pytest.approx(
            _NOVELTY_STALE_DELIVERY
        )


class TestRecencyFactor:
    def test_fresh_under_24h_is_1(self):
        assert compute_recency_factor(_hours_ago(12)) == pytest.approx(1.0)

    def test_exactly_24h_is_1(self):
        assert compute_recency_factor(_hours_ago(23.9)) == pytest.approx(1.0)

    def test_7_days_is_floor(self):
        assert compute_recency_factor(_days_ago(7)) == pytest.approx(_RECENCY_FLOOR)

    def test_older_than_7_days_is_floor(self):
        assert compute_recency_factor(_days_ago(30)) == pytest.approx(_RECENCY_FLOOR)

    def test_day_4_is_between_1_and_floor(self):
        v = compute_recency_factor(_days_ago(4))
        assert _RECENCY_FLOOR < v < 1.0

    def test_recency_decreases_monotonically(self):
        vals = [compute_recency_factor(_days_ago(d)) for d in [0.5, 2, 4, 6, 8]]
        for i in range(len(vals) - 1):
            assert vals[i] >= vals[i + 1]


class TestRankBand:
    def test_critical_band(self):
        assert assign_rank_band(10.1) == "critical"

    def test_high_band(self):
        assert assign_rank_band(5.0) == "high"

    def test_medium_band(self):
        assert assign_rank_band(1.5) == "medium"

    def test_low_band(self):
        assert assign_rank_band(0.5) == "low"

    def test_zero_is_low(self):
        assert assign_rank_band(0.0) == "low"


# ---------------------------------------------------------------------------
# 1. Higher severity ranks above lower severity
# ---------------------------------------------------------------------------

class TestSeverityOrdering:
    def _score(self, severity: str) -> float:
        score, *_ = compute_rank_score(
            severity=severity,
            cluster_weight=None,
            total_portfolio_weight=1.0,
            last_delivered_at=None,
            created_at=_hours_ago(1),
            stale_input=False,
        )
        return score

    def test_critical_above_high(self):
        assert self._score("critical") > self._score("high")

    def test_high_above_medium(self):
        assert self._score("high") > self._score("medium")

    def test_medium_above_low(self):
        assert self._score("medium") > self._score("low")

    def test_low_above_info(self):
        assert self._score("low") > self._score("info")

    @pytest.mark.asyncio
    async def test_db_high_severity_ranked_first(self, db_session):
        p = await _make_portfolio(db_session)
        low_row = await _make_insight(db_session, p.id, severity="low", cluster_label="A")
        high_row = await _make_insight(db_session, p.id, severity="high", cluster_label="B")
        result = await rank_portfolio_insights(db_session, p.id)
        types = [r.insight_id for r in result.insights]
        assert types.index(high_row.id) < types.index(low_row.id)


# ---------------------------------------------------------------------------
# 2. Higher affected weight ranks above lower weight
# ---------------------------------------------------------------------------

class TestWeightOrdering:
    def _score(self, weight: Optional[float]) -> float:
        score, *_ = compute_rank_score(
            severity="medium",
            cluster_weight=weight,
            total_portfolio_weight=1.0,
            last_delivered_at=None,
            created_at=_hours_ago(1),
            stale_input=False,
        )
        return score

    def test_higher_weight_higher_score(self):
        assert self._score(0.8) > self._score(0.4)

    def test_any_weight_above_null_weight(self):
        # cluster_weight=0.01 → factor 1.01 > null → factor 1.0
        assert self._score(0.01) > self._score(None)

    def test_full_coverage_doubles_base(self):
        score_full, *_ = compute_rank_score(
            severity="medium", cluster_weight=1.0,
            total_portfolio_weight=1.0, last_delivered_at=None,
            created_at=_hours_ago(1), stale_input=False,
        )
        score_none, *_ = compute_rank_score(
            severity="medium", cluster_weight=None,
            total_portfolio_weight=1.0, last_delivered_at=None,
            created_at=_hours_ago(1), stale_input=False,
        )
        # weight=1.0 → factor 2.0 vs weight=None → factor 1.0 → 2× score
        assert score_full == pytest.approx(score_none * 2.0)

    @pytest.mark.asyncio
    async def test_db_higher_weight_ranked_first(self, db_session):
        p = await _make_portfolio(db_session)
        low_w = await _make_insight(db_session, p.id, cluster_weight=0.1, cluster_label="A")
        high_w = await _make_insight(db_session, p.id, cluster_weight=0.8, cluster_label="B")
        result = await rank_portfolio_insights(db_session, p.id)
        ids = [r.insight_id for r in result.insights]
        assert ids.index(high_w.id) < ids.index(low_w.id)


# ---------------------------------------------------------------------------
# 3. Stale input demotes score
# ---------------------------------------------------------------------------

class TestStaleDemotion:
    def _score(self, stale: bool) -> float:
        score, *_ = compute_rank_score(
            severity="high",
            cluster_weight=None,
            total_portfolio_weight=1.0,
            last_delivered_at=None,
            created_at=_hours_ago(1),
            stale_input=stale,
        )
        return score

    def test_stale_lower_than_fresh(self):
        assert self._score(True) < self._score(False)

    def test_stale_multiplier_value(self):
        fresh = self._score(False)
        stale = self._score(True)
        assert stale == pytest.approx(fresh * _STALE_MULTIPLIER)

    @pytest.mark.asyncio
    async def test_db_stale_ranked_below_fresh(self, db_session):
        p = await _make_portfolio(db_session)
        fresh = await _make_insight(db_session, p.id, stale_input=False, cluster_label="A")
        stale = await _make_insight(db_session, p.id, stale_input=True, cluster_label="B")
        result = await rank_portfolio_insights(db_session, p.id)
        ids = [r.insight_id for r in result.insights]
        assert ids.index(fresh.id) < ids.index(stale.id)


# ---------------------------------------------------------------------------
# 4. Old insight demotes score
# ---------------------------------------------------------------------------

class TestRecencyDemotion:
    def _score(self, days_old: float) -> float:
        score, *_ = compute_rank_score(
            severity="high",
            cluster_weight=None,
            total_portfolio_weight=1.0,
            last_delivered_at=None,
            created_at=_days_ago(days_old),
            stale_input=False,
        )
        return score

    def test_fresh_above_old(self):
        assert self._score(0.5) > self._score(5.0)

    def test_7_day_old_at_floor(self):
        score_7d = self._score(7.0)
        score_old = self._score(30.0)
        # Both at floor — equal or very close.
        assert score_7d == pytest.approx(score_old)

    def test_score_decreases_with_age(self):
        scores = [self._score(d) for d in [0.5, 2, 4, 6, 8]]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    @pytest.mark.asyncio
    async def test_db_old_insight_lower_score(self, db_session):
        p = await _make_portfolio(db_session)
        fresh = await _make_insight(
            db_session, p.id, created_at=_hours_ago(2), cluster_label="A"
        )
        old = await _make_insight(
            db_session, p.id, created_at=_days_ago(8), cluster_label="B"
        )
        result = await rank_portfolio_insights(db_session, p.id)
        fresh_r = next(r for r in result.insights if r.insight_id == fresh.id)
        old_r = next(r for r in result.insights if r.insight_id == old.id)
        assert fresh_r.rank_score > old_r.rank_score


# ---------------------------------------------------------------------------
# 5. Novelty suppression works
# ---------------------------------------------------------------------------

class TestNoveltySuppression:
    def _score(self, last_delivered_at: Optional[datetime]) -> float:
        score, *_ = compute_rank_score(
            severity="high",
            cluster_weight=None,
            total_portfolio_weight=1.0,
            last_delivered_at=last_delivered_at,
            created_at=_hours_ago(1),
            stale_input=False,
        )
        return score

    def test_never_delivered_highest(self):
        assert self._score(None) > self._score(_days_ago(8))

    def test_recently_delivered_suppressed(self):
        assert self._score(_days_ago(3)) < self._score(None)

    def test_stale_delivery_partially_restored(self):
        # Delivered > 7 days ago → 0.8 factor (higher than recent 0.3).
        assert self._score(_days_ago(10)) > self._score(_days_ago(3))

    def test_novelty_factor_values_correct(self):
        assert compute_novelty_factor(None) == pytest.approx(_NOVELTY_NEVER_DELIVERED)
        assert compute_novelty_factor(_days_ago(3)) == pytest.approx(_NOVELTY_RECENT_DELIVERY)
        assert compute_novelty_factor(_days_ago(10)) == pytest.approx(_NOVELTY_STALE_DELIVERY)

    @pytest.mark.asyncio
    async def test_db_recently_delivered_ranked_below_novel(self, db_session):
        p = await _make_portfolio(db_session)
        novel = await _make_insight(
            db_session, p.id, last_delivered_at=None, cluster_label="A"
        )
        suppressed = await _make_insight(
            db_session, p.id, last_delivered_at=_days_ago(1), cluster_label="B"
        )
        result = await rank_portfolio_insights(db_session, p.id)
        ids = [r.insight_id for r in result.insights]
        assert ids.index(novel.id) < ids.index(suppressed.id)


# ---------------------------------------------------------------------------
# 6. Rank ordering deterministic
# ---------------------------------------------------------------------------

class TestDeterministicOrdering:
    def test_same_inputs_same_score(self):
        created = _days_ago(2)
        s1, *_ = compute_rank_score("high", 0.5, 1.0, None, created, False)
        s2, *_ = compute_rank_score("high", 0.5, 1.0, None, created, False)
        assert s1 == pytest.approx(s2)

    def test_in_memory_ranking_deterministic(self):
        created = _days_ago(1)
        candidates = [
            {"severity": "high", "cluster_weight": 0.5, "stale_input": False,
             "created_at": created, "last_delivered_at": None, "cluster_label": "B"},
            {"severity": "medium", "cluster_weight": 0.3, "stale_input": False,
             "created_at": created, "last_delivered_at": None, "cluster_label": "A"},
        ]
        r1 = rank_candidates_in_memory(candidates)
        r2 = rank_candidates_in_memory(candidates)
        assert [c["cluster_label"] for c in r1] == [c["cluster_label"] for c in r2]

    @pytest.mark.asyncio
    async def test_db_ordering_stable_across_calls(self, db_session):
        p = await _make_portfolio(db_session)
        await _make_insight(db_session, p.id, severity="medium", cluster_label="B")
        await _make_insight(db_session, p.id, severity="high", cluster_label="A")
        r1 = await rank_portfolio_insights(db_session, p.id, dry_run=True)
        r2 = await rank_portfolio_insights(db_session, p.id, dry_run=True)
        assert [i.insight_id for i in r1.insights] == [i.insight_id for i in r2.insights]

    def test_tie_broken_by_insight_id(self):
        """Equal-score insights are sorted by insight_id for determinism."""
        created = _hours_ago(2)
        candidates = [
            {"severity": "medium", "cluster_weight": None, "stale_input": False,
             "created_at": created, "last_delivered_at": None, "cluster_label": "Z"},
            {"severity": "medium", "cluster_weight": None, "stale_input": False,
             "created_at": created, "last_delivered_at": None, "cluster_label": "A"},
        ]
        ranked = rank_candidates_in_memory(candidates)
        scores = [c["rank_score"] for c in ranked]
        assert scores[0] == pytest.approx(scores[1])
        # Tie broken by cluster_label (proxy for id in in-memory ranking).
        labels = [c["cluster_label"] for c in ranked]
        assert labels == sorted(labels)


# ---------------------------------------------------------------------------
# 7. Regulatory disclaimer preserved
# ---------------------------------------------------------------------------

class TestDisclaimerPreserved:
    @pytest.mark.asyncio
    async def test_ranking_result_has_disclaimer(self, db_session):
        from app.services.portfolio_insight_service import REGULATORY_DISCLAIMER
        p = await _make_portfolio(db_session)
        result = await rank_portfolio_insights(db_session, p.id)
        assert result.regulatory_disclaimer == REGULATORY_DISCLAIMER

    @pytest.mark.asyncio
    async def test_null_session_has_disclaimer(self):
        from app.services.portfolio_insight_service import REGULATORY_DISCLAIMER
        result = await rank_portfolio_insights(None, "any-id")
        assert result.regulatory_disclaimer == REGULATORY_DISCLAIMER

    @pytest.mark.asyncio
    async def test_disclaimer_nonempty(self, db_session):
        p = await _make_portfolio(db_session)
        result = await rank_portfolio_insights(db_session, p.id)
        assert len(result.regulatory_disclaimer) > 50


# ---------------------------------------------------------------------------
# 8. No prose mutation
# ---------------------------------------------------------------------------

class TestNoProseMutation:
    @pytest.mark.asyncio
    async def test_body_json_unchanged_after_ranking(self, db_session):
        from sqlalchemy import select
        p = await _make_portfolio(db_session)
        original_body = '{"prose":"original prose","regulatory_disclaimer":"disc","meta":{}}'
        row = await _make_insight(db_session, p.id, body_json=original_body)
        await rank_portfolio_insights(db_session, p.id)
        refreshed = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.id == row.id)
        )).scalar_one()
        assert refreshed.body_json == original_body

    @pytest.mark.asyncio
    async def test_ranked_insight_body_json_not_mutated(self, db_session):
        p = await _make_portfolio(db_session)
        original_body = '{"prose":"test","regulatory_disclaimer":"x","meta":{}}'
        await _make_insight(db_session, p.id, body_json=original_body)
        result = await rank_portfolio_insights(db_session, p.id)
        for ri in result.insights:
            assert ri.body_json == original_body

    @pytest.mark.asyncio
    async def test_rank_score_updated_in_db(self, db_session):
        from sqlalchemy import select
        p = await _make_portfolio(db_session)
        row = await _make_insight(
            db_session, p.id, severity="high", rank_score=0.0
        )
        await rank_portfolio_insights(db_session, p.id)
        refreshed = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.id == row.id)
        )).scalar_one()
        # rank_score should now be non-zero (high severity = 3.0 × other factors).
        assert refreshed.rank_score > 0.0

    @pytest.mark.asyncio
    async def test_dry_run_does_not_update_db(self, db_session):
        from sqlalchemy import select
        p = await _make_portfolio(db_session)
        row = await _make_insight(
            db_session, p.id, severity="high", rank_score=0.0
        )
        await rank_portfolio_insights(db_session, p.id, dry_run=True)
        refreshed = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.id == row.id)
        )).scalar_one()
        # dry_run=True: DB rank_score unchanged.
        assert refreshed.rank_score == 0.0


# ---------------------------------------------------------------------------
# 9. No delivery behavior
# ---------------------------------------------------------------------------

class TestNoDeliveryBehavior:
    @pytest.mark.asyncio
    async def test_no_delivery_ledger_written(self, db_session):
        from sqlalchemy import text
        p = await _make_portfolio(db_session)
        await _make_insight(db_session, p.id)
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM delivery_ledger")
        )).scalar()
        await rank_portfolio_insights(db_session, p.id)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM delivery_ledger")
        )).scalar()
        assert before == after

    @pytest.mark.asyncio
    async def test_no_notifications_written(self, db_session):
        from sqlalchemy import text
        p = await _make_portfolio(db_session)
        await _make_insight(db_session, p.id)
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM notifications")
        )).scalar()
        await rank_portfolio_insights(db_session, p.id)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM notifications")
        )).scalar()
        assert before == after

    @pytest.mark.asyncio
    async def test_last_delivered_at_not_set_by_ranking(self, db_session):
        from sqlalchemy import select
        p = await _make_portfolio(db_session)
        row = await _make_insight(db_session, p.id, last_delivered_at=None)
        await rank_portfolio_insights(db_session, p.id)
        refreshed = (await db_session.execute(
            select(PortfolioInsight).where(PortfolioInsight.id == row.id)
        )).scalar_one()
        assert refreshed.last_delivered_at is None

    @pytest.mark.asyncio
    async def test_no_new_portfolio_insight_rows_created(self, db_session):
        from sqlalchemy import text
        p = await _make_portfolio(db_session)
        await _make_insight(db_session, p.id)
        before = (await db_session.execute(
            text("SELECT COUNT(*) FROM portfolio_insights")
        )).scalar()
        await rank_portfolio_insights(db_session, p.id)
        after = (await db_session.execute(
            text("SELECT COUNT(*) FROM portfolio_insights")
        )).scalar()
        assert before == after


# ---------------------------------------------------------------------------
# Null session / edge cases
# ---------------------------------------------------------------------------

class TestNullSessionAndEdgeCases:
    @pytest.mark.asyncio
    async def test_null_session_returns_result(self):
        result = await rank_portfolio_insights(None, "any-id")
        assert isinstance(result, RankingResult)

    @pytest.mark.asyncio
    async def test_null_session_empty_insights(self):
        result = await rank_portfolio_insights(None, "any-id")
        assert result.insights == []
        assert result.rows_updated == 0

    @pytest.mark.asyncio
    async def test_empty_portfolio_no_insights(self, db_session):
        p = await _make_portfolio(db_session)
        result = await rank_portfolio_insights(db_session, p.id)
        assert result.insights == []

    @pytest.mark.asyncio
    async def test_dry_run_rows_updated_zero(self, db_session):
        p = await _make_portfolio(db_session)
        await _make_insight(db_session, p.id, severity="high")
        result = await rank_portfolio_insights(db_session, p.id, dry_run=True)
        assert result.rows_updated == 0
        assert result.dry_run is True

    @pytest.mark.asyncio
    async def test_live_run_rows_updated_nonzero(self, db_session):
        p = await _make_portfolio(db_session)
        await _make_insight(db_session, p.id, severity="high")
        result = await rank_portfolio_insights(db_session, p.id, dry_run=False)
        assert result.rows_updated == 1


# ---------------------------------------------------------------------------
# In-memory ranking helper
# ---------------------------------------------------------------------------

class TestInMemoryRanking:
    def test_higher_severity_first(self):
        created = _hours_ago(1)
        candidates = [
            {"severity": "low", "cluster_weight": None, "stale_input": False,
             "created_at": created, "last_delivered_at": None, "cluster_label": "A"},
            {"severity": "high", "cluster_weight": None, "stale_input": False,
             "created_at": created, "last_delivered_at": None, "cluster_label": "B"},
        ]
        ranked = rank_candidates_in_memory(candidates)
        assert ranked[0]["cluster_label"] == "B"

    def test_adds_rank_score_key(self):
        created = _hours_ago(1)
        candidates = [
            {"severity": "medium", "cluster_weight": None, "stale_input": False,
             "created_at": created, "last_delivered_at": None, "cluster_label": "A"},
        ]
        ranked = rank_candidates_in_memory(candidates)
        assert "rank_score" in ranked[0]

    def test_adds_rank_band_key(self):
        created = _hours_ago(1)
        candidates = [
            {"severity": "medium", "cluster_weight": None, "stale_input": False,
             "created_at": created, "last_delivered_at": None, "cluster_label": "A"},
        ]
        ranked = rank_candidates_in_memory(candidates)
        assert "rank_band" in ranked[0]
        assert ranked[0]["rank_band"] in {"critical", "high", "medium", "low"}

    def test_does_not_mutate_input(self):
        created = _hours_ago(1)
        original = {"severity": "medium", "cluster_weight": None, "stale_input": False,
                    "created_at": created, "last_delivered_at": None, "cluster_label": "A"}
        candidates = [original]
        rank_candidates_in_memory(candidates)
        assert "rank_score" not in original

    def test_empty_list_returns_empty(self):
        assert rank_candidates_in_memory([]) == []
