"""
Tests for question-anchored direct_answer in the investment thesis synthesiser.

No real LLM or network calls are made — model_client.call is mocked throughout.
All assertions are deterministic.

Coverage:
  1. InvestmentThesis schema has direct_answer field with correct default.
  2. _build_synthesis_prompt embeds the question and QUESTION-ANCHORED block
     when original_user_question is supplied.
  3. _build_synthesis_prompt omits the block when question is None.
  4. synthesize_thesis passes original_user_question into the prompt.
  5. synthesize_thesis maps LLM-returned direct_answer onto the thesis object.
  6. Apple + interest-rate response validation (content rules, no generic opener).
  7. direct_answer is empty string in the degenerate empty-thesis path.
"""

from __future__ import annotations

import json
import re
import pytest
from unittest.mock import patch, MagicMock

from app.services.thesis_synthesizer import (
    synthesize_thesis,
    _build_synthesis_prompt,
)
from app.schemas import (
    CompanyContext,
    ValuationView,
    MacroSensitivity,
    RiskProfile,
    MarketContext,
    QualityAssessment,
    InvestmentThesis,
    RetrievedEvidence,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

APPLE_RATES_QUESTION = "How would higher interest rates affect Apple stock?"

_RATE_TERMS = re.compile(
    r"\b(rate|rates|interest rate|valuation|multiple|P/E|discount|compress|compression)\b",
    re.IGNORECASE,
)
_APPLE_OFFSETS = re.compile(
    r"\b(Services|buyback|cash|installed base|iPhone|revenue|margin|net.cash)\b",
    re.IGNORECASE,
)
_GENERIC_OPENER = re.compile(
    r"^(Apple (Inc\.)? is (a|an)|Apple is (a|an)|As a technology|"
    r"Apple, (a|an)|Apple Inc\., (a|an))",
    re.IGNORECASE,
)


def _company(ticker="AAPL", name="Apple Inc.", sector="Technology"):
    return CompanyContext(ticker=ticker, company_name=name, sector=sector)


def _full_agents():
    valuation = ValuationView(
        overall="AAPL trades at ~28x forward P/E, a premium to peers. "
                "Higher rates compress this multiple directly.",
        confidence=0.80,
    )
    macro = MacroSensitivity(
        overall="Rising rates increase the discount rate applied to Apple's "
                "long-duration cash flows, pressuring its premium valuation.",
        confidence=0.75,
    )
    risk = RiskProfile(
        overall="Key risks: valuation multiple compression, China revenue, regulation.",
        confidence=0.70,
        key_risks=["Multiple compression", "China risk", "Regulation", "FX headwind"],
    )
    market = MarketContext(
        overall="Services revenue provides recurring income resilient to rate cycles.",
        confidence=0.65,
        recent_catalysts=["Vision Pro launch", "AI integration", "Buyback $90B"],
    )
    quality = QualityAssessment(
        overall="Apple's net-cash balance sheet and $90B+ buyback programme buffer "
                "against rate headwinds better than leveraged peers.",
        confidence=0.85,
    )
    return valuation, macro, risk, market, quality


def _evidence():
    return [
        RetrievedEvidence(
            title="Apple Q3 Income Statement",
            source="FMP",
            summary="Services revenue $24B, gross margin 46%.",
            timestamp="2024-08-01",
            relevance_score=0.92,
        ),
        RetrievedEvidence(
            title="Fed Funds Rate Decision",
            source="FRED",
            summary="Rates held at 5.25-5.5%. Higher-for-longer signalled.",
            timestamp="2024-09-18",
            relevance_score=0.88,
        ),
    ]


_GOOD_DIRECT_ANSWER = (
    "Higher interest rates would pressure Apple's stock primarily through "
    "valuation multiple compression, as AAPL's ~28x P/E is particularly "
    "sensitive to discount-rate increases on its long-duration cash flows. "
    "The offset is Apple's $90B+ annual buyback programme and net-cash "
    "balance sheet, which provide more resilience than leveraged growth peers."
)

_SENTINEL = object()  # distinguish "not passed" from empty string


def _thesis_json(direct_answer=_SENTINEL) -> str:
    """Return a minimal valid InvestmentThesis JSON for mocking.

    Pass direct_answer="" to produce a thesis with an empty direct_answer field.
    Omit the argument to get the default rate-anchored answer.
    """
    da = _GOOD_DIRECT_ANSWER if direct_answer is _SENTINEL else direct_answer
    data = {
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "direct_answer": da,
        "bull_thesis": (
            "Apple's Services segment — $96B annualised revenue at ~70% gross margin — "
            "provides rate-resilient recurring income. The installed base of 2.2B devices "
            "and ongoing buybacks support earnings-per-share growth even if the multiple compresses."
        ),
        "bear_thesis": (
            "A sustained higher-rate environment compresses AAPL's premium multiple "
            "from ~28x toward the market average (~20x), implying meaningful downside "
            "even without an earnings deterioration. China revenue (~19% of sales) adds "
            "an independent geopolitical risk."
        ),
        "key_drivers": [
            "AAPL-specific: Services segment recurring revenue at ~70% gross margin",
            "AAPL-specific: $90B+ annual buyback programme reduces share count ~3% per year",
            "AAPL-specific: Net-cash balance sheet buffers against rate-driven cost pressure",
            "AAPL-specific: iPhone upgrade cycle drives hardware revenue floor",
        ],
        "key_risks": [
            "Valuation multiple compression from 28x to ~20x in sustained rate environment",
            "China revenue (~19% of sales) exposed to geopolitical risk",
            "Regulatory pressure on App Store economics (Services margin risk)",
            "FX headwind on international revenue from strong USD",
        ],
        "valuation_view": (
            "AAPL trades at ~28-30x forward P/E vs. S&P 500 at ~20x. "
            "Each 100bps rate rise historically compresses this premium by 15-20%."
        ),
        "macro_sensitivity": (
            "Higher rates raise the discount rate on Apple's long-duration Services cash flows, "
            "directly compressing the P/E multiple. Apple's net-cash position partially offsets "
            "this by reducing refinancing risk versus leveraged peers."
        ),
        "confidence_score": 0.72,
        "confidence_reasoning": (
            "Strong evidence base with FMP financials and FRED rate data. "
            "Agent confidence average ~0.75. Penalised slightly for China uncertainty."
        ),
        "what_changes_the_thesis": [
            "Fed pivot to rate cuts would re-expand AAPL's multiple — bullish catalyst",
            "Services revenue deceleration below 10% YoY would remove key bull driver",
            "App Store regulatory loss materially cutting Services gross margin",
            "China ban or revenue loss >25% would alter EPS trajectory",
        ],
        "conclusion": (
            "Apple's premium 28-30x P/E makes it rate-sensitive through multiple compression, "
            "but its $90B+ buyback programme, net-cash balance sheet, and $96B annualised "
            "Services revenue make it more resilient than leveraged growth peers. "
            "The risk/reward for long-term holders remains attractive with a >5-year horizon, "
            "though near-term multiple compression is the primary headwind in a higher-for-longer "
            "rate environment."
        ),
    }
    return json.dumps(data)


# ── 1. Schema tests ───────────────────────────────────────────────────────────

class TestInvestmentThesisSchema:
    """direct_answer exists on InvestmentThesis with a default of ''."""

    def test_direct_answer_field_exists_with_empty_default(self):
        thesis = InvestmentThesis(ticker="AAPL", company_name="Apple Inc.")
        assert hasattr(thesis, "direct_answer")
        assert thesis.direct_answer == ""

    def test_direct_answer_field_accepts_string(self):
        thesis = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            direct_answer="Higher rates compress AAPL's multiple.",
        )
        assert thesis.direct_answer == "Higher rates compress AAPL's multiple."

    def test_direct_answer_serialises_in_model_dump(self):
        thesis = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            direct_answer="Test direct answer.",
        )
        try:
            d = thesis.model_dump()
        except AttributeError:
            d = thesis.dict()
        assert "direct_answer" in d
        assert d["direct_answer"] == "Test direct answer."


# ── 2. Prompt injection tests ─────────────────────────────────────────────────

class TestPromptQuestionAnchor:
    """_build_synthesis_prompt injects / omits question-anchor block correctly."""

    def _build(self, question=None):
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        evidence = _evidence()
        return _build_synthesis_prompt(
            company, valuation, macro, risk, market, quality, evidence,
            original_user_question=question,
        )

    def test_prompt_contains_question_when_supplied(self):
        prompt = self._build(question=APPLE_RATES_QUESTION)
        assert APPLE_RATES_QUESTION in prompt

    def test_prompt_contains_question_anchor_header(self):
        prompt = self._build(question=APPLE_RATES_QUESTION)
        assert "USER'S EXACT QUESTION" in prompt

    def test_prompt_contains_direct_answer_task_item(self):
        prompt = self._build(question=APPLE_RATES_QUESTION)
        assert "direct_answer" in prompt

    def test_prompt_contains_forbidden_opener_rule(self):
        prompt = self._build(question=APPLE_RATES_QUESTION)
        assert "FORBIDDEN" in prompt
        assert "generic company" in prompt.lower() or "generic company description" in prompt.lower()

    def test_prompt_omits_question_anchor_when_no_question(self):
        prompt = self._build(question=None)
        assert "USER'S EXACT QUESTION" not in prompt
        assert APPLE_RATES_QUESTION not in prompt

    def test_prompt_still_contains_direct_answer_in_schema_description(self):
        """direct_answer field must appear in schema description even without a question."""
        prompt = self._build(question=None)
        assert "direct_answer" in prompt


# ── 3. Synthesis pass-through tests ──────────────────────────────────────────

class TestSynthesisDirectAnswer:
    """synthesize_thesis maps LLM direct_answer into the returned object."""

    def test_direct_answer_mapped_from_llm_response(self, monkeypatch):
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        evidence = _evidence()

        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = _thesis_json()
            result = synthesize_thesis(
                company, valuation, macro, risk, market, quality, evidence,
                original_user_question=APPLE_RATES_QUESTION,
            )

        assert isinstance(result, InvestmentThesis)
        assert result.direct_answer != ""
        # Must mention rate/valuation mechanism
        assert _RATE_TERMS.search(result.direct_answer), (
            f"direct_answer missing rate/valuation terms: {result.direct_answer!r}"
        )

    def test_question_is_embedded_in_prompt_sent_to_llm(self, monkeypatch):
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        evidence = _evidence()

        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = _thesis_json()
            synthesize_thesis(
                company, valuation, macro, risk, market, quality, evidence,
                original_user_question=APPLE_RATES_QUESTION,
            )

        # The original synthesis prompt (first LLM call) must embed the user's question.
        # A compound-risk retry may add a second call with a different prompt; use
        # call_args_list[0] to assert against the primary synthesis call.
        first_call = mock_client.call.call_args_list[0]
        prompt_sent = first_call[0][0] if first_call[0] else first_call[1].get("prompt", "")
        assert APPLE_RATES_QUESTION in prompt_sent

    def test_no_question_produces_empty_direct_answer_from_mock(self, monkeypatch):
        """When no question is passed and LLM returns no direct_answer, field is ''."""
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        evidence = _evidence()

        bare_thesis = _thesis_json(direct_answer="")

        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = bare_thesis
            result = synthesize_thesis(
                company, valuation, macro, risk, market, quality, evidence,
                original_user_question=None,
            )

        assert result.direct_answer == ""


# ── 4. Content validation tests (Apple + rates) ───────────────────────────────

class TestAppleRatesContentRules:
    """Validate that a well-formed direct_answer for Apple+rates passes all content rules.

    These tests do NOT invoke the LLM — they validate the content rules
    directly against the mock thesis that a correctly-prompted LLM should produce.
    """

    GOOD_DIRECT_ANSWER = _GOOD_DIRECT_ANSWER

    BAD_DIRECT_ANSWER_GENERIC = (
        "Apple Inc. is a leading technology company that designs and manufactures "
        "consumer electronics. The company faces various headwinds as a growth stock."
    )

    BAD_DIRECT_ANSWER_WRONG_TOPIC = (
        "Apple's Services segment generated $24B in Q3, driving gross margin expansion. "
        "The company has a strong competitive moat in consumer electronics."
    )

    def test_good_answer_mentions_rate_impact(self):
        assert _RATE_TERMS.search(self.GOOD_DIRECT_ANSWER), (
            "Good direct_answer must mention rate/valuation terms"
        )

    def test_good_answer_mentions_apple_specific_offset(self):
        assert _APPLE_OFFSETS.search(self.GOOD_DIRECT_ANSWER), (
            "Good direct_answer must mention an Apple-specific offset"
        )

    def test_good_answer_does_not_open_generically(self):
        assert not _GENERIC_OPENER.match(self.GOOD_DIRECT_ANSWER), (
            "Good direct_answer must not open with a generic company description"
        )

    def test_bad_generic_opener_detected(self):
        """Confirm the generic-opener detector fires on a bad answer."""
        assert _GENERIC_OPENER.match(self.BAD_DIRECT_ANSWER_GENERIC), (
            "Generic opener detector should flag this bad answer"
        )

    def test_bad_wrong_topic_missing_rate_terms(self):
        """An answer that ignores the rate question fails the rate-terms check."""
        assert not _RATE_TERMS.search(self.BAD_DIRECT_ANSWER_WRONG_TOPIC), (
            "Wrong-topic answer should fail the rate-terms check"
        )

    def test_synthesized_direct_answer_passes_all_rules(self, monkeypatch):
        """End-to-end: synthesizer produces a direct_answer that passes all content rules."""
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        evidence = _evidence()

        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = _thesis_json()
            result = synthesize_thesis(
                company, valuation, macro, risk, market, quality, evidence,
                original_user_question=APPLE_RATES_QUESTION,
            )

        da = result.direct_answer

        assert da, "direct_answer must be non-empty"

        assert _RATE_TERMS.search(da), (
            f"direct_answer must mention rate/valuation mechanism — got: {da!r}"
        )

        assert _APPLE_OFFSETS.search(da), (
            f"direct_answer must mention at least one Apple-specific offset — got: {da!r}"
        )

        assert not _GENERIC_OPENER.match(da), (
            f"direct_answer must not open with a generic company description — got: {da!r}"
        )


# ── 5. Degenerate path ────────────────────────────────────────────────────────

class TestEmptyThesisDirectAnswer:
    """Empty thesis (all-zero agents + no evidence) sets direct_answer to ''."""

    def test_empty_thesis_direct_answer_is_empty_string(self):
        company = _company()
        val = ValuationView()
        mac = MacroSensitivity()
        risk = RiskProfile()
        market = MarketContext()
        quality = QualityAssessment()

        result = synthesize_thesis(
            company, val, mac, risk, market, quality, [],
            original_user_question=APPLE_RATES_QUESTION,
        )

        assert result.direct_answer == ""
        assert result.confidence_score == 0.0


# ── 6. Backend serialisation contract ─────────────────────────────────────────

class TestModelDumpSnakeCaseContract:
    """model_dump() must use snake_case keys — frontend reads t.direct_answer."""

    def test_model_dump_uses_direct_answer_snake_case(self):
        thesis = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            direct_answer="Higher rates compress AAPL's multiple.",
        )
        try:
            d = thesis.model_dump()
        except AttributeError:
            d = thesis.dict()

        assert "direct_answer" in d, (
            "model_dump() must use snake_case 'direct_answer' — "
            "frontend extractInvestmentThesis() reads t.direct_answer"
        )
        assert "directAnswer" not in d, (
            "model_dump() must not produce camelCase 'directAnswer' — "
            "that would break the frontend mapping"
        )
        assert d["direct_answer"] == "Higher rates compress AAPL's multiple."

    def test_investment_thesis_api_payload_contains_direct_answer(self, monkeypatch):
        """The dict packed into answer['investment_thesis'] must have direct_answer."""
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        evidence = _evidence()

        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = _thesis_json()
            thesis = synthesize_thesis(
                company, valuation, macro, risk, market, quality, evidence,
                original_user_question=APPLE_RATES_QUESTION,
            )

        try:
            payload = thesis.model_dump()
        except AttributeError:
            payload = thesis.dict()

        # This is exactly what router_service packs into answer["investment_thesis"]
        assert "direct_answer" in payload
        assert payload["direct_answer"] != "", (
            "direct_answer must be non-empty when LLM returns it"
        )

    def test_empty_direct_answer_field_still_present_in_dump(self):
        """Even when direct_answer='', the key must be in model_dump() output."""
        thesis = InvestmentThesis(ticker="AAPL", company_name="Apple Inc.")
        try:
            d = thesis.model_dump()
        except AttributeError:
            d = thesis.dict()

        assert "direct_answer" in d
        assert d["direct_answer"] == ""
