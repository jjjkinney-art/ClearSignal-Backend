# Original-byte cash-table binding and row references — 25 October 2026

The new `cash_reconciliation_source_binding.py` service compares a caller's table
capsule against a capsule regenerated from the supplied original filing bytes.
The bytes must match the supplied content hash; the exact complete proof must
match, including source hash, table position, XML and capsule hash. The service
then reconstructs the bridge again. It rejects a rehashed capsule with two
offsetting rows removed, even though that capsule still reconciles arithmetically.

Metadata requires an exact SEC issuer URL, supported 10-K form, available/fresh
state, bounded title, ISO filing/evaluation dates and annual periods ending no
later than the filing. No currency substitution is permitted. These are checked
caller inputs; they are not an independent network availability or authenticity
check. The supplied body must come from the validated document retrieval path
when that integration is implemented.

Each reconstructed numeric row receives a `ClaimDocumentReference`, carrying
the original filing hash, filing date, statement section, complete printed row
quote and current-column Inline XBRL fact fragment. The reference also retains
all column fact IDs alongside it. The ordinary 300-character quote cap is
unchanged; long rows are withheld rather than clipped. These reference objects
support the displayed statement rows only, not a causal or sustainability claim.

The result changes `source_binding_established` to true specifically for
`exact_supplied_document_bytes`. It keeps `independent_origin_verification`,
`admitted`, `launch_ready` and semantic component-nonoverlap verification false.
Someone who supplies a different body and matching metadata can still create
internally consistent evidence; this service is not an authentication system.

## Retained verification

`scripts/replay_retained_cash_source_binding.py` verifies the original filing
receipt/pinned body hash and the committed PR344 replay hash, then binds that
unchanged proof to the source bytes. All rows, periods, signed taxonomy values,
display contributions, annual totals and component changes remain identical;
only the scoped source-binding flag changes. Sixteen complete row references
are created. `CASH_SOURCE_BINDING_REPLAY_20261025.json` retains the result and
reference objects. The replay repeats byte-for-byte with external sockets
denied, zero external requests and zero model calls.

The replay uses explicitly supplied historical source metadata for a consistency
probe, not a fresh production source check. No old execution ledger is opened.
Synthetic tests cover original-byte/capsule/hash mismatch, the offsetting-row
substitution, alternative reconciling sources, date/period/identity/currency/form
and availability mismatch, complete row fact anchors and withholding long quotes.
The 19 new cases and adjacent parser/source suites pass 208 tests. Full collection
finds 19,148 tests with zero errors; `git diff --check` passes. Full repository
regression remains for PR CI. These checks establish bounded behavior, not quality.

## Remaining integration

This service is not connected to ordinary ingestion, `RetrievedEvidence`, final
answer admission, `/ask`, saved research or settings. It creates row-reference
objects, not admitted citations in production answers. The next step is to
retain a trusted original-source handle in the existing bounded fetch path and
use this binding during producer/final reconstruction, preserving the complete
bridge and source references through the response gate. It must not allow caller
capsules or receipt-looking metadata to replace the fetched source.

The final claim contract must distinguish reported statement contributions and
derived change arithmetic from verified causation, semantic nonoverlap,
recurrence or normalized cash generation. Annual evidence must not explain a
later interim movement. A source-bound annual bridge will still not establish
valuation, competitive economics or complete company coverage.

This exposed retained probe is not a current ASML/ACHC rerun, complete-answer
assessment, independent usefulness pass or launch clearance. The rough 55%
planning judgment remains unchanged; measured quality pass rate remains null.
All twelve live approvals remain consumed. No capture, provider/model calls,
spending, benchmark/holdout access, old-ledger execution or activation follows.
