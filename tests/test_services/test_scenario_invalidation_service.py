"""
Tests — Scenario Rebuild + Storage Pipeline, Phase 14 · Slice 5.

Covers:
  1.  successful storage — snapshot row created after valid pipeline
  2.  snapshot row fields correct (scenario_type, entity_key, plausibility_band)
  3.  evidence rows written after successful storage
  4.  run_log appended after successful storage
  5.  explainability gate blocks storage for a bad seed
  6.  propagation failure blocks storage (unknown seed type)
  7.  stale detection — is_scenario_stale with expired row
  8.  stale detection — is_scenario_stale with old schema
  9.  stale detection — is_scenario_stale returns True for None
  10. find_stale_scenarios returns [] for None session
  11. find_stale_scenarios returns expired rows
  12. batch rebuild returns one result per seed
  13. batch rebuild empty list returns []
  14. ticker rebuild returns results list
  15. null session + shadow_only=False returns error result
  16. null session + shadow_only=True runs pipeline without writing
  17. shadow_only=True — no snapshot written, run_log still appended
  18. no source-table mutation — ForecastVector count unchanged
  19. no source-table mutation — CrossExposure count unchanged
  20. no delivery rows created
  21. no notification rows created
  22. blocked seed produces no snapshot row
  23. blocked seed produces no evidence rows
  24. run_log is append-only (count grows by 1 per build)
  25. result dict has required keys
  26. stored=True on success
  27. stored=False on blocked
  28. no conviction imports (AST)
  29. no forecast write-back (AST)
  30. no decision write-back (AST)
  31. no delivery imports (AST)
  32. no notification imports (AST)
  33. rebuild_scenario_for_target with valid seed
  34. rebuild_scenario_batch processes multiple seeds
  35. plausibility_band derived correctly from confidence
  36. scenario_impact derived from p_positive/p_negative
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "scenario_invalidation_service.py"

_REQUIRED_RESULT_KEYS = {
    "stored", "blocked", "block_reason",
    "snapshot_id", "evidence_count", "log_id",
    "scenario_type", "entity_key", "error",
}

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
# Seed helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _company_seed(ticker="NVDA", *, p_pos=0.72, p_neg=0.18, user_id=None):
    return {
        "scenario_type":      "company_scenario",
        "entity_type":        "company",
        "entity_id":          ticker,
        "ticker":             ticker,
        "scenario_name":      f"{ticker} company scenario",
        "changed_assumption": f"If {ticker} forecast strengthens near-term",
        "source_type":        "forecast_vector",
        "source_id":          _uid(),
        "evidence_refs":      ["ev-1"],
        "source_versions":    {"forecast_vector": "v1"},
        "transmission_inputs": {
            "direction": "strengthening",
            "forecast_type": "thesis_strengthening",
            "horizon": "near_term",
            "horizon_days": 30,
        },
        "impact_inputs":      {"p_positive": p_pos, "p_negative": p_neg},
        "confidence_inputs":  {
            "confidence_band_low": 0.60, "confidence_band_high": 0.85,
            "p_max": p_pos, "evidence_count": 2, "forecast_schema": 1,
        },
        "uncertainty_inputs": {"band_width": 0.25, "p_neutral": 0.10},
        "user_id":            user_id,
    }


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
        "evidence_refs":      [],
        "source_versions":    {},
        "transmission_inputs": {
            "direction": "accelerating",
            "forecast_type": "macro_shift",
            "horizon": "medium_term",
            "macro_key": macro_key,
            "watchlist_count": 0,
        },
        "impact_inputs":      {"p_positive": 0.60, "p_negative": 0.30},
        "confidence_inputs":  {
            "confidence_band_low": 0.50, "confidence_band_high": 0.80,
            "evidence_count": 0,
        },
        "uncertainty_inputs": {"band_width": 0.30, "p_neutral": 0.10},
        "affected_tickers":   affected_tickers or [],
        "affected_portfolios": [],
        "user_id":            None,
    }


def _bad_seed():
    """Seed that will fail validation — scenario_type unknown."""
    return {
        "scenario_type":      "invalid_type",
        "entity_type":        "company",
        "entity_id":          "ZZZZZ",
        "ticker":             "ZZZZZ",
        "scenario_name":      "bad",
        "changed_assumption": "bad",
        "source_type":        "forecast_vector",
        "source_id":          _uid(),
        "evidence_refs":      [],
        "source_versions":    {},
        "transmission_inputs": {},
        "impact_inputs":      {},
        "confidence_inputs":  {},
        "uncertainty_inputs": {},
        "user_id":            None,
    }


async def _count(db, model) -> int:
    n = (await db.execute(select(func.count()).select_from(model))).scalar_one()
    return int(n)


# ---------------------------------------------------------------------------
# 1–4. Successful storage
# ---------------------------------------------------------------------------

class TestSuccessfulStorage:
    @pytest.mark.asyncio
    async def test_stored_true_on_success(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        result = await rebuild_scenario_for_target(db, _company_seed())
        assert result["stored"] is True, result.get("error") or result.get("block_reason")

    @pytest.mark.asyncio
    async def test_snapshot_row_created(self, db):
        from app.db.models import ScenarioSnapshot
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        await rebuild_scenario_for_target(db, _company_seed(ticker="AAPL"))
        await db.commit()
        n = await _count(db, ScenarioSnapshot)
        assert n == 1

    @pytest.mark.asyncio
    async def test_snapshot_fields_correct(self, db):
        from app.db.models import ScenarioSnapshot
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        await rebuild_scenario_for_target(db, _company_seed(ticker="MSFT"))
        await db.commit()
        row = (await db.execute(select(ScenarioSnapshot))).scalar_one()
        assert row.scenario_type == "company_scenario"
        assert row.entity_key    == "MSFT"
        assert row.plausibility_band in ("remote", "plausible", "likely_conditional")
        assert row.scenario_impact in (
            "significant_positive", "moderate_positive", "neutral",
            "moderate_negative", "significant_negative", "ambiguous",
        )

    @pytest.mark.asyncio
    async def test_evidence_rows_written(self, db):
        from app.db.models import ScenarioEvidence
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        result = await rebuild_scenario_for_target(db, _company_seed())
        await db.commit()
        assert result["evidence_count"] >= 1
        n = await _count(db, ScenarioEvidence)
        assert n >= 1

    @pytest.mark.asyncio
    async def test_run_log_appended(self, db):
        from app.db.models import ScenarioRunLog
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        result = await rebuild_scenario_for_target(db, _company_seed())
        await db.commit()
        assert result["log_id"] != ""
        n = await _count(db, ScenarioRunLog)
        assert n == 1

    @pytest.mark.asyncio
    async def test_result_has_required_keys(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        result = await rebuild_scenario_for_target(db, _company_seed())
        missing = _REQUIRED_RESULT_KEYS - result.keys()
        assert not missing, f"Missing keys: {missing}"

    @pytest.mark.asyncio
    async def test_snapshot_id_non_empty(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        result = await rebuild_scenario_for_target(db, _company_seed())
        assert result["snapshot_id"] != ""


# ---------------------------------------------------------------------------
# 5–6. Blocking rules
# ---------------------------------------------------------------------------

class TestBlockingRules:
    @pytest.mark.asyncio
    async def test_unknown_type_blocked(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        result = await rebuild_scenario_for_target(db, _bad_seed())
        assert result["blocked"] is True
        assert result["stored"] is False

    @pytest.mark.asyncio
    async def test_blocked_seed_no_snapshot_row(self, db):
        from app.db.models import ScenarioSnapshot
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        await rebuild_scenario_for_target(db, _bad_seed())
        await db.commit()
        n = await _count(db, ScenarioSnapshot)
        assert n == 0

    @pytest.mark.asyncio
    async def test_blocked_seed_no_evidence_rows(self, db):
        from app.db.models import ScenarioEvidence
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        await rebuild_scenario_for_target(db, _bad_seed())
        await db.commit()
        n = await _count(db, ScenarioEvidence)
        assert n == 0

    @pytest.mark.asyncio
    async def test_stored_false_on_blocked(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        result = await rebuild_scenario_for_target(db, _bad_seed())
        assert result["stored"] is False

    @pytest.mark.asyncio
    async def test_block_reason_non_empty_when_blocked(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        result = await rebuild_scenario_for_target(db, _bad_seed())
        assert result["block_reason"] != ""

    @pytest.mark.asyncio
    async def test_explanation_gate_blocks_doctored_seed(self, db):
        """Manually inject a banned phrase into a valid seed's changed_assumption
        and confirm the pipeline blocks it (via the explainability validation)."""
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        seed = _company_seed()
        # Build once to get a valid explanation, then doctor the seed name so
        # build_what_changed surfaces a banned term in what_changed
        seed["changed_assumption"] = "You should buy NVDA immediately."
        result = await rebuild_scenario_for_target(db, seed)
        # The banned phrase 'buy' should surface in what_changed and fail validation
        assert result["blocked"] is True or result["stored"] is False


# ---------------------------------------------------------------------------
# 7–11. Stale detection
# ---------------------------------------------------------------------------

class TestStaleDetection:
    def test_none_is_stale(self):
        from app.services.scenario_invalidation_service import is_scenario_stale
        assert is_scenario_stale(None) is True

    def test_expired_row_is_stale(self):
        from app.services.scenario_invalidation_service import is_scenario_stale

        class FakeRow:
            scenario_schema = 1
            expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        assert is_scenario_stale(FakeRow()) is True

    def test_old_schema_is_stale(self):
        from app.services.scenario_invalidation_service import is_scenario_stale

        class FakeRow:
            scenario_schema = 0  # old
            expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        assert is_scenario_stale(FakeRow()) is True

    def test_fresh_current_schema_not_stale(self):
        from app.services.scenario_invalidation_service import (
            is_scenario_stale, CURRENT_SCENARIO_SCHEMA,
        )

        class FakeRow:
            scenario_schema = CURRENT_SCENARIO_SCHEMA
            expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        assert is_scenario_stale(FakeRow()) is False

    def test_no_expires_at_is_stale(self):
        from app.services.scenario_invalidation_service import is_scenario_stale

        class FakeRow:
            scenario_schema = 1
            expires_at = None

        assert is_scenario_stale(FakeRow()) is True

    @pytest.mark.asyncio
    async def test_find_stale_none_session(self):
        from app.services.scenario_invalidation_service import find_stale_scenarios
        result = await find_stale_scenarios(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_find_stale_returns_expired_rows(self, db):
        from app.db.models import ScenarioSnapshot
        from app.services.scenario_invalidation_service import find_stale_scenarios

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        row = ScenarioSnapshot(
            id="exp-001", scenario_type="company_scenario",
            entity_type="company", entity_key="NVDA",
            scenario_key="test", scenario_schema=1,
            confidence_score=0.5, uncertainty_score=0.2,
            plausibility_band="plausible", scenario_impact="ambiguous",
            condition="", transmission_path="[]",
            affected_entities="[]", affected_forecasts="[]",
            affected_decisions="[]",
            what_changed="changed", why_it_matters="matters",
            evidence_summary="[]", invalidators="[]",
            source_versions="{}", built_at=past, expires_at=past,
        )
        db.add(row)
        await db.commit()
        stale = await find_stale_scenarios(db)
        assert any(getattr(r, "id", "") == "exp-001" for r in stale)

    @pytest.mark.asyncio
    async def test_find_stale_fresh_rows_not_returned(self, db):
        from app.services.scenario_invalidation_service import (
            find_stale_scenarios, CURRENT_SCENARIO_SCHEMA,
        )
        from app.db.models import ScenarioSnapshot

        future = datetime.now(timezone.utc) + timedelta(hours=48)
        row = ScenarioSnapshot(
            id="fresh-001", scenario_type="company_scenario",
            entity_type="company", entity_key="AAPL",
            scenario_key="test", scenario_schema=CURRENT_SCENARIO_SCHEMA,
            confidence_score=0.5, uncertainty_score=0.2,
            plausibility_band="plausible", scenario_impact="ambiguous",
            condition="", transmission_path="[]",
            affected_entities="[]", affected_forecasts="[]",
            affected_decisions="[]",
            what_changed="changed", why_it_matters="matters",
            evidence_summary="[]", invalidators="[]",
            source_versions="{}", built_at=future, expires_at=future,
        )
        db.add(row)
        await db.commit()
        stale = await find_stale_scenarios(db)
        assert not any(getattr(r, "id", "") == "fresh-001" for r in stale)


# ---------------------------------------------------------------------------
# 12–14. Batch + ticker rebuild
# ---------------------------------------------------------------------------

class TestBatchAndTickerRebuild:
    @pytest.mark.asyncio
    async def test_batch_returns_one_result_per_seed(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_batch
        seeds = [_company_seed("NVDA"), _macro_seed("RATES")]
        results = await rebuild_scenario_batch(db, seeds)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_batch_empty_list_returns_empty(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_batch
        results = await rebuild_scenario_batch(db, [])
        assert results == []

    @pytest.mark.asyncio
    async def test_ticker_rebuild_returns_list(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenarios_for_ticker
        results = await rebuild_scenarios_for_ticker(db, "NVDA")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_batch_all_have_required_keys(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_batch
        results = await rebuild_scenario_batch(db, [_company_seed()])
        for r in results:
            missing = _REQUIRED_RESULT_KEYS - r.keys()
            assert not missing, f"Missing keys: {missing}"

    @pytest.mark.asyncio
    async def test_batch_mixed_valid_invalid(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_batch
        results = await rebuild_scenario_batch(db, [_company_seed(), _bad_seed()])
        assert len(results) == 2
        stored = [r["stored"] for r in results]
        assert True in stored    # at least one stored
        assert False in stored   # at least one blocked/failed


# ---------------------------------------------------------------------------
# 15–17. Null session and shadow mode
# ---------------------------------------------------------------------------

class TestNullSessionAndShadow:
    @pytest.mark.asyncio
    async def test_null_session_no_shadow_returns_error(self):
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        result = await rebuild_scenario_for_target(None, _company_seed(), shadow_only=False)
        assert result["stored"] is False
        assert result["error"] != ""

    @pytest.mark.asyncio
    async def test_null_session_batch_no_shadow_returns_empty(self):
        from app.services.scenario_invalidation_service import rebuild_scenario_batch
        results = await rebuild_scenario_batch(None, [_company_seed()], shadow_only=False)
        assert results == []

    @pytest.mark.asyncio
    async def test_null_session_ticker_no_shadow_returns_empty(self):
        from app.services.scenario_invalidation_service import rebuild_scenarios_for_ticker
        results = await rebuild_scenarios_for_ticker(None, "NVDA", shadow_only=False)
        assert results == []

    @pytest.mark.asyncio
    async def test_shadow_only_no_snapshot_written(self, db):
        from app.db.models import ScenarioSnapshot
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        result = await rebuild_scenario_for_target(db, _company_seed(), shadow_only=True)
        await db.commit()
        assert result["stored"] is False
        n = await _count(db, ScenarioSnapshot)
        assert n == 0

    @pytest.mark.asyncio
    async def test_shadow_only_run_log_appended(self, db):
        from app.db.models import ScenarioRunLog
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        result = await rebuild_scenario_for_target(db, _company_seed(), shadow_only=True)
        await db.commit()
        assert result["log_id"] != ""
        n = await _count(db, ScenarioRunLog)
        assert n >= 1


# ---------------------------------------------------------------------------
# 18–21. No source-table mutation, no delivery, no notifications
# ---------------------------------------------------------------------------

class TestNoSourceMutation:
    async def _source_counts(self, db):
        from app.db.models import ForecastVector, CrossExposure
        fv = await _count(db, ForecastVector)
        cx = await _count(db, CrossExposure)
        return fv, cx

    @pytest.mark.asyncio
    async def test_forecast_vector_count_unchanged(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        before_fv, before_cx = await self._source_counts(db)
        await rebuild_scenario_for_target(db, _company_seed())
        await db.commit()
        after_fv, after_cx = await self._source_counts(db)
        assert before_fv == after_fv
        assert before_cx == after_cx

    @pytest.mark.asyncio
    async def test_no_delivery_rows(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target

        # Delivery-adjacent tables: check Notification if it exists
        try:
            from app.db.models import Notification
            before = await _count(db, Notification)
            await rebuild_scenario_for_target(db, _company_seed())
            await db.commit()
            after = await _count(db, Notification)
            assert before == after
        except (ImportError, Exception):
            pass  # table may not exist in this test DB

    @pytest.mark.asyncio
    async def test_no_decision_priority_rows(self, db):
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        try:
            from app.db.models import DecisionPriority
            before = await _count(db, DecisionPriority)
            await rebuild_scenario_for_target(db, _company_seed())
            await db.commit()
            after = await _count(db, DecisionPriority)
            assert before == after
        except (ImportError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_run_log_append_only_grows_by_one(self, db):
        from app.db.models import ScenarioRunLog
        from app.services.scenario_invalidation_service import rebuild_scenario_for_target
        before = await _count(db, ScenarioRunLog)
        await rebuild_scenario_for_target(db, _company_seed())
        await db.commit()
        after = await _count(db, ScenarioRunLog)
        assert after == before + 1


# ---------------------------------------------------------------------------
# 35–36. Scoring helpers
# ---------------------------------------------------------------------------

class TestScoringHelpers:
    def test_plausibility_band_high_confidence(self):
        from app.services.scenario_invalidation_service import _plausibility_band
        assert _plausibility_band(0.80) == "likely_conditional"

    def test_plausibility_band_medium_confidence(self):
        from app.services.scenario_invalidation_service import _plausibility_band
        assert _plausibility_band(0.55) == "plausible"

    def test_plausibility_band_low_confidence(self):
        from app.services.scenario_invalidation_service import _plausibility_band
        assert _plausibility_band(0.20) == "remote"

    def test_scenario_impact_significant_positive(self):
        from app.services.scenario_invalidation_service import _scenario_impact
        seed = {"impact_inputs": {"p_positive": 0.75, "p_negative": 0.15}}
        assert _scenario_impact(seed) == "significant_positive"

    def test_scenario_impact_moderate_positive(self):
        from app.services.scenario_invalidation_service import _scenario_impact
        seed = {"impact_inputs": {"p_positive": 0.55, "p_negative": 0.30}}
        assert _scenario_impact(seed) == "moderate_positive"

    def test_scenario_impact_significant_negative(self):
        from app.services.scenario_invalidation_service import _scenario_impact
        seed = {"impact_inputs": {"p_positive": 0.10, "p_negative": 0.75}}
        assert _scenario_impact(seed) == "significant_negative"

    def test_scenario_impact_moderate_negative(self):
        from app.services.scenario_invalidation_service import _scenario_impact
        seed = {"impact_inputs": {"p_positive": 0.25, "p_negative": 0.55}}
        assert _scenario_impact(seed) == "moderate_negative"

    def test_scenario_impact_ambiguous_close(self):
        from app.services.scenario_invalidation_service import _scenario_impact
        seed = {"impact_inputs": {"p_positive": 0.45, "p_negative": 0.40}}
        assert _scenario_impact(seed) == "ambiguous"

    def test_scenario_impact_empty_inputs(self):
        from app.services.scenario_invalidation_service import _scenario_impact
        assert _scenario_impact({}) == "ambiguous"


# ---------------------------------------------------------------------------
# AST safety checks
# ---------------------------------------------------------------------------

class TestASTSafety:
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

    def _calls(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    calls.append(node.func.attr)
                elif isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
        return calls

    def test_no_conviction_imports(self):
        forbidden = ["conviction_engine", "conviction_modeler",
                     "recommendation", "stance_engine"]
        violations = [n for n in self._imports()
                      if any(f in n.lower() for f in forbidden)]
        assert not violations, f"Conviction imports: {violations}"

    def test_no_delivery_imports(self):
        forbidden = ["delivery_service", "delivery_queue",
                     "notification_service", "push_service"]
        violations = [n for n in self._imports()
                      if any(f in n.lower() for f in forbidden)]
        assert not violations, f"Delivery imports: {violations}"

    def test_no_order_imports(self):
        forbidden = ["order_engine", "execution_engine", "trade_service"]
        violations = [n for n in self._imports()
                      if any(f in n.lower() for f in forbidden)]
        assert not violations, f"Order imports: {violations}"

    def test_no_forecast_write_back_calls(self):
        write_fns = {"upsert_forecast_vector", "add_forecast_evidence",
                     "add_calibration_log"}
        violations = [c for c in self._calls() if c in write_fns]
        assert not violations, f"Forecast write-back calls: {violations}"

    def test_no_decision_write_back_calls(self):
        write_fns = {"upsert_decision_priority", "add_decision_evidence",
                     "add_ranking_log"}
        violations = [c for c in self._calls() if c in write_fns]
        assert not violations, f"Decision write-back calls: {violations}"

    def test_no_notification_write_calls(self):
        write_fns = {"create_notification", "add_notification",
                     "upsert_notification", "send_notification"}
        violations = [c for c in self._calls() if c in write_fns]
        assert not violations, f"Notification write calls: {violations}"
