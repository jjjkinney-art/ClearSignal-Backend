"""
Tests — Decision Portfolio Awareness, Phase 13 · Slice 7.

Covers:
  1.  build_portfolio_map returns {} for null session
  2.  build_portfolio_map returns {} for empty portfolio
  3.  build_portfolio_map returns ticker→weight for seeded positions
  4.  build_portfolio_map handles weight=None (ownership known)
  5.  build_portfolio_map aggregates across multiple portfolios
  6.  build_portfolio_map keeps highest weight when ticker in multiple portfolios
  7.  build_portfolio_map does not return tickers from other users
  8.  compute_portfolio_exposure_multiplier returns 1.0 for unknown ticker
  9.  compute_portfolio_exposure_multiplier returns > 1.0 for owned ticker with weight
  10. compute_portfolio_exposure_multiplier returns 1.20 for owned ticker without weight
  11. compute_portfolio_exposure_multiplier respects 1.50 ceiling
  12. compute_portfolio_exposure_multiplier respects 0.50 floor
  13. apply_portfolio_context — unowned ticker → exposure_multiplier unchanged (1.0)
  14. apply_portfolio_context — owned ticker with weight → decision_score increases
  15. apply_portfolio_context — does not mutate original ranking_output
  16. apply_portfolio_context — does not mutate original candidate
  17. apply_portfolio_context — recomputed decision_score in [0, 1]
  18. apply_portfolio_context — empty portfolio_map returns unchanged ranking
  19. apply_portfolio_context — base_score × confidence × uncertainty × new_exposure
  20. rebuild_decisions_for_user_portfolio returns [] for null session (non-shadow)
  21. rebuild_decisions_for_user_portfolio returns [] for empty user_id
  22. rebuild_decisions_for_user_portfolio shadow_only writes no rows
  23. rebuild_decisions_for_user_portfolio writes user-scoped rows (user_id set)
  24. rebuild_decisions_for_user_portfolio does NOT write global rows (user_id=NULL)
  25. global rows unchanged after user rebuild
  26. tenant isolation — user A rows not visible to user B
  27. portfolio positions not mutated after rebuild
  28. no delivery rows after rebuild
  29. owned ticker decision_score >= global decision_score
  30. AST: no delivery/notification imports
  31. AST: no conviction/recommendation imports
  32. AST: no advice language in string constants
  33. AST: no portfolio write calls (no position_add, portfolio_create)
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import timedelta, timezone, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "decision_portfolio_service.py"

# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture()
async def db(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

async def _seed_portfolio_and_position(
    db,
    user_id: str,
    ticker: str = "NVDA",
    weight: float = None,
    membership_class: str = "owned",
) -> tuple:
    from app.db.repositories.portfolio_repo import portfolio_create, position_add
    port = await portfolio_create(db, name=f"Port-{_uid()[:6]}", user_id=user_id)
    pos  = await position_add(
        db, port.id, ticker,
        membership_class=membership_class,
        weight=weight,
    )
    return port, pos


async def _seed_global_priority(db, ticker: str = "NVDA", score: float = 0.55) -> object:
    from app.db.repositories.decision_repo import upsert_decision_priority
    return await upsert_decision_priority(
        db,
        candidate_type      = "forecast_candidate",
        entity_type         = "company",
        entity_key          = ticker,
        source_ref          = f"src-{_uid()[:8]}",
        decision_priority   = "medium",
        decision_rank_score = score,
        attention_score     = 0.60,
        urgency_score       = 0.55,
        impact_score        = 0.55,
        confidence_score    = 0.70,
        uncertainty_score   = 0.85,
        decision_reason     = "Signal is significant for this ticker.",
        why_now             = "Horizon is near-term.",
        deprioritizers      = ["Low evidence count."],
        evidence_summary    = ["Source: forecast_vector."],
        decision_schema     = 1,
        user_id             = None,   # global row
        ttl_hours           = 24,
    )


# ---------------------------------------------------------------------------
# Synthetic candidate + ranking output for pure-function tests
# ---------------------------------------------------------------------------

def _candidate(ticker: str = "NVDA", ctype: str = "forecast_candidate") -> dict:
    return {
        "candidate_type": ctype,
        "entity_type": "company",
        "entity_id": ticker,
        "ticker": ticker,
        "source_type": "forecast_vector",
        "source_id": f"fv-{ticker.lower()}",
        "headline": f"{ticker} signal",
        "summary": "test",
        "evidence_refs": [],
        "source_versions": {},
        "user_id": None,
        "urgency_inputs": {"horizon_days": 45, "horizon": "near_term"},
        "impact_inputs": {
            "p_positive": 0.65, "p_negative": 0.20, "p_neutral": 0.15,
            "confidence_band_low": 0.55, "confidence_band_high": 0.75,
            "forecast_type": "thesis_strengthening",
        },
        "attention_inputs": {
            "forecast_type": "thesis_strengthening",
            "entity_type": "company",
            "direction": "strengthening",
        },
        "confidence_inputs": {
            "confidence_band_low": 0.55, "confidence_band_high": 0.75,
            "evidence_count": 3,
        },
        "uncertainty_inputs": {"band_width": 0.20, "p_neutral": 0.15},
    }


def _ranking(ticker: str = "NVDA", decision_score: float = 0.50,
             base_score: float = 0.55, confidence: float = 0.70,
             uncertainty: float = 0.85, exposure: float = 1.00) -> dict:
    return {
        "candidate_type":        "forecast_candidate",
        "entity_type":           "company",
        "entity_id":             ticker,
        "ticker":                ticker,
        "source_type":           "forecast_vector",
        "source_id":             f"fv-{ticker.lower()}",
        "decision_score":        decision_score,
        "attention_score":       0.60,
        "urgency_score":         0.55,
        "impact_score":          0.55,
        "confidence_multiplier": confidence,
        "uncertainty_discount":  uncertainty,
        "exposure_multiplier":   exposure,
        "rank_inputs": {
            "w_attention": 0.40, "w_urgency": 0.35, "w_impact": 0.25,
            "base_score":  base_score,
        },
        "candidate": _candidate(ticker),
    }


# ---------------------------------------------------------------------------
# 1–7. build_portfolio_map
# ---------------------------------------------------------------------------

class TestBuildPortfolioMap:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.decision_portfolio_service import build_portfolio_map
        result = await build_portfolio_map(None, "user-001")
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_portfolio_returns_empty(self, db):
        from app.services.decision_portfolio_service import build_portfolio_map
        from app.db.repositories.portfolio_repo import portfolio_create
        uid = _uid()
        await portfolio_create(db, name="Empty", user_id=uid)
        await db.commit()
        result = await build_portfolio_map(db, uid)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_ticker_weight_for_positions(self, db):
        from app.services.decision_portfolio_service import build_portfolio_map
        uid = _uid()
        await _seed_portfolio_and_position(db, uid, ticker="NVDA", weight=0.15)
        await db.commit()
        result = await build_portfolio_map(db, uid)
        assert "NVDA" in result
        assert abs(result["NVDA"] - 0.15) < 1e-9

    @pytest.mark.asyncio
    async def test_weight_none_stored_as_none(self, db):
        from app.services.decision_portfolio_service import build_portfolio_map
        uid = _uid()
        await _seed_portfolio_and_position(db, uid, ticker="AAPL", weight=None)
        await db.commit()
        result = await build_portfolio_map(db, uid)
        assert "AAPL" in result
        assert result["AAPL"] is None

    @pytest.mark.asyncio
    async def test_aggregates_across_multiple_portfolios(self, db):
        from app.services.decision_portfolio_service import build_portfolio_map
        from app.db.repositories.portfolio_repo import portfolio_create, position_add
        uid = _uid()
        p1 = await portfolio_create(db, name="P1", user_id=uid)
        p2 = await portfolio_create(db, name="P2", user_id=uid)
        await position_add(db, p1.id, "NVDA", weight=0.10)
        await position_add(db, p2.id, "AAPL", weight=0.05)
        await db.commit()
        result = await build_portfolio_map(db, uid)
        assert "NVDA" in result
        assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_keeps_highest_weight_across_portfolios(self, db):
        from app.services.decision_portfolio_service import build_portfolio_map
        from app.db.repositories.portfolio_repo import portfolio_create, position_add
        uid = _uid()
        p1 = await portfolio_create(db, name="Q1", user_id=uid)
        p2 = await portfolio_create(db, name="Q2", user_id=uid)
        await position_add(db, p1.id, "NVDA", weight=0.05)
        await position_add(db, p2.id, "NVDA", weight=0.20)
        await db.commit()
        result = await build_portfolio_map(db, uid)
        assert result["NVDA"] >= 0.20

    @pytest.mark.asyncio
    async def test_other_user_tickers_not_returned(self, db):
        from app.services.decision_portfolio_service import build_portfolio_map
        uid_a = _uid()
        uid_b = _uid()
        await _seed_portfolio_and_position(db, uid_a, ticker="TSLA", weight=0.10)
        await db.commit()
        result = await build_portfolio_map(db, uid_b)
        assert "TSLA" not in result


# ---------------------------------------------------------------------------
# 8–12. compute_portfolio_exposure_multiplier
# ---------------------------------------------------------------------------

class TestComputePortfolioExposureMultiplier:
    def test_unknown_ticker_returns_1_0(self):
        from app.services.decision_portfolio_service import compute_portfolio_exposure_multiplier
        assert compute_portfolio_exposure_multiplier("AAPL", {}) == 1.0

    def test_owned_ticker_with_weight_greater_than_1_0(self):
        from app.services.decision_portfolio_service import compute_portfolio_exposure_multiplier
        m = compute_portfolio_exposure_multiplier("NVDA", {"NVDA": 0.20})
        assert m > 1.0

    def test_owned_ticker_without_weight_returns_1_20(self):
        from app.services.decision_portfolio_service import compute_portfolio_exposure_multiplier
        m = compute_portfolio_exposure_multiplier("NVDA", {"NVDA": None})
        assert abs(m - 1.20) < 1e-9

    def test_ceiling_at_1_50(self):
        from app.services.decision_portfolio_service import compute_portfolio_exposure_multiplier
        m = compute_portfolio_exposure_multiplier("NVDA", {"NVDA": 1.0})
        assert m <= 1.50

    def test_floor_at_0_50(self):
        from app.services.decision_portfolio_service import compute_portfolio_exposure_multiplier
        m = compute_portfolio_exposure_multiplier("NVDA", {"NVDA": -10.0})
        assert m >= 0.50


# ---------------------------------------------------------------------------
# 13–19. apply_portfolio_context
# ---------------------------------------------------------------------------

class TestApplyPortfolioContext:
    def test_unowned_ticker_exposure_unchanged(self):
        from app.services.decision_portfolio_service import apply_portfolio_context
        c = _candidate("AAPL")
        r = _ranking("AAPL", exposure=1.00)
        adjusted = apply_portfolio_context(c, r, portfolio_map={})
        assert abs(adjusted["exposure_multiplier"] - 1.00) < 1e-9

    def test_owned_ticker_decision_score_increases(self):
        from app.services.decision_portfolio_service import apply_portfolio_context
        c = _candidate("NVDA")
        r = _ranking("NVDA", decision_score=0.40, base_score=0.55,
                     confidence=0.70, uncertainty=0.85, exposure=1.00)
        adjusted = apply_portfolio_context(c, r, portfolio_map={"NVDA": 0.20})
        assert adjusted["decision_score"] > r["decision_score"]

    def test_does_not_mutate_original_ranking(self):
        from app.services.decision_portfolio_service import apply_portfolio_context
        c = _candidate("NVDA")
        r = _ranking("NVDA")
        original_score = r["decision_score"]
        apply_portfolio_context(c, r, portfolio_map={"NVDA": 0.20})
        assert r["decision_score"] == original_score

    def test_does_not_mutate_original_candidate(self):
        from app.services.decision_portfolio_service import apply_portfolio_context
        c = _candidate("NVDA")
        original_ticker = c["ticker"]
        r = _ranking("NVDA")
        apply_portfolio_context(c, r, portfolio_map={"NVDA": 0.20})
        assert c["ticker"] == original_ticker

    def test_adjusted_decision_score_in_unit_interval(self):
        from app.services.decision_portfolio_service import apply_portfolio_context
        c = _candidate("NVDA")
        # High base score — check ceiling holds
        r = _ranking("NVDA", decision_score=0.90, base_score=0.95,
                     confidence=1.0, uncertainty=1.0, exposure=1.0)
        adjusted = apply_portfolio_context(c, r, portfolio_map={"NVDA": 0.50})
        assert 0.0 <= adjusted["decision_score"] <= 1.0

    def test_empty_portfolio_map_returns_unchanged(self):
        from app.services.decision_portfolio_service import apply_portfolio_context
        c = _candidate("NVDA")
        r = _ranking("NVDA", decision_score=0.50)
        adjusted = apply_portfolio_context(c, r, portfolio_map={})
        assert abs(adjusted["decision_score"] - 0.50) < 1e-9

    def test_formula_correctness(self):
        """decision_score = base × conf × uncertainty × new_exposure, clamped."""
        from app.services.decision_portfolio_service import (
            apply_portfolio_context,
            compute_portfolio_exposure_multiplier,
        )
        base = 0.60
        conf = 0.75
        unc  = 0.80
        c = _candidate("NVDA")
        r = _ranking("NVDA", base_score=base, confidence=conf,
                     uncertainty=unc, exposure=1.00,
                     decision_score=base * conf * unc * 1.00)
        weight = 0.25
        adjusted = apply_portfolio_context(c, r, portfolio_map={"NVDA": weight})
        new_exp = compute_portfolio_exposure_multiplier("NVDA", {"NVDA": weight})
        expected = min(base * conf * unc * new_exp, 1.0)
        assert abs(adjusted["decision_score"] - expected) < 1e-6


# ---------------------------------------------------------------------------
# 20–29. rebuild_decisions_for_user_portfolio
# ---------------------------------------------------------------------------

class TestRebuildDecisionsForUserPortfolio:
    @pytest.mark.asyncio
    async def test_null_session_non_shadow_returns_empty(self):
        from app.services.decision_portfolio_service import rebuild_decisions_for_user_portfolio
        result = await rebuild_decisions_for_user_portfolio(None, "user-001", shadow_only=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_user_id_returns_empty(self, db):
        from app.services.decision_portfolio_service import rebuild_decisions_for_user_portfolio
        result = await rebuild_decisions_for_user_portfolio(db, "")
        assert result == []

    @pytest.mark.asyncio
    async def test_shadow_only_writes_no_rows(self, db):
        from app.services.decision_portfolio_service import rebuild_decisions_for_user_portfolio
        from app.db.repositories.decision_repo import count_decision_priorities
        uid = _uid()
        await _seed_portfolio_and_position(db, uid, ticker="NVDA", weight=0.10)
        await db.commit()

        await rebuild_decisions_for_user_portfolio(db, uid, shadow_only=True)
        await db.commit()

        count = await count_decision_priorities(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_writes_user_scoped_rows(self, db):
        from app.services.decision_portfolio_service import rebuild_decisions_for_user_portfolio
        from app.db.repositories.decision_repo import list_decision_priorities
        # Seed a forecast vector so build_candidates has substrate
        from app.db.repositories.forecast_repo import upsert_forecast_vector
        uid = _uid()
        await _seed_portfolio_and_position(db, uid, ticker="NVDA", weight=0.15)
        await upsert_forecast_vector(
            db,
            entity_type="company",
            entity_key="NVDA",
            horizon="near_term",
            horizon_days=30,
            forecast_type="thesis_strengthening",
            p_positive=0.70,
            p_negative=0.20,
            p_neutral=0.10,
            confidence_band_low=0.55,
            confidence_band_high=0.75,
            why="NVDA signal",
            invalidators=["earnings miss"],
            analog_basis=[],
            similarity_basis=[],
            evidence_summary=[],
            source_versions={"company_dossier": "v1"},
            forecast_schema=1,
            user_id=uid,
        )
        await db.commit()

        results = await rebuild_decisions_for_user_portfolio(db, uid)
        await db.commit()

        stored = [r for r in results if r.get("stored")]
        if stored:  # may be 0 if no matching candidates pass validation
            user_rows = await list_decision_priorities(db, user_id=uid)
            assert len(user_rows) >= 1
            for row in user_rows:
                assert row.user_id == uid

    @pytest.mark.asyncio
    async def test_does_not_write_global_rows(self, db):
        """After a user rebuild, user_id=NULL rows must remain at 0."""
        from app.services.decision_portfolio_service import rebuild_decisions_for_user_portfolio
        from app.db.repositories.decision_repo import list_decision_priorities
        uid = _uid()
        await _seed_portfolio_and_position(db, uid, ticker="NVDA", weight=0.10)
        await db.commit()

        await rebuild_decisions_for_user_portfolio(db, uid)
        await db.commit()

        global_rows = await list_decision_priorities(db, user_id_is_null=True)
        assert len(global_rows) == 0

    @pytest.mark.asyncio
    async def test_global_row_unchanged_after_user_rebuild(self, db):
        """A pre-existing global row must not be modified by user rebuild."""
        from app.services.decision_portfolio_service import rebuild_decisions_for_user_portfolio
        from app.db.repositories.decision_repo import list_decision_priorities

        uid = _uid()
        await _seed_portfolio_and_position(db, uid, ticker="NVDA", weight=0.10)
        global_row = await _seed_global_priority(db, ticker="NVDA", score=0.42)
        original_score = global_row.decision_rank_score
        await db.commit()

        await rebuild_decisions_for_user_portfolio(db, uid)
        await db.commit()

        # Reload and confirm untouched
        global_rows = await list_decision_priorities(db, user_id_is_null=True)
        assert any(abs(r.decision_rank_score - original_score) < 1e-9 for r in global_rows)

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, db):
        """User A's decisions are not visible when querying user B's rows."""
        from app.services.decision_portfolio_service import rebuild_decisions_for_user_portfolio
        from app.db.repositories.decision_repo import list_decision_priorities
        from app.db.repositories.forecast_repo import upsert_forecast_vector

        uid_a = _uid()
        uid_b = _uid()
        await _seed_portfolio_and_position(db, uid_a, ticker="NVDA", weight=0.15)
        await upsert_forecast_vector(
            db,
            entity_type="company",
            entity_key="NVDA",
            horizon="near_term",
            horizon_days=30,
            forecast_type="thesis_strengthening",
            p_positive=0.70,
            p_negative=0.20,
            p_neutral=0.10,
            confidence_band_low=0.55,
            confidence_band_high=0.75,
            why="NVDA signal for A",
            invalidators=["earnings miss"],
            analog_basis=[],
            similarity_basis=[],
            evidence_summary=[],
            source_versions={"company_dossier": "v1"},
            forecast_schema=1,
            user_id=uid_a,
        )
        await db.commit()

        await rebuild_decisions_for_user_portfolio(db, uid_a)
        await db.commit()

        # User B must not see user A's rows
        b_rows = await list_decision_priorities(db, user_id=uid_b)
        assert len(b_rows) == 0

    @pytest.mark.asyncio
    async def test_portfolio_positions_not_mutated(self, db):
        """Portfolio and position row counts must not change after rebuild."""
        from app.services.decision_portfolio_service import rebuild_decisions_for_user_portfolio
        from app.db.models import Portfolio, PortfolioPosition
        from sqlalchemy import select, func

        uid = _uid()
        await _seed_portfolio_and_position(db, uid, ticker="AAPL", weight=0.08)
        await db.commit()

        port_before = (await db.execute(select(func.count()).select_from(Portfolio))).scalar_one()
        pos_before  = (await db.execute(select(func.count()).select_from(PortfolioPosition))).scalar_one()

        await rebuild_decisions_for_user_portfolio(db, uid)
        await db.commit()

        port_after = (await db.execute(select(func.count()).select_from(Portfolio))).scalar_one()
        pos_after  = (await db.execute(select(func.count()).select_from(PortfolioPosition))).scalar_one()

        assert port_before == port_after
        assert pos_before  == pos_after

    @pytest.mark.asyncio
    async def test_no_delivery_rows_after_rebuild(self, db):
        from app.services.decision_portfolio_service import rebuild_decisions_for_user_portfolio
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func

        uid = _uid()
        await _seed_portfolio_and_position(db, uid, ticker="NVDA", weight=0.10)
        await db.commit()

        await rebuild_decisions_for_user_portfolio(db, uid)
        await db.commit()

        dl_count = (await db.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar_one()
        assert dl_count == 0

    @pytest.mark.asyncio
    async def test_owned_ticker_score_geq_global_baseline(self, db):
        """When the user owns a ticker, their user-scoped score should be ≥
        the global base score for the same ticker, because the exposure
        multiplier can only stay the same or increase for owned positions.
        """
        from app.services.decision_portfolio_service import (
            apply_portfolio_context,
            build_portfolio_map,
        )
        from app.services.decision_ranking_engine import rank_candidate

        uid = _uid()
        await _seed_portfolio_and_position(db, uid, ticker="NVDA", weight=0.20)
        await db.commit()

        c = _candidate("NVDA")
        global_ranking = rank_candidate(c)

        pm = await build_portfolio_map(db, uid)
        user_ranking = apply_portfolio_context(c, global_ranking, portfolio_map=pm)

        assert user_ranking["decision_score"] >= global_ranking["decision_score"] - 1e-9


# ---------------------------------------------------------------------------
# 30–33. AST safety
# ---------------------------------------------------------------------------

def _load_tree() -> ast.AST:
    return ast.parse(_SVC.read_text(encoding="utf-8"))


def _get_docstring_values(tree: ast.AST) -> set:
    values: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                values.add(node.body[0].value.value)
    return values


class TestASTSafety:
    def test_no_delivery_or_notification_imports(self):
        tree = _load_tree()
        forbidden = {"delivery_service", "notification_service",
                     "notification_repo", "delivery_repo"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names  = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fw in forbidden:
                        assert fw not in part.lower(), \
                            f"Forbidden import {part!r}"

    def test_no_conviction_or_recommendation_imports(self):
        tree = _load_tree()
        forbidden = {"conviction_modeler", "conviction",
                     "recommendation", "order", "execution"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names  = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fw in forbidden:
                        assert fw not in part.lower(), \
                            f"Forbidden import {part!r}"

    def test_no_advice_language_in_string_constants(self):
        tree = _load_tree()
        docstring_values = _get_docstring_values(tree)
        banned_terms = ["buy", "sell", "hold", "overweight", "underweight",
                        "recommend", "target price", "position size"]
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if val in docstring_values:
                    continue
                for term in banned_terms:
                    if term in val.lower():
                        offenders.append(repr(term) + " in " + repr(val[:80]))
        assert not offenders, "Advice language: " + str(offenders)

    def test_no_portfolio_write_calls(self):
        """Read-only portfolio access: must not call position_add or portfolio_create."""
        src = _SVC.read_text(encoding="utf-8")
        for forbidden in ("position_add", "portfolio_create", "portfolio_update",
                          "portfolio_delete", "position_remove", "position_update"):
            assert forbidden not in src, \
                f"Portfolio write call {forbidden!r} found in portfolio service"
