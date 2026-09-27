"""Bounded prompt context for explicit Intelligence profile settings.

This module accepts only the server-owned enum values from the account profile.
It never reads conversations, messages, holdings, analyses, or legacy memory.
The rendered prompt block contains fixed application text only: no user-authored
or database-authored prose can cross this boundary.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .research_personalization import (
    ANALYSIS_EMPHASES,
    EVIDENCE_STYLES,
    PROFILE_ORIGIN,
    RESPONSE_DEPTHS,
    TIME_HORIZONS,
)


PROFILE_CONTEXT_VERSION = 1

_DEPTH_DIRECTIVES = {
    "concise": (
        "Keep the direct answer and conclusion compact; use the shortest complete "
        "explanation permitted by the section contract."
    ),
    "balanced": (
        "Use the default section depth and keep detail proportional to materiality."
    ),
    "deep": (
        "Use the fullest analytical depth permitted by the section contract, while "
        "avoiding repetition."
    ),
}
_HORIZON_DIRECTIVES = {
    "near_term": (
        "Lead with the next one to four quarters and near-term catalysts, while still "
        "stating material longer-term implications."
    ),
    "mixed": (
        "Balance near-term catalysts with multi-year business durability."
    ),
    "multi_year": (
        "Emphasize multi-year durability, compounding, and structural risks, while "
        "still naming material near-term catalysts."
    ),
}
_EMPHASIS_DIRECTIVES = {
    "downside_first": (
        "Order otherwise equivalent points with downside mechanisms before upside. "
        "Do not change confidence, omit upside, or overstate risk."
    ),
    "balanced": (
        "Present material upside and downside symmetrically."
    ),
    "opportunity_first": (
        "Order otherwise equivalent points with opportunity mechanisms before "
        "downside. Do not change confidence, omit risks, or overstate upside."
    ),
}
_EVIDENCE_DIRECTIVES = {
    "primary_sources": (
        "When citing the evidence already provided, foreground primary-source support."
    ),
    "balanced_sources": (
        "When citing the evidence already provided, explain primary-source facts "
        "alongside reputable contextual sources."
    ),
}


def build_applied_profile(profile: Mapping[str, Any] | None) -> Optional[dict]:
    """Return a validated, prompt-safe profile or None.

    Opt-in, persistence, explicit origin, and every enum must pass. Unknown or
    malformed values fail closed so the unpersonalized prompt remains unchanged.
    """
    if not isinstance(profile, Mapping):
        return None
    if profile.get("persisted") is not True or profile.get("enabled") is not True:
        return None
    if profile.get("origin") != PROFILE_ORIGIN:
        return None

    response_depth = profile.get("response_depth")
    time_horizon = profile.get("time_horizon")
    analysis_emphasis = profile.get("analysis_emphasis")
    evidence_style = profile.get("evidence_style")
    if response_depth not in RESPONSE_DEPTHS:
        return None
    if time_horizon not in TIME_HORIZONS:
        return None
    if analysis_emphasis not in ANALYSIS_EMPHASES:
        return None
    if evidence_style not in EVIDENCE_STYLES:
        return None

    return {
        "profile_version": PROFILE_CONTEXT_VERSION,
        "origin": PROFILE_ORIGIN,
        "response_depth": response_depth,
        "time_horizon": time_horizon,
        "analysis_emphasis": analysis_emphasis,
        "evidence_style": evidence_style,
    }


def format_profile_for_prompt(profile: Mapping[str, Any] | None) -> str:
    """Render fixed directives from a validated profile."""
    if not isinstance(profile, Mapping):
        return ""
    expected = {
        "persisted": True,
        "enabled": True,
        "origin": profile.get("origin"),
        "response_depth": profile.get("response_depth"),
        "time_horizon": profile.get("time_horizon"),
        "analysis_emphasis": profile.get("analysis_emphasis"),
        "evidence_style": profile.get("evidence_style"),
    }
    safe = build_applied_profile(expected)
    if safe is None or profile.get("profile_version") != PROFILE_CONTEXT_VERSION:
        return ""

    return (
        "USER-SELECTED INTELLIGENCE PRESENTATION PREFERENCES "
        "(lowest priority):\n"
        "- These preferences may change ordering, emphasis, and level of detail only.\n"
        "- Never change evidence retrieval, source inclusion, factual conclusions, "
        "confidence, uncertainty, safety rules, or the required JSON/section contract.\n"
        f"- Depth: {_DEPTH_DIRECTIVES[safe['response_depth']]}\n"
        f"- Horizon: {_HORIZON_DIRECTIVES[safe['time_horizon']]}\n"
        f"- Emphasis: {_EMPHASIS_DIRECTIVES[safe['analysis_emphasis']]}\n"
        f"- Evidence presentation: {_EVIDENCE_DIRECTIVES[safe['evidence_style']]} "
        "Do not add, remove, or reweight evidence.\n"
    )


def response_metadata(profile: Mapping[str, Any] | None) -> dict:
    if not format_profile_for_prompt(profile):
        return {"applied": False}
    return {
        "applied": True,
        "profile_version": PROFILE_CONTEXT_VERSION,
        "response_depth": profile["response_depth"],
        "time_horizon": profile["time_horizon"],
        "analysis_emphasis": profile["analysis_emphasis"],
        "evidence_style": profile["evidence_style"],
    }
