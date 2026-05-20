"""
ThesisImpactEvaluator — higher-level service that aggregates multiple
EventImpactAssessments into a per-ticker thesis evolution summary.

Sits above event_processor.py (which handles individual event→thesis comparison)
and synthesizes the overall thesis drift direction across multiple recent events.

Responsibilities:
1. Load recent EventImpactAssessments for a ticker from the timeline store
2. Determine aggregate thesis drift direction across events
3. Generate a WatchlistDriftSummary for each ticker (used in morning brief section 5)
4. Identify which tickers have "broke" vs "strengthened" vs "weakened"
5. Detect debate shifts (when multiple events all point to a topic outside the old debate)

ThesisImpactEvaluator does NOT call the LLM. All logic is deterministic.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Dict, List, Optional, Tuple

from ..schemas import EventImpactAssessment, WatchlistDriftSummary
from .timeline_store import JsonFileTimelineStore, default_store

logger = logging.getLogger(__name__)

# How many recent impact assessments to consider per ticker
_DEFAULT_LOOKBACK = 10

# Impact type → drift direction mapping
_IMPACT_TO_DRIFT: dict[str, str] = {
    "thesis_broke":       "broke",
    "weakens_thesis":     "weakened",
    "debate_shift":       "weakened",      # debate shifts are cautiously negative
    "market_repriced":    "unchanged",
    "regime_change":      "weakened",
    "strengthens_thesis": "strengthened",
    "priced_in":          "priced_in",
    "noise":              "unchanged",
}

# Priority weights for drift direction determination
_DIRECTION_PRIORITY = {
    "broke":        100,
    "weakened":      50,
    "priced_in":     20,
    "unchanged":     10,
    "strengthened":   5,
}


class ThesisImpactEvaluator:
    """
    Aggregates per-event assessments into a holistic thesis drift summary.

    Usage:
        evaluator = ThesisImpactEvaluator()
        drift = evaluator.get_ticker_drift("AAPL")
        all_drift = evaluator.get_watchlist_drift(["AAPL", "MSFT", "NVDA"])
    """

    def __init__(
        self,
        store: Optional[JsonFileTimelineStore] = None,
        lookback: int = _DEFAULT_LOOKBACK,
    ) -> None:
        self._store = store or default_store
        self._lookback = lookback

    # ── Public API ─────────────────────────────────────────────────────────

    def get_ticker_drift(self, ticker: str) -> WatchlistDriftSummary:
        """
        Compute drift summary for a single ticker from recent impact assessments.

        Parameters
        ----------
        ticker:
            Ticker symbol (case-insensitive).

        Returns
        -------
        WatchlistDriftSummary with direction, driver, and materiality.
        """
        try:
            assessments = self._load_recent_assessments(ticker)
            return self._compute_drift(ticker, assessments)
        except Exception as exc:
            logger.warning("get_ticker_drift failed for %s: %s", ticker, exc)
            return WatchlistDriftSummary(
                ticker=ticker.upper(),
                direction="unchanged",
                driver="",
                materiality=0.0,
                alert_priority="ignore",
            )

    def get_watchlist_drift(
        self,
        tickers: List[str],
    ) -> List[WatchlistDriftSummary]:
        """
        Compute drift summaries for all tickers, sorted by materiality descending.
        """
        try:
            summaries: List[WatchlistDriftSummary] = []
            for ticker in tickers:
                summary = self.get_ticker_drift(ticker)
                summaries.append(summary)

            # Sort: broke first → weakened → strengthened → priced_in → unchanged
            priority_order = {"broke": 0, "weakened": 1, "strengthened": 2, "priced_in": 3, "unchanged": 4}
            summaries.sort(
                key=lambda s: (priority_order.get(s.direction, 99), -s.materiality)
            )
            return summaries
        except Exception as exc:
            logger.warning("get_watchlist_drift failed: %s", exc)
            return []

    def get_high_priority_tickers(
        self,
        tickers: List[str],
        min_priority: str = "high",
    ) -> List[str]:
        """
        Return tickers that have at least one recent impact at or above min_priority.

        Parameters
        ----------
        tickers:
            Tickers to evaluate.
        min_priority:
            Minimum alert priority: 'critical' | 'high' | 'medium'.
        """
        try:
            priority_rank = {"critical": 3, "high": 2, "medium": 1, "ignore": 0}
            min_rank = priority_rank.get(min_priority, 1)

            high_priority = []
            for ticker in tickers:
                assessments = self._load_recent_assessments(ticker, limit=5)
                for a in assessments:
                    if priority_rank.get(a.alert_priority, 0) >= min_rank:
                        high_priority.append(ticker)
                        break

            return high_priority
        except Exception as exc:
            logger.warning("get_high_priority_tickers failed: %s", exc)
            return []

    def get_debate_shifts(
        self,
        tickers: List[str],
    ) -> List[Tuple[str, str]]:
        """
        Return (ticker, debate_shift_driver) pairs for tickers with recent debate shifts.

        Returns only tickers where the dominant recent impact_type is 'debate_shift'.
        """
        try:
            shifts: List[Tuple[str, str]] = []
            for ticker in tickers:
                assessments = self._load_recent_assessments(ticker, limit=5)
                debate_assessments = [a for a in assessments if a.impact_type == "debate_shift"]
                if debate_assessments:
                    # Get the highest-materiality debate-shift event headline
                    top = max(debate_assessments, key=lambda a: a.materiality_score)
                    driver = top.event_headline or top.thesis_implication or ticker
                    shifts.append((ticker.upper(), driver))
            return shifts
        except Exception as exc:
            logger.warning("get_debate_shifts failed: %s", exc)
            return []

    # ── Internal helpers ───────────────────────────────────────────────────

    def _load_recent_assessments(
        self,
        ticker: str,
        limit: Optional[int] = None,
    ) -> List[EventImpactAssessment]:
        """Load recent EventImpactAssessments from the timeline store."""
        try:
            entries = self._store.load(ticker.upper(), entry_type="event_impact")
            entries.sort(key=lambda e: e.timestamp, reverse=True)
            cap = limit or self._lookback
            recent = entries[:cap]
            return [EventImpactAssessment.model_validate(e.data) for e in recent]
        except Exception as exc:
            logger.warning("_load_recent_assessments failed for %s: %s", ticker, exc)
            return []

    def _compute_drift(
        self,
        ticker: str,
        assessments: List[EventImpactAssessment],
    ) -> WatchlistDriftSummary:
        """Aggregate multiple assessments into a single drift summary."""
        if not assessments:
            return WatchlistDriftSummary(
                ticker=ticker.upper(),
                direction="unchanged",
                driver="",
                materiality=0.0,
                alert_priority="ignore",
            )

        # Map each assessment to its drift direction
        directions = [_IMPACT_TO_DRIFT.get(a.impact_type, "unchanged") for a in assessments]

        # Weighted vote: most-severe direction wins
        direction_scores: Counter[str] = Counter()
        for i, a in enumerate(assessments):
            direction = directions[i]
            # Recency weight: most recent gets full weight, older assessments decay
            recency_weight = 1.0 / (i + 1)
            severity_weight = _DIRECTION_PRIORITY.get(direction, 10)
            direction_scores[direction] += severity_weight * recency_weight * (a.materiality_score + 0.1)

        # Winner is the highest-scored direction
        winning_direction = max(direction_scores, key=lambda d: direction_scores[d])

        # Aggregate materiality: average of top 3 assessments
        top_assessments = sorted(assessments, key=lambda a: a.materiality_score, reverse=True)[:3]
        avg_materiality = sum(a.materiality_score for a in top_assessments) / len(top_assessments)

        # Driver: thesis implication from the highest-priority assessment
        # (prefer thesis_broke or debate_shift)
        priority_type_order = [
            "thesis_broke", "weakens_thesis", "debate_shift",
            "strengthens_thesis", "market_repriced", "regime_change",
        ]
        driver_assessment = None
        for ptype in priority_type_order:
            candidates = [a for a in assessments if a.impact_type == ptype]
            if candidates:
                driver_assessment = max(candidates, key=lambda a: a.materiality_score)
                break
        if driver_assessment is None:
            driver_assessment = assessments[0]

        # Get driver text: prefer thesis_implication, fall back to event_headline
        driver_text = driver_assessment.thesis_implication or driver_assessment.event_headline or ""
        # Compress to ≤15 words
        if driver_text:
            words = driver_text.split()
            if len(words) > 15:
                driver_text = " ".join(words[:15]) + "…"

        # Alert priority: highest priority across assessments
        priority_rank = {"critical": 4, "high": 3, "medium": 2, "ignore": 1}
        top_priority = max(assessments, key=lambda a: priority_rank.get(a.alert_priority, 0))
        alert_priority = top_priority.alert_priority

        return WatchlistDriftSummary(
            ticker=ticker.upper(),
            direction=winning_direction,
            driver=driver_text,
            materiality=round(avg_materiality, 3),
            alert_priority=alert_priority,
        )


# Module-level singleton
_default_evaluator: Optional[ThesisImpactEvaluator] = None


def get_default_evaluator() -> ThesisImpactEvaluator:
    global _default_evaluator
    if _default_evaluator is None:
        _default_evaluator = ThesisImpactEvaluator()
    return _default_evaluator
