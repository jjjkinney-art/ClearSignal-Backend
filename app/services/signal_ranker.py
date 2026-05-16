"""
Signal ranking engine — Phase 3 of the decision-intelligence layer.

Responsibilities
----------------
1. Collect signals from all five specialist agent outputs.
2. Stamp source_agent on each signal.
3. Deduplicate signals that express the same underlying idea.
4. Merge similar signals, keeping the highest-impact version.
5. Score and rank by composite importance.
6. Split into top_signals / top_risks / secondary_signals / noise.
7. Build a CompressedThesis from the ranked signal set.

Ranking formula
---------------
    score = impact_score
            × agent_confidence
            × type_priority
            × direction_weight
            × thesis_sensitivity_weight

Where:
    agent_confidence         = the source agent's confidence field
    type_priority            = per-type weight (structural=1.0 … noise=0.0)
    direction_weight         = bullish/bearish=1.1, neutral=0.85
    thesis_sensitivity_weight= 0.70–1.25 based on stock-impact vs. descriptive content
                               (replaces the old recurrence_bonus, which is now folded
                               into impact_score during deduplication via _merge)

All scoring is deterministic — no LLM calls in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Pattern

from ..schemas import (
    CompanyContext,
    CompanyKnowledgeProfile,
    CompressedThesis,
    InvestmentThesis,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RetrievedEvidence,
    RiskProfile,
    Signal,
    ValuationView,
)

# ── Signal type priority weights ──────────────────────────────────────────────
# structural and catalyst signals are thesis-defining; noise is filtered out.
_TYPE_PRIORITY: Dict[str, float] = {
    "structural": 1.00,
    "catalyst":   0.90,
    "valuation":  0.85,
    "macro":      0.80,
    "risk":       0.75,
    "cyclical":   0.70,
    "quality":    0.65,
    "noise":      0.00,
}

# ── Direction weights ─────────────────────────────────────────────────────────
# Directional signals (bullish or bearish) matter more than neutral observations.
_DIRECTION_WEIGHT: Dict[str, float] = {
    "bullish": 1.10,
    "bearish": 1.10,
    "neutral": 0.85,
}

# ── Stopwords for similarity comparison ───────────────────────────────────────
_STOPWORDS: frozenset = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "will", "would", "may", "might", "could", "should",
    "its", "it", "this", "that", "as", "not", "no",
})

# ── Thesis-sensitivity scoring constants ──────────────────────────────────────
# Keywords that indicate a signal DIRECTLY affects stock price — via valuation,
# earnings, or macro transmission mechanisms.  Two or more hits → boost score.
_STOCK_IMPACT_KEYWORDS: frozenset = frozenset({
    "compress", "compression", "expansion", "multiple", "p/e", "pe",
    "earnings", "eps", "ebitda", "ebit", "margin", "margins",
    "rate", "rates", "discount rate", "interest rate",
    "fcf", "free cash flow", "buyback", "repurchase",
    "guidance", "revision", "estimate",
    "catalyst", "inflect", "derating", "rerating",
    "accelerat", "decelerat", "tariff",
    "pricing power", "yield", "duration",
    "leverage", "refinanc", "liquidity",
    "thesis", "valuation", "sensitivity",
    "revenue growth", "earnings growth",
    "dcf", "fair value", "price target",
    "beat", "miss", "headwind", "tailwind",
})

# Regex patterns that indicate a signal is a STATIC DESCRIPTIVE FACT rather
# than a stock-moving driver.  Presence of one or more → penalise score.
_DESCRIPTIVE_PHRASE_PATTERNS: List = [
    # "52% of revenue/sales/income" — revenue breakdown without impact
    re.compile(r'\b\d+\s*%\s+of\b', re.IGNORECASE),
    # "is/are/remains the [world's] largest/leading/major..." — generic market position
    # Uses [^\s]+ to allow qualifiers like "world's" between "the" and the adjective
    re.compile(
        r'\b(is|are|remains?)\s+(?:(?:a|an|the)\s+){1,2}(?:[^\s]+\s+){0,2}'
        r'(largest|leading|major|primary|key|dominant|top)\b',
        re.IGNORECASE,
    ),
    # "has been a leader/player/pioneer..." — historical position claim
    re.compile(
        r'\b(has|have)\s+(been|a|an|the)\s+(leader|player|pioneer|company)\b',
        re.IGNORECASE,
    ),
    # "founded/established/headquartered in..." — corporate background
    re.compile(r'\b(founded|established|headquartered)\s+in\b', re.IGNORECASE),
    # "operates in 175 countries" — scale fact
    re.compile(
        r'\boperates?\s+(in|across)\s+\d+\s+(countries|markets|regions)\b',
        re.IGNORECASE,
    ),
    # "employs 160,000" — headcount fact
    re.compile(r'\b(employs?|workforce\s+of)\s+[\d,]+\b', re.IGNORECASE),
]

# ── Forbidden phrases (Phase 5 + cognition refinements) ──────────────────────
# Terminal language that signals generic, non-analytical prose.
FORBIDDEN_PHRASES: frozenset = frozenset({
    # Original set
    "well positioned",
    "strong company",
    "industry leader",
    "robust ecosystem",
    "faces challenges",
    "investors should monitor",
    "remains to be seen",
    "time will tell",
    "broadly diversified",
    "key player",
    "wide moat company",
    # Extended: corporate / AI-compressed patterns (Refinement 5)
    "this indicates",
    "the company remains",
    "strong positioning",
    "well-positioned",
    "continues to benefit",
    "going forward",
    "moving forward",
    "in the long run",
    "it is clear that",
    "demonstrates the ability",
    "a testament to",
    "speaks to the",
    "headwinds and tailwinds",
    "remains well",
    "poised to benefit",
    "poised for growth",
    "solid fundamentals",
    "continues to grow",
    "positioned for",
    # Refinement 6 — synthetic construction filter (final pass)
    "remains compelling",
    "continues to expand",
    "continues to benefit",
    "supports higher valuation",
    "contributes to growth",
    "offsets pressure",
    "indicates strength",
    "strategically positioned",
    # Refinement 3 — elite phrase substitutions (final language quality pass)
    "provides a buffer",
    "strong margins",
    "impacting revenue",
    "premium valuation",
    "pricing power",
    # Cognition refinement — AI cadence + over-synthesised patterns
    "directionally constructive",
    "structurally repriced",
    "favorable backdrop",
    "asymmetric upside",
    "compelling opportunity",
    "significant upside potential",
    "constructive setup",
    "durable growth vector",
    "self-reinforcing",
    "stabilizing offset",
    "creates a favorable",
    "supports the narrative",
    "underpins the thesis",
    "validates the view",
    "confidence remains high",
    "confidence is high",
    "high conviction",
    # Confidence-language inflation patterns
    "strong conviction",
    "highly constructive",
    "conviction remains high",
    "elevated conviction",
    "well-supported thesis",
    "well supported thesis",
    "confidence remains elevated",
    "strongly constructive",
    # Hidden-process exposure patterns (Realism Refinement Phase)
    # These narrate internal analytical mechanics rather than making PM judgements.
    "signals converge",
    "evidence supports the thesis",
    "evidence supports",
    "analysis indicates",
    "multiple factors suggest",
    "directional alignment",
    "conviction remains high",
    "point in the same direction",
    "all point in the same",
    "leaving limited room for analytical",
    "limited room for analytical",
    "broadly constructive signals",
    "cross-agent convergence",
    "agent consensus",
    "agents agree",
    "agents register",
    "agent outputs",
    "agent confidence",
    "broadly aligned",
    "remains elevated",
    "confidence remains elevated",
    "suggests positive momentum",
    "suggests negative momentum",
    "analytically constructive",
    "constructive signal",
    "key analytical",
    # Phase D — Orchestration leakage (new): scoring/process language masquerading as analysis
    "signals are split",
    "signals diverge",
    "directional disagreement",
    "analytical disagreement",
    "confidence reduced because",
    "constructive vs cautious",
    "two forces affect",
    "affect the multiple in opposite",
    "in opposite directions",
    "evidence count",
    # Phase D — Completeness bias: symmetric conditional endings that avoid taking a view
    "depending on which scenario",
    "whichever prevails",
    "whichever dominates",
    "either scenario",
    # Phase D — Understated confidence bans: overselling language that fails the PM test
    "highly compelling",
    "strongly bullish",
    "strongly bearish",
    "high-conviction opportunity",
    "exceptional opportunity",
    "exceptional investment case",
    "robust thesis",
    "unambiguously bullish",
    "unambiguously positive",
    # Phase E — Explicit conviction language bans: implicit PM restraint over stated conviction
    "conviction is high",
    "conviction is elevated",
    "analysis converges",
    "analysis converges on",
    "all factors point",
    "all signals point",
    "therefore investors should",
    "this creates a mixed outlook",
    "this supports the investment thesis",
    "this confirms the thesis",
    "this validates the thesis",
    "the thesis is well-supported",
    "the thesis is supported",
    "the investment case is strong",
    "this means the stock",
    "therefore the stock",
})

# ── Causal language scoring modifiers (Refinement 4) ──────────────────────────
# Signals with explicit causal verbs are more analytically useful than
# purely descriptive signals and score higher in the ranking engine.
_CAUSAL_VERBS: frozenset = frozenset({
    "compress", "compresses", "compressed",
    "drive", "drives", "drove",
    "expand", "expands", "expanded",
    "threaten", "threatens", "threatened",
    "erode", "erodes", "eroded",
    "support", "supports", "supported",
    "amplify", "amplifies", "amplified",
    "accelerate", "accelerates", "accelerated",
    "reduce", "reduces", "reduced",
    "increase", "increases", "increased",
    "impact", "impacts", "impacted",
    "weigh", "weighs", "weighed",
    "squeeze", "squeezes", "squeezed",
    "boost", "boosts", "boosted",
    "limit", "limits", "limited",
    "pressure", "pressures", "pressured",
    "offset", "offsets", "offsetting",
    "constrain", "constrains", "constrained",
    "widen", "widens", "widened",
    "narrow", "narrows", "narrowed",
})

# Descriptive-stall verbs that signal generic/background statements rather than
# causal mechanisms.  Penalised slightly in scoring.
_DESCRIPTIVE_STALLS: frozenset = frozenset({
    "remains", "maintain", "maintains",
    "continues", "is considered", "has been",
    "has historically", "positioned", "known for",
    "recognized", "is known",
})


# ── Causal dimension system (Refinement 3: signal orthogonality) ──────────────
# Each signal is classified into a causal dimension.  Top signals that share
# a dimension express the same underlying mechanism and should be collapsed.
# This ensures top_signals represent genuinely different causal forces.

_SIGNAL_CAUSAL_DIMENSIONS: Dict[str, List[str]] = {
    "valuation":          ["multiple", "p/e", "pe", "dcf", "fair value", "price target",
                           "valuation", "discount", "premium", "multiples", "rerating",
                           "derating", "priced in", "priced at"],
    "macro":              ["rate", "rates", "fed", "inflation", "gdp", "macro", "yield",
                           "duration", "currency", "fx", "monetary", "fiscal", "recession",
                           "cycle", "credit", "spread", "treasury"],
    "regulatory":         ["antitrust", "regulatory", "regulation", "legal", "eu", "ftc",
                           "doj", "probe", "lawsuit", "compliance", "policy", "government",
                           "legislation", "tax"],
    "operational":        ["margin", "revenue", "earnings", "eps", "ebitda", "guidance",
                           "unit", "volume", "sales", "growth", "operating", "segment",
                           "product", "service", "launch", "cycle"],
    "capital_allocation": ["buyback", "repurchase", "dividend", "debt", "leverage", "cash",
                           "fcf", "free cash flow", "balance sheet", "capital return",
                           "refinanc", "net cash", "net debt"],
    "competitive":        ["market share", "competition", "competitor", "moat", "switching",
                           "lock-in", "ecosystem", "platform", "network effect"],
    "behavioral":         ["sentiment", "institutional", "positioning", "momentum",
                           "short", "retail", "flows", "options"],
}

_DIMENSION_ORDER: List[str] = [
    "valuation", "macro", "regulatory", "operational",
    "capital_allocation", "competitive", "behavioral",
]


def _get_signal_dimension(signal_text: str) -> str:
    """Classify a signal into its primary causal dimension.

    Returns the first matching dimension from ``_SIGNAL_CAUSAL_DIMENSIONS``,
    following ``_DIMENSION_ORDER`` priority.  Falls back to "operational" when
    no keywords match (operational mechanics are the default analytical frame).
    """
    lower = signal_text.lower()
    for dim in _DIMENSION_ORDER:
        keywords = _SIGNAL_CAUSAL_DIMENSIONS[dim]
        if any(kw in lower for kw in keywords):
            return dim
    return "operational"


def _enforce_signal_orthogonality(signals: List["Signal"]) -> List["Signal"]:  # type: ignore[name-defined]
    """Ensure top signals represent different causal dimensions.

    When two or more signals share the same causal dimension, keeps only the
    highest-scored one from each dimension.  This prevents the top signal
    list from restating the same mechanism (e.g. three Services-margin signals
    rephrased differently).

    The output list preserves the original score ordering within allowed slots.
    Expects input already sorted highest-score first.
    """
    seen_dimensions: Dict[str, int] = {}  # dimension → count
    result: List["Signal"] = []           # type: ignore[name-defined]

    for sig in signals:
        dim = _get_signal_dimension(sig.signal)
        count = seen_dimensions.get(dim, 0)
        # Allow at most 1 signal per dimension in top positions
        if count < 1:
            result.append(sig)
            seen_dimensions[dim] = count + 1
        # Skip: same dimension already represented

    return result


def _are_same_dimension_duplicates(s1: "Signal", s2: "Signal") -> bool:  # type: ignore[name-defined]
    """Return True when two signals share a dimension AND have moderate overlap.

    Uses a lower Jaccard threshold (0.30 vs default 0.45) for same-dimension
    signals, since they are more likely to restate the same mechanism even with
    different surface wording.
    """
    if _get_signal_dimension(s1.signal) != _get_signal_dimension(s2.signal):
        return False
    return _jaccard(s1.signal, s2.signal) >= 0.30


def _causal_score_modifier(signal: "Signal") -> float:  # type: ignore[name-defined]
    """Return a 0.88–1.12 multiplier based on causal language presence.

    Signals with specific causal verbs (compresses, drives, threatens…) receive
    a 12% boost because they express a mechanism → P&L transmission chain.
    Purely descriptive signals (remains, maintains, positioned…) without any
    causal verb receive an 12% penalty.
    """
    text_lower = signal.signal.lower()
    words = set(re.findall(r"\b\w+\b", text_lower))
    has_causal      = bool(words & _CAUSAL_VERBS)
    has_descriptive = bool(words & _DESCRIPTIVE_STALLS)

    if has_causal and not has_descriptive:
        return 1.12   # Reward: explicit causal mechanism
    if has_descriptive and not has_causal:
        return 0.88   # Penalise: purely descriptive
    return 1.00       # Neutral: mixed or neither


# ── Dataclass for ranked output ───────────────────────────────────────────────

@dataclass
class RankedSignalSet:
    """Output of rank_signals().

    Attributes
    ----------
    top_signals      : Up to 3 highest-scoring non-risk signals (bullish/neutral/mixed).
    top_risks        : Up to 4 bearish/risk-type signals ranked by severity.
    secondary_signals: Remaining non-noise signals (up to 6).
    noise            : Signals scored at 0 or typed as noise — filtered from output.
    all_ranked       : All non-noise signals in descending score order.
    """
    top_signals:       List[Signal] = field(default_factory=list)
    top_risks:         List[Signal] = field(default_factory=list)
    secondary_signals: List[Signal] = field(default_factory=list)
    noise:             List[Signal] = field(default_factory=list)
    all_ranked:        List[Signal] = field(default_factory=list)


# ── Similarity / deduplication helpers ───────────────────────────────────────

def _tokenize(text: str) -> Set[str]:
    """Lowercase word tokens with stopwords removed."""
    words = re.findall(r"\b\w+\b", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _jaccard(a: str, b: str) -> float:
    """Jaccard similarity between the word sets of two strings."""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _are_duplicates(s1: Signal, s2: Signal, threshold: float = 0.45) -> bool:
    """Return True if two signals express the same idea."""
    return _jaccard(s1.signal, s2.signal) >= threshold


def _merge(primary: Signal, secondary: Signal, recurrence_bonus: float) -> Signal:
    """Merge secondary into primary, boosting impact_score by recurrence."""
    merged_score = min(1.0, primary.impact_score * (1.0 + recurrence_bonus))
    # Combine importance_reason text if both have content
    combined_reason = primary.importance_reason
    if secondary.importance_reason and secondary.importance_reason not in combined_reason:
        combined_reason = f"{combined_reason} {secondary.importance_reason}".strip()
    # Union evidence refs
    combined_refs = list(dict.fromkeys(primary.evidence_refs + secondary.evidence_refs))
    return Signal(
        signal=primary.signal,
        explanation=primary.explanation or secondary.explanation,
        impact_score=merged_score,
        confidence=max(primary.confidence, secondary.confidence),
        signal_type=primary.signal_type,
        time_horizon=primary.time_horizon,
        direction=primary.direction,
        source_agent=f"{primary.source_agent}+{secondary.source_agent}"
            if secondary.source_agent and secondary.source_agent != primary.source_agent
            else primary.source_agent,
        evidence_refs=combined_refs,
        importance_reason=combined_reason,
    )


# ── Score computation ─────────────────────────────────────────────────────────

def _score(signal: Signal, agent_confidence: float) -> float:
    """Compute a composite ranking score for a single signal.

    Formula
    -------
        score = impact_score
                × agent_confidence
                × type_priority
                × direction_weight
                × thesis_sensitivity_weight

    thesis_sensitivity_weight is 0.70–1.25 based on whether the signal text
    contains stock-moving mechanisms (earnings, multiple compression, macro
    transmission) vs. static descriptive facts (revenue breakdowns, generic
    market-position claims).  This ensures that "higher rates compress AAPL's
    P/E multiple" ranks above "iPhone is 52% of revenue" even when both carry
    the same LLM-assigned impact_score.
    """
    type_w    = _TYPE_PRIORITY.get(signal.signal_type, 0.5)
    dir_w     = _DIRECTION_WEIGHT.get(signal.direction, 0.85)
    thesis_w  = _thesis_sensitivity_score(signal.signal)
    causal_w  = _causal_score_modifier(signal)
    return signal.impact_score * agent_confidence * type_w * dir_w * thesis_w * causal_w


# ── Thesis-sensitivity scoring ────────────────────────────────────────────────

def _thesis_sensitivity_score(signal_text: str) -> float:
    """Return a thesis-sensitivity multiplier for a signal's text.

    Signals that directly affect stock price via valuation, earnings, or
    macro transmission mechanisms receive a multiplier > 1.0.  Static
    descriptive facts that are informative but do not directly move the
    stock receive a multiplier < 1.0.

    The multiplier is applied inside ``_score()`` so that thesis-sensitive
    signals rank above same-type descriptive signals regardless of the
    LLM's raw ``impact_score`` assignment.

    Multiplier table
    ----------------
    ≥ 2 stock-impact keyword hits                  → 1.25  (strong boost)
    1 stock-impact hit, 0 descriptive pattern hits → 1.10  (moderate boost)
    0 hits on either side                          → 1.00  (neutral)
    1 descriptive hit, 0 impact hits               → 0.85  (mild penalty)
    ≥ 2 descriptive pattern hits                   → 0.70  (strong penalty)

    Returns a value in [0.70, 1.25].
    """
    if not signal_text:
        return 1.0

    lower = signal_text.lower()

    # Count stock-impact keyword hits (substring match, case-insensitive via lower())
    impact_hits = sum(1 for kw in _STOCK_IMPACT_KEYWORDS if kw in lower)

    # Count descriptive-pattern hits
    descriptive_hits = sum(
        1 for p in _DESCRIPTIVE_PHRASE_PATTERNS if p.search(signal_text)
    )

    if impact_hits >= 2:
        return 1.25   # Strong stock-impact signal — boost
    elif impact_hits == 1 and descriptive_hits == 0:
        return 1.10   # Moderate stock-impact — slight boost
    elif descriptive_hits >= 2:
        return 0.70   # Strongly descriptive — penalise
    elif descriptive_hits == 1 and impact_hits == 0:
        return 0.85   # Somewhat descriptive — mild penalty
    else:
        return 1.00   # Neutral or mixed


# ── Forbidden phrase detection ────────────────────────────────────────────────

def detect_forbidden_phrases(text: str) -> List[str]:
    """Return list of forbidden phrases found in *text*.

    Used by the depth guard and synthesis checker to enforce causal,
    specific language in thesis output.
    """
    lower = text.lower()
    return [phrase for phrase in FORBIDDEN_PHRASES if phrase in lower]


# ── Signal collection ─────────────────────────────────────────────────────────

def _collect_signals(
    valuation: ValuationView,
    macro: MacroSensitivity,
    risk: RiskProfile,
    market: MarketContext,
    quality: QualityAssessment,
) -> List[Tuple[Signal, float]]:
    """Collect (signal, agent_confidence) pairs from all agents.

    Stamps source_agent on each signal.  Skips agents with zero confidence
    or empty signal lists.

    Returns
    -------
    List of (Signal, agent_confidence) tuples ready for deduplication/ranking.
    """
    collected: List[Tuple[Signal, float]] = []

    agent_map = [
        ("valuation", valuation.signals, valuation.confidence),
        ("macro",     macro.signals,     macro.confidence),
        ("risk",      risk.signals,      risk.confidence),
        ("market",    market.signals,    market.confidence),
        ("quality",   quality.signals,   quality.confidence),
    ]

    for agent_name, signals, confidence in agent_map:
        if confidence <= 0.0:
            continue
        for sig in signals:
            stamped = Signal(
                signal=sig.signal,
                explanation=sig.explanation,
                impact_score=sig.impact_score,
                confidence=sig.confidence if sig.confidence > 0 else confidence,
                signal_type=sig.signal_type,
                time_horizon=sig.time_horizon,
                direction=sig.direction,
                source_agent=agent_name,
                evidence_refs=sig.evidence_refs,
                importance_reason=sig.importance_reason,
            )
            collected.append((stamped, confidence))

    return collected


# ── Deduplication ─────────────────────────────────────────────────────────────

def _deduplicate(
    pairs: List[Tuple[Signal, float]],
    recurrence_bonus: float = 0.20,
) -> List[Tuple[Signal, float]]:
    """Merge duplicate signals and apply recurrence bonus.

    Two signals are duplicates when:
    - Jaccard similarity ≥ 0.45 (standard threshold), OR
    - They share a causal dimension AND Jaccard ≥ 0.30 (same-dimension merging)

    The lower threshold for same-dimension signals ensures that "Services margins
    expand," "Services recurring margin profile," and "Services margin durability"
    collapse into a single structural mechanism rather than appearing as three
    separate top signals.

    Returns
    -------
    Deduplicated list of (Signal, agent_confidence) pairs.
    """
    if not pairs:
        return []

    # Sort by raw score descending so higher-quality signals are kept as primary
    scored = sorted(pairs, key=lambda p: _score(p[0], p[1]), reverse=True)
    merged: List[Tuple[Signal, float]] = []

    for sig, conf in scored:
        matched = False
        for i, (existing, existing_conf) in enumerate(merged):
            if _are_duplicates(sig, existing) or _are_same_dimension_duplicates(sig, existing):
                # Merge into existing (primary), boosting its score
                merged[i] = (_merge(existing, sig, recurrence_bonus), existing_conf)
                matched = True
                break
        if not matched:
            merged.append((sig, conf))

    return merged


# ── Main ranking function ─────────────────────────────────────────────────────

def rank_signals(
    valuation: ValuationView,
    macro: MacroSensitivity,
    risk: RiskProfile,
    market: MarketContext,
    quality: QualityAssessment,
    company: Optional[CompanyContext] = None,
    profile: Optional[CompanyKnowledgeProfile] = None,
) -> RankedSignalSet:
    """Collect, deduplicate, and rank signals from all five specialist agents.

    Parameters
    ----------
    valuation : Output from run_valuation_agent().
    macro     : Output from run_macro_agent().
    risk      : Output from run_risk_agent().
    market    : Output from run_market_agent().
    quality   : Output from run_quality_agent().
    company   : Optional — used for profile-keyword boosting.
    profile   : Optional — business_model_keywords boost structural signals.

    Returns
    -------
    RankedSignalSet with top_signals, top_risks, secondary_signals, noise.
    """
    # Collect and stamp source_agent
    pairs = _collect_signals(valuation, macro, risk, market, quality)

    print(f"[DIAG] SIGNAL RANKER: collected={len(pairs)} raw signals")

    if not pairs:
        return RankedSignalSet()

    # Deduplicate
    deduped = _deduplicate(pairs)
    print(f"[DIAG] SIGNAL RANKER: after_dedup={len(deduped)}")

    # Score and sort
    scored_sigs: List[Tuple[Signal, float]] = sorted(
        deduped,
        key=lambda p: _score(p[0], p[1]),
        reverse=True,
    )

    # Boost structural signals that mention profile keywords
    if profile and profile.business_model_keywords:
        kw_lower = {k.lower() for k in profile.business_model_keywords}
        boosted: List[Tuple[Signal, float]] = []
        for sig, conf in scored_sigs:
            sig_lower = sig.signal.lower()
            if any(kw in sig_lower for kw in kw_lower):
                # Boost by 10% for company-specific keyword presence
                boosted_sig = Signal(
                    **{**sig.model_dump(), "impact_score": min(1.0, sig.impact_score * 1.10)}
                )
                boosted.append((boosted_sig, conf))
            else:
                boosted.append((sig, conf))
        # Re-sort after boosting
        scored_sigs = sorted(boosted, key=lambda p: _score(p[0], p[1]), reverse=True)

    # Separate noise
    non_noise = [(s, c) for s, c in scored_sigs if s.signal_type != "noise" and _score(s, c) > 0]
    noise_sigs = [s for s, c in scored_sigs if s.signal_type == "noise" or _score(s, c) == 0]

    all_ranked = [s for s, _ in non_noise]

    # Split into top_signals (non-risk directions) and top_risks (bearish/risk-type)
    bullish_neutral = [s for s in all_ranked if s.direction in ("bullish", "neutral")]
    bearish_risk    = [s for s in all_ranked if s.direction == "bearish"
                       or s.signal_type == "risk"]

    # top_signals: up to 3 from bullish/neutral pool, enforcing causal orthogonality
    # Orthogonality pass: draw from a wider candidate pool (up to 6) so we can
    # find signals from genuinely different causal dimensions after filtering.
    top_signals_candidates = bullish_neutral[:6]
    top_signals = _enforce_signal_orthogonality(top_signals_candidates)[:3]

    # top_risks: up to 4 from bearish/risk pool (orthogonality applied at 2 per dim)
    top_risks = bearish_risk[:4]

    # secondary_signals: everything else, up to 6
    used_ids = {id(s) for s in top_signals + top_risks}
    secondary = [s for s in all_ranked if id(s) not in used_ids][:6]

    result = RankedSignalSet(
        top_signals=top_signals,
        top_risks=top_risks,
        secondary_signals=secondary,
        noise=noise_sigs,
        all_ranked=all_ranked,
    )

    print(
        f"[DIAG] SIGNAL RANKER: "
        f"top_signals={len(top_signals)} "
        f"top_risks={len(top_risks)} "
        f"secondary={len(secondary)} "
        f"noise={len(noise_sigs)}"
    )
    return result


# ── Thesis compression ────────────────────────────────────────────────────────

def compress_thesis(
    thesis: InvestmentThesis,
    ranked: RankedSignalSet,
) -> CompressedThesis:
    """Build a CompressedThesis from a ranked signal set and synthesised thesis.

    Deterministic — no LLM.  Constructs all fields from the already-available
    thesis text and ranked signals so that the compressed view is always
    consistent with the full thesis.

    Parameters
    ----------
    thesis : The fully synthesised InvestmentThesis.
    ranked : Output of rank_signals() for this thesis.

    Returns
    -------
    CompressedThesis ready to be attached to thesis.compressed_thesis.
    """
    # direct_answer — prefer explicit field; fall back to first sentence of conclusion
    direct_answer = thesis.direct_answer or ""
    if not direct_answer and thesis.conclusion:
        # Take the first 1-2 sentences of the conclusion
        sentences = re.split(r"(?<=[.!?])\s+", thesis.conclusion.strip())
        direct_answer = " ".join(sentences[:2])

    # top_signals for compressed view — use ranked top_signals first
    ct_signals = (ranked.top_signals[:3]
                  if ranked.top_signals
                  else ranked.all_ranked[:3])

    # one_sentence_thesis — first sentence of bull_thesis + confidence qualifier
    one_sent = ""
    if thesis.bull_thesis:
        first_bull = re.split(r"(?<=[.!?])\s+", thesis.bull_thesis.strip())[0]
        conf_qualifier = (
            "high conviction" if thesis.confidence_score >= 0.75
            else "moderate conviction" if thesis.confidence_score >= 0.55
            else "low conviction"
        )
        one_sent = f"{first_bull} [{conf_qualifier}, {thesis.confidence_score:.0%}]"

    # why_it_matters — from top signal's importance_reason, or top_signal.signal
    why_it_matters = ""
    if ct_signals:
        top = ct_signals[0]
        why_it_matters = top.importance_reason or top.explanation or top.signal

    # what_changes_this_view — from thesis field (already ranked by synthesizer)
    what_changes = (thesis.what_changes_the_thesis[:4]
                    if thesis.what_changes_the_thesis
                    else [])

    return CompressedThesis(
        direct_answer=direct_answer,
        top_signals=ct_signals,
        one_sentence_thesis=one_sent,
        why_it_matters=why_it_matters,
        what_changes_this_view=what_changes,
    )


# ── Forbidden phrase checker ──────────────────────────────────────────────────

def check_forbidden_phrases(thesis: InvestmentThesis) -> List[str]:
    """Return [QUALITY] warning strings for any forbidden phrases found.

    Checks all major prose fields: bull_thesis, bear_thesis, conclusion,
    direct_answer, confidence_reasoning, valuation_view, macro_sensitivity.
    Returns an empty list when the thesis uses causal, specific language.
    """
    warnings: List[str] = []
    fields_to_check = {
        "bull_thesis":          thesis.bull_thesis,
        "bear_thesis":          thesis.bear_thesis,
        "conclusion":           thesis.conclusion,
        "direct_answer":        thesis.direct_answer,
        "confidence_reasoning": thesis.confidence_reasoning,
        "valuation_view":       thesis.valuation_view,
        "macro_sensitivity":    thesis.macro_sensitivity,
    }
    for field_name, text in fields_to_check.items():
        if not text:
            continue
        hits = detect_forbidden_phrases(text)
        if hits:
            warnings.append(
                f"[QUALITY] Forbidden generic phrase(s) in {field_name}: "
                + ", ".join(f'"{p}"' for p in hits)
                + " — replace with causal, company-specific language."
            )
    return warnings


# ── Signal overlap detection ──────────────────────────────────────────────────

def detect_signal_overlap(
    ranked: RankedSignalSet,
    threshold: float = 0.45,
) -> List[str]:
    """Detect semantically overlapping signals that survived deduplication.

    Checks all non-noise signals (top_signals + top_risks + secondary_signals)
    for pairs that express the same underlying idea but were not merged — e.g.
    because they ended up in opposite directional pools.

    Parameters
    ----------
    ranked    : Output of rank_signals().
    threshold : Jaccard similarity above which signals are considered overlapping.
                Default 0.45 matches the deduplication threshold.

    Returns
    -------
    List of [OVERLAP] warning strings, one per detected pair.  Empty list if no
    overlap is found.
    """
    all_sigs = ranked.top_signals + ranked.top_risks + ranked.secondary_signals
    warnings: List[str] = []

    for i in range(len(all_sigs)):
        for j in range(i + 1, len(all_sigs)):
            s1, s2 = all_sigs[i], all_sigs[j]
            sim = _jaccard(s1.signal, s2.signal)
            if sim >= threshold:
                warnings.append(
                    f"[OVERLAP] Signal similarity={sim:.2f}: "
                    f"'{s1.signal[:55]}…' ({s1.signal_type}/{s1.direction}) "
                    f"vs '{s2.signal[:55]}…' ({s2.signal_type}/{s2.direction}) "
                    f"— consider merging these concepts."
                )

    return warnings


# ── Confidence reasoning builder ──────────────────────────────────────────────

def build_confidence_reasoning(
    agent_confidences: Dict[str, float],
    ranked: Optional[RankedSignalSet],
    evidence_count: int,
    original_reasoning: str = "",
) -> str:
    """Build PM-note confidence reasoning without exposing analytical process.

    Produces analyst-grade uncertainty language that frames confidence in
    terms of what IS resolved and what IS NOT — without mentioning agent
    names, signal counts, or internal process mechanics.

    Strict output rules
    -------------------
    - NEVER mention agent names ("macro agent", "risk analysis", "valuation agent")
    - NEVER cite raw percentages or signal counts
    - NEVER use process-narration ("signals converge", "all point in the same direction")
    - ALWAYS frame uncertainty as a market/positioning question
    - ALWAYS name the specific unresolved variable, not the process gap

    Output examples (target)
    ------------------------
    HIGH CONFIDENCE:
      "The investment case reads cleanly here — the mechanism is consistent
       with what drives earnings and what the market is paying for. Residual
       uncertainty is timing, not direction."

    MACRO UNCERTAIN:
      "The macro transmission is the main unresolved variable. Whether rates
       stay structurally restrictive long enough to matter for this multiple
       is a genuinely hard call — that is where the conviction discount sits."

    SPLIT SIGNALS:
      "The investment picture is genuinely two-sided at this stage. The bull
       and bear cases are more evenly matched than a clean call requires."

    THIN EVIDENCE:
      "Limited evidence coverage means this position carries more uncertainty
       than the score reflects — the framework is sound, the data is thin."

    Parameters
    ----------
    agent_confidences : Mapping of agent name → confidence float (0.0–1.0).
    ranked            : Ranked signal set from rank_signals(); may be None.
    evidence_count    : Total evidence items feeding the synthesis.
    original_reasoning: LLM-generated reasoning to fall back on.

    Returns
    -------
    A 1–3 sentence PM-note uncertainty explanation.
    """
    if not agent_confidences:
        return (
            original_reasoning
            or "The evidence base is too thin to assign a conviction level here."
        )

    confs        = list(agent_confidences.values())
    mean_conf    = sum(confs) / len(confs)
    conf_range   = max(confs) - min(confs) if len(confs) > 1 else 0.0
    macro_conf   = agent_confidences.get("macro",   1.0)
    risk_conf    = agent_confidences.get("risk",    1.0)
    quality_conf = agent_confidences.get("quality", 1.0)

    # Signal direction analysis (no counts surfaced — just the lean)
    all_sigs  = (ranked.all_ranked if ranked and ranked.all_ranked else [])
    bullish_n = sum(1 for s in all_sigs if s.direction == "bullish")
    bearish_n = sum(1 for s in all_sigs if s.direction == "bearish")
    total_n   = len(all_sigs)
    dir_share = max(bullish_n, bearish_n) / total_n if total_n > 0 else 0.5

    # ── Classify the dominant uncertainty type ────────────────────────────────
    macro_uncertain   = macro_conf   < 0.55
    risk_uncertain    = risk_conf    < 0.55
    quality_uncertain = quality_conf < 0.55
    double_uncertain  = macro_uncertain and risk_uncertain
    direction_split   = total_n >= 3 and dir_share < 0.60
    thin_evidence     = evidence_count < 4
    high_confidence   = mean_conf >= 0.70 and conf_range < 0.20 and not direction_split

    parts: List[str] = []

    # ── Case 1: Thin evidence — always flag first ─────────────────────────────
    if thin_evidence:
        parts.append(
            "Limited evidence coverage means this position carries more "
            "uncertainty than the score reflects — the framework is sound, "
            "the data is thin."
        )

    # ── Case 2: Double uncertainty (macro + risk both weak) ───────────────────
    elif double_uncertain:
        parts.append(
            "The macro backdrop and downside risk profile both carry real "
            "unresolved questions here."
        )
        if direction_split:
            parts.append(
                "The investment picture does not have a strong directional lean "
                "at this stage — position sizing matters more than conviction level."
            )
        else:
            parts.append(
                "The conviction discount reflects what is genuinely hard to call, "
                "not an analytical gap."
            )

    # ── Case 3: Macro uncertainty dominant ───────────────────────────────────
    elif macro_uncertain:
        parts.append(
            "The macro transmission is the main unresolved variable."
        )
        if not direction_split:
            parts.append(
                "The fundamental case is relatively clear; the timing call "
                "is harder — and that is where the conviction discount sits."
            )
        else:
            parts.append(
                "With the macro path unclear and the investment picture "
                "directionally mixed, the thesis requires a catalyst, "
                "not just time."
            )

    # ── Case 4: Risk uncertainty dominant ────────────────────────────────────
    elif risk_uncertain:
        parts.append(
            "The risk profile has real open questions that are not fully "
            "resolved by the available evidence."
        )
        parts.append(
            "The conviction discount reflects the downside exposure that "
            "is genuinely hard to size — not analytical hesitancy."
        )

    # ── Case 5: Significant cross-view divergence ─────────────────────────────
    elif conf_range >= 0.30:
        parts.append(
            "The analytical picture has genuine divergence across the "
            "investment framework — the uncertainty is real."
        )
        if direction_split:
            parts.append(
                "The investment thesis does not have a strong directional lean; "
                "the bull and bear cases are more evenly matched than a "
                "clean call requires."
            )

    # ── Case 6: Direction split only ─────────────────────────────────────────
    elif direction_split:
        parts.append(
            "The investment picture is genuinely two-sided at this stage."
        )
        parts.append(
            "The bull and bear cases are more evenly matched than a clean "
            "call requires — this is a balanced risk/reward, not a "
            "high-conviction position."
        )

    # ── Case 7: High confidence — clear case ─────────────────────────────────
    elif high_confidence:
        parts.append(
            "The investment case reads cleanly here — the mechanism is "
            "consistent with what drives earnings and what the market is "
            "paying for."
        )
        if quality_uncertain:
            parts.append(
                "The residual uncertainty is on the quality of the business "
                "model in a stress scenario, not the near-term direction."
            )
        else:
            parts.append(
                "Residual uncertainty is timing, not direction."
            )

    # ── Case 8: Moderate, broad uncertainty ──────────────────────────────────
    else:
        parts.append(
            "The thesis is directionally clear but not without residual risk."
        )
        if mean_conf < 0.65:
            parts.append(
                "Conviction sits at a moderate level — the mechanism is sound, "
                "the outcome range is wider than ideal."
            )

    # ── If the LLM produced something genuinely better, prefer it ────────────
    # Only use the LLM reasoning if we couldn't build a meaningful PM note
    if not parts and original_reasoning:
        return original_reasoning

    # Cap at 2 sentences for readability (polisher strips counts/percentages)
    return " ".join(parts[:2])


# ── Confidence realism cap (Refinement 1) ────────────────────────────────────

def compute_confidence_realism_cap(
    raw_score:      float,
    macro_conf:     float,
    risk_conf:      float,
    quality_conf:   float,
    evidence_count: int,
    ranked:         Optional[RankedSignalSet] = None,
) -> Tuple[float, List[str]]:
    """Apply conservative confidence caps based on uncertainty flags.

    Real institutional conviction accounts for unresolved variables.
    An 80% confidence score is only defensible when macro, risk, AND
    the evidence base all point clearly in one direction.

    Cap table (applied cumulatively — the tightest binding cap wins):
    ─────────────────────────────────────────────────────────────────
    macro_conf < 0.50           → cap at 0.72   (macro uncertain)
    risk_conf < 0.50            → cap at 0.72   (downside exposure unresolved)
    macro AND risk both < 0.55  → cap at 0.68   (double uncertainty)
    evidence_count < 3          → cap at 0.65   (thin evidence base)
    cross-agent spread ≥ 0.35   → cap at 0.74   (agents disagree)
    signal direction split       → cap at 0.73   (directional ambiguity)

    Returns
    -------
    (adjusted_score, list_of_uncertainty_factors_that_triggered)
    """
    score = float(raw_score)
    caps:  List[Tuple[float, str]] = []

    # ── Macro uncertainty ─────────────────────────────────────────────────────
    if macro_conf < 0.50:
        caps.append((0.72, "macro outlook uncertain"))
    elif macro_conf < 0.60:
        caps.append((0.76, "macro environment unclear"))

    # ── Risk uncertainty ──────────────────────────────────────────────────────
    if risk_conf < 0.50:
        caps.append((0.72, "downside exposure unresolved"))
    elif risk_conf < 0.60:
        caps.append((0.76, "risk profile partially uncertain"))

    # ── Double uncertainty: macro + risk both weak ────────────────────────────
    if macro_conf < 0.55 and risk_conf < 0.55:
        caps.append((0.68, "macro and risk uncertainty compound"))

    # ── Sparse evidence ───────────────────────────────────────────────────────
    if evidence_count < 3:
        caps.append((0.65, "evidence base too thin to underwrite"))
    elif evidence_count < 5:
        caps.append((0.74, "limited evidence coverage"))

    # ── Cross-agent spread ────────────────────────────────────────────────────
    if quality_conf < 0.50:
        caps.append((0.74, "business quality uncertain"))

    # ── Signal direction split ────────────────────────────────────────────────
    if ranked is not None and ranked.all_ranked:
        all_sigs  = ranked.all_ranked
        bullish_n = sum(1 for s in all_sigs if s.direction == "bullish")
        bearish_n = sum(1 for s in all_sigs if s.direction == "bearish")
        total_n   = max(len(all_sigs), 1)
        # Split: neither side > 60% = genuinely ambiguous
        dominant_share = max(bullish_n, bearish_n) / total_n
        if dominant_share < 0.60:
            caps.append((0.73, "signal direction is genuinely split"))

    if not caps:
        return score, []

    # Take the tightest applicable cap
    effective_cap = min(c for c, _ in caps)
    triggered     = [reason for c, reason in caps if c == effective_cap]

    adjusted = min(score, effective_cap)
    return round(adjusted, 4), triggered


# ── Evidence reference propagation ────────────────────────────────────────────

def _ref_label(ev: RetrievedEvidence) -> str:
    """Format an evidence item as a short reference label for evidence_refs.

    Format: "[{source}] {title[:60]}"
    Preserved as a structured string so the frontend can parse source type.
    """
    return f"[{ev.source}] {ev.title[:60]}"


def propagate_evidence_refs(
    signals: List[Signal],
    evidence: List[RetrievedEvidence],
    min_overlap: int = 2,
) -> List[Signal]:
    """Infer evidence_refs for signals that have none.

    For each signal with an empty evidence_refs list, tokenizes the signal
    text and checks every evidence item (title + summary) for keyword overlap.
    When at least *min_overlap* non-stopword tokens match, the evidence
    item's reference label is added to the signal's evidence_refs.

    Signals that already have evidence_refs set by the LLM are left untouched
    (the LLM's explicit citation is more precise than keyword inference).

    Modifies signals in-place (returns the same list for convenience).

    Parameters
    ----------
    signals    : List of Signal objects to annotate.
    evidence   : Full pool of RetrievedEvidence from the pipeline.
    min_overlap: Minimum shared-token count to count as a match (default 2).

    Returns
    -------
    The same list with evidence_refs populated on previously-empty signals.
    """
    if not evidence:
        return signals

    # Pre-tokenise each evidence item once for efficiency
    ev_tokens: List[Tuple[RetrievedEvidence, Set[str]]] = []
    for ev in evidence:
        combined = f"{ev.title} {ev.summary}"
        tokens = _tokenize(combined)
        ev_tokens.append((ev, tokens))

    updated: List[Signal] = []
    for sig in signals:
        if sig.evidence_refs:
            # LLM already populated refs — honour them
            updated.append(sig)
            continue

        sig_tokens = _tokenize(sig.signal)
        if not sig_tokens:
            updated.append(sig)
            continue

        inferred_refs: List[str] = []
        for ev, ev_toks in ev_tokens:
            overlap = len(sig_tokens & ev_toks)
            if overlap >= min_overlap:
                inferred_refs.append(_ref_label(ev))

        if inferred_refs:
            # Build a new Signal with evidence_refs populated
            if hasattr(sig, "model_copy"):
                sig = sig.model_copy(update={"evidence_refs": inferred_refs})
            else:
                sig = sig.copy(update={"evidence_refs": inferred_refs})  # type: ignore[attr-defined]

        updated.append(sig)

    return updated
