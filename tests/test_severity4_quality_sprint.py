"""
tests/test_severity4_quality_sprint.py

Regression suite for the Severity-4 Quality Sprint (2026-06-03).

Changes validated
-----------------
P1 — Megacap profile upgrades (AAPL, NVDA, MSFT, AMZN)
     * New keywords for Apple Intelligence, Blackwell/GB200, AWS margin/FCF, Copilot
     * Richer business_model descriptions surfacing current investment debates

P2 — Compound risk enforcement
     * synthesis_validator correctly detects MISSING_COMPOUND_RISK
     * validate_thesis returns retry_prompt_addendum for hard violations
     * bear_thesis retry path is exercised non-fatally

P3 — Depth guard enforcement
     * _driver_alternatives() extracts sub-product names from driver strings
     * "Azure" satisfies "Intelligent Cloud" driver — no false DEPTH warning
     * inject_revenue_context() appends revenue context to conclusion
     * inject is idempotent (double-call does not add context twice)
"""

from __future__ import annotations

import pytest

from app.services.company_knowledge import get_knowledge_profile, list_known_tickers
from app.schemas import CompanyKnowledgeProfile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile(ticker: str) -> CompanyKnowledgeProfile:
    p = get_knowledge_profile(ticker)
    assert p is not None, f"No profile registered for {ticker}"
    return p


def _kws(ticker: str):
    """Return lowercased keyword list for a ticker."""
    return [k.lower() for k in _profile(ticker).business_model_keywords]


# ═══════════════════════════════════════════════════════════════════════════════
# P1 — Megacap profile upgrades
# ═══════════════════════════════════════════════════════════════════════════════

class TestAAPLProfileUpgrade:
    """AAPL profile must surface Apple Intelligence and DMA as first-class concepts."""

    def test_apple_intelligence_keyword(self):
        assert any("apple intelligence" in k for k in _kws("AAPL")), \
            "AAPL must have 'Apple Intelligence' in keywords"

    def test_dma_keyword(self):
        assert any("dma" in k or "digital markets act" in k for k in _kws("AAPL")), \
            "AAPL must have EU DMA keyword"

    def test_vision_pro_keyword(self):
        assert any("vision pro" in k for k in _kws("AAPL")), \
            "AAPL must have 'Vision Pro' keyword"

    def test_ai_supercycle_or_ondevice(self):
        assert any("ai" in k for k in _kws("AAPL")), \
            "AAPL must have at least one AI-related keyword"

    def test_business_model_mentions_apple_intelligence(self):
        bm = _profile("AAPL").business_model.lower()
        assert "apple intelligence" in bm, \
            "AAPL business_model must describe Apple Intelligence"

    def test_major_risks_include_dma(self):
        risks = " ".join(_profile("AAPL").major_risks).lower()
        assert "dma" in risks or "digital markets act" in risks, \
            "AAPL major_risks must include EU DMA enforcement"

    def test_major_risks_include_google_tac(self):
        risks = " ".join(_profile("AAPL").major_risks).lower()
        assert "tac" in risks or "google" in risks, \
            "AAPL major_risks must include Google TAC / DOJ risk"

    def test_keyword_count_at_least_18(self):
        assert len(_profile("AAPL").business_model_keywords) >= 18, \
            "AAPL should have ≥18 keywords after Sev-4 upgrade"


class TestNVDAProfileUpgrade:
    """NVDA profile must center the Blackwell cycle and inference/training split."""

    def test_blackwell_keyword(self):
        assert any("blackwell" in k for k in _kws("NVDA")), \
            "NVDA must have 'Blackwell' keyword"

    def test_gb200_keyword(self):
        assert any("gb200" in k or "b200" in k for k in _kws("NVDA")), \
            "NVDA must have GB200 or B200 keyword"

    def test_inference_keyword(self):
        assert any("inference" in k for k in _kws("NVDA")), \
            "NVDA must have 'inference' keyword"

    def test_nim_microservices_keyword(self):
        assert any("nim" in k for k in _kws("NVDA")), \
            "NVDA must have NIM keyword"

    def test_business_model_mentions_blackwell(self):
        bm = _profile("NVDA").business_model.lower()
        assert "blackwell" in bm, \
            "NVDA business_model must describe Blackwell architecture"

    def test_business_model_mentions_inference_vs_training(self):
        bm = _profile("NVDA").business_model.lower()
        assert "inference" in bm and "training" in bm, \
            "NVDA business_model must distinguish inference vs training"

    def test_primary_drivers_include_blackwell(self):
        drivers = " ".join(_profile("NVDA").primary_revenue_drivers).lower()
        assert "blackwell" in drivers or "b100" in drivers or "gb200" in drivers, \
            "NVDA primary_revenue_drivers must reference Blackwell GPUs"

    def test_keyword_count_at_least_18(self):
        assert len(_profile("NVDA").business_model_keywords) >= 18, \
            "NVDA should have ≥18 keywords after Sev-4 upgrade"


class TestAMZNProfileUpgrade:
    """AMZN profile must surface AWS margin recovery and FCF yield framing."""

    def test_aws_margin_keyword(self):
        assert any("aws margin" in k for k in _kws("AMZN")), \
            "AMZN must have 'AWS margin' keyword"

    def test_fcf_yield_keyword(self):
        assert any("fcf yield" in k or "ev/fcf" in k for k in _kws("AMZN")), \
            "AMZN must have FCF yield / EV/FCF keyword"

    def test_trainium_keyword(self):
        assert any("trainium" in k for k in _kws("AMZN")), \
            "AMZN must have Trainium keyword"

    def test_bedrock_keyword(self):
        assert any("bedrock" in k for k in _kws("AMZN")), \
            "AMZN must have Bedrock keyword"

    def test_business_model_mentions_aws_margin(self):
        bm = _profile("AMZN").business_model.lower()
        assert "aws margin" in bm or "margin expan" in bm, \
            "AMZN business_model must describe AWS margin expansion thesis"

    def test_business_model_mentions_fcf_framing(self):
        bm = _profile("AMZN").business_model.lower()
        assert "fcf" in bm or "free cash flow" in bm, \
            "AMZN business_model must frame valuation as FCF-based"

    def test_primary_drivers_include_aws_margin(self):
        drivers = " ".join(_profile("AMZN").primary_revenue_drivers).lower()
        assert "margin" in drivers, \
            "AMZN primary_revenue_drivers must reference AWS margin trajectory"

    def test_advertising_segment_prominent(self):
        drivers = " ".join(_profile("AMZN").primary_revenue_drivers).lower()
        assert "advertising" in drivers and "margin" in drivers, \
            "AMZN must identify advertising as high-margin profit driver"


class TestMSFTProfileUpgrade:
    """MSFT profile must explicitly name all three segment labels and Copilot monetization."""

    def test_copilot_keyword(self):
        assert any("copilot" in k for k in _kws("MSFT")), \
            "MSFT must have Copilot keyword"

    def test_azure_openai_service_keyword(self):
        assert any("azure openai" in k for k in _kws("MSFT")), \
            "MSFT must have 'Azure OpenAI Service' keyword"

    def test_github_copilot_keyword(self):
        assert any("github copilot" in k for k in _kws("MSFT")), \
            "MSFT must have GitHub Copilot keyword"

    def test_intelligent_cloud_keyword(self):
        assert any("intelligent cloud" in k for k in _kws("MSFT")), \
            "MSFT must have 'Intelligent Cloud' segment keyword"

    def test_productivity_segment_keyword(self):
        assert any("productivity" in k for k in _kws("MSFT")), \
            "MSFT must have 'Productivity' segment keyword"

    def test_copilot_monetization_keyword(self):
        assert any("copilot monetization" in k or "m365 copilot" in k for k in _kws("MSFT")), \
            "MSFT must have Copilot monetization keyword"

    def test_keyword_count_at_least_18(self):
        assert len(_profile("MSFT").business_model_keywords) >= 18, \
            "MSFT should have ≥18 keywords after Sev-4 upgrade"


# ═══════════════════════════════════════════════════════════════════════════════
# P2 — Compound Risk Enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompoundRiskValidator:
    """synthesis_validator must detect MISSING_COMPOUND_RISK correctly."""

    def _make_mock_thesis(self, bear_text: str):
        """Build a minimal InvestmentThesis with only bear_thesis populated."""
        from app.schemas import InvestmentThesis
        return InvestmentThesis(
            ticker="TEST",
            company_name="Test Corp",
            bull_thesis="Bull case here.",
            bear_thesis=bear_text,
            key_drivers=["driver A"],
            key_risks=["risk A"],
            confidence_score=0.5,
            directional_stance="Hold",
        )

    def test_detects_missing_compound_risk(self):
        """Simple additive bear case (no compound connector) must trigger the check."""
        from app.services.synthesis_validator import validate_thesis
        thesis = self._make_mock_thesis(
            "Revenue may decline. Margins may compress. The stock could fall."
        )
        result = validate_thesis(thesis)
        compound_viol = [v for v in result.violations if v.check_id == "MISSING_COMPOUND_RISK"]
        assert compound_viol, "Validator must flag bear_thesis with no compound risk"

    def test_passes_with_plus_pattern(self):
        """Bear thesis using '+' compound pattern must pass."""
        from app.services.synthesis_validator import validate_thesis
        thesis = self._make_mock_thesis(
            "Revenue slowing + margin compression = EPS decline that compounds the multiple "
            "contraction beyond what a single-factor bear case would imply."
        )
        result = validate_thesis(thesis)
        compound_viols = [v for v in result.violations if v.check_id == "MISSING_COMPOUND_RISK"]
        assert not compound_viols, "Plus-pattern compound risk must pass the check"

    def test_passes_with_connector_phrase(self):
        """Bear thesis with 'while' connector must pass."""
        from app.services.synthesis_validator import validate_thesis
        thesis = self._make_mock_thesis(
            "Higher rates increase the discount rate applied to cash flows while "
            "simultaneously slowing consumer spending, compressing both the multiple "
            "and the earnings base."
        )
        result = validate_thesis(thesis)
        compound_viols = [v for v in result.violations if v.check_id == "MISSING_COMPOUND_RISK"]
        assert not compound_viols, "Connector-phrase compound risk must pass the check"

    def test_retry_prompt_addendum_non_empty_on_violation(self):
        """ValidationResult.retry_prompt_addendum must be non-empty when violations exist."""
        from app.services.synthesis_validator import validate_thesis
        thesis = self._make_mock_thesis(
            "The stock could fall if revenue declines."
        )
        result = validate_thesis(thesis)
        if result.hard_violations:
            assert result.retry_prompt_addendum, \
                "retry_prompt_addendum must be non-empty when hard violations exist"

    def test_check_id_is_correct(self):
        """The violation check_id must be exactly 'MISSING_COMPOUND_RISK'."""
        from app.services.synthesis_validator import validate_thesis
        thesis = self._make_mock_thesis("Revenue slows. Margins fall.")
        result = validate_thesis(thesis)
        ids = [v.check_id for v in result.violations]
        assert "MISSING_COMPOUND_RISK" in ids, \
            f"Expected MISSING_COMPOUND_RISK in violation IDs, got: {ids}"


# ═══════════════════════════════════════════════════════════════════════════════
# P3 — Depth Guard Enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestDriverAlternatives:
    """_driver_alternatives() must extract sub-product names from driver strings."""

    def test_intelligent_cloud_extracts_azure(self):
        from app.services.depth_guard import _driver_alternatives
        driver = "Intelligent Cloud (~43% of revenue — Azure IaaS/PaaS/AI services, SQL Server)"
        alts = [a.lower() for a in _driver_alternatives(driver)]
        assert "intelligent cloud" in alts, "Primary name must be in alternatives"
        assert "azure" in alts, "Azure must be extracted as sub-product alternative"

    def test_gpl1_driver_extracts_ozempic(self):
        from app.services.depth_guard import _driver_alternatives
        driver = "GLP-1 diabetes (Ozempic, Rybelsus) — ~55% of revenue"
        alts = [a.lower() for a in _driver_alternatives(driver)]
        assert any("glp" in a or "diabetes" in a for a in alts), \
            "Primary name must be in alternatives"

    def test_aws_driver_no_spurious_alternatives(self):
        from app.services.depth_guard import _driver_alternatives
        driver = "AWS (~17% of revenue, ~65-70% of operating income)"
        alts = _driver_alternatives(driver)
        # The main token should be 'AWS'; percentage tokens should not be included
        assert "AWS" in alts
        for alt in alts:
            assert not alt.startswith("~"), f"Percentage token should not be included: {alt}"

    def test_returns_list_for_simple_driver(self):
        from app.services.depth_guard import _driver_alternatives
        driver = "Gaming (~9% revenue)"
        alts = _driver_alternatives(driver)
        assert isinstance(alts, list) and len(alts) >= 1


class TestDepthGuardCheck5SmartMatch:
    """Check 5 must accept product names as equivalent to segment labels."""

    def _make_company(self, ticker: str, name: str):
        from app.schemas import CompanyContext
        return CompanyContext(ticker=ticker, company_name=name)

    def _make_thesis(self, text: str):
        from app.schemas import InvestmentThesis
        return InvestmentThesis(
            ticker="MSFT",
            company_name="Microsoft Corporation",
            bull_thesis=text,
            bear_thesis=text,
            conclusion=text,
            key_drivers=[text],
            key_risks=["risk"],
            confidence_score=0.5,
            directional_stance="Hold",
        )

    def test_azure_satisfies_intelligent_cloud_check(self):
        """Thesis mentioning 'Azure' must not trigger revenue driver warning for MSFT."""
        from app.services.depth_guard import check_synthesis_depth
        profile = _profile("MSFT")
        company = self._make_company("MSFT", "Microsoft Corporation")
        thesis = self._make_thesis(
            "Microsoft's Azure cloud platform is growing rapidly at 30%+ YoY. "
            "Copilot subscriptions on Microsoft 365 add $30/seat/month incremental revenue. "
            "MSFT trades at 30x forward earnings."
        )
        warnings = check_synthesis_depth(thesis, company, profile)
        depth_revenue_warnings = [w for w in warnings if "primary revenue" in w]
        assert not depth_revenue_warnings, (
            "Thesis mentioning Azure should NOT trigger revenue driver warning. "
            f"Got: {depth_revenue_warnings}"
        )

    def test_missing_both_segment_and_product_still_fires(self):
        """Thesis with no segment OR product names must still trigger warning."""
        from app.services.depth_guard import check_synthesis_depth
        profile = _profile("MSFT")
        company = self._make_company("MSFT", "Microsoft Corporation")
        thesis = self._make_thesis(
            "MSFT's cloud business is growing rapidly. "
            "Earnings are strong. The stock trades at a premium valuation."
        )
        warnings = check_synthesis_depth(thesis, company, profile)
        depth_revenue_warnings = [w for w in warnings if "primary revenue" in w]
        assert depth_revenue_warnings, (
            "Thesis with no segment or product names must still trigger revenue driver warning"
        )


class TestInjectRevenueContext:
    """inject_revenue_context() must append driver context without duplication."""

    def _make_thesis_with_conclusion(self, conclusion: str) -> "InvestmentThesis":
        from app.schemas import InvestmentThesis
        return InvestmentThesis(
            ticker="MSFT",
            company_name="Microsoft Corporation",
            bull_thesis="bull",
            bear_thesis="bear",
            conclusion=conclusion,
            key_drivers=["driver"],
            key_risks=["risk"],
            confidence_score=0.5,
            directional_stance="Hold",
        )

    def test_injects_business_model_context(self):
        """inject_revenue_context must append revenue context to conclusion."""
        from app.services.depth_guard import inject_revenue_context
        profile = _profile("MSFT")
        thesis = self._make_thesis_with_conclusion("Some conclusion text.")
        result = inject_revenue_context(thesis, profile)
        assert "Business model context:" in result.conclusion, \
            "inject_revenue_context must add 'Business model context:' to conclusion"

    def test_includes_top_driver(self):
        """Injected context must include at least the top revenue driver."""
        from app.services.depth_guard import inject_revenue_context
        profile = _profile("MSFT")
        thesis = self._make_thesis_with_conclusion("Original conclusion.")
        result = inject_revenue_context(thesis, profile)
        # The first driver for MSFT is "Intelligent Cloud"
        assert "Intelligent Cloud" in result.conclusion or "Azure" in result.conclusion, \
            "Injected context must reference top MSFT driver"

    def test_idempotent(self):
        """Calling inject_revenue_context twice must not double-append the context."""
        from app.services.depth_guard import inject_revenue_context
        profile = _profile("AMZN")
        thesis = self._make_thesis_with_conclusion("Some conclusion.")
        r1 = inject_revenue_context(thesis, profile)
        r2 = inject_revenue_context(r1, profile)
        count = r2.conclusion.count("Business model context:")
        assert count == 1, f"Context should appear exactly once, found {count} times"

    def test_inject_for_nvda(self):
        """NVDA injection must reference Data Center or AWS equivalent."""
        from app.services.depth_guard import inject_revenue_context
        profile = _profile("NVDA")
        thesis = self._make_thesis_with_conclusion("NVDA conclusion.")
        result = inject_revenue_context(thesis, profile)
        assert "Business model context:" in result.conclusion
        # NVDA top driver is Data Center
        assert "Data Center" in result.conclusion or "data center" in result.conclusion.lower(), \
            "NVDA injection must reference Data Center driver"

    def test_empty_conclusion_handled(self):
        """inject_revenue_context must handle None or empty conclusion gracefully."""
        from app.services.depth_guard import inject_revenue_context
        profile = _profile("AAPL")
        thesis = self._make_thesis_with_conclusion("")
        result = inject_revenue_context(thesis, profile)
        assert "Business model context:" in result.conclusion


# ═══════════════════════════════════════════════════════════════════════════════
# Non-regression: existing profiles unaffected
# ═══════════════════════════════════════════════════════════════════════════════

class TestNonRegression:
    """Pre-existing profiles must still be present and intact after Sev-4 edits."""

    @pytest.mark.parametrize("ticker", [
        "TSLA", "GOOGL", "META", "JPM", "BRK.B",
        "V", "JNJ", "XOM", "COST", "ASML",
        "PLTR", "AVGO", "AMD", "UNH", "TSM",
    ])
    def test_profile_still_present(self, ticker: str):
        p = get_knowledge_profile(ticker)
        assert p is not None, f"Pre-existing profile {ticker} was removed"
        assert len(p.business_model_keywords) >= 10, \
            f"{ticker} keywords list unexpectedly short after Sev-4 edits"

    @pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "NVDA", "AMZN"])
    def test_megacap_profile_still_registered(self, ticker: str):
        p = get_knowledge_profile(ticker)
        assert p is not None, f"Megacap profile {ticker} must still be registered"
        assert p.ticker == ticker

    def test_total_profile_count_unchanged_or_higher(self):
        """Profile count must not have decreased (no accidental deletions)."""
        tickers = list_known_tickers()
        assert len(tickers) >= 58, \
            f"Expected ≥58 profiles, got {len(tickers)} — possible accidental deletion"
