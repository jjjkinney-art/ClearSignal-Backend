# Watchlist Duplicate Cleanup — Rehearsal (Section 0.8C)

**Status: DRY RUN ONLY. This tool authorises nothing and changes nothing.**

`scripts/watchlist_duplicate_cleanup_rehearsal.py` reports what a future
cleanup *would* do to duplicate active watchlist memberships. It is
structurally incapable of mutating the database:

* there is no `--execute` / `--apply` / `--cleanup` / `--commit` / `--force`
  flag, and a test interrogates the real argument parser to prove it;
* the executable body contains no `INSERT`, `UPDATE`, `DELETE`, `session.add`,
  `commit`, `flush` or audit-write path — only `SELECT`;
* on PostgreSQL it opens an explicitly `READ ONLY` transaction;
* a test wraps the session and fails if any write method is touched.

No API route or admin endpoint is added. Nothing is scheduled. It is an
operator CLI, run deliberately, by hand.

## Selection and retention rules

Active rows only. **Inactive rows are excluded entirely** and never interact
with active ones, so soft-deleted history is preserved untouched.

```
owned  namespace (user_id IS NOT NULL):
    ROW_NUMBER() OVER (PARTITION BY user_id, ticker
                       ORDER BY added_at ASC, id ASC)

legacy namespace (user_id IS NULL):
    ROW_NUMBER() OVER (PARTITION BY ticker
                       ORDER BY added_at ASC, id ASC)

rn = 1  ->  RETAINED
rn > 1  ->  CLEANUP CANDIDATE
```

* **The same ticker under two different non-null owners is never a duplicate.**
  The partition key includes the owner. This is the property that made the
  original "duplicate AAPL" report a false positive, and it is pinned by test.
* **No owner is assumed or hard-coded.** The system account is treated as an
  ordinary non-null owner. Groups are discovered from the database.
* The two namespaces are independent: a null-owner row can never join an owned
  partition, and vice versa.

### Ordering and null behaviour

The ordering mirrors `watchlist_repo._membership_stmt` exactly
(`added_at ASC, id ASC`), so the row this tool retains is the row the running
application already treats as authoritative through `_resolve_one`. Cleanup
therefore removes only redundancy, never the row in use.

`watched_tickers.added_at` and `id` are both **NOT NULL** in the schema, so
there is no `NULLS FIRST` / `NULLS LAST` ambiguity and no dialect-dependent
null ordering to reason about. `id` is a `VARCHAR(36)` uuid hex compared
lexicographically, which makes the tie-break **total and deterministic** even
when bulk-created rows share a timestamp — the common case here, since the
duplicates were produced by a repeated startup seed.

## Output

Deterministic, aggregate-only JSON:

```
active_row_count_before                 membership_duplicate_owner_count
distinct_ticker_count_before            legacy_duplicate_groups
active_owner_count_before               legacy_candidate_rows
membership_duplicate_groups             total_candidate_rows
membership_candidate_rows               retained_active_rows
projected_active_row_count_after        orphan_owner_count
projected_distinct_ticker_count_after   orphan_active_row_count
projected_active_owner_count_after      expectation_match
plan_fingerprint                        expectation_checks
generated_at                            transaction_mode
tool / tool_version                     dry_run
```

**Aggregate-only guarantee.** Owner ids, emails, ticker membership lists,
retained row ids and candidate row ids are computed in memory to build the
fingerprint and are **never printed, logged or returned**. A test asserts the
serialised output contains no uuid-like value, no `@`, no ticker symbol and no
`://`. Errors are sanitised to the exception class name only, so SQL text and
bound parameters cannot leak through a failure path.

`transaction_mode` reports the dialect and whether a `READ ONLY` transaction
was obtained (e.g. `postgresql:read_only`). It contains no host, database name
or credential.

`orphan_owner_count` is an **unenforced** referential check computed by outer
join — there is no foreign key between `watched_tickers.user_id` and
`users.id`, and the columns are not even the same width (`VARCHAR(64)` vs
`VARCHAR(36)`).

## Expectation guards

Every one of the nine expectations must be supplied explicitly:

```
--expect-active-rows                  --expect-membership-candidate-rows
--expect-distinct-tickers             --expect-legacy-duplicate-groups
--expect-active-owners                --expect-legacy-candidate-rows
--expect-membership-duplicate-groups  --expect-orphan-owners
                                      --expect-orphan-rows
```

Omitting any of them exits **3** and produces no plan. `--no-expectations`
exists for local and synthetic use only and is **refused outright when the
environment reports production**, using the repository's canonical
`settings.is_production` (which falls back to `RENDER_SERVICE_ID`). Production
is never inferred from a hostname printed to output.

On any mismatch the tool prints aggregate `expected` / `actual` / `delta` only,
sets `expectation_match: false`, **withholds the fingerprint**, and exits **2**.
Silently accepting current state is not possible.

| exit | meaning |
|---|---|
| 0 | analysis completed, every expectation matched |
| 2 | expectation mismatch — no authorizable plan |
| 3 | usage / guard error (expectations omitted, or omitted in production) |
| 4 | database unavailable or analysis failed |

## Plan fingerprint

A SHA-256 over the complete plan, sorted in Python so the digest cannot depend
on database return order. Each row contributes namespace, owner, ticker, rank,
retain/candidate decision, row identity and the ordering key — so the
fingerprint changes if **any** of the candidate set, retained set, ownership
namespace, ticker grouping, row identity or ordering decision changes. It is
not a count: two plans with identical totals but different rows hash
differently, and that is pinned by test.

The raw plan never leaves the tool. Only the opaque digest and the aggregate
counts are emitted.

### How a future executor must consume it

The executor — **not implemented, separately approved** — must:

1. take the approved fingerprint as a required argument;
2. recompute it from the live database using this same shared selection
   implementation, immediately before any mutation, inside the same
   transaction that performs the write;
3. abort unless it matches **exactly**.

A mismatch means the underlying rows moved between rehearsal and execution, so
the approved plan is void and must be re-rehearsed and re-approved. This is
what prevents an approval from being replayed against changed data.

## What this tool does not do

* **It does not authorise cleanup.** A matching fingerprint is a precondition
  for a separate human approval, not the approval itself.
* **It performs no cleanup**, and no executor exists.
* **It creates no migration and no unique index.** The two partial unique
  indexes remain a later, separately approved step, and must come *after*
  cleanup — `CREATE UNIQUE INDEX CONCURRENTLY` cannot succeed while duplicates
  exist.
* **Rollback is deliberately unimplemented**, because there is nothing to roll
  back. When the executor is built it will write one `audit_log` row per
  deactivated record (`action="dedupe"`, `resource="watched_ticker"`), mirroring
  the existing `rollback_import` precedent, and rollback will reactivate exactly
  those ids. Those identifiers will live only in the database — never in
  operator output.
* **It does not close the concurrent-insert race.** Only a database unique
  index does.

## Usage

```bash
DATABASE_URL=... python3 scripts/watchlist_duplicate_cleanup_rehearsal.py \
  --expect-active-rows 1155 \
  --expect-distinct-tickers 25 \
  --expect-active-owners 5 \
  --expect-membership-duplicate-groups 24 \
  --expect-membership-candidate-rows 1031 \
  --expect-legacy-duplicate-groups 0 \
  --expect-legacy-candidate-rows 0 \
  --expect-orphan-owners 0 \
  --expect-orphan-rows 0
```

Those figures are the expectations recorded after two post-fix restarts. They
are **arguments to be re-confirmed against a fresh reading**, not results
encoded in the tool. Take a current `/admin/loop-status` reading immediately
before any rehearsal and pass what it actually reports.
