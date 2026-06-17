"""
Similarity Scorer — Phase 11 · Slice 3.

Scores T4 (failure-mode) feature vectors pairwise and materialises
similarity_edge rows. No other target type, no delivery, no forecasting
or conviction integration.

Reuses evidence_engine's scoring *principles* rather than forking them:
  - concern-tag Jaccard, mechanism match, setup/context/macro agreement —
    the same weighted composite shape as evidence_engine._score_analog.
  - _mechanism_score, RELEVANCE_FLOOR, DISANALOGY_PENALTY are imported
    directly from app.evidence_engine (SP-2: reuse wholesale, never fork).
  - The one structural difference from _score_analog: that function scores
    an analog against a SetupFingerprint built from live thesis context;
    this scorer compares two materialised SimilarityFeatureVector rows
    (entity vs. entity), since neither side here is a live fingerprint.

Explainability contract (mandatory, enforced in code — not optional):
  - Every edge carries `contributions`: a list of {feature, shared_value,
    weight, partial_score} dicts, one per scoring component that
    contributed > 0.
  - Every edge carries a `headline` built from its strongest contribution.
  - Every edge carries a non-empty `disanalogy` naming a concrete
    difference between the two entities (or, if none is found, an explicit
    "directional, not confirmed" caveat) — disanalogy is never blank.
  - Orphan-score gate: an edge is never stored with floor_passed=True and
    empty contributions. If scoring math clears the floor but no
    component produced shared structure (should not happen given the
    floor itself requires positive contribution), floor_passed is forced
    to False rather than shipping an unexplained "match."

Safety invariants (Phase 11 SP-1 / SP-4):
  - This module never writes to similarity_feature_vector, dossier_*,
    historical_analogs, company_dossier, cross_exposures, thesis_versions,
    or any delivery table. It only reads similarity_feature_vector and
    writes similarity_edge.
  - No ranking/scoring output here is wired into forecasting or conviction
    paths — edges are descriptive cache rows only (Slice 4+ delivery is
    out of scope for this module).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.evidence_engine import DISANALOGY_PENALTY, RELEVANCE_FLOOR, _mechanism_score

logger = logging.getLogger(__name__)

# Bumped when the scoring formula or weight profile changes.
SCORE_VERSION: int = 1

# Component weights — mirrors evidence_engine._score_analog's composite shape.
_TAG_WEIGHT = 0.40
_MECHANISM_WEIGHT = 0.30
_VALUATION_REGIME_WEIGHT = 0.075
_GROWTH_PHASE_WEIGHT = 0.075
_SECTOR_WEIGHT = 0.05
_BUSINESS_MODEL_WEIGHT = 0.05
_MACRO_WEIGHT = 0.05


def _jaccard(a: set, b: set) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def score_failure_mode_pair(query_vec, candidate_vec) -> Dict:
    """Score two T4 SimilarityFeatureVector rows against each other.

    Returns a dict: {score, contributions, headline, disanalogy, floor_passed}.
    Pure function of the two vectors' stored fields — deterministic by
    construction (no randomness, no I/O, no clock reads).
    """
    q_cat = query_vec.categorical or {}
    c_cat = candidate_vec.categorical or {}
    q_tags = set(query_vec.tag_set or [])
    c_tags = set(candidate_vec.tag_set or [])

    contributions: List[dict] = []

    # 1. Concern-tag Jaccard
    tag_score = _jaccard(q_tags, c_tags)
    tag_partial = round(_TAG_WEIGHT * tag_score, 4)
    if tag_partial > 0:
        contributions.append({
            "feature": "concern_tags",
            "shared_value": sorted(q_tags & c_tags),
            "weight": _TAG_WEIGHT,
            "partial_score": tag_partial,
        })

    # 2. Mechanism match (reused from evidence_engine — exact=1.0, sibling=0.5)
    mech_score = _mechanism_score(q_cat.get("mechanism", ""), c_cat.get("mechanism", ""))
    mech_partial = round(_MECHANISM_WEIGHT * mech_score, 4)
    if mech_partial > 0:
        contributions.append({
            "feature": "mechanism",
            "shared_value": c_cat.get("mechanism", ""),
            "weight": _MECHANISM_WEIGHT,
            "partial_score": mech_partial,
        })

    # 3. Setup match: valuation_regime + growth_phase
    setup_score = 0.0
    setup_matches: Dict[str, str] = {}
    if q_cat.get("valuation_regime") and q_cat.get("valuation_regime") == c_cat.get("valuation_regime"):
        setup_score += _VALUATION_REGIME_WEIGHT
        setup_matches["valuation_regime"] = q_cat["valuation_regime"]
    if q_cat.get("growth_phase") and q_cat.get("growth_phase") == c_cat.get("growth_phase"):
        setup_score += _GROWTH_PHASE_WEIGHT
        setup_matches["growth_phase"] = q_cat["growth_phase"]
    if setup_score > 0:
        contributions.append({
            "feature": "setup",
            "shared_value": setup_matches,
            "weight": _VALUATION_REGIME_WEIGHT + _GROWTH_PHASE_WEIGHT,
            "partial_score": round(setup_score, 4),
        })

    # 4. Context: sector + business_model
    context_score = 0.0
    context_matches: Dict[str, str] = {}
    if q_cat.get("sector") and q_cat.get("sector") == c_cat.get("sector"):
        context_score += _SECTOR_WEIGHT
        context_matches["sector"] = q_cat["sector"]
    if q_cat.get("business_model") and q_cat.get("business_model") == c_cat.get("business_model"):
        context_score += _BUSINESS_MODEL_WEIGHT
        context_matches["business_model"] = q_cat["business_model"]
    if context_score > 0:
        contributions.append({
            "feature": "context",
            "shared_value": context_matches,
            "weight": _SECTOR_WEIGHT + _BUSINESS_MODEL_WEIGHT,
            "partial_score": round(context_score, 4),
        })

    # 5. Macro regime agreement
    macro_score = 0.0
    if q_cat.get("macro_regime") and q_cat.get("macro_regime") == c_cat.get("macro_regime"):
        macro_score = _MACRO_WEIGHT
        contributions.append({
            "feature": "macro_regime",
            "shared_value": q_cat["macro_regime"],
            "weight": _MACRO_WEIGHT,
            "partial_score": round(macro_score, 4),
        })

    raw = tag_partial + mech_partial + setup_score + context_score + macro_score
    # Flat disanalogy penalty — the same structural honesty tax evidence_engine
    # applies to every analog score (forces a deliberate floor, not a freebie).
    raw -= DISANALOGY_PENALTY
    score = max(0.0, min(1.0, raw))

    floor_passed = score >= RELEVANCE_FLOOR
    # Orphan-score gate: never ship floor_passed=True with nothing to show for it.
    if floor_passed and not contributions:
        logger.debug(
            "[similarity_scorer] orphan score suppressed: score=%.4f had no contributions", score,
        )
        floor_passed = False

    headline = _build_headline(contributions, c_cat)
    disanalogy = _build_disanalogy(q_cat, c_cat, q_tags, c_tags)

    return {
        "score": score,
        "contributions": contributions,
        "headline": headline,
        "disanalogy": disanalogy,
        "floor_passed": floor_passed,
    }


def _build_headline(contributions: List[dict], c_cat: dict) -> str:
    if not contributions:
        return "No shared structural features identified above the relevance floor."

    top = max(contributions, key=lambda c: c["partial_score"])
    feature = top["feature"]

    if feature == "concern_tags":
        tags = ", ".join(top["shared_value"]) or "overlapping concern tags"
        return f"Both failure modes share concern tags: {tags}."
    if feature == "mechanism":
        return f"Both failure modes operate via the same mechanism: {c_cat.get('mechanism', 'unspecified')}."
    if feature == "setup":
        parts = ", ".join(f"{k}={v}" for k, v in top["shared_value"].items())
        return f"Both share setup characteristics: {parts}."
    if feature == "context":
        parts = ", ".join(f"{k}={v}" for k, v in top["shared_value"].items())
        return f"Both share business context: {parts}."
    if feature == "macro_regime":
        return f"Both occurred under the same macro regime: {top['shared_value']}."
    return "Structural resemblance identified across tracked features."


def _build_disanalogy(q_cat: dict, c_cat: dict, q_tags: set, c_tags: set) -> str:
    """Name a concrete difference between the two entities — mandatory, never blank."""
    diffs: List[str] = []
    for field, label in (
        ("ticker", "company"),
        ("sector", "sector"),
        ("business_model", "business model"),
        ("valuation_regime", "valuation regime"),
        ("growth_phase", "growth phase"),
        ("macro_regime", "macro regime"),
        ("mechanism", "mechanism"),
    ):
        qv, cv = q_cat.get(field, ""), c_cat.get(field, "")
        if qv and cv and qv != cv:
            diffs.append(f"{label} differs ({qv} vs {cv})")

    only_q = q_tags - c_tags
    only_c = c_tags - q_tags
    if only_q or only_c:
        parts = []
        if only_q:
            parts.append(f"query-only tags {sorted(only_q)}")
        if only_c:
            parts.append(f"candidate-only tags {sorted(only_c)}")
        diffs.append("concern tags diverge: " + "; ".join(parts))

    if not diffs:
        return (
            "No tracked structural differences identified; treat this as a "
            "directional, not confirmed, resemblance."
        )
    if len(diffs) == 1:
        return diffs[0]
    return f"{diffs[0]} (also: {'; '.join(diffs[1:])})"


# ---------------------------------------------------------------------------
# Edge builders
# ---------------------------------------------------------------------------

async def build_failure_mode_similarity_edges(
    session,
    query_entity_key: str,
    *,
    user_id: Optional[str] = None,
    max_candidates: int = 500,
) -> List[object]:
    """Score *query_entity_key* against every other T4 feature vector and
    upsert the resulting similarity_edge rows, ranked by score descending.

    Returns the list of upserted SimilarityEdge ORM rows (both above- and
    below-floor — below-floor rows are stored for diagnostics only, per the
    similarity_edge schema's documented intent). Returns [] when session is
    None, the query vector does not exist, or on error.
    """
    if session is None:
        return []
    try:
        from app.db.repositories.similarity_repo import (
            get_feature_vector, list_feature_vectors, upsert_similarity_edge,
        )

        query_vec = await get_feature_vector(
            session, target_type="failure_mode", entity_key=query_entity_key, user_id=user_id,
        )
        if query_vec is None:
            logger.debug(
                "[similarity_scorer] query feature vector not found for entity_key=%s",
                query_entity_key,
            )
            return []

        candidates = await list_feature_vectors(
            session, target_type="failure_mode", user_id=user_id, limit=max_candidates,
        )

        scored = []
        for cand in candidates:
            if cand.entity_key == query_entity_key:
                continue
            result = score_failure_mode_pair(query_vec, cand)
            scored.append((result, cand))

        # Deterministic ordering: score desc, then candidate_key asc as tiebreak.
        scored.sort(key=lambda item: (-item[0]["score"], item[1].entity_key))

        edges = []
        for rank, (result, cand) in enumerate(scored, start=1):
            edge = await upsert_similarity_edge(
                session,
                target_type="failure_mode",
                query_key=query_entity_key,
                candidate_key=cand.entity_key,
                score=result["score"],
                rank=rank,
                contributions=result["contributions"],
                headline=result["headline"],
                disanalogy=result["disanalogy"],
                floor_passed=result["floor_passed"],
                score_schema=SCORE_VERSION,
                user_id=user_id,
            )
            if edge is not None:
                edges.append(edge)
        return edges
    except Exception as exc:
        logger.debug(
            "[similarity_scorer] build_failure_mode_similarity_edges failed for %s: %r",
            query_entity_key, exc,
        )
        return []


async def build_failure_mode_similarity_edges_for_ticker(
    session,
    ticker: str,
    *,
    user_id: Optional[str] = None,
    max_candidates: int = 500,
) -> List[object]:
    """Build similarity_edge rows for every T4 feature vector belonging to *ticker*.

    Returns the combined list of upserted edges across all of the ticker's
    failure-mode vectors. Returns [] when session is None, the ticker has no
    T4 vectors, or on error.
    """
    if session is None:
        return []
    try:
        from app.db.repositories.similarity_repo import list_feature_vectors

        all_vectors = await list_feature_vectors(
            session, target_type="failure_mode", user_id=user_id, limit=max_candidates,
        )
        ticker_vectors = [v for v in all_vectors if (v.categorical or {}).get("ticker") == ticker]

        edges: List[object] = []
        for vec in ticker_vectors:
            built = await build_failure_mode_similarity_edges(
                session, vec.entity_key, user_id=user_id, max_candidates=max_candidates,
            )
            edges.extend(built)
        return edges
    except Exception as exc:
        logger.debug(
            "[similarity_scorer] build_failure_mode_similarity_edges_for_ticker failed for %s: %r",
            ticker, exc,
        )
        return []


async def build_failure_mode_similarity_edges_for_all(
    session,
    *,
    limit: Optional[int] = None,
    user_id: Optional[str] = None,
    max_candidates: int = 500,
) -> List[object]:
    """Build similarity_edge rows for every T4 feature vector in the system.

    Returns the combined list of upserted edges. Returns [] when session is
    None or on error.
    """
    if session is None:
        return []
    try:
        from app.db.repositories.similarity_repo import list_feature_vectors

        vectors = await list_feature_vectors(
            session, target_type="failure_mode", user_id=user_id, limit=limit or max_candidates,
        )

        edges: List[object] = []
        for vec in vectors:
            built = await build_failure_mode_similarity_edges(
                session, vec.entity_key, user_id=user_id, max_candidates=max_candidates,
            )
            edges.extend(built)
        return edges
    except Exception as exc:
        logger.debug(
            "[similarity_scorer] build_failure_mode_similarity_edges_for_all failed: %r", exc,
        )
        return []
