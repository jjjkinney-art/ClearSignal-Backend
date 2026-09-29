"""Deterministic factual and citation grading for benchmark claims.

The grader does not infer citation entailment from lexical overlap.  A citation
must carry an explicit adjudication produced by an approved automated grader or
human review workflow.  ``pending`` remains unverified and can never satisfy a
launch threshold.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .intelligence_benchmark import BenchmarkContractError


class Materiality(str, Enum):
    CONSEQUENTIAL = "consequential"
    MATERIAL = "material"
    SUPPORTING = "supporting"


class EntailmentLabel(str, Enum):
    SUPPORTS = "supports"
    PARTIAL = "partial"
    CONTRADICTS = "contradicts"
    NOT_FOUND = "not_found"
    PENDING = "pending"


@dataclass(frozen=True)
class ExpectedClaim:
    claim_id: str
    metric: str
    value: str
    unit: str
    currency: Optional[str]
    period: str
    scope: str
    source_id: str
    materiality: Materiality
    absolute_tolerance: str = "0"

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ExpectedClaim":
        required = ("claim_id", "metric", "value", "unit", "period", "scope", "source_id")
        if any(not str(value.get(key, "")).strip() for key in required):
            raise BenchmarkContractError(f"expected claim requires fields: {required}")
        try:
            materiality = Materiality(str(value["materiality"]))
            Decimal(str(value["value"]))
            tolerance = Decimal(str(value.get("absolute_tolerance", "0")))
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise BenchmarkContractError("expected claim has invalid numeric or materiality data") from exc
        if tolerance < 0:
            raise BenchmarkContractError("absolute_tolerance cannot be negative")
        return ExpectedClaim(
            claim_id=str(value["claim_id"]), metric=str(value["metric"]),
            value=str(value["value"]), unit=str(value["unit"]),
            currency=(str(value["currency"]) if value.get("currency") else None),
            period=str(value["period"]), scope=str(value["scope"]),
            source_id=str(value["source_id"]), materiality=materiality,
            absolute_tolerance=str(value.get("absolute_tolerance", "0")),
        )


@dataclass(frozen=True)
class ObservedClaim:
    claim_id: str
    text: str
    value: str
    unit: str
    currency: Optional[str]
    period: str
    scope: str
    cited_source_id: Optional[str]

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ObservedClaim":
        claim_id = str(value.get("claim_id", "")).strip()
        if not claim_id:
            raise BenchmarkContractError("observed claim_id is required")
        try:
            Decimal(str(value["value"]))
        except (KeyError, InvalidOperation) as exc:
            raise BenchmarkContractError(
                f"observed claim {claim_id} requires a decimal value"
            ) from exc
        return ObservedClaim(
            claim_id=claim_id, text=str(value.get("text", "")),
            value=str(value["value"]), unit=str(value.get("unit", "")),
            currency=(str(value["currency"]) if value.get("currency") else None),
            period=str(value.get("period", "")), scope=str(value.get("scope", "")),
            cited_source_id=(str(value["cited_source_id"]) if value.get("cited_source_id") else None),
        )


@dataclass(frozen=True)
class CitationAdjudication:
    claim_id: str
    source_id: str
    document_exists: bool
    label: EntailmentLabel
    reviewer: str
    rationale: str

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "CitationAdjudication":
        try:
            label = EntailmentLabel(str(value["label"]))
        except (KeyError, ValueError) as exc:
            raise BenchmarkContractError("citation adjudication has invalid label") from exc
        if not str(value.get("claim_id", "")).strip() or not str(value.get("source_id", "")).strip():
            raise BenchmarkContractError("citation adjudication requires claim_id and source_id")
        reviewer = str(value.get("reviewer", "")).strip()
        if not reviewer:
            raise BenchmarkContractError("citation adjudication requires reviewer identity")
        return CitationAdjudication(
            claim_id=str(value["claim_id"]), source_id=str(value["source_id"]),
            document_exists=bool(value.get("document_exists", False)),
            label=label, reviewer=reviewer,
            rationale=str(value.get("rationale", "")),
        )


@dataclass(frozen=True)
class GradeFinding:
    code: str
    claim_id: str
    message: str
    stop_ship: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClaimGrade:
    claim_id: str
    materiality: Materiality
    value_correct: bool
    unit_correct: bool
    currency_correct: bool
    period_correct: bool
    scope_correct: bool
    numerical_fact_correct: bool
    source_binding_correct: bool
    entailment_label: Optional[EntailmentLabel]


@dataclass(frozen=True)
class FactualCitationScorecard:
    claim_grades: Tuple[ClaimGrade, ...]
    findings: Tuple[GradeFinding, ...]
    material_claim_count: int
    material_numerical_correct_count: int
    material_numerical_accuracy: Optional[float]
    source_binding_required_count: int
    source_binding_correct_count: int
    claim_source_binding: Optional[float]
    fabricated_material_sources: int
    pending_material_adjudications: int
    fully_adjudicated: bool

    @property
    def stop_ship_count(self) -> int:
        return sum(finding.stop_ship for finding in self.findings)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        for grade in result["claim_grades"]:
            grade["materiality"] = grade["materiality"].value
            if grade["entailment_label"] is not None:
                grade["entailment_label"] = grade["entailment_label"].value
        return result


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return numerator / denominator if denominator else None


def grade_factual_citations(
    *, expected_claims: Sequence[ExpectedClaim],
    observed_claims: Sequence[ObservedClaim],
    adjudications: Sequence[CitationAdjudication],
) -> FactualCitationScorecard:
    expected_by_id = {claim.claim_id: claim for claim in expected_claims}
    observed_by_id = {claim.claim_id: claim for claim in observed_claims}
    adjudication_by_claim = {item.claim_id: item for item in adjudications}
    if len(expected_by_id) != len(expected_claims):
        raise BenchmarkContractError("expected claim ids must be unique")
    if len(observed_by_id) != len(observed_claims):
        raise BenchmarkContractError("observed claim ids must be unique")
    if len(adjudication_by_claim) != len(adjudications):
        raise BenchmarkContractError("one adjudication is allowed per claim")

    findings = []
    grades = []
    material_total = material_correct = 0
    binding_total = binding_correct = 0
    fabricated_material_sources = pending_material = 0

    for claim_id in sorted(expected_by_id):
        expected = expected_by_id[claim_id]
        observed = observed_by_id.get(claim_id)
        is_material = expected.materiality in {
            Materiality.CONSEQUENTIAL, Materiality.MATERIAL,
        }
        if is_material:
            material_total += 1
            binding_total += 1
        if observed is None:
            findings.append(GradeFinding(
                "missing_expected_claim", claim_id,
                "expected claim was absent from the analysis", is_material,
            ))
            grades.append(ClaimGrade(
                claim_id, expected.materiality, False, False, False, False,
                False, False, False, None,
            ))
            continue

        actual = Decimal(observed.value)
        target = Decimal(expected.value)
        tolerance = Decimal(expected.absolute_tolerance)
        value_correct = abs(actual - target) <= tolerance
        unit_correct = observed.unit.casefold() == expected.unit.casefold()
        currency_correct = (observed.currency or "").upper() == (expected.currency or "").upper()
        period_correct = observed.period == expected.period
        scope_correct = observed.scope.casefold() == expected.scope.casefold()
        dimension_values = {
            "value": value_correct, "unit": unit_correct,
            "currency": currency_correct, "period": period_correct,
            "scope": scope_correct,
        }
        for dimension, correct in dimension_values.items():
            if not correct:
                findings.append(GradeFinding(
                    f"{dimension}_mismatch", claim_id,
                    f"observed {dimension} does not match the frozen reference",
                    is_material,
                ))
        numerical_correct = all(dimension_values.values())
        if is_material and numerical_correct:
            material_correct += 1

        adjudication = adjudication_by_claim.get(claim_id)
        source_binding_correct = False
        entailment = adjudication.label if adjudication else None
        if not observed.cited_source_id:
            findings.append(GradeFinding(
                "missing_citation", claim_id, "claim has no cited source", is_material,
            ))
        elif adjudication is None:
            if is_material:
                pending_material += 1
            findings.append(GradeFinding(
                "citation_not_adjudicated", claim_id,
                "citation support has not been adjudicated", is_material,
            ))
        else:
            same_claim_and_source = (
                adjudication.claim_id == claim_id
                and adjudication.source_id == observed.cited_source_id
            )
            if not adjudication.document_exists:
                if is_material:
                    fabricated_material_sources += 1
                findings.append(GradeFinding(
                    "fabricated_or_missing_source", claim_id,
                    "cited document does not exist", is_material,
                ))
            if observed.cited_source_id != expected.source_id:
                findings.append(GradeFinding(
                    "wrong_source_binding", claim_id,
                    "claim is not bound to the frozen reference source", is_material,
                ))
            if adjudication.label == EntailmentLabel.PENDING:
                if is_material:
                    pending_material += 1
                findings.append(GradeFinding(
                    "citation_entailment_pending", claim_id,
                    "citation entailment remains pending", is_material,
                ))
            elif adjudication.label != EntailmentLabel.SUPPORTS:
                findings.append(GradeFinding(
                    "citation_does_not_support_claim", claim_id,
                    f"citation adjudication is {adjudication.label.value}", is_material,
                ))
            source_binding_correct = (
                same_claim_and_source
                and adjudication.document_exists
                and observed.cited_source_id == expected.source_id
                and adjudication.label == EntailmentLabel.SUPPORTS
            )
        if is_material and source_binding_correct:
            binding_correct += 1
        grades.append(ClaimGrade(
            claim_id=claim_id, materiality=expected.materiality,
            value_correct=value_correct, unit_correct=unit_correct,
            currency_correct=currency_correct, period_correct=period_correct,
            scope_correct=scope_correct, numerical_fact_correct=numerical_correct,
            source_binding_correct=source_binding_correct,
            entailment_label=entailment,
        ))

    for claim_id in sorted(set(observed_by_id) - set(expected_by_id)):
        findings.append(GradeFinding(
            "unexpected_unscored_claim", claim_id,
            "observed claim has no frozen reference and was not scored", False,
        ))
    fully_adjudicated = pending_material == 0 and all(
        claim_id in observed_by_id and claim_id in adjudication_by_claim
        for claim_id, claim in expected_by_id.items()
        if claim.materiality in {Materiality.CONSEQUENTIAL, Materiality.MATERIAL}
    )
    return FactualCitationScorecard(
        claim_grades=tuple(grades), findings=tuple(findings),
        material_claim_count=material_total,
        material_numerical_correct_count=material_correct,
        material_numerical_accuracy=_ratio(material_correct, material_total),
        source_binding_required_count=binding_total,
        source_binding_correct_count=binding_correct,
        claim_source_binding=_ratio(binding_correct, binding_total),
        fabricated_material_sources=fabricated_material_sources,
        pending_material_adjudications=pending_material,
        fully_adjudicated=fully_adjudicated,
    )


def grade_payload(payload: Mapping[str, Any]) -> FactualCitationScorecard:
    return grade_factual_citations(
        expected_claims=[ExpectedClaim.from_dict(item) for item in payload.get("expected_claims", ())],
        observed_claims=[ObservedClaim.from_dict(item) for item in payload.get("observed_claims", ())],
        adjudications=[CitationAdjudication.from_dict(item) for item in payload.get("adjudications", ())],
    )

