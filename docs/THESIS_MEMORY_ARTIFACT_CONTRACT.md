# Account-owned thesis memory artifact contract

**Status:** persisted, owner-filtered, and protected by a newer-evidence comparison gate  
**Schema:** `1`

## Purpose

ClearSignal needs a stable, inspectable representation of the assumptions that
matter to a user's saved thesis before it can safely notice when new public
evidence changes that thesis. The artifact is a bounded projection of the exact
structured response already saved inside an account-owned research message.

This is not semantic memory, a generated summary, or current evidence.

## Ownership and lifecycle

- An artifact inherits ownership from its parent `ResearchMessage`; it must never
  be stored or queried outside that owner-filtered boundary.
- Soft deletion, hard deletion, export, and retention must follow the parent
  conversation and message.
- Shared ticker-wide research routes must not expose these artifacts.
- Older analyses are not backfilled automatically.
- Raw transcript text is not an artifact input.

## Safety boundary

The projection:

- reads only the structured `answer.investment_thesis` branch;
- copies only allow-listed thesis fields and evidence-reference metadata;
- enforces text, list, and evidence-reference bounds;
- excludes arbitrary model metadata, raw conversation text, prompts, and general
  answer branches;
- labels every artifact `historical_only` and
  `requires_fresh_evidence`;
- fails closed with `status: unavailable` when no supported structured thesis
  exists.

Artifacts must never be silently inserted into a future prompt. A future
analysis may use one only after explicit same-owner selection, ticker validation,
and the existing fresh-evidence admission boundary.

## Schema

```json
{
  "artifact_version": 1,
  "status": "available",
  "historical_only": true,
  "requires_fresh_evidence": true,
  "ticker": "AAPL",
  "thesis": {
    "direct_answer": "Historical thesis text",
    "key_drivers": ["Historical driver"],
    "key_risks": ["Historical risk"],
    "what_to_monitor": ["Historical metric"],
    "invalidation_conditions": ["Historical invalidation condition"],
    "confidence_score": 59.0
  },
  "evidence_references": [
    {
      "evidence_id": "E1",
      "url": "https://...",
      "freshness": "current"
    }
  ],
  "evidence_integrity": {
    "overall_status": "admitted",
    "has_material_conflict": false,
    "admitted_count": 1,
    "blocked_count": 0
  }
}
```

## Next reviewed integration

The owner-filtered loader requires an explicit conversation id, validates the
authenticated owner, deletion state, assistant role, and same-ticker scope, and
re-projects the artifact from the saved structured response before returning it.
It never reads raw message text.

The comparison gate now admits only attributable, same-ticker evidence whose
published, filed, or observed timestamp is newer than the selected thesis and
which the caller has explicitly marked admitted and materially related. Retrieval
time never makes an old document new. Conflict, supersession, unavailability,
future evidence, missing attribution, and missing source time all fail closed.
The gate never decides thesis direction by itself.

1. Produce an evidence-bound stronger, weaker, unchanged, or unverified
   classification only after the gate is ready.
2. Expose the historical artifact, eligible new evidence, change classification,
   and uncertainty in Intelligence Mode.
3. Add end-to-end acceptance tests before enabling proactive notices.
