"""
Tests — Decision Observability Service, Phase 13 · Slice 10.

Covers:
  1.  build_decision_observability_snapshot — null session returns safe empty dict
  2.  build_decision_observability_snapshot — all required keys present
  3.  build_decision_observability_snapshot — db_available=False on null session
  4.  build_decision_observability_snapshot — db_available=True on live session
  5.  build_decision_observability_snapshot — empty DB: all counts are 0
  6.  build_decision_observability_snapshot — populated: priority_count reflects rows
  7.  build_decision_observability_snapshot — priority_count_by_bucket correct
  8.  build_decision_observability_snapshot — priority_count_by_type correct
  9.  build_decision_observability_snapshot — shadow_delivery_count reflects ledger
  10. build_decision_observability_snapshot — shadow_escalated_count=0 on clean DB
  11. build_decision_observability_snapshot — live_notification_count=0 (no decision kind)
  12. build_decision_observability_snapshot — safe_state=True on default flags
  13. build_decision_observability_snapshot — safe_state=False when delivery_enabled=True
  14. build_decision_observability_snapshot — no secret/payload fields in snapshot
  15. build_decision_observability_snapshot — snapshot_utc present and non-empty
  16. build_decision_observability_snapshot — latest_priority_at populated after row
  17. build_decision_observability_snapshot — calibration_outcome_count reflects log rows
  18. build_decision_observability_snapshot — never raises (exception → degraded snapshot)
  19. flags section always present even on config error
  20. AST: no write calls in observability service
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import timezone, datetime
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Path
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "decision_observability_service.py"

_REQUIRED_KEYS = {
    "flags",
    "db_available",
    "priority_count",
    "evidence_count",
    "ranking_log_count",
    "calibration_outcome_count",
    "expired_priority_count",
    "priority_count_by_bucket",
    "priority_count_by_type",
    "shadow_delivery_count",
    "shadow_escalated_count",
    "live_notification_count",
    "latest_priority_at",
    "latest_calibration_at",
    "safe_state",
    "snapshot_utc",
}

_SECRET_TERMS = {
    "secret", "password", "token", "api_key", "private_key",
    "stripe", "payload", "raw", "prompt",
}

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


async def _seed_priority(db, ticker: str = "NVDA", bucket: str = "medium",
                         ctype: str = "forecast_candidate", score: float = 0.55):
    from app.db.repositories.decision_repo import upsert_decision_priority
    return await upsert_decision_priority(
        db,
        candidate_type      = ctype,
        entity_type         = "company",
        entity_key          = ticker,
        source_ref          = f"src-{_uid()[:8]}",
        decision_priority   = bucket,
        decision_rank_score = score,
        attention_score     = 0.55,
        urgency_score       = 0.55,
        impact_score        = 0.55,
        confidence_score    = 0.70,
        uncertainty_score   = 0.85,
        decision_reason     = "Signal is significant.",
        why_now             = "Horizon is near-term.",
        deprioritizers      = ["Low evidence."],
        evidence_summary    = ["Source: forecast_vector."],
        decision_schema     = 1,
        user_id             = None,
        ttl_hours           = 24,
    )


# ---------------------------------------------------------------------------
# 1–5. Null session / empty DB
# ---------------------------------------------------------------------------

class TestNullSessionAndEmpty:
    @pytest.mark.asyncio
    async def test_null_session_returns_dict(self):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        result = await build_decision_observability_snapshot(None)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_all_required_keys_present_null_session(self):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        result = await build_decision_observability_snapshot(None)
        missing = _REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Missing keys: {missing}"

    @pytest.mark.asyncio
    async def test_db_available_false_on_null_session(self):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        result = await build_decision_observability_snapshot(None)
        assert result["db_available"] is False

    @pytest.mark.asyncio
    async def test_db_available_true_on_live_session(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        result = await build_decision_observability_snapshot(db)
        assert result["db_available"] is True

    @pytest.mark.asyncio
    async def test_empty_db_all_counts_zero(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        result = await build_decision_observability_snapshot(db)
        assert result["priority_count"] == 0
        assert result["evidence_count"] == 0
        assert result["ranking_log_count"] == 0
        assert result["shadow_delivery_count"] == 0
        assert result["shadow_escalated_count"] == 0
        assert result["live_notification_count"] == 0


# ---------------------------------------------------------------------------
# 6–9. Populated DB counts
# ---------------------------------------------------------------------------

class TestPopulatedCounts:
    @pytest.mark.asyncio
    async def test_priority_count_reflects_rows(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        await _seed_priority(db, ticker="NVDA", bucket="high")
        await _seed_priority(db, ticker="AAPL", bucket="medium")
        await db.commit()
        result = await build_decision_observability_snapshot(db)
        assert result["priority_count"] >= 2

    @pytest.mark.asyncio
    async def test_priority_count_by_bucket_correct(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        await _seed_priority(db, ticker="NVDA", bucket="critical")
        await _seed_priority(db, ticker="AAPL", bucket="critical")
        await _seed_priority(db, ticker="MSFT", bucket="high")
        await db.commit()
        result = await build_decision_observability_snapshot(db)
        by_bucket = result["priority_count_by_bucket"]
        assert by_bucket["critical"] >= 2
        assert by_bucket["high"] >= 1
        # All buckets present
        for b in ("critical", "high", "medium", "low", "informational"):
            assert b in by_bucket

    @pytest.mark.asyncio
    async def test_priority_count_by_type_correct(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        await _seed_priority(db, ticker="NVDA", ctype="forecast_candidate")
        await _seed_priority(db, ticker="AAPL", ctype="risk_candidate")
        await db.commit()
        result = await build_decision_observability_snapshot(db)
        by_type = result["priority_count_by_type"]
        assert by_type["forecast_candidate"] >= 1
        assert by_type["risk_candidate"] >= 1

    @pytest.mark.asyncio
    async def test_shadow_delivery_count_reflects_ledger(self, db):
        from app.services.decision_observability_service import (
            build_decision_observability_snapshot, DECISION_DELIVERY_CHANNEL,
        )
        from app.services.loop_idempotency_service import build_payload_hash, guard_delivery
        payload_hash = build_payload_hash({"entity": "NVDA", "transition": "first_priority"})
        await guard_delivery(
            db,
            user_id="system",
            channel=DECISION_DELIVERY_CHANNEL,
            target_key="company:NVDA:forecast_candidate",
            payload_hash=payload_hash,
        )
        await db.commit()
        result = await build_decision_observability_snapshot(db)
        assert result["shadow_delivery_count"] >= 1


# ---------------------------------------------------------------------------
# 10–15. Safety and safe_state
# ---------------------------------------------------------------------------

class TestSafeState:
    @pytest.mark.asyncio
    async def test_shadow_escalated_count_zero_on_clean_db(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        result = await build_decision_observability_snapshot(db)
        assert result["shadow_escalated_count"] == 0

    @pytest.mark.asyncio
    async def test_live_notification_count_zero(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        result = await build_decision_observability_snapshot(db)
        assert result["live_notification_count"] == 0

    @pytest.mark.asyncio
    async def test_safe_state_true_on_default_flags(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        result = await build_decision_observability_snapshot(db)
        # With all defaults (shadow=True, delivery_enabled=False, no escalations),
        # safe_state must be True
        assert result["safe_state"] is True

    @pytest.mark.asyncio
    async def test_safe_state_false_when_delivery_enabled(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        # Patch settings to simulate decision_delivery_enabled=True
        mock_settings = MagicMock()
        mock_settings.decision_build_enabled       = False
        mock_settings.decision_scoring_enabled     = False
        mock_settings.decision_delivery_enabled    = True   # unsafe
        mock_settings.decision_shadow              = True
        mock_settings.decision_targets_enabled     = ""
        mock_settings.decision_calibration_enabled = False
        with patch("app.services.decision_observability_service._flags_section",
                   return_value={
                       "decision_build_enabled":       False,
                       "decision_scoring_enabled":     False,
                       "decision_delivery_enabled":    True,
                       "decision_shadow":              True,
                       "decision_targets_enabled":     "",
                       "decision_calibration_enabled": False,
                   }):
            result = await build_decision_observability_snapshot(db)
        assert result["safe_state"] is False

    @pytest.mark.asyncio
    async def test_no_secret_fields_in_snapshot(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        result = await build_decision_observability_snapshot(db)

        def _check_dict(d: dict, path: str = ""):
            for k, v in d.items():
                full_key = f"{path}.{k}" if path else k
                assert not any(s in k.lower() for s in _SECRET_TERMS), \
                    f"Secret-sounding key {full_key!r} in snapshot"
                if isinstance(v, dict):
                    _check_dict(v, full_key)
                elif isinstance(v, str) and len(v) > 4:
                    assert not any(s in v.lower() for s in _SECRET_TERMS), \
                        f"Secret-sounding value at {full_key!r}: {v!r}"

        _check_dict(result)

    @pytest.mark.asyncio
    async def test_snapshot_utc_present_and_non_empty(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        result = await build_decision_observability_snapshot(db)
        assert result["snapshot_utc"]
        assert "T" in result["snapshot_utc"]


# ---------------------------------------------------------------------------
# 16–18. Timestamps and robustness
# ---------------------------------------------------------------------------

class TestTimestampsAndRobustness:
    @pytest.mark.asyncio
    async def test_latest_priority_at_populated_after_row(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        await _seed_priority(db, ticker="NVDA")
        await db.commit()
        result = await build_decision_observability_snapshot(db)
        assert result["latest_priority_at"] is not None
        assert "T" in result["latest_priority_at"]

    @pytest.mark.asyncio
    async def test_calibration_outcome_count_reflects_log_rows(self, db):
        from app.services.decision_observability_service import build_decision_observability_snapshot
        from app.services.decision_calibration_service import record_decision_outcome
        pid = _uid()
        await record_decision_outcome(db, priority_id=pid, realized_significance="material")
        await record_decision_outcome(db, priority_id=pid, realized_significance="immaterial")
        await db.commit()
        result = await build_decision_observability_snapshot(db)
        assert result["calibration_outcome_count"] >= 2

    @pytest.mark.asyncio
    async def test_never_raises_on_bad_session(self):
        from app.services.decision_observability_service import build_decision_observability_snapshot

        class BrokenSession:
            async def execute(self, *a, **kw):
                raise RuntimeError("DB is down")

        result = await build_decision_observability_snapshot(BrokenSession())
        # Must return a degraded dict, not raise
        assert isinstance(result, dict)
        assert result["db_available"] is False


# ---------------------------------------------------------------------------
# 19–20. Flags robustness and AST
# ---------------------------------------------------------------------------

class TestFlagsAndAST:
    def test_flags_section_always_returns_dict(self):
        from app.services.decision_observability_service import _flags_section
        result = _flags_section()
        assert isinstance(result, dict)
        for key in (
            "decision_build_enabled", "decision_scoring_enabled",
            "decision_delivery_enabled", "decision_shadow",
            "decision_targets_enabled", "decision_calibration_enabled",
        ):
            assert key in result

    def test_no_write_calls_in_observability(self):
        src = _SVC.read_text(encoding="utf-8")
        for forbidden in (
            "session.add(",
            "session.delete(",
            ".update(",
            "session.flush(",
            "session.commit(",
        ):
            assert forbidden not in src, f"Write call {forbidden!r} found in observability service"
