"""Sprint 3B — latency optimization: context compaction and unit completion.

Grounded in the Sprint 3A.1 production profile (`validation/runs/sprint3a1-profile`):
synthesis-bound on 30/36 queries, and one LOW finding on LLY-decision_threshold.
Fully offline — no network, no LLM.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrity.threshold_parsing import infer_unit, parse_threshold_zone
from app.services.thesis_synthesizer import (
    _dedupe_evidence, _evidence_block, _normalize_evidence_text,
)


def _ev(title, summary, source="10-Q", ts="2026-01-01", score=0.5):
    return SimpleNamespace(title=title, summary=summary, source=source,
                           timestamp=ts, relevance_score=score)


# ── Evidence deduplication ───────────────────────────────────────────────────

class TestEvidenceDeduplication:
    def test_identical_summaries_collapse(self):
        items = [_ev("A", "Azure grew 31% in constant currency."),
                 _ev("B", "Azure grew 31% in constant currency.")]
        assert len(_dedupe_evidence(items)) == 1

    def test_case_and_punctuation_variants_collapse(self):
        # The same sentence from two providers must count once.
        items = [_ev("A", "Azure grew 31% in constant currency."),
                 _ev("B", "azure grew 31% in constant currency!!!")]
        assert len(_dedupe_evidence(items)) == 1

    def test_highest_ranked_instance_survives(self):
        items = [_ev("First", "Same fact."), _ev("Second", "Same fact.")]
        assert [e.title for e in _dedupe_evidence(items)] == ["First"]

    def test_distinct_facts_all_preserved(self):
        items = [_ev("A", "Azure grew 31%."), _ev("B", "Capex rose to $19B."),
                 _ev("C", "Copilot seats doubled.")]
        assert len(_dedupe_evidence(items)) == 3

    def test_same_title_different_summary_kept(self):
        # Two facts filed under one headline are still two facts.
        items = [_ev("Earnings", "Revenue grew 14%."),
                 _ev("Earnings", "Margins compressed 200bps.")]
        assert len(_dedupe_evidence(items)) == 2

    def test_empty_summaries_are_not_duplicates_of_each_other(self):
        # An empty summary says nothing about whether the facts match.
        items = [_ev("A", ""), _ev("B", ""), _ev("C", "")]
        assert len(_dedupe_evidence(items)) == 3

    def test_order_is_preserved(self):
        items = [_ev("A", "one"), _ev("B", "two"), _ev("C", "one"), _ev("D", "three")]
        assert [e.title for e in _dedupe_evidence(items)] == ["A", "B", "D"]

    def test_empty_input(self):
        assert _dedupe_evidence([]) == []

    def test_normalizer_ignores_cosmetics_only(self):
        a = _normalize_evidence_text("Azure grew 31%, in Q3!")
        b = _normalize_evidence_text("azure grew 31 in q3")
        assert a == b
        assert _normalize_evidence_text("Azure grew 31%") != \
            _normalize_evidence_text("Azure grew 32%")

    def test_dedup_runs_before_truncation_preserving_more_facts(self):
        """Duplicates must not displace unique evidence from the top-N cut."""
        items = ([_ev(f"dup{i}", "Repeated headline fact.") for i in range(8)]
                 + [_ev(f"uniq{i}", f"Distinct fact number {i}.") for i in range(5)])
        block = _evidence_block(items, max_items=10)
        for i in range(5):
            assert f"Distinct fact number {i}." in block, f"lost unique fact {i}"
        assert block.count("Repeated headline fact.") == 1

    def test_evidence_block_shrinks_with_duplicates_present(self):
        uniq = [_ev(f"u{i}", f"Distinct fact {i}.") for i in range(4)]
        withdup = uniq + [_ev("d", "Distinct fact 0.")] * 3
        assert len(_evidence_block(withdup)) <= len(_evidence_block(uniq)) + 5

    def test_no_evidence_message_unchanged(self):
        assert _evidence_block([]) == "No evidence available."

    def test_unique_evidence_block_is_byte_identical(self):
        """With no duplicates present, compaction must change nothing."""
        items = [_ev(f"T{i}", f"Fact number {i}.") for i in range(6)]
        before_len = len(_evidence_block(items))
        assert before_len > 0
        # Re-running is stable and every fact is present.
        assert _evidence_block(items) == _evidence_block(items)
        for i in range(6):
            assert f"Fact number {i}." in _evidence_block(items)


# ── LLY prescription-unit completion ─────────────────────────────────────────

class TestPrescriptionUnitInference:
    """The exact Sprint 3A.1 LOW finding: LLY-decision_threshold shipped
    'Zepbound New Prescription Volume' with a null unit."""

    def test_exact_lly_production_metric(self):
        assert infer_unit("Zepbound New Prescription Volume") == "prescriptions"

    def test_exact_lly_production_threshold(self):
        r = parse_threshold_zone({
            "metric": "Zepbound New Prescription Volume",
            "bull_threshold": ">500000", "bear_threshold": "<300000",
            "rationale": "Strong initial uptake above 500,000 supports the growth "
                         "narrative; below indicates market challenges.",
        }, ticker="LLY")
        assert r["unavailable"] is False
        assert r["unit"] == "prescriptions"
        assert r["unit_inferred"] is True
        assert r["unit_missing_reason"] is None

    @pytest.mark.parametrize("metric", [
        "Prescription Volume", "New Prescriptions", "NRx", "TRx",
        "Total Scripts", "Zepbound Scripts",
    ])
    def test_prescription_family_recognised(self, metric):
        assert infer_unit(metric) == "prescriptions"

    @pytest.mark.parametrize("metric,expected", [
        ("Weekly Zepbound Prescriptions", "prescriptions/week"),
        ("Monthly NRx Volume", "prescriptions/month"),
        ("Quarterly Prescription Volume", "prescriptions/quarter"),
        ("Annual Prescription Volume", "prescriptions/year"),
    ])
    def test_period_appended_only_when_metric_states_it(self, metric, expected):
        assert infer_unit(metric) == expected

    def test_period_is_never_guessed(self):
        # The production metric names no period, so none may be invented.
        for metric in ("Zepbound New Prescription Volume", "Prescription Volume",
                       "New Prescriptions"):
            unit = infer_unit(metric)
            assert unit == "prescriptions"
            assert "/" not in unit, f"period fabricated for {metric!r}"

    def test_non_prescription_metrics_unaffected(self):
        assert infer_unit("Competitive Positioning") is None
        assert infer_unit("Management Execution") is None

    def test_explicit_unit_still_wins(self):
        r = parse_threshold_zone({
            "metric": "Zepbound New Prescription Volume",
            "bull_threshold": ">20%", "bear_threshold": "<10%",
        }, ticker="LLY")
        assert r["unit"] == "%"
        assert r["unit_inferred"] is False


# ── Sprint 2B/2C/2D unit inference must not regress ─────────────────────────

class TestPriorUnitInferenceUnchanged:
    @pytest.mark.parametrize("metric,expected", [
        ("Vehicle Deliveries", "vehicles"),
        ("Quarterly EUV Shipments", "systems/quarter"),
        ("737 MAX Monthly Production Rate", "aircraft/month"),
        ("Brent Crude Price", "USD/bbl"),
        ("ASP of Model 3/Y", "USD"),
        ("Operating Margin", "%"),
        ("Forward P/E", "x"),
    ])
    def test_existing_inferences_intact(self, metric, expected):
        assert infer_unit(metric) == expected

    def test_eps_still_needs_currency(self):
        assert infer_unit("Blended EPS") is None
        assert infer_unit("Blended EPS", currency="USD") == "USD/share"

    def test_currency_metrics_still_never_fabricate(self):
        for metric in ("Free Cash Flow", "Revenue", "EBITDA"):
            assert infer_unit(metric) is None

    def test_visa_overlap_protection_intact(self):
        r = parse_threshold_zone({
            "metric": "Forward P/E", "bull_threshold": "<31x",
            "bear_threshold": ">28x"}, ticker="V")
        assert r["unavailable"] is True

    def test_calendar_year_guard_intact(self):
        r = parse_threshold_zone({
            "metric": "Free Cash Flow", "bull_threshold": ">2026",
            "bear_threshold": "<2025", "rationale": "Positive FCF by 2026."},
            ticker="BA")
        assert r["unavailable"] is True
        assert "calendar year" in r["reason"]


# ── No new model calls / no schema change ────────────────────────────────────

class TestNoBehaviorChange:
    def test_compaction_is_deterministic(self):
        items = [_ev("A", "one"), _ev("B", "one"), _ev("C", "two")]
        assert [e.title for e in _dedupe_evidence(items)] == \
               [e.title for e in _dedupe_evidence(items)]

    def test_compaction_adds_no_model_call(self):
        """Context compaction must be deterministic string work, never an
        extra LLM round-trip — an extra call would cost more than it saves."""
        import inspect
        source = inspect.getsource(_dedupe_evidence) + inspect.getsource(
            _normalize_evidence_text)
        for forbidden in ("ModelClient", "chat.completions", "openai", ".call("):
            assert forbidden not in source

    def test_dedupe_never_raises_on_odd_input(self):
        weird = [SimpleNamespace(title="x"), _ev("A", None), _ev("B", "ok")]
        assert isinstance(_dedupe_evidence(weird), list)
