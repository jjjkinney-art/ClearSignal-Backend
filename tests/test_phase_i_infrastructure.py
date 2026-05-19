"""
Phase I infrastructure tests.
30 deterministic tests covering NormalizedEvent, ingestion adapters, and access control.
"""
from __future__ import annotations
import pytest

# ── NormalizedEvent tests (8) ──────────────────────────────────────────────────

from app.services.ingestion.normalized_event import (
    NormalizedEvent, EventCategory, SourceReliability,
)


def test_normalized_event_has_required_fields():
    event = NormalizedEvent(
        category=EventCategory.EARNINGS,
        headline="Test headline",
        source="test_source",
        event_timestamp="2026-05-19T10:00:00Z",
        ingestion_timestamp="2026-05-19T10:01:00Z",
    )
    assert event.category == EventCategory.EARNINGS
    assert event.headline == "Test headline"
    assert event.source == "test_source"
    assert event.event_timestamp == "2026-05-19T10:00:00Z"
    assert event.ingestion_timestamp == "2026-05-19T10:01:00Z"


def test_event_category_enum_has_earnings():
    assert EventCategory.EARNINGS == "earnings"


def test_event_category_enum_has_guidance():
    assert EventCategory.GUIDANCE == "guidance"


def test_event_category_enum_has_macro():
    assert EventCategory.MACRO == "macro"


def test_event_category_enum_has_news():
    assert EventCategory.NEWS == "news"


def test_source_reliability_enum_values():
    assert SourceReliability.HIGH == "high"
    assert SourceReliability.MEDIUM == "medium"
    assert SourceReliability.LOW == "low"


def test_event_id_auto_generated():
    e1 = NormalizedEvent(
        category=EventCategory.NEWS,
        headline="h",
        source="s",
        event_timestamp="2026-05-19T00:00:00Z",
        ingestion_timestamp="2026-05-19T00:00:00Z",
    )
    e2 = NormalizedEvent(
        category=EventCategory.NEWS,
        headline="h",
        source="s",
        event_timestamp="2026-05-19T00:00:00Z",
        ingestion_timestamp="2026-05-19T00:00:00Z",
    )
    assert e1.event_id != e2.event_id
    assert len(e1.event_id) == 36  # UUID format


def test_tags_defaults_to_empty_list():
    event = NormalizedEvent(
        category=EventCategory.MACRO,
        headline="CPI print",
        source="macro_release",
        event_timestamp="2026-05-19T00:00:00Z",
        ingestion_timestamp="2026-05-19T00:00:00Z",
    )
    assert event.tags == []


def test_normalized_event_serializes_to_dict():
    event = NormalizedEvent(
        category=EventCategory.EARNINGS,
        headline="AAPL beat",
        source="earnings_release",
        event_timestamp="2026-05-19T00:00:00Z",
        ingestion_timestamp="2026-05-19T00:00:00Z",
        tags=["beat"],
    )
    d = event.model_dump()
    assert isinstance(d, dict)
    assert d["headline"] == "AAPL beat"
    assert d["tags"] == ["beat"]


def test_is_market_moving_defaults_to_false():
    event = NormalizedEvent(
        category=EventCategory.NEWS,
        headline="Routine update",
        source="news_wire",
        event_timestamp="2026-05-19T00:00:00Z",
        ingestion_timestamp="2026-05-19T00:00:00Z",
    )
    assert event.is_market_moving is False


def test_sentiment_defaults_to_none():
    event = NormalizedEvent(
        category=EventCategory.NEWS,
        headline="Some news",
        source="news_wire",
        event_timestamp="2026-05-19T00:00:00Z",
        ingestion_timestamp="2026-05-19T00:00:00Z",
    )
    assert event.sentiment is None


# ── Adapter tests (12) ─────────────────────────────────────────────────────────

from app.services.ingestion.earnings_adapter import EarningsIngestionAdapter
from app.services.ingestion.news_adapter import NewsIngestionAdapter
from app.services.ingestion.macro_adapter import MacroIngestionAdapter, _MACRO_MARKET_MOVING


def test_earnings_normalize_returns_normalized_event():
    adapter = EarningsIngestionAdapter()
    raw = {
        "ticker": "AAPL",
        "period": "1",
        "actual_eps": 1.50,
        "estimated_eps": 1.40,
        "date": "2026-05-19T20:00:00Z",
    }
    result = adapter.normalize(raw)
    assert result is not None
    assert isinstance(result, NormalizedEvent)
    assert result.ticker == "AAPL"
    assert result.category == EventCategory.EARNINGS


def test_earnings_normalize_returns_none_for_empty_dict():
    adapter = EarningsIngestionAdapter()
    result = adapter.normalize({})
    assert result is None


def test_earnings_normalize_detects_beat():
    adapter = EarningsIngestionAdapter()
    raw = {
        "ticker": "MSFT",
        "period": "2",
        "actual_eps": 2.00,
        "estimated_eps": 1.80,
        "date": "2026-05-19T20:00:00Z",
    }
    result = adapter.normalize(raw)
    assert result is not None
    assert "beat" in result.tags
    assert "beat" in result.headline.lower()


def test_earnings_normalize_detects_miss():
    adapter = EarningsIngestionAdapter()
    raw = {
        "ticker": "TSLA",
        "period": "1",
        "actual_eps": 0.50,
        "estimated_eps": 0.75,
        "date": "2026-05-19T20:00:00Z",
    }
    result = adapter.normalize(raw)
    assert result is not None
    assert "miss" in result.tags
    assert "miss" in result.headline.lower()


def test_earnings_adapter_source_reliability_is_high():
    adapter = EarningsIngestionAdapter()
    assert adapter.source_reliability == "high"


def test_news_normalize_returns_normalized_event():
    adapter = NewsIngestionAdapter()
    raw = {
        "title": "Apple announces new product line",
        "body": "Apple unveiled a new range of products at its annual event.",
        "source": "reuters",
        "published_at": "2026-05-19T14:00:00Z",
        "tickers": ["AAPL"],
    }
    result = adapter.normalize(raw)
    assert result is not None
    assert isinstance(result, NormalizedEvent)
    assert result.ticker == "AAPL"
    assert result.category == EventCategory.NEWS


def test_news_normalize_returns_none_for_no_title():
    adapter = NewsIngestionAdapter()
    raw = {"body": "Some body text", "source": "reuters"}
    result = adapter.normalize(raw)
    assert result is None


def test_news_tag_event_detects_beat():
    adapter = NewsIngestionAdapter()
    tags = adapter._tag_event("Company beat earnings estimates", "")
    assert "beat" in tags


def test_news_tag_event_detects_merger():
    adapter = NewsIngestionAdapter()
    tags = adapter._tag_event("BigCorp announces acquisition of SmallCo", "")
    assert "merger" in tags


def test_macro_normalize_returns_normalized_event():
    adapter = MacroIngestionAdapter()
    raw = {
        "name": "CPI",
        "actual": 3.2,
        "estimate": 3.0,
        "previous": 3.1,
        "date": "2026-05-19T12:30:00Z",
    }
    result = adapter.normalize(raw)
    assert result is not None
    assert isinstance(result, NormalizedEvent)
    assert result.category == EventCategory.MACRO


def test_macro_normalize_ticker_is_none():
    adapter = MacroIngestionAdapter()
    raw = {
        "name": "Nonfarm Payroll",
        "actual": 250000,
        "estimate": 200000,
        "date": "2026-05-19T12:30:00Z",
    }
    result = adapter.normalize(raw)
    assert result is not None
    assert result.ticker is None


def test_macro_market_moving_contains_cpi():
    assert "cpi" in _MACRO_MARKET_MOVING


# ── Access control tests (10) ──────────────────────────────────────────────────

from app.enterprise.access_control import (
    PlanEntitlements, UserAccount, FeatureGate, PlanGateError,
    get_gate, _PLANS,
)


def test_plan_entitlements_free_max_watchlist_slots():
    free = _PLANS["free"]
    assert free.max_watchlist_slots == 5


def test_plan_entitlements_pro_has_morning_brief():
    pro = _PLANS["pro"]
    assert "morning_brief" in pro.features


def test_plan_entitlements_institutional_has_api_access():
    inst = _PLANS["institutional"]
    assert inst.api_access is True


def test_user_account_defaults_to_free_plan():
    user = UserAccount(user_id="u1")
    assert user.plan == "free"


def test_user_account_get_entitlements_returns_correct_plan():
    user = UserAccount(user_id="u2", plan="pro")
    ents = user.get_entitlements()
    assert ents.plan_name == "pro"
    assert ents.max_watchlist_slots == 50


def test_user_account_analysis_limit_not_reached_on_pro():
    user = UserAccount(user_id="u3", plan="pro")
    # Pro has unlimited (0), so limit should never be reached
    for _ in range(100):
        user.increment_analysis_count()
    assert user.analysis_limit_reached() is False


def test_feature_gate_stub_mode_always_passes_check():
    gate = FeatureGate(stub_mode=True)
    assert gate.check("morning_brief") is True
    assert gate.check("api_access") is True
    assert gate.check("nonexistent_feature") is True


def test_feature_gate_require_passes_in_stub_mode():
    gate = FeatureGate(stub_mode=True)
    # Should not raise
    gate.require("morning_brief")
    gate.require("api_access")


def test_feature_gate_non_stub_raises_plan_gate_error():
    user = UserAccount(user_id="u4", plan="free")
    gate = FeatureGate(user=user, stub_mode=False)
    with pytest.raises(PlanGateError) as exc_info:
        gate.require("morning_brief")
    assert exc_info.value.feature == "morning_brief"
    assert exc_info.value.current_plan == "free"


def test_get_gate_none_returns_stub_gate():
    gate = get_gate(None)
    assert gate._stub_mode is True
    assert gate.check("anything") is True
