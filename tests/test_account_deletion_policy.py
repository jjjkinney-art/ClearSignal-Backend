"""Acceptance tests for the account-deletion retention-policy gate."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
from app.routers import research_memory_admin as admin
from app.services.account_deletion_policy import (
    evaluate_account_deletion_policy,
    get_provisional_beta_policy,
)
from app.services.account_deletion_policy_rehearsal import (
    run_account_deletion_policy_rehearsal,
)


ADMIN_ID = "11111111-1111-4111-8111-111111111111"
MEMBER_ID = "22222222-2222-4222-8222-222222222222"


def _request(user_id: str | None, *, authenticated: bool = True) -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.user_id = user_id
    request.state.is_authenticated = authenticated
    request.state.auth_subject = f"subject:{user_id}" if authenticated else None
    return request


def test_policy_gate_blocks_missing_unsupported_and_inconsistent_values():
    unresolved = evaluate_account_deletion_policy()
    assert unresolved["policy_resolved"] is False
    assert unresolved["authorizes_production_deletion"] is False

    unsupported = evaluate_account_deletion_policy(
        audit_log_disposition="keep",
        audit_log_retention_days=0,
        access_grant_disposition="leave_active",
        access_grant_retention_days=0,
    )
    assert unsupported["policy_resolved"] is False

    inconsistent = evaluate_account_deletion_policy(
        audit_log_disposition="delete",
        audit_log_retention_days=30,
        access_grant_disposition="retain_revoked",
        access_grant_retention_days=0,
    )
    assert inconsistent["policy_resolved"] is False
    assert "audit_log_retention_days_must_be_zero_when_deleted" in inconsistent["blockers"]
    assert (
        "access_grant_retention_days_must_be_positive_when_retained"
        in inconsistent["blockers"]
    )


def test_policy_gate_validates_candidates_without_authorizing_operations():
    result = evaluate_account_deletion_policy(
        audit_log_disposition="anonymize",
        audit_log_retention_days=365,
        access_grant_disposition="retain_revoked",
        access_grant_retention_days=365,
    )
    assert result["policy_resolved"] is True
    assert result["fail_closed"] is True
    assert result["authorizes_production_preview"] is False
    assert result["authorizes_production_deletion"] is False
    assert result["requires_identity_verification"] is True
    assert result["requires_separate_preview_approval"] is True
    assert result["requires_separate_deletion_approval"] is True


def test_provisional_beta_policy_is_structurally_valid_but_not_launch_approved():
    result = get_provisional_beta_policy()
    assert result["policy_id"] == "account-retention-v1-beta"
    assert result["status"] == "provisional_pending_legal_review"
    assert result["validation"]["policy_resolved"] is True
    assert result["validation"]["policy"]["audit_log"] == {
        "disposition": "anonymize",
        "retention_days": 365,
    }
    assert result["validation"]["policy"]["access_grants"] == {
        "disposition": "delete",
        "retention_days": 0,
        "revoke_before_handling": True,
    }
    assert result["deletion_request_target_days"] == 30
    assert result["review_interval_days"] == 180
    assert result["legal_review_required"] is True
    assert result["owner_approval_recorded"] is False
    assert result["approved_for_public_launch"] is False
    assert result["validation"]["authorizes_production_preview"] is False
    assert result["validation"]["authorizes_production_deletion"] is False


@pytest.mark.asyncio
async def test_policy_rehearsal_passes_without_side_effects():
    result = await run_account_deletion_policy_rehearsal()
    assert result["passed"] is True
    assert result["synthetic"] is True
    assert result["policy_only"] is True
    assert result["production_database_untouched"] is True
    assert result["authorizes_production_preview"] is False
    assert result["authorizes_production_deletion"] is False
    assert all(result["checks"].values())


@pytest.mark.asyncio
async def test_policy_rehearsal_route_is_admin_only(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_user_ids", ADMIN_ID)

    result = await admin.account_deletion_policy_rehearsal(_request(ADMIN_ID))
    assert result["passed"] is True

    with pytest.raises(HTTPException) as forbidden:
        await admin.account_deletion_policy_rehearsal(_request(MEMBER_ID))
    assert forbidden.value.status_code == 403

    with pytest.raises(HTTPException) as unauthenticated:
        await admin.account_deletion_policy_rehearsal(
            _request(None, authenticated=False)
        )
    assert unauthenticated.value.status_code == 401


@pytest.mark.asyncio
async def test_policy_rehearsal_route_redacts_internal_failure(monkeypatch):
    async def unavailable():
        raise RuntimeError("secret policy detail")

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_user_ids", ADMIN_ID)
    monkeypatch.setattr(
        admin,
        "run_account_deletion_policy_rehearsal",
        unavailable,
    )

    with pytest.raises(HTTPException) as failure:
        await admin.account_deletion_policy_rehearsal(_request(ADMIN_ID))
    assert failure.value.status_code == 503
    assert failure.value.detail == (
        "Account deletion policy rehearsal unavailable: RuntimeError"
    )
    assert "secret" not in failure.value.detail
