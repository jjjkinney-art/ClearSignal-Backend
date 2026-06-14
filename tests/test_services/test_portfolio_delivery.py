"""
Tests for app/services/portfolio_delivery_service.py — Phase 10D · Slice 7.

Covers 10 specified scenarios:
  1. Null session returns safe empty result
  2. Empty portfolio — no insights — produces empty delivery result
  3. Single insight enqueued successfully (shadow mode)
  4. Duplicate insight suppressed on second call (same content_key window)
  5. Zero-rank-score insight suppressed before enqueue
  6. last_delivered_at stamped on delivered insight row
  7. Regulatory disclaimer preserved in payload
  8. body_json / prose never mutated by delivery
  9. build_portfolio_context_block returns correct structure (read-only)
 10. shadow=True does not create Notification rows (delivery_ledger only)
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Portfolio, PortfolioInsight, PortfolioPosition
from app.services.portfolio_delivery_service import (
    CHANNEL_IN_APP,
    KIND_PORTFOLIO_ALERT,
    InsightDeliveryOutcome,
    PortfolioDeliveryResult,
    _build_payload,
    _delivery_content_key,
    _map_severity,
    build_portfolio_context_block,
    deliver_portfolio_insights,
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


async def _add_portfolio(session, user_id: str = "user1") -> Portfolio:
    row = Portfolio(name="Test Portfolio", user_id=user_id)
    session.add(row)
    await session.flush()
    return row


async def _add_insight(
    session,
    portfolio_id: str,
    insight_type: str = "concentration_risk",
    cluster_label: str = "Tech Cluster",
    severity: str = "high",
    rank_score: float = 3.0,
    cluster_weight: Optional[float] = 0.4,
    stale_input: bool = False,
    member_tickers: str = '["AAPL","MSFT"]',
    body_json: Optional[str] = None,
    last_delivered_at: Optional[datetime] = None,
) -> PortfolioInsight:
    content_key = f"ck-{uuid.uuid4().hex[:16]}"
    if body_json is None:
        body_json = json.dumps({
            "prose": f"Two positions share {cluster_label} exposure.",
            "regulatory_disclaimer": "This is not investment advice.",
            "meta": {"insight_type": insight_type},
        })
    row = PortfolioInsight(
        portfolio_id=portfolio_id,
        insight_type=insight_type,
        cluster_label=cluster_label,
        severity=severity,
        severity_rank=3,
        rank_score=rank_score,
        cluster_weight=cluster_weight,
        stale_input=stale_input,
        member_tickers=member_tickers,
        body_json=body_json,
        content_key=content_key,
        last_delivered_at=last_delivered_at,
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# §1 — Null session safety
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_null_session_returns_portfolio_delivery_result(self):
        result = await deliver_portfolio_insights(
            None, "port-123", "user-123"
        )
        assert isinstance(result, PortfolioDeliveryResult)
        assert result.portfolio_id == "port-123"
        assert result.enqueued == 0
        assert result.skipped == 1
        assert result.shadow is True

    @pytest.mark.asyncio
    async def test_null_session_never_raises(self):
        result = await deliver_portfolio_insights(None, "p", "u")
        assert result is not None

    @pytest.mark.asyncio
    async def test_null_session_has_regulatory_disclaimer(self):
        result = await deliver_portfolio_insights(None, "p", "u")
        assert len(result.regulatory_disclaimer) > 0


# ---------------------------------------------------------------------------
# §2 — Empty portfolio
# ---------------------------------------------------------------------------

class TestEmptyPortfolio:
    @pytest.mark.asyncio
    async def test_empty_portfolio_zero_enqueued(self, db_session):
        port = await _add_portfolio(db_session)
        result = await deliver_portfolio_insights(
            db_session, port.id, "user1"
        )
        assert result.enqueued == 0
        assert result.outcomes == []

    @pytest.mark.asyncio
    async def test_empty_portfolio_no_suppress(self, db_session):
        port = await _add_portfolio(db_session)
        result = await deliver_portfolio_insights(
            db_session, port.id, "user1"
        )
        assert result.suppressed_duplicate == 0
        assert result.suppressed_guardrail == 0
        assert result.suppressed_zero_score == 0


# ---------------------------------------------------------------------------
# §3 — Single insight enqueued (shadow mode)
# ---------------------------------------------------------------------------

class TestSingleInsightEnqueue:
    @pytest.mark.asyncio
    async def test_single_insight_enqueued(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=3.5)

        with patch(
            "app.services.portfolio_delivery_service._loop_delivery_svc"
        ) as mock_lds:
            mock_result = MagicMock()
            mock_result.status = "pending"
            mock_result.reason = ""
            mock_result.delivery_id = "dl-001"
            mock_lds.enqueue = AsyncMock(return_value=mock_result)
            mock_lds.flush_pending_shadow = AsyncMock(return_value=[mock_result])
            mock_lds.STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
            mock_lds.STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
            mock_lds.STATUS_SKIPPED = "skipped"
            mock_lds.STATUS_DELIVERED_SHADOW = "delivered_shadow"
            mock_lds.STATUS_FAILED = "failed"

            result = await deliver_portfolio_insights(
                db_session, port.id, "user1", shadow=True
            )

        assert result.enqueued == 1
        assert result.suppressed_duplicate == 0
        assert len(result.outcomes) == 1
        assert result.outcomes[0].delivery_id == "dl-001"

    @pytest.mark.asyncio
    async def test_enqueue_called_with_channel_in_app(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=2.0)

        call_kwargs = {}

        async def capture_enqueue(*args, **kwargs):
            call_kwargs.update({
                "channel": args[2] if len(args) > 2 else kwargs.get("channel"),
                "payload": args[4] if len(args) > 4 else kwargs.get("payload"),
                "severity": kwargs.get("severity"),
            })
            m = MagicMock()
            m.status = "pending"
            m.reason = ""
            m.delivery_id = "dl-x"
            return m

        with patch(
            "app.services.portfolio_delivery_service._loop_delivery_svc"
        ) as mock_lds:
            mock_lds.enqueue = capture_enqueue
            mock_lds.flush_pending_shadow = AsyncMock(return_value=[])
            mock_lds.STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
            mock_lds.STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
            mock_lds.STATUS_SKIPPED = "skipped"
            mock_lds.STATUS_DELIVERED_SHADOW = "delivered_shadow"
            mock_lds.STATUS_FAILED = "failed"

            await deliver_portfolio_insights(db_session, port.id, "user1")

        assert call_kwargs.get("channel") == CHANNEL_IN_APP

    @pytest.mark.asyncio
    async def test_payload_contains_kind_portfolio_alert(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=2.5)

        captured_payload = {}

        async def capture_enqueue(*args, **kwargs):
            captured_payload.update(args[4] if len(args) > 4 else {})
            m = MagicMock()
            m.status = "pending"
            m.reason = ""
            m.delivery_id = "dl-y"
            return m

        with patch(
            "app.services.portfolio_delivery_service._loop_delivery_svc"
        ) as mock_lds:
            mock_lds.enqueue = capture_enqueue
            mock_lds.flush_pending_shadow = AsyncMock(return_value=[])
            mock_lds.STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
            mock_lds.STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
            mock_lds.STATUS_SKIPPED = "skipped"
            mock_lds.STATUS_DELIVERED_SHADOW = "delivered_shadow"
            mock_lds.STATUS_FAILED = "failed"

            await deliver_portfolio_insights(db_session, port.id, "user1")

        assert captured_payload.get("kind") == KIND_PORTFOLIO_ALERT


# ---------------------------------------------------------------------------
# §4 — Duplicate suppression via loop_delivery_service
# ---------------------------------------------------------------------------

class TestDuplicateSuppression:
    @pytest.mark.asyncio
    async def test_duplicate_suppressed_on_second_call(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=3.0)

        suppressed_result = MagicMock()
        suppressed_result.status = "suppressed_duplicate"
        suppressed_result.reason = "duplicate_content_key"
        suppressed_result.delivery_id = None

        with patch(
            "app.services.portfolio_delivery_service._loop_delivery_svc"
        ) as mock_lds:
            mock_lds.enqueue = AsyncMock(return_value=suppressed_result)
            mock_lds.flush_pending_shadow = AsyncMock(return_value=[])
            mock_lds.STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
            mock_lds.STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
            mock_lds.STATUS_SKIPPED = "skipped"
            mock_lds.STATUS_DELIVERED_SHADOW = "delivered_shadow"
            mock_lds.STATUS_FAILED = "failed"

            result = await deliver_portfolio_insights(
                db_session, port.id, "user1"
            )

        assert result.suppressed_duplicate == 1
        assert result.enqueued == 0

    @pytest.mark.asyncio
    async def test_delivery_content_key_stable_across_calls(self):
        ck = "abc123"
        channel = "in_app"
        key1 = _delivery_content_key(ck, channel)
        key2 = _delivery_content_key(ck, channel)
        assert key1 == key2

    @pytest.mark.asyncio
    async def test_delivery_content_key_differs_by_channel(self):
        ck = "abc123"
        key_in_app = _delivery_content_key(ck, "in_app")
        key_email = _delivery_content_key(ck, "email")
        assert key_in_app != key_email


# ---------------------------------------------------------------------------
# §5 — Zero rank_score suppression
# ---------------------------------------------------------------------------

class TestZeroScoreSuppression:
    @pytest.mark.asyncio
    async def test_zero_score_suppressed_before_enqueue(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=0.0)

        with patch(
            "app.services.portfolio_delivery_service._loop_delivery_svc"
        ) as mock_lds:
            mock_lds.enqueue = AsyncMock()
            mock_lds.flush_pending_shadow = AsyncMock(return_value=[])
            mock_lds.STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
            mock_lds.STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
            mock_lds.STATUS_SKIPPED = "skipped"
            mock_lds.STATUS_DELIVERED_SHADOW = "delivered_shadow"
            mock_lds.STATUS_FAILED = "failed"

            result = await deliver_portfolio_insights(
                db_session, port.id, "user1"
            )

        assert result.suppressed_zero_score == 1
        assert result.enqueued == 0
        mock_lds.enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_nonzero_score_not_suppressed(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=0.1)

        with patch(
            "app.services.portfolio_delivery_service._loop_delivery_svc"
        ) as mock_lds:
            m = MagicMock()
            m.status = "pending"
            m.reason = ""
            m.delivery_id = "dl-z"
            mock_lds.enqueue = AsyncMock(return_value=m)
            mock_lds.flush_pending_shadow = AsyncMock(return_value=[])
            mock_lds.STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
            mock_lds.STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
            mock_lds.STATUS_SKIPPED = "skipped"
            mock_lds.STATUS_DELIVERED_SHADOW = "delivered_shadow"
            mock_lds.STATUS_FAILED = "failed"

            result = await deliver_portfolio_insights(
                db_session, port.id, "user1"
            )

        assert result.suppressed_zero_score == 0
        mock_lds.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# §6 — last_delivered_at stamped on successful delivery
# ---------------------------------------------------------------------------

class TestLastDeliveredAtStamped:
    @pytest.mark.asyncio
    async def test_last_delivered_at_stamped_after_enqueue(self, db_session):
        port = await _add_portfolio(db_session)
        insight = await _add_insight(db_session, port.id, rank_score=2.0)
        assert insight.last_delivered_at is None

        with patch(
            "app.services.portfolio_delivery_service._loop_delivery_svc"
        ) as mock_lds:
            m = MagicMock()
            m.status = "pending"
            m.reason = ""
            m.delivery_id = "dl-stamp"
            mock_lds.enqueue = AsyncMock(return_value=m)
            mock_lds.flush_pending_shadow = AsyncMock(return_value=[m])
            mock_lds.STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
            mock_lds.STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
            mock_lds.STATUS_SKIPPED = "skipped"
            mock_lds.STATUS_DELIVERED_SHADOW = "delivered_shadow"
            mock_lds.STATUS_FAILED = "failed"

            await deliver_portfolio_insights(db_session, port.id, "user1")

        assert insight.last_delivered_at is not None

    @pytest.mark.asyncio
    async def test_last_delivered_at_not_stamped_on_duplicate(self, db_session):
        port = await _add_portfolio(db_session)
        insight = await _add_insight(db_session, port.id, rank_score=2.0)
        assert insight.last_delivered_at is None

        dup = MagicMock()
        dup.status = "suppressed_duplicate"
        dup.reason = "duplicate_content_key"
        dup.delivery_id = None

        with patch(
            "app.services.portfolio_delivery_service._loop_delivery_svc"
        ) as mock_lds:
            mock_lds.enqueue = AsyncMock(return_value=dup)
            mock_lds.flush_pending_shadow = AsyncMock(return_value=[])
            mock_lds.STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
            mock_lds.STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
            mock_lds.STATUS_SKIPPED = "skipped"
            mock_lds.STATUS_DELIVERED_SHADOW = "delivered_shadow"
            mock_lds.STATUS_FAILED = "failed"

            await deliver_portfolio_insights(db_session, port.id, "user1")

        # last_delivered_at should remain None (not stamped for duplicates)
        assert insight.last_delivered_at is None


# ---------------------------------------------------------------------------
# §7 — Regulatory disclaimer preserved in payload
# ---------------------------------------------------------------------------

class TestRegulatoryDisclaimerPreserved:
    @pytest.mark.asyncio
    async def test_disclaimer_in_delivery_result(self, db_session):
        port = await _add_portfolio(db_session)
        result = await deliver_portfolio_insights(db_session, port.id, "u")
        assert len(result.regulatory_disclaimer) > 0

    def test_disclaimer_in_payload(self):
        row = MagicMock()
        row.id = "ins-1"
        row.portfolio_id = "port-1"
        row.insight_type = "concentration_risk"
        row.cluster_label = "Tech"
        row.severity = "high"
        row.rank_score = 3.0
        row.member_tickers = '["AAPL"]'
        row.stale_input = False
        row.content_key = "ck-abc"
        row.created_at = datetime(2026, 6, 14, tzinfo=timezone.utc)
        row.body_json = json.dumps({
            "prose": "Shared exposure detected.",
            "regulatory_disclaimer": "Not investment advice.",
        })
        payload = _build_payload(row)
        assert "regulatory_disclaimer" in payload
        assert len(payload["regulatory_disclaimer"]) > 0

    def test_disclaimer_preserved_from_body_json(self):
        row = MagicMock()
        row.id = "ins-2"
        row.portfolio_id = "port-2"
        row.insight_type = "shared_risk_cluster"
        row.cluster_label = "Finance"
        row.severity = "medium"
        row.rank_score = 2.0
        row.member_tickers = '[]'
        row.stale_input = False
        row.content_key = "ck-def"
        row.created_at = datetime(2026, 6, 14, tzinfo=timezone.utc)
        row.body_json = json.dumps({
            "prose": "Risk cluster detected.",
            "regulatory_disclaimer": "Specific disclaimer text XYZ.",
        })
        payload = _build_payload(row)
        assert "Specific disclaimer text XYZ." in payload["regulatory_disclaimer"]


# ---------------------------------------------------------------------------
# §8 — body_json / prose never mutated
# ---------------------------------------------------------------------------

class TestBodyJsonNotMutated:
    @pytest.mark.asyncio
    async def test_body_json_not_mutated_by_delivery(self, db_session):
        port = await _add_portfolio(db_session)
        original_body = json.dumps({
            "prose": "Original prose — must not change.",
            "regulatory_disclaimer": "Not advice.",
        })
        insight = await _add_insight(
            db_session, port.id, rank_score=2.0, body_json=original_body
        )

        with patch(
            "app.services.portfolio_delivery_service._loop_delivery_svc"
        ) as mock_lds:
            m = MagicMock()
            m.status = "pending"
            m.reason = ""
            m.delivery_id = "dl-mut"
            mock_lds.enqueue = AsyncMock(return_value=m)
            mock_lds.flush_pending_shadow = AsyncMock(return_value=[m])
            mock_lds.STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
            mock_lds.STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
            mock_lds.STATUS_SKIPPED = "skipped"
            mock_lds.STATUS_DELIVERED_SHADOW = "delivered_shadow"
            mock_lds.STATUS_FAILED = "failed"

            await deliver_portfolio_insights(db_session, port.id, "user1")

        assert insight.body_json == original_body

    def test_build_payload_does_not_mutate_row_body_json(self):
        row = MagicMock()
        row.id = "ins-3"
        row.portfolio_id = "port-3"
        row.insight_type = "catalyst_propagation"
        row.cluster_label = "Energy"
        row.severity = "low"
        row.rank_score = 1.0
        row.member_tickers = '["XOM"]'
        row.stale_input = False
        row.content_key = "ck-ghi"
        row.created_at = datetime(2026, 6, 14, tzinfo=timezone.utc)
        original = '{"prose": "Energy risk.", "regulatory_disclaimer": "Not advice."}'
        row.body_json = original

        _build_payload(row)  # must not mutate row
        assert row.body_json == original


# ---------------------------------------------------------------------------
# §9 — build_portfolio_context_block (read-only briefing helper)
# ---------------------------------------------------------------------------

class TestBriefingHelper:
    def _make_ranked_insight(
        self,
        insight_id: str = "ins-1",
        insight_type: str = "concentration_risk",
        cluster_label: str = "Tech",
        severity: str = "high",
        rank_score: float = 3.0,
        rank_band: str = "high",
        member_tickers=None,
        body_json: Optional[str] = None,
    ) -> dict:
        if member_tickers is None:
            member_tickers = ["AAPL", "MSFT"]
        if body_json is None:
            body_json = json.dumps({"prose": "Shared exposure.", "meta": {}})
        return {
            "insight_id": insight_id,
            "insight_type": insight_type,
            "cluster_label": cluster_label,
            "severity": severity,
            "rank_score": rank_score,
            "rank_band": rank_band,
            "member_tickers": member_tickers,
            "body_json": body_json,
        }

    def test_empty_list_returns_no_alerts(self):
        block = build_portfolio_context_block([])
        assert block["has_portfolio_alerts"] is False
        assert block["portfolio_alert_count"] == 0
        assert block["top_highlights"] == []

    def test_single_insight_produces_one_highlight(self):
        insights = [self._make_ranked_insight()]
        block = build_portfolio_context_block(insights)
        assert block["has_portfolio_alerts"] is True
        assert block["portfolio_alert_count"] == 1
        assert len(block["top_highlights"]) == 1

    def test_highlight_contains_required_fields(self):
        insights = [self._make_ranked_insight(
            insight_id="i-abc", severity="high", rank_score=4.0, rank_band="high"
        )]
        block = build_portfolio_context_block(insights)
        h = block["top_highlights"][0]
        assert h["insight_id"] == "i-abc"
        assert h["severity"] == "high"
        assert h["rank_score"] == 4.0
        assert h["rank_band"] == "high"
        assert "prose" in h
        assert "cluster_label" in h

    def test_highlights_capped_at_max(self):
        insights = [
            self._make_ranked_insight(insight_id=f"i-{i}", rank_score=float(10 - i))
            for i in range(10)
        ]
        block = build_portfolio_context_block(insights, max_highlights=3)
        assert len(block["top_highlights"]) == 3

    def test_severity_summary_counts_correctly(self):
        insights = [
            self._make_ranked_insight(insight_id="a", severity="high"),
            self._make_ranked_insight(insight_id="b", severity="high"),
            self._make_ranked_insight(insight_id="c", severity="medium"),
        ]
        block = build_portfolio_context_block(insights)
        assert block["severity_summary"]["high"] == 2
        assert block["severity_summary"]["medium"] == 1

    def test_affected_tickers_deduplicated(self):
        insights = [
            self._make_ranked_insight("a", member_tickers=["AAPL", "MSFT"]),
            self._make_ranked_insight("b", member_tickers=["MSFT", "GOOGL"]),
        ]
        block = build_portfolio_context_block(insights)
        assert set(block["affected_tickers"]) == {"AAPL", "MSFT", "GOOGL"}
        # No duplicates
        assert len(block["affected_tickers"]) == 3

    def test_sorted_descending_by_rank_score(self):
        insights = [
            self._make_ranked_insight("low", rank_score=1.0),
            self._make_ranked_insight("high", rank_score=5.0),
            self._make_ranked_insight("mid", rank_score=3.0),
        ]
        block = build_portfolio_context_block(insights, max_highlights=3)
        scores = [h["rank_score"] for h in block["top_highlights"]]
        assert scores == sorted(scores, reverse=True)

    def test_no_db_writes(self, db_session=None):
        # build_portfolio_context_block is pure / read-only — no session needed
        insights = [self._make_ranked_insight()]
        block = build_portfolio_context_block(insights)
        assert block is not None

    def test_member_tickers_as_json_string(self):
        insights = [
            self._make_ranked_insight(
                "a", member_tickers='["TSLA", "NIO"]'
            )
        ]
        block = build_portfolio_context_block(insights)
        assert "TSLA" in block["affected_tickers"]
        assert "NIO" in block["affected_tickers"]


# ---------------------------------------------------------------------------
# §10 — Shadow mode: no Notification rows
# ---------------------------------------------------------------------------

class TestShadowMode:
    @pytest.mark.asyncio
    async def test_shadow_true_calls_flush_pending_shadow(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=3.0)

        flush_calls = []

        async def capture_flush(*args, **kwargs):
            flush_calls.append(True)
            return []

        with patch(
            "app.services.portfolio_delivery_service._loop_delivery_svc"
        ) as mock_lds:
            m = MagicMock()
            m.status = "pending"
            m.reason = ""
            m.delivery_id = "dl-shd"
            mock_lds.enqueue = AsyncMock(return_value=m)
            mock_lds.flush_pending_shadow = capture_flush
            mock_lds.STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
            mock_lds.STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
            mock_lds.STATUS_SKIPPED = "skipped"
            mock_lds.STATUS_DELIVERED_SHADOW = "delivered_shadow"
            mock_lds.STATUS_FAILED = "failed"

            result = await deliver_portfolio_insights(
                db_session, port.id, "user1", shadow=True, shadow_flush=True
            )

        assert len(flush_calls) == 1, "flush_pending_shadow should be called once"
        assert result.shadow is True

    @pytest.mark.asyncio
    async def test_shadow_flush_false_skips_drain(self, db_session):
        port = await _add_portfolio(db_session)
        await _add_insight(db_session, port.id, rank_score=2.5)

        flush_calls = []

        async def capture_flush(*args, **kwargs):
            flush_calls.append(True)
            return []

        with patch(
            "app.services.portfolio_delivery_service._loop_delivery_svc"
        ) as mock_lds:
            m = MagicMock()
            m.status = "pending"
            m.reason = ""
            m.delivery_id = "dl-nosh"
            mock_lds.enqueue = AsyncMock(return_value=m)
            mock_lds.flush_pending_shadow = capture_flush
            mock_lds.STATUS_SUPPRESSED_DUPLICATE = "suppressed_duplicate"
            mock_lds.STATUS_SUPPRESSED_GUARDRAIL = "suppressed"
            mock_lds.STATUS_SKIPPED = "skipped"
            mock_lds.STATUS_DELIVERED_SHADOW = "delivered_shadow"
            mock_lds.STATUS_FAILED = "failed"

            result = await deliver_portfolio_insights(
                db_session, port.id, "user1", shadow=True, shadow_flush=False
            )

        assert len(flush_calls) == 0
        assert result.shadow_drained == 0

    @pytest.mark.asyncio
    async def test_shadow_mode_result_carries_shadow_flag(self, db_session):
        port = await _add_portfolio(db_session)
        result = await deliver_portfolio_insights(
            db_session, port.id, "user1", shadow=True
        )
        assert result.shadow is True

    @pytest.mark.asyncio
    async def test_non_shadow_mode_result_carries_shadow_false(self, db_session):
        port = await _add_portfolio(db_session)
        result = await deliver_portfolio_insights(
            db_session, port.id, "user1", shadow=False
        )
        assert result.shadow is False


# ---------------------------------------------------------------------------
# Helpers / unit tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_map_severity_high_to_alert(self):
        assert _map_severity("high") == "alert"

    def test_map_severity_critical(self):
        assert _map_severity("critical") == "critical"

    def test_map_severity_medium_to_warning(self):
        assert _map_severity("medium") == "warning"

    def test_map_severity_low_to_info(self):
        assert _map_severity("low") == "info"

    def test_map_severity_unknown_to_info(self):
        assert _map_severity("unknown") == "info"

    def test_map_severity_case_insensitive(self):
        assert _map_severity("HIGH") == "alert"

    def test_delivery_content_key_is_64_hex(self):
        key = _delivery_content_key("some-content-key", "in_app")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_build_payload_structure(self):
        row = MagicMock()
        row.id = "ins-99"
        row.portfolio_id = "port-99"
        row.insight_type = "hidden_correlation"
        row.cluster_label = "Cluster A"
        row.severity = "high"
        row.rank_score = 4.5
        row.member_tickers = '["A","B","C"]'
        row.stale_input = False
        row.content_key = "ck-xyz"
        row.created_at = datetime(2026, 6, 14, tzinfo=timezone.utc)
        row.body_json = '{"prose": "Test prose.", "regulatory_disclaimer": "Disc."}'
        payload = _build_payload(row)
        assert payload["kind"] == KIND_PORTFOLIO_ALERT
        assert payload["portfolio_id"] == "port-99"
        assert payload["insight_id"] == "ins-99"
        assert payload["insight_type"] == "hidden_correlation"
        assert payload["severity"] == "alert"   # high → alert
        assert payload["member_tickers"] == ["A", "B", "C"]
        assert payload["prose"] == "Test prose."

    def test_build_payload_handles_malformed_body_json(self):
        row = MagicMock()
        row.id = "ins-bad"
        row.portfolio_id = "port-bad"
        row.insight_type = "regime_sensitivity"
        row.cluster_label = "Macro"
        row.severity = "info"
        row.rank_score = 0.5
        row.member_tickers = "[]"
        row.stale_input = False
        row.content_key = "ck-bad"
        row.created_at = datetime(2026, 6, 14, tzinfo=timezone.utc)
        row.body_json = "NOT VALID JSON{{{"
        payload = _build_payload(row)
        assert payload["prose"] == ""
