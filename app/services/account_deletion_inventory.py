"""Read-only inventory for verified account-deletion previews.

This service returns aggregate row counts only. It performs no mutation and is
not exposed as a live-account HTTP endpoint. Identity verification, retention
policy, approval, and deletion remain governed by the operator runbook.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select

from app.db.models import Base


IDENTITY_SCOPES = {
    "users": "auth_subject",
    "access_grants": "subject",
}

CHILD_SCOPES = {
    "portfolio_positions": "portfolios",
    "portfolio_insights": "portfolios",
    "preference_evidence": "learned_preference",
    "thesis_deltas": "thesis_versions",
}

SHARED_OR_OPERATIONAL_TABLES = {
    "ticker_memory",
    "concern_tags",
    "theme_clusters",
    "cross_exposures",
    "briefing_sessions",
    "historical_analogs",
    "scheduled_jobs",
    "job_locks",
    "job_runs",
    "delivery_ledger",
    "stripe_events",
    "benchmark_shadow_jobs",
    "benchmark_shadow_transitions",
    "benchmark_shadow_control",
    "benchmark_shadow_cancellations",
}


def _required(value: str, label: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


async def _scalar_count(session, statement) -> int:
    return int(await session.scalar(statement) or 0)


async def build_account_deletion_preview(
    session,
    *,
    user_id: str,
    auth_subject: str,
) -> dict:
    """Return counts for all known account-owned and child-scoped tables."""

    owner = _required(user_id, "Verified user id")
    subject = _required(auth_subject, "Verified authentication subject")
    tables = Base.metadata.tables
    counts: dict[str, int] = {}
    scope_kinds: dict[str, str] = {}

    for table_name, table in sorted(tables.items()):
        if "user_id" not in table.c:
            continue
        counts[table_name] = await _scalar_count(
            session,
            select(func.count()).select_from(table).where(table.c.user_id == owner),
        )
        scope_kinds[table_name] = "direct_user_id"

    for table_name, column_name in IDENTITY_SCOPES.items():
        table = tables[table_name]
        counts[table_name] = await _scalar_count(
            session,
            select(func.count()).select_from(table).where(
                table.c[column_name] == subject
            ),
        )
        scope_kinds[table_name] = f"identity_{column_name}"

    portfolios = tables["portfolios"]
    for table_name in ("portfolio_positions", "portfolio_insights"):
        table = tables[table_name]
        counts[table_name] = await _scalar_count(
            session,
            select(func.count())
            .select_from(table.join(portfolios, table.c.portfolio_id == portfolios.c.id))
            .where(portfolios.c.user_id == owner),
        )
        scope_kinds[table_name] = "child_of_owned_portfolio"

    preferences = tables["learned_preference"]
    preference_evidence = tables["preference_evidence"]
    counts["preference_evidence"] = await _scalar_count(
        session,
        select(func.count())
        .select_from(
            preference_evidence.join(
                preferences,
                preference_evidence.c.preference_id == preferences.c.id,
            )
        )
        .where(preferences.c.user_id == owner),
    )
    scope_kinds["preference_evidence"] = "child_of_owned_preference"

    versions = tables["thesis_versions"]
    deltas = tables["thesis_deltas"]
    owned_version_ids = select(versions.c.id).where(versions.c.user_id == owner)
    counts["thesis_deltas"] = await _scalar_count(
        session,
        select(func.count()).select_from(deltas).where(
            or_(
                deltas.c.from_version_id.in_(owned_version_ids),
                deltas.c.to_version_id.in_(owned_version_ids),
            )
        ),
    )
    scope_kinds["thesis_deltas"] = "child_of_owned_thesis_version"

    ordered_counts = dict(sorted(counts.items()))
    return {
        "schema_version": 1,
        "read_only": True,
        "aggregate_counts_only": True,
        "table_count": len(ordered_counts),
        "total_rows": sum(ordered_counts.values()),
        "counts": ordered_counts,
        "scope_kinds": dict(sorted(scope_kinds.items())),
        "child_scopes": dict(sorted(CHILD_SCOPES.items())),
        "shared_or_operational_tables_excluded": sorted(
            SHARED_OR_OPERATIONAL_TABLES
        ),
    }
