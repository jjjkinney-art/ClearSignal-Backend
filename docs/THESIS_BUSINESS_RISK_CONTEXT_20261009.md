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
