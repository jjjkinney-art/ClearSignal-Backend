"""
LiveThesisUpdateService — the primary moat.

Orchestrates the complete event → thesis → alert → brief → timeline
update lifecycle. This is the service that makes ClearSignal feel alive.

When a new event arrives (via API, scheduler, or manual trigger):
  1. Classify + normalize the event
  2. Compare against all watched thesis snapshots (ThesisImpactEvaluator)
  3. Generate EventImpactAssessments for all affected tickers
  4. Update alert priorities in the timeline store
  5. Trigger morning brief refresh (if high materiality)
  6. Update watchlist drift summaries
  7. Return a structured UpdateSummary for observability

All operations are deterministic. No LLM calls.

Design:
- LiveThesisUpdateService is stateless between calls (store is the source of truth)
- Can be called from API endpoints, async schedulers, or webhook handlers
- Graceful degradation: partial failures don't block the full update
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from ..schemas import EventImpactAssessment, WatchlistDriftSummary
from .event_processor import process_event_for_watchlist, save_impact_assessment
from .ingestion.event_normalizer import get_default_normalizer
from .ingestion.normalized_event import EventCategory, NormalizedEvent, SourceReliability
from .market_regime_tracker import update_regime
from .thesis_impact_evaluator import ThesisImpactEvaluator, get_default_evaluator
from .timeline_store import JsonFileTimelineStore, default_store

logger = logging.getLogger(__name__)


@dataclass
class UpdateSummary:
    """
    Summary of one LiveThesisUpdateService.process_event() call.

    Used for observability, API responses, and morning brief generation.
    """
    event_id: str
    event_headline: str
    event_category: str
    tickers_assessed: List[str] = field(default_factory=list)
    impact_assessments: List[EventImpactAssessment] = field(default_factory=list)
    watchlist_drift: List[WatchlistDriftSummary] = field(default_factory=list)
    regime_updated: bool = False
    brief_refresh_triggered: bool = False
    processed_at: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for a in self.impact_assessments if a.alert_priority == "critical")

    @property
    def high_count(self) -> int:
        return sum(1 for a in self.impact_assessments if a.alert_priority == "high")

    @property
    def should_alert(self) -> bool:
        return self.critical_count > 0 or self.high_count > 0

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_headline": self.event_headline,
            "event_category": self.event_category,
            "tickers_assessed": self.tickers_assessed,
            "impact_count": len(self.impact_assessments),
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "should_alert": self.should_alert,
            "regime_updated": self.regime_updated,
            "brief_refresh_triggered": self.brief_refresh_triggered,
            "watchlist_drift": [
                {
                    "ticker": d.ticker,
                    "direction": d.direction,
                    "driver": d.driver,
                    "materiality": d.materiality,
                    "alert_priority": d.alert_priority,
                }
                for d in self.watchlist_drift
            ],
            "processed_at": self.processed_at,
        }


class LiveThesisUpdateService:
    """
    Orchestrates the complete live thesis update pipeline.

    Intended usage:
        service = LiveThesisUpdateService()
        summary = service.process_event(event)
        # summary.impact_assessments ready for API response
        # timeline store updated with assessments + regime
    """

    def __init__(
        self,
        store: Optional[JsonFileTimelineStore] = None,
        evaluator: Optional[ThesisImpactEvaluator] = None,
    ) -> None:
        self._store = store or default_store
        self._evaluator = evaluator or get_default_evaluator()
        self._normalizer = get_default_normalizer()
        self._brief_refresh_threshold = 0.65  # materiality score to trigger brief refresh

    def process_event(self, event: NormalizedEvent) -> UpdateSummary:
        """
        Process a single NormalizedEvent through the full update pipeline.

        Safe to call from sync contexts. All failures are caught and logged.
        """
        processed_at = datetime.now(timezone.utc).isoformat()

        summary = UpdateSummary(
            event_id=event.event_id,
            event_headline=event.headline,
            event_category=event.category.value if event.category else "",
            processed_at=processed_at,
        )

        try:
            # Stage 1: Normalize (provenance, extended tags)
            event = self._normalizer.normalize(event)

            # Stage 2: Thesis impact assessment for all relevant tickers
            impacts = process_event_for_watchlist(event, self._store)
            summary.impact_assessments = impacts
            summary.tickers_assessed = list({a.ticker for a in impacts})

            # Stage 3: Persist all assessments
            for impact in impacts:
                if hasattr(event, "provenance") and event.provenance is not None:
                    impact.provenance = event.provenance
                save_impact_assessment(impact, self._store)

            # Stage 4: Update regime if this is a macro event
            if event.category == EventCategory.MACRO and event.is_market_moving:
                try:
                    update_regime([event])
                    summary.regime_updated = True
                    logger.info("Regime updated from macro event: %s", event.headline[:80])
                except Exception as regime_exc:
                    logger.warning("Regime update failed: %s", regime_exc)

            # Stage 5: Compute watchlist drift for affected tickers
            if summary.tickers_assessed:
                try:
                    summary.watchlist_drift = self._evaluator.get_watchlist_drift(
                        summary.tickers_assessed
                    )
                except Exception as drift_exc:
                    logger.warning("Watchlist drift computation failed: %s", drift_exc)

            # Stage 6: Determine if brief refresh is warranted
            max_materiality = max(
                (a.materiality_score for a in impacts), default=0.0
            )
            if max_materiality >= self._brief_refresh_threshold or summary.critical_count > 0:
                summary.brief_refresh_triggered = True
                logger.info(
                    "Morning brief refresh triggered: max_materiality=%.2f critical=%d",
                    max_materiality,
                    summary.critical_count,
                )

            logger.info(
                "LiveThesisUpdateService.process_event complete: event='%s' "
                "tickers=%d impacts=%d critical=%d",
                event.headline[:80],
                len(summary.tickers_assessed),
                len(impacts),
                summary.critical_count,
            )

        except Exception as exc:
            logger.warning("LiveThesisUpdateService.process_event failed: %s", exc)

        return summary

    def process_events_batch(
        self,
        events: List[NormalizedEvent],
    ) -> List[UpdateSummary]:
        """
        Process a batch of events. Returns one UpdateSummary per event.
        Order is preserved. Failures per event are isolated.
        """
        summaries: List[UpdateSummary] = []
        for ev in events:
            summaries.append(self.process_event(ev))
        return summaries

    def get_watchlist_state(
        self,
        tickers: List[str],
    ) -> List[WatchlistDriftSummary]:
        """
        Return the current thesis drift state for all watched tickers.
        Used by the morning brief and watchlist page.
        """
        try:
            return self._evaluator.get_watchlist_drift(tickers)
        except Exception as exc:
            logger.warning("get_watchlist_state failed: %s", exc)
            return []


def _make_synthetic_event(
    headline: str,
    ticker: Optional[str] = None,
    category: EventCategory = EventCategory.NEWS,
    is_market_moving: bool = True,
    tags: Optional[List[str]] = None,
) -> NormalizedEvent:
    """
    Utility for creating synthetic events in tests and development.
    """
    now = datetime.now(timezone.utc).isoformat()
    return NormalizedEvent(
        ticker=ticker,
        category=category,
        headline=headline,
        body=headline,
        source="synthetic",
        source_reliability=SourceReliability.MEDIUM,
        event_timestamp=now,
        ingestion_timestamp=now,
        is_market_moving=is_market_moving,
        tags=tags or [],
    )


# Module-level singleton
_default_service: Optional[LiveThesisUpdateService] = None


def get_live_thesis_service() -> LiveThesisUpdateService:
    global _default_service
    if _default_service is None:
        _default_service = LiveThesisUpdateService()
    return _default_service
