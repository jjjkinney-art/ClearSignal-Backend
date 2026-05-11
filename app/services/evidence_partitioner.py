"""Centralised evidence partitioner that splits the full evidence pool into
per-agent subsets.

Each specialist agent (Valuation, Macro, Risk, Market, Quality) has a
distinct evidence appetite.  Routing all evidence to every agent is wasteful
and can dilute signal.  This module provides a single :func:`partition_evidence`
entry-point that classifies each :class:`~app.schemas.RetrievedEvidence` item
into one or more agent-specific pools based on source provenance and title
keyword matching.

Items may appear in multiple pools (e.g. an FMP income statement is relevant
to both Valuation and Quality).  Company-specific items (where the company
ticker or name appears in the evidence title) are broadcast to all five pools.

Public API
----------
partition_evidence(evidence, company) → EvidencePartition

EvidencePartition
-----------------
Dataclass with five typed lists (valuation, macro, risk, market, quality)
plus helper properties ``all_unique`` and ``total_items()``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from ..schemas import CompanyContext, RetrievedEvidence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword / source routing tables
# ---------------------------------------------------------------------------

# Source name substrings that route evidence to specific pools.
# Matching is case-insensitive on the ``source`` field.
_VALUATION_SOURCES: tuple[str, ...] = ("fmp", "morningstar")
_MACRO_SOURCES: tuple[str, ...] = ("federal reserve", "fred", "st. louis fed", "stlouisfed")
_RISK_SOURCES: tuple[str, ...] = ("sec edgar", "sec", "edgar")
_MARKET_SOURCES: tuple[str, ...] = ("newsapi", "bloomberg", "reuters", "cnbc", "ap news", "associated press")
_QUALITY_SOURCES: tuple[str, ...] = ("fmp",)  # Company profile endpoint is FMP

# Title keyword substrings for each pool.
# Matching is case-insensitive on the ``title`` field.
_VALUATION_TITLE_KEYWORDS: tuple[str, ...] = (
    "income",
    "revenue",
    "earnings",
    "eps",
    "p/e",
    "margin",
    "profitability",
    "financial",
    "price change",
    "stock price",
    "valuation",
    "balance sheet",
)

_MACRO_TITLE_KEYWORDS: tuple[str, ...] = (
    "treasury",
    "yield",
    "inflation",
    "cpi",
    "pce",
    "fed funds",
    "federal reserve",
    "recession",
    "gdp",
    "vix",
    "credit spread",
    "t10y2y",
    "dgs",
    "interest rate",
)

_RISK_TITLE_KEYWORDS: tuple[str, ...] = (
    "10-k",
    "10-q",
    "annual report",
    "quarterly report",
    "filing",
    "debt",
    "liability",
    "leverage",
    "risk factor",
    "regulation",
    "lawsuit",
    "litigation",
)

_MARKET_TITLE_KEYWORDS: tuple[str, ...] = (
    "news",
    "catalyst",
    "guidance",
    "earnings beat",
    "earnings miss",
    "analyst",
    "upgrade",
    "downgrade",
    "price target",
    "momentum",
)

_QUALITY_TITLE_KEYWORDS: tuple[str, ...] = (
    "profile",
    "business model",
    "free cash flow",
    "fcf",
    "buyback",
    "dividend",
    "r&d",
    "research",
    "intellectual property",
    "subscription",
    "recurring",
    "moat",
)


def _source_matches(evidence: RetrievedEvidence, patterns: tuple[str, ...]) -> bool:
    """Return True if the evidence source (lowercased) contains any pattern."""
    src = evidence.source.lower()
    return any(p in src for p in patterns)


def _title_matches(evidence: RetrievedEvidence, keywords: tuple[str, ...]) -> bool:
    """Return True if the evidence title (lowercased) contains any keyword."""
    title = evidence.title.lower()
    return any(kw in title for kw in keywords)


def _title_has_macro_keywords(evidence: RetrievedEvidence) -> bool:
    """Convenience check — used to exclude macro-labelled items from Valuation pool."""
    return _title_matches(evidence, _MACRO_TITLE_KEYWORDS)


# ---------------------------------------------------------------------------
# EvidencePartition dataclass
# ---------------------------------------------------------------------------

@dataclass
class EvidencePartition:
    """Container for per-agent evidence pools produced by :func:`partition_evidence`.

    Pools are not mutually exclusive — the same evidence item may appear in
    multiple pools when it is relevant to more than one agent.

    Attributes
    ----------
    valuation:
        Evidence relevant to the Valuation specialist (P/E, margins, financials).
    macro:
        Evidence relevant to the Macro specialist (FRED series, yield curve, inflation).
    risk:
        Evidence relevant to the Risk specialist (SEC filings, debt, litigation).
    market:
        Evidence relevant to the Market specialist (news, catalysts, guidance).
    quality:
        Evidence relevant to the Quality specialist (FCF, moat, capital allocation).
    """

    valuation: List[RetrievedEvidence] = field(default_factory=list)
    macro: List[RetrievedEvidence] = field(default_factory=list)
    risk: List[RetrievedEvidence] = field(default_factory=list)
    market: List[RetrievedEvidence] = field(default_factory=list)
    quality: List[RetrievedEvidence] = field(default_factory=list)

    @property
    def all_unique(self) -> List[RetrievedEvidence]:
        """All evidence items deduplicated (union across all five pools).

        De-duplication is performed by object identity (``id()``), so the same
        :class:`~app.schemas.RetrievedEvidence` instance appearing in multiple
        pools is counted once.  Order is preserved (valuation → macro → risk →
        market → quality).
        """
        seen: set[int] = set()
        result: List[RetrievedEvidence] = []
        for pool in (self.valuation, self.macro, self.risk, self.market, self.quality):
            for item in pool:
                oid = id(item)
                if oid not in seen:
                    seen.add(oid)
                    result.append(item)
        return result

    def total_items(self) -> int:
        """Total item count across all pools, counting duplicates (cross-pool items)."""
        return (
            len(self.valuation)
            + len(self.macro)
            + len(self.risk)
            + len(self.market)
            + len(self.quality)
        )


# ---------------------------------------------------------------------------
# Core routing logic
# ---------------------------------------------------------------------------

def partition_evidence(
    evidence: List[RetrievedEvidence],
    company: CompanyContext,
) -> EvidencePartition:
    """Route each evidence item to the most relevant agent pool(s).

    Parameters
    ----------
    evidence:
        Full list of :class:`~app.schemas.RetrievedEvidence` items retrieved
        for this analysis request.
    company:
        Resolved :class:`~app.schemas.CompanyContext` used to detect
        company-specific evidence items (by ticker or company name in title).

    Returns
    -------
    EvidencePartition
        A dataclass with five typed lists.  Items may appear in more than one
        pool.  Company-specific items appear in all five pools.

    Routing rules
    -------------
    VALUATION pool — FMP/Morningstar sources or title keywords covering financial
    statements, earnings, P/E, margins, and stock price; *excluding* items that
    also match macro keywords (yield, treasury, inflation, etc.).

    MACRO pool — FRED/Federal Reserve sources or title keywords covering
    treasury yields, inflation, CPI/PCE, Fed Funds, yield curve, VIX, GDP, and
    recession indicators.

    RISK pool — SEC EDGAR sources or title keywords covering regulatory filings
    (10-K, 10-Q), debt/leverage, litigation, and risk factors.

    MARKET pool — NewsAPI/Bloomberg/Reuters/CNBC sources or title keywords
    covering news catalysts, analyst actions, guidance, and price momentum.

    QUALITY pool — FMP company-profile source or title keywords covering FCF,
    buybacks, dividends, R&D, moat, and recurring revenue.

    Company-specific items — any item whose title contains the company ticker
    or company name is added to ALL five pools regardless of other routing.
    """
    partition = EvidencePartition()

    # Pre-compute lowercased company identifiers for fast matching
    ticker_lower = company.ticker.lower()
    name_lower = company.company_name.lower()

    for item in evidence:
        title_lower = item.title.lower()

        # ── Company-specific broadcast ────────────────────────────────────────
        is_company_specific = (
            ticker_lower in title_lower or name_lower in title_lower
        )
        if is_company_specific:
            partition.valuation.append(item)
            partition.macro.append(item)
            partition.risk.append(item)
            partition.market.append(item)
            partition.quality.append(item)
            logger.debug(
                "evidence_partitioner: '%s' → ALL pools (company-specific)", item.title
            )
            continue  # Already routed everywhere; skip per-pool checks

        # ── MACRO pool ────────────────────────────────────────────────────────
        routed_macro = False
        if _source_matches(item, _MACRO_SOURCES) or _title_matches(item, _MACRO_TITLE_KEYWORDS):
            partition.macro.append(item)
            routed_macro = True
            logger.debug("evidence_partitioner: '%s' → macro", item.title)

        # ── VALUATION pool ────────────────────────────────────────────────────
        # Exclude items that match macro keywords to avoid polluting the
        # Valuation agent with interest-rate series data.
        is_macro_labelled = routed_macro or _title_has_macro_keywords(item)
        if (
            not is_macro_labelled
            and (
                _source_matches(item, _VALUATION_SOURCES)
                or _title_matches(item, _VALUATION_TITLE_KEYWORDS)
            )
        ):
            partition.valuation.append(item)
            logger.debug("evidence_partitioner: '%s' → valuation", item.title)

        # ── RISK pool ─────────────────────────────────────────────────────────
        if _source_matches(item, _RISK_SOURCES) or _title_matches(item, _RISK_TITLE_KEYWORDS):
            partition.risk.append(item)
            logger.debug("evidence_partitioner: '%s' → risk", item.title)

        # ── MARKET pool ───────────────────────────────────────────────────────
        if _source_matches(item, _MARKET_SOURCES) or _title_matches(item, _MARKET_TITLE_KEYWORDS):
            partition.market.append(item)
            logger.debug("evidence_partitioner: '%s' → market", item.title)

        # ── QUALITY pool ──────────────────────────────────────────────────────
        if _source_matches(item, _QUALITY_SOURCES) or _title_matches(item, _QUALITY_TITLE_KEYWORDS):
            partition.quality.append(item)
            logger.debug("evidence_partitioner: '%s' → quality", item.title)

    logger.info(
        "evidence_partitioner: partitioned %d items into "
        "valuation=%d macro=%d risk=%d market=%d quality=%d (total_with_dupes=%d)",
        len(evidence),
        len(partition.valuation),
        len(partition.macro),
        len(partition.risk),
        len(partition.market),
        len(partition.quality),
        partition.total_items(),
    )

    return partition
