"""
Provider router for market and company evidence retrieval.

Public API
----------
retrieve_market_evidence(question, detected_topics, company=None)
    Route a question to appropriate external providers (FMP, SEC EDGAR, NewsAPI)
    and return a merged, ranked list of RetrievedEvidence objects.

Routing rules
-------------
+─────────────────────────┬───────────────────────────────────────────────────+
│ Signal                  │ Providers called                                  │
+─────────────────────────┼───────────────────────────────────────────────────+
│ company provided        │ FMP (financials) + SEC EDGAR (filings) +          │
│                         │ NewsAPI company headlines                          │
│ macro topics (no co.)   │ NewsAPI macro headlines                            │
│ company + macro topics  │ FMP + SEC + NewsAPI company + NewsAPI macro        │
│ neither                 │ NewsAPI general market headlines (fallback)        │
+─────────────────────────┴───────────────────────────────────────────────────+

This module is complementary to ``general_finance_evidence.retrieve_general_finance_evidence``,
which handles FRED macro data.  Together they cover:
  • FRED          — live macro time-series
  • FMP           — company financials and stock metrics
  • SEC EDGAR     — regulatory filings metadata
  • NewsAPI       — real-time headlines

FRED retrieval is NOT duplicated here.  Callers that want both macro and
company evidence should call both functions and merge results themselves,
or let the agent layer decide which to invoke.
"""

from __future__ import annotations

from typing import List, Optional

from ...schemas import RetrievedEvidence
from . import fmp_provider
from . import sec_provider
from . import news_provider

# Re-export the provider modules for direct import convenience.
__all__ = [
    "retrieve_market_evidence",
    "fmp_provider",
    "sec_provider",
    "news_provider",
]

# Maximum items in the final merged result.
# Company queries get a higher cap because they pull from 3 providers.
_CAP_COMPANY = 8
_CAP_MACRO   = 4


def retrieve_market_evidence(
    question: str,
    detected_topics: List[str],
    company: Optional[str] = None,
) -> List[RetrievedEvidence]:
    """Route *question* to appropriate providers and return merged evidence.

    Parameters
    ----------
    question : str
        The user's question (used for diagnostics / future NLP routing).
    detected_topics : list of str
        FRED topic names detected by ``_detect_topics()`` — used to drive
        macro news headline queries.
    company : str or None
        When provided, enables FMP + SEC + company-specific news retrieval.
        Accepts a ticker symbol (e.g. ``"AAPL"``) or a company name
        (e.g. ``"Apple Inc."``).

    Returns
    -------
    List[RetrievedEvidence]
        Merged, deduplicated, and relevance-sorted evidence list.
        Never raises — returns ``[]`` if all providers fail.
    """
    has_company = bool(company and company.strip())
    has_topics  = bool(detected_topics)

    print(
        f"[DIAG] MARKET EVIDENCE ROUTER: "
        f"company={company!r} topics={detected_topics} "
        f"has_company={has_company} has_topics={has_topics}"
    )

    evidence: List[RetrievedEvidence] = []

    if has_company:
        co = company.strip()  # type: ignore[union-attr]

        # ── Financial Modeling Prep ───────────────────────────────────────────
        fmp_items = fmp_provider.fetch_company_evidence(co)
        evidence.extend(fmp_items)
        print(f"[DIAG] MARKET EVIDENCE ROUTER: FMP contributed {len(fmp_items)} item(s)")

        # ── SEC EDGAR ────────────────────────────────────────────────────────
        sec_items = sec_provider.fetch_recent_filings(co)
        evidence.extend(sec_items)
        print(f"[DIAG] MARKET EVIDENCE ROUTER: SEC contributed {len(sec_items)} item(s)")

        # ── NewsAPI — company headlines ───────────────────────────────────────
        co_news = news_provider.fetch_company_news(co)
        evidence.extend(co_news)
        print(f"[DIAG] MARKET EVIDENCE ROUTER: NewsAPI/company contributed {len(co_news)} item(s)")

    if has_topics or not has_company:
        # ── NewsAPI — macro headlines ─────────────────────────────────────────
        # Called for pure macro queries (no company) and also for mixed
        # queries (company + macro topics) to add broader context.
        macro_news = news_provider.fetch_macro_news(detected_topics)
        evidence.extend(macro_news)
        print(f"[DIAG] MARKET EVIDENCE ROUTER: NewsAPI/macro contributed {len(macro_news)} item(s)")

    # ── Deduplicate ───────────────────────────────────────────────────────────
    seen: set = set()
    deduped: List[RetrievedEvidence] = []
    for ev in evidence:
        key = ev.title[:80].lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(ev)

    # ── Sort by relevance and cap ─────────────────────────────────────────────
    deduped.sort(key=lambda e: e.relevance_score, reverse=True)
    cap    = _CAP_COMPANY if has_company else _CAP_MACRO
    result = deduped[:cap]

    print(
        f"[DIAG] MARKET EVIDENCE ROUTER: "
        f"total={len(evidence)} → deduped={len(deduped)} → capped={len(result)} "
        f"(cap={cap})"
    )
    return result
