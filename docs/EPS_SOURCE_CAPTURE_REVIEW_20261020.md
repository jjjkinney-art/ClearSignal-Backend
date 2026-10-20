# Separate ASML/NPK EPS source-adequacy capture proposal

Base: PR313 merge `0dacb490b40e22046060d8cc04dc2d0ec17e9479`.

**Implemented and validated offline, not executed live.** This document is an
exact-scope code review, not a single-run approval package. Actual executor,
proxy/CA, credentials, source/commit bindings and fresh output/ledger have not
been validated for execution in this session. All eleven prior live approvals
remain consumed. No approval file or real execution output/ledger was created.

## Why these two captures

PR312/313 provide explicit basic/diluted and USD/EUR annual scenario paths. We
still lack retained Company Facts EPS data establishing current ASML and NPK
candidate adequacy. Repeating the six-question pilot cannot close that source
uncertainty by itself. ACHC already has a retained facts body and needs no new
request for this diagnostic step.

Use a new, separately reviewed capture purpose, never the earlier source-capture
or pilot approval:

| Frozen issuer | Exact URL | Route and stage | GET slots | Body envelope |
| --- | --- | --- | --- | --- |
| ASML, CIK 0000937966 | `https://data.sec.gov/api/xbrl/companyfacts/CIK0000937966.json` | `sec/facts`, `evidence.sec_metrics` | 1 | 16,777,216 bytes |
| NPK, CIK 0000080172 | `https://data.sec.gov/api/xbrl/companyfacts/CIK0000080172.json` | `sec/facts`, `evidence.sec_metrics` | 1 | 16,777,216 bytes |

The CIKs match the frozen version-2 development registry, not a newly verified
current ticker directory. Neither is a reserved holdout. Existing core-thesis
case IDs provide ledger slot identity only; no question or endpoint is executed.
The report states **zero completed questions**, zero model attempts/tokens,
not-admitted diagnostics and no application activation.

## Fixed limits and authority

- Two SEC GETs total, one nontransferable slot per exact source; zero directory,
  submissions, document or model slots. No FMP, NewsAPI, FRED, quote or split calls.
- Retain the existing transport/credential/reflection rules, 64 KiB bounded wire
  reads, strict Content-Length handling, observed-byte enforcement, identity
  encoding and HTTP 200/JSON requirements. No redirect, retry, alternate URL or
  larger response exception is introduced.
- Stage supervision remains 20 seconds per source, cleanup drain three seconds
  and whole-run/launcher bound 480 seconds. One worker processes sources in order.
  Analysis is within stage supervision. No deadline or rate increase.
- Each source has a fixed 16 MiB body envelope. Maximum retained raw bodies total
  32 MiB, plus receipts/diagnostics/ledger; this is not a process-memory/RSS cap.
- Preparation writes only a pending manifest. Execution, spending and public-body
  retention each require separate affirmative single-run approval matching the
  manifest, code, configuration, date and canonical fresh output path.
- US$0.52 remains a ledger allowance, **not an invoice ceiling** or authority
  created by this proposal. Actual invoice charges remain unverified.
- Existing output is refused before runtime credential reads; output creation is
  exclusive. No retry/resume/reset or old ledger/output reuse. Approval of one
  source/date/configuration/output cannot transfer to another.

`validation/eps_source_capture.py` and its isolated worker are separate from the
old fixed capture modules. The ledger recognizes one additional explicit purpose
and reconstructs its complete expected policy before accepting it. There is no
generic caller-supplied source/limit selector. Existing old-capture, offline,
source-monitoring and freshness policy/manifest digests match the clean baseline
under identical invented test bindings. Real source hashes necessarily change;
no consumed approval becomes reusable. The full historical run inventories were not
revalidated or recreated in this checkout; only the retained ACHC body and
receipt were checked as described below.

The worker preserves claim-before-dispatch and dispatch-at-most-once, ambient
credential isolation, fixed proxy/CA substitution checks, no Authorization header
on SEC requests, canary screening, durable halt and first-failure retention.
Only the supervisor writes source files or settles claims. Late results cannot
publish or settle; their claims stay unresolved. Parent failure reporting never
overwrites terminal evidence. Raw bodies are retained only after transport and
diagnostic validation succeeds, matching the existing capture discipline.

## What the diagnostics establish

`validation/eps_source_gap_analysis.py` parses supplied bytes offline. It rejects
wrong identity, malformed/duplicate-key/nonfinite JSON and noncanonical dates.
At an explicit nonfuture UTC analysis date it evaluates four exact candidates:
US-GAAP basic/diluted EPS, each in USD/shares or EUR/shares. It records parsed and
annual/as-of record counts, comparable-period selection and exact
period/accession/form/value metadata. Candidate qualification checks the latest
annual Assets period and same-filing reporting-currency/form anchor.

A missing candidate remains a diagnostic gap. Basic is never promoted into
diluted, a translation is not selected as reporting currency, and IFRS/other
units are not inferred. A qualified candidate is not an admitted application
answer: current issuer mapping, reference admission, security/share/split/price
compatibility, actual user assumptions and independent adjudication remain
separate. Qualification is at the manifest's fixed analysis date; it is not a
claim of current identity or data if execution occurs later.

Capture completion establishes receipt/body integrity and candidate diagnostics,
not primary-source authenticity independently verified, useful answers, valuation
authority or launch readiness. It may complete with no usable EPS candidates.
That is a result to review, not permission to retry, change URLs or loosen gates.

## Offline evidence

The synthetic suite exercises real owned HTTPX/httpcore and the isolated worker
with invented in-memory network streams, fixed test authority and disposable
ledgers. It covers per-source size boundaries under declared/chunked/absent
lengths, malformed lengths, identity/media/encoding/reflection failures, timeout
after claim, late work, first failure, no redispatch, configuration drift,
scope/date/retention approval mismatch and old/new approval separation. It also
checks current registry non-holdout status and zero non-facts quota transfer.

The retained ACHC body was analyzed without a new request. It reproduces the
distinct annual basic prior EPS 2.79 and diluted prior EPS 2.78; source body and
receipt hashes are unchanged. ACHC is an offline analyzer compatibility input,
not an authorized capture URL. Original results and frozen-profile comparisons
are retained in `EPS_SOURCE_CAPTURE_VERIFICATION_20261020.json`.

All checks use CPython 3.11.9 and pinned dependencies with test-only credentials
and external sockets/DNS/connect blocked. There were **730 passing related
tests**, including **76 new capture/diagnostic cases**, and **18,292 collected
tests with zero errors**. The broader combined run reported no warnings. A final focused rerun passed 216 tests; import smoke registered 136 routes.
Collection emitted an existing Starlette/AnyIO deprecation warning. Full
hosted repository CI and review remain pending.

## Next concrete gates

1. Review this exact diff and required hosted CI, then merge if accepted.
2. In the bounded-pilot executor, prepare a clean exact-commit package with the
   actual validated runtime/dependencies, nonsecret execution configuration,
   proxy/CA identity, credential presence, full source hash, canonical manifest
   hash, analysis date, run ID and fresh absent output/ledger. Preserve and verify
   the actual historical inventories there. Do not use test fixtures as a package.
3. Obtain separate execution/spending/public-body-retention approval for exactly
   that single package. Do not execute during preparation.
4. After the authorized capture, verify body/receipt hashes and replay diagnostics
   offline. Decide from actual candidates whether the application can proceed or
   a specific source gap remains. Do not automatically activate the endpoint.
5. Return to complete-answer/source/usefulness review and the existing development
   benchmark before reserved holdouts and signed-in save/reopen acceptance.

Preparation syntax, after the merge and actual configuration review:

```sh
python -m validation.eps_source_capture --prepare \
  --execution-config /REVIEWED/execution.json \
  --analysis-as-of YYYY-MM-DD \
  --output-dir /FRESH/eps-source-run \
  --manifest /NEW/pending-manifest.json
```

The paths/date above are placeholders, not an executable approval package. No
live command or spending authority is supplied here.

## Reproduction commands

Run from the repository root with the audited CPython 3.11.9 interpreter and
pinned dependencies. The original runs used an external-network-denying audit
wrapper, test-only environment values and disposable pytest directories. These
commands specify the same selections; retain the offline wrapper when repeating.

```sh
python -m pytest -q tests/test_eps_source_capture.py tests/test_eps_source_gap_analysis.py \
  tests/test_source_capture.py tests/test_capture_budget.py tests/test_pilot_policy_ledger.py

python -m pytest -q tests/test_eps_source_capture.py tests/test_eps_source_gap_analysis.py \
  tests/test_source_capture.py tests/test_capture_budget.py tests/test_pilot_policy_ledger.py \
  tests/test_pilot_approved.py tests/test_pilot_live.py tests/test_pilot_preflight.py \
  tests/test_pilot_rehearsal.py tests/test_pilot_netrc_isolation.py \
  tests/test_pilot_sec_document_selection.py tests/test_pilot_sec_halt_diagnosis.py \
  tests/test_sec_document_envelope.py tests/test_source_monitoring_pilot.py \
  tests/test_monitoring_freshness_pilot.py tests/test_eur_annual_eps_scenarios.py \
  tests/test_basic_eps_scenarios.py tests/test_conditional_valuation_api.py \
  tests/test_conditional_valuation_account_boundary.py

python -m pytest --collect-only -q
```

The combined ASGI test wrapper permits local AF_UNIX socket construction required
by the test runtime; external socket, DNS and connect activity is denied. The
isolated capture-worker scenarios additionally use their own synthetic wire and
network guard. No real provider credential values are used by these tests.
