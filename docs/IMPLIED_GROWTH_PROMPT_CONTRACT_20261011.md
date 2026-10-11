# Implied-growth prompt semantics

The question-answerer previously instructed the model to calculate earnings
CAGR but report it as revenue CAGR, to force a numerical growth answer, and to
supply numerical historical analogs from training knowledge when evidence was
absent. Valuation and synthesis prompts independently repeated the forced CAGR
instruction. This increment shares one explicit-input contract across those
three implied-growth prompts.

The contract requires named input provenance, multiple basis/date, exact
scenario horizon, terminal multiple and earnings endpoint before computation;
missing inputs must be identified without invented values. Earnings growth
cannot become revenue growth without a margin/share-count bridge. Consensus
comparisons require matching metrics and periods. Numerical analogs need
supplied evidence. Implied operating growth is not expected stock return.

Existing scenario conventions (3–5 years, 10% discount, terminal P/E 20–25x)
remain labeled assumptions/ranges. Explicit user assumptions stay explicit;
the patch neither silently replaces them with defaults nor introduces a new
valuation model. Ordinary valuation intents and existing generation paths stay
available. Four-sentence question-answerer formatting is preserved.

Validation: 151 tests passed in separate processes across
 test_implied_growth_contract (3), test_phase4_intent_and_qfirst (50),
 test_question_anchored_valuation (50), test_valuation_consistency (48).
New tests mock model calls, inspect all three prompts, and verify explicit user
scenarios and ordinary valuation generation remain available. No live model or
provider acceptance was performed.

## Remaining enforcement limitation

These are tested prompt requirements, not deterministic numerical validation.
The existing interfaces carry prose evidence and free-form user assumptions;
an empty evidence list alone does not prove that a scenario lacks inputs.
A blanket unavailable guard would disable supported user scenarios, while
parsing arbitrary prose numbers into trusted operands would invent trust.
Neither is implemented. A selective production enforcement contract remains
open: it needs explicit validated operand/scenario provenance, a defined
calculation relationship and treatment of the existing assumption ranges.
Current price/multiple observation dates, forecast periods and numerical
historical analogs still require real source adjudication. No completion claim
for valuation/expected returns or launch readiness follows from these tests.
