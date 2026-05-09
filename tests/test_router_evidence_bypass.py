"""
Tests for the evidence-count-based fallback gate in route_question()
(app/services/router_service.py).

Core invariant:
  • evidence_count > 0  → generic-language gate is skipped entirely;
    answer is kept unless it is empty / shorter than 40 chars.
  • evidence_count == 0 → generic-language gate applies as before.
  • For yield questions that DO need a fallback the replacement must be
    _YIELD_FALLBACK_ANSWER, never the old "Bond yields affect the stock
    market…" static text.

The agent functions are fully mocked so no network calls are made.
evidence_count is set on the fake GeneralFinanceAnswer to simulate what the
real agents stamp after evidence retrieval.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from app.services.router_service import (
    _ROUTER_EVIDENCE_TERMS,
    _is_generic_answer,
    _topic_aware_fallback,
)
from app.agents import _YIELD_FALLBACK_ANSWER, _GENERIC_EVIDENCE_FALLBACK
from app.schemas import GeneralFinanceAnswer, QuestionRequest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_result(answer: str, evidence_count: int = 0) -> GeneralFinanceAnswer:
    """Build a fake agent result with controlled evidence_count."""
    r = GeneralFinanceAnswer(answer=answer, bullets=["b1"], caveats=["c1"])
    r.evidence_count = evidence_count
    return r


def _route(question: str, agent_answer: str, evidence_count: int = 0) -> str:
    """Patch both agent entry-points and return the final routed answer string."""
    from app.services.router_service import route_question

    fake = _make_result(agent_answer, evidence_count=evidence_count)
    req = QuestionRequest(question=question, company_name="")
    with patch("app.services.router_service.run_general_finance_agent",
               return_value=fake), \
         patch("app.services.router_service.run_general_fallback_agent",
               return_value=fake):
        resp = route_question(req)
    return resp.answer["general"]["answer"]


# ── _ROUTER_EVIDENCE_TERMS content ───────────────────────────────────────────

class TestRouterEvidenceTerms:
    """Smoke-tests that the frozenset covers all key FRED vocabulary."""

    def test_treasury_yield_variants(self):
        assert "10-year treasury" in _ROUTER_EVIDENCE_TERMS
        assert "2-year treasury" in _ROUTER_EVIDENCE_TERMS
        assert "treasury yield" in _ROUTER_EVIDENCE_TERMS
        assert "treasury yields" in _ROUTER_EVIDENCE_TERMS

    def test_yield_curve(self):
        assert "yield curve" in _ROUTER_EVIDENCE_TERMS

    def test_fed_funds(self):
        assert "fed funds" in _ROUTER_EVIDENCE_TERMS
        assert "federal funds" in _ROUTER_EVIDENCE_TERMS

    def test_inflation_terms(self):
        assert "cpi" in _ROUTER_EVIDENCE_TERMS
        assert "consumer price" in _ROUTER_EVIDENCE_TERMS

    def test_macro_series(self):
        assert "unemployment" in _ROUTER_EVIDENCE_TERMS
        assert "gdp" in _ROUTER_EVIDENCE_TERMS
        assert "industrial production" in _ROUTER_EVIDENCE_TERMS

    def test_fred_series_ids(self):
        assert "dgs10" in _ROUTER_EVIDENCE_TERMS
        assert "dgs2" in _ROUTER_EVIDENCE_TERMS
        assert "t10y2y" in _ROUTER_EVIDENCE_TERMS

    def test_is_frozenset(self):
        assert isinstance(_ROUTER_EVIDENCE_TERMS, frozenset)


# ── Core gate: evidence_count > 0 keeps the answer ───────────────────────────

class TestEvidenceCountGate:
    """When evidence_count > 0 the generic-language check must be skipped."""

    # ── Real-looking answers (evidence_count=3, Render log scenario) ─────────

    def test_10yr_treasury_mention_kept_with_evidence(self):
        """The exact scenario from the Render logs: answer mentions
        10-year Treasury + market participants but evidence_count=3."""
        answer = (
            "Treasury yields are rising because market participants are "
            "repricing Fed rate hike expectations upward following hotter-than-"
            "expected CPI. The 10-year Treasury yield hit 4.62% as long-term "
            "bonds sold off on inflation fears."
        )
        result = _route("Why are treasury yields rising?", answer, evidence_count=3)
        assert result == answer

    def test_generic_language_with_evidence_kept(self):
        """'market participants' is in _GENERIC_ANSWER_FRAGMENTS but
        evidence_count > 0 must prevent replacement."""
        answer = (
            "The yield curve has re-inverted. Market participants are watching "
            "whether the 2-year Treasury yield stays above the 10-year, which "
            "historically signals recession risk within 12–18 months."
        )
        result = _route("What is the yield curve doing?", answer, evidence_count=3)
        assert result == answer

    def test_financial_markets_respond_phrase_kept_with_evidence(self):
        answer = (
            "CPI came in at 3.5% year-over-year. Financial markets respond to "
            "this number because it directly informs Fed rate policy — a hot "
            "print reduces the probability of near-term rate cuts."
        )
        result = _route("What is inflation doing?", answer, evidence_count=2)
        assert result == answer

    def test_is_important_concept_phrase_kept_with_evidence(self):
        answer = (
            "The federal funds rate is an important concept for understanding "
            "borrowing costs. It currently sits at 5.25–5.50%, the highest "
            "level since 2001, reflecting the Fed's anti-inflation stance."
        )
        result = _route("What is the Fed funds rate?", answer, evidence_count=1)
        assert result == answer

    def test_gdp_answer_with_evidence_kept(self):
        answer = (
            "GDP growth was revised down to 1.6% annualised in Q4, weaker than "
            "the initial 2.1% estimate, as consumer spending cooled and "
            "business investment contracted slightly."
        )
        result = _route("How is GDP growth?", answer, evidence_count=2)
        assert result == answer

    def test_unemployment_answer_with_evidence_kept(self):
        answer = (
            "The unemployment rate rose to 3.9%, its highest since early 2022, "
            "as payroll growth in manufacturing and retail slowed more than "
            "economists expected."
        )
        result = _route("What is unemployment doing?", answer, evidence_count=2)
        assert result == answer

    def test_answer_without_evidence_terms_still_kept_with_count(self):
        """Even an answer that contains NO FRED vocabulary is kept when
        evidence_count > 0 — the count is the gate, not text scanning."""
        answer = (
            "Rates moved sharply overnight after the jobs report came in far "
            "above consensus, forcing investors to reprice the path of Fed policy "
            "and pushing short-duration paper to multi-year highs."
        )
        result = _route("Why did rates spike?", answer, evidence_count=3)
        assert result == answer

    # ── evidence_count = 0: generic-language gate must still fire ────────────

    def test_generic_answer_no_evidence_is_replaced(self):
        generic = (
            "Market participants watch interest rates closely. "
            "This is a market question about monetary policy."
        )
        result = _route("How often does the Fed meet?", generic, evidence_count=0)
        assert result != generic

    def test_good_answer_no_evidence_is_kept(self):
        good = (
            "The Federal Reserve's FOMC meets eight times per year — roughly "
            "every six to eight weeks — producing a rate decision and statement "
            "at each meeting; four meetings per year also include the dot plot."
        )
        result = _route("How often does the Fed meet?", good, evidence_count=0)
        assert result == good


# ── too_short: always replace regardless of evidence_count ───────────────────

class TestTooShortAlwaysReplaced:
    """Answers shorter than 40 chars are replaced even when evidence was used."""

    def test_empty_answer_replaced(self):
        result = _route("Why are yields rising?", "", evidence_count=3)
        assert len(result) >= 40

    def test_very_short_answer_replaced(self):
        result = _route("Why are yields rising?", "Yields rose.", evidence_count=3)
        assert len(result) >= 40

    def test_replacement_is_non_empty(self):
        result = _route("What is inflation?", "", evidence_count=0)
        assert result


# ── Yield fallback when replacement IS needed ─────────────────────────────────

class TestYieldFallbackSelection:
    """When a fallback is triggered on a yield question the answer must be
    _YIELD_FALLBACK_ANSWER, never the old 'Bond yields affect…' text."""

    OLD_STATIC = "Bond yields affect the stock market because"

    def test_bare_yields_question_gets_yield_fallback(self):
        result = _route("Why are yields rising right now?", "", evidence_count=0)
        assert result == _YIELD_FALLBACK_ANSWER

    def test_treasury_yields_question_gets_yield_fallback(self):
        result = _route("Why are treasury yields moving?", "", evidence_count=0)
        assert result == _YIELD_FALLBACK_ANSWER

    def test_bond_yield_question_gets_yield_fallback(self):
        generic = "Bond yields are an important concept. Market participants watch them."
        result = _route("Why are bond yields rising?", generic, evidence_count=0)
        assert result == _YIELD_FALLBACK_ANSWER

    def test_old_static_text_never_returned_for_yield_question(self):
        result = _route("Why are yields rising?", "", evidence_count=0)
        assert self.OLD_STATIC not in result

    def test_yield_fallback_mentions_10yr(self):
        result = _route("Why are yields rising?", "", evidence_count=0)
        assert "10-year" in result.lower()

    def test_yield_fallback_mentions_2yr(self):
        result = _route("Why are yields rising?", "", evidence_count=0)
        assert "2-year" in result.lower()

    def test_yield_fallback_mentions_yield_curve(self):
        result = _route("Why are yields rising?", "", evidence_count=0)
        assert "yield curve" in result.lower()


# ── Non-yield fallback still works ───────────────────────────────────────────

class TestNonYieldFallback:
    """For non-yield topics the static _TOPIC_FALLBACKS text is still used."""

    def test_non_yield_generic_no_evidence_replaced(self):
        generic = "Market participants watch interest rates closely."
        result = _route("How often does the Fed meet?", generic, evidence_count=0)
        assert result != generic
        assert result

    def test_non_yield_good_answer_kept(self):
        good = (
            "The FOMC meets eight times a year on a fixed schedule, roughly "
            "every six to eight weeks. Each meeting ends with a rate decision "
            "and a policy statement."
        )
        result = _route("How often does the Fed meet?", good, evidence_count=0)
        assert result == good

    def test_non_yield_generic_with_evidence_kept(self):
        """Even a generic-sounding answer is kept for non-yield topics when
        evidence_count > 0."""
        generic = (
            "Market participants watch Fed meetings closely because the rate "
            "decision directly sets short-term borrowing costs, which flow "
            "through to mortgages, car loans, and corporate credit lines."
        )
        result = _route("How often does the Fed meet?", generic, evidence_count=2)
        assert result == generic


# ── _YIELD_FALLBACK_ANSWER self-consistency ───────────────────────────────────

class TestYieldFallbackContent:
    """The constant itself must be informative enough to be a real fallback."""

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

    def test_does_not_start_with_old_static(self):
        assert not _YIELD_FALLBACK_ANSWER.startswith(
            "Bond yields affect the stock market"
        )

    def test_longer_than_40_chars(self):
        assert len(_YIELD_FALLBACK_ANSWER) > 40


# ── evidence_count stamped on GeneralFinanceAnswer ───────────────────────────

class TestEvidenceCountSchema:
    """GeneralFinanceAnswer must accept and hold an evidence_count field."""

    def test_default_is_zero(self):
        r = GeneralFinanceAnswer(answer="test", bullets=[], caveats=[])
        assert r.evidence_count == 0

    def test_can_set_to_nonzero(self):
        r = GeneralFinanceAnswer(answer="test", bullets=[], caveats=[])
        r.evidence_count = 3
        assert r.evidence_count == 3

    def test_constructor_accepts_evidence_count(self):
        r = GeneralFinanceAnswer(
            answer="test", bullets=[], caveats=[], evidence_count=5
        )
        assert r.evidence_count == 5
