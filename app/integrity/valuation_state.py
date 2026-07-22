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


# expectation_regime (conviction modeler) → state
_REGIME_MAP = {
    "cheap": ValuationState.CHEAP,
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


# Prose keyword heuristic — HEURISTIC provenance, used only to flag a
# label-vs-prose contradiction (never to assert a state as fact).
_CHEAP_WORDS = (
    "undervalued", "cheap", "discount to intrinsic", "below intrinsic",
    "attractive entry", "margin of safety", "priced cheap",
)
_STRETCHED_WORDS = (
    "overvalued", "expensive", "demanding", "stretched", "rich valuation",
    "premium multiple", "limited upside", "priced for perfection",
    "fully priced", "priced in",
)
_FAIR_WORDS = ("fairly valued", "fair value", "reasonably valued", "fairly priced")


def from_prose(text: Optional[str]) -> ValuationState:
    """Best-effort classification of free-text valuation prose.  Deliberately
    conservative: returns UNDETERMINED unless the language clearly leans one way."""
    if not text:
        return ValuationState.UNDETERMINED
    t = text.lower()
    cheap = sum(1 for w in _CHEAP_WORDS if w in t)
    stretched = sum(1 for w in _STRETCHED_WORDS if w in t)
    fair = sum(1 for w in _FAIR_WORDS if w in t)
    # "priced in / limited upside" strongly implies not-cheap.
    if stretched and stretched >= cheap and stretched >= fair:
        return ValuationState.STRETCHED
    if fair and fair >= cheap and fair >= stretched:
        return ValuationState.FAIR
    if cheap and cheap > stretched and cheap > fair:
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
