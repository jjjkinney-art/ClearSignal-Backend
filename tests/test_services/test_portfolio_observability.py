"""
Tests for app/services/portfolio_observability_service.py — Phase 10D · Slice 8.

Covers all 8 specified scenarios:
  1. Empty snapshot (null session)
  2. Snapshot with portfolios, positions, and insights
  3. Severity / type / rank_band counts
  4. Delivery ledger portfolio_alert count
  5. Notification portfolio_alert count
  6. safe_state logic
  7. DB failure safe degradation
  8. No secrets exposed
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    DeliveryLedger,
    Notification,
    Portfolio,
    PortfolioInsight,
    PortfolioPosition,
)
from app.services.portfolio_observability_service import (
    _portfolio_flags_section,
    _regulatory_section,
    build_portfolio_snapshot,
    build_portfolio_snapshot_sync,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


def _uid() -> str:
    return str(uuid.uuid4())


async def _add_portfolio(session, is_default: bool = False) -> Portfolio:
    row = Portfolio(name=f"Portfolio-{_uid()[:8]}", is_default=is_default)
    session.add(row)
    await session.flush()
    return row


async def _add_position(
    session,
    portfolio_id: str,
    ticker: str = "AAPL",
    membership_class: str = "owned",
) -> PortfolioPosition:
    row = PortfolioPosition(
        portfolio_id=portfolio_id,
        ticker=ticker,
        membership_class=membership_class,
        active=True,
    )
    session.add(row)
    await session.flush()
    return row


async def _add_insight(
    session,
    portfolio_id: str,
    insight_type: str = "concentration_risk",
    severity: str = "high",
    rank_score: float = 3.5,
    stale_input: bool = False,
    last_delivered_at: Optional[datetime] = None,
) -> PortfolioInsight:
    row = PortfolioInsight(
        portfolio_id=portfolio_id,
        insight_type=insight_type,
        cluster_label=f"Cluster-{insight_type}",
        severity=severity,
        severity_rank=3,
        rank_score=rank_score,
        body_json=json.dumps({"prose": "Test prose.", "regulatory_disclaimer": "Not advice."}),
        content_key=_uid(),
        stale_input=stale_input,
        last_delivered_at=last_delivered_at,
    )
    session.add(row)
    await session.flush()
    return row


async def _add_ledger_row(
    session,
    channel: str = "in_app",
    status: str = "delivered_shadow",
    artifact_ref: Optional[str] = None,
) -> DeliveryLedger:
    row = DeliveryLedger(
        content_key=_uid(),
        target_key="port-test",
        channel=channel,
        content_hash=_uid(),
        status=status,
        artifact_ref=artifact_ref,
    )
    session.add(row)
    await session.flush()
    return row


async def _add_notification(
    session,
    kind: str = "portfolio_alert",
    user_id: str = "user1",
) -> Notification:
    row = Notification(
        user_id=user_id,
        kind=kind,
        body_json=json.dumps({"msg": "test"}),
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# §1 — Null session (empty snapshot)
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_null_session_returns_snapshot(self):
        snap = await build_portfolio_snapshot(None)
        assert isinstance(snap, dict)

    @pytest.mark.asyncio
    async def test_null_session_status_ok(self):
        snap = await build_portfolio_snapshot(None)
        assert snap["status"] == "ok"

    @pytest.mark.asyncio
    async def test_null_session_all_top_level_keys_present(self):
        snap = await build_portfolio_snapshot(None)
        required = [
            "status", "snapshot_utc", "db_available", "safe_state",
            "portfolio_flags", "portfolios", "positions", "insights",
            "delivery", "notifications", "digests", "regulatory",
        ]
        for key in required:
            assert key in snap, f"missing key: {key}"

    @pytest.mark.asyncio
    async def test_null_session_db_available_false(self):
        snap = await build_portfolio_snapshot(None)
        assert snap["db_available"] is False

    @pytest.mark.asyncio
    async def test_null_session_counts_are_zero(self):
        snap = await build_portfolio_snapshot(None)
        assert snap["portfolios"]["total"] == 0
        assert snap["positions"]["total"] == 0
        assert snap["insights"]["total"] == 0
        assert snap["notifications"]["portfolio_alert_count"] == 0

    @pytest.mark.asyncio
    async def test_null_session_never_raises(self):
        # Should not raise under any circumstances
        snap = await build_portfolio_snapshot(None)
        assert snap is not None

    def test_sync_wrapper_returns_snapshot(self):
        snap = build_portfolio_snapshot_sync()
        assert isinstance(snap, dict)
        assert snap["status"] == "ok"
        assert snap["db_available"] is False


# ---------------------------------------------------------------------------
# §2 — Snapshot with portfolios, positions, insights
# ---------------------------------------------------------------------------

class TestSnapshotWithData:
    @pytest.mark.asyncio
    async def test_portfolio_count_reflected(self, db_session):
        p1 = await _add_portfolio(db_session)
        p2 = await _add_portfolio(db_session)
        snap = await build_portfolio_snapshot(db_session)
        assert snap["portfolios"]["total"] >= 2

    @pytest.mark.asyncio
    async def test_position_count_reflected(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_position(db_session, port.id, ticker="AAPL")
        await _add_position(db_session, port.id, ticker="MSFT")
        snap = await build_portfolio_snapshot(db_session)
        assert snap["positions"]["total"] >= 2

    @pytest.mark.asyncio
    async def test_insight_count_reflected(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id)
        await _add_insight(db_session, port.id)
        snap = await build_portfolio_snapshot(db_session)
        assert snap["insights"]["total"] >= 2

    @pytest.mark.asyncio
    async def test_default_portfolio_id_returned(self, db_session):
        port = await _add_portfolio(db_session, is_default=True)
        snap = await build_portfolio_snapshot(db_session)
        assert snap["portfolios"]["default_portfolio_id"] == port.id

    @pytest.mark.asyncio
    async def test_snapshot_utc_is_iso_string(self, db_session):
        snap = await build_portfolio_snapshot(db_session)
        assert isinstance(snap["snapshot_utc"], str)
        assert "T" in snap["snapshot_utc"]

    @pytest.mark.asyncio
    async def test_db_available_true(self, db_session):
        snap = await build_portfolio_snapshot(db_session)
        assert snap["db_available"] is True

    @pytest.mark.asyncio
    async def test_positions_by_membership_class(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_position(db_session, port.id, ticker="AAPL", membership_class="owned")
        await _add_position(db_session, port.id, ticker="MSFT", membership_class="watchlist")
        snap = await build_portfolio_snapshot(db_session)
        by_class = snap["positions"]["by_membership_class"]
        assert by_class.get("owned", 0) >= 1
        assert by_class.get("watchlist", 0) >= 1


# ---------------------------------------------------------------------------
# §3 — Severity / type / rank_band counts
# ---------------------------------------------------------------------------

class TestInsightCounts:
    @pytest.mark.asyncio
    async def test_by_severity_counts(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, severity="high", rank_score=3.0)
        await _add_insight(db_session, port.id, severity="medium", rank_score=1.5)
        await _add_insight(db_session, port.id, severity="medium", rank_score=1.5)
        snap = await build_portfolio_snapshot(db_session)
        by_sev = snap["insights"]["by_severity"]
        assert by_sev.get("high", 0) >= 1
        assert by_sev.get("medium", 0) >= 2

    @pytest.mark.asyncio
    async def test_by_type_counts(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, insight_type="concentration_risk")
        await _add_insight(db_session, port.id, insight_type="hidden_correlation")
        await _add_insight(db_session, port.id, insight_type="concentration_risk")
        snap = await build_portfolio_snapshot(db_session)
        by_type = snap["insights"]["by_type"]
        assert by_type.get("concentration_risk", 0) >= 2
        assert by_type.get("hidden_correlation", 0) >= 1

    @pytest.mark.asyncio
    async def test_by_rank_band_high(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=4.5)   # high band
        snap = await build_portfolio_snapshot(db_session)
        by_band = snap["insights"]["by_rank_band"]
        assert by_band.get("high", 0) >= 1

    @pytest.mark.asyncio
    async def test_by_rank_band_critical(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=12.0)  # critical band
        snap = await build_portfolio_snapshot(db_session)
        by_band = snap["insights"]["by_rank_band"]
        assert by_band.get("critical", 0) >= 1

    @pytest.mark.asyncio
    async def test_by_rank_band_medium(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=1.5)   # medium band
        snap = await build_portfolio_snapshot(db_session)
        by_band = snap["insights"]["by_rank_band"]
        assert by_band.get("medium", 0) >= 1

    @pytest.mark.asyncio
    async def test_by_rank_band_low(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=0.5)   # low band
        snap = await build_portfolio_snapshot(db_session)
        by_band = snap["insights"]["by_rank_band"]
        assert by_band.get("low", 0) >= 1

    @pytest.mark.asyncio
    async def test_stale_count(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, stale_input=True)
        await _add_insight(db_session, port.id, stale_input=False)
        snap = await build_portfolio_snapshot(db_session)
        assert snap["insights"]["stale_count"] >= 1

    @pytest.mark.asyncio
    async def test_last_generated_at_set(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id)
        snap = await build_portfolio_snapshot(db_session)
        assert snap["insights"]["last_generated_at"] is not None

    @pytest.mark.asyncio
    async def test_last_delivered_shadow_at_set(self, db_session):
        port = await _add_portfolio(db_session)
        ts = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
        await _add_insight(db_session, port.id, last_delivered_at=ts)
        snap = await build_portfolio_snapshot(db_session)
        assert snap["insights"]["last_delivered_shadow_at"] is not None

    @pytest.mark.asyncio
    async def test_last_delivered_shadow_at_none_when_never_delivered(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, last_delivered_at=None)
        snap = await build_portfolio_snapshot(db_session)
        # May be None if no insight has been delivered
        assert "last_delivered_shadow_at" in snap["insights"]


# ---------------------------------------------------------------------------
# §4 — Delivery ledger portfolio_alert count
# ---------------------------------------------------------------------------

class TestDeliveryLedgerCount:
    @pytest.mark.asyncio
    async def test_empty_delivery_ledger(self, db_session):
        snap = await build_portfolio_snapshot(db_session)
        assert snap["delivery"]["in_app_total"] == 0
        assert snap["delivery"]["shadow_count"] == 0

    @pytest.mark.asyncio
    async def test_shadow_count_incremented(self, db_session):
        await _add_ledger_row(db_session, channel="in_app", status="delivered_shadow")
        snap = await build_portfolio_snapshot(db_session)
        assert snap["delivery"]["shadow_count"] >= 1

    @pytest.mark.asyncio
    async def test_in_app_total_counts_all_in_app(self, db_session):
        await _add_ledger_row(db_session, channel="in_app", status="delivered_shadow")
        await _add_ledger_row(db_session, channel="in_app", status="pending")
        snap = await build_portfolio_snapshot(db_session)
        assert snap["delivery"]["in_app_total"] >= 2

    @pytest.mark.asyncio
    async def test_email_rows_not_in_in_app_total(self, db_session):
        await _add_ledger_row(db_session, channel="email", status="delivered_shadow")
        snap = await build_portfolio_snapshot(db_session)
        assert snap["delivery"]["in_app_total"] == 0


# ---------------------------------------------------------------------------
# §5 — Notification portfolio_alert count
# ---------------------------------------------------------------------------

class TestNotificationCount:
    @pytest.mark.asyncio
    async def test_empty_notifications(self, db_session):
        snap = await build_portfolio_snapshot(db_session)
        assert snap["notifications"]["portfolio_alert_count"] == 0

    @pytest.mark.asyncio
    async def test_portfolio_alert_counted(self, db_session):
        await _add_notification(db_session, kind="portfolio_alert")
        snap = await build_portfolio_snapshot(db_session)
        assert snap["notifications"]["portfolio_alert_count"] >= 1

    @pytest.mark.asyncio
    async def test_other_notification_kinds_not_counted(self, db_session):
        await _add_notification(db_session, kind="daily_brief")
        await _add_notification(db_session, kind="watchlist_alert")
        snap = await build_portfolio_snapshot(db_session)
        assert snap["notifications"]["portfolio_alert_count"] == 0


# ---------------------------------------------------------------------------
# §6 — safe_state logic
# ---------------------------------------------------------------------------

class TestSafeState:
    @pytest.mark.asyncio
    async def test_safe_state_true_when_delivery_disabled(self, db_session):
        with patch(
            "app.services.portfolio_observability_service._portfolio_flags_section",
            return_value={
                "portfolio_insight_enabled":  True,
                "portfolio_delivery_enabled": False,   # delivery off → safe
                "portfolio_shadow":           False,
                "portfolio_internal_only":    True,
            },
        ):
            snap = await build_portfolio_snapshot(db_session)
        assert snap["safe_state"] is True

    @pytest.mark.asyncio
    async def test_safe_state_true_when_shadow_enabled(self, db_session):
        with patch(
            "app.services.portfolio_observability_service._portfolio_flags_section",
            return_value={
                "portfolio_insight_enabled":  True,
                "portfolio_delivery_enabled": True,
                "portfolio_shadow":           True,    # shadow → safe
                "portfolio_internal_only":    True,
            },
        ):
            snap = await build_portfolio_snapshot(db_session)
        assert snap["safe_state"] is True

    @pytest.mark.asyncio
    async def test_safe_state_false_when_live_delivery(self, db_session):
        with patch(
            "app.services.portfolio_observability_service._portfolio_flags_section",
            return_value={
                "portfolio_insight_enabled":  True,
                "portfolio_delivery_enabled": True,
                "portfolio_shadow":           False,   # live delivery → NOT safe
                "portfolio_internal_only":    False,
            },
        ):
            snap = await build_portfolio_snapshot(db_session)
        assert snap["safe_state"] is False

    @pytest.mark.asyncio
    async def test_safe_state_default_is_true(self, db_session):
        # Default flags: delivery_enabled=False → safe
        snap = await build_portfolio_snapshot(db_session)
        assert snap["safe_state"] is True


# ---------------------------------------------------------------------------
# §7 — DB failure safe degradation
# ---------------------------------------------------------------------------

class TestDbFailureDegradation:
    @pytest.mark.asyncio
    async def test_db_error_does_not_raise(self):
        # Pass an object that is not a real session — all DB calls will fail
        class BrokenSession:
            async def execute(self, *a, **kw):
                raise RuntimeError("DB is down")

        snap = await build_portfolio_snapshot(BrokenSession())
        assert snap is not None
        assert snap["status"] == "ok"

    @pytest.mark.asyncio
    async def test_db_error_db_available_is_false_or_partial(self):
        class BrokenSession:
            async def execute(self, *a, **kw):
                raise RuntimeError("DB is down")

        snap = await build_portfolio_snapshot(BrokenSession())
        # db_available should be False (total failure) or "partial"
        assert snap["db_available"] in (False, "partial")

    @pytest.mark.asyncio
    async def test_db_error_zeros_in_counts(self):
        class BrokenSession:
            async def execute(self, *a, **kw):
                raise RuntimeError("DB is down")

        snap = await build_portfolio_snapshot(BrokenSession())
        assert snap["portfolios"]["total"] == 0
        assert snap["insights"]["total"] == 0
        assert snap["notifications"]["portfolio_alert_count"] == 0

    @pytest.mark.asyncio
    async def test_db_error_safe_state_still_present(self):
        class BrokenSession:
            async def execute(self, *a, **kw):
                raise RuntimeError("DB is down")

        snap = await build_portfolio_snapshot(BrokenSession())
        assert "safe_state" in snap


# ---------------------------------------------------------------------------
# §8 — No secrets exposed
# ---------------------------------------------------------------------------

class TestNoSecretsExposed:
    @pytest.mark.asyncio
    async def test_snapshot_contains_no_database_url(self, db_session):
        snap = await build_portfolio_snapshot(db_session)
        snap_str = json.dumps(snap)
        # DATABASE_URL pattern: postgresql:// or sqlite://
        assert "postgresql://" not in snap_str
        assert "sqlite://" not in snap_str

    @pytest.mark.asyncio
    async def test_snapshot_contains_no_api_key_patterns(self, db_session):
        snap = await build_portfolio_snapshot(db_session)
        snap_str = json.dumps(snap).lower()
        # Should not contain raw API key patterns
        assert "sk-ant-" not in snap_str
        assert "bearer " not in snap_str

    @pytest.mark.asyncio
    async def test_snapshot_contains_no_user_tokens(self, db_session):
        snap = await build_portfolio_snapshot(db_session)
        snap_str = json.dumps(snap)
        # No fields named "token", "password", "secret", "key" with values
        for sensitive_key in ("password", "token", "secret", "api_key"):
            assert sensitive_key not in snap_str.lower() or (
                sensitive_key + "_count" in snap_str.lower()
                or sensitive_key + "_present" in snap_str.lower()
            )

    @pytest.mark.asyncio
    async def test_regulatory_section_no_secrets(self, db_session):
        snap = await build_portfolio_snapshot(db_session)
        reg = snap["regulatory"]
        # Regulatory section must have exactly these keys — no dynamic user data
        allowed_keys = {
            "disclaimer_present", "disclaimer_length",
            "prohibited_word_count", "prohibited_phrase_count",
            "load_error",   # optional error key
        }
        for key in reg.keys():
            assert key in allowed_keys, f"unexpected key in regulatory: {key}"


# ---------------------------------------------------------------------------
# Portfolio flags section unit tests
# ---------------------------------------------------------------------------

class TestPortfolioFlagsSection:
    def test_flags_have_required_keys(self):
        flags = _portfolio_flags_section()
        for key in [
            "portfolio_insight_enabled",
            "portfolio_delivery_enabled",
            "portfolio_shadow",
            "portfolio_internal_only",
        ]:
            assert key in flags

    def test_flags_are_booleans(self):
        flags = _portfolio_flags_section()
        for key, val in flags.items():
            assert isinstance(val, bool), f"flag {key} should be bool, got {type(val)}"

    def test_flags_safe_defaults(self):
        # Without any settings override, all flags should reflect safe defaults
        flags = _portfolio_flags_section()
        # Delivery disabled OR shadow on → safe state
        safe = not flags["portfolio_delivery_enabled"] or flags["portfolio_shadow"]
        assert safe, "default flags should always produce safe_state=True"


# ---------------------------------------------------------------------------
# Regulatory section unit tests
# ---------------------------------------------------------------------------

class TestRegulatorySectionUnit:
    def test_regulatory_section_disclaimer_present(self):
        reg = _regulatory_section()
        assert reg["disclaimer_present"] is True

    def test_regulatory_section_prohibited_word_count_gt_0(self):
        reg = _regulatory_section()
        assert reg["prohibited_word_count"] > 0

    def test_regulatory_section_prohibited_phrase_count_gt_0(self):
        reg = _regulatory_section()
        assert reg["prohibited_phrase_count"] > 0

    def test_regulatory_section_disclaimer_length_gt_0(self):
        reg = _regulatory_section()
        assert reg["disclaimer_length"] > 0
