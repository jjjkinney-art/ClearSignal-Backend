"""Deterministic, explainable cross-company structural ranking.

This service deliberately ranks *business quality*, not current expected return.
It consumes the same curated profiles and durability model used by the conviction
engine, so comparative answers cannot invent live prices or imply that a durable
business is automatically the best stock at today's valuation.
"""

from __future__ import annotations

import re
from typing import List

from ..schemas import (
    CompanyContext,
    ComparativeRankingEntry,
    ComparativeRankingResult,
    ValuationView,
)
from .company_knowledge import get_profile_for_company
from .conviction_modeler import (
    _build_valuation_reference,
    _compute_structured_durability,
    _get_uncertainty_drivers,
)


_COMPARATIVE_PATTERN = re.compile(
    r"\b(compare|comparison|versus|vs\.?|rank|ranking|better|best|choose|between)\b",
    re.IGNORECASE,
)


def is_comparative_question(question: str) -> bool:
    """Return whether the user explicitly asked for comparison or ranking."""
    return bool(_COMPARATIVE_PATTERN.search(question or ""))


def _quality_tier(score: float) -> str:
    if score >= 0.80:
        return "exceptional"
    if score >= 0.68:
        return "durable"
    if score >= 0.54:
        return "established"
    if score >= 0.38:
        return "mixed"
    return "speculative"


def _compact(text: str, *, max_chars: int = 220) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= max_chars:
        return clean
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    if sentences and len(sentences[0]) <= max_chars:
        return sentences[0]
    return clean[: max_chars - 1].rstrip() + "…"


def build_comparative_ranking(
    companies: List[CompanyContext],
    *,
    question: str = "",
) -> ComparativeRankingResult:
    """Rank companies on structural durability with an auditable explanation.

    Missing profiles rank last and are labeled rather than receiving a neutral
    default that could look like a real analytical score.
    """
    rows = []
    for input_position, company in enumerate(companies):
        profile = get_profile_for_company(company)
        if profile is None:
            score = 0.0
            advantage = "No curated structural profile is available."
            estimate_watch = ""
            valuation_reference = ""
            data_quality = "insufficient_profile"
        else:
            score = _compute_structured_durability(profile)
            advantage = _compact(
                profile.competitive_advantages[0]
                if profile.competitive_advantages
                else profile.business_model
            )
            drivers = _get_uncertainty_drivers(company)
            estimate_watch = drivers[0] if drivers else ""
            valuation_reference = _build_valuation_reference(ValuationView(), profile)
            data_quality = "profiled"

        rows.append({
            "input_position": input_position,
            "company": company,
            "score": round(score, 4),
            "advantage": advantage,
            "estimate_watch": estimate_watch,
            "valuation_reference": valuation_reference,
            "data_quality": data_quality,
        })

    rows.sort(key=lambda row: (-row["score"], row["input_position"]))
    entries = [
        ComparativeRankingEntry(
            rank=index,
            ticker=row["company"].ticker,
            company_name=row["company"].company_name,
            structural_quality_score=row["score"],
            quality_tier=_quality_tier(row["score"]),
            key_advantage=row["advantage"],
            estimate_watch=row["estimate_watch"],
            valuation_reference=row["valuation_reference"],
            data_quality=row["data_quality"],
        )
        for index, row in enumerate(rows, start=1)
    ]

    if not entries:
        return ComparativeRankingResult(
            summary="No companies were resolved for comparison.",
            caveats=["Name at least two supported companies or ticker symbols."],
        )

    spread = round(entries[0].structural_quality_score - entries[-1].structural_quality_score, 4)
    top_score = entries[0].structural_quality_score
    top_ties = [entry.ticker for entry in entries if entry.structural_quality_score == top_score]
    leader = entries[0].ticker if len(top_ties) == 1 else ""
    if len(entries) == 1:
        summary = (
            f"Only {entries[0].ticker} was resolved; at least two companies are required "
            "for a comparative ranking."
        )
    elif len(top_ties) > 1:
        summary = (
            f"{' and '.join(top_ties)} are tied on structural business quality at "
            f"{top_score:.2f}; current expected return requires live valuation evidence."
        )
    else:
        summary = (
            f"{entries[0].ticker} ranks first on structural business quality at "
            f"{entries[0].structural_quality_score:.2f}, versus "
            f"{entries[-1].ticker} at {entries[-1].structural_quality_score:.2f}."
        )

    caveats = [
        "This ranks structural business quality, not current expected return or a buy recommendation.",
        "Valuation references are curated frameworks labeled as non-live market data.",
        "Run current evidence-backed analysis on each company before making an allocation decision.",
    ]
    if re.search(r"\b(cheap|cheaper|valuation|value|overvalued|undervalued|price)\b", question, re.I):
        caveats.insert(
            0,
            "A live valuation winner cannot be determined without current price and estimate evidence.",
        )

    return ComparativeRankingResult(
        leader=leader,
        score_spread=spread,
        summary=summary,
        entries=entries,
        caveats=caveats,
    )
