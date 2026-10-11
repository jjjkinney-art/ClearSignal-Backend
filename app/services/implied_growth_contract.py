"""Shared prompt requirements; not a deterministic calculation validator."""

IMPLIED_GROWTH_RULES = """IMPLIED-GROWTH EVIDENCE CONTRACT:
Before calculating, identify the supplied inputs and their provenance: current
multiple with earnings/revenue basis and observation date, an exact scenario
horizon and terminal multiple, and the required earnings endpoint. Show the
formula and assumptions. If required inputs are missing, explicitly say the
calculation is unavailable and name the missing inputs; do not invent numbers.
Do not force a CAGR, consensus gap or compression percentage from a multiple alone.
Existing conventions of 3–5 years, 10% discount and terminal P/E 20–25x are
scenario assumptions, not observed facts; do not silently select a point from
those ranges. Explicit user assumptions remain labeled user assumptions and
must not be treated as verified inputs or discarded in favor of the defaults.
Earnings CAGR is not revenue CAGR: revenue growth requires an explicit margin
and share-count bridge. Consensus comparisons require matching metric and
periods. Numerical historical analogs require supplied evidence, never training
knowledge. Do not infer expected stock returns from implied operating growth.
Discuss supported evidence qualitatively and distinguish unavailable calculation
from unavailable evidence; do not force a directional numerical verdict.
"""
