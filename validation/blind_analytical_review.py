"""Blind analytical review contracts and inter-reviewer agreement reporting.

This module intentionally remains offline and dependency-free.  Reviewers see
only an opaque output token and the material required to apply the rubric; model,
provider, prompt, build, treatment and memory identities are rejected.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from itertools import combinations
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .intelligence_benchmark import BenchmarkContractError, content_hash


RUBRIC_DIMENSIONS: Tuple[str, ...] = (
    "responsiveness",
    "reasoning",
    "materiality",
    "counterarguments",
    "uncertainty",
    "usefulness",
)

FORBIDDEN_BLIND_FIELDS = frozenset({
    "model", "model_id", "provider", "build", "build_commit", "commit",
    "prompt", "prompt_version", "retrieval_version", "treatment", "variant",
    "memory_fixture_id", "system_name", "vendor",
})


class ReviewVerdict(str, Enum):
    PASS = "pass"
    REVIEW = "review"
    FAIL = "fail"


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BenchmarkContractError(f"{field_name} is required")
    return text


def _reject_identity_leakage(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold()
            if normalized in FORBIDDEN_BLIND_FIELDS:
                raise BenchmarkContractError(
                    f"blind review payload exposes forbidden field {path}.{key}"
                )
            _reject_identity_leakage(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_identity_leakage(item, f"{path}[{index}]")


@dataclass(frozen=True)
class BlindReviewPacket:
    case_id: str
    blind_output_id: str
    question: str
    analysis: Mapping[str, Any]
    rubric_version: str

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "BlindReviewPacket":
        packet = BlindReviewPacket(
            case_id=_required_text(value.get("case_id"), "case_id"),
            blind_output_id=_required_text(value.get("blind_output_id"), "blind_output_id"),
            question=_required_text(value.get("question"), "question"),
            analysis=value.get("analysis", {}),
            rubric_version=_required_text(value.get("rubric_version"), "rubric_version"),
        )
        if not isinstance(packet.analysis, Mapping):
            raise BenchmarkContractError("analysis must be an object")
        _reject_identity_leakage(value)
        return packet


def blind_output_id(run_id: str, blinding_secret: str) -> str:
    """Return a stable opaque identifier without publishing the source run id."""
    run_id = _required_text(run_id, "run_id")
    secret = _required_text(blinding_secret, "blinding_secret")
    if len(secret) < 16:
        raise BenchmarkContractError("blinding_secret must contain at least 16 characters")
    return content_hash({"namespace": secret, "run_id": run_id})


@dataclass(frozen=True)
class ReviewAssignment:
    assignment_id: str
    blind_output_id: str
    reviewer_id: str
    rubric_version: str

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ReviewAssignment":
        return ReviewAssignment(*(
            _required_text(value.get(field), field) for field in (
                "assignment_id", "blind_output_id", "reviewer_id", "rubric_version"
            )
        ))


def assign_reviews(
    *, blind_output_ids: Sequence[str], reviewer_ids: Sequence[str],
    rubric_version: str, reviews_per_output: int = 2,
) -> Tuple[ReviewAssignment, ...]:
    """Deterministically balance blind outputs across distinct reviewers."""
    outputs = tuple(sorted({_required_text(item, "blind_output_id") for item in blind_output_ids}))
    reviewers = tuple(sorted({_required_text(item, "reviewer_id") for item in reviewer_ids}))
    rubric_version = _required_text(rubric_version, "rubric_version")
    if len(outputs) != len(blind_output_ids):
        raise BenchmarkContractError("blind_output_ids must be unique")
    if len(reviewers) != len(reviewer_ids):
        raise BenchmarkContractError("reviewer_ids must be unique")
    if reviews_per_output < 2:
        raise BenchmarkContractError("at least two reviews per output are required")
    if reviews_per_output > len(reviewers):
        raise BenchmarkContractError("not enough distinct reviewers")
    assignments = []
    for output_index, output_id in enumerate(outputs):
        for slot in range(reviews_per_output):
            reviewer = reviewers[(output_index + slot) % len(reviewers)]
            assignment_id = content_hash({
                "blind_output_id": output_id,
                "reviewer_id": reviewer,
                "rubric_version": rubric_version,
            })
            assignments.append(ReviewAssignment(
                assignment_id, output_id, reviewer, rubric_version,
            ))
    return tuple(assignments)


@dataclass(frozen=True)
class AnalyticalReview:
    assignment_id: str
    blind_output_id: str
    reviewer_id: str
    rubric_version: str
    scores: Tuple[Tuple[str, int], ...]
    verdict: ReviewVerdict
    rationale: str

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "AnalyticalReview":
        raw_scores = value.get("scores")
        if not isinstance(raw_scores, Mapping):
            raise BenchmarkContractError("scores must be an object")
        if set(raw_scores) != set(RUBRIC_DIMENSIONS):
            raise BenchmarkContractError(
                f"scores must contain exactly: {RUBRIC_DIMENSIONS}"
            )
        scores = []
        for dimension in RUBRIC_DIMENSIONS:
            score = raw_scores[dimension]
            if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
                raise BenchmarkContractError(f"{dimension} score must be an integer from 1 to 5")
            scores.append((dimension, score))
        try:
            verdict = ReviewVerdict(str(value.get("verdict", "")))
        except ValueError as exc:
            raise BenchmarkContractError("verdict must be pass, review, or fail") from exc
        return AnalyticalReview(
            assignment_id=_required_text(value.get("assignment_id"), "assignment_id"),
            blind_output_id=_required_text(value.get("blind_output_id"), "blind_output_id"),
            reviewer_id=_required_text(value.get("reviewer_id"), "reviewer_id"),
            rubric_version=_required_text(value.get("rubric_version"), "rubric_version"),
            scores=tuple(scores), verdict=verdict,
            rationale=_required_text(value.get("rationale"), "rationale"),
        )

    @property
    def score_map(self) -> Dict[str, int]:
        return dict(self.scores)

    @property
    def normalized_score(self) -> float:
        return sum(score for _, score in self.scores) / (5 * len(self.scores))


@dataclass(frozen=True)
class OutputAgreement:
    blind_output_id: str
    review_count: int
    pair_count: int
    analytical_quality: float
    dimension_agreement_rate: float
    mean_absolute_dimension_gap: float
    verdict_agreement: bool
    requires_adjudication: bool


@dataclass(frozen=True)
class BlindReviewScorecard:
    outputs: Tuple[OutputAgreement, ...]
    analytical_quality: Optional[float]
    dimension_agreement_rate: Optional[float]
    mean_absolute_dimension_gap: Optional[float]
    assigned_review_count: int
    completed_review_count: int
    missing_assignment_ids: Tuple[str, ...]
    unresolved_output_ids: Tuple[str, ...]
    fully_reviewed: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def score_blind_reviews(
    *, assignments: Sequence[ReviewAssignment], reviews: Sequence[AnalyticalReview],
) -> BlindReviewScorecard:
    assignment_by_id = {item.assignment_id: item for item in assignments}
    if len(assignment_by_id) != len(assignments):
        raise BenchmarkContractError("assignment ids must be unique")
    review_by_assignment = {item.assignment_id: item for item in reviews}
    if len(review_by_assignment) != len(reviews):
        raise BenchmarkContractError("one review is allowed per assignment")
    unknown = sorted(set(review_by_assignment) - set(assignment_by_id))
    if unknown:
        raise BenchmarkContractError(f"reviews reference unknown assignments: {unknown}")

    for assignment_id, review in review_by_assignment.items():
        assignment = assignment_by_id[assignment_id]
        if (
            review.blind_output_id != assignment.blind_output_id
            or review.reviewer_id != assignment.reviewer_id
            or review.rubric_version != assignment.rubric_version
        ):
            raise BenchmarkContractError(
                f"review identity does not match assignment {assignment_id}"
            )

    expected_by_output: Dict[str, list[ReviewAssignment]] = {}
    for assignment in assignments:
        expected_by_output.setdefault(assignment.blind_output_id, []).append(assignment)
    if any(len({item.reviewer_id for item in group}) < 2 for group in expected_by_output.values()):
        raise BenchmarkContractError("each output requires two distinct assigned reviewers")

    results = []
    total_pair_dimensions = agreeing_pair_dimensions = 0
    total_gap = 0
    unresolved = []
    completed_scores = []
    for output_id in sorted(expected_by_output):
        completed = [
            review_by_assignment[item.assignment_id]
            for item in expected_by_output[output_id]
            if item.assignment_id in review_by_assignment
        ]
        completed_scores.extend(review.normalized_score for review in completed)
        pairs = list(combinations(completed, 2))
        agreeing = 0
        gap_sum = 0
        for left, right in pairs:
            for dimension in RUBRIC_DIMENSIONS:
                gap = abs(left.score_map[dimension] - right.score_map[dimension])
                gap_sum += gap
                agreeing += gap <= 1
        denominator = len(pairs) * len(RUBRIC_DIMENSIONS)
        agreement_rate = agreeing / denominator if denominator else 0.0
        mean_gap = gap_sum / denominator if denominator else 0.0
        verdict_agreement = bool(completed) and len({item.verdict for item in completed}) == 1
        complete = len(completed) == len(expected_by_output[output_id]) and len(completed) >= 2
        requires_adjudication = (not complete) or (not verdict_agreement) or mean_gap > 1.0
        if requires_adjudication:
            unresolved.append(output_id)
        total_pair_dimensions += denominator
        agreeing_pair_dimensions += agreeing
        total_gap += gap_sum
        results.append(OutputAgreement(
            blind_output_id=output_id,
            review_count=len(completed), pair_count=len(pairs),
            analytical_quality=(sum(item.normalized_score for item in completed) / len(completed)) if completed else 0.0,
            dimension_agreement_rate=agreement_rate,
            mean_absolute_dimension_gap=mean_gap,
            verdict_agreement=verdict_agreement,
            requires_adjudication=requires_adjudication,
        ))

    missing = tuple(sorted(set(assignment_by_id) - set(review_by_assignment)))
    return BlindReviewScorecard(
        outputs=tuple(results),
        analytical_quality=(sum(completed_scores) / len(completed_scores)) if completed_scores else None,
        dimension_agreement_rate=(agreeing_pair_dimensions / total_pair_dimensions) if total_pair_dimensions else None,
        mean_absolute_dimension_gap=(total_gap / total_pair_dimensions) if total_pair_dimensions else None,
        assigned_review_count=len(assignments), completed_review_count=len(reviews),
        missing_assignment_ids=missing, unresolved_output_ids=tuple(unresolved),
        fully_reviewed=not missing and not unresolved,
    )


def score_payload(payload: Mapping[str, Any]) -> BlindReviewScorecard:
    return score_blind_reviews(
        assignments=[ReviewAssignment.from_dict(item) for item in payload.get("assignments", ())],
        reviews=[AnalyticalReview.from_dict(item) for item in payload.get("reviews", ())],
    )
