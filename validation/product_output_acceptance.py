"""End-to-end capture and grading for the first product-output cohort."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping

from .generated_output_grading import GeneratedOutputReport, grade_generated_outputs
from .pipeline_capture import CaptureDecision, PipelineRunner, capture_pipeline_outputs


@dataclass(frozen=True)
class ProductOutputAcceptance:
    schema_version: int
    run_id: str
    execution_enabled: bool
    capture_safety: Dict[str, bool]
    capture_case_count: int
    grading: GeneratedOutputReport | None
    passed: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def run_product_output_acceptance(
    manifest: Mapping[str, Any], *, execute: bool = False,
    runner: PipelineRunner | None = None,
) -> ProductOutputAcceptance:
    capture: CaptureDecision = capture_pipeline_outputs(
        manifest, execute=execute, runner=runner,
    )
    grading = None
    if execute:
        grading = grade_generated_outputs({
            "schema_version": 1,
            "run_id": capture.run_id,
            "cases": list(capture.captured_cases),
        })
    return ProductOutputAcceptance(
        schema_version=1,
        run_id=capture.run_id,
        execution_enabled=execute,
        capture_safety={
            "research_memory_enabled": capture.research_memory_enabled,
            "persistence_enabled": capture.persistence_enabled,
            "notification_delivery_enabled": (
                capture.notification_delivery_enabled
            ),
        },
        capture_case_count=capture.case_count,
        grading=grading,
        passed=bool(grading and grading.passed),
    )
