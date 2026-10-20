"""Offline retained NPK evidence -> final source gate for equivalent questions.

Arguments: retained PR292 capture directory, retained PR314 results ZIP, fresh
output JSON. Synthetic full-pipeline coverage is in the corresponding test file.
"""
def main():
    import sys,socket
    socket.has_ipv6=False
    blocked=[]
    def guard(event,args):
        if event.startswith('socket.') and not(event=='socket.__new__' and args[1]==socket.AF_UNIX):
            blocked.append(event);raise RuntimeError('external network forbidden in wording replay')
    sys.addaudithook(guard)
    sys.path[:0]=['.','tests']
    import json,hashlib,zipfile,ast,subprocess,re
    from pathlib import Path
    import httpx,pytest
    from app.providers import sec_client
    from app.schemas import InvestmentThesis
    from app.services import thesis_disclosures as disclosure,thesis_competition as competition,financial_thesis_foundation as foundation,verified_sec_metric_service as metrics
    from app.services.source_answer import apply_source_answer_gate
    from app.services.evidence_references import admit_evidence
    from app.services.issuer_identity import parse_directory
    from app.services.public_document_ingestion import _HTMLTextExtractor,PublicDocument
    from test_source_thesis_paraphrases import FORMS
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
        facts=z.read('capture/npk-facts.json');facts_receipt=json.loads(z.read('capture/npk-facts.json.receipt.json'))
    facts_hash=hashlib.sha256(facts).hexdigest()
    assert facts_hash==facts_receipt['body_sha256']=='0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f'
    assert len(facts)==facts_receipt['body_bytes']
    parser=_HTMLTextExtractor();parser.feed(body.decode('utf-8',errors='replace'))
    title,text,sections,_=parser.result(max_chars=360000,preserve_sec_risk=True,preserve_sec_business=True)
    doc=PublicDocument(url,url,'text/html',body_hash,len(body),title,text,sections,(),(),
        'html',True,'2026-10-15',publisher='SEC EDGAR',published_at='2026-03-13',document_type='10-K',
        source_type='regulatory_filing',source_tier='primary')
    base_commit='ba6c70df35c84b94ffab30c9419a416f13a63438'
    source=subprocess.check_output(['git','show',base_commit+':app/services/financial_thesis_foundation.py'],text=True)
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='is_broad_thesis_request')
    scope={'re':re};exec(compile(ast.Module(body=[node],type_ignores=[]),'<committed-baseline-scope>','exec'),scope)
    baseline=scope['is_broad_thesis_request'];candidate=foundation.is_broad_thesis_request
    reads=[]
    def saved_get(request_url,**kwargs):
        assert request_url=='https://data.sec.gov/api/xbrl/companyfacts/CIK0000080172.json'
        reads.append(request_url)
        return httpx.Response(200,content=facts,request=httpx.Request('GET',request_url))
    canonical_question='What is the investment thesis for NPK? Cite material claims.'
    results=[]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(metrics,'_load_ticker_cik_map',lambda:{'NPK':'80172'})
        mp.setattr('app.services.providers.sec_provider._load_ticker_cik_map',lambda:{'NPK':'80172'})
        mp.setattr('app.services.issuer_identity._load_directory',lambda:parse_directory({'0':{'ticker':'NPK','title':'NATIONAL PRESTO INDUSTRIES INC','cik_str':80172}}))
        mp.setattr(sec_client.requests,'get',saved_get)
        items=metrics.fetch_verified_metric_evidence('NPK',question=canonical_question)
        items+=disclosure.extract_business_descriptions(doc,ticker='NPK',cik='80172')
        items+=competition.extract_competition_descriptions(doc,ticker='NPK',cik='80172')
        risks=[];seen=set()
        for risk_scope in disclosure.RISK_TOPICS:
            for item in disclosure.extract_issuer_risk_evidence(doc,ticker='NPK',question=f'What operating risk affects {risk_scope}?',broad_thesis=True):
                value=disclosure.bound_thesis_risk(item,ticker='NPK')
                if value and value['quote'] not in seen:
                    seen.add(value['quote']);risks.append(item)
        risks.sort(key=lambda i:i.risk_disclosures[0]['start_offset']);items+=risks[:2]
        admitted,refs,integrity=admit_evidence(items,evaluated_at='2026-10-21')
        canonical_thesis=InvestmentThesis(ticker='NPK',company_name='National Presto Industries, Inc.')
        canonical=apply_source_answer_gate(canonical_thesis,canonical_question,admitted,references=refs)
        assert canonical['status']=='partial'
        for template in FORMS:
            question=template.format(ticker='NPK')+' Cite material claims.'
            row={'question':question}
            for name,selector in [('baseline',baseline),('candidate',candidate)]:
                mp.setattr(foundation,'is_broad_thesis_request',selector)
                thesis=InvestmentThesis(ticker='NPK',company_name='National Presto Industries, Inc.')
                result=apply_source_answer_gate(thesis,question,admitted,references=refs)
                if name=='candidate':
                    assert result==canonical and thesis.direct_answer==canonical_thesis.direct_answer
                    assert result['status']=='partial' and thesis.confidence_score==0
                    assert 'valuation and expected returns' in result['unanswered_parts']
                else:
                    assert result['status']=='attributed' and 'Financial thesis foundation (partial)' not in thesis.direct_answer
                row[name]={'status':result['status'],'claim_count':len(result['claims']),
                    'unanswered_parts':result['unanswered_parts'],
                    'result_sha256':hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                    'direct_answer':thesis.direct_answer}
            results.append(row)
    assert len(reads)==1 and not blocked
    report={'base_commit':base_commit,'date_auckland':'2026-10-21','kind':'retained_evidence_final_gate_wording_replay',
        'body_hashes':{'filing':body_hash,'facts':facts_hash},'archive_inventory_entries_verified':len(sums),
        'external_requests':0,'model_calls':0,'retained_fact_substitutions':1,'paraphrases_checked':len(results),
        'canonical_question':canonical_question,'canonical_source_answer':canonical,'canonical_direct_answer':canonical_thesis.direct_answer,
        'references':refs,'integrity':integrity,'results':results,
        'limitations':['This retained-data replay exercises the final source gate, not full HTTP/JWT/database/browser or fresh retrieval acceptance.',
            'Synthetic tests separately exercise normal pipeline retrieval selection and model skipping; retained facts/disclosures are assembled once for identical-evidence comparison.',
            'Directory identity, filing metadata and HTTP response are injected; hashes do not independently establish SEC origin or current-source availability.',
            'The baseline comparison substitutes only the committed broad-thesis selector, leaving current admission/composition unchanged.',
            'Broader competitive assessment, valuation, risk materiality, independent usefulness review and development/holdout acceptance remain unresolved.',
            'No live approval, new spending, capture or historical ledger write; full historical inventories are not revalidated here.']}
    with Path(sys.argv[3]).open('x') as out:json.dump(report,out,indent=2,allow_nan=False)
    print(json.dumps({'paraphrases_checked':len(results),'exact_canonical_matches':len(results),'external_requests':0,'model_calls':0}))

if __name__=='__main__':main()
