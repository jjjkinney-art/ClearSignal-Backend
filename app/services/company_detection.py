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
2. Alias word-boundary lookup — longest-match-first on the full lowercased
   text, using ``\\b`` word boundaries so that "arm" does NOT match inside
   "pharmaceuticals".  This prevents the ARM Holdings / Vertex Pharma class
   of false-positive resolution.
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

Routing gate
------------
MINIMUM_ROUTE_CONFIDENCE : 0.85
    Hard floor used by the router_service.  Fuzzy matches below this value
    are surfaced as "Did you mean?" suggestions rather than being silently
    routed to the wrong company's investment pipeline.

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
# Routing confidence gate
# ---------------------------------------------------------------------------

# Hard minimum confidence for the router to send a query to the investment
# pipeline.  alias_exact (0.95) and exact_ticker (1.00) always clear this bar.
# fuzzy_token matches below this threshold are treated as "not found" by the
# router and surfaced as "Did you mean?" candidates rather than silently
# routed to the wrong company.
MINIMUM_ROUTE_CONFIDENCE: float = 0.85

# ---------------------------------------------------------------------------
# Stop-words — common English words that look like valid tickers
# ---------------------------------------------------------------------------

_TICKER_STOP_WORDS: frozenset[str] = frozenset({
    "A", "I", "IT", "IS", "IN", "ON", "OF", "AT", "BE", "BY", "DO", "GO",
    "IF", "NO", "OR", "TO", "UP", "US", "WE", "AN", "AS", "AM", "ARE",
    "ALL", "AND", "BUT", "CAN", "FOR", "GET", "GOT", "HAD", "HAS", "HIM",
    "HIS", "HOW", "ITS", "LET", "MAY", "ME", "MY", "NEW", "NOT",
    # "NOW" removed (Severity-1b): ServiceNow ticker; uppercase NOW on a financial
    # platform almost always refers to the ticker, not the English adverb.
    # Long-form alias "servicenow" still handles natural-language queries.
    "OFF", "OLD", "OUR", "OUT", "OWN", "SAY", "SHE",
    # "SO" removed (Severity-1b): Southern Company ticker; uppercase SO in
    # financial queries almost always refers to the ticker, not a conjunction.
    # Long-form alias "southern company" still handles natural-language queries.
    "THE", "TOO",
    "TWO", "USE", "WAS", "WAY", "WHO", "WHY", "WIN", "WITH", "YES", "YET",
    "YOU",
    # ── Protected generic-word tickers ────────────────────────────────────────
    # These are valid ticker symbols that are ALSO common English words.
    # Prevent them from being auto-resolved in free-text queries — they are
    # handled explicitly via alias lookup ("c3 ai", "applovin", "cloudflare",
    # "snowflake", "doordash", "shopify", "uipath", "opendoor", "arm holdings")
    # or via the entity_resolution_service clarification flow.
    "AI",   # C3.ai — "AI" most commonly means artificial intelligence in prose
    "APP",  # AppLovin — "app" is a ubiquitous English word
    "NET",  # Cloudflare — "net" is a common noun/adjective
    # "SNOW" removed (Severity-1b): Snowflake ticker; uppercase SNOW on a financial
    # platform almost always refers to the ticker, not the weather term. The alias
    # "snowflake" handles natural-language queries; PROTECTED_GENERIC_TICKERS still
    # flags genuinely ambiguous low-confidence cases.
    "DASH", # DoorDash — "dash" is a common verb/noun
    "PATH", # UiPath — "path" is a common noun
    "OPEN", # Opendoor — "open" is a common adjective/verb
    "SHOP", # Shopify — "shop" is a common verb/noun (Shopify resolves via alias)
    "ARM",  # Arm Holdings — "arm" is a body part (resolves via "arm holdings" alias)
    # "NOW" removed — see first block above.
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
    "APP":   {"company_name": "AppLovin Corporation",                     "sector": "Technology",                "industry": "Mobile Advertising"},
    "SOUN":  {"company_name": "SoundHound AI Inc.",                      "sector": "Technology",                "industry": "Voice AI"},
    "BBAI":  {"company_name": "BigBear.ai Holdings Inc.",                "sector": "Technology",                "industry": "AI Analytics"},
    "RGTI":  {"company_name": "Rigetti Computing Inc.",                  "sector": "Technology",                "industry": "Quantum Computing"},
    "IONQ":  {"company_name": "IonQ Inc.",                               "sector": "Technology",                "industry": "Quantum Computing"},

    # ── Pharma & Biotech (regression coverage) ────────────────────────────────
    "VRTX":  {"company_name": "Vertex Pharmaceuticals Inc.",             "sector": "Health Care",               "industry": "Biotechnology"},
    "NVO":   {"company_name": "Novo Nordisk A/S",                        "sector": "Health Care",               "industry": "Pharmaceuticals"},
    "ISRG":  {"company_name": "Intuitive Surgical Inc.",                 "sector": "Health Care",               "industry": "Medical Devices"},
    "CRSP":  {"company_name": "CRISPR Therapeutics AG",                  "sector": "Health Care",               "industry": "Biotechnology"},
    "AZN":   {"company_name": "AstraZeneca PLC",                         "sector": "Health Care",               "industry": "Pharmaceuticals"},
    "RHHBY": {"company_name": "Roche Holding AG",                        "sector": "Health Care",               "industry": "Pharmaceuticals"},
    "BNTX":  {"company_name": "BioNTech SE",                             "sector": "Health Care",               "industry": "Biotechnology"},
    "BIIB":  {"company_name": "Biogen Inc.",                             "sector": "Health Care",               "industry": "Biotechnology"},
    "GILD":  {"company_name": "Gilead Sciences Inc.",                    "sector": "Health Care",               "industry": "Biotechnology"},
    "AMGN":  {"company_name": "Amgen Inc.",                              "sector": "Health Care",               "industry": "Biotechnology"},
    "ILMN":  {"company_name": "Illumina Inc.",                           "sector": "Health Care",               "industry": "Genomics"},
    "DXCM":  {"company_name": "DexCom Inc.",                             "sector": "Health Care",               "industry": "Medical Devices"},
    "VEEV":  {"company_name": "Veeva Systems Inc.",                      "sector": "Health Care",               "industry": "Healthcare Software"},
    "INCY":  {"company_name": "Incyte Corporation",                      "sector": "Health Care",               "industry": "Biotechnology"},
    "ALNY":  {"company_name": "Alnylam Pharmaceuticals Inc.",            "sector": "Health Care",               "industry": "Biotechnology"},
    "SGEN":  {"company_name": "Seagen Inc.",                             "sector": "Health Care",               "industry": "Biotechnology"},
    "EXAS":  {"company_name": "Exact Sciences Corporation",              "sector": "Health Care",               "industry": "Diagnostics"},
    "SRPT":  {"company_name": "Sarepta Therapeutics Inc.",               "sector": "Health Care",               "industry": "Biotechnology"},
    "NTLA":  {"company_name": "Intellia Therapeutics Inc.",              "sector": "Health Care",               "industry": "Biotechnology"},
    "BEAM":  {"company_name": "Beam Therapeutics Inc.",                  "sector": "Health Care",               "industry": "Biotechnology"},
    "EDIT":  {"company_name": "Editas Medicine Inc.",                    "sector": "Health Care",               "industry": "Biotechnology"},
    "ZBH":   {"company_name": "Zimmer Biomet Holdings Inc.",             "sector": "Health Care",               "industry": "Medical Devices"},
    "SYK":   {"company_name": "Stryker Corporation",                     "sector": "Health Care",               "industry": "Medical Devices"},
    "BSX":   {"company_name": "Boston Scientific Corporation",           "sector": "Health Care",               "industry": "Medical Devices"},
    "MDT":   {"company_name": "Medtronic plc",                           "sector": "Health Care",               "industry": "Medical Devices"},
    "ABT":   {"company_name": "Abbott Laboratories",                     "sector": "Health Care",               "industry": "Medical Devices"},
    "DHR":   {"company_name": "Danaher Corporation",                     "sector": "Health Care",               "industry": "Life Sciences Tools"},
    "TMO":   {"company_name": "Thermo Fisher Scientific Inc.",           "sector": "Health Care",               "industry": "Life Sciences Tools"},
    "A":     {"company_name": "Agilent Technologies Inc.",               "sector": "Health Care",               "industry": "Life Sciences Tools"},
    "EW":    {"company_name": "Edwards Lifesciences Corporation",        "sector": "Health Care",               "industry": "Medical Devices"},
    "HCA":   {"company_name": "HCA Healthcare Inc.",                     "sector": "Health Care",               "industry": "Healthcare Services"},
    "CVS":   {"company_name": "CVS Health Corporation",                  "sector": "Health Care",               "industry": "Healthcare Services"},
    "CI":    {"company_name": "Cigna Group",                             "sector": "Health Care",               "industry": "Managed Care"},
    "MCK":   {"company_name": "McKesson Corporation",                    "sector": "Health Care",               "industry": "Healthcare Distribution"},
    "HUM":   {"company_name": "Humana Inc.",                             "sector": "Health Care",               "industry": "Managed Care"},
    "ELV":   {"company_name": "Elevance Health Inc.",                    "sector": "Health Care",               "industry": "Managed Care"},
    "MOH":   {"company_name": "Molina Healthcare Inc.",                  "sector": "Health Care",               "industry": "Managed Care"},

    # ── Financials (broader) ──────────────────────────────────────────────────
    "BLK":   {"company_name": "BlackRock Inc.",                          "sector": "Financials",                "industry": "Asset Management"},
    "MS":    {"company_name": "Morgan Stanley",                          "sector": "Financials",                "industry": "Investment Banking"},
    "SCHW":  {"company_name": "Charles Schwab Corporation",              "sector": "Financials",                "industry": "Brokerage"},
    "AXP":   {"company_name": "American Express Company",                "sector": "Financials",                "industry": "Credit Services"},
    "COF":   {"company_name": "Capital One Financial Corporation",       "sector": "Financials",                "industry": "Consumer Finance"},
    "USB":   {"company_name": "U.S. Bancorp",                            "sector": "Financials",                "industry": "Banking"},
    "PNC":   {"company_name": "PNC Financial Services Group Inc.",       "sector": "Financials",                "industry": "Banking"},
    "TFC":   {"company_name": "Truist Financial Corporation",            "sector": "Financials",                "industry": "Banking"},
    "SPGI":  {"company_name": "S&P Global Inc.",                         "sector": "Financials",                "industry": "Financial Data"},
    "MCO":   {"company_name": "Moody's Corporation",                     "sector": "Financials",                "industry": "Financial Data"},
    "ICE":   {"company_name": "Intercontinental Exchange Inc.",          "sector": "Financials",                "industry": "Financial Exchanges"},
    "CME":   {"company_name": "CME Group Inc.",                          "sector": "Financials",                "industry": "Financial Exchanges"},
    "MSCI":  {"company_name": "MSCI Inc.",                               "sector": "Financials",                "industry": "Financial Data"},
    "NDAQ":  {"company_name": "Nasdaq Inc.",                             "sector": "Financials",                "industry": "Financial Exchanges"},

    # ── Utilities & Real Estate ───────────────────────────────────────────────
    "NEE":   {"company_name": "NextEra Energy Inc.",                     "sector": "Utilities",                 "industry": "Electric Utilities"},
    "DUK":   {"company_name": "Duke Energy Corporation",                 "sector": "Utilities",                 "industry": "Electric Utilities"},
    "SO":    {"company_name": "Southern Company",                        "sector": "Utilities",                 "industry": "Electric Utilities"},
    "AMT":   {"company_name": "American Tower Corporation",              "sector": "Real Estate",               "industry": "Cell Tower REITs"},
    "EQIX":  {"company_name": "Equinix Inc.",                            "sector": "Real Estate",               "industry": "Data Center REITs"},
    "PLD":   {"company_name": "Prologis Inc.",                           "sector": "Real Estate",               "industry": "Industrial REITs"},
    "SPG":   {"company_name": "Simon Property Group Inc.",               "sector": "Real Estate",               "industry": "Retail REITs"},
    "DLR":   {"company_name": "Digital Realty Trust Inc.",               "sector": "Real Estate",               "industry": "Data Center REITs"},
    "O":     {"company_name": "Realty Income Corporation",               "sector": "Real Estate",               "industry": "Net Lease REITs"},

    # ── Consumer / Retail ─────────────────────────────────────────────────────
    "PG":    {"company_name": "Procter & Gamble Co.",                    "sector": "Consumer Staples",          "industry": "Household Products"},
    "KO":    {"company_name": "The Coca-Cola Company",                   "sector": "Consumer Staples",          "industry": "Beverages"},
    "PEP":   {"company_name": "PepsiCo Inc.",                            "sector": "Consumer Staples",          "industry": "Beverages"},
    "PM":    {"company_name": "Philip Morris International Inc.",        "sector": "Consumer Staples",          "industry": "Tobacco"},
    "MO":    {"company_name": "Altria Group Inc.",                       "sector": "Consumer Staples",          "industry": "Tobacco"},
    "CL":    {"company_name": "Colgate-Palmolive Company",               "sector": "Consumer Staples",          "industry": "Household Products"},
    "MDLZ":  {"company_name": "Mondelez International Inc.",             "sector": "Consumer Staples",          "industry": "Food Products"},
    "GIS":   {"company_name": "General Mills Inc.",                      "sector": "Consumer Staples",          "industry": "Food Products"},
    "K":     {"company_name": "Kellanova",                               "sector": "Consumer Staples",          "industry": "Food Products"},
    "CMG":   {"company_name": "Chipotle Mexican Grill Inc.",             "sector": "Consumer Discretionary",    "industry": "Restaurants"},
    "YUM":   {"company_name": "Yum! Brands Inc.",                        "sector": "Consumer Discretionary",    "industry": "Restaurants"},
    "BKNG":  {"company_name": "Booking Holdings Inc.",                   "sector": "Consumer Discretionary",    "industry": "Online Travel"},
    "EXPE":  {"company_name": "Expedia Group Inc.",                      "sector": "Consumer Discretionary",    "industry": "Online Travel"},
    "AMZN":  {"company_name": "Amazon.com Inc.",                         "sector": "Consumer Discretionary",    "industry": "E-Commerce"},  # already present but confirm
    "LVS":   {"company_name": "Las Vegas Sands Corp.",                   "sector": "Consumer Discretionary",    "industry": "Casinos & Gaming"},
    "WYNN":  {"company_name": "Wynn Resorts Limited",                    "sector": "Consumer Discretionary",    "industry": "Casinos & Gaming"},
    "MGM":   {"company_name": "MGM Resorts International",               "sector": "Consumer Discretionary",    "industry": "Casinos & Gaming"},

    # ── Industrials (broader) ─────────────────────────────────────────────────
    "UPS":   {"company_name": "United Parcel Service Inc.",              "sector": "Industrials",               "industry": "Air Freight & Logistics"},
    "FDX":   {"company_name": "FedEx Corporation",                       "sector": "Industrials",               "industry": "Air Freight & Logistics"},
    "CSX":   {"company_name": "CSX Corporation",                         "sector": "Industrials",               "industry": "Railroads"},
    "NSC":   {"company_name": "Norfolk Southern Corporation",            "sector": "Industrials",               "industry": "Railroads"},
    "UNP":   {"company_name": "Union Pacific Corporation",               "sector": "Industrials",               "industry": "Railroads"},
    "WM":    {"company_name": "Waste Management Inc.",                   "sector": "Industrials",               "industry": "Waste Management"},
    "VRSK":  {"company_name": "Verisk Analytics Inc.",                   "sector": "Industrials",               "industry": "Data Analytics"},
    "EXPO":  {"company_name": "Exponent Inc.",                           "sector": "Industrials",               "industry": "Consulting"},

    # ── Materials ─────────────────────────────────────────────────────────────
    "LIN":   {"company_name": "Linde plc",                               "sector": "Materials",                 "industry": "Industrial Gases"},
    "APD":   {"company_name": "Air Products and Chemicals Inc.",         "sector": "Materials",                 "industry": "Industrial Gases"},
    "ECL":   {"company_name": "Ecolab Inc.",                             "sector": "Materials",                 "industry": "Specialty Chemicals"},
    "SHW":   {"company_name": "The Sherwin-Williams Company",            "sector": "Materials",                 "industry": "Specialty Chemicals"},
    "FCX":   {"company_name": "Freeport-McMoRan Inc.",                   "sector": "Materials",                 "industry": "Copper Mining"},
    "NEM":   {"company_name": "Newmont Corporation",                     "sector": "Materials",                 "industry": "Gold Mining"},
    "GOLD":  {"company_name": "Barrick Gold Corporation",                "sector": "Materials",                 "industry": "Gold Mining"},

    # ── Communication Services (Severity-1 fix) ───────────────────────────────
    "VZ":    {"company_name": "Verizon Communications Inc.",             "sector": "Communication Services",    "industry": "Telecom"},
    "T":     {"company_name": "AT&T Inc.",                               "sector": "Communication Services",    "industry": "Telecom"},
    "CMCSA": {"company_name": "Comcast Corporation",                     "sector": "Communication Services",    "industry": "Cable & Satellite"},

    # ── Energy Services (Severity-1 fix) ──────────────────────────────────────
    "SLB":   {"company_name": "SLB",                                     "sector": "Energy",                    "industry": "Oilfield Services"},

    # ── Severity-1b expansion (2026-06-02) ────────────────────────────────────
    # 12 companies absent from 100-company validation roster; 3 more (NOW/SNOW/SO)
    # were present but blocked by _TICKER_STOP_WORDS — see stop-words section above.
    # Financials
    "CB":    {"company_name": "Chubb Limited",                           "sector": "Financials",                "industry": "Insurance"},
    # Industrials
    "ETN":   {"company_name": "Eaton Corporation plc",                   "sector": "Industrials",               "industry": "Electrical Equipment"},
    "EMR":   {"company_name": "Emerson Electric Co.",                    "sector": "Industrials",               "industry": "Industrial Automation"},
    # Energy
    "EOG":   {"company_name": "EOG Resources Inc.",                      "sector": "Energy",                    "industry": "Oil & Gas E&P"},
    "PSX":   {"company_name": "Phillips 66",                             "sector": "Energy",                    "industry": "Oil Refining"},
    "OXY":   {"company_name": "Occidental Petroleum Corporation",        "sector": "Energy",                    "industry": "Oil & Gas"},
    "VLO":   {"company_name": "Valero Energy Corporation",               "sector": "Energy",                    "industry": "Oil Refining"},
    # Utilities
    "D":     {"company_name": "Dominion Energy Inc.",                    "sector": "Utilities",                 "industry": "Electric Utilities"},
    "AEP":   {"company_name": "American Electric Power Company Inc.",    "sector": "Utilities",                 "industry": "Electric Utilities"},
    "EXC":   {"company_name": "Exelon Corporation",                      "sector": "Utilities",                 "industry": "Electric Utilities"},
    # Communication Services
    "TMUS":  {"company_name": "T-Mobile US Inc.",                        "sector": "Communication Services",    "industry": "Telecom"},
    "CHTR":  {"company_name": "Charter Communications Inc.",             "sector": "Communication Services",    "industry": "Cable & Satellite"},
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
    "nvidia corporation":      "NVDA",
    # NVIDIA product brands
    "cuda":                    "NVDA",
    "h100":                    "NVDA",
    "blackwell":               "NVDA",
    "hopper":                  "NVDA",    # NVIDIA GPU architecture
    # typos
    "nvidea":                  "NVDA",
    "nvidai":                  "NVDA",
    "nvdia":                   "NVDA",
    "nividia":                 "NVDA",
    "nviida":                  "NVDA",
    "nviddia":                 "NVDA",
    "nvida":                   "NVDA",

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
    "visa inc":                "V",
    "visa inc.":               "V",
    "visa card":               "V",

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
    # AMD product brands — users search these even when asking about the stock
    "ryzen":                   "AMD",
    "radeon":                  "AMD",
    "epyc":                    "AMD",
    # typos
    "amdd":                    "AMD",
    "advancedmicro":           "AMD",

    # ── Intel ─────────────────────────────────────────────────────────────────
    "intel":                   "INTC",

    # ── Qualcomm ──────────────────────────────────────────────────────────────
    "qualcomm":                "QCOM",

    # ── Broadcom ──────────────────────────────────────────────────────────────
    "broadcom":                "AVGO",
    "avgo":                    "AVGO",   # ticker alias (people say "AVGO stock" lowercase)
    "broadcom inc":            "AVGO",
    # typos
    "broadcome":               "AVGO",
    "braodcom":                "AVGO",
    "brodcom":                 "AVGO",

    # ── TSMC ──────────────────────────────────────────────────────────────────
    "tsmc":                    "TSM",
    "taiwan semiconductor":    "TSM",
    "taiwan semiconductor manufacturing": "TSM",
    "taiwan semi":             "TSM",
    "tsm":                     "TSM",   # lowercase ticker alias

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
    "arm semiconductor":       "ARM",

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
    "asml holding":            "ASML",
    "asml holding n.v.":       "ASML",
    "asml holdings":           "ASML",
    "asml semiconductor":      "ASML",

    # ── Lam Research ──────────────────────────────────────────────────────────
    "lam research":            "LRCX",
    "lrcx":                    "LRCX",

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
    "lly":                     "LLY",
    "eli lilly and company":   "LLY",
    "eli lilly & company":     "LLY",

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

    # ── AppLovin ──────────────────────────────────────────────────────────────
    # NOTE: "app" alone is NOT registered — it's a generic English word and
    # would cause "Is this app investable?" to resolve to AppLovin.
    "applovin":                "APP",
    "applovin corporation":    "APP",
    "app lovin":               "APP",
    "applovin inc":            "APP",

    "soundhound":              "SOUN",
    "sound hound":             "SOUN",

    # ── Vertex Pharmaceuticals ────────────────────────────────────────────────
    # CRITICAL: must be registered before short aliases like "arm" can
    # substring-match inside "pharmaceuticals".  Word-boundary fix in
    # _alias_lookup also prevents that class of false match.
    "vertex pharmaceuticals":          "VRTX",
    "vertex pharma":                   "VRTX",
    "vertex":                          "VRTX",
    "vrtx":                            "VRTX",
    # typos
    "vertx pharmaceuticals":           "VRTX",
    "vertex pharmaceutical":           "VRTX",

    # ── Novo Nordisk ──────────────────────────────────────────────────────────
    "novo nordisk":                    "NVO",
    "novo":                            "NVO",
    "nvo":                             "NVO",
    # typos / variants and legal forms
    "novo nordisk as":                 "NVO",
    "novo nordisk a/s":                "NVO",
    "novonordisk":                     "NVO",
    "nordisk":                         "NVO",

    # ── Intuitive Surgical ────────────────────────────────────────────────────
    "intuitive surgical":              "ISRG",
    "intuitive":                       "ISRG",
    "isrg":                            "ISRG",
    # typos
    "intuative surgical":              "ISRG",

    # ── CRISPR Therapeutics ───────────────────────────────────────────────────
    "crispr therapeutics":             "CRSP",
    "crispr":                          "CRSP",
    "crsp":                            "CRSP",
    # typos
    "crispr theraputics":              "CRSP",

    # ── AstraZeneca ───────────────────────────────────────────────────────────
    "astrazeneca":                     "AZN",
    "astra zeneca":                    "AZN",
    "azn":                             "AZN",
    # typos
    "astra zennica":                   "AZN",
    "astrazenica":                     "AZN",

    # ── Roche ─────────────────────────────────────────────────────────────────
    "roche":                           "RHHBY",
    "roche holding":                   "RHHBY",
    "roche holdings":                  "RHHBY",
    "rhhby":                           "RHHBY",
    # typos
    "roch":                            "RHHBY",

    # ── BioNTech ──────────────────────────────────────────────────────────────
    "biontech":                        "BNTX",
    "bio n tech":                      "BNTX",
    "bntx":                            "BNTX",
    # typos
    "biotech biontech":                "BNTX",
    "biontech se":                     "BNTX",

    # ── Biogen ────────────────────────────────────────────────────────────────
    "biogen":                          "BIIB",
    "biib":                            "BIIB",

    # ── Gilead Sciences ───────────────────────────────────────────────────────
    "gilead":                          "GILD",
    "gilead sciences":                 "GILD",
    "gild":                            "GILD",

    # ── Amgen ─────────────────────────────────────────────────────────────────
    "amgen":                           "AMGN",
    "amgn":                            "AMGN",

    # ── Illumina ──────────────────────────────────────────────────────────────
    "illumina":                        "ILMN",
    "ilmn":                            "ILMN",

    # ── DexCom ────────────────────────────────────────────────────────────────
    "dexcom":                          "DXCM",
    "dex com":                         "DXCM",

    # ── Veeva Systems ─────────────────────────────────────────────────────────
    "veeva":                           "VEEV",
    "veeva systems":                   "VEEV",

    # ── Alnylam ───────────────────────────────────────────────────────────────
    "alnylam":                         "ALNY",
    "alnylam pharmaceuticals":         "ALNY",

    # ── Intuitive (medical) ───────────────────────────────────────────────────
    # (aliased above)

    # ── Stryker ───────────────────────────────────────────────────────────────
    "stryker":                         "SYK",
    "syk":                             "SYK",

    # ── Boston Scientific ─────────────────────────────────────────────────────
    "boston scientific":               "BSX",
    "bsx":                             "BSX",

    # ── Medtronic ─────────────────────────────────────────────────────────────
    "medtronic":                       "MDT",
    "mdt":                             "MDT",

    # ── Abbott ────────────────────────────────────────────────────────────────
    "abbott":                          "ABT",
    "abbott laboratories":             "ABT",
    "abt":                             "ABT",

    # ── Danaher ───────────────────────────────────────────────────────────────
    "danaher":                         "DHR",
    "dhr":                             "DHR",

    # ── Thermo Fisher ─────────────────────────────────────────────────────────
    "thermo fisher":                   "TMO",
    "thermo fisher scientific":        "TMO",
    "tmo":                             "TMO",

    # ── Edwards Lifesciences ──────────────────────────────────────────────────
    "edwards lifesciences":            "EW",
    "edwards":                         "EW",

    # ── HCA Healthcare ────────────────────────────────────────────────────────
    "hca healthcare":                  "HCA",
    "hca":                             "HCA",

    # ── CVS Health ────────────────────────────────────────────────────────────
    "cvs health":                      "CVS",
    "cvs":                             "CVS",
    "cvs pharmacy":                    "CVS",

    # ── Cigna ─────────────────────────────────────────────────────────────────
    "cigna":                           "CI",
    "cigna group":                     "CI",

    # ── McKesson ──────────────────────────────────────────────────────────────
    "mckesson":                        "MCK",

    # ── Humana ────────────────────────────────────────────────────────────────
    "humana":                          "HUM",

    # ── Elevance Health ───────────────────────────────────────────────────────
    "elevance health":                 "ELV",
    "elevance":                        "ELV",
    "anthem":                          "ELV",       # formerly Anthem Inc.

    # ── BlackRock ─────────────────────────────────────────────────────────────
    "blackrock":                       "BLK",
    "blk":                             "BLK",

    # ── Morgan Stanley ────────────────────────────────────────────────────────
    "morgan stanley":                  "MS",

    # ── Charles Schwab ────────────────────────────────────────────────────────
    "charles schwab":                  "SCHW",
    "schwab":                          "SCHW",

    # ── American Express ──────────────────────────────────────────────────────
    "american express":                "AXP",
    "amex":                            "AXP",
    "axp":                             "AXP",

    # ── Capital One ───────────────────────────────────────────────────────────
    "capital one":                     "COF",

    # ── U.S. Bancorp ──────────────────────────────────────────────────────────
    "us bancorp":                      "USB",
    "u.s. bancorp":                    "USB",
    "us bank":                         "USB",

    # ── S&P Global ────────────────────────────────────────────────────────────
    "s&p global":                      "SPGI",
    "sp global":                       "SPGI",
    "standard and poors":              "SPGI",

    # ── Moody's ───────────────────────────────────────────────────────────────
    "moodys":                          "MCO",
    "moody's":                         "MCO",

    # ── ICE ───────────────────────────────────────────────────────────────────
    "intercontinental exchange":       "ICE",

    # ── CME Group ─────────────────────────────────────────────────────────────
    "cme group":                       "CME",
    "cme":                             "CME",
    "chicago mercantile exchange":     "CME",

    # ── MSCI ──────────────────────────────────────────────────────────────────
    "msci":                            "MSCI",

    # ── Nasdaq ────────────────────────────────────────────────────────────────
    "nasdaq inc":                      "NDAQ",

    # ── NextEra Energy ────────────────────────────────────────────────────────
    "nextera energy":                  "NEE",
    "nextera":                         "NEE",

    # ── Duke Energy ───────────────────────────────────────────────────────────
    "duke energy":                     "DUK",

    # ── Southern Company ──────────────────────────────────────────────────────
    "southern company":                "SO",

    # ── American Tower ────────────────────────────────────────────────────────
    "american tower":                  "AMT",

    # ── Equinix ───────────────────────────────────────────────────────────────
    "equinix":                         "EQIX",

    # ── Prologis ──────────────────────────────────────────────────────────────
    "prologis":                        "PLD",

    # ── Simon Property Group ──────────────────────────────────────────────────
    "simon property":                  "SPG",

    # ── Digital Realty ────────────────────────────────────────────────────────
    "digital realty":                  "DLR",

    # ── Realty Income ─────────────────────────────────────────────────────────
    "realty income":                   "O",

    # ── Consumer staples ──────────────────────────────────────────────────────
    "procter and gamble":              "PG",
    "procter & gamble":                "PG",
    "p&g":                             "PG",
    "coca cola":                       "KO",
    "coca-cola":                       "KO",
    "coke":                            "KO",
    "pepsi":                           "PEP",
    "pepsico":                         "PEP",
    "philip morris":                   "PM",
    "altria":                          "MO",
    "colgate":                         "CL",
    "colgate palmolive":               "CL",
    "mondelez":                        "MDLZ",
    "general mills":                   "GIS",
    "chipotle":                        "CMG",
    "booking holdings":                "BKNG",
    "booking.com":                     "BKNG",
    "expedia":                         "EXPE",

    # ── Industrials ───────────────────────────────────────────────────────────
    "ups":                             "UPS",
    "united parcel service":           "UPS",
    "fedex":                           "FDX",
    "csx":                             "CSX",
    "norfolk southern":                "NSC",
    "union pacific":                   "UNP",
    "waste management":                "WM",
    "linde":                           "LIN",
    "air products":                    "APD",
    "ecolab":                          "ECL",
    "sherwin williams":                "SHW",
    "sherwin-williams":                "SHW",
    "freeport mcmoran":                "FCX",
    "freeport":                        "FCX",
    "newmont":                         "NEM",
    "barrick gold":                    "GOLD",
    "barrick":                         "GOLD",

    # ── Verizon (Severity-1 fix) ──────────────────────────────────────────────
    "verizon":                         "VZ",
    "verizon communications":          "VZ",
    "vz":                              "VZ",

    # ── AT&T (Severity-1 fix) ─────────────────────────────────────────────────
    # NOTE: bare "t" is intentionally NOT registered — it is a single-char
    # stop-word candidate and would create false positives on phrases like
    # "T-bills" or "t-mobile".  The ticker "T" is handled by exact_ticker
    # detection (Step 1) via _COMPANY_DB now that "T" is registered there.
    "at&t":                            "T",
    "att":                             "T",
    "at and t":                        "T",
    "at&t inc":                        "T",

    # ── Comcast (Severity-1 fix) ──────────────────────────────────────────────
    "comcast":                         "CMCSA",
    "comcast corporation":             "CMCSA",
    "cmcsa":                           "CMCSA",
    "xfinity":                         "CMCSA",
    "nbcuniversal":                    "CMCSA",
    "nbc universal":                   "CMCSA",

    # ── SLB / Schlumberger (Severity-1 fix) ───────────────────────────────────
    "slb":                             "SLB",
    "schlumberger":                    "SLB",
    "schlumberger limited":            "SLB",

    # ── Severity-1b expansion aliases (2026-06-02) ────────────────────────────
    # NOW — ServiceNow (no longer a stop word; long-form alias below supplements
    #        the new exact-ticker resolution for direct ticker queries)
    "service now":                     "NOW",    # spaced variant
    "servicenow inc":                  "NOW",

    # SNOW — Snowflake (no longer a stop word)
    "snowflake inc":                   "SNOW",

    # SO — Southern Company (no longer a stop word)
    "southern co":                     "SO",     # common abbreviation
    "southern company the":            "SO",

    # CB — Chubb Limited
    "chubb":                           "CB",
    "chubb limited":                   "CB",
    "chubb insurance":                 "CB",

    # ETN — Eaton Corporation
    "eaton":                           "ETN",
    "eaton corporation":               "ETN",
    "eaton corp":                      "ETN",

    # EMR — Emerson Electric
    "emerson":                         "EMR",
    "emerson electric":                "EMR",
    "emerson electric co":             "EMR",

    # EOG — EOG Resources
    "eog resources":                   "EOG",
    "eog":                             "EOG",

    # PSX — Phillips 66
    "phillips 66":                     "PSX",
    "phillips66":                      "PSX",

    # OXY — Occidental Petroleum
    "occidental":                      "OXY",
    "occidental petroleum":            "OXY",
    "oxy petroleum":                   "OXY",

    # VLO — Valero Energy
    "valero":                          "VLO",
    "valero energy":                   "VLO",

    # D — Dominion Energy
    "dominion energy":                 "D",
    "dominion":                        "D",

    # AEP — American Electric Power
    "american electric power":         "AEP",
    "aep":                             "AEP",

    # EXC — Exelon
    "exelon":                          "EXC",
    "exelon corporation":              "EXC",

    # TMUS — T-Mobile
    "t-mobile":                        "TMUS",
    "tmobile":                         "TMUS",
    "t mobile":                        "TMUS",
    "t-mobile us":                     "TMUS",

    # CHTR — Charter Communications
    "charter communications":          "CHTR",
    "charter":                         "CHTR",
    "spectrum cable":                  "CHTR",   # consumer brand (specific form to avoid matching "spectrum" alone)
    "spectrum internet":               "CHTR",
}

# Pre-sort alias keys by length (descending) so that the longest match wins.
_ALIAS_KEYS_BY_LENGTH: list[str] = sorted(_ALIAS_MAP.keys(), key=len, reverse=True)

# ---------------------------------------------------------------------------
# Protected generic-word tickers
# ---------------------------------------------------------------------------
# Mapping: TICKER → (company_name, clarification_prompt)
# These tickers are also common English words.  The entity_resolution_service
# uses this dict to detect ambiguous queries and return needs_clarification=True
# rather than silently routing to the wrong company.
PROTECTED_GENERIC_TICKERS: dict[str, tuple[str, str]] = {
    "AI":   ("C3.ai Inc.",            "Do you mean C3.ai (AI), artificial intelligence broadly, or another AI company?"),
    "APP":  ("AppLovin Corporation",  "Do you mean AppLovin (APP) or are you using 'app' generically?"),
    "NET":  ("Cloudflare Inc.",       "Do you mean Cloudflare (NET) or using 'net' as a general term?"),
    "SNOW": ("Snowflake Inc.",        "Do you mean Snowflake (SNOW) or the weather/substance term 'snow'?"),
    "DASH": ("DoorDash Inc.",         "Do you mean DoorDash (DASH) or using 'dash' generically?"),
    "PATH": ("UiPath Inc.",           "Do you mean UiPath (PATH) or using 'path' generically?"),
    "OPEN": ("Opendoor Technologies Inc.", "Do you mean Opendoor (OPEN) or using 'open' generically?"),
    "SHOP": ("Shopify Inc.",          "Do you mean Shopify (SHOP) or using 'shop' generically?"),
    "ARM":  ("Arm Holdings plc",      "Do you mean Arm Holdings (ARM) or using 'arm' generically?"),
    "NOW":  ("ServiceNow Inc.",       "Do you mean ServiceNow (NOW) or using 'now' as a time reference?"),
}

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
    # Generic industry / sector terms — must not trigger company detection.
    # E.g. "biotech" would fuzzy-match "biontech" (BNTX) at ratio 0.93,
    # "pharmaceutical" would fuzzy-match via substring in alias_exact.
    "biotech", "biotechnology", "pharma", "pharmaceutical", "pharmaceuticals",
    "therapeutics", "genomics", "healthcare", "health care", "medtech",
    "semiconductor", "semiconductors", "software", "hardware", "fintech",
    "streaming", "ecommerce", "cybersecurity", "enterprise", "startup",
    "fund", "funds", "etf", "index", "reit", "trust",
    "equipment", "agricultural", "industrial", "manufacturing",
    "technology", "technologies", "solutions", "systems", "group",
    "holdings", "international", "global", "national", "american",
    "financial", "capital", "management", "consulting", "analytics",
    "energy", "renewable", "electric", "utility", "utilities",
    "retail", "consumer", "media", "entertainment", "gaming",
    "logistics", "transport", "transportation", "aerospace", "defense",
    # Common financial and economic terms that fuzzy-match company names.
    # Critical case: "interest" has ratio 0.941 with "pinterest" (literally
    # a suffix relationship: "p" + "interest" = "pinterest").
    "interest", "interests", "rate", "rates", "yield", "yields",
    "inflation", "deflation", "stagflation", "monetary", "fiscal",
    "recession", "expansion", "contraction", "growth", "decline",
    "high", "low", "rising", "falling", "volatile", "volatility",
    "earnings", "revenue", "profit", "profits", "loss", "losses",
    "margin", "margins", "valuation", "valuations", "multiple", "multiples",
    "dividend", "dividends", "buyback", "buybacks", "repurchase",
    "guidance", "forecast", "forecasts", "estimate", "estimates",
    "quarter", "quarterly", "annual", "year", "years", "month", "months",
    "increase", "decrease", "growth", "decline", "surge", "drop",
    "invest", "investing", "investment", "investments", "investor", "investors",
    "portfolio", "allocation", "diversification", "hedge", "hedging",
    "risk", "risks", "reward", "rewards", "return", "returns",
    "bull", "bear", "rally", "correction", "crash", "recovery",
    "macro", "micro", "cyclical", "secular", "structural", "tactical",
    "why", "when", "where", "which", "whose", "whom",
    "high", "low", "much", "many", "some", "most", "more", "less",
    "because", "since", "given", "despite", "although", "however",
    "currently", "recently", "historically", "going", "forward",
    # Macro / fixed-income terms that fuzzy-match telecom aliases.
    # "inversion" has difflib ratio 0.75 with "verizon" →
    # confidence 0.853 → just above the 0.85 routing gate.
    # These are economic concepts, not company references.
    "inversion", "reversion", "diversion", "conversion", "aversion",
    "version", "versions",
    # Economic report terms that fuzzy-match company aliases.
    # "report" has difflib ratio 0.857 with "freeport" (FCX alias) →
    # causes "jobs report", "earnings report", "CPI report" etc. to
    # mis-route to Freeport-McMoRan.  All variants blocked here.
    "report", "reports", "reported", "reporting",
    # Related macro data-release terms with similar fuzzy-match risk.
    "jobs", "payroll", "payrolls", "nonfarm", "nonfarm payroll",
    "employment", "unemployment", "cpi", "ppi", "gdp", "pce",
    "fomc", "minutes", "survey", "surveys", "data", "release",
    # Common adjectives / adverbs that survive context-word stripping and
    # fuzzy-match company aliases at the 0.55 candidate threshold.
    # "recent" → stripped to residual tokens that match TMUS/FCX/REGN at 0.55-0.63.
    "recent", "recently",
    # "tech" fuzzy-matches "bio n tech" (BNTX alias) as a 2-gram window
    # ("on tech" → 0.824).  "tech" is a generic sector abbreviation, not
    # a company name.  Long-form "technology"/"technologies" already blocked.
    "tech",
    # "fed" fuzzy-matches "fedex" (FDX alias) at ratio 0.75.
    # In financial prose "fed" almost always means Federal Reserve, not FedEx.
    # FedEx resolves correctly via the "fedex" alias_exact path.
    "fed",
    # "bank" fuzzy-matches "us bank" (USB / US Bancorp) at ratio 0.727.
    # "bank stocks", "bank sector", "banking" queries must not route to USB.
    # US Bancorp resolves correctly via "us bancorp" / "usb" alias_exact.
    "bank",
    # "lender" fuzzy-matches "linde" (LIN) at ratio 0.727.
    # Generic lending/credit sector language must not route to Linde plc.
    "lender", "lenders",
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
    rejection_reason:
        Non-empty when a fuzzy match was found but discarded before routing:
        "fuzzy_below_threshold" — difflib match found but confidence < MINIMUM_ROUTE_CONFIDENCE
        "not_found"             — no match at any confidence level
        ""                      — resolution succeeded (exact_ticker or alias_exact)
    fallback_reason:
        Non-empty when no confident resolution was reached:
        "candidates_available"  — top-N suggestions populated for Did-you-mean UX
        "no_candidates"         — not even low-confidence suggestions found
        ""                      — resolution succeeded, no fallback needed
    """
    context: Optional[CompanyContext]
    confidence: float
    method: str
    matched_text: str
    candidates: List[Tuple[str, str, float]] = field(default_factory=list)
    rejection_reason: str = ""
    fallback_reason: str = ""


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
    """Step 2 — word-boundary search over lowercased *text*, longest alias first.

    Uses ``re.search(r'\\b<alias>\\b', lower)`` rather than a plain substring
    ``in`` check.  This prevents false positives where a short alias appears
    *inside* an unrelated word — the canonical failure case being "arm"
    matching inside "pharmaceuticals", which caused "Vertex Pharmaceuticals"
    to resolve to ARM Holdings.

    Word-boundary semantics (Python ``re`` module):
      - ``\\b`` matches between a word-char (``[A-Za-z0-9_]``) and a
        non-word-char (or string edge).
      - "arm" in "pharmaceuticals" → NO match (surrounded by word chars).
      - "arm" in "arm holdings"    → MATCH (boundaries on both sides).
      - "arm" in "ARM Holdings"    → MATCH (after lowercasing).
      - "coke" in "Coca-Cola"      → NO match (hyphen is non-word-char but
        "coke" is not present as text, so still no match).
    """
    lower = text.lower()
    for alias in _ALIAS_KEYS_BY_LENGTH:
        pattern = r'\b' + re.escape(alias) + r'\b'
        if re.search(pattern, lower):
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

    # Exclude very short aliases (< 5 chars) from fuzzy matching.
    # Short aliases like "ford" (4), "arm" (3), "ma" (2), "so" (2) have high
    # difflib similarity with many ordinary English words ("for", "charm",
    # "macro", "also").  The critical case: difflib.SequenceMatcher(None,
    # "for", "ford").ratio() == 0.857 → confidence 0.903 → above the 0.85
    # routing threshold, causing any query "… for <missing-ticker> …" to
    # mis-route to Ford Motor Company.  All 4-char aliases that matter are
    # covered by exact_ticker detection (STEP 1) or word-boundary alias
    # lookup (STEP 2), so raising the floor to 5 does not reduce recall.
    alias_keys = [k for k in _ALIAS_MAP.keys() if len(k) >= 5]
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
    :class:`EntityResolution` with a confidence score, resolution method,
    candidate suggestions when no match is found, and observability fields
    (rejection_reason, fallback_reason) for logging and monitoring.

    Detection order
    ---------------
    1. Exact uppercase ticker — always wins at confidence 1.00.
    2. Alias word-boundary lookup — longest match first, confidence 0.95.
    3. Token-window fuzzy match — difflib ratio scaled to 0.72–0.95.

    Governance
    ----------
    The router applies MINIMUM_ROUTE_CONFIDENCE (0.85) as a hard gate.
    Fuzzy matches below that threshold are flagged with
    rejection_reason="fuzzy_below_threshold" so callers can surface a
    "Did you mean?" UI instead of silently routing to the wrong company.

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
    import json as _json

    if not text or not text.strip():
        return EntityResolution(
            None, 0.0, "not_found", "",
            rejection_reason="not_found",
            fallback_reason="no_candidates",
        )

    normalized = _normalize_query(text)

    # ── Step 1: explicit uppercase ticker ────────────────────────────────────
    ctx = _extract_explicit_ticker(text)
    if ctx is not None:
        logger.info(_json.dumps({
            "event": "entity_resolved",
            "method": "exact_ticker",
            "ticker": ctx.ticker,
            "confidence": 1.00,
            "matched_text": ctx.ticker,
            "rejection_reason": "",
            "fallback_reason": "",
            "raw_query": text[:120],
        }))
        return EntityResolution(
            ctx, 1.0, "exact_ticker", ctx.ticker,
            rejection_reason="",
            fallback_reason="",
        )

    # ── Step 2: alias word-boundary lookup ────────────────────────────────────
    ctx = _alias_lookup(text)
    if ctx is not None:
        alias = ctx.aliases[0] if ctx.aliases else ""
        logger.info(_json.dumps({
            "event": "entity_resolved",
            "method": "alias_exact",
            "ticker": ctx.ticker,
            "confidence": 0.95,
            "matched_text": alias,
            "rejection_reason": "",
            "fallback_reason": "",
            "raw_query": text[:120],
        }))
        return EntityResolution(
            ctx, 0.95, "alias_exact", alias,
            rejection_reason="",
            fallback_reason="",
        )

    # ── Step 3: token-window fuzzy match ─────────────────────────────────────
    fuzzy_result = _fuzzy_token_match(text, cutoff=0.72)
    if fuzzy_result is not None:
        ctx, score, matched_alias = fuzzy_result
        # Scale difflib ratio (0.72 – 1.0) → confidence (0.72 – 0.95)
        confidence = round(0.50 + score * 0.47, 3)
        # Determine whether this match clears the routing gate.
        # Matches below MINIMUM_ROUTE_CONFIDENCE must NOT be silently routed;
        # the router will demote them to "Did you mean?" candidates.
        below_threshold = confidence < MINIMUM_ROUTE_CONFIDENCE
        rejection_reason = "fuzzy_below_threshold" if below_threshold else ""
        logger.info(_json.dumps({
            "event": "entity_resolved",
            "method": "fuzzy_token",
            "ticker": ctx.ticker,
            "confidence": confidence,
            "matched_text": matched_alias,
            "difflib_score": round(score, 4),
            "rejection_reason": rejection_reason,
            "fallback_reason": "",
            "below_routing_threshold": below_threshold,
            "raw_query": text[:120],
        }))
        return EntityResolution(
            ctx, confidence, "fuzzy_token", matched_alias,
            rejection_reason=rejection_reason,
            fallback_reason="",
        )

    # ── Not found — gather candidates for "Did you mean?" ────────────────────
    candidates = _gather_candidates(text)
    fallback_reason = "candidates_available" if candidates else "no_candidates"
    logger.info(_json.dumps({
        "event": "entity_not_found",
        "method": "not_found",
        "rejection_reason": "not_found",
        "fallback_reason": fallback_reason,
        "candidate_count": len(candidates),
        "top_candidates": [(t, round(s, 3)) for t, _, s in candidates[:3]],
        "raw_query": text[:120],
    }))
    return EntityResolution(
        None, 0.0, "not_found", "",
        candidates=candidates,
        rejection_reason="not_found",
        fallback_reason=fallback_reason,
    )


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
