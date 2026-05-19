"""
Phase K backend tests — history_service, watchlist_themes, usage_tracking,
and API endpoint smoke tests.

All tests are deterministic (no LLM calls, no network).
"""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

# ── HistoryEntry + history_service ───────────────────────────────────────────

from app.services.history_service import (
    HistoryEntry,
    get_analysis_history,
    get_history_summary,
    get_recent_tickers,
    get_ticker_history,
)
from app.services.watchlist_themes import (
    WatchlistThemeGroup,
    classify_ticker_theme,
    group_watchlist_by_theme,
)
from app.services.usage_tracking import (
    UsageEvent,
    UsageTracker,
    usage_tracker,
)


# =============================================================================
# HistoryEntry tests (8)
# =============================================================================

def test_history_entry_has_required_fields():
    """HistoryEntry has all required fields."""
    entry = HistoryEntry(ticker="AAPL", timestamp="2024-01-01T00:00:00", entry_type="thesis_snapshot")
    assert hasattr(entry, "ticker")
    assert hasattr(entry, "timestamp")
    assert hasattr(entry, "entry_type")
    assert hasattr(entry, "one_sentence_thesis")
    assert hasattr(entry, "core_takeaway")
    assert hasattr(entry, "dominant_driver")
    assert hasattr(entry, "drift_state")
    assert hasattr(entry, "confidence_score")
    assert hasattr(entry, "change_summary")
    assert hasattr(entry, "core_debate")
    assert hasattr(entry, "snapshot_id")
    assert hasattr(entry, "change_id")


def test_history_entry_entry_id_auto_generated_as_uuid():
    """entry_id is auto-generated as a UUID string."""
    entry = HistoryEntry(ticker="AAPL", timestamp="2024-01-01T00:00:00", entry_type="thesis_snapshot")
    # Should be a valid UUID
    parsed = uuid.UUID(entry.entry_id)
    assert str(parsed) == entry.entry_id


def test_get_analysis_history_returns_empty_list_when_no_data(tmp_path, monkeypatch):
    """get_analysis_history() returns empty list when no data."""
    from app.services import history_service
    from app.services.timeline_store import JsonFileTimelineStore
    empty_store = JsonFileTimelineStore(str(tmp_path / "empty_timeline"))
    monkeypatch.setattr(history_service, "default_store", empty_store)
    result = get_analysis_history()
    assert result == []


def test_get_analysis_history_never_raises():
    """get_analysis_history() never raises regardless of state."""
    try:
        result = get_analysis_history()
        assert isinstance(result, list)
    except Exception as exc:
        pytest.fail(f"get_analysis_history() raised: {exc}")


def test_get_history_summary_returns_dict_with_total_tickers_key(tmp_path, monkeypatch):
    """get_history_summary() returns dict with total_tickers key."""
    from app.services import history_service
    from app.services.timeline_store import JsonFileTimelineStore
    empty_store = JsonFileTimelineStore(str(tmp_path / "empty_timeline"))
    monkeypatch.setattr(history_service, "default_store", empty_store)
    result = get_history_summary()
    assert isinstance(result, dict)
    assert "total_tickers" in result


def test_get_history_summary_returns_dict_with_total_entries_key(tmp_path, monkeypatch):
    """get_history_summary() returns dict with total_entries key."""
    from app.services import history_service
    from app.services.timeline_store import JsonFileTimelineStore
    empty_store = JsonFileTimelineStore(str(tmp_path / "empty_timeline"))
    monkeypatch.setattr(history_service, "default_store", empty_store)
    result = get_history_summary()
    assert "total_entries" in result


def test_get_recent_tickers_returns_list_when_empty(tmp_path, monkeypatch):
    """get_recent_tickers() returns list (even empty)."""
    from app.services import history_service
    from app.services.timeline_store import JsonFileTimelineStore
    empty_store = JsonFileTimelineStore(str(tmp_path / "empty_timeline"))
    monkeypatch.setattr(history_service, "default_store", empty_store)
    result = get_recent_tickers()
    assert isinstance(result, list)


def test_get_ticker_history_returns_list_when_empty(tmp_path, monkeypatch):
    """get_ticker_history() returns list (even empty)."""
    from app.services import history_service
    from app.services.timeline_store import JsonFileTimelineStore
    empty_store = JsonFileTimelineStore(str(tmp_path / "empty_timeline"))
    monkeypatch.setattr(history_service, "default_store", empty_store)
    result = get_ticker_history("AAPL")
    assert isinstance(result, list)


# =============================================================================
# Thematic grouping tests (15)
# =============================================================================

def test_classify_ticker_nvda_is_ai_infrastructure():
    assert classify_ticker_theme("NVDA", "") == "ai_infrastructure"


def test_classify_ticker_aapl_is_mega_cap_tech():
    assert classify_ticker_theme("AAPL", "") == "mega_cap_tech"


def test_classify_ticker_jpm_is_financial():
    assert classify_ticker_theme("JPM", "") == "financial"


def test_classify_ticker_xom_is_energy_commodities():
    assert classify_ticker_theme("XOM", "") == "energy_commodities"


def test_classify_ticker_unh_is_healthcare_biotech():
    assert classify_ticker_theme("UNH", "") == "healthcare_biotech"


def test_classify_ticker_tsla_is_consumer_cyclical():
    assert classify_ticker_theme("TSLA", "") == "consumer_cyclical"


def test_classify_ticker_rklb_is_rate_sensitive():
    assert classify_ticker_theme("RKLB", "") == "rate_sensitive"


def test_classify_ticker_unknown_returns_other():
    assert classify_ticker_theme("UNKNOWN", "") == "other"


def test_classify_ticker_empty_ticker_nvidia_name_fallback():
    """classify_ticker_theme("", "NVIDIA Corporation") returns ai_infrastructure via name fallback."""
    result = classify_ticker_theme("", "NVIDIA Corporation")
    assert result == "ai_infrastructure"


def test_classify_ticker_empty_ticker_bank_name_fallback():
    """classify_ticker_theme("", "Bank of America") returns financial via name fallback."""
    result = classify_ticker_theme("", "Bank of America")
    assert result == "financial"


def test_group_watchlist_by_theme_empty_returns_empty():
    """group_watchlist_by_theme([]) returns []."""
    result = group_watchlist_by_theme([])
    assert result == []


def test_group_watchlist_by_theme_single_returns_one_group():
    """group_watchlist_by_theme with one entry returns 1 group."""
    result = group_watchlist_by_theme([{"ticker": "NVDA", "company_name": ""}])
    assert len(result) == 1
    assert result[0].theme_key == "ai_infrastructure"


def test_group_watchlist_by_theme_mixed_tickers_correct_labels():
    """group_watchlist_by_theme with mixed tickers returns correct theme labels."""
    entries = [
        {"ticker": "NVDA", "company_name": ""},
        {"ticker": "AAPL", "company_name": ""},
        {"ticker": "JPM", "company_name": ""},
    ]
    result = group_watchlist_by_theme(entries)
    theme_keys = {g.theme_key for g in result}
    assert "ai_infrastructure" in theme_keys
    assert "mega_cap_tech" in theme_keys
    assert "financial" in theme_keys


def test_watchlist_theme_group_has_required_fields():
    """WatchlistThemeGroup has theme_key, theme_label, tickers fields."""
    group = WatchlistThemeGroup(
        theme_key="ai_infrastructure",
        theme_label="AI Infrastructure",
        description="GPU supply chain",
        macro_sensitivity="CapEx risk",
        tickers=["NVDA"],
        ticker_count=1,
    )
    assert hasattr(group, "theme_key")
    assert hasattr(group, "theme_label")
    assert hasattr(group, "tickers")
    assert group.theme_key == "ai_infrastructure"
    assert group.theme_label == "AI Infrastructure"
    assert "NVDA" in group.tickers


def test_other_theme_appears_last_when_multiple_themes():
    """'other' theme always appears last when multiple themes are present."""
    entries = [
        {"ticker": "NVDA", "company_name": ""},
        {"ticker": "AAPL", "company_name": ""},
        {"ticker": "ZZZZ", "company_name": ""},   # unknown → other
    ]
    result = group_watchlist_by_theme(entries)
    assert len(result) > 1
    assert result[-1].theme_key == "other"


# =============================================================================
# UsageTracker tests (12)
# =============================================================================

def test_usage_tracker_track_records_event():
    """UsageTracker.track() records event and increments totals."""
    tracker = UsageTracker(window_seconds=60)
    event = UsageEvent(user_id="u1", event_type="analysis", ticker="AAPL")
    tracker.track(event)
    assert tracker.get_totals().get("analysis", 0) == 1


def test_usage_tracker_get_user_count_returns_zero_for_unknown():
    """UsageTracker.get_user_count() returns 0 for unknown user."""
    tracker = UsageTracker(window_seconds=60)
    assert tracker.get_user_count("nobody", "analysis") == 0


def test_usage_tracker_check_rate_limit_returns_true_when_under():
    """UsageTracker.check_rate_limit() returns True when under limit."""
    tracker = UsageTracker(window_seconds=60)
    # No events tracked yet — should be under any limit
    assert tracker.check_rate_limit("u1", "analysis", max_per_window=5) is True


def test_usage_tracker_check_rate_limit_returns_false_when_over():
    """UsageTracker.check_rate_limit() returns False when over limit."""
    tracker = UsageTracker(window_seconds=60)
    event = UsageEvent(user_id="u1", event_type="analysis")
    # Track 3 events
    for _ in range(3):
        tracker.track(event)
    # Limit of 3 means we've hit exactly the limit (len(dq) < 3 is False after 3)
    assert tracker.check_rate_limit("u1", "analysis", max_per_window=3) is False


def test_usage_tracker_get_totals_returns_dict():
    """UsageTracker.get_totals() returns dict."""
    tracker = UsageTracker(window_seconds=60)
    result = tracker.get_totals()
    assert isinstance(result, dict)


def test_usage_event_has_required_fields():
    """UsageEvent has user_id, event_type, timestamp fields."""
    event = UsageEvent(user_id="u1", event_type="analysis", ticker="AAPL")
    assert event.user_id == "u1"
    assert event.event_type == "analysis"
    assert isinstance(event.timestamp, float)


def test_usage_tracker_register_hook_fires_on_track():
    """UsageTracker.register_hook() fires callback on track()."""
    tracker = UsageTracker(window_seconds=60)
    fired = []
    tracker.register_hook(lambda e: fired.append(e.event_type))
    event = UsageEvent(user_id="u1", event_type="watchlist_add")
    tracker.track(event)
    assert fired == ["watchlist_add"]


def test_usage_tracker_hook_failure_does_not_raise():
    """Hook failure does not propagate and cause track() to raise."""
    tracker = UsageTracker(window_seconds=60)

    def bad_hook(e):
        raise RuntimeError("hook error")

    tracker.register_hook(bad_hook)
    event = UsageEvent(user_id="u1", event_type="analysis")
    try:
        tracker.track(event)  # should not raise
    except Exception as exc:
        pytest.fail(f"track() raised due to hook failure: {exc}")


def test_usage_tracker_totals_accumulate():
    """Totals accumulate across multiple track() calls."""
    tracker = UsageTracker(window_seconds=60)
    for _ in range(5):
        tracker.track(UsageEvent(user_id="u1", event_type="brief_view"))
    assert tracker.get_totals()["brief_view"] == 5


def test_usage_tracker_window_expiry():
    """Events outside the window don't count toward the rate limit."""
    tracker = UsageTracker(window_seconds=1)  # 1-second window
    # Manually inject an old timestamp into the deque
    from collections import deque
    key = "u1:analysis"
    tracker._events[key] = deque([time.time() - 10])  # 10s old event
    # Should be pruned → within limit
    assert tracker.check_rate_limit("u1", "analysis", max_per_window=1) is True


def test_usage_tracker_module_singleton_is_instance():
    """module-level usage_tracker is a UsageTracker instance."""
    assert isinstance(usage_tracker, UsageTracker)


def test_usage_tracker_multiple_event_types_tracked_independently():
    """Multiple event types tracked independently."""
    tracker = UsageTracker(window_seconds=60)
    tracker.track(UsageEvent(user_id="u1", event_type="analysis"))
    tracker.track(UsageEvent(user_id="u1", event_type="analysis"))
    tracker.track(UsageEvent(user_id="u1", event_type="watchlist_add"))
    totals = tracker.get_totals()
    assert totals.get("analysis", 0) == 2
    assert totals.get("watchlist_add", 0) == 1


# =============================================================================
# API endpoint tests (5)
# =============================================================================

@pytest.fixture(scope="module")
def client():
    from app.main import create_app
    app = create_app()
    return TestClient(app)


def test_api_history_returns_list(client):
    """GET /history returns list."""
    response = client.get("/history")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_history_summary_returns_dict(client):
    """GET /history/summary returns dict."""
    response = client.get("/history/summary")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_api_watchlist_themes_returns_list(client):
    """GET /watchlist/themes returns list."""
    response = client.get("/watchlist/themes")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_usage_stats_returns_dict(client):
    """GET /usage/stats returns dict."""
    response = client.get("/usage/stats")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_api_endpoints_no_500_when_no_data(client):
    """Endpoints never return 500 when no data."""
    for path in ["/history", "/history/summary", "/watchlist/themes", "/usage/stats"]:
        response = client.get(path)
        assert response.status_code != 500, f"{path} returned 500"
