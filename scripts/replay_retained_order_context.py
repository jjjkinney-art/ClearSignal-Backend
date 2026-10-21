"""Retained PR292/PR314 -> ordinary disclosure retrieval -> final source gate.

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
            raise RuntimeError('external network forbidden in order-context replay')
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
    from app.services.public_document_ingestion import _HTMLTextExtractor, PublicDocument
    from app.services.source_answer import apply_source_answer_gate
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
    parser = _HTMLTextExtractor()
    parser.feed(body.decode('utf-8', errors='replace'))
    title, text, sections, _ = parser.result(max_chars=360000, preserve_sec_risk=True, preserve_sec_business=True)
    doc = PublicDocument(url, url, 'text/html', body_hash, len(body), title, text, sections, (), (),
                         'html', True, '2026-10-15', publisher='SEC EDGAR', published_at='2026-03-13',
                         document_type='10-K', source_type='regulatory_filing', source_tier='primary')
    base = '1d1f0b7dfb0875b70f58e87497219114ecc57be2'
    source = subprocess.check_output(['git', 'show', base + ':app/services/thesis_disclosures.py'], text=True)
    baseline = types.ModuleType('app.services._baseline_order_disclosures')
    baseline.__package__ = 'app.services'
    exec(compile(source, '<committed-baseline-disclosures>', 'exec'), baseline.__dict__)
    fact_reads, document_reads = [], []
    def saved_get(request_url, **kwargs):
        assert request_url == 'https://data.sec.gov/api/xbrl/companyfacts/CIK0000080172.json'
        fact_reads.append(request_url)
        return httpx.Response(200, content=facts, request=httpx.Request('GET', request_url))
    def saved_document(request_url, **kwargs):
        assert request_url == url
        document_reads.append(request_url)
        return doc
    question = 'What is the investment thesis for NPK? Cite material claims.'
    results = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(metrics, '_load_ticker_cik_map', lambda: {'NPK': '80172'})
        patch.setattr('app.services.providers.sec_provider._load_ticker_cik_map', lambda: {'NPK': '80172'})
        patch.setattr('app.services.issuer_identity._load_directory', lambda: parse_directory({
            '0': {'ticker': 'NPK', 'title': 'NATIONAL PRESTO INDUSTRIES INC', 'cik_str': 80172}}))
        patch.setattr(sec_client.requests, 'get', saved_get)
        patch.setattr(disclosures.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
            SimpleNamespace(url=url, timestamp='2026-03-13', document_type='10-K')])
        patch.setattr(disclosures, 'fetch_public_document', saved_document)
        patch.setattr(baseline, 'fetch_public_document', saved_document)
        financial = metrics.fetch_verified_metric_evidence('NPK', question=question)
        for name, module in [('baseline', baseline), ('candidate', disclosures)]:
            items = module.fetch_thesis_disclosures('NPK', question=question)
            orders = [item for item in items if item.operating_disclosures]
            admitted, refs, integrity = admit_evidence(financial + items, evaluated_at='2026-10-21')
            thesis = InvestmentThesis(ticker='NPK', company_name='National Presto Industries, Inc.')
            result = apply_source_answer_gate(thesis, question, admitted, references=refs)
            assert result['status'] == 'partial' and thesis.confidence_score == 0
            assert 'business model completeness' in result['unanswered_parts']
            assert 'valuation and expected returns' in result['unanswered_parts']
            for item in orders:
                value = item.operating_disclosures[0]
                assert text[value['start_offset']:value['end_offset']] == value['quote']
            results[name] = {'source_answer': result, 'direct_answer': thesis.direct_answer,
                             'order_disclosures': [item.operating_disclosures[0] for item in orders],
                             'references': refs, 'integrity': integrity}
    before, after = results['baseline'], results['candidate']
    assert len(before['order_disclosures']) == 0 and len(after['order_disclosures']) == 1
    order = after['order_disclosures'][0]['order_context']
    assert order['scope'] == {'kind': 'named_segment', 'label': 'Defense'}
    assert order['observations'] == [
        {'as_of': '2025-12-31', 'reported_amount': '$1,747,809,000'},
        {'as_of': '2024-12-31', 'reported_amount': '$1,085,612,000'},
        {'as_of': '2023-12-31', 'reported_amount': '$564,005,000'}]
    assert order['currency_code'] is None and order['numeric_normalization_performed'] is False
    assert before['source_answer']['claims'] == after['source_answer']['claims'][:-1]
    assert before['references'] == after['references'][:-1]
    for key in ('unanswered_parts', 'business_context_coverage', 'inferences'):
        assert before['source_answer'][key] == after['source_answer'][key]
    assert len(before['source_answer']['claims']) == 9
    assert len(fact_reads) == 1 and len(document_reads) == 2 and not blocked
    report = {'base_commit': base, 'kind': 'retained_ordinary_disclosures_and_final_gate_order_context',
              'date_auckland': '2026-10-21', 'body_hashes': {'filing': body_hash, 'facts': facts_hash},
              'archive_inventory_entries_verified': len(sums), 'external_requests': 0, 'model_calls': 0,
              'retained_fact_substitutions': 1, 'retained_document_substitutions': 2,
              'question': question, 'results': results,
              'limitations': ['Ordinary disclosure retrieval uses injected discovery/document responses; final answer composition is real. No fresh-source, HTTP/JWT, persistence or browser acceptance.',
                             'Committed base disclosure retrieval versus candidate; current financial production, admission and final composition are shared.',
                             'Raw-source hash/receipt consistency does not establish independent origin authenticity or present availability.',
                             'Printed dollar amounts retain unknown currency code; no normalization, growth, revenue conversion, forecast or valuation is inferred.',
                             'Exposed development evidence, not independent usefulness review or development/holdout launch acceptance.']}
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'claims_before': 9, 'claims_after': 10, 'preserved_claims_and_references': True,
                      'scope': order['scope'], 'currency_code': None, 'external_requests': 0, 'model_calls': 0}))


if __name__ == '__main__':
    main()
