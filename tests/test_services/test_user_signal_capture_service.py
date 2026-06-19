"""
Tests — User Signal Capture Service, Phase 15 · Slice 3.

Covers:
  1.  service importable
  2.  flag gate: all functions return None when learning_capture_enabled=False
  3.  null-session safety: all functions return None when session is None
      (even when flag is True)
  4.  capture_search_signal: polarity mapping (click→positive, query→neutral)
  5.  capture_analysis_signal: always positive
  6.  capture_forecast_interaction: always positive
  7.  capture_scenario_interaction: polarity mapping
      (expand→positive, dismiss→negative, other→neutral)
  8.  capture_watchlist_interaction: polarity mapping
      (add→positive, remove→negative)
  9.  capture_portfolio_interaction: always positive
  10. capture_alert_interaction: polarity mapping
      (open/act→positive, dismiss/mute→negative)
  11. event persistence: rows appear in user_signal_event after capture
  12. surface_was_personalized propagated to stored row
  13. pre_personalization_rank propagated to stored row
  14. tenant isolation: user A events not visible to user B query
  15. no preference creation: learned_preference count unchanged after capture
  16. no relevance adjustment creation: relevance_adjustment_log count unchanged
  17. no truth-table mutation during capture operations
  18. AST safety: service imports no truth-write repository functions
  19. AST safety: no buy/sell/advice language in non-docstring string constants
  20. multiple events: each capture call creates an independent row
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Engine / session fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture()
async def db(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncSessionLocal() as session:
        yield session


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. Service importable
# ---------------------------------------------------------------------------

class TestImport:
    def test_service_importable(self):
        import app.services.user_signal_capture_service  # noqa: F401

    def test_all_capture_functions_importable(self):
        from app.services.user_signal_capture_service import (
            capture_search_signal,
            capture_analysis_signal,
            capture_forecast_interaction,
            capture_scenario_interaction,
            capture_watchlist_interaction,
            capture_portfolio_interaction,
            capture_alert_interaction,
        )
        for fn in (
            capture_search_signal, capture_analysis_signal,
            capture_forecast_interaction, capture_scenario_interaction,
            capture_watchlist_interaction, capture_portfolio_interaction,
            capture_alert_interaction,
        ):
            assert callable(fn)


# ---------------------------------------------------------------------------
# 2. Flag gate: all functions return None when capture disabled
# ---------------------------------------------------------------------------

class TestFlagGate:
    """All capture functions must return None when run_override=False."""

    @pytest.mark.asyncio
    async def test_search_disabled(self, db):
        from app.services.user_signal_capture_service import capture_search_signal
        result = await capture_search_signal(
            db, user_id=_uid(), signal_type="search_click",
            entity_key="NVDA", run_override=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_analysis_disabled(self, db):
        from app.services.user_signal_capture_service import capture_analysis_signal
        result = await capture_analysis_signal(
            db, user_id=_uid(), signal_type="analysis_open", run_override=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_forecast_disabled(self, db):
        from app.services.user_signal_capture_service import capture_forecast_interaction
        result = await capture_forecast_interaction(
            db, user_id=_uid(), signal_type="forecast_view", run_override=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_scenario_disabled(self, db):
        from app.services.user_signal_capture_service import capture_scenario_interaction
        result = await capture_scenario_interaction(
            db, user_id=_uid(), signal_type="scenario_expand", run_override=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_watchlist_disabled(self, db):
        from app.services.user_signal_capture_service import capture_watchlist_interaction
        result = await capture_watchlist_interaction(
            db, user_id=_uid(), signal_type="watchlist_add", run_override=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_portfolio_disabled(self, db):
        from app.services.user_signal_capture_service import capture_portfolio_interaction
        result = await capture_portfolio_interaction(
            db, user_id=_uid(), run_override=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_alert_disabled(self, db):
        from app.services.user_signal_capture_service import capture_alert_interaction
        result = await capture_alert_interaction(
            db, user_id=_uid(), signal_type="alert_open", run_override=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_disabled_produces_no_db_row(self, db):
        from app.services.user_signal_capture_service import capture_analysis_signal
        from app.db.repositories.user_learning_repo import count_user_signal_events
        uid = _uid()
        await capture_analysis_signal(
            db, user_id=uid, signal_type="analysis_open",
            entity_key="NVDA", run_override=False,
        )
        await db.commit()
        n = await count_user_signal_events(db, user_id=uid)
        assert n == 0, "Disabled capture must not write any event row"


# ---------------------------------------------------------------------------
# 3. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_search_null_session(self):
        from app.services.user_signal_capture_service import capture_search_signal
        result = await capture_search_signal(
            None, user_id=_uid(), signal_type="search_click", run_override=True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_analysis_null_session(self):
        from app.services.user_signal_capture_service import capture_analysis_signal
        result = await capture_analysis_signal(
            None, user_id=_uid(), signal_type="analysis_open", run_override=True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_forecast_null_session(self):
        from app.services.user_signal_capture_service import capture_forecast_interaction
        assert await capture_forecast_interaction(
            None, user_id=_uid(), signal_type="forecast_view", run_override=True,
        ) is None

    @pytest.mark.asyncio
    async def test_scenario_null_session(self):
        from app.services.user_signal_capture_service import capture_scenario_interaction
        assert await capture_scenario_interaction(
            None, user_id=_uid(), signal_type="scenario_expand", run_override=True,
        ) is None

    @pytest.mark.asyncio
    async def test_watchlist_null_session(self):
        from app.services.user_signal_capture_service import capture_watchlist_interaction
        assert await capture_watchlist_interaction(
            None, user_id=_uid(), signal_type="watchlist_add", run_override=True,
        ) is None

    @pytest.mark.asyncio
    async def test_portfolio_null_session(self):
        from app.services.user_signal_capture_service import capture_portfolio_interaction
        assert await capture_portfolio_interaction(
            None, user_id=_uid(), run_override=True,
        ) is None

    @pytest.mark.asyncio
    async def test_alert_null_session(self):
        from app.services.user_signal_capture_service import capture_alert_interaction
        assert await capture_alert_interaction(
            None, user_id=_uid(), signal_type="alert_open", run_override=True,
        ) is None


# ---------------------------------------------------------------------------
# 4. capture_search_signal: polarity mapping
# ---------------------------------------------------------------------------

class TestSearchSignalPolarity:
    @pytest.mark.asyncio
    async def test_search_click_is_positive(self, db):
        from app.services.user_signal_capture_service import capture_search_signal
        row = await capture_search_signal(
            db, user_id=_uid(), signal_type="search_click",
            entity_key="NVDA", run_override=True,
        )
        await db.commit()
        assert row is not None
        assert row.polarity == "positive"

    @pytest.mark.asyncio
    async def test_search_query_is_neutral(self, db):
        from app.services.user_signal_capture_service import capture_search_signal
        row = await capture_search_signal(
            db, user_id=_uid(), signal_type="search_query",
            entity_key="NVDA", run_override=True,
        )
        await db.commit()
        assert row is not None
        assert row.polarity == "neutral"


# ---------------------------------------------------------------------------
# 5. capture_analysis_signal: always positive
# ---------------------------------------------------------------------------

class TestAnalysisSignal:
    @pytest.mark.asyncio
    async def test_analysis_open_is_positive(self, db):
        from app.services.user_signal_capture_service import capture_analysis_signal
        row = await capture_analysis_signal(
            db, user_id=_uid(), signal_type="analysis_open",
            entity_type="company", entity_key="AAPL", run_override=True,
        )
        await db.commit()
        assert row is not None
        assert row.polarity == "positive"
        assert row.signal_type == "analysis_open"

    @pytest.mark.asyncio
    async def test_section_expand_is_positive(self, db):
        from app.services.user_signal_capture_service import capture_analysis_signal
        row = await capture_analysis_signal(
            db, user_id=_uid(), signal_type="section_expand", run_override=True,
        )
        await db.commit()
        assert row.polarity == "positive"


# ---------------------------------------------------------------------------
# 6. capture_forecast_interaction: always positive
# ---------------------------------------------------------------------------

class TestForecastInteraction:
    @pytest.mark.asyncio
    async def test_forecast_view_is_positive(self, db):
        from app.services.user_signal_capture_service import capture_forecast_interaction
        row = await capture_forecast_interaction(
            db, user_id=_uid(), signal_type="forecast_view",
            entity_type="company", entity_key="MSFT", run_override=True,
        )
        await db.commit()
        assert row is not None
        assert row.polarity == "positive"
        assert row.source_surface == "forecast"

    @pytest.mark.asyncio
    async def test_horizon_toggle_is_positive(self, db):
        from app.services.user_signal_capture_service import capture_forecast_interaction
        row = await capture_forecast_interaction(
            db, user_id=_uid(), signal_type="horizon_toggle",
            entity_type="horizon", entity_key="long", run_override=True,
        )
        await db.commit()
        assert row.polarity == "positive"


# ---------------------------------------------------------------------------
# 7. capture_scenario_interaction: polarity mapping
# ---------------------------------------------------------------------------

class TestScenarioInteractionPolarity:
    @pytest.mark.asyncio
    async def test_scenario_expand_is_positive(self, db):
        from app.services.user_signal_capture_service import capture_scenario_interaction
        row = await capture_scenario_interaction(
            db, user_id=_uid(), signal_type="scenario_expand", run_override=True,
        )
        await db.commit()
        assert row.polarity == "positive"

    @pytest.mark.asyncio
    async def test_scenario_dismiss_is_negative(self, db):
        from app.services.user_signal_capture_service import capture_scenario_interaction
        row = await capture_scenario_interaction(
            db, user_id=_uid(), signal_type="scenario_dismiss", run_override=True,
        )
        await db.commit()
        assert row.polarity == "negative"

    @pytest.mark.asyncio
    async def test_unknown_scenario_signal_is_neutral(self, db):
        from app.services.user_signal_capture_service import capture_scenario_interaction
        row = await capture_scenario_interaction(
            db, user_id=_uid(), signal_type="scenario_hover", run_override=True,
        )
        await db.commit()
        assert row.polarity == "neutral"


# ---------------------------------------------------------------------------
# 8. capture_watchlist_interaction: polarity mapping
# ---------------------------------------------------------------------------

class TestWatchlistInteractionPolarity:
    @pytest.mark.asyncio
    async def test_watchlist_add_is_positive(self, db):
        from app.services.user_signal_capture_service import capture_watchlist_interaction
        row = await capture_watchlist_interaction(
            db, user_id=_uid(), signal_type="watchlist_add",
            entity_key="TSLA", run_override=True,
        )
        await db.commit()
        assert row.polarity == "positive"

    @pytest.mark.asyncio
    async def test_watchlist_remove_is_negative(self, db):
        from app.services.user_signal_capture_service import capture_watchlist_interaction
        row = await capture_watchlist_interaction(
            db, user_id=_uid(), signal_type="watchlist_remove",
            entity_key="TSLA", run_override=True,
        )
        await db.commit()
        assert row.polarity == "negative"

    @pytest.mark.asyncio
    async def test_unknown_watchlist_signal_is_neutral(self, db):
        from app.services.user_signal_capture_service import capture_watchlist_interaction
        row = await capture_watchlist_interaction(
            db, user_id=_uid(), signal_type="watchlist_reorder", run_override=True,
        )
        await db.commit()
        assert row.polarity == "neutral"


# ---------------------------------------------------------------------------
# 9. capture_portfolio_interaction: always positive
# ---------------------------------------------------------------------------

class TestPortfolioInteraction:
    @pytest.mark.asyncio
    async def test_portfolio_view_is_positive(self, db):
        from app.services.user_signal_capture_service import capture_portfolio_interaction
        row = await capture_portfolio_interaction(
            db, user_id=_uid(), entity_key="NVDA", run_override=True,
        )
        await db.commit()
        assert row is not None
        assert row.polarity == "positive"
        assert row.signal_type == "portfolio_view"
        assert row.source_surface == "portfolio"


# ---------------------------------------------------------------------------
# 10. capture_alert_interaction: polarity mapping
# ---------------------------------------------------------------------------

class TestAlertInteractionPolarity:
    @pytest.mark.asyncio
    async def test_alert_open_is_positive(self, db):
        from app.services.user_signal_capture_service import capture_alert_interaction
        row = await capture_alert_interaction(
            db, user_id=_uid(), signal_type="alert_open", run_override=True,
        )
        await db.commit()
        assert row.polarity == "positive"

    @pytest.mark.asyncio
    async def test_alert_act_is_positive(self, db):
        from app.services.user_signal_capture_service import capture_alert_interaction
        row = await capture_alert_interaction(
            db, user_id=_uid(), signal_type="alert_act", run_override=True,
        )
        await db.commit()
        assert row.polarity == "positive"

    @pytest.mark.asyncio
    async def test_alert_dismiss_is_negative(self, db):
        from app.services.user_signal_capture_service import capture_alert_interaction
        row = await capture_alert_interaction(
            db, user_id=_uid(), signal_type="alert_dismiss", run_override=True,
        )
        await db.commit()
        assert row.polarity == "negative"

    @pytest.mark.asyncio
    async def test_alert_mute_is_negative(self, db):
        from app.services.user_signal_capture_service import capture_alert_interaction
        row = await capture_alert_interaction(
            db, user_id=_uid(), signal_type="alert_mute", run_override=True,
        )
        await db.commit()
        assert row.polarity == "negative"

    @pytest.mark.asyncio
    async def test_unknown_alert_signal_is_neutral(self, db):
        from app.services.user_signal_capture_service import capture_alert_interaction
        row = await capture_alert_interaction(
            db, user_id=_uid(), signal_type="alert_snooze", run_override=True,
        )
        await db.commit()
        assert row.polarity == "neutral"


# ---------------------------------------------------------------------------
# 11. Event persistence
# ---------------------------------------------------------------------------

class TestEventPersistence:
    @pytest.mark.asyncio
    async def test_event_row_appears_in_db(self, db):
        from app.services.user_signal_capture_service import capture_analysis_signal
        from app.db.repositories.user_learning_repo import (
            list_user_signal_events, count_user_signal_events,
        )
        uid = _uid()
        await capture_analysis_signal(
            db, user_id=uid, signal_type="analysis_open",
            entity_type="company", entity_key="NVDA", run_override=True,
        )
        await db.commit()
        n = await count_user_signal_events(db, user_id=uid)
        assert n == 1
        rows = await list_user_signal_events(db, user_id=uid)
        assert rows[0].entity_key == "NVDA"

    @pytest.mark.asyncio
    async def test_entity_key_and_type_stored(self, db):
        from app.services.user_signal_capture_service import capture_watchlist_interaction
        from app.db.repositories.user_learning_repo import list_user_signal_events
        uid = _uid()
        await capture_watchlist_interaction(
            db, user_id=uid, signal_type="watchlist_add",
            entity_type="company", entity_key="GOOG", run_override=True,
        )
        await db.commit()
        rows = await list_user_signal_events(db, user_id=uid)
        assert rows[0].entity_type == "company"
        assert rows[0].entity_key == "GOOG"

    @pytest.mark.asyncio
    async def test_source_surface_stored(self, db):
        from app.services.user_signal_capture_service import capture_alert_interaction
        from app.db.repositories.user_learning_repo import list_user_signal_events
        uid = _uid()
        await capture_alert_interaction(
            db, user_id=uid, signal_type="alert_open",
            source_surface="alert_digest", run_override=True,
        )
        await db.commit()
        rows = await list_user_signal_events(db, user_id=uid)
        assert rows[0].source_surface == "alert_digest"


# ---------------------------------------------------------------------------
# 12. surface_was_personalized propagated
# ---------------------------------------------------------------------------

class TestSurfaceWasPersonalized:
    @pytest.mark.asyncio
    async def test_personalized_flag_true(self, db):
        from app.services.user_signal_capture_service import capture_analysis_signal
        from app.db.repositories.user_learning_repo import list_user_signal_events
        uid = _uid()
        await capture_analysis_signal(
            db, user_id=uid, signal_type="analysis_open",
            surface_was_personalized=True, run_override=True,
        )
        await db.commit()
        rows = await list_user_signal_events(db, user_id=uid)
        assert rows[0].surface_was_personalized is True

    @pytest.mark.asyncio
    async def test_personalized_flag_false_by_default(self, db):
        from app.services.user_signal_capture_service import capture_forecast_interaction
        from app.db.repositories.user_learning_repo import list_user_signal_events
        uid = _uid()
        await capture_forecast_interaction(
            db, user_id=uid, signal_type="forecast_view", run_override=True,
        )
        await db.commit()
        rows = await list_user_signal_events(db, user_id=uid)
        assert rows[0].surface_was_personalized is False


# ---------------------------------------------------------------------------
# 13. pre_personalization_rank propagated
# ---------------------------------------------------------------------------

class TestPrePersonalizationRank:
    @pytest.mark.asyncio
    async def test_rank_stored_when_provided(self, db):
        from app.services.user_signal_capture_service import capture_scenario_interaction
        from app.db.repositories.user_learning_repo import list_user_signal_events
        uid = _uid()
        await capture_scenario_interaction(
            db, user_id=uid, signal_type="scenario_expand",
            pre_personalization_rank=7, run_override=True,
        )
        await db.commit()
        rows = await list_user_signal_events(db, user_id=uid)
        assert rows[0].pre_personalization_rank == 7

    @pytest.mark.asyncio
    async def test_rank_none_when_not_provided(self, db):
        from app.services.user_signal_capture_service import capture_portfolio_interaction
        from app.db.repositories.user_learning_repo import list_user_signal_events
        uid = _uid()
        await capture_portfolio_interaction(
            db, user_id=uid, entity_key="NVDA", run_override=True,
        )
        await db.commit()
        rows = await list_user_signal_events(db, user_id=uid)
        assert rows[0].pre_personalization_rank is None


# ---------------------------------------------------------------------------
# 14. Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_user_a_events_not_returned_for_user_b(self, db):
        from app.services.user_signal_capture_service import capture_analysis_signal
        from app.db.repositories.user_learning_repo import list_user_signal_events
        uid_a, uid_b = _uid(), _uid()
        await capture_analysis_signal(
            db, user_id=uid_a, signal_type="analysis_open", run_override=True,
        )
        await db.commit()
        rows_b = await list_user_signal_events(db, user_id=uid_b)
        assert rows_b == []

    @pytest.mark.asyncio
    async def test_counts_are_per_user(self, db):
        from app.services.user_signal_capture_service import capture_watchlist_interaction
        from app.db.repositories.user_learning_repo import count_user_signal_events
        uid_a, uid_b = _uid(), _uid()
        await capture_watchlist_interaction(
            db, user_id=uid_a, signal_type="watchlist_add", run_override=True,
        )
        await capture_watchlist_interaction(
            db, user_id=uid_a, signal_type="watchlist_add", run_override=True,
        )
        await capture_watchlist_interaction(
            db, user_id=uid_b, signal_type="watchlist_add", run_override=True,
        )
        await db.commit()
        assert await count_user_signal_events(db, user_id=uid_a) == 2
        assert await count_user_signal_events(db, user_id=uid_b) == 1


# ---------------------------------------------------------------------------
# 15. No preference creation
# ---------------------------------------------------------------------------

class TestNoPreferenceCreation:
    @pytest.mark.asyncio
    async def test_capture_does_not_create_learned_preference(self, db):
        from app.services.user_signal_capture_service import capture_analysis_signal
        from app.db.repositories.user_learning_repo import count_learned_preferences
        uid = _uid()
        before = await count_learned_preferences(db, user_id=uid)
        await capture_analysis_signal(
            db, user_id=uid, signal_type="analysis_open",
            entity_key="NVDA", run_override=True,
        )
        await db.commit()
        after = await count_learned_preferences(db, user_id=uid)
        assert before == after == 0, (
            "Signal capture must not create learned_preference rows — "
            "that is the inference layer's job (Slice 15.5)"
        )

    @pytest.mark.asyncio
    async def test_multiple_captures_still_no_preferences(self, db):
        from app.services.user_signal_capture_service import (
            capture_analysis_signal, capture_watchlist_interaction,
            capture_alert_interaction,
        )
        from app.db.repositories.user_learning_repo import count_learned_preferences
        uid = _uid()
        for _ in range(5):
            await capture_analysis_signal(
                db, user_id=uid, signal_type="analysis_open", run_override=True,
            )
        await capture_watchlist_interaction(
            db, user_id=uid, signal_type="watchlist_add", run_override=True,
        )
        await capture_alert_interaction(
            db, user_id=uid, signal_type="alert_dismiss", run_override=True,
        )
        await db.commit()
        n = await count_learned_preferences(db, user_id=uid)
        assert n == 0


# ---------------------------------------------------------------------------
# 16. No relevance adjustment creation
# ---------------------------------------------------------------------------

class TestNoRelevanceAdjustmentCreation:
    @pytest.mark.asyncio
    async def test_capture_does_not_create_adjustment_log_rows(self, db):
        from app.services.user_signal_capture_service import (
            capture_search_signal, capture_portfolio_interaction,
        )
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        await capture_search_signal(
            db, user_id=uid, signal_type="search_click",
            entity_key="NVDA", run_override=True,
        )
        await capture_portfolio_interaction(
            db, user_id=uid, entity_key="MSFT", run_override=True,
        )
        await db.commit()
        n = await count_relevance_adjustment_logs(db, user_id=uid)
        assert n == 0, (
            "Signal capture must not create relevance_adjustment_log rows — "
            "that is the relevance shadow service's job (Slice 15.9)"
        )


# ---------------------------------------------------------------------------
# 17. No truth-table mutation during capture
# ---------------------------------------------------------------------------

class TestNoTruthTableMutation:
    @pytest.mark.asyncio
    async def test_capture_does_not_mutate_truth_tables(self, db):
        from sqlalchemy import select, func
        from app.db.models import ForecastVector, ScenarioSnapshot, DecisionPriority
        from app.services.user_signal_capture_service import (
            capture_analysis_signal, capture_forecast_interaction,
            capture_scenario_interaction,
        )

        async def _counts():
            fv = (await db.execute(
                select(func.count()).select_from(ForecastVector))).scalar_one()
            ss = (await db.execute(
                select(func.count()).select_from(ScenarioSnapshot))).scalar_one()
            dp = (await db.execute(
                select(func.count()).select_from(DecisionPriority))).scalar_one()
            return fv, ss, dp

        before = await _counts()
        uid = _uid()
        await capture_analysis_signal(
            db, user_id=uid, signal_type="analysis_open",
            entity_key="NVDA", run_override=True,
        )
        await capture_forecast_interaction(
            db, user_id=uid, signal_type="forecast_view",
            entity_key="NVDA", run_override=True,
        )
        await capture_scenario_interaction(
            db, user_id=uid, signal_type="scenario_expand",
            entity_key="NVDA", run_override=True,
        )
        await db.commit()
        after = await _counts()
        assert before == after == (0, 0, 0), (
            f"Truth-table row counts changed during capture: {before} → {after}"
        )


# ---------------------------------------------------------------------------
# 18. AST safety: no truth-write imports
# ---------------------------------------------------------------------------

class TestASTNoTruthWriteImports:
    def test_service_does_not_import_write_repositories(self):
        import app.services.user_signal_capture_service as mod
        src  = inspect.getsource(mod)
        tree = ast.parse(src)
        imported: list = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
        forbidden = [
            "forecast_repo", "similarity_repo", "scenario_repo", "decision_repo",
            "conviction_engine", "recommendation_engine", "stance_engine",
            "order_engine", "execution_engine",
        ]
        violations = [n for n in imported if any(f in n.lower() for f in forbidden)]
        assert not violations, (
            f"user_signal_capture_service imports forbidden modules: {violations}"
        )

    def test_service_does_not_reference_truth_orm_models(self):
        import app.services.user_signal_capture_service as mod
        src = inspect.getsource(mod)
        forbidden_models = [
            "ForecastVector", "ScenarioSnapshot", "DecisionPriority",
            "SimilarityEdge", "ForecastEvidence",
        ]
        for model in forbidden_models:
            assert model not in src, (
                f"user_signal_capture_service references {model} — SP-7a violation"
            )

    def test_service_only_imports_user_learning_repo(self):
        import app.services.user_signal_capture_service as mod
        src  = inspect.getsource(mod)
        tree = ast.parse(src)
        # The only repo import should be user_learning_repo
        repo_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "repo" in node.module.lower():
                    repo_imports.append(node.module)
        assert all("user_learning_repo" in m for m in repo_imports), (
            f"Service imports unexpected repo: {repo_imports}"
        )


# ---------------------------------------------------------------------------
# 19. AST safety: no buy/sell/advice language in non-docstring constants
# ---------------------------------------------------------------------------

class TestASTNoAdviceLanguage:
    _ADVICE_PHRASES = [
        "buy", "sell", "hold", "recommendation", "target_price",
        "position_size", "trade", "execution",
    ]

    def test_no_advice_phrases_in_long_string_constants(self):
        import app.services.user_signal_capture_service as mod
        src  = inspect.getsource(mod)
        tree = ast.parse(src)

        docstring_nodes: set = set()

        def _mark_docstrings(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Module)):
                body = node.body
                if body and isinstance(body[0], ast.Expr):
                    val = body[0].value
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        docstring_nodes.add(id(val))
            for child in ast.iter_child_nodes(node):
                _mark_docstrings(child)

        _mark_docstrings(tree)

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstring_nodes:
                    continue
                val = node.value.lower()
                if len(val) > 60:
                    for phrase in self._ADVICE_PHRASES:
                        if phrase in val:
                            violations.append((phrase, node.value[:80]))
        assert not violations, (
            f"Advice/trade phrases found in non-docstring string constants: {violations}"
        )


# ---------------------------------------------------------------------------
# 20. Multiple events: each call creates an independent row
# ---------------------------------------------------------------------------

class TestMultipleEventsIndependent:
    @pytest.mark.asyncio
    async def test_repeated_same_signal_creates_multiple_rows(self, db):
        from app.services.user_signal_capture_service import capture_analysis_signal
        from app.db.repositories.user_learning_repo import count_user_signal_events
        uid = _uid()
        for _ in range(5):
            await capture_analysis_signal(
                db, user_id=uid, signal_type="analysis_open",
                entity_key="NVDA", run_override=True,
            )
        await db.commit()
        n = await count_user_signal_events(db, user_id=uid)
        assert n == 5, "Each capture call must create an independent event row"

    @pytest.mark.asyncio
    async def test_mixed_signals_all_persisted(self, db):
        from app.services.user_signal_capture_service import (
            capture_search_signal, capture_analysis_signal,
            capture_forecast_interaction, capture_watchlist_interaction,
        )
        from app.db.repositories.user_learning_repo import count_user_signal_events
        uid = _uid()
        await capture_search_signal(
            db, user_id=uid, signal_type="search_click", run_override=True,
        )
        await capture_analysis_signal(
            db, user_id=uid, signal_type="analysis_open", run_override=True,
        )
        await capture_forecast_interaction(
            db, user_id=uid, signal_type="forecast_view", run_override=True,
        )
        await capture_watchlist_interaction(
            db, user_id=uid, signal_type="watchlist_add", run_override=True,
        )
        await db.commit()
        n = await count_user_signal_events(db, user_id=uid)
        assert n == 4
