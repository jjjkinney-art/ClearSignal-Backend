# Completed research retries preserve the saved answer

Base: `d1ed1fcac959f52d71b67cc5022da9dcfd7392b7` (merged PR316).
Validation date: 20 October 2026 UTC. This is offline work; no live run authority.

## Defect and behavior

The real authenticated `/ask` path could recompute a completed conversation turn
while storage deduplicated that turn by request reference. With invented annual
EPS changing from 5 to 6, the retry displayed 6 but History still contained 5.
The regression fails on the unmodified base. This reproduces a code defect, not
an observed production incident or an explanation of an earlier pilot failure.

For an authenticated owner supplying both `research_conversation_id` and
`research_request_ref`, `/ask` now reads the original completed response after
normal preflight and before retrieval/model work. The lookup requires both the
conversation and message to belong to that owner, an undeleted conversation,
an assistant message, a supported versioned response snapshot, and the existing
100,000-byte snapshot bound. It returns a detached JSON copy. Client message
routes still cannot submit assistant snapshots.

A completed retry returns the original full post-integrity payload, citations,
reporting periods, request id and observability metadata. It is a historical
replay, not fresh validation. `X-Research-Turn-Replayed: true` and
`Cache-Control: no-store` identify the early replay. Legacy JSON remains one
object; opt-in progressive NDJSON returns one final frame with that same object.

The key is scoped to owner/conversation/reference. **First saved turn wins even
if question or context changes with the same reference. A new question or fresh
analysis requires a new reference.** Whitespace/truncation follow the existing
storage normalization. A new reference fetches updated data and saves a new turn.
Requests without an explicit reference/conversation follow the original path.
Authentication, beta admission, entitlements when enforced, rate limits and daily
quota preflight still precede replay; a replay does not bypass them.

The save path also rereads the canonical response within its transaction before
emitting. If an earlier completed turn wins, that payload is emitted, and the
discarded recomputation is not appended to owner thesis/notice storage. A failed
save makes one fresh owner-scoped lookup after rollback to recover an existing
completed turn; it does not rerun sources. Ordinary persistence-unavailable
behavior remains best effort if no completed response can be recovered.

This is **not** provider dispatch at-most-once for simultaneous first requests.
In-flight duplicates may both retrieve before one completed turn is visible.
No database schema, production supervision, deadline, quota, capture policy,
pilot authorization or source-admission rule changes.

## Offline acceptance

`tests/test_owned_annual_eps_ask.py` exercises actual AuthMiddleware, signed
invented HS256 tokens, DB-backed beta grants/local owner resolution, normal
`/ask` streaming/research pipeline, strict annual EPS admission, and account-owned
conversation creation/save/reopen. SQLite is disposable. External provider/
profile results and directory data are substituted; model entry points are
counted and must remain unused. Billing enforcement and unrelated rate limiting
are disabled in this fixture; billing acceptance is not inferred.

Twenty-two tests cover exact display/reopen/citation identity, invalid JWTs,
revocation, daily quota, distinct owners, persisted preferences without cross-
account spoofing or source-fact reweighting, same-reference replay/new-reference
refresh, changed-question semantics, NDJSON, same ref in a different conversation,
late canonical winner and failed-transaction recovery, and deleted/foreign/
missing/unsupported/error/oversized snapshot rejection. The late-winner tests
control lookup order; they are not a PostgreSQL concurrency/load test.

The retained replay script uses the original PR314 archive, verifies all 19
inventory entries and both body hash/length receipts, and supplies the exact
captured Company Facts bytes to the real parser. It then sends six signed `/ask`
requests, reopens each stored answer, repeats each completed request and verifies
another owner's reopen is denied before sources. No external requests or model
calls occur. Identity directory and unrelated providers remain injected.

| Retained request | Source result |
| --- | --- |
| ASML annual basic EUR EPS | attributed, 24.73 versus 19.25 |
| ASML annual diluted EUR EPS | attributed, 24.71 versus 19.24 |
| NPK annual basic USD EPS | attributed, 4.63 versus 5.82 |
| NPK annual diluted USD EPS | explicit insufficient evidence |
| NPK annual basic and diluted USD EPS | partial; basic comparison and diluted gap |
| ASML annual basic USD EPS | explicit insufficient evidence; no currency conversion |

All six saved snapshots and assistant texts exactly match their emitted answers;
all six completed retries are exact with no further source reads; all six
cross-owner reopen attempts are 404. No account keys or raw retained bodies are
committed. `OWNED_ANNUAL_EPS_ASK_REPLAY_20261020.json` records the bounded results.

To reproduce from the repo root using audited CPython 3.11.9 and dependencies:

```sh
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
  SEC_USER_AGENT='Test contact@example.invalid' \
  /PATH/TO/PINNED/python -I -B scripts/replay_owned_annual_eps_ask.py \
  /PATH/TO/PR314-results.zip /NEW/owned-replay.json
```

This script uses pytest fixtures as offline tooling, never as runtime product
code, and denies external socket/DNS/connect activity (allowing local AF_UNIX
construction for the event loop). Original bodies and historical ledgers are
read only; no full historical inventory is independently revalidated here.

## Verification and launch gates

`OWNED_ANNUAL_EPS_ASK_VERIFICATION_20261020.json` retains commands/logs and hashes:
22 focused tests, 266 related tests and 386 source tests passed; 18,365 collected
with zero errors; import smoke found 136 routes. Five local CI group replicas
passed (83 / 87 / 221 / 178 / 195). Related tests report a Starlette/AnyIO
deprecation; existing source tests report ten executor teardown warnings. The
previous baseline review documents that warning class; it is not claimed fixed.
Hosted CI/full per-file regression must still pass on the exact published head.

This closes the demonstrated completed-retry inconsistency and adds bounded
signed HTTP/save-reopen acceptance. It does not establish real Supabase/provider
authentication, production PostgreSQL/concurrency, browser rendering, billing,
full personalized research usefulness or current directory/source independence.
No live capture/approval is reused; all twelve consumed approvals stay consumed.
The separate conditional valuation endpoint remains default off.

Next launch work remains company-specific competitive assessment, explicit
valuation/return assumptions and decision boundaries, and risk materiality tied
to evidence. These need independent source/usefulness adjudication and a
separately reviewed development benchmark before frozen holdouts and production
signed-in acceptance. The original six broad answers remain partial. Neither
this replay nor passing transport implies universal-company launch readiness.
