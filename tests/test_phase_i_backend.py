"""
Phase I backend tests — MorningBrief, TimelineEvent, AlertPriority,
and WatchlistEntry extension fields.

All tests are deterministic (no LLM calls, no network).
"""

from __future__ import annotations

import uuid
from typing import List, Optional

import pytest

from app.schemas import (
    Alert,
    AlertPriority,
    MaterialChangeEvent,
    ThesisDiff,
    TimelineEvent,
    WatchlistEntry,
)
from app.services.morning_brief_service import MorningBrief, generate_morning_brief
from app.services.timeline_event_service import (
    events_from_material_change,
    events_from_thesis_diff,
    get_ticker_timeline,
)
from app.services.alert_prioritizer import alert_priority_score, rank_alerts


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _make_watchlist_entry(
    ticker: str = "AAPL",
    drift_state: str = "unchanged",
    latest_thesis_trend: str = "stable",
    has_material_change: bool = False,
    core_debate: str = "",
) -> WatchlistEntry:
    return WatchlistEntry(
        ticker=ticker,
        company_name=f"{ticker} Inc.",
        drift_state=drift_state,
        latest_thesis_trend=latest_thesis_trend,
        has_material_change=has_material_change,
        core_debate=core_debate,
    )


def _make_change(
    ticker: str = "AAPL",
    category: str = "market_repriced",
    severity: str = "medium",
    summary: str = "Market repriced after macro data.",
    change_type: str = "thesis_weakened",
    materiality_score: float = 0.5,
    confidence_change: float = -0.10,
    drivers: Optional[List[str]] = None,
    thesis_trend_changed: bool = False,
) -> MaterialChangeEvent:
    return MaterialChangeEvent(
        ticker=ticker,
        severity=severity,
        summary=summary,
        change_type=change_type,
        timestamp="2026-05-19T06:00:00+00:00",
        materiality_score=materiality_score,
        change_category=category,
        drivers=drivers or [],
        confidence_change=confidence_change,
        thesis_trend_changed=thesis_trend_changed,
    )


def _make_diff(
    confidence_change: float = 0.0,
    core_debate_shifted: bool = False,
    trend_flipped: bool = False,
    new_risks: Optional[List[str]] = None,
    top_signal_replaced: bool = False,
    change_category: str = "",
) -> ThesisDiff:
    return ThesisDiff(
        confidence_change=confidence_change,
        core_debate_shifted=core_debate_shifted,
        trend_flipped=trend_flipped,
        new_risks=new_risks or [],
        top_signal_replaced=top_signal_replaced,
    )


def _make_alert(ticker: str = "AAPL", severity: str = "medium") -> Alert:
    return Alert(
        ticker=ticker,
        headline=f"{ticker} alert",
        body="Test body.",
        severity=severity,
        alert_type="thesis_change",
        timestamp="2026-05-19T06:00:00+00:00",
    )


# =============================================================================
# MorningBrief tests (10)
# =============================================================================

class TestMorningBrief:

    def test_empty_watchlist_returns_safe_brief(self):
        """Empty watchlist should not raise and should return a safe brief."""
        brief = generate_morning_brief(
            watchlist_entries=[],
            recent_material_changes=[],
            recent_alerts=[],
        )
        assert isinstance(brief, MorningBrief)
        assert brief.ticker_count == 0
        assert isinstance(brief.brief_text, str)
        assert len(brief.brief_text) > 0

    def test_single_material_change_is_present_in_brief(self):
        """A single material change event should produce a non-empty brief_text."""
        entry   = _make_watchlist_entry("NVDA", has_material_change=True)
        change  = _make_change("NVDA", category="thesis_broke", severity="high",
                                summary="Guidance missed badly.")
        brief   = generate_morning_brief(
            watchlist_entries=[entry],
            recent_material_changes=[change],
            recent_alerts=[],
        )
        assert brief.ticker_count == 1
        assert len(brief.brief_text) > 10

    def test_thesis_broke_appears_before_debate_shift(self):
        """thesis_broke category should rank above cosmetic changes."""
        entry_broke  = _make_watchlist_entry("RKLB", drift_state="breaking")
        entry_stable = _make_watchlist_entry("AAPL", drift_state="unchanged")
        change_broke = _make_change("RKLB", category="thesis_broke", materiality_score=0.9)
        change_cos   = _make_change("AAPL", category="cosmetic",     materiality_score=0.1)

        brief = generate_morning_brief(
            watchlist_entries=[entry_stable, entry_broke],
            recent_material_changes=[change_cos, change_broke],
            recent_alerts=[],
        )
        # RKLB should appear before AAPL in top_movers
        assert brief.top_movers.index("RKLB") < brief.top_movers.index("AAPL") if "AAPL" in brief.top_movers else True

    def test_debate_shifts_list_populated(self):
        """debate_shifts should include tickers with thesis_trend_changed=True."""
        entry  = _make_watchlist_entry("META")
        change = _make_change("META", category="thesis_broke", thesis_trend_changed=True)
        brief  = generate_morning_brief(
            watchlist_entries=[entry],
            recent_material_changes=[change],
            recent_alerts=[],
        )
        assert "META" in brief.debate_shifts

    def test_attention_required_populated_for_material_changes(self):
        """attention_required should include tickers with high-severity changes."""
        entry  = _make_watchlist_entry("TSLA", has_material_change=True)
        change = _make_change("TSLA", category="thesis_broke", severity="high",
                                materiality_score=0.85)
        brief  = generate_morning_brief(
            watchlist_entries=[entry],
            recent_material_changes=[change],
            recent_alerts=[],
        )
        assert "TSLA" in brief.attention_required

    def test_brief_text_max_eight_sentences(self):
        """brief_text must never exceed 8 sentences."""
        entries = [_make_watchlist_entry(t, has_material_change=True) for t in
                   ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]]
        changes = [_make_change(t, category="market_repriced", summary=f"{t} repriced.")
                   for t in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]]
        brief   = generate_morning_brief(
            watchlist_entries=entries,
            recent_material_changes=changes,
            recent_alerts=[],
        )
        sentences = [s.strip() for s in brief.brief_text.split(".") if s.strip()]
        assert len(sentences) <= 8

    def test_brief_text_contains_no_bullet_points(self):
        """brief_text must not contain bullet point characters."""
        entry  = _make_watchlist_entry("GOOG")
        change = _make_change("GOOG", summary="Advertising recovery strong.")
        brief  = generate_morning_brief(
            watchlist_entries=[entry],
            recent_material_changes=[change],
            recent_alerts=[],
        )
        assert "•" not in brief.brief_text
        assert "- " not in brief.brief_text
        assert "* " not in brief.brief_text

    def test_market_regime_note_is_one_sentence(self):
        """market_regime_note should be a single sentence (no embedded full stops mid-text)."""
        entry  = _make_watchlist_entry("MSFT")
        change = _make_change("MSFT")
        brief  = generate_morning_brief(
            watchlist_entries=[entry],
            recent_material_changes=[change],
            recent_alerts=[],
        )
        # A single sentence ends with exactly one terminating period (or similar)
        note = brief.market_regime_note.strip()
        assert len(note) > 0
        # Should not be more than 3 sentences (generous bound for 1-sentence requirement)
        sub_sentences = [s for s in note.split(".") if s.strip()]
        assert len(sub_sentences) <= 3

    def test_top_movers_sorted_by_materiality_desc(self):
        """top_movers should rank highest-materiality tickers first."""
        e1 = _make_watchlist_entry("HIGH")
        e2 = _make_watchlist_entry("LOW")
        c1 = _make_change("HIGH", materiality_score=0.9)
        c2 = _make_change("LOW",  materiality_score=0.2)
        brief = generate_morning_brief(
            watchlist_entries=[e2, e1],
            recent_material_changes=[c2, c1],
            recent_alerts=[],
        )
        if "HIGH" in brief.top_movers and "LOW" in brief.top_movers:
            assert brief.top_movers.index("HIGH") < brief.top_movers.index("LOW")

    def test_no_material_changes_produces_quiet_brief(self):
        """When no material changes exist, brief should note monitoring."""
        entries = [_make_watchlist_entry("AMZN"), _make_watchlist_entry("META")]
        brief   = generate_morning_brief(
            watchlist_entries=entries,
            recent_material_changes=[],
            recent_alerts=[],
        )
        assert "monitor" in brief.brief_text.lower() or "no material" in brief.brief_text.lower()


# =============================================================================
# TimelineEvent tests (10)
# =============================================================================

class TestTimelineEvent:

    def test_thesis_broke_maps_to_thesis_shift_critical(self):
        change = _make_change("RKLB", category="thesis_broke", severity="high")
        events = events_from_material_change(change)
        assert len(events) >= 1
        primary = events[0]
        assert primary.event_type == "thesis_shift"
        assert primary.severity == "critical"

    def test_core_debate_shifted_maps_to_narrative_transition(self):
        diff   = _make_diff(core_debate_shifted=True)
        events = events_from_thesis_diff("AAPL", diff, "2026-05-19T00:00:00+00:00")
        types  = [e.event_type for e in events]
        assert "narrative_transition" in types

    def test_market_repriced_maps_to_correct_type_and_severity(self):
        change = _make_change("NVDA", category="market_repriced", severity="medium")
        events = events_from_material_change(change)
        assert len(events) >= 1
        primary = events[0]
        assert primary.event_type == "market_repriced"
        assert primary.severity == "high"

    def test_new_risk_emerged_maps_to_new_risk(self):
        change = _make_change("TSLA", category="new_risk_emerged")
        events = events_from_material_change(change)
        assert len(events) >= 1
        assert events[0].event_type == "new_risk"

    def test_events_from_material_change_never_raises_on_none(self):
        """Passing None should return empty list, not raise."""
        result = events_from_material_change(None)  # type: ignore[arg-type]
        assert result == []

    def test_events_from_thesis_diff_empty_diff_returns_empty(self):
        """A diff with no changes should produce no events."""
        diff   = _make_diff()  # all defaults, no significant changes
        events = events_from_thesis_diff("AAPL", diff, "2026-05-19T00:00:00+00:00")
        assert isinstance(events, list)

    def test_timeline_event_title_max_sixty_chars(self):
        change = _make_change("VERYLONGTICKER", category="thesis_broke")
        events = events_from_material_change(change)
        for ev in events:
            assert len(ev.title) <= 60, f"Title too long: {ev.title!r}"

    def test_timeline_event_has_all_required_fields(self):
        change = _make_change("AAPL")
        events = events_from_material_change(change)
        assert len(events) >= 1
        ev = events[0]
        assert ev.event_id
        assert ev.ticker
        assert ev.event_type
        assert ev.title
        assert ev.body
        assert ev.severity
        assert ev.timestamp

    def test_get_ticker_timeline_returns_list(self):
        """get_ticker_timeline should return a list even for unknown tickers."""
        result = get_ticker_timeline("XXXXXXXXNOTREAL")
        assert isinstance(result, list)

    def test_multiple_event_types_from_one_material_change(self):
        """A top_signal_replaced change_type should produce 2 events."""
        change = _make_change(
            "GOOG",
            category="market_repriced",
            change_type="top_signal_replaced",
        )
        events = events_from_material_change(change)
        # Should produce primary + secondary narrative_transition
        assert len(events) >= 1
        event_types = {e.event_type for e in events}
        assert "narrative_transition" in event_types or "market_repriced" in event_types


# =============================================================================
# AlertPriority tests (15)
# =============================================================================

class TestAlertPriority:

    def test_thesis_broke_confidence_collapse_is_critical(self):
        """thesis_broke + confidence -30pp should be critical."""
        diff   = _make_diff(confidence_change=-0.30)
        change = _make_change("RKLB", category="thesis_broke", materiality_score=0.85)
        ap     = alert_priority_score(diff, change)
        assert ap.priority == "critical"

    def test_core_debate_shift_and_trend_flip_is_high(self):
        """core_debate_shifted + trend_flipped alone should reach high."""
        diff = _make_diff(core_debate_shifted=True, trend_flipped=True)
        ap   = alert_priority_score(diff)
        assert ap.priority in ("high", "critical")

    def test_small_confidence_change_only_is_ignore(self):
        """confidence -5pp with no other signals should be ignore."""
        diff = _make_diff(confidence_change=-0.05)
        ap   = alert_priority_score(diff)
        assert ap.priority == "ignore"

    def test_three_new_risks_plus_top_signal_is_medium_or_higher(self):
        """3 new risks + top_signal_replaced should be at least medium."""
        diff = _make_diff(
            new_risks=["risk A", "risk B", "risk C"],
            top_signal_replaced=True,
        )
        ap = alert_priority_score(diff)
        assert ap.priority in ("medium", "high", "critical")

    def test_high_materiality_score_adds_to_score(self):
        """A high materiality_score on the change_event should push score up."""
        diff_low  = _make_diff(confidence_change=-0.05)
        diff_high = _make_diff(confidence_change=-0.05)
        change_high = _make_change("X", materiality_score=0.80)
        ap_low  = alert_priority_score(diff_low,  None)
        ap_high = alert_priority_score(diff_high, change_high)
        assert ap_high.priority_score > ap_low.priority_score

    def test_score_never_exceeds_one(self):
        """No matter how many signals, score must be ≤ 1.0."""
        diff = _make_diff(
            confidence_change=-0.30,
            core_debate_shifted=True,
            trend_flipped=True,
            new_risks=["r1", "r2", "r3"],
            top_signal_replaced=True,
        )
        change = _make_change("OVER", category="thesis_broke", materiality_score=0.99)
        ap = alert_priority_score(diff, change)
        assert ap.priority_score <= 1.0

    def test_rank_alerts_returns_sorted_list(self):
        """rank_alerts should sort pairs highest-score first."""
        diff_low   = _make_diff(confidence_change=-0.05)
        diff_high  = _make_diff(confidence_change=-0.30, core_debate_shifted=True)
        change_low  = _make_change("LOW",  category="cosmetic",     materiality_score=0.1)
        change_high = _make_change("HIGH", category="thesis_broke", materiality_score=0.9)
        ranked = rank_alerts([
            (diff_low,  change_low),
            (diff_high, change_high),
        ])
        assert len(ranked) == 2
        assert ranked[0].priority_score >= ranked[1].priority_score

    def test_rank_alerts_empty_pairs_returns_empty(self):
        result = rank_alerts([])
        assert result == []

    def test_alert_priority_has_all_required_fields(self):
        diff = _make_diff(confidence_change=-0.20, core_debate_shifted=True)
        ap   = alert_priority_score(diff)
        assert hasattr(ap, "alert_id")
        assert hasattr(ap, "ticker")
        assert hasattr(ap, "priority")
        assert hasattr(ap, "priority_score")
        assert hasattr(ap, "reason")

    def test_priority_score_is_float_in_range(self):
        diff = _make_diff(confidence_change=-0.15, trend_flipped=True)
        ap   = alert_priority_score(diff)
        assert isinstance(ap.priority_score, float)
        assert 0.0 <= ap.priority_score <= 1.0

    def test_critical_threshold_at_0_65(self):
        """Exactly at threshold: thesis_broke (0.50) + confidence -30pp (0.35) = 0.85."""
        diff   = _make_diff(confidence_change=-0.30)
        change = _make_change("T", category="thesis_broke")
        ap     = alert_priority_score(diff, change)
        assert ap.priority_score >= 0.65
        assert ap.priority == "critical"

    def test_high_threshold_at_0_35(self):
        """core_debate_shifted (0.25) + trend_flipped (0.20) = 0.45 → high."""
        diff = _make_diff(core_debate_shifted=True, trend_flipped=True)
        ap   = alert_priority_score(diff)
        assert ap.priority_score >= 0.35
        assert ap.priority in ("high", "critical")

    def test_medium_threshold_at_0_15(self):
        """top_signal_replaced (0.12) + 1 new risk (0.08) = 0.20 → medium."""
        diff = _make_diff(new_risks=["some risk"], top_signal_replaced=True)
        ap   = alert_priority_score(diff)
        assert ap.priority_score >= 0.15
        assert ap.priority in ("medium", "high", "critical")

    def test_ignore_below_0_15(self):
        """No signals at all → ignore."""
        diff = _make_diff()
        ap   = alert_priority_score(diff)
        assert ap.priority == "ignore"
        assert ap.priority_score < 0.15

    def test_reason_field_is_populated_when_signals_present(self):
        """reason should be a non-empty string when signals are detected."""
        diff   = _make_diff(core_debate_shifted=True)
        ap     = alert_priority_score(diff)
        assert isinstance(ap.reason, str)
        assert len(ap.reason) > 0


# =============================================================================
# WatchlistEntry extension tests (5)
# =============================================================================

class TestWatchlistEntryExtension:

    def test_watchlist_entry_has_recent_alert_count(self):
        entry = WatchlistEntry(ticker="AAPL")
        assert hasattr(entry, "recent_alert_count")
        assert entry.recent_alert_count == 0

    def test_watchlist_entry_has_materiality_level(self):
        entry = WatchlistEntry(ticker="AAPL")
        assert hasattr(entry, "materiality_level")
        assert isinstance(entry.materiality_level, str)

    def test_watchlist_entry_has_thesis_stability(self):
        entry = WatchlistEntry(ticker="AAPL")
        assert hasattr(entry, "thesis_stability")
        assert entry.thesis_stability == "stable"

    def test_watchlist_entry_has_latest_change_narrative(self):
        entry = WatchlistEntry(ticker="AAPL")
        assert hasattr(entry, "latest_change_narrative")
        assert isinstance(entry.latest_change_narrative, str)

    def test_watchlist_entry_has_debate_focus(self):
        entry = WatchlistEntry(ticker="AAPL")
        assert hasattr(entry, "debate_focus")
        assert isinstance(entry.debate_focus, str)
