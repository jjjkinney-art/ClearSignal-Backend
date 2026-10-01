from __future__ import annotations

import json
from pathlib import Path

from scripts import benchmark_product_output_acceptance
from validation.product_output_acceptance import run_product_output_acceptance


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "validation" / "product_output_acceptance.v1.json"
)


def _manifest():
    return json.loads(MANIFEST_PATH.read_text())


def _runner_for(manifest, *, bad_ticker=None):
    by_ticker = {case["issuer_id"]: case for case in manifest["cases"]}

    def runner(ticker, question, request_id):
        case = by_ticker[ticker]
        expected = case["expected_claims"][0]
        source = case["sources"][0]
        value = expected["value"] if ticker != bad_ticker else "0"
        return {
            "company": ticker,
            "request_id": request_id,
            "agents_used": ["thesis_synthesizer"],
            "answer": {"verified_sec_facts": [{
                "value_text": value,
                "rendered": value,
                "provenance": "reported",
                "raw_value": value,
                "unit": expected["unit"],
                "currency": expected["currency"],
                "ticker": ticker,
                "metric": f"us-gaap:{expected['metric']}",
                "as_of": "2025-12-31",
                "period": expected["period"],
                "scope": expected["scope"],
                "document_ref": {
                    "reference_id": f"sec:{source['revision_id']}",
                    "title": "Frozen SEC filing",
                    "provider": "SEC EDGAR",
                    "url": source["document_url"],
                },
            }]},
            "routing": {"pipeline_elapsed_s": 1.25},
        }

    return runner


def test_frozen_manifest_has_six_consistent_smaller_company_cases():
    manifest = _manifest()
    assert manifest["run_id"] == "synthetic:smaller-company-revenue-product-v1"
    assert {case["issuer_id"] for case in manifest["cases"]} == {
        "AA", "DOCU", "ETSY", "ACHC", "ACMR", "MAN",
    }
    assert len(manifest["cases"]) == 6
    assert all(case["question_id"] == "latest-annual-revenue" for case in manifest["cases"])
    assert all(len(case["expected_claims"]) == 1 for case in manifest["cases"])


def test_first_six_company_product_output_acceptance_passes():
    manifest = _manifest()
    result = run_product_output_acceptance(
        manifest, execute=True, runner=_runner_for(manifest),
    )
    assert result.passed is True
    assert result.capture_case_count == 6
    assert result.capture_safety == {
        "research_memory_enabled": False,
        "persistence_enabled": False,
        "notification_delivery_enabled": False,
    }
    assert result.grading is not None
    assert result.grading.case_count == 6
    assert {tier.market_cap_tier for tier in result.grading.tiers} == {
        "mid", "small_micro",
    }
    assert all(tier.case_count == 3 for tier in result.grading.tiers)
    assert all(tier.pass_rate == 1.0 for tier in result.grading.tiers)
    assert all(case.elapsed_ms is not None for case in result.grading.cases)


def test_one_bad_company_fails_issuer_tier_and_entire_acceptance():
    manifest = _manifest()
    result = run_product_output_acceptance(
        manifest, execute=True, runner=_runner_for(manifest, bad_ticker="ACMR"),
    )
    assert result.passed is False
    assert result.grading is not None
    acmr = next(case for case in result.grading.cases if case.issuer_id == "ACMR")
    assert acmr.passed is False
    small = next(
        tier for tier in result.grading.tiers
        if tier.market_cap_tier == "small_micro"
    )
    assert small.passed is False
    assert small.pass_rate == 2 / 3


def test_acceptance_cli_is_inert_by_default(capsys):
    assert benchmark_product_output_acceptance.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["execution_enabled"] is False
    assert output["capture_case_count"] == 6
    assert output["grading"] is None
    assert output["passed"] is False

