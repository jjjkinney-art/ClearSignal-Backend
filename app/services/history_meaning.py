"""
Shared meaning-native history abstractions.

This module defines the PRIMARY output types of the history/evidence layer.
All downstream modules (monitoring, alerts, learning) must consume these
objects as their primary history input instead of rebuilding history
logic from raw counts.

HIERARCHY
---------
HistoricalMeaning         — top-level cross-domain meaning object
PriceHistoryMeaning       — price-domain meaning
FinancialHistoryMeaning   — financial metrics meaning
EventHistoryMeaning       — event pattern meaning
SignalHistoryMeaning      — signal/alert activity meaning

RULE: raw stats (avg, volatility, counts, ratios) are computed INTERNALLY
by the evidence layer and used only to SUPPORT meaning inference.
The HistoricalMeaning objects are the authoritative outputs.
Downstream modules must NOT re-derive meaning from raw counts.
"""

from __future__ import annotations

from typing import Optional, Dict, Any


# ===========================================================================
# DOMAIN MEANING OBJECTS
# ===========================================================================

class PriceHistoryMeaning:
    """What the price history means, not what the numbers are.

    Fields
    ------
    situation_archetype  : "rising_steady" | "falling_steady" | "volatile_rising" |
                           "volatile_falling" | "stagnant" | "recovering" | "unknown"
    pattern_stability    : "stable" | "shifting" | "volatile"
    pattern_direction    : "rising" | "falling" | "stable"
    escalation_likelihood: "high" | "medium" | "low"
    usual_consequence    : "thesis_change" | "reanalysis" | "alert" | "noise"
    meaning_summary      : one-sentence human-readable summary
    supporting_stats     : dict of numeric stats (supporting only, never drivers)
    """
    def __init__(
        self,
        situation_archetype:   str,
        pattern_stability:     str,
        pattern_direction:     str,
        escalation_likelihood: str,
        usual_consequence:     str,
        meaning_summary:       str,
        supporting_stats:      Optional[Dict[str, Any]] = None,
    ) -> None:
        self.situation_archetype   = situation_archetype
        self.pattern_stability     = pattern_stability
        self.pattern_direction     = pattern_direction
        self.escalation_likelihood = escalation_likelihood
        self.usual_consequence     = usual_consequence
        self.meaning_summary       = meaning_summary
        self.supporting_stats      = supporting_stats or {}


class FinancialHistoryMeaning:
    """What the financial metric history means.

    Fields
    ------
    situation_archetype  : "growth_accelerating" | "growth_decelerating" | "deteriorating" |
                           "recovering" | "stagnant" | "mixed" | "unknown"
    pattern_stability    : "stable" | "shifting" | "volatile"
    dominant_direction   : "improving" | "deteriorating" | "stable" | "mixed"
    escalation_likelihood: "high" | "medium" | "low"
    usual_consequence    : "thesis_change" | "reanalysis" | "alert" | "noise"
    meaning_summary      : one-sentence human-readable summary
    supporting_stats     : dict of numeric stats (supporting only)
    """
    def __init__(
        self,
        situation_archetype:   str,
        pattern_stability:     str,
        dominant_direction:    str,
        escalation_likelihood: str,
        usual_consequence:     str,
        meaning_summary:       str,
        supporting_stats:      Optional[Dict[str, Any]] = None,
    ) -> None:
        self.situation_archetype   = situation_archetype
        self.pattern_stability     = pattern_stability
        self.dominant_direction    = dominant_direction
        self.escalation_likelihood = escalation_likelihood
        self.usual_consequence     = usual_consequence
        self.meaning_summary       = meaning_summary
        self.supporting_stats      = supporting_stats or {}


class EventHistoryMeaning:
    """What the event pattern history means.

    Fields
    ------
    situation_archetype  : "cluster_forming" | "isolated_events" | "escalating_pattern" |
                           "fading_pattern" | "diverse_activity" | "concentrated_activity" | "unknown"
    pattern_stability    : "stable" | "increasing" | "decreasing"
    escalation_likelihood: "high" | "medium" | "low"
    usual_consequence    : "thesis_change" | "reanalysis" | "alert" | "noise"
    meaning_summary      : one-sentence human-readable summary
    supporting_stats     : dict of numeric stats (supporting only)
    """
    def __init__(
        self,
        situation_archetype:   str,
        pattern_stability:     str,
        escalation_likelihood: str,
        usual_consequence:     str,
        meaning_summary:       str,
        supporting_stats:      Optional[Dict[str, Any]] = None,
    ) -> None:
        self.situation_archetype   = situation_archetype
        self.pattern_stability     = pattern_stability
        self.escalation_likelihood = escalation_likelihood
        self.usual_consequence     = usual_consequence
        self.meaning_summary       = meaning_summary
        self.supporting_stats      = supporting_stats or {}


class SignalHistoryMeaning:
    """What the signal and alert activity history means.

    Fields
    ------
    situation_archetype  : "escalating_alerts" | "fading_alerts" | "steady_monitoring" |
                           "thesis_pressure" | "noise_accumulation" | "unknown"
    activity_direction   : "increasing" | "decreasing" | "stable"
    escalation_likelihood: "high" | "medium" | "low"
    usual_consequence    : "thesis_change" | "reanalysis" | "alert" | "noise"
    meaning_summary      : one-sentence human-readable summary
    supporting_stats     : dict of numeric stats (supporting only)
    """
    def __init__(
        self,
        situation_archetype:   str,
        activity_direction:    str,
        escalation_likelihood: str,
        usual_consequence:     str,
        meaning_summary:       str,
        supporting_stats:      Optional[Dict[str, Any]] = None,
    ) -> None:
        self.situation_archetype   = situation_archetype
        self.activity_direction    = activity_direction
        self.escalation_likelihood = escalation_likelihood
        self.usual_consequence     = usual_consequence
        self.meaning_summary       = meaning_summary
        self.supporting_stats      = supporting_stats or {}


# ===========================================================================
# TOP-LEVEL AGGREGATED MEANING OBJECT
# ===========================================================================

class HistoricalMeaning:
    """Aggregated cross-domain historical meaning object.

    This is the PRIMARY output of the history/evidence layer.
    All downstream modules (monitoring, alerts, learning) consume this
    object as their primary history input.

    Fields
    ------
    situation_archetype  : highest-salience archetype across all domains
    historical_pattern   : human description of the dominant historical pattern
    pattern_stability    : overall stability of the historical pattern
    pattern_direction    : direction of the dominant pattern
    escalation_likelihood: overall escalation likelihood
    usual_consequence    : most common consequence type historically
    meaning_summary      : cross-domain narrative
    price                : PriceHistoryMeaning (may be None)
    financial            : FinancialHistoryMeaning (may be None)
    event                : EventHistoryMeaning (may be None)
    signal               : SignalHistoryMeaning (may be None)
    supporting_stats     : raw stats dict (supporting only)
    """
    def __init__(
        self,
        situation_archetype:   str,
        historical_pattern:    str,
        pattern_stability:     str,
        pattern_direction:     str,
        escalation_likelihood: str,
        usual_consequence:     str,
        meaning_summary:       str,
        price:                 Optional[PriceHistoryMeaning]     = None,
        financial:             Optional[FinancialHistoryMeaning]  = None,
        event:                 Optional[EventHistoryMeaning]      = None,
        signal:                Optional[SignalHistoryMeaning]     = None,
        supporting_stats:      Optional[Dict[str, Any]]          = None,
    ) -> None:
        self.situation_archetype   = situation_archetype
        self.historical_pattern    = historical_pattern
        self.pattern_stability     = pattern_stability
        self.pattern_direction     = pattern_direction
        self.escalation_likelihood = escalation_likelihood
        self.usual_consequence     = usual_consequence
        self.meaning_summary       = meaning_summary
        self.price                 = price
        self.financial             = financial
        self.event                 = event
        self.signal                = signal
        self.supporting_stats      = supporting_stats or {}


# ===========================================================================
# MEANING INFERENCE FUNCTIONS
# All raw stats flow IN as arguments; meaning objects flow OUT.
# These functions are called by the evidence layer FIRST, before
# any interpretive text is written to the context.
# ===========================================================================

def _infer_price_meaning(
    trend_direction:    str,
    trend_strength:     str,
    volatility_regime:  str,
    pattern_behavior:   str,
    price_event_corr:   Optional[str],
    typical_consequence: str,
    supporting_stats:   Dict[str, Any],
) -> PriceHistoryMeaning:
    """Infer PriceHistoryMeaning from supporting stats.

    The archetype and escalation_likelihood are DERIVED HERE, not imported
    from the stats dict.  The stats are inputs to this reasoning, not outputs.
    """
    # Situation archetype from the combination of volatility + direction
    if volatility_regime == "volatile" and trend_direction == "rising":
        archetype     = "volatile_rising"
        escalation    = "high"
    elif volatility_regime == "volatile" and trend_direction == "falling":
        archetype     = "volatile_falling"
        escalation    = "high"
    elif trend_direction == "rising" and trend_strength in ("strong", "moderate"):
        archetype     = "rising_steady"
        escalation    = "medium"
    elif trend_direction == "falling" and trend_strength in ("strong", "moderate"):
        archetype     = "falling_steady"
        escalation    = "medium"
    elif trend_direction == "stable":
        archetype     = "stagnant"
        escalation    = "low"
    else:
        archetype     = "unknown"
        escalation    = "low"

    # Pattern stability
    if volatility_regime == "volatile":
        stability = "volatile"
    elif volatility_regime == "shifting":
        stability = "shifting"
    else:
        stability = "stable"

    # Meaning summary
    corr_clause = (
        f" with {price_event_corr} correlation between price and event frequency"
        if price_event_corr and price_event_corr != "neutral"
        else ""
    )
    meaning_summary = (
        f"Price shows {trend_strength} {trend_direction} trend in a {volatility_regime} regime"
        f"{corr_clause}. Historically, this pattern has been associated with "
        f"{typical_consequence.replace('_', ' ')} outcomes."
    )

    return PriceHistoryMeaning(
        situation_archetype   = archetype,
        pattern_stability     = stability,
        pattern_direction     = trend_direction,
        escalation_likelihood = escalation,
        usual_consequence     = typical_consequence,
        meaning_summary       = meaning_summary,
        supporting_stats      = supporting_stats,
    )


def _infer_financial_meaning(
    metric_trends:       Dict[str, str],   # {"revenue": "upward", "net_income": "downward", ...}
    typical_consequence: str,
    supporting_stats:    Dict[str, Any],
) -> FinancialHistoryMeaning:
    """Infer FinancialHistoryMeaning from metric trend patterns."""
    if not metric_trends:
        return FinancialHistoryMeaning(
            situation_archetype   = "unknown",
            pattern_stability     = "stable",
            dominant_direction    = "stable",
            escalation_likelihood = "low",
            usual_consequence     = typical_consequence,
            meaning_summary       = "No financial trend data available.",
            supporting_stats      = supporting_stats,
        )

    upward   = sum(1 for v in metric_trends.values() if v == "upward")
    downward = sum(1 for v in metric_trends.values() if v == "downward")
    total    = len(metric_trends)

    if upward == total:
        archetype   = "growth_accelerating"
        direction   = "improving"
        escalation  = "medium"
    elif downward == total:
        archetype   = "deteriorating"
        direction   = "deteriorating"
        escalation  = "high"
    elif upward > downward:
        archetype   = "growth_decelerating" if downward > 0 else "growth_accelerating"
        direction   = "improving"
        escalation  = "medium"
    elif downward > upward:
        archetype   = "recovering" if upward > 0 else "deteriorating"
        direction   = "deteriorating"
        escalation  = "medium"
    else:
        archetype   = "mixed"
        direction   = "mixed"
        escalation  = "low"

    parts = [f"{k.replace('_',' ')} {v}" for k, v in metric_trends.items()]
    trend_str = "; ".join(parts)
    meaning_summary = (
        f"Financial metrics show {direction} trend ({trend_str}). "
        f"Historically, such patterns have been associated with "
        f"{typical_consequence.replace('_', ' ')} outcomes."
    )

    return FinancialHistoryMeaning(
        situation_archetype   = archetype,
        pattern_stability     = "stable" if escalation == "low" else "shifting",
        dominant_direction    = direction,
        escalation_likelihood = escalation,
        usual_consequence     = typical_consequence,
        meaning_summary       = meaning_summary,
        supporting_stats      = supporting_stats,
    )


def _infer_event_meaning(
    event_freq_trend:      str,
    repeated_patterns:     str,
    event_diversity:       Optional[str],
    dominant_event_type:   Optional[str],
    typical_consequence:   str,
    supporting_stats:      Dict[str, Any],
) -> EventHistoryMeaning:
    """Infer EventHistoryMeaning from event pattern context."""
    # Archetype from frequency trend + repetition + diversity
    if event_freq_trend == "increasing" and repeated_patterns == "common":
        archetype   = "cluster_forming"
        escalation  = "high"
    elif event_freq_trend == "increasing":
        archetype   = "escalating_pattern"
        escalation  = "medium"
    elif event_freq_trend == "decreasing" and repeated_patterns == "rare":
        archetype   = "fading_pattern"
        escalation  = "low"
    elif event_diversity == "concentrated":
        archetype   = "concentrated_activity"
        escalation  = "medium"
    elif event_diversity == "diverse":
        archetype   = "diverse_activity"
        escalation  = "low"
    else:
        archetype   = "isolated_events"
        escalation  = "low"

    dominant_clause = f" dominated by {dominant_event_type}" if dominant_event_type else ""
    meaning_summary = (
        f"Event pattern is {archetype.replace('_', ' ')}"
        f"{dominant_clause}, frequency {event_freq_trend}. "
        f"Historically associated with {typical_consequence.replace('_', ' ')} outcomes."
    )

    return EventHistoryMeaning(
        situation_archetype   = archetype,
        pattern_stability     = event_freq_trend,
        escalation_likelihood = escalation,
        usual_consequence     = typical_consequence,
        meaning_summary       = meaning_summary,
        supporting_stats      = supporting_stats,
    )


def _infer_signal_meaning(
    signal_freq_change:  str,
    alert_freq_trend:    str,
    typical_consequence: str,
    supporting_stats:    Dict[str, Any],
) -> SignalHistoryMeaning:
    """Infer SignalHistoryMeaning from signal and alert activity patterns."""
    if signal_freq_change == "increasing" and alert_freq_trend == "increasing":
        archetype   = "escalating_alerts"
        direction   = "increasing"
        escalation  = "high"
    elif signal_freq_change == "decreasing" and alert_freq_trend == "decreasing":
        archetype   = "fading_alerts"
        direction   = "decreasing"
        escalation  = "low"
    elif typical_consequence == "thesis_change":
        archetype   = "thesis_pressure"
        direction   = signal_freq_change
        escalation  = "high"
    elif signal_freq_change == "stable" and alert_freq_trend == "stable":
        archetype   = "steady_monitoring"
        direction   = "stable"
        escalation  = "low"
    else:
        archetype   = "noise_accumulation"
        direction   = signal_freq_change
        escalation  = "low"

    meaning_summary = (
        f"Signal activity is {archetype.replace('_', ' ')} "
        f"(signals {signal_freq_change}, alerts {alert_freq_trend}). "
        f"Historically associated with {typical_consequence.replace('_', ' ')} outcomes."
    )

    return SignalHistoryMeaning(
        situation_archetype   = archetype,
        activity_direction    = direction,
        escalation_likelihood = escalation,
        usual_consequence     = typical_consequence,
        meaning_summary       = meaning_summary,
        supporting_stats      = supporting_stats,
    )


def build_historical_meaning(
    price_meaning:     Optional[PriceHistoryMeaning],
    financial_meaning: Optional[FinancialHistoryMeaning],
    event_meaning:     Optional[EventHistoryMeaning],
    signal_meaning:    Optional[SignalHistoryMeaning],
    supporting_stats:  Optional[Dict[str, Any]] = None,
) -> HistoricalMeaning:
    """Aggregate domain meanings into a single HistoricalMeaning object.

    The top-level archetype, escalation_likelihood, and usual_consequence
    are synthesised from the domain meanings using a priority ladder:
        1. signal meaning (most directly actionable)
        2. price meaning (most market-relevant)
        3. event meaning
        4. financial meaning (slowest-moving)
    """
    # Priority ladder for top-level fields
    domains = [m for m in [signal_meaning, price_meaning, event_meaning, financial_meaning] if m is not None]

    if not domains:
        return HistoricalMeaning(
            situation_archetype   = "unknown",
            historical_pattern    = "No historical data available.",
            pattern_stability     = "stable",
            pattern_direction     = "stable",
            escalation_likelihood = "low",
            usual_consequence     = "noise",
            meaning_summary       = "No historical meaning available.",
            price                 = None,
            financial             = None,
            event                 = None,
            signal                = None,
            supporting_stats      = supporting_stats or {},
        )

    # Top-level archetype: highest-escalation domain wins
    _ESC_ORDER = {"high": 3, "medium": 2, "low": 1}
    primary = max(domains, key=lambda d: _ESC_ORDER.get(d.escalation_likelihood, 0))

    situation_archetype   = primary.situation_archetype
    escalation_likelihood = primary.escalation_likelihood
    usual_consequence     = primary.usual_consequence

    # Pattern stability and direction: from price if available, else first domain
    if price_meaning:
        pattern_stability = price_meaning.pattern_stability
        pattern_direction = price_meaning.pattern_direction
    else:
        pattern_stability = getattr(domains[0], "pattern_stability", "stable")
        pattern_direction = getattr(
            domains[0],
            "pattern_direction",
            getattr(domains[0], "dominant_direction", getattr(domains[0], "activity_direction", "stable")),
        )

    # Historical pattern narrative
    parts = []
    if price_meaning:
        parts.append(f"price: {price_meaning.situation_archetype}")
    if financial_meaning:
        parts.append(f"financials: {financial_meaning.situation_archetype}")
    if event_meaning:
        parts.append(f"events: {event_meaning.situation_archetype}")
    if signal_meaning:
        parts.append(f"signals: {signal_meaning.situation_archetype}")
    historical_pattern = "; ".join(parts) if parts else "no pattern data"

    # Cross-domain meaning summary
    summaries = [d.meaning_summary for d in domains if d.meaning_summary]
    meaning_summary = " | ".join(summaries[:2]) if summaries else "No historical meaning available."

    return HistoricalMeaning(
        situation_archetype   = situation_archetype,
        historical_pattern    = historical_pattern,
        pattern_stability     = pattern_stability,
        pattern_direction     = pattern_direction,
        escalation_likelihood = escalation_likelihood,
        usual_consequence     = usual_consequence,
        meaning_summary       = meaning_summary,
        price                 = price_meaning,
        financial             = financial_meaning,
        event                 = event_meaning,
        signal                = signal_meaning,
        supporting_stats      = supporting_stats or {},
    )


def get_historical_meaning_from_context(ctx: Any) -> Optional[HistoricalMeaning]:
    """Extract the HistoricalMeaning object from a GroundingContext.

    Returns None if no meaning has been attached (e.g. when evidence was
    not built through the history pipeline).

    This is the canonical accessor for downstream modules.  They should
    call this function rather than re-deriving meaning from raw stats.
    """
    return getattr(ctx, "historical_meaning", None)
