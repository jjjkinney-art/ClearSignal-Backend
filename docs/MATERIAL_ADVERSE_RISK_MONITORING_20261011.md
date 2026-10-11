# Preserve monitoring for bound risk mechanisms

The accepted explicit-mechanism fixture in `test_thesis_disclosures.py` includes
“Supply chain disruptions could materially adversely affect our liquidity and
operating results.” Existing source binding admits this sentence, but conditional
monitoring recognized only the unqualified “adversely affect” form. The modifier
therefore removed the useful condition/effect interpretation.

The grammar now also recognizes exactly `could materially adversely affect` and
`may materially adversely affect`. Original bound quotes and condition/effect
fragments remain intact. Materiality is the issuer's wording, not an independent
assessment. No risk ranking, likelihood, threshold, financial attribution or
valuation conclusion is introduced. Nested modal conditions, negations and
forecast statements remain outside the grammar. Historical predecessor output
still requires current successor relevance confirmation.

Acceptance covers both modals through extraction, binding, reference admission
and the final source-answer gate; exact source spans, unchanged partial status,
zero assessed confidence, unresolved materiality/likelihood/impact, tampered
claims and missing references. Socket guards prohibit network in the new gate
cases. This is synthetic regression evidence, not live answer-quality acceptance.

An additional reproduced omission affected short explicit subjects: “Cyberattacks”
and “Loan defaults” passed source binding but were below the monitoring parser's
15-character minimum. Monitoring now requires a lexical subject instead of that
arbitrary minimum. Empty, whitespace-only, punctuation-only and one-letter
subjects remain excluded, as do unresolved demonstrative/pronoun subjects.
The 500-character maximum and nested-modal exclusions remain. Tests exercise
both subjects through extraction, binding and the final answer gate with both
modals and with/without the materiality modifier; negative cases include unresolved
subjects, nested forecasts and the length limit.

This bounded repair implements part of the conditional-monitoring work recorded
in `CITED_RISK_MONITORING_20261011.md`. The broader risk-relevance and representative
company adjudication gaps remain open. Live verification is deferred.
