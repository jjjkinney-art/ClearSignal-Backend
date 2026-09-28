"""Retrieve conservative, question-aware comparable SEC metric evidence."""

from __future__ import annotations

import re

from ..config import settings
from ..integrity.sec_metric_evidence import comparable_metric_evidence
from ..providers.sec_client import get_company_fact_records_for_concepts
from ..schemas import RetrievedEvidence
from .providers.sec_provider import _load_ticker_cik_map

_TICKER = re.compile(r"[A-Z]{1,5}(?:\.[A-Z])?\Z")
_METRICS = (
    (("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"),
     "revenue", ("revenue", "revenues", "sales", "top line", "top-line")),
    (("GrossProfit",), "gross profit", ("gross profit", "gross margin")),
    (("OperatingIncomeLoss",), "operating income",
     ("operating income", "operating profit", "operating margin")),
    (("NetIncomeLoss", "ProfitLoss"), "net income",
     ("net income", "net profit", "earnings")),
    (("NetCashProvidedByUsedInOperatingActivities",), "operating cash flow",
     ("operating cash flow", "cash from operations", "cash generated from operations")),
    (("ResearchAndDevelopmentExpense",), "research and development",
     ("research and development", "r&d", "research expense", "development expense")),
    (("PaymentsToAcquirePropertyPlantAndEquipment",), "capital expenditure",
     ("capital expenditure", "capital expenditures", "capex", "capital spending")),
    (("ShareBasedCompensation", "StockBasedCompensation"), "stock-based compensation",
     ("stock-based compensation", "stock based compensation", "share-based compensation",
      "share based compensation", "sbc")),
    (("PaymentsForRepurchaseOfCommonStock",), "share repurchases",
     ("share repurchase", "share repurchases", "stock repurchase", "stock repurchases",
      "buyback", "buybacks")),
    (("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"), "dividends paid",
     ("dividend", "dividends", "dividends paid")),
)


def _requested_metrics(question: str | None) -> tuple:
    """Narrow an explicit metric question without guessing from broad prose."""
    normalized = re.sub(r"\s+", " ", (question or "").lower()).strip()
    if not normalized:
        return _METRICS
    matched = tuple(
        metric for metric in _METRICS
        if any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized)
               for term in metric[2])
    )
    return matched or _METRICS


def fetch_verified_metric_evidence(
    ticker: str, *, question: str | None = None,
) -> list[RetrievedEvidence]:
    """Return only facts with an exact prior-year comparable observation."""
    if not isinstance(ticker, str) or not _TICKER.fullmatch(ticker):
        return []
    cik = _load_ticker_cik_map().get(ticker)
    if not cik or not cik.isdigit():
        return []
    metrics = _requested_metrics(question)
    concepts_to_fetch = tuple(
        concept for concepts, _, _ in metrics for concept in concepts
    )
    records = get_company_fact_records_for_concepts(
        cik, concepts=concepts_to_fetch, unit="USD",
        user_agent=getattr(settings, "sec_user_agent", "") or "",
    )
    evidence = []
    for concepts, metric_name, _ in metrics:
        item = comparable_metric_evidence(
            records, ticker=ticker, expected_cik=cik,
            concepts=concepts, metric_name=metric_name,
        )
        if item is not None:
            evidence.append(item)
    return evidence
