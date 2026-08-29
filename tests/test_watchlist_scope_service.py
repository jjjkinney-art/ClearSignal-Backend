from types import SimpleNamespace

from app.services.watchlist_scope_service import should_use_db_watchlist


def _request(*, authenticated: bool):
    return SimpleNamespace(state=SimpleNamespace(is_authenticated=authenticated))


def test_authenticated_accounts_always_use_durable_watchlist_membership():
    assert should_use_db_watchlist(
        _request(authenticated=True),
        feature_enabled=False,
    )


def test_rollout_flag_preserves_db_backed_bypass_mode():
    assert should_use_db_watchlist(
        _request(authenticated=False),
        feature_enabled=True,
    )


def test_legacy_local_mode_remains_available_when_both_are_false():
    assert not should_use_db_watchlist(
        _request(authenticated=False),
        feature_enabled=False,
    )


def test_missing_request_state_fails_closed_to_legacy_mode():
    assert not should_use_db_watchlist(None, feature_enabled=False)
