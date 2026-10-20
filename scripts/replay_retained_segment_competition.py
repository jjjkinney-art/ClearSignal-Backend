"""Offline PR292 filing + PR314 facts replay through the core-thesis pipeline.

Arguments: retained PR292 capture directory, retained PR314 results ZIP, new
output JSON. Fixed body hashes; no live source requests or ledger mutation.
"""

def main():
    import sys,socket
    socket.has_ipv6=False
    blocked=[]
    def guard(event,args):
        if event.startswith('socket.') and not(event=='socket.__new__' and args[1]==socket.AF_UNIX):
            blocked.append(event)
            raise RuntimeError('external network forbidden in retained segment replay')
    sys.addaudithook(guard)
    sys.path[:0]=['.','tests']
    import json,hashlib,zipfile,types,subprocess,threading
    from pathlib import Path
    from contextlib import redirect_stdout,redirect_stderr
    from io import StringIO
    import httpx,pytest
    from app.services import thesis_competition,thesis_disclosures,router_service as router,verified_sec_metric_service as metrics
    from app.services.issuer_identity import parse_directory
    from app.services.public_document_ingestion import _HTMLTextExtractor,PublicDocument
    from app.schemas import CompanyContext
    from app.providers import sec_client
    from test_source_evidence_latency import isolated_pipeline
    capture=Path(sys.argv[1]);body=(capture/'npk-filing.html').read_bytes()
    receipt=json.loads((capture/'npk-filing.html.receipt.json').read_text())
    body_hash=hashlib.sha256(body).hexdigest()
    assert body_hash==receipt['body_sha256']=='8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1'
    assert len(body)==receipt['body_bytes']==1404517
    url='https://www.sec.gov/Archives/edgar/data/80172/000143774926008214/npk20251231_10k.htm'
    assert receipt['url']==url and receipt['media_type']=='text/html'
    with zipfile.ZipFile(sys.argv[2]) as z:
        sums=json.loads(z.read('SHA256SUMS.json'))
        assert all(hashlib.sha256(z.read(n)).hexdigest()==h for n,h in sums.items())
        facts=z.read('capture/npk-facts.json')
        fact_receipt=json.loads(z.read('capture/npk-facts.json.receipt.json'))
    fact_hash=hashlib.sha256(facts).hexdigest()
    assert fact_hash==fact_receipt['body_sha256']=='0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f'
    assert len(facts)==fact_receipt['body_bytes']
    parser=_HTMLTextExtractor();parser.feed(body.decode('utf-8',errors='replace'))
    title,text,sections,links=parser.result(max_chars=360000,preserve_sec_risk=True,preserve_sec_business=True)
    doc=PublicDocument(url,url,'text/html',body_hash,len(body),title,text,sections,(),(),
        'html',True,'2026-10-15',publisher='SEC EDGAR',published_at='2026-03-13',document_type='10-K',
        source_type='regulatory_filing',source_tier='primary')
    # Load only the committed extractor source to reproduce the old selection;
    # no baseline files are modified and no external code is downloaded.
    base_source=subprocess.check_output(['git','show','daa095f3c1038be2a228d9b958cbcbf07e3e1f3e:app/services/thesis_competition.py'],text=True)
    base=types.ModuleType('app.services._retained_segment_baseline');base.__package__='app.services'
    exec(compile(base_source,'<committed-baseline-competition>','exec'),base.__dict__)
    real_metrics=metrics.fetch_verified_metric_evidence
    results=[];gets=[]
    def saved_get(request_url,**kwargs):
        assert request_url=='https://data.sec.gov/api/xbrl/companyfacts/CIK0000080172.json'
        gets.append(request_url)
        return httpx.Response(200,content=facts,request=httpx.Request('GET',request_url))
    with pytest.MonkeyPatch.context() as mp:
        models=isolated_pipeline.__wrapped__(mp)
        mp.setattr(metrics,'fetch_verified_metric_evidence',real_metrics)
        mp.setattr(metrics,'_load_ticker_cik_map',lambda:{'NPK':'80172'})
        mp.setattr(router._sec_provider,'_load_ticker_cik_map',lambda:{'NPK':'80172'})
        mp.setattr('app.services.issuer_identity._load_directory',lambda:parse_directory({'0':{'ticker':'NPK','title':'NATIONAL PRESTO INDUSTRIES INC','cik_str':80172}}))
        mp.setattr(sec_client.requests,'get',saved_get)
        question='What is the investment thesis for National Presto Industries, Inc., what supports it, and what could invalidate it? Distinguish reported facts from inference and cite material claims.'
        for label,extractor in [('baseline',base),('candidate',thesis_competition)]:
            business=thesis_disclosures.extract_business_descriptions(doc,ticker='NPK',cik='80172')
            competition=extractor.extract_competition_descriptions(doc,ticker='NPK',cik='80172')
            risks=[];seen=set()
            for scope in thesis_disclosures.RISK_TOPICS:
                for risk in thesis_disclosures.extract_issuer_risk_evidence(doc,ticker='NPK',
                        question=f'What operating risk affects {scope}?',broad_thesis=True):
                    value=thesis_disclosures.bound_thesis_risk(risk,ticker='NPK')
                    if value and value['quote'] not in seen:
                        seen.add(value['quote']);risks.append(risk)
            risks.sort(key=lambda item:item.risk_disclosures[0]['start_offset'])
            mp.setattr(thesis_disclosures,'fetch_thesis_disclosures',lambda *a,_items=business+competition+risks[:2],**kw:_items)
            workers=set(threading.enumerate())
            with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
                response=router._run_investment_pipeline(CompanyContext(ticker='NPK',company_name='National Presto Industries, Inc.'),question,'retained-segment-'+label,side_effects_enabled=False)
            for worker in threading.enumerate():
                if worker not in workers and worker.name.startswith('ThreadPoolExecutor-'):
                    worker.join(5);assert not worker.is_alive()
            data=response.model_dump(mode='json');source=data['answer']['source_answer']
            assert source['status']=='partial' and data['routing']['response_mode']=='source_evidence'
            assert any('competitive position' in p for p in source['unanswered_parts'])
            assert 'valuation and expected returns' in source['unanswered_parts']
            admitted=[c for c in source['claims'] if c['claim_kind']=='issuer_competition_description']
            assert len(admitted)==(1 if label=='candidate' else 0)
            if admitted:
                claim,=admitted
                assert claim['competition_scope']=={'kind':'named_segment','label':'Defense'}
                value=competition[0].competition_disclosures[0]
                assert doc.text[value['start_offset']:value['end_offset']]==value['document_ref']['quote']==value['quote']
                ref=next(r for r in data['answer']['evidence_references'] if r['id']==claim['reference_id'])
                assert ref['url']==url and ref['section']=='Item 1. Business'
                assert 'not a company-wide competitive assessment' in data['answer']['investment_thesis']['direct_answer']
            assert not models and data['answer']['investment_thesis']['confidence_score']==0
            results.append({'selection':label,'competition_claims':len(admitted),'response':data})
    old_claims=results[0]['response']['answer']['source_answer']['claims']
    new_claims=results[1]['response']['answer']['source_answer']['claims']
    assert [(c['claim_kind'],c['claim']) for c in old_claims]==[
        (c['claim_kind'],c['claim']) for c in new_claims if c['claim_kind']!='issuer_competition_description']
    assert sum(c['claim_kind']=='issuer_disclosed_risk' for c in new_claims)==2
    assert sum(c['claim_kind']=='issuer_business_description' for c in new_claims)==1
    assert not blocked and len(gets)==2
    report={'base_commit':'daa095f3c1038be2a228d9b958cbcbf07e3e1f3e','analysis_date_auckland':'2026-10-21',
        'kind':'retained_named_segment_core_thesis_offline_replay','body_hashes':{'npk_filing':body_hash,'npk_facts':fact_hash},
        'external_requests':0,'model_calls':0,'retained_fact_reads':len(gets),'results':results,
        'limitations':['Retained body/receipt integrity is verified, not independent SEC origin authenticity or current-source availability.',
            'Filing metadata, directory and unrelated provider context are injected; application transport/HTTP/JWT/database/browser acceptance is not exercised.',
            'Only exposed development NPK material is replayed. No holdouts, fresh capture authority, ledger writes or live approvals.',
            'One disclosed segment competition basis is not company-wide competitive strength, materiality, a moat, valuation or launch acceptance.',
            'No full historical run inventory is independently revalidated here.']}
    with Path(sys.argv[3]).open('x') as output:json.dump(report,output,indent=2,allow_nan=False)
    print(json.dumps({'baseline_competition_claims':0,'candidate_competition_claims':1,'external_requests':0,'model_calls':0,'still_partial':True}))

if __name__=='__main__':main()
