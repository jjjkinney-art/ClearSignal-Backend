"""Quality specialist agent.

Focuses on competitive moat durability, management track record, capital-allocation
discipline, revenue durability (recurring vs one-time), and operating quality
(FCF conversion, margin consistency, asset intensity).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..schemas import CompanyContext, QualityAssessment, RetrievedEvidence
from ..structured_output import get_structured_response
from ..model_client import model_client
from ..config import settings

logger = logging.getLogger(__name__)

_AGENT_NAME = "quality_agent"

_EVIDENCE_KEYWORDS = [
    "profile",
    "company profile",
    "fmp",
    "business",
    "revenue",
    "free cash flow",
    "fcf",
    "buyback",
    "dividend",
    "r&d",
    "research",
    "intellectual property",
    "subscription",
    "recurring",
]


def _filter_evidence(
    evidence: List[RetrievedEvidence],
    company: CompanyContext,
) -> List[RetrievedEvidence]:
    """Return evidence items relevant to this agent's business-quality domain.

    Matches on title OR source containing any keyword (case-insensitive).
    Evidence whose title contains the company ticker or name is always included
    to capture company-specific profile and financial quality data.
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


def _empty_output(reason: str = "") -> QualityAssessment:
    return QualityAssessment(
        overall=f"Insufficient evidence for quality assessment. {reason}".strip(),
        confidence=0.0,
    )


def _build_prompt(company: CompanyContext, evidence: List[RetrievedEvidence]) -> str:
    """Build the quality agent prompt."""
    evidence_block = "\n".join(
        f"[{i + 1}] {ev.title}\n    Source: {ev.source}\n    {ev.summary}"
        for i, ev in enumerate(evidence)
    )
    sector_line = f"Sector: {company.sector}" if company.sector else ""
    industry_line = f"Industry: {company.industry}" if company.industry else ""
    context_lines = "\n".join(filter(None, [sector_line, industry_line]))

    return f"""You are a specialist business quality analyst. Analyse {company.company_name} ({company.ticker}).
{context_lines}

EVIDENCE (company profile, financial quality indicators):
{evidence_block}

Based on the company profile and financial evidence above, assess the following:
- What is the company's competitive moat — how durable are its advantages (brand, network effects, switching costs, IP, cost leadership)?
- What does management's track record look like — capital-allocation decisions, insider ownership, execution consistency?
- How disciplined is capital allocation — buyback efficacy, dividend policy, R&D investment vs returns, M&A track record?
- How durable and recurring is revenue — what share is subscription/contracted vs transactional/cyclical? How sticky are customers?
- What is the operating quality — FCF conversion rate, margin consistency over cycles, asset-intensity vs returns?

Produce a JSON object matching the QualityAssessment schema with these fields:
- moat: Competitive advantages and their durability
- management: Management quality and track record
- capital_allocation: Buybacks, dividends, R&D, and M&A discipline
- revenue_durability: Recurring vs one-time revenue; customer stickiness
- operating_quality: Margin consistency, FCF conversion, asset intensity
- overall: One concise paragraph summarising business quality
- confidence: 0.0-1.0 based on evidence completeness

Rules:
- Cite evidence numbers (e.g. [1], [2]) in your text.
- Be specific — no generic placeholders or invented figures.
- Return ONLY valid JSON, no markdown fences or prose outside the JSON object.

JSON:"""


def run_quality_agent(
    company: CompanyContext,
    evidence: List[RetrievedEvidence],
    request_id: Optional[str] = None,
) -> QualityAssessment:
    """Run the quality specialist agent.

    Filters evidence to business-quality-relevant items (company profile,
    FCF, moat indicators), builds a focused prompt, calls the LLM via
    get_structured_response, and returns a QualityAssessment. Degrades
    gracefully if evidence is empty or the LLM call fails.
    """
    relevant = _filter_evidence(evidence, company)
    print(
        f"[DIAG] [{_AGENT_NAME}] ticker={company.ticker} "
        f"relevant_evidence={len(relevant)}/{len(evidence)}"
    )

    if not relevant:
        return _empty_output("No quality-relevant evidence available.")

    prompt = _build_prompt(company, relevant)
    try:
        result: QualityAssessment = get_structured_response(
            prompt,
            QualityAssessment,
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
