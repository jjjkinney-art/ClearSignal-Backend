"""Synthetic annual cash-use explanations; no live source/model calls."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from app.services import annual_cash_flow_context as service
from app.integrity.provenance import ClaimDocumentReference
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from app.schemas import InvestmentThesis
from test_segment_revenue_policy import document as base_document
from test_financial_thesis_foundation import pair, evidence

QUOTE = ('Cash used in operating activities was $100 during 2025 as compared to $200 during 2024. '
    'The principal factors behind the decrease in cash used can be found in the changes in the components of working capital within the Consolidated Statements of Cash Flows. '
    'Of particular note during 2025 was net earnings of $60, which included non-cash depreciation of $10, deferred income tax of $5 and retirement plan expense of $3 related to the Company’s defined contribution retirement plan. '
    'The combination of these factors was more than offset by increases in inventory and accounts receivable levels. '
    'Of particular note during 2024 was net earnings of $50, which included non-cash depreciation of $8 and deferred income tax benefit of $4. '
    'This was augmented by decreases in deposits made to vendors and a net increase in payable and accrual levels. '
    'The combination of these factors was more than offset by increases in inventory and accounts receivable levels.')


def text():
    return ('ITEM 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS '
        'An overview of operations follows. 2025 COMPARED TO 2024 Results. 2024 COMPARED TO 2023 Older results. '
        'LIQUIDITY AND CAPITAL RESOURCES 2025 COMPARED TO 2024 ' + QUOTE +
        ' Net cash used in investing activities was $10. 2024 COMPARED TO 2023 Older cash flows. '
        'ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK')


def observation(year,amount):
    return {'concept_namespace':'http://fasb.org/us-gaap/2025','concept':service.CONCEPT,
        'fact_id':f'cash{year}','context_id':f'year{year}','unit_id':'usd','literal':str(abs(amount)),
        'format_namespace':'http://www.xbrl.org/inlineXBRL/transformation/2020-02-12',
        'format':'num-dot-decimal','sign':'-' if amount<0 else '', 'scale':0,
        'entity_scheme':'http://www.sec.gov/CIK','entity_identifier':'1234567',
        'start':f'{year}-01-01','end':f'{year}-12-31',
        'unit_namespace':'http://www.xbrl.org/2003/iso4217','unit':'USD','scope':'consolidated'}


def document(source=None):
    source=source or text()
    return replace(base_document(source),cash_flow_observations=(observation(2025,-100),observation(2024,-200)))


def item():
    result=service.extract_annual_cash_flow_context(document(),ticker='ZQXB',cik='1234567')
    assert len(result)==1
    return result[0]


def test_signed_annual_observations_and_complete_prior_context_are_retained():
    value=service.bound_annual_cash_flow_context(item(),ticker='ZQXB',cik='1234567')
    assert value['quote']==QUOTE
    context=value['cash_flow_context']
    assert context['current_amount']==-100 and context['prior_amount']==-200
    assert context['current_start']=='2025-01-01' and context['current_end']=='2025-12-31'
    assert context['interim_bridge_established'] is False
    assert context['independent_causality_established'] is False
    assert 'Both annual amounts are cash outflows' in item().summary


@pytest.mark.parametrize('change',[
    lambda d:replace(d,cash_flow_observations=(observation(2025,100),observation(2024,-200))),
    lambda d:replace(d,cash_flow_observations=(observation(2025,-100),)),
    lambda d:replace(d,cash_flow_observations=d.cash_flow_observations+d.cash_flow_observations[:1]),
    lambda d:replace(d,cash_flow_observations=(observation(2026,-100),observation(2024,-200))),
    lambda d:replace(d,document_type='10-Q'),
    lambda d:replace(d,final_url='https://example.com/filing.htm'),
    lambda d:replace(d,cash_flow_observations=(None,)),
    lambda d:replace(d,cash_flow_observations=d.cash_flow_observations*51),
])
def test_missing_conflicting_positive_or_other_period_sources_fail_closed(change):
    assert service.extract_annual_cash_flow_context(change(document()),ticker='ZQXB',cik='1234567')==[]


@pytest.mark.parametrize('before,after',[
    ('$100 during 2025','$101 during 2025'),('$200 during 2024','$199 during 2024'),
    ('decrease in cash used','increase in cash used'),
    ('Of particular note during 2024','Of particular note during 2023'),
    ('2025 COMPARED TO 2024 Results','2026 COMPARED TO 2025 Results'),
    ('LIQUIDITY AND CAPITAL RESOURCES','OTHER RESOURCES'),
    (' Net cash used in investing activities was $10.',''),
    ('ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK',''),
    ('This was augmented by decreases in deposits made to vendors and a net increase in payable and accrual levels. ',''),
    ('more than offset by increases in inventory','expected to be offset by future inventory'),
])
def test_narrative_sign_direction_years_and_complete_window_are_required(before,after):
    assert service.extract_annual_cash_flow_context(document(text().replace(before,after)),ticker='ZQXB',cik='1234567')==[]


@pytest.mark.parametrize('field',['sign','scale','scope','dimension','entity','currency','period','amount','quote','offset','hash','causality','interim','summary','ticker','ref','stale','metadata_period','fact_id','context_id','namespace'])
def test_final_binder_reconstructs_signed_context_and_reference(field):
    value=deepcopy(item());v=value.cash_flow_disclosures[0];o=v['observations'][0]
    if field=='sign':o['sign']=''
    elif field=='scale':o['scale']=3
    elif field=='scope':o['scope']='segment'
    elif field=='dimension':o['dimensions']=[{'member':'Other'}]
    elif field=='entity':o['entity_identifier']='999'
    elif field=='currency':o['unit']='EUR'
    elif field=='period':o['start']='2025-04-01'
    elif field=='amount':v['cash_flow_context']['current_amount']=100
    elif field=='quote':v['quote']='Improved cash proves strength.'
    elif field=='offset':v['start_offset']+=1
    elif field=='hash':v['cash_flow_source_proof']['sha256']='0'*64
    elif field=='causality':v['cash_flow_context']['independent_causality_established']=True
    elif field=='interim':v['cash_flow_context']['interim_bridge_established']=True
    elif field=='summary':value.summary='Cash generation is sustainable.'
    elif field=='ticker':v['ticker']='OTHER'
    elif field=='ref':v['document_ref']['quote']='Short quote.'
    elif field=='stale':value.freshness_status='stale'
    elif field=='metadata_period':value.reporting_period_start='2025-04-01'
    elif field=='fact_id':o['fact_id']=v['observations'][1]['fact_id']
    elif field=='context_id':o['context_id']=v['observations'][1]['context_id']
    elif field=='namespace':o['concept_namespace']='http://fasb.org/us-gaap/2024'
    assert service.bound_annual_cash_flow_context(value,ticker='ZQXB',cik='1234567') is None


def test_ordinary_retrieval_is_single_fetch_and_final_gate_does_not_reinterpret_interim(monkeypatch):
    from app.services import thesis_disclosures as disclosures
    doc=document();calls=[]
    monkeypatch.setattr(disclosures.sec_provider,'_load_ticker_cik_map',lambda:{'ZQXB':'1234567'})
    monkeypatch.setattr(disclosures.sec_provider,'fetch_recent_filings',lambda *a,**kw:[SimpleNamespace(
        url=doc.final_url,timestamp=doc.published_at,document_type='10-K')])
    def saved(url,**kwargs):calls.append(url);return doc
    monkeypatch.setattr(disclosures,'fetch_public_document',saved)
    retrieved=disclosures.fetch_thesis_disclosures('ZQXB',question='What is the investment thesis for ZQXB?')
    assert len(calls)==1
    financial=pair(ticker='ZQXB',cik='1234567')+[evidence(service.CONCEPT,'operating cash flow',ticker='ZQXB',cik='1234567',ytd=True)]
    admitted,refs,_=admit_evidence(financial+retrieved,evaluated_at='2026-10-24')
    thesis=InvestmentThesis(ticker='ZQXB',company_name='Synthetic issuer')
    result=apply_source_answer_gate(thesis,'What is the investment thesis for ZQXB? Cite material claims.',admitted,references=refs)
    claims=[c for c in result['claims'] if c['claim_kind']==service.KIND]
    assert len(claims)==1 and thesis.direct_answer.count(claims[0]['claim'])==1
    assert f"[{claims[0]['reference_id']}]" in thesis.direct_answer
    cash=next(r for r in result['inferences'] if r.get('metric')=='operating cash flow')
    assert cash['signal']=='context_only'
    assert result['status']=='partial' and 'valuation and expected returns' in result['unanswered_parts']
    assert 'later interim results' in thesis.direct_answer and thesis.confidence_score==0


def test_only_the_new_scoped_reference_can_hold_a_complete_long_explanation():
    ref=item().cash_flow_disclosures[0]['document_ref']
    assert len(ref['quote'])>900 and ClaimDocumentReference(**ref).quote==QUOTE
    with pytest.raises(ValueError,match='300'):
        ClaimDocumentReference(**{**ref,'section':'Item 7. Management discussion and analysis'})
