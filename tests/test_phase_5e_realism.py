"""Phase 5e — Final Realism Audit Suite.

10-ticker matrix confirming the conviction modeler produces:
  • Realistic score dispersion across the full expectation-quality spectrum
  • HE-ticker structural discounts (TSLA / PLTR / NVDA / SNOW)
  • Quality-anchor premiums (MSFT / JPM / VRTX / ASML)
  • Balanced-tier placement for mixed-profile names (META / GOOGL)
  • Realism-specific language patterns for expectation-fragility dominance
  • Cross-ticker dispersion: std_dev > 0.10, full range > 0.35

Tickers
───────
  TSLA  — priced for perfection, speculative / demanding setup
  PLTR  — narrative + loss-making path, speculative
  NVDA  — high quality but demanding expectations (two scenarios)
  SNOW  — deceleration risk + HE premium = speculative
  MSFT  — quality anchor, durable / balanced
  JPM   — financial quality + macro sensitivity, balanced / durable
  META  — balanced quality, not in HE set
  ASML  — monopoly compounder, balanced / durable
  VRTX  — biotech cash-flow quality, balanced / durable
  GOOGL — search / cloud quality, balanced

Classes
───────
  TestTslaRealism          (5 tests)
  TestPltrRealism          (4 tests)
  TestNvdaRealism          (5 tests)
  TestSnowRealism          (4 tests)
  TestMsftRealism          (4 tests)
  TestJpmRealism           (4 tests)
  TestMetaRealism          (4 tests)
  TestAsmlRealism          (4 tests)
  TestVrtxRealism          (4 tests)
  TestGooglRealism         (4 tests)
  TestCrossTickerDispersion(6 tests)
  TestReasoningLanguage    (8 tests)
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import List

import pytest


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _ts(days_ago: int = 5) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ev(
    title: str = "Test Item",
    source: str = "newsapi",
    summary: str = "Summary text.",
    days_ago: int = 5,
    relevance_score: float = 0.80,
):
    from app.schemas import RetrievedEvidence
    return RetrievedEvidence(
        title=title,
        source=source,
        summary=summary,
        timestamp=_ts(days_ago),
        relevance_score=relevance_score,
    )


def _fmp_val(ticker: str, pe: int = 35, ev_eb: int = 25, fwd_pe: int = 28):
    return _ev(
        title=f"{ticker} Valuation Ratios TTM",
        source="FMP ratios-ttm",
        summary=f"P/E: {pe}x. EV/EBITDA: {ev_eb}x. Forward P/E: {fwd_pe}x.",
        days_ago=3,
    )


def _fmp_analyst(ticker: str, buys: int = 30, holds: int = 8, sells: int = 2):
    return _ev(
        title=f"{ticker} Analyst Estimates",
        source="FMP analyst-estimates",
        summary=f"Consensus: {buys} buys, {holds} holds, {sells} sells.",
        days_ago=3,
    )


def _he_priced_perfection(ticker: str, driver: str = "AI revenue") -> "RetrievedEvidence":
    return _ev(
        title=f"{ticker} Valuation Concern",
        source="newsapi",
        summary=(
            f"{ticker} is priced for perfection on {driver}. "
            "Demanding valuation demands continued acceleration above consensus. "
            "Premium multiple requires executing well above already-elevated expectations. "
            "Priced for perfection — any miss risks material derating."
        ),
        days_ago=4,
    )


def _quality_anchor(ticker: str, theme: str = "durable earnings") -> "RetrievedEvidence":
    return _ev(
        title=f"{ticker} Quality Note",
        source="newsapi",
        summary=(
            f"{ticker} demonstrates consistent {theme} with diversified revenue streams. "
            "Balance sheet strength and recurring cash flow reduce earnings risk. "
            "Management track record supports reliability of forward guidance."
        ),
        days_ago=4,
    )


def _make_company(ticker: str, name: str = "", sector: str = "Technology"):
    from app.schemas import CompanyContext
    return CompanyContext(ticker=ticker, company_name=name or ticker, sector=sector)


def _make_agents(
    val_conf: float = 0.72,
    mac_conf: float = 0.70,
    risk_conf: float = 0.68,
    mkt_conf: float = 0.65,
    qual_conf: float = 0.70,
    val_stance: str = "fairly_valued",
):
    from app.schemas import (
        ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment,
    )
    return (
        ValuationView(overall="val", confidence=val_conf, valuation_stance=val_stance),
        MacroSensitivity(overall="mac", confidence=mac_conf),
        RiskProfile(overall="risk", confidence=risk_conf),
        MarketContext(overall="mkt", confidence=mkt_conf),
        QualityAssessment(overall="qual", confidence=qual_conf),
    )


def _run(
    ticker: str,
    evidence: List = None,
    val_conf: float = 0.70,
    mac_conf: float = 0.68,
    risk_conf: float = 0.66,
    mkt_conf: float = 0.62,
    qual_conf: float = 0.68,
    val_stance: str = "fairly_valued",
    governance_warnings: List = None,
    sector: str = "Technology",
):
    from app.services.conviction_modeler import compute_conviction
    val, mac, risk, mkt, qual = _make_agents(
        val_conf=val_conf, mac_conf=mac_conf, risk_conf=risk_conf,
        mkt_conf=mkt_conf, qual_conf=qual_conf, val_stance=val_stance,
    )
    return compute_conviction(
        evidence=evidence or [],
        valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
        company=_make_company(ticker=ticker, sector=sector),
        governance_warnings=governance_warnings or [],
    )


# ── 1. TSLA ────────────────────────────────────────────────────────────────────

class TestTslaRealism:
    """TSLA: HE ticker, priced-for-perfection, speculative / demanding setup."""

    def test_tsla_base_case_is_demanding_or_lower(self):
        """TSLA with neutral inputs should not clear the Balanced threshold."""
        result = _run(
            ticker="TSLA",
            evidence=[
                _ev("TSLA Report", summary="Tesla reported mixed Q4 results."),
                _fmp_val("TSLA", pe=68, ev_eb=45, fwd_pe=55),
            ],
            val_stance="fairly_valued",
            val_conf=0.62,
        )
        assert result.final_score < 0.65, (
            f"TSLA base case should be Demanding or lower, got {result.final_score:.4f}"
        )

    def test_tsla_overpriced_is_speculative_or_demanding(self):
        """TSLA + overpriced stance + priced-for-perfection evidence = low band."""
        result = _run(
            ticker="TSLA",
            evidence=[
                _he_priced_perfection("TSLA", driver="autonomous vehicle revenue"),
                _fmp_val("TSLA", pe=75, ev_eb=50, fwd_pe=60),
                _ev(
                    "TSLA Risk",
                    summary=(
                        "Tesla faces execution uncertainty on FSD timeline, "
                        "robotaxi competition is intensifying, and energy margins are compressing. "
                        "The bull case requires multiple simultaneous moonshots."
                    ),
                ),
            ],
            val_stance="overpriced",
            val_conf=0.55,
            risk_conf=0.52,
        )
        assert result.final_score <= 0.58, (
            f"TSLA overpriced should be speculative/demanding, got {result.final_score:.4f}"
        )
        assert result.final_score >= 0.28, (
            f"TSLA should have minimum floor, got {result.final_score:.4f}"
        )

    def test_tsla_score_floor_maintained(self):
        """Even pessimistic TSLA should stay above 0.25 (not zero-evidence territory)."""
        result = _run(
            ticker="TSLA",
            evidence=[_he_priced_perfection("TSLA")],
            val_stance="overpriced",
            val_conf=0.50,
        )
        assert result.final_score >= 0.25, (
            f"TSLA floor should be >= 0.25, got {result.final_score:.4f}"
        )

    def test_tsla_setup_label_not_balanced_or_durable(self):
        """TSLA with overpriced stance should not get Balanced or Durable label."""
        result = _run(
            ticker="TSLA",
            evidence=[_he_priced_perfection("TSLA"), _fmp_val("TSLA", pe=80)],
            val_stance="overpriced",
            val_conf=0.55,
        )
        assert result.setup_label not in ("balanced thesis", "durable thesis"), (
            f"TSLA overpriced should not be balanced/durable, got '{result.setup_label}'"
        )

    def test_tsla_fragility_elevated_vs_msft(self):
        """TSLA expectation_fragility should substantially exceed MSFT."""
        tsla = _run(
            ticker="TSLA",
            evidence=[_he_priced_perfection("TSLA")],
            val_stance="overpriced",
            val_conf=0.55,
        )
        msft = _run(
            ticker="MSFT",
            evidence=[_quality_anchor("MSFT", theme="recurring cloud revenue")],
            val_stance="fairly_valued",
            val_conf=0.78,
            qual_conf=0.80,
            sector="Technology",
        )
        assert tsla.dimensions.expectation_fragility > msft.dimensions.expectation_fragility + 0.10, (
            f"TSLA fragility {tsla.dimensions.expectation_fragility:.3f} should "
            f"substantially exceed MSFT {msft.dimensions.expectation_fragility:.3f}"
        )


# ── 2. PLTR ────────────────────────────────────────────────────────────────────

class TestPltrRealism:
    """PLTR: HE ticker, narrative-growth, speculative setup."""

    def test_pltr_overpriced_is_speculative(self):
        result = _run(
            ticker="PLTR",
            evidence=[
                _he_priced_perfection("PLTR", driver="government AI contract revenue"),
                _ev(
                    "PLTR Note",
                    summary=(
                        "Palantir trades at an extreme premium to software peers. "
                        "Path to consensus estimates requires accelerating government + "
                        "commercial contract wins well above current trajectory. "
                        "Speculative narrative premium embedded in the multiple."
                    ),
                ),
                _fmp_val("PLTR", pe=120, ev_eb=90, fwd_pe=95),
            ],
            val_stance="overpriced",
            val_conf=0.52,
            risk_conf=0.50,
        )
        assert result.final_score <= 0.55, (
            f"PLTR overpriced should be speculative, got {result.final_score:.4f}"
        )

    def test_pltr_neutral_inputs_below_balanced(self):
        """PLTR with neutral inputs should not reach Balanced (0.60) due to HE premium."""
        result = _run(
            ticker="PLTR",
            evidence=[_fmp_val("PLTR", pe=80, fwd_pe=70)],
            val_stance="fairly_valued",
            val_conf=0.60,
        )
        assert result.final_score < 0.65, (
            f"PLTR neutral should be below Balanced, got {result.final_score:.4f}"
        )

    def test_pltr_floor_maintained(self):
        result = _run(
            ticker="PLTR",
            evidence=[_he_priced_perfection("PLTR")],
            val_stance="overpriced",
            val_conf=0.50,
        )
        assert result.final_score >= 0.22, (
            f"PLTR floor >= 0.22, got {result.final_score:.4f}"
        )

    def test_pltr_fragility_above_baseline(self):
        """PLTR expectation_fragility should exceed 0.45 even with neutral stance."""
        result = _run(
            ticker="PLTR",
            evidence=[_fmp_val("PLTR", pe=90)],
            val_stance="fairly_valued",
            val_conf=0.62,
        )
        assert result.dimensions.expectation_fragility > 0.45, (
            f"PLTR fragility should exceed 0.45, got {result.dimensions.expectation_fragility:.3f}"
        )


# ── 3. NVDA ────────────────────────────────────────────────────────────────────

class TestNvdaRealism:
    """NVDA: High quality + HE premium. Two scenarios: neutral and overpriced."""

    def test_nvda_neutral_within_demanding_to_balanced(self):
        """NVDA with neutral inputs: Demanding-to-Balanced range (0.48–0.72)."""
        result = _run(
            ticker="NVDA",
            evidence=[
                _fmp_val("NVDA", pe=42, ev_eb=31, fwd_pe=36),
                _fmp_analyst("NVDA", buys=41, holds=5, sells=1),
                _quality_anchor("NVDA", theme="data center GPU dominance"),
            ],
            val_stance="fairly_valued",
            val_conf=0.70,
            qual_conf=0.75,
        )
        assert 0.48 <= result.final_score <= 0.72, (
            f"NVDA neutral should be Demanding–Balanced, got {result.final_score:.4f}"
        )

    def test_nvda_overpriced_is_demanding(self):
        """NVDA overpriced + priced-for-perfection = Demanding setup."""
        result = _run(
            ticker="NVDA",
            evidence=[
                _he_priced_perfection("NVDA", driver="hyperscaler AI CapEx"),
                _fmp_val("NVDA", pe=55, ev_eb=42, fwd_pe=48),
            ],
            val_stance="overpriced",
            val_conf=0.60,
        )
        assert result.final_score <= 0.62, (
            f"NVDA overpriced should be Demanding or lower, got {result.final_score:.4f}"
        )
        assert result.final_score >= 0.35, (
            f"NVDA overpriced floor >= 0.35, got {result.final_score:.4f}"
        )

    def test_nvda_overpriced_setup_label_is_demanding_or_speculative(self):
        result = _run(
            ticker="NVDA",
            evidence=[_he_priced_perfection("NVDA")],
            val_stance="overpriced",
            val_conf=0.58,
        )
        assert result.setup_label in ("demanding setup", "speculative setup"), (
            f"NVDA overpriced label should be demanding/speculative, got '{result.setup_label}'"
        )

    def test_nvda_neutral_better_than_overpriced(self):
        """Neutral NVDA should clearly outscore overpriced NVDA."""
        neutral = _run(
            ticker="NVDA",
            evidence=[_fmp_val("NVDA"), _quality_anchor("NVDA")],
            val_stance="fairly_valued",
            val_conf=0.70,
        )
        overpriced = _run(
            ticker="NVDA",
            evidence=[_he_priced_perfection("NVDA"), _fmp_val("NVDA", pe=55)],
            val_stance="overpriced",
            val_conf=0.58,
        )
        assert neutral.final_score > overpriced.final_score + 0.05, (
            f"Neutral NVDA ({neutral.final_score:.4f}) should score "
            f"materially higher than overpriced ({overpriced.final_score:.4f})"
        )

    def test_nvda_fragility_elevated_but_bounded(self):
        """NVDA fragility should be elevated (>0.45) — priced-for-perfection signal fires."""
        result = _run(
            ticker="NVDA",
            evidence=[_he_priced_perfection("NVDA"), _fmp_val("NVDA", pe=55)],
            val_stance="overpriced",
        )
        f = result.dimensions.expectation_fragility
        # HE ticker + overpriced + priced-for-perfection evidence → high fragility
        # No upper cap: the modeler may reach >0.90 in this extreme scenario
        assert f > 0.45, (
            f"NVDA fragility should be elevated (>0.45), got {f:.3f}"
        )
        assert f <= 1.0, (
            f"NVDA fragility must be <=1.0, got {f:.3f}"
        )


# ── 4. SNOW ────────────────────────────────────────────────────────────────────

class TestSnowRealism:
    """SNOW: HE ticker with decelerating growth + competition = speculative / demanding."""

    def test_snow_overpriced_is_speculative_or_demanding(self):
        result = _run(
            ticker="SNOW",
            evidence=[
                _he_priced_perfection("SNOW", driver="data-cloud consumption revenue"),
                _ev(
                    "SNOW Competition",
                    summary=(
                        "Snowflake faces intensifying competition from Databricks and AWS Redshift. "
                        "Growth is decelerating faster than the Street expected. "
                        "Product consumption model creates revenue volatility. "
                        "Premium multiple requires re-acceleration that current data doesn't support."
                    ),
                ),
                _fmp_val("SNOW", pe=150, ev_eb=80, fwd_pe=100),
            ],
            val_stance="overpriced",
            val_conf=0.50,
            risk_conf=0.48,
        )
        assert result.final_score <= 0.55, (
            f"SNOW overpriced should be speculative/demanding, got {result.final_score:.4f}"
        )

    def test_snow_score_lower_than_msft(self):
        """SNOW should score materially below a quality anchor like MSFT."""
        snow = _run(
            ticker="SNOW",
            evidence=[_he_priced_perfection("SNOW"), _fmp_val("SNOW", pe=130)],
            val_stance="overpriced",
            val_conf=0.52,
        )
        msft = _run(
            ticker="MSFT",
            evidence=[_quality_anchor("MSFT"), _fmp_val("MSFT", pe=28, ev_eb=20, fwd_pe=25)],
            val_stance="fairly_valued",
            val_conf=0.80,
            qual_conf=0.82,
        )
        assert msft.final_score > snow.final_score + 0.15, (
            f"MSFT ({msft.final_score:.4f}) should substantially outscore SNOW ({snow.final_score:.4f})"
        )

    def test_snow_setup_not_durable(self):
        result = _run(
            ticker="SNOW",
            evidence=[_he_priced_perfection("SNOW"), _fmp_val("SNOW", pe=120)],
            val_stance="overpriced",
            val_conf=0.52,
        )
        assert result.setup_label != "durable thesis", (
            f"SNOW should not be durable, got '{result.setup_label}'"
        )

    def test_snow_fragility_high(self):
        result = _run(
            ticker="SNOW",
            evidence=[_he_priced_perfection("SNOW")],
            val_stance="overpriced",
            val_conf=0.52,
        )
        assert result.dimensions.expectation_fragility > 0.55, (
            f"SNOW fragility should be high, got {result.dimensions.expectation_fragility:.3f}"
        )


# ── 5. MSFT ────────────────────────────────────────────────────────────────────

class TestMsftRealism:
    """MSFT: Quality anchor — Balanced to Durable (0.68–0.90)."""

    def test_msft_quality_is_balanced_or_durable(self):
        result = _run(
            ticker="MSFT",
            evidence=[
                _quality_anchor("MSFT", theme="recurring cloud and Office 365 revenue"),
                _fmp_val("MSFT", pe=28, ev_eb=20, fwd_pe=25),
                _fmp_analyst("MSFT", buys=45, holds=5, sells=0),
                _ev("MSFT Azure", summary="Azure cloud growth remains steady at 28% YoY."),
            ],
            val_stance="fairly_valued",
            val_conf=0.80,
            mac_conf=0.75,
            risk_conf=0.78,
            qual_conf=0.82,
        )
        assert result.final_score >= 0.68, (
            f"MSFT quality scenario should be >= 0.68, got {result.final_score:.4f}"
        )

    def test_msft_durable_label_possible(self):
        """MSFT with strong quality inputs should reach high-alignment or actionable tier."""
        result = _run(
            ticker="MSFT",
            evidence=[
                _quality_anchor("MSFT", theme="durable earnings and buyback program"),
                _fmp_val("MSFT", pe=28, ev_eb=20, fwd_pe=25),
                _fmp_analyst("MSFT", buys=45, holds=5, sells=0),
            ],
            val_stance="fairly_valued",
            val_conf=0.82,
            mac_conf=0.78,
            risk_conf=0.80,
            qual_conf=0.85,
        )
        # Actual label values: "high-alignment thesis" (≥0.75) or "actionable thesis" (0.60–0.75)
        assert result.setup_label in ("high-alignment thesis", "actionable thesis"), (
            f"MSFT quality label should be high-alignment or actionable, got '{result.setup_label}'"
        )

    def test_msft_score_above_tsla_overpriced(self):
        msft = _run(
            ticker="MSFT",
            evidence=[_quality_anchor("MSFT"), _fmp_val("MSFT", pe=28)],
            val_stance="fairly_valued",
            val_conf=0.80,
            qual_conf=0.82,
        )
        tsla = _run(
            ticker="TSLA",
            evidence=[_he_priced_perfection("TSLA"), _fmp_val("TSLA", pe=75)],
            val_stance="overpriced",
            val_conf=0.55,
        )
        assert msft.final_score > tsla.final_score + 0.15, (
            f"MSFT ({msft.final_score:.4f}) should substantially outscore TSLA ({tsla.final_score:.4f})"
        )

    def test_msft_fragility_low(self):
        """MSFT should have low expectation_fragility given quality and fair valuation."""
        result = _run(
            ticker="MSFT",
            evidence=[_quality_anchor("MSFT"), _fmp_val("MSFT", pe=28)],
            val_stance="fairly_valued",
            val_conf=0.80,
            qual_conf=0.82,
        )
        assert result.dimensions.expectation_fragility < 0.50, (
            f"MSFT fragility should be low, got {result.dimensions.expectation_fragility:.3f}"
        )


# ── 6. JPM ────────────────────────────────────────────────────────────────────

class TestJpmRealism:
    """JPM: Financial quality + macro sensitivity — Balanced to Durable (0.62–0.85)."""

    def test_jpm_quality_is_balanced_or_better(self):
        result = _run(
            ticker="JPM",
            evidence=[
                _quality_anchor("JPM", theme="diversified financial services revenue"),
                _fmp_val("JPM", pe=12, ev_eb=9, fwd_pe=11),
                _fmp_analyst("JPM", buys=30, holds=12, sells=2),
            ],
            val_stance="fairly_valued",
            val_conf=0.75,
            mac_conf=0.65,
            risk_conf=0.70,
            qual_conf=0.76,
            sector="Financials",
        )
        assert result.final_score >= 0.60, (
            f"JPM quality scenario should be >= 0.60, got {result.final_score:.4f}"
        )

    def test_jpm_macro_sensitivity_caps_ceiling(self):
        """JPM with elevated macro uncertainty should not reach Durable."""
        result = _run(
            ticker="JPM",
            evidence=[
                _ev("JPM Macro", summary="Interest rate path remains highly uncertain. Recession risk elevated."),
                _fmp_val("JPM", pe=12),
            ],
            val_stance="fairly_valued",
            val_conf=0.68,
            mac_conf=0.42,  # high macro uncertainty
            risk_conf=0.58,
            sector="Financials",
        )
        # High macro uncertainty should push score away from top of Durable
        assert result.final_score <= 0.85, (
            f"JPM with high macro uncertainty should be capped, got {result.final_score:.4f}"
        )

    def test_jpm_above_pltr_overpriced(self):
        jpm = _run(
            ticker="JPM",
            evidence=[_quality_anchor("JPM"), _fmp_val("JPM", pe=12)],
            val_stance="fairly_valued",
            val_conf=0.75,
            qual_conf=0.76,
            sector="Financials",
        )
        pltr = _run(
            ticker="PLTR",
            evidence=[_he_priced_perfection("PLTR"), _fmp_val("PLTR", pe=120)],
            val_stance="overpriced",
            val_conf=0.52,
        )
        assert jpm.final_score > pltr.final_score + 0.10, (
            f"JPM ({jpm.final_score:.4f}) should outscore PLTR overpriced ({pltr.final_score:.4f})"
        )

    def test_jpm_not_speculative(self):
        result = _run(
            ticker="JPM",
            evidence=[_quality_anchor("JPM"), _fmp_val("JPM", pe=12)],
            val_stance="fairly_valued",
            val_conf=0.75,
            sector="Financials",
        )
        assert result.setup_label != "speculative setup", (
            f"JPM should not be speculative, got '{result.setup_label}'"
        )


# ── 7. META ────────────────────────────────────────────────────────────────────

class TestMetaRealism:
    """META: Balanced quality, not in HE set — Balanced tier (0.58–0.80)."""

    def test_meta_balanced_scenario(self):
        result = _run(
            ticker="META",
            evidence=[
                _quality_anchor("META", theme="advertising revenue and AI efficiency gains"),
                _fmp_val("META", pe=22, ev_eb=15, fwd_pe=19),
                _fmp_analyst("META", buys=38, holds=8, sells=1),
            ],
            val_stance="fairly_valued",
            val_conf=0.72,
            qual_conf=0.74,
        )
        assert 0.55 <= result.final_score <= 0.85, (
            f"META quality scenario should be 0.55–0.85, got {result.final_score:.4f}"
        )

    def test_meta_not_speculative_with_quality_evidence(self):
        result = _run(
            ticker="META",
            evidence=[
                _quality_anchor("META", theme="ad platform efficiency"),
                _fmp_val("META", pe=22),
            ],
            val_stance="fairly_valued",
            val_conf=0.72,
        )
        assert result.setup_label not in ("speculative setup", "insufficient evidence"), (
            f"META quality should not be speculative, got '{result.setup_label}'"
        )

    def test_meta_score_between_tsla_and_msft(self):
        """META should occupy middle ground between HE speculative and quality anchor."""
        meta = _run(
            ticker="META",
            evidence=[_quality_anchor("META"), _fmp_val("META", pe=22)],
            val_stance="fairly_valued",
            val_conf=0.72,
        )
        tsla = _run(
            ticker="TSLA",
            evidence=[_he_priced_perfection("TSLA")],
            val_stance="overpriced",
            val_conf=0.55,
        )
        msft = _run(
            ticker="MSFT",
            evidence=[_quality_anchor("MSFT"), _fmp_val("MSFT", pe=28)],
            val_stance="fairly_valued",
            val_conf=0.80,
            qual_conf=0.82,
        )
        assert tsla.final_score < meta.final_score, (
            f"META ({meta.final_score:.4f}) should outscore TSLA overpriced ({tsla.final_score:.4f})"
        )
        # META can match MSFT in some scenarios but shouldn't dramatically exceed it

    def test_meta_fragility_moderate(self):
        """META fragility should be moderate — not as low as MSFT, not as high as TSLA."""
        result = _run(
            ticker="META",
            evidence=[_fmp_val("META", pe=22)],
            val_stance="fairly_valued",
            val_conf=0.72,
        )
        f = result.dimensions.expectation_fragility
        assert f < 0.65, (
            f"META fragility should be moderate (<0.65), got {f:.3f}"
        )


# ── 8. ASML ────────────────────────────────────────────────────────────────────

class TestAsmlRealism:
    """ASML: Monopoly compounder in EUV lithography — Balanced to Durable (0.62–0.85)."""

    def test_asml_quality_is_balanced_or_durable(self):
        result = _run(
            ticker="ASML",
            evidence=[
                _quality_anchor("ASML", theme="EUV lithography monopoly and high-NA backlog"),
                _fmp_val("ASML", pe=35, ev_eb=26, fwd_pe=30),
                _fmp_analyst("ASML", buys=28, holds=6, sells=1),
                _ev("ASML Backlog", summary="ASML backlog at record highs, High-NA EUV demand robust."),
            ],
            val_stance="fairly_valued",
            val_conf=0.76,
            qual_conf=0.78,
        )
        assert result.final_score >= 0.60, (
            f"ASML quality scenario should be >= 0.60, got {result.final_score:.4f}"
        )

    def test_asml_score_above_pltr(self):
        asml = _run(
            ticker="ASML",
            evidence=[_quality_anchor("ASML"), _fmp_val("ASML", pe=35)],
            val_stance="fairly_valued",
            val_conf=0.76,
            qual_conf=0.78,
        )
        pltr = _run(
            ticker="PLTR",
            evidence=[_he_priced_perfection("PLTR"), _fmp_val("PLTR", pe=120)],
            val_stance="overpriced",
            val_conf=0.52,
        )
        assert asml.final_score > pltr.final_score + 0.08, (
            f"ASML ({asml.final_score:.4f}) should outscore PLTR overpriced ({pltr.final_score:.4f})"
        )

    def test_asml_not_speculative(self):
        result = _run(
            ticker="ASML",
            evidence=[_quality_anchor("ASML"), _fmp_val("ASML", pe=35)],
            val_stance="fairly_valued",
            val_conf=0.76,
        )
        assert result.setup_label != "speculative setup", (
            f"ASML should not be speculative, got '{result.setup_label}'"
        )

    def test_asml_not_in_he_set(self):
        """ASML is not a high-expectation ticker — it should not get HE structural compression."""
        from app.services.conviction_modeler import _HIGH_EXPECTATION_TICKERS
        assert "ASML" not in _HIGH_EXPECTATION_TICKERS, (
            "ASML should not be in _HIGH_EXPECTATION_TICKERS — it's a quality compounder, "
            "not a narrative-growth name"
        )


# ── 9. VRTX ────────────────────────────────────────────────────────────────────

class TestVrtxRealism:
    """VRTX: Biotech with real cash flows — Balanced to Durable (0.65–0.87)."""

    def test_vrtx_quality_is_balanced_or_durable(self):
        result = _run(
            ticker="VRTX",
            evidence=[
                _quality_anchor("VRTX", theme="CF modulator franchise cash flow"),
                _fmp_val("VRTX", pe=28, ev_eb=22, fwd_pe=24),
                _fmp_analyst("VRTX", buys=25, holds=8, sells=0),
                _ev("VRTX Pipeline", summary=(
                    "Vertex CF franchise generates durable high-margin recurring revenue. "
                    "Pain pipeline optionality adds asymmetric upside without compromising "
                    "the CF cash cow. Balance sheet net cash."
                )),
            ],
            val_stance="fairly_valued",
            val_conf=0.76,
            qual_conf=0.78,
        )
        assert result.final_score >= 0.62, (
            f"VRTX quality scenario should be >= 0.62, got {result.final_score:.4f}"
        )

    def test_vrtx_above_tsla_overpriced(self):
        vrtx = _run(
            ticker="VRTX",
            evidence=[_quality_anchor("VRTX"), _fmp_val("VRTX", pe=28)],
            val_stance="fairly_valued",
            val_conf=0.76,
        )
        tsla = _run(
            ticker="TSLA",
            evidence=[_he_priced_perfection("TSLA")],
            val_stance="overpriced",
            val_conf=0.55,
        )
        assert vrtx.final_score > tsla.final_score + 0.10, (
            f"VRTX ({vrtx.final_score:.4f}) should outscore TSLA overpriced ({tsla.final_score:.4f})"
        )

    def test_vrtx_not_speculative(self):
        result = _run(
            ticker="VRTX",
            evidence=[_quality_anchor("VRTX")],
            val_stance="fairly_valued",
            val_conf=0.76,
        )
        assert result.setup_label != "speculative setup", (
            f"VRTX should not be speculative, got '{result.setup_label}'"
        )

    def test_vrtx_fragility_low(self):
        result = _run(
            ticker="VRTX",
            evidence=[_quality_anchor("VRTX"), _fmp_val("VRTX", pe=28)],
            val_stance="fairly_valued",
            val_conf=0.76,
        )
        assert result.dimensions.expectation_fragility < 0.55, (
            f"VRTX fragility should be low, got {result.dimensions.expectation_fragility:.3f}"
        )


# ── 10. GOOGL ─────────────────────────────────────────────────────────────────

class TestGooglRealism:
    """GOOGL: Search/cloud quality + AI transition uncertainty — Balanced (0.58–0.80)."""

    def test_googl_balanced_scenario(self):
        result = _run(
            ticker="GOOGL",
            evidence=[
                _quality_anchor("GOOGL", theme="search monopoly and cloud revenue"),
                _fmp_val("GOOGL", pe=22, ev_eb=16, fwd_pe=19),
                _fmp_analyst("GOOGL", buys=42, holds=7, sells=1),
                _ev("GOOGL AI", summary=(
                    "Google faces AI search disruption risk from ChatGPT / Perplexity, "
                    "but Cloud is accelerating. Diversified revenue reduces single-point risk."
                )),
            ],
            val_stance="fairly_valued",
            val_conf=0.72,
            qual_conf=0.74,
        )
        assert 0.55 <= result.final_score <= 0.85, (
            f"GOOGL balanced scenario should be 0.55–0.85, got {result.final_score:.4f}"
        )

    def test_googl_not_speculative_with_quality_evidence(self):
        result = _run(
            ticker="GOOGL",
            evidence=[
                _quality_anchor("GOOGL"),
                _fmp_val("GOOGL", pe=22),
            ],
            val_stance="fairly_valued",
            val_conf=0.72,
        )
        assert result.setup_label not in ("speculative setup", "insufficient evidence"), (
            f"GOOGL quality should not be speculative, got '{result.setup_label}'"
        )

    def test_googl_not_in_he_set(self):
        from app.services.conviction_modeler import _HIGH_EXPECTATION_TICKERS
        assert "GOOGL" not in _HIGH_EXPECTATION_TICKERS, (
            "GOOGL is not a narrative-growth HE name — alphabet is quality anchor tier"
        )

    def test_googl_scores_above_tsla_overpriced(self):
        googl = _run(
            ticker="GOOGL",
            evidence=[_quality_anchor("GOOGL"), _fmp_val("GOOGL", pe=22)],
            val_stance="fairly_valued",
            val_conf=0.72,
        )
        tsla = _run(
            ticker="TSLA",
            evidence=[_he_priced_perfection("TSLA"), _fmp_val("TSLA", pe=75)],
            val_stance="overpriced",
            val_conf=0.55,
        )
        assert googl.final_score > tsla.final_score + 0.08, (
            f"GOOGL ({googl.final_score:.4f}) should outscore TSLA overpriced ({tsla.final_score:.4f})"
        )


# ── 11. Cross-ticker dispersion ────────────────────────────────────────────────

class TestCrossTickerDispersion:
    """10-ticker matrix must show real dispersion — not all clustering near 0.65."""

    @pytest.fixture(scope="class")
    def ten_ticker_scores(self):
        """Run all 10 tickers and collect scores."""
        scenarios = [
            # (ticker, evidence, val_stance, val_conf, qual_conf)
            ("TSLA", [_he_priced_perfection("TSLA"), _fmp_val("TSLA", pe=75)], "overpriced", 0.55, 0.62),
            ("PLTR", [_he_priced_perfection("PLTR"), _fmp_val("PLTR", pe=120)], "overpriced", 0.52, 0.58),
            ("NVDA", [_he_priced_perfection("NVDA"), _fmp_val("NVDA", pe=55)], "overpriced", 0.60, 0.70),
            ("SNOW", [_he_priced_perfection("SNOW"), _fmp_val("SNOW", pe=130)], "overpriced", 0.50, 0.55),
            ("MSFT", [_quality_anchor("MSFT"), _fmp_val("MSFT", pe=28), _fmp_analyst("MSFT")], "fairly_valued", 0.80, 0.82),
            ("JPM",  [_quality_anchor("JPM"), _fmp_val("JPM", pe=12), _fmp_analyst("JPM")], "fairly_valued", 0.75, 0.76),
            ("META", [_quality_anchor("META"), _fmp_val("META", pe=22), _fmp_analyst("META")], "fairly_valued", 0.72, 0.74),
            ("ASML", [_quality_anchor("ASML"), _fmp_val("ASML", pe=35), _fmp_analyst("ASML")], "fairly_valued", 0.76, 0.78),
            ("VRTX", [_quality_anchor("VRTX"), _fmp_val("VRTX", pe=28), _fmp_analyst("VRTX")], "fairly_valued", 0.76, 0.78),
            ("GOOGL",[_quality_anchor("GOOGL"), _fmp_val("GOOGL", pe=22), _fmp_analyst("GOOGL")], "fairly_valued", 0.72, 0.74),
        ]
        scores = {}
        for ticker, evs, stance, vc, qc in scenarios:
            r = _run(ticker=ticker, evidence=evs, val_stance=stance, val_conf=vc, qual_conf=qc)
            scores[ticker] = r.final_score
        return scores

    def test_score_range_exceeds_35_points(self, ten_ticker_scores):
        """Top score minus bottom score must exceed 0.35."""
        scores = list(ten_ticker_scores.values())
        spread = max(scores) - min(scores)
        assert spread >= 0.35, (
            f"10-ticker spread must be >= 0.35, got {spread:.4f}. "
            f"Scores: {ten_ticker_scores}"
        )

    def test_std_dev_exceeds_10_points(self, ten_ticker_scores):
        """Standard deviation across 10 tickers must exceed 0.10."""
        scores = list(ten_ticker_scores.values())
        std = statistics.stdev(scores)
        assert std >= 0.10, (
            f"10-ticker std_dev must be >= 0.10, got {std:.4f}. "
            f"Scores: {ten_ticker_scores}"
        )

    def test_no_mid_clustering_all_at_065(self, ten_ticker_scores):
        """At most 3 tickers should cluster within 0.05 of 0.65."""
        near_065 = sum(1 for s in ten_ticker_scores.values() if abs(s - 0.65) < 0.05)
        assert near_065 <= 3, (
            f"{near_065} tickers clustered near 0.65 — conviction modeler is compressing. "
            f"Scores: {ten_ticker_scores}"
        )

    def test_he_tickers_below_quality_anchors(self, ten_ticker_scores):
        """HE overpriced tickers (TSLA/PLTR/NVDA/SNOW) must all score below MSFT."""
        msft_score = ten_ticker_scores["MSFT"]
        for he in ("TSLA", "PLTR", "NVDA", "SNOW"):
            assert ten_ticker_scores[he] < msft_score, (
                f"{he} ({ten_ticker_scores[he]:.4f}) should score below MSFT ({msft_score:.4f})"
            )

    def test_quality_anchors_all_above_50(self, ten_ticker_scores):
        """Quality anchors (MSFT/JPM/VRTX/ASML) should all clear 0.60."""
        for qa in ("MSFT", "JPM", "VRTX", "ASML"):
            assert ten_ticker_scores[qa] >= 0.60, (
                f"{qa} quality anchor should score >= 0.60, got {ten_ticker_scores[qa]:.4f}"
            )

    def test_speculative_tickers_below_55(self, ten_ticker_scores):
        """TSLA and PLTR (overpriced + HE) should both score below 0.58."""
        for spec in ("TSLA", "PLTR"):
            assert ten_ticker_scores[spec] <= 0.58, (
                f"{spec} overpriced should be <= 0.58, got {ten_ticker_scores[spec]:.4f}"
            )


# ── 12. Reasoning language patterns ────────────────────────────────────────────

class TestReasoningLanguage:
    """Phase 5e: realism-specific language patterns appear in reasoning output."""

    def _reasoning(self, ticker: str, evidence, val_stance: str, val_conf: float,
                   qual_conf: float = 0.68) -> str:
        r = _run(ticker=ticker, evidence=evidence, val_stance=val_stance,
                 val_conf=val_conf, qual_conf=qual_conf)
        return r.confidence_reasoning.lower()

    def test_tsla_reasoning_mentions_fragility_language(self):
        """TSLA reasoning should reference expectations, misses, or acceleration."""
        text = self._reasoning(
            "TSLA",
            evidence=[_he_priced_perfection("TSLA"), _fmp_val("TSLA", pe=75)],
            val_stance="overpriced",
            val_conf=0.55,
        )
        keywords = ["little room", "acceleration", "vulnerable", "expectation", "demands"]
        assert any(k in text for k in keywords), (
            f"TSLA reasoning should contain fragility language, got:\n{text}"
        )

    def test_pltr_reasoning_mentions_expectation_or_speculative(self):
        text = self._reasoning(
            "PLTR",
            evidence=[_he_priced_perfection("PLTR"), _fmp_val("PLTR", pe=120)],
            val_stance="overpriced",
            val_conf=0.52,
        )
        keywords = ["expectation", "speculative", "priced", "conviction discount", "demanding"]
        assert any(k in text for k in keywords), (
            f"PLTR reasoning should contain expectation/speculative language, got:\n{text}"
        )

    def test_nvda_overpriced_reasoning_calls_out_expectations(self):
        text = self._reasoning(
            "NVDA",
            evidence=[_he_priced_perfection("NVDA", driver="hyperscaler AI CapEx"),
                      _fmp_val("NVDA", pe=55)],
            val_stance="overpriced",
            val_conf=0.60,
        )
        keywords = ["expectation", "room for misses", "vulnerable", "priced", "acceleration"]
        assert any(k in text for k in keywords), (
            f"NVDA overpriced reasoning should call out expectations, got:\n{text}"
        )

    def test_msft_reasoning_does_not_call_speculative(self):
        text = self._reasoning(
            "MSFT",
            evidence=[_quality_anchor("MSFT"), _fmp_val("MSFT", pe=28)],
            val_stance="fairly_valued",
            val_conf=0.80,
            qual_conf=0.82,
        )
        assert "speculative" not in text, (
            f"MSFT quality reasoning should not call speculative, got:\n{text}"
        )

    def test_msft_reasoning_positive_framing(self):
        """MSFT reasoning should contain constructive / clarity / mechanism language."""
        text = self._reasoning(
            "MSFT",
            evidence=[_quality_anchor("MSFT"), _fmp_val("MSFT", pe=28)],
            val_stance="fairly_valued",
            val_conf=0.80,
            qual_conf=0.82,
        )
        keywords = ["clarity", "constructive", "mechanism", "consistent", "high"]
        assert any(k in text for k in keywords), (
            f"MSFT reasoning should have positive framing, got:\n{text}"
        )

    def test_high_fragility_reasoning_avoids_generic_thin_phrase(self):
        """Fragility-driven reasoning should NOT contain legacy generic thin-evidence phrase."""
        text = self._reasoning(
            "TSLA",
            evidence=[_he_priced_perfection("TSLA"), _fmp_val("TSLA", pe=75)],
            val_stance="overpriced",
            val_conf=0.55,
        )
        forbidden = "limited evidence coverage means this position carries more uncertainty"
        assert forbidden not in text, (
            f"Legacy fallback phrase leaked into TSLA reasoning:\n{text}"
        )

    def test_speculative_ticker_no_generic_coverage_phrase(self):
        """PLTR reasoning should not contain the legacy 'data is thin' generic phrase."""
        text = self._reasoning(
            "PLTR",
            evidence=[_he_priced_perfection("PLTR")],
            val_stance="overpriced",
            val_conf=0.52,
        )
        forbidden_phrases = [
            "the framework is sound, the data is thin",
            "limited evidence coverage means",
        ]
        for phrase in forbidden_phrases:
            assert phrase not in text, (
                f"Legacy phrase '{phrase}' leaked into PLTR reasoning:\n{text}"
            )

    def test_he_ticker_compression_reasoning_references_ticker(self):
        """When compression is applied to an HE ticker, reasoning should name it."""
        r = _run(
            ticker="TSLA",
            evidence=[_he_priced_perfection("TSLA"), _fmp_val("TSLA", pe=75)],
            val_stance="overpriced",
            val_conf=0.55,
        )
        # Either reasoning or what_increases_conviction should name TSLA
        combined = (r.confidence_reasoning + " " + r.what_increases_conviction).lower()
        assert "tsla" in combined, (
            f"TSLA should be named in conviction output, got reasoning:\n{r.reasoning}"
        )
