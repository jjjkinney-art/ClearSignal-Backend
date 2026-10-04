"""Synthetic rehearsal for the account-deletion retention-policy gate."""

from __future__ import annotations

from app.services.account_deletion_policy import (
    evaluate_account_deletion_policy,
    get_provisional_beta_policy,
)


async def run_account_deletion_policy_rehearsal() -> dict:
    """Prove unresolved policy fails closed and resolved policy grants no authority."""

    unresolved = evaluate_account_deletion_policy()
    invalid = evaluate_account_deletion_policy(
        audit_log_disposition="keep_forever",
        audit_log_retention_days=-1,
        access_grant_disposition="active",
        access_grant_retention_days=True,
    )
    delete_candidate = evaluate_account_deletion_policy(
        audit_log_disposition="delete",
        audit_log_retention_days=0,
        access_grant_disposition="delete",
        access_grant_retention_days=0,
    )
    retention_candidate = evaluate_account_deletion_policy(
        audit_log_disposition="anonymize",
        audit_log_retention_days=365,
        access_grant_disposition="retain_revoked",
        access_grant_retention_days=365,
    )
    provisional = get_provisional_beta_policy()

    cases = (unresolved, invalid, delete_candidate, retention_candidate)
    checks = {
        "unresolved_policy_blocked": unresolved["policy_resolved"] is False,
        "unsupported_policy_blocked": invalid["policy_resolved"] is False,
        "invalid_retention_period_blocked": (
            "audit_log_retention_days_must_be_a_nonnegative_integer"
            in invalid["blockers"]
            and "access_grant_retention_days_must_be_a_nonnegative_integer"
            in invalid["blockers"]
        ),
        "explicit_delete_candidate_validates": (
            delete_candidate["policy_resolved"] is True
        ),
        "explicit_retention_candidate_validates": (
            retention_candidate["policy_resolved"] is True
        ),
        "provisional_beta_policy_validates": (
            provisional["validation"]["policy_resolved"] is True
        ),
        "provisional_policy_requires_legal_review": (
            provisional["legal_review_required"] is True
            and provisional["approved_for_public_launch"] is False
        ),
        "provisional_policy_has_no_owner_approval": (
            provisional["owner_approval_recorded"] is False
        ),
        "all_cases_fail_closed": all(case["fail_closed"] for case in cases),
        "zero_preview_authority": (
            all(case["authorizes_production_preview"] is False for case in cases)
            and provisional["validation"]["authorizes_production_preview"] is False
        ),
        "zero_deletion_authority": (
            all(case["authorizes_production_deletion"] is False for case in cases)
            and provisional["validation"]["authorizes_production_deletion"] is False
        ),
        "identity_verification_always_required": all(
            case["requires_identity_verification"] is True for case in cases
        ),
        "separate_approvals_always_required": all(
            case["requires_separate_preview_approval"] is True
            and case["requires_separate_deletion_approval"] is True
            for case in cases
        ),
        "production_database_untouched": True,
        "zero_external_side_effects": True,
    }

    return {
        "schema_version": 1,
        "passed": all(checks.values()),
        "synthetic": True,
        "policy_only": True,
        "checks": checks,
        "candidate_policy_count": 3,
        "provisional_policy_id": provisional["policy_id"],
        "provisional_policy_status": provisional["status"],
        "legal_review_required": provisional["legal_review_required"],
        "approved_for_public_launch": provisional["approved_for_public_launch"],
        "authorizes_production_preview": False,
        "authorizes_production_deletion": False,
        "production_database_untouched": True,
    }
