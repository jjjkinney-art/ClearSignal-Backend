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

from .identifiers import identifier_label_at, identifier_spans
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
    # Sprint 2B — bare conditional/subjunctive framing. Sprint 2A left macro
    # sensitivities like "a 100 bps rise would compress margins" as HEURISTIC
    # even though the sentence is explicitly conditional.
    " would ", " could ", " were ", "each 100", "per 100 bps", "a 100 bps",
    "every 100 bps", "all else equal", "holding ", "implies a downside",
)
_ESTIMATED_CUES = (
    "estimate", "consensus", "analysts expect", "analyst expect", "projected",
    "guidance implies", "street expects", "forecast", "expected to",
    # Sprint 2B — first-person and modelled estimate language.
    "we estimate", "our estimate", "modeled", "modelled", "we model",
    "we project", "implied by consensus", "street consensus",
)
_DERIVED_CUES = (
    "based on", "implies", "derived from", "run-rate", "run rate", "annualized",
    "at current pace", "extrapolat", "computed from", "using the",
    # Sprint 2B — explicit arithmetic-relationship language.
    "translates to", "equates to", "equivalent to", "works out to",
    "multiplying", "dividing", "as a multiple of", "ratio of",
)
_REPORTED_CUES = (
    "reported", "per the 10-q", "per the 10-k", "per the filing", "quarter",
    "fiscal", "q1", "q2", "q3", "q4", "fy20", "earnings call", "guidance of",
    "came in at", "posted", "print",
)

# Sprint 2B — forward-looking / conditional language.  Sprint 2A found REPORTED
# firing on prose like "exceeding 25% in the next quarterly report": the word
# "quarter" is a reported cue, but the sentence describes a FUTURE result, not
# a published one.  When a reported cue has no source binding, these decide
# whether the honest fallback is SCENARIO rather than bare HEURISTIC.
_FORWARD_CUES = (
    "next quarter", "in the next", "upcoming", "coming quarter", "will need",
    "would need", "must ", "should reach", "target", "trajectory", "path to",
    "by 2026", "by 2027", "by 2028", "going forward", "over the next",
    "guide", "outlook", "on track to", "expects to", "aiming",
)

# Explicit source references that prose can cite for itself. A claim whose
# surrounding text names the document it came from IS source-bound, even when
# the evidence pool supplied nothing — "net revenue grew 11% per the 10-Q"
# identifies its own source. Deliberately narrow: only concrete, checkable
# documents count. Period words like "quarter"/"fiscal"/"q3" are NOT sources —
# treating them as such is precisely the Sprint 2A defect.
_SOURCE_REFERENCES = (
    (r"\b10-q\b", "10-Q"),
    (r"\b10-k\b", "10-K"),
    (r"\b8-k\b", "8-K"),
    (r"\b20-f\b", "20-F"),
    (r"\bproxy statement\b|\bdef 14a\b", "proxy statement"),
    (r"\bearnings call\b|\bconference call\b", "earnings call"),
    (r"\bpress release\b", "press release"),
    (r"\bannual report\b", "annual report"),
    (r"\bshareholder letter\b", "shareholder letter"),
    (r"\bsec filing\b|\bthe filing\b|\bregulatory filing\b", "SEC filing"),
    (r"\binvestor (?:day|presentation)\b", "investor presentation"),
)
_SOURCE_REFERENCES = tuple(
    (re.compile(p, re.IGNORECASE), label) for p, label in _SOURCE_REFERENCES
)

# Directional sense of the condition around a figure. Captured at extraction
# time so canonicalization can keep "above 25%" and "below 25%" distinct.
_ABOVE_WORDS = (
    "above", "exceed", "exceeding", "over ", "greater than", "more than",
    "at least", "sustain", "north of", "beat", "outperform", "upside",
)
_BELOW_WORDS = (
    "below", "under ", "less than", "falls below", "decline", "declining",
    "decrease", "compress", "deceleration", "slowdown", "drop", "beneath",
    "south of", "miss", "underperform", "downside", "contract",
)

# Freshness-tier → freshness_status + stale mapping (see freshness_analyzer.py).
_TIER_STATUS = {
    "fresh": ("current", False),
    "moderate": ("dated", False),
    "stale": ("stale", True),
    "very_stale": ("stale", True),
    "unknown": ("source_date_unavailable", True),
}


def _window_text(text: str, start: int, end: int, *,
                 before: int = _WINDOW, after: int = _WINDOW) -> str:
    """Lowercased context around a numeric match.

    ``before``/``after`` are asymmetric on purpose: polarity words ("above",
    "falls below") almost always PRECEDE the figure, so polarity detection uses
    a tight, left-biased window to avoid picking up the opposite sense from a
    neighbouring clause.
    """
    lo = max(0, start - before)
    hi = min(len(text), end + after)
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


def has_source_binding(
    source: Optional[str], as_of: Optional[str], source_date_unavailable: bool = False,
) -> bool:
    """A REPORTED claim is only defensible with a real source binding: something
    identifying WHERE the number came from, plus either WHEN it was true or an
    explicit acknowledgement that the source carries no date.

    Prose cue words are never part of this test — that is the Sprint 2A defect
    this function exists to close.
    """
    if not (source and str(source).strip()):
        return False
    return bool(as_of and str(as_of).strip()) or bool(source_date_unavailable)


def _downgrade_unsourced_reported(window: str) -> Provenance:
    """Choose the honest classification for a claim that *looked* REPORTED but
    has no source binding.  Never fabricates a source or a date — it only
    reclassifies, and only downward.

    ``_classify`` already ruled out the scenario/estimated/derived cue sets
    before returning REPORTED, so the decision here rests on forward-looking
    language: a figure described as something a future filing will show is a
    SCENARIO, and anything weaker falls back to HEURISTIC.
    """
    if any(c in window for c in _FORWARD_CUES):
        return Provenance.SCENARIO
    if any(c in window for c in _ESTIMATED_CUES):
        return Provenance.ESTIMATED
    if any(c in window for c in _DERIVED_CUES):
        return Provenance.DERIVED
    return Provenance.HEURISTIC


def inline_source(window: str) -> Optional[str]:
    """Return the document the surrounding prose cites as this figure's source,
    or None. Used to satisfy source binding when the evidence pool did not
    supply one — never to invent a source that the text does not name.
    """
    for pattern, label in _SOURCE_REFERENCES:
        if pattern.search(window):
            return f"{label} (cited in text)"
    return None


def _polarity(window: str) -> Optional[str]:
    """Directional sense of the condition wrapped around a figure.

    ``below`` is tested first: bear-case prose routinely contains both senses
    ("growth above 25%... a decline below 25%"), and the decline reading is the
    one that must not be conflated with the bull framing.
    """
    if any(w in window for w in _BELOW_WORDS):
        return "below"
    if any(w in window for w in _ABOVE_WORDS):
        return "above"
    return None


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
    # Character spans of numbers that belong to a product/model/filing/index
    # name rather than to a measurement (Sprint 2B).
    id_spans = identifier_spans(text)

    for m in _NUM.finditer(text):
        num = m.group("num")
        if not num:
            continue
        # Skip bare small integers with no unit/sign — too ambiguous to be a claim
        # (avoids treating "3" in "top 3 risks" as a quantitative claim).
        if not m.group("unit") and not m.group("sign") and "." not in num and len(num) <= 2:
            continue
        # Skip a number that is part of an identifier phrase ("Microsoft 365",
        # "Boeing 737"). Any other figure in the same sentence is unaffected.
        if identifier_label_at(id_spans, m.start("num"), m.end("num")):
            continue
        window = _window_text(text, m.start(), m.end())
        provenance = _classify(window)
        value_text = m.group(0).strip()

        try:
            raw_value = float(num.replace(",", ""))
        except ValueError:
            raw_value = None
        unit = m.group("unit")

        # Sprint 2B — enforce source binding BEFORE accepting REPORTED. Cue
        # words alone can no longer make a number read as published fact; a
        # claim without a real source binding is reclassified downward.
        claim_source = source
        downgraded = False
        if provenance is Provenance.REPORTED:
            if not claim_source:
                # The prose may name its own source ("per the 10-Q").
                claim_source = inline_source(window)
            # An undated source is acceptable only when the claim says so; the
            # REPORTED branch below stamps source_date_unavailable in that case.
            if not has_source_binding(claim_source, as_of, source_date_unavailable=True):
                provenance = _downgrade_unsourced_reported(window)
                downgraded = True

        claim = QuantitativeClaim(
            value_text=value_text,
            provenance=provenance,
            raw_value=raw_value,
            unit=unit,
            ticker=ticker,
            metric=metric,
            polarity=_polarity(_window_text(text, m.start(), m.end(), before=45, after=15)),
        )

        if provenance is Provenance.REPORTED:
            claim.as_of = as_of
            claim.stale = stale
            claim.freshness_status = fstatus
            claim.source = claim_source
            if as_of is None:
                # Source exists but carries no date — say so explicitly rather
                # than letting the figure read as current fact.
                claim.stale = True
                claim.freshness_status = "source_date_unavailable"
                claim.source_date_unavailable = True
        elif provenance in (Provenance.SCENARIO, Provenance.ESTIMATED):
            claim.confidence = claim.confidence or "low"
            if not claim.assumptions:
                claim.assumptions = _nearby_assumption(window)
                claim.assumptions_inferred = bool(claim.assumptions)
            if claim.assumptions is None and downgraded:
                # A reclassified claim always has a stateable assumption: the
                # figure was framed as reported but nothing sources it, so it
                # stands on the forward-looking condition around it.
                claim.assumptions = (
                    "forward-looking figure with no sourced filing or evidence binding"
                )
                claim.assumptions_inferred = True
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
