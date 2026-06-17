"""
Decision Portfolio Awareness — Phase 13 · Slice 7.

Adds portfolio-aware adjustment to decision rankings for a specific user,
writing user-scoped DecisionPriority rows (user_id = <uid>) that reflect
the user's actual holdings, WITHOUT modifying the global rows (user_id = NULL).

Two-tier model
--------------
    tier 1 — global  (user_id = NULL):  canonical rankings, written by Slice 13.5
    tier 2 — user    (user_id = <uid>): portfolio-adjusted rankings, written here

Rules
-----
    1. Global rows are never read-modified; this service only writes user rows.
    2. User A's rows are invisible to user B (enforced by user_id column in repo).
    3. Portfolio reads are read-only — no write path touches portfolio tables.
    4. A ticker owned by the user receives an exposure boost proportional to
       weight; a ticker the user does not own receives the neutral multiplier 1.0.
    5. The final user decision_score is clamped to [0, 1] after applying the
       portfolio boost.
    6. Explanation validation (from Slice 13.4) is the hard gate here too:
       no row is stored unless validate_decision_explanation returns (True, None).

Safety invariants (SP-5)
------------------------
    - No delivery, notification, or conviction write path.
    - No import from delivery, notification, conviction, or recommendation modules.
    - No buy/sell/hold/recommend/target-price/position-size language.
    - Portfolio data is used only as a scalar weight input — it is never surfaced
      as trading advice.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exposure multiplier bounds (mirrors decision_ranking_engine constants)
# ---------------------------------------------------------------------------

_EXPOSURE_MIN: float = 0.50
_EXPOSURE_MAX: float = 1.50
_EXPOSURE_DEFAULT: float = 1.00

# Weight → exposure boost:  0% → 1.0,  33%+ → 1.50 (cap at +0.50)
_WEIGHT_SCALE: float = 1.50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Build a per-user ticker → weight map from portfolio positions
# ---------------------------------------------------------------------------

async def build_portfolio_map(
    session,
    user_id: str,
) -> Dict[str, Optional[float]]:
    """Return {ticker.upper(): weight_or_None} for all active positions.

    Reads across all portfolios owned by *user_id*.  Weight may be None when
    the user did not supply a percentage allocation.

    Returns {} when session is None, user_id is falsy, or on error.
    Portfolio tables are never written by this function.
    """
    if session is None or not user_id:
        return {}
    try:
        from app.db.repositories.portfolio_repo import portfolio_list, position_list

        portfolios = await portfolio_list(session, user_id=user_id)
        position_map: Dict[str, Optional[float]] = {}

        for port in portfolios:
            positions = await position_list(session, port.id)
            for pos in positions:
                ticker = (pos.ticker or "").strip().upper()
                if not ticker:
                    continue
                weight = pos.weight  # may be None
                # When the same ticker appears in multiple portfolios, keep
                # the largest weight (or any weight vs. None).
                existing = position_map.get(ticker)
                if existing is None:
                    position_map[ticker] = weight
                elif weight is not None:
                    if existing is None or weight > existing:
                        position_map[ticker] = weight

        return position_map
    except Exception as exc:
        logger.debug("[decision_portfolio] build_portfolio_map error: %r", exc)
        return {}


# ---------------------------------------------------------------------------
# Compute portfolio-aware exposure multiplier for one candidate
# ---------------------------------------------------------------------------

def compute_portfolio_exposure_multiplier(
    ticker: str,
    portfolio_map: Dict[str, Optional[float]],
) -> float:
    """Return exposure multiplier ∈ [0.50, 1.50] for *ticker* given *portfolio_map*.

    If the ticker is in the user's portfolio:
        weight present  → 1.0 + min(weight × 1.50, 0.50)   e.g. 20 % → 1.30
        weight absent   → 1.20   (ownership known, weight unknown)
    If the ticker is NOT in the user's portfolio:
        → 1.0   (neutral — no portfolio adjustment)
    """
    ticker = (ticker or "").strip().upper()
    if ticker not in portfolio_map:
        return _EXPOSURE_DEFAULT

    weight = portfolio_map[ticker]
    if weight is not None:
        raw = 1.0 + min(float(weight) * _WEIGHT_SCALE, 0.50)
    else:
        raw = 1.20

    return _clamp(raw, _EXPOSURE_MIN, _EXPOSURE_MAX)


# ---------------------------------------------------------------------------
# Apply portfolio context to one already-ranked candidate
# ---------------------------------------------------------------------------

def apply_portfolio_context(
    candidate: dict,
    ranking_output: dict,
    *,
    portfolio_map: Dict[str, Optional[float]],
) -> dict:
    """Return a portfolio-adjusted copy of *ranking_output*.

    The original *ranking_output* and *candidate* are NOT mutated.

    Steps:
        1. Compute the portfolio exposure multiplier for the candidate's ticker.
        2. Replace exposure_multiplier in the output.
        3. Recompute decision_score using the stored base_score, confidence,
           and uncertainty discount from rank_inputs / ranking_output.
        4. Leave all other fields (attention_score, urgency_score, etc.) unchanged
           — only the exposure layer is portfolio-adjusted.

    Returns the unchanged *ranking_output* dict when portfolio_map is empty or
    the ticker is not in the portfolio.
    """
    ticker = (candidate.get("ticker") or "").strip().upper()
    new_exposure = compute_portfolio_exposure_multiplier(ticker, portfolio_map)

    # Fast-path: exposure not changing from what the ranking engine already set
    old_exposure = float(ranking_output.get("exposure_multiplier", _EXPOSURE_DEFAULT))
    if abs(new_exposure - old_exposure) < 1e-9:
        return dict(ranking_output)

    # Recompute decision_score with the new exposure multiplier
    rank_inputs = ranking_output.get("rank_inputs", {}) or {}
    base_score   = float(rank_inputs.get("base_score", 0.0))
    confidence   = float(ranking_output.get("confidence_multiplier", 1.0))
    uncertainty  = float(ranking_output.get("uncertainty_discount", 1.0))

    new_decision_score = _clamp(
        base_score * confidence * uncertainty * new_exposure, 0.0, 1.0
    )

    adjusted = dict(ranking_output)
    adjusted["exposure_multiplier"] = new_exposure
    adjusted["decision_score"]      = new_decision_score

    # Update base_score record in rank_inputs so callers see a consistent snapshot
    adjusted["rank_inputs"] = dict(rank_inputs)
    adjusted["rank_inputs"]["exposure_multiplier"] = new_exposure

    return adjusted


# ---------------------------------------------------------------------------
# User-portfolio rebuild
# ---------------------------------------------------------------------------

async def rebuild_decisions_for_user_portfolio(
    session,
    user_id: str,
    *,
    ttl_hours: int = 24,
    snapshot_reason: str = "rebuild",
    shadow_only: bool = False,
    targets: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build portfolio-aware user-scoped decision rows for *user_id*.

    Pipeline per candidate:
        1. Build candidates (Slice 13.2) — global substrate
        2. Rank candidates (Slice 13.3) — compute base scores
        3. Load portfolio_map for *user_id* (read-only)
        4. apply_portfolio_context — adjust exposure_multiplier per ticker
        5. Re-explain (Slice 13.4) — explanation uses adjusted ranking_output
        6. Validate explanation — hard gate, same as Slice 13.5
        7. Persist user-scoped row (user_id = user_id)

    Global rows (user_id = NULL) are NEVER touched by this function.
    Returns one result dict per candidate processed (same shape as
    decision_invalidation_service._run_pipeline_for_candidate).
    Returns [] when session is None (non-shadow), user_id is falsy, or on error.
    """
    if not user_id:
        return []
    if session is None and not shadow_only:
        return []

    try:
        from app.services.decision_candidate_builder import build_candidates
        from app.services.decision_ranking_engine import rank_candidates
        from app.services.decision_explainability_service import (
            build_decision_explanation,
            validate_decision_explanation,
        )
        from app.services.decision_invalidation_service import (
            _score_to_bucket,
            CURRENT_DECISION_SCHEMA,
        )

        # ── 1. Build + 2. Rank ──────────────────────────────────────────────
        candidates = await build_candidates(session, user_id=user_id, targets=targets)
        if not candidates:
            return []

        ranked_results = rank_candidates(candidates)

        # ── 3. Portfolio map ────────────────────────────────────────────────
        portfolio_map = await build_portfolio_map(session, user_id)

        results: List[Dict[str, Any]] = []

        for position, ranked_result in enumerate(ranked_results):
            candidate = ranked_result.get("candidate", ranked_result)
            result: Dict[str, Any] = {
                "stored": False, "blocked": False, "block_reason": "",
                "priority_id": "", "evidence_count": 0, "log_id": "",
                "error": "",
            }

            try:
                # ── 4. Apply portfolio context ───────────────────────────────
                adjusted_ranking = apply_portfolio_context(
                    candidate, ranked_result, portfolio_map=portfolio_map
                )

                # ── 5. Explain ───────────────────────────────────────────────
                explanation = build_decision_explanation(candidate, adjusted_ranking)

                # ── 6. Validate ──────────────────────────────────────────────
                ok, reason = validate_decision_explanation(explanation)
                if not ok:
                    result["blocked"]      = True
                    result["block_reason"] = reason or "validation failed"
                    results.append(result)
                    continue

                if dry_run := (shadow_only or session is None):
                    result["stored"] = False
                    results.append(result)
                    continue

                # ── 7. Persist user-scoped row ───────────────────────────────
                from app.db.repositories.decision_repo import (
                    upsert_decision_priority,
                    delete_evidence_for_priority,
                    add_decision_evidence,
                    add_ranking_log,
                )

                decision_score = adjusted_ranking.get("decision_score", 0.0)
                bucket         = _score_to_bucket(decision_score)
                decision_reason = " ".join(explanation.get("why_important", []))
                why_now_text    = " ".join(explanation.get("why_now", []))
                deprioritizers  = explanation.get("deprioritizers", [])
                evidence_items  = explanation.get("evidence", [])

                priority_row = await upsert_decision_priority(
                    session,
                    candidate_type      = candidate.get("candidate_type", ""),
                    entity_type         = candidate.get("entity_type", ""),
                    entity_key          = candidate.get("ticker") or candidate.get("entity_id", ""),
                    source_ref          = candidate.get("source_id", ""),
                    decision_priority   = bucket,
                    decision_rank_score = decision_score,
                    attention_score     = adjusted_ranking.get("attention_score", 0.0),
                    urgency_score       = adjusted_ranking.get("urgency_score", 0.0),
                    impact_score        = adjusted_ranking.get("impact_score", 0.0),
                    confidence_score    = adjusted_ranking.get("confidence_multiplier", 0.0),
                    uncertainty_score   = adjusted_ranking.get("uncertainty_discount", 0.0),
                    decision_reason     = decision_reason,
                    why_now             = why_now_text,
                    deprioritizers      = deprioritizers,
                    evidence_summary    = evidence_items,
                    source_versions     = candidate.get("source_versions") or {},
                    decision_schema     = CURRENT_DECISION_SCHEMA,
                    user_id             = user_id,  # user-scoped
                    ttl_hours           = ttl_hours,
                )

                if priority_row is None:
                    result["error"] = "upsert_decision_priority returned None"
                    results.append(result)
                    continue

                priority_id = getattr(priority_row, "id", "")
                result["priority_id"] = priority_id

                await delete_evidence_for_priority(session, priority_id=priority_id)
                evidence_count = 0
                for idx, item in enumerate(evidence_items):
                    ev = await add_decision_evidence(
                        session,
                        priority_id  = priority_id,
                        source_type  = candidate.get("source_type", ""),
                        source_id    = candidate.get("source_id", ""),
                        dimension    = "attention",
                        contribution = adjusted_ranking.get("attention_score", 0.0),
                        weight       = float(idx == 0),
                        description  = item if isinstance(item, str) else str(item),
                        entity_type  = candidate.get("entity_type", ""),
                        entity_key   = candidate.get("ticker") or candidate.get("entity_id", ""),
                        user_id      = user_id,
                    )
                    if ev is not None:
                        evidence_count += 1

                result["evidence_count"] = evidence_count

                log_row = await add_ranking_log(
                    session,
                    priority_id         = priority_id,
                    candidate_type      = candidate.get("candidate_type", ""),
                    entity_type         = candidate.get("entity_type", ""),
                    entity_key          = candidate.get("ticker") or candidate.get("entity_id", ""),
                    user_id             = user_id,
                    decision_priority   = bucket,
                    decision_rank_score = decision_score,
                    rank_position       = position,
                    snapshot_reason     = snapshot_reason,
                )
                result["log_id"] = getattr(log_row, "id", "") if log_row else ""
                result["stored"] = True

            except Exception as exc:
                logger.debug(
                    "[decision_portfolio] pipeline error for %s/%s: %r",
                    candidate.get("candidate_type"), candidate.get("source_id"), exc,
                )
                result["error"] = str(exc)

            results.append(result)

        return results

    except Exception as exc:
        logger.debug("[decision_portfolio] rebuild_decisions_for_user_portfolio error: %r", exc)
        return []
