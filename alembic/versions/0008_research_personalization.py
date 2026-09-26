"""explicit account-owned Intelligence Mode profile

Revision ID: 0008_research_personalization
Revises: 0007_research_conversations
Create Date: 2026-09-27

Stores only user-selected structured preferences. No transcript inference,
legacy backfill, or automatic prompt injection is enabled by this migration.
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_research_personalization"
down_revision = "0007_research_conversations"
branch_labels = None
depends_on = None

TABLE = "research_personalization_profiles"


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if TABLE in existing:
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("response_depth", sa.String(20), nullable=False,
                  server_default="balanced"),
        sa.Column("time_horizon", sa.String(20), nullable=False,
                  server_default="mixed"),
        sa.Column("analysis_emphasis", sa.String(20), nullable=False,
                  server_default="balanced"),
        sa.Column("evidence_style", sa.String(30), nullable=False,
                  server_default="primary_sources"),
        sa.Column("origin", sa.String(30), nullable=False,
                  server_default="explicit_user_setting"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_research_personalization_owner", TABLE, ["user_id"])


def downgrade() -> None:
    if TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(TABLE)
