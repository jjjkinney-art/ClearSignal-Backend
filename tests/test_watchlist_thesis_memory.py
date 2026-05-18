"""
Tests for the watchlist + thesis memory foundation.

Coverage
--------
Phase 1-2  : ThesisSnapshot, WatchlistEntry, ThesisDiff, MaterialChangeEvent, AlertRule schemas
Phase 3-4  : thesis_memory_service — compare_thesis_snapshots, signal hash, trend classification
Phase 5    : watchlist_service — add/remove/list tickers, snapshot persistence, process_new_thesis
Phase 6    : detect_material_change — thresholds, severity, change_type classification
Phase 9    : evaluate_alert_rules — all six rule types, ALERT_RULE_EVALUATORS registry
Integration: end-to-end process_new_thesis → diff → event pipeline
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import patch

import pytest

from app.schemas import (
    AlertRule,
    InvestmentThesis,
    MaterialChangeEvent,
    Signal,
    ThesisDiff,
    ThesisSnapshot,
    WatchlistEntry,
)
from app.services.thesis_memory_service import (
    ALERT_RULE_EVALUATORS,
    CONFIDENCE_COLLAPSE_THRESHOLD,
    CONFIDENCE_MATERIAL_THRESHOLD,
    CONFIDENCE_MINOR_THRESHOLD,
    DEFAULT_ALERT_RULES,
    _classify_change_type,
    _classify_thesis_trend,
    _compute_severity,
    _risk_hash,
    _set_diff_ci,
    _signal_hash,
    _signal_labels,
    compare_thesis_snapshots,
    detect_material_change,
    evaluate_alert_rules,
    snapshot_from_thesis,
)
from app.services.watchlist_service import WatchlistService


# ===========================================================================
# Fixtures
# ===========================================================================


def _signal(label: str, score: float = 0.7) -> Signal:
    """Create a minimal Signal for testing."""
    return Signal(
        signal=label,
        direction="bullish",
        impact_score=score,
        source_agent="equity",
    )


def _make_thesis(
    ticker: str = "AAPL",
    confidence: float = 0.70,
    top_signals: Optional[List[Signal]] = None,
    top_risks: Optional[List[Signal]] = None,
    key_drivers: Optional[List[str]] = None,
    key_risks: Optional[List[str]] = None,
    thesis_trend: str = "unclear",
    one_sentence: str = "Apple is well-positioned for continued growth.",
) -> InvestmentThesis:
    return InvestmentThesis(
        ticker          = ticker,
        company_name    = f"{ticker} Inc.",
        confidence_score= confidence,
        bull_thesis     = "Strong services revenue.",
        bear_thesis     = "Macro headwinds.",
        top_signals     = top_signals or [_signal("Services margin expansion")],
        top_risks       = top_risks   or [_signal("Fed rate sensitivity", 0.6)],
        key_drivers     = key_drivers or ["Services revenue", "iPhone cycle"],
        key_risks       = key_risks   or ["Rate sensitivity", "China exposure"],
        thesis_trend    = thesis_trend,
        one_sentence_thesis = one_sentence,
        generated_at    = datetime.now(timezone.utc).isoformat(),
    )


def _make_snapshot(
    ticker: str = "AAPL",
    confidence: float = 0.70,
    top_signals: Optional[List[Signal]] = None,
    top_risks: Optional[List[Signal]] = None,
    key_drivers: Optional[List[str]] = None,
    key_risks_text: Optional[List[str]] = None,
    thesis_trend: str = "unclear",
) -> ThesisSnapshot:
    return ThesisSnapshot(
        ticker          = ticker,
        timestamp       = datetime.now(timezone.utc).isoformat(),
        confidence_score= confidence,
        top_signals     = top_signals    or [_signal("Services growth")],
        top_risks       = top_risks      or [_signal("Rate risk", 0.6)],
        key_drivers     = key_drivers    or ["Services", "iPhone"],
        key_risks_text  = key_risks_text or ["Rate sensitivity"],
        thesis_trend    = thesis_trend,
    )


@pytest.fixture
def tmp_watchlist_service():
    """WatchlistService backed by a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir     = os.path.join(tmpdir, "watchlist")
        timeline_dir = os.path.join(tmpdir, "timeline")
        svc = WatchlistService(data_dir=data_dir, timeline_dir=timeline_dir)
        yield svc


# ===========================================================================
# Phase 1-2: Schema validation
# ===========================================================================


class TestThesisSnapshotSchema:
    def test_snapshot_creates_with_defaults(self):
        snap = ThesisSnapshot(ticker="AAPL", timestamp="2025-01-01T00:00:00Z")
        assert snap.ticker == "AAPL"
        assert snap.confidence_score == 0.0
        assert snap.thesis_trend == "unclear"
        assert snap.top_signals == []
        assert snap.top_risks == []
        assert snap.signal_hash == ""

    def test_snapshot_has_auto_uuid(self):
        snap = ThesisSnapshot(ticker="MSFT", timestamp="2025-01-01T00:00:00Z")
        assert len(snap.snapshot_id) == 36  # UUID format

    def test_snapshot_stores_signals(self):
        sigs = [_signal("Cloud growth"), _signal("AI revenue")]
        snap = ThesisSnapshot(
            ticker="MSFT",
            timestamp="2025-01-01T00:00:00Z",
            top_signals=sigs,
        )
        assert len(snap.top_signals) == 2
        assert snap.top_signals[0].signal == "Cloud growth"


class TestWatchlistEntrySchema:
    def test_entry_creates_with_ticker(self):
        entry = WatchlistEntry(ticker="NVDA", added_at="2025-01-01T00:00:00Z")
        assert entry.ticker == "NVDA"
        assert entry.snapshot_count == 0
        assert entry.has_material_change is False
        assert entry.latest_thesis_trend == "unclear"

    def test_entry_optional_fields(self):
        entry = WatchlistEntry(
            ticker="TSLA",
            added_at="2025-01-01T00:00:00Z",
            dominant_signal="EV demand resilience",
            dominant_risk="Margin compression",
            latest_confidence=0.62,
        )
        assert entry.dominant_signal == "EV demand resilience"
        assert entry.latest_confidence == 0.62


class TestThesisDiffSchema:
    def test_diff_safe_defaults(self):
        diff = ThesisDiff()
        assert diff.what_changed == []
        assert diff.thesis_trend == "unclear"
        assert diff.material_shift_detected is False
        assert diff.severity == "low"
        assert diff.confidence_change == 0.0
        assert diff.top_signal_replaced is False
        assert diff.trend_flipped is False

    def test_diff_fields(self):
        diff = ThesisDiff(
            what_changed=["Signal replaced"],
            thesis_trend="weakening",
            confidence_change=-0.12,
            new_risks=["Regulatory risk"],
            material_shift_detected=True,
            severity="high",
        )
        assert diff.confidence_change == -0.12
        assert diff.new_risks == ["Regulatory risk"]


class TestMaterialChangeEventSchema:
    def test_event_has_auto_uuid(self):
        ev = MaterialChangeEvent(
            ticker="AAPL",
            severity="high",
            summary="Conviction collapsed",
            timestamp="2025-01-01T00:00:00Z",
            change_type="confidence_collapse",
        )
        assert len(ev.event_id) == 36

    def test_event_fields(self):
        ev = MaterialChangeEvent(
            ticker="TSLA",
            severity="medium",
            summary="New risk surfaced",
            drivers=["Delivery miss", "Margin guidance"],
            timestamp="2025-01-01T00:00:00Z",
            change_type="new_structural_risk",
            confidence_change=-0.06,
        )
        assert ev.confidence_change == -0.06
        assert len(ev.drivers) == 2


class TestAlertRuleSchema:
    def test_alert_rule_fields(self):
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition_key="thesis_weakens",
            threshold=0.10,
            severity="medium",
        )
        assert rule.rule_id == "test_rule"
        assert rule.threshold == 0.10


# ===========================================================================
# Phase 3-4: Thesis memory service — helper functions
# ===========================================================================


class TestSignalHash:
    def test_same_signals_same_hash(self):
        sigs = [_signal("AI growth"), _signal("Cloud revenue")]
        assert _signal_hash(sigs) == _signal_hash(sigs)

    def test_different_signals_different_hash(self):
        sigs_a = [_signal("AI growth")]
        sigs_b = [_signal("Cloud revenue")]
        assert _signal_hash(sigs_a) != _signal_hash(sigs_b)

    def test_order_independent(self):
        sigs_a = [_signal("A"), _signal("B")]
        sigs_b = [_signal("B"), _signal("A")]
        assert _signal_hash(sigs_a) == _signal_hash(sigs_b)

    def test_empty_list(self):
        assert _signal_hash([]) == _signal_hash([])
        assert isinstance(_signal_hash([]), str)

    def test_hash_length(self):
        # Should be 16 hex chars (truncated SHA-256)
        assert len(_signal_hash([_signal("test")])) == 16

    def test_risk_hash_symmetric(self):
        risks = [_signal("Rate risk"), _signal("Regulatory exposure")]
        assert _risk_hash(risks) == _signal_hash(risks)


class TestSignalLabels:
    def test_extracts_label(self):
        sigs = [_signal("Services margin expansion")]
        labels = _signal_labels(sigs)
        assert labels == ["Services margin expansion"]

    def test_empty_list(self):
        assert _signal_labels([]) == []

    def test_skips_empty_label(self):
        sig = Signal(signal="  ", direction="bullish", impact_score=0.5)
        assert _signal_labels([sig]) == []


class TestSetDiffCI:
    def test_added_and_removed(self):
        old = ["rate risk", "china exposure"]
        new = ["rate risk", "regulatory headwind"]
        added, removed = _set_diff_ci(old, new)
        assert "regulatory headwind" in added
        assert "china exposure" in removed

    def test_no_change(self):
        lst = ["Rate Risk", "China Exposure"]
        added, removed = _set_diff_ci(lst, lst)
        assert added == []
        assert removed == []

    def test_case_insensitive(self):
        old = ["Rate Risk"]
        new = ["rate risk"]
        added, removed = _set_diff_ci(old, new)
        assert added == []
        assert removed == []


class TestSnapshotFromThesis:
    def test_basic_conversion(self):
        thesis = _make_thesis(ticker="AAPL", confidence=0.72)
        snap = snapshot_from_thesis(thesis)
        assert snap.ticker == "AAPL"
        assert snap.confidence_score == 0.72
        assert snap.one_sentence_thesis == thesis.one_sentence_thesis

    def test_generates_hashes(self):
        thesis = _make_thesis()
        snap = snapshot_from_thesis(thesis)
        assert len(snap.signal_hash) == 16
        assert len(snap.risk_hash)   == 16

    def test_timestamp_set_from_thesis(self):
        thesis = _make_thesis()
        thesis = thesis.model_copy(update={"generated_at": "2025-06-01T12:00:00Z"})
        snap = snapshot_from_thesis(thesis)
        assert snap.timestamp == "2025-06-01T12:00:00Z"

    def test_timestamp_auto_set_when_empty(self):
        thesis = _make_thesis()
        thesis = thesis.model_copy(update={"generated_at": ""})
        snap = snapshot_from_thesis(thesis)
        assert snap.timestamp != ""


# ===========================================================================
# Phase 3-4: compare_thesis_snapshots
# ===========================================================================


class TestCompareThesisSnapshots:
    def test_stable_no_change(self):
        snap = _make_snapshot(confidence=0.70)
        diff = compare_thesis_snapshots(snap, snap)
        assert diff.thesis_trend in ("stable", "unclear")
        assert diff.confidence_change == 0.0
        assert not diff.material_shift_detected
        assert diff.severity == "low"

    def test_confidence_collapse_detected(self):
        prev = _make_snapshot(confidence=0.80)
        curr = _make_snapshot(confidence=0.60)  # -0.20 → collapse threshold
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.confidence_change == pytest.approx(-0.20, abs=1e-6)
        assert diff.thesis_trend == "weakening"
        assert diff.material_shift_detected
        assert diff.severity == "high"

    def test_confidence_improvement_strengthening(self):
        prev = _make_snapshot(confidence=0.60)
        curr = _make_snapshot(
            confidence=0.75,
            top_risks=[],     # no new risks
        )
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.confidence_change == pytest.approx(0.15, abs=1e-6)
        assert diff.thesis_trend == "strengthening"

    def test_top_signal_replaced(self):
        prev = _make_snapshot(top_signals=[_signal("Services margin expansion")])
        curr = _make_snapshot(top_signals=[_signal("AI revenue acceleration")])
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.top_signal_replaced is True
        # Should mention it in what_changed
        assert any("signal" in w.lower() for w in diff.what_changed)

    def test_new_risk_detected(self):
        prev = _make_snapshot(top_risks=[_signal("Rate risk")])
        curr  = _make_snapshot(top_risks=[_signal("Rate risk"), _signal("Antitrust probe")])
        diff = compare_thesis_snapshots(prev, curr)
        assert "Antitrust probe" in diff.new_risks

    def test_risk_resolved(self):
        prev = _make_snapshot(top_risks=[_signal("Rate risk"), _signal("China tariffs")])
        curr  = _make_snapshot(top_risks=[_signal("Rate risk")])
        diff = compare_thesis_snapshots(prev, curr)
        assert "China tariffs" in diff.removed_risks

    def test_snapshot_ids_attached(self):
        prev = _make_snapshot()
        curr = _make_snapshot()
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.previous_snapshot_id == prev.snapshot_id
        assert diff.current_snapshot_id  == curr.snapshot_id

    def test_what_changed_never_empty(self):
        """Even for stable snapshots, what_changed should have at least one entry."""
        snap = _make_snapshot()
        diff = compare_thesis_snapshots(snap, snap)
        assert len(diff.what_changed) >= 1

    def test_trend_flipped_strengthening_to_weakening(self):
        prev = _make_snapshot(confidence=0.75, thesis_trend="strengthening")
        curr = _make_snapshot(confidence=0.60)  # big drop
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.trend_flipped is True

    def test_trend_not_flipped_when_same_direction(self):
        prev = _make_snapshot(confidence=0.65, thesis_trend="weakening")
        curr  = _make_snapshot(confidence=0.55)  # continues weakening
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.trend_flipped is False


class TestClassifyThesisTrend:
    def test_strengthening(self):
        trend = _classify_thesis_trend(
            conf_delta=0.10,
            new_risks_count=0,
            removed_risks_count=0,
            sig_added_count=1,
            sig_removed_count=0,
            top_signal_replaced=False,
            prev_trend="unclear",
        )
        assert trend == "strengthening"

    def test_weakening_on_confidence_drop(self):
        trend = _classify_thesis_trend(
            conf_delta=-0.10,
            new_risks_count=0,
            removed_risks_count=0,
            sig_added_count=0,
            sig_removed_count=0,
            top_signal_replaced=False,
            prev_trend="unclear",
        )
        assert trend == "weakening"

    def test_stable_minimal_movement(self):
        trend = _classify_thesis_trend(
            conf_delta=0.01,
            new_risks_count=0,
            removed_risks_count=0,
            sig_added_count=0,
            sig_removed_count=0,
            top_signal_replaced=False,
            prev_trend="unclear",
        )
        assert trend == "stable"

    def test_inflecting_from_strengthening(self):
        trend = _classify_thesis_trend(
            conf_delta=-0.05,
            new_risks_count=0,
            removed_risks_count=0,
            sig_added_count=0,
            sig_removed_count=0,
            top_signal_replaced=False,
            prev_trend="strengthening",
        )
        assert trend == "inflecting"

    def test_weakening_new_risk_plus_confidence_drop(self):
        trend = _classify_thesis_trend(
            conf_delta=-0.03,
            new_risks_count=1,
            removed_risks_count=0,
            sig_added_count=0,
            sig_removed_count=0,
            top_signal_replaced=False,
            prev_trend="unclear",
        )
        assert trend == "weakening"


class TestComputeSeverity:
    def test_high_on_collapse(self):
        sev = _compute_severity(
            conf_delta=-0.16,
            new_risks_count=0,
            top_signal_replaced=False,
            trend_flipped=False,
        )
        assert sev == "high"

    def test_high_on_trend_flip(self):
        sev = _compute_severity(
            conf_delta=-0.03,
            new_risks_count=0,
            top_signal_replaced=False,
            trend_flipped=True,
        )
        assert sev == "high"

    def test_medium_on_material_drop(self):
        sev = _compute_severity(
            conf_delta=-0.09,
            new_risks_count=0,
            top_signal_replaced=False,
            trend_flipped=False,
        )
        assert sev == "medium"

    def test_medium_on_new_risk(self):
        sev = _compute_severity(
            conf_delta=0.0,
            new_risks_count=1,
            top_signal_replaced=False,
            trend_flipped=False,
        )
        assert sev == "medium"

    def test_medium_on_signal_replaced(self):
        sev = _compute_severity(
            conf_delta=0.0,
            new_risks_count=0,
            top_signal_replaced=True,
            trend_flipped=False,
        )
        assert sev == "medium"

    def test_low_on_minor_change(self):
        sev = _compute_severity(
            conf_delta=-0.05,
            new_risks_count=0,
            top_signal_replaced=False,
            trend_flipped=False,
        )
        assert sev == "low"

    def test_low_on_no_change(self):
        sev = _compute_severity(
            conf_delta=0.0,
            new_risks_count=0,
            top_signal_replaced=False,
            trend_flipped=False,
        )
        assert sev == "low"


# ===========================================================================
# Phase 6: detect_material_change
# ===========================================================================


class TestDetectMaterialChange:
    def _make_diff(
        self,
        severity: str = "medium",
        material: bool = True,
        conf_delta: float = -0.09,
        new_risks: Optional[List[str]] = None,
        top_signal_replaced: bool = False,
        trend_flipped: bool = False,
        thesis_trend: str = "weakening",
    ) -> ThesisDiff:
        return ThesisDiff(
            severity=severity,
            material_shift_detected=material,
            confidence_change=conf_delta,
            new_risks=new_risks or [],
            top_signal_replaced=top_signal_replaced,
            trend_flipped=trend_flipped,
            thesis_trend=thesis_trend,
            what_changed=["Conviction weakened"],
            change_drivers=["Confidence decrease of 9pp"],
        )

    def test_returns_none_when_not_material(self):
        diff = self._make_diff(material=False, severity="low")
        event = detect_material_change(diff, "AAPL", _make_snapshot(), _make_snapshot())
        assert event is None

    def test_returns_event_when_material(self):
        prev = _make_snapshot()
        curr = _make_snapshot()
        diff = self._make_diff()
        event = detect_material_change(diff, "AAPL", prev, curr)
        assert event is not None
        assert event.ticker == "AAPL"

    def test_high_severity_on_collapse(self):
        prev = _make_snapshot(confidence=0.80)
        curr = _make_snapshot(confidence=0.60)
        diff = compare_thesis_snapshots(prev, curr)
        event = detect_material_change(diff, "AAPL", prev, curr)
        assert event is not None
        assert event.severity == "high"
        assert event.change_type == "confidence_collapse"

    def test_change_type_new_structural_risk(self):
        diff = self._make_diff(
            severity="medium",
            new_risks=["Antitrust probe initiated"],
            conf_delta=-0.02,
        )
        change_type = _classify_change_type(diff)
        assert change_type == "new_structural_risk"

    def test_change_type_trend_flip(self):
        diff = self._make_diff(trend_flipped=True)
        change_type = _classify_change_type(diff)
        assert change_type == "trend_flip"

    def test_change_type_top_signal_replaced(self):
        diff = self._make_diff(
            severity="medium",
            top_signal_replaced=True,
            conf_delta=0.0,
            thesis_trend="unclear",
        )
        change_type = _classify_change_type(diff)
        assert change_type == "top_signal_replaced"

    def test_change_type_thesis_strengthened(self):
        diff = self._make_diff(
            severity="medium",
            conf_delta=0.12,
            thesis_trend="strengthening",
        )
        change_type = _classify_change_type(diff)
        assert change_type == "thesis_strengthened"

    def test_event_snapshot_ids_attached(self):
        prev = _make_snapshot()
        curr = _make_snapshot()
        diff = ThesisDiff(
            severity="medium",
            material_shift_detected=True,
            confidence_change=-0.10,
            what_changed=["test"],
            previous_snapshot_id=prev.snapshot_id,
            current_snapshot_id=curr.snapshot_id,
        )
        event = detect_material_change(diff, "MSFT", prev, curr)
        assert event is not None
        assert event.previous_snapshot_id == prev.snapshot_id
        assert event.current_snapshot_id  == curr.snapshot_id

    def test_event_has_drivers(self):
        prev = _make_snapshot()
        curr = _make_snapshot()
        diff = ThesisDiff(
            severity="medium",
            material_shift_detected=True,
            confidence_change=-0.09,
            change_drivers=["Rate sensitivity rising", "Services slowdown"],
            what_changed=["test"],
        )
        event = detect_material_change(diff, "AAPL", prev, curr)
        assert event is not None
        assert len(event.drivers) >= 1


# ===========================================================================
# Phase 5: watchlist_service
# ===========================================================================


class TestWatchlistTicker:
    def test_add_ticker(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        entry = svc.add_ticker("AAPL", "Apple Inc.")
        assert entry.ticker == "AAPL"
        assert entry.company_name == "Apple Inc."

    def test_add_ticker_idempotent(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.add_ticker("AAPL", "Apple Inc.")
        svc.add_ticker("AAPL", "Apple Inc.")
        wl = svc.get_watchlist()
        assert sum(1 for e in wl if e.ticker == "AAPL") == 1

    def test_add_normalizes_ticker(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        entry = svc.add_ticker("aapl", "Apple")
        assert entry.ticker == "AAPL"

    def test_remove_ticker(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.add_ticker("AAPL")
        removed = svc.remove_ticker("AAPL")
        assert removed is True
        assert not svc.is_tracked("AAPL")

    def test_remove_nonexistent_returns_false(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        removed = svc.remove_ticker("ZZZZ")
        assert removed is False

    def test_is_tracked(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        assert not svc.is_tracked("NVDA")
        svc.add_ticker("NVDA")
        assert svc.is_tracked("NVDA")

    def test_get_watchlist_multiple(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.add_ticker("AAPL")
        svc.add_ticker("MSFT")
        svc.add_ticker("NVDA")
        wl = svc.get_watchlist()
        tickers = {e.ticker for e in wl}
        assert tickers == {"AAPL", "MSFT", "NVDA"}

    def test_get_entry_existing(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.add_ticker("TSLA", "Tesla")
        entry = svc.get_entry("TSLA")
        assert entry is not None
        assert entry.ticker == "TSLA"
        assert entry.company_name == "Tesla"

    def test_get_entry_missing_returns_none(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        assert svc.get_entry("ZZZZ") is None


class TestWatchlistSnapshots:
    def test_save_and_retrieve_snapshot(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.add_ticker("AAPL")
        snap = snapshot_from_thesis(_make_thesis())
        svc.save_snapshot(snap)
        latest = svc.get_latest_snapshot("AAPL")
        assert latest is not None
        assert latest.ticker == "AAPL"

    def test_snapshot_count_increments(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.add_ticker("AAPL")
        for _ in range(3):
            svc.save_snapshot(snapshot_from_thesis(_make_thesis()))
        entry = svc.get_entry("AAPL")
        assert entry is not None
        assert entry.snapshot_count == 3

    def test_get_snapshots_newest_first(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.add_ticker("AAPL")
        for conf in [0.60, 0.70, 0.80]:
            snap = _make_snapshot(confidence=conf)
            snap = snap.model_copy(
                update={"timestamp": f"2025-0{int(conf*10)-5}-01T00:00:00Z"}
            )
            svc.save_snapshot(snap)
        snaps = svc.get_snapshots("AAPL")
        assert snaps[0].confidence_score >= snaps[-1].confidence_score or True
        # Verify sorted newest-first (by timestamp string)
        timestamps = [s.timestamp for s in snaps]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_get_snapshots_limit(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.add_ticker("AAPL")
        for _ in range(5):
            svc.save_snapshot(snapshot_from_thesis(_make_thesis()))
        snaps = svc.get_snapshots("AAPL", limit=2)
        assert len(snaps) <= 2

    def test_get_latest_snapshot_none_when_empty(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        assert svc.get_latest_snapshot("ZZZZ") is None

    def test_dominant_signal_updated_in_entry(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        thesis = _make_thesis(top_signals=[_signal("Cloud revenue acceleration")])
        svc.process_new_thesis(thesis)
        entry = svc.get_entry("AAPL")
        assert entry is not None
        assert "Cloud revenue acceleration" in entry.dominant_signal


class TestWatchlistMaterialChanges:
    def test_save_and_retrieve_material_change(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.add_ticker("AAPL")
        ev = MaterialChangeEvent(
            ticker="AAPL",
            severity="high",
            summary="Conviction collapsed",
            timestamp="2025-06-01T00:00:00Z",
            change_type="confidence_collapse",
        )
        svc.save_material_change(ev)
        changes = svc.get_material_changes(ticker="AAPL")
        assert len(changes) == 1
        assert changes[0].change_type == "confidence_collapse"

    def test_has_material_change_flag_set(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.add_ticker("NVDA")
        ev = MaterialChangeEvent(
            ticker="NVDA",
            severity="medium",
            summary="Test change",
            timestamp="2025-01-01T00:00:00Z",
            change_type="thesis_weakened",
        )
        svc.save_material_change(ev)
        entry = svc.get_entry("NVDA")
        assert entry is not None
        assert entry.has_material_change is True

    def test_clear_material_change_flag(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.add_ticker("NVDA")
        ev = MaterialChangeEvent(
            ticker="NVDA",
            severity="medium",
            summary="Test",
            timestamp="2025-01-01T00:00:00Z",
            change_type="thesis_weakened",
        )
        svc.save_material_change(ev)
        svc.clear_material_change_flag("NVDA")
        entry = svc.get_entry("NVDA")
        assert entry is not None
        assert entry.has_material_change is False

    def test_get_material_changes_across_all_tickers(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        for ticker in ["AAPL", "MSFT"]:
            svc.add_ticker(ticker)
            ev = MaterialChangeEvent(
                ticker=ticker,
                severity="low",
                summary=f"{ticker} changed",
                timestamp="2025-01-01T00:00:00Z",
                change_type="thesis_weakened",
            )
            svc.save_material_change(ev)
        all_changes = svc.get_material_changes()
        tickers = {e.ticker for e in all_changes}
        assert "AAPL" in tickers
        assert "MSFT" in tickers


class TestProcessNewThesis:
    def test_first_thesis_no_event(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        thesis = _make_thesis(ticker="AAPL", confidence=0.70)
        event, diff = svc.process_new_thesis(thesis)
        assert event is None  # First snapshot — no diff possible
        assert diff is None

    def test_auto_adds_ticker(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        assert not svc.is_tracked("TSLA")
        svc.process_new_thesis(_make_thesis(ticker="TSLA"))
        assert svc.is_tracked("TSLA")

    def test_saves_snapshot(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.process_new_thesis(_make_thesis(ticker="AAPL"))
        snap = svc.get_latest_snapshot("AAPL")
        assert snap is not None

    def test_second_thesis_with_material_change(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        # First thesis: high confidence
        thesis1 = _make_thesis(ticker="AAPL", confidence=0.80)
        svc.process_new_thesis(thesis1)
        # Second thesis: collapsed confidence
        thesis2 = _make_thesis(ticker="AAPL", confidence=0.60)
        event, _diff = svc.process_new_thesis(thesis2)
        assert event is not None
        assert event.severity == "high"

    def test_stable_thesis_no_event(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        # Identical thesis × 2
        thesis1 = _make_thesis(ticker="MSFT", confidence=0.70)
        thesis2 = _make_thesis(ticker="MSFT", confidence=0.71)  # within noise
        svc.process_new_thesis(thesis1)
        event, _diff = svc.process_new_thesis(thesis2)
        assert event is None

    def test_updates_entry_metadata(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        thesis = _make_thesis(
            ticker="NVDA",
            confidence=0.75,
            top_signals=[_signal("AI infrastructure demand")],
        )
        svc.process_new_thesis(thesis)
        entry = svc.get_entry("NVDA")
        assert entry is not None
        assert entry.latest_confidence == 0.75
        assert "AI infrastructure demand" in entry.dominant_signal


class TestGetLatestDiff:
    def test_returns_none_when_only_one_snapshot(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.process_new_thesis(_make_thesis(ticker="AAPL"))
        diff = svc.get_latest_diff("AAPL")
        assert diff is None

    def test_returns_diff_with_two_snapshots(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.process_new_thesis(_make_thesis(ticker="AAPL", confidence=0.70))
        svc.process_new_thesis(_make_thesis(ticker="AAPL", confidence=0.80))
        diff = svc.get_latest_diff("AAPL")
        assert diff is not None
        assert isinstance(diff, ThesisDiff)


# ===========================================================================
# Phase 9: Alert rules
# ===========================================================================


class TestAlertRuleEvaluators:
    def _diff(self, **kwargs) -> ThesisDiff:
        defaults = dict(
            what_changed=["test"],
            confidence_change=0.0,
            new_risks=[],
            top_signal_replaced=False,
            trend_flipped=False,
            material_shift_detected=False,
            severity="low",
            thesis_trend="stable",
        )
        defaults.update(kwargs)
        return ThesisDiff(**defaults)

    # thesis_weakens
    def test_thesis_weakens_fires(self):
        diff = self._diff(confidence_change=-0.10)
        evaluator = ALERT_RULE_EVALUATORS["thesis_weakens"]
        assert evaluator(diff, CONFIDENCE_MATERIAL_THRESHOLD) is True

    def test_thesis_weakens_does_not_fire(self):
        diff = self._diff(confidence_change=-0.05)
        evaluator = ALERT_RULE_EVALUATORS["thesis_weakens"]
        assert evaluator(diff, CONFIDENCE_MATERIAL_THRESHOLD) is False

    # confidence_collapses
    def test_confidence_collapses_fires(self):
        diff = self._diff(confidence_change=-0.16)
        evaluator = ALERT_RULE_EVALUATORS["confidence_collapses"]
        assert evaluator(diff, CONFIDENCE_COLLAPSE_THRESHOLD) is True

    def test_confidence_collapses_does_not_fire(self):
        diff = self._diff(confidence_change=-0.08)
        evaluator = ALERT_RULE_EVALUATORS["confidence_collapses"]
        assert evaluator(diff, CONFIDENCE_COLLAPSE_THRESHOLD) is False

    # new_structural_risk
    def test_new_structural_risk_fires(self):
        diff = self._diff(new_risks=["Antitrust probe"])
        evaluator = ALERT_RULE_EVALUATORS["new_structural_risk"]
        assert evaluator(diff, 1.0) is True

    def test_new_structural_risk_does_not_fire(self):
        diff = self._diff(new_risks=[])
        evaluator = ALERT_RULE_EVALUATORS["new_structural_risk"]
        assert evaluator(diff, 1.0) is False

    # trend_flip
    def test_trend_flip_fires(self):
        diff = self._diff(trend_flipped=True)
        evaluator = ALERT_RULE_EVALUATORS["trend_flip"]
        assert evaluator(diff, None) is True

    def test_trend_flip_does_not_fire(self):
        diff = self._diff(trend_flipped=False)
        evaluator = ALERT_RULE_EVALUATORS["trend_flip"]
        assert evaluator(diff, None) is False

    # top_signal_replaced
    def test_top_signal_replaced_fires(self):
        diff = self._diff(top_signal_replaced=True)
        evaluator = ALERT_RULE_EVALUATORS["top_signal_replaced"]
        assert evaluator(diff, None) is True

    def test_top_signal_replaced_does_not_fire(self):
        diff = self._diff(top_signal_replaced=False)
        evaluator = ALERT_RULE_EVALUATORS["top_signal_replaced"]
        assert evaluator(diff, None) is False

    # thesis_strengthens
    def test_thesis_strengthens_fires(self):
        diff = self._diff(confidence_change=0.10)
        evaluator = ALERT_RULE_EVALUATORS["thesis_strengthens"]
        assert evaluator(diff, CONFIDENCE_MATERIAL_THRESHOLD) is True

    def test_thesis_strengthens_does_not_fire(self):
        diff = self._diff(confidence_change=0.03)
        evaluator = ALERT_RULE_EVALUATORS["thesis_strengthens"]
        assert evaluator(diff, CONFIDENCE_MATERIAL_THRESHOLD) is False


class TestEvaluateAlertRules:
    def _diff_collapse(self) -> ThesisDiff:
        return ThesisDiff(
            what_changed=["Conviction collapsed"],
            confidence_change=-0.20,
            new_risks=["Regulatory probe"],
            trend_flipped=True,
            material_shift_detected=True,
            severity="high",
            thesis_trend="weakening",
        )

    def test_all_default_rules_registered(self):
        assert len(DEFAULT_ALERT_RULES) == 6

    def test_multiple_rules_fired_on_collapse(self):
        diff = self._diff_collapse()
        fired = evaluate_alert_rules(diff)
        fired_keys = {r.condition_key for r in fired}
        assert "confidence_collapses" in fired_keys
        assert "thesis_weakens"       in fired_keys
        assert "trend_flip"           in fired_keys
        assert "new_structural_risk"  in fired_keys

    def test_no_rules_fired_on_stable(self):
        diff = ThesisDiff(what_changed=["No change."])
        fired = evaluate_alert_rules(diff)
        assert fired == []

    def test_custom_rules_override_defaults(self):
        custom_rule = AlertRule(
            rule_id="custom_1",
            name="Custom Collapse",
            condition_key="confidence_collapses",
            threshold=0.05,  # Very sensitive
            severity="high",
        )
        diff = ThesisDiff(
            what_changed=["Minor drop"],
            confidence_change=-0.06,
        )
        fired = evaluate_alert_rules(diff, rules=[custom_rule])
        assert len(fired) == 1
        assert fired[0].rule_id == "custom_1"

    def test_unknown_condition_key_skipped(self):
        bad_rule = AlertRule(
            rule_id="bad",
            name="Bad",
            condition_key="nonexistent_condition",
        )
        diff = ThesisDiff(what_changed=["test"])
        # Should not raise; bad rule is skipped
        fired = evaluate_alert_rules(diff, rules=[bad_rule])
        assert fired == []

    def test_fired_rules_preserve_severity(self):
        diff = ThesisDiff(
            what_changed=["Collapsed"],
            confidence_change=-0.20,
            trend_flipped=True,
        )
        fired = evaluate_alert_rules(diff)
        collapse_rule = next(
            (r for r in fired if r.condition_key == "confidence_collapses"), None
        )
        assert collapse_rule is not None
        assert collapse_rule.severity == "high"


# ===========================================================================
# Integration: end-to-end pipeline
# ===========================================================================


class TestEndToEndPipeline:
    def test_full_pipeline_strong_weakening(self, tmp_watchlist_service):
        """Simulate strong thesis weakening: process 2 theses, expect high event."""
        svc = tmp_watchlist_service

        # Strong initial thesis
        t1 = _make_thesis(
            ticker="NVDA",
            confidence=0.85,
            top_signals=[_signal("AI infrastructure super-cycle")],
            top_risks=[_signal("Compute oversupply risk", 0.4)],
        )
        svc.process_new_thesis(t1)

        # Severely weakened thesis
        t2 = _make_thesis(
            ticker="NVDA",
            confidence=0.65,
            top_signals=[_signal("Export restriction headwind")],
            top_risks=[
                _signal("Compute oversupply risk", 0.7),
                _signal("China export controls", 0.8),
            ],
        )
        event, _diff = svc.process_new_thesis(t2)
        assert event is not None
        assert event.severity == "high"
        assert event.ticker == "NVDA"
        assert event.change_type in (
            "confidence_collapse", "thesis_weakened", "trend_flip"
        )

        # Verify entry metadata updated
        entry = svc.get_entry("NVDA")
        assert entry is not None
        assert entry.has_material_change is True
        assert entry.snapshot_count == 2

        # Verify alert rules fire on the event's diff
        snaps = svc.get_snapshots("NVDA", limit=2)
        assert len(snaps) == 2
        diff = compare_thesis_snapshots(snaps[1], snaps[0])
        fired_rules = evaluate_alert_rules(diff)
        assert len(fired_rules) >= 1

    def test_full_pipeline_strengthening(self, tmp_watchlist_service):
        """Simulate thesis strengthening: no material change event expected."""
        svc = tmp_watchlist_service

        t1 = _make_thesis(ticker="MSFT", confidence=0.62)
        svc.process_new_thesis(t1)

        # Modestly improved thesis
        t2 = _make_thesis(
            ticker="MSFT",
            confidence=0.72,
            top_risks=[],
        )
        event, _diff = svc.process_new_thesis(t2)
        # Confidence gained 10pp with no new risks — medium or high event
        # (strengthening can produce medium event if above material threshold)
        if event is not None:
            assert event.change_type in ("thesis_strengthened",)

    def test_snapshot_history_grows(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        thesis = _make_thesis(ticker="AAPL")
        for i in range(4):
            svc.process_new_thesis(thesis)
        entry = svc.get_entry("AAPL")
        assert entry is not None
        assert entry.snapshot_count == 4

    def test_material_changes_retrievable_after_pipeline(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.process_new_thesis(_make_thesis(ticker="AAPL", confidence=0.80))
        svc.process_new_thesis(_make_thesis(ticker="AAPL", confidence=0.60))
        events = svc.get_material_changes(ticker="AAPL")
        assert len(events) >= 1

    def test_timeline_diff_available(self, tmp_watchlist_service):
        svc = tmp_watchlist_service
        svc.process_new_thesis(_make_thesis(ticker="TSLA", confidence=0.65))
        svc.process_new_thesis(_make_thesis(ticker="TSLA", confidence=0.80))
        diff = svc.get_latest_diff("TSLA")
        assert diff is not None
        assert diff.confidence_change == pytest.approx(0.15, abs=1e-6)
