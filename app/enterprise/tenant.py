"""
Tenant-safe architecture hooks.

Provides real code paths (not TODO stubs) for future multi-user and
enterprise safety without requiring full auth infrastructure now.

Key abstractions
----------------
TenantScope : identifies an organizational tenant (e.g. firm)
UserScope   : identifies a user within a tenant
ScopeContext: combined scope used throughout the request pipeline

All watchlists, saved analyses, alert subscriptions, and data-access
restrictions flow through a ScopeContext.  Storage interfaces are
scope-aware so data isolation can be enforced by adding a tenant_id
column filter when needed.

Usage::

    scope = ScopeContext(tenant_id="firm-abc", user_id="user-1")
    # All storage queries in this request are scoped
    alerts = get_scoped_alerts(scope)
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ── Scope types ──────────────────────────────────────────────────────────

@dataclass
class TenantScope:
    """Identifies an organizational tenant.

    Attributes
    ----------
    tenant_id       : unique identifier for the tenant
    name            : display name
    allowed_sources : explicit list of data sources this tenant may use
                      (empty = all sources allowed)
    max_watchlist   : maximum number of watched companies (0 = unlimited)
    feature_flags   : per-tenant feature toggles
    """
    tenant_id:       str
    name:            str = ""
    allowed_sources: List[str] = field(default_factory=list)
    max_watchlist:   int = 0
    feature_flags:   Dict[str, bool] = field(default_factory=dict)


@dataclass
class UserScope:
    """Identifies a user within a tenant.

    Attributes
    ----------
    user_id     : unique user identifier
    tenant_id   : owning tenant
    roles       : list of role strings (e.g. ["analyst", "viewer"])
    preferences : user-level config (alert sensitivity, focus, etc.)
    """
    user_id:     str
    tenant_id:   str = ""
    roles:       List[str] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def get_preference(self, key: str, default: Any = None) -> Any:
        return self.preferences.get(key, default)


@dataclass
class ScopeContext:
    """Combined user + tenant scope for a request.

    This is the primary scope object threaded through the request
    pipeline.  All scoped storage and access decisions reference this.

    Attributes
    ----------
    user_id         : user identifier (empty = anonymous/system)
    tenant_id       : tenant identifier (empty = single-tenant)
    session_id      : optional session for grouping related requests
    user_scope      : full UserScope object if available
    tenant_scope    : full TenantScope object if available
    request_id      : linked request ID
    """
    user_id:      str = ""
    tenant_id:    str = ""
    session_id:   str = ""
    user_scope:   Optional[UserScope] = None
    tenant_scope: Optional[TenantScope] = None
    request_id:   str = ""

    def is_anonymous(self) -> bool:
        return not self.user_id

    def is_multi_tenant(self) -> bool:
        return bool(self.tenant_id)

    def storage_prefix(self) -> str:
        """Return a storage namespace prefix for this scope."""
        if self.tenant_id and self.user_id:
            return f"{self.tenant_id}:{self.user_id}"
        if self.tenant_id:
            return self.tenant_id
        return "default"

    def allowed_sources(self) -> List[str]:
        """Return allowed data sources for this scope (empty = all)."""
        if self.tenant_scope and self.tenant_scope.allowed_sources:
            return list(self.tenant_scope.allowed_sources)
        return []

    def can_access_source(self, source: str) -> bool:
        allowed = self.allowed_sources()
        if not allowed:
            return True   # no restrictions
        return source in allowed

    def user_preference(self, key: str, default: Any = None) -> Any:
        if self.user_scope:
            return self.user_scope.get_preference(key, default)
        return default

    def feature_enabled(self, flag: str) -> bool:
        if self.tenant_scope:
            return self.tenant_scope.feature_flags.get(flag, False)
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id":   self.user_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "is_anonymous": self.is_anonymous(),
            "storage_prefix": self.storage_prefix(),
        }


# ── Scope-aware storage interface stubs ──────────────────────────────────

class ScopedWatchlist:
    """Scope-isolated watchlist for tracked companies.

    In a multi-tenant deployment this would query a scoped table.
    In single-tenant mode it uses a shared in-memory store.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Set[str]] = {}   # prefix → set of tickers
        self._lock  = threading.Lock()

    def add(self, ticker: str, scope: ScopeContext) -> None:
        prefix = scope.storage_prefix()
        tenant_scope = scope.tenant_scope
        if tenant_scope and tenant_scope.max_watchlist > 0:
            current = self.get(scope)
            if len(current) >= tenant_scope.max_watchlist:
                raise ValueError(
                    f"Watchlist limit {tenant_scope.max_watchlist} reached for scope '{prefix}'"
                )
        with self._lock:
            self._store.setdefault(prefix, set()).add(ticker.upper())

    def remove(self, ticker: str, scope: ScopeContext) -> None:
        prefix = scope.storage_prefix()
        with self._lock:
            if prefix in self._store:
                self._store[prefix].discard(ticker.upper())

    def get(self, scope: ScopeContext) -> List[str]:
        prefix = scope.storage_prefix()
        with self._lock:
            return sorted(self._store.get(prefix, set()))

    def is_watched(self, ticker: str, scope: ScopeContext) -> bool:
        return ticker.upper() in self.get(scope)


class ScopedAlertSubscriptions:
    """Scope-isolated alert subscription registry."""

    def __init__(self) -> None:
        self._subs: Dict[str, Dict[str, Any]] = {}   # prefix:ticker → config
        self._lock = threading.Lock()

    def subscribe(
        self,
        ticker: str,
        scope: ScopeContext,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        key = f"{scope.storage_prefix()}:{ticker.upper()}"
        with self._lock:
            self._subs[key] = config or {"sensitivity": "medium"}

    def unsubscribe(self, ticker: str, scope: ScopeContext) -> None:
        key = f"{scope.storage_prefix()}:{ticker.upper()}"
        with self._lock:
            self._subs.pop(key, None)

    def get_config(self, ticker: str, scope: ScopeContext) -> Optional[Dict[str, Any]]:
        key = f"{scope.storage_prefix()}:{ticker.upper()}"
        with self._lock:
            return self._subs.get(key)

    def all_for_scope(self, scope: ScopeContext) -> Dict[str, Any]:
        prefix = scope.storage_prefix()
        with self._lock:
            return {
                k.split(":", 1)[1]: v
                for k, v in self._subs.items()
                if k.startswith(prefix + ":")
            }


# ── Default scope and registry ────────────────────────────────────────────

_ANONYMOUS_SCOPE = ScopeContext(user_id="", tenant_id="", session_id="system")

scoped_watchlist      = ScopedWatchlist()
scoped_alert_subs     = ScopedAlertSubscriptions()

_SCOPE_STORE: Dict[str, ScopeContext] = {}
_SCOPE_LOCK  = threading.Lock()


def register_scope(scope: ScopeContext) -> None:
    """Register a ScopeContext for later retrieval by session_id or user_id."""
    key = scope.session_id or scope.user_id or "anonymous"
    with _SCOPE_LOCK:
        _SCOPE_STORE[key] = scope


def get_scope(key: str = "") -> ScopeContext:
    """Retrieve a ScopeContext by session_id or user_id.

    Returns the anonymous scope when no match is found.
    """
    with _SCOPE_LOCK:
        return _SCOPE_STORE.get(key, _ANONYMOUS_SCOPE)
