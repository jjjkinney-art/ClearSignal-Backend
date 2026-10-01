from __future__ import annotations

import json

import pytest

from scripts import benchmark_generated_outputs
from validation.generated_output_grading import grade_generated_outputs
from validation.intelligence_benchmark import BenchmarkContractError


ACCESSION = "0001193125-26-077167"
SOURCE_ID = f"sec:aa:{ACCESSION}"


def _fact(**overrides):
    value = {
        "value_text": "$12,831,000,000",
        "rendered": "$12,831,000,000 (as of 2025-12-31)",
        "provenance": "reported",
        "raw_value": 12831000000,
        "unit": "USD",
        "currency": "USD",
        "ticker": "AA",
        "metric": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "as_of": "2025-12-31",
        "period": "FY2025",
        "scope": "consolidated",
        "document_ref": {
            "reference_id": (
                "sec:1675149:0001193125-26-077167:us-gaap:"
                "RevenueFromContractWithCustomerExcludingAssessedTax"
            ),
            "title": "10-K filed 2026-02-26 · Revenue",
            "provider": "SEC EDGAR",
            "url": (
                "https://www.sec.gov/Archives/edgar/data/1675149/"
                "000119312526077167/0001193125-26-077167-index.htm"
            ),
            "published_at": "2026-02-26",
        },
    }
    value.update(overrides)
    return value


def _payload(*, fact=None):
    claim_id = "AA-fy2025-revenue"
    return {
        "schema_version": 1,
        "run_id": "generated-output-test-v1",
        "cases": [{
            "issuer_id": "AA",
            "question_id": "latest-revenue",
            "sources": [{
                "source_id": SOURCE_ID,
                "revision_id": ACCESSION,
            }],
            "expected_claims": [{
                "claim_id": claim_id,
                "metric": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "value": "12831000000",
                "unit": "USD",
                "currency": "USD",
                "period": "FY2025",
                "scope": "consolidated",
                "source_id": SOURCE_ID,
                "materiality": "material",
            }],
            "adjudications": [{
                "claim_id": claim_id,
                "source_id": SOURCE_ID,
                "document_exists": True,
                "label": "supports",
                "reviewer": "automated:sec-inline-xbrl-accession-v1",
                "rationale": "Exact accession-bound SEC fact.",
            }],
            "response": {
                "company": "AA",
                "request_id": "synthetic:benchmark-request",
                "answer": {"verified_sec_facts": [fact or _fact()]},
            },
        }],
    }


def test_real_pipeline_shaped_verified_fact_passes():
    report = grade_generated_outputs(_payload())
    assert report.passed is True
    assert report.case_count == 1
    result = report.cases[0]
    assert result.admitted_claim_count == 1
    assert result.rejected_claim_count == 0
    assert result.material_numerical_accuracy == 1.0
    assert result.claim_source_binding == 1.0


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_value", 1),
        ("unit", "shares"),
        ("currency", "EUR"),
        ("period", "FY2024"),
        ("scope", "segment"),
    ],
)
def test_each_factual_dimension_fails_closed(field, value):
    report = grade_generated_outputs(_payload(fact=_fact(**{field: value})))
    assert report.passed is False
    assert report.cases[0].stop_ship_count >= 1


def test_wrong_ticker_or_unbound_document_is_rejected():
    wrong_ticker = grade_generated_outputs(_payload(fact=_fact(ticker="AAPL")))
    assert wrong_ticker.passed is False
    assert wrong_ticker.cases[0].admitted_claim_count == 0

    unbound = _fact(document_ref={
        **_fact()["document_ref"],
        "reference_id": "sec:other",
        "url": "https://www.sec.gov/Archives/edgar/data/1/other-index.htm",
    })
    report = grade_generated_outputs(_payload(fact=unbound))
    assert report.passed is False
    assert report.cases[0].claim_source_binding == 0.0


def test_generated_prose_and_unstructured_claims_are_not_treated_as_facts():
    payload = _payload()
    payload["cases"][0]["response"]["answer"] = {
        "investment_thesis": {
            "direct_answer": "AA reported $12.831 billion in revenue.",
            "quantitative_claims": [{"raw_value": 12831000000}],
        },
        "verified_sec_facts": [],
    }
    report = grade_generated_outputs(payload)
    assert report.passed is False
    assert report.cases[0].admitted_claim_count == 0


def test_ambiguous_duplicate_fact_and_cross_issuer_capture_fail_closed():
    duplicate = _payload()
    duplicate["cases"][0]["response"]["answer"]["verified_sec_facts"].append(_fact())
    with pytest.raises(BenchmarkContractError, match="ambiguous"):
        grade_generated_outputs(duplicate)

    mismatch = _payload()
    mismatch["cases"][0]["response"]["company"] = "AAPL"
    with pytest.raises(BenchmarkContractError, match="does not match"):
        grade_generated_outputs(mismatch)


def test_cli_returns_gate_exit_code(tmp_path, capsys):
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(_payload()))
    assert benchmark_generated_outputs.main([str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True

    path.write_text(json.dumps(_payload(fact=_fact(period="FY2024"))))
    assert benchmark_generated_outputs.main([str(path)]) == 1

