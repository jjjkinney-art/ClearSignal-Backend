"""
Tests — Similarity Feature Builder, Phase 11 · Slice 2 (T4 failure-mode only).

Covers:
  1.  Single failure-mode vector build (full substrate: fm + analog)
  2.  Ticker-level build (multiple failure modes for one ticker)
  3.  All-build with limit
  4.  Sparse substrate behavior (analog missing/unlinked)
  5.  Missing failure_mode_id -> None
  6.  analog_id preservation in categorical fields
  7.  Deterministic vector output (rebuild produces identical feature fields)
  8.  Idempotent upsert (rebuild updates same row, no duplicate)
  9.  No-write-back property (source tables unchanged)
  10. Null-session safety (all three public functions)
  11. No similarity_edge rows created by the builder
"""

from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="module")
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

async def _seed_analog(db, **overrides) -> object:
    from app.db.models import HistoricalAnalog

    defaults = dict(
        label="Cisco 2000 Inventory Glut",
        episode="dot-com inventory correction",
        entity_ticker="CSCO",
        sector="tech",
        business_model="hardware",
        quality_rating="strong",
        mechanism="inventory_channel_correction",
        concern_tags=["supply_chain_risk", "capex_cycle"],
        valuation_regime="peak_multiple",
        growth_phase="hypergrowth",
        macro_regime="hiking",
        event_start=date(2000, 3, 1),
        event_end=date(2001, 9, 1),
        drawdown_pct=0.86,
        time_to_trough_days=400,
        time_to_recover_days=5000,
        outcome_summary="Severe inventory writedown.",
        disanalogy="Different customer base.",
        why_relevant="Shared capex-cycle exposure.",
    )
    defaults.update(overrides)
    row = HistoricalAnalog(**defaults)
    db.add(row)
    await db.flush()
    return row


async def _seed_failure_mode(db, *, ticker="AAPL", analog_id, **overrides) -> object:
    from app.db.repositories.dossier_repo import upsert_failure_mode

    kwargs = dict(
        sequence_stage=2,
        stage_evidence="Stage 2 evidence text.",
        relevance_at_match=0.71,
    )
    kwargs.update(overrides)
    return await upsert_failure_mode(db, ticker, analog_id, **kwargs)


# ---------------------------------------------------------------------------
# 1. Single failure-mode vector build (full substrate)
# ---------------------------------------------------------------------------

class TestSingleBuild:
    @pytest.mark.asyncio
    async def test_build_with_full_substrate(self, db):
        from app.services.similarity_feature_builder import build_failure_mode_feature_vector

        analog = await _seed_analog(db)
        fm = await _seed_failure_mode(db, ticker="AAPL", analog_id=analog.id)
        await db.commit()

        vec = await build_failure_mode_feature_vector(db, fm.id)
        assert vec is not None
        assert vec.target_type == "failure_mode"
        assert vec.entity_key == fm.id
        assert vec.categorical["ticker"] == "AAPL"
        assert vec.categorical["analog_id"] == analog.id
        assert vec.categorical["failure_mode_label"] == "Cisco 2000 Inventory Glut"
        assert vec.categorical["mechanism"] == "inventory_channel_correction"
        assert "supply_chain_risk" in vec.tag_set
        assert "capex_cycle" in vec.tag_set
        assert vec.numeric["sequence_stage"] == 2.0
        assert abs(vec.numeric["relevance_at_match"] - 0.71) < 1e-6
        assert "AAPL" in vec.text_anchor
        assert "Cisco 2000 Inventory Glut" in vec.text_anchor
        assert vec.source_versions["analog_id"] == analog.id


# ---------------------------------------------------------------------------
# 2. Ticker-level build
# ---------------------------------------------------------------------------

class TestTickerLevelBuild:
    @pytest.mark.asyncio
    async def test_builds_all_failure_modes_for_ticker(self, db):
        from app.services.similarity_feature_builder import (
            build_failure_mode_feature_vectors_for_ticker,
        )

        analog1 = await _seed_analog(db, label="Analog Ticker A1")
        analog2 = await _seed_analog(db, label="Analog Ticker A2", mechanism="demand_air_pocket")
        await _seed_failure_mode(db, ticker="MSFT", analog_id=analog1.id, sequence_stage=1)
        await _seed_failure_mode(db, ticker="MSFT", analog_id=analog2.id, sequence_stage=3)
        await _seed_failure_mode(db, ticker="OTHER", analog_id=analog1.id)
        await db.commit()

        vecs = await build_failure_mode_feature_vectors_for_ticker(db, "MSFT")
        assert len(vecs) == 2
        tickers = {v.categorical["ticker"] for v in vecs}
        assert tickers == {"MSFT"}

    @pytest.mark.asyncio
    async def test_ticker_with_no_failure_modes_returns_empty(self, db):
        from app.services.similarity_feature_builder import (
            build_failure_mode_feature_vectors_for_ticker,
        )

        vecs = await build_failure_mode_feature_vectors_for_ticker(db, "NOPE_TICKER")
        assert vecs == []


# ---------------------------------------------------------------------------
# 3. All-build with limit
# ---------------------------------------------------------------------------

class TestAllBuild:
    @pytest.mark.asyncio
    async def test_build_all_respects_limit(self, db):
        from app.services.similarity_feature_builder import (
            build_failure_mode_feature_vectors_for_all,
        )

        analog = await _seed_analog(db, label="Analog Limit Test")
        for i in range(5):
            await _seed_failure_mode(db, ticker=f"LIM{i}", analog_id=analog.id)
        await db.commit()

        limited = await build_failure_mode_feature_vectors_for_all(db, limit=3)
        assert len(limited) == 3

    @pytest.mark.asyncio
    async def test_build_all_without_limit_covers_existing_rows(self, db):
        from app.services.similarity_feature_builder import (
            build_failure_mode_feature_vectors_for_all,
        )
        from sqlalchemy import select, func
        from app.db.models import DossierFailureMode

        total = (await db.execute(select(func.count()).select_from(DossierFailureMode))).scalar_one()
        all_vecs = await build_failure_mode_feature_vectors_for_all(db)
        assert len(all_vecs) == total


# ---------------------------------------------------------------------------
# 4. Sparse substrate behavior (analog missing/unlinked)
# ---------------------------------------------------------------------------

class TestSparseSubstrate:
    @pytest.mark.asyncio
    async def test_sparse_vector_when_analog_missing(self, db):
        """analog_id points nowhere — builder must not raise; returns sparse vector."""
        from app.services.similarity_feature_builder import build_failure_mode_feature_vector
        from app.db.repositories.dossier_repo import upsert_failure_mode

        fm = await upsert_failure_mode(
            db, "SPARSE_CO", "nonexistent-analog-id",
            sequence_stage=1, relevance_at_match=0.5,
        )
        await db.commit()

        vec = await build_failure_mode_feature_vector(db, fm.id)
        assert vec is not None
        assert vec.categorical["ticker"] == "SPARSE_CO"
        assert vec.categorical["failure_mode_label"] == ""
        assert vec.categorical["mechanism"] == ""
        assert vec.tag_set == []
        assert vec.numeric["sequence_stage"] == 1.0
        assert "analog record unavailable" in vec.text_anchor


# ---------------------------------------------------------------------------
# 5. Missing failure_mode_id -> None
# ---------------------------------------------------------------------------

class TestMissingFailureMode:
    @pytest.mark.asyncio
    async def test_missing_failure_mode_id_returns_none(self, db):
        from app.services.similarity_feature_builder import build_failure_mode_feature_vector

        result = await build_failure_mode_feature_vector(db, "does-not-exist-id")
        assert result is None


# ---------------------------------------------------------------------------
# 6. analog_id preservation
# ---------------------------------------------------------------------------

class TestAnalogIdPreservation:
    @pytest.mark.asyncio
    async def test_analog_id_present_in_categorical_and_source_versions(self, db):
        from app.services.similarity_feature_builder import build_failure_mode_feature_vector

        analog = await _seed_analog(db, label="Analog Preserve Test")
        fm = await _seed_failure_mode(db, ticker="PRSV", analog_id=analog.id)
        await db.commit()

        vec = await build_failure_mode_feature_vector(db, fm.id)
        assert vec.categorical["analog_id"] == analog.id
        assert vec.source_versions["analog_id"] == analog.id


# ---------------------------------------------------------------------------
# 7. Deterministic vector output
# ---------------------------------------------------------------------------

class TestDeterminism:
    @pytest.mark.asyncio
    async def test_rebuild_produces_identical_feature_fields(self, db):
        from app.services.similarity_feature_builder import build_failure_mode_feature_vector

        analog = await _seed_analog(db, label="Analog Determinism Test")
        fm = await _seed_failure_mode(db, ticker="DETM", analog_id=analog.id)
        await db.commit()

        v1 = await build_failure_mode_feature_vector(db, fm.id)
        await db.commit()
        v2 = await build_failure_mode_feature_vector(db, fm.id)
        await db.commit()

        assert v1.categorical == v2.categorical
        assert v1.tag_set == v2.tag_set
        assert v1.numeric == v2.numeric
        assert v1.text_anchor == v2.text_anchor


# ---------------------------------------------------------------------------
# 8. Idempotent upsert
# ---------------------------------------------------------------------------

class TestIdempotentUpsert:
    @pytest.mark.asyncio
    async def test_rebuild_updates_same_row_no_duplicate(self, db):
        from app.services.similarity_feature_builder import build_failure_mode_feature_vector
        from sqlalchemy import select, func
        from app.db.models import SimilarityFeatureVector

        analog = await _seed_analog(db, label="Analog Idempotent Test")
        fm = await _seed_failure_mode(db, ticker="IDEM", analog_id=analog.id, sequence_stage=1)
        await db.commit()

        v1 = await build_failure_mode_feature_vector(db, fm.id)
        await db.commit()
        first_id = v1.id

        # Advance stage, rebuild
        fm.sequence_stage = 4
        await db.commit()
        v2 = await build_failure_mode_feature_vector(db, fm.id)
        await db.commit()

        assert v2.id == first_id
        assert v2.numeric["sequence_stage"] == 4.0

        count = (
            await db.execute(
                select(func.count()).select_from(SimilarityFeatureVector).where(
                    SimilarityFeatureVector.entity_key == fm.id
                )
            )
        ).scalar_one()
        assert count == 1


# ---------------------------------------------------------------------------
# 9. No-write-back property
# ---------------------------------------------------------------------------

class TestNoWriteBack:
    @pytest.mark.asyncio
    async def test_source_tables_unchanged_after_build(self, db):
        from app.services.similarity_feature_builder import (
            build_failure_mode_feature_vector,
            build_failure_mode_feature_vectors_for_ticker,
            build_failure_mode_feature_vectors_for_all,
        )
        from sqlalchemy import select
        from app.db.models import (
            DossierFailureMode, HistoricalAnalog, CompanyDossier,
            CrossExposure, ThesisVersion,
        )

        analog = await _seed_analog(db, label="Analog No-Write-Back Test")
        fm = await _seed_failure_mode(db, ticker="NWB", analog_id=analog.id)

        dossier = CompanyDossier(ticker="NWB", company_name="No Write Back Inc")
        db.add(dossier)
        cross = CrossExposure(ticker_a="NWB", ticker_b="OTHERCO", strength=0.4)
        db.add(cross)
        thesis = ThesisVersion(
            ticker="NWB", company_name="No Write Back Inc",
            directional_stance="neutral", confidence_score=0.5,
        )
        db.add(thesis)
        await db.commit()

        async def _dump(model):
            rows = (await db.execute(select(model))).scalars().all()
            cols = [c.name for c in model.__table__.columns]
            return sorted(
                tuple(getattr(r, c) for c in cols) for r in rows
            )

        before = {
            "fm": await _dump(DossierFailureMode),
            "analog": await _dump(HistoricalAnalog),
            "dossier": await _dump(CompanyDossier),
            "cross": await _dump(CrossExposure),
            "thesis": await _dump(ThesisVersion),
        }

        await build_failure_mode_feature_vector(db, fm.id)
        await build_failure_mode_feature_vectors_for_ticker(db, "NWB")
        await build_failure_mode_feature_vectors_for_all(db)
        await db.commit()

        after = {
            "fm": await _dump(DossierFailureMode),
            "analog": await _dump(HistoricalAnalog),
            "dossier": await _dump(CompanyDossier),
            "cross": await _dump(CrossExposure),
            "thesis": await _dump(ThesisVersion),
        }

        assert before == after


# ---------------------------------------------------------------------------
# 10. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_build_single_null_session(self):
        from app.services.similarity_feature_builder import build_failure_mode_feature_vector

        result = await build_failure_mode_feature_vector(None, "any-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_build_for_ticker_null_session(self):
        from app.services.similarity_feature_builder import (
            build_failure_mode_feature_vectors_for_ticker,
        )

        result = await build_failure_mode_feature_vectors_for_ticker(None, "AAPL")
        assert result == []

    @pytest.mark.asyncio
    async def test_build_for_all_null_session(self):
        from app.services.similarity_feature_builder import (
            build_failure_mode_feature_vectors_for_all,
        )

        result = await build_failure_mode_feature_vectors_for_all(None)
        assert result == []


# ---------------------------------------------------------------------------
# 11. No similarity_edge rows created
# ---------------------------------------------------------------------------

class TestNoEdgesCreated:
    @pytest.mark.asyncio
    async def test_builder_creates_no_edges(self, db):
        from app.services.similarity_feature_builder import (
            build_failure_mode_feature_vector,
            build_failure_mode_feature_vectors_for_ticker,
            build_failure_mode_feature_vectors_for_all,
        )
        from sqlalchemy import select, func
        from app.db.models import SimilarityEdge

        analog = await _seed_analog(db, label="Analog No-Edges Test")
        fm = await _seed_failure_mode(db, ticker="NOEDGE", analog_id=analog.id)
        await db.commit()

        await build_failure_mode_feature_vector(db, fm.id)
        await build_failure_mode_feature_vectors_for_ticker(db, "NOEDGE")
        await build_failure_mode_feature_vectors_for_all(db)
        await db.commit()

        count = (await db.execute(select(func.count()).select_from(SimilarityEdge))).scalar_one()
        assert count == 0
