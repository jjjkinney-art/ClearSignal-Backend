# Source-backed Services operating-risk disclosures

Status: initial AAPL coverage; production acceptance pending.

An explicit Apple Services evidence question that also asks about operating risk
now requests bounded SEC periodic filings. If the newest quarterly report has no
qualifying risk disclosure, discovery can use the latest annual report in the
remaining slot of the existing two-document default budget. Revenue-only
questions do not trigger annual-risk discovery. No additional model calls are
introduced. The existing router evidence deadline still applies.

The extractor accepts a complete, qualitative sentence only inside a recognized
Item 1A Risk Factors section with an explicit next-section boundary. The sentence
must connect Services, third-party applications, or digital content to a stated
adverse possibility. Generic company-wide “products and services” warnings,
ambiguous pronoun references, numerical assertions, cross-references, table-of-
contents entries, incomplete sentences, unsupported issuers and provenance are
excluded. It produces at most two disclosures per document.

Each disclosure retains its exact normalized-text span, the retrieved document's
SHA-256 identity, SEC accession URL, filing date and section. It is classified as
an issuer-disclosed risk, not a verified occurrence, probability, quantified
impact or directional thesis change. No quantitative fact is created from it.
Admission still excludes unavailable, conflicting, superseded and post-boundary
evidence. The source answer validates the producer metadata again and uses the
original admitted-reference IDs, including gaps left by rejected items.

The answer includes the dated quote and states what remains unverified. When no
risk qualifies, it says so rather than supplying a generated risk explanation.
The Services evidence boundary continues to withhold unsupported margins,
forecasts, headlines and conclusions before persistence and emission. Account
ownership and guarded shared ticker routes are unchanged.

## Validation

Regression coverage includes exact spans; duplicate collapse; annual fallback;
document limits; provenance and malformed metadata; wrong issuer; numerical and
instruction-like text; historical admission; stable citation IDs; and the
pipeline's saved/emitted response under both authentication configurations.

The excerpt fixtures quote Apple's 2025 10-K but have synthetic surrounding
section markup. An additional manual extraction check used the full primary SEC
HTML through the existing ingestion parser (1,520,316 bytes, 120,000 bounded
normalized characters). Two disclosures qualified and both offsets matched the
original normalized text exactly. This verifies one filing layout, not universal
risk extraction or live production latency.

Primary source:
https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm

## Deployment acceptance and expansion

After deployment, run a new signed-in investigation:

> What is the strongest current public evidence for Apple’s Services revenue growth, what operating risk could invalidate the thesis, and what remains unverified?

Check that a qualifying risk has its own citation and filing date, and that the
answer keeps its probability, quantified impact and thesis direction unverified.
Inspect the linked filing; reopen the saved investigation and confirm the same
answer and source IDs persist. If the source deadline or extraction rejects the
filing, an explicit missing-risk state is the expected fallback.

Before claiming broader coverage, add issuer-specific section/layout acceptance
for other companies and jurisdictions; relevant risk retrieval and ranking;
PDF/OCR anchors; amendment/version handling for qualitative disclosures; and
cross-sector benchmark adjudication of risk relevance and completeness. Quantified
risk effects require independently bound evidence and remain outside this slice.
