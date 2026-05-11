"""Valuation specialist agent.

Focuses on valuation multiples, growth trajectory, margin trends,
discount-rate sensitivity, and relative valuation vs sector peers.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..schemas import CompanyContext, ValuationView, RetrievedEvidence
from ..structured_output import get_structured_response
from ..model_client import model_client
from ..config import settings

logger = logging.getLogger(__name__)

_AGENT_NAME = "valuation_agent"

_EVIDENCE_KEYWORDS = [
    "income",
    "revenue",
    "earnings",
    "eps",
    "p/e",
    "margin",
    "profitability",
    "financial",
    "fmp",
    "price change",
    "stock price",
]


def _filter_evidence(
    evidence: List[RetrievedEvidence],
    company: CompanyContext,
) -> List[RetrievedEvidence]:
    """Return evidence items relevant to this agent's valuation domain.

    Matches on title OR source containing any keyword (case-insensitive).
    Evidence whose title contains the company ticker or name is always included.
    """
    ticker_lower = company.ticker.lower()
    name_lower = company.company_name.lower()
    alias_lowers = [a.lower() for a in company.aliases]

    relevant: List[RetrievedEvidence] = []
    seen_titles: set = set()

    for ev in evidence:
        title_lower = ev.title.lower()
        source_lower = ev.source.lower()

        # Always include company-specific evidence
        is_company_match = (
            ticker_lower in title_lower
            or name_lower in title_lower
            or any(alias in title_lower for alias in alias_lowers)
        )

        # Domain keyword match on title or source
        is_keyword_match = any(
            kw in title_lower or kw in source_lower
            for kw in _EVIDENCE_KEYWORDS
        )

        if (is_company_match or is_keyword_match) and ev.title not in seen_titles:
            relevant.append(ev)
            seen_titles.add(ev.title)

    return relevant


def _empty_output(reason: str = "") -> ValuationView:
    return ValuationView(
        overall=f"Insufficient evidence for valuation analysis. {reason}".strip(),
        confidence=0.0,
    )


def _build_prompt(company: CompanyContext, evidence: List[RetrievedEvidence]) -> str:
    """Build the valuation agent prompt."""
    evidence_block = "\n".join(
        f"[{i + 1}] {ev.title}\n    Source: {ev.source}\n    {ev.summary}"
        for i, ev in enumerate(evidence)
    )
    sector_line = f"Sector: {company.sector}" if company.sector else ""
    industry_line = f"Industry: {company.industry}" if company.industry else ""
    context_lines = "\n".join(filter(None, [sector_line, industry_line]))

    return f"""You are a specialist valuation analyst. Analyse {company.company_name} ({company.ticker}).
{context_lines}

EVIDENCE:
{evidence_block}

Produce a JSON object matching the ValuationView schema with these fields:
- pe_assessment: P/E ratio vs sector history and peers
- growth_view: Revenue and EPS growth trajectory from the evidence
- margin_trend: Operating and net margin trend
- discount_sensitivity: How sensitive the valuation is to discount-rate moves
- relative_value: Relative value vs sector peers
- overall: One concise paragraph summarising the valuation
- confidence: 0.0-1.0 based on evidence completeness

Rules:
- Cite evidence numbers (e.g. [1], [2]) in your text.
- Be specific — no generic placeholders or invented figures.
- Return ONLY valid JSON, no markdown fences or prose outside the JSON object.

JSON:"""


def run_valuation_agent(
    company: CompanyContext,
    evidence: List[RetrievedEvidence],
    request_id: Optional[str] = None,
) -> ValuationView:
    """Run the valuation specialist agent.

    Filters evidence to valuation-relevant items, builds a focused prompt,
    calls the LLM via get_structured_response, and returns a ValuationView.
    Degrades gracefully if evidence is empty or the LLM call fails.
    """
    relevant = _filter_evidence(evidence, company)
    print(
        f"[DIAG] [{_AGENT_NAME}] ticker={company.ticker} "
        f"relevant_evidence={len(relevant)}/{len(evidence)}"
    )

    if not relevant:
        return _empty_output("No valuation-relevant evidence available.")

    prompt = _build_prompt(company, relevant)
    try:
        result: ValuationView = get_structured_response(
            prompt,
            ValuationView,
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
