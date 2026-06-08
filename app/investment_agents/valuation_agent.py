"""Valuation specialist agent.

Focuses on valuation multiples, growth trajectory, margin trends,
discount-rate sensitivity, and relative valuation vs sector peers.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..schemas import CompanyContext, ValuationView, RetrievedEvidence, CompanyKnowledgeProfile, Signal
from ..structured_output import get_structured_response
from ..model_client import model_client
from ..config import settings
from ._signal_extraction import extract_min_bullish_signal

logger = logging.getLogger(__name__)

_AGENT_NAME = "valuation_agent"

_EVIDENCE_KEYWORDS = [
    "income", "revenue", "earnings", "eps", "p/e", "pe ratio",
    "margin", "profitability", "financial", "fmp",
    "price change", "stock price", "valuation", "multiple",
    "ev/ebitda", "forward pe", "growth rate", "guidance",
    "beat", "miss", "fiscal", "quarter", "annual",
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


def _build_prompt(
    company: CompanyContext,
    evidence: List[RetrievedEvidence],
    profile: Optional[CompanyKnowledgeProfile] = None,
    question_intent: Optional[str] = None,
    question: Optional[str] = None,
) -> str:
    """Build the valuation agent prompt."""
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
Primary revenue drivers: {', '.join(profile.primary_revenue_drivers)}
Valuation style: {profile.valuation_style}
Key metrics to anchor on: {', '.join(profile.key_metrics)}
Competitive advantages (inform premium/discount): {'; '.join(profile.competitive_advantages[:3])}
Business model keywords you MUST reference: {', '.join(profile.business_model_keywords[:8])}

MANDATORY SPECIFICITY RULES:
- Every analytical sentence MUST reference a specific {company.company_name} business segment, product, metric, or competitive dynamic.
- FORBIDDEN generic phrases: "higher rates hurt growth stocks", "the company faces headwinds", "like many tech companies", "as a growth stock"
- REQUIRED: Name specific {company.ticker} revenue lines, products, or structural advantages in every claim.
- Do NOT write sector-level analysis — write exclusively about {company.company_name}.

VALUATION SPECIFICITY REQUIRED:
- Cite the actual valuation style: {profile.valuation_style}
- Reference specific revenue drivers when assessing growth assumptions
- Name specific margin lines (not "margins declined" — which margins?)
"""
    else:
        company_context_block = ""

    # ── Valuation stance instruction block ───────────────────────────────────
    # Injected only when the user is asking a price-fairness question.
    # Requires the model to commit to an explicit verdict.
    if question_intent == "valuation_stance":
        stance_block = f"""
VALUATION STANCE REQUIRED — USER IS ASKING WHETHER {company.ticker} IS OVERPRICED / FAIRLY VALUED / UNDERPRICED:

You MUST populate the `valuation_stance` field with one of:
  "overpriced" | "fairly_valued" | "underpriced" | "cannot_determine"

Rules for choosing a stance:
- "overpriced":       current multiple materially exceeds what the growth/quality profile justifies.
  Look for: forward P/E > historical range, EV/EBITDA above peer median, analyst consensus price
  target below current price, or premium that requires execution perfection.
- "underpriced":      current multiple is below what the growth/quality profile justifies.
  Look for: P/E discount to peers without fundamental justification, FCF yield above risk-free
  rate by meaningful margin, or analyst targets materially above current price.
- "fairly_valued":    current price reasonably reflects known fundamentals — neither stretched
  nor cheap by standard metrics. Use when evidence does not clearly support either extreme.
- "cannot_determine": evidence is genuinely insufficient to form a confident view.
  ONLY use this when no ratio data or analyst targets are available — do NOT use it as a
  hedge when evidence exists but the answer is uncomfortable.

Also populate `valuation_stance_reasoning` with 1–2 sentences naming:
  (a) the key metric that anchors your verdict (e.g. "Trading at ~28x forward P/E vs peer median of 22x"),
  (b) what growth/quality assumption the current price requires to be justified.

If confidence < 0.45 because evidence is thin, set `valuation_stance = "cannot_determine"` and
explain what data is missing in `valuation_stance_reasoning`.
"""
    else:
        stance_block = ""

    # ── Verbatim question guidance (Phase 4) ─────────────────────────────────
    # When the verbatim question is available, inject a focused instruction
    # block so the valuation agent produces output that directly supports
    # the question-answerer and synthesis layers.  Enabled for all question
    # intents except valuation_stance (which already has its own full mandate).
    if question and question_intent not in ("valuation_stance", None, ""):
        _q_intent_hints = {
            "implied_growth_rate": (
                f"The user's question is about the IMPLIED GROWTH RATE embedded in "
                f"{company.ticker}'s current multiple. MANDATORY:\n"
                f"  - In `pe_assessment`: state the current forward P/E or EV/Revenue "
                f"explicitly, then compute what compound revenue CAGR that multiple "
                f"implies over 3–5 years (use discount rate 10% if unspecified).\n"
                f"  - In `growth_view`: state the analyst consensus growth rate and "
                f"whether it meets or falls short of the implied rate.\n"
                f"  - In `relative_value`: name 1–2 historical periods or peers where "
                f"a similar multiple was sustained — and the outcome.\n"
                f"  - In `overall`: lead with the implied CAGR figure."
            ),
            "quantitative_threshold": (
                f"The user is asking for a QUANTITATIVE THRESHOLD — what level of "
                f"[revenue decline / margin compression / loss rate] causes material "
                f"earnings impact. MANDATORY:\n"
                f"  - In `pe_assessment`: cite the specific financial exposure from "
                f"evidence (e.g. loan book size, segment revenue at risk).\n"
                f"  - In `discount_sensitivity`: compute the EPS or ROE impact at "
                f"the threshold scenario from evidence data.\n"
                f"  - In `overall`: lead with the quantified threshold and impact."
            ),
            "metric_ordering": (
                f"The user is asking WHICH METRIC deteriorates first. MANDATORY:\n"
                f"  - In `margin_trend`: name the specific margin or unit-economics "
                f"line that leads in a downturn and explain the causal mechanism.\n"
                f"  - In `growth_view`: explain which growth metric follows and why.\n"
                f"  - In `overall`: rank at least 2 metrics by order of deterioration."
            ),
            "segment_ranking": (
                f"The user is asking to RANK SEGMENTS by moat width or quality. "
                f"MANDATORY:\n"
                f"  - In `relative_value`: compare the segments named in the question "
                f"on margin profile, switching cost, and growth rate.\n"
                f"  - In `overall`: state a ranked order (#1, #2, #3) with the "
                f"primary reason for each ranking."
            ),
            "timing_lag": (
                f"The user is asking about TIMING LAGS (decision → revenue impact). "
                f"MANDATORY:\n"
                f"  - In `growth_view`: state the causal chain from the upstream "
                f"decision to the revenue line, naming the number of quarters lag.\n"
                f"  - In `overall`: lead with the specific lag estimate in quarters."
            ),
            "historical_precedent": (
                f"The user is asking for HISTORICAL PRECEDENT. MANDATORY:\n"
                f"  - In `relative_value`: name the best historical analog — company, "
                f"period, metric trajectory — and whether the current situation is "
                f"more or less favorable.\n"
                f"  - In `pe_assessment`: compare current multiple to the historical "
                f"period's entry multiple.\n"
                f"  - In `overall`: lead with the most relevant historical comparison."
            ),
        }
        _q_hint = _q_intent_hints.get(question_intent, "")
        if _q_hint:
            question_guidance_block = (
                f"\nQUESTION-SPECIFIC GUIDANCE (Phase 4):\n"
                f'USER\'S EXACT QUESTION: "{question}"\n\n'
                f"{_q_hint}\n"
            )
        else:
            question_guidance_block = (
                f"\nUSER'S EXACT QUESTION (orient your analysis to this): "
                f'"{question}"\n'
            )
    else:
        question_guidance_block = ""

    return f"""You are a specialist valuation analyst. Analyse {company.company_name} ({company.ticker}).
{context_lines}

{company_context_block}
{stance_block}{question_guidance_block}
EVIDENCE:
{evidence_block}

Produce a JSON object matching the ValuationView schema with these fields:
- pe_assessment: P/E ratio vs sector history and peers
- growth_view: Revenue and EPS growth trajectory from the evidence
- margin_trend: Operating and net margin trend
- discount_sensitivity: How sensitive the valuation is to discount-rate moves
- relative_value: Relative value vs sector peers
- overall: One concise paragraph summarising the valuation
- valuation_stance: (see instruction above) "overpriced" | "fairly_valued" | "underpriced" | "cannot_determine" | "" (empty when no stance question)
- valuation_stance_reasoning: 1-2 sentences anchoring the verdict to a specific metric
- confidence: 0.0-1.0 based on evidence completeness
- signals: array of 2-4 extracted signals. REQUIRED: this array MUST NOT be empty — return at
  least 1 signal even if evidence is limited. At least 1 signal MUST have direction="bullish"
  describing the company's primary valuation support, pricing power, or earnings growth driver.
  Each signal object must have:
    - signal: string — 1-2 sentences naming the specific driver, with priced-in language (NOT generic)
    - direction: "bullish" | "bearish" | "neutral"
    - signal_type: "valuation" | "structural" | "cyclical" | "catalyst" | "macro" | "quality" | "risk"
    - impact_score: 0.0-1.0 (how much does this move the thesis?)
    - time_horizon: "short_term" | "medium_term" | "long_term"
    - importance_reason: string — why this signal outweighs others
    - evidence_origin: string — human-readable source (e.g. "earnings call", "SEC filing", "estimate revisions")
    - source_category: string — one of: earnings|filing|macro|news|research|estimate_revision|market_data

Signal quality rules:
- BAD: "Apple has strong revenue" (generic description)
- GOOD: "Services segment at 72% gross margin offsets hardware P/E compression" (causal mechanism)
- Each signal must name a specific {company.ticker} product, segment, or metric

PRICED-IN ANALYSIS — MANDATORY for every valuation signal:
Each signal MUST answer: "Is this already priced in, or would this move the stock?"
- State what the current multiple implies is already embedded in the price
- Name one thing the market has NOT yet fully priced (where positioning could shift)
- Use language: "the stock already prices X", "at ~[multiple]x, the market is paying for Y",
  "incremental upside requires Z, not merely X", "consensus already assumes X — the differentiated call is Y"
- GOOD signal: "At ~28x forward earnings, the multiple already prices Services durability — upside
  requires margin acceleration above consensus, not just stability. [1]"
- BAD signal: "Strong Services margins support valuation." (no priced/unpriced distinction)

For evidence_origin and source_category fields in each signal object:
- evidence_origin: human-readable source label (e.g. "earnings call", "SEC filing", "estimate revisions", "news", "macro rates context")
- source_category: one of earnings|filing|macro|news|research|estimate_revision|market_data
  Derive these from the evidence items you cite.

Rules:
- Cite evidence numbers (e.g. [1], [2]) in your text.
- Be specific — no generic placeholders or invented figures.
- Return ONLY valid JSON, no markdown fences or prose outside the JSON object.

JSON:"""


def run_valuation_agent(
    company: CompanyContext,
    evidence: List[RetrievedEvidence],
    request_id: Optional[str] = None,
    profile: Optional[CompanyKnowledgeProfile] = None,
    question_intent: Optional[str] = None,
    question: Optional[str] = None,
) -> ValuationView:
    """Run the valuation specialist agent.

    Filters evidence to valuation-relevant items, builds a focused prompt,
    calls the LLM via get_structured_response, and returns a ValuationView.
    Degrades gracefully if evidence is empty or the LLM call fails.

    Parameters
    ----------
    question_intent : Optional[str]
        Detected intent from _detect_question_intent().  When
        ``"valuation_stance"`` the prompt requires an explicit
        overpriced / fairly_valued / underpriced / cannot_determine verdict
        and populates ``valuation_stance`` + ``valuation_stance_reasoning``.
    """
    relevant = _filter_evidence(evidence, company)
    print(
        f"[DIAG] [{_AGENT_NAME}] ticker={company.ticker} "
        f"relevant_evidence={len(relevant)}/{len(evidence)} "
        f"question_intent={question_intent!r}"
    )

    if not relevant:
        return _empty_output("No valuation-relevant evidence available.")

    prompt = _build_prompt(company, relevant, profile, question_intent=question_intent, question=question)
    try:
        result: ValuationView = get_structured_response(
            prompt,
            ValuationView,
            model_client,
            max_retries=getattr(settings, "agent_max_retries", 1),
            backoff_factor=settings.model_backoff_factor,
        )
        result.evidence_used = [ev.title[:70] for ev in relevant]
        # Post-call fallback: if the LLM produced no bullish signals (either
        # signals=[] or all signals are bearish/risk), extract the most positive
        # sentence from the overall text as a minimum bullish signal.
        # Fires when: no bullish signal exists AND confidence > 0.3.
        # Appends when signals are already present (preserves bearish signals).
        _has_bullish = any(s.direction == "bullish" for s in (result.signals or []))
        if not _has_bullish and result.overall and result.confidence > 0.3:
            extracted = extract_min_bullish_signal(
                result.overall, company, _AGENT_NAME, "valuation", profile
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
