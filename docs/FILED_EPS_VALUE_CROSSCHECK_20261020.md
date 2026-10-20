# Filed EPS value cross-check — 20 October 2026 Auckland

Base: `0ddffda9b554e1089dfa260211f88449e3ef3195` (merged/deployed PR307).
Base tree: `12c366dd366abbb397f44b427d1d33ae20c7d399`.

## Demonstrated metadata-only acceptance and correction

The offline `assess_filed_share_basis` previously reconstructed source EPS and
matched a filing's accession directory, form, filing date, reporting-period end
and common-share declaration. It did not compare the EPS amount with the filing's
own numeric facts. An invented filing with diluted EPS **999** passed against a
reconstructed producer value **5** when those metadata fields agreed.

That exact contradiction was reproduced offline on the checked PR307 tree.
This demonstrates that metadata-only success was narrower than numerical
corroboration. It does not show that a live answer contained wrong EPS or identify
the cause of any earlier pilot failure. Production does not call this offline
helper. No actual NPK amount or source body was changed for reproduction.

The updated helper adds the missing check to the existing binding path, rather
than introducing another alternative passing report. After the existing
quote/profile/source-EPS and filing checks, it reruns PR307's bounded raw-filing
EPS inspection and requires:

1. An explicit standard numeric diluted-EPS observation for the filing period.
2. Unambiguous current coverage: equal duplicate values and periods are allowed
   with every fact ID retained; conflicting values or annual starts are refused.
3. Exact calendar start/end and Decimal-value agreement with the reconstructed
   current source EPS. No float tolerance, rounded comparison or string-equality
   substitution is used. `5.00` and `5` agree; a smaller numeric difference does
   not disappear under a low ambient Decimal precision.

USD/shares units, issuer contexts, annual duration, namespaces, supported numeric
transforms and raw receipt/hash binding are revalidated by the existing inspector.
A basic-EPS fact equal to the requested diluted value still does not qualify;
a “basic and diluted” heading or policy cannot promote it. Monetary USD units,
foreign currency, quarterly/prior/future-only contexts and unsupported facts leave
gaps. An inspector resource-limit failure does not grant an implicit match.

Success adds `filed_eps_value_consistent` and `filed_eps_crosscheck`, retaining the
producer response reference, exact concept/value/unit/period, raw filing binding,
literal observations and all matching fact IDs. Failure returns only the existing
sanitized gap shape with a fixed stage code, including
`filed_diluted_eps_not_observed`, `filed_diluted_eps_conflicting`,
`filed_eps_value_or_period` or `filed_eps_inspection`. No caller-supplied passing
report, extra assertion or split report is accepted instead of raw inputs.

## Deliberate contract tightening and remaining gates

The helper's success condition is stricter: a cover-only document that previously
passed now returns `filed_diluted_eps_not_observed`. Existing positive integration
fixtures now contain matching invented diluted-EPS facts. The cover extractor's
own tests and acceptance contract are unchanged. Existing rejection tests still
exercise their intended earlier gates; none was changed into a permissive result.

Exact filed agreement is source consistency, not independent source authenticity,
accuracy, common-share rights or current quote compatibility. Even fabricated
matching sources can pass consistency; a regression test retains all independent
verification/admission flags as false in that case. The prior-year comparison is
still reconstructed by the existing producer contract, but is **not independently
cross-checked against this filing**. No broader comparison audit is claimed.

Current listing, price unit, class-specific EPS rights, complete corporate-action
interval, split basis, quote-session admission and independent useful-answer
acceptance remain open. No price/EPS ratio, current market P/E, expected return or
buy/sell threshold is computed. Source-EPS producer admission, the basic/diluted
concept distinction and the conditional scenario bridge are not widened.

## Retained NPK replay

Rerunning PR307's inspector on the previously retained NPK body exactly reproduced
[its existing report](NPK_FILED_EPS_BASIS_REPLAY_20261018.json), including five
basic-EPS facts, current value 4.63, no qualifying diluted-EPS numeric fact and the
participating-securities policy. The original body and receipt matched byte for
byte before/after; the fixed body hash remained
`8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
No split cutoff or complete later corporate-action interval is established.

A full real NPK quote/profile/structured-EPS cross-check was **not** executed:
those complete bound inputs are not retained here. Synthetic agreement must not
be presented as real market validation. This task did not rehash all historical
files or ledgers, consume another approval or recreate historical output.

## Validation and reproduction

Pinned CPython 3.11.9 and the existing audited dependency environment; tests,
baseline reproduction and retained-source replay deny socket operations and use
no real credentials. The interpreter target was initially absent; the failed test
launch executed no tests. `uv python install 3.11.9` restored the runtime in a
separate download before the socket-denied checks. No dependency changes.

- **1,042 related regressions passed**, including **28 new tests**, no warnings.
- **36 existing synthetic pilot tests passed**, no warnings.
- Total **1,078 regressions**; the earlier 226-test subset is not additional coverage.
- Import smoke: **135 routes**. Single-process collection: **17,956 tests**,
  zero collection errors; existing Starlette/AnyIO deprecation warning recorded.
- Retained NPK inspection exactly matches the PR307 report; original bytes unchanged.
- Hosted full regression and independent review remain pending.

Use the exact socket-denying wrapper and related file list from
[PR307's review](FILED_EPS_BASIS_INSPECTION_20261018.md), prepending
`tests/test_filed_eps_crosscheck.py`. Run the same two synthetic pilot files
separately with that wrapper. The new tests cover literal value/period agreement,
equivalent and conflicting duplicates, basic-only/headings, unit/transform limits,
source/reference tampering, exact decimal comparison, policy resource failure,
returned-object isolation and unchanged false market/admission flags.

To reproduce the old metadata-only acceptance with that wrapper in the exact base tree:

```python
from test_filing_share_class import combined, args
from test_filing_eps_basis import document, fact
r = combined(args(document(fact('Diluted', '999'))))
assert r['binding_passed']
assert r['quote_profile_eps']['source_eps']['value'] == '5'
```

On the changed tree, the same raw fixture produces
`binding_passed=False`, stage `filed_eps_value_or_period`; the new regression test
also verifies that no partial source report or ratio escapes the failure result.
The old tree's staged tree was checked against the exact base tree above before
running the reproduction. All reproduction values are invented.

No production import, setting, live request, provider permission, transport,
deadline, quota, claim, halt, fencing, credential/proxy/CA safeguard, retention
policy or holdout output was changed. Production monitoring activation remains
off. Frozen FMP/NewsAPI/FRED exclusions remain unchanged; all eleven live
approvals are consumed. There is no new execution or spending authority.
