# Selected comparison claim binding — October 8, 2026

## Deployed baseline and live acceptance

PR212 is deployed at e9607e36d76bc31e4c90899a8419c82a1c5718a6.
The user supplied a Render post212 full source acceptance run with 33/33 pass.
Signed-in automatic scope, save, reload, Recall, explicit selection, comparison,
and comparison reopening passed. This clears those tested regressions, not the
broader launch or universal public-information coverage gates.

A real September 26 saved Tesla investigation identified Supercharger network
advantage and vehicle deliveries as its confirmation metric. The October 8 live
comparison retrieved five periodic SEC filings, all older than that record.
It preserved the recorded conclusion and honestly returned unverified direction.

Tesla's investor-relations site lists an October 2 production/delivery release:
https://ir.tesla.com/press-release/tesla-third-quarter-2026-production-deliveries-and-deployments
The public-source search found this release; the live analysis did not retrieve
it. It has not been injected into a production answer or treated as a completed
positive comparison acceptance. Primary release ingestion is the next retrieval
work item, with issuer, publication date, readable content, claim attribution,
freshness, and canonical source identity required before comparison admission.

## Reproduced comparison defect

Two red regression tests showed that the orchestrator could label a directional
conclusion verified even if it had no citation, or cited only an old source.
It created its change claims from eligible source titles and automatically
assigned those sources' IDs, rather than validating the actual conclusion.

Synthesis also ranked/deduplicated evidence and then numbered the resulting
prompt positions. Those positions could differ from the canonical E IDs exposed
by source inspection, particularly when admission removed an earlier source.

## Repair

Validate the actual comparison conclusion's cited sentences. Each sentence must
cite an eligible newer source. Numeric [1] citations normalize to E1; canonical
[E1] citations retain their identity. Missing, old, unknown, partial, or excessive
claims fail closed. Conflicting structured and textual direction also fail closed.
Source-title placeholders no longer authorize a directional conclusion.

Copy evidence specifically for the synthesis prompt and bind canonical IDs from
the admitted reference contract before ranking or deduplication. Preserve original
admission object identity for SEC fact projection and leave provider/cache objects
untouched. Unmatched prompt records receive an unattributed marker. The internal
citation field is excluded from serialized evidence. Source inspection and the
synthesis prompt now share IDs, including gaps left by blocked sources.

The selected-history prompt requires actual conclusion citations. Prompt evidence
ranking, token bounds, and source admission remain in place.

## Limits and next acceptance

807 relevant checks passed across two disjoint regression suites. One existing
prompt-reduction A/B artifact test was skipped because its artifacts are absent.
The two new negative comparison cases failed before the repair and pass after it.
Positive citation-bound comparison, admission-removal identity, prompt ranking,
source-evidence, selected memory, API/security and synthesis regressions passed.

Citation membership is not semantic entailment. These checks do not prove that a
source justifies every interpretation or numerical claim, and the remaining
semantic accuracy gate stays open. Conservative sentence parsing can return an
honest gap for unusual formatting or abbreviations. No historical record dates
were changed to manufacture a positive test.

After CI and deployment, rerun the no-newer-evidence saved comparison and full
source cohort. Then implement primary release retrieval and repeat the real
Tesla comparison with independently checked source dates and claim meanings.
