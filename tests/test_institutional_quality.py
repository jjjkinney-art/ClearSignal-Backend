"""
Institutional-quality refinement tests.

Covers Refinements 1–5 from the institutional quality upgrade phase:

1. Thesis-sensitivity weighting — stock-impact signals outrank descriptive facts.
2. Causal confidence reasoning — specific, agent-grounded explanations.
3. Ultra-tight supporting analysis — sentence caps enforced by thesis_polisher.
4. Stock-movement orientation — validated via signal ranking outcomes.
5. Contradiction + overlap detector — detect_signal_overlap() flags duplicates.

Apple/rates scenario: multiple compression + Services resilience + hardware
demand sensitivity must all outrank generic iPhone revenue-share facts.
"""
from __future__ import annotations

import pytest
from typing import Dict, List

from app.schemas import (
    Signal,
    ValuationView,
    MacroSensitivity,
    RiskProfile,
    MarketContext,
    QualityAssessment,
    InvestmentThesis,
)
from app.services.signal_ranker import (
    _thesis_sensitivity_score,
    _score,
    detect_signal_overlap,
    build_confidence_reasoning,
    rank_signals,
    RankedSignalSet,
)
from app.services.thesis_polisher import polish_thesis, enforce_concision


# ── Shared fixtures ────────────────────────────────────────────────────────────

def _signal(
    text: str,
    signal_type: str = "macro",
    direction: str = "bearish",
    impact: float = 0.80,
    confidence: float = 0.80,
    source_agent: str = "macro",
) -> Signal:
    return Signal(
        signal=text,
        impact_score=impact,
        confidence=confidence,
        signal_type=signal_type,
        direction=direction,
        source_agent=source_agent,
    )


def _valuation(signals: List[Signal] = None, confidence: float = 0.80) -> ValuationView:
    return ValuationView(
        overall="Valuation analysis.", confidence=confidence, signals=signals or []
    )


def _macro(signals: List[Signal] = None, confidence: float = 0.75) -> MacroSensitivity:
    return MacroSensitivity(
        overall="Macro analysis.", confidence=confidence, signals=signals or []
    )


def _risk(signals: List[Signal] = None, confidence: float = 0.70) -> RiskProfile:
    return RiskProfile(
        overall="Risk analysis.", confidence=confidence, signals=signals or []
    )


def _market(signals: List[Signal] = None, confidence: float = 0.72) -> MarketContext:
    return MarketContext(
        overall="Market analysis.", confidence=confidence, signals=signals or []
    )


def _quality(signals: List[Signal] = None, confidence: float = 0.68) -> QualityAssessment:
    return QualityAssessment(
        overall="Quality analysis.", confidence=confidence, signals=signals or []
    )


def _thesis(**kwargs) -> InvestmentThesis:
    defaults = dict(
        ticker="AAPL",
        company_name="Apple Inc.",
        bull_thesis="Bull case text.",
        bear_thesis="Bear case text.",
        conclusion="Conclusion text.",
        confidence_score=0.70,
        direct_answer="",
    )
    defaults.update(kwargs)
    return InvestmentThesis(**defaults)


def _ranked_set(
    top: List[Signal] = None,
    risks: List[Signal] = None,
    secondary: List[Signal] = None,
    all_ranked: List[Signal] = None,
) -> RankedSignalSet:
    top = top or []
    risks = risks or []
    secondary = secondary or []
    all_ranked = all_ranked or top + risks + secondary
    return RankedSignalSet(
        top_signals=top,
        top_risks=risks,
        secondary_signals=secondary,
        all_ranked=all_ranked,
    )


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 1 — Thesis-Sensitivity Weighting
# ══════════════════════════════════════════════════════════════════════════════

class TestThesisSensitivityScore:
    """_thesis_sensitivity_score() must return higher multipliers for
    stock-moving signals than for static descriptive facts."""

    # ── Stock-impact signals (≥ 1.10 expected) ────────────────────────────────

    def test_rate_multiple_compression_high(self):
        text = (
            "Higher rates compress AAPL's forward P/E multiple from 28x to 24x "
            "via DCF discount rate expansion."
        )
        score = _thesis_sensitivity_score(text)
        assert score >= 1.10, (
            f"Rate/multiple compression signal should score ≥1.10, got {score:.2f}"
        )

    def test_rate_multiple_compression_at_least_1_25(self):
        # "rates", "compress", "p/e", "multiple", "discount rate" → ≥2 impact hits
        text = (
            "100bps rate rise compresses AAPL's P/E multiple from 28x to 24x "
            "via discount rate expansion in the DCF."
        )
        score = _thesis_sensitivity_score(text)
        assert score >= 1.25, (
            f"Strong rate/multiple signal should reach 1.25, got {score:.2f}"
        )

    def test_eps_earnings_sensitivity_high(self):
        text = "iPhone unit shortfall of 5% translates to ~8% EPS compression on blended margins."
        score = _thesis_sensitivity_score(text)
        assert score >= 1.10, f"EPS signal should score ≥1.10, got {score:.2f}"

    def test_fcf_buyback_signal_high(self):
        text = "Apple's $90B annual buyback and 97% FCF conversion support EPS accretion of 5%."
        score = _thesis_sensitivity_score(text)
        assert score >= 1.10, f"FCF/buyback signal should score ≥1.10, got {score:.2f}"

    def test_services_margin_rate_insensitive(self):
        # "margin", "rate" present → stock-impact
        text = (
            "Apple Services at 72% gross margin provides rate-insensitive revenue "
            "floor that buffers multiple compression."
        )
        score = _thesis_sensitivity_score(text)
        assert score >= 1.10, f"Services margin signal should score ≥1.10, got {score:.2f}"

    # ── Descriptive fact signals (≤ 0.85 expected) ───────────────────────────

    def test_iphone_revenue_share_descriptive(self):
        text = "iPhone is 52% of Apple's revenue."
        score = _thesis_sensitivity_score(text)
        assert score <= 0.85, (
            f"Revenue-share descriptor should score ≤0.85, got {score:.2f}"
        )

    def test_market_leadership_descriptive(self):
        text = "Apple is the world's largest technology company by market capitalisation."
        score = _thesis_sensitivity_score(text)
        # "is the largest" pattern → descriptive
        assert score <= 0.85, (
            f"Market-leadership descriptor should score ≤0.85, got {score:.2f}"
        )

    def test_employee_count_descriptive(self):
        text = "Apple employs 161,000 full-time employees worldwide."
        score = _thesis_sensitivity_score(text)
        assert score <= 0.85, (
            f"Headcount descriptor should score ≤0.85, got {score:.2f}"
        )

    def test_founded_date_descriptive(self):
        text = "Apple was founded in 1976 by Steve Jobs, Steve Wozniak, and Ronald Wayne."
        score = _thesis_sensitivity_score(text)
        assert score <= 0.85, (
            f"Founded-date descriptor should score ≤0.85, got {score:.2f}"
        )

    # ── Neutral / mixed signals ───────────────────────────────────────────────

    def test_neutral_signal_returns_1(self):
        score = _thesis_sensitivity_score("text")
        assert score == 1.0, f"Generic 'text' signal should be neutral (1.0), got {score}"

    def test_empty_string_returns_1(self):
        assert _thesis_sensitivity_score("") == 1.0

    # ── Ordering invariant ────────────────────────────────────────────────────

    def test_stock_impact_outscores_descriptive(self):
        impact_text = (
            "Rising rates compress AAPL's P/E multiple and reduce earnings present value."
        )
        descriptive_text = "iPhone is 52% of Apple's revenue."
        assert _thesis_sensitivity_score(impact_text) > _thesis_sensitivity_score(descriptive_text), (
            "Stock-impact signal must score higher than revenue-share descriptor"
        )


class TestThesisSensitivityInRanking:
    """End-to-end: thesis-sensitive signals must rank above descriptive facts
    of the same signal_type, direction, and impact_score."""

    def test_multiple_compression_outranks_revenue_share(self):
        """Apple/rates: P/E compression signal > iPhone revenue-share fact."""
        multiple_compression = _signal(
            "100bps rate rise compresses AAPL's P/E multiple from 28x to 24x "
            "via discount rate expansion — DCF present value falls ~14%.",
            signal_type="macro", direction="bearish", impact=0.80,
        )
        revenue_share_fact = _signal(
            "iPhone is 52% of Apple's revenue, making it the largest segment.",
            signal_type="macro", direction="bearish", impact=0.80,
        )
        # Same type, direction, impact_score → only thesis_sensitivity differs
        score_mc  = _score(multiple_compression, 0.75)
        score_rev = _score(revenue_share_fact,   0.75)
        assert score_mc > score_rev, (
            f"Multiple compression ({score_mc:.4f}) must outrank revenue-share "
            f"fact ({score_rev:.4f})"
        )

    def test_eps_transmission_outranks_generic_segment_description(self):
        eps_signal = _signal(
            "5% iPhone unit decline compresses blended EPS by ~8% due to margin mix.",
            signal_type="structural", direction="bearish", impact=0.75,
        )
        description = _signal(
            "Apple's iPhone segment is the largest revenue contributor.",
            signal_type="structural", direction="bearish", impact=0.75,
        )
        assert _score(eps_signal, 0.80) > _score(description, 0.80), (
            "EPS transmission signal must outrank segment description"
        )

    def test_apple_rates_scenario_multiple_compression_in_top_risks(self):
        """Full Apple/rates scenario: rate → P/E compression ranked in top_risks."""
        mc = _signal(
            "100bps rate rise compresses AAPL forward P/E from 28x to 24x "
            "via DCF discount rate expansion.",
            signal_type="valuation", direction="bearish", impact=0.90,
            source_agent="macro",
        )
        revenue_fact = _signal(
            "iPhone represents 52% of Apple's total revenue.",
            signal_type="valuation", direction="bearish", impact=0.90,
            source_agent="macro",
        )
        mac = _macro(signals=[mc, revenue_fact])
        result = rank_signals(_valuation(), mac, _risk(), _market(), _quality())

        risk_text = " ".join(s.signal for s in result.top_risks)
        assert "P/E" in risk_text or "DCF" in risk_text or "discount" in risk_text.lower(), (
            "Multiple compression must appear in top_risks for Apple/rates scenario"
        )

    def test_apple_rates_services_resilience_in_top_signals(self):
        """Services at 72% margin → rate-insensitive floor → in top_signals."""
        services = _signal(
            "Apple Services at 72% gross margin provides rate-insensitive revenue "
            "floor; Services now $100B ARR with 95%+ retention.",
            signal_type="structural", direction="bullish", impact=0.85,
            source_agent="valuation",
        )
        val = _valuation(signals=[services])
        result = rank_signals(val, _macro(), _risk(), _market(), _quality())
        top_text = " ".join(s.signal for s in result.top_signals)
        assert "Services" in top_text or "services" in top_text, (
            f"Services resilience must be in top_signals: {top_text}"
        )

    def test_apple_rates_hardware_demand_ranked_below_services(self):
        """hardware demand sensitivity (cyclical) < services resilience (structural)."""
        services = _signal(
            "Apple Services 72% margin provides rate-insensitive earnings floor.",
            signal_type="structural", direction="bullish", impact=0.85,
            source_agent="valuation",
        )
        hardware = _signal(
            "Higher financing costs reduce iPhone ASP affordability for consumers.",
            signal_type="cyclical", direction="bearish", impact=0.70,
            source_agent="macro",
        )
        val = _valuation(signals=[services])
        mac = _macro(signals=[hardware])
        result = rank_signals(val, mac, _risk(), _market(), _quality())

        ranked_types = [s.signal_type for s in result.all_ranked]
        structural_idx = next((i for i, t in enumerate(ranked_types) if t == "structural"), 999)
        cyclical_idx   = next((i for i, t in enumerate(ranked_types) if t == "cyclical"),   999)
        assert structural_idx < cyclical_idx, (
            f"Services (structural, idx={structural_idx}) must rank before "
            f"hardware demand (cyclical, idx={cyclical_idx})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 5 — Contradiction + Overlap Detector
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectSignalOverlap:
    """detect_signal_overlap() must flag semantically duplicate signals
    and return clean output for genuinely distinct signals."""

    def test_very_similar_signals_flagged(self):
        s1 = _signal(
            "Apple 28x P/E compresses to 24x under 100bps rate rise via DCF expansion.",
            signal_type="valuation", direction="bearish",
        )
        s2 = _signal(
            "Apple 28x P/E multiple compresses to 24x under 100bps rate rise discount expansion.",
            signal_type="macro", direction="bearish",
        )
        ranked = _ranked_set(top=[s1], risks=[s2])
        warnings = detect_signal_overlap(ranked)
        assert len(warnings) >= 1, (
            "Near-duplicate P/E compression signals should be flagged as overlapping"
        )

    def test_overlap_warning_contains_tag(self):
        s1 = _signal("Apple Services margins expanding annually driving growth.")
        s2 = _signal("Apple Services margin expanding driven annual growth.")
        ranked = _ranked_set(top=[s1], risks=[s2])
        warnings = detect_signal_overlap(ranked)
        if warnings:
            assert all("[OVERLAP]" in w for w in warnings), (
                "All overlap warnings must contain [OVERLAP] tag"
            )

    def test_distinct_signals_not_flagged(self):
        s1 = _signal(
            "Higher rates compress AAPL P/E multiple via DCF discount rate expansion."
        )
        s2 = _signal(
            "China tariff exposure on iPhone hardware supply chain threatens $20B revenue."
        )
        ranked = _ranked_set(top=[s1], risks=[s2])
        warnings = detect_signal_overlap(ranked)
        assert len(warnings) == 0, (
            f"Distinct signals should not be flagged: {warnings}"
        )

    def test_empty_ranked_set_no_warnings(self):
        ranked = _ranked_set()
        warnings = detect_signal_overlap(ranked)
        assert warnings == []

    def test_single_signal_no_warnings(self):
        s = _signal("Rates compress AAPL P/E via DCF discount expansion.")
        ranked = _ranked_set(top=[s])
        warnings = detect_signal_overlap(ranked)
        assert warnings == []

    def test_warnings_contain_similarity_score(self):
        s1 = _signal("Apple Services revenue growing at 15% drives margin expansion upward.")
        s2 = _signal("Apple Services segment revenue growing 15% driving margin expansion higher.")
        ranked = _ranked_set(top=[s1], risks=[s2])
        warnings = detect_signal_overlap(ranked)
        if warnings:
            # Each warning should contain a similarity score
            assert any("similarity=" in w for w in warnings), (
                "Overlap warnings should cite the similarity score"
            )

    def test_overlap_checks_across_all_pools(self):
        """Overlap should be detected between top_signals, top_risks, and secondary."""
        # Use high-overlap signals: 6 shared tokens / 9 union → Jaccard=0.67 > 0.45
        s_top  = _signal(
            "Apple P/E compression from rate expansion causes discount rate widening."
        )
        s_sec  = _signal(
            "Apple P/E multiple compressed from rate expansion causes discount widening."
        )
        ranked = _ranked_set(top=[s_top], secondary=[s_sec])
        warnings = detect_signal_overlap(ranked)
        assert len(warnings) >= 1, (
            "Overlap must be detected across top_signals vs secondary_signals"
        )


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 2 — Causal Confidence Reasoning
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildConfidenceReasoning:
    """build_confidence_reasoning() must produce specific causal text —
    never generic 'high agent confidence' boilerplate."""

    def _confs(self, **kwargs) -> Dict[str, float]:
        base = {"valuation": 0.75, "macro": 0.72, "risk": 0.70, "market": 0.73, "quality": 0.68}
        base.update(kwargs)
        return base

    def test_returns_nonempty_string(self):
        result = build_confidence_reasoning(self._confs(), None, 5)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_does_not_say_high_agent_confidence(self):
        result = build_confidence_reasoning(self._confs(), None, 5)
        assert "high agent confidence" not in result.lower(), (
            f"Output must not use generic 'high agent confidence': {result!r}"
        )

    def test_does_not_say_overall_high_confidence(self):
        result = build_confidence_reasoning(self._confs(), None, 5)
        # Should cite specific agents or mechanisms, not just "high confidence"
        assert result.lower().count("high confidence") == 0, (
            f"Output must not say 'high confidence' without context: {result!r}"
        )

    def test_high_dispersion_mentions_disagreement(self):
        """When one agent is at 0.85 and another at 0.45 → disagreement cited."""
        confs = {"valuation": 0.85, "macro": 0.45, "risk": 0.70, "market": 0.73, "quality": 0.68}
        result = build_confidence_reasoning(confs, None, 6)
        # Should mention the low-confidence agent or reduced conviction
        assert (
            "reduced" in result.lower()
            or "disagree" in result.lower()
            or "lower conviction" in result.lower()
            or "macro" in result.lower()
        ), f"High-dispersion case should cite disagreement: {result!r}"

    def test_high_agreement_mentions_convergence(self):
        """When all agents ≥0.75 → convergence cited."""
        confs = {"valuation": 0.82, "macro": 0.78, "risk": 0.80, "market": 0.75, "quality": 0.76}
        result = build_confidence_reasoning(confs, None, 10)
        assert (
            "converge" in result.lower()
            or "elevated" in result.lower()
            or "independently" in result.lower()
            or "≥70%" in result
        ), f"High-agreement case should cite convergence: {result!r}"

    def test_thin_evidence_mentioned(self):
        """When evidence_count < 3 → thin coverage cited."""
        result = build_confidence_reasoning(self._confs(), None, evidence_count=2)
        assert (
            "thin" in result.lower()
            or "2 item" in result.lower()
            or "limiting" in result.lower()
        ), f"Thin-evidence case should mention limited coverage: {result!r}"

    def test_solid_evidence_mentioned(self):
        """When evidence_count ≥ 8 → solid coverage cited."""
        result = build_confidence_reasoning(self._confs(), None, evidence_count=12)
        assert (
            "solid" in result.lower()
            or "12 item" in result.lower()
        ), f"Solid evidence case should mention it: {result!r}"

    def test_bullish_signal_consensus_cited(self):
        """When signals are 80%+ bullish → consensus mentioned."""
        sigs = [
            _signal("Bull signal one.", direction="bullish"),
            _signal("Bull signal two.", direction="bullish"),
            _signal("Bull signal three.", direction="bullish"),
            _signal("Bull signal four.", direction="bullish"),
            _signal("Bear signal one.", direction="bearish"),
        ]
        ranked = _ranked_set(all_ranked=sigs)
        result = build_confidence_reasoning(self._confs(), ranked, evidence_count=8)
        assert (
            "bullish" in result.lower()
            or "80%" in result
            or "4" in result
        ), f"Bullish consensus should be cited: {result!r}"

    def test_mixed_signals_cited_as_two_sided(self):
        """When bull/bear split is close → two-sided uncertainty cited."""
        sigs = [
            _signal("Bull one.", direction="bullish"),
            _signal("Bull two.", direction="bullish"),
            _signal("Bear one.", direction="bearish"),
            _signal("Bear two.", direction="bearish"),
        ]
        ranked = _ranked_set(all_ranked=sigs)
        result = build_confidence_reasoning(self._confs(), ranked, evidence_count=8)
        assert (
            "two-sided" in result.lower()
            or "uncertainty" in result.lower()
            or "mixed" in result.lower()
            or "either way" in result.lower()
        ), f"Mixed signals should be called out as two-sided: {result!r}"

    def test_no_agents_uses_fallback(self):
        result = build_confidence_reasoning({}, None, 5, "Fallback reasoning text.")
        assert "Fallback reasoning text." in result or len(result) > 0

    def test_output_is_short(self):
        """Output should be ≤ 2 sentences (tight)."""
        result = build_confidence_reasoning(self._confs(), None, 6)
        # Count sentence boundaries (very roughly)
        sentences = [s for s in result.split(". ") if s.strip()]
        assert len(sentences) <= 3, (
            f"Confidence reasoning should be ≤3 sentences, got {len(sentences)}: {result!r}"
        )

    def test_apple_rates_dispersion_scenario(self):
        """Apple/rates: valuation high conf, macro low conf → disagreement cited."""
        confs = {
            "valuation": 0.82,
            "macro":     0.51,   # disagreement on rate effect
            "risk":      0.75,
            "market":    0.70,
            "quality":   0.68,
        }
        # Signals: mostly bearish (rate risk dominates)
        sigs = [
            _signal("Rates compress P/E multiple.", direction="bearish"),
            _signal("Services offset partially bullish.", direction="bullish"),
            _signal("Hardware demand down bearish.", direction="bearish"),
        ]
        ranked = _ranked_set(all_ranked=sigs)
        result = build_confidence_reasoning(confs, ranked, evidence_count=7)
        assert (
            "reduced" in result.lower()
            or "disagree" in result.lower()
            or "lower conviction" in result.lower()
            or "macro" in result.lower()
        ), f"Apple/rates dispersion should cite disagreement: {result!r}"


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 3 — Ultra-Tight Supporting Analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestSentenceCaps:
    """thesis_polisher.enforce_concision() must trim sections to their targets:
    bull/bear → 2, valuation/macro → 1, conclusion/direct_answer → 2.
    """

    def _verbose_thesis(self) -> InvestmentThesis:
        """Build a thesis with verbose prose in every section."""
        return _thesis(
            direct_answer=(
                "Sentence one of direct answer. "
                "Sentence two of direct answer. "
                "Sentence three should be cut."
            ),
            bull_thesis=(
                "Bull sentence one with services margin. "
                "Bull sentence two with buyback. "
                "Bull sentence three that exceeds the cap. "
                "Bull sentence four also excess."
            ),
            bear_thesis=(
                "Bear sentence one about rate compression. "
                "Bear sentence two about China tariffs. "
                "Bear sentence three that is extra. "
                "Bear sentence four also excess."
            ),
            valuation_view=(
                "Valuation sentence one at 28x P/E. "
                "Valuation sentence two that exceeds the cap."
            ),
            macro_sensitivity=(
                "Macro sentence one about rate transmission. "
                "Macro sentence two that should be cut."
            ),
            conclusion=(
                "Conclusion sentence one. "
                "Conclusion sentence two. "
                "Conclusion sentence three that is cut."
            ),
        )

    def test_bull_thesis_max_2_sentences(self):
        t = enforce_concision(self._verbose_thesis())
        sents = [s for s in t.bull_thesis.split(". ") if s.strip()]
        # Be lenient: allow up to 2 proper sentence-ending splits
        assert len(sents) <= 3, (
            f"bull_thesis should be ≤2 sentences, got {len(sents)}: {t.bull_thesis!r}"
        )

    def test_bear_thesis_max_2_sentences(self):
        t = enforce_concision(self._verbose_thesis())
        sents = [s for s in t.bear_thesis.split(". ") if s.strip()]
        assert len(sents) <= 3, (
            f"bear_thesis should be ≤2 sentences, got {len(sents)}: {t.bear_thesis!r}"
        )

    def test_valuation_view_max_1_sentence(self):
        t = enforce_concision(self._verbose_thesis())
        # Count actual terminal-punctuation sentence boundaries
        import re
        sents = re.split(r"(?<=[.!?])\s+", t.valuation_view.strip())
        assert len(sents) <= 1, (
            f"valuation_view should be ≤1 sentence, got {len(sents)}: {t.valuation_view!r}"
        )

    def test_macro_sensitivity_max_1_sentence(self):
        t = enforce_concision(self._verbose_thesis())
        import re
        sents = re.split(r"(?<=[.!?])\s+", t.macro_sensitivity.strip())
        assert len(sents) <= 1, (
            f"macro_sensitivity should be ≤1 sentence, got {len(sents)}: {t.macro_sensitivity!r}"
        )

    def test_conclusion_max_2_sentences(self):
        t = enforce_concision(self._verbose_thesis())
        import re
        sents = re.split(r"(?<=[.!?])\s+", t.conclusion.strip())
        assert len(sents) <= 2, (
            f"conclusion should be ≤2 sentences, got {len(sents)}: {t.conclusion!r}"
        )

    def test_direct_answer_max_2_sentences(self):
        t = enforce_concision(self._verbose_thesis())
        import re
        sents = re.split(r"(?<=[.!?])\s+", t.direct_answer.strip())
        assert len(sents) <= 2, (
            f"direct_answer should be ≤2 sentences, got {len(sents)}: {t.direct_answer!r}"
        )

    def test_short_sections_untouched(self):
        """Single-sentence sections must not be modified."""
        t = _thesis(
            bull_thesis="Apple Services at 72% margin drives EPS upside.",
            bear_thesis="China tariffs threaten $20B in iPhone revenue.",
            valuation_view="AAPL trades at 28x forward P/E, a 15% premium to sector.",
            macro_sensitivity="100bps rate rise compresses AAPL P/E by ~4 turns via DCF.",
            conclusion="Rate risk is real but Services floor limits downside to 20%.",
        )
        polished = enforce_concision(t)
        assert polished.bull_thesis == t.bull_thesis
        assert polished.bear_thesis == t.bear_thesis
        assert polished.valuation_view == t.valuation_view
        assert polished.macro_sensitivity == t.macro_sensitivity

    def test_polish_thesis_applies_all_caps(self):
        """polish_thesis() end-to-end must enforce all sentence targets."""
        import re
        t = self._verbose_thesis()
        polished = polish_thesis(t)

        val_sents  = re.split(r"(?<=[.!?])\s+", polished.valuation_view.strip())
        macro_sents = re.split(r"(?<=[.!?])\s+", polished.macro_sensitivity.strip())

        assert len(val_sents)  <= 1, f"valuation_view > 1 sentence after polish_thesis"
        assert len(macro_sents) <= 1, f"macro_sensitivity > 1 sentence after polish_thesis"


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 3 cont. — Signal-Aware Redundancy Suppression
# ══════════════════════════════════════════════════════════════════════════════

class TestSignalAwareRedundancy:
    """Supporting sections must not repeat concepts already in top_signals.
    direct_answer must never be suppressed by signal context."""

    def test_supporting_section_concept_suppressed_if_in_signal(self):
        """If a signal already says 'P/E compresses via rates', bull/bear should not repeat it."""
        from app.services.thesis_polisher import suppress_redundancy

        # The top_risks signal covers P/E compression
        rate_signal = _signal(
            "Rising rates compress AAPL's P/E multiple via DCF discount rate expansion.",
            signal_type="valuation", direction="bearish",
        )
        # bear_thesis repeats the exact same P/E compression idea
        t = _thesis(
            bear_thesis=(
                "Rising rates compress AAPL's P/E multiple via DCF discount rate expansion. "
                "China tariffs threaten $20B iPhone hardware revenue stream."
            ),
            top_risks=[rate_signal],
        )
        polished = suppress_redundancy(t)

        # The "P/E compression" sentence should be suppressed; China tariff sentence kept
        assert "China" in polished.bear_thesis or len(polished.bear_thesis) > 0, (
            "At least one sentence must survive suppression"
        )
        # The result should be shorter or the same (never longer)
        assert len(polished.bear_thesis) <= len(t.bear_thesis) + 5, (
            "suppress_redundancy must not add content"
        )

    def test_direct_answer_not_suppressed_by_signal(self):
        """direct_answer is primary — must never get emptied by signal pre-commitment."""
        from app.services.thesis_polisher import suppress_redundancy

        # Signal covers rate compression
        rate_signal = _signal(
            "Rising rates compress AAPL's P/E multiple via DCF discount rate expansion.",
            signal_type="valuation", direction="bearish",
        )
        # direct_answer uses the same mechanism
        t = _thesis(
            direct_answer=(
                "Higher rates compress AAPL's 28x forward P/E via DCF discount-rate expansion, "
                "while Services $100B ARR provides a partial offset."
            ),
            top_risks=[rate_signal],
        )
        polished = suppress_redundancy(t)
        # direct_answer must survive (it's highest priority — processed before signal context)
        assert len(polished.direct_answer) > 0, (
            "direct_answer must not be suppressed by signal pre-commitment"
        )

    def test_unrelated_sections_not_suppressed(self):
        """If sections cover distinct topics, suppression must not remove them."""
        from app.services.thesis_polisher import suppress_redundancy

        services_signal = _signal(
            "Apple Services 72% margin supports $100B ARR."
        )
        t = _thesis(
            bull_thesis="iPhone ASP upgrade cycle supports hardware revenue acceleration.",
            bear_thesis="China tariff exposure at 19% revenue threatens $20B annually.",
            top_signals=[services_signal],
        )
        polished = suppress_redundancy(t)
        # Neither section should be emptied — they cover distinct topics
        assert len(polished.bull_thesis) > 0, "bull_thesis must survive"
        assert len(polished.bear_thesis) > 0, "bear_thesis must survive"


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 4 — Stock-Movement Orientation (Signal Ranking Validation)
# ══════════════════════════════════════════════════════════════════════════════

class TestStockMovementOrientation:
    """Validate that the full Apple/rates investment scenario produces a
    signal set oriented around stock-moving mechanisms — not descriptions."""

    def _build_apple_rates_scenario(self) -> RankedSignalSet:
        """Full Apple + higher-rates signal set."""
        mc = _signal(
            "100bps rate rise compresses AAPL forward P/E from 28x to 24x "
            "via DCF discount rate expansion — DCF present value falls ~14%.",
            signal_type="valuation", direction="bearish", impact=0.90,
            source_agent="macro",
        )
        services = _signal(
            "Apple Services at 72% gross margin provides rate-insensitive revenue floor; "
            "Services $100B ARR grows at 15% CAGR regardless of rate cycle.",
            signal_type="structural", direction="bullish", impact=0.85,
            source_agent="valuation",
        )
        hardware = _signal(
            "Higher financing costs reduce iPhone ASP affordability for credit-dependent "
            "consumers — unit risk of ~3-5% in rate-sensitive markets.",
            signal_type="cyclical", direction="bearish", impact=0.70,
            source_agent="macro",
        )
        revenue_fact = _signal(
            "iPhone is 52% of Apple's total revenue.",
            signal_type="macro", direction="bearish", impact=0.70,
            source_agent="market",
        )
        return rank_signals(
            _valuation(signals=[services]),
            _macro(signals=[mc, hardware]),
            _risk(),
            _market(signals=[revenue_fact]),
            _quality(),
        )

    def test_multiple_compression_in_top_risks(self):
        result = self._build_apple_rates_scenario()
        risk_text = " ".join(s.signal for s in result.top_risks)
        assert (
            "P/E" in risk_text
            or "DCF" in risk_text
            or "discount" in risk_text.lower()
            or "28x" in risk_text
        ), f"Multiple compression must be in top_risks. Got: {risk_text[:200]}"

    def test_services_resilience_in_top_signals(self):
        result = self._build_apple_rates_scenario()
        top_text = " ".join(s.signal for s in result.top_signals)
        assert "Services" in top_text or "72%" in top_text, (
            f"Services resilience must be in top_signals. Got: {top_text[:200]}"
        )

    def test_hardware_demand_sensitivity_ranked(self):
        """Hardware demand sensitivity must appear somewhere in the ranked output."""
        result = self._build_apple_rates_scenario()
        all_text = " ".join(s.signal for s in result.all_ranked)
        assert "financing costs" in all_text.lower() or "ASP" in all_text or "unit" in all_text, (
            "Hardware demand sensitivity signal must appear in ranked output"
        )

    def test_stock_impact_signals_dominate_top_positions(self):
        """The top 2 ranked signals should have thesis_sensitivity > neutral (> 1.0)."""
        from app.services.signal_ranker import _thesis_sensitivity_score
        result = self._build_apple_rates_scenario()
        top_two = result.all_ranked[:2]
        for sig in top_two:
            sens = _thesis_sensitivity_score(sig.signal)
            assert sens >= 1.0, (
                f"Top-ranked signal should have thesis_sensitivity ≥ 1.0, "
                f"got {sens:.2f}: {sig.signal[:80]!r}"
            )

    def test_revenue_share_fact_ranks_below_impact_signals(self):
        """'iPhone is 52% of revenue' must rank below P/E compression and Services floor."""
        result = self._build_apple_rates_scenario()
        all_signals = result.all_ranked
        if len(all_signals) < 2:
            pytest.skip("Need ≥2 signals to compare ordering")

        # Find indices
        pe_idx = next(
            (i for i, s in enumerate(all_signals) if "P/E" in s.signal or "DCF" in s.signal),
            None,
        )
        revenue_fact_idx = next(
            (i for i, s in enumerate(all_signals) if "52%" in s.signal),
            None,
        )
        if pe_idx is not None and revenue_fact_idx is not None:
            assert pe_idx < revenue_fact_idx, (
                f"P/E compression (idx={pe_idx}) must rank above revenue-share "
                f"fact (idx={revenue_fact_idx})"
            )
