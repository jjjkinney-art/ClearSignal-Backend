"""Fail-closed policy gate for future account-deletion operations.

This module validates policy choices only. It does not query an account, mutate
data, authorize deletion, or expose a live-account route.
"""

from __future__ import annotations

from typing import Any


POLICY_SCHEMA_VERSION = 1
AUDIT_LOG_DISPOSITIONS = ("delete", "anonymize", "retain")
ACCESS_GRANT_DISPOSITIONS = ("delete", "retain_revoked")


def _normalized_choice(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _retention_days(
    value: Any,
    *,
    disposition: str | None,
    field_name: str,
    blockers: list[str],
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        blockers.append(f"{field_name}_must_be_a_nonnegative_integer")
        return None
    if disposition == "delete" and value != 0:
        blockers.append(f"{field_name}_must_be_zero_when_deleted")
    if disposition in {"anonymize", "retain", "retain_revoked"} and value == 0:
        blockers.append(f"{field_name}_must_be_positive_when_retained")
    return value


def evaluate_account_deletion_policy(
    *,
    audit_log_disposition: Any = None,
    audit_log_retention_days: Any = None,
    access_grant_disposition: Any = None,
    access_grant_retention_days: Any = None,
) -> dict:
    """Validate explicit retention choices and return a non-authorizing gate."""

    blockers: list[str] = []
    audit_choice = _normalized_choice(audit_log_disposition)
    grant_choice = _normalized_choice(access_grant_disposition)

    if audit_choice not in AUDIT_LOG_DISPOSITIONS:
        blockers.append("audit_log_disposition_unresolved_or_unsupported")
    if grant_choice not in ACCESS_GRANT_DISPOSITIONS:
        blockers.append("access_grant_disposition_unresolved_or_unsupported")

    audit_days = _retention_days(
        audit_log_retention_days,
        disposition=audit_choice,
        field_name="audit_log_retention_days",
        blockers=blockers,
    )
    grant_days = _retention_days(
        access_grant_retention_days,
        disposition=grant_choice,
        field_name="access_grant_retention_days",
        blockers=blockers,
    )

    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "policy_resolved": not blockers,
        "fail_closed": True,
        "authorizes_production_preview": False,
        "authorizes_production_deletion": False,
        "requires_identity_verification": True,
        "requires_separate_preview_approval": True,
        "requires_separate_deletion_approval": True,
        "blockers": sorted(set(blockers)),
        "policy": {
            "audit_log": {
                "disposition": audit_choice,
                "retention_days": audit_days,
            },
            "access_grants": {
                "disposition": grant_choice,
                "retention_days": grant_days,
                "revoke_before_handling": True,
            },
        },
    }
