"""
Portfolio delivery integration — Phase 10D · Slice 7.

Reads ranked portfolio_insights, converts each into a 10C-compatible delivery
payload, and enqueues via loop_delivery_service.enqueue() on the "in_app"
channel with kind="portfolio_alert".

Shadow mode (default)
---------------------
By default every call operates in shadow mode: delivery_ledger rows are
created and optionally drained via flush_pending_shadow(), but NO live
Notification rows are written and no external transport fires.  Shadow drain
can be suppressed (shadow_flush=False) when the caller wants to accumulate
rows for a batch drain later.

Deduplication
-------------
The delivery content_key is derived from the insight's own content_key (which
already encodes portfolio_id + insight_type + cluster_label + ISO_week_bucket)
concatenated with the channel name.  This means a given insight fires at most
once per channel per 7-day window, independent of how many times
deliver_portfolio_insights() is called.

Briefing helper
---------------
build_portfolio_context_block(ranked_insights) returns a plain dict that a
morning_brief_v2 consumer can embed under a "portfolio_context" key.  It does
NOT write to the DB, does NOT stamp last_delivered_at, and does NOT consume or
generate a content_key.

Design constraints
------------------
* No LLM calls, no external channels, no investment recommendations.
* Never mutates insight body_json or prose.
* Never creates live Notification rows (shadow mode default).
* Null-session safe: returns an empty PortfolioDeliveryResult without raising.
* Never implements Slice 8.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Module-level import of loop_delivery_service so tests can patch it cleanly.
# Wrapped in try/except to survive import cycles in test environments.
try:
    from app.services import loop_delivery_service as _loop_delivery_svc
except Exception:  # pragma: no cover
    _loop_delivery_svc = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHANNEL_IN_APP = "in_app"
KIND_PORTFOLIO_ALERT = "portfolio_alert"

# Severity mapping from portfolio insight severity to 10C delivery severity.
# 10C guardrails use: critical, alert, warning, info
_PORTFOLIO_TO_DELIVERY_SEVERITY: Dict[str, str] = {
    "critical": "critical",
    "high":     "alert",
    "medium":   "warning",
    "low":      "info",
    "info":     "info",
}

# rank_band threshold for automatic suppression (below "low" band → rank_score=0)
_SUPPRESS_ZERO_SCORE = True


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class InsightDeliveryOutcome:
    """Outcome of one insight's enqueue attempt."""

    insight_id: str
    content_key: str            # insight-level content_key (from PortfolioInsight row)
    delivery_content_key: str   # delivery-layer dedup key
    status: str                 # loop_delivery_service STATUS_* constant
    reason: str                 # suppression reason, or ""
    delivery_id: Optional[str]  # DeliveryLedger row id, or None


@dataclass
class PortfolioDeliveryResult:
    """Summary of one deliver_portfolio_insights() call."""

    portfolio_id: str
    delivered_at: str       # ISO-8601 UTC
    enqueued: int           # rows successfully queued (pending)
    suppressed_duplicate: int
    suppressed_guardrail: int
    suppressed_zero_score: int
    skipped: int
    shadow: bool
    shadow_drained: int     # rows drained via flush_pending_shadow
    outcomes: List[InsightDeliveryOutcome] = field(default_factory=list)
    regulatory_disclaimer: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _delivery_content_key(insight_content_key: str, channel: str) -> str:
    """Build a stable delivery-layer dedup key from the insight content_key + channel.

    The insight content_key already encodes a 7-day ISO-week window, so this
    key is stable for the same 7-day window and channel.
    """
    raw = f"{insight_content_key}|{channel}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _map_severity(insight_severity: str) -> str:
    """Map a portfolio insight severity to a 10C delivery severity."""
    return _PORTFOLIO_TO_DELIVERY_SEVERITY.get(
        insight_severity.lower(), "info"
    )


def _build_payload(row, *, include_disclaimer: bool = True) -> Dict[str, Any]:
    """Convert a PortfolioInsight ORM row into a 10C-compatible delivery payload.

    The payload is a JSON-serialisable dict; the delivery pipeline snapshots it
    into delivery_ledger.payload_json.
    """
    # Parse body_json defensively
    try:
        body = json.loads(row.body_json) if row.body_json else {}
    except (json.JSONDecodeError, TypeError):
        body = {}

    payload: Dict[str, Any] = {
        "kind":            KIND_PORTFOLIO_ALERT,
        "portfolio_id":    row.portfolio_id,
        "insight_id":      row.id,
        "insight_type":    row.insight_type,
        "cluster_label":   row.cluster_label,
        "severity":        _map_severity(row.severity),
        "rank_score":      row.rank_score,
        "member_tickers":  _safe_json_list(row.member_tickers),
        "stale_input":     bool(row.stale_input),
        "content_key":     row.content_key,
        "created_at":      row.created_at.isoformat() if row.created_at else None,
        "prose":           body.get("prose", ""),
    }

    if include_disclaimer:
        payload["regulatory_disclaimer"] = body.get("regulatory_disclaimer", "")

    return payload


def _safe_json_list(value: Optional[str]) -> List[str]:
    try:
        parsed = json.loads(value) if value else []
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Public API — delivery
# ---------------------------------------------------------------------------

async def deliver_portfolio_insights(
    session,
    portfolio_id: str,
    user_id: str,
    channel: str = CHANNEL_IN_APP,
    shadow: bool = True,
    shadow_flush: bool = True,
    limit: int = 50,
) -> PortfolioDeliveryResult:
    """Read ranked portfolio_insights and enqueue each via loop_delivery_service.

    Parameters
    ----------
    session       : AsyncSession or None (null-session safe).
    portfolio_id  : Portfolio whose insights to deliver.
    user_id       : Recipient.  Passed verbatim to enqueue().
    channel       : Delivery channel; defaults to "in_app".
    shadow        : If True (default) flush via flush_pending_shadow() so no
                    live Notification rows are ever written.
    shadow_flush  : If shadow=True, whether to immediately drain pending rows
                    after enqueue.  Pass False to batch-drain externally.
    limit         : Max insights to read from portfolio_insights.

    Returns
    -------
    PortfolioDeliveryResult — always returns, never raises.
    """
    from app.services.portfolio_insight_service import REGULATORY_DISCLAIMER

    delivered_at = _now_utc().isoformat()

    if session is None:
        return PortfolioDeliveryResult(
            portfolio_id=portfolio_id,
            delivered_at=delivered_at,
            enqueued=0,
            suppressed_duplicate=0,
            suppressed_guardrail=0,
            suppressed_zero_score=0,
            skipped=1,
            shadow=shadow,
            shadow_drained=0,
            regulatory_disclaimer=REGULATORY_DISCLAIMER,
        )

    _lds = _loop_delivery_svc
    if _lds is None:
        logger.error("[portfolio_delivery] loop_delivery_service unavailable")
        return PortfolioDeliveryResult(
            portfolio_id=portfolio_id,
            delivered_at=delivered_at,
            enqueued=0,
            suppressed_duplicate=0,
            suppressed_guardrail=0,
            suppressed_zero_score=0,
            skipped=1,
            shadow=shadow,
            shadow_drained=0,
            regulatory_disclaimer=REGULATORY_DISCLAIMER,
        )

    try:
        from app.db.repositories import portfolio_repo as _pr
    except Exception as exc:
        logger.error("[portfolio_delivery] portfolio_repo import failed: %r", exc)
        return PortfolioDeliveryResult(
            portfolio_id=portfolio_id,
            delivered_at=delivered_at,
            enqueued=0,
            suppressed_duplicate=0,
            suppressed_guardrail=0,
            suppressed_zero_score=0,
            skipped=1,
            shadow=shadow,
            shadow_drained=0,
            regulatory_disclaimer=REGULATORY_DISCLAIMER,
        )

    rows = await _pr.insight_list(session, portfolio_id, limit=limit)

    outcomes: List[InsightDeliveryOutcome] = []
    enqueued = 0
    suppressed_duplicate = 0
    suppressed_guardrail = 0
    suppressed_zero_score = 0
    skipped = 0

    for row in rows:
        # Suppress insights with zero rank_score (no signal).
        if _SUPPRESS_ZERO_SCORE and (row.rank_score or 0.0) == 0.0:
            suppressed_zero_score += 1
            outcomes.append(InsightDeliveryOutcome(
                insight_id=row.id,
                content_key=row.content_key,
                delivery_content_key="",
                status=_lds.STATUS_SKIPPED,
                reason="zero_rank_score",
                delivery_id=None,
            ))
            continue

        delivery_ck = _delivery_content_key(row.content_key, channel)
        payload = _build_payload(row)
        delivery_severity = _map_severity(row.severity)

        try:
            result = await _lds.enqueue(
                session,
                user_id,
                channel,
                portfolio_id,           # target_key = portfolio being delivered
                payload,
                artifact_ref=row.id,
                severity=delivery_severity,
            )
        except Exception as exc:
            logger.warning("[portfolio_delivery] enqueue failed for %s: %r", row.id, exc)
            skipped += 1
            outcomes.append(InsightDeliveryOutcome(
                insight_id=row.id,
                content_key=row.content_key,
                delivery_content_key=delivery_ck,
                status=_lds.STATUS_FAILED,
                reason=str(exc),
                delivery_id=None,
            ))
            continue

        # Count by status
        if result.status == _lds.STATUS_SUPPRESSED_DUPLICATE:
            suppressed_duplicate += 1
        elif result.status == _lds.STATUS_SUPPRESSED_GUARDRAIL:
            suppressed_guardrail += 1
        elif result.status == _lds.STATUS_SKIPPED:
            skipped += 1
        elif result.status in (_lds.STATUS_DELIVERED_SHADOW, "pending"):
            enqueued += 1
            # Stamp last_delivered_at on the insight row.
            _stamp_delivered(row)
        else:
            # "pending" or any other accepted status
            enqueued += 1
            _stamp_delivered(row)

        outcomes.append(InsightDeliveryOutcome(
            insight_id=row.id,
            content_key=row.content_key,
            delivery_content_key=delivery_ck,
            status=result.status,
            reason=result.reason or "",
            delivery_id=result.delivery_id,
        ))

    # Flush DB state for last_delivered_at stamps.
    if enqueued > 0:
        try:
            await session.flush()
        except Exception as exc:
            logger.warning("[portfolio_delivery] flush failed: %r", exc)

    # Shadow drain — drain pending rows without creating Notification rows.
    shadow_drained = 0
    if shadow and shadow_flush:
        try:
            drain_results = await _lds.flush_pending_shadow(session)
            shadow_drained = len(drain_results)
        except Exception as exc:
            logger.warning("[portfolio_delivery] flush_pending_shadow failed: %r", exc)

    return PortfolioDeliveryResult(
        portfolio_id=portfolio_id,
        delivered_at=delivered_at,
        enqueued=enqueued,
        suppressed_duplicate=suppressed_duplicate,
        suppressed_guardrail=suppressed_guardrail,
        suppressed_zero_score=suppressed_zero_score,
        skipped=skipped,
        shadow=shadow,
        shadow_drained=shadow_drained,
        outcomes=outcomes,
        regulatory_disclaimer=REGULATORY_DISCLAIMER,
    )


def _stamp_delivered(row) -> None:
    """Set last_delivered_at on a PortfolioInsight row to now (UTC)."""
    try:
        row.last_delivered_at = _now_utc()
    except Exception as exc:
        logger.debug("[portfolio_delivery] _stamp_delivered failed: %r", exc)


# ---------------------------------------------------------------------------
# Public API — briefing helper
# ---------------------------------------------------------------------------

def build_portfolio_context_block(
    ranked_insights: List[Any],
    max_highlights: int = 5,
) -> Dict[str, Any]:
    """Build a morning_brief_v2 portfolio_context block from ranked insights.

    This is a read-only, non-mutating helper.  It does NOT:
      * write to the DB
      * stamp last_delivered_at
      * consume or generate a content_key
      * call loop_delivery_service

    Parameters
    ----------
    ranked_insights : List of RankedInsight dataclasses (from ranking service)
                      OR plain dicts with the same fields.
    max_highlights  : Maximum number of top insights to surface as highlights.

    Returns
    -------
    A plain dict suitable for embedding under "portfolio_context" in a
    MorningBriefV2 or similar structured briefing payload.
    """
    if not ranked_insights:
        return {
            "has_portfolio_alerts": False,
            "portfolio_alert_count": 0,
            "top_highlights": [],
            "severity_summary": {},
            "affected_tickers": [],
        }

    def _get(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    # Sort by rank_score descending (already sorted from ranking service, but
    # defensive sort in case caller passed unsorted list).
    try:
        sorted_insights = sorted(
            ranked_insights,
            key=lambda x: -(_get(x, "rank_score") or 0.0),
        )
    except Exception:
        sorted_insights = list(ranked_insights)

    # Severity summary
    severity_summary: Dict[str, int] = {}
    all_tickers: List[str] = []

    for insight in sorted_insights:
        sev = _get(insight, "severity", "info") or "info"
        severity_summary[sev] = severity_summary.get(sev, 0) + 1

        # Collect member_tickers
        raw_tickers = _get(insight, "member_tickers", None)
        if isinstance(raw_tickers, list):
            all_tickers.extend(raw_tickers)
        elif isinstance(raw_tickers, str):
            try:
                parsed = json.loads(raw_tickers)
                if isinstance(parsed, list):
                    all_tickers.extend(parsed)
            except (json.JSONDecodeError, TypeError):
                pass

    # Deduplicate tickers preserving order
    seen: set = set()
    unique_tickers: List[str] = []
    for t in all_tickers:
        if t not in seen:
            seen.add(t)
            unique_tickers.append(t)

    # Top highlights — top N by rank_score
    highlights = []
    for insight in sorted_insights[:max_highlights]:
        body_json_raw = _get(insight, "body_json", "{}")
        try:
            body = json.loads(body_json_raw) if isinstance(body_json_raw, str) else {}
        except (json.JSONDecodeError, TypeError):
            body = {}

        highlights.append({
            "insight_id":    _get(insight, "insight_id") or _get(insight, "id"),
            "insight_type":  _get(insight, "insight_type", ""),
            "cluster_label": _get(insight, "cluster_label", ""),
            "severity":      _get(insight, "severity", "info"),
            "rank_score":    round(_get(insight, "rank_score") or 0.0, 4),
            "rank_band":     _get(insight, "rank_band", "low"),
            "prose":         body.get("prose", ""),
        })

    return {
        "has_portfolio_alerts": len(sorted_insights) > 0,
        "portfolio_alert_count": len(sorted_insights),
        "top_highlights": highlights,
        "severity_summary": severity_summary,
        "affected_tickers": unique_tickers,
    }
