# Offline company-quality review handoff

This tool reconciles existing matrix captures into a coordinator's pending-review
worksheet. It runs no providers and assigns no factual or usefulness scores.

```bash
python scripts/benchmark_company_quality.py --plan --output /tmp/quality-plan.json
python scripts/benchmark_company_quality_review.py \
  --plan /tmp/quality-plan.json \
  --batch /tmp/company-quality-batch-000-v1.json \
  --batch /tmp/company-quality-batch-020-v1.json \
  --output /tmp/company-quality-review.json
```

Use the exact original registry, ticker and family filters when producing the
plan, and pass `--registry` for a frozen nondefault registry. A filtered batch
cannot be combined with the default full plan. Without `--batch`, the tool
produces an entirely missing, pending worksheet. Existing output files are never
overwritten. The input byte hashes are ordered: plan, each batch in command-line
order, registry. Canonical batch hashes are also retained.

The tool reconstructs the canonical plan, checks registry/matrix identity,
questions and dimensions, batch ranges/counts/checkpoint position, and response
hashes. Identical overlapping rows are deduplicated; any differing row for the
same case is rejected. Explicitly choose and preserve a separate capture set for
reruns: an improved later answer must not silently replace the baseline.
Missing cases, execution failures and unexecuted cases remain in the full scope
and counts by size and question family. The exact captured response, including
its citations, remains available for review; no claims or source references are
invented or inferred. Factual, citation and usefulness reviews remain pending,
quality pass rate remains null, and launch readiness remains false.

Hashes establish consistency of supplied files, not authenticity. A caller can
rewrite a response and its hash; these are not signed capture attestations.
The current capture format has no build identifier or unique execution identity;
its deterministic run ID identifies matrix scope only. The worksheet explicitly
reports build/execution provenance unavailable. It cannot prove batches came
from the same deployment. Review coordinators must retain separate provenance.
This worksheet is not a blinded reviewer packet and must not be presented as one.

Next, review primary documents and freeze case-specific numerical/citation
references before using the existing factual grader. Narrative usefulness needs
the existing independent blind-review rubric and disagreement workflow, not an
automatic conversion of response text into reference facts. The representative
100-issuer registry, 30 issuers per size tier and reserved unseen holdout remain
separate unmet acceptance inputs. Neither fixture tests nor capture completion
establish real answer quality or signed-in production acceptance.
