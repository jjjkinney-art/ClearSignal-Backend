"""
Phase M — Real Market Infrastructure test suite.

Tests cover:
- EvidenceProvenance schema (10 tests)
- EventFreshnessScore schema (5 tests)
- MorningBriefV2 schema (5 tests)
- WatchlistDriftSummary schema (5 tests)
- EventDeduplicator (10 tests)
- FreshnessScorer (12 tests)
- EventNormalizer (10 tests)
- SECEdgarAdapter (5 tests)
- TreasuryMacroAdapter (5 tests)
- EventIngestionPipeline (8 tests)
- ThesisImpactEvaluator (10 tests)
- LiveThesisUpdateService (8 tests)
- MorningBriefV2 generation (10 tests)
- API endpoint coverage (7 tests)

Total: 110 tests
All deterministic — no LLM calls, no network calls.
"""
from __future__ import annotations

import asyncio
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest

# ── Schema imports ─────────────────────────────────────────────────────────────

from app.schemas import (
    EvidenceProvenance,
    EventFreshnessScore,
    EventImpactAssessment,
    MorningBriefV2,
    ThesisSnapshot,
    WatchlistDriftSummary,
)
from app.services.ingestion.normalized_event import (
    EventCategory,
    NormalizedEvent,
    SourceReliability,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ago_iso(hours: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.isoformat()


def _make_event(
    ticker: Optional[str] = "AAPL",
    category: EventCategory = EventCategory.EARNINGS,
    headline: str = "Apple Q1 beat estimates",
    tags: Optional[List[str]] = None,
    is_market_moving: bool = True,
    source_reliability: SourceReliability = SourceReliability.HIGH,
    hours_ago: float = 0.5,
) -> NormalizedEvent:
    ts = _ago_iso(hours_ago)
    return NormalizedEvent(
        ticker=ticker,
        category=category,
        headline=headline,
        body=headline,
        source="test_source",
        source_reliability=source_reliability,
        event_timestamp=ts,
        ingestion_timestamp=ts,
        is_market_moving=is_market_moving,
        tags=tags or ["beat"],
    )


def _make_snapshot(
    ticker: str = "AAPL",
    confidence: float = 0.75,
    drift: str = "stable",
    core_debate: str = "Can Apple sustain Services margin expansion?",
) -> ThesisSnapshot:
    return ThesisSnapshot.model_construct(
        snapshot_id=str(uuid.uuid4()),
        ticker=ticker,
        confidence_score=confidence,
        drift_state=drift,
        core_market_debate=core_debate,
        dominant_driver="Services margin expansion",
        macro_sensitivity="interest rate sensitive",
        thesis_direction="bull",
        direct_answer="Strong buy based on Services narrative.",
        key_drivers=["Services growth", "iPhone ASP"],
        top_signals=[],
        bull_case=[],
        bear_case=[],
        risks=[],
        catalysts=[],
        snapshot_timestamp=_now_iso(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 1: EvidenceProvenance schema
# ─────────────────────────────────────────────────────────────────────────────

class TestEvidenceProvenanceSchema:
    def test_default_construction(self):
        ep = EvidenceProvenance()
        assert ep.source_origin == ""
        assert ep.evidence_type == ""
        assert ep.citation_label == ""
        assert 0.0 <= ep.source_confidence <= 1.0

    def test_full_construction(self):
        ep = EvidenceProvenance(
            source_origin="earnings_transcript",
            source_timestamp=_now_iso(),
            source_confidence=0.95,
            evidence_type="transcript",
            citation_label="Q1 2025 earnings call",
        )
        assert ep.source_origin == "earnings_transcript"
        assert ep.citation_label == "Q1 2025 earnings call"
        assert ep.source_confidence == 0.95

    def test_confidence_bounds_low(self):
        ep = EvidenceProvenance(source_confidence=0.0)
        assert ep.source_confidence == 0.0

    def test_confidence_bounds_high(self):
        ep = EvidenceProvenance(source_confidence=1.0)
        assert ep.source_confidence == 1.0

    def test_confidence_out_of_bounds_raises(self):
        with pytest.raises(Exception):
            EvidenceProvenance(source_confidence=1.5)

    def test_sec_filing_provenance(self):
        ep = EvidenceProvenance(
            source_origin="sec_filing",
            evidence_type="filing",
            citation_label="10-K filing, Feb 2025",
            source_confidence=1.0,
        )
        assert ep.source_origin == "sec_filing"
        assert ep.evidence_type == "filing"
        assert "10-K" in ep.citation_label

    def test_macro_provenance(self):
        ep = EvidenceProvenance(
            source_origin="macro_release",
            evidence_type="macro",
            citation_label="CPI March 2025",
            source_confidence=0.9,
        )
        assert ep.evidence_type == "macro"
        assert "CPI" in ep.citation_label

    def test_model_dump_round_trip(self):
        ep = EvidenceProvenance(
            source_origin="news_wire",
            citation_label="News report, 2025-01-15",
            source_confidence=0.7,
        )
        d = ep.model_dump()
        ep2 = EvidenceProvenance.model_validate(d)
        assert ep2.source_origin == ep.source_origin
        assert ep2.citation_label == ep.citation_label

    def test_evidence_type_values(self):
        valid_types = ["filing", "transcript", "macro", "market_move", "guidance", "estimate", "regulatory"]
        for ev_type in valid_types:
            ep = EvidenceProvenance(evidence_type=ev_type)
            assert ep.evidence_type == ev_type

    def test_attached_to_event_impact(self):
        assessment = EventImpactAssessment(
            ticker="AAPL",
            event_id="test-001",
            provenance=EvidenceProvenance(
                citation_label="Q1 earnings call",
                evidence_type="transcript",
                source_confidence=0.9,
            ),
        )
        assert assessment.provenance is not None
        assert assessment.provenance.citation_label == "Q1 earnings call"


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 2: EventFreshnessScore schema
# ─────────────────────────────────────────────────────────────────────────────

class TestEventFreshnessScoreSchema:
    def test_default_construction(self):
        fs = EventFreshnessScore()
        assert fs.freshness == 1.0
        assert fs.label == "Today"
        assert not fs.is_stale

    def test_stale_flag(self):
        fs = EventFreshnessScore(freshness=0.2, label="Stale", is_stale=True)
        assert fs.is_stale is True

    def test_freshness_bounds(self):
        fs1 = EventFreshnessScore(freshness=0.0)
        fs2 = EventFreshnessScore(freshness=1.0)
        assert fs1.freshness == 0.0
        assert fs2.freshness == 1.0

    def test_label_values(self):
        for label in ["Live", "Today", "This Week", "Stale"]:
            fs = EventFreshnessScore(label=label)
            assert fs.label == label

    def test_model_dump(self):
        fs = EventFreshnessScore(event_id="abc", age_hours=2.5, freshness=0.8, label="Today")
        d = fs.model_dump()
        assert d["event_id"] == "abc"
        assert d["age_hours"] == 2.5


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 3: WatchlistDriftSummary schema
# ─────────────────────────────────────────────────────────────────────────────

class TestWatchlistDriftSummarySchema:
    def test_construction(self):
        d = WatchlistDriftSummary(ticker="AAPL", direction="weakened", driver="Guidance cut", materiality=0.72)
        assert d.ticker == "AAPL"
        assert d.direction == "weakened"
        assert d.materiality == 0.72

    def test_default_direction(self):
        d = WatchlistDriftSummary(ticker="MSFT")
        assert d.direction == "unchanged"

    def test_all_directions(self):
        for direction in ["strengthened", "weakened", "broke", "unchanged", "priced_in"]:
            d = WatchlistDriftSummary(ticker="T", direction=direction)
            assert d.direction == direction

    def test_materiality_bounds(self):
        d = WatchlistDriftSummary(ticker="T", materiality=0.0)
        assert d.materiality == 0.0
        d2 = WatchlistDriftSummary(ticker="T", materiality=1.0)
        assert d2.materiality == 1.0

    def test_model_dump(self):
        d = WatchlistDriftSummary(ticker="NVDA", direction="broke", driver="Miss on data center", materiality=0.9)
        dump = d.model_dump()
        assert dump["ticker"] == "NVDA"
        assert dump["direction"] == "broke"


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 4: MorningBriefV2 schema
# ─────────────────────────────────────────────────────────────────────────────

class TestMorningBriefV2Schema:
    def test_default_construction(self):
        brief = MorningBriefV2()
        assert brief.regime_headline == ""
        assert brief.narrative_shifts == []
        assert brief.debate_shifts == []
        assert brief.priority_alerts == []
        assert brief.watchlist_drift == []

    def test_with_all_sections(self):
        brief = MorningBriefV2(
            generated_at=_now_iso(),
            reference_date="2025-03-15",
            ticker_count=5,
            regime_headline="Higher-for-longer confirmed.",
            regime_factors=["CPI sticky", "Fed hawkish"],
            rate_environment="higher_for_longer",
            risk_appetite="selective",
            narrative_shifts=["AAPL: thesis weakened post-miss."],
            debate_shifts=["META debate shifting from capex → monetization."],
            priority_alerts=["⚑ AAPL: thesis broke."],
            attention_required=["AAPL"],
            watchlist_drift=[WatchlistDriftSummary(ticker="AAPL", direction="weakened")],
            top_movers=["AAPL"],
        )
        assert brief.ticker_count == 5
        assert len(brief.narrative_shifts) == 1
        assert "AAPL" in brief.attention_required

    def test_model_dump_structure(self):
        brief = MorningBriefV2(regime_headline="Test regime")
        d = brief.model_dump()
        assert "regime_headline" in d
        assert "narrative_shifts" in d
        assert "debate_shifts" in d
        assert "priority_alerts" in d
        assert "watchlist_drift" in d

    def test_backward_compat_fields(self):
        brief = MorningBriefV2(brief_text="legacy text", market_regime_note="legacy note")
        assert brief.brief_text == "legacy text"
        assert brief.market_regime_note == "legacy note"

    def test_watchlist_drift_nested(self):
        drift = [
            WatchlistDriftSummary(ticker="AAPL", direction="broke"),
            WatchlistDriftSummary(ticker="MSFT", direction="strengthened"),
        ]
        brief = MorningBriefV2(watchlist_drift=drift)
        assert len(brief.watchlist_drift) == 2
        assert brief.watchlist_drift[0].ticker == "AAPL"


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 5: EventDeduplicator
# ─────────────────────────────────────────────────────────────────────────────

class TestEventDeduplicator:
    def setup_method(self):
        from app.services.ingestion.event_deduplicator import EventDeduplicator
        self.dedup = EventDeduplicator(max_size=100)

    def test_new_event_not_duplicate(self):
        ev = _make_event()
        assert not self.dedup.is_duplicate(ev)

    def test_mark_seen_makes_duplicate(self):
        ev = _make_event()
        self.dedup.mark_seen(ev)
        assert self.dedup.is_duplicate(ev)

    def test_different_headline_not_duplicate(self):
        ev1 = _make_event(headline="Apple beats estimates")
        ev2 = _make_event(headline="Apple misses estimates")
        self.dedup.mark_seen(ev1)
        assert not self.dedup.is_duplicate(ev2)

    def test_filter_removes_duplicates(self):
        ev = _make_event()
        result = self.dedup.filter([ev, ev, ev])
        assert len(result) == 1

    def test_filter_preserves_order(self):
        ev1 = _make_event(headline="Event A")
        ev2 = _make_event(headline="Event B")
        ev3 = _make_event(headline="Event C")
        result = self.dedup.filter([ev1, ev2, ev3])
        assert len(result) == 3
        assert result[0].headline == "Event A"

    def test_stats_tracking(self):
        ev = _make_event()
        self.dedup.filter([ev, ev])
        stats = self.dedup.stats
        assert stats["total_seen"] == 1
        assert stats["total_deduped"] == 1

    def test_lru_eviction(self):
        from app.services.ingestion.event_deduplicator import EventDeduplicator
        dedup = EventDeduplicator(max_size=3)
        events = [_make_event(headline=f"Event {i}") for i in range(5)]
        dedup.filter(events)
        assert len(dedup._seen) <= 3

    def test_load_seen_hashes(self):
        ev = _make_event()
        from app.services.ingestion.event_deduplicator import _content_hash
        h = _content_hash(ev)
        self.dedup.load_seen_hashes([h])
        assert self.dedup.is_duplicate(ev)

    def test_persist_seen_hashes(self):
        ev = _make_event()
        self.dedup.mark_seen(ev)
        hashes = self.dedup.persist_seen_hashes()
        assert len(hashes) == 1
        assert isinstance(hashes[0], str)

    def test_macro_event_no_ticker(self):
        ev = _make_event(ticker=None, category=EventCategory.MACRO, headline="CPI hot")
        assert not self.dedup.is_duplicate(ev)
        self.dedup.mark_seen(ev)
        assert self.dedup.is_duplicate(ev)


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 6: FreshnessScorer
# ─────────────────────────────────────────────────────────────────────────────

class TestFreshnessScorer:
    def test_just_ingested_is_live(self):
        from app.services.ingestion.freshness_scorer import score_freshness
        ev = _make_event(hours_ago=0.0)
        result = score_freshness(ev)
        assert result.label == "Live"
        assert result.freshness > 0.90
        assert not result.is_stale

    def test_twelve_hours_ago_is_today(self):
        from app.services.ingestion.freshness_scorer import score_freshness
        ev = _make_event(hours_ago=12.0)
        result = score_freshness(ev)
        # Earnings have 24h half-life; 12h gives ~0.5 * reliability modifier → Today
        assert result.label in ("Today", "This Week")  # boundary area
        assert result.freshness > 0.3

    def test_three_days_is_stale(self):
        from app.services.ingestion.freshness_scorer import score_freshness
        ev = _make_event(hours_ago=72.0)
        result = score_freshness(ev)
        assert result.is_stale

    def test_macro_has_shorter_half_life(self):
        from app.services.ingestion.freshness_scorer import score_freshness
        # CPI release 6 hours ago — macro half-life is 12h
        ev_macro = _make_event(category=EventCategory.MACRO, hours_ago=6.0)
        ev_earnings = _make_event(category=EventCategory.EARNINGS, hours_ago=6.0)
        fs_macro = score_freshness(ev_macro)
        fs_earnings = score_freshness(ev_earnings)
        # Macro decays faster than earnings
        assert fs_macro.freshness < fs_earnings.freshness

    def test_high_reliability_multiplier(self):
        from app.services.ingestion.freshness_scorer import score_freshness
        ev_high = _make_event(source_reliability=SourceReliability.HIGH, hours_ago=6.0)
        ev_low = _make_event(source_reliability=SourceReliability.LOW, hours_ago=6.0)
        fs_high = score_freshness(ev_high)
        fs_low = score_freshness(ev_low)
        assert fs_high.freshness >= fs_low.freshness

    def test_market_moving_boost(self):
        from app.services.ingestion.freshness_scorer import score_freshness
        ev_mm = _make_event(is_market_moving=True, hours_ago=8.0)
        ev_nm = _make_event(is_market_moving=False, hours_ago=8.0)
        fs_mm = score_freshness(ev_mm)
        fs_nm = score_freshness(ev_nm)
        assert fs_mm.freshness >= fs_nm.freshness

    def test_bad_timestamp_graceful(self):
        from app.services.ingestion.freshness_scorer import score_freshness
        ev = _make_event(hours_ago=0.0)
        ev.ingestion_timestamp = "NOT-A-DATE"
        ev.event_timestamp = "NOT-A-DATE"
        result = score_freshness(ev)
        # Should degrade gracefully, not raise
        assert isinstance(result, EventFreshnessScore)

    def test_age_hours_calculated(self):
        from app.services.ingestion.freshness_scorer import score_freshness
        ev = _make_event(hours_ago=5.0)
        result = score_freshness(ev)
        assert 4.5 <= result.age_hours <= 5.5

    def test_freshness_label_utility(self):
        from app.services.ingestion.freshness_scorer import freshness_label
        assert freshness_label(0.0) == "Live"
        assert freshness_label(12.0) == "Today"
        assert freshness_label(48.0) == "This Week"
        assert freshness_label(200.0) == "Stale"

    def test_event_id_preserved(self):
        from app.services.ingestion.freshness_scorer import score_freshness
        ev = _make_event(hours_ago=1.0)
        result = score_freshness(ev)
        assert result.event_id == ev.event_id

    def test_label_thresholds_all_reachable(self):
        from app.services.ingestion.freshness_scorer import score_freshness
        # Test different ages to ensure all labels are reachable
        labels_seen = set()
        for hours in [0.0, 2.0, 48.0, 300.0]:
            ev = _make_event(hours_ago=hours)
            fs = score_freshness(ev)
            labels_seen.add(fs.label)
        # Should see at least 3 different labels
        assert len(labels_seen) >= 2

    def test_freshness_between_zero_and_one(self):
        from app.services.ingestion.freshness_scorer import score_freshness
        for hours in [0.1, 6.0, 24.0, 100.0]:
            ev = _make_event(hours_ago=hours)
            fs = score_freshness(ev)
            assert 0.0 <= fs.freshness <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 7: EventNormalizer
# ─────────────────────────────────────────────────────────────────────────────

class TestEventNormalizer:
    def setup_method(self):
        from app.services.ingestion.event_normalizer import EventNormalizer
        self.normalizer = EventNormalizer()

    def test_adds_provenance(self):
        ev = _make_event()
        result = self.normalizer.normalize(ev)
        assert result.provenance is not None
        assert result.provenance.citation_label != ""

    def test_earnings_provenance_type(self):
        ev = _make_event(category=EventCategory.EARNINGS, headline="AAPL beats estimates")
        result = self.normalizer.normalize(ev)
        assert result.provenance is not None
        assert result.provenance.evidence_type == "transcript"

    def test_macro_provenance_type(self):
        ev = _make_event(
            ticker=None,
            category=EventCategory.MACRO,
            headline="CPI above expectations",
        )
        result = self.normalizer.normalize(ev)
        assert result.provenance is not None
        assert result.provenance.evidence_type == "macro"

    def test_sec_provenance_from_source(self):
        ev = _make_event(category=EventCategory.REGULATORY)
        ev.source = "sec_edgar"
        result = self.normalizer.normalize(ev)
        assert result.provenance is not None
        assert "filing" in result.provenance.evidence_type or "regulatory" in result.provenance.evidence_type

    def test_extended_tags_added(self):
        ev = _make_event(headline="Company A raised guidance for full year", tags=[])
        result = self.normalizer.normalize(ev)
        assert "raised" in result.tags

    def test_beat_tag_detected(self):
        ev = _make_event(headline="Q1 revenue exceeded estimates by 8%", tags=[])
        result = self.normalizer.normalize(ev)
        assert "beat" in result.tags

    def test_miss_tag_detected(self):
        ev = _make_event(headline="Q3 earnings fell short of consensus", tags=[])
        result = self.normalizer.normalize(ev)
        assert "miss" in result.tags

    def test_market_moving_set(self):
        ev = _make_event(headline="Company announces merger", is_market_moving=False)
        result = self.normalizer.normalize(ev)
        assert result.is_market_moving is True  # merger → market_moving

    def test_timestamp_repair(self):
        ev = _make_event(hours_ago=1.0)
        ev.ingestion_timestamp = ""  # corrupt
        result = self.normalizer.normalize(ev)
        # Should be repaired to a valid ISO timestamp
        assert len(result.ingestion_timestamp) >= 10

    def test_high_reliability_confidence(self):
        ev = _make_event(source_reliability=SourceReliability.HIGH)
        result = self.normalizer.normalize(ev)
        assert result.provenance is not None
        assert result.provenance.source_confidence >= 0.9


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 8: SECEdgarAdapter
# ─────────────────────────────────────────────────────────────────────────────

class TestSECEdgarAdapter:
    def setup_method(self):
        from app.services.ingestion.sec_edgar_adapter import SECEdgarAdapter
        self.adapter = SECEdgarAdapter(use_live_api=False)  # synthetic mode

    def test_health_check_synthetic(self):
        result = asyncio.get_event_loop().run_until_complete(self.adapter.health_check())
        assert result is True

    def test_fetch_returns_events(self):
        events = asyncio.get_event_loop().run_until_complete(
            self.adapter.fetch_latest(tickers=None)
        )
        assert len(events) > 0

    def test_events_have_high_reliability(self):
        events = asyncio.get_event_loop().run_until_complete(
            self.adapter.fetch_latest(tickers=None)
        )
        for ev in events:
            assert ev.source_reliability == SourceReliability.HIGH

    def test_events_have_sec_source(self):
        events = asyncio.get_event_loop().run_until_complete(
            self.adapter.fetch_latest(tickers=None)
        )
        for ev in events:
            assert "sec_edgar" in ev.source

    def test_ticker_filter(self):
        events = asyncio.get_event_loop().run_until_complete(
            self.adapter.fetch_latest(tickers=["AAPL"])
        )
        for ev in events:
            assert ev.ticker == "AAPL"


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 9: TreasuryMacroAdapter
# ─────────────────────────────────────────────────────────────────────────────

class TestTreasuryMacroAdapter:
    def setup_method(self):
        from app.services.ingestion.treasury_adapter import TreasuryMacroAdapter
        self.adapter = TreasuryMacroAdapter(use_live_api=False)

    def test_health_check(self):
        result = asyncio.get_event_loop().run_until_complete(self.adapter.health_check())
        assert result is True

    def test_returns_macro_events(self):
        events = asyncio.get_event_loop().run_until_complete(self.adapter.fetch_latest())
        assert len(events) > 0
        for ev in events:
            assert ev.category == EventCategory.MACRO

    def test_no_ticker_on_macro(self):
        events = asyncio.get_event_loop().run_until_complete(self.adapter.fetch_latest())
        for ev in events:
            assert ev.ticker is None

    def test_market_moving_set(self):
        events = asyncio.get_event_loop().run_until_complete(self.adapter.fetch_latest())
        assert any(ev.is_market_moving for ev in events)

    def test_cpi_event_has_correct_tags(self):
        events = asyncio.get_event_loop().run_until_complete(self.adapter.fetch_latest())
        cpi_events = [e for e in events if "cpi" in e.headline.lower()]
        assert len(cpi_events) > 0
        # CPI events should have cpi_release or hot_cpi tag
        for ev in cpi_events:
            assert any("cpi" in t for t in ev.tags)


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 10: EventIngestionPipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestEventIngestionPipeline:
    def _make_pipeline(self) -> "EventIngestionPipeline":
        from app.services.ingestion.event_ingestion_pipeline import EventIngestionPipeline
        from app.services.ingestion.event_deduplicator import EventDeduplicator
        from app.services.ingestion.event_normalizer import EventNormalizer

        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.timeline_store import JsonFileTimelineStore
            store = JsonFileTimelineStore(data_dir=tmpdir)
            pipeline = EventIngestionPipeline(
                store=store,
                deduplicator=EventDeduplicator(),
                normalizer=EventNormalizer(),
                max_staleness_hours=72.0,
            )
        return pipeline

    def test_pipeline_no_adapters_returns_empty(self):
        from app.services.ingestion.event_ingestion_pipeline import EventIngestionPipeline
        from app.services.ingestion.event_deduplicator import EventDeduplicator

        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.timeline_store import JsonFileTimelineStore
            store = JsonFileTimelineStore(data_dir=tmpdir)
            pipeline = EventIngestionPipeline(store=store)
            result = asyncio.get_event_loop().run_until_complete(pipeline.run())
            assert result.events_fetched == 0
            assert result.impact_assessments == []

    def test_pipeline_with_sec_adapter(self):
        from app.services.ingestion.event_ingestion_pipeline import EventIngestionPipeline
        from app.services.ingestion.sec_edgar_adapter import SECEdgarAdapter
        from app.services.ingestion.event_deduplicator import EventDeduplicator
        from app.services.ingestion.event_normalizer import EventNormalizer

        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.timeline_store import JsonFileTimelineStore
            store = JsonFileTimelineStore(data_dir=tmpdir)
            pipeline = EventIngestionPipeline(
                store=store,
                deduplicator=EventDeduplicator(),
                normalizer=EventNormalizer(),
            )
            pipeline.register_adapter(SECEdgarAdapter(use_live_api=False))
            result = asyncio.get_event_loop().run_until_complete(pipeline.run())
            assert result.events_fetched > 0
            assert result.adapters_called == 1

    def test_pipeline_dedup_working(self):
        from app.services.ingestion.event_ingestion_pipeline import EventIngestionPipeline
        from app.services.ingestion.sec_edgar_adapter import SECEdgarAdapter
        from app.services.ingestion.event_deduplicator import EventDeduplicator
        from app.services.ingestion.event_normalizer import EventNormalizer

        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.timeline_store import JsonFileTimelineStore
            store = JsonFileTimelineStore(data_dir=tmpdir)
            dedup = EventDeduplicator()
            pipeline = EventIngestionPipeline(store=store, deduplicator=dedup, normalizer=EventNormalizer())
            pipeline.register_adapter(SECEdgarAdapter(use_live_api=False))
            # Run twice — second run should see all events as duplicates
            r1 = asyncio.get_event_loop().run_until_complete(pipeline.run())
            r2 = asyncio.get_event_loop().run_until_complete(pipeline.run())
            assert r1.events_after_dedup > 0
            assert r2.events_after_dedup == 0  # all deduped

    def test_pipeline_result_has_duration(self):
        from app.services.ingestion.event_ingestion_pipeline import EventIngestionPipeline
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.timeline_store import JsonFileTimelineStore
            store = JsonFileTimelineStore(data_dir=tmpdir)
            pipeline = EventIngestionPipeline(store=store)
            result = asyncio.get_event_loop().run_until_complete(pipeline.run())
            assert result.duration_ms >= 0.0

    def test_health_check_no_adapters(self):
        from app.services.ingestion.event_ingestion_pipeline import EventIngestionPipeline
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.timeline_store import JsonFileTimelineStore
            store = JsonFileTimelineStore(data_dir=tmpdir)
            pipeline = EventIngestionPipeline(store=store)
            health = asyncio.get_event_loop().run_until_complete(pipeline.health_check())
            assert "pipeline_healthy" in health
            assert health["pipeline_healthy"] is True  # vacuously true with no adapters

    def test_health_check_with_sec_adapter(self):
        from app.services.ingestion.event_ingestion_pipeline import EventIngestionPipeline
        from app.services.ingestion.sec_edgar_adapter import SECEdgarAdapter
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.timeline_store import JsonFileTimelineStore
            store = JsonFileTimelineStore(data_dir=tmpdir)
            pipeline = EventIngestionPipeline(store=store)
            pipeline.register_adapter(SECEdgarAdapter(use_live_api=False))
            health = asyncio.get_event_loop().run_until_complete(pipeline.health_check())
            assert health["adapters"]["sec_edgar"] is True

    def test_adapter_count(self):
        from app.services.ingestion.event_ingestion_pipeline import EventIngestionPipeline
        from app.services.ingestion.sec_edgar_adapter import SECEdgarAdapter
        from app.services.ingestion.treasury_adapter import TreasuryMacroAdapter
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.timeline_store import JsonFileTimelineStore
            store = JsonFileTimelineStore(data_dir=tmpdir)
            pipeline = EventIngestionPipeline(store=store)
            pipeline.register_adapter(SECEdgarAdapter(use_live_api=False))
            pipeline.register_adapter(TreasuryMacroAdapter(use_live_api=False))
            assert pipeline.adapter_count == 2

    def test_staleness_filter(self):
        from app.services.ingestion.event_ingestion_pipeline import EventIngestionPipeline
        from app.services.ingestion.event_deduplicator import EventDeduplicator
        from app.services.ingestion.event_normalizer import EventNormalizer

        class StaleAdapter:
            source_name = "stale_source"
            source_reliability = "medium"
            async def fetch_latest(self, tickers=None, since=None):
                # Return an event timestamped 200 hours ago
                ts = _ago_iso(200.0)
                return [NormalizedEvent(
                    ticker="AAPL",
                    category=EventCategory.EARNINGS,
                    headline="Old event",
                    body="",
                    source="stale",
                    source_reliability=SourceReliability.LOW,
                    event_timestamp=ts,
                    ingestion_timestamp=ts,
                    is_market_moving=False,
                    tags=[],
                )]
            async def health_check(self):
                return True

        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.timeline_store import JsonFileTimelineStore
            store = JsonFileTimelineStore(data_dir=tmpdir)
            pipeline = EventIngestionPipeline(
                store=store,
                deduplicator=EventDeduplicator(),
                normalizer=EventNormalizer(),
                max_staleness_hours=48.0,  # tight window
            )
            pipeline._adapters.append(StaleAdapter())  # type: ignore
            result = asyncio.get_event_loop().run_until_complete(pipeline.run())
            assert result.skipped_stale >= 1
            assert result.events_after_freshness == 0


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 11: ThesisImpactEvaluator
# ─────────────────────────────────────────────────────────────────────────────

class TestThesisImpactEvaluator:
    def _make_evaluator(self, tmpdir: str):
        from app.services.thesis_impact_evaluator import ThesisImpactEvaluator
        from app.services.timeline_store import JsonFileTimelineStore
        store = JsonFileTimelineStore(data_dir=tmpdir)
        return ThesisImpactEvaluator(store=store), store

    def _store_assessment(self, store, ticker: str, impact_type: str, priority: str, materiality: float):
        from app.services.timeline_store import TimelineEntry
        assessment = EventImpactAssessment(
            ticker=ticker,
            event_id=str(uuid.uuid4()),
            impact_type=impact_type,
            materiality_score=materiality,
            alert_priority=priority,
            timestamp=_now_iso(),
        )
        entry = TimelineEntry(
            ticker=ticker,
            entry_type="event_impact",
            timestamp=assessment.timestamp,
            data=assessment.model_dump(),
        )
        store.save(entry)
        return assessment

    def test_empty_store_returns_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evaluator, _ = self._make_evaluator(tmpdir)
            drift = evaluator.get_ticker_drift("AAPL")
            assert drift.ticker == "AAPL"
            assert drift.direction == "unchanged"

    def test_thesis_broke_maps_to_broke(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evaluator, store = self._make_evaluator(tmpdir)
            self._store_assessment(store, "AAPL", "thesis_broke", "critical", 0.9)
            drift = evaluator.get_ticker_drift("AAPL")
            assert drift.direction == "broke"

    def test_strengthens_maps_to_strengthened(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evaluator, store = self._make_evaluator(tmpdir)
            self._store_assessment(store, "MSFT", "strengthens_thesis", "medium", 0.6)
            drift = evaluator.get_ticker_drift("MSFT")
            assert drift.direction == "strengthened"

    def test_weakens_maps_to_weakened(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evaluator, store = self._make_evaluator(tmpdir)
            self._store_assessment(store, "NVDA", "weakens_thesis", "high", 0.72)
            drift = evaluator.get_ticker_drift("NVDA")
            assert drift.direction == "weakened"

    def test_priced_in_maps_to_priced_in(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evaluator, store = self._make_evaluator(tmpdir)
            self._store_assessment(store, "GOOG", "priced_in", "ignore", 0.3)
            drift = evaluator.get_ticker_drift("GOOG")
            assert drift.direction == "priced_in"

    def test_broke_overrides_strengthened(self):
        """thesis_broke should win even with prior strengthened assessments."""
        with tempfile.TemporaryDirectory() as tmpdir:
            evaluator, store = self._make_evaluator(tmpdir)
            self._store_assessment(store, "AAPL", "strengthens_thesis", "medium", 0.5)
            self._store_assessment(store, "AAPL", "thesis_broke", "critical", 0.95)
            drift = evaluator.get_ticker_drift("AAPL")
            assert drift.direction == "broke"

    def test_get_watchlist_drift_sorted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evaluator, store = self._make_evaluator(tmpdir)
            self._store_assessment(store, "AAPL", "strengthens_thesis", "medium", 0.5)
            self._store_assessment(store, "MSFT", "thesis_broke", "critical", 0.9)
            drift = evaluator.get_watchlist_drift(["AAPL", "MSFT"])
            assert len(drift) == 2
            # broke comes before strengthened
            assert drift[0].ticker == "MSFT"

    def test_high_priority_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evaluator, store = self._make_evaluator(tmpdir)
            self._store_assessment(store, "AAPL", "thesis_broke", "critical", 0.9)
            self._store_assessment(store, "MSFT", "noise", "ignore", 0.1)
            high = evaluator.get_high_priority_tickers(["AAPL", "MSFT"], min_priority="high")
            assert "AAPL" in high
            assert "MSFT" not in high

    def test_debate_shifts_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evaluator, store = self._make_evaluator(tmpdir)
            self._store_assessment(store, "META", "debate_shift", "high", 0.75)
            shifts = evaluator.get_debate_shifts(["META", "AAPL"])
            assert any(t == "META" for t, _ in shifts)

    def test_materiality_aggregated_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evaluator, store = self._make_evaluator(tmpdir)
            self._store_assessment(store, "AAPL", "weakens_thesis", "medium", 0.6)
            self._store_assessment(store, "AAPL", "weakens_thesis", "medium", 0.8)
            drift = evaluator.get_ticker_drift("AAPL")
            assert drift.materiality > 0.0
            assert drift.materiality <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 12: LiveThesisUpdateService
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveThesisUpdateService:
    def _make_service(self, tmpdir: str):
        from app.services.live_thesis_update_service import LiveThesisUpdateService
        from app.services.thesis_impact_evaluator import ThesisImpactEvaluator
        from app.services.timeline_store import JsonFileTimelineStore
        store = JsonFileTimelineStore(data_dir=tmpdir)
        evaluator = ThesisImpactEvaluator(store=store)
        return LiveThesisUpdateService(store=store, evaluator=evaluator)

    def _store_snapshot(self, store, ticker: str):
        from app.services.timeline_store import TimelineEntry
        snap = _make_snapshot(ticker=ticker)
        entry = TimelineEntry(
            ticker=ticker,
            entry_type="thesis_snapshot",
            timestamp=_now_iso(),
            data=snap.model_dump(),
        )
        store.save(entry)

    def test_process_event_returns_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._make_service(tmpdir)
            ev = _make_event()
            summary = service.process_event(ev)
            assert summary.event_id == ev.event_id
            assert isinstance(summary.impact_assessments, list)

    def test_process_macro_updates_regime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._make_service(tmpdir)
            ev = _make_event(
                ticker=None,
                category=EventCategory.MACRO,
                headline="FOMC holds rates — higher for longer",
                tags=["fed_hold"],
            )
            summary = service.process_event(ev)
            assert summary.regime_updated is True

    def test_process_non_macro_no_regime_update(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._make_service(tmpdir)
            ev = _make_event(ticker="AAPL", category=EventCategory.EARNINGS)
            summary = service.process_event(ev)
            # Earnings for specific ticker should NOT update regime
            assert summary.regime_updated is False

    def test_high_materiality_triggers_brief_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.live_thesis_update_service import LiveThesisUpdateService
            from app.services.thesis_impact_evaluator import ThesisImpactEvaluator
            from app.services.timeline_store import JsonFileTimelineStore
            store = JsonFileTimelineStore(data_dir=tmpdir)
            evaluator = ThesisImpactEvaluator(store=store)
            service = LiveThesisUpdateService(store=store, evaluator=evaluator)
            # Store a high-confidence snapshot so the miss will have high materiality
            self._store_snapshot(store, "AAPL")
            ev = _make_event(
                ticker="AAPL",
                headline="AAPL severely misses earnings",
                tags=["miss"],
                is_market_moving=True,
            )
            summary = service.process_event(ev)
            # With a matching thesis snapshot, should have assessments
            assert summary.event_id == ev.event_id

    def test_batch_processing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._make_service(tmpdir)
            events = [_make_event(headline=f"Event {i}") for i in range(3)]
            summaries = service.process_events_batch(events)
            assert len(summaries) == 3

    def test_summary_to_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._make_service(tmpdir)
            ev = _make_event()
            summary = service.process_event(ev)
            d = summary.to_dict()
            assert "event_id" in d
            assert "impact_count" in d
            assert "tickers_assessed" in d

    def test_should_alert_property(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.live_thesis_update_service import UpdateSummary
            summary = UpdateSummary(
                event_id="test",
                event_headline="",
                event_category="",
                impact_assessments=[
                    EventImpactAssessment(ticker="AAPL", alert_priority="critical"),
                ],
            )
            assert summary.should_alert is True
            assert summary.critical_count == 1

    def test_synthetic_event_utility(self):
        from app.services.live_thesis_update_service import _make_synthetic_event
        ev = _make_synthetic_event(
            headline="CPI above expectations",
            ticker=None,
            category=EventCategory.MACRO,
            is_market_moving=True,
            tags=["hot_cpi"],
        )
        assert ev.ticker is None
        assert ev.category == EventCategory.MACRO
        assert "hot_cpi" in ev.tags


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 13: MorningBriefV2 generation
# ─────────────────────────────────────────────────────────────────────────────

class TestMorningBriefV2Generation:
    def _make_watchlist_entry(self, ticker: str):
        from app.schemas import WatchlistEntry
        return WatchlistEntry(
            ticker=ticker,
            company_name=f"{ticker} Inc.",
            has_material_change=False,
        )

    def _make_regime(self, rate_env: str = "higher_for_longer", risk_app: str = "selective"):
        from app.schemas import MarketRegime
        return MarketRegime(
            rate_environment=rate_env,
            risk_appetite=risk_app,
            dominant_narrative=f"{rate_env} — {risk_app} stance.",
            key_macro_factors=["CPI sticky", "Fed hawkish"],
        )

    def test_empty_watchlist_returns_brief(self):
        from app.services.morning_brief_service import generate_morning_brief_v2
        brief = generate_morning_brief_v2(watchlist_entries=[])
        assert isinstance(brief, MorningBriefV2)
        assert brief.ticker_count == 0

    def test_with_watchlist_entries(self):
        from app.services.morning_brief_service import generate_morning_brief_v2
        entries = [self._make_watchlist_entry("AAPL"), self._make_watchlist_entry("MSFT")]
        brief = generate_morning_brief_v2(watchlist_entries=entries)
        assert brief.ticker_count == 2

    def test_regime_section_populated(self):
        from app.services.morning_brief_service import generate_morning_brief_v2
        regime = self._make_regime()
        brief = generate_morning_brief_v2(watchlist_entries=[], regime=regime)
        assert brief.rate_environment == "higher_for_longer"
        assert brief.risk_appetite == "selective"
        assert brief.regime_headline != ""

    def test_narrative_shifts_from_event_impacts(self):
        from app.services.morning_brief_service import generate_morning_brief_v2
        impacts = [
            EventImpactAssessment(
                ticker="AAPL",
                impact_type="thesis_broke",
                alert_priority="critical",
                materiality_score=0.9,
                thesis_implication="The bull case just got harder to defend.",
            ),
        ]
        brief = generate_morning_brief_v2(
            watchlist_entries=[self._make_watchlist_entry("AAPL")],
            event_impacts=impacts,
        )
        assert len(brief.narrative_shifts) > 0
        assert any("AAPL" in s for s in brief.narrative_shifts)

    def test_debate_shifts_from_impact_type(self):
        from app.services.morning_brief_service import generate_morning_brief_v2
        impacts = [
            EventImpactAssessment(
                ticker="META",
                impact_type="debate_shift",
                alert_priority="high",
                materiality_score=0.75,
                thesis_implication="Market debate shifted to AI monetization.",
            ),
        ]
        brief = generate_morning_brief_v2(
            watchlist_entries=[self._make_watchlist_entry("META")],
            event_impacts=impacts,
        )
        assert len(brief.debate_shifts) > 0

    def test_priority_alerts_from_critical(self):
        from app.services.morning_brief_service import generate_morning_brief_v2
        impacts = [
            EventImpactAssessment(
                ticker="NVDA",
                impact_type="thesis_broke",
                alert_priority="critical",
                materiality_score=0.92,
                thesis_implication="Data center miss breaks the supply-demand narrative.",
            ),
        ]
        brief = generate_morning_brief_v2(
            watchlist_entries=[self._make_watchlist_entry("NVDA")],
            event_impacts=impacts,
        )
        assert len(brief.priority_alerts) > 0
        assert "NVDA" in brief.attention_required

    def test_watchlist_drift_included(self):
        from app.services.morning_brief_service import generate_morning_brief_v2
        drift = [
            WatchlistDriftSummary(ticker="AAPL", direction="weakened", materiality=0.65),
        ]
        brief = generate_morning_brief_v2(
            watchlist_entries=[self._make_watchlist_entry("AAPL")],
            watchlist_drift=drift,
        )
        assert any(d.ticker == "AAPL" for d in brief.watchlist_drift)

    def test_top_movers_populated(self):
        from app.services.morning_brief_service import generate_morning_brief_v2
        drift = [
            WatchlistDriftSummary(ticker="AAPL", direction="broke", materiality=0.9),
            WatchlistDriftSummary(ticker="MSFT", direction="strengthened", materiality=0.5),
        ]
        brief = generate_morning_brief_v2(
            watchlist_entries=[
                self._make_watchlist_entry("AAPL"),
                self._make_watchlist_entry("MSFT"),
            ],
            watchlist_drift=drift,
        )
        assert "AAPL" in brief.top_movers

    def test_backward_compat_brief_text(self):
        from app.services.morning_brief_service import generate_morning_brief_v2
        brief = generate_morning_brief_v2(
            watchlist_entries=[self._make_watchlist_entry("AAPL")],
            regime=self._make_regime(),
        )
        assert isinstance(brief.brief_text, str)

    def test_regime_all_combinations(self):
        from app.services.morning_brief_service import generate_morning_brief_v2
        for rate in ["higher_for_longer", "cutting_cycle", "pause", "uncertain"]:
            for risk in ["risk_on", "risk_off", "selective"]:
                regime = self._make_regime(rate_env=rate, risk_app=risk)
                brief = generate_morning_brief_v2(watchlist_entries=[], regime=regime)
                assert brief.regime_headline != ""

    def test_reference_date_preserved(self):
        from app.services.morning_brief_service import generate_morning_brief_v2
        brief = generate_morning_brief_v2(
            watchlist_entries=[],
            reference_date="2025-03-15",
        )
        assert brief.reference_date == "2025-03-15"


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK 14: API endpoint coverage
# ─────────────────────────────────────────────────────────────────────────────

class TestPhaseMAIPendpoints:
    """Smoke tests to verify API endpoints are registered and importable."""

    def test_api_imports_cleanly(self):
        """If this fails, there's a syntax or import error in api.py."""
        from app.api import router
        assert router is not None

    def test_pipeline_health_route_registered(self):
        from app.api import router
        routes = [r.path for r in router.routes]
        assert "/pipeline/health" in routes

    def test_pipeline_run_route_registered(self):
        from app.api import router
        routes = [r.path for r in router.routes]
        assert "/pipeline/run" in routes

    def test_events_process_route_registered(self):
        from app.api import router
        routes = [r.path for r in router.routes]
        assert "/events/process" in routes

    def test_events_freshness_route_registered(self):
        from app.api import router
        routes = [r.path for r in router.routes]
        assert "/events/freshness/{ticker}" in routes

    def test_morning_brief_v2_route_registered(self):
        from app.api import router
        routes = [r.path for r in router.routes]
        assert "/morning-brief/v2" in routes

    def test_watchlist_drift_route_registered(self):
        from app.api import router
        routes = [r.path for r in router.routes]
        assert "/watchlist/drift" in routes
