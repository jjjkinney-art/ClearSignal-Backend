"""
Thesis change detection logic.

This module provides utilities to compare two structured analyses and
determine whether the underlying investment thesis has materially
changed.  Rather than performing naive string diffs, it operates on
structured outputs (``SynthesisOutput`` instances) and applies
heuristics to detect meaningful differences in key components such
as drivers, risks, macro context and final verdict.  The result
encapsulates the presence of change, its severity, a summary of
changes, the affected components, and an impact statement.

The detection sensitivity can be tuned using a ``sensitivity``
parameter.  Lower sensitivity thresholds classify smaller changes as
more significant, while higher sensitivity thresholds suppress noise.

Example usage::

    from app.services.thesis_change_logic import detect_thesis_change
    result = detect_thesis_change(prev_synthesis, curr_synthesis, sensitivity="low")
    if result.has_changed:
        print(result.change_summary)

"""

from __future__ import annotations

import uuid as _uuid
from typing import List, Optional

from ..schemas import SynthesisOutput, ThesisChangeResult
from .learning import update_signal_effectiveness

# ── Enterprise layer ──────────────────────────────────────────────────────
try:
    from ..enterprise.observability import get_existing_trace, start_span
    from ..enterprise.audit import audit_store, AnalysisAuditRecord
    _TCL_ENTERPRISE = True
except Exception:
    _TCL_ENTERPRISE = False
    audit_store = None  # type: ignore


def _set_difference(old: List[str], new: List[str]) -> (List[str], List[str]):
    """Compute items added and removed between two lists (case-insensitive).

    Returns a tuple of (added, removed).  Comparison is case-insensitive
    and preserves original casing of items in ``new`` and ``old``.
    """
    old_lower = {x.lower(): x for x in old}
    new_lower = {x.lower(): x for x in new}
    added_keys = [new_lower[k] for k in new_lower.keys() if k not in old_lower]
    removed_keys = [old_lower[k] for k in old_lower.keys() if k not in new_lower]
    return added_keys, removed_keys


def detect_thesis_change(
    prev:        SynthesisOutput,
    curr:        SynthesisOutput,
    sensitivity: Optional[str] = None,
    request_id:  Optional[str] = None,
) -> ThesisChangeResult:
    """Detect meaningful changes between two analyses.

    Enterprise lifecycle:
        - When request_id is provided, emits a span into the existing trace.
        - The ThesisChangeResult is referenced in the parent audit record.

    Parameters
    ----------
    prev : SynthesisOutput
    curr : SynthesisOutput
    sensitivity : Optional[str]  "low" | "medium" | "high"
    request_id  : Optional[str]  Parent request_id for trace correlation.
    """
    # ── Enterprise: attach a span to the parent trace if active ──────────
    _trace = None
    if _TCL_ENTERPRISE and request_id:
        try:
            _trace = get_existing_trace(request_id)
        except Exception:
            pass

    changed_components: List[str] = []
    summary_parts: List[str] = []
    severity_score: float = 0.0
    # Helper to record changes and update severity
    def record_change(name: str, added: List[str], removed: List[str], weight: float) -> None:
        nonlocal severity_score
        changed_components.append(name)
        if added:
            summary_parts.append(f"{name.replace('_', ' ')} added: {', '.join(added)}")
        if removed:
            summary_parts.append(f"{name.replace('_', ' ')} removed: {', '.join(removed)}")
        # Weight is base weight; amplify by number of items changed
        severity_score += weight + 0.5 * len(added) + 0.25 * len(removed)

    # Keep track of all added signals for learning feedback
    added_signals: List[str] = []

    # 1. Final verdict change
    if prev.final_verdict != curr.final_verdict:
        changed_components.append("final_verdict")
        summary_parts.append(f"final verdict changed from {prev.final_verdict} to {curr.final_verdict}")
        severity_score += 3.0

    # 2. Macro overlay changes
    added, removed = _set_difference(prev.macro_overlay, curr.macro_overlay)
    if added or removed:
        record_change("macro_overlay", added, removed, weight=2.0)
        added_signals.extend(added)

    # 3. Key drivers ranked changes
    added, removed = _set_difference(prev.key_drivers_ranked, curr.key_drivers_ranked)
    if added or removed:
        record_change("key_drivers", added, removed, weight=2.0)
        added_signals.extend(added)

    # 4. Key risks ranked changes
    added, removed = _set_difference(prev.key_risks_ranked, curr.key_risks_ranked)
    if added or removed:
        record_change("key_risks", added, removed, weight=2.0)
        added_signals.extend(added)

    # 5. Key catalysts changes
    added, removed = _set_difference(prev.key_catalysts, curr.key_catalysts)
    if added or removed:
        record_change("key_catalysts", added, removed, weight=1.0)
        added_signals.extend(added)

    # 6. Bull and bear case changes can indicate sentiment shifts
    added, removed = _set_difference(prev.bull_case, curr.bull_case)
    if added or removed:
        record_change("bull_case", added, removed, weight=1.0)
        added_signals.extend(added)
    added, removed = _set_difference(prev.bear_case, curr.bear_case)
    if added or removed:
        record_change("bear_case", added, removed, weight=1.0)
        added_signals.extend(added)

    # Determine base severity category from severity_score
    # Default thresholds: low < 3, medium < 6, high >= 6
    if severity_score >= 6.0:
        base_severity = "high"
    elif severity_score >= 3.0:
        base_severity = "medium"
    elif severity_score > 0:
        base_severity = "low"
    else:
        base_severity = "low"

    # Adjust severity based on sensitivity setting
    severity = base_severity
    if sensitivity:
        s = sensitivity.lower()
        if s == "low":
            # Treat moderate changes as high and small changes as medium
            if base_severity == "medium":
                severity = "high"
            elif base_severity == "low":
                severity = "medium" if changed_components else "low"
        elif s == "high":
            # Suppress medium to low unless strong change
            if base_severity == "medium":
                severity = "low"
            elif base_severity == "high":
                severity = "medium"

    # Construct impact statement
    if not changed_components:
        impact = "No impact."
    else:
        if severity == "high":
            impact = "These changes indicate a significant shift in the investment thesis and may warrant re‑evaluation."
        elif severity == "medium":
            impact = "These changes moderately affect the thesis and should be reviewed."
        else:
            impact = "Changes are minor and do not materially alter the thesis."

    # Build a concise summary
    if summary_parts:
        change_summary = "; ".join(summary_parts)
    else:
        change_summary = "No significant changes detected."

    # Feed back added signals into the learning memory.  Only the
    # newly introduced signals are recorded, not those removed.  This
    # simple adaptation loop increases the weight of signals that
    # repeatedly contribute to thesis changes.
    if added_signals:
        try:
            update_signal_effectiveness(added_signals)
        except Exception:
            pass

    result = ThesisChangeResult(
        has_changed=bool(changed_components),
        change_severity=severity,
        change_summary=change_summary,
        changed_components=changed_components,
        impact_on_thesis=impact,
    )

    # ── Enterprise: emit span with thesis-change outcome ─────────────────
    if _TCL_ENTERPRISE and _trace is not None:
        try:
            from contextlib import contextmanager as _cm
            @_cm
            def _null():
                class _N:
                    def set_tag(self, *a, **k): pass
                yield _N()
            # Use with-less span: create, tag, finish
            from ..enterprise.observability import Span as _Span
            import time as _time
            sp = _Span(stage="thesis_change_detection",
                       request_id=request_id or "",
                       trace_id=_trace.trace_id)
            sp.set_tag("has_changed", result.has_changed)
            sp.set_tag("severity", result.change_severity)
            sp.set_tag("changed_components", result.changed_components)
            sp.finish()
            _trace.add_span(sp)
        except Exception:
            pass

    return result