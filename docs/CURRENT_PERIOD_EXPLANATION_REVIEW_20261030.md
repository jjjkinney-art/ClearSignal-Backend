# Current-period explanations and monitoring criteria — offline review (2026-10-30)

## What this is, and what it is not

An offline before/after comparison of four answers from the ordinary pilot run
`ordinary-20261030-01` (NPK and GOOGL, `core_thesis` and `decision_threshold`).
Every SEC response was served from the bodies retained in run 1, by exact URL
(17 served, 0 missing); external DNS and connections were refused by a guard.
No live SEC, provider or model request was made.

These four cases were already exposed during the run-1 review and the fixes
were developed against them. **Replaying them is not independent launch
validation.** The review below is model-assisted, not an independent human
review. Run-1 originals were not modified (sha256 manifest re-verified).

## Code versions

| Label | Code |
|---|---|
| Run 1 (live) | `c4b60f3` (package `f3ca1afd…`) |
| Before | `main 9da213d` + PR #353 `39e1a1f` (revenue-concept recency fix) |
| After | `main 9da213d` + PR #353 `39e1a1f` + this branch |

Both replays include #353, so GOOGL revenue ($127.6B, +24.7%) is present in
both; the differences below come from this branch only.

## Changes (general, no ticker rules)

1. **What changed in the latest reported period.** From the same admitted
   10-Q/10-K the filing-metrics stage already fetches (no extra request):
   - management sentences that reconcile with the verified XBRL comparison —
     stated change within the text's own rounding, or stated level plus a growth
     rate within 0.5 points — and agree in direction;
   - segment/component sentences whose own "by $X from $A to $B" figures agree
     and that state a cause, taken from the latest-period discussion only;
   - when net income and operating income move in opposite directions, the
     filing's own consolidated bridge (operating income, other income (expense),
     tax, residual), with exactly one fact per concept and period.
   The section says the attributions are management's, and that the bridge
   shows where a change sits, not why. Every binding, figure, quote and the
   rendering are rechecked by `bound_current_period_explanation`.
2. **Monitoring criteria with cited baselines.** "Below the cited current
   amount" now names the amount and period (e.g. "below $127.6B (reported for
   2026-07-01 to 2026-09-30)"; "operating margin below 31.81%"). A "What to
   check in the next comparable filing" list restates only the filing's own
   figures and management's stated reasons. No new thresholds.
3. **Repeated caveats.** "Not a forecast" is stated once per section in the
   rendered answer (structured rows keep it on every test). Per-excerpt issuer
   caveats are consolidated into one closing note with the same content.

## Before/after rubric (same rubric both sides)

| Case | Accuracy | Citations | Specificity | Usefulness | Missing info | Uncertainty |
|---|---|---|---|---|---|---|
| NPK core_thesis | = (all figures/quotes verified) | +1 ref (E5 explanation) | ↑ consolidated statement + Defense/Housewares drivers | ↑ explains the +21.7% quarter; segment baselines to monitor | unchanged parts list | preserved; 6→2 "not a forecast", 2→0 per-excerpt caveats |
| GOOGL core_thesis | = | +1 ref | ↑ bridge: NI −$8.5B vs op. income +$9.3B, OI&E $12.8B→−$8.2B; stated revenue drivers | ↑ resolves the "counter-evidence in net income" with the filing's own arithmetic | unchanged | preserved; same reduction |
| NPK decision_threshold | = | = | ↑ explicit 13.24% baseline and period | small ↑ | unchanged | preserved |
| GOOGL decision_threshold | = | = | ↑ explicit 31.81% baseline and period | small ↑ | unchanged | preserved |

All 32 quotations in the after answers appear verbatim (after whitespace and
byte-order-mark normalisation) in the retained filings. Unanswered parts are
identical before and after: the explanation does not fill competitive position,
valuation, business-model completeness or risk materiality.

## Missing evidence vs. evidence available but omitted

| Gap | Class | Status |
|---|---|---|
| Why revenue / net income moved (NPK, GOOGL) | Available but omitted (10-Q results discussion was fetched) | **Addressed** |
| Threshold answers: stated drivers | Not retrieved under run-1 config (`DECISION_MONITORING_FILING_FALLBACK_ENABLED=false`) | Code ready. With the flag on, replay adds 2 (NPK) / 3 (GOOGL) explanation criteria from retained bodies; live, this costs one extra 10-Q request per case. Config decision, not made here. |
| Company-specific risk selection (GOOGL shows IP boilerplate) | Available but poorly selected | **Not addressed.** Topic frequency was tested and rejected as a general signal (NPK's most frequent topic is cybersecurity). |
| Valuation boundaries, expected returns | Missing source evidence (no price/valuation inputs admitted) | Not addressed; no thresholds invented |
| Margin drivers | Partly available: revenue drivers are stated; cost drivers are not bound | "Drivers of the margin change remain unverified" retained |
| Pre-existing quotes contain stray U+FEFF characters (NPK business/backlog excerpts) | Cosmetic, pre-existing | Not addressed |

## Tests

`tests/test_current_period_explanation.py` (9 tests, excerpts from the retained
filings). Related suites: 496 passed. Full suite on macOS: every failure was
re-run in isolation on this branch and on `39e1a1f`; three branch-only failures
were fixed (structured "not a forecast" retained; closing-note wording retained;
schema field added to the serialization test). Sixteen failures occur identically
on `39e1a1f` under the offline guard (approval-gated and isolated-pipeline tests)
and are left to Linux CI.
