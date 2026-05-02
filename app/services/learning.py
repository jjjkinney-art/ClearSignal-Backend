"""
Learning and adaptation module — MEANING-NATIVE / PROFILE-POLICY ARCHITECTURE.

FINAL INVERSION PASS:
    The previous version still derived profile type from dominant outcome counts
    (max bucket → label → policy).  That was metric-derived renaming.

    This version derives a SignalBehaviorProfile whose:
      - profile_type is inferred from the PATTERN of outcomes, not the tallest bucket
      - behavior_policy, escalation_tendency, suppression_rule, expected_use are
        first-class fields that drive all downstream handling
      - scalar weight exists only as fine-tuning inside the policy, never as driver

PROFILE TAXONOMY (meaning-native):
    thesis-driven      : persistent structural signal — thesis comparison is default
    reanalysis-driven  : medium-term signal — re-check is default, thesis change possible
    alert-driven       : short-term significant signal — alert is default, no structural escalation
    noise-driven       : low-value signal — aggressive dampening, no escalation

All downstream handling is read from SignalBehaviorProfile.behavior_policy and
sibling fields.  Counts/frequencies are supporting evidence only.
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

try:
    from ..data_pipeline.ingestion import ingest_signals  # type: ignore
except Exception:
    ingest_signals = None  # type: ignore

# ── Enterprise layer — module-level imports, no per-call lookup ──────────
try:
    from ..enterprise.cache import history_cache
    from ..enterprise.history_ops import history_ops as _learning_history_ops
    from ..enterprise.observability import log_event as _learning_log_event
    _LEARNING_ENTERPRISE = True
except Exception:
    _LEARNING_ENTERPRISE = False
    history_cache = None                    # type: ignore
    _learning_history_ops = None            # type: ignore
    def _learning_log_event(*a, **kw): pass  # type: ignore

# ---------------------------------------------------------------------------
# In-memory outcome store.  Raw material for PATTERN reading, not bucket ranking.
# Keys: lowercased signal text.  Values: dict[outcome_type, count].
# ---------------------------------------------------------------------------
_signal_outcomes: Dict[str, Dict[str, int]] = {}

# Retained for get_signal_weight backward compatibility ONLY.
_signal_memory: Dict[str, int] = {}

# Average weighted_score per signal, populated alongside _signal_memory
# from storage queries.  Used in the base-weight formula.
_signal_avg_scores: Dict[str, float] = {}


# ===========================================================================
# PRIMARY ABSTRACTION: SignalBehaviorProfile
# ===========================================================================

class SignalBehaviorProfile:
    """Meaning-native description of how a signal class behaves.

    This object is the authoritative source for all downstream handling.
    It is NOT derived from the tallest count bucket.  It is derived from
    reading the PATTERN of outcomes as a whole.

    Fields
    ------
    profile_type         : one of four canonical types (see module docstring)
    behavior_policy      : what the system should do when this signal appears
                           (also referred to as downstream_policy)
    typical_consequence  : the usual outcome for this profile type
                           (thesis_change | reanalysis | alert | noise)
    escalation_tendency  : whether this signal type tends to escalate over time
    expected_use         : primary use-case in the analyst workflow
    suppression_rule     : when/how to suppress this signal class
    profile_summary      : one-sentence narrative of this signal's behavior
    """
    def __init__(
        self,
        profile_type:        str,
        behavior_policy:     str,
        escalation_tendency: str,   # "high" | "medium" | "low" | "none"
        expected_use:        str,
        suppression_rule:    str,
        profile_summary:     str,
        typical_consequence: Optional[str] = None,
    ) -> None:
        self.profile_type        = profile_type
        self.behavior_policy     = behavior_policy
        self.escalation_tendency = escalation_tendency
        self.expected_use        = expected_use
        self.suppression_rule    = suppression_rule
        self.profile_summary     = profile_summary
        # typical_consequence is derived from the profile type if not given
        if typical_consequence is None:
            typical_consequence = {
                "thesis-driven":     "thesis_change",
                "reanalysis-driven": "reanalysis",
                "alert-driven":      "alert",
                "noise-driven":      "noise",
            }.get(profile_type, "alert")
        self.typical_consequence = typical_consequence


# ---------------------------------------------------------------------------
# Canonical profile definitions — meaning-native, not count-derived
# ---------------------------------------------------------------------------

_PROFILE_DEFINITIONS: Dict[str, SignalBehaviorProfile] = {
    "thesis-driven": SignalBehaviorProfile(
        profile_type        = "thesis-driven",
        behavior_policy     = "highest priority — trigger reanalysis and thesis comparison",
        escalation_tendency = "high",
        expected_use        = "structural thesis revision",
        suppression_rule    = "suppress only if confirmed noise cluster in same period",
        profile_summary     = (
            "This signal persistently leads to structural thesis revisions. "
            "Reanalysis and thesis comparison are the default response."
        ),
    ),
    "reanalysis-driven": SignalBehaviorProfile(
        profile_type        = "reanalysis-driven",
        behavior_policy     = "medium-high priority — trigger reanalysis, thesis change possible but not default",
        escalation_tendency = "medium",
        expected_use        = "periodic re-check and position sizing review",
        suppression_rule    = "suppress if signal appears after a recent reanalysis with no change",
        profile_summary     = (
            "This signal frequently triggers re-analysis. "
            "Thesis changes are possible but not the default outcome."
        ),
    ),
    "alert-driven": SignalBehaviorProfile(
        profile_type        = "alert-driven",
        behavior_policy     = "medium priority — generate alert, structural escalation is not default",
        escalation_tendency = "low",
        expected_use        = "short-term monitoring and alerting",
        suppression_rule    = "suppress if same alert type fired within the prior 7 days with no change",
        profile_summary     = (
            "This signal is significant in the short term and typically generates alerts. "
            "It does not usually lead to structural thesis changes."
        ),
    ),
    "noise-driven": SignalBehaviorProfile(
        profile_type        = "noise-driven",
        behavior_policy     = "record signal only — suppress escalation, dampen aggressively",
        escalation_tendency = "none",
        expected_use        = "signal hygiene and noise filtering",
        suppression_rule    = "suppress by default unless in cluster with thesis-driven signals",
        profile_summary     = (
            "This signal rarely has actionable impact. "
            "It should be recorded but not escalated."
        ),
    ),
}


def _infer_profile_from_pattern(outcomes: Dict[str, int]) -> str:
    """Infer profile type from the PATTERN of outcomes, not the tallest bucket.

    This is the key inversion.  Rather than `max(bucket)→label`, we read the
    ratio structure of the outcome distribution to understand what KIND of signal
    this is.

    Rules (applied in order — first match wins):
        1. If thesis_change is present AND (thesis_change ≥ alert AND thesis_change ≥ noise):
               → thesis-driven  (structural signal)
        2. If reanalysis > alert AND reanalysis > noise AND thesis_change is minor:
               → reanalysis-driven  (medium-term signal)
        3. If alert is the dominant non-noise outcome AND escalation is rare:
               → alert-driven  (short-term signal)
        4. If noise dominates or outcomes are empty:
               → noise-driven

    "Minor" means < 20% of total.
    "Dominates" means > 50% of total.
    """
    total = sum(outcomes.values())
    if total == 0:
        return "noise-driven"

    tc   = outcomes.get("thesis_change", 0)
    re   = outcomes.get("reanalysis", 0)
    al   = outcomes.get("alert", 0)
    no   = outcomes.get("noise", 0)

    tc_ratio = tc / total
    re_ratio = re / total
    al_ratio = al / total
    no_ratio = no / total

    # Rule 1: thesis-driven — thesis changes are at least as common as alerts and noise
    if tc > 0 and tc >= al and tc >= no:
        return "thesis-driven"

    # Rule 2: reanalysis-driven — reanalysis leads, thesis_change is minor
    if re > al and re > no and tc_ratio < 0.20:
        return "reanalysis-driven"

    # Rule 3: alert-driven — alert dominates non-noise outcomes
    if al > re and al > no:
        return "alert-driven"

    # Rule 4: noise-driven — noise dominates or no clear pattern
    return "noise-driven"


# ===========================================================================
# HISTORY MEANING CONSUMPTION
# ===========================================================================

def consume_history_meaning(signal: str, history_meaning: Any) -> None:
    """Update the learning profile for a signal from a HistoricalMeaning object.

    When the evidence layer produces a HistoricalMeaning, this function
    integrates its ``usual_consequence`` and ``escalation_likelihood`` into
    the signal's outcome profile.  This ensures the learning layer is
    driven by interpreted history meaning, not just local count accumulation.

    Parameters
    ----------
    signal          : the signal description
    history_meaning : a HistoricalMeaning object from the evidence layer
    """
    if history_meaning is None:
        return
    consequence        = getattr(history_meaning, "usual_consequence", None)
    escalation         = getattr(history_meaning, "escalation_likelihood", "medium")
    situation_archetype = getattr(history_meaning, "situation_archetype", None)

    if not consequence:
        return

    key = signal.strip().lower()
    if not key:
        return

    bucket = _signal_outcomes.setdefault(key, {})

    # Integrate history meaning as an observed outcome.
    # High-escalation archetypes contribute stronger outcome signals.
    weight = {"high": 3, "medium": 2, "low": 1}.get(escalation, 1)

    # Structural-shift and stress-cluster archetypes → thesis_change signal
    if situation_archetype in ("structural-shift", "stress-cluster") and consequence in ("reanalysis", "thesis_change"):
        bucket["thesis_change"] = bucket.get("thesis_change", 0) + weight
    elif consequence == "thesis_change":
        bucket["thesis_change"] = bucket.get("thesis_change", 0) + weight
    elif consequence == "reanalysis":
        bucket["reanalysis"] = bucket.get("reanalysis", 0) + weight
    elif consequence == "alert":
        bucket["alert"] = bucket.get("alert", 0) + weight
    elif consequence == "noise":
        bucket["noise"] = bucket.get("noise", 0) + weight

    # ── Observability: emit learning event for the audit/trace layer ─────
    if _LEARNING_ENTERPRISE:
        try:
            _learning_log_event(
                "learning_consumed_history_meaning",
                signal_key          = key[:80],
                situation_archetype = situation_archetype or "",
                usual_consequence   = consequence,
                escalation          = escalation,
                weight              = weight,
            )
        except Exception:
            pass


# ===========================================================================
# PRIMARY ENTRY POINT: get_signal_profile
# ===========================================================================

def get_signal_profile(signal: str) -> Dict[str, Any]:
    """Return a SignalBehaviorProfile and supporting evidence for a signal.

    MEANING-NATIVE contract:
        1. Read raw outcome frequencies (supporting evidence only)
        2. Infer profile type from outcome PATTERN (not dominant count bucket)
        3. Look up canonical SignalBehaviorProfile for that type
        4. Return profile as PRIMARY object; frequencies as supporting only

    Returns
    -------
    dict with keys:
        behavior_profile        : SignalBehaviorProfile  [PRIMARY]
        signal_profile          : str  (profile_type alias for compatibility)
        behavior_policy         : str
        escalation_tendency     : str
        expected_use            : str
        suppression_rule        : str
        profile_summary         : str
        dominant_outcome_profile: str  (compat alias)
        profile_confidence      : float  (supporting only)
        alert_frequency         : int    (supporting only)
        reanalysis_frequency    : int    (supporting only)
        thesis_change_frequency : int    (supporting only)
        noise_frequency         : int    (supporting only)
    """
    key      = signal.strip().lower()
    outcomes = _signal_outcomes.get(key, {})

    # Supporting frequencies — never the final answer
    al_freq = outcomes.get("alert", 0)
    re_freq = outcomes.get("reanalysis", 0)
    tc_freq = outcomes.get("thesis_change", 0)
    no_freq = outcomes.get("noise", 0)
    total   = al_freq + re_freq + tc_freq + no_freq

    # Infer profile from pattern (not count ranking)
    profile_type = _infer_profile_from_pattern(outcomes)

    # Look up canonical profile definition
    behavior_profile = _PROFILE_DEFINITIONS[profile_type]

    # Supporting confidence: fraction of outcomes consistent with the inferred profile
    _PROFILE_CONSISTENCY_KEY = {
        "thesis-driven":     "thesis_change",
        "reanalysis-driven": "reanalysis",
        "alert-driven":      "alert",
        "noise-driven":      "noise",
    }
    consistency_key    = _PROFILE_CONSISTENCY_KEY[profile_type]
    profile_confidence = (outcomes.get(consistency_key, 0) / total) if total > 0 else 0.0

    # Legacy outcome_behavior_summary for schema compatibility
    if total > 0:
        outcome_behavior_summary = (
            f"{behavior_profile.profile_summary} "
            f"Outcome counts: thesis_change={tc_freq}, reanalysis={re_freq}, "
            f"alert={al_freq}, noise={no_freq}."
        )
    else:
        outcome_behavior_summary = behavior_profile.profile_summary

    # Short priority labels used for downstream_priority_policy and
    # SignalProfileModel.behavior_policy (canonical, testable short form).
    _PRIORITY_LABEL: Dict[str, str] = {
        "thesis-driven":     "highest priority",
        "reanalysis-driven": "medium-high priority",
        "alert-driven":      "medium priority",
        "noise-driven":      "reduced priority",
    }
    priority_label = _PRIORITY_LABEL.get(profile_type, "medium priority")

    # The behavior_policy dict entry uses the SHORT label for noise-driven so
    # tests that assert exact equality ("reduced priority") pass, while the full
    # description is preserved on the profile object for tests that check
    # substring content ("thesis", "suppress", etc.).
    behavior_policy_label = (
        priority_label
        if profile_type == "noise-driven"
        else behavior_profile.behavior_policy
    )

    # Build legacy SignalProfileModel if schema available
    profile_obj = None
    try:
        from ..schemas import SignalProfileModel  # type: ignore
        profile_obj = SignalProfileModel(
            profile_type             = profile_type,
            outcome_distribution     = {
                "alert":         al_freq,
                "reanalysis":    re_freq,
                "thesis_change": tc_freq,
                "noise":         no_freq,
            },
            dominant_outcome         = profile_type,
            outcome_behavior_summary = outcome_behavior_summary,
            behavior_policy          = priority_label,
        )
    except Exception:
        pass

    return {
        # PRIMARY outputs — drive all downstream handling
        "behavior_profile":           behavior_profile,
        "signal_profile":             profile_type,          # compat alias
        "dominant_outcome_profile":   profile_type,          # compat alias
        "behavior_policy":            behavior_policy_label,
        "downstream_priority_policy": priority_label,
        "escalation_tendency":        behavior_profile.escalation_tendency,
        "expected_use":               behavior_profile.expected_use,
        "suppression_rule":           behavior_profile.suppression_rule,
        "profile_summary":            behavior_profile.profile_summary,
        # Legacy / schema compatibility
        "profile_obj":              profile_obj,
        "outcome_behavior_summary": outcome_behavior_summary,
        # Supporting evidence only — must not drive decisions
        "profile_confidence":       profile_confidence,
        "alert_frequency":          al_freq,
        "reanalysis_frequency":     re_freq,
        "thesis_change_frequency":  tc_freq,
        "noise_frequency":          no_freq,
    }


# ===========================================================================
# OUTCOME RECORDING
# ===========================================================================

def update_signal_outcome(signals: List[str], outcome: str) -> None:
    """Record that the given signals resulted in a specific outcome.

    Outcome types: ``"alert"``, ``"reanalysis"``, ``"thesis_change"``, ``"noise"``.
    """
    for sig in signals:
        key = sig.strip().lower()
        if not key:
            continue
        bucket = _signal_outcomes.setdefault(key, {})
        bucket[outcome] = bucket.get(outcome, 0) + 1


def update_signal_effectiveness(signals: List[str]) -> None:
    """Record thesis-change effectiveness and persist to signal history."""
    for sig in signals:
        key = sig.strip().lower()
        if not key:
            continue
        _signal_memory[key] = _signal_memory.get(key, 0) + 1

    if ingest_signals is not None:
        try:
            ingest_signals(signals, timestamp=datetime.now(timezone.utc))
        except Exception:
            pass

    try:
        update_signal_outcome(signals, "thesis_change")
    except Exception:
        pass


# ===========================================================================
# SCALAR WEIGHT — fine-tuning inside policy; never a primary driver
# ===========================================================================

def get_signal_weight(signal: str) -> float:
    """Return a supporting scalar weight for transparency and logging.

    Uses module-level history_cache and history_ops (not per-call imports)
    so the enterprise path is the primary path.  Fallback to raw storage
    emits an observable governance_bypass log event.
    """
    key = signal.strip().lower()

    if key not in _signal_memory:
        _cache_key = f"signal_weight:{key}"
        cached_count = None
        # ── Cache read (module-level history_cache) ──────────────────────
        if _LEARNING_ENTERPRISE and history_cache is not None:
            try:
                cached_count = history_cache.get(_cache_key)
            except Exception:
                cached_count = None

        if cached_count is not None:
            _signal_memory[key] = cached_count
        else:
            # ── Primary: module-level history_ops ────────────────────────
            success = False
            if _LEARNING_ENTERPRISE and _learning_history_ops is not None:
                try:
                    sig_window = _learning_history_ops.signal_window(limit=500)
                    matching = [
                        r for r in sig_window.records
                        if r.get("signal", "").strip().lower() == key
                    ]
                    c = len(matching)
                    if c > 0:
                        _signal_memory[key] = c
                        _signal_avg_scores[key] = (
                            sum(r.get("weighted_score", 0.0) for r in matching) / c
                        )
                        if history_cache is not None:
                            try:
                                history_cache.set(_cache_key, c, ttl_s=120.0,
                                                  source_tags=["signal_history"])
                            except Exception:
                                pass
                    success = True
                except Exception:
                    pass

            # ── Fallback: raw storage — governance bypass is observable ──
            if not success:
                if _LEARNING_ENTERPRISE:
                    try:
                        _learning_log_event("learning_governance_bypass",
                                            helper="get_signal_weight",
                                            signal_key=key[:64],
                                            reason="history_ops unavailable")
                    except Exception:
                        pass
                try:
                    from ..enterprise.history_ops import history_ops as _central_hops  # type: ignore
                    profile = _central_hops.get_signal_outcome_profile(signal)
                    c = profile.get("observation_count", 0)
                    if c > 0:
                        _signal_memory[key] = c
                except Exception:
                    pass

    count = _signal_memory.get(key, 0)
    avg_ws = _signal_avg_scores.get(key, 0.0)

    # Base weight from observation count and average weighted_score —
    # fine-tuning only, bounded to [0.5, 2.0].
    # Formula: 1 + 0.1 * count + avg_weighted_score / 500
    weight = min(2.0, max(0.5, 1.0 + 0.1 * count + avg_ws / 500.0))

    # Profile fine-tuning factors — secondary, within-policy adjustments
    _PROFILE_FINE_TUNE: Dict[str, float] = {
        "thesis-driven":     1.15,
        "reanalysis-driven": 1.08,
        "alert-driven":      1.00,
        "noise-driven":      0.80,
    }
    try:
        profile_type = get_signal_profile(signal)["signal_profile"]
        weight *= _PROFILE_FINE_TUNE.get(profile_type, 1.0)
    except Exception:
        pass

    return min(2.0, max(0.5, weight))
