"""watched_tickers: enforce active membership uniqueness

Revision ID: 0005_watchlist_unique_active
Revises: 0004_portfolios_org_id
Create Date: 2026-09-03

Closes the concurrent-insert race that Sections 0.8-0.8D contained but could
not eliminate. ``ticker_add`` is a check-then-insert; only a database
constraint makes it atomic.

Two PARTIAL unique indexes, because the two ownership namespaces are
different things:

    uq_watched_tickers_owner_ticker_active
        (user_id, ticker) WHERE active IS TRUE AND user_id IS NOT NULL

    uq_watched_tickers_legacy_ticker_active
        (ticker)          WHERE active IS TRUE AND user_id IS NULL

Design notes
------------
* Partial on ``active`` so soft-deleted history is untouched: one active row
  plus any number of inactive rows for the same key stays legal.
* The owned key leads with ``user_id``, so the SAME TICKER UNDER DIFFERENT
  OWNERS REMAINS VALID. That distinction is the whole point -- treating it as
  duplication was the original false positive.
* NO ``COALESCE(user_id, '')``. ``user_id`` is VARCHAR(64), so ``''`` is a
  representable, distinct owner value; collapsing it with NULL would conflate
  two namespaces.
* NO ``NULLS NOT DISTINCT``. It would allow a single index, but requires
  PostgreSQL 15+ and the deployed version is unconfirmed. Two partial indexes
  work on 9.6+.
* NOT a conventional UniqueConstraint: SQLAlchemy/Alembic emit those as table
  constraints, which cannot carry a WHERE predicate.

Safety
------
PostgreSQL only. Other dialects (the SQLite test path) are a deliberate no-op:
CONCURRENTLY and the pg_index catalogs do not exist there.

Fails closed BEFORE any DDL if duplicates still exist, or if an index with
either target name already exists in an unexpected or invalid state. An
unexpected index is never silently dropped or replaced.

After creation, both indexes are verified through the PostgreSQL catalogs --
existence, uniqueness, indisvalid, indisready, table, columns and predicate.
CREATE INDEX CONCURRENTLY can leave an INVALID index behind on failure; that
must fail the migration loudly rather than pass as success.

Rollback ordering
-----------------
Rolling back the Section 0.8D cleanup AFTER this migration requires:

    drop indexes -> restore rows -> rerun cleanup -> recreate and revalidate

because reactivating the deactivated rows recreates the duplicates by design
and would violate ``uq_watched_tickers_owner_ticker_active``.

This migration does not alter, delete or reactivate any watchlist row.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0005_watchlist_unique_active"
down_revision = "0004_portfolios_org_id"
branch_labels = None
depends_on = None

TABLE = "watched_tickers"

INDEX_OWNED = "uq_watched_tickers_owner_ticker_active"
INDEX_LEGACY = "uq_watched_tickers_legacy_ticker_active"

CREATE_OWNED = (
    "CREATE UNIQUE INDEX CONCURRENTLY %s "
    "ON watched_tickers (user_id, ticker) "
    "WHERE active IS TRUE AND user_id IS NOT NULL" % INDEX_OWNED
)
CREATE_LEGACY = (
    "CREATE UNIQUE INDEX CONCURRENTLY %s "
    "ON watched_tickers (ticker) "
    "WHERE active IS TRUE AND user_id IS NULL" % INDEX_LEGACY
)
DROP_OWNED = "DROP INDEX CONCURRENTLY IF EXISTS %s" % INDEX_OWNED
DROP_LEGACY = "DROP INDEX CONCURRENTLY IF EXISTS %s" % INDEX_LEGACY

# index name -> (expected columns, required owner-predicate fragment)
#
# The owner fragment must be matched EXACTLY, not by substring on "null":
# "user_id is not null" contains "user_id is null" as a substring only in the
# loose sense, and a naive check cannot tell the two predicates apart. Getting
# this wrong would let the legacy index be validated against the OWNED
# predicate -- an index that constrains the wrong namespace while reporting
# success.
EXPECTED = {
    INDEX_OWNED: (["user_id", "ticker"], "user_id is not null"),
    INDEX_LEGACY: (["ticker"], "user_id is null"),
}

COUNT_OWNED_DUPLICATES = """
SELECT COUNT(*) FROM (
    SELECT 1 FROM watched_tickers
    WHERE active IS TRUE AND user_id IS NOT NULL
    GROUP BY user_id, ticker HAVING COUNT(*) > 1
) t
"""

COUNT_LEGACY_DUPLICATES = """
SELECT COUNT(*) FROM (
    SELECT 1 FROM watched_tickers
    WHERE active IS TRUE AND user_id IS NULL
    GROUP BY ticker HAVING COUNT(*) > 1
) t
"""

INDEX_CATALOG = """
SELECT c.relname                                AS index_name,
       t.relname                                AS table_name,
       i.indisunique                            AS is_unique,
       i.indisvalid                             AS is_valid,
       i.indisready                             AS is_ready,
       pg_get_expr(i.indpred, i.indrelid)       AS predicate,
       pg_get_indexdef(i.indexrelid)            AS indexdef
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
JOIN pg_class t ON t.oid = i.indrelid
WHERE c.relname = :name
"""


class MigrationPreflightError(RuntimeError):
    """A precondition failed. No DDL was issued."""


class IndexValidationError(RuntimeError):
    """An index was created but does not match its intended definition."""


def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def inspect_index(bind, name):
    """Return the catalog row for `name`, or None. PostgreSQL only."""
    row = bind.execute(sa.text(INDEX_CATALOG), {"name": name}).mappings().first()
    return dict(row) if row else None


def duplicate_preflight(bind) -> None:
    """Refuse to create the indexes while duplicates still exist.

    CREATE UNIQUE INDEX CONCURRENTLY would fail anyway, but it would fail
    *after* doing work and would leave an INVALID index behind. Checking first
    turns that into a clean, early refusal with an actionable count.
    """
    owned = bind.execute(sa.text(COUNT_OWNED_DUPLICATES)).scalar() or 0
    legacy = bind.execute(sa.text(COUNT_LEGACY_DUPLICATES)).scalar() or 0
    if owned or legacy:
        raise MigrationPreflightError(
            "watched_tickers still contains duplicate active memberships "
            "(owned groups=%d, legacy groups=%d). Run the Section 0.8D "
            "cleanup first; this migration will not create a unique index "
            "over duplicated data." % (owned, legacy)
        )


def existing_index_preflight(bind) -> None:
    """Refuse when a target name is already taken by an unexpected index.

    A pre-existing index that already matches the intended definition and is
    valid is fine -- the migration is then a no-op for that name. Anything
    else (invalid, not ready, non-unique, wrong table) is a refusal. An
    unexpected index is NEVER silently dropped or replaced: that would destroy
    something a human created deliberately.
    """
    for name in (INDEX_OWNED, INDEX_LEGACY):
        found = inspect_index(bind, name)
        if found is None:
            continue
        if not found["is_valid"] or not found["is_ready"]:
            raise MigrationPreflightError(
                "index %s already exists but is invalid or not ready "
                "(indisvalid=%s, indisready=%s). A previous CONCURRENTLY "
                "attempt probably failed. Drop it deliberately, then rerun; "
                "this migration will not replace it automatically."
                % (name, found["is_valid"], found["is_ready"])
            )
        if not found["is_unique"] or found["table_name"] != TABLE:
            raise MigrationPreflightError(
                "index %s already exists but is not the expected unique index "
                "on %s (unique=%s, table=%s). Refusing to replace it."
                % (name, TABLE, found["is_unique"], found["table_name"])
            )


def validate_index(bind, name) -> None:
    """Verify the created index through the catalogs. Raises on any mismatch."""
    found = inspect_index(bind, name)
    if found is None:
        raise IndexValidationError("index %s does not exist after creation" % name)
    if not found["is_unique"]:
        raise IndexValidationError("index %s is not UNIQUE" % name)
    if not found["is_valid"]:
        raise IndexValidationError(
            "index %s has indisvalid=false; a concurrent build failed and it "
            "enforces nothing" % name)
    if not found["is_ready"]:
        raise IndexValidationError("index %s has indisready=false" % name)
    if found["table_name"] != TABLE:
        raise IndexValidationError(
            "index %s targets %s, expected %s"
            % (name, found["table_name"], TABLE))

    columns, owner_fragment = EXPECTED[name]
    definition = (found["indexdef"] or "").lower()
    for column in columns:
        if column not in definition:
            raise IndexValidationError(
                "index %s definition is missing column %s" % (name, column))

    predicate = " ".join((found["predicate"] or "").lower().split())
    predicate = predicate.replace("(", " ").replace(")", " ")
    predicate = " ".join(predicate.split())
    if not predicate:
        raise IndexValidationError(
            "index %s has no partial predicate; it would wrongly constrain "
            "inactive history" % name)
    if "active" not in predicate:
        raise IndexValidationError(
            "index %s predicate is missing active: %r" % (name, predicate))

    # Distinguish "user_id is null" from "user_id is not null" exactly.
    has_not_null = "user_id is not null" in predicate
    has_null = ("user_id is null" in predicate) and not has_not_null
    if owner_fragment == "user_id is not null" and not has_not_null:
        raise IndexValidationError(
            "index %s must scope to NON-NULL owners: %r" % (name, predicate))
    if owner_fragment == "user_id is null" and not has_null:
        raise IndexValidationError(
            "index %s must scope to NULL owners: %r" % (name, predicate))


def upgrade() -> None:
    bind = op.get_bind()
    if not _is_postgres(bind):
        # SQLite/other: CONCURRENTLY and pg_index do not exist. The uniqueness
        # semantics are covered by tests that build the equivalent partial
        # indexes directly; production is PostgreSQL.
        return

    duplicate_preflight(bind)
    existing_index_preflight(bind)

    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        if inspect_index(bind, INDEX_OWNED) is None:
            op.execute(sa.text(CREATE_OWNED))
        if inspect_index(bind, INDEX_LEGACY) is None:
            op.execute(sa.text(CREATE_LEGACY))

    # A concurrent build can leave an INVALID index behind rather than raising.
    validate_index(bind, INDEX_OWNED)
    validate_index(bind, INDEX_LEGACY)


def downgrade() -> None:
    bind = op.get_bind()
    if not _is_postgres(bind):
        return

    # DROP INDEX CONCURRENTLY also cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute(sa.text(DROP_OWNED))
        op.execute(sa.text(DROP_LEGACY))
