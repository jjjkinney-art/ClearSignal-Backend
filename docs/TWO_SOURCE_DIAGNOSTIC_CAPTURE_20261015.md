# Two-source diagnostic capture proposal and offline analyzer

Preparation and review only. This document and the local-file analyzer authorize
no HTTP request, pilot, spending, or change to existing capture policy. The
dedicated capture executor and its approval manifest are not implemented here.
The existing six-case pilot must not be silently repurposed for this plan.

## Why new source data is needed

The PR289 saved ACHC core comparisons carry inline bindings to the Q2 filing,
while its monitoring comparisons carry Company Facts bindings to Q1. Core has
an existing filing-body fallback; monitoring has no document-fetch slot. No
raw Company Facts response was retained. Offline synthetic checks show that
complete same-concept Q2 pairs select Q2; only Q1 or ineligible Q2 records can
select Q1, while missing Q2 priors and conflicting Q2 records abstain. These
checks constrain possibilities but do not identify the historical response.

NPK's saved diagnostics report 164 screened sentences and no business description.
Counts alone do not show which source wording was rejected or whether it should
qualify. Repeating an unchanged six-case run will not recover that missing text.

## Proposed exact source scope

One GET each, no transfer of slots between sources:

| Source | Exact URL | Body envelope |
| --- | --- | ---: |
| ACHC Company Facts, CIK 1520697 | https://data.sec.gov/api/xbrl/companyfacts/CIK0001520697.json | 16,777,216 bytes |
| NPK annual filing, CIK 80172, 10-K filed 2026-03-13 | https://www.sec.gov/Archives/edgar/data/80172/000143774926008214/npk20251231_10k.htm | 15,000,000 bytes |

The NPK URL/form/date come from persisted PR289 primary filing references. A new
review must validate that binding from the immutable record, not infer it from
a ticker or filename. This does not reuse historical execution authority.

The eventual implementation must preserve explicit proxy/CA and credential
isolation, media and encoding checks, strict declared/observed byte limits,
bounded reads, credential reflection/canary checks, durable at-most-once claims,
halt/fencing/late-worker handling and fresh output/ledger creation. No redirects,
retries, discovery calls, models, FMP, NewsAPI or FRED. Preserve existing 480-second
whole-run and applicable stage supervision; do not extend them to force success.
Existing reviewed document validation is mandatory wherever applicable. Exceeding
a bound or a timeout fails closed. No smaller alternate filing or truncation.

The package must explicitly propose retaining the two bounded public response
bodies, safe source receipts (URL, HTTP status/media/encoding, observed byte count,
body hash and capture time), and derived diagnostics. Previous approvals did not
authorize this additional content retention. The new exact-diff review, passing
checks and separate single-use approval must cover it before capture. Do not
store authorization headers, contact values or credentials. A current snapshot
cannot retrospectively establish the content of the old Company Facts response.

## Offline analyzer implemented in this change

`python -m validation.source_gap_analysis --achc-facts LOCAL_JSON --npk-html
LOCAL_HTML --output FRESH_REPORT_JSON` reads supplied local files only. There is
no URL-fetch option or execution/approval creation. Inputs are bounded before
parsing; existing outputs cannot be overwritten and final-path symlinks are refused.

ACHC uses the existing Company Facts parser, duration checks and comparable-fact
producer independently for explicit core concepts and USD/EUR. It reports parsed
and eligible counts, latest period ends and whether a comparison qualified, without
exporting financial amounts or inventing rejection causes. Aliases remain separate.

NPK uses the existing visible-HTML normalizer and complete business-section window.
It proposes at most two complete candidate sentences from each of three review
buckets: length, numeric/forward wording and other. At most six samples, 600
characters per complete sentence and 1,800 text characters total. Longer sentences
retain offsets, length and hash without text; no quote is clipped. The normalized
text/body hashes and byte count tie samples to supplied bytes. UTF-8 with replacement
is assumed and reported; capture encoding is not independently validated here.

These review buckets are not final production rejection reasons: production also
handles heading removal, issuer identity and additional predicates. Neither sampled
text nor a successful local analysis is admitted evidence. The report explicitly
does not verify HTTP origin, media, capture time, or authenticity. Source receipts
and independent review are still required. No source content is executed.

## Before any execution

Review and test the dedicated fixed two-source executor and body-retention contract;
generate a fresh source/configuration-bound manifest and exact command; validate the
actual executor offline; preserve all nine historical runs; obtain a new separate
approval. US$0.52 remains a ledger allowance, not an invoice ceiling. No invoice
limit or new spending authority is established by this proposal.

After capture, stop. Compare ACHC parsed/eligible/selected Q2 records and use NPK's
complete sentences to reproduce only demonstrated defects offline. Do not tune
unseen-company coverage to a single ticker or relax evidence admission from counts.
