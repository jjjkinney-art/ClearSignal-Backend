"""Historical-record freshness derived from the audited comparison gate."""

from app.services.research_memory_context import attach_historical_freshness


def test_newer_eligible_evidence_marks_historical_record_stale():
    metadata = {"applied": True, "status": "applied"}
    result = attach_historical_freshness(metadata, {
        "evidence_gate": {
            "status": "ready",
            "eligible_evidence": [{"evidence_id": "E1"}, {"evidence_id": "E2"}],
        },
    })

    assert result["historical_record_freshness"] == {
        "freshness_version": 1,
        "status": "stale",
        "reason_code": "newer_material_evidence",
        "newer_evidence_count": 2,
    }
    assert metadata == {"applied": True, "status": "applied"}


def test_absence_of_qualifying_new_evidence_does_not_claim_record_is_current():
    result = attach_historical_freshness(
        {"applied": True},
        {"evidence_gate": {
            "status": "insufficient_new_evidence",
            "eligible_evidence": [],
            "blocked_counts": {"not_newer": 2},
        }},
    )

    assert result["historical_record_freshness"]["status"] == "not_proven_stale"
    assert result["historical_record_freshness"]["reason_code"] == (
        "no_qualifying_newer_evidence"
    )


def test_newer_conflicting_evidence_marks_record_stale_but_global_conflict_is_unknown():
    newer_conflict = attach_historical_freshness(
        {"applied": True},
        {"evidence_gate": {
            "status": "conflicting_evidence",
            "eligible_evidence": [],
            "blocked_counts": {"material_conflict": 1},
        }},
    )
    assert newer_conflict["historical_record_freshness"] == {
        "freshness_version": 1,
        "status": "stale",
        "reason_code": "newer_conflicting_evidence",
        "newer_evidence_count": 1,
    }

    global_conflict = attach_historical_freshness(
        {"applied": True},
        {"evidence_gate": {
            "status": "conflicting_evidence",
            "eligible_evidence": [],
        }},
    )
    assert global_conflict["historical_record_freshness"]["status"] == "unknown"
    assert global_conflict["historical_record_freshness"]["reason_code"] == (
        "current_evidence_conflict"
    )


def test_unselected_memory_does_not_gain_freshness_metadata():
    metadata = {"applied": False, "status": "not_selected"}
    assert attach_historical_freshness(metadata, None) == metadata
