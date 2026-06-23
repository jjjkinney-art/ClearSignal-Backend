"""
Session Context Service — Phase 20A · Issue 3 + 4.

Lightweight in-memory tracker that remembers the last company analyzed
per session, enabling follow-up questions to auto-resolve:

  "NVDA"                         → analyzes NVDA, stores as active ticker
  "What breaks the thesis?"      → resolves to NVDA via session context
  "What if AI CapEx falls 20%?"  → resolves to NVDA via session context

The store is a bounded LRU dict — no database, no persistence across
restarts.  This is intentional: session context is ephemeral UI state,
not durable intelligence.

Thread-safety: uses a threading.Lock for the in-memory dict.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_MAX_SESSIONS: int = 10_000
_lock = threading.Lock()
_store: OrderedDict[str, Dict[str, Any]] = OrderedDict()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_active_ticker(
    session_id: str,
    ticker: str,
    company_name: str = "",
) -> None:
    """Record the last company analyzed for a session.

    Called after a successful investment-pipeline run.
    """
    if not session_id or not ticker:
        return
    with _lock:
        _store[session_id] = {
            "ticker":       ticker,
            "company_name": company_name,
            "updated_at":   _now(),
        }
        _store.move_to_end(session_id)
        while len(_store) > _MAX_SESSIONS:
            _store.popitem(last=False)


def get_active_ticker(session_id: str) -> Optional[str]:
    """Return the last active ticker for a session, or None."""
    if not session_id:
        return None
    with _lock:
        entry = _store.get(session_id)
        if entry:
            _store.move_to_end(session_id)
            return entry["ticker"]
    return None


def get_session_context(session_id: str) -> Optional[Dict[str, Any]]:
    """Return the full session context dict, or None."""
    if not session_id:
        return None
    with _lock:
        return _store.get(session_id)


def clear_session(session_id: str) -> None:
    """Remove session context (e.g. on explicit user reset)."""
    if not session_id:
        return
    with _lock:
        _store.pop(session_id, None)
