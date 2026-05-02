"""
Financial Modeling Prep client for company data retrieval.

This client encapsulates a handful of FMP endpoints that are useful
for enriching company analyses.  Each function handles HTTP
requests, response parsing, and error handling.  When a request
fails, functions return ``None`` or an empty structure so that the
calling code can gracefully fall back to placeholders.
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, List

import requests  # type: ignore

logger = logging.getLogger(__name__)


def _get(url: str) -> Optional[dict | list]:
    """Internal helper to perform a GET request and parse JSON.

    Returns ``None`` when any exception occurs.
    """
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning(f"FMP request failed: {exc}")
        return None


def get_company_profile(symbol: str, api_key: str = "") -> Optional[Dict[str, Optional[str]]]:
    """Fetch basic company profile information.

    Retrieves company name, industry, sector, and a short description.  If
    the request fails or no data is returned, ``None`` is returned.
    """
    url = f"https://financialmodelingprep.com/api/v3/profile/{symbol}"
    if api_key:
        url += f"?apikey={api_key}"
    data = _get(url)
    if not data or not isinstance(data, list):
        return None
    record = data[0]
    return {
        "name": record.get("companyName"),
        "industry": record.get("industry"),
        "sector": record.get("sector"),
        "description": record.get("description"),
        "ticker": record.get("symbol"),
        "ceo": record.get("ceo"),
        "website": record.get("website"),
    }


def get_market_snapshot(symbol: str, api_key: str = "") -> Optional[Dict[str, Optional[float]]]:
    """Fetch real‑time quote and market snapshot.

    Returns the current price, volume, market capitalization, and 52‑week
    high/low values.  Returns ``None`` on failure.
    """
    url = f"https://financialmodelingprep.com/api/v3/quote/{symbol}"
    if api_key:
        url += f"?apikey={api_key}"
    data = _get(url)
    if not data or not isinstance(data, list):
        return None
    record = data[0]
    return {
        "price": record.get("price"),
        "volume": record.get("volume"),
        "market_cap": record.get("marketCap"),
        "high_52_week": record.get("yearHigh"),
        "low_52_week": record.get("yearLow"),
    }


def get_financial_context(symbol: str, api_key: str = "", limit: int = 1) -> Optional[Dict[str, float]]:
    """Retrieve recent financial statement metrics.

    Extracts a few core metrics (revenue, net income, EBITDA, EPS) from
    the most recent income statement.  Returns ``None`` when the API
    call fails or no data is available.
    """
    url = f"https://financialmodelingprep.com/api/v3/income-statement/{symbol}?limit={limit}"
    if api_key:
        url += f"&apikey={api_key}"
    data = _get(url)
    if not data or not isinstance(data, list):
        return None
    record = data[0]
    context: Dict[str, float] = {}
    for api_field, ctx_field in [
        ("revenue", "revenue"),
        ("netIncome", "net_income"),
        ("ebitda", "ebitda"),
        ("eps", "eps"),
    ]:
        value = record.get(api_field)
        if isinstance(value, (int, float)):
            context[ctx_field] = float(value)
    return context or None


def get_recent_news(symbol: str, api_key: str = "", limit: int = 3) -> Optional[List[Dict[str, str]]]:
    """Retrieve recent news or press releases for a company.

    Uses the press releases endpoint to fetch the latest articles.  Each
    item includes a title and published date.  Returns ``None`` on
    failure.
    """
    url = f"https://financialmodelingprep.com/api/v3/press-releases/{symbol}?limit={limit}"
    if api_key:
        url += f"&apikey={api_key}"
    data = _get(url)
    if not data or not isinstance(data, list):
        return None
    news: List[Dict[str, str]] = []
    for item in data:
        title = item.get("title")
        date = item.get("publishedDate") or item.get("date")
        if title and date:
            news.append({"title": title, "date": date})
    return news or None
