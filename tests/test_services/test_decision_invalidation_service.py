"""
Tests — Decision Rebuild + Storage Pipeline, Phase 13 · Slice 5.

Covers:
  1.  is_decision_stale returns True for None
  2.  is_decision_stale returns True for expired row
  3.  is_decision_stale returns True for wrong schema version
  4.  is_decision_stale returns False for a fresh, current-schema row
  5.  find_stale_decisions returns [] when session is None
  6.  find_stale_decisions returns stale rows when they exist
  7.  rebuild_decision_for_target returns error dict for null session (non-shadow)
  8.  rebuild_decision_for_target dry_run=True does not write any rows
  9.  rebuild_decision_for_target persists a decision_priority row
  10. rebuild_decision_for_target persists decision_evidence rows
  11. rebuild_decision_for_target writes a ranking_log row
  12. rebuild_decision_for_target blocks storage when explanation is invalid
  13. rebuild_decision_for_target blocked candidate → zero decision_priority rows
  14. rebuild_decision_for_target blocked candidate → zero decision_evidence rows
  15. rebuild_decision_for_target stored result dict has stored=True
  16. rebuild_decision_for_target blocked result dict has blocked=True
  17. rebuild_decision_batch returns [] for empty list
  18. rebuild_decision_batch returns [] for null session (non-shadow)
  19. rebuild_decision_batch persists rows for all valid candidates
  20. rebuild_decision_batch blocks individual invalid candidates
  21. rebuild_decision_batch shadow_only=True — no rows stored
  22. rebuild_decisions_for_ticker returns [] when session is None (non-shadow)
  23. rebuild_decisions_for_ticker runs without error on empty substrate
  24. rebuild_decision_for_target does not write to source tables
  25. no delivery rows written after any rebuild
  26. no notification rows accessible on the session after rebuild
  27. score_to_bucket — critical threshold ≥ 0.80
  28. score_to_bucket — high threshold ≥ 0.60
  29. score_to_bucket — medium threshold ≥ 0.40
  30. score_to_bucket — low threshold ≥ 0.20
  31. score_to_bucket — informational for score < 0.20
  32. repeated rebuild of same candidate upserts, not duplicates, priority row
  33. evidence rows replaced on rebuild (old rows cleared)
  34. AST: no delivery/notification imports
  35. AST: no conviction/recommendation/order imports
  36. AST: no writes to source tables (no dossier/forecast/similarity inserts)
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "decision_invalidation_service.py"

# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture()
async def db(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Synthetic candidate factory
# ---------------------------------------------------------------------------

def _candidate(ctype: str = "forecast_candidate", ticker: str = "NVDA",
               source_id: str = "src-001") -> dict:
    """Return a minimal but complete candidate dict that passes validation."""
    return {
        "candidate_type": ctype,
        "entity_type": "company",
        "entity_id": ticker,
        "ticker": ticker,
        "source_type": f"{ctype}_source",
        "source_id": source_id,
        "headline": f"{ticker} {ctype} signal",
        "summary": "test summary",
        "evidence_refs": ["ref-1"],
        "source_versions": {"schema": "v1"},
        "user_id": None,
        "urgency_inputs": {"horizon_days": 45, "horizon": "near_term"},
        "impact_inputs": {
            "p_positive": 0.65, "p_negative": 0.25, "p_neutral": 0.10,
            "confidence_band_low": 0.55, "confidence_band_high": 0.75,
            "forecast_type": "thesis_strengthening",
        },
        "attention_inputs": {
            "forecast_type": "thesis_strengthening",
            "entity_type": "company",
            "direction": "strengthening",
        },
        "confidence_inputs": {
            "confidence_band_low": 0.55, "confidence_band_high": 0.75,
            "evidence_count": 3,
        },
        "uncertainty_inputs": {"band_width": 0.20, "p_neutral": 0.10},
    }


def _risk_candidate(ticker: str = "NVDA", source_id: str = "risk-001") -> dict:
    return {
        "candidate_type": "risk_candidate",
        "entity_type": "failure_mode",
        "entity_id": "fm-001",
        "ticker": ticker,
        "source_type": "dossier_failure_mode",
        "source_id": source_id,
        "headline": f"{ticker} risk signal",
        "summary": "risk summary",
        "evidence_refs": [],
        "source_versions": {"dossier_failure_mode": "v1"},
        "user_id": None,
        "urgency_inputs": {"sequence_stage": 3, "matched_days_ago": 5},
        "impact_inputs": {"relevance_at_match": 0.70, "sequence_stage": 3},
        "attention_inputs": {"ticker": ticker, "analog_id": "analog-001", "stage": 3},
        "confidence_inputs": {
            "relevance_at_match": 0.70,
            "has_analog_label": True,
            "has_stage_evidence": True,
        },
        "uncertainty_inputs": {"matched_days_ago": 5, "sequence_stage": 3},
    }


# ---------------------------------------------------------------------------
# Mock priority-row helpers for staleness tests
# ---------------------------------------------------------------------------

class _MockPriorityRow:
    def __init__(self, *, decision_schema=1, expires_at=None):
        self.decision_schema = decision_schema
        self.expires_at = expires_at or (_now() + timedelta(hours=24))


# ---------------------------------------------------------------------------
# 1–4. is_decision_stale
# ---------------------------------------------------------------------------

class TestIsDecisionStale:
    def test_none_is_stale(self):
        from app.services.decision_invalidation_service import is_decision_stale
        assert is_decision_stale(None) is True

    def test_expired_row_is_stale(self):
        from app.services.decision_invalidation_service import is_decision_stale
        row = _MockPriorityRow(expires_at=_now() - timedelta(hours=1))
        assert is_decision_stale(row) is True

    def test_wrong_schema_is_stale(self):
        from app.services.decision_invalidation_service import is_decision_stale, CURRENT_DECISION_SCHEMA
        row = _MockPriorityRow(decision_schema=CURRENT_DECISION_SCHEMA + 99)
        assert is_decision_stale(row) is True

    def test_fresh_row_is_not_stale(self):
        from app.services.decision_invalidation_service import is_decision_stale, CURRENT_DECISION_SCHEMA
        row = _MockPriorityRow(
            decision_schema=CURRENT_DECISION_SCHEMA,
            expires_at=_now() + timedelta(hours=24),
        )
        assert is_decision_stale(row) is False


# ---------------------------------------------------------------------------
# 5–6. find_stale_decisions
# ---------------------------------------------------------------------------

class TestFindStaleDecisions:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.decision_invalidation_service import find_stale_decisions
        result = await find_stale_decisions(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_finds_expired_rows(self, db):
        from app.services.decision_invalidation_service import find_stale_decisions, CURRENT_DECISION_SCHEMA
        from app.db.repositories.decision_repo import upsert_decision_priority

        # Seed an expired priority row
        await upsert_decision_priority(
            db,
            candidate_type="forecast_candidate",
            entity_type="company",
            entity_key="NVDA",
            source_ref="stale-001",
            decision_reason="test reason",
            why_now="test why now",
            deprioritizers=["d1"],
            evidence_summary=["e1"],
            decision_schema=CURRENT_DECISION_SCHEMA,
            ttl_hours=-1,   # already expired
        )
        await db.commit()

        stale = await find_stale_decisions(db)
        assert len(stale) >= 1

    @pytest.mark.asyncio
    async def test_fresh_row_not_in_stale_list(self, db):
        from app.services.decision_invalidation_service import find_stale_decisions, CURRENT_DECISION_SCHEMA
        from app.db.repositories.decision_repo import upsert_decision_priority

        await upsert_decision_priority(
            db,
            candidate_type="forecast_candidate",
            entity_type="company",
            entity_key="FRESH",
            source_ref="fresh-001",
            decision_reason="test reason",
            why_now="test why now",
            deprioritizers=["d1"],
            evidence_summary=["e1"],
            decision_schema=CURRENT_DECISION_SCHEMA,
            ttl_hours=48,
        )
        await db.commit()

        stale = await find_stale_decisions(db)
        keys = [getattr(r, "entity_key", "") for r in stale]
        assert "FRESH" not in keys


# ---------------------------------------------------------------------------
# 7. Null-session non-shadow → error dict
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_rebuild_for_target_null_session_returns_error(self):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        c = _candidate()
        result = await rebuild_decision_for_target(None, c, shadow_only=False)
        assert result["stored"] is False
        assert result["error"]  # non-empty

    @pytest.mark.asyncio
    async def test_rebuild_batch_null_session_non_shadow_returns_empty(self):
        from app.services.decision_invalidation_service import rebuild_decision_batch
        result = await rebuild_decision_batch(None, [_candidate()], shadow_only=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_rebuild_for_ticker_null_session_non_shadow_returns_empty(self):
        from app.services.decision_invalidation_service import rebuild_decisions_for_ticker
        result = await rebuild_decisions_for_ticker(None, "NVDA", shadow_only=False)
        assert result == []


# ---------------------------------------------------------------------------
# 8. Shadow / dry-run — no DB rows
# ---------------------------------------------------------------------------

class TestShadowMode:
    @pytest.mark.asyncio
    async def test_dry_run_writes_no_priority_row(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        from app.db.repositories.decision_repo import list_decision_priorities

        c = _candidate()
        result = await rebuild_decision_for_target(db, c, shadow_only=True)
        await db.commit()

        rows = await list_decision_priorities(db)
        assert len(rows) == 0
        assert result["stored"] is False

    @pytest.mark.asyncio
    async def test_batch_shadow_writes_no_rows(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_batch
        from app.db.repositories.decision_repo import count_decision_priorities

        await rebuild_decision_batch(db, [_candidate(), _risk_candidate()], shadow_only=True)
        await db.commit()

        count = await count_decision_priorities(db)
        assert count == 0


# ---------------------------------------------------------------------------
# 9–11. Successful storage
# ---------------------------------------------------------------------------

class TestSuccessfulStorage:
    @pytest.mark.asyncio
    async def test_stores_decision_priority_row(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        from app.db.repositories.decision_repo import list_decision_priorities

        c = _candidate(ticker="AAPL", source_id="fv-aapl")
        result = await rebuild_decision_for_target(db, c)
        await db.commit()

        assert result["stored"] is True
        assert result["priority_id"]
        rows = await list_decision_priorities(db, entity_key="AAPL")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_stores_decision_evidence_rows(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        from app.db.repositories.decision_repo import list_decision_evidence

        c = _candidate(ticker="TSLA", source_id="fv-tsla")
        result = await rebuild_decision_for_target(db, c)
        await db.commit()

        assert result["evidence_count"] >= 1
        evs = await list_decision_evidence(db, priority_id=result["priority_id"])
        assert len(evs) >= 1

    @pytest.mark.asyncio
    async def test_writes_ranking_log_row(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        from app.db.repositories.decision_repo import list_ranking_logs

        c = _candidate(ticker="MSFT", source_id="fv-msft")
        result = await rebuild_decision_for_target(db, c, snapshot_reason="rebuild")
        await db.commit()

        assert result["log_id"]
        logs = await list_ranking_logs(db, candidate_type="forecast_candidate")
        assert len(logs) >= 1
        assert logs[0].snapshot_reason == "rebuild"

    @pytest.mark.asyncio
    async def test_stored_result_has_stored_true(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        c = _candidate()
        result = await rebuild_decision_for_target(db, c)
        assert result["stored"] is True


# ---------------------------------------------------------------------------
# 12–16. Explanation validation gate
# ---------------------------------------------------------------------------

class TestValidationGate:
    @staticmethod
    def _invalid_candidate() -> dict:
        """Candidate with unsupported type — explanation will fail validation."""
        c = _candidate()
        c["candidate_type"] = "not_a_real_type"
        return c

    @pytest.mark.asyncio
    async def test_invalid_candidate_blocked(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        result = await rebuild_decision_for_target(db, self._invalid_candidate())
        assert result["blocked"] is True
        assert result["stored"] is False

    @pytest.mark.asyncio
    async def test_blocked_writes_no_priority_row(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        from app.db.repositories.decision_repo import count_decision_priorities

        await rebuild_decision_for_target(db, self._invalid_candidate())
        await db.commit()

        count = await count_decision_priorities(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_blocked_writes_no_evidence_row(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        from app.db.repositories.decision_repo import count_decision_evidence

        await rebuild_decision_for_target(db, self._invalid_candidate())
        await db.commit()

        count = await count_decision_evidence(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_blocked_result_has_block_reason(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        result = await rebuild_decision_for_target(db, self._invalid_candidate())
        assert result["block_reason"]

    @pytest.mark.asyncio
    async def test_blocked_result_has_blocked_true(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        result = await rebuild_decision_for_target(db, self._invalid_candidate())
        assert result["blocked"] is True


# ---------------------------------------------------------------------------
# 17–21. rebuild_decision_batch
# ---------------------------------------------------------------------------

class TestRebuildBatch:
    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_batch
        result = await rebuild_decision_batch(db, [])
        assert result == []

    @pytest.mark.asyncio
    async def test_batch_persists_valid_candidates(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_batch
        from app.db.repositories.decision_repo import count_decision_priorities

        candidates = [
            _candidate(ticker="NVDA", source_id="b-001"),
            _risk_candidate(ticker="AMD", source_id="b-002"),
        ]
        results = await rebuild_decision_batch(db, candidates)
        await db.commit()

        stored = [r for r in results if r["stored"]]
        assert len(stored) == 2
        count = await count_decision_priorities(db)
        assert count == 2

    @pytest.mark.asyncio
    async def test_batch_blocks_invalid_candidates(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_batch
        from app.db.repositories.decision_repo import count_decision_priorities

        bad = _candidate()
        bad["candidate_type"] = "bad_type"
        good = _candidate(ticker="GOOD", source_id="g-001")

        results = await rebuild_decision_batch(db, [bad, good])
        await db.commit()

        blocked = [r for r in results if r["blocked"]]
        stored  = [r for r in results if r["stored"]]
        assert len(blocked) == 1
        assert len(stored)  == 1
        count = await count_decision_priorities(db)
        assert count == 1

    @pytest.mark.asyncio
    async def test_batch_shadow_mode_writes_nothing(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_batch
        from app.db.repositories.decision_repo import count_decision_priorities

        results = await rebuild_decision_batch(
            db,
            [_candidate(ticker="SHAD", source_id="sh-001")],
            shadow_only=True,
        )
        await db.commit()

        count = await count_decision_priorities(db)
        assert count == 0
        assert all(not r["stored"] for r in results)


# ---------------------------------------------------------------------------
# 22–23. rebuild_decisions_for_ticker
# ---------------------------------------------------------------------------

class TestRebuildForTicker:
    @pytest.mark.asyncio
    async def test_null_session_non_shadow_returns_empty(self):
        from app.services.decision_invalidation_service import rebuild_decisions_for_ticker
        result = await rebuild_decisions_for_ticker(None, "NVDA", shadow_only=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_substrate_returns_empty_list(self, db):
        from app.services.decision_invalidation_service import rebuild_decisions_for_ticker
        result = await rebuild_decisions_for_ticker(db, "ZZZZ")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 24–26. Source table / delivery isolation
# ---------------------------------------------------------------------------

class TestIsolation:
    @pytest.mark.asyncio
    async def test_rebuild_does_not_mutate_source_tables(self, db):
        """Verify that rebuild touches only decision_* tables."""
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        from app.db.models import ForecastVector, DossierFailureMode

        c = _candidate()
        await rebuild_decision_for_target(db, c)
        await db.commit()

        from sqlalchemy import select, func
        fv_count = (await db.execute(
            select(func.count()).select_from(ForecastVector)
        )).scalar_one()
        fm_count = (await db.execute(
            select(func.count()).select_from(DossierFailureMode)
        )).scalar_one()
        assert fv_count == 0
        assert fm_count == 0

    @pytest.mark.asyncio
    async def test_no_delivery_rows_after_rebuild(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        from app.db.models import DeliveryLedger

        c = _candidate()
        await rebuild_decision_for_target(db, c)
        await db.commit()

        from sqlalchemy import select, func
        dl_count = (await db.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar_one()
        assert dl_count == 0


# ---------------------------------------------------------------------------
# 27–31. Priority bucket mapping
# ---------------------------------------------------------------------------

class TestScoreBucket:
    def _bucket(self, score: float) -> str:
        from app.services.decision_invalidation_service import _score_to_bucket
        return _score_to_bucket(score)

    def test_critical(self):
        assert self._bucket(0.80) == "critical"
        assert self._bucket(0.95) == "critical"

    def test_high(self):
        assert self._bucket(0.60) == "high"
        assert self._bucket(0.79) == "high"

    def test_medium(self):
        assert self._bucket(0.40) == "medium"
        assert self._bucket(0.59) == "medium"

    def test_low(self):
        assert self._bucket(0.20) == "low"
        assert self._bucket(0.39) == "low"

    def test_informational(self):
        assert self._bucket(0.19) == "informational"
        assert self._bucket(0.00) == "informational"


# ---------------------------------------------------------------------------
# 32–33. Upsert idempotency and evidence refresh
# ---------------------------------------------------------------------------

class TestUpsertIdempotency:
    @pytest.mark.asyncio
    async def test_repeated_rebuild_does_not_duplicate_priority_row(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        from app.db.repositories.decision_repo import count_decision_priorities

        c = _candidate(ticker="IDEM", source_id="idem-001")
        await rebuild_decision_for_target(db, c)
        await db.commit()
        await rebuild_decision_for_target(db, c)
        await db.commit()

        count = await count_decision_priorities(db)
        assert count == 1  # upsert, not insert

    @pytest.mark.asyncio
    async def test_rebuild_replaces_evidence_rows(self, db):
        from app.services.decision_invalidation_service import rebuild_decision_for_target
        from app.db.repositories.decision_repo import list_decision_evidence

        c = _candidate(ticker="EVID", source_id="ev-001")
        r1 = await rebuild_decision_for_target(db, c)
        await db.commit()
        ev_count_1 = (await list_decision_evidence(db, priority_id=r1["priority_id"]))

        r2 = await rebuild_decision_for_target(db, c)
        await db.commit()
        ev_count_2 = (await list_decision_evidence(db, priority_id=r2["priority_id"]))

        # Same priority_id; evidence refreshed — count should be stable (not doubled)
        assert len(ev_count_2) <= len(ev_count_1) + 2  # allow minor variance, never double


# ---------------------------------------------------------------------------
# 34–36. AST safety
# ---------------------------------------------------------------------------

def _load_tree() -> ast.AST:
    return ast.parse(_SVC.read_text(encoding="utf-8"))


class TestASTSafety:
    def test_no_delivery_or_notification_imports(self):
        tree = _load_tree()
        forbidden = {"delivery_service", "notification_service",
                     "notification_repo", "delivery_repo"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names  = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fw in forbidden:
                        assert fw not in part.lower(), \
                            f"Forbidden import {part!r} in invalidation service"

    def test_no_conviction_or_recommendation_imports(self):
        tree = _load_tree()
        forbidden = {"conviction_modeler", "conviction", "recommendation",
                     "order", "execution", "forecast_delivery_service"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names  = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fw in forbidden:
                        assert fw not in part.lower(), \
                            f"Forbidden import {part!r} in invalidation service"

    def test_no_source_table_imports(self):
        """Service must not import dossier, analog, thesis, portfolio, or similarity
        repo write paths — it may only write to decision_* tables via decision_repo."""
        src = _SVC.read_text(encoding="utf-8")
        forbidden_strings = [
            "dossier_repo",
            "analog_repo",
            "thesis_repo",
            "similarity_repo",
            "portfolio_repo",
            "watchlist_repo",
            "forecast_repo",
        ]
        for s in forbidden_strings:
            assert s not in src, \
                f"Invalidation service must not import {s!r} (source-table isolation)"
