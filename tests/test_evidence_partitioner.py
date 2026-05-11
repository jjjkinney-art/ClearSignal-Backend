"""Tests for app.services.evidence_partitioner — EvidencePartition and partition_evidence."""
from __future__ import annotations

import pytest

from app.schemas import CompanyContext, RetrievedEvidence
from app.services.evidence_partitioner import EvidencePartition, partition_evidence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ev(title: str, source: str = "FMP", summary: str = "Test summary", score: float = 0.9) -> RetrievedEvidence:
    return RetrievedEvidence(
        title=title,
        source=source,
        summary=summary,
        timestamp="2024-11-01",
        relevance_score=score,
    )


def _company(ticker: str = "AAPL", name: str = "Apple Inc.") -> CompanyContext:
    return CompanyContext(ticker=ticker, company_name=name, sector="Technology")


# ---------------------------------------------------------------------------
# TestEvidencePartitionDataclass
# ---------------------------------------------------------------------------

class TestEvidencePartitionDataclass:
    def test_default_all_empty(self):
        ep = EvidencePartition()
        assert ep.valuation == []
        assert ep.macro == []
        assert ep.risk == []
        assert ep.market == []
        assert ep.quality == []

    def test_all_unique_empty_when_no_items(self):
        assert EvidencePartition().all_unique == []

    def test_total_items_zero_when_empty(self):
        assert EvidencePartition().total_items() == 0

    def test_total_items_counts_across_pools(self):
        items_val = [_ev(f"Income statement {i}") for i in range(2)]
        items_mac = [_ev(f"Treasury yield {i}", source="FRED") for i in range(3)]
        items_risk = [_ev("Annual filing")]
        ep = EvidencePartition(
            valuation=items_val,
            macro=items_mac,
            risk=items_risk,
            market=[],
            quality=[],
        )
        assert ep.total_items() == 6

    def test_all_unique_deduplicates(self):
        shared = _ev("Shared evidence item")
        ep = EvidencePartition(valuation=[shared], macro=[shared])
        unique = ep.all_unique
        assert len(unique) == 1
        assert unique[0] is shared


# ---------------------------------------------------------------------------
# TestPartitionEvidence_MacroRouting
# ---------------------------------------------------------------------------

class TestPartitionEvidence_MacroRouting:
    def test_fred_source_routes_to_macro(self):
        ev = _ev("Federal Funds Rate: 5.25%", source="FRED (Federal Reserve)")
        partition = partition_evidence([ev], _company())
        assert ev in partition.macro

    def test_treasury_keyword_routes_to_macro(self):
        ev = _ev("10-Year Treasury Yield: 4.3%", source="FedReserve")
        partition = partition_evidence([ev], _company())
        assert ev in partition.macro

    def test_cpi_keyword_routes_to_macro(self):
        ev = _ev("CPI inflation: 3.2%", source="BLS")
        partition = partition_evidence([ev], _company())
        assert ev in partition.macro

    def test_fred_not_in_valuation_pool(self):
        # Pure FRED series without any company name in title should stay in macro only
        ev = _ev("T10Y2Y Yield Curve Spread: -0.45%", source="FRED")
        partition = partition_evidence([ev], _company())
        assert ev not in partition.valuation


# ---------------------------------------------------------------------------
# TestPartitionEvidence_ValuationRouting
# ---------------------------------------------------------------------------

class TestPartitionEvidence_ValuationRouting:
    def test_income_statement_routes_to_valuation(self):
        ev = _ev("Q3 Earnings Report: EPS beat", source="SomeSource")
        partition = partition_evidence([ev], _company())
        assert ev in partition.valuation

    def test_fmp_source_routes_to_valuation(self):
        ev = _ev("Stock price change +3.2%", source="FMP")
        partition = partition_evidence([ev], _company())
        assert ev in partition.valuation

    def test_revenue_keyword_routes_to_valuation(self):
        ev = _ev("Annual revenue grew 15%", source="Morningstar")
        partition = partition_evidence([ev], _company())
        assert ev in partition.valuation


# ---------------------------------------------------------------------------
# TestPartitionEvidence_RiskRouting
# ---------------------------------------------------------------------------

class TestPartitionEvidence_RiskRouting:
    def test_sec_edgar_source_routes_to_risk(self):
        ev = _ev("10-K Annual Report Filed", source="SEC EDGAR")
        partition = partition_evidence([ev], _company())
        assert ev in partition.risk

    def test_10k_keyword_routes_to_risk(self):
        ev = _ev("Apple 10-K Annual Filing", source="SEC EDGAR")
        partition = partition_evidence([ev], _company())
        assert ev in partition.risk

    def test_debt_keyword_routes_to_risk(self):
        ev = _ev("Corporate debt levels high", source="Bloomberg")
        partition = partition_evidence([ev], _company())
        assert ev in partition.risk


# ---------------------------------------------------------------------------
# TestPartitionEvidence_MarketRouting
# ---------------------------------------------------------------------------

class TestPartitionEvidence_MarketRouting:
    def test_newsapi_source_routes_to_market(self):
        ev = _ev("Breaking: Fed holds rates steady", source="NewsAPI/Bloomberg")
        partition = partition_evidence([ev], _company())
        assert ev in partition.market

    def test_analyst_upgrade_routes_to_market(self):
        ev = _ev("Analyst upgrades Apple to Buy", source="Reuters")
        partition = partition_evidence([ev], _company())
        assert ev in partition.market

    def test_guidance_keyword_routes_to_market(self):
        ev = _ev("Company raises guidance for Q4", source="CNBC")
        partition = partition_evidence([ev], _company())
        assert ev in partition.market


# ---------------------------------------------------------------------------
# TestPartitionEvidence_CompanyBroadcast
# ---------------------------------------------------------------------------

class TestPartitionEvidence_CompanyBroadcast:
    def test_company_name_in_title_goes_to_all_pools(self):
        ev = _ev("Apple Inc. reports record quarterly revenue", source="FRED")
        company = _company(ticker="AAPL", name="Apple Inc.")
        partition = partition_evidence([ev], company)
        assert ev in partition.valuation
        assert ev in partition.macro
        assert ev in partition.risk
        assert ev in partition.market
        assert ev in partition.quality

    def test_company_ticker_in_title_goes_to_all_pools(self):
        ev = _ev("AAPL stock rallies 5% on earnings beat", source="NewsAPI")
        company = _company(ticker="AAPL", name="Apple Inc.")
        partition = partition_evidence([ev], company)
        assert ev in partition.valuation
        assert ev in partition.macro
        assert ev in partition.risk
        assert ev in partition.market
        assert ev in partition.quality

    def test_all_unique_counts_broadcasted_item_once(self):
        ev = _ev("Apple Inc. raises guidance", source="FMP")
        company = _company(ticker="AAPL", name="Apple Inc.")
        partition = partition_evidence([ev], company)
        # Item is in all 5 pools but all_unique should count it once
        assert len(partition.all_unique) == 1

    def test_pure_macro_without_company_name_stays_in_macro_only(self):
        ev = _ev("10-Year Treasury Yield: 4.5%", source="FRED")
        company = _company(ticker="AAPL", name="Apple Inc.")
        partition = partition_evidence([ev], company)
        assert ev in partition.macro
        assert ev not in partition.valuation


# ---------------------------------------------------------------------------
# TestPartitionEvidence_EdgeCases
# ---------------------------------------------------------------------------

class TestPartitionEvidence_EdgeCases:
    def test_empty_evidence_returns_empty_partition(self):
        partition = partition_evidence([], _company())
        assert partition.valuation == []
        assert partition.macro == []
        assert partition.risk == []
        assert partition.market == []
        assert partition.quality == []

    def test_single_item_routes_somewhere(self):
        ev = _ev("Q3 Earnings Report: EPS beat", source="FMP")
        partition = partition_evidence([ev], _company())
        total = partition.total_items()
        assert total >= 1
