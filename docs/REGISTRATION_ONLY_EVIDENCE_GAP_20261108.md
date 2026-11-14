# Registration-only evidence gap (pilot profile only)

Status: implemented on `pilot/registration-only-gap`, stacked on `pilot/run9-answer-fixes` (83eaa18). Do-not-merge draft.
No new SEC retrieval, package, approval, execution, merge or deployment accompanies this change.

## Why

Run 10 halted at VBREY (position 3): a company-facts request failed with an unclassified 4xx and, correctly, the pilot
boundary halts on any failed request after a claim. VBREY is a depositary-receipt registration entity. SEC's own
filing list for it contains only registration forms and no XBRL, so there are no company facts to fetch. That
absence is a property of the registrant, provable from a response SEC already returned. It is not a retrieval failure.

## The rule

The facts request is skipped, and the answer says why, only when **every** condition holds on the submissions response
retained for the **exact CIK** being analysed (`app/services/sec_registration_only.py`):

1. the body is a JSON object whose `cik` equals the expected CIK;
2. `filings.recent` has parallel arrays `form`, `isXBRL`, `isInlineXBRL`, `isXBRLNumeric` of one length, at least 1;
3. `filings.files == []` (the listing is complete, no older pages);
4. every `isXBRL` and `isInlineXBRL` is exactly the integer 0; every `isXBRLNumeric` is null or 0 (SEC leaves it null on most entries);
5. every form is one of `F-6`, `F-6 POS`, `F-6EF`, `424B3`, `EFFECT`;
6. `entityType == "other"` and `sic == "8880"` (corroboration, never sufficient alone).

A missing, malformed, ragged or wrong-typed field means "not proven". The rule never reads a ticker, a company name, an
`/ADR` suffix or an HTTP error. A 404, 400 or any other client error on a facts request is **not** evidence of absence.

## Scope

Active only under the pilot profile (`threshold_filing_explanations_enabled`, which is what creates the request-scoped
submissions scope). Outside it `facts_not_applicable` returns None and behaviour is unchanged. The metrics stage has no
`sec/submissions` quota, so it never fetches: it waits up to 5 s for the filing-list stage's single-flight fetch (`peek`).

## What happens when it qualifies

- no `sec/facts` request is issued;
- the answer states that financial analysis is unavailable and why (`explanation()`), and carries
  `evidence_not_applicable: [{task, reason, evidence}]`;
- the ledger records status `unanswered_registration_only`.

## Verification by the pilot

`validation/ordinary_registration_only.py` is an independent second copy of the predicate (validation never imports
application code; a test keeps the two equal). The ledger at case completion and the export at re-proof both require, from
the **same run's retained evidence**: the declaration is well formed; the retained submissions response for that case's
exact CIK satisfies the predicate; the declared evidence equals what the predicate derives; and the case made **no**
`sec/facts` attempt. Otherwise the run halts `invalid_response` (ledger) or the export refuses.

## If a facts request was issued, failure still halts

A `sec/facts` attempt that fails halts `post_claim_failure` exactly as before, and a declaration cannot rescue it. The
numeric HTTP status is recorded in the failure detail (`http_client_error_404`) for diagnosis only. The failure class and
the halt are unchanged by it.

## Reporting

`unanswered_registration_only` cases stay in the 12-case reporting denominator, are reported separately, and count as
unanswered for the answered-cases target. Earlier exports (Runs 9 and 10) re-export byte-identically.

## Prototype evidence

Over 29 retained issuers (101 bodies, Runs 1 to 10) the predicate accepts exactly VBREY. The retained evidence has one
positive example; that limit is stated, not hidden.

## Cohort 5

Cohort, order, questions and criteria are unchanged. A next run would be an operational follow-up. IFCNF's outcome is
decided by IFCNF's own evidence, not by this rule's existence.

## Source binding (`app/**/*.py` + `validation/*.py`)

| | |
|---|---|
| Base (run9fix / #379 head) | `83eaa18bb9c0d1b8eefef20f121c1f7a025d2c78`, binding `ea576d25…5074` (461 files) |
| This change | binding `8165586415ba9284e24adaea46b945bddad2361ca846acc90cc3551539b68af2` (463 files: the base plus `app/services/sec_registration_only.py` and `validation/ordinary_registration_only.py`) |

Run 10's package (`c93cc9bf…0659`) is bound to the base and is not valid for this code. A follow-up run needs a new package, review and approval; none is prepared here.

## Offline evidence

- Run 9 and Run 10 retained ledgers re-export to packets identical under the base code and this code; the original files are unchanged (manifests: 10 of 10 OK each).
- The unmodified base fails 24 `tests/test_pilot_rehearsal.py` tests locally with `offline_network_attempt`; those depend on the machine and are decided by CI.
