"""
Tests for app.services.monitoring — declarative alert-condition evaluation.

All tests are pure (no LLM calls, no network, no I/O).
"""
from __future__ import annotations

import pytest

from app.services.monitoring import (
    evaluate_condition,
    check_conditions,
    YIELD_CURVE_REINVERSION,
    MARGIN_COMPRESSION,
    VOLATILITY_SPIKE,
    VIX_ABOVE_THRESHOLD,
    CREDIT_SPREAD_WIDENING,
)
from app.schemas import AlertCondition, AlertEvent


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _cond(type_, threshold, direction, topic=None, ticker=None, condition_id=""):
    """Build a minimal AlertCondition for test use."""
    return AlertCondition(
        condition_id=condition_id or type_,
        type=type_,
        threshold=threshold,
        direction=direction,
        topic=topic,
        ticker=ticker,
    )


# ---------------------------------------------------------------------------
# TestEvaluateCondition
# ---------------------------------------------------------------------------


class TestEvaluateCondition:
    """Unit tests for evaluate_condition()."""

    # direction = "above"

    def test_above_triggers_when_strictly_greater(self):
        cond = _cond("test", threshold=10.0, direction="above")
        assert evaluate_condition(cond, 10.1) is True

    def test_above_does_not_trigger_when_equal(self):
        cond = _cond("test", threshold=10.0, direction="above")
        assert evaluate_condition(cond, 10.0) is False

    def test_above_does_not_trigger_when_below(self):
        cond = _cond("test", threshold=10.0, direction="above")
        assert evaluate_condition(cond, 9.99) is False

    # direction = "below"

    def test_below_triggers_when_strictly_less(self):
        cond = _cond("test", threshold=5.0, direction="below")
        assert evaluate_condition(cond, 4.99) is True

    def test_below_does_not_trigger_when_equal(self):
        cond = _cond("test", threshold=5.0, direction="below")
        assert evaluate_condition(cond, 5.0) is False

    def test_below_does_not_trigger_when_above(self):
        cond = _cond("test", threshold=5.0, direction="below")
        assert evaluate_condition(cond, 5.01) is False

    # direction = "crosses" with threshold == 0

    def test_crosses_zero_triggers_on_negative_value(self):
        """crosses + threshold=0 should fire when value < 0."""
        cond = _cond("test", threshold=0.0, direction="crosses")
        assert evaluate_condition(cond, -0.01) is True

    def test_crosses_zero_triggers_on_strongly_negative_value(self):
        cond = _cond("test", threshold=0.0, direction="crosses")
        assert evaluate_condition(cond, -5.0) is True

    def test_crosses_zero_does_not_trigger_on_positive_value(self):
        cond = _cond("test", threshold=0.0, direction="crosses")
        assert evaluate_condition(cond, 0.01) is False

    def test_crosses_zero_does_not_trigger_on_exactly_zero(self):
        """Exactly 0.0 should NOT trigger (not strictly below 0)."""
        cond = _cond("test", threshold=0.0, direction="crosses")
        assert evaluate_condition(cond, 0.0) is False

    # direction = "crosses" with non-zero threshold (behaves like "below")

    def test_crosses_nonzero_threshold_behaves_like_below_triggers(self):
        """Non-zero threshold: crosses behaves like 'below'."""
        cond = _cond("test", threshold=3.0, direction="crosses")
        assert evaluate_condition(cond, 2.99) is True

    def test_crosses_nonzero_threshold_behaves_like_below_no_trigger(self):
        cond = _cond("test", threshold=3.0, direction="crosses")
        assert evaluate_condition(cond, 3.0) is False

    def test_crosses_nonzero_threshold_no_trigger_when_above(self):
        cond = _cond("test", threshold=3.0, direction="crosses")
        assert evaluate_condition(cond, 3.01) is False

    # Unknown direction

    def test_unknown_direction_returns_false(self):
        """An unrecognised direction string should return False (safe default)."""
        cond = _cond("test", threshold=0.0, direction="sideways")
        result = evaluate_condition(cond, 100.0)
        # The implementation logs a warning and returns False
        assert result is False


# ---------------------------------------------------------------------------
# TestCheckConditions
# ---------------------------------------------------------------------------


class TestCheckConditions:
    """Integration tests for check_conditions()."""

    def test_empty_conditions_returns_empty_list(self):
        assert check_conditions([], {"T10Y2Y": 0.5}) == []

    def test_empty_readings_returns_empty_list(self):
        cond = _cond(YIELD_CURVE_REINVERSION, threshold=0.0, direction="crosses", topic="T10Y2Y")
        assert check_conditions([cond], {}) == []

    def test_condition_topic_matches_reading_key_and_triggers(self):
        cond = _cond(VIX_ABOVE_THRESHOLD, threshold=25.0, direction="above", topic="VIXCLS")
        events = check_conditions([cond], {"VIXCLS": 30.0})
        assert len(events) == 1

    def test_condition_topic_matches_but_threshold_not_met(self):
        cond = _cond(VIX_ABOVE_THRESHOLD, threshold=25.0, direction="above", topic="VIXCLS")
        events = check_conditions([cond], {"VIXCLS": 20.0})
        assert len(events) == 0

    def test_multiple_conditions_one_triggers(self):
        conditions = [
            _cond(YIELD_CURVE_REINVERSION, threshold=0.0, direction="crosses", topic="T10Y2Y"),
            _cond(VIX_ABOVE_THRESHOLD, threshold=30.0, direction="above", topic="VIXCLS"),
        ]
        readings = {"T10Y2Y": 0.5, "VIXCLS": 35.0}
        events = check_conditions(conditions, readings)
        assert len(events) == 1
        assert events[0].type == VIX_ABOVE_THRESHOLD

    def test_multiple_conditions_all_trigger(self):
        conditions = [
            _cond(YIELD_CURVE_REINVERSION, threshold=0.0, direction="crosses", topic="T10Y2Y"),
            _cond(VIX_ABOVE_THRESHOLD, threshold=30.0, direction="above", topic="VIXCLS"),
        ]
        readings = {"T10Y2Y": -0.10, "VIXCLS": 35.0}
        events = check_conditions(conditions, readings)
        assert len(events) == 2

    def test_condition_with_no_matching_reading_is_skipped(self):
        cond = _cond(MARGIN_COMPRESSION, threshold=0.0, direction="below", topic="MARGIN_METRIC")
        # Key is absent from readings
        events = check_conditions([cond], {"VIXCLS": 30.0})
        assert events == []

    def test_returned_events_have_correct_type(self):
        cond = _cond(CREDIT_SPREAD_WIDENING, threshold=5.0, direction="above", topic="BAMLH0A0HYM2")
        events = check_conditions([cond], {"BAMLH0A0HYM2": 6.5})
        assert len(events) == 1
        assert events[0].type == CREDIT_SPREAD_WIDENING

    def test_returned_events_have_correct_ticker(self):
        cond = _cond(
            MARGIN_COMPRESSION, threshold=0.1, direction="below",
            topic="MARGIN", ticker="AAPL",
        )
        events = check_conditions([cond], {"MARGIN": 0.05})
        assert len(events) == 1
        assert events[0].ticker == "AAPL"

    def test_returned_events_have_correct_topic(self):
        cond = _cond(VOLATILITY_SPIKE, threshold=20.0, direction="above", topic="VIXCLS")
        events = check_conditions([cond], {"VIXCLS": 25.0})
        assert len(events) == 1
        assert events[0].topic == "VIXCLS"

    def test_returned_events_carry_correct_current_value(self):
        cond = _cond(VIX_ABOVE_THRESHOLD, threshold=30.0, direction="above", topic="VIXCLS")
        events = check_conditions([cond], {"VIXCLS": 42.7})
        assert events[0].current_value == pytest.approx(42.7)

    def test_returned_events_carry_correct_threshold(self):
        cond = _cond(VIX_ABOVE_THRESHOLD, threshold=30.0, direction="above", topic="VIXCLS")
        events = check_conditions([cond], {"VIXCLS": 42.7})
        assert events[0].threshold == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# TestAlertEventFields
# ---------------------------------------------------------------------------


class TestAlertEventFields:
    """Verify that triggered AlertEvent instances are well-formed."""

    def _trigger(self) -> AlertEvent:
        cond = _cond(VIX_ABOVE_THRESHOLD, threshold=30.0, direction="above", topic="VIXCLS")
        events = check_conditions([cond], {"VIXCLS": 35.0})
        assert len(events) == 1
        return events[0]

    def test_triggered_at_is_nonempty_string(self):
        event = self._trigger()
        assert isinstance(event.triggered_at, str)
        assert len(event.triggered_at) > 0

    def test_triggered_at_looks_like_iso_timestamp(self):
        """triggered_at should contain a 'T' separator (ISO-8601 format)."""
        event = self._trigger()
        assert "T" in event.triggered_at

    def test_message_is_nonempty_string(self):
        event = self._trigger()
        assert isinstance(event.message, str)
        assert len(event.message) > 0

    def test_current_value_matches_reading(self):
        event = self._trigger()
        assert event.current_value == pytest.approx(35.0)

    def test_threshold_matches_condition(self):
        event = self._trigger()
        assert event.threshold == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# TestBuiltInConditionTypes
# ---------------------------------------------------------------------------


class TestBuiltInConditionTypes:
    """Verify the exported constant names and types."""

    def test_yield_curve_reinversion_value(self):
        assert YIELD_CURVE_REINVERSION == "yield_curve_reinversion"

    def test_volatility_spike_value(self):
        assert VOLATILITY_SPIKE == "volatility_spike"

    def test_vix_above_threshold_value(self):
        assert VIX_ABOVE_THRESHOLD == "vix_above_threshold"

    def test_margin_compression_is_str(self):
        assert isinstance(MARGIN_COMPRESSION, str)

    def test_yield_curve_reinversion_is_str(self):
        assert isinstance(YIELD_CURVE_REINVERSION, str)

    def test_volatility_spike_is_str(self):
        assert isinstance(VOLATILITY_SPIKE, str)

    def test_vix_above_threshold_is_str(self):
        assert isinstance(VIX_ABOVE_THRESHOLD, str)

    def test_credit_spread_widening_is_str(self):
        assert isinstance(CREDIT_SPREAD_WIDENING, str)


# ---------------------------------------------------------------------------
# TestRealScenarios
# ---------------------------------------------------------------------------


class TestRealScenarios:
    """End-to-end realistic scenarios combining monitoring constants and logic."""

    def test_yield_curve_reinversion_fires_when_negative(self):
        cond = _cond(YIELD_CURVE_REINVERSION, threshold=0.0, direction="crosses", topic="T10Y2Y")
        events = check_conditions([cond], {"T10Y2Y": -0.15})
        assert len(events) == 1
        assert events[0].type == YIELD_CURVE_REINVERSION

    def test_yield_curve_reinversion_does_not_fire_when_positive(self):
        cond = _cond(YIELD_CURVE_REINVERSION, threshold=0.0, direction="crosses", topic="T10Y2Y")
        events = check_conditions([cond], {"T10Y2Y": 0.49})
        assert len(events) == 0

    def test_vix_spike_fires_above_30(self):
        cond = _cond(VIX_ABOVE_THRESHOLD, threshold=30.0, direction="above", topic="VIXCLS")
        events = check_conditions([cond], {"VIXCLS": 32.5})
        assert len(events) == 1

    def test_vix_no_spike_below_30(self):
        cond = _cond(VIX_ABOVE_THRESHOLD, threshold=30.0, direction="above", topic="VIXCLS")
        events = check_conditions([cond], {"VIXCLS": 18.0})
        assert len(events) == 0

    def test_vix_no_spike_exactly_at_threshold(self):
        """VIX exactly equal to threshold should NOT trigger (direction='above' is strict)."""
        cond = _cond(VIX_ABOVE_THRESHOLD, threshold=30.0, direction="above", topic="VIXCLS")
        events = check_conditions([cond], {"VIXCLS": 30.0})
        assert len(events) == 0

    def test_multiple_conditions_mixed(self):
        conditions = [
            _cond(YIELD_CURVE_REINVERSION, 0.0, "crosses", topic="T10Y2Y"),
            _cond(VIX_ABOVE_THRESHOLD, 30.0, "above", topic="VIXCLS"),
            _cond(CREDIT_SPREAD_WIDENING, 5.0, "above", topic="BAMLH0A0HYM2"),
        ]
        readings = {"T10Y2Y": -0.10, "VIXCLS": 18.0, "BAMLH0A0HYM2": 6.2}
        events = check_conditions(conditions, readings)
        assert len(events) == 2  # yield reinversion + credit spread
        types = {e.type for e in events}
        assert YIELD_CURVE_REINVERSION in types
        assert CREDIT_SPREAD_WIDENING in types
        assert VIX_ABOVE_THRESHOLD not in types

    def test_all_three_conditions_fire(self):
        conditions = [
            _cond(YIELD_CURVE_REINVERSION, 0.0, "crosses", topic="T10Y2Y"),
            _cond(VIX_ABOVE_THRESHOLD, 30.0, "above", topic="VIXCLS"),
            _cond(CREDIT_SPREAD_WIDENING, 5.0, "above", topic="BAMLH0A0HYM2"),
        ]
        readings = {"T10Y2Y": -0.20, "VIXCLS": 38.0, "BAMLH0A0HYM2": 7.1}
        events = check_conditions(conditions, readings)
        assert len(events) == 3

    def test_condition_resolved_by_type_key_when_topic_absent(self):
        """If topic is None, _resolve_reading falls back to condition.type as key."""
        cond = _cond(YIELD_CURVE_REINVERSION, threshold=0.0, direction="crosses", topic=None)
        events = check_conditions([cond], {YIELD_CURVE_REINVERSION: -0.05})
        assert len(events) == 1

    def test_condition_resolved_by_condition_id_as_last_resort(self):
        """_resolve_reading checks condition_id last."""
        cond = AlertCondition(
            condition_id="my_custom_metric",
            type="custom_type",
            threshold=100.0,
            direction="above",
            topic=None,
        )
        events = check_conditions([cond], {"my_custom_metric": 150.0})
        assert len(events) == 1
        assert events[0].type == "custom_type"
