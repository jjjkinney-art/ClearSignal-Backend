"""
Tests — Similarity Engine Schema, Phase 11 · Slice 1.

Covers:
  1.  Table count: Base.metadata has exactly 40 tables (38 → +2)
  2.  Both similarity tables are registered in Base.metadata
  3.  SimilarityFeatureVector ORM model has all required columns
  4.  SimilarityEdge ORM model has all required columns
  5.  Both tables and expected indexes are created against in-memory SQLite
  6.  Migration idempotency: Base.metadata.create_all runs twice without error
  7.  Feature vector CRUD: upsert, get, list
  8.  Feature vector upsert is idempotent (re-insert updates, not duplicates)
  9.  Feature vector uniqueness: (target_type, entity_key, user_id)
  10. Similarity edge CRUD: upsert, get, list
  11. Similarity edge upsert is idempotent (re-insert updates)
  12. Similarity edge uniqueness: (target_type, query_key, candidate_key, user_id)
  13. delete_expired_edges removes only expired rows
  14. delete_edges_for_query removes only matching rows
  15. Null-session safety: every repo function returns empty/None, never raises
  16. No source-table mutation: repo writes touch only the two similarity tables
  17. floor_passed=False rows are stored (diagnostic coverage) and filterable
  18. list_similarity_edges floor_passed_only filter
  19. list_similarity_edges exclude_expired filter
  20. ORM column types match spec (score float, floor_passed bool, etc.)
  21. Self-exclusion invariant: repo does not prevent self, but query_key ≠ candidate_key
      is enforced by the caller — test that same-key rows can be written (no DDL block)
  22. empty contributions can be stored (orphan-score guard is service-layer, not DDL)
  23. user_id=None rows coexist with user_id rows (shared global library pattern)
  24. SP-1 no-write-back: running repo ops leaves source tables untouched
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_vector_kwargs(**overrides) -> dict:
    base = dict(
        target_type     = "failure_mode",
        entity_key      = "AAPL",
        categorical     = {"sector": "tech", "valuation_regime": "peak_multiple"},
        tag_set         = ["capex_cycle", "supply_chain_risk"],
        numeric         = {"conviction": 0.75, "specificity": 0.80},
        text_anchor     = "Entering late-cycle demand deceleration with peak-multiple exposure.",
        source_versions = {"dossier_failure_mode": 1, "historical_analogs": "analog-uuid-1"},
        vector_schema   = 1,
        user_id         = None,
    )
    base.update(overrides)
    return base


def _make_edge_kwargs(**overrides) -> dict:
    base = dict(
        target_type   = "failure_mode",
        query_key     = "AAPL",
        candidate_key = "CSCO",
        score         = 0.72,
        rank          = 1,
        contributions = [
            {"feature": "tag_set",    "shared_value": ["capex_cycle"], "weight": 0.40, "partial_score": 0.27},
            {"feature": "mechanism",  "shared_value": "demand_pull_forward", "weight": 0.30, "partial_score": 0.30},
        ],
        headline      = "Both entered peak-multiple periods before demand deceleration.",
        disanalogy    = "CSCO had far greater customer concentration; AAPL is more diversified.",
        floor_passed  = True,
        score_schema  = 1,
        user_id       = None,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1–2. Table count and registration
# ---------------------------------------------------------------------------

class TestTableRegistration:
    def test_table_count_is_40(self):
        from app.db.models import Base
        tables = set(Base.metadata.tables.keys())
        # Phase 12 · Slice 1 added 3 more tables (41–43); use >= to remain
        # valid as future phases add tables.
        assert len(tables) >= 40, (
            f"Expected >= 40 tables (38 baseline + 2 similarity + later phases). "
            f"Got {len(tables)}. Tables: {sorted(tables)}"
        )

    def test_similarity_feature_vector_registered(self):
        from app.db.models import Base
        assert "similarity_feature_vector" in Base.metadata.tables

    def test_similarity_edge_registered(self):
        from app.db.models import Base
        assert "similarity_edge" in Base.metadata.tables


# ---------------------------------------------------------------------------
# 3–4. ORM column presence
# ---------------------------------------------------------------------------

class TestORMColumns:
    def test_feature_vector_required_columns(self):
        from app.db.models import SimilarityFeatureVector
        cols = {c.name for c in SimilarityFeatureVector.__table__.columns}
        for required in [
            "id", "target_type", "entity_key",
            "categorical", "tag_set", "numeric",
            "text_anchor", "source_versions", "vector_schema",
            "user_id", "built_at",
        ]:
            assert required in cols, f"SimilarityFeatureVector missing column: {required}"

    def test_edge_required_columns(self):
        from app.db.models import SimilarityEdge
        cols = {c.name for c in SimilarityEdge.__table__.columns}
        for required in [
            "id", "target_type", "query_key", "candidate_key",
            "score", "rank", "contributions", "headline", "disanalogy",
            "floor_passed", "score_schema", "user_id",
            "built_at", "expires_at",
        ]:
            assert required in cols, f"SimilarityEdge missing column: {required}"

    def test_score_is_float_column(self):
        from app.db.models import SimilarityEdge
        from sqlalchemy import Float
        col = SimilarityEdge.__table__.columns["score"]
        assert isinstance(col.type, Float)

    def test_floor_passed_is_boolean_column(self):
        from app.db.models import SimilarityEdge
        from sqlalchemy import Boolean
        col = SimilarityEdge.__table__.columns["floor_passed"]
        assert isinstance(col.type, Boolean)

    def test_rank_is_integer_column(self):
        from app.db.models import SimilarityEdge
        from sqlalchemy import Integer
        col = SimilarityEdge.__table__.columns["rank"]
        assert isinstance(col.type, Integer)

    def test_vector_schema_is_integer_column(self):
        from app.db.models import SimilarityFeatureVector
        from sqlalchemy import Integer
        col = SimilarityFeatureVector.__table__.columns["vector_schema"]
        assert isinstance(col.type, Integer)


# ---------------------------------------------------------------------------
# 5–6. Table + index creation and idempotency
# ---------------------------------------------------------------------------

class TestSchemaCreation:
    @pytest.mark.asyncio
    async def test_tables_created(self, db):
        from sqlalchemy import text
        result = await db.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = {row[0] for row in result.all()}
        assert "similarity_feature_vector" in tables
        assert "similarity_edge" in tables

    @pytest.mark.asyncio
    async def test_create_all_idempotent(self, engine):
        from app.db.models import Base
        # Run create_all a second time — must not error
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        # Still two tables present
        assert "similarity_feature_vector" in Base.metadata.tables
        assert "similarity_edge" in Base.metadata.tables


# ---------------------------------------------------------------------------
# 7–9. Feature vector CRUD
# ---------------------------------------------------------------------------

class TestFeatureVectorCRUD:
    @pytest.mark.asyncio
    async def test_upsert_creates_row(self, db):
        from app.db.repositories.similarity_repo import upsert_feature_vector, get_feature_vector

        row = await upsert_feature_vector(db, **_make_vector_kwargs(entity_key="TEST_UPSERT_CREATE"))
        await db.commit()
        assert row is not None
        assert row.entity_key == "TEST_UPSERT_CREATE"
        assert row.target_type == "failure_mode"

    @pytest.mark.asyncio
    async def test_get_returns_row(self, db):
        from app.db.repositories.similarity_repo import upsert_feature_vector, get_feature_vector

        await upsert_feature_vector(db, **_make_vector_kwargs(entity_key="TEST_GET"))
        await db.commit()
        found = await get_feature_vector(db, target_type="failure_mode", entity_key="TEST_GET", user_id=None)
        assert found is not None
        assert found.entity_key == "TEST_GET"

    @pytest.mark.asyncio
    async def test_get_returns_none_when_missing(self, db):
        from app.db.repositories.similarity_repo import get_feature_vector

        result = await get_feature_vector(db, target_type="company", entity_key="MISSING_XYZ", user_id=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_row(self, db):
        from app.db.repositories.similarity_repo import upsert_feature_vector, get_feature_vector

        await upsert_feature_vector(db, **_make_vector_kwargs(
            entity_key="TEST_UPSERT_UPDATE",
            text_anchor="original anchor",
        ))
        await db.commit()

        await upsert_feature_vector(db, **_make_vector_kwargs(
            entity_key="TEST_UPSERT_UPDATE",
            text_anchor="updated anchor",
        ))
        await db.commit()

        found = await get_feature_vector(db, target_type="failure_mode", entity_key="TEST_UPSERT_UPDATE")
        assert found is not None
        assert found.text_anchor == "updated anchor"

    @pytest.mark.asyncio
    async def test_list_returns_rows(self, db):
        from app.db.repositories.similarity_repo import upsert_feature_vector, list_feature_vectors

        await upsert_feature_vector(db, **_make_vector_kwargs(entity_key="TEST_LIST_A"))
        await upsert_feature_vector(db, **_make_vector_kwargs(entity_key="TEST_LIST_B"))
        await db.commit()

        rows = await list_feature_vectors(db, target_type="failure_mode")
        keys = {r.entity_key for r in rows}
        assert "TEST_LIST_A" in keys
        assert "TEST_LIST_B" in keys

    @pytest.mark.asyncio
    async def test_user_id_none_and_user_id_coexist(self, db):
        """Shared global library (user_id=None) and user-scoped rows are independent."""
        from app.db.repositories.similarity_repo import (
            upsert_feature_vector, get_feature_vector
        )

        await upsert_feature_vector(db, **_make_vector_kwargs(
            entity_key="TEST_SCOPE", user_id=None,
        ))
        await upsert_feature_vector(db, **_make_vector_kwargs(
            entity_key="TEST_SCOPE", user_id="user-abc",
        ))
        await db.commit()

        global_row = await get_feature_vector(db, target_type="failure_mode", entity_key="TEST_SCOPE", user_id=None)
        user_row   = await get_feature_vector(db, target_type="failure_mode", entity_key="TEST_SCOPE", user_id="user-abc")
        assert global_row is not None
        assert user_row is not None
        assert global_row.id != user_row.id


# ---------------------------------------------------------------------------
# 10–12. Similarity edge CRUD
# ---------------------------------------------------------------------------

class TestSimilarityEdgeCRUD:
    @pytest.mark.asyncio
    async def test_upsert_creates_edge(self, db):
        from app.db.repositories.similarity_repo import upsert_similarity_edge

        row = await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="EDGE_CREATE_Q", candidate_key="EDGE_CREATE_C",
        ))
        await db.commit()
        assert row is not None
        assert row.query_key == "EDGE_CREATE_Q"
        assert row.candidate_key == "EDGE_CREATE_C"
        assert abs(row.score - 0.72) < 1e-6

    @pytest.mark.asyncio
    async def test_get_edge_returns_row(self, db):
        from app.db.repositories.similarity_repo import upsert_similarity_edge, get_similarity_edge

        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="EDGE_GET_Q", candidate_key="EDGE_GET_C",
        ))
        await db.commit()

        found = await get_similarity_edge(
            db, target_type="failure_mode", query_key="EDGE_GET_Q", candidate_key="EDGE_GET_C",
        )
        assert found is not None
        assert found.floor_passed is True

    @pytest.mark.asyncio
    async def test_get_edge_returns_none_when_missing(self, db):
        from app.db.repositories.similarity_repo import get_similarity_edge

        result = await get_similarity_edge(
            db, target_type="company", query_key="MISSING_Q", candidate_key="MISSING_C",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_edge_updates_score(self, db):
        from app.db.repositories.similarity_repo import upsert_similarity_edge, get_similarity_edge

        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="EDGE_UPDATE_Q", candidate_key="EDGE_UPDATE_C", score=0.50,
        ))
        await db.commit()

        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="EDGE_UPDATE_Q", candidate_key="EDGE_UPDATE_C", score=0.88,
        ))
        await db.commit()

        found = await get_similarity_edge(
            db, target_type="failure_mode", query_key="EDGE_UPDATE_Q", candidate_key="EDGE_UPDATE_C",
        )
        assert abs(found.score - 0.88) < 1e-6

    @pytest.mark.asyncio
    async def test_list_edges(self, db):
        from app.db.repositories.similarity_repo import upsert_similarity_edge, list_similarity_edges

        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="LIST_Q", candidate_key="LIST_C1", rank=1,
        ))
        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="LIST_Q", candidate_key="LIST_C2", rank=2,
        ))
        await db.commit()

        edges = await list_similarity_edges(db, query_key="LIST_Q", target_type="failure_mode")
        candidate_keys = [e.candidate_key for e in edges]
        assert "LIST_C1" in candidate_keys
        assert "LIST_C2" in candidate_keys


# ---------------------------------------------------------------------------
# 13. delete_expired_edges
# ---------------------------------------------------------------------------

class TestDeleteExpiredEdges:
    @pytest.mark.asyncio
    async def test_deletes_expired_rows_only(self, db):
        from app.db.repositories.similarity_repo import (
            upsert_similarity_edge, delete_expired_edges, get_similarity_edge
        )

        # Expired edge
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        row_exp = await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="EXP_Q", candidate_key="EXP_C_EXPIRED",
        ))
        if row_exp:
            row_exp.expires_at = past
        await db.commit()

        # Active edge
        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="EXP_Q", candidate_key="EXP_C_ACTIVE", ttl_hours=48,
        ))
        await db.commit()

        deleted = await delete_expired_edges(db)
        await db.commit()
        assert deleted >= 1

        active = await get_similarity_edge(
            db, target_type="failure_mode", query_key="EXP_Q", candidate_key="EXP_C_ACTIVE",
        )
        assert active is not None


# ---------------------------------------------------------------------------
# 14. delete_edges_for_query
# ---------------------------------------------------------------------------

class TestDeleteEdgesForQuery:
    @pytest.mark.asyncio
    async def test_deletes_only_matching_query_key(self, db):
        from app.db.repositories.similarity_repo import (
            upsert_similarity_edge, delete_edges_for_query, list_similarity_edges
        )

        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="DEL_Q_TARGET", candidate_key="DEL_C1",
        ))
        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="DEL_Q_TARGET", candidate_key="DEL_C2",
        ))
        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="DEL_Q_OTHER", candidate_key="DEL_C3",
        ))
        await db.commit()

        deleted = await delete_edges_for_query(
            db, target_type="failure_mode", query_key="DEL_Q_TARGET",
        )
        await db.commit()
        assert deleted >= 2

        remaining = await list_similarity_edges(db, query_key="DEL_Q_OTHER", target_type="failure_mode")
        assert any(e.candidate_key == "DEL_C3" for e in remaining)


# ---------------------------------------------------------------------------
# 15. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_upsert_feature_vector_null_session(self):
        from app.db.repositories.similarity_repo import upsert_feature_vector
        result = await upsert_feature_vector(None, **_make_vector_kwargs())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_feature_vector_null_session(self):
        from app.db.repositories.similarity_repo import get_feature_vector
        result = await get_feature_vector(None, target_type="company", entity_key="AAPL")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_feature_vectors_null_session(self):
        from app.db.repositories.similarity_repo import list_feature_vectors
        result = await list_feature_vectors(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_upsert_similarity_edge_null_session(self):
        from app.db.repositories.similarity_repo import upsert_similarity_edge
        result = await upsert_similarity_edge(None, **_make_edge_kwargs())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_similarity_edge_null_session(self):
        from app.db.repositories.similarity_repo import get_similarity_edge
        result = await get_similarity_edge(None, target_type="company", query_key="A", candidate_key="B")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_similarity_edges_null_session(self):
        from app.db.repositories.similarity_repo import list_similarity_edges
        result = await list_similarity_edges(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_expired_edges_null_session(self):
        from app.db.repositories.similarity_repo import delete_expired_edges
        result = await delete_expired_edges(None)
        assert result == 0

    @pytest.mark.asyncio
    async def test_delete_edges_for_query_null_session(self):
        from app.db.repositories.similarity_repo import delete_edges_for_query
        result = await delete_edges_for_query(None, target_type="company", query_key="A")
        assert result == 0


# ---------------------------------------------------------------------------
# 16. SP-1 no-write-back: repo ops must not touch source tables
# ---------------------------------------------------------------------------

class TestNoWriteBack:
    @pytest.mark.asyncio
    async def test_repo_does_not_write_dossier(self, db):
        """Source tables exist but remain empty after similarity repo writes."""
        from app.db.models import CompanyDossier, DossierFailureMode, CrossExposure
        from app.db.repositories.similarity_repo import upsert_feature_vector, upsert_similarity_edge
        from sqlalchemy import select, func

        await upsert_feature_vector(db, **_make_vector_kwargs(entity_key="NWB_TEST"))
        await upsert_similarity_edge(db, **_make_edge_kwargs(query_key="NWB_Q", candidate_key="NWB_C"))
        await db.commit()

        for model in (CompanyDossier, DossierFailureMode, CrossExposure):
            result = await db.execute(select(func.count()).select_from(model))
            count = result.scalar_one()
            assert count == 0, (
                f"{model.__tablename__} should be empty after similarity repo writes. Got {count}."
            )

    @pytest.mark.asyncio
    async def test_repo_does_not_write_thesis_versions(self, db):
        from app.db.models import ThesisVersion
        from app.db.repositories.similarity_repo import upsert_feature_vector
        from sqlalchemy import select, func

        await upsert_feature_vector(db, **_make_vector_kwargs(entity_key="NWB_TV", target_type="thesis"))
        await db.commit()

        result = await db.execute(select(func.count()).select_from(ThesisVersion))
        assert result.scalar_one() == 0

    @pytest.mark.asyncio
    async def test_repo_does_not_write_historical_analogs(self, db):
        from app.db.models import HistoricalAnalog
        from app.db.repositories.similarity_repo import upsert_feature_vector
        from sqlalchemy import select, func

        await upsert_feature_vector(db, **_make_vector_kwargs(entity_key="NWB_HA", target_type="failure_mode"))
        await db.commit()

        result = await db.execute(select(func.count()).select_from(HistoricalAnalog))
        assert result.scalar_one() == 0


# ---------------------------------------------------------------------------
# 17–18. floor_passed=False and filtering
# ---------------------------------------------------------------------------

class TestFloorPassedFilter:
    @pytest.mark.asyncio
    async def test_below_floor_rows_can_be_stored(self, db):
        """floor_passed=False rows are stored (diagnostic) — no DDL block."""
        from app.db.repositories.similarity_repo import upsert_similarity_edge, get_similarity_edge

        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="FP_Q", candidate_key="FP_BELOW",
            floor_passed=False, score=0.10,
        ))
        await db.commit()

        row = await get_similarity_edge(
            db, target_type="failure_mode", query_key="FP_Q", candidate_key="FP_BELOW",
        )
        assert row is not None
        assert row.floor_passed is False

    @pytest.mark.asyncio
    async def test_floor_passed_only_filter(self, db):
        from app.db.repositories.similarity_repo import upsert_similarity_edge, list_similarity_edges

        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="FP_FILT_Q", candidate_key="FP_ABOVE", floor_passed=True, score=0.80,
        ))
        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="FP_FILT_Q", candidate_key="FP_BELOW", floor_passed=False, score=0.15,
        ))
        await db.commit()

        floor_rows = await list_similarity_edges(
            db, query_key="FP_FILT_Q", target_type="failure_mode", floor_passed_only=True,
        )
        assert all(e.floor_passed for e in floor_rows)
        assert any(e.candidate_key == "FP_ABOVE" for e in floor_rows)
        assert not any(e.candidate_key == "FP_BELOW" for e in floor_rows)


# ---------------------------------------------------------------------------
# 19. exclude_expired filter
# ---------------------------------------------------------------------------

class TestExcludeExpiredFilter:
    @pytest.mark.asyncio
    async def test_exclude_expired_filter(self, db):
        from app.db.repositories.similarity_repo import upsert_similarity_edge, list_similarity_edges

        past = datetime.now(timezone.utc) - timedelta(hours=1)

        # Insert expired edge
        exp_row = await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="EXF_Q", candidate_key="EXF_STALE",
        ))
        if exp_row:
            exp_row.expires_at = past

        # Insert active edge
        await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="EXF_Q", candidate_key="EXF_FRESH", ttl_hours=48,
        ))
        await db.commit()

        active = await list_similarity_edges(
            db, query_key="EXF_Q", target_type="failure_mode", exclude_expired=True,
        )
        keys = {e.candidate_key for e in active}
        assert "EXF_FRESH" in keys
        assert "EXF_STALE" not in keys


# ---------------------------------------------------------------------------
# 21. Self-exclusion is caller responsibility (no DDL block on same-key rows)
# ---------------------------------------------------------------------------

class TestSelfExclusion:
    @pytest.mark.asyncio
    async def test_same_key_rows_storable_at_db_level(self, db):
        """The DB doesn't block query_key == candidate_key; the scorer does."""
        from app.db.repositories.similarity_repo import upsert_similarity_edge, get_similarity_edge

        row = await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="SELF_TICKER", candidate_key="SELF_TICKER",
        ))
        await db.commit()
        # Repo stores it — the application-layer guard (SP-4 / scorer) prevents serving it
        assert row is not None


# ---------------------------------------------------------------------------
# 22. Empty contributions can be stored (orphan-score guard is service-layer)
# ---------------------------------------------------------------------------

class TestEmptyContributions:
    @pytest.mark.asyncio
    async def test_empty_contributions_storable(self, db):
        from app.db.repositories.similarity_repo import upsert_similarity_edge, get_similarity_edge

        row = await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="ORPHAN_Q", candidate_key="ORPHAN_C",
            contributions=[],   # orphan — scorer must reject, but repo stores
        ))
        await db.commit()
        found = await get_similarity_edge(
            db, target_type="failure_mode", query_key="ORPHAN_Q", candidate_key="ORPHAN_C",
        )
        assert found is not None
        assert found.contributions == []


# ---------------------------------------------------------------------------
# 23. user_id=None (shared global library) coexists with user-scoped edges
# ---------------------------------------------------------------------------

class TestUserIdScoping:
    @pytest.mark.asyncio
    async def test_global_and_user_edges_are_independent(self, db):
        """NULL and user-scoped edges are separate rows with different IDs.
        list_similarity_edges(user_id=None) is unfiltered (returns all rows);
        list_similarity_edges(user_id="user-abc") returns only that user's rows.
        Use get_similarity_edge to fetch the NULL-scoped row directly.
        """
        from app.db.repositories.similarity_repo import (
            upsert_similarity_edge, list_similarity_edges, get_similarity_edge,
        )

        global_row = await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="SCOPE_Q2", candidate_key="SCOPE_C2", user_id=None,
        ))
        user_row = await upsert_similarity_edge(db, **_make_edge_kwargs(
            query_key="SCOPE_Q2", candidate_key="SCOPE_C2", user_id="user-abc",
        ))
        await db.commit()

        # Stored as separate rows with different IDs
        assert global_row is not None
        assert user_row is not None
        assert global_row.id != user_row.id

        # list filtered by user_id returns only that user's rows
        user_edges = await list_similarity_edges(db, query_key="SCOPE_Q2", user_id="user-abc")
        user_ids = {e.id for e in user_edges}
        assert user_row.id in user_ids
        assert global_row.id not in user_ids

        # get with user_id=None fetches the NULL-scoped row
        fetched_global = await get_similarity_edge(
            db, target_type="failure_mode", query_key="SCOPE_Q2", candidate_key="SCOPE_C2", user_id=None,
        )
        assert fetched_global is not None
        assert fetched_global.id == global_row.id
