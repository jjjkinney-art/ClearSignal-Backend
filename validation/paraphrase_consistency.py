"""Deterministic consistency grading across semantically equivalent prompts.

The evaluator consumes structured output signatures prepared by the benchmark
runner.  It does not infer equivalence from prose or reward identical wording.
Instead, it compares the answer behavior, thesis direction, confidence,
material claims and the material risk/catalyst coverage that should survive a
change in phrasing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from itertools import combinations
from math import isfinite
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .intelligence_benchmark import BenchmarkContractError


class AnswerBehavior(str, Enum):
    ANSWER = "answer"
    ABSTAIN = "abstain"
    CLARIFY = "clarify"


class ThesisDirection(str, Enum):
    POSITIVE = "positive"
    MIXED = "mixed"
    NEGATIVE = "negative"
    INSUFFICIENT = "insufficient"


def _text(value: Any, field_name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise BenchmarkContractError(f"{field_name} is required")
    return result


def _unique_sorted(values: Sequence[Any], field_name: str) -> Tuple[str, ...]:
    result = tuple(sorted(_text(value, field_name) for value in values))
    if len(set(result)) != len(result):
        raise BenchmarkContractError(f"{field_name} values must be unique")
    return result


@dataclass(frozen=True)
class ClaimSignature:
    claim_id: str
    value: str
    unit: str
    currency: Optional[str]
    period: str
    scope: str
    source_id: str

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ClaimSignature":
        raw_value = _text(value.get("value"), "value")
        try:
            Decimal(raw_value)
        except InvalidOperation as exc:
            raise BenchmarkContractError("claim value must be decimal") from exc
        return ClaimSignature(
            claim_id=_text(value.get("claim_id"), "claim_id"),
            value=raw_value,
            unit=_text(value.get("unit"), "unit"),
            currency=(str(value["currency"]).strip().upper() if value.get("currency") else None),
            period=_text(value.get("period"), "period"),
            scope=_text(value.get("scope"), "scope").casefold(),
            source_id=_text(value.get("source_id"), "source_id"),
        )

    @property
    def comparable(self) -> Tuple[Optional[str], ...]:
        return (
            str(Decimal(self.value).normalize()), self.unit.casefold(), self.currency, self.period,
            self.scope, self.source_id,
        )


@dataclass(frozen=True)
class ParaphraseVariant:
    variant_id: str
    question: str
    behavior: AnswerBehavior
    direction: ThesisDirection
    confidence: Optional[float]
    claims: Tuple[ClaimSignature, ...]
    material_risk_ids: Tuple[str, ...]
    material_catalyst_ids: Tuple[str, ...]

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ParaphraseVariant":
        try:
            behavior = AnswerBehavior(str(value.get("behavior", "")))
            direction = ThesisDirection(str(value.get("direction", "")))
        except ValueError as exc:
            raise BenchmarkContractError("invalid behavior or thesis direction") from exc
        raw_confidence = value.get("confidence")
        confidence = None if raw_confidence is None else float(raw_confidence)
        if confidence is not None and (not isfinite(confidence) or not 0.0 <= confidence <= 1.0):
            raise BenchmarkContractError("confidence must be between 0 and 1")
        if behavior == AnswerBehavior.ANSWER and confidence is None:
            raise BenchmarkContractError("answered variants require confidence")
        raw_claims = value.get("claims", ())
        if not isinstance(raw_claims, (list, tuple)):
            raise BenchmarkContractError("claims must be a list")
        claims = tuple(ClaimSignature.from_dict(item) for item in raw_claims)
        if len({item.claim_id for item in claims}) != len(claims):
            raise BenchmarkContractError("claim ids must be unique within a variant")
        return ParaphraseVariant(
            variant_id=_text(value.get("variant_id"), "variant_id"),
            question=_text(value.get("question"), "question"),
            behavior=behavior, direction=direction, confidence=confidence,
            claims=tuple(sorted(claims, key=lambda item: item.claim_id)),
            material_risk_ids=_unique_sorted(value.get("material_risk_ids", ()), "material_risk_ids"),
            material_catalyst_ids=_unique_sorted(value.get("material_catalyst_ids", ()), "material_catalyst_ids"),
        )


@dataclass(frozen=True)
class ParaphraseGroup:
    group_id: str
    case_id: str
    issuer_id: str
    as_of: str
    source_snapshot_id: str
    variants: Tuple[ParaphraseVariant, ...]

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ParaphraseGroup":
        raw_variants = value.get("variants", ())
        if not isinstance(raw_variants, (list, tuple)) or len(raw_variants) < 2:
            raise BenchmarkContractError("paraphrase group requires at least two variants")
        variants = tuple(ParaphraseVariant.from_dict(item) for item in raw_variants)
        if len({item.variant_id for item in variants}) != len(variants):
            raise BenchmarkContractError("variant ids must be unique within a group")
        if len({item.question.casefold() for item in variants}) != len(variants):
            raise BenchmarkContractError("paraphrase questions must be distinct")
        return ParaphraseGroup(
            group_id=_text(value.get("group_id"), "group_id"),
            case_id=_text(value.get("case_id"), "case_id"),
            issuer_id=_text(value.get("issuer_id"), "issuer_id"),
            as_of=_text(value.get("as_of"), "as_of"),
            source_snapshot_id=_text(value.get("source_snapshot_id"), "source_snapshot_id"),
            variants=tuple(sorted(variants, key=lambda item: item.variant_id)),
        )


@dataclass(frozen=True)
class ConsistencyFinding:
    code: str
    group_id: str
    left_variant_id: str
    right_variant_id: str
    message: str
    material: bool = True


@dataclass(frozen=True)
class PairResult:
    left_variant_id: str
    right_variant_id: str
    consistent: bool
    confidence_gap: Optional[float]
    risk_overlap: float
    catalyst_overlap: float
    finding_codes: Tuple[str, ...]


@dataclass(frozen=True)
class GroupResult:
    group_id: str
    pair_count: int
    consistent_pair_count: int
    consistency: float
    pairs: Tuple[PairResult, ...]


@dataclass(frozen=True)
class ParaphraseScorecard:
    groups: Tuple[GroupResult, ...]
    findings: Tuple[ConsistencyFinding, ...]
    pair_count: int
    consistent_pair_count: int
    paraphrase_consistency: Optional[float]
    material_inconsistency_count: int
    fully_evaluated: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _overlap(left: Sequence[str], right: Sequence[str]) -> float:
    union = set(left) | set(right)
    return len(set(left) & set(right)) / len(union) if union else 1.0


def _pair_findings(
    group: ParaphraseGroup, left: ParaphraseVariant, right: ParaphraseVariant,
    *, max_confidence_gap: float, minimum_topic_overlap: float,
) -> Tuple[Tuple[ConsistencyFinding, ...], Optional[float], float, float]:
    findings = []

    def add(code: str, message: str) -> None:
        findings.append(ConsistencyFinding(
            code, group.group_id, left.variant_id, right.variant_id, message,
        ))

    if left.behavior != right.behavior:
        add("answer_behavior_changed", "equivalent prompts produced different answer/abstain/clarify behavior")
    if left.direction != right.direction:
        add("thesis_direction_changed", "equivalent prompts produced different thesis directions")
    confidence_gap = None
    if left.confidence is not None and right.confidence is not None:
        confidence_gap = abs(left.confidence - right.confidence)
        if confidence_gap > max_confidence_gap:
            add("confidence_drift", "confidence changed beyond the explicit tolerance")
    elif left.confidence != right.confidence:
        add("confidence_presence_changed", "confidence was emitted for only one equivalent prompt")

    left_claims = {item.claim_id: item for item in left.claims}
    right_claims = {item.claim_id: item for item in right.claims}
    for claim_id in sorted(set(left_claims) | set(right_claims)):
        if claim_id not in left_claims or claim_id not in right_claims:
            add("material_claim_omitted", f"material claim {claim_id} appeared in only one response")
        elif left_claims[claim_id].comparable != right_claims[claim_id].comparable:
            add("material_claim_conflict", f"material claim {claim_id} changed fact or source binding")

    risk_overlap = _overlap(left.material_risk_ids, right.material_risk_ids)
    catalyst_overlap = _overlap(left.material_catalyst_ids, right.material_catalyst_ids)
    if risk_overlap < minimum_topic_overlap:
        add("material_risk_coverage_drift", "material risk coverage changed beyond tolerance")
    if catalyst_overlap < minimum_topic_overlap:
        add("material_catalyst_coverage_drift", "material catalyst coverage changed beyond tolerance")
    return tuple(findings), confidence_gap, risk_overlap, catalyst_overlap


def score_paraphrase_groups(
    groups: Sequence[ParaphraseGroup], *, max_confidence_gap: float = 0.15,
    minimum_topic_overlap: float = 0.5,
) -> ParaphraseScorecard:
    if not 0.0 <= max_confidence_gap <= 1.0:
        raise BenchmarkContractError("max_confidence_gap must be between 0 and 1")
    if not 0.0 <= minimum_topic_overlap <= 1.0:
        raise BenchmarkContractError("minimum_topic_overlap must be between 0 and 1")
    if len({group.group_id for group in groups}) != len(groups):
        raise BenchmarkContractError("paraphrase group ids must be unique")
    group_results = []
    all_findings = []
    total_pairs = consistent_pairs = 0
    for group in sorted(groups, key=lambda item: item.group_id):
        pair_results = []
        group_consistent = 0
        for left, right in combinations(group.variants, 2):
            findings, gap, risk_overlap, catalyst_overlap = _pair_findings(
                group, left, right,
                max_confidence_gap=max_confidence_gap,
                minimum_topic_overlap=minimum_topic_overlap,
            )
            all_findings.extend(findings)
            consistent = not findings
            group_consistent += consistent
            pair_results.append(PairResult(
                left.variant_id, right.variant_id, consistent, gap,
                risk_overlap, catalyst_overlap,
                tuple(item.code for item in findings),
            ))
        pair_count = len(pair_results)
        total_pairs += pair_count
        consistent_pairs += group_consistent
        group_results.append(GroupResult(
            group.group_id, pair_count, group_consistent,
            group_consistent / pair_count, tuple(pair_results),
        ))
    return ParaphraseScorecard(
        groups=tuple(group_results), findings=tuple(all_findings),
        pair_count=total_pairs, consistent_pair_count=consistent_pairs,
        paraphrase_consistency=(consistent_pairs / total_pairs) if total_pairs else None,
        material_inconsistency_count=len(all_findings),
        fully_evaluated=bool(groups) and total_pairs > 0,
    )


def score_payload(payload: Mapping[str, Any]) -> ParaphraseScorecard:
    return score_paraphrase_groups(
        [ParaphraseGroup.from_dict(item) for item in payload.get("groups", ())],
        max_confidence_gap=float(payload.get("max_confidence_gap", 0.15)),
        minimum_topic_overlap=float(payload.get("minimum_topic_overlap", 0.5)),
    )
