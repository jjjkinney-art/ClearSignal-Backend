"""
AI Visual Generation Service — Phase 19 · Slice 9.

Generates AI visual *generation requests* and audit records.  AI visuals are
derived from structured intelligence — NEVER from raw user prompts.

Core principle
--------------
The user's question selects WHICH intelligence to visualize.  The prompt is
constructed from structured intelligence data (entity names, evidence,
scenario/similarity/portfolio/personal-experience structure) — the user's raw
text is never forwarded into the prompt.

Prompt privacy
--------------
The raw prompt is never stored.  Only its SHA-256 hash (prompt_hash) is
persisted to ai_visual_generation_log, alongside the visual_type and the
validation result.

Functions
---------
  classify_visual_question   — map a question to a visual type + sources (pure)
  build_visual_prompt        — structured prompt from data, no user text (pure)
  build_visual_generation_spec — full generation spec + prompt_hash (pure)
  validate_generated_visual  — post-generation safety validation (pure)
  build_visual_fallback      — deterministic fallback spec (pure)
  generate_visual_request    — orchestrate + audit-log (async)

AI visual categories
--------------------
  ecosystem_map, supply_chain_map, scenario_explainer,
  thesis_explainer, change_explainer

Failure path
------------
If validation fails (explainability, evidence, labels, or advisory-language),
no image is surfaced — a deterministic fallback spec is returned instead.

Flag gate
---------
generate_visual_request is gated on visual_ai_enabled.  When disabled (the
default) it returns a deterministic fallback — AI generation never runs.

SP-19 invariants
----------------
  SP-19a: no advisory language (label + post-generation scans).
  SP-19b: visualization does not change truth.
  SP-19c: writes only ai_visual_generation_log (audit, prompt_hash only).
  SP-19d: no upstream feedback.
  SP-19f: AI output undergoes post-generation safety validation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.services.visual_spec_builder_service import (
    validate_visual_spec,
    validate_visual_explainability,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# No-advice vocabulary (SP-19a / SP-19f).  Enforcement allowlist — exempted
# from the Slice 19.9 AST banned-phrase scan.
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
# AI visual categories + intelligence sources
# ---------------------------------------------------------------------------

_AI_VISUALS = frozenset({
    "ecosystem_map", "supply_chain_map",
    "scenario_explainer", "thesis_explainer", "change_explainer",
})

_SOURCES: Dict[str, List[str]] = {
    "ecosystem_map":      ["similarity", "portfolio"],
    "supply_chain_map":   ["similarity", "memory"],
    "scenario_explainer": ["scenario"],
    "thesis_explainer":   ["memory", "forecast"],
    "change_explainer":   ["personal_experience", "memory"],
}

# Question keyword → visual type, evaluated in priority order.
_QUESTION_PATTERNS: List[Tuple[str, Tuple[str, ...]]] = [
    ("supply_chain_map",   ("supply chain", "supply-chain", "supplier")),
    ("scenario_explainer", ("scenario", "what if", "what happens if", "what would happen")),
    ("change_explainer",   ("what changed", "changed", "since my last", "change since")),
    ("thesis_explainer",   ("thesis", "conviction")),
    ("ecosystem_map",      ("ecosystem", "why does", "why is", "matter", "connect")),
]

_AI_TEMPLATES: Dict[str, Dict[str, str]] = {
    "ecosystem_map": {
        "what": "Ecosystem map showing how {entity_key} connects to related entities.",
        "why":  "Illustrates how {entity_key} fits within its ecosystem.",
    },
    "supply_chain_map": {
        "what": "Supply-chain map for {entity_key}.",
        "why":  "Shows the supply relationships around {entity_key}.",
    },
    "scenario_explainer": {
        "what": "Visual explanation of an active scenario for {entity_key}.",
        "why":  "Illustrates how the scenario for {entity_key} unfolds.",
    },
    "thesis_explainer": {
        "what": "Visual explanation of the thesis for {entity_key}.",
        "why":  "Illustrates the thesis structure for {entity_key}.",
    },
    "change_explainer": {
        "what": "Visual explanation of how {entity_key} has changed.",
        "why":  "Illustrates the change in {entity_key} over time.",
    },
}

_DEFAULT_STYLE = "clean infographic, labeled nodes, no decorative elements"

_DEFAULT_CONSTRAINTS: Tuple[str, ...] = (
    "label all data sources",
    "no text implying a transaction",
    "no arrows implying direction of action",
    "neutral, descriptive labels only",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    def __missing__(self, key):  # noqa: D401
        return ""


def _fmt(template: str, entity_key: str) -> str:
    if not template:
        return ""
    try:
        return template.format_map(_SafeDict({"entity_key": entity_key}))
    except Exception:
        return template


def _title(visual_type: str, entity_key: str) -> str:
    label = visual_type.replace("_", " ").title()
    return f"{entity_key} - {label}" if entity_key else label


def _hash_prompt(prompt: Dict[str, Any]) -> str:
    canonical = json.dumps(prompt, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scan_banned(*texts: Any) -> List[str]:
    found: List[str] = []
    for t in texts:
        low = str(t or "").lower()
        for phrase in _BANNED_PHRASES:
            if phrase in low and phrase not in found:
                found.append(phrase)
    return found


def _ai_enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "visual_ai_enabled", False))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Question classification (pure)
# ---------------------------------------------------------------------------

def classify_visual_question(
    question: str,
    *,
    entity_key: str = "",
) -> Dict[str, Any]:
    """Map a user question to an AI visual type + intelligence sources.

    The question is used ONLY to select the visual type and the data sources.
    It is never forwarded into the generated prompt.

    Returns {visual_type, entity_key, intelligence_sources, recognized}.
    recognized=False (and visual_type="") when no pattern matches.
    """
    q = (question or "").lower()
    for vtype, keywords in _QUESTION_PATTERNS:
        if any(k in q for k in keywords):
            return {
                "visual_type":          vtype,
                "entity_key":           entity_key,
                "intelligence_sources": list(_SOURCES.get(vtype, [])),
                "recognized":           True,
            }
    return {
        "visual_type":          "",
        "entity_key":           entity_key,
        "intelligence_sources": [],
        "recognized":           False,
    }


# ---------------------------------------------------------------------------
# Prompt construction (pure) — structured data only, never user text
# ---------------------------------------------------------------------------

def build_visual_prompt(
    *,
    visual_type: str,
    entity_key: str = "",
    structured_data: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
    style: Optional[str] = None,
    constraints: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Construct a structured image-generation prompt.

    The prompt is built ONLY from the entity name, structured intelligence
    data, and evidence references.  It carries no raw user text and no
    free-form question.
    """
    return {
        "prompt_type":   visual_type,
        "entity":        entity_key,
        "data":          dict(structured_data or {}),
        "evidence_refs": list(evidence_refs or []),
        "style":         style or _DEFAULT_STYLE,
        "constraints":   list(constraints or _DEFAULT_CONSTRAINTS),
    }


# ---------------------------------------------------------------------------
# Generation spec (pure)
# ---------------------------------------------------------------------------

def build_visual_generation_spec(
    *,
    visual_type: str,
    entity_key: str = "",
    structured_data: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
    what_am_i_looking_at: str = "",
    why_does_it_matter: str = "",
    style: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an AI visual generation spec (ai_image tier).

    The spec carries the prompt_hash — never the prompt text.  A spec for an
    unknown visual type, or one failing validation, is returned blocked.
    """
    structured_data = dict(structured_data or {})
    evidence_refs = list(evidence_refs or [])
    title = _title(visual_type, entity_key)

    if visual_type not in _AI_VISUALS:
        return {
            "visual_type":       visual_type,
            "rendering_tier":    "ai_image",
            "entity_key":        entity_key,
            "title":             title,
            "prompt_hash":       "",
            "explanation":       {
                "what_am_i_looking_at": "",
                "why_does_it_matter":   "",
                "supporting_evidence":  evidence_refs,
            },
            "evidence_refs":     evidence_refs,
            "constraints":       list(_DEFAULT_CONSTRAINTS),
            "explanation_valid": False,
            "blocked_reason":    f"'{visual_type}' is not an AI visual type",
        }

    template = _AI_TEMPLATES.get(visual_type, {})
    what = what_am_i_looking_at or _fmt(template.get("what", ""), entity_key)
    why = why_does_it_matter or _fmt(template.get("why", ""), entity_key)

    prompt = build_visual_prompt(
        visual_type=visual_type, entity_key=entity_key,
        structured_data=structured_data, evidence_refs=evidence_refs,
        style=style,
    )
    prompt_hash = _hash_prompt(prompt)

    explanation = {
        "what_am_i_looking_at": what,
        "why_does_it_matter":   why,
        "supporting_evidence":  evidence_refs,
    }
    spec: Dict[str, Any] = {
        "visual_type":       visual_type,
        "rendering_tier":    "ai_image",
        "entity_key":        entity_key,
        "title":             title,
        "prompt_hash":       prompt_hash,
        "explanation":       explanation,
        "evidence_refs":     evidence_refs,
        "constraints":       prompt["constraints"],
        "explanation_valid": False,
        "blocked_reason":    "",
    }
    ok, reason = validate_visual_spec({"title": title, "explanation": explanation})
    spec["explanation_valid"] = ok
    spec["blocked_reason"] = "" if ok else reason
    return spec


# ---------------------------------------------------------------------------
# Post-generation validation (pure)
# ---------------------------------------------------------------------------

def validate_generated_visual(
    generated: Dict[str, Any],
) -> Tuple[bool, str, List[str]]:
    """Validate a generated visual's metadata + OCR'd text content.

    Checks: explainability (3 fields + evidence), then advisory-language scan
    across title, explanation text, and any post-generation text_content
    (simulating an OCR pass over the rendered image).

    Returns (ok, reason, banned_phrases_found).
    """
    explanation = generated.get("explanation", {})
    ok, reason = validate_visual_explainability(explanation)
    if not ok:
        return False, reason, []

    found = _scan_banned(
        generated.get("title", ""),
        explanation.get("what_am_i_looking_at", ""),
        explanation.get("why_does_it_matter", ""),
        generated.get("text_content", ""),
    )
    if found:
        return False, f"advisory language detected: {found[0]}", found
    return True, "", []


# ---------------------------------------------------------------------------
# Deterministic fallback (pure)
# ---------------------------------------------------------------------------

def build_visual_fallback(
    *,
    visual_type: str,
    entity_key: str = "",
    evidence_refs: Optional[List[str]] = None,
    reason: str = "",
    what_am_i_looking_at: str = "",
    why_does_it_matter: str = "",
) -> Dict[str, Any]:
    """Build a deterministic fallback spec (json tier, no image).

    Used whenever AI generation is disabled, fails, or is blocked.  Carries
    the same explanation + evidence, downgraded to a deterministic rendering.
    """
    evidence_refs = list(evidence_refs or [])
    template = _AI_TEMPLATES.get(visual_type, {})
    what = what_am_i_looking_at or _fmt(template.get("what", ""), entity_key)
    why = why_does_it_matter or _fmt(template.get("why", ""), entity_key)
    title = _title(visual_type, entity_key)

    explanation = {
        "what_am_i_looking_at": what,
        "why_does_it_matter":   why,
        "supporting_evidence":  evidence_refs,
    }
    spec: Dict[str, Any] = {
        "visual_type":       visual_type,
        "rendering_tier":    "json",
        "entity_key":        entity_key,
        "title":             title,
        "explanation":       explanation,
        "evidence_refs":     evidence_refs,
        "is_fallback":       True,
        "fallback_reason":   reason,
        "image_url":         None,
        "explanation_valid": False,
    }
    ok, _ = validate_visual_spec({"title": title, "explanation": explanation})
    spec["explanation_valid"] = ok
    return spec


# ---------------------------------------------------------------------------
# Orchestrator (async) — builds, validates, audit-logs, returns request
# ---------------------------------------------------------------------------

async def _log_generation(
    session, *, user_id: str, spec: Dict[str, Any],
    passed: bool, reason: str, banned: List[str], model: str,
) -> None:
    try:
        from app.db.repositories.visual_intelligence_repo import add_ai_visual_log
        await add_ai_visual_log(
            session,
            user_id=user_id,
            visual_type=spec.get("visual_type", ""),
            entity_key=spec.get("entity_key", ""),
            prompt_hash=spec.get("prompt_hash", ""),
            generation_model=model,
            validation_passed=passed,
            validation_reason=(reason or "")[:100],
            banned_phrases_found=",".join(banned),
            run_reason="shadow",
        )
    except Exception as exc:
        logger.debug("[ai_visual] _log_generation failed: %r", exc)


async def generate_visual_request(
    session,
    *,
    user_id: str,
    visual_type: str,
    entity_key: str = "",
    structured_data: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
    generation_model: str = "",
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Build, validate, and audit-log an AI visual generation request.

    Returns the generation request when validation passes, or a deterministic
    fallback spec otherwise.  No image is ever surfaced on a failed path.
    The prompt text is never stored — only its hash is logged.

    When visual_ai_enabled is False (default) or session is None, returns a
    deterministic fallback without invoking generation.
    """
    evidence_refs = list(evidence_refs or [])

    if not _ai_enabled(run_override):
        return build_visual_fallback(
            visual_type=visual_type, entity_key=entity_key,
            evidence_refs=evidence_refs, reason="ai_disabled",
        )
    if session is None:
        return build_visual_fallback(
            visual_type=visual_type, entity_key=entity_key,
            evidence_refs=evidence_refs, reason="no_session",
        )

    try:
        spec = build_visual_generation_spec(
            visual_type=visual_type, entity_key=entity_key,
            structured_data=structured_data, evidence_refs=evidence_refs,
        )

        if not spec["explanation_valid"]:
            await _log_generation(
                session, user_id=user_id, spec=spec,
                passed=False, reason=spec["blocked_reason"], banned=[],
                model=generation_model,
            )
            return build_visual_fallback(
                visual_type=visual_type, entity_key=entity_key,
                evidence_refs=evidence_refs, reason=spec["blocked_reason"],
                what_am_i_looking_at=spec["explanation"]["what_am_i_looking_at"],
                why_does_it_matter=spec["explanation"]["why_does_it_matter"],
            )

        # Post-generation safety validation (simulated — no model call here).
        generated = {
            "title":        spec["title"],
            "explanation":  spec["explanation"],
            "text_content": "",
        }
        ok, reason, banned = validate_generated_visual(generated)
        await _log_generation(
            session, user_id=user_id, spec=spec,
            passed=ok, reason=reason, banned=banned, model=generation_model,
        )
        if not ok:
            return build_visual_fallback(
                visual_type=visual_type, entity_key=entity_key,
                evidence_refs=evidence_refs, reason=reason,
                what_am_i_looking_at=spec["explanation"]["what_am_i_looking_at"],
                why_does_it_matter=spec["explanation"]["why_does_it_matter"],
            )

        return {
            "visual_type":       visual_type,
            "rendering_tier":    "ai_image",
            "entity_key":        entity_key,
            "title":             spec["title"],
            "prompt_hash":       spec["prompt_hash"],
            "evidence_refs":     evidence_refs,
            "explanation":       spec["explanation"],
            "constraints":       spec["constraints"],
            "explanation_valid": True,
            "is_fallback":       False,
            "image_url":         None,
        }
    except Exception as exc:
        logger.debug("[ai_visual] generate_visual_request failed: %r", exc)
        return build_visual_fallback(
            visual_type=visual_type, entity_key=entity_key,
            evidence_refs=evidence_refs, reason="generation_error",
        )
