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

import datetime as _dt
import json
import logging
import re
import traceback as _traceback
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
    check_cross_section_duplication,
    # build_confidence_reasoning is intentionally NOT imported here.
    # Phase 5c+: production pipeline never calls it — the conviction modeler
    # (conviction_modeler.py) owns confidence_reasoning.  Calling this function
    # would inject generic boilerplate phrases that the governance check flags
    # as hard-fail violations.
    compute_confidence_realism_cap,
    _get_signal_dimension,
    RankedSignalSet,
)
from .thesis_polisher import polish_thesis
from .confidence_calibrator import compute_evidence_coverage_gaps
from .conviction_modeler import compute_conviction
from .freshness_analyzer import analyze_evidence_freshness

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
    "what_increases_conviction",
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


def _classify_debate_type(
    dominant_dim: str,
    original_user_question: Optional[str] = None,
) -> str:
    """Classify the debate into a PM-facing category for hierarchy injection.

    Returns one of: valuation | product_competition | regulatory | margin | macro
    Used to drive section depth allocation and conclusion framing.
    """
    q = (original_user_question or "").lower()
    dim = dominant_dim.lower()

    # Question-level overrides (strongest signal)
    _QUESTION_PATTERNS: List[tuple] = [
        (["margin", "profitab", "cost", "operating leverage", "fcf"], "margin"),
        (["multiple", "p/e", "valuation", "cheap", "expensive", "priced", "pe "], "valuation"),
        (["compet", "market share", "moat", "product", "demand", "adoption", "launch"], "product_competition"),
        (["regulat", "antitrust", "doj", "ftc", "government", "policy", "legal"], "regulatory"),
        (["rate", "inflation", "macro", "yield", "fed", "cycle", "recession"], "macro"),
    ]
    for keywords, category in _QUESTION_PATTERNS:
        if any(kw in q for kw in keywords):
            return category

    # Dimension-level mapping (secondary signal)
    _DIM_MAP: Dict[str, str] = {
        "valuation":          "valuation",
        "macro":              "macro",
        "regulatory":         "regulatory",
        "capital_allocation": "valuation",
        "operational":        "margin",
    }
    return _DIM_MAP.get(dim, "product_competition")


def _build_core_debate_mandate_block(
    company_name: str,
    ticker: str,
    dominant_dim: str,
    debate_type: str,
    original_user_question: Optional[str] = None,
    prior_snapshot=None,
) -> str:
    """Build the mandatory CORE MARKET DEBATE block for the synthesis prompt.

    This block:
    1. Forces isolation of the single fulcrum variable
    2. Maps debate type to section depth hierarchy
    3. Enforces conclusion to restate the fulcrum
    4. Adds historical debate-shift comparison when prior snapshot exists
    """
    # Debate-type specific examples and depth instruction
    _DEBATE_EXAMPLES: Dict[str, Dict[str, str]] = {
        "valuation": {
            "examples": (
                '"Can the current multiple hold if rates stay restrictive longer than consensus expects?"\n'
                '"Is the re-rating already complete, or does earnings execution still support expansion?"\n'
                '"At current levels, is the market paying for growth or paying for quality?"'
            ),
            "depth_directive": (
                "Since this is a VALUATION debate, valuation_view is your anchor section — "
                "it must be 3 sentences: current multiple, what it implies, and what moves it. "
                "Macro is a one-liner. Bull thesis names the re-rating catalyst."
            ),
        },
        "product_competition": {
            "examples": (
                '"Can the platform moat hold as competition accelerates, or is market share already at risk?"\n'
                '"Is the new product cycle durable, or is this a one-period pull-forward?"\n'
                '"Does the competitive advantage justify the current multiple?"'
            ),
            "depth_directive": (
                "Since this is a PRODUCT/COMPETITION debate, bull_thesis and bear_thesis are your "
                "anchor sections — both need competitive durability mechanics. "
                "Name specific products, market share data, and switching cost estimates. "
                "Valuation view anchors on the multiple justified if the moat holds vs breaks."
            ),
        },
        "regulatory": {
            "examples": (
                '"Does the regulatory overhang now outweigh the earnings trajectory?"\n'
                '"Is the enforcement risk already priced, or does the market still underestimate the timeline?"\n'
                '"Can the business model survive structural regulatory change?"'
            ),
            "depth_directive": (
                "Since this is a REGULATORY debate, bear_thesis is your most specific section — "
                "name the regulatory body, action type, realistic timeline, and revenue impact. "
                "what_changes_the_thesis must prioritize regulatory events."
            ),
        },
        "margin": {
            "examples": (
                '"Is margin expansion sustainable, or is it a one-period cost discipline story?"\n'
                '"Can operating leverage absorb investment spending without compressing the multiple?"\n'
                '"Is incremental margin improvement already in the price?"'
            ),
            "depth_directive": (
                "Since this is a MARGIN debate, both bull_thesis and bear_thesis anchor on "
                "specific margin lines, operating leverage, and EPS sensitivity. "
                "valuation_view must connect the margin trajectory to the specific multiple it supports."
            ),
        },
        "macro": {
            "examples": (
                '"Can earnings durability offset duration-driven multiple compression?"\n'
                '"Is the macro headwind already priced, or does the market still underestimate sensitivity?"\n'
                '"Does the business model have enough cyclical insulation to hold the multiple?"'
            ),
            "depth_directive": (
                "Since this is a MACRO debate, macro_sensitivity is your anchor section — "
                "name the exact transmission channel, magnitude, and second-order effect. "
                "valuation_view is a one-liner anchoring the multiple to the macro scenario."
            ),
        },
    }

    ex = _DEBATE_EXAMPLES.get(debate_type, _DEBATE_EXAMPLES["product_competition"])
    examples_txt = ex["examples"]
    depth_directive = ex["depth_directive"]

    # Historical debate comparison (only when prior snapshot available)
    if prior_snapshot is not None:
        prev_debate = (getattr(prior_snapshot, "core_debate", "") or "").strip()
        prev_mkt_debate = (getattr(prior_snapshot, "core_market_debate", "") or "").strip()
        prior_debate_line = prev_debate or prev_mkt_debate
        if prior_debate_line:
            historical_debate_block = (
                f"\nPRIOR CORE DEBATE (from previous analysis): '{prior_debate_line[:100]}'\n"
                f"MANDATORY — compare the prior and current debate in confidence_reasoning or conclusion:\n"
                f"  - 'Core debate unchanged — only risk weighting changed.' OR\n"
                f"  - 'Core debate shifted from [X] toward [Y] — the fulcrum variable rotated.' OR\n"
                f"  - 'Market debate narrowed from [broad X] to [specific Y] — prior ambiguity resolved.'\n"
            )
        else:
            historical_debate_block = ""
    else:
        historical_debate_block = ""

    return f"""
CORE MARKET DEBATE — MANDATORY (the highest-priority analytical task):
Identify the SINGLE live question investors are actually debating for {company_name} ({ticker}) today.
This is the fulcrum variable: the one thing that, if resolved differently, would flip the investment decision.

REQUIREMENTS for core_debate and core_market_debate:
- ONE sentence, phrased as an open question — NOT a statement, NOT a summary
- Must ISOLATE the fulcrum variable — not enumerate all pros and cons
- Must be specific to {ticker}'s actual situation — not a generic sector question
- Must name the mechanism that makes this THE debate (not just a factor to watch)
{historical_debate_block}
GOOD examples (study the isolation technique):
{examples_txt}

BAD examples (rejected):
  "{ticker} has strong growth but faces valuation risks." — statement, not debate
  "There are several factors affecting {ticker}." — not isolated
  "The market is debating whether {ticker} is well-positioned." — generic, no mechanism
  Anything starting with "The market is debating whether..." — BANNED

SECTION DEPTH HIERARCHY — driven by the debate type:
{depth_directive}

CONCLUSION REQUIREMENT — positioning-first, not mechanism-first:
The conclusion MUST open with the bottom-line positioning view or expectation structure.
NOT with the mechanism. NOT with "The thesis requires..." or "The business needs...".
REQUIRED:
  Sentence 1 → Positioning or expectation structure: what the market is pricing vs. what is defensible.
  Sentence 2 → The fulcrum or exit risk: the specific thing that would change the view.
PATTERNS:
  "[Business] remains [quality], but the market already prices in [expectation] — setup works only if [condition]."
  "At ~[X]x, the market is paying for [assumption] — the risk is whether [Y] holds."
  "Current pricing already assumes [X]; the question is whether [Y] delivers on schedule."
FORBIDDEN: "The thesis requires...", "The company remains...", "The business has...", generic headwind/tailwind summaries.

"""


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

# Evidence type labels mapped from title/source keywords
_EVIDENCE_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "earnings":    ["earnings", "eps", "quarterly", "fiscal", "q1", "q2", "q3", "q4", "beat", "miss", "results"],
    "guidance":    ["guidance", "outlook", "forecast", "raised", "lowered", "revised", "estimates"],
    "macro":       ["fed", "rate", "inflation", "gdp", "unemployment", "fomc", "yield", "monetary"],
    "regulatory":  ["regulatory", "antitrust", "doj", "ftc", "sec", "probe", "investigation", "ruling"],
    "product":     ["launch", "product", "announced", "unveil", "release", "ai", "model"],
    "analyst":     ["upgrade", "downgrade", "target", "price target", "rating", "analyst"],
    "market":      ["stock", "share", "rally", "decline", "trading", "volume", "short"],
}


def _classify_evidence_type(ev: RetrievedEvidence) -> str:
    """Classify evidence into a category label for display."""
    text = (ev.title + " " + ev.source).lower()
    for ev_type, keywords in _EVIDENCE_TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return ev_type
    return "research"


def _evidence_recency_weight(ev: RetrievedEvidence, reference_ts: str) -> float:
    """Compute a recency multiplier relative to the most recent evidence date.

    Recent items (≤30 days from reference) get 1.5x boost.
    Items 30-60 days get 1.2x.
    Items 60-90 days get 1.0x (no change).
    Items >90 days get 0.80x decay.
    Returns 1.0 on any parse failure (safe default).
    """
    try:
        ref = _dt.date.fromisoformat(reference_ts[:10])
        ev_date = _dt.date.fromisoformat(ev.timestamp[:10])
        days_old = (ref - ev_date).days
        if days_old <= 0:
            return 1.5
        if days_old <= 30:
            return 1.5
        if days_old <= 60:
            return 1.2
        if days_old <= 90:
            return 1.0
        return 0.80
    except Exception:
        return 1.0


def _composite_evidence_score(ev: RetrievedEvidence, reference_ts: str) -> float:
    """Composite score = relevance × recency_weight, with type-based bonus."""
    recency = _evidence_recency_weight(ev, reference_ts)
    base = float(ev.relevance_score) * recency
    # Earnings and guidance get +0.1 bonus (highest signal value)
    ev_type = _classify_evidence_type(ev)
    if ev_type in ("earnings", "guidance"):
        base += 0.1
    return base


def _build_live_data_provenance_block(evidence: List[RetrievedEvidence]) -> str:
    """Build a prompt block that enforces live-data citation and provenance.

    When FMP valuation ratios or analyst estimate evidence is present, the
    synthesiser is required to cite the live metric directly rather than
    using generic valuation language.  When the evidence is thin or stale,
    the block instructs the model to qualify claims accordingly.
    """
    from .confidence_calibrator import (
        _has_live_valuation,
        _has_analyst_estimates,
        _has_recent_earnings,
        _oldest_evidence_age_days,
        _STALE_THRESHOLD_DAYS,
        _RECENT_EARNINGS_THRESHOLD_DAYS,
    )

    has_val = _has_live_valuation(evidence)
    has_est = _has_analyst_estimates(evidence)
    has_earn = _has_recent_earnings(evidence)
    oldest = _oldest_evidence_age_days(evidence)

    lines: List[str] = ["EVIDENCE PROVENANCE — MANDATORY:"]

    if has_val:
        lines.append(
            "- Live valuation ratios (FMP) are present in the evidence. "
            "You MUST cite the specific ratio (P/E, EV/EBITDA, FCF yield, or Price/Sales) "
            "from these items in valuation_view. "
            'Do NOT write "the stock trades at a premium" without naming the actual multiple.'
        )
    else:
        lines.append(
            "- No live valuation ratios available. "
            "You MUST qualify valuation claims with 'estimated' or 'based on available data' "
            "and note the absence of current ratio data in confidence_reasoning."
        )

    if has_est:
        lines.append(
            "- Analyst estimates / price-target consensus data is present. "
            "You MUST reference the consensus target vs current price or forward EPS estimate "
            "when discussing the valuation outlook."
        )
    else:
        lines.append(
            "- No analyst estimate or price-target data available. "
            "Do NOT assert a 'consensus view' or 'analyst expectations' without explicit evidence."
        )

    if has_earn:
        lines.append(
            "- Recent earnings evidence is present. "
            "You MUST incorporate the actual vs estimated result or guidance language "
            "when assessing near-term trajectory."
        )
    else:
        lines.append(
            "- No recent earnings evidence (< 90d). "
            "Flag this gap when discussing near-term earnings visibility."
        )

    if oldest is not None and oldest > _STALE_THRESHOLD_DAYS:
        lines.append(
            f"- WARNING: Oldest evidence is {oldest}d old — some data pre-dates current "
            "market conditions. Use temporal qualifiers ('as of [date]') for any claims "
            "that could have changed materially."
        )
    elif oldest is not None and oldest > _RECENT_EARNINGS_THRESHOLD_DAYS:
        lines.append(
            f"- Evidence is moderately stale (oldest: {oldest}d). "
            "Prefer the most recent items when claims conflict across time periods."
        )

    lines.append(
        "- CITATION REQUIREMENT: Every quantitative claim (multiples, margins, growth rates, "
        "price targets) MUST be traceable to an evidence item number [N]. "
        'Do NOT invent numbers. If no number is available, write "no current data" rather '
        "than fabricating a figure."
    )

    return "\n".join(lines) + "\n\n"


def _evidence_block(evidence: List[RetrievedEvidence], max_items: int = 10) -> str:
    """Format top-N evidence items with composite recency+relevance scoring.

    Evidence is ranked by: relevance_score × recency_weight + type_bonus.
    Most recent earnings/guidance items surface to the top even if raw
    relevance score is slightly lower.
    """
    if not evidence:
        return "No evidence available."

    # Reference date = most recent timestamp in the set
    try:
        reference_ts = max(
            (ev.timestamp for ev in evidence if ev.timestamp),
            key=lambda ts: ts[:10],
            default="2025-01-01",
        )
    except Exception:
        reference_ts = "2025-01-01"

    scored = sorted(
        evidence,
        key=lambda e: _composite_evidence_score(e, reference_ts),
        reverse=True,
    )[:max_items]

    lines = []
    for i, ev in enumerate(scored):
        ev_type = _classify_evidence_type(ev)
        lines.append(
            f"[{i + 1}] [{ev_type.upper()}] {ev.title}\n"
            f"    Source: {ev.source} ({ev.timestamp[:7] if ev.timestamp else 'n/a'})\n"
            f"    {ev.summary}"
        )
    return "\n".join(lines)


def _build_market_regime_block(evidence: List[RetrievedEvidence]) -> str:
    """Extract current market regime context from evidence for synthesis prompt injection.

    Scans the top evidence items for rate/valuation/macro signals and returns
    a compact block that anchors temporal language in the synthesis output.
    Returns an empty string when no regime signals are detectable.
    """
    _RATE_TERMS = {
        "rate", "rates", "fed", "federal reserve", "yield", "yields",
        "inflation", "tightening", "easing", "hike", "cut", "bps",
        "basis points", "fomc", "monetary policy", "rate path",
    }
    _VAL_TERMS = {
        "multiple", "p/e", "pe ratio", "forward pe", "ev/ebitda", "valuation",
        "premium", "discount", "expensive", "cheap", "overvalued", "undervalued",
        "trading at", "priced at", "multiple compression", "re-rating",
    }
    _MACRO_TERMS = {
        "gdp", "recession", "economic growth", "unemployment", "jobs report",
        "consumer spending", "credit", "slowdown", "expansion", "soft landing",
        "hard landing", "macro", "economy", "cyclical",
    }

    rate_signal: str = ""
    val_signal: str = ""
    macro_signal: str = ""

    top_ev = sorted(evidence, key=lambda e: e.relevance_score, reverse=True)[:10]
    for ev in top_ev:
        text = (ev.title + " " + ev.summary).lower()
        if not rate_signal and any(t in text for t in _RATE_TERMS):
            rate_signal = ev.summary[:110].strip()
        elif not val_signal and any(t in text for t in _VAL_TERMS):
            val_signal = ev.summary[:110].strip()
        elif not macro_signal and any(t in text for t in _MACRO_TERMS):
            macro_signal = ev.summary[:110].strip()
        if rate_signal and val_signal and macro_signal:
            break

    if not any([rate_signal, val_signal, macro_signal]):
        return ""

    lines = [
        "CURRENT MARKET REGIME — anchor all temporal claims to these conditions:"
    ]
    if rate_signal:
        lines.append(f"  Rate environment: {rate_signal}")
    if val_signal:
        lines.append(f"  Valuation context: {val_signal}")
    if macro_signal:
        lines.append(f"  Macro backdrop: {macro_signal}")
    lines.append(
        "Use these to drive language like: 'this cycle', 'since rates repriced', "
        "'at current multiples', 'over the last quarter', 'right now'."
    )
    return "\n".join(lines) + "\n\n"


def _extract_recent_events(evidence: List[RetrievedEvidence]) -> str:
    """Extract 3-4 most significant recent events from evidence for synthesis injection.

    Prioritizes: earnings beats/misses, guidance changes, macro shifts, regulatory events.
    Returns a RECENT MARKET EVENTS block or '' if nothing significant found.
    """
    _HIGH_SIGNAL_TERMS = {
        "beat", "miss", "exceeded", "fell short", "raised guidance", "lowered guidance",
        "revised", "cut guidance", "raised outlook", "earnings", "revenue beat",
        "guidance", "rate hike", "rate cut", "fomc", "tariff", "antitrust",
        "launched", "unveiled", "announced", "partnership", "acquisition",
        "margin expansion", "margin compression", "layoffs", "restructuring",
        "upgrade", "downgrade", "price target",
    }

    if not evidence:
        return ""

    try:
        reference_ts = max(
            (ev.timestamp for ev in evidence if ev.timestamp),
            key=lambda ts: ts[:10],
            default="2025-01-01",
        )
    except Exception:
        reference_ts = "2025-01-01"

    # Score: recency weight × relevance × high-signal keyword presence
    def _signal_score(ev: RetrievedEvidence) -> float:
        recency = _evidence_recency_weight(ev, reference_ts)
        text = (ev.title + " " + ev.summary).lower()
        keyword_bonus = 0.3 if any(kw in text for kw in _HIGH_SIGNAL_TERMS) else 0.0
        return float(ev.relevance_score) * recency + keyword_bonus

    top_events = sorted(evidence, key=_signal_score, reverse=True)[:4]

    # Only include items that actually have high-signal keywords
    significant = [
        ev for ev in top_events
        if any(kw in (ev.title + " " + ev.summary).lower() for kw in _HIGH_SIGNAL_TERMS)
    ]

    if not significant:
        return ""

    lines = ["RECENT MARKET EVENTS — anchor your temporal analysis to these:"]
    for ev in significant[:3]:
        ts_short = ev.timestamp[:7] if ev.timestamp else ""
        ev_type = _classify_evidence_type(ev)
        lines.append(f"  [{ev_type.upper()}{' ' + ts_short if ts_short else ''}] {ev.title}: {ev.summary[:90].rstrip('.')}.")
    lines.append(
        "Reference these events using language like: 'following the recent earnings', "
        "'after the guidance revision', 'since the macro shift', 'post-announcement'."
    )
    return "\n".join(lines) + "\n\n"


def _build_expectation_delta_block(
    company_name: str,
    ticker: str,
    debate_type: str,
) -> str:
    """Build the EXPECTATION_DELTA mandatory block for synthesis prompt injection.

    Forces the LLM to explicitly reason about what's priced in vs what would
    surprise. Complementary to (but distinct from) PRICED_IN_REASONING which
    addresses valuation; this block addresses market psychology more broadly.
    """
    # Debate-type specific expectation framing
    _EXPECTATION_FRAMING: Dict[str, str] = {
        "valuation": (
            "Current consensus is most likely anchored on the existing multiple — "
            "the differentiated call is whether the multiple can hold, expand, or must compress. "
            "Name what growth rate / margin assumption the multiple ALREADY EMBEDS."
        ),
        "product_competition": (
            "Current consensus is likely tracking market share and product cycle. "
            "The differentiated call is durability — whether competitive advantage persists "
            "beyond the current product cycle. Name the specific moat that consensus may be underweighting."
        ),
        "regulatory": (
            "Current consensus likely underestimates regulatory timeline risk. "
            "The differentiated call is probability-weighted revenue impact and resolution timeline. "
            "Name what a base-case regulatory outcome looks like vs what the market prices."
        ),
        "margin": (
            "Current consensus is likely tracking the most recent margin print. "
            "The differentiated call is sustainability — whether the current margin rate "
            "reflects structural improvement or one-period cost discipline. Name the specific driver."
        ),
        "macro": (
            "Current consensus is anchored on the prevailing rate/macro path. "
            "The differentiated call is duration sensitivity — whether the company's earnings "
            "durability outweighs multiple pressure. Name what rate scenario the stock currently prices."
        ),
    }

    framing = _EXPECTATION_FRAMING.get(debate_type, _EXPECTATION_FRAMING["valuation"])

    return f"""
EXPECTATION DELTA — MANDATORY:
Every significant thesis claim must answer: "Is this already consensus, or would this move the stock?"
{framing}

REQUIRED — address ALL THREE of these in your thesis sections:
1. CONSENSUS ASSUMPTION: What does the market currently expect from {company_name} ({ticker})?
   (e.g. "Consensus assumes sustained Services growth — the bar is already high.")
2. POTENTIAL SURPRISE: What would most surprise investors — on the upside OR the downside?
   (e.g. "A margin miss on the next print would be unpriced at ~28x.")
3. REPRICING CHECK: Has recent price action already baked in the current narrative?
   (e.g. "Post-earnings rerating already captured the beat — incremental upside requires guidance raise.")

REQUIRED LANGUAGE PATTERNS (use 2-3 across valuation_view, bull_thesis, conclusion):
- "Consensus already expects X — the differentiated call is Y"
- "The stock already prices in X — incremental upside requires Z"
- "A X would be unpriced at current multiples"
- "The debate is no longer X — it is now Y"
- "The burden shifts to [execution / margin expansion / monetization / guidance delivery]"
- "The setup is [less one-sided / becoming a harder timing call / cleaner than it looks]"

BANNED TIMELESS ASSERTIONS (replace with expectation framing):
- "Revenue growth is strong" → "Consensus already prices double-digit growth — the question is durability"
- "The company has good fundamentals" → "At ~[X]x, fundamentals are in the price; execution is the open variable"
- "The stock could perform well" → "The stock works if X holds — the market has not yet tested that assumption"

"""


def _build_narrative_state_block(
    prior_snapshot,  # Optional[ThesisSnapshot]
    dominant_dim: str,
    debate_type: str,
) -> str:
    """Build a NARRATIVE STATE block tracking regime and narrative transitions.

    Only injected when a prior snapshot exists — captures whether the investment
    narrative is stable, transitioning, or repricing.
    """
    if prior_snapshot is None:
        return ""

    prev_dim = (getattr(prior_snapshot, "dominant_dimension", "") or "").lower()
    curr_dim = dominant_dim.lower()

    _NARRATIVE_TRANSITIONS: Dict[str, Dict[str, str]] = {
        "valuation": {
            "macro":              "The market focus is transitioning from valuation support toward macro sensitivity.",
            "regulatory":         "The narrative is rotating from valuation to regulatory risk.",
            "operational":        "The debate moved from valuation toward margin execution.",
            "capital_allocation": "Market attention shifted from valuation to capital return mechanics.",
        },
        "macro": {
            "valuation":          "The narrative rotated from macro sensitivity toward valuation support — rate path expectations may have shifted.",
            "operational":        "Focus is transitioning from macro conditions toward operating execution.",
            "regulatory":         "Macro concern is giving way to regulatory risk as the primary investment question.",
        },
        "operational": {
            "valuation":          "The narrative transitioned from margin/growth execution toward valuation sustainability.",
            "macro":              "Operating story is being overshadowed by macro regime conditions.",
            "regulatory":         "Business execution concerns are giving way to regulatory risk as the dominant lens.",
        },
        "regulatory": {
            "valuation":          "Regulatory overhang is easing — the debate is rotating back toward valuation.",
            "operational":        "Regulatory focus is rotating toward operating execution as the primary variable.",
            "macro":              "Regulatory risk is becoming secondary to macro sensitivity.",
        },
    }

    transition_line = ""
    if prev_dim and curr_dim and prev_dim != curr_dim:
        transition_line = (
            _NARRATIVE_TRANSITIONS.get(prev_dim, {}).get(curr_dim, "")
            or f"The dominant investment lens shifted from {prev_dim.replace('_', ' ')} toward {curr_dim.replace('_', ' ')}."
        )

    if not transition_line and prev_dim == curr_dim:
        transition_line = f"The {curr_dim.replace('_', ' ')} narrative is stable — the market debate is unchanged in its framing."

    if not transition_line:
        return ""

    return (
        f"NARRATIVE STATE — use this to frame repricing vs thesis language:\n"
        f"  {transition_line}\n"
        f"  Reference this in confidence_reasoning or conclusion where analytically relevant.\n\n"
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
Sentence 1: state the SPECIFIC current multiple (e.g. "~28x forward earnings"), what growth rate \
or margin trajectory the market is ALREADY PRICING IN at that level, and whether that assumption \
is achievable, generous, or stretched relative to current evidence. \
MANDATORY: use "the stock already prices in" / "at ~[X]x, the market is paying for" language. \
Sentence 2: what would cause the multiple to expand or compress — name the specific trigger and \
which scenario is more likely given current rate/macro conditions. \
EXAMPLE GOOD: "At ~28x forward earnings, the stock already prices sustained double-digit Services \
growth — incremental upside requires margin acceleration beyond what consensus assumes, not just \
stability." \
EXAMPLE BAD: "Apple trades at a premium multiple due to its strong brand and ecosystem."
  "macro_sensitivity"       : string — 2 sentences on macro transmission. \
Sentence 1: primary transmission pathway with direction and channel \
(e.g. rates → discount rate → DCF impact on long-duration cash flows; \
FX → international revenue mix → reported EPS). \
Sentence 2: magnitude and directional bias — quantify the sensitivity where possible \
(100bps rate move ≈ X% P/E compression; 10% USD appreciation ≈ Y% revenue headwind \
on international segment).
  "confidence_score"        : number between 0.0 and 1.0. Provide your honest analytical read. \
score 0.80+ ONLY when macro, risk, AND evidence all clearly agree. If macro or regulatory \
uncertainty is real and unresolved, lean toward 0.55–0.72 range. \
IMPORTANT: The conviction modeler will override this score after you respond — your job is \
to give an honest initial read, NOT to anchor at any specific number. Do not anchor at 0.65. \
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
  "what_increases_conviction": string — 1-2 sentences. Name the SPECIFIC evidence, event, or \
data release that would most raise conviction for THIS company right now. PM-grade specificity \
required. This is the single most important missing piece that, if resolved, would change the \
investment decision. GOOD: "Clarity on hyperscaler CapEx guidance for H2 2026 would resolve \
the primary uncertainty — that data point determines whether the data-center revenue runway \
extends or plateaus." BAD: "More evidence would increase conviction." \
  "what_changes_the_thesis" : array of 4 strings — company-specific triggers that flip the thesis
  "core_takeaway"           : string — 1-2 sentences that make the thesis INSTANTLY CLEAR to \
an intelligent but non-institutional investor. Same analytical depth, accessible language. \
NOT educational. NOT simplified reasoning. Just clear expression of what matters. \
MUST answer: "What is the single most important thing to understand here?" \
GOOD: "The market already expects strong Services growth. The debate is whether that growth \
can continue fast enough to offset higher interest rates." \
GOOD: "The stock now depends more on margin expansion than revenue growth." \
BAD: "Apple is a strong company with risks and opportunities." \
BAD: "There are several factors to consider when evaluating this investment." \
Length: 1-2 sentences. Tone: intelligent, calm, clear. No jargon overload.
  "dominant_driver"         : string — 5-15 words max naming the SINGLE most important \
mechanism currently driving or threatening the thesis. A phrase, not a sentence. \
GOOD: "Services margin expansion offsetting hardware cyclicality" \
GOOD: "Rate duration compression on long-dated FCF multiples" \
GOOD: "China tariff impact on iPhone supply chain economics" \
BAD: "Multiple factors are influencing the investment case." \
This should be the answer to: "If you had to name ONE thing that matters most right now, what is it?"
  "conclusion"              : string — decision-compressive PM-grade conclusion. HARD LIMIT: 2 sentences. \
LEAD WITH POSITIONING AND EXPECTATION STRUCTURE — not mechanism explanation. \
Think of the final line of a trade desk recommendation memo: bottom-line view first, then the fulcrum. \
\
MANDATORY STRUCTURE: \
  Sentence 1 → Positioning call OR expectation structure — the bottom-line view. \
  Sentence 2 → The single risk or fulcrum that would change the view. NOT a mechanism restatement. \
\
REQUIRED PATTERNS for sentence 1 (use one, do not blend): \
(a) Positioning + expectation — "[Business] remains [quality], but the market already prices in [expectation]." \
(b) Expectation mis-pricing — "At current multiples, the market is underpricing [X] — the thesis holds if [Y]." \
(c) Expectation structure — "Current pricing already assumes [X]; the setup only works if [Y]." \
(d) Setup quality — "The setup is constructive — [expectation] is already embedded in the multiple." \
\
SENTENCE 1 RULES — STRICTLY ENFORCED: \
- MUST open with the positioning or expectation structure, not the mechanism \
- FORBIDDEN openers: "The thesis requires...", "This thesis requires...", "The business requires..." \
- FORBIDDEN openers: "The company remains...", "The stock needs...", "[Ticker]'s [noun] provides..." \
- FORBIDDEN openers: Any sentence beginning with the mechanism rather than the bottom-line view \
\
GOOD (decision-compressive, positioning-first): \
"Costco remains durable, but the market already prices in continued margin execution — the setup only \
works if renewal rates hold and ticket sizes expand." \
"At ~28x forward earnings, the market is paying for durable Cloud margin expansion, not just stability — \
the bear case is whether Search deceleration becomes structural before Azure offsets it." \
"Current pricing already assumes membership fee stability and operating leverage — the question is \
whether that assumption survives a softening consumer environment." \
"The setup is constructive — most downside is embedded in the multiple, but rate duration remains the exit risk." \
\
BAD (mechanism-first, avoid these): \
"The thesis requires Costco's margin expansion to outpace [anything]." \
"The company remains well-positioned despite headwinds." \
"This thesis requires [X] to materialize before the market reprices the multiple." \
"[Ticker]'s strong fundamentals support a positive outlook going forward." \
"Overall, the investment thesis is balanced with risks and opportunities on both sides." """


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
    question_intent: Optional[str] = None,
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

    # Build live-data provenance block (Truth Density phase)
    live_data_provenance_block = _build_live_data_provenance_block(evidence)

    # Build market regime context block from evidence (Phase G)
    market_regime_block = _build_market_regime_block(evidence)

    # Build core market debate mandate block (Phase G — Market Debate Hierarchy)
    debate_type = _classify_debate_type(dominant_dim, original_user_question)
    core_debate_mandate_block = _build_core_debate_mandate_block(
        company_name          = company.company_name,
        ticker                = company.ticker,
        dominant_dim          = dominant_dim,
        debate_type           = debate_type,
        original_user_question= original_user_question,
        prior_snapshot        = prior_snapshot,
    )

    # Build recent events block (Phase H)
    recent_events_block = _extract_recent_events(evidence)

    # Build expectation delta block (Phase H)
    expectation_delta_block = _build_expectation_delta_block(
        company_name=company.company_name,
        ticker=company.ticker,
        debate_type=debate_type,
    )

    # Build narrative state block (Phase H — only when prior snapshot available)
    narrative_state_block = _build_narrative_state_block(
        prior_snapshot=prior_snapshot,
        dominant_dim=dominant_dim,
        debate_type=debate_type,
    )

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
            f"Prior one-sentence thesis: {prev_thesis or prev_conclusion[:120] or '(none recorded)'}\n"
            f"Prior bull thesis (first sentence): {prev_bull[:150] or '(none)'}\n"
            f"Prior core debate: {prev_debate or '(none)'}\n"
            f"Prior top risks: {prev_risks_txt or '(none)'}\n\n"
            f"HISTORICAL REASONING — MANDATORY:\n"
            f"You have a prior thesis above. Compare it EXPLICITLY to the current evidence.\n"
            f"You MUST do all three of the following in your conclusion and confidence_reasoning:\n"
            f"  1. STATE whether the operating story changed (new fundamentals) or the market merely\n"
            f"     repriced the same thesis (rate/macro shift, sentiment, multiple compression).\n"
            f"     Be specific: 'The operating story is unchanged — the move came from rates, not earnings.'\n"
            f"  2. STATE whether the core debate evolved, narrowed, or intensified vs the prior view.\n"
            f"     Name what the prior debate was and what it is now.\n"
            f"  3. STATE whether the original bull thesis mechanism still holds, weakened, or broke.\n"
            f"     Quote or paraphrase the prior bull thesis and explain what happened to it.\n\n"
            f"GOOD HISTORICAL LANGUAGE (use these patterns):\n"
            f'  "The operating story is largely unchanged — the repricing came from rates, not fundamentals."\n'
            f'  "The prior bull thesis on [mechanism] held — [what confirmed it]."\n'
            f'  "The original margin assumption no longer holds — [what broke it]."\n'
            f'  "The debate narrowed from [prior X] toward [current Y] — the market resolved the prior ambiguity."\n'
            f'  "The burden shifted — [prior mechanism] is no longer the dominant driver."\n'
            f'  "Consensus already adjusted for [prior bear case]. The residual risk is [new concern]."\n'
            f'  "The setup is repricing, not deteriorating — the underlying thesis is intact."\n\n'
            f"BANNED HISTORICAL LANGUAGE:\n"
            f'  "confidence decreased" → state what changed and why\n'
            f'  "signals diverged" → name which forces diverged and what that means\n'
            f'  "analysis changed" → state the specific mechanism that moved\n'
            f'  "thesis updated" → explain the actual analytical shift\n'
            f'  DO NOT say "No prior thesis available" — you have the prior thesis above.\n\n'
        )
    else:
        historical_reasoning_block = ""

    # Build the question-anchor block (injected only when a question is present)
    # For valuation_stance questions ("Is X overpriced?") the block is
    # overridden to require an explicit verdict in direct_answer.
    if original_user_question and question_intent == "valuation_stance":
        # Pull valuation_stance from the valuation agent if available
        _stance = getattr(valuation, "valuation_stance", "") or ""
        _stance_reasoning = getattr(valuation, "valuation_stance_reasoning", "") or ""
        _val_conf = getattr(valuation, "confidence", 0.5)
        _low_conf_caveat = (
            "\n- CRITICAL: Evidence coverage is thin (valuation agent confidence < 0.45). "
            "You MUST include the phrase 'low-confidence' in your direct_answer and note "
            "which key data is missing (e.g. forward P/E, analyst price targets).\n"
            if _val_conf < 0.45 else ""
        )
        _stance_hint = (
            f"\nValuation agent verdict: {_stance} — {_stance_reasoning}"
            if _stance and _stance != "cannot_determine"
            else ""
        )
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"VALUATION STANCE ANSWER — MANDATORY FOR \"direct_answer\" FIELD:\n"
            f"The user is asking whether {company.company_name} ({ticker}) is "
            f"overpriced, fairly valued, or underpriced at the current price.\n"
            f"{_stance_hint}\n"
            f"Your `direct_answer` MUST:\n"
            f"  1. State the verdict explicitly in Sentence 1: "
            f'"Based on current multiples, {ticker} appears [overpriced / fairly valued / underpriced]…"\n'
            f"  2. Name the primary metric anchoring the verdict "
            f"(e.g. forward P/E, EV/EBITDA, FCF yield, analyst consensus target vs current price).\n"
            f"  3. State what growth or execution assumption the current price requires to be justified.\n"
            f"  4. Keep to 2 sentences total — verdict + mechanism only.\n"
            f"  FORBIDDEN: Hedging the verdict with 'it depends' without a directional lean.\n"
            f"  FORBIDDEN: Restating the question ('You asked whether {ticker} is overpriced…').\n"
            f"  FORBIDDEN: Opening with company description instead of the verdict.\n"
            f"{_low_conf_caveat}\n"
            f"Also set `valuation_stance` in the thesis output to one of: "
            f'"overpriced" | "fairly_valued" | "underpriced" | "cannot_determine"\n\n'
        )
    elif original_user_question:
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
{market_regime_block}{recent_events_block}{narrative_state_block}{core_debate_mandate_block}{expectation_delta_block}{historical_reasoning_block}{question_anchor_block}{ranked_signals_section}
SPECIALIST AGENT OUTPUTS:
{agent_summaries}

Key Risks Identified:
{key_risks_txt}

Recent Catalysts:
{catalysts_txt}

SUPPORTING EVIDENCE:
{ev_block}

{live_data_provenance_block}STOCK-MOVEMENT ORIENTATION — MANDATORY FOR ALL SECTIONS:
Every sentence must answer "What moves the stock?" — NOT "What describes the company?"

HIERARCHICAL DENSITY REQUIREMENT:
- direct_answer, conclusion → ultra-compressed, 2 sentences, mechanism + so-what only
- bull_thesis, bear_thesis → analytical depth layer: explain WHY the thesis works / breaks
  economically. Include operating leverage, capital structure, and second-order effects.
  Do NOT compress these to assertion-level. A 3-4 sentence analytical paragraph is correct.
- valuation_view, macro_sensitivity → 2 sentences each: state the structure and the
  sensitivity logic. Not a one-liner assertion — a complete analytical thought.
- what_increases_conviction → 1-2 sentences. Name the SPECIFIC evidence, event, or data
  release that would most raise conviction for THIS company. PM-grade specificity required.
  GOOD: "Clarity on hyperscaler CapEx guidance for H2 2026 would be the single biggest
        conviction driver — that determines whether the data-center revenue runway extends."
  GOOD: "The next pipeline Phase 3 readout and FDA response on the CFTR successor would
        resolve the primary uncertainty constraining conviction."
  BAD: "More evidence would increase conviction." (too generic)
  BAD: "Better market conditions would help." (not company-specific)

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
- "analysts expect", "consensus expects" → cite the actual estimate figure or omit
- "recent data suggests" → name the specific data item and its date
- "historically" without a date → "as of [period]" or name the specific historical reference
- "the stock is trading at" without citing the multiple → give the actual ratio from evidence

HALLUCINATION PREVENTION — ABSOLUTE RULES:
- NEVER invent a P/E ratio, EV/EBITDA, revenue figure, or price target not present in the evidence.
- If you do not have a specific figure, write "no current ratio data available" rather than estimating.
- Every cited number MUST have a corresponding [N] evidence citation.

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
- conclusion MUST begin with the directional positioning call — the bottom-line view — not a mechanism description.
  WRONG: "MSFT benefits from AI tailwinds that support the premium multiple."
  RIGHT: "Current pricing already assumes Copilot attach rate materialises — the setup only works if enterprise adoption holds through FY26."
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

MARKET-NATIVE COMPRESSION — MANDATORY:
Write at Bloomberg Intelligence / PM meeting note density. Not AI essay density.
Every section should read like an experienced PM summarizing to another PM — not explaining to a beginner.

BANNED verbose patterns → required compressed equivalents:
- "The company may face increasing competitive pressures in the future" → "The setup is less one-sided now."
- "There are both bullish and bearish considerations to weigh" → "This is becoming a harder timing call."
- "Growth remains positive but risks and uncertainties exist" → "The burden shifts to execution."
- "The stock could perform well if conditions are favorable" → "The stock works if X holds."
- "Investors should consider the potential impact of..." → "X is the unpriced risk here."
- "The company continues to benefit from..." → name the specific mechanism and its current rate of change
- "The valuation appears reasonable given..." → "At ~[X]x, the market is paying for Y — Z is the open variable."
- "The stock has shown resilience" → name what it held and why that matters for the investment
- "Macro environment remains uncertain" → "The rate path is unresolved — that is where duration risk lives."
- "The sector faces headwinds" → name the specific headwind, its transmission, and why it matters NOW

GOOD PM SHORTHAND (study these — understated, mechanism-first, timing-aware):
  "Nothing is broken yet." — complete statement, no elaboration needed
  "The setup is cleaner than it looks." — implies the bear case is less acute than priced
  "The bar is higher now." — implies the next print has to beat a raised consensus
  "The market still needs to see that." — implies execution has not yet proved the thesis
  "That is what the thesis requires." — closes the analytical loop without summarizing
  "This is a timing call more than a direction call." — compresses the uncertainty cleanly
  "The debate is not X — it is Y." — reframes without building to a conclusion
  "At these levels, if X holds, the stock works." — conditional entry logic in one sentence
  "Duration matters more here than direction." — rate sensitivity framing, compressed
  "Consensus is already long the good news." — implies upside is limited without saying so

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

0.6. core_takeaway: 1-2 sentences — state what matters most in clear, direct language. Not a
   summary. The one thing an intelligent person needs to understand about this investment right
   now. After writing it, ask: "Would someone who doesn't know finance jargon understand what
   matters?" If not, revise.

0.7. dominant_driver: ≤15 words — name the single most important mechanism. Choose between:
   the #1 upside driver OR the #1 structural risk, whichever is more market-relevant right now.

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


def _check_stance_conclusion_alignment(
    valuation: ValuationView,
    thesis: InvestmentThesis,
) -> List[str]:
    """Flag when valuation_stance contradicts buy/sell language in the conclusion.

    "overpriced" + conclusion that recommends buying (or vice versa) is an
    internal contradiction that confuses the user.
    """
    warnings: List[str] = []
    stance = (getattr(valuation, "valuation_stance", "") or "").lower().strip()
    if not stance or stance == "cannot_determine":
        return warnings

    conclusion_lower = (getattr(thesis, "conclusion", "") or "").lower()
    direct_lower = (getattr(thesis, "direct_answer", "") or "").lower()
    combined = conclusion_lower + " " + direct_lower

    _BUY_SIGNALS = ("buy", "long", "add exposure", "accumulate", "attractive entry",
                    "undervalued", "upside")
    _SELL_SIGNALS = ("sell", "short", "reduce", "exit", "overpriced", "stretched",
                     "overvalued", "avoid")

    has_buy = any(s in combined for s in _BUY_SIGNALS)
    has_sell = any(s in combined for s in _SELL_SIGNALS)

    if stance == "overpriced" and has_buy and not has_sell:
        warnings.append(
            f"[GOVERNANCE] Stance-conclusion contradiction for {thesis.ticker}: "
            f"valuation_stance='overpriced' but conclusion/direct_answer contains "
            f"buy-side language without bearish qualification. Verify alignment."
        )
    elif stance == "underpriced" and has_sell and not has_buy:
        warnings.append(
            f"[GOVERNANCE] Stance-conclusion contradiction for {thesis.ticker}: "
            f"valuation_stance='underpriced' but conclusion/direct_answer contains "
            f"sell-side language without bullish qualification. Verify alignment."
        )
    return warnings


def _check_stale_evidence_warning(
    evidence: List[RetrievedEvidence],
    thesis: InvestmentThesis,
) -> List[str]:
    """Flag when the thesis carries high confidence but evidence is old.

    Uses the confidence_calibrator's freshness check rather than re-implementing
    the staleness logic.  Adds a consistency_warning so the frontend can
    surface a 'data may be outdated' badge.
    """
    warnings: List[str] = []
    _, gaps = compute_evidence_coverage_gaps(evidence)
    stale_gaps = [g for g in gaps if "stale" in g.lower()]
    if stale_gaps and thesis.confidence_score > 0.60:
        for gap in stale_gaps:
            warnings.append(
                f"[GOVERNANCE] Stale evidence with elevated confidence "
                f"({thesis.confidence_score:.0%}) for {thesis.ticker}: {gap}"
            )
    return warnings


_GENERIC_CONFIDENCE_PHRASES: List[str] = [
    "limited evidence coverage",
    "evidence is sparse",
    "insufficient evidence",
    "evidence base is thin",
    "confidence is high",
    "conviction remains strong",
    "evidence is directionally constructive",
    "multiple factors",
    "various factors",
    "several considerations",
    "overall assessment",
]

# Phase 5c / productization: Hard-fail phrases that MUST NOT appear in production
# confidence_reasoning regardless of whether the company ticker is present.
# These are process artifacts or AI boilerplate — not analytical language.
# Any of these appearing means the legacy path or a generic fallback fired.
_HARD_FAIL_CONFIDENCE_PHRASES: List[str] = [
    # Legacy build_confidence_reasoning templates (signal_ranker.py Phase 5c)
    "limited evidence coverage means this position carries more uncertainty",
    "the framework is sound, the data is thin",
    "carries more uncertainty than the score reflects",
    "framework is sound",
    "more uncertainty than the score",
    # Remaining conviction_modeler fallback paths (productization pass)
    "the data is too thin to act on",
    "thesis framework exists but the data",
    "data is too sparse to act on",
    # Generic AI boilerplate that slips through LLM generation
    "it's worth noting that",
    "it is worth noting that",
    "this is a complex situation",
    "it is important to note",
    "there are many factors",
    "various factors contribute",
]


def _check_generic_confidence_reasoning(
    thesis: InvestmentThesis,
    company: CompanyContext,
) -> List[str]:
    """Flag when confidence_reasoning uses generic boilerplate instead of company-specific language.

    Phase 5c governance rules:
    1. HARD FAIL: exact fallback phrases from build_confidence_reasoning are ALWAYS flagged,
       regardless of whether the company ticker appears — they are process artifacts.
    2. SOFT FAIL: generic phrases without a company reference trigger a warning.

    The conviction modeler should always produce specific, company-anchored reasoning.
    This check is a canary for fallback leakage.
    """
    warnings: List[str] = []
    reasoning = (thesis.confidence_reasoning or "").lower()
    if not reasoning:
        return warnings

    ticker = getattr(company, "ticker", "") or ""

    # ── Hard-fail check: these templates NEVER belong in production output ────
    hard_hits = [p for p in _HARD_FAIL_CONFIDENCE_PHRASES if p in reasoning]
    if hard_hits:
        warnings.append(
            f"[GOVERNANCE] Hard-fail generic phrase in confidence_reasoning for {ticker}: "
            f"phrases={hard_hits}. These build_confidence_reasoning templates must be "
            f"replaced by the conviction modeler's company-specific output."
        )
        return warnings  # hard fail is conclusive — don't double-flag

    # ── Soft-fail check: generic phrases without any company reference ────────
    company_name = (getattr(company, "company_name", "") or "").lower()
    has_company_ref = ticker.lower() in reasoning or (
        len(company_name) > 3 and company_name[:6] in reasoning
    )

    generic_hits = [p for p in _GENERIC_CONFIDENCE_PHRASES if p in reasoning]
    if generic_hits and not has_company_ref:
        warnings.append(
            f"[GOVERNANCE] Generic confidence_reasoning for {ticker}: "
            f"phrases detected={generic_hits}. "
            f"Company-specific uncertainty drivers should be primary, not fallback."
        )
    return warnings


def _check_directional_stance_consistency(
    thesis: InvestmentThesis,
    company: CompanyContext,
) -> List[str]:
    """Detect contradictions between directional_stance and setup_label / conviction.

    Rules (deterministic — no LLM calls):
    1. Strong Buy + speculative setup → contradiction
    2. Strong Buy + fragile setup → contradiction
    3. Strong Buy + confidence_score < 0.60 → contradiction
    4. Sell + high-alignment thesis → contradiction
    5. Sell + confidence_score > 0.70 → contradiction
    6. Strong Buy + expectation_fragility > 0.70 → downgrade reasoning note
    """
    warnings: List[str] = []
    stance = (thesis.directional_stance or "Hold").strip()
    label  = (thesis.setup_label or "").lower().strip()
    score  = thesis.confidence_score or 0.0
    ticker = (getattr(company, "ticker", "") or "the company").upper()

    _SPECULATIVE_LABELS = {"speculative setup", "speculative", "insufficient conviction", "fragile setup"}
    _DURABLE_LABELS     = {"high-alignment thesis", "actionable thesis"}

    if stance == "Strong Buy":
        if label in _SPECULATIVE_LABELS:
            warnings.append(
                f"[GOVERNANCE] Directional contradiction on {ticker}: "
                f"stance=Strong Buy but setup_label='{label}'. "
                f"Strong Buy requires at minimum 'monitoring required' setup quality. "
                f"Stance should be downgraded to Buy or Hold."
            )
        if score < 0.60:
            warnings.append(
                f"[GOVERNANCE] Directional contradiction on {ticker}: "
                f"stance=Strong Buy but confidence_score={score:.2f} (<0.60). "
                f"Strong Buy requires conviction ≥0.60."
            )

    if stance == "Sell":
        if label in _DURABLE_LABELS:
            warnings.append(
                f"[GOVERNANCE] Directional contradiction on {ticker}: "
                f"stance=Sell but setup_label='{label}'. "
                f"Sell is incompatible with a durable/aligned setup."
            )
        if score > 0.70:
            warnings.append(
                f"[GOVERNANCE] Directional contradiction on {ticker}: "
                f"stance=Sell but confidence_score={score:.2f} (>0.70). "
                f"High-conviction theses should not produce a Sell stance."
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
    warnings.extend(_check_stance_conclusion_alignment(valuation, thesis))
    warnings.extend(_check_stale_evidence_warning(evidence, thesis))
    warnings.extend(_check_generic_confidence_reasoning(thesis, company))
    warnings.extend(_check_directional_stance_consistency(thesis, company))
    return warnings


# ── Graceful empty thesis ─────────────────────────────────────────────────────

def _empty_thesis(
    company: CompanyContext,
    reason: str = "",
    original_user_question: Optional[str] = None,
) -> InvestmentThesis:
    _ticker_empty = getattr(company, "ticker", None) or "UNKNOWN"
    logger.warning(
        "[FALLBACK_REASONING_TRIGGER] ticker=%s path=_empty_thesis "
        "source_function=_empty_thesis reason=%r "
        "confidence_reasoning=zero_evidence_sentinel score=0.0",
        _ticker_empty, reason or "no_evidence_or_agents",
    )
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
    question_intent: Optional[str] = None,
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
        question_intent=question_intent,
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

    # Stamp question_intent so the API response always carries it
    if question_intent:
        thesis.question_intent = question_intent

    # Propagate valuation_stance from the valuation agent into the thesis
    # when the user asked a price-fairness question.  The synthesiser LLM
    # may also set this field directly; the valuation agent's verdict wins
    # only when the thesis field was left empty by the synthesiser.
    if question_intent == "valuation_stance":
        _agent_stance = getattr(valuation, "valuation_stance", "") or ""
        if _agent_stance and not getattr(thesis, "valuation_stance", ""):
            thesis.valuation_stance = _agent_stance

    # Guard: core_market_debate must be non-empty; fall back to core_debate if LLM omitted it
    if not getattr(thesis, "core_market_debate", ""):
        thesis.core_market_debate = getattr(thesis, "core_debate", "")

    if not getattr(thesis, "core_takeaway", ""):
        # Fallback: construct from core_debate and direct_answer
        cda = getattr(thesis, "core_debate", "") or ""
        da = getattr(thesis, "direct_answer", "") or ""
        if cda:
            thesis.core_takeaway = cda
        elif da:
            thesis.core_takeaway = da[:200] if len(da) > 200 else da

    if not getattr(thesis, "dominant_driver", ""):
        # Fallback: use #1 key_driver or top signal label
        kd = getattr(thesis, "key_drivers", []) or []
        ts = getattr(thesis, "top_signals", []) or []
        if ts and hasattr(ts[0], "label"):
            thesis.dominant_driver = ts[0].label[:80]
        elif kd:
            thesis.dominant_driver = kd[0][:80]

    # Stamp dominant analytical dimension (deterministic, pre-LLM)
    thesis.dominant_dimension = dominant_dim_for_thesis

    # ── [CONFIDENCE_AUDIT] stage 1: LLM raw score ─────────────────────────────
    _ticker_audit = getattr(company, "ticker", "UNKNOWN") or "UNKNOWN"
    _llm_raw_score = thesis.confidence_score
    logger.info(
        "[CONFIDENCE_AUDIT] ticker=%s stage=llm_raw score=%.4f "
        "macro_conf=%.2f risk_conf=%.2f val_conf=%.2f evidence_count=%d",
        _ticker_audit, _llm_raw_score,
        macro.confidence, risk.confidence, valuation.confidence, len(evidence),
    )

    # ── R1: Legacy confidence realism cap (kept as safety floor) ─────────────
    # Still applied so that the old cap logic acts as a floor before the
    # conviction modeler's more granular computation runs.
    # NOTE: This cap is OVERRIDDEN by the conviction modeler at the end of this
    # block.  It only matters if the conviction modeler throws an exception.
    try:
        adjusted_conf, cap_triggers = compute_confidence_realism_cap(
            raw_score=thesis.confidence_score,
            macro_conf=macro.confidence,
            risk_conf=risk.confidence,
            quality_conf=quality.confidence,
            evidence_count=len(evidence),
            ranked=ranked,
        )
        logger.info(
            "[CONFIDENCE_AUDIT] ticker=%s stage=r1_legacy_cap "
            "pre=%.4f post=%.4f triggers=%s",
            _ticker_audit, thesis.confidence_score, adjusted_conf, cap_triggers,
        )
        if adjusted_conf < thesis.confidence_score:
            thesis.confidence_score = adjusted_conf
    except Exception as exc:
        logger.warning("[thesis_synthesizer] confidence realism cap failed: %r", exc)

    # ── R1b: Evidence coverage gap penalty (still applied for gap tracking) ──
    _cov_gaps: List[str] = []
    try:
        cov_penalty, _cov_gaps = compute_evidence_coverage_gaps(evidence)
        if cov_penalty > 0:
            pre_cov = thesis.confidence_score
            thesis.confidence_score = max(0.0, round(thesis.confidence_score - cov_penalty, 4))
            logger.info(
                "[CONFIDENCE_AUDIT] ticker=%s stage=r1b_coverage_gap "
                "pre=%.4f post=%.4f penalty=%.4f gaps=%s",
                _ticker_audit, pre_cov, thesis.confidence_score, cov_penalty, _cov_gaps,
            )
        else:
            logger.info(
                "[CONFIDENCE_AUDIT] ticker=%s stage=r1b_coverage_gap "
                "pre=%.4f post=%.4f penalty=0.0 gaps=[]",
                _ticker_audit, thesis.confidence_score, thesis.confidence_score,
            )
    except Exception as exc:
        logger.warning("[thesis_synthesizer] coverage gap penalty failed: %r", exc)

    # ── Attach ranked signals to thesis ──────────────────────────────────────
    if ranked is not None:
        thesis.top_signals = ranked.top_signals
        thesis.top_risks = ranked.top_risks
        thesis.secondary_signals = ranked.secondary_signals

    # ── Refinement 3: Evidence reference propagation ──────────────────────────
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

    # ── Phase 5++: cross-section duplication audit ────────────────────────────
    try:
        dedup_warnings = check_cross_section_duplication(thesis)
        if dedup_warnings:
            logger.debug(
                "[thesis_synthesizer] cross-section duplication: %d pair(s)",
                len(dedup_warnings),
            )
        warnings = warnings + dedup_warnings
    except Exception as exc:
        logger.warning("[thesis_synthesizer] cross-section dedup failed: %r", exc)

    thesis.consistency_warnings = warnings

    if warnings:
        for w in warnings:
            print(w)

    # ── Conviction modeler — institutional confidence calibration ─────────────
    # Replaces the legacy causal reasoning builder (build_confidence_reasoning)
    # with a seven-dimension decomposition that produces distributed scores and
    # company-specific uncertainty language.  Runs AFTER governance checks so
    # the governance_warnings list is complete.
    try:
        conviction = compute_conviction(
            evidence            = evidence,
            valuation           = valuation,
            macro               = macro,
            risk                = risk,
            market              = market,
            quality             = quality,
            company             = company,
            ranked              = ranked,
            governance_warnings = warnings,
            profile             = profile,
        )
        # Conviction modeler is ALWAYS authoritative — it replaces the LLM score entirely.
        # The LLM score is an initial read; the modeler applies dimensional decomposition,
        # company-specific uncertainty drivers, and contradiction compression on top.
        _pre_conviction_score = thesis.confidence_score
        thesis.confidence_score = conviction.final_score

        # ── [CONFIDENCE_AUDIT] stage 3: conviction modeler output ─────────────
        logger.info(
            "[CONFIDENCE_AUDIT] ticker=%s stage=conviction_modeler "
            "pre=%.4f post=%.4f "
            "linear_base=%.4f frag_score=%.4f frag_mult=%.4f "
            "asym_score=%.4f asym_mult=%.4f "
            "compression_reasons=%d setup_label=%s",
            _ticker_audit,
            _pre_conviction_score, conviction.final_score,
            getattr(conviction, "linear_base_score", conviction.final_score),
            conviction.dimensions.expectation_fragility, conviction.fragility_multiplier_applied,
            conviction.dimensions.expectation_asymmetry, conviction.asymmetry_multiplier_applied,
            len(conviction.compression_reasons or []),
            conviction.setup_label,
        )

        # Always override reasoning — conviction modeler is authoritative.
        # Phase 2: DO NOT append _cov_gaps (GAP_SPARSE | GAP_VALUATION | etc.) to
        # confidence_reasoning — these are internal telemetry labels, not user content.
        # Gap diagnostics remain available in the server logs ([CONFIDENCE_AUDIT]) and
        # the DEV debug panel via analysis_foundation_constraints (clean human-readable).
        thesis.confidence_reasoning = conviction.confidence_reasoning
        # Log gaps for DEV/ops observability without exposing them to users
        if _cov_gaps:
            logger.debug(
                "[coverage_gaps] ticker=%s gaps=%s",
                _ticker_audit, "; ".join(_cov_gaps),
            )

        # Stamp new fields — conviction modeler is authoritative for what_increases_conviction too
        thesis.what_increases_conviction = conviction.what_increases_conviction
        thesis.conviction_dimensions = conviction.dimensions.to_dict()

        # ── Phase 5d: Stamp setup quality fields onto thesis ──────────────────
        # CRITICAL: these three fields are NOT stamped automatically — they live
        # on ConvictionResult, not InvestmentThesis.  Without this block the
        # frontend always gets null/defaults ("actionable thesis" / 1.0 / 1.0)
        # because model_dump() only serialises InvestmentThesis fields.
        thesis.setup_label = conviction.setup_label
        thesis.fragility_multiplier_applied = conviction.fragility_multiplier_applied
        thesis.asymmetry_multiplier_applied = conviction.asymmetry_multiplier_applied
        thesis.directional_stance = conviction.directional_stance
        thesis.directional_stance_reasoning = conviction.directional_stance_reasoning

        # ── Phase 2: Stamp Analysis Foundation structured provenance ──────────
        # User-facing structured content — no internal labels or telemetry.
        thesis.analysis_foundation_evidence    = conviction.analysis_foundation_evidence
        thesis.analysis_foundation_constraints = conviction.analysis_foundation_constraints
        thesis.analysis_foundation_sources     = conviction.analysis_foundation_sources

        # ── [CONFIDENCE_PIPELINE] end-to-end telemetry ───────────────────────
        # Traces raw→fragility→asymmetry→compression→final for dispersion audits.
        _dims = conviction.dimensions
        logger.info(
            "[CONFIDENCE_PIPELINE] ticker=%s "
            "stage=final_conviction "
            "llm_raw=%.4f "
            "frag_score=%.4f frag_mult=%.4f "
            "asym_score=%.4f asym_mult=%.4f "
            "compression_reasons=%d "
            "final_score=%.4f "
            "setup_label=%s "
            "thesis_confidence_score=%.4f",
            _ticker_audit,
            _llm_raw_score,
            _dims.expectation_fragility, conviction.fragility_multiplier_applied,
            _dims.expectation_asymmetry, conviction.asymmetry_multiplier_applied,
            len(conviction.compression_reasons) if conviction.compression_reasons else 0,
            conviction.final_score,
            conviction.setup_label,
            thesis.confidence_score,
        )

        # ── Structured observability log ──────────────────────────────────────
        logger.info(
            "[conviction_modeler] ticker=%s score_pre=%.2f score_post=%.2f "
            "delta=%.2f compressed=%s compression_reasons=%s "
            "eq=%.2f ef=%.2f ta=%.2f mu=%.2f vc=%.2f ed=%.2f gr=%.2f "
            "frag=%.2f asym=%.2f frag_mult=%.3f asym_mult=%.3f setup_label=%s",
            getattr(company, "ticker", "UNKNOWN"),
            _pre_conviction_score,
            conviction.final_score,
            conviction.final_score - _pre_conviction_score,
            conviction.compression_applied,
            conviction.compression_reasons,
            conviction.dimensions.evidence_quality,
            conviction.dimensions.evidence_freshness,
            conviction.dimensions.thesis_alignment,
            conviction.dimensions.macro_uncertainty,
            conviction.dimensions.valuation_certainty,
            conviction.dimensions.estimate_dispersion,
            conviction.dimensions.governance_risk,
            conviction.dimensions.expectation_fragility,
            conviction.dimensions.expectation_asymmetry,
            conviction.fragility_multiplier_applied,
            conviction.asymmetry_multiplier_applied,
            conviction.setup_label,
        )
    except Exception as exc:
        _ticker_exc = getattr(company, "ticker", None) or "UNKNOWN"
        _tb_str = _traceback.format_exc()
        # ── [CONVICTION_PROPAGATION_FAILURE] mandatory assertion ──────────────
        # This fires whenever compute_conviction() throws — it means dims/setup_label/
        # fragility_multiplier will NOT be stamped onto the thesis and the frontend
        # will show llm_raw_preserved score with 0/9 dims.
        # Search for this marker in logs to identify the exact exception.
        logger.error(
            "[CONVICTION_PROPAGATION_FAILURE] ticker=%s "
            "exc_type=%s exc_repr=%r "
            "score_will_be=llm_raw_preserved "
            "dims_will_be=0/9 "
            "setup_label_will_be=actionable_thesis_default "
            "action=FIX_THIS_EXCEPTION "
            "traceback=%s",
            _ticker_exc, type(exc).__name__, exc, _tb_str,
        )
        print(
            f"[CONVICTION_PROPAGATION_FAILURE] [{_ticker_exc}] "
            f"exc_type={type(exc).__name__} exc={exc!r}\n"
            f"TRACEBACK:\n{_tb_str}"
        )
        logger.warning(
            "[FALLBACK_REASONING_TRIGGER] ticker=%s path=conviction_modeler_exception "
            "source_function=compute_conviction exc_type=%s "
            "action=preserve_llm_reasoning score_preserved=%.4f "
            "reason=conviction_modeler_threw_exception",
            _ticker_exc, type(exc).__name__, thesis.confidence_score,
        )
        logger.warning(
            "[thesis_synthesizer] conviction_modeler failed: %r — "
            "preserving LLM reasoning score (build_confidence_reasoning NOT called)",
            exc,
        )
        # CRITICAL: DO NOT call build_confidence_reasoning here.
        # That function produces generic phrases ("limited evidence coverage means this
        # position carries more uncertainty", "the framework is sound, the data is thin")
        # which the governance check flags as hard-fail violations.
        #
        # Phase 5g: preserve the LLM's confidence_reasoning UNLESS it contains a
        # hard-fail generic phrase (these are process artifacts, not analytical language).
        # When found, replace with a minimal company-specific fallback that is always
        # more analytically honest than the legacy boilerplate.
        try:
            _ticker_fb  = getattr(company, "ticker", None) or "the company"
            _sector_fb  = getattr(company, "sector", None) or ""
            _sector_str = f" in the {_sector_fb} sector" if _sector_fb else ""
            _reasoning_lc = (thesis.confidence_reasoning or "").lower()
            _has_hard_fail = any(
                phrase in _reasoning_lc for phrase in _HARD_FAIL_CONFIDENCE_PHRASES
            )
            if not thesis.confidence_reasoning or _has_hard_fail:
                _reason = "empty_llm_reasoning" if not thesis.confidence_reasoning else "hard_fail_phrase_in_llm_reasoning"
                logger.warning(
                    "[FALLBACK_REASONING_TRIGGER] ticker=%s path=%s "
                    "source_function=_synthesize_investment_thesis "
                    "reason=conviction_modeler_failed_replacing_legacy_phrase "
                    "action=generating_company_specific_minimal_fallback",
                    _ticker_fb, _reason,
                )
                thesis.confidence_reasoning = (
                    f"Conviction on {_ticker_fb}{_sector_str} is constrained by "
                    "unresolved variables in the evidence — "
                    "the analytical framework is directionally intact but open items "
                    "prevent a high-confidence assignment at this stage."
                )
            # Phase 2: gaps are logged for ops observability, NOT appended to user-visible reasoning.
            if _cov_gaps:
                logger.debug(
                    "[coverage_gaps_fallback] ticker=%s gaps=%s",
                    _ticker_fb, "; ".join(_cov_gaps),
                )
        except Exception as inner_exc:
            logger.warning(
                "[FALLBACK_REASONING_TRIGGER] ticker=%s path=inner_fallback_exception "
                "source_function=_synthesize_investment_thesis "
                "reason=company_specific_fallback_also_failed exc=%r",
                getattr(company, "ticker", "UNKNOWN"), inner_exc,
            )

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

    # ── Phase 5g: Sync compressed_thesis.one_sentence_thesis after polishing ──
    # compress_hero_thesis() in polish_thesis() strips the conviction bracket
    # "[moderate conviction, 65%]" from thesis.one_sentence_thesis (top-level),
    # but does NOT update thesis.compressed_thesis.one_sentence_thesis.
    # The frontend reads compressed_thesis.one_sentence_thesis first and would
    # show the stale unpolished bracket — this sync eliminates that path.
    if (
        thesis.one_sentence_thesis
        and thesis.compressed_thesis is not None
        and thesis.compressed_thesis.one_sentence_thesis != thesis.one_sentence_thesis
    ):
        try:
            _ct_synced = (
                thesis.compressed_thesis.model_copy(
                    update={"one_sentence_thesis": thesis.one_sentence_thesis}
                )
                if hasattr(thesis.compressed_thesis, "model_copy")
                else thesis.compressed_thesis.copy(  # type: ignore[attr-defined]
                    update={"one_sentence_thesis": thesis.one_sentence_thesis}
                )
            )
            thesis = (
                thesis.model_copy(update={"compressed_thesis": _ct_synced})
                if hasattr(thesis, "model_copy")
                else thesis.copy(update={"compressed_thesis": _ct_synced})  # type: ignore[attr-defined]
            )
            logger.debug(
                "[thesis_synthesizer] compressed_thesis.one_sentence_thesis synced after polishing "
                "ticker=%s hero=%r",
                getattr(company, "ticker", "UNKNOWN"),
                thesis.one_sentence_thesis[:60],
            )
        except Exception as _sync_exc:
            logger.warning(
                "[thesis_synthesizer] compressed_thesis sync failed (non-fatal): %r", _sync_exc
            )

    overlap_count = sum(1 for w in warnings if w.startswith("[OVERLAP]"))
    gov_count = len(warnings) - len(depth_warnings) - len(quality_warnings) - overlap_count

    # ── [LIVE_CONFIDENCE_AUDIT] — end-to-end truth path for dispersion tracing ──
    # This single log consolidates every stage of the confidence score pipeline.
    # Use this to verify that conviction_modeler score (not LLM raw) reaches the
    # API response, and that no mid-pipeline step silently collapses dispersion.
    #
    # Stages:
    #   llm_raw      — LLM's initial confidence_score (anchoring signal)
    #   r1_legacy    — after compute_confidence_realism_cap() (overridden by modeler)
    #   conviction   — conviction_modeler.final_score (AUTHORITATIVE)
    #   thesis_final — thesis.confidence_score at serialization time (should == conviction)
    #   setup_label  — semantic band label (drives frontend Setup Quality meter)
    #   score_source — which path produced the final score
    # ── Stamp score_source provenance field ──────────────────────────────────────
    # Determines and stamps the authoritative score provenance onto the thesis.
    # Travels in the API response so the frontend forensic overlay can display it
    # without re-deriving it from other fields.
    _has_conviction_dims = bool(thesis.conviction_dimensions)
    if _has_conviction_dims and thesis.setup_label != "actionable thesis":
        _score_source = "conviction_modeler"
    elif _has_conviction_dims:
        # Conviction modeler ran but produced balanced/default label
        _score_source = "conviction_modeler_balanced"
    elif thesis.confidence_score == 0.0:
        _score_source = "fallback_empty"
    else:
        _score_source = "llm_raw_preserved"
    # Stamp onto thesis so it travels in the serialized API response
    thesis.score_source = _score_source

    logger.info(
        "[LIVE_CONFIDENCE_AUDIT] ticker=%s "
        "llm_raw=%.4f "
        "conviction_modeler=%.4f "
        "thesis_final=%.4f "
        "setup_label=%s "
        "score_source=%s "
        "fragility_mult=%.4f "
        "asymmetry_mult=%.4f "
        "confidence_reasoning_len=%d "
        "fallback_fired=%s",
        getattr(company, "ticker", "UNKNOWN"),
        _llm_raw_score,
        thesis.confidence_score,   # == conviction_modeler output if modeler succeeded
        thesis.confidence_score,
        thesis.setup_label,
        _score_source,
        thesis.fragility_multiplier_applied,
        thesis.asymmetry_multiplier_applied,
        len(thesis.confidence_reasoning or ""),
        str(_score_source == "llm_raw_preserved"),
    )

    # ── [CONVICTION_PROPAGATION_FAILURE] mandatory pre-serialization assertion ──
    # If this fires, the conviction modeler did NOT propagate. The API response
    # will show 0/9 dims and llm_raw_preserved score on the frontend.
    # Fix: look for [CONVICTION_PROPAGATION_FAILURE] earlier in the same log stream.
    if _score_source == "llm_raw_preserved":
        logger.error(
            "[CONVICTION_PROPAGATION_FAILURE] ticker=%s "
            "stage=pre_serialization "
            "conviction_dimensions_count=%d "
            "setup_label=%r "
            "fragility_mult=%.4f "
            "score_source=llm_raw_preserved "
            "ACTION=investigate_CONVICTION_PROPAGATION_FAILURE_above_in_logs",
            getattr(company, "ticker", "UNKNOWN"),
            len(thesis.conviction_dimensions or {}),
            thesis.setup_label,
            thesis.fragility_multiplier_applied,
        )
        print(
            f"[CONVICTION_PROPAGATION_FAILURE] [{getattr(company, 'ticker', 'UNKNOWN')}] "
            f"pre_serialization: dims={len(thesis.conviction_dimensions or {})}/9 "
            f"setup_label={thesis.setup_label!r} "
            f"score={thesis.confidence_score:.4f} (llm_raw, NOT conviction_modeler) "
            f"— search earlier logs for [CONVICTION_PROPAGATION_FAILURE] to find the exception"
        )

    # ── [HEADLINE_CONFIDENCE_SOURCE] — audit log for headline + confidence layer ──
    # This log proves which formatter produced the visible confidence/conviction
    # layer in the API response.  used_legacy_formatter=true means the conviction
    # modeler did NOT run; the LLM's raw score and reasoning were preserved.
    _reasoning_lc = (thesis.confidence_reasoning or "").lower()
    _has_hard_fail_phrase = any(p in _reasoning_lc for p in _HARD_FAIL_CONFIDENCE_PHRASES)
    _used_legacy = _score_source == "llm_raw_preserved"
    logger.info(
        "[HEADLINE_CONFIDENCE_SOURCE] ticker=%s "
        "headline_text=%r "
        "confidence_score=%.4f "
        "confidence_label=%s "
        "setup_label=%s "
        "source_function=%s "
        "used_legacy_formatter=%s "
        "hard_fail_phrase_in_reasoning=%s "
        "one_sentence_thesis=%r",
        getattr(company, "ticker", "UNKNOWN"),
        (thesis.direct_answer or thesis.conclusion or "")[:80],
        thesis.confidence_score,
        (
            "high" if thesis.confidence_score >= 0.75
            else "moderate" if thesis.confidence_score >= 0.55
            else "low"
        ),
        thesis.setup_label or "ABSENT",
        "conviction_modeler" if not _used_legacy else "llm_raw_preserved",
        str(_used_legacy),
        str(_has_hard_fail_phrase),
        (thesis.one_sentence_thesis or "")[:60],
    )
    if _used_legacy:
        print(
            f"[HEADLINE_CONFIDENCE_SOURCE] [{getattr(company, 'ticker', 'UNKNOWN')}] "
            f"used_legacy_formatter=true "
            f"score={thesis.confidence_score:.2f} "
            f"setup_label={thesis.setup_label!r} "
            f"hard_fail_phrase={_has_hard_fail_phrase} "
            f"→ conviction_modeler exception — search [CONVICTION_PROPAGATION_FAILURE]"
        )
    else:
        print(
            f"[HEADLINE_CONFIDENCE_SOURCE] [{getattr(company, 'ticker', 'UNKNOWN')}] "
            f"used_legacy_formatter=false ✓ "
            f"score={thesis.confidence_score:.2f} "
            f"setup_label={thesis.setup_label!r} "
            f"score_source={_score_source}"
        )

    print(
        f"[thesis_synthesizer] done for {company.ticker}: "
        f"confidence={thesis.confidence_score:.2f} "
        f"setup_label={thesis.setup_label} "
        f"score_source={_score_source} "
        f"dims={len(thesis.conviction_dimensions or {})}/9 "
        f"warnings={len(warnings)} "
        f"(governance={gov_count}, depth={len(depth_warnings)}, "
        f"quality={len(quality_warnings)}, overlap={overlap_count}) "
        f"top_signals={len(thesis.top_signals)} "
        f"top_risks={len(thesis.top_risks)}"
    )

    # ── Live Intelligence: persistence metadata and freshness stamping ────────
    # Stamped after all scoring is complete so version_id and freshness reflect
    # the final synthesized state — not an intermediate.
    try:
        import uuid as _uuid
        thesis.thesis_version_id = str(_uuid.uuid4())

        # Evidence freshness profile — dimension-level age metadata
        _fp = analyze_evidence_freshness(evidence)
        thesis.evidence_freshness = _fp.to_dict()

        # Active uncertainty drivers from conviction modeler dimensions
        if thesis.conviction_dimensions:
            # Most stale or uncertain dimensions become monitored_drivers
            _stale_dims = _fp.stale_dimensions()
            if _stale_dims:
                thesis.monitored_drivers = _stale_dims
            elif thesis.conviction_dimensions:
                # Fall back to the lowest-scoring conviction dimensions
                _dim_scores = thesis.conviction_dimensions
                _worst = sorted(
                    [(k, v) for k, v in _dim_scores.items() if v is not None],
                    key=lambda x: x[1]
                )[:2]
                thesis.monitored_drivers = [k for k, _ in _worst]

        logger.debug(
            "[thesis_synthesizer] persistence metadata stamped: "
            "version_id=%s freshness_dims=%s monitored_drivers=%s",
            thesis.thesis_version_id,
            list(thesis.evidence_freshness.keys()),
            thesis.monitored_drivers,
        )
    except Exception as _pe:
        logger.warning(
            "[thesis_synthesizer] persistence metadata stamping failed (non-fatal): %r", _pe
        )

    return thesis
