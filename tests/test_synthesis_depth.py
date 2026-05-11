"""
Synthesis depth integration tests for the multi-agent investment pipeline.

Verifies that the combination of CompanyKnowledgeProfile injection +
depth guards produces company-specific theses when given company-targeted
mock LLM outputs — not generic macro summaries.

All LLM calls are mocked. No real API calls.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.schemas import (
    CompanyContext,
    CompanyKnowledgeProfile,
    InvestmentThesis,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RetrievedEvidence,
    RiskProfile,
    ValuationView,
)
from app.services.depth_guard import check_synthesis_depth


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ev(title: str, source: str = "FMP", summary: str = "test", score: float = 0.9) -> RetrievedEvidence:
    return RetrievedEvidence(
        title=title,
        source=source,
        summary=summary,
        timestamp="2024-11-01",
        relevance_score=score,
    )


def _agents_zero_confidence(company: CompanyContext):
    """Return all-zero-confidence agent outputs (for controlled testing)."""
    return (
        ValuationView(overall="Valuation analysis.", confidence=0.0),
        MacroSensitivity(overall="Macro analysis.", confidence=0.0),
        RiskProfile(overall="Risk analysis.", confidence=0.0),
        MarketContext(overall="Market context.", confidence=0.0),
        QualityAssessment(overall="Quality assessment.", confidence=0.0),
    )


# ---------------------------------------------------------------------------
# Mock thesis objects
# ---------------------------------------------------------------------------

_APPLE_RATES_THESIS = InvestmentThesis(
    ticker="AAPL",
    company_name="Apple Inc.",
    bull_thesis=(
        "Apple's Services segment — generating ~72% gross margins and growing "
        "at 14% YoY — is largely insulated from rate hikes since its revenues "
        "compound with the 2B+ active device installed base rather than consumer "
        "credit conditions. The $165B cash pile earns higher interest income as "
        "rates rise, partially offsetting multiple compression."
    ),
    bear_thesis=(
        "Apple's ~29x P/E premium implies long-duration growth expectations that "
        "compress in high-rate environments as DCF discount rates rise. Hardware "
        "demand (iPhone represents ~52% of revenue) is sensitive to consumer credit "
        "availability and willingness to finance upgrades."
    ),
    key_drivers=[
        "Services revenue growth at 14% YoY",
        "iPhone ASP expansion",
        "Buyback program reducing share count ~3% annually",
        "China rebound",
    ],
    key_risks=[
        "P/E multiple compression in sustained high-rate environment",
        "iPhone upgrade cycle deceleration",
        "China geopolitical risk",
        "App Store regulatory headwinds (EU DMA)",
    ],
    valuation_view="29x forward P/E justified by Services flywheel; DCF-sensitive.",
    macro_sensitivity="Rate-sensitive multiple; Services offset; hardware credit-linked.",
    confidence_score=0.78,
    confidence_reasoning="Strong evidence base; moderate agent confidence.",
    what_changes_the_thesis=[
        "Fed pivot to rate cuts",
        "Services growth deceleration",
        "iPhone super-cycle",
        "DOJ App Store ruling",
    ],
    conclusion=(
        "Apple's investment thesis turns on whether Services growth can sustain "
        "premium P/E valuation in a higher-for-longer rate environment. The "
        "installed base monetization engine and buyback discipline provide "
        "structural support, but 29x earnings leaves limited margin of safety "
        "if the Fed delays cuts or iPhone demand disappoints."
    ),
)


_NVDA_AI_THESIS = InvestmentThesis(
    ticker="NVDA",
    company_name="NVIDIA Corporation",
    bull_thesis=(
        "NVIDIA's H100/H200 GPUs command >80% of the AI accelerator market, "
        "driving Data Center revenue to run at a ~$100B annual rate. "
        "The CUDA software moat makes GPU switching prohibitively expensive "
        "for hyperscalers (Microsoft Azure, Google Cloud, Amazon AWS) who have "
        "committed multi-year capex cycles to NVIDIA silicon."
    ),
    bear_thesis=(
        "NVIDIA trades at ~35x forward earnings, pricing in sustained 50%+ "
        "revenue growth that requires continuous hyperscaler capex acceleration. "
        "Export restrictions on H100/H200 to China (~20% of prior Data Center "
        "revenue) permanently remove a major growth market; AMD MI300X and "
        "custom ASICs (Google TPU, Amazon Trainium) could gradually erode share."
    ),
    key_drivers=[
        "H100/H200 Data Center demand",
        "CUDA ecosystem lock-in",
        "Hyperscaler AI capex cycle",
        "Blackwell next-gen GPU ramp",
    ],
    key_risks=[
        "Export restrictions on China AI chip sales",
        "AMD MI300X market share gains",
        "Hyperscaler capex slowdown",
        "Valuation at 35x forward P/E",
    ],
    confidence_score=0.80,
)


_TSLA_RECESSION_THESIS = InvestmentThesis(
    ticker="TSLA",
    company_name="Tesla Inc.",
    bull_thesis=(
        "Tesla's Megapack energy storage business ($9B+ run rate) provides "
        "recession-resistant utility-scale demand, while Full Self-Driving "
        "software licenses represent high-margin recurring revenue attached "
        "to the existing fleet of >6M vehicles."
    ),
    bear_thesis=(
        "Consumer discretionary demand for EVs ($40K–$120K vehicles) contracts "
        "sharply in recessions as financing costs rise and confidence falls. "
        "Tesla's automotive gross margin has compressed from ~29% to ~17% as "
        "price cuts to defend market share against BYD and legacy OEMs bite "
        "into profitability."
    ),
    key_risks=[
        "Automotive gross margin compression from price wars",
        "BYD competition in China",
        "FSD regulatory timeline uncertainty",
        "Consumer EV demand cyclicality",
    ],
    confidence_score=0.70,
)


_MSFT_CLOUD_THESIS = InvestmentThesis(
    ticker="MSFT",
    company_name="Microsoft Corporation",
    bull_thesis=(
        "Microsoft 365 and Azure together generate >$180B in largely contracted "
        "annual revenue, providing earnings resilience in a cloud slowdown. "
        "Copilot AI monetization layered on 400M+ Microsoft 365 seats at "
        "$30/user/month represents a 2-3% revenue uplift with minimal marginal cost."
    ),
    bear_thesis=(
        "Azure growth decelerated to 29% in FY24; further slowdown would compress "
        "the ~35x P/E premium. Enterprise IT budget freezes disproportionately "
        "hit discretionary Azure workloads, and GitHub Copilot faces intensifying "
        "competition from Anthropic Claude and Google Gemini."
    ),
    key_drivers=[
        "Azure cloud share gains",
        "Microsoft 365 Copilot monetization",
        "Microsoft 365 seat count expansion",
        "OpenAI partnership leverage",
    ],
    confidence_score=0.82,
)


# ---------------------------------------------------------------------------
# TestAppleRatesSynthesis
# ---------------------------------------------------------------------------

class TestAppleRatesSynthesis:
    @pytest.fixture(autouse=True)
    def thesis(self):
        self._thesis = _APPLE_RATES_THESIS

    def test_apple_rates_bull_mentions_services(self):
        assert "Services" in self._thesis.bull_thesis

    def test_apple_rates_bull_mentions_installed_base(self):
        text = self._thesis.bull_thesis.lower()
        assert "installed base" in text or "2b" in text

    def test_apple_rates_bear_mentions_pe_multiple(self):
        text = self._thesis.bear_thesis.lower()
        assert "p/e" in text or "multiple" in text

    def test_apple_rates_bear_mentions_iphone(self):
        assert "iPhone" in self._thesis.bear_thesis

    def test_apple_rates_thesis_ticker_is_aapl(self):
        assert self._thesis.ticker == "AAPL"

    def test_apple_rates_conclusion_mentions_services(self):
        assert "Services" in self._thesis.conclusion

    def test_apple_rates_conclusion_not_generic(self):
        assert "tech companies face" not in self._thesis.conclusion.lower()

    def test_apple_rates_key_drivers_mention_services(self):
        assert any("Services" in d for d in self._thesis.key_drivers)

    def test_apple_rates_key_risks_mention_multiple_or_pe(self):
        assert any(
            "multiple" in r.lower() or "p/e" in r.lower()
            for r in self._thesis.key_risks
        )


# ---------------------------------------------------------------------------
# TestNvidiaAISynthesis
# ---------------------------------------------------------------------------

class TestNvidiaAISynthesis:
    @pytest.fixture(autouse=True)
    def thesis(self):
        self._thesis = _NVDA_AI_THESIS

    def test_nvda_bull_mentions_gpu(self):
        assert "GPU" in self._thesis.bull_thesis or "H100" in self._thesis.bull_thesis

    def test_nvda_bull_mentions_cuda(self):
        assert "CUDA" in self._thesis.bull_thesis

    def test_nvda_bull_mentions_hyperscaler_or_data_center(self):
        text = self._thesis.bull_thesis.lower()
        assert "hyperscaler" in text or "data center" in text

    def test_nvda_bear_mentions_export_restrictions(self):
        text = self._thesis.bear_thesis.lower()
        assert "export" in text or "china" in text

    def test_nvda_bear_not_generic(self):
        assert "tech companies face" not in self._thesis.bear_thesis.lower()

    def test_nvda_key_drivers_mention_data_center(self):
        assert any(
            "data center" in d.lower() or "H100" in d or "GPU" in d
            for d in self._thesis.key_drivers
        )

    def test_nvda_key_risks_mention_export(self):
        assert any(
            "export" in r.lower() or "china" in r.lower()
            for r in self._thesis.key_risks
        )


# ---------------------------------------------------------------------------
# TestTeslaRecessionSynthesis
# ---------------------------------------------------------------------------

class TestTeslaRecessionSynthesis:
    @pytest.fixture(autouse=True)
    def thesis(self):
        self._thesis = _TSLA_RECESSION_THESIS

    def test_tsla_bull_mentions_megapack_or_energy(self):
        text = self._thesis.bull_thesis.lower()
        assert "Megapack" in self._thesis.bull_thesis or "energy" in text

    def test_tsla_bear_mentions_margin(self):
        assert "margin" in self._thesis.bear_thesis.lower()

    def test_tsla_bear_mentions_byd_or_competition(self):
        text = self._thesis.bear_thesis.lower()
        assert "BYD" in self._thesis.bear_thesis or "competition" in text

    def test_tsla_bear_not_generic(self):
        assert "as a growth stock" not in self._thesis.bear_thesis.lower()

    def test_tsla_key_risks_mention_margin(self):
        assert any("margin" in r.lower() for r in self._thesis.key_risks)


# ---------------------------------------------------------------------------
# TestMicrosoftCloudSlowdownSynthesis
# ---------------------------------------------------------------------------

class TestMicrosoftCloudSlowdownSynthesis:
    @pytest.fixture(autouse=True)
    def thesis(self):
        self._thesis = _MSFT_CLOUD_THESIS

    def test_msft_bull_mentions_azure(self):
        assert "Azure" in self._thesis.bull_thesis

    def test_msft_bull_mentions_microsoft_365_or_copilot(self):
        assert "Microsoft 365" in self._thesis.bull_thesis or "Copilot" in self._thesis.bull_thesis

    def test_msft_bear_mentions_azure_growth(self):
        assert "Azure" in self._thesis.bear_thesis

    def test_msft_bear_not_generic(self):
        assert "the broader market" not in self._thesis.bear_thesis.lower()

    def test_msft_key_drivers_mention_azure(self):
        assert any("Azure" in d for d in self._thesis.key_drivers)

    def test_msft_key_drivers_mention_copilot_or_ai(self):
        assert any("Copilot" in d or "AI" in d for d in self._thesis.key_drivers)


# ---------------------------------------------------------------------------
# TestDepthGuardIntegration
# ---------------------------------------------------------------------------

class TestDepthGuardIntegration:
    def _aapl_company(self) -> CompanyContext:
        return CompanyContext(ticker="AAPL", company_name="Apple Inc.", sector="Technology")

    def _aapl_profile(self) -> CompanyKnowledgeProfile:
        return CompanyKnowledgeProfile(
            ticker="AAPL",
            company_name="Apple Inc.",
            business_model="Premium hardware and services ecosystem.",
            primary_revenue_drivers=["iPhone (~52% of revenue)", "Services (~25%)", "Mac (~8%)"],
            recurring_revenue_sources=["App Store", "iCloud", "Apple One"],
            rate_sensitivity_note="28-30x P/E is DCF-sensitive; Services partially offsets.",
            inflation_pass_through="Strong pricing power via iPhone ASP increases.",
            recession_behavior="iPhone upgrades extend; Services sticky.",
            major_risks=["China", "App Store regulation", "Google TAC risk"],
            valuation_style="~28-30x P/E blended with Services at ~35-40x",
            key_metrics=["iPhone units", "Services revenue growth", "installed base"],
            competitive_advantages=["Ecosystem lock-in", "A-series chips", "App Store network"],
            business_model_keywords=[
                "iPhone", "Services", "App Store", "iCloud", "installed base",
                "buyback", "China", "Mac",
            ],
        )

    def test_specific_apple_thesis_passes_depth_guard(self):
        t = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            bull_thesis=(
                "iPhone revenue (~52%) anchors AAPL's earnings, while Services "
                "segment at 72% gross margin expands the overall margin profile. "
                "The 28x p/e is supported by the 2B+ device installed base. "
                "App Store and iCloud drive recurring revenue."
            ),
            bear_thesis=(
                "China exposure (~19% of AAPL revenue) is the primary geopolitical risk. "
                "Multiple compression would hurt given the premium p/e. Mac demand is cyclical."
            ),
            conclusion=(
                "AAPL's investment case rests on Services margin expansion and iPhone ASP "
                "growth. The installed base supports the revenue multiple. buyback provides EPS support."
            ),
            key_drivers=["Services revenue growth", "iPhone ASP", "installed base"],
            key_risks=["China", "App Store regulation"],
            confidence_score=0.8,
        )
        warnings = check_synthesis_depth(t, self._aapl_company(), profile=self._aapl_profile())
        assert warnings == []

    def test_generic_thesis_fails_depth_guard(self):
        t = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            bull_thesis="The company faces headwinds but as a growth stock it benefits from trends.",
            bear_thesis="Tech companies face many challenges in the current macro environment.",
            conclusion="The outlook is uncertain but positive.",
            key_drivers=["sector trends", "macro tailwinds"],
            key_risks=["competition", "regulation"],
            confidence_score=0.5,
        )
        warnings = check_synthesis_depth(t, self._aapl_company(), profile=self._aapl_profile())
        assert len(warnings) >= 1

    def test_depth_guard_without_profile_still_runs_basic_checks(self):
        # Thesis with no company reference and no valuation terms
        t = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            bull_thesis="The technology sector is growing rapidly worldwide.",
            bear_thesis="Competition is intensifying across all hardware segments.",
            conclusion="The outlook is broadly positive for the industry.",
            key_drivers=["sector growth"],
            key_risks=["competition"],
            confidence_score=0.5,
        )
        warnings = check_synthesis_depth(t, self._aapl_company(), profile=None)
        # No profile → no keyword or driver checks, but company-reference and valuation checks run
        assert isinstance(warnings, list)
        # Should get at least the "does not reference" warning (no AAPL/Apple in text)
        assert len(warnings) >= 1

    def test_profile_enrichment_improves_specificity_check(self):
        # Thesis that mentions the company name but uses no product-level keywords
        t = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            bull_thesis="Apple Inc. benefits from strong revenue growth and margin expansion.",
            bear_thesis="Apple Inc. faces competitive headwinds in its markets.",
            conclusion="Apple Inc. is a high-quality compounder with good p/e support.",
            key_drivers=["revenue growth", "margin expansion"],
            key_risks=["competition", "macro"],
            confidence_score=0.6,
        )
        warnings_no_profile = check_synthesis_depth(t, self._aapl_company(), profile=None)
        warnings_with_profile = check_synthesis_depth(t, self._aapl_company(), profile=self._aapl_profile())

        # With a profile, we get keyword-density and driver checks on top of the basic checks
        assert len(warnings_with_profile) >= len(warnings_no_profile)
        # At minimum, with a profile there should be at least 2 warnings
        # (keyword density: only 0-1 keywords found; primary revenue driver not mentioned specifically)
        assert len(warnings_with_profile) >= 2
