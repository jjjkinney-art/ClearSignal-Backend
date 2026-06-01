"""Macro specialist agent.

Focuses on interest-rate sensitivity, inflation pass-through, recession
risk, and cyclical exposure for a given company under current macro conditions.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..schemas import CompanyContext, MacroSensitivity, RetrievedEvidence, CompanyKnowledgeProfile
from ..structured_output import get_structured_response
from ..model_client import model_client
from ..config import settings
from ._signal_extraction import extract_min_bullish_signal

logger = logging.getLogger(__name__)

_AGENT_NAME = "macro_agent"

_EVIDENCE_KEYWORDS = [
    "fred", "treasury", "yield", "inflation", "cpi", "pce",
    "fed funds", "federal reserve", "recession", "gdp", "vix",
    "credit spread", "t10y2y", "dgs", "interest rate",
    "monetary policy", "quantitative", "rate hike", "rate cut",
    "10-year", "2-year", "spread",
]


def _filter_evidence(
    evidence: List[RetrievedEvidence],
    company: CompanyContext,
) -> List[RetrievedEvidence]:
    """Return evidence items relevant to this agent's macro domain.

    Matches on title OR source containing any keyword (case-insensitive).
    Evidence whose title contains the company ticker or name is always included
    to capture company-specific macro commentary.
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


def _empty_output(reason: str = "") -> MacroSensitivity:
    return MacroSensitivity(
        overall=f"Insufficient evidence for macro sensitivity analysis. {reason}".strip(),
        confidence=0.0,
    )


def _build_prompt(
    company: CompanyContext,
    evidence: List[RetrievedEvidence],
    profile: Optional[CompanyKnowledgeProfile] = None,
) -> str:
    """Build the macro agent prompt."""
    evidence_block = "\n".join(
        f"[{i + 1}] {ev.title}\n    Source: {ev.source}\n    {ev.summary}"
        for i, ev in enumerate(evidence)
    )
    sector_line = f"Sector: {company.sector}" if company.sector else ""
    industry_line = f"Industry: {company.industry}" if company.industry else ""
    context_lines = "\n".join(filter(None, [sector_line, industry_line]))

    if profile is not None:
        company_context_block = f"""=== COMPANY-SPECIFIC CONTEXT ===
Business model: {profile.business_model}
Rate sensitivity: {profile.rate_sensitivity_note}
Inflation pass-through: {profile.inflation_pass_through}
Recession behavior: {profile.recession_behavior}
Business model keywords you MUST reference: {', '.join(profile.business_model_keywords[:8])}

MANDATORY SPECIFICITY RULES:
- Every analytical sentence MUST reference a specific {company.company_name} business segment, product, metric, or competitive dynamic.
- FORBIDDEN generic phrases: "higher rates hurt growth stocks", "the company faces headwinds", "like many tech companies", "as a growth stock"
- REQUIRED: Name specific {company.ticker} revenue lines, products, or structural advantages in every claim.
- Do NOT write sector-level analysis — write exclusively about {company.company_name}.

MACRO SPECIFICITY REQUIRED:
- Trace rate changes through {company.ticker}'s SPECIFIC revenue lines (not "rates hurt growth stocks")
- Explain the transmission mechanism: rate → [specific cost/demand/multiple effect] → [specific P&L line]
"""
    else:
        company_context_block = ""

    return f"""You are a specialist macro analyst. Analyse {company.company_name} ({company.ticker}).
{context_lines}

{company_context_block}
EVIDENCE:
{evidence_block}

Using the macro evidence above, answer the following for this company:
- How do current interest-rate levels and trajectory affect this company's earnings and valuation?
- What is its pricing power and ability to pass through inflation to customers?
- How vulnerable are revenues and margins if the economy enters a recession?
- Is this company cyclical or defensive — how correlated is its business with the economic cycle?
- What yield-curve or credit-spread signals are relevant?

Produce a JSON object matching the MacroSensitivity schema with these fields:
- rate_sensitivity: Impact of rate moves on valuation and earnings
- inflation_sensitivity: Pricing power and cost-pass-through ability
- recession_risk: Revenue and margin vulnerability in a downturn
- cyclicality: Cyclical vs defensive revenue mix and economic correlation
- overall: One concise paragraph summarising macro sensitivity
- confidence: 0.0-1.0 based on evidence completeness
- signals: array of 2-3 extracted macro signals. REQUIRED: this array MUST NOT be empty — return
  at least 1 signal even if evidence is limited. At least 1 signal MUST have direction="bullish"
  or direction="neutral" describing the company's macro resilience or rate/inflation tailwind.
  Each signal object must have:
    - signal: string — causal mechanism (e.g. "100bps rate rise compresses AAPL P/E ~15% via DCF discount rate")
    - direction: "bullish" | "bearish" | "neutral"
    - signal_type: "macro" | "structural" | "cyclical" | "risk"
    - impact_score: 0.0-1.0
    - time_horizon: "short_term" | "medium_term" | "long_term"
    - importance_reason: string — specific transmission mechanism to this company's P&L

Rules:
- Cite evidence numbers (e.g. [1], [2]) in your text.
- Be specific — no generic placeholders or invented figures.
- Return ONLY valid JSON, no markdown fences or prose outside the JSON object.

JSON:"""


def run_macro_agent(
    company: CompanyContext,
    evidence: List[RetrievedEvidence],
    request_id: Optional[str] = None,
    profile: Optional[CompanyKnowledgeProfile] = None,
) -> MacroSensitivity:
    """Run the macro specialist agent.

    Filters evidence to macro-relevant items, builds a focused prompt,
    calls the LLM via get_structured_response, and returns a MacroSensitivity.
    Degrades gracefully if evidence is empty or the LLM call fails.
    """
    relevant = _filter_evidence(evidence, company)
    print(
        f"[DIAG] [{_AGENT_NAME}] ticker={company.ticker} "
        f"relevant_evidence={len(relevant)}/{len(evidence)}"
    )

    if not relevant:
        return _empty_output("No macro-relevant evidence available.")

    prompt = _build_prompt(company, relevant, profile)
    try:
        result: MacroSensitivity = get_structured_response(
            prompt,
            MacroSensitivity,
            model_client,
            max_retries=settings.model_max_retries,
            backoff_factor=settings.model_backoff_factor,
        )
        result.evidence_used = [ev.title[:70] for ev in relevant]
        _has_bullish = any(s.direction == "bullish" for s in (result.signals or []))
        if not _has_bullish and result.overall and result.confidence > 0.3:
            extracted = extract_min_bullish_signal(
                result.overall, company, _AGENT_NAME, "macro", profile
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
