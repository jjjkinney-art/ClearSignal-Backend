# Watchlist Duplicate Cleanup — Executor (Section 0.8D)

Deactivates duplicate active watchlist memberships that a Section 0.8C
rehearsal identified and an operator approved. **It never deletes a row.**

Read `docs/WATCHLIST_CLEANUP_REHEARSAL.md` first — the rehearsal produces the
fingerprint this tool demands, and defines the selection rules it reuses.

## Reuse, not reimplementation

The plan, ranking, partitioning, ordering and fingerprint all come from the
0.8C module, imported and executed verbatim:

```python
R = _rehearsal()                     # scripts/watchlist_duplicate_cleanup_rehearsal.py
plan = await R.build_plan(session)
actual = R.plan_fingerprint(plan)
```

A test asserts the executor contains no `row_number` or `partition_by` of its
own and that `X.R.build_plan is R.build_plan`. The executor cannot drift from
the artifact that was approved.

## Three independent gates

Execution requires **all** of:

1. `--execute` — absent, it refuses and exits 3;
2. all nine aggregate expectations, supplied explicitly;
3. `--approved-fingerprint` — the exact 64-character hex digest from the
   approved rehearsal.

**None is hard-coded.** Tests assert the approved fingerprint and the counts
`1155` / `1031` / `124` appear nowhere in source, so the script cannot be run
against a plan nobody approved.

## One transaction, in this order

```
 1  BEGIN
 2  LOCK TABLE watched_tickers IN SHARE ROW EXCLUSIVE MODE
 3  build the plan                       (0.8C, verbatim)
 4  verify all nine expectations
 5  recompute the fingerprint, require an EXACT match
 6  write the audit trail                (one row per candidate + run marker)
 7  UPDATE ... SET active = false WHERE id IN (candidates)
 8  assert affected rowcount == candidate count
 9  recompute aggregates, validate every postcondition
10  COMMIT  — only if 6, 7, 8 and 9 all succeeded
```

**The lock is taken before the plan is computed.** That is the whole point: the
row set cannot change between the fingerprint check and the `UPDATE`.
`SHARE ROW EXCLUSIVE` blocks concurrent writers and other lock holders but not
plain `SELECT`, so the product stays readable while cleanup runs.

**PostgreSQL only — no degraded path.** The rehearsal may fall back to a no-op
on other dialects because it only reads. A *mutating* executor may not: its
correctness depends on holding the lock, so any dialect that cannot take one is
refused outright rather than silently proceeding unlocked. Dialect-detection
failure is refused for the same reason — not knowing whether the lock was taken
is indistinguishable from not taking it. The refusal happens before plan
selection, before any audit row and before any DML, so a refused run leaves the
database completely untouched. Test fixtures may still use SQLite, but they go
*through* the guard with a simulated dialect rather than around it.

## Rollback and the future unique indexes — ordering constraint

Rollback **recreates the duplicates by design**. Once Phase C's two partial
unique indexes exist, reactivating those rows violates
`uq_watched_tickers_owner_ticker_active`, and the `UPDATE` fails.

**Rollback after Phase C therefore requires dropping the indexes first**, then
restoring, then re-running cleanup and re-creating them. `rollback_operation`
does not hide this: the integrity error surfaces and the operator must make
that call deliberately. A test creates the same partial index in a throwaway
fixture and proves the rollback is rejected while it exists.

Rollback is also **atomic and fail-closed**: every audited row must be restored
or the caller must roll back. `rollback_operation` asserts the affected count
equals the audited count and raises `rollback_row_count_mismatch` otherwise — a
partial restoration would leave the watchlist in a state neither the cleanup
nor the rollback describes. It is deliberately **not exposed through the CLI**;
rollback is its own approval.

Any mismatch or exception rolls the whole transaction back. **A partial cleanup
is never committed.**

## Postconditions

| field | required |
|---|---|
| active rows | `== retained_active_rows` from the verified plan |
| distinct tickers | `== projected_distinct_ticker_count_after` |
| active owners | `== projected_active_owner_count_after` |
| membership duplicate groups / candidates | `== 0` |
| legacy duplicate groups / candidates | `== 0` |
| orphan owners | **unchanged** |
| orphan active rows | **must not grow** |

Two of these deserve explanation. `orphan_owner_count` must not change at all:
every group retains one row, so cleanup can never orphan an owner. But
`orphan_active_row_count` counts *active* rows, so it legitimately **shrinks**
when duplicates are deactivated — requiring equality there would be wrong, and
the invariant that actually matters is that cleanup cannot manufacture a new
unowned active row.

## Audit must not fail open

The audit write deliberately does **not** reuse
`account_import_service._audit`, which swallows exceptions so that audit
failures never block a user action. That trade-off is right for a user action
and wrong here: **a cleanup whose rollback record failed to write must not
commit.** Exceptions propagate, and `write_audit` contains no exception handler
at all — asserted against tokenized code, because mutation testing showed a
prose-only guarantee is worthless here.

## Rollback

Each deactivated row is recorded as one `audit_log` row:

```
resource    = "watched_ticker"
action      = "dedupe"
resource_id = "<operation_ref>:<row_id>"
```

plus one run marker (`resource="watchlist_dedupe_run"`, `resource_id=<op ref>`).

The compound `resource_id` keeps the correlation inside the column that already
means *identifier*, rather than repurposing `user_agent` — an HTTP field — as a
batch key. `resource_id` is `VARCHAR(200)`; a 32-char operation reference plus
a 36-char row id needs 69.

**The opaque operation reference alone recovers exactly this run's rows.**
`audited_row_ids(session, operation_ref)` returns them; row identities never
appear in output. Reactivation is then a scoped `UPDATE ... SET active = true`
over precisely those ids. Tests prove that pre-existing inactive history is not
attributed to the run, and that two operations never share a rollback scope.

**Known limitation:** `audit_log` has no indexes at all, so recovery is a scan
with a `LIKE` prefix. Acceptable for a one-off operator action; worth an index
if this ever becomes routine.

## Replay safety

A second execution with the same approved fingerprint **fails closed**: once the
duplicates are gone the plan differs, so the fingerprint no longer matches and
verification aborts before any write. Tested.

## Not included

* No migration and **neither partial unique index** — those remain a separate,
  later, separately approved step, and must come *after* cleanup.
* No endpoint, no scheduling, no configuration change.
* No production connection is made by this branch.

## Usage

```bash
DATABASE_URL=... python3 scripts/watchlist_duplicate_cleanup_execute.py \
  --execute \
  --approved-fingerprint <64-hex from the approved rehearsal> \
  --expect-active-rows <n> --expect-distinct-tickers <n> \
  --expect-active-owners <n> --expect-membership-duplicate-groups <n> \
  --expect-membership-candidate-rows <n> --expect-legacy-duplicate-groups <n> \
  --expect-legacy-candidate-rows <n> --expect-orphan-owners <n> \
  --expect-orphan-rows <n>
```

Take a fresh rehearsal immediately beforehand and pass what it actually
reports. Expectations copied from an older run are exactly what the fingerprint
check exists to reject.

| exit | meaning |
|---|---|
| 0 | committed, every postcondition verified |
| 2 | verification failed — nothing written |
| 3 | usage / guard error (`--execute`, fingerprint or expectation missing) |
| 4 | database unavailable, or the transaction was rolled back |
