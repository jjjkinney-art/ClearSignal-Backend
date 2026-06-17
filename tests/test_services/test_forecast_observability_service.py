"""
Tests — Forecast Observability Service, Phase 12 · Slice 9.

Covers:
  1.  Snapshot shape — all required top-level keys present
  2.  Snapshot flags section — all 6 forecast_* keys present
  3.  Null-session returns empty snapshot with safe_state=True
  4.  Null-session db_available=False
  5.  DB-up snapshot has db_available=True
  6.  safe_state=True on clean DB (all flags at inert defaults)
  7.  safe_state=False when forecast_delivery_enabled=True
  8.  safe_state=False when shadow_escalated_count > 0
  9.  safe_state=False when live_notification_count > 0
  10. vector_count reflects actual forecast_vector rows
  11. evidence_count reflects actual forecast_evidence rows
  12. calibration_count reflects actual forecast_calibration_log rows
  13. expired_vector_count counts only expired rows
  14. vector_count_by_type bucketed correctly
  15. vector_count_by_horizon bucketed correctly
  16. shadow_delivery_count counts only forecast_shadow channel rows
  17. shadow_escalated_count counts only delivered rows in that channel
  18. live_notification_count counts only kind="forecast" rows
  19. latest_forecast_at is None on empty DB; ISO-8601 when rows exist
  20. latest_calibration_at is None on empty DB; ISO-8601 when rows exist
  21. DB-down degrades to zero counts (exception path)
  22. Never raises (exception always absorbed)
  23. Read-only: no ForecastVector rows written by snapshot (AST)
  24. No conviction/delivery-service/notification-service imports (AST)
  25. snapshot_utc present and ISO-8601 formatted
  26. Admin route delegating to observability service (structure check)
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "forecast_observability_service.py"

# ---------------------------------------------------------------------------
# Fixtures
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

async def _seed_vector(
    db,
    *,
    ticker: str = "AAPL",
    forecast_type: str = "thesis_strengthening",
    horizon: str = "near_term",
    expires_at: datetime | None = None,
):
    from app.db.models import ForecastVector
    now = _now()
    row = ForecastVector(
        id=_uid(),
        entity_type="company",
        entity_key=ticker,
        forecast_type=forecast_type,
        horizon=horizon,
        horizon_days=30,
        p_positive=0.60,
        p_negative=0.20,
        p_neutral=0.20,
        confidence_band_low=0.40,
        confidence_band_high=0.80,
        why="Thesis is strengthening",
        invalidators=["revenue misses", "mgmt change"],
        built_at=now,
        expires_at=expires_at or (now + timedelta(hours=24)),
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_evidence(db, vector_id: str):
    from app.db.models import ForecastEvidence
    row = ForecastEvidence(
        id=_uid(),
        forecast_id=vector_id,
        source_type="historical_analog",
        source_id="analog-001",
        direction="bullish",
        contribution=0.05,
        weight=0.8,
        description="Revenue grew 12% YoY",
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_calibration_log(db):
    from app.db.models import ForecastCalibrationLog
    now = _now()
    row = ForecastCalibrationLog(
        id=_uid(),
        forecast_id="fid-001",
        entity_type="company",
        entity_key="AAPL",
        horizon="near_term",
        forecast_type="thesis_strengthening",
        p_positive_at_forecast=0.70,
        p_negative_at_forecast=0.20,
        p_neutral_at_forecast=0.10,
        actual_outcome="positive",
        brier_score=0.09,
        evaluation_source="thesis_state_change",
        evaluated_at=now,
        created_at=now,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_shadow_ledger(db, status: str = "pending"):
    from app.db.models import DeliveryLedger
    row = DeliveryLedger(
        content_key=_uid()[:64],
        target_key="company:AAPL:thesis_strengthening:30",
        channel="forecast_shadow",
        content_hash=_uid()[:64],
        status=status,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_notification(db, kind: str = "forecast"):
    from app.db.models import Notification
    row = Notification(
        id=_uid(),
        user_id="user-001",
        kind=kind,
        body_json={"text": "Test notification"},
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# 1–2: Snapshot shape
# ---------------------------------------------------------------------------

class TestSnapshotShape:
    @pytest.mark.asyncio
    async def test_all_top_level_keys_present(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        snap = await build_forecast_observability_snapshot(db)
        required = {
            "flags", "db_available", "vector_count", "evidence_count",
            "calibration_count", "expired_vector_count",
            "vector_count_by_type", "vector_count_by_horizon",
            "shadow_delivery_count", "shadow_escalated_count",
            "live_notification_count", "latest_forecast_at",
            "latest_calibration_at", "safe_state", "snapshot_utc",
        }
        missing = required - set(snap.keys())
        assert not missing, f"Missing keys: {missing}"

    @pytest.mark.asyncio
    async def test_flags_section_has_all_keys(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        snap = await build_forecast_observability_snapshot(db)
        flags = snap["flags"]
        required_flags = {
            "forecast_build_enabled", "forecast_scoring_enabled",
            "forecast_delivery_enabled", "forecast_shadow",
            "forecast_targets_enabled", "forecast_calibration_enabled",
        }
        missing = required_flags - set(flags.keys())
        assert not missing, f"Missing flag keys: {missing}"

    @pytest.mark.asyncio
    async def test_vector_count_by_type_keys_present(self, db):
        from app.services.forecast_observability_service import (
            build_forecast_observability_snapshot, _FORECAST_TYPES,
        )
        snap = await build_forecast_observability_snapshot(db)
        for ft in _FORECAST_TYPES:
            assert ft in snap["vector_count_by_type"]

    @pytest.mark.asyncio
    async def test_vector_count_by_horizon_keys_present(self, db):
        from app.services.forecast_observability_service import (
            build_forecast_observability_snapshot, _HORIZONS,
        )
        snap = await build_forecast_observability_snapshot(db)
        for hz in _HORIZONS:
            assert hz in snap["vector_count_by_horizon"]


# ---------------------------------------------------------------------------
# 3–5: Null-session safety and db_available
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_null_session_returns_dict(self):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        result = await build_forecast_observability_snapshot(None)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_null_session_safe_state_true(self):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        result = await build_forecast_observability_snapshot(None)
        assert result["safe_state"] is True

    @pytest.mark.asyncio
    async def test_null_session_db_available_false(self):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        result = await build_forecast_observability_snapshot(None)
        assert result["db_available"] is False

    @pytest.mark.asyncio
    async def test_null_session_zero_counts(self):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        result = await build_forecast_observability_snapshot(None)
        for key in ("vector_count", "evidence_count", "calibration_count",
                    "shadow_delivery_count", "shadow_escalated_count",
                    "live_notification_count", "expired_vector_count"):
            assert result[key] == 0, f"{key} should be 0 for null session"

    @pytest.mark.asyncio
    async def test_db_up_returns_db_available_true(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        result = await build_forecast_observability_snapshot(db)
        assert result["db_available"] is True


# ---------------------------------------------------------------------------
# 6–9: safe_state logic
# ---------------------------------------------------------------------------

class TestSafeState:
    @pytest.mark.asyncio
    async def test_safe_state_true_on_clean_db(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        snap = await build_forecast_observability_snapshot(db)
        assert snap["safe_state"] is True

    @pytest.mark.asyncio
    async def test_safe_state_false_when_delivery_enabled(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        with patch("app.config.settings") as mock_settings:
            mock_settings.forecast_build_enabled     = False
            mock_settings.forecast_scoring_enabled   = False
            mock_settings.forecast_delivery_enabled  = True   # <-- delivery on
            mock_settings.forecast_shadow            = True
            mock_settings.forecast_targets_enabled   = ""
            mock_settings.forecast_calibration_enabled = False
            snap = await build_forecast_observability_snapshot(db)
        assert snap["safe_state"] is False

    @pytest.mark.asyncio
    async def test_safe_state_false_when_shadow_escalated(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_shadow_ledger(db, status="delivered")  # escalated!
        snap = await build_forecast_observability_snapshot(db)
        assert snap["safe_state"] is False

    @pytest.mark.asyncio
    async def test_safe_state_false_when_forecast_notification_exists(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_notification(db, kind="forecast")
        snap = await build_forecast_observability_snapshot(db)
        assert snap["safe_state"] is False


# ---------------------------------------------------------------------------
# 10–15: Counts reflect actual rows
# ---------------------------------------------------------------------------

class TestCounts:
    @pytest.mark.asyncio
    async def test_vector_count(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_vector(db, ticker="AAPL")
        await _seed_vector(db, ticker="MSFT")
        snap = await build_forecast_observability_snapshot(db)
        assert snap["vector_count"] == 2

    @pytest.mark.asyncio
    async def test_evidence_count(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        row = await _seed_vector(db)
        await _seed_evidence(db, row.id)
        await _seed_evidence(db, row.id)
        snap = await build_forecast_observability_snapshot(db)
        assert snap["evidence_count"] == 2

    @pytest.mark.asyncio
    async def test_calibration_count(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_calibration_log(db)
        snap = await build_forecast_observability_snapshot(db)
        assert snap["calibration_count"] == 1

    @pytest.mark.asyncio
    async def test_expired_vector_count(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        past = _now() - timedelta(hours=2)
        await _seed_vector(db, ticker="AAPL", expires_at=past)   # expired
        await _seed_vector(db, ticker="MSFT")                    # not expired
        snap = await build_forecast_observability_snapshot(db)
        assert snap["expired_vector_count"] == 1
        assert snap["vector_count"] == 2

    @pytest.mark.asyncio
    async def test_vector_count_by_type(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_vector(db, forecast_type="thesis_strengthening")
        await _seed_vector(db, forecast_type="thesis_strengthening", ticker="MSFT")
        await _seed_vector(db, forecast_type="risk_escalation")
        snap = await build_forecast_observability_snapshot(db)
        by_type = snap["vector_count_by_type"]
        assert by_type["thesis_strengthening"] == 2
        assert by_type["risk_escalation"] == 1
        assert by_type["risk_resolution"] == 0

    @pytest.mark.asyncio
    async def test_vector_count_by_horizon(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_vector(db, horizon="near_term")
        await _seed_vector(db, horizon="near_term", ticker="MSFT")
        await _seed_vector(db, horizon="long_term", ticker="GOOG")
        snap = await build_forecast_observability_snapshot(db)
        by_hz = snap["vector_count_by_horizon"]
        assert by_hz["near_term"] == 2
        assert by_hz["long_term"] == 1
        assert by_hz["medium_term"] == 0


# ---------------------------------------------------------------------------
# 16–18: Delivery + notification counts
# ---------------------------------------------------------------------------

class TestDeliveryAndNotificationCounts:
    @pytest.mark.asyncio
    async def test_shadow_delivery_count(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_shadow_ledger(db, status="pending")
        await _seed_shadow_ledger(db, status="pending")
        snap = await build_forecast_observability_snapshot(db)
        assert snap["shadow_delivery_count"] == 2

    @pytest.mark.asyncio
    async def test_shadow_escalated_count(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_shadow_ledger(db, status="pending")
        await _seed_shadow_ledger(db, status="delivered")  # escalated
        snap = await build_forecast_observability_snapshot(db)
        assert snap["shadow_delivery_count"] == 2
        assert snap["shadow_escalated_count"] == 1

    @pytest.mark.asyncio
    async def test_other_channel_not_counted(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        from app.db.models import DeliveryLedger
        # Seed a row in a different channel
        row = DeliveryLedger(
            content_key=_uid()[:64],
            target_key="test",
            channel="similarity_shadow",
            content_hash=_uid()[:64],
            status="pending",
        )
        db.add(row)
        await db.flush()
        snap = await build_forecast_observability_snapshot(db)
        assert snap["shadow_delivery_count"] == 0

    @pytest.mark.asyncio
    async def test_live_notification_count_only_forecast_kind(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_notification(db, kind="similarity")  # different kind
        await _seed_notification(db, kind="alert")
        snap = await build_forecast_observability_snapshot(db)
        assert snap["live_notification_count"] == 0

    @pytest.mark.asyncio
    async def test_live_notification_count_counts_forecast_kind(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_notification(db, kind="forecast")
        snap = await build_forecast_observability_snapshot(db)
        assert snap["live_notification_count"] == 1


# ---------------------------------------------------------------------------
# 19–20: Timestamps
# ---------------------------------------------------------------------------

class TestTimestamps:
    @pytest.mark.asyncio
    async def test_latest_forecast_at_none_when_empty(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        snap = await build_forecast_observability_snapshot(db)
        assert snap["latest_forecast_at"] is None

    @pytest.mark.asyncio
    async def test_latest_forecast_at_iso8601_when_rows_exist(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_vector(db)
        snap = await build_forecast_observability_snapshot(db)
        assert snap["latest_forecast_at"] is not None
        # Should be ISO-8601: "YYYY-MM-DDTHH:MM:SSZ"
        assert "T" in snap["latest_forecast_at"]
        assert snap["latest_forecast_at"].endswith("Z")

    @pytest.mark.asyncio
    async def test_latest_calibration_at_none_when_empty(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        snap = await build_forecast_observability_snapshot(db)
        assert snap["latest_calibration_at"] is None

    @pytest.mark.asyncio
    async def test_latest_calibration_at_iso8601_when_rows_exist(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        await _seed_calibration_log(db)
        snap = await build_forecast_observability_snapshot(db)
        assert snap["latest_calibration_at"] is not None
        assert "T" in snap["latest_calibration_at"]

    @pytest.mark.asyncio
    async def test_snapshot_utc_present(self, db):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        snap = await build_forecast_observability_snapshot(db)
        assert snap.get("snapshot_utc") is not None
        assert "T" in snap["snapshot_utc"]
        assert snap["snapshot_utc"].endswith("Z")


# ---------------------------------------------------------------------------
# 21–22: DB-down degradation + never-raises
# ---------------------------------------------------------------------------

class TestDegradation:
    @pytest.mark.asyncio
    async def test_db_down_returns_empty_snapshot(self):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot
        # null session is the standard DB-down path
        snap = await build_forecast_observability_snapshot(None)
        assert snap["db_available"] is False
        assert snap["vector_count"] == 0
        assert snap["safe_state"] is True

    @pytest.mark.asyncio
    async def test_never_raises_on_bad_session(self):
        from app.services.forecast_observability_service import build_forecast_observability_snapshot

        class BrokenSession:
            async def execute(self, *a, **kw):
                raise RuntimeError("DB exploded")

        # Must not raise
        snap = await build_forecast_observability_snapshot(BrokenSession())
        assert isinstance(snap, dict)
        assert snap["safe_state"] is True


# ---------------------------------------------------------------------------
# 23–24: AST safety
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:
    def _imported_names(self) -> list[str]:
        src = _SVC.read_text()
        tree = ast.parse(src)
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
        return names

    def test_no_conviction_import(self):
        for name in self._imported_names():
            assert "conviction" not in name.lower(), f"Forbidden: {name!r}"

    def test_no_delivery_service_import(self):
        for name in self._imported_names():
            assert "delivery_service" not in name.lower(), f"Forbidden: {name!r}"

    def test_no_notification_service_import(self):
        for name in self._imported_names():
            assert "notification_service" not in name.lower(), f"Forbidden: {name!r}"

    def test_no_forecast_vector_write(self):
        """Observability service must not write to forecast_vector."""
        src = _SVC.read_text()
        tree = ast.parse(src)
        forbidden = {"upsert_forecast_vector", "add_forecast_evidence",
                     "delete_evidence_for_forecast", "add_calibration_log"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name and name in forbidden:
                    pytest.fail(f"Observability service must not call {name!r}")

    def test_no_direct_session_add(self):
        """Observability service must never call session.add()."""
        src = _SVC.read_text()
        assert "session.add(" not in src, (
            "Observability service must not call session.add() — read-only"
        )


# ---------------------------------------------------------------------------
# 26: Admin route delegates to observability service
# ---------------------------------------------------------------------------

class TestAdminRoute:
    def test_admin_forecast_status_delegates_to_observability(self):
        """admin_forecast_status must import and call build_forecast_observability_snapshot."""
        api_path = _ROOT / "app" / "api.py"
        src = api_path.read_text()
        assert "forecast_observability_service" in src, (
            "admin_forecast_status must import from forecast_observability_service"
        )
        assert "build_forecast_observability_snapshot" in src, (
            "admin_forecast_status must call build_forecast_observability_snapshot"
        )

    def test_admin_forecast_status_route_declared(self):
        api_path = _ROOT / "app" / "api.py"
        src = api_path.read_text()
        tree = ast.parse(src)
        routes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "router":
                    if node.args and isinstance(node.args[0], ast.Constant):
                        routes.append((node.func.attr, node.args[0].value))
        assert ("get", "/admin/forecast-status") in routes, (
            "GET /admin/forecast-status not declared in api.py"
        )
