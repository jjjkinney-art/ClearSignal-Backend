"""
Tests for the general_fallback intent and agent.

Covers:
  - _detect_intent() routes the five required example questions correctly
  - general_fallback routes that ARE finance-related go to market_question
    or investing_education, not general_fallback
  - run_general_fallback_agent() returns a valid GeneralFinanceAnswer with
    non-empty fields when given a stubbed model client
  - route_question() wires general_fallback through the full fallback-
    enforcement path and never returns empty answer/bullets/caveats
  - company_analysis behaviour is unchanged
"""

import os
import sys
import json
from typing import Any

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas import GeneralFinanceAnswer, QuestionRequest
from app.services.router_service import _detect_intent, route_question


# ─────────────────────────────────────────────────────────────────────────────
# _detect_intent — the five required example questions
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectIntentFallbackExamples:
    """The five required example questions from the spec."""

    def test_how_often_does_fed_meet(self):
        """'How often does the Fed meet?' — contains 'fed', finance keyword → market_question."""
        intent = _detect_intent("How often does the Fed meet?")
        assert intent == "market_question", (
            f"Expected market_question (contains 'fed'), got {intent!r}"
        )

    def test_why_do_markets_crash(self):
        """'Why do markets crash?' — contains 'market' → market_question."""
        intent = _detect_intent("Why do markets crash?")
        assert intent == "market_question", (
            f"Expected market_question (contains 'market'), got {intent!r}"
        )

    def test_how_does_ai_affect_productivity(self):
        """'How does AI affect productivity?' — no finance keywords → general_fallback."""
        intent = _detect_intent("How does AI affect productivity?")
        assert intent == "general_fallback", (
            f"Expected general_fallback (no finance keywords), got {intent!r}"
        )

    def test_what_makes_a_company_valuable(self):
        """'What makes a company valuable?' — contains 'company' → finance pipeline."""
        intent = _detect_intent("What makes a company valuable?")
        # Contains 'company' (finance keyword) but no education trigger → market_question
        # Alternatively could be investing_education — either is acceptable.
        assert intent in ("market_question", "investing_education"), (
            f"Expected a finance intent, got {intent!r}"
        )

    def test_explain_bond_yields_beginner(self):
        """'Explain bond yields like I'm new to investing.' — 'explain' + finance → investing_education."""
        intent = _detect_intent("Explain bond yields like I'm new to investing.")
        assert intent == "investing_education", (
            f"Expected investing_education ('explain' + 'bond'), got {intent!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# _detect_intent — routing correctness for a wider set of cases
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectIntentRouting:
    """Intent detection routes correctly across all four buckets."""

    # ── general_fallback ─────────────────────────────────────────────────────

    def test_ai_productivity_is_fallback(self):
        assert _detect_intent("How does AI affect productivity?") == "general_fallback"

    def test_climate_change_is_fallback(self):
        assert _detect_intent("What is climate change?") == "general_fallback"

    def test_geopolitics_is_fallback(self):
        assert _detect_intent("Why did Russia invade Ukraine?") == "general_fallback"

    def test_empty_question_is_fallback(self):
        # Empty / whitespace question has no finance keywords
        assert _detect_intent("") == "general_fallback"

    def test_unrelated_question_is_fallback(self):
        assert _detect_intent("What is the speed of light?") == "general_fallback"

    # ── market_question ──────────────────────────────────────────────────────

    def test_interest_rates_stocks_is_market(self):
        assert _detect_intent("How will interest rates affect stocks?") == "market_question"

    def test_fed_meeting_is_market(self):
        assert _detect_intent("How often does the Fed meet?") == "market_question"

    def test_why_markets_crash_is_market(self):
        assert _detect_intent("Why do markets crash?") == "market_question"

    def test_bull_market_is_market(self):
        assert _detect_intent("Are we in a bull market?") == "market_question"

    # ── investing_education ──────────────────────────────────────────────────

    def test_what_is_pe_ratio_is_education(self):
        assert _detect_intent("What is a P/E ratio?") == "investing_education"

    def test_explain_bond_yields_is_education(self):
        assert _detect_intent("Explain bond yields like I'm new to investing.") == "investing_education"

    def test_how_does_inflation_affect_is_education(self):
        assert _detect_intent("How does inflation affect bond prices?") == "investing_education"

    def test_what_is_etf_is_education(self):
        assert _detect_intent("What is an ETF?") == "investing_education"

    # ── portfolio_question ───────────────────────────────────────────────────

    def test_my_portfolio_is_portfolio(self):
        assert _detect_intent("Should I rebalance my portfolio?") == "portfolio_question"

    def test_i_own_stock_is_portfolio(self):
        assert _detect_intent("I own Apple stock — should I sell?") == "portfolio_question"

    def test_diversify_is_portfolio(self):
        assert _detect_intent("How should I diversify my holdings?") == "portfolio_question"


# ─────────────────────────────────────────────────────────────────────────────
# run_general_fallback_agent — stubbed model client
# ─────────────────────────────────────────────────────────────────────────────

class TestRunGeneralFallbackAgent:
    """run_general_fallback_agent returns a valid GeneralFinanceAnswer."""

    def _make_stub_client(self, answer_json: str):
        """Return a minimal stub that has a .call() method."""
        class _StubClient:
            def call(self, prompt: str, **kwargs: Any) -> str:
                return answer_json
        return _StubClient()

    def test_returns_structured_answer(self, monkeypatch):
        """Agent returns a valid GeneralFinanceAnswer when model succeeds."""
        from app import agents as ag

        good_json = json.dumps({
            "answer": "The Fed meets eight times per year on a fixed schedule.",
            "bullets": ["Bullet one.", "Bullet two.", "Bullet three."],
            "caveats": ["Caveat one.", "Caveat two."],
        })
        monkeypatch.setattr(ag, "model_client", self._make_stub_client(good_json))

        result = ag.run_general_fallback_agent("How often does the Fed meet?")

        assert isinstance(result, GeneralFinanceAnswer)
        assert len(result.answer) >= 20
        assert len(result.bullets) == 3
        assert len(result.caveats) == 2

    def test_empty_model_response_returns_default(self, monkeypatch):
        """When the model returns unparseable output, agent returns a default instance."""
        from app import agents as ag

        monkeypatch.setattr(ag, "model_client", self._make_stub_client("not json at all!!!"))

        result = ag.run_general_fallback_agent("Why do markets crash?")

        # structured_output falls back to schema() — fields default to "" / []
        assert isinstance(result, GeneralFinanceAnswer)


# ─────────────────────────────────────────────────────────────────────────────
# route_question — full integration with stubbed agents
# ─────────────────────────────────────────────────────────────────────────────

class TestRouteQuestionFallback:
    """route_question never returns empty fields for general_fallback intent."""

    def _make_stub_agent(self, answer: str, bullets=None, caveats=None):
        """Return a stub for run_general_fallback_agent / run_general_finance_agent."""
        def _stub(*args, **kwargs):
            return GeneralFinanceAnswer(
                answer=answer,
                bullets=bullets or ["B1.", "B2.", "B3."],
                caveats=caveats or ["C1.", "C2."],
            )
        return _stub

    def test_fallback_intent_routes_to_fallback_agent(self, monkeypatch):
        """Explicit general_fallback intent calls run_general_fallback_agent."""
        from app.services import router_service as rs

        called_with = {}

        def fake_fallback(question, request_id=None):
            called_with["question"] = question
            return GeneralFinanceAnswer(
                answer="AI boosts productivity by automating repetitive work.",
                bullets=["B1.", "B2.", "B3."],
                caveats=["C1.", "C2."],
            )

        monkeypatch.setattr(rs, "run_general_fallback_agent", fake_fallback)

        req = QuestionRequest(
            company_name="",
            question="How does AI affect productivity?",
            intent="general_fallback",
        )
        response = route_question(req)

        assert called_with.get("question") == "How does AI affect productivity?"
        assert response.routing["intent"] == "general_fallback"
        assert response.routing["pipeline"] == "general_fallback"
        general = response.answer["general"]
        assert general["answer"] != ""
        assert len(general["bullets"]) > 0
        assert len(general["caveats"]) > 0

    def test_fallback_guard_fires_for_empty_answer(self, monkeypatch):
        """Fallback enforcement replaces empty answer even for general_fallback intent."""
        from app.services import router_service as rs

        monkeypatch.setattr(
            rs, "run_general_fallback_agent",
            lambda *a, **kw: GeneralFinanceAnswer(answer="", bullets=[], caveats=[]),
        )

        req = QuestionRequest(
            company_name="",
            question="How does AI affect productivity?",
            intent="general_fallback",
        )
        response = route_question(req)

        general = response.answer["general"]
        assert len(general["answer"].strip()) >= 40, (
            "Fallback enforcement should produce a non-empty answer"
        )
        assert len(general["bullets"]) > 0, "Fallback enforcement should populate bullets"
        assert len(general["caveats"]) > 0, "Fallback enforcement should populate caveats"

    def test_auto_detected_fallback_for_non_finance_question(self, monkeypatch):
        """No explicit intent: non-finance question auto-routes to general_fallback."""
        from app.services import router_service as rs

        agent_called = {}

        def fake_fallback(question, request_id=None):
            agent_called["used"] = "fallback"
            return GeneralFinanceAnswer(
                answer="AI raises productivity by automating knowledge work.",
                bullets=["B1.", "B2.", "B3."],
                caveats=["C1.", "C2."],
            )

        def fake_finance(question, intent=None, request_id=None):
            agent_called["used"] = "finance"
            return GeneralFinanceAnswer(
                answer="Finance agent answer.",
                bullets=["B1.", "B2.", "B3."],
                caveats=["C1.", "C2."],
            )

        monkeypatch.setattr(rs, "run_general_fallback_agent", fake_fallback)
        monkeypatch.setattr(rs, "run_general_finance_agent", fake_finance)

        req = QuestionRequest(
            company_name="",
            question="How does AI affect productivity?",
            # no intent supplied — should be auto-detected as general_fallback
        )
        route_question(req)

        assert agent_called.get("used") == "fallback", (
            "A non-finance question with no intent should route to fallback agent"
        )

    def test_company_analysis_unchanged(self, monkeypatch):
        """company_analysis intent still goes through equity pipeline, not general agents."""
        from app.services import router_service as rs

        general_called = {}

        def fake_fallback(*a, **kw):
            general_called["called"] = True
            return GeneralFinanceAnswer(answer="x", bullets=["b"], caveats=["c"])

        def fake_finance(*a, **kw):
            general_called["called"] = True
            return GeneralFinanceAnswer(answer="x", bullets=["b"], caveats=["c"])

        monkeypatch.setattr(rs, "run_general_fallback_agent", fake_fallback)
        monkeypatch.setattr(rs, "run_general_finance_agent", fake_finance)

        # Stub equity agent so we don't hit the LLM
        from app.schemas import EquityAnalysis
        monkeypatch.setattr(rs, "run_equity_agent", lambda *a, **kw: EquityAnalysis())
        monkeypatch.setattr(rs, "enrich_grounding_context", lambda *a, **kw: None)
        monkeypatch.setattr(rs, "select_evidence_sources", lambda *a, **kw: {"selected_sources": []})
        monkeypatch.setattr(rs, "build_evidence", lambda *a, **kw: None)

        req = QuestionRequest(
            company_name="Apple",
            question="What is Apple's revenue?",
            intent="company_analysis",
        )
        route_question(req)

        assert not general_called.get("called"), (
            "company_analysis must not invoke any general finance agent"
        )
