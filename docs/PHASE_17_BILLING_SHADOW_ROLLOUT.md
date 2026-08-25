# Phase 17 Billing Shadow Rollout

This document covers the safe rollout sequence for Phase 17 billing infrastructure.
All env vars default to off. Each step is independently reversible.

---

## Environment Variables

### Core safety gates (both False throughout shadow phase)

| Variable | Default | Description |
|---|---|---|
| `STRIPE_ENABLED` | `false` | Master Stripe gate. When false, no outbound Stripe calls are made. |
| `ENTITLEMENTS_ENFORCED` | `false` | Master enforcement gate. When false, no user is ever blocked. |

### Stripe configuration (only needed when STRIPE_ENABLED=true)

| Variable | Default | Description |
|---|---|---|
| `STRIPE_SECRET_KEY` | `""` | Stripe secret key (`sk_live_...` or `sk_test_...`). Never commit. |
| `STRIPE_WEBHOOK_SECRET` | `""` | Stripe webhook signing secret (`whsec_...`). Never commit. |
| `STRIPE_PRICE_SIGNAL_MONTHLY` | `""` | Price ID for Signal (pro) monthly plan. |
| `STRIPE_PRICE_SIGNAL_YEARLY` | `""` | Price ID for Signal (pro) annual plan. |
| `STRIPE_PRICE_SYNDICATE_MONTHLY` | `""` | Price ID for Syndicate (teams) monthly plan. |
| `STRIPE_SUCCESS_URL` | `""` | Checkout success redirect URL. |
| `STRIPE_CANCEL_URL` | `""` | Checkout cancel redirect URL. |
| `STRIPE_PORTAL_RETURN_URL` | `""` | Billing portal return URL. |

---

## Safe Defaults (Shadow Phase)

The system is fully inert when:

```
STRIPE_ENABLED=false
ENTITLEMENTS_ENFORCED=false
```

In this state:
- No outbound Stripe API calls are ever made.
- No user is blocked by a plan limit or feature gate.
- All `/billing/*` routes are registered but return safe disabled responses.
- `GET /admin/billing-status` returns `safe_state=true`.

---

## Validation

Run the shadow validation script at any time to confirm safe state:

```bash
python tests/validate_17_billing_shadow.py
```

Expected output: `All checks passed. Billing shadow mode is correctly configured.`

The script checks:
- DB table count = 38 (includes billing tables)
- All 5 billing routes registered (`/billing/checkout`, `/billing/webhook`, `/billing/status`, `/billing/portal`, `/billing/cancel`)
- All billing services importable
- `STRIPE_ENABLED=false`
- `ENTITLEMENTS_ENFORCED=false`
- `safe_state=true`
- No Stripe SDK imported at module load
- No plan gating active

---

## Test-Mode Rollout (Stripe test keys)

Use this sequence to validate the billing flow end-to-end with Stripe test mode.
**Do not flip ENTITLEMENTS_ENFORCED=true during this phase.**

### Step 1 — Configure Stripe test credentials

In Render (or `.env` locally):

```
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...    # from the Stripe Dashboard webhook endpoint
STRIPE_PRICE_SIGNAL_MONTHLY=price_test_...
STRIPE_PRICE_SIGNAL_YEARLY=price_test_...
STRIPE_PRICE_SYNDICATE_MONTHLY=price_test_...
STRIPE_SUCCESS_URL=https://ai-intelligence-interface.vercel.app/billing/success
STRIPE_CANCEL_URL=https://ai-intelligence-interface.vercel.app/billing/cancel
STRIPE_PORTAL_RETURN_URL=https://ai-intelligence-interface.vercel.app/billing
```

Create the Stripe Dashboard webhook endpoint at:

```
https://clearsignal-backend-dlsc.onrender.com/billing/webhook
```

Subscribe it to these events:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_succeeded`
- `invoice.payment_failed`
- `customer.subscription.trial_will_end`

Before changing `STRIPE_ENABLED`, call `GET /admin/billing-status` and confirm
`stripe_config_ready=true`. This field reports only whether every required
value is present; it never exposes keys, webhook secrets, or price IDs.

### Step 2 — Enable Stripe (test mode)

```
STRIPE_ENABLED=true
```

Deploy. Validate with `GET /admin/billing-status`:
- `stripe_enabled: true`
- `stripe_config_ready: true`
- `safe_state: false` (expected — Stripe is now active)
- `entitlements_enforced: false` (still off — no users blocked)

### Step 3 — Validate checkout flow

Use a Stripe test card (`4242 4242 4242 4242`) through `POST /billing/checkout`.
Confirm subscription row appears via `GET /billing/status`.
Confirm webhook events via `GET /admin/billing-status` (`stripe_event_count > 0`).

### Step 4 — Rollback (if needed)

```
STRIPE_ENABLED=false
```

Deploy. Stripe calls stop immediately. All routes return disabled responses.
Existing DB rows (subscriptions, stripe_events) are preserved — no data loss.

---

## Live-Key Rollout

Only proceed after test-mode validation is complete.

### Step 1 — Replace test credentials with live credentials

```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...    # from Stripe dashboard webhook endpoint
STRIPE_PRICE_SIGNAL_MONTHLY=price_live_...
# etc.
```

### Step 2 — Enable Stripe

```
STRIPE_ENABLED=true
```

Deploy. Validate `GET /admin/billing-status`.

### Step 3 — Validate first live checkout

Use a real card in test mode, then remove the test charge via Stripe dashboard.
Confirm subscription + webhook event appear in the DB.

---

## Entitlement Activation Process

**Only activate entitlements after Stripe live-key rollout is stable and subscriptions are being correctly created.**

Entitlement activation is deliberately separate from Stripe activation to allow
independent validation of each subsystem.

### Prerequisites

Before activating entitlements:
- [ ] `STRIPE_ENABLED=true` and working in production
- [ ] At least one real subscription row created via webhook
- [ ] `GET /billing/status` correctly reflects user plan
- [ ] `GET /admin/billing-status` shows `subscription_count > 0`
- [ ] No Stripe webhook errors (`stripe_events.error_count = 0`)

### Activation sequence

1. Notify team — plan gate will begin blocking free users at their limits.
2. Set `ENTITLEMENTS_ENFORCED=true` in Render.
3. Deploy.
4. Validate: hit `POST /watchlist/{ticker}` as a free user at their limit → expect HTTP 402.
5. Validate: hit `GET /billing/status` → `entitlements_enforced: true`.
6. Monitor error logs for unexpected 402 responses (should be 0 for paying users).

### Rollback

```
ENTITLEMENTS_ENFORCED=false
```

Deploy. No users are blocked. Existing subscriptions are unaffected.

---

## Billing Route Reference

| Route | Method | Auth | Description |
|---|---|---|---|
| `/billing/checkout` | POST | User | Create a Stripe Checkout Session |
| `/billing/webhook` | POST | Stripe signature | Receive Stripe webhook events |
| `/billing/status` | GET | User | Current plan + entitlements |
| `/billing/portal` | POST | User | Create Stripe billing portal session |
| `/billing/cancel` | POST | User | Cancel subscription at period end |
| `/admin/billing-status` | GET | Admin | Observability snapshot |

---

## DB Tables (Phase 17 · Slice 1)

| Table | Purpose |
|---|---|
| `subscriptions` | One row per Stripe subscription; synced by webhook handlers |
| `stripe_events` | Idempotency log for all received webhook events |
| `entitlement_cache` | TTL-keyed cache of resolved entitlements (1 hr TTL) |

Users table extended with:
- `stripe_customer_id` — Stripe Customer ID (set on first checkout)
- `plan` — denormalised plan name for fast reads
- `plan_updated_at` — timestamp of last plan change

---

## Observability

`GET /admin/billing-status` returns:

```json
{
  "stripe_enabled": false,
  "entitlements_enforced": false,
  "subscription_count": 0,
  "subscriptions_by_status": {},
  "entitlement_cache_count": 0,
  "stripe_event_count": 0,
  "processed_webhooks": 0,
  "skipped_webhooks": 0,
  "billing_routes_present": true,
  "safe_state": true,
  "db_available": true,
  "snapshot_utc": "2026-06-15T00:00:00Z"
}
```

`safe_state: true` means `STRIPE_ENABLED=false AND ENTITLEMENTS_ENFORCED=false`.

---

## Security Constraints

- `STRIPE_SECRET_KEY` must never appear in application logs.
- `STRIPE_WEBHOOK_SECRET` must never appear in application logs.
- No raw Stripe event payload is stored in the DB (`stripe_events` has no `payload_json` column).
- `SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"` is always exempt from entitlement checks and cannot initiate checkout.
- No password columns — Supabase Auth is the sole credential custodian.
