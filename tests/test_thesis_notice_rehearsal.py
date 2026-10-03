"""Acceptance tests for the synthetic thesis-notice positive-path rehearsal."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
from app.routers import research_memory_admin as admin
from app.services.thesis_notice_rehearsal import run_thesis_notice_rehearsal


ADMIN_ID = "11111111-1111-4111-8111-111111111111"
MEMBER_ID = "22222222-2222-4222-8222-222222222222"


def _request(user_id: str | None, *, authenticated: bool = True) -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.user_id = user_id
    request.state.is_authenticated = authenticated
    request.state.auth_subject = f"subject:{user_id}" if authenticated else None
    return request


@pytest.mark.asyncio
async def test_rehearsal_proves_positive_path_dedupe_and_isolation():
    result = await run_thesis_notice_rehearsal()

    assert result["passed"] is True
    assert result["database_scope"] == "ephemeral_in_memory"
    assert result["synthetic"] is True
    assert result["candidate_count"] == 1
    assert result["persisted_count"] == 1
    assert result["foreign_owner_count"] == 0
    assert result["delivery_enabled"] is False
    assert all(result["checks"].values())


@pytest.mark.asyncio
async def test_admin_route_is_protected_and_returns_only_aggregate_state(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_user_ids", ADMIN_ID)

    result = await admin.thesis_notice_rehearsal(_request(ADMIN_ID))
    assert result["passed"] is True
    serialized = str(result)
    assert "synthetic-owner" not in serialized
    assert "synthetic-message" not in serialized

    with pytest.raises(HTTPException) as forbidden:
        await admin.thesis_notice_rehearsal(_request(MEMBER_ID))
    assert forbidden.value.status_code == 403
    with pytest.raises(HTTPException) as unauthenticated:
        await admin.thesis_notice_rehearsal(_request(None, authenticated=False))
    assert unauthenticated.value.status_code == 401


@pytest.mark.asyncio
async def test_admin_route_redacts_internal_failure(monkeypatch):
    async def unavailable():
        raise RuntimeError("secret database detail")

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_user_ids", ADMIN_ID)
    monkeypatch.setattr(admin, "run_thesis_notice_rehearsal", unavailable)

    with pytest.raises(HTTPException) as failure:
        await admin.thesis_notice_rehearsal(_request(ADMIN_ID))
    assert failure.value.status_code == 503
    assert failure.value.detail == "Thesis notice rehearsal unavailable: RuntimeError"
    assert "secret" not in failure.value.detail
