"""
Event → Thesis Comparison Pipeline.

Deterministically assesses how a new market event (earnings, macro data,
news) impacts an existing investment thesis snapshot.

Core function: assess_event_impact(event, snapshot) → EventImpactAssessment

Design principles:
- No LLM calls — all logic deterministic
- PM-native language in all outputs
- "Already priced in?" as a first-class concept
- Impact types are mutually exclusive, ordered by severity
- Materiality threshold gates all outputs

Impact type hierarchy (most severe first):
  thesis_broke      — event fundamentally breaks the investment case
  debate_shift      — event changes what the market is debating
  weakens_thesis    — event confirms the bear case pathway
  strengthens_thesis — event confirms the bull case pathway
  market_repriced   — valuation/sentiment changed, operating thesis intact
  regime_change     — macro regime shift with broad implications
  priced_in         — expected event, already reflected in thesis/price
  noise             — not material enough to matter
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from ..schemas import EventImpactAssessment, ThesisSnapshot
from .ingestion.normalized_event import EventCategory, NormalizedEvent
from .timeline_store import JsonFileTimelineStore, TimelineEntry, default_store

logger = logging.getLogger(__name__)

# ── Materiality thresholds ────────────────────────────────────────────────────

_NOISE_THRESHOLD    = 0.15   # below this → noise, ignored
_MONITOR_THRESHOLD  = 0.30   # 0.15-0.30 → monitor only
_ALERT_THRESHOLD    = 0.50   # 0.30-0.50 → medium alert
_HIGH_THRESHOLD     = 0.70   # 0.50-0.70 → high alert
_CRITICAL_THRESHOLD = 0.85   # ≥0.85 → critical

# ── PM implication templates ──────────────────────────────────────────────────
# Templates keyed by (impact_type, event_tag, thesis_direction)
# thesis_direction: "bull" | "bear" | "neutral"

_IMPLICATION_TEMPLATES = {
    # Thesis-breaking events
    ("thesis_broke", "miss", "bull"):
        "The bull case just got harder to defend — the earnings miss removes the execution floor.",
    ("thesis_broke", "lowered", "bull"):
        "Guidance cut breaks the revenue trajectory assumption — the thesis needs to be rebuilt.",
    ("thesis_broke", "miss", "bear"):
        "The bear case just got confirmed — worse than the bear scenario.",
    # Strengthening events
    ("strengthens_thesis", "beat", "bull"):
        "The execution check cleared — burden shifts back to the multiple.",
    ("strengthens_thesis", "raised", "bull"):
        "Raised guidance extends the earnings runway — the thesis now has a longer runway to play out.",
    ("strengthens_thesis", "beat", "neutral"):
        "Beat confirms the operational narrative — debate now shifts to what's already priced.",
    # Weakening events
    ("weakens_thesis", "miss", "bull"):
        "Miss adds friction to the bull case without breaking it — the setup is less one-sided now.",
    ("weakens_thesis", "lowered", "bull"):
        "Lowered guidance compresses the upside scenario — the trade becomes more timing-sensitive.",
    # Debate shifts
    ("debate_shift", "", ""):
        "The market is no longer debating the prior question — the fulcrum variable just changed.",
    # Market repricing
    ("market_repriced", "", ""):
        "The multiple compressed on macro, not fundamentals — the operating thesis is intact but the setup is less attractive.",
    # Priced in
    ("priced_in", "beat", "bull"):
        "Beat confirmed consensus — the incremental is in the guidance, not the quarter.",
    ("priced_in", "raised", "bull"):
        "Raised guidance was the expected outcome — the question is whether the new bar is achievable.",
    # Regime change
    ("regime_change", "", ""):
        "The macro backdrop shifted — rate duration risk is now real for long-dated multiples.",
    # Fallback
    ("noise", "", ""):
        "",
}


def _get_template(impact_type: str, primary_tag: str, thesis_dir: str) -> str:
    """Find the best matching PM implication template."""
    # Try exact match first
    key = (impact_type, primary_tag, thesis_dir)
    if key in _IMPLICATION_TEMPLATES:
        return _IMPLICATION_TEMPLATES[key]
    # Try with empty tag
    key2 = (impact_type, "", thesis_dir)
    if key2 in _IMPLICATION_TEMPLATES:
        return _IMPLICATION_TEMPLATES[key2]
    # Try with empty thesis_dir
    key3 = (impact_type, primary_tag, "")
    if key3 in _IMPLICATION_TEMPLATES:
        return _IMPLICATION_TEMPLATES[key3]
    # Final fallback
    return _IMPLICATION_TEMPLATES.get((impact_type, "", ""), "")


def _score_relevance(event: NormalizedEvent, snapshot: ThesisSnapshot) -> float:
    """
    Returns 0.0-1.0 how relevant this event is to the ticker's thesis.
    """
    try:
        base = 0.0
        bonus = 0.0

        if event.ticker is not None and event.ticker.upper() == snapshot.ticker.upper():
            base = 0.8
            if event.category == EventCategory.EARNINGS:
                bonus += 0.2
        elif event.ticker is None:
            # Macro event — check macro_sensitivity
            macro_sens = getattr(snapshot, "macro_sensitivity", None) or ""
            if macro_sens:
                base = 0.5
            else:
                base = 0.3
            # Macro category is broadly relevant
            if event.category == EventCategory.MACRO:
                base = max(base, 0.4)
        else:
            # Different ticker
            base = 0.1

        if event.category == EventCategory.MACRO:
            base = max(base, 0.4)

        # Dominant driver keyword match
        dominant_driver = getattr(snapshot, "dominant_driver", "") or ""
        if dominant_driver and event.headline:
            driver_words = set(dominant_driver.lower().split())
            headline_lower = event.headline.lower()
            if any(w in headline_lower for w in driver_words if len(w) > 3):
                bonus += 0.1

        return min(base + bonus, 1.0)
    except Exception as exc:
        logger.warning("_score_relevance failed: %s", exc)
        return 0.0


def _check_priced_in(
    event: NormalizedEvent,
    snapshot: ThesisSnapshot,
) -> Tuple[bool, str]:
    """
    Returns (is_priced_in: bool, reasoning: str).
    """
    try:
        tags = [t.lower() for t in (event.tags or [])]
        confidence = getattr(snapshot, "confidence_score", 0.0) or 0.0
        core_debate = getattr(snapshot, "core_market_debate", "") or ""

        # 1. Beat + high confidence → priced in
        if "beat" in tags and confidence >= 0.72:
            return (
                True,
                "Beat confirmed the bull thesis — high-conviction snapshot already assumed execution delivery.",
            )

        # 2. Raised guidance + "guidance" in core_market_debate → priced in
        if "raised" in tags and "guidance" in core_debate.lower():
            return (
                True,
                "Raised guidance was the expected outcome the market was pricing — the debate now moves to the next catalyst.",
            )

        # 3. Miss + high confidence → NOT priced in
        if "miss" in tags and confidence >= 0.72:
            return (
                False,
                "High-conviction thesis just hit an execution miss — the market was not pricing this.",
            )

        # 4. Miss + low confidence → priced in (bear already reflected)
        if "miss" in tags and confidence < 0.55:
            return (
                True,
                "Low-conviction thesis already reflected execution uncertainty — the miss confirms the bear scenario.",
            )

        # 5. Non-market-moving → priced in
        if not event.is_market_moving:
            return (
                True,
                "Non-market-moving event — likely reflected in existing price action.",
            )

        # Default
        return (False, "")
    except Exception as exc:
        logger.warning("_check_priced_in failed: %s", exc)
        return (False, "")


def _score_materiality(
    event: NormalizedEvent,
    snapshot: ThesisSnapshot,
    relevance: float,
) -> float:
    """Returns 0.0-1.0 materiality score."""
    try:
        score = relevance * 0.4  # base from relevance

        # Event quality factors
        reliability_val = event.source_reliability.value if event.source_reliability else "medium"
        if reliability_val == "high":
            score += 0.20
        elif reliability_val == "medium":
            score += 0.10

        if event.is_market_moving:
            score += 0.20
        if event.category == EventCategory.EARNINGS:
            score += 0.15
        if event.category == EventCategory.GUIDANCE:
            score += 0.12

        # Tag-based materiality
        tags = [t.lower() for t in (event.tags or [])]
        if "beat" in tags or "miss" in tags:
            score += 0.10
        if "raised" in tags or "lowered" in tags:
            score += 0.12
        if "merger" in tags or "regulatory" in tags:
            score += 0.15

        return min(score, 1.0)
    except Exception as exc:
        logger.warning("_score_materiality failed: %s", exc)
        return 0.0


def _determine_thesis_direction(snapshot: ThesisSnapshot) -> str:
    """Returns 'bull' | 'bear' | 'neutral' based on snapshot state."""
    try:
        drift = getattr(snapshot, "drift_state", "") or ""
        confidence = getattr(snapshot, "confidence_score", 0.0) or 0.0

        if drift in ("strengthening", "inflecting"):
            return "bull"
        if drift in ("weakening", "shifting", "breaking"):
            return "bear"
        if confidence >= 0.65:
            return "bull"
        return "neutral"
    except Exception as exc:
        logger.warning("_determine_thesis_direction failed: %s", exc)
        return "neutral"


def _classify_impact_type(
    event: NormalizedEvent,
    snapshot: ThesisSnapshot,
    priced_in: bool,
    mat_score: float,
) -> str:
    """Classify impact type. Evaluation order matches severity hierarchy."""
    try:
        tags = [t.lower() for t in (event.tags or [])]
        confidence = getattr(snapshot, "confidence_score", 0.0) or 0.0
        drift = getattr(snapshot, "drift_state", "") or ""

        # 1. Below noise threshold
        if mat_score < _NOISE_THRESHOLD:
            return "noise"

        # 2. Macro + market-moving → regime change
        if (
            event.category == EventCategory.MACRO
            and event.is_market_moving
            and mat_score >= 0.4
        ):
            return "regime_change"

        # 3. Priced in
        if priced_in:
            return "priced_in"

        # 4. Miss or lowered guidance
        if "miss" in tags or "lowered" in tags:
            if confidence >= 0.72:
                return "thesis_broke"
            return "weakens_thesis"

        # 5. Beat or raised guidance
        if "beat" in tags or "raised" in tags:
            return "strengthens_thesis"

        # 6. High materiality + market moving
        if mat_score >= 0.6 and event.is_market_moving:
            # Check if topic differs from core debate (debate_shift) vs same (market_repriced)
            core_debate = (getattr(snapshot, "core_market_debate", "") or "").lower()
            headline_lower = (event.headline or "").lower()
            # Simple heuristic: if headline has no overlap with debate → debate_shift
            debate_words = set(w for w in core_debate.split() if len(w) > 4)
            headline_words = set(w for w in headline_lower.split() if len(w) > 4)
            if debate_words and not debate_words.intersection(headline_words):
                return "debate_shift"
            return "market_repriced"

        return "market_repriced"
    except Exception as exc:
        logger.warning("_classify_impact_type failed: %s", exc)
        return "noise"


def _derive_alert_priority(impact_type: str, mat_score: float) -> str:
    """Derive alert priority from impact type and materiality score."""
    if impact_type == "thesis_broke" or mat_score >= _CRITICAL_THRESHOLD:
        return "critical"
    if impact_type in ("debate_shift", "weakens_thesis") or mat_score >= _HIGH_THRESHOLD:
        return "high"
    if impact_type in ("strengthens_thesis", "market_repriced") or mat_score >= _ALERT_THRESHOLD:
        return "medium"
    return "ignore"


def assess_event_impact(
    event: NormalizedEvent,
    snapshot: ThesisSnapshot,
) -> EventImpactAssessment:
    """Assess how a new market event impacts an existing thesis snapshot."""
    try:
        relevance = _score_relevance(event, snapshot)
        priced_in, pi_reasoning = _check_priced_in(event, snapshot)
        mat_score = _score_materiality(event, snapshot, relevance)
        impact_type = _classify_impact_type(event, snapshot, priced_in, mat_score)

        thesis_dir = _determine_thesis_direction(snapshot)
        primary_tag = event.tags[0] if event.tags else ""
        implication = _get_template(impact_type, primary_tag, thesis_dir)

        alert_priority = _derive_alert_priority(impact_type, mat_score)

        recommended_action = (
            "re_evaluate" if alert_priority == "critical" else
            "alert"       if alert_priority in ("high", "medium") else
            "monitor"     if impact_type not in ("noise", "priced_in") else
            "ignore"
        )

        return EventImpactAssessment(
            ticker=snapshot.ticker,
            event_id=event.event_id,
            event_headline=event.headline,
            event_category=event.category.value,
            impact_type=impact_type,
            materiality_score=mat_score,
            already_priced_in=priced_in,
            already_priced_in_reasoning=pi_reasoning,
            thesis_implication=implication,
            recommended_action=recommended_action,
            alert_priority=alert_priority,
            timestamp=event.ingestion_timestamp,
            snapshot_id=snapshot.snapshot_id,
        )
    except Exception as exc:
        logger.warning("assess_event_impact failed: %s", exc)
        return EventImpactAssessment(
            ticker=getattr(snapshot, "ticker", ""),
            event_id=getattr(event, "event_id", ""),
            impact_type="noise",
        )


def process_event_for_watchlist(
    event: NormalizedEvent,
    store: Optional[JsonFileTimelineStore] = None,
) -> List[EventImpactAssessment]:
    """
    Process one event against all watchlist tickers' latest snapshots.
    Returns only non-noise assessments, sorted by materiality descending.
    """
    try:
        _store = store or default_store

        # Determine which tickers to process
        if event.ticker is not None:
            tickers_to_process = [event.ticker.upper()]
        else:
            # Macro event — process ALL watched tickers
            tickers_to_process = _store.all_tickers()

        assessments: List[EventImpactAssessment] = []

        for ticker in tickers_to_process:
            try:
                entry = _store.latest(ticker, entry_type="thesis_snapshot")
                if entry is None:
                    continue

                # Reconstruct ThesisSnapshot from stored data
                snapshot = ThesisSnapshot.model_validate(
                    {**entry.data, "ticker": ticker}
                )
                assessment = assess_event_impact(event, snapshot)
                if assessment.impact_type != "noise":
                    assessments.append(assessment)
            except Exception as ticker_exc:
                logger.warning(
                    "process_event_for_watchlist: failed for ticker %s: %s",
                    ticker,
                    ticker_exc,
                )

        # Sort by materiality descending
        assessments.sort(key=lambda a: a.materiality_score, reverse=True)
        return assessments
    except Exception as exc:
        logger.warning("process_event_for_watchlist failed: %s", exc)
        return []


def save_impact_assessment(
    assessment: EventImpactAssessment,
    store: Optional[JsonFileTimelineStore] = None,
) -> str:
    """Persist an EventImpactAssessment to the timeline store."""
    try:
        _store = store or default_store
        entry = TimelineEntry(
            ticker=assessment.ticker,
            entry_type="event_impact",
            timestamp=assessment.timestamp or "",
            data=assessment.model_dump(),
        )
        return _store.save(entry)
    except Exception as exc:
        logger.warning("save_impact_assessment failed: %s", exc)
        return ""
