"""
Scenario Rebuild + Storage Pipeline — Phase 14 · Slice 5.

Orchestrates the full Phase 14 pipeline for one or many scenario seeds:

    scenario_seed_builder
        → scenario_propagation_engine
        → scenario_explainability_service
        → validate_scenario_explanation   ← hard gate (SP-6)
        → scenario_repo  (upsert_scenario_snapshot
                          + delete_evidence_for_snapshot + add_scenario_evidence
                          + add_run_log)

Core rule: No row may be stored unless validate_scenario_explanation returns
(True, None). A failed explanation aborts the entire seed — no
scenario_snapshot row, no scenario_evidence row.

Stale detection: a stored ScenarioSnapshot is considered stale when:
    - scenario_schema differs from CURRENT_SCENARIO_SCHEMA, OR
    - expires_at <= now()

Safety invariants (SP-6)
------------------------
    - Does NOT write to any source table: no dossier, no forecast, no
      similarity, no portfolio, no delivery, no notification, no conviction,
      no decision, no forecast_vector.
    - Does NOT create Notification rows.
    - Does NOT import from delivery, notification, conviction, or order modules.
    - Flag gate: scenario_build_enabled must be True to persist; when False
      (or shadow_only=True) the pipeline runs but nothing is written.
    - scenario_shadow=True: pipeline runs, run_log appended, no snapshot upsert.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Current schema version — bump to invalidate all stored rows when the
# evaluation model or assembly logic changes.
CURRENT_SCENARIO_SCHEMA: int = 1

# Default TTL for new ScenarioSnapshot rows (hours).
_DEFAULT_TTL_HOURS: int = 72


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Confidence → plausibility band
# ---------------------------------------------------------------------------

def _plausibility_band(confidence: float) -> str:
    if confidence >= 0.70:
        return "likely_conditional"
    if confidence >= 0.40:
        return "plausible"
    return "remote"


# ---------------------------------------------------------------------------
# Impact inputs → scenario_impact label
# ---------------------------------------------------------------------------

def _scenario_impact(seed: dict) -> str:
    """Derive a qualitative impact label from the seed's impact_inputs.

    Labels: significant_positive | moderate_positive | neutral |
            moderate_negative | significant_negative | ambiguous
    These are structural bands — NOT price/return predictions.
    """
    ii = seed.get("impact_inputs", {}) or {}
    p_pos = float(ii.get("p_positive") or 0.0)
    p_neg = float(ii.get("p_negative") or 0.0)
    diff  = abs(p_pos - p_neg)
    if diff < 0.10:
        return "ambiguous"
    if p_pos > p_neg:
        return "significant_positive" if p_pos >= 0.70 else "moderate_positive"
    return "significant_negative" if p_neg >= 0.70 else "moderate_negative"


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------

def is_scenario_stale(snapshot_row) -> bool:
    """Return True if *snapshot_row* is expired or on an old schema version.

    Safe to call with None (returns True — treat missing as stale).
    """
    if snapshot_row is None:
        return True
    try:
        if getattr(snapshot_row, "scenario_schema", 0) != CURRENT_SCENARIO_SCHEMA:
            return True
        expires = getattr(snapshot_row, "expires_at", None)
        if expires is None:
            return True
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires <= _now()
    except Exception:
        return True


async def find_stale_scenarios(
    session,
    *,
    scenario_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 200,
) -> List[Any]:
    """Return ScenarioSnapshot rows that are stale (expired or schema-old).

    Returns [] when session is None or on error.
    """
    if session is None:
        return []
    try:
        from app.db.repositories.scenario_repo import list_scenario_snapshots

        rows = await list_scenario_snapshots(
            session,
            scenario_type=scenario_type,
            entity_type=entity_type,
            limit=limit,
        )
        return [r for r in rows if is_scenario_stale(r)]
    except Exception as exc:
        logger.debug("[scenario_invalidation] find_stale_scenarios error: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Internal single-seed pipeline
# ---------------------------------------------------------------------------

async def _run_pipeline_for_seed(
    session,
    seed: dict,
    *,
    ttl_hours: int,
    snapshot_reason: str,
    rank_position: int,
    dry_run: bool,
) -> Dict[str, Any]:
    """Run the full pipeline for one seed dict.

    Returns a result dict with keys:
        stored         bool  — True if a snapshot row was written
        blocked        bool  — True if explanation validation blocked storage
        block_reason   str   — validation failure message (or "")
        snapshot_id    str   — id of the upserted snapshot row (or "")
        evidence_count int   — number of evidence rows written
        log_id         str   — id of the run_log row (or "")
        scenario_type  str   — scenario_type from seed
        entity_key     str   — entity key from seed
        error          str   — unexpected exception message (or "")
    """
    result: Dict[str, Any] = {
        "stored":        False,
        "blocked":       False,
        "block_reason":  "",
        "snapshot_id":   "",
        "evidence_count": 0,
        "log_id":        "",
        "scenario_type": seed.get("scenario_type", ""),
        "entity_key":    seed.get("ticker") or seed.get("entity_id", ""),
        "error":         "",
    }

    try:
        # ── 1. Propagate ─────────────────────────────────────────────────────
        from app.services.scenario_propagation_engine import propagate_scenario
        propagation = await propagate_scenario(session, seed)
        if not propagation:
            result["blocked"]      = True
            result["block_reason"] = "propagation returned empty result"
            return result

        # ── 2. Explain ───────────────────────────────────────────────────────
        from app.services.scenario_explainability_service import (
            build_scenario_explanation,
            validate_scenario_explanation,
        )
        explanation = build_scenario_explanation(seed, propagation)

        # ── 3. Validate — hard gate ─────────────────────────────────────────
        ok, reason = validate_scenario_explanation(explanation)
        if not ok:
            result["blocked"]      = True
            result["block_reason"] = reason or "validation failed"
            logger.debug(
                "[scenario_invalidation] blocked seed %s/%s: %s",
                seed.get("scenario_type"), seed.get("entity_id"), reason,
            )
            return result

        # ── 4. Map to storage fields ─────────────────────────────────────────
        scenario_type   = seed.get("scenario_type", "")
        entity_type     = seed.get("entity_type", "")
        entity_key      = seed.get("ticker") or seed.get("entity_id", "")
        scenario_key    = (seed.get("scenario_name") or "")[:200]
        condition       = seed.get("changed_assumption", "")
        user_id         = seed.get("user_id")

        what_changed_text = " ".join(explanation.get("what_changed", []))
        why_matters_text  = " ".join(explanation.get("why_it_matters", []))
        evidence_items    = explanation.get("evidence", [])
        invalidators      = explanation.get("invalidators", [])

        transmission_path = propagation.get("transmission_path", [])
        affected_entities = [
            e.get("entity_key") for e in propagation.get("affected_entities", [])
            if e.get("entity_key")
        ]
        confidence_score  = float(propagation.get("impact_confidence", 0.0))
        uncertainty_score = float(propagation.get("impact_uncertainty", 0.0))
        source_versions   = seed.get("source_versions") or {}

        plausibility = _plausibility_band(confidence_score)
        impact_label = _scenario_impact(seed)

        # ── 5. Persist (skip if dry_run) ─────────────────────────────────────
        if dry_run or session is None:
            result["stored"] = False
            # Still log the run even in dry_run (shadow mode)
            if session is not None:
                from app.db.repositories.scenario_repo import add_run_log
                log_row = await add_run_log(
                    session,
                    scenario_id     = None,
                    scenario_type   = scenario_type,
                    entity_type     = entity_type,
                    entity_key      = entity_key,
                    user_id         = user_id,
                    run_reason      = "shadow",
                    snapshot_reason = snapshot_reason,
                    rank_position   = rank_position,
                )
                result["log_id"] = getattr(log_row, "id", "") if log_row else ""
            return result

        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot,
            delete_evidence_for_snapshot,
            add_scenario_evidence,
            add_run_log,
        )

        snapshot_row = await upsert_scenario_snapshot(
            session,
            scenario_type     = scenario_type,
            entity_type       = entity_type,
            entity_key        = entity_key,
            scenario_key      = scenario_key,
            condition         = condition,
            transmission_path = transmission_path,
            scenario_impact   = impact_label,
            plausibility_band = plausibility,
            confidence_score  = confidence_score,
            uncertainty_score = uncertainty_score,
            affected_entities = affected_entities,
            affected_forecasts= [],
            affected_decisions= [],
            what_changed      = what_changed_text,
            why_it_matters    = why_matters_text,
            evidence_summary  = evidence_items,
            invalidators      = invalidators,
            source_versions   = source_versions,
            scenario_schema   = CURRENT_SCENARIO_SCHEMA,
            user_id           = user_id,
            ttl_hours         = ttl_hours,
        )

        if snapshot_row is None:
            result["error"] = "upsert_scenario_snapshot returned None"
            return result

        snapshot_id = getattr(snapshot_row, "id", "")
        result["snapshot_id"] = snapshot_id

        # Clear stale evidence then re-insert
        await delete_evidence_for_snapshot(session, scenario_id=snapshot_id)

        evidence_count = 0

        # One evidence row per evidence item from the explanation
        for item in evidence_items:
            ev = await add_scenario_evidence(
                session,
                scenario_id    = snapshot_id,
                source_phase   = seed.get("source_type", ""),
                source_ref     = seed.get("source_id", ""),
                captured_value = {"text": item if isinstance(item, str) else str(item)},
                entity_type    = entity_type,
                entity_key     = entity_key,
                user_id        = user_id,
            )
            if ev is not None:
                evidence_count += 1

        # One evidence row per seed evidence_ref (if any)
        for ref in (seed.get("evidence_refs") or []):
            ev = await add_scenario_evidence(
                session,
                scenario_id    = snapshot_id,
                source_phase   = seed.get("source_type", ""),
                source_ref     = str(ref),
                captured_value = {},
                entity_type    = entity_type,
                entity_key     = entity_key,
                user_id        = user_id,
            )
            if ev is not None:
                evidence_count += 1

        result["evidence_count"] = evidence_count

        # ── 6. Run log (always append-only) ──────────────────────────────────
        log_row = await add_run_log(
            session,
            scenario_id     = snapshot_id,
            scenario_type   = scenario_type,
            entity_type     = entity_type,
            entity_key      = entity_key,
            user_id         = user_id,
            run_reason      = "assembly",
            snapshot_reason = snapshot_reason,
            rank_position   = rank_position,
        )
        result["log_id"] = getattr(log_row, "id", "") if log_row else ""
        result["stored"] = True

    except Exception as exc:
        logger.debug(
            "[scenario_invalidation] pipeline error for %s/%s: %r",
            seed.get("scenario_type"), seed.get("entity_id"), exc,
        )
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Public rebuild entry-points
# ---------------------------------------------------------------------------

async def rebuild_scenario_for_target(
    session,
    seed: dict,
    *,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
    snapshot_reason: str = "rebuild",
    shadow_only: bool = False,
) -> Dict[str, Any]:
    """Run the pipeline for a single pre-built seed dict.

    shadow_only=True: pipeline runs (propagation + explanation + validation)
    but nothing is persisted except an optional shadow run_log entry.
    Callers typically derive this from the scenario_shadow config flag.

    Returns the pipeline result dict.
    Returns {"error": "null session", ...} when session is None and
    shadow_only is False.
    """
    if session is None and not shadow_only:
        return {
            "stored": False, "blocked": False, "block_reason": "",
            "snapshot_id": "", "evidence_count": 0, "log_id": "",
            "scenario_type": seed.get("scenario_type", ""),
            "entity_key": seed.get("ticker") or seed.get("entity_id", ""),
            "error": "null session",
        }
    return await _run_pipeline_for_seed(
        session,
        seed,
        ttl_hours=ttl_hours,
        snapshot_reason=snapshot_reason,
        rank_position=0,
        dry_run=shadow_only,
    )


async def rebuild_scenarios_for_ticker(
    session,
    ticker: str,
    *,
    user_id: Optional[str] = None,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
    snapshot_reason: str = "rebuild",
    shadow_only: bool = False,
    seed_types: Optional[tuple] = None,
) -> List[Dict[str, Any]]:
    """Build all seeds for *ticker*, run the full pipeline, return one result
    dict per seed.

    Uses scenario_seed_builder with targets forced to *ticker* so only seeds
    for that ticker are produced.  Returns [] when session is None and
    shadow_only is False.
    """
    if session is None and not shadow_only:
        return []
    try:
        from app.services.scenario_seed_builder import build_seeds

        seeds = await build_seeds(
            session,
            user_id=user_id,
            targets=ticker,
            seed_types=seed_types,
        )
        if not seeds:
            return []

        results = []
        for position, seed in enumerate(seeds):
            r = await _run_pipeline_for_seed(
                session,
                seed,
                ttl_hours=ttl_hours,
                snapshot_reason=snapshot_reason,
                rank_position=position,
                dry_run=shadow_only,
            )
            results.append(r)
        return results
    except Exception as exc:
        logger.debug(
            "[scenario_invalidation] rebuild_scenarios_for_ticker error: %r", exc
        )
        return []


async def rebuild_scenario_batch(
    session,
    seeds: List[dict],
    *,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
    snapshot_reason: str = "rebuild",
    shadow_only: bool = False,
) -> List[Dict[str, Any]]:
    """Run the pipeline for an explicit list of pre-built seed dicts.

    Returns one result dict per input seed, in input order.
    Returns [] for empty input or None session without shadow_only.
    """
    if not seeds:
        return []
    if session is None and not shadow_only:
        return []
    results = []
    for position, seed in enumerate(seeds):
        try:
            r = await _run_pipeline_for_seed(
                session,
                seed,
                ttl_hours=ttl_hours,
                snapshot_reason=snapshot_reason,
                rank_position=position,
                dry_run=shadow_only,
            )
            results.append(r)
        except Exception as exc:
            logger.debug(
                "[scenario_invalidation] rebuild_scenario_batch item error: %r", exc
            )
            results.append({
                "stored": False, "blocked": False, "block_reason": "",
                "snapshot_id": "", "evidence_count": 0, "log_id": "",
                "scenario_type": seed.get("scenario_type", ""),
                "entity_key": seed.get("ticker") or seed.get("entity_id", ""),
                "error": str(exc),
            })
    return results
