# Six-case pilot: transport and credential readiness

Static audit based on main `98e4663f6e27e776bc0294e29a2f1cbb791624db` and the inspected local dependency versions: OpenAI 2.32.0, HTTPX 0.28.1,
httpcore 1.0.9, urllib3 2.8.0 and requests 2.32.5. Top-level requirements pin
OpenAI/HTTPX/requests; httpcore/urllib3 are resolved transitive dependencies. No credentials, prices, account entitlements or live
responses were inspected. No capture or paid call was executed. These findings
are not a USD ceiling or authorization to run the pilot.

## Diagnostic boundary

PR269 removed key prefixes and raw provider errors inside the four provider
clients. Remaining reachable sinks were `structured_output` retries, investment
agent fallback handlers, synthesis retries and investment-router provider/future
handlers. Logs now retain exception class instead of exception text. The five specialist
fallback objects use a fixed failure message, preventing exception details from
entering captured output or the next synthesis prompt even at zero confidence.
Exception propagation, request construction, retry counts and failure confidence
are unchanged.

OpenAI's pinned SDK filters Authorization headers in one request-options log,
but that does not protect arbitrary error bodies, URLs, response headers or
exception tracebacks. `OPENAI_LOG=debug` and ordinary Python DEBUG configuration
can expose these through `openai._base_client`, HTTPX/httpcore and urllib3.
`app/provider_diagnostics.py` suppresses records at the exact transport emitters
used by these inspected synchronous paths, before handlers can format them. This
intentionally removes low-level transport diagnostics at all levels, including
warnings. Application status, timing, usage and error-class events remain.
The guard is installed before OpenAI client creation and legacy FMP transport use;
raising logger verbosity cannot bypass it. It does not read secret values.

Tests use the real OpenAI SDK with HTTPX MockTransport (including automatic
retries), urllib3 with a fake connection, and httpcore Trace events. They check
synthetic Bearer headers, credential-bearing URLs, echoed error bodies/response
headers, fallback handlers and unrelated application-log preservation.

This is not a global secret scrubber. SDK or transitive dependency upgrades and alternate emitters require
re-audit. Transitive dependency resolution is therefore a remaining execution
preflight/version-verification requirement. It does not cover arbitrary logging handlers that independently inspect
request objects, custom HTTP trace extensions, direct `http.client` wire-debug
prints, subprocess diagnostics, or secrets deliberately included in user/model
content. The application does not enable those wire-debug facilities on the
inspected pilot path; the execution preflight must reject enabling them. The
OpenAI wrapper still propagates the original exception to callers; inspected
pilot catch sites avoid logging its text, but arbitrary new callers are not
certified. No new remote log/configuration controls are enabled here.

## Static dispatch map

Entry: `validation/pipeline_capture.py::_default_runner` calls local
`detect_company`, then `_run_investment_pipeline` directly with side effects
false and no `as_of`. It does not call `/api/ask`, general router agents, legacy
context enrichment or the legacy FMP client. The saved v2 manifest supplies the
six exact questions, not user-entered variations.

Pure routing inspection of all six saved questions produced:

| Cases | Source-evidence mode | Intent | FRED topics/series |
| --- | --- | --- | --- |
| ASML, ACHC, NPK `core_thesis` | true | investment_thesis | none |
| ASML, ACHC, NPK `decision_threshold` | false | investment_thesis | none |

The three core-thesis cases skip model agents and synthesis, **after** their
current-data evidence tasks have been started. They are not necessarily free.

| Dispatch surface | Logical requests per ordinary case, with credentials | Retry/concurrency considerations |
| --- | --- | --- |
| FMP company task (`fmp_provider.fetch_company_evidence`) | Up to 5 sequential GETs: `/api/v3/profile/{ticker}`, `/stock-price-change/{ticker}`, `/income-statement/{ticker}`, `/balance-sheet-statement/{ticker}`, `/historical/earning_calendar/{ticker}` | Uppercase pilot tickers avoid `/api/v3/search`; each `urlopen` has an 8-second timeout, no explicit application retry. |
| FMP valuation task | Up to 2 GETs: `/api/v3/ratios-ttm/{ticker}`, `/key-metrics-ttm/{ticker}` | Runs concurrently with company/estimate tasks; errors do not refund charges. |
| FMP estimate task | Up to 2 GETs: `/api/v3/analyst-estimates/{ticker}`, `/api/v4/price-target-consensus` | Same transport and timeout. |
| NewsAPI company and macro tasks | 2 GETs to `/v2/everything` | Macro task uses a generic market query even with no detected topics. Separate workers; 8-second `urlopen` timeout each. |
| FRED macro task | 0 for these six exact questions | Other questions issue one GET `/fred/series/observations` per unique matched series. Do not reuse this zero count for different questions. |
| SEC/issuer public-source tasks | Data-dependent submissions, facts, filing indexes and document requests | Still need route/redirect accounting and verified incremental-fee treatment; public access is not proof of zero account/platform cost. |
| Five specialist agents | Up to five structured-response call chains for decision-threshold cases; zero for core-thesis source views | Six-worker pool with Q-first. Agents with insufficient relevant evidence may skip model calls. |
| Q-first question answerer | One direct ModelClient call chain per decision-threshold case | Same agent model/output setting, without the outer structured-response retry loop. |
| Synthesis | Up to two router synthesis invocations per decision-threshold case | Normal router plan: 56 seconds then 42 seconds/reduced evidence. Each invocation contains a JSON-enforcement retry loop, then ModelClient's loop, then SDK retries. |

Those FMP/NewsAPI counts total up to **54 and 12 initial logical GETs** across
six cases on the ordinary path. They exclude redirects, duplicate fallback work
and SEC/document requests; they are not billable-request maxima. Missing keys
skip their provider, which changes evidence coverage rather than proving a
successful pilot. No provider/account pricing is assumed.

Let `A = agent_max_retries` and `S = synthesis_max_retries`; these settings count
total attempts in the application loops. Defaults are both 1. The structured
specialists use A outside ModelClient's A loop; Q-first uses only the latter.
Synthesis similarly uses S outside ModelClient's S loop. The pinned SDK defaults
to **two retries (three attempts)** because client construction leaves its
`max_retries` unset. Ignoring redirects and optional paths, the conservative
logical SDK-attempt expression for a generated case is
`3 * (5*A*A + A + 2*S*S)`, or 24 at defaults (up to 72 across three generated
cases). This is conditional route accounting, not a USD or physical-dispatch
ceiling. Current model/output defaults: agent `gpt-4o-mini`/4096 tokens;
synthesis `gpt-4o-mini`/1536; an opt-in fast synthesis variant uses
`gpt-4.1-nano-2025-04-14`. Effective runtime settings remain unverified.

Additional dispatch hazards:

- Evidence pool failures trigger sequential fallback without waiting for already
  submitted work. Ordinary provider results are snapshotted at 10 seconds;
  source-document tasks may receive 20 seconds. `shutdown(wait=False)` does not
  cancel ongoing requests or prevent subsequent GETs in a worker's sequence.
- Agent wall cap is 16 seconds. Timed-out workers can continue ModelClient/SDK
  retries. Synthesis may start its second worker while the first is still live.
- The optional compound-risk repair calls the agent ModelClient again. Its
  wall-time budget is currently 0.0, so it is disabled on ordinary elapsed-time
  execution. Any enabling change invalidates the above model-attempt expression.
- urllib and HTTPX can follow redirects; each redirect can be another physical
  dispatch. HTTPX default provider clients also have SDK retry behavior. A hook
  only around `.call()`, `urlopen()` or an evidence task cannot prove coverage.
- `max_tokens` constrains requested completion output, not total serialized
  input. Evidence item counts, partial character truncations and timeouts are
  not tokenizer-based input or billed-unit limits.

## Safe next offline integration work

1. Define provider/model/operation route identities and an immutable effective
   configuration digest. Add a preflight rejecting unknown models, providers,
   logging/trace modes, optional repair paths and missing reviewed tariffs.
   Retain the exact six development cases and saved setup hashes.
2. Build an isolated injectable transport harness, still disabled for real
   execution, that calls the existing ledger before **each physical dispatch**.
   Test redirects, retry ownership, one-shot reservation consumption, concurrent
   workers and late completion using synthetic HTTP exchanges. Keep production
   paths unchanged until this adapter is independently reviewed.
3. Choose one retry owner in the future pilot adapter: disable hidden SDK retries
   there or intercept all of them. Ensure abandoned workers cannot bypass the
   shared ledger or start a fresh ledger on restart. Never refund timed-out work.
4. Serialize/tokenize the complete actual request for the selected model with a
   reviewed conservative accounting method, enforce output bounds at dispatch,
   and map every returned/unknown chargeable usage unit. Unknown prices, fees,
   units, response usage or route mismatches must halt further dispatch.
5. Produce a no-dispatch rehearsal artifact binding code/configuration/setup,
   route coverage and ledger identity. Fault-inject missing usage, oversize
   input, multiple dispatches per reservation, deletion/restart and cancellation.

These steps can be implemented and tested with invented prices and no keys.
They do not authorize execution. A live adapter still requires secure authorized
credentials, independent account/price verification, user USD approval, reviewed
transport coverage, complete CI and an explicit separately authorized run.
