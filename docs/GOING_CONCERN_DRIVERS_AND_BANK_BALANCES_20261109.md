# Going-concern disclosure, management's stated drivers and bank balances (development change)

Status: do-not-merge draft on `quality/going-concern-and-drivers`, stacked on `pilot/registration-only-gap`
(`0540938`). Offline work on retained evidence only: no new SEC retrieval, package, approval, live run,
merge or deployment. Run 11's records, scores and consumed approval are untouched, and its assessment is
left unchanged: the replays below are **development evidence**, not a rescoring of Run 11.

## Why

Run 11's assessment found, among the answers that were delivered, three omissions that were already in
the filings the system had retrieved:

1. GALT's thesis did not state its 10-Q's going-concern conclusion.
2. NWBI's thesis gave a 1,501.5% net-income rise with no reason, though its 10-Q states management's.
3. NWBI's thesis called deposits and loans unverified, though the retained facts hold both.

## 1. Going-concern disclosure (`app/services/going_concern_disclosure.py`)

**Cause.** Nothing read the latest periodic filing for it. Risk sampling reads only the annual filing's
risk-factor section, where GALT writes that it has "from time to time faced" doubt: historical and
generic. The current conclusion sits in the 10-Q's Note 1 and in its liquidity discussion.

**Rule.** A sentence qualifies only if it is the issuer's own present-tense conclusion that substantial
doubt exists about its ability to continue as a going concern, and it is not withdrawn by an adjacent
sentence. It is read from the latest periodic filing the metrics stage already holds (same document, so
no extra request and no change to the request quota).

| Not a current conclusion | Example, and the reason it is excluded |
|---|---|
| Conditional or hypothetical | "could raise", "may raise", "if ...": a risk, not a statement |
| Historical | "have from time to time faced", "previously", past tense "raised": about another time |
| Alleviated or negated | "alleviate", "no longer", "do not raise", "has been overcome": the opposite conclusion |
| Alleviated by an adjacent sentence | the next or previous sentence withdraws it |
| An auditor's statement | the auditor's opinion, not the issuer's own conclusion |
| Another entity | a customer, tenant, subsidiary or counterparty |
| No assertion | the going-concern assumption, or doubt about something else |

Precision is preferred to recall: a missed disclosure is a gap the answer can state, an overstated one is
an error. Auditor statements are excluded from this change, not judged unimportant.

**Quote.** The conclusion with its adjacent sentences as one contiguous verbatim passage (a neighbour
longer than 450 characters is left out, never clipped), so management's stated cash position, plans and
the dependence it describes travel with the conclusion and it cannot read as stronger than written. The
rendering says it is the filing's own disclosure, quoted as written, and not an independent assessment,
a prediction that operations will cease, or a statement about any period the filing does not address. No
inference about likelihood or consequence is made.

**Binding.** The binder rechecks the reference, offsets, section, filing and period, the rendering, that
the conclusion is a complete sentence at exact boundaries, and re-applies the same classification to the
stored text and neighbours. It is placed first in the answer, under its own heading, and is not counted
as a sampled risk.

## 2. Management's stated drivers (`app/services/current_period_explanation.py`)

**Cause.** NWBI's MD&A paragraph reads: "Comparison of Operating Results ... The following chart provides a
reconciliation of net income ... (dollars in thousands): Net income for the quarter ended September 30,
2026 was $51 million ..." The reader trims a section heading run into a sentence, but not a chart lead-in
ending in a colon, so the statement was never quoted from its own start, never bound, and the sentence
that gives management's driver was never considered.

**Fix.** A chart or table lead-in ending in a colon is skipped when quoting the statement that follows,
which stays a verbatim substring. It is never skipped when the lead-in scopes or qualifies the statement
(segment, region, brand, division, product, geography, non-GAAP, adjusted, pro forma, constant currency,
organic, excluding).

**Unchanged on purpose.** Every rule that decides whether a statement or its cause binds: the figures
must reconcile with the filing's own facts, the cause sentence must refer back to the same change, agree
in direction, state a cause, add no new scope and name no other period. The attribution is rendered as
management's, "not independently established".

## 3. Bank deposits and loans (`financial_thesis_foundation.py`, `verified_sec_metric_service.py`)

**Cause.** "deposits, loan growth and credit quality" was a fixed sector gap (`SECTOR_GAPS`), never
evaluated. The foundation built only duration comparisons; deposits and loans are balance-sheet facts
and nothing requested or shown them for a broad thesis.

**What now passes, and only if it does.** Deposits and net financing receivables are added to the existing
single Company Facts request for a bank (the same signature pair as the other bank measures). The existing
point-in-time builder requires the same concept and unit, the same filing family, a prior date 350 to 380
days earlier and one unambiguous fact; the foundation rebuilds each from its bound claims and shows it
only if the balance date is a period end of the answer's own core comparisons. Anything short of one
unambiguous, aligned pair leaves the gap in place. Credit quality (allowance, nonaccrual loans) needs
concept-continuity checks not made here and stays an unverified part. An answer that shows balances adds:
"Balance-sheet comparisons are reported totals at two dates; acquisitions, divestitures and
reclassifications between the dates are not adjusted for."

## Backlog (not done here)

AUDC's business description; FORFF's CAD reporting and 40-F support; monitoring baselines for pre-revenue
issuers; IFCNF's missing SEC metadata. Also open: thesis answers list "unverified requested parts" without
saying what evidence is missing and why.

## Limits

- The classifier is conservative and tuned on two retained issuers' filings plus constructed cases; filings
  that state doubt in unusual words are missed. Auditor statements are out of scope.
- The lead-in rule was shown on one retained filing and is covered by constructed negatives.
- The mechanical claim verifier used in the pilot parses duration comparisons; balance claims ("as of")
  are verified separately and are reported as "not parsed" by it.
- Replays use retained bodies only and are development evidence; no live run has used this code.
