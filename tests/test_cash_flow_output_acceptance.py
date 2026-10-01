from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from validation.product_output_acceptance import run_product_output_acceptance


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "validation" / "cash_flow_output_acceptance.v1.json"
)


def _manifest():
    return json.loads(MANIFEST_PATH.read_text())


def _runner_for(manifest, *, wrong_sign_ticker=None):
    cases = {case["issuer_id"]: case for case in manifest["cases"]}

    def runner(ticker, question, request_id):
        case = cases[ticker]
        source = case["sources"][0]
        facts = []
        for expected in case["expected_claims"]:
            raw_value = expected["value"]
            if ticker == wrong_sign_ticker and raw_value.startswith("-"):
                raw_value = raw_value[1:]
            facts.append({
                "value_text": raw_value,
                "rendered": raw_value,
                "provenance": "reported",
                "raw_value": raw_value,
                "unit": expected["unit"],
                "currency": expected["currency"],
                "ticker": ticker,
                "metric": f"us-gaap:{expected['metric']}",
                "as_of": expected["period"],
                "period": expected["period"],
                "scope": expected["scope"],
                "document_ref": {
                    "reference_id": f"sec:{source['revision_id']}",
                    "title": "Frozen SEC filing",
                    "provider": "SEC EDGAR",
                    "url": source["document_url"],
                },
            })
        return {
            "company": ticker,
            "request_id": request_id,
            "agents_used": ["thesis_synthesizer"],
            "answer": {"verified_sec_facts": facts},
            "routing": {"pipeline_elapsed_s": 1.5},
        }

    return runner


def test_cash_flow_manifest_freezes_two_periods_and_one_comparison_per_issuer():
    manifest = _manifest()
    assert len(manifest["cases"]) == 6
    assert all(len(case["expected_claims"]) == 2 for case in manifest["cases"])
    assert all(len(case["comparisons"]) == 1 for case in manifest["cases"])
    direction = {
        case["issuer_id"]: case["comparisons"][0]["direction"]
        for case in manifest["cases"]
    }
    assert direction["ACMR"] == "decrease"
    assert direction["MAN"] == "decrease"


def test_six_company_cash_flow_output_acceptance_passes_all_comparisons():
    manifest = _manifest()
    result = run_product_output_acceptance(
        manifest, execute=True, runner=_runner_for(manifest),
    )
    assert result.passed is True
    assert result.grading is not None
    assert sum(case.comparison_count for case in result.grading.cases) == 6
    assert sum(case.comparison_correct_count for case in result.grading.cases) == 6
    assert all(tier.pass_rate == 1.0 for tier in result.grading.tiers)


def test_positive_to_negative_sign_reversal_is_release_blocking():
    manifest = _manifest()
    result = run_product_output_acceptance(
        manifest, execute=True,
        runner=_runner_for(manifest, wrong_sign_ticker="ACMR"),
    )
    assert result.passed is False
    assert result.grading is not None
    acmr = next(case for case in result.grading.cases if case.issuer_id == "ACMR")
    assert acmr.passed is False
    assert acmr.comparison_correct_count == 0
    assert acmr.stop_ship_count > 0


def test_incorrect_declared_direction_fails_even_when_both_values_are_exact():
    manifest = deepcopy(_manifest())
    aa = next(case for case in manifest["cases"] if case["issuer_id"] == "AA")
    aa["comparisons"][0]["direction"] = "decrease"
    result = run_product_output_acceptance(
        manifest, execute=True, runner=_runner_for(manifest),
    )
    assert result.passed is False
    assert result.grading is not None
    aa_result = next(case for case in result.grading.cases if case.issuer_id == "AA")
    assert aa_result.material_numerical_accuracy == 1.0
    assert aa_result.comparison_correct_count == 0

