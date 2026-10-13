"""Disabled benchmark live-adapter slice; only synthetic wire validation is exposed.

The owned transport is suitable for network-secret substitution: its bearer value
is an invented placeholder, never an environment lookup. This module neither
loads credentials nor grants execution/spending authority. The isolated launcher
always blocks sockets and supplies an internal fake network backend.
"""
import json
import re
import ssl
from types import MappingProxyType

import httpx

from validation.capture_budget import BudgetError
from validation.pilot_boundary import PilotBoundary
from validation.pilot_fixtures import SECRET_CANARIES, SYNTHETIC_CONTACT, SYNTHETIC_KEY

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


TRANSPORT_FAILURE_CODES = frozenset({
    'request_gate', 'request_build', 'dispatch_gate', 'connect_timeout', 'connect_error',
    'proxy_error', 'tls_error', 'write_timeout', 'write_error', 'read_timeout', 'read_error',
    'pool_timeout', 'protocol_error', 'transport_other', 'http_redirect', 'http_auth',
    'http_throttled', 'http_client_error', 'http_server_error', 'http_other_status',
    'response_encoding', 'response_size', 'response_json', 'response_reflection', 'response_close',
})


class TransportFailure(BudgetError):
    def __init__(self, code):
        if type(code) is not str or code not in TRANSPORT_FAILURE_CODES:
            raise BudgetError('invalid transport failure code')
        self.code = code
        super().__init__('owned HTTP exchange failed')


def transport_failure_code(exc):
    # Inspect types only; never copy exception messages, headers or request objects.
    current = exc
    for _ in range(8):
        if isinstance(current, ssl.SSLError):
            return 'tls_error'
        current = getattr(current, '__cause__', None)
        if current is None:
            break
    for kind, code in ((httpx.ProxyError, 'proxy_error'),
                       (httpx.ConnectTimeout, 'connect_timeout'), (httpx.ConnectError, 'connect_error'),
                       (httpx.WriteTimeout, 'write_timeout'), (httpx.WriteError, 'write_error'),
                       (httpx.ReadTimeout, 'read_timeout'), (httpx.ReadError, 'read_error'),
                       (httpx.PoolTimeout, 'pool_timeout'), (httpx.ProtocolError, 'protocol_error')):
        if isinstance(exc, kind):
            return code
    return 'transport_other'


def json_object(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BudgetError('duplicate response field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


class OwnedHTTPTransport:
    """No SDK, redirect, cookie jar, environment, auth discovery or retry loop.

    No public caller-supplied transport/handler. The isolated test worker replaces
    only the socket backend, exercising HTTPX/httpcore's actual HTTP protocol path.
    All calls must be made after the boundary's atomic dispatch claim.
    """
    def __init__(self, *, gate=None, execution=None, runtime=None):
        self.gate = gate
        self.execution = MappingProxyType(dict(execution)) if execution is not None else None
        self.runtime = MappingProxyType(dict(runtime)) if runtime is not None else None
        if gate is not None:
            from validation.pilot_approved import verify_network_configuration
            context = verify_network_configuration(execution, tls=True)
            gate.tls_context = context
            self._wire = httpx.HTTPTransport(retries=0, trust_env=False, proxy=execution['proxy'], verify=context)
        else:
            self._wire = httpx.HTTPTransport(retries=0, trust_env=False, proxy=None)

    def exchange(self, method, url, *, body=b'', timeout=10.0):
        from validation._pilot_wire_fixtures import SyntheticNetworkBackend
        if self.gate is None and type(self._wire._pool._network_backend) is not SyntheticNetworkBackend:
            raise BudgetError('real provider execution remains disabled')
        if self.gate is not None:
            try:
                self.gate.validate_request(method, url, body)
            except BaseException:
                raise TransportFailure('request_gate') from None
        headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity'}
        if method == 'POST' and url == 'https://api.openai.com/v1/chat/completions':
            headers.update({'Authorization': 'Bearer ' + (self.runtime['bearer_placeholder'] if self.runtime else SYNTHETIC_KEY),
                            'Content-Type': 'application/json'})
        elif method == 'GET' and url.startswith(('https://www.sec.gov/', 'https://data.sec.gov/')):
            headers['User-Agent'] = self.runtime['sec_contact'] if self.runtime else SYNTHETIC_CONTACT
        else:
            raise BudgetError('unsupported owned transport operation')
        try:
            request = httpx.Request(method, url, headers=headers, content=body,
                                    extensions={'timeout': dict.fromkeys(('connect', 'read', 'write', 'pool'), timeout)})
        except BaseException:
            raise TransportFailure('request_build') from None
        response = None
        failure = None
        phase = 'dispatch_gate'
        result = None
        try:
            if self.gate is not None:
                self.gate.record_dispatch()
            phase = 'transport_other'
            response = self._wire.handle_request(request)
            if response.status_code != 200:
                status = response.status_code
                code = ('http_redirect' if 300 <= status < 400 else
                        'http_auth' if status in {401, 403} else
                        'http_throttled' if status == 429 else
                        'http_client_error' if 400 <= status < 500 else
                        'http_server_error' if 500 <= status < 600 else 'http_other_status')
                raise TransportFailure(code)
            if response.headers.get('content-encoding', 'identity') != 'identity':
                raise TransportFailure('response_encoding')
            content = bytearray()
            for chunk in response.iter_raw():
                if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise TransportFailure('response_size')
                content.extend(chunk)
            media = response.headers.get('content-type', '').split(';')[0]
            if self.runtime is not None:
                from validation.pilot_policy import reject_runtime_values
                phase = 'response_json'
                parsed = json_object(bytes(content)) if media == 'application/json' else None
                phase = 'response_reflection'
                reject_runtime_values(parsed, (*SECRET_CANARIES, *self.runtime.values()), raw=bytes(content))
            elif any(canary.encode() in content for canary in SECRET_CANARIES):
                raise TransportFailure('response_reflection')
            result = media, bytes(content)
        except BaseException as exc:
            failure = (exc.code if type(exc) is TransportFailure else
                       transport_failure_code(exc) if phase == 'transport_other' else phase)
        finally:
            if response is not None:
                try:
                    response.close()
                except BaseException:
                    if failure is None:
                        failure = 'response_close'
        if failure is not None:
            raise TransportFailure(failure) from None
        return result

    def close(self):
        self._wire.close()


class LiveAdapterBoundary(PilotBoundary):
    """Reuse the integrated pipeline fences, quotas, claims and settlement."""
    def __init__(self, ledger, scenario):
        if ledger.policy.get('purpose') != 'disabled_live_adapter_validation':
            raise BudgetError('explicit disabled live-adapter policy required')
        super().__init__(ledger, scenario)
        self.wire = OwnedHTTPTransport()
        from validation._pilot_wire_fixtures import SyntheticNetworkBackend
        self.wire._wire._pool._network_backend = SyntheticNetworkBackend(self)
        self.documents = {}

    def model_exchange(self, snapshot, stage):
        media, body = self.wire.exchange(snapshot.method, snapshot.url, body=snapshot.body,
                                         timeout=55.0 if stage == 'synthesis' else 15.0)
        if media != 'application/json':
            self.refuse('invalid_response')
        try:
            return 200, json_object(body)
        except BaseException:
            raise TransportFailure('response_json') from None

    def sec_document_urls(self):
        with self.lock:
            return set(self.documents.get(self.case['identity']['cik'], ()))

    def refuse_sec_response(self, code):
        attempt, route, stage = self.sec_attempt.get()
        self.ledger.record_sec_refusal(attempt, route, stage, code)
        self.refuse('invalid_response')

    def sec_content(self, route, url):
        media, content = self.wire.exchange('GET', url)
        if route == 'sec/document':
            if media not in {'text/html', 'text/plain'}:
                self.refuse_sec_response('sec_media_type')
            return media, content
        if media != 'application/json':
            self.refuse_sec_response('sec_media_type')
        try:
            data = json_object(content)
        except BaseException:
            raise TransportFailure('response_json') from None
        if route == 'sec/directory':
            # Full directories are valid; every frozen ticker must occur once
            # with its exact CIK. Other issuers never become authorized routes.
            for identity in self.identities:
                matches = [row for row in data.values() if type(row) is dict
                           and row.get('ticker') == identity['ticker']]
                if (len(matches) != 1 or type(matches[0].get('cik_str')) is not int
                        or str(matches[0]['cik_str']).zfill(10) != identity['cik']):
                    self.refuse('identity_mismatch')
        elif route == 'sec/submissions':
            cik = self.case['identity']['cik']
            if str(data.get('cik', '')).zfill(10) != cik:
                self.refuse('identity_mismatch')
            recent = data['filings']['recent']
            fields = [recent[key] for key in ('form', 'accessionNumber', 'primaryDocument')]
            if any(type(field) is not list for field in fields) or len({len(field) for field in fields}) != 1:
                self.refuse_sec_response('sec_recent_array_shape')
            urls = set()
            excluded_documents = 0
            for form, accession, document in zip(*fields):
                if form not in {'10-K', '10-Q', '20-F', '40-F', '6-K', '8-K'}:
                    continue
                if type(accession) is not str or not re.fullmatch(r'[0-9]{10}-[0-9]{2}-[0-9]{6}', accession):
                    self.refuse_sec_response('sec_accession_syntax')
                if (type(document) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:htm|html|txt)', document)
                        or '..' in document):
                    # Metadata can remain useful without a fetchable document.
                    # Only exact validated filenames enter the network allowlist.
                    excluded_documents += 1
                    continue
                urls.add(f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{document}')
            with self.lock:
                attempt, _, _ = self.sec_attempt.get()
                event = next(item for item in self.events if item['attempt_id'] == attempt)
                event['sec_document_exclusions'] = excluded_documents
                previous = self.documents.setdefault(cik, frozenset(urls))
                if previous != urls:
                    self.refuse('configuration_drift')
        return media, content

    def close(self):
        try:
            super().close()
        finally:
            self.wire.close()


def main(argv=None):
    from validation.pilot_rehearsal import main as launch
    return launch(argv, mode='live_adapter_validation')


if __name__ == '__main__':
    raise SystemExit(main())
