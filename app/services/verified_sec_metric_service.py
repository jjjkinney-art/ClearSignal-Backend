"""Retrieve a conservative set of comparable SEC operating metrics."""

from __future__ import annotations

import re

from ..config import settings
from ..integrity.sec_metric_evidence import comparable_metric_evidence
from ..providers.sec_client import get_company_fact_records_for_concepts
from ..schemas import RetrievedEvidence
from .providers.sec_provider import _load_ticker_cik_map

_TICKER = re.compile(r"[A-Z]{1,5}(?:\.[A-Z])?\Z")
_METRICS = (
    (("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"), "revenue"),
    (("OperatingIncomeLoss",), "operating income"),
    (("NetCashProvidedByUsedInOperatingActivities",), "operating cash flow"),
)
_CONCEPTS = tuple(concept for concepts, _ in _METRICS for concept in concepts)


def fetch_verified_metric_evidence(ticker: str) -> list[RetrievedEvidence]:
    """Return only facts with an exact prior-year comparable observation."""
    if not isinstance(ticker, str) or not _TICKER.fullmatch(ticker):
        return []
    cik = _load_ticker_cik_map().get(ticker)
    if not cik or not cik.isdigit():
        return []
    records = get_company_fact_records_for_concepts(
        cik, concepts=_CONCEPTS, unit="USD",
        user_agent=getattr(settings, "sec_user_agent", "") or "",
    )
    evidence = []
    for concepts, metric_name in _METRICS:
        item = comparable_metric_evidence(
            records, ticker=ticker, expected_cik=cik,
            concepts=concepts, metric_name=metric_name,
        )
        if item is not None:
            evidence.append(item)
    return evidence
