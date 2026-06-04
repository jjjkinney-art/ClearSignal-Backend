"""Quality specialist agent.

Focuses on competitive moat durability, management track record, capital-allocation
discipline, revenue durability (recurring vs one-time), and operating quality
(FCF conversion, margin consistency, asset intensity).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..schemas import CompanyContext, QualityAssessment, RetrievedEvidence, CompanyKnowledgeProfile
from ..structured_output import get_structured_response
from ..model_client import model_client
from ..config import settings
from ._signal_extraction import extract_min_bullish_signal

logger = logging.getLogger(__name__)

_AGENT_NAME = "quality_agent"

_EVIDENCE_KEYWORDS = [
    "profile", "company profile", "fmp", "business",
    "free cash flow", "fcf", "buyback", "repurchase",
    "dividend", "r&d", "research", "intellectual property",
    "subscription", "recurring", "moat", "ecosystem",
    "retention", "churn", "installed base", "switching cost",
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


def _build_question_emphasis_block(
    question_intent: Optional[str],
    question: Optional[str],
    company: CompanyContext,
) -> str:
    """Build a question-specific emphasis block for the quality prompt.

    Tells the quality agent which business-quality dimension to lead with
    based on the user's actual question.  Returns empty string for default intent.
    """
    ticker = company.ticker
    q_display = f'"{question}"' if question else "the user's question"

    if question_intent == "competitive_position":
        return (
            f"QUESTION FOCUS — USER IS ASKING: {q_display}\n"
            f"This is a direct moat question. Make `moat` the highest-depth field:\n"
            f"  1. Enumerate {ticker}'s specific moat sources in order of durability "
            f"(switching costs, network effects, IP, brand, cost leadership).\n"
            f"  2. Assess which moat source is STRENGTHENING vs WEAKENING right now "
            f"and why — name the competitive dynamic driving the change.\n"
            f"  3. If the question compares two {ticker} products/segments (e.g. Azure vs M365), "
            f"compare their moat depth, revenue trajectory, and competitive defensibility "
            f"directly in `moat`.\n\n"
        )
    if question_intent == "valuation_stance":
        return (
            f"QUESTION FOCUS — USER IS ASKING: {q_display}\n"
            f"The user is assessing {ticker}'s valuation. Emphasise quality factors that "
            f"justify or challenge the current premium:\n"
            f"  1. `operating_quality` must lead — FCF yield, conversion rate, and whether "
            f"the current multiple is supported by structural margin durability.\n"
            f"  2. `capital_allocation` must address whether {ticker}'s buyback/dividend "
            f"program provides earnings-per-share floor support.\n"
            f"  3. What quality premium does the current price imply — is it earned or borrowed?\n\n"
        )
    if question_intent == "macro_sensitivity":
        return (
            f"QUESTION FOCUS — USER IS ASKING: {q_display}\n"
            f"The user is asking about macro exposure. Emphasise defensive quality:\n"
            f"  1. `revenue_durability` must lead — what share of {ticker}'s revenue is "
            f"contracted, subscription, or otherwise insulated from macro deterioration?\n"
            f"  2. Assess {ticker}'s pricing power under the specific macro scenario asked about "
            f"(rate rise / rate cut / recession / inflation).\n"
            f"  3. Is {ticker}'s FCF profile counter-cyclical, cyclical, or acyclical?\n\n"
        )
    if question_intent == "risk_assessment":
        return (
            f"QUESTION FOCUS — USER IS ASKING: {q_display}\n"
            f"The user is focused on risks. Surface quality-side risks:\n"
            f"  1. Name the specific quality dimensions most at risk — moat erosion, "
            f"management execution failure, FCF deterioration.\n"
            f"  2. `moat` must include a deterioration scenario — what would cause "
            f"{ticker}'s competitive advantages to weaken materially?\n"
            f"  3. Identify any capital-allocation red flags (dilutive M&A, payout "
            f"unsustainability, R&D yield declining).\n\n"
        )
    return ""


def _build_prompt(
    company: CompanyContext,
    evidence: List[RetrievedEvidence],
    profile: Optional[CompanyKnowledgeProfile] = None,
    question_intent: Optional[str] = None,
    question: Optional[str] = None,
) -> str:
    """Build the quality agent prompt."""
    evidence_block = "\n".join(
        f"[{i + 1}] {ev.title}\n    Source: {ev.source}\n    {ev.summary}"
        for i, ev in enumerate(evidence)
    )
    sector_line = f"Sector: {company.sector}" if company.sector else ""
    industry_line = f"Industry: {company.industry}" if company.industry else ""
    context_lines = "\n".join(filter(None, [sector_line, industry_line]))

    question_emphasis = _build_question_emphasis_block(question_intent, question, company)

    if profile is not None:
        company_context_block = f"""=== COMPANY-SPECIFIC CONTEXT ===
Business model: {profile.business_model}
Competitive advantages: {'; '.join(profile.competitive_advantages)}
Recurring revenue sources: {', '.join(profile.recurring_revenue_sources)}
Capital allocation style: {profile.valuation_style} — infer buyback/dividend discipline from this context.
Business model keywords you MUST reference: {', '.join(profile.business_model_keywords[:8])}

MANDATORY SPECIFICITY RULES:
- Every analytical sentence MUST reference a specific {company.company_name} business segment, product, metric, or competitive dynamic.
- FORBIDDEN generic phrases: "higher rates hurt growth stocks", "the company faces headwinds", "like many tech companies", "as a growth stock"
- REQUIRED: Name specific {company.ticker} revenue lines, products, or structural advantages in every claim.
- Do NOT write sector-level analysis — write exclusively about {company.company_name}.

QUALITY SPECIFICITY REQUIRED:
- Moat assessment must reference specific structural barriers ({company.ticker}'s ecosystem, patents, switching costs, etc.)
- FCF assessment must reference specific business lines that generate or consume cash.
"""
    else:
        company_context_block = ""

    return f"""You are a specialist business quality analyst. Analyse {company.company_name} ({company.ticker}).
{context_lines}

{company_context_block}
{question_emphasis}EVIDENCE (company profile, financial quality indicators):
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
- signals: array of 2-3 quality signals. REQUIRED: this array MUST NOT be empty — return at
  least 1 signal even if evidence is limited. At least 1 signal MUST have direction="bullish"
  describing the company's primary moat, FCF quality, or capital-allocation strength.
  Each signal object must have:
    - signal: string — specific quality driver (e.g. "[company-specific] FCF conversion
      and [company's actual capital return] provide durable shareholder return — use
      the ACTUAL company's metrics from evidence, never copy figures from other companies")
    - direction: "bullish" | "bearish" | "neutral"
    - signal_type: "quality" | "structural" | "risk"
    - impact_score: 0.0-1.0
    - time_horizon: "short_term" | "medium_term" | "long_term"
    - importance_reason: string — why this quality factor differentiates this company

Rules:
- Cite evidence numbers (e.g. [1], [2]) in your text.
- Be specific — no generic placeholders or invented figures.
- Return ONLY valid JSON, no markdown fences or prose outside the JSON object.

JSON:"""


def run_quality_agent(
    company: CompanyContext,
    evidence: List[RetrievedEvidence],
    request_id: Optional[str] = None,
    profile: Optional[CompanyKnowledgeProfile] = None,
    question_intent: Optional[str] = None,
    question: Optional[str] = None,
) -> QualityAssessment:
    """Run the quality specialist agent.

    Filters evidence to business-quality-relevant items (company profile,
    FCF, moat indicators), builds a focused prompt, calls the LLM via
    get_structured_response, and returns a QualityAssessment. Degrades
    gracefully if evidence is empty or the LLM call fails.

    Parameters
    ----------
    question_intent : Optional[str]
        Drives which quality dimension to lead with.  ``"competitive_position"``
        → deep moat decomposition; ``"valuation_stance"`` → FCF and capital
        return quality; ``"macro_sensitivity"`` → revenue durability and
        defensiveness.
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
        return _empty_output("No quality-relevant evidence available.")

    prompt = _build_prompt(company, relevant, profile,
                           question_intent=question_intent, question=question)
    try:
        result: QualityAssessment = get_structured_response(
            prompt,
            QualityAssessment,
            model_client,
            max_retries=settings.model_max_retries,
            backoff_factor=settings.model_backoff_factor,
        )
        result.evidence_used = [ev.title[:70] for ev in relevant]
        _has_bullish = any(s.direction == "bullish" for s in (result.signals or []))
        if not _has_bullish and result.overall and result.confidence > 0.3:
            extracted = extract_min_bullish_signal(
                result.overall, company, _AGENT_NAME, "quality", profile
            )
            if extracted:
                result.signals = list(result.signals or []) + extracted
                print(
                    f"[DIAG] [{_AGENT_NAME}] bullish_extraction fired (no_bullish_signals) "
                    f"ticker={company.ticker} extracted={len(extracted)}"
                )
        return result
    except Exception as exc:
        logger.warning(
            "[%s] LLM call failed for %s: %r",
            _AGENT_NAME,
            company.ticker,
            exc,
        )
        return _empty_output(f"LLM error: {exc}")
