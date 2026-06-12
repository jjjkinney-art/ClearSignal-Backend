"""
Phase 10A · Slice 9 — In-process telemetry and kill-switch for the loop canary.

Owns:
  - Runtime kill-switch override (POST /admin/loop/disable|enable)
  - Per-tick telemetry counters
  - Cohort assignment counts
  - Recent tick summaries (ring buffer)

Override semantics (mirrors dossier_canary_telemetry pattern):
  None  → use config (loop_enabled)
  False → force-disabled (kill switch)
  True  → NOT USED (enable clears the override, restoring config governance)

Pure in-memory, process-local, thread-safe.  Resets on restart.
Tests should call reset() in their teardown.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

_LOCK = threading.Lock()
_MAX_RECENT_TICKS = 50

# ── Kill-switch runtime override ──────────────────────────────────────────────
# None  → use config (settings.loop_enabled governs)
# False → force-disabled regardless of config
_enabled_override: Optional[bool] = None


def get_enabled(config_enabled: bool) -> bool:
    """Resolve effective enabled state: override wins over config."""
    with _LOCK:
        if _enabled_override is None:
            return config_enabled
        return _enabled_override


def force_disable() -> None:
    """Tier-0 kill switch: disable loop immediately without redeploy."""
    global _enabled_override
    with _LOCK:
        _enabled_override = False


def force_enable() -> None:
    """Clear the force-disable override, restoring config governance."""
    global _enabled_override
    with _LOCK:
        _enabled_override = None


def override_state() -> Optional[bool]:
    """Return the current override value (None | False)."""
    with _LOCK:
        return _enabled_override


# ── Telemetry counters ────────────────────────────────────────────────────────
_tick_count:              int = 0
_jobs_claimed:            int = 0
_jobs_succeeded:          int = 0
_jobs_failed:             int = 0
_jobs_skipped:            int = 0   # drift gate + idempotency skips
_delivery_shadow_count:   int = 0
_duplicate_delivery_count: int = 0
_lock_contention_count:   int = 0   # tick lock not acquired
_cost_guard_skip_count:   int = 0   # drift gate skips specifically

# Cohort counts
_cohort_counts: Counter = Counter()

# Recent tick summaries (newest first)
_recent_ticks: Deque[Dict[str, Any]] = deque(maxlen=_MAX_RECENT_TICKS)


def record_tick(result: Any) -> None:
    """Record telemetry from one TickResult.

    Accepts the TickResult dataclass from loop_scheduler_service without
    importing it directly (avoids circular imports).
    """
    global _tick_count, _jobs_claimed, _jobs_succeeded, _jobs_failed
    global _jobs_skipped, _lock_contention_count

    with _LOCK:
        _tick_count += 1

        claimed    = getattr(result, "jobs_claimed",        0) or 0
        succeeded  = getattr(result, "jobs_succeeded",      0) or 0
        failed     = getattr(result, "jobs_failed",         0) or 0
        skipped    = getattr(result, "jobs_short_circuited", 0) or 0
        contended  = not bool(getattr(result, "tick_acquired", True))

        _jobs_claimed   += claimed
        _jobs_succeeded += succeeded
        _jobs_failed    += failed
        _jobs_skipped   += skipped
        if contended:
            _lock_contention_count += 1

        _recent_ticks.appendleft({
            "ts":                getattr(result, "ts", ""),
            "loop_enabled":      getattr(result, "loop_enabled",       False),
            "tick_acquired":     getattr(result, "tick_acquired",      False),
            "jobs_claimed":      claimed,
            "jobs_succeeded":    succeeded,
            "jobs_failed":       failed,
            "jobs_short_circuited": skipped,
            "locks_reaped":      getattr(result, "locks_reaped",       0),
            "errors":            list(getattr(result, "errors",        [])),
        })


def record_delivery_shadow(count: int = 1) -> None:
    """Increment shadow delivery counter."""
    global _delivery_shadow_count
    with _LOCK:
        _delivery_shadow_count += count


def record_duplicate_delivery(count: int = 1) -> None:
    """Increment duplicate delivery suppression counter."""
    global _duplicate_delivery_count
    with _LOCK:
        _duplicate_delivery_count += count


def record_cost_guard_skip(count: int = 1) -> None:
    """Increment drift-gate skip counter."""
    global _cost_guard_skip_count
    with _LOCK:
        _cost_guard_skip_count += count


def record_cohort(cohort: str) -> None:
    """Increment cohort assignment counter."""
    with _LOCK:
        _cohort_counts[cohort] += 1


def snapshot() -> Dict[str, Any]:
    """Return a JSON-serialisable snapshot of all loop telemetry."""
    with _LOCK:
        return {
            "kill_switch": {
                "enabled_override": _enabled_override,
                "effective_state":  "force_disabled" if _enabled_override is False
                                    else "config_governed",
            },
            "counters": {
                "tick_count":               _tick_count,
                "jobs_claimed":             _jobs_claimed,
                "jobs_succeeded":           _jobs_succeeded,
                "jobs_failed":              _jobs_failed,
                "jobs_skipped":             _jobs_skipped,
                "delivery_shadow_count":    _delivery_shadow_count,
                "duplicate_delivery_count": _duplicate_delivery_count,
                "lock_contention_count":    _lock_contention_count,
                "cost_guard_skip_count":    _cost_guard_skip_count,
            },
            "cohort_counts": dict(_cohort_counts),
            "recent_ticks":  list(_recent_ticks)[:10],
        }


def reset() -> None:
    """Clear all counters and the kill-switch override.  Used by tests."""
    global _tick_count, _jobs_claimed, _jobs_succeeded, _jobs_failed
    global _jobs_skipped, _delivery_shadow_count, _duplicate_delivery_count
    global _lock_contention_count, _cost_guard_skip_count, _enabled_override

    with _LOCK:
        _tick_count              = 0
        _jobs_claimed            = 0
        _jobs_succeeded          = 0
        _jobs_failed             = 0
        _jobs_skipped            = 0
        _delivery_shadow_count   = 0
        _duplicate_delivery_count = 0
        _lock_contention_count   = 0
        _cost_guard_skip_count   = 0
        _enabled_override        = None
        _cohort_counts.clear()
        _recent_ticks.clear()
