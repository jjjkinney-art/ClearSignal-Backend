"""Deterministic claim canonicalization / deduplication (Sprint 2B).

Sprint 2A's 36-query benchmark produced 19 ``duplicate_numerical_claim``
findings.  Inspecting the raw responses showed the cause is structural, not
stylistic: ``attach_agent_claims`` extracts from an agent's ``overall`` prose
AND from each of its ``signals``, and the same figure usually appears in both.
The resulting claim objects were byte-identical — e.g. Visa's ``100 bps``
macro claim at indices 4 and 8.

Deduplication here is by SEMANTIC IDENTITY, never by value alone.  Two claims
collapse only when value, metric, provenance, unit, ticker AND polarity all
agree, so these stay distinct:

  * the same figure describing different metrics ("25%" growth vs "25%" margin)
  * opposite-direction conditions on one figure ("above 25%" vs "below 25%")
  * the same number carrying materially different sourcing or assumptions

When a group does collapse, the most complete member survives (sourced over
unsourced, dated over undated, explicit unit over missing, higher confidence,
richer assumptions) so canonicalization never destroys metadata.  Output stays
schema-compatible; ``occurrences`` is the one additive field.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Ordering used to break ties on provenance when two group members are equally
# complete — the more specific/evidenced classification wins.
_PROVENANCE_RANK = {
    "reported": 5, "derived": 4, "estimated": 3, "scenario": 2, "heuristic": 1,
}
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


# Magnitude / unit spellings that denote the same quantity.  "40B", "40 billion"
# and "40bn" are one figure written three ways; folding them to a single token
# stops formatting alone from splitting a duplicate group.  Longest spellings
# are listed first so "bps" is consumed before the bare "b" alternative.
_UNIT_ALIASES = (
    (r"(?:basis\s*points?|bps|bp)\b", "bps"),
    (r"(?:trillions?|tn|t)\b", "t"),
    (r"(?:billions?|bn|b)\b", "b"),
    (r"(?:millions?|mm|m)\b", "m"),
    (r"(?:thousands?|k)\b", "k"),
)
_UNIT_ALIAS_RES = tuple((re.compile(p, re.IGNORECASE), rep) for p, rep in _UNIT_ALIASES)

# Currency symbols are presentation, not identity: "$40B" and "40B" are the same
# figure.  A genuine currency difference shows up in the `unit` field, which is
# compared separately.
_CURRENCY_SYMBOLS = "$€£¥₹"


def normalize_value(value_text: Optional[str]) -> str:
    """Normalize a rendered figure for identity comparison.

    Strips trailing punctuation swept in by the extractor ("$200-220." ->
    "$200-220"), removes whitespace and currency symbols, unifies dash variants,
    folds equivalent magnitude spellings ("40 billion"/"40bn"/"40B" -> "40b"),
    and lowercases — so formatting alone never splits a genuine duplicate group,
    while the numeric content still distinguishes different figures.
    """
    text = (value_text or "").strip().lower()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", "", text)
    text = text.strip(_CURRENCY_SYMBOLS)
    text = re.sub(r"[.,;:]+$", "", text)
    for pattern, replacement in _UNIT_ALIAS_RES:
        text = pattern.sub(replacement, text)
    return text


def normalize_unit(unit: Optional[str]) -> str:
    """Fold a unit string to the same canonical token as ``normalize_value``, so
    'B' and 'billion' are not read as two different units."""
    text = (unit or "").strip().lower()
    if not text:
        return ""
    text = text.strip(_CURRENCY_SYMBOLS)
    for pattern, replacement in _UNIT_ALIAS_RES:
        text = pattern.sub(replacement, text)
    return text


def _identity_key(claim: Dict[str, Any]) -> tuple:
    """The semantic identity of a claim. Everything in this key is a reason two
    claims are genuinely DIFFERENT rather than a repeat of one another."""
    return (
        normalize_value(claim.get("value_text")),
        (claim.get("metric") or "").strip().lower(),
        (claim.get("provenance") or "").strip().lower(),
        (claim.get("ticker") or "").strip().upper(),
        # Author-stated assumptions distinguish claims; an assumption the
        # extractor lifted from the surrounding text window does not — that
        # snippet varies with WHERE the figure appeared, so including it would
        # make every restatement look like a different claim.
        "" if claim.get("assumptions_inferred")
        else (claim.get("assumptions") or "").strip().lower(),
    )


def _compatible(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """True when two claims sharing an identity key can be merged.

    These fields sit here rather than in the identity key because an ABSENT
    value means "unknown", not "different".  A claim that omits a source is not
    a *different* claim from one that names it — it is the same claim carrying
    less metadata, and merging is what lets the richer version win.  Only two
    genuinely CONFLICTING non-null values make the claims distinct assertions.

    Sprint 2D: polarity and unit joined this rule.  The ASML benchmark shipped
    two byte-identical "40B" macro claims that differed only in polarity —
    "above" on the occurrence whose surrounding text happened to contain a
    directional cue, and null on the one that did not.  Null polarity is an
    undetected direction, not a third direction, so it must not split the pair;
    "above" versus "below" still does.
    """
    for field_name in ("source", "as_of", "polarity"):
        x = (a.get(field_name) or "").strip().lower()
        y = (b.get(field_name) or "").strip().lower()
        if x and y and x != y:
            return False
    # Units are compared on their canonical form so "B" and "billion" agree,
    # while two genuinely different explicit units stay apart.
    unit_a, unit_b = normalize_unit(a.get("unit")), normalize_unit(b.get("unit"))
    if unit_a and unit_b and unit_a != unit_b:
        return False
    return True


def _completeness_score(claim: Dict[str, Any]) -> tuple:
    """Rank a claim by how much verifiable metadata it carries. Higher is
    better; used to pick the survivor of a duplicate group."""
    return (
        1 if claim.get("source") else 0,
        1 if claim.get("as_of") else 0,
        1 if claim.get("unit") else 0,
        _CONFIDENCE_RANK.get((claim.get("confidence") or "").lower(), 0),
        1 if claim.get("assumptions") else 0,
        1 if claim.get("derivation") else 0,
        _PROVENANCE_RANK.get((claim.get("provenance") or "").lower(), 0),
        # Prefer a claim that explicitly acknowledges an undated source over one
        # that is silently undated.
        1 if claim.get("source_date_unavailable") else 0,
    )


def canonicalize_claims(claims: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Collapse semantically identical claims, preserving order of first
    appearance and keeping the most complete member of each group.

    Never raises: anything that is not a dict is passed through untouched so a
    malformed upstream payload degrades rather than breaking the response.
    """
    if not claims:
        return []

    # identity key -> positions in `out` sharing it (usually exactly one; more
    # only when sources genuinely conflict).
    groups: Dict[tuple, List[int]] = {}
    out: List[Dict[str, Any]] = []

    for claim in claims:
        if not isinstance(claim, dict):
            out.append(claim)
            continue

        key = _identity_key(claim)
        target = next(
            (pos for pos in groups.get(key, ()) if _compatible(claim, out[pos])), None,
        )
        if target is None:
            merged = dict(claim)
            merged["occurrences"] = 1
            groups.setdefault(key, []).append(len(out))
            out.append(merged)
            continue

        existing = out[target]
        occurrences = int(existing.get("occurrences") or 1) + 1
        newcomer_wins = _completeness_score(claim) > _completeness_score(existing)
        winner = dict(claim if newcomer_wins else existing)
        # Merging must never lose metadata: a field the winner lacks but the
        # other member supplies is carried across.
        loser = existing if newcomer_wins else claim
        # `polarity` is included so a merge of a directional occurrence with an
        # undetected one keeps the direction that was actually observed.
        for field_name in ("source", "as_of", "unit", "confidence", "assumptions",
                           "derivation", "polarity"):
            if not winner.get(field_name) and loser.get(field_name):
                winner[field_name] = loser[field_name]
        winner["occurrences"] = occurrences
        out[target] = winner

    return out
