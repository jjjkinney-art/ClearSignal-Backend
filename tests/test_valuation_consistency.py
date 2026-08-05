"""Sprint 2C — valuation-label consistency and provenance recall.

Grounded in the Sprint 2B production verification run
(`validation/runs/sprint2b-verify`), whose single failing query was
BA-structural_risk: a "Priced Cheap" label shipped against prose reading
"this risk is currently priced in". Fully offline.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrity.claim_extraction import extract_claims
from app.integrity.consistency import (
    HIGH, STATUS_BLOCKED, validate_thesis_integrity,
)
from app.integrity.provenance import Provenance
from app.integrity.valuation_state import (
    ValuationState, from_prose, from_regime, label_for,
)


# ── The exact BA-structural_risk production response ─────────────────────────
# Verbatim from validation/runs/sprint2b-verify/raw_responses/BA-structural_risk.json
BA_STRUCTURAL_RISK = {
    "ticker": "BA",
    "company": "Boeing",
    "expectation_regime": "cheap",
    "valuation_stance": "",
    "valuation_view": (
        "At ~20x forward earnings, the stock already prices in a recovery to "
        "normalized production rates and stable cash flow. Expansion of the "
        "multiple would require consistent production increases and successful "
        "FAA certifications, while any delays could compress the multiple "
        "significantly."
    ),
    "direct_answer": (
        "Boeing's primary structural risk is its reliance on the production rate "
        "of the 737 MAX, which is critical for revenue generation in the "
        "Commercial Airplanes segment. This risk is currently priced in due to "
        "the ongoing FAA production certification challenges and the potential "
        "for capital raises that could dilute earnings."
    ),
    "core_takeaway": (
        "Boeing's stock hinges on its ability to ramp up 737 MAX production "
        "effectively. The market is currently pricing in a recovery, but "
        "execution risks remain high."
    ),
}


class TestBoeingProductionRegression:
    """The exact response that failed the Sprint 2B verification run."""

    def test_prose_is_no_longer_read_as_undetermined(self):
        # Root cause 1: a plain "priced in" substring missed the inflections
        # "already prices in" / "currently pricing in".
        assert from_prose(BA_STRUCTURAL_RISK["valuation_view"]) is ValuationState.FAIR
        assert from_prose(BA_STRUCTURAL_RISK["core_takeaway"]) is ValuationState.FAIR

    def test_direct_answer_is_now_classified(self):
        # Root cause 2: direct_answer was not among the fields the backend
        # classified, and that is where "currently priced in" appeared.
        assert from_prose(BA_STRUCTURAL_RISK["direct_answer"]) is ValuationState.FAIR

    def test_label_is_not_cheap(self):
        res = validate_thesis_integrity(BA_STRUCTURAL_RISK)
        label = res.qualifications.get("price_label")
        assert label != "Priced Cheap"
        assert label == "Fairly Priced"

    def test_regime_is_corrected_to_match_the_label(self):
        res = validate_thesis_integrity(BA_STRUCTURAL_RISK)
        assert res.qualifications.get("expectation_regime") == "fair"

    def test_reconciled_state_is_authoritative(self):
        res = validate_thesis_integrity(BA_STRUCTURAL_RISK)
        assert res.state == "fair"
        assert res.qualifications["price_label"] == label_for(ValuationState.FAIR)


class TestLabelProseAgreement:
    def _thesis(self, **kw):
        base = {"ticker": "X", "company": "X"}
        base.update(kw)
        return base

    def test_cheap_label_with_expensive_prose_blocks(self):
        res = validate_thesis_integrity(self._thesis(
            expectation_regime="cheap",
            valuation_view="The multiple is demanding and the stock looks expensive here.",
        ))
        assert res.ok is False
        assert res.status == STATUS_BLOCKED
        assert any(v.code == "valuation_contradiction" and v.severity == HIGH
                   for v in res.violations)
        assert res.qualifications["price_label"] == "Valuation Unclear"
        assert res.severity_counts()["high"] >= 1

    def test_expensive_label_with_cheap_prose_blocks(self):
        res = validate_thesis_integrity(self._thesis(
            expectation_regime="stretched",
            valuation_view="Deeply undervalued, trading at a discount to intrinsic value "
                           "with a wide margin of safety.",
        ))
        assert res.ok is False
        assert res.status == STATUS_BLOCKED
        assert res.qualifications["price_label"] == "Valuation Unclear"

    def test_fair_label_with_mixed_prose_stays_usable(self):
        res = validate_thesis_integrity(self._thesis(
            expectation_regime="fair",
            valuation_view="Roughly fairly valued; some segments look cheap while "
                           "others carry a premium multiple.",
        ))
        assert res.ok is True
        assert res.status != STATUS_BLOCKED
        assert res.qualifications["price_label"] != "Priced Cheap"

    def test_valid_cheap_response_preserved(self):
        res = validate_thesis_integrity(self._thesis(
            expectation_regime="cheap",
            valuation_view="The shares are undervalued and trade at a clear discount "
                           "to intrinsic value.",
        ))
        assert res.ok is True
        assert res.qualifications["price_label"] == "Priced Cheap"
        assert "expectation_regime" not in res.qualifications

    def test_valid_demanding_response_preserved(self):
        res = validate_thesis_integrity(self._thesis(
            expectation_regime="stretched",
            valuation_view="A demanding multiple that leaves little room for error.",
        ))
        assert res.ok is True
        assert res.qualifications["price_label"] == "Priced Rich"

    def test_stretched_regime_survives_fully_priced_prose(self):
        # The conviction model is more precise than the prose heuristic here;
        # "already prices in" agrees directionally and must not soften it.
        res = validate_thesis_integrity(self._thesis(
            expectation_regime="stretched",
            valuation_view="At 40x the stock already prices in the growth.",
        ))
        assert res.qualifications["price_label"] == "Priced Rich"
        assert "expectation_regime" not in res.qualifications


class TestNegationAndTense:
    """Naive keyword matching must not invent contradictions."""

    @pytest.mark.parametrize("prose", [
        "The stock is not expensive at these levels.",
        "The multiple is less demanding than it was a year ago.",
        "This is no longer stretched after the de-rating.",
        "Valuation is hardly demanding given the growth.",
        "The shares are far from expensive.",
    ])
    def test_negated_expensive_language_is_not_stretched(self, prose):
        assert from_prose(prose) is not ValuationState.STRETCHED

    @pytest.mark.parametrize("prose", [
        "The stock was expensive before the correction.",
        "It had been stretched during the 2021 melt-up.",
        "Historically expensive, the multiple has since normalized.",
        "The name used to be demanding on every metric.",
        "Previously overvalued, it now trades near book.",
    ])
    def test_historical_expensive_language_is_not_current_state(self, prose):
        assert from_prose(prose) is not ValuationState.STRETCHED

    def test_negation_does_not_invert_into_cheap(self):
        # "not expensive" is not a positive claim of cheapness.
        assert from_prose("The stock is not expensive.") is not ValuationState.CHEAP

    def test_no_margin_of_safety_reads_as_stretched(self):
        # The negation belongs to the phrase itself and must not cancel it.
        assert from_prose("There is no margin of safety at this price.") is ValuationState.STRETCHED

    def test_inexpensive_is_not_matched_as_expensive(self):
        assert from_prose("The shares look inexpensive here.") is ValuationState.CHEAP

    def test_negation_does_not_cross_sentence_boundaries(self):
        prose = "Growth is not slowing. The multiple is demanding."
        assert from_prose(prose) is ValuationState.STRETCHED


class TestInflectionCoverage:
    @pytest.mark.parametrize("prose", [
        "The stock already prices in a full recovery.",
        "The market is currently pricing in a recovery.",
        "This risk is currently priced in.",
        "The multiple already reflects the growth.",
        "The shares look fully priced.",
    ])
    def test_fully_priced_inflections_read_as_fair(self, prose):
        assert from_prose(prose) is ValuationState.FAIR

    def test_explicit_expensive_outranks_fully_priced(self):
        # The Sprint 1B MSFT fixture shape: a fully-priced clause must not
        # dilute an explicit "limited upside".
        prose = ("At ~34x forward earnings the multiple already prices Azure "
                 "durability; limited upside without further acceleration.")
        assert from_prose(prose) is ValuationState.STRETCHED


class TestRegimeVocabulary:
    def test_attractive_regime_is_recognised(self):
        # Sprint 2C: 'attractive' is in the conviction modeler's documented
        # vocabulary but was missing from the map, so three benchmark responses
        # degraded to "Valuation Unclear" despite a valid regime.
        assert from_regime("attractive") is ValuationState.CHEAP

    @pytest.mark.parametrize("regime,expected", [
        ("cheap", ValuationState.CHEAP),
        ("attractive", ValuationState.CHEAP),
        ("fair", ValuationState.FAIR),
        ("stretched", ValuationState.STRETCHED),
        ("euphoric", ValuationState.STRETCHED),
        ("bubble", ValuationState.STRETCHED),
    ])
    def test_full_modeler_vocabulary_is_mapped(self, regime, expected):
        assert from_regime(regime) is expected

    def test_unknown_regime_still_degrades_safely(self):
        assert from_regime("wat") is ValuationState.UNDETERMINED
        assert from_regime(None) is ValuationState.UNDETERMINED


# ── Provenance recall (objective 3) ──────────────────────────────────────────

def _freshness(dimension: str, *, tier="fresh", age_days=12, item_count=4):
    return SimpleNamespace(**{
        dimension: SimpleNamespace(tier=tier, age_days=age_days, item_count=item_count)
    })


class TestReportedRecall:
    """REPORTED must be reachable when evidence genuinely binds, and
    unreachable when it does not. The Sprint 2B invariant is not relaxed."""

    def test_sourced_historical_metric_becomes_reported(self):
        claims = extract_claims(
            "Reported revenue grew 14% in the quarter.", ticker="MSFT",
            metric="direct_answer", freshness=_freshness("earnings"),
            dimension="earnings",
        )
        reported = [c for c in claims if c.provenance is Provenance.REPORTED]
        assert reported, "a sourced historical metric must classify as REPORTED"
        assert reported[0].source
        assert reported[0].as_of

    def test_source_with_explicit_date_unavailable_stays_reported(self):
        claims = extract_claims(
            "Reported revenue grew 14% in the quarter.", ticker="MSFT",
            metric="direct_answer",
            freshness=_freshness("earnings", tier="unknown", age_days=None),
            dimension="earnings",
        )
        reported = [c for c in claims if c.provenance is Provenance.REPORTED]
        assert reported
        assert reported[0].source
        assert reported[0].source_date_unavailable is True

    def test_evidence_in_another_dimension_does_not_bind(self):
        """The Sprint 2B-verify defect: the only populated freshness dimension
        was `filing`, and no thesis field maps to it. Evidence that exists
        elsewhere must NOT be borrowed to source an unrelated claim."""
        claims = extract_claims(
            "Reported revenue grew 14% in the quarter.", ticker="MSFT",
            metric="direct_answer",
            freshness=_freshness("filing"),   # evidence exists, but not here
            dimension="earnings",
        )
        for c in claims:
            assert c.provenance is not Provenance.REPORTED
            assert c.source is None

    def test_no_evidence_at_all_downgrades(self):
        claims = extract_claims(
            "Reported revenue grew 14% in the quarter.", ticker="MSFT",
            metric="direct_answer",
            freshness=_freshness("earnings", item_count=0), dimension="earnings",
        )
        assert all(c.provenance is not Provenance.REPORTED for c in claims)

    def test_future_threshold_remains_scenario(self):
        claims = extract_claims(
            "Confirmation would come from growth exceeding 25% in the next "
            "quarterly report.", ticker="NVDA", metric="bull_thesis",
            freshness=_freshness("earnings"), dimension="earnings",
        )
        assert claims
        assert all(c.provenance is not Provenance.REPORTED for c in claims)
        assert any(c.provenance is Provenance.SCENARIO for c in claims)

    def test_upcoming_earnings_call_is_not_a_source(self):
        # Verbatim shape from NVDA-decision_threshold: an "earnings call"
        # reference that points FORWARD must not bind as a source.
        claims = extract_claims(
            "A catalyst could be negative hyperscaler CapEx guidance of 10-15% "
            "in the upcoming earnings call.", ticker="NVDA", metric="bear_thesis",
        )
        for c in claims:
            assert c.provenance is not Provenance.REPORTED

    def test_estimate_remains_estimated(self):
        claims = extract_claims(
            "Consensus estimates put FY27 EPS at $13.20.", ticker="X",
            metric="valuation_view", freshness=_freshness("estimates"),
            dimension="estimates",
        )
        assert any(c.provenance is Provenance.ESTIMATED for c in claims)

    def test_derived_arithmetic_remains_derived(self):
        claims = extract_claims(
            "Annualizing the run-rate translates to $4.8B of revenue.",
            ticker="X", metric="valuation_view", freshness=_freshness("valuation"),
            dimension="valuation",
        )
        assert any(c.provenance is Provenance.DERIVED for c in claims)

    def test_sprint_2b_invariant_holds(self):
        # No prose cue may produce a REPORTED claim without a source.
        for text in (
            "Growth must exceed 25% in the next quarterly report.",
            "Q3 margins reached 31% this fiscal quarter.",
            "The print showed 40% share.",
        ):
            for c in extract_claims(text, ticker="X"):
                if c.provenance is Provenance.REPORTED:
                    assert c.source, f"unsourced REPORTED from {text!r}"
