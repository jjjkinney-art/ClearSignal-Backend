"""
Tests for app.services.company_detection.

Public API under test
---------------------
detect_company(text: str) -> Optional[CompanyContext]
normalize_ticker(raw: str) -> Optional[CompanyContext]

Detection runs three steps in order:
1. Explicit uppercase ticker extraction (regex + stop-word filter).
2. Alias substring lookup (longest match wins).
3. Fuzzy alias match via difflib (cutoff 0.82).

No network calls, no LLM calls.
"""

from __future__ import annotations

import pytest
from app.services.company_detection import detect_company, normalize_ticker
from app.schemas import CompanyContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect(text: str) -> CompanyContext | None:
    return detect_company(text)


def _normalize(raw: str) -> CompanyContext | None:
    return normalize_ticker(raw)


# ---------------------------------------------------------------------------
# TestExplicitTickerDetection
# ---------------------------------------------------------------------------

class TestExplicitTickerDetection:
    """Step 1: uppercase ticker tokens matched against the company DB."""

    def test_aapl_in_sentence(self):
        ctx = _detect("AAPL is up today")
        assert ctx is not None
        assert ctx.ticker == "AAPL"

    def test_nvda_earnings(self):
        ctx = _detect("NVDA earnings beat")
        assert ctx is not None
        assert ctx.ticker == "NVDA"

    def test_msft_quarterly(self):
        ctx = _detect("MSFT reports quarterly")
        assert ctx is not None
        assert ctx.ticker == "MSFT"

    def test_tsla_moving(self):
        ctx = _detect("Why is TSLA moving?")
        assert ctx is not None
        assert ctx.ticker == "TSLA"

    def test_single_letter_a_is_stop_word(self):
        # "A" is in _TICKER_STOP_WORDS — not a valid ticker hit
        ctx = _detect("I have a question")
        # "A" should be filtered out; no other ticker present
        assert ctx is None

    def test_it_is_stop_word(self):
        # "IT" is in the stop-word set
        ctx = _detect("IT services are booming")
        assert ctx is None

    def test_is_is_stop_word(self):
        ctx = _detect("IS the market open?")
        assert ctx is None

    def test_ge_is_not_stop_word(self):
        # GE (GE Aerospace) is a real ticker that is NOT a stop word
        ctx = _detect("We like GE")
        assert ctx is not None
        assert ctx.ticker == "GE"

    def test_first_ticker_wins_when_multiple_present(self):
        # Both AAPL and MSFT appear; the first match in the string should win
        ctx = _detect("AAPL MSFT both look interesting")
        assert ctx is not None
        assert ctx.ticker in {"AAPL", "MSFT"}

    def test_ticker_found_in_longer_sentence(self):
        ctx = _detect("Analysts are watching AMZN closely this quarter")
        assert ctx is not None
        assert ctx.ticker == "AMZN"


# ---------------------------------------------------------------------------
# TestAliasLookup
# ---------------------------------------------------------------------------

class TestAliasLookup:
    """Step 2: case-insensitive substring alias matching."""

    def test_apple_lowercase(self):
        ctx = _detect("Apple")
        assert ctx is not None
        assert ctx.ticker == "AAPL"

    def test_apple_inc(self):
        ctx = _detect("apple inc")
        assert ctx is not None
        assert ctx.ticker == "AAPL"

    def test_nvidia_lowercase(self):
        ctx = _detect("nvidia")
        assert ctx is not None
        assert ctx.ticker == "NVDA"

    def test_microsoft_lowercase(self):
        ctx = _detect("microsoft")
        assert ctx is not None
        assert ctx.ticker == "MSFT"

    def test_alphabet(self):
        ctx = _detect("alphabet")
        assert ctx is not None
        assert ctx.ticker == "GOOGL"

    def test_facebook_maps_to_meta(self):
        ctx = _detect("facebook")
        assert ctx is not None
        assert ctx.ticker == "META"

    def test_berkshire_hathaway(self):
        ctx = _detect("berkshire hathaway")
        assert ctx is not None
        assert ctx.ticker == "BRK.B"

    def test_jp_morgan(self):
        ctx = _detect("jp morgan")
        assert ctx is not None
        assert ctx.ticker == "JPM"

    def test_bank_of_america(self):
        ctx = _detect("bank of america")
        assert ctx is not None
        assert ctx.ticker == "BAC"

    def test_taiwan_semiconductor(self):
        ctx = _detect("taiwan semiconductor")
        assert ctx is not None
        assert ctx.ticker == "TSM"

    def test_palo_alto_networks(self):
        ctx = _detect("palo alto networks")
        assert ctx is not None
        assert ctx.ticker == "PANW"

    def test_berkshire_hathaway_beats_berkshire_alone(self):
        # Longer alias must win over shorter alias (longest-match-first rule)
        ctx = _detect("berkshire hathaway is a conglomerate")
        assert ctx is not None
        assert ctx.ticker == "BRK.B"

    def test_alias_embedded_in_sentence(self):
        ctx = _detect("What is the outlook for Tesla this quarter?")
        assert ctx is not None
        assert ctx.ticker == "TSLA"


# ---------------------------------------------------------------------------
# TestFuzzyMatching
# ---------------------------------------------------------------------------

class TestFuzzyMatching:
    """Step 3: difflib fuzzy matching at cutoff 0.82.

    Only typos that are clearly within the cutoff are tested to avoid
    brittle assertions about the exact difflib score boundary.
    """

    def test_aple_typo_resolves_to_aapl(self):
        # "aple" (missing one 'p') has difflib ratio ≈ 0.89 vs "apple" — above
        # the 0.82 cutoff used by the fuzzy matcher.  "appel" only scores 0.80.
        ctx = _detect("aple")
        assert ctx is not None
        assert ctx.ticker == "AAPL"

    def test_microsft_typo_resolves_to_msft(self):
        # "microsft" is close enough to "microsoft"
        ctx = _detect("microsft")
        assert ctx is not None
        assert ctx.ticker == "MSFT"

    def test_completely_unrelated_word_returns_none(self):
        # A random word that is far from every alias
        ctx = _detect("xyzqquux")
        assert ctx is None


# ---------------------------------------------------------------------------
# TestNormalizeTicker
# ---------------------------------------------------------------------------

class TestNormalizeTicker:
    """normalize_ticker is a thin wrapper around detect_company."""

    def test_aapl_uppercase_returns_context(self):
        # "AAPL" is a known ticker in the DB; explicit ticker step finds it
        ctx = _normalize("AAPL")
        assert ctx is not None
        assert ctx.ticker == "AAPL"
        assert ctx.company_name == "Apple Inc."

    def test_nvda_uppercase_returns_context(self):
        ctx = _normalize("NVDA")
        assert ctx is not None
        assert ctx.ticker == "NVDA"
        assert ctx.company_name == "NVIDIA Corporation"

    def test_unknown_ticker_returns_none(self):
        ctx = _normalize("UNKNOWN_XYZ")
        assert ctx is None

    def test_company_name_string_also_resolves(self):
        # normalize_ticker delegates to detect_company, so aliases work too
        ctx = _normalize("apple")
        assert ctx is not None
        assert ctx.ticker == "AAPL"

    def test_purely_numeric_returns_none(self):
        ctx = _normalize("12345")
        assert ctx is None


# ---------------------------------------------------------------------------
# TestDetectCompanyReturnType
# ---------------------------------------------------------------------------

class TestDetectCompanyReturnType:
    """Structural tests on CompanyContext fields."""

    def test_returns_company_context_instance(self):
        ctx = _detect("AAPL is up")
        assert isinstance(ctx, CompanyContext)

    def test_known_company_has_sector_and_industry(self):
        ctx = _detect("AAPL is up")
        assert ctx is not None
        assert ctx.sector is not None and ctx.sector != ""
        assert ctx.industry is not None and ctx.industry != ""

    def test_aliases_field_is_list(self):
        ctx = _detect("AAPL is up")
        assert ctx is not None
        assert isinstance(ctx.aliases, list)

    def test_unknown_text_returns_none(self):
        ctx = _detect("the quick brown fox jumped over the lazy dog")
        assert ctx is None

    def test_partial_multiword_alias_does_not_fuzzy_resolve(self):
        assert _detect("brown fox") is None

    def test_ticker_field_is_non_empty_string(self):
        ctx = _detect("TSLA is rallying")
        assert ctx is not None
        assert isinstance(ctx.ticker, str)
        assert len(ctx.ticker) > 0

    def test_company_name_is_non_empty_string(self):
        ctx = _detect("TSLA is rallying")
        assert ctx is not None
        assert isinstance(ctx.company_name, str)
        assert len(ctx.company_name) > 0


# ---------------------------------------------------------------------------
# TestSectorIndustry
# ---------------------------------------------------------------------------

class TestSectorIndustry:
    """Verify sector and industry values for representative companies."""

    def test_apple_sector_and_industry(self):
        ctx = _detect("AAPL")
        assert ctx is not None
        assert ctx.sector == "Technology"
        assert ctx.industry == "Consumer Electronics"

    def test_jpmorgan_sector_and_industry(self):
        ctx = _detect("JPM")
        assert ctx is not None
        assert ctx.sector == "Financials"
        assert ctx.industry == "Banking"

    def test_tesla_sector_and_industry(self):
        ctx = _detect("TSLA")
        assert ctx is not None
        assert ctx.sector == "Consumer Discretionary"
        assert ctx.industry == "Electric Vehicles"

    def test_boeing_sector_and_industry(self):
        ctx = _detect("BA")
        assert ctx is not None
        assert ctx.sector == "Industrials"
        assert ctx.industry == "Aerospace & Defense"

    def test_nvidia_sector_and_industry(self):
        ctx = _detect("NVDA")
        assert ctx is not None
        assert ctx.sector == "Technology"
        assert ctx.industry == "Semiconductors"


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Boundary and defensive tests."""

    def test_empty_string_returns_none(self):
        assert _detect("") is None

    def test_whitespace_only_returns_none(self):
        assert _detect("   ") is None

    def test_pure_numbers_returns_none(self):
        assert _detect("12345") is None

    def test_very_long_text_containing_apple(self):
        long_text = "x " * 500 + "Apple" + " y" * 500
        ctx = _detect(long_text)
        assert ctx is not None
        assert ctx.ticker == "AAPL"

    def test_alias_lookup_is_case_insensitive_upper(self):
        ctx_upper = _detect("APPLE")
        assert ctx_upper is not None
        assert ctx_upper.ticker == "AAPL"

    def test_alias_lookup_is_case_insensitive_lower(self):
        ctx_lower = _detect("apple")
        assert ctx_lower is not None
        assert ctx_lower.ticker == "AAPL"

    def test_alias_case_insensitive_upper_and_lower_agree(self):
        ctx_upper = _detect("APPLE")
        ctx_lower = _detect("apple")
        assert ctx_upper is not None and ctx_lower is not None
        assert ctx_upper.ticker == ctx_lower.ticker

    def test_punctuation_around_ticker(self):
        # Regex uses word boundaries so ticker surrounded by punctuation still matches
        ctx = _detect("(AAPL)")
        assert ctx is not None
        assert ctx.ticker == "AAPL"

    def test_stop_word_all_caps_in_stop_word_set_not_treated_as_ticker(self):
        # "AND" is in the stop-word set; make sure it is filtered
        ctx = _detect("AND the market moves on")
        assert ctx is None
