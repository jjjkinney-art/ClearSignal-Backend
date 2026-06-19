"""
User Learning Inference Service — Phase 15 · Slice 5.

Reads captured user_signal_event rows and derives learned preference candidates
for all seven SP-7 dimensions.  Candidates are validated through the
explainability gate (Slice 15.4) before persistence.

Core rule
---------
Infer relevance.  Do not alter truth.

This module NEVER writes to, reads from, or imports any function from:
  forecast_repo, similarity_repo, decision_repo, scenario_repo,
  dossier, ticker_memory, conviction, order, or execution.

It ONLY reads user_signal_event (via user_learning_repo) and writes to
learned_preference (via user_learning_repo.upsert_learned_preference).

Flag gate
---------
All seven public infer_* functions are gated on learning_inference_enabled
(default False).  When the flag is False the function returns [] immediately.

Null-session contract
---------------------
Every public function returns [] when session=None — never raises.

SP-7 invariants
---------------
  SP-7a: no write to any truth table (forecast_vector, similarity_edge,
         scenario_snapshot, decision_priority, ticker_memory, or any upstream).
  SP-7b: no import of any write function from forecast / decision / scenario /
         similarity repos.
  SP-7f: no buy/sell/hold/recommend/target_price/position_size/trade/execution
         language in any generated string (enforced by explainability gate).
  SP-7g: every candidate passes validate_preference_explanation before upsert.
  SP-7h: this service produces candidates only — no relevance adjustment yet
         (that is Slice 15.6+).

Candidate dict shape
--------------------
{
    "dimension":             str,
    "entity_key":            str,
    "affinity":              float,   # net weighted polarity, -1..1
    "confidence":            float,   # |affinity|, 0..1
    "evidence_count":        int,
    "belief_basis":          str,     # joined why_we_believe_this sentences
    "signal_strength_label": str,     # "strong" | "moderate" | "tentative"
    "falsifier":             str,     # first falsifier condition
    "evidence_refs":         [str],   # event reference strings
    "explanation":           dict,    # full validated explanation envelope
    "status":                str,     # "unresolved"
}
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_LOOKBACK_DAYS: int = 90

# Minimum evidence count before a candidate is emitted (anti-fabrication gate).
# Mirrors _MIN_EVIDENCE in user_learning_explainability_service — single source
# of truth is the explainability service; these are kept in sync manually.
_MIN_EVIDENCE: Dict[str, int] = {
    "sector_interest":       5,
    "company_interest":      5,
    "theme_interest":        5,
    "preferred_horizon":     3,
    "preferred_signal_type": 3,
    "ignored_signal_type":   6,   # higher: negative preferences require repetition
    "portfolio_sensitivity": 4,
}

# Polarity → signed weight used for affinity computation.
_POLARITY_WEIGHT: Dict[str, float] = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral":  0.0,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _inference_enabled(override: Optional[bool] = None) -> bool:
    """Return True when learning_inference_enabled flag is set.

    The optional override is for testing — passes True/False without reading
    settings, mirroring the pattern used in Slices 3–4.
    """
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "learning_inference_enabled", False))
    except Exception:
        return False


def _attr(obj: Any, key: str, default: Any = "") -> Any:
    """Read attribute or dict key from an event row or dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _compute_affinity_confidence(events: List[Any]) -> Tuple[float, float]:
    """Compute (affinity, confidence) from a list of event rows.

    affinity  — net weighted polarity sum normalised to [-1, 1]
    confidence — |affinity|, in [0, 1]; reflects signal consistency
    """
    if not events:
        return 0.0, 0.0

    total_weight = 0.0
    net_weighted = 0.0
    for ev in events:
        polarity = _attr(ev, "polarity", "neutral")
        weight   = float(_attr(ev, "interaction_weight", 1.0))
        mult     = _POLARITY_WEIGHT.get(polarity, 0.0)
        total_weight += weight
        net_weighted += weight * mult

    if total_weight == 0:
        return 0.0, 0.0

    affinity   = net_weighted / total_weight   # -1..1
    confidence = abs(net_weighted) / total_weight  # 0..1
    return affinity, confidence


def _events_to_refs(events: List[Any]) -> List[Dict[str, Any]]:
    """Convert ORM event rows to lightweight dicts for the explainability builder."""
    refs = []
    for ev in events:
        if isinstance(ev, dict):
            refs.append({
                "signal_type":    ev.get("signal_type", ""),
                "polarity":       ev.get("polarity", "neutral"),
                "entity_key":     ev.get("entity_key", ""),
                "source_surface": ev.get("source_surface", ""),
            })
        else:
            refs.append({
                "signal_type":    getattr(ev, "signal_type", ""),
                "polarity":       getattr(ev, "polarity", "neutral"),
                "entity_key":     getattr(ev, "entity_key", ""),
                "source_surface": getattr(ev, "source_surface", ""),
            })
    return refs


def _group_by_entity_key(events: List[Any]) -> Dict[str, List[Any]]:
    """Group event rows by entity_key, omitting blank keys."""
    groups: Dict[str, List[Any]] = defaultdict(list)
    for ev in events:
        key = _attr(ev, "entity_key", "")
        if key:
            groups[key].append(ev)
    return dict(groups)


def _build_candidate(
    dimension: str,
    entity_key: str,
    events: List[Any],
) -> Optional[Dict[str, Any]]:
    """Build one validated preference candidate from a group of events.

    Returns None when:
      - evidence_count is below the dimension's minimum threshold, or
      - the assembled explanation fails validate_preference_explanation.

    The validation gate (SP-7g) runs on every candidate before it is returned.
    Candidates that fail the gate are silently dropped and debug-logged.
    """
    from app.services.user_learning_explainability_service import (
        build_preference_explanation,
        validate_preference_explanation,
    )

    min_ev = _MIN_EVIDENCE.get(dimension, 5)
    if len(events) < min_ev:
        return None

    affinity, confidence = _compute_affinity_confidence(events)
    evidence_count = len(events)

    preference_data: Dict[str, Any] = {
        "dimension":      dimension,
        "entity_key":     entity_key,
        "affinity":       affinity,
        "confidence":     confidence,
        "evidence_count": evidence_count,
    }

    event_refs = _events_to_refs(events)
    explanation = build_preference_explanation(preference_data, event_refs)

    ok, reason = validate_preference_explanation(explanation)
    if not ok:
        logger.debug(
            "[inference] explanation rejected for %s/%s: %s",
            dimension, entity_key, reason,
        )
        return None

    falsifier_list = explanation.get("falsifier", [])
    falsifier_str  = falsifier_list[0] if falsifier_list else ""

    return {
        "dimension":             dimension,
        "entity_key":            entity_key,
        "affinity":              affinity,
        "confidence":            confidence,
        "evidence_count":        evidence_count,
        "belief_basis":          "; ".join(explanation.get("why_we_believe_this", [])),
        "signal_strength_label": explanation.get("signal_strength", "tentative"),
        "falsifier":             falsifier_str,
        "evidence_refs":         explanation.get("evidence", []),
        "explanation":           explanation,
        "status":                "unresolved",
    }


async def _fetch_events(
    session,
    *,
    user_id: str,
    entity_type: str,
    lookback_days: int,
) -> List[Any]:
    """Fetch user signal events from the repository.

    Returns [] when session is None or on any error.
    """
    try:
        from app.db.repositories.user_learning_repo import list_user_signal_events

        cutoff = _now() - timedelta(days=lookback_days)
        return await list_user_signal_events(
            session,
            user_id=user_id,
            entity_type=entity_type,
            occurred_after=cutoff,
            limit=2000,
        )
    except Exception as exc:
        logger.debug("[inference] _fetch_events(%s) failed: %r", entity_type, exc)
        return []


def _candidates_from_groups(
    groups: Dict[str, List[Any]],
    dimension: str,
) -> List[Dict[str, Any]]:
    """Build candidates for all entity keys in a group dict (sorted for determinism)."""
    candidates = []
    for entity_key in sorted(groups):
        candidate = _build_candidate(dimension, entity_key, groups[entity_key])
        if candidate is not None:
            candidates.append(candidate)
    return candidates


# ---------------------------------------------------------------------------
# Public dimension-specific inference functions
# ---------------------------------------------------------------------------

async def infer_company_preferences(
    session,
    *,
    user_id: str,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Infer company_interest preferences from non-portfolio company interactions.

    Reads user_signal_event rows with entity_type='company', excluding rows
    where source_surface='portfolio' (those feed portfolio_sensitivity instead).

    Returns a list of validated candidate dicts, possibly empty.
    """
    if not _inference_enabled(run_override):
        return []
    if session is None:
        return []
    try:
        events = await _fetch_events(
            session, user_id=user_id, entity_type="company",
            lookback_days=lookback_days,
        )
        # Exclude portfolio interactions — they feed portfolio_sensitivity
        events = [ev for ev in events if _attr(ev, "source_surface", "") != "portfolio"]
        groups = _group_by_entity_key(events)
        return _candidates_from_groups(groups, "company_interest")
    except Exception as exc:
        logger.debug("[inference] infer_company_preferences failed: %r", exc)
        return []


async def infer_sector_preferences(
    session,
    *,
    user_id: str,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Infer sector_interest preferences from sector interactions.

    Reads user_signal_event rows with entity_type='sector'.
    """
    if not _inference_enabled(run_override):
        return []
    if session is None:
        return []
    try:
        events = await _fetch_events(
            session, user_id=user_id, entity_type="sector",
            lookback_days=lookback_days,
        )
        groups = _group_by_entity_key(events)
        return _candidates_from_groups(groups, "sector_interest")
    except Exception as exc:
        logger.debug("[inference] infer_sector_preferences failed: %r", exc)
        return []


async def infer_theme_preferences(
    session,
    *,
    user_id: str,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Infer theme_interest preferences from theme cluster interactions.

    Reads user_signal_event rows with entity_type='theme'.
    Theme entity_keys are theme identifiers captured via capture_forecast_interaction
    or any surface that populates entity_type='theme'.
    """
    if not _inference_enabled(run_override):
        return []
    if session is None:
        return []
    try:
        events = await _fetch_events(
            session, user_id=user_id, entity_type="theme",
            lookback_days=lookback_days,
        )
        groups = _group_by_entity_key(events)
        return _candidates_from_groups(groups, "theme_interest")
    except Exception as exc:
        logger.debug("[inference] infer_theme_preferences failed: %r", exc)
        return []


async def infer_horizon_preferences(
    session,
    *,
    user_id: str,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Infer preferred_horizon preferences from horizon interaction events.

    Reads user_signal_event rows with entity_type='horizon'.
    Entity keys are horizon labels (e.g., 'short', 'medium', 'long') captured
    by capture_forecast_interaction when signal_type='horizon_toggle'.
    """
    if not _inference_enabled(run_override):
        return []
    if session is None:
        return []
    try:
        events = await _fetch_events(
            session, user_id=user_id, entity_type="horizon",
            lookback_days=lookback_days,
        )
        groups = _group_by_entity_key(events)
        return _candidates_from_groups(groups, "preferred_horizon")
    except Exception as exc:
        logger.debug("[inference] infer_horizon_preferences failed: %r", exc)
        return []


async def infer_signal_type_preferences(
    session,
    *,
    user_id: str,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Infer preferred_signal_type and ignored_signal_type preferences.

    Reads user_signal_event rows with entity_type='signal_type' (captured by
    capture_alert_interaction and similar surfaces).

    For each signal_type entity_key two separate candidates are evaluated:
      preferred_signal_type — driven by positive events (MIN_EVIDENCE=3)
      ignored_signal_type   — driven by negative events (MIN_EVIDENCE=6;
                              higher bar because negative preferences require
                              repetition across sessions before hardening)

    Each dimension is evaluated independently; a single entity_key may produce
    both a preferred and an ignored candidate only when it has mixed signals
    from separate behavioural contexts (unusual but not impossible).
    """
    if not _inference_enabled(run_override):
        return []
    if session is None:
        return []
    try:
        events = await _fetch_events(
            session, user_id=user_id, entity_type="signal_type",
            lookback_days=lookback_days,
        )
        groups = _group_by_entity_key(events)

        candidates: List[Dict[str, Any]] = []
        for entity_key in sorted(groups):
            all_evs = groups[entity_key]

            # preferred_signal_type — positive events
            pos_evs = [e for e in all_evs if _attr(e, "polarity", "") == "positive"]
            if len(pos_evs) >= _MIN_EVIDENCE["preferred_signal_type"]:
                c = _build_candidate("preferred_signal_type", entity_key, pos_evs)
                if c is not None:
                    candidates.append(c)

            # ignored_signal_type — negative events (higher threshold)
            neg_evs = [e for e in all_evs if _attr(e, "polarity", "") == "negative"]
            if len(neg_evs) >= _MIN_EVIDENCE["ignored_signal_type"]:
                c = _build_candidate("ignored_signal_type", entity_key, neg_evs)
                if c is not None:
                    candidates.append(c)

        return candidates
    except Exception as exc:
        logger.debug("[inference] infer_signal_type_preferences failed: %r", exc)
        return []


async def infer_portfolio_sensitivities(
    session,
    *,
    user_id: str,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Infer portfolio_sensitivity preferences from portfolio surface interactions.

    Reads user_signal_event rows with entity_type='company' AND
    source_surface='portfolio'.  These are distinct from company_interest
    because they reflect attention to an existing position rather than
    general analytical interest.

    SP-7f: portfolio sensitivity informs relevance ordering only. It does not
    produce sizing, weighting, or any advisory output.
    """
    if not _inference_enabled(run_override):
        return []
    if session is None:
        return []
    try:
        events = await _fetch_events(
            session, user_id=user_id, entity_type="company",
            lookback_days=lookback_days,
        )
        # Only portfolio surface events feed this dimension
        events = [ev for ev in events if _attr(ev, "source_surface", "") == "portfolio"]
        groups = _group_by_entity_key(events)
        return _candidates_from_groups(groups, "portfolio_sensitivity")
    except Exception as exc:
        logger.debug("[inference] infer_portfolio_sensitivities failed: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

async def infer_learned_preferences(
    session,
    *,
    user_id: str,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    run_override: Optional[bool] = None,
) -> List[Any]:
    """Run all dimension-specific inferencers, validate, and persist candidates.

    Calls all six dimension functions, collects their validated candidate dicts,
    then upserts each into learned_preference via user_learning_repo.

    Returns a list of upserted ORM rows (LearnedPreference objects), possibly
    empty when no events exist, the flag is off, or session is None.

    Every candidate passed to upsert_learned_preference has already been
    validated by validate_preference_explanation (SP-7g). The upsert itself
    does not re-validate — the gate is enforced upstream in _build_candidate.

    No relevance adjustment is written here (that is Slice 15.6+).
    """
    if not _inference_enabled(run_override):
        return []
    if session is None:
        return []
    try:
        all_candidates: List[Dict[str, Any]] = []

        for func in (
            infer_company_preferences,
            infer_sector_preferences,
            infer_theme_preferences,
            infer_horizon_preferences,
            infer_signal_type_preferences,
            infer_portfolio_sensitivities,
        ):
            results = await func(
                session,
                user_id=user_id,
                lookback_days=lookback_days,
                run_override=run_override,
            )
            all_candidates.extend(results)

        from app.db.repositories.user_learning_repo import upsert_learned_preference

        persisted: List[Any] = []
        for c in all_candidates:
            row = await upsert_learned_preference(
                session,
                user_id             = user_id,
                dimension           = c["dimension"],
                entity_key          = c["entity_key"],
                affinity            = c["affinity"],
                confidence          = c["confidence"],
                evidence_count      = c["evidence_count"],
                status              = c.get("status", "unresolved"),
                belief_basis        = c.get("belief_basis", ""),
                signal_strength_label = c.get("signal_strength_label", "tentative"),
                falsifier           = c.get("falsifier", ""),
            )
            if row is not None:
                persisted.append(row)

        return persisted
    except Exception as exc:
        logger.debug("[inference] infer_learned_preferences failed: %r", exc)
        return []
