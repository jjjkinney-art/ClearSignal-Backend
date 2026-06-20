# Phase 18 — Personal Experience Shadow Rollout

**Phase:** 18 · Personal Experience Layer
**Status:** Shadow mode — all flags at inert defaults
**Safety invariant family:** SP-18

---

## Flags

| Flag | Default | Purpose |
|---|---|---|
| `experience_change_detection_enabled` | `False` | Gate for change detection service |
| `experience_attention_enabled` | `False` | Gate for attention scoring service |
| `experience_composer_enabled` | `False` | Gate for experience composer |
| `experience_memory_enabled` | `False` | Gate for session continuity |
| `experience_shadow` | `True` | Shadow journaling (always on) |
| `experience_brief_enabled` | `False` | Gate for daily brief generation |

---

## Rollout Stages

### Stage 0 — Shadow Observation (current)

All flags at defaults. Phase 18 code is deployed but fully inert.

- Shadow journal records what *would* be surfaced
- No user-visible behavior
- No truth-table mutation
- Validation: `python tests/validate_18_personal_experience_shadow.py`
- Admin: `GET /admin/personal-experience-status`

**Exit criteria:**
- All validation checks pass
- safe_state.overall == true
- Shadow journal accumulating events without errors
- No truth-table writes detected

### Stage 1 — Change Detection

Enable: `experience_change_detection_enabled=True`

- Change candidates computed for all users
- Shadow journal captures change events
- No user-visible behavior

**Exit criteria:**
- Change candidates appearing in shadow journal
- No upstream table mutations
- Calibration: explainability_coverage > 0.8

### Stage 2 — Scoring + Composition

Enable: `experience_attention_enabled=True`, `experience_memory_enabled=True`

- Full scoring pipeline active
- Attention queue computed
- Session continuity active
- Still shadow-only

**Exit criteria:**
- Attention queue populated in shadow
- Ranking stability > 0.7
- Novelty reserve applied correctly

### Stage 3 — Brief Generation

Enable: `experience_brief_enabled=True`

- Daily briefs generated (shadow mode)
- Brief snapshots stored
- No delivery

**Exit criteria:**
- Briefs generating daily
- Brief validation passing
- Explainability gate blocking incomplete items

### Stage 4 — Composer Activation

Enable: `experience_composer_enabled=True`

- Full composition pipeline active
- All sections populated
- Still no live delivery (requires frontend integration)

**Exit criteria:**
- Compose pipeline end-to-end
- Attention accuracy > 0.6
- Resume accuracy > 0.5
- All calibration metrics with sufficient samples

### Stage 5 — Live Delivery

Enable: `experience_shadow=False` (only after all Stage 4 criteria met)

- Personalized experience delivered to users
- Requires frontend integration (not in Phase 18 scope)

**Exit criteria:**
- User engagement with surfaced items
- No negative impact on upstream metrics
- SP-18 boundary intact

---

## Rollback

Every stage is independently reversible:

- Set the flag back to its default value
- No data migration required
- Existing rows are inert (shadow journal, brief snapshots, cursors)
- `git revert` any slice without data consequences

Emergency rollback: set all flags to defaults (Stage 0).

---

## SP-18 Boundary

Phase 18 orchestrates intelligence — it never creates it.

| Rule | Constraint |
|---|---|
| SP-18a | No advisory language. All text is templated. |
| SP-18b | Ordering does not change truth. Scores are presentation-layer only. |
| SP-18c | Writes only to 3 Phase 18 tables: `personal_experience_cursor`, `personal_experience_event`, `personal_brief_snapshot`. |
| SP-18d | No upstream feedback. Reads from all upstream phases, writes nothing back. |

**Enforced by:**
- AST scans in every test suite (no banned phrases in string literals)
- Import firewalls (no truth-table write function imports)
- Mutation pattern scans (no `.update()`/`.delete()` on upstream models)
- Explainability gate (4-field requirement blocks incomplete items)
- Validation script (118+ checks)

---

## Acceptance Criteria

- [ ] All 10 slices committed and tested
- [ ] Cumulative test suite passing (426+ tests)
- [ ] Validation script: all checks pass
- [ ] Admin route: safe_state.overall == true
- [ ] Shadow journal accumulating events
- [ ] No truth-table writes
- [ ] No advisory language in any service
- [ ] No user-visible behavior change
- [ ] Rollback tested (flag toggle → inert)

---

## Admin Endpoint

`GET /admin/personal-experience-status`

Returns:
- `flags` — all 6 experience_* flags
- `metrics` — cursor_count, event_count, brief_count, shadow/calibration sub-counts
- `safe_state` — 6 sub-checks + overall
- `db_available` — boolean
- `schema_version` — 1
- `disclaimer` — shadow mode notice
