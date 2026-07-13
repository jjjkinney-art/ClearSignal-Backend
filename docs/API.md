# ClearSignal API — Beta Reference

Backend for **ClearSignal**, an AI-powered equity analysis platform. The
conviction engine (frozen, institutionally validated) produces structured
theses, dossiers, and scenarios; this document covers the user-facing beta API
surfaces built on top of it.

Interactive docs are served by the running app at **`/docs`** (Swagger UI) and
**`/redoc`**; the machine-readable schema is at **`/openapi.json`**. This file
is the human-oriented companion.

---

## Identity & rollout

Most product surfaces are scoped to the acting user. Identity is resolved by the
auth middleware and stamped on `request.state.user_id` before every handler.

| Mode | Behavior |
|---|---|
| `AUTH_ENABLED=false` *(default)* | Every request resolves to a single system **bypass** user — the API is effectively single-tenant. No JWT is inspected. |
| `AUTH_ENABLED=true` | Identity is the verified Supabase JWT `sub`. User-scoped routes return **401** when the token is missing or invalid. |

Several capabilities are **dark-launched behind flags** and are inert until an
operator enables them via environment (never in code):

| Flag | Gates |
|---|---|
| `WATCHLIST_DB_BACKED` | Persistent, multi-instance watchlist membership (vs. local JSON index) |
| `STRIPE_ENABLED` | Billing checkout / portal / cancel (return **503** when off); webhook is a no-op |
| `DELIVERY_SHADOW`, `DELIVERY_IN_APP_ENABLED` | Real notification delivery (inbox is read-only shadow until enabled) |
| `SCENARIO_BUILD_ENABLED`, `SCENARIO_SCORING_ENABLED` | Scenario generation (read endpoints return empty until data exists) |
| `ENTITLEMENTS_ENFORCED` | Plan-based limit enforcement (no-op / failure-open when off) |

**Conventions**

- Read endpoints degrade gracefully when persistence is disabled — empty
  payloads, never `5xx`.
- No endpoint returns buy/sell/hold or price-target language. The engine
  *describes*; it does not recommend.

---

## Health & readiness — `health`

| Method | Path | Notes |
|---|---|---|
| GET | `/`, `/health`, `/healthz` | **Liveness.** Always `200` when the process is up. Returns service identity, conviction schema version, build commit, environment, and DB status. `HEAD` is supported for uptime monitors. |
| GET | `/readyz` | **Readiness.** `200 {"ready": true, "db": "connected"\|"disabled"}` when serviceable; **`503 {"ready": false, "db": "unreachable"}`** when the DB is configured but unreachable — so Render / k8s can gate traffic. |
| GET | `/version` | Conviction schema + deployment identity. |

---

## Watchlist — `watchlist`

Track tickers and their thesis-snapshot history. Scoped to the authenticated
user; DB-backed when `WATCHLIST_DB_BACKED=true`.

| Method | Path | Summary |
|---|---|---|
| GET | `/watchlist` | List watchlisted tickers |
| POST | `/watchlist/{ticker}` | Add a ticker (idempotent) |
| DELETE | `/watchlist/{ticker}` | Remove a ticker |
| GET | `/watchlist/{ticker}/snapshots` | Thesis snapshot history |
| GET | `/watchlist/{ticker}/diff` | Latest thesis diff |
| GET | `/watchlist/{ticker}/changes` · `/watchlist/changes/material` | Material change events |
| POST | `/watchlist/{ticker}/acknowledge` | Clear the material-change flag |
| GET | `/watchlist/status` · `/watchlist/themes` · `/watchlist/drift` | Aggregates |

---

## Portfolio — `portfolio`

Position CRUD plus portfolio-level intelligence, scoped to the caller's default
portfolio.

| Method | Path | Summary |
|---|---|---|
| GET | `/portfolio` | Default portfolio metadata + position counts |
| GET | `/portfolio/positions` | List active positions |
| POST | `/portfolio/positions` | Add / update a position (idempotent) |
| DELETE | `/portfolio/positions/{ticker}` | Remove a position |
| GET | `/portfolio/health` | Concentration / diversification / warnings |
| GET | `/portfolio/exposure` | Shared-risk / failure-mode clusters |
| GET | `/portfolio/insights` | Persisted portfolio insights |

**Add a position** — `POST /portfolio/positions`

```json
{ "ticker": "NVDA", "membership_class": "owned", "weight": 0.3 }
```

`membership_class` ∈ `owned` · `watchlist` · `on_radar`.

---

## Scenarios — `scenarios`

Read-only Scenario Engine — *“what changes if X happens?”*. Descriptive facets
only (transmission path, plausibility, confidence); no conviction/stance/price.

| Method | Path | Summary |
|---|---|---|
| GET | `/scenarios` | Top scenarios for the caller |
| GET | `/scenarios/{ticker}` | Scenarios for a ticker |
| GET | `/scenarios/{ticker}/facet` | Condensed facet (top plausibility/confidence, type counts) |

---

## Notifications — `notifications`

In-app inbox, unread counts, idempotent read receipts, and delivery preferences.
Read-only over the delivery ledger while delivery stays in shadow mode.

| Method | Path | Summary |
|---|---|---|
| GET | `/notifications` | Inbox items (newest first) |
| GET | `/notifications/unread` | Unread items + `{ "count": N, "items": [...] }` |
| POST | `/notifications/read` | Mark one/many read (idempotent) |
| GET | `/notifications/preferences` | Read delivery preferences |
| PATCH | `/notifications/preferences` | Update delivery preferences |

**Mark read** — `POST /notifications/read`

```json
{ "delivery_ids": ["<delivery-id>"] }   // or { "delivery_id": "<delivery-id>" }
```

---

## Auth — `auth`

Supabase JWT session endpoints. Enforced only when `AUTH_ENABLED=true`.

| Method | Path | Summary |
|---|---|---|
| GET | `/auth/me` | Current user identity |
| GET | `/auth/session` | Session state |
| POST | `/auth/logout` | Logout |

---

## Billing — `billing`

Stripe checkout, webhook, status, portal, and cancel. Mutating routes return
**503** and the webhook is a no-op until `STRIPE_ENABLED=true`. The system user
cannot check out.

| Method | Path | Summary |
|---|---|---|
| POST | `/billing/checkout` | Create a Stripe Checkout Session |
| POST | `/billing/webhook` | Stripe webhook receiver (idempotent via `stripe_events`) |
| GET | `/billing/status` | Current billing state + entitlements |
| POST | `/billing/portal` | Create a Stripe billing portal session |
| POST | `/billing/cancel` | Cancel at period end |

**Checkout** — `POST /billing/checkout`

```json
{ "plan": "pro", "interval": "month" }
```

`plan` ∈ `pro` · `teams`; `interval` ∈ `month` · `year`. Returns
`{ "checkout_url": "...", "session_id": "..." }` when enabled, else `503`.

Security invariants: `STRIPE_SECRET_KEY` / webhook secrets / raw Stripe payloads
are never logged or stored; the webhook always returns `200` after a valid
signature (errors are recorded, never retried into duplicate state).

---

## Running the test suite deterministically

A number of **legacy hermetic tests** (e.g. `test_runtime_behavior`,
`test_completion_pass`, `test_enterprise*`, `test_final_*`,
`test_operationalization`, `test_history_inversion`, `test_meaning_native`)
replace real modules — `pydantic`, the `app.*` package tree, `app.providers.*`,
`app.data_pipeline.*` — in `sys.modules` at **import** time and depend on those
stubs through their own execution. Every one of these files passes **on its own**;
the historical problem was purely a shared-process artifact.

### Collection is now order-independent (single process)

`conftest.py` installs a collection-boundary guard (`pytest_collectstart` +
`_restore_real_modules`) that snapshots the real cross-cutting modules and
restores them before **each test module is imported**. It also reverts the
specific in-place attribute mutations some stubs perform (e.g.
`pydantic.BaseModel`). As a result the whole suite now **collects cleanly in a
single process** — which previously failed outright:

```bash
python3 -m pytest tests/ --collect-only     # 12,264 items, 0 collection errors
```

### Run determinism → one process per file

A handful of the hermetic files above share **import-time module state across
the tests within the file**, and that state is what a *neighbouring* file's stubs
disturb at run time. The only fully robust isolation is **a separate interpreter
per test file** — each file re-imports from a pristine `sys.modules`:

```bash
# Deterministic: every file runs in its own process.
find tests -name 'test_*.py' -print0 | xargs -0 -n1 python3 -m pytest -q
```

> **Do not rely on `pytest --forked` for this suite.** `pytest-forked` forks
> *per test* from a single shared parent collection, so import-time module
> replacements accumulated across files during collection still leak into the
> forked children. It does not make these legacy files order-independent — one
> process per **file** does.

**Per-area CI (recommended):** gate each area in its own invocation — they are
each deterministic on their own:

```bash
python3 -m pytest tests/test_services -q      # user-facing router + service suites
python3 -m pytest tests/benchmark -q          # engine benchmarks
# ...one invocation per top-level area / file group
```

> The remaining root-cause cleanup is to convert these files' module-level
> `sys.modules` stubbing into per-test fixtures. Doing so naively (installing a
> bare fake module) drops the *real* attributes downstream imports still need, so
> it must copy real attributes into the fake — a larger, carefully-verified
> refactor tracked separately. The collection guard above closes the
> single-process **collection** gap today; per-file invocation closes the **run**
> gap.
