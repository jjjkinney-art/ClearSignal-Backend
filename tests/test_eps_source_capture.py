"""Invented data/authority only; real I/O is replaced below the owned wire."""
import json
from pathlib import Path
from threading import Event

import pytest

from tests.test_pilot_approved import CONFIG, RUNTIME
from tests.test_sec_document_envelope import WireStream, head, chunked
from validation.capture_budget import AttemptLedger, BudgetError, digest
from validation.pilot_policy import AUDITED_DEPENDENCIES, policy_for as pilot_policy
from validation.eps_source_capture import (SOURCES, PURPOSE, manifest_for as capture_manifest, policy_for,
                                        validate_approval, main)
from validation._eps_source_capture_worker import CaptureOwner, capture_sources
from validation._pilot_wire_fixtures import SyntheticProxyStream

BINDING = {'revision': 'TEST-ONLY', 'source_sha256': 'TEST-ONLY'}
AS_OF = '2026-03-02'
FACTS = b'{"cik":937966,"facts":{}}'
NPK_FACTS = b'{"cik":80172,"facts":{}}'  # Second fixed source is JSON, never an NPK_FACTS request.

def manifest_for(binding, execution, output):
    return capture_manifest(binding, execution, output, AS_OF)


def approval(output):
    return {'reference': 'TEST-ONLY-NOT-AUTHORITY', 'run_id': 'TEST-ONLY-run',
        'manifest_sha256': digest(manifest_for(BINDING, CONFIG, output)),
        'output_dir': str(output), 'execution_allowed': True, 'spending_authorized': True,
        'public_body_retention_authorized': True, 'analysis_as_of': AS_OF}


@pytest.fixture
def owner(tmp_path, monkeypatch):
    for k, v in {'OPENAI_API_KEY': RUNTIME['bearer_placeholder'],
                 'SEC_USER_AGENT': RUNTIME['sec_contact'],
                 **{k: CONFIG['proxy'] for k in CONFIG['proxy_selectors']},
                 **{k: CONFIG['ca_identity']['path'] for k in CONFIG['ca_selectors']}}.items():
        monkeypatch.setenv(k, v)
    policy = policy_for(BINDING, dict(AUDITED_DEPENDENCIES), approval(tmp_path), CONFIG)
    obj = CaptureOwner(AttemptLedger(tmp_path / 'ledger.sqlite', policy, create=True))
    yield obj
    obj.seal()
    obj.wire.close()


def install(owner, monkeypatch, responder=None):
    log = []
    def respond(target):
        if responder:
            return responder(target)
        body, media = (FACTS, 'application/json') if 'CIK0000937966' in target else (NPK_FACTS, 'application/json')
        return head(media, len(body)), body, None
    # Only the native socket is replaced. Request grants, HTTPX/httpcore,
    # status/framing/size/encoding/reflection checks and ledger run unchanged.
    def connect(*args, **kwargs):
        proxy = SyntheticProxyStream(owner)
        proxy.tunnel = WireStream(respond, log)
        return proxy
    monkeypatch.setattr(owner.wire._wire._pool._network_backend.backend, 'connect_tcp', connect)
    return log


def test_exact_two_slots_and_no_model_authority(tmp_path):
    p = policy_for(BINDING, dict(AUDITED_DEPENDENCIES), approval(tmp_path), CONFIG)
    assert p['maximum_attempts'] == 2
    assert p['quotas']['overall'] == {'model': 0, 'sec': 2}
    for source in SOURCES:
        quotas = p['quotas']['per_case'][source[0]]
        assert quotas[source[1]] == quotas['sec'] == 1
        assert sum(v for k, v in quotas.items() if k.startswith('sec/')) == 1
        assert quotas['model'] == 0
    # The old policy still has the exact 33-slot variant and six cases.
    old = pilot_policy(BINDING, dict(AUDITED_DEPENDENCIES), mode='source_monitoring')
    assert old['quotas']['overall']['sec'] == 33 and len(old['approved_case_ids']) == 6


@pytest.mark.parametrize('key,value', [('public_body_retention_authorized', False),
    ('spending_authorized', False), ('execution_allowed', False),
    ('manifest_sha256', 'wrong'), ('output_dir', '/tmp/different'), ('reference', 'pending')])
def test_approval_cannot_transfer(tmp_path, key, value):
    a = {**approval(tmp_path), key: value}
    with pytest.raises(BudgetError):
        validate_approval(a, BINDING, CONFIG)


def test_old_approval_refused(tmp_path):
    a = approval(tmp_path)
    del a['public_body_retention_authorized']
    with pytest.raises(BudgetError):
        validate_approval(a, BINDING, CONFIG)


def test_mutated_fixed_policy_rejected(tmp_path):
    p = policy_for(BINDING, dict(AUDITED_DEPENDENCIES), approval(tmp_path), CONFIG)
    p['quotas']['per_case'][SOURCES[0][0]]['sec/document'] = 1
    with pytest.raises(BudgetError):
        AttemptLedger(tmp_path/'bad.sqlite', p, create=True)


def test_capture_success_exact_receipts(owner, monkeypatch, tmp_path):
    log = install(owner, monkeypatch)
    result = capture_sources(owner, tmp_path)
    assert result['status'] == 'complete'
    assert result['ledger']['attempts'] == result['native_dispatches'] == 2
    assert result['ledger']['unresolved_attempts'] == result['late_tasks'] == 0
    assert result['tasks_finished'] == result['tasks_registered'] == 2
    assert result['model_attempts'] == 0 and not result['launch_ready']
    assert result['completed_questions'] == 0 and result['analysis_as_of'] == AS_OF
    assert not result['application_endpoint_activated'] and result['capture_purpose'] == PURPOSE
    for source, body in zip(SOURCES, (FACTS, NPK_FACTS)):
        assert (tmp_path/source[6]).read_bytes() == body
        r = json.loads((tmp_path/(source[6]+'.receipt.json')).read_text())
        assert r['url'] == source[3] and r['body_bytes'] == len(body)
        assert r['body_sha256'] == __import__('hashlib').sha256(body).hexdigest()
        assert r['http_status'] == 200 and r['content_encoding'] == 'identity'
        assert not r['admitted_evidence']
    assert len(log) == 2 and all(s.closed for s in log)
    assert all(max(s.reads) <= 65536 for s in log)
    assert all(b'authorization:' not in bytes(s.request).lower() for s in log)
    assert RUNTIME['sec_contact'] not in (tmp_path/'artifact.json').read_text()


@pytest.mark.parametrize('media,body,extra,expected', [
    ('application/json', FACTS, b'', 'complete'),
    ('text/plain', FACTS, b'', 'halted'),
    ('application/json', b'{"cik":1}', b'', 'halted'),
    ('application/json', b'invalid', b'', 'halted'),
    ('application/json', FACTS, b'Content-Encoding: gzip\r\n', 'halted'),
    ('application/json', RUNTIME['sec_contact'].encode(), b'', 'halted'),
])
def test_failure_closes_and_never_persists_invalid_body(owner, monkeypatch, tmp_path, media, body, extra, expected):
    def response(target):
        if 'CIK0000937966' in target:
            return head(media, len(body), extra), body, None
        return head('application/json', len(NPK_FACTS)), NPK_FACTS, None
    log = install(owner, monkeypatch, response)
    result = capture_sources(owner, tmp_path)
    assert result['status'] == expected
    assert all(s.closed for s in log)
    if expected == 'halted':
        assert len(log) == 1 and result['ledger']['unresolved_attempts'] == 1
        assert not (tmp_path/SOURCES[0][6]).exists()
        assert not (tmp_path/SOURCES[1][6]).exists()


@pytest.mark.parametrize('source_index', [0, 1])
@pytest.mark.parametrize('overflow', [False, True])
@pytest.mark.parametrize('framing', ['declared', 'chunked', 'absent'])
def test_each_fixed_wire_size_boundary(owner, monkeypatch, source_index, overflow, framing):
    source = SOURCES[source_index]
    size = source[4] + int(overflow)
    body = b'{}' + b' ' * (size - 2)
    extra = b'Transfer-Encoding: chunked\r\n' if framing == 'chunked' else b''
    payload = chunked(body) if framing == 'chunked' else body
    log = install(owner, monkeypatch, lambda _: (
        head(source[5], size if framing == 'declared' else None, extra), payload, None))
    # Wire-only boundary check; huge bodies are not invented valid financial data.
    case = owner.ledger.begin_case(source[0])
    fp = digest({'method':'GET','url':source[3],'route':source[1],'stage':source[2]})
    attempt = owner.ledger.reserve(case, source[1], input_bound=0, output_bound=0, request_sha256=fp)
    owner.ledger.claim_dispatch(attempt, case_run=case, route=source[1], request_sha256=fp,
                                input_bound=0, output_bound=0)
    grant = owner.gate.issue(attempt, fp, source[1], case, source[2])
    with owner.gate.exchange(source[3], grant, fp):
        if overflow:
            with pytest.raises(Exception) as exc:
                owner.wire.exchange('GET', source[3])
            assert getattr(exc.value, 'code', None) == 'response_size'
        else:
            assert len(owner.wire.exchange('GET', source[3])[1]) == size
    assert len(log) == 1 and log[0].closed


def test_late_worker_stays_unsettled_and_cannot_publish(owner, monkeypatch, tmp_path):
    from validation import _eps_source_capture_worker as worker
    entered, release, finished = Event(), Event(), Event()
    original = owner.exchange
    def slow(*args):
        entered.set()
        release.wait(2)
        try:
            return original(*args)
        finally:
            finished.set()
    monkeypatch.setattr(owner, 'exchange', slow)
    monkeypatch.setattr(worker, 'STAGE_SECONDS', .03)
    monkeypatch.setattr(worker, 'DRAIN_SECONDS', .01)
    install(owner, monkeypatch)
    try:
        result = capture_sources(owner, tmp_path)
        assert entered.is_set() and result['status'] == 'halted'
        assert result['ledger']['halted'] == 'stage_timeout'
        assert result['late_tasks'] == 1
        assert not (tmp_path/SOURCES[0][6]).exists()
        frozen = (tmp_path/'artifact.json').read_bytes()
    finally:
        release.set()
        assert finished.wait(3)
    assert (tmp_path/'artifact.json').read_bytes() == frozen


def test_reopened_ledger_cannot_dispatch(owner, tmp_path):
    p = owner.ledger.policy
    reopened = AttemptLedger(tmp_path/'ledger.sqlite', p)
    with pytest.raises(BudgetError):
        reopened.begin_case(SOURCES[0][0])


def test_cli_missing_authority_creates_nothing(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(['--manifest', str(tmp_path/'missing')])
    assert exc.value.code == 2 and list(tmp_path.iterdir()) == []


def test_isolated_worker_end_to_end(tmp_path):
    import os
    import subprocess
    import sys
    from validation.pilot_rehearsal import prepare_policy, ROOT
    base = prepare_policy()
    a = approval(tmp_path)
    a['manifest_sha256'] = digest(manifest_for(base['code_binding'], CONFIG, tmp_path))
    p = policy_for(base['code_binding'], base['dependencies'], a, CONFIG)
    (tmp_path/'isolated-home').mkdir()
    (tmp_path/'request.json').write_text(json.dumps({'policy': p}))
    # Replace only native in-memory TCP underneath the real scoped proxy/TLS
    # backend. The worker still installs its own audit gate before execution.
    code = '''
import sys, socket
sys.path.insert(0, ROOT)
socket.has_ipv6 = False
sys.addaudithook(lambda e,a: (_ for _ in ()).throw(RuntimeError('no real sockets')) if e.startswith('socket.') else None)
from tests.test_sec_document_envelope import WireStream, head
from validation._pilot_wire_fixtures import SyntheticProxyStream
from validation.pilot_live import OwnedHTTPTransport
original = OwnedHTTPTransport.__init__
def init(self, **kwargs):
    original(self, **kwargs)
    def response(target):
        body, media = (b'{"cik":937966,"facts":{}}', 'application/json') if 'CIK0000937966' in target else (b'{"cik":80172,"facts":{}}', 'application/json')
        return head(media, len(body)), body, None
    def connect(*args, **kwargs):
        proxy = SyntheticProxyStream(None)
        proxy.tunnel = WireStream(response, [])
        return proxy
    self._wire._pool._network_backend.connect_tcp = connect
OwnedHTTPTransport.__init__ = init
from validation._eps_source_capture_worker import main
raise SystemExit(main())
'''.replace('ROOT', repr(str(ROOT)))
    env = {'PATH':'/usr/bin:/bin', 'HOME':str(tmp_path/'isolated-home'),
           'OPENAI_API_KEY':RUNTIME['bearer_placeholder'], 'SEC_USER_AGENT':RUNTIME['sec_contact'],
           **{k:CONFIG['proxy'] for k in CONFIG['proxy_selectors']},
           **{k:CONFIG['ca_identity']['path'] for k in CONFIG['ca_selectors']}}
    child = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=tmp_path,
                            env=env, capture_output=True, timeout=30)
    assert child.returncode == 0, child.stderr.decode()
    result = json.loads((tmp_path/'artifact.json').read_text())
    assert result['status'] == 'complete' and result['native_dispatches'] == 2
    assert result['ledger']['unresolved_attempts'] == 0
    assert child.stdout == child.stderr == b''


def test_timeout_after_claim_does_not_release_or_publish(owner, monkeypatch, tmp_path):
    from validation import _eps_source_capture_worker as worker
    entered, release, finished = Event(), Event(), Event()
    def response(_):
        entered.set()
        release.wait(2)
        return head('application/json', len(FACTS)), FACTS, None
    install(owner, monkeypatch, response)
    original = owner.exchange
    def tracked(*args):
        try:
            return original(*args)
        finally:
            finished.set()
    monkeypatch.setattr(owner, 'exchange', tracked)
    monkeypatch.setattr(worker, 'STAGE_SECONDS', .1)
    monkeypatch.setattr(worker, 'DRAIN_SECONDS', .01)
    try:
        result = capture_sources(owner, tmp_path)
        assert entered.is_set() and result['late_tasks'] == 1
        assert result['ledger']['attempts'] == result['ledger']['unresolved_attempts'] == 1
        assert result['native_dispatches'] == 1
        assert result['ledger']['halted'] == 'stage_timeout'
        frozen = (tmp_path/'artifact.json').read_bytes()
    finally:
        release.set()
        assert finished.wait(3)
    assert owner.ledger.summary()['unresolved_attempts'] == 1
    assert not (tmp_path/SOURCES[0][6]).exists()
    assert (tmp_path/'artifact.json').read_bytes() == frozen


def test_configuration_drift_before_claim(owner, monkeypatch, tmp_path):
    log = install(owner, monkeypatch)
    monkeypatch.setenv('SEC_USER_AGENT', 'Changed contact@example.invalid')
    r = capture_sources(owner, tmp_path)
    assert r['status'] == 'halted' and r['native_dispatches'] == 0
    assert r['ledger']['halted'] == 'configuration_drift' and not log


def test_no_redispatch_or_transfer_after_success(owner, monkeypatch):
    install(owner, monkeypatch)
    source = SOURCES[0]
    case = owner.ledger.begin_case(source[0])
    owner.exchange(source, case)
    with pytest.raises(BudgetError):
        owner.exchange(source, case)
    assert owner.gate.dispatched == 1 and owner.ledger.summary()['attempts'] == 1


def test_arbitrary_url_never_dispatched(owner, monkeypatch):
    log = install(owner, monkeypatch)
    case = owner.ledger.begin_case(SOURCES[0][0])
    source = list(SOURCES[0]); source[3] += '?different'
    with pytest.raises(BudgetError):
        owner.exchange(tuple(source), case)
    assert not log and owner.gate.dispatched == 0


def test_derived_reflection_cannot_be_written(owner, monkeypatch, tmp_path):
    from validation import eps_source_gap_analysis
    install(owner, monkeypatch)
    monkeypatch.setattr(eps_source_gap_analysis, 'analyze_eps_facts',
                        lambda _, **kwargs: {'sentence':RUNTIME['sec_contact']})
    r = capture_sources(owner, tmp_path)
    assert r['status'] == 'halted' and not (tmp_path/SOURCES[0][6]).exists()
    assert r['first_failure']['code'] == 'analysis_reflection'
    assert RUNTIME['sec_contact'] not in (tmp_path/'artifact.json').read_text()


@pytest.mark.parametrize('extra,code', [
    (b'Content-Length: nonsense\r\n', 'protocol_error'),
    (b'Content-Length: 2\r\nContent-Length: 3\r\n', 'protocol_error'),
])
def test_malformed_lengths_fail_closed(owner, monkeypatch, tmp_path, extra, code):
    log = install(owner, monkeypatch, lambda _: (head('application/json', None, extra), FACTS, None))
    r = capture_sources(owner, tmp_path)
    assert r['status'] == 'halted' and len(log) == 1
    assert r['ledger']['first_transport_failure']['code'] == code
    assert not (tmp_path/SOURCES[0][6]).exists()


def test_module_entrypoint_without_approval(tmp_path):
    import subprocess
    import sys
    from validation.pilot_rehearsal import ROOT
    code = ('import sys,runpy;sys.path.insert(0,'+repr(str(ROOT))+');'
            'sys.argv=["source_capture","--manifest","missing"];'
            'runpy.run_module("validation.eps_source_capture",run_name="__main__")')
    child = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=tmp_path,
                            env={'PATH':'/usr/bin:/bin'}, capture_output=True, timeout=10)
    assert child.returncode == 2 and child.stdout == b''
    assert b'Diagnostic capture refused' in child.stderr
    assert not list(tmp_path.iterdir())


def test_prepare_writes_only_pending_manifest(tmp_path, monkeypatch):
    from validation import pilot_rehearsal
    monkeypatch.setattr(pilot_rehearsal, 'prepare_policy', lambda: {'code_binding':BINDING})
    config, manifest, output = tmp_path/'config.json', tmp_path/'manifest.json', tmp_path/'fresh'
    config.write_text(json.dumps(CONFIG))
    assert main(['--prepare','--manifest',str(manifest),'--execution-config',str(config),
                 '--output-dir',str(output),'--analysis-as-of',AS_OF]) == 0
    data = json.loads(manifest.read_text())
    assert data == manifest_for(BINDING, CONFIG, output)
    assert data['approval_status'] == 'pending'
    assert data['whole_seconds'] == 480 and data['stage_seconds'] == 20 and data['drain_seconds'] == 3
    assert not output.exists() and set(p.name for p in tmp_path.iterdir()) == {'config.json','manifest.json'}
    with pytest.raises(SystemExit):
        main(['--prepare','--manifest',str(manifest),'--execution-config',str(config),
              '--output-dir',str(output),'--analysis-as-of',AS_OF])


def test_manifest_drift_precedes_runtime_read_or_output(tmp_path, monkeypatch):
    from validation import pilot_rehearsal, pilot_approved
    from validation.eps_source_capture import run_capture
    monkeypatch.setattr(pilot_rehearsal, 'prepare_policy', lambda: {
        'code_binding':BINDING, 'dependencies':dict(AUDITED_DEPENDENCIES)})
    def forbidden():
        pytest.fail('runtime credentials must not be read for changed manifest')
    monkeypatch.setattr(pilot_approved, 'runtime_values', forbidden)
    output = tmp_path/'fresh'
    data = manifest_for(BINDING, CONFIG, output)
    data['sec_gets'] = 3
    with pytest.raises(BudgetError):
        run_capture(data, approval(output))
    assert not output.exists()


def test_old_and_new_capture_authority_cannot_cross_scopes(tmp_path):
    from validation.source_capture import validate_approval as old_validate
    a=approval(tmp_path)
    with pytest.raises(BudgetError):old_validate(a,BINDING,CONFIG)
    old={k:v for k,v in a.items() if k!='analysis_as_of'}
    with pytest.raises(BudgetError):validate_approval(old,BINDING,CONFIG)
    a['analysis_as_of']='2026-03-01'
    with pytest.raises(BudgetError):validate_approval(a,BINDING,CONFIG)


def test_existing_output_is_refused_before_runtime_credential_read(tmp_path,monkeypatch):
    from validation import pilot_rehearsal, pilot_approved
    from validation.eps_source_capture import run_capture
    monkeypatch.setattr(pilot_rehearsal,'prepare_policy',lambda:{'code_binding':BINDING,'dependencies':dict(AUDITED_DEPENDENCIES)})
    def forbidden():pytest.fail('existing output must be refused before runtime reads')
    monkeypatch.setattr(pilot_approved,'runtime_values',forbidden)
    with pytest.raises(BudgetError):run_capture(manifest_for(BINDING,CONFIG,tmp_path),approval(tmp_path))
    assert list(tmp_path.iterdir())==[]


def test_fixed_sources_are_exact_nonholdout_registry_issuers():
    from validation.pilot_rehearsal import ROOT
    registry=json.loads((ROOT/'validation/issuer_registry.v2.json').read_text())
    rows={r['ticker']:r for r in registry['issuers']}
    assert tuple(s[0] for s in SOURCES)==('ASML:core_thesis','NPK:core_thesis')
    for source in SOURCES:
        ticker=source[0].split(':')[0];row=rows[ticker]
        cik=row['issuer_deduplication_key'].split(':')[1]
        assert source[3]=='https://data.sec.gov/api/xbrl/companyfacts/CIK'+cik+'.json'
        assert row['reserved_holdout'] is False and source[4]==16_777_216
        assert source[1:3]==('sec/facts','evidence.sec_metrics') and source[5]=='application/json'


@pytest.mark.parametrize('route',['model/valuation','sec/document','sec/submissions','sec/directory'])
def test_zero_nonfacts_slots_are_not_transferable(owner,route):
    case=owner.ledger.begin_case(SOURCES[0][0])
    with pytest.raises(BudgetError):owner.ledger.reserve(case,route,input_bound=0,output_bound=0,request_sha256='test-only')
    assert owner.gate.dispatched==0
