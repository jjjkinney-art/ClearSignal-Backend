# Unseen-company evaluation, cohort 3: pre-registration (2026-11-06)

Status: **plan only.** No package, approval, retrieval or run exists for it. Connected to
the contract by amendment 1, below.

## Frozen implementation

- Code: `45f5283c9fdc714ba1720bf60098c195977bf67d` on `pilot/threshold-filing-profile`
  (do not merge). Tree `01cdbe49e28d524c266b64851780688ab9c00631`, `app/` tree
  `b9f1cd7383b30f2c9ecafea18f4c82fc4da365dc`, `validation/` tree
  `70b78e597da00e5d3908719a73d3cf7d0b70871b`, source binding
  `3f6080da40cdd2e2edcd7381f501141e52f5b2cfb3da5711105ac7bd93a0df5f`.
- Evidence: CI run 42194149205, job 127813093867: 512 files, 19,514 passed, 0 failed,
  96 skipped, no shutdown errors. Retained child report under the profile: 174 collected,
  165 passed, 0 failed, 0 errors, 9 skipped, all 9 on the allowed list; all 36 required
  tests passed.
- **Any later change under `app/` invalidates this plan.** Connecting this cohort needs a
  declared amendment under `validation/` and `tests/` only: its cases, its binding in
  `THRESHOLD_FILING_PROFILE`, `APPROVED_COHORT`, the case and question digests and the
  test expectations. That changes the source binding, so the amended commit needs its
  own CI. Any other `validation/` change needs a new pre-registration.
- Runs 2, 4 and 5 are **development evidence**: Option B and its limits were designed on
  them. They cannot measure generalization and are excluded here.

## Claim

Six companies never used in development or in any pilot answer the same two ordinary
questions under the threshold-filing profile. The result would be **fresh generalization
evidence with model-assisted review**. It is not independent human validation, not launch
validation and not a representative sample. Launch readiness stays false. It would not
satisfy the broader degradation launch requirement: transport failures halt the run.

## Selection (fixed before it was applied; no filing was inspected)

Script: `scripts/select_generalization_cohort.py`, seed committed in `d38501b` before it
was applied. Output: `docs/generalization_cohort_3_selection.json`. A second run reproduced
it byte for byte.

- **Source:** SEC `company_tickers.json` as retained in the run-5 ledger (sha256
  `76b4b2abb9f7dd0e9cff38e2f20336952bb41806057b2dd1033e244f3e1faec2`, 10,409 rows,
  retained 2026-11-05). It lists only ticker, CIK and name. No directory was fetched.
- **Buckets by directory position:** 1-200, 501-1,500 and 2,501-5,000. The output labels
  them `large`, `mid` and `small`. They are **directory-position buckets, not verified
  company sizes**.
- **Eligibility:** ticker of 1-5 capital letters; no fund, trust, ETF, acquisition, SPAC,
  BDC, REIT, partnership, income, portfolio or merger term in the name.
- **Exclusions by issuer (CIK),** which remove every alternate ticker of an issuer:
  - every issuer in a pilot cohort (runs 1-5 `request.json`) or with any SEC response in a
    run 1-5 ledger: 18 issuers;
  - every issuer whose ticker, CIK or name appears in `app/`, `tests/`, `validation/`,
    `docs/` or `scripts/` at `45f5283`: 776 further issuers. Common-word tickers are
    over-excluded; this is conservative.
- **Ranking:** in each bucket, the two lowest
  `sha256("clearsignal-generalization-3:" + ticker)`, one per issuer.

Result. It is kept whatever the filings turn out to contain.

| Directory-position bucket | Position | Ticker | CIK | SEC name | Other tickers of this CIK |
|---|---|---|---|---|---|
| 1-200 | 132 | BP | 313807 | BP PLC | BPAQF, BPPFF |
| 1-200 | 182 | MNST | 865752 | Monster Beverage Corp | none |
| 501-1,500 | 508 | CRDO | 1807794 | Credo Technology Group Holding Ltd | none |
| 501-1,500 | 998 | LLYVA | 2078416 | Liberty Live Holdings, Inc. | LLYVB, LLYVK |
| 2,501-5,000 | 4008 | DGXX | 1854368 | Digi Power X Inc. | none |
| 2,501-5,000 | 4642 | VIRC | 751365 | VIRCO MFG CORPORATION | none |

**No substitution.** An unsupported filer, a missing filing, a failed identification or a
failed answer stays in the denominator of 12.

## Prior exposure (disclosed)

- **Code and records:** none of the six appears, by ticker, alternate ticker, CIK or name, in
  any of the 360 backend branch and remote heads (positive control: SCCO in 17) or the 91
  frontend heads (positive control: AAPL at the frontend head), the original project tree, or
  the assistant's memory. No retained pilot ledger holds an SEC response for any of them.
- **One exception, directory only:** `offline-review/run5_eval/idmap_before.json` and
  `idmap_after.json`, the 16,006-entry directory-wide identity check for the follow-up identity
  fix, include these names. **BP resolves only because of that fix**: absent before it, present
  after. The fix was written for SMFG, and BP is one of the issuers its directory-wide check
  covered. No filing or company data was involved.
- **Directory only:** selection read directory rows and nothing else. No filing, company-facts
  or submissions data was opened.
- **General knowledge:** the reviewing model has background knowledge of these public companies,
  for example that BP is a UK energy group. It was not used for selection and cannot be removed.
  Where it informs a prediction below, the prediction says so. The reviewer must score from the
  retained packet only.
- **Design history:** the bucket rule is the one used for cohorts 1 and 2, whose outcomes are
  known. Only the seed and the larger exclusion set are new.

## Questions

The run-1/run-2 templates, with the SEC name verbatim. Records:
`docs/generalization_cohort_3_cases.json` (12 cases; question digest
`c0617b758458f25c7517393d00809a8d667ad2023b1689e16b813c19be74a4a1`).

## Offline checks (`docs/generalization_cohort_3_offline_checks.json`)

- **Classification:** the unmodified classifier and resolver from frontend `138d6461` (hashes
  `6ef10de3...` and `6fa4e195...`, Node 24.15.0) return `company_analysis` for all 12.
- **Identity and route:** `scripts/check_cohort_routes.py` at `45f5283`, under the offline guard,
  on the retained directory with the research pipeline stubbed. No network: the guard recorded no
  refusals. 10 cases reach research for the correct issuer. 2 resolve no company. None reaches a
  wrong issuer or the general route.

## Predicted outcomes (stated before any data)

| Issuer | Intent | Identity | Predicted case outcome | Requests per case: thesis / threshold |
|---|---|---|---|---|
| BP | company analysis | correct, through the listed-line rule | Answered but thin, or no comparisons | 4 / 3 if it files 20-F; up to 5 / 4 otherwise |
| MNST | company analysis | correct | Answered | 5 / 4 |
| CRDO | company analysis | correct | Answered | 5 / 4 |
| LLYVA | company analysis | **unresolved**: three share-class tickers, so it abstains | `identity_unresolved` x2: suggestions (thesis), clarification (threshold) | 0 / 0 |
| DGXX | company analysis | correct | Answered; depth unknown | 4 / 3 to 5 / 4 |
| VIRC | company analysis | correct | Answered | 5 / 4 |

- **Totals:** 41-45 of the 66 permitted SEC requests; 10 answered or degraded cases and 2
  `identity_unresolved`; no predicted halt, so no case is reordered.
- **Basis:** intent and identity come from the offline checks. The filing forms assumed for BP and
  DGXX come from general knowledge and **were not checked**. Nothing about company figures,
  explanations or quality is predicted.
- **Not predictable offline:** which filings are slow. A filing still arriving at 16 s, or complete
  after 12 s, degrades one answer. A failed request, or no bytes within the 10 s read timeout, halts
  the run. Either could change these outcomes; neither would be a reason to substitute a company.
- **Assessment:** as in the cohort 2 pre-registration, unchanged. No pooled score, no pass rate, and
  no comparison presented as improvement over development results.

## Expected limits

- Foreign or IFRS filers: the IFRS path is not implemented. Such a case is scored as it is.
- Multi-class issuers: identity abstains by design. LLYVA stays in the denominator.
- Live timing is estimated. On an overloaded host a case can pass its deadline and halt the run.

## Not done

No package, approval file, retrieval or run. Those need the amendment above, its CI, and separate
human approval.

## Amendment 1 (2026-11-07, before any package or retrieval): configuration

Connects the pre-registered cohort to the threshold-filing profile. **A configuration
amendment, not a change to the application.**

| | Frozen application code | Configuration amendment |
|---|---|---|
| Commit | `45f5283c9fdc714ba1720bf60098c195977bf67d` | `556d889a4cae2e943811f5f2cdd8d24b7408f472` |
| `app/` tree | `b9f1cd7383b30f2c9ecafea18f4c82fc4da365dc` | Unchanged, same tree |
| Source binding (`app/` and `validation/`) | `3f6080da40cdd2e2edcd7381f501141e52f5b2cfb3da5711105ac7bd93a0df5f` | `1c0a060e732b56e9beb2bca230ba02fcd95365ffb688a3248bfe17c6437aae2c` |

The binding changes because `validation/` changes. **A future package must bind the amended
value.** Any further change under `app/` invalidates this plan; any further change under
`validation/` needs a further amendment or a new pre-registration.

**What changes (`validation/`, `tests/`, supporting records):**

- `THRESHOLD_FILING_PROFILE` now names `run6` and binds its question order and digest, the
  frontend pin and hashes, the 6 and 5 request quotas within 66, the switch, and the timing: 16 s
  filing wait, 12 s parse cutoff, 10 s read timeout, 30 s and 20 s deadlines, 480 s run limit.
- `APPROVED_COHORT` is `run6`. The launcher refuses any selected cohort, including consumed ones.
- `tests/ordinary_run6_cases.json` is byte-for-byte the pre-registered case file: six issuers,
  twelve questions, the pre-registered order. LLYVA's two cases stay and are expected unresolved.
- The launcher refuses a profile that differs from the running cohort, questions or frontend pin.
- The rehearsal-only cohort and the test-only lift of the launcher's cohort check are removed.
  Nothing lifts that check now.
- Evidence templates are regenerated for this profile. Their attestations are still blank.
- The synthetic backend gains these issuers, for identity only. Its figures and filing forms are
  invented and say nothing about these companies.

**What does not change:** selection, issuers, questions, predicted outcomes and the assessment.
Run 5's commit `0d7152a`, package and consumed approval stay as they are. Consumed cohorts keep
byte-identical quota contracts, now pinned by digest in a test, and Runs 2, 4 and 5 re-export with
unchanged cases, outcome counts, attempts and answer hashes.

**Test structure:** 9 test functions (14 cases) build requests against the original quota shape, so they skip under
this profile and must pass in `test_ordinary_historical_cohort`, which verifies them by name.

## Coverage gaps that remain (not closed by this amendment)

**Earlier live pilots do not validate this profile.** Runs 1-5 used the original contract, without
the switch, shared submissions, the filing wait or the parse cutoff. No live run has used any of
them. Rehearsals use invented SEC responses.

Approved-worker paths never exercised:

- a complete approved-mode run; approved mode has only been tested refusing before a ledger exists;
- the real-resolver branch (`gate.resolve = original_dns`);
- real DNS, proxy or direct TLS to the SEC with a real certificate chain (loopback uses a test CA,
  and resolution rules have unit tests only);
- the network check against a real reviewed configuration (tests use invented CA bytes);
- a ledger, export and `packet.json` from an approved worker (the outcome-record test returns a
  loopback worker's result to the real launcher);
- approved-only worker output values, such as `live_network: true`;
- real SEC response shapes, sizes, timing and rate behaviour under this profile.

Transport failures halt the run. This does not satisfy the broader degradation launch requirement.
