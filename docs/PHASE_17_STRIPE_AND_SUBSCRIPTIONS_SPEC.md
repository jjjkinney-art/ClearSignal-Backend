# Phase 17 — Stripe & Subscription Architecture

**Status:** Design only — no implementation in this document  
**Prerequisite:** Phase 16 (Accounts & Identity) fully deployed and production-validated  
**Stripe API version target:** `2024-04-10` (latest stable)

---

## 1. Goals

Transform ClearSignal from an authenticated product into a paid product.

1. Introduce subscription tiers with distinct feature limits
2. Integrate Stripe for payment, billing, and customer portal
3. Gate access to premium features via a fast entitlement layer
4. Handle payment failure, grace periods, and cancellation safely
5. Preserve backward compatibility with the bypass-mode system user
6. Lay the data model groundwork for Teams and Institutional accounts

---

## 2. Subscription Tiers

### 2.1 Tier Overview

| Tier | Name | Price | Target |
|---|---|---|---|
| Free | **Spark** | $0/month | Evaluators, light users |
| Paid | **Signal** | $29/month or $249/year | Active investors |
| Teams | **Syndicate** | $99/month (up to 5 seats) + $15/seat | Small funds, investment clubs |
| Institutional | **Edge** | Custom (negotiated) | RIAs, hedge funds, family offices |

The `account_type` column on `users` (already present) carries the top-level discriminator:
`individual | team_member | institutional | system`

A new `plan` column on `users` carries the billing plan:
`free | pro | teams | institutional | system`

---

### 2.2 Free Tier — Spark

**Intent:** Demonstrate value, build habit, justify upgrade.  
**Principle:** Free users see real data, feel real capability, but hit limits that make the paid tier obvious.

| Resource | Free Limit |
|---|---|
| Watched tickers | 5 |
| Portfolios | 1 |
| Portfolio positions | 10 per portfolio |
| Briefing cadence | Weekly (Sunday 08:00 UTC) |
| Dossier access | 3 lookups / calendar month |
| Portfolio intelligence | Disabled |
| Delivery channels | In-app only |
| Inbox history | 30 days |
| Custom quiet hours | Disabled |
| Briefing time customization | Disabled |
| Data export | Disabled |
| API access | Disabled |

Free is permanent — not a trial. A trial is a time-bounded experience of the Signal tier (see §2.4).

---

### 2.3 Signal Tier — Pro ($29/month or $249/year)

**Intent:** Full individual investor toolkit. The primary revenue product.

| Resource | Signal Limit |
|---|---|
| Watched tickers | Unlimited (soft cap 500 for performance) |
| Portfolios | 5 |
| Portfolio positions | Unlimited |
| Briefing cadence | Daily (user-selected time, 0–23 UTC) |
| Dossier access | Unlimited |
| Portfolio intelligence | Full (all 8 insight types) |
| Delivery channels | In-app + email |
| Inbox history | Unlimited |
| Custom quiet hours | Enabled |
| Briefing time customization | Enabled |
| Data export | CSV export of watchlist + portfolios |
| API access | Disabled (Teams+) |

Annual plan discount: ~28% savings vs. monthly ($249 vs. $348).

---

### 2.4 Trial Behavior

- **Duration:** 14 calendar days from first sign-in
- **Card requirement:** No card required to start trial
- **Experience:** Full Signal tier during trial
- **Expiry:** Auto-downgrades to Spark at trial end if no subscription started
- **Re-trial:** One trial per email address — no re-activation
- **Trial status:** Stripe subscription status = `trialing`; local `subscriptions.status = trialing`
- **End warning:** Webhook `customer.subscription.trial_will_end` fires 3 days before expiry → send email notification
- **Conversion CTA:** Surface in `/auth/session` response as `trial_days_remaining: N` and `show_upgrade_cta: true`

Trial is implemented as a Stripe subscription in trial mode (no charge), not as a local timer. This ensures Stripe remains the single source of truth for billing state.

---

### 2.5 Syndicate — Teams ($99/month base + $15/seat/month over 5)

**Intent:** Small funds and investment clubs with shared context.

Additional capabilities beyond Signal:

| Capability | Detail |
|---|---|
| Seat count | 5 included; $15/seat/month thereafter |
| Organization watchlist | Shared watchlist visible to all members |
| Shared portfolios | Portfolios owned by org, visible to all members |
| Team-level insights | Portfolio intelligence across all member portfolios |
| Role management | owner \| admin \| member \| viewer |
| Admin billing portal | Org owner manages seats and billing |
| Audit log export | TSV/CSV export of org audit_log (SOC 2 ready) |
| API access | Read-only REST API with org-scoped API keys |

Seat billing uses Stripe's `quantity` on a metered price per seat.

---

### 2.6 Edge — Institutional (Custom pricing)

**Intent:** RIAs, hedge funds, family offices. Negotiated contracts.

Additional capabilities beyond Syndicate:

| Capability | Detail |
|---|---|
| SSO / SAML 2.0 | Via Supabase Auth SAML (no backend code change) |
| Unlimited seats | No per-seat fee |
| Custom delivery SLA | Dedicated delivery schedule |
| Data residency | Supabase EU or US region selection |
| SOC 2 audit export | Automated audit_log exports on schedule |
| Dedicated support | SLA-backed support channel |
| White-label briefings | Custom email templates and domain |
| Read/write API | Full API access with service accounts |

Billing: annual contract via Stripe Invoice (not subscription), or Stripe `collection_method=send_invoice`.

---

## 3. Entitlement Model

### 3.1 Feature Gate Matrix

| Feature | Spark (Free) | Signal (Pro) | Syndicate (Teams) | Edge (Institutional) |
|---|---|---|---|---|
| Watchlist | 5 tickers | Unlimited | Unlimited + org-shared | Unlimited |
| Portfolios | 1 | 5 | Unlimited (org-shared) | Unlimited |
| Portfolio positions | 10 | Unlimited | Unlimited | Unlimited |
| Briefing cadence | Weekly | Daily | Daily | Custom |
| Briefing time control | ✗ | ✓ | ✓ | ✓ |
| Dossier lookups | 3/month | Unlimited | Unlimited | Unlimited |
| Portfolio intelligence | ✗ | ✓ (all types) | ✓ | ✓ |
| Delivery: in-app | ✓ | ✓ | ✓ | ✓ |
| Delivery: email | ✗ | ✓ | ✓ | ✓ |
| Delivery: push | ✗ | ✗ | ✓ | ✓ |
| Custom quiet hours | ✗ | ✓ | ✓ | ✓ |
| Inbox history | 30 days | Unlimited | Unlimited | Unlimited |
| Data export | ✗ | CSV | CSV + JSON | CSV + JSON + API |
| API access | ✗ | ✗ | Read-only | Read + Write |
| Organization features | ✗ | ✗ | ✓ | ✓ |
| SSO / SAML | ✗ | ✗ | ✗ | ✓ |
| Audit log export | ✗ | ✗ | ✓ | ✓ |

### 3.2 Entitlement Resolution

Entitlements are resolved per-request for gated routes. The resolution chain:

```
1. Request arrives at gated route
2. get_entitlements(session, user_id) is called
3. Cache check → entitlement_cache WHERE user_id = ? AND expires_at > NOW()
   └── Hit  → return cached EntitlementSet
   └── Miss → query subscriptions table
4. Subscription query:
   SELECT plan_name, status, grace_period_ends_at, trial_ends_at
   FROM subscriptions
   WHERE user_id = ? AND status NOT IN ('canceled', 'expired')
   ORDER BY created_at DESC LIMIT 1
5. Apply grace period rules:
   └── status='past_due' AND grace_period_ends_at > NOW() → treat as plan_name (keep access)
   └── status='past_due' AND grace_period_ends_at <= NOW() → downgrade to 'free'
   └── status='trialing' AND trial_ends_at > NOW() → treat as 'pro'
   └── status='trialing' AND trial_ends_at <= NOW() → 'free' (Stripe should have fired webhook; fallback)
   └── status='active' → use plan_name as-is
   └── No row found → 'free'
6. Build EntitlementSet from resolved plan
7. Write to entitlement_cache (TTL: 1 hour)
8. Return EntitlementSet
```

### 3.3 EntitlementSet Schema

```python
@dataclass
class EntitlementSet:
    user_id:               str
    plan_name:             str           # free | pro | teams | institutional
    plan_status:           str           # active | trialing | past_due | grace | free_fallback
    trial_days_remaining:  Optional[int] # None if not trialing
    show_upgrade_cta:      bool

    # Limits (-1 = unlimited)
    watchlist_limit:       int           # 5 / -1 / -1 / -1
    portfolio_limit:       int           # 1 / 5 / -1 / -1
    position_limit:        int           # 10 / -1 / -1 / -1
    dossier_monthly_limit: int           # 3 / -1 / -1 / -1

    # Features (booleans)
    can_use_portfolio_intelligence: bool
    can_use_email_delivery:         bool
    can_use_push_delivery:          bool
    can_set_briefing_time:          bool
    can_use_custom_quiet_hours:     bool
    can_export_data:                bool
    can_use_api:                    bool
    can_use_org_features:           bool
    has_unlimited_inbox:            bool

    computed_at:           str           # ISO-8601
    cache_expires_at:      str           # ISO-8601
```

### 3.4 Enforcement Points

Entitlement checks are enforced in the **service layer**, not middleware. This keeps routes thin and ensures entitlements are checked regardless of the call path (HTTP or internal).

| Service | Guard | Limit checked |
|---|---|---|
| `watchlist_service` | `add_ticker_async` | `watchlist_limit` |
| portfolio service | `create_portfolio` | `portfolio_limit` |
| portfolio service | `add_position` | `position_limit` |
| dossier service | `generate_dossier` | `dossier_monthly_limit` |
| portfolio intelligence | `run_insight_pipeline` | `can_use_portfolio_intelligence` |
| delivery service | `dispatch_channel` | `can_use_email_delivery`, `can_use_push_delivery` |
| briefing service | `schedule_briefing` | `briefing_cadence`, `can_set_briefing_time` |
| export service | `export_data` | `can_export_data` |

**Guard pattern:**

```python
async def check_entitlement(session, user_id, *, resource, increment=1):
    ents = await get_entitlements(session, user_id)
    limit = getattr(ents, f"{resource}_limit")
    if limit == -1:
        return  # unlimited
    current = await count_user_resource(session, user_id, resource)
    if current + increment > limit:
        raise EntitlementError(
            resource=resource,
            limit=limit,
            current=current,
            plan=ents.plan_name,
            upgrade_required=True,
        )
```

`EntitlementError` is caught at the route layer and returned as HTTP 402 with:
```json
{
    "error": "plan_limit_reached",
    "resource": "watchlist",
    "limit": 5,
    "current": 5,
    "plan": "free",
    "upgrade_url": "/billing/upgrade"
}
```

### 3.5 Dossier Limit Counting

Monthly dossier usage is tracked via `audit_log`:

```sql
SELECT COUNT(*) FROM audit_log
WHERE user_id = :uid
  AND action = 'dossier_generate'
  AND resource = 'company_dossier'
  AND created_at >= date_trunc('month', NOW())
```

No separate usage table required. At high scale (>100k MAU), migrate to a dedicated `usage_ledger` table.

---

## 4. Stripe Integration

### 4.1 Stripe Objects

| Stripe Object | Cardinality | Our Binding |
|---|---|---|
| `Customer` | 1 per user | `users.stripe_customer_id` (existing column) |
| `Product` | 1 per plan (Signal, Syndicate, Edge) | Hardcoded price IDs in config |
| `Price` | 2 per product (monthly + annual) | Config: `STRIPE_PRICE_*` env vars |
| `Subscription` | 0–1 per customer (at any time) | `subscriptions.stripe_subscription_id` |
| `SubscriptionItem` | 1+ per subscription | Referenced in subscription payload |
| `Invoice` | Auto-created by Stripe | `stripe_events` webhook payload |
| `PaymentMethod` | Stored by Stripe | Never stored locally |
| `CheckoutSession` | Created on demand | Not persisted (redirect URL only) |
| `BillingPortalSession` | Created on demand | Not persisted (redirect URL only) |
| `WebhookEndpoint` | 1 per environment | Configured in Stripe dashboard |

### 4.2 Stripe Customer Lifecycle

```
User signs up (Supabase auth)
  └── provision_new_user() creates users row
  └── stripe_customer_id = NULL  ← Phase 16 placeholder

User initiates upgrade / checkout
  └── stripe_service.get_or_create_customer(user_id, email)
      ├── stripe_customer_id present → return existing Customer
      └── stripe_customer_id NULL →
          stripe.Customer.create(email=email, metadata={"user_id": user_id})
          UPDATE users SET stripe_customer_id = cus_xxx

User completes checkout
  └── stripe.checkout.Session.create(
        customer=cus_xxx,
        mode='subscription',
        line_items=[{price: STRIPE_PRICE_PRO_MONTHLY, quantity: 1}],
        trial_period_days=14,
        allow_promotion_codes=True,
        success_url=FRONTEND_URL + '/billing/success?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=FRONTEND_URL + '/billing/cancel',
      )
  └── Redirect to Stripe-hosted checkout
  └── Stripe fires checkout.session.completed webhook
  └── Backend provisions subscription row
```

### 4.3 Stripe Configuration

All Stripe price IDs and keys are environment variables — never hardcoded.

| Env Var | Description |
|---|---|
| `STRIPE_SECRET_KEY` | Stripe secret key (`sk_live_*` or `sk_test_*`) |
| `STRIPE_WEBHOOK_SECRET` | Webhook endpoint signing secret (`whsec_*`) |
| `STRIPE_PRICE_PRO_MONTHLY` | Price ID for Signal monthly (`price_*`) |
| `STRIPE_PRICE_PRO_ANNUAL` | Price ID for Signal annual |
| `STRIPE_PRICE_TEAMS_MONTHLY` | Price ID for Syndicate base (5 seats) |
| `STRIPE_PRICE_TEAMS_PER_SEAT` | Price ID for Syndicate per-seat metered |
| `STRIPE_PUBLISHABLE_KEY` | Exposed to frontend for Stripe.js |
| `STRIPE_ENABLED` | `false` during build slices; `true` to activate billing |

`STRIPE_ENABLED=false` during all Phase 17 build slices (mirrors `AUTH_ENABLED=false` pattern). All billing routes respond with safe dummy data when disabled.

### 4.4 Webhook Architecture

Webhook events are the authoritative source of billing state. The backend must never assume a checkout completed until the webhook fires.

#### 4.4.1 Event Processing Pipeline

```
POST /webhooks/stripe
  1. Verify Stripe-Signature header using STRIPE_WEBHOOK_SECRET
     └── Reject with 400 on bad signature (no logging of payload)
  2. Parse event JSON → stripe.Event
  3. Idempotency check:
     SELECT id FROM stripe_events WHERE stripe_event_id = event.id
     └── Already processed → return 200 immediately (Stripe retries otherwise)
  4. INSERT INTO stripe_events (stripe_event_id, event_type, payload_json, processing_status='pending')
  5. Route to handler by event_type (see §4.4.2)
  6. UPDATE stripe_events SET processing_status='ok'/'error', error_detail=...
  7. Return 200 (always — even on handler error; Stripe should not re-deliver processed events)
```

**Critical:** The webhook endpoint returns 200 before handler processing completes if the event is already in `stripe_events`. This prevents Stripe from re-delivering and creating duplicate side effects.

**Handler errors** update `stripe_events.processing_status = 'error'` and alert the ops team. They do **not** return 5xx (which would trigger Stripe retries and potentially double-apply an event).

#### 4.4.2 Handled Events

| Stripe Event | Handler Action |
|---|---|
| `checkout.session.completed` | Create `subscriptions` row; set `plan`; invalidate entitlement cache |
| `customer.subscription.created` | Idempotent upsert of `subscriptions` row (backup for checkout) |
| `customer.subscription.updated` | Update `subscriptions.plan_name`, `status`, `current_period_*`; invalidate cache |
| `customer.subscription.deleted` | Set `subscriptions.status = 'canceled'`; downgrade to free; write audit log |
| `invoice.paid` | Extend `current_period_end`; clear `grace_period_ends_at`; restore if lapsed |
| `invoice.payment_failed` | Set `subscriptions.status = 'past_due'`; set `grace_period_ends_at = now + 3 days`; trigger notification |
| `invoice.payment_action_required` | Set `subscriptions.status = 'past_due'`; notify user of 3DS/SCA challenge |
| `customer.subscription.trial_will_end` | Notify user 3 days before trial end; show upgrade CTA |
| `customer.updated` | Sync email to `users.email` if changed via billing portal |
| `customer.deleted` | Nullify `users.stripe_customer_id`; downgrade to free |

#### 4.4.3 Events Explicitly Ignored

| Stripe Event | Reason |
|---|---|
| `payment_intent.*` | Redundant with invoice events; invoices are the source of truth |
| `charge.*` | Redundant with invoice events |
| `product.*` | Product catalog managed in Stripe dashboard, not backend |
| `price.*` | Same as above |
| `radar.*` | Fraud signals handled by Stripe; no backend action needed |

#### 4.4.4 Webhook Endpoint Security

```python
# Signature verification — must happen BEFORE any payload access
payload = await request.body()  # raw bytes, not parsed
sig_header = request.headers.get("stripe-signature", "")
try:
    event = stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )
except stripe.error.SignatureVerificationError:
    raise HTTPException(status_code=400, detail="Invalid Stripe signature")
```

**Never log** the raw webhook payload. Only log `event_type` and `event_id`.

### 4.5 Billing Portal

The Stripe Customer Portal (hosted by Stripe) handles:
- Upgrade / downgrade between Signal monthly ↔ annual
- Cancel subscription
- Resume canceled subscription
- Update payment method
- View invoice history
- Download invoices

Backend creates a portal session on demand:

```python
session = stripe.billing_portal.Session.create(
    customer=user.stripe_customer_id,
    return_url=FRONTEND_URL + '/settings/billing',
)
return {"url": session.url}
```

No custom billing UI is required for Phase 17. The portal covers all self-service scenarios.

### 4.6 Plan Changes

#### Upgrades (Free → Pro, monthly → annual)

Handled via Stripe-hosted checkout for free→paid. For monthly→annual on existing subscription, use Stripe Customer Portal (immediate proration or invoice at cycle end).

#### Downgrades (Pro → Free, annual → monthly)

- **Pro → Free:** Cancel subscription at period end (`cancel_at_period_end=True`). User keeps Pro access until `current_period_end`. At expiry, `customer.subscription.deleted` fires and backend downgrades to free.
- **Annual → Monthly:** Via Customer Portal; Stripe handles proration.

**Principle:** No immediate downgrade in the backend. All plan changes are mediated by Stripe webhooks. The backend only acts on webhook events — never on HTTP requests to change plan directly.

---

## 5. Schema Additions

Phase 17 requires three new tables and two additive columns on existing tables. All migrations are additive (no DROP, no NOT NULL without DEFAULT).

### 5.1 New Column: `users.plan`

```sql
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS plan VARCHAR(20) NOT NULL DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS plan_updated_at TIMESTAMPTZ DEFAULT NULL;
```

`plan` is a **denormalised cache** of the active subscription's `plan_name`. It exists for fast entitlement reads and observability. It is always updated as a side effect of subscription lifecycle events — it is not the source of truth. The `subscriptions` table is authoritative.

### 5.2 Table: `subscriptions`

```sql
CREATE TABLE IF NOT EXISTS subscriptions (
    id                      VARCHAR(36)   PRIMARY KEY,
    user_id                 VARCHAR(36)   NOT NULL,       -- FK → users.id (soft)
    org_id                  VARCHAR(36)   DEFAULT NULL,   -- FK → organizations.id (Teams)
    stripe_subscription_id  VARCHAR(64)   UNIQUE NOT NULL,
    stripe_customer_id      VARCHAR(64)   NOT NULL,
    stripe_price_id         VARCHAR(64)   NOT NULL,
    plan_name               VARCHAR(20)   NOT NULL,       -- free|pro|teams|institutional
    billing_interval        VARCHAR(10)   NOT NULL,       -- month|year|custom
    status                  VARCHAR(20)   NOT NULL,       -- active|trialing|past_due|canceled|paused|lapsed
    trial_ends_at           TIMESTAMPTZ   DEFAULT NULL,
    current_period_start    TIMESTAMPTZ   NOT NULL,
    current_period_end      TIMESTAMPTZ   NOT NULL,
    cancel_at_period_end    BOOLEAN       NOT NULL DEFAULT FALSE,
    canceled_at             TIMESTAMPTZ   DEFAULT NULL,
    grace_period_ends_at    TIMESTAMPTZ   DEFAULT NULL,
    seat_count              INTEGER       NOT NULL DEFAULT 1,   -- Teams only
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS ix_subscriptions_status  ON subscriptions(status);
```

One row per subscription lifecycle event (subscription is never deleted; status tracks lifecycle). A user may have at most one `status IN ('active','trialing','past_due','paused')` row at any time — enforced by application logic, not a DB constraint (to allow historical rows).

### 5.3 Table: `stripe_events`

```sql
CREATE TABLE IF NOT EXISTS stripe_events (
    id                VARCHAR(36)   PRIMARY KEY,
    stripe_event_id   VARCHAR(64)   UNIQUE NOT NULL,    -- dedup key: evt_*
    event_type        VARCHAR(80)   NOT NULL,
    processing_status VARCHAR(20)   NOT NULL DEFAULT 'pending',  -- pending|ok|error|skipped
    error_detail      TEXT          DEFAULT NULL,
    processed_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
    -- payload_json intentionally omitted: Stripe event data is retrievable
    -- via stripe.Event.retrieve(stripe_event_id) and should not be stored
    -- to avoid PII retention in the application database.
);

CREATE INDEX IF NOT EXISTS ix_stripe_events_type ON stripe_events(event_type);
```

**No `payload_json` column.** Raw Stripe event payloads may contain PII (customer email, card last 4, billing address). Storing them in our DB creates a PII retention obligation. If debugging is needed, retrieve the event from Stripe's dashboard by `stripe_event_id`.

### 5.4 Table: `entitlement_cache`

```sql
CREATE TABLE IF NOT EXISTS entitlement_cache (
    user_id              VARCHAR(36)   PRIMARY KEY,
    plan_name            VARCHAR(20)   NOT NULL,
    plan_status          VARCHAR(20)   NOT NULL,
    watchlist_limit      INTEGER       NOT NULL,
    portfolio_limit      INTEGER       NOT NULL,
    position_limit       INTEGER       NOT NULL,
    dossier_monthly_limit INTEGER      NOT NULL,    -- -1 = unlimited
    features_json        TEXT          NOT NULL,    -- JSON: boolean feature flags
    trial_days_remaining INTEGER       DEFAULT NULL,
    computed_at          TIMESTAMPTZ   NOT NULL,
    expires_at           TIMESTAMPTZ   NOT NULL
);
```

Invalidated on every subscription lifecycle event. If the cache row is missing or `expires_at < NOW()`, the service recomputes from `subscriptions` and writes a new row with `expires_at = NOW() + 1 hour`.

At high scale, replace with Redis. The same interface (`get_entitlements(session, user_id)`) is used regardless of backing store.

### 5.5 Total Table Count After Phase 17

| Phase | Tables Added | Running Total |
|---|---|---|
| Phase 16 (current) | 4 | 35 |
| Phase 17 | 3 (`subscriptions`, `stripe_events`, `entitlement_cache`) | 38 |

---

## 6. Service Architecture

### 6.1 New Services

```
app/services/
├── stripe_service.py            # Stripe API calls (customers, sessions, portal)
├── subscription_service.py      # Subscription lifecycle; state machine
├── entitlement_service.py       # EntitlementSet resolution; cache management
└── webhook_handler.py           # Event routing and per-event handlers
```

```
app/routers/
├── billing.py                   # GET /billing/status, POST /billing/checkout, POST /billing/portal
└── webhooks.py                  # POST /webhooks/stripe
```

### 6.2 Stripe Service

Thin wrapper around the Stripe Python SDK. Handles all outbound Stripe API calls. Never called directly from routes — always via `subscription_service`.

Key functions:
- `get_or_create_customer(user_id, email) → Customer`
- `create_checkout_session(customer_id, price_id, trial_days) → CheckoutSession`
- `create_portal_session(customer_id, return_url) → PortalSession`
- `retrieve_subscription(stripe_subscription_id) → Subscription`
- `cancel_subscription_at_period_end(stripe_subscription_id) → Subscription`

All calls are wrapped in try/except with structured logging. Stripe API errors are caught and re-raised as `StripeServiceError` — a domain exception that routes convert to HTTP 502 (upstream failure) rather than 500.

### 6.3 Subscription Service

Owns the local subscription state machine. Called by the webhook handler to apply lifecycle transitions.

```python
async def activate_subscription(session, *, user_id, stripe_subscription_id,
                                stripe_customer_id, stripe_price_id,
                                plan_name, billing_interval, period_start,
                                period_end, trial_ends_at) -> Subscription

async def update_subscription(session, *, stripe_subscription_id,
                              plan_name, status, period_end,
                              cancel_at_period_end) -> Subscription

async def mark_past_due(session, *, stripe_subscription_id,
                        grace_days=3) -> Subscription

async def mark_canceled(session, *, stripe_subscription_id) -> Subscription

async def mark_payment_recovered(session, *,
                                  stripe_subscription_id) -> Subscription

async def get_active_subscription(session, user_id) -> Optional[Subscription]
```

Each function:
1. Updates the `subscriptions` row
2. Updates `users.plan` (denorm)
3. Calls `invalidate_entitlement_cache(user_id)`
4. Writes an `audit_log` entry (`action='subscription_changed'`, `resource='subscription'`)

### 6.4 Entitlement Service

```python
# Public API used by service-layer guards
async def get_entitlements(session, user_id: str) -> EntitlementSet
async def check_watchlist_limit(session, user_id: str) -> None  # raises EntitlementError
async def check_portfolio_limit(session, user_id: str) -> None
async def check_position_limit(session, user_id: str, portfolio_id: str) -> None
async def check_dossier_limit(session, user_id: str) -> None
async def require_feature(session, user_id: str, feature: str) -> None  # raises EntitlementError

# Cache management
async def invalidate_entitlement_cache(session, user_id: str) -> None
async def warm_entitlement_cache(session, user_id: str) -> EntitlementSet

# Plan limit constants (for UI and API responses)
def get_plan_limits(plan_name: str) -> Dict[str, Any]
```

### 6.5 Webhook Handler

```python
# Entry point called by POST /webhooks/stripe after signature verification
async def handle_stripe_event(session, event: stripe.Event) -> None

# Per-event handlers
async def _handle_checkout_completed(session, event) -> None
async def _handle_subscription_created(session, event) -> None
async def _handle_subscription_updated(session, event) -> None
async def _handle_subscription_deleted(session, event) -> None
async def _handle_invoice_paid(session, event) -> None
async def _handle_invoice_payment_failed(session, event) -> None
async def _handle_trial_will_end(session, event) -> None
```

### 6.6 Billing Routes

```
POST /billing/checkout
  Body: { price_id: "pro_monthly" | "pro_annual" }
  Response: { checkout_url: "https://checkout.stripe.com/pay/..." }
  Auth: Required (JWT or bypass user → 402 if bypass)

POST /billing/portal
  Body: {}
  Response: { portal_url: "https://billing.stripe.com/..." }
  Auth: Required; stripe_customer_id must exist

GET /billing/status
  Response: { plan: "free", status: "active", trial_days_remaining: null,
              current_period_end: "...", show_upgrade_cta: false }
  Auth: Required

POST /billing/cancel
  Body: { at_period_end: true }
  Response: { canceled: true, access_until: "..." }
  Auth: Required; delegates to Stripe Customer Portal in Phase 17

POST /webhooks/stripe
  Webhook only — validates Stripe-Signature
  Response: { received: true }
  Auth: None (Stripe signature is the auth)
```

---

## 7. Failure Handling & Grace Periods

### 7.1 Payment Failure State Machine

```
                            ┌─────────────────┐
                            │   active         │
                            └────────┬────────┘
                                     │ invoice.payment_failed
                                     ▼
                            ┌─────────────────┐
                            │   past_due       │  ← grace_period_ends_at = NOW + 3 days
                            └────────┬────────┘    User keeps full plan access
                          ┌──────────┴──────────┐
               invoice.paid             grace_period_ends_at expires
               (Stripe retry)           (no payment after 3 days)
                          │                      │
                          ▼                      ▼
                 ┌─────────────┐        ┌────────────────┐
                 │   active    │        │    lapsed       │  ← downgrade to free
                 └─────────────┘        └───────┬────────┘
                                                │ user pays outstanding invoice
                                                ▼
                                       ┌─────────────────┐
                                       │   active         │  ← restore to plan
                                       └─────────────────┘
```

**Grace period rule:** 3 calendar days of full access after first payment failure. During grace, `subscriptions.status = 'past_due'` and entitlements resolve to the paid plan. After grace expires, `status` transitions to `'lapsed'` and entitlements resolve to `'free'`.

**Why 3 days?** Stripe Smart Retries may succeed within hours; 3 days avoids false degradation for temporary card failures (expired card, transient decline) while not extending indefinitely.

**Dunning is Stripe's responsibility.** Stripe retries failed invoices up to 4 times over ~3 weeks (configurable in Stripe Dashboard → Billing → Retry schedule). Each retry fires `invoice.payment_failed` (if failed) or `invoice.paid` (if recovered). The backend responds to each event accordingly.

### 7.2 Subscription Cancellation

```
User cancels via billing portal
  └── Stripe sets cancel_at_period_end=true on subscription
  └── Backend receives customer.subscription.updated
      └── UPDATE subscriptions SET cancel_at_period_end=true
      └── Entitlement unchanged (access until period end)

Period ends (current_period_end reached)
  └── Stripe fires customer.subscription.deleted
  └── Backend receives webhook
      └── UPDATE subscriptions SET status='canceled', canceled_at=NOW()
      └── UPDATE users SET plan='free'
      └── Invalidate entitlement cache
      └── Write audit_log entry
```

A canceled user can resubscribe at any time. A new checkout session creates a new Stripe subscription — a new `subscriptions` row, fresh trial eligibility only if they have never trialed (enforced by Stripe via `stripe_customer_id` dedup).

### 7.3 Lapsed Subscription Recovery

When a lapsed user pays their outstanding invoice:

1. Stripe fires `invoice.paid`
2. Backend extracts `stripe_subscription_id` from invoice object
3. Calls `mark_payment_recovered(session, stripe_subscription_id=...)`
4. Sets `subscriptions.status = 'active'`, clears `grace_period_ends_at`
5. Sets `users.plan` back to `plan_name`
6. Invalidates entitlement cache
7. Writes audit log: `action='subscription_recovered'`
8. Sends re-activation notification (future: via delivery service)

### 7.4 Webhook Delivery Failures

Stripe retries webhook delivery up to 72 hours (exponential backoff). Our endpoint:
- Always returns 200 after signature verification
- Processes events idempotently (stripe_event_id dedup)
- Handler failures are logged to `stripe_events.processing_status='error'` but do not cause non-200 response

**Ops alert:** Any `processing_status='error'` row in `stripe_events` triggers an alert. Manual re-trigger is possible by retrieving the event from Stripe and calling the handler directly.

**Webhook health check:** `GET /admin/stripe-status` (Phase 17 observability endpoint) reports:
- Last received event timestamp
- Count of `error` events in last 24h
- Subscription counts by status
- Entitlement cache hit rate

### 7.5 Entitlement Cache Failure

If `entitlement_cache` is unavailable or expired:
- `get_entitlements` falls back to live `subscriptions` query
- Failure is logged but does not block the request
- Cache is rebuilt asynchronously after the request completes
- If both `entitlement_cache` and `subscriptions` fail: **fail-open to `free` plan** (safe; users never get unexpected charges)

---

## 8. Ownership Integration

### 8.1 System User Bypass

`SYSTEM_DEFAULT_USER_ID` is permanently on the `free` plan (`plan='system'` in `users`).  
All entitlement checks on `SYSTEM_DEFAULT_USER_ID` short-circuit to **skip** (no limit, no gate).  
This preserves the Phase 16 bypass-mode invariant: existing behavior is unchanged when `AUTH_ENABLED=false`.

```python
if user_id == SYSTEM_DEFAULT_USER_ID:
    return _system_entitlements()  # unlimited, no gating
```

### 8.2 Watchlist

`watchlist_service.add_ticker_async` calls `check_watchlist_limit(session, user_id)` before insert.  
If limit reached: `EntitlementError` → HTTP 402 with upgrade CTA.  
The system-user watchlist (starter data) does not count against the user's limit after import — imported rows are owned by the user and do count.

### 8.3 Portfolios

`create_portfolio` checks `check_portfolio_limit(session, user_id)`.  
The single portfolio from `execute_import` counts toward the free limit.  
On upgrade to Signal (5 portfolios), existing portfolio is not affected; user can create up to 4 more.

### 8.4 Delivery

Delivery dispatch checks `can_use_email_delivery` / `can_use_push_delivery` per entitlement.  
Free users receive in-app delivery only; email delivery is silently suppressed (not errored) when not entitled.  
Briefing cadence: the scheduler reads `entitlement.briefing_cadence` per user before scheduling. Free users receive weekly cadence regardless of `user_settings.briefing_time_utc`.

### 8.5 Dossier

Dossier generation checks `check_dossier_limit` before running the pipeline.  
Usage is tracked via `audit_log` (action=`'dossier_generate'`) — no separate table required.  
Monthly count resets on the first of each calendar month (UTC). Free users see a counter in the UI: "2 of 3 dossier lookups used this month."

---

## 9. Future Compatibility

### 9.1 Teams (Syndicate) — Architecture

Teams require two new tables not built in Phase 17 but architecturally planned:

```sql
-- organizations: one row per team account
CREATE TABLE organizations (
    id           VARCHAR(36)   PRIMARY KEY,
    name         VARCHAR(200)  NOT NULL,
    plan         VARCHAR(20)   NOT NULL DEFAULT 'teams',
    stripe_subscription_id VARCHAR(64) UNIQUE DEFAULT NULL,
    seat_limit   INTEGER       NOT NULL DEFAULT 5,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- organization_members: many-to-many users ↔ organizations
CREATE TABLE organization_members (
    org_id       VARCHAR(36)   NOT NULL,    -- FK → organizations.id
    user_id      VARCHAR(36)   NOT NULL,    -- FK → users.id
    role         VARCHAR(20)   NOT NULL,    -- owner|admin|member|viewer
    joined_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (org_id, user_id)
);
```

`portfolios.org_id` is already present (Phase 16 §8.2). No migration needed to add org-shared portfolios.

Entitlement resolution for team members:
1. Check user's personal subscription (same as today)
2. Also check `organization_members JOIN organizations` for any org membership
3. Effective entitlements = MAX(personal plan, org plan)

### 9.2 Institutional (Edge) — Architecture

Institutional accounts are billed via Stripe Invoices (not subscriptions). The `subscriptions` table supports this via `billing_interval='custom'` and `status='active'` driven by manual invoice payment confirmation.

SSO: Supabase Auth SAML 2.0 — no backend schema change required. The `auth_subject` on `users` captures the SAML assertion's `sub` claim identically to magic link / OAuth flows.

API keys: A `service_accounts` table (Phase 17.3+) holds long-lived tokens for programmatic access:

```sql
-- Planned schema (not Phase 17)
CREATE TABLE service_accounts (
    id           VARCHAR(36)   PRIMARY KEY,
    org_id       VARCHAR(36)   NOT NULL,
    name         VARCHAR(200)  NOT NULL,
    api_key_hash VARCHAR(64)   NOT NULL UNIQUE,  -- SHA-256, never the raw key
    scopes       TEXT          NOT NULL,          -- JSON array: ['read:watchlist', ...]
    last_used_at TIMESTAMPTZ   DEFAULT NULL,
    created_at   TIMESTAMPTZ   NOT NULL,
    expires_at   TIMESTAMPTZ   DEFAULT NULL
);
```

### 9.3 Metered / Usage Billing (Future)

Stripe Meter API supports usage-based pricing (e.g., per dossier generation over a monthly quota). If ClearSignal moves to usage billing, the `audit_log` records are the source of truth for usage reporting. `stripe.billing.Meter.create_event` would be called from the dossier service on each generation.

No schema change required — `audit_log` already captures `action='dossier_generate'` per user per event.

---

## 10. Entitlement Caching Strategy

### 10.1 Cache Lifetime

| Event | Cache Action |
|---|---|
| Subscription activated | Invalidate + warm |
| Subscription updated | Invalidate + warm |
| Subscription canceled | Invalidate + warm |
| Payment failed | Invalidate + warm |
| Grace period expired | Invalidate on next read (TTL-based) |
| Cache TTL | 1 hour |
| Cache miss | Rebuild from `subscriptions`; write new row |
| `subscriptions` miss | Resolve as `free`; write cache with 1h TTL |

### 10.2 Cache Bypass

Routes can pass `force_refresh=True` to `get_entitlements` to skip the cache. This is used by the billing status endpoint to ensure freshness after a checkout.

### 10.3 Future: Redis

At >10k concurrent users, replace `entitlement_cache` table with Redis:
- Same interface (`get_entitlements(session, user_id)`)
- Key: `entitlements:{user_id}`
- TTL: 3600 seconds
- Invalidation: `DEL entitlements:{user_id}` on webhook
- Fallback: if Redis unavailable, read from `subscriptions` (never block the request)

---

## 11. Phase 17 Slice Plan

Phase 17 is divided into 7 slices. Each slice is independently deployable. `STRIPE_ENABLED=false` throughout all build slices.

| Slice | Name | Description |
|---|---|---|
| 17.1 | Schema + Migration | `subscriptions`, `stripe_events`, `entitlement_cache` tables; `users.plan` column |
| 17.2 | Entitlement Service | `EntitlementSet`, plan limits, cache, `check_*` guards — no Stripe calls |
| 17.3 | Stripe Service + Checkout | `stripe_service.py`, `POST /billing/checkout`, test mode with Stripe test keys |
| 17.4 | Webhook Handler | `POST /webhooks/stripe`, idempotency, all event handlers, `stripe_events` writes |
| 17.5 | Billing Routes | `GET /billing/status`, `POST /billing/portal`, `POST /billing/cancel` |
| 17.6 | Entitlement Enforcement | Wire `check_*` guards into watchlist, portfolio, delivery, dossier services |
| 17.7 | Observability + Shadow | `GET /admin/stripe-status`, validation script, shadow mode soak, docs |

**Activation sequence:**
1. All 7 slices deployed with `STRIPE_ENABLED=false`
2. Stripe test-mode webhook validated end-to-end
3. 14-day shadow soak with test events
4. Set `STRIPE_ENABLED=true` + Stripe live keys → billing active

---

## 12. Open Questions

| Question | Decision needed before |
|---|---|
| **Trial card requirement?** Free trial (no card) vs. card-required trial. Recommended: no card required for first 14 days; reduces signup friction, increases conversion. | Slice 17.3 |
| **Annual plan proration policy.** Mid-cycle upgrade from monthly to annual: immediate proration credit or wait for next cycle? Stripe Customer Portal default is immediate. | Slice 17.5 |
| **Dossier limit reset logic.** Reset on calendar month boundary (UTC) or rolling 30 days from signup? Calendar month is simpler and easier to explain. | Slice 17.6 |
| **Import data counts toward limits?** Does the one imported portfolio count against the free 1-portfolio limit? Recommended: yes. Users can delete the imported portfolio if they want a fresh start. | Slice 17.6 |
| **Grace period length.** 3 days recommended. Could extend to 7 days for annual subscribers (they paid a year upfront; a 1-week grace is more generous and appropriate). | Slice 17.4 |
| **Free tier watchlist limit: 5 or 10?** 5 creates faster friction; 10 allows more value demonstration. Recommend 5 to drive conversion, with a clear counter in the UI. | Slice 17.2 |
| **Teams MVP scope.** Does Syndicate launch in Phase 17 or Phase 18? Recommended: Phase 17 schema only (org tables); Phase 18 UI + full team flows. | Slice 17.1 |
| **Stripe test → live key promotion.** Who approves the `STRIPE_ENABLED=true` flip? Requires sign-off on webhook validation, refund policy, and terms of service. | Post-17.7 |

---

## 13. Security Notes

- **No card data ever enters the backend.** All payment collection is via Stripe-hosted checkout and Customer Portal. Backend only receives the customer ID and subscription status.
- **Webhook signature verification is mandatory.** Any request to `POST /webhooks/stripe` that fails signature verification is rejected with 400 before any payload is read or processed.
- **`STRIPE_SECRET_KEY` is never logged.** The Stripe SDK uses it internally; the backend never interpolates it into strings or log statements.
- **Entitlement errors are not exploitable.** The `EntitlementError` HTTP 402 response does not reveal the user's internal plan state beyond what they already know from their billing dashboard.
- **`stripe_events` stores no PII.** Raw event payloads are not persisted. Only `stripe_event_id`, `event_type`, and processing status are stored.
- **The `free` fallback is the safe failure mode.** If entitlement resolution fails for any reason, the user is treated as free. They never gain unexpected access; they may temporarily lose access. This is the correct tradeoff.
