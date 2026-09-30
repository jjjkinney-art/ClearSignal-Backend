"""durable Intelligence Benchmark shadow state

Revision ID: 0009_benchmark_shadow_state
Revises: 0008_research_personalization
Create Date: 2026-09-30

Stores operational metadata for synthetic benchmark jobs only. No prompt,
answer, evidence content, account-owned research, or delivery payload is stored.
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_benchmark_shadow_state"
down_revision = "0008_research_personalization"
branch_labels = None
depends_on = None

JOBS = "benchmark_shadow_jobs"
TRANSITIONS = "benchmark_shadow_transitions"
CONTROL = "benchmark_shadow_control"


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if JOBS not in existing:
        op.create_table(
            JOBS,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("request_id", sa.String(128), nullable=False, unique=True),
            sa.Column("request_fingerprint", sa.String(64), nullable=False),
            sa.Column("account_ref", sa.String(200), nullable=False),
            sa.Column("issuer_id", sa.String(80), nullable=False),
            sa.Column("capability", sa.String(80), nullable=False),
            sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
            sa.Column("actual_cost_usd", sa.Float(), nullable=True),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("holder_id", sa.String(200), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("fence_token", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("failure_code", sa.String(100), nullable=True),
            sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.CheckConstraint("account_ref LIKE 'synthetic:%'",
                               name="ck_benchmark_shadow_synthetic_owner"),
            sa.CheckConstraint("estimated_cost_usd >= 0",
                               name="ck_benchmark_shadow_estimated_cost"),
            sa.CheckConstraint("actual_cost_usd IS NULL OR actual_cost_usd >= 0",
                               name="ck_benchmark_shadow_actual_cost"),
            sa.CheckConstraint(
                "status IN ('reserved','running','succeeded','failed','timed_out','cancelled')",
                name="ck_benchmark_shadow_status",
            ),
        )
        op.create_index("ix_benchmark_shadow_jobs_status_lease", JOBS,
                        ["status", "lease_expires_at"])
        op.create_index("ix_benchmark_shadow_jobs_account_reserved", JOBS,
                        ["account_ref", "reserved_at"])
        op.create_index("ix_benchmark_shadow_jobs_retention", JOBS,
                        ["retention_until"])
    if TRANSITIONS not in existing:
        op.create_table(
            TRANSITIONS,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("job_id", sa.String(36), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("from_status", sa.String(30), nullable=True),
            sa.Column("to_status", sa.String(30), nullable=False),
            sa.Column("actor_id", sa.String(200), nullable=False),
            sa.Column("reason_code", sa.String(100), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("fence_token", sa.Integer(), nullable=False),
            sa.Column("cost_usd", sa.Float(), nullable=True),
            sa.Column("previous_event_hash", sa.String(64), nullable=True),
            sa.Column("event_hash", sa.String(64), nullable=False, unique=True),
            sa.CheckConstraint(
                "to_status IN ('reserved','running','succeeded','failed','timed_out','cancelled')",
                name="ck_benchmark_shadow_transition_status",
            ),
            sa.UniqueConstraint("job_id", "sequence",
                                name="uq_benchmark_shadow_transition_sequence"),
        )
        op.create_index("ix_benchmark_shadow_transition_job", TRANSITIONS,
                        ["job_id", "sequence"])
        op.create_index("ix_benchmark_shadow_transition_time", TRANSITIONS,
                        ["occurred_at"])
    if CONTROL not in existing:
        op.create_table(
            CONTROL,
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("manual_kill", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
            sa.Column("automatic_kill", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
            sa.Column("reason_code", sa.String(100), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_by", sa.String(200), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (TRANSITIONS, JOBS, CONTROL):
        if table in existing:
            op.drop_table(table)
