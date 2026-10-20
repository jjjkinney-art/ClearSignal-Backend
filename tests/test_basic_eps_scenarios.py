"""Explicit basic EPS hypotheses; no diluted substitution or live requests."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.integrity.sec_metric_evidence import comparable_metric_evidence
from app.services.conditional_valuation_math import ValuationContractError
from app.services.financial_thesis_foundation import _rebuild
from app.services.source_anchored_valuation import (
    evaluate_source_anchored_scenario, evaluate_basic_source_anchored_scenario, _source_eps,
)
from app.services.earnings_recovery_scenario import evaluate_earnings_recovery, evaluate_basic_earnings_recovery
from app.services import conditional_valuation_service as svc
from test_conditional_valuation_api import records, post
from test_conditional_valuation_api import enabled  # shared invented provider/clock fixture
from test_source_anchored_valuation import assumptions as positive, admitted, eps_item
from test_earnings_recovery_scenario import assumptions as recovery
from test_quote_eps_binding import inputs as quote_inputs
from validation.quote_eps_binding import assess_quote_eps_binding


def basic_records(current=5):
    return [replace(row,concept='EarningsPerShareBasic',label='Basic EPS')
            if row.concept=='EarningsPerShareDiluted' else row for row in records(current)]


def basic_item(current=5):
    return comparable_metric_evidence(basic_records(current),ticker='ZQXB',expected_cik='1234567',
        concepts=('EarningsPerShareBasic',),metric_name='basic EPS',unit='USD/shares')


def basic_assumptions(loss=False,mode='evaluate_growth_scenario'):
    a=recovery() if loss else positive(mode)
    a['eps_basis']['share_basis']='basic'
    return a


def run_basic(a=None,current=5,items=None,refs=None):
    if items is None:items,refs=admitted([basic_item(current)])
    return evaluate_basic_source_anchored_scenario('ZQXB',items,refs,expected_cik='1234567',
        assumptions=basic_assumptions() if a is None else a,evaluated_at='2026-03-03')


def test_basic_positive_hypothesis_uses_only_basic_comparison_and_exact_conditional_algebra():
    a=basic_assumptions();before=deepcopy(a)
    result=run_basic(a)
    assert result['available'] and result['status']=='partial' and not result['launch_ready']
    assert result['source_eps']['concept']=='us-gaap:EarningsPerShareBasic'
    assert result['source_eps']['share_basis']=='basic' and result['source_eps']['value']=='5'
    assert result['entry_pe_derivation']['formula']=='assumed_price / reported_fiscal_basic_eps'
    assert Decimal(result['entry_pe_derivation']['value'])==20
    assert Decimal(result['values']['annualized_price_change'])==Decimal('0.5')
    assert result['entry_pe_derivation']['market_pe_verified'] is False and a==before
    assert any('no basic/diluted substitution' in s for s in result['limitations'])


def test_required_growth_solves_on_basic_basis_without_changing_the_equation():
    a=basic_assumptions(mode='solve_required_earnings_growth')
    a['annual_price_return_rate']['value']='0.1';a['exit_pe']['value']='20'
    r=run_basic(a)
    assert r['available'] and Decimal(r['values']['eps_growth_rate'])==Decimal('0.1')
    assert r['source_eps']['share_basis']=='basic'


@pytest.mark.parametrize('current',[-2,0,-100])
def test_basic_loss_context_uses_explicit_future_basic_eps_without_dividing_by_loss(current):
    items,refs=admitted([basic_item(current)])
    r=evaluate_basic_earnings_recovery('ZQXB',items,refs,expected_cik='1234567',
        assumptions=basic_assumptions(True),evaluated_at='2026-03-03')
    assert r['available'] and r['source_eps']['share_basis']=='basic'
    assert not r['source_eps_used_in_scenario_arithmetic'] and not r['market_pe_verified']
    assert Decimal(r['values']['assumed_terminal_price'])==100
    assert Decimal(r['values']['annualized_price_change'])==Decimal('0.25')
    assert 'current_pe' not in r and 'eps_growth_rate' not in r['values']


@pytest.mark.parametrize('loss',[False,True])
def test_old_diluted_entry_points_still_refuse_explicit_basic_assumptions(loss):
    items,refs=admitted([basic_item(-2 if loss else 5)])
    evaluator=evaluate_earnings_recovery if loss else evaluate_source_anchored_scenario
    r=evaluator('ZQXB',items,refs,expected_cik='1234567',assumptions=basic_assumptions(loss),evaluated_at='2026-03-03')
    assert not r['available'] and 'values' not in r


@pytest.mark.parametrize('loss',[False,True])
def test_basic_entry_points_refuse_diluted_assumptions_even_with_basic_sources(loss):
    items,refs=admitted([basic_item(-2 if loss else 5)])
    evaluator=evaluate_basic_earnings_recovery if loss else evaluate_basic_source_anchored_scenario
    r=evaluator('ZQXB',items,refs,expected_cik='1234567',assumptions=recovery() if loss else positive(),evaluated_at='2026-03-03')
    assert not r['available'] and 'values' not in r


@pytest.mark.parametrize('loss',[False,True])
def test_basic_assumptions_cannot_consume_diluted_source_facts(loss):
    items,refs=admitted([eps_item(current=-2 if loss else 5)])
    evaluator=evaluate_basic_earnings_recovery if loss else evaluate_basic_source_anchored_scenario
    r=evaluator('ZQXB',items,refs,expected_cik='1234567',assumptions=basic_assumptions(loss),evaluated_at='2026-03-03')
    assert not r['available'] and 'source_eps' not in r


def test_basic_data_cannot_satisfy_original_quote_binding_or_default_eps_helper():
    items,refs=admitted([basic_item()])
    with pytest.raises(ValuationContractError):_source_eps('ZQXB','1234567',items,refs,date(2026,3,2))
    args=quote_inputs();args['items']=items;args['references']=refs
    result=assess_quote_eps_binding(**args)
    assert not result['binding_passed'] and not result['admitted']


@pytest.mark.parametrize('concepts,name,unit',[
    (('EarningsPerShareBasic',),'diluted EPS','USD/shares'),
    (('EarningsPerShareDiluted',),'basic EPS','USD/shares'),
    (('EarningsPerShareBasic','EarningsPerShareDiluted'),'basic EPS','USD/shares'),
    (('EarningsPerShareBasic',),'basic EPS','USD'),
    (('EarningsPerShareBasic',),'basic EPS',None),
])
def test_rebuild_contract_only_allows_exact_named_per_share_pairs(concepts,name,unit):
    assert _rebuild(basic_item(),ticker='ZQXB',cik='1234567',name=name,concepts=concepts,expected_unit=unit) is None


@pytest.mark.parametrize('change',[
    lambda i:i.verified_claims[0].update(metric='us-gaap:EarningsPerShareDiluted'),
    lambda i:i.verified_claims[1].update(metric='us-gaap:EarningsPerShareDiluted'),
    lambda i:i.verified_claims[0].update(raw_value=999),
    lambda i:i.verified_claims[0].update(unit='USD'),
    lambda i:i.verified_claims[0].update(currency='EUR'),
    lambda i:i.verified_claims[0]['document_ref'].update(reference_id='sec:9999999:0001234567-26-000001:us-gaap:EarningsPerShareBasic'),
])
def test_basic_reconstruction_refuses_mixed_tampered_or_mislabeled_claims(change):
    item=basic_item();change(item);items,refs=admitted([item])
    assert not run_basic(items=items,refs=refs)['available']


@pytest.mark.parametrize('mode',['evaluate_growth_scenario','solve_required_earnings_growth','evaluate_earnings_recovery_scenario'])
def test_http_route_selects_explicit_basic_source_and_matching_evaluator(enabled,monkeypatch,mode):
    loss=mode=='evaluate_earnings_recovery_scenario'
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:basic_records(-2 if loss else 5))
    response=post({'ticker':'ZQXB','assumptions':basic_assumptions(loss,mode)})
    r=response.json();assert response.status_code==200 and r['available']
    assert r['scenario']['source_eps']['concept']=='us-gaap:EarningsPerShareBasic'
    assert all(c['metric']=='us-gaap:EarningsPerShareBasic' for c in r['source_claims'])
    assert '_basic_eps_' in r['source_selection']
    assert 'basic EPS' in r['evidence_references'][0]['title']
    assert not r['admitted'] and not r['launch_ready'] and not r['market_pe_verified']


@pytest.mark.parametrize('requested,provided',[('basic','diluted'),('diluted','basic')])
def test_http_never_falls_back_to_the_other_eps_basis(enabled,monkeypatch,requested,provided):
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:records() if provided=='diluted' else basic_records())
    a=positive();a['eps_basis']['share_basis']=requested
    r=post({'ticker':'ZQXB','assumptions':a}).json()
    assert not r['available'] and r['stage']=='annual_'+requested+'_eps'
    assert not r['source_claims'] and not r['evidence_references']


@pytest.mark.parametrize('requested,value',[('basic','7'),('diluted','5')])
def test_http_both_families_present_preserves_exact_requested_values(enabled,monkeypatch,requested,value):
    mixed=records()+basic_records(7)[:-1]
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:mixed)
    a=positive();a['eps_basis']['share_basis']=requested
    r=post({'ticker':'ZQXB','assumptions':a}).json()
    assert r['available'] and r['scenario']['source_eps']['value']==value
    assert r['scenario']['source_eps']['share_basis']==requested


@pytest.mark.parametrize('basis',[None,{},[],{'share_basis':'basic_or_diluted'},{'share_basis':None},{'share_basis':['basic']},{'share_basis':True}])
def test_invalid_or_unspecified_basis_is_rejected_before_sources(enabled,basis):
    a=positive();a['eps_basis']=basis
    assert post({'ticker':'ZQXB','assumptions':a}).status_code==400 and enabled==[]


@pytest.mark.parametrize('current',[0,-2])
def test_basic_positive_growth_still_refuses_nonpositive_eps(enabled,monkeypatch,current):
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:basic_records(current))
    r=post({'ticker':'ZQXB','assumptions':basic_assumptions()}).json()
    assert not r['available'] and r['stage']=='scenario_contract'
    assert not r['source_claims'] and not r['evidence_references']


@pytest.mark.parametrize('change,stage',[
    (lambda rows:[r for r in rows if r.concept!='EarningsPerShareBasic' or r.end!='2025-12-31'],'annual_basic_eps'),
    (lambda rows:rows+[replace(rows[-1],end='2026-12-31',filed='2027-02-20')],'accepted_future_rows_excluded'),
    (lambda rows:[replace(r,unit='EUR') if r.concept=='Assets' else r for r in rows],'annual_reporting_currency'),
    (lambda rows:rows+[replace(rows[1],value=999)],'annual_basic_eps'),
    (lambda rows:[replace(r,unit='USD') if r.concept=='EarningsPerShareBasic' else r for r in rows],'annual_basic_eps'),
])
def test_basic_http_keeps_period_currency_conflict_and_unit_boundaries(enabled,monkeypatch,change,stage):
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:change(basic_records()))
    r=post({'ticker':'ZQXB','assumptions':basic_assumptions()}).json()
    if stage=='accepted_future_rows_excluded':assert r['available']
    else:assert not r['available'] and r['stage']==stage and not r['source_claims']


@pytest.mark.parametrize('change',[
    lambda a:a['eps_basis'].update(earnings_scope='continuing_operations'),
    lambda a:a['eps_basis'].update(accounting='adjusted',adjustment_definition='adjusted hypothesis'),
    lambda a:a['eps_basis'].update(period_basis='trailing_12_months'),
    lambda a:a['eps_basis'].update(issuer='OTHER'),
    lambda a:a['eps_basis'].update(currency='EUR'),
])
def test_basic_source_bridge_does_not_expand_accounting_period_or_currency_scope(change):
    a=basic_assumptions();change(a)
    assert not run_basic(a)['available']
