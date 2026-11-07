"""Fresh-process twelve-case rehearsals over the native ordinary stack.

Offline demonstrations only. The approval here is an invented TEST-ONLY record
bound to the code, dependencies and CA identity actually present; it grants
nothing. ``run_rehearsal`` uses the synthetic SEC backend with every socket
refused. ``run_loopback_rehearsal`` drives the live code path (real sockets,
proxy CONNECT or direct TLS, certificate verification) against a loopback test
server the caller runs on 127.0.0.1, trusting only the caller's test CA. There is no resume
or reset option; the approval-gated live launcher is ordinary_approved.py.
"""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

from validation.capture_budget import BudgetError, digest
from validation.ordinary_native_export import export_packet, record_parent_stop
from validation.ordinary_native_ledger import create_fresh_output
from validation.ordinary_native_policy import TEST_ONLY, ZERO_MODEL_PLACEHOLDER
from validation.ordinary_pilot_contract import CASES
from validation.ordinary_process_supervisor import supervise
from validation.pilot_policy import AUDITED_DEPENDENCIES

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ('happy', 'wire_read_failure', 'wire_redirect', 'wire_oversize', 'wire_connect_failure',
             'core_deadline', 'threshold_deadline', 'evidence_abandoned')
LOOPBACK_CONTACT = 'Ordinary loopback fixture loopback@example.invalid'


def require_runtime():
    if (sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 11, 9)
            or {name: importlib.metadata.version(name) for name in AUDITED_DEPENDENCIES}
            != dict(AUDITED_DEPENDENCIES)):
        raise BudgetError('ordinary runtime refused')


def git_revision():
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, env={'PATH': '/usr/bin:/bin'},
                          capture_output=True, text=True, check=True).stdout.strip()


def execution_configuration(ca, *, documentation_reference, verification_reference):
    """The reviewed proxy configuration naming one CA bundle by path and hash."""
    ca = Path(ca)
    return {'documentation_reference': documentation_reference,
            'verification_reference': verification_reference,
            'substitution': 'explicit_environment_proxy', 'bearer_source': 'OPENAI_API_KEY',
            'sec_contact_source': 'SEC_USER_AGENT', 'proxy': 'http://proxy:8080',
            'proxy_selectors': ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'],
            'ca_selectors': ['SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE'],
            'ca_identity': {'path': str(ca), 'sha256': hashlib.sha256(ca.read_bytes()).hexdigest()},
            'contains_no_credentials': True}


def direct_execution_configuration(ca, *, documentation_reference, verification_reference):
    """The reviewed direct-TLS configuration: no proxy, one pinned CA bundle."""
    ca = Path(ca)
    return {'documentation_reference': documentation_reference,
            'verification_reference': verification_reference,
            'substitution': 'direct_tls', 'proxy': None, 'sec_contact_source': 'SEC_USER_AGENT',
            'ca_selectors': ['SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE'],
            'ca_identity': {'path': str(ca), 'sha256': hashlib.sha256(ca.read_bytes()).hexdigest()},
            'contains_no_credentials': True}


def rehearsal_policy(output, *, ca=None, network='proxy'):
    """Bind an invented approval to the running code, packages and CA bundle."""
    import certifi
    from validation.ordinary_native_policy import execution_package, policy_for
    from validation.pilot_rehearsal import source_binding
    build = direct_execution_configuration if network == 'direct' else execution_configuration
    execution = build(Path(ca or certifi.where()).resolve(), documentation_reference=TEST_ONLY + '-network',
                      verification_reference=TEST_ONLY + '-review')
    values = dict(cases=json.loads((ROOT / 'tests/ordinary_pilot_cases.json').read_text()),
                  code_binding={'revision': git_revision(), 'source_sha256': source_binding()},
                  dependencies={name: importlib.metadata.version(name) for name in AUDITED_DEPENDENCIES},
                  execution=execution, all_in_usd='0.00', retention_reference=TEST_ONLY + '-retention',
                  pricing_review_reference=TEST_ONLY + '-pricing')
    approval = {'reference': TEST_ONLY, 'run_id': TEST_ONLY + '-rehearsal', 'output_dir': str(output),
                'manifest_sha256': digest(execution_package(output_dir=str(output), **values)),
                'all_in_usd': '0.00', 'execution_allowed': True, 'spending_authorized': True}
    return policy_for(approval=approval, **values)


def run_worker(output, policy, *, mode, scenario, environment, forbidden, synthetic):
    """Launch the worker once in ``output``, supervise it, and export its ledger.

    The parent's deadlines are authoritative and the child's own report is
    trusted only after a clean exit. Every one of the twelve cases is reported.
    """
    request = {'policy': policy, 'mode': mode}
    if mode == 'rehearsal':
        request['scenario'] = scenario
    with (output / 'request.json').open('x') as stream:
        json.dump(request, stream, sort_keys=True)
    code = ('import sys; sys.path.insert(0, ' + repr(str(ROOT)) + '); '
            'from validation._ordinary_rehearsal_worker import main; raise SystemExit(main())')
    child = supervise([sys.executable, '-I', '-B', '-c', code, scenario], output=output,
                      environment={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1', **environment})
    ledger = output / 'ledger.sqlite'
    result = {'mode': mode, 'execution_authorized': mode == 'approved',
              'synthetic_sec_backend': synthetic, 'supervisor': child, 'denominator': len(CASES),
              'quality_pass_rate': None, 'launch_ready': False, 'invoice_ceiling_verified': False}
    if not ledger.is_file():
        # Refused before any ledger, gate or request: every case is reported.
        result.update(status='worker_incomplete', packet=None, worker=None,
                      cases=[{'case_id': case, 'status': 'not_run'} for case in CASES])
        return result
    if child['stop_reason']:
        # The child was killed and reaped; its own publication is never trusted.
        record_parent_stop(ledger, 'stage_timeout' if child['stop_reason'].endswith('deadline') else 'rehearsal_failure')
    elif child['returncode']:
        record_parent_stop(ledger, 'rehearsal_failure')
    packet = export_packet(ledger, policy, forbidden_values=forbidden, synthetic=synthetic)
    worker = None
    report = output / 'worker.json'
    if not child['stop_reason'] and not child['returncode'] and report.is_file() and not report.is_symlink():
        worker = json.loads(report.read_text())
    if child['stop_reason'] and child['interrupted_case']:
        # The parent's deadline is authoritative. The child anchors its own case
        # clock slightly later (after the acknowledgment), so it can commit an
        # answer the parent has already ruled late; such an answer is rejected.
        late = child['interrupted_case']
        for row in packet['cases']:
            if row['case_id'] == late:
                row['status'] = 'halted'
        if packet['answers'].pop(late, None) is not None:
            packet['late_answers_rejected'] = [late]
        packet['status'] = 'halted'
    status = ('worker_stopped' if child['stop_reason'] else
              'worker_incomplete' if worker is None else packet['status'])
    result.update(status=status, packet=packet, worker=worker)
    return result


def run_rehearsal(output_dir, *, scenario='happy'):
    if type(scenario) is not str or scenario not in SCENARIOS:
        raise BudgetError('ordinary rehearsal runtime or scenario refused')
    require_runtime()
    output = create_fresh_output(output_dir)  # sole owner; never reused
    policy = rehearsal_policy(output)
    from validation._ordinary_rehearsal_worker import REHEARSAL_RUNTIME
    result = run_worker(output, policy, mode='rehearsal', scenario=scenario, environment={},
                        forbidden=tuple(REHEARSAL_RUNTIME.values()), synthetic=True)
    result['approval'] = 'invented_test_only'
    return result


def run_loopback_rehearsal(output_dir, *, ca, network='proxy'):
    """The live code path against the caller's loopback test server: a CONNECT
    proxy on 127.0.0.1:8080, or (network='direct') TLS on 127.0.0.1:8443."""
    if network not in {'proxy', 'direct'}:
        raise BudgetError('unknown loopback network')
    require_runtime()
    output = create_fresh_output(output_dir)
    policy = rehearsal_policy(output, ca=ca, network=network)
    runtime = {'OPENAI_API_KEY': ZERO_MODEL_PLACEHOLDER, 'SEC_USER_AGENT': LOOPBACK_CONTACT}
    result = run_worker(output, policy, mode='loopback', scenario='loopback', environment=runtime,
                        forbidden=tuple(runtime.values()), synthetic=True)
    result['approval'] = 'invented_test_only'
    return result
