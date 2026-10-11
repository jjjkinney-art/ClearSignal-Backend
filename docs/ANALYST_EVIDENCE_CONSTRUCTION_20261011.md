# Analyst evidence construction and temporal labels

Valuation/expected returns remain open launch-quality areas. This increment
repairs the existing FMP analyst adapter without adding provider calls or a
valuation method. Both analyst outputs previously omitted the required
RetrievedEvidence.timestamp; the constructor exception was swallowed and
valid responses disappeared. They now explicitly retain an unknown publication
date and claim_type=estimate, with unverified source status and no verified
facts or invented public citation URL.

An annual estimate row's date labels its estimate period, not publication time,
retrieval time or a price-target horizon. The adapter no longer calls the first
row "forward" without temporal evidence. Invalid/missing period dates render
"period unavailable". It does not select a new forecast period or assume a
price-target horizon. Finite numeric estimate inputs (including zero revenue
and zero/negative EPS) survive; malformed/nonfinite/bool values cannot become
estimates. Positive target values and ordered ranges retain existing semantics.
A count alone cannot create financial evidence. Provider prose still cannot
enter the strict source-bound financial foundation.

Validation: 214 tests passed across test_analyst_evidence_construction (28),
test_fmp_provider, test_question_anchored_valuation, test_valuation_consistency
and test_source_evidence_latency. New tests use mocked payloads and fail-fast
socket/DNS guards. They assert actual nonempty outputs, unknown provenance,
strict-foundation rejection, malformed/empty payloads and temporal labels.
The combined run emitted source-pipeline thread-cleanup warnings but completed
successfully. No live provider or model calls were made. Live verification,
trusted valuation inputs and expected-return acceptance remain open.

Existing implied-growth prompts already specify 3–5 years and a default 10%
discount rate. Those are existing repository instructions, not newly proposed
policy. They do not supply all mathematical inputs needed to infer growth from
a multiple or create a source-bound expected-return calculation. This repair
neither changes nor claims to complete that calculation contract.

## Required downstream dependency

This branch now depends on PR257 head
c483e7037119ac7f11086e23776b41cd98c37ed3. Merge that freshness/coverage/synthesis
repair before this constructor restoration. It prevents undated provider
estimates from being treated as fresh reported earnings or mandatory forward
claims. Actual adapter payloads with old, future and missing estimate periods
now flow through freshness, coverage and synthesis-prompt tests: estimates stay
unknown-date, reported earnings stays absent, earnings/valuation gaps stay open,
and supported estimate text remains visible without live/current promotion.

After rebasing, 301 tests passed in separate processes across analyst evidence
31, provider freshness 21, FMP provider 45, question-anchored valuation 50,
valuation consistency 48, source evidence latency 45 and truth density 61.
No live provider/model calls were used. Background-thread warnings occurred
in existing pipeline tests; execution passed.
