"""
Watchlist thematic grouping.

Groups watchlist entries by macro theme and sector exposure using
keyword heuristics applied to company names, tickers, and thesis content.
Pure deterministic — no LLM calls.

Themes:
  ai_infrastructure    — NVDA, AMD, SMCI, AVGO, MRVL, TSM, ARM, QCOM (GPU/networking/silicon)
  rate_sensitive       — tech with high P/E, duration risk, long-duration cash flows
  china_exposure       — Apple (iPhone), SBUX, NKE, Qualcomm, Tesla (China rev)
  consumer_cyclical    — AMZN, TSLA, NKE, SBUX, FORD, GM
  mega_cap_tech        — AAPL, GOOGL, MSFT, META, AMZN (the Magnificent 7)
  financial            — JPM, BAC, GS, WFC, BLK, V, MA
  energy_commodities   — XOM, CVX, COP, SLB, OXY
  healthcare_biotech   — UNH, JNJ, PFE, MRK, ABBV, LLY, AMGN
  other                — catch-all
"""
from __future__ import annotations

from typing import Dict, List
from pydantic import BaseModel, Field


class WatchlistThemeGroup(BaseModel):
    theme_key: str                  # "ai_infrastructure" etc.
    theme_label: str                # "AI Infrastructure"
    description: str                # "GPU, networking, and silicon supply chain"
    macro_sensitivity: str          # "High rate sensitivity" | "China exposure" | etc.
    tickers: List[str] = Field(default_factory=list)
    ticker_count: int = 0


# Ticker → theme mapping (primary classification)
_TICKER_THEME_MAP: Dict[str, str] = {
    # AI infrastructure
    "NVDA": "ai_infrastructure", "AMD": "ai_infrastructure",
    "SMCI": "ai_infrastructure", "AVGO": "ai_infrastructure",
    "MRVL": "ai_infrastructure", "TSM": "ai_infrastructure",
    "ARM": "ai_infrastructure", "QCOM": "ai_infrastructure",
    "INTC": "ai_infrastructure",
    # Mega-cap tech
    "AAPL": "mega_cap_tech", "GOOGL": "mega_cap_tech", "GOOG": "mega_cap_tech",
    "MSFT": "mega_cap_tech", "META": "mega_cap_tech", "AMZN": "mega_cap_tech",
    "TSLA": "consumer_cyclical",
    # Consumer cyclical
    "NKE": "consumer_cyclical", "SBUX": "consumer_cyclical",
    "F": "consumer_cyclical", "GM": "consumer_cyclical",
    "HD": "consumer_cyclical", "LOW": "consumer_cyclical",
    # Financial
    "JPM": "financial", "BAC": "financial", "GS": "financial",
    "WFC": "financial", "BLK": "financial", "V": "financial",
    "MA": "financial", "AXP": "financial",
    # Energy
    "XOM": "energy_commodities", "CVX": "energy_commodities",
    "COP": "energy_commodities", "SLB": "energy_commodities",
    "OXY": "energy_commodities",
    # Healthcare
    "UNH": "healthcare_biotech", "JNJ": "healthcare_biotech",
    "PFE": "healthcare_biotech", "MRK": "healthcare_biotech",
    "ABBV": "healthcare_biotech", "LLY": "healthcare_biotech",
    "AMGN": "healthcare_biotech",
    # Rate-sensitive high-growth
    "RKLB": "rate_sensitive", "PLTR": "rate_sensitive",
    "NET": "rate_sensitive", "SNOW": "rate_sensitive",
    "DDOG": "rate_sensitive", "ZS": "rate_sensitive",
}

_THEME_METADATA: Dict[str, Dict[str, str]] = {
    "ai_infrastructure": {
        "label": "AI Infrastructure",
        "description": "GPU, networking silicon, and AI supply chain",
        "macro_sensitivity": "Demand cycle risk · CapEx dependency",
    },
    "mega_cap_tech": {
        "label": "Mega-Cap Tech",
        "description": "The five largest US technology platforms",
        "macro_sensitivity": "Rate duration · China exposure · Regulatory",
    },
    "rate_sensitive": {
        "label": "Rate-Sensitive Growth",
        "description": "High-multiple growth names with long-duration cash flows",
        "macro_sensitivity": "High rate sensitivity · No near-term profitability floor",
    },
    "consumer_cyclical": {
        "label": "Consumer Cyclical",
        "description": "Consumer discretionary names sensitive to spending cycles",
        "macro_sensitivity": "Consumer confidence · China exposure · Employment",
    },
    "financial": {
        "label": "Financials",
        "description": "Banks, asset managers, and payment networks",
        "macro_sensitivity": "Rate environment · Credit quality · Regulation",
    },
    "energy_commodities": {
        "label": "Energy & Commodities",
        "description": "Upstream and integrated energy producers",
        "macro_sensitivity": "Oil price · OPEC · Geopolitical risk",
    },
    "healthcare_biotech": {
        "label": "Healthcare & Biotech",
        "description": "Pharma, biotech, and managed care",
        "macro_sensitivity": "Clinical risk · Drug pricing · PBM regulation",
    },
    "other": {
        "label": "Other",
        "description": "Uncategorized positions",
        "macro_sensitivity": "Varies",
    },
}


def classify_ticker_theme(ticker: str, company_name: str = "") -> str:
    """Classify a ticker into its primary theme. Returns 'other' if unknown."""
    t = ticker.upper().strip()
    if t in _TICKER_THEME_MAP:
        return _TICKER_THEME_MAP[t]

    # Fallback: keyword matching on company name
    name_lower = company_name.lower()
    if any(kw in name_lower for kw in ["semiconductor", "chip", "gpu", "nvidia", "intel"]):
        return "ai_infrastructure"
    if any(kw in name_lower for kw in ["bank", "financial", "insurance", "asset management"]):
        return "financial"
    if any(kw in name_lower for kw in ["pharma", "biotech", "therapeutics", "health"]):
        return "healthcare_biotech"
    if any(kw in name_lower for kw in ["energy", "oil", "gas", "petroleum", "refin"]):
        return "energy_commodities"

    return "other"


def group_watchlist_by_theme(
    entries: List[dict],   # list of dicts with at least ticker and company_name keys
) -> List[WatchlistThemeGroup]:
    """
    Group watchlist entries by thematic classification.

    Returns only non-empty theme groups, sorted by ticker_count descending.
    The "other" group appears last.
    """
    groups: Dict[str, List[str]] = {}
    for entry in entries:
        ticker = (entry.get("ticker") or "").upper()
        company = entry.get("company_name", "")
        theme = classify_ticker_theme(ticker, company)
        groups.setdefault(theme, []).append(ticker)

    result: List[WatchlistThemeGroup] = []
    for theme_key, tickers in groups.items():
        meta = _THEME_METADATA.get(theme_key, _THEME_METADATA["other"])
        result.append(WatchlistThemeGroup(
            theme_key=theme_key,
            theme_label=meta["label"],
            description=meta["description"],
            macro_sensitivity=meta["macro_sensitivity"],
            tickers=sorted(tickers),
            ticker_count=len(tickers),
        ))

    # Sort: non-other by size desc, other always last
    result.sort(key=lambda g: (g.theme_key == "other", -g.ticker_count))
    return result
