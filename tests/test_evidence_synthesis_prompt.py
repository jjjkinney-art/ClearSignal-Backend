"""
Tests for evidence-grounded synthesis in general_finance_prompt and
general_fallback_prompt.

Coverage:
  _format_evidence_section
    - returns "" when no evidence
    - contains evidence title, summary, source, timestamp
    - is sorted by relevance descending
    - does NOT contain old passive "Rules for using it" language

  _evidence_synthesis_block
    - returns "" when no evidence
    - contains mandatory synthesis requirements
    - contains temporal quality guard for today/right now/currently/latest questions
    - does NOT contain quality guard for non-temporal questions
    - contains the worked Treasury-yield example
    - closes with canonical "evidence first" rule
    - covers all documented temporal markers

  general_finance_prompt with evidence
    - CURRENT CONTEXT section present
    - SYNTHESIS REQUIREMENTS section present
    - evidence section appears before USER QUESTION
    - synthesis block appears before USER QUESTION
    - synthesis block appears after evidence section
    - temporal quality guard present for "today" questions
    - temporal quality guard absent for non-temporal questions
    - question preserved in prompt

  general_finance_prompt without evidence
    - CURRENT CONTEXT absent
    - SYNTHESIS REQUIREMENTS absent
    - QUALITY GUARD absent
    - USER QUESTION still present

  general_fallback_prompt with evidence
    - same structural guarantees as general_finance_prompt

  graceful degradation
    - no evidence → prompt still complete and usable
    - empty list → same as None
"""

from __future__ import annotations

import os
import sys
from typing import List

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas import RetrievedEvidence
from app.prompts import (
    _format_evidence_section,
    _evidence_synthesis_block,
    general_finance_prompt,
    general_fallback_prompt,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _ev(
    title: str = "10-Year Treasury Rate: 4.61% (as of 2024-04-01)",
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


def _two_items() -> List[RetrievedEvidence]:
    return [
        _ev(title="DGS10: 4.61%", relevance_score=0.95),
        _ev(title="DGS2: 4.85%", relevance_score=0.88),
    ]


# ── _format_evidence_section ──────────────────────────────────────────────────

class TestFormatEvidenceSection:

    def test_none_returns_empty_string(self):
        assert _format_evidence_section(None) == ""

    def test_empty_list_returns_empty_string(self):
        assert _format_evidence_section([]) == ""

    def test_contains_current_context_header(self):
        result = _format_evidence_section([_ev()])
        assert "CURRENT CONTEXT" in result

    def test_contains_evidence_title(self):
        result = _format_evidence_section([_ev(title="10-Year Treasury Rate: 4.61%")])
        assert "10-Year Treasury Rate: 4.61%" in result

    def test_contains_evidence_summary(self):
        result = _format_evidence_section([_ev(summary="Yields are the benchmark rate.")])
        assert "Yields are the benchmark rate." in result

    def test_contains_source(self):
        result = _format_evidence_section([_ev(source="FRED")])
        assert "FRED" in result

    def test_contains_timestamp(self):
        result = _format_evidence_section([_ev(timestamp="2024-04-01")])
        assert "2024-04-01" in result

    def test_items_numbered(self):
        result = _format_evidence_section(_two_items())
        assert "[1]" in result
        assert "[2]" in result

    def test_sorted_highest_relevance_first(self):
        low = _ev(title="Low", relevance_score=0.40)
        high = _ev(title="High", relevance_score=0.95)
        result = _format_evidence_section([low, high])
        assert result.index("High") < result.index("Low")


# ── _evidence_synthesis_block ─────────────────────────────────────────────────

class TestEvidenceSynthesisBlock:

    def test_none_evidence_returns_empty(self):
        assert _evidence_synthesis_block("Any question?", None) == ""

    def test_empty_list_returns_empty(self):
        assert _evidence_synthesis_block("Any question?", []) == ""

    def test_contains_synthesis_requirements_header(self):
        result = _evidence_synthesis_block("Why are yields rising?", [_ev()])
        assert "SYNTHESIS REQUIREMENTS" in result

    def test_mandates_evidence_first(self):
        result = _evidence_synthesis_block("Why are yields rising?", [_ev()])
        assert "evidence" in result.lower() or "CURRENT CONTEXT" in result

    def test_contains_causal_chain_instruction(self):
        result = _evidence_synthesis_block("Why are yields rising?", [_ev()])
        # Should mention the causal chain: what changed → how markets responded
        lower = result.lower()
        assert "causal" in lower or "changed" in lower or "chain" in lower

    def test_contains_evidence_first_rule(self):
        """Canonical 'evidence first' rule must be present."""
        result = _evidence_synthesis_block("Why are yields rising?", [_ev()])
        assert "evidence first" in result.lower() or "answer using the evidence first" in result.lower()

    def test_contains_worked_example(self):
        result = _evidence_synthesis_block("Why are yields rising?", [_ev()])
        assert "WORKED EXAMPLE" in result or "example" in result.lower()

    def test_worked_example_contains_good_answer_template(self):
        """The worked example shows the correct evidence-first pattern."""
        result = _evidence_synthesis_block("Why are yields rising?", [_ev()])
        # Should contain an example of a good answer mentioning Fed/rate cuts
        assert "rate cut" in result.lower() or "federal reserve" in result.lower()

    def test_temporal_today_triggers_quality_guard(self):
        result = _evidence_synthesis_block("Why are yields rising today?", [_ev()])
        assert "QUALITY GUARD" in result

    def test_temporal_right_now_triggers_quality_guard(self):
        result = _evidence_synthesis_block("What is happening right now with yields?", [_ev()])
        assert "QUALITY GUARD" in result

    def test_temporal_currently_triggers_quality_guard(self):
        result = _evidence_synthesis_block("Why are yields currently elevated?", [_ev()])
        assert "QUALITY GUARD" in result

    def test_temporal_latest_triggers_quality_guard(self):
        result = _evidence_synthesis_block("What is the latest on Treasury yields?", [_ev()])
        assert "QUALITY GUARD" in result

    def test_temporal_this_week_triggers_quality_guard(self):
        result = _evidence_synthesis_block("Why are yields rising this week?", [_ev()])
        assert "QUALITY GUARD" in result

    def test_non_temporal_no_quality_guard(self):
        """Generic questions without temporal markers must NOT get the quality guard."""
        result = _evidence_synthesis_block("How do bond yields affect stocks?", [_ev()])
        assert "QUALITY GUARD" not in result

    def test_non_temporal_still_has_synthesis_rules(self):
        result = _evidence_synthesis_block("How do bond yields affect stocks?", [_ev()])
        assert "SYNTHESIS REQUIREMENTS" in result

    def test_case_insensitive_temporal_detection(self):
        result = _evidence_synthesis_block("Why Are Yields Rising TODAY?", [_ev()])
        assert "QUALITY GUARD" in result

    def test_synthesis_block_contains_bad_answer_anti_pattern(self):
        """Should show what NOT to do (bad answer pattern)."""
        result = _evidence_synthesis_block("Why are yields rising today?", [_ev()])
        lower = result.lower()
        assert "bad" in lower or "reject" in lower or "bad answer" in lower

    def test_synthesis_block_does_not_contain_old_passive_rules(self):
        """Old 'Rules for using it' language should be gone."""
        result = _evidence_synthesis_block("Why are yields rising?", [_ev()])
        assert "Rules for using it" not in result


# ── general_finance_prompt with evidence ─────────────────────────────────────

class TestGeneralFinancePromptWithEvidence:

    def test_current_context_present(self):
        p = general_finance_prompt("Why are yields rising?", evidence=[_ev()])
        assert "CURRENT CONTEXT" in p

    def test_synthesis_requirements_present(self):
        p = general_finance_prompt("Why are yields rising?", evidence=[_ev()])
        assert "SYNTHESIS REQUIREMENTS" in p

    def test_evidence_section_before_user_question(self):
        p = general_finance_prompt("Why are yields rising?", evidence=[_ev()])
        assert p.index("CURRENT CONTEXT") < p.index("USER QUESTION")

    def test_synthesis_block_before_user_question(self):
        p = general_finance_prompt("Why are yields rising?", evidence=[_ev()])
        assert p.index("SYNTHESIS REQUIREMENTS") < p.index("USER QUESTION")

    def test_synthesis_block_after_evidence_section(self):
        p = general_finance_prompt("Why are yields rising?", evidence=[_ev()])
        assert p.index("CURRENT CONTEXT") < p.index("SYNTHESIS REQUIREMENTS")

    def test_today_question_has_quality_guard(self):
        p = general_finance_prompt("Why are Treasury yields rising today?", evidence=[_ev()])
        assert "QUALITY GUARD" in p

    def test_right_now_question_has_quality_guard(self):
        p = general_finance_prompt(
            "What is happening with yields right now?", evidence=[_ev()]
        )
        assert "QUALITY GUARD" in p

    def test_currently_question_has_quality_guard(self):
        p = general_finance_prompt(
            "Why are yields currently elevated?", evidence=[_ev()]
        )
        assert "QUALITY GUARD" in p

    def test_latest_question_has_quality_guard(self):
        p = general_finance_prompt(
            "What is the latest on Treasury yields?", evidence=[_ev()]
        )
        assert "QUALITY GUARD" in p

    def test_non_temporal_no_quality_guard(self):
        p = general_finance_prompt("Why do yields affect stocks?", evidence=[_ev()])
        assert "QUALITY GUARD" not in p

    def test_non_temporal_still_has_synthesis_rules(self):
        p = general_finance_prompt("Why do yields affect stocks?", evidence=[_ev()])
        assert "SYNTHESIS REQUIREMENTS" in p

    def test_question_preserved(self):
        q = "Why are Treasury yields rising today?"
        p = general_finance_prompt(q, evidence=[_ev()])
        assert q in p

    def test_evidence_title_in_prompt(self):
        p = general_finance_prompt(
            "Why are yields rising?",
            evidence=[_ev(title="10-Year Treasury Rate: 4.61% (as of 2024-04-01)")],
        )
        assert "10-Year Treasury Rate: 4.61%" in p

    def test_worked_example_in_prompt(self):
        p = general_finance_prompt("Why are yields rising today?", evidence=[_ev()])
        assert "WORKED EXAMPLE" in p or "example" in p.lower()

    def test_intent_still_works_with_evidence(self):
        p = general_finance_prompt(
            "Why are yields rising today?",
            intent="market_question",
            evidence=[_ev()],
        )
        assert "CURRENT CONTEXT" in p
        assert "SYNTHESIS REQUIREMENTS" in p
        assert "Why are yields rising today?" in p

    def test_multiple_evidence_items_all_in_prompt(self):
        items = _two_items()
        p = general_finance_prompt("Why are yields rising?", evidence=items)
        assert "DGS10" in p
        assert "DGS2" in p


# ── general_finance_prompt without evidence ───────────────────────────────────

class TestGeneralFinancePromptWithoutEvidence:

    def test_current_context_absent(self):
        p = general_finance_prompt("Why are yields rising?")
        assert "CURRENT CONTEXT" not in p

    def test_synthesis_requirements_absent(self):
        p = general_finance_prompt("Why are yields rising?")
        assert "SYNTHESIS REQUIREMENTS" not in p

    def test_quality_guard_absent(self):
        p = general_finance_prompt("Why are yields rising today?")
        assert "QUALITY GUARD" not in p

    def test_user_question_still_present(self):
        q = "Why are yields rising?"
        p = general_finance_prompt(q)
        assert "USER QUESTION" in p
        assert q in p

    def test_empty_list_same_as_none(self):
        p_none = general_finance_prompt("Why are yields rising?", evidence=None)
        p_empty = general_finance_prompt("Why are yields rising?", evidence=[])
        assert "CURRENT CONTEXT" not in p_none
        assert "CURRENT CONTEXT" not in p_empty


# ── general_fallback_prompt with evidence ─────────────────────────────────────

class TestGeneralFallbackPromptWithEvidence:

    def test_current_context_present(self):
        p = general_fallback_prompt("How does inflation affect markets?", evidence=[_ev()])
        assert "CURRENT CONTEXT" in p

    def test_synthesis_requirements_present(self):
        p = general_fallback_prompt("How does inflation affect markets?", evidence=[_ev()])
        assert "SYNTHESIS REQUIREMENTS" in p

    def test_evidence_before_user_question(self):
        p = general_fallback_prompt("How does inflation affect markets?", evidence=[_ev()])
        assert p.index("CURRENT CONTEXT") < p.index("USER QUESTION")

    def test_synthesis_before_user_question(self):
        p = general_fallback_prompt("How does inflation affect markets?", evidence=[_ev()])
        assert p.index("SYNTHESIS REQUIREMENTS") < p.index("USER QUESTION")

    def test_temporal_question_has_quality_guard(self):
        p = general_fallback_prompt(
            "How is inflation affecting markets currently?", evidence=[_ev()]
        )
        assert "QUALITY GUARD" in p

    def test_non_temporal_no_quality_guard(self):
        p = general_fallback_prompt(
            "How does inflation affect markets?", evidence=[_ev()]
        )
        assert "QUALITY GUARD" not in p

    def test_no_evidence_no_context_section(self):
        p = general_fallback_prompt("How does inflation affect markets?")
        assert "CURRENT CONTEXT" not in p

    def test_question_preserved(self):
        q = "How does inflation affect markets currently?"
        p = general_fallback_prompt(q, evidence=[_ev()])
        assert q in p


# ── Graceful degradation ──────────────────────────────────────────────────────

class TestGracefulDegradation:
    """Prompts with no evidence must still be complete and usable."""

    def test_finance_prompt_no_evidence_contains_examples(self):
        p = general_finance_prompt("Why are yields rising?")
        # Must still contain the static worked examples so the model has guidance
        assert "answer" in p.lower()
        assert "bullets" in p.lower()

    def test_fallback_prompt_no_evidence_contains_instructions(self):
        p = general_fallback_prompt("How does AI affect productivity?")
        assert "answer" in p.lower()
        assert "bullets" in p.lower()

    def test_finance_prompt_no_evidence_today_question_still_has_question(self):
        q = "Why are yields rising today?"
        p = general_finance_prompt(q)
        assert q in p
        assert "QUALITY GUARD" not in p  # no evidence → no guard

    def test_synthesis_instructions_only_appear_with_evidence(self):
        """The synthesis block must NEVER appear without evidence."""
        for q in [
            "Why are yields rising?",
            "Why are yields rising today?",
            "How does inflation affect markets currently?",
        ]:
            p_no_ev = general_finance_prompt(q, evidence=None)
            assert "SYNTHESIS REQUIREMENTS" not in p_no_ev, (
                f"SYNTHESIS REQUIREMENTS should be absent without evidence for: {q!r}"
            )
