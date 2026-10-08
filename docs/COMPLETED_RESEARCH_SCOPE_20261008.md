# Completed research conversation scope — October 8, 2026

## Observed problem

Signed-in post209 source-evidence questions with automatic company detection
saved an attributed assistant answer into a conversation whose ticker scope was
empty. Reopening worked, but Recall disabled Use in new analysis, and the
server's selected-history loader rejected the empty scope. Enabling the button
alone would not repair the server boundary.

## Change

After atomically saving a completed server-produced question/answer turn, bind
an empty owned conversation scope to the response's unambiguous structured
issuer. Only an investment-thesis-shaped answer qualifies. Rankings,
multi-issuer routing, invalid symbols, missing attribution, and conflicting
structured issuer fields remain unscoped. The public message endpoint only
accepts user messages and cannot invoke this binding path.

Retries use the already persisted assistant response, so a different retry
payload cannot change the issuer. Explicit scopes remain unchanged. Scope and
messages share the caller's transaction and owner/deletion boundary.

When selecting history, reject snapshots attributed to another issuer or a
ranking. In a multi-issuer conversation, require the snapshot itself to identify
the requested issuer. Legacy snapshots without issuer metadata retain the
existing compatibility behavior only within a single explicit scope.

No frontend change is required: reopening and Recall already consume the
server's conversation scope. Existing unscoped records are not backfilled from
transcript text; reopen and run a fresh completed company analysis to bind scope.

## Verification

152 checks passed across completed scope, conversation CRUD/recall and API routes,
selected history, historical freshness, comparative routing, source-evidence
latency, thesis-impact evidence gates, and launch security.
The new checks exercise persisted scope across a new database session, ticker
filtering, Recall's returned scope, selected-history application, deduplication,
foreign/deleted records, conflicting attribution, explicit scope preservation,
and wrong-issuer/latest-snapshot rejection.

Publication follows the merged selected-history routing repair (PR211).
Deployment and signed-in live acceptance remain pending. Live acceptance must
submit a new automatic-scope company question, reload, confirm the Recall ticker
badge and enabled selection action, then run a fresh selected-history comparison.
The genuine newer-evidence positive comparison test and full post210 33-company
acceptance report remain open.
