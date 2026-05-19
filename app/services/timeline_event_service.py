"""
Timeline event service — convert MaterialChangeEvent and ThesisDiff objects
into structured TimelineEvent objects for thesis history visualisation.

All functions are deterministic (no LLM calls) and defensive against
empty or None inputs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from ..schemas import AlertPriority, MaterialChangeEvent, ThesisDiff, TimelineEvent
from .timeline_store import JsonFileTimelineStore, TimelineEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event-type mapping helpers
# ---------------------------------------------------------------------------

_CATEGORY_TO_EVENT_TYPE = {
    "thesis_broke":        "thesis_shift",
    "market_repriced":     "market_repriced",
    "new_risk_emerged":    "new_risk",
    "thesis_strengthened": "thesis_shift",
    "cosmetic":            "thesis_shift",
}

_CATEGORY_TO_SEVERITY = {
    "thesis_broke":        "critical",
    "market_repriced":     "high",
    "new_risk_emerged":    "high",
    "thesis_strengthened": "medium",
    "cosmetic":            "low",
}

_CHANGE_TYPE_TO_EVENT_TYPE = {
    "confidence_collapse":   "thesis_shift",
    "top_signal_replaced":   "narrative_transition",
    "thesis_weakened":       "thesis_shift",
    "thesis_strengthened":   "thesis_shift",
    "new_structural_risk":   "new_risk",
    "trend_flip":            "thesis_shift",
    "stable":                "thesis_shift",
}

_CHANGE_TYPE_TO_SEVERITY = {
    "confidence_collapse":   "critical",
    "top_signal_replaced":   "medium",
    "thesis_weakened":       "high",
    "thesis_strengthened":   "medium",
    "new_structural_risk":   "high",
    "trend_flip":            "high",
    "stable":                "low",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate_title(title: str, max_len: int = 60) -> str:
    if len(title) <= max_len:
        return title
    return title[:max_len - 1].rstrip() + "…"


def _make_title(event_type: str, ticker: str, change_type: str = "", category: str = "") -> str:
    """Build a brief institutional title (≤60 chars)."""
    t = ticker.upper()
    if event_type == "thesis_shift":
        if change_type == "confidence_collapse" or category == "thesis_broke":
            return _truncate_title(f"{t}: Conviction collapsed")
        return _truncate_title(f"{t}: Thesis direction reversed")
    elif event_type == "market_repriced":
        return _truncate_title(f"{t}: Market repriced — thesis intact")
    elif event_type == "new_risk":
        return _truncate_title(f"{t}: New structural risk emerged")
    elif event_type == "narrative_transition":
        return _truncate_title(f"{t}: Core debate shifted")
    elif event_type == "regime_change":
        return _truncate_title(f"{t}: Regime transition detected")
    elif event_type == "earnings_event":
        return _truncate_title(f"{t}: Earnings event")
    elif event_type == "catalyst_confirmed":
        return _truncate_title(f"{t}: Catalyst confirmed")
    elif event_type == "catalyst_failed":
        return _truncate_title(f"{t}: Catalyst failed")
    else:
        return _truncate_title(f"{t}: Thesis update")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def events_from_material_change(change: MaterialChangeEvent) -> List[TimelineEvent]:
    """Convert a MaterialChangeEvent into 1-2 TimelineEvents.

    Returns an empty list if *change* is None or malformed.
    """
    if change is None:
        return []

    try:
        ticker    = (change.ticker or "").upper()
        timestamp = change.timestamp or _now_iso()
        category  = change.change_category or ""
        ch_type   = change.change_type or ""

        events: List[TimelineEvent] = []

        # ── Primary event from change_category ──────────────────────────────
        event_type = _CATEGORY_TO_EVENT_TYPE.get(category, _CHANGE_TYPE_TO_EVENT_TYPE.get(ch_type, "thesis_shift"))
        severity   = _CATEGORY_TO_SEVERITY.get(category, _CHANGE_TYPE_TO_SEVERITY.get(ch_type, "medium"))

        body = change.summary or f"{ticker}: material change detected."

        title = _make_title(event_type, ticker, change_type=ch_type, category=category)

        primary = TimelineEvent(
            ticker=ticker,
            event_type=event_type,
            title=title,
            body=body,
            severity=severity,
            timestamp=timestamp,
            metadata={
                "change_type":      ch_type,
                "change_category":  category,
                "materiality_score": change.materiality_score,
                "confidence_change": change.confidence_change,
                "drivers":          change.drivers or [],
            },
            source_material_change_id=change.event_id,
            source_snapshot_id=change.current_snapshot_id,
        )
        events.append(primary)

        # ── Secondary event: if top_signal_replaced + debate-type category
        # emit a narrative_transition on top of a thesis_shift
        if ch_type == "top_signal_replaced" and event_type != "narrative_transition":
            secondary = TimelineEvent(
                ticker=ticker,
                event_type="narrative_transition",
                title=_make_title("narrative_transition", ticker),
                body=f"{ticker}: dominant signal replaced — narrative anchor shifted.",
                severity="medium",
                timestamp=timestamp,
                metadata={"derived_from": primary.event_id},
                source_material_change_id=change.event_id,
            )
            events.append(secondary)

        return events

    except Exception as exc:
        logger.warning("events_from_material_change failed: %s", exc)
        return []


def events_from_thesis_diff(
    ticker: str,
    diff: ThesisDiff,
    timestamp: str,
) -> List[TimelineEvent]:
    """Extract TimelineEvents from a ThesisDiff.

    Returns an empty list when *diff* is None or no significant changes
    are detected.
    """
    if diff is None or not ticker:
        return []

    try:
        t      = ticker.upper()
        ts     = timestamp or _now_iso()
        events: List[TimelineEvent] = []

        # ── Confidence collapse ─────────────────────────────────────────────
        if diff.confidence_change <= -0.25:
            ev = TimelineEvent(
                ticker=t,
                event_type="thesis_shift",
                title=_truncate_title(f"{t}: Conviction collapsed"),
                body=f"{t}: confidence fell sharply — conviction level critically weakened.",
                severity="critical",
                timestamp=ts,
                metadata={"confidence_change": diff.confidence_change},
            )
            events.append(ev)

        # ── Core debate shifted ─────────────────────────────────────────────
        if diff.core_debate_shifted:
            body = f"{t}: Core debate shifted"
            if diff.prev_core_debate and diff.curr_core_debate:
                body = (
                    f"{t}: debate moved from '{diff.prev_core_debate[:60]}' "
                    f"to '{diff.curr_core_debate[:60]}'."
                )
            ev = TimelineEvent(
                ticker=t,
                event_type="narrative_transition",
                title=_truncate_title(f"{t}: Core debate shifted"),
                body=body,
                severity="high",
                timestamp=ts,
                metadata={
                    "prev_core_debate": diff.prev_core_debate,
                    "curr_core_debate": diff.curr_core_debate,
                },
            )
            events.append(ev)

        # ── Trend flipped ───────────────────────────────────────────────────
        if diff.trend_flipped:
            ev = TimelineEvent(
                ticker=t,
                event_type="thesis_shift",
                title=_truncate_title(f"{t}: Thesis direction reversed"),
                body=f"{t}: thesis trend flipped — directional conviction reversed.",
                severity="high",
                timestamp=ts,
                metadata={"thesis_trend": diff.thesis_trend},
            )
            events.append(ev)

        # ── Top signal replaced ─────────────────────────────────────────────
        if diff.top_signal_replaced and not diff.trend_flipped:
            ev = TimelineEvent(
                ticker=t,
                event_type="narrative_transition",
                title=_truncate_title(f"{t}: Core debate shifted"),
                body=f"{t}: dominant signal replaced — narrative anchor shifted.",
                severity="medium",
                timestamp=ts,
                metadata={"top_signal_replaced": True},
            )
            events.append(ev)

        # ── New risks ───────────────────────────────────────────────────────
        if diff.new_risks and not any(e.event_type == "new_risk" for e in events):
            risk_count = len(diff.new_risks)
            body = f"{t}: {risk_count} new risk{'s' if risk_count > 1 else ''} identified — {diff.new_risks[0][:80]}."
            ev = TimelineEvent(
                ticker=t,
                event_type="new_risk",
                title=_truncate_title(f"{t}: New structural risk emerged"),
                body=body,
                severity="high",
                timestamp=ts,
                metadata={"new_risks": diff.new_risks},
            )
            events.append(ev)

        return events

    except Exception as exc:
        logger.warning("events_from_thesis_diff failed: %s", exc)
        return []


def get_ticker_timeline(
    ticker: str,
    store: Optional[JsonFileTimelineStore] = None,
    limit: int = 50,
) -> List[TimelineEvent]:
    """Load timeline entries for a ticker and convert to TimelineEvents.

    Falls back to an empty list when no data exists or on any error.
    """
    if not ticker:
        return []

    try:
        from .timeline_store import default_store as _default_store
        backend = store if store is not None else _default_store

        t = ticker.upper()
        raw_entries = backend.load(t)

        timeline_events: List[TimelineEvent] = []

        for entry in raw_entries:
            if entry.entry_type == "timeline_event":
                # Already a TimelineEvent record
                try:
                    ev = TimelineEvent.model_validate(entry.data)
                    timeline_events.append(ev)
                except Exception as parse_exc:
                    logger.debug("get_ticker_timeline: skip malformed timeline_event: %s", parse_exc)

            elif entry.entry_type == "material_change":
                try:
                    change = MaterialChangeEvent.model_validate(entry.data)
                    evs = events_from_material_change(change)
                    timeline_events.extend(evs)
                except Exception as parse_exc:
                    logger.debug("get_ticker_timeline: skip malformed material_change: %s", parse_exc)

        # Sort newest-first, return limited
        timeline_events.sort(key=lambda e: e.timestamp or "", reverse=True)
        return timeline_events[:limit]

    except Exception as exc:
        logger.warning("get_ticker_timeline failed for %s: %s", ticker, exc)
        return []


def save_timeline_event(
    event: TimelineEvent,
    store: Optional[JsonFileTimelineStore] = None,
) -> str:
    """Persist a TimelineEvent to the timeline store.

    Returns the entry_id; never raises.
    """
    try:
        from .timeline_store import default_store as _default_store
        backend = store if store is not None else _default_store

        entry = TimelineEntry(
            ticker=event.ticker.upper(),
            entry_type="timeline_event",
            timestamp=event.timestamp or datetime.now(timezone.utc).isoformat(),
            data=event.model_dump(),
            metadata={"event_id": event.event_id, "event_type": event.event_type},
        )
        return backend.save(entry)
    except Exception as exc:
        logger.warning("save_timeline_event failed: %s", exc)
        return ""
