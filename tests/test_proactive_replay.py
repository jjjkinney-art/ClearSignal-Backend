from __future__ import annotations

import json

import pytest

from scripts import benchmark_proactive_replay
from validation.intelligence_benchmark import BenchmarkContractError
from validation.proactive_replay import ReplayCase, score_payload, score_proactive_replays


def _thesis(**overrides):
    value = {
        "thesis_id": "thesis-1", "owner_ref": "synthetic:owner-a", "ticker": "NVDA",
        "recorded_at": "2025-01-01T00:00:00Z",
        "assumptions": [{"assumption_id": "gross-margin", "material": True}],
    }
    value.update(overrides)
    return value


def _event(**overrides):
    value = {
        "event_id": "event-1", "ticker": "NVDA", "source_id": "filing-1",
        "published_at": "2025-02-01T12:00:00Z", "materiality": "material",
    }
    value.update(overrides)
    return value


def _expected(**overrides):
    value = {
        "relevant": True, "impact": "weakened", "assumption_ids": ["gross-margin"],
        "confidence_delta_min": -0.20, "confidence_delta_max": -0.05,
        "maximum_delay_hours": 24,
    }
    value.update(overrides)
    return value


def _alert(**overrides):
    value = {
        "alert_id": "alert-1", "owner_ref": "synthetic:owner-a", "ticker": "NVDA",
        "detected_at": "2025-02-01T13:00:00Z", "source_id": "filing-1",
        "relevant": True, "impact": "weakened", "assumption_ids": ["gross-margin"],
        "confidence_delta": -0.10,
    }
    value.update(overrides)
    return value


def _case(alerts=None, expected=None, thesis=None, event=None, **overrides):
    value = {
        "replay_id": "replay-1", "thesis": thesis or _thesis(), "event": event or _event(),
        "expected": expected or _expected(), "replay_end_at": "2025-02-03T12:00:00Z",
        "alerts": [_alert()] if alerts is None else alerts,
    }
    value.update(overrides)
    return ReplayCase.from_dict(value)


def test_correct_replay_scores_all_core_metrics():
    result = score_proactive_replays([_case()])
    assert result.detection_recall == 1.0
    assert result.alert_precision == 1.0
    assert result.thesis_impact_accuracy == 1.0
    assert result.timely_alert_rate == 1.0
    assert result.safe_to_expand is True


def test_missed_material_event_is_critical():
    result = score_proactive_replays([_case(alerts=[])])
    assert result.detection_recall == 0.0
    assert result.safe_to_expand is False
    assert "material_event_missed" in result.cases[0].finding_codes


def test_irrelevant_event_should_not_emit_alert():
    expected = _expected(relevant=False, impact="unchanged", assumption_ids=[], confidence_delta_min=0, confidence_delta_max=0)
    quiet = score_proactive_replays([_case(alerts=[], expected=expected)])
    assert quiet.noise_alert_count == 0
    assert quiet.safe_to_expand is True
    noisy = score_proactive_replays([_case(expected=expected, alerts=[_alert(relevant=False, impact="unchanged", assumption_ids=[], confidence_delta=0)])])
    assert noisy.noise_alert_count == 1
    assert "noise_alert" in noisy.cases[0].finding_codes
    assert noisy.safe_to_expand is False


@pytest.mark.parametrize(
    ("alert_overrides", "code"),
    [
        ({"impact": "strengthened"}, "thesis_impact_error"),
        ({"source_id": "wrong"}, "source_binding_error"),
        ({"relevant": False}, "relevance_misclassified"),
        ({"confidence_delta": 0.20}, "confidence_change_error"),
        ({"assumption_ids": []}, "assumption_link_missed"),
        ({"assumption_ids": ["gross-margin", "unknown"]}, "unrelated_assumption_linked"),
        ({"ticker": "AMD"}, "ticker_scope_violation"),
    ],
)
def test_material_alert_errors_fail_closed(alert_overrides, code):
    result = score_proactive_replays([_case(alerts=[_alert(**alert_overrides)])])
    assert result.safe_to_expand is False
    assert code in result.cases[0].finding_codes


def test_unknown_assumption_is_separately_reported():
    result = score_proactive_replays([_case(alerts=[_alert(assumption_ids=["gross-margin", "unknown"])])])
    assert "unknown_assumption_linked" in result.cases[0].finding_codes


def test_prepublication_alert_is_lookahead_leakage():
    result = score_proactive_replays([_case(alerts=[_alert(detected_at="2025-02-01T11:59:00Z")])])
    assert result.lookahead_leakage_count == 1
    assert result.safe_to_expand is False


def test_wrong_owner_is_privacy_exposure():
    result = score_proactive_replays([_case(alerts=[_alert(owner_ref="synthetic:owner-b")])])
    assert result.privacy_exposure_count == 1
    assert result.safe_to_expand is False


def test_late_alert_blocks_expansion_without_becoming_privacy_exposure():
    result = score_proactive_replays([_case(alerts=[_alert(detected_at="2025-02-03T00:00:01Z")])])
    assert result.timely_alert_rate == 0.0
    assert "late_alert" in result.cases[0].finding_codes
    assert result.privacy_exposure_count == 0
    assert result.safe_to_expand is False


def test_duplicate_alerts_are_counted_as_noise():
    result = score_proactive_replays([_case(alerts=[_alert(), _alert(alert_id="alert-2")])])
    assert result.noise_alert_count == 1
    assert result.cases[0].duplicate_alerts == 1
    assert result.safe_to_expand is False


def test_thesis_must_predate_event_and_ticker_must_match():
    with pytest.raises(BenchmarkContractError, match="predate"):
        _case(thesis=_thesis(recorded_at="2025-02-02T00:00:00Z"))
    with pytest.raises(BenchmarkContractError, match="ticker must match"):
        _case(thesis=_thesis(ticker="AMD"))


def test_replay_end_must_follow_publication():
    with pytest.raises(BenchmarkContractError, match="replay end"):
        _case(replay_end_at="2025-01-31T00:00:00Z")


def test_only_synthetic_owner_is_accepted():
    with pytest.raises(BenchmarkContractError, match="synthetic"):
        _case(thesis=_thesis(owner_ref="real-user-id"))


def test_expected_assumptions_must_exist():
    with pytest.raises(BenchmarkContractError, match="unknown thesis assumptions"):
        _case(expected=_expected(assumption_ids=["unknown"]))


def test_expected_assumptions_must_be_material():
    thesis = _thesis(assumptions=[{"assumption_id": "gross-margin", "material": False}])
    with pytest.raises(BenchmarkContractError, match="only material"):
        _case(thesis=thesis)


@pytest.mark.parametrize(
    "expected",
    [
        _expected(impact="strengthened", confidence_delta_min=-0.1, confidence_delta_max=0.1),
        _expected(impact="weakened", confidence_delta_min=-0.1, confidence_delta_max=0.1),
        _expected(impact="unchanged", confidence_delta_min=0.1, confidence_delta_max=0.2),
    ],
)
def test_expected_impact_and_confidence_direction_must_agree(expected):
    with pytest.raises(BenchmarkContractError, match="confidence change"):
        _case(expected=expected)


def test_irrelevant_expected_contract_cannot_claim_impact():
    with pytest.raises(BenchmarkContractError, match="irrelevant events"):
        _case(expected=_expected(relevant=False))


def test_duplicate_alert_and_replay_ids_fail_closed():
    with pytest.raises(BenchmarkContractError, match="alert ids"):
        _case(alerts=[_alert(), _alert()])
    case = _case()
    with pytest.raises(BenchmarkContractError, match="replay ids"):
        score_proactive_replays([case, case])


def test_empty_suite_is_not_safe():
    result = score_payload({"cases": []})
    assert result.fully_evaluated is False
    assert result.safe_to_expand is False


def _payload(alerts=None):
    return {"cases": [{
        "replay_id": "replay-1", "thesis": _thesis(), "event": _event(),
        "expected": _expected(), "replay_end_at": "2025-02-03T12:00:00Z",
        "alerts": [_alert()] if alerts is None else alerts,
    }]}


def test_payload_and_cli_pass_safe_replay(tmp_path, capsys):
    payload = _payload()
    assert score_payload(payload).safe_to_expand is True
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(payload))
    assert benchmark_proactive_replay.main([str(path), "--require-safe"]) == 0
    assert '"safe_to_expand": true' in capsys.readouterr().out


def test_cli_rejects_lookahead_alert(tmp_path):
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(_payload([_alert(detected_at="2025-01-31T00:00:00Z")])))
    assert benchmark_proactive_replay.main([str(path), "--require-safe"]) == 2
