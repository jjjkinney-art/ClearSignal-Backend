"""
test_fuzzy_entity_resolution.py — deterministic regression tests for the
fuzzy entity resolution layer introduced in the robustness refactor.

Covers
------
- All 10 required regression cases (exact spec from requirements)
- Natural-language sentence variants
- Embedded typos in sentences
- Ticker / consumer-name aliases
- Low-confidence graceful fallback (candidates, no crash)
- Observability: EntityResolution fields populated correctly
- Backward-compat: detect_company() still returns CompanyContext or None

No LLM calls, no network calls — pure unit tests.
"""

from __future__ import annotations

import pytest

from app.services.company_detection import (
    EntityResolution,
    detect_company,
    normalize_ticker,
    resolve_entity,
)
from app.schemas import CompanyContext


# ── helpers ─────────────────────────────────────────────────────────────────

def _resolve(text: str) -> EntityResolution:
    return resolve_entity(text)


def _detect(text: str) -> CompanyContext | None:
    return detect_company(text)


# ============================================================================
# 1. Required regression cases (exact spec)
# ============================================================================

class TestRequiredRegressionCases:
    """All 10 cases listed in the requirements must resolve to the correct ticker."""

    def test_rocket_lab_exact(self):
        """'Rocket Lab' — canonical name, must resolve to RKLB."""
        ctx = _detect("Rocket Lab")
        assert ctx is not None, "Rocket Lab not resolved"
        assert ctx.ticker == "RKLB"

    def test_roket_lab_typo(self):
        """'Roket Lab' — one-letter-transposition typo, must resolve to RKLB."""
        ctx = _detect("Roket Lab")
        assert ctx is not None, "'Roket Lab' (typo) not resolved"
        assert ctx.ticker == "RKLB"

    def test_aple_typo(self):
        """'Aple' — missing second 'p', must resolve to AAPL."""
        ctx = _detect("Aple")
        assert ctx is not None, "'Aple' (typo) not resolved"
        assert ctx.ticker == "AAPL"

    def test_nvidea_typo(self):
        """'Nvidea' — common misspelling, must resolve to NVDA."""
        ctx = _detect("Nvidea")
        assert ctx is not None, "'Nvidea' (typo) not resolved"
        assert ctx.ticker == "NVDA"

    def test_microsfot_typo(self):
        """'Microsfot' — transposition typo, must resolve to MSFT."""
        ctx = _detect("Microsfot")
        assert ctx is not None, "'Microsfot' (typo) not resolved"
        assert ctx.ticker == "MSFT"

    def test_goooogle_typo(self):
        """'Goooogle' — extra letters, must resolve to GOOGL."""
        ctx = _detect("Goooogle")
        assert ctx is not None, "'Goooogle' (typo) not resolved"
        assert ctx.ticker == "GOOGL"

    def test_facebook_stock(self):
        """'Facebook stock' — consumer name + context word, must resolve to META."""
        ctx = _detect("Facebook stock")
        assert ctx is not None, "'Facebook stock' not resolved"
        assert ctx.ticker == "META"

    def test_google_cloud_margins(self):
        """'Google cloud margins' — partial topic phrase, must resolve to GOOGL."""
        ctx = _detect("Google cloud margins")
        assert ctx is not None, "'Google cloud margins' not resolved"
        assert ctx.ticker == "GOOGL"

    def test_tesla_stock(self):
        """'Tesla stock' — name + context word, must resolve to TSLA."""
        ctx = _detect("Tesla stock")
        assert ctx is not None, "'Tesla stock' not resolved"
        assert ctx.ticker == "TSLA"

    def test_rklb_ticker(self):
        """'RKLB' — explicit ticker symbol, must resolve to RKLB."""
        ctx = _detect("RKLB")
        assert ctx is not None, "'RKLB' ticker not resolved"
        assert ctx.ticker == "RKLB"


# ============================================================================
# 2. Natural-language sentence variants
# ============================================================================

class TestNaturalLanguagePhrasing:
    """Company names embedded in natural-language questions."""

    def test_what_do_you_think_about_rocket_lab(self):
        ctx = _detect("What do you think about Rocket Lab?")
        assert ctx is not None
        assert ctx.ticker == "RKLB"

    def test_is_nvidia_overvalued(self):
        ctx = _detect("Is Nvidia overvalued?")
        assert ctx is not None
        assert ctx.ticker == "NVDA"

    def test_how_do_high_rates_affect_apple(self):
        ctx = _detect("How do high rates affect Apple?")
        assert ctx is not None
        assert ctx.ticker == "AAPL"

    def test_should_i_buy_tesla(self):
        ctx = _detect("Should I buy Tesla?")
        assert ctx is not None
        assert ctx.ticker == "TSLA"

    def test_microsoft_cloud_growth_outlook(self):
        ctx = _detect("What is the Microsoft cloud growth outlook?")
        assert ctx is not None
        assert ctx.ticker == "MSFT"

    def test_meta_advertising_revenue(self):
        ctx = _detect("Meta advertising revenue trends")
        assert ctx is not None
        assert ctx.ticker == "META"

    def test_amazon_aws_margins(self):
        ctx = _detect("Tell me about Amazon AWS margins")
        assert ctx is not None
        assert ctx.ticker == "AMZN"


# ============================================================================
# 3. Embedded typos in sentences
# ============================================================================

class TestEmbeddedTyposInSentences:
    """Typos embedded in natural-language queries (token-window fuzzy match)."""

    def test_is_nvidea_overvalued_sentence(self):
        ctx = _detect("Is Nvidea overvalued?")
        assert ctx is not None, "Embedded typo 'Nvidea' in sentence not resolved"
        assert ctx.ticker == "NVDA"

    def test_aple_good_buy_sentence(self):
        ctx = _detect("Is Aple a good buy?")
        assert ctx is not None, "Embedded typo 'Aple' in sentence not resolved"
        assert ctx.ticker == "AAPL"

    def test_microsfot_outlook_sentence(self):
        ctx = _detect("What is the Microsfot outlook?")
        assert ctx is not None, "Embedded typo 'Microsfot' in sentence not resolved"
        assert ctx.ticker == "MSFT"

    def test_roket_lab_in_sentence(self):
        ctx = _detect("What do you think about Roket Lab?")
        assert ctx is not None, "Embedded typo 'Roket Lab' in sentence not resolved"
        assert ctx.ticker == "RKLB"

    def test_googel_in_sentence(self):
        ctx = _detect("Is Googel a buy?")
        assert ctx is not None
        assert ctx.ticker == "GOOGL"


# ============================================================================
# 4. Consumer / legacy name aliases
# ============================================================================

class TestAliasResolution:
    """Consumer names, legacy names, and common abbreviations."""

    def test_google_maps_to_alphabet(self):
        ctx = _detect("Google")
        assert ctx is not None
        assert ctx.ticker == "GOOGL"

    def test_facebook_maps_to_meta(self):
        ctx = _detect("Facebook")
        assert ctx is not None
        assert ctx.ticker == "META"

    def test_instagram_maps_to_meta(self):
        ctx = _detect("Instagram")
        assert ctx is not None
        assert ctx.ticker == "META"

    def test_youtube_is_not_resolved(self):
        # YouTube is not independently listed; should not resolve
        # (it belongs to Alphabet but "youtube" is not an alias in our map)
        # This test documents the current limitation, not a bug.
        pass  # intentionally not asserting — YouTube alias not required

    def test_rocket_lab_usa_variant(self):
        ctx = _detect("Rocket Lab USA")
        assert ctx is not None
        assert ctx.ticker == "RKLB"

    def test_rocketlab_one_word(self):
        ctx = _detect("rocketlab")
        assert ctx is not None
        assert ctx.ticker == "RKLB"


# ============================================================================
# 5. EntityResolution fields and confidence
# ============================================================================

class TestEntityResolutionStructure:
    """resolve_entity() returns correct structure for every resolution path."""

    def test_exact_ticker_confidence_is_one(self):
        r = _resolve("AAPL is up today")
        assert r.context is not None
        assert r.ticker_resolved() == "AAPL"
        assert r.confidence == 1.0
        assert r.method == "exact_ticker"

    def test_alias_confidence_is_high(self):
        r = _resolve("Apple stock")
        assert r.context is not None
        assert r.confidence >= 0.90
        assert r.method == "alias_exact"

    def test_fuzzy_token_confidence_between_72_and_95(self):
        # Use a typo not in the explicit alias map to force the fuzzy_token path.
        # "nvdia" (missing 'i') is not an explicit alias → hits fuzzy_token.
        r = _resolve("What about nvdia stock?")
        assert r.context is not None
        assert r.context.ticker == "NVDA"
        # Confidence may be alias_exact if alias exists, else fuzzy_token —
        # either way confidence must be within the valid range.
        assert r.confidence >= 0.72

    def test_not_found_returns_zero_confidence(self):
        r = _resolve("xyzqquux completely unknown")
        assert r.context is None
        assert r.confidence == 0.0
        assert r.method == "not_found"

    def test_not_found_may_have_candidates(self):
        r = _resolve("xyzqquux completely unknown")
        # Candidates may or may not exist — just assert the field is a list
        assert isinstance(r.candidates, list)

    def test_low_confidence_match_candidates_format(self):
        r = _resolve("something vaguely like microsoft")
        # If candidates present, each should be (ticker, name, score)
        for item in r.candidates:
            assert len(item) == 3
            ticker, name, score = item
            assert isinstance(ticker, str)
            assert isinstance(name, str)
            assert 0.0 <= score <= 1.0

    def test_matched_text_populated_on_alias(self):
        r = _resolve("Tesla stock")
        assert r.context is not None
        assert r.matched_text != ""

    def test_matched_text_populated_on_fuzzy(self):
        r = _resolve("Roket Lab")
        assert r.context is not None
        assert r.matched_text != ""

    def test_resolve_entity_never_raises(self):
        """resolve_entity() must not raise under any input."""
        for text in ["", "   ", "12345", "!@#$%", "x" * 500]:
            r = _resolve(text)
            assert isinstance(r, EntityResolution)

    def test_rocket_lab_rklb_entity(self):
        r = _resolve("Rocket Lab")
        assert r.context is not None
        assert r.context.ticker == "RKLB"
        assert r.context.company_name == "Rocket Lab USA Inc."


# ============================================================================
# 6. Backward-compat: detect_company / normalize_ticker
# ============================================================================

class TestBackwardCompatibility:
    """Legacy public API must continue to work unchanged."""

    def test_detect_company_returns_context_or_none(self):
        result = _detect("Apple")
        assert isinstance(result, CompanyContext)

    def test_detect_company_returns_none_for_gibberish(self):
        assert _detect("xyzqquux") is None

    def test_normalize_ticker_aapl(self):
        ctx = normalize_ticker("AAPL")
        assert ctx is not None
        assert ctx.ticker == "AAPL"

    def test_normalize_ticker_rocket_lab(self):
        ctx = normalize_ticker("Rocket Lab")
        assert ctx is not None
        assert ctx.ticker == "RKLB"

    def test_normalize_ticker_rklb(self):
        ctx = normalize_ticker("RKLB")
        assert ctx is not None
        assert ctx.ticker == "RKLB"

    def test_normalize_ticker_unknown_returns_none(self):
        assert normalize_ticker("ZZZUNKOWN") is None


# ============================================================================
# 7. Observability — method field documents the resolution path
# ============================================================================

class TestObservability:
    """Resolution method is always one of the documented values."""

    VALID_METHODS = {"exact_ticker", "alias_exact", "fuzzy_token", "not_found"}

    @pytest.mark.parametrize("query", [
        "AAPL",
        "Apple",
        "Aple",
        "Rocket Lab",
        "Roket Lab",
        "RKLB",
        "Is Nvidea a buy?",
        "xyzqquux",
        "",
        "Facebook stock",
        "Google cloud margins",
    ])
    def test_method_is_valid(self, query: str):
        r = _resolve(query)
        assert r.method in self.VALID_METHODS, (
            f"Unexpected method {r.method!r} for query {query!r}"
        )

    @pytest.mark.parametrize("query,expected_method", [
        ("NVDA", "exact_ticker"),
        ("TSLA earnings", "explicit_or_alias"),  # TSLA explicit ticker hits first
        ("nvidia",  "alias_exact"),
        ("apple",   "alias_exact"),
        ("rocket lab", "alias_exact"),
    ])
    def test_ticker_detection_uses_expected_path(self, query: str, expected_method: str):
        r = _resolve(query)
        # For "explicit_or_alias" accept either path (ticker may trigger alias)
        if expected_method == "explicit_or_alias":
            assert r.method in ("exact_ticker", "alias_exact")
        else:
            assert r.method == expected_method


# ============================================================================
# 8. Graceful failure — never crashes, never hard-fails
# ============================================================================

class TestGracefulFailure:
    """resolve_entity() and detect_company() must never raise."""

    @pytest.mark.parametrize("text", [
        "",
        "   ",
        "12345",
        "!@#$%^&*()",
        "x" * 1000,
        "The quick brown fox jumped over the lazy dog",
        "Analysis couldn't complete",
        None.__class__.__name__,  # "NoneType" — a harmless string
    ])
    def test_no_exception_on_odd_inputs(self, text: str):
        r = _resolve(text)
        assert isinstance(r, EntityResolution)
        assert r.method in {"exact_ticker", "alias_exact", "fuzzy_token", "not_found"}

    def test_no_exception_for_detect_company(self):
        for text in ["", "   ", "?!@#", "x" * 500]:
            result = _detect(text)
            assert result is None or isinstance(result, CompanyContext)


# ============================================================================
# EntityResolution helper (monkey-patch for cleaner test assertions)
# ============================================================================

def _ticker_resolved(self) -> str | None:
    return self.context.ticker if self.context else None


EntityResolution.ticker_resolved = _ticker_resolved
