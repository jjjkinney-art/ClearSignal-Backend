"""Invented Company Facts diagnostics; no external I/O or execution authority."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from validation.eps_source_gap_analysis import analyze_eps_facts, validate_analysis_date

AS_OF='2026-03-02'


def facts(issuer='ASML',currency='EUR',basis='diluted',current=5):
    cik=937966 if issuer=='ASML' else 80172
    form='20-F' if issuer=='ASML' else '10-K'
    accession=f'{cik:010d}-26-000001'
    concept='EarningsPerShareBasic' if basis=='basic' else 'EarningsPerShareDiluted'
    rows=[{'val':value,'start':f'{year}-01-01','end':f'{year}-12-31','filed':'2026-02-20',
           'form':form,'accn':accession} for year,value in ((2024,4),(2025,current))]
    return {'cik':cik,'facts':{'us-gaap':{
        concept:{'label':basis+' EPS','units':{currency+'/shares':rows}},
        'Assets':{'label':'Assets','units':{currency:[{'val':100,'end':'2025-12-31',
            'filed':'2026-02-20','form':form,'accn':accession}]}}}}}


def run(data=None,issuer='ASML'):
    return analyze_eps_facts(json.dumps(facts() if data is None else data).encode(),issuer=issuer,analysis_as_of=AS_OF)


def selected(report,basis='diluted',currency='EUR'):
    return next(r for r in report['candidates'] if r['share_basis']==basis and r['currency']==currency)


@pytest.mark.parametrize('issuer,currency,basis',[('ASML','EUR','diluted'),('ASML','USD','basic'),('NPK','USD','basic'),('NPK','EUR','diluted')])
def test_exact_annual_candidate_is_bounded_not_admitted_and_reproducible(issuer,currency,basis):
    data=facts(issuer,currency,basis);before=deepcopy(data)
    r=run(data,issuer);c=selected(r,basis,currency)
    assert len(r['candidates'])==4 and c['candidate_contract_qualified'] and c['comparison_selected']
    assert c['selected_comparison']['current_value']=='5' and c['selected_comparison']['prior_value']=='4'
    assert c['selected_comparison']['unit']==currency+'/shares' and c['gap'] is None
    assert not r['admitted_evidence'] and not r['source_origin_independently_verified'] and not r['launch_ready']
    assert data==before and r==run(data,issuer)
    assert len(json.dumps(r))<10_000


@pytest.mark.parametrize('value',[-2,0])
def test_nonpositive_eps_remains_source_context_not_a_pe_calculation(value):
    r=run(facts(current=value));c=selected(r)
    assert c['candidate_contract_qualified'] and c['selected_comparison']['current_value']==str(value)
    assert 'values' not in r and 'current_pe' not in r


@pytest.mark.parametrize('change,gap',[
    (lambda d:d['facts']['us-gaap'].pop('Assets'),'latest_annual_reporting_period'),
    (lambda d:d['facts']['us-gaap']['Assets']['units'].update(USD=d['facts']['us-gaap']['Assets']['units']['EUR']),'annual_reporting_currency'),
    (lambda d:d['facts']['us-gaap']['Assets']['units']['EUR'][0].update(form='10-K'),'annual_reporting_form'),
    (lambda d:d['facts']['us-gaap']['Assets']['units']['EUR'][0].update(accn='0000937966-26-000002'),'annual_reporting_currency'),
    (lambda d:d['facts']['us-gaap']['EarningsPerShareDiluted']['units']['EUR/shares'][1].update(form='6-K'),'annual_comparison_unavailable'),
    (lambda d:d['facts']['us-gaap']['EarningsPerShareDiluted']['units']['EUR/shares'][1].update(filed='2026-03-03'),'annual_comparison_unavailable'),
])
def test_reporting_currency_form_accession_date_and_pair_gaps(change,gap):
    d=facts();change(d);c=selected(run(d))
    assert not c['candidate_contract_qualified'] and c['gap']==gap


def test_ifrs_namespace_and_basic_eps_are_never_promoted_to_diluted_us_gaap():
    d=facts(basis='basic');r=run(d)
    assert selected(r,'basic')['candidate_contract_qualified'] and not selected(r)['comparison_selected']
    d['facts']={'ifrs-full':d['facts']['us-gaap']}
    assert all(not c['comparison_selected'] for c in run(d)['candidates'])


@pytest.mark.parametrize('body',[b'{}',b'[]',b'{"cik":1,"facts":{}}',b'{"cik":true,"facts":{}}',
    b'{"cik":937966,"cik":937966,"facts":{}}',b'{"cik":937966,"facts":{"x":NaN}}',
    b'{"cik":937966,"facts":{"x":1e9999}}',b'{"cik":937966,"facts":null}',b'\xff'])
def test_invalid_identity_json_duplicates_and_nonfinite_input_fail_closed(body):
    with pytest.raises((ValueError,UnicodeError)):
        analyze_eps_facts(body,issuer='ASML',analysis_as_of=AS_OF)


@pytest.mark.parametrize('value',[None,'2026-3-2','2999-01-01','not-a-date'])
def test_analysis_date_is_explicit_canonical_and_nonfuture(value):
    with pytest.raises((TypeError,ValueError)):validate_analysis_date(value)


def test_unknown_issuer_cannot_establish_source_identity():
    with pytest.raises(ValueError):run(facts(),issuer='HOLDOUT')
