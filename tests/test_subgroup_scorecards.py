from __future__ import annotations

import json

import pytest

from scripts import benchmark_subgroup_scorecard
from validation.intelligence_benchmark import BenchmarkContractError
from validation.subgroup_scorecards import (
    BenchmarkObservation, MetricRule, ProtectedGroup,
    build_subgroup_scorecard, score_payload,
)


def _observation(identifier, issuer, tier, accuracy=0.99, quality=0.90, failures=None, **dimensions):
    dims = {
        "market_cap_tier": tier, "coverage_tier": "thin" if tier == "small_micro" else "heavy",
        "domicile": "us", "sector": "technology", "profitability": "profitable",
        "evidence_mode": "sec_structured", "reporting_complexity": "simple",
        "personalization_mode": "off",
    }
    dims.update(dimensions)
    return BenchmarkObservation.from_dict({
        "observation_id": identifier, "issuer_id": issuer, "dimensions": dims,
        "metrics": {"material_numerical_accuracy": accuracy, "analytical_quality": quality},
        "critical_failure_codes": failures or [],
    })


def _groups(minimum_observations=2, minimum_issuers=2):
    return [
        ProtectedGroup.from_dict({"group_id": "mega", "dimension": "market_cap_tier", "value": "mega_large", "minimum_observations": minimum_observations, "minimum_issuers": minimum_issuers}),
        ProtectedGroup.from_dict({"group_id": "small", "dimension": "market_cap_tier", "value": "small_micro", "minimum_observations": minimum_observations, "minimum_issuers": minimum_issuers}),
    ]


def _rules(maximum_gap=0.05):
    return [
        MetricRule.from_dict({"metric": "material_numerical_accuracy", "higher_is_better": True, "threshold": 0.98, "maximum_overall_gap": maximum_gap}),
        MetricRule.from_dict({"metric": "analytical_quality", "higher_is_better": True, "threshold": 0.75, "maximum_overall_gap": maximum_gap}),
    ]


def _passing_observations():
    return [
        _observation("mega-1", "AAPL", "mega_large"), _observation("mega-2", "MSFT", "mega_large"),
        _observation("small-1", "SMAL", "small_micro"), _observation("small-2", "TINY", "small_micro"),
    ]


def test_balanced_passing_groups_pass():
    result = build_subgroup_scorecard(observations=_passing_observations(), protected_groups=_groups(), rules=_rules())
    assert result.passed is True
    assert result.fully_evaluated is True
    assert result.launch_blocker_count == 0


def test_aggregate_pass_cannot_hide_small_cap_threshold_failure():
    observations = [
        _observation("mega-1", "AAPL", "mega_large", accuracy=1.0),
        _observation("mega-2", "MSFT", "mega_large", accuracy=1.0),
        _observation("mega-3", "NVDA", "mega_large", accuracy=1.0),
        _observation("mega-4", "AMZN", "mega_large", accuracy=1.0),
        _observation("small-1", "SMAL", "small_micro", accuracy=0.90),
        _observation("small-2", "TINY", "small_micro", accuracy=0.90),
    ]
    result = build_subgroup_scorecard(observations=observations, protected_groups=_groups(), rules=_rules())
    assert dict(result.overall_metrics)["material_numerical_accuracy"] > 0.96
    assert result.passed is False
    assert next(item for item in result.groups if item.group_id == "small").status.value == "fail"


def test_group_regression_blocks_even_when_absolute_threshold_passes():
    observations = [
        _observation("mega-1", "AAPL", "mega_large", quality=0.95),
        _observation("mega-2", "MSFT", "mega_large", quality=0.95),
        _observation("small-1", "SMAL", "small_micro", quality=0.80),
        _observation("small-2", "TINY", "small_micro", quality=0.80),
    ]
    result = build_subgroup_scorecard(observations=observations, protected_groups=_groups(), rules=_rules(maximum_gap=0.05))
    assert result.subgroup_regression_count == 1
    assert result.passed is False


def test_minimum_observations_and_distinct_issuers_are_both_required():
    repeated = [
        _observation("small-1", "SMAL", "small_micro"),
        _observation("small-2", "SMAL", "small_micro"),
    ]
    result = build_subgroup_scorecard(observations=repeated, protected_groups=[_groups()[1]], rules=_rules())
    assert result.insufficient_group_count == 1
    assert result.fully_evaluated is False
    assert result.passed is False


def test_empty_protected_group_is_insufficient_not_zero_scored():
    result = build_subgroup_scorecard(observations=[_observation("mega-1", "AAPL", "mega_large")], protected_groups=[_groups()[1]], rules=_rules())
    group = result.groups[0]
    assert group.status.value == "insufficient"
    assert all(item.value is None for item in group.metric_results)


def test_missing_metric_is_explicit_failure():
    observation = BenchmarkObservation.from_dict({
        "observation_id": "x", "issuer_id": "SMAL",
        "dimensions": {"market_cap_tier": "small_micro"},
        "metrics": {"material_numerical_accuracy": 1.0},
        "critical_failure_codes": [],
    })
    result = build_subgroup_scorecard(observations=[observation], protected_groups=[_groups(1, 1)[1]], rules=_rules())
    assert result.passed is False
    assert any("missing measurement" in reason for reason in result.groups[0].failure_reasons)


def test_critical_case_failure_blocks_any_average():
    observations = _passing_observations()
    observations[2] = _observation("small-1", "SMAL", "small_micro", failures=["fabricated_material_source"])
    result = build_subgroup_scorecard(observations=observations, protected_groups=_groups(), rules=_rules())
    assert result.critical_failure_count == 1
    assert result.passed is False


def test_lower_is_better_rule_uses_maximum_threshold_and_gap():
    observations = [
        BenchmarkObservation.from_dict({"observation_id": "a", "issuer_id": "A", "dimensions": {"market_cap_tier": "mega_large"}, "metrics": {"error_rate": 0.01}, "critical_failure_codes": []}),
        BenchmarkObservation.from_dict({"observation_id": "b", "issuer_id": "B", "dimensions": {"market_cap_tier": "small_micro"}, "metrics": {"error_rate": 0.08}, "critical_failure_codes": []}),
    ]
    groups = [ProtectedGroup.from_dict({"group_id": "small", "dimension": "market_cap_tier", "value": "small_micro", "minimum_observations": 1, "minimum_issuers": 1})]
    rules = [MetricRule.from_dict({"metric": "error_rate", "higher_is_better": False, "threshold": 0.05, "maximum_overall_gap": 0.02})]
    result = build_subgroup_scorecard(observations=observations, protected_groups=groups, rules=rules)
    assert result.groups[0].metric_results[0].threshold_passed is False
    assert result.groups[0].metric_results[0].regression_passed is False


@pytest.mark.parametrize("dimension", ["unknown", "market_cap"])
def test_unknown_protected_dimensions_fail_closed(dimension):
    with pytest.raises(BenchmarkContractError, match="unsupported protected dimension"):
        ProtectedGroup.from_dict({"group_id": "x", "dimension": dimension, "value": "y", "minimum_observations": 1, "minimum_issuers": 1})


def test_unknown_observation_dimensions_fail_closed():
    with pytest.raises(BenchmarkContractError, match="unsupported observation dimensions"):
        BenchmarkObservation.from_dict({"observation_id": "x", "issuer_id": "A", "dimensions": {"unknown": "x"}, "metrics": {"quality": 1}, "critical_failure_codes": []})


@pytest.mark.parametrize("field", ["minimum_observations", "minimum_issuers"])
def test_sample_minimums_must_be_positive_integers(field):
    value = {"group_id": "x", "dimension": "sector", "value": "technology", "minimum_observations": 1, "minimum_issuers": 1}
    value[field] = 0
    with pytest.raises(BenchmarkContractError, match=field):
        ProtectedGroup.from_dict(value)


def test_duplicate_ids_and_rules_fail_closed():
    observation = _passing_observations()[0]
    with pytest.raises(BenchmarkContractError, match="observation ids"):
        build_subgroup_scorecard(observations=[observation, observation], protected_groups=_groups(), rules=_rules())
    group = _groups()[0]
    with pytest.raises(BenchmarkContractError, match="group ids"):
        build_subgroup_scorecard(observations=_passing_observations(), protected_groups=[group, group], rules=_rules())
    rule = _rules()[0]
    with pytest.raises(BenchmarkContractError, match="metric rules"):
        build_subgroup_scorecard(observations=_passing_observations(), protected_groups=_groups(), rules=[rule, rule])


def test_empty_configuration_fails_closed():
    with pytest.raises(BenchmarkContractError, match="protected group"):
        build_subgroup_scorecard(observations=[], protected_groups=[], rules=_rules())
    with pytest.raises(BenchmarkContractError, match="metric rule"):
        build_subgroup_scorecard(observations=[], protected_groups=_groups(), rules=[])


def _payload(small_accuracy=0.99):
    observations = _passing_observations()
    observations[2] = _observation("small-1", "SMAL", "small_micro", accuracy=small_accuracy)
    observations[3] = _observation("small-2", "TINY", "small_micro", accuracy=small_accuracy)
    return {
        "observations": [
            {"observation_id": item.observation_id, "issuer_id": item.issuer_id, "dimensions": dict(item.dimensions), "metrics": dict(item.metrics), "critical_failure_codes": list(item.critical_failure_codes)}
            for item in observations
        ],
        "protected_groups": [as_group(item) for item in _groups()],
        "rules": [as_rule(item) for item in _rules()],
    }


def as_group(item):
    return {"group_id": item.group_id, "dimension": item.dimension, "value": item.value, "minimum_observations": item.minimum_observations, "minimum_issuers": item.minimum_issuers}


def as_rule(item):
    return {"metric": item.metric, "higher_is_better": item.higher_is_better, "threshold": item.threshold, "maximum_overall_gap": item.maximum_overall_gap}


def test_payload_and_cli_pass_complete_scorecard(tmp_path, capsys):
    payload = _payload()
    assert score_payload(payload).passed is True
    path = tmp_path / "subgroups.json"
    path.write_text(json.dumps(payload))
    assert benchmark_subgroup_scorecard.main([str(path), "--require-pass"]) == 0
    assert '"passed": true' in capsys.readouterr().out


def test_cli_rejects_failing_subgroup(tmp_path):
    path = tmp_path / "subgroups.json"
    path.write_text(json.dumps(_payload(small_accuracy=0.90)))
    assert benchmark_subgroup_scorecard.main([str(path), "--require-pass"]) == 2
