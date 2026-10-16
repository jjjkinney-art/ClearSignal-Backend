"""Offline replay of the exposed PR292 NPK body and PR295 financial evidence.

No downloader or pilot launcher. Requires the exact previously retained inputs;
socket operations are denied before application imports. Output must be new.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

BODY_SHA = '8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1'
ARTIFACT_SHA = '8981da9b668f51735423b58de8d4878315f6cef2271a42899687cd52fef2b6cd'
URL = 'https://www.sec.gov/Archives/edgar/data/80172/000143774926008214/npk20251231_10k.htm'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--body', required=True)
    parser.add_argument('--artifact', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    socket.has_ipv6 = False
    sys.addaudithook(lambda event, data: (_ for _ in ()).throw(RuntimeError('network blocked'))
                    if event.startswith('socket.') else None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with open(args.body, 'rb') as source:
        body = source.read(1_404_518)
    with open(args.artifact, 'rb') as source:
        artifact_bytes = source.read(1_000_001)
    if len(body) != 1_404_517 or hashlib.sha256(body).hexdigest() != BODY_SHA:
        raise ValueError('expected exact retained NPK body')
    if hashlib.sha256(artifact_bytes).hexdigest() != ARTIFACT_SHA:
        raise ValueError('expected exact retained PR295 artifact')
    artifact = json.loads(artifact_bytes)
    case, = [row for row in artifact['completed_cases'] if row['case_id'] == 'NPK:core_thesis']

    import requests
    from app.providers.sec_client import SecFactRecord
    from app.integrity.sec_metric_evidence import comparable_metric_evidence
    from app.services import issuer_identity, thesis_disclosures as disclosures
    from app.services.evidence_references import admit_evidence
    from app.services.financial_thesis_foundation import CORE_METRICS, build_financial_foundation
    from app.services.public_document_ingestion import fetch_public_document

    response = requests.Response()
    response.status_code = 200
    response.url = URL
    response.encoding = 'utf-8'
    response.headers.update({'Content-Type': 'text/html', 'Content-Length': str(len(body))})
    response.raw = io.BytesIO(body)
    with patch('socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]), \
            patch('requests.get', return_value=response) as fixture_get:
        document = fetch_public_document(URL, publisher='SEC EDGAR', published_at='2026-03-13',
            document_type='10-K', source_type='regulatory_filing', source_tier='primary',
            sec_periodic_limits=True, preserve_sec_business=True, extract_tables=False)
    assert fixture_get.call_count == 1 and document.content_hash == BODY_SHA
    directory = issuer_identity.parse_directory({'0': {'ticker': 'NPK', 'cik_str': 80172,
                                                       'title': 'National Presto Industries Inc.'}})
    with patch.object(issuer_identity, '_load_directory', return_value=directory), \
            patch.object(disclosures.sec_provider, '_load_ticker_cik_map', return_value={'NPK': '0000080172'}), \
            patch.object(disclosures.sec_provider, 'fetch_recent_filings', return_value=[
                SimpleNamespace(url=URL, timestamp='2026-03-13', document_type='10-K')]), \
            patch.object(disclosures, 'fetch_public_document', return_value=document):
        source_items = disclosures.fetch_thesis_disclosures('NPK', question='What is the investment thesis for NPK?')
        financial = []
        facts = case['answer_and_evidence']['answer']['verified_sec_facts']
        for name, concepts in CORE_METRICS.items():
            records = []
            for fact in facts:
                taxonomy, concept = fact['metric'].split(':')
                if concept not in concepts:
                    continue
                assert fact['ticker'] == 'NPK' and fact['scope'] == 'consolidated' and fact['unit'] == 'USD'
                ref = fact['document_ref']
                _, cik, accession, _, ref_concept = ref['reference_id'].split(':')
                assert int(cik) == 80172 and taxonomy == 'us-gaap' and ref_concept == concept
                records.append(SecFactRecord(cik=cik, taxonomy=taxonomy, concept=concept,
                    label=fact['label'], unit=fact['unit'], value=fact['raw_value'],
                    start=fact['period_start'], end=fact['period_end'], filed=ref['published_at'],
                    form=fact['source'], accession=accession, filing_url=ref['url']))
            item = comparable_metric_evidence(records, ticker='NPK', expected_cik='80172',
                                               concepts=concepts, metric_name=name)
            if item is not None:
                financial.append(item)
        items, refs, _ = admit_evidence(financial + source_items, evaluated_at='2026-10-16')
        current = build_financial_foundation('NPK', items, refs, expected_cik='80172')
        with patch('app.services.operating_risk_mechanisms.operating_risk_mechanism', return_value=None):
            baseline = build_financial_foundation('NPK', items, refs, expected_cik='80172')
        mechanisms = [row for row in current['inferences'] if row['kind'] == 'operating_risk_monitoring_inference']
        assert len(mechanisms) == 1
        mechanism = mechanisms[0]
        risk = next(item for item in items if item.risk_disclosures
                    and item.risk_disclosures[0]['quote'] == mechanism['source_quote'])
        value = disclosures.bound_thesis_risk(risk, ticker='NPK')
        assert value and document.text[value['start_offset']:value['end_offset']] == mechanism['source_quote']
        assert baseline['claims'] == current['claims'] and baseline['unanswered_parts'] == current['unanswered_parts']
    result = {'source_body_sha256': BODY_SHA, 'source_artifact_sha256': ARTIFACT_SHA,
              'source_url': URL, 'scope': 'exposed_saved_NPK_development_replay',
              'live_requests': 0, 'local_response_fixture_uses': fixture_get.call_count,
              'body_bytes': len(body), 'exact_risk_span_reproduced': True,
              'claims_unchanged': True, 'unanswered_parts_unchanged': True,
              'baseline_mechanism_count': 0, 'new_mechanism_count': len(mechanisms),
              'mechanism': mechanism, 'unanswered_parts': current['unanswered_parts'],
              'limitations': ['Saved-body/financial-fact replay, not a fresh pilot or independent factual adjudication.',
                             'Reference IDs belong to this replay, not the historical run.',
                             'Inputs are exposed development evidence; no holdout was used.']}
    with open(args.output, 'x') as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write('\n')
    print(json.dumps({'output': args.output, 'mechanism_count': len(mechanisms), 'live_requests': 0}))


if __name__ == '__main__':
    main()
