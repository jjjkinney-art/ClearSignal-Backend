"""Offline normal-pipeline replay; requires retained PR314 results ZIP and new output."""

def main():
    import sys,socket
    socket.has_ipv6=False
    blocked=[]
    def guard(event,args):
        if event.startswith('socket.') and not (event=='socket.__new__' and args[1]==socket.AF_UNIX):
            blocked.append(event)
            raise RuntimeError('external network forbidden in retained replay')
    sys.addaudithook(guard)
    sys.path[:0]=['.','tests']
    import json,hashlib,zipfile,threading
    from pathlib import Path
    from contextlib import redirect_stdout,redirect_stderr
    from io import StringIO
    import httpx,pytest
    from app.services import verified_sec_metric_service as metrics,router_service as router
    from app.providers import sec_client
    from app.schemas import CompanyContext
    from test_source_evidence_latency import isolated_pipeline
    real_fetch=metrics.fetch_verified_metric_evidence
    expected={'ASML':'28be6fd0f5608350ec396ae5d5097e45da95f4f29ad3fbd19aac328a15cce3d4',
              'NPK':'0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f'}
    with zipfile.ZipFile(sys.argv[1]) as z:
        sums=json.loads(z.read('SHA256SUMS.json'))
        assert all(hashlib.sha256(z.read(n)).hexdigest()==h for n,h in sums.items())
        bodies={t:z.read('capture/'+t.lower()+'-facts.json') for t in expected}
        for t,b in bodies.items():
            receipt=json.loads(z.read('capture/'+t.lower()+'-facts.json.receipt.json'))
            assert hashlib.sha256(b).hexdigest()==expected[t]==receipt['body_sha256']
            assert len(b)==receipt['body_bytes']
    ciks={'ASML':'937966','NPK':'80172'}
    calls=[]
    def saved_get(url,**kwargs):
        ticker=next((t for t,c in ciks.items() if url==f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(c):010d}.json'),None)
        assert ticker is not None,'Unexpected source URL'
        calls.append(url)
        return httpx.Response(200,content=bodies[ticker],request=httpx.Request('GET',url))
    results=[]
    with pytest.MonkeyPatch.context() as mp:
        model_calls=isolated_pipeline.__wrapped__(mp)
        mp.setattr(metrics,'fetch_verified_metric_evidence',real_fetch)
        mp.setattr(metrics,'_load_ticker_cik_map',lambda:ciks)
        mp.setattr(router._sec_provider,'_load_ticker_cik_map',lambda:ciks)
        mp.setattr(sec_client.requests,'get',saved_get)
        cases=[('ASML','basic','EUR','attributed','24.73'),
               ('ASML','diluted','EUR','attributed','24.71'),
               ('NPK','basic','USD','attributed','4.63'),
               ('NPK','diluted','USD','insufficient_claim_evidence',None),
               ('NPK','basic and diluted','USD','partial','4.63'),
               ('ASML','basic','USD','insufficient_claim_evidence',None)]
        for ticker,basis,currency,status,value in cases:
            question=f'What is the latest annual {currency} {basis} EPS for {ticker}?'
            workers=set(threading.enumerate())
            with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
                response=router._run_investment_pipeline(CompanyContext(ticker=ticker,company_name=ticker),
                    question,'retained-annual-eps',side_effects_enabled=False,as_of='2026-10-20')
            for worker in threading.enumerate():
                if worker not in workers and worker.name.startswith('ThreadPoolExecutor-'):
                    worker.join(5)
                    assert not worker.is_alive()
            data=response.model_dump(mode='json');source=data['answer']['source_answer']
            assert source['status']==status and data['routing']['response_mode']=='source_evidence'
            assert data['answer']['investment_thesis']['confidence_score']==0
            assert not model_calls
            refs={r['id'] for r in data['answer']['evidence_references']}
            assert all(c['reference_id'] in refs for c in source['claims'])
            if value:
                numbers=data['answer']['investment_thesis']['quantitative_claims']
                assert str(numbers[0]['raw_value'])==value and numbers[0]['currency']==currency
                assert numbers[0]['period_end']=='2025-12-31'
            else: assert not source['claims']
            if basis=='basic and diluted':assert source['unanswered_parts']==['annual diluted EPS']
            results.append({'ticker':ticker,'basis':basis,'currency':currency,'question':question,'response':data})
    assert not blocked and len(calls)==len(cases)
    report={'base_commit':'24b34570da63696de862daddbd776350cdd2cce6',
        'kind':'retained_companyfacts_normal_research_pipeline_offline_replay',
        'analysis_as_of':'2026-10-20','external_requests':0,'model_calls':0,'body_hashes':expected,
        'offline_pipeline_responses':len(results),'saved_source_replays':len(calls),'cases':results,
        'limitations':['Frozen CIK mapping, company context and other provider/profile results are injected.',
            'This is the normal research pipeline with persistence disabled, not live /ask HTTP/JWT acceptance.',
            'Original retained bodies/receipts are checked; new references are reconstructed offline.',
            'The EPS fact view supplies no valuation scenario, price, recommendation or decision threshold.',
            'Broad thesis composition, personalization/save-reopen and development/holdout acceptance remain open.',
            'Full historical run inventories are not independently revalidated here; no live approval is reused.']}
    with Path(sys.argv[2]).open('x') as f:json.dump(report,f,indent=2,allow_nan=False)
    print(json.dumps({'offline_pipeline_responses':len(results),'external_requests':0,'model_calls':0,'all_checks_passed':True}))

if __name__=='__main__':
    main()
