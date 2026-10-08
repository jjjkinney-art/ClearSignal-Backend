"""Reviewed SEC table and dated cover binding, including live budget integration."""
from dataclasses import replace
from datetime import date
import socket

import pytest
import requests
from app.schemas import RetrievedEvidence
from app.services import issuer_release_evidence as releases
from app.services import live_issuer_kpi_service as live
from app.services.public_document_ingestion import fetch_public_document
TITLE = 'Tesla Third Quarter 2026 Production, Deliveries & Deployments'


class Response:
    status_code = 200
    headers = {'Content-Type': 'text/html'}
    encoding = 'utf-8'

    def __init__(self, text):
        self.body = text.encode()

    def iter_content(self, chunk_size):
        yield self.body

    def raise_for_status(self):
        pass

    def close(self):
        pass


BASE = 'https://www.sec.gov/Archives/edgar/data/1318605/000162828026064366/'
COVER = BASE + 'tsla-20261002.htm'
EXHIBIT = BASE + 'exhibit991111111.htm'
STATEMENT = ('On October 2, 2026, Tesla, Inc. published the press release which is '
             'attached hereto as Exhibit 99.1 and is incorporated herein by reference.')


def exhibit_html():
    # Reconstructed from the independently inspected EDGAR layout, including
    # its exact empty spacer cells, not the issuer-site four-column layout.
    rows = [('',) * 15,
            ('', 'Production', 'Deliveries', 'Subject to operating lease accounting', ''),
            ('Model 3/Y', '457,387', '478,237', '1%', ''),
            ('Other Models', '7,004', '8,295', '4%', ''),
            ('Total', '464,391', '486,532', '1%', ''), ('',) * 5, ('',) * 5]
    grid = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows)
    return f'<p>Exhibit 99.1</p><p>{TITLE}</p><p>Q3 2026</p><table>{grid}</table>'


@pytest.fixture
def documents(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    cover_html = f'<p>Tesla, Inc. TSLA</p><p>{STATEMENT}</p><a href="{EXHIBIT}">Press release of Tesla, Inc., dated October 2, 2026</a>'
    monkeypatch.setattr(requests, 'get', lambda url, **k: Response(
        cover_html if url == COVER else exhibit_html()))
    kwargs = dict(publisher='SEC EDGAR', published_at='2026-10-02',
                  source_type='regulatory_filing', source_tier='primary')
    return (fetch_public_document(COVER, document_type='8-K', **kwargs),
            fetch_public_document(EXHIBIT, document_type='press_release', **kwargs))


def extract(cover, doc):
    return releases.extract_sec_delivery_release(doc, cover=cover, ticker='TSLA',
        question='vehicle deliveries and vehicle production', evaluated_on=date(2026, 10, 8))


def test_exact_values_publication_and_cover_provenance(documents):
    cover, doc = documents
    items = extract(cover, doc)
    assert [i.verified_claims[0]['raw_value'] for i in items] == [486532, 464391]
    for item in items:
        claim = item.verified_claims[0]
        assert item.timestamp == '2026-10-02'
        assert item.reporting_period_end == '2026-09-30'
        assert item.source == 'SEC EDGAR'
        assert item.source_type == 'regulatory_filing'
        assert item.url == EXHIBIT
        assert claim['document_ref']['quote'] == 'Total 464,391 486,532 1%'
        assert claim['document_ref']['content_hash'] == doc.content_hash
        assert claim['table_columns'][2] == 'Deliveries'
        assert claim['publication_binding']['cover_content_hash'] == cover.content_hash
        assert claim['publication_binding']['quote'] == STATEMENT


@pytest.mark.parametrize('target,field,value', [
    ('cover', 'links', ()), ('cover', 'document_type', '10-Q'),
    ('cover', 'text', 'Tesla TSLA On October 2, 2026'),
    ('cover', 'published_at', '2026-09-30'),
    ('cover', 'final_url', COVER.replace('1318605', '1234567')),
    ('cover', 'requested_url', COVER.replace('064366', '064367')),
    ('doc', 'final_url', EXHIBIT.replace('064366', '064367')),
    ('doc', 'requested_url', EXHIBIT.replace('www.sec.gov', 'www.sec.gov.evil.test')),
    ('doc', 'publisher', 'Other'), ('doc', 'source_tier', 'unverified'),
    ('doc', 'content_hash', 'bad'), ('doc', 'published_at', '2026-10-03'),
])
def test_rejects_missing_relationship_foreign_source_or_wrong_date(documents,target,field,value):
    cover, doc = documents
    if target == 'cover': cover = replace(cover, **{field:value})
    else: doc = replace(doc, **{field:value})
    assert extract(cover, doc) == []


@pytest.mark.parametrize('mutation', [
    lambda d: replace(d, tables=d.tables+d.tables),
    lambda d: replace(d, tables=(replace(d.tables[0], context='Q2 2026'),)),
    lambda d: replace(d, text=d.text.replace('486,532','486,533')),
    lambda d: replace(d, tables=(replace(d.tables[0], rows=d.tables[0].rows[1:]),)),
    lambda d: replace(d, tables=(replace(d.tables[0], rows=(d.tables[0].rows[0],
        *tuple(tuple(reversed(r)) for r in d.tables[0].rows[1:5]), *d.tables[0].rows[5:])),)),
])
def test_ambiguous_hidden_or_shifted_tables_fail_closed(documents,mutation):
    cover, doc = documents
    assert extract(cover, mutation(doc)) == []


def test_wrong_issuer_future_or_unsupported_question(documents):
    cover, doc = documents
    for kwargs in ({'ticker':'F','question':'deliveries'},
                   {'ticker':'TSLA','question':'profitability'},
                   {'ticker':'TSLA','question':'deliveries','evaluated_on':date(2026,10,1)}):
        assert releases.extract_sec_delivery_release(doc, cover=cover, **kwargs) == []


def test_live_sec_route_uses_existing_two_document_budget(documents,monkeypatch):
    cover, doc = documents
    monkeypatch.setattr(live.sec_provider, 'fetch_recent_filings', lambda *a,**k: [
        RetrievedEvidence(title='Tesla 8-K',summary='Filed.',source='SEC EDGAR',timestamp='2026-10-02',
                          url=COVER,document_type='8-K')])
    calls=[]
    def fetch(url, **kwargs):
        calls.append(url)
        return cover if url == COVER else doc
    monkeypatch.setattr(live,'fetch_public_document',fetch)
    items=live.fetch_live_issuer_kpi_evidence('TSLA',question='vehicle deliveries and vehicle production')
    assert calls == [COVER,EXHIBIT]
    assert [i.verified_claims[0]['raw_value'] for i in items] == [486532,464391]
    calls.clear()
    assert live.fetch_live_issuer_kpi_evidence('TSLA',question='deliveries',max_documents=1) == []
    assert calls == [COVER]


def test_sec_release_enters_admission_and_keeps_actual_publication_boundary(documents):
    from types import SimpleNamespace
    from app.services.evidence_references import admit_evidence
    from app.services.thesis_impact_comparison import evaluate_selected_thesis_impact
    cover, doc = documents
    items, _, _ = admit_evidence(extract(cover, doc), evaluated_at="2026-10-08T00:00:00Z")
    assert len(items) == 2
    context = {'applied':True, 'ticker':'TSLA', 'created_at':'2026-09-26T01:12:20Z',
               'artifact':{'thesis':{'direct_answer':'Vehicle deliveries are a confirmation metric for Tesla.'}}}
    thesis = SimpleNamespace(direct_answer='More data is needed.',conclusion='More data is needed.',
                             thesis_trend='stable',what_changed=[],change_drivers=[])
    audit = evaluate_selected_thesis_impact(thesis=thesis,context=context,evidence=items)
    assert audit['evidence_gate']['status'] == 'ready'
    assert audit['status'] != 'verified_change'  # Retrieval is not semantic proof.
    context['created_at'] = '2026-10-03T00:00:00Z'
    audit = evaluate_selected_thesis_impact(thesis=thesis,context=context,evidence=items)
    assert audit['evidence_gate']['status'] != 'ready'
