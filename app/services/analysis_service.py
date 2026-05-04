"""
Business logic for orchestrating AI analyst agents.

Enterprise integration:
  - All stages emit observability spans
  - Provider governance filters sources before evidence build
  - Audit record is always emitted (not gated behind a flag)
  - Tenant/user scope is extracted and propagated to evidence layer
  - request_id and trace_id flow through the full lifecycle
"""

import re
import uuid
import logging
import json
import time
from typing import List, Optional, Set

from ..schemas import (
    AnalysisRequest,
    AnalysisResponse,
    EquityAnalysis,
    MacroAnalysis,
    OpportunityAnalysis,
    ResearchAnalysis,
    EducationAnalysis,
    AccountingAnalysis,
    GroundingContext,
    SynthesisOutput,
)
from ..agents import (
    run_equity_agent,
    run_macro_agent,
    run_opportunity_agent,
    run_research_agent,
    run_education_agent,
    run_accounting_agent,
    run_synthesizer_agent,
)
from .router_service import classify_question
from .context_service import enrich_grounding_context
from .evidence_service import select_evidence_sources, build_evidence

# ── Enterprise layer — always imported, degrades gracefully ───────────────
try:
    from ..enterprise.observability import get_tracer, start_span, finish_trace, log_event
    from ..enterprise.audit import audit_store, AnalysisAuditRecord
    from ..enterprise.provider_registry import (
        provider_registry, get_provider_chain, CapabilityType, ProviderPolicy,
    )
    from ..enterprise.tenant import get_scope, ScopeContext
    from ..enterprise.cache import response_cache, provider_cache_key
    _ENTERPRISE = True
except Exception:
    _ENTERPRISE = False

logger = logging.getLogger(__name__)


# ── Null context manager for when trace is unavailable ────────────────────
from contextlib import contextmanager as _cm

@_cm
def _null_span():
    class _N:
        def set_tag(self, *a, **kw): pass
    yield _N()


# ---------------------------------------------------------------------------
# Signal quality helpers — used exclusively by _normalize_synthesis
# ---------------------------------------------------------------------------

# Substrings that indicate a signal is decision-relevant and high-impact.
_HIGH_IMPACT_TERMS: Set[str] = {
    "accelerat", "deceler", "collapse", "surge", "decline", "deteriorat",
    "restructur", "bankruptcy", "default", "catalyst", "upside", "downside",
    "significant", "material", "substantial", "critical", "severe", "major",
    "margin", "revenue", "earnings", "cash flow", "debt", "leverage",
    "market share", "competition", "regulat", "valuat", "guidance",
    "miss", "beat", "growth", "profit", "loss", "risk", "threat",
}

# Whole-word tokens that make a signal vague or generic.
_GENERIC_PENALTIES: Set[str] = {
    "could", "might", "possible", "potential", "various",
    "general", "certain", "ongoing", "continued", "remains",
}

# Common words to exclude when measuring signal overlap.
_STOPWORDS: Set[str] = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "should", "can", "may", "this", "that", "these",
    "those", "it", "its", "their", "which", "as", "if", "while",
    "when", "also", "both", "all", "any", "over", "into", "such",
}

# ---------------------------------------------------------------------------
# Signal type classification
#
# Each type maps to a list of keyword/phrase patterns (substring match on
# lowercased signal text).  Classification is first-match in priority order:
# structural → risk → catalyst → cyclical → short_term → noise.
# ---------------------------------------------------------------------------
_SIGNAL_TYPE_PATTERNS: List[tuple] = [
    ("structural", [
        "business model", "competitive advantage", "moat", "platform",
        "network effect", "switching cost", "pricing power", "long-term",
        "secular", "structural", "market leader", "ecosystem",
        "infrastructure", "franchise", "durable",
    ]),
    ("risk", [
        "risk", "threat", "headwind", "challenge", "concern", "exposure",
        "vulnerab", "downside", "deteriorat", "decline", "loss", "default",
        "bankruptcy", "regulat", "lawsuit", "litigation", "debt", "leverage",
        "margin compression", "miss", "shortfall",
    ]),
    ("catalyst", [
        "catalyst", "upside", "opportunit", "launch", "expansion",
        "acquisition", "partnership", "contract", "new product", "guidance raise",
        "beat", "accelerat", "inflection", "unlock", "re-rating",
    ]),
    ("cyclical", [
        "cyclical", "cycle", "interest rate", "inflation", "macro",
        "recession", "economic", "gdp", "monetary policy", "fed",
        "commodity", "inventory", "seasonal", "demand softening",
    ]),
    ("short_term", [
        "quarter", "q1", "q2", "q3", "q4", "near-term", "short-term",
        "next quarter", "this quarter", "month", "week",
        "earnings call", "guidance cut", "print",
    ]),
    ("noise", [
        "noise", "minor", "immaterial", "negligible", "slight", "modest",
        "unlikely to", "no significant", "not material", "little impact",
        "remains broadly", "broadly stable",
    ]),
]

# Score adjustments applied on top of the base impact score.
_TYPE_SCORE_ADJUSTMENTS: dict = {
    "structural": +1.0,
    "risk":       +0.5,
    "catalyst":    0.0,
    "cyclical":    0.0,
    "short_term":  0.0,
    "noise":      -1.0,
}


def _classify_signal_type(signal: str) -> str:
    """Classify a signal string into one of six types using keyword heuristics.

    Types in priority order: structural, risk, catalyst, cyclical,
    short_term, noise.  Returns the first matching type, or "catalyst"
    as a neutral default when nothing matches.
    """
    text = signal.lower()
    for signal_type, patterns in _SIGNAL_TYPE_PATTERNS:
        if any(pat in text for pat in patterns):
            return signal_type
    return "catalyst"


def _score_signal(signal: str) -> float:
    """Return an impact score for a signal string.

    Base score: +1 per high-impact term, −0.5 per generic filler term,
    −0.5 if longer than 20 words.
    Type adjustment: structural +1.0, risk +0.5, noise −1.0, others 0.
    """
    text = signal.lower()
    score = sum(1.0 for term in _HIGH_IMPACT_TERMS if term in text)
    score -= sum(
        0.5 for term in _GENERIC_PENALTIES
        if re.search(r'\b' + re.escape(term) + r'\b', text)
    )
    if len(text.split()) > 20:
        score -= 0.5
    score += _TYPE_SCORE_ADJUSTMENTS.get(_classify_signal_type(signal), 0.0)
    return score


def _meaningful_tokens(signal: str) -> Set[str]:
    """Extract non-trivial lowercase word tokens from a signal string."""
    words = re.findall(r'\b[a-z]+\b', signal.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    """Jaccard similarity between two token sets; 0 if either is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _rank_and_merge(items: List[str], max_items: int = 5) -> List[str]:
    """Sort signals by impact, merge near-duplicates, return top max_items.

    Two signals are considered similar when their Jaccard similarity on
    meaningful tokens reaches 0.35 or higher.  From each similar pair the
    higher-scored signal is kept; the lower-scored one is dropped.  This
    prevents the ranked list from being dominated by rephrased variants of
    the same underlying point.
    """
    if not items:
        return items

    # Sort highest-impact first so greedy selection always keeps the better signal.
    scored = sorted(
        ((s.strip(), _score_signal(s)) for s in items if s.strip()),
        key=lambda x: x[1],
        reverse=True,
    )

    chosen: List[str] = []
    chosen_tokens: List[Set[str]] = []

    for signal, _score in scored:
        tokens = _meaningful_tokens(signal)
        # Skip if too similar to a signal already chosen (merges similar signals
        # by retaining the higher-impact representative).
        if any(_jaccard(tokens, ct) >= 0.35 for ct in chosen_tokens):
            continue
        chosen.append(signal)
        chosen_tokens.append(tokens)
        if len(chosen) >= max_items:
            break

    return chosen


# ---------------------------------------------------------------------------
# Change trigger derivation
#
# Each trigger map entry is (synonym_list, trigger_text).
# Matching is first-match substring search on lowercased signal text.
# Synonym lists are deliberately broad to cover varied analyst phrasings.
# ---------------------------------------------------------------------------

# Confidence → (min_triggers, max_triggers)
_CONFIDENCE_TRIGGER_RANGE: dict = {
    "high":   (2, 3),
    "medium": (3, 4),
    "low":    (4, 5),
}

_DOWNSIDE_TRIGGER_MAP: List[tuple] = [
    # Revenue / top-line
    (["revenue", "top-line", "topline", "net sales", "sales growth",
      "organic growth", "top line", "turnover"],
     "Revenue growth decelerating materially below consensus estimates"),
    # Margin / profitability
    (["margin", "profitab", "gross profit", "operating profit", "ebitda",
      "cost pressure", "spread compression", "unit economics"],
     "Gross or operating margin contracting on pricing pressure or cost inflation"),
    # Guidance / outlook
    (["guidance", "outlook", "forecast", "projection", "forward estimate",
      "raised guidance", "lowered guidance", "full-year"],
     "Forward guidance cut reflecting deteriorating demand or elevated operating costs"),
    # Debt / leverage / liquidity
    (["debt", "leverage", "leverag", "balance sheet", "liquid", "credit",
      "covenant", "borrow", "net debt", "capital structure", "interest coverage"],
     "Net leverage rising above management's stated target, triggering credit concern"),
    # Competition / market share
    (["competit", "market share", "rival", "displacement", "pricing war",
      "incumbent", "moat erosion", "share loss", "price competition"],
     "Market share erosion accelerating as competitors undercut on price or features"),
    # Regulation / legal
    (["regulat", "compliance", "lawsuit", "litigation", "enforce", "fine",
      "penalty", "antitrust", "government action", "policy change", "legal"],
     "Adverse regulatory decision imposing material operational or financial constraints"),
    # Cash flow
    (["cash flow", "free cash", "cashflow", "fcf", "cash generation",
      "working capital", "burn rate", "cash conversion"],
     "Free cash flow turning negative, calling reported earnings quality into question"),
    # Earnings / EPS
    (["earnings", "eps", "net income", "bottom-line", "bottomline",
      "profit miss", "income miss", "ebitda miss"],
     "Earnings miss with downward revision to full-year guidance"),
    # Macro / rates
    (["macro", "interest rate", "inflation", "recession", "economic slowdown",
      "gdp", "fed", "monetary policy", "rate hike", "stagflat", "rate environment"],
     "Macro deterioration — rate hikes, recessionary demand, or dollar strength — pressuring volumes and multiples"),
    # Growth / re-rating
    (["growth", "accelerat", "expansion", "re-rating", "unit growth",
      "volume growth", "scale"],
     "Core growth rate decelerating below the level required to justify current valuation"),
    # Demand / end markets
    (["demand", "volume", "orders", "backlog", "traffic", "end market",
      "consumption", "throughput", "booking"],
     "End-market demand softening more sharply than the bull-case volume assumption"),
    # Management / strategy
    (["management", "ceo", "cfo", "leadership", "executive", "board",
      "c-suite", "strategy shift", "capital allocation"],
     "Unplanned CEO or CFO departure, or a strategic pivot that lacks investor credibility"),
    # Pricing power
    (["pricing power", "pricing", "price increase", "asm", "net revenue per unit",
      "blended rate", "rate card", "average selling price", "asp"],
     "Pricing power deteriorating as volume sensitivity forces promotional activity"),
    # Costs / expenses
    (["cost", "expense", "opex", "capex", "overhead", "wage", "labor",
      "input cost", "supply chain cost", "sga", "r&d spend"],
     "Operating cost inflation outpacing revenue growth and compressing EBITDA margins"),
    # Default / solvency
    (["default", "bankruptcy", "bankrupt", "insolvency", "solvency",
      "liquidity crisis", "going concern", "distress"],
     "Liquidity position weakening to a point where covenant breach or distress becomes plausible"),
    # Restructuring
    (["restructur", "layoff", "workforce reduction", "reorganiz",
      "divest", "asset sale", "spinoff"],
     "Restructuring charges expanding beyond guided scope, signaling deeper operational issues"),
    # Customer / churn
    (["customer", "churn", "retention", "renewal", "logo", "nrr", "net retention",
      "subscriber", "attrition"],
     "Customer churn or contract non-renewals accelerating above historical norms"),
    # Inventory / supply
    (["inventory", "supply chain", "supplier", "lead time", "stock",
      "excess inventory", "channel fill", "destocking"],
     "Inventory build or supply chain disruption compressing near-term revenue recognition"),
]

_UPSIDE_TRIGGER_MAP: List[tuple] = [
    # Revenue / top-line
    (["revenue", "top-line", "topline", "net sales", "sales growth",
      "organic growth", "top line", "turnover"],
     "Revenue growth reaccelerating above consensus, confirming demand durability"),
    # Margin / profitability
    (["margin", "profitab", "gross profit", "operating profit", "ebitda",
      "cost pressure", "spread", "unit economics"],
     "Gross margin expansion materializing through scale benefits or improved pricing discipline"),
    # Guidance / outlook
    (["guidance", "outlook", "forecast", "projection", "forward estimate",
      "full-year"],
     "Full-year guidance raised, signaling improving demand visibility and execution confidence"),
    # Debt / leverage
    (["debt", "leverage", "leverag", "balance sheet", "liquid", "credit",
      "covenant", "net debt", "capital structure"],
     "Leverage declining faster than planned, opening capacity for capital returns or reinvestment"),
    # Competition / market share
    (["competit", "market share", "rival", "share gain", "moat",
      "displacement", "incumbent", "competitive position"],
     "Sustained market share gains validating the competitive moat and pricing thesis"),
    # Regulation / legal
    (["regulat", "compliance", "legal", "lawsuit", "antitrust",
      "government", "policy", "regulatory clarity"],
     "Regulatory overhang lifted, removing the key sentiment discount from the stock"),
    # Macro / rates
    (["macro", "interest rate", "inflation", "recession", "gdp",
      "fed", "monetary policy", "rate cut", "rate environment"],
     "Rate cuts or improved macro backdrop reducing cost of capital and supporting valuation re-rating"),
    # Earnings / EPS
    (["earnings", "eps", "net income", "bottom-line", "bottomline",
      "profit beat", "ebitda beat"],
     "Earnings beat with upward guidance revision driving broad positive estimate revisions"),
    # Growth / re-rating
    (["growth", "accelerat", "expansion", "re-rating", "unit growth",
      "scale", "inflection"],
     "Growth rate inflecting above consensus, catalyzing multiple expansion"),
    # Demand / end markets
    (["demand", "volume", "orders", "backlog", "traffic", "end market",
      "consumption", "booking"],
     "Demand recovering sharply in key end markets, above the bear-case floor"),
    # Cash flow
    (["cash flow", "free cash", "cashflow", "fcf", "cash generation",
      "cash conversion", "working capital"],
     "Free cash flow inflecting positively, enabling buybacks or accelerated debt paydown"),
    # Management / strategy
    (["management", "ceo", "cfo", "leadership", "executive", "board",
      "strategy", "capital allocation"],
     "Strategic reset or credible capital allocation improvement backed by demonstrable actions"),
    # Pricing power
    (["pricing power", "pricing", "price increase", "asp", "asm",
      "blended rate", "net revenue per unit"],
     "Pricing power reasserting as supply tightens or brand premium strengthens"),
    # Costs / expenses
    (["cost", "expense", "opex", "overhead", "wage", "labor",
      "input cost", "supply chain", "sga"],
     "Cost structure rightsizing driving margin recovery ahead of the market's timeline"),
    # Customer / retention
    (["customer", "churn", "retention", "renewal", "nrr", "net retention",
      "subscriber", "logo"],
     "Customer retention improving and net revenue retention exceeding prior-period levels"),
    # Inventory / supply
    (["inventory", "supply chain", "supplier", "destocking", "channel",
      "lead time"],
     "Inventory normalization completing faster than expected, unlocking deferred revenue"),
]

# Type-based fallbacks when keyword matching finds no match.
# Tuple is (downside_trigger, upside_trigger).
_TYPE_TRIGGER_FALLBACKS: dict = {
    "structural": (
        "Competitive advantage eroding faster than the investment thesis assumes",
        "Structural moat proving wider than consensus reflects, enabling durable outperformance",
    ),
    "risk": (
        "Identified risk materializing at full severity rather than being contained",
        "Key risk resolving or proving less severe than current market pricing implies",
    ),
    "catalyst": (
        "Primary catalyst delayed or failing to materialize on the expected timeline",
        "Catalyst executing ahead of schedule and exceeding initial market expectations",
    ),
    "cyclical": (
        "Cyclical downturn proving deeper or more prolonged than the base case",
        "Cyclical recovery arriving earlier and stronger than consensus projects",
    ),
    "short_term": (
        "Near-term earnings miss triggering a sentiment reset and valuation de-rating",
        "Near-term beat with raised guidance restoring confidence in the medium-term thesis",
    ),
    "noise": (
        "Noise signals converging into a sustained directional change in fundamentals",
        "Fundamental resilience confirmed, dismissing noise as transient rather than structural",
    ),
}

# Stance-appropriate hard defaults — used only when signal matching yields fewer
# than the minimum required triggers.
_DEFAULT_TRIGGERS: dict = {
    "bullish": [
        "Earnings deceleration prompting broad consensus estimate cuts",
        "Macro shock compressing sector multiples and resetting investor expectations",
        "Guidance cut signaling demand weakness or elevated cost pressure",
        "Margin deterioration that cannot be offset through pricing or efficiency gains",
        "Market share loss accelerating beyond a level consistent with the bull thesis",
    ],
    "constructive": [
        "Guidance cut reflecting deteriorating demand or higher-than-expected costs",
        "Margin compression exceeding the range consistent with the constructive thesis",
        "Earnings miss with downward revisions removing the near-term re-rating catalyst",
        "Demand softening across core end markets at a pace that questions the growth runway",
        "Leverage rising above management targets without a credible deleveraging path",
    ],
    "neutral": [
        "Guidance cut or earnings miss shifting the balance of evidence decisively negative",
        "Guidance raise or earnings beat shifting the balance of evidence decisively positive",
        "Macro deterioration compressing multiples and demand simultaneously",
        "Catalyst execution validating the bull case and triggering upward estimate revisions",
        "Risk materialization at full magnitude removing the neutral case",
    ],
    "cautious": [
        "Earnings beat accompanied by a raised guidance restoring investor confidence",
        "Macro easing reducing cost-of-capital headwinds and improving the valuation floor",
        "Key risk resolving or proving less severe than current market pricing implies",
        "Margin recovery demonstrating the cost structure is more flexible than feared",
        "Demand stabilizing at levels that call the bear case into question",
    ],
    "bearish": [
        "Earnings beat with raised full-year guidance triggering broad estimate upgrades",
        "Key risk resolving or proving immaterial relative to market pricing",
        "Demand reaccelerating in core markets above the bear-case floor",
        "Management credibly demonstrating a path to margin recovery",
        "Macro inflection reducing cost-of-capital pressure and supporting re-rating",
    ],
}


def _match_trigger(signal: str, trigger_map: List[tuple]) -> Optional[tuple]:
    """Return (concept_key, trigger_text) for the first map entry whose synonyms
    appear in the signal text, or None if no entry matches."""
    text = signal.lower()
    for keywords, trigger in trigger_map:
        if any(kw in text for kw in keywords):
            return keywords[0], trigger
    return None


def _derive_change_triggers(synthesis: SynthesisOutput) -> List[str]:
    """Generate causal triggers that would change the current stance.

    Count is confidence-aware:
      high confidence   → 2–3 triggers (clear thesis, fewer swing factors)
      medium confidence → 3–4 triggers
      low confidence    → 4–5 triggers (wider uncertainty, more scenarios)

    Direction is stance-aware:
      bullish/constructive → downside triggers (risks materializing or drivers stalling)
      bearish/cautious     → upside triggers   (risks dissipating, catalysts executing)
      neutral              → alternating mix of both

    Resolution order per signal: keyword match → type fallback → stance defaults.
    Duplicate concept keys are suppressed to ensure variety across triggers.
    """
    stance     = synthesis.stance or "neutral"
    confidence = synthesis.confidence_level or "medium"
    risks      = synthesis.key_risks_ranked   or []
    drivers    = synthesis.key_drivers_ranked or []

    min_triggers, max_triggers = _CONFIDENCE_TRIGGER_RANGE.get(
        confidence, (2, 4)
    )

    if stance in ("bullish", "constructive"):
        direction    = "down"
        signal_order = risks[:4] + drivers[:3]
    elif stance in ("bearish", "cautious"):
        direction    = "up"
        signal_order = drivers[:4] + risks[:3]
    else:  # neutral: interleave risks (down) and drivers (up)
        direction    = "mixed"
        signal_order = []
        for r, d in zip(risks[:3], drivers[:3]):
            signal_order += [r, d]
        signal_order += risks[3:4] + drivers[3:4]

    triggers: List[str]    = []
    seen_concepts: Set[str] = set()

    def _add(trigger: str, concept: str) -> bool:
        if concept not in seen_concepts and trigger not in triggers:
            seen_concepts.add(concept)
            triggers.append(trigger)
            return True
        return False

    for i, signal in enumerate(signal_order):
        if len(triggers) >= max_triggers:
            break

        active_pool = (
            _DOWNSIDE_TRIGGER_MAP if i % 2 == 0 else _UPSIDE_TRIGGER_MAP
        ) if direction == "mixed" else (
            _DOWNSIDE_TRIGGER_MAP if direction == "down" else _UPSIDE_TRIGGER_MAP
        )

        match = _match_trigger(signal, active_pool)
        if match:
            concept, trigger = match
            _add(trigger, concept)
        else:
            sig_type = _classify_signal_type(signal)
            pair = _TYPE_TRIGGER_FALLBACKS.get(sig_type)
            if pair:
                use_up = direction == "up" or (direction == "mixed" and i % 2 == 1)
                _add(pair[1] if use_up else pair[0], sig_type + "_fb")

    # Fill to minimum using stance defaults if keyword + type matching fell short.
    if len(triggers) < min_triggers:
        for default in _DEFAULT_TRIGGERS.get(stance, _DEFAULT_TRIGGERS["neutral"]):
            if len(triggers) >= min_triggers:
                break
            _add(default, "default_" + default[:24])

    return triggers[:max_triggers]


_STANCE_ORDER = ["bearish", "cautious", "neutral", "constructive", "bullish"]

# Verdict words produced by the synthesizer agent mapped to an index in
# _STANCE_ORDER, used to nudge the derived stance by one step.
_VERDICT_NUDGE: dict = {
    "bullish": +1, "constructive": +1,
    "bearish": -1, "cautious": -1,
    "neutral": 0,  "mixed": 0,
}


def _derive_stance_and_confidence(synthesis: SynthesisOutput) -> tuple:
    """Derive stance (5-point scale) and confidence (high/medium/low) from
    the normalized signal lists and the model's own final_verdict.

    Stance algorithm
    ----------------
    1. Score each driver and risk signal with _score_signal (clamped ≥ 0 so
       noise signals don't invert polarity).
    2. Weight structural/catalyst drivers × 1.5; weight risk-type risks × 1.5.
    3. Compute a balance ratio: (pos − neg) / (pos + neg).
    4. Map the ratio to a 5-point stance.
    5. Nudge by one step in the direction of the model's own final_verdict.

    Conflict detection
    ------------------
    If strong positive drivers (score ≥ 2) and strong risk signals coexist,
    the situation is flagged as conflicted: stance is clamped to the
    neutral ± 1 band and confidence is capped at medium.

    Confidence algorithm
    --------------------
    - high   : ≥ 3 strong signals, no conflict, ≤ 1 noise signal, ≥ 4 total
    - medium : ≥ 1 strong signal, ≤ 1 noise signal (or conflict with ≥ 2 strong)
    - low    : everything else
    """
    drivers = synthesis.key_drivers_ranked or []
    risks   = synthesis.key_risks_ranked   or []

    # Score signals; clamp to 0 so noise doesn't distort polarity.
    driver_scores = [max(0.0, _score_signal(s)) for s in drivers]
    risk_scores   = [max(0.0, _score_signal(s)) for s in risks]

    driver_types = [_classify_signal_type(s) for s in drivers]
    risk_types   = [_classify_signal_type(s) for s in risks]

    # Weighted positive and negative mass.
    pos_weight = sum(
        sc * (1.5 if t in ("structural", "catalyst") else 1.0)
        for sc, t in zip(driver_scores, driver_types)
    )
    neg_weight = sum(
        sc * (1.5 if t == "risk" else 1.0)
        for sc, t in zip(risk_scores, risk_types)
    )

    # Conflict: strong drivers and strong risks both present.
    strong_drivers = [sc for sc in driver_scores if sc >= 2.0]
    strong_risks   = [sc for sc in risk_scores   if sc >= 2.0]
    has_conflict   = bool(strong_drivers and strong_risks)

    all_types  = driver_types + risk_types
    noise_count = all_types.count("noise")

    # --- Stance ---
    total = pos_weight + neg_weight or 1.0
    ratio = (pos_weight - neg_weight) / total  # range: -1 to +1

    if has_conflict:
        # Clamp to neutral ± 1 when signals sharply conflict.
        if ratio > 0.2:
            stance = "constructive"
        elif ratio < -0.2:
            stance = "cautious"
        else:
            stance = "neutral"
    else:
        if ratio > 0.5:
            stance = "bullish"
        elif ratio > 0.15:
            stance = "constructive"
        elif ratio > -0.15:
            stance = "neutral"
        elif ratio > -0.5:
            stance = "cautious"
        else:
            stance = "bearish"

    # Nudge by the model's own verdict (max one step).
    verdict = (synthesis.final_verdict or "").lower().strip()
    nudge   = _VERDICT_NUDGE.get(verdict, 0)
    if nudge:
        idx = _STANCE_ORDER.index(stance) if stance in _STANCE_ORDER else 2
        stance = _STANCE_ORDER[max(0, min(4, idx + nudge))]

    # --- Confidence ---
    strong_count = len(strong_drivers) + len(strong_risks)
    total_signals = len(drivers) + len(risks)

    if has_conflict:
        confidence = "medium" if strong_count >= 2 and noise_count == 0 else "low"
    elif strong_count >= 3 and noise_count == 0 and total_signals >= 4:
        confidence = "high"
    elif strong_count >= 1 and noise_count <= 1:
        confidence = "medium"
    else:
        confidence = "low"

    return stance, confidence


_VERDICT_ACTION_MAP: dict = {
    "bullish":      "Add {company}",
    "constructive": "Add {company} on weakness",
    "neutral":      "Hold {company} for now",
    "cautious":     "Be cautious with {company} here",
    "bearish":      "Avoid {company} at current levels",
    "mixed":        "Hold {company} for now",
}


def _clean(text: str, max_chars: int = 150) -> str:
    """Truncate to max_chars and strip trailing punctuation for clean sentence embedding."""
    t = (text or "").strip()[:max_chars].rstrip(".,;: ")
    if not t:
        return ""
    # Lowercase the first character so the text embeds naturally after a prefix
    return t[0].lower() + t[1:]


def _build_fallback_reasoning(synthesis: SynthesisOutput, company: str) -> str:
    """Build a 4-sentence verdict_reasoning when the LLM returns empty.

    Sentence structure:
      1. Decision + company name (verdict-mapped opener)
      2. Key driver — what is working (or why the case is uncertain)
      3. Key risk — the complication (using 'but' / 'however')
      4. Practical guidance for a beginner investor with a concrete watchpoint

    Sources (in priority order):
      - key_drivers_ranked / key_risks_ranked  (already ranked by _normalize_synthesis)
      - bull_case / bear_case                  (fallback when ranked lists are empty)
      - Generic stanced sentences              (last resort — no banned phrases)
    """
    co = company.strip() if company and company.strip() else "this company"

    # ── Resolve stance word ───────────────────────────────────────────────────
    # synthesis.stance is set by _derive_stance_and_confidence (step 3) which
    # runs before this fallback (step 5), so prefer it over final_verdict.
    _known = {"bullish", "bearish", "constructive", "cautious", "neutral", "mixed"}
    stance = (synthesis.stance or "").lower().strip()
    if stance not in _known:
        # Extract first known word from final_verdict if stance is missing/sentence
        fv = (synthesis.final_verdict or "").lower()
        stance = next((w for w in _known if w in fv), "neutral")

    # ── Collect raw material ──────────────────────────────────────────────────
    drivers = [d.strip() for d in (synthesis.key_drivers_ranked or []) if d and d.strip()]
    risks   = [r.strip() for r in (synthesis.key_risks_ranked   or []) if r and r.strip()]
    bulls   = [b.strip() for b in (synthesis.bull_case          or []) if b and b.strip()]
    bears   = [b.strip() for b in (synthesis.bear_case          or []) if b and b.strip()]
    monitor = next(
        (m.strip() for m in (synthesis.what_to_monitor or []) if m and m.strip()),
        None,
    )

    # Choose best available driver and risk signal
    driver = drivers[0] if drivers else (bulls[0] if bulls else None)
    risk   = risks[0]   if risks   else (bears[0] if bears else None)

    print(f"FALLBACK DRIVER USED: {driver!r}")
    print(f"FALLBACK RISK USED:   {risk!r}")

    # ── Sentence 1: Decision + company ───────────────────────────────────────
    action_template = _VERDICT_ACTION_MAP.get(stance, "Hold {company} for now")
    s1 = action_template.format(company=co) + "."

    # ── Sentence 2: Key driver ────────────────────────────────────────────────
    # key_drivers_ranked signals are already full sentences — use them directly.
    # Company name only appears in S1; S2 leads with the signal, not the company.
    if driver:
        d_text = driver.strip().rstrip(".,;: ")
        s2 = d_text[0].upper() + d_text[1:] + "."
    else:
        # Generic fallback — each stance gets a distinct opener so back-to-back
        # analyses don't read identically.  Three natural openers are spread
        # across the six stances; same opener never appears in adjacent groups.
        if stance == "bullish":
            s2 = "Right now, the signals across equity, macro, and operations point to a positive setup."
        elif stance == "constructive":
            s2 = "At the moment, the weight of evidence leans positive — though conviction isn't yet strong enough to be aggressive."
        elif stance == "bearish":
            s2 = "At the moment, the evidence points to meaningful headwinds — it's hard to justify adding new exposure here."
        elif stance == "cautious":
            s2 = "As things stand, the risk/reward doesn't clearly favour adding here."
        else:  # neutral / mixed
            s2 = "Right now, the evidence is balanced enough that neither adding nor reducing makes obvious sense."

    # ── Sentence 3: Key risk (connects with 'but' / 'however') ──────────────
    # key_risks_ranked signals are already full sentences — use them directly.
    if risk:
        r_text = risk.strip().rstrip(".,;: ")
        r_lower = r_text[0].lower() + r_text[1:]
        s3 = f"However, {r_lower} — that's the key risk to watch."
    else:
        if stance in ("bullish", "constructive"):
            s3 = "That said, any deterioration in the fundamentals or a shift in macro conditions could limit the upside."
        elif stance in ("bearish", "cautious"):
            s3 = "Until there's clear evidence of improvement, the downside risk outweighs the potential upside here."
        else:
            s3 = "The stock still needs stronger confirmation from earnings, margins, or key operating metrics before the case becomes more compelling."

    # ── Sentence 4: Practical guidance ───────────────────────────────────────
    # Use 'it' instead of company name; contractions where natural.
    if monitor:
        m = _clean(monitor, max_chars=120)
    else:
        m = None

    if stance == "bullish":
        s4 = (
            "Given this setup, adding on any pullback makes sense"
            + (f" — keep an eye on {m}." if m else " — just size it conservatively until the thesis confirms.")
        )
    elif stance == "constructive":
        s4 = (
            "At this point, adding on any weakness makes sense"
            + (f" — watch {m} before committing more." if m else " — keep the position small until there's more confirmation.")
        )
    elif stance == "bearish":
        s4 = (
            "At this point, staying out makes sense"
            + (f" — watch {m} for any sign of a turn." if m else " until the fundamental picture improves.")
        )
    elif stance == "cautious":
        s4 = (
            "For now, holding lightly is the safer move"
            + (f" — don't add until {m} improves." if m else " — don't add until things stabilize.")
        )
    else:  # neutral / mixed
        s4 = (
            "If you already own it, holding makes sense"
            + (f" — watch {m} before adding more." if m else " — but it's worth waiting for stronger evidence before buying more.")
        )

    return " ".join([s1, s2, s3, s4])


def _normalize_synthesis(synthesis: SynthesisOutput, company: str = "") -> SynthesisOutput:
    """Normalize synthesis output fields before returning to the caller.

    1. Trims final_verdict to at most 2 sentences.
    2. Ranks, merges near-duplicates, and caps ranked signal lists at 5.
    3. Derives stance and confidence_level from the normalized signals.
    4. Derives what_would_change_this_view from signals + stance.
    5. Guarantees verdict_reasoning is always non-empty.
    The SynthesisOutput schema is not structurally altered.
    """
    # 1. Trim final_verdict to max 2 sentences
    verdict = synthesis.final_verdict or ""
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', verdict) if s.strip()]
    if len(sentences) > 2:
        synthesis.final_verdict = " ".join(sentences[:2])

    # 2. Rank, merge, and cap ranked signal lists
    synthesis.key_drivers_ranked = _rank_and_merge(synthesis.key_drivers_ranked)
    synthesis.key_risks_ranked   = _rank_and_merge(synthesis.key_risks_ranked)

    # 3. Derive stance and confidence (must run before trigger derivation)
    synthesis.stance, synthesis.confidence_level = _derive_stance_and_confidence(synthesis)

    # 4. Derive causal change triggers from the finalized signals + stance
    synthesis.what_would_change_this_view = _derive_change_triggers(synthesis)

    # 5. Guarantee verdict_reasoning is always non-empty
    print(f"LLM RAW VERDICT_REASONING: {synthesis.verdict_reasoning!r}")
    if not synthesis.verdict_reasoning or not synthesis.verdict_reasoning.strip():
        print(f"FALLBACK TRIGGERED for company={company!r} — LLM returned empty verdict_reasoning")
        synthesis.verdict_reasoning = _build_fallback_reasoning(synthesis, company)

    return synthesis


def analyze_company(
    request: AnalysisRequest,
    scope: Optional["ScopeContext"] = None,
) -> AnalysisResponse:
    """Run the full analysis workflow for a given request.

    Enterprise path (always active):
        1. Start observability trace
        2. Resolve tenant/user scope
        3. Governance: filter allowed evidence sources
        4. Evidence build (with spans, governed calls, history_ops, cache)
        5. Routing + agent execution (with per-agent spans)
        6. Synthesis
        7. Emit full audit record
        8. Finish trace
    """
    request_id = str(uuid.uuid4())
    company    = request.company_name
    t_start    = time.perf_counter()

    # ── 1. Start observability trace ──────────────────────────────────────
    trace = None
    if _ENTERPRISE:
        try:
            trace = get_tracer(request_id=request_id)
            trace.set_metadata("company",  company)
            trace.set_metadata("question", request.user_question or "")
        except Exception:
            trace = None

    # ── 2. Resolve scope ──────────────────────────────────────────────────
    if scope is None and _ENTERPRISE:
        try:
            scope = get_scope(getattr(request, "session_id", "") or
                              getattr(request, "user_id", "") or "")
        except Exception:
            scope = None

    # Attach request_id and scope to context so evidence layer can use them
    _base_ctx = getattr(request, "context", None)

    with (start_span(trace, "context_enrichment") if trace else _null_span()) as sp:
        try:
            context = enrich_grounding_context(company, request.user_question, _base_ctx)
            # Propagate request_id and scope into grounding context
            try:
                object.__setattr__(context, "request_id", request_id)
            except Exception:
                pass
            if scope is not None:
                try:
                    object.__setattr__(context, "scope", scope)
                except Exception:
                    pass
        except Exception as exc:
            logger.error(json.dumps({"event": "context_enrichment_error",
                                     "error": str(exc), "request_id": request_id}))
            context = GroundingContext(company=company)

    # ── 3. Governance: determine allowed sources ──────────────────────────
    with (start_span(trace, "evidence_selection") if trace else _null_span()) as sp:
        try:
            evidence_decision  = select_evidence_sources(request.user_question)
            selected_sources   = evidence_decision.get("selected_sources", [])
        except Exception as exc:
            logger.error(json.dumps({"event": "evidence_selection_error",
                                     "error": str(exc), "request_id": request_id}))
            evidence_decision  = {"selected_sources": [], "skipped_sources": [],
                                   "reasons": {}, "confidence": 0.0}
            selected_sources   = []

        # Filter sources through governance when enterprise is available
        if _ENTERPRISE and provider_registry is not None:
            try:
                from ..config import settings as _cfg
                has_fmp_key = bool(getattr(_cfg, "fmp_api_key", ""))
                pol = ProviderPolicy(require_citeable=True)
                # Remove sources denied by scope restrictions
                if scope is not None:
                    selected_sources = [s for s in selected_sources
                                        if scope.can_access_source(s)]
                # Remove sources denied by governance policy
                governed = []
                for src in selected_sources:
                    dec = provider_registry.check_access(
                        src, policy=pol,
                        has_api_key=(has_fmp_key if src == "fmp" else True)
                    )
                    if dec.allowed:
                        governed.append(src)
                    else:
                        logger.info(json.dumps({"event": "source_denied_by_governance",
                                                "source": src, "reason": dec.reason,
                                                "request_id": request_id}))
                selected_sources = governed
            except Exception:
                pass  # governance errors are non-fatal
        if sp:
            sp.set_tag("sources", selected_sources)
            sp.set_tag("governance_applied", _ENTERPRISE)

    # ── 4. Evidence build ─────────────────────────────────────────────────
    with (start_span(trace, "evidence_build", {"sources": selected_sources})
          if trace else _null_span()) as sp:
        try:
            context = build_evidence(
                company, context.ticker or company,
                request.user_question, selected_sources, context
            )
            if sp:
                sp.set_tag("known_facts_count",
                           len(getattr(context, "known_facts", [])))
                sp.set_tag("historical_meanings",
                           list(getattr(context, "historical_meanings", {}).keys()))
        except Exception as exc:
            logger.error(json.dumps({"event": "evidence_build_error",
                                     "error": str(exc), "request_id": request_id}))

    t_evidence_end = time.perf_counter()
    logger.info(json.dumps({"event": "evidence_built", "request_id": request_id,
                            "duration": t_evidence_end - t_start}))

    # ── 5. Routing ────────────────────────────────────────────────────────
    with (start_span(trace, "routing") if trace else _null_span()) as sp:
        if request.user_question:
            routing_decision = classify_question(request.user_question)
        else:
            routing_decision = classify_question("")
        selected_agents: List[str] = routing_decision.get("selected_agents", [])
        if sp:
            sp.set_tag("agents", selected_agents)

    logger.info(json.dumps({"event": "analysis_started", "request_id": request_id,
                            "company": company, "question": request.user_question,
                            "routing": routing_decision}))

    # ── 6. Agent execution ────────────────────────────────────────────────
    equity      = EquityAnalysis()
    macro       = MacroAnalysis()
    opportunity = OpportunityAnalysis()
    research    = ResearchAnalysis()
    education   = EducationAnalysis()
    accounting  = AccountingAnalysis()

    _AGENT_RUNNERS = {
        "equity":      lambda: run_equity_agent(company, context=context,
                                                 user_question=request.user_question,
                                                 request_id=request_id),
        "macro":       lambda: run_macro_agent(company, context=context,
                                               request_id=request_id),
        "opportunity": lambda: run_opportunity_agent(company, context=context,
                                                      request_id=request_id),
        "research":    lambda: run_research_agent(company, context=context,
                                                   request_id=request_id),
        "education":   lambda: run_education_agent(company, context=context,
                                                    request_id=request_id),
        "accounting":  lambda: run_accounting_agent(company, context=context,
                                                     request_id=request_id),
    }
    _AGENT_DEFAULTS = {
        "equity": EquityAnalysis, "macro": MacroAnalysis,
        "opportunity": OpportunityAnalysis, "research": ResearchAnalysis,
        "education": EducationAnalysis, "accounting": AccountingAnalysis,
    }

    agent_errors: List[str] = []
    for agent in selected_agents:
        runner = _AGENT_RUNNERS.get(agent)
        if runner is None:
            continue
        with (start_span(trace, f"agent_{agent}") if trace else _null_span()) as sp:
            try:
                a_start = time.perf_counter()
                result  = runner()
                a_dur   = time.perf_counter() - a_start
                if sp:
                    sp.set_tag("duration_ms", a_dur * 1000)
                logger.info(json.dumps({"event": "agent_timing", "agent": agent,
                                        "duration": a_dur, "request_id": request_id}))
                if agent == "equity":      equity      = result
                elif agent == "macro":     macro       = result
                elif agent == "opportunity": opportunity = result
                elif agent == "research":  research    = result
                elif agent == "education": education   = result
                elif agent == "accounting": accounting  = result
            except Exception as exc:
                agent_errors.append(agent)
                logger.error(json.dumps({"event": "agent_error", "agent": agent,
                                         "error": str(exc), "request_id": request_id}))
                default_cls = _AGENT_DEFAULTS.get(agent)
                if default_cls:
                    result = default_cls()
                    if agent == "equity":      equity      = result
                    elif agent == "macro":     macro       = result
                    elif agent == "opportunity": opportunity = result
                    elif agent == "research":  research    = result
                    elif agent == "education": education   = result
                    elif agent == "accounting": accounting  = result

    # ── 7. Synthesis ──────────────────────────────────────────────────────
    with (start_span(trace, "synthesis") if trace else _null_span()) as sp:
        try:
            synthesis = run_synthesizer_agent(
                company, equity, macro, opportunity,
                research, education, accounting,
                context=context, request_id=request_id,
            )
        except Exception as exc:
            logger.error(json.dumps({"event": "agent_error", "agent": "synthesizer",
                                     "error": str(exc), "request_id": request_id}))
            synthesis = SynthesisOutput()  # type: ignore[name-defined]

    synthesis = _normalize_synthesis(synthesis, company)

    # Signal ranking (unchanged)
    try:
        from .prioritization_utils import rank_signals
        focus = request.user_focus
        if synthesis.key_drivers_ranked:
            synthesis.key_drivers_ranked = rank_signals(
                synthesis.key_drivers_ranked,
                top_n=len(synthesis.key_drivers_ranked), focus=focus)
        if synthesis.key_risks_ranked:
            synthesis.key_risks_ranked = rank_signals(
                synthesis.key_risks_ranked,
                top_n=len(synthesis.key_risks_ranked),
                focus=focus if focus == "risk" else None)
        if synthesis.key_catalysts:
            synthesis.key_catalysts = rank_signals(
                synthesis.key_catalysts,
                top_n=len(synthesis.key_catalysts), focus=focus)
        if synthesis.macro_overlay and focus == "macro":
            synthesis.macro_overlay = rank_signals(
                synthesis.macro_overlay,
                top_n=len(synthesis.macro_overlay), focus=focus)
    except Exception:
        pass

    t_end = time.perf_counter()
    logger.info(json.dumps({"event": "analysis_duration", "request_id": request_id,
                            "duration": t_end - t_start}))

    # ── 8. Audit record — always emitted ─────────────────────────────────
    try:
        evidence_snapshot = {
            "known_facts_count":          len(getattr(context, "known_facts", [])),
            "has_market_snapshot":        getattr(context, "market_snapshot", None) is not None,
            "has_filings":                bool(getattr(context, "filings_context", [])),
            "historical_meanings_domains": list(getattr(context, "historical_meanings", {}).keys()),
            "scope_tenant":               getattr(scope, "tenant_id", "") if scope else "",
            "scope_user":                 getattr(scope, "user_id", "") if scope else "",
        }
        # Capture signal profile state for selected signals
        signal_profile_state: dict = {}
        try:
            from .learning import get_signal_profile
            question_tokens = (request.user_question or "").lower().split()[:3]
            for tok in question_tokens:
                if len(tok) > 4:
                    signal_profile_state[tok] = get_signal_profile(tok).get("signal_profile", "")
        except Exception:
            pass

        _model_name = ""
        try:
            from ..config import settings as _cfg
            _model_name = getattr(_cfg, "openai_model", "")
        except Exception:
            pass

        audit_record = AnalysisAuditRecord(
            request_id          = request_id,
            company             = company,
            user_question       = request.user_question or "",
            routing_decision    = routing_decision,
            evidence_sources    = selected_sources,
            evidence_snapshot   = evidence_snapshot,
            agents_used         = selected_agents,
            signal_profile_state = signal_profile_state,
            has_errors          = bool(agent_errors),
            trace_id            = trace.trace_id if trace else "",
            configuration       = {"model": _model_name,
                                   "enterprise": _ENTERPRISE},
            notes               = f"agent_errors: {agent_errors}" if agent_errors else "",
        )
        audit_store.record_analysis(audit_record)
    except Exception as exc:
        logger.warning(json.dumps({"event": "audit_emission_error",
                                   "error": str(exc), "request_id": request_id}))

    # Finish trace
    if _ENTERPRISE and trace:
        try:
            finish_trace(request_id)
        except Exception:
            pass

    logger.info(json.dumps({"event": "analysis_complete", "request_id": request_id,
                            "company": company, "agents_used": selected_agents,
                            "routing": routing_decision}))

    # ── Debug: confirm synthesis fields before response is returned ──────────
    print(f"FINAL VERDICT: {synthesis.final_verdict!r}")
    print(f"VERDICT REASONING: {synthesis.verdict_reasoning!r}")

    return AnalysisResponse(
        company    = company,
        request_id = request_id,
        equity     = equity,
        macro      = macro,
        opportunity = opportunity,
        research   = research,
        education  = education,
        accounting = accounting,
        synthesis  = synthesis,
        routing    = routing_decision,
        # Mirrors synthesis.verdict_reasoning at the top level for frontend
        # debugging — confirms the field survives serialization.
        debug_verdict_reasoning = synthesis.verdict_reasoning,
    )
