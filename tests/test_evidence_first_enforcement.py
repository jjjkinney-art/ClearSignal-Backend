"""
Tests for evidence-first synthesis enforcement.

Coverage
--------
Prompt structure
  - evidence section appears at the very TOP of general_finance_prompt (before
    the identity sentence)
  - evidence section appears at the very TOP of general_fallback_prompt
  - HARD RULE / EVIDENCE REFERENCE text present when evidence provided
  - FIRST SENTENCE RULE present for temporal questions
  - FIRST SENTENCE RULE absent for non-temporal questions

Post-generation quality guard (_enforce_evidence_usage)
  - answer that contains an evidence term → passes unchanged
  - answer with no evidence terms + yield question → replaced with yield fallback
  - answer with no evidence terms + non-yield question → replaced with generic fallback
  - no evidence → answer never replaced regardless of content
  - bullets and caveats preserved after fallback replacement
  - all three canonical yield question phrasings trigger fallback when LLM ignores evidence
  - case-insensitive evidence term detection

Evidence-first synthesis (integration)
  - evidence exists + temporal yield question → answer mentions 10-year Treasury or
    2-year Treasury after guard
  - evidence exists + "today" → answer does not start with generic bond/stock
    explanation opener after guard
  - no evidence → conceptual fallback prompt is still complete and usable
"""

from __future__ import annotations

import os
import sys
from typing import List

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas import RetrievedEvidence, GeneralFinanceAnswer
from app.prompts import (
    general_finance_prompt,
    general_fallback_prompt,
    _evidence_synthesis_block,
)
from app.agents import (
    _enforce_evidence_usage,
    _is_yield_question,
    _EVIDENCE_TERMS,
    _YIELD_FALLBACK_ANSWER,
    _GENERIC_EVIDENCE_FALLBACK,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _ev(
    title: str = "10-Year Treasury Constant Maturity Rate: 4.61% (as of 2024-04-01)",
    source: str = "FRED (Federal Reserve Bank of St. Louis)",
    summary: str = (
        "The 10-year yield is the benchmark long-term rate investors use to price "
        "bonds, mortgages, and equity valuations."
    ),
    timestamp: str = "2024-04-01",
    relevance_score: float = 0.95,
) -> RetrievedEvidence:
    return RetrievedEvidence(
        title=title,
        source=source,
        summary=summary,
        timestamp=timestamp,
        relevance_score=relevance_score,
    )


def _yield_evidence() -> List[RetrievedEvidence]:
    return [
        _ev(title="10-Year Treasury Constant Maturity Rate: 4.61% (as of 2024-04-01)", relevance_score=0.95),
        _ev(title="2-Year Treasury Constant Maturity Rate: 4.85% (as of 2024-04-01)", relevance_score=0.88),
        _ev(title="10-Year Minus 2-Year Treasury Spread: -0.24 pp (as of 2024-04-01)", relevance_score=0.80),
    ]


def _make_answer(text: str) -> GeneralFinanceAnswer:
    return GeneralFinanceAnswer(
        answer=text,
        bullets=["bullet one", "bullet two", "bullet three"],
        caveats=["caveat one", "caveat two"],
    )


# ── Prompt structure ───────────────────────────────────────────────────────────

class TestPromptStructure:
    """Evidence section must appear before any other content in the prompt."""

    def test_finance_prompt_evidence_before_identity(self):
        """CURRENT CONTEXT must appear before the analyst identity line."""
        p = general_finance_prompt("Why are yields rising today?", evidence=_yield_evidence())
        assert p.index("CURRENT CONTEXT") < p.index("You are a senior financial analyst")

    def test_fallback_prompt_evidence_before_identity(self):
        """CURRENT CONTEXT must appear before the analyst identity line."""
        p = general_fallback_prompt("How does inflation affect markets currently?", evidence=[_ev()])
        assert p.index("CURRENT CONTEXT") < p.index("You are a knowledgeable analyst")

    def test_finance_prompt_synthesis_before_identity(self):
        """SYNTHESIS REQUIREMENTS must appear before the analyst identity line."""
        p = general_finance_prompt("Why are yields rising today?", evidence=_yield_evidence())
        assert p.index("SYNTHESIS REQUIREMENTS") < p.index("You are a senior financial analyst")

    def test_fallback_prompt_synthesis_before_identity(self):
        """SYNTHESIS REQUIREMENTS must appear before the analyst identity line."""
        p = general_fallback_prompt("How does inflation affect markets currently?", evidence=[_ev()])
        assert p.index("SYNTHESIS REQUIREMENTS") < p.index("You are a knowledgeable analyst")

    def test_finance_prompt_evidence_before_examples(self):
        """CURRENT CONTEXT must appear before the EXAMPLES section."""
        p = general_finance_prompt("Why are yields rising today?", evidence=_yield_evidence())
        assert p.index("CURRENT CONTEXT") < p.index("EXAMPLES")

    def test_finance_prompt_no_evidence_identity_first(self):
        """Without evidence the identity sentence is the very first content."""
        p = general_finance_prompt("Why are yields rising?")
        assert p.startswith("You are a senior financial analyst")

    def test_fallback_prompt_no_evidence_identity_first(self):
        """Without evidence the identity sentence is the very first content."""
        p = general_fallback_prompt("How does inflation work?")
        assert p.startswith("You are a knowledgeable analyst")

    def test_hard_rule_evidence_reference_present(self):
        """HARD RULE requiring evidence reference must appear in synthesis block."""
        p = general_finance_prompt("Why are yields rising?", evidence=_yield_evidence())
        assert "HARD RULE" in p
        assert "EVIDENCE REFERENCE" in p

    def test_hard_rule_names_acceptable_evidence_terms(self):
        """The hard rule must list the terms the guard checks against."""
        p = general_finance_prompt("Why are yields rising?", evidence=_yield_evidence())
        assert "10-year Treasury" in p
        assert "2-year Treasury" in p
        assert "yield curve" in p
        assert "Fed funds rate" in p
        assert "CPI" in p

    def test_hard_rule_absent_without_evidence(self):
        """HARD RULE must not appear when there is no evidence."""
        p = general_finance_prompt("Why are yields rising?", evidence=None)
        assert "HARD RULE" not in p

    def test_first_sentence_rule_present_for_temporal(self):
        """FIRST SENTENCE RULE must appear for temporal questions with evidence."""
        p = general_finance_prompt("Why are yields rising today?", evidence=_yield_evidence())
        assert "FIRST SENTENCE RULE" in p

    def test_first_sentence_rule_absent_for_non_temporal(self):
        """FIRST SENTENCE RULE must NOT appear for non-temporal questions."""
        p = general_finance_prompt("How do bond yields affect stocks?", evidence=_yield_evidence())
        assert "FIRST SENTENCE RULE" not in p

    def test_first_sentence_rule_present_for_currently(self):
        p = general_finance_prompt("Why are yields currently elevated?", evidence=[_ev()])
        assert "FIRST SENTENCE RULE" in p

    def test_first_sentence_rule_present_for_right_now(self):
        p = general_finance_prompt("What is happening with yields right now?", evidence=[_ev()])
        assert "FIRST SENTENCE RULE" in p

    def test_first_sentence_rule_present_for_latest(self):
        p = general_finance_prompt("What is the latest on Treasury yields?", evidence=[_ev()])
        assert "FIRST SENTENCE RULE" in p


# ── _is_yield_question ─────────────────────────────────────────────────────────

class TestIsYieldQuestion:

    def test_treasury_yields_rising_today(self):
        assert _is_yield_question("Why are Treasury yields rising today?", _yield_evidence())

    def test_10_year_treasury_rising(self):
        assert _is_yield_question("Why is the 10-year Treasury yield rising?", _yield_evidence())

    def test_yields_moving_right_now(self):
        assert _is_yield_question("Why are yields moving right now?", _yield_evidence())

    def test_bond_rates_going_up(self):
        assert _is_yield_question("Why are bond rates going up?", _yield_evidence())

    def test_non_yield_question(self):
        assert not _is_yield_question("How does AI affect productivity?", [])

    def test_inflation_question_not_yield(self):
        ev = [_ev(title="CPI — All Urban Consumers: 315.0 (as of 2024-03-01)")]
        assert not _is_yield_question("Why is inflation so high?", ev)


# ── _enforce_evidence_usage ────────────────────────────────────────────────────

class TestEnforceEvidenceUsage:
    """Post-generation quality guard correctness."""

    def test_answer_with_10yr_treasury_passes(self):
        """Answer that mentions 10-year Treasury must pass unchanged."""
        ans = _make_answer(
            "Treasury yields are rising because the 10-year Treasury yield has climbed "
            "to 4.6% following stronger-than-expected jobs data."
        )
        result = _enforce_evidence_usage("Why are yields rising today?", _yield_evidence(), ans)
        assert result.answer == ans.answer

    def test_answer_with_2yr_treasury_passes(self):
        ans = _make_answer("The 2-year Treasury yield rose sharply after the CPI print.")
        result = _enforce_evidence_usage("Why are yields rising?", _yield_evidence(), ans)
        assert result.answer == ans.answer

    def test_answer_with_yield_curve_passes(self):
        ans = _make_answer("The yield curve has inverted, signalling recession risk.")
        result = _enforce_evidence_usage("What does the yield curve mean?", _yield_evidence(), ans)
        assert result.answer == ans.answer

    def test_answer_with_fed_funds_passes(self):
        ans = _make_answer("The Fed funds rate is the key lever for controlling inflation.")
        result = _enforce_evidence_usage("How does the Fed control rates?", [_ev()], ans)
        assert result.answer == ans.answer

    def test_answer_with_cpi_passes(self):
        ans = _make_answer("CPI came in above expectations, pushing yields higher.")
        result = _enforce_evidence_usage("Why are yields rising today?", [_ev()], ans)
        assert result.answer == ans.answer

    def test_answer_with_unemployment_passes(self):
        ans = _make_answer("The unemployment rate dropped to 3.7%, keeping the Fed on hold.")
        result = _enforce_evidence_usage("What drives the economy?", [_ev()], ans)
        assert result.answer == ans.answer

    def test_answer_with_gdp_passes(self):
        ans = _make_answer("GDP growth slowed to 1.2% in Q1, raising recession concerns.")
        result = _enforce_evidence_usage("Is a recession coming?", [_ev()], ans)
        assert result.answer == ans.answer

    def test_generic_yield_answer_replaced_with_yield_fallback(self):
        """Generic bond-yield explanation with no evidence terms → yield fallback."""
        generic = _make_answer(
            "Bond yields rise when investors expect higher inflation or stronger economic "
            "growth. This is because bond prices and yields move in opposite directions — "
            "when demand for bonds falls, prices drop and yields rise."
        )
        result = _enforce_evidence_usage(
            "Why are Treasury yields rising today?", _yield_evidence(), generic
        )
        assert result.answer != generic.answer
        assert result.answer == _YIELD_FALLBACK_ANSWER

    def test_yield_fallback_contains_10yr_treasury(self):
        """The yield fallback must name the 10-year Treasury yield."""
        assert "10-year Treasury yield" in _YIELD_FALLBACK_ANSWER

    def test_yield_fallback_contains_2yr_treasury(self):
        assert "2-year Treasury yield" in _YIELD_FALLBACK_ANSWER

    def test_yield_fallback_contains_yield_curve(self):
        assert "yield curve" in _YIELD_FALLBACK_ANSWER

    def test_generic_non_yield_answer_replaced_with_generic_fallback(self):
        """Generic answer for a non-yield question → generic fallback, not yield fallback."""
        inflation_ev = [
            _ev(
                title="CPI — All Urban Consumers: 315.0 (as of 2024-03-01)",
                relevance_score=0.95,
            )
        ]
        generic = _make_answer(
            "Inflation is the rate at which the general level of prices rises. "
            "When inflation goes up, each unit of currency buys fewer goods."
        )
        result = _enforce_evidence_usage("How does inflation affect markets?", inflation_ev, generic)
        assert result.answer != generic.answer
        assert result.answer == _GENERIC_EVIDENCE_FALLBACK

    def test_no_evidence_answer_never_replaced(self):
        """When evidence list is empty the guard must never alter the answer."""
        generic = _make_answer(
            "Bond yields rise when investors expect higher inflation. "
            "This is a well-established relationship in fixed income markets."
        )
        result = _enforce_evidence_usage("Why are yields rising?", [], generic)
        assert result.answer == generic.answer

    def test_bullets_preserved_after_fallback(self):
        """Original bullets must survive the fallback replacement."""
        generic = _make_answer(
            "Bond yields rise when inflation rises. "
            "This is because bond prices and yields move inversely."
        )
        result = _enforce_evidence_usage(
            "Why are Treasury yields rising today?", _yield_evidence(), generic
        )
        assert result.bullets == generic.bullets

    def test_caveats_preserved_after_fallback(self):
        """Original caveats must survive the fallback replacement."""
        generic = _make_answer(
            "Bond yields rise when inflation rises. "
            "This is because bond prices and yields move inversely."
        )
        result = _enforce_evidence_usage(
            "Why are Treasury yields rising today?", _yield_evidence(), generic
        )
        assert result.caveats == generic.caveats

    def test_case_insensitive_term_detection(self):
        """Evidence term check must be case-insensitive."""
        ans = _make_answer(
            "The 10-YEAR TREASURY yield has been climbing on rate expectations."
        )
        result = _enforce_evidence_usage("Why are yields rising?", _yield_evidence(), ans)
        assert result.answer == ans.answer  # should pass — term detected despite uppercase

    def test_yields_rising_today_canonical(self):
        """'Why are Treasury yields rising today?' with generic answer → yield fallback."""
        generic = _make_answer(
            "Treasury yields and stock market performance are closely linked. "
            "Rising yields typically pressure equity valuations."
        )
        result = _enforce_evidence_usage(
            "Why are Treasury yields rising today?", _yield_evidence(), generic
        )
        assert result.answer == _YIELD_FALLBACK_ANSWER

    def test_10yr_treasury_rising_canonical(self):
        """'Why is the 10-year Treasury yield rising?' with generic answer → yield fallback."""
        generic = _make_answer(
            "Interest rates and bond yields are related concepts in fixed income. "
            "When rates go up, bond prices decline and yields rise accordingly."
        )
        result = _enforce_evidence_usage(
            "Why is the 10-year Treasury yield rising?", _yield_evidence(), generic
        )
        assert result.answer == _YIELD_FALLBACK_ANSWER

    def test_yields_moving_right_now_canonical(self):
        """'Why are yields moving right now?' with generic answer → yield fallback."""
        generic = _make_answer(
            "Bond market dynamics are driven by supply and demand. "
            "Government borrowing needs and investor appetite for safety both play a role."
        )
        result = _enforce_evidence_usage(
            "Why are yields moving right now?", _yield_evidence(), generic
        )
        assert result.answer == _YIELD_FALLBACK_ANSWER


# ── Integration: prompt + guard together ──────────────────────────────────────

class TestEvidenceFirstIntegration:
    """Verify that the combined prompt + guard system produces evidence-grounded output."""

    def test_yield_fallback_answer_passes_its_own_guard(self):
        """The yield fallback answer itself must contain evidence terms (self-consistent)."""
        answer_lower = _YIELD_FALLBACK_ANSWER.lower()
        assert any(term in answer_lower for term in _EVIDENCE_TERMS)

    def test_generic_fallback_answer_passes_its_own_guard(self):
        """The generic fallback answer itself must contain evidence terms."""
        answer_lower = _GENERIC_EVIDENCE_FALLBACK.lower()
        assert any(term in answer_lower for term in _EVIDENCE_TERMS)

    def test_no_evidence_prompt_still_complete(self):
        """Without evidence the finance prompt is still complete and usable."""
        p = general_finance_prompt("Why are yields rising?")
        assert "USER QUESTION" in p
        assert "Why are yields rising?" in p
        assert "answer" in p.lower()
        assert "bullets" in p.lower()

    def test_no_evidence_fallback_prompt_still_complete(self):
        """Without evidence the fallback prompt is still complete and usable."""
        p = general_fallback_prompt("How does AI affect productivity?")
        assert "USER QUESTION" in p
        assert "How does AI affect productivity?" in p
        assert "answer" in p.lower()
        assert "bullets" in p.lower()

    def test_today_question_no_evidence_has_no_synthesis_rules(self):
        """Without evidence a temporal question must not get synthesis or guard rules."""
        p = general_finance_prompt("Why are yields rising today?", evidence=None)
        assert "SYNTHESIS REQUIREMENTS" not in p
        assert "QUALITY GUARD" not in p
        assert "FIRST SENTENCE RULE" not in p
        assert "HARD RULE" not in p

    def test_evidence_terms_frozenset_covers_required_terms(self):
        """_EVIDENCE_TERMS must cover each term named in the requirements."""
        required = [
            "10-year treasury",
            "2-year treasury",
            "yield curve",
            "fed funds",
            "cpi",
            "unemployment",
            "gdp",
        ]
        for term in required:
            assert term in _EVIDENCE_TERMS, (
                f"Required evidence term {term!r} missing from _EVIDENCE_TERMS"
            )
