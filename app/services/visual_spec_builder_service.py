"""
Visual Spec Builder + Validation — Phase 19 · Slice 3.

The visual specification framework.  Answers, per visual request:

  "What visual should exist, and is it safe to generate?"

This module is the gate every visual passes through before any rendering,
SVG generation, or AI image generation (later slices).  It produces a typed
visual specification, decides the rendering tier, and enforces the
explainability gate + no-advice boundary.

Everything here is a pure function — no DB access, no session, no writes.
The spec builder transforms upstream data into a specification dict; it
never modifies upstream data and never creates intelligence.

Explainability gate
-------------------
Every visual must answer three questions:
  1. what_am_i_looking_at — what the visual shows
  2. why_does_it_matter — why it is relevant
  3. supporting_evidence — at least one upstream evidence reference

If any field is empty or missing, the visual is blocked
(explanation_valid=False, blocked_reason set).

Visual Priority Framework
-------------------------
The spec builder decides the rendering tier per visual type:
  json     — frontend-rendered structured data (charts, distributions, timelines)
  svg      — server-side rendered graphs/trees/networks
  ai_image — AI-generated explanatory visuals (question-driven, ecosystem maps)

SP-19 invariants
----------------
  SP-19a: no advisory language.  All text is templated and label-validated.
  SP-19b: visualization does not change truth.  Specs are read-only renderings.
  SP-19c: writes nothing — the spec builder is pure computation.
  SP-19d: no upstream feedback.
  No buy / sell / sizing / trading language appears in any template.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# No-advice vocabulary (SP-19a).  This is the safety allowlist — the words a
# visual label may NEVER contain.  The Slice 19.3 AST test exempts this single
# constant from its banned-phrase scan; it is the enforcement vocabulary, not
# a violation.
# ---------------------------------------------------------------------------

_BANNED_PHRASES: Tuple[str, ...] = (
    "buy", "sell",
    "overweight", "underweight", "recommend",
    "target price", "position size",
    "take a position", "enter a trade", "exit a trade",
    "place an order", "execute",
    "short", "long position",
    "go long", "go short",
    "open a position", "close a position",
)


# ---------------------------------------------------------------------------
# Visual Priority Framework — tier assignments per visual type
# ---------------------------------------------------------------------------

# Tier 1 — Structured JSON (frontend renders).
_JSON_TIER_VISUALS = frozenset({
    "price_chart", "performance_chart", "volatility_overlay",
    "forecast_distribution", "confidence_band", "forecast_evolution",
    "exposure_map", "concentration_map",
    "attention_timeline", "change_timeline", "resume_timeline",
})

# Tier 2 — Server-side SVG (graphs/trees/networks/timelines).
_SVG_TIER_VISUALS = frozenset({
    "outcome_tree", "scenario_tree",
    "transmission_path", "impact_map",
    "similarity_network", "analog_cluster", "relationship_graph",
    "dependency_map",
    "precedent_map", "evidence_timeline",
    "what_changed_map", "thesis_evolution",
    "scenario_exposure",
})

# Tier 3 — AI-generated explanatory visuals.
_AI_TIER_VISUALS = frozenset({
    "ecosystem_map", "supply_chain_map",
    "ai_change_explanation", "ai_risk_map", "ai_commonality_diagram",
})


# Category membership (used by the per-category builders).
_MARKET_VISUALS = frozenset({
    "price_chart", "performance_chart", "volatility_overlay", "evidence_timeline",
})
_FORECAST_VISUALS = frozenset({
    "forecast_distribution", "outcome_tree", "confidence_band", "forecast_evolution",
})
_SCENARIO_VISUALS = frozenset({
    "what_changed_map", "transmission_path", "scenario_tree", "impact_map",
})
_SIMILARITY_VISUALS = frozenset({
    "similarity_network", "analog_cluster", "precedent_map", "relationship_graph",
})
_PORTFOLIO_VISUALS = frozenset({
    "exposure_map", "concentration_map", "dependency_map", "scenario_exposure",
})
_PERSONAL_VISUALS = frozenset({
    "attention_timeline", "change_timeline", "resume_timeline", "thesis_evolution",
})


# ---------------------------------------------------------------------------
# Explainability templates — deterministic, no LLM prose
# ---------------------------------------------------------------------------

_TEMPLATES: Dict[str, Dict[str, str]] = {
    # Market
    "price_chart": {
        "what": "Price history for {entity_key} with annotated analysis events.",
        "why":  "Recent price movement for {entity_key} is contextualized by tracked events.",
    },
    "performance_chart": {
        "what": "Performance of {entity_key} relative to a benchmark.",
        "why":  "Shows how {entity_key} has performed over the selected window.",
    },
    "volatility_overlay": {
        "what": "Price of {entity_key} with volatility bands.",
        "why":  "Volatility context for {entity_key} reflects current scenario plausibility.",
    },
    "evidence_timeline": {
        "what": "Chronological evidence entries for {entity_key}.",
        "why":  "Shows when analysis evidence for {entity_key} was recorded.",
    },
    # Forecast
    "forecast_distribution": {
        "what": "Forecast probability distribution across scenarios for {entity_key}.",
        "why":  "Forecast for {entity_key} was updated on {as_of_date}.",
    },
    "outcome_tree": {
        "what": "Branching forecast outcomes for {entity_key}.",
        "why":  "Conditional forecast paths for {entity_key} reflect the latest assessment.",
    },
    "confidence_band": {
        "what": "Forecast confidence envelope for {entity_key} over time.",
        "why":  "Confidence width for {entity_key} reflects calibration history.",
    },
    "forecast_evolution": {
        "what": "How the forecast for {entity_key} changed over time.",
        "why":  "Forecast for {entity_key} changed across recent assessments.",
    },
    # Scenario
    "what_changed_map": {
        "what": "Before-and-after comparison of scenario state for {entity_key}.",
        "why":  "Scenario conditions for {entity_key} changed since the last assessment.",
    },
    "transmission_path": {
        "what": "Transmission path from trigger to impact for {entity_key}.",
        "why":  "Shows how a scenario propagates through to {entity_key}.",
    },
    "scenario_tree": {
        "what": "Active scenarios for {entity_key} with plausibility on each branch.",
        "why":  "Scenario plausibility for {entity_key} reflects current conditions.",
    },
    "impact_map": {
        "what": "Impact propagation across entities related to {entity_key}.",
        "why":  "Shows which entities a scenario affecting {entity_key} touches.",
    },
    # Similarity
    "similarity_network": {
        "what": "Similarity relationships for {entity_key} based on {edge_count} connections.",
        "why":  "Maps entities related to {entity_key} by shared characteristics.",
    },
    "analog_cluster": {
        "what": "Clustered analogs for {entity_key} grouped by similarity.",
        "why":  "Shows historical analogs grouped around {entity_key}.",
    },
    "precedent_map": {
        "what": "Historical precedent timeline for {entity_key}.",
        "why":  "Maps prior comparable situations for {entity_key}.",
    },
    "relationship_graph": {
        "what": "Multi-dimensional relationship graph for {entity_key}.",
        "why":  "Shows weighted relationships connecting {entity_key} to related entities.",
    },
    # Portfolio
    "exposure_map": {
        "what": "Portfolio exposure broken down by dimension.",
        "why":  "Shows how portfolio weight is distributed across categories.",
    },
    "concentration_map": {
        "what": "Portfolio concentration heat map.",
        "why":  "Highlights where portfolio weight is concentrated.",
    },
    "dependency_map": {
        "what": "Relationships between portfolio holdings.",
        "why":  "Shows which holdings are related by shared characteristics.",
    },
    "scenario_exposure": {
        "what": "Portfolio sensitivity to active scenarios.",
        "why":  "Maps how scenarios intersect with portfolio holdings.",
    },
    # Personal experience
    "attention_timeline": {
        "what": "Timeline of what demanded attention.",
        "why":  "Shows when items rose to attention over time.",
    },
    "change_timeline": {
        "what": "Timeline of what changed since your last visit.",
        "why":  "Shows recent changes ordered by recency.",
    },
    "resume_timeline": {
        "what": "Timeline of paused research that has changed.",
        "why":  "Shows previously-researched items that have new developments.",
    },
    "thesis_evolution": {
        "what": "How the thesis for {entity_key} evolved over time.",
        "why":  "Shows thesis change for {entity_key} across snapshots.",
    },
    # AI tier
    "ecosystem_map": {
        "what": "Ecosystem map showing how {entity_key} connects to related entities.",
        "why":  "Illustrates why {entity_key} matters within its ecosystem.",
    },
    "supply_chain_map": {
        "what": "Supply-chain map for {entity_key}.",
        "why":  "Shows the supply relationships around {entity_key}.",
    },
    "ai_change_explanation": {
        "what": "Visual explanation of how {entity_key} has changed.",
        "why":  "Illustrates the change in {entity_key} over time.",
    },
    "ai_risk_map": {
        "what": "Risk map combining scenario and portfolio views.",
        "why":  "Illustrates how scenario risk intersects holdings.",
    },
    "ai_commonality_diagram": {
        "what": "Diagram of shared characteristics across entities.",
        "why":  "Shows what the selected entities have in common.",
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    def __missing__(self, key):  # noqa: D401
        return ""


def _fmt(template: str, params: Dict[str, Any]) -> str:
    if not template:
        return ""
    try:
        return template.format_map(_SafeDict(params))
    except Exception:
        return template


def _default_title(visual_type: str, entity_key: str) -> str:
    label = visual_type.replace("_", " ").title()
    if entity_key:
        return f"{entity_key} - {label}"
    return label


# ---------------------------------------------------------------------------
# Rendering tier selection
# ---------------------------------------------------------------------------

def select_rendering_tier(visual_type: str) -> str:
    """Return the rendering tier for a visual type.

    Returns "json", "svg", or "ai_image".  Unknown types default to "json"
    (the most conservative tier — no AI generation, no server render).
    """
    if visual_type in _AI_TIER_VISUALS:
        return "ai_image"
    if visual_type in _SVG_TIER_VISUALS:
        return "svg"
    return "json"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_visual_explainability(explanation: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate that an explanation answers all three required questions.

    Returns (ok, reason).
    """
    for field in ("what_am_i_looking_at", "why_does_it_matter"):
        val = explanation.get(field, "")
        if not val or not str(val).strip():
            return False, f"missing or empty: {field}"
    evidence = explanation.get("supporting_evidence", [])
    if not evidence:
        return False, "missing or empty: supporting_evidence"
    return True, ""


def validate_visual_labels(labels: Dict[str, Any]) -> Tuple[bool, str]:
    """Scan visual label text for advisory language (SP-19a).

    Returns (ok, reason).  Returns (False, ...) when any banned phrase is
    found in any label value.
    """
    for key, text in labels.items():
        if not text:
            continue
        low = str(text).lower()
        for phrase in _BANNED_PHRASES:
            if phrase in low:
                return False, f"banned phrase '{phrase}' in {key}"
    return True, ""


def validate_visual_spec(spec: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate a complete visual specification.

    Checks the explainability gate (3 fields) and the no-advice boundary
    (label scan).  Returns (ok, reason).
    """
    explanation = spec.get("explanation", {})
    ok, reason = validate_visual_explainability(explanation)
    if not ok:
        return False, reason

    labels = {
        "title":                spec.get("title", ""),
        "what_am_i_looking_at": explanation.get("what_am_i_looking_at", ""),
        "why_does_it_matter":   explanation.get("why_does_it_matter", ""),
    }
    ok, reason = validate_visual_labels(labels)
    if not ok:
        return False, reason

    return True, ""


# ---------------------------------------------------------------------------
# Core spec builder
# ---------------------------------------------------------------------------

def build_visual_spec(
    *,
    visual_type: str,
    entity_key: str = "",
    data: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
    title: str = "",
    what_am_i_looking_at: str = "",
    why_does_it_matter: str = "",
    template_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build and validate a single visual specification.

    Pipeline:
      1. select rendering tier for the visual type
      2. populate explanation (from explicit text, else templates)
      3. validate explainability + labels
      4. set explanation_valid + blocked_reason

    Returns a spec dict with: visual_type, rendering_tier, entity_key, title,
    data, explanation, evidence_refs, explanation_valid, blocked_reason.

    A spec that fails validation is returned with explanation_valid=False
    and blocked_reason populated — it is never raised as an error.
    """
    data = dict(data or {})
    evidence_refs = list(evidence_refs or [])
    params = dict(template_params or {})
    params.setdefault("entity_key", entity_key)

    tier = select_rendering_tier(visual_type)
    template = _TEMPLATES.get(visual_type, {})

    what = what_am_i_looking_at or _fmt(template.get("what", ""), params)
    why = why_does_it_matter or _fmt(template.get("why", ""), params)
    if not title:
        title = _default_title(visual_type, entity_key)

    explanation = {
        "what_am_i_looking_at": what,
        "why_does_it_matter":   why,
        "supporting_evidence":  evidence_refs,
    }

    spec: Dict[str, Any] = {
        "visual_type":       visual_type,
        "rendering_tier":    tier,
        "entity_key":        entity_key,
        "title":             title,
        "data":              data,
        "explanation":       explanation,
        "evidence_refs":     evidence_refs,
        "explanation_valid": False,
        "blocked_reason":    "",
    }

    ok, reason = validate_visual_spec(spec)
    spec["explanation_valid"] = ok
    spec["blocked_reason"] = "" if ok else reason
    return spec


# ---------------------------------------------------------------------------
# Per-category builders
# ---------------------------------------------------------------------------

def _build_category(
    category_set: frozenset,
    category_name: str,
    *,
    visual_type: str,
    entity_key: str,
    data: Optional[Dict[str, Any]],
    evidence_refs: Optional[List[str]],
    template_params: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if visual_type not in category_set:
        spec = build_visual_spec(
            visual_type=visual_type, entity_key=entity_key,
            data=data, evidence_refs=evidence_refs,
            template_params=template_params,
        )
        spec["explanation_valid"] = False
        spec["blocked_reason"] = (
            f"visual_type '{visual_type}' is not valid for {category_name}"
        )
        return spec
    return build_visual_spec(
        visual_type=visual_type, entity_key=entity_key,
        data=data, evidence_refs=evidence_refs,
        template_params=template_params,
    )


def build_market_visual_spec(
    *,
    visual_type: str,
    entity_key: str = "",
    data: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
    template_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a market visual spec (price chart, performance, volatility, evidence timeline)."""
    return _build_category(
        _MARKET_VISUALS, "market visuals",
        visual_type=visual_type, entity_key=entity_key,
        data=data, evidence_refs=evidence_refs, template_params=template_params,
    )


def build_forecast_visual_spec(
    *,
    visual_type: str,
    entity_key: str = "",
    data: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
    template_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a forecast visual spec (distribution, outcome tree, confidence band, evolution)."""
    return _build_category(
        _FORECAST_VISUALS, "forecast visuals",
        visual_type=visual_type, entity_key=entity_key,
        data=data, evidence_refs=evidence_refs, template_params=template_params,
    )


def build_scenario_visual_spec(
    *,
    visual_type: str,
    entity_key: str = "",
    data: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
    template_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a scenario visual spec (what-changed, transmission, tree, impact map)."""
    return _build_category(
        _SCENARIO_VISUALS, "scenario visuals",
        visual_type=visual_type, entity_key=entity_key,
        data=data, evidence_refs=evidence_refs, template_params=template_params,
    )


def build_similarity_visual_spec(
    *,
    visual_type: str,
    entity_key: str = "",
    data: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
    template_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a similarity visual spec (network, cluster, precedent, relationship graph)."""
    return _build_category(
        _SIMILARITY_VISUALS, "similarity visuals",
        visual_type=visual_type, entity_key=entity_key,
        data=data, evidence_refs=evidence_refs, template_params=template_params,
    )


def build_portfolio_visual_spec(
    *,
    visual_type: str,
    entity_key: str = "",
    data: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
    template_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a portfolio visual spec (exposure, concentration, dependency, scenario exposure)."""
    return _build_category(
        _PORTFOLIO_VISUALS, "portfolio visuals",
        visual_type=visual_type, entity_key=entity_key,
        data=data, evidence_refs=evidence_refs, template_params=template_params,
    )


def build_personal_visual_spec(
    *,
    visual_type: str,
    entity_key: str = "",
    data: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
    template_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a personal-experience visual spec (attention, change, resume timelines, thesis evolution)."""
    return _build_category(
        _PERSONAL_VISUALS, "personal experience visuals",
        visual_type=visual_type, entity_key=entity_key,
        data=data, evidence_refs=evidence_refs, template_params=template_params,
    )
