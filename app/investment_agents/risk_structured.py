"""Structured risk representation and its projection back to RiskProfile
(Sprint 3B.4).

Why
---
Sprint 3B.3's `risk_fast_a` bounded four prose fields to <=2 sentences each. It
failed both gates: 0 keeps across 15 live observations (lost thresholds, lost
numeric anchors, lost mechanisms, metric substitution) at only 11.1% latency
reduction. The lesson was not that output length is the wrong lever — the
latency model is unambiguous that it is — but that *blunt compression of prose
that carries load-bearing facts destroys the facts*.

The redundancy is structural, not verbal. The same four-or-five risks are
restated up to seven times in the control output:

  * once per category prose field (debt / competitive / regulatory / concentration)
  * again as `key_risks` bullets
  * again as the `overall` paragraph
  * again inside each signal, across `signal`, `explanation` and
    `importance_reason` — three prose restatements per signal

So this sprint changes the REPRESENTATION rather than the content budget: the
model states each risk fact exactly once as a structured item, and the existing
RiskProfile contract is rebuilt from those items deterministically in Python.
Nothing downstream changes — synthesis, claim extraction, conviction, signal
ranking and integrity all keep receiving the same field names they get today.

Offline estimate
----------------
A fact-for-fact reconstruction (same figures, thresholds, entities, citations
and mechanisms) calibrated against the Sprint 3B.3 live control — whose
11438.54 ms median implies ~1225 output tokens under the fitted
`723 + 8.75 * output_tokens` relation — gives:

    control    ~1235 est tokens   (within 0.8% of the live-implied figure)
    structured  ~857 est tokens
    reduction   30.6%             (47.0% under a plain chars/4 estimate)

The estimator used charges one token per punctuation character, which
systematically OVERCHARGES the structured form (far more JSON syntax), so 30.6%
is the conservative end of the range, not the optimistic one.

Failure behaviour
-----------------
There is no partial-credit path. If the model's structured output cannot be
parsed and projected with its load-bearing content intact, the caller falls
back to the control representation and the request is recorded as a parse
failure — a half-populated RiskProfile would silently degrade the thesis, which
is precisely the failure this sprint exists to avoid.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Category -> the RiskProfile prose field it projects into. Anything outside
# this map still reaches key_risks and signals; it simply has no dedicated
# prose field, which is better than being silently dropped into an unrelated one.
CATEGORY_TO_FIELD: Dict[str, str] = {
    "debt": "debt_risk",
    "leverage": "debt_risk",
    "balance_sheet": "debt_risk",
    "competitive": "competitive_risk",
    "competition": "competitive_risk",
    "moat": "competitive_risk",
    "regulatory": "regulatory_risk",
    "regulation": "regulatory_risk",
    "legal": "regulatory_risk",
    "concentration": "concentration_risk",
    "customer_concentration": "concentration_risk",
    "supplier": "concentration_risk",
    "geographic": "concentration_risk",
}

PROSE_FIELDS = ("debt_risk", "competitive_risk", "regulatory_risk",
                "concentration_risk")

_VALID_HORIZONS = ("short_term", "medium_term", "long_term")


class RiskItem(BaseModel):
    """One material risk, stated once.

    Only ``mechanism`` is required: a risk with no transmission mechanism is an
    assertion rather than analysis, and Sprint 3B.3 established lost mechanisms
    as a reject condition. Every other field is optional so that a genuinely
    unquantifiable risk (a pending legal outcome, say) is still expressible
    without inviting the model to invent a threshold for it.
    """

    category: str = Field(default="other")
    mechanism: str = Field(default="")
    metric: str = Field(default="")
    current_value: str = Field(default="")
    warning_threshold: str = Field(default="")
    bear_threshold: str = Field(default="")
    entities: List[str] = Field(default_factory=list)
    # Models return citation markers as ints or as strings ("[2]", "2").
    citations: List[Union[int, str]] = Field(default_factory=list)
    impact: float = Field(default=0.5, ge=0.0, le=1.0)
    horizon: str = Field(default="medium_term")


class RiskStructured(BaseModel):
    """The `risk_struct_a` model output contract."""

    overall: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_items: List[RiskItem] = Field(default_factory=list)


def _citation_markers(item: RiskItem) -> str:
    """Render citations as the ``[n]`` markers the rest of the pipeline reads.

    Provenance is a stated reject condition, and the control prompt instructs
    the model to cite evidence numbers inline, so the projected prose has to
    carry the same marker shape rather than a bare list.
    """
    out: List[str] = []
    for c in item.citations:
        text = str(c).strip().strip("[]")
        if text and text not in out:
            out.append(text)
    return "".join(f"[{c}]" for c in out)


def render_item(item: RiskItem) -> str:
    """One risk item as prose, preserving every load-bearing element.

    Order is deliberate: mechanism first (the causal chain), then the metric
    with its current value and thresholds, then named entities, then citation
    markers. Downstream claim extraction reads these strings for figures, so
    the numbers must survive verbatim rather than being summarised.
    """
    parts: List[str] = []
    if item.mechanism:
        parts.append(item.mechanism.rstrip(". ") + ".")

    if item.metric:
        metric_bits = [item.metric]
        if item.current_value:
            metric_bits.append(f"currently {item.current_value}")
        thresholds: List[str] = []
        if item.warning_threshold:
            thresholds.append(f"warning at {item.warning_threshold}")
        if item.bear_threshold:
            thresholds.append(f"bear case at {item.bear_threshold}")
        line = " ".join(metric_bits)
        if thresholds:
            line += "; " + ", ".join(thresholds)
        parts.append(line.rstrip(". ") + ".")

    if item.entities:
        parts.append("Exposure: " + ", ".join(item.entities) + ".")

    markers = _citation_markers(item)
    text = " ".join(p for p in parts if p.strip())
    if markers:
        text = f"{text} {markers}".strip()
    return text.strip()


def _key_risk_line(item: RiskItem, ticker: str) -> str:
    """A `key_risks` bullet in the shape the live artifacts already use.

    Real control output writes "MSFT-specific: <risk>", and the comparator's
    company-specificity check looks for the ticker, so the projection keeps
    that prefix rather than inventing a new format.
    """
    head = item.mechanism.rstrip(". ") if item.mechanism else item.metric
    if item.metric and item.warning_threshold:
        head = f"{head} ({item.metric} warning {item.warning_threshold})"
    return f"{ticker}-specific: {head}".strip()


def project_to_risk_profile(structured: RiskStructured, *, ticker: str,
                            risk_profile_cls: Any,
                            signal_cls: Any) -> Any:
    """Rebuild the production RiskProfile from structured items.

    The classes are injected rather than imported so this module stays free of
    a circular dependency on app.schemas and so the projection can be tested
    against the real schema without importing the agent.
    """
    buckets: Dict[str, List[str]] = {f: [] for f in PROSE_FIELDS}
    key_risks: List[str] = []

    for item in structured.risk_items:
        rendered = render_item(item)
        if not rendered:
            continue
        field = CATEGORY_TO_FIELD.get((item.category or "").strip().lower())
        if field:
            buckets[field].append(rendered)
        key_risks.append(_key_risk_line(item, ticker))

    # Signals are ordered by the model's own impact score so the ranker sees
    # the same priority the model assigned. Three matches the control prompt's
    # "2-3 risk signals" instruction, so signal volume does not change.
    ranked = sorted(structured.risk_items, key=lambda i: i.impact, reverse=True)
    signals = []
    for item in ranked[:3]:
        rendered = render_item(item)
        if not rendered:
            continue
        horizon = item.horizon if item.horizon in _VALID_HORIZONS else "medium_term"
        signals.append(signal_cls(
            signal=rendered,
            explanation=item.mechanism,
            impact_score=item.impact,
            confidence=structured.confidence,
            signal_type="risk",
            time_horizon=horizon,
            direction="bearish",          # risks are bearish by definition
            source_agent="risk",
            importance_reason=(
                f"{item.metric} is the metric most directly threatened"
                if item.metric else "Named as a load-bearing downside mechanism"
            ),
        ))

    return risk_profile_cls(
        debt_risk=" ".join(buckets["debt_risk"]),
        competitive_risk=" ".join(buckets["competitive_risk"]),
        regulatory_risk=" ".join(buckets["regulatory_risk"]),
        concentration_risk=" ".join(buckets["concentration_risk"]),
        key_risks=key_risks,
        overall=structured.overall,
        confidence=structured.confidence,
        signals=signals,
    )


def projection_is_viable(structured: Optional[RiskStructured]) -> bool:
    """Whether a parsed structured output is usable at all.

    Fails closed on the two shapes that would silently produce a hollow
    RiskProfile: no items, or items with no mechanism text. An empty
    projection would read downstream as "this company has no risks", which is
    a far worse outcome than serving the control representation.
    """
    if structured is None:
        return False
    items = [i for i in structured.risk_items if (i.mechanism or "").strip()]
    if not items:
        return False
    return bool((structured.overall or "").strip())
