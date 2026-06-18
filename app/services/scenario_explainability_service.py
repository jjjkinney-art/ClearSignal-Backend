"""
Scenario Explainability Service — Phase 14 · Slice 4.

Converts a (seed, propagation) pair into a human-readable explanation
envelope.  Every field is derived strictly from data already present in
the seed and propagation result; nothing is invented.

Output shape
------------
{
    "what_changed":           [str, ...],   # 1+ sentences: what assumption changed
    "why_it_matters":         [str, ...],   # 1+ sentences: structural consequence
    "transmission_mechanism": [str, ...],   # 1+ sentences: how it propagates
    "evidence":               [str, ...],   # references to verifiable substrates
    "invalidators":           [str, ...],   # conditions that would negate the scenario
    "scenario_type":          str,
    "disclaimer":             str,
}

Safety invariants (SP-6)
------------------------
    - No buy / sell / hold / overweight / underweight / recommend.
    - No target price, position size, or trade/execution language.
    - All sentences are observational — they describe structural connections,
      not outcomes, not actions, not advice.
    - validate_scenario_explanation enforces this before the envelope is used.
    - No DB imports.  No writes.  No session.

Core rule
---------
    A scenario that cannot explain itself cannot be stored later.
    validate_scenario_explanation must be called before any persistence step.
"""

from __future__ import annotations

from typing import List, Optional

# ---------------------------------------------------------------------------
# Scenario type constants
# ---------------------------------------------------------------------------

_COMPANY      = "company_scenario"
_MACRO        = "macro_scenario"
_SECTOR       = "sector_scenario"
_CATALYST     = "catalyst_scenario"
_FAILURE_MODE = "failure_mode_scenario"
_PORTFOLIO    = "portfolio_scenario"

_SUPPORTED_TYPES = frozenset({
    _COMPANY, _MACRO, _SECTOR, _CATALYST, _FAILURE_MODE, _PORTFOLIO,
})

# ---------------------------------------------------------------------------
# Disclaimer — fixed text; always included
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "This scenario explanation is generated from automated structural analysis "
    "and does not constitute financial advice, investment guidance, a prediction "
    "of future outcomes, or any suggestion to take action. "
    "All scenarios are conditional and carry inherent uncertainty."
)

# ---------------------------------------------------------------------------
# Banned phrases — scenario language must never cross into advice
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


def _safe_int(mapping: dict, key: str, default: int = 0) -> int:
    v = mapping.get(key, default)
    try:
        return int(float(v)) if v is not None else default
    except (TypeError, ValueError):
        return default


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _conf_label(v: float) -> str:
    if v >= 0.75:
        return "high"
    if v >= 0.50:
        return "moderate"
    if v >= 0.25:
        return "low"
    return "minimal"


def _has_banned(text: str) -> Optional[str]:
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
# build_what_changed
# ---------------------------------------------------------------------------

def build_what_changed(seed: dict, propagation: dict) -> List[str]:
    """Return 1–3 sentences describing what assumption conditionally changed."""
    stype     = seed.get("scenario_type", "")
    name      = seed.get("scenario_name", "Unnamed scenario")
    changed   = seed.get("changed_assumption", "")
    sentences: List[str] = []

    if changed:
        sentences.append(
            f"Scenario \"{name}\" is triggered by the following conditional change: "
            f"{changed}"
        )
    else:
        sentences.append(
            f"Scenario \"{name}\" describes a conditional structural change."
        )

    if stype == _COMPANY:
        ti     = seed.get("transmission_inputs", {}) or {}
        ticker = seed.get("ticker", "")
        ftype  = ti.get("forecast_type", "").replace("_", " ")
        hz     = ti.get("horizon", "")
        if ticker:
            sentences.append(
                f"The changed assumption applies to {ticker}"
                + (f" over a \"{hz}\" horizon" if hz else "")
                + (f" ({ftype} signal)" if ftype else "") + "."
            )

    elif stype == _MACRO:
        ti        = seed.get("transmission_inputs", {}) or {}
        macro_key = ti.get("macro_key", seed.get("entity_id", ""))
        direction = ti.get("direction", "shifting")
        hz        = ti.get("horizon", "")
        sentences.append(
            f"The macro condition \"{macro_key}\" is conditionally {direction}"
            + (f" over a \"{hz}\" horizon" if hz else "") + "."
        )

    elif stype == _SECTOR:
        ti         = seed.get("transmission_inputs", {}) or {}
        sector_key = ti.get("sector_key", seed.get("entity_id", ""))
        direction  = ti.get("direction", "shifting")
        sentences.append(
            f"The sector condition \"{sector_key}\" is conditionally {direction}."
        )

    elif stype == _CATALYST:
        ti        = seed.get("transmission_inputs", {}) or {}
        ticker    = seed.get("ticker", "")
        direction = ti.get("direction", "open")
        window    = ti.get("expected_window", "")
        sentences.append(
            f"A catalyst for {ticker} with direction \"{direction}\" is conditionally active"
            + (f" within window {window}" if window else "") + "."
        )

    elif stype == _FAILURE_MODE:
        ti     = seed.get("transmission_inputs", {}) or {}
        ticker = seed.get("ticker", "")
        stage  = ti.get("sequence_stage", "?")
        analog = ti.get("analog_id", "")
        sentences.append(
            f"{ticker} is conditionally following a failure-mode trajectory at stage {stage}"
            + (f" (analog: {analog})" if analog else "") + "."
        )

    elif stype == _PORTFOLIO:
        ti       = seed.get("transmission_inputs", {}) or {}
        port     = ti.get("portfolio_name", seed.get("entity_id", "portfolio"))
        n        = _safe_int(ti, "position_count")
        sentences.append(
            f"Portfolio \"{port}\" with {n} position(s) is conditionally affected by a "
            f"shared structural condition."
        )

    return sentences


# ---------------------------------------------------------------------------
# build_why_it_matters
# ---------------------------------------------------------------------------

def build_why_it_matters(seed: dict, propagation: dict) -> List[str]:
    """Return 1–3 sentences on the structural consequence of the changed assumption."""
    stype      = seed.get("scenario_type", "")
    ticker     = seed.get("ticker", "")
    direct     = propagation.get("direct_impacts", []) or []
    indirect   = propagation.get("indirect_impacts", []) or []
    depth      = propagation.get("propagation_depth", 0)
    confidence = propagation.get("impact_confidence", 0.0)
    uncertainty = propagation.get("impact_uncertainty", 0.0)
    sentences: List[str] = []

    n_direct   = len(direct)
    n_indirect = len(indirect)
    n_total    = n_direct + n_indirect

    sentences.append(
        f"This scenario structurally connects to {n_total} entit{'y' if n_total == 1 else 'ies'}: "
        f"{n_direct} direct and {n_indirect} indirect, across {depth} propagation depth(s). "
        f"Impact confidence is {_conf_label(confidence)} ({confidence:.2f}); "
        f"uncertainty is {uncertainty:.2f}."
    )

    if stype == _COMPANY and ticker:
        affected_ports = propagation.get("affected_portfolios", []) or []
        if affected_ports:
            sentences.append(
                f"{ticker} is held in {len(affected_ports)} portfolio(s), "
                f"which share this structural exposure."
            )
        if n_indirect > 0:
            sentences.append(
                f"The structural change in {ticker} propagates to {n_indirect} related "
                f"entit{'y' if n_indirect == 1 else 'ies'} via cross-exposure, "
                f"similarity, or portfolio co-ownership channels."
            )

    elif stype == _MACRO:
        ti        = seed.get("transmission_inputs", {}) or {}
        macro_key = ti.get("macro_key", seed.get("entity_id", ""))
        wc        = _safe_int(ti, "watchlist_count")
        sentences.append(
            f"The macro condition \"{macro_key}\" structurally affects "
            f"{n_indirect} watchlist-connected entit{'y' if n_indirect == 1 else 'ies'}"
            + (f" (watchlist size: {wc})" if wc > 0 else "") + "."
        )

    elif stype == _SECTOR:
        ti         = seed.get("transmission_inputs", {}) or {}
        sector_key = ti.get("sector_key", seed.get("entity_id", ""))
        sentences.append(
            f"The sector condition \"{sector_key}\" propagates to {n_indirect} "
            f"structurally exposed entit{'y' if n_indirect == 1 else 'ies'}."
        )

    elif stype == _CATALYST:
        ti         = seed.get("transmission_inputs", {}) or {}
        specificity = _safe_float(ti, "specificity", 0.0)
        sentences.append(
            f"The catalyst specificity is {specificity:.2f}; higher specificity "
            f"narrows the affected entity set."
        )

    elif stype == _FAILURE_MODE:
        ti        = seed.get("transmission_inputs", {}) or {}
        relevance = _safe_float(seed.get("impact_inputs", {}), "relevance_at_match", 0.0)
        sentences.append(
            f"The failure-mode match relevance is {relevance:.2f}, which governs "
            f"the structural weight assigned to co-exposed entities."
        )

    elif stype == _PORTFOLIO:
        tickers = (seed.get("transmission_inputs", {}) or {}).get("tickers", []) or []
        if tickers:
            t_str = ", ".join(tickers[:5])
            suffix = f" (…{len(tickers) - 5} more)" if len(tickers) > 5 else ""
            sentences.append(
                f"Portfolio positions ({t_str}{suffix}) each carry individual exposure "
                f"to the shared condition."
            )

    return sentences


# ---------------------------------------------------------------------------
# build_transmission_mechanism
# ---------------------------------------------------------------------------

def build_transmission_mechanism(seed: dict, propagation: dict) -> List[str]:
    """Return 1–4 sentences describing how the scenario propagates."""
    path      = propagation.get("transmission_path", []) or []
    indirect  = propagation.get("indirect_impacts", []) or []
    depth     = propagation.get("propagation_depth", 0)
    sentences: List[str] = []

    if not path:
        sentences.append(
            "No propagation path is available; this scenario is limited to the direct entity."
        )
        return sentences

    sentences.append(
        f"Propagation follows {len(path)} transmission step(s) across {depth} depth level(s)."
    )

    channels: dict = {}
    for step in path:
        ch = step.get("channel", "unknown").split(":")[0]
        channels[ch] = channels.get(ch, 0) + 1

    if channels:
        ch_parts = [f"{ch} ({n} step{'s' if n > 1 else ''})" for ch, n in sorted(channels.items())]
        sentences.append("Transmission channels: " + ", ".join(ch_parts) + ".")

    strength_dist: dict = {}
    for imp in indirect:
        s = imp.get("transmission_strength", "weak")
        strength_dist[s] = strength_dist.get(s, 0) + 1

    if strength_dist:
        s_parts = [f"{n} {s}" for s, n in sorted(strength_dist.items(), key=lambda x: (
            ["strong", "moderate", "weak"].index(x[0]) if x[0] in ["strong", "moderate", "weak"] else 9
        ))]
        sentences.append(
            "Indirect transmission strength distribution: " + ", ".join(s_parts) + "."
        )

    if depth >= 2:
        sentences.append(
            "Second-order propagation reaches entities that are not directly connected "
            "to the seed but share structural links with first-order entities."
        )

    return sentences


# ---------------------------------------------------------------------------
# build_evidence_summary
# ---------------------------------------------------------------------------

def build_evidence_summary(seed: dict, propagation: dict) -> List[str]:
    """Return a list of evidence references derived from the seed substrate."""
    stype          = seed.get("scenario_type", "")
    source_type    = seed.get("source_type", "")
    source_id      = seed.get("source_id", "")
    evidence_refs  = seed.get("evidence_refs", []) or []
    source_versions = seed.get("source_versions", {}) or {}
    sentences: List[str] = []

    sentences.append(f"Source: {source_type} (id={source_id}).")

    if evidence_refs:
        sentences.append(
            f"{len(evidence_refs)} evidence reference(s) are attached to this scenario."
        )

    if source_versions:
        ver_parts = [f"{k}={v}" for k, v in source_versions.items()]
        sentences.append("Source versions: " + ", ".join(ver_parts) + ".")

    if stype == _COMPANY:
        ci = seed.get("confidence_inputs", {}) or {}
        ev  = _safe_int(ci, "evidence_count")
        low = _safe_float(ci, "confidence_band_low", 0.0)
        hi  = _safe_float(ci, "confidence_band_high", 1.0)
        sentences.append(
            f"Forecast vector supported by {ev} evidence item(s); "
            f"confidence band: [{low:.2f}, {hi:.2f}]."
        )

    elif stype == _MACRO:
        ci = seed.get("confidence_inputs", {}) or {}
        ev = _safe_int(ci, "evidence_count")
        sentences.append(f"Macro forecast supported by {ev} evidence item(s).")

    elif stype == _SECTOR:
        ci  = seed.get("confidence_inputs", {}) or {}
        ev  = _safe_int(ci, "evidence_count")
        ct  = len((seed.get("transmission_inputs", {}) or {}).get("cross_tickers", []))
        sentences.append(
            f"Sector forecast supported by {ev} evidence item(s) and "
            f"{ct} cross-exposed ticker(s)."
        )

    elif stype == _CATALYST:
        ci       = seed.get("confidence_inputs", {}) or {}
        has_stmt = bool(ci.get("has_statement", False))
        has_win  = bool(ci.get("has_expected_window", False))
        sentences.append(
            f"Catalyst {'has' if has_stmt else 'lacks'} a supporting statement "
            f"and {'has' if has_win else 'lacks'} a defined expected window."
        )

    elif stype == _FAILURE_MODE:
        ci      = seed.get("confidence_inputs", {}) or {}
        has_ev  = bool(ci.get("has_stage_evidence", False))
        stage   = _safe_int(ci, "sequence_stage")
        rel     = _safe_float(ci, "relevance_at_match", 0.0)
        sentences.append(
            f"Failure-mode at stage {stage} {'has' if has_ev else 'lacks'} stage-level evidence; "
            f"relevance at match: {rel:.2f}."
        )

    elif stype == _PORTFOLIO:
        ci       = seed.get("confidence_inputs", {}) or {}
        has_pos  = bool(ci.get("has_positions", False))
        n        = _safe_int(ci, "position_count")
        is_def   = bool(ci.get("is_default", False))
        sentences.append(
            f"Portfolio {'has' if has_pos else 'lacks'} recorded positions; "
            f"{n} active position(s); "
            f"{'default' if is_def else 'custom'} portfolio."
        )

    return sentences


# ---------------------------------------------------------------------------
# build_invalidators
# ---------------------------------------------------------------------------

def build_invalidators(seed: dict, propagation: dict) -> List[str]:
    """Return 1–4 conditions that would structurally negate this scenario."""
    stype     = seed.get("scenario_type", "")
    sentences: List[str] = []

    sentences.append(
        "This scenario is invalidated if the changed assumption does not materialise."
    )

    if stype == _COMPANY:
        ti     = seed.get("transmission_inputs", {}) or {}
        ftype  = ti.get("forecast_type", "").replace("_", " ")
        hz     = ti.get("horizon", "")
        ticker = seed.get("ticker", "")
        if hz:
            sentences.append(
                f"The scenario is structurally negated if the \"{hz}\" forecast horizon "
                f"closes without confirmation of the {ftype or 'signal'} for {ticker}."
            )
        sentences.append(
            f"Cross-exposure paths are invalidated if the structural link data for "
            f"{ticker} changes materially before the scenario window closes."
        )

    elif stype == _MACRO:
        ti        = seed.get("transmission_inputs", {}) or {}
        macro_key = ti.get("macro_key", seed.get("entity_id", ""))
        sentences.append(
            f"The macro condition \"{macro_key}\" is negated if the macro signal "
            f"reverts, is revised downward, or a contrary macro development dominates."
        )
        sentences.append(
            "Affected-ticker paths are negated if watchlist composition changes substantially."
        )

    elif stype == _SECTOR:
        ti         = seed.get("transmission_inputs", {}) or {}
        sector_key = ti.get("sector_key", seed.get("entity_id", ""))
        direction  = ti.get("direction", "shifting")
        sentences.append(
            f"The sector scenario is negated if the {sector_key} sector does not "
            f"trend {direction}, or if a dominant idiosyncratic factor decouples "
            f"individual companies from the sector signal."
        )

    elif stype == _CATALYST:
        ti        = seed.get("transmission_inputs", {}) or {}
        window    = ti.get("expected_window", "")
        ticker    = seed.get("ticker", "")
        if window:
            sentences.append(
                f"The catalyst scenario is negated if the expected window \"{window}\" "
                f"passes without a confirming event for {ticker}."
            )
        sentences.append(
            f"The catalyst is also negated if it is closed, withdrawn, or superseded "
            f"by a contrary signal for {ticker}."
        )

    elif stype == _FAILURE_MODE:
        ti     = seed.get("transmission_inputs", {}) or {}
        stage  = ti.get("sequence_stage", "?")
        ticker = seed.get("ticker", "")
        sentences.append(
            f"The failure-mode scenario is negated if {ticker} diverges from the "
            f"analog trajectory at or before stage {stage}, or if a recovery signal "
            f"with higher relevance emerges."
        )

    elif stype == _PORTFOLIO:
        ti   = seed.get("transmission_inputs", {}) or {}
        port = ti.get("portfolio_name", "the portfolio")
        sentences.append(
            f"The portfolio scenario is negated if \"{port}\" composition changes "
            f"materially, or if the shared condition is resolved at the macro or "
            f"sector level before it affects position-level entities."
        )

    return sentences


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

def build_scenario_explanation(seed: dict, propagation: dict) -> dict:
    """Assemble the full explanation envelope for one scenario.

    The returned dict is self-contained.  Call validate_scenario_explanation
    before any persistence step.
    """
    return {
        "what_changed":           build_what_changed(seed, propagation),
        "why_it_matters":         build_why_it_matters(seed, propagation),
        "transmission_mechanism": build_transmission_mechanism(seed, propagation),
        "evidence":               build_evidence_summary(seed, propagation),
        "invalidators":           build_invalidators(seed, propagation),
        "scenario_type":          seed.get("scenario_type", ""),
        "disclaimer":             _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_REQUIRED_SECTIONS = (
    "what_changed",
    "why_it_matters",
    "transmission_mechanism",
    "evidence",
    "invalidators",
    "disclaimer",
)


def validate_scenario_explanation(explanation: dict) -> tuple:
    """Validate *explanation*.

    Returns (True, None) when valid.
    Returns (False, reason: str) for the first violation found.

    Checks (in order):
        1. Required sections present and non-empty
        2. scenario_type is one of the six supported types
        3. No banned advisory language in any text field
    """
    # 1 — required sections
    for field in _REQUIRED_SECTIONS:
        value = explanation.get(field)
        if value is None:
            return False, f"Missing required field: {field!r}"
        if isinstance(value, list) and not value:
            return False, f"Required list field is empty: {field!r}"
        if isinstance(value, str) and not value.strip():
            return False, f"Required string field is blank: {field!r}"

    # 2 — scenario_type
    stype = explanation.get("scenario_type", "")
    if stype not in _SUPPORTED_TYPES:
        return False, f"Unsupported scenario_type: {stype!r}"

    # 3 — banned language scan across all text fields
    for field in ("what_changed", "why_it_matters", "transmission_mechanism",
                  "evidence", "invalidators"):
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
