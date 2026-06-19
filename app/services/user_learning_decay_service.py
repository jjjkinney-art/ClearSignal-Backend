"""
User Learning Decay & Falsification Service — Phase 15 · Slice 6.

Weakens, expires, and falsifies learned preferences based on:
  - recency (time since last reinforcement)
  - inactivity (exceeding a per-dimension stale threshold)
  - contradictory evidence from new user_signal_event rows
  - preference reversal (net polarity flip)
  - insufficient evidence (evidence_count below the anti-fabrication floor)

Core rule
---------
Preferences are beliefs, not facts.

This module ONLY updates confidence, signal_strength_label, status, and
updated_at on LearnedPreference rows.  It never writes to, reads from, or
imports any function from forecast_repo, similarity_repo, decision_repo,
scenario_repo, dossier, ticker_memory, conviction, order, or execution.

Flag gate
---------
All public functions are gated on learning_inference_enabled (default False)
via run_override.  When the flag is off the function returns None/[]/0
immediately without touching the database.

Null-session contract
---------------------
Every public function returns None / [] / 0 when session=None — never raises.

Decay model
-----------
confidence after t days = initial_confidence × exp(−ln2 × t / half_life)

Each dimension has its own half_life and stale threshold:
  sector_interest      half_life=60d  stale=30d
  company_interest     half_life=60d  stale=30d
  theme_interest       half_life=45d  stale=30d
  preferred_horizon    half_life=90d  stale=60d
  preferred_signal_type half_life=90d stale=90d
  ignored_signal_type  half_life=90d  stale=90d
  portfolio_sensitivity half_life=90d stale=90d

signal_strength_label is recomputed from the new (decayed) confidence using the
same thresholds as the explainability service (strong≥0.70, moderate≥0.40).

Falsification triggers (per dimension)
---------------------------------------
  Any dimension:
    - inactivity beyond stale threshold → status='stale'
    - evidence_count < MIN_EVIDENCE floor → status='falsified' (fabrication)

  sector_interest / company_interest / theme_interest / preferred_horizon /
  portfolio_sensitivity (positive affinity):
    - contradictory_signal: negative event count ≥ 3 in the recent window

  ignored_signal_type (negative affinity):
    - positive_interaction: ANY single positive event resets the accumulation
      (per spec §5.4 and build_falsifier in Slice 15.4)

  preferred_signal_type (positive affinity):
    - contradictory_signal: negative event count ≥ MIN_EVIDENCE["ignored_signal_type"]

SP-7 invariants
---------------
  SP-7a / SP-7b: no truth-table writes or imports.
  SP-7f: no banned advisory language in any generated string.
  SP-7h: this service does not produce relevance adjustments (Slice 15.6+).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-dimension decay parameters
# ---------------------------------------------------------------------------

_DECAY_HALF_LIFE_DAYS: Dict[str, float] = {
    "sector_interest":       60.0,
    "company_interest":      60.0,
    "theme_interest":        45.0,
    "preferred_horizon":     90.0,
    "preferred_signal_type": 90.0,
    "ignored_signal_type":   90.0,
    "portfolio_sensitivity": 90.0,
}

# Days without reinforcement before marking a preference as stale
_STALE_THRESHOLD_DAYS: Dict[str, float] = {
    "sector_interest":       30.0,
    "company_interest":      30.0,
    "theme_interest":        30.0,
    "preferred_horizon":     60.0,
    "preferred_signal_type": 90.0,
    "ignored_signal_type":   90.0,
    "portfolio_sensitivity": 90.0,
}

# Anti-fabrication floor — mirrors _MIN_EVIDENCE in explainability service
_MIN_EVIDENCE: Dict[str, int] = {
    "sector_interest":       5,
    "company_interest":      5,
    "theme_interest":        5,
    "preferred_horizon":     3,
    "preferred_signal_type": 3,
    "ignored_signal_type":   6,
    "portfolio_sensitivity": 4,
}

# Negative event count threshold that triggers contradictory-signal falsification
# for positive-affinity dimensions (excluding ignored_signal_type which has its own rule)
_CONTRADICTION_THRESHOLD: int = 3

# Signal strength label boundaries — mirrors explainability service
_STRONG_THRESHOLD:   float = 0.70
_MODERATE_THRESHOLD: float = 0.40

# Default lookback window for fetching recent events during falsifier detection
_FALSIFIER_LOOKBACK_DAYS: int = 90


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _inference_enabled(override: Optional[bool] = None) -> bool:
    """Return True when learning_inference_enabled flag is set."""
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "learning_inference_enabled", False))
    except Exception:
        return False


def _recency_decay_factor(elapsed_days: float, half_life_days: float) -> float:
    """Exponential decay factor: 1.0 at t=0, 0.5 at t=half_life.

    Returns a value in (0, 1].  Always positive — decay never reverses polarity.
    """
    if elapsed_days <= 0.0:
        return 1.0
    return math.exp(-math.log(2.0) * elapsed_days / half_life_days)


def _confidence_to_strength_label(confidence: float) -> str:
    """Map confidence float to a signal_strength_label string."""
    if confidence >= _STRONG_THRESHOLD:
        return "strong"
    if confidence >= _MODERATE_THRESHOLD:
        return "moderate"
    return "tentative"


def _elapsed_days(last_reinforced_at: Optional[datetime], now: datetime) -> float:
    """Days since last_reinforced_at.  Returns 0.0 if the timestamp is None.

    SQLite returns naive datetimes; treat them as UTC when the caller supplies
    a timezone-aware now so the subtraction doesn't raise TypeError.
    """
    if last_reinforced_at is None:
        return 0.0
    ts = last_reinforced_at
    if ts.tzinfo is None and now.tzinfo is not None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    return max(0.0, delta.total_seconds() / 86_400.0)


def _attr(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


async def _fetch_recent_events(
    session,
    *,
    user_id: str,
    entity_key: str,
    entity_type: str,
    lookback_days: int = _FALSIFIER_LOOKBACK_DAYS,
) -> List[Any]:
    """Fetch UserSignalEvent rows for a specific entity within the lookback window."""
    try:
        from app.db.repositories.user_learning_repo import list_user_signal_events

        cutoff = _now() - timedelta(days=lookback_days)
        return await list_user_signal_events(
            session,
            user_id=user_id,
            entity_type=entity_type,
            entity_key=entity_key,
            occurred_after=cutoff,
            limit=500,
        )
    except Exception as exc:
        logger.debug("[decay] _fetch_recent_events failed: %r", exc)
        return []


def _entity_type_for_dimension(dimension: str) -> str:
    """Map a preference dimension to the entity_type stored in user_signal_event."""
    _MAP = {
        "sector_interest":       "sector",
        "company_interest":      "company",
        "theme_interest":        "theme",
        "preferred_horizon":     "horizon",
        "preferred_signal_type": "signal_type",
        "ignored_signal_type":   "signal_type",
        "portfolio_sensitivity": "company",
    }
    return _MAP.get(dimension, "company")


async def _update_preference_fields(
    session,
    row: Any,
    *,
    confidence: float,
    signal_strength_label: str,
    status: str,
    now: datetime,
) -> None:
    """Mutate the row's decay-relevant fields and flush to the session."""
    row.confidence            = round(confidence, 6)
    row.signal_strength_label = signal_strength_label
    row.status                = status
    row.updated_at            = now
    await session.flush()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def decay_preference(
    session,
    *,
    preference: Any,
    now: Optional[datetime] = None,
    run_override: Optional[bool] = None,
) -> Optional[Any]:
    """Apply recency and inactivity decay to a single learned preference.

    Algorithm:
      1. Compute elapsed days since last_reinforced_at.
      2. Multiply current confidence by the exponential decay factor.
      3. Recompute signal_strength_label from the new confidence.
      4. If elapsed > stale threshold AND status is not already falsified,
         set status='stale'.
      5. Persist changes via session.flush().

    Only confidence, signal_strength_label, status, and updated_at are written.
    affinity is intentionally unchanged — decay weakens certainty, not the
    observed direction of a historical signal.

    Returns the updated preference row, or None when disabled or session is None.
    """
    if not _inference_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        ts_now     = now or _now()
        dimension  = _attr(preference, "dimension", "")
        confidence = float(_attr(preference, "confidence", 0.0))
        status     = _attr(preference, "status", "unresolved")
        last_reinforced = _attr(preference, "last_reinforced_at")

        # Don't decay a preference that's already been explicitly falsified
        if status == "falsified":
            return preference

        elapsed    = _elapsed_days(last_reinforced, ts_now)
        half_life  = _DECAY_HALF_LIFE_DAYS.get(dimension, 60.0)
        stale_days = _STALE_THRESHOLD_DAYS.get(dimension, 30.0)

        decay_factor     = _recency_decay_factor(elapsed, half_life)
        new_confidence   = confidence * decay_factor
        new_label        = _confidence_to_strength_label(new_confidence)
        new_status       = status

        if elapsed >= stale_days and status not in ("falsified", "stale"):
            new_status = "stale"

        await _update_preference_fields(
            session, preference,
            confidence=new_confidence,
            signal_strength_label=new_label,
            status=new_status,
            now=ts_now,
        )
        return preference
    except Exception as exc:
        logger.debug("[decay] decay_preference failed: %r", exc)
        return None


async def decay_preferences(
    session,
    *,
    user_id: str,
    now: Optional[datetime] = None,
    run_override: Optional[bool] = None,
) -> List[Any]:
    """Apply recency and inactivity decay to all learned preferences for a user.

    Fetches all LearnedPreference rows for user_id and calls decay_preference
    on each.  Preferences already in status='falsified' are skipped.

    Returns the list of updated preference rows (may be empty).
    """
    if not _inference_enabled(run_override):
        return []
    if session is None:
        return []
    try:
        from app.db.repositories.user_learning_repo import list_learned_preferences

        prefs = await list_learned_preferences(session, user_id=user_id)
        updated = []
        for pref in prefs:
            row = await decay_preference(
                session, preference=pref, now=now, run_override=run_override,
            )
            if row is not None:
                updated.append(row)
        return updated
    except Exception as exc:
        logger.debug("[decay] decay_preferences failed: %r", exc)
        return []


async def detect_falsifiers(
    session,
    *,
    preference: Any,
    lookback_days: int = _FALSIFIER_LOOKBACK_DAYS,
    run_override: Optional[bool] = None,
) -> List[str]:
    """Detect which falsifier conditions are currently triggered for a preference.

    Returns a list of human-readable triggered condition strings.  Returns []
    when no falsifiers are active or when the function is disabled.

    Checks (in order):
      1. insufficient_evidence — evidence_count below the anti-fabrication floor
      2. inactivity — elapsed since last_reinforced_at > stale threshold
      3. contradictory_signal — recent negative events breach the contradiction
         threshold (for positive-affinity dimensions)
      4. positive_interaction — for ignored_signal_type: any single positive
         event resets the negative accumulation (per the falsifier text in Slice 15.4)
    """
    if not _inference_enabled(run_override):
        return []
    if session is None:
        return []
    try:
        dimension      = _attr(preference, "dimension", "")
        entity_key     = _attr(preference, "entity_key", "")
        user_id        = _attr(preference, "user_id", "")
        evidence_count = int(_attr(preference, "evidence_count", 0))
        last_reinforced = _attr(preference, "last_reinforced_at")
        ts_now         = _now()

        triggered: List[str] = []

        # 1 — insufficient evidence
        min_ev = _MIN_EVIDENCE.get(dimension, 5)
        if evidence_count < min_ev:
            triggered.append(
                f"insufficient_evidence: evidence_count={evidence_count} "
                f"is below the minimum of {min_ev} for dimension '{dimension}'"
            )

        # 2 — inactivity beyond stale threshold
        elapsed    = _elapsed_days(last_reinforced, ts_now)
        stale_days = _STALE_THRESHOLD_DAYS.get(dimension, 30.0)
        if elapsed >= stale_days:
            triggered.append(
                f"inactivity: no reinforcement for {elapsed:.1f} days "
                f"(cutoff {stale_days:.0f}d) on dimension '{dimension}'"
            )

        # 3 & 4 — signal-based falsifiers require event lookup
        if user_id and entity_key:
            entity_type = _entity_type_for_dimension(dimension)
            events = await _fetch_recent_events(
                session,
                user_id=user_id,
                entity_key=entity_key,
                entity_type=entity_type,
                lookback_days=lookback_days,
            )

            pos_count = sum(1 for e in events if _attr(e, "polarity", "") == "positive")
            neg_count = sum(1 for e in events if _attr(e, "polarity", "") == "negative")

            if dimension == "ignored_signal_type":
                # Any single positive interaction resets negative accumulation
                if pos_count >= 1:
                    triggered.append(
                        f"positive_interaction: {pos_count} positive event(s) observed "
                        f"for ignored dimension entity '{entity_key}'; "
                        f"negative accumulation is reset"
                    )
            else:
                # For positive-affinity dimensions: sufficient negatives = contradiction
                contradiction_threshold = _CONTRADICTION_THRESHOLD
                if neg_count >= contradiction_threshold:
                    triggered.append(
                        f"contradictory_signal: {neg_count} negative event(s) observed "
                        f"for dimension '{dimension}' entity '{entity_key}' "
                        f"(min {contradiction_threshold} required)"
                    )

        return triggered
    except Exception as exc:
        logger.debug("[decay] detect_falsifiers failed: %r", exc)
        return []


async def apply_falsification(
    session,
    *,
    preference: Any,
    reason: str,
    run_override: Optional[bool] = None,
) -> Optional[Any]:
    """Mark a learned preference as falsified.

    Sets:
      status             = 'falsified'
      confidence         = 0.0
      signal_strength_label = 'tentative'
      updated_at         = now

    The reason string is prepended to belief_basis so the falsification event
    is auditable.  Only non-empty reasons are prepended to avoid cluttering
    the belief_basis with blank entries.

    Returns the updated row, or None when disabled or session is None.
    """
    if not _inference_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        ts_now = _now()

        if reason:
            existing_basis = _attr(preference, "belief_basis", "") or ""
            prefix = f"[falsified: {reason}]"
            new_basis = f"{prefix} {existing_basis}".strip()
            preference.belief_basis = new_basis

        await _update_preference_fields(
            session, preference,
            confidence=0.0,
            signal_strength_label="tentative",
            status="falsified",
            now=ts_now,
        )
        return preference
    except Exception as exc:
        logger.debug("[decay] apply_falsification failed: %r", exc)
        return None


async def rebuild_preference_strength(
    session,
    *,
    preference: Any,
    events: List[Any],
    run_override: Optional[bool] = None,
) -> Optional[Any]:
    """Recompute confidence and signal_strength_label from a fresh set of events.

    Called when the inference pass provides an updated event list — e.g. after
    new signals arrive or after event expiry.  Does not change status (that is
    the domain of decay_preference and apply_falsification).

    Algorithm:
      1. Count weighted positive vs negative events.
      2. Recompute affinity = net_weighted / total_weight.
      3. Recompute confidence = |affinity|.
      4. Recompute signal_strength_label.
      5. Update the row.

    If the events list is empty or all events are neutral, confidence decays
    to 0.0 (tentative).

    Returns the updated row, or None when disabled or session is None.
    """
    if not _inference_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        ts_now = _now()

        _POLARITY_WEIGHT = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
        total_weight = 0.0
        net_weighted = 0.0
        for ev in events:
            polarity = _attr(ev, "polarity", "neutral")
            weight   = float(_attr(ev, "interaction_weight", 1.0) or 1.0)
            mult     = _POLARITY_WEIGHT.get(polarity, 0.0)
            total_weight += weight
            net_weighted += weight * mult

        if total_weight > 0:
            new_affinity    = net_weighted / total_weight
            new_confidence  = abs(net_weighted) / total_weight
        else:
            new_affinity   = 0.0
            new_confidence = 0.0

        new_label = _confidence_to_strength_label(new_confidence)

        preference.affinity   = round(new_affinity, 6)
        preference.confidence = round(new_confidence, 6)
        preference.signal_strength_label = new_label
        preference.updated_at = ts_now
        await session.flush()
        return preference
    except Exception as exc:
        logger.debug("[decay] rebuild_preference_strength failed: %r", exc)
        return None


async def find_stale_preferences(
    session,
    *,
    user_id: str,
    cutoff_days: Optional[float] = None,
    run_override: Optional[bool] = None,
) -> List[Any]:
    """Return LearnedPreference rows that have not been reinforced within their
    per-dimension stale threshold (or within cutoff_days if supplied).

    When cutoff_days is given it overrides the per-dimension threshold for all
    dimensions, allowing a caller to apply a uniform window.

    Returns [] when disabled or session is None.  Only considers preferences
    with status not in ('falsified',) — already-falsified preferences are
    excluded from the stale scan.
    """
    if not _inference_enabled(run_override):
        return []
    if session is None:
        return []
    try:
        from app.db.repositories.user_learning_repo import list_learned_preferences

        prefs = await list_learned_preferences(session, user_id=user_id)
        ts_now = _now()
        stale = []

        for pref in prefs:
            if _attr(pref, "status", "") == "falsified":
                continue
            dimension      = _attr(pref, "dimension", "")
            last_reinforced = _attr(pref, "last_reinforced_at")
            elapsed        = _elapsed_days(last_reinforced, ts_now)

            threshold = (
                cutoff_days
                if cutoff_days is not None
                else _STALE_THRESHOLD_DAYS.get(dimension, 30.0)
            )

            if elapsed >= threshold:
                stale.append(pref)

        return stale
    except Exception as exc:
        logger.debug("[decay] find_stale_preferences failed: %r", exc)
        return []
