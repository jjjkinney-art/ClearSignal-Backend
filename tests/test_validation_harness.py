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
# Sprint 2A calibration — duplicate-numerical-claim rule
#
# Real MSFT production responses (validation/runs/20260728T140547) showed the
# original value-only duplicate rule flagged 4 false positives: the same
# real-world "Azure growth > 25%" threshold legitimately restated across
# direct_answer/bull_thesis/bear_thesis/conclusion, and the same "~30-33x"
# forward-P/E figure restated across bull_thesis/valuation_view. Neither is a
# defect — it's how an investment thesis is supposed to read. The calibrated
# rule requires matching (normalized value, metric, provenance) plus a
# polarity check against the source prose so "above X" and "below X" mentions
# of the same number are never conflated.
# ─────────────────────────────────────────────────────────────────────────────

class TestDuplicateClaimCalibration:
    def test_identical_semantic_claims_are_flagged(self):
        # Real MSFT bull_thesis text: "growth above 25%... sustaining above 25%"
        # — same field, same polarity, same figure restated -> genuine duplicate.
        thesis = dict(
            BASE_THESIS,
            bull_thesis=(
                "Azure's growth above 25% drives significant revenue and margin expansion. "
                "Confirmation would come from Azure revenue growth sustaining above 25% in constant currency."
            ),
            quantitative_claims=[
                {"value_text": "25%", "provenance": "heuristic", "metric": "bull_thesis", "rendered": "25% (rule-of-thumb)"},
                {"value_text": "25%", "provenance": "heuristic", "metric": "bull_thesis", "rendered": "25% (rule-of-thumb)"},
            ],
        )
        findings = claims_check.check(thesis, _fixture())
        assert any(f.code == "duplicate_numerical_claim" for f in findings)

    def test_same_value_different_metrics_not_flagged(self):
        # Same "25%" restated in direct_answer AND bull_thesis — different
        # metrics -> not automatically a duplicate.
        thesis = dict(
            BASE_THESIS,
            direct_answer="Azure must maintain growth above 25% for the thesis to hold.",
            bull_thesis="Azure's growth above 25% drives margin expansion.",
            quantitative_claims=[
                {"value_text": "25%", "provenance": "heuristic", "metric": "direct_answer"},
                {"value_text": "25%", "provenance": "heuristic", "metric": "bull_thesis"},
            ],
        )
        findings = claims_check.check(thesis, _fixture())
        assert not any(f.code == "duplicate_numerical_claim" for f in findings)

    def test_same_value_opposite_polarity_not_flagged(self):
        # Exact real MSFT direct_answer text: "above 25%" (bull) vs "below 25%"
        # (bear) — same field, same metric, same provenance, but materially
        # different (opposite-direction) meaning -> must NOT be flagged.
        thesis = dict(
            BASE_THESIS,
            direct_answer=(
                "This business model is sustainable as long as Azure maintains a growth rate above 25% "
                "and continues to expand market share. A significant deceleration in Azure's growth below "
                "25% would change the outlook."
            ),
            quantitative_claims=[
                {"value_text": "25%", "provenance": "heuristic", "metric": "direct_answer", "rendered": "25% (rule-of-thumb)"},
                {"value_text": "25%", "provenance": "heuristic", "metric": "direct_answer", "rendered": "25% (rule-of-thumb)"},
            ],
        )
        findings = claims_check.check(thesis, _fixture())
        assert not any(f.code == "duplicate_numerical_claim" for f in findings)

    def test_visa_threshold_overlap_test_still_green(self):
        # Sanity check that claims.py calibration did not disturb the
        # independent thresholds.py overlap detection (Visa fixture).
        thesis = dict(BASE_THESIS, decision_thresholds=[{
            "metric": "Forward P/E", "unavailable": False, "unit": "x",
            "direction": "lower_is_better", "bull_boundary": 31, "bear_boundary": 28,
        }])
        findings = thresholds_check.check(thesis, _fixture(ticker="V", company="Visa"))
        assert any(f.code == "threshold_shown_available_but_contradictory" for f in findings)


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 2A — product-identifier / product-name false-extraction detection
# ─────────────────────────────────────────────────────────────────────────────

class TestProductIdentifierExtraction:
    def test_microsoft_365_extraction_surfaced(self):
        # Exact real defect: "Microsoft 365" -> claim value_text "365,"/"365"/"365."
        thesis = dict(
            BASE_THESIS,
            direct_answer="Azure's integration with Microsoft 365, creates strong switching costs.",
            quantitative_claims=[
                {"value_text": "365,", "provenance": "heuristic", "metric": "direct_answer", "raw_value": 365.0},
            ],
        )
        findings = claims_check.check(thesis, _fixture())
        assert any(f.code == "product_identifier_extracted_as_claim" for f in findings)

    def test_fortune_500_and_sp_500_surfaced(self):
        thesis = dict(
            BASE_THESIS,
            bull_thesis="The company ranks in the Fortune 500 and tracks the S&P 500 closely.",
            quantitative_claims=[
                {"value_text": "500", "provenance": "heuristic", "metric": "bull_thesis"},
            ],
        )
        findings = claims_check.check(thesis, _fixture())
        assert any(f.code == "product_identifier_extracted_as_claim" for f in findings)

    def test_genuine_percentage_not_flagged_as_product_identifier(self):
        thesis = dict(
            BASE_THESIS,
            bull_thesis="Azure's growth above 25% drives margin expansion.",
            quantitative_claims=[
                {"value_text": "25%", "provenance": "heuristic", "metric": "bull_thesis"},
            ],
        )
        findings = claims_check.check(thesis, _fixture())
        assert not any(f.code == "product_identifier_extracted_as_claim" for f in findings)


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


class TestIntegrityStatusReporting:
    """Sprint 2C — the summary must show the Sprint 2B status ladder, not just
    a single 'not clean' rate that reads 100% on every run."""

    @staticmethod
    def _outcome(status=None, ok=True, violations=None, caveats=None):
        from validation.models import QueryOutcome
        integ = {"ok": ok, "violations": violations or [], "caveats": caveats or []}
        if status is not None:
            integ["status"] = status
        return QueryOutcome(
            fixture=_fixture(), status="completed",
            thesis={"_integrity": integ},
        )

    def _summary(self, outcomes):
        from validation.report import _summary_md
        return _summary_md(outcomes)

    def test_status_distribution_section_present(self):
        md = self._summary([
            self._outcome(status="clean"),
            self._outcome(status="qualified", violations=[{"code": "x"}]),
            self._outcome(status="degraded", violations=[{"code": "y"}]),
            self._outcome(status="blocked", ok=False, violations=[{"code": "z"}]),
        ])
        assert "## Integrity status distribution" in md
        for name in ("clean", "qualified", "degraded", "blocked"):
            assert f"`{name}`" in md

    def test_each_status_counted_once(self):
        md = self._summary([
            self._outcome(status="clean"),
            self._outcome(status="clean"),
            self._outcome(status="blocked", ok=False),
        ])
        assert "`clean`: 2" in md
        assert "`blocked`: 1" in md
        assert "`qualified`: 0" in md

    def test_responses_without_status_are_missing_unknown(self):
        # Pre-Sprint-2B responses must still aggregate, not crash or be
        # silently bucketed into a real status.
        md = self._summary([self._outcome(status=None), self._outcome(status=None)])
        assert "`missing/unknown`: 2" in md
        assert "`clean`: 0" in md

    def test_unrecognized_status_falls_into_missing_unknown(self):
        md = self._summary([self._outcome(status="banana")])
        assert "`missing/unknown`: 1" in md

    def test_hard_failure_rate_is_separate_from_any_signal(self):
        # One blocked (ok=false) and one merely qualified: the hard-failure
        # rate must be 1, while the broad any-signal rate is 2.
        md = self._summary([
            self._outcome(status="blocked", ok=False, violations=[{"code": "z"}]),
            self._outcome(status="qualified", violations=[{"code": "x"}]),
        ])
        assert "Hard failures (ok=false): 1" in md
        assert "Any violation or caveat present" in md
        assert "2 (100%)" in md

    def test_broad_rate_is_relabelled_not_a_failure_rate(self):
        md = self._summary([self._outcome(status="qualified", violations=[{"code": "x"}])])
        assert "advisory, not a failure rate" in md
        assert "flagged not-clean" not in md

    def test_no_integrity_blocks_degrades_gracefully(self):
        from validation.models import QueryOutcome
        md = self._summary([
            QueryOutcome(fixture=_fixture(), status="completed", thesis={}),
        ])
        assert "no _integrity blocks observed" in md
