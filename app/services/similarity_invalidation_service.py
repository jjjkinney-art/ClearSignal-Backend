"""
Similarity Invalidation + Rebuild Orchestration — Phase 11 · Slice 5.

Detects stale similarity_feature_vector rows and re-runs the existing
Slice 2/4 feature builders (and, only when explicitly approved, the Slice 3
T4 scorer) to refresh them. Also exposes expired-edge cleanup via the
existing similarity_repo.delete_expired_edges.

This module does NOT:
  - introduce any new similarity target beyond T1/T2/T4 (already built)
  - write to any source table (company_dossier, dossier_*, historical_analogs,
    thesis_versions, cross_exposures) — staleness detection only READS them
    to compare live state against what a vector's source_versions/numeric
    snapshot recorded at build time
  - register a loop producer or wire autonomous scheduling — that remains
    Slice 6+ territory; the functions here are plain async callables meant
    to be invoked manually, from a test, or from a future producer
  - perform delivery of any kind
  - import anything from forecasting/conviction/notification/delivery code

Staleness model (per target_type):
  - TTL: any vector older than `ttl_hours` (default 24) is stale regardless
    of source state — a simple time-based cache-expiry signal.
  - failure_mode: stale if the live DossierFailureMode.sequence_stage no
    longer matches the value recorded in the vector's `numeric` snapshot, or
    if the DossierFailureMode row itself is gone (orphaned vector).
  - company: stale if company_dossier.row_version (bumped on every head
    write) or dossier_core_debate.version no longer matches what is recorded
    in `source_versions`, or if the company_dossier head row is gone.
  - thesis: thesis_versions rows are immutable once written, so the only
    drift signal is dossier_variant.version (recorded in `source_versions`)
    moving on, or the thesis_versions row itself being gone.

Rebuilding a vector is just calling the existing builder again — the
builder's upsert-by-unique-key behavior (Slice 2/4) naturally replaces the
stale snapshot in place. No separate "mark stale" column exists on
similarity_feature_vector and none is added here; identification +
rebuild-in-place is sufficient and keeps the schema unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_VECTOR_TTL_HOURS: int = 24

_SUPPORTED_TARGET_TYPES = ("failure_mode", "company", "thesis")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _scoring_approved(run_scoring: Optional[bool]) -> bool:
    """Whether the T4 scorer should run as part of a rebuild.

    Explicit `run_scoring` (test/caller override) wins. Otherwise falls back
    to settings.similarity_scoring_enabled, which defaults to False — so
    rebuilds are feature-vector-only unless scoring has been deliberately
    turned on.
    """
    if run_scoring is not None:
        return run_scoring
    try:
        from app.config import settings
        return bool(getattr(settings, "similarity_scoring_enabled", False))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Staleness detection
# ---------------------------------------------------------------------------

async def is_vector_stale(session, vector, *, ttl_hours: int = DEFAULT_VECTOR_TTL_HOURS) -> bool:
    """Return True if *vector* should be rebuilt.

    Never raises — any error during the (read-only) live-state comparison
    is treated as "not stale" (fail closed on rebuild churn, not on safety;
    a vector that fails this check simply isn't refreshed this pass).
    """
    if session is None or vector is None:
        return False
    try:
        if vector.built_at is not None:
            built_at = vector.built_at
            if built_at.tzinfo is None:
                built_at = built_at.replace(tzinfo=timezone.utc)
            age_seconds = (_now() - built_at).total_seconds()
            if age_seconds > ttl_hours * 3600:
                return True

        from sqlalchemy import select

        if vector.target_type == "failure_mode":
            from app.db.models import DossierFailureMode

            fm = (
                await session.execute(
                    select(DossierFailureMode).where(DossierFailureMode.id == vector.entity_key)
                )
            ).scalar_one_or_none()
            if fm is None:
                return True  # orphaned — source row gone
            stored_stage = (vector.numeric or {}).get("sequence_stage")
            if stored_stage is not None and float(fm.sequence_stage) != float(stored_stage):
                return True
            return False

        if vector.target_type == "company":
            from app.db.models import CompanyDossier, DossierCoreDebate

            head = (
                await session.execute(
                    select(CompanyDossier).where(CompanyDossier.ticker == vector.entity_key)
                )
            ).scalar_one_or_none()
            if head is None:
                return True
            stored_rv = (vector.source_versions or {}).get("company_dossier_row_version")
            if stored_rv is not None and head.row_version != stored_rv:
                return True

            debate = (
                await session.execute(
                    select(DossierCoreDebate).where(DossierCoreDebate.ticker == vector.entity_key)
                )
            ).scalar_one_or_none()
            stored_debate_v = (vector.source_versions or {}).get("dossier_core_debate_version")
            live_debate_v = debate.version if debate is not None else None
            if stored_debate_v != live_debate_v:
                return True
            return False

        if vector.target_type == "thesis":
            from app.db.models import ThesisVersion, DossierVariant

            thesis = (
                await session.execute(
                    select(ThesisVersion).where(ThesisVersion.id == vector.entity_key)
                )
            ).scalar_one_or_none()
            if thesis is None:
                return True

            variant = (
                await session.execute(
                    select(DossierVariant).where(DossierVariant.ticker == thesis.ticker)
                )
            ).scalar_one_or_none()
            stored_variant_v = (vector.source_versions or {}).get("dossier_variant_version")
            live_variant_v = variant.version if variant is not None else None
            if stored_variant_v != live_variant_v:
                return True
            return False

        # Unknown/unsupported target_type — leave untouched.
        return False
    except Exception as exc:
        logger.debug(
            "[similarity_invalidation_service] is_vector_stale failed for %s/%s: %r",
            getattr(vector, "target_type", "?"), getattr(vector, "entity_key", "?"), exc,
        )
        return False


async def find_stale_vectors(
    session,
    *,
    target_type: Optional[str] = None,
    ttl_hours: int = DEFAULT_VECTOR_TTL_HOURS,
    limit: int = 200,
) -> List[object]:
    """Return the subset of similarity_feature_vector rows that are stale.

    Returns [] when session is None or on error. This is the "rebuild
    candidates" list — callers decide whether/how to act on it.
    """
    if session is None:
        return []
    try:
        from app.db.repositories.similarity_repo import list_feature_vectors

        candidates = await list_feature_vectors(session, target_type=target_type, limit=limit)
        stale = []
        for vector in candidates:
            if await is_vector_stale(session, vector, ttl_hours=ttl_hours):
                stale.append(vector)
        return stale
    except Exception as exc:
        logger.debug("[similarity_invalidation_service] find_stale_vectors failed: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Expired-edge cleanup
# ---------------------------------------------------------------------------

async def cleanup_expired_edges(session, *, batch_limit: int = 500) -> int:
    """Delete expired similarity_edge rows via similarity_repo.delete_expired_edges.

    Returns the number of rows deleted; 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.repositories.similarity_repo import delete_expired_edges

        return await delete_expired_edges(session, batch_limit=batch_limit)
    except Exception as exc:
        logger.debug("[similarity_invalidation_service] cleanup_expired_edges failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# Rebuild orchestration
# ---------------------------------------------------------------------------

async def rebuild_similarity_for_target(
    session,
    target_type: str,
    target_id: str,
    *,
    run_scoring: Optional[bool] = None,
) -> Optional[object]:
    """Rebuild the single feature vector for (target_type, target_id).

    target_id meaning is target_type-dependent:
      - failure_mode -> DossierFailureMode.id
      - company      -> ticker
      - thesis       -> ThesisVersion.id

    For failure_mode, also re-runs the Slice 3 T4 scorer for that entity
    when scoring is approved (explicit `run_scoring` or
    settings.similarity_scoring_enabled).

    Returns the rebuilt ORM vector row, or None when session is None, the
    target_type is unsupported, the underlying builder returns None
    (missing/orphaned source), or on error.
    """
    if session is None:
        return None
    if target_type not in _SUPPORTED_TARGET_TYPES:
        logger.debug(
            "[similarity_invalidation_service] unsupported target_type=%s for rebuild",
            target_type,
        )
        return None
    try:
        if target_type == "failure_mode":
            from app.services.similarity_feature_builder import build_failure_mode_feature_vector

            vector = await build_failure_mode_feature_vector(session, target_id)
            if vector is not None and _scoring_approved(run_scoring):
                from app.services.similarity_scorer import build_failure_mode_similarity_edges

                await build_failure_mode_similarity_edges(session, target_id)
            return vector

        if target_type == "company":
            from app.services.similarity_feature_builder import build_company_feature_vector

            return await build_company_feature_vector(session, target_id)

        if target_type == "thesis":
            from app.services.similarity_feature_builder import build_thesis_feature_vector

            return await build_thesis_feature_vector(session, target_id)

        return None
    except Exception as exc:
        logger.debug(
            "[similarity_invalidation_service] rebuild_similarity_for_target failed for %s/%s: %r",
            target_type, target_id, exc,
        )
        return None


async def rebuild_similarity_for_ticker(
    session,
    ticker: str,
    *,
    run_scoring: Optional[bool] = None,
) -> Dict[str, object]:
    """Rebuild every similarity feature vector touching *ticker*:
      - the T1 company vector
      - all T4 failure-mode vectors for the ticker
      - all T2 thesis vectors for the ticker's thesis_versions rows

    When scoring is approved, also re-runs the T4 scorer for each rebuilt
    failure-mode vector.

    Returns {"company": vector_or_None, "failure_modes": [...], "theses": [...]}.
    Returns the same shape with empty/None values when session is None or
    on error — never raises.
    """
    empty_result: Dict[str, object] = {"company": None, "failure_modes": [], "theses": []}
    if session is None:
        return empty_result
    try:
        from sqlalchemy import select
        from app.db.models import ThesisVersion
        from app.services.similarity_feature_builder import (
            build_company_feature_vector,
            build_failure_mode_feature_vectors_for_ticker,
            build_thesis_feature_vector,
        )

        company_vector = await build_company_feature_vector(session, ticker)
        failure_mode_vectors = await build_failure_mode_feature_vectors_for_ticker(session, ticker)

        thesis_ids = (
            await session.execute(select(ThesisVersion.id).where(ThesisVersion.ticker == ticker))
        ).scalars().all()
        thesis_vectors = []
        for thesis_id in thesis_ids:
            built = await build_thesis_feature_vector(session, thesis_id)
            if built is not None:
                thesis_vectors.append(built)

        if failure_mode_vectors and _scoring_approved(run_scoring):
            from app.services.similarity_scorer import build_failure_mode_similarity_edges

            for fm_vector in failure_mode_vectors:
                await build_failure_mode_similarity_edges(session, fm_vector.entity_key)

        return {
            "company": company_vector,
            "failure_modes": failure_mode_vectors,
            "theses": thesis_vectors,
        }
    except Exception as exc:
        logger.debug(
            "[similarity_invalidation_service] rebuild_similarity_for_ticker failed for %s: %r",
            ticker, exc,
        )
        return empty_result


async def rebuild_similarity_batch(
    session,
    *,
    limit: Optional[int] = None,
    ttl_hours: int = DEFAULT_VECTOR_TTL_HOURS,
    run_scoring: Optional[bool] = None,
) -> List[object]:
    """Find stale vectors (bounded by *limit*) and rebuild each exactly once.

    Returns the list of rebuilt ORM vector rows. Returns [] when session is
    None, there are no stale vectors, or on error.
    """
    if session is None:
        return []
    try:
        fetch_limit = limit if limit is not None else 200
        stale = await find_stale_vectors(session, ttl_hours=ttl_hours, limit=fetch_limit)
        if limit is not None:
            stale = stale[:limit]

        rebuilt: List[object] = []
        seen: set = set()
        for vector in stale:
            key = (vector.target_type, vector.entity_key)
            if key in seen:
                continue
            seen.add(key)
            result = await rebuild_similarity_for_target(
                session, vector.target_type, vector.entity_key, run_scoring=run_scoring,
            )
            if result is not None:
                rebuilt.append(result)
        return rebuilt
    except Exception as exc:
        logger.debug("[similarity_invalidation_service] rebuild_similarity_batch failed: %r", exc)
        return []
