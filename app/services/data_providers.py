"""
External data provider hooks for evidence gathering.

This module centralizes the logic for retrieving up‑to‑date information
from third‑party data sources.  It currently supports minimal
integration with SEC EDGAR and Financial Modeling Prep (FMP).  These
functions are deliberately defensive: they use short timeouts,
gracefully handle HTTP errors, and return empty structures when
requests fail.  This design prevents network issues from
interrupting the analysis pipeline and allows the backend to run
without external connectivity.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import requests  # type: ignore

logger = logging.getLogger(__name__)


def _sec_feed_url(ticker: str, count: int, boundary: str = "") -> str:
    query_count = max(count, 100) if boundary else count
    url = (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&CIK={ticker}&type=10-K&count={query_count}&output=atom"
    )
    if boundary:
        url += f"&dateb={boundary.replace('-', '')}"
    return url


def _parse_sec_feed_events(text: str, count: int, boundary: str = "") -> List[str]:
    import re

    titles = re.findall(r"<title>(.*?)</title>", text)
    dates = re.findall(r"<updated>(\d{4}-\d{2}-\d{2})", text)
    events: List[str] = []
    for title, filing_date in zip(titles[1:], dates):
        if boundary and filing_date > boundary:
            continue
        events.append(f"{title} on {filing_date}")
        if len(events) >= count:
            break
    return events


def fetch_fmp_financials(ticker: str, api_key: str = "", limit: int = 1) -> Dict[str, float]:
    """Fetch basic financial metrics from Financial Modeling Prep.

    Returns a dictionary of selected metrics (e.g., revenue, net income) for
    the most recent period.  If retrieval fails or no data is available,
    an empty dict is returned.

    Parameters
    ----------
    ticker : str
        The stock ticker symbol (e.g., ``AAPL``).
    api_key : str, optional
        API key for FMP.  If provided, it is appended to the query; if
        empty, unauthenticated access will be attempted which may
        be subject to stricter rate limits.
    limit : int, optional
        Number of periods to retrieve; defaults to 1 (most recent).

    Returns
    -------
    Dict[str, float]
        A dictionary mapping metric names to numeric values.
    """
    url = f"https://financialmodelingprep.com/api/v3/income-statement/{ticker}?limit={limit}"
    if api_key:
        url += f"&apikey={api_key}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return {}
        record = data[0]
        metrics: Dict[str, float] = {}
        # Map a few common metrics.  Use .get to avoid KeyError.
        for field_name, pretty_name in [
            ("revenue", "revenue"),
            ("netIncome", "net_income"),
            ("ebitda", "ebitda"),
            ("eps", "eps"),
        ]:
            value = record.get(field_name)
            if isinstance(value, (int, float)):
                metrics[pretty_name] = float(value)
        return metrics
    except Exception as exc:
        logger.warning(f"FMP retrieval failed for {ticker}: {exc}")
        return {}


def fetch_sec_filings(
    company: str,
    ticker: Optional[str] = None,
    user_agent: str = "",
    count: int = 1,
    as_of: Optional[str] = None,
) -> Dict[str, List[str]]:
    """Fetch recent filing events and basic facts from SEC EDGAR.

    Attempts to retrieve the most recent 10‑K or 10‑Q filings via the SEC
    EDGAR search API.  Returns a dictionary containing lists of
    ``recent_events``, ``known_facts``, and ``source_notes``.  When the
    retrieval fails, returns empty lists.

    Parameters
    ----------
    company : str
        Company name used for fallback if ticker is unavailable.
    ticker : str, optional
        Stock ticker symbol; used to construct the query if provided.
    user_agent : str, optional
        User agent string required by the SEC API.  Should identify
        the application and include a contact email.
    count : int, optional
        Number of filings to fetch; defaults to 1 (most recent).

    Returns
    -------
    Dict[str, List[str]]
        Dictionary with keys ``recent_events``, ``known_facts``, and
        ``source_notes``; each value is a list of strings.
    """
    events: List[str] = []
    facts: List[str] = []
    notes: List[str] = []
    # Without a ticker we cannot query EDGAR programmatically; return empty
    if not ticker:
        return {"recent_events": events, "known_facts": facts, "source_notes": notes}
    # Use SEC's company filing search endpoint (atom feed).  Build query
    # to return the most recent filings of type 10-K or 10-Q.  We set
    # output=atom to receive an XML feed which we parse with a simple
    # regular expression.  The SEC requires a descriptive User-Agent.
    boundary = ""
    if as_of:
        try:
            from datetime import date
            boundary = date.fromisoformat(str(as_of)[:10]).isoformat()
        except (TypeError, ValueError):
            boundary = ""
    url = _sec_feed_url(ticker, count, boundary)
    headers = {"User-Agent": user_agent or "ai-analyst-bot/0.1"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        text = resp.text
        events.extend(_parse_sec_feed_events(text, count, boundary))
        # Source note
        notes.append("SEC EDGAR recent filings")
        # We cannot easily extract known facts from EDGAR atom feed; return empty facts
        return {"recent_events": events, "known_facts": facts, "source_notes": notes}
    except Exception as exc:
        logger.warning(f"SEC EDGAR retrieval failed for {ticker}: {exc}")
        return {"recent_events": [], "known_facts": [], "source_notes": []}
