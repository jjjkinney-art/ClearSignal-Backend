from __future__ import annotations

import json

import pytest

from scripts import benchmark_factual_grade
from validation.factual_citation_grading import (
    CitationAdjudication,
    EntailmentLabel,
    ExpectedClaim,
    Materiality,
    ObservedClaim,
    grade_factual_citations,
    grade_payload,
)
from validation.intelligence_benchmark import BenchmarkContractError


def _expected(**overrides):
    values = dict(
        claim_id="revenue", metric="Revenue", value="100.0", unit="million",
        currency="USD", period="FY2025", scope="consolidated",
        source_id="sec-10k", materiality=Materiality.MATERIAL,
        absolute_tolerance="0",
    )
    values.update(overrides)
    return ExpectedClaim(**values)


def _observed(**overrides):
    values = dict(
        claim_id="revenue", text="Revenue was $100 million.", value="100.0",
        unit="million", currency="USD", period="FY2025",
        scope="consolidated", cited_source_id="sec-10k",
    )
    values.update(overrides)
    return ObservedClaim(**values)


def _adjudication(**overrides):
    values = dict(
        claim_id="revenue", source_id="sec-10k", document_exists=True,
        label=EntailmentLabel.SUPPORTS, reviewer="human:reviewer-1",
        rationale="The cited table states the same value and period.",
    )
    values.update(overrides)
    return CitationAdjudication(**values)


def _grade(expected=None, observed=None, adjudication=None):
    return grade_factual_citations(
        expected_claims=[expected or _expected()],
        observed_claims=[observed or _observed()],
        adjudications=[adjudication or _adjudication()],
    )


def test_correct_material_claim_scores_one():
    result = _grade()
    assert result.material_numerical_accuracy == 1.0
    assert result.claim_source_binding == 1.0
    assert result.stop_ship_count == 0
    assert result.fully_adjudicated is True


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("value", "-100.0", "value_mismatch"),
        ("unit", "billion", "unit_mismatch"),
        ("currency", "EUR", "currency_mismatch"),
        ("period", "FY2024", "period_mismatch"),
        ("scope", "segment", "scope_mismatch"),
    ],
)
def test_each_numerical_dimension_is_scored_separately(field, value, code):
    result = _grade(observed=_observed(**{field: value}))
    assert result.material_numerical_accuracy == 0.0
    assert any(f.code == code and f.stop_ship for f in result.findings)


def test_absolute_tolerance_is_explicit_not_implicit():
    result = _grade(
        expected=_expected(absolute_tolerance="0.1"),
        observed=_observed(value="100.05"),
    )
    assert result.material_numerical_accuracy == 1.0


def test_missing_material_claim_is_stop_ship():
    result = grade_factual_citations(
        expected_claims=[_expected()], observed_claims=[], adjudications=[]
    )
    assert result.material_numerical_accuracy == 0.0
    assert result.fully_adjudicated is False
    assert any(f.code == "missing_expected_claim" and f.stop_ship for f in result.findings)


def test_missing_citation_fails_binding():
    result = _grade(observed=_observed(cited_source_id=None))
    assert result.claim_source_binding == 0.0
    assert any(f.code == "missing_citation" for f in result.findings)


def test_nonexistent_document_counts_as_fabricated_material_source():
    result = _grade(adjudication=_adjudication(document_exists=False))
    assert result.fabricated_material_sources == 1
    assert result.claim_source_binding == 0.0
    assert any(f.code == "fabricated_or_missing_source" for f in result.findings)


def test_wrong_document_does_not_satisfy_binding_even_if_it_supports_claim():
    result = _grade(
        observed=_observed(cited_source_id="wrong-source"),
        adjudication=_adjudication(source_id="wrong-source"),
    )
    assert result.claim_source_binding == 0.0
    assert any(f.code == "wrong_source_binding" for f in result.findings)


@pytest.mark.parametrize(
    "label",
    [EntailmentLabel.PARTIAL, EntailmentLabel.CONTRADICTS, EntailmentLabel.NOT_FOUND],
)
def test_non_supporting_entailment_fails_binding(label):
    result = _grade(adjudication=_adjudication(label=label))
    assert result.claim_source_binding == 0.0
    assert any(f.code == "citation_does_not_support_claim" for f in result.findings)


def test_pending_entailment_is_not_counted_as_correct():
    result = _grade(adjudication=_adjudication(label=EntailmentLabel.PENDING))
    assert result.claim_source_binding == 0.0
    assert result.pending_material_adjudications == 1
    assert result.fully_adjudicated is False


def test_absent_adjudication_remains_unverified():
    result = grade_factual_citations(
        expected_claims=[_expected()], observed_claims=[_observed()], adjudications=[]
    )
    assert result.claim_source_binding == 0.0
    assert result.pending_material_adjudications == 1
    assert any(f.code == "citation_not_adjudicated" for f in result.findings)


def test_supporting_claim_failure_does_not_become_material_stop_ship():
    result = _grade(
        expected=_expected(materiality=Materiality.SUPPORTING),
        observed=_observed(value="0"),
    )
    assert result.material_claim_count == 0
    assert result.material_numerical_accuracy is None
    assert result.stop_ship_count == 0


def test_unexpected_claim_is_reported_but_not_silently_scored():
    result = grade_factual_citations(
        expected_claims=[], observed_claims=[_observed()], adjudications=[]
    )
    assert result.material_numerical_accuracy is None
    assert result.findings[0].code == "unexpected_unscored_claim"


def test_duplicate_ids_fail_closed():
    with pytest.raises(BenchmarkContractError, match="unique"):
        grade_factual_citations(
            expected_claims=[_expected(), _expected()],
            observed_claims=[_observed()], adjudications=[_adjudication()],
        )


def test_adjudication_requires_identified_reviewer():
    with pytest.raises(BenchmarkContractError, match="reviewer"):
        CitationAdjudication.from_dict({
            "claim_id": "x", "source_id": "s", "document_exists": True,
            "label": "supports", "reviewer": "",
        })


def _payload(label="supports"):
    return {
        "expected_claims": [{
            "claim_id": "revenue", "metric": "Revenue", "value": "100",
            "unit": "million", "currency": "USD", "period": "FY2025",
            "scope": "consolidated", "source_id": "sec-10k",
            "materiality": "material",
        }],
        "observed_claims": [{
            "claim_id": "revenue", "text": "Revenue was $100 million.",
            "value": "100", "unit": "million", "currency": "USD",
            "period": "FY2025", "scope": "consolidated",
            "cited_source_id": "sec-10k",
        }],
        "adjudications": [{
            "claim_id": "revenue", "source_id": "sec-10k",
            "document_exists": True, "label": label,
            "reviewer": "human:reviewer-1", "rationale": "verified",
        }],
    }


def test_payload_adapter_and_scorecard_json_are_stable():
    scorecard = grade_payload(_payload())
    encoded = json.dumps(scorecard.to_dict(), sort_keys=True)
    assert '"material_numerical_accuracy": 1.0' in encoded
    assert '"entailment_label": "supports"' in encoded


def test_cli_passes_complete_correct_case(tmp_path, capsys):
    path = tmp_path / "grade.json"
    path.write_text(json.dumps(_payload()))
    assert benchmark_factual_grade.main([str(path), "--require-complete"]) == 0
    assert '"fully_adjudicated": true' in capsys.readouterr().out


def test_cli_rejects_pending_material_review(tmp_path):
    path = tmp_path / "grade.json"
    path.write_text(json.dumps(_payload(label="pending")))
    assert benchmark_factual_grade.main([str(path), "--require-complete"]) == 2

