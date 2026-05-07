"""
Tests for the general finance evidence retrieval and injection pipeline.

Coverage:
  - RetrievedEvidence schema validation
  - retrieve_general_finance_evidence() returns [] (safe default)
  - _mock_evidence_for_question() returns structurally correct objects
    for all four documented test cases
  - _format_evidence_section() renders evidence into a prompt-ready string
  - general_finance_prompt() and general_fallback_prompt() include the
    evidence section when evidence is provided and omit it when absent
  - run_general_finance_agent() and run_general_fallback_agent() call
    retrieval, inject evidence, and return valid GeneralFinanceAnswer
  - Evidence retrieval failure is handled gracefully (answer still returns)

Test questions (from spec):
  - "Why are Treasury yields rising?"
  - "Why did tech stocks sell off today?"
  - "How does CPI affect rate expectations?"
  - "Why is Nvidia moving after earnings?"
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, List

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas import RetrievedEvidence, GeneralFinanceAnswer
from app.services.general_finance_evidence import (
    retrieve_general_finance_evidence,
    _mock_evidence_for_question,
)
from app.prompts import (
    _format_evidence_section,
    general_finance_prompt,
    general_fallback_prompt,
)


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_evidence(
    title: str = "Test Headline",
    source: str = "Test Source",
    summary: str = "Test summary of one or two sentences.",
    timestamp: str = "2024-01-15",
    relevance_score: float = 0.90,
) -> RetrievedEvidence:
    return RetrievedEvidence(
        title=title,
        source=source,
        summary=summary,
        timestamp=timestamp,
        relevance_score=relevance_score,
    )


# ── RetrievedEvidence schema ──────────────────────────────────────────────────

class TestRetrievedEvidenceSchema:

    def test_valid_construction(self):
        ev = _make_evidence()
        assert ev.title == "Test Headline"
        assert ev.source == "Test Source"
        assert ev.relevance_score == 0.90

    def test_default_relevance_score(self):
        ev = RetrievedEvidence(
            title="T", source="S", summary="Sum.", timestamp="2024-01-01"
        )
        assert ev.relevance_score == 1.0

    def test_relevance_score_bounds(self):
        # Import from pydantic_core directly — other test modules stub
        # sys.modules["pydantic"].ValidationError with a fake class at collection
        # time, causing a from-pydantic import to miss the real exception.
        # pydantic_core is never stubbed, so this import is always the real class.
        import pydantic_core
        with pytest.raises(pydantic_core.ValidationError):
            RetrievedEvidence(
                title="T", source="S", summary="Sum.", timestamp="2024-01-01",
                relevance_score=1.5,
            )
        with pytest.raises(pydantic_core.ValidationError):
            RetrievedEvidence(
                title="T", source="S", summary="Sum.", timestamp="2024-01-01",
                relevance_score=-0.1,
            )

    def test_serialization(self):
        ev = _make_evidence()
        try:
            d = ev.model_dump()
        except AttributeError:
            d = ev.dict()
        assert set(d.keys()) == {"title", "source", "summary", "timestamp", "relevance_score"}


# ── retrieve_general_finance_evidence (production stub) ──────────────────────

class TestRetrieveGeneralFinanceEvidence:
    """Production function returns empty list until live providers are wired in."""

    def test_returns_list(self):
        result = retrieve_general_finance_evidence("Why are Treasury yields rising?")
        assert isinstance(result, list)

    def test_returns_empty_by_default(self):
        """Safe default: no evidence until a live provider is connected."""
        result = retrieve_general_finance_evidence("any question at all")
        assert result == []

    def test_all_four_spec_questions_return_list(self):
        questions = [
            "Why are Treasury yields rising?",
            "Why did tech stocks sell off today?",
            "How does CPI affect rate expectations?",
            "Why is Nvidia moving after earnings?",
        ]
        for q in questions:
            result = retrieve_general_finance_evidence(q)
            assert isinstance(result, list), f"Expected list for: {q}"


# ── _mock_evidence_for_question (test helper) ─────────────────────────────────

class TestMockEvidenceForQuestion:
    """The four spec examples return correctly structured mock evidence."""

    @pytest.mark.parametrize("question,expected_count", [
        ("Why are Treasury yields rising?", 2),
        ("Why did tech stocks sell off today?", 2),
        ("How does CPI affect rate expectations?", 2),
        ("Why is Nvidia moving after earnings?", 2),
    ])
    def test_returns_correct_count(self, question, expected_count):
        result = _mock_evidence_for_question(question)
        assert len(result) == expected_count, (
            f"Expected {expected_count} evidence items for: {question!r}, got {len(result)}"
        )

    @pytest.mark.parametrize("question", [
        "Why are Treasury yields rising?",
        "Why did tech stocks sell off today?",
        "How does CPI affect rate expectations?",
        "Why is Nvidia moving after earnings?",
    ])
    def test_returns_retrieved_evidence_instances(self, question):
        items = _mock_evidence_for_question(question)
        for item in items:
            assert isinstance(item, RetrievedEvidence), (
                f"Item is {type(item)}, expected RetrievedEvidence"
            )

    @pytest.mark.parametrize("question", [
        "Why are Treasury yields rising?",
        "Why did tech stocks sell off today?",
        "How does CPI affect rate expectations?",
        "Why is Nvidia moving after earnings?",
    ])
    def test_all_fields_non_empty(self, question):
        for ev in _mock_evidence_for_question(question):
            assert ev.title.strip(), f"Empty title in evidence for: {question!r}"
            assert ev.source.strip(), f"Empty source in evidence for: {question!r}"
            assert ev.summary.strip(), f"Empty summary in evidence for: {question!r}"
            assert ev.timestamp.strip(), f"Empty timestamp in evidence for: {question!r}"
            assert 0.0 <= ev.relevance_score <= 1.0

    def test_sorted_by_relevance(self):
        """Items should be returnable sorted highest-relevance first."""
        items = _mock_evidence_for_question("Why are Treasury yields rising?")
        scores = [e.relevance_score for e in items]
        assert scores == sorted(scores, reverse=True), (
            "Expected items in descending relevance order"
        )

    def test_no_match_returns_empty(self):
        result = _mock_evidence_for_question("What is the capital of France?")
        assert result == []


# ── _format_evidence_section ──────────────────────────────────────────────────

class TestFormatEvidenceSection:

    def test_empty_input_returns_empty_string(self):
        assert _format_evidence_section(None) == ""
        assert _format_evidence_section([]) == ""

    def test_contains_section_header(self):
        ev = [_make_evidence(title="Rate Expectations Shift After CPI")]
        result = _format_evidence_section(ev)
        assert "CURRENT CONTEXT" in result

    def test_contains_evidence_title(self):
        ev = [_make_evidence(title="10-Year Yield Climbs to 4.8%")]
        result = _format_evidence_section(ev)
        assert "10-Year Yield Climbs to 4.8%" in result

    def test_contains_evidence_summary(self):
        ev = [_make_evidence(summary="The yield rose after jobs data beat estimates.")]
        result = _format_evidence_section(ev)
        assert "The yield rose after jobs data beat estimates." in result

    def test_contains_source_and_timestamp(self):
        ev = [_make_evidence(source="Bloomberg [mock]", timestamp="2024-01-15")]
        result = _format_evidence_section(ev)
        assert "Bloomberg [mock]" in result
        assert "2024-01-15" in result

    def test_multiple_items_numbered(self):
        ev = [
            _make_evidence(title="First item", relevance_score=0.95),
            _make_evidence(title="Second item", relevance_score=0.80),
        ]
        result = _format_evidence_section(ev)
        assert "[1]" in result
        assert "[2]" in result

    def test_sorted_by_relevance_descending(self):
        low = _make_evidence(title="Low relevance", relevance_score=0.40)
        high = _make_evidence(title="High relevance", relevance_score=0.95)
        # Pass low before high — should be reordered
        result = _format_evidence_section([low, high])
        assert result.index("High relevance") < result.index("Low relevance")

    def test_contains_synthesis_instruction(self):
        ev = [_make_evidence()]
        result = _format_evidence_section(ev)
        assert "specific" in result.lower() or "current" in result.lower()


# ── general_finance_prompt evidence injection ─────────────────────────────────

class TestGeneralFinancePromptEvidenceInjection:

    def test_no_evidence_no_context_section(self):
        prompt = general_finance_prompt("Why are Treasury yields rising?")
        assert "CURRENT CONTEXT" not in prompt

    def test_empty_list_no_context_section(self):
        prompt = general_finance_prompt("Why are Treasury yields rising?", evidence=[])
        assert "CURRENT CONTEXT" not in prompt

    def test_evidence_injects_context_section(self):
        ev = [_make_evidence(title="Fed Holds Rates at 5.25%")]
        prompt = general_finance_prompt("Why are Treasury yields rising?", evidence=ev)
        assert "CURRENT CONTEXT" in prompt
        assert "Fed Holds Rates at 5.25%" in prompt

    def test_evidence_appears_before_user_question(self):
        ev = [_make_evidence(title="Yield Curve Inverts")]
        prompt = general_finance_prompt("Why are Treasury yields rising?", evidence=ev)
        context_pos = prompt.index("CURRENT CONTEXT")
        question_pos = prompt.index("USER QUESTION")
        assert context_pos < question_pos

    def test_question_preserved_in_prompt(self):
        prompt = general_finance_prompt("Why are Treasury yields rising?")
        assert "Why are Treasury yields rising?" in prompt

    def test_intent_still_works_with_evidence(self):
        ev = [_make_evidence()]
        prompt = general_finance_prompt(
            "Why are Treasury yields rising?",
            intent="market_question",
            evidence=ev,
        )
        assert "CURRENT CONTEXT" in prompt
        assert "Why are Treasury yields rising?" in prompt


# ── general_fallback_prompt evidence injection ────────────────────────────────

class TestGeneralFallbackPromptEvidenceInjection:

    def test_no_evidence_no_context_section(self):
        prompt = general_fallback_prompt("How does AI affect productivity?")
        assert "CURRENT CONTEXT" not in prompt

    def test_evidence_injects_context_section(self):
        ev = [_make_evidence(title="AI Productivity Gains Confirmed by OECD Study")]
        prompt = general_fallback_prompt("How does AI affect productivity?", evidence=ev)
        assert "CURRENT CONTEXT" in prompt
        assert "AI Productivity Gains Confirmed by OECD Study" in prompt

    def test_evidence_before_user_question(self):
        ev = [_make_evidence()]
        prompt = general_fallback_prompt("How does AI affect productivity?", evidence=ev)
        assert prompt.index("CURRENT CONTEXT") < prompt.index("USER QUESTION")


# ── run_general_finance_agent evidence pipeline ───────────────────────────────

class TestRunGeneralFinanceAgentEvidencePipeline:
    """End-to-end: retrieval → injection → LLM call → GeneralFinanceAnswer."""

    def _good_json(self, answer: str = "Treasury yields rise when bond prices fall.") -> str:
        return json.dumps({
            "answer": answer,
            "bullets": ["Bullet one.", "Bullet two.", "Bullet three."],
            "caveats": ["Caveat one.", "Caveat two."],
        })

    def test_agent_calls_retrieval_and_injects(self, monkeypatch):
        """Agent calls retrieve_general_finance_evidence and passes result to prompt."""
        from app import agents as ag

        retrieved = _mock_evidence_for_question("Why are Treasury yields rising?")
        injected_evidence = {}

        def fake_retrieve(question):
            return retrieved

        original_prompt_fn = general_finance_prompt

        def capturing_prompt(question, intent=None, evidence=None):
            injected_evidence["evidence"] = evidence
            return original_prompt_fn(question, intent=intent, evidence=evidence)

        class StubClient:
            def call(self, prompt: str, **kwargs: Any) -> str:
                return self._good_json()

            def _good_json(self):
                return json.dumps({
                    "answer": "Treasury yields rise when the Fed signals fewer rate cuts.",
                    "bullets": ["B1.", "B2.", "B3."],
                    "caveats": ["C1.", "C2."],
                })

        monkeypatch.setattr(ag, "retrieve_general_finance_evidence", fake_retrieve)
        monkeypatch.setattr(ag, "general_finance_prompt", capturing_prompt)
        monkeypatch.setattr(ag, "model_client", StubClient())

        ag.run_general_finance_agent("Why are Treasury yields rising?")

        assert injected_evidence.get("evidence") is not None
        assert len(injected_evidence["evidence"]) == len(retrieved)

    def test_agent_continues_without_evidence_on_retrieval_error(self, monkeypatch):
        """If retrieve raises, agent continues without evidence — no crash."""
        from app import agents as ag

        def failing_retrieve(question):
            raise RuntimeError("provider unavailable")

        class StubClient:
            def call(self, prompt: str, **kwargs: Any) -> str:
                return json.dumps({
                    "answer": "Yields rise when inflation expectations increase.",
                    "bullets": ["B1.", "B2.", "B3."],
                    "caveats": ["C1.", "C2."],
                })

        monkeypatch.setattr(ag, "retrieve_general_finance_evidence", failing_retrieve)
        monkeypatch.setattr(ag, "model_client", StubClient())

        result = ag.run_general_finance_agent("Why are Treasury yields rising?")
        assert isinstance(result, GeneralFinanceAnswer)
        assert result.answer != ""

    def test_agent_returns_valid_answer_for_all_four_spec_questions(self, monkeypatch):
        """All four spec questions produce a non-empty GeneralFinanceAnswer."""
        from app import agents as ag

        def fake_retrieve(question):
            return _mock_evidence_for_question(question)

        call_count = {"n": 0}

        class StubClient:
            def call(self, prompt: str, **kwargs: Any) -> str:
                call_count["n"] += 1
                return json.dumps({
                    "answer": "Direct answer to the question with at least two sentences here.",
                    "bullets": ["B1.", "B2.", "B3."],
                    "caveats": ["C1.", "C2."],
                })

        monkeypatch.setattr(ag, "retrieve_general_finance_evidence", fake_retrieve)
        monkeypatch.setattr(ag, "model_client", StubClient())

        questions = [
            "Why are Treasury yields rising?",
            "Why did tech stocks sell off today?",
            "How does CPI affect rate expectations?",
            "Why is Nvidia moving after earnings?",
        ]
        for q in questions:
            result = ag.run_general_finance_agent(q)
            assert isinstance(result, GeneralFinanceAnswer), f"Expected GeneralFinanceAnswer for: {q}"
            assert result.answer != "", f"Empty answer for: {q}"

        assert call_count["n"] == len(questions)


# ── run_general_fallback_agent evidence pipeline ──────────────────────────────

class TestRunGeneralFallbackAgentEvidencePipeline:

    def test_fallback_agent_retrieves_and_injects(self, monkeypatch):
        from app import agents as ag

        retrieved = [_make_evidence(title="AI Adoption Accelerates")]
        injected = {}

        def fake_retrieve(question):
            return retrieved

        original = general_fallback_prompt

        def capturing_prompt(question, evidence=None):
            injected["evidence"] = evidence
            return original(question, evidence=evidence)

        class StubClient:
            def call(self, prompt: str, **kwargs: Any) -> str:
                return json.dumps({
                    "answer": "AI raises productivity by automating repetitive tasks.",
                    "bullets": ["B1.", "B2.", "B3."],
                    "caveats": ["C1.", "C2."],
                })

        monkeypatch.setattr(ag, "retrieve_general_finance_evidence", fake_retrieve)
        monkeypatch.setattr(ag, "general_fallback_prompt", capturing_prompt)
        monkeypatch.setattr(ag, "model_client", StubClient())

        ag.run_general_fallback_agent("How does AI affect productivity?")

        assert injected.get("evidence") == retrieved

    def test_fallback_agent_continues_on_retrieval_error(self, monkeypatch):
        from app import agents as ag

        def failing_retrieve(question):
            raise ConnectionError("network timeout")

        class StubClient:
            def call(self, prompt: str, **kwargs: Any) -> str:
                return json.dumps({
                    "answer": "AI raises productivity through automation of knowledge work.",
                    "bullets": ["B1.", "B2.", "B3."],
                    "caveats": ["C1.", "C2."],
                })

        monkeypatch.setattr(ag, "retrieve_general_finance_evidence", failing_retrieve)
        monkeypatch.setattr(ag, "model_client", StubClient())

        result = ag.run_general_fallback_agent("How does AI affect productivity?")
        assert isinstance(result, GeneralFinanceAnswer)
        assert result.answer != ""
