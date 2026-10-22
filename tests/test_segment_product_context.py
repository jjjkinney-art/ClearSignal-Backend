"""Complete synthetic lists; segment scope must not become issuer-wide coverage."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.integrity.provenance import ClaimDocumentReference
from app.schemas import InvestmentThesis
from app.services import segment_product_context as products, thesis_disclosures as disclosures
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from test_thesis_disclosures import document
from test_financial_thesis_foundation import pair

QUOTE = ('1. Clinical Devices Segment Medical instruments sold by the segment include '
         'laboratory analyzers; temperature monitors; fluid sensors; pressure sensors; '
         'sterile containers; testing chambers; optical readers; storage racks; sample trays; '
         'microscope accessories; reusable holders; instrument cases; timing devices; '
         'replacement seals; and measuring instruments.')
CHANNELS = 'Products are sold directly to retailers and also through independent distributors.'


def fixture(quote=QUOTE):
    return document(f'Item 1. Business {CHANNELS} {quote} Item 1A. Risk Factors '
                    'Supply disruption could affect operations. Item 1B. Unresolved Staff Comments')


def evidence(quote=QUOTE):
    return products.extract_segment_products(fixture(quote), ticker='AAPL', cik='320193')[0]


@pytest.mark.parametrize('label', ['Clinical Devices', 'Water/Filtration', 'Consumer & Industrial', 'Aerospace-Components'])
@pytest.mark.parametrize('verb', ['sold', 'manufactured', 'offered'])
def test_complete_long_quote_bound_to_unseen_segment_heading(label, verb):
    quote=QUOTE.replace('Clinical Devices',label).replace('sold',verb)
    doc=fixture(quote);item=evidence(quote)
    value=products.bound_segment_products(item,ticker='AAPL',cik='320193')
    assert value['quote']==quote and doc.text[value['start_offset']:value['end_offset']]==quote
    assert value['product_context']['scope']=={'kind':'named_segment','label':label}
    assert value['document_ref']['quote']==quote and len(quote)>300
    assert value['product_context']['revenue_inference_performed'] is False
    assert 'not a complete issuer business model' in item.summary


@pytest.mark.parametrize('before,after', [
    ('1. Clinical Devices Segment ','1. The Segment '),
    ('1. Clinical Devices Segment ','Clinical Devices Segment '),
    (' Segment ',' division '), ('sold by the segment','sold by our competitor'),
    ('sold by the segment','expected to be sold by the segment'),
    ('include ','include superior '), ('include ','include high-quality '),
    ('include ','include innovative '), ('include ','include reliable '),
    ('include ','include 20mm '), ('include ','include $100 '),
    ('include ','include workforce '), ('include ','include products which '),
    ('; and measuring instruments.','; and will improve our margins.'),
    ('; and measuring instruments.','; and are expected to expand.'),
])
def test_ambiguous_promotional_numeric_or_future_prose_withheld(before,after):
    assert products.extract_segment_products(fixture(QUOTE.replace(before,after)),ticker='AAPL',cik='320193')==[]


@pytest.mark.parametrize('change', ['label','list','heading','bool','start','end','quote','ref','hash','url','ticker','summary','stale','period'])
def test_final_binding_rejects_tampering(change):
    item=deepcopy(evidence());v=item.product_disclosures[0]
    if change=='label':v['product_context']['scope']['label']='Other'
    elif change=='list':v['product_context']['reported_product_list']='Other products'
    elif change=='heading':v['product_context']['heading']='Another heading'
    elif change=='bool':v['product_context']['revenue_inference_performed']=0
    elif change=='start':v['start_offset']=True
    elif change=='end':v['end_offset']+=1
    elif change=='quote':v['quote']+=' Buy now.'
    elif change=='ref':v['document_ref']['quote']='Buy now.'
    elif change=='hash':v['document_ref']['content_hash']='invalid'
    elif change=='url':v['document_ref']['url']='https://www.sec.gov/Archives/edgar/data/1/other.htm'
    elif change=='ticker':v['ticker']='OTHER'
    elif change=='summary':item.summary='Buy now.'
    elif change=='stale':item.freshness_status='stale'
    elif change=='period':item.reporting_period_end='2024-12-31'
    assert products.bound_segment_products(item,ticker='AAPL',cik='320193') is None


@pytest.mark.parametrize('changes', [
    {'document_type':'20-F'}, {'document_type':'10-Q'}, {'publisher':'Other'},
    {'source_tier':'secondary'}, {'extraction_method':'pdf'}, {'text_ready':False},
    {'published_at':'2099-01-01'}, {'published_at':'invalid'},
    {'final_url':'https://www.sec.gov/Archives/edgar/data/1/other.htm'},
])
def test_document_gates(changes):
    assert products.extract_segment_products(replace(fixture(),**changes),ticker='AAPL',cik='320193')==[]


def test_duplicate_missing_or_intervening_heading_and_full_quote_cap():
    assert products.extract_segment_products(fixture(QUOTE+' '+QUOTE),ticker='AAPL',cik='320193')==[]
    assert products.extract_segment_products(fixture('1. A different sentence. '+QUOTE.split('1. ')[1]),ticker='AAPL',cik='320193')==[]
    assert products.extract_segment_products(fixture(QUOTE.replace('laboratory analyzers','laboratory analyzers '*50)),ticker='AAPL',cik='320193')==[]
    doc=replace(fixture(),text=fixture().text.replace('Item 1A. Risk Factors','Unbounded risks'))
    assert products.extract_segment_products(doc,ticker='AAPL',cik='320193')==[]


def test_scoped_reference_cap_does_not_relax_ordinary_business_quotes():
    ref=evidence().product_disclosures[0]['document_ref']
    assert ClaimDocumentReference(**ref).quote==QUOTE
    with pytest.raises(ValueError,match='300'):
        ClaimDocumentReference(**{**ref,'section':'Item 1. Business'})


def test_normal_retrieval_and_answer_append_products_without_issuer_coverage(monkeypatch):
    monkeypatch.setattr(disclosures.sec_provider,'_load_ticker_cik_map',lambda:{'AAPL':'320193'})
    monkeypatch.setattr(disclosures.sec_provider,'fetch_recent_filings',lambda *a,**kw:[SimpleNamespace(url=fixture().final_url,timestamp=fixture().published_at,document_type='10-K')])
    calls=[]
    def saved(*a,**kw):calls.append(a);return fixture()
    monkeypatch.setattr(disclosures,'fetch_public_document',saved)
    items=disclosures.fetch_thesis_disclosures('AAPL',question='What is the investment thesis for AAPL?')
    assert len(calls)==1 and len(items[-1].product_disclosures)==1
    admitted,refs,_=admit_evidence(pair()+items,evaluated_at='2026-10-22')
    thesis=InvestmentThesis(ticker='AAPL',company_name='Invented issuer')
    result=apply_source_answer_gate(thesis,'What is the investment thesis for AAPL? Cite material claims.',admitted,references=refs)
    rows=[c for c in result['claims'] if c['claim_kind']=='issuer_segment_product_context']
    assert len(rows)==1 and rows[0]['product_context']['scope']['label']=='Clinical Devices'
    assert QUOTE in thesis.direct_answer and f"[{rows[0]['reference_id']}]" in thesis.direct_answer
    assert result['status']=='partial' and 'business model completeness' in result['unanswered_parts']
    assert result['business_context_coverage']['complete_business_model'] is False
