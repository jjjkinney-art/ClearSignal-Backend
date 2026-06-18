# Phase 14 — Scenario Engine Shadow Rollout

## Overview

Phase 14 adds a conditional scenario analysis layer to the intelligence
substrate. All Phase 14 services are **shadow-only** by default: no
user-visible delivery, no mutation of source tables, no recommendation
or conviction consumers. This document defines the safe operating boundaries,
validation procedure, and staged rollout sequence for production.

---

## Environment Variables

All scenario flags are read from environment variables via `app/config.py`.
The safe production default for every flag is given below.

| Variable | Safe Default | Purpose |
|---|---|---|
| `SCENARIO_BUILD_ENABLED` | `false` | Master gate for the seed builder + storage pipeline |
| `SCENARIO_SCORING_ENABLED` | `false` | Gate for scenario confidence scoring + plausibility band computation |
| `SCENARIO_DELIVERY_ENABLED` | `false` | Gate for live delivery to any user-facing channel |
| `SCENARIO_SHADOW` | `true` | When true and scoring is enabled, transitions are journaled to `delivery_ledger` as `channel=scenario_shadow` (inert) |
| `SCENARIO_TARGETS_ENABLED` | `""` (empty) | Comma-separated list of entity keys targeted for scenario build; empty = no targets |
| `SCENARIO_CALIBRATION_ENABLED` | `false` | Gate for calibration_outcome run_log rows |

**Rule:** `SCENARIO_DELIVERY_ENABLED=false` must be maintained throughout
all Phase 14 shadow validation. Enabling it before acceptance criteria are
met violates the SP-6 boundary.

---

## Safe Defaults

The following flag combination is the **inert production baseline**.
No user-visible change occurs with these settings:

```
SCENARIO_BUILD_ENABLED=false
SCENARIO_SCORING_ENABLED=false
SCENARIO_DELIVERY_ENABLED=false
SCENARIO_SHADOW=true
SCENARIO_TARGETS_ENABLED=
SCENARIO_CALIBRATION_ENABLED=false
```

All six `/admin/scenario-status` `safe_state` sub-checks must be `true`
when these defaults are in effect.

---

## Validation Commands

### 1. Shadow validation script (offline)

Runs entirely from Python imports — no live DB or server needed:

```bash
python tests/validate_14_scenario_shadow.py
```

Expected: `Results: N/N passed — all checks passed`

### 2. pytest — Phase 14 service tests only

```bash
python -m pytest \
  tests/test_services/test_scenario_calibration_service.py \
  tests/test_services/test_scenario_delivery_service.py \
  tests/test_services/test_scenario_explainability_service.py \
  tests/test_services/test_scenario_observability_service.py \
  tests/test_services/test_scenario_portfolio_propagation.py \
  tests/test_services/test_scenario_propagation_engine.py \
  tests/test_services/test_scenario_read_service.py \
  tests/test_services/test_scenario_schema.py \
  tests/test_services/test_scenario_seed_builder.py \
  -q
```

Expected: all passing, zero failures.

### 3. Admin status probe (server running)

```bash
curl -s http://localhost:8000/admin/scenario-status | python3 -m json.tool
```

Expected: `safe_state.overall = true`, all six sub-checks `true`,
`live_notification_count = 0`.

---

## Internal Probe Procedure

When the server is running against a live DB, execute the following sequence
to confirm the Phase 14 boundary is intact before any flag change:

1. **Health check**
   ```
   GET /health
   ```
   Confirm 200 and the expected commit hash.

2. **Scenario status snapshot**
   ```
   GET /admin/scenario-status
   ```
   Capture the full JSON. Confirm:
   - `db_available: true`
   - `safe_state.overall: true`
   - `safe_state.shadow_delivery_only: true`
   - `safe_state.no_live_notifications: true`
   - `metrics.live_notification_count: 0`
   - `flags.scenario_delivery_enabled: false`
   - `flags.scenario_build_enabled: false`

3. **No public scenario route**
   Confirm no route outside `/admin/` exposes scenario data.

4. **Audit log spot check**
   Confirm no `scenario_build` or `scenario_delivery` audit entries
   exist unless the corresponding flag was explicitly enabled.

---

## Rollout Stages

### Stage 0 — Shadow Baseline (current)

All flags off. Services deployed but fully inert.
Validation: `validate_14_scenario_shadow.py` exit 0.

### Stage 1 — Build Gate Only

```
SCENARIO_BUILD_ENABLED=true
SCENARIO_TARGETS_ENABLED=<one test ticker>
```

Scenario seeds generated and stored for the target ticker.
`scenario_snapshot` rows appear; no scoring, no delivery.
Validation: `/admin/scenario-status` shows `metrics.scenario_snapshot_count > 0`,
`safe_state.overall` still true.

### Stage 2 — Shadow Scoring

```
SCENARIO_BUILD_ENABLED=true
SCENARIO_SCORING_ENABLED=true
SCENARIO_SHADOW=true
SCENARIO_DELIVERY_ENABLED=false
```

Transitions detected and journaled to `delivery_ledger`
(`channel=scenario_shadow`, `status=pending`).
No user-visible change. No Notification rows created.
Validation: `metrics.shadow_delivery_count > 0`,
`metrics.live_notification_count = 0`,
`safe_state.no_live_notifications = true`.

### Stage 3 — Calibration Enabled

```
SCENARIO_CALIBRATION_ENABLED=true
```

Calibration outcome rows appended to `scenario_run_log`.
`metrics.latest_calibration_timestamp` becomes non-null.
Hit rate and churn metrics become available.

### Stage 4 — Live Delivery (post Phase 14 acceptance)

```
SCENARIO_DELIVERY_ENABLED=true
```

**Requires:** All acceptance criteria below met. Must not be set
during Phase 14 shadow validation.

---

## Rollback

To return to Stage 0 inert state from any stage:

```bash
# In environment / Render dashboard:
SCENARIO_BUILD_ENABLED=false
SCENARIO_SCORING_ENABLED=false
SCENARIO_DELIVERY_ENABLED=false
SCENARIO_CALIBRATION_ENABLED=false
SCENARIO_TARGETS_ENABLED=
# SCENARIO_SHADOW remains true
```

No data migration needed. Existing `scenario_snapshot` rows expire
naturally via `expires_at` (72-hour TTL).
Existing `delivery_ledger` rows with `channel=scenario_shadow` remain
inert — there is no registered consumer for that channel.

---

## Safety Boundaries

### SP-6: No-Advice Boundary

Scenario output **must never**:
- Assert a target price for any asset
- Recommend buying, selling, or any other action
- Size or advise on a position
- Predict an outcome or return

Scenario output **may**:
- Describe a conditional structural situation
- Describe how an outcome would propagate if it occurred
- Report plausibility bands and confidence as structural metadata

Enforced by:
1. `_BANNED_PHRASES` list scanned by AST tests in every slice
2. No `conviction`, `order_service`, `execution_service`, or `stance`
   import in any scenario service
3. `validate_14_scenario_shadow.py` checks 5–9

### SP-6: No-Conviction Boundary

Scenario output **must not flow back** into `conviction_service` or any
table that influences the conviction layer (`convictions`, `thesis_versions`,
`thesis_deltas`).

Enforced by:
- `SCENARIO_SCORING_ENABLED=false` (default) keeps the scoring path idle
- AST check: no `conviction_service` import in scenario services

### SP-6: No-Forecast-Write Boundary

No scenario service writes to `forecast_vector` or `forecast_evidence`.
The scenario layer reads from the intelligence substrate; it does not mutate it.

Enforced by:
- `validate_14_scenario_shadow.py` check 7 (no `add_forecast` pattern)
- `SCENARIO_BUILD_ENABLED=false` default keeps the build pipeline idle

### SP-6: No-Decision-Write Boundary

No scenario service writes to `decision_priority` or `decision_evidence`.

Enforced by:
- `validate_14_scenario_shadow.py` check 8 (no `add_decision` pattern)

---

## Acceptance Criteria

Phase 14 shadow validation is **complete** when all of the following hold:

- [ ] `validate_14_scenario_shadow.py` exits 0 with all checks passing
- [ ] All Phase 14 pytest suites pass (≥ 527 tests)
- [ ] `/admin/scenario-status` returns `safe_state.overall: true`
- [ ] `metrics.live_notification_count = 0` in production
- [ ] `metrics.shadow_delivery_count` increments only when
      `SCENARIO_SCORING_ENABLED=true` is set in a controlled test window
- [ ] No `conviction`, `order_service`, `execution_service`, or `stance`
      import exists in any scenario service (confirmed by AST scan)
- [ ] No `add_forecast`, `add_decision`, or `upsert_snapshot` call exists
      in any scenario service (confirmed by AST scan)
- [ ] No target price, buy/sell/hold, or recommendation language appears
      in any scenario service string constant (confirmed by AST scan)
- [ ] `SCENARIO_DELIVERY_ENABLED=false` throughout the entire validation window

Only after all criteria are met may `SCENARIO_DELIVERY_ENABLED=true`
be considered for a subsequent release.

---

## Related Files

| File | Purpose |
|---|---|
| `app/services/scenario_seed_builder.py` | Slice 14.2 — seed generation |
| `app/services/scenario_propagation_engine.py` | Slice 14.3 — propagation |
| `app/services/scenario_explainability_service.py` | Slice 14.4 — explainability |
| `app/services/scenario_storage_pipeline.py` | Slice 14.5 — storage |
| `app/services/scenario_read_service.py` | Slice 14.6 — read / status |
| `app/services/scenario_portfolio_propagation.py` | Slice 14.7 — portfolio context |
| `app/services/scenario_delivery_service.py` | Slice 14.8 — shadow delivery |
| `app/services/scenario_calibration_service.py` | Slice 14.9 — calibration |
| `app/services/scenario_observability_service.py` | Slice 14.10 — observability |
| `tests/validate_14_scenario_shadow.py` | Offline shadow validation script |
