"""
Keyword-based concern extractor.

Maps question text and thesis content to canonical concern tag names.
No LLM is involved — pure keyword matching against a curated taxonomy.

Usage::

    from app.db.concern_extractor import extract_concerns

    tags = extract_concerns(
        question="What is the CRE loan loss threshold for JPM?",
        bull_thesis="Strong reserve coverage...",
        bear_thesis="Office delinquency rates rising...",
    )
    # tags == {"cre_credit_risk", "interest_rate_risk"}

Tag taxonomy
------------
Each tag is a canonical string identifier.  Tags are stable — never renamed
after initial definition to preserve historical counts in concern_tags table.
"""

from __future__ import annotations

import re
from typing import Dict, FrozenSet, Set

# ---------------------------------------------------------------------------
# Taxonomy: canonical tag → keyword/phrase patterns (lowercase)
# ---------------------------------------------------------------------------
# Each pattern is matched against the lowercased concatenated input.
# Longer, more specific phrases should appear before shorter substrings
# to ensure correct coverage reporting — but the matching is independent
# per tag so order within a list does not affect correctness.

_TAXONOMY: Dict[str, FrozenSet[str]] = {
    "cre_credit_risk": frozenset([
        "commercial real estate", "cre loan", "office loan",
        "cre default", "office default", "office delinquency",
        "loan loss", "reserve build", "provision coverage",
        "cre exposure", "cre portfolio",
    ]),
    "geopolitical_risk": frozenset([
        "geopolit", "taiwan strait", "china invasion", "military escalation",
        "taiwan", "china risk", "strait", "tariff", "trade war",
        "sanctions", "export control", "cross-strait",
    ]),
    "margin_pressure": frozenset([
        "margin compression", "margin pressure", "gross margin",
        "operating margin", "margin expansion", "margin contraction",
        "cost pressure", "cogs", "merchandise mix",
    ]),
    "capex_cycle": frozenset([
        "capex", "capital expenditure", "infrastructure spend",
        "hyperscaler capex", "data center capex", "capex cycle",
        "capex deceleration", "capex growth", "overinvestment",
    ]),
    "interest_rate_risk": frozenset([
        "interest rate", "fed rate", "federal reserve",
        "rate hike", "rate cut", "yield curve", "treasury yield",
        "inflation", "cpi", "monetary policy", "net interest margin",
        "nim", "rate sensitivity",
    ]),
    "regulatory_risk": frozenset([
        "regulation", "antitrust", "doj", "ftc", "sec investigation",
        "regulatory pressure", "compliance", "app store fee",
        "dma", "digital markets act", "regulatory",
    ]),
    "competitive_risk": frozenset([
        "competition", "competitor", "market share", "competitive threat",
        "market position", "share loss", "customer churn",
        "pricing power erosion",
    ]),
    "supply_chain_risk": frozenset([
        "supply chain", "supply shortage", "inventory", "chip shortage",
        "semiconductor supply", "lead time", "production delay",
        "manufacturing constraint",
    ]),
    "valuation_risk": frozenset([
        "valuation", "premium valuation", "price-to-earnings",
        "pe multiple", "price multiple", "overvalued", "overpaid",
        "consensus estimate", "re-rating", "de-rating",
        "earnings revision",
    ]),
    "currency_risk": frozenset([
        "currency", "foreign exchange", "fx risk", "exchange rate",
        "dollar strength", "dollar weakness", "yen", "euro",
        "cross-border revenue", "fx headwind",
    ]),
    "macro_slowdown_risk": frozenset([
        "recession", "economic slowdown", "gdp", "macro environment",
        "consumer spending", "consumer confidence", "credit cycle",
        "unemployment", "macro risk", "soft landing", "hard landing",
    ]),
    "ai_adoption_risk": frozenset([
        "ai adoption", "artificial intelligence", "ai substitution",
        "ai cannibalization", "llm", "large language model",
        "ai-native", "perplexity", "chatgpt substitution",
        "ai search", "ai query",
    ]),
    "concentration_risk": frozenset([
        "customer concentration", "revenue concentration",
        "top customer", "single customer", "hyperscaler dependence",
        "four customers", "61%", "segment concentration",
    ]),
    "att_privacy_risk": frozenset([
        "att", "app tracking transparency", "apple privacy",
        "idfa", "signal loss", "measurement loss",
        "attribution", "cpm decline", "ad targeting",
    ]),
}

# Pre-compile: tag → list of (pattern, compiled_regex)
_COMPILED: Dict[str, list] = {}
for _tag, _patterns in _TAXONOMY.items():
    _COMPILED[_tag] = [re.compile(re.escape(p), re.IGNORECASE) for p in _patterns]


def extract_concerns(
    question: str = "",
    bull_thesis: str = "",
    bear_thesis: str = "",
    verdict_rationale: str = "",
    direct_answer: str = "",
) -> Set[str]:
    """Return the set of canonical concern tag names found in the input text.

    Parameters
    ----------
    question:
        The user's original question (highest signal).
    bull_thesis:
        Bull-thesis text from the InvestmentThesis.
    bear_thesis:
        Bear-thesis text from the InvestmentThesis.
    verdict_rationale:
        Verdict rationale text.
    direct_answer:
        Direct-answer text.

    Returns
    -------
    Set[str]
        Zero or more canonical tag names (e.g. ``{"cre_credit_risk", "interest_rate_risk"}``).
    """
    corpus = " ".join([
        question,
        bull_thesis,
        bear_thesis,
        verdict_rationale,
        direct_answer,
    ]).lower()

    found: Set[str] = set()
    for tag, patterns in _COMPILED.items():
        for pat in patterns:
            if pat.search(corpus):
                found.add(tag)
                break  # one match per tag is enough

    return found


def dominant_concern(concern_counts: Dict[str, int]) -> str:
    """Return the tag name with the highest mention count.

    Parameters
    ----------
    concern_counts:
        Mapping of tag_name → total mention count from the concern_tags table.

    Returns
    -------
    str
        Tag name with highest count, or empty string if the dict is empty.
    """
    if not concern_counts:
        return ""
    return max(concern_counts, key=lambda k: concern_counts[k])
