"""bounded thesis notice evidence provenance

Revision ID: 0012_notice_evidence_snapshot
Revises: 0011_research_notice_inbox
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_notice_evidence_snapshot"
down_revision = "0011_research_notice_inbox"
branch_labels = None
depends_on = None

TABLE = "research_thesis_notices"
COLUMN = "evidence_snapshot"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names()):
        return
    if COLUMN in {item["name"] for item in inspector.get_columns(TABLE)}:
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(sa.Column(
            COLUMN, sa.JSON(), nullable=False, server_default=sa.text("'{}'"),
        ))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names()):
        return
    if COLUMN not in {item["name"] for item in inspector.get_columns(TABLE)}:
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column(COLUMN)
