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
from validation.pilot_fixtures import SCENARIOS, SYNTHETIC_CONTACT, SYNTHETIC_KEY
from validation.pilot_policy import AUDITED_DEPENDENCIES, policy_for


ROOT = Path(__file__).resolve().parents[1]


def source_binding():
    # Explicit code extensions and directories: never .env, configuration
    # stores, credential files, generated logs, request headers or artifacts.
    files = sorted([*ROOT.joinpath('app').rglob('*.py'), *ROOT.joinpath('validation').glob('*.py')])
    if any(path.is_symlink() for path in files):
        raise BudgetError('symlinked rehearsal source is unsupported')
    return digest({str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in files})


def prepare_policy():
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                              env={'PATH': '/usr/bin:/bin'}, capture_output=True,
                              text=True, check=True).stdout.strip()
    dependencies = {name: importlib.metadata.version(name) for name in AUDITED_DEPENDENCIES}
    return policy_for({'revision': revision, 'source_sha256': source_binding()}, dependencies)


def run_rehearsal(output_dir, *, scenario='happy'):
    if type(scenario) is not str or scenario not in SCENARIOS:
        raise BudgetError('unknown immutable rehearsal scenario')
    policy = prepare_policy()
    output = Path(output_dir).resolve()
    output.mkdir(parents=False, exist_ok=False)  # No overwrite, resume or reset.
    request = {'policy': policy, 'scenario': scenario}
    (output / 'request.json').write_text(json.dumps(request, sort_keys=True))
    # Construct from constants; do not copy, print, hash or inspect the caller's
    # environment. The key/contact here are invented fixtures, never real values.
    environment = {'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1',
                   'OPENAI_API_KEY': SYNTHETIC_KEY, 'SEC_USER_AGENT': SYNTHETIC_CONTACT,
                   'CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED': 'false'}
    code = ('import sys; sys.path.insert(0, ' + repr(str(ROOT)) + '); '
            'from validation._pilot_worker import main; raise SystemExit(main())')
    try:
        child = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=output,
                               env=environment, capture_output=True, timeout=120)
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
        artifact = {'artifact_type': 'integrated_offline_pilot_rehearsal',
                    'status': 'worker_incomplete', 'ledger': summary,
                    'code_binding': policy['code_binding'], 'policy_sha256': digest(policy),
                    'execution_allowed': False, 'spending_authorized': False,
                    'tariffs_verified': False, 'hard_usd_cap_established': False,
                    'launch_ready': False, 'quality_status': 'not_adjudicated',
                    'external_dispatches': 0, 'network_attempts': None}
        # Exclusive publication; never replace a prior artifact with a success.
        if not artifact_path.exists():
            with artifact_path.open('x') as stream:
                json.dump(artifact, stream, indent=2)
        else:
            # A nonzero exit after publication is incomplete too; never return
            # a different state than the on-disk review artifact.
            artifact_path.write_text(json.dumps(artifact, indent=2))
        return artifact
    return json.loads(artifact_path.read_text())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--scenario', choices=sorted(SCENARIOS), default='happy')
    args = parser.parse_args(argv)
    try:
        result = run_rehearsal(args.output_dir, scenario=args.scenario)
    except Exception:
        parser.exit(2, 'Offline rehearsal refused; no execution or reset authorized.\n')
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
