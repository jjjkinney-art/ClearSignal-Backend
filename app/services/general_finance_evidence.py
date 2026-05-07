"""
General finance evidence retrieval service.

Architecture
------------
retrieve_general_finance_evidence(question) is the single public entry
point consumed by run_general_finance_agent() and
run_general_fallback_agent().  It returns a ranked list of
RetrievedEvidence objects that are injected into the LLM prompt as a
"Current Context" section, grounding the answer in recent developments
rather than model memory alone.

Current state: returns [] for all questions (safe placeholder).
The architecture is complete — wiring in a live provider requires only
implementing the TODO block below.  The prompt injection, quality guard,
and agent callers require no changes.

To add live retrieval
---------------------
1. Choose a provider:
   - FMP /market-news?limit=10&tickers={symbol}  (equity news)
   - FRED API (macro time-series: 10-year yield, CPI, Fed funds)
   - NewsAPI / Bing News Search (general macro headlines)
   - OpenAI / Cohere re-ranking for relevance scoring
2. Implement the provider call inside retrieve_general_finance_evidence().
3. Convert results to RetrievedEvidence objects, score by relevance, sort
   descending, return top N (3–5 is usually enough for one prompt).
4. The _format_evidence_section() in prompts.py handles rendering
   automatically; no prompt changes needed.

Test helpers
------------
_mock_evidence_for_question() returns pre-written mock evidence for
the four documented test cases.  Used by tests only — never called by
production code.  Remove the TODO block and add real retrieval to retire it.
"""

from __future__ import annotations

import logging
from typing import List

from ..schemas import RetrievedEvidence

logger = logging.getLogger(__name__)


# ── Public entry point ────────────────────────────────────────────────────────

def retrieve_general_finance_evidence(question: str) -> List[RetrievedEvidence]:
    """Retrieve grounding evidence for a general finance or fallback question.

    Called by run_general_finance_agent() and run_general_fallback_agent()
    before each LLM call.  The returned evidence is injected into the prompt
    as a "Current Context" section so the model can produce current-aware,
    evidence-grounded answers instead of relying solely on training memory.

    Parameters
    ----------
    question : str
        The user's question exactly as received (used for keyword matching
        and, eventually, semantic search / reranking).

    Returns
    -------
    List[RetrievedEvidence]
        Ranked list (highest relevance_score first), ready for injection.
        Returns [] when no evidence is available — the prompt falls back to
        conceptual reasoning automatically; no caller change required.
    """
    # ── TODO: replace with live provider calls ────────────────────────────────
    #
    # Example skeleton (FMP market news):
    #
    #   from ..providers import fmp_client
    #   raw = fmp_client.get("/market-news", params={"limit": 10})
    #   items = [
    #       RetrievedEvidence(
    #           title=item["title"],
    #           source=f"FMP / {item.get('site', 'unknown')}",
    #           summary=item.get("text", "")[:300],
    #           timestamp=item["publishedDate"][:10],
    #           relevance_score=_score_relevance(question, item["title"]),
    #       )
    #       for item in raw
    #   ]
    #   items.sort(key=lambda e: e.relevance_score, reverse=True)
    #   return items[:5]
    #
    # ─────────────────────────────────────────────────────────────────────────
    return []


# ── Test / development helpers ────────────────────────────────────────────────

def _mock_evidence_for_question(question: str) -> List[RetrievedEvidence]:
    """Return pre-written mock evidence for the four documented test cases.

    NOT called by production code.  Used exclusively by tests to verify
    that the evidence injection pipeline (retrieval → prompt injection →
    LLM call) works end-to-end with structurally correct evidence objects.

    Coverage
    --------
    - "Why are Treasury yields rising?"
    - "Why did tech stocks sell off today?"
    - "How does CPI affect rate expectations?"
    - "Why is Nvidia moving after earnings?"

    Each case returns 2 structurally correct RetrievedEvidence objects,
    ranked by relevance_score descending.
    """
    q = question.lower()

    # ── Treasury yields rising ────────────────────────────────────────────────
    if ("treasury" in q or "yield" in q) and (
        "rising" in q or "rise" in q or "why" in q or "higher" in q
    ):
        return [
            RetrievedEvidence(
                title="10-Year Treasury Yield Climbs to 4.8% on Strong Jobs Data",
                source="Reuters [mock]",
                summary=(
                    "The 10-year yield rose 15bps this week after non-farm payrolls beat "
                    "estimates by 80k jobs, reducing market expectations for near-term Fed "
                    "rate cuts from four cuts to two in 2024."
                ),
                timestamp="2024-01-15",
                relevance_score=0.95,
            ),
            RetrievedEvidence(
                title="Fed Minutes: Most Members Want Greater Confidence on Inflation",
                source="Federal Reserve [mock]",
                summary=(
                    "FOMC minutes showed members want more evidence that inflation is "
                    "sustainably moving toward 2% before cutting rates, pushing 10-year "
                    "yields higher as markets repriced the rate path."
                ),
                timestamp="2024-01-10",
                relevance_score=0.90,
            ),
        ]

    # ── Tech stocks sell-off ──────────────────────────────────────────────────
    if "tech" in q and (
        "sell" in q or "down" in q or "drop" in q or "today" in q or "off" in q
    ):
        return [
            RetrievedEvidence(
                title="Nasdaq Falls 2.4% as Rate Cut Hopes Fade After CPI Beat",
                source="Bloomberg [mock]",
                summary=(
                    "The Nasdaq Composite dropped 2.4% after December CPI came in at "
                    "3.4% vs 3.2% expected, pushing 10-year yields above 4.7% and "
                    "reducing 2024 rate cut expectations from six to four."
                ),
                timestamp="2024-01-11",
                relevance_score=0.93,
            ),
            RetrievedEvidence(
                title="High-Multiple Tech Names Underperform as Duration Risk Reprices",
                source="WSJ [mock]",
                summary=(
                    "Software and semiconductor names with P/E ratios above 40x fell "
                    "3–5%, while profitable mega-cap tech (Apple, Alphabet) held up "
                    "better — consistent with the duration sensitivity of high-growth "
                    "valuations to rising discount rates."
                ),
                timestamp="2024-01-11",
                relevance_score=0.87,
            ),
        ]

    # ── CPI and rate expectations ─────────────────────────────────────────────
    if "cpi" in q or (
        "inflation" in q and ("rate" in q or "expect" in q or "cut" in q)
    ):
        return [
            RetrievedEvidence(
                title="CPI Rises 3.4% YoY in December, Core Holds at 3.9%",
                source="Bureau of Labor Statistics [mock]",
                summary=(
                    "Headline CPI came in at 3.4% year-over-year vs 3.2% expected. "
                    "Core CPI (ex-food and energy) remained at 3.9%, suggesting services "
                    "inflation is proving stickier than the Fed's 2% target requires."
                ),
                timestamp="2024-01-11",
                relevance_score=0.97,
            ),
            RetrievedEvidence(
                title="Fed Funds Futures Reprice: March Cut Odds Fall from 73% to 48%",
                source="CME FedWatch [mock]",
                summary=(
                    "Following the hot CPI print, traders reduced bets on a March rate "
                    "cut from 73% to 48% probability. The implied number of 2024 cuts "
                    "fell from six to roughly four, lifting Treasury yields across the curve."
                ),
                timestamp="2024-01-11",
                relevance_score=0.94,
            ),
        ]

    # ── Nvidia post-earnings ──────────────────────────────────────────────────
    if "nvidia" in q or "nvda" in q:
        return [
            RetrievedEvidence(
                title="Nvidia Q4 Revenue $22.1B, Beats $20.4B Estimate by 8%; Guides Q1 to $24B",
                source="Nvidia Investor Relations [mock]",
                summary=(
                    "Nvidia reported Q4 FY2024 revenue of $22.1B, up 265% year-over-year. "
                    "Data center revenue of $18.4B was up 409% YoY, driven by hyperscaler "
                    "AI infrastructure buildout. Q1 FY2025 guidance of $24B beat the $21.9B "
                    "consensus by 10%."
                ),
                timestamp="2024-02-21",
                relevance_score=0.98,
            ),
            RetrievedEvidence(
                title="NVDA Surges 16%, Adds $277B Market Cap in Single Session",
                source="Bloomberg [mock]",
                summary=(
                    "Nvidia shares rose 16.4% on earnings day, adding the largest single-day "
                    "market cap gain in stock market history. The move reflected both the "
                    "beat-and-raise quarter and management commentary that AI demand shows "
                    "no sign of slowing across cloud providers and enterprises."
                ),
                timestamp="2024-02-22",
                relevance_score=0.95,
            ),
        ]

    return []
