"""Regression tests for the interactive selected-comparison time budget."""

from app.services.router_service import (
    _DEFAULT_SYNTHESIS_PLAN,
    _SELECTED_COMPARISON_SYNTHESIS_PLAN,
    _limit_synthesis_evidence,
    _synthesis_attempt_plan,
)


def test_selected_comparison_worst_case_stays_below_frontend_timeout():
    retrieval_cap = 10.0
    agent_cap = 16.0
    synthesis_cap = sum(timeout for timeout, _ in _SELECTED_COMPARISON_SYNTHESIS_PLAN)

    assert retrieval_cap + agent_cap + synthesis_cap == 78.0
    assert retrieval_cap + agent_cap + synthesis_cap < 90.0


def test_selected_comparison_uses_reduced_retry_context():
    plan = _synthesis_attempt_plan(selected_comparison=True)

    assert plan == _SELECTED_COMPARISON_SYNTHESIS_PLAN
    assert plan[1][0] < plan[0][0]
    assert plan[1][1] < plan[0][1]


def test_ordinary_analysis_keeps_existing_first_attempt_budget():
    plan = _synthesis_attempt_plan(selected_comparison=False)

    assert plan == _DEFAULT_SYNTHESIS_PLAN
    assert plan[0] == (56.0, None)


def test_evidence_limit_does_not_mutate_full_admitted_collection():
    admitted = list(range(30))

    prompt_evidence = _limit_synthesis_evidence(admitted, 12)

    assert prompt_evidence == list(range(12))
    assert admitted == list(range(30))
    assert prompt_evidence is not admitted


def test_no_limit_reuses_complete_evidence_collection():
    admitted = list(range(5))

    assert _limit_synthesis_evidence(admitted, None) is admitted
