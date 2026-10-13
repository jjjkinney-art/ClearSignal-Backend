"""Reviewed SEC document envelope: exact registry authorization, fixed limits.

Every exchange runs through HTTPX/httpcore/h11 over an invented in-memory
socket. No DNS, socket, credential or real SEC response is used.
"""
import json
from types import SimpleNamespace

import httpcore
import httpx
import pytest
import requests

from tests.test_pilot_live import boundary  # noqa: F401  (fixture)
from validation.capture_budget import BudgetError
from validation.pilot_fixtures import SECRET_CANARIES, SYNTHETIC_CONTACT
from validation.pilot_live import (
    MAX_RESPONSE_BYTES, READ_CHUNK_BYTES, REVIEWED_DOCUMENT_MAX_BYTES,
    ReviewedDocumentEnvelope, TransportFailure, reviewed_document_envelope,
)
from validation.pilot_policy import PILOT_SETTINGS

CIK = '0000937966'
URL = 'https://www.sec.gov/Archives/edgar/data/937966/000162828026011378/asml-20251231.htm'
ROW = {'form': '20-F', 'accessionNumber': '0001628280-26-011378',
       'primaryDocument': 'asml-20251231.htm', 'filingDate': '2026-02-25'}
SUBMISSIONS = f'https://data.sec.gov/submissions/CIK{CIK}.json'
ORDINARY = MAX_RESPONSE_BYTES


def head(media='text/html', length=None, extra=b''):
    framing = b'' if length is None else b'Content-Length: ' + str(length).encode() + b'\r\n'
    return (b'HTTP/1.1 200 OK\r\nContent-Type: ' + media.encode() + b'\r\n' + framing
            + extra + b'Connection: close\r\n\r\n')


def chunked(body, size=READ_CHUNK_BYTES):
    parts = [b'%x\r\n' % len(body[i:i + size]) + body[i:i + size] + b'\r\n'
             for i in range(0, len(body), size)]
    return b''.join(parts) + b'0\r\n\r\n'


class WireStream:
    """One invented HTTP/1.1 response, served lazily from a memoryview."""
    def __init__(self, responder, log):
        self.responder, self.log = responder, log
        self.request = bytearray()
        self.data = self.view = None
        self.pos = self.head_len = 0
        self.reads, self.closed = [], 0
        log.append(self)

    def write(self, buffer, timeout=None):
        self.request.extend(buffer)

    def read(self, max_bytes, timeout=None):
        if self.closed:
            raise AssertionError('read after close')
        self.reads.append(max_bytes)
        if self.view is None:
            target = bytes(self.request).split(b' ', 2)[1].decode()
            response_head, body, self.fault = self.responder(target)
            self.head_len = len(response_head)
            self.data = response_head + body
            self.view = memoryview(self.data)
        if self.fault is not None and self.pos - self.head_len >= self.fault[0]:
            raise self.fault[1]
        chunk = bytes(self.view[self.pos:self.pos + max_bytes])
        self.pos += len(chunk)
        return chunk

    def start_tls(self, *args, **kwargs):
        return self

    def get_extra_info(self, info):
        return None

    def close(self):
        self.closed += 1
        if getattr(self, 'close_error', None) is not None:
            raise self.close_error

    @property
    def body_served(self):
        return max(0, self.pos - self.head_len)


def submissions(rows, cik=CIK, *, dates=True):
    """dates: True per row, False to omit, or an explicit raw filingDate value."""
    recent = {key: [row[key] for row in rows] for key in ('form', 'accessionNumber', 'primaryDocument')}
    if dates is True:
        recent['filingDate'] = [row['filingDate'] for row in rows]
    elif dates is not False:
        recent['filingDate'] = dates
    recent.update(reportDate=['2025-12-31'] * len(rows), items=[''] * len(rows))
    return json.dumps({'cik': cik, 'name': 'Invented fixture issuer', 'filings': {'recent': recent}}).encode()


def install(monkeypatch, boundary, *, rows=(ROW,), document=None, dates=True, log=None):
    """Route the submissions and document targets to invented responses."""
    log = [] if log is None else log

    def respond(target):
        if '/submissions/' in target:
            body = submissions(list(rows), boundary.case['identity']['cik'], dates=dates)
            return head('application/json', len(body)), body, None
        return document()

    monkeypatch.setattr(boundary.wire._wire._pool._network_backend, 'connect_tcp',
                        lambda *a, **kw: WireStream(respond, log))
    return log


def authorize(boundary, monkeypatch, **kwargs):
    log = install(monkeypatch, boundary, **kwargs)
    cik = boundary.case['identity']['cik']
    boundary.sec_exchange('GET', f'https://data.sec.gov/submissions/CIK{cik}.json', None)
    boundary.stage.set('evidence.thesis_disclosures')
    return log


def html(size, *, length=True, extra=b''):
    body = b'a' * size
    return lambda: (head('text/html', size if length else None, extra), body, None)


def gets(log):
    return sum(bytes(stream.request).startswith(b'GET ') for stream in log)


# --- Authorization ---------------------------------------------------------

def test_exact_registry_submission_mints_the_reviewed_envelope(boundary, monkeypatch):
    authorize(boundary, monkeypatch, document=html(1))
    envelope = boundary.reviewed_document(URL)
    assert envelope == ReviewedDocumentEnvelope(CIK, URL, '20-F', '2026-02-25', 'asml-2025-integrated-risk-v1')
    assert boundary.wire.response_limit('GET', URL, envelope) == REVIEWED_DOCUMENT_MAX_BYTES == 30_000_000


@pytest.mark.parametrize('field,value', [
    ('form', '10-K'), ('form', '40-F'), ('filingDate', '2026-02-24'),
    ('filingDate', '2026-02-25T00:00:00'), ('filingDate', None),
    ('primaryDocument', 'asml-20251231x.htm'), ('accessionNumber', '0001628280-26-011379')])
def test_any_other_submission_metadata_keeps_the_ordinary_envelope(boundary, monkeypatch, field, value):
    log = authorize(boundary, monkeypatch, rows=({**ROW, field: value},), document=html(ORDINARY + 1))
    (url,) = boundary.sec_document_urls()
    assert boundary.reviewed_document(url) is None
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', url, None)
    assert boundary.ledger.summary()['first_transport_failure']['code'] == 'response_size'
    assert gets(log) == 2 and log[-1].closed


def test_missing_filing_dates_never_authorize(boundary, monkeypatch):
    authorize(boundary, monkeypatch, rows=(ROW,), dates=False, document=html(1))
    assert boundary.sec_document_urls() == {URL}
    assert boundary.reviewed_document(URL) is None


@pytest.mark.parametrize('dates', [['2026-02-25', '2026-02-25'], [], '2026-02-25', {'0': '2026-02-25'}])
def test_filing_dates_must_be_an_aligned_array(boundary, monkeypatch, dates):
    authorize(boundary, monkeypatch, rows=(ROW,), dates=dates, document=html(1))
    assert boundary.sec_document_urls() == {URL}
    assert boundary.reviewed_document(URL) is None


@pytest.mark.parametrize('registry_row_last', [False, True])
def test_conflicting_rows_for_one_document_are_ambiguous(boundary, monkeypatch, registry_row_last):
    rows = (ROW, {**ROW, 'filingDate': '2026-02-26'})
    log = authorize(boundary, monkeypatch, rows=rows[::-1] if registry_row_last else rows,
                    document=html(ORDINARY + 1))
    assert boundary.reviewed_document(URL) is None
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', URL, None)
    assert boundary.ledger.summary()['first_transport_failure']['code'] == 'response_size'
    assert gets(log) == 2


def test_another_issuer_cannot_reach_the_envelope(boundary, monkeypatch):
    boundary.ledger.finish_case(boundary.case_run)
    boundary.begin(boundary.cases[2])  # ACHC core_thesis, a different CIK
    boundary.stage.set('evidence.sec')
    authorize(boundary, monkeypatch, document=html(1))
    (url,) = boundary.sec_document_urls()
    assert url != URL and url.endswith('/000162828026011378/asml-20251231.htm')
    assert boundary.reviewed_document(url) is None
    # Even the registry URL with a foreign or malformed CIK is refused outright.
    for cik in ('0001520697', '937966', '00000937966', 937966, None):
        assert reviewed_document_envelope(cik, URL, '20-F', '2026-02-25') is None


@pytest.mark.parametrize('args', [
    (CIK, URL, '20-F', None), (CIK, URL, None, '2026-02-25'), (CIK, None, '20-F', '2026-02-25'),
    (CIK, URL + '?x=1', '20-F', '2026-02-25'), (CIK, URL.upper(), '20-F', '2026-02-25'),
    (CIK, URL, '20-f', '2026-02-25'), (CIK, URL, '20-F', '2026-2-25')])
def test_registry_lookup_requires_every_exact_field(args):
    assert reviewed_document_envelope(*args) is None


def test_ticker_or_url_alone_cannot_authorize(boundary, monkeypatch):
    # Without the submissions response the URL is not even routable.
    log = install(monkeypatch, boundary, document=html(1))
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', URL, None)
    assert gets(log) == 0
    assert boundary.reviewed_document(URL) is None


def test_transport_mint_without_validated_submissions_is_unreachable(boundary):
    # Registry-valid metadata handed straight to the transport is not a
    # submissions authorization: the boundary never selects it.
    assert boundary.wire.authorize_reviewed_document(CIK, URL, '20-F', '2026-02-25') is not None
    assert boundary.reviewed_document(URL) is None
    assert URL not in boundary.sec_document_urls()


def test_registry_edit_cannot_widen_the_transport(boundary, monkeypatch):
    from app.services import reviewed_annual_layouts as registry
    widened = ({**registry.REVIEWED_ANNUAL_LAYOUTS[0], 'max_bytes': 31_000_000},)
    monkeypatch.setattr(registry, 'REVIEWED_ANNUAL_LAYOUTS', widened)
    authorize(boundary, monkeypatch, document=html(1))
    assert boundary.reviewed_document(URL) is None


# --- Forged caller metadata -------------------------------------------------

def test_caller_constructed_envelope_is_refused_before_dispatch(boundary, monkeypatch):
    log = authorize(boundary, monkeypatch, document=html(ORDINARY + 1))
    forged = ReviewedDocumentEnvelope(CIK, URL, '20-F', '2026-02-25', 'asml-2025-integrated-risk-v1')
    assert forged == boundary.reviewed_document(URL) and forged is not boundary.reviewed_document(URL)
    for value in (forged, {'max_bytes': 30_000_000}, SimpleNamespace(**vars(forged)), 30_000_000):
        with pytest.raises(TransportFailure) as caught:
            boundary.wire.exchange('GET', URL, reviewed=value)
        assert caught.value.code == 'request_gate'
    assert gets(log) == 1  # the submissions request only


def test_minted_envelope_is_bound_to_its_own_url_and_method(boundary, monkeypatch):
    log = authorize(boundary, monkeypatch, document=html(1))
    minted = boundary.reviewed_document(URL)
    for method, url in (('GET', SUBMISSIONS), ('GET', URL.replace('asml-', 'other-')),
                        ('POST', URL), ('HEAD', URL),
                        ('POST', 'https://api.openai.com/v1/chat/completions')):
        with pytest.raises(TransportFailure) as caught:
            boundary.wire.exchange(method, url, body=b'', reviewed=minted)
        assert caught.value.code == 'request_gate'
    assert gets(log) == 1


def test_conflicting_mint_withdraws_the_authorization(boundary, monkeypatch):
    authorize(boundary, monkeypatch, document=html(1))
    minted = boundary.reviewed_document(URL)
    # A later, different validated claim about the same document is ambiguous.
    from app.services import reviewed_annual_layouts as registry
    other = ({**registry.REVIEWED_ANNUAL_LAYOUTS[0], 'filed_at': '2026-02-26'},)
    monkeypatch.setattr(registry, 'REVIEWED_ANNUAL_LAYOUTS', other)
    assert boundary.wire.authorize_reviewed_document(CIK, URL, '20-F', '2026-02-26') is None
    monkeypatch.undo()
    assert boundary.wire.authorize_reviewed_document(CIK, URL, '20-F', '2026-02-25') is None
    with pytest.raises(BudgetError, match='unreviewed document envelope'):
        boundary.wire.response_limit('GET', URL, minted)


def test_exchange_accepts_no_caller_limit(boundary):
    with pytest.raises(TypeError):
        boundary.wire.exchange('GET', URL, max_bytes=REVIEWED_DOCUMENT_MAX_BYTES)


def test_submission_metadata_drift_halts(boundary, monkeypatch):
    rows = [ROW]
    authorize(boundary, monkeypatch, rows=rows, document=html(1))
    boundary.stage.set('evidence.sec')
    rows[0] = {**ROW, 'filingDate': '2026-02-26'}
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', SUBMISSIONS, None)
    assert boundary.ledger.summary()['halted'] == 'configuration_drift'


# --- Byte boundaries --------------------------------------------------------

@pytest.mark.parametrize('framing', ['length', 'close', 'chunked'])
def test_reviewed_document_accepts_exactly_thirty_million_bytes(boundary, monkeypatch, framing):
    body = b'a' * REVIEWED_DOCUMENT_MAX_BYTES
    document = {'length': lambda: (head('text/html', len(body)), body, None),
                'close': lambda: (head('text/html'), body, None),
                'chunked': lambda: (head('text/html', extra=b'Transfer-Encoding: chunked\r\n'),
                                    chunked(body), None)}[framing]
    log = authorize(boundary, monkeypatch, document=document)
    media, content = boundary.sec_exchange('GET', URL, None)
    assert (media, len(content)) == ('text/html', REVIEWED_DOCUMENT_MAX_BYTES)
    summary = boundary.ledger.summary()
    assert summary['halted'] is None and summary['unresolved_attempts'] == 0
    assert gets(log) == 2 and log[-1].closed == 1
    assert max(log[-1].reads) <= READ_CHUNK_BYTES


@pytest.mark.parametrize('framing', ['length', 'close', 'chunked'])
def test_one_byte_over_the_reviewed_envelope_fails_closed(boundary, monkeypatch, framing):
    size = REVIEWED_DOCUMENT_MAX_BYTES + 1
    body = b'a' * size
    document = {'length': lambda: (head('text/html', size), body, None),
                'close': lambda: (head('text/html'), body, None),
                'chunked': lambda: (head('text/html', extra=b'Transfer-Encoding: chunked\r\n'),
                                    chunked(body), None)}[framing]
    log = authorize(boundary, monkeypatch, document=document)
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', URL, None)
    summary = boundary.ledger.summary()
    assert summary['first_transport_failure'] == {
        'attempt_id': boundary.events[-1]['attempt_id'], 'route': 'sec/document',
        'stage': 'evidence.thesis_disclosures', 'code': 'response_size'}
    assert summary['halted'] == 'post_claim_failure' and summary['unresolved_attempts'] == 1
    stream = log[-1]
    assert stream.closed == 1 and gets(log) == 2
    if framing == 'length':
        # The declaration refuses before the body is read.
        assert stream.body_served < 2 * READ_CHUNK_BYTES
    else:
        # Streamed overflow stops within one bounded socket read past the
        # wire bytes that carry exactly the envelope (plus chunk framing).
        carried = (REVIEWED_DOCUMENT_MAX_BYTES if framing == 'close'
                   else len(chunked(b'a' * REVIEWED_DOCUMENT_MAX_BYTES)))
        assert stream.body_served <= carried + READ_CHUNK_BYTES
    assert max(stream.reads) <= READ_CHUNK_BYTES
    before = gets(log)
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', URL, None)
    assert gets(log) == before  # durable halt: no second dispatch


@pytest.mark.parametrize('size,accepted', [(ORDINARY, True), (ORDINARY + 1, False)])
def test_ordinary_documents_keep_the_sixteen_mebibyte_envelope(boundary, monkeypatch, size, accepted):
    log = authorize(boundary, monkeypatch, rows=({**ROW, 'primaryDocument': 'report.htm'},),
                    document=html(size, length=False))
    (url,) = boundary.sec_document_urls()
    if accepted:
        assert len(boundary.sec_exchange('GET', url, None)[1]) == ORDINARY
    else:
        with pytest.raises(BudgetError):
            boundary.sec_exchange('GET', url, None)
        assert boundary.ledger.summary()['first_transport_failure']['code'] == 'response_size'
    assert gets(log) == 2 and log[-1].closed == 1


@pytest.mark.parametrize('route', ['sec/directory', 'sec/submissions'])
def test_json_routes_keep_the_ordinary_envelope(boundary, monkeypatch, route):
    url = SUBMISSIONS if route == 'sec/submissions' else 'https://www.sec.gov/files/company_tickers.json'
    padding = b'{"pad":"' + b'x' * (ORDINARY - 9) + b'"}'
    log = []
    monkeypatch.setattr(boundary.wire._wire._pool._network_backend, 'connect_tcp',
                        lambda *a, **kw: WireStream(lambda t: (head('application/json'), padding, None), log))
    assert len(padding) == ORDINARY + 1
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', url, None)
    assert boundary.ledger.summary()['first_transport_failure']['code'] == 'response_size'
    assert gets(log) == 1 and log[0].closed == 1


@pytest.mark.parametrize('size,accepted', [(ORDINARY, True), (ORDINARY + 1, False)])
def test_model_route_keeps_the_ordinary_envelope(boundary, monkeypatch, size, accepted):
    body = b'{"p":"' + b'x' * (size - 8) + b'"}'
    assert len(body) == size
    log = []
    monkeypatch.setattr(boundary.wire._wire._pool._network_backend, 'connect_tcp',
                        lambda *a, **kw: WireStream(lambda t: (head('application/json'), body, None), log))
    url = 'https://api.openai.com/v1/chat/completions'
    if accepted:
        assert len(boundary.wire.exchange('POST', url, body=b'{}', timeout=15.0)[1]) == size
    else:
        with pytest.raises(TransportFailure) as caught:
            boundary.wire.exchange('POST', url, body=b'{}', timeout=15.0)
        assert caught.value.code == 'response_size'
    assert log[0].closed == 1


# --- Content-Length ---------------------------------------------------------

@pytest.mark.parametrize('declared,code', [
    (b'Content-Length: abc\r\n', 'protocol_error'), (b'Content-Length: -1\r\n', 'protocol_error'),
    (b'Content-Length: +5\r\n', 'protocol_error'), (b'Content-Length: 1e3\r\n', 'protocol_error'),
    (b'Content-Length: 5\r\nContent-Length: 6\r\n', 'protocol_error'),
    (b'Content-Length: 30000001\r\n', 'response_size'),
    (b'Content-Length: 999999999999999\r\n', 'response_size'),
    # Beyond 15 digits is refused as malformed, never parsed unboundedly.
    (b'Content-Length: 9999999999999999\r\n', 'protocol_error'),
    (b'Transfer-Encoding: chunked\r\nContent-Length: 30000001\r\n', 'response_size')])
def test_invalid_or_over_limit_declarations_fail_before_the_body(boundary, monkeypatch, declared, code):
    body = b'a' * 5
    log = authorize(boundary, monkeypatch, document=lambda: (
        b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n' + declared + b'Connection: close\r\n\r\n', body, None))
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', URL, None)
    assert boundary.ledger.summary()['first_transport_failure']['code'] == code
    assert gets(log) == 2 and log[-1].closed == 1


def test_identical_duplicate_declarations_are_one_value(boundary, monkeypatch):
    log = authorize(boundary, monkeypatch, document=lambda: (
        b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 5\r\nContent-Length: 5\r\n'
        b'Connection: close\r\n\r\n', b'abcde', None))
    assert boundary.sec_exchange('GET', URL, None)[1] == b'abcde'
    assert gets(log) == 2


@pytest.mark.parametrize('values', [['5', '5'], ['5', '6'], [' 5'], ['5 '], ['0x5'], ['']])
def test_transport_rechecks_declarations_it_receives(boundary, monkeypatch, values):
    # Defence in depth beneath h11: any non-single, non-decimal value refuses.
    response = httpx.Response(200, headers=[('Content-Type', 'text/html'),
                                           *(('Content-Length', v) for v in values)],
                              stream=httpx.ByteStream(b'abcde'))
    monkeypatch.setattr(boundary.wire._wire, 'handle_request', lambda request: response)
    with pytest.raises(TransportFailure) as caught:
        boundary.wire.exchange('GET', 'https://www.sec.gov/files/company_tickers.json')
    assert caught.value.code == 'protocol_error'


def test_declared_envelope_with_short_body_is_a_protocol_error(boundary, monkeypatch):
    log = authorize(boundary, monkeypatch, document=lambda: (head('text/html', 30_000_000), b'a', None))
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', URL, None)
    assert boundary.ledger.summary()['first_transport_failure']['code'] == 'protocol_error'
    assert gets(log) == 2 and log[-1].closed == 1


def test_declaration_cannot_admit_more_than_the_stream_limit(boundary, monkeypatch):
    # A small declaration with chunked framing still meets the observed check.
    size = REVIEWED_DOCUMENT_MAX_BYTES + 1
    log = authorize(boundary, monkeypatch, document=lambda: (
        head('text/html', 5, b'Transfer-Encoding: chunked\r\n'), chunked(b'a' * size), None))
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', URL, None)
    assert boundary.ledger.summary()['first_transport_failure']['code'] == 'response_size'
    assert log[-1].closed == 1


def test_framing_shorter_than_the_stream_is_not_extended(boundary, monkeypatch):
    # The message body is what the framing states; trailing bytes are never
    # appended. Downstream canonical-hash validation judges the document.
    authorize(boundary, monkeypatch, document=lambda: (head('text/html', 3), b'abcdef', None))
    assert boundary.sec_exchange('GET', URL, None)[1] == b'abc'


# --- Reads, close and first-cause preservation ------------------------------

def test_socket_reads_are_bounded_by_the_pinned_httpcore_size():
    from httpcore._sync.http11 import HTTP11Connection
    assert HTTP11Connection.READ_NUM_BYTES == READ_CHUNK_BYTES == 64 * 1024


def test_overflow_cause_survives_a_failing_close(boundary, monkeypatch):
    size = REVIEWED_DOCUMENT_MAX_BYTES + 1
    body = b'a' * size
    log = authorize(boundary, monkeypatch, document=lambda: (head('text/html'), body, None))
    handle, cleanups = boundary.wire._wire.handle_request, []

    def with_failing_cleanup(request):
        response = handle(request)
        close = response.close

        def fail():
            close()
            cleanups.append(log[-1].closed)
            raise RuntimeError(SECRET_CANARIES[0])
        response.close = fail  # the transport's own explicit cleanup call
        return response
    monkeypatch.setattr(boundary.wire._wire, 'handle_request', with_failing_cleanup)
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', URL, None)
    summary = boundary.ledger.summary()
    assert cleanups == [1]  # cleanup ran, closed the socket, and then failed
    assert summary['first_transport_failure']['code'] == 'response_size'
    assert summary['halted'] == 'post_claim_failure'
    assert SECRET_CANARIES[0] not in json.dumps(summary)
    assert SECRET_CANARIES[0].encode() not in boundary.ledger.path.read_bytes()


def test_read_timeout_inside_a_reviewed_download_fails_closed(boundary, monkeypatch):
    size = REVIEWED_DOCUMENT_MAX_BYTES
    timeout = httpcore.ReadTimeout('invented inactivity timeout')
    captured = []
    log = authorize(boundary, monkeypatch, document=lambda: (head('text/html', size), b'a' * size,
                                                             (ORDINARY + 1, timeout)))
    handle = boundary.wire._wire.handle_request

    def record(request):
        captured.append(request.extensions['timeout'])
        return handle(request)
    monkeypatch.setattr(boundary.wire._wire, 'handle_request', record)
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', URL, None)
    assert boundary.ledger.summary()['first_transport_failure']['code'] == 'read_timeout'
    # Operation/inactivity timeouts are unchanged; there is no download deadline here.
    assert captured == [dict.fromkeys(('connect', 'read', 'write', 'pool'), 10.0)]
    assert gets(log) == 2 and log[-1].closed == 1


# --- Complete-body validation is preserved ----------------------------------

def test_reflection_is_checked_across_the_complete_reviewed_body(boundary, monkeypatch):
    body = b'a' * (ORDINARY + 1) + SECRET_CANARIES[-1].encode()
    log = authorize(boundary, monkeypatch, document=lambda: (head('text/html', len(body)), body, None))
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', URL, None)
    assert boundary.ledger.summary()['first_transport_failure']['code'] == 'response_reflection'
    assert gets(log) == 2


def test_media_type_is_still_required_for_a_reviewed_body(boundary, monkeypatch):
    body = b'a' * (ORDINARY + 1)
    authorize(boundary, monkeypatch, document=lambda: (head('application/pdf', len(body)), body, None))
    with pytest.raises(BudgetError):
        boundary.sec_exchange('GET', URL, None)
    assert boundary.ledger.summary()['first_sec_refusal']['code'] == 'sec_media_type'


def test_wrong_canonical_hash_is_rejected_downstream_despite_admission(boundary, monkeypatch, tmp_path):
    import socket
    from app.services.public_document_ingestion import PublicDocumentError, fetch_public_document
    size = ORDINARY + 1  # above the ordinary envelope: admitted only as reviewed
    log = authorize(boundary, monkeypatch, document=html(size, length=False))
    # The real bridge: requests -> synthetic Response -> application parsing.
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'isolated-home').mkdir()
    monkeypatch.setenv('HOME', str(tmp_path.resolve() / 'isolated-home'))
    monkeypatch.setenv('CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED', 'false')
    boundary.settings = SimpleNamespace(**PILOT_SETTINGS, sec_user_agent=SYNTHETIC_CONTACT,
                                        fmp_api_key='', fred_api_key='')
    monkeypatch.setattr(requests.sessions.Session, 'send',
                        lambda session, request, **kwargs: boundary.sec_requests(request))
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    with pytest.raises(PublicDocumentError, match='reviewed annual document hash mismatch'):
        fetch_public_document(URL, user_agent=SYNTHETIC_CONTACT, publisher='SEC EDGAR',
                              published_at='2026-02-25', document_type='20-F',
                              source_type='regulatory_filing', source_tier='primary',
                              sec_periodic_limits=True, preserve_sec_business=True, extract_tables=False)
    summary = boundary.ledger.summary()
    # SEC settlement happened; it does not make the document usable evidence.
    assert summary['halted'] is None and summary['unresolved_attempts'] == 0
    assert gets(log) == 2 and log[-1].body_served == size
    assert boundary.sec_authorization_header_absent and boundary.sec_contact_applied


# --- Approved boundary: the same decision through the claimed exchange gate --

@pytest.fixture
def approved(tmp_path, monkeypatch):
    from tests.test_pilot_approved import BINDING, CA_PATH, CONFIG, RUNTIME, approval
    from validation._pilot_wire_fixtures import SyntheticProxyBackend, SyntheticProxyStream
    from validation.capture_budget import AttemptLedger
    from validation.pilot_approved import ApprovedBoundary
    from validation.pilot_policy import AUDITED_DEPENDENCIES, policy_for
    monkeypatch.setenv('OPENAI_API_KEY', RUNTIME['bearer_placeholder'])
    monkeypatch.setenv('SEC_USER_AGENT', RUNTIME['sec_contact'])
    for name in CONFIG['proxy_selectors']:
        monkeypatch.setenv(name, CONFIG['proxy'])
    for name in CONFIG['ca_selectors']:
        monkeypatch.setenv(name, str(CA_PATH))
    output = tmp_path.resolve() / 'approved'
    policy = policy_for(BINDING, dict(AUDITED_DEPENDENCIES), mode='approved',
                        approval=approval(BINDING, output), execution=CONFIG)
    owner = ApprovedBoundary(AttemptLedger(tmp_path / 'ledger.sqlite', policy, create=True))
    owner.wire_log, owner.document = [], html(1)

    def respond(target):
        if '/submissions/' in target:
            body = submissions([owner.row], owner.case['identity']['cik'])
            return head('application/json', len(body)), body, None
        return owner.document()

    class Tunnel(SyntheticProxyStream):
        def __init__(self, inner):
            super().__init__(inner)
            self.tunnel = WireStream(respond, owner.wire_log)

    class Backend(SyntheticProxyBackend):
        def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            assert (host, port) == ('proxy', 8080)
            return Tunnel(self.owner)

    owner.row = ROW
    owner.wire._wire._pool._network_backend.backend = Backend(owner)
    owner.begin(owner.cases[0])
    owner.stage.set('evidence.sec')
    yield owner
    owner.close()


def approved_authorize(owner):
    owner.sec_exchange('GET', SUBMISSIONS, None)
    owner.stage.set('evidence.thesis_disclosures')


@pytest.mark.parametrize('document,accepted', [('asml-20251231.htm', True), ('report.htm', False)])
def test_approved_gate_applies_the_envelope_only_to_the_registry_document(approved, document, accepted):
    from tests.test_pilot_approved import RUNTIME
    approved.row = {**ROW, 'primaryDocument': document}
    approved.document = html(ORDINARY + 1)
    approved_authorize(approved)
    (url,) = approved.sec_document_urls()
    if accepted:
        assert len(approved.sec_exchange('GET', url, None)[1]) == ORDINARY + 1
        assert approved.ledger.summary()['unresolved_attempts'] == 0
    else:
        with pytest.raises(BudgetError):
            approved.sec_exchange('GET', url, None)
        assert approved.ledger.summary()['first_transport_failure']['code'] == 'response_size'
    assert approved.gate.dispatched == 2 and gets(approved.wire_log) == 2
    sent = b''.join(bytes(stream.request) for stream in approved.wire_log)
    assert b'Authorization:' not in sent and RUNTIME['bearer_placeholder'].encode() not in sent
    assert sent.count(RUNTIME['sec_contact'].encode()) == 2
    assert approved.wire_log[-1].closed == 1


def test_approved_gate_scope_must_be_the_document_route(approved):
    from validation.capture_budget import digest
    approved_authorize(approved)
    minted = approved.reviewed_document(URL)
    assert minted is not None
    # A claimed exchange for this URL under any other route never gets the envelope.
    fingerprint = digest({'method': 'GET', 'url': URL, 'route': 'sec/directory',
                          'stage': approved.stage.get()})
    approved.claim('sec/directory', fingerprint, 0, 0)
    with pytest.raises(TransportFailure) as caught:
        with approved.dispatch(URL, fingerprint):
            approved.wire.exchange('GET', URL, reviewed=minted)
    assert caught.value.code == 'request_gate'
    assert approved.gate.dispatched == 1 and gets(approved.wire_log) == 1


# --- The actual isolated pilot worker ----------------------------------------

def asml_core_routes(result):
    return [claim['route'] for claim in result['claims'] if claim['case_id'] == 'ASML:core_thesis']


def test_isolated_pipeline_settles_the_reviewed_document(tmp_path):
    from validation.pilot_rehearsal import run_rehearsal
    output = tmp_path / 'admitted'
    # 16,777,217 invented bytes: one byte above the ordinary envelope.
    result = run_rehearsal(output, scenario='reviewed_document_admitted', mode='live_adapter_validation')
    assert result['status'] == 'complete' and len(result['completed_cases']) == 6
    ledger = result['ledger']
    assert ledger['halted'] is None and ledger['unresolved_attempts'] == 0
    assert ledger['first_transport_failure'] is None
    routes = asml_core_routes(result)
    assert routes.count('sec/document') == 1
    assert not any(route.startswith('model/') for route in routes)  # source-only core route
    assert result['network_attempts'] == result['external_dispatches'] == 0
    for path in output.rglob('*'):
        if path.is_file():
            assert not any(canary.encode() in path.read_bytes() for canary in SECRET_CANARIES)


def test_isolated_pipeline_reviewed_overflow_reproduces_the_halt_shape(tmp_path):
    from validation.pilot_rehearsal import run_rehearsal
    output = tmp_path / 'oversize'
    result = run_rehearsal(output, scenario='reviewed_document_oversize', mode='live_adapter_validation')
    ledger = result['ledger']
    assert result['status'] == 'halted' and result['completed_cases'] == []
    assert ledger['halted'] == 'post_claim_failure'
    first = ledger['first_transport_failure']
    assert (first['route'], first['stage'], first['code']) == (
        'sec/document', 'evidence.thesis_disclosures', 'response_size')
    # Same shape as the demonstrated halt: five settled SEC requests, one
    # unresolved document claim, no model call.
    routes = asml_core_routes(result)
    assert sorted(routes) == sorted(['sec/directory', 'sec/facts', 'sec/submissions',
                                     'sec/submissions', 'sec/submissions', 'sec/document'])
    assert ledger['attempts'] == 6 and ledger['unresolved_attempts'] == 1
    assert first['attempt_id'] == next(c['attempt_id'] for c in result['claims'] if c['route'] == 'sec/document')
    assert json.loads((output / 'artifact.json').read_text()) == result
    for path in output.rglob('*'):
        if path.is_file():
            assert not any(canary.encode() in path.read_bytes() for canary in SECRET_CANARIES)
