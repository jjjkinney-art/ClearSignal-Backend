"""
Phase 9G · Slice 5A — in-process telemetry for shadow dossier injection.

Records the size and facet composition of every injection block built in shadow
mode so ``GET /admin/dossier-injection-status`` can report:
  * token-size distribution (p50 / p95 / p100) — the cap-compliance evidence;
  * per-facet inclusion frequency;
  * staleness mix;
  * a small ring buffer of the most recent records for spot inspection.

Pure in-memory, process-local, thread-safe.  Resets on restart (shadow
telemetry is observational, not durable).  No effect on request behaviour.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from typing import Any, Deque, Dict, List, Optional

_LOCK = threading.Lock()
_MAX_RECENT = 50

# Observed token counts (bounded so memory can't grow without limit).
_token_counts: Deque[int] = deque(maxlen=2000)
_facet_freq: Counter = Counter()
_dropped_freq: Counter = Counter()
_staleness_freq: Counter = Counter()
_intent_freq: Counter = Counter()
_recent: Deque[Dict[str, Any]] = deque(maxlen=_MAX_RECENT)
_built = 0          # blocks successfully built (non-None result)
_null = 0           # times the formatter returned None (nothing to inject)
_over_cap = 0       # blocks observed above the cap (should always be 0)


def record_build(
    ticker: str,
    token_count: int,
    staleness_state: str,
    intent: str,
    included_facets: List[str],
    dropped_facets: List[Any],
    token_cap: int,
) -> None:
    """Record one successfully built injection block."""
    global _built, _over_cap
    with _LOCK:
        _built += 1
        _token_counts.append(int(token_count))
        _facet_freq.update(included_facets or [])
        _dropped_freq.update([d[0] if isinstance(d, (list, tuple)) else d
                              for d in (dropped_facets or [])])
        _staleness_freq.update([staleness_state or "unknown"])
        _intent_freq.update([intent or "general"])
        if token_count > token_cap:
            _over_cap += 1
        _recent.appendleft({
            "ticker": ticker,
            "tokens": int(token_count),
            "staleness": staleness_state,
            "intent": intent,
            "included": list(included_facets or []),
            "dropped": [d[0] if isinstance(d, (list, tuple)) else d
                        for d in (dropped_facets or [])],
        })


def record_null(ticker: str) -> None:
    """Record a request where the formatter returned None (no dossier / nothing)."""
    global _null
    with _LOCK:
        _null += 1


def _percentile(sorted_vals: List[int], pct: float) -> Optional[int]:
    if not sorted_vals:
        return None
    if pct <= 0:
        return sorted_vals[0]
    if pct >= 100:
        return sorted_vals[-1]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return int(round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac))


def snapshot() -> Dict[str, Any]:
    """Return a JSON-serialisable telemetry snapshot."""
    with _LOCK:
        vals = sorted(_token_counts)
        return {
            "blocks_built":      _built,
            "null_results":      _null,
            "over_cap_count":    _over_cap,
            "token_p50":         _percentile(vals, 50),
            "token_p95":         _percentile(vals, 95),
            "token_p100":        _percentile(vals, 100),
            "token_samples":     len(vals),
            "facet_inclusion":   dict(_facet_freq),
            "facet_dropped":     dict(_dropped_freq),
            "staleness_mix":     dict(_staleness_freq),
            "intent_mix":        dict(_intent_freq),
            "recent":            list(_recent),
        }


def reset() -> None:
    """Clear all telemetry (used by tests)."""
    global _built, _null, _over_cap
    with _LOCK:
        _token_counts.clear()
        _facet_freq.clear()
        _dropped_freq.clear()
        _staleness_freq.clear()
        _intent_freq.clear()
        _recent.clear()
        _built = 0
        _null = 0
        _over_cap = 0
