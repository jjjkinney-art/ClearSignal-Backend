"""
Investment thesis synthesiser.

Combines outputs from all five specialist investment agents into a single,
balanced InvestmentThesis.  The synthesiser is the final stage of the
multi-agent company analysis pipeline:

  CompanyContext
      ↓ (retrieve_market_evidence)
  List[RetrievedEvidence]
      ↓ (five parallel specialist agents)
  ValuationView + MacroSensitivity + RiskProfile + MarketContext + QualityAssessment
      ↓ (this module)
  InvestmentThesis

Phase 4 governance checks run deterministically *after* the LLM synthesis
call, without re-invoking the model.  Any detected contradiction is appended
to InvestmentThesis.consistency_warnings so the frontend can surface it.

Usage
-----
    from app.services.thesis_synthesizer import synthesize_thesis
    from app.investment_agents import (
        run_valuation_agent, run_macro_agent, run_risk_agent,
        run_market_agent, run_quality_agent,
    )

    valuation = run_valuation_agent(company, evidence)
    macro     = run_macro_agent(company, evidence)
    risk      = run_risk_agent(company, evidence)
    market    = run_market_agent(company, evidence)
    quality   = run_quality_agent(company, evidence)

    thesis = synthesize_thesis(company, valuation, macro, risk, market, quality, evidence)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..schemas import (
    CompanyContext,
    CompanyKnowledgeProfile,
    InvestmentThesis,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RetrievedEvidence,
    RiskProfile,
    ValuationView,
)
from ..structured_output import get_structured_response, extract_json_candidate, repair_data
from ..model_client import model_client
from ..config import settings
from .depth_guard import check_synthesis_depth
from .signal_ranker import (
    rank_signals,
    compress_thesis as _compress_thesis,
    check_forbidden_phrases,
    propagate_evidence_refs,
    detect_signal_overlap,
    build_confidence_reasoning,
    compute_confidence_realism_cap,
    _get_signal_dimension,
    RankedSignalSet,
)
from .thesis_polisher import polish_thesis

logger = logging.getLogger(__name__)


# ── Governance check constants ────────────────────────────────────────────────

# Known sector / macro contradictions: if a company is in these sectors,
# certain macro claims need extra scrutiny.
_RATE_SENSITIVE_SECTORS = frozenset({
    "Financials", "Real Estate", "Utilities",
})
_RATE_DEFENSIVE_SECTORS = frozenset({
    "Technology", "Consumer Discretionary",
})

# Phrases that assert "rate cuts help this company" — fine for most, but
# potentially misleading for banks (who benefit from higher rates via NIM).
_RATE_CUT_BENEFIT_PHRASES = (
    "rate cuts benefit",
    "lower rates benefit",
    "falling rates help",
    "rate cuts help",
    "benefits from lower rates",
)

# InvestmentThesis fields the LLM must populate (used in prompt + recovery).
# Ordered to match the schema's logical reading order.
_THESIS_FIELDS = (
    "ticker",
    "company_name",
    "direct_answer",
    "core_debate",
    "core_market_debate",
    "bull_thesis",
    "bear_thesis",
    "key_drivers",
    "key_risks",
    "valuation_view",
    "macro_sensitivity",
    "confidence_score",
    "confidence_reasoning",
    "what_changes_the_thesis",
    "conclusion",
)

# Markdown heading patterns used for recovery detection
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)


# ── Dominant dimension detection (Refinement 2: Analytical Asymmetry) ─────────

_DIMENSION_KEYWORDS: Dict[str, List[str]] = {
    "macro":              ["rate", "rates", "fed", "inflation", "macro", "yield",
                           "duration", "currency", "fx", "monetary", "recession"],
    "valuation":          ["multiple", "p/e", "dcf", "fair value", "premium",
                           "discount", "cheap", "expensive", "priced"],
    "regulatory":         ["antitrust", "regulatory", "regulation", "legal",
                           "probe", "ftc", "doj", "government", "policy"],
    "capital_allocation": ["buyback", "repurchase", "dividend", "debt",
                           "leverage", "fcf", "cash", "balance sheet"],
    "operational":        ["margin", "revenue", "earnings", "guidance",
                           "volume", "units", "growth", "segment"],
}

_DEPTH_DIRECTIVES: Dict[str, str] = {
    "macro": (
        "DOMINANT DIMENSION — MACRO: Macro transmission IS the central thesis debate.\n"
        "SECTION PRIORITY SCORE — HARD CAPS (enforce strictly, no exceptions):\n"
        "  macro_sensitivity : DEEP — 3+ sentences REQUIRED. Name the exact transmission "
        "channel with magnitude (e.g. '100bps rate move → ~15-20% P/E compression via DCF "
        "discount rate expansion'). Include second-order effect on buyback ROI and EPS support. "
        "Anchor on the CURRENT rate level and what has changed since the last rate move. "
        "This is your anchor section — it must be more analytically substantive than any other.\n"
        "  bear_thesis       : DEEP — 4 sentences. Full rate transmission pathway. "
        "Name the specific timing scenario that breaks the thesis. End with the trigger, "
        "not with a balanced counterpoint.\n"
        "  bull_thesis       : MEDIUM — 3 sentences. Name the specific offset mechanism. "
        "Do NOT use 'Services offsets' without naming the FCF yield, ARR, or duration mismatch "
        "that actually absorbs the pressure.\n"
        "  valuation_view    : COMPRESSED — 1 sentence HARD CAP. "
        "Format: '[ticker] trades at ~[multiple]x, implying [what rate scenario the market prices].' "
        "NOTHING ELSE. Do NOT explain rate mechanics here — that belongs in macro_sensitivity. "
        "If you write more than 1 sentence in valuation_view, you have failed the asymmetry requirement.\n"
        "  conclusion        : COMPRESSED — 2 sentences HARD CAP. Rate path + positioning only.\n"
        "CRITICAL ENFORCEMENT: valuation_view is a one-line footnote in a macro-dominant thesis. "
        "Intellectual weight belongs in macro_sensitivity and bear_thesis, nowhere else."
    ),
    "valuation": (
        "DOMINANT DIMENSION — VALUATION: Valuation IS the central debate.\n"
        "SECTION PRIORITY SCORE — HARD CAPS (enforce strictly, no exceptions):\n"
        "  valuation_view    : DEEP — 3 sentences REQUIRED. Current multiple vs historical range "
        "and peers. What the multiple ALREADY IMPLIES (growth rate, margin durability, terminal "
        "value assumption). What has to be true for re-rating — name the specific scenario and "
        "what price target follows from it.\n"
        "  bull_thesis       : DEEP — 4 sentences. Re-rating path and what has to happen. "
        "Name the catalyst and the multiple target if the bull case plays out.\n"
        "  bear_thesis       : MEDIUM — 3 sentences. Derating mechanism and trigger.\n"
        "  macro_sensitivity : COMPRESSED — 1 sentence HARD CAP. "
        "Primary macro channel only. Format: '[channel] drives [impact] on [metric].' "
        "No elaboration. If you write 2 sentences, you have failed the asymmetry requirement.\n"
        "  conclusion        : COMPRESSED — 2 sentences. Valuation entry point + positioning.\n"
        "CRITICAL ENFORCEMENT: macro_sensitivity is a one-liner in a valuation-dominant thesis. "
        "Do NOT develop macro beyond one sentence here."
    ),
    "regulatory": (
        "DOMINANT DIMENSION — REGULATORY: Regulatory risk IS the primary investment debate.\n"
        "SECTION PRIORITY SCORE — HARD CAPS (enforce strictly, no exceptions):\n"
        "  bear_thesis       : DEEP — 4 sentences REQUIRED. Mechanism + revenue impact "
        "+ timeline + trigger. Quantify the potential revenue or earnings impact in dollar or % terms. "
        "Name the specific regulatory body, the type of action, and the realistic timeline. "
        "End with the specific trigger that confirms the risk is materializing.\n"
        "  bull_thesis       : MEDIUM — 3 sentences. Probability-weighted upside if risk resolves. "
        "Name what 'resolution' looks like concretely and what the multiple re-rates to.\n"
        "  valuation_view    : MEDIUM — 2 sentences. Multiple discount for regulatory overhang. "
        "What is the stock worth if risk resolves vs what if it materializes?\n"
        "  macro_sensitivity : COMPRESSED — 1 sentence HARD CAP. "
        "Macro is secondary in a regulatory-dominant thesis — one sentence only.\n"
        "  conclusion        : COMPRESSED — 2 sentences. Regulatory path + positioning.\n"
        "CRITICAL ENFORCEMENT: regulatory risk must dominate key_risks. "
        "bear_thesis is your most specific, most detailed section."
    ),
    "capital_allocation": (
        "DOMINANT DIMENSION — CAPITAL ALLOCATION: Capital return mechanics are central.\n"
        "SECTION PRIORITY SCORE — HARD CAPS (enforce strictly, no exceptions):\n"
        "  bull_thesis       : DEEP — 4 sentences REQUIRED. Quantify buyback EPS amplification: "
        "shares outstanding reduction rate (% per year), EPS accretion at zero revenue growth, "
        "FCF yield vs cost of capital. Name the specific annual commitment amount and its "
        "ROI relative to current rates.\n"
        "  valuation_view    : MEDIUM — 2 sentences. EPS trajectory + FCF yield to support multiple.\n"
        "  bear_thesis       : MEDIUM — 3 sentences. What specifically breaks the capital return "
        "story: higher rates → lower buyback ROI? Debt refinancing risk? FCF compression? Name one.\n"
        "  macro_sensitivity : COMPRESSED — 1 sentence HARD CAP. "
        "State only: how rates affect buyback ROI or debt service cost. "
        "If you write more than 1 sentence, you have failed the asymmetry requirement.\n"
        "  conclusion        : COMPRESSED — 2 sentences. Capital return math + positioning.\n"
        "CRITICAL ENFORCEMENT: macro_sensitivity is a one-line footnote in a capital-allocation thesis."
    ),
    "operational": (
        "DOMINANT DIMENSION — OPERATIONAL: Business mechanics and margin structure are the debate.\n"
        "SECTION PRIORITY SCORE — HARD CAPS (enforce strictly, no exceptions):\n"
        "  bull_thesis       : DEEP — 4 sentences REQUIRED. Margin expansion, operating leverage, "
        "unit economics. Name the specific revenue line and margin trajectory with numbers. "
        "Quantify EPS sensitivity to the operating lever that matters most.\n"
        "  bear_thesis       : DEEP — 4 sentences REQUIRED. What breaks the margin or revenue "
        "model — name the specific cost driver or revenue headwind and its P&L pathway. "
        "End with the trigger, not with a balancing counterpoint.\n"
        "  valuation_view    : MEDIUM — 2 sentences. Multiple justified by earnings trajectory.\n"
        "  macro_sensitivity : COMPRESSED — 1 sentence HARD CAP. "
        "Only: macro impact on the key operating metric. No elaboration. One sentence.\n"
        "  conclusion        : COMPRESSED — 2 sentences. Operating inflection point + risk.\n"
        "CRITICAL ENFORCEMENT: Both bull_thesis and bear_thesis anchor on specific "
        "revenue/margin mechanics. macro_sensitivity is a one-liner."
    ),
}


def _build_section_priority_block(dominant_dim: str) -> str:
    """Return a terse section-priority reminder for the prompt task list.

    Emits a one-line reminder tied to the dominant dimension so the LLM
    keeps asymmetric depth even inside the numbered task list.
    """
    _PRIORITY_REMINDER: Dict[str, str] = {
        "macro":             "macro_sensitivity=DEEP · bear_thesis=DEEP · valuation_view=COMPRESSED",
        "valuation":         "valuation_view=DEEP · bull_thesis=DEEP · macro_sensitivity=COMPRESSED",
        "regulatory":        "bear_thesis=DEEP · bull_thesis=MEDIUM · macro_sensitivity=COMPRESSED",
        "capital_allocation":"bull_thesis=DEEP · valuation_view=MEDIUM · macro_sensitivity=COMPRESSED",
        "operational":       "bull_thesis=DEEP · bear_thesis=DEEP · macro_sensitivity=COMPRESSED",
    }
    reminder = _PRIORITY_REMINDER.get(dominant_dim, "")
    if reminder:
        return f"[SECTION PRIORITY — {dominant_dim.upper()}: {reminder}]"
    return ""


def _detect_dominant_dimension(
    macro:   "MacroSensitivity",  # type: ignore[name-defined]
    risk:    "RiskProfile",       # type: ignore[name-defined]
    valuation: "ValuationView",   # type: ignore[name-defined]
    ranked:  Optional["RankedSignalSet"] = None,  # type: ignore[name-defined]
) -> str:
    """Detect the dominant analytical dimension for this thesis.

    Uses a keyword-hit scoring approach across agent overalls and top risk signals.
    Returns the dimension name for injection into the synthesis prompt.
    Falls back to "operational" when no clear winner emerges.
    """
    scores: Dict[str, float] = {dim: 0.0 for dim in _DIMENSION_KEYWORDS}

    combined_text = " ".join([
        macro.overall or "",
        risk.overall  or "",
        valuation.overall or "",
        " ".join(risk.key_risks or []),
    ]).lower()

    for dim, keywords in _DIMENSION_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in combined_text)
        scores[dim] = float(hits)

    # Boost dimension when the macro or risk agent has low confidence
    # (unresolved uncertainty is itself the dominant issue)
    if macro.confidence < 0.58:
        scores["macro"] += 2.0
    if valuation.confidence < 0.55:
        scores["valuation"] += 1.5

    # Boost from top signal dimensions
    if ranked and ranked.top_signals:
        for sig in ranked.top_signals[:3]:
            dim = _get_signal_dimension(sig.signal)
            if dim in scores:
                scores[dim] += 0.5

    best_dim = max(scores, key=lambda d: scores[d])
    # If the winning score is < 2 the signal is too weak — fall back
    return best_dim if scores[best_dim] >= 2.0 else "operational"


# ── Evidence summary builders ─────────────────────────────────────────────────

def _evidence_block(evidence: List[RetrievedEvidence], max_items: int = 10) -> str:
    """Format top-N evidence items as a numbered block for the synthesis prompt."""
    top = sorted(evidence, key=lambda e: e.relevance_score, reverse=True)[:max_items]
    return "\n".join(
        f"[{i + 1}] {ev.title}\n    Source: {ev.source}\n    {ev.summary}"
        for i, ev in enumerate(top)
    )


def _agent_block(label: str, overall: str, confidence: float) -> str:
    """Format one agent output as a plain-text block (no markdown headings)."""
    return (
        f"{label.upper()} AGENT (confidence {confidence:.0%}):\n"
        f"{overall or 'No analysis available.'}"
    )


# ── JSON field schema description (injected into prompt) ─────────────────────

_THESIS_SCHEMA_DESCRIPTION = """\
Required JSON fields (all must be present):
  "ticker"                  : string — the company ticker symbol (e.g. "AAPL")
  "company_name"            : string — canonical company name (e.g. "Apple Inc.")
  "core_debate"             : string — ONE sentence capturing the central analytical \
question the market is currently debating for this stock. Everything else in the thesis \
should orbit this. This is NOT a summary — it is the active debate. \
Examples: "Can Services growth absorb multiple compression as rates stay higher for longer?" \
/ "Is AI capex demand durable or a one-cycle pull-forward?" \
/ "Does the regulatory overhang now outweigh the earnings trajectory?" \
Do NOT write a statement — write the debate as an open question.
  "core_market_debate"      : string — ONE sentence phrased as a PM would in an IC meeting. \
This is the live POSITIONING question — what the market has or has not priced, what would \
change positioning, what is consensus vs non-consensus. NOT explanatory or academic. \
NOT "The market is debating whether..." — lead directly with the tension. \
Examples: "Is Services growth durable enough to offset hardware cyclicality?" \
/ "Is Nvidia demand structural or peak-cycle behavior?" \
/ "Can Meta sustain margin discipline while reaccelerating capex?" \
/ "Is the market underestimating rate duration risk for Apple?" \
Sound like a real PM discussion topic, not a research abstract.
  "direct_answer"           : string — 2 sentences that directly answer the user's exact \
question. MUST open with the mechanism. MUST name one company-specific offset or amplifier. \
MUST NOT open with a generic company overview.
  "bull_thesis"             : string — 3-4 sentence institutional bull case. \
Sentence 1: primary upside driver with economic transmission mechanism. \
Sentence 2: operating leverage, margin structure, or capital allocation effect that amplifies it. \
Sentence 3: valuation anchor — what multiple is fair if the bull case plays out and why. \
Sentence 4 (optional): the specific event or data point that confirms the thesis.
  "bear_thesis"             : string — 3-4 sentence institutional bear case. \
Sentence 1: primary risk with HOW it breaks the thesis (transmission mechanism to EPS/FCF). \
Sentence 2: second-order effect (e.g. buyback ROI falls as rates rise, OR channel inventory \
builds as demand softens, compounding margin pressure). \
Sentence 3: realistic downside pathway — what multiple/EPS scenario materialises and why. \
Sentence 4 (optional): the specific catalyst that triggers the bear case.
  "key_drivers"             : array of 4 strings — top value drivers, ranked by importance
  "key_risks"               : array of 4 strings — top investment risks, ranked by severity
  "valuation_view"          : string — 2 sentences on valuation structure. \
Sentence 1: state the current or target multiple, vs historical range and peers, and what the \
market is implicitly pricing in (growth rate, margin trajectory, or terminal value assumption). \
Sentence 2: segment economics or sensitivity — how the blended multiple could expand or compress \
and what has to be true for each scenario.
  "macro_sensitivity"       : string — 2 sentences on macro transmission. \
Sentence 1: primary transmission pathway with direction and channel \
(e.g. rates → discount rate → DCF impact on long-duration cash flows; \
FX → international revenue mix → reported EPS). \
Sentence 2: magnitude and directional bias — quantify the sensitivity where possible \
(100bps rate move ≈ X% P/E compression; 10% USD appreciation ≈ Y% revenue headwind \
on international segment).
  "confidence_score"        : number between 0.0 and 1.0. Be genuinely conservative: \
score 0.80+ ONLY when macro, risk, AND evidence all clearly agree. If macro or regulatory \
uncertainty is real and unresolved, cap yourself at 0.72. If evidence is sparse, cap at 0.65. \
The score should reflect what you could defend in an IC meeting, not an optimistic read.
  "confidence_reasoning"    : string — 2-3 sentences of honest analyst-style uncertainty. \
Name what IS clear and WHY, then name specifically what is NOT resolved and why it matters \
for the investment decision. Do NOT: cite agent names, percentages, or signal counts. \
Do NOT produce symmetrical hedging — experienced analysts anchor on the dominant uncertainty, \
not a balanced list. Do NOT say "confidence is high" or "conviction remains strong". \
GOOD: "The operational case is clear at current margins; what is harder to call is whether \
rate duration pressure resolves before the multiple needs to reflect it." \
GOOD: "Services margin trajectory is well-evidenced; the China regulatory path and the rate \
path are both genuinely hard to size — that is where the bear case lives, not in the core thesis." \
GOOD: "The earnings are straightforward. The risk is in how the market reprices duration \
at higher rates — and that is not yet resolved." \
BAD: "Confidence is high." / "Conviction remains strong." / "Evidence is directionally constructive."
CONFIDENCE LANGUAGE ALIGNMENT — MANDATORY:
  confidence_score ≥ 0.82 → you MAY use: "constructive", "directionally clear"
  confidence_score 0.70–0.81 → use: "cautiously constructive", "leaning positive", "improving"
  confidence_score 0.55–0.69 → use: "balanced", "two-sided", "residual uncertainty"
  confidence_score < 0.55 → use: "low conviction", "genuinely uncertain", "hard to call"
  NEVER use regardless of score: "high conviction", "strong conviction", "highly constructive",
  "confidence remains high", "elevated conviction", "well-supported thesis"
  The PROSE must match the SCORE — a 0.68 score that says "high conviction" is a contradiction.
  "what_changes_the_thesis" : array of 4 strings — company-specific triggers that flip the thesis
  "conclusion"              : string — institutional-quality 2-sentence conclusion. \
MUST name specific revenue drivers, risks, and valuation factors. Must NOT contain generic phrases."""


# ── Synthesis prompt ──────────────────────────────────────────────────────────

def _build_synthesis_prompt(
    company: CompanyContext,
    valuation: ValuationView,
    macro: MacroSensitivity,
    risk: RiskProfile,
    market: MarketContext,
    quality: QualityAssessment,
    evidence: List[RetrievedEvidence],
    profile: Optional[CompanyKnowledgeProfile] = None,
    original_user_question: Optional[str] = None,
    ranked: Optional[RankedSignalSet] = None,
    prior_snapshot=None,  # Optional[ThesisSnapshot] — avoid circular import
) -> str:
    # Plain-text agent summaries — NO markdown headings to avoid bleeding into output
    agent_summaries = "\n\n".join([
        _agent_block("Valuation", valuation.overall, valuation.confidence),
        _agent_block("Macro Sensitivity", macro.overall, macro.confidence),
        _agent_block("Risk Profile", risk.overall, risk.confidence),
        _agent_block("Market Context", market.overall, market.confidence),
        _agent_block("Business Quality", quality.overall, quality.confidence),
    ])

    key_risks_txt = "\n".join(f"- {r}" for r in risk.key_risks) or "None identified."
    catalysts_txt = "\n".join(f"- {c}" for c in market.recent_catalysts) or "None identified."
    ev_block = _evidence_block(evidence)

    ticker = company.ticker

    # Build the ranked-signals injection block
    if ranked is not None and (ranked.top_signals or ranked.top_risks):
        signal_lines = []
        for i, sig in enumerate(ranked.top_signals[:3], 1):
            signal_lines.append(
                f"  SIGNAL {i} [{sig.signal_type.upper()}/{sig.direction.upper()}"
                f"/impact={sig.impact_score:.1f}]: {sig.signal}"
            )
        for i, sig in enumerate(ranked.top_risks[:3], 1):
            signal_lines.append(
                f"  RISK {i} [RISK/BEARISH/impact={sig.impact_score:.1f}]: {sig.signal}"
            )
        ranked_signals_section = (
            "PRE-RANKED SIGNALS (prioritize these — ranked by composite importance):\n"
            + "\n".join(signal_lines)
            + "\nYour synthesis MUST address each of these signals explicitly.\n"
        )
    else:
        ranked_signals_section = ""

    # Optional company business model section
    if profile is not None:
        biz_model_section = (
            f"COMPANY BUSINESS MODEL (ground every claim in this):\n"
            f"Business model: {profile.business_model}\n"
            f"Primary revenue drivers: {', '.join(profile.primary_revenue_drivers)}\n"
            f"Recurring revenue: {', '.join(profile.recurring_revenue_sources)}\n"
            f"Valuation style: {profile.valuation_style}\n"
            f"Key metrics: {', '.join(profile.key_metrics)}\n"
            f"Competitive advantages: {'; '.join(profile.competitive_advantages)}\n"
            f"Rate sensitivity: {profile.rate_sensitivity_note}\n"
        )
        profile_keywords_hint = (
            f"Required terms include: {', '.join(profile.business_model_keywords[:8])}."
            if profile.business_model_keywords
            else ""
        )
    else:
        biz_model_section = ""
        profile_keywords_hint = ""

    # Detect dominant analytical dimension for asymmetric depth allocation (R2)
    dominant_dim         = _detect_dominant_dimension(macro, risk, valuation, ranked)
    dominant_dim_block   = _DEPTH_DIRECTIVES.get(dominant_dim, "")
    section_priority_tag = _build_section_priority_block(dominant_dim)

    # Confidence language alignment tag — surfaces the right qualifier tier in prompt
    conf_avg = (
        valuation.confidence + macro.confidence + risk.confidence
        + market.confidence + quality.confidence
    ) / 5.0
    if conf_avg >= 0.82:
        conf_lang_tier = "constructive | directionally clear"
    elif conf_avg >= 0.70:
        conf_lang_tier = "cautiously constructive | leaning positive | improving"
    elif conf_avg >= 0.55:
        conf_lang_tier = "balanced | two-sided | still unresolved"
    else:
        conf_lang_tier = "low conviction | genuinely uncertain | hard to call"

    # Build historical reasoning block (injected when a prior thesis snapshot exists)
    if prior_snapshot is not None:
        prev_confidence = getattr(prior_snapshot, "confidence_score", 0.0) or 0.0
        prev_thesis     = getattr(prior_snapshot, "one_sentence_thesis", "") or ""
        prev_bull       = getattr(prior_snapshot, "bull_thesis", "") or ""
        prev_conclusion = getattr(prior_snapshot, "conclusion", "") or ""
        prev_debate     = getattr(prior_snapshot, "core_debate", "") or ""
        prev_risks_txt  = "; ".join((getattr(prior_snapshot, "key_risks_text", []) or [])[:3])
        prev_ts         = (getattr(prior_snapshot, "timestamp", "") or "prior analysis")[:10]
        historical_reasoning_block = (
            f"\nHISTORICAL CONTEXT — PRIOR THESIS (as of {prev_ts}):\n"
            f"Prior thesis: {prev_thesis or prev_conclusion[:120] or '(none recorded)'}\n"
            f"Prior bull thesis (first sentence): {prev_bull[:150] or '(none)'}\n"
            f"Prior core debate: {prev_debate or '(none)'}\n"
            f"Prior confidence: {prev_confidence:.0%}\n"
            f"Prior top risks: {prev_risks_txt or '(none)'}\n\n"
            f"HISTORICAL REASONING — MANDATORY:\n"
            f"You have access to the prior thesis. You MUST reason over what changed.\n"
            f"In your conclusion and confidence_reasoning, address:\n"
            f"  1. Whether the operating story changed (new information) or the market repriced "
            f"the same thesis (rate/macro shift without fundamental change).\n"
            f"  2. Whether the core debate evolved, narrowed, or intensified.\n"
            f"  3. Whether the original thesis mechanism still holds, weakened, or broke.\n"
            f"GOOD HISTORICAL LANGUAGE (use these patterns):\n"
            f'  "The operating story is largely unchanged — the repricing came from rates."\n'
            f'  "The thesis weakened because the original margin assumption no longer holds."\n'
            f'  "The debate narrowed from [X] toward [Y] — the market resolved the prior ambiguity."\n'
            f'  "The burden shifted — [prior mechanism] is no longer the dominant driver."\n'
            f'  "Consensus already adjusted for [prior bear case]. The residual risk is [new concern]."\n'
            f"BANNED HISTORICAL LANGUAGE:\n"
            f'  "confidence decreased" → state what changed and why\n'
            f'  "signals diverged" → name which forces diverged and what that means\n'
            f'  "analysis changed" → state the specific mechanism that moved\n'
            f'  "thesis updated" → explain the actual analytical shift\n\n'
        )
    else:
        historical_reasoning_block = ""

    # Build the question-anchor block (injected only when a question is present)
    if original_user_question:
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"QUESTION-ANCHORED DIRECT ANSWER RULES (mandatory for \"direct_answer\" field):\n"
            f"- Sentence 1: State the PRIMARY mechanism by which this factor affects "
            f"{company.company_name} ({ticker}). Be concrete and specific "
            f'(e.g. "Higher rates compress {ticker}\'s ~28x P/E multiple because '
            f'long-duration cash flows are discounted at a higher rate.").\n'
            f"- Sentence 2: Name at least one {ticker}-specific offset, amplifier, or nuance "
            f"(e.g. Services recurring revenue, buyback program, net-cash balance sheet, "
            f"installed base, iPhone demand elasticity).\n"
            f"- FORBIDDEN: Opening with a generic company description "
            f'("Apple is a technology company…" or "Apple Inc. is a leading…").\n'
            f"- FORBIDDEN: Answering a different question than the one asked.\n"
            f"- REQUIRED: The mechanism must trace directly to {ticker}'s actual "
            f"business model and the macro/sector factor in the question.\n\n"
        )
    else:
        question_anchor_block = ""

    return f"""You are a senior investment analyst producing an institutional-quality investment thesis.

CRITICAL OUTPUT RULES — READ FIRST:
- You MUST return ONLY a single valid JSON object.
- Do NOT write any markdown headings, prose, or text outside the JSON.
- Do NOT use markdown code fences (no ```json or ```).
- Do NOT write "Investment Thesis for...", "Bull Case:", "Bear Case:" or any other headings.
- Your ENTIRE response must start with {{ and end with }}.
- Any non-JSON output will cause a parse failure.

COMPANY: {company.company_name} ({ticker})
Sector: {company.sector or "Unknown"} | Industry: {company.industry or "Unknown"}

{biz_model_section}
{historical_reasoning_block}{question_anchor_block}{ranked_signals_section}
SPECIALIST AGENT OUTPUTS:
{agent_summaries}

Key Risks Identified:
{key_risks_txt}

Recent Catalysts:
{catalysts_txt}

SUPPORTING EVIDENCE:
{ev_block}

STOCK-MOVEMENT ORIENTATION — MANDATORY FOR ALL SECTIONS:
Every sentence must answer "What moves the stock?" — NOT "What describes the company?"

HIERARCHICAL DENSITY REQUIREMENT:
- direct_answer, conclusion → ultra-compressed, 2 sentences, mechanism + so-what only
- bull_thesis, bear_thesis → analytical depth layer: explain WHY the thesis works / breaks
  economically. Include operating leverage, capital structure, and second-order effects.
  Do NOT compress these to assertion-level. A 3-4 sentence analytical paragraph is correct.
- valuation_view, macro_sensitivity → 2 sentences each: state the structure and the
  sensitivity logic. Not a one-liner assertion — a complete analytical thought.

REQUIRED in bull_thesis, bear_thesis, valuation_view, macro_sensitivity:
- Explicit mechanism: X factor → Y stock effect (name the transmission)
- Earnings/EPS/FCF impact quantified wherever possible
- Valuation multiple pressure named (compression or expansion, with current multiple)
- Catalyst specificity: name the event that triggers or proves the thesis
- Second-order effects in bear_thesis (what compounds the primary risk)
- What the market is implicitly pricing in valuation_view

BANNED across ALL prose sections:
- Encyclopedic company descriptions ("Apple designs and sells iPhones…")
- Static revenue facts without impact ("iPhone is 52% of revenue")
- Generic moat language ("wide moat", "durable competitive advantage")
- Descriptive superlatives without mechanism ("Apple is the world's most valuable…")
- Filler assessments ("well-positioned", "strong company", "industry leader")

TRANSFORM this way:
  BAD: "Apple's iPhone segment represents 52% of total revenue."
  GOOD: "iPhone demand elasticity means a 5-point unit decline compresses blended EPS by ~8%."
  BAD: "Apple has a robust ecosystem."
  GOOD: "iOS switching costs anchor 95%+ upgrade retention, sustaining Services ARPU at $10+/month."

INSTITUTIONAL TONE — MANDATORY:
Write every sentence as a buy-side analyst memo, not a company overview or AI summary.
Hedge fund memo tone: compressed, causal, mechanism-first.

SENTENCE STRUCTURE: Mechanism → Specific data point → So-what for {ticker}'s P&L or valuation.
  BAD: "Apple Services margin offsets compression."
  GOOD: "Recurring Services cash flows (72% gross margin, ~$100B ARR) partially absorb \
rate-driven P/E multiple pressure on the lower-margin hardware segment."

  BAD: "The company remains well positioned in its key markets."
  GOOD: "{ticker}'s $165B net-cash position and $90B annual buyback sustain EPS even \
as hardware revenue faces credit-cycle headwinds."

  BAD: "This indicates positive momentum going forward."
  GOOD: "The acceleration in Services attach rates since iOS 17 signals upsell runway \
that sell-side estimates have not yet captured."

FORBIDDEN PHRASES — remove every instance:
- "well positioned", "well-positioned" → say specifically HOW
- "strong company", "solid fundamentals" → cite the actual metric
- "industry leader" → cite market share % or competitive mechanism
- "robust ecosystem" → name the specific lock-in and switching cost estimate
- "faces challenges" → name the challenge and its P&L transmission mechanism
- "investors should monitor" → name the exact data point and threshold
- "going forward", "moving forward" → remove; state the mechanism directly
- "this indicates", "this shows" → replace with the specific inference
- "the company remains" → replace with stock-level framing ("the stock maintains")
- "continues to benefit" → explain HOW and WHY the benefit accrues
- "poised to", "positioned for" → replace with specific catalyst or trigger
- "a testament to", "speaks to the" → replace with direct causal statement

REQUIRED language: causal chains, specific metrics, named transmission mechanisms,
asymmetry analysis, stock-price relevance in every sentence.

TERMINAL DENSITY — MANDATORY:
Write at Bloomberg terminal / hedge-fund IC-memo density. Remove ALL of the following:
- Explanatory transitions ("This means that…", "In other words…", "It follows that…")
- Educational framing ("It is worth understanding that…", "An important factor to consider…")
- Introductory padding ("One of the key factors is…", "It should be noted that…")
- Summary restaters ("Overall,", "On balance,", "Taken together,", "In conclusion,")
- Weak hedges that repeat prior content ("It is also worth noting that X already mentioned…")
Each sentence MUST convey a mechanism AND imply stock impact AND compress interpretation.
No sentence may exist solely to introduce or summarise another sentence.

PM-GRADE LANGUAGE — MANDATORY:
Replace educational finance terms with direct, understated analyst phrasing:
- "strong margins" → "stable margins" or "the margin structure holds"
- "pricing power" → "pricing discipline" or name the specific mechanism
- "provides a buffer" → "limits downside" or "provides cover"
- "premium valuation" → "full valuation" or "trades at a premium to peers"
- "high gross margin" → "structurally high margin"
- "supports valuation" → "supports the multiple"
- "impacting revenue" → "pressuring earnings"

AVOID these AI-synthetic phrases — they sound machine-assembled, not analyst-written:
- "directionally constructive" → say what is specifically positive
- "structurally repriced" → "repriced"
- "self-reinforcing" → "compounding" or describe the flywheel concretely
- "asymmetric upside" → "favorable risk/reward" or state the actual asymmetry
- "favorable backdrop" → name the actual macro condition
- "durable growth vector" → "growth driver"
- "constructive setup" → describe specifically why the setup is favorable
- "inflects operating leverage" → "shifts the earnings mix" or be direct
- "stabilizing offset" → "partial offset"
- "keeps conviction below high" → "limits conviction"
- "affect the multiple in opposite directions" → describe specifically what each force does

confidence_reasoning MUST read like a PM note, not a scoring report.
No signal counts, no agent names, no generic hedges, no symmetrical framing.
  BAD: "8 bullish vs 4 bearish signals across 12 ranked signals."
  BAD: "Evidence is directionally constructive but headwinds remain."
  GOOD: "The valuation case is clear at these earnings; what is harder to call is
         whether rate sensitivity matters enough at current multiples to compress the stock."
  GOOD: "Services margin trajectory is well-evidenced by trailing results; China regulatory
         risk remains genuinely hard to size — which is where most downside optionality lives."

STRUCTURAL VARIETY — MANDATORY:
Never use the same opening sentence template across more than one section.
- BAD (bull_thesis AND conclusion both open with): "[Ticker]'s Services supports valuation despite rate pressure."
- REQUIRED: Vary subject position, causal framing, and emphasis across sections:
  bull_thesis      → lead with the upside mechanism or asymmetry
  bear_thesis      → lead with the transmission mechanism (NOT "the risk is…")
  conclusion       → lead with the inflection condition or current positioning
  valuation_view   → state the multiple first, then the scenario it implies
  macro_sensitivity → state the specific sensitivity channel first, then magnitude
FORBIDDEN: the same subject+verb pattern used to open more than two prose sections.

SECTION ASYMMETRY — MANDATORY:
Do not develop every section equally. Allocate depth to the mechanism that matters most.
- If macro is the primary driver (e.g. rate impact on a rate-sensitive stock): deepen
  macro_sensitivity; valuation_view can be one crisp sentence stating the multiple
- If valuation is the core thesis (e.g. cheap vs. peers): deepen valuation_view; macro
  can be stated in one sentence
- If one risk clearly dominates: bear_thesis should be your most specific, detailed section
- Secondary or weaker factors: state briefly — do not pad them to match the dominant section
A well-written IC memo is naturally asymmetric. Equal section length signals AI writing.

NATURALNESS — MANDATORY:
Sound like an experienced analyst writing for a PM, not an AI generating institutional prose.
- Vary sentence length: not every sentence needs to be maximally dense
- Allow plain-English when it is more precise than jargon:
    "The earnings are straightforward" > "Evidence base is conclusive"
    "This is where the real risk is" > "This represents the primary downside catalyst"
    "The multiple looks full here" > "Valuation appears elevated at current levels"
    "Risk/reward looks reasonable" > "Asymmetric upside opportunity"
- Experienced PMs are understated — they do not oversell their own theses
- Avoid: "compelling opportunity", "significant upside potential", "strong conviction"
- Prefer: "risk/reward looks reasonable if…", "conviction sits at moderate"
- DO NOT produce sentences that exist solely to sound institutional
FORBIDDEN: Any phrase that sounds engineered to impress rather than to inform.

WRITING RHYTHM AND CADENCE VARIATION — MANDATORY:
Vary sentence length and structure within and across sections.
- Not every sentence must be maximally dense or long.
- Use short, blunt sentences to land key analytical judgments:
    "The earnings are clean." / "The multiple looks full." / "China risk is real and unresolved."
- Mix: [short blunt claim] + [longer mechanism sentence] + [short so-what].
- Never write three consecutive sentences of the same approximate length and structure.
- Experienced analysts are understated — do NOT end every section with an emphatic assertion.
- A good bear_thesis often ends on a simple, understated note: "The timing is the question."
- A good bull_thesis often ends with a concrete confirmation signal, not a sweeping conclusion.
CADENCE_VARIATION — specific requirements:
- bull_thesis MUST contain at least one sentence ≤ 12 words (forces compression somewhere).
- bear_thesis MUST NOT end with a conjunctive clause ("which means...", "and therefore...").
- conclusion MUST NOT begin with "[Ticker]'s [noun phrase] provides/supports/sustains/enables..."
- A section CAN end with a blunt one-liner if the point is already made.
- Sections should feel uneven — not every section builds to a tidy multi-clause conclusion.
GOOD CADENCE EXAMPLES (study the rhythm — varied lengths, abrupt endings):
  "Rates matter more than consensus expects. The 28x multiple assumes a normalization path that has not started. That is the risk."
  "The operating story holds. Services mix shifts toward recurring cash flows, and the buyback absorbs what hardware cannot. The question is whether the market reprices duration before the next print."
  "Nothing is broken yet. The bear case requires both a hardware cycle AND rate re-acceleration. That overlap is the tail risk."
BAD CADENCE: Three consecutive long mechanism sentences all ending with "...which supports valuation."

TEMPORAL REALISM — MANDATORY:
Reason about what is already priced in vs what is genuinely new or unresolved:
- What recent development (last 30-90 days) has the market NOT fully priced in yet?
- What catalyst or data point is the current active market debate — and which side is more likely?
- Separate near-term stock movement (6-12m) from long-term value creation (3-5yr) when they diverge.
- Avoid claims that are always or perpetually true — anchor on what has CHANGED or is CHANGING.
- "The multiple already reflects X" is a valid and useful claim when it is true — make it.
- "The market is debating Y" names the live controversy — name it explicitly in core_market_debate.
TEMPORAL ANCHORING — write as if this memo was produced this week, not as a reference document:
- Use grounding language where appropriate: "recently", "over the last quarter", "since rates repriced",
  "this cycle", "right now", "at current levels", "over the last 90 days", "since [event]"
- BAD (timeless): "Apple faces rate sensitivity as a high-duration growth stock."
- GOOD (time-anchored): "Since the rate path repriced, duration pressure has reasserted on AAPL's ~28x multiple."
- Use 2-3 temporal markers across the thesis — not uniformly in every sentence.

PRICED_IN_REASONING — MANDATORY:
Every major thesis element must answer: "Is this already priced in, or would this move the stock?"
Specifically in valuation_view and bull_thesis:
- State what the current multiple ALREADY IMPLIES (growth rate, margin durability, rate scenario)
- Name one thing the market has already priced (consensus view)
- Name one thing the market has NOT yet fully priced (where positioning could change)
REQUIRED phrases to use where analytically true (pick 2-3 across the thesis):
- "The stock already prices in X" / "At ~[multiple]x, the market is paying for Y"
- "Incremental upside requires Z, not just X" / "The market has not yet resolved X"
- "Consensus already assumes X — the differentiated call is Y"
GOOD: "At ~28x, the stock already prices Services durability — incremental upside requires margin acceleration, not merely stability."
GOOD: "The multiple implies a soft landing; any rate re-acceleration would be unpriced and de-rating."
BAD: "Strong Services margins support the valuation." (timeless, no priced/unpriced distinction)
BAD: "The stock is attractively valued." (states no view on what's in the price)

MECHANISM_PRIORITY — MANDATORY:
Every causal claim must name the TRANSMISSION PATH, not the outcome abstraction.
BANNED mechanism abstractions (replace with the actual transmission):
- "offsets the pressure" → HOW does it offset? (e.g. "Services recurring FCF absorbs the ~8% EPS hit from hardware unit declines")
- "stabilizes valuation" → WHAT stabilizes it? ("$90B buyback compresses share count, sustaining EPS at zero revenue growth")
- "cushions downside" → WHAT is the cushion mechanism? ("net cash of $165B covers 18 months of buyback even if FCF halves")
- "supports resilience" → HOW? name the specific financial buffer
- "enhances profitability" → WHICH line item, by how much, through what mechanism
- "pricing power" → name the specific ASP/volume/take-rate mechanism that enables it
- "durable growth" → WHY is it durable? name the structural driver (lock-in, switching cost, contract length)
Every sentence must trace X → Y → stock impact. No abstraction layer.

IMPLICATION_COMPRESSION — MANDATORY:
Stop writing once the analytical implication is obvious. Real PMs trust their readers.
BANNED completeness patterns (remove the symmetric balancing clause):
- "The multiple could expand if X, but compress if Y" → pick the more probable scenario:
  "At ~28x, the market already prices X" — STOP THERE.
- "Either X or Y depending on which scenario materializes" → state the more likely outcome.
- Any sentence that adds a balanced counterpoint to an already-clear directional statement.
- Trailing ", which could affect the multiple in either direction" → cut before this.
STOP WRITING (these are complete sentences — do not add a balancing clause after them):
  "The risk is duration. Everything else is secondary."
  "At ~28x, execution has to be exceptional."
  "Nothing is broken yet."
  "China matters more than investors admit."
  "The market still has not priced the demand normalization question."
  "That is what the multiple is paying for."
BAD (adds a hedge after a clear point):
  "Services ARR supports the multiple, but could compress if regulatory pressure intensifies."
BETTER: "Services ARR supports the multiple. Regulatory overhang is the separate unpriced risk."
(Two clean statements beat one hedged compound sentence.)
Brevity signals conviction. Symmetric completeness signals AI-generated analysis.

HIDDEN-PROCESS BAN — MANDATORY:
You are an analyst writing a MEMO, not narrating your reasoning process.
BANNED (these expose internal process, not analytical conclusions):
- "signals converge" → say what the conclusion IS
- "evidence supports the thesis" → cite the specific evidence and its implication
- "analysis indicates" → state the conclusion directly
- "multiple factors suggest" → name the dominant one and its mechanism
- "conviction remains elevated" → say what makes it defensible or challenging
- "all point in the same direction" → state the shared direction and WHY it matters
- "cross-agent" / "agent outputs" / "agents agree" → NEVER surface process mechanics
- "analytically constructive" → say what is constructive and HOW
- "broadly aligned" → name what is aligned and what is not
- "directional alignment" → state the direction and the mechanism
GOOD: "The earnings path still holds unless rates remain structurally restrictive."
GOOD: "The market is paying for durability, not near-term growth — and durability is hard to prove."
GOOD: "The bear case only matters if hardware weakness becomes cyclical rather than temporary."
Additional orchestration leakage — BANNED (Phase D extensions):
- "signals are split" → "the picture is genuinely two-sided"
- "signals diverge" → name which forces diverge and what that means for the thesis
- "directional disagreement" → "the bull and bear cases are both defensible here"
- "analytical disagreement" → name the specific unresolved question
- "confidence is reduced because" → name the uncertainty: "the macro path is unresolved"
- "constructive vs cautious" → state which view is dominant and what flips it
- "evidence count" → never reference counts; reference what the evidence shows
- "two forces affect the multiple in opposite directions" → name each force separately with its net effect
- "depending on which scenario" → pick the more probable scenario and name it

CONFIDENCE LANGUAGE ALIGNMENT — MANDATORY:
This thesis has an estimated confidence tier: {conf_lang_tier}
Your confidence_reasoning and conclusion MUST use language from this tier.
DO NOT use "high conviction" or "strong conviction" unless confidence_score ≥ 0.82.
DO NOT end confidence_reasoning with an upbeat conclusion that contradicts a low score.
If you assign confidence_score < 0.70, the prose MUST name what is genuinely uncertain.
The writing must match the score. A 0.65 that says "the thesis is well-supported" is a contradiction.
UNDERSTATED CONFIDENCE — MANDATORY (applies even when bullish):
Even at high confidence, use measured language. The mechanism sells the thesis — not the adjective.
BANNED regardless of confidence_score:
- "highly compelling" → say what makes the risk/reward reasonable
- "strongly bullish" → "constructive" or state the mechanism
- "exceptional opportunity" → "reasonable opportunity if X holds"
- "robust thesis" → "defensible thesis"
- "exceptional investment case" → name the specific mechanism that makes it work
GOOD understated bullish language (study these):
  "The thesis still works."  /  "The setup remains constructive."  /  "Nothing is broken yet."
  "Risk/reward looks reasonable here if the rate path cooperates."
  "At these levels, if Services ARR holds, the stock works."
An experienced PM who is genuinely bullish does not say "highly compelling" — they name the mechanism
and let the math speak. Emphatic conviction language is the hallmark of AI-generated finance prose.

IMPLICIT CONVICTION — MANDATORY (applies to ALL sections):
State the mechanism. Let the implication remain unstated. The reader is an experienced investor.
BANNED explicit conviction declarations (replace with mechanism + positioning language):
- "conviction is high" → "the core debate is narrower now"
- "conviction remains" → "the setup holds" or "nothing is broken yet"
- "analysis converges" → state WHAT the dominant picture is, not that it converges
- "all factors point to" → name the DOMINANT factor and its transmission
- "therefore investors should" → STOP. End the sentence at the mechanism.
- "this supports the investment thesis" → state WHAT specifically it supports
- "this confirms the thesis" → "the thesis holds" or end the section there
- "this means [X]" → start with [X] directly; delete the framing clause
IMPLICIT CONVICTION PATTERNS — study these as models:
  "The core debate is narrower now." (replaces: "conviction is high — all factors converge")
  "Most uncertainty sits around duration, not direction." (replaces: "the thesis is well-supported but rate risk remains")
  "The burden now shifts to execution." (replaces: "strong conviction; therefore investors should monitor delivery")
  "That is the risk." (replaces: "this means the stock could underperform if X does not hold")
  "The market still needs to see that." (replaces: "this confirms the thesis is on track")
  "Duration matters more here than direction." (replaces: "analysis converges on a constructive view with timing uncertainty")

SELECTIVE INCOMPLETENESS — MANDATORY:
Real PM memos STOP before the obvious conclusion. The mechanism is stated; the implication is
self-evident to an experienced reader. Do NOT add a conclusory wrap-up sentence.
BANNED CLOSING PATTERNS — strip these from section endings:
- "Therefore, investors should [X]." → end at the mechanism name
- "This means [implication]." → state the mechanism; delete the framing
- "This creates a [type] outlook." → name the specific tension, not the category
- "This supports the investment thesis." → state what it supports, then stop
- "All factors point to [conclusion]." → name the dominant factor and magnitude, then stop
- Any sentence that begins "In conclusion," or "Overall," or "In summary," — DELETE IT
STOP-EARLY PATTERNS — use these to close sections naturally:
  "That is the risk." · "The market still needs to see that."
  "Duration matters more here." · "The setup holds if that holds."
  "That is what the thesis requires." · "The question is timing, not direction."
  "Nothing is broken yet." · "That is what would change the view."
PM RESTRAINT RULE: If your last sentence summarizes what the previous sentences said, delete it.
If your last sentence begins with "This means", "Therefore", or "This creates", delete it and
end one sentence earlier. The strongest IC memos end on a mechanism, not a conclusion.

AGENT CONFLICT ANALYSIS:
Before synthesising, identify any disagreements between agents:
- Does valuation say cheap while risk says high debt? (value trap risk)
- Does macro say rate cuts imminent while quality says margin pressures building?
- Does market say bullish catalysts while risk says near-term headwinds?
Explicitly address each conflict in your bull/bear thesis text.

{dominant_dim_block}

TASK — produce a JSON object with exactly these fields:
{section_priority_tag}

0. core_debate: ONE sentence — the single central analytical question the market is currently
   debating for {ticker}. Write it as an OPEN QUESTION, not a statement. This is the lens
   through which everything else should be read. Examples:
   "Can Services growth absorb multiple compression as rates stay higher for longer?"
   "Is AI capex demand durable or a one-cycle pull-forward?"
   "Does the regulatory overhang now outweigh the earnings trajectory?"
   NOT: "Apple faces rate headwinds." (statement) — MUST be an open question.

0.5. core_market_debate: ONE sentence — phrased as a PM would in an IC meeting discussion.
   This is the live POSITIONING question: what the market has/has not priced in, what would
   change positioning, consensus vs non-consensus. NOT explanatory. Lead with the tension.
   Examples: "Is Services growth durable enough to offset hardware cyclicality?"
   "Is Nvidia demand structural or peak-cycle behavior?"
   "Can Meta sustain margin discipline while reaccelerating capex?"
   "Is the market underestimating rate duration risk for Apple?"
   BAD: "The market is debating whether..." — lead directly with the question.

1. direct_answer: 2 sentences — mechanism + company-specific offset (see QUESTION-ANCHORED
   DIRECT ANSWER RULES above). Ultra-compressed. No elaboration.

2. bull_thesis: 3-4 sentences of institutional bull reasoning.
   Sentence 1 — UPSIDE MECHANISM: Lead with the primary driver and its economic transmission
   (e.g. "Services gross margin mix expanding to ~35% of revenue inflects blended operating
   leverage, driving EPS growth that is structurally decoupled from hardware unit cycles.").
   Sentence 2 — AMPLIFIER: Name the operating leverage, capital allocation, or cost structure
   effect that makes the bull case self-reinforcing (e.g. "$90B buyback on declining share
   count amplifies EPS even at zero revenue growth.").
   Sentence 3 — VALUATION ANCHOR: What multiple is justified if the bull case plays out, and
   what has to be true (e.g. "At 25-28x forward P/E the stock is fairly valued IF Services
   ARR sustains double-digit growth.").
   Sentence 4 (OPTIONAL) — CONFIRMATION: The specific data point or event that proves the bull
   case is on track.
   MUST cite at least one named {company.company_name} segment or product. MUST include a
   specific multiple or financial metric. Do NOT open with "The company…" or "[Ticker]'s
   [noun phrase] provides…" — lead with the economic mechanism.

3. bear_thesis: 3-4 sentences of institutional bear reasoning.
   Sentence 1 — TRANSMISSION: Lead with HOW the primary risk breaks the thesis — name the
   specific transmission mechanism to EPS or FCF (e.g. "A sustained 100bps rate increase
   compresses {ticker}'s 28x P/E to ~22-24x via DCF discount-rate expansion, a ~15-20%
   valuation headwind even with earnings unchanged.").
   Sentence 2 — SECOND-ORDER EFFECT: Name the compounding force (e.g. "As rates rise, the
   $90B buyback ROI deteriorates relative to debt service costs, blunting EPS support at
   exactly the point multiple compression requires it.").
   Sentence 3 — DOWNSIDE PATHWAY: The realistic magnitude and sequence (e.g. "If hardware
   demand softens simultaneously — a plausible outcome at higher consumer credit costs —
   blended EPS could compress 10-15%, producing a double headwind on a compressed multiple.").
   Sentence 4 (OPTIONAL) — CATALYST: The specific event that triggers the bear case.
   MUST name a specific risk mechanism. Do NOT open with "The risk is…" or "There is a
   risk that…" — lead with the transmission.

4. key_drivers: exactly 4 drivers, ranked by importance, phrased as "{ticker}-specific: X"
5. key_risks: exactly 4 risks, ranked by severity, with company-specific transmission.

6. valuation_view: 2 sentences on valuation structure — not generic.
   Sentence 1: State current or target multiple vs historical range / peers, and what the
   market is implicitly pricing (growth rate, margin trajectory, or terminal FCF assumption).
   Sentence 2: Explain how the blended multiple could move — which segments drive expansion
   or compression, and what has to be true for each scenario.

7. macro_sensitivity: 2 sentences on specific macro transmission pathways.
   Sentence 1: Primary channel with direction (rates → discount rate → DCF impact on
   long-duration FCF; FX → international revenue conversion → EPS; consumer demand →
   ASP/unit volumes → blended margin). Name the SPECIFIC {ticker} revenue lines affected.
   Sentence 2: Magnitude — quantify sensitivity where possible (100bps move ≈ X% impact
   on P/E; 10% USD move ≈ Y% revenue headwind on international segment).

8. confidence_score: 0.0-1.0. Penalise for low-confidence agent inputs and sparse evidence.

9. confidence_reasoning: 2-3 sentences of analyst-style uncertainty — PM note, not scoring report.
   Name: (a) what evidence IS established and why it's reliable, (b) what IS NOT resolved
   and what makes it genuinely uncertain, (c) any cyclical vs structural tension if real.
   Sound understated and experienced — like someone who has read the filings, not a model
   symmetrically hedging both sides. Do NOT cite agent names, percentages, or signal counts.
   BAD: "Evidence is directionally constructive but headwinds remain."
   BAD: "Two forces affect the multiple in opposite directions, keeping conviction below high."
   GOOD: "The valuation case is clear at these earnings; what is harder to call is whether
   rate sensitivity matters enough at current multiples to compress the stock near-term."
   GOOD: "Services margin trajectory is well-evidenced; the China regulatory path and rate
   duration are harder to size — which is where the bear case lives, not in the core thesis."

10. what_changes_the_thesis: exactly 4 company-specific triggers (not generic macro events).
11. conclusion: 2 institutional sentences. MUST name specific {ticker} revenue drivers,
    risks, and valuation factors. Must NOT contain generic phrases like "the company faces
    headwinds" or "as a growth stock". Lead with the inflection condition or current
    positioning, not a summary of what was said above.

Agent reconciliation rules:
- If agents DISAGREE on direction, explicitly say WHY the stronger argument wins and \
what would flip you the other way.
- Rank key_drivers and key_risks by importance — put the most impactful first.
- Every claim must trace back to a specific agent output or evidence item number.

Company specificity rules (MANDATORY):
- You MUST mention {company.company_name}'s actual business segments/products.
- FORBIDDEN: Generic phrases like "tech companies face headwinds", "as a growth stock".
- REQUIRED: Specific {ticker} terms. {profile_keywords_hint}

{_THESIS_SCHEMA_DESCRIPTION}

Return ONLY valid JSON, no markdown fences or prose outside the JSON object.

JSON:"""


# ── Markdown stripping recovery ───────────────────────────────────────────────

def _strip_markdown_to_json(raw: str) -> Optional[str]:
    """Attempt to recover a JSON object from a markdown-prose response.

    When the LLM ignores the JSON-only instruction and returns markdown headings
    and paragraphs, this function:
      1. Detects markdown heading patterns.
      2. Strips all heading lines (##, ###, etc.) and code fences.
      3. Tries to find a JSON object in the cleaned text.
      4. Returns the JSON string if found, or None.

    This is a best-effort recovery — it does not reconstruct JSON from prose.
    """
    if not _MD_HEADING_RE.search(raw):
        return None  # Not a markdown response — caller handles normally

    print(f"[DIAG] THESIS SYNTHESIS MARKDOWN DETECTED — attempting markdown strip recovery")

    # Remove fenced code blocks
    cleaned = re.sub(r"```[a-zA-Z]*\n?", "", raw)
    cleaned = cleaned.replace("```", "")

    # Remove markdown heading lines
    cleaned = _MD_HEADING_RE.sub("", cleaned)

    # Try to extract a JSON object from the cleaned text
    candidate = extract_json_candidate(cleaned)
    if candidate and candidate.strip().startswith("{"):
        return candidate

    return None


# ── Deterministic governance checks (Phase 4) ────────────────────────────────

def _check_rate_cut_bank_contradiction(
    company: CompanyContext,
    macro: MacroSensitivity,
    thesis: InvestmentThesis,
) -> List[str]:
    """Flag if thesis/macro text says 'rate cuts benefit' for a bank.

    Banks earn net-interest-margin income that typically shrinks when rates
    fall.  Asserting rate cuts help a bank without nuance is a contradiction.
    """
    warnings: List[str] = []
    if company.sector not in _RATE_SENSITIVE_SECTORS:
        return warnings

    combined_text = (
        (macro.overall + " " + thesis.bull_thesis + " " + thesis.macro_sensitivity)
        .lower()
    )
    if any(phrase in combined_text for phrase in _RATE_CUT_BENEFIT_PHRASES):
        warnings.append(
            f"[GOVERNANCE] Rate-cut benefit claim for {company.sector} company "
            f"({company.ticker}): banks and financials typically earn less NIM when "
            f"rates fall — verify this claim is appropriately nuanced."
        )
    return warnings


def _check_valuation_risk_tension(
    valuation: ValuationView,
    risk: RiskProfile,
    thesis: InvestmentThesis,
) -> List[str]:
    """Flag if valuation says 'cheap/undervalued' but risk says 'high debt'."""
    warnings: List[str] = []
    val_low = (valuation.overall + " " + valuation.relative_value).lower()
    risk_low = (risk.debt_risk + " " + risk.overall).lower()

    cheap_signals = ("cheap", "undervalued", "discount to peers", "low multiple")
    debt_signals = ("high debt", "high leverage", "elevated leverage", "overleveraged",
                    "refinancing risk", "debt burden")

    val_cheap = any(s in val_low for s in cheap_signals)
    high_debt  = any(s in risk_low for s in debt_signals)

    if val_cheap and high_debt:
        warnings.append(
            f"[GOVERNANCE] Valuation-risk tension for {thesis.ticker}: valuation "
            f"signals 'cheap/undervalued' while risk profile flags high debt. "
            f"A 'value trap' scenario should be explicitly addressed in the thesis."
        )
    return warnings


def _check_evidence_sparse(
    evidence: List[RetrievedEvidence],
    thesis: InvestmentThesis,
) -> List[str]:
    """Flag if thesis confidence is high but evidence is sparse."""
    warnings: List[str] = []
    if len(evidence) < 3 and thesis.confidence_score > 0.70:
        warnings.append(
            f"[GOVERNANCE] High confidence ({thesis.confidence_score:.0%}) with "
            f"only {len(evidence)} evidence item(s). Confidence score may be "
            f"overstated — recommend gathering more data before acting."
        )
    return warnings


def _run_governance_checks(
    company: CompanyContext,
    valuation: ValuationView,
    macro: MacroSensitivity,
    risk: RiskProfile,
    thesis: InvestmentThesis,
    evidence: List[RetrievedEvidence],
) -> List[str]:
    """Run all Phase 4 deterministic consistency checks. Return warning strings."""
    warnings: List[str] = []
    warnings.extend(_check_rate_cut_bank_contradiction(company, macro, thesis))
    warnings.extend(_check_valuation_risk_tension(valuation, risk, thesis))
    warnings.extend(_check_evidence_sparse(evidence, thesis))
    return warnings


# ── Graceful empty thesis ─────────────────────────────────────────────────────

def _empty_thesis(
    company: CompanyContext,
    reason: str = "",
    original_user_question: Optional[str] = None,
) -> InvestmentThesis:
    return InvestmentThesis(
        ticker=company.ticker,
        company_name=company.company_name,
        direct_answer="",
        bull_thesis="Insufficient evidence to build a bull thesis.",
        bear_thesis="Insufficient evidence to build a bear thesis.",
        conclusion=f"Analysis incomplete. {reason}".strip(),
        confidence_score=0.0,
        confidence_reasoning="No sufficient evidence or agent outputs available.",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ── JSON-only LLM call with markdown recovery ─────────────────────────────────

def _call_with_json_enforcement(
    prompt: str,
    ticker: str,
    max_retries: int,
    backoff_factor: float,
    request_id: Optional[str] = None,
) -> Optional[InvestmentThesis]:
    """Call the model and enforce JSON-only output for InvestmentThesis.

    Wraps get_structured_response with thesis-specific diagnostics and a
    pre-validation markdown-stripping recovery path.  Returns a validated
    InvestmentThesis or None if all attempts fail.
    """
    import time

    for attempt in range(1, max_retries + 1):
        # ── Model call ────────────────────────────────────────────────────────
        try:
            call_kwargs: Dict[str, Any] = {}
            if request_id:
                call_kwargs["request_id"] = request_id
            raw = model_client.call(prompt, **call_kwargs)
        except Exception as exc:
            logger.warning("[thesis_synthesizer] model call failed attempt=%d: %r", attempt, exc)
            time.sleep(backoff_factor * (2 ** (attempt - 1)))
            continue

        raw_len = len(raw) if raw else 0
        print(
            f"[DIAG] THESIS SYNTHESIS RAW "
            f"ticker={ticker} attempt={attempt} len={raw_len}\n"
            f"[DIAG] THESIS SYNTHESIS RAW TEXT: {raw!r:.1000}"
        )

        # ── Markdown recovery (before JSON extraction) ────────────────────────
        if raw and _MD_HEADING_RE.search(raw):
            recovered = _strip_markdown_to_json(raw)
            if recovered:
                print(
                    f"[DIAG] THESIS SYNTHESIS PARSED "
                    f"ticker={ticker} attempt={attempt} source=markdown_recovery "
                    f"candidate={recovered!r:.400}"
                )
                try:
                    data = json.loads(recovered)
                except json.JSONDecodeError:
                    data = None
            else:
                print(
                    f"[DIAG] THESIS SYNTHESIS PARSED "
                    f"ticker={ticker} attempt={attempt} source=markdown_recovery_failed"
                )
                data = None
        else:
            # Normal JSON extraction path
            candidate = extract_json_candidate(raw) if raw else ""
            print(
                f"[DIAG] THESIS SYNTHESIS PARSED "
                f"ticker={ticker} attempt={attempt} source=json_extract "
                f"candidate={candidate!r:.400}"
            )
            try:
                data = json.loads(candidate)
            except (json.JSONDecodeError, TypeError):
                data = None

        if data is None:
            logger.warning(
                "[thesis_synthesizer] JSON parse failed attempt=%d ticker=%s",
                attempt, ticker,
            )
            time.sleep(backoff_factor * (2 ** (attempt - 1)))
            continue

        # ── Schema validation ─────────────────────────────────────────────────
        from pydantic import ValidationError
        try:
            if hasattr(InvestmentThesis, "model_validate"):
                result = InvestmentThesis.model_validate(data)
            else:
                result = InvestmentThesis.parse_obj(data)
            print(
                f"[DIAG] THESIS SYNTHESIS VALIDATED "
                f"ticker={ticker} attempt={attempt} "
                f"confidence={result.confidence_score} "
                f"bull_len={len(result.bull_thesis)} "
                f"bear_len={len(result.bear_thesis)}"
            )
            return result
        except ValidationError as ve:
            logger.warning(
                "[thesis_synthesizer] validation failed attempt=%d: %s", attempt, ve
            )
            # Attempt repair
            repaired = repair_data(data, InvestmentThesis)
            try:
                if hasattr(InvestmentThesis, "model_validate"):
                    result = InvestmentThesis.model_validate(repaired)
                else:
                    result = InvestmentThesis.parse_obj(repaired)
                print(
                    f"[DIAG] THESIS SYNTHESIS VALIDATED "
                    f"ticker={ticker} attempt={attempt} source=repaired "
                    f"confidence={result.confidence_score}"
                )
                return result
            except ValidationError:
                time.sleep(backoff_factor * (2 ** (attempt - 1)))
                continue

    logger.error(
        "[thesis_synthesizer] all %d attempts failed for %s", max_retries, ticker
    )
    return None


# ── Public entry point ────────────────────────────────────────────────────────

def synthesize_thesis(
    company: CompanyContext,
    valuation: ValuationView,
    macro: MacroSensitivity,
    risk: RiskProfile,
    market: MarketContext,
    quality: QualityAssessment,
    evidence: List[RetrievedEvidence],
    request_id: Optional[str] = None,
    profile: Optional[CompanyKnowledgeProfile] = None,
    original_user_question: Optional[str] = None,
    prior_snapshot=None,  # Optional[ThesisSnapshot] — avoids circular import at module level
) -> InvestmentThesis:
    """Synthesise agent outputs into an InvestmentThesis.

    Runs the LLM synthesis with strict JSON-only enforcement, then applies
    deterministic Phase 4 governance checks and Phase 5 depth enforcement.
    Degrades gracefully if the LLM call fails.

    Parameters
    ----------
    company               : Normalised company identity.
    valuation             : Output from run_valuation_agent().
    macro                 : Output from run_macro_agent().
    risk                  : Output from run_risk_agent().
    market                : Output from run_market_agent().
    quality               : Output from run_quality_agent().
    evidence              : Full evidence list (all agents' inputs combined).
    request_id            : Optional trace ID forwarded to model client.
    profile               : Optional CompanyKnowledgeProfile; enables richer prompting
                            and depth-guard checks when supplied.
    original_user_question: The user's verbatim question. When supplied the synthesiser
                            produces a ``direct_answer`` field that specifically addresses
                            the question before the broader thesis.

    Returns
    -------
    InvestmentThesis with consistency_warnings populated by governance and
    depth-guard layers.
    """
    print(
        f"[thesis_synthesizer] synthesising for {company.ticker} "
        f"({len(evidence)} evidence items, "
        f"val_conf={valuation.confidence:.2f} "
        f"macro_conf={macro.confidence:.2f} "
        f"risk_conf={risk.confidence:.2f} "
        f"market_conf={market.confidence:.2f} "
        f"quality_conf={quality.confidence:.2f})"
    )

    # Check if all agents returned empty outputs (all-zero confidence)
    agent_confidences = [
        valuation.confidence, macro.confidence,
        risk.confidence, market.confidence, quality.confidence,
    ]
    if all(c == 0.0 for c in agent_confidences) and not evidence:
        print(f"[thesis_synthesizer] all agents empty + no evidence — skipping LLM call")
        return _empty_thesis(company, "No agent outputs or evidence available.")

    # ── Phase 3: Signal ranking (pre-synthesis) ───────────────────────────────
    # Run before the LLM call so ranked signals can be injected into the prompt.
    try:
        ranked = rank_signals(
            valuation, macro, risk, market, quality,
            company=company, profile=profile,
        )
    except Exception as exc:
        logger.warning("[thesis_synthesizer] signal_ranker failed: %r — continuing", exc)
        ranked = None

    dominant_dim_for_thesis = _detect_dominant_dimension(macro, risk, valuation, ranked)
    prompt = _build_synthesis_prompt(
        company, valuation, macro, risk, market, quality, evidence, profile,
        original_user_question=original_user_question,
        ranked=ranked,
        prior_snapshot=prior_snapshot,
    )

    # ── JSON-enforced LLM call with markdown recovery ─────────────────────────
    thesis = _call_with_json_enforcement(
        prompt=prompt,
        ticker=company.ticker,
        max_retries=settings.model_max_retries,
        backoff_factor=settings.model_backoff_factor,
        request_id=request_id,
    )

    if thesis is None:
        logger.warning("[thesis_synthesizer] synthesis failed for %s", company.ticker)
        return _empty_thesis(company, "LLM synthesis error: retries exhausted.")

    # Stamp metadata
    thesis.ticker = company.ticker
    thesis.company_name = company.company_name
    thesis.evidence_count = len(evidence)
    thesis.generated_at = datetime.now(timezone.utc).isoformat()

    # Guard: core_market_debate must be non-empty; fall back to core_debate if LLM omitted it
    if not getattr(thesis, "core_market_debate", ""):
        thesis.core_market_debate = getattr(thesis, "core_debate", "")

    # Stamp dominant analytical dimension (deterministic, pre-LLM)
    thesis.dominant_dimension = dominant_dim_for_thesis

    # ── R1: Deterministic confidence realism cap ──────────────────────────────
    # Applied immediately after LLM output so the post-synthesis chain sees
    # a properly conservative confidence score throughout.
    try:
        adjusted_conf, cap_triggers = compute_confidence_realism_cap(
            raw_score=thesis.confidence_score,
            macro_conf=macro.confidence,
            risk_conf=risk.confidence,
            quality_conf=quality.confidence,
            evidence_count=len(evidence),
            ranked=ranked,
        )
        if adjusted_conf < thesis.confidence_score:
            print(
                f"[thesis_synthesizer] confidence capped: "
                f"{thesis.confidence_score:.2f} → {adjusted_conf:.2f} "
                f"triggers={cap_triggers}"
            )
            thesis.confidence_score = adjusted_conf
    except Exception as exc:
        logger.warning("[thesis_synthesizer] confidence realism cap failed: %r", exc)

    # ── Attach ranked signals to thesis ──────────────────────────────────────
    if ranked is not None:
        thesis.top_signals = ranked.top_signals
        thesis.top_risks = ranked.top_risks
        thesis.secondary_signals = ranked.secondary_signals

    # ── Refinement 2: causal confidence reasoning ─────────────────────────────
    # Replace LLM-generated generic confidence text with specific causal
    # reasoning that cites agent agreement/disagreement, evidence coverage,
    # and signal direction consensus.
    try:
        agent_confidences = {
            "valuation": valuation.confidence,
            "macro":     macro.confidence,
            "risk":      risk.confidence,
            "market":    market.confidence,
            "quality":   quality.confidence,
        }
        causal_reasoning = build_confidence_reasoning(
            agent_confidences=agent_confidences,
            ranked=ranked,
            evidence_count=len(evidence),
            original_reasoning=thesis.confidence_reasoning or "",
        )
        if causal_reasoning:
            thesis.confidence_reasoning = causal_reasoning
    except Exception as exc:
        logger.warning("[thesis_synthesizer] confidence_reasoning build failed: %r", exc)

    # ── Refinement 3: Evidence reference propagation ──────────────────────────
    # Infer evidence_refs on signals that the LLM did not explicitly annotate,
    # using keyword overlap against the full evidence pool.
    try:
        thesis.top_signals = propagate_evidence_refs(thesis.top_signals, evidence)
        thesis.top_risks   = propagate_evidence_refs(thesis.top_risks,   evidence)
    except Exception as exc:
        logger.warning("[thesis_synthesizer] evidence propagation failed: %r", exc)

    # ── Phase 4: governance / consistency checks ──────────────────────────────
    warnings = _run_governance_checks(company, valuation, macro, risk, thesis, evidence)

    # ── Refinement 5: signal overlap detection ────────────────────────────────
    if ranked is not None:
        try:
            overlap_warnings = detect_signal_overlap(ranked)
            if overlap_warnings:
                print(f"[DIAG] SIGNAL OVERLAP: {len(overlap_warnings)} overlap(s) detected")
                for w in overlap_warnings:
                    print(w)
            warnings = warnings + overlap_warnings
        except Exception as exc:
            logger.warning("[thesis_synthesizer] overlap detection failed: %r", exc)

    # ── Phase 5: depth enforcement ────────────────────────────────────────────
    depth_warnings = check_synthesis_depth(thesis, company, profile)
    warnings = warnings + depth_warnings

    # ── Phase 5+: forbidden phrase quality check ──────────────────────────────
    quality_warnings = check_forbidden_phrases(thesis)
    warnings = warnings + quality_warnings

    thesis.consistency_warnings = warnings

    if warnings:
        for w in warnings:
            print(w)

    # ── Phase 4: thesis compression ───────────────────────────────────────────
    if ranked is not None:
        try:
            thesis.compressed_thesis = _compress_thesis(thesis, ranked)
            thesis.one_sentence_thesis = thesis.compressed_thesis.one_sentence_thesis
        except Exception as exc:
            logger.warning("[thesis_synthesizer] compression failed: %r", exc)

    # ── Refinement 1+2+4: Concision, redundancy suppression, temporal defaults ─
    try:
        thesis = polish_thesis(thesis)
    except Exception as exc:
        logger.warning("[thesis_synthesizer] thesis_polisher failed: %r — skipping", exc)

    overlap_count = sum(1 for w in warnings if w.startswith("[OVERLAP]"))
    gov_count = len(warnings) - len(depth_warnings) - len(quality_warnings) - overlap_count
    print(
        f"[thesis_synthesizer] done for {company.ticker}: "
        f"confidence={thesis.confidence_score:.2f} "
        f"warnings={len(warnings)} "
        f"(governance={gov_count}, depth={len(depth_warnings)}, "
        f"quality={len(quality_warnings)}, overlap={overlap_count}) "
        f"top_signals={len(thesis.top_signals)} "
        f"top_risks={len(thesis.top_risks)}"
    )
    return thesis
