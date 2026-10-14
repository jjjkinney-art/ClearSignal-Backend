"""Invented authority only; all transport underneath the gate is synthetic."""
from copy import deepcopy
from unittest.mock import Mock
import httpx
import pytest

from test_pilot_approved import CONFIG, BINDING, synthetic_runtime
from validation.capture_budget import AttemptLedger, BudgetError, digest, validate_policy
from validation.pilot_approved import ApprovedBoundary, manifest_for, validate_approval
from validation.pilot_source_monitoring_approved import main
from validation.pilot_policy import AUDITED_DEPENDENCIES, MODEL_ROUTES, policy_for
from validation._pilot_wire_fixtures import SyntheticProxyBackend


def authority(path='/tmp/TEST-ONLY-monitoring', monitoring=True):
    return {'reference': 'TEST-ONLY-NOT-REAL-APPROVAL', 'run_id': 'TEST-ONLY-monitoring',
            'manifest_sha256': digest(manifest_for(BINDING, CONFIG, path, monitoring=monitoring)),
            'output_dir': path, 'execution_allowed': True, 'spending_authorized': True}


def policy():
    return policy_for(BINDING, dict(AUDITED_DEPENDENCIES), mode='approved_source_monitoring',
                      approval=authority(), execution=CONFIG)


@pytest.fixture
def owner(tmp_path):
    boundary = ApprovedBoundary(AttemptLedger(tmp_path/'ledger.sqlite', policy(), create=True))
    boundary.wire._wire._pool._network_backend.backend = SyntheticProxyBackend(boundary)
    boundary.begin(boundary.cases[1]); boundary.stage.set('evidence.sec')
    yield boundary
    boundary.close()


def test_separate_manifest_and_fixed_zero_model_policy():
    manifest = manifest_for(BINDING, CONFIG, '/tmp/TEST-ONLY-monitoring', monitoring=True)
    assert manifest['purpose'] == 'approved_source_monitoring_pilot'
    assert manifest['model_attempts'] == 0 and manifest['sec_gets'] == 33
    assert manifest['illustrative_model_allocation_usd'] == '0'
    assert not manifest['invoice_ceiling_established']
    p = policy(); validate_policy(p)
    assert p['configuration']['settings']['decision_monitoring_inputs_enabled'] is True
    assert p['quotas']['overall'] == {'model': 0, 'sec': 33}
    assert all(case[route] == 0 for case in p['quotas']['per_case'].values() for route in MODEL_ROUTES)


@pytest.mark.parametrize('monitoring', [True, False])
def test_cross_variant_approval_cannot_authorize_the_other_policy(monitoring):
    with pytest.raises(BudgetError):
        validate_approval(authority(monitoring=not monitoring), BINDING, CONFIG, monitoring=monitoring)


@pytest.mark.parametrize('field,value', [('execution_allowed', False), ('spending_authorized', False),
                                     ('manifest_sha256', 'wrong'), ('output_dir', '/tmp/OTHER')])
def test_missing_or_mismatched_authority_fails_closed(field, value):
    approved = authority(); approved[field] = value
    with pytest.raises(BudgetError):
        policy_for(BINDING, dict(AUDITED_DEPENDENCIES), mode='approved_source_monitoring',
                   approval=approved, execution=CONFIG)


def test_policy_quota_and_configuration_mutation_rejected():
    for mutate in (lambda p: p['quotas']['overall'].update(model=1),
                   lambda p: p['configuration']['settings'].update(decision_monitoring_inputs_enabled=False),
                   lambda p: p['quotas']['per_case']['ASML:decision_threshold'].update({'sec/document': 1})):
        p = deepcopy(policy()); mutate(p)
        with pytest.raises(BudgetError): validate_policy(p)


def test_missing_approval_never_launches_or_reads_runtime(tmp_path, monkeypatch):
    from validation import pilot_rehearsal, pilot_approved
    launch = Mock(side_effect=AssertionError('no launch'))
    runtime = Mock(side_effect=AssertionError('no credential read'))
    monkeypatch.setattr(pilot_rehearsal, 'run_rehearsal', launch)
    monkeypatch.setattr(pilot_approved, 'runtime_values', runtime)
    with pytest.raises(SystemExit) as exc:
        main(['--manifest', str(tmp_path/'missing'), '--output-dir', str(tmp_path/'fresh')])
    assert exc.value.code == 2 and not launch.called and not runtime.called
    assert not (tmp_path/'fresh').exists()


def test_sec_dispatch_settles_and_cannot_reuse_grant(owner):
    owner.sec_exchange('GET', 'https://www.sec.gov/files/company_tickers.json', None)
    assert owner.gate.dispatched == 1
    assert owner.ledger.summary()['unresolved_attempts'] == 0
    assert owner.ledger.summary()['executable_provider_adapter'] is True
    with pytest.raises(BudgetError):
        owner.sec_exchange('GET', 'https://www.sec.gov/files/company_tickers.json', None)
    assert owner.gate.dispatched == 1


@pytest.mark.parametrize('stage', ['valuation', 'macro', 'risk', 'market', 'quality', 'question_answerer', 'synthesis'])
def test_model_quota_refuses_before_any_exchange(owner, stage, monkeypatch):
    owner.stage.set(stage)
    wire = Mock(side_effect=AssertionError('no model wire'))
    monkeypatch.setattr(owner.wire, 'exchange', wire)
    payload = {'model': 'gpt-4o-mini', 'messages': [{'role':'user','content':'Invented'}],
               'temperature': 0, 'max_tokens': 1536 if stage=='synthesis' else 4096,
               'service_tier':'default','n':1,'stream':False}
    request = httpx.Request('POST','https://api.openai.com/v1/chat/completions',json=payload,
                           extensions={'timeout': dict.fromkeys(('connect','read','write','pool'),55.0 if stage=='synthesis' else 15.0)})
    with pytest.raises(BudgetError): owner.model_request(request)
    assert not wire.called and owner.gate.dispatched == 0


def test_openai_host_is_excluded_even_with_a_sec_claim(owner):
    fingerprint = digest({'method': 'GET', 'url': 'https://www.sec.gov/files/company_tickers.json',
                          'route': 'sec/directory', 'stage': owner.stage.get()})
    owner.claim('sec/directory', fingerprint, 0, 0)
    with pytest.raises(BudgetError):
        with owner.dispatch('https://api.openai.com/v1/chat/completions', fingerprint):
            raise AssertionError('must not enter exchange')
    assert owner.gate.dispatched == 0


def test_preparation_never_reads_runtime_or_creates_output(tmp_path, monkeypatch):
    import json
    from validation import pilot_approved
    runtime = Mock(side_effect=AssertionError('no credential read'))
    monkeypatch.setattr(pilot_approved, 'runtime_values', runtime)
    manifest = tmp_path/'pending.json'; output = tmp_path/'fresh'
    assert main(['--prepare', '--manifest', str(manifest), '--output-dir', str(output)]) == 0
    data = json.loads(manifest.read_text())
    assert data['purpose'] == 'approved_source_monitoring_pilot'
    assert data['model_attempts'] == 0 and data['sec_gets'] == 33
    assert not runtime.called and not output.exists()


def test_actual_approved_worker_completes_with_synthetic_sec_only(tmp_path, monkeypatch):
    # Replace only native I/O in the child before main. All actual policy,
    # approval, isolated environment, claim/grant and terminal paths remain.
    from validation import pilot_rehearsal
    original = pilot_rehearsal.subprocess.run
    injected = '''
import sys
def deny_test_sockets(event, args):
    if event.startswith('socket.'):
        raise AssertionError('synthetic approved-worker test forbids sockets')
sys.addaudithook(deny_test_sockets)
from validation.pilot_approved import ApprovedBoundary
from validation._pilot_wire_fixtures import SyntheticProxyBackend
original_init = ApprovedBoundary.__init__
def synthetic_init(self, ledger):
    original_init(self, ledger)
    self.wire._wire._pool._network_backend.backend = SyntheticProxyBackend(self)
ApprovedBoundary.__init__ = synthetic_init
'''
    def run(args, *a, **kw):
        if '-c' in args and 'from validation._pilot_worker import main' in args[-1]:
            args = list(args)
            prefix, suffix = args[-1].split('from validation._pilot_worker import main', 1)
            # Suppress urllib3's import-time socket construction before the
            # transport imports; the audit denies all later socket operations.
            args[-1] = prefix + '\nimport socket; socket.has_ipv6 = False\n' + injected + '\nfrom validation._pilot_worker import main' + suffix
        return original(args, *a, **kw)
    monkeypatch.setattr(pilot_rehearsal.subprocess, 'run', run)
    binding = pilot_rehearsal.prepare_policy()['code_binding']
    output = str((tmp_path/'fresh').resolve())
    approved = authority(output)
    approved['manifest_sha256'] = digest(manifest_for(binding, CONFIG, output, monitoring=True))
    result = pilot_rehearsal.run_rehearsal(output, scenario='approved', mode='approved_source_monitoring',
                                         approval=approved, execution=CONFIG)
    assert result['status'] == 'complete'
    assert result['artifact_type'] == 'approved_source_monitoring_pilot'
    assert len(result['completed_cases']) == 6
    assert not result['ledger']['halted'] and result['ledger']['unresolved_attempts'] == 0
    assert all(not row['route'].startswith('model/') for row in result['claims'])
    assert result['illustrative_maximum_model_allocation_usd'] == '0'
    assert result['diagnostics_canary_clean']
    assert result['sec_authorization_header_absent']
    assert len(result['logical_tasks']) == 54
