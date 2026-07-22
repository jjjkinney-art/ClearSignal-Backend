"""Investment-memory consistency (Sprint 1B, issue #3).

Guards against the observed failures where the *current* conviction/verdict
conflicts with the "since first analysis" / prior-view summary, and where one
ticker's memory could describe another ticker.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Directional ordering of stances (bearish → bullish).
_STANCE_ORDINAL = {
    "bearish": -2, "cautious": -1, "neutral": 0, "constructive": 1, "bullish": 2,
    # tolerate a few synonyms seen in prose
    "negative": -2, "positive": 1, "very bullish": 2,
}


def stance_ordinal(stance: Optional[str]) -> Optional[int]:
    if not stance:
        return None
    return _STANCE_ORDINAL.get(stance.strip().lower())


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def validate_memory(
    memory: Optional[Dict[str, Any]],
    *,
    thesis_ticker: Optional[str] = None,
    current_stance: Optional[str] = None,
) -> List[str]:
    """Return memory-consistency violations (empty = consistent).

    Checks:
      1. Active-ticker isolation — memory must be for ``thesis_ticker``.
      2. Delta-direction coherence — ``conviction_direction`` must match the sign
         of (latest - first) in ``conviction_trend`` (no reversed/stale summary).
      3. Current-vs-memory coherence — a rising conviction trend must not accompany
         a current stance that is *more bearish* than the prior stance (and vice
         versa).
      4. Timestamp ordering — ``conviction_trend`` is chronological, so a supplied
         ``last_delta_days_ago`` must be non-negative.
    """
    if not memory:
        return []
    v: List[str] = []

    # 1. Active-ticker isolation.
    mem_ticker = (memory.get("ticker") or memory.get("active_ticker") or "").strip().upper()
    if thesis_ticker and mem_ticker and mem_ticker != thesis_ticker.strip().upper():
        v.append(
            f"memory ticker '{mem_ticker}' leaked into analysis of "
            f"'{thesis_ticker.strip().upper()}'"
        )

    trend: List[float] = list(memory.get("conviction_trend") or [])
    direction = (memory.get("conviction_direction") or "stable").strip().lower()

    # 2. Delta-direction coherence.
    if len(trend) >= 2:
        net = _sign(trend[-1] - trend[0])
        if direction == "rising" and net < 0:
            v.append(
                "memory conviction_direction='rising' but the trend net-declined "
                f"({round(trend[0]*100)}pp → {round(trend[-1]*100)}pp) — reversed summary"
            )
        elif direction == "falling" and net > 0:
            v.append(
                "memory conviction_direction='falling' but the trend net-rose "
                f"({round(trend[0]*100)}pp → {round(trend[-1]*100)}pp) — reversed summary"
            )

    # 3. Current stance vs memory delta direction.
    stance_hist: List[str] = list(memory.get("stance_history") or [])
    cur_ord = stance_ordinal(current_stance)
    prev_ord = stance_ordinal(stance_hist[-1]) if stance_hist else None
    if cur_ord is not None and prev_ord is not None:
        move = _sign(cur_ord - prev_ord)
        if direction == "rising" and move < 0:
            v.append(
                f"current stance '{current_stance}' is more bearish than prior "
                f"'{stance_hist[-1]}' while conviction_direction='rising'"
            )
        elif direction == "falling" and move > 0:
            v.append(
                f"current stance '{current_stance}' is more bullish than prior "
                f"'{stance_hist[-1]}' while conviction_direction='falling'"
            )

    # 4. Timestamp / recency ordering.
    days_ago = memory.get("last_delta_days_ago")
    if isinstance(days_ago, (int, float)) and days_ago < 0:
        v.append(f"memory last_delta_days_ago is negative ({days_ago}) — bad ordering")

    return v
