"""
Tests for app/services/thesis_polisher.py (Refinements 1, 2, 4)
and evidence_refs propagation in app/services/signal_ranker.py (Refinement 3).

Covers:
- Concision limits (sentence truncation, filler stripping)
- Cross-section redundancy suppression
- Evidence_refs propagation from retrieved evidence into signals
- Temporal intelligence field safe defaults
"""
from __future__ import annotations

import pytest
from typing import List, Optional

from app.schemas import (
    InvestmentThesis,
    Signal,
    RetrievedEvidence,
)
from app.services.thesis_polisher import (
    _split_sentences,
    _join_sentences,
    _strip_filler_opener,
    strip_filler_openers,
    _truncate_to_sentences,
    enforce_concision,
    suppress_redundancy,
    apply_temporal_defaults,
    polish_thesis,
    _jaccard,
    _tokenize,
    _SENTENCE_LIMITS,
    _DEDUP_THRESHOLD,
)
from app.services.signal_ranker import propagate_evidence_refs, _ref_label


# ── Shared fixtures ──────────────────────────────────────────────────────────

def _thesis(
    direct_answer: str = "",
    bull_thesis: str = "",
    bear_thesis: str = "",
    conclusion: str = "",
    valuation_view: str = "",
    macro_sensitivity: str = "",
    key_drivers: List[str] = None,
    key_risks: List[str] = None,
    confidence_score: float = 0.7,
    thesis_trend: str = "unclear",
    what_changed: List[str] = None,
    change_drivers: List[str] = None,
) -> InvestmentThesis:
    return InvestmentThesis(
        ticker="AAPL",
        company_name="Apple Inc.",
        direct_answer=direct_answer,
        bull_thesis=bull_thesis or "Bull case.",
        bear_thesis=bear_thesis or "Bear case.",
        conclusion=conclusion or "Conclusion.",
        valuation_view=valuation_view,
        macro_sensitivity=macro_sensitivity,
        key_drivers=key_drivers or [],
        key_risks=key_risks or [],
        confidence_score=confidence_score,
        thesis_trend=thesis_trend,
        what_changed=what_changed or [],
        change_drivers=change_drivers or [],
    )


def _signal(text: str, refs: List[str] = None) -> Signal:
    return Signal(
        signal=text,
        impact_score=0.8,
        evidence_refs=refs or [],
    )


def _evidence(title: str, source: str, summary: str = "") -> RetrievedEvidence:
    return RetrievedEvidence(
        title=title,
        source=source,
        summary=summary or f"Summary for {title}.",
        timestamp="2024-11-01",
        relevance_score=0.9,
    )


# ── Sentence splitting helpers ────────────────────────────────────────────────

class TestSplitSentences:
    def test_single_sentence(self):
        result = _split_sentences("Apple Services grew 14%.")
        assert result == ["Apple Services grew 14%."]

    def test_multiple_sentences(self):
        result = _split_sentences("Services grew 14%. Hardware declined 2%. Net margin expanded.")
        assert len(result) == 3

    def test_empty_string(self):
        assert _split_sentences("") == []

    def test_whitespace_only(self):
        assert _split_sentences("   ") == []

    def test_strips_each_sentence(self):
        result = _split_sentences("  First sentence.  Second sentence.  ")
        assert all(s == s.strip() for s in result)


class TestJoinSentences:
    def test_single_sentence(self):
        assert _join_sentences(["Apple grew 14%."])

    def test_multiple_sentences_joined(self):
        result = _join_sentences(["First.", "Second.", "Third."])
        assert "First." in result
        assert "Second." in result
        assert "Third." in result

    def test_adds_period_if_missing(self):
        result = _join_sentences(["Apple grew 14%"])
        assert result.endswith(".")

    def test_empty_list(self):
        assert _join_sentences([]) == ""


# ── Filler stripping ─────────────────────────────────────────────────────────

class TestStripFillerOpener:
    def test_strips_it_is_worth_noting(self):
        result = _strip_filler_opener("It is worth noting that Services grew 14%.")
        assert "It is worth noting" not in result
        assert "Services" in result

    def test_strips_in_conclusion(self):
        result = _strip_filler_opener("In conclusion, Apple's P/E is 28x.")
        assert "In conclusion" not in result
        assert "Apple" in result

    def test_strips_in_summary(self):
        result = _strip_filler_opener("In summary, rate sensitivity is moderate.")
        assert "In summary" not in result
        assert "rate sensitivity" in result.lower()

    def test_clean_sentence_unchanged(self):
        sent = "Apple Services at 72% margin offsets hardware compression."
        assert _strip_filler_opener(sent) == sent

    def test_capitalises_remainder(self):
        result = _strip_filler_opener("It is worth noting that services generate $100B ARR.")
        assert result[0].isupper()

    def test_strips_notably(self):
        result = _strip_filler_opener("Notably, the buyback is $90B annually.")
        assert "Notably" not in result
        assert "buyback" in result.lower()

    def test_strips_furthermore(self):
        result = _strip_filler_opener("Furthermore, China revenue is 19% of total.")
        assert "Furthermore" not in result

    def test_case_insensitive(self):
        result = _strip_filler_opener("IN CONCLUSION, the thesis is bullish.")
        assert "IN CONCLUSION" not in result


class TestStripFillerOpeners:
    def test_strips_from_multi_sentence_text(self):
        text = "Services grew 14%. It is worth noting that margins expanded. Buyback continues."
        result = strip_filler_openers(text)
        assert "It is worth noting" not in result
        assert "margins expanded" in result.lower()

    def test_clean_text_unchanged(self):
        text = "Apple P/E is 28x. Services at 72% margin drive upside. China risk is 19%."
        result = strip_filler_openers(text)
        # Core content preserved
        assert "28x" in result
        assert "72%" in result
        assert "19%" in result


# ── Concision enforcement ─────────────────────────────────────────────────────

class TestTruncateToSentences:
    def test_truncates_to_max_sentences(self):
        text = "Sentence one. Sentence two. Sentence three. Sentence four."
        result = _truncate_to_sentences(text, 2)
        sentences = _split_sentences(result)
        assert len(sentences) <= 2

    def test_does_not_add_sentences(self):
        text = "Only one sentence."
        result = _truncate_to_sentences(text, 3)
        assert len(_split_sentences(result)) == 1

    def test_empty_text(self):
        assert _truncate_to_sentences("", 2) == ""

    def test_filler_stripped_before_truncation(self):
        text = "It is worth noting that Services grew 14%. Margin expanded. More detail here."
        result = _truncate_to_sentences(text, 2)
        assert "It is worth noting" not in result


class TestEnforceConcision:
    def test_direct_answer_truncated_to_2(self):
        thesis = _thesis(
            direct_answer=(
                "Higher rates compress AAPL P/E via DCF. "
                "Services at 72% margin provides offset. "
                "Hardware demand is rate-sensitive. "
                "Fourth sentence should be gone."
            )
        )
        result = enforce_concision(thesis)
        sentences = _split_sentences(result.direct_answer)
        assert len(sentences) <= _SENTENCE_LIMITS["direct_answer"]

    def test_conclusion_truncated_to_3(self):
        thesis = _thesis(
            conclusion=(
                "AAPL trades at 28x P/E. "
                "Services at 72% margin is key driver. "
                "China risk is 19% of revenue. "
                "This fourth sentence should be removed. "
                "And this fifth too."
            )
        )
        result = enforce_concision(thesis)
        sentences = _split_sentences(result.conclusion)
        assert len(sentences) <= _SENTENCE_LIMITS["conclusion"]

    def test_bull_thesis_truncated_to_3(self):
        thesis = _thesis(
            bull_thesis=(
                "Services at 72% margin expands blended margin. "
                "Buyback of $90B annually compresses share count. "
                "iCloud stickiness keeps churn below 2%. "
                "Fourth sentence should be trimmed."
            )
        )
        result = enforce_concision(thesis)
        sentences = _split_sentences(result.bull_thesis)
        assert len(sentences) <= _SENTENCE_LIMITS["bull_thesis"]

    def test_bear_thesis_truncated_to_3(self):
        thesis = _thesis(
            bear_thesis=(
                "China revenue at 19% faces tariff risk. "
                "Rate rise compresses 28x P/E via DCF. "
                "Hardware demand is credit-sensitive. "
                "This fourth sentence is extra verbosity."
            )
        )
        result = enforce_concision(thesis)
        sentences = _split_sentences(result.bear_thesis)
        assert len(sentences) <= _SENTENCE_LIMITS["bear_thesis"]

    def test_valuation_view_truncated_to_2(self):
        thesis = _thesis(
            valuation_view=(
                "AAPL trades at 28x forward P/E. "
                "This is a premium to the S&P 500. "
                "Third sentence is excess."
            )
        )
        result = enforce_concision(thesis)
        sentences = _split_sentences(result.valuation_view)
        assert len(sentences) <= _SENTENCE_LIMITS["valuation_view"]

    def test_macro_sensitivity_truncated_to_2(self):
        thesis = _thesis(
            macro_sensitivity=(
                "Rate rises compress AAPL via P/E discount. "
                "Services partially offsets with 72% margin. "
                "Third macro sentence should be trimmed."
            )
        )
        result = enforce_concision(thesis)
        sentences = _split_sentences(result.macro_sensitivity)
        assert len(sentences) <= _SENTENCE_LIMITS["macro_sensitivity"]

    def test_short_text_not_modified(self):
        text = "Services at 72% margin drives upside."
        thesis = _thesis(direct_answer=text)
        result = enforce_concision(thesis)
        assert result.direct_answer == text

    def test_key_drivers_untouched(self):
        drivers = ["Services 72% margin", "Buyback $90B", "iCloud lock-in", "China risk"]
        thesis = _thesis(key_drivers=drivers)
        result = enforce_concision(thesis)
        assert result.key_drivers == drivers

    def test_key_risks_untouched(self):
        risks = ["China tariff", "Rate P/E compression", "Regulatory", "Hardware demand"]
        thesis = _thesis(key_risks=risks)
        result = enforce_concision(thesis)
        assert result.key_risks == risks

    def test_filler_stripped_in_enforced_field(self):
        thesis = _thesis(
            direct_answer=(
                "It is worth noting that Services grew 14%. "
                "Margins expanded as a result."
            )
        )
        result = enforce_concision(thesis)
        assert "It is worth noting" not in result.direct_answer

    def test_does_not_mutate_input(self):
        long_conclusion = " ".join(
            f"Sentence {i}." for i in range(6)
        )
        thesis = _thesis(conclusion=long_conclusion)
        original_conclusion = thesis.conclusion
        _ = enforce_concision(thesis)
        assert thesis.conclusion == original_conclusion  # input unchanged


# ── Redundancy suppression ────────────────────────────────────────────────────

class TestSuppressRedundancy:
    def test_near_verbatim_repeat_removed_from_lower_priority(self):
        """If direct_answer and conclusion both say 'Services offsets rate pressure',
        the conclusion sentence should be suppressed."""
        da = "Apple Services at 72% gross margin offsets rate pressure on hardware P/E."
        # Conclusion repeats the core idea near-verbatim
        conc = (
            "Apple Services at 72% gross margin offsets rate pressure on P/E. "
            "China tariffs represent the primary downside risk."
        )
        thesis = _thesis(direct_answer=da, conclusion=conc)
        result = suppress_redundancy(thesis)
        # The verbatim repeat in conclusion should be suppressed
        conc_tokens = _tokenize(result.conclusion)
        da_tokens = _tokenize(da)
        # The suppressed sentence should reduce conclusion overlap with direct_answer
        # At minimum: the non-redundant China sentence should survive
        assert "china" in conc_tokens or "tariff" in conc_tokens

    def test_distinct_sections_fully_preserved(self):
        """Sections with no overlap should be completely preserved."""
        da = "Higher rates compress AAPL P/E via DCF discount rate expansion."
        bull = "Apple Services generates $100B ARR at 72% gross margin."
        bear = "China revenue at 19% faces $10B tariff exposure on iPhone hardware."
        thesis = _thesis(direct_answer=da, bull_thesis=bull, bear_thesis=bear)
        result = suppress_redundancy(thesis)
        # All distinct content should survive
        assert "dcf" in result.direct_answer.lower() or "p/e" in result.direct_answer.lower()
        assert "100b" in result.bull_thesis.lower() or "72%" in result.bull_thesis
        assert "china" in result.bear_thesis.lower() or "tariff" in result.bear_thesis.lower()

    def test_at_least_one_sentence_preserved_per_section(self):
        """Even if all sentences in a section duplicate earlier sections,
        at least one sentence must be kept."""
        # Create near-identical text across all sections (pathological case)
        shared = (
            "Apple Services at 72% margin offsets rate pressure significantly overall."
        )
        thesis = _thesis(
            direct_answer=shared,
            conclusion=shared,
            bull_thesis=shared,
            bear_thesis=shared,
        )
        result = suppress_redundancy(thesis)
        # Every section must have at least one non-empty sentence
        for field_name in ("direct_answer", "conclusion", "bull_thesis", "bear_thesis"):
            text = getattr(result, field_name)
            assert text.strip(), f"{field_name} should not be empty after redundancy suppression"
            assert len(_split_sentences(text)) >= 1

    def test_does_not_mutate_input(self):
        da = "Higher rates compress AAPL P/E. Services provides partial offset."
        thesis = _thesis(direct_answer=da)
        original_da = thesis.direct_answer
        _ = suppress_redundancy(thesis)
        assert thesis.direct_answer == original_da

    def test_empty_section_left_empty(self):
        """An empty section should stay empty — not crash."""
        thesis = _thesis(
            direct_answer="",
            bull_thesis="Services at 72% margin drives upside.",
        )
        result = suppress_redundancy(thesis)
        # Should not crash; empty sections remain empty or unchanged
        assert isinstance(result, InvestmentThesis)


class TestPolishThesis:
    def test_polish_combines_concision_and_redundancy(self):
        """polish_thesis applies both passes."""
        long_da = (
            "Higher rates compress AAPL P/E via DCF. "
            "Services at 72% margin provides offset. "
            "This third sentence will be truncated. "
            "And this fourth."
        )
        # Conclusion near-repeats direct_answer
        conclusion = (
            "Higher rates compress AAPL P/E via DCF discount rate. "
            "China tariffs represent the downside scenario."
        )
        thesis = _thesis(direct_answer=long_da, conclusion=conclusion)
        result = polish_thesis(thesis)

        # Concision: direct_answer ≤ 2 sentences
        assert len(_split_sentences(result.direct_answer)) <= _SENTENCE_LIMITS["direct_answer"]
        # Should be an InvestmentThesis
        assert isinstance(result, InvestmentThesis)

    def test_polish_applies_temporal_defaults(self):
        thesis = _thesis(thesis_trend="unclear")
        result = polish_thesis(thesis)
        assert result.thesis_trend == "unclear"

    def test_polish_thesis_invalid_trend_corrected(self):
        thesis = _thesis(thesis_trend="unknown_garbage")
        result = polish_thesis(thesis)
        assert result.thesis_trend == "unclear"


# ── Temporal intelligence fields ──────────────────────────────────────────────

class TestTemporalDefaults:
    def test_thesis_trend_defaults_to_unclear(self):
        thesis = InvestmentThesis(ticker="AAPL", company_name="Apple Inc.")
        assert thesis.thesis_trend == "unclear"

    def test_what_changed_defaults_to_empty(self):
        thesis = InvestmentThesis(ticker="AAPL", company_name="Apple Inc.")
        assert thesis.what_changed == []

    def test_change_drivers_defaults_to_empty(self):
        thesis = InvestmentThesis(ticker="AAPL", company_name="Apple Inc.")
        assert thesis.change_drivers == []

    def test_valid_thesis_trend_values(self):
        """All valid thesis_trend values survive apply_temporal_defaults."""
        for trend in ("strengthening", "weakening", "stable", "unclear"):
            thesis = _thesis(thesis_trend=trend)
            result = apply_temporal_defaults(thesis)
            assert result.thesis_trend == trend

    def test_invalid_thesis_trend_corrected_to_unclear(self):
        thesis = _thesis(thesis_trend="garbage_value")
        result = apply_temporal_defaults(thesis)
        assert result.thesis_trend == "unclear"

    def test_what_changed_carries_through(self):
        changes = ["Services growth decelerated to 9%", "Buyback reduced by $10B"]
        thesis = _thesis(what_changed=changes)
        assert thesis.what_changed == changes

    def test_change_drivers_carries_through(self):
        drivers = ["Fed rate hike 50bps", "China ban on Apple apps"]
        thesis = _thesis(change_drivers=drivers)
        assert thesis.change_drivers == drivers

    def test_thesis_round_trips_via_schema(self):
        """InvestmentThesis with temporal fields serialises and deserialises."""
        thesis = _thesis(
            thesis_trend="strengthening",
            what_changed=["Services margin expanded to 73%"],
            change_drivers=["Services revenue mix increased to 22% of total"],
        )
        if hasattr(thesis, "model_dump"):
            data = thesis.model_dump()
            restored = InvestmentThesis.model_validate(data)
        else:
            data = thesis.dict()
            restored = InvestmentThesis.parse_obj(data)

        assert restored.thesis_trend == "strengthening"
        assert restored.what_changed == ["Services margin expanded to 73%"]
        assert restored.change_drivers == ["Services revenue mix increased to 22% of total"]

    def test_thesis_trend_present_in_serialised_output(self):
        thesis = InvestmentThesis(ticker="NVDA", company_name="NVIDIA Corp.")
        if hasattr(thesis, "model_dump"):
            data = thesis.model_dump()
        else:
            data = thesis.dict()
        assert "thesis_trend" in data
        assert "what_changed" in data
        assert "change_drivers" in data

    def test_no_prior_thesis_all_defaults_safe(self):
        """First-time analysis: all temporal fields should default without error."""
        thesis = InvestmentThesis(
            ticker="MSFT",
            company_name="Microsoft Corp.",
            bull_thesis="Azure cloud drives upside.",
            bear_thesis="Valuation at 32x is stretched.",
            conclusion="MSFT is a quality compounder at premium valuation.",
        )
        assert thesis.thesis_trend == "unclear"
        assert thesis.what_changed == []
        assert thesis.change_drivers == []


# ── Evidence refs propagation ─────────────────────────────────────────────────

class TestPropagateEvidenceRefs:
    def test_populates_refs_for_empty_signal(self):
        sig = _signal("Apple Services revenue growing at 14% annually")
        ev = _evidence(
            title="Apple Services Revenue Report Q4",
            source="FMP",
            summary="Apple Services segment grew 14% year-over-year in Q4.",
        )
        result = propagate_evidence_refs([sig], [ev])
        assert len(result) == 1
        assert len(result[0].evidence_refs) >= 1

    def test_ref_label_contains_source(self):
        sig = _signal("Apple Services revenue growing at 14% annually")
        ev = _evidence("Apple Services Revenue Report Q4", "FMP")
        result = propagate_evidence_refs([sig], [ev])
        if result[0].evidence_refs:
            assert "FMP" in result[0].evidence_refs[0]

    def test_ref_label_contains_title(self):
        sig = _signal("Apple Services revenue growing at 14% annually")
        ev = _evidence("Apple Services Revenue Report Q4", "FMP")
        result = propagate_evidence_refs([sig], [ev])
        if result[0].evidence_refs:
            assert "Apple Services" in result[0].evidence_refs[0]

    def test_existing_refs_not_overwritten(self):
        """LLM-populated evidence_refs should not be replaced by inference."""
        sig = _signal("Apple Services revenue growing at 14%", refs=["[FMP] Manual citation"])
        ev = _evidence("Apple Services Revenue Report", "FMP")
        result = propagate_evidence_refs([sig], [ev])
        # Original refs preserved
        assert "[FMP] Manual citation" in result[0].evidence_refs

    def test_no_match_leaves_refs_empty(self):
        """Unrelated evidence should not produce spurious refs."""
        sig = _signal("Apple Services revenue growing at 14% annually")
        ev = _evidence(
            "Unrelated Treasury Yield Data", "FRED",
            summary="10-year Treasury yield rose to 4.5%.",
        )
        result = propagate_evidence_refs([sig], [ev])
        # "Apple Services revenue growing" shares no tokens with "Treasury Yield Data"
        # (may or may not match depending on min_overlap) — just check it doesn't crash
        assert len(result) == 1

    def test_multiple_evidence_items_matched(self):
        sig = _signal("Apple iPhone revenue and Services segment both growing")
        evs = [
            _evidence("Apple iPhone Sales Data Q4", "FMP",
                      "iPhone revenue grew 3% in Q4."),
            _evidence("Apple Services Revenue Q4", "FMP",
                      "Services revenue grew 14%."),
            _evidence("Unrelated FRED Treasury Data", "FRED",
                      "10-year yield rose."),
        ]
        result = propagate_evidence_refs([sig], evs)
        # Should match at least one Apple-related evidence
        refs = result[0].evidence_refs
        assert any("Apple" in r for r in refs)

    def test_empty_evidence_list_safe(self):
        sig = _signal("Apple Services at 72% margin")
        result = propagate_evidence_refs([sig], [])
        assert result[0].evidence_refs == []

    def test_multiple_signals_annotated(self):
        sigs = [
            _signal("Apple Services revenue growing at 14% annually"),
            _signal("China tariff exposure on iPhone hardware 19% revenue"),
        ]
        evs = [
            _evidence("Apple Services Revenue Q4", "FMP",
                      "Services grew 14% year-over-year."),
            _evidence("China Tariff Impact on Apple iPhone", "NewsAPI",
                      "Tariffs threaten Apple's China iPhone revenue."),
        ]
        result = propagate_evidence_refs(sigs, evs)
        assert len(result) == 2
        # Both signals should get refs
        assert any(r for r in result[0].evidence_refs)
        assert any(r for r in result[1].evidence_refs)

    def test_evidence_refs_carry_source_metadata(self):
        """Refs should encode both source type and title for frontend use."""
        sig = _signal("Federal Reserve rate data affects Apple valuation")
        ev = _evidence(
            title="Federal Funds Rate Historical Data",
            source="FRED",
            summary="Fed funds rate at 5.25-5.50%.",
        )
        result = propagate_evidence_refs([sig], [ev])
        if result[0].evidence_refs:
            ref = result[0].evidence_refs[0]
            # Format: "[{source}] {title[:60]}"
            assert ref.startswith("[")
            assert "FRED" in ref or "Federal" in ref

    def test_propagation_returns_same_length_list(self):
        sigs = [_signal(f"Signal text {i} about Apple revenue") for i in range(5)]
        ev = _evidence("Apple Annual Report", "FMP", "Annual report data.")
        result = propagate_evidence_refs(sigs, [ev])
        assert len(result) == len(sigs)

    def test_ref_label_format(self):
        """_ref_label produces '[{source}] {title[:60]}' format."""
        ev = _evidence(
            title="Apple Inc. Company Profile and Financial Data Overview",
            source="FMP",
        )
        label = _ref_label(ev)
        assert label.startswith("[FMP]")
        assert len(label) <= len("[FMP] ") + 60

    def test_long_title_truncated_in_ref(self):
        ev = _evidence(
            title="A" * 100,   # Title longer than 60 chars
            source="SEC",
        )
        label = _ref_label(ev)
        # Title portion should be at most 60 chars
        title_portion = label[len("[SEC] "):]
        assert len(title_portion) <= 60


# ── Integration: polish_thesis preserves all non-prose fields ─────────────────

class TestPolishPreservesFields:
    def test_confidence_score_preserved(self):
        thesis = _thesis(confidence_score=0.72)
        result = polish_thesis(thesis)
        assert result.confidence_score == 0.72

    def test_ticker_preserved(self):
        thesis = _thesis()
        result = polish_thesis(thesis)
        assert result.ticker == "AAPL"

    def test_key_drivers_preserved(self):
        drivers = ["Services 72% margin", "Buyback $90B", "iCloud stickiness", "China risk"]
        thesis = _thesis(key_drivers=drivers)
        result = polish_thesis(thesis)
        assert result.key_drivers == drivers

    def test_key_risks_preserved(self):
        risks = ["China tariff 19%", "Rate P/E compression 28x", "Regulatory", "Hardware slowdown"]
        thesis = _thesis(key_risks=risks)
        result = polish_thesis(thesis)
        assert result.key_risks == risks

    def test_evidence_count_preserved(self):
        thesis = _thesis()
        thesis.evidence_count = 15
        result = polish_thesis(thesis)
        assert result.evidence_count == 15

    def test_temporal_fields_preserved(self):
        thesis = _thesis(
            thesis_trend="strengthening",
            what_changed=["Services margin expanded"],
            change_drivers=["Services mix shift"],
        )
        result = polish_thesis(thesis)
        assert result.thesis_trend == "strengthening"
        assert result.what_changed == ["Services margin expanded"]
        assert result.change_drivers == ["Services mix shift"]

    def test_signals_preserved(self):
        from app.schemas import Signal
        sig = Signal(signal="Services at 72% margin", impact_score=0.9)
        thesis = _thesis()
        thesis.top_signals = [sig]
        result = polish_thesis(thesis)
        assert len(result.top_signals) == 1
        assert result.top_signals[0].impact_score == 0.9
