# PE abbreviation boundaries

The existing direction classifier treated the letters `pe` anywhere in a metric
name as the P/E abbreviation. This overrode the existing higher-is-better margin
rule for `Operating margin` and could discard a coherent threshold band.

Require a whole token for the bare `PE` abbreviation. Preserve explicit `P/E`,
existing other metric rules and the parser's operator fallback for unknown names.
This is lexical disambiguation, not a new valuation or investment policy. Other
metric-direction heuristics and full operator-consistency validation remain
outside this bounded correction.

Regression tests exercise both direct inference and the active threshold builder.
