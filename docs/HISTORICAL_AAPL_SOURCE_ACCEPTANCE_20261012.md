# Historical AAPL source acceptance — October 12, 2026

Status: **the observed historical revenue source-answer/save-reopen slice passed**.
This is not overall launch clearance, complete Services-thesis acceptance, or a
600-case benchmark result.

## Evidence origin and deployment identity

The parent coordinator supplied the user's production screenshots, Render log
observations and its independent SEC verification. This worker did not execute
the production request, inspect the user's private account, or independently
repeat that SEC verification. The observations below are an attributed acceptance
record, not newly generated live measurements. Raw screenshots/logs remain with
the parent/user; they are not attached to this repository record.

- Backend: `24181931c6340b9bcfcd47ddac37e9273ed6a8f1`, identified by the supplied
  Render production evidence.
- Frontend: PR83 merged as `9f31521efa70200944df1adfe02eb09e5fb1ab82` after
  exact-head CI and independent review of the navigation-race repair. The parent
  reported rollout/status evidence and the user supplied a production screenshot
  showing the historical control. A new complete production-alias dashboard SHA
  binding was **not** supplied. The merge identity and observed UI must not be
  represented as stronger deployment-attestation evidence than this.
- Request: `What source supports Apple's revenue?`, explicit company `AAPL`,
  historical date `2024-08-15`, request boundary `2024-08-15T23:59:59Z`.

## Observed result

The user-visible answer reported revenue of $85.777 billion versus $81.797 billion,
with 4.9% growth. The parent independently checked SEC accession
`0000320193-24-000081`, filed August 2, 2024. The source predates the requested
boundary. The supplied browser evidence shows that the SEC filing-index link
opens the correct filing; this is not a claim of a direct table/row deep link.

Screenshots show the confirmed cutoff, unassessed confidence and two saved
messages. Refresh/reopen preserved the answer, citations and original message
timestamps. The cutoff display is:

> Answer evidence cutoff: 2024-08-15 · 23:59:59 UTC.

The supplied Render observations report conversation creation HTTP 201,
`/ask` HTTP 200 at 04:16:05 UTC, and conversation reads HTTP 200. Later reads at
04:20:49 and 04:20:58 UTC show no additional `/ask`. No LLM stages were observed
for this run. **Zero billing usage was not directly verified.** This explicit
source request must not be generalized to arbitrary historical questions, which
can still use model analysis. No statistical latency conclusion is inferred.

## Reconciliation of the original Services incident

The [October 5 browser record](LAUNCH_BROWSER_MEMORY_ACCEPTANCE_20261005.md)
reproduced an unsupported approximately 72% Services-margin assertion and
insufficient question-specific grounding. Saving worked; claim binding did not.
Consolidated revenue cannot substitute for Services revenue, margin or risk.

Later evidence supersedes the earlier failing status for the implemented source
slice:

- [Services risk acceptance](SOURCE_BACKED_SERVICES_RISKS.md) records signed-in
  October 6 verification, saved-answer persistence and inspection of the risk
  quote in the linked SEC filing. It preserves unverified probability, impact
  and thesis direction.
- [Post209 acceptance](COMPARISON_EVIDENCE_BOUNDARIES_20261008.md) records 33/33
  source-inspection passes and fresh signed-in AAPL/SPOT/ASML/TSM/NVO/AA source
  answers, all six reopening with two messages and citations. An older Apple
  source answer also displayed unassessed confidence.
- The [roadmap's later checkpoint](UNIVERSAL_PUBLIC_INTELLIGENCE_ROADMAP.md)
  records post213 33/33 passes, superseding its older post203–206 cohort gaps.
  It explicitly keeps broader semantic quality and universal coverage open.

Do not reopen those superseded extraction/source-display failures merely because
historical documents retain their earlier findings. Nor does this October 12
consolidated-revenue smoke establish complete Services thesis quality or a
Services margin. Those are different assertions with their own evidence needs.

## Offline regression performed by this worker

Code base: backend `24181931c6340b9bcfcd47ddac37e9273ed6a8f1`. Python 3.11.17,
repository-pinned requirements, one fresh interpreter per test file. Existing
model/provider stubs were retained. A Python audit hook rejected socket DNS,
connect and send-to events; each final suite recorded **zero network attempts**.
No live/public-provider or model requests occurred in these test runs.

| Suite | Passed | Relevant evidence |
| --- | ---: | --- |
| `tests/test_source_answer.py` | 26 | Original browser wording; removes unsupported 72%; filing metadata and company-wide metrics cannot fill Services claims; serialized answer withholding |
| `tests/test_services_revenue_evidence.py` | 27 | Frozen Apple table; quarter/year-to-date separation; wrong issuer, ambiguous/mismatched periods, missing provenance/support, conflicting amounts and future filing rejection |
| `tests/test_services_risk_evidence.py` | 64 | Exact quote spans/hash/date; wrong issuer; missing risk cannot be replaced by generated prose; future disclosures blocked; bounded annual fallback |
| `tests/test_source_evidence_latency.py` | 45 | All 33 frozen cohort questions skip model stages in gaps; historical current-source exclusion; ordinary analysis retains mocked model stages |
| **Total** | **162** | **All passed; no production re-execution** |

These are frozen/authored fixtures, not a fresh full-filing or signed-in cohort
capture. Risk excerpts have synthetic section markup. The latency suite emitted warnings; its test duration is not production latency
evidence.

The initial audit-hook run caught an unstubbed SEC-directory lookup from
reporting-coverage composition in three older suites; it was blocked before a
connection. Test-local frozen AAPL directory fixtures now remove that attempted
lookup. No production code defect was reproduced and no production code changed.
No gate, fixture evidence assertion, registry, holdout or execution flag changed.

To reproduce ordinary isolated checks with installed requirements:

```sh
for suite in test_source_answer test_services_revenue_evidence test_services_risk_evidence test_source_evidence_latency; do
  python -m pytest -q -o addopts= "tests/$suite.py" || exit 1
done
```

For the stricter offline check, invoke `pytest.main` in a fresh Python process
per file after installing a `sys.addaudithook` that raises on
`socket.getaddrinfo`, `socket.connect` and `socket.sendto`; count those events and
fail the run if any occurred, even if application code caught the exception.
The worker's final counts were 0/0/0/0. Dependency installation was separate from
test execution and did not call product/data/model providers.

## Closure and remaining gates

The narrow historical source-answer/UI/save-reopen blocker can be closed against
the supplied evidence, with its provenance and frontend-attestation limit above.
A repeated paid analysis or new account access is not needed to establish that
observed result. No further product fix is indicated by these offline regressions.

No new 33-company live source run was performed: post209/post213 already record
full source-cohort passes, and this review found no new extraction failure. Those
older passes are not silently relabeled as a full-cohort run on backend24181931.
If the release coordinator requires a fresh full-cohort gate on that exact
revision, the source-inspection CLI is a separate network-enabled SEC check,
without paid model calls or private-account access. It cannot establish general
thesis usefulness or replace signed-in acceptance.

The [finalized benchmark setup](benchmark_proposal_20261011/reconciliation/FINALIZED_SETUP.md)
remains 100 issuers, 600 uncaptured cases (480 development/120 holdout), with
execution disabled, 20 reserved issuers unchanged and external prior exposure
unknown. Capture, primary-source numerical/citation adjudication, blind
usefulness review, per-tier quality parity, personalization and international
coverage remain broader work. Neither source-gap safety nor this narrow pass
satisfies the >=90% useful cited answers per tier or other frozen quality gates.

The [production gate](PRODUCTION_ACCEPTANCE.md) and [beta runbook](BETA_LAUNCH_RUNBOOK.md)
retain separate account-isolation, operational and applicable billing requirements.
Any unrecorded production acceptance needs the appropriate user/operator access;
provider-backed research capture requires explicit execution/budget authorization.
No such authorization or access is needed for the completed offline work here.
The 600-case benchmark was not executed. Overall launch readiness is not asserted.
