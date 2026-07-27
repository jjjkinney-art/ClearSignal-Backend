"""Sprint 2A — unit tests for the production-validation harness itself.

Fully offline: no network requests are made anywhere in this file. Every test
constructs a fake /ask response dict and exercises validation/validator.py and
validation/checks/*.py directly, plus validation/report.py's aggregation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from validation.models import Finding, QueryFixture, QueryOutcome, Severity, severity_rank
from validation.validator import validate, extract_thesis
from validation import report as report_mod
from validation.checks import thresholds as thresholds_check
from validation.checks import claims as claims_check
from validation.checks import structure as structure_check
from validation.checks import integrity as integrity_check


def _fixture(**overrides) -> QueryFixture:
    base = dict(id="MSFT-core_thesis", ticker="MSFT", company="Microsoft",
               category="core_thesis", question="What is the bull/bear case?")
    base.update(overrides)
    return QueryFixture(**base)


def _response(thesis: dict) -> dict:
    return {"answer": {"investment_thesis": thesis}}


BASE_THESIS = {
    "ticker": "MSFT", "company_name": "Microsoft Corporation",
    "direct_answer": "Microsoft's cloud growth supports the bull case.",
    "bull_thesis": "Azure and Office 365 continue to compound revenue at attractive margins.",
    "bear_thesis": "Multiple compression risk if growth decelerates below expectations.",
    "conclusion": "Microsoft remains a durable compounder.",
    "valuation_view": "Trades in line with historical multiple; fairly valued given growth.",
    "expectation_regime": "fair",
    "confidence_score": 0.7,
    "evidence_count": 12,
    "key_risks": ["Cloud growth deceleration", "Regulatory scrutiny"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Threshold checks
# ─────────────────────────────────────────────────────────────────────────────

class TestThresholds:
    def test_valid_higher_is_better_threshold(self):
        thesis = dict(BASE_THESIS, decision_thresholds=[{
            "metric": "Cloud Revenue Growth YoY", "unavailable": False, "unit": "%",
            "direction": "higher_is_better", "bull_boundary": 20, "bear_boundary": 10,
            "neutral_interval": [10, 20], "assumptions": "validates durability", "provenance": "derived",
        }])
        findings = thresholds_check.check(thesis, _fixture())
        assert not any(f.code.startswith("threshold_shown_available_but_contradictory") for f in findings)
        assert not any(f.severity == Severity.CRITICAL for f in findings)

    def test_valid_lower_is_better_threshold(self):
        thesis = dict(BASE_THESIS, decision_thresholds=[{
            "metric": "Forward P/E", "unavailable": False, "unit": "x",
            "direction": "lower_is_better", "bull_boundary": 20, "bear_boundary": 28,
            "neutral_interval": [20, 28], "assumptions": "historical range", "provenance": "derived",
        }])
        findings = thresholds_check.check(thesis, _fixture())
        assert not any(f.severity == Severity.CRITICAL for f in findings)

    def test_overlapping_threshold_rejected(self):
        # The exact Visa bug: bull<31x, bear>28x on a lower-is-better metric.
        thesis = dict(BASE_THESIS, decision_thresholds=[{
            "metric": "Forward P/E", "unavailable": False, "unit": "x",
            "direction": "lower_is_better", "bull_boundary": 31, "bear_boundary": 28,
        }])
        findings = thresholds_check.check(thesis, _fixture(ticker="V", company="Visa"))
        codes = [f.code for f in findings]
        assert "threshold_shown_available_but_contradictory" in codes
        assert any(f.severity == Severity.CRITICAL for f in findings)

    def test_unavailable_threshold_handled_without_false_positive(self):
        thesis = dict(BASE_THESIS, decision_thresholds=[{
            "metric": "Forward P/E", "unavailable": True, "reason": "overlap", "display": "Threshold unavailable",
        }])
        findings = thresholds_check.check(thesis, _fixture())
        assert not any(f.severity == Severity.CRITICAL for f in findings)
        assert not any(f.code == "unavailable_threshold_missing_reason" for f in findings)

    def test_unavailable_threshold_missing_reason_flagged(self):
        thesis = dict(BASE_THESIS, decision_thresholds=[{"metric": "Forward P/E", "unavailable": True}])
        findings = thresholds_check.check(thesis, _fixture())
        assert any(f.code == "unavailable_threshold_missing_reason" for f in findings)

    def test_identical_boundaries_critical(self):
        thesis = dict(BASE_THESIS, decision_thresholds=[{
            "metric": "Forward P/E", "unavailable": False, "direction": "lower_is_better",
            "bull_boundary": 25, "bear_boundary": 25,
        }])
        findings = thresholds_check.check(thesis, _fixture())
        assert any(f.code == "threshold_identical_boundaries" and f.severity == Severity.CRITICAL for f in findings)


# ─────────────────────────────────────────────────────────────────────────────
# Integrity / valuation-contradiction checks
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrity:
    def test_valuation_label_contradiction_flagged(self):
        thesis = dict(BASE_THESIS, expectation_regime="cheap",
                      valuation_view="The stock is priced for perfection; the multiple is demanding.",
                      _integrity={"ok": True, "price_label": "Priced Cheap", "violations": [], "caveats": []})
        findings = integrity_check.check(thesis, _fixture())
        assert any(f.code == "valuation_label_contradiction" for f in findings)
        assert any(f.code == "clean_status_despite_contradiction" for f in findings)

    def test_clean_valuation_no_contradiction(self):
        thesis = dict(BASE_THESIS,
                      _integrity={"ok": True, "price_label": "Fairly Priced", "violations": [], "caveats": []})
        findings = integrity_check.check(thesis, _fixture())
        assert not any(f.code == "valuation_label_contradiction" for f in findings)

    def test_malformed_integrity_object(self):
        thesis = dict(BASE_THESIS, _integrity="not a dict")
        findings = integrity_check.check(thesis, _fixture())
        assert any(f.code == "malformed_integrity" for f in findings)

    def test_dev_jargon_exposed(self):
        thesis = dict(BASE_THESIS, direct_answer="Traceback (most recent call last): KeyError in synthesis.")
        findings = integrity_check.check(thesis, _fixture())
        assert any(f.code == "dev_jargon_exposed" and f.severity == Severity.CRITICAL for f in findings)


# ─────────────────────────────────────────────────────────────────────────────
# Quantitative-claims checks
# ─────────────────────────────────────────────────────────────────────────────

class TestClaims:
    def test_scenario_classification_with_qualification_passes(self):
        thesis = dict(BASE_THESIS, quantitative_claims=[{
            "value_text": "$6-9B", "rendered": "$6-9B (scenario; assumes capex accelerates; low confidence)",
            "provenance": "scenario", "assumptions": "capex accelerates", "confidence": "low",
        }])
        findings = claims_check.check(thesis, _fixture(ticker="NVDA", company="NVIDIA"))
        assert not any(f.code == "scenario_presented_as_fact" for f in findings)

    def test_scenario_without_qualification_flagged_critical(self):
        thesis = dict(BASE_THESIS, quantitative_claims=[{
            "value_text": "$6-9B", "rendered": "$6-9B", "provenance": "scenario",
        }])
        findings = claims_check.check(thesis, _fixture(ticker="NVDA", company="NVIDIA"))
        assert any(f.code == "scenario_presented_as_fact" and f.severity == Severity.CRITICAL for f in findings)

    def test_stale_reported_claim_marked(self):
        thesis = dict(BASE_THESIS, quantitative_claims=[{
            "value_text": "68%", "rendered": "68% (as of ~190d old)", "provenance": "reported",
            "source": "evidence pool", "as_of": "~190d old", "freshness_status": "stale", "stale": True,
        }])
        findings = claims_check.check(thesis, _fixture())
        assert not any(f.code == "stale_claim_not_marked" for f in findings)
        assert not any(f.code == "stale_precision_unqualified" for f in findings)

    def test_stale_reported_claim_not_marked_flagged(self):
        thesis = dict(BASE_THESIS, quantitative_claims=[{
            "value_text": "68%", "rendered": "68%", "provenance": "reported",
            "source": "evidence pool", "freshness_status": "stale",  # stale flag missing
        }])
        findings = claims_check.check(thesis, _fixture())
        assert any(f.code == "stale_claim_not_marked" and f.severity == Severity.HIGH for f in findings)

    def test_invalid_provenance_classification(self):
        thesis = dict(BASE_THESIS, quantitative_claims=[{"value_text": "42%", "provenance": "guess"}])
        findings = claims_check.check(thesis, _fixture())
        assert any(f.code == "invalid_claim_provenance" and f.severity == Severity.CRITICAL for f in findings)

    def test_duplicate_claim_flagged(self):
        thesis = dict(BASE_THESIS, quantitative_claims=[
            {"value_text": "42%", "provenance": "reported", "source": "x", "as_of": "2026-01-01"},
            {"value_text": "42%", "provenance": "reported", "source": "x", "as_of": "2026-01-01"},
        ])
        findings = claims_check.check(thesis, _fixture())
        assert any(f.code == "duplicate_numerical_claim" for f in findings)

    def test_malformed_empty_claim(self):
        thesis = dict(BASE_THESIS, quantitative_claims=[{"provenance": "reported"}])
        findings = claims_check.check(thesis, _fixture())
        assert any(f.code == "empty_claim" for f in findings)


# ─────────────────────────────────────────────────────────────────────────────
# Structure checks (ticker mismatch, missing optional fields, malformed response)
# ─────────────────────────────────────────────────────────────────────────────

class TestStructure:
    def test_ticker_mismatch_critical(self):
        thesis = dict(BASE_THESIS, ticker="AAPL")  # requested MSFT, backend answered AAPL
        findings = structure_check.check(thesis, _fixture())
        assert any(f.code == "ticker_mismatch" and f.severity == Severity.CRITICAL for f in findings)

    def test_missing_optional_fields_do_not_fail(self):
        minimal = {"ticker": "MSFT", "company_name": "Microsoft", "direct_answer": "Answer here."}
        findings = structure_check.check(minimal, _fixture())  # no `requires` on this fixture
        assert not any(f.severity in (Severity.CRITICAL, Severity.HIGH) for f in findings)

    def test_required_field_missing_is_high(self):
        minimal = {"ticker": "MSFT", "company_name": "Microsoft", "direct_answer": "Answer here."}
        fx = _fixture(requires=["decision_thresholds"])
        findings = structure_check.check(minimal, fx)
        assert any(f.code == "missing_required_field" and f.severity == Severity.HIGH for f in findings)

    def test_malformed_backend_response_via_validate(self):
        thesis, findings, presence = validate({"unexpected": "shape"}, _fixture())
        assert thesis is None
        assert any(f.code == "malformed_response" and f.severity == Severity.CRITICAL for f in findings)

    def test_extract_thesis_tolerant_of_garbage(self):
        assert extract_thesis(None) is None
        assert extract_thesis("not a dict") is None
        assert extract_thesis({"answer": "also not a dict"}) is None
        assert extract_thesis({"answer": {"investment_thesis": {"ticker": "MSFT"}}}) == {"ticker": "MSFT"}

    def test_full_validate_pipeline_on_clean_response(self):
        raw = _response(dict(BASE_THESIS))
        thesis, findings, presence = validate(raw, _fixture())
        assert thesis is not None
        assert presence["active_ticker"] is True
        assert presence["quantitative_claims"] is False  # legitimately absent, not a failure
        assert not any(f.severity == Severity.CRITICAL for f in findings)


# ─────────────────────────────────────────────────────────────────────────────
# Severity assignment + summary aggregation
# ─────────────────────────────────────────────────────────────────────────────

class TestSeverityAndAggregation:
    def test_severity_rank_orders_critical_first(self):
        assert severity_rank(Severity.CRITICAL) < severity_rank(Severity.HIGH)
        assert severity_rank(Severity.HIGH) < severity_rank(Severity.MEDIUM)
        assert severity_rank(Severity.MEDIUM) < severity_rank(Severity.LOW)

    def test_outcome_worst_severity_and_passed(self):
        fx = _fixture()
        outcome = QueryOutcome(fixture=fx, status="completed", findings=[
            Finding(code="a", severity=Severity.LOW, message="x"),
            Finding(code="b", severity=Severity.HIGH, message="y"),
        ])
        assert outcome.worst_severity() == Severity.HIGH
        assert outcome.passed() is False  # HIGH findings fail a query

        clean = QueryOutcome(fixture=fx, status="completed", findings=[
            Finding(code="a", severity=Severity.LOW, message="x"),
        ])
        assert clean.passed() is True  # LOW-only findings do not fail

    def test_non_completed_status_never_passes(self):
        fx = _fixture()
        outcome = QueryOutcome(fixture=fx, status="timeout")
        assert outcome.passed() is False

    def test_summary_aggregation_counts_and_pass_rate(self, tmp_path: Path):
        fx1 = _fixture(id="MSFT-core_thesis")
        fx2 = _fixture(id="V-decision_threshold", ticker="V", company="Visa", category="decision_threshold")
        outcomes = [
            QueryOutcome(fixture=fx1, status="completed", elapsed_s=1.2, findings=[]),
            QueryOutcome(fixture=fx2, status="completed", elapsed_s=2.4, findings=[
                Finding(code="threshold_shown_available_but_contradictory", severity=Severity.CRITICAL, message="x"),
            ]),
        ]
        report_mod.write_artifacts(tmp_path, outcomes)

        summary = (tmp_path / "validation_summary.md").read_text()
        assert "Total queries: **2**" in summary
        assert "Pass rate" in summary
        assert "CRITICAL: 1" in summary

        results_json = (tmp_path / "validation_results.json").read_text()
        assert '"total_queries": 2' in results_json

        by_sev = (tmp_path / "failures_by_severity.md").read_text()
        assert "V-decision_threshold" in by_sev

        by_company = (tmp_path / "failures_by_company.md").read_text()
        assert "Visa" in by_company

        latency = (tmp_path / "latency_summary.md").read_text()
        assert "Median" in latency

    def test_pass_rate_is_zero_when_all_critical(self, tmp_path: Path):
        fx = _fixture()
        outcomes = [QueryOutcome(fixture=fx, status="completed", findings=[
            Finding(code="ticker_mismatch", severity=Severity.CRITICAL, message="wrong ticker"),
        ])]
        report_mod.write_artifacts(tmp_path, outcomes)
        summary = (tmp_path / "validation_summary.md").read_text()
        assert "Pass rate (completed, no CRITICAL/HIGH findings): **0.0%**" in summary
