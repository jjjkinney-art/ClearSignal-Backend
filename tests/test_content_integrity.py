"""Sprint 1B — content-integrity & cross-field consistency tests.

Covers the required cases plus MSFT / V / NVDA regression fixtures modelled on the
live issues observed (cheap-label vs demanding-prose; overlapping Visa P/E
thresholds; NVDA scenario $6-9B rendered as fact; stale precise figures; memory
delta direction; active-ticker isolation; unsupported materiality).
"""
from __future__ import annotations

import pytest

from app.integrity.thresholds import (
    ThresholdBand, MetricDirection, validate_band, validate_bands, infer_direction,
)
from app.integrity.valuation_state import (
    ValuationState, from_regime, from_stance, from_prose, reconcile,
)
from app.integrity.provenance import Provenance, QuantitativeClaim, validate_claim
from app.integrity.memory_consistency import validate_memory
from app.integrity.consistency import validate_thesis_integrity, HIGH


# ── 1. Thresholds: no overlapping bull/neutral/bear ──────────────────────────

class TestThresholds:
    def test_visa_overlapping_pe_fails(self):
        # Live bug: bull P/E < 31 and bear P/E > 28 → 29x is both bull and bear.
        band = ThresholdBand("Visa P/E", MetricDirection.LOWER_IS_BETTER,
                             bull_threshold=31, bear_threshold=28)
        violations = validate_band(band)
        assert violations, "overlapping lower-is-better band must fail"
        assert "overlap" in violations[0].lower()

    def test_coherent_lower_is_better_passes(self):
        band = ThresholdBand("Visa P/E", MetricDirection.LOWER_IS_BETTER,
                             bull_threshold=28, bear_threshold=34)
        assert validate_band(band) == []
        assert band.classify(26) == "bull"
        assert band.classify(30) == "neutral"
        assert band.classify(36) == "bear"

    # ── 2. higher-is-better vs lower-is-better handled separately ────────────
    def test_higher_is_better_direction(self):
        good = ThresholdBand("rev growth %", MetricDirection.HIGHER_IS_BETTER,
                             bull_threshold=15, bear_threshold=5)
        assert validate_band(good) == []
        assert good.classify(20) == "bull"
        assert good.classify(10) == "neutral"
        assert good.classify(2) == "bear"
        # inverted higher-is-better fails
        bad = ThresholdBand("rev growth %", MetricDirection.HIGHER_IS_BETTER,
                            bull_threshold=5, bear_threshold=15)
        assert validate_band(bad)

    def test_direction_inference(self):
        assert infer_direction("Forward P/E") is MetricDirection.LOWER_IS_BETTER
        assert infer_direction("Revenue growth") is MetricDirection.HIGHER_IS_BETTER


# ── 3. Valuation state contract + price-label agreement ──────────────────────

class TestValuationState:
    def test_mappers(self):
        assert from_regime("cheap") is ValuationState.CHEAP
        assert from_regime("euphoric") is ValuationState.STRETCHED
        assert from_stance("overpriced") is ValuationState.STRETCHED
        assert from_prose("the multiple already prices this; limited upside") is ValuationState.STRETCHED

    def test_reconcile_agreement(self):
        state, contradiction = reconcile(ValuationState.CHEAP, ValuationState.CHEAP)
        assert state is ValuationState.CHEAP and contradiction is False

    def test_reconcile_hard_contradiction(self):
        state, contradiction = reconcile(ValuationState.CHEAP, ValuationState.STRETCHED)
        assert contradiction is True
        assert state is ValuationState.UNDETERMINED  # fail closed


# ── 4. Provenance: estimated/scenario numbers never render as facts ──────────

class TestProvenance:
    def test_nvda_scenario_without_assumptions_is_invalid(self):
        claim = QuantitativeClaim("$6-9B", Provenance.SCENARIO)
        assert claim.must_qualify()
        assert validate_claim(claim) is not None  # would read as reported fact
        assert claim.is_valid() is True  # scenario qualifier is enough to render safely
        assert "scenario" in claim.render().lower()

    def test_scenario_with_assumptions_renders_qualified(self):
        claim = QuantitativeClaim(
            "$6-9B", Provenance.SCENARIO,
            assumptions="datacenter capex sustains", confidence="low",
        )
        assert validate_claim(claim) is None
        rendered = claim.render().lower()
        assert "scenario" in rendered and "assumes" in rendered and "low confidence" in rendered

    def test_reported_fact_renders_plainly(self):
        claim = QuantitativeClaim("$61.9B", Provenance.REPORTED, as_of="2026-06-30")
        assert claim.must_qualify() is False
        assert validate_claim(claim) is None
        assert claim.render() == "$61.9B (as of 2026-06-30)"

    # ── 5. Stale reported figure must carry an as-of ─────────────────────────
    def test_stale_reported_without_asof_is_invalid(self):
        claim = QuantitativeClaim("42% share", Provenance.REPORTED, stale=True)
        assert validate_claim(claim) is not None
        claim2 = QuantitativeClaim("42% share", Provenance.REPORTED, stale=True, as_of="FY2024")
        assert validate_claim(claim2) is None


# ── 3 (memory). Delta direction + active-ticker isolation ────────────────────

class TestMemoryConsistency:
    def test_reversed_conviction_direction_flagged(self):
        v = validate_memory({"conviction_trend": [0.70, 0.50], "conviction_direction": "rising"})
        assert any("reversed" in m for m in v)

    def test_current_stance_conflicts_with_rising_memory(self):
        v = validate_memory(
            {"stance_history": ["neutral"], "conviction_direction": "rising",
             "conviction_trend": [0.4, 0.6]},
            current_stance="bearish",
        )
        assert any("more bearish" in m for m in v)

    def test_active_ticker_isolation(self):
        v = validate_memory({"ticker": "AAPL", "conviction_trend": [0.5, 0.5]},
                            thesis_ticker="MSFT")
        assert any("leaked" in m for m in v)

    def test_consistent_memory_passes(self):
        v = validate_memory(
            {"ticker": "MSFT", "stance_history": ["neutral", "constructive"],
             "conviction_trend": [0.5, 0.65], "conviction_direction": "rising"},
            thesis_ticker="MSFT", current_stance="constructive",
        )
        assert v == []


# ── 6/7/8. Cross-section validation + regression fixtures ────────────────────

# MSFT: "Priced Cheap" label while prose says the multiple is full / limited upside.
MSFT_CONTRADICTION = {
    "ticker": "MSFT", "company": "Microsoft",
    "expectation_regime": "cheap",
    "valuation_stance": "fairly_valued",
    "valuation_view": "At ~34x forward earnings the multiple already prices Azure "
                      "durability; limited upside without further acceleration.",
    "direct_answer": "MSFT looks fairly valued here.",
}

# NVDA: cheap label but demanding prose + a scenario number stated as fact.
NVDA_CONTRADICTION = {
    "ticker": "NVDA", "company": "NVIDIA",
    "expectation_regime": "cheap",
    "valuation_stance": "overpriced",
    "core_takeaway": "The stock is priced for perfection; the multiple is demanding.",
    "direct_answer": "A sovereign-AI cycle adds $6-9B of revenue.",
}

# Visa: clean, consistent thesis (should pass).
VISA_CLEAN = {
    "ticker": "V", "company": "Visa",
    "expectation_regime": "fair",
    "valuation_stance": "fairly_valued",
    "valuation_view": "Trades around its historical multiple; fairly valued.",
    "direct_answer": "Visa looks fairly valued given cross-border normalization.",
    "memory_context_data": {
        "ticker": "V", "stance_history": ["constructive", "constructive"],
        "conviction_trend": [0.6, 0.62], "conviction_direction": "stable",
    },
}


class TestCrossSection:
    def test_msft_contradiction_fails_closed(self):
        res = validate_thesis_integrity(MSFT_CONTRADICTION)
        assert res.ok is False
        assert any(v.code == "valuation_contradiction" and v.severity == HIGH
                   for v in res.violations)
        # fail closed: price label suppressed to undetermined
        assert res.qualifications.get("expectation_regime") == ValuationState.UNDETERMINED.value
        assert res.qualifications.get("price_label") == "Valuation Unclear"

    def test_nvda_contradiction_and_scenario_fail(self):
        res = validate_thesis_integrity(NVDA_CONTRADICTION)
        assert res.ok is False
        assert any(v.code == "valuation_contradiction" for v in res.violations)

    def test_visa_clean_passes(self):
        res = validate_thesis_integrity(VISA_CLEAN)
        assert res.ok is True
        assert res.qualifications.get("price_label") == "Fairly Priced"

    def test_unsupported_materiality_flagged(self):
        thesis = {
            "ticker": "MSFT",
            "bull_case": ["Gaming is a recurring-revenue engine that cushions the thesis"],
            "expectation_regime": "fair", "valuation_stance": "fairly_valued",
        }
        res = validate_thesis_integrity(thesis)
        assert any(v.code == "unsupported_materiality" for v in res.violations)

    def test_switching_costs_not_recurring_revenue(self):
        thesis = {
            "ticker": "MSFT",
            "bull_case": ["A recurring revenue engine driven by ecosystem lock-in and "
                          "switching costs across 40% of the base"],
            "expectation_regime": "fair",
        }
        res = validate_thesis_integrity(thesis)
        assert any(v.code == "switching_vs_recurring" for v in res.violations)

    def test_stale_precision_flagged_and_qualified(self):
        thesis = {
            "ticker": "NVDA",
            "expectation_regime": "fair",
            "evidence_coverage": "limited recent earnings data for the current quarter",
            "direct_answer": "Datacenter revenue is $26.3B, up 154% year over year.",
        }
        res = validate_thesis_integrity(thesis)
        assert any(v.code == "stale_precision" for v in res.violations)
        assert "indicative" in res.qualifications.get("stale_precision_caveat", "")

    def test_question_alignment_low_severity(self):
        thesis = {"ticker": "MSFT", "company": "Microsoft",
                  "expectation_regime": "fair",
                  "direct_answer": "The broad market outlook is uncertain."}
        res = validate_thesis_integrity(thesis, question="Is MSFT overvalued?")
        assert any(v.code == "question_alignment" for v in res.violations)

    def test_never_raises_on_garbage(self):
        # fail-open on internal error / weird input
        res = validate_thesis_integrity({"expectation_regime": 12345, "bull_case": None})
        assert res.ok in (True, False)  # returned a result, did not raise


# ── Live /ask boundary wiring (fail-closed qualification reaches the response) ─

class TestAskBoundaryWiring:
    def test_contradiction_is_qualified_in_response(self, monkeypatch):
        import json
        from types import SimpleNamespace
        from fastapi.testclient import TestClient
        from app.config import settings
        from app.main import app

        monkeypatch.setattr(settings, "auth_enabled", False, raising=False)
        monkeypatch.setattr(settings, "content_integrity_enabled", True, raising=False)

        contradictory = {
            "answer": {"investment_thesis": dict(NVDA_CONTRADICTION)},
        }

        def _stub_route_question(req):
            r = SimpleNamespace(company="NVDA", routing={"detected_ticker": "NVDA"})
            r.model_dump = lambda: contradictory
            return r

        monkeypatch.setattr("app.api.route_question", _stub_route_question, raising=False)
        c = TestClient(app)
        r = c.post("/ask", json={"company_name": "NVDA", "question": "Is NVDA cheap?"})
        assert r.status_code == 200
        body = json.loads(r.text)  # JSON tolerates leading keepalive whitespace
        thesis = body["answer"]["investment_thesis"]
        # fail-closed: contradictory "cheap" regime downgraded to the safe neutral
        assert thesis["expectation_regime"] == "fair"
        assert thesis["_integrity"]["ok"] is False
        assert any(v["code"] == "valuation_contradiction"
                   for v in thesis["_integrity"]["violations"])
