import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.brief_material_change_service import (
    load_recent_material_changes,
    load_recent_material_changes_from_db,
    merge_material_changes,
)


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


def test_loads_recent_account_scoped_changes_from_durable_feed(monkeypatch):
    calls = []

    async def fake_feed(session, limit, tickers):
        calls.append((session, limit, tickers))
        return {
            "feed": [
                {
                    "ticker": "AAPL",
                    "delta_id": "delta-recent",
                    "created_at": "2026-08-26T15:00:00+00:00",
                    "magnitude": "material",
                    "stance_changed": True,
                    "from_stance": "neutral",
                    "to_stance": "bearish",
                    "conviction_delta": -0.2,
                    "headline": "Stance shifted neutral → bearish. Conviction -20pp.",
                    "concern_tags": ["demand"],
                },
                {
                    "ticker": "MSFT",
                    "delta_id": "cross-account",
                    "created_at": "2026-08-26T15:30:00+00:00",
                    "headline": "Should not escape ticker scope.",
                },
                {
                    "ticker": "AAPL",
                    "delta_id": "too-old",
                    "created_at": "2026-08-24T15:00:00+00:00",
                    "headline": "Old material change.",
                },
            ],
            "next_cursor": None,
            "has_more": False,
        }

    monkeypatch.setattr(
        "app.db.repositories.evolution_repo.get_material_changes_feed",
        fake_feed,
    )
    session = object()

    result = asyncio.run(
        load_recent_material_changes_from_db(
            session,
            [" aapl ", "AAPL"],
            now=NOW,
        )
    )

    assert [change.event_id for change in result] == ["delta-recent"]
    assert result[0].change_type == "thesis_weakened"
    assert result[0].severity == "high"
    assert calls == [(session, 100, ["AAPL"])]


def test_merges_durable_and_timeline_changes_without_duplicates():
    durable = [
        _change(
            "AAPL",
            "2026-08-26T15:00:00Z",
            event_id="shared",
            summary="durable",
        ).data
    ]
    timeline = [
        _change(
            "AAPL",
            "2026-08-26T15:00:00Z",
            event_id="shared",
            summary="timeline",
        ).data,
        _change(
            "MSFT",
            "2026-08-26T15:30:00Z",
            event_id="newer",
        ).data,
    ]

    from app.schemas import MaterialChangeEvent

    result = merge_material_changes(
        [MaterialChangeEvent.model_validate(item) for item in durable],
        [MaterialChangeEvent.model_validate(item) for item in timeline],
    )

    assert [change.event_id for change in result] == ["newer", "shared"]
    assert next(change for change in result if change.event_id == "shared").summary == "durable"
