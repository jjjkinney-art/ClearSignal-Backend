# Production Acceptance Gate

Use this gate after every backend deployment and before inviting beta users.
It reflects the current production configuration: authentication is enabled,
the production database is active, and anonymous product requests must fail
closed.

## Safe acceptance run

Obtain a short-lived Supabase access token from an authenticated ClearSignal
session, then export it only in the current shell:

```bash
export CLEARSIGNAL_ACCESS_TOKEN="<short-lived access token>"
export EXPECTED_BUILD_COMMIT="<expected backend commit>"
python tests/validate_production_acceptance.py
unset CLEARSIGNAL_ACCESS_TOKEN
```

The validator never prints or writes the token. It verifies:

- production health and expected deployed commit;
- anonymous `/ask` rejection;
- authenticated session and non-system identity;
- read-only billing/entitlement state; and
- an authenticated deterministic comparison through `/ask`.

## Account-isolation gate

Required CI also runs `tests/test_auth_scoping.py` and
`tests/test_watchlist_scope_service.py`. Together they verify that:

- an empty authenticated watchlist cannot inherit shared legacy membership;
- authenticated watchlist reads and writes fail closed during a database error;
- one account cannot read or remove another account's watchlist or portfolio data;
- notification read state and delivery preferences remain user-scoped;
- an ordinary user cannot select another user's preference scope; and
- billing status rejects a missing identity and resolves only the acting user's row.

Before invited beta, repeat the critical read/write journeys in production with
two real non-admin accounts. Record only pass/fail results and opaque account
labels; never copy access tokens, customer IDs, emails, portfolio contents, or
other account data into the release record.

The default comparison route does not invoke the LLM pipeline. To exercise one
full provider-backed analysis as a deliberate release-candidate check:

```bash
python tests/validate_production_acceptance.py --include-analysis
```

Without `CLEARSIGNAL_ACCESS_TOKEN`, the public checks still run and the command
exits with status `2`, clearly marking the authenticated portion as blocked.
Status `1` means a check failed; status `0` means the requested gate passed.

`tests/validate_16_auth_shadow.py` remains a historical Phase 16 shadow-mode
validator. It must not be used as the current production launch gate because it
expects authentication to be disabled and the earlier database table count.
