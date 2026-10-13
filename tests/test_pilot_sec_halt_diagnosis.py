"""Redacted first SEC refusal: protocol conditions, concurrency and legacy reads."""
import json
import pytest
from tests.test_pilot_live import boundary, install_protocol
from validation.capture_budget import BudgetError
from validation.pilot_fixtures import sec_fixture, SECRET_CANARIES

@pytest.mark.parametrize('fault', ['media_case', 'media_whitespace', 'media_other',
                                  'array_length', 'array_type', 'accession',
                                  'document_empty', 'document_uppercase'])
def test_distinct_sec_validation_failures_preserve_first_allowlisted_cause(boundary, monkeypatch, fault):
    identity = boundary.case['identity']
    _, raw = sec_fixture('sec/submissions', identity, boundary.identities)
    data = json.loads(raw)
    recent = data['filings']['recent']
    media = 'application/json'
    if fault == 'media_case': media = 'Application/JSON'
    elif fault == 'media_whitespace': media = 'application/json ; charset=utf-8'
    elif fault == 'media_other': media = 'text/plain'
    elif fault == 'array_length': recent['accessionNumber'] = []
    elif fault == 'array_type': recent['form'] = '20-F'
    elif fault == 'accession': recent['accessionNumber'][0] = 'not-an-accession'
    elif fault == 'document_empty': recent['primaryDocument'][0] = ''
    elif fault == 'document_uppercase': recent['primaryDocument'][0] = 'annual.HTM'
    writes = install_protocol(monkeypatch, boundary, data, media=media)
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', f'https://data.sec.gov/submissions/CIK{identity["cik"]}.json', None)
    result = boundary.ledger.summary()
    assert result['halted'] == 'invalid_response'
    expected = ('sec_media_type' if fault.startswith('media_') else
                'sec_recent_array_shape' if fault.startswith('array_') else
                'sec_accession_syntax' if fault == 'accession' else 'sec_document_syntax')
    assert result['first_sec_refusal'] == {
        'attempt_id': boundary.events[0]['attempt_id'], 'route': 'sec/submissions',
        'stage': 'evidence.sec', 'code': expected}
    assert boundary.sec_attempt.get() is None
    assert result['attempts'] == result['unresolved_attempts'] == 1
    assert result['known_actual_nanousd'] == 0
    assert sum(chunk.startswith(b'GET ') for chunk in writes) == 1
    assert not any(canary in json.dumps(boundary.events) for canary in SECRET_CANARIES)


def test_non_target_forms_do_not_expand_document_allowlist(boundary, monkeypatch):
    identity = boundary.case['identity']
    _, raw = sec_fixture('sec/submissions', identity, boundary.identities)
    data = json.loads(raw)
    recent = data['filings']['recent']
    recent['form'].append('FORM-OUTSIDE-FROZEN-SCOPE')
    recent['accessionNumber'].append('unvalidated-unrelated-accession')
    recent['primaryDocument'].append('../unvalidated-unrelated-document')
    install_protocol(monkeypatch, boundary, data)
    boundary.sec_exchange('GET', f'https://data.sec.gov/submissions/CIK{identity["cik"]}.json', None)
    assert len(boundary.sec_document_urls()) == 1
    assert not boundary.ledger.summary()['halted']


def claimed(boundary, route='sec/submissions'):
    from validation.capture_budget import digest
    return boundary.claim(route, digest({'test': len(boundary.events)}), 0, 0)


def test_first_refusal_atomic_across_concurrent_workers(boundary):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    a, b = claimed(boundary), claimed(boundary)
    barrier = Barrier(2)
    def refuse(attempt, code):
        barrier.wait()
        boundary.ledger.record_sec_refusal(attempt, 'sec/submissions', 'evidence.sec', code)
    with ThreadPoolExecutor(2) as pool:
        jobs = [pool.submit(refuse, a, 'sec_accession_syntax'),
                pool.submit(refuse, b, 'sec_document_syntax')]
        for job in jobs: job.result()
    first = boundary.ledger.summary()['first_sec_refusal']
    assert (first['attempt_id'], first['code']) in {
        (a, 'sec_accession_syntax'), (b, 'sec_document_syntax')}
    boundary.ledger.halt('rehearsal_failure')
    boundary.ledger.record_sec_refusal(b, 'sec/submissions', 'evidence.sec', 'sec_recent_array_shape')
    assert boundary.ledger.summary()['first_sec_refusal'] == first


@pytest.mark.parametrize('field', ['code', 'route', 'stage', 'attempt_id'])
def test_unreviewed_metadata_never_persisted(boundary, field):
    values = dict(attempt_id=claimed(boundary), route='sec/submissions',
                  stage='evidence.sec', code='sec_document_syntax')
    values[field] = SECRET_CANARIES[0]
    with pytest.raises(BudgetError): boundary.ledger.record_sec_refusal(**values)
    assert boundary.ledger.summary()['first_sec_refusal'] is None
    assert SECRET_CANARIES[0].encode() not in boundary.ledger.path.read_bytes()
    assert boundary.ledger.summary()['halted'] is None


def test_prior_halt_does_not_acquire_later_cause(boundary):
    attempt = claimed(boundary)
    boundary.ledger.halt('stage_timeout')
    boundary.ledger.record_sec_refusal(attempt, 'sec/submissions', 'evidence.sec', 'sec_document_syntax')
    assert boundary.ledger.summary()['halted'] == 'stage_timeout'
    assert boundary.ledger.summary()['first_sec_refusal'] is None


def test_legacy_ledger_without_diagnostics_remains_readable(boundary):
    attempt = claimed(boundary)
    with boundary.ledger.transaction() as db: db.execute('DROP TABLE first_sec_refusal')
    boundary.ledger.record_sec_refusal(attempt, 'sec/submissions', 'evidence.sec', 'sec_document_syntax')
    assert boundary.ledger.summary()['first_sec_refusal'] is None
    assert boundary.ledger.summary()['halted'] == 'invalid_response'


def test_route_mismatch_cannot_attribute_claim(boundary):
    attempt = claimed(boundary, 'sec/facts')
    with pytest.raises(BudgetError):
        boundary.ledger.record_sec_refusal(attempt, 'sec/submissions', 'evidence.sec', 'sec_document_syntax')
    assert boundary.ledger.summary()['halted'] is None
