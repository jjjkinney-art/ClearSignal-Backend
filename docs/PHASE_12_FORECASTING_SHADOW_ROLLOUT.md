# Phase 12 — Forecasting Engine Shadow Rollout

## Status: SHADOW ONLY — No live delivery, no user-visible behavior

Phase 12 builds the probabilistic forecast layer on top of the Phase 11 similarity engine. All forecast output is internal only. No forecast data reaches any user-facing route, email, notification, or conviction field during Phase 12.

---

## Environment Variables

| Variable | Safe Default | Notes |
|----------|-------------|-------|
| `FORECAST_BUILD_ENABLED` | `false` | Master gate for feature-vector builds |
| `FORECAST_SCORING_ENABLED` | `false` | Master gate for probability scoring |
| `FORECAST_DELIVERY_ENABLED` | `false` | Must remain `false` throughout Phase 12 |
| `FORECAST_SHADOW` | `true` | Shadow-journals transitions to `delivery_ledger` |
| `FORECAST_TARGETS_ENABLED` | `""` | Comma-separated allowlist of entity_types |
| `FORECAST_CALIBRATION_ENABLED` | `false` | Master gate for calibration outcome logging |

**Production invariants for Phase 12:**
- `FORECAST_DELIVERY_ENABLED=false` — never set this True in Phase 12
- `FORECAST_SHADOW=true` — always on; transition events journal inertly
- `FORECAST_BUILD_ENABLED` and `FORECAST_SCORING_ENABLED` may be toggled `true` once the shadow validation passes (see Rollout Stages below)

---

## Safe Defaults

The system is fully inert at all default values:

- No forecast_vector rows are built automatically
- No probability scores are computed automatically
- No delivery_ledger rows are written for forecast events
- No Notification rows are ever written for forecasts
- No forecast data influences conviction, stance, verdict_rationale, or any LLM prompt
- `GET /admin/forecast-status` returns `safe_state: true`

---

## Validation Commands

### Full shadow validation (local SQLite)
```bash
python tests/validate_12_forecasting_shadow.py
```

### Full shadow validation (production Postgres)
```bash
DATABASE_URL=postgresql+asyncpg://... python tests/validate_12_forecasting_shadow.py
```

### Phase 12 unit + integration tests
```bash
python -m pytest tests/test_services/test_forecast_schema.py \
                 tests/test_services/test_forecast_feature_builder.py \
                 tests/test_services/test_forecast_probability_engine.py \
                 tests/test_services/test_forecast_explainability.py \
                 tests/test_services/test_forecast_invalidation_service.py \
                 tests/test_services/test_forecast_read_service.py \
                 tests/test_services/test_forecast_delivery_service.py \
                 tests/test_services/test_forecast_calibration_service.py \
                 tests/test_services/test_forecast_observability_service.py \
                 -q
```

### Quick admin probe (requires running server)
```bash
curl -s https://<backend-host>/admin/forecast-status | python3 -m json.tool
```

---

## Internal Probe Procedure

Once the server is running (with defaults), hit:

```
GET /admin/forecast-status
```

Expected response shape:
```json
{
  "flags": {
    "forecast_build_enabled": false,
    "forecast_scoring_enabled": false,
    "forecast_delivery_enabled": false,
    "forecast_shadow": true,
    "forecast_targets_enabled": "",
    "forecast_calibration_enabled": false
  },
  "db_available": true,
  "vector_count": 0,
  "evidence_count": 0,
  "calibration_count": 0,
  "expired_vector_count": 0,
  "vector_count_by_type": { ... },
  "vector_count_by_horizon": { ... },
  "shadow_delivery_count": 0,
  "shadow_escalated_count": 0,
  "live_notification_count": 0,
  "latest_forecast_at": null,
  "latest_calibration_at": null,
  "safe_state": true,
  "snapshot_utc": "..."
}
```

**Acceptance gate:** `safe_state: true` and `live_notification_count: 0`.

---

## Rollout Stages

### Stage 0 — Shadow Validation (current)
- All flags at safe defaults (all `false` except `forecast_shadow: true`)
- Run `python tests/validate_12_forecasting_shadow.py` → must exit 0
- Check `GET /admin/forecast-status` → must return `safe_state: true`
- No user-visible changes

### Stage 1 — Enable Build + Scoring (internal only)
Prerequisites: Stage 0 complete, 2+ weeks of Phase 11 similarity data in DB.
```
FORECAST_BUILD_ENABLED=true
FORECAST_SCORING_ENABLED=true
FORECAST_TARGETS_ENABLED=company
```
- Forecast vectors begin building for company targets
- No delivery, no user exposure
- Monitor: `vector_count`, `evidence_count` grow in `/admin/forecast-status`
- Acceptance: `vector_count > 0`, `safe_state: true`

### Stage 2 — Enable Shadow Delivery
Prerequisites: Stage 1 complete, ≥ 50 vectors built, calibration baseline established.
```
FORECAST_BUILD_ENABLED=true
FORECAST_SCORING_ENABLED=true
FORECAST_TARGETS_ENABLED=company
FORECAST_SHADOW=true          # already true by default
```
Note: Shadow delivery (journaling to `delivery_ledger(channel="forecast_shadow")`) is
already active when both build and scoring are enabled. This stage confirms transitions
are being journaled correctly without escalating to "delivered".
- Monitor: `shadow_delivery_count` grows, `shadow_escalated_count` stays 0
- Acceptance: `shadow_escalated_count: 0`, `live_notification_count: 0`

### Stage 3 — Enable Calibration
Prerequisites: Stage 2 complete, ≥ 30 days of forecast vectors.
```
FORECAST_CALIBRATION_ENABLED=true
```
- Calibration outcomes can now be logged via `record_forecast_outcome()`
- Monitor: `calibration_count` grows, Brier scores available via `summarize_calibration()`
- Acceptance: `calibration_count > 0`, `mean_brier_score` < 0.25

### Stage 4 — Phase 13 (future)
- Live delivery to users via the Notification table
- Requires `FORECAST_DELIVERY_ENABLED=true`
- **Not implemented in Phase 12 — do not set this flag True before Phase 13**

---

## Rollback

If any validation check fails or unexpected behavior is observed:

1. Set all `FORECAST_*` flags back to safe defaults:
   ```
   FORECAST_BUILD_ENABLED=false
   FORECAST_SCORING_ENABLED=false
   FORECAST_DELIVERY_ENABLED=false
   FORECAST_SHADOW=true
   FORECAST_TARGETS_ENABLED=
   FORECAST_CALIBRATION_ENABLED=false
   ```
2. Restart the backend.
3. Verify `GET /admin/forecast-status` returns `safe_state: true`.
4. The DB tables retain their data — no data loss from flag rollback.
5. To clear all forecast data: `DELETE FROM forecast_vector;` cascades to `forecast_evidence` via FK.
   Calibration data is independent — `DELETE FROM forecast_calibration_log;` if needed.

---

## Calibration Interpretation

The Brier score measures probabilistic forecast accuracy:
- **0.0** — perfect calibration (predicted probability matched outcome exactly)
- **0.25** — random guessing (equivalent to always predicting 0.5)
- **1.0** — worst possible calibration

Benchmark thresholds:
| Score | Interpretation |
|-------|---------------|
| < 0.10 | Excellent |
| 0.10–0.20 | Good |
| 0.20–0.25 | Acceptable (near random) |
| > 0.25 | Poor — investigate feature quality |

Drift detection window (default 30 days):
- `improving` — recent Brier improved by > 0.05 vs prior window
- `worsening` — recent Brier worsened by > 0.05 vs prior window
- `stable` — change within ±0.05
- `insufficient_samples` — fewer than 5 rows in either window

---

## No-Advice Boundary

**Phase 12 forecasts are descriptive probability distributions — not investment advice.**

All forecast output must include the mandatory disclaimer verbatim:

> "Forecasts are probabilistic estimates for internal analytical use only. They are not investment advice, do not constitute a recommendation to buy, sell, or hold any security, and must not be construed as such."

This disclaimer is embedded in `forecast_constants.MANDATORY_DISCLAIMER` and is emitted by `get_forecast_facet_for_ticker()` on every response including empty-state responses.

**Enforcement:**
- `validate_forecast_explanation()` rejects any explanation containing banned language: "buy", "sell", "hold", "target price", "recommend", "overweight", "underweight".
- AST tests in `test_forecast_calibration_service.py` and `test_forecast_observability_service.py` verify no such strings appear in service code.
- The validation script (`validate_12_forecasting_shadow.py`) checks all 10 Phase 12 service modules.

---

## No-Forecast-to-Conviction Boundary (SP-4)

**Forecast output must never influence conviction, stance, verdict_rationale, or any LLM prompt.**

This is enforced structurally:
- No Phase 12 forecast service imports any conviction/stance/LLM-prompt module.
- No thesis generation or synthesis pipeline imports any forecast service.
- The `forecast_vector` and `forecast_evidence` tables have no FK to `thesis_versions`, `company_dossier`, or any other conviction-related table.
- Calibration log rows reference `forecast_id` (soft FK, string only) — no conviction coupling.

The import-graph check in `validate_12_forecasting_shadow.py` (Check 7) verifies this statically on every deployment. Any import of `conviction_engine`, `recommendation`, `notification_service`, or `stance_engine` in any forecast module is a hard FAIL.

---

## Acceptance Criteria

Phase 12 is ready for Phase 13 planning when ALL of the following are met:

- [ ] `python tests/validate_12_forecasting_shadow.py` exits 0 in production
- [ ] `GET /admin/forecast-status` returns `safe_state: true` in production
- [ ] All 701 Phase 12 unit tests pass (`pytest tests/test_services/test_forecast_*.py`)
- [ ] `vector_count > 0` after enabling Stage 1 flags for 24+ hours
- [ ] `shadow_escalated_count == 0` after 7+ days of shadow operation
- [ ] `live_notification_count == 0` at all times
- [ ] At least 10 calibration outcomes recorded with `mean_brier_score < 0.25`
- [ ] No forecast-related fields appear in any public API response (non-`/admin/` routes)
- [ ] Drift trend is `stable` or `improving` over the most recent 30-day window
