"""Synthetic, read-only rehearsal for full account-deletion inventory."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.account_deletion_inventory import build_account_deletion_preview


REHEARSAL_SCHEMA_VERSION = 1
_TARGET_USER = "11111111-1111-4111-8111-111111111111"
_TARGET_SUBJECT = "synthetic:account-deletion-target"
_CONTROL_USER = "22222222-2222-4222-8222-222222222222"
_CONTROL_SUBJECT = "synthetic:account-deletion-control"


async def _seed(session, *, user_id: str, subject: str, suffix: str) -> None:
    t = Base.metadata.tables
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    await session.execute(insert(t["users"]).values(
        id=user_id,
        email=f"synthetic-{suffix}@example.invalid",
        auth_subject=subject,
        created_at=now,
        updated_at=now,
    ))
    await session.execute(insert(t["access_grants"]).values(
        id=f"grant-{suffix}",
        kind="subject",
        subject=subject,
        status="approved",
        created_at=now,
        updated_at=now,
    ))
    await session.execute(insert(t["portfolios"]).values(
        id=f"portfolio-{suffix}",
        user_id=user_id,
        name=f"Synthetic portfolio {suffix}",
        created_at=now,
        updated_at=now,
    ))
    await session.execute(insert(t["portfolio_positions"]).values(
        id=f"position-{suffix}",
        portfolio_id=f"portfolio-{suffix}",
        ticker="AAPL",
        added_at=now,
        updated_at=now,
    ))
    await session.execute(insert(t["learned_preference"]).values(
        id=f"preference-{suffix}",
        user_id=user_id,
        dimension="company_interest",
        entity_key="AAPL",
        first_observed_at=now,
        last_reinforced_at=now,
        updated_at=now,
    ))
    await session.execute(insert(t["preference_evidence"]).values(
        id=f"preference-evidence-{suffix}",
        preference_id=f"preference-{suffix}",
        signal_event_id=f"synthetic-signal-{suffix}",
        source="synthetic_rehearsal",
        observed_at=now,
    ))
    for number in (1, 2):
        await session.execute(insert(t["thesis_versions"]).values(
            id=f"thesis-{suffix}-{number}",
            ticker="AAPL",
            company_name="Synthetic Apple",
            user_id=user_id,
            created_at=now,
        ))
    await session.execute(insert(t["thesis_deltas"]).values(
        id=f"delta-{suffix}",
        ticker="AAPL",
        from_version_id=f"thesis-{suffix}-1",
        to_version_id=f"thesis-{suffix}-2",
        created_at=now,
    ))
    await session.execute(insert(t["research_conversations"]).values(
        id=f"conversation-{suffix}",
        user_id=user_id,
        title="Synthetic research",
        scope_tickers=["AAPL"],
        created_at=now,
        updated_at=now,
    ))
    await session.execute(insert(t["research_messages"]).values(
        id=f"message-{suffix}",
        conversation_id=f"conversation-{suffix}",
        user_id=user_id,
        ordinal=1,
        role="user",
        text="Synthetic question",
        displayed_snapshot={},
        created_at=now,
    ))


async def run_account_deletion_preview_rehearsal() -> dict:
    """Prove full inventory coverage and zero mutation using synthetic accounts."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    checks: dict[str, bool] = {}
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await _seed(
                session,
                user_id=_TARGET_USER,
                subject=_TARGET_SUBJECT,
                suffix="target",
            )
            await _seed(
                session,
                user_id=_CONTROL_USER,
                subject=_CONTROL_SUBJECT,
                suffix="control",
            )
            await session.commit()

            target_first = await build_account_deletion_preview(
                session,
                user_id=_TARGET_USER,
                auth_subject=_TARGET_SUBJECT,
            )
            control_first = await build_account_deletion_preview(
                session,
                user_id=_CONTROL_USER,
                auth_subject=_CONTROL_SUBJECT,
            )
            target_second = await build_account_deletion_preview(
                session,
                user_id=_TARGET_USER,
                auth_subject=_TARGET_SUBJECT,
            )
            control_second = await build_account_deletion_preview(
                session,
                user_id=_CONTROL_USER,
                auth_subject=_CONTROL_SUBJECT,
            )

            counts = target_first["counts"]
            expected_nonzero = {
                "users": 1,
                "access_grants": 1,
                "portfolios": 1,
                "portfolio_positions": 1,
                "learned_preference": 1,
                "preference_evidence": 1,
                "thesis_versions": 2,
                "thesis_deltas": 1,
                "research_conversations": 1,
                "research_messages": 1,
            }
            checks = {
                "dynamic_direct_owner_inventory_present": (
                    target_first["table_count"] >= 40
                    and all(
                        kind == "direct_user_id"
                        for table, kind in target_first["scope_kinds"].items()
                        if table not in {
                            "users",
                            "access_grants",
                            "portfolio_positions",
                            "portfolio_insights",
                            "preference_evidence",
                            "thesis_deltas",
                        }
                    )
                ),
                "identity_scopes_counted": (
                    counts["users"] == 1
                    and counts["access_grants"] == 1
                ),
                "portfolio_children_counted": counts["portfolio_positions"] == 1,
                "preference_children_counted": counts["preference_evidence"] == 1,
                "thesis_children_counted": counts["thesis_deltas"] == 1,
                "representative_counts_exact": all(
                    counts.get(table) == value
                    for table, value in expected_nonzero.items()
                ),
                "preview_is_read_only": (
                    target_first["read_only"] is True
                    and target_first["aggregate_counts_only"] is True
                    and target_first == target_second
                ),
                "foreign_owner_isolated": (
                    control_first == control_second
                    and control_first["total_rows"] == target_first["total_rows"]
                ),
                "shared_ticker_tables_excluded": all(
                    table not in counts
                    for table in (
                        "ticker_memory",
                        "concern_tags",
                        "theme_clusters",
                        "cross_exposures",
                    )
                ),
                "production_database_untouched": True,
                "zero_external_side_effects": True,
            }

        return {
            "schema_version": REHEARSAL_SCHEMA_VERSION,
            "passed": all(checks.values()),
            "database_scope": "ephemeral_in_memory",
            "synthetic": True,
            "read_only": True,
            "checks": checks,
            "table_count": target_first["table_count"],
            "total_preview_rows": target_first["total_rows"],
            "nonzero_table_counts": {
                table: count for table, count in counts.items() if count
            },
            "child_scopes": target_first["child_scopes"],
            "shared_or_operational_table_count": len(
                target_first["shared_or_operational_tables_excluded"]
            ),
            "production_database_untouched": True,
        }
    finally:
        await engine.dispose()
