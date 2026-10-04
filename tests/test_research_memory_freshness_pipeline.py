"""Integration guard for selected-memory freshness response metadata."""

from pathlib import Path


def test_router_attaches_freshness_after_audited_comparison():
    source = Path("app/services/router_service.py").read_text(encoding="utf-8")
    comparison = source.index(
        '_selected_research_metadata["comparison"] = _selected_research_comparison'
    )
    freshness = source.index(
        "_selected_research_metadata = _attach_historical_freshness("
    )
    response = source.index("return AgentAnswerResponse(")

    assert comparison < freshness < response
    assert "historical_record_freshness" not in source[source.index("answer={"):response]
