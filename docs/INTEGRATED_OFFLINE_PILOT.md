# Integrated offline pilot rehearsal

`python -m validation.pilot_rehearsal --output-dir /tmp/new-pilot-rehearsal`
rehearses the six frozen v2 cases through
`app.services.router_service._run_investment_pipeline`. This is an offline test
entrypoint, not the legacy capture runner or a live provider adapter. It has no
execute, credential, approval, tariff, limit, resume, or reset option.

The launcher constructs a fresh child environment containing only invented
credentials, an invented SEC contact and capture explicitly false. It does not
copy or inspect caller credential values. The child uses isolated Python, a new
working directory, an audit guard that refuses sockets, real DNS and child
processes, and preimport bridges for OpenAI, urllib and requests. The production
document admission check receives a fixed synthetic public DNS answer for the
three reviewed SEC hosts; it never resolves them. SDK platform metadata is also
fixed to avoid its `uname` subprocess. `.env` reads/writes are refused.

The child also receives a fresh empty HOME. Requests sessions disable `trust_env`
at construction and reject re-enabling it before request preparation. Both
requests netrc-discovery aliases and stdlib netrc parsing are fenced before
application imports, with an audit-level `.netrc`/`_netrc` open refusal as defense
in depth. This prevents credential discovery before the synthetic send boundary;
clearing HOME alone would allow the operating-system passwd-home fallback.
Synthetic sentinel-home tests cover new/copied sessions, changed sessions and
saved library aliases, asserting zero file reads, zero passwd fallback and no
SEC Authorization header. No real credential files are inspected.

No production source, provider settings, deployment or access controls change.
Application pools still use real concurrent workers. Application total attempts
remain one. The benchmark explicitly overrides the SDK's production default of
two retries to **zero** and uses HTTPX MockTransport with no transport retries.
SDK copies retain that transport; attempts to change its retry owner are refused.
The bridges cover module-level `urlopen` aliases imported by the application,
urllib opener dispatch, and requests' session send path. Any other route hits a
refusal or the socket guard. This is cooperative assurance for the bound code,
not a sandbox against arbitrary hostile Python or a compromised filesystem.

## Immutable scope and reservations

The worker requires CPython 3.11.9 and verifies the frozen setup, source binding and exact audited versions:
OpenAI 2.32.0, HTTPX 0.28.1, httpcore 1.0.9, requests 2.32.5 and urllib3 2.8.0.
Dependency drift fails preflight instead of silently changing the policy. No
transitive dependency pins in the production requirements are changed here.
The artifact records the Git revision plus a digest of the application and
validation Python sources, including uncommitted edits if present. That digest
never includes environment files, credential stores, diagnostics or headers.

| Per issuer case | Model quotas | SEC GET quota |
| --- | --- | --- |
| `core_thesis` | 0 | 8 |
| `decision_threshold` | 1 each for valuation, macro, risk, market, quality and Q-first; 2 synthesis | 2 |
| All six cases | 24 | 30 |

Unused stage/case/category slots cannot transfer. Core SEC allocation is at most
two directory GETs, three submissions GETs, one facts GET and two document GETs.
The second directory allowance covers a separate document-discovery client.
Threshold allocation is one directory and one submissions GET. Allowed URLs are
the exact reviewed directory, current case CIK endpoints and internal fixture
document URL. Only GET without a body is accepted. Redirects are rejected before
following any destination. The bridge applies the configured invented SEC
contact to both urllib and requests; it never records that contact. SEC claims
share a durable sliding-window limit of ten per second, with waits outside the
SQLite transaction. No real SEC response, identity or service limit was tested.

Model requests use control `gpt-4o-mini`, explicit `service_tier=default`, `n=1`,
non-streaming plain text, temperature zero, and 4096 output tokens for agents/Q
or 1536 for synthesis. Responses must identify `gpt-4o-mini-2024-07-18`, default
tier, one complete plain-text choice and recognized, internally consistent usage.
Unknown units, model/tier mismatches or missing/excess usage permanently halt.

Every model attempt reserves **128,000 input tokens**, plus its full output
allowance, regardless of actual request size. Serialized bytes are never billed
as tokens. The separate conservative admission check bounds plain-text content
by its UTF-8 byte count (byte-level BPE starts with bytes and merges), adds 64
tokens per message and 64 for reply framing, and requires room for output within
128,000. This is a deliberately restrictive offline assumption for the fixed
one/two-message schema, not independent verification of live model framing or
alias mapping. `token_framing_verified_for_live` remains false. A separately
reviewed complete-request/tokenizer method is still required before live use.

At the supplied illustrative rates of $0.15/M input and $0.60/M output tokens,
all 24 model slots reserve $0.5105664. The ledger's $0.52 comparison is an
illustrative API-usage allocation only. SEC's synthetic zero units do not prove
zero incremental costs. Neither figure is a verified tariff, invoice ceiling,
whole-pilot cap, account entitlement or spending authorization.

## Durable failure behavior

One shared SQLite ledger binds the immutable policy, case, route, complete model
body and allowed non-secret semantics. Request-header and credential/contact
values are excluded from the digest. Known invented secret canaries in model
content are rejected before binding; this does not claim a general-purpose
secret detector. The child holds captured diagnostics only in memory, scans
them for invented canaries and discards them. It publishes no prompts, model
answers, raw exceptions, provider headers or diagnostic logs.

Reservations and one-shot claims are separate atomic transactions, both fenced
by the persistent halt. No DB or bridge lock spans the simulated exchange.
Reservations never refund. Stage timeout, partial pool submission failure,
unknown request or ambiguous response halts further work before the original
sequential/second-synthesis fallback can claim again. An already claimed late
response can still settle after halt; pending reservations remain retained.
No new case starts until every worker drains and every claim settles.

Executor construction and underlying `submit()` failures also durably halt.
Each submission has a tracking ticket before it enters the actual executor:
CPython can queue work and then raise while starting a thread, without returning
that work's Future. On such an ambiguous failure, queued tickets are fenced
before their function can run; already-running tickets remain tracked through
late completion. Synthetic faults are injected inside the actual submission,
after queueing, for partial agent work and queued/running synthesis work. The
artifact reports these ambiguous and fenced submissions separately from provider
claims; no synthetic future is mistaken for proof that queued work never existed.

Reopening this rehearsal policy always halts, even if the previous process
appeared complete. A crashed claim cannot replay. Existing output directories,
missing/replaced ledger files, policy changes and implicit migrations are
refused. A failed child never starts a replacement ledger. A separately invoked
new offline rehearsal may use a new directory; nothing automatically restarts
or authorizes a real pilot. Filesystem rollback by a privileged external actor
is outside this cooperative mechanism.

## Evidence and remaining prerequisites

The happy fixture run completes all six cases, including NPK with reviewed CIK
`0000080172`, with **16 model claims and 27 SEC claims**. The lower counts reflect
actual application skips and fixture coverage; they are not new quotas. The
concurrency scenario holds six actual agent exchanges in flight together. All
protocol usage is invented fixture data, not observed provider billing.

Tests exercise 429/500 SDK handling with zero retries, valid/refused SDK copies,
duplicate-stage attempts, oversized/secret-bearing inputs, unknown routes,
response/usage mismatches, SEC redirects and identity mismatch, application
configuration and `.env` drift, socket/DNS attempts, all three stage timeouts,
partial pool failure and sequential fallback, concurrent claims, late settlement,
process crash/reopen, deletion/replacement, full allocation and SEC pacing.

`artifact.json` binds code, dependencies, setup, effective settings, policy and
ledger; it records case identities, route counts, full reservations, concurrency,
coverage gaps and diagnostic/network audit results. A crashed child reports
`worker_incomplete` and unknown final network-audit count, retaining its ledger.
All artifacts keep `execution_allowed`, `spending_authorized`, `tariffs_verified`,
`all_incremental_charges_accounted`, `hard_usd_cap_established` and `launch_ready`
false; quality stays `not_adjudicated`.

FMP is deliberately absent: financial statements, market/price data, valuation
ratios and analyst estimates remain coverage gaps. NewsAPI company/macro news
and FRED macro evidence are also absent. Synthetic SEC documents and empty facts
do not replace that coverage or establish investment-answer quality.

Before any live integration/run: independently review every real transport,
redirect/retry path and late-worker fence; verify current model context/framing,
response identity, usage units, account rates and all incremental provider and
platform charges; securely verify authorized credentials and proxy replacement
under separate permission; agree reduced FMP-absent coverage and quality criteria;
complete required CI, independent review and deployment verification; and obtain
explicit scope and USD spending approval for a separately authorized run.
This rehearsal proves no actual provider authentication or network-secret proxy
replacement. No paid/provider request is performed or authorized here.
