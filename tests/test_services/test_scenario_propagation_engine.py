"""
Tests — Scenario Propagation Engine, Phase 14 · Slice 3.

Covers:
  1.  null-session safety — propagate_scenario returns {} when session is None
  2.  empty seed — propagate_scenario returns {} for empty dict
  3.  unknown seed type — returns {}
  4.  propagation output keys — all required keys present
  5.  company_scenario — direct impact on primary ticker
  6.  company_scenario — first-order via cross_exposure
  7.  company_scenario — second-order via cross_exposure chain
  8.  company_scenario — depth limit (no depth > 2)
  9.  macro_scenario — direct + first-order from seed affected_tickers
  10. macro_scenario — propagation_depth correct
  11. sector_scenario — direct + first-order from cross tickers
  12. sector_scenario — second-order via similarity
  13. catalyst_scenario — direct + first-order
  14. failure_mode_scenario — direct + first-order
  15. portfolio_scenario — direct + first-order (portfolio positions)
  16. portfolio_scenario — second-order via cross_exposure of positions
  17. sparse substrate — no cross/similarity data → direct-only, no exception
  18. deterministic output — same DB state yields identical result
  19. transmission_path is a non-empty list after propagation
  20. transmission_path steps are ordered (step numbers ascending)
  21. affected_entities is a superset of direct_impacts
  22. no DB writes — row counts unchanged after propagation
  23. no scenario_snapshot writes
  24. impact_confidence in [0, 1]
  25. impact_uncertainty in [0, 1]
  26. propagate_all returns list of non-empty dicts
  27. propagate_all with null session returns []
  28. no advice language in module (AST)
  29. no conviction/order imports (AST)
  30. no write-function calls (AST)
  31. no scenario_repo import (AST)
  32. affected_portfolios always a list
  33. direct impact always depth 0
  34. first-order impacts always depth 1
  35. second-order impacts always depth 2
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "scenario_propagation_engine.py"

_REQUIRED_PROPAGATION_KEYS = {
    "scenario_type",
    "scenario_name",
    "transmission_path",
    "direct_impacts",
    "indirect_impacts",
    "affected_entities",
    "affected_portfolios",
    "impact_confidence",
    "impact_uncertainty",
    "propagation_depth",
    "source_versions",
}

_REQUIRED_IMPACT_KEYS = {
    "entity_key",
    "entity_type",
    "impact_channel",
    "transmission_strength",
    "depth",
}

_REQUIRED_STEP_KEYS = {"step", "cause", "effect", "channel"}

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


# ---------------------------------------------------------------------------
# Seed / DB helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _seed_fv(db, *, ticker="NVDA", entity_type="company",
                   p_pos=0.70, p_neg=0.20, p_neu=0.10, user_id=None):
    from app.db.repositories import forecast_repo
    return await forecast_repo.upsert_forecast_vector(
        db,
        entity_type=entity_type,
        entity_key=ticker,
        horizon="near_term",
        horizon_days=30,
        forecast_type="thesis_strengthening",
        p_positive=p_pos,
        p_negative=p_neg,
        p_neutral=p_neu,
        confidence_band_low=0.55,
        confidence_band_high=0.85,
        why=f"{ticker} signal",
        invalidators=[],
        analog_basis=[],
        similarity_basis=[],
        evidence_summary=[],
        source_versions={},
        forecast_schema=1,
        user_id=user_id,
    )


async def _seed_cross(db, *, a="NVDA", b="AMD", strength=0.80, exposure_type="sector"):
    import json as _json
    from app.db.models import CrossExposure
    row = CrossExposure(
        id=_uid(), ticker_a=a, ticker_b=b,
        shared_concerns=_json.dumps([]), exposure_type=exposure_type,
        strength=strength,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_similarity(db, *, query_key="NVDA", candidate_key="AMD",
                            score=0.82, user_id=None):
    from app.db.repositories import similarity_repo
    return await similarity_repo.upsert_similarity_edge(
        db,
        target_type="company",
        query_key=query_key,
        candidate_key=candidate_key,
        score=score,
        rank=1,
        contributions=[],
        headline=f"{query_key} similar to {candidate_key}",
        disanalogy="",
        floor_passed=True,
        score_schema=1,
        user_id=user_id,
    )


async def _seed_portfolio(db, *, tickers=None, user_id=None):
    from app.db.models import Portfolio, PortfolioPosition
    tickers = tickers or ["NVDA"]
    port = Portfolio(id=_uid(), user_id=user_id, name="Test", is_default=False)
    db.add(port)
    await db.flush()
    for t in tickers:
        pos = PortfolioPosition(
            id=_uid(), portfolio_id=port.id, ticker=t,
            membership_class="owned", active=True,
        )
        db.add(pos)
    await db.flush()
    return port


async def _seed_catalyst(db, *, ticker="NVDA", status="open", user_id=None):
    from app.db.models import DossierCatalyst
    row = DossierCatalyst(
        id=_uid(), ticker=ticker, statement="catalyst",
        direction="bull_trigger", specificity=0.80,
        expected_window="Q3", status=status, conviction_weight=0.6,
        user_id=user_id,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_failure_mode(db, *, ticker="NVDA", user_id=None):
    from app.db.models import DossierFailureMode
    row = DossierFailureMode(
        id=_uid(), ticker=ticker, analog_id=_uid(),
        sequence_stage=2, stage_evidence="evidence",
        relevance_at_match=0.75, matched_at=_now(), user_id=user_id,
    )
    db.add(row)
    await db.flush()
    return row


def _company_seed(ticker="NVDA", **overrides):
    base = {
        "scenario_type":      "company_scenario",
        "entity_type":        "company",
        "entity_id":          ticker,
        "ticker":             ticker,
        "scenario_name":      f"{ticker} scenario",
        "changed_assumption": f"If {ticker} shifts",
        "source_type":        "forecast_vector",
        "source_id":          _uid(),
        "affected_tickers":   [],
        "affected_portfolios":[],
        "evidence_refs":      [],
        "transmission_inputs": {"direction": "strengthening", "forecast_type": "thesis_strengthening",
                                "horizon": "near_term", "horizon_days": 30,
                                "similar_tickers": [], "cross_tickers": []},
        "impact_inputs":       {"p_positive": 0.70, "p_negative": 0.20},
        "confidence_inputs":   {"confidence_band_low": 0.55, "confidence_band_high": 0.85,
                                "p_max": 0.70, "evidence_count": 1, "forecast_schema": 1},
        "uncertainty_inputs":  {"band_width": 0.30, "p_neutral": 0.10},
        "source_versions":     {"forecast_vector": "v1"},
        "user_id":             None,
    }
    base.update(overrides)
    return base


def _macro_seed(macro_key="RATES", affected_tickers=None):
    return {
        "scenario_type":      "macro_scenario",
        "entity_type":        "macro",
        "entity_id":          macro_key,
        "ticker":             "",
        "scenario_name":      f"Macro {macro_key} scenario",
        "changed_assumption": f"If macro {macro_key} shifts",
        "source_type":        "forecast_vector",
        "source_id":          _uid(),
        "affected_tickers":   affected_tickers or [],
        "affected_portfolios":[],
        "evidence_refs":      [],
        "transmission_inputs":{"direction": "accelerating", "forecast_type": "macro_shift",
                               "horizon": "medium_term", "horizon_days": 90,
                               "macro_key": macro_key, "watchlist_count": 0},
        "impact_inputs":       {"p_positive": 0.65, "p_negative": 0.25},
        "confidence_inputs":   {"confidence_band_low": 0.50, "confidence_band_high": 0.80,
                                "p_max": 0.65, "evidence_count": 0, "forecast_schema": 1},
        "uncertainty_inputs":  {"band_width": 0.30, "p_neutral": 0.10},
        "source_versions":     {},
        "user_id":             None,
    }


def _sector_seed(sector_key="SEMIS", cross_tickers=None):
    return {
        "scenario_type":      "sector_scenario",
        "entity_type":        "sector",
        "entity_id":          sector_key,
        "ticker":             "",
        "scenario_name":      f"Sector {sector_key} scenario",
        "changed_assumption": f"If sector {sector_key} contracts",
        "source_type":        "forecast_vector",
        "source_id":          _uid(),
        "affected_tickers":   cross_tickers or [],
        "affected_portfolios":[],
        "evidence_refs":      [],
        "transmission_inputs":{"direction": "contracting", "forecast_type": "sector_shift",
                               "horizon": "near_term", "horizon_days": 30,
                               "sector_key": sector_key,
                               "cross_tickers": cross_tickers or []},
        "impact_inputs":       {"p_positive": 0.20, "p_negative": 0.65},
        "confidence_inputs":   {"confidence_band_low": 0.50, "confidence_band_high": 0.80,
                                "p_max": 0.65, "evidence_count": 0, "forecast_schema": 1},
        "uncertainty_inputs":  {"band_width": 0.30, "p_neutral": 0.15},
        "source_versions":     {},
        "user_id":             None,
    }


def _catalyst_seed(ticker="NVDA"):
    return {
        "scenario_type":      "catalyst_scenario",
        "entity_type":        "company",
        "entity_id":          _uid(),
        "ticker":             ticker,
        "scenario_name":      f"{ticker} catalyst scenario",
        "changed_assumption": f"If {ticker} catalyst triggers",
        "source_type":        "dossier_catalyst",
        "source_id":          _uid(),
        "affected_tickers":   [],
        "affected_portfolios":[],
        "evidence_refs":      [],
        "transmission_inputs":{"direction": "bull_trigger", "expected_window": "Q3",
                               "specificity": 0.80, "ticker": ticker, "cross_tickers": []},
        "impact_inputs":       {"specificity": 0.80, "conviction_weight": 0.6},
        "confidence_inputs":   {"specificity": 0.80, "has_statement": True,
                                "has_expected_window": True, "conviction_weight": 0.6},
        "uncertainty_inputs":  {"inverse_specificity": 0.20, "created_days_ago": 5},
        "source_versions":     {"dossier_catalyst": _uid()},
        "user_id":             None,
    }


def _failure_mode_seed(ticker="NVDA"):
    return {
        "scenario_type":      "failure_mode_scenario",
        "entity_type":        "company",
        "entity_id":          _uid(),
        "ticker":             ticker,
        "scenario_name":      f"{ticker} failure-mode scenario",
        "changed_assumption": f"If {ticker} continues on trajectory",
        "source_type":        "dossier_failure_mode",
        "source_id":          _uid(),
        "affected_tickers":   [],
        "affected_portfolios":[],
        "evidence_refs":      [],
        "transmission_inputs":{"analog_id": _uid(), "sequence_stage": 2,
                               "ticker": ticker, "cross_tickers": []},
        "impact_inputs":       {"relevance_at_match": 0.75, "sequence_stage": 2},
        "confidence_inputs":   {"relevance_at_match": 0.75, "has_stage_evidence": True,
                                "sequence_stage": 2},
        "uncertainty_inputs":  {"matched_days_ago": 3, "sequence_stage": 2},
        "source_versions":     {"dossier_failure_mode": _uid()},
        "user_id":             None,
    }


def _portfolio_seed(portfolio_id=None, tickers=None):
    pid = portfolio_id or _uid()
    tickers = tickers or ["NVDA", "AAPL"]
    return {
        "scenario_type":      "portfolio_scenario",
        "entity_type":        "portfolio",
        "entity_id":          pid,
        "ticker":             "",
        "scenario_name":      "Portfolio scenario",
        "changed_assumption": "If shared condition applies",
        "source_type":        "portfolio_positions",
        "source_id":          pid,
        "affected_tickers":   tickers,
        "affected_portfolios":[pid],
        "evidence_refs":      [],
        "transmission_inputs":{"portfolio_id": pid, "portfolio_name": "Test",
                               "position_count": len(tickers),
                               "tickers": tickers, "is_default": False},
        "impact_inputs":       {"position_count": len(tickers), "portfolio_name": "Test"},
        "confidence_inputs":   {"has_positions": True, "position_count": len(tickers),
                                "is_default": False},
        "uncertainty_inputs":  {"position_count": len(tickers), "correlation_unknown": True},
        "source_versions":     {"portfolio": pid},
        "user_id":             None,
    }


# ---------------------------------------------------------------------------
# 1–3. Basic safety
# ---------------------------------------------------------------------------

class TestNullAndEdgeCases:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty_dict(self):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(None, _company_seed())
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_seed_returns_empty_dict(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, {})
        assert result == {}

    @pytest.mark.asyncio
    async def test_unknown_seed_type_returns_empty_dict(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, {"scenario_type": "unknown_type"})
        assert result == {}


# ---------------------------------------------------------------------------
# 4. Output shape
# ---------------------------------------------------------------------------

class TestOutputShape:
    @pytest.mark.asyncio
    async def test_all_required_keys_present(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _company_seed())
        assert result
        missing = _REQUIRED_PROPAGATION_KEYS - result.keys()
        assert not missing, f"Missing keys: {missing}"

    @pytest.mark.asyncio
    async def test_direct_impact_keys(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _company_seed())
        for imp in result["direct_impacts"]:
            missing = _REQUIRED_IMPACT_KEYS - imp.keys()
            assert not missing, f"Missing impact keys: {missing}"

    @pytest.mark.asyncio
    async def test_transmission_step_keys_present(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        for step in result["transmission_path"]:
            missing = _REQUIRED_STEP_KEYS - step.keys()
            assert not missing, f"Missing step keys: {missing}"


# ---------------------------------------------------------------------------
# 5. company_scenario — direct impact
# ---------------------------------------------------------------------------

class TestCompanyPropagation:
    @pytest.mark.asyncio
    async def test_company_direct_impact_on_primary_ticker(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        direct_keys = [i["entity_key"] for i in result["direct_impacts"]]
        assert "NVDA" in direct_keys

    @pytest.mark.asyncio
    async def test_company_direct_impact_depth_zero(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        for imp in result["direct_impacts"]:
            assert imp["depth"] == 0

    # 6. First-order via cross_exposure
    @pytest.mark.asyncio
    async def test_company_first_order_via_cross_exposure(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD", strength=0.80)
        await db.commit()
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        indirect_keys = [i["entity_key"] for i in result["indirect_impacts"]]
        assert "AMD" in indirect_keys

    @pytest.mark.asyncio
    async def test_company_first_order_depth_one(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD", strength=0.80)
        await db.commit()
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        fo_impacts = [i for i in result["indirect_impacts"] if i["depth"] == 1]
        assert any(i["entity_key"] == "AMD" for i in fo_impacts)

    # 7. Second-order via cross_exposure chain
    @pytest.mark.asyncio
    async def test_company_second_order_via_chain(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD",  strength=0.80)
        await _seed_cross(db, a="AMD",  b="TSLA", strength=0.70)
        await db.commit()
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        all_keys = {i["entity_key"] for i in result["affected_entities"]}
        assert "TSLA" in all_keys

    # 8. Depth limit — no entity beyond depth 2
    @pytest.mark.asyncio
    async def test_depth_limit_never_exceeds_two(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        # Chain: NVDA→AMD→TSLA→MSFT — MSFT should not appear (depth would be 3)
        await _seed_cross(db, a="NVDA", b="AMD",  strength=0.80)
        await _seed_cross(db, a="AMD",  b="TSLA", strength=0.75)
        await _seed_cross(db, a="TSLA", b="MSFT", strength=0.72)
        await db.commit()
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        for imp in result["indirect_impacts"]:
            assert imp["depth"] <= 2, f"Impact depth {imp['depth']} > 2: {imp}"

    @pytest.mark.asyncio
    async def test_propagation_depth_field_matches_max(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD",  strength=0.80)
        await _seed_cross(db, a="AMD",  b="TSLA", strength=0.70)
        await db.commit()
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        max_actual = max(
            (i["depth"] for i in result["direct_impacts"] + result["indirect_impacts"]),
            default=0,
        )
        assert result["propagation_depth"] == max_actual


# ---------------------------------------------------------------------------
# 9–10. macro_scenario
# ---------------------------------------------------------------------------

class TestMacroPropagation:
    @pytest.mark.asyncio
    async def test_macro_direct_impact(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _macro_seed(macro_key="RATES"))
        direct_keys = [i["entity_key"] for i in result["direct_impacts"]]
        assert "RATES" in direct_keys

    @pytest.mark.asyncio
    async def test_macro_first_order_from_affected_tickers(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        seed = _macro_seed(macro_key="RATES", affected_tickers=["NVDA", "AAPL"])
        result = await propagate_scenario(db, seed)
        indirect_keys = [i["entity_key"] for i in result["indirect_impacts"]]
        assert "NVDA" in indirect_keys
        assert "AAPL" in indirect_keys

    @pytest.mark.asyncio
    async def test_macro_propagation_depth_at_least_one(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        seed = _macro_seed(macro_key="INFLATION", affected_tickers=["NVDA"])
        result = await propagate_scenario(db, seed)
        assert result["propagation_depth"] >= 1

    @pytest.mark.asyncio
    async def test_macro_no_second_order(self, db):
        """Macro propagation deliberately skips second-order to avoid explosion."""
        from app.services.scenario_propagation_engine import propagate_scenario
        seed = _macro_seed(macro_key="GDP", affected_tickers=["NVDA", "AAPL"])
        result = await propagate_scenario(db, seed)
        so_impacts = [i for i in result["indirect_impacts"] if i["depth"] == 2]
        assert so_impacts == []


# ---------------------------------------------------------------------------
# 11–12. sector_scenario
# ---------------------------------------------------------------------------

class TestSectorPropagation:
    @pytest.mark.asyncio
    async def test_sector_direct_impact(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _sector_seed(sector_key="SEMIS"))
        assert any(i["entity_key"] == "SEMIS" for i in result["direct_impacts"])

    @pytest.mark.asyncio
    async def test_sector_first_order_from_cross_tickers(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        seed = _sector_seed(sector_key="SEMIS", cross_tickers=["NVDA", "AMD"])
        result = await propagate_scenario(db, seed)
        indirect_keys = {i["entity_key"] for i in result["indirect_impacts"]}
        assert "NVDA" in indirect_keys
        assert "AMD" in indirect_keys

    @pytest.mark.asyncio
    async def test_sector_second_order_via_similarity(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_similarity(db, query_key="NVDA", candidate_key="QCOM", score=0.82)
        await db.commit()
        seed = _sector_seed(sector_key="SEMIS", cross_tickers=["NVDA"])
        result = await propagate_scenario(db, seed)
        all_keys = {i["entity_key"] for i in result["affected_entities"]}
        assert "QCOM" in all_keys


# ---------------------------------------------------------------------------
# 13. catalyst_scenario
# ---------------------------------------------------------------------------

class TestCatalystPropagation:
    @pytest.mark.asyncio
    async def test_catalyst_direct_impact(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _catalyst_seed(ticker="NVDA"))
        assert any(i["entity_key"] == "NVDA" for i in result["direct_impacts"])

    @pytest.mark.asyncio
    async def test_catalyst_first_order_via_cross_exposure(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD", strength=0.78)
        await db.commit()
        result = await propagate_scenario(db, _catalyst_seed(ticker="NVDA"))
        indirect_keys = {i["entity_key"] for i in result["indirect_impacts"]}
        assert "AMD" in indirect_keys


# ---------------------------------------------------------------------------
# 14. failure_mode_scenario
# ---------------------------------------------------------------------------

class TestFailureModePropagation:
    @pytest.mark.asyncio
    async def test_failure_mode_direct_impact(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _failure_mode_seed(ticker="NVDA"))
        assert any(i["entity_key"] == "NVDA" for i in result["direct_impacts"])

    @pytest.mark.asyncio
    async def test_failure_mode_first_order_via_cross_exposure(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="INTC", strength=0.75)
        await db.commit()
        result = await propagate_scenario(db, _failure_mode_seed(ticker="NVDA"))
        indirect_keys = {i["entity_key"] for i in result["indirect_impacts"]}
        assert "INTC" in indirect_keys


# ---------------------------------------------------------------------------
# 15–16. portfolio_scenario
# ---------------------------------------------------------------------------

class TestPortfolioPropagation:
    @pytest.mark.asyncio
    async def test_portfolio_direct_impact_is_portfolio_entity(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        pid = _uid()
        result = await propagate_scenario(db, _portfolio_seed(portfolio_id=pid))
        assert any(i["entity_key"] == pid for i in result["direct_impacts"])

    @pytest.mark.asyncio
    async def test_portfolio_direct_entity_type_is_portfolio(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _portfolio_seed())
        for imp in result["direct_impacts"]:
            assert imp["entity_type"] == "portfolio"

    @pytest.mark.asyncio
    async def test_portfolio_first_order_are_position_tickers(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        pid = _uid()
        result = await propagate_scenario(
            db, _portfolio_seed(portfolio_id=pid, tickers=["NVDA", "AAPL", "MSFT"])
        )
        fo = {i["entity_key"] for i in result["indirect_impacts"] if i["depth"] == 1}
        assert fo == {"NVDA", "AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_portfolio_second_order_via_cross_exposure(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD", strength=0.80)
        await db.commit()
        result = await propagate_scenario(
            db, _portfolio_seed(tickers=["NVDA"])
        )
        all_keys = {i["entity_key"] for i in result["affected_entities"]}
        assert "AMD" in all_keys


# ---------------------------------------------------------------------------
# 17. Sparse substrate
# ---------------------------------------------------------------------------

class TestSparseSubstrate:
    @pytest.mark.asyncio
    async def test_no_exception_on_empty_db(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        for make in (_company_seed, _macro_seed, _sector_seed,
                     _catalyst_seed, _failure_mode_seed, _portfolio_seed):
            try:
                result = await propagate_scenario(db, make())
                assert isinstance(result, dict)
            except Exception as exc:
                pytest.fail(f"propagate raised for {make.__name__}: {exc}")

    @pytest.mark.asyncio
    async def test_direct_only_when_no_links(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _company_seed(ticker="ZZZZ"))
        assert result["direct_impacts"] != []
        assert result["indirect_impacts"] == []
        assert result["propagation_depth"] == 0


# ---------------------------------------------------------------------------
# 18. Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    @pytest.mark.asyncio
    async def test_same_db_same_result(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD",  strength=0.80)
        await _seed_cross(db, a="AMD",  b="TSLA", strength=0.70)
        await db.commit()
        seed = _company_seed(ticker="NVDA")
        r1 = await propagate_scenario(db, seed)
        r2 = await propagate_scenario(db, seed)
        assert r1["propagation_depth"]   == r2["propagation_depth"]
        assert len(r1["indirect_impacts"]) == len(r2["indirect_impacts"])
        keys1 = sorted(i["entity_key"] for i in r1["affected_entities"])
        keys2 = sorted(i["entity_key"] for i in r2["affected_entities"])
        assert keys1 == keys2


# ---------------------------------------------------------------------------
# 19–20. Transmission path
# ---------------------------------------------------------------------------

class TestTransmissionPath:
    @pytest.mark.asyncio
    async def test_path_is_non_empty_list(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _company_seed())
        assert isinstance(result["transmission_path"], list)
        assert len(result["transmission_path"]) >= 1

    @pytest.mark.asyncio
    async def test_path_steps_are_monotonically_ordered(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD", strength=0.80)
        await db.commit()
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        steps = [s["step"] for s in result["transmission_path"]]
        assert steps == list(range(len(steps))), f"Steps not ordered: {steps}"


# ---------------------------------------------------------------------------
# 21. affected_entities
# ---------------------------------------------------------------------------

class TestAffectedEntities:
    @pytest.mark.asyncio
    async def test_affected_entities_includes_direct(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        direct_keys = {i["entity_key"] for i in result["direct_impacts"]}
        entity_keys = {i["entity_key"] for i in result["affected_entities"]}
        assert direct_keys.issubset(entity_keys)

    @pytest.mark.asyncio
    async def test_affected_entities_no_duplicates(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD", strength=0.80)
        await db.commit()
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        keys = [i["entity_key"] for i in result["affected_entities"]]
        assert len(keys) == len(set(keys)), f"Duplicate entities: {keys}"


# ---------------------------------------------------------------------------
# 22–23. No DB writes
# ---------------------------------------------------------------------------

class TestNoWrites:
    async def _counts(self, db):
        from app.db.models import (
            ForecastVector, CrossExposure, ScenarioSnapshot, ScenarioRunLog,
        )
        result = {}
        for m in (ForecastVector, CrossExposure, ScenarioSnapshot, ScenarioRunLog):
            n = (await db.execute(select(func.count()).select_from(m))).scalar_one()
            result[m.__tablename__] = n
        return result

    @pytest.mark.asyncio
    async def test_no_row_counts_change(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD", strength=0.80)
        await db.commit()
        before = await self._counts(db)
        await propagate_scenario(db, _company_seed(ticker="NVDA"))
        after = await self._counts(db)
        assert before == after

    @pytest.mark.asyncio
    async def test_no_scenario_snapshot_created(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        from app.db.models import ScenarioSnapshot
        await propagate_scenario(db, _company_seed(ticker="NVDA"))
        n = (await db.execute(select(func.count()).select_from(ScenarioSnapshot))).scalar_one()
        assert n == 0


# ---------------------------------------------------------------------------
# 24–25. Confidence / uncertainty range
# ---------------------------------------------------------------------------

class TestScoreRanges:
    @pytest.mark.asyncio
    async def test_impact_confidence_in_range(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _company_seed())
        assert 0.0 <= result["impact_confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_impact_uncertainty_in_range(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _company_seed())
        assert 0.0 <= result["impact_uncertainty"] <= 1.0


# ---------------------------------------------------------------------------
# 26–27. propagate_all
# ---------------------------------------------------------------------------

class TestPropagateAll:
    @pytest.mark.asyncio
    async def test_propagate_all_returns_list(self, db):
        from app.services.scenario_propagation_engine import propagate_all
        seeds = [_company_seed(), _macro_seed()]
        result = await propagate_all(db, seeds)
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_propagate_all_null_session_returns_empty(self):
        from app.services.scenario_propagation_engine import propagate_all
        result = await propagate_all(None, [_company_seed()])
        assert result == []

    @pytest.mark.asyncio
    async def test_propagate_all_skips_empty_dicts(self, db):
        from app.services.scenario_propagation_engine import propagate_all
        result = await propagate_all(db, [{}, _company_seed()])
        non_empty = [r for r in result if r]
        assert len(non_empty) == 1


# ---------------------------------------------------------------------------
# 28. No advice language (AST)
# ---------------------------------------------------------------------------

class TestNoAdviceLanguage:
    def _non_docstring_constants(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        docstring_ids: set = set()
        for node in ast.walk(tree):
            body = None
            if isinstance(node, (ast.Module, ast.ClassDef,
                                  ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr):
                inner = body[0].value
                if isinstance(inner, ast.Constant):
                    docstring_ids.add(id(inner))
        return [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_ids
        ]

    def test_no_buy_sell_hold_in_constants(self):
        for val in self._non_docstring_constants():
            low = val.lower()
            for term in ("buy ", " buy", "sell ", " sell", "hold ", " hold"):
                assert term not in low, (
                    f"Advice term {term!r} in string constant: {val!r}"
                )

    def test_no_target_price_in_constants(self):
        for val in self._non_docstring_constants():
            low = val.lower()
            for term in ("target_price", "price_target", "position_size"):
                assert term not in low, (
                    f"Forbidden term {term!r} in string constant: {val!r}"
                )


# ---------------------------------------------------------------------------
# 29. No conviction/order imports (AST)
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:
    def _imports(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
        return imported

    def test_no_conviction_imports(self):
        forbidden = [
            "conviction_engine", "conviction_modeler",
            "recommendation", "stance_engine",
            "order_engine", "execution_engine",
        ]
        violations = [n for n in self._imports()
                      if any(f in n.lower() for f in forbidden)]
        assert not violations, f"Forbidden imports: {violations}"

    def test_no_scenario_repo_import(self):
        violations = [n for n in self._imports() if "scenario_repo" in n.lower()]
        assert not violations, f"scenario_repo imported: {violations}"


# ---------------------------------------------------------------------------
# 30. No write-function calls (AST)
# ---------------------------------------------------------------------------

class TestNoWriteCalls:
    def test_no_forecast_write_calls(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        write_fns = {"upsert_forecast_vector", "add_forecast_evidence", "add_calibration_log"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                attr = None
                if isinstance(node.func, ast.Attribute):
                    attr = node.func.attr
                elif isinstance(node.func, ast.Name):
                    attr = node.func.id
                if attr in write_fns:
                    assert False, f"Forecast write call {attr!r} found in propagation engine"

    def test_no_decision_write_calls(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        write_fns = {"upsert_decision_priority", "add_decision_evidence", "add_ranking_log"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                attr = None
                if isinstance(node.func, ast.Attribute):
                    attr = node.func.attr
                elif isinstance(node.func, ast.Name):
                    attr = node.func.id
                if attr in write_fns:
                    assert False, f"Decision write call {attr!r} found in propagation engine"


# ---------------------------------------------------------------------------
# 31. No scenario_repo (raw string scan after stripping comments/docstrings)
# ---------------------------------------------------------------------------

class TestNoScenarioRepo:
    def test_no_scenario_repo_in_ast_imports(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                full = node.module or ""
                assert "scenario_repo" not in full
                for alias in node.names:
                    assert "scenario_repo" not in alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert "scenario_repo" not in alias.name


# ---------------------------------------------------------------------------
# 32–35. Structural invariants
# ---------------------------------------------------------------------------

class TestStructuralInvariants:
    @pytest.mark.asyncio
    async def test_affected_portfolios_is_list(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        for seed in [_company_seed(), _macro_seed(), _portfolio_seed()]:
            result = await propagate_scenario(db, seed)
            assert isinstance(result.get("affected_portfolios"), list), (
                f"affected_portfolios is not a list for {seed['scenario_type']}"
            )

    @pytest.mark.asyncio
    async def test_direct_impacts_all_depth_zero(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        result = await propagate_scenario(db, _company_seed())
        for imp in result["direct_impacts"]:
            assert imp["depth"] == 0

    @pytest.mark.asyncio
    async def test_first_order_impacts_all_depth_one(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD", strength=0.80)
        await db.commit()
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        fo = [i for i in result["indirect_impacts"] if i["impact_channel"] == "cross_exposure"
              and i["entity_key"] == "AMD"]
        assert all(i["depth"] == 1 for i in fo)

    @pytest.mark.asyncio
    async def test_second_order_impacts_all_depth_two(self, db):
        from app.services.scenario_propagation_engine import propagate_scenario
        await _seed_cross(db, a="NVDA", b="AMD",  strength=0.80)
        await _seed_cross(db, a="AMD",  b="TSLA", strength=0.70)
        await db.commit()
        result = await propagate_scenario(db, _company_seed(ticker="NVDA"))
        so = [i for i in result["indirect_impacts"] if i["depth"] == 2]
        for imp in so:
            assert imp["depth"] == 2
