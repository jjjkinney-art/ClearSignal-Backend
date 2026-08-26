from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.brief_material_change_service import load_recent_material_changes


NOW = datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc)


def _change(
    ticker: str,
    timestamp: str,
    *,
    event_id: str,
    summary: str = "The core debate changed",
) -> SimpleNamespace:
    return SimpleNamespace(
        timestamp=timestamp,
        data={
            "event_id": event_id,
            "ticker": ticker,
            "severity": "high",
            "summary": summary,
            "drivers": ["demand"],
            "timestamp": timestamp,
            "change_type": "trend_flip",
            "materiality_score": 0.75,
            "change_category": "market_repriced",
        },
    )


class FakeStore:
    def __init__(self, entries_by_ticker):
        self.entries_by_ticker = entries_by_ticker
        self.calls = []

    def load(self, ticker, *, entry_type):
        self.calls.append((ticker, entry_type))
        value = self.entries_by_ticker.get(ticker, [])
        if isinstance(value, Exception):
            raise value
        return value


def test_loads_only_recent_changes_for_requested_tickers():
    store = FakeStore(
        {
            "AAPL": [
                _change("AAPL", "2026-08-26T15:00:00Z", event_id="recent"),
                _change("AAPL", "2026-08-24T15:00:00Z", event_id="old"),
            ],
            "NVDA": [_change("NVDA", "2026-08-26T14:00:00Z", event_id="other")],
        }
    )

    result = load_recent_material_changes(store, [" aapl ", "AAPL"], now=NOW)

    assert [change.event_id for change in result] == ["recent"]
    assert store.calls == [("AAPL", "material_change")]


def test_sorts_changes_newest_first_and_ignores_bad_records():
    store = FakeStore(
        {
            "AAPL": [
                SimpleNamespace(timestamp="bad", data={"ticker": "AAPL"}),
                _change("AAPL", "2026-08-26T13:00:00Z", event_id="older"),
            ],
            "MSFT": [_change("MSFT", "2026-08-26T15:30:00Z", event_id="newer")],
            "BROKEN": RuntimeError("unavailable"),
        }
    )

    result = load_recent_material_changes(store, ["AAPL", "MSFT", "BROKEN"], now=NOW)

    assert [change.event_id for change in result] == ["newer", "older"]


def test_rejects_cross_ticker_records_and_future_changes():
    store = FakeStore(
        {
            "AAPL": [
                _change("MSFT", "2026-08-26T15:00:00Z", event_id="wrong-ticker"),
                _change("AAPL", "2026-08-26T17:00:00Z", event_id="future"),
            ]
        }
    )

    assert load_recent_material_changes(store, ["AAPL"], now=NOW) == []


def test_zero_per_ticker_limit_returns_no_changes():
    store = FakeStore(
        {"AAPL": [_change("AAPL", "2026-08-26T15:00:00Z", event_id="recent")]}
    )

    assert load_recent_material_changes(
        store,
        ["AAPL"],
        now=NOW,
        per_ticker_limit=0,
    ) == []
