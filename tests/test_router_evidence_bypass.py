"""
Tests for the evidence-bypass logic added to route_question() in
router_service.py.

The key invariant being tested:
  • When an answer already contains evidence terms (treasury yield, CPI, etc.)
    the router must NOT replace it with a static fallback — even if the answer
    also contains phrases in _GENERIC_ANSWER_FRAGMENTS.
  • When no evidence terms are present AND the answer is generic, the router
    SHOULD replace it; for yield questions the replacement must be
    _YIELD_FALLBACK_ANSWER, not the old "Bond yields affect the stock market…"
    text.
  • The old "Bond yields affect the stock market…" string must never be
    returned when the answer already contains evidence terms.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from app.services.router_service import (
    _ROUTER_EVIDENCE_TERMS,
    _is_generic_answer,
    _topic_aware_fallback,
)
from app.agents import _YIELD_FALLBACK_ANSWER, _GENERIC_EVIDENCE_FALLBACK


# ── _ROUTER_EVIDENCE_TERMS content ───────────────────────────────────────────

class TestRouterEvidenceTerms:
    """The frozenset must cover all the key FRED evidence vocabulary."""

    def test_contains_treasury_yield_variants(self):
        assert "10-year treasury" in _ROUTER_EVIDENCE_TERMS
        assert "2-year treasury" in _ROUTER_EVIDENCE_TERMS
        assert "treasury yield" in _ROUTER_EVIDENCE_TERMS
        assert "treasury yields" in _ROUTER_EVIDENCE_TERMS

    def test_contains_yield_curve(self):
        assert "yield curve" in _ROUTER_EVIDENCE_TERMS

    def test_contains_fed_funds(self):
        assert "fed funds" in _ROUTER_EVIDENCE_TERMS
        assert "federal funds" in _ROUTER_EVIDENCE_TERMS

    def test_contains_inflation_terms(self):
        assert "cpi" in _ROUTER_EVIDENCE_TERMS
        assert "consumer price" in _ROUTER_EVIDENCE_TERMS

    def test_contains_macro_series(self):
        assert "unemployment" in _ROUTER_EVIDENCE_TERMS
        assert "gdp" in _ROUTER_EVIDENCE_TERMS
        assert "industrial production" in _ROUTER_EVIDENCE_TERMS

    def test_contains_fred_series_ids(self):
        assert "dgs10" in _ROUTER_EVIDENCE_TERMS
        assert "dgs2" in _ROUTER_EVIDENCE_TERMS
        assert "t10y2y" in _ROUTER_EVIDENCE_TERMS

    def test_is_frozenset(self):
        assert isinstance(_ROUTER_EVIDENCE_TERMS, frozenset)


# ── Evidence bypass: answer contains evidence terms ───────────────────────────

class TestEvidenceBypassLogic:
    """Answers that contain evidence terms must survive the generic-language
    check untouched, regardless of whether they also contain banned phrases."""

    def _make_request(self, question: str):
        from app.schemas import QuestionRequest
        return QuestionRequest(question=question, company_name="")

    def _run_route(self, question: str, agent_answer: str):
        """Patch run_general_finance_agent to return a controlled answer, then
        call route_question and return the answer string from the response."""
        from app.schemas import GeneralFinanceAnswer
        from app.services.router_service import route_question

        fake_result = GeneralFinanceAnswer(
            answer=agent_answer,
            bullets=["bullet 1"],
            caveats=["caveat 1"],
        )
        with patch("app.services.router_service.run_general_finance_agent",
                   return_value=fake_result), \
             patch("app.services.router_service.run_general_fallback_agent",
                   return_value=fake_result):
            resp = route_question(self._make_request(question))

        return resp.answer["general"]["answer"]

    # ── Evidence present: answer must be kept ────────────────────────────────

    def test_treasury_yield_answer_kept(self):
        answer = (
            "The 10-year Treasury yield rose to 4.62% as market participants "
            "repriced Fed rate expectations higher."
        )
        result = self._run_route("Why are treasury yields rising?", answer)
        assert result == answer

    def test_yield_curve_answer_kept(self):
        answer = (
            "The yield curve has re-inverted as the 2-year Treasury climbed "
            "above the 10-year Treasury, signaling recession risk."
        )
        result = self._run_route("What is the yield curve doing?", answer)
        assert result == answer

    def test_cpi_answer_kept(self):
        answer = (
            "CPI came in hotter than expected at 3.5% YoY, which is pushing "
            "the Fed to hold rates higher for longer."
        )
        result = self._run_route("What is inflation doing right now?", answer)
        assert result == answer

    def test_fed_funds_answer_kept(self):
        answer = (
            "The federal funds rate is currently 5.25–5.50%, and the Fed has "
            "signaled it will not cut until inflation returns to 2%."
        )
        result = self._run_route("What is the Fed funds rate?", answer)
        assert result == answer

    def test_unemployment_answer_kept(self):
        answer = (
            "The unemployment rate ticked up to 3.9%, its highest reading "
            "since early 2022, as hiring in manufacturing slowed."
        )
        result = self._run_route("What is unemployment doing?", answer)
        assert result == answer

    def test_gdp_answer_kept(self):
        answer = (
            "GDP growth in Q4 was revised down to 1.6% annualized, below the "
            "initial 2.1% estimate, reflecting weaker consumer spending."
        )
        result = self._run_route("How is GDP growth looking?", answer)
        assert result == answer

    # ── Evidence present + generic phrase: still kept ────────────────────────

    def test_evidence_answer_with_market_participants_kept(self):
        """'market participants' is in _GENERIC_ANSWER_FRAGMENTS, but the
        answer ALSO contains a treasury evidence term — must be kept."""
        answer = (
            "The 10-year Treasury yield is at 4.62%.  Market participants are "
            "watching the Fed's next move closely."
        )
        result = self._run_route("Why are yields rising?", answer)
        assert result == answer

    def test_evidence_answer_with_financial_markets_respond_kept(self):
        answer = (
            "The yield curve has inverted. Financial markets respond to this "
            "signal by pricing in higher recession risk over the next 12 months."
        )
        result = self._run_route("What is the yield curve saying?", answer)
        assert result == answer


# ── No evidence + generic language: must trigger fallback ────────────────────

class TestFallbackWhenNoEvidence:
    """When the answer contains no evidence terms and uses generic language,
    the router should replace it.  For yield questions, the replacement must
    be _YIELD_FALLBACK_ANSWER."""

    def _run_route(self, question: str, agent_answer: str):
        from app.schemas import GeneralFinanceAnswer, QuestionRequest
        from app.services.router_service import route_question

        fake_result = GeneralFinanceAnswer(
            answer=agent_answer,
            bullets=["bullet 1"],
            caveats=["caveat 1"],
        )
        req = QuestionRequest(question=question, company_name="")
        with patch("app.services.router_service.run_general_finance_agent",
                   return_value=fake_result), \
             patch("app.services.router_service.run_general_fallback_agent",
                   return_value=fake_result):
            resp = route_question(req)

        return resp.answer["general"]["answer"]

    def test_generic_yield_answer_replaced_with_yield_fallback(self):
        generic_answer = (
            "Bond yields are an important concept in macroeconomics. "
            "Market participants watch them closely for signals about monetary policy."
        )
        result = self._run_route("Why are yields rising right now?", generic_answer)
        assert result == _YIELD_FALLBACK_ANSWER

    def test_yield_fallback_mentions_10yr_treasury(self):
        generic_answer = (
            "This is a market question about yields. Financial markets respond "
            "to interest rate changes in many ways."
        )
        result = self._run_route("Why are treasury yields moving?", generic_answer)
        assert "10-year" in result.lower() or "10-Year" in result

    def test_yield_fallback_mentions_2yr_treasury(self):
        generic_answer = (
            "This is a market question about yields. Financial markets respond "
            "to interest rate changes in many ways."
        )
        result = self._run_route("Why are treasury yields moving?", generic_answer)
        assert "2-year" in result.lower() or "2-Year" in result

    def test_yield_fallback_mentions_yield_curve(self):
        generic_answer = (
            "This is a market question about yields. Financial markets respond "
            "to interest rate changes in many ways."
        )
        result = self._run_route("Why are treasury yields moving?", generic_answer)
        assert "yield curve" in result.lower()

    def test_old_static_yield_text_never_returned_for_generic_yield_question(self):
        """The old 'Bond yields affect the stock market because…' text must
        never be the answer when the question is about yields."""
        OLD_STATIC = "Bond yields affect the stock market because"
        generic_answer = (
            "Bond yields are an important concept. Market participants watch "
            "them closely."
        )
        result = self._run_route("Why are bond yields rising?", generic_answer)
        assert OLD_STATIC not in result


# ── Too-short answer: always replaced ────────────────────────────────────────

class TestTooShortAnswerReplaced:
    """Answers shorter than 40 characters are always replaced, even if they
    contain an evidence term."""

    def _run_route(self, question: str, agent_answer: str):
        from app.schemas import GeneralFinanceAnswer, QuestionRequest
        from app.services.router_service import route_question

        fake_result = GeneralFinanceAnswer(
            answer=agent_answer,
            bullets=[],
            caveats=[],
        )
        req = QuestionRequest(question=question, company_name="")
        with patch("app.services.router_service.run_general_finance_agent",
                   return_value=fake_result), \
             patch("app.services.router_service.run_general_fallback_agent",
                   return_value=fake_result):
            resp = route_question(req)
        return resp.answer["general"]["answer"]

    def test_too_short_empty_replaced(self):
        result = self._run_route("What are bond yields?", "")
        assert len(result) >= 40

    def test_too_short_with_evidence_term_still_replaced(self):
        result = self._run_route("What are bond yields?", "CPI 3.5%")
        assert len(result) >= 40

    def test_too_short_answer_is_non_empty(self):
        result = self._run_route("Why are yields rising?", "Yields rose.")
        assert result  # not empty


# ── Non-yield topic: old static fallback still works ─────────────────────────

class TestNonYieldTopicFallback:
    """For questions that don't match any yield topic, the old _TOPIC_FALLBACKS
    text is still returned when the answer is generic."""

    def _run_route(self, question: str, agent_answer: str):
        from app.schemas import GeneralFinanceAnswer, QuestionRequest
        from app.services.router_service import route_question

        fake_result = GeneralFinanceAnswer(
            answer=agent_answer,
            bullets=[],
            caveats=[],
        )
        req = QuestionRequest(question=question, company_name="")
        with patch("app.services.router_service.run_general_finance_agent",
                   return_value=fake_result), \
             patch("app.services.router_service.run_general_fallback_agent",
                   return_value=fake_result):
            resp = route_question(req)
        return resp.answer["general"]["answer"]

    def test_non_yield_generic_answer_is_replaced(self):
        generic = "Market participants watch interest rates closely."
        result = self._run_route(
            "How often does the Fed meet?", generic
        )
        # The answer should not be the original generic answer
        assert result != generic

    def test_non_yield_replacement_is_non_empty(self):
        generic = "This is a market question about the Federal Reserve."
        result = self._run_route("How often does the Fed meet?", generic)
        assert result

    def test_good_non_yield_answer_kept(self):
        good = (
            "The Federal Reserve's FOMC meets eight times per year, roughly "
            "every six to eight weeks.  Each meeting produces a rate decision "
            "and a policy statement; four meetings per year also include the "
            "dot plot and a press conference."
        )
        result = self._run_route("How often does the Fed meet?", good)
        assert result == good


# ── _YIELD_FALLBACK_ANSWER self-consistency ───────────────────────────────────

class TestYieldFallbackContent:
    """_YIELD_FALLBACK_ANSWER must mention the key FRED series so it is
    genuinely more informative than the old static text."""

    def test_mentions_10yr(self):
        assert "10-year" in _YIELD_FALLBACK_ANSWER.lower()

    def test_mentions_2yr(self):
        assert "2-year" in _YIELD_FALLBACK_ANSWER.lower()

    def test_mentions_yield_curve(self):
        assert "yield curve" in _YIELD_FALLBACK_ANSWER.lower()

    def test_mentions_inflation(self):
        assert "inflation" in _YIELD_FALLBACK_ANSWER.lower()

    def test_mentions_recession(self):
        assert "recession" in _YIELD_FALLBACK_ANSWER.lower()

    def test_does_not_start_with_bond_yields_affect(self):
        assert not _YIELD_FALLBACK_ANSWER.startswith(
            "Bond yields affect the stock market"
        )

    def test_is_non_empty(self):
        assert len(_YIELD_FALLBACK_ANSWER) > 40
