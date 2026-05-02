"""
SEC EDGAR client for retrieving company filings and basic facts.

This client provides thin wrappers around a couple of useful EDGAR
endpoints needed for the analyst workflow.  Only a minimal subset
is implemented: retrieval of recent filings metadata and basic
company facts.  All network interactions use timeouts and catch
exceptions so that failures never propagate up the call stack.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

import requests  # type: ignore

logger = logging.getLogger(__name__)


class FilingItem(dict):
    """Simple dictionary subclass representing a filing event.

    Keys include ``filing_type``, ``filing_date``, ``title`` and ``url``.
    This structure is intentionally lightweight to avoid introducing a
    dependency on the Pydantic models at this layer.  Consumers are
    expected to convert dictionaries into more robust models when
    assembling the grounding context.
    """


def get_recent_filings(company: str, ticker: Optional[str] = None, user_agent: str = "", count: int = 3) -> List[FilingItem]:
    """Retrieve recent filing events from SEC EDGAR.

    Parameters
    ----------
    company : str
        The company name, used only when ticker is unavailable.
    ticker : Optional[str]
        Stock ticker symbol or CIK.  Required for the API call; when
        absent, no request is made and an empty list is returned.
    user_agent : str
        A descriptive user agent string; the SEC requires that API
        requests identify the calling application.  If omitted, a
        default agent is used.
    count : int
        Number of filings to fetch (defaults to 3).

    Returns
    -------
    List[FilingItem]
        A list of filing metadata dictionaries.  When retrieval fails
        or no ticker is provided, the list is empty.
    """
    if not ticker:
        return []
    # Use the SEC company search endpoint with output=atom to obtain an
    # Atom feed of recent filings.  We limit to the specified count and
    # request 10-K and 10-Q filings which are most relevant to the
    # analyst.  The feed includes title and updated (date) tags.
    url = (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&CIK={ticker}&type=10-K&owner=include&count={count}&output=atom"
    )
    headers = {"User-Agent": user_agent or "ai-analyst-bot/0.1"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        text = resp.text
        # Extract filing titles and dates using a naive regex.  The first
        # <title> element is the feed title and is skipped.  Dates come
        # from <updated> tags.  We pair titles and dates by index.
        titles = re.findall(r"<title>(.*?)</title>", text, re.DOTALL)
        dates = re.findall(r"<updated>(\d{4}-\d{2}-\d{2})", text)
        filings: List[FilingItem] = []
        for title, date in zip(titles[1:], dates):
            # Derive the filing type from the beginning of the title
            filing_type = title.split()[0] if title else ""
            filings.append(FilingItem({
                "filing_type": filing_type,
                "filing_date": date,
                "title": title,
                "url": None,
            }))
        return filings
    except Exception as exc:
        logger.warning(f"SEC EDGAR retrieval failed for {ticker}: {exc}")
        return []


def get_company_facts(cik: str, user_agent: str = "") -> dict:
    """Retrieve basic company facts from the SEC Company Facts API.

    The SEC hosts a JSON endpoint that provides entity information and
    selected financial statement facts keyed by the Central Index Key (CIK).
    This function attempts a lightweight retrieval and extracts a few
    top‑level fields for use in the grounding context.  When the CIK
    is missing, malformed or the request fails, an empty dict is
    returned.  The returned dictionary may contain keys such as
    ``entityName``, ``cik`` and ``ticker``.  Parsing of detailed facts
    (e.g. XBRL taxonomy) is intentionally omitted to avoid overbuilding.

    Parameters
    ----------
    cik : str
        Ten‑digit Central Index Key identifying the registrant.  If the
        string contains fewer than ten digits, it will be left‑padded
        with zeros as required by the SEC API.  Non‑numeric values
        bypass retrieval and result in an empty dict.
    user_agent : str
        User agent string for the SEC API.  A descriptive agent is
        recommended to comply with SEC terms.  A default is used when
        not provided.

    Returns
    -------
    dict
        Dictionary containing extracted company fact fields.  Empty
        when retrieval or parsing fails.
    """
    if not cik or not cik.isdigit():
        return {}
    # CIK must be 10 digits; pad with leading zeros if necessary.
    padded_cik = cik.zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{padded_cik}.json"
    headers = {"User-Agent": user_agent or "ai-analyst-bot/0.1"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result: dict = {}
        # Extract a handful of top‑level fields if present
        for key in ["entityName", "cik", "ticker"]:
            if key in data and data[key]:
                result[key] = data[key]
        return result
    except Exception as exc:
        logger.warning(f"SEC company facts retrieval failed for {cik}: {exc}")
        return {}
