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
import time as _time

from ..structured_output import get_structured_response, extract_json_candidate, repair_data
from ..model_client import synthesis_client as model_client
from ..config import settings
from .depth_guard import check_synthesis_depth, inject_revenue_context

# ── Compound-risk retry wall-clock budget ─────────────────────────────────────
# The compound-risk retry makes one additional model_client.call() after the
# primary synthesis.  On Render free tier, Nginx kills connections at ~61 s
# (proxy_read_timeout).  If the primary synthesis LLM call already consumed
# more than this many seconds by the time the validator fires, we skip the
# retry entirely and fall back to the advisory warning path — keeping total
# request time safely under the ceiling.
#
# Derivation (conservative):
#   61 s  Render Nginx ceiling
#  -25 s  agent pipeline baseline (5 sequential agents, ~5 s each)
#   - 3 s  router / evidence overhead
#   - 3 s  post-synthesis processing (depth guard, conviction modeler, etc.)
#   -20 s  estimated retry duration (one targeted bear_thesis LLM call)
#   ──────────────────────────────────────────────────────────────────
#  = 10 s  safety margin  →  skip if synthesis call has consumed > 10 s
#
# Set to 0.0 on Render free tier: the compound retry adds 15-30s to the
# synthesis phase, pushing the total pipeline past the hard 61s Nginx
# proxy_read_timeout.  With budget=0.0, synthesis_elapsed is always >0s,
# so the retry is always skipped.  The main synthesis still produces a
# complete bear thesis; the compound-risk patch is a quality enhancement
# that can be re-enabled when moving to a paid tier with a longer timeout.
_COMPOUND_RETRY_WALL_BUDGET_S: float = 0.0
from .signal_ranker import (
    rank_signals,
    reweight_signals_for_intent,
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
from .conviction_modeler import compute_conviction, _compute_business_durability, _ARCHETYPE_DURABLE_THRESHOLD, _ARCHETYPE_QUALITY_THRESHOLD
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
    # Sprint 1 fields (2026-06-08)
    "why_not",          # P2: Why-Not-X counter-thesis (4-sentence with invalidation)
    "threshold_zones",  # P3: bull/bear breakpoint zones (always 3 zones)
    # Phase 8 fields (2026-06-08)
    "verdict_rationale",  # Phase 8: 1-sentence verdict card rationale
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

# Phase 2 Lever 1 + Phase 3 extension: map question_intent → dominant_dim override.
# Used in _build_synthesis_prompt() and exported for tests.
_INTENT_TO_DOMINANT_DIM: Dict[str, str] = {
    "competitive_position": "operational",   # bull/bear anchored on product/moat mechanics
    "macro_sensitivity":    "macro",          # macro_sensitivity DEEP, valuation COMPRESSED
    "risk_assessment":      "regulatory",     # bear_thesis DEEP — closest structural proxy
    # Phase 3 additions:
    "investment_thesis":    "operational",   # business model durability question → operating mechanics
    "business_model":       "operational",   # same treatment — unit economics / revenue quality
    # valuation_stance intentionally omitted: keyword scoring already converges on "valuation"
    # for most megacap names, and the existing valuation_stance block handles it.
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

CONCLUSION REQUIREMENT — 2 sentences HARD CAP, positioning-first, PM-grade:
The conclusion is the most important output. It must read like a portfolio manager's one-line
assessment after reviewing a full IC memo — not an academic summary or mechanism explanation.

SENTENCE 1 — Positioning verdict (REQUIRED):
  Open with the BOTTOM-LINE SETUP VIEW: what is the market pricing, and is that defensible?
  The reader must know the positioning stance within the first 10 words.
  APPROVED OPENERS:
    "[Business] remains [quality], but the market already prices in [X] — [condition]."
    "At ~[X]x, the setup already assumes [Y]; the risk is whether [Z] holds."
    "[Business] is durable, but the stock setup is [demanding/expectation-sensitive]."
    "The business quality is not in question; the debate is whether [pricing/timing/execution]."

SENTENCE 2 — Fulcrum or exit (REQUIRED):
  Name the specific condition that would change the positioning view — either a catalyst that
  would upgrade conviction, or the specific thing that would prove the setup wrong.

STRICTLY FORBIDDEN — these trigger immediate rewrite:
  "The thesis requires..." / "The company remains..." / "The business has..."
  "This thesis requires [Company] to..." / "[Ticker]'s [noun] provides..."
  Any sentence beginning with a mechanism before the positioning verdict.
  Generic headwind/tailwind summaries with no bottom-line positioning.
  Restating the bull/bear case instead of giving a verdict.

ARCHETYPE VOCABULARY (use the right register for this business):
  Durable compounder at premium: "priced for continued execution", "expectation-sensitive at current levels", "valuation already prices in the moat"
  Expectation-sensitive quality: "demanding setup", "limited room for misses", "acceleration priced in not continuation"
  Narrative-fragile: "speculative at current multiples", "binary on [X]", "execution dependency too concentrated"

CONCRETE EXAMPLE — durable compounder at elevated valuation:
  GOOD: "[Ticker] likely remains a durable compounder, but current valuation leaves limited room for execution misses."
  BAD:  "The thesis requires [Ticker] margin expansion to validate the current multiple."
  Why the GOOD version wins: it opens with a positioning verdict ("likely remains… durable") and
  immediately frames the risk from the market's perspective ("limited room"), not the business
  mechanism ("margin expansion required"). The reader knows the stance in the first 7 words.

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
    # Phase 4B calibration: threshold lowered 0.58 → 0.35.
    # The old 0.58 threshold fired for nearly every company (most macro agents
    # return confidence 0.40–0.55 on standard analyses), artificially elevating
    # macro to dominant_dim for operationally-driven businesses like AMZN and NEE.
    # The new threshold 0.35 reserves the macro boost for genuinely unresolved
    # macro regimes (e.g. Fed pivot inflection points, tariff shock quarters)
    # where macro uncertainty truly dominates the investment case.
    if macro.confidence < 0.35:
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


# ── Phase 2 Lever 2: Question-aware agent sub-field injection ─────────────────

def _build_agent_summaries(
    valuation: "ValuationView",
    macro: "MacroSensitivity",
    risk: "RiskProfile",
    market: "MarketContext",
    quality: "QualityAssessment",
    question_intent: Optional[str] = None,
) -> str:
    """Build the specialist-agent summaries block for the synthesis prompt.

    Phase 2 Lever 2: when ``question_intent`` is set, inject the single most
    question-relevant sub-field alongside each agent's ``.overall`` summary.
    This surfaces the depth content that Phase 1 emphasis blocks produced
    (``rate_sensitivity``, ``moat``, ``competitive_risk``, etc.) into the
    synthesis prompt so the LLM can anchor on it rather than only on ``.overall``.

    Injection is additive — ``.overall`` is always included; sub-fields append
    immediately after the relevant agent block under an indented "→ <label>:" line.
    The injected text is kept verbatim from the agent field so the synthesis LLM
    sees exactly what the specialist agent produced for the relevant dimension.
    """
    # Per-intent: agent-label → list of (sub-label, field-value) pairs to inject.
    # Keys must match the label strings passed to _agent_block exactly.
    sub_field_injections: Dict[str, List[tuple]] = {}

    if question_intent == "competitive_position":
        sub_field_injections = {
            "Business Quality": [
                ("Moat detail",            getattr(quality, "moat",             "") or ""),
            ],
            "Risk Profile": [
                ("Competitive risk detail", getattr(risk,    "competitive_risk", "") or ""),
            ],
            "Market Context": [
                ("Sentiment/competitive",   getattr(market,  "sentiment",        "") or ""),
            ],
        }
    elif question_intent == "macro_sensitivity":
        sub_field_injections = {
            "Macro Sensitivity": [
                ("Rate sensitivity detail", getattr(macro,   "rate_sensitivity",  "") or ""),
                ("Recession risk detail",   getattr(macro,   "recession_risk",    "") or ""),
            ],
            "Business Quality": [
                ("Revenue durability",      getattr(quality, "revenue_durability","") or ""),
            ],
        }
    elif question_intent == "valuation_stance":
        sub_field_injections = {
            "Valuation": [
                ("P/E assessment",          getattr(valuation, "pe_assessment",        "") or ""),
                ("Discount-rate sensitivity", getattr(valuation, "discount_sensitivity","") or ""),
            ],
            "Business Quality": [
                ("Operating quality",       getattr(quality,   "operating_quality",    "") or ""),
            ],
        }
    elif question_intent == "risk_assessment":
        sub_field_injections = {
            "Risk Profile": [
                ("Competitive risk detail", getattr(risk, "competitive_risk", "") or ""),
                ("Regulatory risk detail",  getattr(risk, "regulatory_risk",  "") or ""),
                ("Debt / balance sheet",    getattr(risk, "debt_risk",        "") or ""),
            ],
            "Business Quality": [
                ("Capital allocation risk", getattr(quality, "capital_allocation", "") or ""),
            ],
        }
    elif question_intent in ("investment_thesis", "business_model"):
        # Phase 3: surface business model quality sub-fields so the synthesis LLM
        # anchors the thesis on revenue durability and operating quality rather than
        # defaulting to a generic company overview.
        sub_field_injections = {
            "Business Quality": [
                ("Revenue durability",  getattr(quality,   "revenue_durability",  "") or ""),
                ("Operating quality",   getattr(quality,   "operating_quality",   "") or ""),
            ],
            "Valuation": [
                ("Growth view",         getattr(valuation, "growth_view",          "") or ""),
                ("Margin trend",        getattr(valuation, "margin_trend",         "") or ""),
            ],
        }
    # ── Phase 4 intents: surface the most relevant sub-fields ─────────────────
    elif question_intent == "implied_growth_rate":
        sub_field_injections = {
            "Valuation": [
                ("P/E assessment",      getattr(valuation, "pe_assessment",        "") or ""),
                ("Growth view",         getattr(valuation, "growth_view",          "") or ""),
                ("Relative value",      getattr(valuation, "relative_value",       "") or ""),
            ],
        }
    elif question_intent == "timing_lag":
        sub_field_injections = {
            "Macro Sensitivity": [
                ("Rate sensitivity",    getattr(macro,    "rate_sensitivity",      "") or ""),
                ("Recession risk",      getattr(macro,    "recession_risk",        "") or ""),
            ],
            "Valuation": [
                ("Growth view",         getattr(valuation, "growth_view",          "") or ""),
            ],
        }
    elif question_intent == "quantitative_threshold":
        sub_field_injections = {
            "Risk Profile": [
                ("Competitive risk",    getattr(risk,     "competitive_risk",      "") or ""),
                ("Debt / balance sheet",getattr(risk,     "debt_risk",             "") or ""),
            ],
            "Valuation": [
                ("Discount sensitivity",getattr(valuation,"discount_sensitivity",  "") or ""),
                ("P/E assessment",      getattr(valuation, "pe_assessment",        "") or ""),
            ],
        }
    elif question_intent == "metric_ordering":
        sub_field_injections = {
            "Macro Sensitivity": [
                ("Recession risk",      getattr(macro,    "recession_risk",        "") or ""),
            ],
            "Business Quality": [
                ("Revenue durability",  getattr(quality,   "revenue_durability",   "") or ""),
                ("Operating quality",   getattr(quality,   "operating_quality",    "") or ""),
            ],
            "Valuation": [
                ("Margin trend",        getattr(valuation, "margin_trend",         "") or ""),
            ],
        }
    elif question_intent == "segment_ranking":
        sub_field_injections = {
            "Business Quality": [
                ("Moat detail",         getattr(quality,   "moat",                 "") or ""),
                ("Revenue durability",  getattr(quality,   "revenue_durability",   "") or ""),
            ],
            "Valuation": [
                ("Relative value",      getattr(valuation, "relative_value",       "") or ""),
            ],
        }
    elif question_intent == "historical_precedent":
        sub_field_injections = {
            "Valuation": [
                ("P/E assessment",      getattr(valuation, "pe_assessment",        "") or ""),
                ("Relative value",      getattr(valuation, "relative_value",       "") or ""),
            ],
            "Business Quality": [
                ("Operating quality",   getattr(quality,   "operating_quality",    "") or ""),
            ],
        }

    def _enriched_block(label: str, overall: str, confidence: float) -> str:
        base = _agent_block(label, overall, confidence)
        extras = sub_field_injections.get(label, [])
        if not extras:
            return base
        detail_lines = []
        for sub_label, sub_text in extras:
            stripped = (sub_text or "").strip()
            if stripped:
                detail_lines.append(f"  → {sub_label}: {stripped}")
        if detail_lines:
            base = base + "\n" + "\n".join(detail_lines)
        return base

    return "\n\n".join([
        _enriched_block("Valuation",         valuation.overall, valuation.confidence),
        _enriched_block("Macro Sensitivity",  macro.overall,     macro.confidence),
        _enriched_block("Risk Profile",       risk.overall,      risk.confidence),
        _enriched_block("Market Context",     market.overall,    market.confidence),
        _enriched_block("Business Quality",   quality.overall,   quality.confidence),
    ])


# ── Phase 3: Secondary-section mandates per question_intent ──────────────────

def _build_secondary_section_mandates(
    ticker: str,
    question_intent: Optional[str],
) -> str:
    """Build per-intent mandates for the 4 secondary sections that still converge.

    Phase 2 differentiated primary sections (bull_thesis, bear_thesis, core_debate,
    direct_answer, macro_sensitivity, valuation_view) via dominant_dim override,
    sub-field injection, and section anchor mandates.  Four secondary sections
    remained at 55–75% overlap because they lacked per-intent instructions:

      • one_sentence_thesis  — defaults to generic company positioning
      • key_drivers          — Azure/AI always leads regardless of question
      • what_increases_conviction — generic earnings catalysts for all questions
      • conclusion           — 2-sentence COMPRESSED with no intent-specific framing

    This function returns a short, targeted mandate block for all four sections
    that redirects each toward the dimension the user actually asked about.
    Injected immediately after the question_anchor_block in the synthesis prompt.
    Returns empty string for None intent (backward compat).
    """
    if not question_intent:
        return ""

    if question_intent == "competitive_position":
        return (
            f"SECONDARY SECTION MANDATES — COMPETITIVE QUESTION:\n"
            f"  one_sentence_thesis: State the competitive verdict — "
            f"'{ticker} moat is [strengthening/stable/eroding] because [specific dynamic].'\n"
            f"  key_drivers: 1ST DRIVER MUST BE A COMPETITIVE FACTOR "
            f"(moat durability, market-share trajectory, switching-cost depth). "
            f"Do NOT lead with a macro or valuation driver.\n"
            f"  what_increases_conviction: Name 1 CONFIRMING signal (market-share data, "
            f"enterprise win rate, renewal metric) AND 1 DISCONFIRMING signal (competitor "
            f"win announcement, workload-migration data). Not generic earnings beats.\n"
            f"  conclusion: End with the competitive outcome + monitoring trigger — "
            f"'Hold / add if [competitive metric] confirms moat durability; "
            f"reduce if [specific competitive risk] materializes.'\n\n"
        )
    elif question_intent == "macro_sensitivity":
        return (
            f"SECONDARY SECTION MANDATES — MACRO QUESTION:\n"
            f"  one_sentence_thesis: State the macro setup verdict — "
            f"'{ticker} is [defensively positioned / rate-sensitive / cyclically exposed] "
            f"because [specific transmission mechanism].'\n"
            f"  key_drivers: 1ST DRIVER MUST BE A MACRO/RATE FACTOR "
            f"(rate path, economic cycle, capex-cycle sensitivity). "
            f"Do NOT lead with a competitive or product driver.\n"
            f"  what_increases_conviction: Name 1 MACRO CONFIRMING signal "
            f"(Fed action, CPI/PCE print, enterprise IT spend survey, yield-curve move) AND "
            f"1 MACRO DISCONFIRMING signal. Not product-launch or competitive news.\n"
            f"  conclusion: End with rate-scenario-dependent positioning — "
            f"'Constructive if [rate/macro scenario]; reduce exposure if [adverse macro scenario].'\n\n"
        )
    elif question_intent == "valuation_stance":
        return (
            f"SECONDARY SECTION MANDATES — VALUATION QUESTION:\n"
            f"  one_sentence_thesis: State the valuation verdict explicitly — "
            f"'At ~[X]x forward [metric], {ticker} is [overpriced/fairly valued/underpriced] "
            f"because [primary valuation anchor].'\n"
            f"  key_drivers: 1ST DRIVER MUST BE A VALUATION/MULTIPLE DRIVER "
            f"(multiple expansion/compression catalyst, earnings revision trajectory, "
            f"analyst consensus vs current price). Not a moat or product driver.\n"
            f"  what_increases_conviction: Name 1 VALUATION CONFIRMING signal "
            f"(earnings beat, analyst upgrade cluster, PT revision) AND "
            f"1 VALUATION DISCONFIRMING signal (guidance cut, multiple re-rate trigger).\n"
            f"  conclusion: End with explicit entry/exit levels — "
            f"'Add at [X]x [metric]; avoid above [Y]x [metric].'\n\n"
        )
    elif question_intent == "risk_assessment":
        return (
            f"SECONDARY SECTION MANDATES — RISK QUESTION:\n"
            f"  one_sentence_thesis: State the risk-adjusted verdict — "
            f"'The risk-reward for {ticker} is [favorable/balanced/unfavorable] because "
            f"[primary risk] is [priced/underpriced/mispriced] at current levels.'\n"
            f"  key_drivers: 1ST DRIVER MUST BE THE PRIMARY RISK FACTOR "
            f"(the mechanism that most threatens the thesis). Not a growth or moat driver.\n"
            f"  what_increases_conviction: Name 1 RISK-MATERIALIZING signal (the trigger "
            f"that confirms the risk is real) AND 1 RISK-RESOLUTION signal (the data point "
            f"that takes the risk off the table).\n"
            f"  conclusion: End with the risk-monitoring stance — "
            f"'Monitor [specific trigger]; reduce if [risk event]; add if [risk resolves].'\n\n"
        )
    elif question_intent in ("investment_thesis", "business_model"):
        return (
            f"SECONDARY SECTION MANDATES — BUSINESS MODEL / THESIS QUESTION:\n"
            f"  one_sentence_thesis: Frame as business model durability verdict — "
            f"'{ticker}'s [primary revenue engine] is [accelerating/stable/at risk] "
            f"because [specific operating mechanic or unit economic].'\n"
            f"  key_drivers: 1ST DRIVER MUST BE A BUSINESS MODEL DRIVER "
            f"(revenue durability, unit economics, operating leverage, pricing power). "
            f"Not a rate or competitive driver.\n"
            f"  what_increases_conviction: Name 1 EXECUTION CONFIRMING signal "
            f"(ARR growth, gross-margin expansion, FCF conversion, seat/unit additions) AND "
            f"1 EXECUTION DISCONFIRMING signal (miss vs consensus, guidance cut, "
            f"churn signal, pricing-power erosion).\n"
            f"  conclusion: End with business model verdict + execution trigger — "
            f"'Thesis intact if [operating metric] holds; reassess if [execution risk] appears.'\n\n"
        )
    return ""


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
  "verdict_rationale"       : string — MANDATORY. 1 sentence. Mechanism + expectation setup. \
NOT a repeat of directional_stance_reasoning. Name the specific driver behind the verdict. \
GOOD: "Data center revenue growing 122% YoY ahead of consensus — setup is constructive at current multiples."
  "direct_answer"           : string — EXACTLY 4 sentences answering the user's question. \
S1: verdict/conclusion first — NEVER company background. S2: primary mechanism. \
S3: key metric or threshold. S4: what would change the view. \
GOOD S1: "Nvidia's data center setup is constructive — the question is duration, not direction." \
BAD S1: any sentence that opens with company history or "X is a leading provider of..."
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
  "why_not"                 : string — MANDATORY. 4 sentences: \
S1: "The bull case rests on the assumption that [assumption]." \
S2: "The counter-thesis: [alternative scenario that breaks that assumption]." \
S3: "The tell: [metric/event] [falling/rising] to [threshold] would signal the bull case has broken." \
S4: "This analysis would be wrong if [specific invalidation condition]." \
NOT a repeat of bear_thesis — must name a NEW angle with leading indicator + invalidation. \
See SPRINT 1 INTELLIGENCE FIELDS section below for full guidance.
  "threshold_zones"         : array of 3 objects — MANDATORY, never empty. \
Include: (1) valuation metric, (2) operating/fundamental metric, (3) risk/macro metric. \
Each: {"metric": string, "bull_threshold": string, "bear_threshold": string, "rationale": string}. \
See SPRINT 1 INTELLIGENCE FIELDS section below for guidance.
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
  "thesis_evolution"        : string — 2-3 sentence "What Changed?" narrative (MANDATORY). \
Synthesize what has recently shifted in the investment story. Answer: "What does a PM returning \
after 2 weeks need to know has changed?" Draw from: estimate revisions, management tone, \
debate evolution, macro regime shift, multiple re-rating, acceleration/deceleration. \
REQUIRED patterns (use whichever applies): \
  "The debate shifted from [X] toward [Y] — [driver]." \
  "Consensus expectations [expanded/contracted] after [event]." \
  "Macro sensitivity [changed] as [mechanism] — the stock now [...]." \
  "The operating story is unchanged — the repricing came from [rates/sentiment/multiple]." \
If evidence is genuinely sparse: "Insufficient recent evidence to characterise a thesis evolution." \
FORBIDDEN: Generic statements ("the market has been volatile", "conditions have changed").
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
"Overall, the investment thesis is balanced with risks and opportunities on both sides."

CATALYST CALENDAR REQUIREMENT (Part 5 — MANDATORY when applicable):
  "catalyst_calendar" field MUST be populated when:
    (a) directional_stance is "Tactical", OR
    (b) Evidence references an upcoming earnings print, guidance event, regulatory decision,
        product launch, or macro release within 60 days.
  If no near-term catalyst exists, set catalyst_calendar to null.

  When populated, catalyst_calendar must be a JSON object with these fields:
    "primary_catalyst"      : string — the single most important near-term event
    "catalyst_type"         : "earnings" | "macro_event" | "product_launch" |
                              "regulatory_decision" | "guidance_event" | "management_event" | "none"
    "event_window"          : string — specific timing window (e.g. "2-3 weeks", "next 4-6 weeks")
    "asymmetry_window"      : string — upside/downside asymmetry before the event
    "what_resolves_the_debate" : string — what specific data from the event confirms or denies thesis
    "time_horizon"          : "tactical" | "intermediate" | "structural"
    "time_horizon_rationale": string — why this time horizon was assigned

  GOOD catalyst_calendar: {
    "primary_catalyst": "Q2 earnings call — gross margin guidance is the key variable",
    "catalyst_type": "earnings",
    "event_window": "Within 2-3 weeks",
    "asymmetry_window": "Setup skewed to downside at current multiples — guidance cut reprices ~12%",
    "what_resolves_the_debate": "Gross margin guidance above 72% confirms Services mix durability",
    "time_horizon": "tactical",
    "time_horizon_rationale": "Binary earnings event within 2 weeks makes this tactical"
  }
  BAD: Vague timing ("soon"), generic catalyst ("upcoming results"), no asymmetry framing.

SPRINT 1 INTELLIGENCE FIELDS (MANDATORY — do not omit):

  "why_not" : string — 4 sentences answering: "What would prove this analysis wrong?" \
This is NOT a repeat of bear_thesis. It is the single strongest counter-thesis that \
would invalidate the core bull assumption, with an explicit invalidation condition. \
\
STRUCTURE (follow this order, all 4 sentences required): \
  Sentence 1 → Name the core assumption the bull case depends on. \
    Format: "The bull case rests on the assumption that [specific assumption]." \
  Sentence 2 → State the alternative scenario that would prove that assumption false. \
    Format: "The counter-thesis: [what would have to be true / what evidence or event would \
    reveal the assumption is wrong]." \
  Sentence 3 → Name the leading indicator that would confirm the counter-thesis is materializing. \
    Format: "The tell: [specific metric, event, or data point] falling/rising to [threshold] \
    would signal the bull case has broken." \
  Sentence 4 → State the explicit invalidation condition — what data or event would flip the analysis. \
    Format: "This analysis would be wrong if [specific condition] — [consequence]." \
\
GOOD: "The bull case rests on the assumption that hyperscaler CapEx appetite remains structurally \
elevated and is not front-loaded demand. The counter-thesis: if hyperscaler guidance in Q3 signals \
even a one-quarter pause, Nvidia's data center revenue would likely miss the ~$40B run rate the \
multiple currently prices in. The tell: data center revenue growth decelerating below 15% YoY for \
two consecutive quarters would confirm front-loading, not durability. This analysis would be wrong \
if hyperscaler CapEx guidance accelerates above $200B for FY26 — that would validate structurally \
elevated demand and make the current multiple defensible." \
BAD: "There are risks to the bull thesis including competition and valuation." (That's a risk list.) \
BAD: Repeating what's already in bear_thesis. why_not must add a NEW analytical angle. \
BAD: Omitting sentence 4. All 4 sentences are required.

  "threshold_zones" : array of 2-3 objects, each with: \
    "metric"          : string — specific metric name (company-specific, not generic) \
    "bull_threshold"  : string — level above which the bull case is intact (e.g. ">25%", ">$40B") \
    "bear_threshold"  : string — level below which the thesis breaks (e.g. "<15%", "<3.5%") \
    "rationale"       : string — one sentence explaining why this zone matters for THIS thesis \
\
Rules for threshold_zones: \
  - Choose metrics that ACTUALLY drive this thesis, not generic ones. \
  - For growth companies: data center revenue growth, forward P/E, FCF yield. \
  - For macro-sensitive names: treasury yield, rate sensitivity metric. \
  - Always include at least one VALUATION metric and one FUNDAMENTAL metric. \
  - Bull/bear thresholds should be ASYMMETRIC when the thesis is asymmetric. \
\
GOOD example zone: \
  { "metric": "Data Center Revenue Growth YoY", \
    "bull_threshold": ">25%", \
    "bear_threshold": "<15%", \
    "rationale": "Growth above 25% validates hyperscaler CapEx is structural; below 15% signals front-loading." } \
\
BAD: { "metric": "Revenue", "bull_threshold": "up", "bear_threshold": "down" } — not specific enough. """


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
    pre_synthesized_answer: Optional[str] = None,
) -> str:
    # Plain-text agent summaries with question-aware sub-field injection (Phase 2 Lever 2).
    # For each question_intent, the most analytically relevant sub-field from the
    # corresponding agent is appended alongside .overall so the synthesis LLM sees
    # the depth content produced by Phase 1 emphasis blocks (moat, rate_sensitivity,
    # competitive_risk, etc.) rather than only the summary sentence.
    agent_summaries = _build_agent_summaries(
        valuation, macro, risk, market, quality, question_intent=question_intent
    )

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

    # Optional company business model section + archetype hint
    if profile is not None:
        # Compute business durability and derive setup archetype.
        # Inferred from profile + agent signals — NO ticker identity.
        _dur = _compute_business_durability(quality, risk, evidence, profile)
        if _dur >= _ARCHETYPE_DURABLE_THRESHOLD:
            _archetype_label = "durable_compounder"
            _archetype_hint = (
                "SETUP ARCHETYPE: durable_compounder — recurring economics, moat-driven, "
                "recession-resilient. Premium valuation reflects quality premium, NOT narrative "
                "dependency. Conclusion vocabulary: 'priced for continued execution', "
                "'expectation-sensitive at current levels', 'valuation already prices in the moat'."
            )
        elif _dur >= _ARCHETYPE_QUALITY_THRESHOLD:
            _archetype_label = "expectation_sensitive_quality"
            _archetype_hint = (
                "SETUP ARCHETYPE: expectation_sensitive_quality — high-quality but cyclical "
                "or growth-rate dependent. Conclusion vocabulary: 'demanding setup', "
                "'limited room for misses', 'acceleration priced in, not continuation'."
            )
        else:
            _archetype_label = "narrative_fragile"
            _archetype_hint = (
                "SETUP ARCHETYPE: narrative_fragile — execution binary, expectation-heavy, "
                "narrative-dependent valuation. Conclusion vocabulary: 'speculative at current "
                "multiples', 'binary on [X]', 'execution dependency too concentrated'."
            )
        biz_model_section = (
            f"COMPANY BUSINESS MODEL (ground every claim in this):\n"
            f"Business model: {profile.business_model}\n"
            f"Primary revenue drivers: {', '.join(profile.primary_revenue_drivers)}\n"
            f"Recurring revenue: {', '.join(profile.recurring_revenue_sources)}\n"
            f"Valuation style: {profile.valuation_style}\n"
            f"Key metrics: {', '.join(profile.key_metrics)}\n"
            f"Competitive advantages: {'; '.join(profile.competitive_advantages)}\n"
            f"Rate sensitivity: {profile.rate_sensitivity_note}\n"
            f"\n{_archetype_hint}\n"
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
    dominant_dim = _detect_dominant_dimension(macro, risk, valuation, ranked)

    # Phase 2 Lever 1: override keyword-scored dominant_dim with question_intent when
    # present.  The user's explicit question is a stronger analytical signal than
    # keyword frequency in agent output text.  Uses module-level _INTENT_TO_DOMINANT_DIM.
    if question_intent in _INTENT_TO_DOMINANT_DIM:
        dominant_dim = _INTENT_TO_DOMINANT_DIM[question_intent]

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
    elif original_user_question and question_intent == "competitive_position":
        # Phase 2 Lever 4: section-level mandates for competitive/moat questions.
        # Extends beyond direct_answer to anchor bull_thesis, bear_thesis,
        # core_debate, and valuation_view on competitive mechanics.
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"SECTION MANDATES — COMPETITIVE / MOAT QUESTION:\n"
            f"direct_answer (2 sentences REQUIRED):\n"
            f"  Sentence 1 — Name {ticker}'s primary moat source and whether it is "
            f"strengthening or weakening vs the named competitor or threat.\n"
            f"  Sentence 2 — Name the single biggest competitive risk: specific "
            f"competitor, specific product/workload at risk, specific market-share estimate.\n"
            f"  FORBIDDEN: Opening with generic company description.\n"
            f"bull_thesis — COMPETITIVE ANCHOR REQUIRED:\n"
            f"  MUST lead with moat mechanics — switching costs, ecosystem lock-in, "
            f"network effects, or IP. Name the SPECIFIC structural advantage and why it "
            f"compounds. MUST NOT open with valuation or rate discussion.\n"
            f"bear_thesis — COMPETITIVE ANCHOR REQUIRED:\n"
            f"  MUST anchor on moat erosion or competitive displacement. Name the competitor, "
            f"the specific product/workload segment at risk, the market-share estimate at "
            f"stake, and ONE second-order effect if the moat erodes.\n"
            f"core_debate — COMPETITIVE FRAMING REQUIRED:\n"
            f'  Write as an open competitive question, e.g.: '
            f'"Can {ticker}\'s [primary product] hold market share against [competitor] '
            f'as [competitive threat] accelerates?"\n'
            f"valuation_view — MOAT-LINKED SENTENCE:\n"
            f'  One sentence: "At ~[X]x forward [metric], the market is pricing in '
            f'[moat-holds / moat-erodes scenario]."\n\n'
        )
    elif original_user_question and question_intent == "macro_sensitivity":
        # Phase 2 Lever 4: section-level mandates for macro/rate questions.
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"SECTION MANDATES — MACRO / RATE QUESTION:\n"
            f"direct_answer (2 sentences REQUIRED):\n"
            f"  Sentence 1 — State the PRIMARY transmission channel: "
            f"[rate/macro move] → [specific mechanism] → [specific P&L or multiple impact] "
            f"for {ticker}. Quantify direction and magnitude.\n"
            f"  Sentence 2 — Name {ticker}'s most important offset or insulation: "
            f"recurring revenue, rate-insensitive earnings, balance sheet, pricing power.\n"
            f"macro_sensitivity — DEEPEST SECTION FOR THIS QUESTION:\n"
            f"  3+ sentences REQUIRED. Lead with the transmission mechanism name, "
            f"quantify magnitude, then second-order effect specific to {ticker}.\n"
            f"  FORBIDDEN: 'Rates affect growth stocks' — must trace through {ticker}'s "
            f"specific revenue structure.\n"
            f"bull_thesis — MACRO OFFSET REQUIRED:\n"
            f"  MUST include the macro offset or insulation mechanism — why is {ticker} "
            f"partially protected from the scenario asked about?\n"
            f"bear_thesis — MACRO TRANSMISSION REQUIRED:\n"
            f"  MUST anchor on the specific macro transmission channel in the question "
            f"(rate rise / cut / recession / inflation) traced to a specific {ticker} "
            f"P&L line or multiple compression pathway.\n"
            f"core_debate — MACRO FRAMING REQUIRED:\n"
            f'  Write as an open macro question, e.g.: '
            f'"Can {ticker}\'s earnings durability offset [specific macro headwind] '
            f'if [scenario] persists longer than consensus expects?"\n'
            f"valuation_view — MACRO-MULTIPLE LINK:\n"
            f"  One sentence: how does the current macro regime affect the multiple — "
            f"compression or expansion, and under what scenario does it inflect?\n\n"
        )
    elif original_user_question and question_intent == "risk_assessment":
        # Phase 2 Lever 4: section-level mandates for risk questions.
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"SECTION MANDATES — RISK QUESTION:\n"
            f"direct_answer (2 sentences REQUIRED):\n"
            f"  Sentence 1 — Name {ticker}'s #1 risk: the specific mechanism, who it "
            f"comes from, and what P&L line or structural position it threatens.\n"
            f"  Sentence 2 — State the trigger that would confirm the risk is materializing.\n"
            f"bear_thesis — MOST ANALYTICALLY SUBSTANTIVE SECTION FOR THIS QUESTION:\n"
            f"  MUST enumerate 2 distinct risks: (1) primary — named mechanism + revenue "
            f"at risk + trigger; (2) secondary — the compounding effect when primary "
            f"risk materializes.\n"
            f"  MUST NOT open with 'The biggest risk is…' — lead with the mechanism.\n"
            f"bull_thesis — RISK MITIGATION REQUIRED:\n"
            f"  MUST address what has to happen for each named risk to NOT materialize — "
            f"probability-weighted upside if risks resolve.\n"
            f"key_risks — EXHAUSTIVE REQUIRED:\n"
            f"  Include mechanism, revenue at risk, and trigger for each entry.\n"
            f"core_debate — RISK TRADE-OFF FRAMING:\n"
            f'  Write as a risk trade-off question, e.g.: '
            f'"Does {ticker}\'s [primary risk] now outweigh its [primary upside]?"\n'
            f"what_changes_the_thesis — RISK-RESOLUTION EVENTS PRIORITIZED:\n"
            f"  Name the specific data points that would confirm or deny the primary risk.\n\n"
        )
    # ── Phase 4: six new specific-answer intents ─────────────────────────────
    elif original_user_question and question_intent == "implied_growth_rate":
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"SECTION MANDATES — IMPLIED GROWTH RATE QUESTION:\n"
            f"direct_answer (4 sentences REQUIRED):\n"
            f"  Sentence 1 — State {ticker}'s current forward P/E or EV/Revenue multiple "
            f"and the implied compound revenue or EPS CAGR that multiple requires over 3–5 years "
            f"(assume 10% discount rate if unspecified). Quantify: '~[X]x forward P/E implies "
            f"~[Y]% compound growth over [N] years.'\n"
            f"  Sentence 2 — State the current analyst consensus growth estimate and whether "
            f"it meets, exceeds, or falls short of the implied rate.\n"
            f"  Sentence 3 — Name 1–2 historical analogs (company, period, multiple entry point, "
            f"growth outcome) — did those companies sustain the implied rate?\n"
            f"  Sentence 4 — State whether the implied growth rate is achievable, stretched, or "
            f"requires execution perfection, and what single data point would confirm or deny it.\n"
            f"  FORBIDDEN: Opening with generic company description.\n"
            f"  FORBIDDEN: Answering with 'the market believes growth is strong.'\n"
            f"valuation_view — GROWTH-RATE ANCHOR REQUIRED:\n"
            f"  Lead with the specific multiple and the implied growth rate.\n"
            f"  MANDATORY: Use 'at ~[X]x, the market is paying for [Y]% compound growth' language.\n\n"
        )
    elif original_user_question and question_intent == "timing_lag":
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"SECTION MANDATES — TIMING LAG QUESTION:\n"
            f"direct_answer (4 sentences REQUIRED):\n"
            f"  Sentence 1 — State the typical lag in quarters between the upstream decision "
            f"(capex cut / order cancellation / policy change) and the downstream revenue "
            f"impact on {ticker}. Give a specific range: 'typically [X]–[Y] quarters.'\n"
            f"  Sentence 2 — Explain the causal chain with specific mechanism: "
            f"[upstream decision] → [order book / backlog / contract stage] → "
            f"[{ticker} revenue line affected]. Name the specific revenue segment.\n"
            f"  Sentence 3 — Quantify the magnitude: what % of {ticker}'s revenue is "
            f"exposed to this lag pathway at current run-rates?\n"
            f"  Sentence 4 — Name the leading indicator {ticker} discloses or management "
            f"cites that provides earliest visibility into the lag materializing.\n"
            f"  FORBIDDEN: Vague timing ('several quarters', 'some time').\n"
            f"  FORBIDDEN: Omitting the specific revenue segment name.\n"
            f"macro_sensitivity — DEEPEST SECTION FOR THIS QUESTION:\n"
            f"  Lead with the causal chain. State the lag range explicitly.\n"
            f"  Name the leading indicator and where it is disclosed (earnings call / 10-Q).\n\n"
        )
    elif original_user_question and question_intent == "quantitative_threshold":
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"SECTION MANDATES — QUANTITATIVE THRESHOLD QUESTION:\n"
            f"direct_answer (4 sentences REQUIRED):\n"
            f"  Sentence 1 — State the specific financial exposure from evidence "
            f"(e.g. '$17B commercial real estate office exposure' or "
            f"'Data Center represents ~55% of revenue'). Name the dollar amount or %.\n"
            f"  Sentence 2 — State the threshold: 'At a [X]% loss / decline rate, "
            f"EPS would be impacted by approximately [Y]%. Compute from evidence data.\n"
            f"  Sentence 3 — Compare to historical precedent: what loss / decline rate "
            f"occurred in the most comparable stress period, and what was the actual impact?\n"
            f"  Sentence 4 — State the probability scenario and the single trigger that "
            f"would confirm the threshold is being approached.\n"
            f"  FORBIDDEN: Refusing to quantify ('the impact would depend on many factors').\n"
            f"  FORBIDDEN: Answering with multiple / thesis discussion instead of the threshold.\n"
            f"bear_thesis — THRESHOLD MECHANICS REQUIRED:\n"
            f"  MUST anchor on the quantified threshold — name the exposure size, "
            f"the loss rate that matters, and the resulting EPS/ROE impact.\n"
            f"key_risks — QUANTIFIED REQUIRED:\n"
            f"  Each risk entry must include the exposure size and the threshold that triggers impact.\n\n"
        )
    elif original_user_question and question_intent == "metric_ordering":
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"SECTION MANDATES — METRIC ORDERING QUESTION:\n"
            f"direct_answer (4 sentences REQUIRED):\n"
            f"  Sentence 1 — Name the metric that deteriorates FIRST and state the "
            f"causal mechanism: why does this metric lead the others in a downturn? "
            f"Be specific to {ticker}'s business model (e.g. 'comparable store sales "
            f"leads because they are reported monthly with no smoothing').\n"
            f"  Sentence 2 — Name the metric that deteriorates SECOND and explain the "
            f"causal link to the first (why does it follow, with what lag).\n"
            f"  Sentence 3 — Name the metric that is most RECESSION-RESISTANT and "
            f"explain the structural reason (contract length, membership model, etc.).\n"
            f"  Sentence 4 — State the one metric an investor should watch weekly/monthly "
            f"as the earliest recession signal for {ticker}.\n"
            f"  FORBIDDEN: Listing metrics without causal ordering ('all metrics would decline').\n"
            f"  FORBIDDEN: Generic macro discussion without {ticker}-specific mechanism.\n"
            f"macro_sensitivity — METRIC-CHAIN REQUIRED:\n"
            f"  Lead with the specific metric ordering. Name ALL metrics the question asks "
            f"about and rank them explicitly.\n"
            f"bear_thesis — DETERIORATION SEQUENCE REQUIRED:\n"
            f"  Walk through the deterioration sequence in causal order.\n\n"
        )
    elif original_user_question and question_intent == "segment_ranking":
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"SECTION MANDATES — SEGMENT RANKING QUESTION:\n"
            f"direct_answer (4 sentences REQUIRED):\n"
            f"  Sentence 1 — State the ranking explicitly: '#1: [segment] because "
            f"[primary moat source]. #2: [segment] because [reason]. #3: [segment] "
            f"because [reason].' Name ALL segments from the question.\n"
            f"  Sentence 2 — Explain the #1 segment's moat in structural terms: "
            f"switching costs, network effects, regulatory protection, IP, or "
            f"distribution advantage. Quantify the margin or retention rate.\n"
            f"  Sentence 3 — Explain the most vulnerable segment's Achilles heel — "
            f"what specific threat could displace it or compress its margin.\n"
            f"  Sentence 4 — Name the ONE metric that could change the ranking if it "
            f"materially shifts (e.g. 'if cloud renewal rates drop below 90%, "
            f"Intelligent Cloud falls to #3').\n"
            f"  FORBIDDEN: 'All segments have strong moats.'\n"
            f"  FORBIDDEN: Omitting any segment named in the question.\n"
            f"bull_thesis — SEGMENT MOAT ANCHOR REQUIRED:\n"
            f"  Lead with the #1 segment moat and why it compounds over time.\n"
            f"bear_thesis — WEAKEST SEGMENT ANCHOR REQUIRED:\n"
            f"  Lead with the weakest segment's structural vulnerability.\n\n"
        )
    elif original_user_question and question_intent == "historical_precedent":
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"SECTION MANDATES — HISTORICAL PRECEDENT QUESTION:\n"
            f"direct_answer (4 sentences REQUIRED):\n"
            f"  Sentence 1 — Name the best historical analog: company, time period, "
            f"the relevant metric trajectory (e.g. 'Cisco 1999–2001: 50x revenue "
            f"multiple, then demand pulled forward reversed sharply').\n"
            f"  Sentence 2 — State the key SIMILARITY between the historical case and "
            f"{ticker}'s current situation — what makes this a valid analog?\n"
            f"  Sentence 3 — State the key DIFFERENCE — what structural factor makes "
            f"{ticker}'s situation more or less favorable than the historical case?\n"
            f"  Sentence 4 — State the implication: if the analog holds, what happens "
            f"to {ticker}'s multiple or growth trajectory over the relevant period?\n"
            f"  FORBIDDEN: 'There is no direct historical precedent.'\n"
            f"  FORBIDDEN: Vague analogies without naming a specific company and period.\n"
            f"valuation_view — HISTORICAL MULTIPLE COMPARISON REQUIRED:\n"
            f"  Compare current multiple to the historical analog's entry multiple.\n"
            f"  State whether current entry is more/less attractive than the analog.\n\n"
        )
    # ── End Phase 4 ───────────────────────────────────────────────────────────

    elif original_user_question and question_intent in ("investment_thesis", "business_model"):
        # Phase 3 Lever 4: first-class anchor for business model / full-thesis questions.
        # Previously this fell through to the generic block below, giving no section-specific
        # mandates. Now directs bull/bear/core_debate to anchor on business model mechanics.
        question_anchor_block = (
            f'USER\'S EXACT QUESTION: "{original_user_question}"\n\n'
            f"SECTION MANDATES — BUSINESS MODEL / INVESTMENT THESIS QUESTION:\n"
            f"direct_answer (2 sentences REQUIRED):\n"
            f"  Sentence 1 — State whether {ticker}'s primary business model driver "
            f"is sustainable under the scenario asked about. Be specific about the mechanism "
            f"(revenue engine, unit economics, or operating leverage).\n"
            f"  Sentence 2 — Name the single most important operating metric to watch "
            f"for confirming or denying the thesis (ARR growth, gross margin, FCF conversion, "
            f"seat/unit growth rate).\n"
            f"bull_thesis — BUSINESS MODEL ANCHOR REQUIRED:\n"
            f"  MUST anchor on business model durability — recurring revenue compounding, "
            f"operating leverage trajectory, unit economics, or pricing power. "
            f"Lead with the SPECIFIC mechanism that makes the thesis self-reinforcing. "
            f"MUST NOT open with a macro or competitive discussion.\n"
            f"bear_thesis — EXECUTION RISK REQUIRED:\n"
            f"  MUST anchor on execution or model risk — what breaks the recurring revenue "
            f"trajectory, what compresses operating leverage, or what degrades unit economics. "
            f"Name the specific operating metric that would crack first.\n"
            f"core_debate — BUSINESS MODEL FRAMING REQUIRED:\n"
            f'  Frame as: "Is {ticker}\'s [primary growth driver] durable enough to '
            f'[sustain/justify] [the current earnings expectation or valuation multiple]?"\n\n'
        )
    elif original_user_question:
        # Generic anchor for other unrecognized intents — mandates direct_answer only.
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

    # Phase 4 (Option B): if a pre_synthesized_answer was produced by the Q-First
    # question_answerer_agent, append a directive to the question_anchor_block
    # instructing the synthesis LLM to use it verbatim for the direct_answer field.
    # The thesis sections (bull, bear, conclusion) are instructed to build around it
    # rather than to produce their own independent direct_answer from scratch.
    if pre_synthesized_answer:
        _qa_inject = (
            f"\n\nPRE-SYNTHESIZED DIRECT ANSWER (Phase 4 Q-First — MANDATORY):\n"
            f"The following direct answer was produced by a dedicated question-answering "
            f"agent before this synthesis call. It uses the company knowledge profile and "
            f"retrieved evidence to produce a specific, quantified answer.\n\n"
            f"  direct_answer = \"\"\"\n{pre_synthesized_answer}\n\"\"\"\n\n"
            f"INSTRUCTIONS FOR THIS SYNTHESIS:\n"
            f"1. Use the pre-synthesized direct_answer above VERBATIM in the "
            f"\"direct_answer\" JSON field — do NOT rewrite, summarize, or replace it.\n"
            f"2. Build your bull_thesis, bear_thesis, and conclusion to ELABORATE and "
            f"SUPPORT the direct answer above — not to contradict or ignore it.\n"
            f"3. The direct_answer field in your JSON output MUST match the pre-synthesized "
            f"answer above exactly (character-for-character). It will be overwritten "
            f"post-synthesis in any case, but matching it signals you read it.\n"
        )
        question_anchor_block = question_anchor_block + _qa_inject

    # Phase 3: build secondary section mandates for the 4 convergence-prone sections.
    # Injected after question_anchor_block so both primary and secondary mandates are
    # contiguous in the "instruction" region of the prompt.
    secondary_mandates_block = _build_secondary_section_mandates(ticker, question_intent)

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
{market_regime_block}{recent_events_block}{narrative_state_block}{core_debate_mandate_block}{expectation_delta_block}{historical_reasoning_block}{question_anchor_block}{secondary_mandates_block}{ranked_signals_section}
SPECIALIST AGENT OUTPUTS:
{agent_summaries}

Key Risks Identified:
{key_risks_txt}

Recent Catalysts:
{catalysts_txt}

SUPPORTING EVIDENCE:
{ev_block}

{live_data_provenance_block}SECTION CONTRACT — EACH SECTION HAS ONE JOB AND MUST NOT POACH FROM OTHERS:

  direct_answer     → ONLY answers the user's exact question. 2–4 sentences.
                      For Phase 4 intents (implied_growth_rate, timing_lag,
                      quantitative_threshold, metric_ordering, segment_ranking,
                      historical_precedent): follow the 4-sentence format exactly
                      as specified in the question anchor block above.
                      Does NOT summarise the business, repeat the conclusion, or
                      discuss the market debate.

  one_sentence_thesis → Single positioning statement. Does NOT preview the bull/bear.

  core_market_debate → The ONE live investor disagreement question. Phrased as a question.
                       Does NOT describe the business model or restate the thesis.

  bull_thesis        → WHY the thesis works economically. Mechanism + operating leverage.
                       Does NOT repeat the valuation multiple or macro rate context
                       already covered in valuation_view/macro_sensitivity.

  bear_thesis        → HOW the thesis breaks. Specific compounding failure path.
                       Does NOT repeat risk factors already named in bull_thesis.

  valuation_view     → What expectations are already PRICED IN at the current multiple.
                       2 sentences. Does NOT opine on business quality (that is bull_thesis).
                       Does NOT discuss interest rates (that is macro_sensitivity).

  macro_sensitivity  → HOW macro variables (rates, FX, cycle) alter the thesis mechanics.
                       2 sentences. Does NOT repeat the P/E ratio or valuation stance
                       already stated in valuation_view.

  conclusion         → Final PM-grade positioning verdict. 2 sentences HARD CAP.
                       Does NOT restate the bull/bear case or summarise earlier sections.
                       Opens with positioning stance — not with a mechanism description.

NON-REPETITION RULE — STRICTLY ENFORCED:
- A phrase appearing verbatim in one section MUST NOT appear in any other section.
- A mechanism described in one section need only be named (not re-explained) elsewhere.
- "membership fee growth", "renewal rates", "multiple compression", "rate sensitivity"
  should appear in AT MOST ONE section each — the section where they are the primary driver.
- If a concept was fully explained in bull_thesis, later sections may reference it in
  one clause ("membership fee renewals already addressed above" is acceptable) but
  MUST NOT re-explain the mechanism.

STOCK-MOVEMENT ORIENTATION — MANDATORY FOR ALL SECTIONS:
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
  GOOD: "{ticker}'s net-cash balance and [company-specific] annual capital return
sustain EPS even as [primary segment] revenue faces credit-cycle headwinds."
  NOTE: Never copy dollar amounts from these examples. All figures must come
  from the evidence items or the company business model context above.

  BAD: "This indicates positive momentum going forward."
  GOOD: "The acceleration in [company-specific product/segment] attach rates since
[specific recent event] signals upsell runway that sell-side estimates have not yet captured."

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

CROSS-COMPANY CONTAMINATION PREVENTION — ABSOLUTE RULES:
The synthesis prompt contains example sentences drawn from AAPL analysis.
These examples illustrate STYLE AND STRUCTURE — the dollar amounts are APPLE'S,
not {ticker}'s.  You MUST NOT copy any figure from these examples into your output.
Specifically:
- "$90B buyback" → this is Apple's buyback.  Do NOT use for {ticker}.
- "$165B net-cash" → this is Apple's gross cash.  Do NOT use for {ticker}.
- "$100B ARR" → this is Apple's Services ARR.  Do NOT use for {ticker}.
- "72% gross margin" → this is Apple's Services margin.  Do NOT use for {ticker}.
- "iOS 17", "Services", "iPhone", "App Store" → Apple products.  Do NOT use for {ticker}.
If {ticker} has a buyback, its SIZE must come from the evidence items above.
If no buyback is mentioned in the evidence, do NOT assert one exists.
Violation of this rule causes a hallucination alert and disqualifies the thesis.

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
- "stabilizes valuation" → WHAT stabilizes it? (e.g. "[company-specific] buyback
  compresses share count, sustaining EPS at zero revenue growth — use the ACTUAL
  company's buyback figure from evidence, never copy example dollar amounts")
- "cushions downside" → WHAT is the cushion mechanism? (e.g. "net cash of [X]B
  covers N months of buyback even if FCF halves — cite the ACTUAL company's cash
  position from evidence, do not invent or copy figures from other companies")
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
   effect that makes the bull case self-reinforcing (e.g. "[company's actual buyback or
   capital return mechanism] amplifies EPS even at zero revenue growth — cite the company's
   ACTUAL capital return amount from evidence; do not invent or copy figures from other
   companies").
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
   [company's actual buyback] ROI deteriorates relative to debt service costs, blunting
   EPS support at exactly the point multiple compression requires it — use the company's
   ACTUAL capital return figure from evidence, not a figure from another company").
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
11. conclusion: 2 sentences HARD CAP. POSITIONING-FIRST — not mechanism-first.
    Sentence 1: State the bottom-line setup view (what is priced in, whether it is defensible).
    Sentence 2: Name the specific fulcrum — the condition that would change the view.
    FORBIDDEN: "The thesis requires...", "The company remains...", "The business has...",
    restating the bull/bear cases, mechanism-before-verdict structure.
    REQUIRED: The reader knows the positioning verdict within the first 10 words.
    APPROVED: "[Business] remains [quality], but the market already prices in [X]."
              "At ~[X]x, the setup assumes [Y]; the risk is whether [Z] holds."

12. thesis_evolution: 2-3 sentences — "What Changed?" narrative (Part 2 — MANDATORY).
    This is the most time-sensitive section. A PM returning after 2 weeks needs to read
    this first to understand what has shifted.
    Synthesize from the evidence what has RECENTLY CHANGED in the investment story:
    - Expectation revisions: have estimates moved higher or lower, and why?
    - Debate evolution: has the primary uncertainty narrowed, intensified, or shifted topic?
    - Acceleration/deceleration: is the primary driver moving faster or slower than before?
    - Management tone: did recent commentary signal more caution or more confidence?
    - Multiple re-rating: has the market repriced the stock without a fundamental change?
    - Macro regime shift: has a change in rates/FX/credit altered the sensitivity?
    REQUIRED patterns (use the most applicable):
      "The debate shifted from [X] toward [Y] — [what drove the shift]."
      "Consensus expectations [expanded/contracted] materially after [event]."
      "Macro sensitivity [increased/declined] as [mechanism] — the stock now [...]."
      "Management tone shifted [more cautious/more optimistic] — [specific language]."
      "The operating story is unchanged — the repricing came from [rates/sentiment], not fundamentals."
    FORBIDDEN: Generic statements ("the market has been volatile", "conditions changed").
    If evidence is too sparse to detect a meaningful shift, write:
      "Insufficient recent evidence to characterise a thesis evolution."
    DO NOT default to this fallback unless evidence is genuinely sparse — real analysis preferred.

SIGNAL DIVERSITY REQUIREMENTS (Part 3 — MANDATORY):
key_drivers and key_risks MUST draw from diverse signal categories. FORBIDDEN to use the
same concept type in more than 2 of the 4 drivers OR more than 2 of the 4 risks.

REQUIRED signal category spread — at least 3 different categories across key_drivers:
  - pricing power / ASP discipline (how the company protects or grows unit economics)
  - operating leverage (fixed-cost absorption as revenue scales)
  - capital allocation (buybacks, M&A, capex efficiency, dividend capacity)
  - geographic expansion (international revenue mix shift and FX exposure)
  - balance sheet optionality (net cash, debt refinancing, acquisition capacity)
  - duration sensitivity (rate sensitivity on long-dated FCF multiples)
  - margin structure (gross margin mix shift, COGS leverage, SG&A efficiency)
  - inventory efficiency (channel inventory health, working capital cycle)
  - customer behaviour (churn, attach rates, NPS, switching costs in action)
  - competitive re-rating (share gain/loss, moat erosion signals, new entrants)
  - regulatory tailwind/headwind (specific rule changes affecting unit economics)
  - execution cadence (quarter-over-quarter delivery vs street model)

CROSS-SIGNAL INTERACTION — MANDATORY for bear_thesis:
Name at least ONE cross-signal compound risk where two factors interact:
  "higher rates + lean inventory + membership cash flow = muted macro sensitivity"
  "rate re-acceleration + hardware cycle + high multiple = three-way compression"
  "margin expansion + buyback + rate cuts = layered EPS support even at flat revenue"
The compound interaction should appear as one sentence in bear_thesis or bull_thesis.

SIGNAL REPETITION — FORBIDDEN:
Do NOT use more than one of these per entire thesis output:
  - "renewal rates" / "membership fee growth" / "membership renewal"
  - "multiple compression" / "valuation compression" / "P/E compression"
  - "rate sensitivity" / "rate pressure" / "interest rate headwind"
These may appear in EXACTLY ONE section each. If the concept is already in bull_thesis,
it may not reappear in valuation_view, macro_sensitivity, or conclusion.

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
    pre_synthesized_answer: Optional[str] = None,
) -> InvestmentThesis:
    """Synthesise agent outputs into an InvestmentThesis.

    Runs the LLM synthesis with strict JSON-only enforcement, then applies
    deterministic Phase 4 governance checks and Phase 5 depth enforcement.
    Degrades gracefully if the LLM call fails.

    Parameters
    ----------
    company                : Normalised company identity.
    valuation              : Output from run_valuation_agent().
    macro                  : Output from run_macro_agent().
    risk                   : Output from run_risk_agent().
    market                 : Output from run_market_agent().
    quality                : Output from run_quality_agent().
    evidence               : Full evidence list (all agents' inputs combined).
    request_id             : Optional trace ID forwarded to model client.
    profile                : Optional CompanyKnowledgeProfile; enables richer prompting
                             and depth-guard checks when supplied.
    original_user_question : The user's verbatim question. When supplied the synthesiser
                             produces a ``direct_answer`` field that specifically addresses
                             the question before the broader thesis.
    pre_synthesized_answer : Optional direct_answer pre-generated by the Q-First
                             question_answerer_agent (Phase 4 / Option B).
                             When set and non-empty, it is (a) injected into the
                             synthesis prompt so the thesis is built around it, and
                             (b) used to overwrite thesis.direct_answer post-synthesis,
                             ensuring the Q-First answer is not overwritten by the
                             synthesis LLM.

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

    # Log agent confidence signals for diagnostics.
    agent_confidences = [
        valuation.confidence, macro.confidence,
        risk.confidence, market.confidence, quality.confidence,
    ]
    all_agents_empty  = all(c == 0.0 for c in agent_confidences)
    no_evidence       = not evidence

    if all_agents_empty and no_evidence:
        # All agents returned zero confidence AND no evidence was retrieved.
        # This typically means external data providers are unavailable (no API
        # keys / network error).  Rather than silently returning "Analysis
        # incomplete", attempt the LLM synthesis anyway — the model has strong
        # training knowledge for well-known companies (TSLA, AAPL, etc.) and
        # can still produce a useful thesis from the question + company context
        # even without retrieved evidence.
        #
        # We only hard-bail when the company object carries no identifiable
        # ticker/name, which would leave the synthesiser with nothing to reason
        # about.
        ticker_known = bool(getattr(company, "ticker", None))
        name_known   = bool(getattr(company, "company_name", None))
        if not ticker_known and not name_known:
            print(
                f"[thesis_synthesizer] all agents empty + no evidence + "
                f"unknown company — skipping LLM call"
            )
            return _empty_thesis(company, "No agent outputs or evidence available.")

        print(
            f"[thesis_synthesizer] WARNING: all agents empty + no evidence for "
            f"{company.ticker} — attempting LLM synthesis from model knowledge "
            f"(external data providers may be unavailable)"
        )

    # ── Phase 3: Signal ranking (pre-synthesis) ───────────────────────────────
    # Run before the LLM call so ranked signals can be injected into the prompt.
    try:
        ranked = rank_signals(
            valuation, macro, risk, market, quality,
            company=company, profile=profile,
        )
        # Phase 2 Lever 3: reweight top_signals by question_intent so the hard
        # MUST-address mandate in the synthesis prompt points at question-relevant
        # signal types rather than always the highest composite-importance signals.
        if question_intent and ranked is not None:
            ranked = reweight_signals_for_intent(ranked, question_intent)
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
        pre_synthesized_answer=pre_synthesized_answer,
    )

    # ── JSON-enforced LLM call with markdown recovery ─────────────────────────
    # Timer starts here so the compound-risk retry can measure how much of the
    # Render 61 s ceiling the synthesis call has already consumed.
    _synthesis_call_start: float = _time.monotonic()
    # Use synthesis_max_retries (default: 1) instead of model_max_retries (3).
    # A synthesis retry adds synthesis_timeout(35s) per attempt — on Render free
    # tier one retry alone pushes total pipeline past the 61s Nginx ceiling.
    # synthesis_max_retries=1 means: one attempt, no retry on timeout.
    _synthesis_max_retries = getattr(settings, "synthesis_max_retries", 1)
    thesis = _call_with_json_enforcement(
        prompt=prompt,
        ticker=company.ticker,
        max_retries=_synthesis_max_retries,
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

    # Guard: conclusion must never be empty after a successful synthesis.
    # An empty conclusion is confusing to users and breaks frontend rendering.
    # Construct a minimal positioning-first fallback from existing thesis content
    # without making an additional LLM call.
    if not getattr(thesis, "conclusion", ""):
        _bull = (getattr(thesis, "bull_thesis", "") or "")[:120].rstrip(".").strip()
        _bear = (getattr(thesis, "bear_thesis", "") or "")[:80].rstrip(".").strip()
        _conf = getattr(thesis, "confidence_score", 0.5) or 0.5
        if _conf >= 0.65:
            _setup = "a constructive"
        elif _conf >= 0.45:
            _setup = "a mixed"
        else:
            _setup = "a cautious"
        thesis.conclusion = (
            f"{company.ticker} presents {_setup} setup at current levels. "
            f"Monitor execution against embedded expectations before adjusting exposure."
        )
        logger.warning(
            "[thesis_synthesizer] conclusion was empty after synthesis for %s — "
            "deterministic fallback applied.",
            company.ticker,
        )

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

    # ── Post-synthesis bullish extraction fallback ────────────────────────────
    # If top_signals is empty or all bearish after ranking, extract the most
    # positive sentence from the synthesis bull_thesis and prepend it.
    #
    # WHY HERE instead of agent level:
    # Individual agent overalls are risk-first by design — they enumerate risks
    # and only mention positives as hedges ("growth is robust, BUT competition…").
    # The keyword scorer could not find qualifying sentences in that prose even
    # after the scoring calibration in 6332000.  The synthesis stage distils
    # all bullish content into a cleanly positive-framed bull_thesis, which
    # reliably produces a qualifying sentence for every company.
    #
    # This fires AFTER conviction modeler inputs are assembled, so the extracted
    # signal is included in thesis.top_signals when the modeler runs below.
    try:
        _has_bullish_top = any(
            s.direction in ("bullish", "neutral") for s in (thesis.top_signals or [])
        )
        if not _has_bullish_top and thesis.bull_thesis:
            from ..investment_agents._signal_extraction import extract_min_bullish_signal
            _extracted = extract_min_bullish_signal(
                thesis.bull_thesis, company, "synthesis", "structural", profile
            )
            if _extracted:
                thesis.top_signals = _extracted + list(thesis.top_signals or [])
                print(
                    f"[DIAG] [thesis_synthesizer] post_synthesis_extraction fired "
                    f"ticker={company.ticker} — prepended bullish signal from bull_thesis"
                )
    except Exception as exc:
        logger.warning("[thesis_synthesizer] post_synthesis_extraction failed: %r", exc)

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

    # ── P3: Revenue-driver context injection when Check 5 fires ──────────────
    # When the depth guard reports that no primary revenue driver was mentioned,
    # inject a compact context line into thesis.conclusion so the output always
    # surfaces key segment data even if the LLM elided it from the main body.
    _depth_revenue_miss = any(
        "primary revenue" in w or "revenue drivers" in w
        for w in depth_warnings
    )
    if _depth_revenue_miss and profile is not None:
        try:
            thesis = inject_revenue_context(thesis, profile)
            logger.info(
                "[depth_guard] revenue_context injected into conclusion for %s",
                company.ticker,
            )
        except Exception as _di_exc:
            logger.warning(
                "[depth_guard] revenue_context injection failed (non-fatal): %r",
                _di_exc,
            )

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
            question_intent     = question_intent,
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

        # ── Expectation Intelligence (Part 3) ─────────────────────────────────
        thesis.expectation_regime         = conviction.expectation_regime
        thesis.expectation_shift_severity = conviction.expectation_shift_severity

        # ── Phase 6: Stamp runtime fingerprint ───────────────────────────────
        # Allows the frontend to verify the live backend is running matrix code.
        try:
            import hashlib as _hashlib, os as _os_rt, time as _time_rt
            from .conviction_modeler import (
                CONVICTION_SCHEMA_VERSION as _CSV,
                ARCHETYPE_MATRIX_ENABLED as _AME,
            )
            _cm_path = _os_rt.path.join(
                _os_rt.path.dirname(__file__), "conviction_modeler.py"
            )
            _checksum = "unavailable"
            if _os_rt.path.exists(_cm_path):
                with open(_cm_path, "rb") as _f:
                    _checksum = _hashlib.md5(_f.read()).hexdigest()[:12]
            from ..startup import _PROCESS_START_EPOCH
            import time as _t_rt
            _deploy_ts = _t_rt.strftime(
                "%Y-%m-%dT%H:%M:%SZ", _t_rt.gmtime(_PROCESS_START_EPOCH)
            )
            _git = (
                _os_rt.environ.get("RENDER_GIT_COMMIT", "")[:12]
                or _os_rt.environ.get("GIT_COMMIT", "")[:12]
                or "unknown"
            )
            thesis.runtime_version = {
                "matrix_loaded":                _AME,
                "matrix_version":               _CSV,
                "conviction_modeler_checksum":  _checksum,
                "deployment_timestamp":         _deploy_ts,
                "git_commit":                   _git,
            }
        except Exception as _rv_exc:
            logger.warning("[runtime_version_stamp] failed: %r", _rv_exc)
            thesis.runtime_version = {"matrix_loaded": False, "error": str(_rv_exc)}

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

    # ── Phase 4 (Option B): overwrite direct_answer with Q-First pre-synthesized answer ──
    # Applied AFTER polish_thesis so the polisher's 2-sentence truncation rule does
    # not trim the Q-First answer (which uses up to 4 sentences for specificity).
    # The synthesis LLM has already built its thesis sections around the pre-synthesized
    # answer (it was injected into the prompt via _qa_inject).  We overwrite here to
    # guarantee the verbatim Q-First answer is what the API returns.
    if pre_synthesized_answer:
        thesis.direct_answer = pre_synthesized_answer
        print(
            f"[thesis_synthesizer] direct_answer overwritten with Q-First answer "
            f"({len(pre_synthesized_answer)} chars) for {company.ticker} "
            f"(applied after polish)"
        )

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
    # Phase 6 matrix: "actionable thesis" IS the correct label for durable compounders
    # (COST, MSFT). Any present label + conviction dims = conviction modeler ran.
    # The old check `setup_label != "actionable thesis"` was wrong — it treated the
    # correct matrix output as an absence signal.
    _has_conviction_dims = bool(thesis.conviction_dimensions)
    if _has_conviction_dims:
        # Conviction modeler ran — use single canonical source name.
        # We no longer distinguish "balanced" vs "non-balanced" labels because
        # "actionable thesis" is now the correct authoritative label for many tickers.
        _score_source = "conviction_modeler"
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

    # ── Post-synthesis validation (Part 6) ────────────────────────────────────
    # Deterministic quality checks on the synthesized thesis.
    # Hard violations trigger a targeted single-field retry before falling back
    # to advisory-only warning mode.
    try:
        from .synthesis_validator import validate_thesis, summarize_validation
        _val_result = validate_thesis(thesis)
        if _val_result.has_violations:
            _val_summary = summarize_validation(_val_result)
            logger.info(
                "[synthesis_validator] ticker=%s %s",
                getattr(company, "ticker", "UNKNOWN"), _val_summary,
            )

            # ── P2: Targeted retry for MISSING_COMPOUND_RISK ──────────────────
            # bear_thesis is the only field that needs to change.  Build a
            # minimal focused prompt, regenerate just that field, validate the
            # patch, and swap bear_thesis only if the retry passes.
            #
            # Wall-clock budget guard: the retry makes one additional
            # model_client.call() which takes ~15-20 s.  On Render free tier
            # the Nginx proxy_read_timeout is ~61 s.  If the synthesis call +
            # post-processing has already consumed more than
            # _COMPOUND_RETRY_WALL_BUDGET_S seconds by the time we reach here,
            # skip the retry entirely — publishing the advisory warning is
            # better than a silent 504 gateway timeout for the user.
            _compound_viol = next(
                (v for v in _val_result.hard_violations
                 if v.check_id == "MISSING_COMPOUND_RISK"),
                None,
            )
            if _compound_viol is not None:
                _synthesis_elapsed: float = _time.monotonic() - _synthesis_call_start
                _retry_allowed: bool = _synthesis_elapsed <= _COMPOUND_RETRY_WALL_BUDGET_S
                if not _retry_allowed:
                    logger.info(
                        "[synthesis_validator] compound_risk retry SKIPPED for %s — "
                        "synthesis_elapsed=%.1fs exceeds wall budget %.1fs; "
                        "keeping original bear_thesis with advisory warning",
                        getattr(company, "ticker", "UNKNOWN"),
                        _synthesis_elapsed,
                        _COMPOUND_RETRY_WALL_BUDGET_S,
                    )
                    print(
                        f"[DIAG] compound_risk retry SKIPPED ticker={getattr(company, 'ticker', 'UNKNOWN')} "
                        f"elapsed={_synthesis_elapsed:.1f}s budget={_COMPOUND_RETRY_WALL_BUDGET_S}s"
                    )
            if _compound_viol is not None and _retry_allowed:
                try:
                    _bear_retry_prompt = (
                        f"You are a financial analyst writing the bear case for "
                        f"{company.ticker} ({company.company_name}).\n\n"
                        f"CURRENT BEAR THESIS (needs improvement):\n"
                        f"{thesis.bear_thesis}\n\n"
                        f"REQUIRED FIX: {_compound_viol.remediation_hint}\n\n"
                        f"Rewrite the bear thesis paragraph.  It must:\n"
                        f"1. Keep all existing bearish arguments.\n"
                        f"2. Add at least one compound risk interaction using the format:\n"
                        f"   '[Factor A] + [Factor B] = [compound outcome that is worse "
                        f"than either factor alone]'\n"
                        f"3. Remain one paragraph (200-400 words).\n"
                        f"4. Be company-specific — reference {company.ticker} by name.\n\n"
                        f"Return ONLY the updated bear thesis paragraph text. "
                        f"No JSON, no headings, no explanation."
                    )
                    _bear_raw = model_client.call(_bear_retry_prompt)
                    if _bear_raw and len(_bear_raw.strip()) > 100:
                        _patched = thesis.model_copy(
                            update={"bear_thesis": _bear_raw.strip()}
                        )
                        _retry_val = validate_thesis(_patched)
                        _still_failing = any(
                            v.check_id == "MISSING_COMPOUND_RISK"
                            for v in _retry_val.hard_violations
                        )
                        if not _still_failing:
                            thesis.bear_thesis = _bear_raw.strip()
                            logger.info(
                                "[synthesis_validator] MISSING_COMPOUND_RISK patched "
                                "via bear_thesis retry for %s",
                                company.ticker,
                            )
                            # Remove the now-resolved warning from the list
                            _val_result = _retry_val
                        else:
                            logger.info(
                                "[synthesis_validator] compound_risk retry did not "
                                "resolve for %s — keeping original with warning",
                                company.ticker,
                            )
                except Exception as _cr_exc:
                    logger.warning(
                        "[synthesis_validator] compound_risk retry failed (non-fatal): %r",
                        _cr_exc,
                    )

            # Append remaining hard validator warnings to consistency_warnings
            for _vv in _val_result.violations:
                if _vv.severity == "hard":
                    thesis.consistency_warnings.append(
                        f"[VALIDATOR:{_vv.check_id}] {_vv.description}"
                    )
        else:
            logger.debug(
                "[synthesis_validator] ticker=%s all checks passed (%d)",
                getattr(company, "ticker", "UNKNOWN"), _val_result.checks_run,
            )
    except Exception as _ve:
        logger.warning("[synthesis_validator] failed (non-fatal): %r", _ve)

    # ── Catalyst Calendar: extract from LLM output if returned ────────────────
    # The synthesis prompt asks the LLM to populate catalyst_calendar as a JSON
    # sub-object.  If it was returned (non-None), validate and stamp it.
    # If not returned but stance is Tactical, log a warning.
    try:
        from ..schemas import CatalystContext as _CatCtx
        _cc_raw = getattr(thesis, "catalyst_calendar", None)
        if _cc_raw is None and thesis.directional_stance == "Tactical":
            logger.info(
                "[catalyst_calendar] ticker=%s stance=Tactical but catalyst_calendar is None — "
                "prompt should have populated it",
                getattr(company, "ticker", "UNKNOWN"),
            )
        elif isinstance(_cc_raw, dict):
            # LLM returned a dict — validate into CatalystContext
            try:
                thesis.catalyst_calendar = _CatCtx.model_validate(_cc_raw)
            except Exception:
                thesis.catalyst_calendar = _CatCtx(**{
                    k: v for k, v in _cc_raw.items()
                    if k in _CatCtx.model_fields
                })
    except Exception as _cce:
        logger.warning("[catalyst_calendar] failed (non-fatal): %r", _cce)

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
