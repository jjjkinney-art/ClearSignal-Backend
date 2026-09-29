"""Foundational contracts for the ClearSignal Intelligence Benchmark.

This module is deliberately dependency-light and side-effect free.  It defines
the records that future benchmark runners and scorecard jobs must emit without
making network calls, touching production state, or deciding market truth from
price direction alone.

The core invariants are:

* every historical case has an explicit point-in-time boundary;
* a source published after that boundary cannot enter the case;
* manifests and outputs are canonically hashed and never overwritten;
* factual integrity, analytical quality, calibration, and market usefulness
  remain separate score families; and
* critical trust failures are stop-ship regardless of an aggregate average.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


BENCHMARK_SCHEMA_VERSION = 1


class BenchmarkContractError(ValueError):
    """Raised when a benchmark record would violate a trust invariant."""


class BenchmarkProtocol(str, Enum):
    FAST_REGRESSION = "fast_regression"
    FROZEN_HISTORICAL = "frozen_historical"
    METAMORPHIC_CONSISTENCY = "metamorphic_consistency"
    MEMORY_AB = "memory_personalization_ab"
    PROACTIVE_REPLAY = "proactive_noticing_replay"
    LIVE_SHADOW = "live_shadow"
    ADVERSARIAL = "adversarial_failure"


class MarketCapTier(str, Enum):
    MEGA_LARGE = "mega_large"
    MID = "mid"
    SMALL_MICRO = "small_micro"
    UNKNOWN = "unknown"


class ClaimSeverity(str, Enum):
    CONSEQUENTIAL = "consequential"
    MATERIAL = "material"
    SUPPORTING = "supporting"
    PRESENTATIONAL = "presentational"


class ScoreFamily(str, Enum):
    FACTUAL_INTEGRITY = "factual_integrity"
    EVIDENCE_INTEGRITY = "evidence_integrity"
    ANALYTICAL_QUALITY = "analytical_quality"
    CALIBRATION = "calibration"
    CONSISTENCY = "consistency"
    MARKET_USEFULNESS = "market_usefulness"
    OPERABILITY = "operability"


def _aware_iso(value: str, *, field_name: str) -> datetime:
    """Parse a timezone-aware ISO-8601 timestamp or fail closed."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BenchmarkContractError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BenchmarkContractError(f"{field_name} must include a timezone")
    return parsed


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Stable UTF-8 JSON representation used for all benchmark hashes."""
    return json.dumps(
        _jsonable(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceSnapshot:
    """One immutable source admitted to a point-in-time case."""

    source_id: str
    source_type: str
    document_url: str
    published_at: str
    retrieved_at: str
    content_sha256: str
    authoritative: bool = False

    def validate_for(self, as_of: str) -> None:
        boundary = _aware_iso(as_of, field_name="as_of")
        published = _aware_iso(self.published_at, field_name="published_at")
        retrieved = _aware_iso(self.retrieved_at, field_name="retrieved_at")
        if not self.source_id.strip() or not self.document_url.strip():
            raise BenchmarkContractError("source_id and document_url are required")
        if published > boundary:
            raise BenchmarkContractError(
                f"source {self.source_id} was published after the as-of boundary"
            )
        if retrieved < published:
            raise BenchmarkContractError(
                f"source {self.source_id} was retrieved before publication"
            )
        if len(self.content_sha256) != 64:
            raise BenchmarkContractError(
                f"source {self.source_id} requires a SHA-256 content hash"
            )
        try:
            int(self.content_sha256, 16)
        except ValueError as exc:
            raise BenchmarkContractError(
                f"source {self.source_id} has a non-hex content hash"
            ) from exc


@dataclass(frozen=True)
class BenchmarkCase:
    """Versioned case metadata independent of any one model execution."""

    case_id: str
    ticker: str
    company: str
    question: str
    category: str
    protocol: BenchmarkProtocol
    as_of: str
    market_cap_tier: MarketCapTier
    sector: str
    difficulty_tags: Tuple[str, ...] = ()
    expected_behavior: str = "answer"  # answer | abstain | clarify
    sealed: bool = False

    def __post_init__(self) -> None:
        _aware_iso(self.as_of, field_name="as_of")
        if not all((self.case_id.strip(), self.ticker.strip(), self.question.strip())):
            raise BenchmarkContractError("case_id, ticker, and question are required")
        if self.expected_behavior not in {"answer", "abstain", "clarify"}:
            raise BenchmarkContractError(
                "expected_behavior must be answer, abstain, or clarify"
            )


@dataclass(frozen=True)
class ExecutionManifest:
    """Reproducible, immutable description of one benchmark execution."""

    run_id: str
    case: BenchmarkCase
    generated_at: str
    build_commit: str
    model_id: str
    prompt_version: str
    retrieval_version: str
    feature_flags: Tuple[Tuple[str, bool], ...]
    sources: Tuple[SourceSnapshot, ...]
    output_sha256: str
    memory_fixture_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    schema_version: int = BENCHMARK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        generated = _aware_iso(self.generated_at, field_name="generated_at")
        boundary = _aware_iso(self.case.as_of, field_name="as_of")
        if generated < boundary:
            raise BenchmarkContractError("generated_at cannot precede as_of")
        if not all((self.run_id.strip(), self.build_commit.strip(), self.model_id.strip())):
            raise BenchmarkContractError("run_id, build_commit, and model_id are required")
        if len(self.output_sha256) != 64:
            raise BenchmarkContractError("output_sha256 must be a SHA-256 hash")
        if len({source.source_id for source in self.sources}) != len(self.sources):
            raise BenchmarkContractError("source_id values must be unique within a run")
        for source in self.sources:
            source.validate_for(self.case.as_of)
        flag_names = [name for name, _ in self.feature_flags]
        if flag_names != sorted(flag_names) or len(flag_names) != len(set(flag_names)):
            raise BenchmarkContractError(
                "feature_flags must be unique and sorted by name"
            )

    @property
    def manifest_sha256(self) -> str:
        return content_hash(self)


def build_execution_manifest(
    *, case: BenchmarkCase, output: Mapping[str, Any], run_id: str,
    generated_at: str, build_commit: str, model_id: str,
    prompt_version: str, retrieval_version: str,
    feature_flags: Mapping[str, bool], sources: Sequence[SourceSnapshot],
    memory_fixture_id: Optional[str] = None,
    parent_run_id: Optional[str] = None,
) -> ExecutionManifest:
    """Create a validated manifest with canonical ordering and output hash."""
    return ExecutionManifest(
        run_id=run_id,
        case=case,
        generated_at=generated_at,
        build_commit=build_commit,
        model_id=model_id,
        prompt_version=prompt_version,
        retrieval_version=retrieval_version,
        feature_flags=tuple(sorted(feature_flags.items())),
        sources=tuple(sorted(sources, key=lambda source: source.source_id)),
        output_sha256=content_hash(output),
        memory_fixture_id=memory_fixture_id,
        parent_run_id=parent_run_id,
    )


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    family: ScoreFamily
    description: str
    unit: str
    higher_is_better: bool
    requires_mature_outcome: bool = False


METRIC_DICTIONARY: Tuple[MetricDefinition, ...] = (
    MetricDefinition("material_numerical_accuracy", ScoreFamily.FACTUAL_INTEGRITY,
                     "Share of verifiable material numerical claims with correct value, sign, unit, currency, period, and scope.", "ratio", True),
    MetricDefinition("claim_source_binding", ScoreFamily.EVIDENCE_INTEGRITY,
                     "Share of consequential claims bound to the correct supporting document and period.", "ratio", True),
    MetricDefinition("fabricated_material_sources", ScoreFamily.EVIDENCE_INTEGRITY,
                     "Count of material citations or sources that do not exist.", "count", False),
    MetricDefinition("analytical_quality", ScoreFamily.ANALYTICAL_QUALITY,
                     "Blind-rubric score for responsiveness, reasoning, materiality, counterarguments, uncertainty, and usefulness.", "ratio", True),
    MetricDefinition("brier_score", ScoreFamily.CALIBRATION,
                     "Mean squared error for predefined binary probabilistic outcomes.", "score", False, True),
    MetricDefinition("expected_calibration_error", ScoreFamily.CALIBRATION,
                     "Weighted gap between forecast confidence and observed frequency.", "score", False, True),
    MetricDefinition("paraphrase_consistency", ScoreFamily.CONSISTENCY,
                     "Share of paraphrase groups with materially consistent evidence and conclusions.", "ratio", True),
    MetricDefinition("benchmark_relative_return", ScoreFamily.MARKET_USEFULNESS,
                     "Total return relative to the predefined market or sector baseline.", "return", True, True),
    MetricDefinition("thesis_event_accuracy", ScoreFamily.MARKET_USEFULNESS,
                     "Share of predefined thesis catalysts, risks, or KPI inflections classified correctly.", "ratio", True, True),
    MetricDefinition("p95_latency_ms", ScoreFamily.OPERABILITY,
                     "95th percentile end-to-end response latency.", "milliseconds", False),
    MetricDefinition("mean_cost_usd", ScoreFamily.OPERABILITY,
                     "Mean provider cost for one completed benchmark case.", "usd", False),
)


@dataclass(frozen=True)
class LaunchGateThresholds:
    material_numerical_accuracy_min: float = 0.98
    claim_source_binding_min: float = 0.95
    fabricated_material_sources_max: int = 0
    cross_account_exposures_max: int = 0
    critical_failures_max: int = 0


@dataclass(frozen=True)
class LaunchGateInputs:
    material_numerical_accuracy: Optional[float]
    claim_source_binding: Optional[float]
    fabricated_material_sources: int
    cross_account_exposures: int
    critical_failures: int
    historical_suite_complete: bool
    shadow_ledger_operating: bool
    reproducibility_sample_passed: bool
    subgroup_regression_count: int = 0
    lookahead_leakage_count: int = 0


@dataclass(frozen=True)
class LaunchGateDecision:
    passed: bool
    failures: Tuple[str, ...] = field(default_factory=tuple)
    deferred_longitudinal_metrics: Tuple[str, ...] = (
        "brier_score", "expected_calibration_error",
        "benchmark_relative_return", "thesis_event_accuracy",
    )


def evaluate_launch_gate(
    inputs: LaunchGateInputs,
    thresholds: LaunchGateThresholds = LaunchGateThresholds(),
) -> LaunchGateDecision:
    """Return deterministic launch-gate failures without averaging them away."""
    failures = []
    for name, value in (
        ("material_numerical_accuracy", inputs.material_numerical_accuracy),
        ("claim_source_binding", inputs.claim_source_binding),
    ):
        if value is not None and not 0.0 <= value <= 1.0:
            raise BenchmarkContractError(f"{name} must be between 0 and 1")

    if inputs.material_numerical_accuracy is None:
        failures.append("material numerical accuracy was not measured")
    elif inputs.material_numerical_accuracy < thresholds.material_numerical_accuracy_min:
        failures.append("material numerical accuracy is below 98%")
    if inputs.claim_source_binding is None:
        failures.append("claim-to-source binding was not measured")
    elif inputs.claim_source_binding < thresholds.claim_source_binding_min:
        failures.append("claim-to-source binding is below 95%")
    if inputs.fabricated_material_sources > thresholds.fabricated_material_sources_max:
        failures.append("fabricated material source detected")
    if inputs.cross_account_exposures > thresholds.cross_account_exposures_max:
        failures.append("cross-account exposure detected")
    if inputs.critical_failures > thresholds.critical_failures_max:
        failures.append("critical benchmark failure remains open")
    if inputs.lookahead_leakage_count:
        failures.append("point-in-time look-ahead leakage detected")
    if inputs.subgroup_regression_count:
        failures.append("one or more protected issuer subgroups regressed")
    if not inputs.historical_suite_complete:
        failures.append("sealed historical suite is incomplete")
    if not inputs.shadow_ledger_operating:
        failures.append("live shadow ledger is not operating")
    if not inputs.reproducibility_sample_passed:
        failures.append("reproducibility sample did not pass")
    return LaunchGateDecision(passed=not failures, failures=tuple(failures))

