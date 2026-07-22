"""Sprint 1C — structured provenance & threshold generation at source.

Covers required tests A (quantitative claims), B (thresholds), C (integration),
plus MSFT / Visa / NVDA regression fixtures. Uses only the pipeline's real,
production modules (app/integrity/claim_extraction.py, threshold_parsing.py,
thesis_wiring.py) — no LLM/network calls; the LLM-facing pieces (agents,
thesis_synthesizer) are exercised through a fake FreshnessProfile-shaped object
and plain thesis-like objects so the wiring itself is genuinely verified.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrity.provenance import Provenance, QuantitativeClaim, validate_claim, validate_claim_sourced
from app.integrity.claim_extraction import extract_claims, attach_agent_claims
from app.integrity.threshold_parsing import parse_threshold_zone, build_decision_thresholds
from app.integrity.thesis_wiring import attach_structured_content
from app.integrity.thresholds import MetricDirection


def _dim(tier, age_days=None, item_count=1):
    return SimpleNamespace(tier=tier, age_days=age_days, item_count=item_count)


def _freshness(**dims):
    base = dict(earnings=_dim("unknown"), filing=_dim("unknown"),
               estimates=_dim("unknown"), valuation=_dim("unknown"), macro=_dim("unknown"))
    base.update(dims)
    return SimpleNamespace(dominant_stale_dimension=None, has_any_evidence=True, **base)


# ── A. Quantitative claim tests ──────────────────────────────────────────────

class TestQuantitativeClaimsA:
    def test_reported_with_source_and_date_passes(self):
        c = QuantitativeClaim("$61.9B", Provenance.REPORTED, as_of="2026-06-30", source="10-Q")
        assert validate_claim(c) is None
        assert validate_claim_sourced(c) is None

    def test_reported_without_source_metadata_fails_strict(self):
        c = QuantitativeClaim("$61.9B", Provenance.REPORTED, as_of="2026-06-30")  # no source
        assert validate_claim_sourced(c) is not None  # source required under strict check
        # Sprint 1B's original (non-strict) validator is unaffected:
        assert validate_claim(c) is None

    def test_reported_source_no_date_fails_unless_marked_unavailable(self):
        c = QuantitativeClaim("42%", Provenance.REPORTED, source="10-K")
        assert validate_claim_sourced(c) is not None
        c2 = QuantitativeClaim("42%", Provenance.REPORTED, source="10-K", source_date_unavailable=True)
        assert validate_claim_sourced(c2) is None

    def test_derived_claim_requires_derivation(self):
        c = QuantitativeClaim("3.2x", Provenance.DERIVED)
        assert validate_claim(c) is not None
        c2 = QuantitativeClaim("3.2x", Provenance.DERIVED, derivation="EV / trailing EBITDA")
        assert validate_claim(c2) is None

    def test_estimated_and_scenario_require_assumptions_and_confidence(self):
        c = QuantitativeClaim("$6-9B", Provenance.SCENARIO)
        assert validate_claim(c) is not None
        c2 = QuantitativeClaim("$6-9B", Provenance.SCENARIO, assumptions="capex sustains", confidence="low")
        assert validate_claim(c2) is None

    def test_heuristic_claims_render_visibly_qualified(self):
        c = QuantitativeClaim("42%", Provenance.HEURISTIC)
        assert c.must_qualify() is True
        assert "rule-of-thumb" in c.render().lower()

    def test_unsupported_precision_extraction_is_heuristic_and_qualified(self):
        # A number with no scenario/estimate/derive/report cue nearby.
        claims = extract_claims("The number 42% appears here with no context clue at all.")
        assert claims and claims[0].provenance is Provenance.HEURISTIC
        assert "rule-of-thumb" in claims[0].render().lower()

    def test_stale_claim_carries_as_of_and_stale_status(self):
        fresh = _freshness(valuation=_dim("stale", age_days=190, item_count=2))
        claims = extract_claims(
            "Reported gross margin of 68% per the 10-Q for the quarter.",
            ticker="MSFT", freshness=fresh, dimension="valuation",
        )
        reported = [c for c in claims if c.provenance is Provenance.REPORTED]
        assert reported
        assert reported[0].stale is True
        assert reported[0].as_of is not None  # carries the age-based as-of marker
        assert reported[0].freshness_status == "stale"

    def test_claims_carry_ticker_and_do_not_leak(self):
        claims = extract_claims("Reported revenue of $61.9B per the 10-Q.", ticker="MSFT")
        assert claims and all(c.ticker == "MSFT" for c in claims)
        claims_v = extract_claims("Reported revenue of $61.9B per the 10-Q.", ticker="V")
        assert all(c.ticker == "V" for c in claims_v)
        assert claims[0].ticker != claims_v[0].ticker

    def test_units_and_metric_name_consistent(self):
        claims = extract_claims("Forward P/E of 31x looks rich versus history.",
                                ticker="V", metric="valuation")
        assert claims
        assert claims[0].unit == "x"
        assert claims[0].metric == "valuation"

    def test_rendered_prose_reflects_structured_claim(self):
        c = QuantitativeClaim("$6-9B", Provenance.SCENARIO, assumptions="capex sustains", confidence="low")
        rendered = c.render()
        assert "$6-9B" in rendered and "scenario" in rendered and "capex sustains" in rendered


# ── B. Threshold tests ───────────────────────────────────────────────────────

class TestThresholdsB:
    def test_higher_is_better_band_coherent(self):
        z = {"metric": "Revenue growth YoY", "bull_threshold": ">25%", "bear_threshold": "<15%"}
        r = parse_threshold_zone(z, ticker="NVDA")
        assert r["unavailable"] is False
        assert r["direction"] == MetricDirection.HIGHER_IS_BETTER.value
        assert r["neutral_interval"] == [15.0, 25.0]

    def test_lower_is_better_band_coherent(self):
        z = {"metric": "Forward P/E", "bull_threshold": "<20x", "bear_threshold": ">28x"}
        r = parse_threshold_zone(z, ticker="V")
        assert r["unavailable"] is False
        assert r["direction"] == MetricDirection.LOWER_IS_BETTER.value

    def test_range_target_style_supported_via_direction_fallback(self):
        # No metric-name hint (infer_direction -> None); operators disambiguate.
        z = {"metric": "Same-store sales growth", "bull_threshold": ">4%", "bear_threshold": "<1%"}
        r = parse_threshold_zone(z, ticker="CAVA")
        assert r["unavailable"] is False
        assert r["direction"] == MetricDirection.HIGHER_IS_BETTER.value

    def test_conflicting_thresholds_fail_closed(self):
        # The exact prior Visa bug: bull <31x, bear >28x (lower-is-better overlap).
        z = {"metric": "Forward P/E", "bull_threshold": "<31x", "bear_threshold": ">28x"}
        r = parse_threshold_zone(z, ticker="V")
        assert r["unavailable"] is True
        assert "overlap" in r["reason"]
        assert r["display"] == "Threshold unavailable"

    def test_unit_mismatch_fails_validation(self):
        z = {"metric": "Data center revenue", "bull_threshold": ">$40B", "bear_threshold": "<15%"}
        r = parse_threshold_zone(z, ticker="NVDA")
        assert r["unavailable"] is True
        assert "unit mismatch" in r["reason"]

    def test_missing_or_unparseable_threshold_is_explicit_unavailable(self):
        z = {"metric": "Sentiment", "bull_threshold": "improving", "bear_threshold": "worsening"}
        r = parse_threshold_zone(z, ticker="MSFT")
        assert r["unavailable"] is True
        assert r["display"] == "Threshold unavailable"

    def test_threshold_prose_matches_structured_band(self):
        z = {"metric": "Forward P/E", "bull_threshold": "<20x", "bear_threshold": ">28x"}
        r = parse_threshold_zone(z, ticker="V")
        assert "20.0" in r["display"] and "28.0" in r["display"]

    def test_visa_overlap_is_impossible_to_ship(self):
        zones = [{"metric": "Forward P/E", "bull_threshold": "<31x", "bear_threshold": ">28x"}]
        out = build_decision_thresholds(zones, ticker="V")
        assert all(o["unavailable"] for o in out)

    def test_msft_visa_nvda_fixtures_produce_valid_structured_thresholds(self):
        fixtures = [
            ("MSFT", {"metric": "Azure Revenue Growth YoY", "bull_threshold": ">30%", "bear_threshold": "<20%"}),
            ("V",    {"metric": "Cross-Border Volume Growth YoY", "bull_threshold": ">10%", "bear_threshold": "<3%"}),
            ("NVDA", {"metric": "Data Center Revenue Growth YoY", "bull_threshold": ">25%", "bear_threshold": "<15%"}),
        ]
        for ticker, zone in fixtures:
            r = parse_threshold_zone(zone, ticker=ticker)
            assert r["unavailable"] is False, f"{ticker} fixture should be valid: {r}"


# ── C. Integration tests ─────────────────────────────────────────────────────

def _fake_thesis(**overrides):
    fields = dict(
        direct_answer="", bull_thesis="", bear_thesis="", valuation_view="",
        macro_sensitivity="", conclusion="", what_changed=[], threshold_zones=[],
        quantitative_claims=[], decision_thresholds=[], claim_provenance_summary={},
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


class TestIntegrationC:
    def test_attach_structured_content_populates_claims_and_thresholds(self):
        thesis = _fake_thesis(
            direct_answer="A sovereign-AI cycle adds $6-9B of revenue if capex accelerates.",
            valuation_view="At ~34x forward earnings the multiple already prices Azure durability.",
            threshold_zones=[
                {"metric": "Data Center Revenue Growth YoY", "bull_threshold": ">25%",
                 "bear_threshold": "<15%", "rationale": "validates hyperscaler capex durability"},
            ],
        )
        attach_structured_content(thesis, ticker="NVDA", evidence=[])
        assert thesis.quantitative_claims, "expected extracted claims"
        assert thesis.decision_thresholds and thesis.decision_thresholds[0]["unavailable"] is False
        assert isinstance(thesis.claim_provenance_summary, dict) and thesis.claim_provenance_summary

    def test_scenario_estimate_explicitly_marked_scenario(self):
        thesis = _fake_thesis(
            direct_answer="A sovereign-AI cycle adds $6-9B of revenue if hyperscaler capex accelerates."
        )
        attach_structured_content(thesis, ticker="NVDA", evidence=[])
        scenario_claims = [c for c in thesis.quantitative_claims if c["provenance"] == "scenario"]
        assert scenario_claims
        assert scenario_claims[0]["assumptions"]

    def test_stale_valuation_figure_is_qualified_with_as_of(self):
        thesis = _fake_thesis(
            valuation_view="Reported gross margin of 68% for the quarter.",
        )
        freshness = _freshness(valuation=_dim("very_stale", age_days=400, item_count=1))
        attach_structured_content(thesis, ticker="MSFT", evidence=None, freshness=freshness)
        reported = [c for c in thesis.quantitative_claims if c["provenance"] == "reported"]
        assert reported
        assert reported[0]["stale"] is True
        assert reported[0]["as_of"] is not None

    def test_agent_claims_merged_into_thesis(self):
        thesis = _fake_thesis()
        agent_claims = [QuantitativeClaim("$40B", Provenance.ESTIMATED, assumptions="street model",
                                          confidence="medium").to_dict()]
        attach_structured_content(thesis, ticker="NVDA", evidence=[], agent_claims=agent_claims)
        assert any(c["value_text"] == "$40B" for c in thesis.quantitative_claims)

    def test_claims_do_not_leak_across_tickers(self):
        thesis_a = _fake_thesis(direct_answer="Reported revenue of $61.9B per the 10-Q.")
        thesis_b = _fake_thesis(direct_answer="Reported revenue of $35.8B per the 10-Q.")
        attach_structured_content(thesis_a, ticker="MSFT", evidence=[])
        attach_structured_content(thesis_b, ticker="V", evidence=[])
        assert all(c["ticker"] == "MSFT" for c in thesis_a.quantitative_claims)
        assert all(c["ticker"] == "V" for c in thesis_b.quantitative_claims)

    def test_never_raises_and_degrades_to_empty(self):
        class Weird:
            direct_answer = 12345  # wrong type on purpose
            bull_thesis = None
            bear_thesis = None
            valuation_view = None
            macro_sensitivity = None
            conclusion = None
            what_changed = None
            threshold_zones = None
            quantitative_claims = []
            decision_thresholds = []
            claim_provenance_summary = {}
        w = Weird()
        attach_structured_content(w, ticker="X", evidence=[])  # must not raise
        assert w.quantitative_claims == [] or isinstance(w.quantitative_claims, list)

    def test_agent_level_attach_agent_claims_helper(self):
        view = SimpleNamespace(overall="Reported operating margin of 42% per the 10-K.",
                               signals=[], quantitative_claims=[])
        attach_agent_claims(view, ticker="MSFT", dimension="valuation", metric="valuation")
        assert view.quantitative_claims
        assert view.quantitative_claims[0]["ticker"] == "MSFT"


# ── Live /ask boundary still works with structured payloads present ──────────

class TestBoundaryCompatibility:
    def test_boundary_validator_tolerates_new_structured_fields(self):
        from app.integrity.consistency import validate_thesis_integrity
        thesis = {
            "ticker": "V", "company": "Visa",
            "expectation_regime": "fair", "valuation_stance": "fairly_valued",
            "quantitative_claims": [
                QuantitativeClaim("$6-9B", Provenance.SCENARIO, assumptions="x", confidence="low").to_dict()
            ],
            "decision_thresholds": [
                {"metric": "Forward P/E", "unavailable": True, "reason": "overlap"}
            ],
        }
        res = validate_thesis_integrity(thesis)
        assert res.ok is True  # existing Sprint 1B boundary behavior unaffected

    def test_boundary_catches_claim_ticker_leak_as_final_safety_net(self):
        from app.integrity.consistency import validate_thesis_integrity
        thesis = {
            "ticker": "MSFT",
            "expectation_regime": "fair",
            "quantitative_claims": [
                QuantitativeClaim("$6B", Provenance.REPORTED, as_of="2026-01-01",
                                  ticker="AAPL").to_dict()  # wrong ticker leaked in
            ],
        }
        res = validate_thesis_integrity(thesis)
        assert res.ok is False
        assert any(v.code == "claim_ticker_leak" for v in res.violations)

    def test_boundary_catches_shipped_incoherent_threshold(self):
        from app.integrity.consistency import validate_thesis_integrity
        thesis = {
            "ticker": "V",
            "expectation_regime": "fair",
            "decision_thresholds": [
                {"metric": "Forward P/E", "unavailable": False, "direction": "lower_is_better",
                 "bull_boundary": 31, "bear_boundary": 28},  # a bug that slipped past the source check
            ],
        }
        res = validate_thesis_integrity(thesis)
        assert res.ok is False
        assert any(v.code == "threshold_contradiction" for v in res.violations)

    def test_boundary_allows_unavailable_threshold_through(self):
        from app.integrity.consistency import validate_thesis_integrity
        thesis = {
            "ticker": "V", "expectation_regime": "fair",
            "decision_thresholds": [{"metric": "Forward P/E", "unavailable": True, "reason": "overlap"}],
        }
        res = validate_thesis_integrity(thesis)
        assert res.ok is True


class TestLiveAskResponseIncludesStructuredPayloads:
    """C-1/C-2/C-3: the live /ask response carries the new companion payloads
    (via InvestmentThesis.model_dump(), no api.py boundary change needed) AND
    the existing readable fields + Sprint 1B _integrity block remain present."""

    def test_ask_response_includes_claims_thresholds_and_integrity(self, monkeypatch):
        import json
        from types import SimpleNamespace as SNS
        from fastapi.testclient import TestClient
        from app.config import settings
        from app.main import app

        monkeypatch.setattr(settings, "auth_enabled", False, raising=False)
        monkeypatch.setattr(settings, "content_integrity_enabled", True, raising=False)

        thesis_payload = {
            "ticker": "NVDA", "company": "NVIDIA",
            "expectation_regime": "fair", "valuation_stance": "overpriced",
            "direct_answer": "Datacenter capex sensitivity is the key driver here.",
            "bull_thesis": "Bull case narrative.", "bear_thesis": "Bear case narrative.",
            "quantitative_claims": [
                QuantitativeClaim("$6-9B", Provenance.SCENARIO, assumptions="capex sustains",
                                  confidence="low", ticker="NVDA").to_dict()
            ],
            "decision_thresholds": [
                {"metric": "Data Center Revenue Growth YoY", "unavailable": False,
                 "direction": "higher_is_better", "bull_boundary": 25, "bear_boundary": 15,
                 "neutral_interval": [15, 25], "unit": "%"}
            ],
            "claim_provenance_summary": {"scenario": 1},
        }

        def _stub_route_question(req):
            r = SNS(company="NVDA", routing={"detected_ticker": "NVDA"})
            r.model_dump = lambda: {"answer": {"investment_thesis": dict(thesis_payload)}}
            return r

        monkeypatch.setattr("app.api.route_question", _stub_route_question, raising=False)
        c = TestClient(app)
        r = c.post("/ask", json={"company_name": "NVDA", "question": "How capex-sensitive is NVDA?"})
        assert r.status_code == 200
        thesis = json.loads(r.text)["answer"]["investment_thesis"]

        # New structured companion payloads present:
        assert thesis["quantitative_claims"][0]["provenance"] == "scenario"
        assert thesis["decision_thresholds"][0]["unavailable"] is False
        assert thesis["claim_provenance_summary"] == {"scenario": 1}
        # Existing readable frontend fields still present (no frontend change required):
        assert thesis["direct_answer"] == "Datacenter capex sensitivity is the key driver here."
        assert thesis["bull_thesis"] == "Bull case narrative."
        # Sprint 1B boundary validator still runs and is compatible:
        assert "_integrity" in thesis
        assert thesis["_integrity"]["ok"] is True  # clean fixture, no contradiction


# ── MSFT / Visa / NVDA live regression fixtures ───────────────────────────────

class TestLiveRegressionFixtures:
    def test_msft_azure_growth_claim_has_provenance_and_as_of(self):
        fresh = _freshness(earnings=_dim("moderate", age_days=45, item_count=3))
        claims = extract_claims(
            "Reported Azure revenue growth of 33% for the quarter per the 10-Q.",
            ticker="MSFT", freshness=fresh, dimension="earnings",
        )
        reported = [c for c in claims if c.provenance is Provenance.REPORTED]
        assert reported and reported[0].as_of is not None

    def test_msft_priced_cheap_cannot_coexist_with_demanding_prose_unqualified(self):
        from app.integrity.consistency import validate_thesis_integrity
        thesis = {
            "ticker": "MSFT", "expectation_regime": "cheap", "valuation_stance": "fairly_valued",
            "valuation_view": "At ~34x forward earnings the multiple already prices Azure "
                              "durability; limited upside without further acceleration.",
        }
        res = validate_thesis_integrity(thesis)
        assert res.ok is False
        assert res.qualifications["expectation_regime"] == "undetermined"

    def test_visa_pe_bands_non_overlapping_after_fix(self):
        z = {"metric": "Forward P/E", "bull_threshold": "<20x", "bear_threshold": ">28x"}
        r = parse_threshold_zone(z, ticker="V")
        assert r["unavailable"] is False

    def test_visa_cross_border_scenario_vs_reported_distinguished(self):
        claims = extract_claims(
            "Cross-border volume could reach 15% growth if travel recovery continues, "
            "while reported net revenue grew 11% per the 10-Q this quarter.",
            ticker="V",
        )
        provs = {c.provenance for c in claims}
        assert Provenance.SCENARIO in provs
        assert Provenance.REPORTED in provs

    def test_nvda_hyperscaler_capex_is_scenario_or_derived_not_bare_fact(self):
        claims = extract_claims(
            "A sovereign-AI cycle adds $6-9B of revenue if hyperscaler capex accelerates.",
            ticker="NVDA",
        )
        assert claims and claims[0].provenance in (Provenance.SCENARIO, Provenance.ESTIMATED, Provenance.DERIVED)
        assert claims[0].provenance is not Provenance.REPORTED

    def test_nvda_cuda_recurring_revenue_requires_anchor(self):
        from app.integrity.consistency import validate_thesis_integrity
        thesis = {
            "ticker": "NVDA",
            "bull_case": ["CUDA/NIM software is a recurring-revenue engine that cushions the thesis"],
            "expectation_regime": "fair",
        }
        res = validate_thesis_integrity(thesis)
        assert any(v.code == "unsupported_materiality" for v in res.violations)

    def test_nvda_datacenter_and_valuation_bands_coherent(self):
        zones = [
            {"metric": "Data Center Revenue Growth YoY", "bull_threshold": ">25%", "bear_threshold": "<15%"},
            {"metric": "Forward P/E", "bull_threshold": "<35x", "bear_threshold": ">55x"},
        ]
        out = build_decision_thresholds(zones, ticker="NVDA")
        assert all(o["unavailable"] is False for o in out)
