"""
Similarity Read Service — Phase 11 · Slice 6.

Exposes similarity results for internal inspection (admin routes, future
dossier facets) and builds the "Resembles" facet payload.

This module is READ-ONLY:
  - Reads exclusively from similarity_feature_vector and similarity_edge
    (via app.db.repositories.similarity_repo).
  - Never calls a feature builder or the scorer — no rebuild happens here,
    by design. If nothing has been built/scored yet for an entity, the
    answer is simply "no similarity data" (safe empty state), not a
    just-in-time build.
  - Never writes to any table, derived or source.

Descriptive-only boundary (Phase 11 SP-4, carried into Slice 6):
  - Nothing in this module is wired into conviction, stance, forecast, or
    recommendation paths. It has no import of forecasting/conviction code.
  - Every match returned to a caller carries its disanalogy and explanation
    contributions — a match missing either is dropped rather than surfaced,
    even though the Slice 3 scorer already guarantees both are present for
    any floor_passed edge (defense in depth at the read boundary).
  - A fixed disclaimer string accompanies every "Resembles" facet payload.

Filtering applied by default:
  - floor_passed=False (below-floor) edges are omitted.
  - Expired edges (`expires_at` in the past) are omitted.
  - Edges with empty contributions or blank disanalogy are omitted (should
    never occur given the Slice 3 orphan-score gate, but checked anyway).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DISCLAIMER = "Similarity is descriptive and does not imply identical outcomes."

_KNOWN_TARGET_TYPES = ("failure_mode", "company", "thesis")


async def _resolve_entity_label(session, target_type: str, entity_key: str) -> str:
    """Best-effort human-readable label for an entity_key, read from its
    own feature vector's categorical fields. Falls back to entity_key
    verbatim when no vector exists (e.g. it expired/was never built)."""
    try:
        from app.db.repositories.similarity_repo import get_feature_vector

        vec = await get_feature_vector(session, target_type=target_type, entity_key=entity_key)
        if vec is None:
            return entity_key
        cat = vec.categorical or {}
        if target_type == "failure_mode":
            ticker = cat.get("ticker", "")
            label = cat.get("failure_mode_label", "")
            if ticker and label:
                return f"{ticker} ({label})"
            return ticker or entity_key
        if target_type == "company":
            return cat.get("ticker", "") or entity_key
        if target_type == "thesis":
            ticker = cat.get("ticker", "")
            return f"{ticker} thesis snapshot" if ticker else entity_key
        return entity_key
    except Exception as exc:
        logger.debug(
            "[similarity_read_service] _resolve_entity_label failed for %s/%s: %r",
            target_type, entity_key, exc,
        )
        return entity_key


async def _format_match(session, edge) -> Optional[dict]:
    """Render one SimilarityEdge as a "Resembles" match dict.

    Returns None (caller filters it out) when disanalogy or contributions
    are missing — defense in depth on top of the Slice 3 orphan-score gate.
    """
    if not edge.disanalogy or not edge.contributions:
        logger.debug(
            "[similarity_read_service] dropping edge %s->%s: missing disanalogy or contributions",
            edge.query_key, edge.candidate_key,
        )
        return None
    target_label = await _resolve_entity_label(session, edge.target_type, edge.query_key)
    similar_to_label = await _resolve_entity_label(session, edge.target_type, edge.candidate_key)
    return {
        "target": target_label,
        "similar_to": similar_to_label,
        "score": edge.score,
        "why_similar": edge.contributions,
        "key_disanalogy": edge.disanalogy,
        "similarity_type": edge.target_type,
    }


async def get_similarity_for_target(
    session,
    target_type: str,
    target_id: str,
    *,
    limit: int = 5,
) -> List[dict]:
    """Return up to *limit* above-floor, non-expired, fully-explained matches
    for one entity (target_type, target_id). [] when session is None,
    nothing qualifies, or on error. Never rebuilds anything."""
    if session is None:
        return []
    try:
        from app.db.repositories.similarity_repo import list_similarity_edges

        edges = await list_similarity_edges(
            session,
            target_type=target_type,
            query_key=target_id,
            floor_passed_only=True,
            exclude_expired=True,
            limit=limit,
        )
        matches = []
        for edge in edges:
            formatted = await _format_match(session, edge)
            if formatted is not None:
                matches.append(formatted)
        return matches[:limit]
    except Exception as exc:
        logger.debug(
            "[similarity_read_service] get_similarity_for_target failed for %s/%s: %r",
            target_type, target_id, exc,
        )
        return []


async def _entity_keys_for_ticker(session, ticker: str, target_type: str) -> List[str]:
    """Resolve which similarity_feature_vector entity_keys belong to *ticker*
    for a given target_type, by reading existing vectors only."""
    from app.db.repositories.similarity_repo import get_feature_vector, list_feature_vectors

    if target_type == "company":
        vec = await get_feature_vector(session, target_type="company", entity_key=ticker)
        return [ticker] if vec is not None else []

    vectors = await list_feature_vectors(session, target_type=target_type, limit=500)
    return [v.entity_key for v in vectors if (v.categorical or {}).get("ticker") == ticker]


async def get_similarity_for_ticker(
    session,
    ticker: str,
    *,
    limit: int = 5,
) -> List[dict]:
    """Return up to *limit* matches across all similarity targets touching
    *ticker* (its company vector, all its failure-mode vectors, all its
    thesis vectors), sorted by score descending. [] when session is None,
    nothing qualifies, or on error. Never rebuilds anything."""
    if session is None:
        return []
    try:
        all_matches: List[dict] = []
        for target_type in _KNOWN_TARGET_TYPES:
            entity_keys = await _entity_keys_for_ticker(session, ticker, target_type)
            for entity_key in entity_keys:
                all_matches.extend(
                    await get_similarity_for_target(session, target_type, entity_key, limit=limit)
                )
        all_matches.sort(key=lambda m: m["score"], reverse=True)
        return all_matches[:limit]
    except Exception as exc:
        logger.debug(
            "[similarity_read_service] get_similarity_for_ticker failed for %s: %r", ticker, exc,
        )
        return []


async def get_resembles_facet_for_ticker(session, ticker: str) -> Dict:
    """Build the "Resembles" dossier facet payload for *ticker*.

    Always returns a well-formed dict, even when session is None or no
    similarity data exists yet (safe empty state):
        {"has_similarity": False, "ticker": ticker, "matches": [], "disclaimer": ...}
    """
    empty = {"has_similarity": False, "ticker": ticker, "matches": [], "disclaimer": DISCLAIMER}
    if session is None:
        return empty
    try:
        matches = await get_similarity_for_ticker(session, ticker, limit=5)
        return {
            "has_similarity": len(matches) > 0,
            "ticker": ticker,
            "matches": matches,
            "disclaimer": DISCLAIMER,
        }
    except Exception as exc:
        logger.debug(
            "[similarity_read_service] get_resembles_facet_for_ticker failed for %s: %r",
            ticker, exc,
        )
        return empty


async def build_similarity_status_snapshot(session) -> Dict:
    """Read-only observability snapshot for GET /admin/similarity-status.

    Flags + row counts only — never builds/rebuilds anything. DB-down-safe:
    degrades to zeros/disabled rather than raising.
    """
    from app.config import settings

    flags = {
        "similarity_build_enabled": settings.similarity_build_enabled,
        "similarity_scoring_enabled": settings.similarity_scoring_enabled,
        "similarity_targets_enabled": settings.similarity_targets_enabled,
        "similarity_shadow": settings.similarity_shadow,
    }
    safe_state = (not settings.similarity_build_enabled) or settings.similarity_shadow

    if session is None:
        return {
            "status": "disabled",
            "reason": "DATABASE_URL not set",
            "flags": flags,
            "vector_counts": {},
            "edge_counts": {},
            "safe_state": True,
        }
    try:
        from app.db.repositories.similarity_repo import list_feature_vectors, list_similarity_edges

        vector_counts = {}
        for target_type in _KNOWN_TARGET_TYPES:
            vectors = await list_feature_vectors(session, target_type=target_type, limit=10000)
            vector_counts[target_type] = len(vectors)

        edges = await list_similarity_edges(session, limit=10000)
        edge_counts = {
            "total": len(edges),
            "floor_passed": sum(1 for e in edges if e.floor_passed),
        }

        return {
            "status": "ok",
            "flags": flags,
            "vector_counts": vector_counts,
            "edge_counts": edge_counts,
            "safe_state": safe_state,
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "flags": flags,
            "vector_counts": {},
            "edge_counts": {},
            "safe_state": True,
        }
