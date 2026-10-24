"""Retained PR292/PR314 -> ordinary ingestion -> evidence-linked operating research questions.

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
    base = 'afd74fc98159fd9ab368eeb8e045bf7aa70e0674'
    def old_module(path, package):
        module = types.ModuleType(package + '._baseline_segment_analysis')
        module.__package__ = package
        source = subprocess.check_output(['git', 'show', base + ':' + path], text=True)
        exec(compile(source, '<committed-baseline:' + path + '>', 'exec'), module.__dict__)
        return module
    from app.services import financial_thesis_foundation as foundation
    baseline_foundation = old_module('app/services/financial_thesis_foundation.py', 'app.services')
    candidate_foundation = foundation.build_financial_foundation
    from app.services import thesis_evidence_overview as overview
    baseline_overview = old_module('app/services/thesis_evidence_overview.py', 'app.services')
    candidate_overview = overview.render_bound_overview
    from app.services import segment_revenue_policy as policies
    candidate_policies = policies.extract_segment_revenue_policies
    from app.services import annual_cash_flow_context as cash
    candidate_cash = cash.extract_annual_cash_flow_context
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
    policy_proofs = []
    cash_proofs = []
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
            patch.setattr(policies, 'extract_segment_revenue_policies', candidate_policies)
            patch.setattr(cash, 'extract_annual_cash_flow_context', candidate_cash)
            items = disclosures.fetch_thesis_disclosures('NPK', question=question)
            if name == 'candidate':
                producer_proofs = [item.impairment_disclosures[0] for item in items if item.impairment_disclosures]
                policy_proofs = [item.revenue_policy_disclosures[0] for item in items if item.revenue_policy_disclosures]
                cash_proofs = [item.cash_flow_disclosures[0] for item in items if item.cash_flow_disclosures]
            segments = [item for item in items if item.segment_disclosures]
            admitted, refs, integrity = admit_evidence(financial + items, evaluated_at='2026-10-22')
            thesis = InvestmentThesis(ticker='NPK', company_name='National Presto Industries, Inc.')
            patch.setattr(foundation, 'build_financial_foundation', baseline_foundation.build_financial_foundation if name == 'baseline' else candidate_foundation)
            patch.setattr(overview, 'render_bound_overview', baseline_overview.render_bound_overview if name == 'baseline' else candidate_overview)
            result = apply_source_answer_gate(thesis, question, admitted, references=refs)
            assert result['status'] == 'partial' and thesis.confidence_score == 0
            assert 'business model completeness' in result['unanswered_parts']
            assert 'valuation and expected returns' in result['unanswered_parts']
            results[name] = {'source_answer': result, 'direct_answer': thesis.direct_answer,
                             'segment_disclosures': [item.segment_disclosures[0] for item in segments],
                             'references': refs, 'integrity': integrity}
    before, after = results['baseline'], results['candidate']
    archived = json.loads(Path('docs/ANNUAL_CASH_FLOW_REPLAY_20261024.json').read_text())
    assert before == archived['results']['candidate']
    for key in ('claims', 'unanswered_parts', 'business_context_coverage'):
        assert before['source_answer'][key] == after['source_answer'][key]
    assert before['references'] == after['references']
    assert before['integrity'] == after['integrity']
    assert before['segment_disclosures'] == after['segment_disclosures']
    previous_inferences = before['source_answer']['inferences']
    assert after['source_answer']['inferences'][:len(previous_inferences)] == previous_inferences
    questions = after['source_answer']['inferences'][len(previous_inferences):]
    assert [q['topic'] for q in questions] == ['contract_cost_exposure', 'annual_cash_conversion']
    assert questions[0]['segment_label'] == 'Defense'
    assert questions[0]['reference_ids'] == ['E11', 'E15']
    assert questions[1]['reference_ids'] == ['E17']
    assert all(q['causal_attribution_established'] is False and q['materiality_assessed'] is False for q in questions)
    opening = after['direct_answer'].split('Positive, rising reported comparisons:')[0]
    for research_question in questions:
        assert opening.count(research_question['text']) == 1
    for claim in after['source_answer']['claims']:
        assert after['direct_answer'].count(claim['claim']) == 1
    assert len(after['source_answer']['claims']) == 17
    assert len(fact_reads) == 1 and len(document_reads) == 2 and not blocked
    report = {'base_commit': base, 'kind': 'retained_ingestion_final_gate_operating_questions',
              'date_auckland': '2026-10-25', 'body_hashes': {'filing': body_hash, 'facts': facts_hash},
              'archive_inventory_entries_verified': len(sums), 'external_requests': 0, 'model_calls': 0,
              'retained_fact_substitutions': 1, 'retained_document_substitutions': 2,
              'question': question,
              'word_counts': {k: len(v['direct_answer'].split()) for k, v in results.items()},
              'results': results, 'added_research_questions': questions,
              'limitations': [
                  'Injected discovery/DNS and retained HTTP responses; no fresh-source, HTTP/JWT, persistence or signed-in acceptance.',
                  'Committed PR341 foundation/overview reproduce the archived candidate exactly. All seventeen claims, citations, prior inferences, integrity, coverage and gaps remain unchanged. Two research questions are added, not source facts or new directional signals.',
                  'Exact filing hash/URL/publication date and segment label are required for a contract/results link. This is document consistency, not independent authenticity or causal attribution.',
                  'Generic exposed NPK question is not the frozen core-thesis wording. No current ASML/ACHC rerun, independent usefulness score or development/holdout acceptance.',
                  'All twelve live approvals remain consumed. No new provider/model calls, spending, capture, old-ledger execution or activation.']}
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'claims_preserved': 17, 'research_questions_added': len(questions),
                      'word_counts': report['word_counts'], 'external_requests': 0, 'model_calls': 0}))


if __name__ == '__main__':
    main()
