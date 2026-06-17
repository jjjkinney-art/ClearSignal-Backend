"""
Tests — Similarity Scorer, Phase 11 · Slice 3 (T4 failure-mode scoring only).

Covers:
  1.  Deterministic scoring (same pair scored twice -> identical result)
  2.  Edge explainability: every edge has score, contributions, headline, disanalogy
  3.  Disanalogy is always present (even for near-identical entities)
  4.  No orphan scores: every floor_passed=True edge has non-empty contributions
  5.  No-write-back: source tables AND similarity_feature_vector unchanged
  6.  Self-exclusion: no edge with query_key == candidate_key
  7.  Ranking: edges ranked by score descending, deterministic tiebreak
  8.  Ticker-level and all-level edge builders
  9.  Null-session safety
  10. Missing query vector -> []
  11. Below-floor pairs stored with floor_passed=False (diagnostic), still explainable
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def engine():
    """Function-scoped: the scorer reads ALL vectors of a target_type as
    candidates, so tests must not share state via a module-scoped DB."""
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
# Seed helpers — write feature vectors directly (Slice 3 tests scoring, not
# the Slice 2 builder), but route through the real repo upsert.
# ---------------------------------------------------------------------------

async def _seed_vector(db, *, entity_key, ticker, **overrides):
    from app.db.repositories.similarity_repo import upsert_feature_vector

    categorical = dict(
        ticker=ticker,
        analog_id="analog-x",
        failure_mode_label="Some Analog",
        mechanism="inventory_channel_correction",
        sector="tech",
        business_model="hardware",
        valuation_regime="peak_multiple",
        growth_phase="hypergrowth",
        macro_regime="hiking",
        quality_rating="strong",
    )
    categorical.update(overrides.pop("categorical", {}))
    tag_set = overrides.pop("tag_set", ["supply_chain_risk", "capex_cycle"])
    numeric = overrides.pop("numeric", {"sequence_stage": 2.0, "relevance_at_match": 0.7})

    return await upsert_feature_vector(
        db,
        target_type="failure_mode",
        entity_key=entity_key,
        categorical=categorical,
        tag_set=tag_set,
        numeric=numeric,
        text_anchor=f"{ticker} matched to Some Analog at stage 2.",
        source_versions={"dossier_failure_mode_id": entity_key},
        vector_schema=1,
        **overrides,
    )


# ---------------------------------------------------------------------------
# 1. Deterministic scoring
# ---------------------------------------------------------------------------

class TestDeterministicScoring:
    @pytest.mark.asyncio
    async def test_same_pair_scored_twice_is_identical(self, db):
        from app.services.similarity_scorer import score_failure_mode_pair

        v1 = await _seed_vector(db, entity_key="FM_A", ticker="AAPL")
        v2 = await _seed_vector(db, entity_key="FM_B", ticker="MSFT")
        await db.commit()

        r1 = score_failure_mode_pair(v1, v2)
        r2 = score_failure_mode_pair(v1, v2)

        assert r1 == r2


# ---------------------------------------------------------------------------
# 2. Edge explainability
# ---------------------------------------------------------------------------

class TestExplainability:
    @pytest.mark.asyncio
    async def test_edges_carry_full_explanation(self, db):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges

        await _seed_vector(db, entity_key="EXP_Q", ticker="AAPL")
        await _seed_vector(db, entity_key="EXP_C", ticker="CSCO")
        await db.commit()

        edges = await build_failure_mode_similarity_edges(db, "EXP_Q")
        assert len(edges) == 1
        edge = edges[0]

        assert edge.score is not None
        assert isinstance(edge.contributions, list)
        assert edge.headline and isinstance(edge.headline, str)
        assert edge.disanalogy and isinstance(edge.disanalogy, str)


# ---------------------------------------------------------------------------
# 3. Disanalogy always present
# ---------------------------------------------------------------------------

class TestDisanalogyAlwaysPresent:
    @pytest.mark.asyncio
    async def test_disanalogy_present_for_near_identical_entities(self, db):
        """Even when categorical fields are nearly identical, disanalogy is non-empty
        (falls back to the explicit 'directional, not confirmed' caveat when the
        ticker differs but everything else matches, or to the no-diff caveat
        when truly identical aside from entity_key)."""
        from app.services.similarity_scorer import score_failure_mode_pair

        v1 = await _seed_vector(db, entity_key="ID_A", ticker="SAMECO")
        v2 = await _seed_vector(db, entity_key="ID_B", ticker="SAMECO")
        await db.commit()

        result = score_failure_mode_pair(v1, v2)
        assert result["disanalogy"]
        assert len(result["disanalogy"]) > 0

    @pytest.mark.asyncio
    async def test_disanalogy_present_for_dissimilar_entities(self, db):
        from app.services.similarity_scorer import score_failure_mode_pair

        v1 = await _seed_vector(
            db, entity_key="DIFF_A", ticker="AAPL",
            categorical={"sector": "tech", "valuation_regime": "peak_multiple"},
        )
        v2 = await _seed_vector(
            db, entity_key="DIFF_B", ticker="XOM",
            categorical={"sector": "energy", "valuation_regime": "compressed"},
            tag_set=["currency_risk"],
        )
        await db.commit()

        result = score_failure_mode_pair(v1, v2)
        assert result["disanalogy"]
        assert "sector differs" in result["disanalogy"] or "differs" in result["disanalogy"]


# ---------------------------------------------------------------------------
# 4. No orphan scores
# ---------------------------------------------------------------------------

class TestNoOrphanScores:
    @pytest.mark.asyncio
    async def test_every_floor_passed_edge_has_contributions(self, db):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges

        await _seed_vector(db, entity_key="ORPH_Q", ticker="AAPL")
        await _seed_vector(db, entity_key="ORPH_C1", ticker="CSCO")  # similar -> likely passes
        await _seed_vector(
            db, entity_key="ORPH_C2", ticker="XOM",
            categorical={"sector": "energy", "business_model": "commodity",
                         "valuation_regime": "compressed", "growth_phase": "mature",
                         "macro_regime": "easing", "mechanism": "rate_shock"},
            tag_set=["currency_risk"],
        )
        await db.commit()

        edges = await build_failure_mode_similarity_edges(db, "ORPH_Q")
        for edge in edges:
            if edge.floor_passed:
                assert edge.contributions, (
                    f"floor_passed=True edge {edge.candidate_key} has empty contributions"
                )


# ---------------------------------------------------------------------------
# 5. No-write-back
# ---------------------------------------------------------------------------

class TestNoWriteBack:
    @pytest.mark.asyncio
    async def test_source_and_feature_vector_tables_unchanged(self, db):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges
        from sqlalchemy import select
        from app.db.models import (
            DossierFailureMode, HistoricalAnalog, CompanyDossier,
            CrossExposure, ThesisVersion, SimilarityFeatureVector,
        )

        await _seed_vector(db, entity_key="NWB_Q", ticker="AAPL")
        await _seed_vector(db, entity_key="NWB_C", ticker="CSCO")
        await db.commit()

        async def _dump(model):
            rows = (await db.execute(select(model))).scalars().all()
            cols = [c.name for c in model.__table__.columns]
            return sorted(tuple(getattr(r, c) for c in cols) for r in rows)

        before = {
            "fm": await _dump(DossierFailureMode),
            "analog": await _dump(HistoricalAnalog),
            "dossier": await _dump(CompanyDossier),
            "cross": await _dump(CrossExposure),
            "thesis": await _dump(ThesisVersion),
            "sfv": await _dump(SimilarityFeatureVector),
        }

        await build_failure_mode_similarity_edges(db, "NWB_Q")
        await db.commit()

        after = {
            "fm": await _dump(DossierFailureMode),
            "analog": await _dump(HistoricalAnalog),
            "dossier": await _dump(CompanyDossier),
            "cross": await _dump(CrossExposure),
            "thesis": await _dump(ThesisVersion),
            "sfv": await _dump(SimilarityFeatureVector),
        }

        assert before == after


# ---------------------------------------------------------------------------
# 6. Self-exclusion
# ---------------------------------------------------------------------------

class TestSelfExclusion:
    @pytest.mark.asyncio
    async def test_no_edge_with_query_equal_candidate(self, db):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges

        await _seed_vector(db, entity_key="SELF_Q", ticker="AAPL")
        await _seed_vector(db, entity_key="SELF_C", ticker="CSCO")
        await db.commit()

        edges = await build_failure_mode_similarity_edges(db, "SELF_Q")
        for edge in edges:
            assert edge.candidate_key != edge.query_key


# ---------------------------------------------------------------------------
# 7. Ranking
# ---------------------------------------------------------------------------

class TestRanking:
    @pytest.mark.asyncio
    async def test_edges_ranked_by_score_descending(self, db):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges

        await _seed_vector(db, entity_key="RANK_Q", ticker="AAPL")
        # Strong match — identical categorical/tags
        await _seed_vector(db, entity_key="RANK_STRONG", ticker="CSCO")
        # Weak match — divergent fields
        await _seed_vector(
            db, entity_key="RANK_WEAK", ticker="XOM",
            categorical={"sector": "energy", "business_model": "commodity",
                         "valuation_regime": "compressed", "growth_phase": "mature",
                         "macro_regime": "easing", "mechanism": "rate_shock"},
            tag_set=["currency_risk"],
        )
        await db.commit()

        edges = await build_failure_mode_similarity_edges(db, "RANK_Q")
        scores = [e.score for e in edges]
        assert scores == sorted(scores, reverse=True)

        ranks = [e.rank for e in edges]
        assert ranks == sorted(ranks)

        strong_edge = next(e for e in edges if e.candidate_key == "RANK_STRONG")
        weak_edge = next(e for e in edges if e.candidate_key == "RANK_WEAK")
        assert strong_edge.score > weak_edge.score
        assert strong_edge.rank < weak_edge.rank


# ---------------------------------------------------------------------------
# 8. Ticker-level and all-level builders
# ---------------------------------------------------------------------------

class TestTickerAndAllBuilders:
    @pytest.mark.asyncio
    async def test_build_for_ticker(self, db):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges_for_ticker

        await _seed_vector(db, entity_key="TKR_A1", ticker="TICKBUILD")
        await _seed_vector(db, entity_key="TKR_A2", ticker="TICKBUILD")
        await _seed_vector(db, entity_key="TKR_OTHER", ticker="UNRELATED")
        await db.commit()

        edges = await build_failure_mode_similarity_edges_for_ticker(db, "TICKBUILD")
        query_keys = {e.query_key for e in edges}
        assert "TKR_A1" in query_keys
        assert "TKR_A2" in query_keys

    @pytest.mark.asyncio
    async def test_build_for_all(self, db):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges_for_all
        from sqlalchemy import select, func
        from app.db.models import SimilarityFeatureVector

        await _seed_vector(db, entity_key="ALL_A", ticker="ALLCO1")
        await _seed_vector(db, entity_key="ALL_B", ticker="ALLCO2")
        await db.commit()

        edges = await build_failure_mode_similarity_edges_for_all(db)
        total_vectors = (
            await db.execute(select(func.count()).select_from(SimilarityFeatureVector))
        ).scalar_one()
        # at minimum, each vector should have generated at least one outbound edge
        # given >= 2 vectors exist
        assert len(edges) >= 1
        assert total_vectors >= 2


# ---------------------------------------------------------------------------
# 9. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_build_single_null_session(self):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges

        result = await build_failure_mode_similarity_edges(None, "any-key")
        assert result == []

    @pytest.mark.asyncio
    async def test_build_for_ticker_null_session(self):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges_for_ticker

        result = await build_failure_mode_similarity_edges_for_ticker(None, "AAPL")
        assert result == []

    @pytest.mark.asyncio
    async def test_build_for_all_null_session(self):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges_for_all

        result = await build_failure_mode_similarity_edges_for_all(None)
        assert result == []


# ---------------------------------------------------------------------------
# 10. Missing query vector
# ---------------------------------------------------------------------------

class TestMissingQueryVector:
    @pytest.mark.asyncio
    async def test_missing_query_vector_returns_empty(self, db):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges

        result = await build_failure_mode_similarity_edges(db, "does-not-exist")
        assert result == []


# ---------------------------------------------------------------------------
# 11. Below-floor pairs stored as diagnostics, still explainable
# ---------------------------------------------------------------------------

class TestBelowFloorDiagnostics:
    @pytest.mark.asyncio
    async def test_below_floor_edge_still_has_disanalogy_and_headline(self, db):
        from app.services.similarity_scorer import build_failure_mode_similarity_edges

        await _seed_vector(db, entity_key="BF_Q", ticker="AAPL")
        await _seed_vector(
            db, entity_key="BF_C", ticker="XOM",
            categorical={"sector": "energy", "business_model": "commodity",
                         "valuation_regime": "compressed", "growth_phase": "mature",
                         "macro_regime": "easing", "mechanism": "rate_shock"},
            tag_set=["currency_risk"],
        )
        await db.commit()

        edges = await build_failure_mode_similarity_edges(db, "BF_Q")
        weak_edge = next(e for e in edges if e.candidate_key == "BF_C")

        assert weak_edge.floor_passed is False
        assert weak_edge.disanalogy
        assert weak_edge.headline
