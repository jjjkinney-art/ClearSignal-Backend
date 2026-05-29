"""Tests for thesis_synthesizer JSON-enforcement and markdown recovery.

Verifies that:
- The synthesis prompt ends with "JSON:" and contains no markdown headings
- The LLM response is always parsed as JSON (never as prose)
- Markdown responses are recovered via _strip_markdown_to_json
- synthesize_thesis() returns a schema-valid InvestmentThesis on first attempt
- diagnostics are emitted ([DIAG] THESIS SYNTHESIS RAW / PARSED / VALIDATED)
"""
from __future__ import annotations

import json
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.schemas import (
    CompanyContext,
    CompanyKnowledgeProfile,
    InvestmentThesis,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RetrievedEvidence,
    RiskProfile,
    ValuationView,
)
from app.services.thesis_synthesizer import (
    _build_synthesis_prompt,
    _call_with_json_enforcement,
    _strip_markdown_to_json,
    synthesize_thesis,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _company(ticker: str = "AAPL", name: str = "Apple Inc.") -> CompanyContext:
    return CompanyContext(ticker=ticker, company_name=name, sector="Technology")


def _profile() -> CompanyKnowledgeProfile:
    return CompanyKnowledgeProfile(
        ticker="AAPL",
        company_name="Apple Inc.",
        business_model="Premium hardware and services ecosystem.",
        primary_revenue_drivers=["iPhone (~52%)", "Services (~25%)"],
        recurring_revenue_sources=["App Store", "iCloud"],
        rate_sensitivity_note="Premium multiple compresses ~15-20% per 100bps rate rise.",
        inflation_pass_through="Strong pricing power via premium brand.",
        recession_behavior="iPhone upgrades extend in recessions.",
        major_risks=["China revenue ~19%", "App Store regulation"],
        valuation_style="~28x P/E",
        key_metrics=["Services revenue growth", "iPhone ASP"],
        competitive_advantages=["Ecosystem lock-in", "1.2B installed base"],
        business_model_keywords=["iPhone", "Services", "App Store", "iCloud", "buyback", "China"],
    )


def _valuation() -> ValuationView:
    return ValuationView(
        summary="AAPL trades at ~28x P/E, justified by Services 72% gross margin.",
        overall="AAPL at 28x P/E with 95% FCF conversion.",
        confidence=0.75,
    )


def _macro() -> MacroSensitivity:
    return MacroSensitivity(
        overall="Rate rises compress AAPL's premium multiple; Services recurring revenue buffers impact.",
        confidence=0.70,
    )


def _risk() -> RiskProfile:
    return RiskProfile(
        overall="China revenue ~19% of total is the primary geopolitical risk.",
        key_risks=["China revenue concentration", "App Store regulation"],
        confidence=0.68,
    )


def _market() -> MarketContext:
    return MarketContext(
        overall="iPhone installed base 1.2B; Services flywheel accelerating.",
        recent_catalysts=["Services guidance raise", "India expansion"],
        confidence=0.72,
    )


def _quality() -> QualityAssessment:
    return QualityAssessment(
        overall="95% FCF conversion, AA- credit, $90B annual buyback.",
        confidence=0.80,
    )


def _evidence() -> List[RetrievedEvidence]:
    return [
        RetrievedEvidence(
            title="AAPL Q4 2024 Earnings",
            source="FMP",
            summary="Services revenue grew 12% YoY to $24.2B. iPhone revenue $44.7B.",
            timestamp="2024-11-01",
            relevance_score=0.9,
        ),
        RetrievedEvidence(
            title="10-Year Treasury Yield",
            source="FRED",
            summary="DGS10 at 4.35%, near cycle highs.",
            timestamp="2024-11-01",
            relevance_score=0.7,
        ),
    ]


def _valid_thesis_json(ticker: str = "AAPL") -> str:
    """Return a well-formed InvestmentThesis JSON string."""
    return json.dumps({
        "ticker": ticker,
        "company_name": "Apple Inc.",
        "bull_thesis": (
            f"{ticker}'s Services segment at 72% gross margin drives earnings quality. "
            f"The 28x P/E reflects the Services flywheel with App Store and iCloud recurring revenue. "
            f"iPhone installed base of 1.2B provides durable upgrade cycle revenue."
        ),
        "bear_thesis": (
            f"China revenue (~19% of {ticker} total) faces tariff and regulatory risk that could "
            f"remove $10B+ annually from revenue. A sustained 100bps rate rise compresses the "
            f"premium multiple by ~15-20% through the discount rate effect on Services cash flows."
        ),
        "key_drivers": [
            f"{ticker}-specific: Services gross margin expansion to 74%+ supports earnings",
            f"{ticker}-specific: iPhone ASP growth via Pro mix shift",
            f"{ticker}-specific: India manufacturing diversification reduces China supply risk",
            f"{ticker}-specific: App Store monetisation via higher developer fees",
        ],
        "key_risks": [
            f"China revenue ~19% of {ticker} total faces geopolitical escalation risk",
            "App Store regulation (EU DMA) could compress Services gross margin 200-400bps",
            "Rate-driven multiple compression: 100bps rise = ~15-20% P/E de-rating",
            "iPhone unit saturation in mature markets — upgrade cycle extending to 4+ years",
        ],
        "valuation_view": f"{ticker} at ~28x P/E is pricing in 12-15% Services growth. DCF implies $185-210 fair value.",
        "macro_sensitivity": (
            f"Rising rates compress {ticker}'s premium multiple through DCF discount rate. "
            f"Services recurring cash flows provide partial buffer vs pure growth stocks."
        ),
        "confidence_score": 0.72,
        "confidence_reasoning": (
            "Valuation (0.75), quality (0.80), market (0.72), macro (0.70), risk (0.68) "
            "— averaged with evidence depth weighting."
        ),
        "what_changes_the_thesis": [
            f"{ticker} Services gross margin drops below 70% for 2+ consecutive quarters",
            "China revenue ban or tariff exceeding 25% on AAPL hardware imports",
            "App Store antitrust ruling requiring structural separation of payments",
            "Fed funds rate above 6% compressing growth multiples market-wide",
        ],
        "conclusion": (
            f"{ticker} is a high-quality compounder with 95% FCF conversion and $90B annual buyback. "
            f"The Services segment at 72% gross margin is the primary earnings quality driver. "
            f"At 28x P/E the stock prices in 12-15% Services CAGR; China risk and rate sensitivity "
            f"are the key thesis-changers. Maintain overweight with $210 price target."
        ),
    })


# ---------------------------------------------------------------------------
# TestPromptStructure
# ---------------------------------------------------------------------------

class TestPromptStructure:
    """The synthesis prompt must be structured to elicit JSON, not markdown."""

    def test_prompt_ends_with_json_terminator(self):
        """Prompt must end with 'JSON:' to signal JSON-only output."""
        prompt = _build_synthesis_prompt(
            _company(), _valuation(), _macro(), _risk(), _market(), _quality(), _evidence()
        )
        assert prompt.strip().endswith("JSON:"), (
            f"Prompt does not end with 'JSON:'. Last 100 chars: {prompt.strip()[-100:]!r}"
        )

    def test_prompt_contains_json_only_rule(self):
        """Prompt must contain explicit 'Return ONLY valid JSON' instruction."""
        prompt = _build_synthesis_prompt(
            _company(), _valuation(), _macro(), _risk(), _market(), _quality(), _evidence()
        )
        assert "Return ONLY valid JSON" in prompt

    def test_prompt_contains_no_markdown_code_fence_instruction(self):
        """Prompt must tell the LLM NOT to use code fences."""
        prompt = _build_synthesis_prompt(
            _company(), _valuation(), _macro(), _risk(), _market(), _quality(), _evidence()
        )
        # The prompt should instruct against code fences
        lower = prompt.lower()
        assert "no markdown" in lower or "no code fence" in lower or "no ```" in lower

    def test_prompt_lists_all_required_fields(self):
        """Prompt must list all InvestmentThesis fields the LLM should populate."""
        prompt = _build_synthesis_prompt(
            _company(), _valuation(), _macro(), _risk(), _market(), _quality(), _evidence()
        )
        required = [
            "bull_thesis", "bear_thesis", "key_drivers", "key_risks",
            "valuation_view", "macro_sensitivity", "confidence_score",
            "confidence_reasoning", "what_changes_the_thesis", "conclusion",
        ]
        for field in required:
            assert field in prompt, f"Field '{field}' not listed in synthesis prompt"

    def test_agent_summaries_use_plain_text_not_markdown_headings(self):
        """Agent summary blocks in the prompt must NOT use ### headings."""
        from app.services.thesis_synthesizer import _agent_block
        block = _agent_block("Valuation", "AAPL at 28x P/E.", 0.75)
        assert "###" not in block, f"_agent_block uses markdown heading: {block!r}"
        assert "#" not in block or block.index("#") > 10  # # allowed inside sentences

    def test_prompt_contains_critical_output_rules(self):
        """Prompt must include 'CRITICAL OUTPUT RULES' section."""
        prompt = _build_synthesis_prompt(
            _company(), _valuation(), _macro(), _risk(), _market(), _quality(), _evidence()
        )
        assert "CRITICAL OUTPUT RULES" in prompt

    def test_prompt_forbids_markdown_headings_in_output(self):
        """Prompt must explicitly forbid writing Investment Thesis headings."""
        prompt = _build_synthesis_prompt(
            _company(), _valuation(), _macro(), _risk(), _market(), _quality(), _evidence()
        )
        # Should have something like "Do NOT write any markdown headings"
        lower = prompt.lower()
        assert "do not write" in lower or "do not use" in lower

    def test_prompt_with_profile_includes_company_keywords(self):
        """When profile is given, prompt includes required business_model_keywords."""
        prompt = _build_synthesis_prompt(
            _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
            _evidence(), profile=_profile()
        )
        assert "iPhone" in prompt
        assert "Services" in prompt

    def test_response_must_start_with_brace_rule(self):
        """Prompt must say the response must start with {."""
        prompt = _build_synthesis_prompt(
            _company(), _valuation(), _macro(), _risk(), _market(), _quality(), _evidence()
        )
        assert "{" in prompt and "start with" in prompt.lower()


# ---------------------------------------------------------------------------
# TestMarkdownStripping
# ---------------------------------------------------------------------------

class TestMarkdownStripping:
    """_strip_markdown_to_json recovers JSON from markdown-prose responses."""

    def test_returns_none_for_clean_json(self):
        """Clean JSON string returns None — caller handles it normally."""
        clean = '{"ticker": "AAPL", "bull_thesis": "Services drives margin."}'
        result = _strip_markdown_to_json(clean)
        assert result is None

    def test_recovers_json_from_markdown_heading_response(self):
        """Extracts JSON object embedded in a markdown-heading response."""
        markdown_response = (
            "### Investment Thesis for Apple Inc.\n"
            "#### Bull Case\n"
            "Apple's Services segment is growing.\n\n"
            '{"ticker": "AAPL", "bull_thesis": "Services at 72% margin.", '
            '"bear_thesis": "China risk.", "confidence_score": 0.7}\n'
        )
        result = _strip_markdown_to_json(markdown_response)
        assert result is not None
        data = json.loads(result)
        assert data["ticker"] == "AAPL"

    def test_recovers_json_from_fenced_code_block(self):
        """Extracts JSON from a ```json ... ``` fenced code block."""
        fenced = (
            "Here is the investment thesis:\n\n"
            "```json\n"
            '{"ticker": "AAPL", "bull_thesis": "Services 72% margin.", "confidence_score": 0.75}\n'
            "```\n"
        )
        # _strip_markdown_to_json requires a heading to trigger; add one
        fenced_with_heading = "### Analysis\n" + fenced
        result = _strip_markdown_to_json(fenced_with_heading)
        assert result is not None
        data = json.loads(result)
        assert data["ticker"] == "AAPL"

    def test_returns_none_when_no_json_recoverable(self):
        """Returns None when no JSON object can be extracted from markdown."""
        pure_prose = (
            "### Investment Thesis\n"
            "#### Bull Case\n"
            "Apple is a great company with strong fundamentals.\n"
            "#### Bear Case\n"
            "China risk is the main concern.\n"
        )
        result = _strip_markdown_to_json(pure_prose)
        # No valid JSON object → should return None
        assert result is None or (result is not None and not result.strip().startswith("{"))


# ---------------------------------------------------------------------------
# TestCallWithJsonEnforcement
# ---------------------------------------------------------------------------

class TestCallWithJsonEnforcement:
    """_call_with_json_enforcement parses valid JSON on first attempt."""

    def test_returns_thesis_on_clean_json_response(self, capsys):
        """Returns a valid InvestmentThesis when model returns clean JSON."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = _call_with_json_enforcement(
                prompt="test prompt",
                ticker="AAPL",
                max_retries=3,
                backoff_factor=0.0,
            )
        assert result is not None
        assert isinstance(result, InvestmentThesis)
        assert result.ticker == "AAPL"
        assert result.confidence_score == 0.72

    def test_emits_raw_diagnostic(self, capsys):
        """[DIAG] THESIS SYNTHESIS RAW is printed."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            _call_with_json_enforcement(
                prompt="test prompt", ticker="AAPL",
                max_retries=3, backoff_factor=0.0,
            )
        captured = capsys.readouterr()
        assert "[DIAG] THESIS SYNTHESIS RAW" in captured.out

    def test_emits_parsed_diagnostic(self, capsys):
        """[DIAG] THESIS SYNTHESIS PARSED is printed."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            _call_with_json_enforcement(
                prompt="test prompt", ticker="AAPL",
                max_retries=3, backoff_factor=0.0,
            )
        captured = capsys.readouterr()
        assert "[DIAG] THESIS SYNTHESIS PARSED" in captured.out

    def test_emits_validated_diagnostic(self, capsys):
        """[DIAG] THESIS SYNTHESIS VALIDATED is printed on success."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            _call_with_json_enforcement(
                prompt="test prompt", ticker="AAPL",
                max_retries=3, backoff_factor=0.0,
            )
        captured = capsys.readouterr()
        assert "[DIAG] THESIS SYNTHESIS VALIDATED" in captured.out

    def test_recovers_from_markdown_response(self, capsys):
        """Returns a valid thesis when model returns markdown with embedded JSON."""
        markdown_with_json = (
            "### Investment Thesis for Apple Inc.\n\n"
            "#### Analysis\n"
            "Here is the structured output:\n\n"
            + _valid_thesis_json("AAPL")
            + "\n"
        )
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = markdown_with_json
            result = _call_with_json_enforcement(
                prompt="test prompt", ticker="AAPL",
                max_retries=3, backoff_factor=0.0,
            )
        assert result is not None
        assert result.ticker == "AAPL"
        captured = capsys.readouterr()
        assert "MARKDOWN DETECTED" in captured.out

    def test_returns_none_after_all_retries_fail(self):
        """Returns None when model consistently returns unparseable output."""
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = "### Bull Case\nApple is great.\n### Bear Case\nChina risk.\n"
            result = _call_with_json_enforcement(
                prompt="test prompt", ticker="AAPL",
                max_retries=2, backoff_factor=0.0,
            )
        # Pure markdown prose with no JSON object should return None
        assert result is None

    def test_bull_thesis_present_in_parsed_result(self):
        """Parsed result has non-empty bull_thesis."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = _call_with_json_enforcement(
                prompt="test prompt", ticker="AAPL",
                max_retries=3, backoff_factor=0.0,
            )
        assert result is not None
        assert len(result.bull_thesis) > 20

    def test_no_markdown_headings_in_parsed_fields(self):
        """Parsed thesis fields contain no markdown heading characters."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = _call_with_json_enforcement(
                prompt="test prompt", ticker="AAPL",
                max_retries=3, backoff_factor=0.0,
            )
        assert result is not None
        # None of the text fields should START with a markdown heading
        for field in ("bull_thesis", "bear_thesis", "conclusion", "valuation_view"):
            value = getattr(result, field, "")
            assert not value.startswith("#"), (
                f"Field '{field}' starts with '#': {value[:80]!r}"
            )


# ---------------------------------------------------------------------------
# TestSynthesizeThesis
# ---------------------------------------------------------------------------

class TestSynthesizeThesis:
    """synthesize_thesis() integration — uses mocked model client."""

    def test_returns_investment_thesis_type(self):
        """Return type is always InvestmentThesis."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                _evidence(), profile=_profile(),
            )
        assert isinstance(result, InvestmentThesis)

    def test_thesis_ticker_matches_company(self):
        """thesis.ticker is stamped to match the company's ticker."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                _evidence(),
            )
        assert result.ticker == "AAPL"

    def test_evidence_count_stamped(self):
        """evidence_count is set to the number of evidence items passed in."""
        valid_json = _valid_thesis_json("AAPL")
        ev = _evidence()
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                ev,
            )
        assert result.evidence_count == len(ev)

    def test_generated_at_is_set(self):
        """generated_at is a non-empty ISO timestamp."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                _evidence(),
            )
        assert result.generated_at != ""
        assert "T" in result.generated_at  # ISO format contains T

    def test_no_markdown_headings_in_bull_thesis(self):
        """bull_thesis field contains no markdown heading markers."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                _evidence(),
            )
        assert "###" not in result.bull_thesis
        assert result.bull_thesis[:1] != "#"

    def test_consistency_warnings_is_list(self):
        """consistency_warnings is always a list (may be empty)."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                _evidence(),
            )
        assert isinstance(result.consistency_warnings, list)

    def test_empty_thesis_returned_when_all_agents_zero_and_no_evidence(self):
        """Returns graceful empty thesis when all agents have 0 confidence + no evidence.

        Guard behaviour (post-fix): for a known ticker (AAPL), the synthesiser
        now attempts the LLM call even with empty agents/evidence so the model
        can draw on training knowledge.  When that call fails (here: mock
        returns None), synthesize_thesis falls back to an empty thesis rather
        than propagating the error.
        """
        empty_val = ValuationView(overall="", confidence=0.0)
        empty_mac = MacroSensitivity(overall="", confidence=0.0)
        empty_risk = RiskProfile(overall="", confidence=0.0)
        empty_mkt = MarketContext(overall="", confidence=0.0)
        empty_qual = QualityAssessment(overall="", confidence=0.0)

        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = None  # simulate LLM failure / no key
            result = synthesize_thesis(
                _company(), empty_val, empty_mac, empty_risk, empty_mkt, empty_qual,
                evidence=[],
            )

        # LLM was attempted (guard no longer bails immediately for known tickers)
        mock_client.call.assert_called()
        assert result.confidence_score == 0.0
        assert "insufficient" in result.bull_thesis.lower()

    def test_markdown_response_recovered_successfully(self):
        """synthesize_thesis recovers and returns thesis even when model emits markdown."""
        markdown_response = (
            "### Investment Thesis for Apple Inc.\n\n"
            "Here is my analysis:\n\n"
            + _valid_thesis_json("AAPL")
        )
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = markdown_response
            result = synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                _evidence(),
            )
        assert isinstance(result, InvestmentThesis)
        assert result.ticker == "AAPL"
        assert result.confidence_score > 0.0

    def test_model_called_once_on_clean_json(self):
        """Model is called exactly once when JSON is valid on first attempt."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                _evidence(),
            )
        mock_client.call.assert_called_once()

    def test_key_drivers_is_list(self):
        """key_drivers is always a list."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                _evidence(),
            )
        assert isinstance(result.key_drivers, list)

    def test_key_risks_is_list(self):
        """key_risks is always a list."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                _evidence(),
            )
        assert isinstance(result.key_risks, list)

    def test_what_changes_the_thesis_is_list(self):
        """what_changes_the_thesis is always a list."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                _evidence(),
            )
        assert isinstance(result.what_changes_the_thesis, list)

    def test_confidence_score_in_valid_range(self):
        """confidence_score is between 0.0 and 1.0."""
        valid_json = _valid_thesis_json("AAPL")
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = valid_json
            result = synthesize_thesis(
                _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                _evidence(),
            )
        assert 0.0 <= result.confidence_score <= 1.0

    def test_graceful_fallback_on_persistent_parse_failure(self):
        """Returns empty thesis gracefully if model always fails to produce JSON."""
        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = (
                "### Bull Thesis\nApple is great.\n### Bear Thesis\nChina risk.\n"
            )
            with patch("app.services.thesis_synthesizer.settings") as mock_settings:
                mock_settings.model_max_retries = 1
                mock_settings.model_backoff_factor = 0.0
                result = synthesize_thesis(
                    _company(), _valuation(), _macro(), _risk(), _market(), _quality(),
                    _evidence(),
                )
        assert isinstance(result, InvestmentThesis)
        assert result.ticker == "AAPL"
        # Should be the empty/fallback thesis
        assert result.confidence_score == 0.0
