# Source-backed issuer operating risks

Status: implementation and local extraction acceptance complete; signed-in
production acceptance pending after deployment.

## Supported topics

| Issuer | SEC CIK | Explicit question topic |
| --- | --- | --- |
| Apple | 320193 | Services, App Store, iCloud, Apple Music, digital content |
| Microsoft | 789019 | Cloud, Azure |
| NVIDIA | 1045810 | Data Center, AI infrastructure |
| DocuSign | 1261333 | Subscriptions, renewals, retention |

A question must request risk and a supported topic. This is a bounded qualitative
risk path, not universal company coverage, complete risk ranking, segment revenue
extraction, or a verified assessment of which risk would invalidate a thesis.

At most two complete, nonnumeric sentences qualify per filing. They must appear
inside Item 1A Risk Factors with a recognized closing section, match the topic,
and state a possible adverse effect. URLs must bind to the reviewed issuer CIK.
Quotes retain the exact normalized text span, full-document SHA-256, filing date,
section and original admitted citation ID. Generic summaries, numerical effects,
incomplete text, cross-references, substituted provenance and foreign issuers
cannot fill a risk slot. Microsoft split-word headings are recognized without
rewriting the quoted text. Missing support produces an insufficient-evidence
answer; unavailable or later-than-boundary records remain blocked by admission.

## Retrieval and output boundaries

The existing default budget remains two document attempts, including failed
downloads. Duplicate URLs are not fetched twice. A quarterly report without a
qualifying disclosure can use the latest annual report in the remaining slot.
No new model calls or background monitoring are introduced.

The three new issuer/topic paths can request a 10 MB / 240,000 normalized-character
allowance for periodic SEC HTML filings. General documents retain 2 MB / 120,000
characters. Expanded limits require primary SEC periodic-filing metadata and an
SEC archive HTML URL, and are checked again on every redirect. PDFs, other hosts,
nonperiodic filings and oversized responses are rejected. The router's existing
evidence deadline still applies; a local successful extraction does not establish
production download latency or coverage of every quarterly layout.

For the new risk topics, the source-answer view accepts only bound disclosures.
Consolidated revenue cannot substitute for Cloud or Data Center growth, and a
disclosure cannot establish actual damage, probability, quantified impact or a
directional thesis change. Unsupported generated thesis fields are cleared before
persistence and again before emission. Existing Apple Services numerical evidence
continues through its own source-bound table extractor. Account ownership and
guarded shared ticker research routes are unchanged.

## Validation evidence

`ISSUER_RISK_EXTRACTION_ACCEPTANCE_20261006.json` records a local check of three
full primary SEC annual HTML filings, including byte hashes and matching quote
offsets. All three produced admitted, attributed disclosures with explicit
unverified-impact language. This is parser/extractor/gate acceptance, not a live
signed-in product test or an analytical completeness score.

Automated tests cover issuer/topic mismatches, provenance mutations, truncated and
cross-referenced sections, numerical/instruction-like text, original reference-ID
gaps, historical admission, missing support, bounded fallback/download behavior,
expanded-size restrictions, complete emitted/saved thesis gating, and exact private
conversation persistence with foreign-owner rejection. Excerpt tests have
synthetic surrounding markup; the Microsoft short quote is authored test data.

## Production acceptance after deployment

Run each question in a new signed-in Intelligence Mode investigation:

1. What current public evidence identifies an operating risk to Microsoft's Cloud growth, and what remains unverified?
2. What current public evidence identifies an operating risk to NVIDIA's Data Center growth, and what remains unverified?
3. What current public evidence identifies an operating risk to DocuSign's subscription renewals, and what remains unverified?

Inspect each dated risk citation in the actual SEC filing. Reopen the investigation
and verify the same answer, quote and citation IDs persist. Confirm unsupported
margins, forecasts and directional claims are absent. Repeat the Apple Services
question as a regression. A timed-out or unsupported filing should show insufficient
evidence, never a generated substitute. Production acceptance must be recorded
separately before describing these new paths as live and verified.
