# Source evidence response latency

After post207, the owner reported all 33 production company evidence cases passing.
Signed-in checks also passed for SPOT, ASML, TSM, NVO, AA and AAPL; the separate
post207 acceptance record is proposed in PR208. Those checks observed long waits
but did not measure server p50 or p95.

## Change

Source-demand questions previously retrieved and admitted evidence, ran the
question answerer, five specialist agents and synthesis, then replaced their
narrative with a deterministic attributed answer. They now build that evidence
view directly after admission, skipping those seven discarded model stages.
Ordinary thesis, valuation and selected comparison questions retain the model
pipeline. Retrieval and source admission, exact issuer binding, quote/hash
verification, claim references, freshness gates and owned persistence remain
on the existing path. An unavailable claim still produces an honest gap.

These responses expose `routing.response_mode=source_evidence` and
`investment_thesis.score_source=not_assessed_evidence_view`. The numeric
confidence default is retained for schema compatibility; consumers must treat
it as unassessed. The paired frontend change labels both new and saved source
views as unassessed and renders answer prose as paragraphs beneath a heading.

## Validation

486 backend checks passed with repository-pinned FastAPI/Starlette/Pydantic/PyJWT.
Coverage includes every cohort question skipping models in an evidence gap,
attributed issuer risk cases, conflicting sources, downstream gate reapplication,
memory freshness and ownership, conversation routes, references and ordinary
analysis retaining all seven model calls. No production speed claim is made.

## Deployment acceptance

1. Deploy backend and paired frontend commits; record their identifiers.
2. Run `python scripts/company_evidence_acceptance.py --inspect-source --output /tmp/company-evidence-source-latency-full.json`.
   Require all 33 cases to pass again; investigate any gap before advancing.
3. Repeat signed-in fresh questions for SPOT, ASML, TSM, NVO, AA and AAPL.
   Record browser elapsed time and `routing.pipeline_elapsed_s`; verify mode,
   claim attribution, source links, issuer scope, paragraph readability and the
   unassessed confidence label. Do not infer p95 from this small sample.
4. Reload/reopen a new answer and an older saved source answer. Check citations,
   scope and confidence display; check History and Research Trail filters.
5. Exercise an ordinary thesis and a selected historical comparison. Verify
   generated analysis and its existing evidence/freshness gates still operate.

The source evidence improvement does not close unrelated roadmap gates or
establish full-cohort signed-in, mobile, multi-account or statistical latency
acceptance. Proceed to the next roadmap gate only after deployed acceptance.
