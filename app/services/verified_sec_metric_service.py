"""Retrieve conservative, question-aware comparable SEC metric evidence."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from ..config import settings
from ..integrity.sec_metric_evidence import (
    comparable_instant_metric_evidence,
    comparable_metric_evidence,
)
from ..providers.sec_client import get_company_fact_records_for_concept_units
from ..schemas import RetrievedEvidence
from .providers.sec_provider import _load_ticker_cik_map

_TICKER = re.compile(r"[A-Z]{1,5}(?:\.[A-Z])?\Z")
_LATEST_PERIOD_ANCHOR = ("Assets", "USD")
_MAX_STALENESS_DAYS = 550
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
    (("InterestIncomeExpenseNet",), "net interest income",
     ("net interest income", "net interest revenue"), "USD", "duration"),
    (("Deposits",), "deposits",
     ("deposit balance", "deposit balances", "total deposits", "deposits"),
     "USD", "instant"),
    (("FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss",),
     "net financing receivables",
     ("net financing receivables", "financing receivables", "net loans", "loan balance",
      "loan balances"), "USD", "instant"),
    (("FinancingReceivableAllowanceForCreditLossExcludingAccruedInterest",
      "FinancingReceivableAllowanceForCreditLosses"),
     "allowance for credit losses",
     ("allowance for credit losses", "credit loss allowance", "loan loss allowance",
      "allowance for loan losses"), "USD", "instant"),
    (("FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal",
      "ProvisionForLoanLossesExpensed"),
     "credit loss expense or reversal",
     ("credit loss expense", "credit loss provision", "provision for credit losses",
      "provision for loan losses"), "USD", "duration"),
    (("FinancingReceivableExcludingAccruedInterestAllowanceForCreditLossWriteoff",),
     "gross financing receivable charge-offs",
     ("gross charge-offs", "gross chargeoffs", "loan write-offs", "loan writeoffs"),
     "USD", "duration"),
    (("FinancingReceivableExcludingAccruedInterestAllowanceForCreditLossWriteoffAfterRecovery",),
     "net financing receivable charge-offs",
     ("net charge-offs", "net chargeoffs", "net loan losses"), "USD", "duration"),
    (("PremiumsEarnedNet",), "net premiums earned",
     ("net premiums earned", "premiums earned", "earned premiums"), "USD", "duration"),
    (("PremiumsWrittenNet",), "net premiums written",
     ("net premiums written", "premiums written", "written premiums"), "USD", "duration"),
    (("PolicyholderBenefitsAndClaimsIncurredNet",),
     "policyholder benefits and claims incurred",
     ("policyholder benefits", "claims incurred", "insurance claims incurred",
      "benefits and claims"), "USD", "duration"),
    (("NetInvestmentIncome", "InvestmentIncomeNet"), "net investment income",
     ("net investment income", "insurance investment income"), "USD", "duration"),
    (("UnearnedPremiums",), "unearned premium reserve",
     ("unearned premiums", "unearned premium reserve", "premium reserve"),
     "USD", "instant"),
    (("SupplementalInformationForPropertyCasualtyInsuranceUnderwritersReservesForUnpaidClaimsAndClaimsAdjustmentExpense",
      "SupplementaryInsuranceInformationLiabilityForFuturePolicyBenefitsLossesClaimsAndLossExpenseReserves"),
     "reported insurance loss and benefit reserves",
     ("insurance loss reserves", "loss and benefit reserves", "claims reserves",
      "loss reserves"), "USD", "instant"),
    (("RevenueRemainingPerformanceObligation",),
     "remaining performance obligations",
     ("remaining performance obligations", "remaining performance obligation", "rpo"),
     "USD", "instant"),
    (("ContractWithCustomerLiability",), "total contract liabilities",
     ("total contract liabilities", "total deferred revenue"), "USD", "instant"),
    (("ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent"),
     "current contract liabilities",
     ("current contract liabilities", "current contract liability",
      "current deferred revenue", "deferred revenue"), "USD", "instant"),
    (("ContractWithCustomerLiabilityNoncurrent", "DeferredRevenueNoncurrent"),
     "noncurrent contract liabilities",
     ("noncurrent contract liabilities", "non-current contract liabilities",
      "long-term deferred revenue", "long term deferred revenue"), "USD", "instant"),
    (("ContractWithCustomerLiabilityRevenueRecognized",),
     "revenue recognized from contract liabilities",
     ("revenue recognized from contract liabilities",
      "revenue recognized from deferred revenue", "deferred revenue recognized",
      "contract liability revenue recognition"),
     "USD", "duration"),
    (("LeaseIncome", "OperatingLeaseLeaseIncome",
      "OperatingLeasesIncomeStatementLeaseRevenue"),
     "lease income",
     ("lease income", "rental income", "rental revenue", "rental revenues"),
     "USD", "duration"),
    (("RealEstateInvestmentPropertyNet",), "net investment property",
     ("net investment property", "net real estate assets", "net property assets"),
     "USD", "instant"),
    (("RealEstateInvestmentPropertyAtCost",), "investment property at cost",
     ("investment property at cost", "real estate at cost", "property at cost"),
     "USD", "instant"),
    (("RealEstateInvestmentPropertyAccumulatedDepreciation",
      "RealEstateAccumulatedDepreciation"),
     "real estate accumulated depreciation",
     ("real estate accumulated depreciation", "property accumulated depreciation"),
     "USD", "instant"),
    (("PaymentsToAcquireCommercialRealEstate", "PaymentsToAcquireRealEstate",
      "PaymentsToAcquireRealEstateAndRealEstateJointVentures"),
     "real estate acquisition spending",
     ("real estate acquisition spending", "property acquisition spending",
      "real estate acquisitions", "property acquisitions"), "USD", "duration"),
    (("ProceedsFromRealEstateAndRealEstateJointVentures",
      "ProceedsFromSaleOfRealEstateHeldforinvestment", "ProceedsFromSaleOfRealEstate"),
     "real estate disposition proceeds",
     ("real estate disposition proceeds", "property disposition proceeds",
      "real estate sale proceeds", "property sale proceeds"), "USD", "duration"),
    (("SecuredDebt",), "secured debt",
     ("secured debt", "mortgage debt", "property debt"), "USD", "instant"),
    (("ImpairmentOfRealEstate",), "real estate impairment",
     ("real estate impairment", "property impairment"), "USD", "duration"),
)


def structured_claims_from_evidence(items: list[RetrievedEvidence]) -> list[dict]:
    """Flatten only producer-bound structured claims, preserving order."""
    claims = []
    seen = set()
    for item in items:
        for claim in item.verified_claims:
            if not isinstance(claim, dict):
                continue
            reference = claim.get("document_ref")
            if not isinstance(reference, dict) or not reference.get("reference_id"):
                continue
            identity = (
                claim.get("ticker"), claim.get("metric"), claim.get("as_of"),
                str(claim.get("raw_value")), reference.get("reference_id"),
            )
            if identity in seen:
                continue
            seen.add(identity)
            claims.append(dict(claim))
    return claims


def structured_calculations_from_evidence(
    items: list[RetrievedEvidence],
) -> list[dict]:
    """Flatten producer-built calculations without promoting them to facts."""
    calculations = []
    seen = set()
    for item in items:
        for claim in item.calculated_claims:
            if not isinstance(claim, dict):
                continue
            calculation_id = str(claim.get("calculation_id", "")).strip()
            inputs = claim.get("inputs")
            if not calculation_id or calculation_id in seen or not isinstance(inputs, list):
                continue
            if len(inputs) < 2 or not all(
                isinstance(value, dict) and value.get("reference_id")
                for value in inputs
            ):
                continue
            seen.add(calculation_id)
            calculations.append(dict(claim))
    return calculations


def _attach_free_cash_flow_calculations(
    items: list[RetrievedEvidence],
) -> None:
    """Attach exact OCF minus capex calculations for compatible periods."""
    claims = [
        claim for item in items for claim in item.verified_claims
        if isinstance(claim, dict)
    ]
    by_metric = {
        metric: [claim for claim in claims if claim.get("metric") == metric]
        for metric in (
            "us-gaap:NetCashProvidedByUsedInOperatingActivities",
            "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        )
    }
    operating = by_metric["us-gaap:NetCashProvidedByUsedInOperatingActivities"]
    capex = by_metric["us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"]
    calculations = []
    for cash_claim in operating:
        matches = [
            claim for claim in capex
            if all(claim.get(field) == cash_claim.get(field)
                   for field in ("ticker", "period", "scope", "unit", "currency"))
            and claim.get("unit") == "USD"
        ]
        if len(matches) != 1:
            continue
        capex_claim = matches[0]
        try:
            value = Decimal(str(cash_claim["raw_value"])) - Decimal(
                str(capex_claim["raw_value"])
            )
        except (KeyError, InvalidOperation):
            continue
        input_rows = []
        for role, claim in (("operating_cash_flow", cash_claim),
                            ("capital_expenditure", capex_claim)):
            reference = claim.get("document_ref")
            if not isinstance(reference, dict) or not reference.get("reference_id"):
                input_rows = []
                break
            input_rows.append({
                "role": role,
                "metric": claim["metric"],
                "raw_value": str(claim["raw_value"]),
                "unit": claim["unit"],
                "period": claim["period"],
                "scope": claim["scope"],
                "reference_id": reference["reference_id"],
            })
        if len(input_rows) != 2:
            continue
        exact = format(value, "f")
        ticker = str(cash_claim["ticker"])
        period = str(cash_claim["period"])
        calculations.append({
            "calculation_id": f"{ticker}-{period}-free-cash-flow",
            "ticker": ticker,
            "metric": "ClearSignal:FreeCashFlow",
            "provenance": "derived",
            "raw_value": exact,
            "unit": "USD",
            "currency": "USD",
            "period": period,
            "scope": cash_claim["scope"],
            "formula": "operating_cash_flow - capital_expenditure",
            "inputs": input_rows,
        })
    if calculations and items:
        items[0].calculated_claims.extend(calculations)


def _requested_metrics(question: str | None) -> tuple:
    """Narrow an explicit metric question without guessing from broad prose."""
    normalized = re.sub(r"\s+", " ", (question or "").lower()).strip()
    if not normalized:
        return _METRICS
    if re.search(r"(?<!\w)(?:free cash flow|fcf)(?!\w)", normalized):
        required = {"operating cash flow", "capital expenditure"}
        return tuple(metric for metric in _METRICS if metric[1] in required)
    matches = [
        (metric, tuple(
            term for term in metric[2]
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized)
        ))
        for metric in _METRICS
    ]
    matches = [(metric, terms) for metric, terms in matches if terms]
    if not matches:
        return _METRICS
    selected = []
    for metric, terms in matches:
        other_terms = {
            other_term
            for other_metric, other_matches in matches if other_metric is not metric
            for other_term in other_matches
        }
        # "total deferred revenue" should not also retrieve generic revenue or
        # current deferred revenue. Preserve genuine multi-metric questions by
        # suppressing a metric only when every one of its matches is contained
        # within a longer matched phrase belonging to another metric.
        if all(any(
            term != other
            and re.search(rf"(?<!\w){re.escape(term)}(?!\w)", other)
            for other in other_terms
        )
               for term in terms):
            continue
        selected.append(metric)
    return tuple(selected) or _METRICS


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
    concept_units = tuple(dict.fromkeys((*concept_units, _LATEST_PERIOD_ANCHOR)))
    records = get_company_fact_records_for_concept_units(
        cik, concept_units=concept_units,
        user_agent=getattr(settings, "sec_user_agent", "") or "",
    )
    anchor_ends = [
        record.end for record in records
        if record.concept == _LATEST_PERIOD_ANCHOR[0]
        and record.unit == _LATEST_PERIOD_ANCHOR[1]
        and record.start is None
    ]
    latest_issuer_end = max(anchor_ends) if anchor_ends else None
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
        if item is not None and latest_issuer_end and item.reporting_period_end:
            age = (
                date.fromisoformat(latest_issuer_end)
                - date.fromisoformat(item.reporting_period_end)
            ).days
            if age > _MAX_STALENESS_DAYS:
                item = None
        if item is not None:
            evidence.append(item)
    if re.search(r"(?<!\w)(?:free cash flow|fcf)(?!\w)", (question or "").lower()):
        _attach_free_cash_flow_calculations(evidence)
    return evidence
