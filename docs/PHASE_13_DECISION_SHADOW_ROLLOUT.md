# Phase 13 Decision Intelligence — Shadow Rollout Guide

Phase 13 adds a complete Decision Intelligence subsystem to the backend:
candidate builder, multi-dimension ranking engine, explainability layer,
portfolio-awareness, shadow delivery journaling, calibration, and observability.
All output is shadow-only and gated behind feature flags.  No decision output
is exposed to users, no conviction/stance/forecast write-back occurs, and no
recommendation language is present anywhere in the service graph.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DECISION_BUILD_ENABLED` | `false` | Gate for building decision candidates. Must be `false` in shadow mode. |
| `DECISION_SCORING_ENABLED` | `false` | Gate for scoring and ranking candidates. Must be `false` in shadow mode. |
| `DECISION_DELIVERY_ENABLED` | `false` | Gate for live delivery. **Must remain `false` throughout all shadow stages.** |
| `DECISION_SHADOW` | `true` | Shadow journal mode. Must be `true`. |
| `DECISION_TARGETS_ENABLED` | `""` | Comma-separated list of entity keys allowed in shadow scoring. Empty = all candidates are gated. |
| `DECISION_CALIBRATION_ENABLED` | `false` | Gate for calibration outcome recording. |

### Safe Defaults (deploy-day configuration)

```
DECISION_BUILD_ENABLED=false
DECISION_SCORING_ENABLED=false
DECISION_DELIVERY_ENABLED=false
DECISION_SHADOW=true
DECISION_TARGETS_ENABLED=
DECISION_CALIBRATION_ENABLED=false
```

No existing behavior changes when all gates are false.

---

## Safe State Definition

The system is in safe state when **all** of the following are true:

- `decision_shadow == true`
- `decision_delivery_enabled == false`
- `shadow_escalated_count == 0` (no shadow delivery row ever promoted)
- `live_notification_count == 0` (no `Notification` row with `kind LIKE "decision%"`)

Check safe state at any time:

```bash
curl -s "$BACKEND_URL/admin/decision-status" | python3 -m json.tool | grep safe_state
```

---

## SP-5 No-Advice Boundary

Decision output is not advice.  The SP-5 constraint is enforced at the source level:

- **No advice language.** The string constants `buy`, `sell`, `hold`, `target price`,
  `overweight`, `underweight`, `position size`, `enter a trade`, `exit a trade` do not
  appear in any decision service module (enforced by AST scan in the validation script).
- **No conviction coupling.** Decision services do not import `conviction_engine`,
  `conviction_modeler`, `recommendation`, `notification_service`, `stance_engine`,
  `order_engine`, or `execution_engine`.
- **No upstream flow-back.** Decision services do not import `forecast_repo`,
  `forecast_builder`, or `forecast_vector`.  Decision output does not mutate any source
  table (verified by the observability snapshot's no-mutation check).

---

## No-Conviction Boundary

- `decision_priority` rows carry no conviction, stance, or verdict fields.
- The ranking engine (`decision_ranking_engine.py`) produces `decision_rank_score`,
  `attention_score`, `urgency_score`, `impact_score` — all read-only signals.
- No decision path imports from `conviction_modeler` or any phase that produces
  conviction output.

---

## No-Forecast Write-Back Boundary

- `decision_observability_service.py` and `decision_calibration_service.py` are
  read-only with respect to all source tables.
- The calibration pipeline (`decision_calibration_service.py`) appends to
  `decision_ranking_log` only; it never writes to `decision_priority`,
  `decision_evidence`, `forecast_vector`, or any conviction/recommendation table.
- Enforced structurally: `decision_ranking_log` has no UPDATE or DELETE path — only
  `add_ranking_log()` (INSERT-only via `session.add()`).

---

## Validation Commands

### Full shadow validation (local / staging)

```bash
python tests/validate_13_decision_shadow.py
```

Runs 19 checks (DB schema, imports, flag defaults, AST hygiene, route exposure,
immutability, runtime safe_state, explainability invariants, ranking invariants,
calibration invariants).  Exits 0 on success.

### Against a production Postgres DB

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host/db \
  python tests/validate_13_decision_shadow.py
```

### Unit + integration test suite

```bash
pytest tests/test_services/test_decision_candidate_builder.py \
       tests/test_services/test_decision_ranking_engine.py \
       tests/test_services/test_decision_explainability_service.py \
       tests/test_services/test_decision_portfolio_service.py \
       tests/test_services/test_decision_delivery_service.py \
       tests/test_services/test_decision_calibration_service.py \
       tests/test_services/test_decision_observability_service.py \
       -v
```

---

## Admin Probe Procedure

Two admin endpoints are available.  Both require no auth token in development and
respect `AUTH_ENABLED` in production.

### Observability snapshot

```bash
curl -s "$BACKEND_URL/admin/decision-status" | python3 -m json.tool
```

Expected response shape (safe shadow mode):

```json
{
  "flags": {
    "decision_build_enabled": false,
    "decision_scoring_enabled": false,
    "decision_delivery_enabled": false,
    "decision_shadow": true,
    "decision_targets_enabled": "",
    "decision_calibration_enabled": false
  },
  "db_available": true,
  "priority_count": 0,
  "evidence_count": 0,
  "ranking_log_count": 0,
  "calibration_outcome_count": 0,
  "expired_priority_count": 0,
  "priority_count_by_bucket": {
    "critical": 0, "high": 0, "medium": 0, "low": 0, "informational": 0
  },
  "priority_count_by_type": {
    "forecast_candidate": 0,
    "risk_candidate": 0,
    "catalyst_candidate": 0,
    "watchlist_candidate": 0,
    "portfolio_exposure_candidate": 0,
    "delivery_transition_candidate": 0,
    "similarity_candidate": 0
  },
  "shadow_delivery_count": 0,
  "shadow_escalated_count": 0,
  "live_notification_count": 0,
  "latest_priority_at": null,
  "latest_calibration_at": null,
  "safe_state": true,
  "snapshot_utc": "..."
}
```

### Per-ticker decision read

```bash
curl -s "$BACKEND_URL/admin/decision/NVDA" | python3 -m json.tool
```

Returns the top decision priorities for the given ticker across all candidate types.
No conviction, stance, or recommendation fields appear in the response.

---

## Rollout Stages

### Stage 0 — Schema + services deployed, all gates off (current)

All Phase 13 tables exist.  All service modules are importable.  No flags are set.
No priority rows are built, no shadow journaling occurs.

**Acceptance criterion:** `python tests/validate_13_decision_shadow.py` exits 0.

### Stage 1 — Enable build for a single candidate type

```
DECISION_BUILD_ENABLED=true
DECISION_TARGETS_ENABLED=NVDA,AAPL
```

Candidate builder runs for the listed tickers.  `DECISION_SCORING_ENABLED` remains
false so no priority rows are written.

**Acceptance criterion:** `candidate_build_count > 0` visible in a debug log; no
decision rows in the DB; `safe_state == true`.

### Stage 2 — Enable scoring in shadow

```
DECISION_BUILD_ENABLED=true
DECISION_SCORING_ENABLED=true
DECISION_SHADOW=true
DECISION_DELIVERY_ENABLED=false
```

Priority rows begin appearing in `decision_priority`.  Shadow delivery journals
transitions to `delivery_ledger` (channel=`decision_shadow`, status=`pending`).

**Acceptance criterion:**
- `priority_count > 0` in observability snapshot
- `shadow_delivery_count > 0` (transitions journaled)
- `shadow_escalated_count == 0`
- `live_notification_count == 0`
- `safe_state == true`

### Stage 3 — Enable calibration

```
DECISION_CALIBRATION_ENABLED=true
```

Calibration outcomes can be recorded via `record_decision_outcome()`.  Log rows
appear in `decision_ranking_log` with `snapshot_reason = "calibration_outcome"`.

**Acceptance criterion:** `calibration_outcome_count > 0` when outcomes exist;
no change to any other safe_state component.

### Stage 4 — Full shadow evaluation (no gate change required)

Operate Stage 2 + 3 for a minimum of two market weeks.  Monitor:

- `priority_count_by_bucket` distribution (healthy: critical < 5% of total)
- `expired_priority_count` (healthy: < 20% of total; high values indicate TTL
  tuning is needed)
- `shadow_escalated_count` (must remain 0 — never promote)
- Calibration metrics via `/admin/decision-status`

### Stage 5 — NOT YET SCHEDULED

Live delivery (`DECISION_DELIVERY_ENABLED=true`) is out of scope for Phase 13.
It will be gated behind a separate rollout document and requires explicit sign-off
that the no-advice boundary has been reviewed by a product stakeholder.

---

## Rollback

To immediately return to a fully inert state, set:

```
DECISION_BUILD_ENABLED=false
DECISION_SCORING_ENABLED=false
DECISION_CALIBRATION_ENABLED=false
```

`DECISION_SHADOW` and `DECISION_DELIVERY_ENABLED` do not need to change.  Existing
`decision_priority` rows will expire on their TTL without any manual deletion.

To clear shadow journal entries (optional, non-destructive to source data):

```sql
DELETE FROM delivery_ledger WHERE channel = 'decision_shadow';
```

---

## Acceptance Criteria

Before any Stage advance, ALL of the following must hold:

- [ ] `python tests/validate_13_decision_shadow.py` exits 0
- [ ] `GET /admin/decision-status` returns `safe_state: true`
- [ ] `shadow_escalated_count == 0`
- [ ] `live_notification_count == 0`
- [ ] No `Notification` row exists with `kind LIKE 'decision%'`
- [ ] Full pytest suite (decision modules) passes with 0 failures
- [ ] No `buy`, `sell`, `hold`, `target price` string appears in any decision service source (validated by AST scan)
- [ ] No import of `conviction_engine`, `recommendation`, or `stance_engine` in any decision service (validated by AST scan)
- [ ] No decision service imports `forecast_repo`, `forecast_builder`, or `forecast_vector`

`DECISION_DELIVERY_ENABLED` must be `false` at all stages within Phase 13.
