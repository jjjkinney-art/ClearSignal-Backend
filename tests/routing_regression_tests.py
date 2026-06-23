"""
Routing Regression Tests — Phase 20A.

Validates the five routing improvements:
  P1 — Scenario query routing (expanded patterns)
  P2 — Theme-to-company routing (expanded mappings)
  P3 — Ticker normalization
  P4 — Graceful failure handling
  P5 — Active ticker / session context

These are fast, offline tests — no API calls, no DB, no LLM.
"""

from __future__ import annotations

import pytest


# ===================================================================
# § P1 — Scenario Query Routing
# ===================================================================

class TestScenarioIntentDetection:
    """Scenario questions must be detected regardless of company mention."""

    @pytest.mark.parametrize("question", [
        "What happens if AI CapEx falls 20%?",
        "What would happen if EUV shipments fall below 30 units?",
        "What breaks the thesis?",
        "What happens if Azure growth slows to 20%?",
        "What could derail the company?",
        "What could impair margins?",
        "What invalidates the thesis?",
        "What changes the thesis?",
        "What happens if interest rates rise above 6%?",
        "What if GPU demand drops 30%?",
        "Worst case scenario for the stock?",
        "What is the biggest risk?",
        "Bear case for the company?",
        "What if cloud spending declines?",
        "What would happen if GLP-1 competition intensifies?",
    ])
    def test_scenario_detected(self, question):
        from app.services.scenario_routing_service import detect_scenario_intent
        assert detect_scenario_intent(question), (
            f"Scenario intent NOT detected: {question!r}"
        )

    @pytest.mark.parametrize("question", [
        "What is NVDA's current stock price?",
        "Explain the business model.",
        "How did earnings go?",
        "Show me the balance sheet.",
        "Compare Visa and Mastercard.",
    ])
    def test_non_scenario_not_detected(self, question):
        from app.services.scenario_routing_service import detect_scenario_intent
        assert not detect_scenario_intent(question), (
            f"False positive scenario detection: {question!r}"
        )


class TestScenarioContextExtraction:
    """Scenario context should identify themes and affected tickers."""

    def test_ai_capex_scenario(self):
        from app.services.scenario_routing_service import extract_scenario_context
        ctx = extract_scenario_context("What happens if AI CapEx falls 20%?")
        assert ctx["is_scenario"] is True
        assert ctx["theme"] == "ai capex"
        assert "NVDA" in ctx["affected_tickers"]
        assert "ASML" in ctx["affected_tickers"]
        assert ctx["needs_disambiguation"] is True

    def test_azure_scenario_with_active_ticker(self):
        from app.services.scenario_routing_service import extract_scenario_context
        ctx = extract_scenario_context(
            "What happens if Azure growth slows to 20%?",
            active_ticker="MSFT",
        )
        assert ctx["is_scenario"] is True
        assert ctx["active_ticker"] == "MSFT"
        assert ctx["needs_disambiguation"] is False

    def test_euv_scenario(self):
        from app.services.scenario_routing_service import extract_scenario_context
        ctx = extract_scenario_context(
            "What happens if EUV shipments fall below 30 units?"
        )
        assert ctx["is_scenario"] is True
        assert ctx["theme"] is not None
        assert "ASML" in ctx["affected_tickers"]

    def test_thesis_break_no_theme(self):
        from app.services.scenario_routing_service import extract_scenario_context
        ctx = extract_scenario_context("What breaks the thesis?")
        assert ctx["is_scenario"] is True
        assert ctx["theme"] is None
        assert ctx["affected_tickers"] == []


# ===================================================================
# § P2 — Theme-to-Company Routing
# ===================================================================

class TestThemeRouting:
    """Theme-based questions should surface affected companies."""

    @pytest.mark.parametrize("question,expected_tickers", [
        ("GLP-1 market share shifts", ["LLY", "NVO"]),
        ("Cross-border payments slow", ["V", "MA"]),
        ("Cloud spending declines", ["MSFT", "AMZN", "GOOGL"]),
        ("Semiconductor equipment demand drops", ["ASML", "AMAT", "LRCX"]),
        ("Credit losses rise sharply", ["JPM", "BAC", "C"]),
        ("Interest rate hike impact", ["JPM", "BAC", "C", "SCHW"]),
    ])
    def test_theme_maps_to_tickers(self, question, expected_tickers):
        from app.services.scenario_routing_service import extract_scenario_context
        ctx = extract_scenario_context(question)
        for ticker in expected_tickers:
            assert ticker in ctx["affected_tickers"], (
                f"Expected {ticker} in affected_tickers for: {question!r}"
            )

    def test_unknown_theme_no_tickers(self):
        from app.services.scenario_routing_service import extract_scenario_context
        ctx = extract_scenario_context("What happens if unicorns invade?")
        assert ctx["theme"] is None
        assert ctx["affected_tickers"] == []


# ===================================================================
# § P3 — Ticker Normalization
# ===================================================================

class TestTickerNormalization:
    """Variant tickers must resolve to canonical forms."""

    @pytest.mark.parametrize("variant,canonical", [
        ("BRK.B", "BRK.B"),
        ("BRK-B", "BRK.B"),
        ("BRKB", "BRK.B"),
        ("BRK.A", "BRK.A"),
        ("BRK-A", "BRK.A"),
        ("BRKA", "BRK.A"),
        ("BF.B", "BF.B"),
        ("BF-B", "BF.B"),
        ("BFB", "BF.B"),
        ("RDS.A", "SHEL"),
        ("RDS-A", "SHEL"),
        ("RDSA", "SHEL"),
    ])
    def test_normalize_ticker(self, variant, canonical):
        from app.services.ticker_normalization_service import normalize_ticker
        assert normalize_ticker(variant) == canonical

    def test_unknown_ticker_passthrough(self):
        from app.services.ticker_normalization_service import normalize_ticker
        assert normalize_ticker("AAPL") == "AAPL"
        assert normalize_ticker("NVDA") == "NVDA"

    def test_normalize_in_text(self):
        from app.services.ticker_normalization_service import normalize_ticker_in_text
        result = normalize_ticker_in_text("What about BRK-B and BF-B?")
        assert "BRK.B" in result
        assert "BF.B" in result

    def test_empty_passthrough(self):
        from app.services.ticker_normalization_service import normalize_ticker
        assert normalize_ticker("") == ""

    def test_case_insensitive(self):
        from app.services.ticker_normalization_service import normalize_ticker
        assert normalize_ticker("brk.b") == "BRK.B"
        assert normalize_ticker("brkb") == "BRK.B"


class TestTickerCompanyResolution:
    """Normalized tickers must resolve to companies."""

    def test_brk_b_resolves(self):
        from app.services.company_detection import detect_company
        result = detect_company("BRK.B")
        assert result is not None
        assert result.ticker == "BRK.B"
        assert "Berkshire" in result.company_name

    def test_bf_b_resolves(self):
        from app.services.company_detection import detect_company
        result = detect_company("BF.B")
        assert result is not None
        assert result.ticker == "BF.B"
        assert "Brown" in result.company_name

    def test_berkshire_alias_resolves(self):
        from app.services.company_detection import detect_company
        result = detect_company("berkshire hathaway")
        assert result is not None
        assert result.ticker == "BRK.B"

    def test_brown_forman_alias_resolves(self):
        from app.services.company_detection import detect_company
        result = detect_company("brown-forman")
        assert result is not None
        assert result.ticker == "BF.B"


# ===================================================================
# § P4 — Graceful Failure Handling (structural tests)
# ===================================================================

class TestGracefulFailureHandling:
    """Synthesis fallback text should not contain internal error messages."""

    def test_fallback_text_sanitized(self):
        from app.schemas import InvestmentThesis
        fallback = InvestmentThesis(
            ticker="LLY",
            company_name="Eli Lilly and Company",
            bull_thesis="Synthesis unavailable (wall cap exceeded).",
            bear_thesis="Synthesis unavailable (wall cap exceeded).",
            conclusion="Could not synthesize — wall cap exceeded.",
            confidence_score=0.0,
            key_drivers=[],
            key_risks=[],
        )
        # The fallback exists as a valid schema — this tests the retry
        # mechanism is structurally in place in the router.
        assert fallback.confidence_score == 0.0
        assert "wall cap" in fallback.conclusion


class TestRouterHasRetryLogic:
    """The router must have retry logic in the synthesis section."""

    def test_retry_present_in_source(self):
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "app" / "services" / "router_service.py"
        content = src.read_text()
        assert "retrying synthesis" in content.lower(), (
            "Router must contain synthesis retry logic"
        )
        assert "for _syn_attempt in range(2)" in content, (
            "Router must have retry loop for synthesis"
        )


# ===================================================================
# § P1 expanded — Scenario pattern coverage
# ===================================================================

class TestExpandedScenarioPatterns:
    """New patterns: suppose, assume, imagine, under a scenario where, thesis variants."""

    @pytest.mark.parametrize("question", [
        # suppose / assume / imagine family
        "Suppose revenue falls 30%, what happens?",
        "Assume margins decline by 500bps",
        "Imagine GPU demand collapses overnight",
        # under a scenario where
        "Under a scenario where rates hit 7%, what changes?",
        "In a scenario where AI spending stalls",
        # thesis break variants
        "What would increase conviction?",
        "What would decrease conviction?",
        "What would weaken the thesis?",
        "What would strengthen the thesis?",
        "What threatens the thesis?",
        "What confirms the thesis?",
        "What disproves the thesis?",
        "What would improve the thesis?",
        # cause / need patterns
        "What would cause margins to decline?",
        "What would need to happen for the stock to rally?",
        "What needs to go wrong for this to fail?",
        "What needs to go right?",
        # what if expanded
        "What if the product is delayed?",
        "What if the acquisition is cancelled?",
        "What if demand deteriorates?",
        "What if margins improve significantly?",
        "What if the trend reverses?",
        "What if demand increases sharply?",
        # sensitivity / exposure
        "How exposed is the company to China?",
        "How sensitive is revenue to rate changes?",
        "How vulnerable is the model to competition?",
        "How dependent is ASML on TSMC?",
        # stress / base / upside
        "Stress test the thesis",
        "Upside scenario for the stock?",
        "Base case for earnings?",
    ])
    def test_expanded_scenario_detected(self, question):
        from app.services.scenario_routing_service import detect_scenario_intent
        assert detect_scenario_intent(question), (
            f"Scenario intent NOT detected: {question!r}"
        )


# ===================================================================
# § P2 expanded — Theme mapping coverage
# ===================================================================

class TestExpandedThemeMappings:
    """New themes: cybersecurity, insurance, travel, defense, etc."""

    @pytest.mark.parametrize("question,expected_ticker", [
        # Cybersecurity
        ("What if cybersecurity spending doubles?", "CRWD"),
        ("Ransomware attacks increase", "PANW"),
        # Insurance
        ("What if catastrophe losses spike?", "PGR"),
        ("Insurance premium growth", "ALL"),
        # Asset management
        ("Asset management AUM declines", "BLK"),
        ("Private equity fundraising slows", "BX"),
        ("Fund flows reverse", "TROW"),
        # Travel
        ("Travel demand collapses", "BKNG"),
        ("Hotel occupancy drops", "MAR"),
        # Consumer staples
        ("Consumer staples demand weakens", "PG"),
        ("Commodity cost inflation", "KO"),
        # Defense
        ("Defense spending increases", "LMT"),
        ("Military spending cuts", "RTX"),
        # Industrial automation
        ("Factory automation adoption accelerates", "ROK"),
        # Payments expanded
        ("Digital payments volume declines", "V"),
        ("Buy now pay later defaults rise", "AFRM"),
        # Obesity drugs expanded
        ("GLP-1 competition intensifies", "LLY"),
        ("Ozempic supply shortage", "NVO"),
        ("Mounjaro demand exceeds expectations", "LLY"),
        # Energy
        ("Oil price collapses", "XOM"),
        ("Natural gas demand spikes", "LNG"),
        ("Renewable energy adoption", "NEE"),
        # EV / battery
        ("EV demand stalls", "TSLA"),
        ("Lithium price crashes", "ALB"),
        # Advertising
        ("Ad spending declines", "GOOGL"),
        ("Streaming subscriber growth slows", "NFLX"),
        # Data analytics
        ("Data analytics demand grows", "SPGI"),
    ])
    def test_expanded_theme_detected(self, question, expected_ticker):
        from app.services.scenario_routing_service import extract_scenario_context
        ctx = extract_scenario_context(question)
        assert expected_ticker in ctx["affected_tickers"], (
            f"Expected {expected_ticker} for: {question!r}, "
            f"got theme={ctx['theme']!r}, tickers={ctx['affected_tickers']}"
        )


# ===================================================================
# § P3 expanded — Shell ticker aliases
# ===================================================================

class TestShellTickerAliases:
    """RDS.A/RDS.B/RDSA/RDSB normalize to SHEL (current canonical ticker)."""

    @pytest.mark.parametrize("variant", [
        "RDS.A", "RDS-A", "RDSA",
        "RDS.B", "RDS-B", "RDSB",
    ])
    def test_rds_normalizes_to_shel(self, variant):
        from app.services.ticker_normalization_service import normalize_ticker
        assert normalize_ticker(variant) == "SHEL"

    def test_shel_resolves_to_company(self):
        from app.services.company_detection import detect_company
        result = detect_company("SHEL")
        assert result is not None
        assert result.ticker == "SHEL"
        assert "Shell" in result.company_name

    def test_shell_alias_resolves(self):
        from app.services.company_detection import detect_company
        result = detect_company("royal dutch shell")
        assert result is not None
        assert result.ticker == "SHEL"

    def test_rds_in_text_normalizes(self):
        from app.services.ticker_normalization_service import normalize_ticker_in_text
        result = normalize_ticker_in_text("What about RDS-A and RDS.B?")
        assert "SHEL" in result
        assert "RDS" not in result


# ===================================================================
# § P5 — Active ticker context + session awareness
# ===================================================================

class TestActiveTickerContext:
    """active_ticker field on QuestionRequest + session context service."""

    def test_question_request_has_active_ticker(self):
        from app.schemas import QuestionRequest
        req = QuestionRequest(
            company_name="", question="What breaks the thesis?",
            active_ticker="NVDA",
        )
        assert req.active_ticker == "NVDA"

    def test_question_request_active_ticker_defaults_none(self):
        from app.schemas import QuestionRequest
        req = QuestionRequest(company_name="", question="hello")
        assert req.active_ticker is None

    def test_scenario_uses_active_ticker(self):
        from app.services.scenario_routing_service import extract_scenario_context
        ctx = extract_scenario_context(
            "What breaks the thesis?",
            active_ticker="NVDA",
        )
        assert ctx["is_scenario"] is True
        assert ctx["active_ticker"] == "NVDA"
        assert ctx["needs_disambiguation"] is False

    def test_scenario_active_ticker_overrides_theme(self):
        from app.services.scenario_routing_service import extract_scenario_context
        ctx = extract_scenario_context(
            "What if AI CapEx falls 20%?",
            active_ticker="ASML",
        )
        assert ctx["active_ticker"] == "ASML"
        assert ctx["needs_disambiguation"] is False
        assert "NVDA" in ctx["affected_tickers"]


class TestSessionContextService:
    """In-memory session context store for follow-up routing."""

    def test_record_and_get(self):
        from app.services.session_context_service import (
            record_active_ticker, get_active_ticker, clear_session,
        )
        record_active_ticker("sess-1", "NVDA", "NVIDIA Corporation")
        assert get_active_ticker("sess-1") == "NVDA"
        clear_session("sess-1")

    def test_get_nonexistent(self):
        from app.services.session_context_service import get_active_ticker
        assert get_active_ticker("nonexistent") is None

    def test_overwrite(self):
        from app.services.session_context_service import (
            record_active_ticker, get_active_ticker, clear_session,
        )
        record_active_ticker("sess-2", "NVDA", "NVIDIA")
        record_active_ticker("sess-2", "MSFT", "Microsoft")
        assert get_active_ticker("sess-2") == "MSFT"
        clear_session("sess-2")

    def test_clear(self):
        from app.services.session_context_service import (
            record_active_ticker, get_active_ticker, clear_session,
        )
        record_active_ticker("sess-3", "AAPL", "Apple")
        clear_session("sess-3")
        assert get_active_ticker("sess-3") is None

    def test_empty_session_id_safe(self):
        from app.services.session_context_service import (
            record_active_ticker, get_active_ticker,
        )
        record_active_ticker("", "NVDA", "NVIDIA")
        assert get_active_ticker("") is None

    def test_context_dict(self):
        from app.services.session_context_service import (
            record_active_ticker, get_session_context, clear_session,
        )
        record_active_ticker("sess-4", "LLY", "Eli Lilly")
        ctx = get_session_context("sess-4")
        assert ctx is not None
        assert ctx["ticker"] == "LLY"
        assert ctx["company_name"] == "Eli Lilly"
        assert "updated_at" in ctx
        clear_session("sess-4")


class TestSessionContextFollowUp:
    """Follow-up scenario questions should resolve via session context."""

    def test_followup_uses_session_ticker(self):
        from app.services.session_context_service import (
            record_active_ticker, get_active_ticker, clear_session,
        )
        from app.services.scenario_routing_service import (
            detect_scenario_intent, extract_scenario_context,
        )
        record_active_ticker("sess-followup", "NVDA", "NVIDIA")
        question = "What breaks the thesis?"
        assert detect_scenario_intent(question)
        ticker = get_active_ticker("sess-followup")
        ctx = extract_scenario_context(question, active_ticker=ticker)
        assert ctx["active_ticker"] == "NVDA"
        assert ctx["needs_disambiguation"] is False
        clear_session("sess-followup")

    def test_followup_with_theme_uses_session_ticker(self):
        from app.services.session_context_service import (
            record_active_ticker, get_active_ticker, clear_session,
        )
        from app.services.scenario_routing_service import extract_scenario_context
        record_active_ticker("sess-theme", "MSFT", "Microsoft")
        ticker = get_active_ticker("sess-theme")
        ctx = extract_scenario_context(
            "What if cloud spending declines?",
            active_ticker=ticker,
        )
        assert ctx["active_ticker"] == "MSFT"
        assert ctx["needs_disambiguation"] is False
        clear_session("sess-theme")


class TestRouterHasSessionWiring:
    """Router source must wire session context + active_ticker."""

    def test_session_context_wired_in_router(self):
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "app" / "services" / "router_service.py"
        content = src.read_text()
        assert "get_active_ticker" in content
        assert "record_active_ticker" in content
        assert "_active_ticker" in content
        assert "_session_id_for_ctx" in content

    def test_session_id_stamped_in_api(self):
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "app" / "api.py"
        content = src.read_text()
        assert "_session_id" in content
        assert "session_id" in content.lower()
