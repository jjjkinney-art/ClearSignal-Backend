"""Offline PR292/PR314 bytes -> business producer/binder -> final source answer.

Usage: python scripts/replay_retained_segment_composition.py CAPTURE_DIR FACTS_ZIP NEW_OUTPUT
Run from repository root. No source/model requests or execution authority.
"""

def main():
    import sys
    import socket
    socket.has_ipv6 = False
    blocked = []
    def guard(event, args):
        if event.startswith('socket.') and not (event == 'socket.__new__' and args[1] == socket.AF_UNIX):
            blocked.append(event)
            raise RuntimeError('external network forbidden in segment replay')
    sys.addaudithook(guard)
    sys.path.insert(0, '.')
    import hashlib
    import json
    import subprocess
    import types
    import zipfile
    from pathlib import Path
    import httpx
    import pytest
    from app.providers import sec_client
    from app.schemas import InvestmentThesis
    from app.services import thesis_disclosures as disclosures, thesis_competition as competition
    from app.services import verified_sec_metric_service as metrics
    from app.services.evidence_references import admit_evidence
    from app.services.issuer_identity import parse_directory
    from app.services.public_document_ingestion import _HTMLTextExtractor, PublicDocument
    from app.services.source_answer import apply_source_answer_gate

    capture = Path(sys.argv[1])
    output = Path(sys.argv[3])
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
    base = '6c5d1e700f94350d57ac3b48755927a25d6e37e5'
    source = subprocess.check_output(['git', 'show', base + ':app/services/thesis_disclosures.py'], text=True)
    baseline = types.ModuleType('app.services._baseline_segment_disclosures')
    baseline.__package__ = 'app.services'
    exec(compile(source, '<committed-baseline-disclosures>', 'exec'), baseline.__dict__)
    original_binder = disclosures.bound_business_description
    reads = []
    def saved_get(request_url, **kwargs):
        assert request_url == 'https://data.sec.gov/api/xbrl/companyfacts/CIK0000080172.json'
        reads.append(request_url)
        return httpx.Response(200, content=facts, request=httpx.Request('GET', request_url))
    question = 'What is the investment thesis for NPK? Cite material claims.'
    results = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(metrics, '_load_ticker_cik_map', lambda: {'NPK': '80172'})
        patch.setattr('app.services.providers.sec_provider._load_ticker_cik_map', lambda: {'NPK': '80172'})
        patch.setattr('app.services.issuer_identity._load_directory', lambda: parse_directory({
            '0': {'ticker': 'NPK', 'title': 'NATIONAL PRESTO INDUSTRIES INC', 'cik_str': 80172}}))
        patch.setattr(sec_client.requests, 'get', saved_get)
        financial = metrics.fetch_verified_metric_evidence('NPK', question=question)
        competitive = competition.extract_competition_descriptions(doc, ticker='NPK', cik='80172')
        risks, seen = [], set()
        for scope in disclosures.RISK_TOPICS:
            for item in disclosures.extract_issuer_risk_evidence(doc, ticker='NPK',
                    question=f'What operating risk affects {scope}?', broad_thesis=True):
                value = disclosures.bound_thesis_risk(item, ticker='NPK')
                if value and value['quote'] not in seen:
                    seen.add(value['quote'])
                    risks.append(item)
        risks.sort(key=lambda item: item.risk_disclosures[0]['start_offset'])
        for name, module, binder in [('baseline', baseline, baseline.bound_business_description),
                                      ('candidate', disclosures, original_binder)]:
            patch.setattr(disclosures, 'bound_business_description', binder)
            business = module.extract_business_descriptions(doc, ticker='NPK', cik='80172')
            bound = [binder(item, ticker='NPK', cik='80172') for item in business]
            assert all(bound)
            for value in bound:
                assert text[value['start_offset']:value['end_offset']] == value['quote']
            admitted, refs, integrity = admit_evidence(financial + business + competitive + risks[:2], evaluated_at='2026-10-21')
            thesis = InvestmentThesis(ticker='NPK', company_name='National Presto Industries, Inc.')
            result = apply_source_answer_gate(thesis, question, admitted, references=refs)
            assert result['status'] == 'partial' and thesis.confidence_score == 0
            assert 'business model completeness' in result['unanswered_parts']
            assert 'competitive position' in result['unanswered_parts']
            assert 'valuation and expected returns' in result['unanswered_parts']
            results[name] = {'business_descriptions': bound, 'source_answer': result,
                             'direct_answer': thesis.direct_answer, 'references': refs, 'integrity': integrity}
    before, after = results['baseline'], results['candidate']
    assert len(before['business_descriptions']) == 1 and len(after['business_descriptions']) == 2
    added = after['business_descriptions'][1]
    assert added['quote'] == 'The Safety segment is currently comprised of Rely Innovations, Inc. ("Rely").'
    assert added['business_scope'] == {'kind': 'named_segment', 'label': 'Safety'}
    assert before['business_descriptions'][0] == after['business_descriptions'][0]
    for result in (before, after):
        facets = {row['facet']: row for row in result['source_answer']['business_context_coverage']['facets']}
        assert all(facets[key]['status'] == 'not_verified' for key in ('activities', 'revenue_model'))
        assert result['source_answer']['business_context_coverage']['complete_business_model'] is False
    assert next(row for row in before['source_answer']['business_context_coverage']['facets'] if row['facet'] == 'segments')['status'] == 'not_verified'
    assert next(row for row in after['source_answer']['business_context_coverage']['facets'] if row['facet'] == 'segments')['status'] == 'source_description_present'
    # Response reference IDs shift when a description is added; claim content must not.
    preserved = lambda result: [(row['claim_kind'], row['claim']) for row in result['source_answer']['claims']
                                if row['claim_kind'] != 'issuer_business_description']
    assert preserved(before) == preserved(after)
    assert len(reads) == 1 and not blocked
    report = {'base_commit': base, 'kind': 'retained_business_producer_and_final_gate_comparison',
              'date_auckland': '2026-10-21', 'body_hashes': {'filing': body_hash, 'facts': facts_hash},
              'archive_inventory_entries_verified': len(sums), 'external_requests': 0, 'model_calls': 0,
              'retained_fact_substitutions': len(reads), 'question': question, 'results': results,
              'limitations': ['Retained-source producer/binder and final gate, not fresh retrieval, HTTP/JWT, persistence or browser acceptance.',
                             'Committed baseline business producer/binder; current financial, competition, risk and final composition are shared.',
                             'Directory identity, filing metadata and facts HTTP response are injected. Hashes do not establish independent source origin or current availability.',
                             'One segment composition description is not complete segment coverage, business economics, ownership proof or an investment thesis.',
                             'No independent usefulness review, development/holdout quality pass or new execution/spending/retention authority.']}
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'business_before': 1, 'business_after': 2, 'segment_scope': added['business_scope'],
                      'preserved_nonbusiness_claims': len(preserved(after)), 'external_requests': 0, 'model_calls': 0}))


if __name__ == '__main__':
    main()
