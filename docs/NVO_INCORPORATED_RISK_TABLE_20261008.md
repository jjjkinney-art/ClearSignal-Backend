# NVO incorporated annual risk table — 8 October 2026

## Deployed checkpoint

The owner's post-PR #206 Render subset reports SPOT, ASML and TSM pass and NVO
gap. ASML's transport-hash blocker is cleared for that deployed source-binding
sample. The earlier complete post-PR #203 cohort passed all 29 domestic cases.
These separate runs do not establish a fresh complete-cohort count or launch
clearance. Signed-in and saved-research production acceptance remain outstanding.

## Reviewed source relationship

NVO's 2025 20-F Item 3.D incorporates Risk management pages 41–42 of Annual
Report 2025, explicitly excluding Mitigating actions on page 42. The actual
20-F contains a link to the same-accession annual report; the SEC accession
index identifies that document as EX-15.1.

| Role | Source URL | Form | Filed |
|---|---|---|---|
| Parent | https://www.sec.gov/Archives/edgar/data/353278/000035327826000012/nvo-20251231.htm | 20-F | 2026-02-04 |
| Incorporated report | https://www.sec.gov/Archives/edgar/data/353278/000035327826000012/nvo-20251231_d2.htm | EX-15.1 | 2026-02-04 |

Only those exact source identities and CIK 353278 qualify. Every byte outside
the same narrowly reviewed empty transport-script tail used by the ASML repair
must match the registered fingerprint:

- Parent: `bc3b95895aa5c5ce37bbeb9b511ab60f9bfa5b9c072bbb24e58c0b093f92edd9`.
- Exhibit: `757f48ffad59564c82b801e3ca55aec74245b456659c34f5ad013d9d0ce547ee`.
- First three risk-row cells, separated by a null byte:
  `68ee5d0b7b2a126bbb24b088527c9956ab9670d172674d6ff789945f4296f061`.

The original downloaded-byte SHA remains each source reference's content hash.
The first reviewed parent body was 1,425,869 bytes; a fresh download was
1,425,860 bytes with a different transport-tail URL and the same fingerprint.
The exhibit is 10,592,960 bytes. Both old and fresh bytes pass local replay.

## Retrieval and table binding

After the current 20-F has no qualifying requested disclosure, an exact observed
incorporation statement and exhibit link can replace the remaining annual
candidate with this reviewed exhibit. Both successful and failed fetches consume
the same bounded attempt budget. A one-document budget cannot follow the link.
No SEC index request, arbitrary exhibit search or extra document slot is added.
EX-15.1 is permitted under periodic HTML limits only for this registered source;
other exhibits retain existing behavior. The 15 MB download limit and 360k
retained-text limit remain. Redirect destinations are checked independently.

The reviewed table is table 90, with exactly the Risk area, Description, Impact
and Mitigating actions headers. The clinical pipeline row must be unambiguous.
The first three cells must match the reviewed row fingerprint and a unique,
contiguous span in retained visible text. Each cell preserves its own exact
start/end offsets. Mitigating actions never enter the risk claim.

A dedicated parser permits only empty decorative row-spanned cells in that
reviewed table. Nonempty semantic row spans, nested/incomplete tables and cells
above the 2k cap fail closed. Generic table rules are unchanged. Topic rules
now recognize the explicit phrases clinical activities and clinical pipeline;
clinical care, generic pipeline and non-clinical activities do not qualify.

The disclosure stores the parent quote/reference, parent fingerprint and offsets,
the original exhibit hash and verified fingerprint, table headers, cell offsets,
section and page 42. The answer identifies the material as an incorporated table
row rather than an independent assessment or a generated sentence. References,
answer claims and serialized research snapshots retain both source relationships.
The read-only acceptance harness checks the parent span/link as well as each
exhibit cell and the answer citation.

## Validation and remaining gate

824 tests pass across 19 isolated modules, including 62 new incorporation/table
cases. They cover actual fetch/admit/answer paths using authored source fixtures,
missing or mismatched parent statements/links, scope/issuer/form/date mismatches,
changed source bodies, altered headers, excluded mitigations, missing/numeric
impacts, ambiguous rows, semantic row spans, malformed references, forged cells,
source limits, redirect checks, document budgets and snapshot ownership.
An in-memory account-owned conversation is persisted and reopened with both
references intact; a second owner cannot read it.

Actual downloaded old and fresh NVO documents pass the production acceptance
harness in two attempts, with exact incorporation and cell spans and an
attributed citation. Replay supplies downloaded bytes and a frozen identity
fixture; it is not a fresh Render retrieval or signed-in test. Required pinned
CI and deployed acceptance remain separate gates.

After deployment:

```sh
python scripts/company_evidence_acceptance.py \
  --case SPOT --case TSM --case ASML --case NVO \
  --inspect-source --output /tmp/company-evidence-post207.json
```

Then rerun the complete 33-case cohort and fresh signed-in answers plus saved
History/Research Trail checks. Broader foreign-report incorporation, other table
rows/topics, future annual filings and arbitrary jurisdiction reports still need
separate review. Continue the broader roadmap after launch gates are verified.
