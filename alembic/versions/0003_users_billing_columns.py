"""users: add billing-plan columns required by auth provisioning

Revision ID: 0003_users_billing_columns
Revises: 0002_delivery_ledger_severity
Create Date: 2026-08-26

Production was originally created through ``create_all()`` before the Phase 17
``users.plan`` and ``users.plan_updated_at`` fields existed.  ``create_all``
does not alter an existing table, so authenticated first-login provisioning
failed while SQLAlchemy selected the current User model.

This migration is additive and idempotent.  It adds only missing columns,
preserves every row, defaults existing accounts to ``free``, and restores the
well-known system account's ``system`` plan.

Downgrade drops the two columns and therefore discards their values, but does
not delete any user rows.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_users_billing_columns"
down_revision = "0002_delivery_ledger_severity"
branch_labels = None
depends_on = None

_TABLE = "users"
_SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return

    existing = {column["name"] for column in insp.get_columns(_TABLE)}
    additions = []
    if "plan" not in existing:
        additions.append(
            sa.Column(
                "plan",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'free'"),
            )
        )
    if "plan_updated_at" not in existing:
        additions.append(
            sa.Column("plan_updated_at", sa.DateTime(timezone=True), nullable=True)
        )

    if additions:
        with op.batch_alter_table(_TABLE) as batch:
            for column in additions:
                batch.add_column(column)

    bind.execute(
        sa.text("UPDATE users SET plan = 'system' WHERE id = :system_user_id"),
        {"system_user_id": _SYSTEM_USER_ID},
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return

    existing = {column["name"] for column in insp.get_columns(_TABLE)}
    removals = [name for name in ("plan_updated_at", "plan") if name in existing]
    if removals:
        with op.batch_alter_table(_TABLE) as batch:
            for name in removals:
                batch.drop_column(name)
