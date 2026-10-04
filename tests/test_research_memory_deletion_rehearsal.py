"""Acceptance coverage for synthetic research-memory deletion rehearsal."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
from app.routers import research_memory_admin as admin
from app.services.research_memory_deletion_rehearsal import (
    run_research_memory_deletion_rehearsal,
)


ADMIN_ID = "11111111-1111-4111-8111-111111111111"
MEMBER_ID = "22222222-2222-4222-8222-222222222222"


def _request(user_id: str | None, *, authenticated: bool = True) -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.user_id = user_id
    request.state.is_authenticated = authenticated
    request.state.auth_subject = f"subject:{user_id}" if authenticated else None
    return request


@pytest.mark.asyncio
async def test_rehearsal_proves_complete_purge_retrieval_invalidation_and_isolation():
    result = await run_research_memory_deletion_rehearsal()

    assert result["passed"] is True
    assert result["database_scope"] == "ephemeral_in_memory"
    assert result["synthetic"] is True
    assert result["preview_counts"] == {
        "conversations": 1,
        "messages": 1,
        "personalization_profiles": 1,
        "thesis_notices": 1,
    }
    assert result["deleted_counts"] == result["preview_counts"]
    assert set(result["remaining_target_counts"].values()) == {0}
    assert result["foreign_owner_preserved"] is True
    assert result["production_database_untouched"] is True
    assert all(result["checks"].values())


@pytest.mark.asyncio
async def test_deletion_rehearsal_route_is_admin_only_and_aggregate(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_user_ids", ADMIN_ID)

    result = await admin.research_memory_deletion_rehearsal(_request(ADMIN_ID))
    assert result["passed"] is True
    serialized = str(result)
    assert "synthetic-deletion-target" not in serialized
    assert "synthetic-conversation" not in serialized
    assert "Apple" not in serialized

    with pytest.raises(HTTPException) as forbidden:
        await admin.research_memory_deletion_rehearsal(_request(MEMBER_ID))
    assert forbidden.value.status_code == 403
    with pytest.raises(HTTPException) as unauthenticated:
        await admin.research_memory_deletion_rehearsal(
            _request(None, authenticated=False)
        )
    assert unauthenticated.value.status_code == 401


@pytest.mark.asyncio
async def test_deletion_rehearsal_route_redacts_internal_failure(monkeypatch):
    async def unavailable():
        raise RuntimeError("secret deletion detail")

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_user_ids", ADMIN_ID)
    monkeypatch.setattr(
        admin,
        "run_research_memory_deletion_rehearsal",
        unavailable,
    )

    with pytest.raises(HTTPException) as failure:
        await admin.research_memory_deletion_rehearsal(_request(ADMIN_ID))
    assert failure.value.status_code == 503
    assert failure.value.detail == (
        "Research memory deletion rehearsal unavailable: RuntimeError"
    )
    assert "secret" not in failure.value.detail
