"""End-to-end unit tests for audited thesis-impact orchestration."""

from types import SimpleNamespace

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


def _thesis(answer="The thesis strengthened because services demand accelerated."):
    return SimpleNamespace(
        direct_answer=answer,
        conclusion=answer,
        thesis_trend="strengthening",
        what_changed=[],
        change_drivers=[],
    )


def _evidence(**overrides):
    value = {
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
        "Quarterly filing shows services demand acceleration — SEC EDGAR"
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
    thesis = _thesis("The thesis is unchanged as services demand remains stable.")
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
