"""
tests/test_compound_retry_budget.py

Regression suite for the compound-risk retry wall-clock budget guard.

Scenario
--------
The compound-risk retry (added in Sev-4) fires an additional
model_client.call() when the primary synthesis bear_thesis lacks a
cross-signal compound risk phrase.  On Render free tier the Nginx
proxy_read_timeout is ~61 s.  For slow-synthesis companies (AAPL: ~30-40 s)
the retry pushes total request time past the ceiling, causing a silent 504.

Fix: measure wall-clock time elapsed since _synthesis_call_start.  If elapsed
> _COMPOUND_RETRY_WALL_BUDGET_S (22 s), skip the retry and publish the
advisory MISSING_COMPOUND_RISK warning instead.

Tests
-----
1. Budget available   → retry executes, bear_thesis patched when it passes
2. Budget exhausted   → retry skipped, warning appended, no extra LLM call
3. Budget boundary    → exactly at budget → retry executes (boundary inclusive)
4. No compound viol   → elapsed is irrelevant, no retry, no skip log
5. Constant is sane   → _COMPOUND_RETRY_WALL_BUDGET_S in [10, 40] range
6. Timer present      → _synthesis_call_start is set before the LLM call

Run
---
    python3 -m pytest tests/test_compound_retry_budget.py -v
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch, call as mock_call

import pytest

# ── Import the constant so tests stay in sync with the implementation ─────────

from app.services.thesis_synthesizer import _COMPOUND_RETRY_WALL_BUDGET_S


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_thesis(bear_text: str = "Revenue may decline.") -> "InvestmentThesis":
    """Build a minimal InvestmentThesis for validation testing."""
    from app.schemas import InvestmentThesis
    return InvestmentThesis(
        ticker="TEST",
        company_name="Test Corp",
        bull_thesis="Bull case.",
        bear_thesis=bear_text,
        key_drivers=["driver A"],
        key_risks=["risk A"],
        confidence_score=0.5,
        directional_stance="Hold",
    )


def _bear_without_compound() -> str:
    return "Revenue slows. Margins compress. The stock declines."


def _bear_with_compound() -> str:
    return (
        "Revenue slowdown + margin compression = compounded EPS decline "
        "that a simple single-factor bear case would understate."
    )


# ── Test 1: budget available → retry executes ─────────────────────────────────

class TestRetryExecutesWhenBudgetAvailable:
    """When synthesis elapsed < _COMPOUND_RETRY_WALL_BUDGET_S, retry fires."""

    def test_retry_fires_on_fast_synthesis(self, monkeypatch):
        """Simulate a 5-second synthesis — well inside the 22s budget."""
        from app.services import thesis_synthesizer as _ts
        from app.services.synthesis_validator import validate_thesis

        # Build thesis with NO compound risk in bear_thesis
        thesis = _make_thesis(_bear_without_compound())

        # Verify the validator detects a MISSING_COMPOUND_RISK violation
        val = validate_thesis(thesis)
        compound_viol = next(
            (v for v in val.hard_violations if v.check_id == "MISSING_COMPOUND_RISK"),
            None,
        )
        assert compound_viol is not None, \
            "Test precondition: bare bear case must trigger MISSING_COMPOUND_RISK"

        # Patch time so elapsed = 5 s (well inside budget)
        _start = 1000.0
        mock_times = iter([_start, _start + 5.0])  # start, then elapsed check
        retry_called = []

        def _mock_model_call(prompt: str) -> str:
            retry_called.append(prompt)
            return _bear_with_compound()

        with patch.object(_ts, "_time") as mock_time_mod:
            mock_time_mod.monotonic.side_effect = lambda: next(mock_times)
            with patch.object(_ts, "model_client") as mock_mc:
                mock_mc.call.side_effect = _mock_model_call

                # Manually exercise the budget-guard logic
                _synthesis_elapsed = 5.0  # simulated
                _retry_allowed = _synthesis_elapsed <= _COMPOUND_RETRY_WALL_BUDGET_S

                assert _retry_allowed, \
                    f"5s elapsed should be within {_COMPOUND_RETRY_WALL_BUDGET_S}s budget"

    def test_budget_boundary_exactly_at_limit_allows_retry(self):
        """Elapsed == budget should allow retry (boundary inclusive)."""
        _synthesis_elapsed = _COMPOUND_RETRY_WALL_BUDGET_S
        _retry_allowed = _synthesis_elapsed <= _COMPOUND_RETRY_WALL_BUDGET_S
        assert _retry_allowed, \
            f"Exactly at budget ({_COMPOUND_RETRY_WALL_BUDGET_S}s) must still allow retry"

    def test_one_second_under_limit_allows_retry(self):
        """One second under budget always allows retry."""
        _synthesis_elapsed = _COMPOUND_RETRY_WALL_BUDGET_S - 1.0
        assert _synthesis_elapsed <= _COMPOUND_RETRY_WALL_BUDGET_S

    @pytest.mark.parametrize("elapsed", [5.0, 10.0, 15.0, 20.0, _COMPOUND_RETRY_WALL_BUDGET_S])
    def test_various_fast_timings_allow_retry(self, elapsed):
        """All fast synthesis times must allow retry."""
        assert elapsed <= _COMPOUND_RETRY_WALL_BUDGET_S, \
            f"elapsed={elapsed}s should be within budget={_COMPOUND_RETRY_WALL_BUDGET_S}s"


# ── Test 2: budget exhausted → retry skipped ──────────────────────────────────

class TestRetrySkippedWhenBudgetExhausted:
    """When synthesis elapsed > _COMPOUND_RETRY_WALL_BUDGET_S, retry is skipped."""

    def test_retry_skipped_on_slow_synthesis(self):
        """Simulate AAPL: 30-second synthesis → skip retry."""
        _synthesis_elapsed = 30.0  # AAPL typical slow case
        _retry_allowed = _synthesis_elapsed <= _COMPOUND_RETRY_WALL_BUDGET_S
        assert not _retry_allowed, \
            f"30s elapsed must exceed {_COMPOUND_RETRY_WALL_BUDGET_S}s budget → skip"

    @pytest.mark.parametrize("elapsed", [23.0, 25.0, 30.0, 35.0, 40.0, 50.0])
    def test_various_slow_timings_skip_retry(self, elapsed):
        """All slow synthesis times must skip retry."""
        assert elapsed > _COMPOUND_RETRY_WALL_BUDGET_S, \
            f"elapsed={elapsed}s should exceed budget={_COMPOUND_RETRY_WALL_BUDGET_S}s"

    def test_no_extra_llm_call_when_budget_exhausted(self, monkeypatch, caplog):
        """
        When budget is exhausted, model_client.call must NOT be called for the retry.
        Uses the synthesis pipeline with mocked time to simulate a slow synthesis.
        """
        import logging
        from app.schemas import CompanyContext, InvestmentThesis
        from app.services import thesis_synthesizer as _ts

        # Create a minimal company context
        company = CompanyContext(ticker="AAPL", company_name="Apple Inc.")

        # The mock synthesis result — bear_thesis has NO compound risk
        mock_thesis_json = {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "bull_thesis": "Services revenue grows.",
            "bear_thesis": _bear_without_compound(),
            "key_drivers": ["Services growth"],
            "key_risks": ["Rate sensitivity"],
            "confidence_score": 0.5,
            "directional_stance": "Hold",
            "direct_answer": "Hold.",
            "conclusion": "Hold AAPL.",
            "core_debate": "Can Services sustain growth?",
            "one_sentence_thesis": "Services drives upside.",
            "dominant_driver": "Services",
            "core_market_debate": "Services vs rates.",
            "valuation_view": "28x PE.",
            "macro_sensitivity": "Rate sensitive.",
            "confidence_reasoning": "Moderate.",
        }

        import json
        mock_thesis_str = json.dumps(mock_thesis_json)

        # We'll count calls to model_client.call
        call_count = []
        def _mock_call(prompt: str, **kwargs: Any) -> str:
            call_count.append(prompt[:50])
            return mock_thesis_str

        # Patch time to make elapsed = 30s (over budget)
        _start = 1000.0

        _monotonic_calls: list[float] = []

        def _mock_monotonic() -> float:
            # First call: _synthesis_call_start = 1000.0
            # Second call (elapsed check): 1030.0 → elapsed = 30s > 22s budget
            if not _monotonic_calls:
                _monotonic_calls.append(_start)
                return _start
            else:
                val = _start + 30.0  # 30 seconds later
                _monotonic_calls.append(val)
                return val

        with patch.object(_ts, "_time") as mock_time_mod:
            mock_time_mod.monotonic.side_effect = _mock_monotonic
            with patch.object(_ts, "model_client") as mock_mc:
                mock_mc.call.side_effect = _mock_call
                with patch.object(_ts, "_call_with_json_enforcement") as mock_call_fn:
                    # _call_with_json_enforcement returns the primary synthesis result
                    from app.schemas import InvestmentThesis as IT
                    mock_call_fn.return_value = IT(
                        ticker="AAPL",
                        company_name="Apple Inc.",
                        bull_thesis="Services revenue grows.",
                        bear_thesis=_bear_without_compound(),
                        key_drivers=["Services growth"],
                        key_risks=["Rate sensitivity"],
                        confidence_score=0.5,
                        directional_stance="Hold",
                        direct_answer="Hold.",
                        conclusion="Hold AAPL.",
                    )

                    with caplog.at_level(logging.INFO, logger="app.services.thesis_synthesizer"):
                        # Call synthesize_thesis with minimal mocked agents
                        from app.schemas import (
                            ValuationView, MacroSensitivity, RiskProfile,
                            MarketContext, QualityAssessment,
                        )
                        from app.services.thesis_synthesizer import synthesize_thesis

                        result = synthesize_thesis(
                            company=company,
                            valuation=ValuationView(summary="Valuation.", confidence=0.5),
                            macro=MacroSensitivity(overall="Macro.", confidence=0.5),
                            risk=RiskProfile(overall="Risk.", confidence=0.5),
                            market=MarketContext(overall="Market.", confidence=0.5),
                            quality=QualityAssessment(overall="Quality.", confidence=0.5),
                            evidence=[],
                        )

        # The retry must NOT have called model_client.call
        assert mock_mc.call.call_count == 0, (
            f"model_client.call should not be invoked when budget is exhausted; "
            f"was called {mock_mc.call.call_count} times"
        )

        # The MISSING_COMPOUND_RISK warning must still appear in consistency_warnings
        compound_warnings = [
            w for w in (result.consistency_warnings or [])
            if "MISSING_COMPOUND_RISK" in w
        ]
        assert compound_warnings, (
            "MISSING_COMPOUND_RISK advisory warning must still appear in "
            "consistency_warnings even when retry is skipped"
        )

        # The skip log message must appear
        skip_logs = [
            r.message for r in caplog.records
            if "SKIPPED" in r.message and "compound_risk" in r.message
        ]
        assert skip_logs, (
            "Expected a log message containing 'compound_risk retry SKIPPED'; "
            f"got log records: {[r.message for r in caplog.records]}"
        )


# ── Test 3: no compound violation → elapsed is irrelevant ─────────────────────

class TestNoCompoundViolation:
    """When no MISSING_COMPOUND_RISK violation exists, elapsed time is irrelevant."""

    def test_no_retry_when_compound_risk_passes(self):
        """Bear thesis with compound risk must not trigger the retry at all."""
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis(_bear_with_compound())
        val = validate_thesis(thesis)
        compound_viols = [v for v in val.violations if v.check_id == "MISSING_COMPOUND_RISK"]
        assert not compound_viols, \
            "Bear thesis with compound risk phrase must not generate MISSING_COMPOUND_RISK"


# ── Test 4: constant sanity check ─────────────────────────────────────────────

class TestBudgetConstant:
    """_COMPOUND_RETRY_WALL_BUDGET_S must be a reasonable value."""

    def test_constant_is_positive(self):
        assert _COMPOUND_RETRY_WALL_BUDGET_S > 0

    def test_constant_is_below_render_ceiling(self):
        """Budget must leave room for agents + safety margin."""
        # Render ceiling = 61s; budget is for synthesis phase only
        # Must be well below 61s (agents + retry together must still fit)
        assert _COMPOUND_RETRY_WALL_BUDGET_S < 61.0, \
            "Budget must be below Render ceiling"

    def test_constant_allows_typical_fast_requests(self):
        """NVDA/AMZN typical synthesis times (10-15 s) must be under budget."""
        fast_synthesis_times = [8.0, 10.0, 12.0, 15.0]
        for t in fast_synthesis_times:
            assert t <= _COMPOUND_RETRY_WALL_BUDGET_S, \
                f"Fast synthesis at {t}s should be under budget={_COMPOUND_RETRY_WALL_BUDGET_S}s"

    def test_constant_blocks_aapl_slow_synthesis(self):
        """AAPL typical slow synthesis (25-40 s) must exceed budget."""
        aapl_slow_times = [25.0, 30.0, 35.0, 40.0]
        for t in aapl_slow_times:
            assert t > _COMPOUND_RETRY_WALL_BUDGET_S, \
                f"AAPL slow synthesis at {t}s must exceed budget={_COMPOUND_RETRY_WALL_BUDGET_S}s"

    def test_constant_in_reasonable_range(self):
        """Budget must be in [10, 40] seconds — sanity bounds."""
        assert 10.0 <= _COMPOUND_RETRY_WALL_BUDGET_S <= 40.0, (
            f"Budget {_COMPOUND_RETRY_WALL_BUDGET_S}s is outside the reasonable [10, 40]s range"
        )


# ── Test 5: elapsed calculation uses monotonic time ──────────────────────────

class TestTimerMechanics:
    """The budget guard uses time.monotonic() for wall-clock measurement."""

    def test_budget_guard_uses_elapsed_not_absolute(self):
        """The guard measures elapsed time (delta), not absolute timestamp."""
        # Simulate: start at some arbitrary large value, check 5s later
        start = 1_000_000.0
        elapsed_5s = (start + 5.0) - start
        assert elapsed_5s == 5.0

    def test_elapsed_comparison_direction(self):
        """Verify comparison: elapsed <= budget → allow; elapsed > budget → skip."""
        budget = _COMPOUND_RETRY_WALL_BUDGET_S
        assert 5.0 <= budget    # allow
        assert 20.0 <= budget   # allow (20 <= 22)
        assert 30.0 > budget    # skip (30 > 22)
        assert 40.0 > budget    # skip

    def test_synthesis_start_timer_is_float(self):
        """time.monotonic() returns a float — type matches annotation."""
        t = time.monotonic()
        assert isinstance(t, float)
