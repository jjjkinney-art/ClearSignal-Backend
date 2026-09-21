"""access_grants: controlled-beta admission grants

Revision ID: 0006_access_grants
Revises: 0005_watchlist_unique_active
Create Date: 2026-09-21

Section 0.15. Creates the table that records operator approvals for the
controlled beta. It does NOT enable the gate (that is a configuration step),
does NOT create any grant, and does NOT touch users, watchlists or portfolios.

Privacy by construction
-----------------------
The table stores no email address, name or user id. A pre-authentication
grant carries only ``email_locator`` — an HMAC-SHA256 digest of the
normalised address — which is a one-time admission lookup key. Once redeemed
the row is bound to the Supabase ``subject`` and the locator is never used
for identity resolution again.

``subject`` is UNIQUE, so one identity holds at most one grant and a second
grant can never be redeemed by an already-admitted subject.

Upgrade is a pure CREATE TABLE; downgrade is a pure DROP TABLE. Because the
table is empty on creation and holds only operator approvals, the downgrade
loses nothing except those approvals, and no user row is affected either way.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0006_access_grants"
down_revision = "0005_watchlist_unique_active"
branch_labels = None
depends_on = None

TABLE = "access_grants"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE in inspector.get_table_names():
        # Idempotent: a re-run over an existing table is a no-op rather than
        # an error, and an operator-created table is never replaced.
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="invite"),
        sa.Column("email_locator", sa.String(64), nullable=True),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="approved"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note_ref", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        # One identity, at most one grant. This is the replay guard that does
        # not depend on application code being correct.
        #
        # Declared INSIDE create_table deliberately: SQLite cannot ALTER a
        # table to add a constraint, so op.create_unique_constraint() fails
        # there outright. Inline works on both dialects, and the test suite
        # exercises the migration on SQLite.
        sa.UniqueConstraint("subject", name="uq_access_grants_subject"),
    )
    op.create_index("ix_access_grants_email_locator", TABLE, ["email_locator"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    op.drop_table(TABLE)
