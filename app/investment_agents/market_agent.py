"""Market context specialist agent.

Focuses on recent news catalysts, price momentum, analyst sentiment,
and institutional/retail positioning signals.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..schemas import CompanyContext, MarketContext, RetrievedEvidence
from ..structured_output import get_structured_response
from ..model_client import model_client
from ..config import settings

logger = logging.getLogger(__name__)

_AGENT_NAME = "market_agent"

_EVIDENCE_KEYWORDS = [
    "news",
    "newsapi",
    "bloomberg",
    "reuters",
    "cnbc",
    "catalyst",
    "guidance",
    "earnings beat",
    "earnings miss",
    "analyst",
    "upgrade",
    "downgrade",
    "price change",
]


def _filter_evidence(
    evidence: List[RetrievedEvidence],
    company: CompanyContext,
) -> List[RetrievedEvidence]:
    """Return evidence items relevant to this agent's market-context domain.

    Matches on title OR source containing any keyword (case-insensitive).
    Evidence whose title contains the company ticker or name is always included
    to capture company-specific news and price events.
    """
    ticker_lower = company.ticker.lower()
    name_lower = company.company_name.lower()
    alias_lowers = [a.lower() for a in company.aliases]

    relevant: List[RetrievedEvidence] = []
    seen_titles: set = set()

    for ev in evidence:
        title_lower = ev.title.lower()
        source_lower = ev.source.lower()

        is_company_match = (
            ticker_lower in title_lower
            or name_lower in title_lower
            or any(alias in title_lower for alias in alias_lowers)
        )

        is_keyword_match = any(
            kw in title_lower or kw in source_lower
            for kw in _EVIDENCE_KEYWORDS
        )

        if (is_company_match or is_keyword_match) and ev.title not in seen_titles:
            relevant.append(ev)
            seen_titles.add(ev.title)

    return relevant


def _empty_output(reason: str = "") -> MarketContext:
    return MarketContext(
        overall=f"Insufficient evidence for market context analysis. {reason}".strip(),
        confidence=0.0,
    )


def _build_prompt(company: CompanyContext, evidence: List[RetrievedEvidence]) -> str:
    """Build the market context agent prompt."""
    evidence_block = "\n".join(
        f"[{i + 1}] {ev.title}\n    Source: {ev.source}\n    {ev.summary}"
        for i, ev in enumerate(evidence)
    )
    sector_line = f"Sector: {company.sector}" if company.sector else ""
    industry_line = f"Industry: {company.industry}" if company.industry else ""
    context_lines = "\n".join(filter(None, [sector_line, industry_line]))

    return f"""You are a specialist market analyst. Analyse {company.company_name} ({company.ticker}).
{context_lines}

EVIDENCE (recent news, price data, analyst commentary):
{evidence_block}

Based on the news and market evidence above, assess the following:
- What are the most important recent catalysts (earnings surprises, guidance changes, M&A, regulatory events)?
- What does price momentum and recent price action signal about the stock's near-term direction?
- What is the prevailing analyst and market sentiment — are upgrades/downgrades clustering?
- What do positioning signals (short interest, institutional flows, options activity) suggest?

Produce a JSON object matching the MarketContext schema with these fields:
- recent_catalysts: Array of key catalysts from recent news (each a concise string)
- momentum: Price momentum and technical positioning assessment
- sentiment: Analyst and market sentiment summary
- positioning: Institutional and retail positioning signals
- overall: One concise paragraph summarising the current market context
- confidence: 0.0-1.0 based on evidence completeness

Rules:
- Cite evidence numbers (e.g. [1], [2]) in your text.
- Be specific — no generic placeholders or invented figures.
- recent_catalysts must be a JSON array of strings.
- Return ONLY valid JSON, no markdown fences or prose outside the JSON object.

JSON:"""


def run_market_agent(
    company: CompanyContext,
    evidence: List[RetrievedEvidence],
    request_id: Optional[str] = None,
) -> MarketContext:
    """Run the market context specialist agent.

    Filters evidence to news and market-relevant items, builds a focused prompt,
    calls the LLM via get_structured_response, and returns a MarketContext.
    Degrades gracefully if evidence is empty or the LLM call fails.
    """
    relevant = _filter_evidence(evidence, company)
    print(
        f"[DIAG] [{_AGENT_NAME}] ticker={company.ticker} "
        f"relevant_evidence={len(relevant)}/{len(evidence)}"
    )

    if not relevant:
        return _empty_output("No market-context-relevant evidence available.")

    prompt = _build_prompt(company, relevant)
    try:
        result: MarketContext = get_structured_response(
            prompt,
            MarketContext,
            model_client,
            max_retries=settings.model_max_retries,
            backoff_factor=settings.model_backoff_factor,
        )
        result.evidence_used = [ev.title[:70] for ev in relevant]
        return result
    except Exception as exc:
        logger.warning(
            "[%s] LLM call failed for %s: %r",
            _AGENT_NAME,
            company.ticker,
            exc,
        )
        return _empty_output(f"LLM error: {exc}")
