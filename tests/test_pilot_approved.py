"""Activation contract tests: all configuration and authority here are invented."""
import json
import hashlib
import certifi
import socket
import ssl
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from validation.capture_budget import AttemptLedger, BudgetError, digest
from validation.pilot_approved import (ApprovedBoundary, ScopedStream, manifest_for,
                                       validate_approval, validate_execution, main)
from validation.pilot_policy import AUDITED_DEPENDENCIES, policy_for
from validation._pilot_wire_fixtures import SyntheticProxyBackend

CA_PATH = Path(certifi.where()).resolve()
CONFIG = {'documentation_reference': 'TEST-ONLY-invented-contract',
          'verification_reference': 'TEST-ONLY-config-review',
          'substitution': 'explicit_environment_proxy', 'bearer_source': 'OPENAI_API_KEY',
          'sec_contact_source': 'SEC_USER_AGENT', 'proxy': 'http://proxy:8080',
          'proxy_selectors': ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'],
          'ca_selectors': ['SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE'],
          'ca_identity': {'path': str(CA_PATH), 'sha256': hashlib.sha256(CA_PATH.read_bytes()).hexdigest()},
          'contains_no_credentials': True}
RUNTIME = {'bearer_placeholder': 'TEST_ONLY_NETWORK_PLACEHOLDER',
           'sec_contact': 'Test Fixture contact@example.invalid'}


@pytest.fixture(autouse=True)
def synthetic_runtime(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', RUNTIME['bearer_placeholder'])
    monkeypatch.setenv('SEC_USER_AGENT', RUNTIME['sec_contact'])
    for name in CONFIG['proxy_selectors']:
        monkeypatch.setenv(name, CONFIG['proxy'])
    for name in CONFIG['ca_selectors']:
        monkeypatch.setenv(name, str(CA_PATH))


BINDING = {'revision': 'TEST-ONLY', 'source_sha256': 'TEST-ONLY'}


def approval(binding=BINDING, output_dir='/tmp/TEST-ONLY-run'):
    return {'reference': 'TEST-ONLY-NOT-REAL-APPROVAL', 'run_id': 'TEST-ONLY-run',
            'manifest_sha256': digest(manifest_for(binding, CONFIG, output_dir)), 'output_dir': str(output_dir),
            'execution_allowed': True, 'spending_authorized': True}


@pytest.fixture
def boundary(tmp_path):
    policy = policy_for(BINDING, dict(AUDITED_DEPENDENCIES), mode='approved',
                        approval=approval(), execution=CONFIG)
    owner = ApprovedBoundary(AttemptLedger(tmp_path/'ledger.sqlite', policy, create=True))
    # Replace only native I/O underneath the exact approved scoped backend.
    owner.wire._wire._pool._network_backend.backend = SyntheticProxyBackend(owner)
    owner.begin(owner.cases[0]); owner.stage.set('evidence.sec')
    yield owner
    owner.close()


@pytest.mark.parametrize('bad', [None, {}, {**approval(), 'manifest_sha256': 'wrong'},
                                {**approval(), 'spending_authorized': False}])
def test_missing_mismatched_approval_refused(bad):
    with pytest.raises(BudgetError):
        policy_for(BINDING, dict(AUDITED_DEPENDENCIES), mode='approved', approval=bad, execution=CONFIG)


def test_cli_missing_approval_never_launches(tmp_path, monkeypatch):
    from validation import pilot_rehearsal
    launch = Mock(side_effect=AssertionError('must not launch'))
    monkeypatch.setattr(pilot_rehearsal, 'run_rehearsal', launch)
    with pytest.raises(SystemExit) as exc:
        main(['--manifest', str(tmp_path/'missing'), '--approval', str(tmp_path/'absent'),
              '--output-dir', str(tmp_path/'output')])
    assert exc.value.code == 2 and not launch.called


def test_unverified_or_proxy_config_refused():
    for bad in [None, {**CONFIG, 'verification_reference': ''}, {**CONFIG, 'proxy': 'http://proxy.invalid'},
                {**CONFIG, 'substitution': 'unknown'}, {**CONFIG, 'contains_no_credentials': False}]:
        with pytest.raises(BudgetError): validate_execution(bad)


def test_approved_native_path_claims_headers_and_usage(boundary):
    backend = boundary.wire._wire._pool._network_backend.backend
    original = backend.connect_tcp
    streams = []
    def connect(*args, **kwargs):
        stream = original(*args, **kwargs); streams.append(stream); return stream
    backend.connect_tcp = connect
    boundary.sec_exchange('GET', 'https://www.sec.gov/files/company_tickers.json', None)
    assert b'User-Agent: Test Fixture contact@example.invalid' in bytes(streams[-1].request)
    assert b'Authorization:' not in bytes(streams[-1].request)
    assert bytes(streams[-1].connect_request).startswith(b'CONNECT www.sec.gov:443 HTTP/1.1\r\n')
    boundary.ledger.finish_case(boundary.case_run)
    boundary.begin(boundary.cases[1]); boundary.stage.set('valuation')
    payload = {'model':'gpt-4o-mini','messages':[{'role':'user','content':'invented question'}],
               'temperature':0,'max_tokens':4096,'service_tier':'default','n':1,'stream':False}
    request = httpx.Request('POST','https://api.openai.com/v1/chat/completions',json=payload,
                            headers={'Authorization':'Bearer MUST_NOT_FORWARD'},
                            extensions={'timeout':dict.fromkeys(('connect','read','write','pool'),15.0)})
    response = boundary.model_request(request)
    assert response.status_code == 200
    sent = bytes(streams[-1].request)
    assert b'Authorization: Bearer TEST_ONLY_NETWORK_PLACEHOLDER' in sent
    assert b'MUST_NOT_FORWARD' not in sent
    assert boundary.gate.dispatched == boundary.ledger.summary()['attempts'] == 2
    assert boundary.events[-1]['input_reservation_tokens'] == 128000
    assert boundary.events[-1]['usage']['input_tokens'] == 100
    with pytest.raises(BudgetError): boundary.model_request(request)
    assert boundary.gate.dispatched == 2  # Stage quota cannot be reused.


def test_no_network_without_claim_or_after_scope(boundary):
    wire = boundary.wire
    with pytest.raises(BudgetError): wire.exchange('GET','https://www.sec.gov/files/company_tickers.json')
    with pytest.raises(BudgetError): boundary.sec_content('sec/directory','https://www.sec.gov/files/company_tickers.json')
    assert boundary.gate.dispatched == 0


def test_scoped_dns_tls_and_thread_local_gate(boundary):
    gate = boundary.gate
    gate.resolve = lambda *a, **kw: [(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.1',8080))]
    url = 'https://www.sec.gov/files/company_tickers.json'
    fingerprint = digest({'method': 'GET', 'url': url, 'route': 'sec/directory', 'stage': boundary.stage.get()})
    boundary.claim('sec/directory', fingerprint, 0, 0)
    with boundary.dispatch(url, fingerprint):
        gate.validate_request('GET', url, b'')
        gate.record_dispatch()
        assert gate.dns('proxy',8080)[0][4][0] == '10.0.0.1'
        gate.audit('socket.connect',(None,('10.0.0.1',8080)))
        for event,args in [('socket.connect',(None,('127.0.0.1',443))),
                           ('socket.getaddrinfo',('other.invalid',443)), ('socket.bind',())]:
            with pytest.raises(BudgetError): gate.audit(event,args)
        stream = ScopedStream(Mock(),gate)
        with pytest.raises(BudgetError): stream.start_tls(ssl.create_default_context(), 'other.invalid')
        insecure = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); insecure.check_hostname=False
        with pytest.raises(BudgetError): stream.start_tls(insecure,'www.sec.gov')
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as pool:
            with pytest.raises(BudgetError): pool.submit(gate.require).result()
    with pytest.raises(BudgetError): gate.dns('www.sec.gov',443)


def test_late_worker_close_never_restores_bridges(boundary, monkeypatch):
    pending = Future()
    boundary.futures.append(pending)
    boundary.original_wait = lambda *a, **kw: (set(), {pending})
    restored = Mock()
    boundary.patches.append(Mock(stop=restored))
    boundary.close()
    assert boundary.gate.closed and boundary.ledger.summary()['halted']
    restored.assert_not_called()
    with pytest.raises(BudgetError): boundary.gate.require()


def test_modes_keep_identical_frozen_quotas(boundary):
    baseline = policy_for(BINDING,dict(AUDITED_DEPENDENCIES))
    for key in ('quotas','prices','maximum_attempts','budget_usd','configuration','approved_case_ids'):
        assert boundary.ledger.policy[key] == baseline[key]


def test_exact_approved_launcher_worker_with_fake_io(tmp_path, monkeypatch):
    import subprocess
    from validation.pilot_rehearsal import prepare_policy, run_rehearsal
    real_run = subprocess.run
    injection = '''
from validation.pilot_approved import ApprovedBoundary
from validation._pilot_wire_fixtures import SyntheticProxyBackend
original = ApprovedBoundary.__init__
def fake_init(self, ledger):
    original(self, ledger)
    self.wire._wire._pool._network_backend.backend = SyntheticProxyBackend(self)
ApprovedBoundary.__init__ = fake_init
'''
    def fake_child(args, **kwargs):
        if '-c' in args and 'from validation._pilot_worker import main' in args[-1]:
            args = list(args)
            prefix, suffix = args[-1].split('from validation._pilot_worker import main', 1)
            args[-1] = prefix + '\n' + injection + '\nfrom validation._pilot_worker import main' + suffix
            assert kwargs['env']['OPENAI_API_KEY'] == RUNTIME['bearer_placeholder']
            assert kwargs['env']['SEC_USER_AGENT'] == RUNTIME['sec_contact']
        return real_run(args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', fake_child)
    binding = prepare_policy()['code_binding']
    result = run_rehearsal(tmp_path/'approved', mode='approved', scenario='approved',
                           approval=approval(binding, tmp_path/'approved'), execution=CONFIG)
    assert result['status'] == 'complete', result
    assert result['external_dispatches'] == result['ledger']['attempts'] > 0
    assert result['usage_source'] == 'provider_reported_protocol_units_not_invoice'
    assert result['execution_allowed'] is result['spending_authorized'] is True
    assert result['authentication_verified'] is False
    assert len(result['completed_cases']) == 6
    assert result['ledger']['unresolved_attempts'] == 0
    assert result['hard_usd_cap_established'] is False
    for path in (tmp_path/'approved').rglob('*'):
        if path.is_file():
            content = path.read_bytes()
            for value in RUNTIME.values():
                assert value.encode() not in content
                assert hashlib.sha256(value.encode()).hexdigest().encode() not in content


@pytest.mark.parametrize('scenario', ['wire_redirect', 'wire_connect_failure', 'wire_read_failure'])
def test_approved_failures_are_counted_and_never_retried(boundary, scenario):
    boundary.scenario = scenario
    url = 'https://www.sec.gov/files/company_tickers.json'
    with pytest.raises(BudgetError): boundary.sec_exchange('GET',url,None)
    assert boundary.gate.dispatched == 1
    assert boundary.ledger.summary()['halted']
    with pytest.raises(BudgetError): boundary.sec_exchange('GET',url,None)
    assert boundary.gate.dispatched == 1


def test_approval_cannot_transfer_output_directory(tmp_path):
    from validation.pilot_rehearsal import prepare_policy, run_rehearsal
    binding = prepare_policy()['code_binding']
    with pytest.raises(BudgetError, match='one fresh output'):
        run_rehearsal(tmp_path/'different', mode='approved', scenario='approved',
                       approval=approval(binding,tmp_path/'approved'), execution=CONFIG)
    assert not (tmp_path/'different').exists()


def claim_directory(boundary):
    url = 'https://www.sec.gov/files/company_tickers.json'
    fingerprint = digest({'method': 'GET', 'url': url, 'route': 'sec/directory', 'stage': boundary.stage.get()})
    boundary.claim('sec/directory', fingerprint, 0, 0)
    return url, fingerprint


def test_gate_itself_refuses_unclaimed_scope(boundary):
    with pytest.raises(BudgetError):
        with boundary.gate.exchange('https://www.sec.gov/files/company_tickers.json'):
            pytest.fail('unclaimed scope opened')
    assert boundary.gate.dispatched == boundary.ledger.summary()['attempts'] == 0


def test_copied_context_and_concurrent_replay_consume_one_claim(boundary):
    from contextvars import copy_context
    from concurrent.futures import ThreadPoolExecutor
    url, fingerprint = claim_directory(boundary)
    contexts = [copy_context(), copy_context()]
    def dispatch():
        try:
            with boundary.dispatch(url, fingerprint):
                boundary.wire.exchange('GET',url)
            return True
        except BudgetError:
            return False
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda context: context.run(dispatch), contexts))
    assert sum(results) == 1
    assert boundary.gate.dispatched == boundary.ledger.summary()['attempts'] == 1
    with boundary.ledger.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM native_dispatches').fetchone()[0] == 1
    boundary.done()


def test_gate_rechecks_immutable_payload(boundary):
    url, fingerprint = claim_directory(boundary)
    with boundary.dispatch(url, fingerprint):
        with pytest.raises(BudgetError): boundary.wire.exchange('POST',url,body=b'changed')
    assert boundary.gate.dispatched == 0
    boundary.done()


@pytest.mark.parametrize('value', ['http://user:password@proxy:8080', 'http://proxy:8080?secret=x',
                                  'http://other:8080', 'https://proxy:8080', 'http://proxy:8080#x'])
def test_proxy_drift_is_rejected_without_io(boundary, monkeypatch, value):
    monkeypatch.setenv('https_proxy',value)
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET','https://www.sec.gov/files/company_tickers.json',None)
    assert boundary.gate.dispatched == 0
    assert boundary.ledger.summary()['halted']


def test_ca_source_drift_rejected(boundary, monkeypatch, tmp_path):
    changed = tmp_path/'changed.pem'; changed.write_text('invented invalid certificate')
    monkeypatch.setenv('SSL_CERT_FILE',str(changed))
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET','https://www.sec.gov/files/company_tickers.json',None)
    assert boundary.gate.dispatched == 0


def test_connect_restriction_and_late_tls(boundary):
    url, fingerprint = claim_directory(boundary)
    raw = Mock()
    with boundary.dispatch(url,fingerprint):
        stream = ScopedStream(raw,boundary.gate)
        with pytest.raises(BudgetError):
            stream.write(b'CONNECT unreviewed.invalid:443 HTTP/1.1\r\nHost: unreviewed.invalid:443\r\n\r\n')
        raw.write.assert_not_called()
        good = ScopedStream(raw,boundary.gate)
        good.write(b'CONNECT www.sec.gov:443 HTTP/1.1\r\nHost: www.sec.gov:443\r\nAccept: */*\r\n\r\n')
        boundary.gate.seal()
        with pytest.raises(BudgetError): good.start_tls(ssl.create_default_context(),'www.sec.gov')
    raw.start_tls.assert_not_called()
    boundary.done()


def test_contact_reflection_rejected_before_artifacts(boundary):
    from validation._pilot_wire_fixtures import SyntheticProxyStream
    from validation.pilot_fixtures import model_fixture
    boundary.ledger.finish_case(boundary.case_run)
    boundary.begin(boundary.cases[1]); boundary.stage.set('valuation')
    fixture = model_fixture('valuation',boundary.case['identity'])
    fixture['choices'][0]['message']['content'] = RUNTIME['sec_contact']
    body = json.dumps(fixture).encode()
    response = b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body
    def connect(*args,**kwargs):
        stream = SyntheticProxyStream(boundary); stream.tunnel.response=response; return stream
    boundary.wire._wire._pool._network_backend.backend.connect_tcp=connect
    payload = {'model':'gpt-4o-mini','messages':[{'role':'user','content':'invented question'}],
               'temperature':0,'max_tokens':4096,'service_tier':'default','n':1,'stream':False}
    request=httpx.Request('POST','https://api.openai.com/v1/chat/completions',json=payload,
                          extensions={'timeout':dict.fromkeys(('connect','read','write','pool'),15.0)})
    with pytest.raises(BudgetError): boundary.model_request(request)
    serialized=json.dumps(boundary.ledger.policy)+json.dumps(boundary.events)
    assert RUNTIME['sec_contact'] not in serialized
    assert hashlib.sha256(RUNTIME['sec_contact'].encode()).hexdigest() not in serialized


def test_direct_worker_copied_request_is_refused_before_ledger(tmp_path):
    import subprocess,sys
    from validation.pilot_rehearsal import prepare_policy, ROOT
    binding=prepare_policy()['code_binding']
    approved=tmp_path/'approved'; copied=tmp_path/'copied'; copied.mkdir(); (copied/'isolated-home').mkdir()
    policy=prepare_policy(mode='approved',approval=approval(binding,approved),execution=CONFIG)
    (copied/'request.json').write_text(json.dumps({'policy':policy,'scenario':'approved'}))
    code='import sys; sys.path.insert(0,'+repr(str(ROOT))+'); from validation._pilot_worker import main; raise SystemExit(main())'
    result=subprocess.run([sys.executable,'-I','-B','-c',code],cwd=copied,env={'PATH':'/usr/bin:/bin'},capture_output=True)
    assert result.returncode==2
    assert not (copied/'ledger.sqlite').exists()


def test_runtime_contact_never_changes_persisted_policy_hash(monkeypatch):
    first=policy_for(BINDING,dict(AUDITED_DEPENDENCIES),mode='approved',approval=approval(),execution=CONFIG)
    monkeypatch.setenv('SEC_USER_AGENT','Other Fixture other@example.invalid')
    second=policy_for(BINDING,dict(AUDITED_DEPENDENCIES),mode='approved',approval=approval(),execution=CONFIG)
    assert digest(first)==digest(second)
    assert 'contact@example.invalid' not in json.dumps(first)
    assert 'other@example.invalid' not in json.dumps(second)


def test_durable_native_consumption_cannot_be_reissued(boundary):
    url,fingerprint=claim_directory(boundary)
    attempt=boundary.events[-1]['attempt_id']
    with boundary.dispatch(url,fingerprint):
        boundary.wire.exchange('GET',url)
    with pytest.raises(BudgetError,match='already consumed'):
        boundary.ledger.claim_native_dispatch(attempt,case_run=boundary.case_run,
                                             route='sec/directory',request_sha256=fingerprint)
    boundary.done()


def nested_reflection(value, shape):
    if shape == 'duplicate':
        return '{"reflected":' + json.dumps(value) + ',"reflected":"safe"}'
    return json.dumps({'reflected': value}) if shape else value


@pytest.mark.parametrize('field', ['sec_contact', 'bearer_placeholder'])
@pytest.mark.parametrize('quoted', [False, True])
@pytest.mark.parametrize('nested_json', [False, True, 'duplicate'])
@pytest.mark.parametrize('escaped', [False, True])
def test_runtime_prompt_values_refused_before_hash_or_claim(boundary, monkeypatch, field, quoted, nested_json, escaped):
    from validation import pilot_boundary
    boundary.ledger.finish_case(boundary.case_run)
    boundary.begin(boundary.cases[1]); boundary.stage.set('valuation')
    value = RUNTIME[field]
    if quoted:
        value = 'Review \"Fixture\" ' + value
        monkeypatch.setenv('SEC_USER_AGENT' if field == 'sec_contact' else 'OPENAI_API_KEY',value)
        boundary.runtime[field] = value
    payload = {'model':'gpt-4o-mini','messages':[{'role':'user','content':'prefix '+value+' suffix'}],
               'temperature':0,'max_tokens':4096,'service_tier':'default','n':1,'stream':False}
    if nested_json:
        payload['messages'][0]['content'] = nested_reflection(value, nested_json)
    raw = json.dumps(payload)
    if escaped:
        raw = raw.replace('Review', '\\u0052eview').replace('TEST_ONLY', '\\u0054EST_ONLY').replace('Test Fixture', '\\u0054est Fixture')
        assert value not in raw
    body = raw.encode()
    fingerprint = Mock(side_effect=AssertionError('fingerprinting must not occur'))
    monkeypatch.setattr(pilot_boundary, 'digest', fingerprint)
    reserve = Mock(side_effect=AssertionError('reservation must not occur'))
    monkeypatch.setattr(boundary.ledger, 'reserve', reserve)
    claim = Mock(side_effect=AssertionError('claim must not occur'))
    monkeypatch.setattr(boundary, 'claim', claim)
    original_hash = hashlib.sha256
    def no_body_hash(data=b'', **kwargs):
        assert data != body, 'body hashing must not occur'
        return original_hash(data, **kwargs)
    monkeypatch.setattr(hashlib, 'sha256', no_body_hash)
    request = httpx.Request('POST','https://api.openai.com/v1/chat/completions',content=body,
                            extensions={'timeout':dict.fromkeys(('connect','read','write','pool'),15.0)})
    with pytest.raises(BudgetError):
        boundary.model_request(request)
    fingerprint.assert_not_called(); reserve.assert_not_called(); claim.assert_not_called()
    summary = boundary.ledger.summary()
    assert summary['attempts'] == summary['reserved_nanousd'] == boundary.gate.dispatched == 0
    assert boundary.events == []
    assert summary['halted']


@pytest.mark.parametrize('field', ['sec_contact', 'bearer_placeholder'])
@pytest.mark.parametrize('nested_json', [False, True, 'duplicate'])
def test_quoted_escaped_response_values_refused(boundary, monkeypatch, field, nested_json):
    from validation._pilot_wire_fixtures import SyntheticProxyStream
    from validation.pilot_live import OwnedHTTPTransport
    value = 'Review "Fixture" ' + RUNTIME[field]
    monkeypatch.setenv('SEC_USER_AGENT' if field == 'sec_contact' else 'OPENAI_API_KEY', value)
    boundary.runtime[field] = value
    boundary.wire.close()
    boundary.wire = OwnedHTTPTransport(gate=boundary.gate, execution=CONFIG, runtime=boundary.runtime)
    from validation.pilot_approved import ScopedBackend
    body = json.dumps({str(i): {'ticker': identity['ticker'], 'cik_str': int(identity['cik']),
                               'title': nested_reflection(value, nested_json)}
                       for i, identity in enumerate(boundary.identities)}).encode()
    assert value.encode() not in body  # JSON quoting hides the raw contact.
    response = b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body
    backend = SyntheticProxyBackend(boundary)
    def connect(*args, **kwargs):
        stream = SyntheticProxyStream(boundary); stream.tunnel.response=response; return stream
    backend.connect_tcp = connect
    boundary.wire._wire._pool._network_backend = ScopedBackend(backend,boundary.gate)
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET','https://www.sec.gov/files/company_tickers.json',None)
    assert boundary.ledger.summary()['halted']
    assert not any('usage' in event for event in boundary.events)


@pytest.mark.parametrize('field', ['sec_contact', 'bearer_placeholder'])
@pytest.mark.parametrize('nested_json', [False, True, 'duplicate'])
def test_quoted_result_value_refused_before_serialization(field, nested_json):
    from validation._pilot_worker import safe_result
    value = 'Review "Fixture" ' + RUNTIME[field]
    data = {'nested': [{'answer': nested_reflection(value, nested_json)}]}
    assert value not in json.dumps(data)
    result = Mock(); result.model_dump.return_value = data
    with pytest.raises(BudgetError): safe_result(result,(value,))
