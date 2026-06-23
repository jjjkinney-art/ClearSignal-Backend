"""
Ticker Normalization — Phase 20A · Priority 3.

Normalizes common ticker variants to their canonical form BEFORE
company lookup.  Handles dot-separated, dash-separated, and
concatenated share-class tickers.

Examples:
  BRK.B, BRK-B, BRKB → BRK.B
  BF.B, BF-B, BFB → BF.B
  BRK.A, BRK-A, BRKA → BRK.A
  RDS.A, RDS-A, RDSA → RDS.A  (legacy Shell)
"""

from __future__ import annotations

import re
from typing import Optional


# Canonical mapping: normalized form → canonical ticker.
# Keys are uppercase with no separators for matching;
# values are the canonical dotted ticker.
_TICKER_VARIANTS = {
    # Berkshire Hathaway
    "BRKB":  "BRK.B",
    "BRK-B": "BRK.B",
    "BRK.B": "BRK.B",
    "BRKA":  "BRK.A",
    "BRK-A": "BRK.A",
    "BRK.A": "BRK.A",
    # Brown-Forman
    "BFB":   "BF.B",
    "BF-B":  "BF.B",
    "BF.B":  "BF.B",
    "BFA":   "BF.A",
    "BF-A":  "BF.A",
    "BF.A":  "BF.A",
    # Legacy Shell (delisted but commonly searched)
    "RDSA":  "RDS.A",
    "RDS-A": "RDS.A",
    "RDS.A": "RDS.A",
    "RDSB":  "RDS.B",
    "RDS-B": "RDS.B",
    "RDS.B": "RDS.B",
    # Linde (delisted LIN.DE, often typed as LINDE)
    # Kept as-is since LIN is the canonical US ticker
    # Liberty Media
    "LSXMA": "LSXMA",
    "LSXMB": "LSXMB",
    "LSXMK": "LSXMK",
}

_STRIP_RE = re.compile(r"[.\-]")


def normalize_ticker(raw: str) -> str:
    """Normalize a ticker string to its canonical form.

    Handles:
      - Dot-separated class tickers: BRK.B → BRK.B (identity)
      - Dash-separated class tickers: BRK-B → BRK.B
      - Concatenated class tickers: BRKB → BRK.B

    Returns the canonical ticker if a mapping exists, or the input
    uppercased if no mapping matches.
    """
    if not raw:
        return raw
    upper = raw.strip().upper()

    # Direct lookup (handles BRK.B, BRK-B, BRKB etc.)
    if upper in _TICKER_VARIANTS:
        return _TICKER_VARIANTS[upper]

    # Strip separators and try again (handles novel separator styles)
    stripped = _STRIP_RE.sub("", upper)
    if stripped in _TICKER_VARIANTS:
        return _TICKER_VARIANTS[stripped]

    return upper


def normalize_ticker_in_text(text: str) -> str:
    """Normalize any ticker variants found in a text string.

    Scans for known variant patterns and replaces them with canonical
    forms.  Non-destructive — only replaces exact variant matches.
    """
    if not text:
        return text

    result = text
    for variant, canonical in _TICKER_VARIANTS.items():
        if variant == canonical:
            continue
        pattern = re.compile(r"\b" + re.escape(variant) + r"\b", re.IGNORECASE)
        result = pattern.sub(canonical, result)
    return result
