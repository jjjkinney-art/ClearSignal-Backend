"""Evidence gates for selected historical thesis comparisons."""

from types import SimpleNamespace

from app.services.research_comparison import apply_evidence_gated_comparison


def _context(**overrides):
    context = {
        "applied": True,
        "created_at": "2026-08-01T12:00:00+00:00",
        "historical_thesis": {
            "direct_answer": "Cloud demand was the main growth driver.",
            "confidence_score": 0.60,
        },
    }
    context.update(overrides)
    return context


def _thesis(answer="The thesis has strengthened because cloud demand accelerated."):
    return SimpleNamespace(
        direct_answer=answer,
        conclusion=answer,
        confidence_score=0.68,
        what_changed=[],
        thesis_trend="unclear",
        change_drivers=[],
    )


def _evidence(*, title, summary, timestamp, source="SEC EDGAR"):
    return SimpleNamespace(
        title=title,
        summary=summary,
        timestamp=timestamp,
        source=source,
        url="https://www.sec.gov/filing.htm",
        document_type="10-Q",
        page=7,
        section=None,
    )


def test_rejects_directional_change_without_evidence_newer_than_prior_record():
    thesis = _thesis()
    result = apply_evidence_gated_comparison(
        thesis,
        _context(),
        [_evidence(
            title="Annual filing",
            summary="Cloud demand accelerated.",
            timestamp="2026-07-30",
        )],
    )
    assert result["status"] == "insufficient_new_evidence"
    assert result["direction"] == "unclear"
    assert result["claimed_direction_rejected"] == "strengthened"
    assert result["confidence_delta"] == 0.08
    assert "cannot verify" in thesis.direct_answer
    assert thesis.thesis_trend == "unclear"
    assert thesis.change_drivers == []
    assert thesis.what_changed == [
        "No attributable, materially related evidence newer than the selected prior record was retrieved."
    ]


def test_rejects_new_but_unrelated_evidence():
    thesis = _thesis()
    result = apply_evidence_gated_comparison(
        thesis,
        _context(),
        [_evidence(
            title="Board appoints a new director",
            summary="The governance committee added one independent member.",
            timestamp="2026-08-10",
        )],
    )
    assert result["status"] == "insufficient_new_evidence"
    assert result["evidence_changes"] == []


def test_allows_direction_only_with_new_related_attributable_evidence():
    thesis = _thesis()
    result = apply_evidence_gated_comparison(
        thesis,
        _context(),
        [_evidence(
            title="Quarterly filing shows cloud demand acceleration",
            summary="Cloud demand and cloud revenue growth accelerated during the quarter.",
            timestamp="2026-08-10",
        )],
    )
    assert result["status"] == "verified_change"
    assert result["direction"] == "strengthened"
    assert result["evidence_changes"] == [{
        "title": "Quarterly filing shows cloud demand acceleration",
        "source": "SEC EDGAR",
        "published_at": "2026-08-10",
        "matched_terms": ["accelerated", "cloud", "demand"],
        "url": "https://www.sec.gov/filing.htm",
        "document_type": "10-Q",
        "page": 7,
        "section": None,
    }]
    assert thesis.thesis_trend == "strengthening"
    assert thesis.what_changed == [
        "Quarterly filing shows cloud demand acceleration — SEC EDGAR (2026-08-10)"
    ]
    delta = result["longitudinal_delta"]
    assert delta["prior"]["conclusion"] == "Cloud demand was the main growth driver."
    assert delta["current"]["conclusion"] == thesis.direct_answer
    assert delta["change"]["direction"] == "strengthened"
    assert delta["confidence_movement"] == {
        "prior": 0.6,
        "current": 0.68,
        "delta": 0.08,
        "direction": "increased",
        "evidentiary_status": "context_only",
    }
    assert delta["supporting_evidence"][0]["url"].startswith("https://www.sec.gov/")


def test_confidence_change_alone_never_proves_thesis_change():
    thesis = _thesis("The current analysis retains the prior thesis.")
    thesis.confidence_score = 0.95
    result = apply_evidence_gated_comparison(thesis, _context(), [])
    assert result["status"] == "no_directional_change"
    assert result["direction"] == "unchanged"
    assert result["confidence_delta"] == 0.35
    assert result["evidence_changes"] == []
    assert result["longitudinal_delta"]["confidence_movement"]["direction"] == "increased"
    assert result["longitudinal_delta"]["confidence_movement"]["evidentiary_status"] == "context_only"


def test_malformed_historical_timestamp_fails_closed():
    thesis = _thesis()
    result = apply_evidence_gated_comparison(
        thesis, _context(created_at="not-a-date"), []
    )
    assert result["status"] == "unavailable"
    assert result["direction"] == "unclear"
    assert result["longitudinal_delta"]["change"]["status"] == "unavailable"


def test_structured_trend_is_evidence_gated_when_conclusion_omits_direction_words():
    thesis = _thesis("Cloud demand accelerated in the current quarter.")
    thesis.thesis_trend = "strengthening"
    result = apply_evidence_gated_comparison(thesis, _context(), [])

    assert result["status"] == "insufficient_new_evidence"
    assert result["claimed_direction_rejected"] == "strengthened"


def test_current_conclusion_falls_back_to_conclusion_field_in_delta():
    thesis = _thesis("Current evidence retains the prior view.")
    thesis.direct_answer = ""
    result = apply_evidence_gated_comparison(thesis, _context(), [])

    assert result["current_conclusion"] == thesis.conclusion
    assert result["longitudinal_delta"]["current"]["conclusion"] == thesis.conclusion
