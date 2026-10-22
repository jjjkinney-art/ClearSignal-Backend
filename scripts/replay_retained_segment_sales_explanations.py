"""Retained PR292/PR314 -> ordinary ingestion -> management-attributed sales explanation.

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
    base = '4ccaf6a7d20395177c9d5aa21d5b5adae8906f5d'
    def old_module(path, package):
        module = types.ModuleType(package + '._baseline_segment_analysis')
        module.__package__ = package
        source = subprocess.check_output(['git', 'show', base + ':' + path], text=True)
        exec(compile(source, '<committed-baseline:' + path + '>', 'exec'), module.__dict__)
        return module
    baseline_parser = old_module('app/providers/sec_segment_facts.py', 'app.providers')
    baseline_service = old_module('app/services/segment_financial_context.py', 'app.services')
    baseline_service.reconstruct = baseline_parser.reconstruct
    candidate_functions = (segment_parser.parse_segment_tables, segment_service.extract_segment_financial_context,
                           segment_service.bound_segment_financial_context)
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
            functions = ((baseline_parser.parse_segment_tables, baseline_service.extract_segment_financial_context,
                          baseline_service.bound_segment_financial_context) if name == 'baseline' else candidate_functions)
            patch.setattr(segment_parser, 'parse_segment_tables', functions[0])
            patch.setattr(segment_service, 'extract_segment_financial_context', functions[1])
            patch.setattr(segment_service, 'bound_segment_financial_context', functions[2])
            items = disclosures.fetch_thesis_disclosures('NPK', question=question)
            segments = [item for item in items if item.segment_disclosures]
            admitted, refs, integrity = admit_evidence(financial + items, evaluated_at='2026-10-22')
            thesis = InvestmentThesis(ticker='NPK', company_name='National Presto Industries, Inc.')
            result = apply_source_answer_gate(thesis, question, admitted, references=refs)
            assert result['status'] == 'partial' and thesis.confidence_score == 0
            assert 'business model completeness' in result['unanswered_parts']
            assert 'valuation and expected returns' in result['unanswered_parts']
            results[name] = {'source_answer': result, 'direct_answer': thesis.direct_answer,
                             'segment_disclosures': [item.segment_disclosures[0] for item in segments],
                             'references': refs, 'integrity': integrity}
    before, after = results['baseline'], results['candidate']
    assert len(before['segment_disclosures']) == len(after['segment_disclosures']) == 1
    archived = json.loads(Path('docs/SEGMENT_ANALYSIS_REPLAY_20261022.json').read_text())
    assert before == archived['results']['candidate']
    value = after['segment_disclosures'][0]
    rows = value['segment_context']['segments']
    assert [(r['label'], r['revenue_usd'], r['operating_income_usd']) for r in rows] == [
        ('Housewares / Small Appliance', 95604000, -9292000),
        ('Defense', 405937000, 58383000), ('Safety', 1983000, -8850000)]
    assert all(r['start'] == '2025-01-01' and r['end'] == '2025-12-31' for r in rows)
    assert value['proof']['allocation'] in after['direct_answer']
    assert value['segment_context']['currency'] == 'USD'
    assert before['source_answer']['claims'][:-1] == after['source_answer']['claims'][:-1]
    assert before['references'] == after['references']
    for key in ('unanswered_parts', 'business_context_coverage'):
        assert before['source_answer'][key] == after['source_answer'][key]
    assert len(before['source_answer']['claims']) == len(after['source_answer']['claims']) == 11
    assert before['source_answer']['inferences'] == after['source_answer']['inferences']
    calculation = after['source_answer']['inferences'][-1]
    assert calculation['kind'] == 'segment_table_calculation' and calculation['provenance'] == 'derived'
    assert calculation['analysis']['status'] == 'matched'
    assert [r['display_percent'] for r in calculation['analysis']['derived_ratios']] == ['19.0', '-9.7', '80.6', '14.4', '0.4', '-446.3']
    assert calculation['analysis']['totals']['revenue']['amount_usd'] == 503524000
    assert calculation['analysis']['totals']['operating_income']['amount_usd'] == 40241000
    explanation, = value['sales_explanations']
    assert explanation['label'] == 'Defense'
    assert (explanation['current_revenue_usd'], explanation['prior_revenue_usd'], explanation['change_usd']) == (405937000, 284025000, 121912000)
    assert explanation['quote'] in after['direct_answer']
    assert explanation['limitation'] in after['direct_answer']
    assert after['source_answer']['claims'][-1]['sales_explanations'] == value['sales_explanations']
    assert len(fact_reads) == 1 and len(document_reads) == 2 and not blocked
    report = {'base_commit': base, 'kind': 'retained_ingestion_and_final_gate_segment_sales_explanations',
              'date_auckland': '2026-10-22', 'body_hashes': {'filing': body_hash, 'facts': facts_hash},
              'archive_inventory_entries_verified': len(sums), 'external_requests': 0, 'model_calls': 0,
              'retained_fact_substitutions': 1, 'retained_document_substitutions': 2,
              'question': question, 'results': results,
              'limitations': ['Ordinary ingestion/disclosure retrieval and final composition execute with injected discovery, DNS and retained HTTP responses. No fresh-source, HTTP/JWT, persistence or browser acceptance.',
                             'Committed base segment parser/producer/binder versus candidate; current ordinary retrieval, financial production, admission and final composition are shared.',
                             'Raw-source hash/receipt consistency does not establish independent origin authenticity or present availability.',
                             'Segment USD units, scale, sign, periods and dimensions resolve from this retained XML. Exact segment-table totals reconciliation and labelled derived ratios only; management-attributed shipment explanation is not independently established causation, new orders or a future forecast. No consolidated-company exposure, standalone margin or valuation conclusion follows.',
                             'Exposed development evidence, not independent usefulness review or development/holdout launch acceptance.']}
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'claims_before': 11, 'claims_after': 11, 'previous_nonsegment_claims_preserved': 10, 'all_reference_ids_preserved': True,
                      'segments': rows, 'sales_explanation': explanation,
                      'currency_code': 'USD', 'external_requests': 0, 'model_calls': 0}))


if __name__ == '__main__':
    main()
