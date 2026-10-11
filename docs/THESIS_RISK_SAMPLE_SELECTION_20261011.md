# Apply risk-sample eligibility before the extraction cap

The broad-thesis relevance guard documented in
`THESIS_BUSINESS_RISK_CONTEXT_20261009.md` excludes generic introductions and
unnamed actions/efforts. Previously, the topic extractor returned its first two
candidates before that guard ran. Two rejected candidates could exhaust the cap
and hide a later qualifying mechanism in the same already-fetched risk section.

An offline reproduction placed a generic liquidity introduction and unnamed
effort before an explicit refinancing-risk sentence. Broad fetch returned zero
risks and reported the operating-risk-mechanism gap, although the later sentence
independently passed exact source binding.

Broad-thesis fetch now opts into the existing eligibility predicate before the
extractor's two-result cap. The final binder repeats the same shared predicate.
The narrow topic route keeps its existing selection; issuer/section/date/hash
checks, document budgets, source ordering, duplicate handling and final two-risk
cap remain unchanged. This is sample eligibility, not relevance ranking or proof
of materiality. No extra document request, model call or paid provider is added.

Regression coverage checks zero through three rejected leading sentences,
all-invalid sections, unchanged first-two eligible results, later eligible
mechanisms, one document fetch, source spans/hashes, final references, partial
status and unresolved risk materiality/likelihood/impact. Network guards enforce
the new end-to-end synthetic cases. These are synthetic acceptance checks, not
adjudication of actual company answers. Live tests remain deferred.

Validation: 412 focused tests passed using isolated per-file processes, including
disclosures, issuer risks, succession, source answers, financial foundation,
pipeline, parse budget and routing. A combined ordering that loads source-answer
tests before financial-foundation tests fails three pretax cases; the same
failures reproduce on the independent grammar branch without this selection
change. The financial-foundation file passes all 35 tests in isolation. Pipeline
checks retain pre-existing non-daemon-thread cleanup warnings.
