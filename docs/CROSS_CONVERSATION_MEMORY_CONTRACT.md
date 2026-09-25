# Cross-conversation memory: implementation contract

Status: design contract for the required pre-public-launch JARVIS milestone. No endpoint described here is live solely because this document exists. Voice is outside this launch scope.

## User promise

An approved user can ask a question, leave, and return weeks later in a new conversation: “What was that concern about Apple we discussed last month?” ClearSignal finds relevant discussions without exact wording, shows when and why a conclusion was reached, and separately checks whether current evidence changes it. If several discussions plausibly match, it asks which one. If none matches, it says so. It never portrays an old answer as a current fact or silently treats another person's research as the user's memory.

The same account's signed-in Analysis and Intelligence Mode must share one history. The interface should make resuming an investigation as easy as opening a recent conversation, searching ordinary language, or asking a follow-up. The user can inspect the retrieved original, revise active scope, and delete history. A saved conversation is not evidence that any scheduled monitoring ran.

## Existing boundary and why a new store is needed

- `app/services/history_service.py` reads the process-level `JsonFileTimelineStore` by ticker. `/history` and `/history/summary` call it without a user identifier. It is a legacy analysis-history surface, **not** a user-owned conversation store and must not be used as the source of personal recall. Before shipping personal recall, audit every route exposing that legacy store and block access to another user's data or retire the route.
- `memory_entries` and `thesis_versions` have nullable `user_id` fields and ticker/session-oriented history. Their presence does not make older unbound rows safe to retrieve as personal memories. Exclude unbound and other-user rows by construction; do not automatically claim legacy data for a newly signed-in account.
- Current follow-up context and frontend presentation are not a durable, account-owned conversation transcript. The `/ask` response can contain generated research and separately verified facts; persist their provenance separately and do not infer a source citation for generated prose.

## Data and ownership

Use PostgreSQL as the durable source of truth. Add an additive migration with separate `research_conversations` and `research_messages` tables. Each conversation has an immutable owner identity (`user_id` referencing the authenticated user), ID, title, created/updated timestamps, explicit scope (ticker(s), time window, optional portfolio reference), and deletion timestamp or a clearly specified hard-delete policy. Each message has an immutable owner inherited from its conversation, ordered ID, role, text, created timestamp, request reference, and a versioned structured snapshot of displayed claims, evidence links, freshness and uncertainty. Record preference memories separately with their origin and a user-editable/deletable lifecycle. Never treat an AI inference about a user's holdings as a confirmed holding or preference.

The client cannot supply a trusted owner. Resolve it from the authenticated session on every read and write. Query by both conversation ID and owner; a foreign or unknown ID returns the same 404. Message insertion verifies that the target conversation belongs to the authenticated owner in the same transaction. Do not expose personal memory through the global ticker timeline, caches, logs, metrics labels, URLs, or another user's portfolio. Backups, exports and deletions must cover the new tables and any search index.

Start retrieval with a bounded, account-filtered text search over messages and explicit scope/date filters. Index by owner plus time and conversation, and enforce owner filtering **inside** the retrieval query before ranking. Add semantic/vector retrieval only when it demonstrably improves evaluation and can obey the same owner, retention and deletion boundaries. Rank candidates with dated excerpts and identifiers; return ambiguity and no-match outcomes explicitly. Never silently turn retrieved text into instructions for the model. Put quotation boundaries around past messages and cap recalled context and cost.

## API and flow

1. `POST /research/conversations`: create an owned conversation (or idempotently resume one) after authentication/admission.
2. `GET /research/conversations`: paginated recent list and bounded search for the current owner, with stable cursor, dates and scope. `GET /research/conversations/{id}` returns only that owner's conversation and messages.
3. A user-initiated `/ask` can carry an owned conversation ID and explicit scope. On a successful response, atomically append the question and the displayed answer snapshot or record an honest interrupted/failed state. Never claim to have stored an answer that did not persist. Retrying with the same request reference must not duplicate messages or charge repeated model calls merely to recover history.
4. `POST /research/recall`: take a natural-language query and optional scope, retrieve only current-owner candidates, and return `matched`, `ambiguous`, or `unavailable` with dates and original conversation references. For a question asking what is true **now**, perform a separate on-demand evidence check with its own timestamp. If that check fails, show the historical answer and say that the present conclusion cannot be verified.
5. `DELETE /research/conversations/{id}` and an account-wide export/deletion path must invalidate retrieval records and remove associated personal data according to the published retention/deletion policy. Support cannot bypass identity verification or the existing deletion runbook.

Names and payloads above are proposed contracts, not permission to expose incomplete endpoints. Define response schemas, size limits, retention, quotas and error behavior before implementation. Keep automatic monitoring off until its own rollout gate.

## Validation and rollout

- Two approved users discuss the same ticker and phrase; each sees only their own messages, including search results, resume links, errors and exports. Probe direct IDs, stale cursors, cache keys and deletion races.
- Save dated source-backed discussion; return after at least a month in test data with a paraphrase lacking exact keywords; find the right conversation and display original date, source and original conclusion separately from newly fetched evidence. Evaluate recall quality on paraphrases, ambiguous matches, missing records and stale evidence. An uncertain result requests clarification.
- Verify no memory survives account deletion in database, retrieval index or user-visible caches; restoration/backups honor the documented deletion process. Verify a remembered preference can be inspected, corrected, or deleted.
- Test provider failure, DB write failure, partial retries, missing ticker, no portfolio, large histories, malicious text inside recalled messages, and concurrent messages. Establish measured retrieval latency, storage and model cost ceilings before enabling for the cohort.
- Release in phases: schema and private tests; authenticated read/write behind an off-by-default flag; limited-cohort recall with manual quality review of aggregate, non-identifying outcomes; then broaden only after privacy, accuracy, deletion and performance gates pass. No public site copy should claim long-term personalized memory before the real acceptance test passes.

## Near-term implementation order

1. Audit and close the unscoped legacy history boundary. Determine whether the current route can be made account-owned from available data or must return an unavailable state until new persistence exists.
2. Land the additive owned-conversation schema and tested CRUD/search service with strict isolation and deletion; keep the new endpoints dark.
3. Integrate `/ask` and Intelligence Mode through one conversation contract, then expose recent history and transparent recall. Preserve original source links and timestamps.
4. Run the month-later and two-account acceptance tests against production-equivalent data, observe a limited cohort, and update the public-launch gate only after the results pass.
