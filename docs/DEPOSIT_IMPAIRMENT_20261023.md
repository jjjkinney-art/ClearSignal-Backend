# Dated consolidated deposit impairment and management event context

Base: merged PR334, `03d0723aca96181d99e2cdb9007cd13980353738`.
Implements the first contract in `OPERATING_COUNTEREVIDENCE_SOURCE_REVIEW_20261023.md`.
This is a shared, bounded disclosure capability, not completion of broad-company
research or independent usefulness acceptance.

## Answer change

The retained ordinary-path replay appends E14: a reported $2,701,000 consolidated
vendor-deposit impairment for 2025, with the complete three-sentence management
passage describing deposits, the vendor's bankruptcy filing and recognition of
the full-deposit impairment. “Recovery ... deemed unlikely” remains in the quote
and is labelled management's assessment. No vendor name or future recovery
outcome is invented.

All thirteen earlier claims and citation IDs remain unchanged. Issuer coverage,
inferences, calculations and unanswered parts remain identical; the answer is
still partial. Narrative `Housewares/Small Appliances` is retained exactly and is
not joined by guesswork to the differently spelled segment-table label. The
expense remains consolidated; it does not become a dimensional segment expense
or a complete bridge explaining operating-profit changes.

## Measurement contract

`sec_deposit_impairment.py` adds a separate XML/table parser. The existing GAAP
consolidated parser and its concept/namespace exclusions are unchanged. Custom
QName prefixes/local names do not qualify a financial meaning by themselves.
Explicit visible vendor/supplier-deposit impairment labels in two matching
statement presentations establish this contract's narrow reported expense role.
No ticker, issuer, custom concept, namespace URI or segment name is allowlisted.

The parser reuses bounded XML resource/ID handling and table visibility parsing,
but requires the strict consolidated resource shape, excluding both segment and
scenario nodes. A custom HTTP(S) namespace must be source-resolved and non-GAAP;
reserved XBRL, Inline XBRL, currency, XHTML and SRT namespaces are excluded.
Exact SEC CIK, annual duration, USD measure, positive unsigned amount, supported
dot-decimal transform, integer displayed value and scale 3 are required. The
supported annual period ends December 31; arbitrary currencies, scales, fiscal
layouts and negative/reversal facts remain gaps.

Each table requires its own immediately preceding substantive statement title
and thousands heading, explicit consecutive year columns, and an exact visible
expense/reconciliation label. A cash-flow row additionally requires the prior
heading “Adjustments to reconcile net earnings to net cash provided by operating
activities:”. Hidden, malformed, ambiguous or conflicting statements withhold
the result. The latest visible year must bind; no fallback to an earlier column
occurs if the current fact fails.

Exactly one income-statement and one cash-flow presentation must agree on
concept namespace/name, issuer, duration, USD unit, scale, sign and expanded
amount. Supported other observations of that concept/period must also agree.
These are duplicate presentations of one measurement. They are never summed,
and the cash-flow reconciliation is not represented as another expense or proof
of a new cash payment. In the retained filing the displayed `2,701` at scale 3
expands exactly to $2,701,000.

## Complete event and final binding

`deposit_impairment_context.py` requires a complete Item 7/7A MD&A window and its
first current/prior comparison followed by the prior/earlier comparison heading.
It matches three adjacent complete sentences: a dated deposit amount and source
segment label, “the vendor” filing for court protection on a valid date, and
management recognising impairment of the full deposit in a specified quarter
while deeming recovery unlikely. One vendor introduction is supported in that
comparison block; multiple vendors, partial or approximate amounts and unresolved
references are withheld. Deposit, court-filing and recognition quarters must be
chronological within the measured annual period/year. No outside identity,
acquisition, tariff, materiality, recurrence or after-tax consequence is inferred.

Ordinary HTML ingestion attaches separate `deposit_impairment_proofs` when the
existing eligible issuer/annual route requests segment context. Retrieval appends
the new disclosure after existing claims; predecessor-only risk context does not
activate it. `impairment_disclosures` is default empty in the evidence schema.
Final binding reconstructs both statement presentations, scalar, complete event,
offsets, dates, source references and exact summary. The narrative SEC reference
has its own 900-character section allowance; ordinary MD&A references retain
their 300-character cap. Final answer claims expose event/measurement context and
references, rather than the complete internal table and MD&A proofs.

Proofs retain both supported statement tables and positive custom observations,
with XML/table/cell resource limits. Reconstruction additionally limits the proof
to two tables, at most 150 rows per table, at most 50 cells per row, 500 characters
per cell, ten 2,000-character preceding paragraphs and 100 observations. These
limits are deliberate support boundaries, not demonstrated universal coverage.

## Verification

64 new synthetic/adversarial tests cover unseen custom names/namespaces, visible
statement qualification, hidden facts, resources/units/dimensions, wrong issuer,
period/sign/scale, conflicting duplicate presentations, single-presentation gaps,
complete event dates/quarters, partial impairment, vendor ambiguity, final proof
tampering and ordinary retrieval/final composition. The schema serialization
contract is updated for the separate default-empty field.

619 focused tests and 202 adjacent ingestion/reference/provenance/answer tests
pass. Collection finds 18,968 tests with no collection errors. The committed
verification JSON records local CI regression group outcomes and hashes. Full
per-file hosted CI remains a separate check on the draft PR.

The socket-guarded replay verifies the original PR292 filing and PR314 company
facts bodies/receipts and all nineteen archive inventory hashes. It loads the
committed PR334 financial foundation for baseline and disables only the new
impairment producer; baseline exactly reproduces the PR333 archived candidate.
Current ingestion, financial production and admission are shared. The candidate
executes ordinary ingestion and final composition with injected discovery, DNS
and retained HTTP responses, producing 13 to 14 claims while preserving prior
claims/citations and gaps. Full new producer proofs are retained in the report.
It makes zero external requests or model calls; it does not test an HTTP/JWT,
signed-in storage or browser path.

Reproduce with Python 3.11.9 and unchanged pinned requirements:

```bash
python -I -B scripts/replay_retained_deposit_impairment.py CAPTURE_DIR FACTS_ZIP NEW_OUTPUT
```

The script refuses an existing output and installs an external-socket guard.
Source hash/receipt agreement is not independent origin authentication. Exposed
replay and synthetic unseen names are engineering evidence, not independent
research-quality adjudication across sizes/questions. Gross-profit/tariff and
relocation contexts, broader reasoning and valuation remain open. The frozen
benchmark, development/holdout and signed-in gates are unchanged.

All twelve live approvals remain consumed. This work makes no new capture,
provider/model call, spending, old-ledger resumption, holdout-output inspection,
flag change or activation and grants no new execution authority.
