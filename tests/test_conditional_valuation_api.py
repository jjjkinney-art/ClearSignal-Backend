"""Real ASGI endpoint with invented SEC records, no external dispatch or model."""
import asyncio
from copy import deepcopy
import json
import threading
from dataclasses import replace
from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from app.config import Settings, settings
from app.providers.sec_client import SecFactRecord
from app.routers.conditional_valuation import router, conditional_valuation
from app.services import conditional_valuation_service as svc
from app.services.conditional_valuation_math import ValuationContractError
from test_source_anchored_valuation import assumptions as positive
from test_earnings_recovery_scenario import assumptions as recovery


def records(current=5):
    result=[]
    for year,value in ((2024,4),(2025,current)):
        accession=f'0001234567-{str(year+1)[-2:]}-000001'
        result.append(SecFactRecord('1234567','us-gaap','EarningsPerShareDiluted','Diluted EPS','USD/shares',value,
            f'{year}-01-01',f'{year}-12-31',f'{year+1}-02-20','10-K',accession,
            f'https://www.sec.gov/Archives/edgar/data/1234567/{accession.replace("-", "")}/{accession}-index.htm'))
    result.append(replace(result[-1],concept='Assets',label='Assets',unit='USD',value=100,start=None))
    return result


def payload(loss=False):
    return {'ticker':'ZQXB','assumptions':recovery() if loss else positive()}


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings,'conditional_valuation_scenarios_enabled',True)
    monkeypatch.setattr(settings,'enable_data_retrieval',True)
    calls=[]
    from app.services.issuer_identity import parse_directory
    monkeypatch.setattr(svc,'_current_date',lambda:date(2026,3,2))
    monkeypatch.setattr(svc,'_load_directory',lambda:parse_directory({'0':{'ticker':'ZQXB','title':'Invented Company','cik_str':1234567}}))
    def fetch(*args,**kwargs):
        calls.append((args,kwargs));return records()
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',fetch)
    return calls


def post(data=None,raw=None,uid='owner',denied=False,headers=None):
    app=FastAPI();app.include_router(router)
    @app.middleware('http')
    async def auth(request,call_next):
        request.state.user_id=uid;request.state.admission_denied=denied
        return await call_next(request)
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://test.invalid') as client:
            return await client.post('/research/valuation-scenarios',content=raw if raw is not None else json.dumps(payload() if data is None else data),
                headers={'content-type':'application/json',**(headers or {})})
    workers_before=set(threading.enumerate())
    try:
        return asyncio.run(go())
    finally:
        # asyncio root-task completion signals AnyIO workers to stop, but does
        # not join them. Bound and verify this request harness's own cleanup;
        # keep the global thread-leak guard and production deadlines intact.
        workers=[t for t in threading.enumerate() if t not in workers_before
                 and t.name=='AnyIO worker thread']
        for worker in workers:
            worker.join(timeout=5)
        assert not any(worker.is_alive() for worker in workers), 'Scenario test worker failed to stop'


def test_default_is_off_and_old_imports_are_exact_compatibility_objects():
    assert Settings(_env_file=None).conditional_valuation_scenarios_enabled is False
    import validation.valuation_scenario as old_math
    import validation.source_anchored_valuation as old_source
    import validation.earnings_recovery_scenario as old_recovery
    from app.services import conditional_valuation_math, source_anchored_valuation, earnings_recovery_scenario
    assert old_math.evaluate_scenario is conditional_valuation_math.evaluate_scenario
    assert old_source.evaluate_source_anchored_scenario is source_anchored_valuation.evaluate_source_anchored_scenario
    assert old_recovery.evaluate_earnings_recovery is earnings_recovery_scenario.evaluate_earnings_recovery


def test_off_and_global_retrieval_off_do_not_dispatch(enabled,monkeypatch):
    monkeypatch.setattr(settings,'conditional_valuation_scenarios_enabled',False)
    assert post().status_code==404
    assert svc.evaluate_requested_scenario(payload())['stage']=='feature_disabled'
    monkeypatch.setattr(settings,'conditional_valuation_scenarios_enabled',True)
    monkeypatch.setattr(settings,'enable_data_retrieval',False)
    assert post().status_code==503
    assert svc.evaluate_requested_scenario(payload())['stage']=='retrieval_disabled'
    assert enabled==[]


@pytest.mark.parametrize('uid,denied,status',[(None,False,401),(None,True,403)])
def test_existing_account_admission_blocks_before_providers(enabled,uid,denied,status):
    assert post(uid=uid,denied=denied).status_code==status
    assert enabled==[]


def test_positive_scenario_uses_server_sources_and_returns_only_hypothetical_price_change(enabled):
    a=payload();before=deepcopy(a)
    response=post(a);assert response.status_code==200
    assert response.headers['cache-control']=='no-store'
    r=response.json();assert r['available'] and r['status']=='partial'
    assert r['scenario']['source_eps']['value']=='5'
    assert not r['admitted'] and not r['market_price_observed'] and not r['market_pe_verified']
    assert r['evidence_references'][0]['id']==r['scenario']['source_eps']['reference_id']
    assert r['source_claims'][0]['metric']=='us-gaap:EarningsPerShareDiluted'
    assert len(enabled)==1 and enabled[0][1]['concept_units']==svc.CONCEPT_UNITS
    assert a==before


def test_recovery_route_keeps_signed_eps_and_old_positive_mode_still_refuses(enabled,monkeypatch):
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:records(-2))
    r=post(payload(loss=True)).json();assert r['available']
    assert r['scenario']['source_eps']['value']=='-2'
    assert not r['scenario']['source_eps_used_in_scenario_arithmetic']
    r=post().json();assert not r['available'] and r['stage']=='scenario_contract'
    assert r['evidence_references']==[]


@pytest.mark.parametrize('raw',[b'',b'\xff',b'{}',b'null',b'[]',b'{',
    b'{"ticker":"ZQXB","ticker":"OTHER","assumptions":{}}',
    b'{"ticker":"ZQXB","assumptions":{"mode":"evaluate_growth_scenario","mode":"other"}}',
    b'{"ticker":"ZQXB","assumptions":{"value":NaN}}',
    b'{"ticker":"ZQXB","assumptions":{"value":1.5}}'])
def test_malformed_duplicate_nonfinite_and_float_json_rejected_before_provider(enabled,raw):
    assert post(raw=raw).status_code==400
    assert enabled==[]


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(ticker='zqxb'),lambda p:p.update(ticker='ZQXB?apikey=CANARY'),
    lambda p:p.update(expected_cik='9999999'),lambda p:p.update(items=[{}]),
    lambda p:p.update(references=[{'id':'E1'}]),lambda p:p.update(approval=True),
    lambda p:p['assumptions'].update(mode='choose_for_me'),
    lambda p:p['assumptions'].update(scenario_as_of='2099-01-01'),
])
def test_request_cannot_supply_identity_evidence_authority_or_unsupported_mode(enabled,mutation):
    p=payload();mutation(p);r=post(p)
    assert r.status_code==400 and 'CANARY' not in r.text
    assert enabled==[]


def test_body_envelope_and_media_checked_without_provider(enabled):
    assert post(raw=b' '*16385).status_code==413
    assert post(headers={'content-type':'text/plain'}).status_code==415
    assert enabled==[]


def test_stream_overflow_is_checked_when_declared_length_is_absent_or_misleading(enabled):
    async def go(length):
        headers=[(b'content-type',b'application/json')]
        if length is not None:headers.append((b'content-length',length))
        scope={'type':'http','method':'POST','path':'/research/valuation-scenarios','headers':headers}
        chunks=iter([{'type':'http.request','body':b' '*10000,'more_body':True},
                     {'type':'http.request','body':b' '*10000,'more_body':False}])
        async def receive():return next(chunks)
        req=Request(scope,receive);req.state.user_id='owner'
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:await conditional_valuation(req)
        assert e.value.status_code==413
    asyncio.run(go(None));asyncio.run(go(b'1'))
    assert enabled==[]


@pytest.mark.parametrize('change,stage',[
    (lambda rows:[replace(x,cik='9999999') for x in rows],'annual_diluted_eps'),
    (lambda rows:[replace(x,form='6-K') for x in rows],'annual_diluted_eps'),
    (lambda rows:[x for x in rows if x.concept!='Assets'],'latest_annual_reporting_period'),
    (lambda rows:[replace(x,unit='EUR') if x.concept=='Assets' else x for x in rows],'annual_reporting_currency'),
    (lambda rows:rows+[replace(rows[-1],unit='EUR')],'annual_reporting_currency'),
    (lambda rows:rows+[replace(rows[-1],end='2026-01-01')],'latest_annual_reporting_period'),
    (lambda rows:[replace(x,accession='0001234567-26-000002') if x.concept=='Assets' else x for x in rows],'annual_reporting_currency'),
    (lambda rows:[x for x in rows if x.end!='2024-12-31'],'annual_diluted_eps'),
])
def test_currency_latest_period_identity_and_source_pair_gaps_are_not_filled(enabled,monkeypatch,change,stage):
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:change(records()))
    r=post().json();assert not r['available'] and r['stage']==stage
    assert r['source_claims']==[] and r['evidence_references']==[]


def test_wrong_future_and_missing_issuer_sources_are_sanitized(enabled,monkeypatch):
    from app.services.issuer_identity import Directory
    monkeypatch.setattr(svc,'_load_directory',lambda:Directory({},{}))
    assert post().json()['stage']=='issuer_identity' and enabled==[]
    def fail():raise RuntimeError('CANARY provider diagnostic')
    monkeypatch.setattr(svc,'_load_directory',fail)
    r=post();assert r.json()['stage']=='source_unavailable' and 'CANARY' not in r.text


def test_as_of_excludes_later_restated_rows_and_does_not_mutate_inputs(enabled,monkeypatch):
    rows=records();later=replace(rows[1],value=999,filed='2026-04-01')
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:[*rows,later])
    r=post().json();assert r['available'] and r['scenario']['source_eps']['value']=='5'
    assert rows[1].value==5


def test_distinct_users_and_requests_cannot_share_assumed_prices(enabled):
    a=payload();b=deepcopy(a);b['assumptions']['price']['value']='225'
    first=post(a,uid='owner-a').json();second=post(b,uid='owner-b').json()
    assert first['scenario']['supplied_assumptions']['price']['value']=='100'
    assert second['scenario']['supplied_assumptions']['price']['value']=='225'
    assert len(enabled)==2
    assert 'owner-a' not in json.dumps(second) and 'owner-b' not in json.dumps(first)


def test_application_implementation_does_not_depend_on_validation_package():
    from pathlib import Path
    for path in ('conditional_valuation_math.py','source_anchored_valuation.py','earnings_recovery_scenario.py','conditional_valuation_service.py'):
        text=(Path('app/services')/path).read_text()
        assert 'from validation.' not in text and 'import validation.' not in text


def test_current_directory_does_not_authorize_historical_scenario_identity(enabled):
    p=payload();p['assumptions']['scenario_as_of']='2026-03-01'
    assert post(p).status_code==400 and enabled==[]


def test_conflicting_official_directory_symbol_is_not_resolved_by_last_row(enabled,monkeypatch):
    from app.services.issuer_identity import parse_directory
    directory=parse_directory({'a':{'ticker':'ZQXB','title':'Issuer A','cik_str':1234567},
                               'b':{'ticker':'ZQXB','title':'Issuer B','cik_str':9999999}})
    monkeypatch.setattr(svc,'_load_directory',lambda:directory)
    assert post().json()['stage']=='issuer_identity' and enabled==[]


def test_scenario_dates_use_utc_even_when_local_calendar_is_previous_day(enabled,monkeypatch):
    from app.services import source_anchored_valuation as source, earnings_recovery_scenario as recovery_module
    class PreviousLocalDate(date):
        @classmethod
        def today(cls):
            return cls(2026,3,1)
    monkeypatch.setattr(source,'date',PreviousLocalDate)
    monkeypatch.setattr(recovery_module,'date',PreviousLocalDate)
    assert post().json()['available']
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',lambda *a,**kw:records(-2))
    assert post(payload(True)).json()['available']
