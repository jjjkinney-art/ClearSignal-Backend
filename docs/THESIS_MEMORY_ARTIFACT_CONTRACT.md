# Account-owned thesis memory artifact contract

**Status:** implementation foundation  
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

1. Save this projection alongside each newly completed account-owned assistant
   response.
2. Load artifacts only through an owner- and deletion-filtered service.
3. Compare a selected historical artifact with newly admitted evidence.
4. Emit a thesis-impact result only when attributable evidence is newer and
   materially related.
5. Expose the historical artifact, new evidence, change classification, and
   uncertainty in Intelligence Mode.
6. Add cross-account, deletion, stale-evidence, conflict, supersession, and
   no-new-evidence acceptance tests before enabling proactive notices.
