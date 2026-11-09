# Registration-only rule: a blank SIC (development change)

Status: do-not-merge draft on `fix/registration-only-blank-sic`, from `26d2859` (head of draft #381). Offline work on retained
evidence only: no new SEC retrieval, package, approval, live run, merge or deployment. #381 and cohort 6 (issuers, questions, order,
criteria) are unchanged.

## What changed
The registration-only predicate required `sic == "8880"`. SEC leaves the SIC **blank** for some depositary-receipt registration
entities, which Run 11 retained for IFCNF (Inficon Holding AG/ADR): `sic` present and exactly `""`, `sicDescription` `""`, `entityType`
`other`, two filings (`F-6 POS`, `F-6EF`), no XBRL flag, `files` empty. That blank is why the rule did not qualify IFCNF and why its issued
facts request (HTTP 404) halted Run 11. The rule now accepts a blank SIC when **every other existing check passes**, and nothing else changes:

| Condition (unchanged unless marked) | |
|---|---|
| Exact CIK; the response reports that CIK | unchanged |
| Non-empty, parallel, aligned arrays; complete listing (`files == []`) | unchanged |
| Every form in `{F-6, F-6 POS, F-6EF, 424B3, EFFECT}` | unchanged |
| Every `isXBRL` and `isInlineXBRL` exactly the integer 0; `isXBRLNumeric` null or 0 | unchanged |
| `entityType` is `other` | unchanged |
| **`sic` is `"8880"`, or the key is present as `""` with `sicDescription` exactly `""`** | **widened** |

Still refused: any other SIC (including a conflicting operating code), a missing, null, numeric or whitespace SIC, a blank SIC beside a
description or with no description field, unread older pages, any malformed or ragged field, any flagged filing, any operating or foreign
annual form. The predicate takes only a response body and a CIK: no ticker, name, suffix, form-type shortcut, taxonomy or HTTP result is an
input. IFRS, 40-F and a 404 are not evidence of absence and are not used. Both independent copies (application and pilot) are changed
identically and a test keeps them equal on every fixture.

A blank SIC is **no corroboration at all**. With it, conditions 1 to 5 carry the whole proof: the filing list alone.

## What the filing list establishes, and what it does not
It establishes that SEC's complete filing list for that CIK shows only registration forms and no XBRL-tagged filing. It does **not**
establish what SEC's company-facts service holds for the CIK: that service was not queried, and no result of querying it is claimed. The
answer says so: "This rests on SEC's filing list alone; SEC's company-facts service was not queried, so nothing here states what it holds."
The earlier sentences ("no company-facts request was made", "not a retrieval failure") remain true and unchanged.

## What the pilot does
When the rule qualifies, no facts request is made, the case is recorded `unanswered_registration_only`, the next case runs, and all 12 cases
stay in the denominator. The ledger and export re-prove the declaration from the same case's retained filing list and refuse it otherwise. If a
facts request **is** issued and fails, the run still halts under its existing code (`http_client_error_404`, `http_auth_403`, `http_throttled_429`, ...);
a provable list cannot rescue an issued failure.

## What this does not do
- **It does not resolve ERO's possible halt.** ERO files 40-F and reports in IFRS. Its filing list is not expected to be registration-only, so this
  rule would not apply, and if its company-facts request fails the run still halts. That is the separate design question in
  `PROPOSAL_FACTS_UNAVAILABLE_AND_WARRANTS_20261109.md` (state 1 there is wider than this change: it would not require a registration-only form list).
- It addresses only the **blank-SIC registration-only** case, whose retained evidence is one issuer (IFCNF). Positive evidence remains two
  issuers (IFCNF, VBREY); no further claim is made about how SEC encodes other registrants.
- It does not change warrant resolution (see `WARRANT_SUBSTITUTION_RISK_20261109.md`) or any code outside the predicate, its explanation and tests.

## Tests (all offline)
Retained positives (IFCNF blank SIC; VBREY 8880) and retained operating and cross-border negatives (NWBI, GALT, Fortis 40-F, AudioCodes 20-F,
BP and Marex IFRS), the latter also with the most permissive metadata (`other`, blank SIC, older pages cleared, flags zeroed); 36 one-condition
mutations (11 SIC variants and 25 other conditions); ledger tests at IFCNF's real position (11th) including each failed-exchange detail; loopback rehearsals on the wire (no facts request, later cases
run, 12 in the denominator; an operating issuer with a blank SIC still answers; flagged list, conflicting SIC and 403 each halt under their own code; a 429 beside a
proven registrant halts); and an export tamper test.
