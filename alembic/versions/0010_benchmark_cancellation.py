"""content-free provider cancellation acknowledgements

Revision ID: 0010_benchmark_cancellation
Revises: 0009_benchmark_shadow_state
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_benchmark_cancellation"
down_revision = "0009_benchmark_shadow_state"
branch_labels = None
depends_on = None

TABLE = "benchmark_shadow_cancellations"


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if TABLE in existing:
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("fence_token", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(80), nullable=False),
        sa.Column("operation_ref_hash", sa.String(64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("reason_code", sa.String(100), nullable=False),
        sa.Column("attempted_by", sa.String(200), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("call_token", sa.String(36), nullable=True),
        sa.Column("call_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('pending','calling','acknowledged','rejected','timed_out','error')",
            name="ck_benchmark_shadow_cancellation_outcome",
        ),
        sa.UniqueConstraint(
            "job_id", "fence_token", "attempt_number",
            name="uq_benchmark_shadow_cancellation_attempt",
        ),
    )
    op.create_index("ix_benchmark_shadow_cancellation_job", TABLE,
                    ["job_id", "requested_at"])
    op.create_index("ix_benchmark_shadow_cancellation_outcome", TABLE,
                    ["outcome", "requested_at"])


def downgrade() -> None:
    if TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(TABLE)
