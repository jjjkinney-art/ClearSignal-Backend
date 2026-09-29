from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from validation.intelligence_benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    METRIC_DICTIONARY,
    BenchmarkCase,
    BenchmarkContractError,
    BenchmarkProtocol,
    LaunchGateInputs,
    MarketCapTier,
    ScoreFamily,
    SourceSnapshot,
    build_execution_manifest,
    canonical_json,
    content_hash,
    evaluate_launch_gate,
)


def _case(**overrides) -> BenchmarkCase:
    values = dict(
        case_id="AAPL-2025Q1-quality", ticker="AAPL", company="Apple Inc.",
        question="Did earnings quality improve?", category="quality_of_earnings",
        protocol=BenchmarkProtocol.FROZEN_HISTORICAL,
        as_of="2025-02-01T21:00:00Z",
        market_cap_tier=MarketCapTier.MEGA_LARGE,
        sector="Information Technology", difficulty_tags=("fiscal_period",),
    )
    values.update(overrides)
    return BenchmarkCase(**values)


def _source(**overrides) -> SourceSnapshot:
    values = dict(
        source_id="sec-10q-2025q1", source_type="sec_filing",
        document_url="https://www.sec.gov/example",
        published_at="2025-01-31T21:05:00Z",
        retrieved_at="2025-02-01T09:00:00-05:00",
        content_sha256="a" * 64, authoritative=True,
    )
    values.update(overrides)
    return SourceSnapshot(**values)


def _manifest(**overrides):
    values = dict(
        case=_case(), output={"conclusion": "quality improved"},
        run_id="run-001", generated_at="2025-02-02T00:00:00Z",
        build_commit="abc123", model_id="test-model", prompt_version="v1",
        retrieval_version="v1", feature_flags={"memory": False, "sources": True},
        sources=[_source()],
    )
    values.update(overrides)
    return build_execution_manifest(**values)


def _passing_gate(**overrides) -> LaunchGateInputs:
    values = dict(
        material_numerical_accuracy=0.99, claim_source_binding=0.97,
        fabricated_material_sources=0, cross_account_exposures=0,
        critical_failures=0, historical_suite_complete=True,
        shadow_ledger_operating=True, reproducibility_sample_passed=True,
    )
    values.update(overrides)
    return LaunchGateInputs(**values)


def test_case_requires_timezone_aware_as_of():
    with pytest.raises(BenchmarkContractError, match="timezone"):
        _case(as_of="2025-02-01T21:00:00")


def test_case_supports_explicit_abstention():
    assert _case(expected_behavior="abstain").expected_behavior == "abstain"


def test_case_rejects_unknown_expected_behavior():
    with pytest.raises(BenchmarkContractError, match="expected_behavior"):
        _case(expected_behavior="guess")


def test_source_published_after_boundary_is_rejected():
    with pytest.raises(BenchmarkContractError, match="after the as-of"):
        _manifest(sources=[_source(published_at="2025-02-02T00:00:00Z")])


def test_source_retrieved_before_publication_is_rejected():
    with pytest.raises(BenchmarkContractError, match="before publication"):
        _manifest(sources=[_source(retrieved_at="2025-01-01T00:00:00Z")])


def test_source_requires_real_sha256_shape():
    with pytest.raises(BenchmarkContractError, match="SHA-256"):
        _manifest(sources=[_source(content_sha256="short")])


def test_manifest_sorts_sources_and_feature_flags_deterministically():
    source_b = _source(source_id="b", content_sha256="b" * 64)
    source_a = _source(source_id="a", content_sha256="a" * 64)
    manifest = _manifest(
        sources=[source_b, source_a], feature_flags={"z": True, "a": False},
    )
    assert [item.source_id for item in manifest.sources] == ["a", "b"]
    assert manifest.feature_flags == (("a", False), ("z", True))


def test_manifest_rejects_duplicate_source_ids():
    with pytest.raises(BenchmarkContractError, match="unique"):
        _manifest(sources=[_source(), _source(content_sha256="b" * 64)])


def test_output_hash_is_key_order_independent():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def test_manifest_hash_is_stable_and_schema_versioned():
    first = _manifest()
    second = _manifest(feature_flags={"sources": True, "memory": False})
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.schema_version == BENCHMARK_SCHEMA_VERSION
    assert len(first.manifest_sha256) == 64


def test_canonical_json_rejects_nan():
    with pytest.raises(ValueError):
        canonical_json({"score": float("nan")})


def test_manifest_is_immutable():
    manifest = _manifest()
    with pytest.raises(FrozenInstanceError):
        manifest.run_id = "changed"  # type: ignore[misc]


def test_metric_families_remain_separate():
    families = {metric.family for metric in METRIC_DICTIONARY}
    assert ScoreFamily.FACTUAL_INTEGRITY in families
    assert ScoreFamily.ANALYTICAL_QUALITY in families
    assert ScoreFamily.MARKET_USEFULNESS in families
    assert len({metric.key for metric in METRIC_DICTIONARY}) == len(METRIC_DICTIONARY)


def test_market_metrics_are_marked_as_maturity_dependent():
    mature = {metric.key for metric in METRIC_DICTIONARY if metric.requires_mature_outcome}
    assert "benchmark_relative_return" in mature
    assert "brier_score" in mature
    assert "material_numerical_accuracy" not in mature


def test_launch_gate_passes_without_waiting_for_twelve_month_returns():
    decision = evaluate_launch_gate(_passing_gate())
    assert decision.passed is True
    assert "benchmark_relative_return" in decision.deferred_longitudinal_metrics


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"material_numerical_accuracy": 0.979}, "below 98%"),
        ({"claim_source_binding": 0.949}, "below 95%"),
        ({"fabricated_material_sources": 1}, "fabricated material source"),
        ({"cross_account_exposures": 1}, "cross-account exposure"),
        ({"critical_failures": 1}, "critical benchmark failure"),
        ({"lookahead_leakage_count": 1}, "look-ahead leakage"),
        ({"subgroup_regression_count": 1}, "issuer subgroups regressed"),
        ({"historical_suite_complete": False}, "historical suite is incomplete"),
        ({"shadow_ledger_operating": False}, "shadow ledger is not operating"),
        ({"reproducibility_sample_passed": False}, "reproducibility sample"),
    ],
)
def test_each_stop_ship_condition_fails_independently(override, expected):
    decision = evaluate_launch_gate(_passing_gate(**override))
    assert decision.passed is False
    assert any(expected in failure for failure in decision.failures)


def test_missing_required_measurement_fails_closed():
    decision = evaluate_launch_gate(
        _passing_gate(material_numerical_accuracy=None, claim_source_binding=None)
    )
    assert decision.passed is False
    assert len(decision.failures) == 2


def test_invalid_ratio_is_rejected_not_clamped():
    with pytest.raises(BenchmarkContractError, match="between 0 and 1"):
        evaluate_launch_gate(_passing_gate(material_numerical_accuracy=1.2))

