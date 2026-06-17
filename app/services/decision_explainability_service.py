"""
Decision Explainability Service — Phase 13 · Slice 4.

Converts a (candidate, ranking_output) pair into a human-readable
explanation envelope.  Every field is derived strictly from the data
already present in the candidate and ranking_output; nothing is invented.

Output shape
------------
{
    "why_important":  [str, ...],   # 1+ sentences: what makes this signal significant
    "why_now":        [str, ...],   # 1+ sentences: why it is time-sensitive
    "evidence":       [str, ...],   # references to verifiable substrates
    "deprioritizers": [str, ...],   # honest uncertainty / confidence caveats
    "candidate_type": str,
    "decision_score": float,
    "disclaimer":     str,
}

Safety invariants (SP-5)
------------------------
    - No buy / sell / hold / overweight / underweight / recommend.
    - No target price, position size, or trade/execution language.
    - All sentences are observational — they describe signal state, not action.
    - validate_decision_explanation enforces this before the envelope is used.
    - No DB imports, no writes, no session.
"""

from __future__ import annotations

from typing import List, Optional

# ---------------------------------------------------------------------------
# Candidate type constants (import-safe copies — no circular dependency)
# ---------------------------------------------------------------------------

_FORECAST            = "forecast_candidate"
_RISK                = "risk_candidate"
_CATALYST            = "catalyst_candidate"
_WATCHLIST           = "watchlist_candidate"
_PORTFOLIO           = "portfolio_exposure_candidate"
_DELIVERY            = "delivery_transition_candidate"
_SIMILARITY          = "similarity_candidate"

_SUPPORTED_TYPES = frozenset({
    _FORECAST, _RISK, _CATALYST, _WATCHLIST,
    _PORTFOLIO, _DELIVERY, _SIMILARITY,
})

# ---------------------------------------------------------------------------
# Disclaimer — fixed text; always included
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "This explanation is generated from automated signal analysis and does not "
    "constitute financial advice, investment guidance, or a representation "
    "of future outcomes. All signals carry inherent uncertainty."
)

# ---------------------------------------------------------------------------
# Banned phrases — observational language must never cross into advice
# ---------------------------------------------------------------------------

_BANNED_PHRASES: List[str] = [
    "buy",
    "sell",
    "hold",
    "overweight",
    "underweight",
    "recommend",
    "target price",
    "position size",
    "take a position",
    "enter a trade",
    "exit a trade",
    "place an order",
    "execute",
    "short",
    "long position",
    "go long",
    "go short",
    "open a position",
    "close a position",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_str(mapping: dict, key: str, default: str = "") -> str:
    v = mapping.get(key, default)
    return str(v) if v is not None else default


def _safe_float(mapping: dict, key: str, default: float = 0.0) -> float:
    v = mapping.get(key, default)
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _score_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.50:
        return "moderate"
    if score >= 0.25:
        return "low"
    return "minimal"


def _has_banned(text: str) -> Optional[str]:
    """Return the first matching banned phrase found in *text* (case-insensitive), or None."""
    lower = text.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lower:
            return phrase
    return None


def _scan_list(items: List[str]) -> Optional[str]:
    for item in items:
        hit = _has_banned(item)
        if hit:
            return hit
    return None


# ---------------------------------------------------------------------------
# Per-section builders — why_important
# ---------------------------------------------------------------------------

def build_why_important(candidate: dict, ranking_output: dict) -> List[str]:
    """Return 1–3 sentences explaining why this signal warrants attention."""
    ctype = candidate.get("candidate_type", "")
    ticker = _safe_str(candidate, "ticker", "this entity")
    headline = _safe_str(candidate, "headline")
    decision_score = _safe_float(ranking_output, "decision_score")
    attention_score = _safe_float(ranking_output, "attention_score")
    impact_score = _safe_float(ranking_output, "impact_score")
    sentences: List[str] = []

    if ctype == _FORECAST:
        ai = candidate.get("attention_inputs", {}) or {}
        ii = candidate.get("impact_inputs", {}) or {}
        direction = _safe_str(ai, "direction", "uncertain")
        ftype = _safe_str(ai, "forecast_type", "")
        p_pos = _safe_float(ii, "p_positive", 0.0)
        p_neg = _safe_float(ii, "p_negative", 0.0)
        dominant = "positive" if p_pos >= p_neg else "negative"
        dominant_p = max(p_pos, p_neg)
        sentences.append(
            f"A forecast signal for {ticker} shows a {_pct(dominant_p)} probability "
            f"of a {dominant} outcome, with a directional stance of \"{direction}\"."
        )
        if ftype:
            sentences.append(f"The signal type is \"{ftype}\".")
        if impact_score >= 0.60:
            sentences.append(
                f"The directional probability is {_score_label(impact_score)}, "
                f"indicating meaningful signal strength."
            )

    elif ctype == _RISK:
        ai = candidate.get("attention_inputs", {}) or {}
        ii = candidate.get("impact_inputs", {}) or {}
        stage = _safe_float(ai, "stage", 1.0)
        relevance = _safe_float(ii, "relevance_at_match", 0.0)
        analog_id = _safe_str(ai, "analog_id", "an analog pattern")
        sentences.append(
            f"A risk pattern matching {analog_id} has been detected for {ticker} "
            f"at stage {int(stage)} of 5, with a relevance score of {relevance:.2f}."
        )
        if attention_score >= 0.60:
            sentences.append(
                f"The stage progression places this risk at a {_score_label(attention_score)} "
                f"attention level."
            )

    elif ctype == _CATALYST:
        ai = candidate.get("attention_inputs", {}) or {}
        ii = candidate.get("impact_inputs", {}) or {}
        direction = _safe_str(ai, "direction", "unspecified")
        window = _safe_str(ai, "expected_window", "")
        specificity = _safe_float(ii, "specificity", 0.0)
        sentences.append(
            f"A catalyst signal for {ticker} has been identified with direction "
            f"\"{direction}\" and a specificity of {specificity:.2f}."
        )
        if window:
            sentences.append(f"The expected catalyst window is {window}.")

    elif ctype == _WATCHLIST:
        ai = candidate.get("attention_inputs", {}) or {}
        company_name = _safe_str(ai, "company_name", ticker)
        added_days = _safe_float(ai, "added_days_ago", 0.0)
        sentences.append(
            f"{company_name} ({ticker}) is on the active watchlist, "
            f"added {int(added_days)} day(s) ago."
        )
        if headline:
            sentences.append(headline)

    elif ctype == _PORTFOLIO:
        ai = candidate.get("attention_inputs", {}) or {}
        ii = candidate.get("impact_inputs", {}) or {}
        mc = _safe_str(ai, "membership_class", "watchlist")
        weight = ii.get("weight")
        portfolio_name = _safe_str(ii, "portfolio_name", "a portfolio")
        sentences.append(
            f"{ticker} is held in {portfolio_name} as a \"{mc}\" position."
        )
        if weight is not None:
            sentences.append(
                f"The current portfolio weight is {_pct(float(weight))}, "
                f"contributing to a {_score_label(impact_score)} impact score."
            )

    elif ctype == _DELIVERY:
        ai = candidate.get("attention_inputs", {}) or {}
        ui = candidate.get("urgency_inputs", {}) or {}
        status = _safe_str(ai, "status", "unknown")
        channel = _safe_str(ai, "channel", "")
        severity = _safe_str(ui, "canonical_severity", "")
        sentences.append(
            f"A delivery transition for {ticker} has status \"{status}\""
            + (f" on channel \"{channel}\"" if channel else "") + "."
        )
        if severity:
            sentences.append(f"The canonical severity is \"{severity}\".")

    elif ctype == _SIMILARITY:
        ai = candidate.get("attention_inputs", {}) or {}
        ii = candidate.get("impact_inputs", {}) or {}
        candidate_key = _safe_str(ii, "candidate_key", "a related entity")
        score = _safe_float(ai, "score", 0.0)
        sentences.append(
            f"{ticker} shows a similarity score of {score:.2f} relative to "
            f"{candidate_key}, placing it at a {_score_label(attention_score)} "
            f"attention level."
        )

    else:
        sentences.append(
            f"Signal detected for {ticker} with a composite score of "
            f"{decision_score:.3f} ({_score_label(decision_score)} priority)."
        )

    return sentences


# ---------------------------------------------------------------------------
# Per-section builders — why_now
# ---------------------------------------------------------------------------

def build_why_now(candidate: dict, ranking_output: dict) -> List[str]:
    """Return 1–3 sentences on why this signal is time-sensitive now."""
    ctype = candidate.get("candidate_type", "")
    ticker = _safe_str(candidate, "ticker", "this entity")
    urgency_score = _safe_float(ranking_output, "urgency_score")
    sentences: List[str] = []

    if ctype == _FORECAST:
        ui = candidate.get("urgency_inputs", {}) or {}
        horizon_days = _safe_float(ui, "horizon_days", 90.0)
        horizon_label = _safe_str(ui, "horizon", "")
        sentences.append(
            f"The forecast horizon for {ticker} is {int(horizon_days)} day(s)"
            + (f" ({horizon_label})" if horizon_label else "") + "."
        )
        sentences.append(
            f"Urgency is rated {_score_label(urgency_score)} based on the time remaining "
            f"until the forecast window closes."
        )

    elif ctype == _RISK:
        ui = candidate.get("urgency_inputs", {}) or {}
        matched_days = _safe_float(ui, "matched_days_ago", 0.0)
        stage = _safe_float(ui, "sequence_stage", 1.0)
        sentences.append(
            f"The risk pattern for {ticker} was matched {int(matched_days)} day(s) ago "
            f"and is currently at stage {int(stage)} of 5."
        )
        sentences.append(
            f"The combined stage-and-recency urgency is {_score_label(urgency_score)}."
        )

    elif ctype == _CATALYST:
        ui = candidate.get("urgency_inputs", {}) or {}
        created_days = _safe_float(ui, "created_days_ago", 0.0)
        window = _safe_str(ui, "expected_window", "")
        sentences.append(
            f"The catalyst for {ticker} was identified {int(created_days)} day(s) ago."
        )
        if window:
            sentences.append(f"The expected window is {window}.")
        sentences.append(f"Signal urgency is {_score_label(urgency_score)}.")

    elif ctype == _WATCHLIST:
        ui = candidate.get("urgency_inputs", {}) or {}
        added_days = _safe_float(ui, "added_days_ago", 0.0)
        sentences.append(
            f"{ticker} was added to the watchlist {int(added_days)} day(s) ago."
        )
        sentences.append(
            f"Watchlist items added recently are prioritised higher; "
            f"current urgency is {_score_label(urgency_score)}."
        )

    elif ctype == _PORTFOLIO:
        ui = candidate.get("urgency_inputs", {}) or {}
        mc = _safe_str(ui, "membership_class", "watchlist")
        sentences.append(
            f"Portfolio exposure for {ticker} is classified as \"{mc}\", "
            f"driving a {_score_label(urgency_score)} urgency score."
        )

    elif ctype == _DELIVERY:
        ui = candidate.get("urgency_inputs", {}) or {}
        status = _safe_str(ui, "status", "unknown")
        attempts = _safe_float(ui, "attempts", 0.0)
        sentences.append(
            f"Delivery for {ticker} is \"{status}\" after {int(attempts)} attempt(s)."
        )
        sentences.append(
            f"The delivery urgency is {_score_label(urgency_score)}."
        )

    elif ctype == _SIMILARITY:
        ui = candidate.get("urgency_inputs", {}) or {}
        rank = _safe_float(ui, "rank", 10.0)
        built_days = _safe_float(ui, "built_days_ago", 0.0)
        sentences.append(
            f"The similarity edge for {ticker} ranks {int(rank)} and was computed "
            f"{int(built_days)} day(s) ago."
        )
        sentences.append(
            f"Recency and rank combine to a {_score_label(urgency_score)} urgency."
        )

    else:
        sentences.append(
            f"Signal urgency for {ticker} is {_score_label(urgency_score)}."
        )

    return sentences


# ---------------------------------------------------------------------------
# Per-section builders — evidence
# ---------------------------------------------------------------------------

def build_evidence_summary(candidate: dict, ranking_output: dict) -> List[str]:
    """Return a list of evidence references derived from the candidate substrate.

    Sentences reference only data already present — no inference beyond
    what the upstream services recorded.
    """
    ctype = candidate.get("candidate_type", "")
    ticker = _safe_str(candidate, "ticker", "this entity")
    evidence_refs = candidate.get("evidence_refs", []) or []
    source_type = _safe_str(candidate, "source_type")
    source_id = _safe_str(candidate, "source_id")
    source_versions = candidate.get("source_versions", {}) or {}
    sentences: List[str] = []

    sentences.append(
        f"Source: {source_type} (id={source_id})."
    )

    if evidence_refs:
        sentences.append(
            f"{len(evidence_refs)} evidence reference(s) are attached to this signal."
        )

    if source_versions:
        version_parts = [f"{k}={v}" for k, v in source_versions.items()]
        sentences.append(
            "Source versions: " + ", ".join(version_parts) + "."
        )

    if ctype == _FORECAST:
        ci = candidate.get("confidence_inputs", {}) or {}
        ev_count = _safe_float(ci, "evidence_count", 0.0)
        cb_low = _safe_float(ci, "confidence_band_low", 0.0)
        cb_high = _safe_float(ci, "confidence_band_high", 1.0)
        sentences.append(
            f"Forecast is supported by {int(ev_count)} evidence item(s); "
            f"confidence band: [{cb_low:.2f}, {cb_high:.2f}]."
        )

    elif ctype == _RISK:
        ci = candidate.get("confidence_inputs", {}) or {}
        has_label = bool(ci.get("has_analog_label", False))
        has_ev = bool(ci.get("has_stage_evidence", False))
        sentences.append(
            f"Risk pattern {'has' if has_label else 'lacks'} an analog label "
            f"and {'has' if has_ev else 'lacks'} stage-level evidence."
        )

    elif ctype == _CATALYST:
        ci = candidate.get("confidence_inputs", {}) or {}
        has_stmt = bool(ci.get("has_statement", False))
        has_win = bool(ci.get("has_expected_window", False))
        sentences.append(
            f"Catalyst {'has' if has_stmt else 'lacks'} a supporting statement "
            f"and {'has' if has_win else 'lacks'} a defined expected window."
        )

    elif ctype == _SIMILARITY:
        ci = candidate.get("confidence_inputs", {}) or {}
        has_contrib = bool(ci.get("has_contributions", False))
        has_dis = bool(ci.get("has_disanalogy", False))
        sentences.append(
            f"Similarity edge {'includes' if has_contrib else 'lacks'} feature contributions "
            f"and {'notes' if has_dis else 'omits'} disanalogies."
        )

    elif ctype == _PORTFOLIO:
        ci = candidate.get("confidence_inputs", {}) or {}
        has_w = bool(ci.get("has_weight", False))
        has_cb = bool(ci.get("has_cost_basis", False))
        sentences.append(
            f"Portfolio record {'includes' if has_w else 'lacks'} weight data "
            f"and {'includes' if has_cb else 'lacks'} cost-basis data."
        )

    elif ctype == _DELIVERY:
        ci = candidate.get("confidence_inputs", {}) or {}
        has_sev = bool(ci.get("has_severity", False))
        has_ref = bool(ci.get("has_artifact_ref", False))
        sentences.append(
            f"Delivery record {'has' if has_sev else 'lacks'} a severity classification "
            f"and {'has' if has_ref else 'lacks'} an artifact reference."
        )

    return sentences


# ---------------------------------------------------------------------------
# Per-section builders — deprioritizers
# ---------------------------------------------------------------------------

def build_deprioritizers(candidate: dict, ranking_output: dict) -> List[str]:
    """Return 1–4 sentences on confidence caveats and uncertainty factors.

    These are honest discounts — they explain why the decision_score may be
    lower than attention + urgency + impact alone would suggest.
    """
    ctype = candidate.get("candidate_type", "")
    ticker = _safe_str(candidate, "ticker", "this entity")
    confidence = _safe_float(ranking_output, "confidence_multiplier")
    discount = _safe_float(ranking_output, "uncertainty_discount")
    exposure = _safe_float(ranking_output, "exposure_multiplier")
    sentences: List[str] = []

    # Confidence caveat
    if confidence < 0.60:
        sentences.append(
            f"Confidence multiplier is {confidence:.2f} — limited evidence or a wide "
            f"confidence band reduces the weight of this signal."
        )
    else:
        sentences.append(
            f"Confidence multiplier is {confidence:.2f}, reflecting adequate evidence quality."
        )

    # Uncertainty caveat
    if discount < 0.80:
        sentences.append(
            f"Uncertainty discount is {discount:.2f} — significant spread or neutral "
            f"probability mass dampens the score."
        )
    else:
        sentences.append(
            f"Uncertainty discount is {discount:.2f}, indicating low residual uncertainty."
        )

    # Exposure note (portfolio-specific amplifier or neutral)
    if ctype == _PORTFOLIO and exposure != 1.0:
        if exposure > 1.0:
            sentences.append(
                f"Portfolio exposure multiplier is {exposure:.2f} — the position size "
                f"amplifies the composite score."
            )
        else:
            sentences.append(
                f"Portfolio exposure multiplier is {exposure:.2f} — limited position data "
                f"reduces the composite score."
            )

    # Type-specific caveats
    if ctype == _WATCHLIST:
        sentences.append(
            f"{ticker} is on the watchlist without attached forecast or risk signals; "
            f"the impact baseline is neutral."
        )

    elif ctype == _SIMILARITY:
        uu = candidate.get("uncertainty_inputs", {}) or {}
        inv_score = _safe_float(uu, "inverse_score", 0.50)
        if inv_score > 0.30:
            sentences.append(
                f"Similarity inverse score is {inv_score:.2f}; edges with lower "
                f"similarity scores carry higher uncertainty."
            )

    elif ctype == _FORECAST:
        ii = candidate.get("impact_inputs", {}) or {}
        p_neu = _safe_float(ii, "p_neutral", 0.0)
        if p_neu > 0.25:
            sentences.append(
                f"The forecast neutral probability is {_pct(p_neu)}, which increases "
                f"outcome uncertainty."
            )

    elif ctype == _RISK:
        ui = candidate.get("urgency_inputs", {}) or {}
        matched_days = _safe_float(ui, "matched_days_ago", 0.0)
        if matched_days > 30:
            sentences.append(
                f"The risk pattern was matched {int(matched_days)} day(s) ago; "
                f"older matches carry higher staleness uncertainty."
            )

    return sentences


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

def build_decision_explanation(
    candidate: dict,
    ranking_output: dict,
) -> dict:
    """Assemble the full explanation envelope for one decision candidate.

    The returned dict is self-contained: every field needed for storage or
    display is present.  Call validate_decision_explanation before persisting.
    """
    return {
        "why_important":  build_why_important(candidate, ranking_output),
        "why_now":        build_why_now(candidate, ranking_output),
        "evidence":       build_evidence_summary(candidate, ranking_output),
        "deprioritizers": build_deprioritizers(candidate, ranking_output),
        "candidate_type": candidate.get("candidate_type", ""),
        "decision_score": _safe_float(ranking_output, "decision_score"),
        "disclaimer":     _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = ("why_important", "why_now", "evidence", "deprioritizers", "disclaimer")


def validate_decision_explanation(explanation: dict) -> tuple[bool, Optional[str]]:
    """Validate *explanation*.

    Returns (True, None) when valid.
    Returns (False, reason: str) for the first violation found.

    Checks (in order):
        1. Required fields present and non-empty
        2. candidate_type is one of the seven supported types
        3. No banned advisory language in any text field
    """
    # 1 — required fields
    for field in _REQUIRED_FIELDS:
        value = explanation.get(field)
        if value is None:
            return False, f"Missing required field: {field!r}"
        if isinstance(value, list) and not value:
            return False, f"Required list field is empty: {field!r}"
        if isinstance(value, str) and not value.strip():
            return False, f"Required string field is blank: {field!r}"

    # 2 — candidate_type
    ctype = explanation.get("candidate_type", "")
    if ctype not in _SUPPORTED_TYPES:
        return False, f"Unsupported candidate_type: {ctype!r}"

    # 3 — banned language scan across all text content
    for field in ("why_important", "why_now", "evidence", "deprioritizers"):
        value = explanation.get(field, [])
        if isinstance(value, list):
            hit = _scan_list(value)
            if hit:
                return False, f"Banned phrase {hit!r} found in field {field!r}"
        elif isinstance(value, str):
            hit = _has_banned(value)
            if hit:
                return False, f"Banned phrase {hit!r} found in field {field!r}"

    # Disclaimer text itself must not contain banned phrases
    disclaimer = explanation.get("disclaimer", "")
    hit = _has_banned(disclaimer)
    if hit:
        return False, f"Banned phrase {hit!r} found in disclaimer"

    return True, None
