# Run 3 — frozen pre-registration (2026-10-31)

Status: **prepared, not approved, not executed.** This document and the
scoring below are fixed before any retrieval. It refines
`docs/GENERALIZATION_EVAL_PLAN_20261030.md` (unchanged) with what was verified
offline afterwards.

## Code under test

The answer-quality implementation is frozen at
`e9a7a9d7a8c9fd4c812baccb4f20afdae32ef7f7`. This branch changes only the
cohort (`tests/ordinary_run3_cases.json`, `validation/ordinary_pilot_contract.py`),
the frontend-intent pin (`validation/ordinary_frontend_intents.py`), the
rehearsal's synthetic identities and fault target, the tests that named the
old cohort, and documents. No file under `app/` changes. The run-1/run-2
cohort file `tests/ordinary_pilot_cases.json` and both consumed approvals are
unchanged.

## Exposure disclosure

- No SEC filing, company-facts response or submissions response of SCCO, BX,
  LNC, LVS, BWMX or USCB was retrieved or read during selection or
  implementation (run-1/run-2 ledgers and this session's records checked).
- **BX is not fully unseen.** In June 2026 BX was in a 50-company benchmark of
  an earlier pipeline (it returned score 0) and a hand-written BX profile was
  added to `app/services/company_knowledge.py` from model knowledge, not from
  filings. In run 2, GOOGL and AMZN (which also have such profiles) showed no
  profile text in their source-evidence answers (0 of 38 and 0 of 44
  fragments). Post-run check: no BX profile text in BX answers.
- **LVS** appears in `app/services/company_detection.py` as name/sector/
  industry routing metadata only.
- Blackstone appears in an unrelated historical-analogs episode.

## Size tiers: unverified

The tiers come only from position in SEC's `company_tickers.json` (retained in
run 2, sha256 `b5be63822ef78687908848b349820d9d6a962af9287e2164f44f4b217259f4ea`),
which is SEC's ordering, not a dated, attributable size measure. No such
measure is available offline. The tiers are therefore reported as
**unverified directory-position tiers**; no issuer is substituted. After the
run, the latest reported revenue and total assets in each issuer's retained
SEC facts (dated, attributable) are recorded as size context only; tiers are
not re-assigned.

## Frontend classification (verified)

The unmodified `queryIntent.ts` and `symbolResolver.ts` at frontend
`5ee51c375a75d43ba51fe71114e54a07efe43815` (hashes `d8f9810f…41b6`,
`6fa4e195…8542`; production deployment `5ee51c3` verified 2026-10-30) were run
under Node 24.15.0 on the twelve exact questions (questions sha256
`835a5fe7d038e21f7085f078f63cf10b92a4d58c310cce00fc6a80c5087f061d`):
eleven `company_analysis`; **`BWMX:core_thesis` → `investing_education`**.
The pin records what production sends.

## Offline route predictions (frozen backend, real SEC directory)

| Order | Case | Predicted route |
|---|---|---|
| 1–2 | SCCO | entity suggestion (NVIDIA offered) — no research |
| 3–4 | BX | research pipeline, BX |
| 5–6 | LNC | entity suggestion (Ford, Citigroup, CRISPR, …) — no research |
| 7–8 | LVS | research pipeline, LVS |
| 9–10 | USCB | research pipeline, USCB |
| 11 | BWMX:decision_threshold | resolves to DE (another issuer); the boundary refuses its first SEC request before dispatch and **halts** |
| 12 | BWMX:core_thesis | **not run** after that halt (alone it would reach a model and halt) |

The synthetic rehearsal (invented SEC data, same code) reproduces the tail:
cases 1–10 answered, `BWMX:decision_threshold` routed to DE and halted with
`invalid_response`, `BWMX:core_thesis` not run, no model request and no
out-of-scope SEC request. With SEC's real directory SCCO and LNC are expected
to yield entity suggestions rather than answers (the synthetic directory is
too small to show this).

These are generalization failures of the frozen code (entity resolution of
upper-case SEC names and foreign legal forms; frontend classification). They
are counted; the research logic is not tuned to them.

## Frozen scoring

Reported per issuer and across all **12** cases; no pass rate; launch
readiness false.

1. **Outcome**: full / degraded / unanswered / operational failure / not run,
   and the system's unanswered parts.
2. **Accuracy and support** (mechanical): quotations verbatim in retained
   bodies; amounts reconciled with retained XBRL by period; derived changes
   recomputed. Errors listed individually (wrong figure, misattributed quote,
   cause on the wrong period or scope, wrong issuer, implied threshold or
   recommendation).
3. **Research quality** 0/1/2 each: company specificity; material risks
   ("none qualified" scores 1 if true, 0 if a qualifying risk was retained and
   omitted); explanations of change (does each quoted cause explain the stated
   change, period and scope?); monitoring criteria; citation support.
4. **Usefulness** 0/1/2: 2 = decision-relevant company-specific research
   beyond headline figures; 1 = correct but mostly headline figures or an
   honest partial answer; 0 = no research delivered. **An honest refusal,
   entity suggestion or halt scores 0 for usefulness**: preferable to
   fabrication, but still a usefulness gap.
5. **Material omissions**: up to five facts a careful analyst would expect
   (latest-period drivers, segment results, concentrations, one-off items,
   the business model, sector-specific measures such as AUM, net interest
   margin, insurance reserves or casino gaming volume), each marked present,
   retained but omitted, or missing from retained sources.
6. **Sector and reporting fit**, recorded per issuer: generic metrics that do
   not suit the business (e.g. operating margin for an insurer or bank),
   missing US-GAAP facts, foreign-issuer filings (20-F/6-K).

Review is model-assisted; results will be called fresh generalization
evidence, not independent human validation.

## Limits (unchanged from runs 1 and 2)

At most 66 SEC GETs (8 per thesis case, 3 per threshold case, same per-stage
caps); 30 s / 20 s per case; 480 s wall clock; one case at a time; at most 4
concurrent SEC requests and 10 dispatches per second; 16 MiB per response,
256 MiB retained; 0 model, 0 paid-provider, 0 retries, no redirects; direct
TLS to the SEC hosts with the pinned CA; filing fallback off; USD 1.00
all-in; output `~/clearsignal-pilot/run-3`, 0700, 90-day retention.
