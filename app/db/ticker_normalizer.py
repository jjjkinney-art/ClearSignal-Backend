"""
Canonical ticker normalizer.

Converts any known company name, alias, or ticker variant to a single
uppercase canonical ticker string.  Prevents fragmented thesis history
when the model returns "Nvidia" vs "NVDA" vs "NVIDIA Corporation".

Usage::

    from app.db.ticker_normalizer import normalize_ticker

    normalize_ticker("Nvidia")             # → "NVDA"
    normalize_ticker("NVIDIA Corporation") # → "NVDA"
    normalize_ticker("nvda")               # → "NVDA"
    normalize_ticker("JPMorgan Chase")     # → "JPM"
    normalize_ticker("UNKNOWN_CO")         # → "UNKNOWN_CO"  (passthrough)

The lookup is O(1) via a pre-built lowercased dict.  Unknown inputs are
uppercased, stripped, and truncated to 20 characters (safe for the DB column).

Maintenance: add entries to _RAW_MAP below when new tickers are added to
the platform.  Aliases, common misspellings, and full legal names all go here.
"""

from __future__ import annotations

from typing import Dict

# ---------------------------------------------------------------------------
# Raw mapping: variant (any case) → canonical ticker (uppercase)
# ---------------------------------------------------------------------------
# Format: "any string the model might return" → "TICKER"
# Include: company name, common aliases, ETF names, legal entity names.
# All keys are lowercased at build time — do NOT pre-lowercase here.

_RAW_MAP: Dict[str, str] = {
    # NVIDIA
    "nvda":                          "NVDA",
    "nvidia":                        "NVDA",
    "nvidia corporation":            "NVDA",
    "nvidia corp":                   "NVDA",
    "nvidia corp.":                  "NVDA",

    # Apple
    "aapl":                          "AAPL",
    "apple":                         "AAPL",
    "apple inc":                     "AAPL",
    "apple inc.":                    "AAPL",
    "apple computer":                "AAPL",

    # Microsoft
    "msft":                          "MSFT",
    "microsoft":                     "MSFT",
    "microsoft corporation":         "MSFT",
    "microsoft corp":                "MSFT",

    # Alphabet / Google
    "googl":                         "GOOGL",
    "goog":                          "GOOGL",
    "alphabet":                      "GOOGL",
    "alphabet inc":                  "GOOGL",
    "alphabet inc.":                 "GOOGL",
    "google":                        "GOOGL",
    "google llc":                    "GOOGL",

    # Amazon
    "amzn":                          "AMZN",
    "amazon":                        "AMZN",
    "amazon.com":                    "AMZN",
    "amazon.com inc":                "AMZN",
    "amazon web services":           "AMZN",
    "aws":                           "AMZN",

    # Meta
    "meta":                          "META",
    "meta platforms":                "META",
    "meta platforms inc":            "META",
    "facebook":                      "META",
    "fb":                            "META",

    # Tesla
    "tsla":                          "TSLA",
    "tesla":                         "TSLA",
    "tesla inc":                     "TSLA",
    "tesla motors":                  "TSLA",

    # TSMC
    "tsm":                           "TSM",
    "tsmc":                          "TSM",
    "taiwan semiconductor":          "TSM",
    "taiwan semiconductor manufacturing": "TSM",
    "taiwan semiconductor mfg":      "TSM",

    # JPMorgan Chase
    "jpm":                           "JPM",
    "jpmorgan":                      "JPM",
    "jpmorgan chase":                "JPM",
    "j.p. morgan":                   "JPM",
    "jp morgan":                     "JPM",
    "jpmorgan chase & co":           "JPM",

    # Costco
    "cost":                          "COST",
    "costco":                        "COST",
    "costco wholesale":              "COST",
    "costco wholesale corporation":  "COST",

    # Visa
    "v":                             "V",
    "visa":                          "V",
    "visa inc":                      "V",

    # Broadcom
    "avgo":                          "AVGO",
    "broadcom":                      "AVGO",
    "broadcom inc":                  "AVGO",

    # Eli Lilly
    "lly":                           "LLY",
    "eli lilly":                     "LLY",
    "eli lilly and company":         "LLY",
    "lilly":                         "LLY",

    # Novo Nordisk
    "nvo":                           "NVO",
    "novo nordisk":                  "NVO",
    "novo nordisk a/s":              "NVO",

    # Goldman Sachs
    "gs":                            "GS",
    "goldman sachs":                 "GS",
    "goldman sachs group":           "GS",
    "the goldman sachs group":       "GS",

    # UnitedHealth
    "unh":                           "UNH",
    "unitedhealth":                  "UNH",
    "unitedhealth group":            "UNH",
    "united health":                 "UNH",

    # Walmart
    "wmt":                           "WMT",
    "walmart":                       "WMT",
    "walmart inc":                   "WMT",
    "wal-mart":                      "WMT",

    # AMD
    "amd":                           "AMD",
    "advanced micro devices":        "AMD",
    "advanced micro devices inc":    "AMD",

    # Palantir
    "pltr":                          "PLTR",
    "palantir":                      "PLTR",
    "palantir technologies":         "PLTR",

    # Honeywell
    "hon":                           "HON",
    "honeywell":                     "HON",
    "honeywell international":       "HON",

    # Bank of America
    "bac":                           "BAC",
    "bank of america":               "BAC",
    "bank of america corporation":   "BAC",

    # ASML
    "asml":                          "ASML",
    "asml holding":                  "ASML",
    "asml holding nv":               "ASML",
}

# Build the lowercased lookup dict once at import time
_LOOKUP: Dict[str, str] = {k.lower().strip(): v for k, v in _RAW_MAP.items()}

_MAX_TICKER_LEN = 20


def normalize_ticker(raw: str) -> str:
    """Return the canonical uppercase ticker for any known name or alias.

    Parameters
    ----------
    raw:
        Any string that might represent a company: ticker, full name, alias.
        Case-insensitive.  Leading/trailing whitespace is stripped.

    Returns
    -------
    str
        Canonical uppercase ticker (e.g. "NVDA"), or the uppercased+stripped
        input truncated to 20 chars when no mapping is found.
    """
    if not raw:
        return "UNKNOWN"

    cleaned = raw.strip()
    key = cleaned.lower()

    # Exact match
    if key in _LOOKUP:
        return _LOOKUP[key]

    # Partial prefix match — handles "NVIDIA Corporation (NVDA)" style strings
    # produced by some model outputs
    for alias, canonical in _LOOKUP.items():
        if key.startswith(alias) or alias.startswith(key):
            return canonical

    # No match — passthrough, uppercased and truncated
    return cleaned.upper()[:_MAX_TICKER_LEN]


def canonical_ticker_for_thesis(thesis_data: dict, company_name: str = "") -> str:
    """Resolve ticker from thesis dict, with company_name as fallback.

    Checks thesis_data['ticker'] first, then thesis_data['company_name'],
    then the company_name argument.  Returns "UNKNOWN" if all are empty.
    """
    candidates = [
        str(thesis_data.get("ticker") or ""),
        str(thesis_data.get("company_name") or ""),
        company_name,
    ]
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        result = normalize_ticker(candidate)
        if result and result != "UNKNOWN":
            return result
    return "UNKNOWN"
