"""
tests/test_macro_query_no_company_regression.py

Regression suite: macro / sector queries must NOT be mis-routed to company
investment pipelines due to fuzzy alias matches on common English words.

Root cause (2026-06-08)
-----------------------
Three common English words fuzzy-matched company aliases above the 0.72
routing threshold:

  "report"  → 0.857 with "freeport" (FCX / Freeport-McMoRan)
  "on tech" → 0.824 with "bio n tech" (BNTX / BioNTech)
  "fed"     → 0.750 with "fedex"     (FDX / FedEx)

This caused macro queries such as:
  - "What will the most recent jobs report do to US tech stocks?"
  - "How will the Fed decision affect bank stocks?"
  - "Will tech stocks benefit from lower rates?"

...to be routed to FCX / FDX / BNTX investment theses respectively
instead of the general-finance / market_question pipeline.

Fix
---
Added to _CONTEXT_WORDS in app/services/company_detection.py:
  "report", "reports", "reported", "reporting"
  "jobs", "payroll", "payrolls", "nonfarm", "nonfarm payroll"
  "employment", "unemployment", "cpi", "ppi", "gdp", "pce"
  "fomc", "minutes", "survey", "surveys", "data", "release"
  "tech"  — generic sector abbreviation
  "fed"   — Federal Reserve abbreviation

These words are stripped during _normalize_query() before token-window
generation, so they can never become fuzzy-match candidates.

Real company resolution is unaffected:
  "Freeport-McMoRan" → FCX via explicit_phrase / alias_exact
  "FedEx"            → FDX via alias_exact
  "BioNTech"         → BNTX via alias_exact

Run
---
    python3 -m pytest tests/test_macro_query_no_company_regression.py -v
"""

from __future__ import annotations

import pytest

from app.services.company_detection import detect_company, resolve_entity
from app.services.router_service import _detect_intent, _has_investment_intent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detected_ticker(query: str):
    """Return the ticker detect_company() found, or None."""
    result = detect_company(query)
    return result.ticker if result is not None else None


def _would_route_company(query: str) -> bool:
    """True if the router would fire the investment pipeline for this query."""
    from app.services.company_detection import MINIMUM_ROUTE_CONFIDENCE
    _HIGH_CONF = frozenset({"exact_ticker", "alias_exact"})
    er = resolve_entity(query)
    if er.context is None:
        return False
    meets_threshold = (
        er.method in _HIGH_CONF
        or er.confidence >= MINIMUM_ROUTE_CONFIDENCE
    )
    if not meets_threshold:
        return False
    has_intent = _has_investment_intent(query)
    is_high_conf = er.method in _HIGH_CONF
    return has_intent or is_high_conf


# ── Regression: macro queries must NOT detect a company ──────────────────────

class TestMacroQueriesNoCompanyDetected:
    """Macro / sector questions must produce detect_company() == None.

    These queries have no company name in them.  Any non-None result is
    a false positive that would mis-route to a company investment thesis.
    """

    # Primary regression case: "report" → "freeport" → FCX
    def test_jobs_report_tech_stocks_not_fcx(self):
        """The original bug: 'report' fuzzy-matched 'freeport' → FCX."""
        ticker = _detected_ticker(
            "What will the most recent jobs report do to US tech stocks?"
        )
        assert ticker is None, (
            f"Expected no company detection, got {ticker!r}. "
            "'report' is still fuzzy-matching 'freeport' → FCX."
        )

    def test_jobs_report_impact_on_tech_not_bntx(self):
        """'on tech' must not fuzzy-match 'bio n tech' → BNTX."""
        ticker = _detected_ticker("jobs report impact on tech stocks")
        assert ticker is None, (
            f"Expected no company detection, got {ticker!r}. "
            "'on tech' is still fuzzy-matching 'bio n tech' → BNTX."
        )

    def test_fed_decision_bank_stocks_not_fdx(self):
        """'fed' must not fuzzy-match 'fedex' → FDX."""
        ticker = _detected_ticker(
            "How will the Fed decision affect bank stocks?"
        )
        assert ticker is None, (
            f"Expected no company detection, got {ticker!r}. "
            "'fed' is still fuzzy-matching 'fedex' → FDX."
        )

    def test_tech_stocks_lower_rates_not_bntx(self):
        """'tech' / sector terms must not match 'bio n tech' → BNTX."""
        ticker = _detected_ticker(
            "Will tech stocks benefit from lower rates?"
        )
        assert ticker is None, (
            f"Expected no company detection, got {ticker!r}. "
            "'tech' is still fuzzy-matching a company alias."
        )

    def test_cpi_report_fed_rate_decision_no_company(self):
        """'report' + 'fed' together must not trigger any company match."""
        ticker = _detected_ticker("CPI report and Fed rate decision")
        assert ticker is None, (
            f"Expected no company detection, got {ticker!r}."
        )

    def test_nonfarm_payroll_no_company(self):
        ticker = _detected_ticker(
            "nonfarm payroll surprise what does it mean for stocks"
        )
        assert ticker is None, (
            f"Expected no company detection, got {ticker!r}."
        )

    def test_recent_payroll_data_no_company(self):
        ticker = _detected_ticker("recent payroll data effect on markets")
        assert ticker is None, (
            f"Expected no company detection, got {ticker!r}."
        )

    def test_fed_tech_multiples_no_company(self):
        ticker = _detected_ticker(
            "What does the Fed decision mean for tech stocks?"
        )
        assert ticker is None, (
            f"Expected no company detection, got {ticker!r}."
        )


# ── Regression: macro queries must route to market_question ──────────────────

class TestMacroQueriesRouteIntent:
    """Server-side _detect_intent must classify macro questions correctly.

    These queries contain finance keywords (stocks, rates, markets) so they
    pass the finance gate and must land on market_question, not general_fallback.
    """

    def test_jobs_report_routes_market_question(self):
        intent = _detect_intent(
            "What will the most recent jobs report do to US tech stocks?"
        )
        assert intent == "market_question", (
            f"Expected 'market_question', got {intent!r}."
        )

    def test_fed_bank_stocks_routes_market_question(self):
        intent = _detect_intent(
            "How will the Fed decision affect bank stocks?"
        )
        assert intent == "market_question", (
            f"Expected 'market_question', got {intent!r}."
        )

    def test_tech_rates_routes_market_question(self):
        intent = _detect_intent(
            "Will tech stocks benefit from lower rates?"
        )
        assert intent == "market_question", (
            f"Expected 'market_question', got {intent!r}."
        )

    def test_macro_query_does_not_route_company_pipeline(self):
        """Confirm the full routing simulation skips the investment pipeline."""
        assert not _would_route_company(
            "What will the most recent jobs report do to US tech stocks?"
        ), "Router would still mis-route this macro query to a company pipeline."


# ── Regression: real companies must still resolve correctly ──────────────────

class TestRealCompaniesStillResolve:
    """Adding words to _CONTEXT_WORDS must not break legitimate company routing.

    Freeport-McMoRan, FedEx, and BioNTech each have an explicit name/alias
    that bypasses the fuzzy path — they must still resolve.
    """

    @pytest.mark.parametrize("query,expected_ticker", [
        # FCX — explicit name, not relying on fuzzy "freeport"
        ("Analyze Freeport-McMoRan",            "FCX"),
        ("What is Freeport-McMoRan outlook?",   "FCX"),
        ("FCX copper exposure",                  "FCX"),
        # FDX — alias_exact on "fedex"
        ("Analyze FedEx",                        "FDX"),
        ("FedEx earnings miss guidance",         "FDX"),
        ("FDX operating margin",                 "FDX"),
        # BNTX — alias_exact on "biontech"
        ("Analyze BioNTech",                     "BNTX"),
        ("BioNTech mRNA pipeline",               "BNTX"),
        ("BNTX valuation",                       "BNTX"),
    ])
    def test_real_company_still_detected(self, query, expected_ticker):
        ticker = _detected_ticker(query)
        assert ticker == expected_ticker, (
            f"detect_company({query!r}) → {ticker!r}, expected {expected_ticker!r}. "
            "Adding words to _CONTEXT_WORDS broke a real company resolution."
        )
