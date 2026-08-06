"""Sprint 2D — claim canonicalization edge cases and financial unit completion.

Grounded in the Sprint 2C production verification run
(`validation/runs/sprint2c-verify`), whose only four remaining findings were
two ASML duplicate-claim pairs and two Boeing missing threshold units.
Fully offline.
"""
from __future__ import annotations

import pytest

from app.integrity.canonicalization import (
    canonicalize_claims, normalize_unit, normalize_value,
)
from app.integrity.threshold_parsing import (
    infer_unit, parse_threshold_zone, resolve_currency,
)


def _claim(**kw):
    """A claim shaped like the ASML macro claims in the saved run."""
    base = {
        "value_text": "40B", "provenance": "heuristic", "metric": "macro",
        "unit": "B", "ticker": "ASML", "polarity": None, "source": None,
        "as_of": None, "assumptions": None, "assumptions_inferred": False,
        "confidence": None, "derivation": None, "source_date_unavailable": False,
        "stale": False, "freshness_status": "source_date_unavailable",
        "raw_value": 40.0,
    }
    base.update(kw)
    return base


# ── 1. The exact ASML production shapes ──────────────────────────────────────

class TestASMLProductionRegression:
    """The two 40B macro claims differed ONLY in polarity: 'above' on the
    occurrence whose surrounding text carried a directional cue, null on the
    one that did not."""

    def test_asml_decision_threshold_pair_merges(self):
        pair = [_claim(polarity="above"), _claim(polarity=None)]
        out = canonicalize_claims(pair)
        assert len(out) == 1
        assert out[0]["occurrences"] == 2

    def test_asml_structural_risk_pair_merges(self):
        # Same shape, different extraction offsets in the saved response.
        pair = [_claim(polarity="above"), _claim(polarity=None)]
        assert len(canonicalize_claims(pair)) == 1

    def test_merged_claim_keeps_the_observed_polarity(self):
        out = canonicalize_claims([_claim(polarity=None), _claim(polarity="above")])
        assert out[0]["polarity"] == "above"

    def test_null_polarity_is_unknown_not_a_third_direction(self):
        # Order must not matter.
        assert len(canonicalize_claims([_claim(polarity="above"), _claim()])) == 1
        assert len(canonicalize_claims([_claim(), _claim(polarity="above")])) == 1

    def test_scenario_vs_heuristic_100bps_pair_stays_separate(self):
        """The other ASML macro pair differs by provenance and is a LEGITIMATE
        distinction — the validator correctly never flagged it."""
        out = canonicalize_claims([
            _claim(value_text="100 bps", unit="bps", provenance="scenario"),
            _claim(value_text="100bps", unit="bps", provenance="heuristic"),
        ])
        assert len(out) == 2


# ── 2. Formatting equivalence ────────────────────────────────────────────────

class TestValueNormalization:
    @pytest.mark.parametrize("a,b", [
        ("40B", "$40B"),        # currency symbol is presentation
        ("40B", "40 billion"),
        ("40B", "40bn"),
        ("40B", "40b"),
        ("$40B", "40 billion"),
        ("40B.", "40B"),        # trailing punctuation
        ("40 B", "40B"),        # internal whitespace
    ])
    def test_equivalent_spellings_normalize_together(self, a, b):
        assert normalize_value(a) == normalize_value(b)

    @pytest.mark.parametrize("a,b", [
        ("40B", "40M"),
        ("40B", "41B"),
        ("40%", "40x"),
        ("40B", "400B"),
    ])
    def test_genuinely_different_figures_stay_apart(self, a, b):
        assert normalize_value(a) != normalize_value(b)

    def test_bps_is_not_eaten_by_the_billion_alias(self):
        assert normalize_value("100bps") == normalize_value("100 basis points")
        assert normalize_value("100bps") != normalize_value("100b")

    def test_unit_normalization_matches_value_normalization(self):
        assert normalize_unit("B") == normalize_unit("billion") == "b"
        assert normalize_unit("bps") == normalize_unit("basis points") == "bps"
        assert normalize_unit(None) == ""

    def test_formatting_variants_merge_end_to_end(self):
        out = canonicalize_claims([
            _claim(value_text="40B"), _claim(value_text="$40B"),
            _claim(value_text="40 billion", unit=None),
        ])
        assert len(out) == 1
        assert out[0]["occurrences"] == 3


# ── 3. Distinctions that must survive ────────────────────────────────────────

class TestPreservedDistinctions:
    def test_same_value_different_metric(self):
        out = canonicalize_claims([_claim(metric="macro"), _claim(metric="valuation")])
        assert len(out) == 2

    def test_same_value_opposite_polarity(self):
        out = canonicalize_claims([_claim(polarity="above"), _claim(polarity="below")])
        assert len(out) == 2

    def test_same_value_different_provenance(self):
        out = canonicalize_claims([
            _claim(provenance="heuristic"), _claim(provenance="scenario"),
        ])
        assert len(out) == 2

    def test_same_value_different_ticker(self):
        out = canonicalize_claims([_claim(ticker="ASML"), _claim(ticker="AMAT")])
        assert len(out) == 2

    def test_conflicting_non_null_sources_stay_separate(self):
        out = canonicalize_claims([
            _claim(source="10-K"), _claim(source="earnings call"),
        ])
        assert len(out) == 2

    def test_conflicting_as_of_dates_stay_separate(self):
        out = canonicalize_claims([
            _claim(as_of="2026-03-31"), _claim(as_of="2025-12-31"),
        ])
        assert len(out) == 2

    def test_different_explicit_units_stay_separate(self):
        out = canonicalize_claims([
            _claim(value_text="40", unit="%"), _claim(value_text="40", unit="x"),
        ])
        assert len(out) == 2

    def test_author_stated_assumptions_stay_separate(self):
        out = canonicalize_claims([
            _claim(assumptions="assumes EUV demand holds", assumptions_inferred=False),
            _claim(assumptions="assumes China export curbs ease", assumptions_inferred=False),
        ])
        assert len(out) == 2


# ── 4. Noise that must NOT split a group ─────────────────────────────────────

class TestMergedNoise:
    def test_inferred_assumption_versus_empty(self):
        out = canonicalize_claims([
            _claim(assumptions="if rates rise 100bps", assumptions_inferred=True),
            _claim(assumptions=None),
        ])
        assert len(out) == 1
        assert out[0]["occurrences"] == 2

    def test_two_different_inferred_snippets(self):
        out = canonicalize_claims([
            _claim(assumptions="if rates rise", assumptions_inferred=True),
            _claim(assumptions="could compress the multiple", assumptions_inferred=True),
        ])
        assert len(out) == 1

    def test_missing_unit_versus_explicit_unit(self):
        # Absent unit is unknown, not different; the explicit one is kept.
        out = canonicalize_claims([_claim(unit=None), _claim(unit="B")])
        assert len(out) == 1
        assert out[0]["unit"] == "B"

    def test_missing_source_versus_present_source(self):
        out = canonicalize_claims([_claim(source=None), _claim(source="10-K")])
        assert len(out) == 1
        assert out[0]["source"] == "10-K"

    def test_equivalent_punctuation(self):
        out = canonicalize_claims([_claim(value_text="40B."), _claim(value_text="40B")])
        assert len(out) == 1

    def test_occurrences_accumulate_across_a_larger_group(self):
        out = canonicalize_claims([_claim() for _ in range(5)])
        assert len(out) == 1
        assert out[0]["occurrences"] == 5


# ── 5. Financial threshold units ─────────────────────────────────────────────

class TestCurrencyResolution:
    @pytest.mark.parametrize("text,expected", [
        ("EPS above $10", "USD"),
        ("EPS above €3.20", "EUR"),
        ("above £5", "GBP"),
        ("above ¥500", "JPY"),
        ("revenue of USD 40B", "USD"),
        ("revenue of EUR 28B", "EUR"),
    ])
    def test_explicit_currency_is_resolved(self, text, expected):
        assert resolve_currency(text) == expected

    def test_no_currency_evidence_returns_none(self):
        assert resolve_currency("FCF must turn positive by 2026") is None
        assert resolve_currency(None, "", "growth of 12%") is None

    def test_us_listing_alone_is_not_currency_evidence(self):
        # The ticker/company never participates in currency resolution.
        assert resolve_currency("Boeing free cash flow improves") is None


class TestFinancialUnitInference:
    def test_blended_eps_with_usd_context(self):
        # The exact Boeing shape: the rationale carries "$10" / "$8".
        r = parse_threshold_zone({
            "metric": "Blended EPS", "bull_threshold": ">10", "bear_threshold": "<8",
            "rationale": "EPS above $10 indicates successful recovery; below $8 "
                         "suggests significant operational issues.",
        }, ticker="BA")
        assert r["unavailable"] is False
        assert r["unit"] == "USD/share"
        assert r["unit_inferred"] is True

    def test_eps_with_eur_context(self):
        assert infer_unit("Adjusted EPS", currency="EUR") == "EUR/share"

    @pytest.mark.parametrize("metric", [
        "EPS", "Diluted EPS", "Adjusted EPS", "Blended EPS", "Earnings Per Share",
    ])
    def test_all_eps_variants_are_per_share(self, metric):
        assert infer_unit(metric, currency="USD") == "USD/share"

    def test_eps_without_currency_fails_safe(self):
        assert infer_unit("Blended EPS") is None
        assert infer_unit("Blended EPS", currency=None) is None

    def test_free_cash_flow_with_explicit_currency(self):
        r = parse_threshold_zone({
            "metric": "Free Cash Flow", "bull_threshold": ">$6B",
            "bear_threshold": "<$2B", "rationale": "FCF recovery underpins the thesis.",
        }, ticker="BA")
        assert r["unavailable"] is False
        # The magnitude suffix in the threshold text is an EXPLICIT unit, so it
        # wins over inference and is left exactly as parsed.
        assert r["unit"] == "b"
        assert r["unit_inferred"] is False

    def test_free_cash_flow_without_currency_metadata_stays_unresolved(self):
        r = parse_threshold_zone({
            "metric": "Free Cash Flow", "bull_threshold": ">6", "bear_threshold": "<2",
            "rationale": "FCF must improve materially.",
        }, ticker="BA")
        assert r["unavailable"] is False
        assert r["unit"] is None
        assert r["unit_missing_reason"]
        assert r["unit_inferred"] is False

    def test_revenue_with_explicit_currency(self):
        assert infer_unit("Revenue", currency="USD") == "USD"
        assert infer_unit("Annual Revenue", currency="EUR") == "EUR/year"

    @pytest.mark.parametrize("metric", [
        "Operating Margin", "Gross Margin", "Revenue Growth Rate", "Dividend Yield",
    ])
    def test_percent_metrics_need_no_currency(self, metric):
        assert infer_unit(metric) == "%"

    @pytest.mark.parametrize("metric", [
        "Forward P/E", "P/E", "EV/EBITDA", "Forward Multiple",
    ])
    def test_multiple_metrics_need_no_currency(self, metric):
        assert infer_unit(metric) == "x"

    def test_explicit_unit_is_never_overridden(self):
        r = parse_threshold_zone({
            "metric": "Blended EPS", "bull_threshold": ">10%", "bear_threshold": "<8%",
            "rationale": "EPS above $10.",
        }, ticker="BA")
        assert r["unit"] == "%"
        assert r["unit_inferred"] is False

    def test_ambiguous_metric_gets_no_invented_unit(self):
        assert infer_unit("Competitive Positioning", currency="USD") is None
        assert infer_unit("Management Execution") is None

    def test_no_currency_is_ever_fabricated(self):
        # A currency-shaped metric with no currency evidence must stay None,
        # never silently default to USD.
        for metric in ("Free Cash Flow", "Revenue", "EBITDA", "Operating Income"):
            assert infer_unit(metric) is None


class TestMalformedCurrencyBand:
    """Boeing's "Free Cash Flow" band was bull>2026 / bear<2025 — calendar
    years, not cash. Dressing that up as USD would be worse than admitting the
    band is unusable."""

    def test_calendar_year_band_for_a_currency_metric_is_unavailable(self):
        r = parse_threshold_zone({
            "metric": "Free Cash Flow", "bull_threshold": ">2026",
            "bear_threshold": "<2025",
            "rationale": "Positive FCF by 2026 supports valuation; negative FCF "
                         "signals ongoing operational challenges.",
        }, ticker="BA")
        assert r["unavailable"] is True
        assert "calendar year" in r["reason"]

    def test_real_currency_values_are_not_mistaken_for_years(self):
        r = parse_threshold_zone({
            "metric": "Free Cash Flow", "bull_threshold": ">$6B",
            "bear_threshold": "<$2B", "rationale": "FCF recovery.",
        }, ticker="BA")
        assert r["unavailable"] is False

    def test_year_guard_does_not_apply_to_non_currency_metrics(self):
        # A count metric legitimately in the 2000s must not be fail-closed.
        r = parse_threshold_zone({
            "metric": "Vehicle Deliveries", "bull_threshold": ">2026",
            "bear_threshold": "<2025", "rationale": "Delivery ramp.",
        }, ticker="TSLA")
        assert r["unavailable"] is False
        assert r["unit"] == "vehicles"

    def test_year_guard_requires_both_boundaries_to_look_like_years(self):
        r = parse_threshold_zone({
            "metric": "Free Cash Flow", "bull_threshold": ">2026",
            "bear_threshold": "<5", "rationale": "FCF.",
        }, ticker="BA")
        assert r["unavailable"] is False


# ── 6. Sprint 2B/2C gains must not regress ───────────────────────────────────

class TestPreviousGainsPreserved:
    def test_visa_overlap_still_rejected(self):
        r = parse_threshold_zone({
            "metric": "Forward P/E", "bull_threshold": "<31x", "bear_threshold": ">28x",
        }, ticker="V")
        assert r["unavailable"] is True

    def test_visa_non_overlapping_band_accepted(self):
        r = parse_threshold_zone({
            "metric": "Forward P/E", "bull_threshold": "<20x", "bear_threshold": ">28x",
        }, ticker="V")
        assert r["unavailable"] is False
        assert r["direction"] == "lower_is_better"

    def test_higher_is_better_preserved(self):
        r = parse_threshold_zone({
            "metric": "Revenue Growth", "bull_threshold": ">25%", "bear_threshold": "<15%",
        }, ticker="X")
        assert r["direction"] == "higher_is_better"
        assert r["neutral_interval"] == [15.0, 25.0]

    @pytest.mark.parametrize("metric,expected", [
        ("Vehicle Deliveries", "vehicles"),
        ("Quarterly EUV Shipments", "systems/quarter"),
        ("737 MAX Monthly Production Rate", "aircraft/month"),
        ("Brent Crude Price", "USD/bbl"),
    ])
    def test_sprint_2b_unit_inferences_unchanged(self, metric, expected):
        assert infer_unit(metric) == expected

    def test_unparseable_threshold_still_unavailable(self):
        r = parse_threshold_zone({
            "metric": "Something", "bull_threshold": "strong", "bear_threshold": "weak",
        }, ticker="X")
        assert r["unavailable"] is True

    def test_canonicalization_still_handles_odd_input(self):
        assert canonicalize_claims([]) == []
        assert canonicalize_claims(None) == []
        out = canonicalize_claims([_claim(), "junk", None])
        assert "junk" in out and None in out

    def test_claim_schema_stays_backward_compatible(self):
        out = canonicalize_claims([_claim()])[0]
        for key in _claim():
            assert key in out
        assert out["occurrences"] == 1
