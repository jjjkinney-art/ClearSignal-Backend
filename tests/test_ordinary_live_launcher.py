"""The approval-gated ordinary launcher and the live code path, offline.

Loopback runs drive real sockets, the proxy CONNECT, TLS certificate
verification and the gate's socket audit against a server on 127.0.0.1:8080
that trusts nothing outside this process and serves invented SEC responses.
No external host is contacted. Approvals here are invented records.
"""
import json
import os
from pathlib import Path
import socket
import sqlite3
import stat

import pytest

from _ordinary_loopback_sec import LoopbackSEC
from validation import ordinary_approved as launcher
from validation.capture_budget import BudgetError, digest
from validation.ordinary_isolated_rehearsal import LOOPBACK_CONTACT, run_loopback_rehearsal
from validation.ordinary_native_policy import TEST_ONLY, ZERO_MODEL_PLACEHOLDER
from validation.ordinary_pilot_contract import CASES


def _port_free():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', 8080))
        except OSError:
            return False
    return True


needs_port = pytest.mark.skipif(not _port_free(), reason='127.0.0.1:8080 is in use')


@pytest.fixture(scope='module')
def loopback(tmp_path_factory):
    base = tmp_path_factory.mktemp('loopback').resolve()
    with LoopbackSEC(base) as sec:
        result = run_loopback_rehearsal(base / 'run', ca=sec.ca_path)
    return result, sec, base / 'run'


@needs_port
@pytest.mark.timeout(180)
def test_loopback_run_uses_the_live_code_path_within_every_limit(loopback):
    result, sec, output = loopback
    packet, worker = result['packet'], result['worker']
    assert result['status'] == 'complete' and packet['first_failure'] is None
    assert [c['status'] for c in packet['cases']] == ['answered_unadjudicated'] * 12
    # Every exchange crossed a real socket: one CONNECT, one verified TLS
    # session and one request each, all through the gate.
    assert packet['attempt_count'] == packet['wire_entries'] == worker['external_dispatches'] == 60
    assert len(sec.connects) == len(sec.requests) == 60 and sec.handshake_failures == 0
    assert all(head.split(' ')[1] in {'www.sec.gov:443', 'data.sec.gov:443'} for head in sec.connects)
    assert all(r['method'] == 'GET' and r['host'] == r['tunnel'] and r['user_agent'] == LOOPBACK_CONTACT
               for r in sec.requests)
    assert worker['mode'] == 'loopback' and worker['live_network'] is False
    assert worker['blocked_external_operations'] == [] and worker['refused_model_requests'] == 0
    assert worker['refused_requests'] == [] and worker['unfinished_workers'] == 0
    assert 1 <= worker['max_inflight_sec'] <= 4
    assert {(r['pipeline'], r['response_mode']) for r in worker['routing']} == {('investment_thesis', 'source_evidence')}
    # Runtime values are used on the wire and never stored.
    for path in output.rglob('*'):
        if path.is_file():
            content = path.read_bytes()
            assert LOOPBACK_CONTACT.encode() not in content and ZERO_MODEL_PLACEHOLDER.encode() not in content


@needs_port
@pytest.mark.timeout(120)
def test_an_unpinned_certificate_halts_before_any_request_is_served(tmp_path):
    base = tmp_path.resolve()
    with LoopbackSEC(base, untrusted=True) as sec:
        result = run_loopback_rehearsal(base / 'run', ca=sec.ca_path)
    packet = result['packet']
    assert result['status'] == 'halted' and packet['halt'] == 'post_claim_failure'
    assert packet['first_failure']['code'] == 'connect_error'
    assert sec.handshake_failures >= 1 and sec.requests == []
    assert [c['status'] for c in packet['cases']] == ['halted'] + ['not_run_after_halt'] * 11
    assert all(a['response'] is None for a in packet['attempts'])


@needs_port
@pytest.mark.timeout(180)
def test_the_output_directory_holds_only_the_declared_inventory(loopback):
    _, _, output = loopback
    assert {p.name for p in output.iterdir()} <= set(launcher.OUTPUT_INVENTORY)
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    for empty in ('isolated-home', '.clearSignal_timeline', '.clearSignal_watchlist'):
        assert not (output / empty).exists() or not any((output / empty).iterdir()), empty
    with sqlite3.connect(output / 'ledger.sqlite') as db:
        tables = sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    assert tables == sorted(launcher.LEDGER_TABLES)


def test_every_named_enforcing_test_exists():
    root = Path(__file__).resolve().parents[1]
    for entry in launcher.ENFORCED_BY:
        path, _, name = entry.partition('::')
        assert (root / path).is_file(), path
        assert not name or f'def {name}(' in (root / path).read_text(), entry


def test_evidence_templates_carry_derived_facts_and_require_attestations():
    for kind in ('cost', 'retention'):
        template = launcher.evidence_template(kind, '0.00' if kind == 'cost' else None)
        assert template['derived'] == launcher.derived_evidence(kind)
        with pytest.raises(BudgetError):
            launcher.validate_evidence(kind, template, all_in_usd='0.00')
    cost = launcher.derived_evidence('cost')
    assert cost['sec_gets_maximum'] == 66 and cost['model_attempts'] == cost['paid_provider_attempts'] == 0
    assert cost['transport_retries'] == 0 and cost['follow_redirects'] is False


def test_committed_evidence_templates_match_the_code():
    root = Path(__file__).resolve().parents[1] / 'docs/ordinary-evidence'
    for kind in ('cost', 'retention'):
        committed = json.loads((root / f'{kind}-evidence.template.json').read_text())
        assert committed == launcher.evidence_template(kind, None), kind


def test_live_modes_require_an_approval_of_their_own_kind(tmp_path):
    from validation._ordinary_rehearsal_worker import live_request_allowed
    from validation.ordinary_isolated_rehearsal import rehearsal_policy
    output = tmp_path.resolve()
    policy = rehearsal_policy(output)
    assert live_request_allowed(policy, 'loopback', output)
    assert not live_request_allowed(policy, 'approved', output)  # a TEST-ONLY approval never goes live
    assert not live_request_allowed(policy, 'loopback', output / 'elsewhere')
    real = json.loads(json.dumps(policy).replace(TEST_ONLY, 'REVIEW-2026-0001'))
    assert live_request_allowed(real, 'approved', output) and not live_request_allowed(real, 'loopback', output)


@pytest.mark.timeout(120)
@pytest.mark.parametrize('mode,placeholder', [
    ('loopback', 'sk-invented-model-credential'),   # a model credential is never accepted
    ('approved', ZERO_MODEL_PLACEHOLDER),            # a TEST-ONLY approval never runs live
])
def test_the_worker_refuses_a_live_mode_before_any_ledger_or_socket(tmp_path, mode, placeholder):
    from validation.ordinary_isolated_rehearsal import rehearsal_policy, run_worker
    from validation.ordinary_native_ledger import create_fresh_output
    output = create_fresh_output(tmp_path.resolve() / 'run')
    runtime = {'OPENAI_API_KEY': placeholder, 'SEC_USER_AGENT': LOOPBACK_CONTACT}
    result = run_worker(output, rehearsal_policy(output), mode=mode, scenario=mode, environment=runtime,
                        forbidden=tuple(runtime.values()), synthetic=True)
    assert result['status'] == 'worker_incomplete' and result['supervisor']['returncode'] == 2
    assert result['cases'] == [{'case_id': case, 'status': 'not_run'} for case in CASES]
    assert not (output / 'ledger.sqlite').exists()


def test_only_the_gate_admits_a_socket_and_only_in_a_live_mode():
    from validation._ordinary_rehearsal_worker import gate_admits

    class Gate:
        def __init__(self, admits):
            self.admits = admits

        def audit(self, event, args):
            if not self.admits:
                raise BudgetError('network outside owned claimed exchange')

    class Boundary:
        def __init__(self, admits):
            self.gate = Gate(admits)

    event = ('socket.connect', (None, ('127.0.0.1', 8080)))
    assert gate_admits(True, [object(), Boundary(True)], *event)
    assert not gate_admits(True, [object(), Boundary(False)], *event)  # refused by the gate
    assert not gate_admits(False, [object(), Boundary(True)], *event)  # rehearsal: never
    assert not gate_admits(True, [object()], *event)                   # before the boundary exists


# -- the approval-gated launcher: prepare, check, single-use execution -------------

ATTESTED = 'Reviewed by the operator; reference REVIEW-2026-0001 section 3'


@pytest.fixture
def approved_inputs(tmp_path, monkeypatch):
    """A complete invented package and approval, and a host configured for it."""
    base = tmp_path.resolve()
    ca = base / 'reviewed-ca.pem'
    ca.write_bytes(b'-----BEGIN CERTIFICATE-----\ninvented\n-----END CERTIFICATE-----\n')
    from validation.ordinary_isolated_rehearsal import execution_configuration
    execution = execution_configuration(ca, documentation_reference='NETWORK-REVIEW-2026-0001',
                                        verification_reference='PROXY-VERIFICATION-2026-0001')
    files = {'execution': base / 'execution.json', 'cost': base / 'cost.json',
             'retention': base / 'retention.json', 'package': base / 'package.json',
             'approval': base / 'approval.json'}
    files['execution'].write_text(json.dumps(execution))
    for kind in ('cost', 'retention'):
        document = launcher.evidence_template(kind, '0.00' if kind == 'cost' else None)
        document['operator_attestations'] = dict.fromkeys(document['operator_attestations'], ATTESTED)
        files[kind].write_text(json.dumps(document))
    output = base / 'approved-run'
    package = launcher.prepare(execution_path=files['execution'], cost_path=files['cost'],
                               retention_path=files['retention'], output_dir=output)
    files['package'].write_text(json.dumps(package))
    approval = {'reference': 'APPROVAL-2026-0001', 'run_id': 'ORDINARY-2026-0001', 'output_dir': str(output),
                'manifest_sha256': digest(package), 'all_in_usd': '0.00',
                'execution_allowed': True, 'spending_authorized': True}
    files['approval'].write_text(json.dumps(approval))
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        monkeypatch.setenv(name, 'http://proxy:8080')
    for name in ('SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE'):
        monkeypatch.setenv(name, str(ca))
    monkeypatch.setenv('OPENAI_API_KEY', ZERO_MODEL_PLACEHOLDER)
    monkeypatch.setenv('SEC_USER_AGENT', 'Invented Operator operator@example.invalid')
    for name in ('FMP_API_KEY', 'FRED_API_KEY', 'NEWS_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    paths = dict(package_path=files['package'], approval_path=files['approval'],
                 cost_path=files['cost'], retention_path=files['retention'])
    return paths, files, output


def _rewrite(path, change):
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


@pytest.mark.parametrize('mutation', [
    'approval_digest', 'approval_not_allowed', 'approval_spending', 'approval_amount', 'approval_test_only',
    'approval_other_directory', 'package_code_drift', 'package_amount', 'cost_attestation_missing',
    'cost_derived_changed', 'retention_attestation_pending', 'evidence_bytes_changed', 'output_exists',
    'model_credential', 'paid_provider_key', 'sec_contact_missing', 'proxy_changed', 'ca_bytes_changed',
])
def test_run_refuses_every_unapproved_or_drifted_input(approved_inputs, monkeypatch, mutation):
    paths, files, output = approved_inputs
    policy, runtime = launcher.check(**paths)  # the complete invented inputs pass
    assert policy['approval']['reference'] == 'APPROVAL-2026-0001' and not output.exists()
    assert runtime == {'OPENAI_API_KEY': ZERO_MODEL_PLACEHOLDER,
                       'SEC_USER_AGENT': 'Invented Operator operator@example.invalid'}
    approval, package = files['approval'], files['package']
    changes = {
        'approval_digest': lambda: _rewrite(approval, lambda a: a.update(manifest_sha256='0' * 64)),
        'approval_not_allowed': lambda: _rewrite(approval, lambda a: a.update(execution_allowed=False)),
        'approval_spending': lambda: _rewrite(approval, lambda a: a.update(spending_authorized=False)),
        'approval_amount': lambda: _rewrite(approval, lambda a: a.update(all_in_usd='1.00')),
        'approval_test_only': lambda: _rewrite(approval, lambda a: a.update(reference=TEST_ONLY)),
        'approval_other_directory': lambda: _rewrite(approval, lambda a: a.update(output_dir=str(output) + '-2')),
        'package_code_drift': lambda: _rewrite(package, lambda p: p['code_binding'].update(source_sha256='0' * 64)),
        'package_amount': lambda: _rewrite(package, lambda p: p['proposal'].update(all_in_usd='5.00')),
        'cost_attestation_missing': lambda: _rewrite(
            files['cost'], lambda d: d['operator_attestations'].update(compute_host_cost_reference=None)),
        'cost_derived_changed': lambda: _rewrite(files['cost'], lambda d: d['derived'].update(sec_gets_maximum=67)),
        'retention_attestation_pending': lambda: _rewrite(
            files['retention'], lambda d: d['operator_attestations'].update(retention_period='pending review')),
        'evidence_bytes_changed': lambda: files['retention'].write_text(files['retention'].read_text() + ' '),
        'output_exists': lambda: output.mkdir(mode=0o700),
        'model_credential': lambda: monkeypatch.setenv('OPENAI_API_KEY', 'sk-invented-not-a-placeholder'),
        'paid_provider_key': lambda: monkeypatch.setenv('FMP_API_KEY', 'invented'),
        'sec_contact_missing': lambda: monkeypatch.delenv('SEC_USER_AGENT'),
        'proxy_changed': lambda: monkeypatch.setenv('HTTPS_PROXY', 'http://elsewhere:8080'),
        'ca_bytes_changed': lambda: Path(os.environ['SSL_CERT_FILE']).write_bytes(b'changed'),
    }
    changes[mutation]()
    with pytest.raises(BudgetError):
        launcher.check(**paths)


def test_run_without_execute_only_checks(approved_inputs, monkeypatch):
    paths, files, output = approved_inputs
    monkeypatch.setattr(launcher, 'run_worker', lambda *a, **k: pytest.fail('worker launched'))
    code = launcher.main(['run', '--package', str(files['package']), '--approval', str(files['approval']),
                          '--cost-evidence', str(files['cost']), '--retention-evidence', str(files['retention'])])
    assert code == 0 and not output.exists()


def test_an_approval_executes_at_most_once(approved_inputs, monkeypatch):
    paths, files, output = approved_inputs
    calls = []

    def recorded(out, policy, **kwargs):
        calls.append(kwargs)
        return {'status': 'complete', 'packet': None, 'supervisor': {}}
    monkeypatch.setattr(launcher, 'run_worker', recorded)
    result = launcher.execute(**paths)
    assert result['output_dir'] == str(output) and output.is_dir()
    assert calls == [{'mode': 'approved', 'scenario': 'approved', 'synthetic': False,
                      'environment': {'OPENAI_API_KEY': ZERO_MODEL_PLACEHOLDER,
                                      'SEC_USER_AGENT': 'Invented Operator operator@example.invalid'},
                      'forbidden': (ZERO_MODEL_PLACEHOLDER, 'Invented Operator operator@example.invalid')}]
    with pytest.raises(BudgetError):
        launcher.execute(**paths)  # the directory now exists: the approval is spent
    assert len(calls) == 1


@pytest.mark.parametrize('kind,change', [
    ('cost', lambda d: d['derived'].update(model_attempts=1)),
    ('retention', lambda d: d['derived'].update(output_directory_mode='0755')),
    ('cost', lambda d: d['operator_attestations'].update(proxy_and_egress_cost_reference='TBD by finance')),
    ('retention', lambda d: d['operator_attestations'].update(deletion_procedure=None)),
])
def test_prepare_refuses_tampered_or_unfinished_evidence(approved_inputs, kind, change):
    _, files, output = approved_inputs
    _rewrite(files[kind], change)
    with pytest.raises(BudgetError):
        launcher.prepare(execution_path=files['execution'], cost_path=files['cost'],
                         retention_path=files['retention'], output_dir=output.parent / 'other-run')


def test_check_refuses_a_ceiling_other_than_the_cost_evidence(approved_inputs):
    # Package and approval agree with each other on 5.00; the cost review said 0.00.
    paths, files, _ = approved_inputs
    _rewrite(files['package'], lambda p: p['proposal'].update(all_in_usd='5.00'))
    package = json.loads(files['package'].read_text())
    _rewrite(files['approval'], lambda a: a.update(all_in_usd='5.00', manifest_sha256=digest(package)))
    with pytest.raises(BudgetError):
        launcher.check(**paths)


def test_prepare_refuses_test_only_or_incomplete_inputs(approved_inputs):
    _, files, output = approved_inputs
    execution = json.loads(files['execution'].read_text())
    execution['verification_reference'] = TEST_ONLY + '-review'
    files['execution'].write_text(json.dumps(execution))
    with pytest.raises(BudgetError):
        launcher.prepare(execution_path=files['execution'], cost_path=files['cost'],
                         retention_path=files['retention'], output_dir=output.parent / 'other-run')
