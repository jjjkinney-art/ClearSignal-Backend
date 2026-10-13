"""Benchmark-only bridges. Installed in an isolated child before app imports.

Every apparent provider exchange is synthetic. No live transport is accepted.
This is cooperative rehearsal assurance, not a sandbox for arbitrary Python.
"""
from concurrent import futures
from contextvars import ContextVar
from io import BytesIO
import hashlib
import json
import netrc
import os
from pathlib import Path
from threading import Barrier, Event, Lock
from typing import NamedTuple
from unittest.mock import patch
from urllib import request as urllib_request

import httpx
import openai
from openai.resources.chat.completions import Completions
import requests

from validation.capture_budget import BudgetError, RateLimitDelay, digest
from validation.pilot_fixtures import (
    SECRET_CANARIES, SYNTHETIC_CONTACT, document_url, model_fixture, sec_fixture,
)
from validation.pilot_policy import PILOT_SETTINGS, response_usage, validate_model_payload
from validation.pilot_preflight import preflight


class FrozenModelRequest(NamedTuple):
    """Private immutable wire values, captured before validation and claiming."""
    method: str
    url: str
    body: bytes


class PilotBoundary:
    def __init__(self, ledger, scenario):
        self.ledger, self.scenario = ledger, scenario
        self.contact = SYNTHETIC_CONTACT
        self.cases = preflight()['cases']
        self.identities = [case['identity'] for case in self.cases[::2]]
        self.case = self.case_run = None
        self.stage = ContextVar('offline_pilot_stage', default='outside_pipeline')
        self.patches, self.pools, self.futures = [], [], []
        self.pool_index = 0
        self.lock = Lock()
        self.claimed = Event()
        self.release = Event()
        self.fault_used = False
        self.events = []
        self.sec_route_calls = {}
        self.transport_entries = {'openai_mock': 0, 'urllib': 0, 'requests': 0}
        self.blocked_after_halt = 0
        self.constructor_failures = self.ambiguous_submissions = self.queued_submissions_fenced = 0
        self.inflight = self.max_inflight = 0
        self.sec_contact_applied = True
        self.sec_authorization_header_absent = True
        self.settings = None
        self.model_clients = []
        self.concurrent_agents = Barrier(6)
        self.original_wait = futures.wait
        self.original_executor = futures.ThreadPoolExecutor
        self.http = httpx.Client(transport=httpx.MockTransport(self.model_request),
                                 follow_redirects=False, trust_env=False)

    def refuse(self, reason='invalid_request'):
        self.ledger.halt(reason)
        self.release.set()
        raise BudgetError('offline pilot boundary refused this operation')

    def active(self):
        try:
            self.ledger.require_active()
        except BudgetError:
            with self.lock:
                self.blocked_after_halt += 1
            raise
        if self.settings is not None:
            if (any(getattr(self.settings, key) != value for key, value in PILOT_SETTINGS.items())
                    or self.settings.sec_user_agent != self.contact
                    or self.settings.fmp_api_key or self.settings.fred_api_key
                    or os.environ.get('CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED') != 'false'
                    or os.environ.get('HOME') != str(Path.cwd().resolve() / 'isolated-home')
                    or Path('.env').exists()):
                self.refuse('configuration_drift')
            for client in self.model_clients:
                if client.max_retries != 1:
                    self.refuse('configuration_drift')

    def once(self, names):
        with self.lock:
            if not self.fault_used and self.scenario in names:
                self.fault_used = True
                return True
        return False

    def _patch(self, target, name, value):
        item = patch.object(target, name, value)
        item.start()
        self.patches.append(item)

    def install(self):
        owner = self
        original_init = openai.OpenAI.__init__
        original_create = Completions.create
        original_send = httpx.Client.send
        original_session_init = requests.sessions.Session.__init__
        original_prepare = requests.sessions.Session.prepare_request
        original_executor_init = owner.original_executor.__init__

        def executor_init(pool, *args, **kwargs):
            original_executor_init(pool, *args, **kwargs)
            if owner.once({str(getattr(pool, 'kind', '')) + '_constructor_failure'}):
                raise RuntimeError('invented executor construction failure')

        def session_init(session, *args, **kwargs):
            original_session_init(session, *args, **kwargs)
            session.trust_env = False

        def prepare(session, request):
            # This must run before Session.prepare_request can discover netrc.
            # Reject changed/copied sessions that re-enable ambient authority.
            if session.trust_env is not False:
                owner.refuse('configuration_drift')
            return original_prepare(session, request)

        def no_netrc(*args, **kwargs):
            # Also fences requests' imported aliases and aliases saved before
            # bridge installation that eventually invoke stdlib netrc.netrc.
            owner.refuse('configuration_drift')

        def sdk_init(client, *args, **kwargs):
            if (args or set(kwargs) - {'api_key', 'timeout', 'max_retries', 'http_client',
                                       'organization', 'project', 'default_headers', 'default_query',
                                       'base_url', 'workload_identity', 'webhook_secret', 'websocket_base_url'}
                    or kwargs.get('max_retries', 0) != 0
                    or kwargs.get('http_client') not in (None, owner.http)
                    or kwargs.get('organization') is not None or kwargs.get('project') is not None
                    or any(kwargs.get(key) is not None for key in
                           ('workload_identity', 'webhook_secret', 'websocket_base_url'))
                    or kwargs.get('default_headers') or kwargs.get('default_query')
                    or callable(kwargs.get('api_key'))
                    or str(kwargs.get('base_url') or 'https://api.openai.com/v1').rstrip('/') != 'https://api.openai.com/v1'):
                owner.refuse()
            kwargs.update(max_retries=0, http_client=owner.http)
            original_init(client, **kwargs)

        def create(resource, *args, **kwargs):
            owner.active()
            if owner.once({'sdk_copy_retry'}):
                resource._client.with_options(max_retries=2)
            if owner.once({'sdk_copy_valid'}):
                resource = resource._client.with_options(max_retries=0).chat.completions
            if owner.once({'sdk_retry_drift'}):
                resource._client.max_retries = 2
            if resource._client.max_retries != 0 or resource._client._client is not owner.http:
                owner.refuse('configuration_drift')
            if owner.once({'configuration_drift'}):
                owner.settings.agent_model = 'unreviewed-model'
                owner.active()
            if owner.once({'custom_request_header'}):
                kwargs['extra_headers'] = {'X-Unreviewed': 'invented-fixture'}
            if (args or set(kwargs) - {'model', 'messages', 'temperature', 'max_tokens',
                                      'service_tier', 'n', 'stream'}):
                owner.refuse()
            for name, value in {'service_tier': 'default', 'n': 1, 'stream': False}.items():
                if name in kwargs and (type(kwargs[name]) is not type(value) or kwargs[name] != value):
                    owner.refuse()
                kwargs[name] = value
            if owner.once({'unknown_model_route'}):
                kwargs['model'] = 'unreviewed-model'
            if owner.once({'oversize_input'}):
                kwargs['messages'] = [{'role': 'user', 'content': 'x' * 128_000}]
            if owner.once({'request_secret'}):
                kwargs['messages'] = [{'role': 'user', 'content': SECRET_CANARIES[0]}]
            result = original_create(resource, **kwargs)
            if owner.once({'duplicate_stage'}):
                return original_create(resource, **kwargs)
            return result

        def send(client, request, *args, **kwargs):
            if client is not owner.http:
                owner.refuse()
            return original_send(client, request, *args, **kwargs)

        def request_send(session, request, **kwargs):
            return owner.sec_requests(request)

        def opener_open(opener, fullurl, data=None, timeout=None):
            return owner.sec_urlopen(fullurl, data=data, timeout=timeout)

        self._patch(openai.OpenAI, '__init__', sdk_init)
        self._patch(Completions, 'create', create)
        self._patch(httpx.Client, 'send', send)
        self._patch(requests.sessions.Session, '__init__', session_init)
        self._patch(requests.sessions.Session, 'prepare_request', prepare)
        self._patch(requests.sessions, 'get_netrc_auth', no_netrc)
        self._patch(requests.utils, 'get_netrc_auth', no_netrc)
        self._patch(netrc, 'netrc', no_netrc)
        self._patch(requests.sessions.Session, 'send', request_send)
        self._patch(urllib_request, 'urlopen', self.sec_urlopen)
        self._patch(urllib_request.OpenerDirector, 'open', opener_open)
        self._patch(owner.original_executor, '__init__', executor_init)

        class PipelinePool(owner.original_executor):
            def __init__(pool, max_workers=None, *args, **kwargs):
                owner.active()
                owner.pool_index += 1
                source = owner.case['case_id'].endswith(':core_thesis')
                if owner.pool_index == 1:
                    pool.kind = 'evidence'
                    pool.names = ['fmp', 'sec', 'news_co', 'news_macro', 'fred', 'valuation', 'estimates']
                    if source:
                        pool.names += ['sec_metrics', 'thesis_disclosures', 'filing_metrics']
                    expected = len(pool.names)
                elif not source and owner.pool_index == 2:
                    pool.kind = 'agents'
                    pool.names = ['valuation', 'macro', 'risk', 'market', 'quality', 'question_answerer']
                    expected = 6
                elif not source and owner.pool_index in (3, 4):
                    pool.kind, pool.names, expected = 'synthesis', ['synthesis'], 1
                else:
                    owner.refuse()
                if max_workers != expected or args or kwargs:
                    owner.refuse()
                pool.submitted = 0
                try:
                    super().__init__(max_workers=max_workers)
                except BaseException:
                    owner.constructor_failures += 1
                    owner.refuse('pool_failure')
                owner.pools.append(pool)

            def _adjust_thread_count(pool):
                # Faults occur INSIDE the actual CPython submit, after it queues
                # the WorkItem. No injected refusal preempts the real failure.
                if (pool.kind == 'agents' and pool.submitted == 2
                        and owner.case['identity']['ticker'] == 'ACHC'
                        and owner.scenario == 'agent_submit_failure'):
                    owner.claimed.wait(2)
                    raise RuntimeError('invented thread start failure after queueing')
                if pool.kind == 'synthesis' and owner.scenario == 'synthesis_submit_failure':
                    raise RuntimeError('invented thread start failure after queueing')
                super()._adjust_thread_count()
                if pool.kind == 'synthesis' and owner.scenario == 'synthesis_running_submit_failure':
                    owner.claimed.wait(2)
                    raise RuntimeError('invented submit failure with running work')

            def submit(pool, fn, /, *args, **kwargs):
                owner.active()
                index = pool.submitted
                pool.submitted += 1
                if index >= len(pool.names):
                    owner.refuse()
                if pool.kind == 'evidence' and index == 3 and owner.scenario == 'partial_pool_failure':
                    owner.claimed.wait(1)
                    owner.refuse('pool_failure')
                name = pool.names[index]
                stage = 'evidence.' + name if pool.kind == 'evidence' else name
                # Track work BEFORE handing it to an executor. submit may queue
                # executable work and then raise without returning its Future.
                tracked = futures.Future()
                ticket = {'started': False, 'fenced': False}
                owner.futures.append(tracked)

                def run():
                    with owner.lock:
                        if ticket['fenced']:
                            return None  # Ambiguously queued work may wake later.
                        ticket['started'] = True
                    token = owner.stage.set(stage)
                    try:
                        owner.active()
                        return fn(*args, **kwargs)
                    except BaseException:
                        owner.ledger.halt('pool_failure')
                        owner.release.set()
                        raise BudgetError('offline pipeline worker failed') from None
                    finally:
                        owner.stage.reset(token)
                        tracked.set_result(None)

                try:
                    future = super().submit(run)
                except BaseException:
                    # Durable fence first, before router fallback/another pool.
                    owner.ledger.halt('pool_failure')
                    owner.release.set()
                    with owner.lock:
                        owner.ambiguous_submissions += 1
                        if not ticket['started']:
                            ticket['fenced'] = True
                            owner.queued_submissions_fenced += 1
                            tracked.set_result(None)
                    raise BudgetError('offline executor submission failed') from None
                future._pilot_stage = stage
                future._pilot_pool = pool.kind
                return future

        def wait(items, timeout=None, return_when=futures.ALL_COMPLETED):
            kind = next(iter(items))._pilot_pool if items else ''
            injected = owner.scenario == {'evidence': 'evidence_timeout', 'agents': 'agent_timeout',
                                          'synthesis': 'synthesis_timeout'}.get(kind)
            if injected:
                owner.claimed.wait(1)
            done, pending = owner.original_wait(items, timeout=0.02 if injected else timeout,
                                                 return_when=return_when)
            # Only the normal first SEC-document wait has a reviewed grace
            # period. Ordinary providers, agents and synthesis halt immediately.
            grace = (not injected and timeout == 10 and owner.case['case_id'].endswith(':core_thesis')
                     and all(f._pilot_stage in {'evidence.thesis_disclosures', 'evidence.filing_metrics'}
                             for f in pending))
            if pending and not grace:
                owner.ledger.halt('stage_timeout')
                owner.release.set()
            return done, pending

        self._patch(futures, 'ThreadPoolExecutor', PipelinePool)
        self._patch(futures, 'wait', wait)

    def begin(self, case):
        self.case = case
        self.case_run = self.ledger.begin_case(case['case_id'])
        self.pool_index = 0
        self.claimed.clear()
        self.release.clear()

    def claim(self, route, fingerprint, inputs, outputs):
        self.active()
        binding = dict(case_run=self.case_run, route=route, request_sha256=fingerprint,
                       input_bound=inputs, output_bound=outputs)
        attempt = self.ledger.reserve(**binding)
        while True:
            try:
                self.active()
                self.ledger.claim_dispatch(attempt, **binding)
                break
            except RateLimitDelay as delay:
                # No SQLite or bridge lock is held during the pacing wait.
                self.release.wait(min(delay.seconds, 0.05))
        with self.lock:
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
            self.events.append({'case_id': self.case['case_id'], 'route': route,
                                'attempt_id': attempt, 'input_reservation_tokens': inputs,
                                'output_bound_tokens': outputs})
        is_model = route.startswith('model/')
        target = ((self.scenario in {'evidence_timeout', 'partial_pool_failure'} and not is_model)
                  or (self.scenario == 'agent_timeout' and is_model and route != 'model/synthesis')
                  or (self.scenario in {'synthesis_timeout', 'synthesis_running_submit_failure'}
                      and route == 'model/synthesis')
                  or (self.scenario == 'agent_submit_failure'
                      and self.case['identity']['ticker'] == 'ACHC' and route == 'model/valuation'))
        if target and self.once({self.scenario}):
            self.claimed.set()
            self.release.wait(2)
        if is_model and self.once({'crash_after_claim'}):
            os._exit(37)  # Deliberate fixture crash AFTER the durable one-shot claim.
        if (self.scenario in {'concurrency', 'concurrent_usage_failure'}
                and self.case['identity']['ticker'] == 'ACHC'
                and is_model and route != 'model/synthesis'):
            # All six real agent workers must claim while earlier exchanges
            # remain in flight. This deadlocks if any dispatch holds the DB lock.
            self.concurrent_agents.wait(timeout=3)
        return attempt

    def done(self):
        with self.lock:
            self.inflight -= 1

    def model_request(self, request):
        with self.lock:
            self.transport_entries['openai_mock'] += 1
        self.active()
        try:
            if (type(request) is not httpx.Request or type(request.stream) is not httpx.ByteStream
                    or set(request.extensions) - {'timeout'}):
                self.refuse()
            snapshot = FrozenModelRequest(request.method, str(request.url), request.read())
            if (type(snapshot.method) is not str or type(snapshot.body) is not bytes
                    or snapshot.method != 'POST'
                    or snapshot.url != 'https://api.openai.com/v1/chat/completions'):
                self.refuse()
            if any(canary.encode() in snapshot.body for canary in SECRET_CANARIES):
                self.refuse()
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise BudgetError('duplicate request field')
                    result[key] = value
                return result
            payload = json.loads(snapshot.body, object_pairs_hook=unique_object)
            self.validate_request_values(snapshot.body, payload)
            stage = self.stage.get()
            inputs, outputs = validate_model_payload(payload, stage)
            expected_timeout = 55.0 if stage == 'synthesis' else 15.0
            timeout = request.extensions.get('timeout')
            if (type(timeout) is not dict or set(timeout) != {'connect', 'read', 'write', 'pool'}
                    or any(value != expected_timeout for value in timeout.values())):
                self.refuse('configuration_drift')
            # Credentials, contact values and ALL headers are intentionally absent.
            fingerprint = digest({'method': snapshot.method, 'url': snapshot.url,
                                  'body_sha256': hashlib.sha256(snapshot.body).hexdigest(),
                                  'stage': stage})
            attempt = self.claim('model/' + stage, fingerprint, inputs, outputs)
        except (BudgetError, ValueError, UnicodeError, TypeError):
            self.ledger.halt('invalid_request')
            raise BudgetError('model request refused') from None
        try:
            status, data = self.model_exchange(snapshot, stage)
            if (self.case['identity']['ticker'] == 'ACHC'
                    and self.once({'concurrent_usage_failure'})):
                data.pop('usage')
            elif self.once({'model_429', 'model_500'}):
                status = 429 if self.scenario == 'model_429' else 500
                data = {'error': {'message': SECRET_CANARIES[-1], 'type': 'fixture_error'}}
            elif self.once({'missing_usage'}):
                data.pop('usage')
            elif self.once({'excess_usage'}):
                data['usage'].update(completion_tokens=outputs + 1, total_tokens=outputs + 101)
            elif self.once({'model_mismatch'}):
                data['model'] = 'unreviewed-model'
            elif self.once({'tier_mismatch'}):
                data['service_tier'] = 'priority'
            elif self.once({'unknown_usage'}):
                data['usage']['unpriced_units'] = 1
            elif self.once({'secret_reflection'}):
                data['choices'][0]['message']['content'] = SECRET_CANARIES[-1]
            encoded = json.dumps(data).encode()
            if status >= 400:
                try:
                    self.ledger.settle(attempt)
                except BudgetError:
                    pass
                # Exercise real SDK HTTP-error handling with retries disabled.
                return httpx.Response(status, content=encoded)
            if any(canary.encode() in encoded for canary in SECRET_CANARIES):
                self.refuse('invalid_response')
            usage = response_usage(data, outputs)
            self.ledger.settle(attempt, input_tokens=usage[0], output_tokens=usage[1])
            with self.lock:
                event = next(item for item in self.events if item['attempt_id'] == attempt)
                event['usage'] = {'input_tokens': usage[0], 'output_tokens': usage[1],
                                  'model': data['model'], 'service_tier': data['service_tier']}
            return httpx.Response(status, content=encoded)
        except BaseException:
            self.ledger.halt_dispatch(attempt)
            raise BudgetError('model fixture response refused') from None
        finally:
            self.done()

    def validate_request_values(self, raw, payload):
        """Additional runtime-only exclusions supplied by approved boundaries."""
        pass

    def model_exchange(self, snapshot, stage):
        return 200, model_fixture(stage, self.case['identity'])

    def sec_document_urls(self):
        return {document_url(self.case['identity'])}

    def sec_content(self, route, url):
        return sec_fixture(route, self.case['identity'], self.identities)

    def sec_route(self, method, url, body):
        self.active()
        identity = self.case['identity']
        allowed = {
            'https://www.sec.gov/files/company_tickers.json': 'sec/directory',
            f'https://data.sec.gov/submissions/CIK{identity["cik"]}.json': 'sec/submissions',
            f'https://data.sec.gov/api/xbrl/companyfacts/CIK{identity["cik"]}.json': 'sec/facts',
            **{url: 'sec/document' for url in self.sec_document_urls()},
        }
        if self.once({'unknown_sec_route'}):
            url = 'https://unreviewed.invalid/'
        if self.once({'sec_post'}):
            method = 'POST'
        if self.once({'sec_body'}):
            body = b'invented-body'
        if method != 'GET' or body is not None or type(url) is not str or url not in allowed:
            self.refuse()
        stage = self.stage.get()
        if stage not in {'evidence.sec', 'evidence.sec_metrics',
                         'evidence.thesis_disclosures', 'evidence.filing_metrics'}:
            self.refuse()
        with self.lock:
            route = allowed[url]
            self.sec_route_calls[route] = self.sec_route_calls.get(route, 0) + 1
        return allowed[url]

    def sec_exchange(self, method, url, body):
        route = self.sec_route(method, url, body)
        fingerprint = digest({'method': method, 'url': url, 'route': route,
                              'stage': self.stage.get()})
        attempt = self.claim(route, fingerprint, 0, 0)
        try:
            media_type, content = self.sec_content(route, url)
            if self.once({'sec_redirect'}):
                self.refuse('invalid_response')  # No Location or redirect is followed.
            if route == 'sec/directory':
                data = json.loads(content)
                if self.once({'sec_identity_mismatch'}):
                    data['0']['cik_str'] = 1
                actual = {row['ticker']: str(row['cik_str']).zfill(10) for row in data.values()}
                if any(actual.get(item['ticker']) != item['cik'] for item in self.identities):
                    self.refuse('identity_mismatch')
            elif route in {'sec/submissions', 'sec/facts'}:
                data = json.loads(content)
                if self.once({'sec_response_identity_mismatch'}):
                    data['cik'] = '1'
                if str(data.get('cik', '')).zfill(10) != self.case['identity']['cik']:
                    self.refuse('identity_mismatch')
            self.ledger.settle(attempt, input_tokens=0, output_tokens=0)
            return media_type, content
        except BaseException:
            self.ledger.halt_dispatch(attempt)
            raise BudgetError('SEC fixture response refused') from None
        finally:
            self.done()

    def sec_urlopen(self, request, data=None, timeout=None, **kwargs):
        with self.lock:
            self.transport_entries['urllib'] += 1
        if kwargs or not isinstance(request, urllib_request.Request) or data is not None:
            self.refuse()
        contact = self.settings.sec_user_agent
        request.add_header('User-Agent', contact)
        self.sec_contact_applied &= request.get_header('User-agent') == contact
        _, content = self.sec_exchange(request.get_method(), request.full_url, request.data)
        return BytesIO(content)

    def sec_requests(self, request):
        with self.lock:
            self.transport_entries['requests'] += 1
        if type(request) is not requests.PreparedRequest:
            self.refuse()
        self.sec_authorization_header_absent &= 'Authorization' not in request.headers
        if set(name.lower() for name in request.headers) - {'user-agent', 'accept', 'accept-encoding', 'connection'}:
            self.refuse()
        contact = self.settings.sec_user_agent
        request.headers['User-Agent'] = contact
        self.sec_contact_applied &= request.headers.get('User-Agent') == contact
        media_type, content = self.sec_exchange(request.method, request.url, request.body)
        response = requests.Response()
        response.status_code, response.url = 200, request.url
        response._content, response._content_consumed = content, True
        response.headers['Content-Type'] = media_type
        response.encoding = 'utf-8'
        return response

    def drain(self):
        self.release.set()
        _, pending = self.original_wait(self.futures, timeout=3)
        if pending:
            self.ledger.halt('stage_timeout')
        return len(pending)

    def close(self):
        self.drain()
        for pool in self.pools:
            pool.shutdown(wait=False)
        self.http.close()
        for item in reversed(self.patches):
            item.stop()
