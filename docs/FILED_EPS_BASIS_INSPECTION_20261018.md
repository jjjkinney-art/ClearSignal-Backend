# Filed EPS basis inspection — 18 October 2026 Auckland

Base: `3e1813522e3a53227c759a6cf55249e5230892e2` (merged/deployed PR306).

## Result and purpose

The offline inspector binds explicit per-share facts and EPS accounting-policy
text to one retained annual filing. It keeps basic and diluted EPS separate and
never turns a financial-period end into an already-adjusted split cutoff.
There are no production imports, provider requests, settings changes, quote
calculations or evidence-admission changes.

The already retained NPK body contains 2025 basic EPS of **4.63 USD/share**,
2024 basic EPS of **5.82 USD/share**, and 2023 basic EPS of **4.86 USD/share**.
It has two equivalent 2025 facts, two equivalent 2024 facts and one 2023 fact.
Their IDs and periods remain separate in the replay. No explicit standard
numeric diluted-EPS fact qualified. A nearby display heading describing
“basic and diluted” cannot authorize silently relabeling those basic facts.
This is source consistency, not an independent adjudication of the issuer's
reported figures, EPS class allocation or current market valuation.

The EPS policy says basic EPS includes common shares and participating
securities, and discusses potential common shares for diluted EPS. The saved
report retains its whitespace-normalized display text and exact source fact,
context and namespace identifiers. This is not a canonical XBRL text-block
value, a conclusion about economic rights, or proof of basic/diluted equality.
The original body remains available separately for source inspection.

## Conservative contract

`validation.filing_eps_basis.inspect_filing_eps_basis` first reuses the existing
PR305 raw-body/receipt, CIK, symbol, form, reporting-period and cover-class checks.
Supported forms are 10-K and 10-K/A only, within the unchanged 15,000,000-byte
application envelope. Other forms, encodings and unsupported cover declarations
remain gaps rather than inferred identities. A supplied matching receipt proves
byte consistency, not independently authenticated source origin.

A local subclass of the bounded Inline XBRL target supports only explicit
`iso4217:USD / xbrli:shares` divided units, with resolved namespaces and the exact
numerator/denominator structure. A unit ID containing “USDPerShare”, a simple
USD monetary unit, reversed division, foreign currency or spoofed namespace
cannot qualify. The production monetary parser and producer admission validators
are unchanged; this new helper does not widen their accepted unit types.

Only standard GAAP EarningsPerShareBasic and EarningsPerShareDiluted facts are
retained, using unsegmented issuer-bound duration contexts of 300–380 days ending
no later than the supplied filing period. Prior annual facts are preserved but
do not fill current-period coverage. Different current values or start dates
produce explicit conflicting coverage with no selected value. Equivalent
facts retain every fact ID, rather than counting as independent confirmations.
A missing observation is not proof the issuer omitted the metric.

Supported dot-decimal literals, properly grouped supported transformations,
explicit sign and scale are evaluated with Decimal precision 100, independently
of ambient precision. Zero and negative EPS remain observations; no positive-EPS
valuation assumption is imposed. The absolute 1,000,000 EPS and scale −9…9 bounds
are computational limits, not investment policies. Fact literals, transforms,
scale, decimals, unit/context IDs, issuer scheme, period and filing metadata are
retained. Unsupported continuation, exclusion, tuple, target, nil, precision,
escape and transformation cases are not treated as independent literal facts.

Policy display extraction supports one context-bound standard GAAP text block
at a time, at most 32 blocks and 8,192 characters per block, under the existing
XML depth/resource/namespace/identifier limits. Block separators and whitespace
are normalized; ix:exclude text is omitted. Overlong policies are discarded
rather than truncated into apparent complete quotations. A policy-count/nesting
limit rejects the inspection. Finding “participating securities” is recorded
as a literal phrase observation; not finding it is unknown, not evidence of
absence. Unsupported facts/policies do not erase independent valid numeric facts.

## Saved-source replay and limits

[Full replay report](NPK_FILED_EPS_BASIS_REPLAY_20261018.json) contains source
bindings, cover declaration, all five numeric facts, current coverage and policy.

- Original body: 1,404,517 bytes.
- Body SHA-256: `8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
- Exact URL: `https://www.sec.gov/Archives/edgar/data/80172/000143774926008214/npk20251231_10k.htm`.
- Supplied metadata: CIK `0000080172`, NPK, 10-K, filed 2026-03-13,
  reporting period ended 2025-12-31.
- The original body and receipt were read before and after replay and matched
  byte for byte. No historical ledger or previous run output was changed or
  recreated. This task did not rehash all historical files or ledgers.

The first replay assertion expected three observations; the source correctly
returned five because equivalent facts appear in more than one statement/note.
The final assertion checks the three unique period/value pairs while preserving
all five fact IDs. This changed the replay assertion, not the source or parser.

Reproduce on an executor holding the previously authorized retained capture,
using the pinned socket-denying environment below, with `sys.path[:0]=['.','tests']`:

```python
import hashlib, json
from pathlib import Path
from validation.filing_eps_basis import inspect_filing_eps_basis
capture = Path('/workspace/scratch/a974112f317d/pr292-results-review/extracted/capture')
p = capture / 'npk-filing.html'
rp = capture / 'npk-filing.html.receipt.json'
body, receipt_bytes = p.read_bytes(), rp.read_bytes()
assert hashlib.sha256(body).hexdigest() == '8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1'
report = inspect_filing_eps_basis(body, json.loads(receipt_bytes),
    expected_cik='0000080172', expected_symbol='NPK', form='10-K',
    filed_at='2026-03-13', reporting_period_end='2025-12-31')
assert report['inspected']
assert report['reporting_period_coverage'][0]['value'] == '4.63'
assert report['reporting_period_coverage'][1]['status'] == 'not_observed'
assert {(r['start'], r['end'], r['value']) for r in report['observations']} == {
    ('2023-01-01', '2023-12-31', '4.86'),
    ('2024-01-01', '2024-12-31', '5.82'),
    ('2025-01-01', '2025-12-31', '4.63')}
assert report['eps_policy_display_text'][0]['participating_securities_mentioned'] is True
assert body == p.read_bytes() and receipt_bytes == rp.read_bytes()
```

`already_adjusted_through` remains null. Split basis, EPS class compatibility,
quote unit, independent adjudication, product admission and launch readiness all
remain false. Basic EPS is not fed into the existing diluted-EPS scenario bridge.
No price, P/E or buy/sell threshold is derived. Next source work must establish
the relevant EPS class/basis and corporate-action interval; market quote admission
and independent useful-answer acceptance are separate remaining gates.

## Validation

Pinned CPython 3.11.9, audited dependency environment, invented fixtures and a
socket-denying audit hook; no provider or model API calls. Final related suite:
**1,014 passed**, including **63 new cases**, with no warnings. Separate existing
synthetic pilot suite: **36 passed**, no warnings. Total **1,050 regressions**;
the earlier 135-test subset is not additional coverage. Import smoke passed with
135 routes. Single-process collection completed with 17,928 tests and zero
collection errors; it reported the existing Starlette/AnyIO deprecation warning.
An initial new assertion expected an empty observation list when
malformed date metadata correctly caused the existing cover validator to reject
the entire filing; it was corrected to accept rejection, without loosening code.

Exact related-suite command (substitute the pinned interpreter path only):

```bash
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
SEC_USER_AGENT='Test contact@example.invalid' /path/to/pinned/python -I -B - <<'PY'
import sys, socket
sys.path[:0] = ['.', 'tests']
socket.has_ipv6 = False
sys.addaudithook(lambda e,a: (_ for _ in ()).throw(RuntimeError('network blocked'))
                if e.startswith('socket.') else None)
import pytest
raise SystemExit(pytest.main(['-q',
    'tests/test_filing_eps_basis.py', 'tests/test_split_event_reconciliation.py',
    'tests/test_filing_share_class.py', 'tests/test_quote_eps_binding.py',
    'tests/test_fmp_quote_capture.py', 'tests/test_dated_price_capture.py',
    'tests/test_source_anchored_valuation.py', 'tests/test_valuation_scenario_checker.py',
    'tests/test_fmp_profile_price_boundary.py', 'tests/test_fmp_provider.py',
    'tests/test_valuation_numeric_inputs.py', 'tests/test_valuation_period_labels.py',
    'tests/test_source_answer.py', 'tests/test_evidence_references.py',
    'tests/test_threshold_evidence_admission.py', 'tests/test_valuation_consistency.py',
    'tests/test_provider_secret_diagnostics.py', 'tests/test_public_document_ingestion.py',
    'tests/test_sec_inline_memory.py']))
PY
```

Run `tests/test_monitoring_freshness_pilot.py` and
`tests/test_source_monitoring_pilot.py` separately with that same wrapper.
For import smoke replace the pytest invocation with
`from app.main import app; print(len(app.routes))`.

Hosted CI and independent review remain pending. No transport, timeout, quota,
claim, halt, fencing, credential/proxy/CA, source-only pilot scope or retention
policy was changed. Production monitoring activation remains off, frozen
FMP/NewsAPI/FRED exclusions remain in place, and all eleven live approvals remain
consumed. No new live execution or spending authority was created. The earlier
PR301 combined-suite thread warning is not claimed diagnosed or repaired.
