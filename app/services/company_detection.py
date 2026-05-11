"""company_detection.py — detect and normalise company names / ticker symbols.

Public API
----------
detect_company(text: str) -> Optional[CompanyContext]
normalize_ticker(raw: str) -> Optional[CompanyContext]

Detection runs three steps in order:
1. Explicit uppercase ticker extraction (regex + stop-word filter).
2. Alias substring lookup (longest match wins).
3. Fuzzy alias match via difflib (cutoff 0.82).

No network calls are made; no external API keys are required.
"""

from __future__ import annotations

import difflib
import re
from typing import Optional

from app.schemas import CompanyContext

# ---------------------------------------------------------------------------
# Stop-words — common English words that look like valid tickers
# ---------------------------------------------------------------------------

_TICKER_STOP_WORDS: frozenset[str] = frozenset({
    "A", "I", "IT", "IS", "IN", "ON", "OF", "AT", "BE", "BY", "DO", "GO",
    "IF", "NO", "OR", "TO", "UP", "US", "WE", "AN", "AS", "AM", "ARE",
    "ALL", "AND", "BUT", "CAN", "FOR", "GET", "GOT", "HAD", "HAS", "HIM",
    "HIS", "HOW", "ITS", "LET", "MAY", "ME", "MY", "NEW", "NOT", "NOW",
    "OFF", "OLD", "OUR", "OUT", "OWN", "SAY", "SHE", "SO", "THE", "TOO",
    "TWO", "USE", "WAS", "WAY", "WHO", "WHY", "WIN", "WITH", "YES", "YET",
    "YOU",
})

# ---------------------------------------------------------------------------
# Company database — ticker → metadata
# ---------------------------------------------------------------------------

_COMPANY_DB: dict[str, dict] = {
    "AAPL":  {"company_name": "Apple Inc.",                              "sector": "Technology",                "industry": "Consumer Electronics"},
    "MSFT":  {"company_name": "Microsoft Corporation",                   "sector": "Technology",                "industry": "Software"},
    "GOOGL": {"company_name": "Alphabet Inc.",                           "sector": "Technology",                "industry": "Internet Services"},
    "AMZN":  {"company_name": "Amazon.com Inc.",                         "sector": "Consumer Discretionary",    "industry": "E-Commerce"},
    "META":  {"company_name": "Meta Platforms Inc.",                     "sector": "Technology",                "industry": "Social Media"},
    "NVDA":  {"company_name": "NVIDIA Corporation",                      "sector": "Technology",                "industry": "Semiconductors"},
    "TSLA":  {"company_name": "Tesla Inc.",                              "sector": "Consumer Discretionary",    "industry": "Electric Vehicles"},
    "BRK.B": {"company_name": "Berkshire Hathaway Inc.",                 "sector": "Financials",                "industry": "Diversified Financials"},
    "JPM":   {"company_name": "JPMorgan Chase & Co.",                    "sector": "Financials",                "industry": "Banking"},
    "GS":    {"company_name": "Goldman Sachs Group Inc.",                "sector": "Financials",                "industry": "Investment Banking"},
    "BAC":   {"company_name": "Bank of America Corp.",                   "sector": "Financials",                "industry": "Banking"},
    "WFC":   {"company_name": "Wells Fargo & Co.",                       "sector": "Financials",                "industry": "Banking"},
    "C":     {"company_name": "Citigroup Inc.",                          "sector": "Financials",                "industry": "Banking"},
    "V":     {"company_name": "Visa Inc.",                               "sector": "Financials",                "industry": "Payment Processing"},
    "MA":    {"company_name": "Mastercard Inc.",                         "sector": "Financials",                "industry": "Payment Processing"},
    "PYPL":  {"company_name": "PayPal Holdings Inc.",                    "sector": "Financials",                "industry": "Digital Payments"},
    "NFLX":  {"company_name": "Netflix Inc.",                            "sector": "Communication Services",    "industry": "Streaming"},
    "DIS":   {"company_name": "The Walt Disney Company",                 "sector": "Communication Services",    "industry": "Entertainment"},
    "BA":    {"company_name": "The Boeing Company",                      "sector": "Industrials",               "industry": "Aerospace & Defense"},
    "JNJ":   {"company_name": "Johnson & Johnson",                       "sector": "Health Care",               "industry": "Pharmaceuticals"},
    "PFE":   {"company_name": "Pfizer Inc.",                             "sector": "Health Care",               "industry": "Pharmaceuticals"},
    "MRNA":  {"company_name": "Moderna Inc.",                            "sector": "Health Care",               "industry": "Biotechnology"},
    "UNH":   {"company_name": "UnitedHealth Group Inc.",                 "sector": "Health Care",               "industry": "Managed Care"},
    "XOM":   {"company_name": "ExxonMobil Corporation",                  "sector": "Energy",                    "industry": "Oil & Gas"},
    "CVX":   {"company_name": "Chevron Corporation",                     "sector": "Energy",                    "industry": "Oil & Gas"},
    "COP":   {"company_name": "ConocoPhillips",                          "sector": "Energy",                    "industry": "Oil & Gas E&P"},
    "WMT":   {"company_name": "Walmart Inc.",                            "sector": "Consumer Staples",          "industry": "Retail"},
    "TGT":   {"company_name": "Target Corporation",                      "sector": "Consumer Staples",          "industry": "Retail"},
    "HD":    {"company_name": "The Home Depot Inc.",                     "sector": "Consumer Discretionary",    "industry": "Home Improvement Retail"},
    "COST":  {"company_name": "Costco Wholesale Corporation",            "sector": "Consumer Staples",          "industry": "Retail"},
    "SBUX":  {"company_name": "Starbucks Corporation",                   "sector": "Consumer Discretionary",    "industry": "Restaurants"},
    "MCD":   {"company_name": "McDonald's Corporation",                  "sector": "Consumer Discretionary",    "industry": "Restaurants"},
    "NKE":   {"company_name": "Nike Inc.",                               "sector": "Consumer Discretionary",    "industry": "Apparel"},
    "AMD":   {"company_name": "Advanced Micro Devices Inc.",             "sector": "Technology",                "industry": "Semiconductors"},
    "INTC":  {"company_name": "Intel Corporation",                       "sector": "Technology",                "industry": "Semiconductors"},
    "QCOM":  {"company_name": "Qualcomm Inc.",                           "sector": "Technology",                "industry": "Semiconductors"},
    "AVGO":  {"company_name": "Broadcom Inc.",                           "sector": "Technology",                "industry": "Semiconductors"},
    "TSM":   {"company_name": "Taiwan Semiconductor Manufacturing Co.",  "sector": "Technology",                "industry": "Semiconductors"},
    "CRM":   {"company_name": "Salesforce Inc.",                         "sector": "Technology",                "industry": "Software"},
    "ORCL":  {"company_name": "Oracle Corporation",                      "sector": "Technology",                "industry": "Software"},
    "NOW":   {"company_name": "ServiceNow Inc.",                         "sector": "Technology",                "industry": "Software"},
    "SNOW":  {"company_name": "Snowflake Inc.",                          "sector": "Technology",                "industry": "Cloud Computing"},
    "PLTR":  {"company_name": "Palantir Technologies Inc.",              "sector": "Technology",                "industry": "Data Analytics"},
    "NET":   {"company_name": "Cloudflare Inc.",                         "sector": "Technology",                "industry": "Cybersecurity"},
    "CRWD":  {"company_name": "CrowdStrike Holdings Inc.",               "sector": "Technology",                "industry": "Cybersecurity"},
    "PANW":  {"company_name": "Palo Alto Networks Inc.",                 "sector": "Technology",                "industry": "Cybersecurity"},
    "UBER":  {"company_name": "Uber Technologies Inc.",                  "sector": "Technology",                "industry": "Ride-Sharing"},
    "LYFT":  {"company_name": "Lyft Inc.",                               "sector": "Technology",                "industry": "Ride-Sharing"},
    "ABNB":  {"company_name": "Airbnb Inc.",                             "sector": "Consumer Discretionary",    "industry": "Online Travel"},
    "COIN":  {"company_name": "Coinbase Global Inc.",                    "sector": "Financials",                "industry": "Cryptocurrency Exchange"},
    "SPOT":  {"company_name": "Spotify Technology S.A.",                 "sector": "Communication Services",    "industry": "Music Streaming"},
    "SHOP":  {"company_name": "Shopify Inc.",                            "sector": "Technology",                "industry": "E-Commerce Software"},
    "ARM":   {"company_name": "Arm Holdings plc",                        "sector": "Technology",                "industry": "Semiconductors"},
    "SMCI":  {"company_name": "Super Micro Computer Inc.",               "sector": "Technology",                "industry": "Computer Hardware"},
    "MU":    {"company_name": "Micron Technology Inc.",                  "sector": "Technology",                "industry": "Semiconductors"},
    "AMAT":  {"company_name": "Applied Materials Inc.",                  "sector": "Technology",                "industry": "Semiconductor Equipment"},
    "ASML":  {"company_name": "ASML Holding N.V.",                       "sector": "Technology",                "industry": "Semiconductor Equipment"},
    "LRCX":  {"company_name": "Lam Research Corporation",               "sector": "Technology",                "industry": "Semiconductor Equipment"},
    "TXN":   {"company_name": "Texas Instruments Inc.",                  "sector": "Technology",                "industry": "Semiconductors"},
    "CAT":   {"company_name": "Caterpillar Inc.",                        "sector": "Industrials",               "industry": "Construction Machinery"},
    "DE":    {"company_name": "Deere & Company",                         "sector": "Industrials",               "industry": "Agricultural Machinery"},
    "MMM":   {"company_name": "3M Company",                              "sector": "Industrials",               "industry": "Diversified Industrials"},
    "HON":   {"company_name": "Honeywell International Inc.",            "sector": "Industrials",               "industry": "Diversified Industrials"},
    "GE":    {"company_name": "GE Aerospace",                            "sector": "Industrials",               "industry": "Aerospace & Defense"},
    "RTX":   {"company_name": "RTX Corporation",                         "sector": "Industrials",               "industry": "Aerospace & Defense"},
    "LMT":   {"company_name": "Lockheed Martin Corporation",             "sector": "Industrials",               "industry": "Aerospace & Defense"},
    "NOC":   {"company_name": "Northrop Grumman Corporation",            "sector": "Industrials",               "industry": "Aerospace & Defense"},
    "UAL":   {"company_name": "United Airlines Holdings Inc.",           "sector": "Industrials",               "industry": "Airlines"},
    "DAL":   {"company_name": "Delta Air Lines Inc.",                    "sector": "Industrials",               "industry": "Airlines"},
    "LUV":   {"company_name": "Southwest Airlines Co.",                  "sector": "Industrials",               "industry": "Airlines"},
    "MAR":   {"company_name": "Marriott International Inc.",             "sector": "Consumer Discretionary",    "industry": "Hotels"},
    "HLT":   {"company_name": "Hilton Worldwide Holdings Inc.",          "sector": "Consumer Discretionary",    "industry": "Hotels"},
    "CCL":   {"company_name": "Carnival Corporation",                    "sector": "Consumer Discretionary",    "industry": "Cruise Lines"},
    "RCL":   {"company_name": "Royal Caribbean Group",                   "sector": "Consumer Discretionary",    "industry": "Cruise Lines"},
    "ABBV":  {"company_name": "AbbVie Inc.",                             "sector": "Health Care",               "industry": "Pharmaceuticals"},
    "LLY":   {"company_name": "Eli Lilly and Company",                   "sector": "Health Care",               "industry": "Pharmaceuticals"},
    "MRK":   {"company_name": "Merck & Co. Inc.",                        "sector": "Health Care",               "industry": "Pharmaceuticals"},
    "BMY":   {"company_name": "Bristol-Myers Squibb Co.",                "sector": "Health Care",               "industry": "Pharmaceuticals"},
    "REGN":  {"company_name": "Regeneron Pharmaceuticals Inc.",          "sector": "Health Care",               "industry": "Biotechnology"},
    "INTU":  {"company_name": "Intuit Inc.",                             "sector": "Technology",                "industry": "Financial Software"},
    "ADBE":  {"company_name": "Adobe Inc.",                              "sector": "Technology",                "industry": "Software"},
}

# ---------------------------------------------------------------------------
# Alias map — lowercase alias → ticker
# ---------------------------------------------------------------------------

_ALIAS_MAP: dict[str, str] = {
    # Apple
    "apple":                   "AAPL",
    "apple inc":               "AAPL",
    # Microsoft
    "microsoft":               "MSFT",
    "msft":                    "MSFT",
    # Alphabet / Google
    "google":                  "GOOGL",
    "alphabet":                "GOOGL",
    "googl":                   "GOOGL",
    # Amazon
    "amazon":                  "AMZN",
    "amzn":                    "AMZN",
    # Meta
    "meta":                    "META",
    "facebook":                "META",
    "fb":                      "META",
    # NVIDIA
    "nvidia":                  "NVDA",
    "nvda":                    "NVDA",
    # Tesla
    "tesla":                   "TSLA",
    "tsla":                    "TSLA",
    # Berkshire
    "berkshire":               "BRK.B",
    "berkshire hathaway":      "BRK.B",
    # JPMorgan
    "jpmorgan":                "JPM",
    "jp morgan":               "JPM",
    "j.p. morgan":             "JPM",
    # Goldman Sachs
    "goldman sachs":           "GS",
    "goldman":                 "GS",
    # Bank of America
    "bank of america":         "BAC",
    "bofa":                    "BAC",
    "bac":                     "BAC",
    # Wells Fargo
    "wells fargo":             "WFC",
    # Citigroup
    "citigroup":               "C",
    "citi":                    "C",
    # Visa
    "visa":                    "V",
    # Mastercard
    "mastercard":              "MA",
    # PayPal
    "paypal":                  "PYPL",
    # Netflix
    "netflix":                 "NFLX",
    # Disney
    "disney":                  "DIS",
    "walt disney":             "DIS",
    # Boeing
    "boeing":                  "BA",
    # Johnson & Johnson
    "johnson & johnson":       "JNJ",
    "j&j":                     "JNJ",
    "jnj":                     "JNJ",
    # Pfizer
    "pfizer":                  "PFE",
    # Moderna
    "moderna":                 "MRNA",
    # UnitedHealth
    "unitedhealth":            "UNH",
    "united health":           "UNH",
    # ExxonMobil
    "exxonmobil":              "XOM",
    "exxon":                   "XOM",
    # Chevron
    "chevron":                 "CVX",
    # ConocoPhillips
    "conocophillips":          "COP",
    "conoco":                  "COP",
    # Walmart
    "walmart":                 "WMT",
    # Target
    "target":                  "TGT",
    # Home Depot
    "home depot":              "HD",
    # Costco
    "costco":                  "COST",
    # Starbucks
    "starbucks":               "SBUX",
    # McDonald's
    "mcdonalds":               "MCD",
    "mcdonald's":              "MCD",
    # Nike
    "nike":                    "NKE",
    # AMD
    "amd":                     "AMD",
    "advanced micro devices":  "AMD",
    # Intel
    "intel":                   "INTC",
    # Qualcomm
    "qualcomm":                "QCOM",
    # Broadcom
    "broadcom":                "AVGO",
    # TSMC
    "tsmc":                    "TSM",
    "taiwan semiconductor":    "TSM",
    # Salesforce
    "salesforce":              "CRM",
    # Oracle
    "oracle":                  "ORCL",
    # ServiceNow
    "servicenow":              "NOW",
    # Snowflake
    "snowflake":               "SNOW",
    # Palantir
    "palantir":                "PLTR",
    # Cloudflare
    "cloudflare":              "NET",
    # CrowdStrike
    "crowdstrike":             "CRWD",
    # Palo Alto Networks
    "palo alto networks":      "PANW",
    "palo alto":               "PANW",
    # Uber
    "uber":                    "UBER",
    # Lyft
    "lyft":                    "LYFT",
    # Airbnb
    "airbnb":                  "ABNB",
    # Coinbase
    "coinbase":                "COIN",
    # Spotify
    "spotify":                 "SPOT",
    # Shopify
    "shopify":                 "SHOP",
    # Arm Holdings
    "arm":                     "ARM",
    "arm holdings":            "ARM",
    # Super Micro
    "super micro":             "SMCI",
    "supermicro":              "SMCI",
    # Micron
    "micron":                  "MU",
    # Applied Materials
    "applied materials":       "AMAT",
    # ASML
    "asml":                    "ASML",
    # Lam Research
    "lam research":            "LRCX",
    # Texas Instruments
    "texas instruments":       "TXN",
    # Caterpillar
    "caterpillar":             "CAT",
    # Deere
    "deere":                   "DE",
    "john deere":              "DE",
    # 3M
    "3m":                      "MMM",
    # Honeywell
    "honeywell":               "HON",
    # GE
    "general electric":        "GE",
    "ge":                      "GE",
    # Raytheon / RTX
    "raytheon":                "RTX",
    # Lockheed Martin
    "lockheed martin":         "LMT",
    "lockheed":                "LMT",
    # Northrop Grumman
    "northrop grumman":        "NOC",
    "northrop":                "NOC",
    # United Airlines
    "united airlines":         "UAL",
    # Delta
    "delta air lines":         "DAL",
    "delta":                   "DAL",
    # Southwest Airlines
    "southwest airlines":      "LUV",
    "southwest":               "LUV",
    # Marriott
    "marriott":                "MAR",
    # Hilton
    "hilton":                  "HLT",
    # Carnival
    "carnival":                "CCL",
    # Royal Caribbean
    "royal caribbean":         "RCL",
    # AbbVie
    "abbvie":                  "ABBV",
    # Eli Lilly
    "eli lilly":               "LLY",
    "lilly":                   "LLY",
    # Merck
    "merck":                   "MRK",
    # Bristol-Myers
    "bristol myers":           "BMY",
    "bms":                     "BMY",
    # Regeneron
    "regeneron":               "REGN",
    # Intuit
    "intuit":                  "INTU",
    # Adobe
    "adobe":                   "ADBE",
}

# Pre-sort alias keys by length (descending) so that the longest match wins
# in _alias_lookup without extra work at call time.
_ALIAS_KEYS_BY_LENGTH: list[str] = sorted(_ALIAS_MAP.keys(), key=len, reverse=True)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")


def _make_context(ticker: str, matched_alias: str) -> CompanyContext:
    """Build a CompanyContext from *ticker*, falling back gracefully if unknown."""
    info = _COMPANY_DB.get(ticker)
    if info:
        return CompanyContext(
            ticker=ticker,
            company_name=info["company_name"],
            sector=info.get("sector"),
            industry=info.get("industry"),
            aliases=[matched_alias],
        )
    # Ticker not in DB — return a minimal context so callers still get something.
    return CompanyContext(
        ticker=ticker,
        company_name=ticker,
        sector=None,
        industry=None,
        aliases=[matched_alias] if matched_alias else [],
    )


def _extract_explicit_ticker(text: str) -> Optional[CompanyContext]:
    """Step 1 — scan *text* for an uppercase word that is a known ticker.

    Candidates must pass the stop-word filter and appear as a key in
    ``_COMPANY_DB``.  The first matching candidate wins.
    """
    for match in _TICKER_RE.finditer(text):
        candidate = match.group(1)
        if candidate in _TICKER_STOP_WORDS:
            continue
        if candidate in _COMPANY_DB:
            return _make_context(candidate, candidate)
    return None


def _alias_lookup(text: str) -> Optional[CompanyContext]:
    """Step 2 — substring search over lowercased *text*.

    Iterates aliases from longest to shortest so that a more-specific alias
    (e.g. ``"berkshire hathaway"``) beats a shorter one (``"berkshire"``).
    """
    lower = text.lower()
    for alias in _ALIAS_KEYS_BY_LENGTH:
        if alias in lower:
            ticker = _ALIAS_MAP[alias]
            return _make_context(ticker, alias)
    return None


def _fuzzy_match(text: str) -> Optional[CompanyContext]:
    """Step 3 — fuzzy match *text* against the alias key list via difflib."""
    lower = text.lower()
    matches = difflib.get_close_matches(
        lower, list(_ALIAS_MAP.keys()), n=1, cutoff=0.82
    )
    if matches:
        alias = matches[0]
        ticker = _ALIAS_MAP[alias]
        return _make_context(ticker, alias)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_company(text: str) -> Optional[CompanyContext]:
    """Detect and normalise the company referenced in *text*.

    Runs three detection steps in order:

    1. Explicit uppercase ticker extraction.
    2. Alias substring lookup (longest match first).
    3. Fuzzy alias match (difflib cutoff 0.82).

    Prints a ``[DIAG]`` line showing which method resolved the company (or
    ``not found``).

    Parameters
    ----------
    text:
        Free-text user query, e.g. ``"What is Apple's revenue forecast?"``.

    Returns
    -------
    CompanyContext or None
        Populated context on success; ``None`` when no company can be
        identified.
    """
    ctx = _extract_explicit_ticker(text)
    if ctx is not None:
        print(f"[DIAG] company_detection: resolved '{ctx.ticker}' via explicit ticker extraction")
        return ctx

    ctx = _alias_lookup(text)
    if ctx is not None:
        print(f"[DIAG] company_detection: resolved '{ctx.ticker}' via alias lookup (alias='{ctx.aliases[0]}')")
        return ctx

    ctx = _fuzzy_match(text)
    if ctx is not None:
        print(f"[DIAG] company_detection: resolved '{ctx.ticker}' via fuzzy match (alias='{ctx.aliases[0]}')")
        return ctx

    print("[DIAG] company_detection: not found")
    return None


def normalize_ticker(raw: str) -> Optional[CompanyContext]:
    """Resolve *raw* — expected to already be a ticker or company name — to a
    ``CompanyContext``.

    This is a thin wrapper around :func:`detect_company` intended for callers
    that already have an isolated token rather than a full sentence.

    Parameters
    ----------
    raw:
        A raw ticker symbol or company name, e.g. ``"AAPL"`` or ``"apple"``.

    Returns
    -------
    CompanyContext or None
    """
    return detect_company(raw)
