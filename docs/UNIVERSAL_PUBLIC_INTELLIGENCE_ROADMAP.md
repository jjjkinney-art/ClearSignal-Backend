# Universal Public Intelligence Roadmap

**Date:** 2026-09-28  
**Status:** Active roadmap  
**North star:** ClearSignal should accept a research question about any public company and analyze all legally accessible, relevant public information it can verify—while making every factual claim inspectable, attributable, current, and honest about uncertainty or missing coverage.

This roadmap supersedes the live-data scope of the older static company-profile coverage plans. It extends the current account-owned research memory, personalized Intelligence Mode, and claim-level SEC evidence work into a universal public-information research system.

### P0 priority — universal company quality (user directive, October 9, 2026 Auckland)

**Launch requirement:** users researching companies across the market-cap
spectrum must receive similarly high-quality, personalized research, whether
an issuer is small/micro-cap, mid-cap or large-cap. JetBlue and Smith & Wesson
were illustrative examples of smaller companies; Apple and Tesla illustrated
large companies. These names are not a required ticker list or special-case
implementation targets. Company size, name recognition, or inclusion in a
hand-reviewed ticker list must not determine answer quality. Personalization
must consistently apply the user's explicit research preferences, selected
historical thesis, risks and time horizon where available, with the same
ownership, evidence and uncertainty safeguards across company sizes. The intended scope remains every public company, including
smaller issuers and international listings. This is a launch-critical expansion
of the existing infrastructure, not a rebuild or a 33-company product limit.

Prioritize this work ahead of optional feature expansion and cosmetic polish,
while preserving the existing security, factual-integrity and comparison gates.
The 33/33 deployed risk-evidence result validates specific issuer/topic cases;
it does not establish reliable answers across all questions or public companies.
A safe gap is honest handling, but is not a successful useful-answer result.

**Implementation and acceptance order:**

1. Audit and extend shared issuer identity, official source discovery, document
   retrieval, sector metrics and topic extraction. Prefer fixes that transfer to
   unseen companies over an ever-growing collection of ticker-specific patches.
   Review genuinely issuer-specific layouts without weakening attribution.
2. Select representative smaller, mid-sized and large companies across sectors
   and source complexities for end-to-end acceptance, without tailoring the
   product to the illustrative names. Test legal company names and tickers;
   core investment thesis, operating risks, comparable-period financial trends,
   sector operating metrics, recent developments, and saved-thesis comparisons.
   Use the signed-in production path, test consistent personalization and
   relevance to the user's selected thesis/preferences, and verify readable
   save/reopen results. Include unseen smaller issuers to test transferability.
3. Expand the existing benchmark to its minimum 100-issuer milestone, with at
   least 30 issuers in each principal large-, mid- and small/micro-cap tier,
   multiple sectors, fiscal calendars and jurisdictions, and an unseen holdout.
   This is a first validation floor, not proof that every public company works.
4. Apply the same factual, citation, relevance and usability standards to every
   tier. Require at least 90% useful cited answers in each tier and report
   issuer/question-family failures, not merely 90% in an aggregate dominated
   by large companies. Apply the existing numerical-accuracy and source-binding
   gates; allow no fabricated material sources, issuer/period contamination,
   account leakage or issuer-level stop-ship failure. Report gaps separately.
5. Measure live latency, freshness, retrieval failures, saved-answer usability,
   and source coverage by issuer, question family, sector, size and jurisdiction.
   Fix recurring failure classes and rerun both failing and unseen companies.
6. Extend exchange/security identity and official non-SEC sources for markets
   the SEC foundation does not cover. Maintain an auditable market/source-family
   coverage inventory. Broad acceptance of a name or a safe gap alone must not
   be advertised as equivalent research quality or universal verified coverage.

No guaranteed issue-free company count is established yet. Exhaustive success
for every possible question is not a measurable promise; broad public-company
access, quality parity and evidence-based coverage are the engineering goals.
Unsupported scope must be explicit, and any narrower initial release must be
described as a scoped beta rather than completion of the universal launch goal.

**Current implementation baseline:** shared SEC identity/discovery, bounded
primary-document ingestion, reusable facts and risk-topic extraction, admission,
citations, account-owned memory and benchmark runners already exist. Global
source families, broader document layouts, question coverage and representative
production validation remain substantial work.

The first multi-question capture increment is documented in
`COMPANY_QUALITY_MATRIX_20261009.md`: six question families produce 108 cases
across the existing 18-issuer registry, with bounded batches and per-case
checkpoints. Captures remain unreviewed and dry runs remain unexecuted. This
does not expand the registry to 100 issuers or validate personalized answer
quality; primary-source adjudication, unseen holdout and signed-in acceptance
remain required before reporting useful-answer rates or launch readiness.

The first deployed eight-case batch exposed shared question-completeness gaps:
four broad thesis questions returned risk-only gaps, and four financial answers
omitted profitability while reporting no unanswered parts. The immediate fix
adds profitability retrieval, complete metric-slot reporting and explicit date
ranges. Broad source-supported thesis composition remains P0 across company
sizes; a successful capture or an attributed subset is not a full useful answer.

Post218 deployed answer inspection confirmed profitability retrieval and
explicit gaps for missing operating income, plus complete date ranges. AAPL
and TSLA have complete financial metric slots; AA and ACHC remain partial.
The next source-supported thesis increment adds a conditional financial
foundation from producer-bound comparisons, documented in
`SOURCE_SUPPORTED_THESIS_FOUNDATION_20261009.md`. Business-specific mechanisms,
valuation, disclosed risks, personalization and unseen-company usefulness must
still pass acceptance before a complete thesis or quality-parity claim.

Post219 deployed inspection confirmed partial financial foundations for AAPL,
AA, ACHC and TSLA. The next increment adds exact official business descriptions
and sampled issuer-risk quotes from one annual filing, documented in
`THESIS_BUSINESS_RISK_CONTEXT_20261009.md`. This is shared infrastructure rather
than a ticker allowlist. It does not establish complete business-model coverage,
competitive advantage, valuation, risk materiality or launch readiness. Live
acceptance and primary-document adjudication precede the next valuation and
broader-universe increments; the 100-issuer and personalization gates remain P0.

Post220 deployed capture added cited risk context to all four sampled broad
theses but no business descriptions. Business extraction remains the immediate
P0 fix before valuation: address normalized heading/sentence boundaries and
expose count-only section/qualification diagnostics, then rerun live acceptance.
No full thesis or universal-company quality pass is inferred from these captures.

Backend PR215 is deployed at `7c69214096c7128a98d62124a7aba1b8d0c131a5`.
Its live September 26 Tesla comparison retrieved the October 2 SEC delivery
release, admitted one newer evidence item and survived save/reopen. Frontend
PR81 is deployed at `7cf1e976dbe3fe9a7400a4bc7632e35fed58c714`; the audit now
shows eligible evidence separately from an unverified conclusion. These close
that retrieval/display increment, not full launch readiness. Fully cited and
semantically supported comparisons remain P0; a delivery count alone must not
be turned into proof of competitive advantage. Publication-date display across
time zones also needs review after the live audit rendered October 2 as October 1.

### Latest acceptance — October 8, 2026

The user supplied the deployed post213 Render source-evidence run: **33/33 pass**.
This supersedes the historical post203–post206 cohort gaps recorded below.
PR213 is deployed at `060d50f6a58b33b73a679616a3a9406aa41b2d03`.
Signed-in source-evidence and ordinary selected-history comparisons preserved the
historical thesis, declined unsupported direction when no eligible newer evidence
was retrieved, and survived reopening. This confirms those regressions; broader
launch readiness, semantic accuracy and universal source coverage remain open.

The official Tesla release increment has since passed deployed retrieval and
save/reopen acceptance through the SEC exhibit route described above. The
issuer's investor-relations index returned HTTP 403 on Render. Wider issuer
coverage and supported comparison conclusions remain open. See
`OFFICIAL_DELIVERY_RELEASES_20261008.md` for the retrieval increment.

## 1. Product promise and boundary

ClearSignal will provide broad query acceptance, not a false promise that every fact on the internet is available. Paywalls, licensing restrictions, removed pages, inaccessible jurisdictions, and facts that were never publicly disclosed must remain explicit limitations.

For every question, the product must do one of three things:

1. Answer with claim-level evidence from public sources.
2. Answer partially and identify the precise evidence gap.
3. Decline to make the claim when reliable public evidence is unavailable or contradictory.

The product must never fill an evidence gap with confident generated prose.

## 2. Non-negotiable invariants

- **Account ownership:** research conversations, thesis snapshots, preferences, and recalled evidence remain account-owned.
- **Guarded shared routes:** ticker-wide/shared research routes remain protected by authorization and cannot leak one account's private research into another account.
- **No implicit backfill:** analyses created before account-owned persistence are not backfilled unless a separately reviewed migration is approved.
- **Evidence before prose:** every material factual claim links to an evidence record; inference and calculation are labeled separately.
- **Stable identity:** resolve ticker, issuer, legal entity, exchange, CIK/LEI, ADR, predecessor, and subsidiary relationships before retrieval.
- **Source provenance:** preserve public URL, publisher, document type, publication/filed time, accessed time, reporting period, page/section/table location, and extraction method.
- **Source quality:** prefer primary sources; visibly distinguish primary, authoritative secondary, reputable reporting, estimates, and user-supplied material.
- **Comparable periods:** normalize fiscal calendars, duration, units, currencies, restatements, and quarter-versus-year-to-date facts before comparison.
- **Conflict visibility:** surface material disagreement, amendments, restatements, and stale claims rather than silently choosing convenient evidence.
- **Safe access:** use only permitted public access patterns; respect licensing, robots controls, rate limits, and redistribution restrictions.
- **Fail closed:** unsupported, ambiguous, stale, or identity-mismatched claims must not be presented as verified.
- **Personalization boundary:** Intelligence Mode may change prioritization, framing, and presentation, but not the underlying evidence or factual conclusion.

## 3. Coverage ladder

| Level | Capability | Exit condition |
|---|---|---|
| 1 | Standard US issuer facts | Comparable SEC 10-K/10-Q facts with claim-level citations |
| 2 | US metric and sector packs | General-company metrics plus tested bank, insurer, SaaS, REIT, energy, healthcare, retail, and industrial schemas |
| 3 | Foreign issuer filings | 20-F/6-K and prioritized jurisdiction/IFRS sources with entity, currency, and calendar normalization |
| 4 | Unstructured primary documents | Reliable extraction from releases, presentations, calls, regulatory decisions, and other issuer/regulator documents |
| 5 | Multi-source public web | Trusted current context from news, government, exchange, industry, and public datasets with source ranking and conflict handling |
| 6 | Universal research orchestration | Arbitrary public-company questions decomposed, researched, synthesized, remembered, and audited end to end |

## 4. Delivery phases

### Phase A — Harden the current SEC foundation (P0, in progress)

Current foundation: account-owned thesis snapshots and conversations, History and Research Trail integration, research recall, personalization context, and claim-level comparable SEC evidence for revenue, operating income, and operating cash flow.

Next work:

- Continue expanding exact-period and duration disambiguation beyond the implemented
  10-Q quarter/YTD, 10-K annual/fourth-quarter, non-calendar 53-week year,
  amendment, malformed-duration, and duplicate-fact regression gates.
- Continue amendment/restatement, units, and scale hardening beyond the
  implemented latest-filing precedence, same-day amendment preference,
  equivalent-duplicate collapse, conflicting-restatement fail-closed gates,
  finite-value admission, and exact unscaled USD/share/per-share claim binding.
- Continue calculation-provenance expansion beyond the implemented free-cash-flow
  contract, which preserves its formula, exact period/unit/scope compatibility,
  and both accession-bound input references separately from reported facts.
- Continue entity-resolution benchmarking beyond the implemented SEC dotted/hyphenated
  share-class normalization; explicit former-ticker, former-name, subsidiary, and
  business-unit metadata; and close-date-bounded acquisition aliases that fail closed
  before the current parent's ownership began. The first spin-off/predecessor cohort
  now covers PayPal/eBay, Kyndryl/IBM, GE HealthCare/GE, and GE Vernova/GE, while
  same-issuer former-ticker windows preserve historical FB/META resolution. The first
  merger/divestiture-successor cohort now preserves WBD's AT&T/Discovery chain and
  Viatris's Mylan/Upjohn chain, failing closed before each successor existed. Broader
  merger chains, asset divestitures, and historical security-master coverage remain.
  Analysis requests now propagate an explicit point-in-time boundary into resolution,
  with an eight-case frozen acceptance cohort spanning acquisition, separation,
  former-ticker, merger-successor, and divestiture-successor behavior.
  SEC retrieval now anchors its lookback and end date to that same boundary, while
  latest-only providers are suppressed for historical requests rather than leaking
  future information into point-in-time analysis. The main question pipeline also
  propagates the boundary into structured SEC revenue and metric selection, which
  rejects facts whose period end or filing date falls after the requested date.
  Historical questions now use the same temporal identity resolver before the
  main `/ask` route, returning an explicit clarification instead of attributing
  pre-acquisition, pre-separation, or pre-merger evidence to today's issuer.

### Phase B — General-company metric families (P0)

Add verified comparable facts for:

- net income and diluted EPS;
- gross profit and gross margin inputs;
- research and development;
- capital expenditure and free-cash-flow inputs;
- cash, debt, interest expense, and share count;
- segment revenue and segment profit where the issuer reports them comparably;
- dividends, repurchases, and stock-based compensation.

Derived metrics must store their formula and input evidence. ClearSignal must not silently substitute a non-GAAP issuer metric for a standardized accounting fact.

### Phase C — Sector-specific intelligence packs (P0/P1)

| Sector | Initial verified metrics and events |
|---|---|
| Banks | Net interest income/margin, deposits, loans, provision, charge-offs, capital ratios including CET1 |
| Insurers | Premiums, underwriting result, loss/expense/combined ratios, reserves, catastrophe disclosures |
| SaaS and software | RPO/cRPO, stock compensation, cloud/subscription mix; ARR and retention only when explicitly disclosed |
| REITs | NOI, occupancy, debt maturity, property/segment data; FFO/AFFO only when explicitly reconciled |
| Energy and mining | Production, realized price, reserves/resources, unit costs, capex, project milestones |
| Pharma and biotech | Trial, regulatory, safety, patent/exclusivity, pipeline, and product-sales milestones |
| Retail and consumer | Comparable sales, store count, inventory, traffic/ticket, category and geographic mix when disclosed |
| Industrials and telecom | Backlog, orders, utilization, subscribers, churn, ARPU, and project/program milestones when disclosed |

Each pack requires a taxonomy, aliases, issuer-specific disclosure rules, period semantics, source hierarchy, and adversarial tests. Non-standard KPIs must retain the issuer's definition and cannot be compared across companies without a compatibility check.

### Phase D — Foreign issuers and global filings (P1)

- Support SEC 20-F and 6-K facts and ADR-to-home-listing identity mapping.
- Add IFRS taxonomy mapping without forcing US-GAAP equivalence.
- Prioritize official jurisdiction sources, beginning with major markets and expanding by demand: SEDAR+, Companies House/FCA/UK ESEF, EU national filing systems, ASX, NZX, and selected Asian exchanges/regulators.
- Normalize fiscal calendars, reporting currencies, translation rates, units, and local filing terminology.
- Preserve the original-language source; add translated text only as a labeled aid.

### Phase E — Unstructured primary-source intelligence (P0/P1)

Ingest and analyze legally accessible:

- earnings releases, investor presentations, shareholder letters, and issuer press releases;
- public earnings-call transcripts or licensed transcript feeds;
- regulatory decisions, enforcement actions, approvals, recalls, and safety notices;
- proxy statements, governance documents, insider disclosures, and material contracts;
- public product, pricing, status, and policy pages;
- patent, clinical-trial, government-contract, tender, and other authoritative public databases.

Required platform capabilities include HTML/PDF parsing, OCR, table extraction, document versioning, section/page anchors, bounded quotations, duplicate detection, and change tracking.

### Phase F — Trusted secondary and current context (P1)

- Add reputable news and specialist trade reporting for events not yet reflected in filings.
- Add exchanges, central banks, statistical agencies, courts, legislatures, and industry/regulatory datasets.
- Attach source tier, freshness, corroboration count, and correction history to extracted claims.
- Separate reported fact, third-party estimate, market consensus, calculation, and model inference in both storage and UI.
- Require corroboration or an explicit single-source warning for high-impact secondary-source claims.

### Phase G — Universal research planner and evidence graph (P0)

The shared evidence response contract now exposes per-reference freshness,
availability, supersession, and material-conflict states; preserves published,
filed, observed, and retrieved timestamps; and carries a fail-closed integrity
summary into account-owned research-memory metadata.
The production question pipeline now applies that contract before any agent,
question-answer, synthesis, comparison, or source-answer step: conflicting,
superseded, unavailable, and post-boundary evidence is retained for audit but
blocked from prompting, while stale evidence remains admitted with its warning.

Build a query planner that can:

1. resolve the company, security, jurisdiction, time period, metric, and user intent;
2. decompose broad questions into answerable research claims;
3. select the appropriate source families and retrieval strategy;
4. extract and normalize evidence while preserving document anchors;
5. detect contradictions, amendments, stale evidence, and missing comparisons;
6. synthesize an answer whose claims link to evidence IDs;
7. expose why a source was selected and what could not be verified.

The evidence graph should connect issuer, security, document, reporting period, claim, metric, event, person, product, geography, and prior thesis. This becomes the shared substrate for comparisons, Research Trail, History, alerts, and cross-conversation recall.

### Phase H — Reliable cross-conversation memory (P0)

- Persist only account-owned research artifacts and verified evidence references.
- Recall prior theses and conclusions with their original as-of date and source set.
- Mark recalled claims stale when newer filings, corrections, or contradictory evidence arrive.
- Make memory use visible: show what prior research was reused and allow the user to exclude or forget it.
- Keep user preferences separate from factual evidence and never let preference memory override contradictory facts.
- Add deletion, export, retention, isolation, and authorization acceptance tests.

### Phase I — Cinematic Intelligence Mode experience (P0)

- Present an evidence-first narrative with progressive disclosure rather than a document dump.
- Add source-aware claim cards, period comparisons, document previews, and a research timeline.
- Visualize relationships among the current answer, prior thesis, new evidence, and changed conclusion.
- Design explicit states for conflicting evidence, unavailable sources, incomplete comparisons, stale memory, and unsupported questions.
- Maintain polished motion, loading transitions, responsive/mobile behavior, accessibility, and reduced-motion support.
- Keep voice outside the full-launch critical path.

### Phase J — Launch validation and controlled expansion (P0)

- Build a benchmark spanning company sizes, sectors, fiscal calendars, filing types, and jurisdictions.
- Test fresh filings, amended filings, restatements, duplicate facts, ticker changes, mergers, foreign currencies, missing periods, malformed documents, source removal, and conflicting reporting.
- Red-team prompt injection and malicious content inside retrieved public pages and documents.
- Verify account isolation, guarded shared ticker routes, deletion, export, and memory non-leakage.
- Establish latency, availability, freshness, retrieval-cost, and cache-invalidation budgets.
- Roll out by capability flag and coverage cohort; never imply universal verified coverage before the relevant source family passes acceptance.

Current foundation (2026-10-01): the frozen registry contains 18 issuers and
54 core research questions. The zero-side-effect production rehearsal spans 13
issuers across eight sectors, including three mid-cap and three small/micro-cap
issuers, with enforced cap-tier floors. The 100-issuer target, 30 issuers per
principal cap tier, and additional sector/jurisdiction depth remain launch work.
The smaller-company factual gate separately requires complete adjudication,
at least 95% material numerical accuracy, 100% claim-to-source binding, zero
fabricated sources, and no issuer-level stop-ship failure in either cap tier.
Its first primary-source pack freezes 24 material revenue, net-income, and
current/prior operating-cash-flow facts plus six recomputed trend comparisons for
AA, DOCU, ETSY, ACHC, ACMR, and MAN against exact SEC accession numbers,
acceptance timestamps, archived filing URLs, and SHA-256 document identities.

## 5. Full-launch gates

**Open P0 launch blocker — cross-company coverage (2026-10-06):** a public-router
audit of the complete 18-company benchmark, including the proposed DocuSign
fix, correctly handed off only 14 issuers in all three input forms. All three
small/micro entries failed; `MAN` incorrectly handed off Viatris. Isolated
negative controls also exposed unrelated consolidated revenue being accepted
for unsupported operating-risk topics. Unrestricted public-company coverage
must not launch until exact issuer routing, question-part relevance, readable
saved responses and a signed-in cross-sector/size matrix pass. See the
[cross-company audit and release criteria](CROSS_COMPANY_COVERAGE_AUDIT_20261006.md).
Local remediation (6 October): exact structured issuer selection, official SEC
long-tail discovery, readable saved gap answers and unsupported-risk gating pass
[post-fix acceptance](CROSS_COMPANY_COVERAGE_FIX_ACCEPTANCE_20261006.md).
The original audit is preserved as the failing baseline. This launch gate remains
open until required CI, deployment and signed-in issuer/topic acceptance pass;
local routing success does not complete universal risk extraction.

Broader evidence testing (7 October NZ / 6 October UTC): a new 33-issuer,
11-sector cohort checks ticker, official-name and question-only routing, exact
source spans, risk-topic relevance, separate numeric/risk question parts, saved
answers and owner isolation. Shared risk-topic selection now removes the
four-issuer extraction whitelist for additional exact SEC-directory identities.
The read-only live SEC acceptance CLI distinguishes useful cited answers from
safe gaps and retrieval errors; it cannot authorize launch. Four cached full
filings pass replay, while the expanded live retrieval and signed-in matrix remain
open. Foreign filing layouts and multi-topic risk completeness remain explicit
gaps. See [broader company evidence acceptance](BROAD_COMPANY_EVIDENCE_ACCEPTANCE_20261007.md).

Signed-in post-deployment acceptance (7 October NZ / 6 October UTC) sampled fifteen
companies across all eleven sectors: four returned attributed risk disclosures
and eleven returned explicit gaps. This is a failing useful-evidence sample;
the broad-company launch gate remains open. Annual fallback after a failed first
quarterly download is being repaired, with extraction/timing diagnostics added
to isolate the actual gap causes. See [live results and required follow-up](COMPANY_EVIDENCE_LIVE_20261007.md).

The PR #195 live retest still returned gaps for AA, MAN, ACHC and ACMR, while
DOCU retained cited disclosures. Read-only Render diagnostics confirmed all
downloads succeeded but the four annual texts hit the retained-text cap without
a complete Risk Factors section. A follow-up preserves bounded complete later
sections and excludes explicit hidden HTML/XBRL metadata. This requires fresh
deployed acceptance and does not clear the broader launch gate.

PR #196 deployed acceptance improved DOCU to source-bound September quarterly
disclosures, but AA, MAN, ACHC and ACMR still returned gaps. Full-visible Render
diagnostics exposed split words in actual SEC section headings (`Ri sk`, `Ite m`)
and an ACMR section just above the former size ceiling. The next repair supports
split fixed heading words and a bounded 200,000-character general issuer section,
with Apple's stricter ceiling and claim/identity gates retained. Authored
regressions pass; fresh deployed acceptance and the broader live cohort remain
required. This work remains an open launch blocker.

Bounded Services risk slice (2026-10-06): AAPL periodic-filing extraction can
attribute qualitative operating-risk disclosures with exact quotes, filing dates
and document identities. This is initial issuer coverage, not a verified risk
outcome or universal risk-completeness claim. Apple signed-in production acceptance
passed on 6 October; broader issuer, section, version and jurisdiction work is tracked in
[Source-backed Services risks](SOURCE_BACKED_SERVICES_RISKS.md).

Issuer-risk expansion (2026-10-06): Microsoft Cloud, NVIDIA Data Center and
DocuSign subscription-renewal disclosures now have explicit issuer/topic matching,
bounded periodic-SEC retrieval, exact quote spans and gated saved answers. Three
full annual HTML filings passed local extraction/admission checks. Signed-in
production acceptance remains pending after deployment; this does not complete
universal risk ranking, segment-growth extraction or quantified risk assessment.
See [Source-backed issuer risks](SOURCE_BACKED_ISSUER_RISKS.md).

ClearSignal is ready for full launch when all P0 gates pass:

- Every material factual statement in benchmark answers has evidence, or is visibly labeled as calculation/inference.
- No unsupported attribution or cross-company/period identity error appears in the release benchmark.
- At least 90% of supported benchmark questions return a useful claim-level cited answer; the remainder return a precise, safe gap state.
- SEC general-company metrics and the prioritized sector packs pass comparable-period and source-link validation.
- Primary-document ingestion reliably preserves page/section/table anchors and document versions.
- Cross-conversation recall shows provenance and staleness and passes account-isolation tests.
- Shared ticker-wide research routes remain guarded under direct, indirect, and adversarial access tests.
- History, Research Trail, comparisons, and Personalized Intelligence Mode pass signed-in end-to-end testing on desktop and mobile.
- Production monitoring covers retrieval failure, source drift, extraction error, stale evidence, authorization denial, latency, and cost.

Under the October 9 user directive, international public-company coverage is part
of the prioritized universal-quality workstream. Optional long-tail sources may
continue expanding, but an unsupported market cannot count as equivalent quality
merely because its questions are accepted or return safe gaps. Any staged release
must disclose its validated scope; a narrower beta is not completion of the
universal launch goal. A question being accepted must never be confused with its
answer being verified.

Broad-company acceptance update (2026-10-07): the deployed split-heading repair
restored all five signed-in retest cases, and the complete 33-company read-only
cohort reports 20 source-binding passes and 13 gaps. Full launch coverage remains
blocked. Prioritize the demonstrated TSLA full-annual/amendment selection defect,
COST/PLTR section boundaries, topic-level review for BA/H/F/NFLX, and observed
filing discovery for JPM/XOM. Foreign-form breadth remains a separate expansion.
These figures measure selected issuer/topic coverage, not overall roadmap
completion. See [live coverage record](COMPANY_EVIDENCE_LIVE_20261007.md).

Post-PR #200: the complete eight-case domestic subset now has five passes
(COST/BA/PLTR/H/F) and three gaps (JPM/XOM/NFLX). JPM needs bounded retrieval
of the observed larger primary files; Netflix needs explicit customer/member
retention wording. XOM is a newly reorganized holdings issuer (CIK 2115436),
with prior annuals under predecessor CIK 34088. Add verified, dated issuer
succession and source-document provenance before reusing predecessor research;
the current identity guard must not be relaxed or the cohort identity changed
to manufacture a pass. Exact current-CIK annual discovery alone is insufficient.
Retest these cases, signed-in storage and the complete supported cohort before
clearing broad-company launch acceptance. No overall percentage is inferred.

Follow-up after PR #198: TSLA now passes a fresh signed-in supply-chain test and
the separate read-only source-span/citation check. The complete nine-case
domestic-gap subset still has eight gaps (COST/JPM/BA/XOM/PLTR/H/F/NFLX). Do not
replace the earlier full-cohort result with an extrapolated coverage percentage.
Compact closing-heading support and opt-in bounded source inspection are the
next repair; keep the launch gate open until fresh production reports establish
restored useful answers and complete source binding.

## 6. Immediate implementation sequence

8 October 2026 owner-reported complete post-PR #203 run: all 29 domestic cases
pass; SPOT, ASML, TSM and NVO remain gaps. This is source-binding acceptance for
the frozen question sample, not signed-in acceptance or full launch clearance.
PR #204 is merged; the owner-reported deployed four-case subset passes SPOT
and TSM and still reports ASML and NVO gaps. This does not establish a new full
cohort count. The next repair adds a document-specific, hash-pinned ASML integrated
Risk Factors mapping. PR #206 repaired the changing transport-script hash and is
merged; the owner-reported deployed subset now passes SPOT, ASML and TSM, with
NVO still a gap. This does not establish a new full-cohort count. The next slice
verifies NVO's exact 20-F incorporation statement and observed annual-report link,
then extracts the reviewed clinical pipeline table with descriptions and impacts
separate from explicitly excluded mitigating actions. Both old and freshly
downloaded NVO documents pass local two-attempt source/citation replay, and owned
snapshot persistence is tested. Required follow-up CI, deployment and fresh
signed-in/live/saved acceptance remain separate gates. See
[foreign annual section work](FOREIGN_20F_RISK_SECTIONS_20261008.md),
[ASML integrated-report work](ASML_INTEGRATED_RISK_CONTEXT_20261008.md), and
[NVO incorporated table work](NVO_INCORPORATED_RISK_TABLE_20261008.md).


Post-PR #199 targeted inspection: COST now passes; the complete eight-company
domestic subset still has seven gaps (JPM/BA/XOM/PLTR/H/F/NFLX). Apply the observed
passage/section normalization repairs, then retest their actual source spans and
signed-in answers. Separately address JPM's confirmed download-size rejection
and XOM's missing annual metadata without weakening issuer identity or bounded
retrieval. NFLX needs customer-subscription evidence; labor/content renewal risks
must not be substituted. This subset does not revise the full-cohort coverage
percentage or clear the full-launch gate.

Successor-context implementation update (2026-10-08): PR #202's fresh signed-in
JPM retest delivered two cited credit-loss disclosures and passed saved-thread,
History and Research Trail checks for that run. The next implementation adds
an explicit, document-specific XOM predecessor context link, preserving both
issuer identities, relationship proof and the original annual filing date.
Ordinary SEC discovery remains exact-CIK. Exxon source/live acceptance and a
fresh complete cohort remain required; this does not revise the last complete
20-pass/13-gap result. See [reviewed successor context and retest plan](XOM_REVIEWED_PREDECESSOR_CONTEXT_20261008.md).

1. Finish the general-company SEC metric family and period/identity hardening.
2. Add the universal evidence schema and source-quality model before adding many new connectors.
3. Deliver the first sector packs: banks, insurers, SaaS, and REITs.
4. Add primary-document ingestion for earnings releases and investor presentations.
5. Connect verified claims and staleness to account-owned cross-conversation memory.
6. Ship the evidence graph and gap/conflict states in Intelligence Mode.
7. Add foreign issuer and trusted secondary-source cohorts behind capability flags.
8. Run the cross-sector, cross-jurisdiction launch benchmark and controlled beta.

## 7. Explicitly deferred

- Voice interaction is not required for full launch.
- Private, credentialed, leaked, unlawfully obtained, or redistribution-prohibited information is out of scope.
- Automatic backfill of older, pre-ownership analyses is deferred unless separately designed and approved.
- Autonomous trading, personalized investment instructions, and claims of exhaustive internet access are out of scope.
