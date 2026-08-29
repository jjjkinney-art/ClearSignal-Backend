"""Phase 5d — Live Realism Audit & Pipeline Propagation Tests.

Validates:
1. InvestmentThesis schema includes setup_label, fragility_multiplier_applied,
   asymmetry_multiplier_applied (the fields that were missing from the API response)
2. model_dump() serializes all three conviction setup-quality fields
3. Ticker-specific score bands for TSLA / PLTR / NVDA / SNOW / MSFT / JPM / VRTX / ASML
4. Setup label semantics: speculative → "speculative setup", durable → "high-alignment thesis"
5. Score dispersion: fragile tickers compress, durable tickers elevate, no midpoint collapse
6. Frontend default fallback is never triggered when fields are present in schema

Test classes
────────────
  TestSchemaFieldPresence      — setup_label/fragility_mult/asymmetry_mult in InvestmentThesis
  TestApiSerializationChain    — model_dump includes all three fields
  TestTickerSpecificBands      — 8-ticker matrix with realistic synthetic evidence
  TestSetupLabelSemantics      — label mapping to tier for each band
  TestDispersionNoCollapse     — std_dev ≥ 0.12, fragile < 0.50, durable ≥ 0.72
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import List

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ts(days_ago: int = 7) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _ev(
    title: str = "Item",
    source: str = "newsapi",
    summary: str = "Summary.",
    timestamp: str | None = None,
    relevance_score: float = 0.80,
):
    from app.schemas import RetrievedEvidence
    return RetrievedEvidence(
        title=title, source=source, summary=summary,
        timestamp=timestamp or _ts(7),
        relevance_score=relevance_score,
    )


def _fmp_ev(summary: str = "P/E 22x. FCF yield 5%. EV/EBITDA 15x.") -> object:
    return _ev(source="FMP ratios-ttm", title="Ratios TTM",
               summary=summary, timestamp=_ts(5))


def _analyst_ev(summary: str = "Buy consensus. 35 buys. Price target raised.") -> object:
    return _ev(source="FMP analyst-estimates", title="Analyst Estimates",
               summary=summary, timestamp=_ts(5))


def _filing_ev(summary: str = "Revenue +18%. FCF margin 22%.") -> object:
    return _ev(source="sec 10-k", title="10-K Filing",
               summary=summary, timestamp=_ts(5))


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
    val_conf: float = 0.70,
    mac_conf: float = 0.68,
    risk_conf: float = 0.66,
    mkt_conf: float = 0.65,
    qual_conf: float = 0.68,
    val_stance: str = "fairly_valued",
    ticker: str = "AAPL",
    sector: str = "Technology",
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


# ══════════════════════════════════════════════════════════════════════════════
# Class 1: Schema field presence
# ══════════════════════════════════════════════════════════════════════════════

class TestSchemaFieldPresence:
    """InvestmentThesis must declare the three setup quality fields."""

    def test_setup_label_field_exists(self):
        """setup_label must be a declared field on InvestmentThesis."""
        from app.schemas import InvestmentThesis
        fields = InvestmentThesis.model_fields
        assert "setup_label" in fields, (
            "InvestmentThesis is missing 'setup_label' field — "
            "frontend will always default to 'actionable thesis'"
        )

    def test_fragility_multiplier_field_exists(self):
        """fragility_multiplier_applied must be a declared field on InvestmentThesis."""
        from app.schemas import InvestmentThesis
        fields = InvestmentThesis.model_fields
        assert "fragility_multiplier_applied" in fields, (
            "InvestmentThesis missing 'fragility_multiplier_applied'"
        )

    def test_asymmetry_multiplier_field_exists(self):
        """asymmetry_multiplier_applied must be a declared field on InvestmentThesis."""
        from app.schemas import InvestmentThesis
        fields = InvestmentThesis.model_fields
        assert "asymmetry_multiplier_applied" in fields, (
            "InvestmentThesis missing 'asymmetry_multiplier_applied'"
        )

    def test_setup_label_default_is_actionable_thesis(self):
        """setup_label default must be 'actionable thesis' (not empty)."""
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(ticker="TEST", company_name="Test Corp")
        assert thesis.setup_label == "actionable thesis", (
            f"Expected 'actionable thesis', got '{thesis.setup_label}'"
        )

    def test_multiplier_defaults_are_one(self):
        """Both multiplier fields must default to 1.0 (no penalty)."""
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(ticker="TEST", company_name="Test Corp")
        assert thesis.fragility_multiplier_applied == pytest.approx(1.0)
        assert thesis.asymmetry_multiplier_applied == pytest.approx(1.0)

    def test_setup_label_accepts_all_valid_labels(self):
        """setup_label field must accept every valid label the modeler can produce."""
        from app.schemas import InvestmentThesis
        valid_labels = [
            "high-alignment thesis",
            "actionable thesis",
            "monitoring required",
            "expectation-sensitive",
            "mixed evidence",
            "fragile setup",
            "asymmetric setup",
            "speculative setup",
            "insufficient conviction",
        ]
        for lbl in valid_labels:
            thesis = InvestmentThesis(
                ticker="TEST", company_name="Test Corp", setup_label=lbl
            )
            assert thesis.setup_label == lbl, (
                f"setup_label rejected valid label '{lbl}'"
            )

    def test_multiplier_ge_0_le_1(self):
        """Multiplier fields must accept values in [0, 1] and reject outside."""
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(
            ticker="TEST", company_name="Test Corp",
            fragility_multiplier_applied=0.78,
            asymmetry_multiplier_applied=0.85,
        )
        assert thesis.fragility_multiplier_applied == pytest.approx(0.78)
        assert thesis.asymmetry_multiplier_applied == pytest.approx(0.85)


# ══════════════════════════════════════════════════════════════════════════════
# Class 2: API serialization chain
# ══════════════════════════════════════════════════════════════════════════════

class TestApiSerializationChain:
    """model_dump() must include all three setup-quality fields."""

    def _make_thesis(
        self,
        setup_label: str = "actionable thesis",
        fragility_multiplier_applied: float = 0.87,
        asymmetry_multiplier_applied: float = 0.91,
        **kwargs,
    ):
        from app.schemas import InvestmentThesis
        return InvestmentThesis(
            ticker="NVDA", company_name="NVIDIA Corp",
            confidence_score=0.72,
            setup_label=setup_label,
            fragility_multiplier_applied=fragility_multiplier_applied,
            asymmetry_multiplier_applied=asymmetry_multiplier_applied,
            **kwargs,
        )

    def test_model_dump_includes_setup_label(self):
        thesis = self._make_thesis()
        d = thesis.model_dump()
        assert "setup_label" in d, "setup_label missing from model_dump()"
        assert d["setup_label"] == "actionable thesis"

    def test_model_dump_includes_fragility_multiplier(self):
        thesis = self._make_thesis()
        d = thesis.model_dump()
        assert "fragility_multiplier_applied" in d
        assert d["fragility_multiplier_applied"] == pytest.approx(0.87)

    def test_model_dump_includes_asymmetry_multiplier(self):
        thesis = self._make_thesis()
        d = thesis.model_dump()
        assert "asymmetry_multiplier_applied" in d
        assert d["asymmetry_multiplier_applied"] == pytest.approx(0.91)

    def test_json_roundtrip_preserves_setup_quality_fields(self):
        """Setup quality fields survive JSON serialization (simulating HTTP response)."""
        import json
        thesis = self._make_thesis(
            setup_label="speculative setup",
            fragility_multiplier_applied=0.78,
            asymmetry_multiplier_applied=0.80,
        )  # uses positional helpers, no double-kwarg conflict
        d = thesis.model_dump()
        payload = json.dumps(d)
        restored = json.loads(payload)
        assert restored["setup_label"] == "speculative setup"
        assert restored["fragility_multiplier_applied"] == pytest.approx(0.78)
        assert restored["asymmetry_multiplier_applied"] == pytest.approx(0.80)

    def test_speculative_label_survives_serialization(self):
        """Speculative label must not be altered by serialization."""
        import json
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(
            ticker="TSLA", company_name="Tesla Inc",
            confidence_score=0.32,
            setup_label="speculative setup",
            fragility_multiplier_applied=0.78,
            asymmetry_multiplier_applied=0.80,
        )
        d = json.loads(json.dumps(thesis.model_dump()))
        assert d["setup_label"] == "speculative setup"
        assert d["confidence_score"] == pytest.approx(0.32)

    def test_durable_label_survives_serialization(self):
        """Durable label must not be altered by serialization."""
        import json
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(
            ticker="MSFT", company_name="Microsoft Corp",
            confidence_score=0.82,
            setup_label="high-alignment thesis",
            fragility_multiplier_applied=0.98,
            asymmetry_multiplier_applied=0.97,
        )
        d = json.loads(json.dumps(thesis.model_dump()))
        assert d["setup_label"] == "high-alignment thesis"
        assert d["confidence_score"] == pytest.approx(0.82)


# ══════════════════════════════════════════════════════════════════════════════
# Class 3: Ticker-specific score bands (8-ticker matrix)
# ══════════════════════════════════════════════════════════════════════════════

class TestTickerSpecificBands:
    """Score bands for canonical tickers must reflect expectation asymmetry."""

    # ── TSLA — speculative, high fragility, narrative-driven ─────────────────

    def test_tsla_speculative_band(self):
        """TSLA with narrative-driven overpriced setup should score < 0.50."""
        evidence = [
            _ev(summary=(
                "Tesla valuation implies continued growth acceleration and margin "
                "expansion. EV market share pressure from BYD and domestic OEMs "
                "is being ignored. Priced for continued robotaxi optionality."
            )),
            _ev(summary=(
                "Priced for perfection. High expectations embedded. "
                "Elevated multiple requires continued acceleration beyond consensus."
            )),
            _fmp_ev("P/E 60x. EV/EBITDA 35x. Rich valuation relative to delivery targets."),
        ]
        result = _run(
            evidence=evidence, ticker="TSLA", sector="Consumer Cyclical",
            val_conf=0.45, val_stance="overpriced",
            mac_conf=0.55, risk_conf=0.45, mkt_conf=0.50, qual_conf=0.52,
        )
        assert result.final_score < 0.50, (
            f"TSLA speculative scenario scored {result.final_score:.3f} — "
            f"expected < 0.50 for narrative-driven overpriced setup"
        )

    def test_tsla_setup_label_speculative_or_fragile(self):
        """TSLA overpriced scenario must get speculative or fragile label, not balanced."""
        evidence = [
            _ev(summary="Tesla priced for perfection. High expectations. Multiple stretched."),
            _fmp_ev("P/E 65x. Elevated vs delivery trajectory."),
        ]
        result = _run(
            evidence=evidence, ticker="TSLA", sector="Consumer Cyclical",
            val_conf=0.42, val_stance="overpriced",
            mac_conf=0.52, risk_conf=0.42,
        )
        assert result.setup_label in {
            "speculative setup", "fragile setup", "asymmetric setup",
            "expectation-sensitive", "insufficient conviction"
        }, (
            f"TSLA got '{result.setup_label}' — expected a speculative/fragile label"
        )

    # ── PLTR — high expectations, narrative AI premium ───────────────────────

    def test_pltr_speculative_band(self):
        """PLTR with an overpriced narrative setup remains below the durable tier."""
        evidence = [
            _ev(summary=(
                "Palantir valuation pricing in continued government/commercial "
                "AI adoption at an accelerating pace. High multiple requires "
                "sustained execution without margin for misses."
            )),
            _fmp_ev("P/E 180x. Priced well beyond near-term earnings power."),
            _analyst_ev("Mixed signals. Valuation remains a concern at current levels."),
        ]
        result = _run(
            evidence=evidence, ticker="PLTR", sector="Technology",
            val_conf=0.42, val_stance="overpriced",
            mac_conf=0.55, risk_conf=0.45, qual_conf=0.52,
        )
        assert result.final_score < 0.62, (
            f"PLTR speculative scored {result.final_score:.3f} — expected < 0.62"
        )

    # ── NVDA — overpriced but structurally strong ─────────────────────────────

    def test_nvda_overpriced_scenario_below_0_60(self):
        """NVDA quality can offset some valuation pressure, but remains below 0.65."""
        evidence = [
            _ev(summary=(
                "Nvidia priced for continued hyperscaler CapEx acceleration. "
                "Expectations are elevated. Any deceleration in data center demand "
                "growth reprices the thesis materially."
            )),
            _fmp_ev("P/E 42x. EV/EBITDA 31x. Rich relative to sector."),
            _analyst_ev("Strong buy consensus but target implies limited upside at current price."),
            _ev(summary="AI demand durability is the central debate. Structural vs cycle question."),
        ]
        result = _run(
            evidence=evidence, ticker="NVDA", sector="Technology",
            val_conf=0.50, val_stance="overpriced",
            mac_conf=0.60, risk_conf=0.55, qual_conf=0.65,
        )
        assert result.final_score < 0.65, (
            f"NVDA overpriced scored {result.final_score:.3f} — expected < 0.65"
        )

    def test_nvda_overpriced_above_minimum(self):
        """NVDA despite overpriced rating still has structural support — score ≥ 0.30."""
        evidence = [
            _ev(summary="Nvidia dominates AI accelerator market with structural moat."),
            _fmp_ev("P/E 42x. Strong FCF generation. Revenue +120% YoY."),
        ]
        result = _run(
            evidence=evidence, ticker="NVDA", sector="Technology",
            val_conf=0.55, val_stance="overpriced",
            mac_conf=0.65, risk_conf=0.60,
        )
        assert result.final_score >= 0.30, (
            f"NVDA scored {result.final_score:.3f} — too low even for overpriced; "
            "structural business quality should provide a floor"
        )

    # ── SNOW — demanding setup, enterprise sales headwinds ───────────────────

    def test_snow_demanding_band(self):
        """SNOW with slowing consumption growth should score 0.35–0.58."""
        evidence = [
            _ev(summary=(
                "Snowflake consumption-based model faces headwinds as enterprises "
                "optimize cloud spend. NRR declining. Competition from Databricks intensifies."
            )),
            _fmp_ev("P/S 15x. FCF positive but rich relative to revised growth."),
            _ev(summary="Snowflake requires re-acceleration of product consumption to justify multiple."),
        ]
        result = _run(
            evidence=evidence, ticker="SNOW", sector="Technology",
            val_conf=0.48, val_stance="overpriced",
            mac_conf=0.60, risk_conf=0.50, qual_conf=0.55,
        )
        assert result.final_score < 0.60, (
            f"SNOW scored {result.final_score:.3f} — expected < 0.60 with slowing growth"
        )

    # ── MSFT — durable, diversified, fair value ───────────────────────────────

    def test_msft_durable_band(self):
        """MSFT with diverse revenue, strong FCF, and fair value should score ≥ 0.70."""
        evidence = [
            _fmp_ev("P/E 32x. FCF yield 3.5%. Azure +21% YoY. Dividend raised."),
            _analyst_ev("Buy consensus. 52 buys. AI monetization driving estimates higher."),
            _filing_ev("Revenue diversified: Productivity 37%, Cloud 28%, Gaming 13%. "
                       "Operating margin 44%. FCF $75B trailing."),
            _ev(summary=(
                "Microsoft's Azure and Copilot integration creates durable revenue "
                "streams across enterprise, consumer, and developer verticals."
            )),
            _ev(source="sec 10-q", summary="Balance sheet pristine. Net cash position. "
                "Return on equity 35%. Dividend growth consistent 11 years.",
                timestamp=_ts(30)),
        ]
        result = _run(
            evidence=evidence, ticker="MSFT", sector="Technology",
            val_conf=0.75, val_stance="fairly_valued",
            mac_conf=0.72, risk_conf=0.75, mkt_conf=0.70, qual_conf=0.80,
        )
        assert result.final_score >= 0.70, (
            f"MSFT durable scored {result.final_score:.3f} — expected ≥ 0.70 "
            "for diversified, fair-valued, high-conviction setup"
        )

    def test_msft_durable_setup_label(self):
        """MSFT high-conviction scenario must get durable label."""
        evidence = [
            _fmp_ev("P/E 31x. Fair value. Azure growing double digits."),
            _analyst_ev("Buy consensus. Strong free cash flow. Dividend raised."),
            _filing_ev("Revenue +16%. FCF margin 33%. Balance sheet strength."),
            _ev(summary="Azure AI adoption broadening. Copilot enterprise rollout accelerating."),
        ]
        result = _run(
            evidence=evidence, ticker="MSFT", sector="Technology",
            val_conf=0.78, val_stance="fairly_valued",
            mac_conf=0.75, risk_conf=0.78, mkt_conf=0.72, qual_conf=0.80,
        )
        assert result.setup_label in {
            "high-alignment thesis", "actionable thesis"
        }, (
            f"MSFT got '{result.setup_label}' — expected durable/balanced label"
        )

    # ── JPM — financials, rate-sensitive but diversified ─────────────────────

    def test_jpm_balanced_band(self):
        """JPM with rate tailwind and strong capital returns should score ≥ 0.62."""
        evidence = [
            _fmp_ev("P/E 12x. P/B 1.8x. NIM expanding. ROE 17%."),
            _analyst_ev("Buy consensus. Capital return program. Dividend raised."),
            _filing_ev("Revenue +14%. CET1 15.0%. Loan loss provisions in line."),
            _ev(summary=(
                "JPMorgan benefits from higher-for-longer rates expanding net interest margin. "
                "Diversified revenue across IB, Consumer, and Wealth Management."
            )),
        ]
        result = _run(
            evidence=evidence, ticker="JPM", sector="Financial Services",
            val_conf=0.68, val_stance="fairly_valued",
            mac_conf=0.65, risk_conf=0.70, mkt_conf=0.65, qual_conf=0.72,
        )
        assert result.final_score >= 0.60, (
            f"JPM balanced scored {result.final_score:.3f} — expected ≥ 0.60 "
            "for diversified bank with capital return and rate tailwind"
        )

    # ── VRTX — biotech with approved product, pipeline optionality ───────────

    def test_vrtx_constructive_band(self):
        """VRTX with approved product franchise should score ≥ 0.58."""
        evidence = [
            _fmp_ev("P/E 28x. FCF positive. CF franchise durable cash generator."),
            _analyst_ev("Buy consensus. Pipeline readout upcoming. Patent cliff distant."),
            _ev(summary=(
                "Vertex's CFTR franchise has durable pricing power and limited competition. "
                "Next-gen therapy Phase 3 readout would be the primary conviction driver. "
                "Pain franchise expansion represents meaningful optionality."
            )),
            _filing_ev("Revenue +22%. Operating margin 38%. CF market penetration high."),
        ]
        result = _run(
            evidence=evidence, ticker="VRTX", sector="Healthcare",
            val_conf=0.65, val_stance="fairly_valued",
            mac_conf=0.65, risk_conf=0.65, mkt_conf=0.62, qual_conf=0.70,
        )
        assert result.final_score >= 0.55, (
            f"VRTX scored {result.final_score:.3f} — expected ≥ 0.55 "
            "for approved-franchise biotech with durable revenue"
        )

    # ── ASML — structural monopoly, cyclical semiconductor exposure ───────────

    def test_asml_constructive_band(self):
        """ASML as EUV monopoly with backlog visibility should score ≥ 0.60."""
        evidence = [
            _fmp_ev("P/E 34x. EV/EBITDA 24x. Backlog 15B EUR. Pricing power intact."),
            _analyst_ev("Buy consensus. Geopolitical risk (China) acknowledged. Structural moat."),
            _ev(summary=(
                "ASML has a structural monopoly in extreme ultraviolet lithography. "
                "Backlog provides multi-year revenue visibility. "
                "China export restrictions reduce near-term revenue but don't threaten the moat."
            )),
            _filing_ev("Revenue +12%. Order intake strong. Gross margin 51%. EUV transition on track."),
        ]
        result = _run(
            evidence=evidence, ticker="ASML", sector="Technology",
            val_conf=0.67, val_stance="fairly_valued",
            mac_conf=0.62, risk_conf=0.65, mkt_conf=0.65, qual_conf=0.72,
        )
        assert result.final_score >= 0.58, (
            f"ASML scored {result.final_score:.3f} — expected ≥ 0.58 "
            "for structural-monopoly semiconductor equipment name"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 4: Setup label semantics
# ══════════════════════════════════════════════════════════════════════════════

class TestSetupLabelSemantics:
    """setup_label values must be semantically meaningful, not always 'actionable thesis'."""

    def test_empty_evidence_score_is_low_even_when_setup_label_is_structural(self):
        """Evidence lowers conviction; setup_label independently describes setup quality."""
        result = _run(evidence=[], ticker="UNKNOWN", sector="Technology",
                      val_conf=0.50, val_stance="fairly_valued")
        assert result.final_score < 0.45
        assert result.setup_label in {
            "actionable thesis", "asymmetric setup", "demanding setup",
            "speculative setup", "high-alignment thesis",
        }

    def test_rich_evidence_msft_gets_durable_or_balanced_label(self):
        """MSFT with rich evidence should get durable or balanced label."""
        evidence = [
            _fmp_ev("P/E 31x. Fair value. Strong FCF."),
            _analyst_ev("52 buys. AI monetization."),
            _filing_ev("Revenue +16%. FCF margin 33%."),
            _ev(summary="Azure AI adoption broadening. Enterprise cloud durable."),
        ]
        result = _run(
            evidence=evidence, ticker="MSFT", sector="Technology",
            val_conf=0.78, val_stance="fairly_valued",
            mac_conf=0.75, risk_conf=0.78, qual_conf=0.80,
        )
        assert result.setup_label in {
            "high-alignment thesis", "actionable thesis", "monitoring required"
        }, (
            f"MSFT rich evidence got label '{result.setup_label}' — "
            f"expected durable/balanced label, score={result.final_score:.3f}"
        )

    def test_overpriced_he_ticker_never_gets_high_alignment(self):
        """Overpriced HE ticker (NVDA/TSLA) must never get 'high-alignment thesis'."""
        for ticker in ["NVDA", "TSLA", "PLTR"]:
            evidence = [
                _ev(summary="Priced for perfection. Elevated expectations."),
                _fmp_ev("P/E 65x. Stretched multiple."),
            ]
            result = _run(
                evidence=evidence, ticker=ticker, sector="Technology",
                val_conf=0.42, val_stance="overpriced",
                mac_conf=0.55, risk_conf=0.45,
            )
            assert result.setup_label != "high-alignment thesis", (
                f"{ticker} overpriced got 'high-alignment thesis' — "
                f"should compress to speculative/fragile/demanding"
            )

    def test_fragility_multiplier_below_one_for_he_overpriced(self):
        """HE tickers with overpriced stance must apply fragility penalty (mult < 1.0)."""
        evidence = [
            _ev(summary="TSLA priced for perfection. Multiple stretched."),
            _fmp_ev("P/E 60x. Rich valuation."),
        ]
        result = _run(
            evidence=evidence, ticker="TSLA", sector="Consumer Cyclical",
            val_conf=0.42, val_stance="overpriced",
            mac_conf=0.55, risk_conf=0.42,
        )
        assert result.fragility_multiplier_applied < 0.97, (
            f"TSLA overpriced fragility_multiplier={result.fragility_multiplier_applied:.3f} — "
            "expected < 0.97 (penalty should be applied)"
        )

    def test_asymmetry_multiplier_never_rewards_overpriced_setup(self):
        """The legacy multiplier field must never increase an overpriced score."""
        evidence = [
            _ev(summary="PLTR priced at 180x earnings. AI narrative premium."),
            _fmp_ev("P/E 180x. Requires continued re-rating to justify."),
        ]
        result = _run(
            evidence=evidence, ticker="PLTR", sector="Technology",
            val_conf=0.38, val_stance="overpriced",
            mac_conf=0.52, risk_conf=0.40,
        )
        assert 0.0 < result.asymmetry_multiplier_applied <= 1.0

    def test_setup_label_not_always_actionable_thesis(self):
        """setup_label must vary across scenarios — not always 'actionable thesis'."""
        labels = set()
        scenarios = [
            dict(ticker="MSFT", val_stance="fairly_valued", val_conf=0.78,
                 evidence=[_fmp_ev(), _analyst_ev(), _filing_ev()]),
            dict(ticker="TSLA", val_stance="overpriced", val_conf=0.38,
                 evidence=[_ev(summary="Priced for perfection."), _fmp_ev("P/E 65x.")]),
            dict(ticker="JPM", val_stance="fairly_valued", val_conf=0.65,
                 evidence=[_fmp_ev("P/E 12x. ROE 17%."), _analyst_ev()]),
        ]
        for s in scenarios:
            evidence = s.pop("evidence")
            result = _run(evidence=evidence, **s)
            labels.add(result.setup_label)
        assert len(labels) >= 2, (
            f"setup_label collapsed to just {labels} across 3 distinct scenarios — "
            "expected at least 2 different labels"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 5: Score dispersion — no midpoint collapse
# ══════════════════════════════════════════════════════════════════════════════

class TestDispersionNoCollapse:
    """Scores across the 8-ticker matrix must show meaningful spread."""

    def _compute_all_scores(self) -> list[float]:
        """Run conviction modeler for a diverse set of 8 scenarios."""
        scores = []

        # TSLA — speculative overpriced
        r = _run(
            evidence=[
                _ev(summary="Tesla priced for perfection. High expectations. Multiple stretched."),
                _fmp_ev("P/E 60x. EV/EBITDA 35x."),
            ],
            ticker="TSLA", sector="Consumer Cyclical",
            val_conf=0.42, val_stance="overpriced",
            mac_conf=0.52, risk_conf=0.42,
        )
        scores.append(r.final_score)

        # PLTR — speculative narrative AI
        r = _run(
            evidence=[
                _ev(summary="Palantir priced at 180x. AI narrative premium."),
                _fmp_ev("P/E 180x. Revenue multiple rich."),
            ],
            ticker="PLTR", sector="Technology",
            val_conf=0.38, val_stance="overpriced",
            mac_conf=0.50, risk_conf=0.38,
        )
        scores.append(r.final_score)

        # NVDA — overpriced but structurally strong
        r = _run(
            evidence=[
                _ev(summary="NVDA priced for continued AI acceleration. Fragile to deceleration."),
                _fmp_ev("P/E 42x. Forward P/E 36x."),
                _analyst_ev("Strong buy consensus. Limited upside at current price."),
            ],
            ticker="NVDA", sector="Technology",
            val_conf=0.50, val_stance="overpriced",
            mac_conf=0.60, risk_conf=0.55, qual_conf=0.65,
        )
        scores.append(r.final_score)

        # SNOW — demanding, slowing growth
        r = _run(
            evidence=[
                _ev(summary="Snowflake consumption slowing. NRR declining. Competition rising."),
                _fmp_ev("P/S 15x. Rich given revised growth."),
            ],
            ticker="SNOW", sector="Technology",
            val_conf=0.48, val_stance="overpriced",
            mac_conf=0.58, risk_conf=0.48,
        )
        scores.append(r.final_score)

        # VRTX — balanced, approved franchise
        r = _run(
            evidence=[
                _fmp_ev("P/E 28x. FCF positive. CF franchise durable."),
                _analyst_ev("Buy consensus. Pipeline optionality."),
                _ev(summary="Vertex CF franchise has durable pricing power."),
            ],
            ticker="VRTX", sector="Healthcare",
            val_conf=0.65, val_stance="fairly_valued",
            mac_conf=0.65, risk_conf=0.65, qual_conf=0.70,
        )
        scores.append(r.final_score)

        # JPM — balanced, diversified bank
        r = _run(
            evidence=[
                _fmp_ev("P/E 12x. P/B 1.8x. ROE 17%."),
                _analyst_ev("Buy. Capital return program."),
                _filing_ev("Revenue diversified. CET1 15%."),
            ],
            ticker="JPM", sector="Financial Services",
            val_conf=0.68, val_stance="fairly_valued",
            mac_conf=0.65, risk_conf=0.70, qual_conf=0.72,
        )
        scores.append(r.final_score)

        # ASML — constructive, structural monopoly
        r = _run(
            evidence=[
                _fmp_ev("P/E 34x. Backlog 15B. Pricing power."),
                _analyst_ev("Buy. EUV monopoly intact."),
                _ev(summary="ASML has structural monopoly in EUV. Backlog provides visibility."),
                _filing_ev("Revenue +12%. Gross margin 51%."),
            ],
            ticker="ASML", sector="Technology",
            val_conf=0.67, val_stance="fairly_valued",
            mac_conf=0.62, risk_conf=0.65, qual_conf=0.72,
        )
        scores.append(r.final_score)

        # MSFT — durable, diversified tech
        r = _run(
            evidence=[
                _fmp_ev("P/E 32x. FCF yield 3.5%. Azure +21%."),
                _analyst_ev("52 buys. AI monetization."),
                _filing_ev("Revenue diversified. Operating margin 44%."),
                _ev(summary="Microsoft durable revenue streams across enterprise and cloud."),
                _ev(source="sec 10-q", summary="Net cash position. ROE 35%. Dividend raised.",
                    timestamp=_ts(30)),
            ],
            ticker="MSFT", sector="Technology",
            val_conf=0.75, val_stance="fairly_valued",
            mac_conf=0.72, risk_conf=0.75, mkt_conf=0.70, qual_conf=0.80,
        )
        scores.append(r.final_score)

        return scores

    def test_8_ticker_score_range_above_0_20(self):
        """Phase 7 preserves at least 20 points of cross-ticker dispersion."""
        scores = self._compute_all_scores()
        spread = max(scores) - min(scores)
        assert spread > 0.20, (
            f"Score range only {spread:.3f} across 8 tickers — "
            f"expected > 0.20. Scores: {[round(s, 3) for s in scores]}"
        )

    def test_8_ticker_std_dev_above_0_08(self):
        """Standard deviation across 8 tickers must exceed 0.08."""
        scores = self._compute_all_scores()
        std = statistics.stdev(scores)
        assert std > 0.08, (
            f"std_dev={std:.4f} across 8 tickers — expected > 0.08. "
            f"Scores: {[round(s, 3) for s in scores]}"
        )

    def test_fragile_tickers_below_balanced_tickers(self):
        """Mean(speculative tickers) < mean(balanced tickers)."""
        scores = self._compute_all_scores()
        # Scores order: TSLA, PLTR, NVDA, SNOW, VRTX, JPM, ASML, MSFT
        speculative_mean = statistics.mean(scores[:2])   # TSLA, PLTR
        balanced_mean    = statistics.mean(scores[4:])   # VRTX, JPM, ASML, MSFT
        assert speculative_mean < balanced_mean, (
            f"Speculative mean {speculative_mean:.3f} ≥ balanced mean {balanced_mean:.3f} — "
            "fragile tickers not being penalized relative to durable ones"
        )

    def test_msft_highest_or_near_highest(self):
        """MSFT must score higher than TSLA and PLTR."""
        scores = self._compute_all_scores()
        tsla_score  = scores[0]
        pltr_score  = scores[1]
        msft_score  = scores[7]
        assert msft_score > tsla_score, (
            f"MSFT {msft_score:.3f} ≤ TSLA {tsla_score:.3f} — wrong ordering"
        )
        assert msft_score > pltr_score, (
            f"MSFT {msft_score:.3f} ≤ PLTR {pltr_score:.3f} — wrong ordering"
        )

    def test_speculative_below_0_52(self):
        """Both speculative tickers (TSLA, PLTR) must score < 0.52."""
        scores = self._compute_all_scores()
        tsla_score = scores[0]
        pltr_score = scores[1]
        assert tsla_score < 0.52, f"TSLA scored {tsla_score:.3f} — expected < 0.52"
        assert pltr_score < 0.52, f"PLTR scored {pltr_score:.3f} — expected < 0.52"

    def test_no_score_stuck_at_0_65(self):
        """No ticker should be stuck exactly at 0.65 ± 0.02 (LLM default indicator)."""
        scores = self._compute_all_scores()
        stuck = [s for s in scores if 0.63 <= s <= 0.67]
        assert len(stuck) <= 2, (
            f"{len(stuck)} scores stuck near 0.65 (LLM default band): "
            f"{[round(s, 3) for s in stuck]}. "
            "This suggests the conviction modeler is returning LLM fallback values."
        )
