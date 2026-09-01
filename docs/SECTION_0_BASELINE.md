# Section 0 — Backend Baseline and Regression Protection

Recorded 2026-08-31 against the deployed release. This document is a
**record of what is currently true**, not a plan. It exists so that later
9/10 roadmap sections can be judged against a known-good starting point.

No production configuration, billing configuration, delivery mode, live data,
or user record was modified to produce it.

---

## 1. Deployed release

| Property | Value |
|---|---|
| Backend URL | `https://clearsignal-backend-dlsc.onrender.com` |
| Deployed commit | `a63f151ab2c3` (= `origin/main` HEAD) |
| Schema / version tag | `7-linear-4i` |
| Environment | `production` |
| Database | enabled, 60 tables |
| Agent model | `gpt-4o-mini` |
| Route count (excl. HEAD/OPTIONS) | 104 |

Runtime configuration observed at baseline (`/health`): agent timeout 15.0s,
agent max retries 1, synthesis timeout 55.0s, synthesis max tokens 1536,
synthesis max retries 1.

## 2. Deployed-release assumptions

These held at the time of recording and are what the regression tests protect.
Each is verified rather than assumed.

1. **Authentication is enforced.** Anonymous `POST /ask` returns 401.
   `auth_enabled=true`, `bypass_mode=false`. `/auth/session` and `/auth/me`
   return 200 with null identity when unauthenticated — they are informational
   and are not an authorization boundary.
2. **The `/admin` boundary is separate from the product boundary.** Ordinary
   non-admin accounts receive 403 from `/admin/*`. The launch gate therefore
   requires two credentials and must not reuse the product token for operator
   snapshots.
3. **Billing is in the free-beta safe state.** `STRIPE_ENABLED=false`,
   `ENTITLEMENTS_ENFORCED=false`, so
   `safe_state = (not stripe_enabled) and (not entitlements_enforced)` is true.
   `billing_live_ready` is false by design in this mode.
4. **Continuous delivery is in shadow.** `loop_enabled=false`,
   `loop_shadow=true`, `effective_enabled=false`, `override_state=null`,
   `canary_pct=0`, `internal_only=true`. `duplicate_total=0`.
5. **The kill switch is two-state.** `_enabled_override` is only ever `None`
   (config governs) or `False` (force-disabled). It is never `True`;
   `/admin/loop/enable` *clears* the override and cannot start the loop while
   config says `loop_enabled=false`.
6. **Watchlist membership is account-scoped.** Any authenticated request uses
   the user-scoped database path; an authenticated database failure raises 503
   rather than falling back to the shared file-backed index, so an
   authenticated account cannot inherit shared legacy membership.
7. **Starter data is copied, not shared.** `POST /auth/import` is the only
   caller of `execute_import`, is never auto-triggered by session or
   onboarding, and copies system-owned rows (`user_id
   00000000-0000-0000-0000-000000000001`) into new per-user rows with fresh
   UUIDs. Source rows are never modified.
8. **Watchlist deletion is a soft delete.** `ticker_deactivate` sets
   `active=False`; `ticker_add` reactivates an existing inactive row in place,
   preserving `added_at`.
9. **Required CI is a single job.** `.github/workflows/ci.yml` defines one job,
   `test (py3.11, pinned)`, with eight steps. One green check therefore
   represents the entire required suite.

## 3. API contract

The public route surface is frozen in
[`tests/contracts/api_surface_v1.json`](../tests/contracts/api_surface_v1.json)
and enforced by `tests/test_api_surface_contract.py`.

### Why the import smoke reports 108 routes but the contract holds 104 entries

The two numbers count different things, and both are correct.

* `len(app.routes)` — what the CI import smoke step prints — counts **route
  objects** registered on the application: **108**.
* The contract counts distinct **`(method, path)` pairs**, excluding `HEAD`
  and `OPTIONS`: **104**.

The difference is exactly the four dedicated `HEAD`-only route objects:

```
HEAD /        HEAD /health        HEAD /healthz        HEAD /readyz
```

`108 − 4 = 104`.

These exist because Milestone 8 split `GET` and `HEAD` into separate routes to
give each a unique `operationId` (a single handler serving both emitted
duplicate ids and broke client generators). The `HEAD` variants are
deliberately kept out of the OpenAPI schema and serve uptime monitors only.

The mapping is one-to-one because **no route object exposes more than one
non-`HEAD`/`OPTIONS` method** — verified, count zero — so 104 route objects
yield exactly 104 pairs.

Excluding `HEAD` loses no coverage: all eight excluded pairs are `HEAD`, none
is any other method, and **every excluded path is still covered under `GET`**,
so no path disappears from the contract. The framework-generated documentation
routes (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`) are
**included** as `GET` entries rather than excluded — they are part of the
published surface and `test_launch_access_policy.py` already depends on
`/openapi.json`.

`OPTIONS` is excluded on the same principle: it is supplied by CORS middleware
rather than by the application, so it is not an application contract.

### Contract semantics

The contract is a **floor, not an exact match**:

* every recorded `(method, path)` must continue to exist;
* adding routes is allowed and does not fail the suite — the roadmap is
  expected to add surface area;
* removing or renaming a route fails the suite, forcing the change to be a
  deliberate, reviewed edit of the fixture in the same commit.

Endpoints referenced by name in `docs/BETA_LAUNCH_RUNBOOK.md`,
`tests/validate_beta_launch.py` and `tests/validate_production_acceptance.py`
are additionally asserted individually, so losing one fails by name rather
than as an anonymous set difference.

## 4. Baseline test results

Run on `a63f151` with Python 3.9.6 locally. CI pins Python 3.11.9; the suites
below are the ones the required job runs by name.

| CI step | Result |
|---|---|
| Import smoke test | pass — 108 routes registered |
| Collection determinism | **13,427 collected, 0 errors** |
| Launch-security & reproducibility | **76 passed** |
| Production router regression | **87 passed** |
| Auth & billing | **204 passed** |
| Validation V1/V6 (conviction engine) | **178 passed** |
| Release-closure intelligence regressions | **131 passed** |

Total across the five named suites: **676 passed, 0 failed**.

The "Full repository regression (isolated per file)" CI step spawns one
interpreter per test file across the whole tree. It was not reproduced locally
— see *Deferred*, below.

## 5. Regression coverage audit

Coverage was audited per area against the behaviour validated during the
controlled-beta launch gate.

| Area | Existing coverage | Verdict |
|---|---|---|
| Analysis | `test_comparative_ranking.py`, `test_company_detection.py`, `test_company_routing.py`, `test_question_anchored_valuation.py` | covered |
| Watchlist | `test_watchlist_db_backed.py`, `test_watchlist_scope_service.py` | covered |
| Portfolio | `test_portfolio_router.py` | covered |
| Alerts / notifications | `test_notifications_router.py` | covered |
| Billing | `test_services/test_billing_observability.py` (pins the `safe_state` formula), `test_services/test_billing_routes.py`, `test_billing_checkout_webhook.py`, `test_services/test_webhook_service.py` | covered |
| Authentication scoping | `test_auth_scoping.py`, `test_services/test_auth_middleware.py`, `test_services/test_auth_routes.py`, `test_services/test_account_import_service.py` (copy semantics, system-row preservation, distinct ids) | covered |
| Duplicate delivery | `test_services/test_loop_idempotency_service.py`, `test_services/test_loop_observability.py` | covered |

### Gaps found and closed

1. **The real `/admin/loop/disable` and `/admin/loop/enable` handlers had no
   test.** `test_services/test_loop_canary_slice9.py` covers the kill-switch
   *service* functions well, but its `ADMIN_API` section exercises a `mini`
   FastAPI app that re-implements the handlers inline. No test imported the
   handlers from `app/api.py`, so an edit to them would ship uncaught — on a
   Tier-0 safety control that the runbook's rollback procedure depends on.
   Closed by `tests/test_admin_loop_killswitch_route.py`.

2. **The public route surface was unpinned.** Nothing asserted which endpoints
   exist, so an endpoint could be removed or renamed without any test failing —
   including endpoints the launch gate itself calls. Closed by
   `tests/test_api_surface_contract.py` and the frozen fixture.

### Gaps considered and deliberately not filled

* **Watchlist fail-closed on database error** is asserted by
  `test_auth_scoping.py` / `test_watchlist_scope_service.py` at the unit level.
  It is not reproducible against production, and inducing a database failure
  there is out of scope for a baseline task.
* **Cross-account isolation in production** was exercised manually as runbook
  entry criterion 4 and passed. It is deliberately not automated here: it
  requires two live user credentials and mutates real account state, which
  belongs in the acceptance runbook rather than in CI.

## 6. Mutation checks

Both new modules were verified to fail when the behaviour they protect is
broken — a test that cannot fail protects nothing.

| Injected regression | Result |
|---|---|
| A recorded route removed from the surface | `test_no_recorded_route_has_been_removed` **failed** as intended |
| `force_enable()` changed to set `_enabled_override = True` | **5 of 7** kill-switch tests failed, including `test_enable_does_not_force_enable_when_config_disabled` |

Both mutations were reverted; the source tree is clean apart from the added
files.
