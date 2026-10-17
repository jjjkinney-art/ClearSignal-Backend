# Post-207 production acceptance — 8 October 2026

The owner supplied a complete Render `company_evidence_acceptance.py
--inspect-source` run with **33/33 passes** after PR #207. All four previously
failing foreign issuers also passed the targeted deployed run. PR #207 was
squash merged as `bd7f494c64c02241ff30634e9c6c9d27b56ea9d4`.
The pasted production output does not independently attest the runtime commit.

Fresh signed-in desktop browser checks subsequently used explicit company scope
and the frozen cohort questions, suffixed with `Post-207 launch acceptance
October 8.`. Test investigations remain saved for review. This report contains
public test metadata only, without account identifiers, credentials, private
record IDs, unrelated research or browser screenshots.

## Signed-in results

| Company/topic | Returned evidence | Reload/reopen | History and Research Trail |
|---|---|---|---|
| NVO / drug development | E1: incorporated Annual Report 2025 EX-15.1, 20-F filed 2026-02-04; clinical pipeline risk description and impact, mitigating actions excluded | Same two readable messages and exhibit citation | Correct NVO entry in both |
| ASML / export controls | E1: 20-F filed 2026-02-25; export-control countermeasures, conflicting regulations and legal liabilities | Same two readable messages and filing citation | Correct ASML entry in both |
| TSM / export controls | E1: 20-F filed 2026-04-16; compliance, approvals and potential operational/legal effects | Same two readable messages and filing citation | Correct TSM entry in both |
| SPOT / subscription renewals | E1/E2: 20-F filed 2026-02-10; pricing/retention and competition/user-base effects | Same two readable messages and both filing citations | Correct SPOT entry in both |
| AA / smelter energy supply | E1/E2: 10-K filed 2026-02-26; energy costs/disruption and input-price risks | Same two readable messages and both filing citations | Correct AA entry in both; included under AA, excluded under AAPL in both views |
| AAPL / Services | E1: 10-Q filed 2026-07-31; third-party software/services availability risk | Same two readable messages and filing citation | Correct AAPL entry in both |

All completed answers explicitly distinguish issuer disclosures from independently
verified occurrence, current conditions, likelihood, quantified financial effects
or a directional thesis change. The source-inspection area retains the correct
issuer, filing date and SEC document link. These browser checks inspect the
rendered answers and citation metadata; they do not repeat the raw-byte/hash
and exact-span audit performed by the deployed `--inspect-source` script.

## Response-time observations

These are coarse browser observations measured from submission to inspection,
not server timings or p50/p95 benchmarks. Requests were submitted serially;
navigation and persistence inspection occurred while a request was processing.

| Case | Last observed waiting | First observed complete |
|---|---:|---:|
| NVO | 55 seconds | 70 seconds |
| ASML | 30 seconds | 47 seconds |
| TSM | 24 seconds | 66 seconds |
| SPOT | Initial pending state only | 39 seconds |
| AA | Initial pending state only | 44 seconds |
| AAPL | Initial pending state only | 61 seconds |

Evidence correctness and persistence must not be used to close the latency gate.
The next performance pass should correlate production request traces with
retrieval, agent and synthesis stages, establish an explicit request budget and
compare repeated representative requests before changing execution behavior.
Source inspection in `router_service.py` confirms that these narrow evidence
questions still execute the broader analysis and synthesis pipeline before
`apply_source_answer_gate` installs the source-bound answer. This is a candidate
for investigation, not an established cause of the observed wait times.

## Acceptance limits and next work

The four repaired foreign issuer/topic pairs and both domestic controls pass the
fresh-answer, saved-investigation, History and Research Trail checks above.
The new Alcoa record does not appear under AAPL; an older erroneous Alcoa record
remains historical and was not rewritten. This is one signed-in account and a
six-case desktop sample, not a fresh signed-in
33-company matrix, mobile acceptance, live cross-account isolation test or
unrestricted public-company certification. Existing full-launch gates remain
open, including latency, freshness, monitoring and answer readability.

Prioritize measured latency and answer readability, then continue the universal
evidence schema/source-quality and
verified-memory workstreams. Keep source identity, attribution and ownership
checks intact throughout those changes.
