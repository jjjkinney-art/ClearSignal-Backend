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
            × (1 + recurrence_bonus)

Where:
    agent_confidence  = the source agent's confidence field
    type_priority     = per-type weight (structural=1.0 … noise=0.0)
    direction_weight  = bullish/bearish=1.1, neutral=0.85
    recurrence_bonus  = 0.2 per additional agent that raised the same concept

All scoring is deterministic — no LLM calls in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

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

# ── Forbidden phrases (Phase 5) ───────────────────────────────────────────────
FORBIDDEN_PHRASES: frozenset = frozenset({
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
})


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
    """Compute a composite ranking score for a single signal."""
    type_w  = _TYPE_PRIORITY.get(signal.signal_type, 0.5)
    dir_w   = _DIRECTION_WEIGHT.get(signal.direction, 0.85)
    return signal.impact_score * agent_confidence * type_w * dir_w


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

    Two signals are duplicates when their Jaccard similarity ≥ 0.45.
    The higher-scoring signal is kept as primary; the lower-scoring one
    is merged in (boosting impact_score and unioning evidence_refs).

    Returns
    -------
    Deduplicated list of (Signal, agent_confidence) pairs, longest first.
    """
    if not pairs:
        return []

    # Sort by raw score descending so higher-quality signals are kept as primary
    scored = sorted(pairs, key=lambda p: _score(p[0], p[1]), reverse=True)
    merged: List[Tuple[Signal, float]] = []

    for sig, conf in scored:
        matched = False
        for i, (existing, existing_conf) in enumerate(merged):
            if _are_duplicates(sig, existing):
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

    # top_signals: up to 3 from bullish/neutral pool
    top_signals = bullish_neutral[:3]

    # top_risks: up to 4 from bearish/risk pool
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

    Checks bull_thesis, bear_thesis, conclusion, and direct_answer.
    Returns an empty list when the thesis uses causal, specific language.
    """
    warnings: List[str] = []
    fields_to_check = {
        "bull_thesis":  thesis.bull_thesis,
        "bear_thesis":  thesis.bear_thesis,
        "conclusion":   thesis.conclusion,
        "direct_answer": thesis.direct_answer,
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
