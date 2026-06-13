"""
Phase 10B · Slice 4 — Canonical alert payload tests.

Tests cover:
  - from_watch_alert adapter
  - from_alert adapter
  - from_material_change adapter
  - from_priority_summary adapter
  - severity normalization (all legacy values)
  - alert_type normalization (all legacy values)
  - required keys always present across all adapters
  - stable dict/JSON serialization
  - null-safety (missing optional fields never raise)
  - payload_version = 1
  - is_actionable property
  - raw_refs preservation
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytest


# ---------------------------------------------------------------------------
# Fixtures & minimal legacy types
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _WatchAlert:
    ticker: str
    alert_type: str
    severity: str
    message: str
    prior_value: str = ""
    current_value: str = ""
    conviction_delta: float = 0.0
    generated_at: str = dataclasses.field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _make_alert(**kw) -> Any:
    """Return a minimal schemas.Alert-like object via Pydantic."""
    from app.schemas import Alert
    defaults = dict(
        alert_type="CONVICTION_DROP",
        severity="high",
        reason="Conviction fell 15pp",
        impact_explanation="Thesis is weaker",
        recommended_interpretation="Review before acting",
    )
    defaults.update(kw)
    return Alert(**defaults)


def _make_material_change(**kw) -> Any:
    from app.schemas import MaterialChangeEvent
    defaults = dict(
        ticker="AAPL",
        severity="high",
        summary="Conviction dropped on earnings miss",
        timestamp=datetime.now(timezone.utc).isoformat(),
        change_type="confidence_collapse",
    )
    defaults.update(kw)
    return MaterialChangeEvent(**defaults)


def _make_alert_priority(**kw) -> Any:
    from app.schemas import AlertPriority
    defaults = dict(
        alert_id="ap-001",
        ticker="AAPL",
        priority="high",
        priority_score=0.72,
        reason="Thesis broke; confidence collapsed",
    )
    defaults.update(kw)
    return AlertPriority(**defaults)


REQUIRED_KEYS = {
    "payload_version", "ticker", "alert_type", "severity",
    "title", "summary", "source", "created_at", "raw_refs",
}


# ---------------------------------------------------------------------------
# 1. TestFromWatchAlert
# ---------------------------------------------------------------------------

class TestFromWatchAlert:
    def test_basic_conversion(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="CONVICTION_DROP",
                         severity="high", message="Conviction fell")
        p = from_watch_alert(wa)
        assert p.ticker == "AAPL"
        assert p.source == "watch_alert"

    def test_alert_type_normalized(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="SETUP_DOWNGRADE",
                         severity="high", message="Setup downgraded")
        p = from_watch_alert(wa)
        assert p.alert_type == "SETUP_DOWNGRADE"

    def test_severity_normalized(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="CONVICTION_DROP",
                         severity="HIGH", message="msg")
        p = from_watch_alert(wa)
        assert p.severity == "high"

    def test_message_becomes_summary(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="MSFT", alert_type="DRIVER_SHIFT",
                         severity="medium", message="Driver changed to AI capex")
        p = from_watch_alert(wa)
        assert "AI capex" in p.summary

    def test_raw_refs_preserved(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="CONVICTION_DROP",
                         severity="high", message="msg",
                         prior_value="0.72", current_value="0.55",
                         conviction_delta=-0.17)
        p = from_watch_alert(wa)
        assert p.raw_refs["prior_value"] == "0.72"
        assert p.raw_refs["current_value"] == "0.55"
        assert p.raw_refs["conviction_delta"] == pytest.approx(-0.17)

    def test_ticker_from_kwarg_when_missing(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="", alert_type="STANCE_SHIFT",
                         severity="medium", message="msg")
        p = from_watch_alert(wa, ticker="NVDA")
        assert p.ticker == "NVDA"

    def test_title_includes_ticker(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="TSLA", alert_type="SETUP_UPGRADE",
                         severity="medium", message="msg")
        p = from_watch_alert(wa)
        assert "TSLA" in p.title

    def test_payload_version_is_1(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="CONVICTION_DROP",
                         severity="low", message="msg")
        p = from_watch_alert(wa)
        assert p.payload_version == 1

    def test_all_required_keys_present(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="RISK_REGIME_CHANGE",
                         severity="high", message="msg")
        p = from_watch_alert(wa)
        d = p.to_dict()
        for key in REQUIRED_KEYS:
            assert key in d, f"Missing required key: {key}"


# ---------------------------------------------------------------------------
# 2. TestFromAlert
# ---------------------------------------------------------------------------

class TestFromAlert:
    def test_basic_conversion(self):
        from app.services.watchlist_alert_payload import from_alert
        a = _make_alert()
        p = from_alert(a, ticker="AAPL")
        assert p.ticker == "AAPL"
        assert p.source == "alert"

    def test_alert_type_passed_through(self):
        from app.services.watchlist_alert_payload import from_alert
        a = _make_alert(alert_type="CONVICTION_DROP")
        p = from_alert(a, ticker="AAPL")
        assert p.alert_type == "CONVICTION_DROP"

    def test_severity_normalized(self):
        from app.services.watchlist_alert_payload import from_alert
        a = _make_alert(severity="high")
        p = from_alert(a, ticker="AAPL")
        assert p.severity == "high"

    def test_reason_becomes_summary(self):
        from app.services.watchlist_alert_payload import from_alert
        a = _make_alert(reason="Thesis eroded on tariff risk")
        p = from_alert(a, ticker="AAPL")
        assert "tariff" in p.summary.lower()

    def test_no_ticker_field_required(self):
        from app.services.watchlist_alert_payload import from_alert
        a = _make_alert()
        p = from_alert(a)
        assert p.ticker == ""

    def test_optional_fields_in_raw_refs(self):
        from app.services.watchlist_alert_payload import from_alert
        a = _make_alert(interpretive_summary="This is a structural shift")
        p = from_alert(a, ticker="NVDA")
        assert "interpretive_summary" in p.raw_refs

    def test_all_required_keys_present(self):
        from app.services.watchlist_alert_payload import from_alert
        a = _make_alert()
        p = from_alert(a, ticker="AAPL")
        d = p.to_dict()
        for key in REQUIRED_KEYS:
            assert key in d, f"Missing required key: {key}"

    def test_created_at_override(self):
        from app.services.watchlist_alert_payload import from_alert
        ts = "2026-01-01T00:00:00+00:00"
        a = _make_alert()
        p = from_alert(a, created_at=ts)
        assert p.created_at == ts


# ---------------------------------------------------------------------------
# 3. TestFromMaterialChange
# ---------------------------------------------------------------------------

class TestFromMaterialChange:
    def test_basic_conversion(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change()
        p = from_material_change(ev)
        assert p.ticker == "AAPL"
        assert p.source == "material_change"

    def test_confidence_collapse_maps_to_conviction_drop(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(change_type="confidence_collapse")
        p = from_material_change(ev)
        assert p.alert_type == "CONVICTION_DROP"

    def test_thesis_broke_category_takes_priority(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(
            change_type="confidence_collapse",
            change_category="thesis_broke",
        )
        p = from_material_change(ev)
        assert p.alert_type == "THESIS_BREAK"

    def test_new_risk_emerged_category(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(change_type="stable", change_category="new_risk_emerged")
        p = from_material_change(ev)
        assert p.alert_type == "NEW_RISK"

    def test_market_repriced_category(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(change_type="stable", change_category="market_repriced")
        p = from_material_change(ev)
        assert p.alert_type == "MARKET_REPRICED"

    def test_materiality_score_becomes_priority_score(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(materiality_score=0.75)
        p = from_material_change(ev)
        assert p.priority_score == pytest.approx(0.75)

    def test_event_id_becomes_delta_id(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change()
        p = from_material_change(ev)
        assert p.delta_id is not None
        assert len(p.delta_id) > 0

    def test_current_snapshot_id_becomes_thesis_version_id(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(current_snapshot_id="snap-001")
        p = from_material_change(ev)
        assert p.thesis_version_id == "snap-001"

    def test_summary_preserved(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(summary="Earnings miss broke thesis trajectory")
        p = from_material_change(ev)
        assert "Earnings miss" in p.summary

    def test_drivers_in_raw_refs(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(drivers=["capex cut", "margin compression"])
        p = from_material_change(ev)
        assert "capex cut" in p.raw_refs["drivers"]

    def test_trend_flip_alert_type(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(change_type="trend_flip")
        p = from_material_change(ev)
        assert p.alert_type == "TREND_FLIP"

    def test_top_signal_replaced_maps_to_driver_shift(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(change_type="top_signal_replaced")
        p = from_material_change(ev)
        assert p.alert_type == "DRIVER_SHIFT"

    def test_all_required_keys_present(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change()
        p = from_material_change(ev)
        d = p.to_dict()
        for key in REQUIRED_KEYS:
            assert key in d, f"Missing required key: {key}"


# ---------------------------------------------------------------------------
# 4. TestFromPrioritySummary
# ---------------------------------------------------------------------------

class TestFromPrioritySummary:
    def test_basic_conversion(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority()
        p = from_priority_summary(ap)
        assert p.ticker == "AAPL"
        assert p.source == "priority_summary"

    def test_high_priority_maps_to_high_alert_type(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(priority="high")
        p = from_priority_summary(ap)
        assert p.alert_type == "HIGH_PRIORITY"
        assert p.severity == "high"

    def test_critical_priority_maps_correctly(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(priority="critical", priority_score=0.85)
        p = from_priority_summary(ap)
        assert p.alert_type == "CRITICAL_PRIORITY"
        assert p.severity == "critical"

    def test_medium_priority_maps_correctly(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(priority="medium", priority_score=0.30)
        p = from_priority_summary(ap)
        assert p.alert_type == "MEDIUM_PRIORITY"
        assert p.severity == "medium"

    def test_ignore_priority_maps_to_no_action(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(priority="ignore", priority_score=0.05)
        p = from_priority_summary(ap)
        assert p.alert_type == "NO_ACTION"
        assert p.severity == "info"

    def test_reason_becomes_summary(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(reason="Core debate shifted; 3 new risks")
        p = from_priority_summary(ap)
        assert "Core debate" in p.summary

    def test_summary_kwarg_overrides_reason(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(reason="original reason")
        p = from_priority_summary(ap, summary="custom summary")
        assert p.summary == "custom summary"

    def test_priority_score_preserved(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(priority_score=0.63)
        p = from_priority_summary(ap)
        assert p.priority_score == pytest.approx(0.63)

    def test_alert_id_becomes_delta_id(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(alert_id="ap-xyz")
        p = from_priority_summary(ap)
        assert p.delta_id == "ap-xyz"

    def test_ticker_override_kwarg(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(ticker="")
        p = from_priority_summary(ap, ticker="META")
        assert p.ticker == "META"

    def test_all_required_keys_present(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority()
        p = from_priority_summary(ap)
        d = p.to_dict()
        for key in REQUIRED_KEYS:
            assert key in d, f"Missing required key: {key}"


# ---------------------------------------------------------------------------
# 5. TestSeverityNormalization
# ---------------------------------------------------------------------------

class TestSeverityNormalization:
    def test_known_values_pass_through(self):
        from app.services.watchlist_alert_payload import normalize_severity
        for s in ("critical", "high", "medium", "low", "info"):
            assert normalize_severity(s) == s

    def test_case_insensitive(self):
        from app.services.watchlist_alert_payload import normalize_severity
        assert normalize_severity("HIGH") == "high"
        assert normalize_severity("CRITICAL") == "critical"
        assert normalize_severity("Medium") == "medium"

    def test_ignore_maps_to_info(self):
        from app.services.watchlist_alert_payload import normalize_severity
        assert normalize_severity("ignore") == "info"

    def test_warning_maps_to_medium(self):
        from app.services.watchlist_alert_payload import normalize_severity
        assert normalize_severity("warning") == "medium"

    def test_alert_maps_to_high(self):
        from app.services.watchlist_alert_payload import normalize_severity
        assert normalize_severity("alert") == "high"

    def test_empty_string_maps_to_low(self):
        from app.services.watchlist_alert_payload import normalize_severity
        assert normalize_severity("") == "low"

    def test_unknown_string_maps_to_low(self):
        from app.services.watchlist_alert_payload import normalize_severity
        assert normalize_severity("extremely_urgent") == "low"

    def test_none_handled_gracefully(self):
        from app.services.watchlist_alert_payload import normalize_severity
        assert normalize_severity(None) == "low"  # type: ignore


# ---------------------------------------------------------------------------
# 6. TestAlertTypeNormalization
# ---------------------------------------------------------------------------

class TestAlertTypeNormalization:
    def test_watch_alert_types_pass_through(self):
        from app.services.watchlist_alert_payload import normalize_alert_type
        types = [
            ("SETUP_DOWNGRADE", "SETUP_DOWNGRADE"),
            ("SETUP_UPGRADE", "SETUP_UPGRADE"),
            ("CONVICTION_DROP", "CONVICTION_DROP"),
            ("CONVICTION_RISE", "CONVICTION_RISE"),
            ("DRIVER_SHIFT", "DRIVER_SHIFT"),
            ("RISK_REGIME_CHANGE", "RISK_REGIME_CHANGE"),
            ("STALE_TO_FRESH", "STALE_TO_FRESH"),
            ("FRESH_TO_STALE", "FRESH_TO_STALE"),
            ("FRAGILITY_ESCALATION", "FRAGILITY_ESCALATION"),
            ("FRAGILITY_DE_ESCALATION", "FRAGILITY_DE_ESCALATION"),
            ("STANCE_SHIFT", "STANCE_SHIFT"),
        ]
        for raw, expected in types:
            assert normalize_alert_type(raw) == expected, f"Failed for {raw}"

    def test_material_change_types_normalized(self):
        from app.services.watchlist_alert_payload import normalize_alert_type
        assert normalize_alert_type("confidence_collapse") == "CONVICTION_DROP"
        assert normalize_alert_type("top_signal_replaced") == "DRIVER_SHIFT"
        assert normalize_alert_type("trend_flip") == "TREND_FLIP"
        assert normalize_alert_type("new_structural_risk") == "NEW_STRUCTURAL_RISK"
        assert normalize_alert_type("thesis_weakened") == "THESIS_WEAKENED"
        assert normalize_alert_type("thesis_strengthened") == "THESIS_STRENGTHENED"
        assert normalize_alert_type("stable") == "STABLE"
        assert normalize_alert_type("thesis_broke") == "THESIS_BREAK"
        assert normalize_alert_type("market_repriced") == "MARKET_REPRICED"
        assert normalize_alert_type("new_risk_emerged") == "NEW_RISK"
        assert normalize_alert_type("cosmetic") == "COSMETIC"

    def test_case_insensitive(self):
        from app.services.watchlist_alert_payload import normalize_alert_type
        assert normalize_alert_type("CONVICTION_DROP") == "CONVICTION_DROP"
        assert normalize_alert_type("confidence_collapse") == "CONVICTION_DROP"

    def test_empty_string_maps_to_unknown(self):
        from app.services.watchlist_alert_payload import normalize_alert_type
        assert normalize_alert_type("") == "UNKNOWN"

    def test_none_returns_unknown(self):
        from app.services.watchlist_alert_payload import normalize_alert_type
        assert normalize_alert_type(None) == "UNKNOWN"  # type: ignore

    def test_unknown_raw_value_uppercased(self):
        from app.services.watchlist_alert_payload import normalize_alert_type
        result = normalize_alert_type("new_future_type")
        assert result == result.upper()


# ---------------------------------------------------------------------------
# 7. TestRequiredKeys
# ---------------------------------------------------------------------------

class TestRequiredKeys:
    """All adapters must produce REQUIRED_KEYS on every invocation."""

    def _check_keys(self, d: dict) -> None:
        for key in REQUIRED_KEYS:
            assert key in d, f"Missing: {key}"

    def test_from_watch_alert_required_keys(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="CONVICTION_DROP",
                         severity="high", message="msg")
        self._check_keys(from_watch_alert(wa).to_dict())

    def test_from_alert_required_keys(self):
        from app.services.watchlist_alert_payload import from_alert
        self._check_keys(from_alert(_make_alert(), ticker="AAPL").to_dict())

    def test_from_material_change_required_keys(self):
        from app.services.watchlist_alert_payload import from_material_change
        self._check_keys(from_material_change(_make_material_change()).to_dict())

    def test_from_priority_summary_required_keys(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        self._check_keys(from_priority_summary(_make_alert_priority()).to_dict())

    def test_payload_version_always_1(self):
        from app.services.watchlist_alert_payload import (
            from_watch_alert, from_alert, from_material_change, from_priority_summary
        )
        wa = _WatchAlert(ticker="X", alert_type="CONVICTION_DROP", severity="low", message="")
        payloads = [
            from_watch_alert(wa),
            from_alert(_make_alert()),
            from_material_change(_make_material_change()),
            from_priority_summary(_make_alert_priority()),
        ]
        for p in payloads:
            assert p.payload_version == 1

    def test_source_field_correct_per_adapter(self):
        from app.services.watchlist_alert_payload import (
            from_watch_alert, from_alert, from_material_change, from_priority_summary
        )
        wa = _WatchAlert(ticker="X", alert_type="CONVICTION_DROP", severity="low", message="")
        assert from_watch_alert(wa).source == "watch_alert"
        assert from_alert(_make_alert()).source == "alert"
        assert from_material_change(_make_material_change()).source == "material_change"
        assert from_priority_summary(_make_alert_priority()).source == "priority_summary"


# ---------------------------------------------------------------------------
# 8. TestStableSerialization
# ---------------------------------------------------------------------------

class TestStableSerialization:
    def test_to_dict_deterministic(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="CONVICTION_DROP",
                         severity="high", message="msg", generated_at="2026-06-13T00:00:00+00:00")
        d1 = from_watch_alert(wa).to_dict()
        d2 = from_watch_alert(wa).to_dict()
        assert d1 == d2

    def test_to_json_is_valid_json(self):
        from app.services.watchlist_alert_payload import from_material_change
        p = from_material_change(_make_material_change())
        j = p.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_to_json_has_sorted_keys(self):
        from app.services.watchlist_alert_payload import from_material_change
        p = from_material_change(_make_material_change())
        j = p.to_json()
        parsed = json.loads(j)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_to_json_deterministic_across_calls(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change()
        j1 = from_material_change(ev).to_json()
        j2 = from_material_change(ev).to_json()
        # created_at will vary since MaterialChangeEvent.timestamp may differ
        # — compare parsed structures minus created_at
        d1 = {k: v for k, v in json.loads(j1).items() if k != "created_at"}
        d2 = {k: v for k, v in json.loads(j2).items() if k != "created_at"}
        assert d1 == d2

    def test_to_dict_contains_payload_version(self):
        from app.services.watchlist_alert_payload import from_alert
        d = from_alert(_make_alert()).to_dict()
        assert d["payload_version"] == 1


# ---------------------------------------------------------------------------
# 9. TestNullSafety
# ---------------------------------------------------------------------------

class TestNullSafety:
    def test_watch_alert_empty_strings(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="", alert_type="", severity="", message="")
        p = from_watch_alert(wa)
        assert p is not None
        assert p.ticker == ""
        assert p.severity == "low"
        assert p.alert_type == "UNKNOWN"

    def test_material_change_no_snapshot_ids(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change()
        p = from_material_change(ev)
        assert p.thesis_version_id is None or isinstance(p.thesis_version_id, str)

    def test_material_change_no_materiality_score(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(materiality_score=0.0)
        p = from_material_change(ev)
        assert p.priority_score is not None  # 0.0 is valid, not None

    def test_priority_empty_alert_id(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(alert_id="")
        p = from_priority_summary(ap)
        assert p.delta_id is None  # empty string normalized to None

    def test_alert_no_optional_fields(self):
        from app.services.watchlist_alert_payload import from_alert
        from app.schemas import Alert
        a = Alert(
            alert_type="DRIVER_SHIFT",
            severity="medium",
            reason="Signal shifted",
            impact_explanation="Thesis uncertain",
            recommended_interpretation="Hold",
        )
        p = from_alert(a, ticker="META")
        assert p is not None
        assert p.ticker == "META"

    def test_watch_alert_no_conviction_delta(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="FRAGILITY_ESCALATION",
                         severity="high", message="Fragility crossed threshold")
        p = from_watch_alert(wa)
        assert p.raw_refs["conviction_delta"] == 0.0

    def test_material_change_empty_drivers(self):
        from app.services.watchlist_alert_payload import from_material_change
        ev = _make_material_change(drivers=[])
        p = from_material_change(ev)
        assert p.raw_refs["drivers"] == []


# ---------------------------------------------------------------------------
# 10. TestIsActionable
# ---------------------------------------------------------------------------

class TestIsActionable:
    def test_critical_is_actionable(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(priority="critical")
        assert from_priority_summary(ap).is_actionable is True

    def test_high_is_actionable(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="SETUP_DOWNGRADE",
                         severity="high", message="msg")
        assert from_watch_alert(wa).is_actionable is True

    def test_medium_is_actionable(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="DRIVER_SHIFT",
                         severity="medium", message="msg")
        assert from_watch_alert(wa).is_actionable is True

    def test_low_is_not_actionable(self):
        from app.services.watchlist_alert_payload import from_watch_alert
        wa = _WatchAlert(ticker="AAPL", alert_type="STABLE",
                         severity="low", message="msg")
        assert from_watch_alert(wa).is_actionable is False

    def test_info_is_not_actionable(self):
        from app.services.watchlist_alert_payload import from_priority_summary
        ap = _make_alert_priority(priority="ignore")
        assert from_priority_summary(ap).is_actionable is False


# ---------------------------------------------------------------------------
# 11. TestSchemaConstants
# ---------------------------------------------------------------------------

class TestSchemaConstants:
    def test_payload_version_constant(self):
        from app.services.watchlist_alert_payload import PAYLOAD_VERSION
        assert PAYLOAD_VERSION == 1

    def test_source_strings_are_stable(self):
        from app.services.watchlist_alert_payload import (
            from_watch_alert, from_alert, from_material_change, from_priority_summary
        )
        wa = _WatchAlert(ticker="X", alert_type="STABLE", severity="low", message="")
        sources = {
            from_watch_alert(wa).source,
            from_alert(_make_alert()).source,
            from_material_change(_make_material_change()).source,
            from_priority_summary(_make_alert_priority()).source,
        }
        assert sources == {"watch_alert", "alert", "material_change", "priority_summary"}

    def test_all_canonical_alert_type_constants_defined(self):
        import app.services.watchlist_alert_payload as mod
        expected = [
            "AT_SETUP_DOWNGRADE", "AT_SETUP_UPGRADE", "AT_CONVICTION_DROP",
            "AT_CONVICTION_RISE", "AT_DRIVER_SHIFT", "AT_RISK_REGIME_CHANGE",
            "AT_STALE_TO_FRESH", "AT_FRESH_TO_STALE", "AT_FRAGILITY_ESCALATION",
            "AT_FRAGILITY_DE_ESCALATION", "AT_STANCE_SHIFT", "AT_THESIS_BREAK",
            "AT_THESIS_WEAKENED", "AT_THESIS_STRENGTHENED", "AT_NEW_STRUCTURAL_RISK",
            "AT_NEW_RISK", "AT_TREND_FLIP", "AT_MARKET_REPRICED", "AT_COSMETIC",
            "AT_STABLE", "AT_CRITICAL_PRIORITY", "AT_HIGH_PRIORITY",
            "AT_MEDIUM_PRIORITY", "AT_NO_ACTION", "AT_UNKNOWN",
        ]
        for name in expected:
            assert hasattr(mod, name), f"Missing constant: {name}"
