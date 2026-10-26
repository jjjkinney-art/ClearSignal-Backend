"""Synthetic HTTP protocol/accounting integration, with no native-network path.

The existing owned transport refuses real network backends without its approved
exchange gate. This rehearsal installs only the exact internal fake backend.
It is NOT the final executor, URL authorization or ordinary-answer parity proof.
"""
from threading import Lock

from .ordinary_pilot_accounting import AccountingError
from .ordinary_pilot_contract import CASES
from .pilot_fixtures import SECRET_CANARIES

CIKS = dict(NPK='0000080172', GOOGL='0001652044', INGR='0001046257',
            NNBR='0000918541', AMZN='0001018724', MAN='0000871763')


class _FixtureOwner:
    def __init__(self, ticker, scenario):
        self.scenario, self.monitoring = scenario, False
        self.case = {'identity': {'ticker': ticker, 'cik': CIKS[ticker],
                                 'company_name': 'Invented rehearsal company'}}
        self.identities = [self.case['identity']]
        self.lock, self.used, self.connects = Lock(), set(), 0

    def once(self, scenarios):
        with self.lock:
            if scenarios == {'wire_connect_failure'}:
                self.connects += 1
            if self.scenario not in scenarios or self.scenario in self.used:
                return False
            self.used.add(self.scenario)
            return True


def rehearse_facts(book, case, *, scenario='happy'):
    """One invented facts response over real HTTPX/httpcore parsing; no sockets."""
    if case not in CASES or scenario not in {
            'happy', 'wire_redirect', 'wire_read_failure', 'wire_connect_failure'}:
        raise AccountingError('unsupported rehearsal')
    from .pilot_live import OwnedHTTPTransport
    from ._pilot_wire_fixtures import SyntheticNetworkBackend
    owner = _FixtureOwner(case.split(':')[0], scenario)
    attempt = book.claim(case, 'evidence.sec_metrics', 'sec/facts')
    wire = None
    try:
        wire = OwnedHTTPTransport()
        wire._wire._pool._network_backend = SyntheticNetworkBackend(owner)
        url = 'https://data.sec.gov/api/xbrl/companyfacts/CIK' + owner.case['identity']['cik'] + '.json'
        media, body = wire.exchange('GET', url)
        if media != 'application/json':
            raise AccountingError('fixture media mismatch')
        receipt = book.retain_fixture_body(attempt, body, forbidden_values=SECRET_CANARIES)
        wire.close()
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
    book.settle(attempt, succeeded=True)
    if book.summary()['halt']:
        raise AccountingError('rehearsal halted; response not publishable')
    return {'receipt': receipt, 'simulated_connections': owner.connects,
            'external_requests': 0, 'execution_authorized': False}
