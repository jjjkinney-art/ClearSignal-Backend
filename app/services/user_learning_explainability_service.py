"""
User Learning Explainability Service — Phase 15 · Slice 4.

Builds and validates the four mandatory explanation fields for every learned
preference (SP-7g).  This is a pure-computation module: no session, no DB
access, no writes anywhere.

The four mandatory fields (spec §8.1)
--------------------------------------
  1. why_we_believe_this  — the inference rule that fired; names the behavior
                            pattern observed (e.g. "opened NVDA analysis 14×
                            in 30d")
  2. evidence             — the contributing signal events backing the belief
  3. signal_strength      — "strong" / "moderate" / "tentative" label derived
                            from confidence and evidence_count
  4. falsifier            — what observable evidence would overturn the belief
                            (required for SP-7e anti-fabrication gate)

A preference missing or malformed on any of these four is rejected by
validate_preference_explanation and must never reach status='active'.

Output shape
------------
{
    "why_we_believe_this": [str, ...],   # 1+ sentences
    "evidence":            [str, ...],   # 1+ references to supporting events
    "signal_strength":     str,          # "strong" | "moderate" | "tentative"
    "falsifier":           [str, ...],   # 1+ conditions that would overturn this
    "dimension":           str,          # the preference dimension
    "disclaimer":          str,          # fixed SP-7f safety text (always present)
}

Safety invariants (SP-7)
-------------------------
  SP-7f: no buy/sell/hold/recommend/target_price/position_size/trade/execution
         language in any generated string.
  SP-7g: validate_preference_explanation blocks any explanation missing a
         required field or carrying banned language.
  No session, no DB import, no write of any kind.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Supported preference dimensions (spec §6.1)
# ---------------------------------------------------------------------------

SUPPORTED_DIMENSIONS: frozenset = frozenset({
    "sector_interest",
    "company_interest",
    "theme_interest",
    "preferred_horizon",
    "preferred_signal_type",
    "ignored_signal_type",
    "portfolio_sensitivity",
})

# ---------------------------------------------------------------------------
# Signal strength thresholds
# ---------------------------------------------------------------------------

_STRONG_CONFIDENCE_THRESHOLD:   float = 0.70
_MODERATE_CONFIDENCE_THRESHOLD: float = 0.40

# Minimum evidence counts considered meaningful per dimension
_MIN_EVIDENCE: Dict[str, int] = {
    "sector_interest":      5,
    "company_interest":     5,
    "theme_interest":       5,
    "preferred_horizon":    3,
    "preferred_signal_type": 3,
    "ignored_signal_type":  6,   # higher — negative preferences require repetition
    "portfolio_sensitivity": 4,
}

# ---------------------------------------------------------------------------
# Disclaimer — fixed SP-7f safety text; always included
# ---------------------------------------------------------------------------

_DISCLAIMER: str = (
    "This explanation is derived from your observed interaction patterns and "
    "reflects ordering and prominence preferences only. It does not constitute "
    "financial advice, an assessment of any security, or guidance on any "
    "course of action."
)

# ---------------------------------------------------------------------------
# Banned phrases — SP-7f; observational language must never cross into advice
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

# Required output fields
_REQUIRED_FIELDS: Tuple[str, ...] = (
    "why_we_believe_this",
    "evidence",
    "signal_strength",
    "falsifier",
    "disclaimer",
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _has_banned(text: str) -> Optional[str]:
    """Return the first banned phrase found in *text* (case-insensitive), else None."""
    lower = text.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lower:
            return phrase
    return None


def _scan_list(items: List[str]) -> Optional[str]:
    """Return the first banned phrase found anywhere in *items*, else None."""
    for item in items:
        hit = _has_banned(str(item))
        if hit:
            return hit
    return None


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _entity_label(dimension: str, entity_key: str) -> str:
    """Return a human-readable label for the entity in the context of a dimension."""
    key = str(entity_key) if entity_key else "unknown"
    if dimension == "preferred_horizon":
        return f"{key}-term"
    if dimension in ("preferred_signal_type", "ignored_signal_type"):
        return key.replace("_", " ")
    return key


# ---------------------------------------------------------------------------
# Field builders
# ---------------------------------------------------------------------------

def build_why_we_believe_this(
    preference_data: Dict[str, Any],
    events: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """Build the 'why we believe this' explanation sentences.

    Derives observational sentences from the preference fields and
    contributing events. Language is always descriptive (past behavior
    observed), never prescriptive.

    Returns a list of 1+ non-empty strings. Returns a single-item list
    with an insufficient-signal note when evidence_count is below the
    minimum for the dimension (insufficient_samples analogue).
    """
    dimension    = str(preference_data.get("dimension", ""))
    entity_key   = str(preference_data.get("entity_key", ""))
    affinity     = _safe_float(preference_data.get("affinity", 0.0))
    evidence_count = _safe_int(preference_data.get("evidence_count", 0))
    label        = _entity_label(dimension, entity_key)
    min_ev       = _MIN_EVIDENCE.get(dimension, 5)

    if evidence_count < min_ev:
        return [
            f"Insufficient signal to characterize {label!r} interest "
            f"(observed {evidence_count} event(s); minimum {min_ev} required)."
        ]

    polarity_desc = "toward" if affinity >= 0 else "away from"
    direction     = "positive" if affinity >= 0 else "negative"

    sentences: List[str] = []

    if dimension == "sector_interest":
        sentences.append(
            f"You have engaged with {label!r} sector content {evidence_count} time(s), "
            f"indicating a {direction} affinity."
        )
    elif dimension == "company_interest":
        sentences.append(
            f"You have opened or revisited analyses for {label!r} {evidence_count} time(s), "
            f"indicating sustained interest in this name."
        )
    elif dimension == "theme_interest":
        sentences.append(
            f"Interactions across your sessions show repeated engagement with the "
            f"{label!r} theme ({evidence_count} event(s))."
        )
    elif dimension == "preferred_horizon":
        sentences.append(
            f"You have toggled to or engaged with {label!r} horizon content "
            f"{evidence_count} time(s), suggesting a preference for this time frame."
        )
    elif dimension == "preferred_signal_type":
        sentences.append(
            f"You have engaged with {label!r} signals {evidence_count} time(s) "
            f"across multiple sessions, indicating a preference for this signal type."
        )
    elif dimension == "ignored_signal_type":
        sentences.append(
            f"You have dismissed or muted {label!r} signals {evidence_count} time(s) "
            f"across multiple distinct sessions."
        )
        sentences.append(
            f"Repeated dismissals across sessions are required before this preference "
            f"is recorded (a single session does not constitute a lasting signal)."
        )
    elif dimension == "portfolio_sensitivity":
        sentences.append(
            f"You have viewed or drilled into the {label!r} portfolio position "
            f"{evidence_count} time(s), indicating heightened attention to this name."
        )
    else:
        sentences.append(
            f"Observed {evidence_count} interaction(s) {polarity_desc} {label!r}."
        )

    if events:
        pos_count = sum(1 for e in events if e.get("polarity") == "positive")
        neg_count = sum(1 for e in events if e.get("polarity") == "negative")
        if pos_count and neg_count:
            sentences.append(
                f"Mixed signal: {pos_count} positive and {neg_count} negative "
                f"interaction(s) observed."
            )

    return sentences


def build_evidence_summary(
    events: Optional[List[Dict[str, Any]]],
    *,
    max_items: int = 10,
) -> List[str]:
    """Build the evidence reference list from contributing signal events.

    Each item is an observational reference string.
    Returns at least one item (an 'insufficient evidence' note when the list
    is empty), ensuring the field is never blank.
    """
    if not events:
        return ["No contributing events available for this preference."]

    lines: List[str] = []
    for ev in events[:max_items]:
        signal_type = str(ev.get("signal_type", "unknown_event"))
        entity_key  = str(ev.get("entity_key", ""))
        polarity    = str(ev.get("polarity", "neutral"))
        surface     = str(ev.get("source_surface", ""))

        parts = [f"{signal_type} ({polarity})"]
        if entity_key:
            parts.append(f"on {entity_key!r}")
        if surface:
            parts.append(f"via {surface!r}")
        lines.append(" ".join(parts))

    if len(events) > max_items:
        lines.append(f"…and {len(events) - max_items} additional event(s).")

    return lines


def build_signal_strength(
    confidence: float,
    evidence_count: int,
    dimension: str = "",
) -> str:
    """Return 'strong', 'moderate', or 'tentative' based on confidence and count.

    Mirrors the Phase 14 calibration confidence vocabulary so downstream
    consumers can apply a uniform interpretation across phases.
    """
    min_ev = _MIN_EVIDENCE.get(dimension, 5)
    if evidence_count < min_ev:
        return "tentative"
    if confidence >= _STRONG_CONFIDENCE_THRESHOLD:
        return "strong"
    if confidence >= _MODERATE_CONFIDENCE_THRESHOLD:
        return "moderate"
    return "tentative"


def build_falsifier(
    preference_data: Dict[str, Any],
) -> List[str]:
    """Build the falsifier condition list for a preference.

    Each item is an observable condition that — if met — would overturn the
    belief. At least one item is always returned (SP-7e: every belief is
    falsifiable; an unfalsifiable preference is treated as fabrication).

    Falsifiers are dimension-specific and phrased as behavioral thresholds,
    not market outcomes.
    """
    dimension  = str(preference_data.get("dimension", ""))
    entity_key = str(preference_data.get("entity_key", ""))
    affinity   = _safe_float(preference_data.get("affinity", 0.0))
    label      = _entity_label(dimension, entity_key)

    conditions: List[str] = []

    if dimension == "sector_interest":
        conditions.append(
            f"30 or more consecutive days without any interaction involving the "
            f"{label!r} sector."
        )
        if affinity > 0:
            conditions.append(
                f"Three or more dismissals of {label!r} sector content in distinct sessions."
            )
    elif dimension == "company_interest":
        conditions.append(
            f"30 or more days without opening an analysis for {label!r}."
        )
        if affinity > 0:
            conditions.append(
                f"Removal of {label!r} from the watchlist."
            )
    elif dimension == "theme_interest":
        conditions.append(
            f"30 or more days without engaging with any {label!r} theme content."
        )
    elif dimension == "preferred_horizon":
        conditions.append(
            f"Absence of {label!r} horizon engagement for 60 or more days."
        )
        conditions.append(
            f"Three or more explicit switches away from the {label!r} horizon."
        )
    elif dimension == "preferred_signal_type":
        conditions.append(
            f"90 or more days without engaging with any {label!r} signal."
        )
    elif dimension == "ignored_signal_type":
        conditions.append(
            f"A positive interaction with a {label!r} signal (opening, acting on, "
            f"or expanding a {label!r} item). One positive interaction resets the "
            f"negative accumulation."
        )
        conditions.append(
            f"Absence of any {label!r} dismissal for 90 or more days (decay)."
        )
    elif dimension == "portfolio_sensitivity":
        conditions.append(
            f"90 or more days without viewing the {label!r} portfolio position."
        )
    else:
        conditions.append(
            f"Sustained absence of interactions with {label!r} over the dimension's "
            f"decay half-life."
        )

    return conditions


# ---------------------------------------------------------------------------
# Envelope builder
# ---------------------------------------------------------------------------

def build_preference_explanation(
    preference_data: Dict[str, Any],
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble the full four-field explanation envelope for one learned preference.

    The returned dict is self-contained. Call validate_preference_explanation
    before persisting (storing a preference without first validating its
    explanation is an SP-7g violation).

    preference_data keys used:
      dimension, entity_key, affinity, confidence, evidence_count

    events: optional list of contributing signal event dicts
      (signal_type, polarity, entity_key, source_surface)
    """
    dimension  = str(preference_data.get("dimension", ""))
    confidence = _safe_float(preference_data.get("confidence", 0.0))
    ev_count   = _safe_int(preference_data.get("evidence_count", 0))

    return {
        "why_we_believe_this": build_why_we_believe_this(preference_data, events),
        "evidence":            build_evidence_summary(events),
        "signal_strength":     build_signal_strength(confidence, ev_count, dimension),
        "falsifier":           build_falsifier(preference_data),
        "dimension":           dimension,
        "disclaimer":          _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Validation gate
# ---------------------------------------------------------------------------

def validate_preference_explanation(explanation: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate *explanation*.

    Returns (True, None) when all checks pass.
    Returns (False, reason) for the first violation found.

    Checks (in order):
      1. Required fields present and non-empty (SP-7g)
      2. dimension is one of the seven supported values
      3. signal_strength is one of the three supported labels
      4. No banned advisory language in any text field (SP-7f)
      5. disclaimer is present and non-blank
    """
    # 1 — required fields present and non-empty
    for field in _REQUIRED_FIELDS:
        value = explanation.get(field)
        if value is None:
            return False, f"Missing required field: {field!r}"
        if isinstance(value, list) and not value:
            return False, f"Required list field is empty: {field!r}"
        if isinstance(value, str) and not value.strip():
            return False, f"Required string field is blank: {field!r}"

    # 2 — dimension must be one of the seven supported values
    dimension = explanation.get("dimension", "")
    if dimension not in SUPPORTED_DIMENSIONS:
        return False, f"Unsupported dimension: {dimension!r}"

    # 3 — signal_strength must be a recognised label
    strength = explanation.get("signal_strength", "")
    if strength not in ("strong", "moderate", "tentative"):
        return False, f"Invalid signal_strength: {strength!r}"

    # 4 — banned language scan across all generated text content
    text_list_fields = ("why_we_believe_this", "evidence", "falsifier")
    for field in text_list_fields:
        value = explanation.get(field, [])
        if isinstance(value, list):
            hit = _scan_list(value)
            if hit:
                return False, f"Banned phrase {hit!r} found in field {field!r}"
        elif isinstance(value, str):
            hit = _has_banned(value)
            if hit:
                return False, f"Banned phrase {hit!r} found in field {field!r}"

    # 5 — disclaimer must not contain banned phrases either
    disclaimer = explanation.get("disclaimer", "")
    hit = _has_banned(disclaimer)
    if hit:
        return False, f"Banned phrase {hit!r} found in disclaimer"

    return True, None
