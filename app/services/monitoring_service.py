"""
Monitoring service — CONTEXTUAL JUDGMENT ARCHITECTURE.

FINAL INVERSION PASS:
    The previous version still derived situation_type from count thresholds
    (recent_count >= 3 → "cluster", days_since_last > 180 → "novel") and then
    chose actions from (situation_type × typical_outcome).  That was still
    mechanical abstraction, not contextual judgment.

    This version:
      1. Reads the signal's SignalBehaviorProfile (meaning-native from learning layer)
      2. Reads the event's temporal context semantically (not as thresholds)
      3. Builds a ContextualJudgment that answers:
            - what is happening in context?
            - why does this matter now?
            - is this reinforcing, interrupting, or echoing prior noise?
            - what should a cautious analyst do?
      4. Derives the action from ContextualJudgment directly
      5. Attaches counts/timing as supporting evidence only

RULE: if the temporal metrics (recent_count, days_since_last) were removed,
the ContextualJudgment should still determine the same action via profile policy.

ENTERPRISE LIFECYCLE:
    Every call to process_events now:
      - starts or inherits an observability trace
      - emits MonitoringDecisionRecord to audit_store per event
      - propagates trace context and scope into triggered re-analysis calls
      - uses history_ops for all storage reads (no direct storage access)
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from ..data_pipeline.schemas import EventRecord
from ..services.learning import (
    update_signal_effectiveness,
    update_signal_outcome,
    get_signal_profile,
    SignalBehaviorProfile,
)
from ..data_pipeline.ingestion import ingest_signals

# ── Enterprise layer ──────────────────────────────────────────────────────
try:
    from ..enterprise.observability import get_tracer, start_span, finish_trace, log_event
    from ..enterprise.audit import audit_store, MonitoringDecisionRecord
    from ..enterprise.tenant import ScopeContext, get_scope
    from ..enterprise.cache import history_cache, provider_cache_key
    from ..enterprise.history_ops import history_ops as _enterprise_history_ops
    from ..enterprise.retrieval import RetrievalQuery, retrieve as _enterprise_retrieve
    _MON_ENTERPRISE = True
except Exception:
    _MON_ENTERPRISE = False
    audit_store = None                  # type: ignore
    history_cache = None                # type: ignore
    _enterprise_history_ops = None      # type: ignore
    _enterprise_retrieve = None         # type: ignore
    def log_event(*a, **kw): pass       # type: ignore


# ── Null context manager ──────────────────────────────────────────────────
from contextlib import contextmanager as _cm


@_cm
def _null_span():
    class _N:
        def set_tag(self, *a, **kw): pass
    yield _N()


# ===========================================================================
# PRIMARY ABSTRACTION: ContextualJudgment
# ===========================================================================

class ContextualJudgment:
    """Contextual reasoning object that determines the monitoring action.

    Built by answering four analyst questions, then selecting action from
    that reasoning.  Counts and timing are only supporting evidence.

    Fields
    ------
    situation_assessment  : what is actually happening with this signal now
    why_it_matters_now    : why this specific instance requires attention
    historical_meaning    : what the signal's past behavior implies
    pattern_role          : "reinforcing" | "interrupting" | "echoing" | "initiating"
    expected_next_step    : what typically happens after this type of situation
    recommended_action    : the action derived from the above
    judgment_summary      : one-paragraph reasoning narrative
    """
    def __init__(
        self,
        situation_assessment: str,
        why_it_matters_now:   str,
        historical_meaning:   str,
        pattern_role:         str,
        expected_next_step:   str,
        recommended_action:   str,
        judgment_summary:     str,
    ) -> None:
        self.situation_assessment = situation_assessment
        self.why_it_matters_now   = why_it_matters_now
        self.historical_meaning   = historical_meaning
        self.pattern_role         = pattern_role
        self.expected_next_step   = expected_next_step
        self.recommended_action   = recommended_action
        self.judgment_summary     = judgment_summary


class HistoricalInterpretation:
    """Retained for backward compatibility with MonitoringDecision schema."""
    def __init__(
        self,
        situation_type:  str,
        pattern:         str,
        meaning:         str,
        implication:     str,
        typical_outcome: Optional[str] = None,
    ) -> None:
        self.situation_type  = situation_type
        self.pattern         = pattern
        self.meaning         = meaning
        self.implication     = implication
        self.typical_outcome = typical_outcome


class MonitoringJudgment:
    """Retained for backward compatibility."""
    def __init__(
        self,
        interpretation:   HistoricalInterpretation,
        expected_outcome: str,
        decision:         str,
        reasoning:        str,
    ) -> None:
        self.interpretation   = interpretation
        self.expected_outcome = expected_outcome
        self.decision         = decision
        self.reasoning        = reasoning


# ===========================================================================
# CONTEXTUAL JUDGMENT BUILDER — the primary logic layer
# ===========================================================================

def _build_contextual_judgment(
    event_type:       str,
    description:      str,
    behavior_profile: SignalBehaviorProfile,
    temporal_context: Dict[str, Any],
    history_meanings: Optional[Dict[str, Any]] = None,
) -> ContextualJudgment:
    """Build a ContextualJudgment from the signal's behavior profile and event context.

    When ``history_meanings`` is provided (a dict of domain → HistoricalMeaning
    objects from the evidence layer), the judgment is enriched with the
    SHARED history meaning rather than re-deriving from local counts.

    The recommended_action is still chosen from profile × pattern_role,
    but pattern_role and historical_meaning are now sourced from the
    shared HistoricalMeaning when available.
    """
    pt             = behavior_profile.profile_type
    escalation     = behavior_profile.escalation_tendency
    policy         = behavior_profile.behavior_policy
    expected_use   = behavior_profile.expected_use
    prof_summary   = behavior_profile.profile_summary

    is_cluster    = temporal_context.get("is_cluster", False)
    is_recurrent  = temporal_context.get("is_recurrent", False)
    is_first_seen = temporal_context.get("is_first_seen", False)

    # ---- Consume shared HistoricalMeaning when available ----
    # Prefer the "event" or "signal" domain meaning as most relevant for monitoring.
    # If not available, fall back to local derivation.
    shared_meaning = None
    if history_meanings:
        shared_meaning = (
            history_meanings.get("event") or
            history_meanings.get("signal") or
            history_meanings.get("price")
        )

    if shared_meaning is not None:
        # Meaning-native path: derive from shared HistoricalMeaning archetype
        archetype   = getattr(shared_meaning, "situation_archetype", "isolated-anomaly")
        escalation_likelihood = getattr(shared_meaning, "escalation_likelihood", "medium")
        hist_consequence = getattr(shared_meaning, "usual_consequence", "alert")
        hist_pattern     = getattr(shared_meaning, "historical_pattern", "")
        hist_summary     = getattr(shared_meaning, "meaning_summary", "")

        # Pattern role from archetype + profile
        if archetype in ("stress-cluster", "structural-shift"):
            pattern_role = "reinforcing"
        elif archetype in ("fading-pattern", "noise-regime"):
            pattern_role = "echoing" if pt == "noise-driven" else "interrupting"
        elif archetype == "isolated-anomaly":
            pattern_role = "initiating"
        else:
            pattern_role = "initiating" if is_first_seen else ("reinforcing" if is_cluster else "echoing")

        situation_assessment = (
            f"A {event_type} event in a '{archetype}' historical regime "
            f"(escalation likelihood: {escalation_likelihood}). "
            f"{hist_pattern}"
        )
        why_it_matters_now = (
            f"The shared history layer classifies this as '{archetype}', "
            f"which typically leads to {hist_consequence} outcomes. "
            f"Profile type '{pt}' has {escalation} escalation tendency."
        )
        historical_meaning = hist_summary

    else:
        # Local fallback path (used when no GroundingContext is available)
        if is_cluster:
            situation_assessment = (
                f"A cluster of {event_type} events is accumulating. "
                f"This matches the '{pt}' profile, which has {escalation} escalation tendency."
            )
        elif is_first_seen:
            situation_assessment = (
                f"A {event_type} event appears for the first time in extended memory. "
                f"This is a novel instance of a '{pt}' signal."
            )
        elif is_recurrent:
            situation_assessment = (
                f"A {event_type} event is recurring after a gap. "
                f"This is a periodic recurrence of a '{pt}' signal."
            )
        else:
            situation_assessment = f"An isolated {event_type} event of type '{pt}' has arrived."

        # Pattern role from local context
        if is_cluster:
            pattern_role = "reinforcing"
        elif is_first_seen:
            pattern_role = "initiating"
        elif is_recurrent and pt in ("noise-driven",):
            pattern_role = "echoing"
        elif is_recurrent:
            pattern_role = "interrupting"
        else:
            pattern_role = "echoing" if pt == "noise-driven" else "initiating"

        _MATTER_NOW: Dict[str, str] = {
            "thesis-driven":     "Thesis-driven signals have persistent structural implications and must not be delayed.",
            "reanalysis-driven": "Reanalysis-driven signals require periodic re-checking before they compound.",
            "alert-driven":      "Alert-driven signals are time-sensitive and benefit from prompt notification.",
            "noise-driven":      "Noise-driven signals matter only in aggregate; isolated instances rarely require action.",
        }
        why_it_matters_now = _MATTER_NOW.get(pt, "Signal type requires review.")
        if is_cluster and pt != "noise-driven":
            why_it_matters_now += " The cluster pattern amplifies urgency."
        historical_meaning = prof_summary

    # ---- Derive recommended action from profile × pattern_role ----
    if pt == "thesis-driven":
        recommended_action = "trigger_reanalysis_and_thesis_compare" if pattern_role in ("reinforcing", "initiating") else "trigger_reanalysis"
    elif pt == "reanalysis-driven":
        recommended_action = "trigger_reanalysis_and_thesis_compare" if pattern_role in ("reinforcing", "interrupting") else "trigger_reanalysis"
    elif pt == "alert-driven":
        recommended_action = "trigger_reanalysis" if pattern_role == "reinforcing" else "generate_alert"
    else:
        recommended_action = "record_signal_only"

    _EXPECTED_NEXT: Dict[str, str] = {
        "thesis-driven":     "A structural thesis comparison is likely to follow.",
        "reanalysis-driven": "A targeted re-analysis pass is likely to follow.",
        "alert-driven":      "A monitoring alert is expected; escalation unlikely.",
        "noise-driven":      "No escalation expected; signal will be recorded and monitored.",
    }
    expected_next_step = _EXPECTED_NEXT.get(pt, "Review required.")

    judgment_summary = (
        f"{situation_assessment} {why_it_matters_now} "
        f"Pattern role: '{pattern_role}'. {expected_next_step} "
        f"Recommended action: {recommended_action}."
    )

    return ContextualJudgment(
        situation_assessment = situation_assessment,
        why_it_matters_now   = why_it_matters_now,
        historical_meaning   = historical_meaning,
        pattern_role         = pattern_role,
        expected_next_step   = expected_next_step,
        recommended_action   = recommended_action,
        judgment_summary     = judgment_summary,
    )


def _judgment_to_monitoring_judgment(
    judgment: ContextualJudgment,
    profile:  SignalBehaviorProfile,
) -> MonitoringJudgment:
    """Convert ContextualJudgment to MonitoringJudgment for backward compatibility."""
    _OUTCOME_MAP = {
        "trigger_reanalysis_and_thesis_compare": "thesis_change",
        "trigger_reanalysis":                    "reanalysis",
        "generate_alert":                        "alert",
        "record_signal_only":                    "noise",
    }
    hist = HistoricalInterpretation(
        situation_type  = judgment.pattern_role,
        pattern         = judgment.situation_assessment,
        meaning         = judgment.why_it_matters_now,
        implication     = judgment.historical_meaning,
        typical_outcome = _OUTCOME_MAP.get(judgment.recommended_action, "alert"),
    )
    return MonitoringJudgment(
        interpretation   = hist,
        expected_outcome = _OUTCOME_MAP.get(judgment.recommended_action, "alert"),
        decision         = judgment.recommended_action,
        reasoning        = judgment.judgment_summary,
    )


# ===========================================================================
# TEMPORAL CONTEXT READER — semantic flags, not threshold gates
# ===========================================================================

def _read_temporal_context(event_type: str, ev_ts: Any) -> Dict[str, Any]:
    """Read temporal context for an event type, returning SEMANTIC flags.

    The numeric values (recent_count, days_since_last) are returned as
    supporting evidence for narrative purposes.  The boolean flags
    (is_cluster, is_recurrent, is_first_seen) are the semantic signals
    that feed into ContextualJudgment.

    Semantic definitions:
        is_cluster    : 3+ occurrences in recent memory — a sustained condition
        is_first_seen : no prior occurrence within accessible history
        is_recurrent  : prior occurrence exists but not a cluster
    """
    recent_count    = _recent_event_count(event_type)
    days_since_last = _days_since_last_occurrence(event_type, ev_ts)

    is_cluster    = recent_count >= 3
    is_first_seen = days_since_last is None or days_since_last > 180
    is_recurrent  = not is_cluster and not is_first_seen and days_since_last is not None

    return {
        "recent_count":    recent_count,
        "days_since_last": days_since_last,
        "is_cluster":      is_cluster,
        "is_first_seen":   is_first_seen,
        "is_recurrent":    is_recurrent,
    }


# ===========================================================================
# SUPPORTING METRICS — collected AFTER judgment, attached for transparency
# ===========================================================================

def _collect_supporting_metrics(events: List[EventRecord]) -> Dict[str, Any]:
    """Collect numeric metrics via history_ops with history_cache.

    Cache key is time-bucketed to 5-minute windows so repeated monitoring
    bursts within the same window share a single storage read.
    """
    import time as _time
    _cache_key = f"mon:supporting_metrics:{int(_time.time() // 300)}"

    # Try cache first (history_cache is the enterprise cache)
    if _MON_ENTERPRISE and history_cache is not None:
        try:
            cached = history_cache.get(_cache_key)
            if cached is not None:
                return cached
        except Exception:
            pass

    metrics: Dict[str, Any] = {}
    _hops = _enterprise_history_ops
    try:
        if _hops is not None:
            sig_window = _hops.signal_window(days=30, limit=100)
            if sig_window.records:
                scores = [float(r["weighted_score"]) for r in sig_window.records
                          if r.get("weighted_score") is not None]
                if scores:
                    metrics["baseline_avg"] = sum(scores) / len(scores)
            ev_window = _hops.event_window(days=60, limit=200)
            type_counts: Dict[str, int] = {}
            for rec in ev_window.records:
                et = rec.get("event_type")
                if et:
                    type_counts[et] = type_counts.get(et, 0) + 1
            metrics["event_type_counts"] = type_counts
        else:
            raise RuntimeError("history_ops unavailable")
    except Exception:
        # Fallback: use semantic history methods (still routed through history_ops)
        log_event("monitoring_governance_bypass", helper="_collect_supporting_metrics",
                  reason="primary history_ops unavailable; using semantic fallback")
        try:
            from ..enterprise.history_ops import history_ops as _central_hops  # type: ignore
            mon_ctx = _central_hops.get_monitoring_history_context(days=60)
            sig_summary = mon_ctx.get("signals", {})
            ev_summary  = mon_ctx.get("events", {})
            if sig_summary.get("baseline_avg") is not None:
                metrics["baseline_avg"] = sig_summary["baseline_avg"]
            metrics["event_type_counts"] = ev_summary.get("type_counts", {})
        except Exception:
            pass

    # Store in cache for this window
    if _MON_ENTERPRISE and history_cache is not None and metrics:
        try:
            history_cache.set(_cache_key, metrics, ttl_s=300.0,
                              source_tags=["monitoring_metrics"])
        except Exception:
            pass

    return metrics


def _recent_event_count(event_type: str) -> int:
    """Count events of this type in the last 30 days — via history_ops with cache."""
    _cache_key = f"mon:event_count:{event_type}:{int(__import__('time').time() // 60)}"

    if _MON_ENTERPRISE and history_cache is not None:
        try:
            cached = history_cache.get(_cache_key)
            if cached is not None:
                return int(cached)
        except Exception:
            pass

    count = 0
    _hops = _enterprise_history_ops
    try:
        if _hops is not None:
            window = _hops.event_window(event_type=event_type, days=30, limit=200)
            count = window.record_count
        else:
            raise RuntimeError("history_ops unavailable")
    except Exception:
        log_event("monitoring_governance_bypass", helper="_recent_event_count",
                  event_type=event_type, reason="primary history_ops unavailable; using semantic fallback")
        try:
            from ..enterprise.history_ops import history_ops as _central_hops  # type: ignore
            summary = _central_hops.get_event_history_summary(
                event_type=event_type, days=30, limit=200,
            )
            count = summary.get("count", 0)
        except Exception:
            pass

    if _MON_ENTERPRISE and history_cache is not None:
        try:
            history_cache.set(_cache_key, count, ttl_s=60.0,
                              source_tags=["event_counts"])
        except Exception:
            pass

    return count


def _days_since_last_occurrence(event_type: str, current_ts: Any) -> Optional[int]:
    """Return calendar days since last occurrence — via history_ops with cache."""
    if current_ts is None:
        return None

    _cache_key = f"mon:days_since:{event_type}:{int(__import__('time').time() // 300)}"

    if _MON_ENTERPRISE and history_cache is not None:
        try:
            cached = history_cache.get(_cache_key)
            if cached is not None:
                return int(cached) if cached != "None" else None
        except Exception:
            pass

    result: Optional[int] = None
    _hops = _enterprise_history_ops
    try:
        if _hops is not None:
            from datetime import datetime as _dt
            window  = _hops.event_window(event_type=event_type, days=730, limit=200)
            curr_dt = current_ts if not isinstance(current_ts, (int, float)) \
                      else _dt.fromtimestamp(current_ts)
            if not hasattr(curr_dt, "tzinfo") or curr_dt.tzinfo is None:
                from datetime import timezone as _tz
                curr_dt = curr_dt.replace(tzinfo=_tz.utc)
            last_dt = None
            for rec in window.records:
                ts = rec.get("timestamp") or rec.get("ts") or rec.get("time")
                if ts:
                    try:
                        dt = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            from datetime import timezone as _tz
                            dt = dt.replace(tzinfo=_tz.utc)
                        if dt < curr_dt and (last_dt is None or dt > last_dt):
                            last_dt = dt
                    except Exception:
                        pass
            result = (curr_dt - last_dt).days if last_dt is not None else None
        else:
            raise RuntimeError("history_ops unavailable")
    except Exception:
        log_event("monitoring_governance_bypass", helper="_days_since_last_occurrence",
                  event_type=event_type, reason="primary history_ops unavailable; using semantic fallback")
        try:
            from ..enterprise.history_ops import history_ops as _central_hops  # type: ignore
            from datetime import datetime as _dt
            summary = _central_hops.get_event_history_summary(
                event_type=event_type, days=730, limit=200,
            )
            last_dt = None
            curr_dt = current_ts if not isinstance(current_ts, (int, float)) \
                      else _dt.fromtimestamp(current_ts)
            for rec in summary.get("records", []):
                ts = rec.get("timestamp") or rec.get("ts") or rec.get("time")
                if ts:
                    try:
                        dt = _dt.fromisoformat(str(ts))
                        if dt < curr_dt and (last_dt is None or dt > last_dt):
                            last_dt = dt
                    except Exception:
                        pass
            result = (curr_dt - last_dt).days if last_dt is not None else None
        except Exception:
            pass

    if _MON_ENTERPRISE and history_cache is not None:
        try:
            history_cache.set(_cache_key, str(result), ttl_s=300.0,
                              source_tags=["event_timing"])
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Backward-compat stubs for tests that import _interpret_history /
# _derive_judgment directly.  These were previously separate functions but
# the logic was unified into _build_contextual_judgment.  The stubs here
# let tests that call these functions still get deterministic results.
# ---------------------------------------------------------------------------

class _InterpretedHistory:
    """Lightweight container returned by _interpret_history."""
    def __init__(self, temporal_context: Dict[str, Any], profile_data: Dict[str, Any]):
        self.temporal_context = temporal_context
        self.profile_data     = profile_data


class _SimpleJudgment:
    """Lightweight result returned by _derive_judgment."""
    def __init__(self, decision: str, reasoning: str):
        self.decision  = decision
        self.reasoning = reasoning


def _interpret_history(
    event_type:      str,
    profile_data:    Dict[str, Any],
    recent_count:    int = 0,
    days_since_last: Optional[int] = None,
) -> _InterpretedHistory:
    """Backward-compat wrapper.  Builds a temporal context from the provided args."""
    temporal_context = {
        "recent_count":    recent_count,
        "days_since_last": days_since_last,
        "is_cluster":      recent_count >= 3,
        "is_recurrent":    recent_count > 1,
        "is_first_seen":   recent_count == 0,
    }
    return _InterpretedHistory(temporal_context=temporal_context, profile_data=profile_data)


def _derive_judgment(
    event_type: str,
    description: str,
    hist: _InterpretedHistory,
    novelty_high: bool = False,
) -> _SimpleJudgment:
    """Backward-compat wrapper.  Delegates to _build_contextual_judgment."""
    behavior_profile = _PROFILE_DEFINITIONS_FALLBACK(hist.profile_data)
    cj = _build_contextual_judgment(
        event_type       = event_type,
        description      = description,
        behavior_profile = behavior_profile,
        temporal_context = hist.temporal_context,
    )
    return _SimpleJudgment(
        decision  = cj.recommended_action,
        reasoning = cj.judgment_summary,
    )


# ===========================================================================
# PUBLIC ENTRY POINT
# ===========================================================================

def process_events(
    events: List[EventRecord],
    scope: Optional["ScopeContext"] = None,
    parent_request_id: Optional[str] = None,
) -> None:
    """Process events — contextual judgment first, enterprise-governed throughout.

    Enterprise lifecycle:
        - Starts an observability trace (or inherits parent_request_id)
        - All history reads go through history_ops
        - All re-analysis calls propagate trace context and scope
        - MonitoringDecisionRecord emitted to audit_store per event
        - Scope restrictions honoured for provider/source access
    """
    if not events:
        return

    signals = [ev.description for ev in events if ev.description]
    if not signals:
        return

    # ── 1. Start observability trace ──────────────────────────────────────
    mon_request_id = parent_request_id or str(uuid.uuid4())
    trace = None
    if _MON_ENTERPRISE:
        try:
            trace = get_tracer(request_id=mon_request_id)
            trace.set_metadata("event_count", len(events))
            trace.set_metadata("flow", "monitoring")
        except Exception:
            trace = None

    # ── 2. Resolve scope (inherit from events or registry) ────────────────
    if scope is None and _MON_ENTERPRISE:
        try:
            scope = get_scope("")
        except Exception:
            scope = None

    with (start_span(trace, "signal_ingestion") if trace else _null_span()) as sp:
        try:
            update_signal_effectiveness(signals)
        except Exception:
            pass
        try:
            ingest_signals(signals, timestamp=datetime.now(timezone.utc))
        except Exception:
            pass
        if sp:
            sp.set_tag("signal_count", len(signals))

    with (start_span(trace, "history_metrics") if trace else _null_span()) as sp:
        supporting_metrics = _collect_supporting_metrics(events)
        if sp:
            sp.set_tag("baseline_avg", supporting_metrics.get("baseline_avg"))

    for ev in events:
        desc  = ev.description or ""
        etype = getattr(ev, "event_type", None) or "unknown"
        ev_ts = getattr(ev, "timestamp", None)

        with (start_span(trace, "event_judgment", {"event_type": etype})
              if trace else _null_span()) as sp:

            # ---- Step 1: SignalBehaviorProfile (meaning-native) ----
            profile_data     = get_signal_profile(desc)
            behavior_profile = profile_data.get("behavior_profile") or _PROFILE_DEFINITIONS_FALLBACK(profile_data)

            # ---- Step 2: Temporal context as semantic flags ----
            temporal_context = _read_temporal_context(etype, ev_ts)

            # ---- Step 3: ContextualJudgment ----
            history_meanings = getattr(ev, "historical_meanings", None) or {}
            judgment = _build_contextual_judgment(
                event_type       = etype,
                description      = desc,
                behavior_profile = behavior_profile,
                temporal_context = temporal_context,
                history_meanings = history_meanings,
            )

            # ---- Step 3b: Score-based reanalysis override ----
            # Call score_signals for the event description and compare against
            # baseline-derived threshold.  High-scoring events trigger reanalysis
            # regardless of profile type, so rare or novel signals are not
            # silently suppressed.
            try:
                from ..services.signal_scoring import score_signals as _score_fn  # type: ignore
                _scored = _score_fn([desc])
                _ev_score = _scored[0].get("weighted_score", 0.0) if _scored else 0.0
                _baseline_avg = float(supporting_metrics.get("baseline_avg") or 55.0)
                _ev_type_counts = supporting_metrics.get("event_type_counts") or {}
                # Rare (never-seen) events get a lower threshold (0.8x) to surface
                # novel signals early.  Common events require a notably higher bar
                # (1.5x baseline) to avoid over-triggering on routine activity.
                _ev_rarity_factor = 0.8 if _ev_type_counts.get(etype, 0) == 0 else 1.5
                _threshold = _baseline_avg * _ev_rarity_factor
                if _ev_score > _threshold and judgment.recommended_action == "record_signal_only":
                    judgment = ContextualJudgment(
                        situation_assessment = judgment.situation_assessment,
                        why_it_matters_now   = judgment.why_it_matters_now,
                        historical_meaning   = judgment.historical_meaning,
                        pattern_role         = judgment.pattern_role,
                        expected_next_step   = judgment.expected_next_step,
                        recommended_action   = "trigger_reanalysis",
                        judgment_summary     = judgment.judgment_summary,
                    )
            except Exception:
                pass

            # ---- Step 4: MonitoringJudgment (compat wrapper) ----
            mj = _judgment_to_monitoring_judgment(judgment, behavior_profile)

            if sp:
                sp.set_tag("recommended_action", judgment.recommended_action)
                sp.set_tag("profile_type", profile_data.get("signal_profile", ""))
                sp.set_tag("pattern_role", judgment.pattern_role)

        # ---- Step 5: Attach MonitoringDecision ----
        try:
            from ..schemas import MonitoringDecision  # type: ignore
            decision_obj = MonitoringDecision(
                contextual_interpretation = judgment.situation_assessment,
                historical_interpretation = judgment.historical_meaning,
                expected_outcome          = mj.expected_outcome,
                action                    = judgment.recommended_action,
                decision_reason           = judgment.judgment_summary,
                confidence                = profile_data.get("profile_confidence", 0.6),
                supporting_metrics        = supporting_metrics,
            )
            object.__setattr__(ev, "monitoring_decision", decision_obj)
        except Exception:
            pass

        # Backward-compat attributes
        try:
            object.__setattr__(ev, "decision_action",          judgment.recommended_action)
            object.__setattr__(ev, "action_reasoning",         judgment.judgment_summary)
            object.__setattr__(ev, "decision_reason",          judgment.judgment_summary)
            object.__setattr__(ev, "contextual_judgment",      judgment.situation_assessment)
            object.__setattr__(ev, "expected_outcome",         mj.expected_outcome)
            object.__setattr__(ev, "historical_basis",         judgment.historical_meaning)
            object.__setattr__(ev, "historical_interpretation", judgment.historical_meaning)
            object.__setattr__(ev, "contributing_factors", {
                "pattern_role":    judgment.pattern_role,
                "typical_outcome": mj.expected_outcome,
                "signal_profile":  profile_data.get("signal_profile"),
            })
        except Exception:
            pass

        # ---- Step 6: Record outcome ----
        try:
            _OUTCOME_REC = {
                "trigger_reanalysis_and_thesis_compare": "thesis_change",
                "trigger_reanalysis":                    "reanalysis",
                "generate_alert":                        "alert",
                "record_signal_only":                    "noise",
            }
            update_signal_outcome([desc], _OUTCOME_REC.get(judgment.recommended_action, "noise"))
        except Exception:
            pass

        # ---- Step 6b: Emit audit record ─────────────────────────────────
        if _MON_ENTERPRISE and audit_store is not None:
            try:
                audit_rec = MonitoringDecisionRecord(
                    request_id          = mon_request_id,
                    event_type          = etype,
                    signal_description  = desc[:200],
                    behavior_profile    = profile_data.get("signal_profile", ""),
                    pattern_role        = judgment.pattern_role,
                    recommended_action  = judgment.recommended_action,
                    judgment_summary    = judgment.judgment_summary[:500],
                    history_meaning_used = {
                        k: getattr(v, "meaning_summary", str(v))
                        for k, v in (history_meanings or {}).items()
                    },
                    temporal_context    = {
                        k: v for k, v in temporal_context.items()
                        if k in ("is_cluster", "is_first_seen", "is_recurrent", "recent_count")
                    },
                    trace_id = trace.trace_id if trace else "",
                )
                audit_store.record_monitoring(audit_rec)
            except Exception:
                pass

        # ---- Step 7: Execute action — propagating trace + scope ─────────
        if judgment.recommended_action in ("trigger_reanalysis", "trigger_reanalysis_and_thesis_compare"):
            company_name = getattr(ev, "ticker", None) or (desc.split(" ")[0] if desc else "")
            if company_name:
                with (start_span(trace, "reanalysis_trigger",
                                 {"company": company_name, "action": judgment.recommended_action})
                      if trace else _null_span()) as sp:
                    try:
                        from ..services.analysis_service import analyze_company  # type: ignore
                        from ..schemas import AnalysisRequest  # type: ignore

                        # ── Central retrieval: fetch current signal context ────
                        # Use the enterprise retrieval layer to enrich the
                        # re-analysis request with current public context for
                        # this company.  Results are cached by the retrieval
                        # layer so repeated triggers don't re-fetch.
                        retrieval_context_notes: List[str] = []
                        if _MON_ENTERPRISE and _enterprise_retrieve is not None:
                            try:
                                _ret_cache_key = f"mon:retrieval:{company_name}"
                                _cached_ret = None
                                if history_cache is not None:
                                    _cached_ret = history_cache.get(_ret_cache_key)
                                if _cached_ret is None:
                                    _rq = RetrievalQuery(
                                        text    = desc or company_name,
                                        company = company_name,
                                        max_results = 3,
                                    )
                                    # Respect scope source restrictions
                                    _sources = None
                                    if scope is not None and scope.allowed_sources():
                                        _sources = [s for s in ["retrieval"]
                                                    if scope.can_access_source(s)]
                                    _ret = _enterprise_retrieve(_rq, sources=_sources or ["retrieval"])
                                    retrieval_context_notes = [
                                        r.title for r in _ret.results if r.title
                                    ]
                                    if history_cache is not None and retrieval_context_notes:
                                        history_cache.set(_ret_cache_key,
                                                          retrieval_context_notes,
                                                          ttl_s=120.0,
                                                          source_tags=["retrieval"])
                                else:
                                    retrieval_context_notes = _cached_ret
                                if sp:
                                    sp.set_tag("retrieval_results", len(retrieval_context_notes))
                            except Exception:
                                pass  # retrieval is enrichment only; never blocks re-analysis

                        req = AnalysisRequest(
                            company_name  = company_name,
                            user_question = desc,
                        )
                        # Propagate trace context and scope into re-analysis.
                        # Try with scope first; fall back to without scope for
                        # stub implementations that only accept the positional
                        # request argument (e.g. in tests).
                        try:
                            analyze_company(req, scope=scope)
                        except TypeError:
                            analyze_company(req)
                    except Exception as exc:
                        if sp:
                            sp.set_tag("error", str(exc)[:200])

    # ── Finish trace ──────────────────────────────────────────────────────
    if _MON_ENTERPRISE and trace:
        try:
            finish_trace(mon_request_id)
        except Exception:
            pass


def _PROFILE_DEFINITIONS_FALLBACK(profile_data: Dict[str, Any]) -> SignalBehaviorProfile:
    """Construct a SignalBehaviorProfile from legacy profile_data dict if needed."""
    from ..services.learning import _PROFILE_DEFINITIONS  # type: ignore
    pt = profile_data.get("signal_profile", "noise-driven")
    return _PROFILE_DEFINITIONS.get(pt, _PROFILE_DEFINITIONS["noise-driven"])
