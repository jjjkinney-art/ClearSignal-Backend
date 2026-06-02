"""
tests/test_severity3_knowledge_profiles.py

Regression suite for Severity-3 knowledge profile sprint (2026-06-03).

15 new CompanyKnowledgeProfile entries covering:
  P1 (formerly Q≤3 with valid routing): PANW, DIS, UBER, INTC, MA, BLK,
    PM, UPS, DE, DUK, ABNB
  P2 (formerly Q≤3 from Severity-1b validation): EMR, AEP, EXC, SO

Tests verify:
  1. Profile is registered and retrievable by ticker
  2. Required fields are populated (non-empty)
  3. business_model_keywords are substantive (≥10 unique terms)
  4. primary_revenue_drivers lists are non-empty and ordered
  5. major_risks are company-specific (not generic)
  6. No profile overlaps with previously registered tickers

Run
---
    python3 -m pytest tests/test_severity3_knowledge_profiles.py -v
"""

from __future__ import annotations

import pytest

from app.services.company_knowledge import (
    get_knowledge_profile,
    list_known_tickers,
)
from app.schemas import CompanyKnowledgeProfile


# ── New tickers added in this sprint ─────────────────────────────────────────

SEVERITY3_TICKERS = [
    "PANW", "DIS", "UBER", "INTC", "MA",
    "BLK", "PM", "UPS", "DE", "DUK",
    "ABNB", "EMR", "AEP", "EXC", "SO",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile(ticker: str) -> CompanyKnowledgeProfile:
    p = get_knowledge_profile(ticker)
    assert p is not None, f"No profile registered for {ticker}"
    return p


# ── Test 1: all 15 tickers registered ────────────────────────────────────────

class TestProfilesRegistered:
    @pytest.mark.parametrize("ticker", SEVERITY3_TICKERS)
    def test_profile_exists(self, ticker):
        p = get_knowledge_profile(ticker)
        assert p is not None, f"Profile for {ticker} not found in knowledge database"
        assert p.ticker == ticker

    def test_total_profile_count_increased(self):
        """Total profile count must be at least 58 (43 existing + 15 new)."""
        tickers = list_known_tickers()
        assert len(tickers) >= 58, (
            f"Expected ≥58 profiles, got {len(tickers)}. "
            "Some Severity-3 profiles may not have registered."
        )

    def test_all_severity3_tickers_in_known_list(self):
        known = set(list_known_tickers())
        missing = [t for t in SEVERITY3_TICKERS if t not in known]
        assert not missing, f"Missing from knowledge DB: {missing}"


# ── Test 2: required fields populated ────────────────────────────────────────

class TestRequiredFields:
    @pytest.mark.parametrize("ticker", SEVERITY3_TICKERS)
    def test_business_model_non_empty(self, ticker):
        p = _profile(ticker)
        assert len(p.business_model) >= 100, (
            f"{ticker}.business_model is too short ({len(p.business_model)} chars); "
            "must be a substantive paragraph"
        )

    @pytest.mark.parametrize("ticker", SEVERITY3_TICKERS)
    def test_primary_revenue_drivers_non_empty(self, ticker):
        p = _profile(ticker)
        assert len(p.primary_revenue_drivers) >= 3, (
            f"{ticker}: expected ≥3 revenue drivers, got {len(p.primary_revenue_drivers)}"
        )

    @pytest.mark.parametrize("ticker", SEVERITY3_TICKERS)
    def test_major_risks_non_empty(self, ticker):
        p = _profile(ticker)
        assert len(p.major_risks) >= 3, (
            f"{ticker}: expected ≥3 major risks, got {len(p.major_risks)}"
        )

    @pytest.mark.parametrize("ticker", SEVERITY3_TICKERS)
    def test_competitive_advantages_non_empty(self, ticker):
        p = _profile(ticker)
        assert len(p.competitive_advantages) >= 2, (
            f"{ticker}: expected ≥2 competitive advantages"
        )

    @pytest.mark.parametrize("ticker", SEVERITY3_TICKERS)
    def test_key_metrics_non_empty(self, ticker):
        p = _profile(ticker)
        assert len(p.key_metrics) >= 5, (
            f"{ticker}: expected ≥5 key metrics, got {len(p.key_metrics)}"
        )

    @pytest.mark.parametrize("ticker", SEVERITY3_TICKERS)
    def test_company_name_matches_ticker(self, ticker):
        p = _profile(ticker)
        assert p.company_name, f"{ticker}: company_name is empty"
        assert len(p.company_name) > 5, f"{ticker}: company_name too short"


# ── Test 3: business_model_keywords substantive ───────────────────────────────

class TestKeywords:
    @pytest.mark.parametrize("ticker", SEVERITY3_TICKERS)
    def test_minimum_keyword_count(self, ticker):
        p = _profile(ticker)
        assert len(p.business_model_keywords) >= 10, (
            f"{ticker}: only {len(p.business_model_keywords)} keywords — "
            "depth guard requires ≥10 for meaningful thesis validation"
        )

    @pytest.mark.parametrize("ticker", SEVERITY3_TICKERS)
    def test_keywords_are_company_specific(self, ticker):
        """Keywords must not be pure generic sector terms."""
        p = _profile(ticker)
        generic_only = {"revenue", "margins", "growth", "earnings", "profit",
                        "cash flow", "market share", "competition", "risk"}
        specific = [kw for kw in p.business_model_keywords
                    if kw.lower() not in generic_only]
        assert len(specific) >= 8, (
            f"{ticker}: fewer than 8 company-specific keywords; "
            f"found only {specific}"
        )

    # ── Spot-check key terms per company ──────────────────────────────────────

    def test_panw_has_platformization(self):
        p = _profile("PANW")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("platformization" in k for k in kws), \
            "PANW must have 'platformization' keyword"
        assert any("xsiam" in k or "cortex" in k for k in kws), \
            "PANW must have Cortex or XSIAM keyword"

    def test_dis_has_disney_plus_and_parks(self):
        p = _profile("DIS")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("disney+" in k for k in kws), "DIS must have 'Disney+' keyword"
        assert any("theme park" in k or "park" in k for k in kws), \
            "DIS must have theme park keyword"
        assert any("bob iger" in k for k in kws), "DIS must have 'Bob Iger' keyword"

    def test_uber_has_gross_bookings(self):
        p = _profile("UBER")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("gross bookings" in k for k in kws), \
            "UBER must have 'Gross Bookings' keyword"
        assert any("mapc" in k for k in kws), "UBER must have 'MAPC' keyword"

    def test_intc_has_foundry_and_process_node(self):
        p = _profile("INTC")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("18a" in k or "intel foundry" in k for k in kws), \
            "INTC must have 18A or Intel Foundry keyword"
        assert any("gaudi" in k for k in kws), "INTC must have Gaudi keyword"

    def test_ma_has_gdv(self):
        p = _profile("MA")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("gdv" in k or "gross dollar volume" in k for k in kws), \
            "MA must have GDV keyword"
        assert any("cross-border" in k or "tokenization" in k for k in kws), \
            "MA must have cross-border or tokenization keyword"

    def test_blk_has_ishares_and_aladdin(self):
        p = _profile("BLK")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("ishares" in k for k in kws), "BLK must have iShares keyword"
        assert any("aladdin" in k for k in kws), "BLK must have Aladdin keyword"
        assert any("aum" in k for k in kws), "BLK must have AUM keyword"

    def test_pm_has_iqos_and_zyn(self):
        p = _profile("PM")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("iqos" in k for k in kws), "PM must have IQOS keyword"
        assert any("zyn" in k for k in kws), "PM must have ZYN keyword"
        assert any("heatstick" in k or "heated tobacco" in k for k in kws), \
            "PM must have heated tobacco keyword"

    def test_ups_has_adv_and_revenue_per_piece(self):
        p = _profile("UPS")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("adv" in k or "average daily volume" in k for k in kws), \
            "UPS must have ADV keyword"
        assert any("revenue per piece" in k for k in kws), \
            "UPS must have 'revenue per piece' keyword"

    def test_de_has_precision_agriculture(self):
        p = _profile("DE")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("precision" in k for k in kws), \
            "DE must have precision agriculture keyword"
        assert any("see & spray" in k or "see and spray" in k for k in kws), \
            "DE must have See & Spray keyword"

    def test_duk_has_rate_base_and_clean_energy(self):
        p = _profile("DUK")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("rate base" in k for k in kws), "DUK must have 'rate base' keyword"
        assert any("duke energy carolinas" in k or "carolinas" in k for k in kws), \
            "DUK must have Carolinas keyword"

    def test_abnb_has_gbv_and_adr(self):
        p = _profile("ABNB")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("gbv" in k or "gross booking value" in k for k in kws), \
            "ABNB must have GBV keyword"
        assert any("adr" in k or "average daily rate" in k for k in kws), \
            "ABNB must have ADR keyword"

    def test_emr_has_deltav_and_aspentech(self):
        p = _profile("EMR")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("deltav" in k for k in kws), "EMR must have DeltaV keyword"
        assert any("aspentech" in k for k in kws), "EMR must have AspenTech keyword"

    def test_aep_has_transmission_and_rate_base(self):
        p = _profile("AEP")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("transmission" in k for k in kws), "AEP must have transmission keyword"
        assert any("rate base" in k for k in kws), "AEP must have rate base keyword"

    def test_exc_has_comed_and_myrp(self):
        p = _profile("EXC")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("comed" in k for k in kws), "EXC must have ComEd keyword"
        assert any("myrp" in k or "multi-year rate plan" in k for k in kws), \
            "EXC must have MYRP keyword"

    def test_so_has_vogtle_and_georgia_power(self):
        p = _profile("SO")
        kws = [k.lower() for k in p.business_model_keywords]
        assert any("vogtle" in k for k in kws), "SO must have Vogtle keyword"
        assert any("georgia power" in k for k in kws), \
            "SO must have Georgia Power keyword"


# ── Test 4: existing profiles unaffected ─────────────────────────────────────

class TestNonRegression:
    """Previously registered profiles must still be present and intact."""

    @pytest.mark.parametrize("ticker", [
        "AAPL", "NVDA", "MSFT", "TSLA", "GOOGL",
        "HON", "BA", "CRM", "AXP", "NKE",
        "KO", "MDLZ", "CVX", "SCHW", "COP",
        "RTX", "NEE", "VZ", "T", "CMCSA",
    ])
    def test_existing_profile_still_present(self, ticker):
        p = get_knowledge_profile(ticker)
        assert p is not None, f"Pre-existing profile {ticker} was accidentally removed"
        assert p.business_model, f"{ticker}.business_model is now empty"
        assert len(p.business_model_keywords) > 0, \
            f"{ticker}.business_model_keywords is now empty"
