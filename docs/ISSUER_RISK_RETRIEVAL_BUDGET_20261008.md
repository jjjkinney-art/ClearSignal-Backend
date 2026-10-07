# Issuer-risk retrieval budget — 8 October 2026

## Production evidence

After PR #201 deployment, the owner ran the read-only company-evidence CLI
with source inspection for JPM and NFLX. Both completed with
`exact_source_spans_and_answer_citations`, no retrieval failures and two
admitted annual-filing disclosures apiece. The quarterly reports produced no
qualifying disclosures; the existing two-document fallback reached the annuals.

| Issuer | Total retrieval | Quarterly download/parse/inspection | Annual download/parse/inspection | Quarterly / annual risk extraction |
|---|---:|---:|---:|---:|
| JPM | 17,376 ms | 7,651 ms | 9,203 ms | 20 / 66 ms |
| NFLX | 3,195 ms | 1,451 ms | 1,673 ms | 4 / 4 ms |

The same deployment's signed-in Netflix answer contained two cited retention
disclosures. JPM's answer correctly withheld the risk claim. Both fresh
investigations preserved two messages after reopening and appeared under their
correct tickers in account-owned History and Research Trail. The live router's
10-second evidence pool cannot wait for a 17.4-second provider task. CLI source
success therefore does not establish successful live delivery. Source-inspection
timings include diagnostic work and are not an exact profile of the earlier
live request; its precise provider trace was not supplied.

## Remediation

Non-Apple periodic-risk requests ask the public document reader to omit its
second, whole-document HTML table-grid pass. The risk extractor consumes only
normalized visible text and exact offsets. Visible text inside tables remains
in the text pass. Apple Services and ordinary KPI requests retain table grids.
The text parser also reuses its already-normalized full text instead of joining
and normalizing the entire filing twice when preparing the retained window.

URL, redirect, public-address, content-type, byte and retained-section limits
remain in force. Raw-body hashing, hidden-content exclusions, issuer identity,
complete-section, sentence, admission and citation requirements remain unchanged.
The router still waits at most 10 seconds for evidence; this change does not
extend the deadline or reattach a late provider result to a completed answer.

An authored, table-heavy 11,970,178-byte HTML replay ran locally twice per mode:
median parsing/fetch-stub time was 3.139 seconds with table grids and 1.484
seconds without them. Both modes produced the same content and retained-text
hashes and the same 1,260,000-character window origin. Network and DNS were
stubbed for this replay. This is a local work-reduction measurement, not a
production latency guarantee or replay of JPM's actual filing body.

Regressions compare both modes through risk extraction, admission and answer
citations, including a late complete section, a visible-table disclosure, hidden
decoys, and default KPI tables. Text-only calls must still reject oversized files.
Local validation passed 601 distinct tests across ingestion, live extraction,
source inspection, source binding, risk sections/passages, Services tables,
company routing, owner-scoped memory and legacy-memory boundaries. The broader
regression modules ran in separate interpreters. Required remote CI is pending.

## Remaining gate

Required CI must pass for the final PR head. After deployment, rerun JPM and
NFLX source acceptance and fresh signed-in analyses, including reopen and history
checks. JPM must deliver its source-bound risk answer within the existing live
deadline; a faster local parser alone does not close that gate. If it remains
withheld, inspect the request's `issuer_kpis` abandonment/extraction logs before
changing retrieval order or budgets.

XOM's successor/predecessor identity linkage remains a separate unresolved
coverage gap. The latest complete 33-company run remains 20 passes and 13 gaps;
these two targeted source passes do not certify the full cohort or launch.
