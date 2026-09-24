"""Fetch a narrowly scoped, independently verifiable SEC revenue fact."""

from __future__ import annotations

import re

from ..config import settings
from ..integrity.sec_revenue_claim import REVENUE_CONCEPTS, latest_sec_revenue_claim
from ..providers.sec_client import get_company_fact_records_for_concepts
from .providers.sec_provider import _load_ticker_cik_map

_TICKER = re.compile(r"[A-Z]{1,5}(?:\.[A-Z])?\Z")


def fetch_verified_revenue_claim(ticker: str) -> dict | None:
    """Return one structured claim; never infer a document from prose.

    Caller enforces the request's authentication and retrieval wall clock.
    The SEC ticker map, rather than caller supplied company metadata,
    establishes the registrant identity.
    """
    if not isinstance(ticker, str) or not _TICKER.fullmatch(ticker):
        return None
    cik = _load_ticker_cik_map().get(ticker)
    if not cik or not cik.isdigit():
        return None
    records = get_company_fact_records_for_concepts(
        cik, concepts=REVENUE_CONCEPTS, unit="USD",
        user_agent=getattr(settings, "sec_user_agent", "") or "",
    )
    return latest_sec_revenue_claim(records, ticker=ticker, expected_cik=cik)
