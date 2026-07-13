"""delivery_ledger: severity columns + index (replaces the Phase 10C lifespan ALTER)

Revision ID: 0002_delivery_ledger_severity
Revises: 0001_baseline
Create Date: 2026-07-13

Versioned, reversible replacement for the idempotent ``ALTER TABLE`` block that
used to run in the app lifespan (Phase 10C).  Adds two nullable columns and an
index to ``delivery_ledger``:

    canonical_severity  VARCHAR(20)  NULL
    severity_rank       INTEGER      NULL
    index ix_delivery_ledger_canonical_severity (canonical_severity)

Idempotent: introspects the table first and only adds what is missing, so it is:
  * a NO-OP on a fresh DB (0001 already created these via the current models), and
  * the real DELTA on a legacy pre-10C DB that lacks the columns.

Data-safe: only ADD COLUMN (nullable) + CREATE INDEX — no rows touched.

Downgrade drops the index and the two columns.  Reversible for schema, but it
DISCARDS any values stored in canonical_severity / severity_rank (severity
classification).  No rows are lost.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_delivery_ledger_severity"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_TABLE = "delivery_ledger"
_INDEX = "ix_delivery_ledger_canonical_severity"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return  # nothing to migrate (persistence-less / partial DB)

    existing_cols = {c["name"] for c in insp.get_columns(_TABLE)}
    to_add = []
    if "canonical_severity" not in existing_cols:
        to_add.append(sa.Column("canonical_severity", sa.String(length=20), nullable=True))
    if "severity_rank" not in existing_cols:
        to_add.append(sa.Column("severity_rank", sa.Integer(), nullable=True))

    # Only enter a batch (which rebuilds the table on SQLite) when there is work.
    if to_add:
        with op.batch_alter_table(_TABLE) as batch:
            for col in to_add:
                batch.add_column(col)

    existing_idx = {i["name"] for i in sa.inspect(bind).get_indexes(_TABLE)}
    if _INDEX not in existing_idx:
        op.create_index(_INDEX, _TABLE, ["canonical_severity"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return

    existing_idx = {i["name"] for i in insp.get_indexes(_TABLE)}
    if _INDEX in existing_idx:
        op.drop_index(_INDEX, table_name=_TABLE)

    existing_cols = {c["name"] for c in insp.get_columns(_TABLE)}
    drops = [c for c in ("severity_rank", "canonical_severity") if c in existing_cols]
    if drops:
        with op.batch_alter_table(_TABLE) as batch:
            for col in drops:
                batch.drop_column(col)
