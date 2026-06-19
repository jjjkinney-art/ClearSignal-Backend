"""
Tests — User Learning Repositories, Phase 15 · Slice 2.

Covers:
  1.  repo module importable
  2.  null-session safety on every function
  3.  add_user_signal_event CRUD
  4.  list_user_signal_events with filters
  5.  count_user_signal_events with filters
  6.  delete_expired_user_signal_events
  7.  upsert_learned_preference (insert + update)
  8.  get_learned_preference
  9.  list_learned_preferences with filters
  10. count_learned_preferences with filters
  11. delete_learned_preference
  12. tenant isolation — user A events invisible to user B
  13. tenant isolation — user A preferences invisible to user B
  14. add_preference_evidence
  15. list_preference_evidence with filters
  16. delete_evidence_for_preference
  17. count_preference_evidence
  18. add_relevance_adjustment_log
  19. list_relevance_adjustment_logs with filters
  20. count_relevance_adjustment_logs with filters
  21. relevance_adjustment_log append-only AST check (no update/delete)
  22. no truth-table imports in the repo
  23. no advice/trade language in the repo
  24. no source-table mutation during repo operations
  25. each add_relevance_adjustment_log call creates a new row (append-only)
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Engine / session fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture()
async def db(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncSessionLocal() as session:
        yield session


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. Module importable
# ---------------------------------------------------------------------------

class TestImport:
    def test_user_learning_repo_importable(self):
        import app.db.repositories.user_learning_repo  # noqa: F401

    def test_all_functions_importable(self):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event,
            list_user_signal_events,
            count_user_signal_events,
            delete_expired_user_signal_events,
            upsert_learned_preference,
            get_learned_preference,
            list_learned_preferences,
            count_learned_preferences,
            delete_learned_preference,
            add_preference_evidence,
            list_preference_evidence,
            delete_evidence_for_preference,
            count_preference_evidence,
            add_relevance_adjustment_log,
            list_relevance_adjustment_logs,
            count_relevance_adjustment_logs,
        )
        # All names must be callable
        for fn in (
            add_user_signal_event, list_user_signal_events,
            count_user_signal_events, delete_expired_user_signal_events,
            upsert_learned_preference, get_learned_preference,
            list_learned_preferences, count_learned_preferences,
            delete_learned_preference, add_preference_evidence,
            list_preference_evidence, delete_evidence_for_preference,
            count_preference_evidence, add_relevance_adjustment_log,
            list_relevance_adjustment_logs, count_relevance_adjustment_logs,
        ):
            assert callable(fn), f"{fn.__name__} is not callable"


# ---------------------------------------------------------------------------
# 2. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_add_signal_event_null(self):
        from app.db.repositories.user_learning_repo import add_user_signal_event
        assert await add_user_signal_event(None, user_id="u1", signal_type="analysis_open") is None

    @pytest.mark.asyncio
    async def test_list_signal_events_null(self):
        from app.db.repositories.user_learning_repo import list_user_signal_events
        assert await list_user_signal_events(None) == []

    @pytest.mark.asyncio
    async def test_count_signal_events_null(self):
        from app.db.repositories.user_learning_repo import count_user_signal_events
        assert await count_user_signal_events(None) == 0

    @pytest.mark.asyncio
    async def test_delete_expired_events_null(self):
        from app.db.repositories.user_learning_repo import delete_expired_user_signal_events
        assert await delete_expired_user_signal_events(None, cutoff=_now()) == 0

    @pytest.mark.asyncio
    async def test_upsert_preference_null(self):
        from app.db.repositories.user_learning_repo import upsert_learned_preference
        result = await upsert_learned_preference(
            None, user_id="u1", dimension="sector_interest", entity_key="semis",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_preference_null(self):
        from app.db.repositories.user_learning_repo import get_learned_preference
        result = await get_learned_preference(
            None, user_id="u1", dimension="sector_interest", entity_key="semis",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_list_preferences_null(self):
        from app.db.repositories.user_learning_repo import list_learned_preferences
        assert await list_learned_preferences(None) == []

    @pytest.mark.asyncio
    async def test_count_preferences_null(self):
        from app.db.repositories.user_learning_repo import count_learned_preferences
        assert await count_learned_preferences(None) == 0

    @pytest.mark.asyncio
    async def test_delete_preference_null(self):
        from app.db.repositories.user_learning_repo import delete_learned_preference
        result = await delete_learned_preference(
            None, user_id="u1", dimension="sector_interest", entity_key="semis",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_add_evidence_null(self):
        from app.db.repositories.user_learning_repo import add_preference_evidence
        result = await add_preference_evidence(
            None, preference_id="p1", signal_event_id="e1",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_list_evidence_null(self):
        from app.db.repositories.user_learning_repo import list_preference_evidence
        assert await list_preference_evidence(None) == []

    @pytest.mark.asyncio
    async def test_delete_evidence_null(self):
        from app.db.repositories.user_learning_repo import delete_evidence_for_preference
        assert await delete_evidence_for_preference(None, preference_id="p1") == 0

    @pytest.mark.asyncio
    async def test_count_evidence_null(self):
        from app.db.repositories.user_learning_repo import count_preference_evidence
        assert await count_preference_evidence(None) == 0

    @pytest.mark.asyncio
    async def test_add_adjustment_log_null(self):
        from app.db.repositories.user_learning_repo import add_relevance_adjustment_log
        result = await add_relevance_adjustment_log(
            None, user_id="u1", surface="feed",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_list_adjustment_logs_null(self):
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        assert await list_relevance_adjustment_logs(None) == []

    @pytest.mark.asyncio
    async def test_count_adjustment_logs_null(self):
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        assert await count_relevance_adjustment_logs(None) == 0


# ---------------------------------------------------------------------------
# 3. add_user_signal_event CRUD
# ---------------------------------------------------------------------------

class TestSignalEventCRUD:
    @pytest.mark.asyncio
    async def test_add_creates_row(self, db):
        from app.db.repositories.user_learning_repo import add_user_signal_event
        uid = _uid()
        row = await add_user_signal_event(
            db,
            user_id    = uid,
            signal_type = "analysis_open",
            polarity    = "positive",
            entity_type = "company",
            entity_key  = "NVDA",
        )
        await db.commit()
        assert row is not None
        assert row.user_id == uid
        assert row.signal_type == "analysis_open"
        assert row.polarity == "positive"

    @pytest.mark.asyncio
    async def test_add_anti_loop_fields(self, db):
        from app.db.repositories.user_learning_repo import add_user_signal_event
        uid = _uid()
        row = await add_user_signal_event(
            db,
            user_id                  = uid,
            signal_type              = "forecast_view",
            surface_was_personalized = True,
            pre_personalization_rank = 3,
        )
        await db.commit()
        assert row.surface_was_personalized is True
        assert row.pre_personalization_rank == 3

    @pytest.mark.asyncio
    async def test_add_returns_different_ids(self, db):
        from app.db.repositories.user_learning_repo import add_user_signal_event
        uid = _uid()
        r1 = await add_user_signal_event(db, user_id=uid, signal_type="analysis_open")
        r2 = await add_user_signal_event(db, user_id=uid, signal_type="analysis_open")
        await db.commit()
        assert r1.id != r2.id


# ---------------------------------------------------------------------------
# 4 & 5. list and count user_signal_events with filters
# ---------------------------------------------------------------------------

class TestSignalEventListCount:
    @pytest.mark.asyncio
    async def test_list_by_user_id(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, list_user_signal_events,
        )
        uid_a, uid_b = _uid(), _uid()
        await add_user_signal_event(db, user_id=uid_a, signal_type="alert_open")
        await add_user_signal_event(db, user_id=uid_a, signal_type="alert_open")
        await add_user_signal_event(db, user_id=uid_b, signal_type="alert_open")
        await db.commit()
        rows_a = await list_user_signal_events(db, user_id=uid_a)
        assert len(rows_a) == 2

    @pytest.mark.asyncio
    async def test_list_by_signal_type(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, list_user_signal_events,
        )
        uid = _uid()
        await add_user_signal_event(db, user_id=uid, signal_type="analysis_open")
        await add_user_signal_event(db, user_id=uid, signal_type="alert_dismiss")
        await db.commit()
        rows = await list_user_signal_events(db, signal_type="analysis_open")
        assert all(r.signal_type == "analysis_open" for r in rows)

    @pytest.mark.asyncio
    async def test_list_by_polarity(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, list_user_signal_events,
        )
        uid = _uid()
        await add_user_signal_event(db, user_id=uid, signal_type="a", polarity="positive")
        await add_user_signal_event(db, user_id=uid, signal_type="b", polarity="negative")
        await db.commit()
        pos = await list_user_signal_events(db, user_id=uid, polarity="positive")
        assert len(pos) == 1

    @pytest.mark.asyncio
    async def test_list_by_occurred_after(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, list_user_signal_events,
        )
        uid = _uid()
        old_ts = _now() - timedelta(days=10)
        await add_user_signal_event(db, user_id=uid, signal_type="a", occurred_at=old_ts)
        await add_user_signal_event(db, user_id=uid, signal_type="b")
        await db.commit()
        cutoff = _now() - timedelta(days=1)
        recent = await list_user_signal_events(db, user_id=uid, occurred_after=cutoff)
        assert len(recent) == 1

    @pytest.mark.asyncio
    async def test_count_by_user_id(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, count_user_signal_events,
        )
        uid = _uid()
        await add_user_signal_event(db, user_id=uid, signal_type="a")
        await add_user_signal_event(db, user_id=uid, signal_type="b")
        await db.commit()
        n = await count_user_signal_events(db, user_id=uid)
        assert n == 2

    @pytest.mark.asyncio
    async def test_count_by_signal_type(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, count_user_signal_events,
        )
        uid = _uid()
        await add_user_signal_event(db, user_id=uid, signal_type="analysis_open")
        await add_user_signal_event(db, user_id=uid, signal_type="alert_dismiss")
        await db.commit()
        n = await count_user_signal_events(db, signal_type="analysis_open")
        assert n >= 1


# ---------------------------------------------------------------------------
# 6. delete_expired_user_signal_events
# ---------------------------------------------------------------------------

class TestSignalEventExpiry:
    @pytest.mark.asyncio
    async def test_delete_expired_removes_old_rows(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, delete_expired_user_signal_events,
            count_user_signal_events,
        )
        uid = _uid()
        old_ts = _now() - timedelta(days=100)
        await add_user_signal_event(db, user_id=uid, signal_type="a", occurred_at=old_ts)
        await add_user_signal_event(db, user_id=uid, signal_type="b")  # recent
        await db.commit()

        cutoff = _now() - timedelta(days=30)
        deleted = await delete_expired_user_signal_events(db, cutoff=cutoff)
        await db.commit()
        assert deleted == 1
        remaining = await count_user_signal_events(db, user_id=uid)
        assert remaining == 1

    @pytest.mark.asyncio
    async def test_delete_expired_returns_zero_when_nothing_old(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, delete_expired_user_signal_events,
        )
        uid = _uid()
        await add_user_signal_event(db, user_id=uid, signal_type="a")
        await db.commit()
        cutoff = _now() - timedelta(days=30)
        deleted = await delete_expired_user_signal_events(db, cutoff=cutoff)
        assert deleted == 0


# ---------------------------------------------------------------------------
# 7 & 8. upsert_learned_preference + get_learned_preference
# ---------------------------------------------------------------------------

class TestLearnedPreferenceUpsertGet:
    @pytest.mark.asyncio
    async def test_upsert_creates_row(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, get_learned_preference,
        )
        uid = _uid()
        row = await upsert_learned_preference(
            db,
            user_id       = uid,
            dimension     = "sector_interest",
            entity_key    = "semiconductors",
            affinity      = 0.75,
            confidence    = 0.8,
            evidence_count = 12,
            status        = "active",
            belief_basis  = "Opened semiconductor analyses 12× in 30d",
            falsifier     = "30d without a semiconductor interaction",
        )
        await db.commit()
        assert row is not None
        assert row.affinity == 0.75
        assert row.status == "active"

        fetched = await get_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semiconductors",
        )
        assert fetched is not None
        assert fetched.affinity == 0.75

    @pytest.mark.asyncio
    async def test_upsert_updates_in_place(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, get_learned_preference, count_learned_preferences,
        )
        uid = _uid()
        await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
            affinity=0.5, status="unresolved",
        )
        await db.commit()
        await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
            affinity=0.9, status="active",
        )
        await db.commit()

        # Same unique key → exactly one row
        n = await count_learned_preferences(db, user_id=uid)
        assert n == 1

        row = await get_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        assert row.affinity == 0.9
        assert row.status == "active"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, db):
        from app.db.repositories.user_learning_repo import get_learned_preference
        row = await get_learned_preference(
            db, user_id=_uid(), dimension="sector_interest", entity_key="nonexistent",
        )
        assert row is None


# ---------------------------------------------------------------------------
# 9 & 10. list_learned_preferences + count_learned_preferences
# ---------------------------------------------------------------------------

class TestLearnedPreferenceListCount:
    @pytest.mark.asyncio
    async def test_list_by_user_id(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, list_learned_preferences,
        )
        uid = _uid()
        await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        await upsert_learned_preference(
            db, user_id=uid, dimension="company_interest", entity_key="NVDA",
        )
        await db.commit()
        rows = await list_learned_preferences(db, user_id=uid)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_list_by_dimension(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, list_learned_preferences,
        )
        uid = _uid()
        await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        await upsert_learned_preference(
            db, user_id=uid, dimension="company_interest", entity_key="NVDA",
        )
        await db.commit()
        sector_rows = await list_learned_preferences(db, dimension="sector_interest")
        assert all(r.dimension == "sector_interest" for r in sector_rows)

    @pytest.mark.asyncio
    async def test_list_by_status(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, list_learned_preferences,
        )
        uid = _uid()
        await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis", status="active",
        )
        await upsert_learned_preference(
            db, user_id=uid, dimension="company_interest", entity_key="NVDA", status="unresolved",
        )
        await db.commit()
        active = await list_learned_preferences(db, user_id=uid, status="active")
        assert len(active) == 1
        assert active[0].status == "active"

    @pytest.mark.asyncio
    async def test_count_by_dimension_and_status(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, count_learned_preferences,
        )
        uid = _uid()
        await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis", status="active",
        )
        await upsert_learned_preference(
            db, user_id=uid, dimension="company_interest", entity_key="NVDA", status="unresolved",
        )
        await db.commit()
        n = await count_learned_preferences(db, user_id=uid, status="active")
        assert n == 1


# ---------------------------------------------------------------------------
# 11. delete_learned_preference
# ---------------------------------------------------------------------------

class TestLearnedPreferenceDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_row(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, delete_learned_preference,
            get_learned_preference,
        )
        uid = _uid()
        await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        await db.commit()

        deleted = await delete_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        await db.commit()
        assert deleted is True

        gone = await get_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        assert gone is None

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self, db):
        from app.db.repositories.user_learning_repo import delete_learned_preference
        result = await delete_learned_preference(
            db, user_id=_uid(), dimension="sector_interest", entity_key="nonexistent",
        )
        assert result is False


# ---------------------------------------------------------------------------
# 12. Tenant isolation — events
# ---------------------------------------------------------------------------

class TestSignalEventTenantIsolation:
    @pytest.mark.asyncio
    async def test_user_a_events_not_visible_to_user_b(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, list_user_signal_events,
        )
        uid_a, uid_b = _uid(), _uid()
        await add_user_signal_event(db, user_id=uid_a, signal_type="analysis_open")
        await db.commit()
        rows_b = await list_user_signal_events(db, user_id=uid_b)
        assert rows_b == []

    @pytest.mark.asyncio
    async def test_count_is_per_user(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, count_user_signal_events,
        )
        uid_a, uid_b = _uid(), _uid()
        await add_user_signal_event(db, user_id=uid_a, signal_type="a")
        await add_user_signal_event(db, user_id=uid_a, signal_type="b")
        await add_user_signal_event(db, user_id=uid_b, signal_type="a")
        await db.commit()
        assert await count_user_signal_events(db, user_id=uid_a) == 2
        assert await count_user_signal_events(db, user_id=uid_b) == 1


# ---------------------------------------------------------------------------
# 13. Tenant isolation — preferences
# ---------------------------------------------------------------------------

class TestPreferenceTenantIsolation:
    @pytest.mark.asyncio
    async def test_user_a_preferences_not_visible_to_user_b(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, list_learned_preferences,
        )
        uid_a, uid_b = _uid(), _uid()
        await upsert_learned_preference(
            db, user_id=uid_a, dimension="sector_interest", entity_key="semis",
        )
        await db.commit()
        rows_b = await list_learned_preferences(db, user_id=uid_b)
        assert rows_b == []

    @pytest.mark.asyncio
    async def test_same_entity_key_different_users_are_independent(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, get_learned_preference,
        )
        uid_a, uid_b = _uid(), _uid()
        await upsert_learned_preference(
            db, user_id=uid_a, dimension="sector_interest", entity_key="semis",
            affinity=0.9,
        )
        await upsert_learned_preference(
            db, user_id=uid_b, dimension="sector_interest", entity_key="semis",
            affinity=0.1,
        )
        await db.commit()
        row_a = await get_learned_preference(
            db, user_id=uid_a, dimension="sector_interest", entity_key="semis",
        )
        row_b = await get_learned_preference(
            db, user_id=uid_b, dimension="sector_interest", entity_key="semis",
        )
        assert row_a.affinity == 0.9
        assert row_b.affinity == 0.1


# ---------------------------------------------------------------------------
# 14 – 17. Preference evidence
# ---------------------------------------------------------------------------

class TestPreferenceEvidence:
    @pytest.mark.asyncio
    async def test_add_evidence_creates_row(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, add_preference_evidence,
        )
        uid = _uid()
        pref = await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        await db.commit()

        ev = await add_preference_evidence(
            db,
            preference_id   = pref.id,
            signal_event_id = _uid(),
            contribution    = 0.42,
            source          = "analysis_history",
        )
        await db.commit()
        assert ev is not None
        assert ev.preference_id == pref.id
        assert ev.contribution == 0.42

    @pytest.mark.asyncio
    async def test_list_evidence_by_preference_id(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, add_preference_evidence, list_preference_evidence,
        )
        uid = _uid()
        pref = await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        await db.commit()

        await add_preference_evidence(db, preference_id=pref.id, signal_event_id=_uid())
        await add_preference_evidence(db, preference_id=pref.id, signal_event_id=_uid())
        await db.commit()

        rows = await list_preference_evidence(db, preference_id=pref.id)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_list_evidence_by_source(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, add_preference_evidence, list_preference_evidence,
        )
        uid = _uid()
        pref = await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        await db.commit()

        await add_preference_evidence(
            db, preference_id=pref.id, signal_event_id=_uid(), source="watchlist_behavior",
        )
        await add_preference_evidence(
            db, preference_id=pref.id, signal_event_id=_uid(), source="analysis_history",
        )
        await db.commit()

        watch_rows = await list_preference_evidence(db, source="watchlist_behavior")
        assert len(watch_rows) >= 1
        assert all(r.source == "watchlist_behavior" for r in watch_rows)

    @pytest.mark.asyncio
    async def test_delete_evidence_for_preference(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, add_preference_evidence,
            delete_evidence_for_preference, list_preference_evidence,
        )
        uid = _uid()
        pref = await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        await db.commit()

        await add_preference_evidence(db, preference_id=pref.id, signal_event_id=_uid())
        await add_preference_evidence(db, preference_id=pref.id, signal_event_id=_uid())
        await db.commit()

        deleted = await delete_evidence_for_preference(db, preference_id=pref.id)
        await db.commit()
        assert deleted == 2
        remaining = await list_preference_evidence(db, preference_id=pref.id)
        assert remaining == []

    @pytest.mark.asyncio
    async def test_count_evidence_by_preference(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, add_preference_evidence, count_preference_evidence,
        )
        uid = _uid()
        pref = await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        await db.commit()

        await add_preference_evidence(db, preference_id=pref.id, signal_event_id=_uid())
        await add_preference_evidence(db, preference_id=pref.id, signal_event_id=_uid())
        await db.commit()
        n = await count_preference_evidence(db, preference_id=pref.id)
        assert n == 2

    @pytest.mark.asyncio
    async def test_count_evidence_total(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, add_preference_evidence, count_preference_evidence,
        )
        uid = _uid()
        pref = await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        await db.commit()
        await add_preference_evidence(db, preference_id=pref.id, signal_event_id=_uid())
        await db.commit()
        n = await count_preference_evidence(db)
        assert n >= 1


# ---------------------------------------------------------------------------
# 18 – 20. Relevance adjustment log
# ---------------------------------------------------------------------------

class TestRelevanceAdjustmentLog:
    @pytest.mark.asyncio
    async def test_add_creates_row(self, db):
        from app.db.repositories.user_learning_repo import add_relevance_adjustment_log
        uid = _uid()
        row = await add_relevance_adjustment_log(
            db,
            user_id          = uid,
            surface          = "feed",
            run_reason       = "shadow",
            item_ref         = "fc-001",
            intrinsic_rank   = 5,
            adjusted_rank    = 3,
            relevance_weight = 0.3,
            prominence_tier  = "normal",
            floor_applied    = False,
        )
        await db.commit()
        assert row is not None
        assert row.user_id == uid
        assert row.run_reason == "shadow"
        assert row.intrinsic_rank == 5
        assert row.adjusted_rank == 3

    @pytest.mark.asyncio
    async def test_each_add_creates_new_row(self, db):
        from app.db.repositories.user_learning_repo import (
            add_relevance_adjustment_log, count_relevance_adjustment_logs,
        )
        uid = _uid()
        await add_relevance_adjustment_log(db, user_id=uid, surface="feed", item_ref="fc-001")
        await add_relevance_adjustment_log(db, user_id=uid, surface="feed", item_ref="fc-001")
        await add_relevance_adjustment_log(db, user_id=uid, surface="feed", item_ref="fc-002")
        await db.commit()
        n = await count_relevance_adjustment_logs(db, user_id=uid)
        assert n == 3  # append-only: all three rows persist

    @pytest.mark.asyncio
    async def test_list_by_user_id(self, db):
        from app.db.repositories.user_learning_repo import (
            add_relevance_adjustment_log, list_relevance_adjustment_logs,
        )
        uid_a, uid_b = _uid(), _uid()
        await add_relevance_adjustment_log(db, user_id=uid_a, surface="feed")
        await add_relevance_adjustment_log(db, user_id=uid_b, surface="feed")
        await db.commit()
        rows_a = await list_relevance_adjustment_logs(db, user_id=uid_a)
        assert len(rows_a) == 1
        assert rows_a[0].user_id == uid_a

    @pytest.mark.asyncio
    async def test_list_by_surface(self, db):
        from app.db.repositories.user_learning_repo import (
            add_relevance_adjustment_log, list_relevance_adjustment_logs,
        )
        uid = _uid()
        await add_relevance_adjustment_log(db, user_id=uid, surface="feed")
        await add_relevance_adjustment_log(db, user_id=uid, surface="alert_digest")
        await db.commit()
        feed_rows = await list_relevance_adjustment_logs(db, surface="feed")
        assert all(r.surface == "feed" for r in feed_rows)

    @pytest.mark.asyncio
    async def test_list_by_run_reason(self, db):
        from app.db.repositories.user_learning_repo import (
            add_relevance_adjustment_log, list_relevance_adjustment_logs,
        )
        uid = _uid()
        await add_relevance_adjustment_log(db, user_id=uid, surface="feed", run_reason="shadow")
        await db.commit()
        shadow_rows = await list_relevance_adjustment_logs(db, run_reason="shadow")
        assert len(shadow_rows) >= 1

    @pytest.mark.asyncio
    async def test_list_floor_applied_filter(self, db):
        from app.db.repositories.user_learning_repo import (
            add_relevance_adjustment_log, list_relevance_adjustment_logs,
        )
        uid = _uid()
        await add_relevance_adjustment_log(
            db, user_id=uid, surface="feed", floor_applied=True, item_ref="critical-001",
        )
        await add_relevance_adjustment_log(
            db, user_id=uid, surface="feed", floor_applied=False, item_ref="normal-001",
        )
        await db.commit()
        floored = await list_relevance_adjustment_logs(db, user_id=uid, floor_applied=True)
        assert len(floored) == 1
        assert floored[0].floor_applied is True

    @pytest.mark.asyncio
    async def test_count_by_run_reason(self, db):
        from app.db.repositories.user_learning_repo import (
            add_relevance_adjustment_log, count_relevance_adjustment_logs,
        )
        uid = _uid()
        await add_relevance_adjustment_log(db, user_id=uid, surface="feed", run_reason="shadow")
        await add_relevance_adjustment_log(db, user_id=uid, surface="feed", run_reason="shadow")
        await db.commit()
        n = await count_relevance_adjustment_logs(db, run_reason="shadow")
        assert n >= 2


# ---------------------------------------------------------------------------
# 21. Relevance adjustment log append-only AST check
# ---------------------------------------------------------------------------

class TestRelevanceAdjustmentLogAppendOnlyAST:
    def _load_repo_source(self):
        import app.db.repositories.user_learning_repo as mod
        return inspect.getsource(mod)

    def test_add_log_function_has_no_update_call(self):
        src  = self._load_repo_source()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "add_relevance_adjustment_log":
                    fn_src = ast.unparse(node)
                    assert "session.merge(" not in fn_src, \
                        "merge() found in add_relevance_adjustment_log — append-only violation"
                    assert "session.delete(" not in fn_src, \
                        "delete() found in add_relevance_adjustment_log — append-only violation"
                    for child in ast.walk(node):
                        if isinstance(child, ast.Attribute) and child.attr == "update":
                            assert False, (
                                f"update() found in add_relevance_adjustment_log: "
                                f"{ast.unparse(child)}"
                            )
                    return
        pytest.fail("add_relevance_adjustment_log not found in user_learning_repo")

    def test_no_delete_of_relevance_adjustment_log_anywhere_in_repo(self):
        src = self._load_repo_source()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Look for session.delete(row) where row is a RelevanceAdjustmentLog
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "delete"
                    and node.args
                ):
                    arg_src = ast.unparse(node.args[0])
                    assert "RelevanceAdjustmentLog" not in arg_src, (
                        f"session.delete(RelevanceAdjustmentLog...) found in repo — "
                        f"append-only violation: {arg_src}"
                    )

    def test_no_bulk_delete_of_relevance_adjustment_log_in_repo(self):
        src = self._load_repo_source()
        # The SQL delete() macro must never target relevance_adjustment_log
        # Look for delete(RelevanceAdjustmentLog) pattern in the AST
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn_src = ast.unparse(node)
                if "delete(" in fn_src and "RelevanceAdjustmentLog" in fn_src:
                    assert False, (
                        "Bulk delete targeting RelevanceAdjustmentLog found — "
                        "this table is append-only"
                    )


# ---------------------------------------------------------------------------
# 22. No truth-table imports
# ---------------------------------------------------------------------------

class TestNoTruthTableImports:
    def test_repo_does_not_import_write_paths(self):
        import app.db.repositories.user_learning_repo as mod
        src  = inspect.getsource(mod)
        tree = ast.parse(src)
        imported: list = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
        forbidden = [
            "forecast_repo", "similarity_repo", "scenario_repo", "decision_repo",
            "conviction_engine", "recommendation", "stance_engine",
            "order_engine", "execution_engine",
            "forecast_builder", "similarity_builder", "scenario_builder",
        ]
        violations = [n for n in imported if any(f in n.lower() for f in forbidden)]
        assert not violations, (
            f"user_learning_repo imports forbidden write-path modules: {violations}"
        )

    def test_repo_does_not_write_to_forecast_vector(self):
        import app.db.repositories.user_learning_repo as mod
        src = inspect.getsource(mod)
        # Should never reference forecast_vector as a write target
        assert "ForecastVector" not in src or "add_forecast" not in src, (
            "user_learning_repo appears to write to ForecastVector"
        )

    def test_repo_does_not_write_to_scenario_snapshot(self):
        import app.db.repositories.user_learning_repo as mod
        src = inspect.getsource(mod)
        assert "ScenarioSnapshot" not in src, (
            "user_learning_repo references ScenarioSnapshot — SP-7a violation"
        )

    def test_repo_does_not_write_to_decision_priority(self):
        import app.db.repositories.user_learning_repo as mod
        src = inspect.getsource(mod)
        assert "DecisionPriority" not in src, (
            "user_learning_repo references DecisionPriority — SP-7a violation"
        )


# ---------------------------------------------------------------------------
# 23. No advice/trade language in the repo
# ---------------------------------------------------------------------------

class TestNoAdviceLanguage:
    _ADVICE_PHRASES = [
        "buy", "sell", "hold", "recommendation", "target_price",
        "position_size", "trade", "execution", "forecast_override",
        "similarity_override", "scenario_override", "decision_override",
    ]

    def test_no_advice_phrases_in_repo_source(self):
        import app.db.repositories.user_learning_repo as mod
        src  = inspect.getsource(mod)
        tree = ast.parse(src)

        # Collect module-level docstring to exclude it from the scan
        docstring_nodes: set = set()

        def _mark_docstrings(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Module)):
                body = node.body
                if body and isinstance(body[0], ast.Expr):
                    val = body[0].value
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        docstring_nodes.add(id(val))
            for child in ast.iter_child_nodes(node):
                _mark_docstrings(child)

        _mark_docstrings(tree)

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstring_nodes:
                    continue
                val = node.value.lower()
                # Only flag strings long enough to be advice text
                if len(val) > 60:
                    for phrase in self._ADVICE_PHRASES:
                        if phrase in val:
                            violations.append((phrase, node.value[:80]))
        assert not violations, (
            f"Advice/trade phrases found in non-docstring string constants: {violations}"
        )


# ---------------------------------------------------------------------------
# 24. No source-table mutation during repo operations
# ---------------------------------------------------------------------------

class TestNoSourceTableMutation:
    @pytest.mark.asyncio
    async def test_repo_operations_do_not_mutate_source_tables(self, db):
        from sqlalchemy import select, func
        from app.db.models import ForecastVector, DecisionPriority, ScenarioSnapshot
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, upsert_learned_preference,
            add_preference_evidence, add_relevance_adjustment_log,
        )

        async def _counts():
            fv = (await db.execute(
                select(func.count()).select_from(ForecastVector))).scalar_one()
            dp = (await db.execute(
                select(func.count()).select_from(DecisionPriority))).scalar_one()
            ss = (await db.execute(
                select(func.count()).select_from(ScenarioSnapshot))).scalar_one()
            return fv, dp, ss

        before = await _counts()

        uid = _uid()
        ev = await add_user_signal_event(
            db, user_id=uid, signal_type="analysis_open",
        )
        pref = await upsert_learned_preference(
            db, user_id=uid, dimension="sector_interest", entity_key="semis",
        )
        await add_preference_evidence(
            db, preference_id=pref.id, signal_event_id=ev.id,
        )
        await add_relevance_adjustment_log(
            db, user_id=uid, surface="feed",
        )
        await db.commit()

        after = await _counts()
        assert before == after == (0, 0, 0), (
            f"Source-table row counts changed: {before} → {after}"
        )


# ---------------------------------------------------------------------------
# 25. Each add call creates a distinct row (append-only, no dedup)
# ---------------------------------------------------------------------------

class TestAppendOnlySemantics:
    @pytest.mark.asyncio
    async def test_signal_events_always_append(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event, count_user_signal_events,
        )
        uid = _uid()
        for _ in range(3):
            await add_user_signal_event(
                db, user_id=uid, signal_type="analysis_open", entity_key="NVDA",
            )
        await db.commit()
        n = await count_user_signal_events(db, user_id=uid)
        assert n == 3

    @pytest.mark.asyncio
    async def test_preference_evidence_always_appends(self, db):
        from app.db.repositories.user_learning_repo import (
            upsert_learned_preference, add_preference_evidence, count_preference_evidence,
        )
        uid = _uid()
        pref = await upsert_learned_preference(
            db, user_id=uid, dimension="company_interest", entity_key="NVDA",
        )
        await db.commit()
        for _ in range(4):
            await add_preference_evidence(
                db, preference_id=pref.id, signal_event_id=_uid(),
            )
        await db.commit()
        n = await count_preference_evidence(db, preference_id=pref.id)
        assert n == 4

    @pytest.mark.asyncio
    async def test_relevance_adjustment_log_always_appends(self, db):
        from app.db.repositories.user_learning_repo import (
            add_relevance_adjustment_log, count_relevance_adjustment_logs,
        )
        uid = _uid()
        for i in range(5):
            await add_relevance_adjustment_log(
                db, user_id=uid, surface="feed", item_ref=f"item-{i}",
            )
        await db.commit()
        n = await count_relevance_adjustment_logs(db, user_id=uid)
        assert n == 5
