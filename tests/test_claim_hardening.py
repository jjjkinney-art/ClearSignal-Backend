"""Sprint 2B — claim provenance & extraction hardening.

Every case here is drawn from a real defect in the Sprint 2A 36-query
production benchmark (validation/runs/20260729T154936) or from a legitimate
behavior that must survive the fix.  Fully offline: no network, no LLM.
"""
from __future__ import annotations

import pytest

from app.integrity.canonicalization import canonicalize_claims, normalize_value
from app.integrity.claim_extraction import extract_claims, has_source_binding
from app.integrity.consistency import (
    STATUS_BLOCKED, STATUS_CLEAN, STATUS_DEGRADED, STATUS_QUALIFIED,
    validate_thesis_integrity,
)
from app.integrity.identifiers import identifier_spans
from app.integrity.provenance import Provenance
from app.integrity.threshold_parsing import infer_unit, parse_threshold_zone


def _provenance_of(text, **kw):
    return [c.provenance for c in extract_claims(text, ticker="X", **kw)]


def _values(text, **kw):
    return [c.value_text for c in extract_claims(text, ticker="X", **kw)]


# ── 1. Source binding for REPORTED claims ────────────────────────────────────

class TestReportedRequiresSourceBinding:
    """Sprint 2A shipped 9 HIGH `missing_source_for_reported_claim` findings.
    Every one came from a prose cue word with nothing sourcing it."""

    def test_binding_requires_source_and_date_or_explicit_unavailable(self):
        assert has_source_binding("10-Q", "2026-03-31") is True
        assert has_source_binding("10-Q", None, source_date_unavailable=True) is True
        assert has_source_binding("10-Q", None) is False
        assert has_source_binding(None, "2026-03-31") is False
        assert has_source_binding("", "2026-03-31") is False

    def test_future_quarterly_report_is_not_reported(self):
        # MSFT-structural_risk / NVDA-decision_threshold: "quarter" is a
        # reported cue, but the sentence describes a FUTURE result.
        provs = _provenance_of(
            "Confirmation would come from Azure's revenue growth rate "
            "exceeding 25% in the next quarterly report."
        )
        assert provs, "expected at least one claim"
        assert Provenance.REPORTED not in provs

    def test_future_year_in_forward_prose_is_not_reported(self):
        # JPM-structural_risk claim[15]: '2026' classified REPORTED.
        provs = _provenance_of(
            "Management is targeting a mid-teens return on tangible common "
            "equity by 2026, per the fiscal outlook."
        )
        assert Provenance.REPORTED not in provs

    def test_valuation_target_range_is_not_reported(self):
        # BA-core_thesis claim[4]: '$200-220.' classified REPORTED.
        provs = _provenance_of(
            "Our bull case targets a share price of $200-220. This assumes the "
            "quarterly delivery cadence normalizes."
        )
        assert Provenance.REPORTED not in provs

    def test_bull_condition_percentage_is_not_reported(self):
        provs = _provenance_of(
            "The bull case holds while cloud growth stays above 22% through the "
            "fiscal year."
        )
        assert Provenance.REPORTED not in provs

    def test_bear_condition_percentage_is_not_reported(self):
        # ASML-structural_risk claim[12]: '15-20%' classified REPORTED.
        provs = _provenance_of(
            "A bear case emerges if bookings decline 15-20% versus the prior "
            "fiscal quarter."
        )
        assert Provenance.REPORTED not in provs

    def test_bare_number_with_quarter_cue_is_not_reported(self):
        # ASML-decision_threshold claim[3]: '200' classified REPORTED.
        provs = _provenance_of(
            "Systems shipped could approach 200 units in a strong quarter."
        )
        assert Provenance.REPORTED not in provs

    def test_genuine_reported_claim_with_inline_source_is_preserved(self):
        # The prose names its own source — this MUST stay REPORTED.
        claims = extract_claims(
            "Reported net revenue grew 11% per the 10-Q this quarter.", ticker="V",
        )
        reported = [c for c in claims if c.provenance is Provenance.REPORTED]
        assert reported, "a claim citing the 10-Q must remain REPORTED"
        assert reported[0].source, "a REPORTED claim must carry a source"
        assert reported[0].source_date_unavailable is True

    def test_earnings_call_is_a_valid_inline_source(self):
        claims = extract_claims(
            "Management reported a 42% gross margin on the earnings call.", ticker="X",
        )
        assert any(c.provenance is Provenance.REPORTED and c.source for c in claims)

    def test_period_words_alone_are_never_a_source(self):
        # "quarter"/"fiscal"/"Q3" are periods, not sources — the exact Sprint 2A
        # defect. None of these may produce a sourced REPORTED claim.
        for text in (
            "Margins reached 31% this quarter.",
            "Revenue grew 18% in fiscal terms.",
            "Q3 operating income rose 12%.",
        ):
            claims = extract_claims(text, ticker="X")
            assert not [c for c in claims if c.provenance is Provenance.REPORTED], text

    @pytest.mark.parametrize("text", [
        "Azure growth must exceed 25% in the next quarterly report.",
        "Management targets 15% margins by 2026.",
        "The bull case implies $200-220. per share this fiscal year.",
        "Bookings fell 15-20% versus the prior quarter.",
        "Q3 shipments could approach 200 systems.",
        "FY2027 revenue reaches 30% growth on this trajectory.",
        "Deliveries of 1.8M vehicles are posted as the quarterly goal.",
        "Reported guidance of 12% is the fiscal target.",
        "The print showed 40% share in a strong quarter.",
    ])
    def test_no_prose_cue_alone_yields_an_unsourced_reported_claim(self, text):
        """The core Sprint 2B invariant: REPORTED is unreachable without a
        source. These are the nine Sprint 2A failure shapes."""
        for c in extract_claims(text, ticker="X"):
            if c.provenance is Provenance.REPORTED:
                assert c.source, f"unsourced REPORTED claim from {text!r}"

    def test_downgrade_never_fabricates_source_or_date(self):
        for c in extract_claims(
            "Growth should reach 30% in the next quarterly report.", ticker="X",
        ):
            assert c.source is None
            assert c.as_of is None


# ── 2. Product / identifier numbers are not quantitative claims ──────────────

class TestIdentifierExtraction:
    """Sprint 2A: "Microsoft 365" became the claim `365`; "Boeing 737" became
    `737`.  The fix must not blacklist the numbers themselves."""

    def test_microsoft_365_not_extracted(self):
        assert "365" not in "".join(_values(
            "Azure's integration with Microsoft 365 creates switching costs."
        ))

    def test_microsoft_365_with_trailing_punctuation_not_extracted(self):
        # Sprint 2A saw all three of "365," / "365" / "365." extracted.
        for text in (
            "...its integration with Microsoft 365, which locks in enterprises.",
            "...strength across Microsoft 365.",
            "...bundled into Microsoft 365 and Azure.",
        ):
            vals = [v for v in _values(text) if "365" in v]
            assert vals == [], f"{text!r} -> {vals!r}"

    def test_office_and_windows_365_not_extracted(self):
        assert not [v for v in _values("Office 365 seats grew.") if "365" in v]
        assert not [v for v in _values("Windows 365 adoption rose.") if "365" in v]

    def test_365_days_remains_extractable(self):
        # The number is only excluded inside an identifier phrase.
        assert any("365" in v for v in _values("The contract runs a full 365 days."))

    def test_boeing_737_not_extracted_as_family_name(self):
        assert not [v for v in _values("Boeing 737 production remains constrained.")
                    if "737" in v]

    def test_737_max_suffix_not_extracted(self):
        assert not [v for v in _values("The 737 MAX return-to-service continues.")
                    if "737" in v]

    def test_737_aircraft_delivered_remains_extractable(self):
        # A genuine count that happens to equal a model number.
        assert any("737" in v for v in _values("Boeing delivered 737 aircraft last year."))

    def test_model_3_not_treated_as_a_claim(self):
        assert not [v for v in _values("Model 3 remains the volume vehicle.")
                    if v.strip() == "3"]

    def test_model_3_asp_remains_extractable(self):
        vals = _values("Model 3 ASP of $42,000 held firm.")
        assert any("42,000" in v for v in vals), vals

    def test_sp_500_excluded_but_its_return_extracted(self):
        vals = _values("The S&P 500 returned 12% over the period.")
        assert not [v for v in vals if v.strip() == "500"]
        assert any("12%" in v for v in vals), vals

    def test_fortune_500_excluded(self):
        assert not [v for v in _values("A Fortune 500 customer base.")
                    if v.strip() == "500"]

    def test_regulatory_forms_and_rules_excluded(self):
        assert not [v for v in _values("Disclosed in Form 10-K and Form 8-K filings.")
                    if v.strip() in ("10", "8")]
        assert not [v for v in _values("Sales under a Rule 10b5-1 plan; Rule 144 applies.")
                    if v.strip() in ("10", "144")]

    def test_identifier_spans_are_narrow(self):
        # Only the identifier's own number is covered; other figures are free.
        text = "S&P 500 returned 12%."
        spans = identifier_spans(text)
        assert len(spans) == 1
        start, end, label = spans[0]
        assert text[start:end] == "500"
        assert "S&P" in label


# ── 3. Canonicalization / deduplication ──────────────────────────────────────

def _claim(**kw):
    base = {
        "value_text": "25%", "provenance": "scenario", "metric": "bull_thesis",
        "unit": "%", "ticker": "X", "polarity": None, "source": None,
        "as_of": None, "assumptions": None, "assumptions_inferred": False,
        "confidence": None, "derivation": None, "source_date_unavailable": False,
    }
    base.update(kw)
    return base


class TestCanonicalization:
    """Sprint 2A produced 19 duplicate findings; the raw responses showed the
    duplicate pairs were byte-identical claim objects."""

    def test_identical_claims_collapse_and_count_occurrences(self):
        out = canonicalize_claims([_claim(), _claim()])
        assert len(out) == 1
        assert out[0]["occurrences"] == 2

    def test_same_value_different_metric_preserved(self):
        out = canonicalize_claims([
            _claim(metric="bull_thesis"), _claim(metric="macro_sensitivity"),
        ])
        assert len(out) == 2

    def test_same_value_opposite_polarity_preserved(self):
        out = canonicalize_claims([
            _claim(polarity="above"), _claim(polarity="below"),
        ])
        assert len(out) == 2

    def test_same_value_different_provenance_preserved(self):
        out = canonicalize_claims([
            _claim(provenance="scenario"), _claim(provenance="reported"),
        ])
        assert len(out) == 2

    def test_inferred_assumption_snippets_do_not_block_dedup(self):
        # The real MSFT-structural_risk case: one claim restated in the same
        # field, differing only by the text window the extractor captured.
        out = canonicalize_claims([
            _claim(assumptions="if azure maintains a growth rate above 25%",
                   assumptions_inferred=True, polarity="above"),
            _claim(assumptions="would come from azure's revenue growth exceeding",
                   assumptions_inferred=True, polarity="above"),
        ])
        assert len(out) == 1
        assert out[0]["occurrences"] == 2

    def test_author_stated_assumptions_do_distinguish(self):
        out = canonicalize_claims([
            _claim(assumptions="assumes AI capex accelerates", assumptions_inferred=False),
            _claim(assumptions="assumes FX headwinds abate", assumptions_inferred=False),
        ])
        assert len(out) == 2

    def test_most_complete_member_survives(self):
        out = canonicalize_claims([
            _claim(source=None, as_of=None, confidence=None),
            _claim(source="10-Q", as_of="2026-03-31", confidence="high"),
        ])
        assert len(out) == 1
        assert out[0]["source"] == "10-Q"
        assert out[0]["as_of"] == "2026-03-31"
        assert out[0]["confidence"] == "high"
        assert out[0]["occurrences"] == 2

    def test_order_of_first_appearance_is_stable(self):
        out = canonicalize_claims([
            _claim(value_text="10%"), _claim(value_text="20%"), _claim(value_text="10%"),
        ])
        assert [c["value_text"] for c in out] == ["10%", "20%"]

    def test_trailing_punctuation_normalized(self):
        assert normalize_value("$200-220.") == normalize_value("$200-220")
        out = canonicalize_claims([_claim(value_text="$200-220."), _claim(value_text="$200-220")])
        assert len(out) == 1

    def test_non_dict_entries_pass_through(self):
        out = canonicalize_claims([_claim(), "junk", None])
        assert "junk" in out and None in out

    def test_empty_input(self):
        assert canonicalize_claims([]) == []
        assert canonicalize_claims(None) == []

    @pytest.mark.parametrize("value,metric", [
        ("~28-30x", "valuation"),   # AAPL valuation duplicates
        ("100 bps", "macro"),       # Visa / ASML / LLY macro duplicates
        ("~12-14x", "valuation"),   # JPM valuation duplicate ranges
        ("15-25%", "macro"),        # Palantir macro duplicates
        ("$20-25B", "valuation"),   # Lilly valuation duplicates
    ])
    def test_benchmark_duplicate_pairs_collapse(self, value, metric):
        """Regression fixtures for the exact duplicate pairs Sprint 2A found —
        each was the same figure extracted from an agent's `overall` prose and
        again from one of its signals."""
        pair = [_claim(value_text=value, metric=metric, provenance="heuristic",
                       unit=None, ticker="X") for _ in range(2)]
        out = canonicalize_claims(pair)
        assert len(out) == 1
        assert out[0]["occurrences"] == 2

    def test_same_claim_in_direct_answer_and_conclusion_preserved(self):
        # Different thesis sections are different metrics — a restatement in
        # the conclusion is not a defect and must not be silently dropped.
        out = canonicalize_claims([
            _claim(metric="direct_answer"), _claim(metric="conclusion"),
        ])
        assert len(out) == 2


# ── 4. Provenance classification quality ─────────────────────────────────────

class TestProvenanceClassification:
    def test_reported_historical_fact_with_source(self):
        claims = extract_claims("Revenue rose 14% as reported in the 10-K.", ticker="X")
        assert Provenance.REPORTED in [c.provenance for c in claims]

    def test_derived_calculation_language(self):
        assert Provenance.DERIVED in _provenance_of(
            "Annualizing the run-rate translates to $4.8B of revenue."
        )

    def test_analyst_estimate(self):
        assert Provenance.ESTIMATED in _provenance_of(
            "Consensus estimates put FY27 EPS at $13.20."
        )

    def test_conditional_scenario(self):
        assert Provenance.SCENARIO in _provenance_of(
            "If hyperscaler capex accelerates, this could add $6-9B of revenue."
        )

    def test_macro_sensitivity_is_scenario_not_heuristic(self):
        # Sprint 2A left these as HEURISTIC despite explicit conditionality.
        assert Provenance.SCENARIO in _provenance_of(
            "A 100 bps rise in rates would compress the multiple materially."
        )

    def test_genuine_heuristic_falls_back_safely(self):
        provs = _provenance_of("The stock trades at 31x forward earnings.")
        assert provs and provs[0] is Provenance.HEURISTIC

    def test_ambiguous_claim_never_defaults_to_reported(self):
        for c in extract_claims("A 45% figure appears in the analysis.", ticker="X"):
            assert c.provenance is not Provenance.REPORTED

    def test_polarity_is_captured(self):
        above = extract_claims("Growth must stay above 25% to hold.", ticker="X")
        below = extract_claims("A decline below 25% breaks the thesis.", ticker="X")
        assert above[0].polarity == "above"
        assert below[0].polarity == "below"


# ── 5. Integrity status semantics ────────────────────────────────────────────

class TestIntegrityStatus:
    def _thesis(self, claims=None, **kw):
        t = {"ticker": "X", "company": "X", "expectation_regime": "fair",
             "valuation_stance": "fairly_valued"}
        if claims is not None:
            t["quantitative_claims"] = claims
        t.update(kw)
        return t

    def test_clean_response_is_clean(self):
        res = validate_thesis_integrity(self._thesis())
        assert res.status == STATUS_CLEAN
        assert res.ok is True

    def test_unsourced_reported_claim_blocks(self):
        res = validate_thesis_integrity(self._thesis(claims=[
            _claim(provenance="reported", source=None, ticker="X"),
        ]))
        assert res.status == STATUS_BLOCKED
        assert res.ok is False
        assert any(v.code == "unsourced_reported_claim" for v in res.violations)

    def test_sourced_reported_claim_does_not_block(self):
        res = validate_thesis_integrity(self._thesis(claims=[
            _claim(provenance="reported", source="10-Q", as_of="2026-03-31", ticker="X"),
        ]))
        assert res.ok is True
        assert not any(v.code == "unsourced_reported_claim" for v in res.violations)

    def test_majority_unqualified_claims_degrade(self):
        claims = [_claim(provenance="heuristic", ticker="X",
                         value_text=f"{i}0%") for i in range(1, 7)]
        res = validate_thesis_integrity(self._thesis(claims=claims))
        assert res.status == STATUS_DEGRADED
        assert res.ok is True, "degraded quality is not a hard contradiction"
        assert any(v.code == "degraded_claim_quality" for v in res.violations)

    def test_small_claim_set_not_degraded_on_ratio_alone(self):
        # Below the absolute floor: 2 claims, 1 unqualified is not 'degraded'.
        claims = [
            _claim(provenance="heuristic", ticker="X", value_text="10%"),
            _claim(provenance="scenario", ticker="X", value_text="20%",
                   confidence="low"),
        ]
        res = validate_thesis_integrity(self._thesis(claims=claims))
        assert res.status != STATUS_DEGRADED

    def test_qualified_sits_between_clean_and_degraded(self):
        claims = [
            _claim(provenance="scenario", ticker="X", value_text="10%", confidence="low"),
            _claim(provenance="heuristic", ticker="X", value_text="20%"),
        ]
        res = validate_thesis_integrity(self._thesis(claims=claims))
        assert res.status == STATUS_QUALIFIED

    def test_hard_contradiction_still_sets_ok_false(self):
        # Sprint 1B behavior must be untouched.
        res = validate_thesis_integrity({
            "ticker": "MSFT", "expectation_regime": "cheap",
            "valuation_stance": "fairly_valued",
            "valuation_view": "At ~34x forward earnings the multiple already "
                              "prices Azure durability; limited upside.",
        })
        assert res.ok is False
        assert res.status == STATUS_BLOCKED

    def test_severity_counts_are_reported(self):
        res = validate_thesis_integrity(self._thesis(claims=[
            _claim(provenance="reported", source=None, ticker="X"),
        ]))
        counts = res.severity_counts()
        assert counts["high"] >= 1
        assert set(counts) == {"high", "medium", "low"}


# ── 6. Threshold unit inference ──────────────────────────────────────────────

class TestThresholdUnits:
    @pytest.mark.parametrize("metric,expected", [
        ("Vehicle Deliveries", "vehicles"),
        ("ASP of Model 3/Y", "USD"),
        ("EUV System Shipments", "systems"),
        ("Quarterly EUV Shipments", "systems/quarter"),
        ("737 MAX Monthly Production Rate", "aircraft/month"),
        ("Brent Crude Price", "USD/bbl"),
    ])
    def test_sprint_2a_missing_units_are_inferred(self, metric, expected):
        """The exact 7 metrics that produced `threshold_missing_unit` in the
        Sprint 2A benchmark."""
        assert infer_unit(metric) == expected

    def test_ambiguous_metric_gets_no_invented_unit(self):
        assert infer_unit("Competitive Positioning") is None
        assert infer_unit("Management Execution") is None
        assert infer_unit("") is None

    def test_inference_fills_unit_on_a_parsed_band(self):
        r = parse_threshold_zone(
            {"metric": "Vehicle Deliveries", "bull_threshold": ">1800000",
             "bear_threshold": "<1500000"}, ticker="TSLA",
        )
        assert r["unavailable"] is False
        assert r["unit"] == "vehicles"
        assert r["unit_inferred"] is True

    def test_explicit_unit_is_never_overridden(self):
        r = parse_threshold_zone(
            {"metric": "Vehicle Deliveries", "bull_threshold": ">20%",
             "bear_threshold": "<10%"}, ticker="TSLA",
        )
        assert r["unit"] == "%"
        assert r["unit_inferred"] is False

    def test_word_units_render_with_a_space(self):
        r = parse_threshold_zone(
            {"metric": "Brent Crude Price", "bull_threshold": ">85",
             "bear_threshold": "<60"}, ticker="XOM",
        )
        assert "85.0 USD/bbl" in r["display"]

    def test_unit_missing_reason_is_explicit(self):
        # Parses cleanly, but nothing about "Revenue Growth" implies a unit.
        r = parse_threshold_zone(
            {"metric": "Revenue Growth", "bull_threshold": ">25",
             "bear_threshold": "<15"}, ticker="X",
        )
        assert r["unavailable"] is False
        assert r["unit"] is None
        assert r["unit_missing_reason"]


# ── 7. Threshold validity must not regress ───────────────────────────────────

class TestThresholdValidityPreserved:
    def test_visa_overlap_still_rejected(self):
        # The Sprint 1B/1C Visa overlap protection.
        r = parse_threshold_zone(
            {"metric": "Forward P/E", "bull_threshold": "<31x",
             "bear_threshold": ">28x"}, ticker="V",
        )
        assert r["unavailable"] is True
        assert r["reason"]

    def test_visa_non_overlapping_band_still_accepted(self):
        r = parse_threshold_zone(
            {"metric": "Forward P/E", "bull_threshold": "<20x",
             "bear_threshold": ">28x"}, ticker="V",
        )
        assert r["unavailable"] is False

    def test_lower_is_better_direction_preserved(self):
        r = parse_threshold_zone(
            {"metric": "Forward P/E", "bull_threshold": "<20x",
             "bear_threshold": ">28x"}, ticker="V",
        )
        assert r["direction"] == "lower_is_better"

    def test_higher_is_better_direction_preserved(self):
        r = parse_threshold_zone(
            {"metric": "Revenue Growth", "bull_threshold": ">25%",
             "bear_threshold": "<15%"}, ticker="X",
        )
        assert r["direction"] == "higher_is_better"
        assert r["neutral_interval"] == [15.0, 25.0]

    def test_unparseable_threshold_still_unavailable(self):
        r = parse_threshold_zone(
            {"metric": "Something", "bull_threshold": "strong",
             "bear_threshold": "weak"}, ticker="X",
        )
        assert r["unavailable"] is True

    def test_unit_mismatch_still_unavailable(self):
        r = parse_threshold_zone(
            {"metric": "Growth", "bull_threshold": ">25%",
             "bear_threshold": "<15x"}, ticker="X",
        )
        assert r["unavailable"] is True


# ── 8. Backward compatibility ────────────────────────────────────────────────

class TestBackwardCompatibility:
    def test_claim_dict_keeps_all_sprint_1c_fields(self):
        claims = extract_claims("Growth of 25% is required.", ticker="X")
        d = claims[0].to_dict()
        for key in (
            "value_text", "provenance", "as_of", "confidence", "assumptions",
            "stale", "raw_value", "unit", "source", "source_date_unavailable",
            "ticker", "metric", "derivation", "freshness_status", "rendered",
        ):
            assert key in d, f"missing legacy field {key}"

    def test_new_fields_are_additive(self):
        d = extract_claims("Growth of 25% is required.", ticker="X")[0].to_dict()
        assert "polarity" in d
        assert "assumptions_inferred" in d

    def test_canonicalization_adds_occurrences_without_dropping_fields(self):
        original = _claim()
        out = canonicalize_claims([original])[0]
        for key in original:
            assert key in out
        assert out["occurrences"] == 1

    def test_integrity_result_keeps_ok_and_adds_status(self):
        res = validate_thesis_integrity({"ticker": "X", "expectation_regime": "fair"})
        assert isinstance(res.ok, bool)
        assert res.status in (
            STATUS_CLEAN, STATUS_QUALIFIED, STATUS_DEGRADED, STATUS_BLOCKED,
        )

    def test_extraction_never_raises_on_odd_input(self):
        for text in ("", None, "no numbers here", "%%%", "$", "1", "12345678901234567890"):
            assert isinstance(extract_claims(text or "", ticker="X"), list)
