"""Synthetic HTTP protocol/accounting integration, with no native-network path.

The existing owned transport refuses real network backends without its approved
exchange gate. This rehearsal installs only the exact internal fake backend.
It is NOT the final executor, URL authorization or ordinary-answer parity proof.
"""
from threading import Lock
import hashlib
import re
import sqlite3

from .ordinary_pilot_accounting import AccountingError
from .ordinary_pilot_contract import CASES
from .pilot_fixtures import SECRET_CANARIES
from .capture_budget import digest as request_digest

CIKS = dict(NPK='0000080172', GOOGL='0001652044', INGR='0001046257',
            NNBR='0000918541', AMZN='0001018724', MAN='0000871763')


class _FixtureOwner:
    def __init__(self, ticker, scenario, book, attempt, binding=None):
        self.book, self.attempt = book, attempt
        self.binding = binding or {}
        self.scenario = 'monitoring_financial_inputs' if scenario == 'reported-facts' else scenario
        self.monitoring = scenario == 'reported-facts'
        self.case = {'identity': {'ticker': ticker, 'cik': CIKS[ticker],
                                 'company_name': 'Invented rehearsal company'}}
        self.identities = [self.case['identity']]
        self.lock, self.used, self.connects = Lock(), set(), 0

    def once(self, scenarios):
        with self.lock:
            if scenarios == {'wire_connect_failure'}:
                self.book.claim_fixture_dispatch(self.attempt, **self.binding)
                self.connects += 1
            if self.scenario not in scenarios or self.scenario in self.used:
                return False
            self.used.add(self.scenario)
            return True


def rehearse_facts(book, case, *, scenario='happy'):
    return rehearse_sec(book, case, stage='evidence.sec_metrics', route='sec/facts', scenario=scenario)


def rehearse_sec(book, case, *, stage, route, scenario='happy', bound=False):
    """Fixed synthetic SEC routes only, never a caller-supplied URL."""
    if case not in CASES or scenario not in {
            'happy', 'reported-facts', 'wire_redirect', 'wire_read_failure', 'wire_connect_failure'}:
        raise AccountingError('unsupported rehearsal')
    from .pilot_live import OwnedHTTPTransport
    from ._pilot_wire_fixtures import SyntheticNetworkBackend
    url = _fixture_url(book, case, stage, route) if bound else None
    fingerprint = request_digest({'method':'GET', 'url':url, 'route':route, 'stage':stage}) if bound else None
    attempt = book.claim(case, stage, route, request_sha256=fingerprint)
    binding = {'case':case, 'route':route, 'request_sha256':fingerprint} if bound else None
    owner = _FixtureOwner(case.split(':')[0], scenario, book, attempt, binding)
    wire = None
    try:
        wire = OwnedHTTPTransport()
        wire._wire._pool._network_backend = SyntheticNetworkBackend(owner)
        url = url if bound else _fixture_url(book, case, stage, route)
        media, body = wire.exchange('GET', url)
        if media != ('text/html' if route == 'sec/document' else 'application/json'):
            raise AccountingError('fixture media mismatch')
        receipt = book.retain_fixture_body(attempt, body, forbidden_values=SECRET_CANARIES)
        _retain_fixture_receipt(book, attempt, url, media)
        receipt.update(route=route, stage=stage, url=url)
        wire.close()
        book.settle(attempt, succeeded=True)
        if book.summary()['halt']:
            raise AccountingError('rehearsal halted; response not publishable')
        result = {'receipt': receipt, 'simulated_connections': owner.connects,
                  'external_requests': 0, 'execution_authorized': False}
    except BaseException as primary:
        book.seal_local()
        cleanup_codes = []
        try:
            if wire is not None:
                wire.close()
        except BaseException:
            cleanup_codes.append('transport_close')
        try:
            book.settle(attempt, succeeded=False)
        except BaseException:
            cleanup_codes.append('settlement')
        recording_failed = False
        for code in cleanup_codes:
            try:
                book.record_cleanup_failure(code)
            except BaseException:
                recording_failed = True
        # Safe typed metadata survives even if storage is unavailable. The
        # original exception/code remains primary; never return a response.
        primary.offline_cleanup_codes = tuple(cleanup_codes)
        primary.offline_cleanup_recording_failed = recording_failed
        raise
    return result


def _fixture_url(book, case, stage, route):
    with sqlite3.connect(book.path) as db:
        return _fixture_url_from_db(db, case, stage, route)


def _fixture_url_from_db(db, case, stage, route):
    cik = CIKS[case.split(':')[0]]
    fixed = {'sec/directory': 'https://www.sec.gov/files/company_tickers.json',
             'sec/submissions': f'https://data.sec.gov/submissions/CIK{cik}.json',
             'sec/facts': f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'}
    if route in fixed:
        return fixed[route]
    if route != 'sec/document':
        raise AccountingError('unknown fixture route')
    from .pilot_live import json_object
    sources = db.execute("SELECT b.body,b.sha256 FROM bodies b JOIN attempts a "
        "ON a.id=b.attempt_id WHERE a.case_id=? AND a.stage=? "
        "AND a.route='sec/submissions' AND a.outcome='success'", (case, stage)).fetchall()
    if len(sources) != 1:
        raise AccountingError('one retained same-case same-stage submissions source required')
    body, digest = sources[0]
    if hashlib.sha256(body).hexdigest() != digest:
        raise AccountingError('retained submissions hash mismatch')
    data = json_object(body)
    if str(data.get('cik', '')).zfill(10) != cik:
        raise AccountingError('submissions fixture issuer mismatch')
    recent = data['filings']['recent']
    if recent['form'] != ['10-K']:
        raise AccountingError('unsupported fixture filing')
    accession, = recent['accessionNumber']
    document, = recent['primaryDocument']
    if (type(accession) is not str or not re.fullmatch(r'[0-9]{10}-[0-9]{2}-[0-9]{6}', accession)
            or type(document) is not str or not re.fullmatch(r'[A-Za-z0-9_-]+\.htm[l]?', document)):
        raise AccountingError('unsafe fixture filing metadata')
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}"


def _retain_fixture_receipt(book, attempt, url, media):
    """Record only the observed successful fake exchange while its attempt is active."""
    if book._locally_sealed:
        raise AccountingError('locally sealed')
    with sqlite3.connect(book.path, timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        halt, = db.execute('SELECT halt FROM state').fetchone()
        row = db.execute('SELECT case_id,stage,route,outcome FROM attempts WHERE id=?', (attempt,)).fetchone()
        if halt or not row or row[3] != 'pending':
            raise AccountingError('fixture receipt has no pending attempt')
        case, stage, route, _ = row
        reason = book._case_reason(db, case, book.clock())
        if reason:
            raise AccountingError(reason)
        if (not db.execute('SELECT 1 FROM fixture_dispatches WHERE attempt_id=?', (attempt,)).fetchone()
                or not db.execute('SELECT 1 FROM bodies WHERE attempt_id=?', (attempt,)).fetchone()
                or url != _fixture_url_from_db(db, case, stage, route)
                or media != ('text/html' if route == 'sec/document' else 'application/json')):
            raise AccountingError('fixture receipt scope mismatch')
        # OwnedHTTPTransport only returns successfully for a 200 response.
        db.execute('INSERT INTO fixture_receipts VALUES (?,?,?,200)', (attempt, url, media))
