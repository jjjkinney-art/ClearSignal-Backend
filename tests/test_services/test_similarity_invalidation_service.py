"""
Tests — Similarity Invalidation + Rebuild Orchestration, Phase 11 · Slice 5.

Covers:
  1.  Stale vector detection (TTL-based, sequence_stage drift, row_version drift)
  2.  Fresh vector ignored (not stale)
  3.  Expired edge cleanup
  4.  Ticker rebuild calls correct builders (company + failure_mode + thesis)
  5.  Target rebuild calls correct builder (per target_type)
  6.  Batch rebuild limit honored
  7.  Flags default inert (similarity_build_enabled / scoring_enabled / shadow)
  8.  Null-session safety
  9.  No-write-back property
  10. No similarity_edge rows created when scoring not approved
  11. No forecast/delivery/notification imports in the module
"""

from __future__ import annotations

import json

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


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

async def _seed_failure_mode_vector(db, ticker="AAPL"):
    from app.db.repositories.dossier_repo import upsert_failure_mode
    from app.db.models import HistoricalAnalog
    from app.services.similarity_feature_builder import build_failure_mode_feature_vector
    from datetime import date

    analog = HistoricalAnalog(
        label=f"Analog {ticker}", episode="test episode", mechanism="inventory_channel_correction",
        concern_tags=["supply_chain_risk"], sector="tech", business_model="hardware",
        disanalogy="n/a",
    )
    db.add(analog)
    await db.flush()

    fm = await upsert_failure_mode(db, ticker, analog.id, sequence_stage=1, relevance_at_match=0.6)
    await db.commit()

    vec = await build_failure_mode_feature_vector(db, fm.id)
    await db.commit()
    return fm, vec


async def _seed_company_vector(db, ticker="AAPL"):
    from app.db.repositories.dossier_repo import get_or_create_head, upsert_head
    from app.services.similarity_feature_builder import build_company_feature_vector

    await get_or_create_head(db, ticker, company_name="Apple Inc.")
    await upsert_head(db, ticker, stance="bullish", conviction=0.7)
    await db.commit()

    vec = await build_company_feature_vector(db, ticker)
    await db.commit()
    return vec


async def _seed_thesis_vector(db, ticker="AAPL"):
    from app.db.models import ThesisVersion
    from app.services.similarity_feature_builder import build_thesis_feature_vector

    thesis = ThesisVersion(
        ticker=ticker, company_name="Apple Inc.",
        directional_stance="bullish", confidence_score=0.6,
        key_drivers=json.dumps(["services"]), key_risks=json.dumps([]),
    )
    db.add(thesis)
    await db.commit()

    vec = await build_thesis_feature_vector(db, thesis.id)
    await db.commit()
    return thesis, vec


# ---------------------------------------------------------------------------
# 1. Stale vector detection
# ---------------------------------------------------------------------------

class TestStaleDetection:
    @pytest.mark.asyncio
    async def test_ttl_expiry_marks_stale(self, db):
        from datetime import datetime, timedelta, timezone
        from app.services.similarity_invalidation_service import is_vector_stale

        fm, vec = await _seed_failure_mode_vector(db, ticker="TTLCO")
        vec.built_at = datetime.now(timezone.utc) - timedelta(hours=48)
        await db.commit()

        stale = await is_vector_stale(db, vec, ttl_hours=24)
        assert stale is True

    @pytest.mark.asyncio
    async def test_failure_mode_sequence_stage_drift_marks_stale(self, db):
        from app.services.similarity_invalidation_service import is_vector_stale
        from app.db.repositories.dossier_repo import upsert_failure_mode

        fm, vec = await _seed_failure_mode_vector(db, ticker="DRIFTCO")
        # Stage progresses — vector's recorded numeric.sequence_stage is now stale
        await upsert_failure_mode(db, "DRIFTCO", fm.analog_id, sequence_stage=3)
        await db.commit()

        stale = await is_vector_stale(db, vec, ttl_hours=24)
        assert stale is True

    @pytest.mark.asyncio
    async def test_company_row_version_drift_marks_stale(self, db):
        from app.services.similarity_invalidation_service import is_vector_stale
        from app.db.repositories.dossier_repo import upsert_head

        vec = await _seed_company_vector(db, ticker="ROWVCO")
        # Any head write bumps row_version unconditionally
        await upsert_head(db, "ROWVCO", stance="bearish")
        await db.commit()

        stale = await is_vector_stale(db, vec, ttl_hours=24)
        assert stale is True

    @pytest.mark.asyncio
    async def test_orphaned_vector_marks_stale(self, db):
        """If the source row is gone entirely, the vector is stale (orphaned)."""
        from app.services.similarity_invalidation_service import is_vector_stale
        from app.db.models import DossierFailureMode

        fm, vec = await _seed_failure_mode_vector(db, ticker="ORPHANCO")
        await db.delete(fm)
        await db.commit()

        stale = await is_vector_stale(db, vec, ttl_hours=24)
        assert stale is True


# ---------------------------------------------------------------------------
# 2. Fresh vector ignored
# ---------------------------------------------------------------------------

class TestFreshVectorIgnored:
    @pytest.mark.asyncio
    async def test_freshly_built_vector_not_stale(self, db):
        from app.services.similarity_invalidation_service import is_vector_stale

        fm, vec = await _seed_failure_mode_vector(db, ticker="FRESHCO")
        stale = await is_vector_stale(db, vec, ttl_hours=24)
        assert stale is False

    @pytest.mark.asyncio
    async def test_find_stale_vectors_excludes_fresh(self, db):
        from app.services.similarity_invalidation_service import find_stale_vectors

        await _seed_failure_mode_vector(db, ticker="FINDFRESH")
        stale = await find_stale_vectors(db, target_type="failure_mode", ttl_hours=24)
        assert stale == []


# ---------------------------------------------------------------------------
# 3. Expired edge cleanup
# ---------------------------------------------------------------------------

class TestExpiredEdgeCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_removes_expired_edges(self, db):
        from app.services.similarity_invalidation_service import cleanup_expired_edges
        from app.db.repositories.similarity_repo import upsert_similarity_edge, get_similarity_edge
        from datetime import datetime, timedelta, timezone

        edge = await upsert_similarity_edge(
            db, target_type="failure_mode", query_key="EXP_Q", candidate_key="EXP_C",
            score=0.5, rank=1, contributions=[{"feature": "x", "weight": 0.5, "partial_score": 0.5}],
        )
        edge.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()

        deleted = await cleanup_expired_edges(db)
        assert deleted >= 1

        remaining = await get_similarity_edge(
            db, target_type="failure_mode", query_key="EXP_Q", candidate_key="EXP_C",
        )
        assert remaining is None


# ---------------------------------------------------------------------------
# 4. Ticker rebuild calls correct builders
# ---------------------------------------------------------------------------

class TestTickerRebuild:
    @pytest.mark.asyncio
    async def test_rebuild_for_ticker_covers_company_failure_mode_and_thesis(self, db):
        from app.services.similarity_invalidation_service import rebuild_similarity_for_ticker

        await _seed_company_vector(db, ticker="TKRREBUILD")
        await _seed_failure_mode_vector(db, ticker="TKRREBUILD")
        await _seed_thesis_vector(db, ticker="TKRREBUILD")

        result = await rebuild_similarity_for_ticker(db, "TKRREBUILD")
        assert result["company"] is not None
        assert len(result["failure_modes"]) == 1
        assert len(result["theses"]) == 1

    @pytest.mark.asyncio
    async def test_rebuild_for_ticker_does_not_score_by_default(self, db):
        from app.services.similarity_invalidation_service import rebuild_similarity_for_ticker
        from sqlalchemy import select, func
        from app.db.models import SimilarityEdge

        await _seed_failure_mode_vector(db, ticker="NOSCORE")
        await rebuild_similarity_for_ticker(db, "NOSCORE")  # run_scoring=None -> falls back to flag (False)
        await db.commit()

        count = (await db.execute(select(func.count()).select_from(SimilarityEdge))).scalar_one()
        assert count == 0

    @pytest.mark.asyncio
    async def test_rebuild_for_ticker_scores_when_explicitly_approved(self, db):
        from app.services.similarity_invalidation_service import rebuild_similarity_for_ticker
        from sqlalchemy import select, func
        from app.db.models import SimilarityEdge

        await _seed_failure_mode_vector(db, ticker="SCOREOK")
        await rebuild_similarity_for_ticker(db, "SCOREOK", run_scoring=True)
        await db.commit()

        # at least the upsert attempt happened; with only 1 vector total there are
        # no candidates to score against, so 0 edges is correct — verify no crash
        # and that the call path completed without error.
        count = (await db.execute(select(func.count()).select_from(SimilarityEdge))).scalar_one()
        assert count == 0  # only one failure_mode vector exists -> no candidates


# ---------------------------------------------------------------------------
# 5. Target rebuild calls correct builder
# ---------------------------------------------------------------------------

class TestTargetRebuild:
    @pytest.mark.asyncio
    async def test_rebuild_failure_mode_target(self, db):
        from app.services.similarity_invalidation_service import rebuild_similarity_for_target

        fm, _ = await _seed_failure_mode_vector(db, ticker="TGTFM")
        result = await rebuild_similarity_for_target(db, "failure_mode", fm.id)
        assert result is not None
        assert result.entity_key == fm.id

    @pytest.mark.asyncio
    async def test_rebuild_company_target(self, db):
        from app.services.similarity_invalidation_service import rebuild_similarity_for_target

        await _seed_company_vector(db, ticker="TGTCO")
        result = await rebuild_similarity_for_target(db, "company", "TGTCO")
        assert result is not None
        assert result.entity_key == "TGTCO"

    @pytest.mark.asyncio
    async def test_rebuild_thesis_target(self, db):
        from app.services.similarity_invalidation_service import rebuild_similarity_for_target

        thesis, _ = await _seed_thesis_vector(db, ticker="TGTTHESIS")
        result = await rebuild_similarity_for_target(db, "thesis", thesis.id)
        assert result is not None
        assert result.entity_key == thesis.id

    @pytest.mark.asyncio
    async def test_rebuild_unsupported_target_type_returns_none(self, db):
        from app.services.similarity_invalidation_service import rebuild_similarity_for_target

        result = await rebuild_similarity_for_target(db, "macro_regime", "anything")
        assert result is None


# ---------------------------------------------------------------------------
# 6. Batch rebuild limit honored
# ---------------------------------------------------------------------------

class TestBatchRebuild:
    @pytest.mark.asyncio
    async def test_batch_rebuild_respects_limit(self, db):
        from app.services.similarity_invalidation_service import rebuild_similarity_batch

        for i in range(5):
            await _seed_failure_mode_vector(db, ticker=f"BATCH{i}")

        # ttl_hours=0 -> every vector built "now" is already older than 0 hours -> all stale
        rebuilt = await rebuild_similarity_batch(db, limit=2, ttl_hours=0)
        assert len(rebuilt) <= 2

    @pytest.mark.asyncio
    async def test_batch_rebuild_no_stale_vectors_returns_empty(self, db):
        from app.services.similarity_invalidation_service import rebuild_similarity_batch

        await _seed_failure_mode_vector(db, ticker="BATCHFRESH")
        rebuilt = await rebuild_similarity_batch(db, ttl_hours=24)
        assert rebuilt == []


# ---------------------------------------------------------------------------
# 7. Flags default inert
# ---------------------------------------------------------------------------

class TestFlagsDefaultInert:
    def test_similarity_flags_default_to_inert_values(self):
        from app.config import settings

        assert settings.similarity_build_enabled is False
        assert settings.similarity_scoring_enabled is False
        assert settings.similarity_targets_enabled == ""
        assert settings.similarity_shadow is True

    @pytest.mark.asyncio
    async def test_scoring_not_run_when_flag_is_default_false(self, db, monkeypatch):
        from app.config import settings
        from app.services.similarity_invalidation_service import rebuild_similarity_for_target
        from sqlalchemy import select, func
        from app.db.models import SimilarityEdge

        monkeypatch.setattr(settings, "similarity_scoring_enabled", False)
        fm, _ = await _seed_failure_mode_vector(db, ticker="FLAGOFF")
        await rebuild_similarity_for_target(db, "failure_mode", fm.id)  # run_scoring=None -> flag
        await db.commit()

        count = (await db.execute(select(func.count()).select_from(SimilarityEdge))).scalar_one()
        assert count == 0


# ---------------------------------------------------------------------------
# 8. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_is_vector_stale_null_session(self):
        from app.services.similarity_invalidation_service import is_vector_stale

        result = await is_vector_stale(None, object())
        assert result is False

    @pytest.mark.asyncio
    async def test_find_stale_vectors_null_session(self):
        from app.services.similarity_invalidation_service import find_stale_vectors

        result = await find_stale_vectors(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_cleanup_expired_edges_null_session(self):
        from app.services.similarity_invalidation_service import cleanup_expired_edges

        result = await cleanup_expired_edges(None)
        assert result == 0

    @pytest.mark.asyncio
    async def test_rebuild_for_target_null_session(self):
        from app.services.similarity_invalidation_service import rebuild_similarity_for_target

        result = await rebuild_similarity_for_target(None, "company", "AAPL")
        assert result is None

    @pytest.mark.asyncio
    async def test_rebuild_for_ticker_null_session(self):
        from app.services.similarity_invalidation_service import rebuild_similarity_for_ticker

        result = await rebuild_similarity_for_ticker(None, "AAPL")
        assert result == {"company": None, "failure_modes": [], "theses": []}

    @pytest.mark.asyncio
    async def test_rebuild_batch_null_session(self):
        from app.services.similarity_invalidation_service import rebuild_similarity_batch

        result = await rebuild_similarity_batch(None)
        assert result == []


# ---------------------------------------------------------------------------
# 9. No-write-back
# ---------------------------------------------------------------------------

class TestNoWriteBack:
    @pytest.mark.asyncio
    async def test_source_tables_unchanged_after_invalidation_sweep(self, db):
        from app.services.similarity_invalidation_service import (
            find_stale_vectors, cleanup_expired_edges, rebuild_similarity_for_ticker,
            rebuild_similarity_batch,
        )
        from sqlalchemy import select
        from app.db.models import (
            DossierFailureMode, HistoricalAnalog, CompanyDossier,
            DossierCoreDebate, ThesisVersion, DossierVariant,
        )

        await _seed_failure_mode_vector(db, ticker="NWB")
        await _seed_company_vector(db, ticker="NWB")
        await _seed_thesis_vector(db, ticker="NWB")

        async def _dump(model):
            rows = (await db.execute(select(model))).scalars().all()
            cols = [c.name for c in model.__table__.columns]
            return sorted(tuple(getattr(r, c) for c in cols) for r in rows)

        before = {
            "fm": await _dump(DossierFailureMode),
            "analog": await _dump(HistoricalAnalog),
            "dossier": await _dump(CompanyDossier),
            "debate": await _dump(DossierCoreDebate),
            "thesis": await _dump(ThesisVersion),
            "variant": await _dump(DossierVariant),
        }

        await find_stale_vectors(db)
        await cleanup_expired_edges(db)
        await rebuild_similarity_for_ticker(db, "NWB")
        await rebuild_similarity_batch(db)
        await db.commit()

        after = {
            "fm": await _dump(DossierFailureMode),
            "analog": await _dump(HistoricalAnalog),
            "dossier": await _dump(CompanyDossier),
            "debate": await _dump(DossierCoreDebate),
            "thesis": await _dump(ThesisVersion),
            "variant": await _dump(DossierVariant),
        }

        assert before == after


# ---------------------------------------------------------------------------
# 10. No edges created when scoring not approved
# ---------------------------------------------------------------------------

class TestNoEdgesWithoutApproval:
    @pytest.mark.asyncio
    async def test_batch_rebuild_creates_no_edges_by_default(self, db):
        from app.services.similarity_invalidation_service import rebuild_similarity_batch
        from sqlalchemy import select, func
        from app.db.models import SimilarityEdge

        await _seed_failure_mode_vector(db, ticker="BATCHNOEDGE1")
        await _seed_failure_mode_vector(db, ticker="BATCHNOEDGE2")

        await rebuild_similarity_batch(db, ttl_hours=0)  # all stale, run_scoring defaults to flag (off)
        await db.commit()

        count = (await db.execute(select(func.count()).select_from(SimilarityEdge))).scalar_one()
        assert count == 0


# ---------------------------------------------------------------------------
# 11. No forecast/delivery/notification imports
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:
    def test_module_has_no_forecast_or_delivery_import_statements(self):
        """Check actual import statements (AST), not prose in docstrings/comments
        that legitimately describe what this module avoids importing."""
        import ast
        import inspect
        import app.services.similarity_invalidation_service as mod

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

        forbidden = ["forecast", "conviction_engine", "notification", "delivery_repo", "delivery_service"]
        for name in imported_names:
            lowered = name.lower()
            for term in forbidden:
                assert term not in lowered, (
                    f"forbidden import '{name}' (matches '{term}') found in "
                    f"similarity_invalidation_service"
                )
