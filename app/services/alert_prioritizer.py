"""
Alert prioritizer — deterministic scoring of thesis diffs and
material change events to produce structured AlertPriority objects.

No LLM calls.  All scoring is composite, additive, and deterministic.
The score is capped at 1.0.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from ..schemas import AlertPriority, MaterialChangeEvent, ThesisDiff

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority thresholds
# ---------------------------------------------------------------------------

_THRESHOLD_CRITICAL = 0.65
_THRESHOLD_HIGH     = 0.35
_THRESHOLD_MEDIUM   = 0.15


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def alert_priority_score(
    diff: ThesisDiff,
    change_event: Optional[MaterialChangeEvent] = None,
) -> AlertPriority:
    """Compute alert priority from a ThesisDiff + optional MaterialChangeEvent.

    Scoring is additive and deterministic.  The composite score is capped
    at 1.0 before applying thresholds.

    Parameters
    ----------
    diff:
        A ThesisDiff produced by ``thesis_memory_service.compare_thesis_snapshots``.
    change_event:
        Optional MaterialChangeEvent associated with the diff.

    Returns
    -------
    AlertPriority
        Priority in [critical, high, medium, ignore] with a 0.0-1.0 score
        and a human-readable reason string.
    """
    if diff is None:
        return AlertPriority(
            alert_id="",
            ticker="",
            priority="ignore",
            priority_score=0.0,
            reason="No diff provided.",
        )

    try:
        score   = 0.0
        reasons: List[str] = []

        ticker   = ""
        alert_id = ""
        if change_event is not None:
            ticker   = change_event.ticker or ""
            alert_id = change_event.event_id or ""

        # ── Thesis break signals (highest weight) ───────────────────────────
        category = (change_event.change_category if change_event else "") or ""
        if category == "thesis_broke":
            score += 0.50
            reasons.append("thesis broke")

        cc = diff.confidence_change if diff.confidence_change is not None else 0.0
        if cc <= -0.25:
            score += 0.35
            reasons.append(f"confidence collapsed ({cc:+.0%})")
        elif cc <= -0.15:
            score += 0.20
            reasons.append(f"confidence weakened significantly ({cc:+.0%})")

        # ── Debate + narrative ───────────────────────────────────────────────
        if diff.core_debate_shifted:
            score += 0.25
            reasons.append("core debate shifted")
        if diff.trend_flipped:
            score += 0.20
            reasons.append("trend flipped")

        # ── Risk signals ─────────────────────────────────────────────────────
        new_risks_count = len(diff.new_risks) if diff.new_risks else 0
        if new_risks_count > 0:
            risk_contrib = min(new_risks_count * 0.08, 0.20)
            score += risk_contrib
            reasons.append(f"{new_risks_count} new risk(s) identified")
        if diff.top_signal_replaced:
            score += 0.12
            reasons.append("top signal replaced")

        # ── Materiality from MaterialChangeEvent ─────────────────────────────
        if change_event is not None:
            ms = change_event.materiality_score if change_event.materiality_score is not None else 0.0
            if ms >= 0.7:
                score += 0.15
                reasons.append(f"materiality score {ms:.2f} (high)")
            elif ms >= 0.4:
                score += 0.08
                reasons.append(f"materiality score {ms:.2f} (medium)")

        # ── Cap and classify ─────────────────────────────────────────────────
        score = min(score, 1.0)

        if score >= _THRESHOLD_CRITICAL:
            priority = "critical"
        elif score >= _THRESHOLD_HIGH:
            priority = "high"
        elif score >= _THRESHOLD_MEDIUM:
            priority = "medium"
        else:
            priority = "ignore"

        reason = "; ".join(reasons) if reasons else "no significant changes detected"

        return AlertPriority(
            alert_id=alert_id,
            ticker=ticker,
            priority=priority,
            priority_score=round(score, 4),
            reason=reason,
        )

    except Exception as exc:
        logger.warning("alert_priority_score failed: %s", exc)
        return AlertPriority(
            alert_id="",
            ticker="",
            priority="ignore",
            priority_score=0.0,
            reason=f"scoring error: {exc}",
        )


def rank_alerts(
    pairs: List[Tuple[ThesisDiff, Optional[MaterialChangeEvent]]],
) -> List[AlertPriority]:
    """Rank multiple (ThesisDiff, MaterialChangeEvent) pairs by priority score.

    Returns AlertPriority objects sorted highest-score-first.
    Handles None entries defensively.

    Parameters
    ----------
    pairs:
        List of (ThesisDiff, Optional[MaterialChangeEvent]) tuples.

    Returns
    -------
    List[AlertPriority]
        Sorted descending by priority_score.
    """
    if not pairs:
        return []

    results: List[AlertPriority] = []
    for item in pairs:
        try:
            diff, change = item if len(item) == 2 else (item[0], None)  # type: ignore[misc]
            ap = alert_priority_score(diff, change)
            results.append(ap)
        except Exception as exc:
            logger.warning("rank_alerts: failed to score pair: %s", exc)

    results.sort(key=lambda ap: ap.priority_score, reverse=True)
    return results
