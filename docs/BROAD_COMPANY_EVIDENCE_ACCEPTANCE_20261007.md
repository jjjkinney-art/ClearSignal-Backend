# Broader company evidence acceptance

Status: implementation and deterministic acceptance complete; expanded live SEC
retrieval and signed-in production acceptance remain open. Recorded 7 October
2026 in New Zealand (6 October UTC). Base: `c8b55037e60f806cbad6450b0ae9e1a904701eee`.

## Problem and resulting behavior

The earlier issuer-risk extractor required one of four hardcoded company/topic
pairs. Correct routing could therefore still end in a risk-evidence gap for
other companies. The extractor now selects a narrowly defined topic independently
of the issuer, then requires an exact current SEC-directory CIK for additional
issuers. An unknown, conflicting or unavailable identity cannot qualify evidence.
The four reviewed issuer identities retain compatibility with their earlier paths.

Shared topic families cover Cloud, Data Center, subscription renewals, staffing,
energy supply, patient safety, customer concentration, distribution, supply
chains, cybersecurity, credit losses, liquidity, interest rates, drug development,
patents, membership renewals, marketplace sellers, commodity prices, occupancy,
production quality, export controls and government contracts. Apple's Services
slice keeps its own reviewed matching and shorter quote limit.

This removes the need to register each additional US issuer in the risk module;
it does not establish support for every question, document layout or jurisdiction.
Multiple requested risk topics are withheld until per-topic completeness is
represented. Foreign 20-F/40-F layouts, risk ranking, quantified effects, forecasts
and complete segment-growth coverage are outside this expansion.
Possessive company names are removed only as exact verified name spans. A topic
before that name remains part of the question; a plural possessive such as
Liquidity Services' does not accidentally request the separate liquidity topic.

Evidence still requires primary SEC periodic HTML, a matching issuer accession
URL, a dated and complete Item 1A section, explicit topic relevance and an exact
quote span. Unsupported/generated implications are removed before saving. A
requested numeric metric may answer its own part; it cannot fill a missing risk
slot. Complete nonnumeric risk sentences may now reach 900 characters. The
document-reference limit expands only for hashed SEC Risk Factors references;
other reference types retain 300 characters. Missing or overlong support fails
closed. No additional LLM calls, shared ticker writes or background delivery are
introduced; the existing two-document default and router deadline remain.

## What was verified

| Layer | Result | Limit |
| --- | --- | --- |
| Frozen cohort | 33 issuers, 11 sectors, 24 question-topic labels | Not a complete market sample or current market-cap classification |
| Public routing handoff | 99 checks pass: ticker, official name and question-only input for every cohort issuer | Providers/models blocked at handoff; not live analysis execution |
| Expanded regression module | 146 tests pass | Positive documents are authored fixtures except one reviewed WD-40 sentence with synthetic section markup |
| Relevant regressions | 581 tests pass across 19 isolated files | Local Python 3.12; required pinned Python 3.11 CI is separate |
| Cached full SEC HTML replay | Four issuers pass parser, extraction, admission, exact-span and answer-citation checks | Previously downloaded files; not a fresh download or signed-in request |
| Expanded live retrieval | Pending | Direct SEC request from this execution environment timed out; no 33-issuer live pass is claimed |
| Signed-in expanded issuer/topic matrix | Pending after deployment | Earlier routing/persistence acceptance does not establish new risk extraction coverage |

Tests reject foreign-issuer URLs, unrelated topics, wrong or truncated sections,
ambiguous questions, identity outages/conflicts, malformed provenance, unsupported
forms, corrupted quote spans and numeric risk assertions. They also verify complete
saved answers, owner isolation and correct AA/AAPL History filtering. Collection
must remain clean under the repository's required CI workflow.

The reviewed WD-40 distribution sentence exposed a real filtering gap: the
adverse-effect matcher accepted `disrupt` but missed `disruption`. That word family
now qualifies when the other identity, section, topic and provenance checks pass.
This one source excerpt does not certify the complete WD-40 filing pipeline.

Registry: [company_evidence_coverage.v1.json](../validation/company_evidence_coverage.v1.json).
Cached replay: [four-filing report](COMPANY_EVIDENCE_CACHED_REPLAY_20261007.json).
Original failing baseline: [cross-company audit](CROSS_COMPANY_COVERAGE_AUDIT_20261006.md).

## Live retrieval procedure

The new CLI uses the actual bounded SEC retriever, admission and source-answer
gate. It makes no model calls or account writes and needs no bearer token. Configure
`SEC_USER_AGENT` with a valid application/contact identity through the normal local
environment; do not put credentials in a report. From the deployed revision's
local checkout, first run the companies that exposed the broader problem:

```bash
python3 scripts/company_evidence_acceptance.py \
  --case DOCU --case MAN --case AA --case ACHC --case ACMR --case WDFC \
  --output company-evidence-canary.json
```

Then run the complete registry:

```bash
python3 scripts/company_evidence_acceptance.py \
  --output company-evidence-coverage.json
```

Progress goes to stderr; JSON goes to stdout and the selected output file. Each
completed case checkpoints a report so interruption leaves a visibly incomplete,
failing result. Gaps and retrieval errors exit nonzero; unsupported foreign layouts
are not silently counted as successful risk answers. The complete registry's four
foreign entries deliberately expose those remaining gaps. Use repeated `--case`
selections to evaluate a declared supported release cohort separately.

Passing requires an admitted risk disclosure, its original exact document span,
dated source identity, explicit citation in the answer and an attributed answer
state. A page returning HTTP 200, filing metadata, consolidated revenue or a safe
gap message does not count as a supported risk answer. Reports contain public
document identities and quote hashes, not tokens or private account data.

## Release decision

Do not close the broader company launch gate from deterministic routing or fixture
tests. After required CI, deployment and live SEC canaries, run the cohort questions
in signed-in Intelligence Mode. Inspect the cited filing, verify question-part
relevance, reopen the saved investigation, check History/Research Trail ticker
filters, and confirm unsigned/foreign-owner access is denied. Preserve exact
deployment revision and pass/gap/error counts. Safe gap behavior and supported
answer usefulness must be assessed separately.

Existing benchmark requirements for numerical accuracy, source binding, useful
answer rate, latency, freshness and zero issuer-level stop-ship failures remain.
Unrestricted company/topic promises remain blocked until supported scope is
demonstrated. Shared ticker-wide research routes stay guarded; older analyses are
not backfilled. Every CLI report explicitly leaves `launch_cleared` false.
