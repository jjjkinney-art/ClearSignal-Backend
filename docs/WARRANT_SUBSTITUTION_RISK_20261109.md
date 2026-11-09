# FMSTW to FMST substitution risk (recorded; not changed in this branch)

Status: a risk record only. Warrant routing is **not** changed by `fix/registration-only-blank-sic`, and cohort 6 is unchanged.

## What is known (offline, from the retained directory and the code)
- SEC's retained directory lists `FMST` and `FMSTW` under one CIK (1935418), both titled "Foremost Clean Energy Ltd.". It holds only ticker, CIK and
  title per row; nothing states that `FMSTW` is a warrant. The "W" is a naming convention, not evidence.
- A name-only question (cohort 6's FMSTW cases) resolves to **no company**: with two unsuffixed symbols under one CIK the resolver treats them as two share
  classes and abstains; only `…F` foreign ordinary lines are discounted. Both cases are `identity_unresolved` as registered. Naming `FMSTW` resolves to
  `FMSTW`; naming `FMST` resolves to `FMST`.

## The substitution risk
`validation/ordinary_native_ledger.py::answer_names_issuer` accepts an answer whose company is any ticker the retained directory lists under the case's
registered CIK. That rule was added so FORFF could be answered as FTS and IFCNF as IFHLY. For case `FMSTW:core_thesis` it would therefore also **accept an
answer about `FMST`**, which would be a different security (common stock) answered under a warrant's case id, with nothing flagging it.

## What this branch does not do
It does not change identity resolution, `answer_names_issuer`, or how a warrant is described. Any fix needs its own proposal, tests and approval:
a warrant-sibling test that refuses `FMST` for case `FMSTW`, and an answer that keeps the requested symbol and states that company data describes the
issuer, not the security.
