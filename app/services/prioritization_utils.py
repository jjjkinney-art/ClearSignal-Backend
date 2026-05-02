"""
Signal prioritization utilities.

This module implements lightweight heuristics to rank lists of drivers,
risks, changes or alerts by their perceived importance.  The goal is
to surface the most impactful signals in a deterministic and
explainable way without introducing heavy machine learning
dependencies.  The heuristics assign scores based on keyword
occurrences and phrase length, then sort items accordingly.

Future enhancements could incorporate sentiment analysis or user
preferences, but this module intentionally remains simple.
"""

from __future__ import annotations

from typing import List, Optional

def _get_signal_weight(signal: str) -> float:
    """Lazily resolve get_signal_weight from the learning module at call time.

    Using a lazy import here (rather than a module-level binding) ensures that
    this function always uses whatever version of ``app.services.learning`` is
    current in ``sys.modules`` at the moment of the call.  This matters in the
    test suite, where conftest.py replaces the learning module before each test
    to undo contamination from test-collection-time stubs.  A module-level
    ``from .learning import get_signal_weight`` would bind to the stub version
    imported during collection and ignore the restored real module.
    """
    try:
        from .learning import get_signal_weight as _gsw
        return _gsw(signal)
    except Exception:
        return 1.0


def _score_item(item: str) -> float:
    """Assign a heuristic score to a signal for ranking purposes.

    The scoring function looks for certain keywords that typically
    indicate higher significance (e.g. risk, regulatory, macro) and
    adds fractional points based on the length of the phrase.  Lower
    cases are used for keyword matching to make scoring case‑insensitive.
    """
    text = item.lower()
    score = 0.0
    keyword_weights = {
        "risk": 2.0,
        "regulatory": 2.0,
        "macro": 1.5,
        "interest": 1.5,
        "growth": 1.0,
        "debt": 1.5,
        "litigation": 2.0,
        "valuation": 1.0,
        "profit": 1.0,
        "competition": 1.0,
    }
    for kw, w in keyword_weights.items():
        if kw in text:
            score += w
    # Add a small component for phrase length (more words imply more detail)
    score += 0.1 * len(item.split())
    return score


def rank_signals(items: List[str], top_n: int = 3, focus: Optional[str] = None) -> List[str]:
    """Rank a list of signal descriptions by importance.

    Parameters
    ----------
    items : List[str]
        Signal descriptions to rank.
    top_n : int, default 3
        Number of top items to return.  If fewer than ``top_n`` items
        are provided, the full sorted list is returned.
    focus : Optional[str], default None
        Optional user focus area (e.g. 'macro', 'risk').  When
        provided, items containing the focus keyword receive a small
        additional boost to their score.

    Returns
    -------
    List[str]
        The ``top_n`` items sorted by descending importance.
    """
    if not items:
        return []
    # Compute scores
    scored = []
    for item in items:
        base = _score_item(item)
        # Apply adaptive weight based on past effectiveness
        weight = 1.0
        try:
            weight = _get_signal_weight(item)
        except Exception:
            weight = 1.0
        s = base * weight
        # Apply focus boost.  The boost is additive to ensure it can
        # elevate focused signals relative to others.  A modest value is
        # chosen to prevent focus from dominating high base scores.
        if focus and focus.lower() in item.lower():
            s += 0.5
        scored.append((item, s))
    # Sort by score descending; stable sort keeps original order for ties
    scored.sort(key=lambda x: x[1], reverse=True)
    # Return the top_n items
    return [item for item, _ in scored[:top_n]]