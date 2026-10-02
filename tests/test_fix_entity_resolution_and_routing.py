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
from app.services.entity_resolution_service import resolve_for_analysis, resolve_query
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


class TestEntityIdentityMetadata:
    """Resolution retains how the requested entity relates to the SEC issuer."""

    @pytest.mark.parametrize("query,expected_ticker,expected_relation", [
        ("Instagram growth", "META", "subsidiary"),
        ("What happened to FB?", "META", "former_ticker"),
        ("Royal Dutch Shell earnings", "SHEL", "former_name"),
        ("AWS operating margin", "AMZN", "business_unit"),
    ])
    def test_alias_relationship_is_explicit(
        self, query: str, expected_ticker: str, expected_relation: str,
    ):
        result = resolve_query(query)

        assert result.canonical_ticker == expected_ticker
        assert result.identity_relation == expected_relation
        assert result.requested_entity

    @pytest.mark.parametrize("ticker", ["BRK.A", "BRK.B", "BF.B", "GOOG", "GOOGL"])
    def test_share_class_ticker_remains_distinct(self, ticker: str):
        result = resolve_query(ticker)

        assert result.canonical_ticker == ticker
        assert result.identity_relation == "share_class"

    def test_canonical_issuer_is_not_mislabeled_as_alias(self):
        result = resolve_query("META")

        assert result.canonical_ticker == "META"
        assert result.identity_relation == "canonical_issuer"

    @pytest.mark.parametrize("query,parent,effective_from,historical_ticker", [
        ("LinkedIn revenue", "MSFT", "2016-12-08", "LNKD"),
        ("Whole Foods margins", "AMZN", "2017-08-28", "WFM"),
        ("GitHub growth", "MSFT", "2018-10-26", ""),
        ("Activision Blizzard bookings", "MSFT", "2023-10-13", "ATVI"),
        ("YouTube advertising revenue", "GOOGL", "2006-11-13", ""),
    ])
    def test_current_acquisition_alias_retains_temporal_identity(
        self, query: str, parent: str, effective_from: str, historical_ticker: str,
    ):
        result = resolve_query(query)

        assert result.canonical_ticker == parent
        assert result.identity_relation == "acquired_subsidiary"
        assert result.relationship_status == "current"
        assert result.relationship_effective_from == effective_from
        assert result.historical_ticker == historical_ticker

    def test_pre_acquisition_date_fails_closed(self):
        result = resolve_query("LinkedIn revenue", as_of="2015-12-31")

        assert result.canonical_ticker == ""
        assert result.needs_clarification is True
        assert result.resolution_method == "temporal_identity_mismatch"
        assert result.relationship_status == "not_yet_owned"
        assert result.historical_ticker == "LNKD"
        assert "not owned by Microsoft" in result.ambiguity_reason

    def test_acquisition_close_date_resolves_to_parent(self):
        result = resolve_query("LinkedIn revenue", as_of="2016-12-08")

        assert result.canonical_ticker == "MSFT"
        assert result.needs_clarification is False
        assert result.identity_as_of == "2016-12-08"

    def test_company_hint_obeys_temporal_guard(self):
        result = resolve_query(
            "How fast was it growing?",
            company_hint="Whole Foods",
            as_of="2016-12-31",
        )

        assert result.canonical_ticker == ""
        assert result.needs_clarification is True
        assert result.historical_ticker == "WFM"

    @pytest.mark.parametrize("query,ticker,from_date,predecessor", [
        ("PayPal revenue", "PYPL", "2015-07-17", "EBAY"),
        ("Kyndryl revenue", "KD", "2021-11-03", "IBM"),
        ("GE HealthCare revenue", "GEHC", "2023-01-04", "GE"),
        ("GE Vernova revenue", "GEV", "2024-04-02", "GE"),
    ])
    def test_current_spin_off_identity_retains_predecessor(
        self, query: str, ticker: str, from_date: str, predecessor: str,
    ):
        result = resolve_query(query)

        assert result.canonical_ticker == ticker
        assert result.identity_relation == "separated_company"
        assert result.relationship_event == "spin_off"
        assert result.relationship_effective_from == from_date
        assert result.predecessor_ticker == predecessor

    def test_pre_spin_off_date_fails_closed_to_predecessor_choice(self):
        result = resolve_query("PayPal revenue", as_of="2014-12-31")

        assert result.canonical_ticker == ""
        assert result.needs_clarification is True
        assert result.relationship_status == "pre_separation"
        assert result.predecessor_ticker == "EBAY"
        assert "not yet a separate public issuer" in result.ambiguity_reason

    def test_spin_off_effective_date_resolves_standalone_company(self):
        result = resolve_query("GE Vernova revenue", as_of="2024-04-02")

        assert result.canonical_ticker == "GEV"
        assert result.needs_clarification is False
        assert result.identity_as_of == "2024-04-02"

    def test_same_issuer_former_ticker_remains_safe_historically(self):
        historical = resolve_query("FB earnings", as_of="2021-12-31")
        current = resolve_query("FB earnings", as_of="2024-12-31")

        assert historical.canonical_ticker == current.canonical_ticker == "META"
        assert historical.relationship_status == "historical_alias_active"
        assert current.relationship_status == "former_alias"
        assert historical.relationship_effective_to == "2022-06-08"
        assert historical.relationship_event == "ticker_change"

    @pytest.mark.parametrize("query,ticker,effective,predecessors,event", [
        (
            "Warner Bros Discovery revenue", "WBD", "2022-04-08",
            ("T", "DISCA"), "divestiture_merger",
        ),
        (
            "WarnerMedia revenue", "WBD", "2022-04-08",
            ("T",), "divestiture_merger",
        ),
        (
            "Viatris revenue", "VTRS", "2020-11-16",
            ("MYL", "PFE"), "merger_successor",
        ),
        (
            "Mylan revenue", "VTRS", "2020-11-16",
            ("MYL",), "merger_successor",
        ),
    ])
    def test_current_merger_successor_retains_predecessor_chain(
        self, query: str, ticker: str, effective: str,
        predecessors: tuple[str, ...], event: str,
    ):
        result = resolve_query(query)

        assert result.canonical_ticker == ticker
        assert result.identity_relation == "merger_successor"
        assert result.relationship_effective_from == effective
        assert result.predecessor_tickers == predecessors
        assert result.relationship_event == event

    def test_pre_merger_successor_date_requires_predecessor_choice(self):
        result = resolve_query("Viatris revenue", as_of="2019-12-31")

        assert result.canonical_ticker == ""
        assert result.needs_clarification is True
        assert result.relationship_status == "pre_merger"
        assert result.predecessor_tickers == ("MYL", "PFE")
        assert "MYL, PFE" in result.clarification_prompt

    def test_pre_divestiture_merger_does_not_route_to_successor(self):
        result = resolve_query("WarnerMedia revenue", as_of="2021-12-31")

        assert result.canonical_ticker == ""
        assert result.needs_clarification is True
        assert result.predecessor_tickers == ("T",)
        assert result.relationship_event == "divestiture_merger"

    def test_merger_close_date_resolves_successor(self):
        result = resolve_query("Viatris revenue", as_of="2020-11-16")

        assert result.canonical_ticker == "VTRS"
        assert result.needs_clarification is False
        assert result.identity_as_of == "2020-11-16"

    def test_analysis_wrapper_propagates_as_of_boundary(self):
        result = resolve_for_analysis(
            company_hint="Viatris",
            user_question="How was revenue trending?",
            as_of="2019-12-31T23:59:59Z",
        )

        assert result.canonical_ticker == ""
        assert result.needs_clarification is True
        assert result.relationship_status == "pre_merger"

    def test_generic_ambiguous_hint_still_defers_to_context_rich_question(self):
        result = resolve_for_analysis(
            company_hint="AI",
            user_question="Can Meta continue despite AI infrastructure spending?",
        )

        assert result.canonical_ticker == "META"
        assert result.needs_clarification is False

    def test_analysis_request_accepts_explicit_as_of_boundary(self):
        from app.schemas import AnalysisRequest

        request = AnalysisRequest(
            company_name="LinkedIn",
            user_question="How fast was revenue growing?",
            as_of="2015-12-31T23:59:59Z",
        )

        assert request.as_of == "2015-12-31T23:59:59Z"


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

    @pytest.mark.parametrize(
        "question",
        [
            "What is Tesla doing to set itself up to do well in 2030 and beyond?",
            "What advantages does Tesla have over rivals in the U.S. and China?",
        ],
    )
    def test_explicit_company_analysis_routes_natural_research_questions(self, question):
        """Structured company scope must not depend on legacy keyword matching."""
        from app.services import router_service

        assert not router_service._has_investment_intent(question)
        mock_response = MagicMock()

        with patch.object(
            router_service,
            "_run_investment_pipeline",
            return_value=mock_response,
        ) as mock_pipeline:
            request = self._make_request(
                company_name="TSLA",
                question=question,
                intent="company_analysis",
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
