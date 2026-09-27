"""Deterministic claim-to-source responses for explicit source questions."""

from __future__ import annotations

import re
from typing import Iterable


_SOURCE_REQUEST_RE = re.compile(
    r"\b(which source|what source|sources? supports?|cite|citation|pieces? of .*evidence)\b",
    re.IGNORECASE,
)
_LEGACY_SOURCE_RE = re.compile(r"\s*\[Source:\s*https?://[^\]]+\]\s*", re.IGNORECASE)


def _claim_text(item: object) -> str | None:
    source = str(getattr(item, "source", "") or "")
    summary = str(getattr(item, "summary", "") or "").strip()
    # Filing-discovery metadata proves only that a filing exists. It is not an
    # extracted fact and cannot support a business claim.
    if source == "SEC EDGAR" and (
        " filed a " in summary or "filings contain" in summary
    ):
        return None
    summary = _LEGACY_SOURCE_RE.sub(" ", summary)
    summary = re.sub(r"\s+", " ", summary).strip()
    return summary[:500] if len(summary) >= 30 else None


def apply_source_answer_gate(thesis: object, question: str, items: Iterable[object]) -> dict | None:
    """Bind source-demand answers to retrieved evidence or fail closed."""
    if not _SOURCE_REQUEST_RE.search(question or ""):
        return None

    claims: list[dict] = []
    for index, item in enumerate(items, start=1):
        claim = _claim_text(item)
        if not claim:
            continue
        claims.append({
            "claim": claim,
            "reference_id": f"E{index}",
        })
        if len(claims) == 3:
            break

    requested_three = bool(re.search(r"\b(?:three|3)\b", question, re.IGNORECASE))
    enough = len(claims) >= (3 if requested_three else 1)
    if not enough:
        answer = (
            "ClearSignal retrieved source records, but this run did not extract "
            "enough claim-level evidence to answer the question with reliable "
            "claim-to-source attribution. Review the linked filings directly or "
            "run the analysis again when structured facts are available."
        )
        setattr(thesis, "direct_answer", answer)
        return {
            "status": "insufficient_claim_evidence",
            "reason": "Retrieved filing metadata is not claim-level support.",
            "claims": [],
        }

    answer = " ".join(
        f"{number}. {row['claim']} [{row['reference_id']}]"
        for number, row in enumerate(claims, start=1)
    )
    setattr(thesis, "direct_answer", answer)
    return {
        "status": "attributed",
        "reason": "Each claim is bound to a retrieved evidence reference.",
        "claims": claims,
    }
