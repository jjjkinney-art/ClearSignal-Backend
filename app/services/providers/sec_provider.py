"""
SEC EDGAR evidence provider.

Fetches company filing metadata from the SEC EDGAR EFTS (Elasticsearch-based)
full-text search API and converts it into RetrievedEvidence objects.

No API key is required — EDGAR is a public government service.  All requests
follow the SEC's rate-limit guidance (≤ 10 req/s) and include a descriptive
User-Agent header as required by SEC policy.

Capabilities
------------
fetch_recent_filings(company, forms, limit)
    Returns evidence objects for the most recent 10-K, 10-Q, and other SEC
    filings for the named company.  Each object carries the filing type, the
    period it covers, and the filing date.

Every function returns ``[]`` on any network, parsing, or rate-limit error.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import List
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ...schemas import RetrievedEvidence

logger = logging.getLogger(__name__)

# SEC mandates a descriptive User-Agent for automated access:
# https://www.sec.gov/os/accessing-edgar-data
_EDGAR_EFTS_BASE  = "https://efts.sec.gov/LATEST/search-index"
_USER_AGENT       = "ClearSignal-Backend research@example.com"

# Form-type human-readable labels for evidence titles.
_FORM_LABELS: dict = {
    "10-K":  "Annual Report (10-K)",
    "10-Q":  "Quarterly Report (10-Q)",
    "8-K":   "Current Report (8-K)",
    "DEF 14A": "Proxy Statement (DEF 14A)",
    "S-1":   "IPO Registration (S-1)",
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_json(url: str, timeout: int = 10):
    """Fetch JSON from *url* with the required SEC User-Agent header.  Raises."""
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _years_ago(n: int) -> str:
    """Return an ISO-8601 date string for *n* years before today."""
    return (datetime.date.today() - datetime.timedelta(days=365 * n)).isoformat()


def _form_label(form_type: str) -> str:
    return _FORM_LABELS.get(form_type, form_type)


# ── Public provider functions ─────────────────────────────────────────────────

def fetch_recent_filings(
    company: str,
    forms: List[str] | None = None,
    limit: int = 5,
    years_back: int = 2,
) -> List[RetrievedEvidence]:
    """Search EDGAR for recent filings by *company* and return evidence objects.

    Parameters
    ----------
    company : str
        Company name or ticker (used as the EDGAR full-text search query).
    forms : list of str, optional
        SEC form types to filter by.  Defaults to ``["10-K", "10-Q"]``.
    limit : int
        Maximum number of evidence objects to return.
    years_back : int
        Only include filings from the last *n* years.

    Returns
    -------
    List[RetrievedEvidence]
        Evidence objects sorted by recency (newest first), capped at *limit*.
        Returns ``[]`` on any error.
    """
    if not company or not company.strip():
        return []

    if forms is None:
        forms = ["10-K", "10-Q"]

    company = company.strip()
    start_date = _years_ago(years_back)

    params = {
        "q":             f'"{company}"',
        "forms":         ",".join(forms),
        "dateRange":     "custom",
        "startdt":       start_date,
    }
    url = f"{_EDGAR_EFTS_BASE}?{urlencode(params)}"

    print(
        f"[DIAG] SEC EDGAR: searching filings for '{company}' "
        f"forms={forms} since {start_date}"
    )

    try:
        data = _fetch_json(url)
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            logger.debug("SEC EDGAR: no filings found for '%s'", company)
            print(f"[DIAG] SEC EDGAR: no hits for '{company}'")
            return []

        evidence: List[RetrievedEvidence] = []
        seen_keys: set = set()

        for hit in hits:
            src = hit.get("_source", {})
            form_type   = src.get("form_type",        "")
            file_date   = src.get("file_date",         "")
            period      = src.get("period_of_report", "")
            entity_name = src.get("entity_name",      company)

            # Deduplicate: same company + form + period
            key = f"{entity_name}|{form_type}|{period}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            label   = _form_label(form_type)
            period_str = f" (period: {period})" if period else ""
            title = f"{entity_name} — {label} filed {file_date}{period_str}"
            summary = (
                f"{entity_name} filed a {label} with the SEC on {file_date}. "
                f"This report covers the period ending {period}. "
                f"10-K filings contain annual audited financials, risk factors, "
                f"and MD&A; 10-Q filings contain quarterly unaudited financials."
                if form_type in ("10-K", "10-Q")
                else f"{entity_name} filed a {label} with the SEC on {file_date}."
            )

            evidence.append(RetrievedEvidence(
                title=title,
                source="SEC EDGAR",
                summary=summary,
                timestamp=file_date,
                relevance_score=0.90 if form_type == "10-K" else 0.85,
            ))

            if len(evidence) >= limit:
                break

        print(f"[DIAG] SEC EDGAR: {len(evidence)} filing(s) returned for '{company}'")
        return evidence

    except HTTPError as exc:
        logger.warning("SEC EDGAR HTTP %d for '%s': %s", exc.code, company, exc.reason)
        print(f"[DIAG] SEC EDGAR: HTTP {exc.code} for '{company}': {exc.reason!r}")
    except URLError as exc:
        logger.warning("SEC EDGAR network error for '%s': %r", company, exc.reason)
        print(f"[DIAG] SEC EDGAR: network error for '{company}': {exc.reason!r}")
    except Exception as exc:
        logger.warning("SEC EDGAR unexpected error for '%s': %r", company, exc)
        print(f"[DIAG] SEC EDGAR: unexpected error for '{company}': {exc!r}")
    return []
