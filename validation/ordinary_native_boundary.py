"""Integrated ordinary-pilot boundary: the real application over native accounting.

Every SEC GET the application makes passes, in order, through: a route/stage
check against this case's admitted URLs, a nontransferable stage reservation,
a four-slot concurrency wait, the paced durable dispatch claim, the ordinary
exchange gate (native intent plus durable wire entry), the owned SEC transport,
semantic admission, and atomic body/receipt retention before settlement.

The caller supplies the network backend beneath the gate's ScopedBackend: the
synthetic SEC backend for rehearsals, or NATIVE_BACKEND (the owned transport's
own socket backend) only from the approval-gated worker modes. Model and
paid-provider requests are refused. Nothing here verifies approver identity,
invoice terms or SEC origin.
"""
import os
from pathlib import Path
from threading import BoundedSemaphore

from validation.capture_budget import BudgetError, RateLimitDelay, digest
from validation.ordinary_native_ledger import OrdinaryNativeGate, OrdinaryNativeLedger
from validation.ordinary_network import DirectScopedBackend, is_direct
from validation.ordinary_pilot_contract import quota_contract
from validation.ordinary_transport import OrdinaryHTTPTransport
from validation.pilot_approved import ScopedBackend, runtime_values
from validation.pilot_boundary import PilotBoundary
from validation.pilot_live import SubmissionRefusal, TransportFailure, json_object, submission_documents

# 'routing' is set by the worker around /ask company resolution; its stage
# quota admits only the SEC directory.
SEC_STAGES = frozenset({'routing', 'evidence.sec', 'evidence.sec_metrics',
                        'evidence.thesis_disclosures', 'evidence.filing_metrics'})
PAID_PROVIDER_ENVIRONMENT = ('FMP_API_KEY', 'FRED_API_KEY', 'NEWS_API_KEY')
# Explicit marker for the transport's own socket backend; there is no default.
NATIVE_BACKEND = object()


class _SecRefusal(Exception):
    def __init__(self, code):
        self.code = code


class _IdentityMismatch(Exception):
    pass


def boundary_cases(policy):
    """Case records from the approved policy, in their fixed order."""
    return [{'case_id': r['case_id'], 'question': r['question'], 'question_id': r['question_id'],
             'identity': {'ticker': r['issuer_id'], 'cik': r['expected_cik'],
                          'company_name': r['issuer_id']}}
            for r in policy['case_records']]


class OrdinaryNativeBoundary(PilotBoundary):
    def __init__(self, ledger, *, backend):
        if type(ledger) is not OrdinaryNativeLedger:
            raise BudgetError('ordinary boundary requires its fresh native ledger')
        policy = ledger.policy
        super().__init__(ledger, 'ordinary_native', cases=boundary_cases(policy))
        if not self.monitoring or self.freshness:
            raise BudgetError('ordinary source-evidence configuration required')
        self.runtime = runtime_values()
        self.forbidden = tuple(self.runtime.values())
        self.execution_hash = digest(policy['execution_configuration'])
        self.contact = self.runtime['sec_contact']
        self.gate = OrdinaryNativeGate(self)
        self.wire = OrdinaryHTTPTransport(gate=self.gate, execution=policy['execution_configuration'],
                                          runtime=self.runtime)
        native = self.wire._wire._pool._network_backend
        scoped = DirectScopedBackend if is_direct(policy['execution_configuration']) else ScopedBackend
        self.wire._wire._pool._network_backend = scoped(native if backend is NATIVE_BACKEND else backend, self.gate)
        self.slots = BoundedSemaphore(quota_contract()['concurrent_sec'])
        self.admitted = {}        # (case_run, stage) -> document URLs from that stage's submissions
        self.case_documents = {}  # case_run -> the first admitted URL set (drift check)
        self.refused_model_requests = 0
        self.claim_pacing_waits = self.slot_waits = 0
        self.refused_requests = []  # bounded (stage, target) diagnostics; SEC URLs are public

    # -- configuration -----------------------------------------------------------

    def active(self):
        try:
            self.ledger.require_active()
        except BudgetError:
            with self.lock:
                self.blocked_after_halt += 1
            raise
        if (digest(self.ledger.policy['execution_configuration']) != self.execution_hash
                or runtime_values() != self.runtime
                or any(os.environ.get(name) for name in PAID_PROVIDER_ENVIRONMENT)
                or os.environ.get('CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED') != 'false'
                or os.environ.get('HOME') != str(Path.cwd().resolve() / 'isolated-home')
                or Path('.env').exists()):
            self.refuse('configuration_drift')
        if self.settings is not None:
            expected = self.ledger.policy['configuration']['settings']
            missing = object()  # an absent pinned setting is drift, never an error
            if (any(getattr(self.settings, key, missing) != value for key, value in expected.items())
                    or self.settings.fmp_api_key or self.settings.fred_api_key
                    or self.settings.sec_user_agent != self.contact):
                self.refuse('configuration_drift')

    def model_request(self, request):
        """The ordinary cohort has zero model attempts; any request halts."""
        with self.lock:
            self.transport_entries['openai_mock'] += 1
            self.refused_model_requests += 1
        self.refuse('invalid_request')

    def begin(self, case):
        super().begin(case)
        with self.lock:
            self.admitted = {key: value for key, value in self.admitted.items() if key[0] == self.case_run}

    # -- SEC routing -------------------------------------------------------------

    def _refuse_request(self, stage, url):
        from urllib.parse import urlsplit
        try:
            host = urlsplit(url).hostname if type(url) is str else None
        except ValueError:
            host = None
        target = url if host in {'www.sec.gov', 'data.sec.gov'} else (host or 'unparseable')
        with self.lock:
            if len(self.refused_requests) < 20:
                self.refused_requests.append({'stage': stage, 'target': target})
        self.refuse()

    def sec_route(self, method, url, body):
        self.active()
        stage = self.stage.get()
        if method != 'GET' or body is not None or type(url) is not str or stage not in SEC_STAGES:
            self._refuse_request(stage, url)
        cik = self.case['identity']['cik']
        fixed = {'https://www.sec.gov/files/company_tickers.json': 'sec/directory',
                 f'https://data.sec.gov/submissions/CIK{cik}.json': 'sec/submissions',
                 f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json': 'sec/facts'}
        with self.lock:
            documents = self.admitted.get((self.case_run, stage), frozenset())
        # A filing document is admissible only after this case and stage
        # validated a submissions response listing that exact URL.
        route = fixed.get(url) or ('sec/document' if url in documents else None)
        if route is None:
            self._refuse_request(stage, url)
        with self.lock:
            self.sec_route_calls[route] = self.sec_route_calls.get(route, 0) + 1
        return route

    def _acquire_slot(self, case_run):
        """Wait for one of four SEC slots, never past the case deadline."""
        while not self.slots.acquire(timeout=0.05):
            with self.lock:
                self.slot_waits += 1
            self.active()
            if self.ledger.case_remaining_seconds(case_run) <= 0:
                return False
        return True

    def _admit(self, route, stage, media, content):
        """Semantic checks on a complete 200 response, before retention."""
        if route == 'sec/document':
            if media not in {'text/html', 'text/plain'}:
                raise _SecRefusal('sec_media_type')
            return
        if media != 'application/json':
            raise _SecRefusal('sec_media_type')
        try:
            data = json_object(content)
        except BaseException:
            raise TransportFailure('response_json') from None
        if type(data) is not dict:
            raise _IdentityMismatch()
        cik = self.case['identity']['cik']
        if route == 'sec/directory':
            # Full directories are valid; every cohort ticker must occur once
            # with its exact CIK. Other issuers never become authorized routes.
            for identity in self.identities:
                matches = [row for row in data.values() if type(row) is dict
                           and row.get('ticker') == identity['ticker']]
                if (len(matches) != 1 or type(matches[0].get('cik_str')) is not int
                        or str(matches[0]['cik_str']).zfill(10) != identity['cik']):
                    raise _IdentityMismatch()
            return
        if str(data.get('cik', '')).zfill(10) != cik:
            raise _IdentityMismatch()
        if route == 'sec/submissions':
            try:
                urls, _, _ = submission_documents(data, cik)
            except SubmissionRefusal as refusal:
                raise _SecRefusal(refusal.code) from None
            except (KeyError, TypeError, AttributeError):
                raise _SecRefusal('sec_recent_array_shape') from None
            urls = frozenset(urls)
            with self.lock:
                if self.case_documents.setdefault(self.case_run, urls) != urls:
                    self.refuse('configuration_drift')
                self.admitted[(self.case_run, stage)] = urls

    def sec_exchange(self, method, url, body):
        route = self.sec_route(method, url, body)
        stage, case_run = self.stage.get(), self.case_run
        fingerprint = digest({'method': 'GET', 'url': url, 'route': route, 'stage': stage})
        attempt = self.ledger.reserve(case_run, route, stage=stage, input_bound=0, output_bound=0,
                                      request_sha256=fingerprint)
        slot = claimed = False
        token = None
        try:
            slot = self._acquire_slot(case_run)
            if not slot:
                self.ledger.halt('stage_timeout')
                raise BudgetError('SEC slot unavailable before the case deadline')
            while True:  # pacing before dispatch only; no I/O is ever retried
                self.active()
                try:
                    self.ledger.claim_dispatch(attempt, case_run=case_run, route=route,
                                               request_sha256=fingerprint, input_bound=0, output_bound=0)
                    break
                except RateLimitDelay as delay:
                    with self.lock:
                        self.claim_pacing_waits += 1
                    self.release.wait(min(delay.seconds, 0.05))
            claimed = True
            with self.lock:
                self.inflight += 1
                self.max_inflight = max(self.max_inflight, self.inflight)
                self.events.append({'case_id': self.case['case_id'], 'route': route, 'stage': stage,
                                    'attempt_id': attempt})
            grant = self.gate.issue(attempt, fingerprint, route, case_run, stage)
            token = self.sec_attempt.set((attempt, route, stage))
            with self.gate.exchange(url, grant, fingerprint):
                media, content = self.wire.exchange('GET', url)
            self._admit(route, stage, media, content)
            try:
                self.ledger.complete_response(attempt, url=url, media_type=media, body=content,
                                              forbidden_values=self.forbidden)
            except BudgetError:
                self._record(attempt, 'retention_refused', route)
                raise
            return media, content
        except BaseException as exc:
            self._fail(exc, attempt, route, stage, claimed)
            raise BudgetError('ordinary SEC exchange refused') from None
        finally:
            if token is not None:
                self.sec_attempt.reset(token)
            if claimed:
                self.done()
            if slot:
                self.slots.release()

    def _record(self, attempt, code, detail):
        try:
            self.ledger.record_exchange_failure(attempt, code, detail)
        except BaseException:
            pass  # The durable halt already set (or set below) remains primary.

    def _fail(self, exc, attempt, route, stage, claimed):
        """Keep the attempt consumed; preserve the first meaningful cause."""
        self.release.set()
        try:
            if type(exc) is TransportFailure:
                self.ledger.record_transport_failure(attempt, route, stage, exc.code)
                self._record(attempt, 'transport', exc.code)
            elif type(exc) is _SecRefusal:
                self.ledger.record_sec_refusal(attempt, route, stage, exc.code)
                self._record(attempt, 'sec_refusal', exc.code)
            elif type(exc) is _IdentityMismatch:
                self.ledger.halt('identity_mismatch')
                self._record(attempt, 'identity_mismatch', route)
            elif not claimed:
                self._record(attempt, 'halted_before_dispatch', route)
            else:
                self._record(attempt, 'interrupted', route)
            if claimed:
                self.ledger.halt_dispatch(attempt)
            else:
                self.ledger.halt('rehearsal_failure')
        except BaseException:
            try:
                self.ledger.halt('rehearsal_failure')
            except BaseException:
                pass

    # -- lifecycle ---------------------------------------------------------------

    def complete_case(self, response):
        """Retain the whole application response and finish the active case."""
        self.ledger.complete_case(self.case_run, response, forbidden_values=self.forbidden)

    def close(self):
        # Keep every bridge installed through process exit, including while
        # abandoned threads unwind. Never restore ordinary requests/urllib.
        self.gate.seal()
        self.drain()
        for pool in self.pools:
            pool.shutdown(wait=False)
        self.http.close()
        self.wire.close()
