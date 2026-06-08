"""Risk specialist agent.

Focuses on debt and leverage risk, SEC filing disclosures, competitive threats,
regulatory exposure, and revenue/customer concentration risk.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..schemas import CompanyContext, RiskProfile, RetrievedEvidence, CompanyKnowledgeProfile
from ..structured_output import get_structured_response
from ..model_client import model_client
from ..config import settings

logger = logging.getLogger(__name__)

_AGENT_NAME = "risk_agent"

_EVIDENCE_KEYWORDS = [
    "sec", "edgar", "10-k", "10-q", "annual report", "quarterly report",
    "filing", "debt", "balance sheet", "liability", "leverage",
    "risk", "risk factor", "regulation", "lawsuit", "litigation",
    "refinancing", "credit rating", "covenant", "supply chain",
    "exposure", "concentration",
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


def _build_question_emphasis_block(
    question_intent: Optional[str],
    question: Optional[str],
    company: CompanyContext,
) -> str:
    """Build a question-specific emphasis block for the risk prompt.

    Tells the risk agent which risk category to lead with based on what
    the user actually asked about.  Returns empty string for default intent.
    """
    ticker = company.ticker
    q_display = f'"{question}"' if question else "the user's question"

    if question_intent == "risk_assessment":
        return (
            f"QUESTION FOCUS — USER IS ASKING: {q_display}\n"
            f"This is a direct risk question. Make your analysis comprehensive and risk-first:\n"
            f"  1. Lead `overall` with the single highest-severity risk to the {ticker} thesis.\n"
            f"  2. `key_risks` must be exhaustive — list every material risk named in evidence.\n"
            f"  3. Each risk must name the specific {ticker} revenue line, customer segment, "
            f"or competitive dynamic at stake — no generic sector risks.\n\n"
        )
    if question_intent == "competitive_position":
        return (
            f"QUESTION FOCUS — USER IS ASKING: {q_display}\n"
            f"The user is asking about competitive moat. Lead with competitive risks:\n"
            f"  1. Make `competitive_risk` the highest-depth field — name specific "
            f"competitors, disruption vectors, and market-share loss mechanisms for {ticker}.\n"
            f"  2. Identify the specific moat element most at risk and why.\n"
            f"  3. Quantify the market-share impact if the moat erodes (revenue at risk).\n\n"
        )
    if question_intent == "valuation_stance":
        return (
            f"QUESTION FOCUS — USER IS ASKING: {q_display}\n"
            f"The user is assessing {ticker}'s valuation. Emphasise risks that could "
            f"compress the multiple:\n"
            f"  1. Lead with estimate-cut risk — what could cause consensus EPS to step down?\n"
            f"  2. Name the guidance miss scenario most likely to trigger a de-rating.\n"
            f"  3. Identify any balance-sheet risk that challenges the premium multiple.\n\n"
        )
    if question_intent == "macro_sensitivity":
        return (
            f"QUESTION FOCUS — USER IS ASKING: {q_display}\n"
            f"The user is asking about macro exposure. Lead with macro-linked risks:\n"
            f"  1. What is the specific rate-shock or recession scenario most damaging to "
            f"{ticker}'s revenue or margins?\n"
            f"  2. Does {ticker}'s debt structure create refinancing risk in a higher-rate env?\n"
            f"  3. Name the customer segment most vulnerable to macro deterioration.\n\n"
        )
    return ""


def _build_prompt(
    company: CompanyContext,
    evidence: List[RetrievedEvidence],
    profile: Optional[CompanyKnowledgeProfile] = None,
    question_intent: Optional[str] = None,
    question: Optional[str] = None,
) -> str:
    """Build the risk agent prompt."""
    evidence_block = "\n".join(
        f"[{i + 1}] {ev.title}\n    Source: {ev.source}\n    {ev.summary}"
        for i, ev in enumerate(evidence)
    )
    sector_line = f"Sector: {company.sector}" if company.sector else ""
    industry_line = f"Industry: {company.industry}" if company.industry else ""
    context_lines = "\n".join(filter(None, [sector_line, industry_line]))

    question_emphasis = _build_question_emphasis_block(question_intent, question, company)

    if profile is not None:
        major_risks_block = "\n".join(f"  - {r}" for r in profile.major_risks)
        company_context_block = f"""=== COMPANY-SPECIFIC CONTEXT ===
Business model: {profile.business_model}
Known major risks (validate and expand from evidence):
{major_risks_block}
Business model keywords you MUST reference: {', '.join(profile.business_model_keywords[:8])}

MANDATORY SPECIFICITY RULES:
- Every analytical sentence MUST reference a specific {company.company_name} business segment, product, metric, or competitive dynamic.
- FORBIDDEN generic phrases: "higher rates hurt growth stocks", "the company faces headwinds", "like many tech companies", "as a growth stock"
- REQUIRED: Name specific {company.ticker} revenue lines, products, or structural advantages in every claim.
- Do NOT write sector-level analysis — write exclusively about {company.company_name}.

RISK SPECIFICITY REQUIRED:
- Each risk must name the specific {company.ticker} revenue line, customer segment, or competitive dynamic at stake.
- Do NOT list sector-level risks without tracing them to {company.ticker}'s specific situation.
"""
    else:
        company_context_block = ""

    return f"""You are a specialist risk analyst. Analyse {company.company_name} ({company.ticker}).
{context_lines}

{company_context_block}
{question_emphasis}EVIDENCE (SEC filings, balance-sheet data, and related sources):
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
- signals: array of 2-3 risk signals. Each signal object must have:
    - signal: string — specific risk with transmission mechanism (e.g. "China revenue ~19% of AAPL total faces $10B+ tariff exposure")
    - direction: "bearish" (risks are bearish by default)
    - signal_type: "risk" | "cyclical" | "structural"
    - impact_score: 0.0-1.0 (severity)
    - time_horizon: "short_term" | "medium_term" | "long_term"
    - importance_reason: string — why this risk is the most thesis-threatening

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
    profile: Optional[CompanyKnowledgeProfile] = None,
    question_intent: Optional[str] = None,
    question: Optional[str] = None,
) -> RiskProfile:
    """Run the risk specialist agent.

    Filters evidence to risk-relevant items (SEC filings, debt, leverage),
    builds a focused prompt, calls the LLM via get_structured_response,
    and returns a RiskProfile. Degrades gracefully if evidence is empty
    or the LLM call fails.

    Parameters
    ----------
    question_intent : Optional[str]
        Drives which risk category to lead with.  ``"risk_assessment"`` → full
        comprehensive risk list; ``"competitive_position"`` → competitive_risk
        as anchor; ``"valuation_stance"`` → estimate-cut and de-rating risks.
    question : Optional[str]
        The user's verbatim question, injected into the emphasis block.
    """
    relevant = _filter_evidence(evidence, company)
    print(
        f"[DIAG] [{_AGENT_NAME}] ticker={company.ticker} "
        f"relevant_evidence={len(relevant)}/{len(evidence)} "
        f"question_intent={question_intent!r}"
    )

    if not relevant:
        return _empty_output("No risk-relevant evidence available.")

    prompt = _build_prompt(company, relevant, profile,
                           question_intent=question_intent, question=question)
    try:
        result: RiskProfile = get_structured_response(
            prompt,
            RiskProfile,
            model_client,
            max_retries=getattr(settings, "agent_max_retries", 1),
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
