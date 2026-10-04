"""Transactional audit-linkage anonymization for verified account deletion.

This primitive does not commit. A future, separately approved deletion
orchestrator must call it inside the same transaction as the associated account
deletion and must roll back on any count mismatch.
"""

from __future__ import annotations

from sqlalchemy import update

from app.db.models import Base


ANONYMIZED_AUDIT_FIELDS = (
    "user_id",
    "resource_id",
    "ip_address",
    "user_agent",
)
PRESERVED_AUDIT_FIELDS = (
    "id",
    "resource",
    "action",
    "created_at",
)


def _required_user_id(value: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError("Verified user id is required")
    return normalized


async def anonymize_account_audit_log(session, *, user_id: str) -> int:
    """Remove all account-linkable fields and return the affected row count."""

    owner = _required_user_id(user_id)
    table = Base.metadata.tables["audit_log"]
    result = await session.execute(
        update(table)
        .where(table.c.user_id == owner)
        .values(
            user_id=None,
            resource_id=None,
            ip_address=None,
            user_agent=None,
        )
    )
    return int(result.rowcount or 0)
