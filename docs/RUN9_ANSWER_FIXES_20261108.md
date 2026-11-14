# Run 9 answer fixes: development evidence (20261108)

**Status: development evidence on a do-not-merge draft. Not a test of generalization.** Run 9, its recorded scores and its consumed approval are unchanged (`ordinary-20261108-09`, package `e26087c6…5369`, commit `af36f55`). No retrieval, package, approval, live run, merge or deployment was made. Every replay below used copies of the retained Run 4 and Run 9 ledgers through the offline guard, and cohort 4's filings are now development material, so they cannot test these fixes.

Branch `pilot/run9-answer-fixes`, from `af36f55`.

## What changed

| Area | Change |
|---|---|
| Partial answers | `app/services/disclosure_only_answer.py` (new) delivers bound business, competition and risk quotations when no financial foundation can be built, labelled "Source-bound disclosures only (partial): no financial analysis was completed". It states no figure, baseline, threshold or inference. `source_answer.py` calls it only after the financial foundation returns nothing. |
| IFRS wording | `sec_client.py` records which XBRL taxonomies a Company Facts response actually contained (no new request). IFRS is named only when that response held more `ifrs-full` than `us-gaap` concepts; otherwise the reason is generic. No IFRS parsing was added. |
| Export | `validation/ordinary_native_export.py` counts such an answer as `source_bound_disclosures_only`, apart from `source_bound_claims`, only when the answer is marked `content_scope: disclosures_only` and every claim is a business, competition or risk quotation. The count appears only when a case has it, so an export without such a case is unchanged. |
| Table cells | Spaced-parenthesis cells such as `(14.8 )%`, `(313.1 )`, `(62.3 %)` are recognised, so a flattened table is split from the sentence after it. |
| Headings | A title-case heading may contain `of`, `to`, `and` and similar words and is up to 20 words. Any other lower-case word, a change verb or a causal connective means prose, which is never stripped. |
| Cross-references | "primarily due to the factors discussed above" and its variants are not a cause. |
| Fiscal quarters | A fiscal-quarter name is bound only when a year-to-date context ending on the quarter's last day fixes the quarter number (second or third), and the filing's own heading names that quarter for this fiscal year against the prior one. The evidence is stored with the explanation and rechecked when it is bound. |
| Human Capital | Item 1 sentences inside a clearly delimited Human Capital subsection are not candidates. The subsection must start at a heading (not a cross-reference) and end at the next standard Item 1 heading, or at the end of Item 1 within 12,000 characters. Otherwise nothing is excluded. |
| Deferred | The broader promotional-language filter. |

## Replay method and fidelity

The frozen `af36f55` tree reproduces **all six** original Run 9 thesis answers byte for byte from the retained ledger, so the "before" text is the run's real output. The branch was then replayed on the same ledgers. Twelve thesis cases (six from Run 9, six from Run 4) went through the full router; 36 captured explanation inputs and annual documents were also replayed directly.

## Unexpected changes

None in the intended scope. Against the frozen tree, of 12 thesis cases only COHU, TRIP, DCGO, MRX, BWMX and BX changed; CNK, LXRX, SCCO, LNC, LVS and USCB are byte-identical. Of 36 direct replays, exactly five changed (BX explanation, COHU explanation, TRIP explanation, TRIP business, DCGO business), all intended.

One observation, now resolved (see "Competition sentences" below): both disclosure-only answers first included a workforce-style competition sentence.
- COHU's explanation keeps one statement (the stated driver) and drops "net sales increased 37.0%…", because the explanation reader keeps one statement per metric and prefers one with a stated cause. COHU's revenue comparison is unchanged elsewhere in the answer.

## Before and after

### MRX (Run 9 thesis): before

```
This run did not establish a source-supported investment thesis, its supporting mechanisms, or what would invalidate it. No source-bound operating-risk disclosure qualified for this broad question. Filing discovery alone cannot establish the investment case; these parts remain unverified.
```

### MRX: after

```
Source-bound disclosures only (partial): no financial analysis was completed

The SEC structured data retrieved for this issuer is tagged mainly under the IFRS taxonomy (ifrs-full), which this version does not read, so no revenue, profit or cash-flow comparison, monitoring baseline or threshold was attempted. The statements below are quotations from the issuer's annual filing; they are not a financial analysis, a thesis or an assessment.

Official business and sampled risk context
MRX described its business in its 20-F filed 2026-03-25: “We offer execution and clearing services in metals (both base and precious), agricultural products (primarily soft commodities, which include cocoa, coffee, grains, livestock and sugar), energy and fixed income, digital assets and equity futures and options.” [E1]

MRX described its business in its 20-F filed 2026-03-25: “We also provide execution services, where we execute transactions on a regulated exchange on behalf of our clients and then pass the transaction to the relevant counterparty or clearing house to settle and, in connection with our Prime Services, provide trade execution custody and clearing services.” [E2]

MRX disclosed in its 20-F filed 2026-03-25: “We face numerous and evolving cybersecurity risks that threaten the confidentiality, integrity and availability of our IT Systems and Confidential Information, and the performance of these IT Systems could deteriorate or fail.” [E3]

MRX disclosed in its 20-F filed 2026-03-25: “Our indebtedness may increase, including as a result of the offering of Senior Notes, which could adversely affect our ability to raise additional capital to fund our operations, limit our ability to react to changes in the economy or our industry, expose us to interest rate risk to the extent of our floating rate notes and prevent us from meeting our debt obligations.” [E4]
These short excerpts are issuer statements and partial context, not a complete business model or a ranking of the most material risks, and not independent assessments. Competitive advantage and future performance remain unverified; disclosed possibilities do not establish occurrence, probability or a quantified effect.

Business context coverage
Products, services and operating activities: sampled issuer description [E1] [E2].
How the issuer generates revenue: not verified in the admitted descriptions.
Customers and distribution channels: not verified in the admitted descriptions.
Reported segment structure: not verified in the admitted descriptions.
These are sampled issuer descriptions. Full business-model coverage, segment economics, competitive strength and causal financial drivers remain unverified.

This is not a financial analysis. Unverified requested parts: financial performance and reported comparisons; monitoring baselines; valuation and expected returns; competitive position; investment thesis and its supporting/invalidation mechanisms; risk materiality, likelihood and effect on the investment case; business model completeness.
```

### BWMX (Run 4 thesis): before

```
This run did not establish a source-supported investment thesis, its supporting mechanisms, or what would invalidate it. No source-bound operating-risk disclosure qualified for this broad question. Filing discovery alone cannot establish the investment case; these parts remain unverified.
```

### BWMX: after (excerpt, first paragraphs)

```
Source-bound disclosures only (partial): no financial analysis was completed

The SEC structured data retrieved for this issuer is tagged mainly under the IFRS taxonomy (ifrs-full), which this version does not read, so no revenue, profit or cash-flow comparison, monitoring baseline or threshold was attempted. The statements below are quotations from the issuer's annual filing; they are not a financial analysis, a thesis or an assessment.

Official business, competition and sampled risk context
```

### COHU (sentence-level changes)

> removed: Management stated: “Research and development (14.8 )% (17.8 )% (17.2 )% (20.8 )% Selling, general and administrative (18.9 )% (25.2 )% (22.8 )% (27.7 )% Amortization of purchased intangible assets (4.1 )% (8.1 )% (4.9 )% (9.1 )% Restructuring charges (0.3 )% (0.4 )% (0.4 )% (2.5 )% Income (loss) from operations 7.4 % (7.7 )% 0.4 % (16.4 )% Third Quarter of Fiscal 2026 Compared to Third Quarter of Fiscal 2025 Net Sales Our consolidated net sales increased 37.0% to $173.0 million in 2026, compared to $126.2 million in 2025.”

> removed: Management stated: “As a result of the factors set forth above, our net income was $12.1 million for the three months ended September 26, 2026, as compared to a net loss of $4.1 million for the three months ended September 27, 2025.”

> added: Management stated: “Net sales for the third quarter of fiscal 2026 increased compared to the same period in fiscal 2025, primarily driven by stronger demand across AI‑based computing applications, industrial and automotive semiconductor markets.”

> removed: - Net income, management's stated reason: “As a result of the factors set forth above, our net income was $12.1 million for the three months ended September 26, 2026, as compared to a net loss of $4.1 million for the three months ended September 27, 2025”.

> added: - Revenue, management's stated reason: “primarily driven by stronger demand across AI‑based computing applications, industrial and automotive semiconductor markets”.

### TRIP (sentence-level changes; reference numbers shift because one item is gone)

> removed: Management stated: “Net income (loss) $ (313.1 ) $ 53.2 $ (323.1 ) $ 78.2 Net income (loss) margin (62.3 %) 9.6 % (23.3 %) 5.3 % Net income decreased by $366.3 million and $401.3 million during the three and nine months ended September 30, 2026 when compared to the same periods in 2025.”

> removed: and “These decreases were driven by the factors discussed above in “ Net income (loss) from continuing operations ”

> removed: and “ Net income (loss) from discontinued operations, net of tax ”.”

> added: Management stated: “Net income decreased by $366.3 million and $401.3 million during the three and nine months ended September 30, 2026 when compared to the same periods in 2025.”

> removed: Later filings' year-over-year explanations show whether management reports the same driver.

> removed: [E5]

> removed: - Net income, management's stated reason: “driven by the factors discussed above in “ Net income (loss) from continuing operations ”

> removed: and “ Net income (loss) from discontinued operations, net of tax ””.

> removed: TRIP described its business in its 10-K filed 2026-02-13: “We offer leadership training and support to ensure that all employees are supported in their careers.”

> removed: [E7]

> removed: [E8]

> added: [E7]

> added: [E8]

> added: TRIP disclosed in its 10-K filed 2026-02-13: “We derive a substantial portion of our revenue from advertising and any significant reduction in spending by advertisers on our platform could harm our business.”

> removed: TRIP disclosed in its 10-K filed 2026-02-13: “We derive a substantial portion of our revenue from advertising and any significant reduction in spending by advertisers on our platform could harm our business.”

> added: TRIP disclosed in its 10-K filed 2026-02-13: “The success of our operations and the quality of our services are also highly dependent on our ability to attract, retain and engage skilled personnel.”

> removed: TRIP disclosed in its 10-K filed 2026-02-13: “The success of our operations and the quality of our services are also highly dependent on our ability to attract, retain and engage skilled personnel.”

> removed: [E11]

> removed: [E10]

> added: [E9]

> removed: Products, services and operating activities: sampled issuer description [E6]

> removed: [E7].

> added: Products, services and operating activities: sampled issuer description [E6].

### DCGO (sentence-level changes)

> removed: DCGO described its business in its 10-K filed 2026-03-16: “We offer a pay package that we believe is innovative within our industry.”

> added: DCGO disclosed in its 10-K filed 2026-03-16: “DocGo’s business strategy depends heavily on achieving economies of scale because its initial up-front investment is costly and the associated revenue is recognized on a ratable basis.”

> removed: DCGO disclosed in its 10-K filed 2026-03-16: “DocGo’s business strategy depends heavily on achieving economies of scale because its initial up-front investment is costly and the associated revenue is recognized on a ratable basis.”

> added: DCGO disclosed in its 10-K filed 2026-03-16: “DocGo is highly dependent on information technology networks and systems, including on-site systems, managed data center systems and cloud-based computing center systems, to securely process, transmit and store sensitive data and information, such as PHI and other types of personal data or PII relating to its employees, customers, patients and other confidential or proprietary business information.”

> removed: DCGO disclosed in its 10-K filed 2026-03-16: “DocGo is highly dependent on information technology networks and systems, including on-site systems, managed data center systems and cloud-based computing center systems, to securely process, transmit and store sensitive data and information, such as PHI and other types of personal data or PII relating to its employees, customers, patients and other confidential or proprietary business information.”

> removed: [E9]

> removed: Products, services and operating activities: sampled issuer description [E6]

> removed: [E7].

> added: Products, services and operating activities: sampled issuer description [E6].

### Blackstone (Run 4; heading no longer duplicated)

> removed: Management stated: “Three Months Ended June 30, 2026 Compared to Three Months Ended June 30, 2025 Revenues Revenues were $5.0 billion for the three months ended June 30, 2026, an increase of $1.3 billion compared to $3.7 billion for the three months ended June 30, 2025.”

> added: Management stated: “Revenues were $5.0 billion for the three months ended June 30, 2026, an increase of $1.3 billion compared to $3.7 billion for the three months ended June 30, 2025.”

## Reported separately

**Claim accuracy (mechanical, development replay):**
- All 36 newly quoted passages in the six changed answers appear verbatim in the retained filing text (0 not found). That check ran before the competition fix, which only removes one MRX sentence.
- No figure, baseline or threshold is added anywhere. The disclosure-only answers contain no digits outside quoted filing sentences and their filing dates (test `test_the_partial_answer_states_no_figure_baseline_threshold_or_inference`), and carry no inference.
- A cross-reference ("factors discussed above") is no longer presented as a stated cause, which removes two statements that read as causes but were not (COHU net income, TRIP net income).
- This is not an independent accuracy review.

**Substantive coverage (what is delivered, not whether it helps):**

| Case | Before | After |
|---|---|---|
| MRX thesis | `insufficient_claim_evidence`, 0 claims | `partial`, 4 claims (2 business, 2 risk), disclosure-only |
| BWMX thesis (Run 4) | `insufficient_claim_evidence`, 0 claims | `partial`, 5 claims (2 business, 1 competition, 2 risk), disclosure-only |
| COHU thesis | explanation quoted a table fragment and a cross-reference | explanation quotes management's stated driver |
| TRIP thesis | 11 claims, one a leadership-training "business description", one cross-reference cause | 10 claims, neither |
| DCGO thesis | 9 claims, one a pay-package "business description" | 8 claims, without it |

Under the export's own classes, MRX and BWMX count as `source_bound_disclosures_only`, not `source_bound_claims`, so they cannot be read as completed financial analysis. For the next pilot the owner has decided that the existing 8-of-12 target counts `source_bound_claims` only, and that total source-backed coverage is reported alongside it; see `docs/PILOT_ANSWER_CONTENT_REPORTING.md`.

**Usefulness:** not re-scored. The rubric is untouched and Run 9's recorded scores stand. Which changes bear on a user's decision and which are presentation was assessed in `offline-review/RUN9_DIAGNOSIS_20261108.md`; this branch implements that analysis and adds no new score.

## Limits

- Cohort 4 filings were used to find and fix these defects, so they now count as development evidence.
- Only second and third fiscal quarters are named, only when the filing's own comparison heading and year-to-date context agree. First quarters, fourth quarters and headings of another form are not named (nothing is guessed).
- The Human Capital rule recognises a fixed list of following Item 1 headings; an unlisted heading means the zone runs to the next listed one or the end of Item 1, never further than 12,000 characters.
- IFRS facts are still not read. A disclosure-only answer reports that gap and nothing else about the issuer's finances.
- Cooperative cancellation, web fallback and size rejection are unexercised, as before. Broad-company launch readiness and the approximately 95% accuracy target remain unverified.

## Competition sentences (review after the first CI run)

Both disclosure-only answers carried a competition sentence. Rule applied: keep it only if it describes a concrete, issuer-specific competitive exposure.

| Sentence | Verdict | Reason |
|---|---|---|
| MRX: "We compete with other brokers and banks for front-office staff." | **Selection defect, removed** | It describes a labour market. The producer already excludes competition for `employees`, `personnel`, `workforce`, `recruit*`, `talent` and `sales professionals`; "staff" and "front-office" were missing from that list. |
| BWMX: "We also compete with other companies for distributors, leaders and consultants." | Kept | It names the issuer's own sales network (a direct-selling channel), not employees, so it describes who the issuer must win to sell. It remains generic about who the rivals are ("other companies"). |

Fix: `staff` and `front/middle/back-office` join the existing workforce exclusion in `app/services/thesis_competition.py`. Replay on all 20 retained annual filings: exactly one sentence changed (MRX's); the other 19 filings are identical. Replay of all 12 thesis cases through the router: only MRX changed (5 claims to 4: two business statements and two risks); the other 11 answers are byte-identical to the previous branch output. Tests: `tests/test_run9_competition_selection.py` (staff, talent and personnel competition rejected; channel, product-market and "staffing firm" competition still qualifies).

Unchanged and not workforce-related, but generic: MNST "We also compete with companies that are smaller or primarily local in operation." and TRIP "We compete with different types of companies in the various markets…".

## Reporting split

Financial claims, disclosure-only content and no substantive answer are reported separately, with both total source-backed coverage and the count used for the 8-of-12 target (disclosure-only excluded). The export states both in `answer_content.coverage`. Status rule and wording: `docs/PILOT_ANSWER_CONTENT_REPORTING.md`.
