from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import benchmark_cap_tier_factual
from validation.cap_tier_factual_benchmark import grade_cap_tier_cohort
from validation.intelligence_benchmark import BenchmarkContractError


ISSUERS = ("AA", "DOCU", "ETSY", "ACHC", "ACMR", "MAN")
REAL_CASES_PATH = (
    Path(__file__).resolve().parents[1]
    / "validation" / "cap_tier_factual_cases.v1.json"
)


def _claim_payload(issuer_id, *, value="100", label="supports", exists=True):
    source_id = f"sec-{issuer_id.lower()}-10k"
    return {
        "expected_claims": [{
            "claim_id": f"{issuer_id}-revenue",
            "metric": "Revenue",
            "value": "100",
            "unit": "million",
            "currency": "USD",
            "period": "FY2025",
            "scope": "consolidated",
            "source_id": source_id,
            "materiality": "material",
        }],
        "observed_claims": [{
            "claim_id": f"{issuer_id}-revenue",
            "text": "Frozen observed claim.",
            "value": value,
            "unit": "million",
            "currency": "USD",
            "period": "FY2025",
            "scope": "consolidated",
            "cited_source_id": source_id,
        }],
        "adjudications": [{
            "claim_id": f"{issuer_id}-revenue",
            "source_id": source_id,
            "document_exists": exists,
            "label": label,
            "reviewer": "human:benchmark-reviewer",
            "rationale": "Fixture verifies deterministic cohort aggregation.",
        }],
    }


def _source(issuer_id, **overrides):
    value = {
        "source_id": f"sec-{issuer_id.lower()}-10k",
        "source_type": "sec_filing",
        "document_url": f"https://www.sec.gov/{issuer_id.lower()}-10k",
        "accepted_at": "2026-02-01T00:00:00Z",
        "retrieved_at": "2026-04-02T00:00:00Z",
        "content_sha256": "a" * 64,
        "authoritative": True,
    }
    value.update(overrides)
    return value


def _cohort(**case_overrides):
    return {
        "schema_version": 1,
        "cohort_id": "smaller-company-v1-test",
        "cases": [
            {
                "issuer_id": issuer_id,
                "as_of": "2026-04-01T00:00:00Z",
                "sources": [_source(issuer_id)],
                "claim_payload": _claim_payload(
                    issuer_id, **case_overrides.get(issuer_id, {})
                ),
            }
            for issuer_id in ISSUERS
        ],
    }


def test_complete_mid_and_small_cap_cohort_passes():
    report = grade_cap_tier_cohort(_cohort())
    assert report.passed is True
    assert report.issuer_count == 6
    assert [item.market_cap_tier for item in report.tier_results] == [
        "mid", "small_micro",
    ]
    assert all(item.issuer_count == 3 for item in report.tier_results)
    assert all(item.material_numerical_accuracy == 1.0 for item in report.tier_results)
    assert all(item.claim_source_binding == 1.0 for item in report.tier_results)


def test_frozen_sec_smaller_company_pack_passes_all_gates():
    payload = json.loads(REAL_CASES_PATH.read_text())
    report = grade_cap_tier_cohort(payload)
    assert report.passed is True
    assert report.issuer_count == 6
    assert sum(item.material_claim_count for item in report.tier_results) == 12
    assert all(item.material_numerical_accuracy == 1.0 for item in report.tier_results)
    assert all(item.claim_source_binding == 1.0 for item in report.tier_results)
    assert all(item.stop_ship_count == 0 for item in report.tier_results)


@pytest.mark.parametrize("missing", ["AA", "ACHC"])
def test_each_cap_tier_requires_three_distinct_issuers(missing):
    payload = _cohort()
    payload["cases"] = [
        item for item in payload["cases"] if item["issuer_id"] != missing
    ]
    report = grade_cap_tier_cohort(payload)
    assert report.passed is False
    affected = "mid" if missing == "AA" else "small_micro"
    assert next(
        item for item in report.tier_results
        if item.market_cap_tier == affected
    ).passed is False


def test_one_bad_issuer_cannot_hide_inside_a_passing_average():
    report = grade_cap_tier_cohort(_cohort(AA={"value": "0"}))
    assert report.passed is False
    aa = next(item for item in report.issuer_results if item.issuer_id == "AA")
    assert aa.passed is False
    assert aa.stop_ship_count > 0


def test_pending_adjudication_fails_issuer_tier_and_cohort():
    report = grade_cap_tier_cohort(_cohort(ACMR={"label": "pending"}))
    assert report.passed is False
    small = next(
        item for item in report.tier_results
        if item.market_cap_tier == "small_micro"
    )
    assert small.pending_material_adjudications == 1
    assert small.passed is False


def test_fabricated_or_missing_source_is_stop_ship():
    report = grade_cap_tier_cohort(_cohort(DOCU={"exists": False}))
    assert report.passed is False
    assert sum(
        item.fabricated_material_sources for item in report.tier_results
    ) == 1


def test_duplicate_unregistered_and_large_cap_issuers_fail_closed():
    duplicate = _cohort()
    duplicate["cases"].append(dict(duplicate["cases"][0]))
    with pytest.raises(BenchmarkContractError, match="unique"):
        grade_cap_tier_cohort(duplicate)

    unregistered = _cohort()
    unregistered["cases"][0]["issuer_id"] = "UNKNOWN"
    with pytest.raises(BenchmarkContractError, match="unregistered"):
        grade_cap_tier_cohort(unregistered)

    large = _cohort()
    large["cases"][0]["issuer_id"] = "AAPL"
    with pytest.raises(BenchmarkContractError, match="only mid and small_micro"):
        grade_cap_tier_cohort(large)


def test_future_or_unbound_sources_fail_before_scoring():
    future = _cohort()
    future["cases"][0]["sources"][0]["accepted_at"] = "2026-04-01T00:00:01Z"
    with pytest.raises(BenchmarkContractError, match="future_source_version"):
        grade_cap_tier_cohort(future)

    unbound = _cohort()
    unbound["cases"][0]["sources"][0]["source_id"] = "different-source"
    with pytest.raises(BenchmarkContractError, match="require admitted sources"):
        grade_cap_tier_cohort(unbound)


def test_cli_emits_aggregate_report_and_uses_exit_code_as_gate(tmp_path, capsys):
    passing = tmp_path / "passing.json"
    passing.write_text(json.dumps(_cohort()))
    assert benchmark_cap_tier_factual.main([str(passing)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is True
    assert output["issuer_count"] == 6

    failing = tmp_path / "failing.json"
    failing.write_text(json.dumps(_cohort(MAN={"label": "not_found"})))
    assert benchmark_cap_tier_factual.main([str(failing)]) == 1
