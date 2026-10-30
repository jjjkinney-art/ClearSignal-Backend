"""Disabled benchmark live-adapter slice; only synthetic wire validation is exposed.

The owned transport is suitable for network-secret substitution: its bearer value
is an invented placeholder, never an environment lookup. This module neither
loads credentials nor grants execution/spending authority. The isolated launcher
always blocks sockets and supplies an internal fake network backend.
"""
from dataclasses import dataclass
import json
import re
import ssl
from threading import Lock
from types import MappingProxyType

import httpx

from validation.capture_budget import BudgetError
from validation.pilot_boundary import PilotBoundary
from validation.pilot_fixtures import SECRET_CANARIES, SYNTHETIC_CONTACT, SYNTHETIC_KEY

MAX_RESPONSE_BYTES = 16 * 1024 * 1024
# The one larger envelope. It is a constant, never a caller value: a reviewed
# annual-layout registry entry must state exactly this limit to receive it.
REVIEWED_DOCUMENT_MAX_BYTES = 30_000_000
# httpcore's fixed HTTP/1.1 socket read size (pinned httpcore 1.0.9). The body
# buffer never grows past the active envelope. Transient exchange memory is
# that buffer, one immutable copy of it, and httpcore/h11's own bounded read
# buffers; callers then hold the copy. Process RSS is not bounded by the cap.
READ_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class ReviewedDocumentEnvelope:
    """Submission-validated metadata for one registry-bound SEC document."""
    cik: str
    url: str
    form: str
    filed_at: str
    registry_id: str


def reviewed_document_envelope(cik, url, form, filed_at):
    """Exact reviewed annual-layout match, or None. Never a generic override.

    Every field is required: the zero-padded issuer CIK and the form and filing
    date come from the same validated submissions row that produced the URL.
    """
    if (any(type(value) is not str for value in (cik, url, form, filed_at))
            or not re.fullmatch(r'[0-9]{10}', cik)
            or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', filed_at)):
        return None
    from app.services.reviewed_annual_layouts import reviewed_annual_layout
    layout = reviewed_annual_layout(url, form, filed_at, cik=cik)
    if (layout is None or layout['url'] != url or layout['form'] != form
            or layout['filed_at'] != filed_at or layout['cik'] != str(int(cik))
            or layout['max_bytes'] != REVIEWED_DOCUMENT_MAX_BYTES):
        return None
    return ReviewedDocumentEnvelope(cik, url, form, filed_at, layout['registry_id'])


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


FILING_DOCUMENT_FORMS = frozenset({'10-K', '10-Q', '20-F', '40-F', '6-K', '8-K'})


class SubmissionRefusal(BudgetError):
    """A validated submissions response cannot admit filing documents."""
    def __init__(self, code):
        self.code = code
        super().__init__('SEC submissions response refused')


def submission_documents(data, cik):
    """Exact filing-document URLs admitted by one issuer's submissions response.

    ``cik`` is the 10-digit issuer CIK the response was already checked against.
    Returns ``(urls, filings, excluded)``: the URL set, each URL's
    ``(form, filingDate)`` or ``None`` when rows disagree or lack an aligned
    date, and the count of supported rows whose filename is not fetchable.
    Missing ``filings.recent`` keys propagate as KeyError, as they always have.
    """
    recent = data['filings']['recent']
    fields = [recent[key] for key in ('form', 'accessionNumber', 'primaryDocument')]
    if any(type(field) is not list for field in fields) or len({len(field) for field in fields}) != 1:
        raise SubmissionRefusal('sec_recent_array_shape')
    # Filing dates are optional here: without an aligned date a document
    # stays fetchable under the ordinary envelope, never the reviewed one.
    dates = recent.get('filingDate')
    dated = type(dates) is list and len(dates) == len(fields[0])
    urls = set()
    filings = {}
    excluded = 0
    for index, (form, accession, document) in enumerate(zip(*fields)):
        if form not in FILING_DOCUMENT_FORMS:
            continue
        if type(accession) is not str or not re.fullmatch(r'[0-9]{10}-[0-9]{2}-[0-9]{6}', accession):
            raise SubmissionRefusal('sec_accession_syntax')
        if (type(document) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:htm|html|txt)', document)
                or '..' in document):
            # Metadata can remain useful without a fetchable document.
            # Only exact validated filenames enter the network allowlist.
            excluded += 1
            continue
        url = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{document}'
        urls.add(url)
        filed_at = dates[index] if dated else None
        entry = (form, filed_at) if type(filed_at) is str else None
        # Rows disagreeing about one document make it ambiguous: no
        # reviewed envelope, whichever row happens to come first.
        filings[url] = entry if filings.get(url, entry) == entry else None
    return urls, filings, excluded


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
        # Envelopes minted by THIS transport from validated submissions only.
        self._reviewed = {}
        self._reviewed_lock = Lock()
        if gate is not None:
            from validation.pilot_approved import verify_network_configuration
            context = verify_network_configuration(execution, tls=True)
            gate.tls_context = context
            self._wire = httpx.HTTPTransport(retries=0, trust_env=False, proxy=execution['proxy'], verify=context)
        else:
            self._wire = httpx.HTTPTransport(retries=0, trust_env=False, proxy=None)

    def authorize_reviewed_document(self, cik, url, form, filed_at):
        """Mint the larger envelope for one exact registry document, or nothing.

        Called only by the boundary while it holds metadata from a validated
        submissions response for the current issuer. A second, different
        mint for the same document withdraws the authorization entirely.
        """
        envelope = reviewed_document_envelope(cik, url, form, filed_at)
        if envelope is None:
            return None
        with self._reviewed_lock:
            previous = self._reviewed.setdefault((cik, url), envelope)
            if previous != envelope:
                self._reviewed[(cik, url)] = None
                return None
            return previous

    def minted_document(self, cik, url):
        """The envelope this transport minted for (cik, url), or None."""
        with self._reviewed_lock:
            return self._reviewed.get((cik, url))

    def response_limit(self, method, url, reviewed):
        """Ordinary envelope, or the fixed reviewed one for its minted document."""
        if reviewed is None:
            return MAX_RESPONSE_BYTES
        if (type(reviewed) is not ReviewedDocumentEnvelope or method != 'GET' or reviewed.url != url
                or not url.startswith('https://www.sec.gov/Archives/edgar/data/')):
            raise BudgetError('unreviewed document envelope')
        minted = self.minted_document(reviewed.cik, url)
        # Identity, not equality: a caller-constructed copy of correct registry
        # values is not an authorization. Re-derive from the registry as well.
        if minted is not reviewed or reviewed_document_envelope(
                reviewed.cik, url, reviewed.form, reviewed.filed_at) != reviewed:
            raise BudgetError('unreviewed document envelope')
        if self.gate is not None and self.gate.require(url)['route'] != 'sec/document':
            raise BudgetError('unreviewed document envelope')
        return REVIEWED_DOCUMENT_MAX_BYTES

    def exchange(self, method, url, *, body=b'', timeout=10.0, reviewed=None):
        from validation._pilot_wire_fixtures import SyntheticNetworkBackend
        if self.gate is None and type(self._wire._pool._network_backend) is not SyntheticNetworkBackend:
            raise BudgetError('real provider execution remains disabled')
        if self.gate is not None:
            try:
                self.gate.validate_request(method, url, body)
            except BaseException:
                raise TransportFailure('request_gate') from None
        try:
            limit = self.response_limit(method, url, reviewed)
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
            # A declaration is advisory: it can refuse early, never admit. One
            # exact decimal value only; the observed stream is enforced below.
            declared = response.headers.get_list('content-length')
            if declared:
                if len(declared) != 1 or not re.fullmatch(r'[0-9]{1,15}', declared[0]):
                    raise TransportFailure('protocol_error')
                if int(declared[0]) > limit:
                    raise TransportFailure('response_size')
            content = bytearray()
            # Raw chunks are single httpcore socket reads (READ_CHUNK_BYTES each
            # at most). No re-chunking layer adds a buffer of its own.
            for chunk in response.iter_raw():
                if len(content) + len(chunk) > limit:
                    raise TransportFailure('response_size')
                content.extend(chunk)
            media = response.headers.get('content-type', '').split(';')[0]
            # One immutable copy for every validation and the caller; release
            # the growable buffer before validating it.
            payload = bytes(content)
            content.clear()
            if self.runtime is not None:
                from validation.pilot_policy import reject_runtime_values
                phase = 'response_json'
                parsed = json_object(payload) if media == 'application/json' else None
                phase = 'response_reflection'
                reject_runtime_values(parsed, (*SECRET_CANARIES, *self.runtime.values()), raw=payload)
            elif any(canary.encode() in payload for canary in SECRET_CANARIES):
                raise TransportFailure('response_reflection')
            result = media, payload
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
        if ledger.policy.get('purpose') not in {'disabled_live_adapter_validation', 'disabled_source_monitoring_validation', 'disabled_monitoring_freshness_validation'}:
            raise BudgetError('explicit disabled live-adapter policy required')
        super().__init__(ledger, scenario)
        self.wire = OwnedHTTPTransport()
        from validation._pilot_wire_fixtures import SyntheticNetworkBackend
        self.wire._wire._pool._network_backend = SyntheticNetworkBackend(self)
        self.documents = {}
        self.document_filings = {}

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

    def reviewed_document(self, url):
        """The envelope minted from this issuer's validated submissions, if any.

        Nothing here reads the caller's request: no header, ticker or limit.
        """
        with self.lock:
            cik = self.case['identity']['cik']
            filing = self.document_filings.get(cik, {}).get(url)
        if filing is None:
            return None
        return self.wire.minted_document(cik, url)

    def sec_content(self, route, url):
        reviewed = self.reviewed_document(url) if route == 'sec/document' else None
        media, content = self.wire.exchange('GET', url, reviewed=reviewed)
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
            try:
                urls, filings, excluded_documents = submission_documents(data, cik)
            except SubmissionRefusal as refusal:
                self.refuse_sec_response(refusal.code)
            with self.lock:
                attempt, _, _ = self.sec_attempt.get()
                event = next(item for item in self.events if item['attempt_id'] == attempt)
                event['sec_document_exclusions'] = excluded_documents
                previous = self.documents.setdefault(cik, frozenset(urls))
                if previous != urls:
                    self.refuse('configuration_drift')
                if self.document_filings.setdefault(cik, dict(filings)) != filings:
                    self.refuse('configuration_drift')
                for url, entry in filings.items():
                    if entry is not None:
                        # Mints only for an exact reviewed registry document.
                        self.wire.authorize_reviewed_document(cik, url, *entry)
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
