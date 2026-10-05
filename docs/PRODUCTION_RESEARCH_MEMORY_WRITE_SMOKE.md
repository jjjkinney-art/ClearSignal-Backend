# Production private research-memory write smoke

Status: **explicitly mutating, account-scoped release check.** Run only after
the non-mutating launch read smoke passes.

The harness creates one uniquely tagged private conversation and one user
message in the authenticated account. It verifies direct retrieval and
cross-conversation recall, then soft-deletes the conversation in a `finally`
block and proves the deleted record is hidden from direct reads and recall.

It does not call `/ask`, model or data providers, shared ticker-wide stores,
notices, personalization, portfolios, billing, or external delivery. The
soft-deleted rows remain available only to approved retention/deletion
operations; the fixture disappears from the product immediately.

## Safety requirements

- Use a fresh bearer token for the intended test account.
- The script requires the exact production-write confirmation phrase.
- Never paste a bearer token into chat, source files, logs, or arguments.
- If cleanup fails, treat the run as failed and manually delete the uniquely
  marked conversation from the product before proceeding.

## Run

After the 16/16 read smoke passes and the token is still exported as
`CLEARSIGNAL_SMOKE_ACCESS_TOKEN`:

```bash
python3 scripts/launch_research_memory_write_smoke.py \
  --confirm-production-write WRITE_PRIVATE_RESEARCH_MEMORY
```

Success requires exit code 0, `"passed": true`, seven passing checks,
`"cleanup_succeeded": true`, `"shared_ticker_writes": false`, and
`"provider_calls": false`.

Unset the token after verification:

```bash
unset CLEARSIGNAL_SMOKE_ACCESS_TOKEN T
```
