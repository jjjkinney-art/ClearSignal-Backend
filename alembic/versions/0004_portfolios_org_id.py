"""portfolios: add organization compatibility column

Revision ID: 0004_portfolios_org_id
Revises: 0003_users_billing_columns
Create Date: 2026-08-26

Production's ``portfolios`` table predates the Phase 16 ``org_id`` field.
Because the original baseline uses ``create_all(checkfirst=True)``, it cannot
alter that existing table.  Selecting the current Portfolio ORM model during
account import therefore raised ``UndefinedColumnError``.

This migration is additive and idempotent.  Existing portfolio rows and their
relationships are preserved; the new compatibility field defaults to NULL.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_portfolios_org_id"
down_revision = "0003_users_billing_columns"
branch_labels = None
depends_on = None

_TABLE = "portfolios"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return

    existing = {column["name"] for column in insp.get_columns(_TABLE)}
    if "org_id" not in existing:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(
                sa.Column("org_id", sa.String(length=36), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return

    existing = {column["name"] for column in insp.get_columns(_TABLE)}
    if "org_id" in existing:
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column("org_id")
