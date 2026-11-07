# Run 8 answer quality: offline fixes (2026-11-07)

Development evidence only. These fixes were designed on Run 8's retained responses for BP, MNST, CRDO, DGXX and VIRC, so replaying those cases cannot measure generalization. Nothing was retrieved. Run 8 and its consumed approval are unchanged. Cooperative cancellation remains untested live. A baseline replay reproduced Run 8's claims exactly for all 8 answered cases before any change.

## Extraction failures fixed
- **Stated cause after a restated metric (MNST):** "Net sales increased primarily due to ..." now binds to the statement before it. A next sentence with its own amounts still binds by itself.
- **"Sales" as the opening word (VIRC):** now names revenue only at the start of a sentence.
- **Product catalogs (MNST):** "We offer the following ... product line" is no longer a business description.
- **Segment revenue model (MNST):** "Our ... segment primarily generates ... revenues by selling ..." is now one.
- **Employee benefits (VIRC, CRDO):** no longer business descriptions.
- **"The Corporation" as a subject (DGXX):** treated like "The Company". This did not produce a DGXX description.
- **Risk selection (CRDO, DGXX):** corporate structure, generic key-person dependence and "if any such risks occur" no longer qualify.
- **Summary headings (MNST):** "Operational and Industry Risks ●" is no longer quoted.
- **Rounding (MNST):** amounts gain precision only when rounding would make a real change look like none.

## Decision-threshold answers
Each states a historical baseline, an explicit monitoring condition with its basis, and exactly which inputs a decision threshold would need: no number is invented.

## Evidence gaps and unfixed limits
- **DGXX cause:** the filing gives causes for a revenue line (energy sales), not for reported total revenue, so none is bound. That is correct behaviour.
- **DGXX business:** remaining sentences carry numbers or promotional wording, which existing rules exclude.
- **VIRC business:** better sentences exist, but need a short-name alias ("Virco"), which existing identity rules forbid, or a 304-character limit change. Left for a decision.
- **Plain-language risks:** bottler, aluminum, data-center and supplier risks exist but do not meet the specificity rule. Fixing summary headings removed MNST's regulation risk, whose score came from the heading.
- **MNST operating income:** the filing's attribution is at segment level, so none is bound to the consolidated figure.

Using this in a run needs a new freeze, pre-registration, package and approval.
