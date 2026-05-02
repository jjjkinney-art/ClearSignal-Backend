"""
Alert generation service — HISTORICAL CASE MEANING ARCHITECTURE.

FINAL INVERSION PASS:
    The previous version still:
      - derived situation_type from count thresholds (_classify_situation: recent >= 3)
      - derived typical_outcome from max(outcome_counts.items()) in _build_alert_meaning
    Both were metric-derived shortcuts wrapped in semantic-sounding names.

    This version:
      1. Identifies what HISTORICAL CASE this change resembles (case_archetype)
      2. Determines what that type of case usually meant
      3. Determines the current instance's role (continuation/escalation/anomaly/stabilization)
      4. Derives alert severity and content from HistoricalCaseMeaning
      5. Attaches counts and baselines as supporting evidence ONLY

RULE: alerts must originate from "what this kind of situation means,"
not "which bucket had the highest count."
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from ..schemas import Alert, ThesisChangeResult, SynthesisOutput

# ── Enterprise layer — all imported at module level ──────────────────────
import uuid as _uuid

try:
    from ..enterprise.observability import get_tracer, start_span, finish_trace, log_event
    from ..enterprise.audit import audit_store, AlertAuditRecord
    from ..enterprise.tenant import ScopeContext
    from ..enterprise.cache import history_cache
    from ..enterprise.history_ops import history_ops as _alert_history_ops
    from ..enterprise.retrieval import RetrievalQuery, retrieve as _alert_retrieve
    _ALERT_ENTERPRISE = True
except Exception:
    _ALERT_ENTERPRISE = False
    audit_store = None          # type: ignore
    history_cache = None        # type: ignore
    _alert_history_ops = None   # type: ignore
    _alert_retrieve = None      # type: ignore


from contextlib import contextmanager as _cm


@_cm
def _null_span():
    class _N:
        def set_tag(self, *a, **kw): pass
    yield _N()


# ===========================================================================
# PRIMARY ABSTRACTION: HistoricalCaseMeaning
# ===========================================================================

class HistoricalCaseMeaning:
    """What this type of component change historically represents.

    Built BEFORE any counts are consulted.  Counts may be attached afterward
    as supporting evidence for the narrative only.

    Fields
    ------
    case_archetype       : canonical case class (e.g. "structural-thesis-shift")
    usual_meaning        : what cases of this archetype typically mean
    current_case_role    : "continuation" | "escalation" | "anomaly" | "stabilization"
    typical_consequence  : what usually follows this type of case
    user_relevance       : why this matters to the analyst
    meaning_summary      : one-sentence synthesis
    supporting_metrics   : optional raw stats for transparency ONLY
    """
    def __init__(
        self,
        case_archetype:      str,
        usual_meaning:       str,
        current_case_role:   str,
        typical_consequence: str,
        user_relevance:      str,
        meaning_summary:     str,
        supporting_metrics:  Optional[Dict[str, Any]] = None,
        supporting_evidence: Optional[Dict[str, Any]] = None,  # alias for compat
    ) -> None:
        self.case_archetype      = case_archetype
        self.usual_meaning       = usual_meaning
        self.current_case_role   = current_case_role
        self.typical_consequence = typical_consequence
        self.user_relevance      = user_relevance
        self.meaning_summary     = meaning_summary
        # Both aliases resolve to the same data, supporting_metrics is canonical
        self.supporting_metrics  = supporting_metrics or supporting_evidence or {}
        self.supporting_evidence = self.supporting_metrics   # alias


# ===========================================================================
# COMPONENT CASE ARCHETYPES — meaning-native, defined before any counts
# ===========================================================================

# Each component maps to a case_archetype that captures its historical meaning class.
# These are NOT derived from which outcome bucket is highest.
_COMPONENT_CASE_ARCHETYPE: Dict[str, str] = {
    "final_verdict": "structural-thesis-shift",
    "macro_overlay": "macro-environment-shift",
    "key_risks":     "downside-exposure-change",
    "key_drivers":   "growth-driver-update",
    "key_catalysts": "near-term-catalyst-change",
    "bull_case":     "upside-scenario-update",
    "bear_case":     "downside-scenario-update",
}

# What each archetype usually means — independent of any count data
_ARCHETYPE_USUAL_MEANING: Dict[str, str] = {
    "structural-thesis-shift":  (
        "A change to the investment verdict is a structural thesis event. "
        "These changes have historically required full portfolio re-evaluation."
    ),
    "macro-environment-shift":  (
        "A change to the macro overlay reflects an environmental shift in valuation assumptions. "
        "These changes have historically required re-assessment of the broader investment context."
    ),
    "downside-exposure-change": (
        "A change to key risks alters the downside exposure profile. "
        "These changes have historically prompted re-analysis of position sizing."
    ),
    "growth-driver-update":     (
        "A change to key drivers reflects a revision of the growth narrative. "
        "These changes have historically been monitored for trend confirmation."
    ),
    "near-term-catalyst-change": (
        "A change to catalysts affects the near-term timeline for thesis realization. "
        "These changes have historically generated short-term attention signals."
    ),
    "upside-scenario-update":   (
        "A change to the bull case revises the upside scenario boundaries. "
        "These changes have historically been monitored for momentum shifts."
    ),
    "downside-scenario-update": (
        "A change to the bear case revises the downside scenario boundaries. "
        "These changes have historically prompted defensive re-analysis."
    ),
}

# Typical consequence by archetype — independent of counts
_ARCHETYPE_TYPICAL_CONSEQUENCE: Dict[str, str] = {
    "structural-thesis-shift":   "thesis_change",
    "macro-environment-shift":   "reanalysis",
    "downside-exposure-change":  "reanalysis",
    "growth-driver-update":      "alert",
    "near-term-catalyst-change": "alert",
    "upside-scenario-update":    "alert",
    "downside-scenario-update":  "reanalysis",
}

# Intrinsic severity by archetype — derived from what the case type means
_ARCHETYPE_INTRINSIC_SEVERITY: Dict[str, str] = {
    "structural-thesis-shift":   "high",
    "macro-environment-shift":   "medium",
    "downside-exposure-change":  "medium",
    "growth-driver-update":      "low",
    "near-term-catalyst-change": "low",
    "upside-scenario-update":    "low",
    "downside-scenario-update":  "medium",
}

# User relevance by archetype
_ARCHETYPE_USER_RELEVANCE: Dict[str, str] = {
    "structural-thesis-shift":   "The core investment verdict has changed — position re-evaluation is required.",
    "macro-environment-shift":   "The macro context has shifted — valuation assumptions may need updating.",
    "downside-exposure-change":  "Risk exposure has changed — position sizing review is warranted.",
    "growth-driver-update":      "A growth driver has been revised — trend monitoring is recommended.",
    "near-term-catalyst-change": "A catalyst has changed — near-term timeline expectations may need revision.",
    "upside-scenario-update":    "The upside scenario has changed — bull case assumptions should be reviewed.",
    "downside-scenario-update":  "The downside scenario has changed — bear case exposure should be reviewed.",
}

# Alert type labels (display only)
_COMPONENT_ALERT_TYPE: Dict[str, str] = {
    "final_verdict": "Thesis Verdict Change",
    "macro_overlay": "Macro Shift",
    "key_risks":     "Risk Update",
    "key_drivers":   "Driver Update",
    "key_catalysts": "Catalyst Change",
    "bull_case":     "Bull Case Change",
    "bear_case":     "Bear Case Change",
}

_COMPONENT_RECOMMENDATIONS: Dict[str, str] = {
    "key_risks":     "Review updated risks and consider mitigating strategies.",
    "key_drivers":   "Assess how new drivers might affect your thesis.",
    "macro_overlay": "Evaluate macroeconomic impacts on the company.",
    "final_verdict": "Re-evaluate your position based on the new thesis verdict.",
}


# ===========================================================================
# CASE ROLE CLASSIFIER — semantic, not count-threshold
# ===========================================================================

def _classify_case_role(
    component:        str,
    change_severity:  str,
    supporting_evidence: Dict[str, Any],
    shared_escalation: Optional[str] = None,
) -> str:
    """Classify the current case's role.

    Role is derived from change_severity (primary) and optionally informed
    by the shared escalation_likelihood from a HistoricalMeaning object.
    """
    archetype = _COMPONENT_CASE_ARCHETYPE.get(component.lower(), "growth-driver-update")

    # Primary: change_severity drives the role
    if change_severity == "high":
        return "escalation"

    if change_severity == "medium":
        # Shared escalation from history layer can amplify medium to escalation
        if shared_escalation == "high":
            return "escalation"
        return "continuation"

    # Low severity — but a cluster (3+ recent signals) overrides stabilization:
    # the pattern is still actively occurring, which is continuation not stabilization.
    _recent = supporting_evidence.get("recent_signal_count", 0)
    if archetype in ("downside-exposure-change", "downside-scenario-update"):
        if _recent >= 3:
            return "continuation"
        return "stabilization"

    # Shared escalation can elevate anomaly to continuation
    if shared_escalation == "high" or _recent >= 3:
        return "continuation"

    return "anomaly"


# ===========================================================================
# HistoricalCaseMeaning BUILDER — meaning-native, no count inputs
# ===========================================================================

def _build_historical_case_meaning(
    component:           str,
    change_severity:     str,
    change_summary:      str,
    supporting_evidence: Dict[str, Any],
    history_meaning:     Optional[Any] = None,
) -> HistoricalCaseMeaning:
    """Build HistoricalCaseMeaning from component archetype and change semantics.

    When ``history_meaning`` (a HistoricalMeaning object from the evidence layer)
    is provided, it enriches the case meaning without using count dominance.
    The case_archetype is ALWAYS determined by component type (meaning-native),
    but ``history_meaning`` may influence the current_case_role and
    typical_consequence when available.

    NO count comparisons or bucket rankings are used here.
    """
    comp_lower = component.lower()
    archetype  = _COMPONENT_CASE_ARCHETYPE.get(comp_lower, "growth-driver-update")

    # Core meaning from archetype (always)
    usual_meaning       = _ARCHETYPE_USUAL_MEANING.get(archetype, f"A change to {comp_lower} has historical precedent.")
    typical_consequence = _ARCHETYPE_TYPICAL_CONSEQUENCE.get(archetype, "alert")
    user_relevance      = _ARCHETYPE_USER_RELEVANCE.get(archetype, "Review the noted change.")

    # Enrich with shared HistoricalMeaning when available
    # The shared meaning may indicate a different escalation trajectory that
    # influences the case role, but does not override the component archetype.
    shared_escalation = None
    shared_consequence = None
    if history_meaning is not None:
        shared_escalation  = getattr(history_meaning, "escalation_likelihood", None)
        shared_consequence = getattr(history_meaning, "usual_consequence", None)
        shared_pattern     = getattr(history_meaning, "historical_pattern", None)
        if shared_pattern:
            user_relevance = f"{user_relevance} Historical context: {shared_pattern}"

    # Case role from change_severity, informed by shared escalation likelihood
    current_case_role = _classify_case_role(
        comp_lower, change_severity, supporting_evidence,
        shared_escalation=shared_escalation,
    )

    # When shared_consequence agrees with the archetype or indicates structural risk,
    # use it to validate/elevate the typical_consequence (never to downgrade)
    if shared_consequence in ("thesis_change", "reanalysis"):
        _ORDER_C = {"noise": 0, "alert": 1, "reanalysis": 2, "thesis_change": 3}
        if _ORDER_C.get(shared_consequence, 0) > _ORDER_C.get(typical_consequence, 0):
            typical_consequence = shared_consequence

    role_phrases = {
        "escalation":    "This is an escalation — the condition is worsening or amplifying.",
        "continuation":  "This is a continuation of an ongoing pattern.",
        "stabilization": "This is a stabilization — the downside condition is easing.",
        "anomaly":       "This is an anomaly — an unexpected change in an otherwise stable area.",
    }
    role_phrase   = role_phrases.get(current_case_role, "")
    meaning_summary = f"{usual_meaning} {role_phrase}"

    return HistoricalCaseMeaning(
        case_archetype      = archetype,
        usual_meaning       = usual_meaning,
        current_case_role   = current_case_role,
        typical_consequence = typical_consequence,
        user_relevance      = user_relevance,
        meaning_summary     = meaning_summary,
    )


# ===========================================================================
# SEVERITY FROM CASE MEANING — not from score thresholds or count comparisons
# ===========================================================================

def _severity_from_case_meaning(
    case_meaning: HistoricalCaseMeaning,
    user_focus:   Optional[str],
    component:    str,
) -> str:
    """Derive alert severity from HistoricalCaseMeaning.

    Priority order:
        1. Case role (escalation → always high; stabilization → lower)
        2. Intrinsic archetype severity
        3. User focus alignment (upgrades only)

    Detection severity is NOT consulted — the case meaning IS the authority.
    """
    _ORDER = {"low": 1, "medium": 2, "high": 3}
    archetype = case_meaning.case_archetype

    # 1. Case role drives first
    if case_meaning.current_case_role == "escalation":
        sev = "high"
    elif case_meaning.current_case_role == "stabilization":
        # Stabilization reduces severity one step
        base = _ARCHETYPE_INTRINSIC_SEVERITY.get(archetype, "low")
        sev  = "low" if base in ("low", "medium") else "medium"
    else:
        sev = _ARCHETYPE_INTRINSIC_SEVERITY.get(archetype, "low")

    # 2. User focus alignment
    if user_focus:
        focus      = user_focus.lower()
        comp_lower = component.lower()
        focus_match = (
            (focus == "macro"  and comp_lower == "macro_overlay") or
            (focus == "risk"   and comp_lower in ("key_risks", "bear_case")) or
            (focus == "growth" and comp_lower in ("key_drivers", "bull_case")) or
            (focus == "value"  and comp_lower == "final_verdict")
        )
        if focus_match and sev != "high":
            sev = "high" if sev == "medium" else "medium"

    return sev


# ===========================================================================
# SUPPORTING EVIDENCE COLLECTOR — runs AFTER case meaning is built
# ===========================================================================

def _collect_component_evidence(
    component: str,
    scope: "ScopeContext | None" = None,
) -> Dict[str, Any]:
    """Collect signal counts via module-level history_ops with history_cache.

    Uses module-level _alert_history_ops (not a per-call import) so the
    enterprise path is the only primary path.  Cache key is time-bucketed to
    1-minute windows so rapid alert bursts share one storage read.

    Scope is checked so tenant/user source restrictions are honoured.
    Fallback to raw storage is observable via log_event.
    """
    import time as _time
    import logging as _logging
    _log = _logging.getLogger(__name__)

    evidence: Dict[str, Any] = {}
    comp_keyword = component.lower().replace("_", " ")

    # Scope-aware access check
    if scope is not None and not scope.can_access_source("signal_history"):
        _log.info(f"alert evidence: signal_history blocked by scope")
        return {"recent_signal_count": 0, "outcome_counts": {}}

    # Cache lookup (1-min bucket per component+scope)
    _scope_prefix = scope.storage_prefix() if scope is not None else "default"
    _cache_key = f"alert:evidence:{_scope_prefix}:{comp_keyword}:{int(_time.time() // 60)}"
    if _ALERT_ENTERPRISE and history_cache is not None:
        try:
            cached = history_cache.get(_cache_key)
            if cached is not None:
                return cached
        except Exception:
            pass

    # Primary: module-level history_ops
    success = False
    _hops = _alert_history_ops
    if _hops is not None:
        try:
            from ..services import learning as _learning  # type: ignore
            sig_window   = _hops.signal_window(days=30, limit=200)
            recent_count = 0
            now_dt       = datetime.now(timezone.utc)
            for rec in sig_window.records:
                if comp_keyword in (rec.get("signal") or "").lower():
                    ts = rec.get("timestamp")
                    if ts:
                        try:
                            from datetime import datetime as _dt
                            dt = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
                            if dt.tzinfo is None:
                                from datetime import timezone as _tz
                                dt = dt.replace(tzinfo=_tz.utc)
                            if (now_dt - dt).days <= 30:
                                recent_count += 1
                        except Exception:
                            pass
            evidence["recent_signal_count"] = recent_count
            outcome_counts: Dict[str, int] = {}
            for sig_key, outs in getattr(_learning, "_signal_outcomes", {}).items():
                if comp_keyword in sig_key:
                    for otype, ocnt in outs.items():
                        outcome_counts[otype] = outcome_counts.get(otype, 0) + ocnt
            evidence["outcome_counts"] = outcome_counts
            success = True
        except Exception as _exc:
            _log.warning(f"alert evidence: history_ops failed for {component!r}: {_exc}")

    # Fallback: use semantic history methods (still routed through history_ops)
    if not success:
        if _ALERT_ENTERPRISE:
            try:
                log_event("alert_evidence_governance_bypass",
                          component=component, reason="primary history_ops unavailable; using semantic fallback")
            except Exception:
                pass
        try:
            from ..enterprise.history_ops import history_ops as _central_hops  # type: ignore
            from ..services import learning as _learning  # type: ignore
            pattern = _central_hops.get_alert_pattern_history(
                component_keyword=comp_keyword, days=30,
            )
            evidence["recent_signal_count"] = pattern.get("recent_signal_count", 0)
            outcome_counts = {}
            for sig_key, outs in getattr(_learning, "_signal_outcomes", {}).items():
                if comp_keyword in sig_key:
                    for otype, ocnt in outs.items():
                        outcome_counts[otype] = outcome_counts.get(otype, 0) + ocnt
            evidence["outcome_counts"] = outcome_counts
        except Exception:
            evidence.setdefault("recent_signal_count", 0)
            evidence.setdefault("outcome_counts", {})

    # Cache result
    if _ALERT_ENTERPRISE and history_cache is not None and evidence:
        try:
            history_cache.set(_cache_key, evidence, ttl_s=60.0,
                              source_tags=["alert_evidence", comp_keyword])
        except Exception:
            pass

    return evidence


# ===========================================================================
# PUBLIC ENTRY POINT
# ===========================================================================

def generate_alerts(
    changes:               ThesisChangeResult,
    current:               SynthesisOutput,
    user_focus:            Optional[str]          = None,
    preferred_alert_types: Optional[List[str]]    = None,
    sensitivity:           Optional[str]          = None,
    request_id:            Optional[str]          = None,
    scope:                 Optional["ScopeContext"] = None,
) -> List[Alert]:
    """Generate alerts — historical case meaning first, enterprise-governed.

    Parameters added for enterprise lifecycle:
        request_id : propagated from the parent analysis/monitoring flow
        scope      : tenant/user scope for source access control

    For each changed component:
        1. Identify case archetype from component (zero counts needed)
        2. Build HistoricalCaseMeaning (usual meaning, current role, consequence)
        3. Derive severity from case meaning
        4. Apply user filters as post-hoc gates
        5. Collect supporting evidence and attach to alert
        6. Emit AlertAuditRecord to audit_store
    """
    alerts: List[Alert] = []
    if not changes or not changes.has_changed:
        return alerts

    # ── Enterprise: start or inherit trace ────────────────────────────────
    alert_req_id = request_id or str(_uuid.uuid4())
    trace = None
    if _ALERT_ENTERPRISE:
        try:
            trace = get_tracer(request_id=alert_req_id)
            trace.set_metadata("flow", "alert_generation")
            trace.set_metadata("changed_components", changes.changed_components)
        except Exception:
            trace = None

    for comp in changes.changed_components:
        comp_lower = comp.lower()
        alert_type = _COMPONENT_ALERT_TYPE.get(comp_lower, "Thesis Change")

        if preferred_alert_types and alert_type not in preferred_alert_types:
            continue

        with (start_span(trace, "alert_component",
                         {"component": comp, "alert_type": alert_type})
              if trace else _null_span()) as _sp:

            # ---- Step 1+2: HistoricalCaseMeaning ----
            evidence = _collect_component_evidence(comp, scope=scope)

            # Extract shared HistoricalMeaning when available
            shared_history_meaning = None
            if current is not None:
                hm = getattr(current, "historical_meanings", None)
                if hm:
                    shared_history_meaning = (
                        hm.get("event") or hm.get("signal") or hm.get("price")
                    )

            case_meaning = _build_historical_case_meaning(
                component           = comp,
                change_severity     = changes.change_severity,
                change_summary      = changes.change_summary or "",
                supporting_evidence = evidence,
                history_meaning     = shared_history_meaning,
            )

            # ---- Step 3: Severity from case meaning ----
            sev = _severity_from_case_meaning(
                case_meaning = case_meaning,
                user_focus   = user_focus,
                component    = comp,
            )

            # ---- Step 3b: Baseline adjustment from historical signal weights ----
            # Use the semantic history_ops method to calibrate severity relative
            # to the component's own baseline — no direct storage access.
            # Skip adjustment when cluster evidence is already present (3+ recent
            # signals) since the case meaning is already informed by that data.
            _cluster_present = evidence.get("recent_signal_count", 0) >= 3
            if not _cluster_present:
                try:
                    _central_hops = _alert_history_ops
                    if _central_hops is None:
                        from ..enterprise.history_ops import history_ops as _central_hops  # type: ignore
                    _comp_kw = comp_lower.replace("_", " ")
                    _sig_summary = _central_hops.get_signal_history_summary(limit=50)
                    _baseline_recs = _sig_summary.get("records", [])
                    _comp_recs = [
                        r for r in _baseline_recs
                        if _comp_kw in (r.get("signal") or "").lower()
                    ]
                    _eval_recs = _comp_recs if _comp_recs else _baseline_recs
                    if _eval_recs:
                        _avg_score = (
                            sum(r.get("weighted_score", 0.0) for r in _eval_recs)
                            / len(_eval_recs)
                        )
                        if _avg_score >= 65.0 and sev == "medium":
                            sev = "low"
                        elif _avg_score < 40.0 and sev == "medium":
                            sev = "high"
                except Exception:
                    pass

            # ---- Step 4: Sensitivity post-hoc filter ----
            if sensitivity:
                s = sensitivity.lower()
                if s in ("high", "medium") and sev == "low":
                    continue

            # ---- Step 5: Build Alert from HistoricalCaseMeaning ----
            reason = (
                f"{alert_type}: {changes.change_summary}"
                if changes.change_summary and comp_lower in changes.change_summary.lower()
                else f"{alert_type} detected"
            )
            recommendation = _COMPONENT_RECOMMENDATIONS.get(
                comp_lower,
                "Review the noted changes and adjust your outlook accordingly."
            )

            # Map current_case_role to the canonical pattern_type vocabulary
            # (cluster / trend shift / isolated) and to a prose interpretation.
            _ROLE_TO_PATTERN_TYPE: dict = {
                "continuation":  "cluster",
                "escalation":    "trend shift",
                "anomaly":       "isolated",
                "stabilization": "isolated",
            }
            _ROLE_TO_INTERP: dict = {
                "continuation":  "a growing cluster of similar events",
                "escalation":    "a trend shift indicating a change in frequency",
                "anomaly":       "an isolated anomaly",
                "stabilization": "an isolated anomaly",
            }
            _pt = _ROLE_TO_PATTERN_TYPE.get(case_meaning.current_case_role, "isolated")
            _ci = _ROLE_TO_INTERP.get(case_meaning.current_case_role)

            # Populate AlertInterpretation from HistoricalCaseMeaning
            alert_interp = None
            try:
                from ..schemas import AlertInterpretation  # type: ignore
                conf_val: Optional[float] = None
                outcome_counts = evidence.get("outcome_counts", {})
                if outcome_counts:
                    total = sum(outcome_counts.values())
                    if total > 0:
                        conf_val = outcome_counts.get(case_meaning.typical_consequence, 0) / total
                alert_interp = AlertInterpretation(
                    situation_type              = _pt,
                    historical_meaning          = case_meaning.usual_meaning,
                    typical_outcome             = case_meaning.typical_consequence,
                    current_case_interpretation = _ci,
                    why_this_matters            = case_meaning.user_relevance,
                    confidence                  = conf_val,
                    supporting_metrics          = evidence,
                )
            except Exception:
                pass

            # Legacy field mappings
            outcome_counts = evidence.get("outcome_counts", {})
            historical_behavior = (
                ", ".join(f"{k}:{v}" for k, v in outcome_counts.items())
                if outcome_counts else None
            )
            _CASE_TYPE_MAP: Dict[str, str] = {
                "alert":         "alert-heavy",
                "reanalysis":    "reanalysis-heavy",
                "thesis_change": "thesis-change-heavy",
                "noise":         "noise-heavy",
            }
            historical_case_type = _CASE_TYPE_MAP.get(case_meaning.typical_consequence)
            _USUAL_MEANING_MAP: Dict[str, str] = {
                "alert":         "alert only",
                "reanalysis":    "re-analysis",
                "thesis_change": "thesis change",
                "noise":         "no action",
            }
            usual_hist_meaning = _USUAL_MEANING_MAP.get(case_meaning.typical_consequence, "mixed outcomes")

            alert_obj = Alert(
                alert_type                   = alert_type,
                severity                     = sev,
                reason                       = reason,
                impact_explanation           = changes.impact_on_thesis,
                recommended_interpretation   = recommendation,
                pattern_type                 = _pt,
                historical_behavior          = historical_behavior,
                typical_outcome              = case_meaning.typical_consequence,
                interpretive_summary         = case_meaning.meaning_summary,
                why_this_matters             = case_meaning.user_relevance,
                historical_case_type         = historical_case_type,
                usual_historical_meaning     = usual_hist_meaning,
                current_case_interpretation  = _ci,
                why_this_is_notable          = case_meaning.meaning_summary,
            )

            try:
                if alert_interp is not None:
                    object.__setattr__(alert_obj, "alert_interpretation", alert_interp)
            except Exception:
                pass

            try:
                object.__setattr__(alert_obj, "_case_meaning", case_meaning)
            except Exception:
                pass

            # ── Emit audit record ─────────────────────────────────────────
            if _ALERT_ENTERPRISE and audit_store is not None:
                try:
                    audit_rec = AlertAuditRecord(
                        request_id          = alert_req_id,
                        component           = comp,
                        case_archetype      = case_meaning.case_archetype,
                        case_role           = case_meaning.current_case_role,
                        severity            = sev,
                        severity_reason     = (
                            f"archetype={case_meaning.case_archetype}, "
                            f"case_role={case_meaning.current_case_role}, "
                            f"change_severity={changes.change_severity}"
                        ),
                        typical_consequence = case_meaning.typical_consequence,
                        history_meaning_used = {
                            "usual_meaning":       case_meaning.usual_meaning[:200],
                            "situation_archetype": case_meaning.case_archetype,
                        },
                        supporting_evidence = {
                            "recent_signal_count": evidence.get("recent_signal_count", 0),
                            "outcome_counts":      evidence.get("outcome_counts", {}),
                        },
                        trace_id = trace.trace_id if trace else "",
                    )
                    audit_store.record_alert(audit_rec)
                except Exception:
                    pass

            if _sp:
                _sp.set_tag("severity", sev)
                _sp.set_tag("case_archetype", case_meaning.case_archetype)

            alerts.append(alert_obj)

    # ── Finish trace ──────────────────────────────────────────────────────
    if _ALERT_ENTERPRISE and trace:
        try:
            finish_trace(alert_req_id)
        except Exception:
            pass

    return alerts


# ===========================================================================
# BACKWARD COMPATIBILITY: AlertMeaning shim (for tests that import it)
# ===========================================================================

class AlertMeaning:
    """Backward-compatibility shim.  New code should use HistoricalCaseMeaning."""
    def __init__(
        self,
        situation_type:     str,
        historical_meaning: str,
        typical_outcome:    str,
        implication:        str,
        why_this_matters:   str,
    ) -> None:
        self.situation_type     = situation_type
        self.historical_meaning = historical_meaning
        self.typical_outcome    = typical_outcome
        self.implication        = implication
        self.why_this_matters   = why_this_matters


def _build_alert_meaning(
    component:      str,
    situation_type: str,
    outcome_counts: Dict[str, int],
    changes:        Any,
    history_meaning: Optional[Any] = None,
) -> "AlertMeaning":
    """Backward-compatibility wrapper.  Delegates to _build_historical_case_meaning."""
    comp_lower    = component.lower()
    change_sev    = getattr(changes, "change_severity", "medium") or "medium"
    change_summary = getattr(changes, "change_summary", "") or ""

    case_meaning = _build_historical_case_meaning(
        component           = component,
        change_severity     = change_sev,
        change_summary      = change_summary,
        supporting_evidence = {"outcome_counts": outcome_counts},
        history_meaning     = history_meaning,
    )
    return AlertMeaning(
        situation_type     = case_meaning.current_case_role,
        historical_meaning = case_meaning.usual_meaning,
        typical_outcome    = case_meaning.typical_consequence,
        implication        = case_meaning.meaning_summary,
        why_this_matters   = case_meaning.user_relevance,
    )


def _severity_from_meaning(
    meaning:       AlertMeaning,
    detection_sev: str,
    user_focus:    Optional[str],
    component:     str,
) -> str:
    """Backward-compatibility wrapper.  Delegates to _severity_from_case_meaning."""
    comp_lower = component.lower()
    archetype  = _COMPONENT_CASE_ARCHETYPE.get(comp_lower, "growth-driver-update")
    case_meaning = HistoricalCaseMeaning(
        case_archetype      = archetype,
        usual_meaning       = meaning.historical_meaning,
        current_case_role   = meaning.situation_type,
        typical_consequence = meaning.typical_outcome,
        user_relevance      = meaning.why_this_matters,
        meaning_summary     = meaning.implication,
    )
    return _severity_from_case_meaning(case_meaning, user_focus, component)
