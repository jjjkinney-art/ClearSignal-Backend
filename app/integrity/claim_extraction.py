"""Generator-facing quantitative-claim extraction (Sprint 1C).

Moves provenance classification UPSTREAM: this module is called from inside
each generator (valuation/macro/risk agents, thesis_synthesizer) right after
that generator produces its own text, using that generator's own evidence
context — not just at the api.py response boundary (Sprint 1B).

``extract_claims()`` finds numeric tokens in generated prose and classifies
each with a ``QuantitativeClaim`` (Provenance + as-of/confidence/assumptions/
source), using keyword cues plus an optional evidence-freshness dimension.
Deliberately conservative: an unclassifiable number defaults to HEURISTIC
(must be visibly qualified), never to an unqualified REPORTED fact.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence

from .provenance import Provenance, QuantitativeClaim

# ── Numeric token pattern ────────────────────────────────────────────────────
# Matches "$6-9B", "$61.9B", "31x", "42%", "154%", "$200B" — value + unit.
_NUM = re.compile(
    r"(?P<sign>~)?\$?\s?(?P<num>\d[\d,]*\.?\d*)"
    r"(?:\s?[-–]\s?\$?(?P<num2>\d[\d,]*\.?\d*))?"
    r"\s?(?P<unit>%|x|bp|bps|B|M|K)?(?!\w)",
    re.IGNORECASE,
)
# NOTE: a trailing \b (rather than the (?!\w) lookahead above) silently fails to
# match a non-word unit like '%' whenever it is followed by whitespace/punctuation
# — \b requires one side to be a word char, and '%' followed by ' ' is non-word on
# both sides. (?!\w) has no such asymmetry and works for every unit we support.

# Context-window cue words (checked in a +/- _WINDOW char radius of the match).
_WINDOW = 60

_SCENARIO_CUES = (
    "if ", " if,", "scenario", "assum", "could reach", "could add", "hypothetical",
    "sensitivity", "sovereign-ai cycle adds", "were to", "in a downside",
    "in an upside", "would imply", "would add",
)
_ESTIMATED_CUES = (
    "estimate", "consensus", "analysts expect", "analyst expect", "projected",
    "guidance implies", "street expects", "forecast", "expected to",
)
_DERIVED_CUES = (
    "based on", "implies", "derived from", "run-rate", "run rate", "annualized",
    "at current pace", "extrapolat", "computed from", "using the",
)
_REPORTED_CUES = (
    "reported", "per the 10-q", "per the 10-k", "per the filing", "quarter",
    "fiscal", "q1", "q2", "q3", "q4", "fy20", "earnings call", "guidance of",
    "came in at", "posted", "print",
)

# Freshness-tier → freshness_status + stale mapping (see freshness_analyzer.py).
_TIER_STATUS = {
    "fresh": ("current", False),
    "moderate": ("dated", False),
    "stale": ("stale", True),
    "very_stale": ("stale", True),
    "unknown": ("source_date_unavailable", True),
}


def _window_text(text: str, start: int, end: int) -> str:
    lo = max(0, start - _WINDOW)
    hi = min(len(text), end + _WINDOW)
    return text[lo:hi].lower()


def _classify(window: str) -> Provenance:
    if any(c in window for c in _SCENARIO_CUES):
        return Provenance.SCENARIO
    if any(c in window for c in _ESTIMATED_CUES):
        return Provenance.ESTIMATED
    if any(c in window for c in _DERIVED_CUES):
        return Provenance.DERIVED
    if any(c in window for c in _REPORTED_CUES):
        return Provenance.REPORTED
    return Provenance.HEURISTIC  # unclassifiable → must be visibly qualified


def _freshness_for_dimension(freshness: Any, dimension: Optional[str]):
    """Return (as_of, stale, freshness_status, source) from a FreshnessProfile-like
    object, tolerant of it being None or missing the requested dimension."""
    if freshness is None or not dimension:
        return None, False, None, None
    dim = getattr(freshness, dimension, None)
    if dim is None:
        return None, False, None, None
    tier = getattr(dim, "tier", "unknown")
    age_days = getattr(dim, "age_days", None)
    status, stale = _TIER_STATUS.get(tier, ("source_date_unavailable", True))
    as_of = f"~{age_days}d old" if isinstance(age_days, (int, float)) else None
    if as_of is None and status == "current":
        # No age available even though the tier claims fresh — be conservative.
        status, stale = "source_date_unavailable", True
    source = f"evidence pool ({dimension})" if dim.item_count else None
    return as_of, stale, status, source


def extract_claims(
    text: str,
    *,
    ticker: Optional[str] = None,
    metric: Optional[str] = None,
    freshness: Any = None,
    dimension: Optional[str] = None,
) -> List[QuantitativeClaim]:
    """Extract and classify quantitative claims from generated prose.

    Parameters
    ----------
    text       : the generator's own output text (e.g. valuation.overall).
    ticker     : the company this claim is about (for cross-ticker isolation).
    metric     : optional metric-name hint applied to every claim found.
    freshness  : optional FreshnessProfile (or None) already computed by the
                 caller from its OWN evidence — this is what makes the check
                 upstream/source-level rather than a boundary re-derivation.
    dimension  : which freshness dimension applies to this text
                 ('earnings'|'filing'|'estimates'|'valuation'|'macro').
    """
    if not text:
        return []
    claims: List[QuantitativeClaim] = []
    as_of, stale, fstatus, source = _freshness_for_dimension(freshness, dimension)

    for m in _NUM.finditer(text):
        num = m.group("num")
        if not num:
            continue
        # Skip bare small integers with no unit/sign — too ambiguous to be a claim
        # (avoids treating "3" in "top 3 risks" as a quantitative claim).
        if not m.group("unit") and not m.group("sign") and "." not in num and len(num) <= 2:
            continue
        window = _window_text(text, m.start(), m.end())
        provenance = _classify(window)
        value_text = m.group(0).strip()

        try:
            raw_value = float(num.replace(",", ""))
        except ValueError:
            raw_value = None
        unit = m.group("unit")

        claim = QuantitativeClaim(
            value_text=value_text,
            provenance=provenance,
            raw_value=raw_value,
            unit=unit,
            ticker=ticker,
            metric=metric,
        )

        if provenance is Provenance.REPORTED:
            claim.as_of = as_of
            claim.stale = stale
            claim.freshness_status = fstatus
            claim.source = source
            if as_of is None and not stale:
                # No freshness signal available at all — cannot assert currency.
                claim.stale = True
                claim.freshness_status = "source_date_unavailable"
        elif provenance in (Provenance.SCENARIO, Provenance.ESTIMATED):
            claim.confidence = claim.confidence or "low"
            claim.assumptions = claim.assumptions or _nearby_assumption(window)
            claim.freshness_status = "scenario_only" if provenance is Provenance.SCENARIO else "dated"
        elif provenance is Provenance.DERIVED:
            claim.derivation = _nearby_assumption(window) or "computed from reported inputs"
            claim.freshness_status = fstatus or "dated"
        else:  # HEURISTIC
            claim.freshness_status = "source_date_unavailable"

        claims.append(claim)

    return claims


def _nearby_assumption(window: str) -> Optional[str]:
    """Best-effort one-clause assumption/derivation summary from the context window."""
    for cue in (*_SCENARIO_CUES, *_ESTIMATED_CUES, *_DERIVED_CUES):
        idx = window.find(cue)
        if idx != -1:
            snippet = window[idx: idx + 50].strip()
            return snippet or None
    return None


def attach_agent_claims(
    view: Any,
    *,
    ticker: str,
    freshness: Any = None,
    dimension: Optional[str] = None,
    metric: Optional[str] = None,
    text_fields: Sequence[str] = ("overall",),
) -> None:
    """Extract claims from a specialist-agent output object's own text fields
    and stamp ``view.quantitative_claims`` (a list of dicts) in place.

    Called from inside run_valuation_agent / run_investment_macro_agent /
    run_risk_agent, right before they return — i.e. at the generation SOURCE,
    using that agent's own (already evidence-filtered) context.  Never raises.
    """
    try:
        claims: List[QuantitativeClaim] = []
        for field_name in text_fields:
            text = getattr(view, field_name, "") or ""
            claims.extend(extract_claims(
                text, ticker=ticker, metric=metric, freshness=freshness, dimension=dimension,
            ))
        signals = getattr(view, "signals", None) or []
        for sig in signals:
            sig_text = getattr(sig, "signal", "") or ""
            claims.extend(extract_claims(
                sig_text, ticker=ticker, metric=metric, freshness=freshness, dimension=dimension,
            ))
        if hasattr(view, "quantitative_claims"):
            view.quantitative_claims = [c.to_dict() for c in claims]
    except Exception:
        # Never let claim extraction break agent generation.
        if hasattr(view, "quantitative_claims"):
            try:
                view.quantitative_claims = []
            except Exception:
                pass
