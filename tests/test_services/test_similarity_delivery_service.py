"""
Tests — Similarity Delivery Wiring, Phase 11 · Slice 7.

Covers:
  1.  First-crossing detection
  2.  Strengthen detection
  3.  Weaken detection
  4.  Disappearance detection
  5.  Steady-state produces no event
  6.  Dedup behavior (same transition journaled twice -> one ledger row)
  7.  Shadow suppression / flag gating (default inert; explicit override)
  8.  No forecast/conviction imports
  9.  No source-table writes (delivery_ledger is the only table touched)
  10. Dossier similarity_context enrichment: present/absent per flags, safe empty state
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


def _edge(target_type="failure_mode", query_key="Q", candidate_key="C",
          score=0.5, floor_passed=True, user_id=None):
    return {
        "target_type": target_type, "query_key": query_key, "candidate_key": candidate_key,
        "score": score, "floor_passed": floor_passed, "user_id": user_id,
    }


# ---------------------------------------------------------------------------
# 1. First-crossing detection
# ---------------------------------------------------------------------------

class TestFirstCrossing:
    def test_classify_first_crossing_from_none(self):
        from app.services.similarity_delivery_service import classify_transition, TRANSITION_FIRST_CROSSING

        result = classify_transition(None, {"score": 0.6, "floor_passed": True})
        assert result == TRANSITION_FIRST_CROSSING

    def test_classify_first_crossing_from_below_floor(self):
        from app.services.similarity_delivery_service import classify_transition, TRANSITION_FIRST_CROSSING

        result = classify_transition(
            {"score": 0.3, "floor_passed": False}, {"score": 0.55, "floor_passed": True},
        )
        assert result == TRANSITION_FIRST_CROSSING

    def test_detect_transitions_first_crossing(self):
        from app.services.similarity_delivery_service import detect_similarity_transitions, TRANSITION_FIRST_CROSSING

        previous = [_edge(score=0.2, floor_passed=False)]
        current = [_edge(score=0.6, floor_passed=True)]
        events = detect_similarity_transitions(previous, current)
        assert len(events) == 1
        assert events[0]["transition"] == TRANSITION_FIRST_CROSSING
        assert events[0]["previous_score"] == 0.2
        assert events[0]["current_score"] == 0.6


# ---------------------------------------------------------------------------
# 2. Strengthen detection
# ---------------------------------------------------------------------------

class TestStrengthen:
    def test_classify_strengthened(self):
        from app.services.similarity_delivery_service import classify_transition, TRANSITION_STRENGTHENED

        result = classify_transition(
            {"score": 0.5, "floor_passed": True}, {"score": 0.65, "floor_passed": True},
        )
        assert result == TRANSITION_STRENGTHENED

    def test_small_delta_is_not_strengthened(self):
        from app.services.similarity_delivery_service import classify_transition

        result = classify_transition(
            {"score": 0.50, "floor_passed": True}, {"score": 0.55, "floor_passed": True},
        )
        assert result is None


# ---------------------------------------------------------------------------
# 3. Weaken detection
# ---------------------------------------------------------------------------

class TestWeaken:
    def test_classify_weakened(self):
        from app.services.similarity_delivery_service import classify_transition, TRANSITION_WEAKENED

        result = classify_transition(
            {"score": 0.65, "floor_passed": True}, {"score": 0.50, "floor_passed": True},
        )
        assert result == TRANSITION_WEAKENED


# ---------------------------------------------------------------------------
# 4. Disappearance detection
# ---------------------------------------------------------------------------

class TestDisappearance:
    def test_classify_disappeared_to_none(self):
        from app.services.similarity_delivery_service import classify_transition, TRANSITION_DISAPPEARED

        result = classify_transition({"score": 0.6, "floor_passed": True}, None)
        assert result == TRANSITION_DISAPPEARED

    def test_classify_disappeared_to_below_floor(self):
        from app.services.similarity_delivery_service import classify_transition, TRANSITION_DISAPPEARED

        result = classify_transition(
            {"score": 0.6, "floor_passed": True}, {"score": 0.2, "floor_passed": False},
        )
        assert result == TRANSITION_DISAPPEARED

    def test_detect_transitions_disappearance_when_edge_removed_entirely(self):
        from app.services.similarity_delivery_service import detect_similarity_transitions, TRANSITION_DISAPPEARED

        previous = [_edge(score=0.7, floor_passed=True)]
        current = []
        events = detect_similarity_transitions(previous, current)
        assert len(events) == 1
        assert events[0]["transition"] == TRANSITION_DISAPPEARED
        assert events[0]["current_score"] is None


# ---------------------------------------------------------------------------
# 5. Steady-state produces no event
# ---------------------------------------------------------------------------

class TestSteadyState:
    def test_unchanged_above_floor_match_produces_no_event(self):
        from app.services.similarity_delivery_service import detect_similarity_transitions

        previous = [_edge(score=0.55, floor_passed=True)]
        current = [_edge(score=0.56, floor_passed=True)]
        events = detect_similarity_transitions(previous, current)
        assert events == []

    def test_never_crossed_floor_produces_no_event(self):
        from app.services.similarity_delivery_service import detect_similarity_transitions

        previous = [_edge(score=0.1, floor_passed=False)]
        current = [_edge(score=0.15, floor_passed=False)]
        events = detect_similarity_transitions(previous, current)
        assert events == []


# ---------------------------------------------------------------------------
# 6. Dedup behavior
# ---------------------------------------------------------------------------

class TestDedup:
    @pytest.mark.asyncio
    async def test_same_transition_journaled_twice_creates_one_ledger_row(self, db):
        from app.services.similarity_delivery_service import record_similarity_transition_events
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        previous = [_edge(query_key="DEDUP_Q", candidate_key="DEDUP_C", score=0.2, floor_passed=False)]
        current = [_edge(query_key="DEDUP_Q", candidate_key="DEDUP_C", score=0.6, floor_passed=True)]

        await record_similarity_transition_events(db, previous, current, run_override=True)
        await db.commit()
        await record_similarity_transition_events(db, previous, current, run_override=True)
        await db.commit()

        count = (await db.execute(select(func.count()).select_from(DeliveryLedger))).scalar_one()
        assert count == 1

    @pytest.mark.asyncio
    async def test_different_transitions_create_separate_rows(self, db):
        from app.services.similarity_delivery_service import record_similarity_transition_events
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        previous = [_edge(query_key="MULTI_Q", candidate_key="MULTI_C1", score=0.2, floor_passed=False)]
        current = [_edge(query_key="MULTI_Q", candidate_key="MULTI_C1", score=0.6, floor_passed=True)]
        await record_similarity_transition_events(db, previous, current, run_override=True)

        previous2 = [_edge(query_key="MULTI_Q", candidate_key="MULTI_C2", score=0.2, floor_passed=False)]
        current2 = [_edge(query_key="MULTI_Q", candidate_key="MULTI_C2", score=0.7, floor_passed=True)]
        await record_similarity_transition_events(db, previous2, current2, run_override=True)
        await db.commit()

        count = (await db.execute(select(func.count()).select_from(DeliveryLedger))).scalar_one()
        assert count == 2


# ---------------------------------------------------------------------------
# 7. Shadow suppression / flag gating
# ---------------------------------------------------------------------------

class TestFlagGating:
    @pytest.mark.asyncio
    async def test_default_flags_are_inert_no_ledger_row(self, db):
        from app.services.similarity_delivery_service import record_similarity_transition_events
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        previous = [_edge(query_key="GATEQ", candidate_key="GATEC", score=0.2, floor_passed=False)]
        current = [_edge(query_key="GATEQ", candidate_key="GATEC", score=0.6, floor_passed=True)]

        # run_override=None -> falls back to settings, which default to
        # build=False/scoring=False/shadow=True -> not all True -> inert
        events = await record_similarity_transition_events(db, previous, current)
        await db.commit()

        assert events == []
        count = (await db.execute(select(func.count()).select_from(DeliveryLedger))).scalar_one()
        assert count == 0

    @pytest.mark.asyncio
    async def test_explicit_flags_all_true_via_settings_allows_journaling(self, db, monkeypatch):
        from app.config import settings
        from app.services.similarity_delivery_service import record_similarity_transition_events
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        monkeypatch.setattr(settings, "similarity_build_enabled", True)
        monkeypatch.setattr(settings, "similarity_scoring_enabled", True)
        monkeypatch.setattr(settings, "similarity_shadow", True)

        previous = [_edge(query_key="FLAGQ", candidate_key="FLAGC", score=0.2, floor_passed=False)]
        current = [_edge(query_key="FLAGQ", candidate_key="FLAGC", score=0.6, floor_passed=True)]

        events = await record_similarity_transition_events(db, previous, current)
        await db.commit()

        assert len(events) == 1
        count = (await db.execute(select(func.count()).select_from(DeliveryLedger))).scalar_one()
        assert count == 1

    @pytest.mark.asyncio
    async def test_partial_flags_still_inert(self, db, monkeypatch):
        from app.config import settings
        from app.services.similarity_delivery_service import record_similarity_transition_events
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        monkeypatch.setattr(settings, "similarity_build_enabled", True)
        monkeypatch.setattr(settings, "similarity_scoring_enabled", False)  # one flag still off
        monkeypatch.setattr(settings, "similarity_shadow", True)

        previous = [_edge(query_key="PARTQ", candidate_key="PARTC", score=0.2, floor_passed=False)]
        current = [_edge(query_key="PARTQ", candidate_key="PARTC", score=0.6, floor_passed=True)]

        events = await record_similarity_transition_events(db, previous, current)
        await db.commit()

        assert events == []
        count = (await db.execute(select(func.count()).select_from(DeliveryLedger))).scalar_one()
        assert count == 0

    @pytest.mark.asyncio
    async def test_journaled_row_is_pending_and_creates_no_notification(self, db):
        from app.services.similarity_delivery_service import (
            record_similarity_transition_events, SIMILARITY_DELIVERY_CHANNEL,
        )
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger, Notification

        previous = [_edge(query_key="SHADOWQ", candidate_key="SHADOWC", score=0.2, floor_passed=False)]
        current = [_edge(query_key="SHADOWQ", candidate_key="SHADOWC", score=0.6, floor_passed=True)]

        await record_similarity_transition_events(db, previous, current, run_override=True)
        await db.commit()

        row = (await db.execute(select(DeliveryLedger))).scalars().first()
        assert row is not None
        assert row.status == "pending"
        assert row.channel == SIMILARITY_DELIVERY_CHANNEL

        notif_count = (await db.execute(select(func.count()).select_from(Notification))).scalar_one()
        assert notif_count == 0


# ---------------------------------------------------------------------------
# 8. No forecast/conviction imports
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:
    @pytest.mark.parametrize("module_path", [
        "app.services.similarity_delivery_service",
        "app.services.dossier_similarity_enrichment",
    ])
    def test_module_has_no_forecast_or_conviction_import_statements(self, module_path):
        import ast
        import importlib
        import inspect

        mod = importlib.import_module(module_path)
        source = inspect.getsource(mod)
        tree = ast.parse(source)

        imported_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_names.append(node.module)
                imported_names.extend(alias.name for alias in node.names)

        forbidden = ["forecast", "conviction_engine", "recommendation", "notification_service"]
        for name in imported_names:
            lowered = name.lower()
            for term in forbidden:
                assert term not in lowered, (
                    f"forbidden import '{name}' (matches '{term}') found in {module_path}"
                )


# ---------------------------------------------------------------------------
# 9. No source-table writes
# ---------------------------------------------------------------------------

class TestNoSourceTableWrites:
    @pytest.mark.asyncio
    async def test_only_delivery_ledger_is_written(self, db):
        from app.services.similarity_delivery_service import record_similarity_transition_events
        from sqlalchemy import select
        from app.db.models import (
            SimilarityFeatureVector, SimilarityEdge, DossierFailureMode,
            CompanyDossier, ThesisVersion,
        )

        async def _dump(model):
            rows = (await db.execute(select(model))).scalars().all()
            cols = [c.name for c in model.__table__.columns]
            return sorted(tuple(getattr(r, c) for c in cols) for r in rows)

        before = {
            "sfv": await _dump(SimilarityFeatureVector),
            "edge": await _dump(SimilarityEdge),
            "fm": await _dump(DossierFailureMode),
            "company": await _dump(CompanyDossier),
            "thesis": await _dump(ThesisVersion),
        }

        previous = [_edge(query_key="NWBQ", candidate_key="NWBC", score=0.2, floor_passed=False)]
        current = [_edge(query_key="NWBQ", candidate_key="NWBC", score=0.6, floor_passed=True)]
        await record_similarity_transition_events(db, previous, current, run_override=True)
        await db.commit()

        after = {
            "sfv": await _dump(SimilarityFeatureVector),
            "edge": await _dump(SimilarityEdge),
            "fm": await _dump(DossierFailureMode),
            "company": await _dump(CompanyDossier),
            "thesis": await _dump(ThesisVersion),
        }

        assert before == after


# ---------------------------------------------------------------------------
# 10. Dossier similarity_context enrichment
# ---------------------------------------------------------------------------

class TestDossierEnrichment:
    @pytest.mark.asyncio
    async def test_similarity_context_present_and_safe_empty_by_default(self, db):
        from app.services.dossier_similarity_enrichment import get_full_dossier_with_similarity_context
        from app.db.repositories.dossier_repo import get_or_create_head, upsert_head

        await get_or_create_head(db, "ENRICHCO", company_name="Enrich Co")
        await upsert_head(db, "ENRICHCO", stance="bullish", conviction=0.6)
        await db.commit()

        result = await get_full_dossier_with_similarity_context(db, "ENRICHCO")
        assert "similarity_context" in result
        assert result["similarity_context"]["has_similarity"] is False
        assert result["similarity_context"]["matches"] == []
        assert "descriptive" in result["similarity_context"]["disclaimer"]
        # other keys untouched
        assert result["head"] is not None
        assert result["head"].stance == "bullish"

    @pytest.mark.asyncio
    async def test_similarity_context_populated_when_flags_enabled_and_data_exists(self, db, monkeypatch):
        from app.config import settings
        from app.services.dossier_similarity_enrichment import get_full_dossier_with_similarity_context
        from app.db.repositories.dossier_repo import upsert_failure_mode
        from app.db.models import HistoricalAnalog
        from app.services.similarity_feature_builder import build_failure_mode_feature_vector
        from app.services.similarity_scorer import build_failure_mode_similarity_edges

        analog = HistoricalAnalog(
            label="Probe Analog", episode="probe", mechanism="inventory_channel_correction",
            concern_tags=["supply_chain_risk"], sector="tech", business_model="hardware",
            disanalogy="n/a",
        )
        db.add(analog)
        await db.flush()
        fm_q = await upsert_failure_mode(db, "ENRICHQ", analog.id, sequence_stage=1)
        fm_c = await upsert_failure_mode(db, "ENRICHC", analog.id, sequence_stage=1)
        await db.commit()

        await build_failure_mode_feature_vector(db, fm_q.id)
        await build_failure_mode_feature_vector(db, fm_c.id)
        await db.commit()
        await build_failure_mode_similarity_edges(db, fm_q.id)
        await db.commit()

        monkeypatch.setattr(settings, "similarity_build_enabled", True)
        monkeypatch.setattr(settings, "similarity_scoring_enabled", True)

        result = await get_full_dossier_with_similarity_context(db, "ENRICHQ")
        ctx = result["similarity_context"]
        assert ctx["has_similarity"] is True
        assert len(ctx["matches"]) >= 1
        assert ctx["matches"][0]["key_disanalogy"]

    @pytest.mark.asyncio
    async def test_dossier_facets_unaffected_by_enrichment(self, db):
        from app.services.dossier_similarity_enrichment import get_full_dossier_with_similarity_context
        from app.db.repositories.dossier_repo import get_full_dossier, get_or_create_head, upsert_head

        await get_or_create_head(db, "UNCHANGEDCO", company_name="Unchanged Co")
        await upsert_head(db, "UNCHANGEDCO", stance="neutral", conviction=0.45)
        await db.commit()

        plain = await get_full_dossier(db, "UNCHANGEDCO")
        enriched = await get_full_dossier_with_similarity_context(db, "UNCHANGEDCO")

        for key in ("head", "debate", "dimensions", "catalysts", "variant", "durability", "failure_modes"):
            if key == "head":
                assert plain[key].stance == enriched[key].stance
                assert plain[key].conviction == enriched[key].conviction
            else:
                assert plain[key] == enriched[key]
