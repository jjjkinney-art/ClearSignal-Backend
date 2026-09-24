"""A structured SEC observation must retain its own filing identity."""

from app.providers import sec_client


def _companyfacts():
    return {
        "cik": 320193,
        "facts": {"us-gaap": {"Revenues": {
            "label": "Revenue", "units": {"USD": [
                {"val": 1000000, "start": "2025-01-01", "end": "2025-03-31",
                 "filed": "2025-05-01", "form": "10-Q", "accn": "0000320193-25-000001"},
                {"val": 1000000, "start": "2025-01-01", "end": "2025-03-31",
                 "filed": "2025-06-01", "form": "10-Q/A", "accn": "0000320193-25-000002"},
                {"val": 2000000, "end": "2025-06-30", "filed": "2025-07-01",
                 "form": "8-K", "accn": "0000320193-25-000003"},
                {"val": 5, "end": "2025-06-30", "filed": "2025-07-01",
                 "form": "10-Q", "accn": "../../unsafe-file"},
            ]},
        }}},
    }


def test_preserves_accession_period_and_amended_filing_separately():
    records = sec_client.parse_company_fact_records(_companyfacts(), concept="Revenues", unit="USD")
    assert len(records) == 2
    assert {r.accession for r in records} == {
        "0000320193-25-000001", "0000320193-25-000002"}
    assert records[0].start == "2025-01-01"
    assert records[0].end == "2025-03-31"
    assert records[0].filing_url == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019325000001/0000320193-25-000001-index.htm")
    assert records[1].filing_url != records[0].filing_url
    assert sec_client.parse_company_fact_records(_companyfacts(), concept="NetIncomeLoss", unit="USD") == []
    assert sec_client.parse_company_fact_records(_companyfacts(), concept="Revenues", unit="shares") == []


def test_fetch_refuses_mismatched_entity(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return _companyfacts()

    monkeypatch.setattr(sec_client.requests, "get", lambda *args, **kwargs: Response())
    assert sec_client.get_company_fact_records("999999", concept="Revenues", unit="USD") == []
    assert len(sec_client.get_company_fact_records("0000320193", concept="Revenues", unit="USD")) == 2
