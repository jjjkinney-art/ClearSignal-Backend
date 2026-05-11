"""Tests for app.services.depth_guard.check_synthesis_depth."""
from __future__ import annotations

from typing import List

import pytest

from app.schemas import CompanyContext, CompanyKnowledgeProfile, InvestmentThesis
from app.services.depth_guard import check_synthesis_depth


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _thesis(**kwargs) -> InvestmentThesis:
    defaults = dict(
        ticker="AAPL",
        company_name="Apple Inc.",
        bull_thesis="Apple's Services segment drives margin expansion.",
        bear_thesis="iPhone unit saturation may weigh on revenue growth.",
        conclusion="Apple remains a high-quality compounder.",
        confidence_score=0.75,
        key_drivers=["Services growth", "iPhone ASP"],
        key_risks=["China exposure", "Regulation"],
    )
    defaults.update(kwargs)
    return InvestmentThesis(**defaults)


def _company(ticker: str = "AAPL", name: str = "Apple Inc.") -> CompanyContext:
    return CompanyContext(ticker=ticker, company_name=name, sector="Technology")


def _profile() -> CompanyKnowledgeProfile:
    return CompanyKnowledgeProfile(
        ticker="AAPL",
        company_name="Apple Inc.",
        business_model="Premium hardware and services.",
        primary_revenue_drivers=["iPhone", "Services", "Mac"],
        recurring_revenue_sources=["App Store", "iCloud"],
        rate_sensitivity_note="Rate-sensitive premium multiple.",
        inflation_pass_through="Strong pricing power.",
        recession_behavior="iPhone upgrades extend.",
        major_risks=["China", "Regulation"],
        valuation_style="~28x P/E premium",
        key_metrics=["Services revenue growth", "iPhone ASP"],
        competitive_advantages=["Ecosystem lock-in"],
        business_model_keywords=[
            "iPhone", "Services", "App Store", "iCloud", "buyback",
            "China", "Mac",
        ],
    )


# ---------------------------------------------------------------------------
# TestCompanyReferenceCheck
# ---------------------------------------------------------------------------

class TestCompanyReferenceCheck:
    def test_ticker_present_no_company_warning(self):
        t = _thesis(bull_thesis="AAPL Services segment at 72% gross margin.", conclusion="margin")
        warnings = check_synthesis_depth(t, _company())
        company_warnings = [w for w in warnings if "does not reference" in w]
        assert company_warnings == []

    def test_company_name_present_no_company_warning(self):
        t = _thesis(bull_thesis="Apple Inc. has strong margin trajectory.", conclusion="margin")
        warnings = check_synthesis_depth(t, _company())
        company_warnings = [w for w in warnings if "does not reference" in w]
        assert company_warnings == []

    def test_neither_ticker_nor_name_warns(self):
        t = _thesis(
            bull_thesis="The tech sector drives margin expansion.",
            bear_thesis="Hardware saturation weighs on revenue.",
            conclusion="High-quality compounder.",
            key_drivers=["sector growth", "hardware ASP"],
        )
        warnings = check_synthesis_depth(t, _company())
        assert any("[DEPTH]" in w for w in warnings)
        assert any("does not reference" in w for w in warnings)


# ---------------------------------------------------------------------------
# TestBusinessModelKeywordDensity
# ---------------------------------------------------------------------------

class TestBusinessModelKeywordDensity:
    def test_three_keywords_found_no_warning(self):
        t = _thesis(
            bull_thesis="iPhone drives revenue. Services App Store is growing. margin expansion.",
            bear_thesis="competition risk.",
            conclusion="strong compounder.",
        )
        warnings = check_synthesis_depth(t, _company(), profile=_profile())
        keyword_warnings = [w for w in warnings if "company-specific term" in w]
        assert keyword_warnings == []

    def test_zero_keywords_warns(self):
        t = _thesis(
            bull_thesis="The tech sector is growing rapidly in all segments.",
            bear_thesis="Hardware competition is intense across the board.",
            conclusion="A high-quality compounder in this space.",
            key_drivers=["tech growth", "cloud expansion"],
        )
        warnings = check_synthesis_depth(t, _company(), profile=_profile())
        keyword_warnings = [w for w in warnings if "company-specific term" in w]
        assert len(keyword_warnings) >= 1

    def test_one_keyword_warns(self):
        t = _thesis(
            bull_thesis="iPhone continues to dominate the premium phone market.",
            bear_thesis="The broader tech sector faces headwinds.",
            conclusion="A compounder with resilient cash flows.",
            key_drivers=["premium phone market", "cash flows"],
        )
        warnings = check_synthesis_depth(t, _company(), profile=_profile())
        keyword_warnings = [w for w in warnings if "company-specific term" in w]
        assert len(keyword_warnings) >= 1

    def test_no_profile_skips_keyword_check(self):
        # Even with generic text, no keyword warning without a profile
        t = _thesis(
            bull_thesis="Tech companies are doing well. margin expansion.",
            bear_thesis="AAPL faces some headwinds.",
            conclusion="neutral.",
        )
        warnings = check_synthesis_depth(t, _company(), profile=None)
        keyword_warnings = [w for w in warnings if "company-specific term" in w]
        assert keyword_warnings == []

    def test_warning_contains_count(self):
        t = _thesis(
            bull_thesis="iPhone is the main product here.",
            bear_thesis="The tech sector faces headwinds.",
            conclusion="A compounder.",
            key_drivers=["tech growth"],
        )
        warnings = check_synthesis_depth(t, _company(), profile=_profile())
        keyword_warnings = [w for w in warnings if "company-specific term" in w]
        if keyword_warnings:
            # Warning should contain a digit (the count)
            assert any(char.isdigit() for char in keyword_warnings[0])


# ---------------------------------------------------------------------------
# TestValuationLanguageCheck
# ---------------------------------------------------------------------------

class TestValuationLanguageCheck:
    def test_pe_present_no_valuation_warning(self):
        t = _thesis(
            bull_thesis="AAPL trades at a 28x p/e multiple with strong free cash flow.",
            conclusion="margin expansion supports valuation.",
        )
        warnings = check_synthesis_depth(t, _company())
        valuation_warnings = [w for w in warnings if "no valuation-specific language" in w]
        assert valuation_warnings == []

    def test_margin_present_no_valuation_warning(self):
        t = _thesis(
            bull_thesis="AAPL Services segment has 72% gross margin.",
            conclusion="margin expansion is key.",
        )
        warnings = check_synthesis_depth(t, _company())
        valuation_warnings = [w for w in warnings if "no valuation-specific language" in w]
        assert valuation_warnings == []

    def test_no_valuation_terms_warns(self):
        t = _thesis(
            bull_thesis="AAPL is growing in new markets worldwide.",
            bear_thesis="Competition from rivals is increasing.",
            conclusion="The outlook is positive overall.",
            key_drivers=["new markets", "global expansion"],
        )
        warnings = check_synthesis_depth(t, _company())
        valuation_warnings = [w for w in warnings if "no valuation-specific language" in w]
        assert len(valuation_warnings) >= 1

    def test_dcf_present_no_valuation_warning(self):
        t = _thesis(
            bull_thesis="AAPL DCF analysis suggests upside at current prices.",
            conclusion="Strong compounder.",
        )
        warnings = check_synthesis_depth(t, _company())
        valuation_warnings = [w for w in warnings if "no valuation-specific language" in w]
        assert valuation_warnings == []


# ---------------------------------------------------------------------------
# TestGenericPhraseDetector
# ---------------------------------------------------------------------------

class TestGenericPhraseDetector:
    def test_no_generic_phrases_no_warning(self):
        t = _thesis(
            bull_thesis="AAPL Services generates 72% gross margin at 14% YoY growth. p/e at 28x.",
            bear_thesis="iPhone unit volumes face saturation in mature markets.",
            conclusion="Strong compounder with margin expansion.",
        )
        warnings = check_synthesis_depth(t, _company())
        generic_warnings = [w for w in warnings if "generic sector-level phrase" in w]
        assert generic_warnings == []

    def test_two_generic_phrases_warns(self):
        t = _thesis(
            bull_thesis="AAPL as a growth stock benefits from strong tailwinds. margin.",
            bear_thesis="Tech companies face many challenges in the current environment.",
            conclusion="neutral outlook.",
        )
        warnings = check_synthesis_depth(t, _company())
        generic_warnings = [w for w in warnings if "generic sector-level phrase" in w]
        assert len(generic_warnings) >= 1
        # Warning should contain a count
        assert any(char.isdigit() for char in generic_warnings[0])

    def test_one_generic_phrase_no_warning(self):
        t = _thesis(
            bull_thesis="AAPL as a growth stock shows strong free cash flow. p/e reasonable.",
            bear_thesis="iPhone competition is increasing in China.",
            conclusion="Strong compounder. margin expansion.",
        )
        warnings = check_synthesis_depth(t, _company())
        generic_warnings = [w for w in warnings if "generic sector-level phrase" in w]
        assert generic_warnings == []


# ---------------------------------------------------------------------------
# TestPrimaryRevenueDriverCheck
# ---------------------------------------------------------------------------

class TestPrimaryRevenueDriverCheck:
    def test_mentions_iphone_no_driver_warning(self):
        t = _thesis(
            bull_thesis="iPhone revenue drives the majority of AAPL's earnings. margin.",
            conclusion="strong.",
        )
        warnings = check_synthesis_depth(t, _company(), profile=_profile())
        driver_warnings = [w for w in warnings if "primary revenue" in w]
        assert driver_warnings == []

    def test_mentions_services_no_driver_warning(self):
        t = _thesis(
            bull_thesis="AAPL is growing strongly. p/e reasonable.",
            bear_thesis="competition risk.",
            conclusion="Services segment provides recurring revenue for AAPL.",
        )
        warnings = check_synthesis_depth(t, _company(), profile=_profile())
        driver_warnings = [w for w in warnings if "primary revenue" in w]
        assert driver_warnings == []

    def test_mentions_no_drivers_warns(self):
        # Use driver-neutral words — "macro" would substring-match "Mac" (an AAPL
        # primary revenue driver), so we use "economic tailwinds" instead.
        t = _thesis(
            bull_thesis="AAPL operates in a high-growth sector with p/e expansion.",
            bear_thesis="Competition is intensifying across the industry.",
            conclusion="neutral outlook.",
            key_drivers=["sector growth", "economic tailwinds"],
        )
        warnings = check_synthesis_depth(t, _company(), profile=_profile())
        driver_warnings = [w for w in warnings if "primary revenue" in w]
        assert len(driver_warnings) >= 1

    def test_no_profile_skips_driver_check(self):
        t = _thesis(
            bull_thesis="AAPL operates in a high-growth sector with p/e expansion.",
            conclusion="neutral.",
        )
        warnings = check_synthesis_depth(t, _company(), profile=None)
        driver_warnings = [w for w in warnings if "primary revenue" in w]
        assert driver_warnings == []


# ---------------------------------------------------------------------------
# TestReturnType
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_list(self):
        t = _thesis()
        result = check_synthesis_depth(t, _company())
        assert isinstance(result, list)

    def test_empty_list_for_specific_thesis(self):
        t = _thesis(
            bull_thesis=(
                "Apple's Services segment at 72% gross margin drives AAPL's earnings expansion. "
                "The 28x p/e multiple reflects Services flywheel. App Store revenue growing."
            ),
            bear_thesis=(
                "iPhone saturation risk for AAPL. China revenue ~19% of total. "
                "Mac and iPad more cyclical. Regulation risk on App Store."
            ),
            conclusion=(
                "AAPL trades at a premium p/e supported by Services margin expansion. "
                "iCloud and Services provide recurring revenue. iPhone ASP drives earnings."
            ),
            key_drivers=["Services revenue growth", "iPhone ASP expansion", "App Store monetisation"],
        )
        p = _profile()
        warnings = check_synthesis_depth(t, _company(), profile=p)
        assert warnings == []
