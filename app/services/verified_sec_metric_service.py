"""Retrieve conservative, question-aware comparable SEC metric evidence."""

from __future__ import annotations

import re

from ..config import settings
from ..integrity.sec_metric_evidence import (
    comparable_instant_metric_evidence,
    comparable_metric_evidence,
)
from ..providers.sec_client import get_company_fact_records_for_concept_units
from ..schemas import RetrievedEvidence
from .providers.sec_provider import _load_ticker_cik_map

_TICKER = re.compile(r"[A-Z]{1,5}(?:\.[A-Z])?\Z")
_METRICS = (
    (("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"),
     "revenue", ("revenue", "revenues", "sales", "top line", "top-line"), "USD", "duration"),
    (("GrossProfit",), "gross profit", ("gross profit", "gross margin"), "USD", "duration"),
    (("OperatingIncomeLoss",), "operating income",
     ("operating income", "operating profit", "operating margin"), "USD", "duration"),
    (("NetIncomeLoss", "ProfitLoss"), "net income",
     ("net income", "net profit", "earnings"), "USD", "duration"),
    (("EarningsPerShareDiluted",), "diluted EPS",
     ("diluted eps", "diluted earnings per share", "earnings per share", "eps"),
     "USD/shares", "duration"),
    (("WeightedAverageNumberOfDilutedSharesOutstanding",), "diluted share count",
     ("diluted shares", "diluted share count", "weighted average shares", "share count"),
     "shares", "duration"),
    (("NetCashProvidedByUsedInOperatingActivities",), "operating cash flow",
     ("operating cash flow", "cash from operations", "cash generated from operations"),
     "USD", "duration"),
    (("InterestExpenseNonOperating",), "interest expense",
     ("interest expense", "interest cost", "interest costs"), "USD", "duration"),
    (("ResearchAndDevelopmentExpense",), "research and development",
     ("research and development", "r&d", "research expense", "development expense"),
     "USD", "duration"),
    (("PaymentsToAcquirePropertyPlantAndEquipment",), "capital expenditure",
     ("capital expenditure", "capital expenditures", "capex", "capital spending"),
     "USD", "duration"),
    (("ShareBasedCompensation", "StockBasedCompensation"), "stock-based compensation",
     ("stock-based compensation", "stock based compensation", "share-based compensation",
      "share based compensation", "sbc"), "USD", "duration"),
    (("PaymentsForRepurchaseOfCommonStock",), "share repurchases",
     ("share repurchase", "share repurchases", "stock repurchase", "stock repurchases",
      "buyback", "buybacks"), "USD", "duration"),
    (("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"), "dividends paid",
     ("dividend", "dividends", "dividends paid"), "USD", "duration"),
    (("CashAndCashEquivalentsAtCarryingValue",), "cash and cash equivalents",
     ("cash balance", "cash and cash equivalents", "cash equivalents", "cash position"),
     "USD", "instant"),
    (("LongTermDebtAndFinanceLeaseObligations", "LongTermDebt"), "total debt",
     ("total debt", "debt balance", "long-term debt", "long term debt", "leverage"),
     "USD", "instant"),
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
    concept_units = tuple(
        (concept, unit) for concepts, _, _, unit, _ in metrics for concept in concepts
    )
    records = get_company_fact_records_for_concept_units(
        cik, concept_units=concept_units,
        user_agent=getattr(settings, "sec_user_agent", "") or "",
    )
    evidence = []
    for concepts, metric_name, _, unit, period_kind in metrics:
        builder = (
            comparable_instant_metric_evidence
            if period_kind == "instant" else comparable_metric_evidence
        )
        # Concept aliases are ordered, not interchangeable observations. Try
        # each explicit taxonomy concept separately so an issuer exposing both
        # a narrow and broad concept cannot create a synthetic comparison.
        item = next((
            candidate for concept in concepts
            if (candidate := builder(
                records, ticker=ticker, expected_cik=cik,
                concepts=(concept,), metric_name=metric_name, unit=unit,
            )) is not None
        ), None)
        if item is not None:
            evidence.append(item)
    return evidence
