# Cross-company production acceptance — 6 October 2026

**Status: routing and evidence-boundary sample passed; account-history ticker defect blocks sign-off.**

PR #192 was squash merged as `de51491959c66dc8dd245c68feac6e059e530261`.
Required CI passed on final PR head `7f625e185f82660d99275891d6c53c1c9f27acad`
(run `37455539765`). The owner confirmed deployment. Signed-in browser checks
below exercised the production Intelligence workspace, History, and Research
Trail. An independent backend version response could not be obtained from this
execution environment; commit-level deployment attestation remains pending.

Only newly submitted generic test questions and public source metadata are
recorded here. No account identifiers, credentials, private record IDs, unrelated
research, or screenshots are included in this public report. Browser timestamps
were displayed in America/New_York; the runs below completed between 11:54 and
12:05 UTC on 6 October (00:54–01:05 NZDT on 7 October).

## Live observations

| Input | Returned issuer | Evidence behavior | Persistence |
|---|---|---|---|
| DOCU + subscription-renewal risk question | DocuSign Inc. | Two dated 10-K risk disclosures cited as E1/E2; occurrence, likelihood, quantified effects and thesis direction remain unverified | Two readable messages; identical answer and citations after reload/reopen; visible in History and Research Trail |
| MAN + staffing-demand risk question | ManpowerGroup Inc. | Explicit unsupported-risk gap; consolidated metrics remain supporting context | Saved thread and account history; no VTRS handoff |
| AA + quarterly revenue growth and smelter-energy risk question | Alcoa Corp | Revenue growth observation cites E1; risk section explicitly unverified | Saved answer and sources are AA; History/Research Trail incorrectly index the record as AAPL |
| ACHC + facility-safety risk question | Acadia Healthcare Company, Inc. | Explicit unsupported-risk gap | Two readable messages; correct ACHC record in Research Trail |
| ACMR + customer-concentration risk question | ACM Research, Inc. | Explicit unsupported-risk gap | Two readable messages; correct ACMR record in Research Trail |
| Question-only WD-40 distribution-risk question | WD 40 CO / WDFC | Official-directory resolution; explicit unsupported-risk gap, no WD handoff | Two readable messages; WDFC record in Research Trail |
| Selected MNA + Microsoft Cloud question | Identity clarification for MNA | Response states no company analysis ran; no Microsoft answer or sources | Plain-text clarification saved, without JSON payload |

DocuSign's E1 and E2 links were inspected against the actual rendered filing at
`https://www.sec.gov/Archives/edgar/data/1261333/000126133326000021/docu-20260131.htm`.
Both exact quoted spans occur in Item 1A's customer service/retention discussion.
The filing identifies DOCUSIGN, INC., symbol DOCU, fiscal year ended 31 January
2026. This verifies attribution, not that a potential risk occurred.

The Alcoa metric answer reported 31.4% growth. Its inspector showed
$3,966,000,000 for 1 April–30 June 2026 and $3,018,000,000 for the comparable
2025 period, tied to the same Alcoa 10-Q filed 30 July 2026 (CIK 1675149).
The displayed percentage agrees with those displayed amounts. The underlying
XBRL values were not independently re-audited in this browser pass.

## Defect and follow-up

The old database ticker normalizer accepted a reverse prefix match:
`alias.startswith(input)`. Thus valid thesis ticker `AA` matched alias `AAPL`
when saving an account-owned history row. Routing, emitted answer, saved
conversation and cited Alcoa sources retained AA, but history ticker filtering
and any later selection of that row could be wrong.

The follow-up removes abbreviated alias completion and requires a full alias
with a name/parenthetical boundary for suffix matches. Exact known names and
aliases retain their existing mapping. Regression tests preserve short symbols
and verify a saved Alcoa row appears only under its owner's AA filter, never
AAPL or another owner. Validation: **102 tests passed** across normalizer,
owned-history/deletion, database persistence, memory retrieval, and guarded
legacy-memory suites. No production rows were changed or backfilled.

After deployment, rerun the Alcoa combined question in a new investigation.
Verify a newly saved AA record in both History and Research Trail, including
the AA filter and absence under AAPL. Existing erroneous records remain
historical until a separately reviewed repair is authorized; this change does
not silently rewrite research history.

## Remaining acceptance limits

- This is one signed-in account and six live company analyses plus one
  clarification, not universal coverage certification. Local tests cover all
  three input forms; the live sample does not repeat every ticker/name/question
  combination.
- Live cross-account and signed-out isolation were not rerun here. Existing
  regression checks and prior smoke results remain separate evidence.
- The reviewed qualitative-risk extractor still covers four issuer/topic pairs:
  Apple Services, Microsoft Cloud, NVIDIA Data Center, DocuSign renewals.
  Honest gaps for other topics do not establish launch-quality completeness.
- Current evidence does not certify future market performance, analysis
  usefulness, foreign-filing coverage, or all source freshness/completeness.
- The main answer repeats the transcript in oversized heading text. Its
  readability and the prominence of confidence beside an unverified answer
  remain usability work after the persistence defect is confirmed fixed.
- Test investigations remain saved for review. No account deletion, background
  delivery, shared ticker research write, or profile preference change was
  performed.
