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


def normalize_value(value_text: Optional[str]) -> str:
    """Normalize a rendered figure for identity comparison.

    Strips trailing punctuation swept in by the extractor ("$200-220." ->
    "$200-220"), collapses whitespace, unifies dash variants, and lowercases —
    so cosmetic differences never split a genuine duplicate group, while the
    numeric content still distinguishes different figures.
    """
    text = (value_text or "").strip().lower()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[.,;:]+$", "", text)
    return text


def _identity_key(claim: Dict[str, Any]) -> tuple:
    """The semantic identity of a claim. Everything in this key is a reason two
    claims are genuinely DIFFERENT rather than a repeat of one another."""
    return (
        normalize_value(claim.get("value_text")),
        (claim.get("metric") or "").strip().lower(),
        (claim.get("provenance") or "").strip().lower(),
        (claim.get("unit") or "").strip().lower(),
        (claim.get("ticker") or "").strip().upper(),
        # Polarity is what keeps "above 25%" and "below 25%" apart. It is
        # stamped at extraction time from the surrounding prose.
        (claim.get("polarity") or "").strip().lower(),
        # Author-stated assumptions distinguish claims; an assumption the
        # extractor lifted from the surrounding text window does not — that
        # snippet varies with WHERE the figure appeared, so including it would
        # make every restatement look like a different claim.
        "" if claim.get("assumptions_inferred")
        else (claim.get("assumptions") or "").strip().lower(),
    )


def _compatible(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """True when two claims sharing an identity key can be merged.

    Source and as-of are handled here rather than in the identity key because
    they play two different roles.  A claim that omits a source is not a
    *different* claim from one that names it — it is the same claim carrying
    less metadata, and merging is what lets the sourced version win.  But two
    claims citing genuinely CONFLICTING sources (or different as-of dates) are
    distinct assertions and must both survive.
    """
    for field_name in ("source", "as_of"):
        x = (a.get(field_name) or "").strip().lower()
        y = (b.get(field_name) or "").strip().lower()
        if x and y and x != y:
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
        for field_name in ("source", "as_of", "unit", "confidence", "assumptions",
                           "derivation"):
            if not winner.get(field_name) and loser.get(field_name):
                winner[field_name] = loser[field_name]
        winner["occurrences"] = occurrences
        out[target] = winner

    return out
