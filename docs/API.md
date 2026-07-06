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

Several **legacy hermetic tests** (e.g. `test_runtime_behavior`,
`test_completion_pass`, `test_enterprise`, `test_general_fallback`, and others)
replace real modules — `pydantic`, `app.config`, `app.providers.*`,
`app.data_pipeline.*` — in `sys.modules` at *import* time and rely on those stubs
through their own execution. When they are collected in the **same process**
before a file that imports the real app (any router / FastAPI-building test),
that file's collection fails. Every file passes **individually**; this is purely
a shared-process collection-order artifact, not a runtime defect.

**Recommended — process isolation (fully deterministic):**

```bash
pip install pytest-forked          # already in requirements.txt
python3 -m pytest tests/ --forked  # each test file runs in its own process
```

`--forked` gives each file a fresh interpreter, so the `sys.modules` stubs never
leak across files.

**No-dependency partial fallback:** run the self-contained service suites on
their own (this group collects cleanly), then the remainder:

```bash
python3 -m pytest tests/test_services -q          # clean on its own
python3 -m pytest tests -q --ignore=tests/test_services
```

The second command still mixes the hermetic files with app-building files in one
process, so prefer `--forked` when full determinism is required. Individual
suites — `tests/benchmark`, each router test, each service test — are always
deterministic on their own and are what CI should gate on per-area.

> The proper long-term fix is to convert the hermetic files' module-level
> `sys.modules` stubbing into per-test fixtures (setup/teardown). That is a
> larger test refactor tracked separately; `--forked` closes the gap today.
