"""Tests for evidence-bound historical thesis-impact results."""

from app.services.thesis_impact_result import (
    MAX_CLAIM_CHARS,
    MAX_RATIONALE_CHARS,
    build_thesis_impact_result,
)


def _gate():
    return {
        "status": "ready",
        "ready_for_comparison": True,
        "direction": "unverified",
        "eligible_evidence": [
            {
                "evidence_id": "E1",
                "url": "https://www.sec.gov/e1",
                "source_time_field": "filed_at",
                "source_time": "2026-10-01T12:00:00+00:00",
            },
            {
                "evidence_id": "E2",
                "url": "https://www.sec.gov/e2",
                "source_time_field": "published_at",
                "source_time": "2026-10-02T12:00:00+00:00",
            },
        ],
    }


def test_supported_result_binds_every_claim_to_gate_evidence():
    result = build_thesis_impact_result(
        gate=_gate(),
        proposed_direction="stronger",
        rationale="The newer evidence supports the prior operating assumption.",
        claims=[
            {
                "text": "Services growth remained above the saved threshold.",
                "evidence_ids": ["E1"],
            },
            {
                "text": "Management raised the related outlook.",
                "evidence_ids": ["E2", "E1"],
            },
        ],
    )

    assert result["status"] == "supported"
    assert result["direction"] == "stronger"
    assert result["reason"] == "evidence_bound_change"
    assert result["claims"][0]["evidence_ids"] == ["E1"]
    assert [item["evidence_id"] for item in result["evidence_references"]] == [
        "E1",
        "E2",
    ]


def test_unready_gate_forces_unverified_direction():
    result = build_thesis_impact_result(
        gate={
            "status": "insufficient_new_evidence",
            "ready_for_comparison": False,
            "eligible_evidence": [],
        },
        proposed_direction="stronger",
        rationale="Unsupported",
        claims=[{"text": "Unsupported", "evidence_ids": ["E1"]}],
    )

    assert result == {
        "result_version": 1,
        "status": "unverified",
        "direction": "unverified",
        "reason": "insufficient_new_evidence",
        "gate_status": "insufficient_new_evidence",
        "claims": [],
        "evidence_references": [],
    }


def test_unadmitted_evidence_reference_forces_unverified():
    result = build_thesis_impact_result(
        gate=_gate(),
        proposed_direction="weaker",
        rationale="A claim cites evidence the gate did not admit.",
        claims=[{"text": "Unsupported claim", "evidence_ids": ["E99"]}],
    )

    assert result["status"] == "unverified"
    assert result["direction"] == "unverified"
    assert result["reason"] == "unadmitted_evidence_reference"
    assert result["claims"] == []


def test_empty_or_uncited_claims_force_unverified():
    for claims, reason in (
        ([], "missing_change_claims"),
        ([{"text": "", "evidence_ids": ["E1"]}], "malformed_change_claim"),
        ([{"text": "Claim", "evidence_ids": []}], "unsupported_change_claim"),
    ):
        result = build_thesis_impact_result(
            gate=_gate(),
            proposed_direction="unchanged",
            rationale="Rationale",
            claims=claims,
        )
        assert result["status"] == "unverified"
        assert result["reason"] == reason


def test_direction_and_text_are_bounded():
    unsupported = build_thesis_impact_result(
        gate=_gate(),
        proposed_direction="buy",
        rationale="Rationale",
        claims=[{"text": "Claim", "evidence_ids": ["E1"]}],
    )
    assert unsupported["direction"] == "unverified"
    assert unsupported["reason"] == "unsupported_direction"

    bounded = build_thesis_impact_result(
        gate=_gate(),
        proposed_direction="unchanged",
        rationale="r" * (MAX_RATIONALE_CHARS + 100),
        claims=[{
            "text": "c" * (MAX_CLAIM_CHARS + 100),
            "evidence_ids": ["E1", "E1"],
        }],
    )
    assert bounded["status"] == "supported"
    assert len(bounded["rationale"]) == MAX_RATIONALE_CHARS
    assert len(bounded["claims"][0]["text"]) == MAX_CLAIM_CHARS
    assert bounded["claims"][0]["evidence_ids"] == ["E1"]
