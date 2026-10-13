"""Disabled live adapter: actual HTTPX/httpcore parsing with fake socket I/O."""
import json
from pathlib import Path

import pytest

from validation.capture_budget import AttemptLedger, BudgetError
from validation.pilot_fixtures import SECRET_CANARIES, model_fixture
from validation.pilot_live import LiveAdapterBoundary, OwnedHTTPTransport
from validation.pilot_policy import AUDITED_DEPENDENCIES, policy_for, response_usage, RUN_DEADLINE_SECONDS
from validation.pilot_rehearsal import run_rehearsal


@pytest.fixture
def boundary(tmp_path):
    policy = policy_for({'revision': 'fixture', 'source_sha256': 'fixture'},
                        dict(AUDITED_DEPENDENCIES), mode='live_adapter_validation')
    ledger = AttemptLedger(tmp_path / 'book.sqlite', policy, create=True)
    owner = LiveAdapterBoundary(ledger, 'happy')
    owner.begin(owner.cases[0])
    owner.stage.set('evidence.sec')
    yield owner
    owner.close()


def test_real_execution_disabled_before_io():
    wire = OwnedHTTPTransport()
    try:
        with pytest.raises(BudgetError, match='execution remains disabled'):
            wire.exchange('POST', 'https://api.openai.com/v1/chat/completions')
    finally:
        wire.close()


def test_full_directory_and_exact_submission_derived_document(boundary):
    boundary.sec_exchange('GET', 'https://www.sec.gov/files/company_tickers.json', None)
    cik = boundary.case['identity']['cik']
    assert not boundary.sec_document_urls()
    boundary.sec_exchange('GET', f'https://data.sec.gov/submissions/CIK{cik}.json', None)
    url = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/000095017026012345/issuer-20251231.htm'
    assert boundary.sec_document_urls() == {url}
    boundary.sec_exchange('GET', url, None)
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', url.replace('issuer-20251231.htm', 'report.htm'), None)
    assert boundary.ledger.summary()['attempts'] == 3


@pytest.mark.parametrize('scenario', ['wire_redirect', 'wire_connect_failure', 'wire_read_failure'])
def test_wire_failures_halt_without_retry(boundary, scenario):
    boundary.scenario = scenario
    url = 'https://www.sec.gov/files/company_tickers.json'
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', url, None)
    before = boundary.ledger.summary()
    assert before['halted']
    assert before['attempts'] == before['unresolved_attempts'] == 1
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', url, None)
    assert boundary.ledger.summary() == before


def test_ordinary_optional_fields_but_no_extra_units():
    data = model_fixture('valuation', {'ticker': 'ASML'})
    message = data['choices'][0]['message']
    message.update(refusal=None, annotations=[])
    assert response_usage(data, 4096) == (100, 32)
    for key, value in [('tool_calls', []), ('audio', None), ('refusal', 'refused'), ('annotations', [{}])]:
        copy = json.loads(json.dumps(data))
        copy['choices'][0]['message'][key] = value
        with pytest.raises(BudgetError):
            response_usage(copy, 4096)


@pytest.mark.parametrize('scenario', ['happy', 'concurrency', 'wire_redirect', 'wire_connect_failure',
                                      'wire_read_failure', 'agent_submit_failure', 'concurrent_usage_failure'])
def test_isolated_adapter_pipeline(tmp_path, scenario):
    output = tmp_path / 'adapter'
    result = run_rehearsal(output, scenario=scenario, mode='live_adapter_validation')
    assert result['artifact_type'] == 'disabled_live_adapter_validation'
    assert result['status'] == ('complete' if scenario in {'happy', 'concurrency'} else 'halted')
    assert result['network_attempts'] == result['external_dispatches'] == 0
    assert result['execution_allowed'] is result['spending_authorized'] is False
    assert result['ledger']['attempts'] <= 54
    assert result['submission_tracking']['registered'] == result['submission_tracking']['completed']
    if scenario in {'happy', 'concurrency'}:
        assert len(result['completed_cases']) == 6
        assert all(case['answer_and_evidence'] for case in result['completed_cases'])
        models = [claim for claim in result['claims'] if claim['route'].startswith('model/')]
        assert all(claim['usage']['service_tier'] == 'default' for claim in models)
        assert all(claim['input_reservation_tokens'] == 128000 for claim in models)
    for path in output.rglob('*'):
        if path.is_file():
            assert not any(canary.encode() in path.read_bytes() for canary in SECRET_CANARIES)


def test_whole_run_deadline_keeps_frozen_stage_caps():
    assert RUN_DEADLINE_SECONDS == 3 * (20 + 3) + 3 * (10 + 16 + 56 + 42 + 3) + 30
    source = Path('app/services/router_service.py').read_text()
    assert '_DEFAULT_SYNTHESIS_PLAN = ((56.0, None), (42.0, 12))' in source
    assert '_AGENT_WALL_CAP_S = 16.0' in source


class ProtocolStream:
    def __init__(self, response, writes):
        self.remaining, self.writes = response, writes

    def write(self, data, timeout=None):
        self.writes.append(data)

    def read(self, max_bytes, timeout=None):
        chunk, self.remaining = self.remaining[:max_bytes], self.remaining[max_bytes:]
        return chunk

    def start_tls(self, **kwargs):
        return self

    def get_extra_info(self, info):
        return None

    def close(self):
        pass


def install_protocol(monkeypatch, boundary, data, *, status=200, media='application/json'):
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    response = (f'HTTP/1.1 {status} Test\r\nContent-Length: {len(raw)}\r\n'
                f'Content-Type: {media}\r\nConnection: close\r\n\r\n').encode() + raw
    writes = []
    monkeypatch.setattr(boundary.wire._wire._pool._network_backend, 'connect_tcp',
                        lambda *a, **kw: ProtocolStream(response, writes))
    return writes


@pytest.mark.parametrize('fault', ['redirect', 'error', 'oversize', 'wrong_cik', 'duplicate_ticker',
                                  'secret_reflection', 'bad_json', 'encoded_path'])
def test_sec_protocol_rejection_is_durable(boundary, monkeypatch, fault):
    from validation.pilot_fixtures import sec_fixture
    identity = boundary.case['identity']
    route = 'sec/submissions' if fault == 'encoded_path' else 'sec/directory'
    _, raw = sec_fixture(route, identity, boundary.identities)
    data = json.loads(raw)
    url = (f'https://data.sec.gov/submissions/CIK{identity["cik"]}.json' if route == 'sec/submissions'
           else 'https://www.sec.gov/files/company_tickers.json')
    status = 200
    if fault == 'redirect':
        status = 307
    elif fault == 'error':
        status = 429
    elif fault == 'oversize':
        monkeypatch.setattr('validation.pilot_live.MAX_RESPONSE_BYTES', 32)
    elif fault == 'wrong_cik':
        data['0']['cik_str'] = 1
    elif fault == 'duplicate_ticker':
        data['duplicate'] = data['0']
    elif fault == 'secret_reflection':
        data['0']['title'] = SECRET_CANARIES[0]
    elif fault == 'bad_json':
        data = b'{"duplicate":1,"duplicate":2}'
    elif fault == 'encoded_path':
        data['filings']['recent']['primaryDocument'] = ['%2e%2e/report.htm']
    writes = install_protocol(monkeypatch, boundary, data, status=status)
    if fault == 'encoded_path':
        boundary.sec_exchange('GET', url, None)
        assert not boundary.sec_document_urls()
        assert boundary.events[0]['sec_document_exclusions'] == 1
        url = f'https://www.sec.gov/Archives/edgar/data/{int(identity["cik"])}/000095017026012345/%2e%2e/report.htm'
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', url, None)
    assert boundary.ledger.summary()['halted']
    assert boundary.ledger.summary()['attempts'] == 1
    assert b'Authorization:' not in b''.join(writes)


@pytest.mark.parametrize('fault', ['none', 'missing_usage', 'unpriced', 'audio', 'tools', 'reflected_key'])
def test_model_wire_protocol_and_credential_isolation(boundary, monkeypatch, fault):
    import httpx
    boundary.ledger.finish_case(boundary.case_run)
    boundary.begin(boundary.cases[1])
    boundary.stage.set('question_answerer')
    data = model_fixture('question_answerer', boundary.case['identity'])
    data['choices'][0]['message'].update(refusal=None, annotations=[])
    if fault == 'missing_usage':
        del data['usage']
    elif fault == 'unpriced':
        data['usage']['unpriced_units'] = 1
    elif fault in {'audio', 'tools'}:
        data['choices'][0]['message']['audio' if fault == 'audio' else 'tool_calls'] = []
    elif fault == 'reflected_key':
        data['choices'][0]['message']['content'] = SECRET_CANARIES[0]
    writes = install_protocol(monkeypatch, boundary, data)
    monkeypatch.setenv('HTTPS_PROXY', 'https://invented-proxy.invalid')
    monkeypatch.setenv('OPENAI_API_KEY', 'invented-ambient-key-must-not-leave')
    monkeypatch.setenv('NETRC', '/invented/path/not-to-read')
    payload = {'model': 'gpt-4o-mini', 'messages': [{'role': 'user', 'content': 'Synthetic question'}],
               'temperature': 0, 'max_tokens': 4096, 'service_tier': 'default', 'n': 1, 'stream': False}
    request = httpx.Request('POST', 'https://api.openai.com/v1/chat/completions', json=payload,
                            headers={'Authorization': 'Bearer invented-incoming-key-must-not-leave'},
                            extensions={'timeout': dict.fromkeys(('connect', 'read', 'write', 'pool'), 15.0)})
    if fault == 'none':
        assert boundary.model_request(request).status_code == 200
        assert boundary.ledger.summary()['unresolved_attempts'] == 0
    else:
        with pytest.raises(BudgetError):
            boundary.model_request(request)
        assert boundary.ledger.summary()['halted']
    assert boundary.ledger.summary()['attempts'] == 1
    emitted = b''.join(writes)
    assert b'invented-ambient-key' not in emitted
    assert b'invented-incoming-key' not in emitted
    assert emitted.count(b'POST /v1/chat/completions') == 1


@pytest.mark.parametrize('mutation', ['body', 'method', 'url', 'all'])
def test_dispatch_uses_validated_snapshot_after_caller_mutation(boundary, monkeypatch, mutation):
    import hashlib
    import httpx
    import sqlite3
    from validation.capture_budget import digest
    boundary.ledger.finish_case(boundary.case_run)
    boundary.begin(boundary.cases[1])
    boundary.stage.set('question_answerer')
    payload = {'model': 'gpt-4o-mini', 'messages': [{'role': 'user', 'content': 'Synthetic question'}],
               'temperature': 0, 'max_tokens': 4096, 'service_tier': 'default', 'n': 1, 'stream': False}
    original_body = json.dumps(payload).encode()
    original_url = 'https://api.openai.com/v1/chat/completions'
    request = httpx.Request('POST', original_url, content=original_body,
                            extensions={'timeout': dict.fromkeys(('connect', 'read', 'write', 'pool'), 15.0)})
    writes = install_protocol(monkeypatch, boundary,
                              model_fixture('question_answerer', boundary.case['identity']))
    claim = boundary.claim

    def mutate_after_claim(*args):
        attempt = claim(*args)
        if mutation in {'body', 'all'}:
            request._content = json.dumps({**payload, 'model': 'unreviewed-model', 'max_tokens': 99999}).encode()
        if mutation in {'method', 'all'}:
            request.method = 'DELETE'
        if mutation in {'url', 'all'}:
            request.url = httpx.URL('https://unreviewed.invalid/stolen')
        # No post-claim path may consult the caller's read() again.
        def forbidden_read():
            raise AssertionError('mutable caller request was re-read after claim')
        request.read = forbidden_read
        return attempt

    monkeypatch.setattr(boundary, 'claim', mutate_after_claim)
    assert boundary.model_request(request).status_code == 200
    head, body = b''.join(writes).split(b'\r\n\r\n', 1)
    assert head.startswith(b'POST /v1/chat/completions HTTP/1.1\r\n')
    assert b'Host: api.openai.com' in head
    assert body == original_body
    expected = digest({'method': 'POST', 'url': original_url,
                       'body_sha256': hashlib.sha256(original_body).hexdigest(),
                       'stage': 'question_answerer'})
    with sqlite3.connect(boundary.ledger.path) as db:
        assert db.execute('SELECT request_sha256,status FROM attempts').fetchall() == [(expected, 'settled')]
    assert boundary.ledger.summary()['attempts'] == 1


@pytest.mark.parametrize('mode', ['offline', 'live_adapter_validation'])
def test_launcher_timeout_reopens_and_fences_without_reset(tmp_path, monkeypatch, mode):
    from validation import pilot_rehearsal
    from validation.pilot_policy import MODEL_ROUTES
    policy = policy_for({'revision': 'synthetic-timeout', 'source_sha256': 'synthetic-timeout'},
                        dict(AUDITED_DEPENDENCIES), mode=mode)
    monkeypatch.setattr(pilot_rehearsal, 'prepare_policy', lambda **kwargs: policy)
    before = {}
    calls = []

    def expire(command, **kwargs):
        calls.append(kwargs['timeout'])
        ledger = AttemptLedger(Path(kwargs['cwd']) / 'ledger.sqlite', policy, create=True)
        case_run = ledger.begin_case('ASML:decision_threshold')
        binding = dict(case_run=case_run, route=MODEL_ROUTES[0], request_sha256='a' * 64,
                       input_bound=128000, output_bound=4096)
        attempt = ledger.reserve(**binding)
        ledger.claim_dispatch(attempt, **binding)
        before.update(ledger.summary())
        raise pilot_rehearsal.subprocess.TimeoutExpired(
            command, kwargs['timeout'], output=SECRET_CANARIES[0].encode(), stderr=SECRET_CANARIES[-1].encode())

    monkeypatch.setattr(pilot_rehearsal.subprocess, 'run', expire)
    output = tmp_path / 'timed-out'
    result = pilot_rehearsal.run_rehearsal(output, mode=mode)
    assert calls == [RUN_DEADLINE_SECONDS]
    assert result['status'] == 'worker_incomplete'
    assert result['ledger']['halted'] == 'reopen_requires_review'
    assert result['ledger']['attempts'] == result['ledger']['unresolved_attempts'] == 1
    assert result['ledger']['reserved_nanousd'] == before['reserved_nanousd'] > 0
    assert json.loads((output / 'artifact.json').read_text()) == result
    reopened = AttemptLedger(output / 'ledger.sqlite', policy)
    with pytest.raises(BudgetError):
        reopened.begin_case('NPK:decision_threshold')
    with pytest.raises(FileExistsError):
        pilot_rehearsal.run_rehearsal(output, mode=mode)
    assert calls == [RUN_DEADLINE_SECONDS]
    assert reopened.summary() == result['ledger']
    for path in output.rglob('*'):
        if path.is_file():
            assert not any(canary.encode() in path.read_bytes() for canary in SECRET_CANARIES)
