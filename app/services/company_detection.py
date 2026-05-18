"""company_detection.py — detect and normalise company names / ticker symbols.

Public API
----------
detect_company(text: str) -> Optional[CompanyContext]
    Backward-compatible helper.  Returns the resolved CompanyContext or None.

normalize_ticker(raw: str) -> Optional[CompanyContext]
    Thin wrapper around detect_company for already-isolated tokens.

resolve_entity(text: str) -> EntityResolution
    Full resolution with confidence score, resolution method, and candidate
    suggestions for low-confidence cases.  Preferred for new callsites.

Detection pipeline (in order)
------------------------------
1. Explicit uppercase ticker extraction — regex + stop-word filter.
2. Alias substring lookup  — longest-match-first on the full lowercased text.
3. Token-window fuzzy match — N-gram windows extracted from the *normalised*
   text are compared against all alias keys via difflib (cutoff 0.72).
   This step handles typos embedded in natural-language sentences, e.g.
   "Is Nvidea overvalued?" or "What do you think about Roket Lab?".

Confidence thresholds
---------------------
exact_ticker  : 1.00
alias_exact   : 0.95
fuzzy_token   : scaled 0.72 – 0.95 from the difflib ratio
not_found     : 0.00  (candidates populated for "Did you mean?" UX)

No network calls are made; no external API keys are required.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.schemas import CompanyContext

logger = logging.getLogger(__name__)

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
    # ── New entries ───────────────────────────────────────────────────────────
    "RKLB":  {"company_name": "Rocket Lab USA Inc.",                     "sector": "Industrials",               "industry": "Aerospace & Defense"},
    "RIVN":  {"company_name": "Rivian Automotive Inc.",                  "sector": "Consumer Discretionary",    "industry": "Electric Vehicles"},
    "LCID":  {"company_name": "Lucid Group Inc.",                        "sector": "Consumer Discretionary",    "industry": "Electric Vehicles"},
    "F":     {"company_name": "Ford Motor Company",                      "sector": "Consumer Discretionary",    "industry": "Automobiles"},
    "GM":    {"company_name": "General Motors Company",                  "sector": "Consumer Discretionary",    "industry": "Automobiles"},
    "SNAP":  {"company_name": "Snap Inc.",                               "sector": "Communication Services",    "industry": "Social Media"},
    "PINS":  {"company_name": "Pinterest Inc.",                          "sector": "Communication Services",    "industry": "Social Media"},
    "ZM":    {"company_name": "Zoom Video Communications Inc.",          "sector": "Technology",                "industry": "Video Conferencing"},
    "DDOG":  {"company_name": "Datadog Inc.",                            "sector": "Technology",                "industry": "Cloud Monitoring"},
    "HOOD":  {"company_name": "Robinhood Markets Inc.",                  "sector": "Financials",                "industry": "Brokerage"},
    "DASH":  {"company_name": "DoorDash Inc.",                           "sector": "Consumer Discretionary",    "industry": "Food Delivery"},
    "RBLX":  {"company_name": "Roblox Corporation",                      "sector": "Communication Services",    "industry": "Gaming"},
    "SOFI":  {"company_name": "SoFi Technologies Inc.",                  "sector": "Financials",                "industry": "Fintech"},
    "MSTR":  {"company_name": "MicroStrategy Inc.",                      "sector": "Technology",                "industry": "Business Intelligence"},
    "JOBY":  {"company_name": "Joby Aviation Inc.",                      "sector": "Industrials",               "industry": "Urban Air Mobility"},
    "SPCE":  {"company_name": "Virgin Galactic Holdings Inc.",           "sector": "Industrials",               "industry": "Aerospace"},
    "NKLA":  {"company_name": "Nikola Corporation",                      "sector": "Industrials",               "industry": "Electric Vehicles"},
    "CHWY":  {"company_name": "Chewy Inc.",                              "sector": "Consumer Discretionary",    "industry": "E-Commerce"},
    "ETSY":  {"company_name": "Etsy Inc.",                               "sector": "Consumer Discretionary",    "industry": "E-Commerce"},
    "W":     {"company_name": "Wayfair Inc.",                            "sector": "Consumer Discretionary",    "industry": "E-Commerce"},
    "TWLO":  {"company_name": "Twilio Inc.",                             "sector": "Technology",                "industry": "Cloud Communications"},
    "SQ":    {"company_name": "Block Inc.",                              "sector": "Financials",                "industry": "Fintech"},
    "AFRM":  {"company_name": "Affirm Holdings Inc.",                    "sector": "Financials",                "industry": "Fintech"},
    "OPEN":  {"company_name": "Opendoor Technologies Inc.",              "sector": "Consumer Discretionary",    "industry": "Real Estate Tech"},
    "ROKU":  {"company_name": "Roku Inc.",                               "sector": "Communication Services",    "industry": "Streaming"},
    "TTD":   {"company_name": "The Trade Desk Inc.",                     "sector": "Technology",                "industry": "Advertising Tech"},
    "ZS":    {"company_name": "Zscaler Inc.",                            "sector": "Technology",                "industry": "Cybersecurity"},
    "OKTA":  {"company_name": "Okta Inc.",                               "sector": "Technology",                "industry": "Identity Security"},
    "GTLB":  {"company_name": "GitLab Inc.",                             "sector": "Technology",                "industry": "DevOps Software"},
    "PATH":  {"company_name": "UiPath Inc.",                             "sector": "Technology",                "industry": "Automation Software"},
    "AI":    {"company_name": "C3.ai Inc.",                              "sector": "Technology",                "industry": "Enterprise AI"},
    "SOUN":  {"company_name": "SoundHound AI Inc.",                      "sector": "Technology",                "industry": "Voice AI"},
    "BBAI":  {"company_name": "BigBear.ai Holdings Inc.",                "sector": "Technology",                "industry": "AI Analytics"},
    "RGTI":  {"company_name": "Rigetti Computing Inc.",                  "sector": "Technology",                "industry": "Quantum Computing"},
    "IONQ":  {"company_name": "IonQ Inc.",                               "sector": "Technology",                "industry": "Quantum Computing"},
}

# ---------------------------------------------------------------------------
# Alias map — lowercase alias → ticker
# ---------------------------------------------------------------------------

_ALIAS_MAP: dict[str, str] = {
    # ── Apple ─────────────────────────────────────────────────────────────────
    "apple":                   "AAPL",
    "apple inc":               "AAPL",
    # typos
    "aple":                    "AAPL",
    "appel":                   "AAPL",
    "appl":                    "AAPL",
    "aplle":                   "AAPL",

    # ── Microsoft ─────────────────────────────────────────────────────────────
    "microsoft":               "MSFT",
    "msft":                    "MSFT",
    # typos
    "microsfot":               "MSFT",
    "microsft":                "MSFT",
    "micorsoft":               "MSFT",
    "micosoft":                "MSFT",
    "microsofft":              "MSFT",

    # ── Alphabet / Google ─────────────────────────────────────────────────────
    "google":                  "GOOGL",
    "alphabet":                "GOOGL",
    "googl":                   "GOOGL",
    "google cloud":            "GOOGL",
    "google search":           "GOOGL",
    # typos
    "goggle":                  "GOOGL",
    "gogle":                   "GOOGL",
    "goooogle":                "GOOGL",
    "googel":                  "GOOGL",
    "gooogle":                 "GOOGL",

    # ── Amazon ────────────────────────────────────────────────────────────────
    "amazon":                  "AMZN",
    "amzn":                    "AMZN",
    "amazon web services":     "AMZN",
    "aws":                     "AMZN",

    # ── Meta ──────────────────────────────────────────────────────────────────
    "meta":                    "META",
    "facebook":                "META",
    "fb":                      "META",
    "instagram":               "META",
    "whatsapp":                "META",
    "meta platforms":          "META",

    # ── NVIDIA ────────────────────────────────────────────────────────────────
    "nvidia":                  "NVDA",
    "nvda":                    "NVDA",
    # typos
    "nvidea":                  "NVDA",
    "nvidai":                  "NVDA",
    "nvdia":                   "NVDA",
    "nividia":                 "NVDA",
    "nviida":                  "NVDA",
    "nvdia corporation":       "NVDA",

    # ── Tesla ─────────────────────────────────────────────────────────────────
    "tesla":                   "TSLA",
    "tsla":                    "TSLA",
    "tesla motors":            "TSLA",

    # ── Rocket Lab ────────────────────────────────────────────────────────────
    "rocket lab":              "RKLB",
    "rklb":                    "RKLB",
    "rocket lab usa":          "RKLB",
    "rocketlab":               "RKLB",
    # typos
    "roket lab":               "RKLB",
    "rocket labs":             "RKLB",
    "rocket laab":             "RKLB",
    "rocekt lab":              "RKLB",

    # ── Berkshire ─────────────────────────────────────────────────────────────
    "berkshire":               "BRK.B",
    "berkshire hathaway":      "BRK.B",

    # ── JPMorgan ──────────────────────────────────────────────────────────────
    "jpmorgan":                "JPM",
    "jp morgan":               "JPM",
    "j.p. morgan":             "JPM",
    "jpmorgan chase":          "JPM",

    # ── Goldman Sachs ─────────────────────────────────────────────────────────
    "goldman sachs":           "GS",
    "goldman":                 "GS",

    # ── Bank of America ───────────────────────────────────────────────────────
    "bank of america":         "BAC",
    "bofa":                    "BAC",
    "bac":                     "BAC",

    # ── Wells Fargo ───────────────────────────────────────────────────────────
    "wells fargo":             "WFC",

    # ── Citigroup ─────────────────────────────────────────────────────────────
    "citigroup":               "C",
    "citi":                    "C",
    "citibank":                "C",

    # ── Visa ──────────────────────────────────────────────────────────────────
    "visa":                    "V",

    # ── Mastercard ────────────────────────────────────────────────────────────
    "mastercard":              "MA",

    # ── PayPal ────────────────────────────────────────────────────────────────
    "paypal":                  "PYPL",

    # ── Netflix ───────────────────────────────────────────────────────────────
    "netflix":                 "NFLX",

    # ── Disney ────────────────────────────────────────────────────────────────
    "disney":                  "DIS",
    "walt disney":             "DIS",

    # ── Boeing ────────────────────────────────────────────────────────────────
    "boeing":                  "BA",

    # ── J&J ───────────────────────────────────────────────────────────────────
    "johnson & johnson":       "JNJ",
    "j&j":                     "JNJ",
    "jnj":                     "JNJ",

    # ── Pfizer ────────────────────────────────────────────────────────────────
    "pfizer":                  "PFE",

    # ── Moderna ───────────────────────────────────────────────────────────────
    "moderna":                 "MRNA",

    # ── UnitedHealth ──────────────────────────────────────────────────────────
    "unitedhealth":            "UNH",
    "united health":           "UNH",

    # ── ExxonMobil ────────────────────────────────────────────────────────────
    "exxonmobil":              "XOM",
    "exxon":                   "XOM",
    "exxon mobil":             "XOM",

    # ── Chevron ───────────────────────────────────────────────────────────────
    "chevron":                 "CVX",

    # ── ConocoPhillips ────────────────────────────────────────────────────────
    "conocophillips":          "COP",
    "conoco":                  "COP",

    # ── Walmart ───────────────────────────────────────────────────────────────
    "walmart":                 "WMT",
    "wal-mart":                "WMT",

    # ── Target ────────────────────────────────────────────────────────────────
    "target":                  "TGT",

    # ── Home Depot ────────────────────────────────────────────────────────────
    "home depot":              "HD",

    # ── Costco ────────────────────────────────────────────────────────────────
    "costco":                  "COST",

    # ── Starbucks ─────────────────────────────────────────────────────────────
    "starbucks":               "SBUX",

    # ── McDonald's ────────────────────────────────────────────────────────────
    "mcdonalds":               "MCD",
    "mcdonald's":              "MCD",
    "mcdonald":                "MCD",

    # ── Nike ──────────────────────────────────────────────────────────────────
    "nike":                    "NKE",

    # ── AMD ───────────────────────────────────────────────────────────────────
    "amd":                     "AMD",
    "advanced micro devices":  "AMD",

    # ── Intel ─────────────────────────────────────────────────────────────────
    "intel":                   "INTC",

    # ── Qualcomm ──────────────────────────────────────────────────────────────
    "qualcomm":                "QCOM",

    # ── Broadcom ──────────────────────────────────────────────────────────────
    "broadcom":                "AVGO",

    # ── TSMC ──────────────────────────────────────────────────────────────────
    "tsmc":                    "TSM",
    "taiwan semiconductor":    "TSM",

    # ── Salesforce ────────────────────────────────────────────────────────────
    "salesforce":              "CRM",

    # ── Oracle ────────────────────────────────────────────────────────────────
    "oracle":                  "ORCL",

    # ── ServiceNow ────────────────────────────────────────────────────────────
    "servicenow":              "NOW",

    # ── Snowflake ─────────────────────────────────────────────────────────────
    "snowflake":               "SNOW",

    # ── Palantir ──────────────────────────────────────────────────────────────
    "palantir":                "PLTR",

    # ── Cloudflare ────────────────────────────────────────────────────────────
    "cloudflare":              "NET",

    # ── CrowdStrike ───────────────────────────────────────────────────────────
    "crowdstrike":             "CRWD",
    "crowd strike":            "CRWD",

    # ── Palo Alto Networks ────────────────────────────────────────────────────
    "palo alto networks":      "PANW",
    "palo alto":               "PANW",

    # ── Uber ──────────────────────────────────────────────────────────────────
    "uber":                    "UBER",

    # ── Lyft ──────────────────────────────────────────────────────────────────
    "lyft":                    "LYFT",

    # ── Airbnb ────────────────────────────────────────────────────────────────
    "airbnb":                  "ABNB",
    "air bnb":                 "ABNB",

    # ── Coinbase ──────────────────────────────────────────────────────────────
    "coinbase":                "COIN",

    # ── Spotify ───────────────────────────────────────────────────────────────
    "spotify":                 "SPOT",

    # ── Shopify ───────────────────────────────────────────────────────────────
    "shopify":                 "SHOP",

    # ── Arm Holdings ──────────────────────────────────────────────────────────
    "arm":                     "ARM",
    "arm holdings":            "ARM",

    # ── Super Micro ───────────────────────────────────────────────────────────
    "super micro":             "SMCI",
    "supermicro":              "SMCI",

    # ── Micron ────────────────────────────────────────────────────────────────
    "micron":                  "MU",
    "micron technology":       "MU",

    # ── Applied Materials ─────────────────────────────────────────────────────
    "applied materials":       "AMAT",

    # ── ASML ──────────────────────────────────────────────────────────────────
    "asml":                    "ASML",

    # ── Lam Research ──────────────────────────────────────────────────────────
    "lam research":            "LRCX",

    # ── Texas Instruments ─────────────────────────────────────────────────────
    "texas instruments":       "TXN",

    # ── Caterpillar ───────────────────────────────────────────────────────────
    "caterpillar":             "CAT",

    # ── Deere ─────────────────────────────────────────────────────────────────
    "deere":                   "DE",
    "john deere":              "DE",

    # ── 3M ────────────────────────────────────────────────────────────────────
    "3m":                      "MMM",

    # ── Honeywell ─────────────────────────────────────────────────────────────
    "honeywell":               "HON",

    # ── GE ────────────────────────────────────────────────────────────────────
    "general electric":        "GE",
    "ge aerospace":            "GE",

    # ── Raytheon / RTX ────────────────────────────────────────────────────────
    "raytheon":                "RTX",
    "rtx":                     "RTX",

    # ── Lockheed Martin ───────────────────────────────────────────────────────
    "lockheed martin":         "LMT",
    "lockheed":                "LMT",

    # ── Northrop Grumman ──────────────────────────────────────────────────────
    "northrop grumman":        "NOC",
    "northrop":                "NOC",

    # ── United Airlines ───────────────────────────────────────────────────────
    "united airlines":         "UAL",

    # ── Delta ─────────────────────────────────────────────────────────────────
    "delta air lines":         "DAL",
    "delta airlines":          "DAL",
    "delta":                   "DAL",

    # ── Southwest Airlines ────────────────────────────────────────────────────
    "southwest airlines":      "LUV",
    "southwest":               "LUV",

    # ── Marriott ──────────────────────────────────────────────────────────────
    "marriott":                "MAR",

    # ── Hilton ────────────────────────────────────────────────────────────────
    "hilton":                  "HLT",

    # ── Carnival ──────────────────────────────────────────────────────────────
    "carnival":                "CCL",

    # ── Royal Caribbean ───────────────────────────────────────────────────────
    "royal caribbean":         "RCL",

    # ── AbbVie ────────────────────────────────────────────────────────────────
    "abbvie":                  "ABBV",

    # ── Eli Lilly ─────────────────────────────────────────────────────────────
    "eli lilly":               "LLY",
    "lilly":                   "LLY",

    # ── Merck ─────────────────────────────────────────────────────────────────
    "merck":                   "MRK",

    # ── Bristol-Myers ─────────────────────────────────────────────────────────
    "bristol myers":           "BMY",
    "bms":                     "BMY",

    # ── Regeneron ─────────────────────────────────────────────────────────────
    "regeneron":               "REGN",

    # ── Intuit ────────────────────────────────────────────────────────────────
    "intuit":                  "INTU",

    # ── Adobe ─────────────────────────────────────────────────────────────────
    "adobe":                   "ADBE",

    # ── New companies ─────────────────────────────────────────────────────────
    "rivian":                  "RIVN",
    "lucid":                   "LCID",
    "lucid motors":            "LCID",
    "ford":                    "F",
    "ford motor":              "F",
    "general motors":          "GM",
    "snap":                    "SNAP",
    "snapchat":                "SNAP",
    "pinterest":               "PINS",
    "zoom":                    "ZM",
    "zoom video":              "ZM",
    "datadog":                 "DDOG",
    "robinhood":               "HOOD",
    "doordash":                "DASH",
    "door dash":               "DASH",
    "roblox":                  "RBLX",
    "sofi":                    "SOFI",
    "sofi technologies":       "SOFI",
    "microstrategy":           "MSTR",
    "micro strategy":          "MSTR",
    "joby":                    "JOBY",
    "joby aviation":           "JOBY",
    "virgin galactic":         "SPCE",
    "nikola":                  "NKLA",
    "chewy":                   "CHWY",
    "etsy":                    "ETSY",
    "wayfair":                 "W",
    "twilio":                  "TWLO",
    "block":                   "SQ",
    "square":                  "SQ",
    "affirm":                  "AFRM",
    "opendoor":                "OPEN",
    "roku":                    "ROKU",
    "trade desk":              "TTD",
    "zscaler":                 "ZS",
    "okta":                    "OKTA",
    "gitlab":                  "GTLB",
    "uipath":                  "PATH",
    "c3 ai":                   "AI",
    "c3.ai":                   "AI",
    "soundhound":              "SOUN",
    "sound hound":             "SOUN",
}

# Pre-sort alias keys by length (descending) so that the longest match wins.
_ALIAS_KEYS_BY_LENGTH: list[str] = sorted(_ALIAS_MAP.keys(), key=len, reverse=True)

# Context words to strip when normalising a query.
_CONTEXT_WORDS: frozenset[str] = frozenset({
    "stock", "stocks", "share", "shares", "equity", "equities",
    "ticker", "company", "corporation", "inc", "ltd", "llc", "plc",
    "what", "think", "about", "tell", "me", "the", "is", "are",
    "how", "do", "does", "would", "could", "should", "will",
    "overvalued", "undervalued", "buy", "sell", "hold", "good", "bad",
    "analysis", "analyze", "analyse", "outlook", "forecast",
    "price", "target", "earnings", "revenue", "margins", "cloud",
    "worth", "investing", "invest",
    # Common English words that can fuzzy-match company names at our threshold
    "services", "service", "booming", "rising", "falling",
    "markets", "market", "sector", "industry", "today", "week",
})

# ---------------------------------------------------------------------------
# EntityResolution — structured result from resolve_entity()
# ---------------------------------------------------------------------------

@dataclass
class EntityResolution:
    """Structured result of fuzzy entity resolution.

    Attributes
    ----------
    context:
        Resolved CompanyContext, or None if no match was found.
    confidence:
        Float in [0.0, 1.0].  Thresholds:
        >= 0.90 → high confidence, proceed silently
        0.72 – 0.90 → medium confidence, proceed with warning log
        0.00 → not found, candidates populated for "Did you mean?" UX
    method:
        Resolution method: exact_ticker | alias_exact | fuzzy_token | not_found
    matched_text:
        The alias key, token window, or ticker that triggered the match.
    candidates:
        For not_found: list of (ticker, company_name, score) tuples,
        sorted by score descending.  Empty for successful resolutions.
    """
    context: Optional[CompanyContext]
    confidence: float
    method: str
    matched_text: str
    candidates: List[Tuple[str, str, float]] = field(default_factory=list)


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
    return CompanyContext(
        ticker=ticker,
        company_name=ticker,
        sector=None,
        industry=None,
        aliases=[matched_alias] if matched_alias else [],
    )


def _normalize_query(text: str) -> str:
    """Normalise a free-text query for fuzzy matching.

    Steps
    -----
    1. Lowercase.
    2. Replace punctuation (except hyphens) with spaces.
    3. Collapse whitespace.
    4. Remove context words that obscure company names.
    """
    t = text.lower()
    t = re.sub(r"[^\w\s-]", " ", t)      # punctuation → space
    t = re.sub(r"\s+", " ", t).strip()
    tokens = [tok for tok in t.split() if tok not in _CONTEXT_WORDS]
    return " ".join(tokens)


def _token_windows(text: str, max_ngram: int = 4) -> list[str]:
    """Generate all N-gram windows from *text*, longest first.

    Minimum window length: 3 characters (avoids matching noise tokens).
    """
    tokens = text.split()
    if not tokens:
        return []
    windows: list[str] = []
    for n in range(min(max_ngram, len(tokens)), 0, -1):
        for i in range(len(tokens) - n + 1):
            w = " ".join(tokens[i : i + n])
            if len(w) >= 3:
                windows.append(w)
    return windows


def _extract_explicit_ticker(text: str) -> Optional[CompanyContext]:
    """Step 1 — scan *text* for an uppercase word that is a known ticker."""
    for match in _TICKER_RE.finditer(text):
        candidate = match.group(1)
        if candidate in _TICKER_STOP_WORDS:
            continue
        if candidate in _COMPANY_DB:
            return _make_context(candidate, candidate)
    return None


def _alias_lookup(text: str) -> Optional[CompanyContext]:
    """Step 2 — substring search over lowercased *text*, longest alias first."""
    lower = text.lower()
    for alias in _ALIAS_KEYS_BY_LENGTH:
        if alias in lower:
            ticker = _ALIAS_MAP[alias]
            return _make_context(ticker, alias)
    return None


def _fuzzy_token_match(
    text: str,
    cutoff: float = 0.72,
) -> Optional[tuple[CompanyContext, float, str]]:
    """Step 3 — token-window fuzzy match against all alias keys.

    Normalises *text*, generates N-gram windows, and compares each window
    against every alias key via difflib.SequenceMatcher.  Returns the
    (context, score, matched_alias) triple for the best match above *cutoff*,
    or None.

    Using token windows instead of the full query text means that typos
    embedded in natural-language sentences are caught:
      "Is Nvidea overvalued?"   → window "nvidea" → matches "nvidia"  (0.83)
      "Roket Lab outlook?"      → window "roket lab" → matches "rocket lab" (0.95)
    """
    normalized = _normalize_query(text)
    if not normalized:
        return None

    alias_keys = list(_ALIAS_MAP.keys())
    best_score = 0.0
    best_alias: Optional[str] = None

    for window in _token_windows(normalized, max_ngram=4):
        # Quick pre-filter: only consider aliases whose length is within
        # a reasonable range of the window length (avoids matching
        # a 2-char window against a 15-char alias).
        wlen = len(window)
        close = difflib.get_close_matches(
            window,
            [k for k in alias_keys if abs(len(k) - wlen) <= max(4, wlen // 2)],
            n=5,
            cutoff=cutoff,
        )
        for match in close:
            score = difflib.SequenceMatcher(None, window, match).ratio()
            if score > best_score:
                best_score = score
                best_alias = match

    if best_alias and best_score >= cutoff:
        ticker = _ALIAS_MAP[best_alias]
        return _make_context(ticker, best_alias), best_score, best_alias

    return None


def _gather_candidates(
    text: str,
    n: int = 3,
    cutoff: float = 0.55,
) -> List[Tuple[str, str, float]]:
    """Return the top-N candidate matches for a failed resolution.

    Used to populate "Did you mean X?" suggestions.
    """
    normalized = _normalize_query(text)
    if not normalized:
        return []

    alias_keys = list(_ALIAS_MAP.keys())
    raw_candidates: list[tuple[str, float]] = []

    for window in _token_windows(normalized, max_ngram=3):
        close = difflib.get_close_matches(window, alias_keys, n=5, cutoff=cutoff)
        for match in close:
            score = difflib.SequenceMatcher(None, window, match).ratio()
            raw_candidates.append((_ALIAS_MAP[match], score))

    # Deduplicate: keep best score per ticker
    best_per_ticker: dict[str, float] = {}
    for ticker, score in raw_candidates:
        if ticker not in best_per_ticker or score > best_per_ticker[ticker]:
            best_per_ticker[ticker] = score

    results: List[Tuple[str, str, float]] = []
    for ticker, score in sorted(best_per_ticker.items(), key=lambda x: -x[1]):
        info = _COMPANY_DB.get(ticker, {})
        name = info.get("company_name", ticker)
        results.append((ticker, name, score))
        if len(results) >= n:
            break

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_entity(text: str) -> EntityResolution:
    """Full entity resolution with confidence scoring and structured observability.

    Runs the three detection steps in order and returns an
    :class:`EntityResolution` with a confidence score, resolution method, and
    candidate suggestions when no match is found.

    Parameters
    ----------
    text:
        Free-text user query or isolated company name / ticker.

    Returns
    -------
    EntityResolution
        Always returns an object (never raises).  Check ``context`` and
        ``confidence`` in the caller.
    """
    if not text or not text.strip():
        return EntityResolution(None, 0.0, "not_found", "", [])

    normalized = _normalize_query(text)
    logger.info(
        "[entity_resolution] raw=%r normalized=%r",
        text[:120],
        normalized[:120],
    )

    # ── Step 1: explicit uppercase ticker ────────────────────────────────────
    ctx = _extract_explicit_ticker(text)
    if ctx is not None:
        logger.info(
            "[entity_resolution] method=exact_ticker entity=%s conf=1.00",
            ctx.ticker,
        )
        return EntityResolution(ctx, 1.0, "exact_ticker", ctx.ticker)

    # ── Step 2: alias exact substring match ───────────────────────────────────
    ctx = _alias_lookup(text)
    if ctx is not None:
        alias = ctx.aliases[0] if ctx.aliases else ""
        logger.info(
            "[entity_resolution] method=alias_exact entity=%s alias=%r conf=0.95",
            ctx.ticker,
            alias,
        )
        return EntityResolution(ctx, 0.95, "alias_exact", alias)

    # ── Step 3: token-window fuzzy match ─────────────────────────────────────
    fuzzy_result = _fuzzy_token_match(text, cutoff=0.72)
    if fuzzy_result is not None:
        ctx, score, matched_alias = fuzzy_result
        # Scale difflib ratio (0.72 – 1.0) → confidence (0.72 – 0.95)
        confidence = round(0.50 + score * 0.47, 3)
        logger.info(
            "[entity_resolution] method=fuzzy_token entity=%s alias=%r "
            "score=%.3f conf=%.3f",
            ctx.ticker,
            matched_alias,
            score,
            confidence,
        )
        return EntityResolution(ctx, confidence, "fuzzy_token", matched_alias)

    # ── Not found — gather candidates ─────────────────────────────────────────
    candidates = _gather_candidates(text)
    logger.info(
        "[entity_resolution] method=not_found candidates=%s",
        [(t, s) for t, _, s in candidates],
    )
    return EntityResolution(None, 0.0, "not_found", "", candidates)


def detect_company(text: str) -> Optional[CompanyContext]:
    """Detect and normalise the company referenced in *text*.

    Backward-compatible wrapper around :func:`resolve_entity`.  Returns the
    resolved :class:`CompanyContext` for any confidence >= 0.72, or ``None``
    when no company can be identified.

    Parameters
    ----------
    text:
        Free-text user query, e.g. ``"What is Apple's revenue forecast?"``.

    Returns
    -------
    CompanyContext or None
    """
    resolution = resolve_entity(text)
    if resolution.context is not None and resolution.confidence >= 0.72:
        logger.debug(
            "[company_detection] resolved %s via %s (conf=%.2f alias=%r)",
            resolution.context.ticker,
            resolution.method,
            resolution.confidence,
            resolution.matched_text,
        )
        return resolution.context

    if resolution.candidates:
        logger.debug(
            "[company_detection] not_found — top candidates: %s",
            [(t, f"{s:.2f}") for t, _, s in resolution.candidates[:3]],
        )
    else:
        logger.debug("[company_detection] not_found for text=%r", text[:80])
    return None


def normalize_ticker(raw: str) -> Optional[CompanyContext]:
    """Resolve *raw* — expected to be a ticker or company name — to a
    :class:`CompanyContext`.

    Thin wrapper around :func:`detect_company` intended for callers that
    already have an isolated token rather than a full sentence.
    """
    return detect_company(raw)
