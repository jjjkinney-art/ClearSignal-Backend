"""Invented annual EPS facts exercise normal retrieval and source gate boundaries."""
from copy import deepcopy
from dataclasses import replace
import pytest
from app.providers.sec_client import SecFactRecord
from app.schemas import InvestmentThesis
from app.services import annual_eps_research as eps, verified_sec_metric_service as svc
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate, is_source_answer_request

TICKER, CIK = 'ZQXB', '1234567'

def rows(basis='basic',currency='USD',form='10-K',current=5):
    concept='EarningsPerShareBasic' if basis=='basic' else 'EarningsPerShareDiluted'
    result=[]
    for year,value in ((2024,4),(2025,current)):
        accession=f'0001234567-{str(year+1)[-2:]}-000001'
        result.append(SecFactRecord(CIK,'us-gaap',concept,'EPS',currency+'/shares',value,
            f'{year}-01-01',f'{year}-12-31',f'{year+1}-02-20',form,accession,
            f'https://www.sec.gov/Archives/edgar/data/{CIK}/{accession.replace("-", "")}/{accession}-index.htm'))
    result.append(replace(result[-1],concept='Assets',label='Assets',unit=currency,value=100,start=None))
    return result

@pytest.fixture
def sources(monkeypatch):
    from app.services.providers import sec_provider
    monkeypatch.setattr(svc,'_load_ticker_cik_map',lambda:{TICKER:CIK})
    monkeypatch.setattr(sec_provider,'_load_ticker_cik_map',lambda:{TICKER:CIK})
    data=rows();calls=[]
    def fetch(cik,**kw):
        calls.append((cik,kw));return deepcopy(data)
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',fetch)
    return data,calls

def question(basis='basic',currency=''):
    return f'What is the latest annual {currency} {basis} EPS for {TICKER}?'

def answer(material,q=None):
    items,refs=admit_evidence(material,evaluated_at='2026-10-20')[:2]
    thesis=InvestmentThesis(ticker=TICKER,company_name='Invented company')
    result=apply_source_answer_gate(thesis,q or question(),items,references=refs)
    return result,thesis,items,refs

@pytest.mark.parametrize('basis',['basic','diluted'])
@pytest.mark.parametrize('currency',['USD','EUR'])
@pytest.mark.parametrize('form',['10-K','20-F','20-F/A'])
def test_explicit_annual_share_basis_and_currency_use_normal_source_route(sources,basis,currency,form):
    data,calls=sources;data[:]=rows(basis,currency,form)
    q=question(basis)
    assert is_source_answer_request(q)
    items=svc.fetch_verified_metric_evidence(TICKER,question=q,as_of='2026-10-20')
    assert len(items)==1 and len(calls)==1
    assert items[0].verified_claims[0]['unit']==currency+'/shares'
    result,thesis,_,refs=answer(items,q)
    assert result['status']=='attributed' and not result['unanswered_parts']
    assert len(result['claims'])==1 and result['claims'][0]['reference_id']==refs[0]['id']
    assert basis+' EPS' in thesis.direct_answer and 'not current TTM or forward EPS' in thesis.direct_answer
    assert thesis.threshold_zones==[] and not thesis.decision_thresholds
    assert currency+'/shares'==thesis.quantitative_claims[0]['unit']

@pytest.mark.parametrize('requested,provided',[('basic','diluted'),('diluted','basic')])
def test_no_other_basis_fallback(sources,requested,provided):
    data,_=sources;data[:]=rows(provided)
    items=svc.fetch_verified_metric_evidence(TICKER,question=question(requested),as_of='2026-10-20')
    assert not items
    result,thesis,_,_=answer(items,question(requested))
    assert result['status']=='insufficient_claim_evidence' and result['unanswered_parts']==['annual '+requested+' EPS']

@pytest.mark.parametrize('mutation',[
    lambda r:[replace(x,accession='0001234567-26-000999') if x.concept=='Assets' else x for x in r],
    lambda r:[replace(x,unit='EUR') if x.concept=='Assets' else x for x in r],
    lambda r:[replace(x,form='20-F') if x.concept=='Assets' else x for x in r],
    lambda r:[replace(x,end='2026-03-31') if x.concept=='Assets' else x for x in r],
    lambda r:[x for x in r if x.concept!='Assets'],
    lambda r:[replace(x,filed='2026-11-01') for x in r],
    lambda r:[replace(x,cik='7654321') for x in r],
])
def test_annual_period_identity_and_same_filing_anchors_fail_closed(sources,mutation):
    data,_=sources;data[:]=mutation(rows())
    assert not svc.fetch_verified_metric_evidence(TICKER,question=question(),as_of='2026-10-20')

@pytest.mark.parametrize('currency',['EUR','USD EUR','GBP'])
def test_explicit_currency_never_converts_or_resolves_conflict(sources,currency):
    assert not svc.fetch_verified_metric_evidence(TICKER,question=question(currency=currency),as_of='2026-10-20')

def test_current_basic_and_stale_diluted_leave_diluted_slot_unanswered(sources):
    data,_=sources;data[:]=rows()+[replace(r,start='2011-01-01' if r.start else None,end='2011-12-31',filed='2012-02-20') for r in rows('diluted') if r.concept!='Assets']
    q=question('basic and diluted')
    items=svc.fetch_verified_metric_evidence(TICKER,question=q,as_of='2026-10-20')
    result,thesis,_,_=answer(items,q)
    assert result['status']=='partial' and result['unanswered_parts']==['annual diluted EPS']
    assert len(result['claims'])==1 and 'basic EPS' in thesis.direct_answer

@pytest.mark.parametrize('change',[
    lambda i,r:setattr(i,'summary','Invented EPS text cannot replace the source summary.'),
    lambda i,r:i.verified_claims[0].update(raw_value=900),
    lambda i,r:i.verified_claims[0].update(currency='EUR'),
    lambda i,r:r[0].update(url='https://example.invalid/filing'),
    lambda i,r:r.append(deepcopy(r[0])),
])
def test_tampered_claim_or_citation_cannot_answer(change,sources):
    material=svc.fetch_verified_metric_evidence(TICKER,question=question(),as_of='2026-10-20')
    items,refs=admit_evidence(material,evaluated_at='2026-10-20')[:2]
    change(items[0],refs)
    thesis=InvestmentThesis(ticker=TICKER,company_name='Invented')
    result=apply_source_answer_gate(thesis,question(),items,references=refs)
    assert result['status']=='insufficient_claim_evidence' and not result['claims']
    assert not thesis.quantitative_claims

@pytest.mark.parametrize('q',[
    'What is annual EPS?', 'Cite annual basic EPS and revenue.',
    'What is the investment thesis and annual basic EPS?',
    'Explain annual diluted EPS risks.', 'What forward annual basic EPS is expected?',
    'Use annual basic EPS to set valuation thresholds.',
    'Cite adjusted annual basic EPS.', 'What is annual basic EPS for 2024?',
    'What is trailing annual basic EPS?', 'What is IFRS annual basic EPS?',
    'Cite annual basic EPS per ADR.',
])
def test_scoped_fact_view_does_not_consume_other_research_parts(q):
    assert eps.annual_eps_request(q) is None


def test_unrelated_monetary_evidence_cannot_fill_explicit_eps_slot(sources):
    from app.integrity.sec_metric_evidence import comparable_metric_evidence
    data=[replace(r,concept='Revenues',unit='USD') for r in rows() if r.concept!='Assets']
    item=comparable_metric_evidence(data,ticker=TICKER,expected_cik=CIK,concepts=('Revenues',),metric_name='revenue')
    result,thesis,_,_=answer([item])
    assert result['status']=='insufficient_claim_evidence' and not result['claims']

from test_source_evidence_latency import isolated_pipeline
_REAL_METRIC_FETCH = svc.fetch_verified_metric_evidence

@pytest.mark.parametrize('basis,currency',[('basic','USD'),('basic','EUR'),('diluted','EUR')])
def test_full_normal_pipeline_uses_fact_view_without_models(isolated_pipeline,sources,monkeypatch,basis,currency):
    from app.schemas import CompanyContext
    from app.services import router_service as router
    data,calls=sources;data[:]=rows(basis,currency,'20-F' if currency=='EUR' else '10-K')
    monkeypatch.setattr(svc,'fetch_verified_metric_evidence',_REAL_METRIC_FETCH)
    import threading
    workers_before=set(threading.enumerate())
    try:
        response=router._run_investment_pipeline(CompanyContext(ticker=TICKER,company_name='Invented company'),
            question(basis), 'annual-eps-routing',side_effects_enabled=False,as_of='2026-10-20')
    finally:
        for worker in threading.enumerate():
            if worker not in workers_before and worker.name.startswith('ThreadPoolExecutor-'):
                worker.join(5)
                assert not worker.is_alive()
    assert isolated_pipeline==[] and len(calls)==1
    assert response.routing['response_mode']=='source_evidence'
    assert response.answer['source_answer']['status']=='attributed'
    assert response.answer['investment_thesis']['confidence_score']==0
    assert basis+' EPS' in response.answer['investment_thesis']['direct_answer']
    refs={r['id'] for r in response.answer['evidence_references']}
    assert all(c['reference_id'] in refs for c in response.answer['source_answer']['claims'])

@pytest.mark.parametrize('field,value',[
    ('document_type','10-Q'),('extraction_method','publisher_feed'),
    ('freshness_status','stale'),('source_tier','secondary'),
    ('filed_at','2026-01-01'),('reporting_period_end','2024-12-31'),
])
def test_reference_metadata_must_match_annual_admitted_contract(sources,field,value):
    material=svc.fetch_verified_metric_evidence(TICKER,question=question(),as_of='2026-10-20')
    items,refs=admit_evidence(material,evaluated_at='2026-10-20')[:2]
    refs[0][field]=value
    thesis=InvestmentThesis(ticker=TICKER,company_name='Invented')
    result=apply_source_answer_gate(thesis,question(),items,references=refs)
    assert result['status']=='insufficient_claim_evidence' and not result['claims']
