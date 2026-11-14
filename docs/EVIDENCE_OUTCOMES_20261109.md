# Evidence outcome record (default off)

Status: do-not-merge draft on `quality/evidence-outcomes`, from `43ff14d` (the head of #382). Offline work on
retained evidence only: no SEC or web request, provider, spend, package, pilot, merge or deployment. It does not
touch #381, #382, the frozen Cohort 6 code or the ERO/MGRT hold, and it keeps the six pilot criteria and every
historical export unchanged.

## What it adds

`settings.evidence_outcomes_enabled` (default `False`). **With it off the new field is absent and every answer
is byte-identical.** With it on, `source_answer.evidence_outcomes` holds one record per evidence need, and the
answer text gains one "What remains unknown" block. No claim, source, request, model call or limit changes.

This is the one shared-interface change: the additive field above, approved for this task.

| State | Meaning | Closed reasons |
|---|---|---|
| `available` | bound evidence was delivered (with `as_of` and `freshness`, and `missing_parts` when a need is only partly met) | `bound` |
| `unavailable` | the authoritative source was read and shows it is not there; said about that source only | `registration_only_filing_list`, `concept_absent_from_returned_facts` |
| `unsupported` | it exists or is listed and this version cannot use it | `ifrs_taxonomy`, `non_usd_reporting`, `annual_form_not_read`, `interim_form_not_read`, `no_same_period_pair`, `conflicting_evidence`, `selection_rules_not_met` |
| `failed` | an attempt did not complete | `facts_retrieval_failed`, `filing_list_failed`, `filing_too_large`, `filing_not_read`, `time_limit` |
| `not_attempted` | never tried | `identity_unresolved`, `no_filing_listed`, `not_requested`, `no_provider`, `not_recorded` |

A failed request, a bare 404 or an empty reply is never `unavailable`; its class and HTTP status are kept in
`detail`. `tried` is false when no filing was read, and the answer then cannot say that a disclosure "qualified"
or did not.

Needs: `reported_financials`, `change_drivers`, `business_description`, `risk_disclosures`,
`liquidity_going_concern`, and (threshold questions) `decision_inputs`. A broad-thesis question gets the first
five; a threshold question gets `reported_financials`, `change_drivers` and `decision_inputs`; a metric question
gets `reported_financials`.

## How it is derived

- Request-scoped notes (`OutcomeNotes`, bound per evidence worker like the submissions scope) **watch** what the
  SEC clients already do. They never change a return value, raise, or add a request: the facts client records
  its failure class and what the response contained, the filing-list code records the forms listed and a list
  failure, and the filing tasks record which form they chose and a read failure. With the flag off no notes exist
  and each hook returns at once.
- The gate's own signals (`financial_analysis`, `evidence_gaps`, `evidence_not_applicable`, claim kinds,
  `unanswered_parts`) and the admitted references (freshness, period end, blocked ids) supply the rest.
- `build_evidence_outcomes` is a pure function of those inputs.

## Wording corrected when no filing was read

When the risk part has `tried` false, three sentences that said an operating-risk disclosure "qualified" or not are
replaced (only then, only with the flag on) by "No filing was read for this part". When a filing was read and
nothing qualified, the original wording is kept.

## Limits and open dependencies

- The notes exist only for requests that run through the router with the flag on. A filing-list failure is
  recorded for the `_fetch_by_cik` path (ticker lookups); the name-search paths are not annotated.
- `selection_rules_not_met` is this task's word for "a filing was read and no passage met this version's
  selection rules"; it does not claim the filing lacks the disclosure. Likewise `no_provider`, `not_recorded`
  and `conflicting_evidence` are additions to the specified reason list, flagged for review.
- `conflicting_evidence` reflects only what `admit_evidence` already blocks. No source-ranking or conflict policy
  was added or assumed; those rules (design section 3.2, 3.4) remain unapproved and untested.
- `unanswered_parts` entries that state interpretation ("investment thesis ...") are not evidence needs and have
  no outcome; every other part maps to a need.
- Replays are development evidence on retained bodies. They do not measure claim accuracy, coverage of unfamiliar
  companies or usefulness, and they do not change any pilot result.
- Launch gates stay separate and unmet by this task: at least 98% material-number accuracy, at least 95%
  claim-to-source binding, zero fabricated sources; usefulness and omissions are reported separately.
  **Pre-launch work, not done here:** broad-company coverage (IFRS and non-USD reading, 40-F and 6-K documents)
  and a credible web fallback with its source, ranking and conflict rules, licensing and spend approvals.
