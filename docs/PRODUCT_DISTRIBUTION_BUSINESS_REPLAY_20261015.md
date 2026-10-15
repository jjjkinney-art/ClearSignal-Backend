# Source-bound passive product-channel descriptions

## Captured evidence and scope

The separately authorized PR292 two-source capture completed once; its approval
is consumed. There are now ten consumed approvals (nine prior runs and this
capture). No new requests, approval, quota/deadline changes or reruns accompany
this offline fix. Current launch readiness remains unresolved.

The supplied results ZIP contains the exact saved public bodies, receipts,
analyses, SQLite ledger and terminal verification. All 16 payload hashes listed
in terminal verification matched after materialization. The ledger is not opened
through its mutating constructor. The capture terminal reports two settled SEC
claims, zero models, no unresolved claims/late workers/failures. The claim that
all 126 historical files remain unchanged is supported by the capture's recorded
verification; their remote paths are not independently available here.

NPK HTML: 1,404,517 bytes, SHA256
`8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
Fixed URL: `https://www.sec.gov/Archives/edgar/data/80172/000143774926008214/npk20251231_10k.htm`,
CIK 80172, 10-K filed 2026-03-13, as bound to prior primary references.

## Demonstrated NPK exclusion and narrow correction

An offline replay feeds those exact saved bytes through the real
`fetch_public_document` reader/normalizer, business extractor and business
reference binder. Requests are replaced with an in-memory response, DNS with a
fixed public-address fixture and directory lookup with the saved issuer identity;
all real socket audit operations are denied. This tests application processing
of saved bytes, not a new HTTP response or independent source authentication.

Baseline 9dcc1a68 reproduces the saved rejection counts exactly:
164 sentences, length 34, numeric/forward 66, subject/activity 64, no descriptions.
One complete qualitative sentence says products are sold primarily in the United
States and Canada directly to retailers and through independent distributors.
It is excluded because the existing current-business predicates expect an active
issuer subject or named issuer. The source's leading BOM is also retained.

Add one full-match grammar for a passive product distribution sentence, optionally
prefixed by a single BOM and/or `Our`. It requires `Products are sold`, an optional
bounded region phrase, and explicit retail/customer/distributor channels. It
allows no arbitrary trailing clauses or partial-sentence extraction. This is a
shared syntactic rule: no ticker, company, geography or product-name allowlist.
Existing 60–300-character, numerical/forecast/promotion, internal-activity,
complete-sentence, document eligibility, issuer URL and citation binding checks
remain mandatory. No limits or shared producer rules are weakened or bypassed.

Patched replay returns one bound description. Body hash, complete quoted text
(including BOM), original offsets and document identity remain unchanged.
The other 163 sentences retain their rejection results: length 34, numeric/forward
66, subject/activity 63. This supplies distribution context, not a complete
business model, competitive advantage or investment recommendation. Segment
marketing, unresolved pronouns and long mixed-content sentences remain excluded.
No factual-looking clause is clipped from promotional text.

## ACHC finding: no freshness patch justified here

ACHC Company Facts: 3,457,609 bytes, SHA256
`b1d48d703acb9cf3f60aaa852af3b91f4c463c554bf1a3d1bbf0ae55d0e977a3`.
The captured raw USD arrays for revenue, net income, operating cash flow and Assets
end at 2026-03-31 (latest filing date 2026-04-30). OperatingIncomeLoss ends at
2020-03-31 (filed 2020-05-05). These raw maxima agree with parsed diagnostics;
the parser is not discarding Q2 observations from these particular arrays.
The diagnostic helper's ability to select a 2020 comparison does not mean it was
admitted into a product answer. Existing production freshness screening excludes
that comparison against the latest issuer anchor. A replay of the real verified
metric producer with these saved arrays checks that exclusion separately.

This constrains the current captured snapshot only. It cannot establish the old
response, identify an upstream cache/lag cause, or prove that newer filings lack
financial data. The earlier core answer used Q2 inline filing evidence while the
monitoring route used Company Facts. No numerical freshness is fabricated here;
existing newer-filing coverage notices and explicit operating-income/margin gaps
remain. Adding filing fallback to monitoring would require explicit request/
quota review and is outside this change.

## Validation

The new synthetic tests retain exact source spans (including BOM), check ordinary
product-channel wording across invented contexts, reject forecast/numerical/
promotional/internal/ambiguous sentences without clipping, and retain metadata,
issuer identity and quote-tampering rejection. All tests and captured-byte replays
use pinned CPython 3.11.9 with audited dependencies, invented credentials and
all actual socket audit operations denied. No captured full body is committed.

287 tests passed in the first group: `test_product_distribution_business.py` and
`test_thesis_disclosures.py`. Related financial/source-answer/competition and
metric regressions are recorded below after completion. Hosted CI and independent
review remain pending before merge. No live confirmation or complete-answer
quality claim follows from this offline replay.

The second group passed 144 tests: `test_financial_thesis_foundation.py`,
`test_thesis_competition.py`, `test_competition_reference_failure.py`,
`test_thesis_gap_diagnostics.py`, `test_verified_sec_metrics.py`, and
`test_source_answer.py`. Total: 431 passed, no test failures. `git diff --check`
passed. The ACHC production replay returned Q1 revenue, net income, operating
cash flow and supplementary pretax income, with no 2020 operating income.

Both groups used this invocation, with FILES replaced by the paths above:

```bash
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
  SEC_USER_AGENT='Test contact@example.invalid' PINNED_PYTHON -I -B -c \
  "import sys,socket;sys.path[:0]=['.','tests'];socket.has_ipv6=False;sys.addaudithook(lambda e,a: (_ for _ in ()).throw(RuntimeError('network blocked')) if e.startswith('socket.') else None);import pytest;raise SystemExit(pytest.main(['-q',FILES]))"
```

The stored NPK body passed the actual application byte/media/normalization path
using a local response fixture; no network operation occurred. Its body hash
and normalized text selection matched the baseline. The bound-description
check then verified the quote, source URL, issuer CIK, date, content hash and
original offsets. This proves the offline processing change for those saved
bytes; a future end-to-end run and broader unseen-company evaluation remain
separate requirements.
