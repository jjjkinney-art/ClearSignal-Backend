"""Acceptance tests for account-owned thesis notice previews."""

import asyncio
import inspect

from app.services.thesis_notice_preview import (
    build_selected_thesis_notice_preview,
    preview_selected_thesis_notices,
)


def _context(**changes):
    value = {
        "applied": True,
        "status": "applied",
        "conversation_id": "conversation-a",
        "message_id": "message-a",
        "ticker": "AAPL",
        "created_at": "2026-09-27T00:00:00Z",
        "historical_thesis": {
            "direct_answer": "Services retention and installed base support growth.",
        },
    }
    value.update(changes)
    return value


def _evidence(**changes):
    value = {
        "id": "E1",
        "ticker": "AAPL",
        "title": "Quarterly services update",
        "summary": "Services retention across the installed base improved.",
        "published_at": "2026-10-01",
        "freshness_status": "current",
        "source": "SEC EDGAR",
        "url": "https://www.sec.gov/Archives/example.htm",
    }
    value.update(changes)
    return value


def test_preview_projects_selection_and_keeps_delivery_disabled():
    result = build_selected_thesis_notice_preview(
        context=_context(), evidence_items=[_evidence()]
    )
    assert result["available"] is True
    assert result["delivery_enabled"] is False
    assert result["status"] == "candidate_found"
    assert result["selection"] == {
        "conversation_id": "conversation-a",
        "message_id": "message-a",
        "ticker": "AAPL",
        "recorded_at": "2026-09-27T00:00:00Z",
        "historical_only": True,
    }
    assert [item["evidence_id"] for item in result["candidates"]] == ["E1"]
    assert result["evaluation_summary"] == {
        "evaluated_count": 1,
        "eligible_count": 1,
        "rejection_counts": {},
    }
    assert result["candidates"][0]["evidence"] == {
        "title": "Quarterly services update",
        "source": "SEC EDGAR",
        "published_at": "2026-10-01",
        "url": "https://www.sec.gov/Archives/example.htm",
        "document_type": None,
        "section": None,
        "page": None,
    }
    assert "historical_thesis" not in result


def test_preview_returns_explicit_empty_state_for_non_material_evidence():
    result = build_selected_thesis_notice_preview(
        context=_context(),
        evidence_items=[_evidence(title="Board appointment", summary="New director")],
    )
    assert result["status"] == "no_material_change_candidate"
    assert result["candidates"] == []
    assert result["evaluation_summary"] == {
        "evaluated_count": 1,
        "eligible_count": 0,
        "rejection_counts": {"not_materially_related": 1},
    }
    assert result["delivery_enabled"] is False


def test_preview_summarizes_mixed_rejections_without_private_payloads():
    result = build_selected_thesis_notice_preview(
        context=_context(),
        evidence_items=[
            _evidence(id="old", published_at="2026-09-01"),
            _evidence(id="other", ticker="MSFT"),
            _evidence(id="conflict", material_conflict=True),
        ],
    )
    assert result["evaluation_summary"] == {
        "evaluated_count": 3,
        "eligible_count": 0,
        "rejection_counts": {
            "evidence_not_admitted": 1,
            "not_newer_than_thesis": 1,
            "ticker_mismatch": 1,
        },
    }
    serialized = str(result["evaluation_summary"])
    assert "old" not in serialized
    assert "other" not in serialized
    assert "conflict" not in serialized


def test_preview_strips_unsafe_evidence_urls():
    result = build_selected_thesis_notice_preview(
        context=_context(),
        evidence_items=[_evidence(url="https://example.com/data?token=secret")],
    )
    assert result["status"] == "candidate_found"
    assert result["candidates"][0]["evidence"]["url"] is None


def test_unapplied_deleted_or_malformed_context_fails_closed():
    for context, expected in (
        ({"applied": False, "status": "unavailable"}, "unavailable"),
        ({"applied": False, "status": "ticker_mismatch"}, "ticker_mismatch"),
        (_context(message_id=""), "unavailable"),
        (_context(historical_thesis={}), "no_structured_snapshot"),
    ):
        result = build_selected_thesis_notice_preview(
            context=context, evidence_items=[_evidence()]
        )
        assert result["available"] is False
        assert result["delivery_enabled"] is False
        assert result["status"] == expected
        assert result["candidates"] == []


def test_async_boundary_forwards_owner_and_explicit_selection(monkeypatch):
    captured = {}

    async def fake_loader(session, **kwargs):
        captured.update(kwargs)
        return _context()

    import app.services.research_memory_context as memory_context
    monkeypatch.setattr(memory_context, "load_selected_research_context", fake_loader)

    result = asyncio.run(preview_selected_thesis_notices(
        object(), user_id="owner-a", conversation_id="conversation-a",
        target_ticker="AAPL", evidence_items=[_evidence()],
    ))
    assert captured == {
        "user_id": "owner-a",
        "conversation_id": "conversation-a",
        "target_ticker": "AAPL",
    }
    assert result["status"] == "candidate_found"


def test_preview_boundary_has_no_persistence_or_delivery_calls():
    source = inspect.getsource(preview_selected_thesis_notices)
    for forbidden in ("commit(", "flush(", "send_", "notify", "schedule", "publish"):
        assert forbidden not in source
