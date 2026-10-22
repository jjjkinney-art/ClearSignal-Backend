# Coverage that distinguishes issuer and segment evidence

The retained answer after PR330 contains twelve cited claims, including a segment
product list, annual segment figures and a management sales explanation. Its
coverage paragraph still reports only the ordinary issuer-description facets.
Without explicitly listing the separate segment evidence, the wording can appear
to deny information shown earlier in the same answer. This is a scope/presentation
gap, not evidence that the existing financial claims are false.

The financial foundation now accumulates separate coverage entries only after
final binding, reference matching and selection of the product/financial claims.
The entries identify a named-segment product list, reported annual segment results,
or a management-attributed sales explanation. They carry existing citation IDs,
exact source-spelled labels and the applicable periods/currency. No caller-supplied
facet annotation, unbound item, rejected source or missing admitted reference can
populate them. No segment-label aliases or product-to-financial identity joins
are inferred.

The ordinary issuer-description facets keep their original statuses and citation
IDs. When a segment product list is present, the activity line now says issuer-wide
coverage remains unverified and points to the scoped list below. The closing
limitation distinguishes reported results and management attributions from
standalone segment economics, independently established causes, competitive
strength and a complete business model. Without admitted segment context, the
original coverage contract and wording remain unchanged.

This changes no source extraction, numerical calculation, factual claim,
confidence score, evidence-selection limit or completeness gate. The response is
still partial; business-model, competitive, valuation and risk-materiality gaps
remain open. Old saved turns are not recomputed by this increment.

## Retained replay and validation

Base is merged PR330, `6cab5a2e6e0867bbad8b9e0cea16d95efd590f48`.
A read-only production health response at `2026-10-22T07:41:25Z` reported that
revision and `status: ok`. This establishes process identity/liveness only.

`SCOPED_BUSINESS_COVERAGE_REPLAY_20261022.json` runs the committed base financial
foundation versus the candidate through ordinary retained ingestion, disclosure
retrieval, admission and final composition. It exactly reproduces PR330's archived
candidate before applying the coverage change. Current ingestion/admission and
product production are shared; base segment parser/producer/binder functions are
also loaded from the committed baseline. This is not a separate historical
production deployment.

All twelve claims, complete document references, citation IDs, inferences,
calculations and unanswered parts remain identical. The direct answer before and
after the coverage block is identical. The coverage facets retain their original
statuses/IDs and `complete_business_model` stays false. Three scoped entries are
added for the reported segment table, Defense management attribution and
Housewares/Small Appliance product list; no issuer-wide coverage is inferred.

The replay uses unchanged PR292/PR314 retained bytes and receipts, verifies all 19
facts-archive inventory hashes and denies external sockets. Source authenticity,
current source availability and independent entailment/usefulness are not
established by those engineering checks. No provider/model call, new capture,
completed-ledger resumption or holdout inspection occurs.

```bash
python scripts/replay_retained_scoped_coverage.py CAPTURE_DIR FACTS_ZIP NEW_OUTPUT.json
```

The CLI refuses existing outputs. Tests cover products/results without issuer-wide
facets, rejected bindings, absent references, ignored caller annotations, preserved
custom citation IDs, dates and management attribution, and the unchanged no-segment
contract. Counts and hashes are recorded in
`SCOPED_BUSINESS_COVERAGE_VERIFICATION_20261022.json`. Hosted CI remains required
before merge. No dependencies, routes, schemas, flags or production settings change.

This is unblinded engineering validation, not independent quality adjudication or
launch acceptance. Wider company/product coverage, counter-evidence, valuation,
the frozen development/holdout benchmark and signed-in personalized acceptance
remain open. All twelve historical live approvals remain consumed; no new live
execution, spending or activation authority follows.
