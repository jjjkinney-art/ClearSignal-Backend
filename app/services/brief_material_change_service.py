"""Load recent, account-scoped material changes for the Morning Brief."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

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


def _normalize_tickers(tickers: Iterable[str]) -> list[str]:
    return list(
        dict.fromkeys(
            ticker.strip().upper()
            for ticker in tickers
            if isinstance(ticker, str) and ticker.strip()
        )
    )


def _reference_window(
    lookback_hours: int,
    now: Optional[datetime],
) -> tuple[datetime, datetime]:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)
    return reference, reference - timedelta(hours=max(0, lookback_hours))


def load_recent_material_changes(
    store: object,
    tickers: Iterable[str],
    *,
    lookback_hours: int = 24,
    now: Optional[datetime] = None,
    per_ticker_limit: int = 10,
) -> list[MaterialChangeEvent]:
    """Return recent material changes from the legacy timeline store.

    This remains a fallback for local development and in-flight events. The
    durable database feed is loaded separately in production.
    """
    reference, cutoff = _reference_window(lookback_hours, now)
    normalized_tickers = _normalize_tickers(tickers)
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


def _feed_item_to_material_change(
    item: Mapping[str, Any],
) -> Optional[MaterialChangeEvent]:
    """Convert a durable ThesisDelta feed item without inventing new claims."""
    ticker = str(item.get("ticker") or "").strip().upper()
    event_id = str(item.get("delta_id") or "").strip()
    timestamp = str(item.get("created_at") or "").strip()
    summary = str(item.get("headline") or "").strip()
    if not ticker or not event_id or not timestamp or not summary:
        return None

    try:
        conviction_delta = float(item.get("conviction_delta") or 0.0)
    except (TypeError, ValueError):
        conviction_delta = 0.0

    stance_changed = bool(item.get("stance_changed"))
    to_stance = str(item.get("to_stance") or "").strip().lower()
    negative_stances = {"bearish", "negative", "cautious", "underweight", "sell"}
    positive_stances = {"bullish", "positive", "constructive", "overweight", "buy"}

    if to_stance in negative_stances:
        change_type = "thesis_weakened"
        change_category = "thesis_broke" if stance_changed else "new_risk_emerged"
    elif to_stance in positive_stances or conviction_delta > 0:
        change_type = "thesis_strengthened"
        change_category = "thesis_strengthened"
    elif conviction_delta < 0:
        change_type = "confidence_collapse"
        change_category = "new_risk_emerged"
    elif stance_changed:
        change_type = "trend_flip"
        change_category = "market_repriced"
    else:
        change_type = "stable"
        change_category = "market_repriced"

    severity = "high" if stance_changed or abs(conviction_delta) >= 0.15 else "medium"
    drivers = [
        str(tag).strip()
        for tag in (item.get("concern_tags") or [])
        if str(tag).strip()
    ]

    try:
        return MaterialChangeEvent(
            event_id=event_id,
            ticker=ticker,
            severity=severity,
            summary=summary,
            drivers=drivers,
            timestamp=timestamp,
            change_type=change_type,
            confidence_change=conviction_delta,
            thesis_trend_changed=stance_changed,
            materiality_score=min(1.0, max(0.7, abs(conviction_delta))),
            change_category=change_category,
        )
    except Exception as exc:
        logger.warning(
            "Morning Brief ignored malformed durable material change for %s: %s",
            ticker,
            exc,
        )
        return None


async def load_recent_material_changes_from_db(
    session: object,
    tickers: Iterable[str],
    *,
    lookback_hours: int = 24,
    now: Optional[datetime] = None,
    limit: int = 100,
) -> list[MaterialChangeEvent]:
    """Load recent material ThesisDelta rows from durable Postgres storage."""
    normalized_tickers = _normalize_tickers(tickers)
    if session is None or not normalized_tickers or limit <= 0:
        return []

    reference, cutoff = _reference_window(lookback_hours, now)
    try:
        from ..db.repositories.evolution_repo import get_material_changes_feed

        payload = await get_material_changes_feed(
            session,
            limit=max(1, limit),
            tickers=normalized_tickers,
        )
    except Exception as exc:
        logger.warning("Morning Brief durable material-change load failed: %s", exc)
        return []

    changes: list[MaterialChangeEvent] = []
    seen_event_ids: set[str] = set()
    for item in payload.get("feed", []) if isinstance(payload, dict) else []:
        if not isinstance(item, Mapping):
            continue
        change = _feed_item_to_material_change(item)
        if change is None or change.ticker not in normalized_tickers:
            continue
        timestamp = _parse_timestamp(change.timestamp)
        if timestamp is None or timestamp < cutoff or timestamp > reference:
            continue
        if change.event_id in seen_event_ids:
            continue
        seen_event_ids.add(change.event_id)
        changes.append(change)

    changes.sort(key=lambda change: change.timestamp, reverse=True)
    return changes


def merge_material_changes(
    *change_groups: Iterable[MaterialChangeEvent],
) -> list[MaterialChangeEvent]:
    """Merge durable and fallback feeds, preferring the first occurrence."""
    merged: list[MaterialChangeEvent] = []
    seen_event_ids: set[str] = set()
    for group in change_groups:
        for change in group:
            if change.event_id in seen_event_ids:
                continue
            seen_event_ids.add(change.event_id)
            merged.append(change)
    merged.sort(key=lambda change: change.timestamp, reverse=True)
    return merged
