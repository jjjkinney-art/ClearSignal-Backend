"""Production wiring tests for zero-delivery thesis notice previews."""

import inspect

from app.services.router_service import _run_investment_pipeline


def test_notice_preview_runs_after_evidence_admission():
    source = inspect.getsource(_run_investment_pipeline)
    admission = source.index("admit_evidence(")
    preview = source.index("build_selected_thesis_notice_preview(")

    assert admission < preview
    assert "evidence_items=evidence" in source


def test_notice_preview_requires_explicit_selected_memory():
    source = inspect.getsource(_run_investment_pipeline)
    preview_guard = (
        'if research_memory_context_data '
        'and research_memory_context_data.get("applied") is True:'
    )

    assert source.count(preview_guard) >= 2
    assert "context=research_memory_context_data" in source


def test_notice_preview_is_bounded_response_metadata_only():
    source = inspect.getsource(_run_investment_pipeline)

    assert (
        '_selected_research_metadata["thesis_notice_preview"] = '
        "_thesis_notice_preview"
    ) in source
    assert '"delivery_enabled": False' in source
    assert "thesis_notice_preview" not in source.split("answer={", 1)[1].split(
        "routing={", 1
    )[0]


def test_notice_preview_failure_is_explicit_and_fail_closed():
    source = inspect.getsource(_run_investment_pipeline)

    assert '"preview_version": 1' in source
    assert '"available": False' in source
    assert '"status": "unavailable"' in source
    assert '"candidates": []' in source
