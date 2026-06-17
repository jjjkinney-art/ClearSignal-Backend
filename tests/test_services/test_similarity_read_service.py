"""
Tests — Similarity Read Service, Phase 11 · Slice 6.

Covers:
  1.  Read target similarities (get_similarity_for_target)
  2.  Read ticker similarities (get_similarity_for_ticker)
  3.  Safe empty state (no data built yet)
  4.  Below-floor edges omitted
  5.  Expired edges omitted
  6.  Disanalogy included in every match
  7.  Explanation contributions (why_similar) included in every match
  8.  Disclaimer included in the Resembles facet
  9.  No source-table writes
  10. No forecasting imports
  11. No delivery imports
  12. No rebuild triggered by read (feature_builder / scorer never invoked)
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


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

async def _seed_vector(db, *, entity_key, ticker, label="Some Analog", **overrides):
    from app.db.repositories.similarity_repo import upsert_feature_vector

    categorical = dict(
        ticker=ticker, analog_id="analog-x", failure_mode_label=label,
        mechanism="inventory_channel_correction", sector="tech", business_model="hardware",
        valuation_regime="peak_multiple", growth_phase="hypergrowth", macro_regime="hiking",
        quality_rating="strong",
    )
    categorical.update(overrides.pop("categorical", {}))
    tag_set = overrides.pop("tag_set", ["supply_chain_risk", "capex_cycle"])
    numeric = overrides.pop("numeric", {"sequence_stage": 2.0, "relevance_at_match": 0.7})

    return await upsert_feature_vector(
        db, target_type="failure_mode", entity_key=entity_key,
        categorical=categorical, tag_set=tag_set, numeric=numeric,
        text_anchor=f"{ticker} matched to {label}.",
        source_versions={"dossier_failure_mode_id": entity_key},
        vector_schema=1, **overrides,
    )


async def _seed_edge(db, *, query_key, candidate_key, score=0.7, floor_passed=True,
                      contributions=None, disanalogy="Sectors differ.", expires_at=None):
    from app.db.repositories.similarity_repo import upsert_similarity_edge

    if contributions is None:
        contributions = [{"feature": "concern_tags", "shared_value": ["capex_cycle"],
                           "weight": 0.4, "partial_score": 0.3}]
    edge = await upsert_similarity_edge(
        db, target_type="failure_mode", query_key=query_key, candidate_key=candidate_key,
        score=score, rank=1, contributions=contributions, headline="Both share X.",
        disanalogy=disanalogy, floor_passed=floor_passed,
    )
    if expires_at is not None:
        edge.expires_at = expires_at
        await db.commit()
    return edge


# ---------------------------------------------------------------------------
# 1. Read target similarities
# ---------------------------------------------------------------------------

class TestReadTarget:
    @pytest.mark.asyncio
    async def test_get_similarity_for_target_returns_match(self, db):
        from app.services.similarity_read_service import get_similarity_for_target

        await _seed_vector(db, entity_key="Q1", ticker="AAPL")
        await _seed_vector(db, entity_key="C1", ticker="CSCO")
        await _seed_edge(db, query_key="Q1", candidate_key="C1")
        await db.commit()

        matches = await get_similarity_for_target(db, "failure_mode", "Q1")
        assert len(matches) == 1
        assert matches[0]["similarity_type"] == "failure_mode"
        assert "AAPL" in matches[0]["target"]
        assert "CSCO" in matches[0]["similar_to"]


# ---------------------------------------------------------------------------
# 2. Read ticker similarities
# ---------------------------------------------------------------------------

class TestReadTicker:
    @pytest.mark.asyncio
    async def test_get_similarity_for_ticker_aggregates_across_vectors(self, db):
        from app.services.similarity_read_service import get_similarity_for_ticker

        await _seed_vector(db, entity_key="TQ1", ticker="MSFT")
        await _seed_vector(db, entity_key="TQ2", ticker="MSFT")
        await _seed_vector(db, entity_key="TC1", ticker="ORCL")
        await _seed_edge(db, query_key="TQ1", candidate_key="TC1", score=0.6)
        await _seed_edge(db, query_key="TQ2", candidate_key="TC1", score=0.8)
        await db.commit()

        matches = await get_similarity_for_ticker(db, "MSFT")
        assert len(matches) == 2
        # sorted by score descending
        assert matches[0]["score"] >= matches[1]["score"]


# ---------------------------------------------------------------------------
# 3. Safe empty state
# ---------------------------------------------------------------------------

class TestSafeEmptyState:
    @pytest.mark.asyncio
    async def test_no_data_built_yet_returns_empty_facet(self, db):
        from app.services.similarity_read_service import get_resembles_facet_for_ticker

        facet = await get_resembles_facet_for_ticker(db, "NODATA")
        assert facet == {
            "has_similarity": False,
            "ticker": "NODATA",
            "matches": [],
            "disclaimer": "Similarity is descriptive and does not imply identical outcomes.",
        }

    @pytest.mark.asyncio
    async def test_get_similarity_for_target_returns_empty_list_when_no_edges(self, db):
        from app.services.similarity_read_service import get_similarity_for_target

        result = await get_similarity_for_target(db, "failure_mode", "no-such-entity")
        assert result == []


# ---------------------------------------------------------------------------
# 4. Below-floor edges omitted
# ---------------------------------------------------------------------------

class TestBelowFloorOmitted:
    @pytest.mark.asyncio
    async def test_below_floor_edge_excluded(self, db):
        from app.services.similarity_read_service import get_similarity_for_target

        await _seed_vector(db, entity_key="BFQ", ticker="AAPL")
        await _seed_vector(db, entity_key="BFC", ticker="XOM")
        await _seed_edge(db, query_key="BFQ", candidate_key="BFC", score=0.1, floor_passed=False)
        await db.commit()

        matches = await get_similarity_for_target(db, "failure_mode", "BFQ")
        assert matches == []


# ---------------------------------------------------------------------------
# 5. Expired edges omitted
# ---------------------------------------------------------------------------

class TestExpiredOmitted:
    @pytest.mark.asyncio
    async def test_expired_edge_excluded(self, db):
        from datetime import datetime, timedelta, timezone
        from app.services.similarity_read_service import get_similarity_for_target

        await _seed_vector(db, entity_key="EXPQ", ticker="AAPL")
        await _seed_vector(db, entity_key="EXPC", ticker="CSCO")
        await _seed_edge(
            db, query_key="EXPQ", candidate_key="EXPC",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        await db.commit()

        matches = await get_similarity_for_target(db, "failure_mode", "EXPQ")
        assert matches == []


# ---------------------------------------------------------------------------
# 6 & 7. Disanalogy and explanation contributions included
# ---------------------------------------------------------------------------

class TestExplainabilityFieldsPresent:
    @pytest.mark.asyncio
    async def test_match_includes_disanalogy_and_why_similar(self, db):
        from app.services.similarity_read_service import get_similarity_for_target

        await _seed_vector(db, entity_key="EXPLQ", ticker="AAPL")
        await _seed_vector(db, entity_key="EXPLC", ticker="CSCO")
        await _seed_edge(
            db, query_key="EXPLQ", candidate_key="EXPLC",
            disanalogy="Customer concentration differs.",
            contributions=[{"feature": "mechanism", "shared_value": "inventory_channel_correction",
                             "weight": 0.3, "partial_score": 0.3}],
        )
        await db.commit()

        matches = await get_similarity_for_target(db, "failure_mode", "EXPLQ")
        assert len(matches) == 1
        assert matches[0]["key_disanalogy"] == "Customer concentration differs."
        assert matches[0]["why_similar"] == [
            {"feature": "mechanism", "shared_value": "inventory_channel_correction",
             "weight": 0.3, "partial_score": 0.3}
        ]

    @pytest.mark.asyncio
    async def test_edge_missing_disanalogy_or_contributions_is_dropped(self, db):
        """Defense-in-depth: even if a malformed edge slipped through, the read
        layer never surfaces an unexplained or non-disanalogous match."""
        from app.services.similarity_read_service import get_similarity_for_target
        from app.db.repositories.similarity_repo import upsert_similarity_edge

        await _seed_vector(db, entity_key="MALQ", ticker="AAPL")
        await _seed_vector(db, entity_key="MALC", ticker="CSCO")
        await upsert_similarity_edge(
            db, target_type="failure_mode", query_key="MALQ", candidate_key="MALC",
            score=0.9, rank=1, contributions=[], headline="x", disanalogy="",
            floor_passed=True,
        )
        await db.commit()

        matches = await get_similarity_for_target(db, "failure_mode", "MALQ")
        assert matches == []


# ---------------------------------------------------------------------------
# 8. Disclaimer included
# ---------------------------------------------------------------------------

class TestDisclaimer:
    @pytest.mark.asyncio
    async def test_facet_always_includes_disclaimer(self, db):
        from app.services.similarity_read_service import get_resembles_facet_for_ticker, DISCLAIMER

        await _seed_vector(db, entity_key="DISCQ", ticker="DISCCO")
        await _seed_vector(db, entity_key="DISCC", ticker="OTHERCO")
        await _seed_edge(db, query_key="DISCQ", candidate_key="DISCC")
        await db.commit()

        facet = await get_resembles_facet_for_ticker(db, "DISCCO")
        assert facet["disclaimer"] == DISCLAIMER
        assert facet["has_similarity"] is True
        assert len(facet["matches"]) == 1


# ---------------------------------------------------------------------------
# 9. No source-table writes
# ---------------------------------------------------------------------------

class TestNoWriteBack:
    @pytest.mark.asyncio
    async def test_reads_do_not_mutate_similarity_tables_or_source_tables(self, db):
        from app.services.similarity_read_service import (
            get_similarity_for_target, get_similarity_for_ticker,
            get_resembles_facet_for_ticker, build_similarity_status_snapshot,
        )
        from sqlalchemy import select
        from app.db.models import (
            SimilarityFeatureVector, SimilarityEdge, DossierFailureMode, HistoricalAnalog,
        )

        await _seed_vector(db, entity_key="NWBQ", ticker="NWBCO")
        await _seed_vector(db, entity_key="NWBC", ticker="OTHERCO")
        await _seed_edge(db, query_key="NWBQ", candidate_key="NWBC")
        await db.commit()

        async def _dump(model):
            rows = (await db.execute(select(model))).scalars().all()
            cols = [c.name for c in model.__table__.columns]
            return sorted(tuple(getattr(r, c) for c in cols) for r in rows)

        before = {
            "sfv": await _dump(SimilarityFeatureVector),
            "edges": await _dump(SimilarityEdge),
            "fm": await _dump(DossierFailureMode),
            "analog": await _dump(HistoricalAnalog),
        }

        await get_similarity_for_target(db, "failure_mode", "NWBQ")
        await get_similarity_for_ticker(db, "NWBCO")
        await get_resembles_facet_for_ticker(db, "NWBCO")
        await build_similarity_status_snapshot(db)
        await db.commit()

        after = {
            "sfv": await _dump(SimilarityFeatureVector),
            "edges": await _dump(SimilarityEdge),
            "fm": await _dump(DossierFailureMode),
            "analog": await _dump(HistoricalAnalog),
        }

        assert before == after


# ---------------------------------------------------------------------------
# 10 & 11. No forecasting / delivery imports
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:
    def test_module_has_no_forecast_or_delivery_import_statements(self):
        import ast
        import inspect
        import app.services.similarity_read_service as mod

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
                    f"forbidden import '{name}' (matches '{term}') found in similarity_read_service"
                )


# ---------------------------------------------------------------------------
# 12. No rebuild triggered by read
# ---------------------------------------------------------------------------

class TestNoRebuildTriggered:
    @pytest.mark.asyncio
    async def test_read_does_not_invoke_feature_builder_or_scorer(self, db, monkeypatch):
        import app.services.similarity_feature_builder as builder_mod
        import app.services.similarity_scorer as scorer_mod
        from app.services.similarity_read_service import (
            get_similarity_for_target, get_similarity_for_ticker, get_resembles_facet_for_ticker,
        )

        calls = []

        def _spy(name):
            def _inner(*args, **kwargs):
                calls.append(name)
                raise AssertionError(f"{name} should never be called by the read service")
            return _inner

        for fn_name in (
            "build_failure_mode_feature_vector",
            "build_company_feature_vector",
            "build_thesis_feature_vector",
        ):
            monkeypatch.setattr(builder_mod, fn_name, _spy(fn_name))
        monkeypatch.setattr(scorer_mod, "build_failure_mode_similarity_edges", _spy("scorer"))

        await _seed_vector(db, entity_key="NRQ", ticker="NRCO")
        await _seed_vector(db, entity_key="NRC", ticker="OTHERCO2")
        await _seed_edge(db, query_key="NRQ", candidate_key="NRC")
        await db.commit()

        await get_similarity_for_target(db, "failure_mode", "NRQ")
        await get_similarity_for_ticker(db, "NRCO")
        await get_resembles_facet_for_ticker(db, "NRCO")

        assert calls == []


# ---------------------------------------------------------------------------
# Bonus: null-session safety (not explicitly listed but required by convention)
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_all_public_functions_null_session_safe(self):
        from app.services.similarity_read_service import (
            get_similarity_for_target, get_similarity_for_ticker,
            get_resembles_facet_for_ticker, build_similarity_status_snapshot,
        )

        assert await get_similarity_for_target(None, "failure_mode", "x") == []
        assert await get_similarity_for_ticker(None, "AAPL") == []
        facet = await get_resembles_facet_for_ticker(None, "AAPL")
        assert facet["has_similarity"] is False
        assert facet["matches"] == []
        snapshot = await build_similarity_status_snapshot(None)
        assert snapshot["status"] == "disabled"
