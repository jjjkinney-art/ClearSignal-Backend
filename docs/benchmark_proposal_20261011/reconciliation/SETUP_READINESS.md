# Benchmark setup readiness after classification approval

The user-approved classification-only rule is applied to the remaining 26 cases.
The 19-name historical-row rule remains applied. Both original values are retained;
none of the disputed exact values is verified for ClearSignal answers. Older share
count and publication dates remain explicit in the linked evidence.

| Gate | Current evidence |
|---|---|
| Size-classification eligible | 99/100 |
| Classification and identity tiers | 40 large / 30 mid / 29 small/micro |
| Individually cleared for staged metadata admission | 99/100 |
| Admitted tiers | 40 large / 30 mid / 29 small/micro |
| Remaining minimum tier shortfalls | 0 large / 0 mid / 1 small/micro |
| Admitted sector / distinct tag coverage | 11/10 sectors; 28/20 tags |
| Reserved holdouts | 20 unchanged; 20 currently metadata-cleared; external prior exposure still unknown |

The issuer-count shortfall is **1**, not the number of remaining
exact-value discrepancies. Per-company evidence and blocked fields are in
[classification_setup_readiness.json](classification_setup_readiness.json).
Staged admission is not active-registry enrollment or answer-quality acceptance.

## Classification exclusions and replacement

Current exclusions: **JOUT**.
JOUT's unquoted Class B conversion right does not establish an upper bound on
company-wide value below $2bn. Visa instead qualifies large using the documented
Class A component alone; no conversion-parity total is asserted. ASML/BHP dated
SEC annual share tables resolve their prior retrieval gaps. Exact market values remain unverified.

[NPK is a supported development replacement proposal](replacement_candidate_review.json)
for JOUT: October 9 summary/history both $1.08bn, common-stock identity, US domicile,
US GAAP and primary-business-supported Industrials mapping. It is not already in
the 100 and is not a reserved holdout. A JOUT-to-NPK substitution would restore
one small-cap slot without altering the 20 holdouts. **It has not been applied.**

## Remaining metadata fields

No required metadata field remains missing in the reviewed candidate set.

## Offline checks and execution boundary

Candidate admission gates, source-policy scope, dated share/ADR arithmetic,
holdout separation, existing registry/fixture integration, numerical grading and
citation-binding checks are tested offline. No fabricated answer, result hash,
source snapshot or execution manifest is used to imply a completed capture.
The existing historical registry and its 54 fixtures remain unchanged.

A new 100-company registry and six-family fixture manifest are not activated
while the admission/composition gate remains incomplete. The planned workload is
600 cases (480 development, 120 holdout). After the remaining named gaps and any
replacement decision are cleared, generate that offline fixture manifest and
require strict registry coverage plus the additional provenance/holdout checks.
Live or paid captures still require separate authorization. No deployment,
production acceptance test or account-setting change occurred.

Validation: **118 tests passed** across the six focused suites below. One pytest
warning reports an unknown `asyncio_mode` setting because the offline invocation
intentionally excludes application conftest/plugins. No test failed.

```sh
PYTHONPATH=. python -m pytest -q --noconftest \
  tests/test_benchmark_candidate_plan.py \
  tests/test_benchmark_admission_readiness.py \
  tests/test_benchmark_candidate_admission_builder.py \
  tests/test_benchmark_registry.py \
  tests/test_factual_citation_grading.py \
  tests/test_cap_tier_factual_benchmark.py
python scripts/benchmark_candidate_admission.py docs/benchmark_proposal_20261011
```

The read-only builder validates explicit metadata statuses and source references,
scoped approvals, issuer uniqueness and frozen holdouts. Regression cases ensure
missing classification evidence and unresolved truthy values fail admission.
All 100 original quote observations and selections, cohort membership, holdouts,
and the existing registry/fixtures were also compared with the prior PR head.
Full application regression, live captures and production acceptance were not run.
