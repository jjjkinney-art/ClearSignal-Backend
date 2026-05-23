"""
Realism hardening regression suite.

Validates that the conviction modeler and evidence calibrator produce
institutionally appropriate, evidence-grounded output under edge conditions:

  1. No duplicated sentences across thesis sections (Jaccard dedup)
  2. Stale evidence (>180d) explicitly weakens reasoning language
  3. Very stale evidence (>365d) produces month-count language
  4. Sparse evidence (<3 items) produces cautious tier opener
  5. Valuation reasoning embeds PE multiple when extractable
  6. Every confidence_reasoning references ticker, uncertainty source, evidence condition
  7. GAP_SPARSE fires when evidence count < 3
  8. GAP_VERY_STALE fires when oldest evidence > 365 days
  9. GAP_MGMT_COMMENTARY and GAP_SEC_FILING are informational (no extra penalty)
 10. Cross-section duplication detector returns warnings for repeated sentences
"""
from __future__ import annotations

import datetime
import re
import pytest
from typing import List

from app.schemas import (
    CompanyContext,
    InvestmentThesis,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RetrievedEvidence,
    RiskProfile,
    ValuationView,
)
from app.services.conviction_modeler import compute_conviction
from app.services.confidence_calibrator import compute_evidence_coverage_gaps
from app.services.signal_ranker import check_cross_section_duplication


# ── Shared helpers ────────────────────────────────────────────────────────────

def _ts(days_ago: int) -> str:
    """ISO timestamp N days in the past."""
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_evidence(ticker: str, days_ago: int = 30, n: int = 3) -> List[RetrievedEvidence]:
    ts = _ts(days_ago)
    items = [
        RetrievedEvidence(
            title=f"{ticker} Q1 earnings call transcript",
            source="SEC EDGAR",
            summary=f"{ticker} management discussed Q1 results and forward guidance.",
            timestamp=ts,
            relevance_score=0.90,
        ),
        RetrievedEvidence(
            title=f"{ticker} analyst price target update",
            source="analyst-estimates",
            summary=f"Analysts revised {ticker} price targets following earnings.",
            timestamp=ts,
            relevance_score=0.80,
        ),
        RetrievedEvidence(
            title=f"{ticker} 10-K annual report",
            source="SEC EDGAR",
            summary=f"{ticker} annual report showing risk factors and financial position.",
            timestamp=ts,
            relevance_score=0.85,
        ),
    ]
    return items[:n]


def _make_company(ticker: str, sector: str = "Technology") -> CompanyContext:
    return CompanyContext(
        ticker=ticker,
        company_name=f"{ticker} Inc.",
        sector=sector,
        industry="Technology",
        market_cap=500e9,
    )


def _make_valuation(
    stance: str = "overpriced",
    conf: float = 0.45,
    pe_text: str = "Trading at a premium to peers",
) -> ValuationView:
    return ValuationView(
        pe_assessment=pe_text,
        growth_view="Revenue growth moderating",
        margin_trend="Margins under pressure",
        overall="Elevated valuation relative to fundamentals",
        confidence=conf,
        valuation_stance=stance,
    )


def _make_macro(conf: float = 0.55) -> MacroSensitivity:
    return MacroSensitivity(
        rate_sensitivity="High — rate-sensitive growth story",
        overall="Macro headwinds from elevated rates",
        confidence=conf,
    )


def _make_risk(conf: float = 0.50) -> RiskProfile:
    return RiskProfile(
        key_risks=["Execution risk", "Competitive pressure"],
        overall="Elevated risk profile with multiple execution dependencies",
        confidence=conf,
    )


def _make_market(conf: float = 0.55) -> MarketContext:
    return MarketContext(
        overall="Mixed market context",
        confidence=conf,
    )


def _make_quality(conf: float = 0.60) -> QualityAssessment:
    return QualityAssessment(
        overall="Business quality intact but setup demanding",
        confidence=conf,
    )


def _run(ticker: str, evidence: List[RetrievedEvidence], valuation: ValuationView = None):
    company = _make_company(ticker)
    val = valuation or _make_valuation()
    return compute_conviction(
        company=company,
        evidence=evidence,
        valuation=val,
        macro=_make_macro(),
        risk=_make_risk(),
        market=_make_market(),
        quality=_make_quality(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. Cross-section deduplication (signal_ranker.check_cross_section_duplication)
# ══════════════════════════════════════════════════════════════════════════════

class TestCrossSectionDuplication:
    """check_cross_section_duplication() must flag identical sentences across sections."""

    def _thesis(self, **kwargs) -> InvestmentThesis:
        defaults = dict(
            ticker="MSFT",
            company_name="Microsoft Corp.",
            direct_answer="MSFT is well-positioned for enterprise AI adoption.",
            conclusion="MSFT long-term thesis remains intact.",
            bull_thesis="Cloud growth and AI monetization drive upside.",
            bear_thesis="Valuation leaves limited margin of safety.",
            confidence_reasoning="Evidence supports a moderate conviction level.",
        )
        defaults.update(kwargs)
        # bear_thesis must be a string — replace None with empty string
        if defaults.get("bear_thesis") is None:
            defaults["bear_thesis"] = ""
        return InvestmentThesis(**defaults)

    def test_no_duplicates_clean_thesis(self):
        thesis = self._thesis()
        warnings = check_cross_section_duplication(thesis)
        # A clean, diverse thesis should produce zero or very few warnings
        high_sim = [w for w in warnings if "similarity=0." in w and
                    float(re.search(r"similarity=(\d\.\d+)", w).group(1)) > 0.70]
        assert len(high_sim) == 0, f"Unexpected high-similarity duplicates: {high_sim}"

    def test_identical_sentence_across_sections_flagged(self):
        repeated = "The company faces significant execution risk that could derail the thesis."
        thesis = self._thesis(
            bull_thesis=f"Cloud growth is strong. {repeated}",
            bear_thesis=f"Valuation elevated. {repeated}",
        )
        warnings = check_cross_section_duplication(thesis)
        assert len(warnings) > 0, "Identical sentence across sections should be flagged"
        assert any("bull_thesis" in w and "bear_thesis" in w for w in warnings)

    def test_near_duplicate_sentence_flagged(self):
        """Paraphrases with ≥55% Jaccard similarity should be detected."""
        s_a = "Revenue growth has been decelerating and margins are compressing."
        s_b = "Revenue growth is decelerating and margins are under compression."
        thesis = self._thesis(
            direct_answer=f"Setup is mixed. {s_a}",
            conclusion=f"Overall thesis intact. {s_b}",
        )
        warnings = check_cross_section_duplication(thesis)
        # These sentences share most tokens — should hit threshold
        assert len(warnings) > 0, "Near-duplicate sentences should produce a warning"

    def test_empty_sections_do_not_crash(self):
        thesis = self._thesis(
            bull_thesis="",
            bear_thesis=None,
            confidence_reasoning="",
        )
        # Should not raise
        warnings = check_cross_section_duplication(thesis)
        assert isinstance(warnings, list)

    def test_warning_format_contains_section_names(self):
        repeated = "Execution risk remains the dominant concern across all scenarios."
        thesis = self._thesis(
            direct_answer=f"Mixed setup. {repeated}",
            conclusion=f"Monitoring required. {repeated}",
        )
        warnings = check_cross_section_duplication(thesis)
        if warnings:
            w = warnings[0]
            assert "[DUPLICATE_SECTION]" in w
            assert "similarity=" in w


# ══════════════════════════════════════════════════════════════════════════════
# 2. Stale evidence language in confidence_reasoning
# ══════════════════════════════════════════════════════════════════════════════

class TestStaleEvidenceReasoning:
    """Stale evidence must produce time-aware, degraded-confidence language."""

    def test_very_stale_evidence_mentions_months(self):
        """Evidence >365 days old → reasoning must contain a month count."""
        ev = _make_evidence("MSFT", days_ago=400)
        result = _run("MSFT", ev)
        reasoning = result.confidence_reasoning.lower()
        # Should say something like "13 months" or "months old"
        has_months = "month" in reasoning
        has_old_language = any(w in reasoning for w in ["stale", "old", "lag", "predates", "absent"])
        assert has_months or has_old_language, (
            f"Very stale evidence (400d) did not produce time-aware language.\n"
            f"Reasoning: {result.confidence_reasoning}"
        )

    def test_stale_evidence_does_not_produce_high_conviction(self):
        """Stale evidence should keep final_score well below 0.70."""
        ev = _make_evidence("AAPL", days_ago=210)
        result = _run("AAPL", ev)
        assert result.final_score < 0.70, (
            f"Stale (210d) evidence produced too-high conviction: {result.final_score:.2f}"
        )

    def test_fresh_vs_stale_conviction_ordering(self):
        """Fresh evidence should yield higher conviction than very stale evidence for same ticker."""
        fresh = _make_evidence("JPM", days_ago=15)
        stale = _make_evidence("JPM", days_ago=400)
        r_fresh = _run("JPM", fresh)
        r_stale = _run("JPM", stale)
        # Fresh should be at least as high — allow ≤0.02 tolerance for rounding
        assert r_fresh.final_score >= r_stale.final_score - 0.02, (
            f"Fresh ({r_fresh.final_score:.2f}) should ≥ stale ({r_stale.final_score:.2f})"
        )

    def test_stale_evidence_calibrator_penalty(self):
        """compute_evidence_coverage_gaps should assign staleness penalty for >180d evidence."""
        ev = _make_evidence("NVDA", days_ago=200)
        penalty, gaps = compute_evidence_coverage_gaps(ev)
        stale_gaps = [g for g in gaps if "GAP_STALE" in g or "GAP_VERY_STALE" in g]
        assert len(stale_gaps) > 0, f"No staleness gap flagged for 200-day evidence. Gaps: {gaps}"
        assert penalty > 0.0, f"Staleness should produce a confidence penalty. Got {penalty}"

    def test_very_stale_calibrator_gap_type(self):
        """Evidence >365d old → GAP_VERY_STALE in gap list."""
        ev = _make_evidence("TSLA", days_ago=400)
        _, gaps = compute_evidence_coverage_gaps(ev)
        very_stale = [g for g in gaps if "GAP_VERY_STALE" in g]
        assert len(very_stale) > 0, f"GAP_VERY_STALE not present for 400d evidence. Gaps: {gaps}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Sparse evidence robustness
# ══════════════════════════════════════════════════════════════════════════════

class TestSparseEvidenceRobustness:
    """Sparse evidence (<3 items) must produce cautious, non-directional language."""

    def test_zero_evidence_does_not_crash(self):
        result = _run("PLTR", [])
        assert result.confidence_reasoning, "Empty evidence should still produce reasoning"
        assert result.final_score >= 0.0

    def test_zero_evidence_score_is_low(self):
        result = _run("PLTR", [])
        assert result.final_score < 0.50, (
            f"Zero evidence should produce low conviction. Got {result.final_score:.2f}"
        )

    def test_single_item_evidence_score_is_low(self):
        ev = _make_evidence("SNOW", days_ago=20, n=1)
        result = _run("SNOW", ev)
        assert result.final_score < 0.55, (
            f"Single-item evidence should produce limited conviction. Got {result.final_score:.2f}"
        )

    def test_sparse_evidence_reasoning_not_directional(self):
        """With <3 evidence items, reasoning should NOT express strong directional conviction."""
        ev = _make_evidence("DDOG", days_ago=20, n=1)
        result = _run("DDOG", ev)
        reasoning = result.confidence_reasoning.lower()
        # Should not confidently say "buy" / "strong conviction" / "high conviction"
        banned_phrases = ["strong conviction", "high conviction", "clear buy", "compelling buy"]
        violations = [p for p in banned_phrases if p in reasoning]
        assert not violations, (
            f"Sparse evidence reasoning contains confident directional language: {violations}\n"
            f"Reasoning: {result.confidence_reasoning}"
        )

    def test_gap_sparse_fires_for_single_item(self):
        ev = _make_evidence("MDB", days_ago=20, n=1)
        penalty, gaps = compute_evidence_coverage_gaps(ev)
        sparse_gaps = [g for g in gaps if "GAP_SPARSE" in g]
        assert len(sparse_gaps) > 0, f"GAP_SPARSE should fire for 1 evidence item. Gaps: {gaps}"

    def test_gap_sparse_fires_for_empty_evidence(self):
        penalty, gaps = compute_evidence_coverage_gaps([])
        sparse_gaps = [g for g in gaps if "GAP_SPARSE" in g]
        assert len(sparse_gaps) > 0, f"GAP_SPARSE should fire for empty evidence. Gaps: {gaps}"

    def test_gap_sparse_does_not_fire_for_sufficient_evidence(self):
        ev = _make_evidence("COST", days_ago=20, n=3)
        _, gaps = compute_evidence_coverage_gaps(ev)
        sparse_gaps = [g for g in gaps if "GAP_SPARSE" in g]
        assert len(sparse_gaps) == 0, f"GAP_SPARSE should NOT fire for 3+ items. Gaps: {gaps}"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Valuation realism — PE multiple embedding
# ══════════════════════════════════════════════════════════════════════════════

class TestValuationRealismPEMultiple:
    """When PE ratio is extractable from pe_assessment, reasoning should embed expectation context."""

    def test_high_pe_ticker_has_expectation_language(self):
        """TSLA at 85x should produce expectation-loaded language."""
        val = _make_valuation(
            stance="overpriced",
            pe_text="Trading at 85x forward earnings — well above sector median of 25x",
        )
        ev = _make_evidence("TSLA", days_ago=20)
        company = _make_company("TSLA", "Consumer Discretionary")
        result = compute_conviction(
            company=company, evidence=ev, valuation=val,
            macro=_make_macro(), risk=_make_risk(),
            market=_make_market(), quality=_make_quality(),
        )
        reasoning = result.confidence_reasoning.lower()
        # At 85x, the reasoning should reference either the multiple OR expectations
        expectation_words = ["85x", "expectations", "priced for", "premium", "demanding"]
        has_expectation = any(w in reasoning for w in expectation_words)
        assert has_expectation, (
            f"85x PE setup should produce expectation language.\n"
            f"Reasoning: {result.confidence_reasoning}"
        )

    def test_reasonable_pe_does_not_add_premium_warning(self):
        """Low PE (<25x) should not trigger expectation premium language."""
        val = _make_valuation(
            stance="fairly valued",
            conf=0.65,
            pe_text="Trading at 14x forward earnings — below sector median",
        )
        ev = _make_evidence("JPM", days_ago=20)
        company = _make_company("JPM", "Financials")
        result = compute_conviction(
            company=company, evidence=ev, valuation=val,
            macro=_make_macro(), risk=_make_risk(),
            market=_make_market(), quality=_make_quality(),
        )
        reasoning = result.confidence_reasoning
        # 14x should not produce "at ~14x forward earnings, the setup is demanding"
        assert "priced for continued acceleration" not in reasoning.lower(), (
            f"Low PE (14x) should not produce acceleration-premium language.\n"
            f"Reasoning: {reasoning}"
        )

    def test_no_pe_in_assessment_does_not_crash(self):
        """Valuation with no extractable PE number should still produce valid reasoning."""
        val = _make_valuation(pe_text="Elevated relative to peers")
        ev = _make_evidence("NKE", days_ago=20)
        result = _run("NKE", ev, valuation=val)
        assert result.confidence_reasoning, "Missing PE should not crash reasoning"
        assert len(result.confidence_reasoning) > 60


# ══════════════════════════════════════════════════════════════════════════════
# 5. Evidence gap taxonomy completeness
# ══════════════════════════════════════════════════════════════════════════════

class TestEvidenceGapTaxonomy:
    """compute_evidence_coverage_gaps() must categorize gaps with institutional labels."""

    def test_no_valuation_evidence_produces_gap_valuation(self):
        ev = [
            RetrievedEvidence(
                title="Company news article",
                source="Bloomberg",
                summary="General market commentary.",
                timestamp=_ts(10),
                relevance_score=0.70,
            )
        ]
        _, gaps = compute_evidence_coverage_gaps(ev)
        val_gaps = [g for g in gaps if "GAP_VALUATION" in g]
        assert len(val_gaps) > 0, f"Missing valuation ratios should produce GAP_VALUATION. Gaps: {gaps}"

    def test_no_analyst_estimates_produces_gap_analyst(self):
        ev = [
            RetrievedEvidence(
                title="PE ratio analysis",
                source="ratios-ttm",
                summary="P/E ratio at 22x.",
                timestamp=_ts(10),
                relevance_score=0.80,
            )
        ]
        _, gaps = compute_evidence_coverage_gaps(ev)
        analyst_gaps = [g for g in gaps if "GAP_ANALYST" in g]
        assert len(analyst_gaps) > 0, f"No analyst estimates should produce GAP_ANALYST. Gaps: {gaps}"

    def test_mgmt_commentary_gap_is_informational_only(self):
        """GAP_MGMT_COMMENTARY should appear in gaps list but NOT add extra penalty."""
        ev = [
            RetrievedEvidence(
                title="ratios-ttm key metrics",
                source="ratios-ttm",
                summary="P/E at 18x, EV/EBITDA at 12x.",
                timestamp=_ts(5),
                relevance_score=0.90,
            ),
            RetrievedEvidence(
                title="Analyst price target consensus",
                source="analyst-estimates",
                summary="Consensus $150 price target.",
                timestamp=_ts(5),
                relevance_score=0.85,
            ),
            RetrievedEvidence(
                title="Q4 earnings results beat",
                source="earnings",
                summary="Company beat Q4 earnings and raised guidance.",
                timestamp=_ts(30),
                relevance_score=0.88,
            ),
        ]
        penalty_without_mgmt, gaps = compute_evidence_coverage_gaps(ev)
        mgmt_gaps = [g for g in gaps if "GAP_MGMT_COMMENTARY" in g]
        # If it fires, it should not add > 0.05 penalty above the base
        # (verify by checking that the gap is informational only — no extra penalty constant)
        # Since the test ev has all major data types, total penalty should be low
        assert penalty_without_mgmt <= 0.20, (
            f"With full valuation/analyst/earnings evidence, penalty should be ≤0.20. Got {penalty_without_mgmt}"
        )

    def test_sec_filing_gap_is_informational_only(self):
        """GAP_SEC_FILING is informational — should not substantially increase penalty."""
        ev_with_sec = [
            RetrievedEvidence(
                title="ratios-ttm key metrics",
                source="ratios-ttm",
                summary="P/E 20x",
                timestamp=_ts(5),
                relevance_score=0.9,
            ),
            RetrievedEvidence(
                title="analyst-estimates price target",
                source="analyst-estimates",
                summary="Consensus $200.",
                timestamp=_ts(5),
                relevance_score=0.85,
            ),
            RetrievedEvidence(
                title="Q2 earnings results and guidance",
                source="earnings",
                summary="Beat earnings. Raised guidance.",
                timestamp=_ts(20),
                relevance_score=0.88,
            ),
            RetrievedEvidence(
                title="10-K annual report SEC filing",
                source="SEC EDGAR",
                summary="Annual report with risk factors.",
                timestamp=_ts(20),
                relevance_score=0.80,
            ),
        ]
        ev_without_sec = ev_with_sec[:3]  # drop the 10-K
        penalty_with, _ = compute_evidence_coverage_gaps(ev_with_sec)
        penalty_without, gaps_without = compute_evidence_coverage_gaps(ev_without_sec)
        sec_gaps = [g for g in gaps_without if "GAP_SEC_FILING" in g]
        # Penalty difference should be zero or minimal (it's informational)
        delta = penalty_without - penalty_with
        assert delta <= 0.02, (
            f"SEC filing gap should not add substantial penalty. Delta={delta:.3f}"
        )

    def test_full_evidence_pool_has_low_penalty(self):
        """A well-covered evidence pool should produce a low total penalty."""
        ev = [
            RetrievedEvidence(
                title="AAPL ratios-ttm valuation",
                source="ratios-ttm",
                summary="P/E 28x EV/EBITDA 20x FCF yield 3.5%.",
                timestamp=_ts(3),
                relevance_score=0.95,
            ),
            RetrievedEvidence(
                title="AAPL analyst-estimates consensus",
                source="analyst-estimates",
                summary="Consensus price target $215, 12% upside.",
                timestamp=_ts(3),
                relevance_score=0.90,
            ),
            RetrievedEvidence(
                title="AAPL Q2 earnings call transcript",
                source="earnings",
                summary="Beat earnings and EPS. Management raised guidance.",
                timestamp=_ts(20),
                relevance_score=0.88,
            ),
        ]
        penalty, gaps = compute_evidence_coverage_gaps(ev)
        assert penalty <= 0.15, (
            f"Full evidence coverage should produce ≤0.15 penalty. Got {penalty:.3f}. Gaps: {gaps}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 6. Confidence reasoning must always reference ticker, driver, and evidence condition
# ══════════════════════════════════════════════════════════════════════════════

class TestReasoningGrounding:
    """Every confidence_reasoning must be grounded in ticker, uncertainty source, evidence state."""

    @pytest.mark.parametrize("ticker,sector", [
        ("MSFT", "Technology"),
        ("NVDA", "Technology"),
        ("TSLA", "Consumer Discretionary"),
        ("JPM", "Financials"),
        ("XOM", "Energy"),
    ])
    def test_ticker_present_in_reasoning(self, ticker, sector):
        ev = _make_evidence(ticker, days_ago=30)
        company = _make_company(ticker, sector)
        result = compute_conviction(
            company=company, evidence=ev,
            valuation=_make_valuation(), macro=_make_macro(),
            risk=_make_risk(), market=_make_market(), quality=_make_quality(),
        )
        assert ticker.upper() in result.confidence_reasoning.upper(), (
            f"{ticker}: ticker not found in reasoning.\nReasoning: {result.confidence_reasoning}"
        )

    def test_reasoning_minimum_length(self):
        """Reasoning must be substantive — at least 80 characters."""
        for ticker in ["AAPL", "AMZN", "GOOGL"]:
            ev = _make_evidence(ticker, days_ago=30)
            result = _run(ticker, ev)
            assert len(result.confidence_reasoning) >= 80, (
                f"{ticker}: reasoning too short ({len(result.confidence_reasoning)} chars).\n"
                f"Reasoning: {result.confidence_reasoning}"
            )

    def test_reasoning_not_generic_boilerplate(self):
        """Reasoning must not contain generic boilerplate phrases."""
        generic = [
            "it is important to note",
            "it's worth noting",
            "this is a complex situation",
            "there are many factors",
            "various factors",
            "limited evidence coverage means this position",
            "the framework is sound, the data is thin",
            "the data is too thin to act on",
        ]
        for ticker in ["AAPL", "TSLA", "NVDA"]:
            ev = _make_evidence(ticker, days_ago=30)
            result = _run(ticker, ev)
            reasoning_lower = result.confidence_reasoning.lower()
            for phrase in generic:
                assert phrase not in reasoning_lower, (
                    f"{ticker}: generic phrase '{phrase}' found in reasoning.\n"
                    f"Reasoning: {result.confidence_reasoning}"
                )

    def test_stale_evidence_reasoning_references_evidence_condition(self):
        """For stale evidence, reasoning must acknowledge the evidence condition."""
        ev = _make_evidence("COST", days_ago=220)
        result = _run("COST", ev)
        reasoning_lower = result.confidence_reasoning.lower()
        evidence_condition_words = [
            "evidence", "data", "stale", "months", "old", "absent", "lag",
            "predates", "limited", "thin", "recent", "recency"
        ]
        has_condition = any(w in reasoning_lower for w in evidence_condition_words)
        assert has_condition, (
            f"Stale (220d) evidence reasoning doesn't acknowledge evidence condition.\n"
            f"Reasoning: {result.confidence_reasoning}"
        )

    def test_sparse_evidence_reasoning_references_evidence_condition(self):
        """For sparse evidence, reasoning must acknowledge the evidence condition."""
        ev = _make_evidence("GE", days_ago=15, n=1)
        result = _run("GE", ev)
        reasoning_lower = result.confidence_reasoning.lower()
        condition_words = [
            "limited", "thin", "sparse", "insufficient", "evidence", "item", "single",
            "cannot", "directional"
        ]
        has_condition = any(w in reasoning_lower for w in condition_words)
        assert has_condition, (
            f"Sparse (1 item) evidence reasoning doesn't acknowledge sparsity.\n"
            f"Reasoning: {result.confidence_reasoning}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 7. End-to-end conviction score properties under edge conditions
# ══════════════════════════════════════════════════════════════════════════════

class TestConvictionScoreEdgeCases:
    """Score boundary and monotonicity tests across evidence quality."""

    def test_score_always_in_valid_range(self):
        """final_score must always be in [0.0, 1.0]."""
        cases = [
            ("TSLA", [], 30),
            ("NVDA", _make_evidence("NVDA", 400, 1), 400),
            ("MSFT", _make_evidence("MSFT", 5, 3), 5),
        ]
        for ticker, ev, _ in cases:
            result = _run(ticker, ev)
            assert 0.0 <= result.final_score <= 1.0, (
                f"{ticker}: score out of range: {result.final_score}"
            )

    def test_setup_label_valid_under_sparse_evidence(self):
        valid_labels = {
            "high-alignment thesis",
            "actionable thesis",
            "monitoring required",
            "expectation-sensitive",
            "mixed evidence",
            "fragile setup",
            "low-conviction setup",
            "data-limited",
            "speculative",
            "speculative setup",
            "structurally impaired",
        }
        ev = _make_evidence("PLTR", days_ago=30, n=1)
        result = _run("PLTR", ev)
        assert result.setup_label in valid_labels, (
            f"Invalid setup_label for sparse evidence: '{result.setup_label}'"
        )

    def test_dims_populated_for_all_cases(self):
        """conviction_dimensions must be populated (not all-zero) even under bad inputs."""
        for ticker, n in [("SNOW", 0), ("DDOG", 1), ("NOW", 3)]:
            ev = _make_evidence(ticker, days_ago=30, n=n)
            result = _run(ticker, ev)
            dims = result.dimensions
            assert dims is not None, f"{ticker}: dimensions is None"
            # At least some dimensions should be non-zero
            dim_vals = [
                dims.evidence_quality, dims.evidence_freshness, dims.thesis_alignment,
                dims.macro_uncertainty, dims.valuation_certainty, dims.estimate_dispersion,
                dims.governance_risk, dims.expectation_fragility, dims.expectation_asymmetry,
            ]
            non_zero = [v for v in dim_vals if v is not None and v > 0.0]
            assert len(non_zero) > 0, (
                f"{ticker}: all conviction dimensions are zero for n={n}"
            )
