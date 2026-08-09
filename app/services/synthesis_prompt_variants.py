"""Synthesis-prompt variants and section measurement (Sprint 3B.1).

Sprint 3B established that the synthesis prompt is ~74k chars / ~18.6k tokens
and that ~95% of it is static instruction template, which is why synthesis is
the slowest stage on 34/36 benchmark queries. This module is the machinery for
reducing that safely.

Two design decisions shape everything here:

**A variant is a pure transform of the control prompt, not a second builder.**
118 test assertions across ten test files assert that specific instruction
strings appear in ``_build_synthesis_prompt``'s output. Forking the builder
would put every one of those guarantees at risk. Instead the control prompt is
built exactly as before and a variant is derived from it by deterministic
string consolidation, so ``control`` is byte-identical to production and the
existing suite keeps guarding it unchanged.

**Reductions are grouped by semantic cluster, not by size.** The blocks with
the heaviest overlap are the prose-style mandates — seven separate blocks all
instructing the model to vary sentence structure and avoid robotic phrasing.
Consolidating those preserves every distinct requirement while removing the
repetition. Analytic mandates (mechanism priority, priced-in reasoning,
confidence alignment, evidence provenance, expectation delta, the core market
debate) are decision-relevant and are never touched.

Nothing here selects a variant on its own — see ``resolve_variant``: a
non-control prompt requires the same authorization as Sprint 3A.1 profiling
detail, so no ordinary user can reach an experimental prompt.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

VARIANT_CONTROL = "control"
VARIANT_COMPACT_A = "compact_a"
VARIANT_COMPACT_A2 = "compact_a2"
VARIANT_COMPACT_B = "compact_b"

KNOWN_VARIANTS = (VARIANT_CONTROL, VARIANT_COMPACT_A, VARIANT_COMPACT_A2,
                  VARIANT_COMPACT_B)

# Rough English prose ratio. Used only for reporting an approximate token
# figure alongside an exact character count — never for a latency claim.
_CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    return int(len(text or "") / _CHARS_PER_TOKEN)


# ── Section measurement ──────────────────────────────────────────────────────
# Maps a block's leading header to a reporting group. Matching is on the first
# line of each blank-line-separated block, so a block whose header is unknown
# falls into "other" rather than being silently dropped — the section totals
# must always reconcile with the full prompt length.
_SECTION_GROUPS: List[tuple] = [
    ("output_schema", (r"required json fields", r"^\s*\"", r"sprint 1 intelligence fields")),
    ("direct_answer_rules", (r"direct answer", r"pre-synthesized direct answer",
                             r"approved openers", r"core market debate")),
    ("evidence_citation_rules", (r"evidence provenance", r"supporting evidence",
                                 r"signal diversity", r"citation")),
    ("bull_bear_requirements", (r"bull_thesis", r"bear_thesis",
                                r"cross-signal interaction")),
    ("valuation_rules", (r"valuation stance", r"dominant dimension", r"priced_in_reasoning",
                         r"expectation delta")),
    ("confidence_uncertainty_rules", (r"confidence language", r"selective incompleteness",
                                      r"implicit conviction")),
    ("threshold_rules", (r"threshold_zones", r"catalyst calendar")),
    ("integrity_contradiction_rules", (r"agent conflict", r"hidden-process ban",
                                       r"temporal realism", r"company specificity")),
    ("style_formatting_rules", (r"writing rhythm", r"naturalness", r"structural variety",
                                r"section asymmetry", r"pm-grade language",
                                r"institutional tone", r"market-native compression",
                                r"forbidden phrases", r"terminal density",
                                r"implication_compression", r"hierarchical density",
                                r"mechanism_priority", r"stock-movement orientation")),
    ("agent_summaries", (r"specialist agent outputs",)),
    ("dynamic_context", (r"thesis_evolution", r"instructions for this synthesis")),
]
_SECTION_RES = [
    (name, tuple(re.compile(p, re.IGNORECASE) for p in pats))
    for name, pats in _SECTION_GROUPS
]


def _classify_block(block: str) -> str:
    head = block.strip().split("\n", 1)[0].lower()
    for name, patterns in _SECTION_RES:
        if any(p.search(head) for p in patterns):
            return name
    return "other"


def measure_sections(prompt: str) -> Dict[str, Any]:
    """Character/token sizes per prompt section. Never returns prompt text.

    The per-section characters always sum to the full prompt length (blocks
    that match no known header land in ``other``), so a reader can trust the
    breakdown rather than wondering what is missing.
    """
    if not prompt:
        return {"total_chars": 0, "total_tokens": 0, "sections": []}

    blocks = prompt.split("\n\n")
    tally: Dict[str, int] = {}
    for i, block in enumerate(blocks):
        # Re-add the separator consumed by split so the totals reconcile.
        size = len(block) + (2 if i < len(blocks) - 1 else 0)
        tally[_classify_block(block)] = tally.get(_classify_block(block), 0) + size

    sections = [
        {"section": name, "chars": chars, "est_tokens": estimate_tokens("x" * chars)}
        for name, chars in sorted(tally.items(), key=lambda kv: -kv[1])
    ]
    return {
        "total_chars": len(prompt),
        "total_tokens": estimate_tokens(prompt),
        "sections": sections,
    }


# ── compact_a: low-risk consolidation ────────────────────────────────────────
# Seven blocks instruct the model, in different words, to write like a human
# portfolio manager: vary sentence length, avoid template openings, avoid
# robotic connectives, keep an institutional register. compact_a replaces them
# with one block that states each distinct requirement once.
#
# Every requirement below is carried over from the blocks it replaces. What is
# removed is the repetition and the worked examples, not the instruction.
_COMPACT_A_STYLE_HEADERS = (
    "WRITING RHYTHM AND CADENCE VARIATION — MANDATORY:",
    "NATURALNESS — MANDATORY:",
    "STRUCTURAL VARIETY — MANDATORY:",
    "SECTION ASYMMETRY — MANDATORY:",
    "PM-GRADE LANGUAGE — MANDATORY:",
    "INSTITUTIONAL TONE — MANDATORY:",
    "MARKET-NATIVE COMPRESSION — MANDATORY:",
)

_COMPACT_A_STYLE_REPLACEMENT = """PROSE STYLE — MANDATORY:
- Write as a portfolio manager, not a report generator. Institutional register throughout.
- Vary sentence length and structure; never open two sections with the same template.
- Vary section length — sections carrying more signal should be longer.
- No robotic connectives, no filler qualifiers, no restating the section title.
- Compress to market-native phrasing: say the thing, not the framing around it."""

# Three blocks instruct the model to compress implications and stop short of
# spelling out every consequence. They restate one idea.
_COMPACT_A_DENSITY_HEADERS = (
    "IMPLICATION_COMPRESSION — MANDATORY:",
    "TERMINAL DENSITY — MANDATORY:",
    "SELECTIVE INCOMPLETENESS — MANDATORY:",
)

_COMPACT_A_DENSITY_REPLACEMENT = """ANALYTICAL DENSITY — MANDATORY:
- State the implication, not the reasoning chain that produced it.
- End sections on the consequence that matters, not a summary restatement.
- Leave the obvious next inference to the reader; do not exhaust every branch."""


# ── compact_a2: conservative revision after the live A/B ─────────────────────
# The Sprint 3B.1A forensics showed compact_a was too aggressive. Reading the
# removed blocks line by line found they were not purely stylistic — three
# cross-cutting requirements were embedded in them and were dropped:
#
#   * STRUCTURAL VARIETY: "macro_sensitivity -> state the specific sensitivity
#     channel first, THEN MAGNITUDE"        -> NVDA lost its 10% USD move and
#                                              its ~5-8x compression figure.
#   * SECTION ASYMMETRY: "bear_thesis should be your MOST SPECIFIC, DETAILED
#     section"                              -> MSFT lost 20%, TSLA lost 10%,
#                                              both bear-case figures.
#   * SELECTIVE INCOMPLETENESS: "name the dominant factor AND MAGNITUDE, then
#     stop" / "name the specific tension, not the category"
#                                           -> generic metric substitution and
#                                              degraded thresholds on JPM/ASML.
#
# compact_a2 keeps the genuinely duplicated style wording consolidated but
# restores each of those requirements verbatim in intent. The reduction is
# smaller by design: a safe 7-8% beats an 11.2% that costs quantitative
# specificity.
_COMPACT_A2_STYLE_REPLACEMENT = """PROSE STYLE — MANDATORY:
- Write as a portfolio manager, not a report generator. Institutional register throughout.
- Vary sentence length and structure; never open two sections with the same template.
- bull_thesis MUST contain at least one sentence of 12 words or fewer.
- Sections are deliberately asymmetric: when one risk dominates, bear_thesis is your
  MOST SPECIFIC and most detailed section. Equal section lengths read as machine output.
- macro_sensitivity: state the specific sensitivity channel FIRST, then its MAGNITUDE.
- Name the specific mechanism, never the category ("pricing discipline", not "pricing power").
- No robotic connectives, no filler qualifiers, no restating the section title."""

_COMPACT_A2_DENSITY_REPLACEMENT = """ANALYTICAL DENSITY — MANDATORY:
- State the implication, not the reasoning chain that produced it.
- End sections on the consequence that matters, not a summary restatement.
- Name the dominant factor AND ITS MAGNITUDE, then stop — never end on a category.
- Do not hedge with symmetric balancing clauses ("could expand if X, but compress if Y");
  pick the more probable scenario and anchor it to a number.
- Leave the obvious next inference to the reader; do not exhaust every branch."""


def _replace_block_group(prompt: str, headers: tuple, replacement: str) -> str:
    """Remove every block whose header matches, then insert ``replacement``
    where the first one appeared, preserving prompt ordering."""
    blocks = prompt.split("\n\n")
    first_index: Optional[int] = None
    kept: List[str] = []
    for block in blocks:
        head = block.strip().split("\n", 1)[0].strip()
        if head in headers:
            if first_index is None:
                first_index = len(kept)
                kept.append(replacement)
            continue
        kept.append(block)
    return "\n\n".join(kept)


def apply_variant(prompt: str, variant: str) -> str:
    """Derive a variant prompt from the control prompt.

    ``control`` returns the input unchanged — byte-identical, so every existing
    assertion about the production prompt still holds. An unknown variant name
    is treated as control rather than raising: a bad flag must degrade to
    production behavior, never fail a request.
    """
    if not prompt or variant == VARIANT_CONTROL or variant not in KNOWN_VARIANTS:
        return prompt

    if variant == VARIANT_COMPACT_A2:
        out = _replace_block_group(prompt, _COMPACT_A_STYLE_HEADERS,
                                   _COMPACT_A2_STYLE_REPLACEMENT)
        return _replace_block_group(out, _COMPACT_A_DENSITY_HEADERS,
                                    _COMPACT_A2_DENSITY_REPLACEMENT)

    out = _replace_block_group(prompt, _COMPACT_A_STYLE_HEADERS,
                               _COMPACT_A_STYLE_REPLACEMENT)
    out = _replace_block_group(out, _COMPACT_A_DENSITY_HEADERS,
                               _COMPACT_A_DENSITY_REPLACEMENT)

    if variant == VARIANT_COMPACT_B:
        # compact_b is reserved for the SECOND A/B round and deliberately
        # applies no further reduction until compact_a has live quality
        # evidence. Stacking unverified reductions is exactly what the sprint
        # plan forbids.
        return out
    return out


def resolve_variant(requested: Optional[str], *, authorized: bool) -> str:
    """Resolve the synthesis variant for a request.

    Non-control variants require the same authorization as Sprint 3A.1
    profiling detail. An unauthorized caller — which is every ordinary user —
    always receives the production prompt, whatever they ask for.
    """
    if not authorized:
        return VARIANT_CONTROL
    name = str(requested or "").strip().lower()
    return name if name in KNOWN_VARIANTS else VARIANT_CONTROL
