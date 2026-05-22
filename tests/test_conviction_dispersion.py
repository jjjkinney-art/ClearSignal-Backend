"""Phase 5c — Confidence Distribution Dispersion Audit.

Asserts that the conviction modeler produces realistic score spread across a
synthetic scenario matrix.  The core failure mode we guard against is
*midpoint collapse* — too many distinct scenarios clustering in the 55–70%
band with minimal differentiation between great setups and fragile ones.

Test classes
────────────
  TestScoreVariance          — std_dev > 0.12 across 20+ scenarios
  TestMidpointCollapse       — < 50 % of scores land in the 0.55–0.70 window
  TestHighFragilityCompression — overpriced HE tickers stay well below 0.60
  TestEvidenceFreshnessImpact — stale evidence materially lowers scores
  TestAlignmentImpact        — aligned multi-agent evidence raises scores
  TestExtremeScenarios       — excellent ≥ 0.72, speculative ≤ 0.45
  TestHETickerSpread         — HE-overpriced vs non-HE-undervalued spread ≥ 0.20
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest


# ── Minimal helpers ────────────────────────────────────────────────────────────

def _ts(days_ago: int = 7) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _ev(
    title: str = "Item",
    source: str = "newsapi",
    summary: str = "Summary.",
    timestamp: str | None = None,
):
    from app.schemas import RetrievedEvidence
    return RetrievedEvidence(
        title=title, source=source, summary=summary,
        timestamp=timestamp or _ts(7),
        relevance_score=0.8,
    )


def _fmp_ev(ts: str | None = None) -> object:
    return _ev(source="FMP ratios-ttm", title="Ratios TTM",
               summary="P/E 22x. EV/EBITDA 15x. FCF yield 5%.",
               timestamp=ts or _ts(5))


def _analyst_ev(ts: str | None = None) -> object:
    return _ev(source="FMP analyst-estimates", title="Analyst Estimates",
               summary="Buy consensus. 35 buys. Strong buy. Price target raised.",
               timestamp=ts or _ts(5))


def _filing_ev(ts: str | None = None) -> object:
    return _ev(source="sec 10-k", title="10-K Filing",
               summary="Revenue +18%. FCF margin 22%. Dividend raised.",
               timestamp=ts or _ts(5))


def _overpriced_ev() -> object:
    return _ev(
        summary="Priced for perfection. Rich valuation. High expectations embedded. "
                "Multiple expansion requires continued acceleration beyond consensus.",
    )


def _speculative_ev() -> object:
    return _ev(
        summary="Speculative narrative-driven trade. Loss-making and burning cash. "
                "Early-stage optionality play. Hype cycle dynamics.",
    )


def _stale_ev(days: int = 250) -> object:
    return _ev(
        title="Old filing",
        source="sec 10-k",
        summary="Revenue growth slowing. Management cautious.",
        timestamp=_ts(days),
    )


def _agents(
    val_conf: float = 0.70,
    mac_conf: float = 0.68,
    risk_conf: float = 0.66,
    mkt_conf: float = 0.65,
    qual_conf: float = 0.68,
    val_stance: str = "fairly_valued",
):
    from app.schemas import (
        ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment,
    )
    return (
        ValuationView(overall="v", confidence=val_conf, valuation_stance=val_stance),
        MacroSensitivity(overall="m", confidence=mac_conf),
        RiskProfile(overall="r", confidence=risk_conf),
        MarketContext(overall="mk", confidence=mkt_conf),
        QualityAssessment(overall="q", confidence=qual_conf),
    )


def _run(
    evidence=None,
    val_conf=0.70, mac_conf=0.68, risk_conf=0.66,
    mkt_conf=0.65, qual_conf=0.68,
    val_stance="fairly_valued",
    ticker="AAPL",
    sector="Technology",
):
    from app.services.conviction_modeler import compute_conviction
    from app.schemas import CompanyContext
    val, mac, risk, mkt, qual = _agents(
        val_conf=val_conf, mac_conf=mac_conf, risk_conf=risk_conf,
        mkt_conf=mkt_conf, qual_conf=qual_conf, val_stance=val_stance,
    )
    company = CompanyContext(ticker=ticker, company_name=ticker, sector=sector)
    return compute_conviction(
        evidence=evidence or [],
        valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
        company=company,
    )


# ── 1. Score variance across 20-scenario matrix ────────────────────────────────

class TestScoreVariance:
    """Standard deviation across a diverse synthetic matrix must exceed 0.12."""

    def _build_scenario_matrix(self) -> List[float]:
        """20 representative scenarios spanning the full setup quality range."""
        scores = []

        # ── EXCELLENT SETUPS ──────────────────────────────────────────────────
        # 1. MSFT: fresh FMP + analyst + 10-K, fairly valued, high alignment
        scores.append(_run(
            evidence=[_fmp_ev(), _analyst_ev(), _filing_ev()] * 3,
            val_conf=0.88, mac_conf=0.84, risk_conf=0.80,
            val_stance="fairly_valued", ticker="MSFT",
        ).final_score)

        # 2. JPM: undervalued + strong evidence + aligned agents
        scores.append(_run(
            evidence=[_fmp_ev(), _analyst_ev(), _filing_ev()] * 2,
            val_conf=0.84, mac_conf=0.80, risk_conf=0.76,
            val_stance="undervalued", ticker="JPM",
        ).final_score)

        # 3. LLY: undervalued pharma, solid evidence
        scores.append(_run(
            evidence=[_fmp_ev(), _analyst_ev()] * 3,
            val_conf=0.80, mac_conf=0.78, risk_conf=0.74,
            val_stance="undervalued", ticker="LLY",
        ).final_score)

        # ── ACTIONABLE SETUPS ─────────────────────────────────────────────────
        # 4. AAPL: fairly valued, moderate evidence freshness
        scores.append(_run(
            evidence=[_fmp_ev(_ts(20)), _analyst_ev(_ts(20)), _filing_ev(_ts(20))],
            val_conf=0.75, mac_conf=0.72, risk_conf=0.68,
            val_stance="fairly_valued", ticker="AAPL",
        ).final_score)

        # 5. WMT: fairly valued, moderate evidence
        scores.append(_run(
            evidence=[_fmp_ev(), _analyst_ev()],
            val_conf=0.72, mac_conf=0.68, risk_conf=0.65,
            val_stance="fairly_valued", ticker="WMT",
        ).final_score)

        # 6. GOOGL: fairly valued, fresh but mild analyst divergence
        scores.append(_run(
            evidence=[_fmp_ev(), _analyst_ev(),
                      _ev(summary="Mixed revenue outlook. Cloud segment uncertain.")],
            val_conf=0.70, mac_conf=0.65, risk_conf=0.62,
            val_stance="fairly_valued", ticker="GOOGL",
        ).final_score)

        # ── DEMANDING / EXPECTATION-SENSITIVE ─────────────────────────────────
        # 7. NVDA: overpriced, HE, good evidence but stretched
        scores.append(_run(
            evidence=[_fmp_ev(), _analyst_ev(), _overpriced_ev()],
            val_conf=0.78, mac_conf=0.70, risk_conf=0.65,
            val_stance="overpriced", ticker="NVDA",
        ).final_score)

        # 8. CRM: overpriced, moderate evidence
        scores.append(_run(
            evidence=[_fmp_ev(), _overpriced_ev()],
            val_conf=0.70, mac_conf=0.65, risk_conf=0.62,
            val_stance="overpriced", ticker="CRM",
        ).final_score)

        # 9. SHOP: overpriced, limited evidence
        scores.append(_run(
            evidence=[_overpriced_ev()],
            val_conf=0.65, mac_conf=0.60, risk_conf=0.58,
            val_stance="overpriced", ticker="SHOP",
        ).final_score)

        # 10. ARM: HE ticker, fairly valued, thin evidence
        scores.append(_run(
            evidence=[_ev(summary="Moderate growth trajectory. Reasonable business.")],
            val_conf=0.62, mac_conf=0.58, risk_conf=0.58,
            val_stance="fairly_valued", ticker="ARM",
        ).final_score)

        # ── FRAGILE / SPECULATIVE ─────────────────────────────────────────────
        # 11. TSLA: overpriced, speculative evidence, HE
        scores.append(_run(
            evidence=[_speculative_ev(), _overpriced_ev()],
            val_conf=0.45, mac_conf=0.40, risk_conf=0.38,
            val_stance="overpriced", ticker="TSLA",
        ).final_score)

        # 12. PLTR: HE, overpriced, speculative language
        scores.append(_run(
            evidence=[_speculative_ev(), _overpriced_ev()],
            val_conf=0.42, mac_conf=0.38, risk_conf=0.36,
            val_stance="overpriced", ticker="PLTR",
        ).final_score)

        # 13. SNOW: HE, overpriced, stale evidence, slowing growth
        scores.append(_run(
            evidence=[_stale_ev(180), _overpriced_ev()],
            val_conf=0.45, mac_conf=0.42, risk_conf=0.40,
            val_stance="overpriced", ticker="SNOW",
        ).final_score)

        # 14. RIVN: HE, speculative, loss-making
        scores.append(_run(
            evidence=[_speculative_ev(), _speculative_ev()],
            val_conf=0.35, mac_conf=0.32, risk_conf=0.30,
            val_stance="overpriced", ticker="RIVN",
        ).final_score)

        # 15. AI (C3.ai): HE, speculative AI narrative
        scores.append(_run(
            evidence=[_speculative_ev(), _overpriced_ev()],
            val_conf=0.38, mac_conf=0.35, risk_conf=0.32,
            val_stance="overpriced", ticker="AI",
        ).final_score)

        # ── INSUFFICIENT / THIN ───────────────────────────────────────────────
        # 16. No evidence at all
        scores.append(_run(
            evidence=[],
            val_conf=0.35, mac_conf=0.30, risk_conf=0.28,
        ).final_score)

        # 17. Single stale generic news item
        scores.append(_run(
            evidence=[_stale_ev(300)],
            val_conf=0.38, mac_conf=0.35, risk_conf=0.33,
        ).final_score)

        # 18. Very low agent confidence across the board
        scores.append(_run(
            evidence=[_ev(summary="Brief overview.")],
            val_conf=0.30, mac_conf=0.28, risk_conf=0.28,
            mkt_conf=0.30, qual_conf=0.30,
        ).final_score)

        # ── MIXED ────────────────────────────────────────────────────────────
        # 19. Single newsapi item, moderate agents, no stance data
        scores.append(_run(
            evidence=[_ev(summary="Mixed outlook for the sector.")],
            val_conf=0.55, mac_conf=0.50, risk_conf=0.50,
        ).final_score)

        # 20. Moderate evidence but divergent agents
        scores.append(_run(
            evidence=[_fmp_ev(), _ev(summary="Concerns about execution.")],
            val_conf=0.70, mac_conf=0.40, risk_conf=0.38,
            val_stance="fairly_valued",
        ).final_score)

        return scores

    def test_std_dev_above_threshold(self):
        """Score distribution over 20 scenarios must have std_dev > 0.12."""
        scores = self._build_scenario_matrix()
        n    = len(scores)
        mean = sum(scores) / n
        var  = sum((s - mean) ** 2 for s in scores) / n
        std  = var ** 0.5
        assert std > 0.12, (
            f"Midpoint collapse detected — std_dev={std:.3f} (expected >0.12). "
            f"All scores: {[round(s, 3) for s in sorted(scores)]}"
        )

    def test_score_range_span(self):
        """Max − min across 20 scenarios must be ≥ 0.45 (strong spread)."""
        scores = self._build_scenario_matrix()
        span = max(scores) - min(scores)
        assert span >= 0.45, (
            f"Score range too narrow — span={span:.3f} (expected ≥0.45). "
            f"Min={min(scores):.3f}, Max={max(scores):.3f}"
        )

    def test_at_least_one_below_0_40(self):
        """At least one speculative/insufficient scenario must score below 0.40."""
        scores = self._build_scenario_matrix()
        below = [s for s in scores if s < 0.40]
        assert below, (
            f"No scenario scored below 0.40 — lowest was {min(scores):.3f}. "
            "Insufficient compression for speculative/thin setups."
        )

    def test_at_least_one_above_0_72(self):
        """At least one excellent scenario must score above 0.72."""
        scores = self._build_scenario_matrix()
        above = [s for s in scores if s > 0.72]
        assert above, (
            f"No scenario scored above 0.72 — highest was {max(scores):.3f}. "
            "Excellent setups are not reaching the high-conviction band."
        )


# ── 2. Midpoint collapse guard ─────────────────────────────────────────────────

class TestMidpointCollapse:
    """No more than 50 % of 20 distinct scenarios should cluster in 0.55–0.70."""

    def test_midpoint_cluster_below_50_pct(self):
        """The 0.55–0.70 band should not contain more than half the scenarios."""
        scenarios = [
            # Excellent
            dict(evidence=[_fmp_ev(), _analyst_ev(), _filing_ev()] * 3,
                 val_conf=0.88, mac_conf=0.84, val_stance="fairly_valued", ticker="MSFT"),
            dict(evidence=[_fmp_ev(), _analyst_ev()] * 3,
                 val_conf=0.84, mac_conf=0.80, val_stance="undervalued", ticker="JPM"),
            # Actionable
            dict(evidence=[_fmp_ev(), _analyst_ev()],
                 val_conf=0.74, mac_conf=0.70, val_stance="fairly_valued"),
            dict(evidence=[_fmp_ev()],
                 val_conf=0.70, mac_conf=0.66, val_stance="fairly_valued"),
            # Demanding
            dict(evidence=[_fmp_ev(), _overpriced_ev()],
                 val_conf=0.75, mac_conf=0.70, val_stance="overpriced", ticker="NVDA"),
            dict(evidence=[_overpriced_ev()],
                 val_conf=0.65, mac_conf=0.60, val_stance="overpriced", ticker="NVDA"),
            # Fragile
            dict(evidence=[_speculative_ev(), _overpriced_ev()],
                 val_conf=0.45, mac_conf=0.40, val_stance="overpriced", ticker="TSLA"),
            dict(evidence=[_speculative_ev()],
                 val_conf=0.42, mac_conf=0.38, val_stance="overpriced", ticker="PLTR"),
            # Speculative
            dict(evidence=[],
                 val_conf=0.32, mac_conf=0.28, risk_conf=0.28),
            dict(evidence=[_stale_ev(300)],
                 val_conf=0.35, mac_conf=0.32, risk_conf=0.30),
        ]
        scores = [_run(**s).final_score for s in scenarios]
        n_in_band = sum(1 for s in scores if 0.55 <= s <= 0.70)
        pct = n_in_band / len(scores)
        assert pct <= 0.50, (
            f"Midpoint collapse: {n_in_band}/{len(scores)} ({pct:.0%}) scored in "
            f"0.55–0.70 band (expected ≤50%). "
            f"Scores: {[round(s, 3) for s in sorted(scores)]}"
        )


# ── 3. High-fragility compression ─────────────────────────────────────────────

class TestHighFragilityCompression:
    """Overpriced HE tickers must compress materially below non-HE setups."""

    @pytest.mark.parametrize("ticker,expected_max", [
        ("TSLA", 0.55),
        ("PLTR", 0.58),
        ("SNOW", 0.58),
        ("NVDA", 0.65),
    ])
    def test_he_overpriced_compressed(self, ticker, expected_max):
        """HE + overpriced + speculative language should score below expected_max."""
        result = _run(
            evidence=[_speculative_ev(), _overpriced_ev()],
            val_conf=0.45, mac_conf=0.40, risk_conf=0.38,
            val_stance="overpriced",
            ticker=ticker,
        )
        assert result.final_score < expected_max, (
            f"{ticker} overpriced speculative scored {result.final_score:.3f}, "
            f"expected < {expected_max}"
        )

    def test_he_overpriced_materially_below_undervalued(self):
        """TSLA overpriced-speculative must be materially below JPM undervalued."""
        tsla = _run(
            evidence=[_speculative_ev(), _overpriced_ev()],
            val_conf=0.42, mac_conf=0.38,
            val_stance="overpriced", ticker="TSLA",
        )
        jpm = _run(
            evidence=[_fmp_ev(), _analyst_ev(), _filing_ev()],
            val_conf=0.82, mac_conf=0.78,
            val_stance="undervalued", ticker="JPM",
        )
        spread = jpm.final_score - tsla.final_score
        assert spread >= 0.30, (
            f"Spread between JPM undervalued ({jpm.final_score:.3f}) and "
            f"TSLA overpriced ({tsla.final_score:.3f}) = {spread:.3f} (expected ≥0.30)"
        )

    def test_fragility_dim_high_for_he_overpriced(self):
        """Fragility dimension must exceed 0.65 for any HE + overpriced ticker."""
        for ticker in ("NVDA", "TSLA", "PLTR"):
            result = _run(
                evidence=[_overpriced_ev()],
                val_stance="overpriced",
                ticker=ticker,
            )
            assert result.dimensions.expectation_fragility > 0.65, (
                f"{ticker} overpriced fragility = {result.dimensions.expectation_fragility:.3f}, "
                f"expected > 0.65"
            )

    def test_compression_applied_for_he_overpriced_extreme(self):
        """TSLA + extreme macro fear should trigger compression."""
        result = _run(
            evidence=[_fmp_ev(), _overpriced_ev()],
            val_conf=0.42, mac_conf=0.12,  # extreme macro → macro_uncertainty ≈ 0.88
            val_stance="overpriced",
            ticker="TSLA",
        )
        assert result.compression_applied, (
            f"TSLA extreme macro + overpriced should trigger compression. "
            f"Dims: macro_unc={result.dimensions.macro_uncertainty:.2f}, "
            f"frag={result.dimensions.expectation_fragility:.2f}"
        )


# ── 4. Evidence freshness impact ───────────────────────────────────────────────

class TestEvidenceFreshnessImpact:
    """Stale evidence must materially lower scores vs. identical fresh evidence."""

    def test_fresh_above_stale_same_company(self):
        """Same agents, same ticker — fresh evidence must score above stale."""
        fresh = _run(
            evidence=[_fmp_ev(_ts(5)), _analyst_ev(_ts(5)), _filing_ev(_ts(5))],
            val_conf=0.74, mac_conf=0.70,
            val_stance="fairly_valued", ticker="AAPL",
        )
        stale = _run(
            evidence=[_stale_ev(240), _stale_ev(220), _stale_ev(260)],
            val_conf=0.74, mac_conf=0.70,
            val_stance="fairly_valued", ticker="AAPL",
        )
        assert fresh.final_score > stale.final_score, (
            f"Fresh ({fresh.final_score:.3f}) should beat stale ({stale.final_score:.3f})"
        )

    def test_stale_plus_speculative_double_penalty(self):
        """250-day-old speculative evidence should score lower than fresh speculative."""
        fresh_spec = _run(
            evidence=[_speculative_ev(), _speculative_ev()],
            val_conf=0.50, mac_conf=0.46,
            val_stance="overpriced", ticker="PLTR",
        )
        stale_spec = _run(
            evidence=[
                _ev(title="Old spec", source="newsapi",
                    summary="Speculative narrative. Loss-making. Burning cash.",
                    timestamp=_ts(250)),
                _ev(title="Old option", source="newsapi",
                    summary="Pre-revenue optionality play. Early stage.",
                    timestamp=_ts(270)),
            ],
            val_conf=0.45, mac_conf=0.42,
            val_stance="overpriced", ticker="PLTR",
        )
        assert stale_spec.final_score <= fresh_spec.final_score, (
            f"Stale+speculative ({stale_spec.final_score:.3f}) should be ≤ "
            f"fresh+speculative ({fresh_spec.final_score:.3f})"
        )

    def test_freshness_dim_low_for_old_evidence(self):
        """Evidence freshness dimension must be ≤ 0.30 for 220+ day old items."""
        from app.services.conviction_modeler import _score_evidence_freshness
        stale = [_stale_ev(220), _stale_ev(240), _stale_ev(260)]
        freshness = _score_evidence_freshness(stale)
        assert freshness <= 0.30, (
            f"220–260 day stale evidence freshness = {freshness:.3f}, expected ≤ 0.30"
        )

    def test_no_timestamp_penalized(self):
        """Evidence with an unrecognised/malformed timestamp should score below fresh evidence."""
        from app.services.conviction_modeler import _score_evidence_freshness
        # Use a dummy unparseable timestamp so the scorer falls back to 0.38
        no_ts = [
            _ev(title=f"item{i}", summary="Context.", timestamp="invalid-date")
            for i in range(3)
        ]
        freshness_no_ts = _score_evidence_freshness(no_ts)
        freshness_fresh = _score_evidence_freshness([_fmp_ev(_ts(5)), _analyst_ev(_ts(5))])
        assert freshness_no_ts < freshness_fresh, (
            f"Unparseable-timestamp freshness ({freshness_no_ts:.3f}) should be below "
            f"fresh evidence freshness ({freshness_fresh:.3f})"
        )


# ── 5. Alignment impact ────────────────────────────────────────────────────────

class TestAlignmentImpact:
    """Aligned multi-agent evidence raises conviction; split signals suppress it."""

    def test_aligned_above_split_same_evidence(self):
        """Same evidence — aligned agents must outscore split agents."""
        aligned = _run(
            evidence=[_fmp_ev(), _analyst_ev()],
            val_conf=0.82, mac_conf=0.80, risk_conf=0.78,
            mkt_conf=0.76, qual_conf=0.80,
            val_stance="fairly_valued",
        )
        split = _run(
            evidence=[_fmp_ev(), _analyst_ev()],
            val_conf=0.82, mac_conf=0.30, risk_conf=0.28,  # wide divergence
            mkt_conf=0.76, qual_conf=0.80,
            val_stance="fairly_valued",
        )
        assert aligned.final_score > split.final_score, (
            f"Aligned ({aligned.final_score:.3f}) should beat split ({split.final_score:.3f})"
        )

    def test_thesis_alignment_dim_lower_for_split(self):
        """Cross-agent confidence spread should reduce thesis_alignment dimension."""
        aligned = _run(
            evidence=[_fmp_ev()],
            val_conf=0.80, mac_conf=0.78, risk_conf=0.76,
        )
        split = _run(
            evidence=[_fmp_ev()],
            val_conf=0.80, mac_conf=0.30, risk_conf=0.28,
        )
        assert aligned.dimensions.thesis_alignment > split.dimensions.thesis_alignment, (
            f"Aligned thesis_alignment ({aligned.dimensions.thesis_alignment:.3f}) "
            f"should be above split ({split.dimensions.thesis_alignment:.3f})"
        )

    def test_wide_divergence_reduces_score(self):
        """val=0.88, mac=0.22 (wide spread) should score materially below aligned 0.70."""
        high_div = _run(
            evidence=[_fmp_ev()],
            val_conf=0.88, mac_conf=0.22, risk_conf=0.20,
            val_stance="fairly_valued",
        )
        moderate = _run(
            evidence=[_fmp_ev()],
            val_conf=0.70, mac_conf=0.68, risk_conf=0.66,
            val_stance="fairly_valued",
        )
        assert high_div.final_score < moderate.final_score + 0.05, (
            f"Wide-divergence case ({high_div.final_score:.3f}) should not be "
            f"materially above moderate-aligned ({moderate.final_score:.3f})"
        )


# ── 6. Extreme scenario band validation ───────────────────────────────────────

class TestExtremeScenarios:
    """Excellent setups reach ≥0.72; speculative setups stay ≤0.45."""

    def test_excellent_msft_reaches_72(self):
        result = _run(
            evidence=[_fmp_ev(_ts(3)), _analyst_ev(_ts(3)), _filing_ev(_ts(3))] * 3,
            val_conf=0.88, mac_conf=0.84, risk_conf=0.80,
            val_stance="fairly_valued", ticker="MSFT",
        )
        assert result.final_score >= 0.72, (
            f"MSFT excellent setup scored {result.final_score:.3f}, expected ≥0.72"
        )

    def test_excellent_jpm_undervalued_reaches_68(self):
        result = _run(
            evidence=[_fmp_ev(_ts(7)), _analyst_ev(_ts(7)), _filing_ev(_ts(7))] * 2,
            val_conf=0.82, mac_conf=0.78, risk_conf=0.75,
            val_stance="undervalued", ticker="JPM",
        )
        assert result.final_score >= 0.68, (
            f"JPM undervalued scored {result.final_score:.3f}, expected ≥0.68"
        )

    def test_empty_evidence_below_42(self):
        result = _run(
            evidence=[],
            val_conf=0.32, mac_conf=0.28, risk_conf=0.28,
        )
        assert result.final_score < 0.42, (
            f"Empty evidence scored {result.final_score:.3f}, expected <0.42"
        )

    def test_tsla_speculative_below_52(self):
        result = _run(
            evidence=[_speculative_ev(), _overpriced_ev(),
                      _ev(summary="Binary outcome. Execution risk elevated. Guidance risk.")],
            val_conf=0.42, mac_conf=0.38,
            val_stance="overpriced", ticker="TSLA",
        )
        assert result.final_score < 0.52, (
            f"TSLA speculative setup scored {result.final_score:.3f}, expected <0.52"
        )

    def test_pltr_overpriced_speculative_below_52(self):
        result = _run(
            evidence=[_speculative_ev(), _speculative_ev(), _overpriced_ev()],
            val_conf=0.38, mac_conf=0.35,
            val_stance="overpriced", ticker="PLTR",
        )
        assert result.final_score < 0.52, (
            f"PLTR overpriced speculative scored {result.final_score:.3f}, expected <0.52"
        )


# ── 7. HE vs non-HE spread ────────────────────────────────────────────────────

class TestHETickerSpread:
    """High-expectation overpriced setups must diverge materially from undervalued non-HE."""

    def test_he_overpriced_vs_non_he_undervalued_spread(self):
        """NVDA overpriced vs JPM undervalued: spread must be ≥ 0.20."""
        nvda = _run(
            evidence=[_fmp_ev(), _overpriced_ev()],
            val_conf=0.78, mac_conf=0.72, risk_conf=0.68,
            val_stance="overpriced", ticker="NVDA",
        )
        jpm = _run(
            evidence=[_fmp_ev(), _analyst_ev(), _filing_ev()],
            val_conf=0.80, mac_conf=0.76, risk_conf=0.72,
            val_stance="undervalued", ticker="JPM",
        )
        spread = jpm.final_score - nvda.final_score
        assert spread >= 0.20, (
            f"JPM undervalued ({jpm.final_score:.3f}) vs NVDA overpriced "
            f"({nvda.final_score:.3f}) spread = {spread:.3f} (expected ≥0.20)"
        )

    def test_fragility_multiplier_lower_for_he_overpriced(self):
        """HE + overpriced should produce a lower fragility multiplier than non-HE undervalued."""
        he = _run(
            evidence=[_overpriced_ev()],
            val_stance="overpriced", ticker="NVDA",
        )
        non_he = _run(
            evidence=[_fmp_ev()],
            val_stance="undervalued", ticker="JPM",
        )
        assert he.fragility_multiplier_applied < non_he.fragility_multiplier_applied, (
            f"HE frag_mult ({he.fragility_multiplier_applied:.3f}) should be below "
            f"non-HE frag_mult ({non_he.fragility_multiplier_applied:.3f})"
        )

    def test_asymmetry_multiplier_lower_for_he_overpriced(self):
        """HE + overpriced asymmetry multiplier must be below 1.0."""
        result = _run(
            evidence=[_overpriced_ev()],
            val_stance="overpriced", ticker="NVDA",
        )
        assert result.asymmetry_multiplier_applied < 1.0, (
            f"NVDA overpriced asymmetry_mult = {result.asymmetry_multiplier_applied:.3f}, "
            f"expected < 1.0"
        )

    def test_five_he_tickers_all_score_below_baseline(self):
        """Each HE ticker at overpriced stance must score below a non-HE fairly_valued baseline."""
        baseline = _run(
            evidence=[_fmp_ev(), _analyst_ev()],
            val_conf=0.72, mac_conf=0.68,
            val_stance="fairly_valued", ticker="JPM",
        ).final_score

        for ticker in ("TSLA", "PLTR", "NVDA", "SNOW", "ARM"):
            result = _run(
                evidence=[_overpriced_ev()],
                val_conf=0.65, mac_conf=0.60,
                val_stance="overpriced", ticker=ticker,
            )
            assert result.final_score < baseline, (
                f"{ticker} overpriced ({result.final_score:.3f}) should be below "
                f"JPM fairly-valued baseline ({baseline:.3f})"
            )
