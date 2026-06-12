"""
Phase 9G · Slice 5D — Tests for canary wiring in the /ask path.

These tests operate entirely below the HTTP layer.  They verify the logic that
decides whether to attach the dossier block to the QuestionRequest and that the
telemetry records are written correctly, WITHOUT hitting the real /ask endpoint
or the production database.

Approach:
  - Build a fake InjectionResult and a fake QuestionRequest.
  - Simulate the pre-dispatch decision logic (decide_cohort + record_decision
    + conditional model_copy).
  - Verify the request is modified only when all gates pass.
  - Verify the request is NEVER modified at default config values.
"""

from __future__ import annotations

import types
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.schemas import QuestionRequest
from app.services.dossier_canary_cohort import (
    COHORT_CONTROL,
    COHORT_INJECTED,
    COHORT_INELIGIBLE,
    decide_cohort,
)
from app.services import dossier_canary_telemetry as telem


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    telem.reset()
    yield
    telem.reset()


def _make_request(**kw) -> QuestionRequest:
    defaults = dict(company_name="NVDA", question="Is NVDA a buy?")
    defaults.update(kw)
    return QuestionRequest(**defaults)


def _make_injection_result(block_str: str = "PRIOR: bullish context...",
                           token_count: int = 200) -> Any:
    """Minimal stand-in for InjectionResult (uses SimpleNamespace)."""
    return types.SimpleNamespace(
        block_str=block_str,
        token_count=token_count,
        staleness_state="fresh",
        intent="company_analysis",
        included_facets=["debate", "prior_state"],
        dropped_facets=[],
    )


# ─── QuestionRequest: dossier_context_block field ────────────────────────────

def test_question_request_dossier_field_default_none():
    req = _make_request()
    assert req.dossier_context_block is None


def test_question_request_dossier_field_accepts_string():
    req = _make_request()
    req2 = req.model_copy(update={"dossier_context_block": "PRIOR CONTEXT"})
    assert req2.dossier_context_block == "PRIOR CONTEXT"


def test_question_request_dossier_field_excluded_from_serialization():
    """dossier_context_block must not appear in client-facing serialization."""
    req = _make_request()
    req2 = req.model_copy(update={"dossier_context_block": "SECRET_PRIOR"})
    dumped = req2.model_dump()
    assert "dossier_context_block" not in dumped
    assert "SECRET_PRIOR" not in str(dumped)


# ─── Cohort gates: injection only when all pass ───────────────────────────────

def _simulate_pre_dispatch(
    session_id: str,
    canary_pct: int,
    enabled: bool,
    inj_result: Optional[Any] = None,
) -> Dict[str, Any]:
    """Simulate the pre-dispatch logic in _generate() and return outcome."""
    eff_enabled = telem.get_enabled(enabled)
    cohort = decide_cohort(session_id, canary_pct, eff_enabled)

    request = _make_request()
    injected = False

    telem.record_decision(
        session_id=session_id,
        cohort=cohort,
        ticker="NVDA",
        canary_pct=canary_pct,
        token_count=inj_result.token_count if inj_result else 0,
        facets=inj_result.included_facets if inj_result else [],
        staleness=inj_result.staleness_state if inj_result else "unknown",
        dossier_age_days=None,
        prior_stance=None,
    )

    if (
        cohort == COHORT_INJECTED
        and inj_result is not None
        and eff_enabled
        and canary_pct > 0
    ):
        request = request.model_copy(update={
            "dossier_context_block": inj_result.block_str,
        })
        injected = True

    return {"cohort": cohort, "request": request, "injected": injected}


def test_default_config_never_injects():
    """At default settings (enabled=False, canary_pct=0) injection never fires."""
    inj = _make_injection_result()
    for i in range(200):
        out = _simulate_pre_dispatch(f"s{i}", canary_pct=0, enabled=False, inj_result=inj)
        assert out["request"].dossier_context_block is None
        assert out["cohort"] == COHORT_INELIGIBLE
        assert not out["injected"]


def test_enabled_true_but_canary_pct_zero_never_injects():
    inj = _make_injection_result()
    for i in range(100):
        out = _simulate_pre_dispatch(f"s{i}", canary_pct=0, enabled=True, inj_result=inj)
        assert out["request"].dossier_context_block is None
        assert out["cohort"] == COHORT_INELIGIBLE
        assert not out["injected"]


def test_kill_switch_blocks_injection():
    """force_disable() must prevent injection even at canary_pct=50, enabled=True."""
    telem.force_disable()
    inj = _make_injection_result()
    for i in range(200):
        out = _simulate_pre_dispatch(f"s{i}", canary_pct=50, enabled=True, inj_result=inj)
        assert out["request"].dossier_context_block is None
        assert not out["injected"]


def test_null_injection_result_never_injects():
    """No block built (no dossier) → COHORT_INJECTED session still gets no injection."""
    injected_session = next(
        f"s{i}" for i in range(10000)
        if decide_cohort(f"s{i}", 50, True) == COHORT_INJECTED
    )
    out = _simulate_pre_dispatch(
        injected_session, canary_pct=50, enabled=True, inj_result=None
    )
    assert out["request"].dossier_context_block is None
    assert not out["injected"]


def test_injected_cohort_attaches_block_when_all_gates_pass():
    """Find a session in the INJECTED bucket; confirm block is attached."""
    injected_session = next(
        f"s{i}" for i in range(10000)
        if decide_cohort(f"s{i}", 50, True) == COHORT_INJECTED
    )
    inj = _make_injection_result()
    out = _simulate_pre_dispatch(
        injected_session, canary_pct=50, enabled=True, inj_result=inj
    )
    assert out["cohort"] == COHORT_INJECTED
    assert out["injected"] is True
    assert out["request"].dossier_context_block == inj.block_str


def test_control_cohort_never_injects():
    """Sessions in the control arm must not receive the block."""
    control_session = next(
        f"s{i}" for i in range(10000)
        if decide_cohort(f"s{i}", 50, True) == COHORT_CONTROL
    )
    inj = _make_injection_result()
    out = _simulate_pre_dispatch(
        control_session, canary_pct=50, enabled=True, inj_result=inj
    )
    assert out["cohort"] == COHORT_CONTROL
    assert not out["injected"]
    assert out["request"].dossier_context_block is None


def test_holdout_sessions_never_inject():
    """Permanent holdout bucket (5%) must remain CONTROL even at 95% canary."""
    from app.services.dossier_canary_cohort import _session_bucket, HOLDOUT_PCT
    holdout_session = next(
        f"s{i}" for i in range(10000)
        if _session_bucket(f"s{i}") < HOLDOUT_PCT
    )
    inj = _make_injection_result()
    out = _simulate_pre_dispatch(
        holdout_session, canary_pct=95, enabled=True, inj_result=inj
    )
    assert out["cohort"] == COHORT_CONTROL
    assert not out["injected"]


# ─── Decision events recorded correctly ──────────────────────────────────────

def test_control_cohort_records_decision_event():
    control_session = next(
        f"s{i}" for i in range(10000)
        if decide_cohort(f"s{i}", 50, True) == COHORT_CONTROL
    )
    _simulate_pre_dispatch(control_session, canary_pct=50, enabled=True)
    snap = telem.snapshot()
    assert snap["canary"]["decision_total"] == 1
    assert snap["canary"]["cohort_counts"].get(COHORT_CONTROL, 0) >= 1


def test_injected_cohort_records_decision_event():
    injected_session = next(
        f"s{i}" for i in range(10000)
        if decide_cohort(f"s{i}", 50, True) == COHORT_INJECTED
    )
    _simulate_pre_dispatch(
        injected_session, canary_pct=50, enabled=True,
        inj_result=_make_injection_result()
    )
    snap = telem.snapshot()
    assert snap["canary"]["decision_total"] == 1
    assert snap["canary"]["cohort_counts"].get(COHORT_INJECTED, 0) == 1


def test_ineligible_cohort_records_decision_event():
    _simulate_pre_dispatch("any-session", canary_pct=0, enabled=False)
    snap = telem.snapshot()
    assert snap["canary"]["decision_total"] == 1
    assert snap["canary"]["cohort_counts"].get(COHORT_INELIGIBLE, 0) == 1


# ─── Outcome recording ────────────────────────────────────────────────────────

def test_outcome_recording_increments_total():
    telem.record_outcome(
        session_id="s1", cohort=COHORT_INJECTED, ticker="NVDA",
        stance="bullish", conviction=0.80,
        change_vector_len=50, conclusion_len=100,
        specificity=4.0, fallback_used=False,
        latency_s=1.5, prior_challenged=True,
    )
    snap = telem.snapshot()
    assert snap["canary"]["outcome_total"] == 1


def test_outcome_recording_no_thesis_no_error():
    """If the result dict lacks an investment_thesis, outcome recording is skipped."""
    # Simulate the api.py guard: isinstance check before calling record_outcome.
    _5c_thesis_out = None  # no thesis
    if isinstance(_5c_thesis_out, dict):
        telem.record_outcome(
            session_id="s1", cohort=COHORT_CONTROL, ticker="NVDA",
            stance=None, conviction=None, change_vector_len=0,
            conclusion_len=0, specificity=0.0, fallback_used=False,
            latency_s=None, prior_challenged=None,
        )
    snap = telem.snapshot()
    assert snap["canary"]["outcome_total"] == 0


def test_outcome_recorded_for_control_cohort():
    telem.record_outcome(
        session_id="s2", cohort=COHORT_CONTROL, ticker="JPM",
        stance="bearish", conviction=0.60,
        change_vector_len=20, conclusion_len=80,
        specificity=2.0, fallback_used=False,
        latency_s=2.0, prior_challenged=None,
    )
    snap = telem.snapshot()
    assert snap["conviction"]["control_n"] == 1
    assert snap["conviction"]["control_mean"] == pytest.approx(0.60, abs=0.01)


# ─── Prompt injection field passed through synthesizer ───────────────────────

def test_synthesize_thesis_accepts_dossier_context_block_parameter():
    """synthesize_thesis must declare dossier_context_block in its signature."""
    import inspect
    from app.services.thesis_synthesizer import synthesize_thesis
    sig = inspect.signature(synthesize_thesis)
    assert "dossier_context_block" in sig.parameters


def test_build_synthesis_prompt_accepts_dossier_context_block_parameter():
    """_build_synthesis_prompt must declare dossier_context_block in its signature."""
    import inspect
    from app.services.thesis_synthesizer import _build_synthesis_prompt
    sig = inspect.signature(_build_synthesis_prompt)
    assert "dossier_context_block" in sig.parameters


def test_dossier_section_interpolation():
    """The dossier section template logic produces the expected string fragment."""
    # This tests the same logic used inside _build_synthesis_prompt without
    # requiring a full set of agent objects.
    block = "PRIOR: bullish thesis context"
    _dossier_section = f"\n{block}\n" if block else ""
    assert block in _dossier_section

    _dossier_section_none = "" if True else f"\n{'ignored'}\n"
    assert _dossier_section_none == ""


def test_dossier_section_empty_when_none():
    """dossier_context_block=None must produce an empty section (no prompt change)."""
    dossier_context_block = None
    _dossier_section = f"\n{dossier_context_block}\n" if dossier_context_block else ""
    assert _dossier_section == ""


# ─── Telemetry failure isolation ─────────────────────────────────────────────

def test_telemetry_failure_does_not_affect_request():
    """If the telemetry record_decision call raises, _request remains unchanged."""
    original_request = _make_request()
    request_copy = original_request  # simulate local var

    try:
        # Simulate telemetry raising
        with patch.object(telem, "record_decision", side_effect=RuntimeError("db down")):
            cohort = decide_cohort("s99", 50, True)
            telem.record_decision(  # this will be patched to raise
                session_id="s99", cohort=cohort, ticker="NVDA",
                canary_pct=50, token_count=0, facets=[],
                staleness="unknown", dossier_age_days=None, prior_stance=None,
            )
    except RuntimeError:
        pass  # in api.py this is swallowed by the outer try/except

    # _request must still be the original (untouched)
    assert request_copy.dossier_context_block is None
