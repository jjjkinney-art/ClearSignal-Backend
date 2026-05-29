"""
SEC EDGAR evidence provider.

Fetches company filing metadata from the SEC EDGAR submissions API and
(as a fallback) the EFTS full-text search API, converting results into
RetrievedEvidence objects.

No API key is required — EDGAR is a public government service.  All requests
follow the SEC's rate-limit guidance (≤ 10 req/s) and include a descriptive
User-Agent header as required by SEC policy.

Lookup strategy (applied in order, first success wins)
-------------------------------------------------------
1. CIK lookup via ``/files/company_tickers.json`` (ticker → zero-padded CIK)
   then ``/submissions/CIK{cik}.json`` for actual filings.
2. EDGAR EFTS ``entity=`` search — matches on registered company name.
3. EDGAR EFTS ``q=`` full-text search — original behaviour; kept as last resort.

Why the change was needed
-------------------------
Passing a ticker like ``"TSLA"`` to the EFTS ``q=`` parameter does a
full-text body search across all filings, which either:
  • Returns filings from *other* companies that mention "TSLA" in their body
    (e.g. a 2017 filing that cited Tesla as a competitor), or
  • Returns zero results when the date filter is applied and no such document
    happens to exist in that window.
The ``entity=`` and CIK-based paths correctly target Tesla, Inc.'s own filings.

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
import re
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...schemas import RetrievedEvidence

logger = logging.getLogger(__name__)

# SEC mandates a descriptive User-Agent for automated access:
# https://www.sec.gov/os/accessing-edgar-data
_USER_AGENT           = "ClearSignal-Backend research@example.com"
_EDGAR_EFTS_BASE      = "https://efts.sec.gov/LATEST/search-index"
_COMPANY_TICKERS_URL  = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_BASE     = "https://data.sec.gov/submissions"

# Form-type human-readable labels for evidence titles.
_FORM_LABELS: dict = {
    "10-K":    "Annual Report (10-K)",
    "10-Q":    "Quarterly Report (10-Q)",
    "8-K":     "Current Report (8-K)",
    "DEF 14A": "Proxy Statement (DEF 14A)",
    "S-1":     "IPO Registration (S-1)",
}

# Module-level cache for ticker → zero-padded CIK (loaded once per process).
_ticker_cik_cache: Optional[Dict[str, str]] = None

# Pattern that looks like a US stock ticker: 1-5 uppercase ASCII letters,
# optionally a dot-class suffix (e.g. BRK.B).
_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


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


def _make_evidence(
    entity_name: str,
    form_type: str,
    file_date: str,
    period: str,
) -> RetrievedEvidence:
    """Build a RetrievedEvidence object from filing metadata."""
    label      = _form_label(form_type)
    period_str = f" (period: {period})" if period else ""
    title   = f"{entity_name} — {label} filed {file_date}{period_str}"
    summary = (
        f"{entity_name} filed a {label} with the SEC on {file_date}. "
        f"This report covers the period ending {period}. "
        f"10-K filings contain annual audited financials, risk factors, "
        f"and MD&A; 10-Q filings contain quarterly unaudited financials."
        if form_type in ("10-K", "10-Q")
        else f"{entity_name} filed a {label} with the SEC on {file_date}."
    )
    return RetrievedEvidence(
        title=title,
        source="SEC EDGAR",
        summary=summary,
        timestamp=file_date,
        relevance_score=0.90 if form_type == "10-K" else 0.85,
    )


# ── Strategy 1: CIK-based submissions lookup ─────────────────────────────────

def _load_ticker_cik_map() -> Dict[str, str]:
    """Return ticker → zero-padded CIK mapping, fetching from EDGAR once per process.

    Result is cached globally so repeated calls within the same process cost nothing.
    Returns ``{}`` on any error (caller falls back to other strategies).
    """
    global _ticker_cik_cache
    if _ticker_cik_cache is not None:
        return _ticker_cik_cache

    print("[DIAG] SEC EDGAR: loading ticker→CIK map from company_tickers.json …")
    try:
        data = _fetch_json(_COMPANY_TICKERS_URL, timeout=15)
        mapping: Dict[str, str] = {}
        for entry in data.values():
            ticker  = str(entry.get("ticker", "")).upper().strip()
            cik_int = entry.get("cik_str", 0)
            if ticker and cik_int:
                mapping[ticker] = str(int(cik_int)).zfill(10)
        _ticker_cik_cache = mapping
        print(f"[DIAG] SEC EDGAR: ticker→CIK map loaded — {len(mapping)} entries")
        return mapping
    except Exception as exc:
        logger.warning("SEC EDGAR: failed to load ticker→CIK map: %r", exc)
        print(f"[DIAG] SEC EDGAR: ticker→CIK map load failed: {exc!r} — will use EFTS fallback")
        _ticker_cik_cache = {}
        return {}


def _fetch_by_cik(
    ticker: str,
    forms: List[str],
    limit: int,
    years_back: int,
) -> List[RetrievedEvidence]:
    """Look up *ticker* → CIK, then fetch filings via the submissions API.

    Returns ``[]`` if the ticker is not in the CIK map or the API call fails.
    """
    ticker = ticker.upper().strip()
    cik_map = _load_ticker_cik_map()
    cik = cik_map.get(ticker)
    if not cik:
        print(f"[DIAG] SEC EDGAR (CIK): ticker '{ticker}' not in CIK map — skipping")
        return []

    url = f"{_SUBMISSIONS_BASE}/CIK{cik}.json"
    print(f"[DIAG] SEC EDGAR (CIK): fetching submissions for ticker={ticker} CIK={cik}")

    data        = _fetch_json(url, timeout=10)
    entity_name = data.get("name", ticker)
    recent      = data.get("filings", {}).get("recent", {})

    filing_dates = recent.get("filingDate", [])
    form_types   = recent.get("form", [])
    report_dates = recent.get("reportDate", [])

    # Filings are newest-first.
    cutoff   = _years_ago(years_back)
    evidence: List[RetrievedEvidence] = []
    seen_keys: set = set()

    for form_type, file_date, period in zip(form_types, filing_dates, report_dates):
        if file_date < cutoff:
            # All subsequent filings are older — stop scanning.
            break
        if form_type not in forms:
            continue

        key = f"{entity_name}|{form_type}|{period}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        evidence.append(_make_evidence(entity_name, form_type, file_date, period))

        if len(evidence) >= limit:
            break

    print(
        f"[DIAG] SEC EDGAR (CIK): {len(evidence)} filing(s) for "
        f"ticker={ticker} entity='{entity_name}'"
    )
    return evidence


# ── Strategy 2: EFTS entity= search ──────────────────────────────────────────

def _fetch_by_entity_name(
    company: str,
    forms: List[str],
    limit: int,
    years_back: int,
) -> List[RetrievedEvidence]:
    """Search EDGAR EFTS by entity/company name (not full-text body).

    The ``entity`` parameter in the EFTS API searches the filer's registered
    name, which avoids the false positives that the ``q=`` body search produces
    when a ticker is used as the query term.
    """
    start_date = _years_ago(years_back)
    params = {
        "q":         "",
        "entity":    company,
        "forms":     ",".join(forms),
        "dateRange":  "custom",
        "startdt":    start_date,
    }
    url = f"{_EDGAR_EFTS_BASE}?{urlencode(params)}"
    print(
        f"[DIAG] SEC EDGAR (entity=): searching entity='{company}' "
        f"forms={forms} since {start_date}"
    )

    data = _fetch_json(url)
    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        print(f"[DIAG] SEC EDGAR (entity=): no hits for entity='{company}'")
        return []

    evidence: List[RetrievedEvidence] = []
    seen_keys: set = set()

    for hit in hits:
        src         = hit.get("_source", {})
        form_type   = src.get("form_type",        "")
        file_date   = src.get("file_date",         "")
        period      = src.get("period_of_report", "")
        entity_name = src.get("entity_name",       company)

        key = f"{entity_name}|{form_type}|{period}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        evidence.append(_make_evidence(entity_name, form_type, file_date, period))

        if len(evidence) >= limit:
            break

    print(f"[DIAG] SEC EDGAR (entity=): {len(evidence)} filing(s) for '{company}'")
    return evidence


# ── Strategy 3: EFTS q= full-text fallback (original behaviour) ──────────────

def _fetch_by_fulltext(
    company: str,
    forms: List[str],
    limit: int,
    years_back: int,
) -> List[RetrievedEvidence]:
    """Original EFTS full-text search — ``q="company"``."""
    start_date = _years_ago(years_back)
    params = {
        "q":         f'"{company}"',
        "forms":     ",".join(forms),
        "dateRange":  "custom",
        "startdt":    start_date,
    }
    url = f"{_EDGAR_EFTS_BASE}?{urlencode(params)}"
    print(
        f"[DIAG] SEC EDGAR (q=): full-text search q='\"{company}\"' "
        f"forms={forms} since {start_date}"
    )

    data = _fetch_json(url)
    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        print(f"[DIAG] SEC EDGAR (q=): no hits for '{company}'")
        return []

    evidence: List[RetrievedEvidence] = []
    seen_keys: set = set()

    for hit in hits:
        src         = hit.get("_source", {})
        form_type   = src.get("form_type",        "")
        file_date   = src.get("file_date",         "")
        period      = src.get("period_of_report", "")
        entity_name = src.get("entity_name",       company)

        # Sanity-check: reject hits from clearly unrelated entities.
        # If the entity name contains none of the company tokens it is almost
        # certainly a false positive (e.g. a competitor mentioning the ticker
        # in their own filing body).
        company_tokens = set(company.upper().split())
        entity_upper   = entity_name.upper()
        if company_tokens and not any(tok in entity_upper for tok in company_tokens):
            logger.debug(
                "SEC EDGAR (q=): skipping unrelated entity '%s' for query '%s'",
                entity_name, company,
            )
            continue

        key = f"{entity_name}|{form_type}|{period}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        evidence.append(_make_evidence(entity_name, form_type, file_date, period))

        if len(evidence) >= limit:
            break

    print(f"[DIAG] SEC EDGAR (q=): {len(evidence)} filing(s) for '{company}'")
    return evidence


# ── Public provider function ──────────────────────────────────────────────────

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
        Company name or ticker.  When this looks like a US ticker symbol
        (1-5 uppercase letters), the CIK-based lookup is tried first, which
        is more accurate than full-text search.
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

    Lookup strategy (first success wins)
    -------------------------------------
    1. CIK lookup  — ticker → CIK → submissions API (most accurate)
    2. entity= EFTS — matches registered company name in EDGAR
    3. q= EFTS      — full-text body search (original fallback)
    """
    if not company or not company.strip():
        return []

    if forms is None:
        forms = ["10-K", "10-Q"]

    company = company.strip()

    print(
        f"[DIAG] SEC EDGAR: fetch_recent_filings("
        f"company={company!r}, forms={forms}, limit={limit}, years_back={years_back})"
    )

    # ── Strategy 1: ticker → CIK → submissions ───────────────────────────────
    looks_like_ticker = bool(_TICKER_RE.match(company))
    if looks_like_ticker:
        try:
            result = _fetch_by_cik(company, forms, limit, years_back)
            if result:
                return result
        except HTTPError as exc:
            print(f"[DIAG] SEC EDGAR (CIK): HTTP {exc.code} — falling back")
        except URLError as exc:
            print(f"[DIAG] SEC EDGAR (CIK): network error {exc.reason!r} — falling back")
        except Exception as exc:
            print(f"[DIAG] SEC EDGAR (CIK): unexpected error {exc!r} — falling back")

    # ── Strategy 2: entity= EFTS search ─────────────────────────────────────
    try:
        result = _fetch_by_entity_name(company, forms, limit, years_back)
        if result:
            return result
    except HTTPError as exc:
        print(f"[DIAG] SEC EDGAR (entity=): HTTP {exc.code} — falling back")
    except URLError as exc:
        print(f"[DIAG] SEC EDGAR (entity=): network error {exc.reason!r} — falling back")
    except Exception as exc:
        print(f"[DIAG] SEC EDGAR (entity=): unexpected error {exc!r} — falling back")

    # ── Strategy 3: q= full-text EFTS (original fallback) ───────────────────
    try:
        result = _fetch_by_fulltext(company, forms, limit, years_back)
        return result
    except HTTPError as exc:
        logger.warning("SEC EDGAR HTTP %d for '%s': %s", exc.code, company, exc.reason)
        print(f"[DIAG] SEC EDGAR (q=): HTTP {exc.code} — giving up")
    except URLError as exc:
        logger.warning("SEC EDGAR network error for '%s': %r", company, exc.reason)
        print(f"[DIAG] SEC EDGAR (q=): network error — giving up")
    except Exception as exc:
        logger.warning("SEC EDGAR unexpected error for '%s': %r", company, exc)
        print(f"[DIAG] SEC EDGAR (q=): unexpected error {exc!r} — giving up")

    return []
