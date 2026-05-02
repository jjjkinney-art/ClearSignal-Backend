"""
Advanced signal scoring utilities.

This module defines functions to transform plain text signals into
structured objects with additional metadata such as importance
scores, impact type, time horizon and confidence.  The scoring
logic is heuristic‑based and deterministic, using keyword matching
and simple rules to assign attributes.  The resulting objects can
be used to prioritise signals beyond simple ranking and to filter
noise.

The scoring range for ``importance_score`` is 0–100.  Impact types
include ``risk``, ``growth``, ``macro`` and ``structural``.  Time
horizons are ``short``, ``medium`` or ``long``.  Confidence scores
range from 0.5 to 0.95 depending on how specific the signal appears.

These utilities do not rely on external models and can be tested
offline.  They are intended to complement the existing
``rank_signals`` function by providing richer context for signal
prioritisation.
"""

from __future__ import annotations

from typing import List, Dict, Optional, Any

from .prioritization_utils import _score_item
from .learning import get_signal_weight


def _impact_type(text: str) -> str:
    """Heuristically determine the impact type of a signal.

    Returns one of ``risk``, ``growth``, ``macro`` or ``structural``
    based on keyword presence.  Defaults to ``structural`` when no
    category keywords are found.
    """
    t = text.lower()
    if any(kw in t for kw in ("risk", "regulatory", "debt", "litigation", "litigation", "lawsuit")):
        return "risk"
    if any(kw in t for kw in ("growth", "opportunity", "expansion", "demand")):
        return "growth"
    if any(kw in t for kw in ("macro", "inflation", "interest", "rates", "economy", "recession")):
        return "macro"
    return "structural"


def _time_horizon(text: str) -> str:
    """Infer the time horizon of a signal based on heuristic cues."""
    t = text.lower()
    if any(kw in t for kw in ("short-term", "immediate", "near term", "next quarter")):
        return "short"
    if any(kw in t for kw in ("long-term", "long term", "decade")):
        return "long"
    return "medium"


def _confidence_score(text: str) -> float:
    """Assign a heuristic confidence score to a signal.

    Confidence is higher for longer phrases with more descriptive
    content.  The score ranges from 0.5 to 0.95.  Longer signals
    achieve higher confidence.  This function does not incorporate
    external validation.
    """
    words = len(text.split())
    # Map word count into [0.5, 0.95]
    if words <= 3:
        return 0.5
    if words >= 12:
        return 0.95
    return 0.5 + (words - 3) * (0.45 / 9.0)


def score_signals(items: List[str], focus: Optional[str] = None) -> List[Dict[str, Any]]:
    """Compute detailed scores and metadata for a list of signals.

    Parameters
    ----------
    items : List[str]
        List of signal descriptions.
    focus : Optional[str], default None
        Optional user focus area to boost signals matching the focus.

    Returns
    -------
    List[Dict[str, Any]]
        A list of dictionaries, each containing the original signal
        text, its importance_score (0–100), impact_type, time_horizon,
        confidence_score, and overall weighted_score used for ranking.
    """
    results: List[Dict[str, Any]] = []
    for item in items:
        base_score = _score_item(item)
        # Apply adaptive weight based on learning memory
        weight = get_signal_weight(item)
        impact = _impact_type(item)
        horizon = _time_horizon(item)
        confidence = _confidence_score(item)
        # Compute an importance score scaled to 0–100.  Base scores
        # typically range in [0, ~10], so multiply by 10 to scale.
        importance = min(100.0, base_score * weight * 10.0)
        # Increase importance slightly if it matches the user focus
        if focus and focus.lower() in item.lower():
            importance = min(100.0, importance + 5.0)
        # Weighted score for ranking combines importance and confidence
        weighted = importance * confidence
        results.append({
            "signal": item,
            "importance_score": round(importance, 2),
            "impact_type": impact,
            "time_horizon": horizon,
            "confidence_score": round(confidence, 2),
            "weighted_score": round(weighted, 2),
        })
    # Sort by weighted score descending.  Stable sort preserves original order
    # for ties.
    results.sort(key=lambda x: x["weighted_score"], reverse=True)
    return results