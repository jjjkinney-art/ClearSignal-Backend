"""
tests/test_entity_resolution.py

Entity Resolution test suite — verifies the company/ticker resolver correctly
identifies intended companies from natural-language queries, handles generic-word
tickers, and flags ambiguous cases for clarification.

The primary regression case that triggered this suite:
    "Can Meta continue compounding despite AI infrastructure spending pressure?"
    → Must resolve to META (Meta Platforms), NOT AI (C3.ai)

Run:
    python3 -m pytest tests/test_entity_resolution.py -v --tb=short
"""

from __future__ import annotations

import pytest
from app.services.entity_resolution_service import resolve_query, resolve_for_analysis, EntityResolutionResult
from app.services.company_detection import (
    resolve_entity,
    detect_company,
    PROTECTED_GENERIC_TICKERS,
    _TICKER_STOP_WORDS,
    MINIMUM_ROUTE_CONFIDENCE,
)


# ===========================================================================
# Class 1 — Primary regression cases (the live-site bug)
# ===========================================================================

class TestPrimaryRegressionCases:
    """The exact queries that triggered the entity resolution overhaul."""

    def test_meta_wins_over_ai_in_query(self):
        """Primary regression: 'Meta' must win over incidental 'AI' token."""
        result = resolve_query(
            "Can Meta continue compounding despite AI infrastructure spending pressure?"
        )
        assert result.canonical_ticker == "META", (
            f"Expected META, got {result.canonical_ticker!r} via {result.resolution_method!r}. "
            "The word 'AI' in the query must not be resolved as C3.ai (AI) when "
            "the company name 'Meta' is explicitly present."
        )
        assert result.company_name == "Meta Platforms Inc."
        assert not result.needs_clarification

    def test_meta_confidence_is_high(self):
        result = resolve_query(
            "Can Meta continue compounding despite AI infrastructure spending pressure?"
        )
        assert result.confidence_score >= MINIMUM_ROUTE_CONFIDENCE

    def test_meta_resolution_method_is_alias(self):
        """Meta should resolve via alias_exact, not fuzzy."""
        result = resolve_query("Can Meta compound despite AI capex spending?")
        assert result.resolution_method == "alias_exact"

    def test_facebook_resolves_to_meta(self):
        result = resolve_query("Is Facebook still investable?")
        assert result.canonical_ticker == "META"

    def test_meta_resolve_for_analysis_pipeline(self):
        """Simulates the exact analysis_service call path."""
        result = resolve_for_analysis(
            user_question="Can Meta continue compounding despite AI infrastructure spending pressure?",
            company_hint="Meta",
        )
        assert result.canonical_ticker == "META"
        assert not result.needs_clarification


# ===========================================================================
# Class 2 — Explicit C3.ai resolution
# ===========================================================================

class TestC3aiExplicitResolution:
    """C3.ai should resolve when the user clearly means C3.ai, not 'AI' generically."""

    def test_c3ai_dot_notation_resolves(self):
        """'C3.ai' explicit form → AI ticker."""
        result = resolve_query("Is C3.ai investable at current valuation?")
        assert result.canonical_ticker == "AI"
        assert "C3.ai" in result.company_name or result.company_name == "C3.ai Inc."

    def test_c3_space_ai_resolves(self):
        result = resolve_query("What do you think about C3 AI valuation?")
        assert result.canonical_ticker == "AI"

    def test_ticker_ai_phrase_resolves(self):
        """Explicit 'ticker AI' phrase triggers override."""
        result = resolve_query("What is the outlook for ticker AI?")
        assert result.canonical_ticker == "AI"

    def test_dollar_ai_resolves(self):
        """$AI notation → C3.ai."""
        result = resolve_query("Is $AI a buy at current valuation?")
        assert result.canonical_ticker == "AI"


# ===========================================================================
# Class 3 — Needs clarification cases
# ===========================================================================

class TestNeedsClarification:
    """Genuinely ambiguous queries should trigger needs_clarification."""

    def test_ai_alone_needs_clarification(self):
        """'Is AI investable?' — ambiguous, must trigger clarification."""
        result = resolve_query("Is AI investable?")
        assert result.needs_clarification, (
            "Query 'Is AI investable?' should return needs_clarification=True "
            "because 'AI' is both a ticker (C3.ai) and artificial intelligence."
        )
        assert result.clarification_prompt, "clarification_prompt must be non-empty"
        # Should not resolve to a ticker silently
        assert not result.canonical_ticker

    def test_ai_needs_clarification_includes_c3ai_hint(self):
        result = resolve_query("Is AI investable?")
        assert "C3.ai" in result.clarification_prompt or "AI" in result.clarification_prompt

    def test_standalone_snow_needs_clarification(self):
        """Standalone uppercase SNOW with no company context → clarification."""
        result = resolve_query("Is SNOW overvalued at current multiples?")
        assert result.needs_clarification or result.canonical_ticker == "SNOW", (
            "SNOW uppercase standalone should either clarify or resolve to Snowflake — "
            "but must NEVER be confused with weather."
        )
        # If it resolved (not clarification), it should be SNOW
        if not result.needs_clarification:
            assert result.canonical_ticker == "SNOW"


# ===========================================================================
# Class 4 — Company name resolutions (11 spec test cases)
# ===========================================================================

class TestSpecTestCases:
    """All 11 test cases from the specification."""

    def test_01_meta_wins_over_ai(self):
        """TC-01: Meta + AI in query → META."""
        result = resolve_query(
            "Can Meta continue compounding despite AI infrastructure spending pressure?"
        )
        assert result.canonical_ticker == "META"

    def test_02_c3ai_explicit(self):
        """TC-02: 'C3.ai' explicit → AI."""
        result = resolve_query("Is C3.ai investable at current valuation?")
        assert result.canonical_ticker == "AI"

    def test_03_ai_alone_needs_clarification(self):
        """TC-03: 'Is AI investable?' → needs_clarification."""
        result = resolve_query("Is AI investable?")
        assert result.needs_clarification

    def test_04_microsoft_resolves(self):
        """TC-04: Microsoft → MSFT."""
        result = resolve_query(
            "Can Microsoft continue compounding without multiple expansion?"
        )
        assert result.canonical_ticker == "MSFT"
        assert not result.needs_clarification

    def test_05_nvidia_resolves(self):
        """TC-05: Nvidia → NVDA."""
        result = resolve_query(
            "Does Nvidia still offer asymmetric upside at current expectations?"
        )
        assert result.canonical_ticker == "NVDA"
        assert not result.needs_clarification

    def test_06_applovin_resolves(self):
        """TC-06: 'Is AppLovin still undervalued?' → APP."""
        result = resolve_query("Is AppLovin still undervalued?")
        assert result.canonical_ticker == "APP"
        assert not result.needs_clarification

    def test_07_this_app_does_not_resolve_to_applovin(self):
        """TC-07: 'Is this app investable?' must NOT resolve to AppLovin."""
        result = resolve_query("Is this app investable?")
        # Either returns not_found or needs_clarification — but NOT APP
        assert result.canonical_ticker != "APP", (
            "'Is this app investable?' used 'app' as a generic English word — "
            "must not resolve to AppLovin (APP)."
        )

    def test_08_alphabet_resolves(self):
        """TC-08: 'Is Alphabet still cheap after AI capex?' → GOOGL."""
        result = resolve_query("Is Alphabet still cheap after AI capex?")
        assert result.canonical_ticker == "GOOGL"
        assert not result.needs_clarification

    def test_09_google_resolves(self):
        """TC-09: 'Is Google still cheap after AI capex?' → GOOGL."""
        result = resolve_query("Is Google still cheap after AI capex?")
        assert result.canonical_ticker == "GOOGL"
        assert not result.needs_clarification

    def test_10_snowflake_resolves(self):
        """TC-10: 'Can Snowflake reaccelerate?' → SNOW."""
        result = resolve_query("Can Snowflake reaccelerate?")
        assert result.canonical_ticker == "SNOW"
        assert not result.needs_clarification

    def test_11_snow_weather_does_not_resolve(self):
        """TC-11: 'Is snow impacting retail demand?' must NOT resolve to Snowflake."""
        result = resolve_query("Is snow impacting retail demand?")
        # Should NOT resolve to SNOW — "snow" is lowercase/weather context
        assert result.canonical_ticker != "SNOW", (
            "'Is snow impacting retail demand?' uses 'snow' as weather term — "
            "must not resolve to Snowflake (SNOW)."
        )
        assert not result.needs_clarification or result.canonical_ticker == ""


# ===========================================================================
# Class 5 — Stop-word protection
# ===========================================================================

class TestStopWordProtection:
    """Protected generic-word tickers must not fire as exact_ticker via Step 1."""

    def test_ai_is_in_stop_words(self):
        assert "AI" in _TICKER_STOP_WORDS

    def test_app_is_in_stop_words(self):
        assert "APP" in _TICKER_STOP_WORDS

    def test_net_is_in_stop_words(self):
        assert "NET" in _TICKER_STOP_WORDS

    def test_snow_is_in_stop_words(self):
        assert "SNOW" in _TICKER_STOP_WORDS

    def test_dash_is_in_stop_words(self):
        assert "DASH" in _TICKER_STOP_WORDS

    def test_path_is_in_stop_words(self):
        assert "PATH" in _TICKER_STOP_WORDS

    def test_open_is_in_stop_words(self):
        assert "OPEN" in _TICKER_STOP_WORDS

    def test_arm_is_in_stop_words(self):
        assert "ARM" in _TICKER_STOP_WORDS

    def test_now_is_in_stop_words(self):
        assert "NOW" in _TICKER_STOP_WORDS

    def test_protected_generic_tickers_populated(self):
        for ticker in ("AI", "APP", "NET", "SNOW", "DASH", "PATH", "OPEN"):
            assert ticker in PROTECTED_GENERIC_TICKERS, f"'{ticker}' missing from PROTECTED_GENERIC_TICKERS"

    def test_ai_upper_in_sentence_does_not_auto_resolve(self):
        """Uppercase AI in a sentence must not auto-resolve to C3.ai via exact_ticker."""
        # company_detection.resolve_entity should NOT return AI as exact_ticker here
        result = resolve_entity("Will AI help or hurt Meta's business?")
        # It should either: (a) resolve META, or (b) return not_found
        # It must NOT return C3.ai via exact_ticker
        if result.context is not None:
            assert result.context.ticker != "AI" or result.method != "exact_ticker", (
                "resolve_entity returned AI as exact_ticker for 'AI' in a sentence. "
                "AI must be in _TICKER_STOP_WORDS to prevent this."
            )


# ===========================================================================
# Class 6 — Alias resolution (company names)
# ===========================================================================

class TestAliasResolution:
    """Company names and aliases should resolve correctly via alias_exact."""

    def test_cloudflare_resolves_to_net(self):
        result = resolve_query("Is Cloudflare overvalued?")
        assert result.canonical_ticker == "NET"

    def test_servicenow_resolves_to_now(self):
        result = resolve_query("Can ServiceNow maintain its NRR?")
        assert result.canonical_ticker == "NOW"

    def test_doordash_resolves_to_dash(self):
        result = resolve_query("Is DoorDash profitable yet?")
        assert result.canonical_ticker == "DASH"

    def test_arm_holdings_resolves(self):
        result = resolve_query("Is Arm Holdings fairly valued?")
        assert result.canonical_ticker == "ARM"

    def test_shopify_resolves_to_shop(self):
        result = resolve_query("Can Shopify regain its growth premium?")
        assert result.canonical_ticker == "SHOP"

    def test_uipath_resolves_to_path(self):
        result = resolve_query("Is UiPath gaining traction in enterprise?")
        assert result.canonical_ticker == "PATH"

    def test_opendoor_resolves_to_open(self):
        result = resolve_query("Is Opendoor positioned for a housing recovery?")
        assert result.canonical_ticker == "OPEN"

    def test_tesla_resolves(self):
        result = resolve_query("Can Tesla defend its margin at lower prices?")
        assert result.canonical_ticker == "TSLA"

    def test_nvidia_alias_resolves(self):
        result = resolve_query("Is Nvidia approaching bubble territory?")
        assert result.canonical_ticker == "NVDA"

    def test_apple_resolves(self):
        result = resolve_query("Does Apple have room to expand services margin?")
        assert result.canonical_ticker == "AAPL"

    def test_amazon_resolves(self):
        result = resolve_query("Is Amazon AWS growth reaccelerating?")
        assert result.canonical_ticker == "AMZN"


# ===========================================================================
# Class 7 — resolve_for_analysis (pipeline integration)
# ===========================================================================

class TestResolveForAnalysis:
    """Tests for the resolve_for_analysis() wrapper used by analysis_service."""

    def test_prefers_longer_user_question(self):
        """Full question has more context — should be primary."""
        result = resolve_for_analysis(
            user_question="Can Meta continue compounding despite AI infrastructure spending?",
            company_hint="AI",
        )
        # Even with company_hint="AI", full question should resolve META
        assert result.canonical_ticker == "META"

    def test_falls_back_to_hint_when_question_empty(self):
        result = resolve_for_analysis(user_question="", company_hint="Nvidia")
        assert result.canonical_ticker == "NVDA"

    def test_hint_with_ticker_resolves(self):
        result = resolve_for_analysis(user_question="", company_hint="TSLA")
        assert result.canonical_ticker == "TSLA"

    def test_hint_with_company_name_resolves(self):
        result = resolve_for_analysis(user_question="", company_hint="Microsoft")
        assert result.canonical_ticker == "MSFT"

    def test_meta_capex_question_resolves_meta(self):
        result = resolve_for_analysis(
            user_question="Is Meta's AI capex justified by Reels monetization?",
            company_hint="",
        )
        assert result.canonical_ticker == "META"

    def test_returns_entity_resolution_result_type(self):
        result = resolve_for_analysis(user_question="Is Nvidia cheap?", company_hint="")
        assert isinstance(result, EntityResolutionResult)

    def test_not_found_does_not_raise(self):
        result = resolve_for_analysis(user_question="xyz nonsense gibberish", company_hint="")
        assert result.canonical_ticker == "" or result.needs_clarification
        # Should not raise any exception


# ===========================================================================
# Class 8 — AppLovin DB entry
# ===========================================================================

class TestAppLovinDatabase:
    """AppLovin (APP) must be correctly registered."""

    def test_applovin_alias_resolves(self):
        from app.services.company_detection import _ALIAS_MAP, _COMPANY_DB
        assert "applovin" in _ALIAS_MAP
        assert _ALIAS_MAP["applovin"] == "APP"

    def test_applovin_in_company_db(self):
        from app.services.company_detection import _COMPANY_DB
        assert "APP" in _COMPANY_DB
        assert _COMPANY_DB["APP"]["company_name"] == "AppLovin Corporation"

    def test_app_string_alone_does_not_resolve(self):
        """'app' alone (lowercase) must not resolve to AppLovin."""
        result = detect_company("Is this app investable?")
        # Should be None or something other than APP
        if result is not None:
            assert result.ticker != "APP", (
                "detect_company resolved 'Is this app investable?' to AppLovin (APP). "
                "The word 'app' is too generic to auto-resolve."
            )

    def test_applovin_full_name_resolves(self):
        result = resolve_query("Is AppLovin Corporation a buy?")
        assert result.canonical_ticker == "APP"


# ===========================================================================
# Class 9 — EntityResolutionResult structure
# ===========================================================================

class TestEntityResolutionResultSchema:
    """EntityResolutionResult has correct fields and defaults."""

    def test_result_fields_present(self):
        result = EntityResolutionResult()
        assert hasattr(result, "canonical_ticker")
        assert hasattr(result, "company_name")
        assert hasattr(result, "confidence_score")
        assert hasattr(result, "matched_alias")
        assert hasattr(result, "resolution_method")
        assert hasattr(result, "ambiguity_reason")
        assert hasattr(result, "needs_clarification")
        assert hasattr(result, "clarification_prompt")
        assert hasattr(result, "resolution_warning")
        assert hasattr(result, "sector")
        assert hasattr(result, "industry")
        assert hasattr(result, "candidates")

    def test_defaults_are_safe(self):
        result = EntityResolutionResult()
        assert result.canonical_ticker == ""
        assert result.needs_clarification is False
        assert result.confidence_score == 0.0
        assert result.candidates == []

    def test_successful_resolution_fields(self):
        result = resolve_query("Is Tesla overvalued?")
        assert result.canonical_ticker == "TSLA"
        assert result.company_name
        assert result.confidence_score > 0
        assert result.resolution_method in ("alias_exact", "exact_ticker", "fuzzy_token", "explicit_phrase")
        assert not result.needs_clarification

    def test_not_found_result_fields(self):
        result = resolve_query("xyzquibble 7nonsense123")
        assert result.canonical_ticker == ""
        assert result.confidence_score == 0.0
        assert result.resolution_method in ("not_found", "needs_clarification")
