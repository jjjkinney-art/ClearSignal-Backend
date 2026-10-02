from validation.entity_identity_benchmark import (
    TEMPORAL_IDENTITY_CASES,
    evaluate_temporal_identity_case,
    run_temporal_identity_benchmark,
)


def test_frozen_temporal_identity_cohort_has_required_boundaries():
    case_ids = {case.case_id for case in TEMPORAL_IDENTITY_CASES}

    assert len(case_ids) == len(TEMPORAL_IDENTITY_CASES) == 8
    assert any(case.expected_behavior == "clarify" for case in TEMPORAL_IDENTITY_CASES)
    assert any(case.expected_status == "pre_merger" for case in TEMPORAL_IDENTITY_CASES)
    assert any(case.expected_status == "pre_separation" for case in TEMPORAL_IDENTITY_CASES)
    assert any(case.expected_status == "not_yet_owned" for case in TEMPORAL_IDENTITY_CASES)


def test_all_frozen_temporal_identity_cases_pass():
    outcomes = run_temporal_identity_benchmark()

    assert all(outcome.passed for outcome in outcomes), outcomes


def test_benchmark_failure_names_mismatched_dimension():
    case = TEMPORAL_IDENTITY_CASES[0]
    broken = type(case)(
        **{**case.__dict__, "expected_ticker": "MSFT", "expected_behavior": "answer"}
    )

    outcome = evaluate_temporal_identity_case(broken)

    assert outcome.passed is False
    assert "ticker" in outcome.reason
    assert "behavior" in outcome.reason

