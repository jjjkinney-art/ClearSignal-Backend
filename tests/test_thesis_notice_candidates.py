"""Zero-side-effect acceptance tests for thesis notice candidates."""

from app.services.thesis_notice_candidates import (
    build_thesis_notice_candidates,
    evaluate_thesis_notice_candidate,
)


def _artifact():
    return {
        "status": "available",
        "historical_only": True,
        "requires_fresh_evidence": True,
        "ticker": "AAPL",
        "thesis": {
            "direct_answer": "Services retention and installed base support durable growth.",
            "key_risks": ["App Store regulatory pressure"],
        },
    }


def _evidence(**changes):
    value = {
        "id": "E9",
        "ticker": "AAPL",
        "title": "Quarterly filing reports services growth",
        "summary": "Services retention and installed base remained durable.",
        "published_at": "2026-10-01T00:00:00Z",
        "freshness_status": "current",
        "material_conflict": False,
    }
    value.update(changes)
    return value


def test_requires_explicit_owner_selection():
    result = evaluate_thesis_notice_candidate(
        artifact=_artifact(), artifact_recorded_at="2026-09-27T00:00:00Z",
        evidence=_evidence(), owner_selected=False,
    )
    assert result["eligible"] is False
    assert result["delivery_enabled"] is False
    assert result["reason"] == "owner_selection_required"


def test_eligible_candidate_is_new_admitted_related_and_never_delivered():
    result = evaluate_thesis_notice_candidate(
        artifact=_artifact(), artifact_recorded_at="2026-09-27T00:00:00Z",
        evidence=_evidence(), owner_selected=True,
    )
    assert result == {
        "candidate_version": 1,
        "eligible": True,
        "delivery_enabled": False,
        "reason": "new_admitted_related_evidence",
        "ticker": "AAPL",
        "evidence_id": "E9",
        "matched_terms": ["base", "durable", "installed", "retention", "services"],
    }


def test_fails_closed_for_old_conflicting_or_wrong_ticker_evidence():
    cases = [
        (_evidence(published_at="2026-09-01"), "not_newer_than_thesis"),
        (_evidence(freshness_status="conflicting"), "evidence_not_admitted"),
        (_evidence(material_conflict=True), "evidence_not_admitted"),
        (_evidence(ticker="MSFT"), "ticker_mismatch"),
    ]
    for evidence, reason in cases:
        result = evaluate_thesis_notice_candidate(
            artifact=_artifact(), artifact_recorded_at="2026-09-27T00:00:00Z",
            evidence=evidence, owner_selected=True,
        )
        assert result["eligible"] is False
        assert result["delivery_enabled"] is False
        assert result["reason"] == reason


def test_unrelated_and_malformed_evidence_fail_closed():
    unrelated = _evidence(
        title="Board appoints director", summary="Governance committee update."
    )
    malformed = _evidence(published_at="not-a-date")
    assert evaluate_thesis_notice_candidate(
        artifact=_artifact(), artifact_recorded_at="2026-09-27",
        evidence=unrelated, owner_selected=True,
    )["reason"] == "not_materially_related"
    assert evaluate_thesis_notice_candidate(
        artifact=_artifact(), artifact_recorded_at="2026-09-27",
        evidence=malformed, owner_selected=True,
    )["reason"] == "timestamp_unavailable"


def test_batch_returns_only_eligible_candidates():
    candidates = build_thesis_notice_candidates(
        artifact=_artifact(), artifact_recorded_at="2026-09-27",
        owner_selected=True,
        evidence_items=[
            _evidence(),
            _evidence(id="E10", ticker="MSFT"),
            _evidence(id="E11", freshness_status="superseded"),
        ],
    )
    assert [candidate["evidence_id"] for candidate in candidates] == ["E9"]
    assert all(candidate["delivery_enabled"] is False for candidate in candidates)
