# Run 4 candidate: same cohort, reviewed identity fixes (2026-11-03)

Status: **packaged for approval, not approved, not executed.** The frontend
fix was merged and deployed before packaging (see "Frontend pin").

## Code under test

This branch is the frozen run-3 commit `6efe7d2` (frozen answer-quality code
`e9a7a9d`, run-3 cohort, pilot safeguards) plus **one** integration commit
carrying the reviewed issuer-identification fixes of ClearSignal-Backend
PR #358 (`af93632`, `6bd086c`; hosted CI passed on both):

- the longest exact official name wins over a shorter name inside it;
- one issuer's securities resolve to its single unsuffixed symbol;
- a ticker found only inside other issuers' official names is not trusted:
  the official name wins when it identifies one issuer, otherwise identity
  stays unresolved with suggestions (never another company).

On this base the name scan keeps the legal-form rule ("NN INC"), so the
embedded-ticker rule also covers short names written with their legal form.
No other `app/` or `validation/` change. The rehearsal expectations now derive
from the pinned frontend intents instead of the frozen code's predicted halt.

Preserved unchanged: `pilot/run3-generalization` (`6efe7d2`, draft PR #357),
the run-3 pre-registration and frozen scoring (`docs/RUN3_PREREGISTRATION_20261031.md`),
the run-3 outputs (`~/clearsignal-pilot/run-3`, hashes in
`review-manifests/run-3-originals.sha256`), and every consumed approval
(including `Julian-20261031-ordinary-03` and `Julian-20261103-probe-01`).

## Exposure: routing is now development evidence

Run 3 retrieved SEC's company directory and no issuer filing, facts or
submissions body for the six companies (its data.sec.gov requests failed or
were abandoned). Its routing failures for **SCCO, LNC and BWMX** were then
reproduced offline and the identity fixes were developed and reviewed against
those exact names. Their identification and routing are therefore **exposed
development evidence, not unseen generalization evidence**. Their research
answers remain **unevaluated**: run 3 produced none (SCCO ×2 unresolved, BX
halted on a transport failure, nine cases not run). BX's earlier exposure
(benchmark and hand-written profile) is unchanged; LVS and USCB were not used
in development.

## Offline route predictions (this commit, SEC's real directory)

SEC directory as retained in run 2 (sha256 `b5be6382…f4ea`), stubbed pipeline,
no network, frontend intents from the pin below: **all twelve questions route
to the research pipeline on the correct issuer** (SCCO ×2, BX ×2, LNC ×2,
LVS ×2, USCB ×2, BWMX ×2). No case is unresolved and no wrong suggestion is
produced. Wrong-issuer requests remain refused before dispatch.

## Frontend pin

Ai-Intelligence-interface PR #87 was squash-merged by Julian Kinney as
`d66be31ecf7a8581323ff539a5fe43d299e15c01` (tree identical to the reviewed
`6d1d46f`; CI run 41563227519 passed). Verified 2026-11-03:

- GitHub's deployment record for environment "Production –
  ai-intelligence-interface" shows `d66be31` as the **active** Vercel
  production deployment (`ai-intelligence-interface-5vfowz3ai-…`), superseding
  `5ee51c3`; "Production – project-qxbjx" also deployed `d66be31`.
- At `d66be31`, `queryIntent.ts` sha256 `f0b6a07b707beb6c94784e7b18cb5b7aee79b80e74b255e1e9c9367b73d0dde8`,
  `symbolResolver.ts` `6fa4e195…8542` (unchanged).
- The unmodified classifier at that commit (Node 24.15.0) returns
  `company_analysis` for all twelve exact run-3 questions (questions sha256
  `835a5fe7…061d`) and all twelve runs-1-2 questions (`e9948dbc…`).

Not verified: the served `/analyze` bundle itself. It requires sign-in, and
signed-in requests to production `/analyze` returned
`504 MIDDLEWARE_INVOCATION_TIMEOUT` (twice) at verification time; the
middleware only refreshes the Supabase session and is unchanged by #87. The
pilot calls the backend directly with the pinned intents, so it does not
depend on that path, but production users could not reach it at that time.

`validation/ordinary_frontend_intents.py` now pins `d66be31` and every case
intent as `company_analysis`; the policy source binding changes with it.

## Unchanged from run 3

Same six companies and twelve questions (`tests/ordinary_run3_cases.json`),
the same limits (66 SEC GETs, per-stage caps, 30 s / 20 s per case, 480 s,
one case at a time, ≤4 concurrent SEC requests, 16 MiB / 256 MiB, 0 model,
0 paid provider, 0 retries, no redirects, direct pinned TLS, filing fallback
off), USD 1.00 all-in ceiling, SEC contact, 0700 output with 90-day retention
(output `~/clearsignal-pilot/run-4`), and the frozen scoring from the
run-3 pre-registration: 12-case denominators, no pass rate, a degraded answer
is never a quality pass, model-assisted review is not independent human
review.
