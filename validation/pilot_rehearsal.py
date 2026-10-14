"""Launch the actual pilot pipeline in a credential-isolated, no-network child.

Only this launcher is public. It never imports application modules or reads
environment/credential values. There is no execute, resume, tariff or key option.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

from validation.capture_budget import AttemptLedger, BudgetError, digest
from validation.pilot_fixtures import SOURCE_MONITORING_SCENARIOS, LIVE_SCENARIOS, SCENARIOS, SYNTHETIC_CONTACT, SYNTHETIC_KEY
from validation.pilot_policy import AUDITED_DEPENDENCIES, RUN_DEADLINE_SECONDS, policy_for


ROOT = Path(__file__).resolve().parents[1]


def source_binding():
    # Explicit code extensions and directories: never .env, configuration
    # stores, credential files, generated logs, request headers or artifacts.
    files = sorted([*ROOT.joinpath('app').rglob('*.py'), *ROOT.joinpath('validation').glob('*.py')])
    if any(path.is_symlink() for path in files):
        raise BudgetError('symlinked rehearsal source is unsupported')
    return digest({str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in files})


def prepare_policy(*, mode="offline", approval=None, execution=None):
    if sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 11, 9):
        raise BudgetError('rehearsal requires the audited CPython 3.11.9 runtime')
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                              env={'PATH': '/usr/bin:/bin'}, capture_output=True,
                              text=True, check=True).stdout.strip()
    dependencies = {name: importlib.metadata.version(name) for name in AUDITED_DEPENDENCIES}
    return policy_for({'revision': revision, 'source_sha256': source_binding()}, dependencies, mode=mode, approval=approval, execution=execution)


def run_rehearsal(output_dir, *, scenario='happy', mode='offline', approval=None, execution=None):
    approved = mode in {'approved', 'approved_source_monitoring'}
    scenarios = ({'approved'} if approved else SOURCE_MONITORING_SCENARIOS
                 if mode == 'source_monitoring' else LIVE_SCENARIOS
                 if mode == 'live_adapter_validation' else SCENARIOS)
    if type(scenario) is not str or scenario not in scenarios:
        raise BudgetError('unknown immutable rehearsal scenario')
    policy = prepare_policy(mode=mode, approval=approval, execution=execution)
    if approved:
        from validation.pilot_approved import runtime_values, verify_network_configuration
        verify_network_configuration(execution)
        runtime = runtime_values()
    output = Path(output_dir).resolve()
    if approved and str(output) != approval['output_dir']:
        raise BudgetError('approval is bound to one fresh output directory')
    output.mkdir(parents=False, exist_ok=False)  # No overwrite, resume or reset.
    isolated_home = output / 'isolated-home'
    isolated_home.mkdir(mode=0o700)
    request = {'policy': policy, 'scenario': scenario}
    (output / 'request.json').write_text(json.dumps(request, sort_keys=True))
    # Construct from constants; do not copy, print, hash or inspect the caller's
    # environment. The key/contact here are invented fixtures, never real values.
    environment = {'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1',
                   'DECISION_MONITORING_INPUTS_ENABLED': str(policy['configuration']['settings']['decision_monitoring_inputs_enabled']).lower(),
                   'HOME': str(isolated_home),
                   'OPENAI_API_KEY': SYNTHETIC_KEY, 'SEC_USER_AGENT': SYNTHETIC_CONTACT,
                   'CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED': 'false'}
    if approved:
        environment.update(OPENAI_API_KEY=runtime['bearer_placeholder'], SEC_USER_AGENT=runtime['sec_contact'])
        for name in execution['proxy_selectors']:
            environment[name] = execution['proxy']
        for name in execution['ca_selectors']:
            environment[name] = execution['ca_identity']['path']
    code = ('import sys; sys.path.insert(0, ' + repr(str(ROOT)) + '); '
            'from validation._pilot_worker import main; raise SystemExit(main())')
    try:
        child = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=output,
                               env=environment, capture_output=True, timeout=RUN_DEADLINE_SECONDS)
        failed = child.returncode != 0
    except subprocess.TimeoutExpired:
        failed = True
    # Worker stdout/stderr are never persisted or echoed: only a sanitized
    # artifact can leave the child. A crash cannot create or restart a ledger.
    artifact_path = output / 'artifact.json'
    if failed or not artifact_path.is_file():
        ledger_path = output / 'ledger.sqlite'
        summary = None
        if ledger_path.is_file():
            try:
                summary = AttemptLedger(ledger_path, policy).summary()
            except (BudgetError, OSError):
                pass
        artifact = {'artifact_type': ('disabled_live_adapter_validation' if mode == 'live_adapter_validation'
                                     else 'integrated_offline_pilot_rehearsal'),
                    'status': 'worker_incomplete', 'ledger': summary,
                    'code_binding': policy['code_binding'], 'policy_sha256': digest(policy),
                    'execution_allowed': False, 'spending_authorized': False,
                    'tariffs_verified': False, 'hard_usd_cap_established': False,
                    'launch_ready': False, 'quality_status': 'not_adjudicated',
                    'external_dispatches': 0, 'network_attempts': None}
        if mode == 'source_monitoring':
            artifact['artifact_type'] = 'disabled_source_monitoring_validation'
        if approved:
            artifact.update(artifact_type=policy['purpose'], execution_allowed=True,
                            spending_authorized=True, approval_reference=approval['reference'],
                            external_dispatches=None,
                            usage_source='provider_reported_protocol_units_not_invoice',
                            dispatch_count_status='worker_incomplete_unknown; consult durable claims')
        # Exclusive publication; never replace a prior artifact with a success.
        if not artifact_path.exists():
            with artifact_path.open('x') as stream:
                json.dump(artifact, stream, indent=2)
        else:
            # Preserve the published terminal evidence byte-for-byte. The
            # launcher verdict is separate so an abnormal exit cannot turn
            # a worker's publication into success or erase its diagnostics.
            try:
                terminal = json.loads(artifact_path.read_text())
                if type(terminal) is dict:
                    artifact['worker_terminal_evidence'] = terminal
            except (ValueError, OSError):
                pass
            with (output / 'launcher-failure.json').open('x') as stream:
                json.dump(artifact, stream, indent=2)
        return artifact
    return json.loads(artifact_path.read_text())


def main(argv=None, *, mode="offline"):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--scenario', choices=sorted(SOURCE_MONITORING_SCENARIOS if mode == 'source_monitoring' else LIVE_SCENARIOS if mode == 'live_adapter_validation' else SCENARIOS), default='happy')
    args = parser.parse_args(argv)
    try:
        result = run_rehearsal(args.output_dir, scenario=args.scenario, mode=mode)
    except Exception:
        parser.exit(2, 'Offline rehearsal refused; no execution or reset authorized.\n')
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
