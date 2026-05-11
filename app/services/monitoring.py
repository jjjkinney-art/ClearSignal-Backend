"""
Alert condition evaluation — declarative monitoring rules.

Provides pure-function condition evaluation against numeric readings.
This module is intentionally simple and dependency-free: it takes
AlertCondition rules and a dict of current metric values and returns
triggered AlertEvent objects.

Distinct from monitoring_service.py (which handles event-based enterprise
monitoring with observability tracing).  This module provides the
declarative rules layer that a future scheduler or webhook can call.

Usage
-----
    from app.services.monitoring import check_conditions, evaluate_condition
    from app.schemas import AlertCondition

    conditions = [
        AlertCondition(
            condition_id="yc-reinversion",
            type="yield_curve_reinversion",
            threshold=0.0,
            direction="below",
            topic="yields",
            description="Yield curve re-inverts (T10Y2Y goes negative)",
        ),
    ]
    readings = {"T10Y2Y": -0.10, "VIXCLS": 22.5}
    events = check_conditions(conditions, readings)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.schemas import AlertCondition, AlertEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in condition type constants
# ---------------------------------------------------------------------------

YIELD_CURVE_REINVERSION: str = "yield_curve_reinversion"
MARGIN_COMPRESSION: str = "margin_compression"
DEBT_INCREASE: str = "debt_increase"
GUIDANCE_WEAKNESS: str = "guidance_weakness"
VOLATILITY_SPIKE: str = "volatility_spike"
VIX_ABOVE_THRESHOLD: str = "vix_above_threshold"
CREDIT_SPREAD_WIDENING: str = "credit_spread_widening"
RATE_ABOVE_THRESHOLD: str = "rate_above_threshold"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_reading(
    condition: AlertCondition,
    readings: Dict[str, float],
) -> Optional[float]:
    """Try to match *condition* to a value in *readings*.

    Resolution order:
      1. condition.topic  (e.g. "yields", "T10Y2Y")
      2. condition.type   (e.g. "yield_curve_reinversion")
      3. condition.condition_id

    Returns None if no key matches.
    """
    for key in (condition.topic, condition.type, condition.condition_id):
        if key and key in readings:
            return readings[key]
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_condition(condition: AlertCondition, current_value: float) -> bool:
    """Return True when *current_value* satisfies the condition's direction rule.

    direction="above"   → current_value >  threshold
    direction="below"   → current_value <  threshold
    direction="crosses" → triggers when current_value < 0 for threshold == 0
                          (sign flip to negative); for non-zero threshold,
                          behaves like "below" as a sensible default.
    """
    threshold = condition.threshold
    direction = (condition.direction or "crosses").lower()

    if direction == "above":
        return current_value > threshold
    if direction == "below":
        return current_value < threshold
    if direction == "crosses":
        if threshold == 0.0:
            return current_value < 0.0
        # Non-zero threshold: treat as "below" (most common useful default)
        return current_value < threshold

    logger.warning(
        "evaluate_condition: unknown direction %r for condition %s — skipping",
        condition.direction,
        condition.condition_id,
    )
    return False


def check_conditions(
    conditions: List[AlertCondition],
    readings: Dict[str, float],
) -> List[AlertEvent]:
    """Evaluate all *conditions* against the provided *readings* dict.

    For each condition a matching reading is resolved via
    ``_resolve_reading``.  If no reading is found the condition is silently
    skipped (logged at DEBUG level).  When the condition fires an
    ``AlertEvent`` is appended to the returned list.

    Parameters
    ----------
    conditions:
        Declarative alert rules to evaluate.
    readings:
        Mapping of metric key → current numeric value.  Keys may be FRED
        series IDs, topic names, or condition type strings.

    Returns
    -------
    List[AlertEvent]
        One event per triggered condition, in evaluation order.
    """
    events: List[AlertEvent] = []

    for condition in conditions:
        current_value = _resolve_reading(condition, readings)

        if current_value is None:
            logger.debug(
                "check_conditions: no reading found for condition %r "
                "(topic=%r, type=%r) — skipping",
                condition.condition_id,
                condition.topic,
                condition.type,
            )
            continue

        if evaluate_condition(condition, current_value):
            triggered_at = datetime.now(timezone.utc).isoformat()
            message = (
                f"{condition.description or condition.type}: "
                f"{current_value:.4f} {condition.direction} {condition.threshold:.4f}"
            )
            event = AlertEvent(
                condition_id=condition.condition_id,
                type=condition.type,
                ticker=condition.ticker,
                topic=condition.topic,
                current_value=current_value,
                threshold=condition.threshold,
                direction=condition.direction,
                triggered_at=triggered_at,
                message=message,
            )
            events.append(event)
            logger.info(
                "check_conditions: condition %r triggered — %s",
                condition.condition_id,
                message,
            )

    return events
