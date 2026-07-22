"""Provenance classification for quantitative claims (Sprint 1B, issues #4, #5).

Every displayed number should carry where it came from so scenario/estimated
figures (e.g. NVDA's "$6-9B revenue effect") never render as reported fact, and
stale reported figures carry an as-of date or explicit qualifier.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Provenance(str, Enum):
    REPORTED = "reported"      # directly from a filing / print (fact)
    DERIVED = "derived"        # computed from reported inputs (e.g. a ratio)
    ESTIMATED = "estimated"    # model/consensus estimate
    SCENARIO = "scenario"      # conditional on an assumption ("if X, then ~$Y")
    HEURISTIC = "heuristic"    # rule-of-thumb / keyword inference


# Provenances that must NEVER be rendered as a bare fact.
_MUST_QUALIFY = {Provenance.ESTIMATED, Provenance.SCENARIO, Provenance.HEURISTIC}

_QUALIFIER = {
    Provenance.ESTIMATED: "est.",
    Provenance.SCENARIO: "scenario",
    Provenance.HEURISTIC: "rule-of-thumb",
    Provenance.DERIVED: "derived",
}


@dataclass
class QuantitativeClaim:
    """A number plus its provenance and evidence metadata.

    ``value_text`` is the rendered figure (e.g. "$6-9B", "31x", "42%").
    """
    value_text: str
    provenance: Provenance
    as_of: Optional[str] = None            # ISO date of the underlying evidence
    confidence: Optional[str] = None       # 'low' | 'medium' | 'high'
    assumptions: Optional[str] = None      # for SCENARIO/ESTIMATED
    stale: bool = False                    # evidence flagged as not-recent

    def must_qualify(self) -> bool:
        return self.provenance in _MUST_QUALIFY or self.stale

    def render(self) -> str:
        """Render the claim so its status is explicit.

        - REPORTED & fresh → the plain value (optionally with as-of).
        - ESTIMATED/SCENARIO/HEURISTIC/DERIVED → value + a provenance qualifier.
        - stale REPORTED → value + explicit as-of / 'as of' qualifier.
        Never emits an estimate/scenario number as an unqualified fact.
        """
        parts = [self.value_text]
        quals = []
        if self.provenance in _QUALIFIER:
            quals.append(_QUALIFIER[self.provenance])
        if self.assumptions and self.provenance in (Provenance.SCENARIO, Provenance.ESTIMATED):
            quals.append(f"assumes {self.assumptions}")
        if self.as_of:
            quals.append(f"as of {self.as_of}")
        elif self.stale:
            quals.append("as-of date unavailable")
        if self.confidence:
            quals.append(f"{self.confidence} confidence")
        if quals:
            return f"{parts[0]} ({'; '.join(quals)})"
        return parts[0]

    def is_valid(self) -> bool:
        """A claim that MUST be qualified is only valid if it can be (has a
        qualifier source: provenance qualifier, assumptions, or as_of)."""
        if not self.must_qualify():
            return True
        return bool(
            self.provenance in _QUALIFIER or self.assumptions or self.as_of
        )


def validate_claim(claim: QuantitativeClaim) -> Optional[str]:
    """Return a violation message when a claim would render unsafe, else None."""
    if claim.provenance in (Provenance.SCENARIO, Provenance.ESTIMATED) and not (
        claim.assumptions or claim.as_of or claim.confidence
    ):
        return (
            f"{claim.provenance.value} claim '{claim.value_text}' lacks "
            "assumption/date/confidence metadata; would read as reported fact"
        )
    if claim.stale and not claim.as_of:
        return (
            f"stale claim '{claim.value_text}' has no as-of date; must be "
            "suppressed or explicitly qualified"
        )
    return None
