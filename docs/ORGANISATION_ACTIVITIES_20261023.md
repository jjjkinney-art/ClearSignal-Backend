# Source-attributed organisation activities

Base: merged PR332, `a2282d4cfebbcada6f1ddf5b4204acb8b312cbc9`.
This implements the first bounded contract identified in
`SEGMENT_ORGANISATION_SOURCE_REVIEW_20261022.md`. It does not complete the broad
company research blocker or establish independent usefulness.

## Result

The retained 10-K replay appends a thirteenth claim, E13: the complete AMTEC
Corporation manufacturing/customer statement discussed under Defense. Its legal
name, explicit alias, acquisition date, millimetre product specification and
source expansion of DOD remain intact. Current operations, issuer ownership and
the identity of the acquirer are explicitly not established. This is the issuer's
attribution about a named organisation within its segment discussion; it is not
an assertion of a verified issuer ownership chain.

All twelve existing claims and citation IDs remain unchanged, including the
annual segment table, reported allocation caveat, derived ratios, management
sales explanation and Housewares product list. Issuer-wide business coverage,
inferences and unanswered parts are identical. The answer remains partial and
valuation and expected returns remain unsupported.

## Shared implementation

`segment_organisation_context.py` adds a separate producer and final binder.
Neither tickers nor company, subsidiary, product or segment names are allowlisted.
The initial grammar requires a complete sentence with a source-spelled legal
organisation name and explicit quoted alias, optional dated acquisition wording,
a present-tense manufacturing predicate, products and customers. Bare aliases,
pronouns, cross-sentence identities and inferred ownership are withheld.

A complete explicitly bounded 10-K Business section supplies internal source
proof. Its opening and closing headings, text hash and original offset are
preserved. Final binding re-runs the same boundary, sentence, numbered-segment,
alias and disposition logic from that proof; caller-supplied labels and summaries
cannot substitute for reconstruction. There must be 2–12 distinct named segment
headings in consecutive ordinal order. Any next numbered heading, including a
general Business subsection, closes the segment discussion. The last discussion
is bounded by the Business closing heading. This deliberately excludes unsupported
layouts rather than guessing their structure.

The producer samples one eligible organisation in source order, without a
materiality ranking. Duplicate alias definitions are ambiguous. Explicit named
disposition language in Business withholds the candidate, including stock or
partial-asset sales, renaming and former ownership of the named organisation.
Unrelated dispositions do not automatically suppress the organisation. These are
conservative checks, not comprehensive legal-entity resolution: the result always
retains `current_status`, `issuer_ownership` and `acquirer` as `not_established`.
A missing named disposition is never proof of current ownership or operations.

Only explicit millimetre product specifications pass the initial physical-number
rule. Other digits in the activity/customer clause, financial amounts, facility
area, award values and delivery years remain unsupported. The acquisition date
has a distinct grammatical role and cannot follow the filing date. Acronyms must
have an explicit expansion in the same customer clause; no outside dictionary
supplies their meanings. Complete promotional, negated, forward-looking or causal
statements are withheld instead of clipped into neutral facts.

`organisation_disclosures` stores the separate proof. Ordinary disclosure
retrieval appends it after existing products, and the financial foundation admits
it only after final binding and matching to a selected response citation. It does
not fill issuer-wide activity/customer facets or the named-segment product-list
coverage slot. A separately scoped SEC reference permits a complete quote up to
900 characters; ordinary Business references remain capped at 300.

The complete internal Business proof can add up to 160,000 characters to an
eligible evidence item; the retained example adds about 25,600. The final answer
claim carries the selected statement/context/reference and discussion heading,
not that entire proof. Source hash consistency does not independently authenticate
the original retained body.

## Verification

- 73 new synthetic and adversarial tests cover unseen legal names and segments,
  aliases, pronouns, acquisition dates, physical versus financial quantities,
  acronym expansion, disposal/rename ambiguity, boundaries and proof tampering.
- 653 focused tests and 211 adjacent ingestion, reference, provenance and answer
  tests pass. Collection finds 18,904 tests with zero collection errors.
- The five existing CI regression groups pass: 83, 87, 221, 178 and 195 tests.
  This is local group validation, not a claim that the complete per-file CI run
  has finished on GitHub.
- The socket-guarded replay uses the original PR292 filing and PR314 facts body
  and receipts. It verifies all 19 archive inventory entries and original source
  size/hash checks. The baseline loads the committed PR332 financial foundation,
  disables the new organisation producer and exactly reproduces the PR331
  archived candidate. The candidate executes ordinary ingestion and final
  composition with substituted discovery, DNS and retained HTTP responses.
- The replay makes zero external requests and zero model calls. It appends one
  claim while preserving all earlier claims/references, coverage, inferences and
  unanswered parts. No endpoint/JWT, signed-in persistence or browser acceptance
  is implied.

Reproduce from the repository root with Python 3.11.9 and unchanged pinned
requirements:

```bash
python -I -B scripts/replay_retained_organisation_activities.py CAPTURE_DIR FACTS_ZIP NEW_OUTPUT
```

The script refuses an existing output path and installs an external-socket guard.
The committed replay and verification JSON record the results and hashes.

## Remaining work and authority

The initial bounded grammar does not resolve divisions, pronoun-led customer
statements, transitive subsidiary chains, arbitrary acquisition/disposition
language or every filing layout. Current business explanations, broader operating
reasoning, counter-evidence and valuation remain incomplete. The exposed NPK
replay and synthetic unseen names are engineering evidence, not independently
adjudicated research quality across company sizes and questions. The frozen
benchmark, development/holdout gates and signed-in acceptance remain unchanged.

All twelve historical live approvals remain consumed. This work performs no new
capture, provider/model call, spending, old-ledger resumption, holdout-output
inspection or activation and creates no authority for those actions.
