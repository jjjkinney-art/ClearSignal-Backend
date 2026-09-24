"""A filing citation is attached only to an exact structured observation."""

from dataclasses import replace

import pytest

from app.integrity.provenance import Provenance, QuantitativeClaim
from app.integrity.sec_fact_binding import bind_sec_fact
from app.providers.sec_client import parse_company_fact_records


def _record():
    payload = {"cik": 320193, "facts": {"us-gaap": {"Revenues": {
        "label": "Revenue", "units": {"USD": [{
            "val": 1000000, "start": "2025-01-01", "end": "2025-03-31",
            "filed": "2025-05-01", "form": "10-Q", "accn": "0000320193-25-000001",
        }]},
    }}}}
    return parse_company_fact_records(payload, concept="Revenues", unit="USD")[0]


def _claim():
    return QuantitativeClaim(
        "$1,000,000", Provenance.REPORTED, raw_value=1000000, unit="USD",
        ticker="AAPL", metric="us-gaap:Revenues", as_of="2025-03-31",
        source="10-Q",
    )


def test_exact_record_binds_without_mutating_original_claim():
    claim, record = _claim(), _record()
    bound = bind_sec_fact(claim, record, expected_cik="0000320193", period_start="2025-01-01")
    assert claim.document_ref is None
    assert bound is not None
    assert bound.to_dict()["document_ref"] == {
        "reference_id": "sec:320193:0000320193-25-000001:us-gaap:Revenues",
        "title": "10-Q filed 2025-05-01 · Revenue",
        "provider": "SEC EDGAR",
        "url": record.filing_url,
        "published_at": "2025-05-01",
    }


@pytest.mark.parametrize("claim_changes,record_changes,cik,start", [
    ({"provenance": Provenance.ESTIMATED}, {}, "320193", "2025-01-01"),
    ({"raw_value": 1000001}, {}, "320193", "2025-01-01"),
    ({"value_text": "$9M"}, {}, "320193", "2025-01-01"),
    ({"unit": "shares"}, {}, "320193", "2025-01-01"),
    ({"as_of": "2025-06-30"}, {}, "320193", "2025-01-01"),
    ({"source": "10-K"}, {}, "320193", "2025-01-01"),
    ({"metric": "valuation"}, {}, "320193", "2025-01-01"),
    ({}, {"concept": "NetIncomeLoss"}, "320193", "2025-01-01"),
    ({}, {"filing_url": "https://www.sec.gov/Archives/edgar/data/1/other"}, "320193", "2025-01-01"),
    ({}, {"accession": "../../unsafe"}, "320193", "2025-01-01"),
    ({}, {"value": float("nan")}, "320193", "2025-01-01"),
    ({}, {}, "999999", "2025-01-01"),
    ({}, {}, "320193", None),
])
def test_mismatch_never_gets_document_reference(claim_changes, record_changes, cik, start):
    claim = replace(_claim(), **claim_changes)
    record = replace(_record(), **record_changes)
    assert bind_sec_fact(claim, record, expected_cik=cik, period_start=start) is None
    assert claim.document_ref is None
