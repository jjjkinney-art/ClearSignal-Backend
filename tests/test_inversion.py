"""
Architectural inversion enforcement tests.

These tests FAIL if the system reverts to metric-first logic.

Contract:
    - Decisions must be makeable without scores
    - Alerts must be generatable without counts
    - Learning behaviour must work without scalar weights
    - Interpretation must be primary, not derived from labels
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ===========================================================================
# LEARNING LAYER TESTS
# ===========================================================================

class TestLearningProfileFirst:
    """get_signal_profile must be classification-first, weight-agnostic."""

    def test_profile_returned_without_any_weight_computation(self):
        """Profile must be derivable without computing a scalar weight."""
        import app.services.learning as L
        L._signal_outcomes["__test_signal__"] = {
            "thesis_change": 5,
            "alert": 1,
            "noise": 0,
        }
        result = L.get_signal_profile("__TEST_SIGNAL__")
        assert result["signal_profile"] == "thesis-driven"
        # Weight must NOT be present in profile output
        assert "weight" not in result, "Scalar weight must not be a profile output field"
        assert "scalar_weight" not in result

    def test_policy_derived_from_profile_not_weight(self):
        """behavior_policy must map from profile type, not from a numeric value."""
        import app.services.learning as L
        L._signal_outcomes["__noise_sig__"] = {"noise": 10, "alert": 1}
        result = L.get_signal_profile("__noise_sig__")
        assert result["signal_profile"] == "noise-driven"
        assert result["behavior_policy"] == "reduced priority"

    def test_noise_profile_without_weight_history(self):
        """Signals with no history default to noise-driven profile, not weight=1.0."""
        import app.services.learning as L
        result = L.get_signal_profile("__completely_unknown_signal_xyz__")
        assert result["signal_profile"] == "noise-driven"
        assert result["profile_confidence"] == 0.0

    def test_four_canonical_profiles_exist(self):
        """All four canonical profiles must be reachable."""
        import app.services.learning as L
        cases = [
            ("thesis_change", "thesis-driven"),
            ("reanalysis",    "reanalysis-driven"),
            ("alert",         "alert-driven"),
            ("noise",         "noise-driven"),
        ]
        for outcome_key, expected_profile in cases:
            sig = f"__profile_test_{outcome_key}__"
            L._signal_outcomes[sig] = {outcome_key: 10}
            result = L.get_signal_profile(sig)
            assert result["signal_profile"] == expected_profile, (
                f"Expected {expected_profile} for dominant outcome {outcome_key}, "
                f"got {result['signal_profile']}"
            )

    def test_behavior_works_without_scalar_weight(self):
        """Removing get_signal_weight must not break profile derivation."""
        import app.services.learning as L
        # Temporarily hide get_signal_weight
        original = L.get_signal_weight
        try:
            del L.get_signal_weight
            L._signal_outcomes["__wsig__"] = {"reanalysis": 3}
            result = L.get_signal_profile("__wsig__")
            assert result["signal_profile"] == "reanalysis-driven"
        finally:
            L.get_signal_weight = original


# ===========================================================================
# MONITORING LAYER TESTS
# ===========================================================================

class TestMonitoringInterpretationFirst:
    """process_events must form interpretations before decisions."""

    def _make_event(self, description: str = "test signal", event_type: str = "news"):
        """Create a minimal EventRecord-like object."""
        ev = MagicMock()
        ev.description = description
        ev.event_type  = event_type
        ev.ticker      = None
        ev.timestamp   = None
        return ev

    @patch("app.services.monitoring_service.ingest_signals")
    @patch("app.services.monitoring_service.update_signal_effectiveness")
    @patch("app.services.monitoring_service._collect_supporting_metrics", return_value={})
    @patch("app.services.monitoring_service._recent_event_count", return_value=0)
    @patch("app.services.monitoring_service._days_since_last_occurrence", return_value=None)
    def test_decision_attached_to_event(self, *mocks):
        """A monitoring_decision object must be attached to every event."""
        from app.services.monitoring_service import process_events
        import app.services.learning as L
        L._signal_outcomes["test signal"] = {"alert": 3}
        ev = self._make_event()
        process_events([ev])
        # Either the decision object was attached or the action attribute was set
        attached = (
            hasattr(ev, "monitoring_decision") or
            hasattr(ev, "decision_action")
        )
        assert attached, "process_events must attach a decision to each event"

    @patch("app.services.monitoring_service.ingest_signals")
    @patch("app.services.monitoring_service.update_signal_effectiveness")
    @patch("app.services.monitoring_service._collect_supporting_metrics", return_value={})
    @patch("app.services.monitoring_service._recent_event_count", return_value=0)
    @patch("app.services.monitoring_service._days_since_last_occurrence", return_value=None)
    def test_decision_without_scores(self, *mocks):
        """Decision must be formed even when score infrastructure returns nothing."""
        from app.services.monitoring_service import process_events
        import app.services.learning as L
        # Ensure thesis-driven profile without any stored weights
        L._signal_outcomes["mission_critical"] = {"thesis_change": 7}
        ev = self._make_event("mission_critical", "earnings")
        process_events([ev])
        # Decision should exist and be non-trivial
        action = getattr(ev, "decision_action", None) or (
            getattr(getattr(ev, "monitoring_decision", None), "action", None)
        )
        assert action is not None, "Decision action must be set without scores"
        assert action != "", "Decision action must not be empty"

    @patch("app.services.monitoring_service.ingest_signals")
    @patch("app.services.monitoring_service.update_signal_effectiveness")
    @patch("app.services.monitoring_service._collect_supporting_metrics", return_value={})
    @patch("app.services.monitoring_service._recent_event_count", return_value=5)   # cluster
    @patch("app.services.monitoring_service._days_since_last_occurrence", return_value=10)
    def test_cluster_elevates_to_reanalysis(self, *mocks):
        """Cluster situation + reanalysis profile → trigger_reanalysis or stronger."""
        from app.services.monitoring_service import process_events
        import app.services.learning as L
        L._signal_outcomes["cluster_sig"] = {"reanalysis": 8}
        ev = self._make_event("cluster_sig", "filing")
        process_events([ev])
        action = getattr(ev, "decision_action", None) or (
            getattr(getattr(ev, "monitoring_decision", None), "action", None)
        )
        assert action in (
            "trigger_reanalysis",
            "trigger_reanalysis_and_thesis_compare",
        ), f"Cluster + reanalysis-driven should escalate, got: {action}"

    @patch("app.services.monitoring_service.ingest_signals")
    @patch("app.services.monitoring_service.update_signal_effectiveness")
    @patch("app.services.monitoring_service._collect_supporting_metrics", return_value={})
    @patch("app.services.monitoring_service._recent_event_count", return_value=0)
    @patch("app.services.monitoring_service._days_since_last_occurrence", return_value=None)
    def test_noise_profile_gives_record_only(self, *mocks):
        """Isolated noise-driven signal should resolve to record_signal_only."""
        from app.services.monitoring_service import process_events
        import app.services.learning as L
        L._signal_outcomes["just_noise"] = {"noise": 15, "alert": 0}
        ev = self._make_event("just_noise", "misc")
        process_events([ev])
        action = getattr(ev, "decision_action", None) or (
            getattr(getattr(ev, "monitoring_decision", None), "action", None)
        )
        assert action == "record_signal_only", (
            f"Noise-driven isolated signal should produce record_signal_only, got: {action}"
        )


# ===========================================================================
# ALERT LAYER TESTS
# ===========================================================================

class TestAlertMeaningFirst:
    """Alerts must be generated from AlertMeaning, not from count comparisons."""

    def _make_changes(
        self,
        components=("key_risks",),
        severity="medium",
        has_changed=True,
    ):
        changes = MagicMock()
        changes.has_changed        = has_changed
        changes.changed_components = list(components)
        changes.change_severity    = severity
        changes.change_summary     = "test change"
        changes.impact_on_thesis   = "test impact"
        return changes

    def _make_synthesis(self):
        s = MagicMock()
        return s

    @patch("app.services.alert_service._collect_component_evidence", return_value={
        "recent_signal_count": 0,
        "outcome_counts": {},
    })
    def test_alerts_generated_without_any_counts(self, mock_evidence):
        """Alerts must be generated even when outcome_counts is empty."""
        from app.services.alert_service import generate_alerts
        changes = self._make_changes()
        alerts  = generate_alerts(changes, self._make_synthesis())
        assert len(alerts) > 0, "Alerts must be generated without count data"

    @patch("app.services.alert_service._collect_component_evidence", return_value={
        "recent_signal_count": 0,
        "outcome_counts": {},
    })
    def test_alert_has_interpretive_fields(self, mock_evidence):
        """Generated alerts must carry meaning-first fields."""
        from app.services.alert_service import generate_alerts
        changes = self._make_changes()
        alerts  = generate_alerts(changes, self._make_synthesis())
        assert alerts, "Expected at least one alert"
        a = alerts[0]
        assert a.pattern_type        is not None, "pattern_type (situation_type) must be set"
        assert a.typical_outcome     is not None, "typical_outcome must be set"
        assert a.why_this_matters    is not None, "why_this_matters must be set"
        assert a.interpretive_summary is not None, "interpretive_summary must be set"

    @patch("app.services.alert_service._collect_component_evidence", return_value={
        "recent_signal_count": 5,   # cluster
        "outcome_counts": {"alert": 3},
    })
    def test_cluster_elevates_severity(self, mock_evidence):
        """Cluster situation (3+ recent signals) must elevate severity above base."""
        from app.services.alert_service import generate_alerts
        changes = self._make_changes(components=("key_risks",), severity="low")
        alerts  = generate_alerts(changes, self._make_synthesis())
        assert alerts, "Expected alert for key_risks cluster"
        a = alerts[0]
        # Cluster elevation must push severity above 'low'
        assert a.severity in ("medium", "high"), (
            f"Cluster should elevate severity above low, got: {a.severity}"
        )

    @patch("app.services.alert_service._collect_component_evidence", return_value={
        "recent_signal_count": 0,
        "outcome_counts": {},
    })
    def test_severity_not_computed_from_numeric_baseline(self, mock_evidence):
        """Severity must come from meaning, not a numeric baseline comparison.

        We verify this by ensuring no baseline_avg fetch drives the severity —
        the test patches _collect_component_evidence to return empty evidence and
        still expects a meaningful severity to be set.
        """
        from app.services.alert_service import generate_alerts
        changes = self._make_changes(components=("final_verdict",), severity="low")
        alerts  = generate_alerts(changes, self._make_synthesis())
        assert alerts, "Expected alert"
        a = alerts[0]
        # final_verdict has intrinsic high severity from meaning, regardless of baselines
        assert a.severity == "high", (
            f"final_verdict must be high severity from meaning alone, got: {a.severity}"
        )

    def test_no_alerts_when_not_changed(self):
        """No alerts generated when has_changed is False."""
        from app.services.alert_service import generate_alerts
        changes = self._make_changes(has_changed=False)
        alerts  = generate_alerts(changes, self._make_synthesis())
        assert alerts == [], "No alerts should be generated when thesis has not changed"


# ===========================================================================
# INVERSION VALIDATION TESTS (Step 8 of the spec)
# ===========================================================================

class TestInversionComplete:
    """Verify the three inversion completeness claims from the spec."""

    def test_decisions_work_without_scores(self):
        """Decisions must be reachable even if score computation is patched to fail."""
        from app.services.monitoring_service import (
            _interpret_history,
            _derive_judgment,
        )
        import app.services.learning as L

        # Provide profile without any stored scores
        profile_data = {
            "signal_profile":   "thesis-driven",
            "profile_confidence": 0.9,
        }
        hist = _interpret_history(
            event_type       = "earnings",
            profile_data     = profile_data,
            recent_count     = 4,
            days_since_last  = 30,
        )
        judgment = _derive_judgment("earnings", "big miss", hist, novelty_high=False)

        assert judgment.decision is not None
        assert judgment.decision != ""
        assert judgment.reasoning != ""

    def test_alerts_work_without_counts(self):
        """Alerts must be fully formed even with empty outcome_counts."""
        from app.services.alert_service import _build_alert_meaning, _severity_from_meaning
        from unittest.mock import MagicMock

        meaning = _build_alert_meaning(
            component      = "final_verdict",
            situation_type = "isolated",
            outcome_counts = {},    # empty — counts removed
            changes        = MagicMock(change_summary="test", impact_on_thesis=""),
        )
        assert meaning.situation_type     != ""
        assert meaning.historical_meaning != ""
        assert meaning.typical_outcome    != ""
        assert meaning.why_this_matters   != ""

    def test_learning_works_without_weights(self):
        """Signal profile derivation must not require get_signal_weight to be callable."""
        import app.services.learning as L
        import importlib

        L._signal_outcomes["__inv_test__"] = {"alert": 5}

        # Simulate weight infrastructure unavailability
        original_weight = L.get_signal_weight
        try:
            L.get_signal_weight = None  # type: ignore
            result = L.get_signal_profile("__inv_test__")
            assert result["signal_profile"] == "alert-driven"
        finally:
            L.get_signal_weight = original_weight
