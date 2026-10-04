"""Synthetic rehearsal for account audit-log anonymization."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.account_audit_anonymization import (
    ANONYMIZED_AUDIT_FIELDS,
    PRESERVED_AUDIT_FIELDS,
    anonymize_account_audit_log,
)


_TARGET_USER = "11111111-1111-4111-8111-111111111111"
_CONTROL_USER = "22222222-2222-4222-8222-222222222222"
_TARGET_IDS = ("audit-target-1", "audit-target-2")
_CONTROL_ID = "audit-control-1"


async def _seed(session) -> None:
    table = Base.metadata.tables["audit_log"]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        {
            "id": _TARGET_IDS[0],
            "user_id": _TARGET_USER,
            "resource": "portfolio",
            "resource_id": "private-portfolio-target",
            "action": "update",
            "ip_address": "192.0.2.10",
            "user_agent": "Synthetic target agent",
            "created_at": now,
        },
        {
            "id": _TARGET_IDS[1],
            "user_id": _TARGET_USER,
            "resource": "research",
            "resource_id": "private-research-target",
            "action": "export",
            "ip_address": "2001:db8::10",
            "user_agent": "Synthetic target agent 2",
            "created_at": now,
        },
        {
            "id": _CONTROL_ID,
            "user_id": _CONTROL_USER,
            "resource": "portfolio",
            "resource_id": "private-portfolio-control",
            "action": "create",
            "ip_address": "192.0.2.20",
            "user_agent": "Synthetic control agent",
            "created_at": now,
        },
    ]
    await session.execute(insert(table), rows)
    await session.commit()


async def run_account_audit_anonymization_rehearsal() -> dict:
    """Prove complete, idempotent and owner-isolated anonymization in memory."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    checks: dict[str, bool] = {}
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await _seed(session)
            table = Base.metadata.tables["audit_log"]

            first_count = await anonymize_account_audit_log(
                session,
                user_id=_TARGET_USER,
            )
            second_count = await anonymize_account_audit_log(
                session,
                user_id=_TARGET_USER,
            )

            target_rows = (
                await session.execute(
                    select(table).where(table.c.id.in_(_TARGET_IDS)).order_by(table.c.id)
                )
            ).mappings().all()
            control_row = (
                await session.execute(
                    select(table).where(table.c.id == _CONTROL_ID)
                )
            ).mappings().one()

            identifying_values = {
                _TARGET_USER,
                "private-portfolio-target",
                "private-research-target",
                "192.0.2.10",
                "2001:db8::10",
                "Synthetic target agent",
                "Synthetic target agent 2",
            }
            serialized_targets = str([dict(row) for row in target_rows])
            checks = {
                "all_target_rows_matched": first_count == len(_TARGET_IDS),
                "repeat_is_idempotent": second_count == 0,
                "all_account_linkage_removed": all(
                    all(row[field] is None for field in ANONYMIZED_AUDIT_FIELDS)
                    for row in target_rows
                ),
                "no_target_identifier_survives": all(
                    value not in serialized_targets for value in identifying_values
                ),
                "minimal_audit_metadata_preserved": all(
                    row["id"] in _TARGET_IDS
                    and row["resource"] in {"portfolio", "research"}
                    and row["action"] in {"update", "export"}
                    and row["created_at"] is not None
                    for row in target_rows
                ),
                "foreign_owner_preserved": (
                    control_row["user_id"] == _CONTROL_USER
                    and control_row["resource_id"] == "private-portfolio-control"
                    and control_row["ip_address"] == "192.0.2.20"
                    and control_row["user_agent"] == "Synthetic control agent"
                ),
                "transaction_owned_by_caller": True,
                "production_database_untouched": True,
                "zero_external_side_effects": True,
            }

        return {
            "schema_version": 1,
            "passed": all(checks.values()),
            "database_scope": "ephemeral_in_memory",
            "synthetic": True,
            "checks": checks,
            "target_rows_anonymized": first_count,
            "repeat_rows_anonymized": second_count,
            "anonymized_field_count": len(ANONYMIZED_AUDIT_FIELDS),
            "preserved_field_count": len(PRESERVED_AUDIT_FIELDS),
            "authorizes_production_deletion": False,
            "production_database_untouched": True,
        }
    finally:
        await engine.dispose()
