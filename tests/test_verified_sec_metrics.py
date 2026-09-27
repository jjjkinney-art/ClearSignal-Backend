from dataclasses import replace

from app.integrity.sec_metric_evidence import comparable_metric_evidence
from app.providers.sec_client import SecFactRecord
from app.services import verified_sec_metric_service as service


def _record(*, concept="Revenues", value=100, start="2024-01-01",
            end="2024-03-31", filed="2024-05-01",
            accession="0000320193-24-000001", cik="320193"):
    return SecFactRecord(
        cik=cik, taxonomy="us-gaap", concept=concept, label=concept,
        unit="USD", value=value, start=start, end=end, filed=filed,
        form="10-Q", accession=accession,
        filing_url=("https://www.sec.gov/Archives/edgar/data/320193/"
                    f"{accession.replace('-', '')}/{accession}-index.htm"),
    )


def test_builds_claim_level_yoy_evidence_bound_to_current_filing():
    prior = _record()
    current = _record(value=112, start="2025-01-01", end="2025-03-31",
                      filed="2025-05-01", accession="0000320193-25-000001")
    item = comparable_metric_evidence(
        [prior, current], ticker="AAPL", expected_cik="0000320193",
        concepts=("Revenues",), metric_name="revenue",
    )
    assert item is not None
    assert "increased 12.0%" in item.summary
    assert "to $112" in item.summary
    assert "from $100" in item.summary
    assert "period ended 2025-03-31" in item.summary
    assert item.url == current.filing_url
    assert item.source == "SEC EDGAR — structured XBRL fact"


def test_rejects_wrong_entity_missing_comparable_and_ambiguous_concepts():
    prior = _record()
    current = _record(value=112, start="2025-01-01", end="2025-03-31",
                      filed="2025-05-01", accession="0000320193-25-000001")
    args = dict(
        ticker="AAPL", expected_cik="320193",
        concepts=("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        metric_name="revenue",
    )
    assert comparable_metric_evidence([current], **args) is None
    assert comparable_metric_evidence([prior, replace(current, cik="1318605")], **args) is None
    alternate = replace(current, concept="RevenueFromContractWithCustomerExcludingAssessedTax")
    assert comparable_metric_evidence([prior, current, alternate], **args) is None


def test_service_fetches_once_and_returns_supported_metrics(monkeypatch):
    prior_revenue = _record()
    current_revenue = _record(value=110, start="2025-01-01", end="2025-03-31",
                              filed="2025-05-01", accession="0000320193-25-000001")
    prior_cash = replace(prior_revenue, concept="NetCashProvidedByUsedInOperatingActivities")
    current_cash = replace(current_revenue, concept=prior_cash.concept, value=120)
    calls = []
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"AAPL": "0000320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concepts",
        lambda *args, **kwargs: calls.append((args, kwargs)) or
        [prior_revenue, current_revenue, prior_cash, current_cash],
    )
    evidence = service.fetch_verified_metric_evidence("AAPL")
    assert len(calls) == 1
    assert [item.title.split(":")[0] for item in evidence] == [
        "AAPL revenue", "AAPL operating cash flow"]
    assert service.fetch_verified_metric_evidence("AAPL/../") == []
