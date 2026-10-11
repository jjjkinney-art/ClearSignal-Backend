# Cited operating-margin assessment — 2026-10-11

## Acceptance baseline and scope

The implementation base is main `5b45ba9ab43427ac85bcb109f719fccec4c3807d`,
which includes PR #252's offline risk-inference test fixture. The application
baseline remains PR #251 (`8ca5305c`).
The owner reports newer engineering verification of the deployed DOCU/ASML
competition-sentence fix. Treat that as reported acceptance superseding the
pending-retest wording in `COMPETITION_SENTENCE_FORMS_20261011.md`; this task
does not independently verify production or repeat those live requests.

`CITED_COMPETITIVE_CONTEXT_20261011.md` still identifies competitive strength,
valuation/expected returns and risk relevance as substantive gaps, followed by
source adjudication and a representative 100-company benchmark. Rival names
and issuer competition descriptions alone do not establish relative strength.

This bounded increment adds a concrete profitability measure useful to the
competitive assessment: a within-issuer operating-margin comparison from the
already retrieved revenue and operating-income comparisons. It does not rank
peers, assert pricing power or competitive advantage, or clear the competitive
position gap. No provider request, model call, company-specific rule or score
is added. A rising profit amount can coexist with a narrowing margin when
revenue grows faster; the new calculation makes that distinction visible.

## Acceptance criteria

1. Both revenue and operating-income comparisons must survive existing
   producer reconstruction, issuer checks, conflict handling and answer-reference
   selection. Both current and prior operands must match exact dates, currency,
   consolidated scope, form and filing version. Revenue must be positive.
2. Label the output as derived, expose its formula, exact source operands and
   document references, both margins and their percentage-point change. Preserve
   native USD/EUR inputs without conversion. Round display only and identify a
   nonzero movement below display precision honestly.
3. Withhold the calculation for absent, ambiguous, tampered, stale or unavailable
   inputs/references. Net income, pretax income and bank revenue net of interest
   expense cannot substitute for the supported operating-income/sales pair.
4. Keep the source answer partial and confidence unassessed. Preserve competition
   descriptions, risk-monitoring inferences and the unresolved competitive-position,
   valuation and risk-materiality gaps. A loss margin remains non-positive even
   when it improves. No causal or peer-strength conclusion follows from the ratio.
5. Exercise synthetic unseen-issuer positives and negative controls, complete
   source-gate and public-pipeline paths, and related regressions without live
   credentials, paid providers or production data. Record live-quality acceptance
   separately from deterministic correctness.

## Implementation and limits

`financial_thesis_foundation.py` supplies only selected, reconstructed core
comparisons to `operating_margin_assessment.py`. The latter checks cross-metric
alignment and final reference uniqueness, then returns a `derived` calculation
in the existing source-answer `inferences` array. Its `current` and `prior`
objects retain raw operands and the exact producer document references. The
original four reported amounts remain reported quantitative claims; the ratio
is not relabeled as a reported fact. The answer renders the calculation and
both evidence citations alongside explicit competitive-assessment limitations.

This is deliberately narrower than a general ratio engine. Missing references,
different filing vintages, different periods, unsupported revenue definitions,
and existing producer restrictions (including zero prior values in percentage
change comparisons) can leave a margin unavailable. This does not establish
that an issuer failed to report a margin. A newer discovered filing continues
to use the existing reporting-coverage warning; the dated comparison is not
presented as a newly retrieved period.

PR #252 is already merged in the implementation base, so the feature diff does
not duplicate its test patch. Target `main` for CI, whose workflow is filtered
to that base. Required CI, code review and deployed acceptance remain separate
gates.

## Evidence and remaining acceptance

`test_operating_margin_assessment.py` covers widening, narrowing, unchanged,
loss-making and zero-profit cases; USD/EUR and 10-Q/10-K/20-F inputs; current and
prior date mismatches; filing, issuer and currency mismatches; invalid source
values and citations; missing/ambiguous references; competing revenue inputs;
nonpositive revenue; unsupported substitutes; and preservation of competition
and risk limitations. Its tests fail on unexpected network access.

`test_source_evidence_latency.py` exercises the public pipeline with and without
operating-income evidence, checking final citations, derived labeling, partial
status and zero model-stage calls. Other thesis, currency and source-evidence
regressions remain required. The PR records exact execution results.

No real-company margin accuracy, competitive usefulness, production retrieval,
signed-in save/reopen or representative benchmark quality is established by
these synthetic tests. After an independently authorized deployment, review
the new calculation against actual primary documents, including both operand
periods and versions, before treating it as accepted live output. Broader
competitive-strength assessment, valuation, risk relevance and the 100-company
benchmark remain open.
