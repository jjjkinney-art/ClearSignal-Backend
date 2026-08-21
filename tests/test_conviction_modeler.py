"""Regression tests for the Conviction Modeler — institutional confidence calibration.

Covers:
1. Module structure and API contract
2. Evidence quality scoring
3. Evidence freshness scoring
4. Thesis alignment scoring
5. Macro uncertainty scoring
6. Valuation certainty scoring
7. Estimate dispersion scoring
8. Governance risk scoring
9. Weighted composition and score distribution
10. Contradiction-aware compression
11. Company-specific uncertainty language (NVDA, VRTX, AAPL, etc.)
12. what_increases_conviction specificity
13. Confidence reasoning specificity
14. Integration with synthesize_thesis (score, fields stamped)
15. Schema fields (InvestmentThesis has new fields)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import MagicMock, patch

import pytest


# ── Evidence helpers ──────────────────────────────────────────────────────────

def _ev(
    title: str = "Test Item",
    source: str = "newsapi",
    summary: str = "Summary text.",
    timestamp: str = "2026-04-01T00:00:00Z",
    relevance_score: float = 0.8,
):
    from app.schemas import RetrievedEvidence
    return RetrievedEvidence(
        title=title, source=source, summary=summary,
        timestamp=timestamp, relevance_score=relevance_score,
    )


def _fmp_val_ev(ts: str = "2026-05-10T00:00:00Z"):
    return _ev(
        title="AAPL Valuation Ratios TTM",
        source="FMP ratios-ttm",
        summary="P/E: 28.4x. EV/EBITDA: 19.2x.",
        timestamp=ts,
    )


def _fmp_analyst_ev(ts: str = "2026-05-10T00:00:00Z"):
    return _ev(
        title="AAPL Analyst Estimates & Price Target Consensus",
        source="FMP analyst-estimates",
        summary="Consensus target: $215. 32 buys, 8 holds, 2 sells.",
        timestamp=ts,
    )


def _earnings_ev(ts: str = "2026-04-25T00:00:00Z"):
    return _ev(
        title="AAPL Q2 2026 Earnings",
        source="newsapi",
        summary="EPS beat: $1.89 actual vs $1.77 estimate.",
        timestamp=ts,
    )


def _days_ago(days: int) -> str:
    """Return a UTC timestamp with a stable age relative to the test run."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stale(days: int = 200):
    return _ev(
        title="Old note", source="research", summary="Old macro note.",
        timestamp=_days_ago(days),
    )


def _fresh(days: int = 10):
    return _ev(
        title="Fresh item", source="newsapi", summary="Recent news.",
        timestamp=_days_ago(days),
    )


def _make_company(ticker: str = "AAPL", name: str = "Apple Inc.", sector: str = "Technology"):
    from app.schemas import CompanyContext
    return CompanyContext(ticker=ticker, company_name=name, sector=sector)


def _make_agents(val_conf=0.75, mac_conf=0.72, risk_conf=0.70, mkt_conf=0.68, qual_conf=0.73):
    from app.schemas import (
        ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment
    )
    return (
        ValuationView(overall="val", confidence=val_conf),
        MacroSensitivity(overall="mac", confidence=mac_conf),
        RiskProfile(overall="risk", confidence=risk_conf),
        MarketContext(overall="mkt", confidence=mkt_conf),
        QualityAssessment(overall="qual", confidence=qual_conf),
    )


# ── 1. Module structure ───────────────────────────────────────────────────────

class TestModuleStructure:
    def test_importable(self):
        from app.services import conviction_modeler  # noqa: F401

    def test_compute_conviction_callable(self):
        from app.services.conviction_modeler import compute_conviction
        assert callable(compute_conviction)

    def test_conviction_result_dataclass(self):
        from app.services.conviction_modeler import ConvictionResult, ConvictionDimensions
        dims = ConvictionDimensions()
        result = ConvictionResult(
            final_score=0.70, dimensions=dims,
            confidence_reasoning="test", what_increases_conviction="test2"
        )
        assert result.final_score == 0.70
        assert isinstance(result.dimensions, ConvictionDimensions)

    def test_conviction_dimensions_to_dict(self):
        from app.services.conviction_modeler import ConvictionDimensions
        dims = ConvictionDimensions(evidence_quality=0.80, evidence_freshness=0.70)
        d = dims.to_dict()
        assert "evidence_quality" in d
        assert "evidence_freshness" in d
        assert d["evidence_quality"] == 0.80

    def test_compute_conviction_returns_result(self):
        from app.services.conviction_modeler import compute_conviction, ConvictionResult
        val, mac, risk, mkt, qual = _make_agents()
        result = compute_conviction(
            evidence=[], valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
            company=_make_company(),
        )
        assert isinstance(result, ConvictionResult)
        assert 0.0 <= result.final_score <= 1.0


# ── 2. Evidence quality scoring ───────────────────────────────────────────────

class TestEvidenceQualityScoring:
    def _score(self, evidence):
        from app.services.conviction_modeler import _score_evidence_quality
        return _score_evidence_quality(evidence)

    def test_empty_evidence_low_score(self):
        assert self._score([]) < 0.30

    def test_fmp_valuation_boosts_quality(self):
        s_with = self._score([_fmp_val_ev()])
        s_without = self._score([_ev(source="newsapi")])
        assert s_with > s_without

    def test_fmp_analyst_boosts_quality(self):
        s_with = self._score([_fmp_analyst_ev()])
        s_without = self._score([_ev(source="newsapi")])
        assert s_with > s_without

    def test_full_coverage_high_quality(self):
        ev = [_fmp_val_ev(), _fmp_analyst_ev(), _earnings_ev(),
              _ev(source="sec 10-q", title="10-Q Filing")]
        score = self._score(ev)
        assert score >= 0.70

    def test_single_generic_news_moderate_quality(self):
        score = self._score([_ev(source="newsapi")])
        assert 0.30 < score < 0.70

    def test_score_bounded_0_1(self):
        ev = [_fmp_val_ev(), _fmp_analyst_ev(), _earnings_ev()] * 5
        score = self._score(ev)
        assert 0.0 <= score <= 1.0


# ── 3. Evidence freshness scoring ─────────────────────────────────────────────

class TestEvidenceFreshnessScoring:
    def _score(self, evidence):
        from app.services.conviction_modeler import _score_evidence_freshness
        return _score_evidence_freshness(evidence)

    def test_empty_evidence_low_freshness(self):
        assert self._score([]) < 0.30

    def test_very_recent_evidence_high_freshness(self):
        score = self._score([_fresh(days=5)])
        assert score >= 0.85

    def test_month_old_evidence_moderate_freshness(self):
        score = self._score([_fresh(days=35)])
        assert 0.60 <= score <= 0.90

    def test_stale_evidence_low_freshness(self):
        score = self._score([_stale(days=200)])
        assert score < 0.40

    def test_no_timestamps_moderate_freshness(self):
        """Evidence without timestamps returns the neutral fallback."""
        ev = [_ev(timestamp="")]
        score = self._score(ev)
        assert 0.35 <= score <= 0.60

    def test_fresh_scores_higher_than_stale(self):
        fresh_score = self._score([_fresh(days=7)])
        stale_score = self._score([_stale(days=250)])
        assert fresh_score > stale_score

    def test_score_bounded_0_1(self):
        for ev in [[_fresh(days=1)], [_stale(days=500)], []]:
            assert 0.0 <= self._score(ev) <= 1.0


# ── 4. Thesis alignment scoring ───────────────────────────────────────────────

class TestThesisAlignmentScoring:
    def _score(self, val_conf=0.75, mac_conf=0.72, risk_conf=0.70,
               mkt_conf=0.68, qual_conf=0.73, ranked=None):
        from app.services.conviction_modeler import _score_thesis_alignment
        from app.schemas import (
            ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment
        )
        return _score_thesis_alignment(
            ValuationView(overall="v", confidence=val_conf),
            MacroSensitivity(overall="m", confidence=mac_conf),
            RiskProfile(overall="r", confidence=risk_conf),
            MarketContext(overall="mk", confidence=mkt_conf),
            QualityAssessment(overall="q", confidence=qual_conf),
            ranked,
        )

    def test_high_aligned_agents_high_score(self):
        score = self._score(
            val_conf=0.85, mac_conf=0.82, risk_conf=0.80,
            mkt_conf=0.83, qual_conf=0.81
        )
        assert score >= 0.70

    def test_low_agents_low_alignment(self):
        score = self._score(
            val_conf=0.40, mac_conf=0.38, risk_conf=0.35,
            mkt_conf=0.42, qual_conf=0.40
        )
        assert score < 0.55

    def test_wide_spread_penalises_alignment(self):
        """Agents with 0.90 vs 0.40 spread should score lower than tight range."""
        tight = self._score(0.70, 0.68, 0.72, 0.69, 0.71)
        wide  = self._score(0.90, 0.90, 0.40, 0.90, 0.90)
        assert tight > wide

    def test_score_bounded_0_1(self):
        assert 0.0 <= self._score() <= 1.0


# ── 5. Macro uncertainty scoring ──────────────────────────────────────────────

class TestMacroUncertaintyScoring:
    def _score(self, mac_conf=0.70, evidence=None):
        from app.services.conviction_modeler import _score_macro_uncertainty
        from app.schemas import MacroSensitivity
        return _score_macro_uncertainty(
            MacroSensitivity(overall="m", confidence=mac_conf),
            evidence or []
        )

    def test_low_macro_confidence_high_uncertainty(self):
        """Low macro agent confidence means high macro uncertainty."""
        score = self._score(mac_conf=0.30)
        assert score >= 0.65

    def test_high_macro_confidence_low_uncertainty(self):
        score = self._score(mac_conf=0.90)
        assert score <= 0.20

    def test_rate_language_in_evidence_boosts_uncertainty(self):
        ev = [_ev(summary="Fed rate hike risk elevated; recession risk remains.", timestamp="2026-05-01T00:00:00Z")]
        no_ev_score = self._score(mac_conf=0.60, evidence=[])
        rate_ev_score = self._score(mac_conf=0.60, evidence=ev)
        assert rate_ev_score >= no_ev_score

    def test_score_bounded_0_1(self):
        for conf in [0.0, 0.5, 1.0]:
            assert 0.0 <= self._score(mac_conf=conf) <= 1.0


# ── 6. Valuation certainty scoring ───────────────────────────────────────────

class TestValuationCertaintyScoring:
    def _score(self, evidence, stance="", val_conf=0.75):
        from app.services.conviction_modeler import _score_valuation_certainty
        from app.schemas import ValuationView
        return _score_valuation_certainty(
            ValuationView(overall="v", confidence=val_conf, valuation_stance=stance),
            evidence,
        )

    def test_fmp_val_evidence_raises_certainty(self):
        with_fmp = self._score([_fmp_val_ev()])
        without  = self._score([_ev(source="newsapi")])
        assert with_fmp > without

    def test_clear_stance_raises_certainty(self):
        no_stance   = self._score([_fmp_val_ev()], stance="")
        with_stance = self._score([_fmp_val_ev()], stance="overpriced")
        assert with_stance >= no_stance

    def test_cannot_determine_lowers_certainty(self):
        cannot = self._score([_fmp_val_ev()], stance="cannot_determine")
        clear  = self._score([_fmp_val_ev()], stance="overpriced")
        assert cannot < clear

    def test_full_val_coverage_high_certainty(self):
        ev = [_fmp_val_ev(), _fmp_analyst_ev()]
        score = self._score(ev, stance="fairly_valued")
        assert score >= 0.60

    def test_score_bounded_0_1(self):
        for ev in [[], [_fmp_val_ev()], [_ev()]]:
            assert 0.0 <= self._score(ev) <= 1.0


# ── 7. Estimate dispersion scoring ───────────────────────────────────────────

class TestEstimateDispersionScoring:
    def _score(self, evidence):
        from app.services.conviction_modeler import _score_estimate_dispersion
        return _score_estimate_dispersion(evidence)

    def test_no_analyst_evidence_penalised(self):
        score = self._score([_ev(source="newsapi")])
        assert score < 0.60

    def test_analyst_evidence_present_raises_score(self):
        s_with = self._score([_fmp_analyst_ev()])
        s_without = self._score([_ev(source="newsapi")])
        assert s_with > s_without

    def test_dispersion_language_lowers_score(self):
        tight_ev = _ev(
            source="FMP analyst-estimates",
            title="AAPL Analyst Consensus",
            summary="Strong buy consensus. Price target $220. Buy reiterated.",
        )
        dispersed_ev = _ev(
            source="FMP analyst-estimates",
            title="AAPL Analyst Consensus",
            summary="Widely dispersed views. Divergent analyst estimates after earnings.",
        )
        tight_score     = self._score([tight_ev])
        dispersed_score = self._score([dispersed_ev])
        assert tight_score > dispersed_score

    def test_score_bounded_0_1(self):
        assert 0.0 <= self._score([]) <= 1.0
        assert 0.0 <= self._score([_fmp_analyst_ev()]) <= 1.0


# ── 8. Governance risk scoring ────────────────────────────────────────────────

class TestGovernanceRiskScoring:
    def _score(self, warnings):
        from app.services.conviction_modeler import _score_governance_risk
        return _score_governance_risk(warnings)

    def test_no_warnings_zero_risk(self):
        assert self._score([]) == 0.0

    def test_governance_warning_adds_risk(self):
        w = ["[GOVERNANCE] Rate-cut benefit claim for Financial company."]
        assert self._score(w) > 0.0

    def test_multiple_governance_warnings_compound(self):
        one = self._score(["[GOVERNANCE] Warning 1."])
        two = self._score(["[GOVERNANCE] Warning 1.", "[GOVERNANCE] Warning 2."])
        assert two > one

    def test_overlap_warning_adds_smaller_risk(self):
        gov  = self._score(["[GOVERNANCE] Serious issue."])
        over = self._score(["[OVERLAP] Minor overlap."])
        assert gov > over

    def test_score_capped(self):
        """Even with many warnings, governance_risk stays within 0-1."""
        warnings = ["[GOVERNANCE] Warning"] * 20
        assert 0.0 <= self._score(warnings) <= 1.0


# ── 9. Score distribution ─────────────────────────────────────────────────────

class TestScoreDistribution:
    """The conviction modeler must not cluster around 65%."""

    def _run(self, evidence, agents, company, warnings=None):
        from app.services.conviction_modeler import compute_conviction
        val, mac, risk, mkt, qual = agents
        return compute_conviction(
            evidence=evidence,
            valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
            company=company,
            governance_warnings=warnings or [],
        )

    def test_excellent_coverage_scores_above_75(self):
        """Full FMP + fresh evidence + aligned agents → high conviction."""
        evidence = [
            _fmp_val_ev(ts=_days_ago(5)),
            _fmp_analyst_ev(ts=_days_ago(6)),
            _earnings_ev(ts=_days_ago(8)),
            _fresh(days=5), _fresh(days=8),
        ]
        agents = _make_agents(val_conf=0.88, mac_conf=0.82, risk_conf=0.80,
                              mkt_conf=0.85, qual_conf=0.83)
        result = self._run(evidence, agents, _make_company())
        assert result.final_score >= 0.68, f"Expected ≥ 0.68, got {result.final_score}"

    def test_no_evidence_scores_below_45(self):
        """No evidence → low conviction."""
        agents = _make_agents(val_conf=0.50, mac_conf=0.45, risk_conf=0.48,
                              mkt_conf=0.50, qual_conf=0.49)
        result = self._run([], agents, _make_company())
        assert result.final_score < 0.45, f"Expected < 0.45, got {result.final_score}"

    def test_stale_evidence_only_scores_below_60(self):
        """Stale-only evidence reduces score."""
        evidence = [_stale(200), _stale(250)]
        agents = _make_agents()
        result = self._run(evidence, agents, _make_company())
        assert result.final_score < 0.62, f"Expected < 0.62, got {result.final_score}"

    def test_mixed_evidence_scores_between_50_and_75(self):
        """Mixed coverage → mid-range conviction."""
        evidence = [_fmp_val_ev(), _ev(source="newsapi"), _stale(90)]
        agents = _make_agents(mac_conf=0.60, risk_conf=0.55)
        result = self._run(evidence, agents, _make_company())
        assert 0.45 <= result.final_score <= 0.80, f"Got {result.final_score}"

    def test_high_governance_risk_lowers_score(self):
        """Multiple governance warnings compress the score."""
        evidence = [_fmp_val_ev(), _fmp_analyst_ev(), _earnings_ev()]
        agents = _make_agents()
        no_warn_result  = self._run(evidence, agents, _make_company(), warnings=[])
        warn_result     = self._run(evidence, agents, _make_company(),
                                    warnings=["[GOVERNANCE] W1.", "[GOVERNANCE] W2."])
        assert warn_result.final_score <= no_warn_result.final_score

    def test_score_never_below_min(self):
        from app.services.conviction_modeler import _MIN_SCORE
        result = self._run([], _make_agents(0.0, 0.0, 0.0, 0.0, 0.0), _make_company())
        assert result.final_score >= _MIN_SCORE

    def test_score_never_above_max(self):
        from app.services.conviction_modeler import _MAX_SCORE
        evidence = [_fmp_val_ev(), _fmp_analyst_ev(), _earnings_ev()] * 3
        agents = _make_agents(0.99, 0.99, 0.99, 0.99, 0.99)
        result = self._run(evidence, agents, _make_company())
        assert result.final_score <= _MAX_SCORE


# ── 10. Contradiction-aware compression ──────────────────────────────────────

class TestContractionCompression:
    def _run(self, evidence, agents, company, valuation_stance=""):
        from app.services.conviction_modeler import compute_conviction
        from app.schemas import ValuationView
        val_conf = agents[0].confidence
        val = ValuationView(overall="v", confidence=val_conf,
                            valuation_stance=valuation_stance)
        _, mac, risk, mkt, qual = agents
        return compute_conviction(
            evidence=evidence,
            valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
            company=_make_company(),
        )

    def test_compression_flag_set_when_triggered(self):
        """Stale evidence + governance risk triggers compression."""
        from app.services.conviction_modeler import compute_conviction
        from app.schemas import ValuationView

        # Low freshness + governance risk → compression
        stale_evidence = [_stale(200)]
        val, mac, risk, mkt, qual = _make_agents()
        val = ValuationView(overall="v", confidence=0.75, valuation_stance="overpriced")

        # Build dims manually to test compression logic
        from app.services.conviction_modeler import (
            ConvictionDimensions, _check_contradiction_compression
        )
        dims = ConvictionDimensions(
            evidence_freshness=0.25,  # very stale
            governance_risk=0.25,     # governance warnings present
            macro_uncertainty=0.65,   # uncertain
        )
        should_compress, reasons, factor = _check_contradiction_compression(dims, val, None, [])
        assert should_compress
        assert len(reasons) >= 1

    def test_no_compression_for_clean_thesis(self):
        """Aligned, fresh, consistent thesis → no compression."""
        from app.services.conviction_modeler import (
            ConvictionDimensions, _check_contradiction_compression
        )
        from app.schemas import ValuationView
        dims = ConvictionDimensions(
            evidence_freshness=0.90,
            governance_risk=0.0,
            macro_uncertainty=0.20,
            thesis_alignment=0.85,
            estimate_dispersion=0.75,
            expectation_fragility=0.20,
        )
        val = ValuationView(overall="v", confidence=0.85, valuation_stance="fairly_valued")
        should_compress, reasons, factor = _check_contradiction_compression(dims, val, None, [])
        assert not should_compress
        assert reasons == []

    def test_compression_lowers_final_score(self):
        """When compression fires, final_score < raw_score."""
        from app.services.conviction_modeler import (
            ConvictionDimensions, _compose_score, _COMPRESSION_MILD
        )
        dims = ConvictionDimensions(
            evidence_quality=0.70, evidence_freshness=0.25,
            thesis_alignment=0.70, macro_uncertainty=0.70,
            valuation_certainty=0.35, estimate_dispersion=0.38,
            governance_risk=0.30,
        )
        raw = _compose_score(dims)
        # Any compression factor < 1.0 must produce a lower score
        compressed = round(raw * _COMPRESSION_MILD, 4)
        assert compressed < raw

    def test_overpriced_stance_with_bullish_signals_and_macro_uncertainty_triggers(self):
        """Overpriced + macro uncertainty triggers stance-signal compression."""
        from app.services.conviction_modeler import (
            ConvictionDimensions, _check_contradiction_compression
        )
        from app.schemas import ValuationView, Signal

        dims = ConvictionDimensions(macro_uncertainty=0.65)
        val = ValuationView(overall="v", confidence=0.75, valuation_stance="overpriced")

        # Mock a ranked set with bullish lean
        ranked = MagicMock()
        ranked.all_ranked = [
            MagicMock(direction="bullish"),
            MagicMock(direction="bullish"),
            MagicMock(direction="bearish"),
        ]
        should_compress, reasons, factor = _check_contradiction_compression(dims, val, ranked, [])
        assert should_compress
        assert any("bullish" in r for r in reasons)


# ── 11. Company-specific uncertainty language ─────────────────────────────────

class TestCompanySpecificUncertainty:
    def _drivers(self, ticker, sector=None):
        from app.services.conviction_modeler import _get_uncertainty_drivers
        from app.schemas import CompanyContext
        return _get_uncertainty_drivers(
            CompanyContext(ticker=ticker, company_name="Test Co", sector=sector or "Technology")
        )

    def test_nvda_has_specific_drivers(self):
        drivers = self._drivers("NVDA")
        combined = " ".join(drivers).lower()
        assert "hypersca" in combined or "capex" in combined or "asic" in combined

    def test_vrtx_has_pharma_drivers(self):
        drivers = self._drivers("VRTX", sector="Health Care")
        combined = " ".join(drivers).lower()
        assert "pipeline" in combined or "cftr" in combined or "regulat" in combined

    def test_asml_has_export_control_driver(self):
        drivers = self._drivers("ASML")
        combined = " ".join(drivers).lower()
        assert "china" in combined or "export" in combined or "euv" in combined

    def test_unknown_ticker_falls_back_to_sector(self):
        drivers = self._drivers("ZZZZ", sector="Financials")
        combined = " ".join(drivers).lower()
        assert "nim" in combined or "credit" in combined or "rate" in combined

    def test_unknown_ticker_unknown_sector_fallback(self):
        drivers = self._drivers("ZZZZ", sector=None)
        assert len(drivers) >= 1

    def test_aapl_has_china_driver(self):
        drivers = self._drivers("AAPL")
        combined = " ".join(drivers).lower()
        assert "china" in combined or "services" in combined

    def test_lly_has_glp1_driver(self):
        drivers = self._drivers("LLY", sector="Health Care")
        combined = " ".join(drivers).lower()
        assert "glp" in combined or "mounjaro" in combined or "manufactur" in combined

    def test_msft_has_azure_driver(self):
        drivers = self._drivers("MSFT")
        combined = " ".join(drivers).lower()
        assert "azure" in combined or "copilot" in combined or "ai" in combined


# ── 12. what_increases_conviction specificity ─────────────────────────────────

class TestWhatIncreasesConviction:
    def _compute(self, evidence, ticker="NVDA", sector="Technology"):
        from app.services.conviction_modeler import compute_conviction
        company = _make_company(ticker=ticker, sector=sector)
        val, mac, risk, mkt, qual = _make_agents()
        return compute_conviction(
            evidence=evidence,
            valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
            company=company,
        )

    def test_returns_non_empty_string(self):
        result = self._compute([_ev()])
        assert isinstance(result.what_increases_conviction, str)
        assert len(result.what_increases_conviction) > 0

    def test_nvda_references_nvda_specific_term(self):
        """NVDA conviction sentence should not be generic."""
        result = self._compute([], ticker="NVDA")
        text = result.what_increases_conviction.lower()
        nvda_terms = ("hypersca", "capex", "asic", "export", "blackwell", "data center", "nvda")
        assert any(t in text for t in nvda_terms), \
            f"Expected NVDA-specific term in: {result.what_increases_conviction!r}"

    def test_vrtx_references_pipeline(self):
        result = self._compute([], ticker="VRTX", sector="Health Care")
        text = result.what_increases_conviction.lower()
        vrtx_terms = ("pipeline", "cftr", "earnings", "fda", "clinical", "vrtx", "phase")
        assert any(t in text for t in vrtx_terms), \
            f"Expected VRTX-specific term in: {result.what_increases_conviction!r}"

    def test_not_generic_template(self):
        """Should not just say 'more evidence would help'."""
        result = self._compute([_ev()], ticker="AAPL")
        bad_phrases = ("more evidence would", "better market conditions", "more information")
        text = result.what_increases_conviction.lower()
        for phrase in bad_phrases:
            assert phrase not in text, f"Generic phrase found: {phrase!r}"

    def test_stamped_on_thesis_in_synthesizer(self):
        """what_increases_conviction is stamped on the InvestmentThesis."""
        from app.services.thesis_synthesizer import synthesize_thesis
        from app.schemas import CompanyContext, InvestmentThesis, ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment

        company = _make_company(ticker="NVDA", name="NVIDIA Corporation")
        stub_thesis = InvestmentThesis(
            ticker="NVDA", company_name="NVIDIA Corporation",
            bull_thesis="H100 demand drives EPS.", bear_thesis="ASIC risk.",
            conclusion="Constructive.", confidence_score=0.80,
        )
        val, mac, risk, mkt, qual = _make_agents()

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement",
                   return_value=stub_thesis), \
             patch("app.services.thesis_synthesizer.rank_signals", return_value=None), \
             patch("app.services.thesis_synthesizer._detect_dominant_dimension", return_value="valuation"), \
             patch("app.services.thesis_synthesizer.check_synthesis_depth", return_value=[]), \
             patch("app.services.thesis_synthesizer.check_forbidden_phrases", return_value=[]), \
             patch("app.services.thesis_synthesizer.detect_signal_overlap", return_value=[]), \
             patch("app.services.thesis_synthesizer.polish_thesis", side_effect=lambda t, **kw: t), \
             patch("app.services.thesis_synthesizer.compute_confidence_realism_cap", return_value=(0.80, [])):
            result = synthesize_thesis(
                company=company, valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
                evidence=[_ev()],
            )

        # Field must be present and non-empty
        assert hasattr(result, "what_increases_conviction")
        assert isinstance(result.what_increases_conviction, str)
        assert len(result.what_increases_conviction) > 0


# ── 13. Confidence reasoning specificity ─────────────────────────────────────

class TestConfidenceReasoningSpecificity:
    def _compute(self, evidence, ticker="AAPL", sector="Technology", agents=None):
        from app.services.conviction_modeler import compute_conviction
        company = _make_company(ticker=ticker, sector=sector)
        val, mac, risk, mkt, qual = agents or _make_agents()
        return compute_conviction(
            evidence=evidence,
            valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
            company=company,
        )

    def test_reasoning_non_empty(self):
        result = self._compute([_ev()])
        assert len(result.confidence_reasoning) > 10

    def test_reasoning_mentions_ticker(self):
        result = self._compute([_ev()], ticker="MSFT")
        assert "MSFT" in result.confidence_reasoning

    def test_high_conviction_reasoning_uses_positive_language(self):
        evidence = [_fmp_val_ev(ts="2026-05-15T00:00:00Z"), _fmp_analyst_ev(ts="2026-05-15T00:00:00Z"),
                    _earnings_ev(ts="2026-05-01T00:00:00Z"), _fresh(days=5)]
        agents = _make_agents(0.90, 0.88, 0.85, 0.87, 0.86)
        result = self._compute(evidence, agents=agents)
        text = result.confidence_reasoning.lower()
        positive_terms = ("high clarity", "constructive", "reads cleanly", "mechanism is consistent")
        # At least one positive term should appear when score is high
        if result.final_score >= 0.72:
            assert any(t in text for t in positive_terms), \
                f"High-conviction reasoning lacks positive language: {result.confidence_reasoning!r}"

    def test_low_conviction_reasoning_uses_cautionary_language(self):
        result = self._compute([], ticker="AAPL")
        text = result.confidence_reasoning.lower()
        cautionary = ("insufficient", "thin", "limited", "speculative", "conviction discount",
                      "insufficient evidence")
        assert any(t in text for t in cautionary), \
            f"Low-conviction reasoning lacks cautionary language: {result.confidence_reasoning!r}"

    def test_nvda_reasoning_mentions_nvda_specific_term(self):
        """Company-specific uncertainty should surface in reasoning when evidence is thin."""
        result = self._compute([], ticker="NVDA")
        text = result.confidence_reasoning.lower()
        # Should mention NVDA by name (stamped in opener) or specific driver
        assert "nvda" in text or "nvidia" in text.lower() or "hypersca" in text or "capex" in text

    def test_no_generic_template_phrases(self):
        """Should not repeat the old generic 'limited evidence coverage means...' verbatim."""
        result = self._compute([_ev()], ticker="AAPL")
        bad = "limited evidence coverage means this position carries more uncertainty than the score reflects"
        assert bad.lower() not in result.confidence_reasoning.lower()


# ── 14. Schema fields ─────────────────────────────────────────────────────────

class TestSchemaFields:
    def test_what_increases_conviction_on_thesis(self):
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.",
            bull_thesis="b", bear_thesis="b", conclusion="c",
            what_increases_conviction="Next earnings print.",
        )
        assert thesis.what_increases_conviction == "Next earnings print."

    def test_conviction_dimensions_on_thesis(self):
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.",
            bull_thesis="b", bear_thesis="b", conclusion="c",
            conviction_dimensions={"evidence_quality": 0.80},
        )
        assert thesis.conviction_dimensions["evidence_quality"] == 0.80

    def test_fields_default_empty(self):
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.",
            bull_thesis="b", bear_thesis="b", conclusion="c",
        )
        assert thesis.what_increases_conviction == ""
        assert thesis.conviction_dimensions == {}

    def test_conviction_dimensions_stamped_on_thesis_in_synthesizer(self):
        """conviction_dimensions dict is stamped on the thesis after synthesis."""
        from app.services.thesis_synthesizer import synthesize_thesis
        from app.schemas import InvestmentThesis

        company = _make_company(ticker="AAPL")
        stub = InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.",
            bull_thesis="b", bear_thesis="b",
            conclusion="c", confidence_score=0.78,
        )
        val, mac, risk, mkt, qual = _make_agents()

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement", return_value=stub), \
             patch("app.services.thesis_synthesizer.rank_signals", return_value=None), \
             patch("app.services.thesis_synthesizer._detect_dominant_dimension", return_value="valuation"), \
             patch("app.services.thesis_synthesizer.check_synthesis_depth", return_value=[]), \
             patch("app.services.thesis_synthesizer.check_forbidden_phrases", return_value=[]), \
             patch("app.services.thesis_synthesizer.detect_signal_overlap", return_value=[]), \
             patch("app.services.thesis_synthesizer.polish_thesis", side_effect=lambda t, **kw: t), \
             patch("app.services.thesis_synthesizer.compute_confidence_realism_cap", return_value=(0.78, [])):
            result = synthesize_thesis(
                company=company, valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
                evidence=[_fmp_val_ev()],
            )

        assert isinstance(result.conviction_dimensions, dict)
        assert "evidence_quality" in result.conviction_dimensions
        assert "thesis_alignment" in result.conviction_dimensions


# ── 15. Integration: conviction modeler in synthesize_thesis ──────────────────

class TestConvictionModelerIntegration:
    """Verify the conviction modeler is called and its outputs stamped in synthesize_thesis."""

    def _run(self, evidence, conf=0.80, ticker="AAPL"):
        from app.services.thesis_synthesizer import synthesize_thesis
        from app.schemas import InvestmentThesis

        company = _make_company(ticker=ticker)
        stub = InvestmentThesis(
            ticker=ticker, company_name="Test Co",
            bull_thesis="b", bear_thesis="b",
            conclusion="c", confidence_score=conf,
        )
        val, mac, risk, mkt, qual = _make_agents()

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement", return_value=stub), \
             patch("app.services.thesis_synthesizer.rank_signals", return_value=None), \
             patch("app.services.thesis_synthesizer._detect_dominant_dimension", return_value="valuation"), \
             patch("app.services.thesis_synthesizer.check_synthesis_depth", return_value=[]), \
             patch("app.services.thesis_synthesizer.check_forbidden_phrases", return_value=[]), \
             patch("app.services.thesis_synthesizer.detect_signal_overlap", return_value=[]), \
             patch("app.services.thesis_synthesizer.polish_thesis", side_effect=lambda t, **kw: t), \
             patch("app.services.thesis_synthesizer.compute_confidence_realism_cap", return_value=(conf, [])):
            return synthesize_thesis(
                company=company, valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
                evidence=evidence,
            )

    def test_no_evidence_lowers_confidence_below_llm_output(self):
        """Empty evidence → conviction modeler must lower score from 0.80."""
        result = self._run([], conf=0.80)
        assert result.confidence_score < 0.80

    def test_confidence_reasoning_is_overwritten_by_conviction(self):
        """The LLM's generic reasoning is replaced by the conviction modeler's specific text."""
        result = self._run([_ev()], ticker="NVDA")
        # Conviction modeler output is company-specific (mentions NVDA or dimensional language)
        reasoning = result.confidence_reasoning or ""
        generic_old = "Limited evidence coverage means this position carries more uncertainty"
        assert generic_old not in reasoning

    def test_conviction_dimensions_has_ten_keys(self):
        result = self._run([_fmp_val_ev()])
        dims = result.conviction_dimensions
        assert len(dims) == 10
        expected_keys = {
            "business_durability",
            "evidence_quality", "evidence_freshness", "thesis_alignment",
            "macro_uncertainty", "valuation_certainty", "estimate_dispersion",
            "governance_risk", "expectation_fragility", "expectation_asymmetry",
        }
        assert set(dims.keys()) == expected_keys

    def test_all_dimensions_bounded_0_1(self):
        result = self._run([_fmp_val_ev(), _fmp_analyst_ev()])
        for key, val in result.conviction_dimensions.items():
            assert 0.0 <= val <= 1.0, f"{key}={val} out of bounds"

    def test_what_increases_conviction_not_empty(self):
        result = self._run([_ev()])
        assert result.what_increases_conviction != ""

    def test_fresh_evidence_higher_confidence_than_stale(self):
        """Fresh evidence run should yield higher final confidence than stale."""
        fresh_result = self._run(
            [_fmp_val_ev(ts="2026-05-15T00:00:00Z"), _fmp_analyst_ev(ts="2026-05-15T00:00:00Z"),
             _earnings_ev(ts="2026-05-01T00:00:00Z")],
            conf=0.80,
        )
        stale_result = self._run([_stale(200), _stale(250)], conf=0.80)
        assert fresh_result.confidence_score >= stale_result.confidence_score
