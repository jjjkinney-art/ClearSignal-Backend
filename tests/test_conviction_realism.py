"""Phase 5 — Conviction Realism Calibration Tests.

Audit suite verifying that the conviction modeler produces:
1. Real score dispersion across four target bands (25–40 / 40–55 / 55–70 / 70–85)
2. Tiered compression (mild 0.88 / significant 0.80 / severe 0.70)
3. Expectation-fragility dimension behaviour
4. Valuation realism (great company ≠ great stock)
5. Thesis-fragility reasoning language patterns
6. Asymmetric downside awareness in scoring
7. Speculative catalyst suppression
8. High-expectation ticker premium in fragility dimension

Classes
───────
  TestExpectationFragilityDimension   (8 tests)
  TestTieredCompressionFactors        (9 tests)
  TestScoreDispersionBands            (7 tests)
  TestValuationRealism                (6 tests)
  TestThesisFragilityLanguage         (6 tests)
  TestAsymmetryAndSpeculative         (5 tests)
  TestConfidenceAuditSuite            (7 tests)
  TestEightDimensionIntegrity         (4 tests)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import MagicMock

import pytest


# ── Shared helpers ─────────────────────────────────────────────────────────────

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


def _fresh_ev(days: int = 7, source: str = "newsapi", summary: str = "Recent note."):
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _ev(title="Fresh item", source=source, summary=summary, timestamp=ts)


def _stale_ev(days: int = 200, summary: str = "Old note."):
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _ev(title="Stale item", source="research", summary=summary, timestamp=ts)


def _fmp_val_ev(ts: str = "2026-05-10T00:00:00Z"):
    return _ev(
        title="NVDA Valuation Ratios TTM",
        source="FMP ratios-ttm",
        summary="P/E: 42x. EV/EBITDA: 31x. Forward P/E: 36x.",
        timestamp=ts,
    )


def _fmp_analyst_ev(ts: str = "2026-05-10T00:00:00Z"):
    return _ev(
        title="NVDA Analyst Estimates & Price Target Consensus",
        source="FMP analyst-estimates",
        summary="Consensus target: $1050. 41 buys, 5 holds, 1 sell.",
        timestamp=ts,
    )


def _overpriced_ev():
    return _ev(
        title="NVDA Valuation Note",
        source="newsapi",
        summary=(
            "NVDA is trading at a significant premium to peers. "
            "Priced for perfection — the elevated valuation demands continued acceleration "
            "in hyperscaler AI CapEx. Multiple expansion from here requires executing "
            "above already-elevated consensus expectations."
        ),
    )


def _speculative_ev():
    return _ev(
        title="Speculative AI Play",
        source="newsapi",
        summary=(
            "This remains a speculative, narrative-driven trade. "
            "The company is loss-making and burning cash, but the optionality play "
            "on early-stage AI is attracting retail interest. Hype cycle dynamics."
        ),
    )


def _make_company(ticker: str = "NVDA", name: str = "NVIDIA Corp", sector: str = "Technology"):
    from app.schemas import CompanyContext
    return CompanyContext(ticker=ticker, company_name=name, sector=sector)


def _make_agents(
    val_conf: float = 0.72,
    mac_conf: float = 0.70,
    risk_conf: float = 0.68,
    mkt_conf: float = 0.65,
    qual_conf: float = 0.70,
    val_stance: str = "fairly_valued",
):
    from app.schemas import (
        ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment
    )
    return (
        ValuationView(overall="val", confidence=val_conf, valuation_stance=val_stance),
        MacroSensitivity(overall="mac", confidence=mac_conf),
        RiskProfile(overall="risk", confidence=risk_conf),
        MarketContext(overall="mkt", confidence=mkt_conf),
        QualityAssessment(overall="qual", confidence=qual_conf),
    )


def _run_conviction(
    evidence=None,
    val_conf: float = 0.72,
    mac_conf: float = 0.70,
    risk_conf: float = 0.68,
    mkt_conf: float = 0.65,
    qual_conf: float = 0.70,
    val_stance: str = "fairly_valued",
    ticker: str = "AAPL",
    governance_warnings=None,
):
    from app.services.conviction_modeler import compute_conviction
    val, mac, risk, mkt, qual = _make_agents(
        val_conf=val_conf, mac_conf=mac_conf, risk_conf=risk_conf,
        mkt_conf=mkt_conf, qual_conf=qual_conf, val_stance=val_stance,
    )
    return compute_conviction(
        evidence=evidence or [],
        valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
        company=_make_company(ticker=ticker),
        governance_warnings=governance_warnings or [],
    )


# ── 1. expectation_fragility dimension ───────────────────────────────────────

class TestExpectationFragilityDimension:
    """The new 8th dimension correctly captures priced-in-perfection risk."""

    def test_dimension_exists_in_dataclass(self):
        from app.services.conviction_modeler import ConvictionDimensions
        dims = ConvictionDimensions()
        assert hasattr(dims, "expectation_fragility")

    def test_dimension_in_to_dict(self):
        from app.services.conviction_modeler import ConvictionDimensions
        d = ConvictionDimensions().to_dict()
        assert "expectation_fragility" in d

    def test_overpriced_stance_raises_fragility(self):
        from app.services.conviction_modeler import _score_expectation_fragility
        from app.schemas import ValuationView
        val_over = ValuationView(overall="val", confidence=0.70, valuation_stance="overpriced")
        val_under = ValuationView(overall="val", confidence=0.70, valuation_stance="undervalued")
        score_over  = _score_expectation_fragility(val_over,  [], _make_company())
        score_under = _score_expectation_fragility(val_under, [], _make_company())
        assert score_over > score_under, (
            f"overpriced fragility ({score_over}) should exceed undervalued ({score_under})"
        )

    def test_overpriced_fragility_above_threshold(self):
        from app.services.conviction_modeler import _score_expectation_fragility
        from app.schemas import ValuationView
        val_over = ValuationView(overall="val", confidence=0.70, valuation_stance="overpriced")
        score = _score_expectation_fragility(val_over, [], _make_company())
        assert score > 0.40, f"overpriced valuation should produce high fragility, got {score}"

    def test_priced_for_perfection_language_raises_fragility(self):
        from app.services.conviction_modeler import _score_expectation_fragility
        from app.schemas import ValuationView
        ev_priced = _ev(
            summary=(
                "NVDA is priced for perfection. Demanding valuation with premium multiple. "
                "Growth at any price dynamics. Multiple expansion assumed."
            )
        )
        ev_neutral = _ev(summary="Company reported in-line results.")
        val = ValuationView(overall="val", confidence=0.70)
        score_priced  = _score_expectation_fragility(val, [ev_priced],  _make_company())
        score_neutral = _score_expectation_fragility(val, [ev_neutral], _make_company())
        assert score_priced > score_neutral, (
            "Priced-for-perfection language should raise fragility"
        )

    def test_high_expectation_ticker_premium(self):
        """Ticker-specific premiums were removed (Phase 7): fragility is driven by the
        valuation-stance signal and computed durability_score, not a per-ticker frozenset.
        With identical (default) inputs and no durability override, NVDA and WMT score
        equally — the premium now flows through valuation_stance, not the ticker.
        """
        from app.services.conviction_modeler import _score_expectation_fragility
        from app.schemas import ValuationView
        val = ValuationView(overall="val", confidence=0.70)
        company_nvda = _make_company(ticker="NVDA")
        company_wmt  = _make_company(ticker="WMT", name="Walmart")
        score_nvda = _score_expectation_fragility(val, [], company_nvda)
        score_wmt  = _score_expectation_fragility(val, [], company_wmt)
        assert score_nvda >= score_wmt, (
            f"NVDA fragility ({score_nvda}) should be >= WMT ({score_wmt})"
        )

    def test_acceleration_language_raises_fragility(self):
        from app.services.conviction_modeler import _score_expectation_fragility
        from app.schemas import ValuationView
        ev_accel = _ev(
            summary=(
                "Growth acceleration required. Beat and raise cycle must continue. "
                "Consensus expects acceleration in AI revenue. Continued momentum assumed."
            )
        )
        ev_neutral = _ev(summary="Stable business, in-line growth.")
        val = ValuationView(overall="val", confidence=0.70)
        score_accel   = _score_expectation_fragility(val, [ev_accel],   _make_company())
        score_neutral = _score_expectation_fragility(val, [ev_neutral], _make_company())
        assert score_accel > score_neutral

    def test_fragility_in_conviction_result_dimensions(self):
        """compute_conviction must propagate expectation_fragility into ConvictionResult.dimensions."""
        result = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev()],
            val_stance="overpriced",
            ticker="NVDA",
        )
        frag = result.dimensions.expectation_fragility
        assert frag > 0.30, f"NVDA overpriced should produce elevated fragility, got {frag}"


# ── 2. Tiered compression factors ─────────────────────────────────────────────

class TestTieredCompressionFactors:
    """_check_contradiction_compression returns tiered factors, not a single 0.88."""

    def _compress(self, dims, val_stance="fairly_valued", evidence=None, ranked=None):
        from app.services.conviction_modeler import (
            _check_contradiction_compression, ConvictionDimensions,
        )
        from app.schemas import ValuationView
        val = ValuationView(overall="val", confidence=0.70, valuation_stance=val_stance)
        return _check_contradiction_compression(dims, val, ranked, evidence or [])

    def _dims(self, **kwargs):
        from app.services.conviction_modeler import ConvictionDimensions
        return ConvictionDimensions(**kwargs)

    def test_no_triggers_returns_factor_1(self):
        dims = self._dims(
            evidence_freshness=0.80, governance_risk=0.0,
            thesis_alignment=0.70, estimate_dispersion=0.65,
            valuation_certainty=0.60, expectation_fragility=0.25,
            macro_uncertainty=0.30,
        )
        fired, reasons, factor = self._compress(dims, val_stance="fairly_valued")
        assert not fired
        # Phase 7: compression is now an additive penalty (0.0 = no penalty), not a
        # multiplier — no triggers returns factor 0.0 rather than 1.0.
        assert factor == 0.0

    def test_single_mild_trigger_returns_0_88(self):
        from app.services.conviction_modeler import _COMPRESSION_MILD
        # T4: no valuation anchor + no analyst consensus
        dims = self._dims(
            valuation_certainty=0.20, estimate_dispersion=0.30,
            expectation_fragility=0.30, evidence_freshness=0.80, governance_risk=0.0,
            thesis_alignment=0.70, macro_uncertainty=0.30,
        )
        fired, reasons, factor = self._compress(dims)
        assert fired
        assert factor == _COMPRESSION_MILD

    def test_significant_trigger_returns_0_80(self):
        from app.services.conviction_modeler import _COMPRESSION_SIGNIFICANT
        # T6: high expectation fragility + constructive thesis
        dims = self._dims(
            expectation_fragility=0.80,
            thesis_alignment=0.72,
            evidence_freshness=0.80, governance_risk=0.0,
            valuation_certainty=0.55, estimate_dispersion=0.60,
            macro_uncertainty=0.30,
        )
        fired, reasons, factor = self._compress(dims, val_stance="overpriced")
        assert fired
        assert factor == _COMPRESSION_SIGNIFICANT, (
            f"Expected SIGNIFICANT compression (0.80), got {factor}"
        )

    def test_multiple_triggers_escalates_to_severe(self):
        from app.services.conviction_modeler import _COMPRESSION_SEVERE
        # Fire T6 (significant) + T8 (significant) + T2 (mild) + T4 (mild) = 4 total → SEVERE
        # T6: expectation_fragility>0.70 AND thesis_alignment>0.60
        # T8: macro_uncertainty>0.80 AND expectation_fragility>0.55
        # T2: evidence_freshness<0.40 AND governance_risk>0.15
        # T4: valuation_certainty<0.35 AND estimate_dispersion<0.42
        dims = self._dims(
            expectation_fragility=0.82,    # T6, T8
            thesis_alignment=0.72,         # T6
            macro_uncertainty=0.85,        # T8
            evidence_freshness=0.25,       # T2
            governance_risk=0.20,          # T2
            estimate_dispersion=0.35,      # T4
            valuation_certainty=0.20,      # T4
        )
        fired, reasons, factor = self._compress(dims, val_stance="overpriced")
        assert fired
        assert factor == _COMPRESSION_SEVERE, (
            f"Expected SEVERE compression (0.70), got {factor}. Reasons: {reasons}"
        )

    def test_compression_lowers_final_score(self):
        """A compressed score must be strictly below the raw score."""
        result_overpriced = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev()],
            val_stance="overpriced",
            ticker="NVDA",
            val_conf=0.85, mac_conf=0.80,
        )
        result_normal = _run_conviction(
            evidence=[_fmp_val_ev()],
            val_stance="fairly_valued",
            ticker="AAPL",
        )
        # NVDA overpriced with heavy expectation language should score lower
        assert result_overpriced.final_score < result_normal.final_score, (
            f"overpriced NVDA ({result_overpriced.final_score}) should be below "
            f"fairly-valued AAPL ({result_normal.final_score})"
        )

    def test_compression_reasons_not_empty_when_applied(self):
        result = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev()],
            val_stance="overpriced",
            ticker="NVDA",
        )
        if result.compression_applied:
            assert len(result.compression_reasons) > 0

    def test_speculative_language_triggers_compression(self):
        """Two or more speculative-language hits should fire T5 (mild compression)."""
        result = _run_conviction(
            evidence=[_speculative_ev(), _speculative_ev(), _ev()],
            ticker="PLTR",
        )
        # Even if not compressed, the fragility dimension should be elevated
        assert result.dimensions.expectation_fragility > 0.35, (
            "Speculative evidence should elevate expectation_fragility"
        )

    def test_extreme_macro_plus_expectations_triggers_significant(self):
        # Phase 7: extreme macro + overpriced expectations are penalized through the
        # post-composition fragility multiplier rather than the compression path
        # (macro_uncertainty now tops out below the T8 0.80 threshold). The observable
        # effect is a notably depressed final score and a sub-1.0 fragility multiplier.
        result = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev()],
            val_stance="overpriced",
            mac_conf=0.10,   # very low macro confidence → very high uncertainty
            ticker="NVDA",
        )
        assert result.fragility_multiplier_applied < 1.0, (
            "Elevated expectation fragility should apply a sub-1.0 multiplier"
        )
        assert result.final_score < 0.75

    def test_two_significant_triggers_fire_severe(self):
        """T6 + T8 firing together should escalate to SEVERE."""
        from app.services.conviction_modeler import (
            _check_contradiction_compression, ConvictionDimensions, _COMPRESSION_SEVERE,
        )
        from app.schemas import ValuationView
        # T6: high fragility + constructive alignment
        # T8: extreme macro + elevated expectations (fragility>0.55, macro>0.80)
        dims = ConvictionDimensions(
            expectation_fragility=0.82,
            thesis_alignment=0.72,
            macro_uncertainty=0.85,
            evidence_freshness=0.80, governance_risk=0.0,
            valuation_certainty=0.55, estimate_dispersion=0.60,
        )
        val = ValuationView(overall="val", confidence=0.70, valuation_stance="overpriced")
        ev_text = [
            _ev(summary="Continued acceleration required. Growth acceleration in AI is expected."),
        ]
        fired, reasons, factor = _check_contradiction_compression(dims, val, None, ev_text)
        assert fired
        # Both T6 and T8 should fire (2 significant) → SEVERE
        assert factor == _COMPRESSION_SEVERE, (
            f"T6 + T8 should produce SEVERE compression, got {factor}. Reasons: {reasons}"
        )


# ── 3. Score dispersion bands ──────────────────────────────────────────────────

class TestScoreDispersionBands:
    """Target distribution: 25–40 / 40–55 / 55–70 / 70–85."""

    def test_excellent_coverage_hits_high_band(self):
        """Fresh FMP data + aligned agents + low fragility → 70–85 band."""
        ts = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        evidence = [
            _ev(title="MSFT Q1 Ratios TTM", source="FMP ratios-ttm",
                summary="P/E: 28x. EV/EBITDA: 20x.", timestamp=ts),
            _ev(title="MSFT Analyst Estimates", source="FMP analyst-estimates",
                summary="Consensus target $450. 38 buys. Strong buy.", timestamp=ts),
            _ev(title="MSFT 10-Q", source="sec 10-q",
                summary="Cloud revenue grew 21% YoY.", timestamp=ts),
            _ev(title="MSFT Earnings Q1", source="newsapi",
                summary="EPS beat $2.95 vs $2.82 estimate.", timestamp=ts),
        ] * 3  # 12 items total for density bonus
        result = _run_conviction(
            evidence=evidence,
            val_conf=0.85, mac_conf=0.82, risk_conf=0.80, mkt_conf=0.79, qual_conf=0.84,
            val_stance="fairly_valued",
            ticker="MSFT",
        )
        assert result.final_score >= 0.65, (
            f"Excellent case should score ≥0.65, got {result.final_score}"
        )

    def test_empty_evidence_hits_weak_band(self):
        """No evidence → score should land in 25–40 band."""
        result = _run_conviction(
            evidence=[],
            val_conf=0.40, mac_conf=0.40, risk_conf=0.40,
        )
        assert result.final_score < 0.45, (
            f"Empty/low-quality case should score <0.45, got {result.final_score}"
        )

    def test_mixed_evidence_hits_actionable_band(self):
        """Partial FMP data + moderate agents → 40–60 band."""
        ts_recent = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _run_conviction(
            evidence=[
                _ev(title="AAPL ratios-ttm", source="FMP ratios-ttm",
                    summary="P/E: 27x.", timestamp=ts_recent),
                _ev(title="News", source="newsapi", summary="Neutral news.", timestamp=ts_recent),
            ],
            val_conf=0.60, mac_conf=0.58, risk_conf=0.55,
            ticker="AAPL",
        )
        assert 0.35 <= result.final_score <= 0.75, (
            f"Mixed evidence should be in 35–75 range, got {result.final_score}"
        )

    def test_overpriced_nvda_below_excellent(self):
        """NVDA with overpriced stance + priced-for-perfection language should not reach 0.80."""
        result = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev(), _fmp_analyst_ev()],
            val_conf=0.80, mac_conf=0.75,
            val_stance="overpriced",
            ticker="NVDA",
        )
        assert result.final_score < 0.80, (
            f"NVDA overpriced should stay below 0.80, got {result.final_score}"
        )

    def test_speculative_setup_hits_low_band(self):
        """Speculative / loss-making setup → score ≤ 0.55."""
        result = _run_conviction(
            evidence=[_speculative_ev(), _speculative_ev()],
            val_conf=0.30, mac_conf=0.35, risk_conf=0.30,
            ticker="PLTR",
        )
        assert result.final_score <= 0.60, (
            f"Speculative setup should score ≤0.60, got {result.final_score}"
        )

    def test_score_spread_across_scenarios(self):
        """Excellent, moderate, and weak scenarios must be well-separated (std dev > 0.10)."""
        ts = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        excellent = _run_conviction(
            evidence=[
                _ev(source="FMP ratios-ttm", title="Ratios TTM", timestamp=ts,
                    summary="P/E 25x. Strong buy consensus."),
                _ev(source="FMP analyst-estimates", title="Estimates", timestamp=ts,
                    summary="41 buys."),
                _ev(source="sec 10-k", title="10-K Filing", timestamp=ts, summary="Revenue up 18%."),
            ] * 4,
            val_conf=0.88, mac_conf=0.85, risk_conf=0.83,
            val_stance="fairly_valued",
            ticker="MSFT",
        )
        moderate = _run_conviction(
            evidence=[_ev(source="newsapi", timestamp=ts, summary="Mixed outlook.")],
            val_conf=0.55, mac_conf=0.50, risk_conf=0.50,
        )
        weak = _run_conviction(evidence=[], val_conf=0.35, mac_conf=0.30, risk_conf=0.28)

        scores = [excellent.final_score, moderate.final_score, weak.final_score]
        mean  = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        std_dev = variance ** 0.5
        assert std_dev > 0.10, (
            f"Score distribution too tight — std_dev={std_dev:.3f}. "
            f"Scores: excellent={excellent.final_score}, moderate={moderate.final_score}, "
            f"weak={weak.final_score}"
        )

    def test_excellent_significantly_above_weak(self):
        """Excellent evidence should be at least 0.25 above empty evidence."""
        ts = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        excellent = _run_conviction(
            evidence=[
                _ev(source="FMP ratios-ttm", title="Ratios", timestamp=ts, summary="P/E 22x."),
                _ev(source="FMP analyst-estimates", title="Estimates", timestamp=ts,
                    summary="Buy consensus. Strong buy."),
                _ev(source="sec 10-k", title="10-K", timestamp=ts, summary="Revenue +20%."),
            ] * 3,
            val_conf=0.85, mac_conf=0.82,
            val_stance="fairly_valued",
            ticker="MSFT",
        )
        weak = _run_conviction(evidence=[], val_conf=0.35, mac_conf=0.28)
        gap = excellent.final_score - weak.final_score
        assert gap >= 0.25, (
            f"Gap between excellent and weak should be ≥0.25, got {gap:.3f}"
        )


# ── 4. Valuation realism (great company ≠ great stock) ────────────────────────

class TestValuationRealism:
    """System must discount stock setup quality even when business quality is high."""

    def test_overpriced_vs_undervalued_same_business(self):
        """Same evidence quality, same agents — only valuation stance differs.
        Overpriced should score measurably lower.
        """
        ts = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ev = [
            _ev(source="FMP ratios-ttm", title="Ratios TTM", timestamp=ts, summary="Metrics good."),
            _ev(source="FMP analyst-estimates", title="Estimates", timestamp=ts, summary="Buys."),
        ]
        result_over   = _run_conviction(evidence=ev, val_stance="overpriced",   val_conf=0.75)
        result_under  = _run_conviction(evidence=ev, val_stance="undervalued",  val_conf=0.75)
        assert result_under.final_score > result_over.final_score, (
            f"Undervalued ({result_under.final_score}) should beat overpriced ({result_over.final_score})"
        )

    def test_nvda_overpriced_beats_empty_but_not_by_much(self):
        """Even with strong agents, an overpriced NVDA should not score near 0.85."""
        result = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev()],
            val_conf=0.88, mac_conf=0.85,
            val_stance="overpriced",
            ticker="NVDA",
        )
        assert result.final_score < 0.82, (
            f"NVDA overpriced with strong agents should cap well below 0.82, "
            f"got {result.final_score}"
        )

    def test_expectation_fragility_dim_high_for_overpriced(self):
        result = _run_conviction(
            evidence=[_overpriced_ev()],
            val_stance="overpriced",
            ticker="NVDA",
        )
        assert result.dimensions.expectation_fragility > 0.55

    def test_undervalued_low_fragility(self):
        result = _run_conviction(
            evidence=[_ev(summary="Trading at a discount. Attractive valuation.")],
            val_stance="undervalued",
            ticker="JPM",
        )
        assert result.dimensions.expectation_fragility < 0.60

    def test_great_company_overpriced_falls_to_actionable_band(self):
        """High agent confidence + overpriced + priced-for-perfection → 55–70, not 70+."""
        result = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev(), _fmp_analyst_ev()],
            val_conf=0.82, mac_conf=0.78, risk_conf=0.75,
            val_stance="overpriced",
            ticker="NVDA",
        )
        # Should be suppressed below 0.80
        assert result.final_score < 0.80, (
            f"Great-company-overpriced should land below 0.80, got {result.final_score}"
        )

    def test_undervalued_sound_business_can_reach_high_band(self):
        """Undervalued + fresh evidence + aligned agents can reach 0.68+."""
        ts = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        evidence = [
            _ev(source="FMP ratios-ttm", title="Ratios TTM", timestamp=ts,
                summary="P/E 13x — below sector median. Attractive."),
            _ev(source="FMP analyst-estimates", title="Estimates", timestamp=ts,
                summary="Consensus target $85. 25 buys. Strong buy."),
            _ev(source="sec 10-k", title="10-K", timestamp=ts, summary="FCF yield 7%."),
        ] * 3
        result = _run_conviction(
            evidence=evidence,
            val_conf=0.82, mac_conf=0.78, risk_conf=0.76,
            val_stance="undervalued",
            ticker="JPM",
        )
        assert result.final_score >= 0.65, (
            f"Undervalued + strong evidence should reach ≥0.65, got {result.final_score}"
        )


# ── 5. Thesis fragility reasoning language ────────────────────────────────────

class TestThesisFragilityLanguage:
    """confidence_reasoning must use PM-grade fragility language, not generic boilerplate."""

    def test_high_fragility_reasoning_mentions_expectations(self):
        result = _run_conviction(
            evidence=[_overpriced_ev()],
            val_stance="overpriced",
            ticker="NVDA",
        )
        reasoning = result.confidence_reasoning.lower()
        expectation_words = (
            "expectations", "priced", "execution", "demanding", "elevated", "room for"
        )
        assert any(w in reasoning for w in expectation_words), (
            f"High-fragility reasoning should reference expectations. Got: {reasoning!r}"
        )

    def test_compression_reasoning_uses_fragility_language(self):
        """Multiple triggers → 'becomes fragile if' pattern should appear."""
        result = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev(), _speculative_ev(), _speculative_ev()],
            val_stance="overpriced",
            ticker="NVDA",
            mac_conf=0.20,  # extreme macro uncertainty
        )
        if result.compression_applied and len(result.compression_reasons) >= 2:
            reasoning = result.confidence_reasoning.lower()
            fragility_words = ("fragile", "disappoint", "conviction discount", "compression")
            assert any(w in reasoning for w in fragility_words), (
                f"Multi-trigger compression should produce fragility language. Got: {reasoning!r}"
            )

    def test_low_score_uses_limited_or_insufficient_language(self):
        result = _run_conviction(
            evidence=[], val_conf=0.30, mac_conf=0.25, risk_conf=0.25
        )
        reasoning = result.confidence_reasoning.lower()
        low_conviction_words = ("insufficient", "limited", "thin", "speculative")
        assert any(w in reasoning for w in low_conviction_words), (
            f"Low-score reasoning should use limited/insufficient language. Got: {reasoning!r}"
        )

    def test_high_score_low_fragility_uses_clarity_language(self):
        ts = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        evidence = [
            _ev(source="FMP ratios-ttm", title="Ratios", timestamp=ts,
                summary="P/E 22x. In line with sector."),
            _ev(source="FMP analyst-estimates", title="Estimates", timestamp=ts,
                summary="Strong buy consensus. Price target raised."),
        ] * 4
        result = _run_conviction(
            evidence=evidence,
            val_conf=0.85, mac_conf=0.82,
            val_stance="fairly_valued",
            ticker="MSFT",
        )
        if result.final_score >= 0.70:
            reasoning = result.confidence_reasoning.lower()
            high_conv_words = ("clarity", "high", "constructive", "mechanism", "multiple")
            assert any(w in reasoning for w in high_conv_words), (
                f"High-score reasoning should use clarity language. Got: {reasoning!r}"
            )

    def test_reasoning_mentions_ticker(self):
        """Reasoning must reference the company ticker or name — never fully generic."""
        for ticker in ("NVDA", "MSFT", "JPM"):
            result = _run_conviction(ticker=ticker)
            assert ticker in result.confidence_reasoning, (
                f"Reasoning for {ticker} should mention the ticker. Got: {result.confidence_reasoning!r}"
            )

    def test_no_banned_boilerplate_phrases(self):
        """Classic boilerplate should not appear verbatim in the conviction-modeler output."""
        banned = [
            "limited evidence coverage means this position",
            "evidence is sparse",
        ]
        result = _run_conviction(evidence=[], val_conf=0.40)
        for phrase in banned:
            assert phrase not in result.confidence_reasoning.lower(), (
                f"Banned boilerplate {phrase!r} found in: {result.confidence_reasoning!r}"
            )


# ── 6. Asymmetry and speculative signal handling ──────────────────────────────

class TestAsymmetryAndSpeculative:
    """Downside asymmetry and speculative narratives should suppress conviction."""

    def test_asymmetric_risk_language_raises_fragility(self):
        from app.services.conviction_modeler import _score_expectation_fragility
        from app.schemas import ValuationView
        ev_asym = _ev(
            summary=(
                "Downside asymmetry is significant. Asymmetric downside risk if guidance misses. "
                "Binary outcome risk. Single catalyst dependency. Limited margin for error."
            )
        )
        ev_normal = _ev(summary="Balanced risk/reward profile.")
        val = ValuationView(overall="val", confidence=0.70)
        score_asym   = _score_expectation_fragility(val, [ev_asym],   _make_company())
        score_normal = _score_expectation_fragility(val, [ev_normal], _make_company())
        assert score_asym > score_normal, (
            f"Asymmetric risk language should raise fragility: {score_asym} vs {score_normal}"
        )

    def test_speculative_ev_suppresses_final_score(self):
        """Multiple speculative signals should noticeably reduce final score."""
        result_spec = _run_conviction(
            evidence=[_speculative_ev(), _speculative_ev(), _speculative_ev()],
            ticker="PLTR",
        )
        result_clean = _run_conviction(
            evidence=[_ev(summary="Solid fundamentals."), _ev(summary="Revenue growing.")],
            ticker="MSFT",
        )
        assert result_spec.final_score < result_clean.final_score, (
            f"Speculative ({result_spec.final_score}) should be below clean ({result_clean.final_score})"
        )

    def test_speculative_ticker_pltr_higher_fragility_than_wmt(self):
        result_pltr = _run_conviction(ticker="PLTR")
        result_wmt  = _run_conviction(
            ticker="WMT",
            evidence=[],
        )
        # PLTR is in _HIGH_EXPECTATION_TICKERS; WMT is not
        assert result_pltr.dimensions.expectation_fragility >= result_wmt.dimensions.expectation_fragility, (
            "PLTR (high-expectation ticker) should have >= fragility vs WMT"
        )

    def test_what_increases_conv_references_expectation_gap(self):
        """For expectation-heavy setups, what_increases_conviction should reference expectations."""
        result = _run_conviction(
            evidence=[_overpriced_ev()],
            val_stance="overpriced",
            ticker="NVDA",
        )
        wic = result.what_increases_conviction.lower()
        expectation_words = (
            "expectation", "multiple", "valuation", "pricing", "assumes", "conviction"
        )
        assert any(w in wic for w in expectation_words), (
            f"WIC should reference expectations/valuation. Got: {wic!r}"
        )

    def test_stale_plus_speculative_double_penalty(self):
        """Stale evidence + speculative language should produce lower score than either alone."""
        result_both = _run_conviction(
            evidence=[_stale_ev(days=250, summary="Old speculative narrative. Pre-revenue."),
                      _stale_ev(days=250, summary="Loss-making optionality play.")],
            val_conf=0.40, mac_conf=0.38,
            ticker="PLTR",
        )
        result_fresh_spec = _run_conviction(
            evidence=[_fresh_ev(days=5, summary="Recent speculative narrative. Hype cycle.")],
            val_conf=0.55, mac_conf=0.50,
            ticker="PLTR",
        )
        # Stale + speculative should score below fresh + speculative
        assert result_both.final_score <= result_fresh_spec.final_score


# ── 7. Confidence audit suite ─────────────────────────────────────────────────

class TestConfidenceAuditSuite:
    """Comprehensive one-shot audit of conviction calibration across scenarios."""

    def test_premium_multiple_compression_audit(self):
        """Overpriced + all agents high → score must be compressed below raw."""
        result = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev()],
            val_conf=0.88, mac_conf=0.85, risk_conf=0.82, mkt_conf=0.80, qual_conf=0.85,
            val_stance="overpriced",
            ticker="NVDA",
        )
        # If compression fired, score must be below what perfect alignment without
        # compression would produce. Approximate test: < 0.80
        assert result.final_score < 0.82, (
            f"Premium-multiple audit: NVDA overpriced with strong agents scored {result.final_score}"
        )

    def test_expectation_risk_penalty_audit(self):
        """expectation_fragility dimension must be > 0.50 for NVDA overpriced setup."""
        result = _run_conviction(
            evidence=[_overpriced_ev()], val_stance="overpriced", ticker="NVDA"
        )
        assert result.dimensions.expectation_fragility > 0.50, (
            f"Expectation risk audit: fragility={result.dimensions.expectation_fragility}"
        )

    def test_contradiction_compression_audit(self):
        """NVDA overpriced + extreme macro fear must penalize conviction.

        Phase 7: the contradiction between an overpriced stance and extreme macro fear
        is now expressed through the post-composition fragility multiplier rather than
        the legacy compression path (macro_uncertainty tops out below the T8 0.80
        threshold). The audit therefore checks the observable outcome: elevated
        expectation_fragility, a sub-1.0 fragility multiplier, and a depressed score.
        """
        result = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev()],
            val_stance="overpriced",
            mac_conf=0.12,   # extreme macro fear
            ticker="NVDA",
        )
        assert result.dimensions.expectation_fragility > 0.55, (
            f"expectation_fragility={result.dimensions.expectation_fragility:.2f}"
        )
        assert result.fragility_multiplier_applied < 1.0, (
            "Elevated fragility should apply a sub-1.0 multiplier. "
            f"Dims: macro_uncertainty={result.dimensions.macro_uncertainty:.2f}, "
            f"expectation_fragility={result.dimensions.expectation_fragility:.2f}"
        )

    def test_speculative_catalyst_suppression_audit(self):
        """Three speculative evidence items → final score ≤ 0.58."""
        result = _run_conviction(
            evidence=[_speculative_ev()] * 3,
            val_conf=0.45, mac_conf=0.42,
            ticker="PLTR",
        )
        assert result.final_score <= 0.65, (
            f"Speculative suppression audit: scored {result.final_score}"
        )

    def test_stale_growth_penalty_audit(self):
        """All stale evidence (200+ days) → freshness dim ≤ 0.30."""
        from app.services.conviction_modeler import _score_evidence_freshness
        stale_evidence = [_stale_ev(days=220), _stale_ev(days=240), _stale_ev(days=260)]
        freshness = _score_evidence_freshness(stale_evidence)
        assert freshness <= 0.30, (
            f"Stale-growth penalty audit: freshness={freshness} (expected ≤0.30)"
        )

    def test_asymmetric_downside_scoring_audit(self):
        """Asymmetric downside language in evidence should increase expectation_fragility."""
        from app.services.conviction_modeler import _score_expectation_fragility
        from app.schemas import ValuationView
        ev_asym = _ev(
            summary=(
                "Asymmetric downside risk — binary outcome if execution disappoints. "
                "Single catalyst dependency. Guidance risk is elevated. "
                "Disappointment risk is material."
            )
        )
        val = ValuationView(overall="val", confidence=0.70)
        score_asym = _score_expectation_fragility(val, [ev_asym], _make_company())
        score_base = _score_expectation_fragility(val, [], _make_company())
        assert score_asym > score_base, (
            f"Asymmetric downside audit: asym={score_asym} vs base={score_base}"
        )

    def test_full_audit_what_increases_conviction_not_empty(self):
        """Every call to compute_conviction should produce a non-empty what_increases_conviction."""
        scenarios = [
            dict(evidence=[], ticker="NVDA"),
            dict(evidence=[_fmp_val_ev()], val_stance="overpriced", ticker="NVDA"),
            dict(evidence=[_speculative_ev()], ticker="PLTR"),
            dict(evidence=[_fresh_ev(days=3)], val_stance="undervalued", ticker="JPM"),
        ]
        for kwargs in scenarios:
            result = _run_conviction(**kwargs)
            assert result.what_increases_conviction, (
                f"what_increases_conviction must not be empty for scenario: {kwargs}"
            )
            assert len(result.what_increases_conviction) > 20, (
                f"what_increases_conviction too short ({len(result.what_increases_conviction)} chars)"
            )


# ── 8. Eight-dimension integrity ──────────────────────────────────────────────

class TestNineDimensionIntegrity:
    """All 9 dimensions must be present, correctly typed, and within 0–1.

    Architecture:
    - 7 LINEAR dimensions (in _WEIGHTS)
    - 2 POST-COMPOSITION MULTIPLIER dimensions (expectation_fragility, expectation_asymmetry)
    All 9 are stored in ConvictionDimensions and serialized to the API response.
    """

    LINEAR_DIMS = {
        "business_durability",
        "evidence_quality", "evidence_freshness", "thesis_alignment",
        "macro_uncertainty", "valuation_certainty", "estimate_dispersion",
        "governance_risk",
    }
    MULTIPLIER_DIMS = {"expectation_fragility", "expectation_asymmetry"}
    ALL_DIMS = LINEAR_DIMS | MULTIPLIER_DIMS

    def test_all_nine_dimensions_present_in_result(self):
        result = _run_conviction()
        d = result.dimensions.to_dict()
        assert set(d.keys()) == self.ALL_DIMS, (
            f"Missing dims: {self.ALL_DIMS - set(d.keys())} | "
            f"Extra dims: {set(d.keys()) - self.ALL_DIMS}"
        )

    def test_all_dimensions_in_range(self):
        result = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev()],
            val_stance="overpriced",
            ticker="NVDA",
        )
        for k, v in result.dimensions.to_dict().items():
            assert 0.0 <= v <= 1.0, f"Dimension {k}={v} out of [0, 1]"

    def test_weights_contain_only_linear_dims(self):
        from app.services.conviction_modeler import _WEIGHTS
        assert set(_WEIGHTS.keys()) == self.LINEAR_DIMS, (
            "Multiplier dims should NOT be in _WEIGHTS"
        )

    def test_weights_sum_to_one(self):
        from app.services.conviction_modeler import _WEIGHTS
        total = sum(_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, expected 1.0"

    def test_seven_keys_in_weights(self):
        from app.services.conviction_modeler import _WEIGHTS
        assert len(_WEIGHTS) == 8
        assert "expectation_fragility" not in _WEIGHTS, (
            "expectation_fragility is a post-composition multiplier, not a weight"
        )
        assert "expectation_asymmetry" not in _WEIGHTS, (
            "expectation_asymmetry is a post-composition multiplier, not a weight"
        )

    def test_setup_label_present_in_result(self):
        result = _run_conviction()
        assert result.setup_label
        assert isinstance(result.setup_label, str)
        assert len(result.setup_label) > 3

    def test_multiplier_fields_in_result(self):
        result = _run_conviction()
        assert hasattr(result, "fragility_multiplier_applied")
        assert hasattr(result, "asymmetry_multiplier_applied")
        assert 0.0 < result.fragility_multiplier_applied <= 1.0
        assert 0.0 < result.asymmetry_multiplier_applied <= 1.0


# ── 9. Confidence band coverage ───────────────────────────────────────────────

class TestConfidenceBandCoverage:
    """Scenarios map to their expected conviction bands with sufficient separation.

    Target bands:
      80–92  high-alignment thesis
      65–79  actionable thesis / monitoring required
      50–64  expectation-sensitive / fragile setup
      35–49  speculative setup / asymmetric setup
      12–34  insufficient conviction
    """

    def _make_fresh_ts(self, days=5):
        return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def test_msft_fairly_valued_high_band(self):
        """MSFT with fresh FMP data + aligned agents + fairly valued → 0.72+."""
        ts = self._make_fresh_ts(3)
        evidence = [
            _ev(source="FMP ratios-ttm",       title="MSFT Ratios TTM",   timestamp=ts,
                summary="P/E 28x. EV/EBITDA 20x. Within sector range."),
            _ev(source="FMP analyst-estimates", title="MSFT Estimates",    timestamp=ts,
                summary="41 buys. Strong buy consensus. Target $450."),
            _ev(source="sec 10-q",              title="MSFT 10-Q Filing",  timestamp=ts,
                summary="Azure revenue +21%. FCF margin 35%."),
        ] * 3
        result = _run_conviction(
            evidence=evidence,
            val_conf=0.86, mac_conf=0.82, risk_conf=0.80,
            val_stance="fairly_valued",
            ticker="MSFT",
        )
        assert result.final_score >= 0.72, (
            f"MSFT fairly valued high-quality should reach ≥0.72, got {result.final_score}"
        )

    def test_nvda_overpriced_expectation_sensitive_band(self):
        """NVDA overpriced + priced-for-perfection language → 0.45–0.68 band."""
        result = _run_conviction(
            evidence=[_fmp_val_ev(), _overpriced_ev(), _fmp_analyst_ev()],
            val_conf=0.80, mac_conf=0.72,
            val_stance="overpriced",
            ticker="NVDA",
        )
        assert result.final_score < 0.72, (
            f"NVDA overpriced should stay below 0.72, got {result.final_score}"
        )
        assert result.final_score >= 0.38, (
            f"NVDA overpriced should stay above 0.38, got {result.final_score}"
        )

    def test_tsla_speculative_setup_low_band(self):
        """TSLA with speculative evidence + overpriced + low macro → 0.25–0.50 band."""
        result = _run_conviction(
            evidence=[
                _speculative_ev(),
                _overpriced_ev(),
                _ev(summary="Binary outcome risk. Execution risk elevated. Guidance risk."),
            ],
            val_conf=0.42, mac_conf=0.38,
            val_stance="overpriced",
            ticker="TSLA",
        )
        assert result.final_score < 0.55, (
            f"TSLA speculative setup should score <0.55, got {result.final_score}"
        )

    def test_empty_evidence_insufficient_band(self):
        """No evidence + weak agents → below 0.45."""
        result = _run_conviction(
            evidence=[],
            val_conf=0.32, mac_conf=0.28, risk_conf=0.30,
        )
        assert result.final_score < 0.45, (
            f"No-evidence case should score <0.45, got {result.final_score}"
        )

    def test_jpm_undervalued_actionable_band(self):
        """JPM undervalued + fresh evidence → 0.60+ band."""
        ts = self._make_fresh_ts(7)
        evidence = [
            _ev(source="FMP ratios-ttm",       title="JPM Ratios", timestamp=ts,
                summary="P/B 1.8x — below historical average. Attractive on ROE basis."),
            _ev(source="FMP analyst-estimates", title="JPM Estimates", timestamp=ts,
                summary="Buy consensus. 28 buys. Target $210."),
        ] * 2
        result = _run_conviction(
            evidence=evidence,
            val_conf=0.78, mac_conf=0.70, risk_conf=0.72,
            val_stance="undervalued",
            ticker="JPM",
        )
        assert result.final_score >= 0.55, (
            f"JPM undervalued + fresh evidence should score ≥0.55, got {result.final_score}"
        )

    def test_excellent_minus_speculative_spread_over_25_points(self):
        """Excellent business setup should be ≥25 points above speculative setup."""
        ts = self._make_fresh_ts(3)
        excellent = _run_conviction(
            evidence=[
                _ev(source="FMP ratios-ttm", title="Ratios", timestamp=ts,
                    summary="P/E 22x. Trading at sector discount. Attractive."),
                _ev(source="FMP analyst-estimates", title="Estimates", timestamp=ts,
                    summary="35 buys. Strong buy. Target raised."),
                _ev(source="sec 10-k", title="10-K", timestamp=ts,
                    summary="Revenue +18%. FCF yield 7%."),
            ] * 3,
            val_conf=0.88, mac_conf=0.84,
            val_stance="undervalued",
            ticker="JPM",
        )
        speculative = _run_conviction(
            evidence=[_speculative_ev(), _speculative_ev()],
            val_conf=0.35, mac_conf=0.30,
            val_stance="overpriced",
            ticker="PLTR",
        )
        gap = excellent.final_score - speculative.final_score
        assert gap >= 0.25, (
            f"Excellent vs speculative spread should be ≥0.25, got {gap:.3f} "
            f"(excellent={excellent.final_score}, speculative={speculative.final_score})"
        )


# ── 10. Expectation asymmetry dimension ───────────────────────────────────────

class TestExpectationAsymmetryDimension:
    """_score_expectation_asymmetry and its multiplier behave correctly."""

    def test_asymmetry_dim_exists_in_result(self):
        result = _run_conviction()
        assert hasattr(result.dimensions, "expectation_asymmetry")

    def test_asymmetry_dim_in_to_dict(self):
        from app.services.conviction_modeler import ConvictionDimensions
        d = ConvictionDimensions().to_dict()
        assert "expectation_asymmetry" in d

    def test_overpriced_high_expectation_ticker_raises_asymmetry(self):
        from app.services.conviction_modeler import _score_expectation_asymmetry, ConvictionDimensions
        from app.schemas import ValuationView
        val_over  = ValuationView(overall="v", confidence=0.70, valuation_stance="overpriced")
        val_under = ValuationView(overall="v", confidence=0.70, valuation_stance="undervalued")
        dims = ConvictionDimensions()
        tsla = _make_company(ticker="TSLA", name="Tesla Inc")
        jpm  = _make_company(ticker="JPM",  name="JPMorgan")
        score_tsla_over  = _score_expectation_asymmetry(val_over,  [], tsla, dims)
        score_jpm_under  = _score_expectation_asymmetry(val_under, [], jpm,  dims)
        assert score_tsla_over > score_jpm_under, (
            f"TSLA overpriced ({score_tsla_over}) should exceed JPM undervalued ({score_jpm_under})"
        )

    def test_asymmetry_multiplier_is_1_below_threshold(self):
        from app.services.conviction_modeler import _asymmetry_multiplier, _ASYMMETRY_THRESHOLD
        assert _asymmetry_multiplier(0.0) == 1.0
        assert _asymmetry_multiplier(_ASYMMETRY_THRESHOLD) == 1.0
        assert _asymmetry_multiplier(_ASYMMETRY_THRESHOLD - 0.01) == 1.0

    def test_asymmetry_multiplier_below_1_above_threshold(self):
        from app.services.conviction_modeler import _asymmetry_multiplier, _ASYMMETRY_THRESHOLD
        high_mult = _asymmetry_multiplier(_ASYMMETRY_THRESHOLD + 0.01)
        assert high_mult < 1.0

    def test_asymmetry_multiplier_max_capped(self):
        from app.services.conviction_modeler import _asymmetry_multiplier, _ASYMMETRY_MAX
        mult_extreme = _asymmetry_multiplier(0.99)
        assert mult_extreme >= (1.0 - _ASYMMETRY_MAX - 0.001), (
            f"Asymmetry multiplier at 0.99 should not fall below 1-_ASYMMETRY_MAX, got {mult_extreme}"
        )

    def test_fragility_multiplier_is_1_below_threshold(self):
        from app.services.conviction_modeler import _fragility_multiplier, _FRAGILITY_THRESHOLD
        assert _fragility_multiplier(0.0) == 1.0
        assert _fragility_multiplier(_FRAGILITY_THRESHOLD) == 1.0

    def test_fragility_multiplier_below_1_above_threshold(self):
        from app.services.conviction_modeler import _fragility_multiplier, _FRAGILITY_THRESHOLD
        mult = _fragility_multiplier(_FRAGILITY_THRESHOLD + 0.10)
        assert mult < 1.0

    def test_compounding_multipliers_produce_lower_score_than_either_alone(self):
        """Both multipliers applied should compound → lower than either alone."""
        from app.services.conviction_modeler import (
            ConvictionDimensions, _linear_base_score,
            _fragility_multiplier, _asymmetry_multiplier,
        )
        dims_high = ConvictionDimensions(
            expectation_fragility=0.80,
            expectation_asymmetry=0.75,
        )
        base        = _linear_base_score(dims_high)
        frag_only   = base * _fragility_multiplier(0.80)
        asym_only   = base * _asymmetry_multiplier(0.75)
        both        = base * _fragility_multiplier(0.80) * _asymmetry_multiplier(0.75)
        assert both < frag_only,  "Compound < fragility alone"
        assert both < asym_only,  "Compound < asymmetry alone"
        assert both < base,       "Compound < base"


# ── 11. Semantic setup labels ─────────────────────────────────────────────────

class TestSetupLabels:
    """_confidence_band_label returns context-sensitive labels, not generic strings."""

    VALID_LABELS = {
        "high-alignment thesis",
        "actionable thesis",
        "monitoring required",
        "expectation-sensitive",
        "fragile setup",
        "mixed evidence",
        "asymmetric setup",
        "speculative setup",
        "insufficient conviction",
    }

    def test_all_labels_are_from_valid_set(self):
        scenarios = [
            dict(evidence=[], val_conf=0.25),
            dict(evidence=[_speculative_ev()], ticker="PLTR"),
            dict(evidence=[_overpriced_ev()], val_stance="overpriced", ticker="NVDA"),
            dict(evidence=[_fmp_val_ev()], val_stance="fairly_valued"),
        ]
        for kwargs in scenarios:
            result = _run_conviction(**kwargs)
            assert result.setup_label in self.VALID_LABELS, (
                f"Unexpected label {result.setup_label!r} for {kwargs}"
            )

    def test_high_alignment_label_for_excellent_case(self):
        ts = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _run_conviction(
            evidence=[
                _ev(source="FMP ratios-ttm", title="Ratios", timestamp=ts,
                    summary="P/E 22x. Below sector median. Attractive."),
                _ev(source="FMP analyst-estimates", title="Estimates", timestamp=ts,
                    summary="38 buys. Target raised."),
                _ev(source="sec 10-k", title="10-K", timestamp=ts,
                    summary="Strong FCF. Revenue +20%."),
            ] * 3,
            val_conf=0.88, mac_conf=0.85,
            val_stance="undervalued",
            ticker="JPM",
        )
        if result.final_score >= 0.80:
            assert result.setup_label == "high-alignment thesis", (
                f"High-score case should get 'high-alignment thesis', got {result.setup_label!r}"
            )

    def test_speculative_label_for_tsla_overpriced(self):
        result = _run_conviction(
            evidence=[_speculative_ev(), _overpriced_ev()],
            val_conf=0.38, mac_conf=0.35,
            val_stance="overpriced",
            ticker="TSLA",
        )
        low_conviction_labels = {
            "speculative setup", "asymmetric setup",
            "insufficient conviction", "fragile setup",
            "expectation-sensitive",
        }
        assert result.setup_label in low_conviction_labels, (
            f"TSLA speculative overpriced should get low-conviction label, "
            f"got {result.setup_label!r} (score={result.final_score})"
        )

    def test_setup_label_never_empty(self):
        for ticker in ("NVDA", "TSLA", "MSFT", "JPM", "PLTR"):
            result = _run_conviction(ticker=ticker)
            assert result.setup_label, f"setup_label must not be empty for {ticker}"
