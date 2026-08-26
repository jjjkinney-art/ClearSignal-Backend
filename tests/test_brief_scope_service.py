from app.schemas import WatchlistEntry
from app.services.brief_scope_service import parse_ticker_csv, resolve_brief_entries


def _entry(ticker: str, name: str = "") -> WatchlistEntry:
    return WatchlistEntry(ticker=ticker, company_name=name or ticker)


def test_parse_ticker_csv_validates_deduplicates_and_caps():
    raw = ",".join(["aapl", "AAPL", "bad ticker", "NVDA"] + [f"X{i}" for i in range(25)])
    result = parse_ticker_csv(raw)
    assert result[:2] == ["AAPL", "NVDA"]
    assert len(result) == 20
    assert "BAD TICKER" not in result


def test_authenticated_account_entries_are_authoritative():
    entries, scope = resolve_brief_entries(
        account_entries=[_entry("AAPL", "Apple")],
        requested_tickers=["NVDA"],
        legacy_entries=[_entry("TSLA")],
        authenticated=True,
    )
    assert [entry.ticker for entry in entries] == ["AAPL"]
    assert scope == "account"


def test_authenticated_account_entries_are_not_silently_capped():
    account_entries = [_entry(f"X{i}") for i in range(24)]

    entries, scope = resolve_brief_entries(
        account_entries=account_entries,
        requested_tickers=[],
        legacy_entries=[],
        authenticated=True,
    )

    assert [entry.ticker for entry in entries] == [f"X{i}" for i in range(24)]
    assert scope == "account"


def test_authenticated_empty_account_never_inherits_legacy_watchlist():
    entries, scope = resolve_brief_entries(
        account_entries=[],
        requested_tickers=[],
        legacy_entries=[_entry("TSLA")],
        authenticated=True,
    )
    assert entries == []
    assert scope == "account"


def test_authenticated_browser_fallback_preserves_known_metadata():
    entries, scope = resolve_brief_entries(
        account_entries=[],
        requested_tickers=["NVDA", "AAPL"],
        legacy_entries=[_entry("NVDA", "NVIDIA")],
        authenticated=True,
    )
    assert [entry.ticker for entry in entries] == ["NVDA", "AAPL"]
    assert entries[0].company_name == "NVIDIA"
    assert scope == "browser_fallback"


def test_unauthenticated_legacy_compatibility_remains_available():
    entries, scope = resolve_brief_entries(
        account_entries=[],
        requested_tickers=[],
        legacy_entries=[_entry("TSLA")],
        authenticated=False,
    )
    assert [entry.ticker for entry in entries] == ["TSLA"]
    assert scope == "legacy"
