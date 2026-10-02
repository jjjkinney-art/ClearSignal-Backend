"""Tests for the fail-closed thesis-impact evidence gate."""

from app.services.thesis_impact_evidence import gate_thesis_impact_evidence


PRIOR = "2026-09-27T12:00:00+00:00"


def _evidence(**overrides):
    value = {
        "evidence_id": "E1",
        "ticker": "AAPL",
        "url": "https://www.sec.gov/example",
        "filed_at": "2026-10-01T12:00:00Z",
        "materially_related": True,
        "admitted": True,
        "availability": "available",
        "supersession": "current",
        "freshness": "current",
        "material_conflict": False,
    }
    value.update(overrides)
    return value


def test_gate_admits_only_new_attributable_related_evidence():
    result = gate_thesis_impact_evidence(
        prior_created_at=PRIOR,
        target_ticker="aapl",
        evidence=[_evidence()],
        evidence_integrity={
            "overall_status": "admitted",
            "has_material_conflict": False,
        },
    )

    assert result["status"] == "ready"
    assert result["ready_for_comparison"] is True
    assert result["direction"] == "unverified"
    assert result["eligible_evidence"] == [{
        "evidence_id": "E1",
        "url": "https://www.sec.gov/example",
        "source_time_field": "filed_at",
        "source_time": "2026-10-01T12:00:00+00:00",
    }]


def test_retrieval_time_does_not_make_old_evidence_new():
    result = gate_thesis_impact_evidence(
        prior_created_at=PRIOR,
        target_ticker="AAPL",
        evidence=[_evidence(
            filed_at="2026-09-01T12:00:00Z",
            retrieved_at="2026-10-02T12:00:00Z",
        )],
    )

    assert result["status"] == "insufficient_new_evidence"
    assert result["ready_for_comparison"] is False
    assert result["blocked_counts"] == {"not_newer": 1}


def test_gate_rejects_wrong_ticker_unrelated_unattributed_and_unadmitted():
    result = gate_thesis_impact_evidence(
        prior_created_at=PRIOR,
        target_ticker="AAPL",
        evidence=[
            _evidence(ticker="MSFT"),
            _evidence(evidence_id="E2", materially_related=False),
            _evidence(evidence_id="", id="", source_id=""),
            _evidence(evidence_id="E4", admitted=False),
        ],
    )

    assert result["status"] == "insufficient_new_evidence"
    assert result["eligible_evidence"] == []
    assert result["blocked_counts"] == {
        "ticker_mismatch": 1,
        "not_materially_related": 1,
        "unattributed": 1,
        "not_admitted": 1,
    }


def test_gate_fails_closed_for_conflict_supersession_unavailability_and_future():
    for evidence, reason in (
        (_evidence(material_conflict=True), "material_conflict"),
        (_evidence(supersession="superseded"), "superseded"),
        (_evidence(availability="unavailable"), "unavailable"),
        (_evidence(freshness="future"), "future"),
    ):
        result = gate_thesis_impact_evidence(
            prior_created_at=PRIOR,
            target_ticker="AAPL",
            evidence=[evidence],
        )
        expected_status = (
            "conflicting_evidence"
            if reason == "material_conflict"
            else "insufficient_new_evidence"
        )
        assert result["status"] == expected_status
        assert result["ready_for_comparison"] is False
        assert result["blocked_counts"][reason] == 1


def test_overall_integrity_conflict_blocks_otherwise_eligible_evidence():
    result = gate_thesis_impact_evidence(
        prior_created_at=PRIOR,
        target_ticker="AAPL",
        evidence=[_evidence()],
        evidence_integrity={
            "overall_status": "conflicting",
            "has_material_conflict": True,
        },
    )

    assert result == {
        "gate_version": 1,
        "ready_for_comparison": False,
        "direction": "unverified",
        "eligible_evidence": [],
        "status": "conflicting_evidence",
    }


def test_invalid_prior_record_fails_closed():
    result = gate_thesis_impact_evidence(
        prior_created_at="not-a-date",
        target_ticker="AAPL",
        evidence=[_evidence()],
    )
    assert result["status"] == "invalid_prior_record"
    assert result["ready_for_comparison"] is False
