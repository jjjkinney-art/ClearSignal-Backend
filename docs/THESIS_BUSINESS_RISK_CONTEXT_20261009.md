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

Post225 deployed eight-case capture confirms the reporting-coverage check:
Acadia's broad thesis and financial-trends views cite the June filing while
explicitly identifying the three March comparisons. Apple, Alcoa and Tesla
retain their existing observations and business excerpts without new warnings.

Next implementation: retrieve at most one latest domestic primary filing in a
parallel evidence task inside the existing ten-second router collection ceiling.
Opt-in Inline XBRL parsing shares the bounded download and SHA-256 body hash.
Accept only supported namespace-resolved standard US-GAAP consolidated USD
duration facts, verified registrant contexts, explicit reporting dates and a
small allowlist of numeric transformations. Preserve scale, sign and exact
integer statement amounts. Unsupported XML, dimensions, transformations, nil
values, duplicate IDs, conflicts and missing comparable prior periods remain
gaps. Both comparison observations retain the document URL, hash, fact and
context identifiers, source literal and conversion attributes, which the
claim binder and financial foundation recheck independently of answer prose.

Merge newer same-concept comparisons before admission; equivalent observations
need only one reference, while same-period value conflicts remain visible to
the integrity gate. Do not substitute a different revenue or net-income concept
for an existing comparison. Explicit metric requests receive only requested
facts. Historical, segment and issuer-KPI requests do not trigger this fallback.
One document can carry both current and comparative prior-year observations;
no prior-year download or fabricated quarter conversion is required. Preserve
older admitted comparisons and the coverage warning when retrieval fails.

Local targeted validation covers parser identity, scaling/sign, full-period
comparisons, replay binding, conflicts, request scope, evidence merging and
ingestion boundaries. A direct workspace fetch of Acadia's June document
returned HTTP 403 on this attempt; it did not provide a live filing replay.
Full CI and a fresh Render capture are required before declaring the current
financial coverage gap fixed. Missing operating income and wider thesis-quality
gates remain open. This parser is intentionally narrower than a general XBRL
processor and does not establish coverage of foreign/custom taxonomies.

Post226 live eight-case capture confirms Acadia's latest-period fallback: June
quarter revenue is $865.8M (-0.4%), parent-attributable net income $10.9M
(-63.7%), and January–June operating cash flow $223.6M (+54.2%). The Apple,
Alcoa and Tesla comparisons remain intact. This closes the specific Acadia
Company Facts lag demonstrated by that capture, not the broader quality gate.

Review of the June 2026 income statements found no separate consolidated
operating-income subtotal for Alcoa or Acadia. Both present income before income
taxes. Alcoa's custom total-costs concept explicitly includes nonoperating
expenses; neither that concept nor pretax income is an OperatingIncomeLoss
alias. Sources reviewed:
- https://www.sec.gov/Archives/edgar/data/1675149/000119312526326265/R2.htm
- https://www.sec.gov/Archives/edgar/data/1520697/000119312526321076/achc-20260630.htm

Next narrow improvement: when a broad financial thesis or profitability request
has no verified operating-income comparison, admit an independently reconstructed
comparison for the standard consolidated USD pretax concept as supplementary
profitability context. Use the existing one-fetch Company Facts producer and
bounded latest-filing parser. Both values retain their exact concept, period,
issuer identity and filing references. Newer same-concept filing evidence can
replace older pretax evidence; domestic/foreign pretax, custom costs, EBITDA,
pretax and operating income remain distinct. Explicit pretax questions can request
that metric directly.

Operating income stays unanswered. The supplementary comparison does not form
an operating margin, does not count toward the two-core-metric minimum for a
financial foundation, and does not add a supporting or counter-evidence signal
to the thesis. Existing operating-income evidence takes precedence. Conflicting,
tampered or unreferenced supplementary comparisons are withheld. Selected older
pretax evidence receives its own latest-period coverage warning. This is a general
producer rule, not a ticker exception or an assertion that every issuer omits
operating income. Wider operating-profit families, foreign taxonomies, valuation,
primary-source adjudication and the 100-issuer size-tier gate remain priorities.

Post227 live capture confirms the new separately cited pretax comparisons for
Alcoa ($482M versus $161M, +199.4%) and Acadia ($22.007M versus $50.003M,
-56.0%) in the June quarter. Review of the cited SEC income statements confirms
those values, periods, units and changes. Acadia's June financial comparisons
remain intact; Apple and Tesla retain operating-income evidence. This is narrow
numerical corroboration, not complete factual/citation or useful-answer grading.

The expanded 36-case run is incomplete: the first checkpoint contains ten core
theses through Costco; the second contains all sixteen cases at offsets 20–35.
There are 26 captured cases and ten missing cases at offsets 10–19. JPM's core
thesis is the next planned case after the interrupted checkpoint. Render's email
at 2026-10-09 13:23:30 UTC reports an instance memory limit and automatic restart;
this checkpoint order does not prove which operation caused the restart. ASML
has insufficient claim evidence in both captured question families. JPM's
financial-trends view retains a latest-period revenue gap. These remain P0.

Memory repair: replace the whole-document ElementTree and per-display-element
namespace index with XML callbacks. Feed 16 KiB slices of the existing decoded
body and retain only the requested flat facts, eligible context/unit records,
a bounded ID inventory and one small resource subtree. Preserve namespace
resolution, exact amounts, through-EOF duplicate checks, forward references,
identity/period/unit checks and malformed-input rejection. Unsupported nested
fact content still cannot become a flat number. Limits are 128 levels, 200,000
IDs, 20,000 resource elements, 20,000 candidate facts and 256 namespaces in scope;
a resource subtree above 64 nodes is ineligible. Budget exhaustion returns no
inline evidence and emits a reason-only diagnostic. Other retrieval paths and
source integrity guards are unchanged; these bounds can leave explicit evidence
gaps on unusually complex documents.

In fresh local Python processes, a synthetic 5,700,063-character document with
300,000 unrelated span elements peaked at 104,288 KiB before the repair and
20,636 KiB after it. These are synthetic process RSS measurements, not production
capacity guarantees or proof of the Render incident's exact cause. A parser
allocation regression with 100,000 display nodes also checks that valid facts
remain identical under a six-megabyte allocation ceiling.

The capture runner checkpoints the active issuer/question immediately before
provider execution and clears it after a recorded result. A killed process can
therefore leave an identifiable in-flight case without falsely counting it as
captured, failed, adjudicated or complete. Full CI, deployment verification and
a focused JPM core-thesis capture precede resuming only offsets 10–19 with a new
output filename. Preserve the 26 prior captures and review gaps before wider
benchmark execution. Launch readiness and the 100-issuer gate remain open.

Post228 live JPM core-thesis capture completed, followed by all ten missing cases
at offsets 10–19 on the same Render instance. The 36-case cohort is captured
across runs; this demonstrates completion of these post-repair runs, not a
production capacity guarantee or a complete quality adjudication. The new ten
answers contain eight partial core theses, one attributed Apple financial view
and one partial Alcoa financial view. JPM retains older revenue and no admitted
business/risk context; XOM also lacks business/risk context. Competitive position,
valuation/expected returns and risk impact remain unanswered in core theses.

The June 2026 JPM income statement reports total net revenue using the standard
us-gaap:RevenuesNetOfInterestExpense concept, previously outside the supported
revenue family. Primary statement and taxonomy details reviewed:
https://www.sec.gov/Archives/edgar/data/19617/000162828026054343/R2.htm
It reports $57,347 million versus $44,912 million for the June quarters. These
values are primary-source diagnosis, not a hardcoded production answer.

Bank revenue repair admits complete same-concept USD comparisons with the
explicit label "revenue net of interest expense" in both Company Facts and the
bounded latest-filing fallback. A complete newer net-revenue comparison can
replace a whole older generic-revenue comparison; it never combines concepts
across the current/prior pair or computes bank revenue from component sums.
Same-period alternatives cannot silently replace existing comparisons. Identity,
period, content binding, duplicate and source-reference checks remain required.
Reconstruction and thesis interpretation retain the net-revenue label, including
coverage warnings for older net-revenue evidence. Operating income, bank-specific
cash-flow interpretation, competitive position, valuation and risk-impact gaps
remain open. No ticker allowlist or universal quality assertion is added.

Initially local dependency restoration was unavailable; syntax compilation
and diff checks are available locally, while the pinned Python 3.11 CI gate must
execute the new cross-path tests and full suite before merge/deployment. A fresh
JPM capture after deployment must confirm latest-period revenue and supply
retrieval diagnostics before changing the missing-disclosure path. ASML financial
coverage, generic thesis language and the 100-issuer size-tier gate remain P0.

First PR229 CI completed the isolated full regression with two failures, both
in the new bank test file. Its inline fixture produces a padded canonical CIK,
but the replay test supplied an unpadded identity that changed the exact citation
ID on reconstruction. The fixture now uses the producer's canonical CIK; source
binding checks remain intact. After local dependency restoration, all five bank
tests and the 216-test targeted producer/fallback/foundation/source/router/parser
set pass. Full CI must rerun on the corrected tree before merge and deployment.

## Post229 live verification and punctuated contents headings

PR229 merged and deployed as 87fab36a85b95bab1f32969dbc0e93f7ef98ed1a.
Both live JPM families now use the June-quarter revenue net of interest expense
comparison ($57.3B versus $44.9B, +27.7%) with primary source references; the
latest-revenue coverage gap is closed. This does not certify a complete thesis.

The cold core capture abandoned thesis disclosures and filing metrics at the
router's 10-second wall cap. The disclosure task later logged one rejected
business sentence. A standalone Render document probe took 5.96 seconds and
revealed that its 223-character business window was the table of contents:
the normalized heading has a separate period before its page number. The shared
boundary guard rejected a directly adjacent page number but missed this form.

Rejecting a period or colon followed by a page number now applies to business
openings, risk openings and closing headings. No source text or offsets are
rewritten; prose after punctuation remains eligible. Regression cases exercise
TOC-only failure, genuine later sections, punctuated closing references and
bounded HTML selection through business/risk producers and source binding.
All 253 focused section, disclosure, document, risk, foundation and bank tests
pass locally. Full CI and a new live JPM capture remain required. Cold retrieval
latency, missing or ineligible business prose, operating income, bank cash-flow
interpretation, competitive position, valuation and risk impact remain open.

## Post230 live retest and concurrent cold directory loading

PR230 deployed as 8869c5716fb8e81210a8f7514379b52bf64417e0. JPM's
business extractor now examines 235 sentences rather than the TOC fragment;
none qualify under the current conservative business rules. The live task is
still abandoned by the router at 10 seconds, so the answer remains partial.
Representative actual business prose and standalone risk counts are still
needed before changing subject/predicate admission rules.

The same cold run starts four ticker-directory downloads before any publishes
the module cache. A lock with a second cache check now coalesces these concurrent
loads into one request. Success and existing withheld-on-failure behavior are
shared; cached lookups avoid the lock. No provider wall cap, identity validation,
freshness policy or document bound is changed. Concurrent success/failure tests
coordinate four waiters without sleeps and prove exactly one request. All 146
targeted SEC-provider, disclosure, bank and router tests pass locally. Full CI
and live latency verification remain required; this is not a claim that every
annual document will finish inside the current time budget.

## Post232 source-document collection budget

PR231 and PR232 passed full CI and deployed together as
0b991f9ed79e435be302887ac9101fad0556ad9b. The next live JPM core
capture makes one ticker-directory download, confirming removal of the cold
duplicate work. Both thesis disclosures and filing metrics still exceed the
router's 10-second collection cap; the answer remains a partial financial
foundation. That capture does not establish the new business quote's live
admission because the entire document result was discarded.

Source-oriented investment answers skip model agents and synthesis. Their
SEC thesis-disclosure and filing-metric tasks now receive a bounded 20-second
total collection budget. Ordinary providers are snapshotted at 10 seconds;
unrelated results arriving during the document grace period remain excluded.
Model-generated investment answers retain the original 10-second budget.
Completed document work returns immediately, and failures or unfinished tasks
remain gaps. No source guard, document size bound or issuer rule is relaxed.

Deterministic tests cover late-document retention, exclusion of late unrelated
providers, remaining wall-budget calculation, unchanged generated-answer caps,
unfinished/failed tasks and no extra waits for completed or absent documents.
225 focused collection/router/source/provider/disclosure/foundation/bank tests
pass locally. Source-routing and latency regressions also pass; their isolated
fixture now mocks the filing-metric producer and directory lookup explicitly.
Full CI and a live JPM core capture remain required before treating the timeout
as resolved. This permits up to ten more seconds of latency for document-backed
source answers; preprocessing and faster retrieval remain roadmap work.

## Post233 live result and interpretation quality follow-up

PR233 deployed as eac17f415f337e6b1daa2d9dd8f8c535cb4e4d31. The live
JPM core capture completed document retrieval in 12.81 seconds with seven
attributed claims: four financial comparisons, the exact segment description
and two risk excerpts. Neither document task was abandoned. This confirms
late-document retention for that capture, not broad-company launch readiness.

The capture also exposes quality gaps: a cash-flow decline was labeled
counter-evidence without underlying cash-flow drivers; a generic risk-factor
introduction occupied one of two sampled risk slots; and the business excerpt
only listed unexplained segment abbreviations.

For a reconstructed, reference-bound revenue comparison explicitly reporting
RevenuesNetOfInterestExpense, operating cash flow now remains a reported fact
and a context-only interpretation. Neither its sign nor movement alone enters
the supporting/counter-evidence thesis summary or a directional monitoring
test. The response asks for underlying cash-flow, liquidity and capital
disclosures instead. This is a narrow measure-based safeguard, not a banking
industry classifier: banks with other revenue concepts remain follow-up work.
Unbound, conflicting, wrong-issuer or missing-reference revenue cannot trigger
this context. No actual cash-flow driver is inferred from the total.

Research basis: JPM's 2025 consolidated cash-flow statement reports operating
movements in trading assets, securities borrowed and loans held for sale.
These observations motivate withholding a total-only directional signal;
they are not inserted as claims about the June 2026 comparison.
Primary source: https://www.jpmorganchase.com/content/dam/jpmc/jpmorgan-chase-and-co/investor-relations/documents/annualreport-2025.pdf

Broad-thesis risk binding now excludes explicit generic introductions such as
"Any of the risk factors discussed below...". Specific topic producers retain
their existing rules. Business extraction scans its existing 2,000-sentence
bound and prefers admitted operating predicates over bare segment structures,
preserving complete source quotes and offsets, at most two descriptions and
source order within each group. "The Firm" can use the same factual predicates
as "The Company"; promotion and forecast guards still apply. This neither
expands acronyms without evidence nor guarantees a richer JPM description.

These changes need full CI and a fresh live JPM capture before production
quality is confirmed. Remaining P0 work includes cash-flow component coverage,
source-bound business explanation, useful sector metrics, risk completeness,
valuation and diverse/held-out 100-company quality adjudication. The 500-company
expansion follows measured quality in the first cohort, not capture success.

## Post234 live result and named-segment follow-up

PR234 passed full CI and deployed as 5a6aded803986a736f4efd9cf403d1abdd157bce.
The live JPM capture retains cash-flow facts with context_only interpretation,
omits the generic risk introduction and includes a specific credit-loss
mechanism. Retrieval completed in 13.70 seconds without document abandonment.
The business description still lists CCB, CIB and AWM without their names.

The earlier user-supplied normalized Item 1 text contains a full named-segment
sentence immediately before that bare list. It starts with the joined heading
"Business segments & Corporate" and "For management reporting purposes".
Neither the heading nor its factual has-reportable-segments predicate was
previously admitted. A shared rule now admits this complete sentence shape,
including an explicit one-through-twelve word count, named segments introduced
by a dash or colon, and the existing qualitative, length, issuer and section
checks. The names must appear in the source; no ticker dictionary or inferred
acronym expansion is used. Digit-bearing counts remain ineligible.

The exact generic heading can be removed before this explicit subject; the
quote and offsets still point to the complete sentence in normalized text.
Admitted operating descriptions retain priority, followed by the named segment
list. A bare segment list is omitted when a named list qualifies, avoiding
redundant unexplained abbreviations. Forecasts, promotion, arbitrary prefixes,
other subjects, wrong identity and unsupported forms remain gaps.

Tests reproduce the supplied JPM sentence shape and an unseen synthetic medical
issuer with different names, through extraction, exact offsets, final binding
and the source-answer gate. Neither competitive position nor valuation is
established by these segment names. Full CI and a fresh live capture are needed
to confirm the names reach the deployed answer. Products, revenue drivers and
complete business-model explanation remain broader roadmap work.

## Post235 cohort review and shared selection filters

PR235 deployed as ba8573da61ad770f4dd3072a4a591eab8cc77271. The live
JPM response now retains the source-spelled segment names. The subsequent
18-issuer, two-family benchmark captured all 36 cases. The supplied compact
summary reports 12 attributed, five partial and one insufficient financial
answer; 17 partial and one insufficient core-thesis answer. These are producer
statuses, not independent citation adjudication or launch approval.

The observed DOCU and ETSY business claims include internal employee benefits
and skills development. A shared filter now withholds complete sentences
explicitly directed to the issuer's own employees, staff or workforce, or
describing development across its own organization. Both extraction and final
binding apply the filter. Customer-facing employee-benefit administration and
payroll services remain eligible. No substitute business description is invented.

The observed LLY and MSFT risk samples include unknown-risk boilerplate and an
explicit introduction to risks described below. Broad-thesis binding now
withholds these additional bounded introduction shapes. Specific mechanisms
and the narrower topic-specific risk producer retain their existing checks.
The source quotes, section and issuer checks and extraction caps are unchanged.

Regression tests exercise the observed sentence shapes, customer-service
preservation, exact offsets, final binding and financial-foundation gap labels.
Live responses must still confirm useful replacements; filtering can correctly
leave a gap when no qualifying sentence survives. ASML's financial/form coverage,
XOM's missing business and risk context, incomplete operating-income coverage,
core business relevance, competitive evidence, valuation and mechanism-based
invalidation remain P0. The 100-company quality gate and subsequent 500-company
expansion remain open.

## Post236 live verification and EUR/20-F financial coverage

PR236 passed every CI step, merged as 2663e041e67fa26bf41eb54fa8c9bacc04c4fddf,
and deployed healthy. The four supplied live core-thesis captures omit DOCU/ETSY
employee programs and replace LLY/MSFT generic risk introductions with specific
disclosures. ETSY now correctly retains a business-model gap. DOCU's remaining
hosting description still does not explain its core product. All four remain
partial; these captures do not independently adjudicate source accuracy.

The SEC Company Facts response for ASML (CIK 937966) exposes US-GAAP revenue,
operating income, net income and operating cash flow in EUR through 20-F filings.
The latest observed annual period ends 2025-12-31, filed 2026-02-25, accession
0001628280-26-011378. The prior parser admitted none of the EUR observations
because its form whitelist excluded 20-F; the metric retrieval and binding path
also required USD. This is not evidence of an IFRS-taxonomy gap for this case.
Diagnostic source: https://data.sec.gov/api/xbrl/companyfacts/CIK0000937966.json

A shared fact policy now admits annual 20-F/20-F/A alongside existing domestic
forms and supports explicit USD/EUR monetary comparisons. EUR remains EUR in
exact bound facts and scaled summaries; no exchange-rate conversion is performed.
The service queries both currencies in one Company Facts request. It requires
one unambiguous currency at the latest Assets anchor, falling back to requested
monetary facts only when no anchor exists. Concurrent USD/EUR presentations do
not authorize an arbitrary USD preference. Each comparison still requires the
same concept, issuer, currency and matching annual duration/prior-year gap.
The foundation rebuilds the native unit and rejects a combined mixed-currency
case. Existing inline-filing extraction, per-share units and calculated free
cash flow retain their narrower USD support.

Regression tests use synthetic issuers and cover parser-to-admission-to-answer
binding, four financial slots, currency ambiguity, cross-currency pairs,
quarter facts inside annual forms, missing priors, amendments/conflicts,
wrong issuer, tampered display/reference/currency, and historical cutoffs.
An offline replay of the captured real ASML response now yields four attributed
financial comparisons; this is not a deployed benchmark or a complete thesis.
Full CI and a fresh Render capture remain required.

Both comparison producers now require two successfully bound claims before
returning a summary. Several older synthetic metric fixtures changed an
accession while retaining the preceding filing's URL; their URLs now match
their intended observations. Rejection checks were retained. The final focused
suite passed 297 tests, including a wrong-URL comparison refusal.

Other reporting currencies, IFRS concepts, 20-F business extraction and complete
foreign-issuer quality remain P0. XOM's current directory CIK 2115436 names
ExxonMobil Holdings Corp and its inspected submissions list one 10-Q and no
annual filing; predecessor identity must be established from primary documents
before any annual history is associated with the current issuer.
