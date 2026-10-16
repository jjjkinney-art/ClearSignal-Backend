# Risk-to-financial monitoring links — 16 October 2026 Auckland

Base: `959c3bfa79cd18ecddfba5c9e5774e658a986916` (merged/deployed PR297).

## Problem and bounded behavior

The broad financial foundation presents reconstructed financial trends and
source-bound risks in separate sections. An explicit issuer disclosure that a
condition could harm revenue or operating income does not identify the relevant
admitted comparisons as a conditional research question. Improving reported
amounts alone also do not resolve the disclosed future risk.

The new composer links a current, final-bound risk-monitoring inference to
surviving core financial comparisons only when the disclosure's entire potential
effect is an explicit issuer-owned list of named financial families. Examples
include `our revenue and operating income` and `our financial condition and
operating cash flow`. Generic financial-condition/operating-results wording does
not supply a metric. Neither does a financial word in the risk's condition.

Every link preserves the admitted risk ID and financial IDs, the filing date and
each comparison's current/prior start and end dates. It asks whether the named
condition occurs and whether future like-for-like comparisons deteriorate. It
does not say the risk occurred, caused reported changes, has been resolved, is
material or likely, or has a quantified earnings effect. Different reporting
durations remain separate; filing and financial dates do not establish a common
observation period. Links are explicitly marked inference, not additional facts.

Matching is at financial-family level, not proof of identical definitions. The
actual bound concept label remains visible (for example, revenue from contracts
with customers excluding assessed taxes, or net income attributable to parent).
`measure_equivalence_established` stays false and the answer states this limit.
Generic revenue cannot stand in for revenue net of interest expense. For that
reporting context, operating cash flow remains context only and cannot become a
performance breakpoint through the new links. Pretax income never replaces a
missing operating-income comparison.

Third-party/customer measures, adjusted/segment measures, negations, unresolved
qualifiers and historical predecessor risks do not produce these links. The
strict effect-list parser deliberately misses many legitimate formulations.
Their already qualified risk context remains available; no rejected description
or failed metric is admitted by the linker. No new issuer-specific rule, source,
disclosure-selection rule or risk-inference grammar is introduced.

## Existing pilot evidence and limitations

The six retained PR295 answers were inspected read-only from artifact SHA-256
`8981da9b668f51735423b58de8d4878315f6cef2271a42899687cd52fef2b6cd`.
Their six core-thesis risk excerpts describe supplier co-development, patent
expiry, staffing costs/profitability, covenant default, production failure and
procurement requirements. None supplies the existing risk-inference parser's
simple explicit named-measure effect list. The archived answers also contain no
`risk_monitoring_inference` rows. This increment therefore does **not** establish
that those six answers improve, or repair all disclosed-risk coverage. No archived
answer is edited, relabeled, or counted as a new useful-answer pass.

Support for more complex source-explicit operating mechanisms and independent
question/usefulness review remains necessary. Generalizing costs/profitability
to a particular income measure, or a risk-topic label to an unspoken financial
effect, would require more evidence; this change does neither. Competitive
strength, full business economics, valuation boundaries and risk materiality
remain open. The 100-company development/holdout plan is unchanged.

## Validation

CPython 3.11.9 and the existing audited dependencies were used. Tests had invented
credentials, no real credential-file reads and socket operations denied. The
source-answer test stubs issuer identity explicitly; an initial version omitted
that stub and its attempted lookup was blocked. Two initial expected labels were
also corrected to the existing parent-attributable net-income label. The final
code preserves those semantics rather than broadening them to satisfy a test.

- 500 tests passed in the new link suite and the existing foundation, disclosure,
  business coverage, source answer, margin, competition, diagnostic, reference
  and product-distribution suites. The new suite contains 28 cases.
- 36 existing monitoring-freshness/source-monitoring pilot tests passed, including
  isolated synthetic workers and the existing quota, claim and deadline gates.
- Import smoke passed with 135 routes. No live SEC or model requests occurred.

Reproduction of the related suite (from the repository root, using the audited
interpreter in place of `PINNED_PYTHON`):

```bash
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
  SEC_USER_AGENT='Test contact@example.invalid' PINNED_PYTHON -I -B - <<'PY'
import sys, socket
sys.path[:0] = ['.', 'tests']
socket.has_ipv6 = False
sys.addaudithook(lambda event, args: (_ for _ in ()).throw(RuntimeError('network blocked'))
                if event.startswith('socket.') else None)
import pytest
raise SystemExit(pytest.main(['-q',
    'tests/test_risk_financial_monitoring.py',
    'tests/test_financial_thesis_foundation.py', 'tests/test_thesis_disclosures.py',
    'tests/test_business_context_coverage.py', 'tests/test_source_answer.py',
    'tests/test_operating_margin_assessment.py', 'tests/test_thesis_competition.py',
    'tests/test_thesis_gap_diagnostics.py', 'tests/test_evidence_references.py',
    'tests/test_product_distribution_business.py']))
PY
```

For the synthetic pilot suite use the same wrapper with
`tests/test_monitoring_freshness_pilot.py` and
`tests/test_source_monitoring_pilot.py`. Import smoke uses the same isolated
wrapper with `sys.path.insert(0, '.')`, then imports `app.main.app` and reports
`len(app.routes)`. Required hosted CI and independent review remain pending.

Production flags, transport, document/hash admission, risk quote limits, physical
requests, quotas, stage deadlines, claim/dispatch fencing and all eleven consumed
approvals are unchanged. No ledger is resumed or reset, no new authority/package
is created, and no historical live record is modified. This is offline shared
composition work, not launch acceptance or permission for a new pilot.
