# Complete product lists with explicit segment scope

The ordinary annual thesis path can now retain one complete product list under
an explicit numbered segment heading. This repairs a source-format admission
gap: the previously retained Business section contains a neutral long product
enumeration, but the ordinary qualitative business rules appropriately reject
its length and combined heading. Those existing rules and their two-item cap
are unchanged. No ticker, product-name or segment-name allowlist is used.

## Contract and integration

A separate producer searches a complete eligible 10-K Business section for two
adjacent sentence spans: the numbered heading prefix and the complete subsequent
product-list sentence. The source must explicitly name a segment, then describe
products sold/manufactured/offered by that segment using an include/comprise list.
No preceding unrelated heading, pronoun or legal-entity relationship supplies the
segment name. Duplicate eligible lists for a segment are ambiguous. Source order
selects one sampled list and does not rank its materiality.

The complete excerpt, including heading and ordinal, stays within 900 characters.
It is never clipped to a factual-looking clause. Numerical/economic statements,
forecast language, internal employee programs and the supported promotional
patterns remain excluded. Other formats, unnumbered headings, implicit segment
subjects, subsidiary product attribution, 20-F and quarterly disclosures remain
unsupported by this first bounded contract.

`RetrievedEvidence.product_disclosures` separates these lists from ordinary
business descriptions, financial observations and operating explanations. A
specific SEC-only document-reference section permits the complete 900-character
list; ordinary Business references retain their 300-character limit. Final
binding reconstructs product context and checks issuer URL, source/date/status,
reference/hash/span identities, exact summary and explicit scope. As with existing
document proofs, these checks do not independently authenticate the original body
at final admission. Document hash/quote claims are supplied by the producer.

The claim is appended after existing disclosures, preserving prior citation IDs.
Its summary quotes the complete source and says it is a sampled product list for
the named segment. Revenue contribution, ownership, competitive strength and
future performance are not established. It does not fill issuer-wide business
coverage facets or mark the business model complete. No route, dependency, database
migration, additional source request, model call or runtime flag is introduced.

## Retained source and replay

Base is merged PR329, `6023227b16decbc46505f567af1b2b4468ec79de`.
Read-only `/healthz` reported that production revision, `status: ok`, at
`2026-10-22T05:30:32Z`. This is liveness/process identity, not research acceptance.

The unchanged PR292 filing body is 1,404,517 bytes with SHA-256
`8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
Its receipt does not establish independent source authenticity. The retained
Housewares/Small Appliance list includes pressure cookers/canners, kitchen
appliances, heaters and other products. The complete heading/list quote and
offsets survive ingestion, disclosure retrieval, admission and final composition.
This supports that segment's source-reported list only; it does not describe the
Defense or Safety segments or prove that the issuer's activities are complete.

`SEGMENT_PRODUCTS_REPLAY_20261022.json` reproduces PR329's archived candidate
exactly before enabling the new producer. The candidate adds one product claim:
eleven claims become twelve. All eleven earlier claims/citation IDs, the segment
sales explanation, derived calculations, prior inferences, business coverage and
unanswered parts remain unchanged. The result remains partial. The baseline uses
committed segment parser/producer/binder functions, the new product producer
disabled, and shared current ingestion/final composition; it is not a separate
historical application deployment.

```bash
python scripts/replay_retained_segment_products.py CAPTURE_DIR FACTS_ZIP NEW_OUTPUT.json
```

The script refuses existing outputs and checks source receipt hashes and all 19
retained Company Facts archive inventory hashes. Discovery, DNS and HTTP are
injected from existing bodies, and an audit hook rejects external sockets. No new
provider/model request, capture, old-ledger resumption or holdout inspection occurs.

## Validation and remaining gates

Synthetic tests cover unseen segment names, predicate variants, complete long
quotes, rejected ambiguity/promotion/numbers/forecasts, document gates, duplicate
lists, intervening text, quote caps, final-field/reference/summary tampering and
ordinary final-answer integration. Exact counts/hashes and retained replay checks
are recorded in `SEGMENT_PRODUCTS_VERIFICATION_20261022.json`; hosted CI remains
required before merge. Local CPython 3.11.9 was restored after its executable was
missing; existing pinned dependencies and repository runtime requirements were
not changed.

This is unblinded engineering validation, not independent factual/usefulness
adjudication or launch acceptance. Wider product coverage, a complete business
model, operating explanations, counter-evidence, valuation, frozen development/
holdout and signed-in personalized acceptance remain open. All twelve historical
live approvals remain consumed; no new execution/spending or activation authority
follows.
