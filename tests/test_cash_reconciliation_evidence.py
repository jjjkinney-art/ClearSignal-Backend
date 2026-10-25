from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from app.schemas import RetrievedEvidence, InvestmentThesis
from app.services.cash_reconciliation_evidence import CashSource, extract_cash_reconciliation, bound_cash_reconciliation, KIND
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate, _claim_text
from test_sec_cash_reconciliation import xml
from test_segment_revenue_policy import document
from test_financial_thesis_foundation import pair


def doc():
    source = xml()
    d = document(source)
    return replace(d, cash_reconciliation_source=CashSource(source.encode(), d.content_hash,
        '1234567', d.final_url, d.published_at, d.title))


def item():
    value, = extract_cash_reconciliation(doc(), ticker='ZQXB', cik='1234567')
    return value


def answer(value, monkeypatch):
    monkeypatch.setattr('app.services.providers.sec_provider._load_ticker_cik_map', lambda: {'ZQXB':'1234567'})
    admitted, refs, _ = admit_evidence(pair(ticker='ZQXB', cik='1234567') + [value], evaluated_at='2026-10-25')
    thesis = InvestmentThesis(ticker='ZQXB', company_name='Synthetic issuer')
    result = apply_source_answer_gate(thesis, 'What is the investment thesis for ZQXB? Cite material claims.', admitted, references=refs)
    return result, thesis


def test_final_gate_preserves_full_bridge_and_all_row_references(monkeypatch):
    value = item()
    result, thesis = answer(value, monkeypatch)
    row, = [r for r in result['claims'] if r['claim_kind'] == KIND]
    assert len(row['row_references']) == 4
    assert row['cash_reconciliation']['totals'][0]['operating_cash_flow'] == 75
    assert thesis.direct_answer.count(value.summary) == 1
    assert f"[{row['reference_id']}]" in thesis.direct_answer
    assert result['status'] == 'partial' and 'valuation and expected returns' in result['unanswered_parts']
    assert thesis.confidence_score == 0


@pytest.mark.parametrize('field', ['body', 'missing_handle', 'total', 'reference', 'summary', 'stale', 'url', 'period', 'currency', 'row_omission'])
def test_final_binder_rebuilds_from_private_original_bytes(field, monkeypatch):
    value = deepcopy(item())
    if field == 'body': value._cash_reconciliation_source = replace(value._cash_reconciliation_source, body=b'changed')
    elif field == 'missing_handle': value._cash_reconciliation_source = None
    elif field == 'total': value.cash_reconciliation_disclosures[0]['bridge']['totals'][0]['operating_cash_flow'] = 999
    elif field == 'reference': value.cash_reconciliation_disclosures[0]['row_references'][0]['document_ref']['quote'] = 'Changed'
    elif field == 'summary': value.summary = 'Operating strength is proven.'
    elif field == 'stale': value.freshness_status = 'stale'
    elif field == 'url': value.url = 'https://example.com/report.htm'
    elif field == 'period': value.reporting_period_start = '2025-04-01'
    elif field == 'currency': value.cash_reconciliation_disclosures[0]['bridge']['currency'] = 'EUR'
    elif field == 'row_omission': value.cash_reconciliation_disclosures[0]['bridge']['rows'].pop(1)
    assert bound_cash_reconciliation(value, ticker='ZQXB', cik='1234567') is None
    assert _claim_text(value) is None
    result, _ = answer(value, monkeypatch)
    assert not any(r['claim_kind'] == KIND for r in result['claims'])


def test_serialization_omits_raw_source_and_cannot_reauthorize_descriptors(monkeypatch):
    value = item()
    serialized = value.model_dump_json()
    assert '_cash_reconciliation_source' not in serialized and '<html' not in serialized
    clone = RetrievedEvidence.model_validate_json(serialized)
    assert clone._cash_reconciliation_source is None
    assert bound_cash_reconciliation(clone, ticker='ZQXB', cik='1234567') is None
    result, _ = answer(clone, monkeypatch)
    assert not any(r['claim_kind'] == KIND for r in result['claims'])
    payload = json.loads(serialized)
    payload['_cash_reconciliation_source'] = {'body':'caller bytes', 'cik':'1234567'}
    injected = RetrievedEvidence.model_validate(payload)
    assert injected._cash_reconciliation_source is None
    assert bound_cash_reconciliation(injected, ticker='ZQXB', cik='1234567') is None


def test_document_metadata_or_absent_handle_withhold():
    for changed in (replace(doc(), cash_reconciliation_source=None), replace(doc(), content_hash='0'*64),
                    replace(doc(), document_type='20-F'), replace(doc(), source_tier='unverified')):
        assert extract_cash_reconciliation(changed, ticker='ZQXB', cik='1234567') == []


def test_ordinary_ingestion_and_disclosure_fetch_use_one_existing_download(monkeypatch):
    from app.services import public_document_ingestion as ingest, thesis_disclosures as disclosures
    body = xml().encode()
    calls = []
    class Response:
        headers = {'Content-Type':'text/html'}
        encoding = 'utf-8'
        status_code = 200
        def raise_for_status(self): pass
        def iter_content(self, chunk_size): yield body
        def close(self): pass
    def get(url, **kwargs): calls.append(url); return Response()
    monkeypatch.setattr(ingest.requests, 'get', get)
    monkeypatch.setattr(ingest.socket, 'getaddrinfo', lambda *a,**kw:[(2,1,6,'',('93.184.216.34',443))])
    monkeypatch.setattr(disclosures.sec_provider, '_load_ticker_cik_map', lambda:{'ZQXB':'1234567'})
    monkeypatch.setattr(disclosures.sec_provider, 'fetch_recent_filings', lambda *a,**kw:[SimpleNamespace(
        url=doc().final_url, timestamp='2026-03-13', document_type='10-K')])
    items = disclosures.fetch_thesis_disclosures('ZQXB', question='What is the investment thesis for ZQXB?')
    cash = [v for v in items if v.cash_reconciliation_disclosures]
    assert len(calls) == 1 and len(cash) == 1
    assert bound_cash_reconciliation(cash[0], ticker='ZQXB', cik='1234567') is not None
