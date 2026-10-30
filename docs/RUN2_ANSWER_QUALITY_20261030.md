# Run-2 answer-quality fixes — offline before/after (2026-10-30)

## Scope and limits

Development evidence only. All twelve run-2 cases (`ordinary-20261030-02`)
were reviewed before these changes were written, so replaying them is **not
independent validation**. The review is model-assisted. No live request,
rerun, approval or deployment was made; run-2 originals are unchanged
(hashes in `~/clearsignal-pilot/review-manifests/run-2-originals.sha256`).

| | Code |
|---|---|
| Before | `2e74e66` (the run-2 package commit) |
| After | `2e74e66` + `b6b64cc` (signed changes) + `3c212fd` (explanations) + `ed8efe4` (passage selection) |

Replay: retained run-2 SEC bodies served by exact URL (0 missing), offline
guard on, and the application's evidence wait timeouts removed on both sides
(`--untimed`) so host load cannot truncate an answer; live timing is not
under test. Untimed "before" equals the twelve live run-2 answers byte for
byte.

## Changes (general rules; no issuer named in code)

1. **Signed changes.** Profit measures that are non-positive in either period
   state whether the loss narrowed or widened, or that the figure moved
   between loss and profit, with the absolute change; no percentage of a
   negative base. Negative margins are described as losses relative to
   revenue; sign changes are named; loss-making issuers' monitoring tests no
   longer mention a profitability assumption.
2. **Explanations.** Per metric, a reconciled sentence stating a cause beats
   one that repeats figures; "percent" and "to/from" wording reconcile;
   causal sentences that state the current-period amount of one metric, or
   have the metric as subject with matching direction, are admitted only
   when they name the current period; an amount shared by two line items is
   resolved only by the filing's own preceding definition; segment, region
   or brand causes are admitted only with the current period named and are
   labelled as scoped; the bridge also covers same-direction non-operating
   swings larger than the operating change and is labelled non-operating
   income (expense); "attributable to <owner>" is not a cause; run-in
   headings are removed; answers say when the filing states no cause.
3. **Passage selection.** Risk-factor preambles, bullet summaries, run-in
   headings and catch-all macro-hazard lists are rejected; remaining risks
   rank by concrete dependency/concentration statements, then named
   parties, then source order; when none qualifies the answer says so.
   Employee-program sentences are not business descriptions.

## Verification (after)

- 68/68 quotations verbatim in the retained filings.
- 48/48 reported amounts reconcile with retained XBRL company facts by
  period; 4/4 new absolute changes recompute from the signed amounts.
- Every explanation is re-bound when composed (figures, direction, period,
  scope); each displayed cause is a substring of its quote.
- No buy/sell, target or valuation language; unanswered parts unchanged in
  all twelve answers.

## Rubric (0/1/2: specificity, risks, explanations, monitoring, citations)

| Case | Before | After | Main change |
|---|---|---|---|
| NPK:core_thesis | 2/2/2/2/2 | 2/2/2/2/2 | byte-identical |
| NPK:decision_threshold | 1/0/1/2/2 | 1/0/1/2/2 | byte-identical |
| GOOGL:core_thesis | 2/1/2/2/2 | 2/2/2/2/2 | single-source components risk replaces IP boilerplate; segment causes added |
| GOOGL:decision_threshold | 1/0/1/2/2 | 1/0/1/2/2 | unchanged |
| INGR:core_thesis | 1/1/1/2/2 | 2/1/1/2/2 | wellness sentence removed; quarter figures quoted, "no cause stated" flagged |
| INGR:decision_threshold | 1/0/1/2/2 | 1/0/1/2/2 | unchanged |
| NNBR:core_thesis | 2/1/1/1/2 | 2/1/2/2/2 | revenue cause quoted; loss wording fixed; ransomware dependency replaces hazard list |
| NNBR:decision_threshold | 1/0/1/1/2 | 1/0/1/2/2 | negative-margin wording fixed |
| AMZN:core_thesis | 2/0/1/2/2 | 2/2/2/2/2 | bridge + Anthropic gain attribution; segment causes; China concentration replaces preambles |
| AMZN:decision_threshold | 1/0/1/2/2 | 1/0/1/2/2 | unchanged |
| MAN:core_thesis | 2/1/1/2/2 | 2/1/2/2/2 | margin cause and regional causes; "+542.7%" replaced; DSO risk replaces bullets |
| MAN:decision_threshold | 1/0/1/2/2 | 1/0/1/2/2 | sign-change margin wording |

Threshold answers carry no risks or explanations by design (filing fallback
off). All scores are from development cases.

### Examples

- MAN operating income: "increased 542.7% to $112M … from -$25.3M" →
  "moved from a loss to a profit, a change of $137.3M; signed amounts …".
- NNBR margin: "narrowed by 0.37 percentage points" → "was negative in both
  periods; the operating loss relative to revenue widened by 0.37 percentage
  points".
- AMZN: no explanation → bridge (net income +$44.5B vs operating income
  +$8.3B; non-operating income $1.7B → $53.4B) and management's "The net gain
  of $53.4 billion in Q2 2026 … is primarily from upward adjustments … relating
  to our nonvoting preferred stock in Anthropic …", tied to the filing's own
  "Other income (expense), net was $1.1 billion and $53.4 billion during Q2
  2025 and Q2 2026 …".
- NNBR: figure-only "Third Quarter Results Net sales … were $131.1 million"
  → "Net sales increased by $27.2 million, or 26.2% … primarily due to
  higher selling prices, reflecting the pass-through of increased raw
  material costs …".

## Remaining failures (honest list)

1. **Causes in a following sentence are missed.** INGR: "F&II–U.S./Canada
   operating income decreased 33 percent … The decrease resulted primarily
   from production challenges at our Argo facility …" — retained, omitted.
   INGR's consolidated operating-income decline (−30.6%) stays unexplained.
2. **Segment scope given only by a table heading is excluded.** NNBR
   segment operating explanations ("Income from operations increased by $3.8
   million … primarily due to higher selling prices") are retained but
   omitted because the quote alone would read as consolidated.
3. **Risk selection is heuristic.** INGR keeps one generic geopolitical
   risk (three macro hazards, under the threshold); NNBR's FCPA compliance
   text and MAN's reputation/cyber text are weakly specific.
4. Percentage changes of positive bases are kept (e.g. AMZN net income
   +244.9%); correct but large, now explained by the bridge.
5. Threshold answers remain thin by configuration (filing fallback off).

## Follow-up: linked causes, table scope and risk qualification (`d1d82fb`, `a320e37`)

Same twelve development cases, same replay, compared with `2e74e66`.

- A cause in the immediately following sentence is linked only when it
  refers back ("The decrease …"), agrees in direction, names no other period
  and introduces no new scope; the preceding sentence's figures must agree.
- Narrative under an upper-case segment table heading is attributed to that
  segment only when its stated change equals the table row's change for the
  current quarter; it is labelled with the heading and never treated as a
  consolidated statement.
- A risk is presented only with a concrete dependency or named parties
  (statutes and acronyms excluded; macro-hazard text needs a dependency);
  otherwise the answer says none qualified.

| Case | Run 2 | Final | Change |
|---|---|---|---|
| NPK:core_thesis | 2/2/2/2/2 | 2/1/2/2/2 | **risks withdrawn**: general operational text no longer presented; "none qualified" stated |
| GOOGL:core_thesis | 2/1/2/2/2 | 2/2/2/2/2 | single-source components risk |
| INGR:core_thesis | 1/1/1/2/2 | 2/1/2/2/2 | revenue, net income and segment causes (incl. Argo) via linked sentences; "none qualified" for risks |
| NNBR:core_thesis | 2/1/1/1/2 | 2/2/2/2/2 | revenue cause; segment table attributions incl. Mobile Solutions operating-loss cause; ransomware dependency |
| AMZN:core_thesis | 2/0/1/2/2 | 2/2/2/2/2 | bridge + Anthropic attribution; segment causes; China seller concentration |
| MAN:core_thesis | 2/1/1/2/2 | 2/1/2/2/2 | margin and regional causes; "none qualified" for risks |
| NNBR:decision_threshold | 1/0/1/1/2 | 1/0/1/2/2 | loss-margin wording |
| other threshold answers | 1/0/1/2/2 | 1/0/1/2/2 | wording only where margins cross zero |

Risk scores: 1 where "no company-specific risk qualified" is a true
statement about the retained candidates; 2 where a dependency-backed risk is
shown.

Verification (final): 80/80 quotations verbatim; 48/48 reported amounts
reconcile with XBRL by period; no buy/sell, target or valuation language;
unanswered parts unchanged. Under the application's normal evidence time
limits (one run, retained-body fixture, no timeout removal) all twelve
answers are byte-identical to the timeout-free replay; slowest stage 6.4 s
(MAN thesis disclosures) against 10 s / 20 s windows; explanation extraction
at most 0.37 s.

Remaining gaps after the follow-up:
1. Causes more than one sentence away, or introduced without a back-reference,
   are not linked (by design: ambiguity is rejected).
2. Segment tables without an upper-case heading, or with a "%" change
   column only, are not scoped.
3. Risk qualification is lexical: it cannot recognise company-specific risks
   written in generic words (NPK's defence-contract performance risk), and
   could admit a generic risk that happens to name parties.
4. Threshold answers remain thin by configuration (filing fallback off).
5. All findings are from development cases; generalization is untested.
