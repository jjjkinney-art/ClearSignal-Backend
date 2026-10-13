"""Unsupported unselected filenames cannot authorize paths or poison metadata."""
import json
import pytest
from tests.test_pilot_live import boundary, install_protocol
from validation.capture_budget import BudgetError
from validation.pilot_fixtures import sec_fixture


@pytest.mark.parametrize('document', ['', None, 'annual.HTM', 'annual.pdf', 'annual.xml',
                                      '../annual.htm', '%2e%2e/annual.htm',
                                      'https://other.invalid/annual.htm', 'annual.htm?x=1'])
def test_unselected_unsupported_document_excluded_without_poisoning_valid_filing(boundary, monkeypatch, document):
    identity = boundary.case['identity']
    _, raw = sec_fixture('sec/submissions', identity, boundary.identities)
    data = json.loads(raw)
    recent = data['filings']['recent']
    good = recent['primaryDocument'][0]
    accession = recent['accessionNumber'][0]
    recent['form'].append('6-K')
    recent['accessionNumber'].append('0000950170-25-000001')
    recent['primaryDocument'].append(document)
    writes = install_protocol(monkeypatch, boundary, data)
    _, returned = boundary.sec_exchange('GET', f'https://data.sec.gov/submissions/CIK{identity["cik"]}.json', None)
    assert json.loads(returned) == data  # No normalization, deletion, or invented URL.
    expected = f'https://www.sec.gov/Archives/edgar/data/{int(identity["cik"])}/{accession.replace("-", "")}/{good}'
    assert boundary.sec_document_urls() == {expected}
    assert boundary.events[0]['sec_document_exclusions'] == 1
    assert boundary.ledger.summary()['halted'] is None
    assert boundary.ledger.summary()['unresolved_attempts'] == 0
    # An eventual selection of the unsupported entry still cannot dispatch it.
    denied = f'https://www.sec.gov/Archives/edgar/data/{int(identity["cik"])}/000095017025000001/{document}'
    before = len(writes)
    with pytest.raises(BudgetError): boundary.sec_exchange('GET', denied, None)
    assert len(writes) == before
    assert boundary.ledger.summary()['attempts'] == 1


def test_no_fetchable_documents_returns_empty_allowlist(boundary, monkeypatch):
    identity = boundary.case['identity']
    _, raw = sec_fixture('sec/submissions', identity, boundary.identities)
    data = json.loads(raw)
    data['filings']['recent']['primaryDocument'] = ['']
    install_protocol(monkeypatch, boundary, data)
    boundary.sec_exchange('GET', f'https://data.sec.gov/submissions/CIK{identity["cik"]}.json', None)
    assert boundary.sec_document_urls() == set()
    assert boundary.events[0]['sec_document_exclusions'] == 1
    assert not boundary.ledger.summary()['halted']


def test_application_selects_latest_annual_before_unrelated_bad_document(boundary, monkeypatch):
    from app.services.providers import sec_provider
    identity = boundary.case['identity']
    _, raw = sec_fixture('sec/submissions', identity, boundary.identities)
    data = json.loads(raw)
    recent = data['filings']['recent']
    recent.update(form=['20-F', '6-K'], filingDate=['2026-02-01', '2025-12-01'],
                  reportDate=['2025-12-31', '2025-11-01'],
                  accessionNumber=['0000950170-26-012345', '0000950170-25-000001'],
                  primaryDocument=['annual.htm', ''], items=['', ''])
    install_protocol(monkeypatch, boundary, data)
    url = f'https://data.sec.gov/submissions/CIK{identity["cik"]}.json'
    _, content = boundary.sec_exchange('GET', url, None)
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {identity['ticker']: identity['cik']})
    monkeypatch.setattr(sec_provider, '_fetch_json', lambda *a, **k: json.loads(content))
    evidence = sec_provider._fetch_by_cik(identity['ticker'], ['20-F'], 1, 2, as_of='2026-10-13')
    assert len(evidence) == 1
    assert evidence[0].url in boundary.sec_document_urls()
    assert evidence[0].url.endswith('/annual.htm')
