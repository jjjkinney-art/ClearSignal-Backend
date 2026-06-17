"""
Decision Rebuild + Storage Pipeline — Phase 13 · Slice 5.

Orchestrates the full Phase 13 pipeline for one or many candidates:

    candidate_builder
        → ranking_engine
        → explainability_service
        → validate_decision_explanation   ← hard gate (SP-5)
        → decision_repo  (upsert_decision_priority + add_decision_evidence
                          + add_ranking_log)

Core rule: No row may be stored unless validate_decision_explanation returns
(True, None). A failed explanation aborts the entire candidate — no
decision_priority row, no decision_evidence row, no ranking log.

Stale detection: a stored DecisionPriority is considered stale when:
    - decision_schema differs from CURRENT_DECISION_SCHEMA, OR
    - expires_at <= now()

Safety invariants (SP-5)
------------------------
    - Does NOT write to any source table: no dossier, no forecast, no
      similarity, no portfolio, no delivery, no notification, no conviction.
    - Does NOT create Notification rows.
    - Does NOT import from delivery, notification, or conviction modules.
    - flag gate: decision_build_enabled must be True to persist; when False
      (or in shadow mode only) the pipeline runs but nothing is written.
    - decision_shadow = True: pipeline runs, ranking logged, no priority upsert.

Priority bucket mapping (score → label):
    ≥ 0.80  → critical
    ≥ 0.60  → high
    ≥ 0.40  → medium
    ≥ 0.20  → low
    < 0.20  → informational
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Current schema version — bump to invalidate all stored rows when the
# scoring formula or weight config changes.
CURRENT_DECISION_SCHEMA: int = 1

# Default TTL for new DecisionPriority rows (hours).
_DEFAULT_TTL_HOURS: int = 24

# ---------------------------------------------------------------------------
# Score → priority bucket
# ---------------------------------------------------------------------------

_BUCKET_THRESHOLDS: List[Tuple[float, str]] = [
    (0.80, "critical"),
    (0.60, "high"),
    (0.40, "medium"),
    (0.20, "low"),
    (0.00, "informational"),
]


def _score_to_bucket(score: float) -> str:
    for threshold, label in _BUCKET_THRESHOLDS:
        if score >= threshold:
            return label
    return "informational"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------

def is_decision_stale(priority_row) -> bool:
    """Return True if *priority_row* is expired or on an old schema version.

    Safe to call with None (returns True — treat missing as stale).
    """
    if priority_row is None:
        return True
    try:
        if getattr(priority_row, "decision_schema", 0) != CURRENT_DECISION_SCHEMA:
            return True
        expires = getattr(priority_row, "expires_at", None)
        if expires is None:
            return True
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires <= _now()
    except Exception:
        return True


async def find_stale_decisions(
    session,
    *,
    candidate_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 200,
) -> List[Any]:
    """Return DecisionPriority rows that are stale (expired or schema-old).

    Returns [] when session is None or on error.
    """
    if session is None:
        return []
    try:
        from app.db.repositories.decision_repo import list_decision_priorities

        rows = await list_decision_priorities(
            session,
            candidate_type=candidate_type,
            entity_type=entity_type,
            limit=limit,
        )
        return [r for r in rows if is_decision_stale(r)]
    except Exception as exc:
        logger.debug("[decision_invalidation] find_stale_decisions error: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Single-candidate pipeline
# ---------------------------------------------------------------------------

async def _run_pipeline_for_candidate(
    session,
    candidate: dict,
    *,
    user_id: Optional[str],
    ttl_hours: int,
    snapshot_reason: str,
    rank_position: int,
    dry_run: bool,
) -> Dict[str, Any]:
    """Run the full pipeline for one candidate dict.

    Returns a result dict with keys:
        stored     bool   — True if a priority row was written
        blocked    bool   — True if explanation validation blocked storage
        block_reason str  — validation failure message (or "")
        priority_id str   — id of the upserted row (or "")
        evidence_count int — number of evidence rows written
        log_id     str   — id of the ranking log row (or "")
        error      str   — unexpected exception message (or "")
    """
    result: Dict[str, Any] = {
        "stored": False,
        "blocked": False,
        "block_reason": "",
        "priority_id": "",
        "evidence_count": 0,
        "log_id": "",
        "error": "",
    }

    try:
        # ── 1. Rank ─────────────────────────────────────────────────────────
        from app.services.decision_ranking_engine import rank_candidate
        ranking = rank_candidate(candidate)

        # ── 2. Explain ──────────────────────────────────────────────────────
        from app.services.decision_explainability_service import (
            build_decision_explanation,
            validate_decision_explanation,
        )
        explanation = build_decision_explanation(candidate, ranking)

        # ── 3. Validate — hard gate ──────────────────────────────────────────
        ok, reason = validate_decision_explanation(explanation)
        if not ok:
            result["blocked"] = True
            result["block_reason"] = reason or "validation failed"
            logger.debug(
                "[decision_invalidation] blocked candidate %s/%s: %s",
                candidate.get("candidate_type"),
                candidate.get("source_id"),
                reason,
            )
            return result

        # ── 4. Map explanation → storage fields ─────────────────────────────
        decision_score = ranking.get("decision_score", 0.0)
        bucket = _score_to_bucket(decision_score)

        decision_reason = " ".join(explanation.get("why_important", []))
        why_now_text    = " ".join(explanation.get("why_now", []))
        deprioritizers  = explanation.get("deprioritizers", [])
        evidence_items  = explanation.get("evidence", [])

        # ── 5. Persist (skip if dry_run) ────────────────────────────────────
        if dry_run or session is None:
            result["stored"] = False
            return result

        from app.db.repositories.decision_repo import (
            upsert_decision_priority,
            delete_evidence_for_priority,
            add_decision_evidence,
            add_ranking_log,
        )

        priority_row = await upsert_decision_priority(
            session,
            candidate_type      = candidate.get("candidate_type", ""),
            entity_type         = candidate.get("entity_type", ""),
            entity_key          = candidate.get("ticker") or candidate.get("entity_id", ""),
            source_ref          = candidate.get("source_id", ""),
            decision_priority   = bucket,
            decision_rank_score = decision_score,
            attention_score     = ranking.get("attention_score", 0.0),
            urgency_score       = ranking.get("urgency_score", 0.0),
            impact_score        = ranking.get("impact_score", 0.0),
            confidence_score    = ranking.get("confidence_multiplier", 0.0),
            uncertainty_score   = ranking.get("uncertainty_discount", 0.0),
            decision_reason     = decision_reason,
            why_now             = why_now_text,
            deprioritizers      = deprioritizers,
            evidence_summary    = evidence_items,
            source_versions     = candidate.get("source_versions") or {},
            decision_schema     = CURRENT_DECISION_SCHEMA,
            user_id             = user_id,
            ttl_hours           = ttl_hours,
        )

        if priority_row is None:
            result["error"] = "upsert_decision_priority returned None"
            return result

        priority_id = getattr(priority_row, "id", "")
        result["priority_id"] = priority_id

        # Clear stale evidence then re-insert
        await delete_evidence_for_priority(session, priority_id=priority_id)

        evidence_count = 0
        for idx, item in enumerate(evidence_items):
            ev_row = await add_decision_evidence(
                session,
                priority_id  = priority_id,
                source_type  = candidate.get("source_type", ""),
                source_id    = candidate.get("source_id", ""),
                dimension    = "attention",
                contribution = ranking.get("attention_score", 0.0),
                weight       = float(idx == 0),  # first item gets weight 1.0
                description  = item if isinstance(item, str) else str(item),
                entity_type  = candidate.get("entity_type", ""),
                entity_key   = candidate.get("ticker") or candidate.get("entity_id", ""),
                user_id      = user_id,
            )
            if ev_row is not None:
                evidence_count += 1

        result["evidence_count"] = evidence_count

        # ── 6. Ranking log (always append-only) ─────────────────────────────
        log_row = await add_ranking_log(
            session,
            priority_id         = priority_id,
            candidate_type      = candidate.get("candidate_type", ""),
            entity_type         = candidate.get("entity_type", ""),
            entity_key          = candidate.get("ticker") or candidate.get("entity_id", ""),
            user_id             = user_id,
            decision_priority   = bucket,
            decision_rank_score = decision_score,
            rank_position       = rank_position,
            snapshot_reason     = snapshot_reason,
        )
        result["log_id"]  = getattr(log_row, "id", "") if log_row else ""
        result["stored"]  = True

    except Exception as exc:
        logger.debug("[decision_invalidation] pipeline error for %s: %r",
                     candidate.get("source_id"), exc)
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Public rebuild entry-points
# ---------------------------------------------------------------------------

async def rebuild_decision_for_target(
    session,
    candidate: dict,
    *,
    user_id: Optional[str] = None,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
    snapshot_reason: str = "rebuild",
    shadow_only: bool = False,
) -> Dict[str, Any]:
    """Run the pipeline for a single pre-built candidate dict.

    shadow_only=True: pipeline runs (ranking + explanation + validation)
    but nothing is persisted.  Callers typically derive this from the
    decision_shadow config flag.

    Returns the pipeline result dict (see _run_pipeline_for_candidate).
    Returns {"error": "null session", ...} when session is None and
    shadow_only is False.
    """
    if session is None and not shadow_only:
        return {
            "stored": False, "blocked": False, "block_reason": "",
            "priority_id": "", "evidence_count": 0, "log_id": "",
            "error": "null session",
        }
    return await _run_pipeline_for_candidate(
        session,
        candidate,
        user_id=user_id,
        ttl_hours=ttl_hours,
        snapshot_reason=snapshot_reason,
        rank_position=0,
        dry_run=shadow_only,
    )


async def rebuild_decisions_for_ticker(
    session,
    ticker: str,
    *,
    user_id: Optional[str] = None,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
    snapshot_reason: str = "rebuild",
    shadow_only: bool = False,
    targets: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build candidates for all types that match *ticker*, run the full
    pipeline, and return one result dict per candidate.

    Uses decision_candidate_builder with targets forced to *ticker* so only
    signals for this ticker are produced.  Returns [] when session is None
    and shadow_only is False.
    """
    if session is None and not shadow_only:
        return []
    try:
        from app.services.decision_candidate_builder import build_candidates
        from app.services.decision_ranking_engine import rank_candidates

        candidates = await build_candidates(
            session,
            user_id=user_id,
            targets=ticker,
        )
        if not candidates:
            return []

        ranked = rank_candidates(candidates)
        results = []
        for position, ranked_result in enumerate(ranked):
            cand = ranked_result.get("candidate", ranked_result)
            r = await _run_pipeline_for_candidate(
                session,
                cand,
                user_id=user_id,
                ttl_hours=ttl_hours,
                snapshot_reason=snapshot_reason,
                rank_position=position,
                dry_run=shadow_only,
            )
            results.append(r)
        return results
    except Exception as exc:
        logger.debug("[decision_invalidation] rebuild_decisions_for_ticker error: %r", exc)
        return []


async def rebuild_decision_batch(
    session,
    candidates: List[dict],
    *,
    user_id: Optional[str] = None,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
    snapshot_reason: str = "rebuild",
    shadow_only: bool = False,
) -> List[Dict[str, Any]]:
    """Run the pipeline for an explicit list of pre-built candidate dicts.

    Ranks them first (deterministic order) then pipelines each.
    Returns one result dict per input candidate, in ranked order.
    Returns [] for empty input or None session without shadow_only.
    """
    if not candidates:
        return []
    if session is None and not shadow_only:
        return []
    try:
        from app.services.decision_ranking_engine import rank_candidates

        ranked = rank_candidates(candidates)
        results = []
        for position, ranked_result in enumerate(ranked):
            cand = ranked_result.get("candidate", ranked_result)
            r = await _run_pipeline_for_candidate(
                session,
                cand,
                user_id=user_id,
                ttl_hours=ttl_hours,
                snapshot_reason=snapshot_reason,
                rank_position=position,
                dry_run=shadow_only,
            )
            results.append(r)
        return results
    except Exception as exc:
        logger.debug("[decision_invalidation] rebuild_decision_batch error: %r", exc)
        return []
