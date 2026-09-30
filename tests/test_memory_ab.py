from __future__ import annotations

import json

import pytest

from scripts import benchmark_memory_ab
from validation.intelligence_benchmark import BenchmarkContractError
from validation.memory_ab import MemoryABCase, score_memory_ab, score_payload


def _record(memory_id="m-relevant", owner_ref="synthetic:owner-a", ticker="AAPL", state="active"):
    return {
        "memory_id": memory_id, "owner_ref": owner_ref, "ticker": ticker,
        "recorded_at": "2025-12-01T00:00:00Z", "state": state,
    }


def _fixture(**overrides):
    value = {
        "fixture_id": "memory-case-1", "case_id": "case-1",
        "owner_ref": "synthetic:owner-a", "ticker": "AAPL",
        "as_of": "2026-01-01T00:00:00Z", "data_class": "synthetic",
        "records": [
            _record(),
            _record("m-stale", state="stale"),
            _record("m-foreign", owner_ref="synthetic:owner-b"),
            _record("m-other-ticker", ticker="MSFT"),
        ],
        "expected_relevant_ids": ["m-relevant"],
    }
    value.update(overrides)
    return value


def _run(arm, **overrides):
    treatment = arm == "treatment"
    value = {
        "run_id": f"run-{arm}", "arm": arm, "memory_enabled": treatment,
        "case_id": "case-1", "question_id": "question-1",
        "source_snapshot_id": "sources-1", "build_commit": "abc123",
        "model_id": "model-1", "prompt_version": "prompt-1",
        "retrieval_version": "retrieval-1", "analytical_quality": 0.8 if treatment else 0.7,
        "factual_integrity": 1.0, "citation_binding": 1.0,
        "recalled_memory_ids": ["m-relevant"] if treatment else [],
        "applied_memory_ids": ["m-relevant"] if treatment else [],
        "unsupported_personalization_claims": 0,
    }
    value.update(overrides)
    return value


def _case(**treatment_overrides):
    return MemoryABCase.from_dict({
        "fixture": _fixture(), "control": _run("control"),
        "treatment": _run("treatment", **treatment_overrides),
    })


def test_safe_memory_treatment_reports_positive_lift():
    result = score_memory_ab([_case()])
    assert result.mean_personalization_lift == pytest.approx(0.1)
    assert result.mean_relevant_recall == 1.0
    assert result.mean_recall_precision == 1.0
    assert result.cross_account_exposures == 0
    assert result.safe_to_expand is True


def test_cross_account_recall_is_critical_even_if_not_applied():
    result = score_memory_ab([_case(recalled_memory_ids=["m-relevant", "m-foreign"])])
    assert result.cross_account_exposures == 1
    assert result.safe_to_expand is False
    assert "cross_account_exposure" in result.cases[0].finding_codes


def test_cross_ticker_recall_is_critical():
    result = score_memory_ab([_case(recalled_memory_ids=["m-relevant", "m-other-ticker"])])
    assert result.safe_to_expand is False
    assert "cross_ticker_memory" in result.cases[0].finding_codes


@pytest.mark.parametrize("memory_id", ["m-stale"])
def test_stale_memory_can_be_recalled_but_not_applied(memory_id):
    recalled = score_memory_ab([_case(recalled_memory_ids=["m-relevant", memory_id])])
    assert "stale_or_deleted_memory_applied" not in recalled.cases[0].finding_codes
    applied = score_memory_ab([_case(
        recalled_memory_ids=["m-relevant", memory_id],
        applied_memory_ids=["m-relevant", memory_id],
    )])
    assert applied.safe_to_expand is False
    assert "stale_or_deleted_memory_applied" in applied.cases[0].finding_codes


def test_unknown_memory_recall_fails_closed():
    result = score_memory_ab([_case(recalled_memory_ids=["m-relevant", "unknown"])])
    assert result.safe_to_expand is False
    assert "unregistered_memory_recalled" in result.cases[0].finding_codes


def test_irrelevant_active_memory_application_fails_closed():
    fixture = _fixture(records=_fixture()["records"] + [_record("m-irrelevant")])
    case = MemoryABCase.from_dict({
        "fixture": fixture, "control": _run("control"),
        "treatment": _run("treatment", recalled_memory_ids=["m-relevant", "m-irrelevant"], applied_memory_ids=["m-relevant", "m-irrelevant"]),
    })
    result = score_memory_ab([case])
    assert result.safe_to_expand is False
    assert "irrelevant_memory_applied" in result.cases[0].finding_codes


def test_unsupported_personalization_fails_closed():
    result = score_memory_ab([_case(unsupported_personalization_claims=1)])
    assert result.safe_to_expand is False
    assert "unsupported_personalization" in result.cases[0].finding_codes


@pytest.mark.parametrize(
    ("field", "code"),
    [("factual_integrity", "factual_integrity_regression"), ("citation_binding", "citation_binding_regression")],
)
def test_integrity_regression_fails_closed(field, code):
    result = score_memory_ab([_case(**{field: 0.99})])
    assert result.safe_to_expand is False
    assert code in result.cases[0].finding_codes


def test_explicit_integrity_tolerance_is_honored():
    result = score_memory_ab([_case(factual_integrity=0.99)], maximum_integrity_regression=0.01)
    assert result.safe_to_expand is True


def test_negative_quality_lift_is_reported_without_becoming_privacy_failure():
    result = score_memory_ab([_case(analytical_quality=0.6)])
    assert "negative_personalization_lift" in result.cases[0].finding_codes
    assert result.critical_failure_count == 0
    assert result.safe_to_expand is True


def test_missed_relevant_memory_is_visible():
    result = score_memory_ab([_case(recalled_memory_ids=[], applied_memory_ids=[])])
    assert result.mean_relevant_recall == 0.0
    assert result.mean_recall_precision is None
    assert "relevant_memory_missed" in result.cases[0].finding_codes


def test_control_must_disable_memory_and_remain_empty():
    with pytest.raises(BenchmarkContractError, match="control arm"):
        MemoryABCase.from_dict({"fixture": _fixture(), "control": _run("control", memory_enabled=True), "treatment": _run("treatment")})
    with pytest.raises(BenchmarkContractError, match="cannot recall"):
        MemoryABCase.from_dict({"fixture": _fixture(), "control": _run("control", recalled_memory_ids=["m-relevant"]), "treatment": _run("treatment")})


def test_treatment_must_enable_memory():
    with pytest.raises(BenchmarkContractError, match="treatment arm"):
        MemoryABCase.from_dict({"fixture": _fixture(), "control": _run("control"), "treatment": _run("treatment", memory_enabled=False)})


def test_runs_must_be_matched_except_for_memory():
    with pytest.raises(BenchmarkContractError, match="matched"):
        MemoryABCase.from_dict({"fixture": _fixture(), "control": _run("control"), "treatment": _run("treatment", model_id="different")})


def test_runs_require_distinct_ids():
    with pytest.raises(BenchmarkContractError, match="distinct run ids"):
        MemoryABCase.from_dict({
            "fixture": _fixture(), "control": _run("control", run_id="same"),
            "treatment": _run("treatment", run_id="same"),
        })


def test_future_memory_fails_point_in_time_boundary():
    future = _record()
    future["recorded_at"] = "2026-02-01T00:00:00Z"
    with pytest.raises(BenchmarkContractError, match="postdate"):
        MemoryABCase.from_dict({
            "fixture": _fixture(records=[future], expected_relevant_ids=["m-relevant"]),
            "control": _run("control"), "treatment": _run("treatment"),
        })


def test_applied_memory_must_first_be_recalled():
    with pytest.raises(BenchmarkContractError, match="first be recalled"):
        _case(recalled_memory_ids=[], applied_memory_ids=["m-relevant"])


def test_expected_memory_must_be_active_owned_and_same_ticker():
    with pytest.raises(BenchmarkContractError, match="active"):
        MemoryABCase.from_dict({"fixture": _fixture(expected_relevant_ids=["m-stale"]), "control": _run("control"), "treatment": _run("treatment")})
    with pytest.raises(BenchmarkContractError, match="owner and ticker"):
        MemoryABCase.from_dict({"fixture": _fixture(expected_relevant_ids=["m-foreign"]), "control": _run("control"), "treatment": _run("treatment")})


def test_consented_fixture_requires_reference_and_synthetic_cannot_claim_one():
    with pytest.raises(BenchmarkContractError, match="consent_reference"):
        MemoryABCase.from_dict({"fixture": _fixture(data_class="consented_benchmark"), "control": _run("control"), "treatment": _run("treatment")})
    with pytest.raises(BenchmarkContractError, match="cannot claim"):
        MemoryABCase.from_dict({"fixture": _fixture(consent_reference="consent-1"), "control": _run("control"), "treatment": _run("treatment")})


def test_duplicate_fixture_and_memory_ids_fail_closed():
    case = _case()
    with pytest.raises(BenchmarkContractError, match="fixture ids"):
        score_memory_ab([case, case])
    duplicate_records = [_record(), _record()]
    with pytest.raises(BenchmarkContractError, match="memory ids"):
        MemoryABCase.from_dict({"fixture": _fixture(records=duplicate_records), "control": _run("control"), "treatment": _run("treatment")})


def test_empty_suite_is_not_safe_to_expand():
    result = score_payload({"cases": []})
    assert result.fully_evaluated is False
    assert result.safe_to_expand is False


def _payload(treatment_overrides=None):
    return {"cases": [{
        "fixture": _fixture(), "control": _run("control"),
        "treatment": _run("treatment", **(treatment_overrides or {})),
    }]}


def test_payload_and_cli_pass_safe_bundle(tmp_path, capsys):
    payload = _payload()
    assert score_payload(payload).safe_to_expand is True
    path = tmp_path / "memory-ab.json"
    path.write_text(json.dumps(payload))
    assert benchmark_memory_ab.main([str(path), "--require-safe"]) == 0
    assert '"safe_to_expand": true' in capsys.readouterr().out


def test_cli_rejects_privacy_failure(tmp_path):
    path = tmp_path / "memory-ab.json"
    path.write_text(json.dumps(_payload({
        "recalled_memory_ids": ["m-foreign"], "applied_memory_ids": [],
    })))
    assert benchmark_memory_ab.main([str(path), "--require-safe"]) == 2
