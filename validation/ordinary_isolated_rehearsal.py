"""Fresh-process twelve-case rehearsal over the native ordinary stack.

Offline demonstration only. The approval here is an invented TEST-ONLY record
bound to the code, dependencies and CA identity actually present; it grants
nothing. The worker's network backend is always the synthetic SEC backend and
its sockets are refused. There is no live, resume or reset option.
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
from validation.ordinary_pilot_contract import CASES
from validation.ordinary_process_supervisor import supervise
from validation.pilot_policy import AUDITED_DEPENDENCIES

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ('happy', 'wire_read_failure', 'wire_redirect', 'wire_oversize', 'wire_connect_failure',
             'core_deadline', 'threshold_deadline', 'ask_routing')
TEST_ONLY = 'TEST-ONLY-NOT-AN-APPROVAL'


def rehearsal_policy(output):
    """Bind an invented approval to the running code, packages and CA bundle."""
    import certifi
    from validation.ordinary_native_policy import execution_package, policy_for
    from validation.pilot_rehearsal import source_binding
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, env={'PATH': '/usr/bin:/bin'},
                              capture_output=True, text=True, check=True).stdout.strip()
    ca = Path(certifi.where()).resolve()
    execution = {'documentation_reference': TEST_ONLY + '-network', 'verification_reference': TEST_ONLY + '-review',
                 'substitution': 'explicit_environment_proxy', 'bearer_source': 'OPENAI_API_KEY',
                 'sec_contact_source': 'SEC_USER_AGENT', 'proxy': 'http://proxy:8080',
                 'proxy_selectors': ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'],
                 'ca_selectors': ['SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE'],
                 'ca_identity': {'path': str(ca), 'sha256': hashlib.sha256(ca.read_bytes()).hexdigest()},
                 'contains_no_credentials': True}
    values = dict(cases=json.loads((ROOT / 'tests/ordinary_pilot_cases.json').read_text()),
                  code_binding={'revision': revision, 'source_sha256': source_binding()},
                  dependencies={name: importlib.metadata.version(name) for name in AUDITED_DEPENDENCIES},
                  execution=execution, all_in_usd='0.00', retention_reference=TEST_ONLY + '-retention',
                  pricing_review_reference=TEST_ONLY + '-pricing')
    approval = {'reference': TEST_ONLY, 'run_id': TEST_ONLY + '-rehearsal', 'output_dir': str(output),
                'manifest_sha256': digest(execution_package(output_dir=str(output), **values)),
                'all_in_usd': '0.00', 'execution_allowed': True, 'spending_authorized': True}
    return policy_for(approval=approval, **values)


def run_rehearsal(output_dir, *, scenario='happy'):
    if (type(scenario) is not str or scenario not in SCENARIOS
            or sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 11, 9)
            or {name: importlib.metadata.version(name) for name in AUDITED_DEPENDENCIES}
            != dict(AUDITED_DEPENDENCIES)):
        raise BudgetError('ordinary rehearsal runtime or scenario refused')
    output = create_fresh_output(output_dir)  # sole owner; never reused
    policy = rehearsal_policy(output)
    with (output / 'request.json').open('x') as stream:
        json.dump({'policy': policy, 'scenario': scenario}, stream, sort_keys=True)
    code = ('import sys; sys.path.insert(0, ' + repr(str(ROOT)) + '); '
            'from validation._ordinary_rehearsal_worker import main; raise SystemExit(main())')
    child = supervise([sys.executable, '-I', '-B', '-c', code, scenario], output=output,
                      environment={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})
    ledger = output / 'ledger.sqlite'
    result = {'execution_authorized': False, 'approval': 'invented_test_only', 'synthetic_sec_backend': True,
              'supervisor': child, 'denominator': len(CASES), 'quality_pass_rate': None,
              'launch_ready': False, 'invoice_ceiling_verified': False}
    if not ledger.is_file():
        result.update(status='worker_incomplete', packet=None, worker=None)
        return result
    if child['stop_reason']:
        # The child was killed and reaped; its own publication is never trusted.
        record_parent_stop(ledger, 'stage_timeout' if child['stop_reason'].endswith('deadline') else 'rehearsal_failure')
    elif child['returncode']:
        record_parent_stop(ledger, 'rehearsal_failure')
    from validation._ordinary_rehearsal_worker import REHEARSAL_RUNTIME
    packet = export_packet(ledger, policy, forbidden_values=tuple(REHEARSAL_RUNTIME.values()), synthetic=True)
    worker = None
    report = output / 'worker.json'
    if not child['stop_reason'] and not child['returncode'] and report.is_file() and not report.is_symlink():
        worker = json.loads(report.read_text())
    if child['stop_reason'] and child['interrupted_case']:
        for row in packet['cases']:
            if row['case_id'] == child['interrupted_case']:
                row['status'] = 'halted'
    status = ('worker_stopped' if child['stop_reason'] else
              'worker_incomplete' if worker is None else packet['status'])
    result.update(status=status, packet=packet, worker=worker)
    return result
