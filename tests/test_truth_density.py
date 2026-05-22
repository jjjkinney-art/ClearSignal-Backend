"""Regression tests for the Truth Density + Differentiated Cognition phase.

Covers:
1. Always-on FMP evidence fetching (router_service)
2. Confidence calibrator — coverage gap detection and penalty computation
3. Synthesis prompt — provenance block present and correctly conditioned
4. New governance checks — stance-conclusion alignment, stale-evidence warning
5. End-to-end confidence chain — realism cap + coverage gap penalty compound
"""
from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

BASE = "app"


def _make_evidence(
    title: str = "Test Evidence",
    source: str = "newsapi",
    summary: str = "Some summary text.",
    timestamp: str = "2026-04-01T00:00:00Z",
    relevance_score: float = 0.8,
) -> "RetrievedEvidence":  # noqa: F821
    from app.schemas import RetrievedEvidence
    return RetrievedEvidence(
        title=title,
        source=source,
        summary=summary,
        timestamp=timestamp,
        relevance_score=relevance_score,
    )


def _fmp_valuation_ev(**kwargs) -> "RetrievedEvidence":  # noqa: F821
    return _make_evidence(
        title="AAPL Valuation Ratios TTM",
        source="FMP ratios-ttm",
        summary="P/E TTM: 28.4x. EV/EBITDA: 19.2x. FCF yield: 3.8%.",
        **kwargs,
    )


def _fmp_analyst_ev(**kwargs) -> "RetrievedEvidence":  # noqa: F821
    return _make_evidence(
        title="AAPL Analyst Estimates & Price Target Consensus",
        source="FMP analyst-estimates",
        summary="Consensus target: $215. 32 buys, 8 holds, 2 sells.",
        **kwargs,
    )


def _earnings_ev(timestamp: str = "2026-03-15T00:00:00Z", **kwargs) -> "RetrievedEvidence":  # noqa: F821
    return _make_evidence(
        title="AAPL Q2 2026 Earnings Results",
        source="newsapi",
        summary="EPS beat: $1.89 actual vs $1.77 estimate. Revenue $96.4B.",
        timestamp=timestamp,
        **kwargs,
    )


def _stale_ev(days_old: int = 200) -> "RetrievedEvidence":  # noqa: F821
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return _make_evidence(
        title="Old macro note",
        source="research",
        summary="Fed may hike.",
        timestamp=ts,
    )


# ── 1. Confidence calibrator ──────────────────────────────────────────────────

class TestConfidenceCalibratorStructure:
    """Validate that the confidence_calibrator module exists and exports correctly."""

    def test_module_importable(self):
        from app.services import confidence_calibrator  # noqa: F401

    def test_function_exported(self):
        from app.services.confidence_calibrator import compute_evidence_coverage_gaps
        assert callable(compute_evidence_coverage_gaps)

    def test_returns_tuple(self):
        from app.services.confidence_calibrator import compute_evidence_coverage_gaps
        penalty, gaps = compute_evidence_coverage_gaps([])
        assert isinstance(penalty, float)
        assert isinstance(gaps, list)

    def test_empty_evidence_nonzero_penalty(self):
        from app.services.confidence_calibrator import compute_evidence_coverage_gaps
        penalty, gaps = compute_evidence_coverage_gaps([])
        assert penalty > 0.0
        assert len(gaps) >= 1


class TestCoverageGapDetection:
    """Each coverage gap triggers the correct penalty."""

    def test_no_live_valuation_penalty(self):
        """Missing FMP valuation evidence applies -0.08 penalty."""
        from app.services.confidence_calibrator import (
            compute_evidence_coverage_gaps,
            _PENALTY_NO_LIVE_VALUATION,
        )
        # Analyst + earnings present, NO valuation ratios
        ev = [_fmp_analyst_ev(), _earnings_ev()]
        penalty, gaps = compute_evidence_coverage_gaps(ev)
        assert penalty >= _PENALTY_NO_LIVE_VALUATION
        assert any("valuation" in g.lower() for g in gaps)

    def test_no_analyst_estimates_penalty(self):
        """Missing analyst estimates applies -0.05 penalty."""
        from app.services.confidence_calibrator import (
            compute_evidence_coverage_gaps,
            _PENALTY_NO_ANALYST_ESTIMATES,
        )
        ev = [_fmp_valuation_ev(), _earnings_ev()]
        penalty, gaps = compute_evidence_coverage_gaps(ev)
        assert penalty >= _PENALTY_NO_ANALYST_ESTIMATES
        assert any("analyst" in g.lower() for g in gaps)

    def test_no_recent_earnings_penalty(self):
        """Missing recent earnings (< 90d) applies -0.08 penalty."""
        from app.services.confidence_calibrator import (
            compute_evidence_coverage_gaps,
            _PENALTY_NO_RECENT_EARNINGS,
        )
        # Stale evidence — no earnings within 90 days
        ev = [_fmp_valuation_ev(), _fmp_analyst_ev(), _stale_ev(days_old=120)]
        penalty, gaps = compute_evidence_coverage_gaps(ev)
        assert penalty >= _PENALTY_NO_RECENT_EARNINGS
        assert any("earnings" in g.lower() for g in gaps)

    def test_stale_evidence_beyond_180_days_penalty(self):
        """Evidence older than 180 days applies -0.12 penalty."""
        from app.services.confidence_calibrator import (
            compute_evidence_coverage_gaps,
            _PENALTY_STALE_BEYOND_180,
        )
        ev = [_stale_ev(days_old=200)]
        penalty, gaps = compute_evidence_coverage_gaps(ev)
        assert penalty >= _PENALTY_STALE_BEYOND_180
        assert any("stale" in g.lower() for g in gaps)

    def test_stale_evidence_90_to_180_penalty(self):
        """Evidence 90–180 days old applies moderate staleness but NOT the severe penalty."""
        from app.services.confidence_calibrator import (
            compute_evidence_coverage_gaps,
            _PENALTY_STALE_90_TO_180,
            _PENALTY_STALE_BEYOND_180,
        )
        ev = [_stale_ev(days_old=130)]
        penalty, gaps = compute_evidence_coverage_gaps(ev)
        # Moderate staleness penalty applied
        assert penalty >= _PENALTY_STALE_90_TO_180
        # Severe staleness penalty NOT applied (only moderate)
        # The difference between what is actually applied and the severe penalty
        # should be less than the severe threshold (it can't be BOTH)
        assert not any(">" in g and "180" in g for g in gaps), \
            "Moderate staleness should not produce a '> 180d' gap message"

    def test_all_coverage_present_zero_penalty(self):
        """Full coverage — recent FMP + analyst + earnings — yields zero penalty."""
        from app.services.confidence_calibrator import compute_evidence_coverage_gaps
        ev = [
            _fmp_valuation_ev(),
            _fmp_analyst_ev(),
            _earnings_ev(timestamp="2026-04-20T00:00:00Z"),  # < 90 days ago
            _make_evidence(timestamp="2026-04-10T00:00:00Z"),  # recent general
        ]
        penalty, gaps = compute_evidence_coverage_gaps(ev)
        assert penalty == 0.0
        assert gaps == []

    def test_penalty_is_additive(self):
        """Multiple gaps compound: total >= sum of individual penalties."""
        import pytest
        from app.services.confidence_calibrator import (
            compute_evidence_coverage_gaps,
            _PENALTY_NO_LIVE_VALUATION,
            _PENALTY_NO_ANALYST_ESTIMATES,
            _PENALTY_NO_RECENT_EARNINGS,
        )
        # No FMP, no analyst, no recent earnings
        ev = [_make_evidence(source="newsapi", timestamp="2025-10-01T00:00:00Z")]
        penalty, gaps = compute_evidence_coverage_gaps(ev)
        expected_min = round(
            _PENALTY_NO_LIVE_VALUATION
            + _PENALTY_NO_ANALYST_ESTIMATES
            + _PENALTY_NO_RECENT_EARNINGS,
            4,
        )
        assert round(penalty, 6) >= round(expected_min, 6)

    def test_penalty_is_float(self):
        from app.services.confidence_calibrator import compute_evidence_coverage_gaps
        penalty, _ = compute_evidence_coverage_gaps([_make_evidence()])
        assert isinstance(penalty, float)

    def test_penalty_never_negative(self):
        from app.services.confidence_calibrator import compute_evidence_coverage_gaps
        penalty, _ = compute_evidence_coverage_gaps([_make_evidence()])
        assert penalty >= 0.0


class TestCoverageDetectorFunctions:
    """Unit tests for individual detector helpers."""

    def test_has_live_valuation_detects_ratios_ttm(self):
        from app.services.confidence_calibrator import _has_live_valuation
        ev = [_fmp_valuation_ev()]
        assert _has_live_valuation(ev) is True

    def test_has_live_valuation_false_for_generic(self):
        from app.services.confidence_calibrator import _has_live_valuation
        ev = [_make_evidence(source="newsapi")]
        assert _has_live_valuation(ev) is False

    def test_has_analyst_estimates_detects(self):
        from app.services.confidence_calibrator import _has_analyst_estimates
        ev = [_fmp_analyst_ev()]
        assert _has_analyst_estimates(ev) is True

    def test_has_analyst_estimates_false_for_generic(self):
        from app.services.confidence_calibrator import _has_analyst_estimates
        ev = [_make_evidence(source="sec")]
        assert _has_analyst_estimates(ev) is False

    def test_has_recent_earnings_detects_fresh(self):
        from app.services.confidence_calibrator import _has_recent_earnings
        ev = [_earnings_ev(timestamp="2026-05-01T00:00:00Z")]
        assert _has_recent_earnings(ev) is True

    def test_has_recent_earnings_false_for_old(self):
        from app.services.confidence_calibrator import _has_recent_earnings
        old_ts = (datetime.now(timezone.utc) - timedelta(days=150)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        ev = [_earnings_ev(timestamp=old_ts)]
        assert _has_recent_earnings(ev) is False

    def test_has_recent_earnings_no_timestamp_returns_true(self):
        """Earnings evidence with no timestamp gets benefit of doubt."""
        from app.services.confidence_calibrator import _has_recent_earnings
        ev = [_make_evidence(title="Q3 Earnings Results", timestamp="")]
        assert _has_recent_earnings(ev) is True

    def test_oldest_evidence_age_days_parseable(self):
        from app.services.confidence_calibrator import _oldest_evidence_age_days
        ts = (datetime.now(timezone.utc) - timedelta(days=45)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        ev = [_make_evidence(timestamp=ts)]
        age = _oldest_evidence_age_days(ev)
        assert age is not None
        assert 44 <= age <= 46  # allow 1-day slop

    def test_oldest_evidence_age_days_no_timestamps(self):
        from app.services.confidence_calibrator import _oldest_evidence_age_days
        ev = [_make_evidence(timestamp="")]
        age = _oldest_evidence_age_days(ev)
        assert age is None

    def test_parse_timestamp_iso_format(self):
        from app.services.confidence_calibrator import _parse_timestamp
        dt = _parse_timestamp("2026-01-15T10:30:00Z")
        assert dt is not None
        assert dt.year == 2026

    def test_parse_timestamp_date_only(self):
        from app.services.confidence_calibrator import _parse_timestamp
        dt = _parse_timestamp("2025-06-01")
        assert dt is not None
        assert dt.month == 6

    def test_parse_timestamp_year_month(self):
        from app.services.confidence_calibrator import _parse_timestamp
        dt = _parse_timestamp("2025-03")
        assert dt is not None
        assert dt.year == 2025

    def test_parse_timestamp_none_input(self):
        from app.services.confidence_calibrator import _parse_timestamp
        assert _parse_timestamp(None) is None

    def test_parse_timestamp_empty_string(self):
        from app.services.confidence_calibrator import _parse_timestamp
        assert _parse_timestamp("") is None

    def test_parse_timestamp_garbage_returns_none(self):
        from app.services.confidence_calibrator import _parse_timestamp
        assert _parse_timestamp("not-a-date") is None


# ── 2. Always-on FMP evidence in router ───────────────────────────────────────

class TestAlwaysOnFmpEvidence:
    """router_service._run_investment_pipeline fetches FMP for all queries."""

    def _minimal_mocks(self):
        """Return a base set of patches covering the investment pipeline."""
        return [
            patch("app.services.router_service.retrieve_market_evidence", return_value=[]),
            patch("app.services.router_service.retrieve_general_finance_evidence", return_value=[]),
            patch("app.services.router_service.get_profile_for_company", return_value=None),
            patch("app.services.router_service.partition_evidence"),
            patch("app.services.router_service.run_valuation_agent"),
            patch("app.services.router_service.run_investment_macro_agent"),
            patch("app.services.router_service.run_risk_agent"),
            patch("app.services.router_service.run_market_agent"),
            patch("app.services.router_service.run_quality_agent"),
            patch("app.services.router_service.synthesize_thesis"),
            patch("app.services.router_service.watchlist_service"),
        ]

    def _make_agent_returns(self):
        """Stub return values for agent calls."""
        from app.schemas import (
            ValuationView, MacroSensitivity, RiskProfile,
            MarketContext, QualityAssessment, InvestmentThesis,
        )
        val = ValuationView(overall="val", confidence=0.7)
        mac = MacroSensitivity(overall="mac", confidence=0.7)
        risk = RiskProfile(overall="risk", confidence=0.7)
        mkt = MarketContext(overall="mkt", confidence=0.7)
        qual = QualityAssessment(overall="qual", confidence=0.7)
        thesis = InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.",
            bull_thesis="b", bear_thesis="b",
            conclusion="c", confidence_score=0.7,
        )
        return val, mac, risk, mkt, qual, thesis

    def test_valuation_ratios_called_for_non_valuation_question(self):
        """fetch_valuation_ratios is called even for a general company question."""
        from app.schemas import CompanyContext
        from app.services.router_service import _run_investment_pipeline

        company = CompanyContext(ticker="AAPL", company_name="Apple Inc.")
        val, mac, risk, mkt, qual, thesis = self._make_agent_returns()

        with patch("app.services.router_service.fetch_valuation_ratios", return_value=[]) as mock_val, \
             patch("app.services.router_service.fetch_analyst_estimates", return_value=[]) as mock_est, \
             patch("app.services.router_service.retrieve_market_evidence", return_value=[]), \
             patch("app.services.router_service.retrieve_general_finance_evidence", return_value=[]), \
             patch("app.services.router_service._detect_topics", return_value=[]), \
             patch("app.services.router_service.get_profile_for_company", return_value=None), \
             patch("app.services.router_service.partition_evidence", return_value=MagicMock(
                 valuation=[], macro=[], risk=[], market=[], quality=[]
             )), \
             patch("app.services.router_service.run_valuation_agent", return_value=val), \
             patch("app.services.router_service.run_investment_macro_agent", return_value=mac), \
             patch("app.services.router_service.run_risk_agent", return_value=risk), \
             patch("app.services.router_service.run_market_agent", return_value=mkt), \
             patch("app.services.router_service.run_quality_agent", return_value=qual), \
             patch("app.services.router_service.synthesize_thesis", return_value=thesis), \
             patch("app.services.router_service.watchlist_service"):
            _run_investment_pipeline(company, "Tell me about Apple", "req-1")

        # Must be called regardless of question type
        mock_val.assert_called_once_with("AAPL")
        mock_est.assert_called_once_with("AAPL")

    def test_valuation_ratios_called_for_valuation_question(self):
        """fetch_valuation_ratios also called for valuation_stance questions."""
        from app.schemas import CompanyContext
        from app.services.router_service import _run_investment_pipeline

        company = CompanyContext(ticker="AAPL", company_name="Apple Inc.")
        val, mac, risk, mkt, qual, thesis = self._make_agent_returns()

        with patch("app.services.router_service.fetch_valuation_ratios", return_value=[]) as mock_val, \
             patch("app.services.router_service.fetch_analyst_estimates", return_value=[]) as mock_est, \
             patch("app.services.router_service.retrieve_market_evidence", return_value=[]), \
             patch("app.services.router_service.retrieve_general_finance_evidence", return_value=[]), \
             patch("app.services.router_service._detect_topics", return_value=[]), \
             patch("app.services.router_service.get_profile_for_company", return_value=None), \
             patch("app.services.router_service.partition_evidence", return_value=MagicMock(
                 valuation=[], macro=[], risk=[], market=[], quality=[]
             )), \
             patch("app.services.router_service.run_valuation_agent", return_value=val), \
             patch("app.services.router_service.run_investment_macro_agent", return_value=mac), \
             patch("app.services.router_service.run_risk_agent", return_value=risk), \
             patch("app.services.router_service.run_market_agent", return_value=mkt), \
             patch("app.services.router_service.run_quality_agent", return_value=qual), \
             patch("app.services.router_service.synthesize_thesis", return_value=thesis), \
             patch("app.services.router_service.watchlist_service"):
            _run_investment_pipeline(company, "Is Apple stock overpriced?", "req-2")

        mock_val.assert_called_once_with("AAPL")
        mock_est.assert_called_once_with("AAPL")

    def test_fmp_failure_does_not_crash_pipeline(self):
        """When FMP raises an exception, the pipeline continues without crashing."""
        from app.schemas import CompanyContext
        from app.services.router_service import _run_investment_pipeline

        company = CompanyContext(ticker="AAPL", company_name="Apple Inc.")
        _, mac, risk, mkt, qual, thesis = self._make_agent_returns()
        from app.schemas import ValuationView
        val = ValuationView(overall="val", confidence=0.7)

        with patch("app.services.router_service.fetch_valuation_ratios",
                   side_effect=RuntimeError("FMP down")), \
             patch("app.services.router_service.fetch_analyst_estimates",
                   side_effect=RuntimeError("FMP down")), \
             patch("app.services.router_service.retrieve_market_evidence", return_value=[]), \
             patch("app.services.router_service.retrieve_general_finance_evidence", return_value=[]), \
             patch("app.services.router_service._detect_topics", return_value=[]), \
             patch("app.services.router_service.get_profile_for_company", return_value=None), \
             patch("app.services.router_service.partition_evidence", return_value=MagicMock(
                 valuation=[], macro=[], risk=[], market=[], quality=[]
             )), \
             patch("app.services.router_service.run_valuation_agent", return_value=val), \
             patch("app.services.router_service.run_investment_macro_agent", return_value=mac), \
             patch("app.services.router_service.run_risk_agent", return_value=risk), \
             patch("app.services.router_service.run_market_agent", return_value=mkt), \
             patch("app.services.router_service.run_quality_agent", return_value=qual), \
             patch("app.services.router_service.synthesize_thesis", return_value=thesis), \
             patch("app.services.router_service.watchlist_service"):
            result = _run_investment_pipeline(company, "Tell me about Apple", "req-3")

        # Pipeline must not crash; result is an AgentAnswerResponse
        assert result is not None

    def test_fmp_evidence_appended_to_evidence_pool(self):
        """FMP evidence items returned by fetch_valuation_ratios are passed to agents."""
        from app.schemas import CompanyContext
        from app.services.router_service import _run_investment_pipeline

        company = CompanyContext(ticker="MSFT", company_name="Microsoft")
        _, mac, risk, mkt, qual, thesis = self._make_agent_returns()
        from app.schemas import ValuationView
        val = ValuationView(overall="val", confidence=0.7)
        fmp_item = _fmp_valuation_ev()

        captured = {}

        def capture_partition(ev_list, _company):
            captured["evidence"] = ev_list
            return MagicMock(valuation=[], macro=[], risk=[], market=[], quality=[])

        with patch("app.services.router_service.fetch_valuation_ratios",
                   return_value=[fmp_item]), \
             patch("app.services.router_service.fetch_analyst_estimates", return_value=[]), \
             patch("app.services.router_service.retrieve_market_evidence", return_value=[]), \
             patch("app.services.router_service.retrieve_general_finance_evidence", return_value=[]), \
             patch("app.services.router_service._detect_topics", return_value=[]), \
             patch("app.services.router_service.get_profile_for_company", return_value=None), \
             patch("app.services.router_service.partition_evidence", side_effect=capture_partition), \
             patch("app.services.router_service.run_valuation_agent", return_value=val), \
             patch("app.services.router_service.run_investment_macro_agent", return_value=mac), \
             patch("app.services.router_service.run_risk_agent", return_value=risk), \
             patch("app.services.router_service.run_market_agent", return_value=mkt), \
             patch("app.services.router_service.run_quality_agent", return_value=qual), \
             patch("app.services.router_service.synthesize_thesis", return_value=thesis), \
             patch("app.services.router_service.watchlist_service"):
            _run_investment_pipeline(company, "Tell me about Microsoft", "req-4")

        assert fmp_item in captured.get("evidence", [])


# ── 3. Synthesis prompt — provenance block ────────────────────────────────────

class TestProvenanceBlockInPrompt:
    """_build_synthesis_prompt injects a provenance block based on evidence."""

    def _make_company(self, ticker: str = "AAPL", name: str = "Apple Inc."):
        from app.schemas import CompanyContext
        return CompanyContext(ticker=ticker, company_name=name)

    def _make_agents(self):
        from app.schemas import (
            ValuationView, MacroSensitivity, RiskProfile,
            MarketContext, QualityAssessment,
        )
        return (
            ValuationView(overall="v", confidence=0.7),
            MacroSensitivity(overall="m", confidence=0.7),
            RiskProfile(overall="r", confidence=0.7),
            MarketContext(overall="mk", confidence=0.7),
            QualityAssessment(overall="q", confidence=0.7),
        )

    def _build(self, evidence, **kwargs):
        from app.services.thesis_synthesizer import _build_synthesis_prompt
        company = self._make_company()
        val, mac, risk, mkt, qual = self._make_agents()
        return _build_synthesis_prompt(
            company, val, mac, risk, mkt, qual, evidence, **kwargs
        )

    def test_provenance_block_present_with_live_valuation(self):
        """When FMP valuation evidence present, prompt says MUST cite ratio."""
        ev = [_fmp_valuation_ev()]
        prompt = self._build(ev)
        assert "EVIDENCE PROVENANCE" in prompt
        assert "ratios" in prompt.lower() or "ratio" in prompt.lower()

    def test_provenance_block_no_valuation_warns(self):
        """Without live valuation, prompt warns to qualify claims."""
        ev = [_make_evidence(source="newsapi")]
        prompt = self._build(ev)
        assert "No live valuation ratios" in prompt

    def test_provenance_block_with_analyst_estimates(self):
        """With analyst estimates, prompt requires consensus target citation."""
        ev = [_fmp_valuation_ev(), _fmp_analyst_ev()]
        prompt = self._build(ev)
        assert "consensus" in prompt.lower() or "analyst" in prompt.lower()

    def test_provenance_block_no_analyst_warns(self):
        """Without analyst data, prompt forbids asserting consensus."""
        ev = [_fmp_valuation_ev()]
        prompt = self._build(ev)
        assert "No analyst estimate" in prompt

    def test_provenance_block_stale_evidence_warns(self):
        """Stale evidence beyond 180d produces a WARNING in the prompt."""
        ev = [_stale_ev(days_old=200)]
        prompt = self._build(ev)
        assert "WARNING" in prompt or "stale" in prompt.lower()

    def test_provenance_block_citation_requirement_always_present(self):
        """Citation requirement [N] instruction appears regardless of coverage."""
        prompt = self._build([_make_evidence()])
        assert "citation" in prompt.lower() or "[N]" in prompt

    def test_hallucination_prevention_block_present(self):
        """HALLUCINATION PREVENTION rules are always in the prompt."""
        prompt = self._build([_make_evidence()])
        assert "HALLUCINATION PREVENTION" in prompt or "NEVER invent" in prompt

    def test_fresh_evidence_no_stale_warning(self):
        """Recent evidence should NOT trigger the staleness warning."""
        ev = [_make_evidence(timestamp="2026-05-01T00:00:00Z")]
        prompt = self._build(ev)
        assert "WARNING: Oldest evidence is" not in prompt


# ── 4. Governance checks ──────────────────────────────────────────────────────

class TestStanceConclusionAlignment:
    """_check_stance_conclusion_alignment catches contradictions."""

    def _make_valuation(self, stance: str, confidence: float = 0.7):
        from app.schemas import ValuationView
        return ValuationView(
            overall="v", confidence=confidence, valuation_stance=stance
        )

    def _make_thesis(self, conclusion: str, direct_answer: str = ""):
        from app.schemas import InvestmentThesis
        return InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.",
            bull_thesis="b", bear_thesis="b",
            conclusion=conclusion,
            direct_answer=direct_answer,
            confidence_score=0.7,
        )

    def test_overpriced_with_buy_language_flags(self):
        from app.services.thesis_synthesizer import _check_stance_conclusion_alignment
        val = self._make_valuation("overpriced")
        thesis = self._make_thesis(
            conclusion="At current levels this represents an attractive buy opportunity."
        )
        warnings = _check_stance_conclusion_alignment(val, thesis)
        assert len(warnings) == 1
        assert "overpriced" in warnings[0].lower() or "contradiction" in warnings[0].lower()

    def test_underpriced_with_sell_language_flags(self):
        from app.services.thesis_synthesizer import _check_stance_conclusion_alignment
        val = self._make_valuation("underpriced")
        thesis = self._make_thesis(
            conclusion="We recommend selling at current prices given stretched valuation."
        )
        warnings = _check_stance_conclusion_alignment(val, thesis)
        assert len(warnings) == 1

    def test_overpriced_with_bearish_conclusion_no_flag(self):
        from app.services.thesis_synthesizer import _check_stance_conclusion_alignment
        val = self._make_valuation("overpriced")
        thesis = self._make_thesis(
            conclusion="At ~32x forward earnings the stock is overvalued; we would reduce."
        )
        warnings = _check_stance_conclusion_alignment(val, thesis)
        assert len(warnings) == 0

    def test_fairly_valued_no_flag(self):
        from app.services.thesis_synthesizer import _check_stance_conclusion_alignment
        val = self._make_valuation("fairly_valued")
        thesis = self._make_thesis(
            conclusion="We would buy on weakness; the stock looks attractive at these levels."
        )
        warnings = _check_stance_conclusion_alignment(val, thesis)
        assert len(warnings) == 0

    def test_cannot_determine_no_flag(self):
        from app.services.thesis_synthesizer import _check_stance_conclusion_alignment
        val = self._make_valuation("cannot_determine")
        thesis = self._make_thesis(conclusion="Unclear valuation picture.")
        warnings = _check_stance_conclusion_alignment(val, thesis)
        assert len(warnings) == 0

    def test_empty_stance_no_flag(self):
        from app.services.thesis_synthesizer import _check_stance_conclusion_alignment
        val = self._make_valuation("")
        thesis = self._make_thesis(conclusion="Buy the stock.")
        warnings = _check_stance_conclusion_alignment(val, thesis)
        assert len(warnings) == 0

    def test_warning_contains_ticker(self):
        from app.services.thesis_synthesizer import _check_stance_conclusion_alignment
        val = self._make_valuation("overpriced")
        thesis = self._make_thesis(
            conclusion="Buy AAPL at these levels.", direct_answer="Accumulate on dips."
        )
        warnings = _check_stance_conclusion_alignment(val, thesis)
        if warnings:
            assert "AAPL" in warnings[0]


class TestStaleEvidenceGovernance:
    """_check_stale_evidence_warning fires when evidence is old + confidence high."""

    def _make_thesis(self, confidence: float):
        from app.schemas import InvestmentThesis
        return InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.",
            bull_thesis="b", bear_thesis="b",
            conclusion="c", confidence_score=confidence,
        )

    def test_stale_evidence_high_confidence_warns(self):
        from app.services.thesis_synthesizer import _check_stale_evidence_warning
        ev = [_stale_ev(days_old=200)]
        thesis = self._make_thesis(confidence=0.75)
        warnings = _check_stale_evidence_warning(ev, thesis)
        assert len(warnings) >= 1
        assert any("stale" in w.lower() for w in warnings)

    def test_stale_evidence_low_confidence_no_warn(self):
        from app.services.thesis_synthesizer import _check_stale_evidence_warning
        ev = [_stale_ev(days_old=200)]
        thesis = self._make_thesis(confidence=0.50)
        warnings = _check_stale_evidence_warning(ev, thesis)
        assert len(warnings) == 0

    def test_fresh_evidence_no_warn(self):
        from app.services.thesis_synthesizer import _check_stale_evidence_warning
        ev = [_make_evidence(timestamp="2026-05-10T00:00:00Z")]
        thesis = self._make_thesis(confidence=0.85)
        warnings = _check_stale_evidence_warning(ev, thesis)
        assert len(warnings) == 0


# ── 5. Confidence chain — coverage gap applied in synthesize_thesis ───────────

class TestConfidenceChainInSynthesizer:
    """compute_evidence_coverage_gaps penalty is applied inside synthesize_thesis."""

    def _make_company(self):
        from app.schemas import CompanyContext
        return CompanyContext(ticker="NVDA", company_name="NVIDIA Corporation")

    def _make_thesis_stub(self, confidence: float = 0.85):
        from app.schemas import InvestmentThesis
        return InvestmentThesis(
            ticker="NVDA", company_name="NVIDIA Corporation",
            bull_thesis="H100 data-center demand drives earnings beat.",
            bear_thesis="Margin compression from custom silicon erosion.",
            conclusion="Constructive on NVDA at current multiple.",
            confidence_score=confidence,
            confidence_reasoning="High evidence agreement.",
        )

    def _make_agents(self, conf: float = 0.75):
        from app.schemas import (
            ValuationView, MacroSensitivity, RiskProfile,
            MarketContext, QualityAssessment,
        )
        return (
            ValuationView(overall="v", confidence=conf),
            MacroSensitivity(overall="m", confidence=conf),
            RiskProfile(overall="r", confidence=conf),
            MarketContext(overall="mk", confidence=conf),
            QualityAssessment(overall="q", confidence=conf),
        )

    def test_coverage_gap_lowers_confidence(self):
        """synthesize_thesis lowers confidence when FMP evidence is absent."""
        from app.services.thesis_synthesizer import synthesize_thesis
        from app.schemas import CompanyContext

        company = self._make_company()
        val, mac, risk, mkt, qual = self._make_agents()
        stub_thesis = self._make_thesis_stub(confidence=0.85)

        # Evidence with no FMP coverage — should trigger penalty
        evidence = [_make_evidence(source="newsapi", timestamp="2026-04-01T00:00:00Z")]

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement",
                   return_value=stub_thesis), \
             patch("app.services.thesis_synthesizer.rank_signals",
                   return_value=None), \
             patch("app.services.thesis_synthesizer._detect_dominant_dimension",
                   return_value="valuation"), \
             patch("app.services.thesis_synthesizer.check_synthesis_depth",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.check_forbidden_phrases",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.detect_signal_overlap",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.polish_thesis",
                   side_effect=lambda t, **kw: t), \
             patch("app.services.thesis_synthesizer.compute_confidence_realism_cap",
                   return_value=(0.85, [])):  # bypass realism cap
            result = synthesize_thesis(
                company=company,
                valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
                evidence=evidence,
            )

        # The result confidence must be LOWER than the stub's 0.85 because gaps
        assert result.confidence_score < 0.85

    def test_full_coverage_no_penalty(self):
        """With full FMP + analyst + earnings coverage, no coverage penalty applied."""
        from app.services.thesis_synthesizer import synthesize_thesis
        from app.schemas import CompanyContext

        company = self._make_company()
        val, mac, risk, mkt, qual = self._make_agents()
        stub_thesis = self._make_thesis_stub(confidence=0.78)

        evidence = [
            _fmp_valuation_ev(timestamp="2026-05-10T00:00:00Z"),
            _fmp_analyst_ev(timestamp="2026-05-10T00:00:00Z"),
            _earnings_ev(timestamp="2026-05-01T00:00:00Z"),
        ]

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement",
                   return_value=stub_thesis), \
             patch("app.services.thesis_synthesizer.rank_signals",
                   return_value=None), \
             patch("app.services.thesis_synthesizer._detect_dominant_dimension",
                   return_value="valuation"), \
             patch("app.services.thesis_synthesizer.check_synthesis_depth",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.check_forbidden_phrases",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.detect_signal_overlap",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.polish_thesis",
                   side_effect=lambda t, **kw: t), \
             patch("app.services.thesis_synthesizer.compute_confidence_realism_cap",
                   return_value=(0.78, [])):
            result = synthesize_thesis(
                company=company,
                valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
                evidence=evidence,
            )

        # With full coverage the score should be unchanged (or very close)
        assert abs(result.confidence_score - 0.78) < 0.01

    def test_confidence_never_goes_negative(self):
        """Accumulated penalties never push confidence below 0."""
        from app.services.thesis_synthesizer import synthesize_thesis

        company = self._make_company()
        val, mac, risk, mkt, qual = self._make_agents(conf=0.0)
        stub_thesis = self._make_thesis_stub(confidence=0.05)

        evidence = []  # no evidence — maximum penalty

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement",
                   return_value=stub_thesis), \
             patch("app.services.thesis_synthesizer.rank_signals",
                   return_value=None), \
             patch("app.services.thesis_synthesizer._detect_dominant_dimension",
                   return_value="valuation"), \
             patch("app.services.thesis_synthesizer.check_synthesis_depth",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.check_forbidden_phrases",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.detect_signal_overlap",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.polish_thesis",
                   side_effect=lambda t, **kw: t), \
             patch("app.services.thesis_synthesizer.compute_confidence_realism_cap",
                   return_value=(0.05, [])):
            result = synthesize_thesis(
                company=company,
                valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
                evidence=evidence,
            )

        assert result.confidence_score >= 0.0

    def test_gap_descriptions_appended_to_confidence_reasoning(self):
        """Coverage gap descriptions appear in confidence_reasoning."""
        from app.services.thesis_synthesizer import synthesize_thesis

        company = self._make_company()
        val, mac, risk, mkt, qual = self._make_agents()
        stub_thesis = self._make_thesis_stub(confidence=0.80)
        stub_thesis.confidence_reasoning = "Agent agreement high."

        evidence = [_make_evidence(source="newsapi")]  # no FMP coverage

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement",
                   return_value=stub_thesis), \
             patch("app.services.thesis_synthesizer.rank_signals",
                   return_value=None), \
             patch("app.services.thesis_synthesizer._detect_dominant_dimension",
                   return_value="valuation"), \
             patch("app.services.thesis_synthesizer.check_synthesis_depth",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.check_forbidden_phrases",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.detect_signal_overlap",
                   return_value=[]), \
             patch("app.services.thesis_synthesizer.polish_thesis",
                   side_effect=lambda t, **kw: t), \
             patch("app.services.thesis_synthesizer.compute_confidence_realism_cap",
                   return_value=(0.80, [])):
            result = synthesize_thesis(
                company=company,
                valuation=val, macro=mac, risk=risk, market=mkt, quality=qual,
                evidence=evidence,
            )

        assert "Coverage gaps" in (result.confidence_reasoning or "")


# ── 6. Build provenance block unit tests ─────────────────────────────────────

class TestBuildLiveDataProvenanceBlock:
    """Unit tests for the _build_live_data_provenance_block helper."""

    def test_returns_string(self):
        from app.services.thesis_synthesizer import _build_live_data_provenance_block
        result = _build_live_data_provenance_block([])
        assert isinstance(result, str)

    def test_non_empty(self):
        from app.services.thesis_synthesizer import _build_live_data_provenance_block
        result = _build_live_data_provenance_block([_make_evidence()])
        assert len(result) > 0

    def test_live_valuation_present_mentions_must_cite(self):
        from app.services.thesis_synthesizer import _build_live_data_provenance_block
        ev = [_fmp_valuation_ev()]
        result = _build_live_data_provenance_block(ev)
        assert "MUST cite" in result or "must cite" in result.lower()

    def test_no_live_valuation_mentions_qualify(self):
        from app.services.thesis_synthesizer import _build_live_data_provenance_block
        ev = [_make_evidence(source="newsapi")]
        result = _build_live_data_provenance_block(ev)
        assert "qualify" in result.lower() or "No live valuation" in result

    def test_analyst_estimates_present_mentions_consensus(self):
        from app.services.thesis_synthesizer import _build_live_data_provenance_block
        ev = [_fmp_analyst_ev()]
        result = _build_live_data_provenance_block(ev)
        assert "consensus" in result.lower() or "analyst" in result.lower()

    def test_no_analyst_mentions_do_not_assert(self):
        from app.services.thesis_synthesizer import _build_live_data_provenance_block
        ev = [_make_evidence(source="newsapi")]
        result = _build_live_data_provenance_block(ev)
        assert "Do NOT assert" in result or "do not assert" in result.lower()

    def test_citation_requirement_always_present(self):
        from app.services.thesis_synthesizer import _build_live_data_provenance_block
        for ev_list in [[], [_make_evidence()], [_fmp_valuation_ev()]]:
            result = _build_live_data_provenance_block(ev_list)
            assert "CITATION REQUIREMENT" in result or "citation" in result.lower()
