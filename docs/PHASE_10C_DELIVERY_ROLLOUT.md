# Phase 10C — Delivery Channel Rollout Guide

Rollout guide for the Phase 10C In-App Delivery Channel.  Covers safe defaults,
internal validation, canary rollout, rollback, and launch criteria.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DELIVERY_IN_APP_ENABLED` | `false` | Master gate. Must be `true` for any real delivery. |
| `DELIVERY_SHADOW` | `true` | Shadow mode. When `true`, guardrails run but no `Notification` rows are written. |
| `DELIVERY_INTERNAL_ONLY` | `true` | Restrict real delivery to users in `LOOP_INTERNAL_USER_IDS`. |
| `DELIVERY_CANARY_PCT` | `0` | Canary rollout %. Effective only when `DELIVERY_INTERNAL_ONLY=false`. |
| `LOOP_INTERNAL_USER_IDS` | `""` | Comma-separated list of internal user_ids that bypass canary gate. |

Guardrail variables (unchanged from Phase 10A):

| Variable | Default | Description |
|---|---|---|
| `DELIVERY_QUIET_HOURS_START` | `22` | UTC hour when quiet period starts (inclusive). |
| `DELIVERY_QUIET_HOURS_END` | `7` | UTC hour when quiet period ends (exclusive). |
| `DELIVERY_DAILY_CAP` | `20` | Max deliveries per channel per target_key per UTC day. |
| `DELIVERY_SEVERITY_FLOOR` | `info` | Minimum canonical severity for delivery. |

---

## Safe default state

With all defaults the system is **behaviourally identical to Phase 10A** — the
loop writes `delivered_shadow` rows but no `Notification` rows are ever created.

```
DELIVERY_IN_APP_ENABLED=false   # master gate off
DELIVERY_SHADOW=true            # shadow mode on
DELIVERY_INTERNAL_ONLY=true     # restrict to internal users (no-op; gate is off)
DELIVERY_CANARY_PCT=0           # no canary traffic (no-op; gate is off)
```

Confirm safe state after any deploy with:

```bash
python tests/validate_10c_delivery_shadow.py
```

Or via the admin endpoint:

```bash
curl https://<backend>/admin/delivery-status | jq '.safe_state, .delivery_flags'
```

Both must return `safe_state: true` and `delivery_in_app_enabled: false`.

---

## Step 1 — Internal shadow validation

**Goal:** confirm the full guardrail stack runs without errors against real
`delivered_shadow` rows before enabling live delivery.

**No config change needed for this step** — shadow runs automatically from
Phase 10A's `flush_pending_shadow()`.

Validation checks:
1. `GET /admin/delivery-status` → `ledger.shadow_count > 0` (rows are flowing).
2. `ledger.by_severity` contains only canonical values (`critical|high|medium|low|info`).
3. `notifications.delivery_notifications == 0` (no real Notification rows).
4. `duplicate_count == 0` (dedup is clean).
5. `guardrails.stale_threshold_hours == 72` (stale recheck is active).

---

## Step 2 — Enable for internal users

Set in Render environment (single-service restart, no code deploy needed):

```
DELIVERY_IN_APP_ENABLED=true
DELIVERY_SHADOW=false            # allow real Notification creation
DELIVERY_INTERNAL_ONLY=true     # restrict to internal users
LOOP_INTERNAL_USER_IDS=user-1,user-2  # comma-separated internal user_ids
```

After restart, call `flush_in_app()` (via the loop tick or a manual test).
Verify:

```bash
curl .../admin/delivery-status | jq '.safe_state'
# → false  (expected — live delivery is now active for internal users)

curl .../admin/delivery-status | jq '.notifications.delivery_notifications'
# → should increment after a flush

curl .../delivery/inbox?user_id=user-1
# → delivered rows should appear
```

Manual internal testing checklist:
- [ ] `Notification` rows appear in `GET /delivery/inbox`
- [ ] Mark-read (`PATCH /delivery/inbox/{id}/read`) works
- [ ] Digest batches visible via `GET /delivery/digests`
- [ ] Quiet-hours suppression fires (test by setting a delivery after `DELIVERY_QUIET_HOURS_START`)
- [ ] Daily cap fires after 20 deliveries on a target_key
- [ ] Duplicate delivery blocked (same `content_key` → dedup)
- [ ] Stale row suppressed after 72h

---

## Step 3 — Canary rollout

When internal validation passes, expand to a small canary:

```
DELIVERY_INTERNAL_ONLY=false
DELIVERY_CANARY_PCT=5           # 5% of sessions
```

Monitor:
- `GET /admin/delivery-status` → `notifications.delivery_notifications` should grow.
- `GET /admin/delivery-status` → `duplicate_count` should remain 0.
- No errors in server logs with prefix `[in_app]`.

Increase gradually: 5 → 10 → 25 → 50 → 95 (maximum — permanent 5% holdout).

---

## Step 4 — Full rollout

```
DELIVERY_CANARY_PCT=95
DELIVERY_INTERNAL_ONLY=false
```

Monitor for 24h before declaring launch complete.

---

## Rollback

**Instant rollback (no redeploy):** call the loop kill-switch:

```bash
curl -X POST https://<backend>/admin/loop/disable
```

This stops the loop tick (and therefore all delivery flushes) immediately.

**Config rollback:** set in Render and restart:

```
DELIVERY_IN_APP_ENABLED=false
```

This returns the system to safe default state — no `Notification` rows are
created in subsequent flushes.

---

## Guardrail metrics

Monitor these fields in `GET /admin/delivery-status` during rollout:

| Field | Healthy value | Alert when |
|---|---|---|
| `ledger.shadow_count` | Growing during shadow phase | Stops growing unexpectedly |
| `notifications.delivery_notifications` | 0 in shadow; growing in live | Non-zero in shadow phase |
| `duplicate_count` | 0 | > 0 (dedup missed a row) |
| `ledger.suppressed_count` | Small % of total | > 30% of total (over-suppression) |
| `ledger.pending_count` | Near 0 after each flush | Growing unboundedly |

---

## Launch criteria

All of the following must be true before declaring Phase 10C complete:

- [ ] `validate_10c_delivery_shadow.py` passes 100% (all checks PASS, 0 FAIL).
- [ ] Internal users have received real `Notification` rows via `flush_in_app()`.
- [ ] `GET /delivery/inbox` returns rows for internal users.
- [ ] Mark-read flow works end-to-end (`read_receipts > 0` in notification counts).
- [ ] `duplicate_count == 0` after at least 24h of live delivery.
- [ ] No `[in_app]` ERROR or WARNING log lines in production logs.
- [ ] Canary at ≥ 5% for at least 48h with no incidents.
- [ ] `GET /admin/loop-status` and `GET /admin/delivery-status` both return `status: ok`.
