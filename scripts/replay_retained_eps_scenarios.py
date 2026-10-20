"""Offline retained-body application replay; never dispatches provider requests."""

def main():
    import sys,socket
    socket.has_ipv6=False
    blocked=[]
    def guard(event,args):
        if event.startswith('socket.') and not (event=='socket.__new__' and args[1]==socket.AF_UNIX):
            blocked.append(event)
            raise RuntimeError('external network forbidden in retained replay')
    sys.addaudithook(guard)
    sys.path.insert(0,'.')
    import asyncio,threading,json,hashlib,zipfile
    from copy import deepcopy
    from datetime import date
    from decimal import Decimal,localcontext
    from unittest.mock import patch
    import httpx
    from fastapi import FastAPI
    from app.config import settings
    from app.services import conditional_valuation_service as svc
    from app.providers import sec_client
    from app.services.issuer_identity import parse_directory
    from app.routers.conditional_valuation import router

    AS_OF='2026-10-20'
    BODIES={'ASML':'28be6fd0f5608350ec396ae5d5097e45da95f4f29ad3fbd19aac328a15cce3d4',
            'NPK':'0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f'}
    CIKS={'ASML':937966,'NPK':80172}
    archive=sys.argv[1]
    with zipfile.ZipFile(archive) as z:
        inventory=json.loads(z.read('SHA256SUMS.json'))
        assert all(hashlib.sha256(z.read(n)).hexdigest()==h for n,h in inventory.items())
        bodies={t:z.read('capture/'+t.lower()+'-facts.json') for t in BODIES}
        receipts={t:json.loads(z.read('capture/'+t.lower()+'-facts.json.receipt.json')) for t in BODIES}
    for t,b in bodies.items():
        assert hashlib.sha256(b).hexdigest()==BODIES[t]==receipts[t]['body_sha256']
        assert len(b)==receipts[t]['body_bytes']

    calls=[]
    def saved_get(url,**kwargs):
        ticker=next((t for t,c in CIKS.items() if url==f'https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json'),None)
        assert ticker is not None,'Unexpected source URL'
        calls.append({'ticker':ticker,'url':url})
        r=httpx.Response(200,content=bodies[ticker],headers={'content-type':'application/json'},request=httpx.Request('GET',url))
        return r

    def operand(value,unit):
        return {'value':value,'unit':unit,'provenance':{'kind':'user_assumption','reference':'Invented offline demonstration, not market observation or forecast'}}
    def assumptions(ticker,basis,currency,mode):
        a={'mode':mode,'scenario_as_of':AS_OF,'distributions':'excluded',
           'price_per_underlying_common_share':True,'price':operand('100',currency+'/share'),
           'exit_pe':operand('20','x'),'horizon':operand(2,'years'),
           'eps_basis':{'issuer':ticker,'currency':currency,'accounting':'gaap','adjustment_definition':'none',
           'share_basis':basis,'period_basis':'fiscal_year','earnings_scope':'total_operations',
           'split_basis':'User assumes identical unconverted underlying common-share basis'}}
        if mode=='evaluate_growth_scenario':a['eps_growth_rate']=operand('0','annual_fraction')
        elif mode=='solve_required_earnings_growth':a['annual_price_return_rate']=operand('0','annual_fraction')
        else:
            a['target_eps']=operand('4',currency+'/shares')
            a['target_fiscal_period']={'start':'2027-01-01','end':'2027-12-31'}
        return a

    def post(payload,uid='offline-owner'):
        app=FastAPI();app.include_router(router)
        @app.middleware('http')
        async def auth(request,call_next):
            request.state.user_id=uid; request.state.admission_denied=False
            return await call_next(request)
        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://test.invalid') as client:
                return await client.post('/research/valuation-scenarios',json=payload)
        before=set(threading.enumerate())
        try:return asyncio.run(go())
        finally:
            workers=[t for t in threading.enumerate() if t not in before and t.name=='AnyIO worker thread']
            for t in workers:t.join(5)
            assert not any(t.is_alive() for t in workers)

    results=[]
    with patch.object(settings,'conditional_valuation_scenarios_enabled',True), patch.object(settings,'enable_data_retrieval',True), \
         patch.object(svc,'_current_date',lambda:date.fromisoformat(AS_OF)), \
         patch.object(svc,'_load_directory',lambda:parse_directory({str(i):{'ticker':t,'title':'Injected frozen registry identity '+t,'cik_str':c} for i,(t,c) in enumerate(CIKS.items())})), \
         patch.object(sec_client.requests,'get',saved_get):
        modes=['evaluate_growth_scenario','solve_required_earnings_growth','evaluate_earnings_recovery_scenario']
        combinations=[('ASML','basic','EUR','24.73'),('ASML','diluted','EUR','24.71'),('NPK','basic','USD','4.63')]
        for ticker,basis,currency,value in combinations:
            for mode in modes:
                payload={'ticker':ticker,'assumptions':assumptions(ticker,basis,currency,mode)}; before=deepcopy(payload)
                response=post(payload); r=response.json()
                assert response.status_code==200 and response.headers['cache-control']=='no-store'
                if mode=='evaluate_earnings_recovery_scenario':
                    assert not r['available'] and r['stage']=='scenario_contract' and not r['source_claims'] and not r['evidence_references'],r
                    assert 'nonpositive annual EPS' in r['scenario']['reason']
                    results.append({'ticker':ticker,'basis':basis,'currency':currency,'mode':mode,'expected_gap':'positive_EPS_is_not_loss_recovery_context','response':r})
                    continue
                assert r['available'],r
                eps=r['scenario']['source_eps']
                assert eps['value']==value and eps['share_basis']==basis and eps['unit']==currency+'/shares'
                assert eps['period_end']=='2025-12-31' and eps['period_start']=='2025-01-01' and r['status']=='partial'
                expected_prior={('ASML','basic'):'19.25',('ASML','diluted'):'19.24',('NPK','basic'):'5.82'}[(ticker,basis)]
                assert str(r['source_claims'][1]['raw_value'])==expected_prior
                assert r['source_claims'][1]['period_end']=='2024-12-31'
                expected_form='20-F' if ticker=='ASML' else '10-K'
                expected_filed='2026-02-25' if ticker=='ASML' else '2026-03-13'
                assert eps['filed_at']==expected_filed and eps['document_type']==expected_form
                assert r['evidence_references'][0]['document_type']==expected_form
                assert r['evidence_references'][0]['url']==eps['document_ref']['url']
                assert not r['admitted'] and not r['launch_ready'] and not r['market_price_observed']
                assert not r['market_pe_verified'] and not r['fx_conversion_performed'] and not r['adr_conversion_performed']
                assert eps['reference_id'] in {ref['id'] for ref in r['evidence_references']}
                assert all(c['unit']==currency+'/shares' and c['currency']==currency for c in r['source_claims'])
                assert payload==before
                with localcontext() as ctx:
                    ctx.prec=50
                    values=r['scenario']['values']
                    if mode=='evaluate_growth_scenario':
                        expected=Decimal(value)*20/100
                        assert abs(Decimal(values['terminal_price_factor'])-expected)<Decimal('1e-25')
                    elif mode=='evaluate_earnings_recovery_scenario':
                        assert Decimal(values['assumed_terminal_price'])==80
                        assert Decimal(values['terminal_price_factor'])==Decimal('.8')
                    else:
                        expected=(Decimal(100)/(20*Decimal(value))).sqrt()-1
                        assert abs(Decimal(values['eps_growth_rate'])-expected)<Decimal('1e-25'),values
                results.append({'ticker':ticker,'basis':basis,'currency':currency,'mode':mode,'http_status':response.status_code,'cache_control':response.headers['cache-control'],'response':r})
        for ticker,basis,currency,stage in [('NPK','diluted','USD','latest_annual_reporting_period'),('ASML','diluted','USD','annual_diluted_eps'),('NPK','basic','EUR','annual_basic_eps')]:
            r=post({'ticker':ticker,'assumptions':assumptions(ticker,basis,currency,modes[0])}).json()
            assert not r['available'] and r['stage']==stage and not r['source_claims'] and not r['evidence_references'],r
            results.append({'ticker':ticker,'basis':basis,'currency':currency,'expected_gap':stage,'response':r})
        p={'ticker':'ASML','assumptions':assumptions('ASML','diluted','EUR',modes[0])}
        before=len(calls)
        with patch.object(settings,'conditional_valuation_scenarios_enabled',False):
            response=post(p); r=response.json();assert response.status_code==404 and len(calls)==before
        results.append({'case':'feature_off','response':r})
        response=post(p,uid=None);assert response.status_code==401 and len(calls)==before
        results.append({'case':'anonymous','http_status':response.status_code})
    assert not blocked,blocked
    report={'kind':'retained_body_offline_ASGI_application_replay','base_commit':'32584e354a6764e9db4015c32c41fe40c89b86fa',
            'analysis_as_of':AS_OF,'external_requests':0,'model_calls':0,'live_approvals_consumed_by_replay':0,
            'saved_provider_get_replays':calls,'body_hashes':BODIES,'body_lengths':{t:len(b) for t,b in bodies.items()},
            'archive_hashes_verified':len(inventory),'cases':results,
            'limitations':['UTC clock, directory identity and authenticated request state are injected for offline replay.',
            'Feature enabled only in process with restoration; production remains off.',
            'Hypothetical price, future EPS, exit multiple and rates are invented demonstrations, not market observations or forecasts.',
            'Real captured Company Facts bytes pass through the actual provider parser, producer, evidence reconstruction and ASGI scenario handler.',
            'Reference admission is a new offline reconstruction; it does not retroactively admit original capture diagnostics.',
            'Current identity, real JWT/session, share/class/split/price compatibility and financial adjudication remain unverified.',
            'No /ask composition, persistence, personalization, full-company benchmark or launch acceptance is established.',
            'Full historical run inventories were not independently revalidated in this checkout.']}
    with open(sys.argv[2],'x') as f:json.dump(report,f,indent=2,allow_nan=False)
    print(json.dumps({'cases':len(results),'successful_scenarios':6,'explicit_source_gaps':3,'positive_eps_recovery_rejections':3,'feature_and_auth_checks':2,'external_requests':0,'body_hashes_unchanged':True}))


if __name__ == "__main__":
    main()
