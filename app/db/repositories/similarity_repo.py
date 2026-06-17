"""
Similarity repository — Phase 11 · Slice 1.

CRUD for similarity_feature_vector and similarity_edge.
All functions accept an AsyncSession as the first positional argument.
Passing None is safe: every function returns an empty/falsy/None value
rather than raising.  This mirrors the null-session contract used throughout
the loop, portfolio, account, and billing repos.

No scoring, no ranking, no delivery logic.  Pure DB access.
The similarity build/scoring flags are not consulted here; flag checks
belong in the service layer (Phase 11 Slices 2–3).

Safety invariants (Phase 11 SP-1 / SP-4):
  - This repo never writes to any source table (dossier, analogs, exposure,
    portfolio, thesis, delivery).
  - Edges returned here are descriptive cache rows only and must not be
    passed to any forecasting or conviction-scoring path.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from datetime import datetime, timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# Default TTL for similarity edges — 24 hours.
# Overridable by the scorer (Phase 11 Slice 3); stored here as the repo default.
DEFAULT_EDGE_TTL_HOURS: int = 24


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(_uuid_mod.uuid4())


# ---------------------------------------------------------------------------
# § FEATURE VECTORS
# ---------------------------------------------------------------------------

async def upsert_feature_vector(
    session,
    *,
    target_type: str,
    entity_key: str,
    categorical: dict,
    tag_set: list,
    numeric: dict,
    text_anchor: str = "",
    source_versions: dict,
    vector_schema: int = 1,
    user_id: Optional[str] = None,
    vector_id: Optional[str] = None,
) -> Optional[object]:
    """Insert or update a SimilarityFeatureVector row.

    Upsert is keyed on (target_type, entity_key, user_id).
    Returns the ORM row, or None when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import SimilarityFeatureVector
        from sqlalchemy import select

        stmt = select(SimilarityFeatureVector).where(
            SimilarityFeatureVector.target_type == target_type,
            SimilarityFeatureVector.entity_key  == entity_key,
            SimilarityFeatureVector.user_id     == user_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is None:
            row = SimilarityFeatureVector(
                id             = vector_id or _new_id(),
                target_type    = target_type,
                entity_key     = entity_key,
                categorical    = categorical,
                tag_set        = tag_set,
                numeric        = numeric,
                text_anchor    = text_anchor,
                source_versions = source_versions,
                vector_schema  = vector_schema,
                user_id        = user_id,
                built_at       = _now(),
            )
            session.add(row)
        else:
            row.categorical     = categorical
            row.tag_set         = tag_set
            row.numeric         = numeric
            row.text_anchor     = text_anchor
            row.source_versions = source_versions
            row.vector_schema   = vector_schema
            row.built_at        = _now()

        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[similarity_repo] upsert_feature_vector failed: %r", exc)
        return None


async def get_feature_vector(
    session,
    *,
    target_type: str,
    entity_key: str,
    user_id: Optional[str] = None,
) -> Optional[object]:
    """Return the SimilarityFeatureVector for (target_type, entity_key, user_id).

    Returns None when session is None or no row found.
    """
    if session is None:
        return None
    try:
        from app.db.models import SimilarityFeatureVector
        from sqlalchemy import select

        stmt = select(SimilarityFeatureVector).where(
            SimilarityFeatureVector.target_type == target_type,
            SimilarityFeatureVector.entity_key  == entity_key,
            SimilarityFeatureVector.user_id     == user_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.debug("[similarity_repo] get_feature_vector failed: %r", exc)
        return None


async def list_feature_vectors(
    session,
    *,
    target_type: Optional[str] = None,
    user_id: Optional[str] = None,
    vector_schema: Optional[int] = None,
    limit: int = 200,
) -> List[object]:
    """Return SimilarityFeatureVector rows matching the given filters.

    All filters are optional.  Returns [] when session is None or on error.
    Ordered by built_at descending.
    """
    if session is None:
        return []
    try:
        from app.db.models import SimilarityFeatureVector
        from sqlalchemy import select

        stmt = select(SimilarityFeatureVector)
        if target_type is not None:
            stmt = stmt.where(SimilarityFeatureVector.target_type == target_type)
        if user_id is not None:
            stmt = stmt.where(SimilarityFeatureVector.user_id == user_id)
        if vector_schema is not None:
            stmt = stmt.where(SimilarityFeatureVector.vector_schema == vector_schema)
        stmt = stmt.order_by(SimilarityFeatureVector.built_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[similarity_repo] list_feature_vectors failed: %r", exc)
        return []


async def delete_feature_vector(
    session,
    *,
    target_type: str,
    entity_key: str,
    user_id: Optional[str] = None,
) -> bool:
    """Delete a SimilarityFeatureVector row.  Returns True if a row was deleted."""
    if session is None:
        return False
    try:
        from app.db.models import SimilarityFeatureVector
        from sqlalchemy import select

        stmt = select(SimilarityFeatureVector).where(
            SimilarityFeatureVector.target_type == target_type,
            SimilarityFeatureVector.entity_key  == entity_key,
            SimilarityFeatureVector.user_id     == user_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return False
        await session.delete(row)
        await session.flush()
        return True
    except Exception as exc:
        logger.debug("[similarity_repo] delete_feature_vector failed: %r", exc)
        return False


# ---------------------------------------------------------------------------
# § SIMILARITY EDGES
# ---------------------------------------------------------------------------

async def upsert_similarity_edge(
    session,
    *,
    target_type: str,
    query_key: str,
    candidate_key: str,
    score: float,
    rank: int,
    contributions: list,
    headline: str = "",
    disanalogy: str = "",
    floor_passed: bool = False,
    score_schema: int = 1,
    user_id: Optional[str] = None,
    ttl_hours: int = DEFAULT_EDGE_TTL_HOURS,
    edge_id: Optional[str] = None,
) -> Optional[object]:
    """Insert or update a SimilarityEdge row.

    Upsert is keyed on (target_type, query_key, candidate_key, user_id).
    Returns the ORM row, or None when session is None.

    Callers MUST NOT pass floor_passed=True with empty contributions —
    the orphan-score invariant is enforced by the scorer (Phase 11 Slice 3)
    but this repo accepts whatever the caller sends so tests can cover the
    invariant boundary explicitly.
    """
    if session is None:
        return None
    try:
        from app.db.models import SimilarityEdge
        from sqlalchemy import select

        stmt = select(SimilarityEdge).where(
            SimilarityEdge.target_type   == target_type,
            SimilarityEdge.query_key     == query_key,
            SimilarityEdge.candidate_key == candidate_key,
            SimilarityEdge.user_id       == user_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        now = _now()
        expires = now + timedelta(hours=ttl_hours)

        if row is None:
            row = SimilarityEdge(
                id            = edge_id or _new_id(),
                target_type   = target_type,
                query_key     = query_key,
                candidate_key = candidate_key,
                score         = score,
                rank          = rank,
                contributions = contributions,
                headline      = headline,
                disanalogy    = disanalogy,
                floor_passed  = floor_passed,
                score_schema  = score_schema,
                user_id       = user_id,
                built_at      = now,
                expires_at    = expires,
            )
            session.add(row)
        else:
            row.score         = score
            row.rank          = rank
            row.contributions = contributions
            row.headline      = headline
            row.disanalogy    = disanalogy
            row.floor_passed  = floor_passed
            row.score_schema  = score_schema
            row.built_at      = now
            row.expires_at    = expires

        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[similarity_repo] upsert_similarity_edge failed: %r", exc)
        return None


async def get_similarity_edge(
    session,
    *,
    target_type: str,
    query_key: str,
    candidate_key: str,
    user_id: Optional[str] = None,
) -> Optional[object]:
    """Return the SimilarityEdge for the exact (target, query, candidate, user) tuple.

    Returns None when session is None or no row found.
    """
    if session is None:
        return None
    try:
        from app.db.models import SimilarityEdge
        from sqlalchemy import select

        stmt = select(SimilarityEdge).where(
            SimilarityEdge.target_type   == target_type,
            SimilarityEdge.query_key     == query_key,
            SimilarityEdge.candidate_key == candidate_key,
            SimilarityEdge.user_id       == user_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.debug("[similarity_repo] get_similarity_edge failed: %r", exc)
        return None


async def list_similarity_edges(
    session,
    *,
    target_type: Optional[str] = None,
    query_key: Optional[str] = None,
    user_id: Optional[str] = None,
    floor_passed_only: bool = False,
    score_schema: Optional[int] = None,
    exclude_expired: bool = False,
    limit: int = 100,
) -> List[object]:
    """Return SimilarityEdge rows matching the given filters.

    All filters are optional.  Returns [] when session is None or on error.
    Ordered by rank ascending (lower rank = better match).
    """
    if session is None:
        return []
    try:
        from app.db.models import SimilarityEdge
        from sqlalchemy import select

        stmt = select(SimilarityEdge)
        if target_type is not None:
            stmt = stmt.where(SimilarityEdge.target_type == target_type)
        if query_key is not None:
            stmt = stmt.where(SimilarityEdge.query_key == query_key)
        if user_id is not None:
            stmt = stmt.where(SimilarityEdge.user_id == user_id)
        if floor_passed_only:
            stmt = stmt.where(SimilarityEdge.floor_passed.is_(True))
        if score_schema is not None:
            stmt = stmt.where(SimilarityEdge.score_schema == score_schema)
        if exclude_expired:
            stmt = stmt.where(SimilarityEdge.expires_at > _now())
        stmt = stmt.order_by(SimilarityEdge.rank.asc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[similarity_repo] list_similarity_edges failed: %r", exc)
        return []


async def delete_expired_edges(
    session,
    *,
    batch_limit: int = 500,
) -> int:
    """Delete SimilarityEdge rows whose expires_at <= now().

    Returns the number of rows deleted.  Returns 0 when session is None.
    Called by the loop's TTL sweep step (Phase 11 Slice 4).
    """
    if session is None:
        return 0
    try:
        from app.db.models import SimilarityEdge
        from sqlalchemy import select, delete

        subq = (
            select(SimilarityEdge.id)
            .where(SimilarityEdge.expires_at <= _now())
            .limit(batch_limit)
            .scalar_subquery()
        )
        stmt = delete(SimilarityEdge).where(SimilarityEdge.id.in_(subq))
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
    except Exception as exc:
        logger.debug("[similarity_repo] delete_expired_edges failed: %r", exc)
        return 0


async def delete_edges_for_query(
    session,
    *,
    target_type: str,
    query_key: str,
    user_id: Optional[str] = None,
) -> int:
    """Delete all SimilarityEdge rows for a given (target_type, query_key, user_id).

    Used by the invalidation controller (Phase 11 Slice 4) when a query
    entity's feature vector is rebuilt.  Returns row count; 0 on error/no-op.
    """
    if session is None:
        return 0
    try:
        from app.db.models import SimilarityEdge
        from sqlalchemy import select, delete

        stmt = delete(SimilarityEdge).where(
            SimilarityEdge.target_type == target_type,
            SimilarityEdge.query_key   == query_key,
            SimilarityEdge.user_id     == user_id,
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
    except Exception as exc:
        logger.debug("[similarity_repo] delete_edges_for_query failed: %r", exc)
        return 0
