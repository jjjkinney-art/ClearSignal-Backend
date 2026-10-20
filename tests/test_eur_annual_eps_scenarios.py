"""Invented same-currency annual EPS: no FX, ADR, IFRS inference or live calls."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.integrity.sec_metric_evidence import comparable_metric_evidence
from app.integrity.sec_fact_binding import bind_sec_fact
from app.integrity.provenance import Provenance, QuantitativeClaim
from app.providers.sec_client import parse_company_fact_records
from app.services import conditional_valuation_service as svc
from app.services.financial_thesis_foundation import _rebuild
from app.services.source_anchored_valuation import (
    evaluate_source_anchored_scenario, evaluate_basic_source_anchored_scenario,
    evaluate_explicit_annual_eps_scenario, _source_eps,
)
from app.services.earnings_recovery_scenario import (
    evaluate_earnings_recovery, evaluate_basic_earnings_recovery, evaluate_explicit_annual_eps_recovery,
)
from app.services.conditional_valuation_math import ValuationContractError
from test_conditional_valuation_api import records, post, enabled
from test_source_anchored_valuation import assumptions as positive, admitted
from test_earnings_recovery_scenario import assumptions as recovery
from test_quote_eps_binding import inputs as quote_inputs
from validation.quote_eps_binding import assess_quote_eps_binding


def eur_records(current=5,share_basis='diluted',form='20-F'):
    concept='EarningsPerShareBasic' if share_basis=='basic' else 'EarningsPerShareDiluted'
    return [replace(row,unit='EUR',form=form) if row.concept=='Assets' else
        replace(row,concept=concept,unit='EUR/shares',form=form) for row in records(current)]


def assumptions(mode='evaluate_growth_scenario',share_basis='diluted'):
    a=recovery() if mode=='evaluate_earnings_recovery_scenario' else positive(mode)
    a['eps_basis'].update(currency='EUR',share_basis=share_basis)
    a['price']['unit']='EUR/share'
    if 'target_eps' in a:a['target_eps']['unit']='EUR/shares'
    return a


def item(current=5,share_basis='diluted',form='20-F'):
    concept='EarningsPerShareBasic' if share_basis=='basic' else 'EarningsPerShareDiluted'
    return comparable_metric_evidence(eur_records(current,share_basis,form),ticker='ZQXB',expected_cik='1234567',
        concepts=(concept,),metric_name=share_basis+' EPS',unit='EUR/shares')


def run(mode='evaluate_growth_scenario',share_basis='diluted',current=None,a=None,items=None,refs=None):
    loss=mode=='evaluate_earnings_recovery_scenario'
    if items is None:items,refs=admitted([item((-2 if loss else 5) if current is None else current,share_basis)])
    evaluator=evaluate_explicit_annual_eps_recovery if loss else evaluate_explicit_annual_eps_scenario
    return evaluator('ZQXB',items,refs,expected_cik='1234567',assumptions=assumptions(mode,share_basis) if a is None else a,
        evaluated_at='2026-03-03',currency='EUR',share_basis=share_basis)


@pytest.mark.parametrize('basis',['basic','diluted'])
@pytest.mark.parametrize('mode',['evaluate_growth_scenario','solve_required_earnings_growth','evaluate_earnings_recovery_scenario'])
@pytest.mark.parametrize('form',['20-F','20-F/A','10-K'])
def test_http_preserves_form_currency_concept_units_and_hypothesis(enabled,monkeypatch,basis,mode,form):
    loss=mode=='evaluate_earnings_recovery_scenario'
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:eur_records(-2 if loss else 5,basis,form))
    a=assumptions(mode,basis);before=deepcopy(a)
    response=post({'ticker':'ZQXB','assumptions':a});r=response.json()
    assert response.status_code==200 and r['available'] and r['status']=='partial'
    assert r['reporting_currency']=='EUR' and not r['fx_conversion_performed'] and not r['adr_conversion_performed']
    assert not r['market_price_observed'] and not r['market_pe_verified'] and not r['admitted'] and not r['launch_ready']
    assert r['scenario']['source_eps']['unit']=='EUR/shares' and r['scenario']['source_eps']['currency']=='EUR'
    assert r['scenario']['source_eps']['share_basis']==basis and r['evidence_references'][0]['document_type']==form
    assert all(c['unit']=='EUR/shares' and c['currency']=='EUR' and c['source']==form for c in r['source_claims'])
    assert 'EUR per share' in r['evidence_references'][0]['title'] and '$' not in r['evidence_references'][0]['title']
    assert a==before and response.headers['cache-control']=='no-store'


@pytest.mark.parametrize('basis',['basic','diluted'])
def test_eur_positive_arithmetic_is_same_dimensionless_equation(basis):
    r=run(share_basis=basis)
    assert r['available'] and Decimal(r['entry_pe_derivation']['value'])==20
    assert Decimal(r['values']['annualized_price_change'])==Decimal('0.5')
    a=assumptions('solve_required_earnings_growth',basis)
    a['exit_pe']['value']='20';a['annual_price_return_rate']['value']='0.1'
    r=run('solve_required_earnings_growth',basis,a=a)
    assert r['available'] and Decimal(r['values']['eps_growth_rate'])==Decimal('0.1')


@pytest.mark.parametrize('basis',['basic','diluted'])
@pytest.mark.parametrize('current',[-2,0])
def test_eur_recovery_keeps_currency_and_loss_out_of_the_price_equation(basis,current):
    r=run('evaluate_earnings_recovery_scenario',basis,current=current)
    assert r['available'] and r['numeric_contract']['terminal_price_unit']=='EUR/share'
    assert Decimal(r['values']['assumed_terminal_price'])==100
    assert Decimal(r['values']['annualized_price_change'])==Decimal('0.25')
    assert not r['source_eps_used_in_scenario_arithmetic'] and not r['market_pe_verified']


@pytest.mark.parametrize('basis',['basic','diluted'])
@pytest.mark.parametrize('loss',[False,True])
def test_old_usd_entry_points_still_refuse_eur_assumptions_and_facts(basis,loss):
    mode='evaluate_earnings_recovery_scenario' if loss else 'evaluate_growth_scenario'
    items,refs=admitted([item(-2 if loss else 5,basis)])
    evaluator=(evaluate_basic_earnings_recovery if basis=='basic' else evaluate_earnings_recovery) if loss else (
        evaluate_basic_source_anchored_scenario if basis=='basic' else evaluate_source_anchored_scenario)
    r=evaluator('ZQXB',items,refs,expected_cik='1234567',assumptions=assumptions(mode,basis),evaluated_at='2026-03-03')
    assert not r['available'] and 'values' not in r


def test_default_eps_helper_and_quote_binding_cannot_use_eur_sources():
    items,refs=admitted([item()])
    with pytest.raises(ValuationContractError):_source_eps('ZQXB','1234567',items,refs,date(2026,3,2))
    args=quote_inputs();args.update(items=items,references=refs)
    assert not assess_quote_eps_binding(**args)['binding_passed']


@pytest.mark.parametrize('mode,field',[
    ('evaluate_growth_scenario','price'),
    ('evaluate_earnings_recovery_scenario','price'),
    ('evaluate_earnings_recovery_scenario','target_eps'),
])
def test_currency_unit_mismatch_is_never_converted(mode,field):
    a=assumptions(mode)
    a[field]['unit']='USD/share' if field=='price' else 'USD/shares'
    r=run(mode,a=a)
    assert not r['available'] and 'values' not in r


@pytest.mark.parametrize('request_currency,provided_currency',[('EUR','USD'),('USD','EUR')])
def test_http_does_not_fall_back_to_other_currency(enabled,monkeypatch,request_currency,provided_currency):
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:records() if provided_currency=='USD' else eur_records())
    a=assumptions() if request_currency=='EUR' else positive()
    r=post({'ticker':'ZQXB','assumptions':a}).json()
    assert not r['available'] and not r['source_claims'] and not r['evidence_references']


@pytest.mark.parametrize('change,stage',[
    (lambda rows:[replace(r,unit='USD') if r.concept=='Assets' else r for r in rows],'annual_reporting_currency'),
    (lambda rows:rows+[replace(rows[-1],unit='USD')],'annual_reporting_currency'),
    (lambda rows:[replace(r,form='10-K') if r.concept=='Assets' else r for r in rows],'annual_reporting_form'),
    (lambda rows:[replace(r,form='6-K') for r in rows],'annual_diluted_eps'),
    (lambda rows:[replace(r,form='10-Q') for r in rows],'annual_diluted_eps'),
    (lambda rows:[replace(r,taxonomy='ifrs-full') for r in rows],'annual_diluted_eps'),
    (lambda rows:[replace(r,cik='9999999') for r in rows],'annual_diluted_eps'),
    (lambda rows:rows+[replace(rows[1],value=999)],'annual_diluted_eps'),
    (lambda rows:[replace(r,unit='GBP/shares') if r.concept!='Assets' else r for r in rows],'annual_diluted_eps'),
])
def test_eur_source_ambiguity_and_unsupported_taxonomy_forms_remain_gaps(enabled,monkeypatch,change,stage):
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:change(eur_records()))
    r=post({'ticker':'ZQXB','assumptions':assumptions()}).json()
    assert not r['available'] and r['stage']==stage and not r['source_claims']


@pytest.mark.parametrize('currency',[None,'GBP','eur','USD/EUR',[],True])
def test_unsupported_request_currency_is_rejected_before_sources(enabled,currency):
    a=assumptions();a['eps_basis']['currency']=currency
    assert post({'ticker':'ZQXB','assumptions':a}).status_code==400 and enabled==[]


@pytest.mark.parametrize('change',[
    lambda i:i.verified_claims[0].update(currency='USD'),
    lambda i:i.verified_claims[0].update(unit='USD/shares'),
    lambda i:i.verified_claims[1].update(unit='USD/shares'),
    lambda i:i.verified_claims[0].update(raw_value=999),
    lambda i:i.verified_claims[0].update(value_text='$5 per share'),
])
def test_reconstruction_never_relabels_or_admits_tampered_eur_claims(change):
    i=item();change(i);items,refs=admitted([i])
    assert not run(items=items,refs=refs)['available']


@pytest.mark.parametrize('unit,text,accepted',[('EUR/shares','5 EUR per share',True),('EUR/shares','$5 per share',False),
    ('EUR/shares','5 GBP per share',False),('GBP/shares','5 GBP per share',False)])
def test_fact_binder_requires_literal_currency_display_identity(unit,text,accepted):
    record=replace(eur_records()[1],unit=unit)
    claim=QuantitativeClaim(value_text=text,provenance=Provenance.REPORTED,raw_value=5,unit=unit,
        ticker='ZQXB',metric='us-gaap:EarningsPerShareDiluted',as_of=record.end,source=record.form)
    assert (bind_sec_fact(claim,record,expected_cik='1234567',period_start=record.start) is not None)==accepted


def test_companyfacts_parser_preserves_exact_eur_units_and_us_gaap_namespace():
    row={'val':5,'start':'2025-01-01','end':'2025-12-31','filed':'2026-02-20','form':'20-F','accn':'0001234567-26-000001'}
    root={'cik':1234567,'facts':{'us-gaap':{'EarningsPerShareDiluted':{'label':'EPS','units':{'EUR/shares':[row]}}}}}
    parsed=parse_company_fact_records(root,concept='EarningsPerShareDiluted',unit='EUR/shares')
    assert len(parsed)==1 and parsed[0].unit=='EUR/shares' and parsed[0].form=='20-F'
    assert parse_company_fact_records(root,concept='EarningsPerShareDiluted',unit='USD/shares')==[]
    root['facts']={'ifrs-full':root['facts']['us-gaap']}
    assert parse_company_fact_records(root,concept='EarningsPerShareDiluted',unit='EUR/shares')==[]


def test_no_monetary_foundation_or_mixed_currency_rebuild_shortcut():
    i=item()
    assert _rebuild(i,ticker='ZQXB',cik='1234567',name='diluted EPS',concepts=('EarningsPerShareDiluted',)) is None
    assert _rebuild(i,ticker='ZQXB',cik='1234567',name='diluted EPS',concepts=('EarningsPerShareDiluted',),expected_unit='USD/shares') is None
    assert _rebuild(i,ticker='ZQXB',cik='1234567',name='diluted EPS',concepts=('EarningsPerShareDiluted',),expected_unit='EUR/shares') is not None


@pytest.mark.parametrize('current',[0,-2])
def test_eur_positive_pe_still_requires_positive_historical_eps(current):
    assert not run(current=current)['available']


def test_usd_20f_is_also_annual_without_changing_currency(enabled,monkeypatch):
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:[replace(r,form='20-F') for r in records()])
    r=post().json()
    assert r['available'] and r['reporting_currency']=='USD'
    assert r['scenario']['source_eps']['unit']=='USD/shares' and r['evidence_references'][0]['document_type']=='20-F'
    assert not r['fx_conversion_performed'] and not r['adr_conversion_performed']


def test_amended_20f_prior_comparison_still_uses_exact_source_units(enabled,monkeypatch):
    rows=eur_records(form='20-F/A')
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:rows)
    r=post({'ticker':'ZQXB','assumptions':assumptions()}).json()
    assert r['available'] and all(c['source']=='20-F/A' for c in r['source_claims'])
    assert all(c['unit']=='EUR/shares' and c['currency']=='EUR' for c in r['source_claims'])


def test_request_harness_waits_for_its_worker_exit_without_disabling_leak_checks(enabled,monkeypatch):
    """Hold a stopped worker at actual thread exit: response must await cleanup."""
    import threading
    from anyio._backends._asyncio import WorkerThread
    exited_run=threading.Event();join_started=threading.Event();release=threading.Event();result=[];failures=[];owned=[]
    original=WorkerThread.run
    original_join=WorkerThread.join
    def held_exit(worker):
        owned.append(worker)
        original(worker)
        exited_run.set()
        if not release.wait(timeout=10):
            failures.append('test did not release worker exit')
    monkeypatch.setattr(WorkerThread,'run',held_exit)
    def observed_join(worker,*args,**kwargs):
        join_started.set()
        return original_join(worker,*args,**kwargs)
    monkeypatch.setattr(WorkerThread,'join',observed_join)
    def request():
        try:result.append(post())
        except BaseException as exc:failures.append(exc)
    caller=threading.Thread(target=request,name='offline-harness-reproduction')
    caller.start()
    try:
        assert exited_run.wait(timeout=5), 'AnyIO worker never reached normal exit'
        assert join_started.wait(timeout=5), 'Request harness did not join its stopped worker'
        assert caller.is_alive(), 'Request harness returned while its worker remained alive'
        assert result==[]
    finally:
        release.set();caller.join(timeout=5)
        for worker in owned:original_join(worker,timeout=5)
    assert not caller.is_alive() and failures==[]
    assert len(result)==1 and result[0].status_code==200


@pytest.mark.parametrize('basis',['basic','diluted'])
def test_eur_does_not_expand_earnings_scope_to_continuing_operations(basis):
    a=assumptions(share_basis=basis);a['eps_basis']['earnings_scope']='continuing_operations'
    assert not run(share_basis=basis,a=a)['available']


@pytest.mark.parametrize('requested',['EUR','USD'])
def test_reporting_currency_anchor_blocks_convenience_translation_shortcut(enabled,monkeypatch,requested):
    rows=eur_records()+[replace(r,value=9,form='20-F') for r in records() if r.concept!='Assets']
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:rows)
    r=post({'ticker':'ZQXB','assumptions':assumptions() if requested=='EUR' else positive()}).json()
    if requested=='EUR':assert r['available'] and r['scenario']['source_eps']['value']=='5'
    else:assert not r['available'] and r['stage']=='annual_reporting_currency'
