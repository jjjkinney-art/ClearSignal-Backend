"""Controlled capture of real pipeline responses for offline grading.

Capture is an explicit, synthetic-only operation. It bypasses the authenticated
API boundary and therefore must never accept user memory or enable persistence.
The full analysis pipeline still retrieves evidence and generates an answer;
only the returned serialized payload is retained by the caller.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Any, Callable, Dict, Mapping, Tuple

from .benchmark_registry import IssuerRegistry, load_registry
from .intelligence_benchmark import BenchmarkContractError


SCHEMA_VERSION = 1
MAX_CASES = 20
PipelineRunner = Callable[[str, str, str], Mapping[str, Any]]


@dataclass(frozen=True)
class CaptureDecision:
    schema_version: int
    run_id: str
    case_count: int
    execution_enabled: bool
    provider_execution_required: bool
    research_memory_enabled: bool
    persistence_enabled: bool
    notification_delivery_enabled: bool
    captured_cases: Tuple[dict, ...]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _default_runner(ticker: str, question: str, request_id: str) -> Mapping[str, Any]:
    # Imports stay inside the explicitly enabled execution path. Merely loading
    # or validating a capture manifest cannot initialize providers or app state.
    from app.schemas import CompanyContext
    from app.services.company_detection import detect_company
    from app.services.router_service import _run_investment_pipeline

    company = detect_company(ticker)
    if company is None or company.ticker != ticker:
        raise BenchmarkContractError(f"capture could not resolve exact ticker {ticker}")
    if not isinstance(company, CompanyContext):
        raise BenchmarkContractError("capture resolver returned an invalid company")
    response = _run_investment_pipeline(
        company=company,
        question=question,
        request_id=request_id,
        memory_context_block=None,
        memory_context_data=None,
        dossier_context_block=None,
        personalization_context_data=None,
        research_memory_context_block=None,
        research_memory_context_data=None,
        side_effects_enabled=False,
    )
    try:
        return response.model_dump()
    except AttributeError:
        return response.dict()


def capture_pipeline_outputs(
    manifest: Mapping[str, Any], *, execute: bool = False,
    runner: PipelineRunner | None = None,
    registry: IssuerRegistry | None = None,
) -> CaptureDecision:
    """Validate a synthetic manifest and optionally execute its cases."""
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise BenchmarkContractError("pipeline-capture schema_version must be 1")
    run_id = str(manifest.get("run_id", "")).strip()
    if not run_id.startswith("synthetic:"):
        raise BenchmarkContractError("pipeline-capture run_id must be synthetic")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases or len(cases) > MAX_CASES:
        raise BenchmarkContractError(f"pipeline-capture requires 1-{MAX_CASES} cases")
    registry = registry or load_registry()
    allowed = registry.by_ticker()
    seen = set()
    validated = []
    for case in cases:
        if not isinstance(case, Mapping):
            raise BenchmarkContractError("pipeline-capture cases must be objects")
        ticker = str(case.get("issuer_id", "")).upper().strip()
        question_id = str(case.get("question_id", "")).strip()
        question = str(case.get("question", "")).strip()
        key = (ticker, question_id)
        if ticker not in allowed:
            raise BenchmarkContractError(f"pipeline-capture issuer {ticker} is unregistered")
        if not question_id or not question or len(question) > 500:
            raise BenchmarkContractError("capture question_id and 1-500 character question are required")
        if key in seen:
            raise BenchmarkContractError("pipeline-capture issuer/question pairs must be unique")
        forbidden = {
            "account_id", "user_id", "memory", "memory_context",
            "personalization", "conversation_id", "delivery",
        }
        if forbidden.intersection(case):
            raise BenchmarkContractError("pipeline-capture cases cannot contain user state")
        seen.add(key)
        validated.append((case, ticker, question_id, question))

    captured = []
    if execute:
        active_runner = runner or _default_runner
        for case, ticker, question_id, question in validated:
            request_id = f"{run_id}:{ticker}:{question_id}"
            started = time.monotonic()
            response = active_runner(ticker, question, request_id)
            elapsed_ms = round((time.monotonic() - started) * 1000, 3)
            if not isinstance(response, Mapping):
                raise BenchmarkContractError("pipeline runner must return a response object")
            # Preserve frozen grading inputs but replace any pre-existing
            # response. A manifest can never smuggle a hand-authored capture.
            output = {
                key: value for key, value in case.items()
                if key not in {"question", "response"}
            }
            output["response"] = dict(response)
            output["capture_metadata"] = {
                "elapsed_ms": elapsed_ms,
                "pipeline_elapsed_s": (
                    response.get("routing", {}).get("pipeline_elapsed_s")
                    if isinstance(response.get("routing"), Mapping) else None
                ),
            }
            captured.append(output)

    return CaptureDecision(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        case_count=len(validated),
        execution_enabled=execute,
        provider_execution_required=execute,
        research_memory_enabled=False,
        persistence_enabled=False,
        notification_delivery_enabled=False,
        captured_cases=tuple(captured),
    )
