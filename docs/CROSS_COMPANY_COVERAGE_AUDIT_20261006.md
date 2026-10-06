# Cross-company launch coverage audit — 6 October 2026

**Decision: unrestricted public-company coverage is blocked.** DocuSign's
missing resolver entry was one example of a broader integration gap. Passing
Apple and the reviewed risk slices does not establish broad company coverage.

This audit uses the code proposed in PR #192, including the DocuSign routing
fix, on top of main `e0df20f20f6f1bee45d801301f8885738543e4d4`. It does not
claim those changes are deployed. The machine-readable
[report](CROSS_COMPANY_COVERAGE_AUDIT_20261006.json) includes source fingerprints.

## Fixed cohort and observed results

The complete existing benchmark registry contains 18 companies across eight
sectors. Its size tiers are frozen as of 29 September, not current market-cap
measurements. Every company was tested by isolated ticker and company name,
then through the public `route_question` entry point with an explicit ticker,
explicit name, and company name in the question alone.

| Frozen benchmark tier | Companies | Correct handoff in all three forms |
|---|---:|---:|
| Mega/large | 12 | 12 |
| Mid | 3 | 2 |
| Small/micro | 3 | 0 |
| Total | 18 | 14 |

Identity resolution passed 28/36 checks; routing passed 42/54. A correct handoff
means the modern pipeline received the expected ticker. It does **not** mean
an analysis was run, its claims were accurate, or the issuer's requested topic
is supported.

| Company | Reproduced failure |
|---|---|
| Alcoa (`AA`) | Symbol and name unresolved; question-only input reaches general finance |
| Acadia Healthcare (`ACHC`) | Symbol and name unresolved; question-only input reaches general finance |
| ACM Research (`ACMR`) | Symbol and name unresolved; question-only input reaches an entity suggestion |
| ManpowerGroup (`MAN`) | Explicit ticker silently hands off **Viatris (`VTRS`)**; name unresolved; question-only input reaches general finance |

The `MAN` error is a fuzzy match to the alias `mylan`. The explicit-company
route uses the permissive `detect_company` wrapper, so a supplied ticker can be
reinterpreted as a different issuer. This is a wrong-company research risk,
not merely an empty answer.

With PR #192, explicit unresolved source requests produce a plain identity-gap
answer rather than legacy analysis. That protects some failures but does not
repair missing identities or the `MAN` substitution. Question-only general and
suggestion responses also serialize as JSON in saved assistant text under the
current response-contract helper: four cohort routing probes reproduced this.

## Official-source availability

The SEC ticker snapshot contained 10,434 ticker rows; 227 exactly match the
236-entry local company registry. SEC rows include share classes and foreign
issuers, so these counts are an identity-coverage comparison, not a product
quality percentage or an active-common-stock universe.

Independent read-only SEC checks sampled AAPL, DOCU, AA, ACHC, ACMR, MAN and
ASML. The report records HTTP outcomes, exact issuer IDs, filing inventories,
fact taxonomy counts and response hashes. Availability of a filing or fact
inventory does not establish topic extraction, period comparability, current
conditions, or successful application routing. In particular, the missing and
misrouted cohort entries have official SEC identities and public records; their
failure cannot be explained solely by being smaller companies with no data.

An initial Python-requests run timed out on Apple submissions; its companyfacts
request and both endpoints for the other six issuers succeeded. A separate
curl run timed out on Apple submissions and ManpowerGroup facts. The report
preserves both attempt summaries and combines successful endpoint observations:
six of seven sampled issuers have both records verified, including every
missing/misrouted cohort issuer. Apple submissions remain unverified in this
canary. An access timeout must remain distinct from an unsupported issuer or
absent evidence, and these operator-side outcomes do not measure production
retrieval reliability.

## Topic relevance is a separate blocker

The qualitative risk extractor currently has four reviewed issuer/topic pairs:
Apple Services, Microsoft Cloud, NVIDIA Data Center and DocuSign subscription
renewals. Other topic requests do not inherit that capability.

Four isolated source-gate probes supplied a consolidated-revenue statement as
a decoy for an operating-risk question. DocuSign correctly withheld it. Etsy
seller retention, Alcoa smelter energy supply and Acadia facility safety instead
accepted the unrelated statement as `attributed` and retained the generated
bull thesis. These are synthetic gate reproductions, **not** seven live /ask
analyses. They demonstrate that citation binding alone does not enforce topic
relevance outside the reviewed slices. The source gate must explicitly withhold
unsupported question parts and wider generated conclusions.

## Scope and limitations

- Router probes replace the modern pipeline with a handoff marker, replace
  general agents with a marker response, and stop legacy/provider boundaries.
  They make no LLM calls or account writes.
- Live checks query only official read-only SEC metadata/fact endpoints.
- No authenticated production `/ask`, cross-account memory, History or Research
  Trail matrix was exercised. Prior Apple smoke passes remain valid within
  their original scope; they do not certify this cohort.
- Foreign filing routing and extracted claim quality remain unverified even
  when an issuer has SEC records. The audit is not a market-performance study.
- The full SEC snapshot was compared by exact registry membership; fuzzy
  resolution was tested only for the fixed 18-company cohort.
- Account ownership, guarded shared ticker routes and no implicit backfill
  remain required. This audit changes none of those boundaries.

## P0 remediation and release criteria

1. Make an explicit symbol authoritative: exact verified security identity or
   clarification, never an automatic fuzzy substitution. Cover share classes,
   foreign identifiers and temporal aliases with reviewed identity rules.
2. Connect verified issuer discovery to the public router. Adding only the
   four missing benchmark entries is insufficient for unrestricted coverage.
   Missing/ambiguous/unavailable identity must return a precise coverage state.
3. Require question-part relevance as well as provenance. Unsupported topics
   must not substitute consolidated metrics or preserve an uncited investment
   case. Return useful supported parts and clearly identified evidence gaps.
4. Keep displayed and saved answers aligned for success, partial, identity-gap
   and suggestion shapes. General fallbacks must not masquerade as company
   evidence, and saved threads must show readable answer text.
5. Rerun all 54 routing probes with **zero wrong-issuer handoffs** and correct
   cohort identity. Run issuer/topic negative controls through admission and
   the real pipeline, not just an isolated source gate.
6. After deployment, run a bounded signed-in production matrix spanning all
   three size tiers and multiple sectors. Check cited claims against sources,
   period/entity match, saved/reopened text, History/Research Trail, and cleanup.
   Test unsupported and foreign cases for honest gap states.
7. Expand the release benchmark beyond these 18 entries using the existing
   registry targets, then require the roadmap's useful-answer threshold within
   explicitly declared supported coverage. These samples cannot certify all
   public companies.

Unrestricted company marketing and public launch stay blocked until these
criteria pass. A narrowly supported beta still requires zero wrong-company
answers, honest unsupported states, and its existing privacy/release gates.

## Reproduce

Offline router/topic audit (no external fetch):

```bash
python3 scripts/company_coverage_audit.py --output /tmp/company-coverage-audit.json
```

Optional official-source snapshot and independent read-only checks:

```bash
curl -fsS --max-time 20 -A 'ClearSignal research support@clearsignal.ai' \
  'https://www.sec.gov/files/company_tickers.json' -o /tmp/sec-company-tickers.json
python3 scripts/company_coverage_audit.py \
  --sec-snapshot /tmp/sec-company-tickers.json \
  --live-sec-transport curl \
  --live-sec-tickers AAPL DOCU AA ACHC ACMR MAN ASML \
  --output /tmp/company-coverage-audit.json
```

Exit `1` means at least one coverage check failed; the checked-in baseline is
intentionally red. Unit tests validate the audit's failure detection and do not
turn this product coverage gate green. No bearer token is needed for this audit.
