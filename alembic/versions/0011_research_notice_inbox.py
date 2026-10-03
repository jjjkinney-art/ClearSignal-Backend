"""account-owned thesis notice inbox

Revision ID: 0011_research_notice_inbox
Revises: 0010_benchmark_cancellation
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_research_notice_inbox"
down_revision = "0010_benchmark_cancellation"
branch_labels = None
depends_on = None

TABLE = "research_thesis_notices"


def upgrade() -> None:
    if TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("message_id", sa.String(36), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("evidence_id", sa.String(200), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("matched_terms", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="unread"),
        sa.Column("candidate_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("preview_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("delivery_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "fingerprint",
                            name="uq_research_notice_owner_fingerprint"),
        sa.CheckConstraint("status IN ('unread','read','dismissed')",
                           name="ck_research_notice_status"),
    )
    op.create_index("ix_research_notice_owner_detected", TABLE,
                    ["user_id", "detected_at"])
    op.create_index("ix_research_notice_owner_status", TABLE,
                    ["user_id", "status"])
    op.create_index("ix_research_notice_owner_ticker", TABLE,
                    ["user_id", "ticker"])


def downgrade() -> None:
    if TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(TABLE)
