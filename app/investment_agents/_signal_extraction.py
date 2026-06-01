"""Post-call signal extraction fallback for investment agents.

When an investment agent returns no bullish signals (either ``signals=[]``
or all signals are bearish/risk) despite producing a non-empty ``overall``
analysis text, this module provides a keyword-based extraction pass that
formalises the most positive sentence in the existing prose into a Signal
object.

Design constraints
------------------
- NO extra LLM calls — extraction is purely rule-based.
- NO fabrication — sentences are taken verbatim from the agent's own output.
- Direction bias toward "bullish" is intentional: the synthesis pipeline
  already has a reliable bearish signal path (risk agent + ranker).  The
  bullish side of the thesis must not be systematically silenced because the
  non-risk agents returned an empty array.
- Conservative impact scores (0.50–0.55) signal that these were extracted
  from prose, not inferred from hard evidence.
"""
from __future__ import annotations

import re
import logging
from typing import List, Optional

from ..schemas import CompanyContext, CompanyKnowledgeProfile, Signal

logger = logging.getLogger(__name__)

# Keywords that suggest positive investment factors (case-insensitive).
_POSITIVE_KEYWORDS: frozenset = frozenset({
    "grow", "growth", "growing", "accelerat",
    "lead", "leads", "leading", "leader", "dominant", "dominance",
    "strong", "strengthen", "strength",
    "advantage", "advantages", "moat",
    "durable", "resilient", "resilience",
    "margin", "profitab", "profitable",
    "cash flow", "fcf", "free cash",
    "return", "upside", "re-rate",
    "expand", "expansion", "inflect",
    "outperform", "premium", "subscription",
    "loyal", "retention", "sticky",
    "network effect", "scale", "scalab",
    "increase", "increases", "increasing",
    "best", "top", "first", "highest",
    "exceed", "beat", "beats", "record",
    "recovery", "recover", "rebound",
    "competitive advantage", "market share",
})

# Keywords that strongly suggest risk / negative sentiment — sentences
# dominated by these are skipped when searching for the bullish signal.
# NOTE: "compet" is intentionally excluded even though it can signal
# competition risk, because it also appears in clearly positive contexts
# ("competitive advantage", "competitive moat", "competitive positioning").
# Those positive uses are already covered by "competitive advantage" in
# _POSITIVE_KEYWORDS above.  Including "compet" here was causing the
# early-return guard to fire on every sentence written about tech companies
# (nearly all of which mention competition in some form).
_NEGATIVE_SKIP_KEYWORDS: frozenset = frozenset({
    "risk", "threat", "decline", "declin", "compress",
    "loss", "loses", "headwind", "limit", "challenge", "concern",
    "uncertain", "volatile", "volatility", "pressure",
    "regulatory", "antitrust",
})


def _sentence_positive_score(
    sentence: str,
    profile_keywords: frozenset,
) -> int:
    """Return a positive-signal score for a single sentence.

    Uses keyword hit-counting with a bonus for profile-specific keywords.

    Negative keywords subtract from the score, but the first negative hit
    is forgiven — this allows sentences structured as "X is strong, but Y
    creates headwinds" to still qualify when the positive content is
    genuine.  Sentences with 3+ negative hits are discarded entirely (they
    are dominated by risk language regardless of any positive qualifier).
    """
    lower = sentence.lower()

    # Discard sentences dominated by negative language.
    neg_hits = sum(1 for kw in _NEGATIVE_SKIP_KEYWORDS if kw in lower)
    if neg_hits >= 3:
        return 0

    pos_hits = sum(1 for kw in _POSITIVE_KEYWORDS if kw in lower)
    profile_hits = sum(2 for kw in profile_keywords if kw in lower)
    # Forgive the first negative qualifier — only the excess penalises the
    # score.  "Azure growth faces rate pressure" → 2 pos, 1 neg → net 2
    # (threshold met) rather than net 1 (threshold missed at old cutoff of 2).
    effective_neg = max(0, neg_hits - 1)
    return pos_hits + profile_hits - effective_neg


def extract_min_bullish_signal(
    overall: str,
    company: CompanyContext,
    agent_name: str,
    signal_type: str,
    profile: Optional[CompanyKnowledgeProfile] = None,
) -> List[Signal]:
    """Extract at most one bullish Signal from the agent's overall prose.

    Returns an empty list when:
    - ``overall`` is too short to sentence-split meaningfully.
    - No sentence scores above the minimum threshold.

    The scoring is calibrated to handle agents that write compound sentences
    containing both positive and negative qualifiers (e.g. "Azure's growth
    trajectory is robust but faces competitive pressure and rate risk").
    The first two negative keywords are forgiven; only the excess penalises
    the score.  Sentences with 5+ negative hits are discarded entirely.

    Parameters
    ----------
    overall     : The ``overall`` text field already generated by the agent.
    company     : Company context for logging and attribution.
    agent_name  : Used as ``source_agent`` on the Signal and in log messages.
    signal_type : Signal type string (e.g. ``"valuation"``, ``"quality"``).
    profile     : Optional knowledge profile — its ``business_model_keywords``
                  receive extra weight in positive scoring.
    """
    if not overall or len(overall.strip()) < 60:
        return []

    profile_keywords: frozenset = frozenset()
    if profile is not None:
        profile_keywords = frozenset(
            kw.lower() for kw in profile.business_model_keywords
        )

    # Split on sentence boundaries.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", overall.strip())
                 if len(s.strip()) > 30]

    if not sentences:
        return []

    best_sentence: Optional[str] = None
    best_score: int = 0

    for sent in sentences:
        score = _sentence_positive_score(sent, profile_keywords)
        if score > best_score:
            best_score = score
            best_sentence = sent

    # Minimum threshold: at least 1 net-positive score after forgiven negatives.
    # Threshold lowered from 2 → 1 because the adjusted penalty formula already
    # requires genuine positive content (sentences with only negative keywords
    # score 0 or negative and are excluded).
    if best_sentence is None or best_score < 1:
        logger.debug(
            "[%s] signal_extraction: no qualifying positive sentence found "
            "for %s (best_score=%d)",
            agent_name, company.ticker, best_score,
        )
        return []

    # Truncate gracefully to avoid excessively long signal text.
    signal_text = best_sentence[:250].rstrip(",; ")

    signal = Signal(
        signal=signal_text,
        direction="bullish",
        signal_type=signal_type,
        impact_score=0.52,        # Conservative — extracted from prose, not hard evidence
        time_horizon="medium_term",
        importance_reason=(
            f"Primary positive factor identified in {agent_name} analysis — "
            f"extracted from overall assessment when no bullish structured signal was generated."
        ),
        source_agent=agent_name,
    )

    logger.debug(
        "[%s] signal_extraction: extracted 1 bullish signal for %s (score=%d): %r",
        agent_name, company.ticker, best_score, signal_text[:60],
    )
    return [signal]
