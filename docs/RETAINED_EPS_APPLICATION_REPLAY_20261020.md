# ASML/NPK retained EPS application replay

Base: PR314 merge `32584e354a6764e9db4015c32c41fe40c89b86fa`.
Analysis date: 2026-10-20 UTC. Offline only; no product code or production
configuration change, provider dispatch, new live authority or endpoint activation.
All twelve previous live approvals, including PR314's capture, remain consumed.

## Result

Real retained Company Facts bytes pass through the existing provider's response
JSON/parser, comparable SEC fact producer, reporting-period/form/currency anchor,
`admit_evidence`, source reconstruction and actual ASGI scenario handler.
The application implementation required no correction for these cases.

| Source and explicit basis | Current/prior annual EPS | Growth evaluation | Required-growth solution |
| --- | --- | --- | --- |
| ASML EUR basic | 24.73 / 19.25 | available, partial | available, partial |
| ASML EUR diluted | 24.71 / 19.24 | available, partial | available, partial |
| NPK USD basic | 4.63 / 5.82 | available, partial | available, partial |

ASML references retain the 20-F filed 2026-02-25; NPK retains the 10-K filed
2026-03-13. Both use annual 2025 versus 2024 comparisons. Reference IDs, literal
currency/unit/basis, dates and source URLs were checked. Each available answer
remains `admitted=false`, `launch_ready=false` and explicitly hypothetical.
The internal evidence-reference admission is an offline reconstruction, not a
retroactive promotion of capture diagnostics or independent factual adjudication.

The three positive-EPS sources correctly fail the loss/recovery mode's
nonpositive historical EPS requirement. NPK diluted USD fails the latest annual
period gate instead of substituting its 2012 comparison or basic EPS. ASML USD
and NPK EUR remain explicit missing-currency gaps. Feature-off returns 404 and
anonymous access returns 401, both before provider replay. Cache-Control is
no-store on available responses; supplied assumptions remain unchanged.

Fourteen checks passed: six available scenario responses, three positive-EPS
recovery rejections, three source gaps and two feature/auth boundary checks.
There were twelve saved provider-response substitutions, zero external requests,
zero model calls, and no additional use of a live approval.

## Reproduction and arithmetic

`scripts/replay_retained_eps_scenarios.py` requires the original PR314 results
ZIP as input and an absent destination JSON path. It checks all 19 archive hashes
and the two fixed body hashes/lengths against their receipts. It never downloads
sources. External socket/DNS/connect events are denied; local AF_UNIX construction
is permitted for the ASGI runtime. The script uses invented test credentials,
injects a frozen directory and UTC clock, and joins its own AnyIO workers within
five seconds. It restores process-only feature/source patches; the audit guard
remains installed until this dedicated process exits.

```sh
# From this repository, use audited CPython 3.11.9 and pinned dependencies.
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
  SEC_USER_AGENT='Test contact@example.invalid' \
  /PATH/TO/PINNED/python -I -B scripts/replay_retained_eps_scenarios.py \
  /PATH/TO/PR314-results.zip /NEW/replay.json
```

Assumptions are invented demonstrations: price 100 in the requested reporting
currency per underlying common share, exit multiple 20x and horizon two years.
The evaluation uses assumed zero EPS growth; its terminal price factor reproduces
reported EPS × 20 / 100. The required-growth mode assumes zero annual price return;
its growth solution reproduces sqrt(100 / (20 × EPS)) − 1 to 1e-25 tolerance.
No observed quote, FX/ADR conversion or future performance prediction is supplied.
These examples do not authorize user assumptions or establish share/split/class
compatibility. Each source's positive EPS keeps loss/recovery unavailable.

`ASML_NPK_RETAINED_EPS_APPLICATION_REPLAY_20261020.json` retains all responses,
source replay counts, original hashes and explicit limitations. The CLI replay
reproduced that saved report; no raw provider bodies or historical ledgers are
copied into this repository. Related existing EUR/basic/scenario API/account
regressions passed **188 tests** on CPython 3.11.9 with the offline network guard:

```sh
python -m pytest -q tests/test_eur_annual_eps_scenarios.py \
  tests/test_basic_eps_scenarios.py tests/test_conditional_valuation_api.py \
  tests/test_conditional_valuation_account_boundary.py
```

Original result: `188 passed in 13.18s`. Hosted CI for this evidence-only change
remains pending. Full historical inventories were not independently revalidated
here; the captured results archive reports their preservation in its executor.

## What remains

This closes retained-source-to-explicit-scenario replay for these exact paths.
It does not test the normal /ask answer composition, real authenticated sessions,
current directory identity, user personalization, saved/reopened research,
security/share/split/price compatibility, or complete investment-thesis usefulness.
No global launch percentage or launch-ready claim follows from these six results.

Next, review the existing core-thesis and decision-threshold answer composition
and define the finite application integration acceptance cases using these
retained sources. Keep the explicit scenario endpoint disabled until its own
product acceptance and activation decision. Complete the development benchmark
and independent answer-quality review before the frozen holdout gate.
