"""Account-authoritative routing for watchlist membership operations."""

from __future__ import annotations


def is_authenticated_watchlist_request(request) -> bool:
    """Return whether middleware verified a real account for this request."""
    try:
        return bool(request.state.is_authenticated)
    except AttributeError:
        return False


def should_use_db_watchlist(request, *, feature_enabled: bool) -> bool:
    """Use durable membership for verified accounts or an enabled rollout.

    The legacy rollout flag remains useful for local/system-default operation,
    but an authenticated account must use the same database membership source
    as account-scoped Morning Brief generation.
    """
    return bool(feature_enabled) or is_authenticated_watchlist_request(request)
