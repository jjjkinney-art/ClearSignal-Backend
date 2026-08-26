"""Resolve the ticker universe for a morning brief.

Signed-in users must never inherit the process-wide legacy watchlist.  Their
account rows are authoritative; an explicit browser-provided list is accepted
only as a migration fallback when the account has no persisted rows yet.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

from app.schemas import WatchlistEntry

_TICKER = re.compile(r"^[A-Z][A-Z0-9.-]{0,4}$")
_MAX_TICKERS = 20


def parse_ticker_csv(raw: Optional[str]) -> List[str]:
    """Return a validated, de-duplicated ticker list (maximum 20)."""
    result: List[str] = []
    seen: set[str] = set()
    for value in (raw or "").split(","):
        ticker = value.strip().upper()
        if not _TICKER.fullmatch(ticker) or ticker in seen:
            continue
        result.append(ticker)
        seen.add(ticker)
        if len(result) >= _MAX_TICKERS:
            break
    return result


def _entries_for_tickers(
    tickers: Iterable[str],
    metadata_entries: Iterable[WatchlistEntry],
) -> List[WatchlistEntry]:
    by_ticker = {entry.ticker.upper(): entry for entry in metadata_entries}
    return [
        by_ticker.get(ticker)
        or WatchlistEntry(ticker=ticker, company_name=ticker)
        for ticker in tickers
    ]


def resolve_brief_entries(
    *,
    account_entries: Iterable[WatchlistEntry],
    requested_tickers: Iterable[str],
    legacy_entries: Iterable[WatchlistEntry],
    authenticated: bool,
) -> tuple[List[WatchlistEntry], str]:
    """Return (entries, scope) without crossing account boundaries."""
    account = list(account_entries)
    requested = list(requested_tickers)
    legacy = list(legacy_entries)

    if authenticated:
        if account:
            # Persisted account rows are already constrained by entitlements.
            # Paid accounts can exceed the browser-input safety cap, and their
            # Morning Brief must cover the complete account watchlist.
            return account, "account"
        if requested:
            return _entries_for_tickers(requested, legacy), "browser_fallback"
        return [], "account"

    if requested:
        return _entries_for_tickers(requested, legacy), "browser"
    return legacy[:_MAX_TICKERS], "legacy"
