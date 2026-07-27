# Sprint 2A — Production Validation Harness

Validates the **deployed** ClearSignal backend's real `/ask` responses across a
benchmark question suite, checking response structure, the Sprint 1B
`_integrity` block, Sprint 1C `quantitative_claims` / `decision_thresholds` /
`claim_provenance_summary`, and a set of factual/presentation-risk heuristics.

This is an **operational tool**, not part of the application. It makes no
changes to production data and is not imported by `app/`.

## Requirements

`requests` (already a pinned project dependency — see `requirements.txt`).
No other dependency is required.

## Configuration (no secrets committed)

| Variable | Purpose |
|---|---|
| `VALIDATION_BACKEND_URL` | Base URL of the deployed backend, e.g. `https://clearsignal-backend-dlsc.onrender.com`. Required for a live run; not needed for `--dry-run`. |
| `VALIDATION_AUTH_TOKEN` | Optional bearer token, only needed if the target deployment has `AUTH_ENABLED=true`. Never commit this value. |

Both can also be passed as `--backend-url` / `--auth-token` CLI flags, but
prefer environment variables so a token is never captured in shell history or
a screen share.

## Dry run (always safe — no network calls)

```bash
python -m validation.runner --dry-run
```

Prints the fixture count, selected query count, concurrency, and the
**estimated number of live requests** before anything is sent. Always run this
first, and after any fixture-file edit, to confirm the scope of a live run.

## A small, bounded live run (recommended before a full run)

```bash
VALIDATION_BACKEND_URL=https://your-backend.example.com \
  python -m validation.runner --max-queries 3 --concurrency 1
```

`--max-queries` caps how many fixtures this invocation runs, regardless of how
many are in the fixture file — use it to sanity-check connectivity and
artifact generation against 2-3 real queries before committing to the full
suite.

## Full suite

```bash
VALIDATION_BACKEND_URL=https://your-backend.example.com \
  python -m validation.runner --run-id 2026-01-01
```

Concurrency is capped at **3** in code (`MAX_ALLOWED_CONCURRENCY`) regardless
of the `--concurrency` flag — this is a deliberate, non-overridable ceiling to
avoid excessive API/model cost or accidental load on a production model
endpoint. Default concurrency is **1** (fully sequential).

## Resuming an interrupted run

```bash
VALIDATION_BACKEND_URL=https://your-backend.example.com \
  python -m validation.runner --run-id 2026-01-01 --resume
```

Each completed query is appended to `<output-dir>/results.jsonl` immediately,
so `--resume` (with the same `--run-id`) skips fixtures already marked
`completed` and only submits the remainder.

## Filtering

```bash
--category core_thesis        # only one question category
--ticker NVDA                  # only one company
```

Useful for narrow re-checks after a fix, without re-running the whole suite.

## Output artifacts

Written to `validation/runs/<run-id>/` (git-ignored — see below):

| File | Contents |
|---|---|
| `results.jsonl` | One line per completed query, appended incrementally (enables `--resume`). |
| `validation_results.json` | Full machine-readable result set for this invocation. |
| `validation_summary.md` | Human-readable summary: totals, pass rate, severity counts, latency percentiles, worst companies, top failure codes, missing-field rates, provenance coverage, threshold availability/invalidity, integrity-warning rate. |
| `failures_by_severity.md` | Every finding grouped under CRITICAL / HIGH / MEDIUM / LOW. |
| `failures_by_company.md` | Every fixture grouped by company, with pass/fail counts. |
| `latency_summary.md` | Min/median/mean/p95/max latency + the 10 slowest queries. |
| `raw_responses/<fixture-id>.json` | The exact raw `/ask` response body for that fixture (for later manual inspection / re-validation). |

`raw_responses/` and the rest of `validation/runs/` are excluded from git
(see the repo's `.gitignore`) — real production responses may be large and
should not be committed.

## The fixture file (`validation/fixtures.json`)

```json
{
  "fixtures": [
    {"id": "MSFT-core_thesis", "ticker": "MSFT", "company": "Microsoft",
     "category": "core_thesis", "question": "..."}
  ]
}
```

- `id` must be stable and unique — it is the resume/dedupe key.
- `requires` (optional, defaults to `[]`) lists logical field names
  (see `validation/checks/structure.py::FIELD_CANDIDATES`) that MUST be
  present for this specific fixture; missing them is a HIGH finding.
  Fields not listed in `requires` are still tracked (see missing-field rates
  in the summary) but do not fail the query on their own.
- To grow the suite toward 100-150 queries, add more `{ticker, company,
  category, question}` entries — no schema change is needed. Keep `id` unique.

## Severity model

See `validation/severity.py` for the full CRITICAL/HIGH/MEDIUM/LOW criteria
and the finding-code -> criterion map. A query **passes** only if it completed
and has no CRITICAL or HIGH finding (MEDIUM/LOW findings do not fail a query).

## Running the harness's own unit tests

```bash
python3 -m pytest tests/test_validation_harness.py -q
```

These are fully offline (no network) — they run every check module against
constructed fixture response dicts, including the exact Visa overlapping-P/E
and NVDA scenario-claim shapes referenced in Sprint 1B/1C/1D.

## Safety notes

- The runner never mutates backend state — `/ask` is a read-only analysis
  endpoint.
- Concurrency is hard-capped at 3 in code.
- `--dry-run` performs zero network calls.
- Retries only apply to transient failures (timeouts, network errors, 5xx);
  a 4xx (e.g. 401/413/429) is not retried, since retrying it would not
  change the outcome and would waste a request against a real cost-metered
  endpoint.
- This harness does not trigger itself automatically — a human must invoke
  `python -m validation.runner` with a real `--backend-url`/env var to make
  any live request.
