# Phase 11 Similarity Engine — Shadow Rollout

Status: **shadow-ready, not yet enabled anywhere.** This document covers how
to validate the Phase 11 similarity subsystem (Slices 1–8) in shadow mode,
both locally and in production, and what has to be true before it can move
toward an internal or canary rollout.

Phase 11 builds T1 (company), T2 (thesis), and T4 (failure-mode) similarity
feature vectors and T4 similarity edges, journals shadow-only delivery
transition events, and exposes everything through read-only admin routes.
**Nothing in Phase 11 is wired into a public route, the dossier UI,
forecasting, conviction, stance, verdict, or recommendation logic.**

---

## 1. Env vars

All four flags live in `app/config.py` (`Settings`) and can be set via the
environment or `.env`. Names below are the env var form (Pydantic
`BaseSettings` upper-cases the field name).

| Env var | Type | Default | Effect when `true` |
|---|---|---|---|
| `SIMILARITY_BUILD_ENABLED` | bool | `false` | Permits feature-vector builders to be called from an automated path (none exists yet — Slices 2/4 builders are always callable directly regardless of this flag; it governs future automatic invocation, e.g. a loop producer). |
| `SIMILARITY_SCORING_ENABLED` | bool | `false` | Permits the T4 scorer to run as part of `similarity_invalidation_service.rebuild_similarity_for_target/_for_ticker` without an explicit `run_scoring=True` override, and gates `similarity_delivery_service` transition journaling (see below). |
| `SIMILARITY_TARGETS_ENABLED` | string | `""` | Comma-separated allowlist of target_types considered "active" for future automatic rebuild scheduling. Empty means no target is automatically active. Not yet consulted by any scheduler (no Phase 11 loop producer exists). |
| `SIMILARITY_SHADOW` | bool | `true` | When all three of the above plus this flag are `true`, `similarity_delivery_service.record_similarity_transition_events` journals transition events into `delivery_ledger` under `channel="similarity_shadow"`. There is no live-delivery code path in Phase 11 at all — flipping this to `false` does **not** enable real delivery; it simply stops shadow journaling, since no Slice currently implements the live branch. |

**Safe defaults:** `false / false / "" / true`. With these defaults,
`similarity_observability_service.build_similarity_observability_snapshot()`
reports `safe_state: true` and every write path in Phase 11
(`similarity_delivery_service`, the dossier `similarity_context` enrichment)
degrades to its inert/empty form.

No Phase 11 flag has ever required a secret value — there is nothing here
analogous to `STRIPE_SECRET_KEY` or `SUPABASE_JWT_SECRET`.

---

## 2. Local validation

```bash
# From the project root
python tests/validate_11_similarity_shadow.py
```

Runs entirely against an in-memory SQLite DB (or `DATABASE_URL` if set) and
exits `0` on success, `1` on any failed check. Checks cover: schema
(`db_table_count >= 40`, both similarity tables exist), all 8 similarity
service modules import cleanly, all 4 flags are at their inert defaults,
no module imports forecasting/conviction/recommendation code (AST-based,
not a docstring substring match), no public (non-`/admin/`) route exposes
"similarity", both admin similarity routes are declared, `safe_state` is
`true` with and without a DB connection, zero `Notification` rows carry
`kind="similarity"`, zero `similarity_shadow` ledger rows have ever
escalated to `status="delivered"`, every `floor_passed` edge has
non-empty `contributions` and `disanalogy` (the orphan-score invariant),
and the validation probe itself mutates nothing.

Also run the full Phase 11 test suite:

```bash
python3 -m pytest tests/test_services/test_similarity_*.py -q
```

(152+ tests across Slices 1–7, plus the Slice 8 observability tests.)

---

## 3. Production shadow validation

```bash
DATABASE_URL=<production_postgres_url> python tests/validate_11_similarity_shadow.py
```

Then hit the read-only admin endpoint directly:

```bash
curl https://<backend-host>/admin/similarity-status
```

Expected response shape:

```json
{
  "flags": {
    "similarity_build_enabled": false,
    "similarity_scoring_enabled": false,
    "similarity_targets_enabled": "",
    "similarity_shadow": true
  },
  "db_available": true,
  "vector_counts": {"failure_mode": 0, "company": 0, "thesis": 0},
  "edge_counts": {"total": 0, "floor_passed": 0, "expired": 0},
  "edge_counts_by_target_type": {"failure_mode": 0, "company": 0, "thesis": 0},
  "shadow_delivery_count": 0,
  "shadow_escalated_count": 0,
  "live_notification_count": 0,
  "latest_vector_built_at": null,
  "latest_edge_scored_at": null,
  "safe_state": true,
  "snapshot_utc": "..."
}
```

In a freshly-deployed production environment, all counts should be `0` and
`safe_state` must be `true`. A nonzero `vector_counts`/`edge_counts` is
expected only after someone has manually run the builders/scorer (e.g. via
the internal probe procedure below) — that is not itself unsafe, since
nothing reads those rows except the admin routes and the (still-unused)
dossier enrichment wrapper.

---

## 4. Internal probe procedure

To manually exercise Phase 11 against real (or representative) data without
flipping any flag in production:

1. Connect a Python session/script to the target database (same pattern as
   `tests/validate_*` scripts — `create_async_engine(DATABASE_URL)`).
2. Call the Slice 2/4 builders directly for a specific ticker:
   `similarity_feature_builder.build_failure_mode_feature_vectors_for_ticker`,
   `build_company_feature_vector`, `build_thesis_feature_vectors_for_all`.
3. Call `similarity_scorer.build_failure_mode_similarity_edges(session, entity_key)`
   for each resulting T4 vector's `entity_key`.
4. Inspect results via `similarity_read_service.get_resembles_facet_for_ticker`
   or `GET /admin/similarity/{ticker}`.
5. Check `GET /admin/similarity-status` to confirm `safe_state` is still
   `true` and no unexpected `shadow_escalated_count`/`live_notification_count`.

This is exactly what the Phase 11 Internal Similarity Probe (run earlier in
this phase) exercised against synthetic data — see that probe's report for
an example of the score distribution and floor-pass-rate analysis this
procedure produces.

None of these steps require any flag change; they call the same service
functions the validation script and admin routes call.

---

## 5. Rollout sequence

Phase 11 has no live/canary delivery path implemented yet (by design —
explicitly out of scope through Slice 8). The sequence below describes how
flipping flags changes *behavior that already exists in code*, not a future
promise:

1. **Current state (shadow, default):** `build=false, scoring=false,
   targets="", shadow=true`. Builders/scorer are callable manually only.
   No automatic rebuild, no transition journaling, no dossier enrichment
   beyond the safe-empty block.
2. **Internal build-only:** flip `SIMILARITY_BUILD_ENABLED=true` once a
   Slice 9+ loop producer exists to call the builders automatically. No
   behavior change yet if no such producer exists (current state — this
   flag has no consumer yet beyond manual scripts).
3. **Internal scoring + shadow journaling:** flip
   `SIMILARITY_SCORING_ENABLED=true` (keeping `SIMILARITY_SHADOW=true`).
   `similarity_invalidation_service` rebuilds now auto-run the T4 scorer,
   and `similarity_delivery_service.record_similarity_transition_events`
   begins journaling transition events into `delivery_ledger` under
   `channel="similarity_shadow"` — still completely inert (no flush
   pipeline drains that channel, no Notification is ever created).
4. **Dossier enrichment opt-in:** a future caller (not present today) could
   invoke `dossier_similarity_enrichment.get_full_dossier_with_similarity_context`
   instead of the plain `get_full_dossier` to surface `similarity_context`
   — this is additive and read-only, but is still a UI-facing decision
   that needs its own sign-off; Phase 11 does not make this call for you.
5. **Internal/canary (out of scope for Phase 11):** would require a new
   slice that (a) defines a live-delivery branch in
   `similarity_delivery_service` analogous to `loop_delivery_service`'s
   shadow→live promotion, and (b) decides whether/how `similarity_context`
   is surfaced in a real dossier response. Neither exists today.

---

## 6. Rollback

Every step above is flag-gated and additive:

- Setting any of the three gating flags back to their defaults
  (`build=false`, `scoring=false`, or `shadow` back to `true` if it had
  been changed) immediately returns the corresponding code path to its
  inert/no-op branch. No code change is required.
- `similarity_feature_vector` and `similarity_edge` are pure caches —
  dropping or truncating them loses nothing but rebuild latency; nothing
  else in the system reads them except Phase 11's own read service and
  admin routes.
- `delivery_ledger` rows with `channel="similarity_shadow"` can be deleted
  freely; nothing downstream depends on their continued existence (no
  flush pipeline, no digest, no notification ever reads them).
- No migration needs to be reverted — Slice 1's migration only adds two
  new, independent tables (`IF NOT EXISTS`, no `ALTER` on any existing
  table). Rolling back code does not require rolling back schema.

---

## 7. No-forecast boundary

Enforced two ways:

1. **Structurally**, by construction: no `similarity_*` or
   `dossier_similarity_enrichment` module has ever imported anything from a
   forecasting, conviction-engine, or recommendation module across Slices
   1–8.
2. **Mechanically**, by `tests/validate_11_similarity_shadow.py` checks
   6–7, which AST-parse every similarity module's import statements and
   fail if any import name contains `forecast`, `conviction_engine`,
   `recommendation`, or `notification_service`. This is also covered by
   AST-based unit tests in `test_similarity_invalidation_service.py`,
   `test_similarity_read_service.py`, and `test_similarity_delivery_service.py`.

Similarity output (scores, contributions, disanalogy) is descriptive only —
it has no numeric or categorical path into stance, conviction,
`verdict_rationale`, or any catalyst/forecast field.

---

## 8. No-write-back boundary

Enforced at every Slice:

- Slice 1–2/4 builders only ever write to `similarity_feature_vector`,
  reading `dossier_failure_mode`, `historical_analogs`, `company_dossier`,
  `cross_exposures`, `dossier_core_debate`, `dossier_moat_dimension`,
  `dossier_durability`, `thesis_versions`, `dossier_variant`.
- Slice 3's scorer only ever writes to `similarity_edge`, reading
  `similarity_feature_vector`.
- Slice 5's invalidation/rebuild service only calls the Slice 2/4/3
  functions above — it has no direct write path of its own.
- Slice 6's read service is read-only by construction (no upsert/insert
  call anywhere in the module).
- Slice 7's delivery service only writes to the pre-existing
  `delivery_ledger` table (via the pre-existing
  `loop_idempotency_service.guard_delivery`) — never to any similarity or
  dossier source table. The dossier enrichment wrapper never writes
  anything; it only reads `get_full_dossier()` and the Slice 6 read
  service.
- Slice 8's observability service is read-only (counts and `MAX()`
  timestamps only).

Every slice's test suite includes an explicit no-write-back test that
snapshots the relevant source tables before/after the operation under test
and asserts byte-for-byte equality. `tests/validate_11_similarity_shadow.py`
check 14 repeats this at the validation-script level for `similarity_edge`
and `notifications` around the observability snapshot call itself.

---

## 9. Acceptance criteria for moving toward internal/canary

Before any future slice proposes a live-delivery or UI-surfaced rollout,
all of the following must hold:

1. `tests/validate_11_similarity_shadow.py` exits `0` in production.
2. `GET /admin/similarity-status` reports `safe_state: true`,
   `shadow_escalated_count: 0`, `live_notification_count: 0`.
3. The full `tests/test_services/test_similarity_*.py` suite passes (all
   slices).
4. A documented internal probe (§4) has been run against representative
   or real tickers and the score distribution / floor-pass rate has been
   reviewed by a human — see the Phase 11 Internal Similarity Probe report
   for the expected shape of this review (cluster detection, false
   negatives from the mechanism-sibling map, floor-pass rate sanity).
5. A design decision has been made (and written down, not just implied)
   about exactly which UI surface would consume `similarity_context` or a
   live-delivery channel, with explicit sign-off that it remains
   descriptive-only and disclaimer-bearing at the point of display.
6. No flag flip in this document has, on its own, ever produced a
   `Notification` row or a public API response containing similarity data
   — confirmed by re-running the validation script after each flag change.
