"""
Event freshness scoring — quantifies how recent and relevant a NormalizedEvent is.

Freshness decays over time with category-specific half-lives:
  - Earnings / guidance / regulatory:  24h  (market-moving, short half-life)
  - Macro releases (CPI/PPI/Fed):      12h  (high impact, very time-sensitive)
  - Analyst revisions:                 48h
  - News / market pricing:             6h
  - Default:                           24h

Freshness is always 0.0–1.0 where:
  1.0  = ingested within the last minute ("Live")
  0.7+ = same day ("Today")
  0.4+ = within the last 7 days ("This Week")
  <0.4 = stale ("Stale")

Source reliability multiplies the score slightly:
  HIGH   × 1.0
  MEDIUM × 0.95
  LOW    × 0.85
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from ...schemas import EventFreshnessScore
from .normalized_event import EventCategory, NormalizedEvent, SourceReliability

logger = logging.getLogger(__name__)

# Half-life in hours per category
_HALF_LIFE_HOURS: dict[str, float] = {
    EventCategory.EARNINGS.value:          24.0,
    EventCategory.GUIDANCE.value:          24.0,
    EventCategory.MACRO.value:             12.0,
    EventCategory.REGULATORY.value:        24.0,
    EventCategory.ESTIMATE_REVISION.value: 48.0,
    EventCategory.ANALYST_CALL.value:      48.0,
    EventCategory.NEWS.value:               6.0,
    EventCategory.MARKET_PRICING.value:     6.0,
}

_DEFAULT_HALF_LIFE = 24.0

_RELIABILITY_MULTIPLIER = {
    SourceReliability.HIGH.value:   1.00,
    SourceReliability.MEDIUM.value: 0.95,
    SourceReliability.LOW.value:    0.85,
}

# Freshness → label thresholds
_LABEL_THRESHOLDS = [
    (0.95, "Live"),
    (0.70, "Today"),
    (0.40, "This Week"),
    (0.0,  "Stale"),
]


def _parse_iso(ts: str) -> Optional[datetime]:
    """Parse ISO-8601 string to UTC datetime, returning None on failure."""
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def score_freshness(event: NormalizedEvent, now: Optional[datetime] = None) -> EventFreshnessScore:
    """
    Compute the freshness score for a NormalizedEvent.

    Parameters
    ----------
    event:
        The event to score.
    now:
        Reference datetime for age calculation. Defaults to UTC now.
        Useful for deterministic testing.

    Returns
    -------
    EventFreshnessScore
    """
    try:
        _now = now or datetime.now(timezone.utc)

        # Use ingestion_timestamp as the primary recency signal
        ts_str = event.ingestion_timestamp or event.event_timestamp or ""
        event_dt = _parse_iso(ts_str)

        if event_dt is None:
            # Can't parse timestamp — treat as 24h old
            age_hours = 24.0
        else:
            delta = _now - event_dt
            age_hours = max(0.0, delta.total_seconds() / 3600.0)

        # Category-specific half-life
        category_val = event.category.value if event.category else ""
        half_life = _HALF_LIFE_HOURS.get(category_val, _DEFAULT_HALF_LIFE)

        # Exponential decay: freshness = e^(-ln(2) * age / half_life)
        raw_freshness = math.exp(-math.log(2) * age_hours / half_life)

        # Apply reliability multiplier
        reliability_val = event.source_reliability.value if event.source_reliability else "medium"
        multiplier = _RELIABILITY_MULTIPLIER.get(reliability_val, 0.95)
        freshness = min(1.0, max(0.0, raw_freshness * multiplier))

        # Market-moving events get a small boost
        if event.is_market_moving:
            freshness = min(1.0, freshness * 1.05)

        # Derive label
        label = "Stale"
        for threshold, lbl in _LABEL_THRESHOLDS:
            if freshness >= threshold:
                label = lbl
                break

        return EventFreshnessScore(
            event_id=event.event_id,
            age_hours=round(age_hours, 2),
            freshness=round(freshness, 4),
            label=label,
            is_stale=freshness < 0.40,
            ingested_at=event.ingestion_timestamp or "",
        )
    except Exception as exc:
        logger.warning("score_freshness failed for event %s: %s", getattr(event, "event_id", "?"), exc)
        return EventFreshnessScore(
            event_id=getattr(event, "event_id", ""),
            age_hours=999.0,
            freshness=0.0,
            label="Stale",
            is_stale=True,
        )


def freshness_label(age_hours: float, is_market_moving: bool = False) -> str:
    """
    Quick utility to get a freshness label from age alone.
    Used by the frontend formatter when only age is available.
    """
    if age_hours < 0.017:   # ~1 minute
        return "Live"
    if age_hours < 24.0:
        return "Today"
    if age_hours < 168.0:   # 7 days
        return "This Week"
    return "Stale"
