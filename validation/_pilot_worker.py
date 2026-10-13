"""Internal subprocess entrypoint. Never run in an application process."""
from collections import Counter, namedtuple
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import importlib.metadata
import json
import logging
import os
import platform
from pathlib import Path
import socket
import sys
import traceback


def safe_result(result, canaries):
    data = result.model_dump(mode='json')
    from validation.pilot_policy import reject_runtime_values
    reject_runtime_values(data, canaries)
    encoded = json.dumps(data, allow_nan=False)
    if len(encoded.encode()) > 4 * 1024 * 1024 or any(value in encoded for value in canaries):
        from validation.capture_budget import BudgetError
        raise BudgetError('result artifact refused')
    return data


def main():
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode
            or sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 11, 9)):
        return 2
    # Defense in depth for accidental direct invocation of this internal entry.
    # Only this isolated child environment changes; caller values are not read.
    from validation.pilot_fixtures import SYNTHETIC_KEY, SYNTHETIC_CONTACT
    output = Path.cwd().resolve()
    isolated_home = output / 'isolated-home'
    if isolated_home.is_symlink() or not isolated_home.is_dir() or any(isolated_home.iterdir()):
        return 2
    request = json.loads((output / 'request.json').read_text())
    policy, scenario = request['policy'], request['scenario']
    approved = policy.get('purpose') == 'approved_six_case_pilot'
    execution = policy.get('execution_configuration') if approved else None
    if approved:
        # Bind the actual directory before imports, ledger creation, or network setup.
        approval = policy.get('approval')
        approved_output = approval.get('output_dir') if type(approval) is dict else None
        if (type(approved_output) is not str or str(output) != approved_output
                or Path(approved_output).resolve() != Path(approved_output)
                or not Path(approved_output).samefile(Path.cwd())):
            return 2
        # Runtime-only values and fixed reviewed selectors. Never serialize/hash.
        preserved = {name: os.environ[name] for name in (
            'OPENAI_API_KEY', 'SEC_USER_AGENT', 'HTTP_PROXY', 'HTTPS_PROXY',
            'http_proxy', 'https_proxy', 'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE') if name in os.environ}
    os.environ.clear()
    os.environ.update({'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1',
                       'HOME': str(isolated_home),
                       'OPENAI_API_KEY': SYNTHETIC_KEY, 'SEC_USER_AGENT': SYNTHETIC_CONTACT,
                       'CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED': 'false'})
    if approved:
        os.environ.pop('OPENAI_API_KEY', None)
        os.environ.pop('SEC_USER_AGENT', None)
        os.environ.update(preserved)
    blocked = []
    netrc_reads = []
    holder = []

    def deny(event='unreviewed_dns'):
        blocked.append({'event': event, 'locations': [
            {'file': Path(frame.filename).name, 'line': frame.lineno}
            for frame in traceback.extract_stack(limit=10)]})
        if holder:
            holder[0].ledger.halt('offline_network_attempt')
        raise RuntimeError('offline worker prohibits external operations')

    def audit(event, args):
        if event.startswith('socket.'):
            if approved and holder:
                try:
                    holder[0].gate.audit(event, args)
                except Exception:
                    deny(event)
            else:
                deny(event)
        if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn'}:
            deny(event)
        if event == 'import' and args[0] == 'app.main':
            raise RuntimeError('server entrypoint is prohibited')
        if event == 'open' and isinstance(args[0], (str, bytes)):
            raw_path = Path(args[0])
            if raw_path.name in {'.netrc', '_netrc'}:
                netrc_reads.append('netrc_open_blocked')
                if holder:
                    holder[0].ledger.halt('configuration_drift')
                raise RuntimeError('netrc access is prohibited')
            path = raw_path.resolve()
            if path.name == '.env' or path.name.startswith('.env.'):
                if holder:
                    holder[0].ledger.halt('configuration_drift')
                raise RuntimeError('dotenv loading is prohibited')
            mode = args[1]
            if isinstance(mode, str) and any(char in mode for char in 'wax+') and not path.is_relative_to(output):
                raise RuntimeError('worker writes must stay in its new output directory')

    socket.has_ipv6 = False  # Avoid urllib3's import-time IPv6 socket probe.
    platform.processor = lambda: 'offline-fixture'  # SDK platform metadata, no uname child.
    platform.uname = lambda: namedtuple('OfflineUname', 'system node release version machine processor')(
        'Linux', 'offline', '0', 'offline', 'x86_64', 'offline')
    sys.addaudithook(audit)

    original_dns = socket.getaddrinfo

    def synthetic_dns(host, port, *args, **kwargs):
        if approved and holder and holder[0].gate.current.get() is not None:
            return holder[0].gate.dns(host, port, *args, **kwargs)
        if host not in {'www.sec.gov', 'data.sec.gov', 'efts.sec.gov'} or port != 443:
            deny()
        # Invented public-address fixture for the production SSRF admission
        # check. No DNS resolver or socket is invoked.
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('1.1.1.1', 443))]

    socket.getaddrinfo = synthetic_dns
    from validation.capture_budget import AttemptLedger, BudgetError, digest
    from validation.pilot_policy import AUDITED_DEPENDENCIES, policy_for
    from validation.pilot_fixtures import SECRET_CANARIES, SCENARIOS, LIVE_SCENARIOS
    from validation.pilot_preflight import preflight
    from validation.pilot_rehearsal import source_binding
    from validation.pilot_boundary import PilotBoundary

    scenarios = LIVE_SCENARIOS if policy['purpose'] == 'disabled_live_adapter_validation' else SCENARIOS
    if approved:
        scenarios = {'approved'}
    if scenario not in scenarios:
        return 2
    dependencies = {name: importlib.metadata.version(name) for name in AUDITED_DEPENDENCIES}
    actual_policy = policy_for({'revision': policy['code_binding']['revision'],
                                'source_sha256': source_binding()}, dependencies,
                               mode=('approved' if approved else 'live_adapter_validation' if policy['purpose'] == 'disabled_live_adapter_validation' else 'offline'),
                               approval=policy.get('approval'), execution=execution)
    if digest(policy) != digest(actual_policy):
        return 2
    ledger = AttemptLedger(output / 'ledger.sqlite', actual_policy, create=True)
    if approved:
        from validation.pilot_approved import ApprovedBoundary
        boundary = ApprovedBoundary(ledger)
        runtime = boundary.runtime
        boundary.gate.resolve = original_dns
    elif policy['purpose'] == 'disabled_live_adapter_validation':
        from validation.pilot_live import LiveAdapterBoundary
        boundary = LiveAdapterBoundary(ledger, scenario)
    else:
        boundary = PilotBoundary(ledger, scenario)
    holder.append(boundary)
    diagnostics = StringIO()
    log_handler = logging.StreamHandler(diagnostics)
    logging.getLogger().handlers = [log_handler]
    cases = []
    failure = None
    trace = []
    boundary.install()
    cleanup_failed = False
    with redirect_stdout(diagnostics), redirect_stderr(diagnostics):
        try:
            from app.config import settings
            from app.schemas import CompanyContext
            from app.services import router_service
            from app.services.providers import sec_provider
            from app.model_client import model_client, synthesis_client
            boundary.settings = settings
            boundary.model_clients = [model_client, synthesis_client]
            if scenario == 'application_retry_drift':
                model_client.max_retries = 2
            boundary.active()
            for case in boundary.cases:
                boundary.begin(case)
                # Rehearse the conservative cold-directory allowance each case.
                sec_provider._ticker_cik_cache = None
                if scenario == 'dotenv_drift':
                    (output / '.env').write_text('INVENTED_FIXTURE=true')
                if scenario == 'socket_attempt':
                    socket.socket()
                if scenario == 'unknown_dns':
                    socket.getaddrinfo('unreviewed.invalid', 443)
                result = router_service._run_investment_pipeline(
                    CompanyContext(**case['company_context']), case['question'],
                    'offline-pilot-' + case['case_id'], side_effects_enabled=False)
                if boundary.drain():
                    raise BudgetError('unfinished offline workers')
                boundary.active()
                if result.company != case['identity']['ticker']:
                    boundary.refuse('identity_mismatch')
                ledger.finish_case(boundary.case_run)
                completed = {'case_id': case['case_id'], 'identity': case['identity'],
                             'pipeline_returned': True}
                if approved or policy['purpose'] == 'disabled_live_adapter_validation':
                    completed['answer_and_evidence'] = safe_result(result, (*SECRET_CANARIES, *(tuple(runtime.values()) if approved else ())))
                cases.append(completed)
        except BaseException as exc:
            ledger.halt('rehearsal_failure')
            failure = type(exc).__name__
            tb = exc.__traceback__
            while tb:
                # Code locations only, never exception messages or local values.
                trace.append({'file': Path(tb.tb_frame.f_code.co_filename).name,
                              'line': tb.tb_lineno})
                tb = tb.tb_next
        finally:
            try:
                boundary.close()
            except BaseException:
                cleanup_failed = True
                ledger.halt('rehearsal_failure')
    diagnostic_clean = not any(value in diagnostics.getvalue() for value in (*SECRET_CANARIES, *(tuple(runtime.values()) if approved else ())))
    diagnostics.close()
    if not diagnostic_clean:
        ledger.halt('fixture_failure')
    if source_binding() != policy['code_binding']['source_sha256']:
        ledger.halt('configuration_drift')
    summary = ledger.summary()
    counts = Counter(event['route'] for event in boundary.events)
    artifact = {
        'artifact_type': ('disabled_live_adapter_validation' if policy['purpose'] == 'disabled_live_adapter_validation'
                          else 'integrated_offline_pilot_rehearsal'),
        'status': 'complete' if len(cases) == 6 and not summary['halted'] else 'halted',
        'scenario': scenario, 'failure_class': failure, 'failure_locations': trace,
        'cleanup_failure': 'boundary_close' if cleanup_failed else None,
        'code_binding': policy['code_binding'], 'dependencies': dependencies,
        'setup_sha256': policy['setup_sha256'], 'policy_sha256': digest(policy),
        'configuration': policy['configuration'], 'quotas': policy['quotas'],
        'ledger': summary, 'completed_cases': cases, 'route_counts': dict(counts),
        'claims': boundary.events, 'sec_route_calls': boundary.sec_route_calls,
        'transport_entries': boundary.transport_entries,
        'max_concurrent_claims': boundary.max_inflight,
        'blocked_after_halt': boundary.blocked_after_halt,
        'submission_tracking': {
            'registered': len(boundary.futures),
            'completed': sum(future.done() for future in boundary.futures),
            'constructor_failures': boundary.constructor_failures,
            'ambiguous_submissions': boundary.ambiguous_submissions,
            'queued_submissions_fenced': boundary.queued_submissions_fenced,
        },
        'sec_configured_contact_applied': boundary.sec_contact_applied,
        'diagnostics_canary_clean': diagnostic_clean,
        'isolated_home': True, 'netrc_open_attempts': len(netrc_reads),
        'sec_authorization_header_absent': boundary.sec_authorization_header_absent,
        'coverage_gaps': preflight()['coverage_gaps'],
        'excluded_providers': ['fmp', 'newsapi', 'fred'],
        'external_dispatches': 0, 'network_attempts': len(blocked), 'blocked_operations': blocked,
        'usage_source': 'invented_fixture_protocol_units_not_provider_billing',
        'illustrative_maximum_model_allocation_usd': '0.5105664',
        'execution_allowed': False, 'spending_authorized': False,
        'tariffs_verified': False, 'all_incremental_charges_accounted': False,
        'hard_usd_cap_established': False, 'launch_ready': False,
        'quality_status': 'not_adjudicated',
    }
    if approved:
        artifact.update(artifact_type='approved_six_case_pilot',
                        external_dispatches=boundary.gate.dispatched,
                        dispatch_count_status='native_exchange_entries_including_connection_failures',
                        usage_source='provider_reported_protocol_units_not_invoice',
                        execution_allowed=True, spending_authorized=True,
                        approval_reference=policy['approval_reference'],
                        execution_configuration_sha256=digest(execution),
                        authentication_verified=False)
    with (output / 'artifact.json').open('x') as stream:
        json.dump(artifact, stream, indent=2, sort_keys=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
