"""Retained PR292/PR314 -> ordinary ingestion -> evidence-led thesis overview.

Run from repository root: python SCRIPT CAPTURE_DIR FACTS_ZIP NEW_OUTPUT
No live source/model request or old execution-ledger resumption.
"""

def main():
    import sys, socket
    socket.has_ipv6 = False
    blocked = []
    def guard(event, args):
        if event.startswith('socket.') and not (event == 'socket.__new__' and args[1] == socket.AF_UNIX):
            blocked.append(event)
            raise RuntimeError('external network forbidden in segment-analysis replay')
    sys.addaudithook(guard)
    sys.path.insert(0, '.')
    import hashlib, json, subprocess, types, zipfile
    from pathlib import Path
    from types import SimpleNamespace
    import httpx, pytest
    from app.providers import sec_client
    from app.schemas import InvestmentThesis
    from app.services import thesis_disclosures as disclosures, verified_sec_metric_service as metrics
    from app.services.evidence_references import admit_evidence
    from app.services.issuer_identity import parse_directory
    from app.services.source_answer import apply_source_answer_gate
    from app.services import public_document_ingestion as ingestion, segment_financial_context as segment_service
    from app.providers import sec_segment_facts as segment_parser
    capture, output = Path(sys.argv[1]), Path(sys.argv[3])
    if output.exists():
        raise FileExistsError('replay refuses an existing output')
    body = (capture / 'npk-filing.html').read_bytes()
    receipt = json.loads((capture / 'npk-filing.html.receipt.json').read_text())
    body_hash = hashlib.sha256(body).hexdigest()
    assert body_hash == receipt['body_sha256'] == '8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1'
    assert len(body) == receipt['body_bytes'] == 1404517
    url = 'https://www.sec.gov/Archives/edgar/data/80172/000143774926008214/npk20251231_10k.htm'
    assert receipt['url'] == url and receipt['media_type'] == 'text/html'
    with zipfile.ZipFile(sys.argv[2]) as archive:
        sums = json.loads(archive.read('SHA256SUMS.json'))
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest for name, digest in sums.items())
        facts = archive.read('capture/npk-facts.json')
        facts_receipt = json.loads(archive.read('capture/npk-facts.json.receipt.json'))
    facts_hash = hashlib.sha256(facts).hexdigest()
    assert facts_hash == facts_receipt['body_sha256'] == '0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f'
    assert len(facts) == facts_receipt['body_bytes']
    base = 'f10d8f7fdb08af95cec19a5e0acb49ec7d503f0e'
    def old_module(path, package):
        module = types.ModuleType(package + '._baseline_segment_analysis')
        module.__package__ = package
        source = subprocess.check_output(['git', 'show', base + ':' + path], text=True)
        exec(compile(source, '<committed-baseline:' + path + '>', 'exec'), module.__dict__)
        return module
    from app.services import financial_thesis_foundation as foundation
    baseline_foundation = old_module('app/services/financial_thesis_foundation.py', 'app.services')
    candidate_foundation = foundation.build_financial_foundation
    from app.services import segment_product_context as products
    candidate_product_producer = products.extract_segment_products
    from app.services import deposit_impairment_context as impairments
    candidate_impairment_producer = impairments.extract_deposit_impairment
    fact_reads, document_reads = [], []
    def saved_get(request_url, **kwargs):
        assert request_url == 'https://data.sec.gov/api/xbrl/companyfacts/CIK0000080172.json'
        fact_reads.append(request_url)
        return httpx.Response(200, content=facts, request=httpx.Request('GET', request_url))
    class SavedResponse:
        headers = {'Content-Type': 'text/html'}
        encoding = 'utf-8'
        status_code = 200
        def raise_for_status(self): pass
        def iter_content(self, chunk_size=65536):
            for start in range(0, len(body), chunk_size): yield body[start:start + chunk_size]
        def close(self): pass
    def saved_document(request_url, **kwargs):
        assert request_url == url
        document_reads.append(request_url)
        return SavedResponse()
    def saved_http(request_url, **kwargs):
        return saved_document(request_url, **kwargs) if request_url == url else saved_get(request_url, **kwargs)
    question = 'What is the investment thesis for NPK? Cite material claims.'
    results = {}
    producer_proofs = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(metrics, '_load_ticker_cik_map', lambda: {'NPK': '80172'})
        patch.setattr('app.services.providers.sec_provider._load_ticker_cik_map', lambda: {'NPK': '80172'})
        patch.setattr('app.services.issuer_identity._load_directory', lambda: parse_directory({
            '0': {'ticker': 'NPK', 'title': 'NATIONAL PRESTO INDUSTRIES INC', 'cik_str': 80172}}))
        patch.setattr(sec_client.requests, 'get', saved_http)
        patch.setattr(disclosures.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
            SimpleNamespace(url=url, timestamp='2026-03-13', document_type='10-K')])
        patch.setattr(ingestion.requests, 'get', saved_http)
        patch.setattr(ingestion.socket, 'getaddrinfo', lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
        financial = metrics.fetch_verified_metric_evidence('NPK', question=question)
        for name in ('baseline', 'candidate'):
            items = disclosures.fetch_thesis_disclosures('NPK', question=question)
            if name == 'candidate':
                producer_proofs = [item.impairment_disclosures[0] for item in items if item.impairment_disclosures]
            segments = [item for item in items if item.segment_disclosures]
            admitted, refs, integrity = admit_evidence(financial + items, evaluated_at='2026-10-22')
            thesis = InvestmentThesis(ticker='NPK', company_name='National Presto Industries, Inc.')
            patch.setattr(foundation, 'build_financial_foundation', baseline_foundation.build_financial_foundation if name == 'baseline' else candidate_foundation)
            result = apply_source_answer_gate(thesis, question, admitted, references=refs)
            assert result['status'] == 'partial' and thesis.confidence_score == 0
            assert 'business model completeness' in result['unanswered_parts']
            assert 'valuation and expected returns' in result['unanswered_parts']
            results[name] = {'source_answer': result, 'direct_answer': thesis.direct_answer,
                             'segment_disclosures': [item.segment_disclosures[0] for item in segments],
                             'references': refs, 'integrity': integrity}
    before, after = results['baseline'], results['candidate']
    assert len(before['segment_disclosures']) == len(after['segment_disclosures']) == 1
    archived = json.loads(Path('docs/DEPOSIT_IMPAIRMENT_REPLAY_20261023.json').read_text())
    assert before == archived['results']['candidate']
    value = after['segment_disclosures'][0]
    rows = value['segment_context']['segments']
    assert [(r['label'], r['revenue_usd'], r['operating_income_usd']) for r in rows] == [
        ('Housewares / Small Appliance', 95604000, -9292000),
        ('Defense', 405937000, 58383000), ('Safety', 1983000, -8850000)]
    assert all(r['start'] == '2025-01-01' and r['end'] == '2025-12-31' for r in rows)
    assert value['proof']['allocation'] in after['direct_answer']
    assert value['segment_context']['currency'] == 'USD'
    assert before['source_answer']['claims'] == after['source_answer']['claims']
    assert before['references'] == after['references']
    assert before['segment_disclosures'] == after['segment_disclosures']
    assert before['integrity'] == after['integrity']
    for key in ('unanswered_parts','business_context_coverage'):
        assert before['source_answer'][key] == after['source_answer'][key]
    assert len(before['source_answer']['claims']) == len(after['source_answer']['claims']) == 14
    old_inf, new_inf = before['source_answer']['inferences'], after['source_answer']['inferences']
    assert len(old_inf) == len(new_inf)
    for old, new in zip(old_inf, new_inf):
        if old.get('metric') == 'operating cash flow':
            assert old['signal'] == 'supporting' and new['signal'] == 'context_only'
            assert old['reference_ids'] == new['reference_ids']
        else:
            assert old == new
    opening = after['direct_answer'].split('Positive, rising reported comparisons:')[0]
    assert 'Defense: external sales $405,937,000, operating profit $58,383,000' in opening
    assert 'Housewares / Small Appliance: external sales $95,604,000, operating loss $9,292,000' in opening
    assert '[E11]' in opening and '[E14]' in opening
    assert 'neither persistence nor the causes of later consolidated results' in opening
    assert 'operating cash flow [E4]' not in after['direct_answer']
    impairment = after['source_answer']['claims'][-1]
    assert impairment['claim_kind'] == 'issuer_deposit_impairment_context'
    context = impairment['impairment_context']
    assert context['measurement']['amount_usd'] == 2701000
    assert context['measurement']['scope'] == 'consolidated_expense'
    assert context['measurement']['duplicate_presentations_not_added'] is True
    assert context['event']['segment_context'] == 'Housewares/Small Appliances'
    assert context['event']['segment_measurement_established'] is False
    assert context['event']['recovery_assessment'] == 'management_deems_unlikely'
    assert context['event']['bankruptcy_filing_date'] == '2025-05-29'
    assert impairment['document_ref']['quote'] in after['direct_answer']
    assert impairment['reference_id'] == 'E14'
    assert len(fact_reads) == 1 and len(document_reads) == 2 and not blocked
    report = {'base_commit': base, 'kind': 'retained_ingestion_and_final_gate_thesis_overview',
              'date_auckland': '2026-10-23', 'body_hashes': {'filing': body_hash, 'facts': facts_hash},
              'archive_inventory_entries_verified': len(sums), 'external_requests': 0, 'model_calls': 0,
              'retained_fact_substitutions': 1, 'retained_document_substitutions': 2,
              'question': question, 'results': results, 'candidate_impairment_disclosures': producer_proofs,
              'limitations': ['Ordinary ingestion/disclosure retrieval and final composition execute with injected discovery, DNS and retained HTTP responses. No fresh-source, HTTP/JWT, persistence or browser acceptance.',
                             'Committed PR336 financial foundation versus candidate with identical current ingestion and admission. Baseline exactly reproduces PR335 archived candidate. All fourteen claims and references remain identical; only the cash-flow interpretation changes, alongside the new evidence-led prose overview.',
                             'Single consolidated expense with agreeing income/cash-flow presentations and complete dated management event. Narrative segment context is not a segment measurement; no double-counting, new cash payment, certain recovery outcome, recurrence or complete profit bridge follows.',
                             'Raw-source hash/receipt consistency does not establish independent origin authenticity or present availability.',
                             'Exposed development evidence, not independent usefulness review or development/holdout launch acceptance. No new capture, provider/model call, spending, old-ledger resumption or activation.']}
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'claims_before': 14, 'claims_after': 14, 'previous_claims_preserved': 14,
                      'all_previous_reference_ids_preserved': True, 'cash_flow_signal': 'context_only',
                      'external_requests': 0, 'model_calls': 0}))


if __name__ == '__main__':
    main()
