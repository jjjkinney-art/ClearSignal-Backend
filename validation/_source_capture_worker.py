"""Internal isolated capture worker. Importing this module performs no I/O."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import socket
import sys
import time
from threading import Lock

from validation.capture_budget import AttemptLedger, BudgetError, digest
from validation.source_capture import (SOURCES, PURPOSE, STAGE_SECONDS, DRAIN_SECONDS,
    WHOLE_SECONDS, policy_for, write_json)


class CaptureOwner:
    monitoring = True  # ExchangeGate never admits the model host.

    def __init__(self, ledger):
        from validation.pilot_approved import ExchangeGate, ScopedBackend, runtime_values
        from validation.pilot_live import OwnedHTTPTransport
        self.ledger = ledger
        self.runtime = runtime_values()
        self.execution = ledger.policy['execution_configuration']
        self.execution_hash = digest(self.execution)
        self.until = time.monotonic() + WHOLE_SECONDS
        self.stage_until = self.until
        self.gate = ExchangeGate(self)
        self.lock = Lock()
        self.first_failure = None

        class FixedTransport(OwnedHTTPTransport):
            def response_limit(inner, method, url, reviewed):
                inner.gate.require(url)
                source = next((s for s in SOURCES if s[3] == url), None)
                if method != 'GET' or reviewed is not None or source is None:
                    raise BudgetError('capture permits only exact frozen sources')
                state = inner.gate.require(url)
                if state['route'] != source[1] or state['stage'] != source[2]:
                    raise BudgetError('capture source route or stage changed')
                return source[4]

        self.wire = FixedTransport(gate=self.gate, execution=self.execution, runtime=self.runtime)
        self.wire._wire._pool._network_backend = ScopedBackend(
            self.wire._wire._pool._network_backend, self.gate)

    def active(self):
        from validation.pilot_approved import runtime_values
        self.ledger.require_active()
        if (digest(self.ledger.policy['execution_configuration']) != self.execution_hash
                or runtime_values() != self.runtime):
            self.ledger.halt('configuration_drift')
            raise BudgetError('capture configuration drift')
        if time.monotonic() >= min(self.until, self.stage_until):
            self.ledger.halt('stage_timeout')
            raise BudgetError('capture deadline expired')

    def exchange(self, source, case_run):
        from validation.pilot_live import TransportFailure
        from validation.source_gap_analysis import analyze_achc_facts, analyze_npk_html
        if source not in SOURCES:
            raise BudgetError('unknown capture source')
        _, route, stage, url, _, media, _ = source
        self.active()
        fingerprint = digest({'method': 'GET', 'url': url, 'route': route, 'stage': stage})
        attempt = self.ledger.reserve(case_run, route, input_bound=0, output_bound=0,
                                      request_sha256=fingerprint)
        self.ledger.claim_dispatch(attempt, case_run=case_run, route=route,
            request_sha256=fingerprint, input_bound=0, output_bound=0)
        grant = self.gate.issue(attempt, fingerprint, route, case_run, stage)
        phase = 'transport'
        try:
            with self.gate.exchange(url, grant, fingerprint):
                observed_media, body = self.wire.exchange('GET', url)
            self.active()
            if observed_media != media:
                self.ledger.record_sec_refusal(attempt, route, stage, 'sec_media_type')
                raise BudgetError('capture media refused')
            phase = 'analysis'
            # Diagnostics are deliberately NOT application evidence admission.
            analysis = analyze_achc_facts(body) if route == 'sec/facts' else analyze_npk_html(body)
            from validation.pilot_policy import reject_runtime_values
            from validation.pilot_fixtures import SECRET_CANARIES
            phase = 'analysis_reflection'
            reject_runtime_values(analysis, (*SECRET_CANARIES, *self.runtime.values()))
            self.active()
            receipt = {'url': url, 'http_status': 200, 'media_type': observed_media,
                'content_encoding': 'identity', 'body_bytes': len(body),
                'body_sha256': hashlib.sha256(body).hexdigest(),
                'captured_at': datetime.now(timezone.utc).isoformat(),
                'attempt_id': attempt, 'request_sha256': fingerprint,
                'admitted_evidence': False, 'independent_origin_verification': False}
            return attempt, body, receipt, analysis
        except BaseException as exc:
            code = (exc.code if type(exc) is TransportFailure else
                    'analysis_value_error' if phase == 'analysis' and isinstance(exc, ValueError) else
                    'analysis_type_error' if phase == 'analysis' and isinstance(exc, TypeError) else
                    'analysis_other' if phase == 'analysis' else
                    'analysis_reflection' if phase == 'analysis_reflection' else 'capture_policy_failure')
            with self.lock:
                if self.first_failure is None:
                    self.first_failure = {'attempt_id': attempt, 'route': route, 'stage': stage, 'code': code}
            if type(exc) is TransportFailure:
                self.ledger.record_transport_failure(attempt, route, stage, exc.code)
            self.ledger.halt_dispatch(attempt)
            raise

    def seal(self):
        self.gate.seal()


def capture_sources(owner, output):
    """Supervisor is the only publisher. Late tasks cannot write or settle."""
    pool = ThreadPoolExecutor(max_workers=1)
    tracked, receipts = [], []
    status, failure, cleanup_failure = 'halted', None, None
    try:
        for source in SOURCES:
            owner.active()
            case_run = owner.ledger.begin_case(source[0])
            owner.stage_until = min(owner.until, time.monotonic() + STAGE_SECONDS)
            future = pool.submit(owner.exchange, source, case_run)
            tracked.append(future)
            try:
                attempt, body, receipt, analysis = future.result(
                    timeout=max(0, owner.stage_until - time.monotonic()))
            except TimeoutError:
                owner.ledger.halt('stage_timeout')
                failure = 'stage_timeout'
                raise BudgetError('capture stage timeout') from None
            owner.active()
            # Exclusive creation; raw bodies have already passed transport bounds,
            # status, encoding, reflection, media, and diagnostic parsing checks.
            with (output / source[6]).open('xb') as stream:
                stream.write(body)
            write_json(output / (source[6] + '.receipt.json'), receipt)
            write_json(output / (source[6] + '.analysis.json'), analysis)
            owner.active()
            owner.ledger.settle(attempt, input_tokens=0, output_tokens=0)
            owner.ledger.finish_case(case_run)
            receipts.append(receipt)
        status = 'complete'
    except BaseException:
        owner.ledger.halt('rehearsal_failure')  # Preserves any earlier failure.
        failure = failure or 'capture_failure'
    finally:
        owner.seal()
        # Track late work; never publish its results or free its claim.
        _, pending = wait(tracked, timeout=DRAIN_SECONDS)
        pool.shutdown(wait=False, cancel_futures=True)
        if not pending:
            try:
                owner.wire.close()
            except BaseException:
                cleanup_failure = 'transport_cleanup_failure'
                owner.ledger.halt('rehearsal_failure')
                status = 'halted'
        else:
            status = 'halted'
    result = {'status': status, 'failure': failure, 'cleanup_failure': cleanup_failure,
        'first_failure': owner.first_failure, 'receipts': receipts, 'ledger': owner.ledger.summary(),
        'tasks_registered': len(tracked), 'tasks_finished': sum(f.done() for f in tracked),
        'late_tasks': sum(not f.done() for f in tracked), 'native_dispatches': owner.gate.dispatched,
        'model_attempts': 0, 'model_tokens': 0, 'launch_ready': False,
        'quality_status': 'not_adjudicated', 'resume_allowed': False,
        'actual_invoice_verified': False, 'code_binding': owner.ledger.policy['code_binding']}
    # The receipt URLs/codes are fixed; derived source text has separate reflection
    # screening in the owned transport before any source/diagnostic file is written.
    write_json(output / 'artifact.json', result)
    return result


def main():
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode
            or sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 11, 9)):
        return 2
    output = Path.cwd().resolve()
    policy = json.loads((output / 'request.json').read_text())['policy']
    if policy.get('purpose') != PURPOSE or policy['approval']['output_dir'] != str(output):
        return 2
    home = output / 'isolated-home'
    if home.is_symlink() or not home.is_dir() or any(home.iterdir()):
        return 2
    selectors = ('OPENAI_API_KEY', 'SEC_USER_AGENT', 'HTTP_PROXY', 'HTTPS_PROXY',
                 'http_proxy', 'https_proxy', 'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE')
    preserved = {k: os.environ[k] for k in selectors if k in os.environ}
    os.environ.clear()
    os.environ.update(PATH='/usr/bin:/bin', HOME=str(home), PYTHONDONTWRITEBYTECODE='1',
                      CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED='false', **preserved)
    holder = []

    def audit(event, args):
        if event.startswith('socket.'):
            if holder:
                return holder[0].gate.audit(event, args)
            raise RuntimeError('unclaimed network operation')
        if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn'}:
            raise RuntimeError('capture child forbids subprocesses')
        if event == 'import' and args[0] == 'app.main':
            raise RuntimeError('server entrypoint forbidden')
        if event == 'open' and isinstance(args[0], (str, bytes)):
            raw_path = Path(args[0])
            path = raw_path.resolve()
            if (any(p.name in {'.netrc', '_netrc', '.env'} or p.name.startswith('.env.')
                    for p in (raw_path, path))):
                raise RuntimeError('ambient credential file access forbidden')
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing and not path.is_relative_to(output):
                raise RuntimeError('capture child writes outside fresh output forbidden')

    socket.has_ipv6 = False
    platform.processor = lambda: 'isolated-capture'
    sys.addaudithook(audit)
    original_dns = socket.getaddrinfo
    socket.getaddrinfo = lambda *a, **k: holder[0].gate.dns(*a, **k) if holder else (
        (_ for _ in ()).throw(RuntimeError('unclaimed DNS')))
    from validation.pilot_policy import AUDITED_DEPENDENCIES
    from validation.pilot_rehearsal import source_binding
    dependencies = {k: importlib.metadata.version(k) for k in AUDITED_DEPENDENCIES}
    actual = policy_for({**policy['code_binding'], 'source_sha256': source_binding()},
        dependencies, policy['approval'], policy['execution_configuration'])
    if digest(actual) != digest(policy):
        return 2
    ledger = AttemptLedger(output / 'ledger.sqlite', actual, create=True)
    owner = CaptureOwner(ledger)
    owner.gate.resolve = original_dns
    holder.append(owner)
    result = capture_sources(owner, output)
    # Native thread exit is bounded by the launcher deadline. Do not run Python's
    # unbounded executor atexit join with a late task after terminal publication.
    if result['late_tasks']:
        os._exit(1)
    return 0 if result['status'] == 'complete' else 1
