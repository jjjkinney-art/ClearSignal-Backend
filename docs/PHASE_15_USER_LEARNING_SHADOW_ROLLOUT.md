# Phase 15 — User Learning & Personalization: Shadow Rollout

## Status

Shadow mode only. No user-visible personalization. All flags default to off.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LEARNING_CAPTURE_ENABLED` | `false` | Enable signal capture from user interactions |
| `LEARNING_INFERENCE_ENABLED` | `false` | Enable preference inference from captured signals |
| `LEARNING_RELEVANCE_ENABLED` | `false` | Enable relevance adjustments (shadow projection only) |
| `LEARNING_SHADOW` | `true` | Keep all output in shadow mode — no live delivery |
| `LEARNING_TARGETS_ENABLED` | `""` | Comma-separated list of enabled personalization targets (empty = none) |
| `LEARNING_CALIBRATION_ENABLED` | `false` | Enable preference calibration metrics collection |

**Safe production defaults: all flags `false` except `LEARNING_SHADOW=true`.**

---

## Safe Defaults

The system is safe when:

- `LEARNING_RELEVANCE_ENABLED=false` — no feed reordering reaches users
- `LEARNING_SHADOW=true` — all writes land in `relevance_adjustment_log` only
- `LEARNING_TARGETS_ENABLED=""` — no downstream consumer reads learning output
- `LEARNING_CAPTURE_ENABLED=false` — no signals are being collected

At these defaults, Phase 15 is fully inert. The tables exist and are empty.
No user experience is affected.

---

## Validation Commands

```bash
# Full shadow validation (must exit 0 before any flag change)
python tests/validate_15_user_learning_shadow.py

# Live admin probe (requires running backend)
curl -s https://<backend-url>/admin/user-learning-status | python3 -m json.tool

# Unit + integration test suite
pytest tests/test_services/test_user_learning_schema.py \
       tests/test_services/test_user_learning_repo.py \
       tests/test_services/test_user_learning_explainability_service.py \
       tests/test_services/test_user_learning_inference_service.py \
       tests/test_services/test_user_learning_decay_service.py \
       tests/test_services/test_user_learning_profile_service.py \
       tests/test_services/test_user_learning_relevance_service.py \
       tests/test_services/test_user_learning_shadow_service.py \
       tests/test_services/test_user_learning_calibration_service.py \
       tests/test_services/test_user_learning_observability_service.py \
       -q
```

---

## Internal Probe Procedure

1. Deploy with all defaults (all flags off, `LEARNING_SHADOW=true`).
2. Run `python tests/validate_15_user_learning_shadow.py` — must exit 0.
3. Probe the admin endpoint:
   ```
   GET /admin/user-learning-status
   ```
   Confirm:
   - `safe_state.overall = true`
   - `safe_state.no_live_personalization = true`
   - `flags.learning_relevance_enabled = false`
   - `flags.learning_shadow = true`
   - `db_available = true`
   - All metric counts reflect current table state (0 if tables are empty)
4. Confirm no `Notification` rows referencing learning/personalization exist.
5. Confirm `relevance_adjustment_log` count is 0 or reflects only pre-existing test data.

---

## Rollout Stages

### Stage 1 — Signal Capture (internal traffic only)

Enable on a single internal user account to verify signal event recording.

```
LEARNING_CAPTURE_ENABLED=true
LEARNING_INFERENCE_ENABLED=false
LEARNING_SHADOW=true
```

Verify:
- `user_signal_event_count` increases in `/admin/user-learning-status`
- No `learned_preference` rows are created (inference still off)
- `safe_state.overall` remains `true`

### Stage 2 — Inference (shadow, no delivery)

Enable inference to build preference profiles from captured signals.

```
LEARNING_CAPTURE_ENABLED=true
LEARNING_INFERENCE_ENABLED=true
LEARNING_SHADOW=true
LEARNING_RELEVANCE_ENABLED=false
```

Verify:
- `learned_preference_count` grows over time
- `preference_count_by_dimension` shows distribution across dimensions
- No `relevance_adjustment_log` entries with `run_reason != "shadow"`
- `safe_state.no_live_personalization = true` (relevance still off)

### Stage 3 — Relevance projection (shadow journal only)

Enable the relevance engine to compute and journal how feeds *would* change.

```
LEARNING_CAPTURE_ENABLED=true
LEARNING_INFERENCE_ENABLED=true
LEARNING_RELEVANCE_ENABLED=true   ← gates on, but shadow=true
LEARNING_SHADOW=true
```

Verify:
- `shadow_adjustment_count` increases in the log
- `safe_state.shadow_only = true` (relevance on but shadow=true)
- `safe_state.no_live_personalization` may be `false` here — this is expected;
  confirm no actual feed reordering reaches user-facing endpoints
- No `Notification` rows

### Stage 4 — Calibration

Enable calibration metrics collection (append-only, shadow only).

```
LEARNING_CALIBRATION_ENABLED=true
```

Verify:
- `calibration_outcome_count` populates in the log
- `GET /admin/user-learning-status` shows calibration data

### Stage 5 — Live Delivery (future, requires SP-7 sign-off)

Not implemented in Phase 15. Requires separate sign-off and a new phase gate.
Setting `LEARNING_SHADOW=false` with `LEARNING_RELEVANCE_ENABLED=true` would
expose adjustments to users — this is not authorized in Phase 15.

---

## Rollback

At any stage, set all flags to their safe defaults:

```
LEARNING_CAPTURE_ENABLED=false
LEARNING_INFERENCE_ENABLED=false
LEARNING_RELEVANCE_ENABLED=false
LEARNING_SHADOW=true
LEARNING_TARGETS_ENABLED=
LEARNING_CALIBRATION_ENABLED=false
```

No data is deleted by rollback. The tables retain historical data for
post-incident analysis. Signal events and preferences are append-only;
they are not reversed. This is by design: behavioral history is immutable.

---

## SP-7 Boundary

SP-7 governs the interface between User Learning and every downstream consumer:

| SP-7 Sub-rule | Constraint |
|---|---|
| SP-7a | No write to truth tables: forecast_vector, similarity_score, scenario_snapshot, decisions, conviction |
| SP-7b | No import of forecast / decision / scenario / similarity write functions |
| SP-7c | No ranking mutation in the live path — all output is shadow observation only |
| SP-7d | Relevance floor: critical signal types (earnings, credit_downgrade, etc.) may be demoted but never muted below "normal" tier |
| SP-7f | No banned advisory phrases in any output string |
| SP-7h | No user-visible delivery via Notification rows |

These constraints are enforced structurally (import gates), verified by AST
checks in the test suite, and confirmed by the shadow validation script.

---

## No-Truth-Mutation Boundary

Phase 15 services write only to:
- `user_signal_event` (append-only)
- `learned_preference` (upsert, keyed on user/dimension/entity)
- `preference_evidence` (append-only)
- `relevance_adjustment_log` (append-only, run_reason = "shadow" or "calibration")

Phase 15 services never write to:
- `forecast_vector`
- `similarity_score`
- `scenario_snapshot` / `scenario_evidence` / `scenario_run_log`
- `decisions` / `decision_evidence`
- `conviction` (any form)
- `notification`
- `delivery_ledger`

---

## No-Advice Boundary

No Phase 15 output contains investment guidance. Specifically:

- No "buy", "sell", "hold", "overweight", "underweight" language
- No target price fields
- No position size or sizing guidance
- No conviction or stance fields
- No recommendation consumers wired to `learning_targets_enabled`

The disclaimer field in every `/admin/user-learning-status` response confirms
this: *"No investment guidance, conviction, or advice is produced."*

---

## No-Relevance-Live-Delivery Boundary

`LEARNING_RELEVANCE_ENABLED=true` activates only the shadow projection path:

1. `build_relevance_projection` computes how a feed *would* be re-ranked
2. `record_relevance_transition_events` journals the projection to
   `relevance_adjustment_log` with `run_reason="shadow"`
3. No public API endpoint exposes the projection
4. No `Notification` row is created
5. No feed endpoint reads from `relevance_adjustment_log` to reorder results

Live delivery requires `LEARNING_SHADOW=false` AND a separate Phase gate.
That gate does not exist in Phase 15.

---

## Acceptance Criteria

Phase 15 shadow validation passes when all of the following hold:

- [ ] `python tests/validate_15_user_learning_shadow.py` exits 0
- [ ] All Phase 15 unit tests pass (721 tests across 10 test files)
- [ ] `/admin/user-learning-status` returns `safe_state.overall = true`
- [ ] `/admin/user-learning-status` returns `db_available = true`
- [ ] No `Notification` rows exist with learning/personalization content
- [ ] `relevance_adjustment_log` contains only `run_reason IN ("shadow", "calibration")`
- [ ] No truth-table rows were modified by Phase 15 services
- [ ] All 6 learning flags are at safe defaults in the deployed environment
