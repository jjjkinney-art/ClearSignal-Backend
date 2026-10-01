# Universal Public Intelligence Roadmap

**Date:** 2026-09-28  
**Status:** Active roadmap  
**North star:** ClearSignal should accept a research question about any public company and analyze all legally accessible, relevant public information it can verify—while making every factual claim inspectable, attributable, current, and honest about uncertainty or missing coverage.

This roadmap supersedes the live-data scope of the older static company-profile coverage plans. It extends the current account-owned research memory, personalized Intelligence Mode, and claim-level SEC evidence work into a universal public-information research system.

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
  equivalent-duplicate collapse, and conflicting-restatement fail-closed gates.
- Preserve filing, accession, form, period, taxonomy concept, and calculation provenance through the answer layer.
- Benchmark entity resolution across ticker changes, multiple share classes, subsidiaries, and acquisitions.

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

Foreign jurisdiction breadth and long-tail public-web connectors may continue expanding after launch, but the product must already accept those questions and respond with an honest coverage state. A question being accepted must never be confused with its answer being verified.

## 6. Immediate implementation sequence

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
