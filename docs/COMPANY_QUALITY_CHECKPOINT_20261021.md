# Company-quality checkpoint — 21 October 2026 Auckland

## Recovered state

Backend main is `6c5d1e700f94350d57ac3b48755927a25d6e37e5` (PR321).
Frontend PR85 is merged as `86189b4e48dc0961a58897fc5179c7e44c408809`,
after PR84 (`de45b5c9beacf5f0254880d1ff238246c1661179`). PR85 adds browser
QA evidence, not product behavior. Its two Vercel commit statuses were successful
when queried. This session did not independently inspect hosted Actions jobs,
Render runtime revision, deployed environment variables or signed-in production.
Do not turn those status observations into full CI or deployment acceptance.

The frontend assumption form is implemented in PR84 and fixture-browser checked
in PR85. References in the backend roadmap saying that the form is still missing
are historical to PR321; production signed-in and physical iPhone/Safari
acceptance are still open. The current recorded policy keeps the frontend and
both backend scenario flags off. This session changed no flags.

The broad-company blocker has priority over further optional scenario expansion.
The existing benchmark remains 100 issuers / 600 cases: 80 development issuers /
480 cases and 20 reserved holdouts / 120 cases. Do not rebuild it or inspect
holdout answers to choose a repair. All twelve live approvals remain consumed.

## Content assessment of exposed development evidence

This is an unblinded engineering assessment, not an independent usefulness
review, blind score, factual adjudication or new benchmark run. No new source
bytes were downloaded and no source-origin authenticity was established here.
The existing six-case pilot and later replays are separate evidence; this
assessment does not imply that all six pilot questions were rerun on current main.

The NPK canonical answer in `SOURCE_THESIS_PARAPHRASES_REPLAY_20261021.json`
contains 966 whitespace-separated words. It preserves four financial comparisons,
business/channel context, one named-segment competition disclosure, risk excerpts
and explicit gaps. This is useful groundwork, but the broad investment-thesis
question remains unresolved in the following ways, using the existing six rubric
dimensions from `validation/blind_analytical_review.py`:

| Dimension | Observation in the retained answer | Consequence for further work |
| --- | --- | --- |
| Responsiveness | The answer declares products/activities, revenue model and reported segment structure unverified. Its business quote describes distribution channels. | A reader still cannot explain what the company does or how its economics work. More paraphrase parity does not close this gap. |
| Reasoning | Several inferences restate that a reported financial measure increased, followed by a test that a future decline would weaken it. Margin widening is calculated with matched periods; its drivers remain unverified. | Retrieve and bind explicit operating explanations before attributing results to pricing, mix, volume or cost. Do not substitute a trend for a mechanism. |
| Materiality | The Defense competition sentence identifies bases of competition, without establishing segment exposure or relative strength. Risk excerpts do not establish occurrence or financial impact. | Keep the segment label and unresolved materiality. Require separately supported economics/exposure before claiming company-wide importance. |
| Counterarguments | Sampled risk disclosures and conditional monitoring questions appear, but no evidenced ranking of thesis-invalidating conditions is established. | Seek company-specific counter-evidence and distinguish a possibility from an observed development. |
| Uncertainty | The answer explicitly retains competition, valuation, business-completeness and risk-materiality gaps. Different financial reporting durations are disclosed. | Preserve these boundaries; no factual defect is inferred merely because the answer is incomplete. |
| Usefulness | A long, cautious financial foundation leaves the central company explanation and decision relevance unresolved. | Improve substantive context before shortening prose or marking the company a quality pass. No numerical usefulness score is assigned. |

The six successful conditional calculations in
`OWNED_SCENARIO_TURNS_REPLAY_20261021.json` answer separate questions with invented
explicit assumptions. They are not new answers to the original frozen
decision-threshold questions. Historical EPS citations, exact arithmetic,
save/reopen and no-fetch retries do not establish that a hypothetical price,
growth rate or exit multiple is plausible, or that a company is attractive.
Those cases must not be substituted into the original usefulness denominator.

## Next shared implementation slice: business economics

Start with the remaining business-context gap, rather than another scenario mode.
The current code path is:

1. `thesis_disclosures.extract_business_descriptions` searches a complete,
   admitted Business section for eligible complete sentences.
2. `_business_quote_rejection` applies sentence-length, numeric, forecast,
   promotional/internal-activity and subject/predicate exclusions.
3. `business_context.complementary_candidates` selects at most two already
   admitted descriptions; `description_roles` records their explicit facets.
4. `bound_business_description` reconstructs binding before
   `financial_thesis_foundation` composes the answer.

The present replay proves insufficient admitted business context. It does NOT
prove that the needed information is absent from the public filing or identify
which exclusion is responsible. Two excerpts also cannot guarantee a complete
business model. Do not relax the rules or increase caps without inspecting the
underlying candidate passages.

The concrete next artifact is a candidate disposition table from the already
retained complete Business section: exact passage/offset, section, document
hash, current rejection/selection reason, explicit facet, and whether any segment
subject is actually identified. Preserve the original bodies and receipts. Use
the existing exposed development material, not holdouts or a new live pilot.
If those bytes cannot be recovered, record that evidence limitation rather than
guessing a parser change from the final prose.

Choose a shared repair only after that table distinguishes a parsing/admission
failure from missing disclosure or the two-description selection limit. Any
repair must preserve exact quotes and citations, distinguish issuer from segment
scope, and retain exclusions for aspiration, employee programs and promotional
claims. A sentence saying “the segment” cannot acquire a segment identity from a
ticker dictionary or an unrelated competition quote. Segment economics require
their own numerical/period/unit binding, not promotion of prose into numbers.

Validate a chosen repair with before/after retained-source composition and
unseen synthetic subjects plus adversarial exclusions. Preserve the original
exposed results. Then continue with supported operating drivers and
counter-evidence, independent source/usefulness review, separately reviewed
development execution, frozen candidate/holdouts and signed-in personalization
acceptance in the order already defined in `quality_gate_20261016/README.md`.
This adds no new acceptance framework or execution authority.

## Reproducible input bindings and checks

SHA-256 of the exact committed input files inspected in this session:

| Input | SHA-256 |
| --- | --- |
| `SOURCE_THESIS_PARAPHRASES_REPLAY_20261021.json` | `f71ff1ae112318db75f538c9b78e68a677a56540bdf8b341bd40d935f80bb8ed` |
| `OWNED_SCENARIO_TURNS_REPLAY_20261021.json` | `baaabe295dc107c872f9de61affdcb622bf1c0ee1fcb67a2751238278be2704e` |
| `quality_gate_20261016/pilot_gap_review.json` | `fd075435b5f127926590e39dced173ed34b26247d5bc5b02e2e428dcbbc6364f` |

These bind the reviewed repository artifacts, not source authenticity, freshness,
or independent correctness. JSON parsing and word counting used the standard
library only. Documentation-only change: no product tests rerun or historical
test totals claimed as new results. No financial-provider/model requests,
spending, source-body retention, benchmark changes, runtime/dependency changes,
production activation or old-ledger resumption occurred. Broad-company quality
and public-launch readiness remain unestablished; no completion percentage follows.
