# Disclosed operating mechanisms — 16 October 2026 Auckland

Base: `2e27ac9b408f6754ef3d47e2a5fd9bc2752a4248` (merged/deployed PR298).

## Demonstrated gap and resulting behavior

The existing risk-monitoring parser supports a simple condition that `could/may
adversely affect` a stated effect. PR295's saved ACHC staffing and NPK procurement
excerpts instead explicitly describe higher costs and reduced profitability.
Those disclosures were admitted, but their operating mechanism did not become a
conditional research test. PR298 deliberately did not generalize that wording to
an unstated financial measure.

This increment recognizes a separate, bounded source-explicit pattern: a
condition `may/could/can` increase issuer-owned costs and reduce profitability.
It supports a direct clause and a relative `that` clause, an explicit optional
significance modifier, and generic or named labor/operating/production/compliance/
material/procurement costs. It preserves the entire original quote, modal,
condition, effect, filing date and admitted response reference. No possibility is
rewritten as an event that occurred or a forecast.

Only a risk that has already survived final issuer/document/quote binding,
response-reference checks, de-duplication and the existing two-risk cap reaches
the composer. The condition must name its existing bound topic. Nested modals,
negation, unresolved generic subjects, third-party costs/profitability, adjusted
or segment qualifiers and historical predecessor risks produce no new inference.
This is a new composition grammar, **not** broader evidence admission or a new
disclosure selector. It does not cover every operating mechanism.

Surviving reconstructed operating-income and net-income comparisons may appear
alongside the mechanism as `profitability_context_only`. Their actual concept
labels and current/prior periods remain explicit. Generic profitability never
creates operating income, a margin or an earnings-impact calculation. Pretax
income, cash flow and revenue cannot substitute for missing income context.
Without verified income context, the source-explicit mechanism is still shown,
and the absence is stated. References missing from the response cannot be used.

The research test asks for evidence of the operating condition and cost movements
and then future like-for-like profitability. Improving results cannot establish
that the risk is resolved. The composer does not establish occurrence, common
periods, identical definitions, causal attribution, magnitude, likelihood or
materiality. These inference flags stay false, source claims stay separate, and
the partial/unscored answer retains its existing unanswered requirements.

## Saved NPK development replay

[Replay summary](operating_risk_npk_replay_20261016.json) records the exposed
PR292 body and PR295 saved financial facts. Exact inputs:

- NPK retained HTML: 1,404,517 bytes, SHA-256
  `8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
- PR295 artifact SHA-256:
  `8981da9b668f51735423b58de8d4878315f6cef2271a42899687cd52fef2b6cd`.
- Filing: `npk20251231_10k.htm`, CIK 80172, filed 2026-03-13, exact accession URL
  recorded in the summary. No new body was fetched or retained.

`validation/replay_operating_mechanisms.py` refuses different input hashes and
creates output exclusively. It denies socket operations before application
imports, feeds the existing bytes through the actual bounded document reader
and HTML normalizer using one local `requests.Response` fixture, and supplies
invented public DNS/issuer-directory fixtures. It executes the actual thesis
disclosure selection, risk binder, financial-comparison reconstruction, final
evidence admission and foundation composer. Exact source span reproduction is
asserted. Two separate wrong-body/wrong-artifact checks refused the input before
application import and left output absent.

The retained procurement/cybersecurity quote now produces one operating-risk
monitoring inference. Its operating-income and parent-attributable net-income
context cover 2026-04-06 to 2026-07-05 against 2025-03-31 to 2025-06-29. These
periods are not harmonized with the annual disclosure. The replay's E7/E2/E3 IDs
belong to its newly admitted response, not the historical pilot. Source claims
and unanswered parts match a control composition with only the new mechanism
helper disabled. This isolates the new section; it is not a second live run or
an independently adjudicated quality score.

The ACHC wording is exercised in an authored source fixture carrying that exact
owner-provided excerpt. Its real annual body was not available here, so this is
not an independent replay of ACHC's complete real filing. ASML co-development
and patent-expiry wording and NPK production-failure wording remain outside this
grammar. No full six-case improvement, broad-company success rate, or resolved
launch blocker is claimed. The inputs are exposed development material, never
reserved holdout evidence.

Offline reproduction (replace paths and `PINNED_PYTHON` with the audited local
CPython 3.11.9 interpreter; output must be fresh):

```bash
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
  SEC_USER_AGENT='Test contact@example.invalid' PINNED_PYTHON -I -B \
  validation/replay_operating_mechanisms.py \
  --body /path/to/retained/npk-filing.html \
  --artifact /path/to/retained/pr295/artifact.json \
  --output /new/path/operating-risk-replay.json
```

The replay has no download, execute-pilot or approval-creation option. Its fixed
input identity is a diagnostic development fixture, not a product ticker rule.

## Validation and remaining gates

567 tests passed offline on CPython 3.11.9 with audited dependencies, invented
credentials and a socket-denying audit hook:

- 531 related tests: 31 new operating-mechanism cases plus 500 existing risk-link,
  foundation, disclosure, business coverage, source answer, margin, competition,
  diagnostic, reference and product-channel regressions.
- 36 existing source-monitoring/freshness pilot tests, including isolated
  synthetic workers and unchanged quota/claim/deadline checks.
- Import smoke: 135 routes. No initial/final test failures in this increment.

Use the isolated wrapper documented in
[PR298's reproduction instructions](RISK_FINANCIAL_MONITORING_LINKS_20261016.md),
adding `tests/test_operating_risk_mechanisms.py` to its related-file list. The
same wrapper with `tests/test_monitoring_freshness_pilot.py` and
`tests/test_source_monitoring_pilot.py` reproduces the synthetic suite.

Hosted CI and independent review remain required. Full business/competitive
assessment, valuation boundaries, risk materiality, the existing 100-company
development/reserved-holdout plan, independent usefulness/factual adjudication
and signed-in personalization remain open. No production flag, source quota,
transport, byte/hash admission, stage deadline, claim fence or approval changes.
All eleven live approvals remain consumed; no ledger or historical run was
modified. This work creates no authority for another live pilot.
