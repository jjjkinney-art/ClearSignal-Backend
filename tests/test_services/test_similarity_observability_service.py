"""
Tests — Similarity Observability Service, Phase 11 · Slice 8.

Covers:
  1.  Empty snapshot (clean DB, nothing built)
  2.  Populated snapshot (vectors + edges + shadow delivery rows present)
  3.  DB-down degradation (session=None)
  4.  safe_state true/false combinations
  5.  No secret leakage (snapshot never contains raw credential-like values)
  6.  Admin route response shape (via the service function the route delegates to)
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


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


REQUIRED_KEYS = {
    "flags", "db_available", "vector_counts", "edge_counts",
    "edge_counts_by_target_type", "shadow_delivery_count", "shadow_escalated_count",
    "live_notification_count", "latest_vector_built_at", "latest_edge_scored_at",
    "safe_state", "snapshot_utc",
}


# ---------------------------------------------------------------------------
# 1. Empty snapshot
# ---------------------------------------------------------------------------

class TestEmptySnapshot:
    @pytest.mark.asyncio
    async def test_empty_db_snapshot_shape_and_zero_counts(self, db):
        from app.services.similarity_observability_service import build_similarity_observability_snapshot

        snapshot = await build_similarity_observability_snapshot(db)
        assert REQUIRED_KEYS.issubset(snapshot.keys())
        assert snapshot["db_available"] is True
        assert snapshot["vector_counts"] == {"failure_mode": 0, "company": 0, "thesis": 0}
        assert snapshot["edge_counts"] == {"total": 0, "floor_passed": 0, "expired": 0}
        assert snapshot["edge_counts_by_target_type"] == {"failure_mode": 0, "company": 0, "thesis": 0}
        assert snapshot["shadow_delivery_count"] == 0
        assert snapshot["shadow_escalated_count"] == 0
        assert snapshot["live_notification_count"] == 0
        assert snapshot["latest_vector_built_at"] is None
        assert snapshot["latest_edge_scored_at"] is None
        assert snapshot["safe_state"] is True


# ---------------------------------------------------------------------------
# 2. Populated snapshot
# ---------------------------------------------------------------------------

class TestPopulatedSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_reflects_built_vectors_and_edges(self, db):
        from app.db.models import HistoricalAnalog
        from app.db.repositories.dossier_repo import upsert_failure_mode
        from app.services.similarity_feature_builder import build_failure_mode_feature_vector
        from app.services.similarity_scorer import build_failure_mode_similarity_edges
        from app.services.similarity_observability_service import build_similarity_observability_snapshot

        analog = HistoricalAnalog(
            label="Obs Analog", episode="probe", mechanism="inventory_channel_correction",
            concern_tags=["supply_chain_risk"], sector="tech", business_model="hardware",
            disanalogy="n/a",
        )
        db.add(analog)
        await db.flush()
        fm_q = await upsert_failure_mode(db, "OBSQ", analog.id, sequence_stage=1)
        fm_c = await upsert_failure_mode(db, "OBSC", analog.id, sequence_stage=1)
        await db.commit()

        await build_failure_mode_feature_vector(db, fm_q.id)
        await build_failure_mode_feature_vector(db, fm_c.id)
        await db.commit()
        await build_failure_mode_similarity_edges(db, fm_q.id)
        await db.commit()

        snapshot = await build_similarity_observability_snapshot(db)
        assert snapshot["vector_counts"]["failure_mode"] == 2
        assert snapshot["edge_counts"]["total"] >= 1
        assert snapshot["edge_counts_by_target_type"]["failure_mode"] == snapshot["edge_counts"]["total"]
        assert snapshot["latest_vector_built_at"] is not None
        assert snapshot["latest_edge_scored_at"] is not None
        assert snapshot["safe_state"] is True  # still safe — no escalation, no notifications

    @pytest.mark.asyncio
    async def test_snapshot_counts_shadow_delivery_rows(self, db, monkeypatch):
        from app.config import settings
        from app.services.similarity_delivery_service import record_similarity_transition_events
        from app.services.similarity_observability_service import build_similarity_observability_snapshot

        monkeypatch.setattr(settings, "similarity_build_enabled", True)
        monkeypatch.setattr(settings, "similarity_scoring_enabled", True)
        monkeypatch.setattr(settings, "similarity_shadow", True)

        previous = [{
            "target_type": "failure_mode", "query_key": "OBS2Q", "candidate_key": "OBS2C",
            "score": 0.2, "floor_passed": False, "user_id": None,
        }]
        current = [{
            "target_type": "failure_mode", "query_key": "OBS2Q", "candidate_key": "OBS2C",
            "score": 0.6, "floor_passed": True, "user_id": None,
        }]
        await record_similarity_transition_events(db, previous, current)
        await db.commit()

        snapshot = await build_similarity_observability_snapshot(db)
        assert snapshot["shadow_delivery_count"] == 1
        assert snapshot["shadow_escalated_count"] == 0
        assert snapshot["safe_state"] is True


# ---------------------------------------------------------------------------
# 3. DB-down degradation
# ---------------------------------------------------------------------------

class TestDbDownDegradation:
    @pytest.mark.asyncio
    async def test_session_none_degrades_safely(self):
        from app.services.similarity_observability_service import build_similarity_observability_snapshot

        snapshot = await build_similarity_observability_snapshot(None)
        assert REQUIRED_KEYS.issubset(snapshot.keys())
        assert snapshot["db_available"] is False
        assert snapshot["vector_counts"] == {"failure_mode": 0, "company": 0, "thesis": 0}
        assert snapshot["safe_state"] is True


# ---------------------------------------------------------------------------
# 4. safe_state true/false combinations
# ---------------------------------------------------------------------------

class TestSafeStateCombinations:
    @pytest.mark.asyncio
    async def test_safe_state_false_when_shadow_flag_false(self, db, monkeypatch):
        from app.config import settings
        from app.services.similarity_observability_service import build_similarity_observability_snapshot

        monkeypatch.setattr(settings, "similarity_shadow", False)
        snapshot = await build_similarity_observability_snapshot(db)
        assert snapshot["flags"]["similarity_shadow"] is False
        assert snapshot["safe_state"] is False

    @pytest.mark.asyncio
    async def test_safe_state_false_when_escalated_shadow_row_exists(self, db):
        from sqlalchemy import update
        from app.db.models import DeliveryLedger
        from app.db.repositories.loop_repo import delivery_create
        from app.services.similarity_observability_service import build_similarity_observability_snapshot

        row = await delivery_create(
            db, content_key="x" * 64, target_key="OBS_ESCALATED",
            channel="similarity_shadow", content_hash="y" * 64,
        )
        assert row is not None
        await db.execute(
            update(DeliveryLedger).where(DeliveryLedger.id == row.id).values(status="delivered")
        )
        await db.commit()

        snapshot = await build_similarity_observability_snapshot(db)
        assert snapshot["shadow_escalated_count"] == 1
        assert snapshot["safe_state"] is False

    @pytest.mark.asyncio
    async def test_safe_state_false_when_live_similarity_notification_exists(self, db):
        from app.db.models import Notification
        from app.services.similarity_observability_service import build_similarity_observability_snapshot

        db.add(Notification(user_id="u1", kind="similarity", body_json={"x": 1}))
        await db.commit()

        snapshot = await build_similarity_observability_snapshot(db)
        assert snapshot["live_notification_count"] == 1
        assert snapshot["safe_state"] is False

    @pytest.mark.asyncio
    async def test_safe_state_true_when_all_conditions_met(self, db):
        from app.services.similarity_observability_service import build_similarity_observability_snapshot

        snapshot = await build_similarity_observability_snapshot(db)
        assert snapshot["safe_state"] is True


# ---------------------------------------------------------------------------
# 5. No secret leakage
# ---------------------------------------------------------------------------

class TestNoSecretLeakage:
    @pytest.mark.asyncio
    async def test_snapshot_contains_no_secret_like_values(self, db, monkeypatch):
        from app.config import settings
        from app.services.similarity_observability_service import build_similarity_observability_snapshot
        import json

        # Set some unrelated secrets on settings to prove they never leak through
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_live_super_secret_value")
        monkeypatch.setattr(settings, "supabase_jwt_secret", "jwt_super_secret_value")

        snapshot = await build_similarity_observability_snapshot(db)
        serialized = json.dumps(snapshot, default=str)
        assert "sk_live_super_secret_value" not in serialized
        assert "jwt_super_secret_value" not in serialized

    def test_flags_section_only_exposes_booleans_and_short_strings(self):
        from app.services.similarity_observability_service import _flags_section

        flags = _flags_section()
        assert set(flags.keys()) == {
            "similarity_build_enabled", "similarity_scoring_enabled",
            "similarity_targets_enabled", "similarity_shadow",
        }
        assert isinstance(flags["similarity_build_enabled"], bool)
        assert isinstance(flags["similarity_scoring_enabled"], bool)
        assert isinstance(flags["similarity_targets_enabled"], str)
        assert isinstance(flags["similarity_shadow"], bool)


# ---------------------------------------------------------------------------
# 6. Admin route response shape
# ---------------------------------------------------------------------------

class TestAdminRouteResponseShape:
    def test_admin_route_declared_and_delegates_to_observability_service(self):
        """Static check (app.api may not import cleanly on this Python version
        due to an unrelated pre-existing issue elsewhere in the import chain),
        so this verifies the route delegates to the right service by source
        inspection rather than firing an HTTP request."""
        import os

        # this file lives at tests/test_services/<file>.py -> project root is two dirs up
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        api_path = os.path.join(_project_root, "app", "api.py")
        with open(api_path, "r", encoding="utf-8") as f:
            source = f.read()

        assert '"/admin/similarity-status"' in source
        assert '"/admin/similarity/{ticker}"' in source
        assert "build_similarity_observability_snapshot" in source

    @pytest.mark.asyncio
    async def test_route_handler_function_returns_required_keys(self, db):
        """Exercise the exact function the route calls, confirming its return
        shape matches what the admin endpoint will serialize to JSON."""
        from app.services.similarity_observability_service import build_similarity_observability_snapshot

        result = await build_similarity_observability_snapshot(db)
        assert REQUIRED_KEYS.issubset(result.keys())
        assert isinstance(result["flags"], dict)
        assert isinstance(result["vector_counts"], dict)
        assert isinstance(result["edge_counts"], dict)
        assert isinstance(result["safe_state"], bool)
