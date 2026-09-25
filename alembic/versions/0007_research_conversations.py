"""account-owned research conversations and messages

Revision ID: 0007_research_conversations
Revises: 0006_access_grants
Create Date: 2026-09-25

Additive, dark infrastructure for cross-conversation memory. No endpoint or
recall behavior is enabled by this migration. Ownership is mandatory on both
tables and every retrieval path must filter by it before ranking.
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_research_conversations"
down_revision = "0006_access_grants"
branch_labels = None
depends_on = None

CONVERSATIONS = "research_conversations"
MESSAGES = "research_messages"


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if CONVERSATIONS not in existing:
        op.create_table(
            CONVERSATIONS,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(255), nullable=False),
            sa.Column("title", sa.String(200), nullable=False, server_default=""),
            sa.Column("scope_tickers", sa.JSON(), nullable=False),
            sa.Column("scope_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scope_ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scope_portfolio_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_research_conversations_owner_updated", CONVERSATIONS,
                        ["user_id", "updated_at"])
        op.create_index("ix_research_conversations_owner_deleted", CONVERSATIONS,
                        ["user_id", "deleted_at"])

    if MESSAGES not in existing:
        op.create_table(
            MESSAGES,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("conversation_id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(255), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("text", sa.Text(), nullable=False, server_default=""),
            sa.Column("request_ref", sa.String(100), nullable=True),
            sa.Column("snapshot_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("displayed_snapshot", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("conversation_id", "ordinal",
                                name="uq_research_messages_conversation_ordinal"),
            sa.UniqueConstraint("conversation_id", "request_ref", "role",
                                name="uq_research_messages_request_role"),
        )
        op.create_index("ix_research_messages_owner_created", MESSAGES,
                        ["user_id", "created_at"])
        op.create_index("ix_research_messages_conversation", MESSAGES,
                        ["conversation_id", "ordinal"])


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if MESSAGES in existing:
        op.drop_table(MESSAGES)
    if CONVERSATIONS in existing:
        op.drop_table(CONVERSATIONS)
