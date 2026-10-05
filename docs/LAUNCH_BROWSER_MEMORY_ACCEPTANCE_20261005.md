# Signed-in research memory acceptance — 2026-10-05

Backend baseline: `0c1ebb8daaae66eb0b5c1257bbc342e5a144294d`.
Environment: signed-in production frontend and backend.
This run used the live browser UI and two real Apple analyses.

## Observed passes

- Intelligence Mode loaded the authenticated account's saved investigations and explicit profile.
- A fresh Apple investigation persisted exactly two messages and displayed the completed answer.
- History displayed the newly created company thesis record after reload.
- Research Trail (`/timeline`) displayed that same fresh record.
- New investigation cleared the active question and thread.
- Recall of `Browser acceptance check October 5` found the fresh investigation as a historical candidate.
- Selecting `Use in new analysis` visibly selected the prior record and AAPL scope.
- A separate comparison investigation applied the selected history and persisted its own two-message turn.
- The historical audit preserved the prior conclusion and rejected a directional change because none of the five retrieved references qualified as newer evidence.
- Personalized Intelligence Mode was marked as applied to the comparison.
- The notice preview reported zero eligible items and delivery remained off.

The separate production /ask smoke supplied by the account owner passed 10/10 checks before this browser run. Its successful cleanup responses were reported for the smoke conversation and thesis.

## Quality issue reproduced

Question:
> What is the strongest current public evidence for Apple's services-growth thesis, which operating risk could invalidate it, and what remains unverified? Browser acceptance check October 5.

The initial answer stated a Services margin of approximately 72%, while the source inspection panel reported zero verified SEC facts and five filing references. The displayed answer did not bind that numeric statement to an extracted claim. This is a grounding failure, not evidence that the number is false.

The explicit source-request detector recognized phrases such as "which source" and "pieces of evidence" but missed this natural wording. The proposed fix recognizes natural evidence requests and excludes company-wide claims that do not mention the requested Services scope. A Services result must still have relevant extracted claim text; consolidated revenue or profit must not stand in for segment support.

## Limits and follow-up

- This verifies one account and two Apple UI flows; it does not measure accuracy across companies or prove account isolation by itself.
- No newer-evidence positive comparison was exercised in this run.
- The browser acceptance investigations remain as labeled records for review.
- The proposed fix uses conservative lexical Services relevance; it is not a complete claim-level semantic verifier.
- After deployment, repeat the initial evidence request and confirm either relevant attributed claims or an explicit insufficient-evidence answer.
- Broader numerical grounding, relevant issuer KPI extraction, and benchmark accuracy remain release work.
