"""Aggregate factual/citation quality gates for smaller-company cohorts.

The cohort runner is deliberately offline and side-effect free. Individual
claim packs remain the unit of adjudication; this module proves that acceptable
averages are not hiding an unreviewed issuer or a weak market-cap subgroup.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Mapping, Sequence, Tuple

from .benchmark_registry import IssuerRegistry, load_registry
from .factual_citation_grading import FactualCitationScorecard, grade_payload
from .intelligence_benchmark import BenchmarkContractError
from .point_in_time_sources import audit_point_in_time_sources


SCHEMA_VERSION = 1
REQUIRED_TIERS = ("mid", "small_micro")
MINIMUM_ISSUERS_PER_TIER = 3
MINIMUM_MATERIAL_NUMERICAL_ACCURACY = 0.95
MINIMUM_CLAIM_SOURCE_BINDING = 1.0


@dataclass(frozen=True)
class IssuerFactualResult:
    issuer_id: str
    market_cap_tier: str
    material_claim_count: int
    material_numerical_correct_count: int
    source_binding_required_count: int
    source_binding_correct_count: int
    fabricated_material_sources: int
    pending_material_adjudications: int
    stop_ship_count: int
    fully_adjudicated: bool
    comparison_count: int
    comparison_correct_count: int
    passed: bool


@dataclass(frozen=True)
class TierFactualResult:
    market_cap_tier: str
    issuer_count: int
    material_claim_count: int
    material_numerical_accuracy: float
    claim_source_binding: float
    fabricated_material_sources: int
    pending_material_adjudications: int
    stop_ship_count: int
    passed: bool


@dataclass(frozen=True)
class CapTierFactualReport:
    schema_version: int
    cohort_id: str
    issuer_count: int
    issuer_results: Tuple[IssuerFactualResult, ...]
    tier_results: Tuple[TierFactualResult, ...]
    passed: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _issuer_result(
    issuer_id: str, tier: str, scorecard: FactualCitationScorecard,
    comparison_count: int, comparison_correct_count: int,
) -> IssuerFactualResult:
    passed = (
        scorecard.material_claim_count > 0
        and scorecard.fully_adjudicated
        and scorecard.stop_ship_count == 0
        and scorecard.fabricated_material_sources == 0
        and scorecard.material_numerical_accuracy is not None
        and scorecard.material_numerical_accuracy
        >= MINIMUM_MATERIAL_NUMERICAL_ACCURACY
        and scorecard.claim_source_binding is not None
        and scorecard.claim_source_binding >= MINIMUM_CLAIM_SOURCE_BINDING
        and comparison_correct_count == comparison_count
    )
    return IssuerFactualResult(
        issuer_id=issuer_id,
        market_cap_tier=tier,
        material_claim_count=scorecard.material_claim_count,
        material_numerical_correct_count=(
            scorecard.material_numerical_correct_count
        ),
        source_binding_required_count=scorecard.source_binding_required_count,
        source_binding_correct_count=scorecard.source_binding_correct_count,
        fabricated_material_sources=scorecard.fabricated_material_sources,
        pending_material_adjudications=(
            scorecard.pending_material_adjudications
        ),
        stop_ship_count=scorecard.stop_ship_count,
        fully_adjudicated=scorecard.fully_adjudicated,
        comparison_count=comparison_count,
        comparison_correct_count=comparison_correct_count,
        passed=passed,
    )


def grade_comparison_counts(claim_payload: Mapping[str, Any]) -> Tuple[int, int]:
    comparisons = claim_payload.get("comparisons", [])
    if not isinstance(comparisons, list):
        raise BenchmarkContractError("comparisons must be a list")
    expected = {
        str(item.get("claim_id")): item
        for item in claim_payload.get("expected_claims", ())
        if isinstance(item, Mapping)
    }
    observed = {
        str(item.get("claim_id")): item
        for item in claim_payload.get("observed_claims", ())
        if isinstance(item, Mapping)
    }
    seen = set()
    correct = 0
    for item in comparisons:
        if not isinstance(item, Mapping):
            raise BenchmarkContractError("each comparison must be an object")
        comparison_id = str(item.get("comparison_id", "")).strip()
        current_id = str(item.get("current_claim_id", "")).strip()
        prior_id = str(item.get("prior_claim_id", "")).strip()
        if not comparison_id or comparison_id in seen:
            raise BenchmarkContractError("comparison ids must be present and unique")
        if current_id not in expected or prior_id not in expected:
            raise BenchmarkContractError("comparison references unknown expected claims")
        current_expected = expected[current_id]
        prior_expected = expected[prior_id]
        comparable_fields = ("metric", "unit", "currency", "scope")
        if any(
            str(current_expected.get(field)) != str(prior_expected.get(field))
            for field in comparable_fields
        ) or current_expected.get("period") == prior_expected.get("period"):
            raise BenchmarkContractError(
                "comparison claims must share metric/unit/currency/scope and use distinct periods"
            )
        seen.add(comparison_id)
        try:
            expected_delta = Decimal(str(current_expected["value"])) - Decimal(
                str(prior_expected["value"])
            )
            declared_delta = Decimal(str(item["absolute_change"]))
            current_observed = Decimal(str(observed[current_id]["value"]))
            prior_observed = Decimal(str(observed[prior_id]["value"]))
        except (KeyError, InvalidOperation) as exc:
            raise BenchmarkContractError(
                "comparison values and referenced observed claims are required"
            ) from exc
        observed_delta = current_observed - prior_observed
        direction = "increase" if observed_delta > 0 else (
            "decrease" if observed_delta < 0 else "flat"
        )
        if (
            declared_delta == expected_delta
            and observed_delta == expected_delta
            and str(item.get("direction")) == direction
        ):
            correct += 1
    return len(comparisons), correct


def _tier_result(
    tier: str, members: Sequence[IssuerFactualResult],
) -> TierFactualResult:
    material_total = sum(item.material_claim_count for item in members)
    material_correct = sum(
        item.material_numerical_correct_count for item in members
    )
    binding_total = sum(item.source_binding_required_count for item in members)
    binding_correct = sum(item.source_binding_correct_count for item in members)
    fabricated = sum(item.fabricated_material_sources for item in members)
    pending = sum(item.pending_material_adjudications for item in members)
    stop_ship = sum(item.stop_ship_count for item in members)
    numerical_accuracy = _ratio(material_correct, material_total)
    source_binding = _ratio(binding_correct, binding_total)
    passed = (
        len(members) >= MINIMUM_ISSUERS_PER_TIER
        and all(item.passed for item in members)
        and numerical_accuracy >= MINIMUM_MATERIAL_NUMERICAL_ACCURACY
        and source_binding >= MINIMUM_CLAIM_SOURCE_BINDING
        and fabricated == 0
        and pending == 0
        and stop_ship == 0
    )
    return TierFactualResult(
        market_cap_tier=tier,
        issuer_count=len(members),
        material_claim_count=material_total,
        material_numerical_accuracy=numerical_accuracy,
        claim_source_binding=source_binding,
        fabricated_material_sources=fabricated,
        pending_material_adjudications=pending,
        stop_ship_count=stop_ship,
        passed=passed,
    )


def grade_cap_tier_cohort(
    payload: Mapping[str, Any], *, registry: IssuerRegistry | None = None,
) -> CapTierFactualReport:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise BenchmarkContractError("cap-tier factual schema_version must be 1")
    cohort_id = str(payload.get("cohort_id", "")).strip()
    if not cohort_id:
        raise BenchmarkContractError("cap-tier factual cohort_id is required")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise BenchmarkContractError("cap-tier factual cases must be a list")

    registry = registry or load_registry()
    issuers = registry.by_ticker()
    seen = set()
    results = []
    for case in cases:
        if not isinstance(case, Mapping):
            raise BenchmarkContractError("each cap-tier factual case must be an object")
        issuer_id = str(case.get("issuer_id", "")).upper().strip()
        if issuer_id in seen:
            raise BenchmarkContractError("cap-tier factual issuer ids must be unique")
        issuer = issuers.get(issuer_id)
        if issuer is None:
            raise BenchmarkContractError(
                f"cap-tier factual issuer {issuer_id or '<missing>'} is unregistered"
            )
        tier = issuer.market_cap_tier.value
        if tier not in REQUIRED_TIERS:
            raise BenchmarkContractError(
                "cap-tier factual cohort accepts only mid and small_micro issuers"
            )
        claim_payload = case.get("claim_payload")
        if not isinstance(claim_payload, Mapping):
            raise BenchmarkContractError("each case requires a claim_payload object")
        as_of = str(case.get("as_of", "")).strip()
        sources = case.get("sources")
        if not as_of or not isinstance(sources, list):
            raise BenchmarkContractError(
                "each case requires an as_of boundary and source list"
            )
        source_audit = audit_point_in_time_sources(as_of=as_of, records=sources)
        if not source_audit.passed:
            codes = ", ".join(sorted({
                finding.code for finding in source_audit.findings
                if finding.severity.value == "stop_ship"
            }))
            raise BenchmarkContractError(
                f"cap-tier factual source gate failed for {issuer_id}: {codes}"
            )
        admitted_source_ids = {item.source_id for item in source_audit.admitted}
        expected_source_ids = {
            str(item.get("source_id", ""))
            for item in claim_payload.get("expected_claims", ())
            if isinstance(item, Mapping)
        }
        if not expected_source_ids or not expected_source_ids <= admitted_source_ids:
            raise BenchmarkContractError(
                f"cap-tier factual claims for {issuer_id} require admitted sources"
            )
        seen.add(issuer_id)
        comparison_count, comparison_correct = grade_comparison_counts(claim_payload)
        results.append(_issuer_result(
            issuer_id, tier, grade_payload(claim_payload),
            comparison_count, comparison_correct,
        ))

    results.sort(key=lambda item: item.issuer_id)
    tier_results = tuple(
        _tier_result(tier, [item for item in results if item.market_cap_tier == tier])
        for tier in REQUIRED_TIERS
    )
    return CapTierFactualReport(
        schema_version=SCHEMA_VERSION,
        cohort_id=cohort_id,
        issuer_count=len(results),
        issuer_results=tuple(results),
        tier_results=tier_results,
        passed=all(item.passed for item in tier_results),
    )
