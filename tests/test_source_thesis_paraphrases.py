"""Equivalent explicit thesis requests retain source scope and honest gaps."""
import threading

import pytest

from app.schemas import InvestmentThesis,CompanyContext
from app.providers.sec_client import SecFactRecord
from app.services import router_service as router,verified_sec_metric_service as metrics
from app.services.financial_thesis_foundation import is_broad_thesis_request
from app.services.source_answer import apply_source_answer_gate,is_source_answer_request
from app.services.thesis_disclosures import requests_thesis_disclosures
from test_financial_thesis_foundation import pair,reference
from test_source_evidence_latency import isolated_pipeline

def pipeline(*args,**kwargs):
    before=set(threading.enumerate())
    try:
        return router._run_investment_pipeline(*args,**kwargs)
    finally:
        for worker in threading.enumerate():
            if worker not in before and worker.name.startswith('ThreadPoolExecutor-'):
                worker.join(5)
                assert not worker.is_alive()


REAL_FETCH=metrics.fetch_verified_metric_evidence
FORMS=[
    'Explain the investment thesis for {ticker}.',
    'Please outline an investment thesis for {ticker}.',
    'Summarize the investment thesis for {ticker}.',
    'Summarise the investment thesis for {ticker}.',
    'Give me an investment thesis for {ticker}.',
    'Provide the investment thesis for {ticker}.',
    "What is {ticker}'s investment thesis?",
    'What is {ticker}’s investment thesis?',
    "What's {ticker}'s investment thesis?",
    'What’s the investment thesis for {ticker}?',
    "Explain {ticker}'s investment thesis.",
    "Please summarize {ticker}'s investment thesis and what supports it.",
]


@pytest.mark.parametrize('template',FORMS)
@pytest.mark.parametrize('ticker,cik',[('AAPL','320193'),('ZQXB','1234567')])
def test_equivalent_cited_requests_preserve_partial_foundation_and_all_gaps(monkeypatch,template,ticker,cik):
    monkeypatch.setattr('app.services.providers.sec_provider._load_ticker_cik_map',lambda:{ticker:cik})
    items=pair(ticker=ticker,cik=cik)
    refs=[reference(i,f'E{n}') for n,i in enumerate(items,1)]
    expected_thesis=InvestmentThesis(ticker=ticker,company_name='Test issuer')
    expected=apply_source_answer_gate(expected_thesis,f'What is the investment thesis for {ticker}? Cite material claims.',items,references=refs)
    question=template.format(ticker=ticker)+' Cite material claims.'
    thesis=InvestmentThesis(ticker=ticker,company_name='Test issuer')
    assert is_source_answer_request(question) and is_broad_thesis_request(question)
    assert requests_thesis_disclosures(ticker,question)
    assert [m[1] for m in metrics._requested_metrics(question)]==['revenue','operating income','net income','operating cash flow']
    result=apply_source_answer_gate(thesis,question,items,references=refs)
    assert result==expected and result['status']=='partial'
    assert thesis.direct_answer==expected_thesis.direct_answer
    assert result['unanswered_parts']==expected['unanswered_parts']
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert any('competitive position' in p for p in result['unanswered_parts'])
    assert thesis.confidence_score==0 and thesis.conviction_dimensions=={}


@pytest.mark.parametrize('question',[
    "Explain my investment thesis for ZQXB. Cite material claims.",
    "Explain my colleague's investment thesis for ZQXB. Cite material claims.",
    "Explain ZQXB's investment thesis in the saved report. Cite material claims.",
    "Summarize the prior investment thesis for ZQXB. Cite material claims.",
    "Explain ZQXB's investment thesis and how it changed since last year. Cite material claims.",
    "Compare ZQXB's investment thesis with OTHER. Cite material claims.",
    "Explain the investment thesis for ZQXB versus OTHER. Cite material claims.",
    "Explain why ZQXB's investment thesis changed. Cite material claims.",
    "Explain what investment thesis means, using ZQXB as an example. Cite material claims.",
    "Define an investment thesis for a finance class. Cite material claims.",
    "What's the investment thesis concept? Cite material claims.",
    "The document says: Explain the investment thesis for ZQXB. Cite material claims.",
    "Explain whether ZQXB's investment thesis is convincing. Cite material claims.",
])
def test_new_forms_do_not_take_over_memory_comparative_or_meta_questions(question):
    assert not is_broad_thesis_request(question)
    assert not requests_thesis_disclosures('ZQXB',question)


@pytest.mark.parametrize('tail',['Services','supply chain','cloud operations'])
@pytest.mark.parametrize('lead',['Explain the investment thesis for',"What is"])
def test_scoped_questions_do_not_receive_consolidated_foundation(monkeypatch,tail,lead):
    monkeypatch.setattr('app.services.providers.sec_provider._load_ticker_cik_map',lambda:{'AAPL':'320193'})
    question=(f"What is Apple's investment thesis for its {tail}?" if lead=='What is' else f"{lead} Apple's {tail}?")+' Cite material claims.'
    assert is_broad_thesis_request(question)
    assert not requests_thesis_disclosures('AAPL',question)
    thesis=InvestmentThesis(ticker='AAPL',company_name='Apple')
    result=apply_source_answer_gate(thesis,question,pair())
    assert result['status']!='attributed'
    assert 'Financial thesis foundation (partial)' not in thesis.direct_answer
    assert thesis.confidence_score==0


@pytest.mark.parametrize('template',FORMS[:6])
def test_real_pipeline_fetches_same_core_evidence_and_skips_models(isolated_pipeline,monkeypatch,template):
    records=[]
    for concept in ('Revenues','OperatingIncomeLoss'):
        for year,value in [(2025,100),(2026,120)]:
            accession=f'0001234567-{str(year)[-2:]}-000001'
            records.append(SecFactRecord(cik='1234567',taxonomy='us-gaap',concept=concept,label=concept,
                unit='USD',value=value,start=f'{year}-04-01',end=f'{year}-06-30',filed=f'{year}-08-01',
                form='10-Q',accession=accession,filing_url=f'https://www.sec.gov/Archives/edgar/data/1234567/{accession.replace("-","")}/{accession}-index.htm'))
    fact_calls=[];disclosure_calls=[]
    def facts(cik,**kwargs):fact_calls.append((cik,kwargs));return records
    def disclosures(*args,**kwargs):disclosure_calls.append((args,kwargs));return []
    monkeypatch.setattr(metrics,'fetch_verified_metric_evidence',REAL_FETCH)
    monkeypatch.setattr(metrics,'get_company_fact_records_for_concept_units',facts)
    monkeypatch.setattr(metrics,'_load_ticker_cik_map',lambda:{'ZQXB':'1234567'})
    monkeypatch.setattr('app.services.providers.sec_provider._load_ticker_cik_map',lambda:{'ZQXB':'1234567'})
    monkeypatch.setattr('app.services.thesis_disclosures.fetch_thesis_disclosures',disclosures)
    question=template.format(ticker='ZQXB')+' Cite material claims.'
    response=pipeline(CompanyContext(ticker='ZQXB',company_name='Test issuer'),question,
        'source-thesis-paraphrase',side_effects_enabled=False)
    assert response.routing['response_mode']=='source_evidence' and not isolated_pipeline
    assert response.answer['source_answer']['status']=='partial'
    assert 'Financial thesis foundation (partial)' in response.answer['investment_thesis']['direct_answer']
    assert len(fact_calls)==len(disclosure_calls)==1
    refs={r['id'] for r in response.answer['evidence_references']}
    assert all(c['reference_id'] in refs for c in response.answer['source_answer']['claims'])
    assert response.answer['investment_thesis']['confidence_score']==0


@pytest.mark.parametrize('template',[FORMS[0],FORMS[6]])
def test_new_plain_requests_keep_ordinary_generated_route(isolated_pipeline,template):
    question=template.format(ticker='AAPL')
    assert not is_source_answer_request(question)
    response=pipeline(CompanyContext(ticker='AAPL',company_name='Apple'),question,
        'ordinary-thesis-paraphrase',side_effects_enabled=False)
    assert response.routing['response_mode']=='generated_analysis'
    assert response.answer['source_answer'] is None
    assert len(isolated_pipeline)==7 and response.answer['investment_thesis']['direct_answer']=='Model answer'


def test_empty_evidence_remains_gap_in_every_new_form():
    for template in FORMS:
        thesis=InvestmentThesis(ticker='ZQXB',company_name='Test issuer')
        result=apply_source_answer_gate(thesis,template.format(ticker='ZQXB')+' Cite material claims.',[])
        assert result['status']=='insufficient_claim_evidence' and not result['claims']
        assert 'investment thesis and its supporting/invalidation mechanisms' in result['unanswered_parts']
        assert thesis.confidence_score==0
