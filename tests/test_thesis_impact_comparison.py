"""End-to-end unit tests for audited thesis-impact orchestration."""

from types import SimpleNamespace
import pytest

from app.services.thesis_impact_comparison import evaluate_selected_thesis_impact


def _context():
    return {
        "applied": True,
        "ticker": "AAPL",
        "created_at": "2026-09-27T12:00:00+00:00",
        "artifact": {
            "thesis": {
                "direct_answer": "Services demand was the central growth driver.",
            }
        },
    }


def _thesis(answer="The thesis strengthened because services demand accelerated. [E1]"):
    return SimpleNamespace(
        direct_answer=answer,
        conclusion=answer,
        thesis_trend="strengthening",
        what_changed=[],
        change_drivers=[],
    )


def _evidence(**overrides):
    value = {
        "ticker": "AAPL",
        "title": "Quarterly filing shows services demand acceleration",
        "summary": "Services demand and services revenue accelerated.",
        "timestamp": "2026-10-01T12:00:00Z",
        "source": "SEC EDGAR",
        "url": "https://www.sec.gov/example",
        "availability": "available",
        "supersession": "current",
        "freshness": "current",
    }
    value.update(overrides)
    return SimpleNamespace(**value)


def test_source_title_cannot_bind_an_uncited_directional_conclusion():
    thesis = _thesis("The thesis strengthened because services demand accelerated.")
    audit = evaluate_selected_thesis_impact(
        thesis=thesis, context=_context(), evidence=[_evidence()],
    )
    assert audit["evidence_gate"]["status"] == "ready"
    assert audit["status"] != "verified_change"
    assert audit["evidence_bound_result"]["reason"] == "missing_change_claims"
    assert "cannot verify" in thesis.direct_answer


def test_citation_to_old_source_cannot_borrow_new_eligible_source():
    thesis = _thesis("The thesis strengthened because services demand accelerated. [E1]")
    audit = evaluate_selected_thesis_impact(
        thesis=thesis, context=_context(),
        evidence=[_evidence(timestamp="2026-09-01"), _evidence()],
    )
    assert audit["evidence_gate"]["status"] == "ready"
    assert audit["status"] != "verified_change"
    assert audit["evidence_bound_result"]["reason"] == "unadmitted_evidence_reference"


@pytest.mark.parametrize("answer", [
    "The thesis strengthened because services demand accelerated. [E1] Margins fell.",
    "The thesis strengthened because services demand accelerated. [E99]",
    "The thesis weakened because services demand declined. [E1]",
])
def test_partial_unknown_or_contradictory_comparison_cannot_be_verified(answer):
    audit = evaluate_selected_thesis_impact(
        thesis=_thesis(answer), context=_context(), evidence=[_evidence()],
    )
    assert audit["evidence_gate"]["status"] == "ready"
    assert audit["status"] != "verified_change"


def test_numeric_citations_bind_actual_conclusion_to_canonical_identity():
    answer = "The thesis strengthened because services demand accelerated. [1]"
    audit = evaluate_selected_thesis_impact(
        thesis=_thesis(answer), context=_context(), evidence=[_evidence()],
    )
    assert audit["status"] == "verified_change"
    assert audit["evidence_bound_result"]["claims"] == [{"text": answer, "evidence_ids": ["E1"]}]


@pytest.mark.parametrize("overrides,reason", [
    ({"ticker": "MSFT"}, "ticker_mismatch"),
    ({"ticker": ""}, "ticker_mismatch"),
    ({"freshness": "stale"}, "stale"),
    ({"freshness_status": "stale"}, "stale"),
    ({"availability_status": "unavailable"}, "unavailable"),
    ({"freshness_status": "superseded"}, "superseded"),
])
def test_comparison_preserves_issuer_and_blocks_stale_metadata(overrides, reason):
    thesis = _thesis()
    audit = evaluate_selected_thesis_impact(
        thesis=thesis, context=_context(), evidence=[_evidence(**overrides)],
    )
    assert audit["status"] == "insufficient_new_evidence"
    assert audit["direction"] == "unclear"
    assert audit["evidence_gate"]["blocked_counts"][reason] == 1
    assert thesis.thesis_trend == "unclear"
    assert "cannot verify" in thesis.direct_answer


@pytest.mark.parametrize("field", ["verified_claims", "risk_disclosures", "calculated_claims"])
def test_comparison_uses_unambiguous_producer_claim_scope(field):
    evidence = _evidence(ticker="", **{field: [{"ticker": "AAPL"}]})
    audit = evaluate_selected_thesis_impact(
        thesis=_thesis(), context=_context(), evidence=[evidence],
    )
    assert audit["status"] == "verified_change"
    evidence = _evidence(ticker="MSFT", **{field: [{"ticker": "AAPL"}]})
    audit = evaluate_selected_thesis_impact(
        thesis=_thesis(), context=_context(), evidence=[evidence],
    )
    assert audit["status"] == "insufficient_new_evidence"


def test_admission_removal_preserves_the_surviving_reference_id():
    from app.services.evidence_references import admit_evidence
    blocked = _evidence(title="Removed record", freshness_status="unavailable")
    surviving = _evidence()
    admitted, refs, integrity = admit_evidence([blocked, surviving])
    assert len(admitted) == 1
    audit = evaluate_selected_thesis_impact(
        thesis=_thesis("The thesis strengthened because services demand accelerated. [E2]"), context=_context(), evidence=admitted,
        references=refs, evidence_integrity=integrity,
    )
    assert audit["status"] == "verified_change"
    assert audit["evidence_changes"][0]["evidence_id"] == "E2"
    assert audit["evidence_bound_result"]["claims"][0]["evidence_ids"] == ["E2"]


def test_comparison_respects_computed_freshness_from_admission():
    from app.services.evidence_references import admit_evidence
    evidence = _evidence(source="Reuters", source_type="news",
                         timestamp="2026-10-01T12:00:00Z")
    admitted, refs, integrity = admit_evidence([evidence], evaluated_at="2026-11-01T12:00:00Z")
    assert len(admitted) == 1  # Still inspectable supporting context.
    assert refs[0]["freshness_status"] == "stale"
    audit = evaluate_selected_thesis_impact(
        thesis=_thesis(), context=_context(), evidence=admitted,
        references=refs, evidence_integrity=integrity,
    )
    assert audit["status"] == "insufficient_new_evidence"
    assert audit["evidence_gate"]["blocked_counts"] == {"stale": 1}


def test_missing_or_mismatched_canonical_reference_cannot_support_change():
    from app.services.evidence_references import build_evidence_references
    evidence = _evidence()
    refs = build_evidence_references([evidence])
    refs[0]["url"] = "https://www.sec.gov/different-document"
    for references in ([], refs):
        audit = evaluate_selected_thesis_impact(
            thesis=_thesis(), context=_context(), evidence=[evidence], references=references,
        )
        assert audit["status"] == "insufficient_new_evidence"
        assert audit["evidence_gate"]["blocked_counts"] == {"unattributed": 1}


def test_orchestrator_accepts_fully_bound_directional_change():
    thesis = _thesis()
    audit = evaluate_selected_thesis_impact(
        thesis=thesis,
        context=_context(),
        evidence=[_evidence()],
        evidence_integrity={
            "overall_status": "admitted",
            "has_material_conflict": False,
        },
    )

    assert audit["comparison_version"] == 3
    assert audit["status"] == "verified_change"
    assert audit["direction"] == "strengthened"
    assert audit["evidence_gate"]["status"] == "ready"
    assert audit["evidence_bound_result"]["status"] == "supported"
    assert audit["evidence_bound_result"]["claims"][0]["evidence_ids"] == ["E1"]
    assert audit["evidence_changes"][0]["url"] == "https://www.sec.gov/example"
    assert thesis.thesis_trend == "strengthening"
    assert thesis.what_changed == [
        "The thesis strengthened because services demand accelerated. [E1]"
    ]


def test_orchestrator_rejects_old_evidence_and_corrects_model_direction():
    thesis = _thesis()
    audit = evaluate_selected_thesis_impact(
        thesis=thesis,
        context=_context(),
        evidence=[_evidence(timestamp="2026-09-01T12:00:00Z")],
    )

    assert audit["status"] == "insufficient_new_evidence"
    assert audit["direction"] == "unclear"
    assert audit["evidence_gate"]["blocked_counts"] == {"not_newer": 1}
    assert audit["evidence_bound_result"]["direction"] == "unverified"
    assert "cannot verify" in thesis.direct_answer
    assert thesis.thesis_trend == "unclear"
    assert thesis.change_drivers == []


def test_orchestrator_rejects_new_but_unrelated_evidence():
    thesis = _thesis()
    audit = evaluate_selected_thesis_impact(
        thesis=thesis,
        context=_context(),
        evidence=[_evidence(
            title="Board appoints a new director",
            summary="The governance committee added an independent member.",
        )],
    )

    assert audit["status"] == "insufficient_new_evidence"
    assert audit["evidence_gate"]["blocked_counts"] == {
        "not_materially_related": 1
    }


def test_orchestrator_fails_closed_for_integrity_conflict():
    thesis = _thesis()
    audit = evaluate_selected_thesis_impact(
        thesis=thesis,
        context=_context(),
        evidence=[_evidence()],
        evidence_integrity={
            "overall_status": "conflicting",
            "has_material_conflict": True,
        },
    )

    assert audit["status"] == "conflicting_evidence"
    assert audit["direction"] == "unclear"
    assert audit["evidence_bound_result"]["status"] == "unverified"
    assert "conflicting" in thesis.direct_answer


def test_unchanged_result_still_requires_new_bound_evidence():
    thesis = _thesis("The thesis is unchanged as services demand remains stable. [E1]")
    thesis.thesis_trend = "stable"
    audit = evaluate_selected_thesis_impact(
        thesis=thesis,
        context=_context(),
        evidence=[_evidence(
            title="Quarterly filing shows stable services demand",
            summary="Services demand remained stable in the quarter.",
        )],
    )

    assert audit["status"] == "no_directional_change"
    assert audit["direction"] == "unchanged"
    assert audit["evidence_bound_result"]["status"] == "supported"
    assert thesis.thesis_trend == "stable"
