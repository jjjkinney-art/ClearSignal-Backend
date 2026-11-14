# Reporting what a pilot case delivered: three kinds of content, never pooled

Status: reporting rule for the next ordinary pilot. It changes no approved criterion, rubric or past result. Run 9's recorded outputs and scores stand as they were.

## The three kinds

| Kind | Export class | What it is | Counts toward the "at least 8 of 12 source-bound claims" target |
|---|---|---|---|
| Financial claims | `source_bound_claims` | An answer with source-bound claims, including reported financial comparisons | **Yes** |
| Disclosure-only content | `source_bound_disclosures_only` | A partial answer made only of quoted business, competition or risk statements, with no financial analysis. It carries `content_scope: disclosures_only` and says so in its first line | **No** |
| No substantive answer | `insufficient_evidence`, `identity_unresolved`, `no_answer`, `not_run`, `unclassified` | Nothing source-bound was delivered | No |

A disclosure-only answer is source-backed: its quotations are verbatim from the filing. It is not a financial analysis, states no figure, baseline, threshold or inference, and is never evidence that a financial claim was delivered.

## Two coverage numbers, always reported together

The export's `answer_content.coverage` states both:

- `total_source_backed`: every case that delivered any source-bound content (financial claims plus disclosure-only).
- `toward_source_bound_claims_target`: the count the existing 8-of-12 target uses. **Disclosure-only cases are excluded.**
- `disclosure_only_excluded_from_target` and `no_substantive_answer` make the split add up to the denominator of 12.

Eight disclosure-only answers therefore score 8 toward total coverage and 0 toward the target. Usefulness is scored separately (0/1/2) and is not derived from either count.

## Operational status

| Situation | Status |
|---|---|
| A size rejection or an abandoned evidence request leaves **supported disclosures** to deliver | `answered_degraded_unadjudicated`. The answer opens with the "Incomplete answer: …" notice naming the missing filing, and its `evidence_gaps` record the reason |
| A size rejection or abandonment leaves **no substantive evidence** (an insufficient-evidence answer) | `unanswered_size_rejected` or `unanswered_evidence_abandoned` |
| Nothing was lost and the answer has content | `answered_unadjudicated` (historic name: it means no recorded evidence gap, not that the question was answered) |

The rule is `_insufficient(payload)` in `validation/ordinary_native_export.py`: only an `insufficient_claim_evidence` answer can be "unanswered". A disclosure-only partial is not one.

## Where each number comes from

- Claim accuracy, substantive coverage and usefulness stay separate assessments. Coverage counts say what was delivered, not whether it was accurate or helpful.
- The IFRS taxonomy is named as a reason only when the received Company Facts response held more `ifrs-full` than `us-gaap` concepts; otherwise the reason is generic. No IFRS figures are read.

## Not established

This rule defines reporting only. It does not decide the next cohort's criteria, and it does not make a disclosure-only answer more useful than its score says.
