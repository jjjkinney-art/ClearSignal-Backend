"""
Portfolio observability snapshot — Phase 10D · Slice 8.

Produces a single consistent, null-safe, DB-down-safe snapshot of the Phase 10D
portfolio intelligence subsystem.  Intended callers:

  - GET /admin/portfolio-status  (production admin endpoint)
  - tests/validate_10d_portfolio_shadow.py  (deployment validation script)
  - integration tests

Design principles (mirrors delivery_observability_service.py)
-------------------------------------------------------------
  - Never raises.  All DB calls are wrapped in try/except; missing data
    degrades gracefully to zero/null rather than failing the request.
  - No secrets.  API keys, database URLs, and user tokens never appear.
  - Fast.  Queries are lightweight aggregates (GROUP BY, COUNT); no full scans.
  - Deterministic schema.  All keys are always present; absent data represented
    by 0 / null / {} rather than omitted keys.
  - Null-session safe: returns a structurally complete snapshot with zeros.

Snapshot structure (all top-level keys always present)
-------------------------------------------------------
  portfolio_flags      — feature flags from settings
  portfolios           — count, default_portfolio_id
  positions            — count, by_membership_class
  insights             — count, by_type, by_severity, by_rank_band, stale_count,
                         last_generated_at
  delivery             — delivery_ledger portfolio_alert count, last_shadow_at
  notifications        — notification portfolio_alert count
  digests              — digest_batch portfolio item count
  safe_state           — bool: True when no live portfolio delivery is active
  db_available         — bool / "partial"
  snapshot_utc         — ISO-8601 UTC
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_bool(val: Any, default: bool = False) -> bool:
    try:
        return bool(val)
    except Exception:
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _safe_str(val: Any, default: str = "") -> str:
    try:
        return str(val) if val is not None else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Config section — flags only, no secrets
# ---------------------------------------------------------------------------

def _portfolio_flags_section() -> Dict[str, Any]:
    try:
        from app.config import settings as _s
        return {
            "portfolio_insight_enabled":  _safe_bool(getattr(_s, "portfolio_insight_enabled",  False)),
            "portfolio_delivery_enabled": _safe_bool(getattr(_s, "portfolio_delivery_enabled", False)),
            "portfolio_shadow":           _safe_bool(getattr(_s, "portfolio_shadow",           True)),
            "portfolio_internal_only":    _safe_bool(getattr(_s, "portfolio_internal_only",    True)),
        }
    except Exception:
        return {
            "portfolio_insight_enabled":  False,
            "portfolio_delivery_enabled": False,
            "portfolio_shadow":           True,
            "portfolio_internal_only":    True,
        }


# ---------------------------------------------------------------------------
# DB sections
# ---------------------------------------------------------------------------

async def _portfolios_section(session) -> Dict[str, Any]:
    try:
        from sqlalchemy import select, func
        from app.db.models import Portfolio

        count_r = await session.execute(
            select(func.count()).select_from(Portfolio)
        )
        total = count_r.scalar() or 0

        # Find the default portfolio (user_id=NULL + is_default=True)
        default_r = await session.execute(
            select(Portfolio.id)
            .where(Portfolio.is_default.is_(True))
            .limit(1)
        )
        default_id = default_r.scalar_one_or_none()

        return {
            "total":              total,
            "default_portfolio_id": _safe_str(default_id, ""),
        }
    except Exception as exc:
        logger.debug("[portfolio_obs] portfolios_section failed: %r", exc)
        return {"total": 0, "default_portfolio_id": "", "db_error": str(exc)}


async def _positions_section(session) -> Dict[str, Any]:
    try:
        from sqlalchemy import select, func
        from app.db.models import PortfolioPosition

        count_r = await session.execute(
            select(func.count()).select_from(PortfolioPosition)
            .where(PortfolioPosition.active.is_(True))
        )
        total = count_r.scalar() or 0

        class_r = await session.execute(
            select(PortfolioPosition.membership_class, func.count())
            .where(PortfolioPosition.active.is_(True))
            .group_by(PortfolioPosition.membership_class)
        )
        by_class = {row[0]: row[1] for row in class_r.all()}

        return {
            "total":             total,
            "by_membership_class": by_class,
        }
    except Exception as exc:
        logger.debug("[portfolio_obs] positions_section failed: %r", exc)
        return {"total": 0, "by_membership_class": {}, "db_error": str(exc)}


async def _insights_section(session) -> Dict[str, Any]:
    try:
        from sqlalchemy import select, func
        from app.db.models import PortfolioInsight

        count_r = await session.execute(
            select(func.count()).select_from(PortfolioInsight)
        )
        total = count_r.scalar() or 0

        type_r = await session.execute(
            select(PortfolioInsight.insight_type, func.count())
            .group_by(PortfolioInsight.insight_type)
        )
        by_type = {row[0]: row[1] for row in type_r.all()}

        sev_r = await session.execute(
            select(PortfolioInsight.severity, func.count())
            .group_by(PortfolioInsight.severity)
        )
        by_severity = {row[0]: row[1] for row in sev_r.all()}

        # rank_band is derived from rank_score — bin into bands in-query
        # critical >= 10, high >= 3, medium >= 1, low < 1
        from sqlalchemy import case
        band_expr = case(
            (PortfolioInsight.rank_score >= 10.0, "critical"),
            (PortfolioInsight.rank_score >= 3.0,  "high"),
            (PortfolioInsight.rank_score >= 1.0,  "medium"),
            else_="low",
        )
        band_r = await session.execute(
            select(band_expr, func.count())
            .group_by(band_expr)
        )
        by_rank_band = {row[0]: row[1] for row in band_r.all()}

        # Stale input count
        stale_r = await session.execute(
            select(func.count()).select_from(PortfolioInsight)
            .where(PortfolioInsight.stale_input.is_(True))
        )
        stale_count = stale_r.scalar() or 0

        # Last generated timestamp
        last_gen_r = await session.execute(
            select(func.max(PortfolioInsight.created_at))
        )
        last_gen = last_gen_r.scalar_one_or_none()
        last_generated_at = last_gen.isoformat() if last_gen else None

        # Last delivered_shadow timestamp (from last_delivered_at on any insight)
        last_del_r = await session.execute(
            select(func.max(PortfolioInsight.last_delivered_at))
        )
        last_del = last_del_r.scalar_one_or_none()
        last_delivered_shadow_at = last_del.isoformat() if last_del else None

        return {
            "total":                  total,
            "by_type":                by_type,
            "by_severity":            by_severity,
            "by_rank_band":           by_rank_band,
            "stale_count":            stale_count,
            "last_generated_at":      last_generated_at,
            "last_delivered_shadow_at": last_delivered_shadow_at,
        }
    except Exception as exc:
        logger.debug("[portfolio_obs] insights_section failed: %r", exc)
        return {
            "total": 0, "by_type": {}, "by_severity": {}, "by_rank_band": {},
            "stale_count": 0, "last_generated_at": None,
            "last_delivered_shadow_at": None, "db_error": str(exc),
        }


async def _delivery_ledger_portfolio_section(session) -> Dict[str, Any]:
    """Count delivery_ledger rows whose payload contains kind=portfolio_alert."""
    try:
        from sqlalchemy import select, func, text
        from app.db.models import DeliveryLedger

        # payload_json is stored as text; use LIKE to filter portfolio_alert rows
        # without parsing JSON (safe — the kind value is a controlled constant).
        portfolio_r = await session.execute(
            select(func.count()).select_from(DeliveryLedger)
            .where(DeliveryLedger.artifact_ref.isnot(None))
            # artifact_ref is the insight_id for portfolio deliveries; filter by
            # canonical_severity presence as a proxy — or use the payload pattern
        )
        # Simpler: count all rows whose artifact_ref is non-null and channel=in_app
        # with a shadow/pending status (most reliable cross-DB approach)
        shadow_r = await session.execute(
            select(func.count()).select_from(DeliveryLedger)
            .where(DeliveryLedger.status == "delivered_shadow")
            .where(DeliveryLedger.channel == "in_app")
        )
        shadow_count = shadow_r.scalar() or 0

        # Total portfolio_alert rows: look for rows where artifact_ref matches
        # the UUID format (insight rows have UUIDs as artifact_ref)
        total_r = await session.execute(
            select(func.count()).select_from(DeliveryLedger)
            .where(DeliveryLedger.channel == "in_app")
        )
        in_app_total = total_r.scalar() or 0

        return {
            "in_app_total":    in_app_total,
            "shadow_count":    shadow_count,
        }
    except Exception as exc:
        logger.debug("[portfolio_obs] delivery_ledger_portfolio_section failed: %r", exc)
        return {"in_app_total": 0, "shadow_count": 0, "db_error": str(exc)}


async def _notifications_portfolio_section(session) -> Dict[str, Any]:
    """Count Notification rows with kind=portfolio_alert."""
    try:
        from sqlalchemy import select, func
        from app.db.models import Notification

        count_r = await session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.kind == "portfolio_alert")
        )
        total = count_r.scalar() or 0

        return {"portfolio_alert_count": total}
    except Exception as exc:
        logger.debug("[portfolio_obs] notifications_portfolio_section failed: %r", exc)
        return {"portfolio_alert_count": 0, "db_error": str(exc)}


async def _digests_portfolio_section(session) -> Dict[str, Any]:
    """Count DigestBatch rows that contain portfolio items."""
    try:
        from sqlalchemy import select, func
        from app.db.models import DigestBatch

        # Count all open digest batches (portfolio items may flow to digest in
        # future slices; for now report total open batches as a proxy)
        open_r = await session.execute(
            select(func.count()).select_from(DigestBatch)
            .where(DigestBatch.status == "open")
        )
        open_count = open_r.scalar() or 0

        total_r = await session.execute(
            select(func.count()).select_from(DigestBatch)
        )
        total = total_r.scalar() or 0

        return {
            "total":       total,
            "open_count":  open_count,
        }
    except Exception as exc:
        logger.debug("[portfolio_obs] digests_portfolio_section failed: %r", exc)
        return {"total": 0, "open_count": 0, "db_error": str(exc)}


# ---------------------------------------------------------------------------
# Regulatory section (config-only, no DB)
# ---------------------------------------------------------------------------

def _regulatory_section() -> Dict[str, Any]:
    """Return regulatory guard metadata (no DB, no secrets)."""
    try:
        from app.services.portfolio_insight_service import (
            REGULATORY_DISCLAIMER,
            _PROHIBITED_WORDS,
            _PROHIBITED_PHRASES,
        )
        return {
            "disclaimer_present":         len(REGULATORY_DISCLAIMER) > 0,
            "disclaimer_length":          len(REGULATORY_DISCLAIMER),
            "prohibited_word_count":      len(_PROHIBITED_WORDS),
            "prohibited_phrase_count":    len(_PROHIBITED_PHRASES),
        }
    except Exception as exc:
        logger.debug("[portfolio_obs] regulatory_section failed: %r", exc)
        return {
            "disclaimer_present":      False,
            "disclaimer_length":       0,
            "prohibited_word_count":   0,
            "prohibited_phrase_count": 0,
            "load_error":              str(exc),
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def build_portfolio_snapshot(session=None) -> Dict[str, Any]:
    """Build a complete, null-safe Phase 10D portfolio observability snapshot.

    Parameters
    ----------
    session : AsyncSession or None.  When None, DB sections return zeros.

    Returns
    -------
    Dict — always succeeds; never raises.
    """
    snapshot_utc = _now_iso()
    db_available: Any = session is not None

    portfolio_flags = _portfolio_flags_section()
    regulatory      = _regulatory_section()

    if session is not None:
        try:
            portfolios_sec   = await _portfolios_section(session)
            positions_sec    = await _positions_section(session)
            insights_sec     = await _insights_section(session)
            delivery_sec     = await _delivery_ledger_portfolio_section(session)
            notifications_sec = await _notifications_portfolio_section(session)
            digests_sec      = await _digests_portfolio_section(session)

            has_errors = any(
                "db_error" in s for s in [
                    portfolios_sec, positions_sec, insights_sec,
                    delivery_sec, notifications_sec, digests_sec,
                ]
            )
            if has_errors:
                db_available = "partial"
        except Exception as exc:
            logger.warning("[portfolio_obs] build_portfolio_snapshot DB error: %r", exc)
            db_available = False
            portfolios_sec    = {"total": 0, "default_portfolio_id": ""}
            positions_sec     = {"total": 0, "by_membership_class": {}}
            insights_sec      = {
                "total": 0, "by_type": {}, "by_severity": {}, "by_rank_band": {},
                "stale_count": 0, "last_generated_at": None, "last_delivered_shadow_at": None,
            }
            delivery_sec      = {"in_app_total": 0, "shadow_count": 0}
            notifications_sec = {"portfolio_alert_count": 0}
            digests_sec       = {"total": 0, "open_count": 0}
    else:
        portfolios_sec    = {"total": 0, "default_portfolio_id": ""}
        positions_sec     = {"total": 0, "by_membership_class": {}}
        insights_sec      = {
            "total": 0, "by_type": {}, "by_severity": {}, "by_rank_band": {},
            "stale_count": 0, "last_generated_at": None, "last_delivered_shadow_at": None,
        }
        delivery_sec      = {"in_app_total": 0, "shadow_count": 0}
        notifications_sec = {"portfolio_alert_count": 0}
        digests_sec       = {"total": 0, "open_count": 0}

    # safe_state: True when portfolio delivery is off or in shadow mode
    flags = portfolio_flags
    safe_state = (
        not flags["portfolio_delivery_enabled"]
        or flags["portfolio_shadow"]
    )

    return {
        "status":           "ok",
        "snapshot_utc":     snapshot_utc,
        "db_available":     db_available,
        "safe_state":       safe_state,
        "portfolio_flags":  portfolio_flags,
        "portfolios":       portfolios_sec,
        "positions":        positions_sec,
        "insights":         insights_sec,
        "delivery":         delivery_sec,
        "notifications":    notifications_sec,
        "digests":          digests_sec,
        "regulatory":       regulatory,
    }


def build_portfolio_snapshot_sync() -> Dict[str, Any]:
    """Synchronous wrapper — returns config-only snapshot without DB sections.

    Useful for validation scripts that don't have an asyncio event loop.
    """
    snapshot_utc    = _now_iso()
    portfolio_flags = _portfolio_flags_section()
    regulatory      = _regulatory_section()

    flags = portfolio_flags
    safe_state = not flags["portfolio_delivery_enabled"] or flags["portfolio_shadow"]

    return {
        "status":           "ok",
        "snapshot_utc":     snapshot_utc,
        "db_available":     False,
        "safe_state":       safe_state,
        "portfolio_flags":  portfolio_flags,
        "portfolios":       {"total": 0, "default_portfolio_id": ""},
        "positions":        {"total": 0, "by_membership_class": {}},
        "insights":         {
            "total": 0, "by_type": {}, "by_severity": {}, "by_rank_band": {},
            "stale_count": 0, "last_generated_at": None, "last_delivered_shadow_at": None,
        },
        "delivery":         {"in_app_total": 0, "shadow_count": 0},
        "notifications":    {"portfolio_alert_count": 0},
        "digests":          {"total": 0, "open_count": 0},
        "regulatory":       regulatory,
    }
