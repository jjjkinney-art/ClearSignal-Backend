"""Acceptance tests for synthetic full-account deletion preview rehearsal."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
from app.routers import research_memory_admin as admin
from app.services.account_deletion_preview_rehearsal import (
    run_account_deletion_preview_rehearsal,
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
async def test_preview_rehearsal_is_complete_read_only_and_owner_isolated():
    result = await run_account_deletion_preview_rehearsal()

    assert result["passed"] is True
    assert result["database_scope"] == "ephemeral_in_memory"
    assert result["synthetic"] is True
    assert result["read_only"] is True
    assert result["table_count"] >= 40
    assert result["nonzero_table_counts"]["users"] == 1
    assert result["nonzero_table_counts"]["access_grants"] == 1
    assert result["nonzero_table_counts"]["portfolio_positions"] == 1
    assert result["nonzero_table_counts"]["preference_evidence"] == 1
    assert result["nonzero_table_counts"]["thesis_deltas"] == 1
    assert result["production_database_untouched"] is True
    assert all(result["checks"].values())


@pytest.mark.asyncio
async def test_preview_rehearsal_route_is_admin_only_and_aggregate(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_user_ids", ADMIN_ID)

    result = await admin.account_deletion_preview_rehearsal(_request(ADMIN_ID))
    assert result["passed"] is True
    serialized = str(result)
    assert _request(ADMIN_ID).state.auth_subject not in serialized
    assert ADMIN_ID not in serialized
    assert "synthetic question" not in serialized

    with pytest.raises(HTTPException) as forbidden:
        await admin.account_deletion_preview_rehearsal(_request(MEMBER_ID))
    assert forbidden.value.status_code == 403
    with pytest.raises(HTTPException) as unauthenticated:
        await admin.account_deletion_preview_rehearsal(
            _request(None, authenticated=False)
        )
    assert unauthenticated.value.status_code == 401


@pytest.mark.asyncio
async def test_preview_rehearsal_route_redacts_internal_failure(monkeypatch):
    async def unavailable():
        raise RuntimeError("secret preview detail")

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_user_ids", ADMIN_ID)
    monkeypatch.setattr(
        admin,
        "run_account_deletion_preview_rehearsal",
        unavailable,
    )

    with pytest.raises(HTTPException) as failure:
        await admin.account_deletion_preview_rehearsal(_request(ADMIN_ID))
    assert failure.value.status_code == 503
    assert failure.value.detail == (
        "Account deletion preview rehearsal unavailable: RuntimeError"
    )
    assert "secret" not in failure.value.detail
