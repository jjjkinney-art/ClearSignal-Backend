"""Separate, approval-gated two-issuer EPS diagnostic capture; never a pilot resume.

Preparation reads no credentials and performs no network operation. Execution is
confined to an isolated child and requires a separately reviewed single-use file.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from validation.capture_budget import BudgetError, digest
from validation.eps_source_gap_analysis import SOURCES_BY_ISSUER, validate_analysis_date

PURPOSE = 'approved_eps_source_adequacy_capture'
STAGE_SECONDS = 20
DRAIN_SECONDS = 3
WHOLE_SECONDS = 480
# Frozen development-issuer CIKs from issuer_registry.v2.json; no live directory inference.
SOURCES = (
    ('ASML:core_thesis', 'sec/facts', 'evidence.sec_metrics', SOURCES_BY_ISSUER['ASML'],
     16_777_216, 'application/json', 'asml-facts.json'),
    ('NPK:core_thesis', 'sec/facts', 'evidence.sec_metrics', SOURCES_BY_ISSUER['NPK'],
     16_777_216, 'application/json', 'npk-facts.json'),
)


def manifest_for(binding, execution, output_dir, analysis_as_of):
    validate_analysis_date(analysis_as_of)
    return {'schema_version': 1, 'purpose': PURPOSE, 'code_binding': binding,
        'execution_configuration': execution, 'output_dir': str(Path(output_dir).resolve()),
        'sources': [list(s) for s in SOURCES], 'analysis_as_of': analysis_as_of,
        'identity_basis': 'frozen_development_registry_ciks_not_current_directory',
        'model_attempts': 0, 'sec_gets': 2, 'nontransferable_source_slots': True,
        'stage_seconds': STAGE_SECONDS, 'drain_seconds': DRAIN_SECONDS,
        'whole_seconds': WHOLE_SECONDS, 'retain_public_bodies_and_receipts': True,
        'derived_diagnostics_are_admitted_evidence': False,
        'ledger_allowance_usd': '0.52', 'invoice_ceiling_established': False,
        'approval_status': 'pending'}


def validate_approval(approval, binding, execution):
    from validation.pilot_approved import validate_execution
    validate_execution(execution)
    keys = {'reference', 'run_id', 'manifest_sha256', 'output_dir',
            'execution_allowed', 'spending_authorized', 'public_body_retention_authorized', 'analysis_as_of'}
    if (type(approval) is not dict or set(approval) != keys
            or any(approval[k] is not True for k in
                   ('execution_allowed', 'spending_authorized', 'public_body_retention_authorized'))
            or type(approval['output_dir']) is not str
            or approval['output_dir'] != str(Path(approval['output_dir']).resolve())
            or any(type(approval[k]) is not str or not re.fullmatch(
                r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', approval[k]) for k in ('reference', 'run_id'))
            or approval['reference'] in {'pending', 'NO_SPENDING_AUTHORITY'}
            or approval['manifest_sha256'] != digest(manifest_for(binding, execution, approval['output_dir'], approval['analysis_as_of']))):
        raise BudgetError('separate matching capture and public-body retention approval required')


def policy_for(binding, dependencies, approval, execution):
    from validation.pilot_policy import policy_for as pilot_policy
    validate_approval(approval, binding, execution)
    # Derive the existing schema's prices/setup/dependency checks, not its live authority.
    policy = pilot_policy(binding, dependencies, mode='source_monitoring')
    policy.update(purpose=PURPOSE, pilot_id=approval['run_id'], approval_reference=approval['reference'],
                  approval=approval, execution_configuration=execution, execution_allowed=True,
                  spending_authorized=True, maximum_attempts=2,
                  approved_case_ids=[s[0] for s in SOURCES])
    policy['configuration'] = {'variant': 'eps_source_adequacy_capture',
                               'analysis_as_of': approval['analysis_as_of'],
                               'manifest_sha256': approval['manifest_sha256']}
    policy['configuration_version'] = digest(policy['configuration'])
    policy['quotas']['overall'] = {'model': 0, 'sec': 2}
    policy['quotas']['per_case'] = {}
    for case, route, *_ in SOURCES:
        limits = dict.fromkeys([*policy['prices'], 'model', 'sec'], 0)
        limits.update(sec=1)
        limits[route] = 1
        policy['quotas']['per_case'][case] = limits
    return policy


def write_json(path, data):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, sort_keys=True, indent=2, allow_nan=False)


def run_capture(manifest, approval):
    from validation.pilot_rehearsal import ROOT, prepare_policy
    from validation.pilot_approved import runtime_values, verify_network_configuration
    base = prepare_policy()
    execution = manifest['execution_configuration']
    policy = policy_for(base['code_binding'], base['dependencies'], approval, execution)
    output = Path(approval['output_dir'])
    if manifest != manifest_for(base['code_binding'], execution, output, approval['analysis_as_of']):
        raise BudgetError('capture manifest changed')
    if output.exists() or output.is_symlink():
        raise BudgetError('fresh output required; never reset or resume')
    verify_network_configuration(execution)
    runtime = runtime_values()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    home = output / 'isolated-home'
    home.mkdir(mode=0o700)
    write_json(output / 'request.json', {'policy': policy})
    environment = {'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1',
        'HOME': str(home), 'OPENAI_API_KEY': runtime['bearer_placeholder'],
        'SEC_USER_AGENT': runtime['sec_contact'], 'CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED': 'false'}
    environment.update({k: execution['proxy'] for k in execution['proxy_selectors']})
    environment.update({k: execution['ca_identity']['path'] for k in execution['ca_selectors']})
    code = ('import sys; sys.path.insert(0, ' + repr(str(ROOT)) + '); '
            'from validation._eps_source_capture_worker import main; raise SystemExit(main())')
    try:
        child = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=output,
            env=environment, capture_output=True, timeout=WHOLE_SECONDS)
        failed = child.returncode != 0
    except subprocess.TimeoutExpired:
        failed = True
    path = output / 'artifact.json'
    if failed or not path.is_file():
        verdict = {'status': 'worker_incomplete', 'launch_ready': False,
                   'dispatch_count_unknown': True, 'resume_allowed': False}
        # Never replace published terminal evidence or reopen a ledger for reporting.
        write_json(output / 'launcher-failure.json', verdict)
        return verdict
    return json.loads(path.read_text())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--execution-config', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--analysis-as-of')
    args = parser.parse_args(argv)
    try:
        if args.prepare:
            if args.approval or not args.execution_config or not args.output_dir or not args.analysis_as_of:
                raise BudgetError('preparation requires configuration and output binding, never approval')
            from validation.pilot_rehearsal import prepare_policy
            from validation.pilot_approved import validate_execution
            execution = json.loads(args.execution_config.read_text())
            validate_execution(execution)
            binding = prepare_policy()['code_binding']
            write_json(args.manifest, manifest_for(binding, execution, args.output_dir, args.analysis_as_of))
            return 0
        if not args.approval or args.execution_config or args.output_dir or args.analysis_as_of:
            raise BudgetError('execution requires an exact manifest and separate approval')
        result = run_capture(json.loads(args.manifest.read_text()), json.loads(args.approval.read_text()))
    except Exception:
        parser.exit(2, 'Diagnostic capture refused; reviewed manifest and separate approval required.\n')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
