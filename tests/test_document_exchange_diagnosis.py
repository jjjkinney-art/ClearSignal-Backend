"""Synthetic evidence of diagnostic collapse across document transport failures."""
import pytest
import httpcore
from tests.test_pilot_live import boundary, install_protocol, ProtocolStream
from validation.capture_budget import BudgetError
from validation.pilot_fixtures import SECRET_CANARIES


@pytest.mark.parametrize('fault', ['redirect', 'forbidden', 'throttled', 'server_error',
    'compressed', 'oversize', 'reflection', 'connect_timeout', 'read_timeout',
    'malformed_protocol', 'close_failure', 'xhtml', 'media_case', 'html'])
def test_document_exchange_failure_partition(boundary, monkeypatch, fault):
    cik = boundary.case['identity']['cik']
    boundary.sec_exchange('GET', f'https://data.sec.gov/submissions/CIK{cik}.json', None)
    url = next(iter(boundary.sec_document_urls()))
    writes = []
    status = {'redirect':307, 'forbidden':403, 'throttled':429, 'server_error':500}.get(fault, 200)
    media = {'xhtml':'application/xhtml+xml', 'media_case':'Text/HTML'}.get(fault, 'text/html')
    body = SECRET_CANARIES[0].encode() if fault == 'reflection' else b'<html>synthetic evidence</html>'
    extra = b'Content-Encoding: gzip\r\n' if fault == 'compressed' else b''
    response = (f'HTTP/1.1 {status} Synthetic\r\nContent-Type: {media}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n'.encode()+extra+b'\r\n'+body)
    if fault == 'malformed_protocol': response = b'NOT HTTP\r\n\r\n'
    if fault == 'oversize': monkeypatch.setattr('validation.pilot_live.MAX_RESPONSE_BYTES', 8)
    close_fault = [fault == 'close_failure']
    class Stream(ProtocolStream):
        def read(self, *args, **kwargs):
            if fault == 'read_timeout': raise httpcore.ReadTimeout('invented diagnostic message')
            return super().read(*args, **kwargs)
        def close(self):
            if close_fault[0]: raise RuntimeError('invented close message')
    def connect(*args, **kwargs):
        if fault == 'connect_timeout': raise httpcore.ConnectTimeout('invented connect message')
        return Stream(response, writes)
    monkeypatch.setattr(boundary.wire._wire._pool._network_backend, 'connect_tcp', connect)
    if fault == 'html':
        boundary.sec_exchange('GET', url, None)
        assert boundary.ledger.summary()['halted'] is None
        assert boundary.ledger.summary()['unresolved_attempts'] == 0
    else:
        with pytest.raises(BudgetError): boundary.sec_exchange('GET', url, None)
        result = boundary.ledger.summary()
        assert result['unresolved_attempts'] == 1
        if fault in {'xhtml', 'media_case'}:
            assert result['halted'] == 'invalid_response'
            assert result['first_sec_refusal']['code'] == 'sec_media_type'
        else:
            assert result['halted'] == 'post_claim_failure'
            assert result['first_sec_refusal'] is None
            expected = {'redirect':'http_redirect', 'forbidden':'http_auth',
                        'throttled':'http_throttled', 'server_error':'http_server_error',
                        'compressed':'response_encoding', 'oversize':'response_size',
                        'reflection':'response_reflection', 'connect_timeout':'connect_timeout',
                        'read_timeout':'read_timeout', 'malformed_protocol':'protocol_error',
                        'close_failure':'transport_other'}[fault]
            assert result['first_transport_failure'] == {
                'attempt_id':boundary.events[-1]['attempt_id'], 'route':'sec/document',
                'stage':'evidence.sec', 'code':expected}
        assert result['known_actual_nanousd'] == 0
        before = len(writes)
        with pytest.raises(BudgetError): boundary.sec_exchange('GET', url, None)
        assert len(writes) == before
    assert boundary.ledger.summary()['attempts'] == 2
    assert sum(data.startswith(b'GET ') for data in writes) <= 1
    if writes:
        assert b'Accept: application/json' in b''.join(writes)
        assert b'Authorization:' not in b''.join(writes)

    # The same failure can recur during pool cleanup; observe then disarm only fake I/O.
    if fault == 'close_failure':
        with pytest.raises(RuntimeError, match='invented close message'): boundary.wire.close()
        close_fault[0] = False


@pytest.mark.parametrize('kind,code', [
    ('ProxyError','proxy_error'), ('ConnectError','connect_error'),
    ('WriteTimeout','write_timeout'), ('WriteError','write_error'),
    ('ReadError','read_error'), ('PoolTimeout','pool_timeout'),
    ('RemoteProtocolError','protocol_error')])
def test_type_only_classification_with_primary_error_and_close_failure(boundary, monkeypatch, kind, code):
    import httpx
    from validation.pilot_live import TransportFailure
    exc = getattr(httpx, kind)(SECRET_CANARIES[0])
    monkeypatch.setattr(boundary.wire._wire, 'handle_request', lambda request: (_ for _ in ()).throw(exc))
    with pytest.raises(TransportFailure) as caught:
        boundary.wire.exchange('GET', 'https://www.sec.gov/files/company_tickers.json')
    assert caught.value.code == code
    assert str(caught.value) == 'owned HTTP exchange failed'


def test_tls_type_chain_not_message():
    import ssl, httpx
    from validation.pilot_live import transport_failure_code
    error = httpx.ConnectError(SECRET_CANARIES[0])
    error.__cause__ = ssl.SSLError(SECRET_CANARIES[1])
    assert transport_failure_code(error) == 'tls_error'
    assert transport_failure_code(RuntimeError('TLS '+SECRET_CANARIES[0])) == 'transport_other'


def test_status_failure_survives_response_close_failure(boundary, monkeypatch):
    import httpx
    from validation.pilot_live import TransportFailure
    class Body(httpx.SyncByteStream):
        def __iter__(self): yield b''
        def close(self): raise RuntimeError(SECRET_CANARIES[0])
    monkeypatch.setattr(boundary.wire._wire, 'handle_request', lambda request:httpx.Response(429,stream=Body()))
    with pytest.raises(TransportFailure) as caught:
        boundary.wire.exchange('GET','https://www.sec.gov/files/company_tickers.json')
    assert caught.value.code == 'http_throttled'


@pytest.mark.parametrize('value', [
    {'nested': {'reflected': SECRET_CANARIES[0]}},
    {'nested': __import__('json').dumps({'reflected': SECRET_CANARIES[0]})}])
def test_recursive_reflection_is_fixed_code_only(boundary, monkeypatch, value):
    import json
    from types import MappingProxyType
    boundary.wire.runtime=MappingProxyType({'bearer_placeholder':SECRET_CANARIES[0],
                                          'sec_contact':SECRET_CANARIES[1]})
    raw=json.dumps(value).replace('a','\\u0061').encode()
    install_protocol(monkeypatch,boundary,raw)
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET','https://www.sec.gov/files/company_tickers.json',None)
    result=boundary.ledger.summary()
    assert result['first_transport_failure']['code']=='response_reflection'
    assert not any(canary in json.dumps(result) for canary in SECRET_CANARIES)
    assert not any(canary.encode() in boundary.ledger.path.read_bytes() for canary in SECRET_CANARIES)


def test_first_transport_cause_atomic_and_cannot_overwrite_prior_halt(boundary):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from validation.capture_budget import digest
    ids=[boundary.claim('sec/submissions',digest({'i':i}),0,0) for i in range(2)]
    barrier=Barrier(2)
    def fail(i):
        barrier.wait()
        boundary.ledger.record_transport_failure(ids[i],'sec/submissions','evidence.sec',
                                                 ('read_timeout','http_auth')[i])
    with ThreadPoolExecutor(2) as pool:list(pool.map(fail,range(2)))
    first=boundary.ledger.summary()['first_transport_failure']
    assert (first['attempt_id'],first['code']) in {(ids[0],'read_timeout'),(ids[1],'http_auth')}
    boundary.ledger.record_transport_failure(ids[1],'sec/submissions','evidence.sec','response_close')
    boundary.ledger.halt('rehearsal_failure')
    assert boundary.ledger.summary()['first_transport_failure']==first


@pytest.mark.parametrize('field',['attempt_id','route','stage','code'])
def test_diagnostic_metadata_privacy_allowlist(boundary,field):
    from validation.capture_budget import digest
    attempt=boundary.claim('sec/submissions',digest({'fixture':1}),0,0)
    args=dict(attempt_id=attempt,route='sec/submissions',stage='evidence.sec',code='read_timeout')
    args[field]=SECRET_CANARIES[0]
    with pytest.raises(BudgetError):boundary.ledger.record_transport_failure(**args)
    assert boundary.ledger.summary()['first_transport_failure'] is None
    assert SECRET_CANARIES[0].encode() not in boundary.ledger.path.read_bytes()


@pytest.mark.parametrize('scenario',['happy','wire_redirect'])
def test_worker_publishes_terminal_evidence_when_cleanup_raises(tmp_path,monkeypatch,scenario):
    import json
    from validation import pilot_rehearsal
    original=pilot_rehearsal.subprocess.run
    injection="""from validation.pilot_live import LiveAdapterBoundary
_original_close=LiveAdapterBoundary.close
def _failing_close(self):
    _original_close(self)
    raise RuntimeError('invented-private-cleanup-value')
LiveAdapterBoundary.close=_failing_close
"""
    def run(args,*a,**k):
        if '-c' in args and 'from validation._pilot_worker import main' in args[-1]:
            args=list(args)
            prefix,suffix=args[-1].split('from validation._pilot_worker import main',1)
            args[-1]=prefix+'\n'+injection+'\nfrom validation._pilot_worker import main'+suffix
        return original(args,*a,**k)
    monkeypatch.setattr(pilot_rehearsal.subprocess,'run',run)
    result=pilot_rehearsal.run_rehearsal(tmp_path/'run',scenario=scenario,mode='live_adapter_validation')
    assert result['status']=='halted'
    assert result['cleanup_failure']=='boundary_close'
    assert 'invented-private-cleanup-value' not in json.dumps(result)
    if scenario=='wire_redirect':
        assert result['ledger']['first_transport_failure']['code']=='http_redirect'
        assert result['ledger']['halted']=='post_claim_failure'
    else:assert result['ledger']['halted']=='rehearsal_failure'


@pytest.mark.parametrize('phase',['request_gate','request_build','dispatch_gate'])
def test_pre_dispatch_failure_codes(boundary,monkeypatch,phase):
    import httpx
    from validation.pilot_live import TransportFailure
    def fail(*a,**k): raise RuntimeError(SECRET_CANARIES[0])
    class Gate:
        def validate_request(self,*a):
            if phase=='request_gate':fail()
        def record_dispatch(self):fail()
    if phase=='request_build':monkeypatch.setattr(httpx,'Request',fail)
    else:boundary.wire.gate=Gate()
    with pytest.raises(TransportFailure) as caught:
        boundary.wire.exchange('GET','https://www.sec.gov/files/company_tickers.json')
    assert caught.value.code==phase


def test_explicit_response_close_failure(boundary,monkeypatch):
    import httpx
    from validation.pilot_live import TransportFailure
    response=httpx.Response(200,headers={'Content-Type':'text/html'})
    monkeypatch.setattr(response,'iter_raw',lambda:iter([b'<html>synthetic</html>']))
    def fail():raise RuntimeError(SECRET_CANARIES[0])
    monkeypatch.setattr(response,'close',fail)
    monkeypatch.setattr(boundary.wire._wire,'handle_request',lambda request:response)
    with pytest.raises(TransportFailure) as caught:
        boundary.wire.exchange('GET','https://www.sec.gov/files/company_tickers.json')
    assert caught.value.code=='response_close'


@pytest.mark.parametrize('status,code',[(201,'http_other_status'),(400,'http_client_error'),(401,'http_auth')])
def test_remaining_status_categories(boundary,monkeypatch,status,code):
    install_protocol(monkeypatch,boundary,b'',status=status)
    with pytest.raises(BudgetError):boundary.sec_exchange('GET','https://www.sec.gov/files/company_tickers.json',None)
    assert boundary.ledger.summary()['first_transport_failure']['code']==code


def test_bad_json_is_classified_before_semantic_validation(boundary,monkeypatch):
    install_protocol(monkeypatch,boundary,b'{bad JSON')
    with pytest.raises(BudgetError):boundary.sec_exchange('GET','https://www.sec.gov/files/company_tickers.json',None)
    assert boundary.ledger.summary()['first_transport_failure']['code']=='response_json'


def test_existing_halt_and_legacy_ledgers_not_rewritten(boundary):
    from validation.capture_budget import digest
    attempt=boundary.claim('sec/submissions',digest({'fixture':1}),0,0)
    boundary.ledger.halt('stage_timeout')
    boundary.ledger.record_transport_failure(attempt,'sec/submissions','evidence.sec','read_timeout')
    assert boundary.ledger.summary()['first_transport_failure'] is None
    assert boundary.ledger.summary()['halted']=='stage_timeout'
    with boundary.ledger.transaction() as db:db.execute('DROP TABLE first_transport_failure')
    assert boundary.ledger.summary()['first_transport_failure'] is None


def test_model_transport_failure_binds_claim(boundary,monkeypatch):
    from validation.pilot_fixtures import model_fixture
    import httpx
    boundary.ledger.finish_case(boundary.case_run)
    boundary.begin(boundary.cases[1]);boundary.stage.set('question_answerer')
    install_protocol(monkeypatch,boundary,{},status=429)
    payload={'model':'gpt-4o-mini','messages':[{'role':'user','content':'synthetic'}],
             'max_tokens':4096,'temperature':0.0,'n':1,'stream':False,'service_tier':'default'}
    import json
    request=httpx.Request('POST','https://api.openai.com/v1/chat/completions',
                         content=json.dumps(payload).encode(),
                         extensions={'timeout':dict.fromkeys(('connect','read','write','pool'),15.0)})
    with pytest.raises(BudgetError):boundary.model_request(request)
    first=boundary.ledger.summary()['first_transport_failure']
    assert first['route']=='model/question_answerer' and first['stage']=='question_answerer'
    assert first['code']=='http_throttled'


@pytest.mark.parametrize('worker_status', ['complete', 'halted'])
def test_parent_failure_preserves_published_terminal_bytes(tmp_path, monkeypatch, worker_status):
    import json
    from types import SimpleNamespace
    from validation import pilot_rehearsal
    output = tmp_path / 'run'
    terminal = {'status': worker_status, 'claims': [{'route': 'sec/document'}],
                'ledger': {'halted': 'post_claim_failure',
                           'first_transport_failure': {'code': 'read_timeout'}}}
    encoded = json.dumps(terminal, indent=2).encode()
    original = pilot_rehearsal.subprocess.run
    def run(args, *a, **k):
        if '-c' in args and 'from validation._pilot_worker import main' in args[-1]:
            (output / 'artifact.json').write_bytes(encoded)
            return SimpleNamespace(returncode=1)
        return original(args, *a, **k)
    monkeypatch.setattr(pilot_rehearsal.subprocess, 'run', run)
    result = pilot_rehearsal.run_rehearsal(output, mode='live_adapter_validation')
    assert result['status'] == 'worker_incomplete'
    assert result['launch_ready'] is False
    assert result['worker_terminal_evidence'] == terminal
    assert (output / 'artifact.json').read_bytes() == encoded
    assert json.loads((output / 'launcher-failure.json').read_text()) == result
