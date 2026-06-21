# Phase 19 — Visual Intelligence Shadow Rollout

**Phase:** 19 · Visual Intelligence Layer
**Status:** Shadow mode — all flags at inert defaults
**Safety invariant family:** SP-19

---

## Flags

| Flag | Default | Purpose |
|---|---|---|
| `visual_json_enabled` | `False` | Gate for Tier 1 structured JSON visual spec generation |
| `visual_svg_enabled` | `False` | Gate for Tier 2 server-side SVG rendering |
| `visual_ai_enabled` | `False` | Gate for Tier 3 AI-generated visual explanations |
| `visual_cache_enabled` | `False` | Gate for visual specification caching |
| `visual_shadow` | `True` | Shadow journaling (always on) |
| `visual_calibration_enabled` | `False` | Gate for calibration metrics computation |

---

## Rollout Stages

### Stage 0 — Shadow Observation (current)

All flags at defaults. Phase 19 code is deployed but fully inert.

- Shadow journal records what *would* be generated
- No user-visible behavior
- No truth-table mutation
- Validation: `python tests/validate_19_visual_intelligence_shadow.py`
- Admin: `GET /admin/visual-intelligence-status`

**Exit criteria:**
- All validation checks pass
- safe_state.overall == true
- Shadow journal accumulating events without errors
- No truth-table writes detected

### Stage 1 — Structured JSON

Enable: `visual_json_enabled=True`

- Tier 1 visual specs generated for market, forecast, portfolio, personal-experience visuals
- Shadow journal captures visual events
- Calibration: explainability_coverage > 0.9
- No user-visible behavior

**Exit criteria:**
- Specs generating without errors
- Explainability gate blocking incomplete visuals
- Generation latency p95 < 100ms

### Stage 2 — SVG Rendering

Enable: `visual_svg_enabled=True`

- Tier 2 SVGs generated for scenario, similarity, dependency, timeline visuals
- Still shadow-only

**Exit criteria:**
- SVGs generating < 500ms p95
- No advisory language in SVG text labels
- Blocked visual rate < 0.1

### Stage 3 — Caching

Enable: `visual_cache_enabled=True`

- Visual cache active
- Performance validation

**Exit criteria:**
- Cache hit rate > 0.5 after warm-up
- Cache invalidation on upstream data change verified

### Stage 4 — AI Generation

Enable: `visual_ai_enabled=True`

- AI visuals with post-generation safety validation
- Shadow-only — generated visuals logged but not served

**Exit criteria:**
- AI validation pass rate > 0.9
- No banned phrases detected in generated content
- Deterministic fallback operational on failure

### Stage 5 — Calibration

Enable: `visual_calibration_enabled=True`

- Calibration metrics computation active
- All 5 metrics with sufficient samples

**Exit criteria:**
- All calibration metrics reporting
- Sufficient samples for all metrics

### Stage 6 — Live Delivery

Enable: `visual_shadow=False` (only after all Stage 5 criteria met)

- Visuals delivered to users
- Requires frontend integration (not in Phase 19 scope)

**Exit criteria:**
- User engagement with visuals
- No negative impact on upstream metrics
- SP-19 boundary intact

---

## Rollback

Every stage is independently reversible:

- Set the flag back to its default value
- No data migration required
- Existing cache rows and journal entries are inert
- `git revert` any slice without data consequences

Emergency rollback: set all flags to defaults (Stage 0).

---

## Validation Procedure

### Automated

```bash
python tests/validate_19_visual_intelligence_shadow.py
```

All checks must pass.

### Admin Endpoint

```
GET /admin/visual-intelligence-status
```

Verify:
- `safe_state.overall == true`
- All 6 flags at expected values for the current stage
- `db_available == true`
- No unexpected event counts

### Test Suite

```bash
python -m pytest tests/test_services/ -k "visual or market_forecast or scenario_visual or similarity_visual or portfolio_visual or personal_visual or ai_visual" -q
```

All tests must pass (~306 tests).

---

## SP-19 Boundary

Phase 19 visualizes intelligence — it never creates it.

| Rule | Constraint |
|---|---|
| SP-19a | No advisory language. All visual text is templated. |
| SP-19b | Visualization does not change truth. Charts render data, not alter it. |
| SP-19c | Writes only to 3 Phase 19 tables: `visual_spec_cache`, `visual_experience_event`, `ai_visual_generation_log`. |
| SP-19d | No upstream feedback. Reads from all upstream phases, writes nothing back. |
| SP-19e | No directional arrows implying action. Edges are data relationships only. |
| SP-19f | AI-generated visuals undergo post-generation safety validation. |

**Enforced by:**
- AST scans in every test suite (no banned phrases in string literals)
- Import firewalls (no truth-table write function imports)
- Mutation pattern scans (no `.update()`/`.delete()` on upstream models)
- Explainability gate (3-field requirement blocks incomplete visuals)
- Post-generation OCR validation for AI visuals
- Validation script (80+ checks)
- No prompt text stored anywhere (prompt_hash only)

---

## Acceptance Criteria

- [ ] All 12 slices committed and tested
- [ ] Cumulative test suite passing (~306 tests)
- [ ] Validation script: all checks pass
- [ ] Admin route: safe_state.overall == true
- [ ] Shadow journal accumulating events
- [ ] No truth-table writes
- [ ] No advisory language in any service or template
- [ ] No user-visible behavior change
- [ ] Rollback tested (flag toggle → inert)
- [ ] AI visual prompts: no raw user text; no prompt text stored
- [ ] Post-generation safety validation operational
- [ ] Deterministic fallback for failed AI visuals

---

## Admin Endpoint

`GET /admin/visual-intelligence-status`

Returns:
- `flags` — all 6 visual_* flags
- `metrics` — cache_count, event_count, ai_log_count, shadow/calibration sub-counts
- `safe_state` — 6 sub-checks + overall
- `db_available` — boolean
- `schema_version` — 1
- `disclaimer` — shadow mode notice
