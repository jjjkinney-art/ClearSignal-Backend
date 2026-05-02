"""
Event categorization utilities.

This module defines a helper function to categorise news and event
strings into high‑level categories such as earnings, regulatory,
macro and product.  The categorisation is based on simple keyword
searches and can be extended to support more nuanced tagging.  It
is intended to enrich the evidence layer without introducing
external dependencies.
"""

from __future__ import annotations

from typing import List


def categorize_events(events: List[str]) -> List[str]:
    """Return a list of category labels corresponding to each event.

    The same order as the input events is preserved.  Categories are
    determined by keyword matching.  Unknown events are labelled
    "other".

    Parameters
    ----------
    events : List[str]
        Event descriptions to categorise.

    Returns
    -------
    List[str]
        A list of categories, one for each event.
    """
    categories: List[str] = []
    for ev in events:
        t = ev.lower()
        if any(kw in t for kw in ("earnings", "eps", "quarterly results", "income statement")):
            categories.append("earnings")
        elif any(kw in t for kw in ("regulation", "regulatory", "sec", "filing", "10-k", "10-q", "lawsuit")):
            categories.append("regulatory")
        elif any(kw in t for kw in ("inflation", "interest", "macro", "rates", "employment", "gdp")):
            categories.append("macro")
        elif any(kw in t for kw in ("product", "launch", "release", "innovation")):
            categories.append("product")
        else:
            categories.append("other")
    return categories