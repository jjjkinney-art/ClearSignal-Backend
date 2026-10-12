# Offline SDK fixture transport

`validation.benchmark_transport.BenchmarkTransport` connects the real synchronous
OpenAI SDK's HTTPX dispatch boundary to an internally constructed, exact
`httpx.MockTransport`. It only accepts immutable `FixtureResponse` data. There is
no transport/handler injection argument, credential loader, application import,
CLI execution option or production integration. Real/default transports,
transport subclasses and callback fixtures are rejected. Subclassing the wrapper
to override its internal handler is also rejected. Requests must use an
exact HTTPX request and in-memory ByteStream; custom stream callbacks are refused.
This is cooperative fixture-only assurance, **not sandbox security against
arbitrary Python**, monkeypatches, replaced imports or malicious local storage.

The only accepted operation is POST to
`https://fixture.invalid/v1/chat/completions`, with an explicitly selected model,
plain-text messages and `max_tokens`. Extra fields (tools, streaming, alternate
billing units) and unknown models/URLs fail closed. Request body byte length is a
**synthetic input unit, not a tokenizer or billing bound**. Caller-supplied policy
prices use the exact route `fixture-bytes/<model>`; no current tariffs or actual
spending approval are provided. Legacy policy field names `input_token_usd` and
`maximum_input_tokens` represent those synthetic byte units only in this adapter.
`FixtureResponse.input_units/output_units` are explicit fixture usage, including
for simulated error responses, not independently parsed provider billing evidence.

The wrapper clones method, URL, headers and complete body before hashing and
reservation. It binds that digest, case, route and unit bounds to a reservation,
commits `claim_dispatch()` under SQLite BEGIN IMMEDIATE, calls the internal mock
once, then settles usage. Every SDK retry and allowed same-route redirect enters
this boundary again and needs a new reservation. Unknown redirect destinations
are refused before dispatch. A lock serializes the fixture response sequence;
separate wrappers/processes still share aggregate ledger limits and atomic claims.

New ledgers use SQLite `user_version=2`. Reopening older/unversioned ledgers fails;
there is no implicit migration, reset or overwrite. A bound reservation can only
settle after a successful one-shot claim. The accounting-only unbound API remains
available for existing offline tests, but cannot claim or dispatch requests.
Policy hash verification and request binding precede claims. Already claimed
reservations cannot replay, even after restart. Missing or excessive usage halts
new reservations; late claimed responses may settle after a halt. Reservations
never refund. Crash-before-claim reservations remain charged; crash-after-claim
states remain ambiguous and unresolved until explicit settlement/review. The
wrapper does not automatically recover or replay either state. A caller may
explicitly claim an unclaimed bound reservation, but can never reuse a claim.
This does not promise exactly-once delivery to external systems or cancellation
of already claimed work.

The existing six-case development allowlist, one active case, rerun refusal,
exclusive ledger/preflight creation, and holdout exclusions remain enforced.
Preflight still reports execution disabled and no established hard USD cap.
Application providers, capture runner, benchmark artifacts, runtime configuration
and credentials are untouched. No paid/live provider request is supported.

Tests exercise the real SDK with 429/500 retries, HTTPX redirects, process/thread
claim races, immutable bindings, caller request mutation, conservative crash
states, unit bounds, usage failures, unsupported transports/streams and holdouts.
They block socket connection, resolution and datagram send attempts.

Before any separately authorized live integration, pricing and all billable units
must be verified, complete request bounds established, every provider/SDK physical
attempt instrumented, configuration/credentials reviewed, and an explicit USD
budget approved. FMP, NewsAPI, FRED, SEC and the existing capture runner remain
outside this fixture transport. No whole-pilot cap is established.
