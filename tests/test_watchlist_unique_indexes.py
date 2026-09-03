"""Section 0.8E — the watched_tickers active-uniqueness migration.

Two kinds of evidence, kept clearly apart:

  * SEMANTICS — the partial unique indexes are built directly in SQLite, which
    supports partial unique indexes, and the uniqueness rules are exercised
    against real DDL. What is proven here is the RULE, not the migration.

  * MIGRATION MECHANICS — names, exact SQL, CONCURRENTLY, autocommit_block,
    preflight refusals and catalog validation are asserted against the
    migration module with a stubbed PostgreSQL bind, because CONCURRENTLY and
    pg_index do not exist outside PostgreSQL.

No disposable PostgreSQL instance was available, so the concurrent DDL itself
has NOT been executed against a real server. See the module docstring note in
the migration and the report accompanying this branch.

Python 3.9 compatible.
"""
from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

_MIG_PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / \
    "0005_watchlist_unique_active_membership.py"


def _migration():
    spec = importlib.util.spec_from_file_location("_wl_unique_mig", _MIG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _migration()

OWNER_1 = "11111111-1111-1111-1111-111111111111"
OWNER_2 = "22222222-2222-2222-2222-222222222222"

# The SQLite equivalents of the two production predicates. Same columns, same
# predicates; only CONCURRENTLY (a PostgreSQL online-build option, not part of
# the constraint semantics) is omitted, because SQLite has no such option.
SQLITE_OWNED = (
    "CREATE UNIQUE INDEX %s ON watched_tickers (user_id, ticker) "
    "WHERE active IS TRUE AND user_id IS NOT NULL" % M.INDEX_OWNED
)
SQLITE_LEGACY = (
    "CREATE UNIQUE INDEX %s ON watched_tickers (ticker) "
    "WHERE active IS TRUE AND user_id IS NULL" % M.INDEX_LEGACY
)


@pytest.fixture()
def db(tmp_path):
    """A real SQLite database with the production table and both indexes."""
    from app.db.models import Base

    engine = sa.create_engine("sqlite:///%s" % (tmp_path / "u.sqlite"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql(SQLITE_OWNED)
        conn.exec_driver_sql(SQLITE_LEGACY)
    yield engine
    engine.dispose()


def _insert(conn, owner, ticker, active=True):
    conn.execute(sa.text(
        "INSERT INTO watched_tickers "
        "(id, user_id, ticker, company_name, active, added_at, updated_at) "
        "VALUES (:i, :u, :t, :c, :a, :d, :d)"),
        {"i": uuid.uuid4().hex, "u": owner, "t": ticker, "c": ticker,
         "a": active, "d": "2026-01-01 00:00:00"})


# ===========================================================================
# § UNIQUENESS SEMANTICS (real DDL, real inserts)
# ===========================================================================

def test_owned_uniqueness_is_scoped_by_owner(db):
    with db.begin() as conn:
        _insert(conn, OWNER_1, "AAA")
    with pytest.raises(sa.exc.IntegrityError):
        with db.begin() as conn:
            _insert(conn, OWNER_1, "AAA")       # same owner, same ticker


def test_same_ticker_under_different_owners_remains_valid(db):
    """The distinction the whole investigation turned on."""
    with db.begin() as conn:
        _insert(conn, OWNER_1, "AAA")
        _insert(conn, OWNER_2, "AAA")
        _insert(conn, None, "AAA")              # legacy namespace too
    with db.connect() as conn:
        n = conn.execute(sa.text(
            "SELECT COUNT(*) FROM watched_tickers WHERE ticker='AAA'")).scalar()
    assert n == 3


def test_legacy_null_owner_rows_are_unique_by_ticker(db):
    with db.begin() as conn:
        _insert(conn, None, "AAA")
    with pytest.raises(sa.exc.IntegrityError):
        with db.begin() as conn:
            _insert(conn, None, "AAA")


def test_legacy_and_owned_namespaces_do_not_collide(db):
    with db.begin() as conn:
        _insert(conn, None, "AAA")
        _insert(conn, OWNER_1, "AAA")           # must be allowed
    with db.connect() as conn:
        assert conn.execute(sa.text(
            "SELECT COUNT(*) FROM watched_tickers")).scalar() == 2


def test_inactive_historical_duplicates_remain_allowed(db):
    """Soft-deleted history must survive; the index is partial on active."""
    with db.begin() as conn:
        _insert(conn, OWNER_1, "AAA", active=True)
        for _ in range(5):
            _insert(conn, OWNER_1, "AAA", active=False)
        for _ in range(3):
            _insert(conn, None, "BBB", active=False)
    with db.connect() as conn:
        assert conn.execute(sa.text(
            "SELECT COUNT(*) FROM watched_tickers")).scalar() == 9


def test_reactivating_a_second_row_is_rejected(db):
    """Exactly the situation a cleanup rollback would create."""
    with db.begin() as conn:
        _insert(conn, OWNER_1, "AAA", active=True)
        _insert(conn, OWNER_1, "AAA", active=False)
    with pytest.raises(sa.exc.IntegrityError):
        with db.begin() as conn:
            conn.execute(sa.text(
                "UPDATE watched_tickers SET active=1 WHERE active=0"))


def test_deactivating_then_readding_is_allowed(db):
    with db.begin() as conn:
        _insert(conn, OWNER_1, "AAA", active=True)
    with db.begin() as conn:
        conn.execute(sa.text("UPDATE watched_tickers SET active=0"))
        _insert(conn, OWNER_1, "AAA", active=True)
    with db.connect() as conn:
        assert conn.execute(sa.text(
            "SELECT COUNT(*) FROM watched_tickers WHERE active IS TRUE"
        )).scalar() == 1


# ===========================================================================
# § NAMES, COLUMNS, PREDICATES AND EXACT SQL
# ===========================================================================

def test_exact_index_names_are_pinned():
    assert M.INDEX_OWNED == "uq_watched_tickers_owner_ticker_active"
    assert M.INDEX_LEGACY == "uq_watched_tickers_legacy_ticker_active"


def test_exact_upgrade_sql():
    assert M.CREATE_OWNED == (
        "CREATE UNIQUE INDEX CONCURRENTLY "
        "uq_watched_tickers_owner_ticker_active "
        "ON watched_tickers (user_id, ticker) "
        "WHERE active IS TRUE AND user_id IS NOT NULL")
    assert M.CREATE_LEGACY == (
        "CREATE UNIQUE INDEX CONCURRENTLY "
        "uq_watched_tickers_legacy_ticker_active "
        "ON watched_tickers (ticker) "
        "WHERE active IS TRUE AND user_id IS NULL")


def test_exact_downgrade_sql_uses_concurrently():
    assert M.DROP_OWNED == (
        "DROP INDEX CONCURRENTLY IF EXISTS "
        "uq_watched_tickers_owner_ticker_active")
    assert M.DROP_LEGACY == (
        "DROP INDEX CONCURRENTLY IF EXISTS "
        "uq_watched_tickers_legacy_ticker_active")


def test_both_creates_are_unique_concurrently_and_partial():
    for sql in (M.CREATE_OWNED, M.CREATE_LEGACY):
        assert "CREATE UNIQUE INDEX CONCURRENTLY" in sql
        assert "WHERE active IS TRUE" in sql
        assert "watched_tickers" in sql


def test_forbidden_constructs_are_absent():
    """Scan executable CODE. The docstring legitimately explains why COALESCE
    and NULLS NOT DISTINCT are rejected, and prose must not trip its own
    check."""
    import io
    import tokenize

    code = []
    for tok in tokenize.generate_tokens(
            io.StringIO(_MIG_PATH.read_text()).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        code.append(tok.string)
    lowered = " ".join(code).lower()
    assert "coalesce" not in lowered, "COALESCE must not be used"
    assert "nulls not distinct" not in lowered
    assert "uniqueconstraint" not in lowered, "must be a partial INDEX"
    for verb in ("delete from", "update watched_tickers set active",
                 "insert into watched_tickers"):
        assert verb not in lowered, "no watchlist row may be altered: %s" % verb


def test_revision_chain():
    assert M.revision == "0005_watchlist_unique_active"
    assert M.down_revision == "0004_portfolios_org_id"


# ===========================================================================
# § MIGRATION MECHANICS (stubbed PostgreSQL bind)
# ===========================================================================

class _Bind:
    """Minimal bind recording executed SQL, with scripted scalar results."""

    def __init__(self, dialect="postgresql", owned_dupes=0, legacy_dupes=0,
                 catalog=None):
        self.dialect = type("D", (), {"name": dialect})()
        self.sql = []
        self._owned = owned_dupes
        self._legacy = legacy_dupes
        self._catalog = catalog or {}

    def execute(self, statement, params=None):
        text = str(statement)
        self.sql.append(" ".join(text.split()))
        if "GROUP BY user_id, ticker" in text:
            return _Scalar(self._owned)
        if "GROUP BY ticker" in text:
            return _Scalar(self._legacy)
        if "pg_index" in text:
            return _Mappings(self._catalog.get((params or {}).get("name")))
        return _Scalar(None)


class _Scalar:
    def __init__(self, value):
        self._v = value

    def scalar(self):
        return self._v


class _Mappings:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


def _catalog_row(name, table="watched_tickers", unique=True, valid=True,
                 ready=True, predicate=None, indexdef=None):
    cols = "user_id, ticker" if "owner" in name else "ticker"
    pred = predicate if predicate is not None else (
        "(active IS TRUE) AND (user_id IS NOT NULL)" if "owner" in name
        else "(active IS TRUE) AND (user_id IS NULL)")
    return {
        "index_name": name, "table_name": table, "is_unique": unique,
        "is_valid": valid, "is_ready": ready, "predicate": pred,
        "indexdef": indexdef if indexdef is not None else
        "CREATE UNIQUE INDEX %s ON public.watched_tickers USING btree (%s) "
        "WHERE %s" % (name, cols, pred),
    }


# --- preflight ------------------------------------------------------------

def test_preflight_refuses_owned_duplicates_before_any_ddl():
    bind = _Bind(owned_dupes=24)
    with pytest.raises(M.MigrationPreflightError) as ei:
        M.duplicate_preflight(bind)
    assert "owned groups=24" in str(ei.value)
    assert not any("CREATE" in s.upper() for s in bind.sql)


def test_preflight_refuses_legacy_duplicates_before_any_ddl():
    bind = _Bind(legacy_dupes=3)
    with pytest.raises(M.MigrationPreflightError) as ei:
        M.duplicate_preflight(bind)
    assert "legacy groups=3" in str(ei.value)
    assert not any("CREATE" in s.upper() for s in bind.sql)


def test_preflight_passes_when_no_duplicates_remain():
    M.duplicate_preflight(_Bind(owned_dupes=0, legacy_dupes=0))


def test_preflight_refuses_an_invalid_pre_existing_index():
    bind = _Bind(catalog={M.INDEX_OWNED: _catalog_row(M.INDEX_OWNED, valid=False)})
    with pytest.raises(M.MigrationPreflightError) as ei:
        M.existing_index_preflight(bind)
    assert "invalid or not ready" in str(ei.value)


def test_preflight_refuses_a_not_ready_pre_existing_index():
    bind = _Bind(catalog={M.INDEX_LEGACY: _catalog_row(M.INDEX_LEGACY, ready=False)})
    with pytest.raises(M.MigrationPreflightError):
        M.existing_index_preflight(bind)


def test_preflight_refuses_an_unexpected_non_unique_index():
    bind = _Bind(catalog={M.INDEX_OWNED: _catalog_row(M.INDEX_OWNED, unique=False)})
    with pytest.raises(M.MigrationPreflightError) as ei:
        M.existing_index_preflight(bind)
    assert "Refusing to replace it" in str(ei.value)


def test_preflight_never_drops_an_unexpected_index():
    bind = _Bind(catalog={M.INDEX_OWNED: _catalog_row(M.INDEX_OWNED, unique=False)})
    with pytest.raises(M.MigrationPreflightError):
        M.existing_index_preflight(bind)
    assert not any("DROP" in s.upper() for s in bind.sql), (
        "an unexpected index must never be dropped or replaced silently"
    )


def test_preflight_accepts_an_already_correct_index():
    bind = _Bind(catalog={M.INDEX_OWNED: _catalog_row(M.INDEX_OWNED)})
    M.existing_index_preflight(bind)          # no raise: rerun is a no-op


# --- catalog validation ---------------------------------------------------

@pytest.mark.parametrize("kwargs,fragment", [
    ({"unique": False}, "not UNIQUE"),
    ({"valid": False}, "indisvalid=false"),
    ({"ready": False}, "indisready=false"),
    ({"table": "some_other_table"}, "targets"),
    ({"predicate": ""}, "no partial predicate"),
    ({"predicate": "(user_id IS NOT NULL)"}, "missing active"),
    ({"indexdef": "CREATE UNIQUE INDEX x ON watched_tickers (company_name)"},
     "missing column"),
])
def test_catalog_validation_rejects_bad_indexes(kwargs, fragment):
    bind = _Bind(catalog={M.INDEX_OWNED: _catalog_row(M.INDEX_OWNED, **kwargs)})
    with pytest.raises(M.IndexValidationError) as ei:
        M.validate_index(bind, M.INDEX_OWNED)
    assert fragment in str(ei.value)


def test_owned_index_predicate_must_scope_to_non_null_owners():
    """The mirror of the legacy check: a swapped predicate must be caught."""
    bad = _catalog_row(M.INDEX_OWNED,
                       predicate="(active IS TRUE) AND (user_id IS NULL)")
    with pytest.raises(M.IndexValidationError) as ei:
        M.validate_index(_Bind(catalog={M.INDEX_OWNED: bad}), M.INDEX_OWNED)
    assert "NON-NULL owners" in str(ei.value)


def test_catalog_validation_rejects_a_missing_index():
    with pytest.raises(M.IndexValidationError) as ei:
        M.validate_index(_Bind(catalog={}), M.INDEX_OWNED)
    assert "does not exist" in str(ei.value)


def test_catalog_validation_accepts_correct_indexes():
    bind = _Bind(catalog={
        M.INDEX_OWNED: _catalog_row(M.INDEX_OWNED),
        M.INDEX_LEGACY: _catalog_row(M.INDEX_LEGACY),
    })
    M.validate_index(bind, M.INDEX_OWNED)
    M.validate_index(bind, M.INDEX_LEGACY)


def test_legacy_predicate_must_scope_to_null_owners():
    bad = _catalog_row(M.INDEX_LEGACY,
                       predicate="(active IS TRUE) AND (user_id IS NOT NULL)")
    with pytest.raises(M.IndexValidationError) as ei:
        M.validate_index(_Bind(catalog={M.INDEX_LEGACY: bad}), M.INDEX_LEGACY)
    assert "NULL owners" in str(ei.value)


# --- autocommit / dialect gating -----------------------------------------

def test_ddl_runs_inside_an_autocommit_block_and_only_on_postgres():
    """CONCURRENTLY cannot run in a transaction; assert the block is used."""
    src = _MIG_PATH.read_text()
    assert "op.get_context().autocommit_block()" in src
    upgrade = src[src.index("def upgrade("):src.index("def downgrade(")]
    downgrade = src[src.index("def downgrade("):]
    for section, label in ((upgrade, "upgrade"), (downgrade, "downgrade")):
        assert "autocommit_block()" in section, "%s needs the block" % label
        assert "_is_postgres(bind)" in section, "%s must gate on dialect" % label
        block_at = section.index("autocommit_block()")
        for marker in ("CREATE_OWNED", "CREATE_LEGACY", "DROP_OWNED", "DROP_LEGACY"):
            if marker in section:
                assert section.index(marker) > block_at, (
                    "%s must be executed inside the autocommit block" % marker
                )


def test_non_postgres_upgrade_and_downgrade_are_no_ops(monkeypatch):
    executed = []
    monkeypatch.setattr(M.op, "get_bind", lambda: _Bind(dialect="sqlite"))
    monkeypatch.setattr(M.op, "execute", lambda *a, **k: executed.append(a))
    M.upgrade()
    M.downgrade()
    assert executed == [], "no DDL may be emitted on a non-PostgreSQL dialect"
