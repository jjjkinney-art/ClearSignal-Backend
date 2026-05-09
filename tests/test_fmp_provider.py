"""
Tests for app.services.providers.fmp_provider.

All HTTP calls are intercepted at the _fetch_json level so no real network
requests are made.  FMP_API_KEY is injected via monkeypatch.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from app.services.providers import fmp_provider
from app.schemas import RetrievedEvidence


# ── helpers ───────────────────────────────────────────────────────────────────

def _patch_key(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-fmp-key")


def _patch_fetch(monkeypatch, return_value):
    """Patch _fetch_json in fmp_provider to return *return_value* immediately."""
    monkeypatch.setattr(
        "app.services.providers.fmp_provider._fetch_json",
        lambda url, timeout=8: return_value,
    )


# ── Missing API key ───────────────────────────────────────────────────────────

class TestMissingApiKey:

    def test_search_ticker_no_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        assert fmp_provider.search_ticker("Apple Inc.") == ""

    def test_fetch_company_profile_no_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        assert fmp_provider.fetch_company_profile("AAPL") == []

    def test_fetch_price_change_no_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        assert fmp_provider.fetch_price_change("AAPL") == []

    def test_fetch_income_metrics_no_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        assert fmp_provider.fetch_income_metrics("AAPL") == []

    def test_fetch_debt_metrics_no_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        assert fmp_provider.fetch_debt_metrics("AAPL") == []

    def test_fetch_earnings_calendar_no_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        assert fmp_provider.fetch_earnings_calendar("AAPL") == []

    def test_fetch_company_evidence_no_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        assert fmp_provider.fetch_company_evidence("Apple") == []


# ── search_ticker ─────────────────────────────────────────────────────────────

class TestSearchTicker:

    def test_happy_path_returns_symbol(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, [{"symbol": "AAPL", "name": "Apple Inc."}])
        assert fmp_provider.search_ticker("Apple Inc.") == "AAPL"

    def test_empty_response_returns_empty_string(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, [])
        assert fmp_provider.search_ticker("Unknown Corp") == ""

    def test_non_list_response_returns_empty_string(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, {"Error Message": "bad request"})
        assert fmp_provider.search_ticker("Bad Co") == ""

    def test_network_error_returns_empty_string(self, monkeypatch):
        _patch_key(monkeypatch)
        from urllib.error import URLError
        monkeypatch.setattr(
            "app.services.providers.fmp_provider._fetch_json",
            lambda *a, **kw: (_ for _ in ()).throw(URLError("timeout")),
        )
        assert fmp_provider.search_ticker("Apple") == ""

    def test_http_error_returns_empty_string(self, monkeypatch):
        _patch_key(monkeypatch)
        from urllib.error import HTTPError
        monkeypatch.setattr(
            "app.services.providers.fmp_provider._fetch_json",
            lambda *a, **kw: (_ for _ in ()).throw(HTTPError(None, 429, "Too Many Requests", {}, None)),
        )
        assert fmp_provider.search_ticker("Apple") == ""


# ── fetch_company_profile ─────────────────────────────────────────────────────

_PROFILE_PAYLOAD = [{
    "symbol":            "AAPL",
    "companyName":       "Apple Inc.",
    "price":             175.50,
    "mktCap":            2_700_000_000_000,
    "pe":                28.5,
    "sector":            "Technology",
    "industry":          "Consumer Electronics",
    "exchangeShortName": "NASDAQ",
    "beta":              1.23,
    "description":       "Apple designs and sells consumer electronics.",
    "ipoDate":           "1980-12-12",
}]

class TestFetchCompanyProfile:

    def test_returns_retrieved_evidence_instance(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _PROFILE_PAYLOAD)
        result = fmp_provider.fetch_company_profile("AAPL")
        assert len(result) == 1
        assert isinstance(result[0], RetrievedEvidence)

    def test_title_contains_symbol(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _PROFILE_PAYLOAD)
        assert "AAPL" in fmp_provider.fetch_company_profile("AAPL")[0].title

    def test_title_contains_market_cap(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _PROFILE_PAYLOAD)
        title = fmp_provider.fetch_company_profile("AAPL")[0].title
        assert "2.70T" in title or "Mkt Cap" in title

    def test_summary_contains_sector(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _PROFILE_PAYLOAD)
        summary = fmp_provider.fetch_company_profile("AAPL")[0].summary
        assert "Technology" in summary

    def test_source_is_fmp(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _PROFILE_PAYLOAD)
        assert "Financial Modeling Prep" in fmp_provider.fetch_company_profile("AAPL")[0].source

    def test_relevance_score_above_0_8(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _PROFILE_PAYLOAD)
        assert fmp_provider.fetch_company_profile("AAPL")[0].relevance_score >= 0.80

    def test_empty_response_returns_empty_list(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, [])
        assert fmp_provider.fetch_company_profile("AAPL") == []

    def test_network_error_returns_empty_list(self, monkeypatch):
        _patch_key(monkeypatch)
        from urllib.error import URLError
        monkeypatch.setattr(
            "app.services.providers.fmp_provider._fetch_json",
            lambda *a, **kw: (_ for _ in ()).throw(URLError("connection refused")),
        )
        assert fmp_provider.fetch_company_profile("AAPL") == []


# ── fetch_price_change ────────────────────────────────────────────────────────

_PRICE_CHANGE_PAYLOAD = [{
    "symbol": "AAPL",
    "1D":  1.23,
    "5D": -0.45,
    "1M":  3.10,
    "3M": -2.00,
    "6M":  8.50,
    "ytd": 12.30,
    "1Y":  18.75,
}]

class TestFetchPriceChange:

    def test_returns_evidence(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _PRICE_CHANGE_PAYLOAD)
        result = fmp_provider.fetch_price_change("AAPL")
        assert len(result) == 1

    def test_title_contains_1d_change(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _PRICE_CHANGE_PAYLOAD)
        assert "1D" in fmp_provider.fetch_price_change("AAPL")[0].title

    def test_summary_contains_all_windows(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _PRICE_CHANGE_PAYLOAD)
        summary = fmp_provider.fetch_price_change("AAPL")[0].summary
        for window in ("1-day", "5-day", "1-month", "1-year"):
            assert window in summary

    def test_positive_change_has_plus_sign(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _PRICE_CHANGE_PAYLOAD)
        summary = fmp_provider.fetch_price_change("AAPL")[0].summary
        assert "+1.23%" in summary

    def test_empty_payload_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, [])
        assert fmp_provider.fetch_price_change("AAPL") == []

    def test_error_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        monkeypatch.setattr(
            "app.services.providers.fmp_provider._fetch_json",
            lambda *a, **kw: (_ for _ in ()).throw(Exception("boom")),
        )
        assert fmp_provider.fetch_price_change("AAPL") == []


# ── fetch_income_metrics ──────────────────────────────────────────────────────

_INCOME_PAYLOAD = [
    {
        "date":              "2024-09-28",
        "revenue":           391_035_000_000,
        "grossProfitRatio":  0.4606,
        "netIncomeRatio":    0.2353,
        "ebitda":            130_000_000_000,
    },
    {
        "date":              "2023-09-30",
        "revenue":           383_285_000_000,
        "grossProfitRatio":  0.4413,
        "netIncomeRatio":    0.2253,
        "ebitda":            125_000_000_000,
    },
]

class TestFetchIncomeMetrics:

    def test_returns_evidence(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _INCOME_PAYLOAD)
        result = fmp_provider.fetch_income_metrics("AAPL")
        assert len(result) == 1

    def test_title_contains_revenue(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _INCOME_PAYLOAD)
        assert "Revenue" in fmp_provider.fetch_income_metrics("AAPL")[0].title

    def test_title_contains_margin(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _INCOME_PAYLOAD)
        assert "Margin" in fmp_provider.fetch_income_metrics("AAPL")[0].title

    def test_summary_contains_yoy_growth(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _INCOME_PAYLOAD)
        # Revenue grew ~2% YoY
        summary = fmp_provider.fetch_income_metrics("AAPL")[0].summary
        assert "YoY" in summary

    def test_timestamp_from_period_date(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _INCOME_PAYLOAD)
        assert fmp_provider.fetch_income_metrics("AAPL")[0].timestamp == "2024-09-28"

    def test_empty_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, [])
        assert fmp_provider.fetch_income_metrics("AAPL") == []


# ── fetch_debt_metrics ────────────────────────────────────────────────────────

_DEBT_PAYLOAD = [{
    "date":                    "2024-09-28",
    "totalDebt":               109_000_000_000,
    "netDebt":                  60_000_000_000,
    "cashAndCashEquivalents":   29_000_000_000,
    "debtEquityRatio":          1.87,
}]

class TestFetchDebtMetrics:

    def test_returns_evidence(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _DEBT_PAYLOAD)
        assert len(fmp_provider.fetch_debt_metrics("AAPL")) == 1

    def test_title_contains_total_debt(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _DEBT_PAYLOAD)
        assert "Total Debt" in fmp_provider.fetch_debt_metrics("AAPL")[0].title

    def test_summary_mentions_de_ratio(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _DEBT_PAYLOAD)
        assert "1.87x" in fmp_provider.fetch_debt_metrics("AAPL")[0].summary

    def test_empty_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, [])
        assert fmp_provider.fetch_debt_metrics("AAPL") == []


# ── fetch_earnings_calendar ───────────────────────────────────────────────────

_EARNINGS_PAYLOAD = [
    {"date": "2025-01-30", "epsEstimated": 2.35, "eps": None,
     "revenueEstimated": 124_000_000_000, "revenue": None},
    {"date": "2024-10-31", "epsEstimated": 1.60, "eps": 1.64,
     "revenueEstimated": 94_000_000_000, "revenue": 94_930_000_000},
]

class TestFetchEarningsCalendar:

    def test_returns_evidence(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _EARNINGS_PAYLOAD)
        assert len(fmp_provider.fetch_earnings_calendar("AAPL")) == 1

    def test_title_contains_next_date(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _EARNINGS_PAYLOAD)
        assert "2025-01-30" in fmp_provider.fetch_earnings_calendar("AAPL")[0].title

    def test_summary_contains_eps_estimate(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _EARNINGS_PAYLOAD)
        assert "$2.35" in fmp_provider.fetch_earnings_calendar("AAPL")[0].summary

    def test_empty_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, [])
        assert fmp_provider.fetch_earnings_calendar("AAPL") == []


# ── fetch_company_evidence (top-level) ────────────────────────────────────────

class TestFetchCompanyEvidence:

    def test_ticker_heuristic_skips_search(self, monkeypatch):
        """All-uppercase string ≤ 5 chars is treated as ticker directly."""
        _patch_key(monkeypatch)
        search_calls = []
        monkeypatch.setattr(
            "app.services.providers.fmp_provider.search_ticker",
            lambda name: search_calls.append(name) or "AAPL",
        )
        # Mock all downstream fetches to return []
        for fn in ("fetch_company_profile", "fetch_price_change",
                   "fetch_income_metrics", "fetch_debt_metrics",
                   "fetch_earnings_calendar"):
            monkeypatch.setattr(f"app.services.providers.fmp_provider.{fn}", lambda s: [])

        fmp_provider.fetch_company_evidence("AAPL")
        assert search_calls == []   # ticker detected → search skipped

    def test_company_name_triggers_search(self, monkeypatch):
        _patch_key(monkeypatch)
        search_calls = []
        monkeypatch.setattr(
            "app.services.providers.fmp_provider.search_ticker",
            lambda name: search_calls.append(name) or "AAPL",
        )
        for fn in ("fetch_company_profile", "fetch_price_change",
                   "fetch_income_metrics", "fetch_debt_metrics",
                   "fetch_earnings_calendar"):
            monkeypatch.setattr(f"app.services.providers.fmp_provider.{fn}", lambda s: [])

        fmp_provider.fetch_company_evidence("Apple Inc.")
        assert "Apple Inc." in search_calls

    def test_no_ticker_found_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        monkeypatch.setattr(
            "app.services.providers.fmp_provider.search_ticker",
            lambda name: "",
        )
        assert fmp_provider.fetch_company_evidence("Unknown Corp XYZ") == []

    def test_calls_all_sub_fetches(self, monkeypatch):
        _patch_key(monkeypatch)
        called = []
        for fn in ("fetch_company_profile", "fetch_price_change",
                   "fetch_income_metrics", "fetch_debt_metrics",
                   "fetch_earnings_calendar"):
            _fn = fn  # capture
            monkeypatch.setattr(
                f"app.services.providers.fmp_provider.{fn}",
                lambda s, _fn=_fn: called.append(_fn) or [],
            )
        fmp_provider.fetch_company_evidence("AAPL")
        for fn in ("fetch_company_profile", "fetch_price_change",
                   "fetch_income_metrics", "fetch_debt_metrics",
                   "fetch_earnings_calendar"):
            assert fn in called

    def test_results_combined(self, monkeypatch):
        _patch_key(monkeypatch)
        ev = RetrievedEvidence(title="t", source="FMP", summary="s",
                               timestamp="", relevance_score=0.9)
        for fn in ("fetch_company_profile", "fetch_price_change",
                   "fetch_income_metrics", "fetch_debt_metrics",
                   "fetch_earnings_calendar"):
            monkeypatch.setattr(
                f"app.services.providers.fmp_provider.{fn}",
                lambda s, _ev=ev: [_ev],
            )
        result = fmp_provider.fetch_company_evidence("AAPL")
        assert len(result) == 5   # one from each sub-fetch
