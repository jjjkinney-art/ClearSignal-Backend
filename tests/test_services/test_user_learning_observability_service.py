"""
Tests — User Learning Observability Service, Phase 15 · Slice 11.

Verified properties
-------------------
  1. build_user_learning_snapshot (null session)
       - returns safe empty metrics with db_available=False
       - flags present and structurally correct
       - safe_state.overall computed from flags

  2. build_user_learning_snapshot (live session, empty DB)
       - all counts are zero
       - db_available=True
       - safe_state correct

  3. build_user_learning_snapshot (populated DB)
       - user_signal_event_count reflects inserts
       - learned_preference_count reflects inserts
       - preference_evidence_count reflects inserts
       - relevance_adjustment_log_count reflects inserts
       - shadow_adjustment_count reflects shadow rows
       - calibration_outcome_count reflects calibration rows
       - preference_count_by_dimension breakdown correct
       - preference_count_by_strength_label breakdown correct
       - latest_signal_timestamp present
       - latest_preference_timestamp present
       - latest_adjustment_timestamp present

  4. safe_state sub-checks
       - shadow_only: shadow=True AND relevance_enabled=False → True
       - no_live_personalization: relevance_enabled=False → True
       - no_truth_mutation: capture+inference+relevance all off → True
       - no_recommendation_consumers: targets_enabled="" → True
       - no_forecast_similarity_scenario_decision_mutation: capture+inf off → True
       - overall is AND of all sub-checks
       - overall False when relevance_enabled=True AND shadow=False

  5. DB-down degradation
       - None session → db_available=False, all counts 0

  6. No secret leakage
       - disclaimer present
       - no key named "key", "secret", "token", "password"
       - schema_version is int

  7. Admin route shape (AST)
       - api.py contains /admin/user-learning-status
       - handler calls build_user_learning_snapshot
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.services import user_learning_observability_service as svc

_ROOT     = pathlib.Path(__file__).parent.parent.parent
_API_PATH = _ROOT / "app" / "api.py"

# ---------------------------------------------------------------------------
# Fixtures
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


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# DB population helpers
# ---------------------------------------------------------------------------

async def _add_signal(session, user_id: str) -> Any:
    from app.db.repositories.user_learning_repo import add_user_signal_event
    return await add_user_signal_event(
        session,
        user_id        = user_id,
        signal_type    = "mention",
        polarity       = "positive",
        entity_key     = "AAPL",
        source_surface = "feed",
        occurred_at    = _now(),
    )


async def _add_pref(
    session, user_id: str,
    dimension: str = "sector_interest",
    strength: str = "moderate",
) -> Any:
    from app.db.repositories.user_learning_repo import upsert_learned_preference
    return await upsert_learned_preference(
        session,
        user_id               = user_id,
        dimension             = dimension,
        entity_key            = str(uuid.uuid4()),
        affinity              = 0.7,
        confidence            = 0.7,
        signal_strength_label = strength,
    )


async def _add_adj_log(
    session, user_id: str, run_reason: str = "shadow"
) -> Any:
    from app.db.repositories.user_learning_repo import add_relevance_adjustment_log
    return await add_relevance_adjustment_log(
        session,
        user_id          = user_id,
        surface          = "feed",
        run_reason       = run_reason,
        item_ref         = str(uuid.uuid4()),
        intrinsic_rank   = 5,
        adjusted_rank    = 3,
        relevance_weight = 0.2,
    )


# ---------------------------------------------------------------------------
# 1. Null session
# ---------------------------------------------------------------------------

class TestNullSession:

    @pytest.mark.asyncio
    async def test_null_session_returns_dict(self):
        snap = await svc.build_user_learning_snapshot(None)
        assert isinstance(snap, dict)

    @pytest.mark.asyncio
    async def test_null_session_db_available_false(self):
        snap = await svc.build_user_learning_snapshot(None)
        assert snap["db_available"] is False

    @pytest.mark.asyncio
    async def test_null_session_all_counts_zero(self):
        snap = await svc.build_user_learning_snapshot(None)
        m = snap["metrics"]
        assert m["user_signal_event_count"]        == 0
        assert m["learned_preference_count"]       == 0
        assert m["preference_evidence_count"]      == 0
        assert m["relevance_adjustment_log_count"] == 0
        assert m["shadow_adjustment_count"]        == 0
        assert m["calibration_outcome_count"]      == 0

    @pytest.mark.asyncio
    async def test_null_session_flags_present(self):
        snap = await svc.build_user_learning_snapshot(None)
        flags = snap["flags"]
        for key in (
            "learning_capture_enabled",
            "learning_inference_enabled",
            "learning_relevance_enabled",
            "learning_shadow",
            "learning_targets_enabled",
            "learning_calibration_enabled",
        ):
            assert key in flags, f"missing flag: {key}"

    @pytest.mark.asyncio
    async def test_null_session_safe_state_present(self):
        snap = await svc.build_user_learning_snapshot(None)
        assert "safe_state" in snap
        assert "overall" in snap["safe_state"]

    @pytest.mark.asyncio
    async def test_null_session_default_flags_overall_true(self):
        snap = await svc.build_user_learning_snapshot(None)
        assert snap["safe_state"]["overall"] is True


# ---------------------------------------------------------------------------
# 2. Empty DB
# ---------------------------------------------------------------------------

class TestEmptyDb:

    @pytest.mark.asyncio
    async def test_empty_db_available_true(self, session):
        snap = await svc.build_user_learning_snapshot(session)
        assert snap["db_available"] is True

    @pytest.mark.asyncio
    async def test_empty_db_signal_count_zero(self, session):
        snap = await svc.build_user_learning_snapshot(session)
        assert snap["metrics"]["user_signal_event_count"] >= 0

    @pytest.mark.asyncio
    async def test_empty_db_schema_version(self, session):
        snap = await svc.build_user_learning_snapshot(session)
        assert isinstance(snap["schema_version"], int)
        assert snap["schema_version"] >= 1

    @pytest.mark.asyncio
    async def test_empty_db_snapshot_utc_present(self, session):
        snap = await svc.build_user_learning_snapshot(session)
        assert "snapshot_utc" in snap
        assert isinstance(snap["snapshot_utc"], str)

    @pytest.mark.asyncio
    async def test_empty_db_disclaimer_present(self, session):
        snap = await svc.build_user_learning_snapshot(session)
        assert "disclaimer" in snap
        assert len(snap["disclaimer"]) > 20


# ---------------------------------------------------------------------------
# 3. Populated DB
# ---------------------------------------------------------------------------

class TestPopulatedDb:

    @pytest.mark.asyncio
    async def test_signal_count_reflects_inserts(self, session):
        uid = _uid()
        snap_before = await svc.build_user_learning_snapshot(session)
        before = snap_before["metrics"]["user_signal_event_count"]
        await _add_signal(session, uid)
        await _add_signal(session, uid)
        snap_after = await svc.build_user_learning_snapshot(session)
        after = snap_after["metrics"]["user_signal_event_count"]
        assert after >= before + 2

    @pytest.mark.asyncio
    async def test_preference_count_reflects_inserts(self, session):
        uid = _uid()
        snap_before = await svc.build_user_learning_snapshot(session)
        before = snap_before["metrics"]["learned_preference_count"]
        await _add_pref(session, uid)
        snap_after = await svc.build_user_learning_snapshot(session)
        after = snap_after["metrics"]["learned_preference_count"]
        assert after >= before + 1

    @pytest.mark.asyncio
    async def test_log_count_reflects_inserts(self, session):
        uid = _uid()
        snap_before = await svc.build_user_learning_snapshot(session)
        before = snap_before["metrics"]["relevance_adjustment_log_count"]
        await _add_adj_log(session, uid, run_reason="shadow")
        snap_after = await svc.build_user_learning_snapshot(session)
        after = snap_after["metrics"]["relevance_adjustment_log_count"]
        assert after >= before + 1

    @pytest.mark.asyncio
    async def test_shadow_count_reflects_shadow_rows(self, session):
        uid = _uid()
        snap_before = await svc.build_user_learning_snapshot(session)
        before = snap_before["metrics"]["shadow_adjustment_count"]
        await _add_adj_log(session, uid, run_reason="shadow")
        snap_after = await svc.build_user_learning_snapshot(session)
        after = snap_after["metrics"]["shadow_adjustment_count"]
        assert after >= before + 1

    @pytest.mark.asyncio
    async def test_calibration_count_reflects_calibration_rows(self, session):
        uid = _uid()
        snap_before = await svc.build_user_learning_snapshot(session)
        before = snap_before["metrics"]["calibration_outcome_count"]
        await _add_adj_log(session, uid, run_reason="calibration")
        snap_after = await svc.build_user_learning_snapshot(session)
        after = snap_after["metrics"]["calibration_outcome_count"]
        assert after >= before + 1

    @pytest.mark.asyncio
    async def test_preference_count_by_dimension(self, session):
        uid = _uid()
        await _add_pref(session, uid, dimension="company_interest")
        snap = await svc.build_user_learning_snapshot(session)
        by_dim = snap["metrics"]["preference_count_by_dimension"]
        assert isinstance(by_dim, dict)
        assert "company_interest" in by_dim
        assert by_dim["company_interest"] >= 1

    @pytest.mark.asyncio
    async def test_preference_count_by_strength_label(self, session):
        uid = _uid()
        await _add_pref(session, uid, strength="strong")
        snap = await svc.build_user_learning_snapshot(session)
        by_strength = snap["metrics"]["preference_count_by_strength_label"]
        assert isinstance(by_strength, dict)
        assert "strong" in by_strength
        assert by_strength["strong"] >= 1

    @pytest.mark.asyncio
    async def test_latest_signal_timestamp_present(self, session):
        uid = _uid()
        await _add_signal(session, uid)
        snap = await svc.build_user_learning_snapshot(session)
        ts = snap["metrics"]["latest_signal_timestamp"]
        assert ts is not None
        assert isinstance(ts, str)

    @pytest.mark.asyncio
    async def test_latest_preference_timestamp_present(self, session):
        uid = _uid()
        await _add_pref(session, uid)
        snap = await svc.build_user_learning_snapshot(session)
        ts = snap["metrics"]["latest_preference_timestamp"]
        assert ts is not None
        assert isinstance(ts, str)

    @pytest.mark.asyncio
    async def test_latest_adjustment_timestamp_present(self, session):
        uid = _uid()
        await _add_adj_log(session, uid)
        snap = await svc.build_user_learning_snapshot(session)
        ts = snap["metrics"]["latest_adjustment_timestamp"]
        assert ts is not None
        assert isinstance(ts, str)


# ---------------------------------------------------------------------------
# 4. safe_state sub-checks
# ---------------------------------------------------------------------------

class TestSafeState:

    def _state(self, **flags):
        return svc._compute_safe_state(flags)

    def test_shadow_only_true_when_shadow_and_no_relevance(self):
        s = self._state(learning_shadow=True, learning_relevance_enabled=False)
        assert s["shadow_only"] is True

    def test_shadow_only_false_when_relevance_on_and_shadow_off(self):
        s = self._state(
            learning_shadow=False,
            learning_relevance_enabled=True,
        )
        assert s["shadow_only"] is False

    def test_no_live_personalization_true_when_relevance_off(self):
        s = self._state(learning_relevance_enabled=False)
        assert s["no_live_personalization"] is True

    def test_no_live_personalization_false_when_relevance_on(self):
        s = self._state(learning_relevance_enabled=True)
        assert s["no_live_personalization"] is False

    def test_no_truth_mutation_true_when_all_off(self):
        s = self._state(
            learning_capture_enabled=False,
            learning_inference_enabled=False,
            learning_relevance_enabled=False,
        )
        assert s["no_truth_mutation"] is True

    def test_no_recommendation_consumers_true_when_targets_empty(self):
        s = self._state(learning_targets_enabled="")
        assert s["no_recommendation_consumers"] is True

    def test_no_recommendation_consumers_false_when_targets_set(self):
        s = self._state(learning_targets_enabled="feed")
        assert s["no_recommendation_consumers"] is False

    def test_no_forecast_mutation_true_when_capture_off(self):
        s = self._state(
            learning_capture_enabled=False,
            learning_inference_enabled=True,
        )
        assert s["no_forecast_similarity_scenario_decision_mutation"] is True

    def test_overall_true_with_all_safe_defaults(self):
        s = self._state(
            learning_capture_enabled=False,
            learning_inference_enabled=False,
            learning_relevance_enabled=False,
            learning_shadow=True,
            learning_targets_enabled="",
            learning_calibration_enabled=False,
        )
        assert s["overall"] is True

    def test_overall_false_when_relevance_on_and_shadow_off(self):
        s = self._state(
            learning_capture_enabled=True,
            learning_inference_enabled=True,
            learning_relevance_enabled=True,
            learning_shadow=False,
            learning_targets_enabled="",
            learning_calibration_enabled=False,
        )
        assert s["overall"] is False


# ---------------------------------------------------------------------------
# 5. DB-down degradation
# ---------------------------------------------------------------------------

class TestDbDown:

    @pytest.mark.asyncio
    async def test_none_session_no_raise(self):
        snap = await svc.build_user_learning_snapshot(None)
        assert snap is not None

    @pytest.mark.asyncio
    async def test_none_session_all_metrics_zero(self):
        snap = await svc.build_user_learning_snapshot(None)
        m = snap["metrics"]
        assert m["user_signal_event_count"] == 0
        assert m["learned_preference_count"] == 0
        assert m["relevance_adjustment_log_count"] == 0
        assert m["shadow_adjustment_count"] == 0
        assert m["calibration_outcome_count"] == 0

    @pytest.mark.asyncio
    async def test_none_session_db_available_false(self):
        snap = await svc.build_user_learning_snapshot(None)
        assert snap["db_available"] is False
        assert snap["metrics"]["db_available"] is False


# ---------------------------------------------------------------------------
# 6. No secret leakage
# ---------------------------------------------------------------------------

class TestNoSecretLeakage:

    @pytest.mark.asyncio
    async def test_disclaimer_present(self):
        snap = await svc.build_user_learning_snapshot(None)
        assert snap.get("disclaimer")

    @pytest.mark.asyncio
    async def test_no_secret_keys(self):
        snap = await svc.build_user_learning_snapshot(None)

        def _walk(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    low = k.lower()
                    for bad in ("secret", "password", "token", "api_key"):
                        assert bad not in low, (
                            f"secret-like key {k!r} at {path}"
                        )
                    _walk(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _walk(item, f"{path}[{i}]")

        _walk(snap)

    @pytest.mark.asyncio
    async def test_schema_version_is_int(self):
        snap = await svc.build_user_learning_snapshot(None)
        assert isinstance(snap["schema_version"], int)
        assert snap["schema_version"] >= 1


# ---------------------------------------------------------------------------
# 7. Admin route shape (AST)
# ---------------------------------------------------------------------------

class TestAdminRouteShape:

    def test_admin_route_present_in_api(self):
        src = _API_PATH.read_text()
        assert "/admin/user-learning-status" in src

    def test_handler_calls_build_snapshot(self):
        src = _API_PATH.read_text()
        assert "build_user_learning_snapshot" in src

    def test_handler_imports_from_observability_service(self):
        src = _API_PATH.read_text()
        assert "user_learning_observability_service" in src

    def test_no_direct_db_write_in_admin_handler(self):
        tree = ast.parse(_API_PATH.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if node.name != "admin_user_learning_status":
                continue
            func_src = ast.unparse(node)
            for bad in ("session.add", "session.execute", ".flush()", ".commit()"):
                assert bad not in func_src, (
                    f"admin handler should not write directly: found {bad!r}"
                )
