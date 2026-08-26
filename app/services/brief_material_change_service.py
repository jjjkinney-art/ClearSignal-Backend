"""Load recent, account-scoped material changes for the Morning Brief."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ..schemas import MaterialChangeEvent

logger = logging.getLogger(__name__)


def _parse_timestamp(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return None


def load_recent_material_changes(
    store: object,
    tickers: Iterable[str],
    *,
    lookback_hours: int = 24,
    now: Optional[datetime] = None,
    per_ticker_limit: int = 10,
) -> list[MaterialChangeEvent]:
    """Return recent material changes for the supplied brief universe.

    The store is queried one ticker at a time so a signed-in account can never
    inherit changes belonging only to the process-wide legacy watchlist.
    Malformed records and per-ticker storage failures are ignored.
    """
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)
    cutoff = reference - timedelta(hours=max(0, lookback_hours))

    normalized_tickers = list(
        dict.fromkeys(
            ticker.strip().upper()
            for ticker in tickers
            if isinstance(ticker, str) and ticker.strip()
        )
    )
    changes: list[MaterialChangeEvent] = []
    seen_event_ids: set[str] = set()

    for ticker in normalized_tickers:
        try:
            entries = store.load(ticker, entry_type="material_change") or []
        except Exception as exc:
            logger.warning(
                "Morning Brief material-change load failed for %s: %s",
                ticker,
                exc,
            )
            continue

        entries = sorted(
            entries,
            key=lambda entry: getattr(entry, "timestamp", "") or "",
            reverse=True,
        )[: max(0, per_ticker_limit)]

        for entry in entries:
            try:
                change = MaterialChangeEvent.model_validate(entry.data)
            except Exception as exc:
                logger.warning(
                    "Morning Brief ignored malformed material change for %s: %s",
                    ticker,
                    exc,
                )
                continue

            timestamp = _parse_timestamp(change.timestamp)
            if timestamp is None or timestamp < cutoff or timestamp > reference:
                continue
            if change.ticker.strip().upper() != ticker:
                continue
            if change.event_id in seen_event_ids:
                continue

            seen_event_ids.add(change.event_id)
            changes.append(change)

    changes.sort(key=lambda change: change.timestamp, reverse=True)
    return changes
