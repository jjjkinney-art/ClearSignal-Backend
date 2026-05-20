"""
EventIngestionPipeline — orchestrates all adapters through the full
normalization → deduplication → freshness-scoring → dispatch pipeline.

Architecture:
  1. Fetch from all registered adapters (parallel, retry-safe)
  2. Normalize each event (EventNormalizer: provenance, tags, timestamps)
  3. Deduplicate (EventDeduplicator: content-hash based, LRU)
  4. Score freshness (EventFreshnessScore: time-decay per category)
  5. Filter stale events (configurable staleness gate)
  6. Dispatch to thesis impact pipeline (event_processor)
  7. Persist impacts and return results

The pipeline is designed to be:
  - Retry-safe: adapter failures are logged and skipped
  - Idempotent: duplicate events never reach the thesis pipeline
  - Observable: structured logging at each stage
  - Gracefully degrading: partial results returned even when some adapters fail

Usage:
    pipeline = EventIngestionPipeline()
    pipeline.register_adapter(SECEdgarAdapter())
    pipeline.register_adapter(TreasuryMacroAdapter())
    results = await pipeline.run(tickers=["AAPL", "MSFT"])
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ...schemas import EventFreshnessScore, EventImpactAssessment
from ..event_processor import process_event_for_watchlist, save_impact_assessment
from ..timeline_store import JsonFileTimelineStore, default_store
from .base import EventIngestionAdapter
from .event_deduplicator import EventDeduplicator, get_default_deduplicator
from .event_normalizer import EventNormalizer, get_default_normalizer
from .freshness_scorer import score_freshness
from .normalized_event import NormalizedEvent

logger = logging.getLogger(__name__)


@dataclass
class PipelineRunResult:
    """Result of one EventIngestionPipeline.run() call."""
    started_at: str
    completed_at: str
    adapters_called: int
    events_fetched: int
    events_after_dedup: int
    events_after_freshness: int
    impact_assessments: List[EventImpactAssessment] = field(default_factory=list)
    freshness_scores: Dict[str, EventFreshnessScore] = field(default_factory=dict)
    adapter_errors: List[str] = field(default_factory=list)
    skipped_stale: int = 0

    @property
    def duration_ms(self) -> float:
        try:
            t0 = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(self.completed_at.replace("Z", "+00:00"))
            return (t1 - t0).total_seconds() * 1000
        except Exception:
            return 0.0


class EventIngestionPipeline:
    """
    Orchestrates event ingestion from multiple adapters through the
    normalize → dedup → freshness → thesis-impact pipeline.
    """

    def __init__(
        self,
        store: Optional[JsonFileTimelineStore] = None,
        deduplicator: Optional[EventDeduplicator] = None,
        normalizer: Optional[EventNormalizer] = None,
        max_staleness_hours: float = 72.0,
        max_events_per_run: int = 200,
    ) -> None:
        self._store = store or default_store
        self._dedup = deduplicator or get_default_deduplicator()
        self._normalizer = normalizer or get_default_normalizer()
        self._adapters: List[EventIngestionAdapter] = []
        self._max_staleness_hours = max_staleness_hours
        self._max_events = max_events_per_run
        self._run_count = 0
        self._last_run_at: Optional[str] = None

    # ── Adapter registration ───────────────────────────────────────────────

    def register_adapter(self, adapter: EventIngestionAdapter) -> None:
        """Register an ingestion adapter with this pipeline."""
        self._adapters.append(adapter)
        logger.info("EventIngestionPipeline: registered adapter '%s'", adapter.source_name)

    @property
    def adapter_count(self) -> int:
        return len(self._adapters)

    # ── Main run ──────────────────────────────────────────────────────────

    async def run(
        self,
        tickers: Optional[List[str]] = None,
        since: Optional[str] = None,
    ) -> PipelineRunResult:
        """
        Execute the full ingestion pipeline.

        Parameters
        ----------
        tickers:
            Ticker filter. None = fetch all available events from adapters.
        since:
            ISO-8601 cutoff. Adapters should return only events after this time.

        Returns
        -------
        PipelineRunResult with all impact assessments and metadata.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        self._run_count += 1
        self._last_run_at = started_at

        logger.info(
            "EventIngestionPipeline run #%d started: adapters=%d tickers=%s",
            self._run_count,
            len(self._adapters),
            tickers,
        )

        result = PipelineRunResult(
            started_at=started_at,
            completed_at=started_at,
            adapters_called=0,
            events_fetched=0,
            events_after_dedup=0,
            events_after_freshness=0,
        )

        # ── Stage 1: Fetch from all adapters (parallel) ────────────────────
        raw_events: List[NormalizedEvent] = []
        fetch_tasks = [
            self._safe_fetch(adapter, tickers, since)
            for adapter in self._adapters
        ]
        adapter_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for adapter, adapter_result in zip(self._adapters, adapter_results):
            result.adapters_called += 1
            if isinstance(adapter_result, Exception):
                err_msg = f"{adapter.source_name}: {adapter_result}"
                result.adapter_errors.append(err_msg)
                logger.warning("Adapter '%s' failed: %s", adapter.source_name, adapter_result)
            elif isinstance(adapter_result, list):
                raw_events.extend(adapter_result)
                logger.info("Adapter '%s' returned %d events", adapter.source_name, len(adapter_result))

        result.events_fetched = len(raw_events)

        if not raw_events:
            result.completed_at = datetime.now(timezone.utc).isoformat()
            logger.info("EventIngestionPipeline: no events fetched")
            return result

        # ── Stage 2: Normalize (provenance, tags, timestamps) ─────────────
        normalized: List[NormalizedEvent] = []
        for ev in raw_events[:self._max_events]:
            try:
                normalized.append(self._normalizer.normalize(ev))
            except Exception as exc:
                logger.warning("Normalizer failed for event %s: %s", ev.event_id, exc)

        # ── Stage 3: Deduplicate ───────────────────────────────────────────
        unique_events = self._dedup.filter(normalized)
        result.events_after_dedup = len(unique_events)

        logger.info(
            "Pipeline dedup: %d → %d unique events",
            len(normalized),
            len(unique_events),
        )

        # ── Stage 4: Freshness scoring ─────────────────────────────────────
        fresh_events: List[NormalizedEvent] = []
        for ev in unique_events:
            fs = score_freshness(ev)
            result.freshness_scores[ev.event_id] = fs
            if fs.age_hours <= self._max_staleness_hours:
                fresh_events.append(ev)
            else:
                result.skipped_stale += 1
                logger.debug("Skipped stale event: %s (age=%.1fh)", ev.headline[:60], fs.age_hours)

        result.events_after_freshness = len(fresh_events)

        logger.info(
            "Pipeline freshness gate: %d → %d fresh events (%d stale skipped)",
            len(unique_events),
            len(fresh_events),
            result.skipped_stale,
        )

        # ── Stage 5: Thesis impact assessment ─────────────────────────────
        impacts: List[EventImpactAssessment] = []
        for ev in fresh_events:
            try:
                ev_impacts = process_event_for_watchlist(ev, self._store)
                for impact in ev_impacts:
                    # Attach provenance from the event to the assessment
                    if hasattr(ev, "provenance") and ev.provenance is not None:
                        impact.provenance = ev.provenance
                    # Persist to timeline
                    save_impact_assessment(impact, self._store)
                impacts.extend(ev_impacts)
            except Exception as exc:
                logger.warning("Thesis impact assessment failed for event %s: %s", ev.event_id, exc)

        result.impact_assessments = impacts

        result.completed_at = datetime.now(timezone.utc).isoformat()

        logger.info(
            "EventIngestionPipeline run #%d complete: %d events fetched, "
            "%d unique, %d fresh, %d impacts in %.0fms",
            self._run_count,
            result.events_fetched,
            result.events_after_dedup,
            result.events_after_freshness,
            len(impacts),
            result.duration_ms,
        )

        return result

    # ── Health check ───────────────────────────────────────────────────────

    async def health_check(self) -> dict:
        """Return health status of all registered adapters."""
        checks: dict[str, bool] = {}
        for adapter in self._adapters:
            try:
                healthy = await adapter.health_check()
                checks[adapter.source_name] = healthy
            except Exception:
                checks[adapter.source_name] = False

        return {
            "pipeline_healthy": all(checks.values()),
            "adapters": checks,
            "run_count": self._run_count,
            "last_run_at": self._last_run_at,
            "dedup_stats": self._dedup.stats,
        }

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _safe_fetch(
        self,
        adapter: EventIngestionAdapter,
        tickers: Optional[List[str]],
        since: Optional[str],
    ) -> List[NormalizedEvent]:
        """Fetch from one adapter, never raising."""
        try:
            return await adapter.fetch_latest(tickers=tickers, since=since)
        except Exception as exc:
            logger.warning("_safe_fetch('%s') raised: %s", adapter.source_name, exc)
            raise  # Will be caught by gather(..., return_exceptions=True)


# ── Module-level default pipeline ─────────────────────────────────────────────

_default_pipeline: Optional[EventIngestionPipeline] = None


def get_default_pipeline(auto_register: bool = True) -> EventIngestionPipeline:
    """
    Return the module-level pipeline singleton.

    When auto_register=True (default), registers the standard adapter set
    (SEC EDGAR + Treasury/Macro) if no adapters are registered yet.
    """
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = EventIngestionPipeline()

    if auto_register and _default_pipeline.adapter_count == 0:
        from .sec_edgar_adapter import SECEdgarAdapter
        from .treasury_adapter import TreasuryMacroAdapter
        from .earnings_adapter import EarningsIngestionAdapter
        from .news_adapter import NewsIngestionAdapter
        from .macro_adapter import MacroIngestionAdapter

        _default_pipeline.register_adapter(SECEdgarAdapter(use_live_api=False))
        _default_pipeline.register_adapter(TreasuryMacroAdapter(use_live_api=False))
        _default_pipeline.register_adapter(EarningsIngestionAdapter())
        _default_pipeline.register_adapter(NewsIngestionAdapter())
        _default_pipeline.register_adapter(MacroIngestionAdapter())

    return _default_pipeline
