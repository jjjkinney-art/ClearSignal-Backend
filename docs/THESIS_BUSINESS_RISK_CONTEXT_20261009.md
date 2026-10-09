# Official business and risk context for partial thesis foundations

Post219 deployed capture returned financial foundations for all four sampled
issuers (AAPL, AA, ACHC, TSLA). The financial answers retained explicit gaps.
Those captures validate the visible behavior, not independently adjudicated
accuracy or a useful-answer rate across the issuer universe.

## Behavior and source contract

A broad cited investment-thesis question now requests one full annual 10-K or
20-F alongside existing providers, within the router's existing ten-second
collection ceiling. Discovery or download failures remain missing context.
Historical replay does not request current filings. Named segments, issuer
KPIs and specific operating-risk questions retain their scoped paths.

Business extraction currently supports complete 10-K Item 1 Business sections
closed by Item 1A Risk Factors. It rejects TOC rows, quoted cross-references,
unclosed sections and bodies over the bounded scan. It retains at most two
complete, short qualitative description sentences. Numeric observations,
forward-looking language and selected promotional assertions are excluded.
20-F business descriptions remain a gap pending reviewed boundaries.

Risk context reuses existing topic qualification and source binding, with no
new issuer allowlist. The shared directory resolves issuer identity. At most
two distinct qualifying quotes are retained in source order. They are sampled
disclosures, not a ranking of the most material risks or proof of occurrence,
likelihood or quantified impact. Unrecognized mechanisms remain outside this
increment; predecessor and incorporated-report fallbacks are not added here.

Both kinds preserve exact quote, normalized span, source content hash, SEC URL,
filing date and section. The composer rechecks producer proof and canonical
response references. Changed summaries, wrong issuers, invalid hashes, changed
quotes, future dates and stale/conflicting evidence cannot close missing parts.
Business descriptions never become independently verified competitive moats.
Qualitative disclosures do not enter quantitative reported claims or financial
inferences. A minimum of two eligible financial comparisons still applies.

Large periodic HTML filings can opt into a combined business/risk text window
when it fits the existing 360,000-character limit. Otherwise the previous
complete-risk window is preserved and business context remains unavailable.
Byte limits, ordinary ingestion defaults and table extraction defaults remain
unchanged. The new annual path skips table extraction.

Responses remain partial. Competitive position, valuation and expected returns,
full business-model coverage, and risk materiality/likelihood/financial effects
remain unverified. No assessed confidence, buy/sell recommendation or directional
historical thesis change is introduced.

## Validation and release acceptance

Synthetic tests exercise exact spans, shared producers for an unseen issuer,
canonical references, duplicate quotes, tampered proof, ineligible documents,
TOC/cross-reference boundaries, unchanged ceilings, optional combined windows,
source-pipeline integration, idempotent source gates and historical exclusion.
Synthetic prose is not represented as an actual issuer disclosure.

After deployment, rerun the eight-case AA/ACHC/AAPL/TSLA core-thesis and
financial-trends capture with a fresh output path. Inspect the full answers,
claim kinds, citations and remaining gaps, then compare material quotes and
figures against primary documents. Missing annual context must stay explicit;
an attributed subset or captured response does not count as full thesis success.
Follow with valuation work, unseen holdout expansion, the minimum 100-issuer
size-tier benchmark and signed-in personalization/save-reopen acceptance.


## Post220 deployed capture and extraction follow-up

The user supplied all eight post220 captured answers. All four broad theses
added two cited risk excerpts; none included a business description. Financial
trends retained attributed AAPL/TSLA answers and explicit operating-income gaps
for AA/ACHC. This confirms sampled visible behavior, not independent source
adjudication or complete thesis acceptance.

Normalized HTML can join an unpunctuated heading such as Company Background or
Overview to the next sentence. A follow-up recognizes a small shared set of
these prefixes, removes only the heading, and preserves the entire qualifying
sentence with its adjusted exact source span. It does not scan into arbitrary
conditional or competitor-attributed prose to fabricate a current description.
Count-only diagnostics distinguish missing complete sections from sentence
rejections and record the ingestion text selection. Missing descriptions emit
these counts at warning level so the Render CLI exposes remaining gaps without
requiring raw source prose or credentials in logs.

Local synthetic regression proves this specific boundary correction. It does
not establish that this is the only reason for all four deployed omissions.
Rerun live acceptance after deployment; investigate remaining section-selection,
subject and qualification gaps before valuation work. The complete business
model, competitive position, valuation and size-tier quality gates remain open.


## Post221 identity rejection and correction

The deployed post221 diagnostics showed document_ineligible with zero sentences
scanned for all four sampled issuers. AA, ACHC and TSLA had already retained
combined business/risk sections. The earlier heading correction therefore did
not resolve the upstream rejection.

The production ticker directory supplies ten-digit zero-padded CIK strings;
SEC archive paths use the numeric CIK without those leading zeroes. Business
extraction and its final binder had passed the padded string to the strict
archive URL matcher. Normalize only a validated positive one-to-ten-digit CIK
into its numeric archive representation at both boundaries. Keep exact issuer,
SEC host, accession, HTTPS, form and provenance checks. Malformed, zero,
boolean, oversized or alternate-issuer identities cannot authorize a quote.

Four regressions using directory-shaped CIKs reproduced the rejection before
the correction and pass afterward. Live-fetch and source-pipeline fixtures now
also use padded directory identities so production formatting is represented.
Rerun deployment acceptance to establish actual business-description coverage;
qualifying prose can still remain missing and full thesis quality is unproven.

## Post222 live confirmation and prose-quality correction

The user supplied all eight deployed post222 answers. Each of the four broad
theses now includes two business excerpts and two risk excerpts; financial
answers retain their prior coverage and explicit gaps. This confirms that the
numeric-identity rejection is resolved in the sampled live path. It does not
independently adjudicate figures or quotes, or establish universal coverage.

The excerpts also expose a qualification defect: Acadia's selections describe
commitments and promotional returns, Alcoa's second selection a balance-sheet
goal, and Tesla's selections include development or expansion intentions.
Their operational vocabulary alone does not establish a concrete description
of current business activities. Reject shared aspiration and promotional
language at both extraction and final binding. Skip the entire mixed sentence
rather than clipping a factual-looking clause; continue the existing bounded
scan for later qualifying prose. Preserve exact spans and all source checks.
If no concrete description qualifies, retain the business-context gap.

Regression cases reproduce those sentence shapes, retain concrete product,
service, channel and segment descriptions, reject old promotional proof at
binding, and keep missing context explicit. Live acceptance must confirm the
new selections, including whether the current subject and length rules still
leave gaps. Full business-model quality, operating income for AA/ACHC, ACHC
reporting freshness, competitive position, valuation, risk assessment, the
100-issuer size-tier benchmark and signed-in personalization remain open.

## Post223 selection review and current-operation predicates

The eight deployed post223 answers preserve financial coverage and retain two
business excerpts for each sampled thesis. Previously rejected sentences no
longer appear, but later weak selections remain: Alcoa's project strategy,
Acadia's potential acquisitions and Tesla's design priorities. Acadia also
returns a concrete care-service description and Tesla its segment structure.
This is partial improvement, not acceptance of the business-context quality gate.

The underlying rule searched for activity stems anywhere in a sentence, so
development, products or a subordinate "provide" could authorize non-operating
main statements. Require a shared affirmative present operating predicate,
current business role, segment structure or product-range statement attached
to the issuer subject. Apply the same rule in extraction and final binding.
Retain existing aspiration/promotion exclusions, full sentences, adjusted exact
spans, bounded scanning and source checks. Do not rewrite or clip strategy prose
into a fact. Unsupported grammar remains an explicit gap rather than a guess.

Five synthetic regressions reproduce the incidental-vocabulary admission before
the correction; concrete service, product, distribution, role and segment
statements retain proof. Deployed acceptance must inspect the selected prose,
not just count business claims. Continue to primary-source adjudication and
unseen issuer expansion after this gate, with valuation and the wider quality
roadmap still open.

## Post224 confirmation and financial reporting coverage

The user supplied eight post224 deployed answers. The four sampled theses now
select concrete current product, service or segment descriptions: Apple
products/headphones, Alcoa segments/alumina, Acadia care/treatment levels and
Tesla segments/energy products. The previous strategy and potential-development
selections are absent. Financial coverage remains unchanged. This confirms the
sampled selection correction, not complete business models or independently
audited universal quality.

Read-only SEC snapshots on 2026-10-09 explain two different financial gaps:
Alcoa's Company Facts payload has no us-gaap OperatingIncomeLoss observations;
Acadia's standard tag ends in March 2020 and is correctly withheld by the
existing staleness guard. Do not relabel pretax income, adjusted EBITDA or a
segment metric as reported consolidated operating income. Acadia's Assets,
revenue, net income and operating-cash-flow observations all stop at March 2026
in that payload, while its submissions inventory includes a June 2026 10-Q
filed July 28. The rendered March figures were reproduced from the feed; that
does not establish current-quarter coverage. Snapshots can change on later reads.

Preserve structured report dates in the existing filing-discovery records.
Compare selected, rebuilt financial comparisons with the newest eligible
retrieved filing period. Cite canonical admitted filing and fact references,
add explicit latest-period metric gaps and return a partial answer when the
observations lag. The filing establishes the coverage limitation, never missing
financial values. Use the existing inventory without extra network requests or
historical backfill. Foreign and unsupported grammar/metric families remain
outside this coverage check; absence of a warning is not a freshness certificate.

The local snapshot replay reproduces Acadia's three March comparisons alongside
the June filing and exposes all three latest-period gaps. Synthetic regressions
cover metric and broad-thesis views, canonical references, idempotence, unchanged
quantities, same/older filings, wrong issuer, invalid/future dates, tampered facts
and unadmitted inventory. Full CI and deployed capture remain required.

Priority follow-up: independently bind latest filing-level structured facts when
Company Facts lags, or retain the explicit gap. Review issuer-specific/custom
operating-income presentation before adding a producer; standard missing tags
are not permission to invent aliases. Continue primary-document adjudication,
unseen issuer expansion and the 100-issuer size-tier gate before claiming broad
quality parity. Valuation, competitive position and risk assessment remain open.
