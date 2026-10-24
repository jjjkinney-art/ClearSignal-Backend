"""Synthetic issuers and segment names; no live source or model calls."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from app.services import segment_revenue_policy as service
from app.services.public_document_ingestion import PublicDocument
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from app.schemas import InvestmentThesis
from app.integrity.provenance import ClaimDocumentReference
from test_financial_thesis_foundation import pair

CONTRACT = ("The Company's contracts in the Clinical Devices segment are primarily with the National Health Agency (NHA) and NHA prime contractors. "
    "As a consequence, this segment's business essentially depends on the product needs and governmental funding of the NHA. "
    "Substantially all of the work performed by the Clinical Devices segment directly or indirectly for the NHA is performed on a fixed-price basis. "
    "Under fixed-price contracts, the price paid to the contractor is awarded based on competition or negotiation at the outset of the contract and therefore, "
    "with the exception of limited escalation provisions on specific materials, is generally not subject to any adjustments reflecting the actual costs incurred by the contractor.")
RECOGNITION = ('For the Water Systems and Process Controls segments, revenue is generally recognized as the completed, ordered product is shipped to the customer from the Company’s warehouses. '
    'For the situations in which revenue should be recognized when product is received by the customer, the Company adjusts revenue accordingly. '
    'For the Clinical Devices segment, revenue is primarily recognized when the customer has legal title and formally documents that it has accepted the products. '
    'There are also certain termination clauses in Clinical Devices segment contracts that may give rise to an over-time pattern of recognition of revenue in the absence of alternative use of the product.')


def text():
    return (service.NOTES + ' ' + service.POLICIES + ' ( 1 ) REVENUES: Accounting policy. '
            + CONTRACT + ' ' + RECOGNITION + ' The timing of revenue recognition, billings, and cash collections differs. ( 2 ) ADVERTISING:')


def document(source=None):
    source = source or text()
    url='https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/company.htm'
    return PublicDocument(requested_url=url,final_url=url,content_type='text/html',
        content_hash=hashlib.sha256(source.encode()).hexdigest(),byte_count=len(source.encode()),
        title='Synthetic filing',text=source,sections=(),pages=(),links=(),extraction_method='html',
        text_ready=True,accessed_at='2026-10-24',publisher='SEC EDGAR',published_at='2026-03-13',
        document_type='10-K',source_type='regulatory_filing',source_tier='primary')


def items(source=None):
    return service.extract_segment_revenue_policies(document(source),ticker='ZQXB',cik='1234567')


def test_complete_named_policies_preserve_exceptions_without_performance_inference():
    values=items()
    assert len(values)==2
    for item in values:
        v=service.bound_segment_revenue_policy(item,ticker='ZQXB',cik='1234567')
        assert v and v['quote'] in (CONTRACT,RECOGNITION)
        assert v['policy_context']['scope']=='named_segments'
        assert v['policy_context']['realized_performance_established'] is False
        assert v['policy_context']['future_revenue_established'] is False
        assert v['quote'] in item.summary
    assert values[0].revenue_policy_disclosures[0]['policy_context']['segments']==['Clinical Devices']
    assert values[1].revenue_policy_disclosures[0]['policy_context']['shipment_segments']==['Water Systems','Process Controls']


@pytest.mark.parametrize('before,after',[
    ('with the exception of limited escalation provisions on specific materials, ',''),
    ('generally not subject','always subject'),
    ('directly or indirectly for the NHA','directly or indirectly for the OTHER'),
    ('(NHA)','(OTHER)'),
    ('The Company\'s contracts','Its contracts'),
    ('the National Health Agency (NHA) and NHA prime contractors','the NHA'),
])
def test_partial_or_ambiguous_contract_cannot_pass(before,after):
    assert not any(i.revenue_policy_disclosures[0]['policy_context']['role']=='contract_terms'
                   for i in items(text().replace(before,after)))


@pytest.mark.parametrize('before,after',[
    ('For the situations in which revenue should be recognized when product is received by the customer, the Company adjusts revenue accordingly. ',''),
    ('There are also certain termination clauses in Clinical Devices segment contracts that may give rise to an over-time pattern of recognition of revenue in the absence of alternative use of the product. ',''),
    ('in Clinical Devices segment contracts','in Other Devices segment contracts'),
    ('Water Systems and Process Controls','Water Systems and Water Systems'),
    ('primarily recognized','always recognized'),
    ('The timing of revenue recognition,','There is no timing paragraph,'),
])
def test_recognition_exceptions_and_segment_identity_must_survive(before,after):
    assert not any(i.revenue_policy_disclosures[0]['policy_context']['role']=='recognition_timing'
                   for i in items(text().replace(before,after)))


@pytest.mark.parametrize('mutation',[
    lambda s:s.replace(service.NOTES,'Other notes'),
    lambda s:s.replace(service.POLICIES,'B. OTHER POLICIES:'),
    lambda s:s.replace('( 2 ) ADVERTISING:','( 3 ) ADVERTISING:'),
    lambda s:s.replace('( 2 ) ADVERTISING:',''),
    lambda s:s+' ( 3 ) REVENUES: duplicate ( 4 ) OTHER:',
    lambda s:s.replace(CONTRACT,CONTRACT+' However, another exception applies.'),
])
def test_unsupported_windows_do_not_authorize_contract(mutation):
    assert not any(i.revenue_policy_disclosures[0]['policy_context']['role']=='contract_terms'
                   for i in items(mutation(text())))


@pytest.mark.parametrize('field',['quote','offset','hash','scope','segment','exception','summary','ticker','url','date','stale','form','proof_bool'])
def test_final_binder_reconstructs_proof_and_all_displayed_context(field):
    item=deepcopy(items()[1]);v=item.revenue_policy_disclosures[0]
    if field=='quote': v['quote']='Revenue is cash.'
    elif field=='offset': v['start_offset']+=1
    elif field=='hash': v['policy_source_proof']['text_sha256']='0'*64
    elif field=='scope':v['policy_context']['scope']='issuer'
    elif field=='segment':v['policy_context']['acceptance_segment']='Other'
    elif field=='exception':v['policy_context']['over_time_termination_exception_preserved']=False
    elif field=='summary':item.summary='A durable advantage.'
    elif field=='ticker':v['ticker']='OTHER'
    elif field=='url':item.url='https://example.com/company.htm'
    elif field=='date':item.timestamp='2099-01-01'
    elif field=='stale':item.freshness_status='stale'
    elif field=='form':item.document_type='10-Q'
    elif field=='proof_bool':v['policy_source_proof']['start_offset']=True
    assert service.bound_segment_revenue_policy(item,ticker='ZQXB',cik='1234567') is None


def test_final_gate_keeps_scope_citations_gaps_and_complete_policy_once(monkeypatch):
    monkeypatch.setattr('app.services.providers.sec_provider._load_ticker_cik_map',lambda:{'ZQXB':'1234567'})
    admitted,refs,_=admit_evidence(pair(ticker='ZQXB',cik='1234567')+items(),evaluated_at='2026-10-24')
    thesis=InvestmentThesis(ticker='ZQXB',company_name='Synthetic issuer')
    result=apply_source_answer_gate(thesis,'What is the investment thesis for ZQXB? Cite material claims.',admitted,references=refs)
    policies=[c for c in result['claims'] if c['claim_kind']==service.KIND]
    assert len(policies)==2 and result['status']=='partial'
    for c in policies:
        assert thesis.direct_answer.count(c['claim'])==1
        assert c['document_ref']['quote'] in thesis.direct_answer
        assert f"[{c['reference_id']}]" in thesis.direct_answer
    assert result['business_context_coverage']['complete_business_model'] is False
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert thesis.confidence_score==0


def test_scoped_quote_cap_does_not_weaken_ordinary_business_caps():
    ref=items()[0].revenue_policy_disclosures[0]['document_ref']
    assert len(ref['quote'])>300 and ClaimDocumentReference(**ref).quote==CONTRACT
    with pytest.raises(ValueError,match='300'):
        ClaimDocumentReference(**{**ref,'section':'Item 1. Business'})


def test_ordinary_disclosure_retrieval_uses_existing_document_fetch(monkeypatch):
    from app.services import thesis_disclosures as disclosures
    doc=document();calls=[]
    monkeypatch.setattr(disclosures.sec_provider,'_load_ticker_cik_map',lambda:{'ZQXB':'1234567'})
    monkeypatch.setattr(disclosures.sec_provider,'fetch_recent_filings',lambda *a,**kw:[
        SimpleNamespace(url=doc.final_url,timestamp=doc.published_at,document_type='10-K')])
    def saved(url,**kwargs):
        calls.append((url,kwargs));return doc
    monkeypatch.setattr(disclosures,'fetch_public_document',saved)
    result=disclosures.fetch_thesis_disclosures('ZQXB',question='What is the investment thesis for ZQXB?')
    assert len(calls)==1 and calls[0][0]==doc.final_url
    assert sum(bool(i.revenue_policy_disclosures) for i in result)==2
