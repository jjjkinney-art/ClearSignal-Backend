"""Protected subgroup scorecards for Intelligence Benchmark observations.

Overall averages are reported but can never override an under-sampled, failing,
or materially regressing protected group.  Critical case failures also remain
launch blockers regardless of any aggregate metric.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from math import isfinite
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .intelligence_benchmark import BenchmarkContractError


class GroupStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT = "insufficient"


PROTECTED_DIMENSIONS = frozenset({
    "market_cap_tier", "coverage_tier", "domicile", "sector",
    "profitability", "evidence_mode", "reporting_complexity",
    "personalization_mode",
})


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise BenchmarkContractError(f"{field} is required")
    return result


def _finite(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkContractError(f"{field} must be numeric") from exc
    if not isfinite(result):
        raise BenchmarkContractError(f"{field} must be finite")
    return result


@dataclass(frozen=True)
class MetricRule:
    metric: str
    higher_is_better: bool
    threshold: float
    maximum_overall_gap: float

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "MetricRule":
        higher = value.get("higher_is_better")
        if not isinstance(higher, bool):
            raise BenchmarkContractError("higher_is_better must be boolean")
        gap = _finite(value.get("maximum_overall_gap", 0), "maximum_overall_gap")
        if gap < 0:
            raise BenchmarkContractError("maximum_overall_gap cannot be negative")
        return MetricRule(
            metric=_text(value.get("metric"), "metric"),
            higher_is_better=higher,
            threshold=_finite(value.get("threshold"), "threshold"),
            maximum_overall_gap=gap,
        )


@dataclass(frozen=True)
class ProtectedGroup:
    group_id: str
    dimension: str
    value: str
    minimum_observations: int
    minimum_issuers: int

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ProtectedGroup":
        dimension = _text(value.get("dimension"), "dimension")
        if dimension not in PROTECTED_DIMENSIONS:
            raise BenchmarkContractError(f"unsupported protected dimension: {dimension}")
        observations = value.get("minimum_observations")
        issuers = value.get("minimum_issuers")
        if (
            isinstance(observations, bool) or not isinstance(observations, int)
            or observations < 1
        ):
            raise BenchmarkContractError("minimum_observations must be a positive integer")
        if isinstance(issuers, bool) or not isinstance(issuers, int) or issuers < 1:
            raise BenchmarkContractError("minimum_issuers must be a positive integer")
        return ProtectedGroup(
            group_id=_text(value.get("group_id"), "group_id"),
            dimension=dimension, value=_text(value.get("value"), "value"),
            minimum_observations=observations, minimum_issuers=issuers,
        )


@dataclass(frozen=True)
class BenchmarkObservation:
    observation_id: str
    issuer_id: str
    dimensions: Tuple[Tuple[str, str], ...]
    metrics: Tuple[Tuple[str, float], ...]
    critical_failure_codes: Tuple[str, ...]

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "BenchmarkObservation":
        dimensions = value.get("dimensions")
        metrics = value.get("metrics")
        if not isinstance(dimensions, Mapping):
            raise BenchmarkContractError("dimensions must be an object")
        if not isinstance(metrics, Mapping) or not metrics:
            raise BenchmarkContractError("metrics must be a non-empty object")
        unknown = set(dimensions) - PROTECTED_DIMENSIONS
        if unknown:
            raise BenchmarkContractError(f"unsupported observation dimensions: {sorted(unknown)}")
        normalized_dimensions = tuple(sorted(
            (_text(key, "dimension"), _text(item, f"dimensions.{key}"))
            for key, item in dimensions.items()
        ))
        normalized_metrics = tuple(sorted(
            (_text(key, "metric"), _finite(item, f"metrics.{key}"))
            for key, item in metrics.items()
        ))
        failures = tuple(sorted(
            _text(item, "critical_failure_codes")
            for item in value.get("critical_failure_codes", ())
        ))
        if len(set(failures)) != len(failures):
            raise BenchmarkContractError("critical_failure_codes must be unique")
        return BenchmarkObservation(
            observation_id=_text(value.get("observation_id"), "observation_id"),
            issuer_id=_text(value.get("issuer_id"), "issuer_id"),
            dimensions=normalized_dimensions, metrics=normalized_metrics,
            critical_failure_codes=failures,
        )

    @property
    def dimension_map(self) -> Dict[str, str]:
        return dict(self.dimensions)

    @property
    def metric_map(self) -> Dict[str, float]:
        return dict(self.metrics)


@dataclass(frozen=True)
class MetricResult:
    metric: str
    value: Optional[float]
    overall_value: Optional[float]
    threshold_passed: bool
    regression_passed: bool
    measured_observations: int


@dataclass(frozen=True)
class GroupResult:
    group_id: str
    dimension: str
    value: str
    observation_count: int
    issuer_count: int
    sample_sufficient: bool
    status: GroupStatus
    metric_results: Tuple[MetricResult, ...]
    critical_failure_count: int
    failure_reasons: Tuple[str, ...]


@dataclass(frozen=True)
class SubgroupScorecard:
    overall_metrics: Tuple[Tuple[str, float], ...]
    groups: Tuple[GroupResult, ...]
    observation_count: int
    issuer_count: int
    insufficient_group_count: int
    failing_group_count: int
    subgroup_regression_count: int
    critical_failure_count: int
    launch_blocker_count: int
    fully_evaluated: bool
    passed: bool

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["overall_metrics"] = dict(self.overall_metrics)
        return result


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def build_subgroup_scorecard(
    *, observations: Sequence[BenchmarkObservation],
    protected_groups: Sequence[ProtectedGroup], rules: Sequence[MetricRule],
) -> SubgroupScorecard:
    if len({item.observation_id for item in observations}) != len(observations):
        raise BenchmarkContractError("observation ids must be unique")
    if len({item.group_id for item in protected_groups}) != len(protected_groups):
        raise BenchmarkContractError("protected group ids must be unique")
    if len({item.metric for item in rules}) != len(rules):
        raise BenchmarkContractError("metric rules must be unique")
    if not protected_groups:
        raise BenchmarkContractError("at least one protected group is required")
    if not rules:
        raise BenchmarkContractError("at least one metric rule is required")

    overall = {}
    for rule in rules:
        overall[rule.metric] = _mean([
            item.metric_map[rule.metric]
            for item in observations if rule.metric in item.metric_map
        ])

    group_results = []
    regressions = 0
    for group in sorted(protected_groups, key=lambda item: item.group_id):
        members = [
            item for item in observations
            if item.dimension_map.get(group.dimension) == group.value
        ]
        issuer_count = len({item.issuer_id for item in members})
        sufficient = (
            len(members) >= group.minimum_observations
            and issuer_count >= group.minimum_issuers
        )
        reasons = []
        metric_results = []
        group_regressed = False
        for rule in rules:
            values = [item.metric_map[rule.metric] for item in members if rule.metric in item.metric_map]
            value = _mean(values)
            overall_value = overall[rule.metric]
            measured_all = len(values) == len(members) and bool(members)
            if value is None or overall_value is None or not measured_all:
                threshold_passed = regression_passed = False
                reasons.append(f"{rule.metric}: missing measurement")
            else:
                threshold_passed = (
                    value >= rule.threshold if rule.higher_is_better
                    else value <= rule.threshold
                )
                gap = (
                    overall_value - value if rule.higher_is_better
                    else value - overall_value
                )
                regression_passed = gap <= rule.maximum_overall_gap + 1e-12
                if not threshold_passed:
                    reasons.append(f"{rule.metric}: threshold failed")
                if not regression_passed:
                    reasons.append(f"{rule.metric}: subgroup regression")
                    group_regressed = True
            metric_results.append(MetricResult(
                rule.metric, value, overall_value, threshold_passed,
                regression_passed, len(values),
            ))
        critical_count = sum(len(item.critical_failure_codes) for item in members)
        if critical_count:
            reasons.append("critical case failure present")
        if not sufficient:
            reasons.insert(0, "minimum sample not met")
            status = GroupStatus.INSUFFICIENT
        elif reasons:
            status = GroupStatus.FAIL
        else:
            status = GroupStatus.PASS
        regressions += group_regressed
        group_results.append(GroupResult(
            group.group_id, group.dimension, group.value, len(members), issuer_count,
            sufficient, status, tuple(metric_results), critical_count,
            tuple(reasons),
        ))

    insufficient = sum(item.status == GroupStatus.INSUFFICIENT for item in group_results)
    failing = sum(item.status == GroupStatus.FAIL for item in group_results)
    critical = sum(len(item.critical_failure_codes) for item in observations)
    blockers = insufficient + failing + critical
    fully_evaluated = bool(observations) and insufficient == 0
    return SubgroupScorecard(
        overall_metrics=tuple(sorted(
            (key, value) for key, value in overall.items() if value is not None
        )),
        groups=tuple(group_results), observation_count=len(observations),
        issuer_count=len({item.issuer_id for item in observations}),
        insufficient_group_count=insufficient, failing_group_count=failing,
        subgroup_regression_count=regressions, critical_failure_count=critical,
        launch_blocker_count=blockers, fully_evaluated=fully_evaluated,
        passed=fully_evaluated and blockers == 0,
    )


def score_payload(payload: Mapping[str, Any]) -> SubgroupScorecard:
    return build_subgroup_scorecard(
        observations=[BenchmarkObservation.from_dict(item) for item in payload.get("observations", ())],
        protected_groups=[ProtectedGroup.from_dict(item) for item in payload.get("protected_groups", ())],
        rules=[MetricRule.from_dict(item) for item in payload.get("rules", ())],
    )
