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
from dataclasses import dataclass
from datetime import date
from typing import List, Optional
from urllib.parse import urlsplit
from xml.etree import ElementTree

import requests  # type: ignore

logger = logging.getLogger(__name__)
_ATOM = "{http://www.w3.org/2005/Atom}"
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}\Z")


@dataclass(frozen=True)
class SecFactRecord:
    """One XBRL observation, tied to its filing and reporting period."""

    cik: str
    taxonomy: str
    concept: str
    label: str
    unit: str
    value: int | float
    start: Optional[str]
    end: str
    filed: str
    form: str
    accession: str
    filing_url: str


def parse_company_fact_records(data: dict, *, concept: str, unit: str) -> list[SecFactRecord]:
    """Select observations for one explicit US-GAAP concept and unit.

    Do not infer that a number in generated prose represents this concept.
    Each returned URL is a filing index, identified by that observation's
    accession; it is not a claim citation until a producer binds the fact.
    """
    cik = str(data.get("cik", ""))
    if not cik.isdigit() or not concept or not unit:
        return []
    facts = data.get("facts", {})
    gaap = facts.get("us-gaap", {}) if isinstance(facts, dict) else {}
    entry = gaap.get(concept, {}) if isinstance(gaap, dict) else {}
    units = entry.get("units", {}) if isinstance(entry, dict) else {}
    observations = units.get(unit, []) if isinstance(units, dict) else []
    if not isinstance(observations, list):
        return []
    records = []
    for item in observations:
        if not isinstance(item, dict):
            continue
        accession, form = item.get("accn"), item.get("form")
        if not isinstance(accession, str) or not _ACCESSION.fullmatch(accession):
            continue
        if form not in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
            continue
        end, filed, start = item.get("end"), item.get("filed"), item.get("start")
        try:
            date.fromisoformat(end)
            date.fromisoformat(filed)
            if start is not None:
                date.fromisoformat(start)
        except (TypeError, ValueError):
            continue
        value = item.get("val")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        records.append(SecFactRecord(
            cik=cik, taxonomy="us-gaap", concept=concept,
            label=str(entry.get("label", concept)), unit=unit, value=value,
            start=start, end=end, filed=filed, form=form, accession=accession,
            filing_url=(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                        f"{accession.replace('-', '')}/{accession}-index.htm"),
        ))
    return records


def get_company_fact_records(cik: str, *, concept: str, unit: str,
                             user_agent: str = "") -> list[SecFactRecord]:
    """Fetch a specified concept's observations; fail closed on SEC errors."""
    return get_company_fact_records_for_concepts(
        cik, concepts=(concept,), unit=unit, user_agent=user_agent,
    )


def get_company_fact_records_for_concepts(
    cik: str, *, concepts: tuple[str, ...], unit: str, user_agent: str = "",
) -> list[SecFactRecord]:
    """Fetch several explicit concepts in one Company Facts request."""
    if not cik or not cik.isdigit() or not concepts or not all(concepts) or not unit:
        return []
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json"
    try:
        response = requests.get(url, headers={"User-Agent": user_agent or "ai-analyst-bot/0.1"}, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or str(data.get("cik", "")) != str(int(cik)):
            return []
        return [record for concept in concepts
                for record in parse_company_fact_records(data, concept=concept, unit=unit)]
    except Exception as exc:
        logger.warning("SEC structured fact retrieval failed for CIK %s: %s", cik, exc)
        return []


def _filing_link(entry: ElementTree.Element) -> Optional[str]:
    """Return only a direct SEC archive link from this specific Atom entry."""
    for link in entry.findall(f"{_ATOM}link"):
        if link.get("rel", "alternate") != "alternate":
            continue
        href = link.get("href", "")
        try:
            parsed = urlsplit(href)
            port = parsed.port
        except ValueError:
            continue
        if (parsed.scheme == "https" and parsed.hostname == "www.sec.gov"
                and parsed.username is None and parsed.password is None
                and port is None and parsed.path.startswith("/Archives/edgar/data/")
                and not parsed.fragment and not any(ord(c) < 33 or c == "\\" for c in href)):
            return href
    return None


def _parse_filing_feed(xml_text: str, count: int) -> List[FilingItem]:
    """Parse entry-scoped SEC filing metadata without making a network call."""
    root = ElementTree.fromstring(xml_text)
    filings: List[FilingItem] = []
    for entry in root.findall(f"{_ATOM}entry")[:count]:
        title = (entry.findtext(f"{_ATOM}title") or "").strip()
        filing_date = (entry.findtext(f"{_ATOM}updated") or "")[:10]
        try:
            date.fromisoformat(filing_date)
        except ValueError:
            continue
        if not title:
            continue
        filings.append(FilingItem({
            "filing_type": title.split()[0],
            "filing_date": filing_date,
            "title": title,
            "url": _filing_link(entry),
        }))
    return filings


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
        return _parse_filing_feed(resp.text, count)
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
