"""Twelve-case worker over the native ordinary stack.

Runs the real application question router for each fixed case. Every SEC GET
crosses the integrated boundary: stage reservation, paced durable claims, the
ordinary gate and owned transport, then retention before settlement.
Subprocesses and ambient credential files are always refused by audit hook.

Modes (request.json ``mode``, set only by a launcher):
- ``rehearsal``: the invented synthetic SEC backend; every socket is refused.
- ``loopback``: the live code path (real sockets, CONNECT, TLS verification)
  with a TEST-ONLY approval; the proxy resolves only to 127.0.0.1 and the
  pinned CA is a test CA, so no external host can be reached or trusted.
- ``approved``: live SEC through the reviewed proxy. Requires a non-test
  approval bound to this exact output directory; sockets are admitted only by
  the gate's audit inside a claimed, dispatched exchange.
Synthetic sources provide no evidence of real-company research quality.
"""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import socket
import sys
from collections import namedtuple
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO

SCENARIO_FAULTS = {
    'happy': None,
    # Third case (INGR:core_thesis): first companyfacts request.
    'wire_read_failure': ('read_failure', r'/companyfacts/CIK0001046257\.json$', 1),
    'wire_redirect': ('redirect', r'/submissions/CIK0001046257\.json$', 1),
    'wire_oversize': ('oversize', r'/Archives/edgar/data/1046257/', 1),
    'wire_connect_failure': ('connect_failure', '', 13),
    # Stalled peers: INGR's first (core) and second (threshold) facts requests.
    'core_deadline': ('stall', r'/companyfacts/CIK0001046257\.json$', 1),
    'threshold_deadline': ('stall', r'/companyfacts/CIK0001046257\.json$', 2),
}
REHEARSAL_RUNTIME = {'OPENAI_API_KEY': 'TEST_ONLY_ORDINARY_PLACEHOLDER',
                     'SEC_USER_AGENT': 'Ordinary rehearsal fixture rehearsal@example.invalid'}
LIVE_MODES = ('loopback', 'approved')


def loopback_proxy(host, port, *args, **kwargs):
    """The loopback mode's only resolver: the proxy name maps to 127.0.0.1."""
    if (host, port) != ('proxy', 8080):
        raise RuntimeError('loopback mode resolves only the proxy')
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', 8080))]


# Loopback direct-TLS test server port (unprivileged, so CI needs no root).
LOOPBACK_DIRECT_PORT = 8443


def loopback_sec(host, port, *args, **kwargs):
    """The loopback mode's only direct resolver: an SEC host maps to 127.0.0.1."""
    if host not in {'www.sec.gov', 'data.sec.gov'} or port != 443:
        raise RuntimeError('loopback mode resolves only the SEC hosts')
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', LOOPBACK_DIRECT_PORT))]


def loopback_address(address):
    return address == '127.0.0.1'


def gate_admits(live, holder, event, args):
    """In a live mode, only the gate admits a socket operation: inside a
    claimed, dispatched exchange, to the address it resolved for the proxy."""
    if not live or len(holder) < 2:
        return False
    try:
        holder[1].gate.audit(event, args)
    except Exception:
        return False
    return True


def live_request_allowed(policy, mode, output):
    """A live mode needs an approval for this directory of the matching kind."""
    from validation.ordinary_native_policy import PURPOSE, test_only_references
    approval = policy.get('approval')
    if (policy.get('purpose') != PURPOSE or type(approval) is not dict
            or approval.get('output_dir') != str(output)):
        return False
    return test_only_references(policy) is (mode == 'loopback')


def verify_running_configuration(policy):
    """Compare the code and packages actually loaded with the bound policy."""
    from validation.pilot_policy import AUDITED_DEPENDENCIES
    from validation.pilot_rehearsal import source_binding
    installed = {name: importlib.metadata.version(name) for name in AUDITED_DEPENDENCIES}
    if (sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 11, 9)
            or installed != dict(AUDITED_DEPENDENCIES) or policy['dependencies'] != installed
            or source_binding() != policy['code_binding']['source_sha256']):
        raise RuntimeError('running code or dependencies differ from the bound policy')


def main():
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode
            or sys.version_info[:3] != (3, 11, 9) or sys.implementation.name != 'cpython'
            or len(sys.argv) != 4 or (sys.argv[1] not in SCENARIO_FAULTS and sys.argv[1] not in LIVE_MODES)):
        return 2
    scenario = sys.argv[1]
    try:
        ack_fd, status_fd = map(int, sys.argv[2:])
        if min(ack_fd, status_fd) < 3 or ack_fd == status_fd:
            return 2
    except ValueError:
        return 2

    @contextmanager
    def case_scope(case):
        os.write(status_fd, ('begin ' + case + '\n').encode())
        if os.read(ack_fd, 1) != b'1':
            raise RuntimeError('parent deadline acknowledgment absent')
        try:
            yield
        except BaseException:
            os.write(status_fd, ('abort ' + case + '\n').encode())
            raise
        else:
            os.write(status_fd, ('end ' + case + '\n').encode())

    output = Path.cwd().resolve()
    if {p.name for p in output.iterdir()} != {'isolated-home', 'request.json'}:
        return 2
    home = output / 'isolated-home'
    if home.is_symlink() or not home.is_dir() or any(home.iterdir()):
        return 2
    request = json.loads((output / 'request.json').read_text())
    policy = request['policy']
    mode = request.get('mode')
    live = mode in LIVE_MODES
    if (mode == 'rehearsal' and (scenario not in SCENARIO_FAULTS or request.get('scenario') != scenario)
            or live and (scenario != mode or 'scenario' in request
                         or not live_request_allowed(policy, mode, output))
            or not live and mode != 'rehearsal'):
        return 2
    runtime = REHEARSAL_RUNTIME
    if live:
        # Runtime-only values from the launcher. Never serialized or hashed;
        # the export refuses any record containing them.
        from validation.ordinary_native_policy import ZERO_MODEL_PLACEHOLDER
        runtime = {'OPENAI_API_KEY': os.environ.get('OPENAI_API_KEY'),
                   'SEC_USER_AGENT': os.environ.get('SEC_USER_AGENT')}
        if runtime['OPENAI_API_KEY'] != ZERO_MODEL_PLACEHOLDER:
            return 2
    execution = policy['execution_configuration']
    os.environ.clear()
    os.environ.update(PATH='/usr/bin:/bin', HOME=str(home), PYTHONDONTWRITEBYTECODE='1',
                      CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED='false',
                      DECISION_MONITORING_INPUTS_ENABLED='true',
                      DECISION_MONITORING_FILING_FALLBACK_ENABLED='false',
                      # As in production /ask: authenticated mode, so the router
                      # never writes the legacy global watchlist/history.
                      AUTH_ENABLED='true', **runtime)
    # Direct TLS sets no proxy selector and verifies that none is present.
    for name in execution.get('proxy_selectors') or ():
        os.environ[name] = execution['proxy']
    for name in execution['ca_selectors']:
        os.environ[name] = execution['ca_identity']['path']

    blocked, holder = [], []

    def audit(event, args):
        if event.startswith('socket.') and gate_admits(live, holder, event, args):
            return
        if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system', 'os.posix_spawn'}:
            import traceback
            # Event name and code locations only; never arguments or values.
            blocked.append({'event': event, 'locations': [
                f'{Path(frame.filename).name}:{frame.lineno}' for frame in traceback.extract_stack(limit=30)[:-1]]})
            if holder:
                holder[0].halt('offline_network_attempt')
            raise RuntimeError('external operation prohibited in ordinary worker')
        if event == 'import' and args[0] == 'app.main':
            raise RuntimeError('server import prohibited')
        if event == 'open' and isinstance(args[0], (str, bytes)):
            path = Path(os.fsdecode(args[0])).resolve()
            if path.name in {'.netrc', '_netrc', '.env'} or path.name.startswith('.env.'):
                raise RuntimeError('ambient credential file prohibited')
            mode, flags = args[1:3]
            writes = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
            if writes and not path.is_relative_to(output):
                raise RuntimeError('write outside fresh rehearsal output')

    socket.has_ipv6 = False
    platform.processor = lambda: 'offline-fixture'
    platform.uname = lambda: namedtuple('OfflineUname', 'system node release version machine processor')(
        'Linux', 'offline', '0', 'offline', 'x86_64', 'offline')
    verify_running_configuration(policy)
    sys.addaudithook(audit)
    original_dns = socket.getaddrinfo

    def scoped_dns(host, port, *args, **kwargs):
        # Same reviewed rule as the historical approved worker: inside a claimed
        # exchange only the configured proxy may resolve (via the gate); the
        # application's SSRF admission check for exact SEC hosts receives an
        # invented public address and never reaches a resolver. The request
        # itself always travels through the gate's proxy, never that address.
        boundary = holder[1] if len(holder) > 1 else None
        if boundary is not None and boundary.gate.current.get() is not None:
            return boundary.gate.dns(host, port, *args, **kwargs)
        if host in {'www.sec.gov', 'data.sec.gov'} and port == 443:
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('1.1.1.1', 443))]
        blocked.append({'event': 'dns', 'locations': []})
        if holder:
            holder[0].halt('offline_network_attempt')
        raise RuntimeError('DNS prohibited in ordinary rehearsal')
    socket.getaddrinfo = scoped_dns

    from validation.capture_budget import BudgetError
    from validation.ordinary_frontend_intents import frontend_intent
    from validation.ordinary_native_boundary import NATIVE_BACKEND, OrdinaryNativeBoundary
    from validation.ordinary_native_ledger import OrdinaryNativeLedger
    from validation.ordinary_network import verify_ordinary_network
    from validation._ordinary_synthetic_sec import OrdinarySyntheticSEC
    # The real reviewed proxy/CA check runs here; it is never replaced.
    verify_ordinary_network(execution)
    ledger = OrdinaryNativeLedger(output / 'ledger.sqlite', policy, create=True)
    holder.append(ledger)
    backend = NATIVE_BACKEND if live else OrdinarySyntheticSEC(SCENARIO_FAULTS[scenario])
    boundary = OrdinaryNativeBoundary(ledger, backend=backend)
    # The gate's resolver: the system resolver when approved (direct mode then
    # admits only globally routable answers), fixed 127.0.0.1 answers only in
    # the TEST-ONLY loopback mode.
    if mode == 'approved':
        boundary.gate.resolve = original_dns
    elif boundary.gate.direct:
        boundary.gate.resolve, boundary.gate.allow_address = loopback_sec, loopback_address
    else:
        boundary.gate.resolve = loopback_proxy
    holder.append(boundary)
    diagnostics = StringIO()
    completed, failure, routes = [], None, []
    with redirect_stdout(diagnostics), redirect_stderr(diagnostics):
        boundary.install()
        try:
            from app.config import settings
            from app.schemas import QuestionRequest
            from app.services import router_service
            from app.services.providers import sec_provider
            boundary.settings = settings
            boundary.active()
            for case in boundary.cases:
                with case_scope(case['case_id']):
                    boundary.begin(case)
                    # Each case starts with a cold ticker map, as the quota
                    # contract assumes; identity metadata keeps its own cache.
                    sec_provider._ticker_cik_cache = None
                    sec_provider._reset_shared_company_tickers()
                    # As the frontend sends it: empty company_name and the
                    # frontend classifier's intent, so the /ask core resolves
                    # the company from the question text. That resolution may
                    # use the routing stage's directory slot.
                    token = boundary.stage.set('routing')
                    try:
                        response = router_service.route_question(QuestionRequest(
                            question=case['question'], company_name='',
                            intent=frontend_intent(case['case_id'])))
                    finally:
                        boundary.stage.reset(token)
                    if boundary.drain():
                        raise BudgetError('unfinished pipeline workers')
                    boundary.active()
                    payload = response.model_dump(mode='json')
                    routes.append({'case_id': case['case_id'], 'intent': frontend_intent(case['case_id']),
                                   'company': payload.get('company'),
                                   'pipeline': (payload.get('routing') or {}).get('pipeline'),
                                   'response_mode': (payload.get('routing') or {}).get('response_mode')})
                    boundary.complete_case(payload)
                    completed.append(case['case_id'])
        except BaseException as exc:
            failure = type(exc).__name__
            try:
                ledger.halt('rehearsal_failure')
            except BaseException:
                pass
        finally:
            boundary.close()
    worker = {'format': 'ordinary-native-worker-v1', 'mode': mode, 'synthetic_sec_backend': not live,
              'execution_authorized': mode == 'approved', 'live_network': mode == 'approved',
              'external_dispatches': boundary.gate.dispatched if live else 0,
              'failure_class': failure, 'completed_cases': completed, 'routing': routes,
              'blocked_external_operations': blocked[:10],
              'refused_model_requests': boundary.refused_model_requests,
              'refused_requests': list(boundary.refused_requests),
              'transport_entries': dict(boundary.transport_entries),
              'synthetic_requests': None if live else len(backend.requests),
              'max_inflight_sec': boundary.max_inflight,
              'pacing': {'slot_waits': boundary.slot_waits, 'claim_waits': boundary.claim_pacing_waits,
                         'wire_entry_waits': boundary.gate.entry_pacing_waits},
              'tracked_workers': len(boundary.futures),
              'unfinished_workers': sum(not f.done() for f in boundary.futures),
              'diagnostics_sha256': hashlib.sha256(diagnostics.getvalue().encode()).hexdigest()}
    with (output / 'worker.json').open('x') as stream:
        json.dump(worker, stream, allow_nan=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
