"""
Tests for the yield-curve contradiction guard in app.agents.

The guard (_correct_yield_curve_contradiction) runs after the LLM synthesises
its answer.  It reads the slope direction that _build_t10y2y_evidence() stamped
explicitly into the T10Y2Y evidence title and replaces the answer's opening
paragraph if the LLM contradicts the evidence.

All tests operate entirely on the helper functions and the top-level guard —
no LLM or HTTP calls are made.

Coverage
--------
_read_curve_state        — extracts slope direction from evidence titles
_answer_claims_inversion — detects assertive inversion claims in answer text
_answer_claims_not_inverted — detects explicit non-inversion claims
_strip_opening_paragraph — paragraph removal strategy (blank-line / newline / sentence)
_correct_yield_curve_contradiction — end-to-end guard logic

Contradiction scenarios
-----------------------
1. Evidence NOT inverted, answer claims inversion  → corrected (main bug case)
2. Evidence INVERTED,     answer claims not_inverted → corrected
3. Evidence NOT inverted, answer agrees             → passthrough
4. Evidence INVERTED,     answer agrees             → passthrough
5. Evidence flat                                   → passthrough (ambiguous)
6. No T10Y2Y evidence                             → passthrough
7. No evidence at all                              → passthrough
8. Bullets / caveats / evidence_count preserved after correction
"""

from __future__ import annotations

import pytest
from app.agents import (
    _read_curve_state,
    _answer_claims_inversion,
    _answer_claims_not_inverted,
    _strip_opening_paragraph,
    _correct_yield_curve_contradiction,
    _CORRECTION_NOT_INVERTED,
    _CORRECTION_INVERTED,
)
from app.schemas import GeneralFinanceAnswer, RetrievedEvidence


# ── helpers ───────────────────────────────────────────────────────────────────

def _ev(title: str, summary: str = "mock summary") -> RetrievedEvidence:
    return RetrievedEvidence(
        title=title, source="FRED", summary=summary,
        timestamp="2024-11-15", relevance_score=0.92,
    )


def _t10y2y_not_inverted() -> RetrievedEvidence:
    """Evidence object with a positive T10Y2Y spread (curve NOT inverted)."""
    return _ev(
        title=(
            "10-Year Minus 2-Year Treasury Spread: +0.49 pp "
            "— yield curve is NOT inverted — positively sloped (as of 2024-11-15)"
        ),
        summary=(
            "The 2s10s spread is +0.49 pp as of 2024-11-15. "
            "The 10-year Treasury yield exceeds the 2-year Treasury yield by 0.49 pp. "
            "The curve is positively sloped and is NOT inverted."
        ),
    )


def _t10y2y_inverted() -> RetrievedEvidence:
    """Evidence object with a negative T10Y2Y spread (curve INVERTED)."""
    return _ev(
        title=(
            "10-Year Minus 2-Year Treasury Spread: -0.52 pp "
            "— yield curve is INVERTED (as of 2024-03-01)"
        ),
        summary=(
            "The 2s10s spread is -0.52 pp as of 2024-03-01. "
            "The 2-year Treasury yield exceeds the 10-year Treasury yield by 0.52 pp. "
            "The curve is inverted."
        ),
    )


def _t10y2y_flat() -> RetrievedEvidence:
    """Evidence object with zero T10Y2Y spread (flat curve)."""
    return _ev(
        title=(
            "10-Year Minus 2-Year Treasury Spread: +0.00 pp "
            "— yield curve is flat (as of 2024-06-01)"
        ),
    )


def _result(
    answer: str,
    bullets: list | None = None,
    caveats: list | None = None,
    evidence_count: int = 3,
) -> GeneralFinanceAnswer:
    return GeneralFinanceAnswer(
        answer=answer,
        bullets=bullets or ["bullet 1", "bullet 2"],
        caveats=caveats or ["caveat 1"],
        evidence_count=evidence_count,
    )


# ── _read_curve_state ─────────────────────────────────────────────────────────

class TestReadCurveState:

    def test_not_inverted_title_returns_not_inverted(self):
        ev = _t10y2y_not_inverted()
        assert _read_curve_state([ev]) == "not_inverted"

    def test_inverted_title_returns_inverted(self):
        ev = _t10y2y_inverted()
        assert _read_curve_state([ev]) == "inverted"

    def test_flat_title_returns_flat(self):
        ev = _t10y2y_flat()
        assert _read_curve_state([ev]) == "flat"

    def test_no_t10y2y_in_list_returns_none(self):
        ev = _ev("10-Year Treasury Constant Maturity Rate: 4.41% (as of 2024-11-15)")
        assert _read_curve_state([ev]) is None

    def test_empty_evidence_list_returns_none(self):
        assert _read_curve_state([]) is None

    def test_not_inverted_wins_over_other_items(self):
        """T10Y2Y not-inverted item alongside unrelated items → not_inverted."""
        ev_other = _ev("Federal Funds Rate: 5.33% (as of 2024-11-15)")
        ev_t10y2y = _t10y2y_not_inverted()
        assert _read_curve_state([ev_other, ev_t10y2y]) == "not_inverted"

    def test_inverted_item_alongside_others(self):
        ev_other = _ev("CPI — All Urban Consumers: 316.0 (as of 2024-11-15)")
        ev_t10y2y = _t10y2y_inverted()
        assert _read_curve_state([ev_other, ev_t10y2y]) == "inverted"


# ── _answer_claims_inversion ──────────────────────────────────────────────────

class TestAnswerClaimsInversion:

    def test_bare_inverted_claim(self):
        assert _answer_claims_inversion("The yield curve is inverted.") is True

    def test_currently_inverted(self):
        assert _answer_claims_inversion(
            "The yield curve is currently inverted, with 2-year yields above 10-year."
        ) is True

    def test_remains_inverted(self):
        assert _answer_claims_inversion("The curve remains inverted.") is True

    def test_with_inversion_phrasing(self):
        assert _answer_claims_inversion(
            "With the yield curve inverted, recession risk is elevated."
        ) is True

    def test_not_inverted_returns_false(self):
        """Explicit negation in the answer must suppress the inversion claim."""
        assert _answer_claims_inversion(
            "The yield curve is not inverted. The 10-year exceeds the 2-year."
        ) is False

    def test_not_currently_inverted_returns_false(self):
        assert _answer_claims_inversion(
            "The curve is not currently inverted."
        ) is False

    def test_no_longer_inverted_returns_false(self):
        assert _answer_claims_inversion(
            "The yield curve is no longer inverted."
        ) is False

    def test_positively_sloped_returns_false(self):
        assert _answer_claims_inversion(
            "The yield curve is positively sloped, not a cause for alarm."
        ) is False

    def test_no_yield_curve_mention_returns_false(self):
        assert _answer_claims_inversion("Inflation is running above 3%.") is False

    def test_historical_inversion_with_negation_returns_false(self):
        """'Not inverted unlike the 2022 inversion' — negation wins."""
        assert _answer_claims_inversion(
            "The curve is not inverted unlike when it was inverted in 2022."
        ) is False


# ── _answer_claims_not_inverted ───────────────────────────────────────────────

class TestAnswerClaimsNotInverted:

    def test_not_inverted(self):
        assert _answer_claims_not_inverted("The curve is not inverted.") is True

    def test_not_currently_inverted(self):
        assert _answer_claims_not_inverted(
            "The yield curve is not currently inverted."
        ) is True

    def test_no_longer_inverted(self):
        assert _answer_claims_not_inverted(
            "The yield curve is no longer inverted."
        ) is True

    def test_positively_sloped(self):
        assert _answer_claims_not_inverted(
            "The curve is positively sloped, so recession risk is low."
        ) is True

    def test_plain_inverted_returns_false(self):
        assert _answer_claims_not_inverted("The yield curve is inverted.") is False

    def test_no_yield_curve_mention_returns_false(self):
        assert _answer_claims_not_inverted("GDP growth is slowing.") is False


# ── _strip_opening_paragraph ──────────────────────────────────────────────────

class TestStripOpeningParagraph:

    def test_blank_line_split(self):
        answer = "First paragraph.\n\nSecond paragraph continues here."
        rest = _strip_opening_paragraph(answer)
        assert rest == "Second paragraph continues here."

    def test_single_newline_split(self):
        answer = "First line.\nSecond line continues."
        rest = _strip_opening_paragraph(answer)
        assert rest == "Second line continues."

    def test_sentence_boundary_split(self):
        answer = "The curve is inverted. This has historically signalled recession risk."
        rest = _strip_opening_paragraph(answer)
        assert rest == "This has historically signalled recession risk."

    def test_no_split_point_returns_empty(self):
        """Single-sentence answer with no break → full replacement."""
        rest = _strip_opening_paragraph("The curve is inverted.")
        assert rest == ""

    def test_blank_line_takes_priority_over_newline(self):
        answer = "Para one line A.\nPara one line B.\n\nPara two."
        rest = _strip_opening_paragraph(answer)
        assert rest == "Para two."


# ── _correct_yield_curve_contradiction (end-to-end) ──────────────────────────

class TestCorrectYieldCurveContradiction:

    # ── main bug scenario: NOT inverted evidence, inversion claim in answer ──

    def test_not_inverted_evidence_answer_claims_inversion_corrected(self):
        """The primary bug: evidence says +0.49 pp (not inverted), LLM says 'inverted'."""
        ev = _t10y2y_not_inverted()
        res = _result(
            "The yield curve is currently inverted, which is sending a clear "
            "recession signal. The 2-year yield exceeds the 10-year yield."
        )
        out = _correct_yield_curve_contradiction("Why is the yield curve inverted?", [ev], res)
        assert "not currently inverted" in out.answer.lower() or "NOT inverted" in out.answer or \
               "not inverted" in out.answer.lower()

    def test_not_inverted_correction_starts_with_prescribed_text(self):
        ev = _t10y2y_not_inverted()
        res = _result("The yield curve is inverted.")
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert out.answer.startswith(_CORRECTION_NOT_INVERTED.rstrip())

    def test_not_inverted_correction_does_not_assert_inversion(self):
        """After correction, the answer must not open by claiming inversion."""
        ev = _t10y2y_not_inverted()
        res = _result(
            "The yield curve is currently inverted. This signals recession risk."
        )
        out = _correct_yield_curve_contradiction("?", [ev], res)
        # Opening must not be an inversion claim
        assert not _answer_claims_inversion(out.answer.split(".")[0])

    # ── inverted evidence, not-inverted claim in answer ──────────────────────

    def test_inverted_evidence_answer_claims_not_inverted_corrected(self):
        ev = _t10y2y_inverted()
        res = _result(
            "The yield curve is not inverted — the 10-year yield is comfortably "
            "above the 2-year, reflecting normal term-premium dynamics."
        )
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert "inverted" in out.answer.lower()
        assert "not currently inverted" not in out.answer.lower()

    def test_inverted_correction_starts_with_prescribed_text(self):
        ev = _t10y2y_inverted()
        res = _result("The curve is positively sloped.")
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert out.answer.startswith(_CORRECTION_INVERTED.rstrip())

    # ── agreement passthrough cases ──────────────────────────────────────────

    def test_not_inverted_evidence_answer_agrees_passthrough(self):
        ev = _t10y2y_not_inverted()
        answer = (
            "The yield curve is not currently inverted. The 10-year Treasury "
            "yield at 4.41% exceeds the 2-year at 3.92%, giving a spread of +0.49 pp."
        )
        res = _result(answer)
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert out.answer == answer  # unchanged

    def test_inverted_evidence_answer_agrees_passthrough(self):
        ev = _t10y2y_inverted()
        answer = (
            "The yield curve is inverted. The 2-year Treasury yield exceeds the "
            "10-year by 0.52 pp, which has historically preceded recessions."
        )
        res = _result(answer)
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert out.answer == answer  # unchanged

    def test_positively_sloped_answer_with_not_inverted_evidence_passthrough(self):
        ev = _t10y2y_not_inverted()
        answer = "The curve is positively sloped. The 10-year exceeds the 2-year yield."
        res = _result(answer)
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert out.answer == answer

    # ── flat curve passthrough ────────────────────────────────────────────────

    def test_flat_curve_does_not_trigger_correction(self):
        """Flat is ambiguous; guard should never correct for a flat curve."""
        ev = _t10y2y_flat()
        answer = "The yield curve is flat, with 10-year and 2-year yields nearly equal."
        res = _result(answer)
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert out.answer == answer

    # ── no T10Y2Y evidence passthrough ───────────────────────────────────────

    def test_no_t10y2y_evidence_passthrough(self):
        """With only non-spread evidence, the guard must not fire."""
        ev = _ev("10-Year Treasury Constant Maturity Rate: 4.41% (as of 2024-11-15)")
        answer = "The yield curve is inverted."
        res = _result(answer)
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert out.answer == answer  # guard did not fire

    def test_empty_evidence_passthrough(self):
        answer = "The yield curve is inverted."
        res = _result(answer)
        out = _correct_yield_curve_contradiction("?", [], res)
        assert out.answer == answer

    # ── metadata preservation ─────────────────────────────────────────────────

    def test_bullets_preserved_after_correction(self):
        ev = _t10y2y_not_inverted()
        bullets = ["Yield spread: +0.49 pp", "Fed funds: 5.33%"]
        res = _result("The yield curve is inverted.", bullets=bullets)
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert out.bullets == bullets

    def test_caveats_preserved_after_correction(self):
        ev = _t10y2y_not_inverted()
        caveats = ["FRED data may lag by one business day."]
        res = _result("The yield curve is inverted.", caveats=caveats)
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert out.caveats == caveats

    def test_evidence_count_preserved_after_correction(self):
        ev = _t10y2y_not_inverted()
        res = _result("The yield curve is inverted.", evidence_count=5)
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert out.evidence_count == 5

    def test_evidence_count_preserved_on_passthrough(self):
        ev = _t10y2y_not_inverted()
        answer = "The curve is not inverted."
        res = _result(answer, evidence_count=3)
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert out.evidence_count == 3

    # ── multi-paragraph answer: only opening replaced ─────────────────────────

    def test_second_paragraph_retained_after_correction(self):
        """When the answer has multiple paragraphs, only the opening is replaced."""
        ev = _t10y2y_not_inverted()
        res = _result(
            "The yield curve is currently inverted.\n\n"
            "Looking at rate differentials, the Fed has maintained a restrictive stance."
        )
        out = _correct_yield_curve_contradiction("?", [ev], res)
        assert "Looking at rate differentials" in out.answer

    def test_single_sentence_answer_fully_replaced(self):
        """Single-sentence inversion claim with no trailing content."""
        ev = _t10y2y_not_inverted()
        res = _result("The yield curve is inverted.")
        out = _correct_yield_curve_contradiction("?", [ev], res)
        # Full replacement: answer IS the correction text
        assert out.answer == _CORRECTION_NOT_INVERTED.rstrip()

    # ── false-premise question (primary integration scenario) ─────────────────

    def test_user_asks_why_inverted_evidence_shows_positive_spread(self):
        """Reproduce the exact production scenario from the bug report.

        User: 'Why is the yield curve inverted right now?'
        Evidence: +0.49 pp → NOT inverted
        LLM (without guard): follows the false premise, says 'inverted'
        Guard: must replace opening with the deterministic correction.
        """
        ev = _t10y2y_not_inverted()
        # Simulate what the LLM produces when it follows the user's false premise
        llm_answer = (
            "The yield curve is currently inverted because the Federal Reserve "
            "has kept short-term rates elevated to combat inflation.\n\n"
            "The 2-year Treasury yield sits above the 10-year yield, compressing "
            "the spread and historically signalling recession risk."
        )
        res = _result(llm_answer, evidence_count=4)
        out = _correct_yield_curve_contradiction(
            "Why is the yield curve inverted right now?", [ev], res
        )
        # Opening must state the curve is NOT inverted
        assert "not currently inverted" in out.answer.lower() or \
               "NOT inverted" in out.answer
        # The rest of the context answer should still be present
        assert "Federal Reserve" in out.answer or "spread" in out.answer.lower()
        # Evidence count must be untouched
        assert out.evidence_count == 4
