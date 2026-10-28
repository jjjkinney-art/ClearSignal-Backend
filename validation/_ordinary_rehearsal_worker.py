"""Isolated twelve-case application rehearsal. No live mode or credentials.

Application imports follow the HTTP/provider and process fences. Synthetic
sources provide no evidence of real-company research quality.
"""
import json
import hashlib
import os
from pathlib import Path
import platform
import socket
import sys
import time
from collections import namedtuple
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from io import StringIO


def main():
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode
            or sys.version_info[:3] != (3, 11, 9) or sys.implementation.name != 'cpython'
            or len(sys.argv) != 4 or sys.argv[1] not in {
                'happy', 'wire_connect_failure', 'wire_read_failure', 'core_deadline', 'threshold_deadline'}):
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
    if set(p.name for p in output.iterdir()) != {'isolated-home'}:
        return 2
    home = output / 'isolated-home'
    if home.is_symlink() or not home.is_dir() or any(home.iterdir()):
        return 2
    os.environ.clear()
    os.environ.update(PATH='/usr/bin:/bin', HOME=str(home), PYTHONDONTWRITEBYTECODE='1',
                      OPENAI_API_KEY='TEST_ONLY', SEC_USER_AGENT='Fixture contact@example.invalid',
                      CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED='false',
                      DECISION_MONITORING_INPUTS_ENABLED='true',
                      DECISION_MONITORING_FILING_FALLBACK_ENABLED='false')
    blocked = []
    holder = []
    def audit(event, args):
        if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system', 'os.posix_spawn'}:
            blocked.append(event)
            if holder:
                holder[0].halt('offline_external_operation')
            raise RuntimeError('external operation prohibited in ordinary rehearsal')
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
    sys.addaudithook(audit)
    def synthetic_dns(host, port, *args, **kwargs):
        if host not in {'www.sec.gov', 'data.sec.gov'} or port != 443:
            raise RuntimeError('unknown rehearsal DNS target')
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443))]
    socket.getaddrinfo = synthetic_dns
    from validation.ordinary_pilot_accounting import OfflineAccounting, AccountingError
    from validation.ordinary_pilot_contract import CASES
    from validation.ordinary_coordinator import run_offline_cases
    from validation.ordinary_artifacts import export_fixture_packet
    from validation.ordinary_wire_rehearsal import rehearse_sec, _fixture_url
    from validation.pilot_boundary import PilotBoundary
    from validation.capture_budget import BudgetError
    import validation.pilot_approved as approved
    import ssl
    # Only this no-socket child bypasses live proxy/CA configuration.
    approved.verify_network_configuration = lambda config, tls=False: ssl.create_default_context() if tls else None
    raw_cases = json.loads((Path(__file__).resolve().parents[1] / 'tests/ordinary_pilot_cases.json').read_text())
    if (tuple(c['case_id'] for c in raw_cases) != CASES
            or hashlib.sha256(json.dumps(raw_cases, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            != 'fa9159abaf5b396bee5a5d51c55031044a148f94997709ea601e49f0508747e3'):
        return 2
    cases = [dict(c, identity={'ticker': c['issuer_id'], 'cik': c['expected_cik'],
                              'company_name': c['issuer_id']}) for c in raw_cases]
    book = OfflineAccounting(output / 'ledger.sqlite')
    class LedgerBridge:
        policy = {'configuration': {'variant': 'source_monitoring'}}
        def halt(self, reason):
            book.seal_local()
            with book._connect() as db:
                db.execute("UPDATE state SET halt=CASE WHEN halt='' THEN ? ELSE halt END", (reason,))
    class Boundary(PilotBoundary):
        def active(self):
            if book._locally_sealed or book.summary()['halt']:
                raise BudgetError('ordinary rehearsal halted')
            if self.settings is not None and (self.settings.fmp_api_key or self.settings.fred_api_key
                    or self.settings.sec_user_agent != 'Fixture contact@example.invalid'
                    or self.settings.decision_monitoring_inputs_enabled is not True
                    or self.settings.decision_monitoring_filing_fallback_enabled is not False):
                self.refuse('configuration_drift')
        def model_request(self, request):
            self.refuse('ordinary_model_attempt')
        def sec_document_urls(self):
            try:
                return {_fixture_url(book, self.case['case_id'], self.stage.get(), 'sec/document')}
            except AccountingError:
                return set()
        def sec_exchange(self, method, url, body):
            route = self.sec_route(method, url, body)
            fault = (scenario if self.case['case_id'] == CASES[2] and route == 'sec/facts'
                     and scenario in {'wire_connect_failure', 'wire_read_failure'}
                     else 'reported-facts' if route == 'sec/facts' else 'happy')
            if url != _fixture_url(book, self.case['case_id'], self.stage.get(), route):
                self.refuse('request_url_mismatch')
            if route == 'sec/facts' and (
                    (scenario == 'core_deadline' and self.case['case_id'] == CASES[2])
                    or (scenario == 'threshold_deadline' and self.case['case_id'] == CASES[3])):
                # Stall a real pipeline executor task in C-level sleep. Even if
                # the router returns and cleanup times out, the parent must reap
                # this thread's process and reject any artifact it wrote.
                time.sleep(3600)
            result = rehearse_sec(book, self.case['case_id'], stage=self.stage.get(), route=route,
                                  scenario=fault, bound=True, scoped=True)
            with book._connect() as db:
                raw, = db.execute('SELECT body FROM bodies WHERE attempt_id=?', (result['receipt']['attempt_id'],)).fetchone()
            return ('text/html' if route == 'sec/document' else 'application/json'), raw
    bridge = LedgerBridge()
    holder.append(bridge)
    boundary = Boundary(bridge, 'ordinary_owned_rehearsal', cases=cases)
    diagnostics = StringIO()
    with redirect_stdout(diagnostics), redirect_stderr(diagnostics):
        boundary.install()
        try:
            from app.config import settings
            from app.schemas import CompanyContext
            from app.services import router_service
            from app.services.providers import sec_provider
            boundary.settings = settings
            def invoke(case_id):
                case = next(c for c in cases if c['case_id'] == case_id)
                boundary.case, boundary.case_run = case, case_id
                boundary.pool_index = 0
                boundary.release.clear()
                sec_provider._ticker_cik_cache = None
                sec_provider._reset_shared_company_tickers()
                started = time.monotonic()
                response = router_service._run_investment_pipeline(
                    CompanyContext(company_name=case['issuer_id'], ticker=case['issuer_id']),
                    case['question'], 'ordinary-rehearsal-' + case_id, side_effects_enabled=False)
                if response.company != case['issuer_id'] or response.routing.get('response_mode') != 'source_evidence':
                    boundary.refuse('ordinary_response_mode')
                # Pace invented exchanges below the unchanged 10/sec fixture limit.
                time.sleep(max(0, 1.05 - (time.monotonic() - started)))
                return response.model_dump(mode='json')
            result = run_offline_cases(book, invoke, boundary.drain, forbidden_values=('TEST_ONLY',),
                                       case_scope=case_scope)
            packet = export_fixture_packet(book, forbidden_values=('TEST_ONLY',), require_bound=True)
        finally:
            boundary.close()
    artifact = {'execution_authorized': False, 'external_requests': 0,
                'network_attempts': len(blocked), 'result': result, 'packet': packet,
                'tracked_workers': len(boundary.futures),
                'unfinished_workers': sum(not f.done() for f in boundary.futures)}
    (output / 'result.json').write_text(json.dumps(artifact, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
