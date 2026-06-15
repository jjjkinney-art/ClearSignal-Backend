# Phase 17 — Stripe & Subscriptions Implementation Plan

**Status:** Build-ready execution plan  
**Source of truth:** `PHASE_17_STRIPE_AND_SUBSCRIPTIONS_SPEC.md` (approved — not re-opened here)  
**Build invariant:** `STRIPE_ENABLED=false` and `AUTH_ENABLED=false` throughout every slice  
**Migration target:** `010_subscriptions_billing.sql`  
**Table count:** 35 → 38

This document converts the approved architecture into an ordered, safe, individually-deployable slice plan. It introduces no new architectural decisions. Where the spec left an open question (§12), the slice that must resolve it is named — the question is carried forward, not answered here.

---

## 0. Execution Principles

1. **Every slice ships with `STRIPE_ENABLED=false`.** No slice changes runtime behavior for real users until the final activation step. Billing routes return safe stub data when the flag is off.
2. **Each slice is independently deployable and independently revertible.** A slice never leaves the tree in a state where the prior slice's behavior regresses.
3. **The system user is exempt at every enforcement point.** `SYSTEM_DEFAULT_USER_ID` short-circuits to unlimited before any limit query runs.
4. **No raw Stripe payloads are persisted.** `stripe_events` stores the event id, type, and processing status only.
5. **Webhooks are the only writer of billing state.** No HTTP route mutates `subscriptions.plan_name`/`status` directly.
6. **Fail-open to `free`.** Any entitlement-resolution failure resolves the user to the free tier — never to a paid tier, never to a hard block.
7. **Slices land behind tests first.** Validation criteria below are the acceptance gate for each slice's PR.

---

## 1. Slice Plan

Seven slices, in dependency order. Slices 17.1–17.2 carry zero Stripe dependency and are safe to land first. Stripe SDK is introduced in 17.3.

---

### Slice 17.1 — Schema + Migration

**Objective:** Land all Phase 17 tables and columns. No behavior change. The system can read/write the new tables but nothing populates them yet.

**Files**
- `app/db/migrations/010_subscriptions_billing.sql` (new)
- `app/db/models.py` (add `Subscription`, `StripeEvent`, `EntitlementCache` ORM models; add `plan`, `plan_updated_at` columns to `User`)
- `app/db/startup.py` (or existing idempotent migration runner) — register migration 010 to apply at startup
- `tests/test_db/test_migration_010.py` (new)

**Dependencies:** None. Builds on Phase 16 schema (`users`, `audit_log`).

**Validation**
- Migration applies idempotently on a fresh SQLite in-memory DB and on a DB already at migration 009 (re-run is a no-op).
- `db_table_count == 38` after apply.
- All five objects present: `subscriptions`, `stripe_events`, `entitlement_cache` tables; `users.plan`, `users.plan_updated_at` columns.
- `users.plan` defaults to `'free'` on existing rows; system user row reads `plan='system'` (set in migration).
- No `payload_json` / raw-payload column exists on `stripe_events` (assert by column inspection).
- All existing Phase 16 tests still pass unchanged.

**Rollback strategy:** Migration is additive only (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`). Revert = drop the three new tables and two columns via a manual down-migration; no existing data is touched. Because nothing reads these tables until 17.2, reverting the code commit alone fully neutralizes the slice.

---

### Slice 17.2 — Entitlement Service (no Stripe)

**Objective:** Implement `EntitlementSet`, plan-limit tables, resolution chain, cache, and the `check_*` guards — entirely from local DB state. With no `subscriptions` rows present, every user resolves to `free`. This slice is fully testable without any Stripe contact.

**Files**
- `app/services/entitlement_service.py` (new) — `get_entitlements`, `check_watchlist_limit`, `check_portfolio_limit`, `check_position_limit`, `check_dossier_limit`, `require_feature`, `invalidate_entitlement_cache`, `warm_entitlement_cache`, `get_plan_limits`
- `app/services/entitlement_errors.py` (new) — `EntitlementError` domain exception (resource, limit, current, plan, upgrade_required)
- `app/entitlements/plan_limits.py` (new) — static per-tier limit tables (Spark/Signal/Syndicate/Edge) sourced verbatim from spec §3.1
- `tests/test_services/test_entitlement_service.py` (new)

**Dependencies:** 17.1 (reads `subscriptions`, `entitlement_cache`, `users.plan`).

**Validation**
- With no subscription row → `get_entitlements` returns the Spark/free `EntitlementSet`.
- System user → unlimited set; every `check_*` is a no-op (short-circuit verified before any DB query).
- Free limits enforced exactly: 6th ticker raises `EntitlementError`; 2nd portfolio raises; 11th position raises; 4th dossier in-month raises (count via `audit_log action='dossier_generate'`).
- Cache write/read round-trip: second call within TTL hits `entitlement_cache`, does not re-query `subscriptions` (assert via spy/mock).
- Cache miss and `subscriptions` failure both fall open to `free` without raising.
- `EntitlementError` carries the fields the route layer needs for HTTP 402 (resource, limit, current, plan).

**Rollback strategy:** Service is unreferenced by any route in this slice (guards are wired in 17.6). Revert = remove the three new modules; 17.1 schema remains harmless. No production path calls this code until 17.6, so reverting is zero-impact.

---

### Slice 17.3 — Stripe Service + Checkout

**Objective:** Introduce the Stripe SDK and the outbound-call wrapper. Implement customer creation and checkout-session creation. `POST /billing/checkout` works in Stripe **test mode** only; guarded by `STRIPE_ENABLED`.

**Files**
- `app/services/stripe_service.py` (new) — `get_or_create_customer`, `create_checkout_session`, `create_portal_session`, `retrieve_subscription`, `cancel_subscription_at_period_end`; wraps SDK errors as `StripeServiceError`
- `app/services/stripe_errors.py` (new) — `StripeServiceError`
- `app/routers/billing.py` (new, partial) — `POST /billing/checkout` only this slice
- `app/config.py` (add `stripe_enabled`, `stripe_secret_key`, `stripe_publishable_key`, `stripe_webhook_secret`, `stripe_price_*` settings — all default empty / `False`)
- `app/api.py` (register billing router behind a guard)
- `requirements.txt` (add `stripe` SDK, pinned)
- `tests/test_services/test_stripe_service.py` (new — SDK fully mocked)

**Dependencies:** 17.1 (writes `users.stripe_customer_id`), 17.2 (none direct, but checkout reads current plan).

**Validation**
- `STRIPE_ENABLED=false` → `POST /billing/checkout` returns a safe stub (`{"checkout_url": null, "stripe_disabled": true}`), makes **zero** outbound calls (assert SDK not invoked).
- `STRIPE_ENABLED=true` + mocked SDK → `get_or_create_customer` creates a customer only when `stripe_customer_id` is null; reuses otherwise; persists `cus_*` to `users`.
- Checkout session built with `trial_period_days=14`, correct price id, success/cancel URLs from config.
- `STRIPE_SECRET_KEY` never appears in any log line (assert via log capture).
- SDK exceptions surface as `StripeServiceError` → route returns HTTP 502, not 500.
- **Carries open question:** trial card requirement (spec §12) must be settled here — plan assumes no-card 14-day trial per approved §2.4.

**Rollback strategy:** All Stripe behavior is gated by `stripe_enabled=False` (default). Reverting the code commit removes the router and service. The `stripe` dependency in `requirements.txt` is inert if unused. No customer is created while the flag is off, so there is no Stripe-side state to unwind.

---

### Slice 17.4 — Webhook Handler

**Objective:** Implement `POST /webhooks/stripe` with signature verification, `stripe_events` idempotency, and all handled event types. This slice makes the `subscriptions` table come alive — but only in response to (test-mode) Stripe events.

**Files**
- `app/routers/webhooks.py` (new) — `POST /webhooks/stripe`; raw-body signature verify; idempotency gate; always-200-after-verify
- `app/services/webhook_handler.py` (new) — `handle_stripe_event` + per-event handlers (`_handle_checkout_completed`, `_handle_subscription_created/updated/deleted`, `_handle_invoice_paid`, `_handle_invoice_payment_failed`, `_handle_trial_will_end`)
- `app/services/subscription_service.py` (new) — `activate_subscription`, `update_subscription`, `mark_past_due`, `mark_canceled`, `mark_payment_recovered`, `get_active_subscription`; each updates `subscriptions` + `users.plan` + invalidates entitlement cache + writes `audit_log`
- `app/api.py` (register webhooks router)
- `tests/test_services/test_webhook_handler.py`, `tests/test_services/test_subscription_service.py`, `tests/test_routers/test_webhooks.py` (new)

**Dependencies:** 17.1 (writes `subscriptions`, `stripe_events`), 17.2 (calls `invalidate_entitlement_cache`), 17.3 (`stripe_service` for retrieval/signature secret).

**Validation**
- Bad/missing `Stripe-Signature` → HTTP 400 **before** any payload read; nothing written to `stripe_events`.
- Valid signature, new event → row inserted in `stripe_events`, handler runs, status set `ok`.
- **Idempotency:** replaying the same `stripe_event_id` → returns 200 immediately, handler does **not** run twice (assert side effect applied once).
- `checkout.session.completed` → creates `subscriptions` row, sets `users.plan='pro'`, status `trialing`, invalidates cache.
- `invoice.payment_failed` → status `past_due`, `grace_period_ends_at = now + 3 days`.
- `invoice.paid` after lapse → status `active`, grace cleared, plan restored.
- `customer.subscription.deleted` → status `canceled`, `users.plan='free'`, audit row written.
- Handler exception → `stripe_events.processing_status='error'`, response still 200 (never 5xx — no Stripe re-delivery storm).
- No raw payload persisted anywhere.

**Rollback strategy:** Webhook route is reachable only if the Stripe dashboard has the endpoint registered; in shadow that endpoint points at test mode only. Revert = remove routers/services; `subscriptions` rows created during testing are isolated to test/staging DB. Production `STRIPE_ENABLED=false` means no live events arrive. The `force_disable`-style guard pattern from Phase 16 is mirrored: the webhook handler checks `stripe_enabled` and no-ops (logs + 200) when off.

---

### Slice 17.5 — Billing Routes (status, portal, cancel)

**Objective:** Complete the customer-facing billing surface: `GET /billing/status`, `POST /billing/portal`, `POST /billing/cancel`. All read-only or delegated-to-Stripe-portal; no direct plan mutation.

**Files**
- `app/routers/billing.py` (extend with `/status`, `/portal`, `/cancel`)
- `app/services/subscription_service.py` (add read helpers for status assembly if not already present)
- `tests/test_routers/test_billing.py` (new)

**Dependencies:** 17.2 (entitlement/plan read), 17.3 (`create_portal_session`), 17.4 (subscription state).

**Validation**
- `GET /billing/status` returns `{plan, status, trial_days_remaining, current_period_end, show_upgrade_cta}` from local state; `STRIPE_ENABLED=false` → returns free/stub.
- `POST /billing/portal` requires existing `stripe_customer_id`; returns Stripe portal URL (mocked); 404/clear error if no customer.
- `POST /billing/cancel` delegates to portal/`cancel_at_period_end`; never deletes a `subscriptions` row; access retained until `current_period_end`.
- Annual→monthly / monthly→annual proration is **portal-mediated** (no backend proration logic) — confirms open question (spec §12) resolved as "portal default."

**Rollback strategy:** Routes are additive and read-mostly. Revert removes the three endpoints; `/billing/checkout` from 17.3 is unaffected. No state mutation to unwind.

---

### Slice 17.6 — Entitlement Enforcement Wiring

**Objective:** Wire the 17.2 `check_*` guards into the live service layer. This is the first slice that changes behavior for real requests — but because all users resolve to `free` (no subscriptions) and the system user is exempt, the **only** observable change is free-tier limit enforcement, which matches the intended product behavior.

**Files**
- `app/services/watchlist_service.py` (call `check_watchlist_limit` in add path)
- portfolio service (call `check_portfolio_limit` / `check_position_limit`)
- dossier service (call `check_dossier_limit`)
- portfolio intelligence service (call `require_feature("portfolio_intelligence")`)
- delivery service (gate email/push channels on entitlement)
- briefing scheduler (read `briefing_cadence` per entitlement)
- route layer: central `EntitlementError → HTTP 402` handler (FastAPI exception handler)
- `tests/test_services/test_entitlement_enforcement.py` (new, integration-level)

**Dependencies:** 17.2 (guards), 17.4 (so paid users who exist via webhook resolve above free).

**Validation**
- System user / bypass mode → all guards no-op; existing flows byte-identical to pre-17.6 (this is the critical regression check).
- Free user hitting a limit → HTTP 402 with `{error, resource, limit, current, plan, upgrade_url}`.
- A user with an `active`/`trialing` subscription row → guards pass at the paid limit.
- Email delivery silently suppressed (not errored) for free users; in-app unaffected.
- All Phase 16 ownership/import/onboarding tests still pass.

**Rollback strategy:** Highest-risk slice. Guard each enforcement call so it can be globally short-circuited by a single flag (e.g. `ENTITLEMENTS_ENFORCED`, default `false` on first deploy → flip to `true` after a soak). Revert path: flip the flag off → all guards become no-ops, restoring pre-17.6 behavior without a redeploy (mirrors Phase 16 `AUTH_ENABLED` kill pattern). Code revert removes the guard calls entirely.

---

### Slice 17.7 — Observability + Shadow Validation

**Objective:** Ship the billing observability endpoint, the standalone validation script, and the rollout doc. Run the shadow soak. No enforcement change.

**Files**
- `app/routers/admin_billing.py` (new) — `GET /admin/stripe-status` (last event ts, 24h error count, subscription counts by status, cache hit rate, `stripe_enabled`, `entitlements_enforced` flags — **boolean flags only, never secret values**, mirroring Phase 16 snapshot policy)
- `app/services/billing_observability_service.py` (new) — snapshot builder, degrades safely on DB failure
- `tests/validate_17_stripe_shadow.py` (new, standalone — `sys.exit(main())`)
- `docs/PHASE_17_STRIPE_SHADOW_ROLLOUT.md` (new)
- `tests/test_services/test_billing_observability_service.py`, `tests/test_routers/test_admin_billing.py` (new)

**Dependencies:** 17.1–17.6.

**Validation**
- `GET /admin/stripe-status` returns snapshot; never exposes `stripe_secret_key`, `stripe_webhook_secret`, or price ids' secret portions — boolean presence flags only.
- DB-failure path → degraded snapshot with `db_available=false`, no exception.
- `validate_17_stripe_shadow.py` checks: `db_table_count==38`, `stripe_enabled==false`, `entitlements_enforced` state, idempotency table present, no raw-payload column, system-user exemption holds, free fallback resolves — all PASS.
- Mirrors the Phase 16 `validate_16_auth_shadow.py` static+async structure.

**Rollback strategy:** Observability-only; read-only endpoints and a script. Revert is zero-impact on billing behavior.

---

## 2. Schema Plan (Migration 010)

**File:** `app/db/migrations/010_subscriptions_billing.sql` — applied idempotently at startup, additive only, no DROP, no destructive ALTER.

### 2.1 `users` — additive columns
- `plan VARCHAR(20) NOT NULL DEFAULT 'free'` — denormalised cache of active subscription's `plan_name`; never authoritative.
- `plan_updated_at TIMESTAMPTZ DEFAULT NULL`
- Migration sets system user row to `plan='system'`.

### 2.2 `subscriptions`
Columns per spec §5.2: `id` (PK), `user_id`, `org_id` (nullable, Teams), `stripe_subscription_id` (UNIQUE), `stripe_customer_id`, `stripe_price_id`, `plan_name`, `billing_interval`, `status`, `trial_ends_at`, `current_period_start`, `current_period_end`, `cancel_at_period_end`, `canceled_at`, `grace_period_ends_at`, `seat_count`, `created_at`, `updated_at`.

**Invariant (application-enforced, not DB):** at most one row per user with `status IN ('active','trialing','past_due','paused')`. Historical rows retained.

### 2.3 `stripe_events`
Columns per spec §5.3: `id` (PK), `stripe_event_id` (UNIQUE — dedup key), `event_type`, `processing_status`, `error_detail`, `processed_at`, `created_at`.  
**No `payload_json` column** — PII-retention avoidance; events retrievable from Stripe by id.

### 2.4 `entitlement_cache`
Columns per spec §5.4: `user_id` (PK), `plan_name`, `plan_status`, `watchlist_limit`, `portfolio_limit`, `position_limit`, `dossier_monthly_limit`, `features_json`, `trial_days_remaining`, `computed_at`, `expires_at`.

### 2.5 Indexes
- `ix_subscriptions_user_id` ON `subscriptions(user_id)`
- `ix_subscriptions_status` ON `subscriptions(status)`
- `ix_stripe_events_type` ON `stripe_events(event_type)`
- `stripe_events.stripe_event_id` UNIQUE (idempotency)
- `subscriptions.stripe_subscription_id` UNIQUE
- `entitlement_cache.user_id` PK (one row per user)

### 2.6 Migration safety
All statements `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE … ADD COLUMN IF NOT EXISTS`. Re-runnable. No existing column modified or dropped. Validated by `tests/test_db/test_migration_010.py` against both a fresh DB and a DB at migration 009.

---

## 3. Stripe Integration Plan

| Concern | Plan | Slice |
|---|---|---|
| **Customer creation** | `get_or_create_customer(user_id, email)` — creates `cus_*` only when `users.stripe_customer_id` is null; metadata carries `user_id`; persists id back. | 17.3 |
| **Checkout sessions** | `create_checkout_session` in `mode='subscription'`, `trial_period_days=14`, `allow_promotion_codes`, success/cancel URLs from config. Stripe-hosted; no local card handling. | 17.3 |
| **Billing portal** | `create_portal_session(customer_id, return_url)` → portal URL. All upgrade/downgrade/cancel/payment-method/invoice self-service is portal-mediated. No custom billing UI. | 17.5 |
| **Webhook verification** | Raw-body `stripe.Webhook.construct_event` with `STRIPE_WEBHOOK_SECRET` **before** any payload access. Bad signature → 400, no logging of payload. | 17.4 |
| **Event handling** | `handle_stripe_event` routes by type to per-event handlers; ignores `payment_intent.*`, `charge.*`, `product.*`, `price.*`, `radar.*` per spec §4.4.3. | 17.4 |
| **Subscription state sync** | `subscription_service` is the only writer of `subscriptions`/`users.plan`; every transition also invalidates entitlement cache and writes `audit_log`. HTTP routes never mutate plan state. | 17.4 |
| **Idempotency** | `stripe_events.stripe_event_id` UNIQUE; handler checks-then-inserts; replay returns 200 without re-running side effects. | 17.4 |

---

## 4. Entitlement Plan

| Concern | Plan | Slice |
|---|---|---|
| **EntitlementSet** | Dataclass per spec §3.3; assembled by `get_entitlements`. Carries limits (`-1` = unlimited) + boolean feature flags + trial/CTA fields. | 17.2 |
| **Tier limits** | Static tables in `app/entitlements/plan_limits.py`, verbatim from spec §3.1 (Spark/Signal/Syndicate/Edge). | 17.2 |
| **Free fallback** | No subscription row, cache miss, or DB error → resolve to `free`. Fail-open is the safe mode (never grants paid, never hard-blocks). | 17.2 |
| **System user bypass** | `if user_id == SYSTEM_DEFAULT_USER_ID: return _system_entitlements()` — checked before any DB query, in every `check_*`. Preserves Phase 16 bypass invariant. | 17.2 |
| **Enforcement points** | Service-layer guards (not middleware): watchlist add, portfolio create, position add, dossier generate, portfolio-intelligence run, delivery channel dispatch, briefing schedule, data export. | 17.6 |
| **Breach response** | `EntitlementError` → central FastAPI handler → HTTP 402 with `{error, resource, limit, current, plan, upgrade_url}`. | 17.6 |
| **Cache** | `entitlement_cache` table, 1h TTL; invalidated on every subscription lifecycle event; `force_refresh` bypass for billing-status freshness. Redis-swappable behind same interface. | 17.2 |

---

## 5. Failure Handling

| Failure | Handling | Slice |
|---|---|---|
| **Failed payment** | `invoice.payment_failed` → `mark_past_due` → status `past_due`, `grace_period_ends_at = now + 3 days`. Entitlements still resolve to paid plan during grace. | 17.4 |
| **Grace period** | 3 calendar days of full access (annual-subscriber extension to 7 days is the open question for 17.4, spec §12). On expiry → status `lapsed` → entitlements resolve `free`. | 17.4 |
| **Expired / canceled subscription** | `customer.subscription.deleted` → status `canceled`, `users.plan='free'`, cache invalidated, audit logged. Access retained until `current_period_end` for `cancel_at_period_end`. | 17.4 |
| **Webhook replay** | `stripe_events.stripe_event_id` UNIQUE dedup → replayed event returns 200, side effect not re-applied. | 17.4 |
| **Webhook handler error** | `processing_status='error'`, response still 200 (no 5xx → no Stripe retry storm). Ops alert on any `error` row. Manual re-trigger by retrieving event from Stripe. | 17.4 / 17.7 |
| **Stripe outage (outbound)** | SDK errors caught → `StripeServiceError` → HTTP 502 (not 500). Checkout/portal fail gracefully; existing entitlements (from local `subscriptions`) unaffected — billing state is local-first, Stripe is consulted only for mutations. | 17.3 |
| **Entitlement resolution failure** | Cache + `subscriptions` both unreachable → fail-open to `free`. Logged, non-blocking, cache rebuilt async. | 17.2 |

---

## 6. Validation Plan

| Layer | Coverage | Slice |
|---|---|---|
| **Migration tests** | Idempotent apply, `db_table_count==38`, columns/tables present, no raw-payload column, system-user `plan='system'`. | 17.1 |
| **Unit tests — entitlement** | Free limits (ticker/portfolio/position/dossier), system-user exemption, free fallback, cache round-trip, fail-open on DB error. | 17.2 |
| **Unit tests — Stripe service** | SDK fully mocked: customer create/reuse, checkout build, secret-never-logged, `StripeServiceError` mapping, `STRIPE_ENABLED=false` no-op. | 17.3 |
| **Webhook tests** | Signature verify (good/bad), 400-before-payload, handler dispatch per event type, state transitions, `error`-status-still-200. | 17.4 |
| **Idempotency tests** | Replay same `stripe_event_id` → single side effect; concurrent-delivery safety. | 17.4 |
| **Billing route tests** | `/status`, `/portal`, `/cancel` behavior; stub under `STRIPE_ENABLED=false`; portal-mediated downgrade. | 17.5 |
| **Entitlement enforcement (integration)** | 402 on free breach, paid user passes, system user/bypass byte-identical, Phase 16 regression suite green. | 17.6 |
| **Production shadow validation** | `tests/validate_17_stripe_shadow.py` — standalone, in-memory SQLite, all-PASS gate: table count, flags off, idempotency table, no raw payload, system exemption, free fallback. | 17.7 |
| **Observability tests** | `/admin/stripe-status` snapshot, no-secret-exposure, DB-failure degradation. | 17.7 |

---

## 7. Rollout Plan

Mirrors the Phase 16 shadow-then-activate pattern. `STRIPE_ENABLED=false` and `ENTITLEMENTS_ENFORCED=false` are the safe defaults carried through all build slices.

| Stage | State | Gate to advance |
|---|---|---|
| **1. Shadow build** | All 7 slices deployed. `STRIPE_ENABLED=false`, `ENTITLEMENTS_ENFORCED=false`. Billing routes stub; no Stripe contact; no enforcement. | All slice validations PASS; `validate_17_stripe_shadow.py` all-PASS; Phase 16 suite green. |
| **2. Enforcement soak** | Flip `ENTITLEMENTS_ENFORCED=true` (Stripe still off). Free limits now enforced; all users free; system user exempt. Observe 402 rates, no regression. | 7-day soak, zero ownership/import regressions, 402s only on genuine free breaches. |
| **3. Stripe test mode** | `STRIPE_ENABLED=true` with **test** keys + test webhook endpoint. End-to-end test-mode checkout → webhook → `subscriptions` row → entitlement upgrade. | Full test-mode lifecycle verified: checkout, trial, payment-fail/grace, recover, cancel, replay. `/admin/stripe-status` healthy. |
| **4. Internal checkout** | Test keys, internal/allowlisted users only run real checkout flows against Stripe test mode. | No webhook `error` rows; idempotency holds under real Stripe delivery; entitlement transitions correct. |
| **5. Live key promotion** | Swap test → **live** Stripe keys + live webhook secret (secrets manager, never env file). Requires sign-off on webhook validation, refund policy, ToS. | Approver sign-off (spec §12 open item); smoke-test live `/admin/stripe-status`. |
| **6. Private beta** | Live billing for a small invited cohort. Free tier unchanged for everyone else. Monitor dunning, grace, conversion. | 14-day beta, payment-failure/grace paths exercised in production, no billing-state drift. → general availability. |

**Kill path at every stage:** `STRIPE_ENABLED=false` reverts to stub billing with no Stripe contact; `ENTITLEMENTS_ENFORCED=false` reverts all guards to no-ops without redeploy. Both mirror the Phase 16 `AUTH_ENABLED` instant-rollback guarantee.

---

## 8. Open Questions Carried Into Build

Resolved at the named slice, not in this plan (from spec §12):

| Question | Resolve at |
|---|---|
| Trial card requirement (assume no-card 14-day) | 17.3 |
| Grace period length for annual subscribers (3 vs 7 days) | 17.4 |
| Dossier limit reset (calendar month vs rolling 30d) | 17.6 |
| Imported portfolio counts toward free limit (assume yes) | 17.6 |
| Free watchlist limit (5 vs 10 — plan assumes 5) | 17.2 |
| Teams MVP scope (schema only in 17, UI in 18) | 17.1 |
| Live-key promotion approver / ToS sign-off | Stage 5 (post-17.7) |

---

## 9. Dependency Graph

```
17.1 Schema ─┬─> 17.2 Entitlement ──────────────┬─> 17.6 Enforcement ─> 17.7 Observability
             │                                   │
             └─> 17.3 Stripe+Checkout ─> 17.4 Webhooks ─> 17.5 Billing Routes ┘
```

17.1 and 17.2 are the safe foundation (no Stripe). 17.3 introduces the SDK. 17.4 is the integration keystone. 17.6 is the only behavior-changing slice and is flag-guarded. 17.7 closes with observability and the shadow-validation gate.
