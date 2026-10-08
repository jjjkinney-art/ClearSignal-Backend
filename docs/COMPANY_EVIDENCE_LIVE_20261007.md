# Signed-in broad-company evidence acceptance

Latest status (8 October, owner-reported complete post-PR #203 run): all 29
domestic cases pass; SPOT/ASML/TSM/NVO remain foreign gaps. This source-binding
result does not establish signed-in foreign acceptance or full launch clearance.
The remaining sections preserve the chronological acceptance record; earlier
counts are not current full-cohort results.

Recorded 7 October 2026 NZ / 6 October UTC after the owner confirmed deployment
of PR #194 (merged main `7e97e529fcbc4a2b42690b450c06a1339331dca9`).
The runtime SHA could not be independently retrieved from this environment;
the production frontend and authenticated analysis flow were exercised directly.

## Result: broad-company launch gate remains open

Fifteen fresh company/topic investigations across all eleven cohort sectors were
run through Intelligence Mode with explicit ticker scopes. Four returned dated
issuer risk disclosures with answer citations and inspectable SEC filing links.
Eleven returned readable, saved evidence-gap answers. Safe withholding prevents
unsupported claims, but is not a useful-answer coverage pass.

| Issuer | Sector | Topic | Observed result |
| --- | --- | --- | --- |
| WDFC | Consumer Staples | Distribution | Attributed disclosures |
| MAN | Industrials | Staffing demand | Evidence gap |
| DOCU | Technology | Subscription renewals | Attributed disclosures |
| AA | Materials | Energy supply | Evidence gap |
| ACHC | Health Care | Patient safety | Evidence gap |
| ACMR | Technology | Customer concentration | Evidence gap |
| JPM | Financials | Credit losses | Evidence gap |
| COST | Consumer Staples | Membership renewals | Evidence gap |
| LLY | Health Care | Drug development | Attributed disclosures |
| BA | Industrials | Production quality | Evidence gap |
| XOM | Energy | Commodity prices | Evidence gap |
| ETSY | Consumer Discretionary | Marketplace sellers | Evidence gap |
| NWE | Utilities | Energy supply | Evidence gap |
| SLG | Real Estate | Liquidity | Attributed disclosures |
| NFLX | Communication Services | Subscription renewals | Evidence gap |

Each run displayed the expected company ticker and two saved messages. Tests used
the marker `Broader coverage acceptance October 7.` and normal private account
storage; no shared ticker mutation or external notice delivery was requested.
This record excludes account identifiers, tokens, other private research, full
filing quotations and raw browser snapshots.

The four attributed results are UI observations, not independent certification
of every quote span, causal relevance, risk ranking, current risk occurrence or
investment quality. Lilly's second disclosure concerns general outsourcing and
clinical subjects; its relevance to drug development deserves further review.
Numeric context was shown separately and did not substitute for missing risks.
The other eighteen members of the frozen cohort were not exercised in this run.
This is a failing live sample, not a passed 33-company acceptance report.

## Private memory and history

Both History and Research Trail displayed all fifteen marked fresh analyses.
The History `AA` filter included the new Alcoa test under AA, alongside its
earlier correctly scoped test. Private recall ranked the new WD-40 investigation
as the likely match, and reopening preserved both saved messages and the cited
answer. Research Trail's WDFC filter also showed that answer. These checks do not
prove foreign-owner isolation in production; that remains covered separately by
the ownership regressions and launch acceptance procedures.

## Remediation and required next evidence

Code inspection found a reproducible fallback defect: a failed first quarterly
download skipped annual-risk discovery, allowing the remaining attempt to be
spent on another quarter. The fix prefers the latest annual filing in the
remaining slot after a failed first quarter, just as after a quarter with no
qualifying risks. Failed attempts still count, the default ceiling stays two,
and no quote/admission/identity gate or router deadline is relaxed.

This defect is not yet established as the cause of the eleven live gaps.
Production responses do not reveal download, section, timing or filter outcomes.
The read-only SEC acceptance report now records download/extraction timings,
normalized text length, Risk Factors heading and complete-section counts, topic
sentence counts and extracted-disclosure counts. Counts cover only the scanned
prefix when extraction stops at its two-disclosure limit. No source prose or
user-agent contact is added to diagnostics. Production logs also identify form,
text length, disclosure count and document elapsed time without question text.

Run the full CLI cohort in an environment with configured SEC contact and
working SEC access. Inspect actual failure metadata and compare isolated CLI
timing against production router logs; isolated timing does not reproduce the
full `/ask` deadline. Fix the observed root causes and repeat signed-in cases
before clearing broad coverage. Shared routes remain guarded, old analyses are
not backfilled, and foreign forms/multiple requested topics remain open gaps.

Local validation: 294 relevant tests across seven isolated modules pass on Python
3.12; clean collection finds 14,951 tests. Required pinned CI and a fresh live
retest of this follow-up change remain separate release checks.

## PR #195 deployment retest and Render diagnostics

After the owner confirmed PR #195 deployed, fresh signed-in runs repeated AA,
MAN, ACHC and ACMR. All four still returned evidence gaps. DOCU remained a
positive control with two cited risk disclosures. All five records appeared
in History and Research Trail, and the exact AA investigation reopened with
its two saved messages and unchanged gap answer. This is a targeted five-case
retest, not the full cohort or a production cross-owner test.

The owner's read-only Render report evaluated at `2026-10-06T23:23:50.824460+00:00`
independently reproduced those outcomes: all ten attempted filings downloaded,
with no retrieval failures. DOCU's two annual disclosures matched original
normalized-document spans and answer citations. The four failing annual texts
each reached the 240,000-character retained-text cap.

| Issuer | Retrieval duration | Annual heading outcome | Disclosures |
| --- | --- | --- | --- |
| DOCU | 2,393 ms | One complete section | 2 |
| MAN | 4,990 ms | One heading, rejected as a prefix/reference | 0 |
| AA | 5,376 ms | One heading, rejected as a prefix/reference | 0 |
| ACHC | 3,308 ms | Three headings, all rejected as prefixes/references | 0 |
| ACMR | 2,190 ms | Twelve headings; eleven rejected, one lacking a closing section | 0 |

These isolated timings do not establish `/ask` timing under concurrent load.
MAN's quarterly text had seventeen topic sentences but none met the quote
contract; this change does not relax that contract or claim to resolve that
additional gap. The report does not identify the exact hidden markup or full
visible length of these annual files, so the cutoff is a confirmed symptom,
not proof of a single cause for every company.

The follow-up excludes explicit hidden HTML and Inline XBRL headers/hidden
facts from both narrative and table extraction. Visible Inline XBRL values
remain. For strictly eligible SEC periodic HTML only, a complete, bounded
Risk Factors section may be selected from later in the normalized visible
filing instead of losing it to the beginning-of-document cap. The full-file
byte hash remains unchanged and disclosure offsets refer to the selected
normalized text. The selection uses the same TOC/reference exclusions,
explicit closing heading and 160,000-character section ceiling as before.
No missing boundary is synthesized and no quote, identity or admission gate
is weakened. Other document modes keep their existing text limits.

The report now includes total normalized visible length, selected-window offset
and selection mode, allowing a deployed rerun to distinguish a prefix cutoff
from a retained complete section. External stylesheet visibility is not
evaluated. Required pinned CI and fresh Render/live acceptance are still
necessary; broad-company launch acceptance remains blocked.

Follow-up local validation: 396 relevant tests pass across nine isolated modules;
clean collection finds 14,962 tests. The bounded selector considers at most
64 candidate headings and searches only within the existing section ceiling.
Authored regression documents establish the parser repair; they are not a live
coverage pass for the four failing issuers.

## PR #196 deployment retest: split-word headings and section ceiling

The owner confirmed deployment of merged main
`6268b4a8fadfad4bce558d740aadd20ad7c792a1`. Five fresh signed-in runs used
`Visible SEC section deployment retest October 7.`. AA, MAN, ACHC and ACMR
still returned evidence gaps; DOCU now cited two disclosures from its quarterly
filing dated 2026-09-04 instead of the prior annual filing. All five records
appeared in History and Research Trail. Reopening the fresh AA record restored
its two saved messages and gap answer. These are one-account UI checks, not
production foreign-owner isolation or complete cohort certification.

The owner's read-only Render report evaluated at `2026-10-07T00:07:12.163004+00:00`
confirmed the newer DOCU quotes matched original source spans and answer
citations. Its selected complete risk section retained 139,508 characters,
starting at offset 101,422 in 247,237 visible characters. All four other issuers'
downloads succeeded and produced no admitted risks. The follow-up full-visible
heading diagnostic identified these actual opening layouts:

| Issuer | Annual visible characters | Actual risk heading offset | Observed issue |
| --- | --- | --- | --- |
| MAN | 353,326 | 39,426 | `Item 1A. Ri sk Factors`; strict closing matcher found none |
| AA | 587,884 | 69,065 | `Item 1A. Ri sk Factors.`; next strict closing at 153,758 |
| ACHC | 419,805 | 75,464 | `Item 1A. Ri sk Factors`; strict closing matcher found none |
| ACMR | 458,092 | 57,394 | Canonical heading; marker-to-closing distance 163,277, above old ceiling |

MAN's actual quarterly heading also splits `Item` as `Ite m`. The diagnostic
does not include the actual closing-heading text for MAN or ACHC; allowing
split letters in recognized closing titles is a covered parser repair, not
proof that those live files now close or contain qualifying topic sentences.
The preceding document cutoffs were symptoms, not a complete diagnosis. AA's
actual annual risk section was inside the retained prefix but missed because
of the split opening word. No issuer identity, risk quote or impact assessment
was inferred from these headings.

The next repair matches whitespace inside the fixed known heading words without
rewriting normalized source text or changing quote offsets. TOC entries and
quoted or explicit cross-references cannot establish opening or closing section
boundaries. Candidate scans stay bounded at 64. The general issuer risk-section
ceiling becomes 200,000 characters to accommodate the observed ACMR section;
Apple's stricter 80,000-character extraction ceiling stays unchanged. SEC file
bytes remain limited to 10 MB and retained text to 240,000 characters. Quote
length, numeric exclusions, topic/issuer/admission checks, two-disclosure and
two-document ceilings, and the production router deadline stay unchanged.

Local validation: 427 relevant tests pass across ten isolated modules, including
authored split-span HTML, the longer bounded section, original span and answer
citation checks, false closing references, oversized sections and the unchanged
Apple ceiling. Clean collection finds 14,993 tests. Required pinned CI and fresh
Render/signed-in acceptance remain necessary. This repair does not establish
live useful-answer coverage for the four failing issuers or clear launch.


## PR #197 deployment: five signed-in cases and complete CLI cohort

After the owner confirmed deployment of main
`bc01432c9af9032d689132d1fc607168c0d31783`, five independent signed-in
investigations used `Split-heading coverage retest October 7.`. All returned
issuer disclosures with answer citations: AA two, MAN one, ACHC one, ACMR two,
and DOCU two. The four earlier gaps now cite annual filings; DOCU retains its
2026-09-04 quarterly disclosures. All five appeared in History and Research
Trail. Reopening the exact fresh AA investigation restored both messages and
the same answer. Runtime SHA was not independently retrieved.

These UI checks establish restored retrieval and private persistence for the
five requested cases, not all-company coverage or complete analysis quality.
MAN's admitted disclosure concerns reputational harm causing lost client
engagements and recruitment/retention difficulties; its narrower relevance to
staffing demand needs review. AA's first quote refers to preceding events that
are not reproduced in the answer. Source inspection remains important.

The owner's complete compact Render report confirms `complete: true` and
20 passes / 13 gaps across the frozen 33-company cohort. Each reported pass
has reason `exact_source_spans_and_answer_citations`, including all five
signed-in retest issuers. The original pasted terminal excerpt began midway
through Visa's row; the subsequent compact output supplied every case and all
remaining gap diagnostics. No full-cohort signed-in `/ask` run was performed.

Passing symbols: AAPL, MSFT, NVDA, DOCU, MAN, AA, ACHC, ACMR, WDFC, ETSY, LLY,
V, NWE, LQDT, AZZ, MOD, SLG, CRM, KHC and A. This is evidence-binding coverage
for one selected topic per issuer, not a roadmap-completion percentage or a
certification of risk rankings, forecasts, financial impact or all topics.

| Remaining symbols | Observed diagnostic | Required follow-up |
| --- | --- | --- |
| COST | Both quarterly and annual risk sections lack a recognized closing boundary; annual text is fully retained | Inspect actual closing headings before changing boundaries |
| PLTR | Both filings lack a recognized closing boundary; retained prefix is shorter than total visible text | Distinguish closing layout, section size and cutoff using actual headings |
| TSLA | Quarterly section has no qualifying risk; fallback selected a 10-K/A with no risk headings | Prefer the full annual filing within the same download budget |
| BA, H, F, NFLX | Complete sections and topic sentences exist, but no sentence qualifies | Inspect topic matching and original context; do not simply relax admission |
| JPM | No document diagnostics supplied | Inspect filing discovery and retrieval failures; cause is not established |
| XOM | Only one quarterly document diagnostic supplied | Inspect annual discovery and any remaining download failure |
| SPOT, ASML, TSM, NVO | No document diagnostics; frozen foreign-reporting cohorts remain unsupported by the periodic risk extractor | Add explicit foreign-form parsing and validation separately |

## Full-annual fallback repair and diagnostic follow-up

When the newest quarter or amendment has no qualifying risk, the remaining
slot now prefers an unamended 10-K. A 10-K/A can update governance or signatures
without repeating annual Risk Factors, as demonstrated by the TSLA report.
If no full annual is discovered, a quarter can still fall back to an amendment.
A newest amendment that already supplies qualifying risk is retained. An
amendment without risk can now fall back to the full annual if a slot remains.
Failed downloads consume the budget, duplicate URLs are not retried, and the
normal two-download ceiling and two-year discovery window remain unchanged.
The selected source keeps its actual form, filing date, hash and quote offsets.

The read-only acceptance report now records requested forms, result forms and
filing dates, discovery duration, and whether the provider returned filings,
an empty/unavailable result, or raised an exception. An empty result is not
classified as an unsupported company or a network failure: the provider can
withhold filings for several reasons. No contact, question, document prose or
exception message is added to these diagnostics.

Required next evidence is pinned CI, a deployed TSLA retest, and renewed gap
reports including filing discovery and retrieval failures. The full cohort
still fails; no launch gate is cleared by this repair. Shared ticker routes,
account ownership, existing historical records and external delivery are not
changed. The actual TSLA full annual has not yet been retrieved by this repair;
authored fixtures verify selection and source binding, not live recovery.

Local validation of this follow-up: 451 tests pass across ten isolated modules
on Python 3.12 with the pinned top-level dependencies. Clean collection finds
15,009 tests; the existing Starlette/AnyIO alias deprecation warning remains.
Required pinned Python 3.11 CI and post-deployment live acceptance are separate.

## PR #198 live confirmation and remaining domestic gaps

The owner supplied a Render deployment screenshot for main `9cd0eab` on 7
October 2026 NZ. A fresh signed-in TSLA supply-chain investigation returned two
cited disclosures from the full 10-K filed 2026-01-29. Both messages persisted;
History and Research Trail showed the same answer, and reopening the saved
investigation restored its citations. The browser displayed its own timezone
(6 October, 9:52 PM); this does not change the filing date. No account identifier
or token is retained here.

The complete subsequent nine-case Render report recorded TSLA as a pass with
`exact_source_spans_and_answer_citations`, and eight gaps: COST, JPM, BA, XOM,
PLTR, H, F and NFLX. This was a subset rerun; do not present it as a fresh
33-company result or as an overall roadmap-completion percentage.

JPM discovered quarterly and annual filings, but both downloads were rejected
as `document_rejected`; the precise ingestion reason was not yet reported. XOM
discovered a quarter while full annual and amendment discovery returned
`empty_or_unavailable`. COST and PLTR downloaded filings but did not establish
complete risk boundaries. BA/H/F/NFLX reached topic sentences but accepted none.
These observations do not establish whether the missing evidence is caused by
size ceilings, metadata alignment, unsupported heading layout, sentence
fragmentation or a correctly rejected quote.

The next repair supports explicit compact closing labels such as
`Item 1B.Unresolved Staff Comments`, preserving TOC/cross-reference rejection and
section ceilings. Its actual effect on COST/PLTR must be measured after deploy.
Quote checks retain their previous acceptance predicates and now expose stable
rejection counts. The CLI's optional `--inspect-source` adds bounded public
heading and topic-sentence excerpts, full-visible-text boundary coordinates,
retained-text quote offsets, and submission-array/lookback inventory. Excerpts
are diagnostic candidates, not admitted evidence. Ordinary reports remain
prose-free; neither mode exports contact headers, arbitrary exception text,
tokens or account data. No download ceiling or shared research route is changed.

After deploying this repair, rerun the eight domestic gaps with
`--inspect-source --output company-evidence-inspection.json`, and inspect the
reported rejection reasons and original source layout before further changes.
Repeat the complete frozen cohort and signed-in restored cases before clearing
the broader launch gate. Foreign periodic-form expansion remains separate.

Local validation for this repair: 498 tests passed across twelve relevant
modules; full collection found 15,036 tests with no collection errors. The
existing Starlette/AnyIO alias deprecation warning remains. These local results
do not substitute for pinned CI or a deployed coverage report. Opt-in inspection
adds parsing work to diagnostic timings, so compare uninstrumented request
timing separately when evaluating production latency.

## Post-PR #199 inspection and passage repair

The owner confirmed deployment of merged main `11dcf6a1c8c2ef4dfcf2e53d72821d93c430dbe1`.
The supplied compact extraction reports `complete: true` for eight cases: COST
passes; JPM, BA, XOM, PLTR, H, F and NFLX remain gaps. This is a targeted domestic
subset, not a new 33-company run or signed-in `/ask` acceptance.

Observed causes and limitations:

- COST's annual section now closes correctly and produces two bound disclosures.
- Both JPM downloads are rejected by the 10,000,000-byte ceiling. Their actual
  sizes are not recorded, so this repair does not guess a larger download limit.
- XOM's submissions response has 34 aligned recent rows, one requested 10-Q,
  no requested annual filing, and no archive listed within the two-year lookback.
  Array truncation is not the observed cause. Annual discovery remains open.
- PLTR's explicit annual Risk Factors body spans 298,623 characters, exceeding
  the prior 200,000-character section limit and 240,000-character retained text.
- BA has a narrative reference ending `in Item 1A. Risk Factors` incorrectly
  treated as a section opening. The real section also contains an explicit
  issuer-reported supplier disruption sentence, rejected for lacking a modal.
- H's occupancy/room-closure sentence contains an inserted page-number/contents
  footer and a room-closure mechanism absent from the adverse-language rule.
- F scans overlapping continuation headings repeatedly, and splits an observed
  topic sentence at `e.g.`. Its complete sentence is not in the bounded sample.
- NFLX's generic renewal wording includes entertainment labor agreements and
  content-license renewals, which cannot support customer subscription renewals.
  This repair narrows source qualification while preserving question routing.

The follow-up parser rejects narrative references and continuation headings,
scans each eligible section once, and shares exact sentence offsets between
extraction and inspection. Common abbreviations do not authorize sentence
fragments. SEC periodic normalization removes only the observed numeric
`Table of Contents` footer token and remaps heading offsets; substantive numbers
remain subject to the numeric claim guard. The raw-body content hash is unchanged.
The section bound is 320,000 characters and retained periodic text is 360,000,
enough for the observed PLTR section with explicit closing. Larger or incomplete
sections still fail closed; the Apple-specific 80,000-character bound remains.

Explicit adverse mechanisms include additional costs and closure of rooms or
facilities. An explicit `are/is experiencing` reported event can qualify alongside
the same adverse/scope checks. Every emission remains an attributed issuer
disclosure, not independent verification of occurrence, financial impact, or
thesis change. No numeric guard, issuer identity, ownership, document-download
count, shared route, or delivery boundary is removed.

Local validation: 529 unique relevant tests across thirteen modules pass, including
31 passage regressions. Hyatt and Boeing observed excerpts are replayed within
synthetic layouts; the Ford completion is authored. These tests do not establish
live recovery. Pinned CI, fresh deployed retrieval, signed-in persistence, and a
new full supported cohort remain required. The broad-company launch gate is open.

## PR #200 deployed: five passes and three distinct remaining gaps

The owner supplied a complete eight-case Render rerun after deployment of
main `5e19ff7b6a7b5120e2114fee954cb957d0ec3f04`. COST, BA, PLTR, H and F
pass exact original-span and answer-citation checks. JPM, XOM and NFLX remain
gaps. No new full 33-case or signed-in retest was supplied. Five of eight is
a targeted sample result, not a roadmap or full-cohort completion percentage.

| Issuer | Observed cause | Follow-up |
| --- | --- | --- |
| JPM | Quarterly and annual HTML both rejected at the 10 MB download ceiling | Eligible SEC periodic HTML now has a finite 15 MB ceiling; ordinary documents remain 2 MB |
| NFLX | Complete quarterly/annual sections found, but zero admitted subscription-risk sentences | Recognize explicit member/subscriber retention; keep non-adverse and labor/content renewal language withheld |
| XOM | No annual under the current holdings company's CIK | Separate successor/predecessor source-link work is required; never replace the current issuer with the former CIK |

SEC's [JPM annual directory](https://www.sec.gov/Archives/edgar/data/19617/000162828026008131)
lists the primary HTML at 12,927,325 bytes; its
[quarterly index](https://www.sec.gov/Archives/edgar/data/19617/000162828026054343/0001628280-26-054343-index.htm)
lists 11,513,874 bytes. The expanded bound is based on those observed files,
not unlimited downloads. Declared and streamed oversized bodies still reject,
including on absent or misleading content-length headers. Size rejection
diagnostics now include numeric limit/measurement fields without response
headers, request credentials or document bodies. The retained-text, section,
quote, Apple-specific, two-document and production router bounds are unchanged.
Larger files may increase memory and parsing time; fresh `/ask` timing remains
a separate requirement.

Netflix's [2025 annual filing](https://www.sec.gov/Archives/edgar/data/1065280/000106528026000034/nflx-20251231.htm)
contains explicit adverse member-retention mechanisms. The shared source rule
recognizes retaining members/subscribers, rather than substituting labor or
content renewals. Membership alone, member acquisition alone, employees,
members of a guild and non-adverse retention statements remain insufficient.
These are attributed issuer risk disclosures, not verified financial outcomes.

The integration test caught a crucial XOM distinction. The frozen cohort uses
**ExxonMobil Holdings Corp, CIK 2115436**, not predecessor CIK 34088. SEC's
[successor registration](https://www.sec.gov/Archives/edgar/data/2115436/000119312526291990/d71068d8k12b.htm)
and the current quarterly filing's
[basis note](https://www.sec.gov/Archives/edgar/data/2115436/000003408826000093/R9.htm)
establish the July 2026 reorganization. An exact current-CIK annual search
returned zero hits; a predecessor search returned annual metadata. This is
not proof of an array-alignment defect or permission to silently reuse a
different registrant's filing. The newly bounded annual discovery fallback
admits only independently matching current-CIK primary annual metadata. It
uses one five-second search per empty annual-only request, inspects at most
100 hits, returns at most five deduplicated results, and rejects exhibits,
other CIKs, co-registrants, invalid dates, partial responses and escaped paths.
It cannot itself repair XOM's succession gap.

Next: build an explicitly source-bound, dated succession relationship; retain
both current and source issuers and the predecessor document's actual date in
answer and memory provenance. Require negative tests for mere name/ticker
similarity, subsidiaries, unrelated transactions, date mismatch and expired
relationships. Repeat the XOM case before counting recovery. Broader foreign
forms remain a separate supported-coverage expansion.

Local validation: 591 unique relevant tests across fifteen modules pass,
including 59 new size, retention, annual-discovery and wrong-issuer cases.
The integration fixture is an authored issuer, not a current-XOM coverage pass.
Collection is clean apart from the existing Starlette/AnyIO deprecation warning
and intentionally retired test module. Pinned CI and fresh deployed retrieval,
signed-in answers/persistence and full-cohort acceptance remain required.
