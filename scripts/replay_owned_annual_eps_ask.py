"""Offline retained PR314 bodies -> signed /ask -> owned save/reopen; no live I/O."""

def main():
    import sys,socket
    socket.has_ipv6=False
    blocked=[]
    def guard(event,args):
        if event.startswith('socket.') and not (event=='socket.__new__' and args[1]==socket.AF_UNIX):
            blocked.append(event)
            raise RuntimeError('external network forbidden in owned replay')
    sys.addaudithook(guard)
    sys.path[:0]=['.','tests']
    import asyncio,json,hashlib,zipfile,tempfile
    from pathlib import Path
    from contextlib import redirect_stdout,redirect_stderr
    from io import StringIO
    import httpx,pytest
    from app.providers import sec_client
    from app.services import verified_sec_metric_service as metrics
    from app.services.issuer_identity import parse_directory
    from test_owned_annual_eps_ask import owned_ask,conversation,reopen
    from test_conditional_valuation_account_boundary import boundary,approve,token,bearer,SUBJECT_B,EMAIL_B
    from test_source_evidence_latency import isolated_pipeline
    real_records=sec_client.get_company_fact_records_for_concept_units
    hashes={'ASML':'28be6fd0f5608350ec396ae5d5097e45da95f4f29ad3fbd19aac328a15cce3d4',
            'NPK':'0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f'}
    ciks={'ASML':'937966','NPK':'80172'}
    with zipfile.ZipFile(sys.argv[1]) as z:
        sums=json.loads(z.read('SHA256SUMS.json'))
        assert all(hashlib.sha256(z.read(n)).hexdigest()==h for n,h in sums.items())
        bodies={t:z.read('capture/'+t.lower()+'-facts.json') for t in hashes}
        for t,b in bodies.items():
            receipt=json.loads(z.read('capture/'+t.lower()+'-facts.json.receipt.json'))
            assert hashlib.sha256(b).hexdigest()==hashes[t]==receipt['body_sha256']
            assert len(b)==receipt['body_bytes']
    gets=[]
    def saved_get(url,**kwargs):
        t=next((t for t,c in ciks.items() if url==f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(c):010d}.json'),None)
        assert t is not None,'unexpected URL'
        gets.append(url)
        return httpx.Response(200,content=bodies[t],request=httpx.Request('GET',url))
    async def run(mp,tmp):
        account_gen=boundary.__wrapped__(mp,tmp)
        account=await anext(account_gen)
        models=isolated_pipeline.__wrapped__(mp)
        owned_gen=owned_ask.__wrapped__(account,models,mp)
        client,maker,_,models,_,_=await anext(owned_gen)
        results=[]
        try:
            mp.setattr(metrics,'get_company_fact_records_for_concept_units',real_records)
            mp.setattr(metrics,'_load_ticker_cik_map',lambda:ciks)
            mp.setattr('app.services.providers.sec_provider._load_ticker_cik_map',lambda:ciks)
            mp.setattr('app.services.issuer_identity._load_directory',lambda:parse_directory({
                '0':{'ticker':'ASML','title':'ASML HOLDING NV','cik_str':937966},
                '1':{'ticker':'NPK','title':'NATIONAL PRESTO INDUSTRIES INC','cik_str':80172}}))
            mp.setattr(sec_client.requests,'get',saved_get)
            await approve(maker);await approve(maker,EMAIL_B)
            ha,hb=bearer(token()),bearer(token(SUBJECT_B,EMAIL_B))
            cases=[('ASML','basic','EUR','attributed','24.73'),
                   ('ASML','diluted','EUR','attributed','24.71'),
                   ('NPK','basic','USD','attributed','4.63'),
                   ('NPK','diluted','USD','insufficient_claim_evidence',None),
                   ('NPK','basic and diluted','USD','partial','4.63'),
                   ('ASML','basic','USD','insufficient_claim_evidence',None)]
            for index,(t,basis,currency,status,value) in enumerate(cases):
                created=await client.post('/research/conversations',json={'title':'Retained EPS replay','tickers':[t]},headers=ha)
                assert created.status_code==201
                cid=created.json()['id']
                payload={'company_name':t,'question':f'What is the latest annual {currency} {basis} EPS for {t}?',
                    'intent':'company_analysis','research_conversation_id':cid,'research_request_ref':f'retained-{index}'}
                response=await client.post('/ask',json=payload,headers=ha)
                assert response.status_code==200
                data=response.json();assert 'error' not in data
                assert data['routing']['response_mode']=='source_evidence'
                assert data['answer']['source_answer']['status']==status
                assert data['answer']['investment_thesis']['confidence_score']==0
                if value:assert str(data['answer']['investment_thesis']['quantitative_claims'][0]['raw_value'])==value
                saved=await reopen(client,cid,ha)
                assert [m['role'] for m in saved['messages']]==['user','assistant']
                assert saved['messages'][1]['displayed_snapshot']['response']==data
                assert saved['messages'][1]['text']==data['answer']['investment_thesis']['direct_answer']
                before=len(gets)
                retry=await client.post('/ask',json=payload,headers=ha)
                assert retry.headers['x-research-turn-replayed']=='true'
                assert retry.json()==data and len(gets)==before
                assert (await client.get('/research/conversations/'+cid,headers=hb)).status_code==404
                assert len(gets)==before and not models
                results.append({'ticker':t,'basis':basis,'currency':currency,'http_status':response.status_code,
                    'exact_display_snapshot_preserved':True,'assistant_text_matches_display':True,
                    'other_owner_reopen_status':404,'completed_retry_exact_no_fetch':True,'response':data})
            assert len(gets)==6 and not models and not blocked
        finally:
            await owned_gen.aclose()
            await account_gen.aclose()
        return results
    with tempfile.TemporaryDirectory(prefix='owned-eps-offline-') as tmp, pytest.MonkeyPatch.context() as mp:
        with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
            cases=asyncio.run(run(mp,Path(tmp)))
    report={'base_commit':'d1ed1fcac959f52d71b67cc5022da9dcfd7392b7',
        'kind':'offline_retained_body_signed_ask_owned_save_reopen',
        'archive_hashes_verified':len(sums),'body_hashes':hashes,'external_requests':0,'model_calls':0,
        'saved_source_substitutions':len(gets),'offline_completed_responses':len(cases),'cases':cases,
        'limitations':['Local invented HS256 JWT keys and beta accounts; no real Supabase/provider authentication or production environment acceptance.',
            'Directory identity and unrelated provider/profile results are injected; retained Company Facts bytes use the real parser and research pipeline.',
            'Disposable SQLite persists exact emitted response snapshots; production database/migrations/browser UI are not exercised.',
            'Broader thesis/decision-threshold completeness, inferred personalization and benchmark adjudication remain open.',
            'No capture approval is reused; historical ledgers remain untouched and are not independently revalidated here.']}
    with Path(sys.argv[2]).open('x') as f:json.dump(report,f,indent=2,allow_nan=False)
    print(json.dumps({'offline_responses':len(cases),'exact_snapshot_matches':len(cases),
        'foreign_owner_denials':len(cases),'completed_retry_exact_no_fetch':len(cases),'external_requests':0,'model_calls':0}))

if __name__=='__main__':
    main()
