"""
Phase 10A · Slice 10 — Loop observability snapshot.

Produces a single consistent, null-safe, DB-down-safe snapshot of the entire
Phase 10A loop subsystem.  Intended callers:

  - GET /admin/loop-status (production admin endpoint)
  - tests/validate_10a_loop_shadow.py (deployment validation script)
  - integration tests

Design principles
-----------------
  - Never raises.  All DB calls are wrapped in try/except; missing data
    degrades gracefully to zero/null rather than failing the request.
  - No secrets.  API keys, database URLs, and user tokens are never
    included in the snapshot.
  - Fast.  DB queries are lightweight aggregates (GROUP BY state/outcome,
    COUNT(*)).  The watchlist integrity aggregates add GROUP BY/HAVING over
    watched_tickers and one LEFT JOIN to users for the orphan-owner check;
    all counting happens in the database, never by materialising rows.
  - Deterministic schema.  All keys are always present; absent/failed
    data is represented by 0 / null / {} rather than omitted keys.
  - Thread-safe for in-process telemetry reads (loop_canary_telemetry
    uses its own threading.Lock).

Snapshot structure (all top-level keys always present)
-------------------------------------------------------
  config          — loop flags from settings (no secrets)
  override        — kill-switch runtime state
  effective_enabled — bool resolved from config + override
  canary          — cohort pct, internal_only flag
  telemetry       — in-process counters from loop_canary_telemetry
  jobs            — DB counts by state
  runs            — DB counts by outcome + recent_runs list
  delivery        — DB counts by status
  locks           — tick lock + any active job locks
  guardrails      — all delivery + drift guardrail settings
  db_available    — bool, False if DB was unreachable during this snapshot
  snapshot_utc    — ISO-8601 timestamp of when the snapshot was taken
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


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return default


def _safe_str(val: Any, default: str = "") -> str:
    try:
        return str(val) if val is not None else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Config section — no secrets
# ---------------------------------------------------------------------------

def _config_section() -> Dict[str, Any]:
    try:
        from app.config import settings as _s
        return {
            "loop_enabled":          _safe_bool(_s.loop_enabled),
            "loop_shadow":           _safe_bool(_s.loop_shadow),
            "loop_canary_pct":       _safe_int(_s.loop_canary_pct),
            "loop_internal_only":    _safe_bool(_s.loop_internal_only),
            "loop_drift_gate_enabled": _safe_bool(_s.loop_drift_gate_enabled),
            "loop_force_run":        _safe_bool(_s.loop_force_run),
            "loop_drift_materiality_min": _safe_float(_s.loop_drift_materiality_min),
            "loop_tick_batch_size":  _safe_int(_s.loop_tick_batch_size),
            "loop_lock_lease_s":     _safe_int(_s.loop_lock_lease_s),
            "loop_retry_backoff_s":  _safe_int(_s.loop_retry_backoff_s),
        }
    except Exception:
        return {
            "loop_enabled": False, "loop_shadow": True,
            "loop_canary_pct": 0, "loop_internal_only": True,
            "loop_drift_gate_enabled": True, "loop_force_run": False,
            "loop_drift_materiality_min": 0.4,
            "loop_tick_batch_size": 10, "loop_lock_lease_s": 120,
            "loop_retry_backoff_s": 300,
        }


# ---------------------------------------------------------------------------
# In-process telemetry section
# ---------------------------------------------------------------------------

def _telemetry_section() -> Dict[str, Any]:
    try:
        from app.services import loop_canary_telemetry as _tel
        snap = _tel.snapshot()
        return snap
    except Exception:
        return {
            "kill_switch":    {"enabled_override": None, "effective_state": "config_governed"},
            "counters":       {
                "tick_count": 0, "jobs_claimed": 0, "jobs_succeeded": 0,
                "jobs_failed": 0, "jobs_skipped": 0, "delivery_shadow_count": 0,
                "duplicate_delivery_count": 0, "lock_contention_count": 0,
                "cost_guard_skip_count": 0,
            },
            "cohort_counts": {},
            "recent_ticks":  [],
        }


# ---------------------------------------------------------------------------
# DB sections — all best-effort
# ---------------------------------------------------------------------------

async def _jobs_section(session) -> Dict[str, Any]:
    try:
        from sqlalchemy import select, func
        from app.db.models import ScheduledJob

        r = await session.execute(
            select(ScheduledJob.state, func.count())
            .group_by(ScheduledJob.state)
        )
        by_state = {row[0]: row[1] for row in r.all()}
        return {
            "total":    sum(by_state.values()),
            "by_state": by_state,
        }
    except Exception as exc:
        logger.debug("[observability] jobs_section failed: %r", exc)
        return {"total": 0, "by_state": {}, "db_error": str(exc)}


async def _runs_section(session) -> Dict[str, Any]:
    try:
        from sqlalchemy import select, func
        from app.db.models import JobRun

        # Outcome counts
        rc = await session.execute(
            select(JobRun.outcome, func.count())
            .group_by(JobRun.outcome)
        )
        by_outcome = {row[0]: row[1] for row in rc.all()}

        # 10 most recent runs
        rr = await session.execute(
            select(JobRun)
            .order_by(JobRun.started_utc.desc())
            .limit(10)
        )
        recent = rr.scalars().all()

        return {
            "total":      sum(by_outcome.values()),
            "by_outcome": by_outcome,
            "recent":     [
                {
                    "id":           r.id,
                    "job_type":     r.job_type,
                    "target_key":   r.target_key,
                    "period_bucket": r.period_bucket,
                    "outcome":      r.outcome,
                    "drift_hit":    r.drift_hit,
                    "error":        r.error,
                    "holder_id":    r.holder_id,
                    "started_utc":  r.started_utc.isoformat() if r.started_utc else None,
                    "finished_utc": r.finished_utc.isoformat() if r.finished_utc else None,
                }
                for r in recent
            ],
        }
    except Exception as exc:
        logger.debug("[observability] runs_section failed: %r", exc)
        return {"total": 0, "by_outcome": {}, "recent": [], "db_error": str(exc)}


async def _watchlist_section(session) -> Dict[str, Any]:
    """Return watched-ticker and seeding state for shadow readiness validation."""
    try:
        from sqlalchemy import select, func, text
        from app.db.models import WatchedTicker, ScheduledJob, User

        # ---- watchlist integrity aggregates ----------------------------------
        # All computed in the database (GROUP BY / COUNT / SUM). Rows are never
        # pulled into Python to be counted. Aggregate-only by construction: no
        # user id, row id, email or group-level record leaves these queries.
        #
        # A "membership group" is (user_id, ticker) over ACTIVE rows with a
        # non-null owner. A group is duplicated when COUNT(*) > 1, and its
        # excess is COUNT(*) - 1 (the rows beyond the one legitimate row).
        _mem_groups = (
            select(func.count().label("c"))
            .select_from(WatchedTicker)
            .where(WatchedTicker.active.is_(True))
            .where(WatchedTicker.user_id.isnot(None))
            .group_by(WatchedTicker.user_id, WatchedTicker.ticker)
            .having(func.count() > 1)
            .subquery()
        )
        dup_mem = (await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(_mem_groups.c.c - 1), 0),
            ).select_from(_mem_groups)
        )).one()
        duplicate_membership_groups = int(dup_mem[0] or 0)
        duplicate_membership_excess_rows = int(dup_mem[1] or 0)

        # Legacy groups are keyed on ticker alone: the null-owner namespace is
        # a single shared watchlist, so two active null-owner rows for one
        # ticker are duplicates of each other.
        _legacy_groups = (
            select(func.count().label("c"))
            .select_from(WatchedTicker)
            .where(WatchedTicker.active.is_(True))
            .where(WatchedTicker.user_id.is_(None))
            .group_by(WatchedTicker.ticker)
            .having(func.count() > 1)
            .subquery()
        )
        dup_leg = (await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(_legacy_groups.c.c - 1), 0),
            ).select_from(_legacy_groups)
        )).one()
        duplicate_legacy_groups = int(dup_leg[0] or 0)
        duplicate_legacy_excess_rows = int(dup_leg[1] or 0)

        active_owner_count = int((await session.execute(
            select(func.count(func.distinct(WatchedTicker.user_id)))
            .where(WatchedTicker.active.is_(True))
            .where(WatchedTicker.user_id.isnot(None))
        )).scalar() or 0)

        # Orphan owners: active non-null owner values with no users-table row.
        # NOTE: there is NO foreign key between watched_tickers.user_id and
        # users.id (and the column widths differ: VARCHAR(64) vs VARCHAR(36)),
        # so this is an unenforced referential check computed by outer join,
        # not a constraint the database guarantees.
        _orph = (await session.execute(
            select(
                func.count(func.distinct(WatchedTicker.user_id)),
                func.count(),
            )
            .select_from(
                WatchedTicker.__table__.outerjoin(
                    User.__table__, User.id == WatchedTicker.user_id
                )
            )
            .where(WatchedTicker.active.is_(True))
            .where(WatchedTicker.user_id.isnot(None))
            .where(User.id.is_(None))
        )).one()
        orphan_owner_count = int(_orph[0] or 0)
        orphan_active_row_count = int(_orph[1] or 0)

        # Active ticker count and list
        tr = await session.execute(
            select(WatchedTicker.ticker)
            .where(WatchedTicker.active == True)  # noqa: E712
            .order_by(WatchedTicker.ticker)
        )
        active_tickers = [row[0] for row in tr.all()]

        # Count watchlist_scan jobs seeded (any state)
        jr = await session.execute(
            select(func.count()).select_from(ScheduledJob)
            .where(ScheduledJob.job_type == "watchlist_scan")
        )
        scan_jobs_total = jr.scalar() or 0

        # Duplicate detection: duplicate = same (job_type, target_key, period_bucket) twice
        # A well-seeded set has at most 1 per (job_type, target_key, period_bucket)
        dup_r = await session.execute(
            text(
                "SELECT COUNT(*) FROM ("
                "  SELECT job_type, target_key, period_bucket, COUNT(*) as c"
                "  FROM scheduled_jobs"
                "  GROUP BY job_type, target_key, period_bucket"
                "  HAVING COUNT(*) > 1"
                ") t"
            )
        )
        duplicate_job_combos = dup_r.scalar() or 0

        # Drift-skip count: job_runs with outcome=skipped_stale (drift gate fired)
        from app.db.models import JobRun
        ds_r = await session.execute(
            select(func.count()).select_from(JobRun)
            .where(JobRun.outcome == "skipped_stale")
        )
        drift_skip_count = ds_r.scalar() or 0

        return {
            # COMPATIBILITY: active_ticker_count is HISTORICAL and counts
            # ACTIVE ROWS, not distinct securities. Its name predates
            # multi-account ownership. It is preserved verbatim; do NOT read
            # it as a count of distinct tickers. Use distinct_ticker_count for
            # securities and active_row_count for rows.
            "active_ticker_count": len(active_tickers),
            "active_row_count":    len(active_tickers),
            "distinct_ticker_count": len(set(active_tickers)),
            "active_owner_count":  active_owner_count,
            # Duplicate integrity aggregates (DB-computed, aggregate-only).
            "duplicate_membership_groups":     duplicate_membership_groups,
            "duplicate_membership_excess_rows": duplicate_membership_excess_rows,
            "duplicate_legacy_groups":         duplicate_legacy_groups,
            "duplicate_legacy_excess_rows":    duplicate_legacy_excess_rows,
            # Unenforced referential check — no FK exists on this column.
            "orphan_owner_count":      orphan_owner_count,
            "orphan_active_row_count": orphan_active_row_count,
            "active_tickers":      active_tickers,
            "scan_jobs_total":     scan_jobs_total,
            "duplicate_job_combos": duplicate_job_combos,
            "drift_skip_count":    drift_skip_count,
        }
    except Exception as exc:
        logger.debug("[observability] watchlist_section failed: %r", exc)
        return {
            "active_ticker_count": 0,
            "active_row_count":    0,
            "distinct_ticker_count": 0,
            "active_owner_count": 0,
            "duplicate_membership_groups": 0,
            "duplicate_membership_excess_rows": 0,
            "duplicate_legacy_groups": 0,
            "duplicate_legacy_excess_rows": 0,
            "orphan_owner_count": 0,
            "orphan_active_row_count": 0,
            "active_tickers":      [],
            "scan_jobs_total":     0,
            "duplicate_job_combos": 0,
            "drift_skip_count":    0,
            "db_error":            str(exc),
        }


async def _delivery_section(session) -> Dict[str, Any]:
    try:
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        dr = await session.execute(
            select(DeliveryLedger.status, func.count())
            .group_by(DeliveryLedger.status)
        )
        by_status = {row[0]: row[1] for row in dr.all()}

        # Shadow-delivered count is particularly important for validation
        shadow_count = by_status.get("delivered_shadow", 0)

        return {
            "total":          sum(by_status.values()),
            "by_status":      by_status,
            "shadow_count":   shadow_count,
            "duplicate_total": 0,  # tracked in in-process telemetry counters
        }
    except Exception as exc:
        logger.debug("[observability] delivery_section failed: %r", exc)
        return {
            "total": 0, "by_status": {}, "shadow_count": 0,
            "duplicate_total": 0, "db_error": str(exc),
        }


async def _locks_section(session) -> Dict[str, Any]:
    try:
        from app.services.loop_lock_service import get_lock_state

        tick_lock = await get_lock_state(session, "loop:tick")
        return {
            "tick_lock": tick_lock,
            "tick_lock_held": tick_lock is not None and not tick_lock.get("is_expired", True),
        }
    except Exception as exc:
        logger.debug("[observability] locks_section failed: %r", exc)
        return {"tick_lock": None, "tick_lock_held": False, "db_error": str(exc)}


# ---------------------------------------------------------------------------
# Guardrails section
# ---------------------------------------------------------------------------

def _guardrails_section() -> Dict[str, Any]:
    try:
        from app.config import settings as _s
        return {
            "drift_gate_enabled":    _safe_bool(_s.loop_drift_gate_enabled),
            "drift_materiality_min": _safe_float(_s.loop_drift_materiality_min),
            "force_run":             _safe_bool(_s.loop_force_run),
            "quiet_hours_start_utc": _safe_int(_s.delivery_quiet_hours_start),
            "quiet_hours_end_utc":   _safe_int(_s.delivery_quiet_hours_end),
            "daily_cap":             _safe_int(_s.delivery_daily_cap),
            "severity_floor":        _safe_str(_s.delivery_severity_floor),
        }
    except Exception:
        return {
            "drift_gate_enabled": True, "drift_materiality_min": 0.4,
            "force_run": False, "quiet_hours_start_utc": 22,
            "quiet_hours_end_utc": 7, "daily_cap": 20, "severity_floor": "info",
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def build_snapshot(session=None) -> Dict[str, Any]:
    """Build a complete, null-safe loop observability snapshot.

    Parameters
    ----------
    session : AsyncSession or None.  When None, all DB sections return zeros;
              in-process telemetry and config sections still populate normally.

    Returns
    -------
    Dict — always succeeds; never raises.
    """
    snapshot_utc = _now_iso()
    db_available = session is not None

    # In-process sections (no DB needed)
    config_sec    = _config_section()
    telemetry_sec = _telemetry_section()
    guardrails_sec = _guardrails_section()

    # Resolve effective_enabled from config + override
    try:
        from app.services import loop_canary_telemetry as _tel
        effective_enabled = _tel.get_enabled(config_sec["loop_enabled"])
        override_state    = _tel.override_state()
    except Exception:
        effective_enabled = config_sec.get("loop_enabled", False)
        override_state    = None

    # DB sections (gracefully degrade to empty when session=None or DB is down)
    if session is not None:
        jobs_sec      = await _jobs_section(session)
        runs_sec      = await _runs_section(session)
        delivery_sec  = await _delivery_section(session)
        locks_sec     = await _locks_section(session)
        watchlist_sec = await _watchlist_section(session)

        # If any section carried a db_error, mark db_available=partial
        if any("db_error" in s for s in [jobs_sec, runs_sec, delivery_sec, locks_sec, watchlist_sec]):
            db_available = "partial"
    else:
        jobs_sec      = {"total": 0, "by_state": {}}
        runs_sec      = {"total": 0, "by_outcome": {}, "recent": []}
        delivery_sec  = {"total": 0, "by_status": {}, "shadow_count": 0, "duplicate_total": 0}
        locks_sec     = {"tick_lock": None, "tick_lock_held": False}
        watchlist_sec = {
            "active_ticker_count": 0, "active_row_count": 0,
            "distinct_ticker_count": 0,
            "active_owner_count": 0,
            "duplicate_membership_groups": 0,
            "duplicate_membership_excess_rows": 0,
            "duplicate_legacy_groups": 0,
            "duplicate_legacy_excess_rows": 0,
            "orphan_owner_count": 0,
            "orphan_active_row_count": 0,
            "active_tickers": [],
            "scan_jobs_total": 0, "duplicate_job_combos": 0, "drift_skip_count": 0,
        }

    return {
        "status":           "ok",
        "snapshot_utc":     snapshot_utc,
        "db_available":     db_available,
        # Loop master state
        "loop_enabled":     config_sec["loop_enabled"],
        "loop_shadow":      config_sec["loop_shadow"],
        "effective_enabled": effective_enabled,
        "override_state":   override_state,
        # Canary rollout
        "canary": {
            "canary_pct":       config_sec["loop_canary_pct"],
            "internal_only":    config_sec["loop_internal_only"],
            "cohort_counts":    telemetry_sec.get("cohort_counts", {}),
        },
        # In-process counters
        "telemetry":   telemetry_sec,
        # Config snapshot (no secrets)
        "config":      config_sec,
        # DB state
        "jobs":        jobs_sec,
        "runs":        runs_sec,
        "delivery":    delivery_sec,
        "locks":       locks_sec,
        # Phase 10B — Watchlist shadow state
        "watchlist":   watchlist_sec,
        # Guardrails
        "guardrails":  guardrails_sec,
    }


def build_snapshot_sync(session=None) -> Dict[str, Any]:
    """Synchronous wrapper — returns a partial snapshot without DB sections.

    Useful for scripts that don't have an asyncio event loop.  DB fields
    are populated with safe zeros; all in-process sections are live.
    """
    snapshot_utc = _now_iso()
    config_sec    = _config_section()
    telemetry_sec = _telemetry_section()
    guardrails_sec = _guardrails_section()

    try:
        from app.services import loop_canary_telemetry as _tel
        effective_enabled = _tel.get_enabled(config_sec["loop_enabled"])
        override_state    = _tel.override_state()
    except Exception:
        effective_enabled = config_sec.get("loop_enabled", False)
        override_state    = None

    return {
        "status":           "ok",
        "snapshot_utc":     snapshot_utc,
        "db_available":     False,
        "loop_enabled":     config_sec["loop_enabled"],
        "loop_shadow":      config_sec["loop_shadow"],
        "effective_enabled": effective_enabled,
        "override_state":   override_state,
        "canary": {
            "canary_pct":       config_sec["loop_canary_pct"],
            "internal_only":    config_sec["loop_internal_only"],
            "cohort_counts":    telemetry_sec.get("cohort_counts", {}),
        },
        "telemetry":   telemetry_sec,
        "config":      config_sec,
        "jobs":        {"total": 0, "by_state": {}},
        "runs":        {"total": 0, "by_outcome": {}, "recent": []},
        "delivery":    {"total": 0, "by_status": {}, "shadow_count": 0, "duplicate_total": 0},
        "locks":       {"tick_lock": None, "tick_lock_held": False},
        "watchlist":   {
            "active_ticker_count": 0, "active_row_count": 0,
            "distinct_ticker_count": 0,
            "active_owner_count": 0,
            "duplicate_membership_groups": 0,
            "duplicate_membership_excess_rows": 0,
            "duplicate_legacy_groups": 0,
            "duplicate_legacy_excess_rows": 0,
            "orphan_owner_count": 0,
            "orphan_active_row_count": 0,
            "active_tickers": [],
            "scan_jobs_total": 0, "duplicate_job_combos": 0, "drift_skip_count": 0,
        },
        "guardrails":  guardrails_sec,
    }
