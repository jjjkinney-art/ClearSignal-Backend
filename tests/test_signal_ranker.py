"""
Phase 7 tests — Signal Ranking Engine (app/services/signal_ranker.py)

Covers:
- Duplicate signal deduplication and merging
- Noise suppression
- Top signals ranked correctly by composite score
- Macro + valuation conflicts resolved (highest-scoring wins)
- Thesis compression quality
- Forbidden phrase detection
- Apple/rates scenario signal prioritization
"""
from __future__ import annotations

import pytest
from typing import List

from app.schemas import (
    Signal,
    ValuationView,
    MacroSensitivity,
    RiskProfile,
    MarketContext,
    QualityAssessment,
    CompressedThesis,
    InvestmentThesis,
    CompanyContext,
)
from app.services.signal_ranker import (
    RankedSignalSet,
    _jaccard,
    _tokenize,
    _are_duplicates,
    _merge,
    _score,
    _collect_signals,
    _deduplicate,
    compress_thesis,
    detect_forbidden_phrases,
    check_forbidden_phrases,
    rank_signals,
    FORBIDDEN_PHRASES,
    _TYPE_PRIORITY,
    _DIRECTION_WEIGHT,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _signal(
    text: str,
    signal_type: str = "structural",
    direction: str = "bullish",
    impact: float = 0.8,
    confidence: float = 0.8,
    source_agent: str = "valuation",
    importance_reason: str = "",
) -> Signal:
    return Signal(
        signal=text,
        impact_score=impact,
        confidence=confidence,
        signal_type=signal_type,
        direction=direction,
        source_agent=source_agent,
        importance_reason=importance_reason,
    )


def _valuation(signals: List[Signal] = None, confidence: float = 0.8) -> ValuationView:
    return ValuationView(
        overall="Valuation analysis.",
        confidence=confidence,
        signals=signals or [],
    )


def _macro(signals: List[Signal] = None, confidence: float = 0.75) -> MacroSensitivity:
    return MacroSensitivity(
        overall="Macro analysis.",
        confidence=confidence,
        signals=signals or [],
    )


def _risk(signals: List[Signal] = None, confidence: float = 0.70) -> RiskProfile:
    return RiskProfile(
        overall="Risk analysis.",
        confidence=confidence,
        signals=signals or [],
    )


def _market(signals: List[Signal] = None, confidence: float = 0.72) -> MarketContext:
    return MarketContext(
        overall="Market analysis.",
        confidence=confidence,
        signals=signals or [],
    )


def _quality(signals: List[Signal] = None, confidence: float = 0.68) -> QualityAssessment:
    return QualityAssessment(
        overall="Quality analysis.",
        confidence=confidence,
        signals=signals or [],
    )


def _thesis(
    bull: str = "Bull case text here.",
    bear: str = "Bear case text here.",
    conclusion: str = "Overall conclusion.",
    confidence_score: float = 0.70,
    direct_answer: str = "",
    what_changes: List[str] = None,
) -> InvestmentThesis:
    return InvestmentThesis(
        ticker="AAPL",
        company_name="Apple Inc.",
        bull_thesis=bull,
        bear_thesis=bear,
        conclusion=conclusion,
        confidence_score=confidence_score,
        direct_answer=direct_answer,
        what_changes_the_thesis=what_changes or [],
    )


# ── Similarity helpers ────────────────────────────────────────────────────────

class TestTokenize:
    def test_removes_stopwords(self):
        tokens = _tokenize("the company is in the market")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "in" not in tokens

    def test_lowercases(self):
        tokens = _tokenize("Apple SERVICES Revenue")
        assert "apple" in tokens
        assert "services" in tokens
        assert "revenue" in tokens

    def test_short_words_excluded(self):
        # words ≤ 2 chars are filtered
        tokens = _tokenize("P/E of 25x vs 30x")
        assert "of" not in tokens
        assert "vs" not in tokens

    def test_empty_string(self):
        assert _tokenize("") == set()


class TestJaccard:
    def test_identical_strings_return_1(self):
        assert _jaccard("Apple Services revenue growth", "Apple Services revenue growth") == 1.0

    def test_completely_different_returns_0(self):
        result = _jaccard("xylophone purple castle", "finance bonds yield")
        assert result == 0.0

    def test_partial_overlap(self):
        score = _jaccard("Apple Services margins expand", "Services margins compress slightly")
        assert 0.0 < score < 1.0

    def test_empty_strings(self):
        assert _jaccard("", "something here") == 0.0


class TestAreDuplicates:
    def test_very_similar_signals_are_duplicates(self):
        s1 = _signal("Apple Services revenue growing at 15% drives margin expansion")
        s2 = _signal("Apple Services segment revenue growing 14% driving margin expansion")
        assert _are_duplicates(s1, s2)

    def test_different_signals_not_duplicates(self):
        s1 = _signal("Apple buyback $90B annually supports EPS growth")
        s2 = _signal("China tariff exposure on iPhone hardware supply chain")
        assert not _are_duplicates(s1, s2)

    def test_custom_threshold_lower_catches_more(self):
        # Jaccard ≈ 0.33 (2 shared tokens: "services", "margins" out of 6 total)
        s1 = _signal("Services margins growing expanding")
        s2 = _signal("Services margins revenue growth")
        # At threshold=0.30 Jaccard(0.33) ≥ 0.30 → duplicates
        assert _are_duplicates(s1, s2, threshold=0.30)
        # At threshold=0.90 Jaccard(0.33) < 0.90 → not duplicates
        assert not _are_duplicates(s1, s2, threshold=0.90)


# ── Score computation ─────────────────────────────────────────────────────────

class TestScoreComputation:
    def test_structural_bullish_scores_higher_than_noise(self):
        structural = _signal("text", signal_type="structural", direction="bullish", impact=0.8)
        noise = _signal("text", signal_type="noise", direction="bullish", impact=0.8)
        assert _score(structural, 0.8) > _score(noise, 0.8)

    def test_noise_score_is_zero(self):
        noise = _signal("text", signal_type="noise", impact=1.0)
        assert _score(noise, 1.0) == 0.0

    def test_bullish_scores_higher_than_neutral(self):
        bullish = _signal("text", direction="bullish", signal_type="catalyst", impact=0.8)
        neutral = _signal("text", direction="neutral", signal_type="catalyst", impact=0.8)
        assert _score(bullish, 0.8) > _score(neutral, 0.8)

    def test_bearish_equals_bullish_weight(self):
        bullish = _signal("text", direction="bullish", impact=0.8)
        bearish = _signal("text", direction="bearish", impact=0.8)
        # Both use 1.10 direction weight
        assert abs(_score(bullish, 0.8) - _score(bearish, 0.8)) < 1e-9

    def test_higher_impact_scores_higher(self):
        hi = _signal("text", impact=0.9, signal_type="structural", direction="bullish")
        lo = _signal("text", impact=0.3, signal_type="structural", direction="bullish")
        assert _score(hi, 0.8) > _score(lo, 0.8)

    def test_agent_confidence_scales_score(self):
        sig = _signal("text", impact=0.8, signal_type="structural", direction="bullish")
        assert _score(sig, 0.9) > _score(sig, 0.5)

    def test_type_priority_ordering(self):
        """structural > catalyst > valuation > macro > risk > cyclical > quality"""
        types_ordered = ["structural", "catalyst", "valuation", "macro", "risk", "cyclical", "quality"]
        scores = [
            _score(_signal("x", signal_type=t, impact=1.0, direction="bullish"), 1.0)
            for t in types_ordered
        ]
        for i in range(len(scores) - 1):
            assert scores[i] > scores[i + 1], (
                f"{types_ordered[i]} score {scores[i]:.4f} should exceed "
                f"{types_ordered[i+1]} score {scores[i+1]:.4f}"
            )


# ── Merge ─────────────────────────────────────────────────────────────────────

class TestMerge:
    def test_impact_score_boosted_by_recurrence(self):
        primary = _signal("Services revenue growing 15%", impact=0.7)
        secondary = _signal("Services segment revenue 15% growth", impact=0.6)
        merged = _merge(primary, secondary, recurrence_bonus=0.20)
        assert merged.impact_score > primary.impact_score

    def test_impact_score_capped_at_1(self):
        primary = _signal("text", impact=0.99)
        secondary = _signal("text", impact=0.99)
        merged = _merge(primary, secondary, recurrence_bonus=0.20)
        assert merged.impact_score <= 1.0

    def test_source_agent_combined(self):
        primary = _signal("text", source_agent="valuation")
        secondary = Signal(
            signal="text",
            impact_score=0.5,
            source_agent="macro",
        )
        merged = _merge(primary, secondary, recurrence_bonus=0.20)
        assert "valuation" in merged.source_agent
        assert "macro" in merged.source_agent

    def test_importance_reason_combined(self):
        primary = _signal("text", importance_reason="Services margin")
        secondary = Signal(
            signal="text",
            impact_score=0.5,
            importance_reason="FCF conversion",
        )
        merged = _merge(primary, secondary, recurrence_bonus=0.20)
        assert "Services margin" in merged.importance_reason
        assert "FCF conversion" in merged.importance_reason

    def test_evidence_refs_unioned(self):
        primary = _signal("text")
        primary = Signal(signal="text", impact_score=0.7, evidence_refs=["ref1", "ref2"])
        secondary = Signal(signal="text", impact_score=0.5, evidence_refs=["ref2", "ref3"])
        merged = _merge(primary, secondary, recurrence_bonus=0.20)
        assert "ref1" in merged.evidence_refs
        assert "ref2" in merged.evidence_refs
        assert "ref3" in merged.evidence_refs


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestDeduplicate:
    def test_duplicate_signals_collapsed(self):
        s1 = _signal("Apple Services revenue growing 15% compresses hardware margin drag")
        s2 = _signal("Apple Services segment revenue growing 14% reducing hardware margin impact")
        pairs = [(s1, 0.8), (s2, 0.75)]
        result = _deduplicate(pairs)
        assert len(result) == 1

    def test_unique_signals_all_kept(self):
        s1 = _signal("Apple Services margins at 72% drive blended margin expansion")
        s2 = _signal("China tariff exposure on iPhone hardware threatens $20B revenue")
        s3 = _signal("$90B annual buyback compresses share count, boosting EPS mechanically")
        pairs = [(s1, 0.8), (s2, 0.75), (s3, 0.7)]
        result = _deduplicate(pairs)
        assert len(result) == 3

    def test_recurrence_bonus_applied_to_merged(self):
        # Jaccard ≈ 0.75 — high overlap so dedup fires at 0.45 threshold
        s1 = _signal("Apple Services margin expanding annually driven growth", impact=0.7)
        s2 = _signal("Apple Services margin expanding driven annual growth", impact=0.6)
        pairs = [(s1, 0.8), (s2, 0.75)]
        result = _deduplicate(pairs)
        assert len(result) == 1
        merged_sig, _ = result[0]
        # Merged impact should be higher than original 0.7 due to recurrence bonus
        assert merged_sig.impact_score > 0.7

    def test_empty_pairs_returns_empty(self):
        assert _deduplicate([]) == []


# ── Noise suppression ─────────────────────────────────────────────────────────

class TestNoiseSuppression:
    def test_noise_signals_filtered_from_top_signals(self):
        noise_sig = _signal("Generic text", signal_type="noise", impact=0.9, direction="bullish")
        val = _valuation(signals=[noise_sig])
        result = rank_signals(val, _macro(), _risk(), _market(), _quality())
        # Noise should not appear in top_signals or all_ranked
        assert all(s.signal_type != "noise" for s in result.top_signals)
        assert all(s.signal_type != "noise" for s in result.all_ranked)

    def test_noise_signals_appear_in_noise_bucket(self):
        noise_sig = _signal("Generic noise statement", signal_type="noise", impact=0.9)
        val = _valuation(signals=[noise_sig])
        result = rank_signals(val, _macro(), _risk(), _market(), _quality())
        assert len(result.noise) >= 1


# ── Rank signals main function ────────────────────────────────────────────────

class TestRankSignals:
    def test_returns_ranked_signal_set(self):
        val = _valuation(signals=[_signal("Services 72% gross margin", impact=0.8)])
        result = rank_signals(val, _macro(), _risk(), _market(), _quality())
        assert isinstance(result, RankedSignalSet)

    def test_top_signals_are_non_risk(self):
        val = _valuation(signals=[
            _signal("Services margin expansion drives upside", direction="bullish", impact=0.9),
        ])
        risk_val = _risk(signals=[
            _signal("China revenue 19% tariff exposure", direction="bearish",
                    signal_type="risk", impact=0.85),
        ])
        result = rank_signals(val, _macro(), risk_val, _market(), _quality())
        # top_signals should contain bullish/neutral only
        for sig in result.top_signals:
            assert sig.direction != "bearish"

    def test_top_risks_are_bearish_or_risk_type(self):
        risk_val = _risk(signals=[
            _signal("China revenue 19% tariff threat", direction="bearish",
                    signal_type="risk", impact=0.9),
        ])
        result = rank_signals(_valuation(), _macro(), risk_val, _market(), _quality())
        for sig in result.top_risks:
            assert sig.direction == "bearish" or sig.signal_type == "risk"

    def test_top_signals_max_3(self):
        val = _valuation(signals=[
            _signal(f"Bullish signal {i}", direction="bullish", impact=0.8 - i * 0.05)
            for i in range(6)
        ])
        result = rank_signals(val, _macro(), _risk(), _market(), _quality())
        assert len(result.top_signals) <= 3

    def test_top_risks_max_4(self):
        risk_sigs = [
            _signal(f"Risk signal {i}", direction="bearish", signal_type="risk",
                    impact=0.9 - i * 0.05)
            for i in range(6)
        ]
        result = rank_signals(_valuation(), _macro(), _risk(signals=risk_sigs), _market(), _quality())
        assert len(result.top_risks) <= 4

    def test_secondary_signals_max_6(self):
        # Create more signals than top_signals + top_risks can absorb
        val_sigs = [_signal(f"Bullish driver {i}", impact=0.5) for i in range(5)]
        macro_sigs = [
            _signal(f"Bearish macro {i}", direction="bearish", signal_type="macro", impact=0.5)
            for i in range(5)
        ]
        result = rank_signals(
            _valuation(signals=val_sigs),
            _macro(signals=macro_sigs),
            _risk(), _market(), _quality()
        )
        assert len(result.secondary_signals) <= 6

    def test_no_signals_returns_empty_set(self):
        result = rank_signals(_valuation(), _macro(), _risk(), _market(), _quality())
        assert result.top_signals == []
        assert result.top_risks == []
        assert result.all_ranked == []

    def test_zero_confidence_agent_signals_skipped(self):
        val = _valuation(
            signals=[_signal("High quality Services margin signal", impact=0.9)],
            confidence=0.0,  # zero confidence — should skip
        )
        normal_macro = _macro(signals=[_signal("Rate sensitivity", signal_type="macro")])
        result = rank_signals(val, normal_macro, _risk(), _market(), _quality())
        # val signals should NOT appear since confidence=0
        source_agents = {s.source_agent for s in result.all_ranked}
        assert "valuation" not in source_agents

    def test_source_agent_stamped(self):
        val = _valuation(signals=[_signal("Services at 72% margin", source_agent="")])
        result = rank_signals(val, _macro(), _risk(), _market(), _quality())
        if result.all_ranked:
            assert result.all_ranked[0].source_agent == "valuation"

    def test_structural_outranks_macro_same_impact(self):
        structural = _signal("Apple ecosystem lock-in drives 95% retention", signal_type="structural",
                             direction="bullish", impact=0.8)
        macro = _signal("Rate cut reduces discount rate by 50bps", signal_type="macro",
                        direction="bullish", impact=0.8)
        val = _valuation(signals=[structural])
        mac = _macro(signals=[macro])
        result = rank_signals(val, mac, _risk(), _market(), _quality())
        # Structural signal should rank above macro signal
        if len(result.all_ranked) >= 2:
            types = [s.signal_type for s in result.all_ranked]
            structural_idx = next((i for i, t in enumerate(types) if t == "structural"), 999)
            macro_idx = next((i for i, t in enumerate(types) if t == "macro"), 999)
            assert structural_idx < macro_idx, (
                f"Structural (idx {structural_idx}) should rank before macro (idx {macro_idx})"
            )


# ── Macro + valuation conflict resolution ────────────────────────────────────

class TestMacroValuationConflict:
    """When macro and valuation agents raise conflicting signals, the higher-scoring
    signal should win rank, and both should appear in the output without dedup."""

    def test_conflicting_macro_valuation_both_appear(self):
        """Opposite-direction signals should NOT be deduplicated."""
        bullish_val = _signal(
            "Apple Services 72% gross margin offsets hardware P/E compression at 28x",
            signal_type="valuation", direction="bullish", impact=0.85,
        )
        bearish_macro = _signal(
            "100bps rate rise compresses Apple forward P/E via higher discount rate",
            signal_type="macro", direction="bearish", impact=0.80,
        )
        val = _valuation(signals=[bullish_val])
        mac = _macro(signals=[bearish_macro])
        result = rank_signals(val, mac, _risk(), _market(), _quality())
        directions = {s.direction for s in result.all_ranked}
        # Both directions should be present
        assert "bullish" in directions
        assert "bearish" in directions

    def test_higher_scoring_signal_ranks_first_in_all_ranked(self):
        """Structural > valuation, so structural should rank first."""
        structural = _signal(
            "iCloud ecosystem switching cost forces 95% iPhone upgrade retention",
            signal_type="structural", direction="bullish", impact=0.85,
        )
        valuation_sig = _signal(
            "Apple 28x P/E compressed by rising discount rates on DCF",
            signal_type="valuation", direction="neutral", impact=0.80,
        )
        val = _valuation(signals=[valuation_sig, structural])
        result = rank_signals(val, _macro(), _risk(), _market(), _quality())
        if len(result.all_ranked) >= 2:
            assert result.all_ranked[0].signal_type == "structural"


# ── Apple / rates scenario ────────────────────────────────────────────────────

class TestAppleRatesScenario:
    """Prioritization test: Apple + higher rates should surface:
    1. Multiple compression (valuation bearish)
    2. Services segment resilience (structural bullish)
    3. Hardware demand sensitivity (macro/cyclical bearish)
    """

    def _build_apple_signals(self):
        multiple_compression = _signal(
            "100bps rate rise compresses AAPL forward P/E from 28x to ~24x via DCF discount rate expansion",
            signal_type="valuation", direction="bearish", impact=0.90,
            source_agent="macro",
        )
        services_resilience = _signal(
            "Apple Services at 72% gross margin and $100B ARR provides rate-insensitive revenue floor",
            signal_type="structural", direction="bullish", impact=0.85,
            source_agent="valuation",
        )
        hardware_demand = _signal(
            "Higher financing costs reduce iPhone ASP affordability for credit-dependent consumers",
            signal_type="cyclical", direction="bearish", impact=0.70,
            source_agent="macro",
        )
        return multiple_compression, services_resilience, hardware_demand

    def test_multiple_compression_appears_in_risks(self):
        mc, sr, hd = self._build_apple_signals()
        mac = _macro(signals=[mc, hd])
        val = _valuation(signals=[sr])
        result = rank_signals(val, mac, _risk(), _market(), _quality())
        # multiple compression is bearish → should be in top_risks
        risk_signals_text = " ".join(s.signal for s in result.top_risks)
        assert "P/E" in risk_signals_text or "discount rate" in risk_signals_text.lower(), (
            f"Multiple compression not found in top_risks: {risk_signals_text}"
        )

    def test_services_resilience_appears_in_top_signals(self):
        mc, sr, hd = self._build_apple_signals()
        mac = _macro(signals=[mc, hd])
        val = _valuation(signals=[sr])
        result = rank_signals(val, mac, _risk(), _market(), _quality())
        top_signals_text = " ".join(s.signal for s in result.top_signals)
        assert "Services" in top_signals_text or "services" in top_signals_text, (
            f"Services resilience not found in top_signals: {top_signals_text}"
        )

    def test_hardware_demand_sensitivity_ranked_below_services(self):
        mc, sr, hd = self._build_apple_signals()
        mac = _macro(signals=[mc, hd])
        val = _valuation(signals=[sr])
        result = rank_signals(val, mac, _risk(), _market(), _quality())
        # hardware_demand is cyclical/bearish impact=0.70, services is structural/bullish impact=0.85
        # structural should score higher → services ranked in all_ranked before hardware_demand
        ranked_types = [s.signal_type for s in result.all_ranked]
        structural_idx = next((i for i, t in enumerate(ranked_types) if t == "structural"), 999)
        cyclical_idx = next((i for i, t in enumerate(ranked_types) if t == "cyclical"), 999)
        assert structural_idx < cyclical_idx, (
            f"Services (structural, idx {structural_idx}) should rank before "
            f"hardware demand (cyclical, idx {cyclical_idx})"
        )

    def test_cross_agent_same_concept_deduped(self):
        """If valuation AND macro both flag P/E compression, they should merge.
        Jaccard ≈ 0.75 between these two signals (9 of 12 tokens overlap).
        """
        mc_val = _signal(
            "Apple 28x P/E compresses to 24x under 100bps rate rise DCF expansion",
            signal_type="valuation", direction="bearish", impact=0.85,
            source_agent="valuation",
        )
        mc_mac = _signal(
            "Apple 28x P/E multiple compresses to 24x under 100bps rate rise discount expansion",
            signal_type="macro", direction="bearish", impact=0.80,
            source_agent="macro",
        )
        val = _valuation(signals=[mc_val])
        mac = _macro(signals=[mc_mac])
        result = rank_signals(val, mac, _risk(), _market(), _quality())
        # Both signals express the same P/E compression — should be merged to 1
        pe_signals = [s for s in result.all_ranked if "28x" in s.signal or "24x" in s.signal]
        assert len(pe_signals) == 1, (
            f"Expected 1 merged P/E signal, got {len(pe_signals)}: "
            + "; ".join(s.signal[:60] for s in pe_signals)
        )


# ── Thesis compression ────────────────────────────────────────────────────────

class TestThesisCompression:
    def test_returns_compressed_thesis_instance(self):
        thesis = _thesis(bull="Bull case.", conclusion="Final conclusion.")
        val = _valuation(signals=[_signal("Services 72% margin drives upside", impact=0.85)])
        ranked = rank_signals(val, _macro(), _risk(), _market(), _quality())
        ct = compress_thesis(thesis, ranked)
        assert isinstance(ct, CompressedThesis)

    def test_direct_answer_uses_thesis_field(self):
        thesis = _thesis(direct_answer="Higher rates pressure AAPL via P/E compression.")
        val = _valuation(signals=[_signal("Services margin", impact=0.8)])
        ranked = rank_signals(val, _macro(), _risk(), _market(), _quality())
        ct = compress_thesis(thesis, ranked)
        assert "Higher rates pressure AAPL" in ct.direct_answer

    def test_direct_answer_falls_back_to_conclusion(self):
        thesis = _thesis(
            direct_answer="",
            conclusion="Services at 72% margin offsets hardware sensitivity. This drives upside."
        )
        val = _valuation(signals=[_signal("Signal text", impact=0.8)])
        ranked = rank_signals(val, _macro(), _risk(), _market(), _quality())
        ct = compress_thesis(thesis, ranked)
        assert len(ct.direct_answer) > 0

    def test_one_sentence_thesis_includes_confidence_qualifier(self):
        thesis = _thesis(bull="Services revenue at 72% margin will drive long-term P/E re-rating.",
                         confidence_score=0.80)
        val = _valuation(signals=[_signal("Signal", impact=0.8)])
        ranked = rank_signals(val, _macro(), _risk(), _market(), _quality())
        ct = compress_thesis(thesis, ranked)
        assert "high conviction" in ct.one_sentence_thesis.lower()

    def test_one_sentence_thesis_moderate_conviction(self):
        thesis = _thesis(
            bull="Apple Services margin expansion is the primary bull driver.",
            confidence_score=0.60,
        )
        val = _valuation(signals=[_signal("Signal", impact=0.8)])
        ranked = rank_signals(val, _macro(), _risk(), _market(), _quality())
        ct = compress_thesis(thesis, ranked)
        assert "moderate conviction" in ct.one_sentence_thesis.lower()

    def test_one_sentence_thesis_low_conviction(self):
        thesis = _thesis(
            bull="Bull case uncertain given limited evidence.",
            confidence_score=0.40,
        )
        val = _valuation(signals=[_signal("Signal", impact=0.8)])
        ranked = rank_signals(val, _macro(), _risk(), _market(), _quality())
        ct = compress_thesis(thesis, ranked)
        assert "low conviction" in ct.one_sentence_thesis.lower()

    def test_top_signals_from_ranked_set(self):
        val = _valuation(signals=[
            _signal("Services 72% margin structural advantage", signal_type="structural",
                    impact=0.9, direction="bullish"),
        ])
        ranked = rank_signals(val, _macro(), _risk(), _market(), _quality())
        thesis = _thesis()
        ct = compress_thesis(thesis, ranked)
        assert len(ct.top_signals) >= 1

    def test_what_changes_view_from_thesis(self):
        changes = [
            "Services growth decelerates below 10%",
            "Fed raises rates 200bps",
            "China revenue bans impact 19% of revenue",
        ]
        thesis = _thesis(what_changes=changes)
        val = _valuation(signals=[_signal("Signal", impact=0.8)])
        ranked = rank_signals(val, _macro(), _risk(), _market(), _quality())
        ct = compress_thesis(thesis, ranked)
        assert len(ct.what_changes_this_view) >= 1
        for item in ct.what_changes_this_view:
            assert item in changes

    def test_why_it_matters_from_top_signal(self):
        sig = _signal("Services at 72% margin", importance_reason="Services resilience thesis-defining")
        val = _valuation(signals=[sig])
        ranked = rank_signals(val, _macro(), _risk(), _market(), _quality())
        thesis = _thesis()
        ct = compress_thesis(thesis, ranked)
        # why_it_matters should come from the top signal's importance_reason
        assert len(ct.why_it_matters) > 0


# ── Forbidden phrase detection ────────────────────────────────────────────────

class TestForbiddenPhraseDetection:
    def test_detects_well_positioned(self):
        hits = detect_forbidden_phrases("Apple is well positioned for long-term growth.")
        assert "well positioned" in hits

    def test_detects_industry_leader(self):
        hits = detect_forbidden_phrases("As an industry leader, Apple commands premium pricing.")
        assert "industry leader" in hits

    def test_detects_robust_ecosystem(self):
        hits = detect_forbidden_phrases("Apple's robust ecosystem creates switching costs.")
        assert "robust ecosystem" in hits

    def test_detects_faces_challenges(self):
        hits = detect_forbidden_phrases("The company faces challenges in China.")
        assert "faces challenges" in hits

    def test_detects_investors_should_monitor(self):
        hits = detect_forbidden_phrases("Investors should monitor regulatory developments.")
        assert "investors should monitor" in hits

    def test_clean_text_returns_empty(self):
        clean = (
            "Apple Services generates $100B ARR at 72% gross margin, "
            "compressing blended cost of revenue by 180bps annually."
        )
        assert detect_forbidden_phrases(clean) == []

    def test_case_insensitive_detection(self):
        hits = detect_forbidden_phrases("Apple is WELL POSITIONED to benefit.")
        assert "well positioned" in hits

    def test_multiple_phrases_detected(self):
        text = "Apple is well positioned as an industry leader with a robust ecosystem."
        hits = detect_forbidden_phrases(text)
        assert len(hits) >= 2


class TestCheckForbiddenPhrases:
    def test_returns_quality_warning_strings(self):
        thesis = _thesis(
            bull="Apple is well positioned to outperform.",
            bear="Bear case.",
        )
        warnings = check_forbidden_phrases(thesis)
        assert any("[QUALITY]" in w for w in warnings)

    def test_clean_thesis_returns_no_warnings(self):
        thesis = _thesis(
            bull=(
                "Apple Services at 72% gross margin and $100B ARR provides rate-insensitive "
                "revenue buffer that offsets hardware P/E compression in rising rate cycles."
            ),
            bear=(
                "China revenue concentration at 19% ($69B) faces $10B+ tariff exposure "
                "that could compress iPhone ASP by 8-12% if trade war escalates."
            ),
            conclusion=(
                "AAPL's structural Services margin moat provides a floor while China tariffs "
                "represent the primary downside scenario at current 28x forward P/E."
            ),
        )
        warnings = check_forbidden_phrases(thesis)
        assert warnings == []

    def test_warns_on_bear_thesis_phrase(self):
        thesis = _thesis(
            bull="Services at 72% margin drives upside.",
            bear="Apple faces challenges in China and regulatory markets.",
        )
        warnings = check_forbidden_phrases(thesis)
        field_warnings = [w for w in warnings if "bear_thesis" in w]
        assert len(field_warnings) >= 1

    def test_warns_on_conclusion_phrase(self):
        thesis = _thesis(
            conclusion="Overall, Apple remains to be seen as an industry leader.",
        )
        warnings = check_forbidden_phrases(thesis)
        field_warnings = [w for w in warnings if "conclusion" in w]
        assert len(field_warnings) >= 1


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_all_empty_agents_returns_empty_set(self):
        result = rank_signals(_valuation(), _macro(), _risk(), _market(), _quality())
        assert result.top_signals == []
        assert result.top_risks == []
        assert result.noise == []
        assert result.all_ranked == []

    def test_single_signal_in_top_signals(self):
        val = _valuation(signals=[_signal("One signal only", impact=0.8, direction="bullish")])
        result = rank_signals(val, _macro(), _risk(), _market(), _quality())
        assert len(result.top_signals) == 1

    def test_single_risk_in_top_risks(self):
        risk_val = _risk(signals=[
            _signal("One risk only", signal_type="risk", direction="bearish", impact=0.8)
        ])
        result = rank_signals(_valuation(), _macro(), risk_val, _market(), _quality())
        assert len(result.top_risks) == 1

    def test_all_noise_signals_produces_empty_ranked(self):
        # Short "noise N" signals share the token "noise" and single-digit numbers
        # are filtered (len ≤ 2), so they all dedup into one.  Use distinct verbose
        # strings to avoid dedup collapsing all 5.
        noise_sigs = [
            _signal(f"unrelated generic filler statement number {i} with padding words here extra",
                    signal_type="noise")
            for i in range(5)
        ]
        val = _valuation(signals=noise_sigs)
        result = rank_signals(val, _macro(), _risk(), _market(), _quality())
        assert result.all_ranked == []
        # After dedup some may merge but noise bucket should be non-empty
        assert len(result.noise) >= 1

    def test_signals_from_all_five_agents_collected(self):
        # Use fully distinct, non-overlapping signal texts to prevent the dedup
        # logic from merging them (short identical-suffix strings like "X signal"
        # share the "signal" token and can collapse across agents).
        val = _valuation(signals=[_signal(
            "Azure cloud 29% growth drives FCF expansion and multiple re-rating",
            signal_type="valuation", impact=0.6)])
        mac = _macro(signals=[_signal(
            "Federal Reserve rate pivot reduces discount rate compression on growth multiples",
            signal_type="macro", impact=0.6)])
        ris = _risk(signals=[_signal(
            "Antitrust DOJ investigation into cloud bundling creates regulatory overhang",
            signal_type="risk", direction="bearish", impact=0.6)])
        mkt = _market(signals=[_signal(
            "Consensus EPS estimate revision cycle turning positive after three quarters of cuts",
            signal_type="catalyst", impact=0.6)])
        qua = _quality(signals=[_signal(
            "Recurring subscription revenue base exceeds 85% of total providing earnings durability",
            signal_type="quality", impact=0.6)])
        result = rank_signals(val, mac, ris, mkt, qua)
        source_agents = {s.source_agent for s in result.all_ranked}
        assert "valuation" in source_agents
        assert "macro" in source_agents
        assert "risk" in source_agents
        assert "market" in source_agents
        assert "quality" in source_agents


# ── Fix-5 regression: defensive fallback when only bearish signals exist ──────

class TestTopSignalsFallback:
    """Regression tests for the defensive fallback in rank_signals().

    When all agents return only bearish/risk-type signals (the observed failure
    mode for MSFT, AMZN, NVDA, AMD, GS, UNH, NFLX in the 20-company validation),
    the fallback promotes the highest-scoring non-risk signal to top_signals so
    that top_signals is never empty when signal data exists.
    """

    def test_fallback_fires_when_only_risk_signals_present(self):
        """When all non-risk agents return empty signals and risk agent has bearish
        signals, the fallback puts at least 1 signal in top_signals."""
        # Risk agent: 3 bearish signals only — mirrors the zero-signal company pattern
        risk_sigs = [
            _signal(
                f"Regulatory antitrust exposure risk factor {i}",
                signal_type="risk",
                direction="bearish",
                impact=0.80 - i * 0.05,
                source_agent="risk",
            )
            for i in range(3)
        ]
        val   = _valuation(signals=[])
        mac   = _macro(signals=[])
        ris   = _risk(signals=risk_sigs)
        mkt   = _market(signals=[])
        qua   = _quality(signals=[])
        result = rank_signals(val, mac, ris, mkt, qua)

        # The fallback must fire: top_signals was empty, all_ranked is non-empty
        assert len(result.top_signals) >= 1, (
            "Fallback must populate top_signals when only bearish signals exist. "
            f"Got top_signals={result.top_signals}, all_ranked={result.all_ranked}"
        )

    def test_fallback_does_not_fire_when_bullish_signals_exist(self):
        """When bullish signals are present, the normal path fires (no fallback needed)."""
        bullish_sig = _signal(
            "Azure cloud FCF expansion supports premium multiple",
            direction="bullish",
            signal_type="structural",
            impact=0.85,
            source_agent="valuation",
        )
        val   = _valuation(signals=[bullish_sig])
        mac   = _macro(signals=[])
        ris   = _risk(signals=[_signal("Rate risk", direction="bearish", signal_type="risk", source_agent="risk")])
        mkt   = _market(signals=[])
        qua   = _quality(signals=[])
        result = rank_signals(val, mac, ris, mkt, qua)

        assert len(result.top_signals) >= 1
        # The promoted signal should be the bullish one (not a risk signal promoted)
        assert result.top_signals[0].direction in ("bullish", "neutral")

    def test_fallback_does_not_fire_when_no_signals_at_all(self):
        """When every agent returns empty signals, top_signals stays empty (no phantom signals)."""
        val   = _valuation(signals=[])
        mac   = _macro(signals=[])
        ris   = _risk(signals=[])
        mkt   = _market(signals=[])
        qua   = _quality(signals=[])
        result = rank_signals(val, mac, ris, mkt, qua)

        # all_ranked is empty, fallback can't create signals from nothing
        assert result.top_signals == [], (
            "Fallback must not create signals when all agents return empty signals. "
            f"Got top_signals={result.top_signals}"
        )

    def test_fallback_prioritises_non_risk_signal_when_available(self):
        """When both risk and non-risk signals exist, fallback prefers the non-risk one.

        A 'non-risk signal' in this context is a signal that is neither direction='bearish'
        nor signal_type='risk', so it does not end up in bearish_risk/top_risks.
        A neutral macro or structural signal from a non-risk agent qualifies.
        """
        # 2 bearish risk signals (will go to bearish_risk → top_risks)
        risk_sigs = [
            _signal(
                "Antitrust regulatory scrutiny overhang creates headline risk for multiple",
                signal_type="risk",
                direction="bearish",
                impact=0.78,
                source_agent="risk",
            ),
            _signal(
                "Supply chain concentration in single geography creates execution risk",
                signal_type="risk",
                direction="bearish",
                impact=0.72,
                source_agent="risk",
            ),
        ]
        # 1 neutral macro signal (NOT bearish, NOT risk type → will NOT be in bearish_risk)
        neutral_macro = _signal(
            "Enterprise cloud spending resilient versus consumer cyclical pressures on balance",
            signal_type="macro",
            direction="neutral",
            impact=0.75,
            source_agent="macro",
        )
        val   = _valuation(signals=[])
        mac   = _macro(signals=[neutral_macro])
        ris   = _risk(signals=risk_sigs)
        mkt   = _market(signals=[])
        qua   = _quality(signals=[])
        result = rank_signals(val, mac, ris, mkt, qua)

        # Fallback should have fired: neutral_macro was in bullish_neutral[:6]
        # (direction="neutral") so it should actually go through the normal path,
        # not the fallback. top_signals must be non-empty.
        assert len(result.top_signals) >= 1, (
            "Neutral signal from macro agent must populate top_signals via normal path"
        )
        # The neutral signal is NOT in bearish_risk, so top_signals and top_risks
        # should not overlap
        top_signal_ids = {id(s) for s in result.top_signals}
        top_risk_ids   = {id(s) for s in result.top_risks}
        no_overlap = top_signal_ids.isdisjoint(top_risk_ids)
        assert no_overlap, (
            "A neutral signal must not overlap with top_risks (which only has bearish signals)"
        )
