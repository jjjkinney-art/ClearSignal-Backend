"""
Market regime tracker.

Classifies the current macro regime from recent event patterns.
Deterministic — no LLM calls. Provides PM-language regime narrative
for use in morning brief and synthesis prompts.

Regime state machine:
  Rate environment: higher_for_longer | cutting_cycle | pause | uncertain
  Risk appetite:    risk_on | risk_off | selective

Classification priority:
  1. Most recent high-reliability macro event
  2. Keyword pattern matching on recent headlines
  3. Fallback to "uncertain"/"selective"
"""
from __future__ import annotations

import datetime as _dt
import logging
from datetime import timezone
from typing import List, Optional

from ..schemas import MarketRegime
from .ingestion.normalized_event import EventCategory, NormalizedEvent

logger = logging.getLogger(__name__)

# ── Rate environment keyword classifiers ──────────────────────────────────────

_HIGHER_FOR_LONGER_SIGNALS = frozenset([
    "inflation above", "cpi above", "hot cpi", "above estimate",
    "no cuts", "pause", "higher for longer", "rates unchanged",
    "fed holds", "hawkish", "strong jobs", "beat payroll",
])

_CUTTING_CYCLE_SIGNALS = frozenset([
    "rate cut", "cuts rates", "dovish", "easing", "pivot",
    "weak cpi", "below estimate", "miss payroll", "recession risk",
    "growth concerns", "soft landing",
])

_RISK_ON_SIGNALS = frozenset([
    "strong gdp", "beat earnings", "raised guidance", "ipo surge",
    "credit spreads tight", "rally", "risk appetite", "growth optimism",
])

_RISK_OFF_SIGNALS = frozenset([
    "risk off", "safe haven", "treasury rally", "gold surge",
    "credit spreads widen", "volatility spike", "vix above",
    "recession", "market sell", "selloff",
])

# Rate environment → PM narrative templates
_RATE_NARRATIVES = {
    "higher_for_longer": "Rates staying higher for longer — rate-duration risk is real for long-dated multiples.",
    "cutting_cycle":     "Fed in cutting mode — duration is back as a tailwind, growth multiples can re-expand.",
    "pause":             "Fed on pause — rates stable but the path forward uncertain; market pricing in no more hikes.",
    "uncertain":         "Rate path unclear — macro uncertainty caps upside for rate-sensitive names.",
}

_RISK_NARRATIVES = {
    "risk_on":   "Risk appetite recovering — growth and cyclicals outperforming defensives.",
    "risk_off":  "Risk-off positioning — defensives, cash, and Treasuries attracting flows.",
    "selective": "Selective positioning — market distinguishing quality growth from rate-exposed names.",
}


def _classify_rate_environment(events: List[NormalizedEvent]) -> str:
    """Classify rate environment from recent macro events."""
    hl_score = 0
    cut_score = 0

    for event in events:
        if event.category != EventCategory.MACRO:
            continue
        text = (event.headline + " " + event.body).lower()
        for signal in _HIGHER_FOR_LONGER_SIGNALS:
            if signal in text:
                hl_score += (2 if event.source_reliability.value == "high" else 1)
        for signal in _CUTTING_CYCLE_SIGNALS:
            if signal in text:
                cut_score += (2 if event.source_reliability.value == "high" else 1)

    if hl_score == 0 and cut_score == 0:
        return "uncertain"
    if hl_score > cut_score * 1.5:
        return "higher_for_longer"
    if cut_score > hl_score * 1.5:
        return "cutting_cycle"
    return "pause"


def _classify_risk_appetite(events: List[NormalizedEvent]) -> str:
    """Classify risk appetite from recent events."""
    risk_on_score = 0
    risk_off_score = 0

    for event in events:
        text = (event.headline + " " + event.body).lower()
        for signal in _RISK_ON_SIGNALS:
            if signal in text:
                risk_on_score += 1
        for signal in _RISK_OFF_SIGNALS:
            if signal in text:
                risk_off_score += 1

    if risk_on_score == 0 and risk_off_score == 0:
        return "selective"
    if risk_on_score > risk_off_score * 1.3:
        return "risk_on"
    if risk_off_score > risk_on_score * 1.3:
        return "risk_off"
    return "selective"


def _build_key_factors(events: List[NormalizedEvent]) -> List[str]:
    """Extract 2-4 key macro factors from recent events."""
    factors = []
    seen_headlines: set = set()
    for event in sorted(events, key=lambda e: e.event_timestamp, reverse=True):
        if event.category != EventCategory.MACRO:
            continue
        if event.headline and event.headline not in seen_headlines:
            factors.append(event.headline[:80])
            seen_headlines.add(event.headline)
        if len(factors) >= 4:
            break
    return factors


def classify_regime(events: List[NormalizedEvent]) -> MarketRegime:
    """
    Classify current market regime from a list of recent events.

    Returns a MarketRegime with rate environment, risk appetite, and
    PM-language narrative.
    """
    try:
        rate_env = _classify_rate_environment(events)
        risk_app = _classify_risk_appetite(events)

        # Build composite narrative
        rate_narrative = _RATE_NARRATIVES.get(rate_env, _RATE_NARRATIVES["uncertain"])
        # Add risk appetite context
        if risk_app == "risk_off":
            narrative = rate_narrative.rstrip(".") + " — risk-off positioning adds a defensive overlay."
        elif risk_app == "risk_on":
            narrative = rate_narrative.rstrip(".") + " — but risk appetite is recovering in quality names."
        else:
            narrative = rate_narrative

        key_factors = _build_key_factors(events)

        return MarketRegime(
            rate_environment=rate_env,
            risk_appetite=risk_app,
            dominant_narrative=narrative,
            key_macro_factors=key_factors,
            last_updated=_dt.datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        logger.warning("classify_regime failed: %s", exc)
        return MarketRegime(dominant_narrative="Regime classification unavailable.")


# ── In-memory regime cache (refreshed per-process) ───────────────────────────
_current_regime: Optional[MarketRegime] = None


def update_regime(events: List[NormalizedEvent]) -> MarketRegime:
    """Update and cache the current regime from new events."""
    global _current_regime
    _current_regime = classify_regime(events)
    return _current_regime


def get_current_regime() -> MarketRegime:
    """Get the cached regime, or return uncertain if not yet classified."""
    if _current_regime is not None:
        return _current_regime
    return MarketRegime(
        dominant_narrative="Regime not yet classified — no events processed.",
    )
