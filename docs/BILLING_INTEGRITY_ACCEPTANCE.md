# Billing Integrity Acceptance

Run this gate after deploying billing changes and before enabling paid access
for invited beta users. Use designated test accounts and Stripe test mode first.

## Automated release gate

Required CI covers:

- Signal monthly and annual price mapping;
- Syndicate monthly price mapping;
- rejection of unsupported plan/interval combinations;
- fail-closed rejection of missing or unknown webhook price IDs;
- idempotent customer creation and webhook replay;
- atomic rollback plus HTTP 500 on transient handler failure;
- checkout ownership and metadata propagation;
- subscription create, update, cancellation, deletion, trial, grace, and recovery;
- customer portal and cancellation ownership;
- failed-payment grace and successful-payment recovery;
- entitlement cache invalidation; and
- account-scoped billing status.

The admin `/admin/billing-status` snapshot must report:

- `stripe_enabled: true`;
- `stripe_config_ready: true`;
- `entitlements_enforced: true`;
- `billing_routes_present: true`;
- `db_available: true`;
- `unresolved_webhook_errors: 0`;
- `pending_webhooks: 0`; and
- `billing_live_ready: true`.

The endpoint reports booleans and aggregate counts only. Never place Stripe
keys, webhook secrets, customer IDs, emails, payment details, or access tokens
in the release record.

## Production lifecycle rehearsal

Use a designated payment tester for each paid tier. Record only the opaque test
account label, timestamps, event IDs, expected state, actual state, and pass/fail.

1. Confirm a new account starts on Spark with free entitlements.
2. Open and cancel a Signal monthly checkout; confirm no plan change.
3. Complete Signal monthly checkout; confirm the subscription webhook produces
   Signal entitlements exactly once.
4. Open the customer portal and return successfully.
5. Upgrade or replace the subscription with Signal annual; confirm the price,
   interval, period end, and entitlements remain consistent.
6. Complete a Syndicate monthly checkout with a separate designated account;
   confirm Syndicate entitlements and organization/API capabilities.
7. Replay a completed webhook event; confirm it is reported as a duplicate and
   creates no additional subscription or entitlement mutation.
8. In Stripe test mode, trigger payment failure; confirm `past_due`, the
   three-day grace period, and retained temporary access.
9. Trigger payment success; confirm the grace deadline clears and active access
   resumes without duplicate subscription rows.
10. Cancel at period end through the portal/API; confirm access remains until
    the recorded period end and then returns to Spark after deletion.
11. Verify each test account sees only its own customer, plan, period, portal,
    cancellation, and entitlement state.
12. Confirm `/admin/billing-status` returns `billing_live_ready: true` with no
    pending or errored webhook events.

Any cross-account state, unknown-price entitlement, duplicate paid row,
incorrect plan transition, unresolved webhook error, or payment/entitlement
disagreement is a stop-ship defect.
