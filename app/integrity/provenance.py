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

    Sprint 1C additions (all additive/optional — Sprint 1B call sites that only
    pass the original fields are unaffected): ``raw_value``/``unit`` split the
    display string into a machine-comparable number; ``source``/``ticker``/
    ``metric`` identify what produced the claim and for which company;
    ``derivation`` documents how a DERIVED value was computed;
    ``freshness_status`` is one of 'current'|'dated'|'stale'|
    'source_date_unavailable'|'scenario_only' (see freshness_status_for());
    ``source_date_unavailable`` marks a REPORTED claim whose source genuinely
    carries no date (distinct from one that simply omitted it).
    """
    value_text: str
    provenance: Provenance
    as_of: Optional[str] = None            # ISO date (or relative age) of the evidence
    confidence: Optional[str] = None       # 'low' | 'medium' | 'high'
    assumptions: Optional[str] = None      # for SCENARIO/ESTIMATED
    stale: bool = False                    # evidence flagged as not-recent

    raw_value: Optional[float] = None
    unit: Optional[str] = None             # '%', 'x', '$B', '$M', 'bp', ...
    source: Optional[str] = None           # e.g. "10-Q", "earnings call", "FMP snapshot"
    source_date_unavailable: bool = False  # REPORTED claim whose source has no date at all
    ticker: Optional[str] = None
    metric: Optional[str] = None
    derivation: Optional[str] = None       # how a DERIVED value was computed
    freshness_status: Optional[str] = None  # 'current'|'dated'|'stale'|'source_date_unavailable'|'scenario_only'

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

    def to_dict(self) -> dict:
        """JSON-serializable form for response payloads (companion fields)."""
        return {
            "value_text": self.value_text,
            "provenance": self.provenance.value,
            "as_of": self.as_of,
            "confidence": self.confidence,
            "assumptions": self.assumptions,
            "stale": self.stale,
            "raw_value": self.raw_value,
            "unit": self.unit,
            "source": self.source,
            "source_date_unavailable": self.source_date_unavailable,
            "ticker": self.ticker,
            "metric": self.metric,
            "derivation": self.derivation,
            "freshness_status": self.freshness_status,
            "rendered": self.render(),
        }


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
    if claim.provenance is Provenance.DERIVED and not (claim.derivation or claim.assumptions):
        return (
            f"derived claim '{claim.value_text}' has no derivation description "
            "(how it was computed from reported inputs)"
        )
    return None


def validate_claim_sourced(claim: QuantitativeClaim) -> Optional[str]:
    """Stricter validation for claims produced by the Sprint 1C generator-facing
    pipeline (which always sets ``source`` when it asserts REPORTED).  Runs
    ``validate_claim`` first, then additionally requires REPORTED claims to
    carry a source and either an as-of date or an explicit acknowledgement
    that the source has no date (``source_date_unavailable``).

    Kept separate from ``validate_claim`` so Sprint 1B call sites — which never
    set ``source`` — are unaffected.
    """
    base = validate_claim(claim)
    if base:
        return base
    if claim.provenance is Provenance.REPORTED:
        if not claim.source:
            return f"reported claim '{claim.value_text}' has no source identifier"
        if not claim.as_of and not claim.source_date_unavailable:
            return (
                f"reported claim '{claim.value_text}' has a source but no as-of date "
                "and does not explicitly mark the date as unavailable"
            )
    return None
