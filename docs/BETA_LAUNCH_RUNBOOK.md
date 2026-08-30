# Controlled Beta Launch Runbook

This is the release gate for the first 10–25 invited users. The observation
window is 14 days. Do not broaden access during that window.

## Entry criteria

1. Required CI is green on the exact commit being deployed.
2. The deployed build commit matches that release candidate.
3. `tests/validate_beta_launch.py` exits `0` with two short-lived tokens: one
   from a designated non-admin beta account for product checks and one from a
   designated admin operator account for read-only operational snapshots.
4. The two-account isolation rehearsal in `docs/PRODUCTION_ACCEPTANCE.md` passes.
5. If beta users can pay, the full rehearsal in
   `docs/BILLING_INTEGRITY_ACCEPTANCE.md` passes in Stripe test mode before the
   live configuration is enabled.
6. The operator has verified access to the loop kill switch before admitting
   the first user.

## Run the gate

Free beta with delivery held in shadow:

```bash
export CLEARSIGNAL_ACCESS_TOKEN="<short-lived access token>"
export CLEARSIGNAL_ADMIN_ACCESS_TOKEN="<short-lived admin access token>"
export EXPECTED_BUILD_COMMIT="<deployed backend commit>"
python tests/validate_beta_launch.py
unset CLEARSIGNAL_ACCESS_TOKEN
unset CLEARSIGNAL_ADMIN_ACCESS_TOKEN
```

Paid beta and/or live continuous delivery require deliberate opt-in:

```bash
python tests/validate_beta_launch.py --paid-beta
python tests/validate_beta_launch.py --allow-live-delivery
python tests/validate_beta_launch.py --paid-beta --allow-live-delivery
```

The validator is read-only. It never prints or persists either token. Record only
the commit, UTC timestamp, selected mode, check names, and pass/fail outcome.

## Stop-ship conditions

- Any cross-account read, write, notification, preference, portfolio, or
  billing visibility.
- Any failed required CI check or mismatch between the deployed and expected
  commit.
- Any duplicate delivery.
- Any unresolved or pending billing webhook at the end of its processing
  window.
- Any unknown-price entitlement, duplicate paid subscription, or disagreement
  between payment and entitlement state.
- Any unavailable production database snapshot.

## Rollback

1. Stop new invitations.
2. Disable continuous delivery with `POST /admin/loop/disable`; confirm
   `/admin/loop/status` reports `effective_enabled: false`.
3. For billing incidents, set `ENTITLEMENTS_ENFORCED=false` first so users are
   not incorrectly blocked, then set `STRIPE_ENABLED=false` to stop new Stripe
   operations. Preserve webhook and subscription records for diagnosis.
4. For an authentication or account-isolation incident, take protected product
   traffic out of service. Do not use `AUTH_ENABLED=false` in production: that
   restores shared-system identity behavior and is not a safe beta rollback.
5. Redeploy the last known-good commit and rerun the free/shadow beta gate.
6. Resume only after the original stop-ship condition has a verified fix and a
   complete acceptance rerun.

## Fourteen-day observation record

For each UTC day, record the deployed commit, gate result, health status,
database availability, duplicate-delivery count, unresolved/pending webhook
counts, open stop-ship incidents, and invitation count. Store only aggregate
counts and opaque incident references—never tokens, customer IDs, email
addresses, portfolio data, or payment details.

At day 14, advance toward public-launch readiness only if every stop-ship item
is clear, all invited-user incidents are resolved, the rollback drill has been
performed successfully, and the final gate passes on the current deployment.
