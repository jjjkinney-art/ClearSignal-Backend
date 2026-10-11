# Shared competition sentence forms — 2026-10-11

PR250 deployed at `e757b670dd92f1670b3a4cefa7cbd3f405bca067`.
Its production capture included two ASML competition descriptions but none for
DOCU. Both core theses remained partial and quality was not adjudicated.

The actual DOCU 2026 annual filing was inspected and locally replayed through
the production HTML parser and section selection. The complete business and
risk sections retained the competition prose, but the existing producer
returned zero items. This was a grammatical admission gap, not missing text.

Source:
https://www.sec.gov/Archives/edgar/data/1261333/000126133326000021/docu-20260131.htm

Shared rules now admit singular principal/primary/main competitors, optional
global/regional/national qualifiers and product scope, plus current statements
of competition from other providers. A literal `Our Competition` or
`Competition` block heading can be removed only when the entire remaining
sentence qualifies. Exact source offsets start after that heading.

Forecasts, beliefs, self-rated advantages and numerical market shares remain
excluded. Workforce competition is excluded from product-market context.
No ticker-specific competitor list, additional fetch, or status relaxation is
introduced. Current issuer identity, provenance and final citation binding
remain required; predecessor handling is unchanged.

The same actual DOCU source now yields two bound, exact-span descriptions: the
principal eSignature competitor and vendors focused on particular markets.
Synthetic unseen-issuer tests cover these sentence forms, joined headings,
answer admission, and rejected forecasts/beliefs/workforce sentences.

After CI and deployment, retest DOCU and ASML to confirm both production
coverage and preservation of existing disclosures. Competitive strength,
valuation and risk assessment remain substantive gaps; the representative
100-company quality benchmark still follows those improvements.
