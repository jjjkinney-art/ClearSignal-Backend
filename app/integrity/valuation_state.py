"""Shared valuation-state contract (Sprint 1B, issue #1).

The pipeline computes valuation in three *independent* places that could disagree
and reach the frontend:

  * ``expectation_regime``  (conviction modeler, FROZEN) — cheap|fair|stretched|
    euphoric|bubble.  This drives the "Priced Cheap" label.
  * ``valuation_stance``    (valuation agent LLM) — overpriced|fairly_valued|
    underpriced|cannot_determine.
  * the written valuation prose (``valuation_view`` / ``overall`` / conclusion).

``ValuationState`` is the single contract every field maps into, so a validator
can detect the observed contradiction (e.g. MSFT/NVDA label "cheap" while the
prose says fairly/ demanding-valued) instead of shipping it.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional, Tuple


class ValuationState(str, Enum):
    CHEAP = "cheap"
    FAIR = "fair"
    STRETCHED = "stretched"
    UNDETERMINED = "undetermined"


# expectation_regime (conviction modeler) → state.
# The modeler's documented vocabulary is
# 'cheap' | 'attractive' | 'fair' | 'stretched' | 'euphoric' | 'bubble'
# (conviction_modeler._classify_expectation_regime), ordered by ascending
# expectation fragility.  Sprint 2C: 'attractive' was missing here, so three
# benchmark responses with a perfectly valid regime silently reconciled to
# UNDETERMINED and displayed "Valuation Unclear". It sits below 'fair' on the
# fragility scale, i.e. cheap-leaning.
_REGIME_MAP = {
    "cheap": ValuationState.CHEAP,
    "attractive": ValuationState.CHEAP,
    "fair": ValuationState.FAIR,
    "stretched": ValuationState.STRETCHED,
    "euphoric": ValuationState.STRETCHED,
    "bubble": ValuationState.STRETCHED,
}

# valuation_stance (valuation agent) → state
_STANCE_MAP = {
    "underpriced": ValuationState.CHEAP,
    "fairly_valued": ValuationState.FAIR,
    "overpriced": ValuationState.STRETCHED,
    "cannot_determine": ValuationState.UNDETERMINED,
    "": ValuationState.UNDETERMINED,
}


def from_regime(regime: Optional[str]) -> ValuationState:
    return _REGIME_MAP.get((regime or "").strip().lower(), ValuationState.UNDETERMINED)


def from_stance(stance: Optional[str]) -> ValuationState:
    return _STANCE_MAP.get((stance or "").strip().lower(), ValuationState.UNDETERMINED)


# Prose valuation lexicon — HEURISTIC, used only to flag a label-vs-prose
# contradiction (never to assert a state as fact).
#
# Sprint 2C: these are REGEXES, not substrings.  The Boeing structural-risk
# response shipped "Priced Cheap" against prose reading "the stock already
# prices in a recovery" / "the market is currently pricing in a recovery" —
# a plain "priced in" substring misses both inflections, so the contradiction
# went undetected.  Matching the verb stem catches price/prices/priced/pricing.
_STRETCHED_PATTERNS = (
    r"overvalu(?:ed|ation)",
    r"\bexpensive\b",                      # \b keeps "inexpensive" out
    r"\bdemanding\b",
    r"\bstretched\b",
    r"rich(?:ly)?\s+valu(?:ed|ation)",
    r"premium multiple",
    r"limited upside",
    r"priced for perfection",
    r"no margin of safety",
    r"leaves?\s+little\s+room",
    r"lofty|elevated multiple",
)

# "The stock already prices in X" says the price EMBEDS the growth — that is a
# fully-valued statement, not an assertion that the stock is expensive.  It is
# scored as FAIR so it corrects a wrong "cheap" label without branding the
# response overvalued.  Only the genuinely expensive vocabulary above escalates
# to a hard cheap-vs-stretched contradiction.
_FULLY_PRICED_PATTERNS = (
    r"fully (?:priced|valued)",
    r"pric(?:e|es|ed|ing)\s+in\b",         # priced in / prices in / pricing in
    r"already\s+(?:pric|reflect|discount|bak)",
)
_CHEAP_PATTERNS = (
    r"undervalu(?:ed|ation)",
    r"\bcheap(?:ly)?\b",
    r"discount to intrinsic",
    r"below intrinsic",
    r"attractive entry",
    r"margin of safety",
    r"\bbargain\b",
    r"compelling value",
    r"\binexpensive\b",
)
_FAIR_PATTERNS = (
    r"fairly valued", r"fair value", r"reasonably valued", r"fairly priced",
)

# Language that cancels a match rather than inverting it.  "not expensive" and
# "less demanding" must not read as expensive, but they are also not a positive
# assertion of cheapness — naive inversion would be its own bug — so a negated
# match simply does not count for either side.
_NEGATORS = (
    r"\bnot\b", r"n't\b", r"\bnever\b", r"\bno\b", r"\bless\b", r"\bleast\b",
    r"\bhardly\b", r"\bfar from\b", r"\bwithout\b", r"\bavoid", r"\bnothing\b",
    r"\bno longer\b", r"\brather than\b", r"\binstead of\b",
)
# Past-tense / historical framing: "was expensive", "had been stretched" describe
# where the stock HAS been, not where it is now, so they do not establish the
# current state either.
_HISTORICAL = (
    r"\bwas\b", r"\bwere\b", r"\bhad been\b", r"\bpreviously\b",
    r"\bhistorically\b", r"\bused to\b", r"\bin the past\b", r"\bonce\b",
    r"\bformerly\b", r"\blast year\b", r"\bhas been\b",
)

_NEGATION_WINDOW = 40  # chars of left context inspected for a canceller

_COMPILED = {
    "stretched": tuple(re.compile(p, re.IGNORECASE) for p in _STRETCHED_PATTERNS),
    "cheap": tuple(re.compile(p, re.IGNORECASE) for p in _CHEAP_PATTERNS),
    "fair": tuple(re.compile(p, re.IGNORECASE) for p in _FAIR_PATTERNS),
    "fully_priced": tuple(re.compile(p, re.IGNORECASE) for p in _FULLY_PRICED_PATTERNS),
}
_CANCELLERS = tuple(
    re.compile(p, re.IGNORECASE) for p in (*_NEGATORS, *_HISTORICAL)
)


def _is_cancelled(text: str, start: int) -> bool:
    """True when the match at ``start`` is negated or framed as historical.

    The lookback is clipped at the nearest sentence boundary so a negation in a
    previous sentence cannot silently cancel a fresh assertion.
    """
    lo = max(0, start - _NEGATION_WINDOW)
    window = text[lo:start]
    for boundary in (". ", "! ", "? ", "; "):
        idx = window.rfind(boundary)
        if idx != -1:
            window = window[idx + len(boundary):]
    return any(c.search(window) for c in _CANCELLERS)


def _count_lean(text: str, bucket: str) -> int:
    """Number of non-cancelled matches for one valuation lean."""
    return sum(
        1
        for pattern in _COMPILED[bucket]
        for m in pattern.finditer(text)
        if not _is_cancelled(text, m.start())
    )


def from_prose(text: Optional[str]) -> ValuationState:
    """Best-effort classification of free-text valuation prose.  Deliberately
    conservative: returns UNDETERMINED unless the language clearly leans one way.

    Negated ("not expensive") and historical ("was expensive") phrasings are
    discarded rather than inverted, so neither can manufacture a contradiction.
    """
    if not text:
        return ValuationState.UNDETERMINED
    cheap = _count_lean(text, "cheap")
    stretched = _count_lean(text, "stretched")
    fair = _count_lean(text, "fair")
    fully_priced = _count_lean(text, "fully_priced")

    # Explicit expensive vocabulary outranks the weaker fully-priced signal.
    # "The multiple already prices in durability; limited upside from here" is
    # expensive prose — the fully-priced clause does not soften "limited
    # upside", so fully_priced must not be able to outvote it.
    if stretched and stretched >= cheap:
        return ValuationState.STRETCHED
    # Fully-priced language reads as fully valued, and joins explicit fair
    # wording at the FAIR tier.
    fair_total = fair + fully_priced
    if fair_total and fair_total >= cheap:
        return ValuationState.FAIR
    if cheap:
        return ValuationState.CHEAP
    return ValuationState.UNDETERMINED


_OPPOSITE = {
    (ValuationState.CHEAP, ValuationState.STRETCHED),
    (ValuationState.STRETCHED, ValuationState.CHEAP),
}


def contradicts(a: ValuationState, b: ValuationState) -> bool:
    """True only for a hard directional contradiction (cheap vs stretched).
    FAIR vs CHEAP/STRETCHED is a soft disagreement, not a contradiction."""
    if a is ValuationState.UNDETERMINED or b is ValuationState.UNDETERMINED:
        return False
    return (a, b) in _OPPOSITE


def reconcile(*states: ValuationState) -> Tuple[ValuationState, bool]:
    """Collapse several valuation states into one shared state.

    Returns ``(state, contradiction)``.  Any hard opposite (cheap vs stretched)
    among the inputs sets contradiction=True and yields UNDETERMINED (fail-closed
    — the label is not trustworthy).  Otherwise the most-specific agreed state is
    returned (UNDETERMINED inputs are ignored).
    """
    concrete = [s for s in states if s is not ValuationState.UNDETERMINED]
    if not concrete:
        return ValuationState.UNDETERMINED, False
    for i in range(len(concrete)):
        for j in range(i + 1, len(concrete)):
            if contradicts(concrete[i], concrete[j]):
                return ValuationState.UNDETERMINED, True
    # No hard contradiction. Prefer a directional state over FAIR when present.
    for s in (ValuationState.CHEAP, ValuationState.STRETCHED):
        if s in concrete and ValuationState.FAIR not in concrete:
            return s, False
    if all(s is ValuationState.FAIR for s in concrete):
        return ValuationState.FAIR, False
    # Mixed FAIR + one directional (soft) → FAIR (conservative, not a contradiction).
    return ValuationState.FAIR, False


def label_for(state: ValuationState) -> str:
    """Human display label for the reconciled state (used for the price chip)."""
    return {
        ValuationState.CHEAP: "Priced Cheap",
        ValuationState.FAIR: "Fairly Priced",
        ValuationState.STRETCHED: "Priced Rich",
        ValuationState.UNDETERMINED: "Valuation Unclear",
    }[state]
