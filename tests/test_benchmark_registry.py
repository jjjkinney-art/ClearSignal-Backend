from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import benchmark_registry_audit
from validation.benchmark_registry import (
    REGISTRY_PATH,
    audit_registry,
    load_query_fixtures,
    load_registry,
)
from validation.intelligence_benchmark import BenchmarkContractError


FIXTURES_PATH = Path(__file__).resolve().parents[1] / "validation" / "fixtures.json"


def _report():
    return audit_registry(load_registry(), load_query_fixtures(FIXTURES_PATH))


def test_registry_is_versioned_and_hash_is_stable():
    first = load_registry()
    second = load_registry()
    assert first.registry_version == 1
    assert first.registry_sha256 == second.registry_sha256
    assert len(first.registry_sha256) == 64


def test_existing_suite_maps_completely_to_registry():
    report = _report()
    assert report.fixture_count == 54
    assert report.issuer_count == 18
    assert report.integrity_passed is True
    assert report.integrity_errors == ()


def test_current_coverage_gaps_are_explicit_not_hidden():
    report = _report()
    assert report.launch_coverage_ready is False
    assert "issuer target shortfall: 18/100" in report.target_deficits
    assert "mid target shortfall: 3/30" in report.target_deficits
    assert "small_micro target shortfall: 3/30" in report.target_deficits


def test_all_current_issuers_have_three_core_question_categories():
    fixtures = load_query_fixtures(FIXTURES_PATH)
    categories = {}
    for fixture in fixtures:
        categories.setdefault(fixture.ticker, set()).add(fixture.category)
    assert all(
        values == {"core_thesis", "decision_threshold", "structural_risk"}
        for values in categories.values()
    )


def test_registry_has_no_unknown_market_cap_placeholders():
    counts = dict(_report().market_cap_counts)
    assert counts["unknown"] == 0


def test_registry_now_has_representative_non_large_cap_cohorts():
    counts = dict(_report().market_cap_counts)
    assert counts["mid"] == 3
    assert counts["small_micro"] == 3


def test_registry_rejects_duplicate_ticker(tmp_path):
    data = json.loads(REGISTRY_PATH.read_text())
    data["issuers"].append(dict(data["issuers"][0]))
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data))
    with pytest.raises(BenchmarkContractError, match="sorted|unique"):
        load_registry(path)


def test_registry_rejects_unsorted_complexity_tags(tmp_path):
    data = json.loads(REGISTRY_PATH.read_text())
    data["issuers"][0]["complexity_tags"] = ["z", "a"]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data))
    with pytest.raises(BenchmarkContractError, match="complexity_tags"):
        load_registry(path)


def test_company_mismatch_fails_integrity():
    fixtures = list(load_query_fixtures(FIXTURES_PATH))
    fixtures[0].company = "Wrong Company"
    report = audit_registry(load_registry(), fixtures)
    assert report.integrity_passed is False
    assert any("company does not match" in error for error in report.integrity_errors)


def test_default_cli_passes_structural_integrity(capsys):
    assert benchmark_registry_audit.main([]) == 0
    output = capsys.readouterr().out
    assert "integrity: PASS" in output
    assert "launch coverage: INCOMPLETE" in output


def test_strict_cli_fails_until_coverage_target_is_met(capsys):
    assert benchmark_registry_audit.main(["--strict-targets"]) == 1
    assert "GAP: issuer target shortfall: 18/100" in capsys.readouterr().out
