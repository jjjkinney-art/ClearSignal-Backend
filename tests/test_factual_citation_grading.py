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


@pytest.mark.parametrize("bad", ["false", "true", "0", "", 0, 1, None, [], {}])
def test_document_existence_cannot_be_coerced_into_review_evidence(bad):
    payload = _payload()
    payload["adjudications"][0]["document_exists"] = bad
    with pytest.raises(BenchmarkContractError, match="document_exists requires a boolean"):
        grade_payload(payload)
    with pytest.raises(BenchmarkContractError, match="document_exists requires a boolean"):
        _adjudication(document_exists=bad)


def test_missing_existence_review_is_invalid_not_a_completed_review():
    payload = _payload()
    del payload["adjudications"][0]["document_exists"]
    with pytest.raises(BenchmarkContractError, match="document_exists requires a boolean"):
        grade_payload(payload)


@pytest.mark.parametrize("bad", [None, False, 0, 123, [], {}, "", "   "])
def test_reviewer_must_be_an_explicit_nonempty_identity(bad):
    payload = _payload()
    payload["adjudications"][0]["reviewer"] = bad
    with pytest.raises(BenchmarkContractError, match="reviewer identity"):
        grade_payload(payload)
    with pytest.raises(BenchmarkContractError, match="reviewer identity"):
        _adjudication(reviewer=bad)


@pytest.mark.parametrize("bad", ["NaN", "sNaN", "Infinity", "-Infinity", float("nan"), float("inf")])
@pytest.mark.parametrize("target", ["expected", "observed", "tolerance"])
def test_nonfinite_numbers_cannot_pass_or_crash_scoring(target, bad):
    payload = _payload()
    if target == "observed":
        payload["observed_claims"][0]["value"] = bad
        direct = lambda: _observed(value=bad)
    else:
        field = "absolute_tolerance" if target == "tolerance" else "value"
        payload["expected_claims"][0][field] = bad
        direct = lambda: _expected(**{field: bad})
    with pytest.raises(BenchmarkContractError, match="finite decimal"):
        grade_payload(payload)
    with pytest.raises(BenchmarkContractError, match="finite decimal"):
        direct()


def test_finite_explicit_tolerance_and_negative_values_remain_supported():
    payload = _payload()
    payload["expected_claims"][0].update(value="-100", absolute_tolerance="0.1")
    payload["observed_claims"][0]["value"] = "-100.05"
    assert grade_payload(payload).material_numerical_accuracy == 1.0
    payload["observed_claims"][0]["value"] = "-100.2"
    assert grade_payload(payload).material_numerical_accuracy == 0.0


def test_negative_tolerance_rejected_in_both_interfaces():
    payload = _payload()
    payload["expected_claims"][0]["absolute_tolerance"] = "-0.1"
    with pytest.raises(BenchmarkContractError, match="cannot be negative"):
        grade_payload(payload)
    with pytest.raises(BenchmarkContractError, match="cannot be negative"):
        _expected(absolute_tolerance="-0.1")


def test_genuine_false_existence_remains_a_fabricated_source_stop_ship():
    payload = _payload()
    payload["adjudications"][0]["document_exists"] = False
    result = grade_payload(payload)
    assert result.fabricated_material_sources == 1
    assert result.claim_source_binding == 0.0
    assert result.stop_ship_count == 1


@pytest.mark.parametrize("field,bad", [("document_exists", "false"), ("reviewer", None)])
def test_cli_rejects_invalid_adjudication_without_emitting_a_scorecard(tmp_path, capsys, field, bad):
    payload = _payload()
    payload["adjudications"][0][field] = bad
    path = tmp_path / "invalid-review.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(SystemExit) as error:
        benchmark_factual_grade.main([str(path), "--require-complete"])
    assert error.value.code == 2
    assert capsys.readouterr().out == ""


def test_cli_rejects_infinite_tolerance_instead_of_passing_arbitrary_values(tmp_path, capsys):
    payload = _payload()
    payload["expected_claims"][0]["absolute_tolerance"] = "Infinity"
    payload["observed_claims"][0]["value"] = "999999"
    path = tmp_path / "invalid-tolerance.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(SystemExit) as error:
        benchmark_factual_grade.main([str(path), "--require-complete"])
    assert error.value.code == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("replacement", [
    '"document_exists": false, "document_exists": true',
    '"document_exists": true, "document_exists": false',
    '"document_exists": true, "document_exists": true',
])
def test_cli_rejects_duplicate_existence_decisions_without_a_scorecard(tmp_path, capsys, replacement):
    encoded = json.dumps(_payload()).replace('"document_exists": true', replacement)
    path = tmp_path / "duplicate-review.json"
    path.write_text(encoded)
    with pytest.raises(SystemExit) as error:
        benchmark_factual_grade.main([str(path), "--require-complete"])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "duplicate JSON key" in captured.err


@pytest.mark.parametrize("encoded", [
    '{"expected_claims": [], "expected_claims": []}',
    json.dumps(_payload()).replace('"label": "supports"', '"label": "pending", "label": "supports"'),
    json.dumps(_payload()).replace('"value": "100"', '"value": "999999", "value": "100"', 1),
])
def test_cli_rejects_duplicate_keys_at_every_object_depth(tmp_path, capsys, encoded):
    path = tmp_path / "duplicate-grading.json"
    path.write_text(encoded)
    with pytest.raises(SystemExit) as error:
        benchmark_factual_grade.main([str(path), "--require-complete"])
    assert error.value.code == 2
    assert capsys.readouterr().out == ""

