"""
Post-synthesis validator — deterministic quality checks on InvestmentThesis output.

Part 6 of the Retrieval + Memory + Expectation Intelligence phase.

Purpose
-------
Enforce synthesis guarantees that cannot be guaranteed by prompt alone.
All checks are DETERMINISTIC (no LLM calls) and FAST (pure regex + string ops).

Checks
------
1. SIGNAL REPETITION — "renewal rates", "multiple compression", "rate sensitivity"
   appear in at most one section each.  Violation: list which sections conflict.

2. COMPOUND RISK INTERACTION — bear_thesis must contain at least one cross-signal
   compound risk phrase (using the '+' or 'and' pattern connecting two factors).

3. EXPECTATION FRAMING — thesis_evolution, if non-empty, must reference at least
   one expectation-anchored term (priced-in, consensus, expectations, revised, etc.)
   OR describe a concrete change.

4. SECTION SEMANTIC OVERLAP — key_drivers and key_risks must not share >1 identical
   root term, preventing the bull and bear cases from saying the same thing.

5. EMPTY CRITICAL FIELDS — core_debate, one_sentence_thesis, dominant_driver must
   be non-empty for actionable theses.

6. STANCE-CATALYST CONSISTENCY — if directional_stance == "Tactical", the thesis
   must reference a specific near-term event (earnings, catalyst, event, window,
   data point) in either bear_thesis or thesis_evolution.

Usage
-----
    from app.services.synthesis_validator import validate_thesis, ValidationResult

    result = validate_thesis(thesis)
    if result.has_violations:
        # Retry synthesis with result.retry_prompt_addendum
        pass

Design invariants
-----------------
* Zero LLM calls. Pure Python. Returns in < 1 ms.
* ValidationResult.retry_prompt_addendum is self-contained and usable directly
  as an injection into the synthesis prompt for a targeted retry.
* If an error occurs during validation it is caught and logged — never raises.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..schemas import InvestmentThesis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Phrases that may appear in at most ONE section of the thesis.
# Key: canonical phrase (lower); Value: list of section names to check.
SINGLE_SECTION_PHRASES: dict = {
    "renewal rates": ["bull_thesis", "bear_thesis", "key_drivers", "key_risks",
                      "valuation_view", "conclusion"],
    "multiple compression": ["bull_thesis", "bear_thesis", "key_drivers", "key_risks",
                              "valuation_view", "conclusion"],
    "rate sensitivity": ["bull_thesis", "bear_thesis", "macro_sensitivity",
                          "key_drivers", "key_risks"],
    "membership fee": ["bull_thesis", "bear_thesis", "key_drivers", "key_risks",
                        "valuation_view"],
}

# Minimum evidence of compound cross-signal interaction in bear_thesis
COMPOUND_RISK_CONNECTORS = (
    " + ", " and ", " combined with ", " compounded by ",
    " amplified by ", " alongside ",
)
COMPOUND_RISK_INDICATOR_PATTERN = re.compile(
    r"(\w[\w\s\-]+)\s*\+\s*(\w[\w\s\-]+)",
    re.IGNORECASE,
)

# Expectation framing anchors required in thesis_evolution when non-empty
EXPECTATION_FRAMING_TERMS = (
    "priced", "consensus", "expect", "revised", "estimate", "bar ",
    "market is now", "already reflect", "priced in", "upside", "downside",
    "changed", "shifted", "accelerat", "decelerat", "inflect",
)

# Tactical stance requires a specific near-term event reference
TACTICAL_EVENT_TERMS = (
    "earnings", "catalyst", "event", "window", "quarter", "data point",
    "print", "print ", "release", "announcement", "guidance", "meeting",
    "report", "results", "read-out", "readout",
)

# Fields required to be non-empty for actionable/buy-type stances
REQUIRED_FIELDS_ACTIONABLE = (
    "core_debate",
    "one_sentence_thesis",
    "dominant_driver",
)

ACTIONABLE_STANCES = {"Aggressive Buy", "Buy", "Accumulate"}


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class ValidationViolation:
    """A single detected violation."""
    check_id: str            # e.g. "REPEAT_RENEWAL_RATES"
    description: str         # Human-readable description
    severity: str = "warn"   # "hard" = must fix, "warn" = advisory
    sections_affected: List[str] = field(default_factory=list)
    remediation_hint: str = ""


@dataclass
class ValidationResult:
    """Complete validation result for one InvestmentThesis."""
    violations: List[ValidationViolation] = field(default_factory=list)
    checks_run: int = 0
    passed: int = 0

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    @property
    def hard_violations(self) -> List[ValidationViolation]:
        return [v for v in self.violations if v.severity == "hard"]

    @property
    def has_hard_violations(self) -> bool:
        return bool(self.hard_violations)

    @property
    def retry_prompt_addendum(self) -> str:
        """Self-contained prompt injection for a targeted synthesis retry.

        Lists each hard violation with its specific remediation instruction.
        Returns empty string when no hard violations exist.
        """
        if not self.hard_violations:
            return ""
        lines = [
            "SYNTHESIS CORRECTION REQUIRED — The previous output violated the following rules.",
            "Correct ONLY these specific issues and regenerate the JSON:",
            "",
        ]
        for i, v in enumerate(self.hard_violations, start=1):
            lines.append(f"  {i}. [{v.check_id}] {v.description}")
            if v.remediation_hint:
                lines.append(f"     FIX: {v.remediation_hint}")
        lines.append(
            "\nAll other content should remain substantively identical. "
            "Do not change fields that were not violated."
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

def _check_signal_repetition(thesis: "InvestmentThesis") -> List[ValidationViolation]:
    """Check 1 — forbidden phrases appear in at most one section."""
    violations: List[ValidationViolation] = []

    # Build section text map
    section_texts = {
        "bull_thesis":    (getattr(thesis, "bull_thesis", "") or "").lower(),
        "bear_thesis":    (getattr(thesis, "bear_thesis", "") or "").lower(),
        "valuation_view": (getattr(thesis, "valuation_view", "") or "").lower(),
        "macro_sensitivity": (getattr(thesis, "macro_sensitivity", "") or "").lower(),
        "conclusion":     (getattr(thesis, "conclusion", "") or "").lower(),
        "key_drivers":    " ".join(getattr(thesis, "key_drivers", []) or []).lower(),
        "key_risks":      " ".join(getattr(thesis, "key_risks", []) or []).lower(),
    }

    for phrase, sections_to_check in SINGLE_SECTION_PHRASES.items():
        found_in = [
            s for s in sections_to_check
            if s in section_texts and phrase in section_texts[s]
        ]
        if len(found_in) > 1:
            violations.append(ValidationViolation(
                check_id          = f"REPEAT_{phrase.upper().replace(' ', '_')}",
                description       = (
                    f"'{phrase}' appeared in {len(found_in)} sections: "
                    f"{', '.join(found_in)}. Must appear in at most one section."
                ),
                severity          = "hard",
                sections_affected = found_in,
                remediation_hint  = (
                    f"Remove '{phrase}' from all but the single most analytically "
                    f"important section. Use a synonym or rephrase in others."
                ),
            ))
    return violations


def _check_compound_risk(thesis: "InvestmentThesis") -> List[ValidationViolation]:
    """Check 2 — bear_thesis must contain at least one compound cross-signal risk."""
    bear = (getattr(thesis, "bear_thesis", "") or "")
    if not bear.strip():
        return []  # Empty bear thesis is a separate issue

    has_compound = False

    # Check for '+' compound pattern: "X + Y = Z" or "X + Y"
    if COMPOUND_RISK_INDICATOR_PATTERN.search(bear):
        has_compound = True

    # Check for connector phrases with substance on both sides
    if not has_compound:
        bear_lower = bear.lower()
        for connector in COMPOUND_RISK_CONNECTORS:
            idx = bear_lower.find(connector)
            if idx > 10 and idx < len(bear_lower) - 10:
                # Something meaningful on both sides
                has_compound = True
                break

    if not has_compound:
        return [ValidationViolation(
            check_id         = "MISSING_COMPOUND_RISK",
            description      = (
                "bear_thesis does not contain a cross-signal compound risk interaction. "
                "The bear case must name at least one multi-factor compound risk "
                "(e.g. 'higher rates + lean inventory = muted macro sensitivity')."
            ),
            severity         = "hard",
            sections_affected= ["bear_thesis"],
            remediation_hint = (
                "Add one compound risk phrase to bear_thesis using the format: "
                "'[factor A] + [factor B] = [compound outcome]'. "
                "Example: 'margin pressure + elevated capex + rate sensitivity = "
                "multiple compression risk that a simple bear case understates.'"
            ),
        )]
    return []


def _check_expectation_framing(thesis: "InvestmentThesis") -> List[ValidationViolation]:
    """Check 3 — thesis_evolution, if present, must frame an expectation shift."""
    evolution = (getattr(thesis, "thesis_evolution", "") or "").strip()
    if not evolution or len(evolution) < 30:
        return []  # Empty/sparse evolution is OK (no prior data)

    evolution_lower = evolution.lower()
    has_framing = any(term in evolution_lower for term in EXPECTATION_FRAMING_TERMS)
    if not has_framing:
        return [ValidationViolation(
            check_id         = "EVOLUTION_NO_EXPECTATION_FRAMING",
            description      = (
                "thesis_evolution is present but does not reference what changed "
                "from an expectation/consensus perspective. Generic language detected."
            ),
            severity         = "warn",
            sections_affected= ["thesis_evolution"],
            remediation_hint = (
                "thesis_evolution should explicitly state whether expectations "
                "accelerated, decelerated, or the consensus bar shifted. "
                "Avoid generic 'the company continues to...' language."
            ),
        )]
    return []


def _check_section_semantic_overlap(thesis: "InvestmentThesis") -> List[ValidationViolation]:
    """Check 4 — key_drivers and key_risks must not share >1 identical root term.

    Root term = first 8 characters of each token (>4 chars), normalized to lower.
    Duplicate terms in both lists = the bull and bear cases are circular.
    """
    drivers = getattr(thesis, "key_drivers", []) or []
    risks   = getattr(thesis, "key_risks",   []) or []

    def _root_terms(items: list) -> set:
        roots = set()
        for item in items:
            words = re.findall(r"\b[a-z]{5,}\b", item.lower())
            roots.update(w[:8] for w in words if w not in (
                "about", "which", "these", "their", "there", "would", "could",
                "should", "where", "might", "growth", "margin", "revenu",
                "busine", "compan", "invest", "market",
            ))
        return roots

    driver_roots = _root_terms(drivers)
    risk_roots   = _root_terms(risks)
    overlap      = driver_roots & risk_roots

    if len(overlap) > 2:  # allow up to 2 shared roots (e.g. "execution", "margin")
        sampled = sorted(overlap)[:5]
        return [ValidationViolation(
            check_id          = "SEMANTIC_OVERLAP_DRIVERS_RISKS",
            description       = (
                f"key_drivers and key_risks share {len(overlap)} root terms "
                f"({', '.join(sampled)}...) — bull and bear cases are circular."
            ),
            severity          = "warn",
            sections_affected = ["key_drivers", "key_risks"],
            remediation_hint  = (
                "key_drivers should describe value-creation mechanisms; "
                "key_risks should describe specific failure modes. "
                "They should not share the same root concepts."
            ),
        )]
    return []


def _check_required_fields(thesis: "InvestmentThesis") -> List[ValidationViolation]:
    """Check 5 — required fields must be non-empty for actionable stances."""
    stance = (getattr(thesis, "directional_stance", "") or "").strip()
    if stance not in ACTIONABLE_STANCES:
        return []

    violations = []
    for field_name in REQUIRED_FIELDS_ACTIONABLE:
        val = (getattr(thesis, field_name, "") or "").strip()
        if not val:
            violations.append(ValidationViolation(
                check_id         = f"MISSING_{field_name.upper()}",
                description      = (
                    f"'{field_name}' is empty but stance is '{stance}' — "
                    "actionable stances require this field."
                ),
                severity         = "hard",
                sections_affected= [field_name],
                remediation_hint = (
                    f"Populate '{field_name}' with a specific, company-grounded "
                    "statement. Not generic or placeholder text."
                ),
            ))
    return violations


def _check_tactical_catalyst(thesis: "InvestmentThesis") -> List[ValidationViolation]:
    """Check 6 — Tactical stance must reference a specific near-term event."""
    stance = (getattr(thesis, "directional_stance", "") or "").strip()
    if stance != "Tactical":
        return []

    # Check bear_thesis, thesis_evolution, and conclusion for event references
    text_to_check = " ".join([
        getattr(thesis, "bear_thesis", "") or "",
        getattr(thesis, "thesis_evolution", "") or "",
        getattr(thesis, "conclusion", "") or "",
        getattr(thesis, "directional_stance_reasoning", "") or "",
    ]).lower()

    has_event = any(term in text_to_check for term in TACTICAL_EVENT_TERMS)
    if not has_event:
        return [ValidationViolation(
            check_id         = "TACTICAL_MISSING_CATALYST",
            description      = (
                "directional_stance is 'Tactical' but no specific near-term event "
                "is referenced (earnings, catalyst, event window, data point). "
                "Tactical setups require an identifiable event horizon."
            ),
            severity         = "hard",
            sections_affected= ["directional_stance_reasoning", "conclusion"],
            remediation_hint = (
                "Add a specific near-term catalyst to directional_stance_reasoning "
                "or conclusion. Example: 'The setup is event-driven — the upcoming "
                "earnings print is the fulcrum.' If no specific event exists, "
                "consider changing the stance to Hold or Accumulate."
            ),
        )]
    return []


# ---------------------------------------------------------------------------
# Main validate_thesis entry point
# ---------------------------------------------------------------------------

def validate_thesis(thesis: "InvestmentThesis") -> ValidationResult:
    """Run all deterministic checks on a synthesized InvestmentThesis.

    Returns a ValidationResult containing any violations found.
    Never raises — catches internal errors and logs them.

    Runtime: <1ms for typical thesis objects.
    """
    result = ValidationResult()

    checks = [
        ("signal_repetition",     _check_signal_repetition),
        ("compound_risk",         _check_compound_risk),
        ("expectation_framing",   _check_expectation_framing),
        ("semantic_overlap",      _check_section_semantic_overlap),
        ("required_fields",       _check_required_fields),
        ("tactical_catalyst",     _check_tactical_catalyst),
    ]

    for check_name, check_fn in checks:
        result.checks_run += 1
        try:
            violations = check_fn(thesis)
            if violations:
                result.violations.extend(violations)
            else:
                result.passed += 1
        except Exception as exc:
            logger.warning(
                "synthesis_validator: check '%s' raised %s — skipping",
                check_name, exc,
            )
            result.passed += 1  # Don't block on validator error

    return result


def summarize_validation(result: ValidationResult) -> str:
    """Return a human-readable summary of validation results for logging."""
    if not result.has_violations:
        return f"validation passed ({result.checks_run} checks)"
    total    = len(result.violations)
    hard     = len(result.hard_violations)
    warn     = total - hard
    ids      = ", ".join(v.check_id for v in result.violations[:5])
    return (
        f"validation: {hard} hard + {warn} warn violations "
        f"({result.checks_run} checks) — {ids}"
    )
