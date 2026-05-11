"""Risk specialist agent.

Focuses on debt and leverage risk, SEC filing disclosures, competitive threats,
regulatory exposure, and revenue/customer concentration risk.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..schemas import CompanyContext, RiskProfile, RetrievedEvidence
from ..structured_output import get_structured_response
from ..model_client import model_client
from ..config import settings

logger = logging.getLogger(__name__)

_AGENT_NAME = "risk_agent"

_EVIDENCE_KEYWORDS = [
    "sec",
    "edgar",
    "10-k",
    "10-q",
    "annual report",
    "quarterly report",
    "filing",
    "debt",
    "balance sheet",
    "liability",
    "leverage",
    "risk",
]


def _filter_evidence(
    evidence: List[RetrievedEvidence],
    company: CompanyContext,
) -> List[RetrievedEvidence]:
    """Return evidence items relevant to this agent's risk domain.

    Matches on title OR source containing any keyword (case-insensitive).
    Evidence whose title contains the company ticker or name is always included
    to capture company-specific SEC filings and risk disclosures.
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


def _empty_output(reason: str = "") -> RiskProfile:
    return RiskProfile(
        overall=f"Insufficient evidence for risk analysis. {reason}".strip(),
        confidence=0.0,
    )


def _build_prompt(company: CompanyContext, evidence: List[RetrievedEvidence]) -> str:
    """Build the risk agent prompt."""
    evidence_block = "\n".join(
        f"[{i + 1}] {ev.title}\n    Source: {ev.source}\n    {ev.summary}"
        for i, ev in enumerate(evidence)
    )
    sector_line = f"Sector: {company.sector}" if company.sector else ""
    industry_line = f"Industry: {company.industry}" if company.industry else ""
    context_lines = "\n".join(filter(None, [sector_line, industry_line]))

    return f"""You are a specialist risk analyst. Analyse {company.company_name} ({company.ticker}).
{context_lines}

EVIDENCE (SEC filings, balance-sheet data, and related sources):
{evidence_block}

Based on the SEC filing and balance-sheet evidence above, assess the following:
- What is the company's leverage profile? Assess debt levels, interest coverage, and refinancing risk.
- What are the top competitive threats and risks of market-share erosion?
- What regulatory risks or compliance burdens could materially impact the business?
- Are there significant customer, supplier, product, or geographic concentration risks?
- What are the top 3-5 specific risks an investor should monitor?

Produce a JSON object matching the RiskProfile schema with these fields:
- debt_risk: Leverage, interest coverage, and refinancing risk assessment
- competitive_risk: Competitive moat erosion and market-share threats
- regulatory_risk: Regulatory exposure and compliance burden
- concentration_risk: Customer, supplier, or geography concentration
- key_risks: Array of top 3-5 risks in concise bullet form (each a string)
- overall: One concise paragraph summarising the risk profile
- confidence: 0.0-1.0 based on evidence completeness

Rules:
- Cite evidence numbers (e.g. [1], [2]) in your text.
- Be specific — no generic placeholders or invented figures.
- key_risks must be a JSON array of strings.
- Return ONLY valid JSON, no markdown fences or prose outside the JSON object.

JSON:"""


def run_risk_agent(
    company: CompanyContext,
    evidence: List[RetrievedEvidence],
    request_id: Optional[str] = None,
) -> RiskProfile:
    """Run the risk specialist agent.

    Filters evidence to risk-relevant items (SEC filings, debt, leverage),
    builds a focused prompt, calls the LLM via get_structured_response,
    and returns a RiskProfile. Degrades gracefully if evidence is empty
    or the LLM call fails.
    """
    relevant = _filter_evidence(evidence, company)
    print(
        f"[DIAG] [{_AGENT_NAME}] ticker={company.ticker} "
        f"relevant_evidence={len(relevant)}/{len(evidence)}"
    )

    if not relevant:
        return _empty_output("No risk-relevant evidence available.")

    prompt = _build_prompt(company, relevant)
    try:
        result: RiskProfile = get_structured_response(
            prompt,
            RiskProfile,
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
