from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.schemas import AgentAnswerResponse, CompanyContext
from scripts import benchmark_pipeline_capture
from validation.intelligence_benchmark import BenchmarkContractError
from validation.pipeline_capture import (
    _default_runner,
    capture_pipeline_outputs,
)


def _manifest(**case_overrides):
    case = {
        "issuer_id": "AA",
        "question_id": "latest-revenue",
        "question": "What was Alcoa's latest annual revenue?",
        "sources": [{"source_id": "sec:aa:10k"}],
        "expected_claims": [{"claim_id": "AA-revenue"}],
        "adjudications": [],
    }
    case.update(case_overrides)
    return {
        "schema_version": 1,
        "run_id": "synthetic:capture-test-v1",
        "cases": [case],
    }


def test_dry_run_validates_without_invoking_pipeline():
    def forbidden_runner(*args):
        raise AssertionError("dry-run invoked the pipeline")

    decision = capture_pipeline_outputs(
        _manifest(), execute=False, runner=forbidden_runner,
    )
    assert decision.execution_enabled is False
    assert decision.provider_execution_required is False
    assert decision.captured_cases == ()
    assert decision.research_memory_enabled is False
    assert decision.persistence_enabled is False
    assert decision.notification_delivery_enabled is False


def test_execute_captures_runner_response_and_discards_supplied_response():
    calls = []

    def runner(ticker, question, request_id):
        calls.append((ticker, question, request_id))
        return {
            "company": ticker,
            "request_id": request_id,
            "answer": {"verified_sec_facts": []},
        }

    manifest = _manifest(response={"company": "FORGED"})
    decision = capture_pipeline_outputs(manifest, execute=True, runner=runner)
    assert calls == [(
        "AA", "What was Alcoa's latest annual revenue?",
        "synthetic:capture-test-v1:AA:latest-revenue",
    )]
    captured = decision.captured_cases[0]
    assert captured["response"]["company"] == "AA"
    assert "question" not in captured
    assert captured["capture_metadata"]["elapsed_ms"] >= 0
    assert decision.persistence_enabled is False


def test_default_runner_disables_every_context_and_pipeline_side_effect():
    company = CompanyContext(ticker="AA", company_name="Alcoa")
    response = AgentAnswerResponse(
        company="AA", request_id="synthetic:x", agents_used=[],
        answer={"verified_sec_facts": []}, routing={},
    )
    with patch(
        "app.services.company_detection.detect_company", return_value=company,
    ), patch(
        "app.services.router_service._run_investment_pipeline", return_value=response,
    ) as run:
        captured = _default_runner("AA", "Revenue?", "synthetic:x")
    assert captured["company"] == "AA"
    kwargs = run.call_args.kwargs
    assert kwargs["side_effects_enabled"] is False
    assert kwargs["memory_context_block"] is None
    assert kwargs["memory_context_data"] is None
    assert kwargs["dossier_context_block"] is None
    assert kwargs["personalization_context_data"] is None
    assert kwargs["research_memory_context_block"] is None
    assert kwargs["research_memory_context_data"] is None


@pytest.mark.parametrize(
    "manifest,match",
    [
        ({"schema_version": 1, "run_id": "user:real", "cases": [{}]}, "synthetic"),
        (_manifest(issuer_id="UNKNOWN"), "unregistered"),
        (_manifest(user_id="real-user"), "user state"),
        (_manifest(memory={"transcript": "private"}), "user state"),
    ],
)
def test_non_synthetic_unregistered_and_user_state_fail_closed(manifest, match):
    with pytest.raises(BenchmarkContractError, match=match):
        capture_pipeline_outputs(manifest)


def test_cli_is_dry_run_by_default_and_execute_requires_two_keys(tmp_path, capsys, monkeypatch):
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(_manifest()))
    assert benchmark_pipeline_capture.main([str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["execution_enabled"] is False

    monkeypatch.delenv("CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED", raising=False)
    with pytest.raises(SystemExit) as exc:
        benchmark_pipeline_capture.main([str(path), "--execute"])
    assert exc.value.code == 2
