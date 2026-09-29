from __future__ import annotations

import json

import pytest

from scripts import benchmark_blind_review
from validation.blind_analytical_review import (
    AnalyticalReview,
    BlindReviewPacket,
    ReviewAssignment,
    assign_reviews,
    blind_output_id,
    score_blind_reviews,
    score_payload,
)
from validation.intelligence_benchmark import BenchmarkContractError


DIMENSIONS = {
    "responsiveness": 4, "reasoning": 4, "materiality": 4,
    "counterarguments": 4, "uncertainty": 4, "usefulness": 4,
}


def _assignments():
    return assign_reviews(
        blind_output_ids=["opaque-output"], reviewer_ids=["reviewer-b", "reviewer-a"],
        rubric_version="analytical-v1",
    )


def _review(assignment, **overrides):
    data = {
        "assignment_id": assignment.assignment_id,
        "blind_output_id": assignment.blind_output_id,
        "reviewer_id": assignment.reviewer_id,
        "rubric_version": assignment.rubric_version,
        "scores": DIMENSIONS,
        "verdict": "pass",
        "rationale": "Responsive and decision-useful with explicit uncertainty.",
    }
    data.update(overrides)
    return AnalyticalReview.from_dict(data)


def test_blind_identifier_is_stable_and_secret_namespaced():
    first = blind_output_id("run-1", "a-long-blinding-secret")
    assert first == blind_output_id("run-1", "a-long-blinding-secret")
    assert first != blind_output_id("run-1", "another-long-secret")
    assert "run-1" not in first


def test_blind_packet_rejects_identity_metadata_recursively():
    with pytest.raises(BenchmarkContractError, match="forbidden field"):
        BlindReviewPacket.from_dict({
            "case_id": "case-1", "blind_output_id": "opaque", "question": "Why?",
            "analysis": {"answer": "Because", "metadata": {"model_id": "secret"}},
            "rubric_version": "v1",
        })


def test_blind_packet_accepts_review_material_without_identity():
    packet = BlindReviewPacket.from_dict({
        "case_id": "case-1", "blind_output_id": "opaque", "question": "Why?",
        "analysis": {"answer": "Because", "citations": ["source-1"]},
        "rubric_version": "v1",
    })
    assert packet.blind_output_id == "opaque"


def test_assignment_requires_two_distinct_reviewers():
    with pytest.raises(BenchmarkContractError, match="two reviews"):
        assign_reviews(blind_output_ids=["o"], reviewer_ids=["a", "b"], rubric_version="v", reviews_per_output=1)
    with pytest.raises(BenchmarkContractError, match="not enough"):
        assign_reviews(blind_output_ids=["o"], reviewer_ids=["a"], rubric_version="v")


def test_assignment_is_deterministic_and_balanced():
    assignments = assign_reviews(
        blind_output_ids=["b", "a"], reviewer_ids=["r3", "r1", "r2"],
        rubric_version="v1",
    )
    assert assignments == assign_reviews(
        blind_output_ids=["b", "a"], reviewer_ids=["r3", "r1", "r2"],
        rubric_version="v1",
    )
    assert len(assignments) == 4
    assert all(len({a.reviewer_id for a in assignments if a.blind_output_id == output}) == 2 for output in ("a", "b"))


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_every_rubric_score_is_bounded_integer(dimension):
    assignment = _assignments()[0]
    scores = dict(DIMENSIONS)
    scores[dimension] = 6
    with pytest.raises(BenchmarkContractError, match="integer from 1 to 5"):
        _review(assignment, scores=scores)


def test_review_requires_exact_rubric_dimensions_and_rationale():
    assignment = _assignments()[0]
    with pytest.raises(BenchmarkContractError, match="exactly"):
        _review(assignment, scores={"reasoning": 4})
    with pytest.raises(BenchmarkContractError, match="rationale"):
        _review(assignment, rationale="")


def test_complete_agreeing_reviews_produce_quality_and_agreement():
    assignments = _assignments()
    result = score_blind_reviews(
        assignments=assignments, reviews=[_review(item) for item in assignments],
    )
    assert result.analytical_quality == 0.8
    assert result.dimension_agreement_rate == 1.0
    assert result.mean_absolute_dimension_gap == 0.0
    assert result.fully_reviewed is True
    assert result.unresolved_output_ids == ()


def test_one_point_dimension_gap_still_counts_as_agreement():
    assignments = _assignments()
    scores = dict(DIMENSIONS)
    scores["reasoning"] = 3
    result = score_blind_reviews(
        assignments=assignments,
        reviews=[_review(assignments[0]), _review(assignments[1], scores=scores)],
    )
    assert result.dimension_agreement_rate == 1.0
    assert result.fully_reviewed is True


def test_verdict_disagreement_requires_adjudication():
    assignments = _assignments()
    result = score_blind_reviews(
        assignments=assignments,
        reviews=[_review(assignments[0]), _review(assignments[1], verdict="fail")],
    )
    assert result.outputs[0].verdict_agreement is False
    assert result.outputs[0].requires_adjudication is True
    assert result.fully_reviewed is False


def test_large_score_gap_requires_adjudication():
    assignments = _assignments()
    low = {key: 1 for key in DIMENSIONS}
    result = score_blind_reviews(
        assignments=assignments,
        reviews=[_review(assignments[0]), _review(assignments[1], scores=low)],
    )
    assert result.outputs[0].mean_absolute_dimension_gap == 3.0
    assert result.fully_reviewed is False


def test_missing_review_is_visible_and_incomplete():
    assignments = _assignments()
    result = score_blind_reviews(assignments=assignments, reviews=[_review(assignments[0])])
    assert len(result.missing_assignment_ids) == 1
    assert result.fully_reviewed is False


def test_review_cannot_impersonate_assigned_reviewer():
    assignments = _assignments()
    forged = _review(assignments[0], reviewer_id="someone-else")
    with pytest.raises(BenchmarkContractError, match="does not match"):
        score_blind_reviews(assignments=assignments, reviews=[forged])


def test_unknown_and_duplicate_assignment_reviews_fail_closed():
    assignments = _assignments()
    unknown = _review(ReviewAssignment("unknown", "opaque-output", "r", "analytical-v1"))
    with pytest.raises(BenchmarkContractError, match="unknown"):
        score_blind_reviews(assignments=assignments, reviews=[unknown])
    duplicated = _review(assignments[0])
    with pytest.raises(BenchmarkContractError, match="one review"):
        score_blind_reviews(assignments=assignments, reviews=[duplicated, duplicated])


def test_payload_and_cli_emit_machine_readable_incomplete_result(tmp_path, capsys):
    assignments = _assignments()
    payload = {
        "assignments": [asdict_assignment(item) for item in assignments],
        "reviews": [asdict_review(_review(assignments[0]))],
    }
    assert score_payload(payload).fully_reviewed is False
    path = tmp_path / "blind-review.json"
    path.write_text(json.dumps(payload))
    assert benchmark_blind_review.main([str(path), "--require-complete"]) == 2
    assert '"fully_reviewed": false' in capsys.readouterr().out


def asdict_assignment(item):
    return {
        "assignment_id": item.assignment_id, "blind_output_id": item.blind_output_id,
        "reviewer_id": item.reviewer_id, "rubric_version": item.rubric_version,
    }


def asdict_review(item):
    return {
        **asdict_assignment(item), "scores": dict(item.scores),
        "verdict": item.verdict.value, "rationale": item.rationale,
    }
