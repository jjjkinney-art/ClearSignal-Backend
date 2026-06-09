"""
Tests for app.db.ticker_normalizer — pure Python, no DB required.
"""

from __future__ import annotations

import pytest
from app.db.ticker_normalizer import normalize_ticker, canonical_ticker_for_thesis


class TestNormalizeTicker:

    def test_exact_ticker_passthrough(self):
        assert normalize_ticker("NVDA") == "NVDA"

    def test_lowercase_ticker(self):
        assert normalize_ticker("nvda") == "NVDA"

    def test_full_company_name(self):
        assert normalize_ticker("NVIDIA Corporation") == "NVDA"

    def test_alias(self):
        assert normalize_ticker("Nvidia") == "NVDA"

    def test_jpmorgan_variants(self):
        assert normalize_ticker("JPMorgan Chase") == "JPM"
        assert normalize_ticker("jpmorgan") == "JPM"
        assert normalize_ticker("J.P. Morgan") == "JPM"

    def test_apple_variants(self):
        assert normalize_ticker("Apple") == "AAPL"
        assert normalize_ticker("Apple Inc.") == "AAPL"
        assert normalize_ticker("AAPL") == "AAPL"

    def test_microsoft_variants(self):
        assert normalize_ticker("Microsoft") == "MSFT"
        assert normalize_ticker("microsoft corporation") == "MSFT"

    def test_alphabet_variants(self):
        assert normalize_ticker("Alphabet") == "GOOGL"
        assert normalize_ticker("Google") == "GOOGL"
        assert normalize_ticker("GOOGL") == "GOOGL"

    def test_amazon_variants(self):
        assert normalize_ticker("Amazon") == "AMZN"
        assert normalize_ticker("amazon.com") == "AMZN"

    def test_tsmc_variants(self):
        assert normalize_ticker("TSMC") == "TSM"
        assert normalize_ticker("Taiwan Semiconductor") == "TSM"
        assert normalize_ticker("TSM") == "TSM"

    def test_meta_variants(self):
        assert normalize_ticker("Meta") == "META"
        assert normalize_ticker("Facebook") == "META"
        assert normalize_ticker("META") == "META"

    def test_unknown_passthrough_uppercased(self):
        result = normalize_ticker("FOOBAR_UNKNOWN_CO")
        assert result == "FOOBAR_UNKNOWN_CO"

    def test_empty_string_returns_unknown(self):
        assert normalize_ticker("") == "UNKNOWN"

    def test_truncation_at_20_chars(self):
        long_name = "A" * 25
        result = normalize_ticker(long_name)
        assert len(result) <= 20

    def test_whitespace_stripped(self):
        assert normalize_ticker("  NVDA  ") == "NVDA"
        assert normalize_ticker("  Nvidia  ") == "NVDA"

    def test_case_insensitive_full_name(self):
        assert normalize_ticker("NVIDIA CORPORATION") == "NVDA"
        assert normalize_ticker("nvidia corporation") == "NVDA"

    def test_costco(self):
        assert normalize_ticker("Costco") == "COST"
        assert normalize_ticker("Costco Wholesale") == "COST"

    def test_visa(self):
        assert normalize_ticker("Visa") == "V"
        assert normalize_ticker("Visa Inc") == "V"


class TestCanonicalTickerForThesis:

    def test_uses_thesis_ticker_first(self):
        thesis = {"ticker": "NVDA", "company_name": "NVIDIA Corporation"}
        assert canonical_ticker_for_thesis(thesis, "NVIDIA") == "NVDA"

    def test_falls_back_to_thesis_company_name(self):
        thesis = {"ticker": "", "company_name": "NVIDIA Corporation"}
        assert canonical_ticker_for_thesis(thesis, "") == "NVDA"

    def test_falls_back_to_arg_company_name(self):
        thesis = {"ticker": "", "company_name": ""}
        assert canonical_ticker_for_thesis(thesis, "Costco Wholesale") == "COST"

    def test_normalizes_thesis_ticker(self):
        thesis = {"ticker": "nvidia", "company_name": "NVIDIA Corp"}
        assert canonical_ticker_for_thesis(thesis) == "NVDA"

    def test_empty_all_returns_unknown(self):
        thesis = {}
        result = canonical_ticker_for_thesis(thesis)
        assert result == "UNKNOWN"

    def test_company_name_arg_default(self):
        """company_name has a default of '' so can be called with just thesis."""
        thesis = {"ticker": "AAPL"}
        assert canonical_ticker_for_thesis(thesis) == "AAPL"
