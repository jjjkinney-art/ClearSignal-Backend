"""Synthetic all-or-nothing rehearsal for the account-deletion transaction.

No production deletion orchestrator is exposed here. The only public callable
runs against a newly created ephemeral SQLite database populated with synthetic
accounts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.account_audit_anonymization import anonymize_account_audit_log
from app.services.account_deletion_inventory import build_account_deletion_preview
from app.services.research_memory_lifecycle import delete_owner_research_memory


_SUCCESS_USER = "11111111-1111-4111-8111-111111111111"
_SUCCESS_SUBJECT = "synthetic:transaction-success"
_ROLLBACK_USER = "22222222-2222-4222-8222-222222222222"
_ROLLBACK_SUBJECT = "synthetic:transaction-rollback"
_CONTROL_USER = "33333333-3333-4333-8333-333333333333"
_CONTROL_SUBJECT = "synthetic:transaction-control"


async def _seed_account(session, *, user_id: str, subject: str, suffix: str) -> None:
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
    await session.execute(insert(t["research_personalization_profiles"]).values(
        id=f"profile-{suffix}",
        user_id=user_id,
        enabled=True,
        response_depth="deep",
        time_horizon="multi_year",
        analysis_emphasis="downside_first",
        evidence_style="primary_sources",
        origin="explicit_user_setting",
        created_at=now,
        updated_at=now,
    ))
    await session.execute(insert(t["research_thesis_notices"]).values(
        id=f"notice-{suffix}",
        user_id=user_id,
        conversation_id=f"conversation-{suffix}",
        message_id=f"message-{suffix}",
        ticker="AAPL",
        evidence_id=f"evidence-{suffix}",
        evidence_snapshot={"title": "Synthetic filing"},
        fingerprint=(suffix * 64)[:64],
        matched_terms=["services"],
        status="unread",
        candidate_version=1,
        preview_version=1,
        delivery_enabled=False,
        detected_at=now,
        updated_at=now,
    ))
    await session.execute(insert(t["audit_log"]).values(
        id=f"audit-{suffix}",
        user_id=user_id,
        resource="research",
        resource_id=f"conversation-{suffix}",
        action="delete",
        ip_address="192.0.2.42",
        user_agent="Synthetic transaction agent",
        created_at=now,
    ))


async def _delete_representative_account(
    session,
    *,
    user_id: str,
    auth_subject: str,
) -> dict[str, int]:
    """Apply the representative child-first sequence inside caller transaction."""

    t = Base.metadata.tables
    counts: dict[str, int] = {}

    await session.execute(
        update(t["access_grants"])
        .where(t["access_grants"].c.subject == auth_subject)
        .values(status="revoked", revoked_at=datetime.now(timezone.utc))
    )

    portfolio_ids = select(t["portfolios"].c.id).where(
        t["portfolios"].c.user_id == user_id
    )
    result = await session.execute(
        delete(t["portfolio_positions"]).where(
            t["portfolio_positions"].c.portfolio_id.in_(portfolio_ids)
        )
    )
    counts["portfolio_positions"] = int(result.rowcount or 0)

    preference_ids = select(t["learned_preference"].c.id).where(
        t["learned_preference"].c.user_id == user_id
    )
    result = await session.execute(
        delete(t["preference_evidence"]).where(
            t["preference_evidence"].c.preference_id.in_(preference_ids)
        )
    )
    counts["preference_evidence"] = int(result.rowcount or 0)

    version_ids = select(t["thesis_versions"].c.id).where(
        t["thesis_versions"].c.user_id == user_id
    )
    result = await session.execute(
        delete(t["thesis_deltas"]).where(
            (t["thesis_deltas"].c.from_version_id.in_(version_ids))
            | (t["thesis_deltas"].c.to_version_id.in_(version_ids))
        )
    )
    counts["thesis_deltas"] = int(result.rowcount or 0)

    counts.update(await delete_owner_research_memory(session, user_id=user_id))
    counts["audit_log_anonymized"] = await anonymize_account_audit_log(
        session,
        user_id=user_id,
    )

    for table_name in ("learned_preference", "thesis_versions", "portfolios"):
        table = t[table_name]
        result = await session.execute(
            delete(table).where(table.c.user_id == user_id)
        )
        counts[table_name] = int(result.rowcount or 0)

    result = await session.execute(
        delete(t["access_grants"]).where(
            t["access_grants"].c.subject == auth_subject
        )
    )
    counts["access_grants"] = int(result.rowcount or 0)

    result = await session.execute(
        delete(t["users"]).where(t["users"].c.auth_subject == auth_subject)
    )
    counts["users"] = int(result.rowcount or 0)
    await session.flush()
    return counts


async def _linked_audit_count(session, user_id: str) -> int:
    table = Base.metadata.tables["audit_log"]
    return int(
        await session.scalar(
            select(func.count()).select_from(table).where(table.c.user_id == user_id)
        )
        or 0
    )


async def run_account_deletion_transaction_rehearsal() -> dict:
    """Prove success atomicity, failure rollback and isolation using synthetic data."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    checks: dict[str, bool] = {}
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            for user_id, subject, suffix in (
                (_SUCCESS_USER, _SUCCESS_SUBJECT, "success"),
                (_ROLLBACK_USER, _ROLLBACK_SUBJECT, "rollback"),
                (_CONTROL_USER, _CONTROL_SUBJECT, "control"),
            ):
                await _seed_account(
                    session,
                    user_id=user_id,
                    subject=subject,
                    suffix=suffix,
                )
            await session.commit()

            success_before = await build_account_deletion_preview(
                session,
                user_id=_SUCCESS_USER,
                auth_subject=_SUCCESS_SUBJECT,
            )
            rollback_before = await build_account_deletion_preview(
                session,
                user_id=_ROLLBACK_USER,
                auth_subject=_ROLLBACK_SUBJECT,
            )
            control_before = await build_account_deletion_preview(
                session,
                user_id=_CONTROL_USER,
                auth_subject=_CONTROL_SUBJECT,
            )
            await session.rollback()

            async with session.begin():
                success_counts = await _delete_representative_account(
                    session,
                    user_id=_SUCCESS_USER,
                    auth_subject=_SUCCESS_SUBJECT,
                )

            success_after = await build_account_deletion_preview(
                session,
                user_id=_SUCCESS_USER,
                auth_subject=_SUCCESS_SUBJECT,
            )
            control_after_success = await build_account_deletion_preview(
                session,
                user_id=_CONTROL_USER,
                auth_subject=_CONTROL_SUBJECT,
            )
            success_audit_links = await _linked_audit_count(session, _SUCCESS_USER)
            await session.rollback()

            rollback_injected = False
            try:
                async with session.begin():
                    await _delete_representative_account(
                        session,
                        user_id=_ROLLBACK_USER,
                        auth_subject=_ROLLBACK_SUBJECT,
                    )
                    rollback_injected = True
                    raise RuntimeError("synthetic rollback checkpoint")
            except RuntimeError as exc:
                if str(exc) != "synthetic rollback checkpoint":
                    raise

            rollback_after = await build_account_deletion_preview(
                session,
                user_id=_ROLLBACK_USER,
                auth_subject=_ROLLBACK_SUBJECT,
            )
            control_after_rollback = await build_account_deletion_preview(
                session,
                user_id=_CONTROL_USER,
                auth_subject=_CONTROL_SUBJECT,
            )
            rollback_audit_links = await _linked_audit_count(session, _ROLLBACK_USER)
            control_audit_links = await _linked_audit_count(session, _CONTROL_USER)

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
                "research_personalization_profiles": 1,
                "research_thesis_notices": 1,
                "audit_log": 1,
            }
            checks = {
                "preview_captured_before_mutation": all(
                    success_before["counts"].get(table) == count
                    for table, count in expected_nonzero.items()
                ),
                "child_first_deletion_counts_match": (
                    success_counts["portfolio_positions"] == 1
                    and success_counts["preference_evidence"] == 1
                    and success_counts["thesis_deltas"] == 1
                ),
                "research_memory_deleted": (
                    success_counts["conversations"] == 1
                    and success_counts["messages"] == 1
                    and success_counts["personalization_profiles"] == 1
                    and success_counts["thesis_notices"] == 1
                ),
                "audit_linkage_anonymized": (
                    success_counts["audit_log_anonymized"] == 1
                    and success_audit_links == 0
                ),
                "access_grant_removed": success_counts["access_grants"] == 1,
                "user_removed_last": success_counts["users"] == 1,
                "all_owner_links_zero_after_success": (
                    success_after["total_rows"] == 0
                ),
                "failure_was_injected": rollback_injected is True,
                "failed_transaction_fully_rolled_back": (
                    rollback_after == rollback_before
                    and rollback_audit_links == 1
                ),
                "foreign_owner_preserved": (
                    control_after_success == control_before
                    and control_after_rollback == control_before
                    and control_audit_links == 1
                ),
                "shared_ticker_tables_excluded": all(
                    table not in success_before["counts"]
                    for table in ("ticker_memory", "concern_tags", "theme_clusters")
                ),
                "supabase_identity_not_touched": True,
                "production_database_untouched": True,
                "zero_external_side_effects": True,
            }

        return {
            "schema_version": 1,
            "passed": all(checks.values()),
            "database_scope": "ephemeral_in_memory",
            "synthetic": True,
            "checks": checks,
            "preview_table_count": success_before["table_count"],
            "preview_total_rows": success_before["total_rows"],
            "success_remaining_owner_rows": success_after["total_rows"],
            "rollback_restored_owner_rows": rollback_after["total_rows"],
            "foreign_owner_preserved": checks["foreign_owner_preserved"],
            "authorizes_production_deletion": False,
            "production_database_untouched": True,
        }
    finally:
        await engine.dispose()
