"""
Tests — Similarity Feature Builder, Phase 11 · Slice 4 (T1 company, T2 thesis).

Covers:
  1.  Company (T1) vector build with full substrate
  2.  Company (T1) sparse vector when facets (debate/moat/durability/exposures) missing
  3.  Company (T1) missing head -> None
  4.  Thesis (T2) vector build with full substrate
  5.  Thesis (T2) sparse vector when facets (debate/variant/durability) missing
  6.  Thesis (T2) missing thesis_version_id -> None
  7.  Deterministic output (both targets)
  8.  Idempotent upsert (both targets)
  9.  No-write-back property (both targets)
  10. Null-session safety (all four public functions)
  11. build_company_feature_vectors_for_all / build_thesis_feature_vectors_for_all
  12. No similarity_edge rows created
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

async def _seed_company_full(db, ticker="AAPL"):
    from app.db.repositories.dossier_repo import (
        get_or_create_head, upsert_head, write_debate, upsert_dimension, write_durability,
    )
    from app.db.models import CrossExposure

    head = await get_or_create_head(db, ticker, company_name="Apple Inc.")
    await upsert_head(
        db, ticker,
        stance="bullish", conviction=0.72, primary_concern="margin_pressure",
        global_confidence=0.8, staleness_state="fresh",
    )
    await write_debate(
        db, ticker,
        question="Can AAPL sustain services growth?",
        bull_pole="Services mix expands margins.",
        bear_pole="Hardware cyclicality dominates.",
        current_lean="bull", confidence=0.65,
    )
    await upsert_dimension(db, ticker, "ecosystem_lockin", strength="strong", trend="stable", confidence=0.7)
    await upsert_dimension(db, ticker, "switching_costs", strength="moderate", trend="stable", confidence=0.6)
    await write_durability(
        db, ticker,
        cycle_position="mid", conviction_trend="rising", horizon_hint="secular",
    )
    cross = CrossExposure(
        ticker_a=ticker, ticker_b="MSFT",
        shared_concerns=json.dumps(["regulatory_risk", "ai_adoption_risk"]),
        exposure_type="thematic", strength=0.5,
    )
    db.add(cross)
    await db.commit()
    return head


async def _seed_thesis_full(db, ticker="AAPL"):
    from app.db.models import ThesisVersion
    from app.db.repositories.dossier_repo import write_debate, write_variant, write_durability

    thesis = ThesisVersion(
        ticker=ticker, company_name="Apple Inc.",
        directional_stance="bullish", confidence_score=0.68,
        bull_thesis="Services growth.", bear_thesis="Hardware cyclicality.",
        key_drivers=json.dumps(["services_growth", "buybacks"]),
        key_risks=json.dumps(["china_exposure"]),
    )
    db.add(thesis)
    await db.flush()

    await write_debate(
        db, ticker,
        question="Can AAPL sustain services growth?",
        bull_pole="Services mix expands margins.",
        bear_pole="Hardware cyclicality dominates.",
        current_lean="bull", confidence=0.65,
    )
    await write_variant(
        db, ticker,
        divergences=[
            {"dimension": "margin_trajectory", "consensus_view": "flat", "clearsignal_view": "expanding",
             "direction": "bullish", "conviction": 0.6},
        ],
        confidence=0.55,
    )
    await write_durability(db, ticker, cycle_position="mid", horizon_hint="secular")
    await db.commit()
    return thesis


# ---------------------------------------------------------------------------
# 1. Company vector build (full substrate)
# ---------------------------------------------------------------------------

class TestCompanyFullBuild:
    @pytest.mark.asyncio
    async def test_build_company_with_full_substrate(self, db):
        from app.services.similarity_feature_builder import build_company_feature_vector

        await _seed_company_full(db, ticker="AAPL")
        vec = await build_company_feature_vector(db, "AAPL")

        assert vec is not None
        assert vec.target_type == "company"
        assert vec.entity_key == "AAPL"
        assert vec.categorical["stance"] == "bullish"
        assert vec.categorical["core_debate_lean"] == "bull"
        assert vec.categorical["durability_cycle_position"] == "mid"
        assert "ecosystem_lockin" in vec.categorical["moat_axes_present"]
        assert "regulatory_risk" in vec.tag_set
        assert "ai_adoption_risk" in vec.tag_set
        assert vec.numeric["conviction"] == pytest.approx(0.72)
        assert vec.numeric["moat_axis_count"] == 2.0
        assert vec.numeric["cross_exposure_count"] == 1.0


# ---------------------------------------------------------------------------
# 2. Company sparse vector
# ---------------------------------------------------------------------------

class TestCompanySparse:
    @pytest.mark.asyncio
    async def test_sparse_vector_when_facets_missing(self, db):
        from app.services.similarity_feature_builder import build_company_feature_vector
        from app.db.repositories.dossier_repo import get_or_create_head, upsert_head

        await get_or_create_head(db, "SPARSECO", company_name="Sparse Co")
        await upsert_head(db, "SPARSECO", stance="neutral", conviction=0.3)
        await db.commit()

        vec = await build_company_feature_vector(db, "SPARSECO")
        assert vec is not None
        assert vec.categorical["stance"] == "neutral"
        assert vec.categorical["core_debate_lean"] == ""
        assert vec.categorical["durability_cycle_position"] == ""
        assert vec.tag_set == []
        assert vec.numeric["moat_axis_count"] == 0.0
        assert vec.numeric["cross_exposure_count"] == 0.0


# ---------------------------------------------------------------------------
# 3. Company missing head -> None
# ---------------------------------------------------------------------------

class TestCompanyMissingHead:
    @pytest.mark.asyncio
    async def test_missing_head_returns_none(self, db):
        from app.services.similarity_feature_builder import build_company_feature_vector

        result = await build_company_feature_vector(db, "NOHEAD")
        assert result is None


# ---------------------------------------------------------------------------
# 4. Thesis vector build (full substrate)
# ---------------------------------------------------------------------------

class TestThesisFullBuild:
    @pytest.mark.asyncio
    async def test_build_thesis_with_full_substrate(self, db):
        from app.services.similarity_feature_builder import build_thesis_feature_vector

        thesis = await _seed_thesis_full(db, ticker="AAPL")
        vec = await build_thesis_feature_vector(db, thesis.id)

        assert vec is not None
        assert vec.target_type == "thesis"
        assert vec.entity_key == thesis.id
        assert vec.categorical["ticker"] == "AAPL"
        assert vec.categorical["directional_stance"] == "bullish"
        assert vec.categorical["core_debate_lean"] == "bull"
        assert vec.categorical["durability_cycle_position"] == "mid"
        assert "margin_trajectory" in vec.tag_set
        assert vec.numeric["confidence_score"] == pytest.approx(0.68)
        assert vec.numeric["key_drivers_count"] == 2.0
        assert vec.numeric["key_risks_count"] == 1.0
        assert vec.numeric["variant_confidence"] == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# 5. Thesis sparse vector
# ---------------------------------------------------------------------------

class TestThesisSparse:
    @pytest.mark.asyncio
    async def test_sparse_vector_when_facets_missing(self, db):
        from app.services.similarity_feature_builder import build_thesis_feature_vector
        from app.db.models import ThesisVersion

        thesis = ThesisVersion(
            ticker="SPARSETHESIS", company_name="Sparse Thesis Co",
            directional_stance="neutral", confidence_score=0.4,
        )
        db.add(thesis)
        await db.commit()

        vec = await build_thesis_feature_vector(db, thesis.id)
        assert vec is not None
        assert vec.categorical["directional_stance"] == "neutral"
        assert vec.categorical["core_debate_lean"] == ""
        assert vec.tag_set == []
        assert vec.numeric["key_drivers_count"] == 0.0
        assert vec.numeric["variant_confidence"] == 0.0


# ---------------------------------------------------------------------------
# 6. Thesis missing id -> None
# ---------------------------------------------------------------------------

class TestThesisMissing:
    @pytest.mark.asyncio
    async def test_missing_thesis_version_id_returns_none(self, db):
        from app.services.similarity_feature_builder import build_thesis_feature_vector

        result = await build_thesis_feature_vector(db, "does-not-exist")
        assert result is None


# ---------------------------------------------------------------------------
# 7. Deterministic output
# ---------------------------------------------------------------------------

class TestDeterminism:
    @pytest.mark.asyncio
    async def test_company_rebuild_is_deterministic(self, db):
        from app.services.similarity_feature_builder import build_company_feature_vector

        await _seed_company_full(db, ticker="DETM")
        v1 = await build_company_feature_vector(db, "DETM")
        await db.commit()
        v2 = await build_company_feature_vector(db, "DETM")
        await db.commit()

        assert v1.categorical == v2.categorical
        assert v1.tag_set == v2.tag_set
        assert v1.numeric == v2.numeric
        assert v1.text_anchor == v2.text_anchor

    @pytest.mark.asyncio
    async def test_thesis_rebuild_is_deterministic(self, db):
        from app.services.similarity_feature_builder import build_thesis_feature_vector

        thesis = await _seed_thesis_full(db, ticker="DETMTHESIS")
        v1 = await build_thesis_feature_vector(db, thesis.id)
        await db.commit()
        v2 = await build_thesis_feature_vector(db, thesis.id)
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
    async def test_company_rebuild_updates_same_row(self, db):
        from app.services.similarity_feature_builder import build_company_feature_vector
        from app.db.repositories.dossier_repo import upsert_head
        from sqlalchemy import select, func
        from app.db.models import SimilarityFeatureVector

        await _seed_company_full(db, ticker="IDEMCO")
        v1 = await build_company_feature_vector(db, "IDEMCO")
        await db.commit()
        first_id = v1.id

        await upsert_head(db, "IDEMCO", stance="bearish", conviction=0.2)
        await db.commit()
        v2 = await build_company_feature_vector(db, "IDEMCO")
        await db.commit()

        assert v2.id == first_id
        assert v2.categorical["stance"] == "bearish"

        count = (
            await db.execute(
                select(func.count()).select_from(SimilarityFeatureVector).where(
                    SimilarityFeatureVector.entity_key == "IDEMCO",
                    SimilarityFeatureVector.target_type == "company",
                )
            )
        ).scalar_one()
        assert count == 1

    @pytest.mark.asyncio
    async def test_thesis_rebuild_updates_same_row(self, db):
        from app.services.similarity_feature_builder import build_thesis_feature_vector
        from sqlalchemy import select, func
        from app.db.models import SimilarityFeatureVector

        thesis = await _seed_thesis_full(db, ticker="IDEMTHESIS")
        v1 = await build_thesis_feature_vector(db, thesis.id)
        await db.commit()
        first_id = v1.id

        v2 = await build_thesis_feature_vector(db, thesis.id)
        await db.commit()

        assert v2.id == first_id

        count = (
            await db.execute(
                select(func.count()).select_from(SimilarityFeatureVector).where(
                    SimilarityFeatureVector.entity_key == thesis.id,
                    SimilarityFeatureVector.target_type == "thesis",
                )
            )
        ).scalar_one()
        assert count == 1


# ---------------------------------------------------------------------------
# 9. No-write-back
# ---------------------------------------------------------------------------

class TestNoWriteBack:
    @pytest.mark.asyncio
    async def test_source_tables_unchanged_after_company_and_thesis_build(self, db):
        from app.services.similarity_feature_builder import (
            build_company_feature_vector, build_thesis_feature_vector,
            build_company_feature_vectors_for_all, build_thesis_feature_vectors_for_all,
        )
        from sqlalchemy import select
        from app.db.models import (
            CompanyDossier, CrossExposure, DossierCoreDebate, DossierMoatDimension,
            DossierDurability, ThesisVersion, DossierVariant,
        )

        await _seed_company_full(db, ticker="NWB")
        thesis = await _seed_thesis_full(db, ticker="NWB")

        async def _dump(model):
            rows = (await db.execute(select(model))).scalars().all()
            cols = [c.name for c in model.__table__.columns]
            return sorted(tuple(getattr(r, c) for c in cols) for r in rows)

        before = {
            "dossier": await _dump(CompanyDossier),
            "cross": await _dump(CrossExposure),
            "debate": await _dump(DossierCoreDebate),
            "moat": await _dump(DossierMoatDimension),
            "durability": await _dump(DossierDurability),
            "thesis": await _dump(ThesisVersion),
            "variant": await _dump(DossierVariant),
        }

        await build_company_feature_vector(db, "NWB")
        await build_thesis_feature_vector(db, thesis.id)
        await build_company_feature_vectors_for_all(db)
        await build_thesis_feature_vectors_for_all(db)
        await db.commit()

        after = {
            "dossier": await _dump(CompanyDossier),
            "cross": await _dump(CrossExposure),
            "debate": await _dump(DossierCoreDebate),
            "moat": await _dump(DossierMoatDimension),
            "durability": await _dump(DossierDurability),
            "thesis": await _dump(ThesisVersion),
            "variant": await _dump(DossierVariant),
        }

        assert before == after


# ---------------------------------------------------------------------------
# 10. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_build_company_null_session(self):
        from app.services.similarity_feature_builder import build_company_feature_vector

        result = await build_company_feature_vector(None, "AAPL")
        assert result is None

    @pytest.mark.asyncio
    async def test_build_company_for_all_null_session(self):
        from app.services.similarity_feature_builder import build_company_feature_vectors_for_all

        result = await build_company_feature_vectors_for_all(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_build_thesis_null_session(self):
        from app.services.similarity_feature_builder import build_thesis_feature_vector

        result = await build_thesis_feature_vector(None, "any-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_build_thesis_for_all_null_session(self):
        from app.services.similarity_feature_builder import build_thesis_feature_vectors_for_all

        result = await build_thesis_feature_vectors_for_all(None)
        assert result == []


# ---------------------------------------------------------------------------
# 11. for_all builders
# ---------------------------------------------------------------------------

class TestForAllBuilders:
    @pytest.mark.asyncio
    async def test_company_for_all_covers_all_tickers(self, db):
        from app.services.similarity_feature_builder import build_company_feature_vectors_for_all

        await _seed_company_full(db, ticker="ALLCO1")
        await _seed_company_full(db, ticker="ALLCO2")

        vecs = await build_company_feature_vectors_for_all(db)
        tickers = {v.entity_key for v in vecs}
        assert "ALLCO1" in tickers
        assert "ALLCO2" in tickers

    @pytest.mark.asyncio
    async def test_thesis_for_all_covers_all_versions(self, db):
        from app.services.similarity_feature_builder import build_thesis_feature_vectors_for_all

        t1 = await _seed_thesis_full(db, ticker="ALLTHESIS1")
        t2 = await _seed_thesis_full(db, ticker="ALLTHESIS2")

        vecs = await build_thesis_feature_vectors_for_all(db)
        entity_keys = {v.entity_key for v in vecs}
        assert t1.id in entity_keys
        assert t2.id in entity_keys


# ---------------------------------------------------------------------------
# 12. No similarity_edge rows created
# ---------------------------------------------------------------------------

class TestNoEdgesCreated:
    @pytest.mark.asyncio
    async def test_builders_create_no_edges(self, db):
        from app.services.similarity_feature_builder import (
            build_company_feature_vector, build_thesis_feature_vector,
        )
        from sqlalchemy import select, func
        from app.db.models import SimilarityEdge

        await _seed_company_full(db, ticker="NOEDGE")
        thesis = await _seed_thesis_full(db, ticker="NOEDGE")

        await build_company_feature_vector(db, "NOEDGE")
        await build_thesis_feature_vector(db, thesis.id)
        await db.commit()

        count = (await db.execute(select(func.count()).select_from(SimilarityEdge))).scalar_one()
        assert count == 0
