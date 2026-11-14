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

## Second pass: risks and business sentences
- **Heading as context:** a stripped summary heading is kept beside the risk, never in its quote. It can support a passage that itself states the issuer's exposure and a consequence.
- **Plain-language risks:** a risk can now qualify if the passage states the issuer's own exposure and a consequence, and uses a term that this filing's business section repeats and that is not common across business sections generally. A term alone never qualifies, and a sentence naming a macro hazard still needs a concrete dependency.
- **Common-word list:** `business_common_words.py` is fixed, derived from 18 issuers in retained filings, and is itself development data.
- **Ranking:** at equal specificity, a risk the issuer heads in its own summary comes first. The limit stays two.
- **Filing-defined short names:** used only to select a quote inside one issuer's already verified filing, when the filing defines the name and the directory's registrant name begins with it. Identity resolution and routing are unchanged. A complete sentence was tried first: VIRC's best one contains a digit, so a longer limit gained nothing and was reverted.

Replayed against Runs 2, 4, 5 and 8, compared with `2e58f6e`:

| Result | Cases |
|---|---|
| Material risk recovered | MNST regulation; AGEN clinical-trial enrollment |
| Added, weaker | INGR capital-spending funding; MAN reputation damage, partly generic |
| Useful risk lost from this pass | None found |
| Still missed | MNST bottlers and aluminum (limit of two); DGXX data-center and HPC risks |
| Threshold answers | Unchanged |

## Evidence gaps and unfixed limits
- **DGXX cause:** the filing gives causes for a revenue line (energy sales), not for reported total revenue, so none is bound. That is correct behaviour.
- **DGXX business:** remaining sentences carry numbers or promotional wording, which existing rules exclude.
- **MNST operating income:** the filing's attribution is at segment level, so none is bound to the consolidated figure.
- **Checker limit:** one Run 2 NPK business quotation fails the verbatim check because it begins with a stray invisible character. The business quote was not changed by this work.

**Next quality checkpoint:** a fresh cohort. These replays cannot measure generalization.

Using this in a run needs a new freeze, pre-registration, package and approval.
