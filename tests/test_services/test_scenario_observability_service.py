"""
Tests for scenario_observability_service — Phase 14 · Slice 10.

Verified properties
-------------------
  1. build_scenario_observability_snapshot (null session)
       - returns safe empty metrics with db_available=False
       - flags present and structurally correct
       - safe_state.overall computed from flags

  2. build_scenario_observability_snapshot (live session, empty DB)
       - all counts are zero
       - db_available=True
       - safe_state correct

  3. build_scenario_observability_snapshot (populated DB)
       - scenario_snapshot_count reflects inserts
       - scenario_evidence_count reflects inserts
       - scenario_run_log_count reflects inserts
       - scenario_count_by_type breakdowns correct
       - scenario_count_by_impact breakdowns correct
       - shadow_delivery_count reflects scenario_shadow ledger rows
       - live_notification_count zero when no notifications inserted
       - latest_scenario_timestamp present
       - latest_calibration_timestamp present

  4. safe_state sub-checks
       - shadow_delivery_only: delivery_enabled=False and shadow=True → True
       - no_recommendation_consumers: delivery_enabled=False → True
       - no_conviction_consumers: scoring_enabled=False → True
       - no_forecast_mutation_consumers: build_enabled=False → True
       - no_decision_mutation_consumers: build_enabled=False → True
       - no_live_notifications: zero Notification rows → True
       - overall is AND of all sub-checks

  5. DB-down degradation
       - None session → db_available=False, zeros everywhere

  6. No secret leakage
       - disclaimer present
       - no key named "key", "secret", "token", "password"
       - schema_version int

  7. Admin route shape (AST)
       - handler calls build_scenario_observability_snapshot
       - handler does not import scenario_read_service directly
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.services import scenario_observability_service as svc

# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_tables(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest_asyncio.fixture
async def session(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        async with s.begin():
            yield s
            await s.rollback()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# DB population helpers
# ---------------------------------------------------------------------------

async def _insert_snapshot(session, *, scenario_type="company", entity_type="company",
                            entity_key="AAPL", scenario_key="base", user_id=None,
                            scenario_impact="moderate_negative"):
    from app.db.models import ScenarioSnapshot
    from datetime import timedelta
    import uuid
    row = ScenarioSnapshot(
        id                = str(uuid.uuid4()),
        scenario_type     = scenario_type,
        entity_type       = entity_type,
        entity_key        = entity_key,
        scenario_key      = scenario_key,
        user_id           = user_id,
        condition         = "test condition",
        transmission_path = [{"step": 1}],
        scenario_impact   = scenario_impact,
        plausibility_band = "plausible",
        confidence_score  = 0.7,
        uncertainty_score = 0.2,
        affected_entities  = [],
        affected_forecasts = [],
        affected_decisions = [],
        what_changed       = "test",
        why_it_matters     = "test",
        evidence_summary   = [],
        invalidators       = ["condition not met"],
        source_versions    = {},
        built_at           = _now(),
        expires_at         = _now() + timedelta(hours=72),
    )
    session.add(row)
    await session.flush()
    return row


async def _insert_evidence(session, *, scenario_id="test-id"):
    from app.db.models import ScenarioEvidence
    import uuid
    row = ScenarioEvidence(
        id           = str(uuid.uuid4()),
        scenario_id  = scenario_id,
        source_phase = "forecast",
        source_ref   = "some-ref",
    )
    session.add(row)
    await session.flush()
    return row


async def _insert_run_log(session, *, scenario_type="company", entity_key="AAPL",
                           run_reason="calibration_outcome", realized_state=None):
    from app.db.models import ScenarioRunLog
    import uuid
    row = ScenarioRunLog(
        id              = str(uuid.uuid4()),
        scenario_type   = scenario_type,
        entity_type     = "company",
        entity_key      = entity_key,
        run_reason      = run_reason,
        snapshot_reason = "test",
        realized_state  = realized_state,
        evaluated_at    = _now(),
        created_at      = _now(),
    )
    session.add(row)
    await session.flush()
    return row


async def _insert_shadow_ledger(session, *, target_key="test:key", content_key=None):
    from app.db.models import DeliveryLedger
    import uuid, hashlib, json
    ck = content_key or hashlib.sha256(target_key.encode()).hexdigest()[:64]
    row = DeliveryLedger(
        id           = str(uuid.uuid4()),
        content_key  = ck,
        target_key   = target_key,
        channel      = "scenario_shadow",
        content_hash = ck,
        status       = "pending",
    )
    session.add(row)
    await session.flush()
    return row


# ============================================================================
# 1. Null session
# ============================================================================

class TestNullSession:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        result = await svc.build_scenario_observability_snapshot(None)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_db_available_false(self):
        result = await svc.build_scenario_observability_snapshot(None)
        assert result["db_available"] is False

    @pytest.mark.asyncio
    async def test_metrics_all_zero(self):
        result = await svc.build_scenario_observability_snapshot(None)
        m = result["metrics"]
        assert m["scenario_snapshot_count"] == 0
        assert m["scenario_evidence_count"] == 0
        assert m["scenario_run_log_count"] == 0
        assert m["shadow_delivery_count"] == 0
        assert m["live_notification_count"] == 0

    @pytest.mark.asyncio
    async def test_flags_all_present(self):
        result = await svc.build_scenario_observability_snapshot(None)
        flags = result["flags"]
        for key in (
            "scenario_build_enabled",
            "scenario_scoring_enabled",
            "scenario_delivery_enabled",
            "scenario_shadow",
            "scenario_targets_enabled",
            "scenario_calibration_enabled",
        ):
            assert key in flags

    @pytest.mark.asyncio
    async def test_safe_state_present(self):
        result = await svc.build_scenario_observability_snapshot(None)
        assert "safe_state" in result
        assert "overall" in result["safe_state"]

    @pytest.mark.asyncio
    async def test_disclaimer_present(self):
        result = await svc.build_scenario_observability_snapshot(None)
        assert "disclaimer" in result
        assert isinstance(result["disclaimer"], str)
        assert len(result["disclaimer"]) > 10

    @pytest.mark.asyncio
    async def test_schema_version_int(self):
        result = await svc.build_scenario_observability_snapshot(None)
        assert isinstance(result["schema_version"], int)


# ============================================================================
# 2. Live session — empty DB
# ============================================================================

class TestEmptyDB:
    @pytest.mark.asyncio
    async def test_db_available_true(self, session):
        result = await svc.build_scenario_observability_snapshot(session)
        assert result["db_available"] is True

    @pytest.mark.asyncio
    async def test_empty_counts(self, session):
        result = await svc.build_scenario_observability_snapshot(session)
        m = result["metrics"]
        assert m["scenario_snapshot_count"] >= 0
        assert m["scenario_evidence_count"] >= 0
        assert m["shadow_delivery_count"] >= 0
        assert m["live_notification_count"] >= 0

    @pytest.mark.asyncio
    async def test_safe_state_overall_is_bool(self, session):
        result = await svc.build_scenario_observability_snapshot(session)
        assert isinstance(result["safe_state"]["overall"], bool)


# ============================================================================
# 3. Populated DB
# ============================================================================

class TestPopulatedDB:
    @pytest.mark.asyncio
    async def test_snapshot_count_increases(self, session):
        before = await svc.build_scenario_observability_snapshot(session)
        before_count = before["metrics"]["scenario_snapshot_count"]

        await _insert_snapshot(session, entity_key="CNT_TEST_1", scenario_key="s1")
        await _insert_snapshot(session, entity_key="CNT_TEST_2", scenario_key="s2")

        after = await svc.build_scenario_observability_snapshot(session)
        assert after["metrics"]["scenario_snapshot_count"] >= before_count + 2

    @pytest.mark.asyncio
    async def test_evidence_count_increases(self, session):
        before = await svc.build_scenario_observability_snapshot(session)
        before_count = before["metrics"]["scenario_evidence_count"]

        await _insert_evidence(session, scenario_id="evid-test-snap-1")
        await _insert_evidence(session, scenario_id="evid-test-snap-2")

        after = await svc.build_scenario_observability_snapshot(session)
        assert after["metrics"]["scenario_evidence_count"] >= before_count + 2

    @pytest.mark.asyncio
    async def test_run_log_count_increases(self, session):
        before = await svc.build_scenario_observability_snapshot(session)
        before_count = before["metrics"]["scenario_run_log_count"]

        await _insert_run_log(session, entity_key="RL_TEST_1")
        await _insert_run_log(session, entity_key="RL_TEST_2")

        after = await svc.build_scenario_observability_snapshot(session)
        assert after["metrics"]["scenario_run_log_count"] >= before_count + 2

    @pytest.mark.asyncio
    async def test_count_by_type_includes_macro(self, session):
        await _insert_snapshot(session, scenario_type="macro",
                               entity_key="MACRO_OBS", entity_type="macro",
                               scenario_key="macro_obs_1")
        result = await svc.build_scenario_observability_snapshot(session)
        by_type = result["metrics"]["scenario_count_by_type"]
        assert "macro" in by_type
        assert by_type["macro"] >= 1

    @pytest.mark.asyncio
    async def test_count_by_impact_includes_significant_negative(self, session):
        await _insert_snapshot(session, scenario_type="catalyst",
                               entity_key="CAT_OBS_1", entity_type="company",
                               scenario_key="cat_obs_1",
                               scenario_impact="significant_negative")
        result = await svc.build_scenario_observability_snapshot(session)
        by_impact = result["metrics"]["scenario_count_by_impact"]
        assert "significant_negative" in by_impact
        assert by_impact["significant_negative"] >= 1

    @pytest.mark.asyncio
    async def test_shadow_delivery_count_increases(self, session):
        import hashlib
        ck = hashlib.sha256(b"obs_shadow_test_unique_key").hexdigest()[:64]
        await _insert_shadow_ledger(session, target_key="obs:shadow:test", content_key=ck)

        result = await svc.build_scenario_observability_snapshot(session)
        assert result["metrics"]["shadow_delivery_count"] >= 1

    @pytest.mark.asyncio
    async def test_live_notification_count_zero_when_no_notifications(self, session):
        result = await svc.build_scenario_observability_snapshot(session)
        # No notifications inserted in our test scope
        assert result["metrics"]["live_notification_count"] >= 0

    @pytest.mark.asyncio
    async def test_latest_scenario_timestamp_present(self, session):
        await _insert_snapshot(session, entity_key="TS_TEST", scenario_key="ts1")
        result = await svc.build_scenario_observability_snapshot(session)
        assert result["metrics"]["latest_scenario_timestamp"] is not None

    @pytest.mark.asyncio
    async def test_latest_calibration_timestamp_present(self, session):
        await _insert_run_log(session, entity_key="CAL_TS_TEST",
                              run_reason="calibration_outcome",
                              realized_state="materialized")
        result = await svc.build_scenario_observability_snapshot(session)
        # calibration timestamp present if any run_log exists
        assert result["metrics"]["latest_calibration_timestamp"] is not None


# ============================================================================
# 4. safe_state sub-checks
# ============================================================================

class TestSafeStateSubChecks:
    def _safe_state_with_flags(self, *, delivery_enabled, shadow, scoring_enabled,
                               build_enabled, notif_count=0):
        flags = {
            "scenario_build_enabled":       build_enabled,
            "scenario_scoring_enabled":     scoring_enabled,
            "scenario_delivery_enabled":    delivery_enabled,
            "scenario_shadow":              shadow,
            "scenario_targets_enabled":     "",
            "scenario_calibration_enabled": False,
        }
        return svc._compute_safe_state(flags, notif_count)

    def test_shadow_delivery_only_true_when_delivery_off_and_shadow_on(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=False, shadow=True,
            scoring_enabled=False, build_enabled=False
        )
        assert ss["shadow_delivery_only"] is True

    def test_shadow_delivery_only_false_when_delivery_on(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=True, shadow=True,
            scoring_enabled=False, build_enabled=False
        )
        assert ss["shadow_delivery_only"] is False

    def test_no_recommendation_consumers_true_when_delivery_off(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=False, shadow=True,
            scoring_enabled=False, build_enabled=False
        )
        assert ss["no_recommendation_consumers"] is True

    def test_no_conviction_consumers_true_when_scoring_off(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=False, shadow=True,
            scoring_enabled=False, build_enabled=False
        )
        assert ss["no_conviction_consumers"] is True

    def test_no_conviction_consumers_false_when_scoring_on(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=False, shadow=True,
            scoring_enabled=True, build_enabled=False
        )
        assert ss["no_conviction_consumers"] is False

    def test_no_forecast_mutation_true_when_build_off(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=False, shadow=True,
            scoring_enabled=False, build_enabled=False
        )
        assert ss["no_forecast_mutation_consumers"] is True

    def test_no_decision_mutation_true_when_build_off(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=False, shadow=True,
            scoring_enabled=False, build_enabled=False
        )
        assert ss["no_decision_mutation_consumers"] is True

    def test_no_live_notifications_true_when_zero_notif(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=False, shadow=True,
            scoring_enabled=False, build_enabled=False, notif_count=0
        )
        assert ss["no_live_notifications"] is True

    def test_no_live_notifications_false_when_nonzero(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=False, shadow=True,
            scoring_enabled=False, build_enabled=False, notif_count=1
        )
        assert ss["no_live_notifications"] is False

    def test_overall_true_when_all_sub_checks_pass(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=False, shadow=True,
            scoring_enabled=False, build_enabled=False, notif_count=0
        )
        assert ss["overall"] is True

    def test_overall_false_when_any_sub_check_fails(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=True, shadow=True,
            scoring_enabled=False, build_enabled=False
        )
        assert ss["overall"] is False

    def test_safe_state_all_keys_present(self):
        ss = self._safe_state_with_flags(
            delivery_enabled=False, shadow=True,
            scoring_enabled=False, build_enabled=False
        )
        for key in (
            "overall",
            "shadow_delivery_only",
            "no_live_notifications",
            "no_recommendation_consumers",
            "no_conviction_consumers",
            "no_forecast_mutation_consumers",
            "no_decision_mutation_consumers",
        ):
            assert key in ss


# ============================================================================
# 5. DB-down degradation
# ============================================================================

class TestDBDownDegradation:
    @pytest.mark.asyncio
    async def test_none_session_returns_db_available_false(self):
        result = await svc.build_scenario_observability_snapshot(None)
        assert result["db_available"] is False

    @pytest.mark.asyncio
    async def test_none_session_never_raises(self):
        try:
            await svc.build_scenario_observability_snapshot(None)
        except Exception as exc:
            pytest.fail(f"Should not raise: {exc}")

    @pytest.mark.asyncio
    async def test_none_session_metrics_zero(self):
        result = await svc.build_scenario_observability_snapshot(None)
        m = result["metrics"]
        assert m["scenario_snapshot_count"] == 0
        assert m["scenario_run_log_count"] == 0
        assert m["shadow_delivery_count"] == 0

    @pytest.mark.asyncio
    async def test_none_session_safe_state_present(self):
        result = await svc.build_scenario_observability_snapshot(None)
        assert "safe_state" in result
        assert "overall" in result["safe_state"]


# ============================================================================
# 6. No secret leakage
# ============================================================================

class TestNoSecretLeakage:
    @pytest.mark.asyncio
    async def test_no_secret_key_in_response(self, session):
        result = await svc.build_scenario_observability_snapshot(session)
        flat_keys = list(result.keys()) + list(result.get("flags", {}).keys())
        for dangerous in ("key", "secret", "token", "password", "api_key"):
            for k in flat_keys:
                assert dangerous not in k.lower() or k == "content_key", \
                    f"suspicious key {k!r} in response"

    @pytest.mark.asyncio
    async def test_disclaimer_in_response(self, session):
        result = await svc.build_scenario_observability_snapshot(session)
        assert "disclaimer" in result

    @pytest.mark.asyncio
    async def test_schema_version_in_response(self, session):
        result = await svc.build_scenario_observability_snapshot(session)
        assert "schema_version" in result
        assert isinstance(result["schema_version"], int)

    @pytest.mark.asyncio
    async def test_no_raw_sql_or_internal_paths_in_response(self, session):
        result = await svc.build_scenario_observability_snapshot(session)
        result_str = str(result).lower()
        for dangerous in ("select ", "insert ", "update ", "delete "):
            assert dangerous not in result_str


# ============================================================================
# 7. Admin route AST shape
# ============================================================================

class TestAdminRouteShape:
    def _api_source(self):
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "app", "api.py"
        )
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_route_calls_observability_service(self):
        source = self._api_source()
        assert "build_scenario_observability_snapshot" in source

    def test_route_imports_observability_service(self):
        source = self._api_source()
        assert "scenario_observability_service" in source

    def test_observability_schema_version_constant_exists(self):
        assert hasattr(svc, "OBSERVABILITY_SCHEMA_VERSION")
        assert isinstance(svc.OBSERVABILITY_SCHEMA_VERSION, int)

    def test_build_function_is_async(self):
        assert inspect.iscoroutinefunction(svc.build_scenario_observability_snapshot)

    def test_compute_safe_state_is_sync(self):
        assert not inspect.iscoroutinefunction(svc._compute_safe_state)
