"""
tests/test_fix_entity_resolution_and_routing.py

Regression tests for two fixes applied to the question-answering path:

Fix A — entity_resolution_service.resolve_for_analysis
    company_hint (AnalysisRequest.company_name) is now authoritative when
    non-empty.  A question that mentions competitor names must not override
    the explicitly supplied company.

Fix B — router_service.route_question
    When company_name is supplied and the question has investment intent,
    the request is routed to the full investment pipeline rather than
    falling through to keyword-based equity routing.  Validated via
    detect_company() resolution (prerequisite for the routing branch).

Primary regression case that triggered these fixes:
    company_name="COST"
    question="Costco consistently trades at a 40-50x earnings premium versus
              Walmart at 25-30x and Target at 15-20x..."
    Previously resolved to: Walmart Inc. (WMT)  ← WRONG
    After Fix A: Costco Wholesale Corporation (COST)  ← CORRECT

Run:
    python3 -m pytest tests/test_fix_entity_resolution_and_routing.py -v --tb=short
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from app.services.entity_resolution_service import resolve_for_analysis
from app.services.company_detection import detect_company


# ===========================================================================
# Fix A — resolve_for_analysis: company_hint is authoritative
# ===========================================================================

class TestResolveForAnalysisFixA:
    """company_hint must be authoritative when non-empty and resolvable."""

    # ── Primary regression case ───────────────────────────────────────────

    def test_cost_not_overridden_by_walmart_in_question(self):
        """COST must resolve to Costco, not Walmart, even when Walmart appears in question."""
        result = resolve_for_analysis(
            company_hint="COST",
            user_question=(
                "Costco consistently trades at a 40-50x earnings premium versus "
                "Walmart at 25-30x and Target at 15-20x. Is the premium structurally "
                "justified, and what single metric would cause it to compress?"
            ),
        )
        assert result.canonical_ticker == "COST", (
            f"Expected COST, got {result.canonical_ticker!r}. "
            "Walmart mention in the question must not override the explicit company_hint."
        )

    def test_cost_resolves_to_costco(self):
        """Resolved company name must be Costco, not Walmart."""
        result = resolve_for_analysis(company_hint="COST", user_question="dummy question")
        assert result.canonical_ticker == "COST"
        assert "costco" in result.company_name.lower(), (
            f"Expected Costco in company name, got: {result.company_name!r}"
        )

    # ── TSM with multiple named competitors ──────────────────────────────

    def test_tsm_not_overridden_by_apple_nvidia_amd_in_question(self):
        """TSM must resolve to TSMC even when Apple, Nvidia, AMD appear in question."""
        result = resolve_for_analysis(
            company_hint="TSM",
            user_question=(
                "How does TSMC's manufacturing moat in N3 and N2 translate into "
                "pricing power with its top five customers — Apple, Nvidia, AMD, "
                "Qualcomm, and Broadcom — and what is the ceiling given Intel "
                "Foundry and Samsung as alternatives?"
            ),
        )
        assert result.canonical_ticker == "TSM", (
            f"Expected TSM, got {result.canonical_ticker!r}. "
            "Named competitors (Apple, Nvidia, AMD) must not override TSM hint."
        )

    # ── NVDA and MSFT baseline ────────────────────────────────────────────

    def test_nvda_hint_resolves_correctly(self):
        result = resolve_for_analysis(
            company_hint="NVDA",
            user_question=(
                "At Nvidia's current P/E multiple, what is the implied 5-year "
                "revenue growth rate the market is pricing in?"
            ),
        )
        assert result.canonical_ticker == "NVDA"

    def test_msft_hint_resolves_correctly(self):
        result = resolve_for_analysis(
            company_hint="MSFT",
            user_question=(
                "Which Microsoft segment has the widest moat — Productivity, "
                "Intelligent Cloud, or Personal Computing?"
            ),
        )
        assert result.canonical_ticker == "MSFT"

    # ── Fallback: empty company_hint still uses question text ─────────────

    def test_empty_hint_falls_back_to_question(self):
        """When company_hint is absent, question text is used as before."""
        result = resolve_for_analysis(
            company_hint="",
            user_question="What is the investment thesis for Nvidia?",
        )
        # Should still resolve NVDA from the question
        assert result.canonical_ticker == "NVDA", (
            f"Expected NVDA from question text when hint is empty, "
            f"got {result.canonical_ticker!r}"
        )

    def test_whitespace_only_hint_falls_back_to_question(self):
        """Whitespace-only company_hint behaves as absent."""
        result = resolve_for_analysis(
            company_hint="   ",
            user_question="Should I buy JPMorgan stock?",
        )
        assert result.canonical_ticker == "JPM"

    # ── Unresolvable hint falls back to question ──────────────────────────

    def test_unresolvable_hint_falls_back_to_question(self):
        """When company_hint does not resolve, question text is used."""
        result = resolve_for_analysis(
            company_hint="ZZZNOTTICKER",
            user_question="What is the investment thesis for Apple?",
        )
        # Should resolve AAPL from the question, not fail silently
        assert result.canonical_ticker == "AAPL", (
            f"Unresolvable hint should fall back to question-text resolution; "
            f"got {result.canonical_ticker!r}"
        )

    # ── Confidence must remain high ───────────────────────────────────────

    def test_resolution_confidence_with_explicit_hint(self):
        """Resolving via company_hint should carry high confidence."""
        result = resolve_for_analysis(company_hint="JPM", user_question="")
        assert result.canonical_ticker == "JPM"
        assert result.confidence_score >= 0.85, (
            f"Expected confidence >= 0.85 for explicit ticker hint, "
            f"got {result.confidence_score}"
        )


# ===========================================================================
# Fix B prerequisite — detect_company resolves pilot tickers correctly
# ===========================================================================

class TestDetectCompanyForRoutingFixB:
    """
    detect_company() is the resolution step that gates the Fix B routing branch.
    These tests confirm that all Stage 7A pilot companies resolve to a valid
    CompanyContext so _run_investment_pipeline can be invoked.
    """

    @pytest.mark.parametrize("ticker,expected_name_fragment", [
        ("NVDA", "nvidia"),
        ("COST", "costco"),
        ("MSFT", "microsoft"),
        ("TSM",  "taiwan"),
        ("JPM",  "jpmorgan"),
    ])
    def test_pilot_tickers_resolve(self, ticker: str, expected_name_fragment: str):
        ctx = detect_company(ticker)
        assert ctx is not None, (
            f"detect_company({ticker!r}) returned None — "
            "Fix B routing branch will not fire for this ticker."
        )
        assert ctx.ticker == ticker
        assert expected_name_fragment in ctx.company_name.lower(), (
            f"Unexpected company_name for {ticker}: {ctx.company_name!r}"
        )

    def test_detect_company_returns_company_context_fields(self):
        """CompanyContext from detect_company has all fields needed by pipeline."""
        ctx = detect_company("NVDA")
        assert ctx is not None
        assert ctx.ticker
        assert ctx.company_name
        # sector and industry may be None for some companies — that's acceptable


# ===========================================================================
# Fix B routing — verify investment pipeline is reached via route_question
# ===========================================================================

class TestRouteQuestionInvestmentPipelineFixB:
    """
    Verify that route_question routes explicit company_name + investment-intent
    questions into _run_investment_pipeline rather than the legacy keyword path.

    Uses mock to intercept _run_investment_pipeline so the test stays fast
    (no real LLM calls) while confirming the routing decision.
    """

    def _make_request(self, company_name: str, question: str, intent: str = "company_analysis"):
        from app.schemas import QuestionRequest
        return QuestionRequest(
            company_name=company_name,
            question=question,
            intent=intent,
        )

    def test_nvda_routes_to_investment_pipeline(self):
        """NVDA + valuation question must reach _run_investment_pipeline."""
        from app.services import router_service

        mock_response = MagicMock()
        mock_response.company = "NVDA"

        with patch.object(router_service, "_run_investment_pipeline",
                          return_value=mock_response) as mock_pipeline:
            request = self._make_request(
                company_name="NVDA",
                question=(
                    "At Nvidia's current price-to-earnings multiple, what is the implied "
                    "5-year forward revenue growth rate the market is pricing in?"
                ),
            )
            router_service.route_question(request)
            mock_pipeline.assert_called_once()
            call_kwargs = mock_pipeline.call_args
            assert call_kwargs[1]["question"] == request.question or \
                   call_kwargs[0][1] == request.question, (
                "question must be passed verbatim to _run_investment_pipeline"
            )

    def test_cost_routes_to_investment_pipeline(self):
        """COST + competitor-mentioning question must reach investment pipeline."""
        from app.services import router_service

        mock_response = MagicMock()

        with patch.object(router_service, "_run_investment_pipeline",
                          return_value=mock_response) as mock_pipeline:
            request = self._make_request(
                company_name="COST",
                question=(
                    "Costco trades at a 40-50x earnings premium versus Walmart at "
                    "25-30x and Target at 15-20x. What single metric would compress "
                    "the premium in the next 12 months?"
                ),
            )
            router_service.route_question(request)
            mock_pipeline.assert_called_once()

    def test_msft_routes_to_investment_pipeline(self):
        from app.services import router_service
        mock_response = MagicMock()

        with patch.object(router_service, "_run_investment_pipeline",
                          return_value=mock_response) as mock_pipeline:
            request = self._make_request(
                company_name="MSFT",
                question=(
                    "Which Microsoft segment has the widest economic moat — "
                    "Productivity, Intelligent Cloud, or Personal Computing?"
                ),
            )
            router_service.route_question(request)
            mock_pipeline.assert_called_once()

    def test_tsm_routes_to_investment_pipeline(self):
        from app.services import router_service
        mock_response = MagicMock()

        with patch.object(router_service, "_run_investment_pipeline",
                          return_value=mock_response) as mock_pipeline:
            request = self._make_request(
                company_name="TSM",
                question=(
                    "How does TSMC's manufacturing moat in N3 and N2 translate into "
                    "pricing power, and what is the ceiling given Intel and Samsung "
                    "alternatives?"
                ),
            )
            router_service.route_question(request)
            mock_pipeline.assert_called_once()

    def test_non_company_intent_not_rerouted(self):
        """market_question intent must NOT be routed to investment pipeline."""
        from app.services import router_service
        mock_response = MagicMock()

        with patch.object(router_service, "_run_investment_pipeline",
                          return_value=mock_response) as mock_pipeline:
            request = self._make_request(
                company_name="NVDA",
                question="Why are semiconductor stocks falling today?",
                intent="market_question",
            )
            # Should NOT route to investment pipeline — market_question is excluded
            try:
                router_service.route_question(request)
            except Exception:
                pass  # other parts of the pipeline may fail in test env
            mock_pipeline.assert_not_called()
