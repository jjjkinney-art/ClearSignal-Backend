"""baseline: adopt the full current schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-13

Baseline for adopting Alembic on top of the pre-existing ``create_all()`` schema.

This revision materialises the ENTIRE current model schema
(``app.db.models.Base.metadata``) via ``create_all(checkfirst=True)``, which is
idempotent:
  * on a NEW empty database it creates every table, and
  * on an EXISTING database (previously created by the old startup
    ``create_all`` path) it is a no-op — ``checkfirst`` skips tables that
    already exist.

So this migration is safe to *run* against a fresh DB and safe to *stamp*
against an existing one.

Downgrade is DESTRUCTIVE: it drops every application table (``drop_all``) and
therefore all data.  It exists only to make the revision formally reversible for
disposable/test databases — never run it against a database with real data.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Import inside the function so the module imports cheaply and always tracks
    # the live model metadata.
    from app.db.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    # DESTRUCTIVE — drops all application tables. Irreversible data loss.
    from app.db.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
