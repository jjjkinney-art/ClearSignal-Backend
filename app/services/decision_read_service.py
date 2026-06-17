"""
Decision Read Service — Phase 13 · Slice 6.

Read-only access to stored DecisionPriority rows.  Never rebuilds, ranks,
explains, or writes anything.

Core rule: this module calls only decision_repo read functions. It does NOT
import decision_candidate_builder, decision_ranking_engine, decision_
explainability_service, or decision_invalidation_service. Any call that would
trigger a rebuild or write is forbidden here.

Safety invariants (SP-5)
------------------------
  - No write, add, update, delete path exists.
  - No import from rebuild/ranking/explanation modules.
  - No import from delivery, notification, or conviction modules.
  - No buy/sell/hold/recommend/target-price/position-size language in any
    generated field.
  - The DISCLAIMER is appended verbatim to every decision item and to every
    aggregate payload.

Read filters applied to all list operations
-------------------------------------------
  - exclude_expired=True  (expires_at > now)
  - decision_reason non-empty  (explanation exists)
  - evidence_summary non-empty  (evidence exists)
  - decision_rank_score > 0.0  (was actually scored)
  - candidate_type in _SUPPORTED_TYPES
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "This information is generated from automated signal analysis and does not "
    "constitute financial advice, investment guidance, or a representation "
    "of future outcomes. All signals carry inherent uncertainty."
)

_SUPPORTED_TYPES = frozenset({
    "forecast_candidate",
    "risk_candidate",
    "catalyst_candidate",
    "watchlist_candidate",
    "portfolio_exposure_candidate",
    "delivery_transition_candidate",
    "similarity_candidate",
})

# Map candidate_type → human-readable source_type label (best-effort)
_TYPE_TO_SOURCE: Dict[str, str] = {
    "forecast_candidate":            "forecast_vector",
    "risk_candidate":                "dossier_failure_mode",
    "catalyst_candidate":            "dossier_catalyst",
    "watchlist_candidate":           "watched_tickers",
    "portfolio_exposure_candidate":  "portfolio_positions",
    "delivery_transition_candidate": "delivery_ledger",
    "similarity_candidate":          "similarity_edge",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Row validation
# ---------------------------------------------------------------------------

def _is_valid_priority(row) -> bool:
    """Return True iff *row* passes all read-layer filters."""
    try:
        # Expiry
        exp = getattr(row, "expires_at", None)
        if exp is None:
            return False
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= _now():
            return False

        # Explanation must exist
        if not (getattr(row, "decision_reason", None) or "").strip():
            return False

        # Evidence must exist
        ev = getattr(row, "evidence_summary", None) or []
        if not ev:
            return False

        # Must have been scored
        if (getattr(row, "decision_rank_score", 0.0) or 0.0) <= 0.0:
            return False

        # Supported type only
        if getattr(row, "candidate_type", "") not in _SUPPORTED_TYPES:
            return False

        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Row → output dict
# ---------------------------------------------------------------------------

def _format_priority(row) -> Dict[str, Any]:
    """Render one DecisionPriority row as a public-safe decision dict."""
    decision_reason = getattr(row, "decision_reason", "") or ""
    why_now_raw     = getattr(row, "why_now", "") or ""
    deprioritizers  = getattr(row, "deprioritizers", []) or []
    evidence_summary = getattr(row, "evidence_summary", []) or []
    candidate_type  = getattr(row, "candidate_type", "")

    # Derive headline from the first sentence of decision_reason
    headline = decision_reason.split(".")[0].strip() if decision_reason else ""

    # Derive summary from the first evidence item
    summary = evidence_summary[0] if evidence_summary else ""

    # why_important: split on ". " to reconstruct sentence list
    why_important = [s.strip() + "." for s in decision_reason.split(". ") if s.strip()]
    if why_important and why_important[-1].endswith(".."):
        why_important[-1] = why_important[-1][:-1]

    # why_now: same treatment
    why_now = [s.strip() + "." for s in why_now_raw.split(". ") if s.strip()]
    if why_now and why_now[-1].endswith(".."):
        why_now[-1] = why_now[-1][:-1]

    built_at   = getattr(row, "built_at",   None)
    expires_at = getattr(row, "expires_at", None)

    return {
        "ticker":          getattr(row, "entity_key", ""),
        "candidate_type":  candidate_type,
        "priority_bucket": getattr(row, "decision_priority", "informational"),
        "decision_score":  round(float(getattr(row, "decision_rank_score", 0.0)), 4),
        "headline":        headline,
        "summary":         summary,
        "why_important":   why_important,
        "why_now":         why_now,
        "evidence":        evidence_summary,
        "deprioritizers":  deprioritizers,
        "source_type":     _TYPE_TO_SOURCE.get(candidate_type, candidate_type),
        "source_id":       getattr(row, "source_ref", ""),
        "generated_at":    built_at.isoformat()   if built_at   else None,
        "expires_at":      expires_at.isoformat() if expires_at else None,
        "disclaimer":      _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Public read functions
# ---------------------------------------------------------------------------

async def get_decisions_for_ticker(
    session,
    ticker: str,
    *,
    limit: int = 10,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return formatted decisions for *ticker*.

    Returns all stored non-expired, valid decision priorities for the ticker,
    sorted by decision_rank_score descending, capped at *limit*.

    Returns the safe empty state when session is None or no rows exist.
    Never rebuilds or writes.
    """
    if session is None:
        return _empty_ticker_payload(ticker)
    try:
        from app.db.repositories.decision_repo import list_decision_priorities

        rows = await list_decision_priorities(
            session,
            entity_key=ticker.upper(),
            user_id=user_id,
            exclude_expired=True,
            limit=limit * 3,  # over-fetch so we can filter
        )
        valid = [_format_priority(r) for r in rows if _is_valid_priority(r)]
        valid = valid[:limit]

        return {
            "ticker":      ticker.upper(),
            "has_decisions": bool(valid),
            "decisions":   valid,
            "count":       len(valid),
            "disclaimer":  _DISCLAIMER,
        }
    except Exception as exc:
        logger.debug("[decision_read] get_decisions_for_ticker error: %r", exc)
        return _empty_ticker_payload(ticker)


def _empty_ticker_payload(ticker: str) -> Dict[str, Any]:
    return {
        "ticker":        ticker.upper() if ticker else "",
        "has_decisions": False,
        "decisions":     [],
        "count":         0,
        "disclaimer":    _DISCLAIMER,
    }


async def get_decisions_for_user(
    session,
    user_id: str,
    *,
    limit: int = 20,
) -> Dict[str, Any]:
    """Return formatted decisions scoped to *user_id*.

    Returns the safe empty state when session is None or no rows exist.
    Never rebuilds or writes.
    """
    if session is None or not user_id:
        return _empty_user_payload(user_id or "")
    try:
        from app.db.repositories.decision_repo import list_decision_priorities

        rows = await list_decision_priorities(
            session,
            user_id=user_id,
            exclude_expired=True,
            limit=limit * 3,
        )
        valid = [_format_priority(r) for r in rows if _is_valid_priority(r)]
        valid = valid[:limit]

        return {
            "user_id":       user_id,
            "has_decisions": bool(valid),
            "decisions":     valid,
            "count":         len(valid),
            "disclaimer":    _DISCLAIMER,
        }
    except Exception as exc:
        logger.debug("[decision_read] get_decisions_for_user error: %r", exc)
        return _empty_user_payload(user_id)


def _empty_user_payload(user_id: str) -> Dict[str, Any]:
    return {
        "user_id":       user_id,
        "has_decisions": False,
        "decisions":     [],
        "count":         0,
        "disclaimer":    _DISCLAIMER,
    }


async def get_top_decisions(
    session,
    *,
    limit: int = 20,
    user_id: Optional[str] = None,
    candidate_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the highest-scoring valid decisions across all tickers.

    When *user_id* is given, restricts to that user's scope.
    When *candidate_type* is given, restricts to that type.
    Returns the safe empty state when session is None.
    Never rebuilds or writes.
    """
    if session is None:
        return {"has_decisions": False, "decisions": [], "count": 0, "disclaimer": _DISCLAIMER}
    try:
        from app.db.repositories.decision_repo import list_decision_priorities

        rows = await list_decision_priorities(
            session,
            user_id=user_id,
            candidate_type=candidate_type,
            exclude_expired=True,
            limit=limit * 3,
        )
        valid = [_format_priority(r) for r in rows if _is_valid_priority(r)]
        valid = valid[:limit]

        return {
            "has_decisions": bool(valid),
            "decisions":     valid,
            "count":         len(valid),
            "disclaimer":    _DISCLAIMER,
        }
    except Exception as exc:
        logger.debug("[decision_read] get_top_decisions error: %r", exc)
        return {"has_decisions": False, "decisions": [], "count": 0, "disclaimer": _DISCLAIMER}


async def get_decision_facet_for_ticker(
    session,
    ticker: str,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a condensed decision facet for *ticker* for dossier/UI integration.

    Returns only the top-3 valid decisions, with a facet-level summary:
      - has_decisions
      - top_bucket  (highest priority bucket seen, or "none")
      - top_score   (highest decision_rank_score, or 0.0)
      - type_counts ({candidate_type: count})
      - decisions   (top-3, formatted)

    Returns the safe empty facet when session is None or no rows exist.
    Never rebuilds or writes.
    """
    if session is None:
        return _empty_facet(ticker)
    try:
        from app.db.repositories.decision_repo import list_decision_priorities

        rows = await list_decision_priorities(
            session,
            entity_key=ticker.upper(),
            user_id=user_id,
            exclude_expired=True,
            limit=50,
        )
        valid = [r for r in rows if _is_valid_priority(r)]

        type_counts: Dict[str, int] = {}
        for r in valid:
            ct = getattr(r, "candidate_type", "unknown")
            type_counts[ct] = type_counts.get(ct, 0) + 1

        top_bucket = "none"
        _bucket_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "informational": 0}
        for r in valid:
            b = getattr(r, "decision_priority", "informational")
            if _bucket_rank.get(b, 0) > _bucket_rank.get(top_bucket, -1):
                top_bucket = b

        top_score = max(
            (float(getattr(r, "decision_rank_score", 0.0)) for r in valid),
            default=0.0,
        )

        top3 = [_format_priority(r) for r in valid[:3]]

        return {
            "ticker":        ticker.upper(),
            "has_decisions": bool(valid),
            "top_bucket":    top_bucket,
            "top_score":     round(top_score, 4),
            "type_counts":   type_counts,
            "decisions":     top3,
            "disclaimer":    _DISCLAIMER,
        }
    except Exception as exc:
        logger.debug("[decision_read] get_decision_facet_for_ticker error: %r", exc)
        return _empty_facet(ticker)


def _empty_facet(ticker: str) -> Dict[str, Any]:
    return {
        "ticker":        ticker.upper() if ticker else "",
        "has_decisions": False,
        "top_bucket":    "none",
        "top_score":     0.0,
        "type_counts":   {},
        "decisions":     [],
        "disclaimer":    _DISCLAIMER,
    }


async def build_decision_status_snapshot(session) -> Dict[str, Any]:
    """Return a read-only admin observability snapshot of the decision layer.

    Covers:
      - All 6 decision_* config flags
      - Row counts (total, valid, expired, by type, by bucket)
      - Latest built_at timestamp
      - safe_state: True when decision_shadow=True and no critical rows
        have leaked to a delivery path (delivery_count always 0 in Phase 13)
      - db_available

    Returns a degraded-but-valid snapshot when session is None.
    Never rebuilds or writes.
    """
    from app.config import settings

    flags = {
        "decision_build_enabled":       settings.decision_build_enabled,
        "decision_scoring_enabled":     settings.decision_scoring_enabled,
        "decision_delivery_enabled":    settings.decision_delivery_enabled,
        "decision_shadow":              settings.decision_shadow,
        "decision_targets_enabled":     settings.decision_targets_enabled,
        "decision_calibration_enabled": settings.decision_calibration_enabled,
    }

    empty_counts: Dict[str, Any] = {
        "total":      0,
        "valid":      0,
        "expired":    0,
        "by_type":    {},
        "by_bucket":  {},
        "latest_built_at": None,
    }

    if session is None:
        return {
            "flags":         flags,
            "counts":        empty_counts,
            "db_available":  False,
            "safe_state":    settings.decision_shadow and not settings.decision_delivery_enabled,
            "disclaimer":    _DISCLAIMER,
        }

    try:
        from app.db.repositories.decision_repo import list_decision_priorities, count_decision_priorities

        total_count = await count_decision_priorities(session)

        # Fetch all rows (no expiry filter) for count breakdown
        all_rows = await list_decision_priorities(session, limit=2000)
        now = _now()

        by_type:   Dict[str, int] = {}
        by_bucket: Dict[str, int] = {}
        valid_count   = 0
        expired_count = 0
        latest_ts: Optional[datetime] = None

        for r in all_rows:
            ct = getattr(r, "candidate_type", "unknown")
            bk = getattr(r, "decision_priority", "informational")
            by_type[ct]   = by_type.get(ct, 0) + 1
            by_bucket[bk] = by_bucket.get(bk, 0) + 1

            exp = getattr(r, "expires_at", None)
            if exp is not None:
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp <= now:
                    expired_count += 1
                else:
                    if _is_valid_priority(r):
                        valid_count += 1

            bat = getattr(r, "built_at", None)
            if bat is not None:
                if latest_ts is None or bat > latest_ts:
                    latest_ts = bat

        counts: Dict[str, Any] = {
            "total":      total_count,
            "valid":      valid_count,
            "expired":    expired_count,
            "by_type":    by_type,
            "by_bucket":  by_bucket,
            "latest_built_at": latest_ts.isoformat() if latest_ts else None,
        }

        safe_state = (
            settings.decision_shadow
            and not settings.decision_delivery_enabled
        )

        return {
            "flags":        flags,
            "counts":       counts,
            "db_available": True,
            "safe_state":   safe_state,
            "disclaimer":   _DISCLAIMER,
        }

    except Exception as exc:
        logger.debug("[decision_read] build_decision_status_snapshot error: %r", exc)
        return {
            "flags":        flags,
            "counts":       empty_counts,
            "db_available": False,
            "safe_state":   False,
            "disclaimer":   _DISCLAIMER,
        }
