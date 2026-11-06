"""Approval-gated live launcher for the ordinary twelve-case pilot. Off by default.

Commands:
- ``evidence-template``: write a cost or retention evidence document whose
  ``derived`` section is computed from this code and whose operator
  attestations are left empty for the responsible humans to complete.
- ``prepare``: bind completed evidence (by SHA-256), the reviewed proxy
  configuration, the cohort and the running code into the execution package,
  and print the digest a separate approval must name. Creates no output.
- ``run``: check the package, the separate approval, both evidence documents
  and this host's configuration. Nothing is created or sent unless
  ``--execute`` is also given; then the worker runs once, into the approved
  output directory, which must not exist yet (so an approval cannot be reused).

This module cannot verify who approved, what an invoice says, or what SEC
serves. Those remain human reviews; see the evidence attestations.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys

from validation.capture_budget import BudgetError, digest
from validation.ordinary_isolated_rehearsal import ROOT, git_revision, require_runtime, run_worker
from validation.ordinary_native_boundary import PAID_PROVIDER_ENVIRONMENT
from validation.ordinary_native_ledger import create_fresh_output
from validation.ordinary_native_policy import (ZERO_MODEL_PLACEHOLDER, execution_package, policy_for,
                                                test_only_references)
from validation.ordinary_pilot_contract import CASES, COHORT_FILE, quota_contract
from validation.ordinary_network import validate_ordinary_execution, verify_ordinary_network
from validation.pilot_approved import runtime_values
from validation.pilot_live import READ_CHUNK_BYTES
from validation.pilot_policy import AUDITED_DEPENDENCIES

ATTESTATIONS = {
    'cost': ('sec_access_terms_reference', 'proxy_and_egress_cost_reference',
             'compute_host_cost_reference', 'provider_billing_check_reference'),
    'retention': ('storage_location', 'access_control', 'retention_period',
                  'deletion_procedure', 'sec_content_terms_reference'),
}
# What one run writes into its output directory, and nothing else.
OUTPUT_INVENTORY = {
    'request.json': 'launcher request: the bound policy (approval, references, case records, '
                    'proxy/CA configuration); no runtime values',
    'ledger.sqlite': 'durable ledger: claims, wire entries, retained SEC response bodies with '
                     'receipts, answers, failures, halts',
    'ledger.sqlite-journal': 'transient SQLite rollback journal; absent after commit or parent rollback',
    'worker.json': 'worker report: counts, routing, pacing, diagnostics hash',
    'packet.json': 'parent record of all twelve outcomes: the ledger export, or twelve not_run '
                   'outcomes when the worker stopped before creating its ledger',
    'isolated-home': 'empty HOME directory for the worker',
    '.clearSignal_timeline': 'empty directory created by the application timeline store at import',
    '.clearSignal_watchlist': 'empty directory created by the application watchlist store at import',
}
LEDGER_TABLES = ('attempts', 'cases', 'first_sec_refusal', 'first_transport_failure', 'native_dispatches',
                 'ordinary_answers', 'ordinary_case_times', 'ordinary_exchange_failures',
                 'ordinary_responses', 'ordinary_run', 'ordinary_wire_entries', 'policy',
                 'sec_claims', 'stage_reservations')
# Offline tests a reviewer can run for each derived property.
ENFORCED_BY = (
    'tests/test_ordinary_live_launcher.py::test_loopback_run_uses_the_live_code_path_within_every_limit',
    'tests/test_ordinary_live_launcher.py::test_an_unpinned_certificate_halts_before_any_request_is_served',
    'tests/test_ordinary_live_launcher.py::test_run_refuses_every_unapproved_or_drifted_input',
    'tests/test_ordinary_live_launcher.py::test_the_output_directory_holds_only_the_declared_inventory',
    'tests/test_ordinary_live_launcher.py::test_direct_tls_reaches_only_the_claimed_sec_host_within_every_limit',
    'tests/test_ordinary_live_launcher.py::test_direct_tls_refuses_an_unpinned_certificate_before_any_request',
    'tests/test_ordinary_live_launcher.py::test_direct_tls_refuses_rather_than_overrides_an_inherited_proxy',
    'tests/test_ordinary_live_launcher.py::test_direct_resolution_admits_only_the_claimed_host_and_public_answers',
    'tests/test_ordinary_isolated_worker.py::test_twelve_cases_run_through_the_integrated_native_path',
    'tests/test_ordinary_isolated_worker.py::test_an_abandoned_evidence_request_degrades_one_answer_without_halting',
    'tests/test_ordinary_isolated_worker.py::test_the_abandoned_response_never_reaches_the_answer_and_closes_before_the_next_case',
    'tests/test_ordinary_native_boundary.py',
    'tests/test_ordinary_native_ledger.py',
)
_ATTESTATION = re.compile(r'[ -~]{8,500}')


def derived_evidence(kind):
    """The code-derived half of an evidence document; re-derived at run time."""
    limits = quota_contract()
    if kind == 'cost':
        return {'sec_gets_maximum': limits['sec_gets'],
                'sec_gets_per_case': {case: v['sec'] for case, v in limits['per_case'].items()},
                'sec_dispatches_per_second_maximum': 10, 'concurrent_sec_maximum': limits['concurrent_sec'],
                'wall_seconds_maximum': limits['wall_seconds'],
                'response_bytes_maximum': limits['body_max_bytes'],
                'transfer': {
                    # An oversized body is read until the chunk that crosses the
                    # cap arrives, then refused: one socket read past the cap.
                    'body_bytes_read_per_response_maximum': limits['body_max_bytes'] + READ_CHUNK_BYTES,
                    'body_bytes_read_maximum': limits['sec_gets'] * (limits['body_max_bytes'] + READ_CHUNK_BYTES),
                    'not_bounded_by_this_code': [
                        'per request: one proxy CONNECT exchange and a TLS handshake with certificate chain',
                        'HTTP request and response headers',
                        'TLS record framing and TCP/IP packet overhead',
                        'response bytes already in flight or buffered (TCP receive window, TLS records) '
                        'when an oversized or failed response is closed',
                    ],
                    'estimate_guidance': 'egress and proxy cost estimates must add protocol overhead and '
                                         'in-flight margin to body_bytes_read_maximum',
                },
                'retained_bytes_maximum': limits['aggregate_raw_body_max_bytes'],
                'model_attempts': 0, 'paid_provider_attempts': 0,
                'model_credential': f'OPENAI_API_KEY must equal the non-secret {ZERO_MODEL_PLACEHOLDER}',
                'paid_provider_environment_must_be_absent': list(PAID_PROVIDER_ENVIRONMENT),
                'network_destinations': ['https://www.sec.gov', 'https://data.sec.gov'],
                'network_path': 'the reviewed execution configuration: explicit proxy http://proxy:8080, or '
                                'direct TLS to the SEC hosts with no application proxy (any VPN or other '
                                'network layer below the process is outside this code); either way TLS is '
                                'verified against a pinned CA bundle with hostname checking',
                'transport_retries': 0, 'follow_redirects': False, 'enforced_by': list(ENFORCED_BY)}
    if kind == 'retention':
        return {'output_directory_mode': '0700', 'output_inventory': OUTPUT_INVENTORY,
                'ledger_tables': list(LEDGER_TABLES),
                'source_content': 'public SEC EDGAR responses from www.sec.gov and data.sec.gov only',
                'runtime_values_never_stored': ['SEC_USER_AGENT value', 'OPENAI_API_KEY value'],
                'runtime_value_screening': 'retention and export refuse any record containing a runtime value',
                'enforced_by': list(ENFORCED_BY)}
    raise BudgetError('unknown evidence kind')


def evidence_template(kind, all_in_usd=None):
    document = {'format': f'ordinary-{kind}-evidence-v1', 'derived': derived_evidence(kind),
                'operator_attestations': dict.fromkeys(ATTESTATIONS[kind])}
    if kind == 'cost':
        document['all_in_usd'] = all_in_usd
    return document


def validate_evidence(kind, document, *, all_in_usd):
    """A completed document: exact derived facts, every attestation given."""
    keys = {'format', 'derived', 'operator_attestations'} | ({'all_in_usd'} if kind == 'cost' else set())
    attestations = document.get('operator_attestations') if type(document) is dict else None
    if (type(document) is not dict or set(document) != keys
            or document['format'] != f'ordinary-{kind}-evidence-v1'
            or document['derived'] != derived_evidence(kind)
            or kind == 'cost' and document['all_in_usd'] != all_in_usd
            or type(attestations) is not dict or set(attestations) != set(ATTESTATIONS[kind])
            or any(type(v) is not str or not _ATTESTATION.fullmatch(v)
                   or re.search(r'test-only|todo|tbd|pending', v, re.I) for v in attestations.values())):
        raise BudgetError(f'completed {kind} evidence required')


def evidence_reference(kind, path):
    return f'{kind}-evidence-sha256:' + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def package_values(*, execution, all_in_usd, cost_path, retention_path):
    from validation.pilot_rehearsal import source_binding
    return dict(cases=json.loads((ROOT / COHORT_FILE).read_text()),
                code_binding={'revision': git_revision(), 'source_sha256': source_binding()},
                dependencies={name: importlib.metadata.version(name) for name in AUDITED_DEPENDENCIES},
                execution=execution, all_in_usd=all_in_usd,
                retention_reference=evidence_reference('retention', retention_path),
                pricing_review_reference=evidence_reference('cost', cost_path))


def _load(path):
    return json.loads(Path(path).read_text())


def require_run3_cohort():
    """Approved packages and runs use the pre-registered run-3 cohort only."""
    from validation.ordinary_pilot_contract import COHORT
    if COHORT != 'run3' or 'ORDINARY_PILOT_COHORT' in os.environ:
        raise BudgetError('cohort selection is for rehearsals only')


def prepare(*, execution_path, cost_path, retention_path, output_dir):
    """The package for the running code; refuses incomplete evidence."""
    require_runtime()
    require_run3_cohort()
    execution = _load(execution_path)
    validate_ordinary_execution(execution)
    cost = _load(cost_path)
    all_in_usd = cost.get('all_in_usd') if type(cost) is dict else None
    validate_evidence('cost', cost, all_in_usd=all_in_usd)
    validate_evidence('retention', _load(retention_path), all_in_usd=all_in_usd)
    output = Path(output_dir)
    if not output.is_absolute() or output.exists():
        raise BudgetError('absolute, not yet existing output directory required')
    if any('test-only' in execution[key].lower() for key in ('documentation_reference', 'verification_reference')):
        raise BudgetError('test-only configuration cannot be packaged for execution')
    values = package_values(execution=execution, all_in_usd=all_in_usd, cost_path=cost_path,
                            retention_path=retention_path)
    return execution_package(output_dir=str(output), **values)


def check(*, package_path, approval_path, cost_path, retention_path):
    """Every precondition for one approved run; returns (policy, runtime). Creates nothing."""
    require_runtime()
    require_run3_cohort()
    package, approval = _load(package_path), _load(approval_path)
    try:
        execution = package['execution_configuration']
        proposal = package['proposal']
        all_in_usd, output_dir = proposal['all_in_usd'], proposal['output_dir']
    except (TypeError, KeyError):
        raise BudgetError('execution package required') from None
    validate_ordinary_execution(execution)
    validate_evidence('cost', _load(cost_path), all_in_usd=all_in_usd)
    validate_evidence('retention', _load(retention_path), all_in_usd=all_in_usd)
    values = package_values(execution=execution, all_in_usd=all_in_usd, cost_path=cost_path,
                            retention_path=retention_path)
    # Recomputed from the running code, cohort and evidence bytes: any drift differs.
    if package != execution_package(output_dir=output_dir, **values):
        raise BudgetError('package differs from the running code, cohort or evidence')
    if type(approval) is not dict or approval.get('output_dir') != output_dir:
        raise BudgetError('approval must name the packaged output directory')
    policy = policy_for(approval=approval, **values)
    if test_only_references(policy):
        raise BudgetError('test-only records cannot authorize execution')
    if Path(output_dir).exists():
        raise BudgetError('approved output directory already exists; approvals are single-use')
    if any(os.environ.get(name) for name in PAID_PROVIDER_ENVIRONMENT):
        raise BudgetError('paid provider credentials must be absent')
    if os.environ.get('OPENAI_API_KEY') != ZERO_MODEL_PLACEHOLDER:
        raise BudgetError('the zero-model placeholder is required in place of any model credential')
    runtime = runtime_values()  # SEC contact present and well formed
    verify_ordinary_network(execution)  # proxy selectors, or none for direct TLS; pinned CA bytes
    return policy, {'OPENAI_API_KEY': runtime['bearer_placeholder'], 'SEC_USER_AGENT': runtime['sec_contact']}


def outcome_record(result):
    """All twelve outcomes: the ledger export, or the parent's own record when
    the worker stopped before creating a ledger."""
    if result['packet'] is not None:
        return result['packet']
    return {'format': 'ordinary-native-outcomes-v1', 'status': result['status'], 'ledger': False,
            'denominator': len(CASES), 'cases': result['cases'],
            'worker_returncode': result['supervisor']['returncode'],
            'stop_reason': result['supervisor']['stop_reason'],
            'execution_authorized': False, 'invoice_ceiling_verified': False}


def write_durably(path, record):
    with path.open('x') as stream:
        json.dump(record, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def execute(**paths):
    policy, runtime = check(**paths)
    output = create_fresh_output(policy['approval']['output_dir'])  # fails if it exists
    result = run_worker(output, policy, mode='approved', scenario='approved', environment=runtime,
                        forbidden=tuple(runtime.values()), synthetic=False)
    record = outcome_record(result)
    write_durably(output / 'packet.json', record)
    result.update(output_dir=str(output), outcomes=record['cases'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    template = commands.add_parser('evidence-template')
    template.add_argument('--kind', choices=sorted(ATTESTATIONS), required=True)
    template.add_argument('--all-in-usd')
    template.add_argument('--out', type=Path, required=True)
    prep = commands.add_parser('prepare')
    for name in ('execution-config', 'cost-evidence', 'retention-evidence', 'package'):
        prep.add_argument('--' + name, type=Path, required=True)
    prep.add_argument('--output-dir', type=Path, required=True)
    run = commands.add_parser('run')
    for name in ('package', 'approval', 'cost-evidence', 'retention-evidence'):
        run.add_argument('--' + name, type=Path, required=True)
    run.add_argument('--execute', action='store_true',
                     help='make the approved live SEC requests; without it, only check')
    args = parser.parse_args(argv)
    try:
        if args.command == 'evidence-template':
            if (args.kind == 'cost') != (args.all_in_usd is not None):
                raise BudgetError('--all-in-usd is required for, and only for, cost evidence')
            with args.out.open('x') as stream:
                json.dump(evidence_template(args.kind, args.all_in_usd), stream, indent=2, sort_keys=True)
            return 0
        if args.command == 'prepare':
            package = prepare(execution_path=args.execution_config, cost_path=args.cost_evidence,
                              retention_path=args.retention_evidence, output_dir=args.output_dir)
            with args.package.open('x') as stream:
                json.dump(package, stream, indent=2, sort_keys=True)
            print(json.dumps({'package_sha256': digest(package), 'approval_required': True}))
            return 0
        paths = dict(package_path=args.package, approval_path=args.approval,
                     cost_path=args.cost_evidence, retention_path=args.retention_evidence)
        if not args.execute:
            policy, _ = check(**paths)
            print(json.dumps({'checks_passed': True, 'executed': False,
                              'output_dir': policy['approval']['output_dir']}))
            return 0
        result = execute(**paths)
    except Exception as exc:
        parser.exit(2, f'Ordinary pilot refused: {exc if isinstance(exc, BudgetError) else type(exc).__name__}\n')
    print(json.dumps({'status': result['status'], 'cases': result['outcomes'],
                      'output_dir': result['output_dir']}, sort_keys=True))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
