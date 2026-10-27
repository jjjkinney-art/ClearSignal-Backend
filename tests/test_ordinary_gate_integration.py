"""Synthetic integration of the existing gate with the twelve-case ledger.

The adapter and proxy here are test doubles, not live execution authority.
"""
import sqlite3
import ssl

import pytest

from validation._pilot_wire_fixtures import SyntheticProxyBackend
from validation.capture_budget import BudgetError, digest
from validation.ordinary_case_lifecycle import OfflineCaseLifecycle
from validation.ordinary_pilot_accounting import OfflineAccounting
from validation.ordinary_pilot_contract import CASES
from validation.ordinary_wire_rehearsal import CIKS
from validation.pilot_approved import ExchangeGate, ScopedBackend
from validation.pilot_live import OwnedHTTPTransport, TransportFailure
from validation.ordinary_transport import OrdinaryHTTPTransport


class FixtureOwner:
    """Minimal gate owner and test-only mapping; cannot issue native grants."""
    monitoring = True

    def __init__(self, book, case):
        self.book, self.case_id = book, case
        self.ledger = self
        self.policy = {'execution_configuration': {'proxy': 'http://proxy:8080'}}
        self.claims = {}
        self.case = {'identity': {'ticker': case.split(':')[0], 'cik': CIKS[case.split(':')[0]],
                                  'company_name': 'Invented issuer'}}
        self.identities = [self.case['identity']]
        self.scenario = 'happy'
        self.used = set()

    def active(self):
        if self.book._locally_sealed:
            raise BudgetError('sealed fixture')

    def once(self, scenarios):
        if self.scenario not in scenarios or self.scenario in self.used:
            return False
        self.used.add(self.scenario)
        return True

    def claim_native_dispatch(self, attempt, *, case_run, route, request_sha256):
        if self.claims.get(attempt) != (case_run, route, request_sha256):
            raise BudgetError('fixture claim mismatch')
        self.book.claim_fixture_dispatch(attempt)


def setup(book, case, monkeypatch, *, transport=OwnedHTTPTransport):
    import validation.pilot_approved as approved
    monkeypatch.setattr(approved, 'verify_network_configuration',
                        lambda config, tls=False: ssl.create_default_context() if tls else None)
    owner = FixtureOwner(book, case)
    gate = ExchangeGate(owner)
    wire = transport(gate=gate, execution=owner.policy['execution_configuration'],
                              runtime={'sec_contact': 'Fixture contact@example.invalid'})
    fake = SyntheticProxyBackend(owner)
    wire._wire._pool._network_backend = ScopedBackend(fake, gate)
    return owner, gate, wire


def claim(owner, gate):
    case = owner.case_id
    stage, route = 'evidence.sec_metrics', 'sec/facts'
    url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{CIKS[case.split(":")[0]]}.json'
    fingerprint = digest({'method': 'GET', 'url': url, 'route': route, 'stage': stage})
    attempt = owner.book.claim(case, stage, route)
    owner.claims[attempt] = (case, route, fingerprint)
    return attempt, url, fingerprint, gate.issue(attempt, fingerprint, route, case, stage)


def test_all_cases_use_claimed_scoped_fake_proxy_and_keep_accounting(tmp_path, monkeypatch):
    now = [0]
    book = OfflineAccounting(tmp_path / 'ledger.db', clock=lambda: now[0])
    lifecycle = OfflineCaseLifecycle(book)
    for case in CASES:
        lifecycle.begin(case)
        owner, gate, wire = setup(book, case, monkeypatch)
        attempt, url, fingerprint, grant = claim(owner, gate)
        with gate.exchange(url, grant, fingerprint):
            media, body = wire.exchange('GET', url)
        assert media == 'application/json'
        book.retain_fixture_body(attempt, body, forbidden_values=('invented-secret',))
        book.settle(attempt, succeeded=True)
        assert gate.dispatched == 1
        gate.seal(); wire.close()
        lifecycle.finish(case, status='partial_gap')
        now[0] += 2
    lifecycle.finalize()
    with sqlite3.connect(book.path) as db:
        assert db.execute('SELECT COUNT(*) FROM fixture_dispatches').fetchone()[0] == 12
        assert db.execute("SELECT COUNT(*) FROM attempts WHERE outcome='success'").fetchone()[0] == 12
        assert db.execute('SELECT COUNT(*) FROM bodies').fetchone()[0] == 12


def test_gate_refuses_changed_request_and_reused_grant(tmp_path, monkeypatch):
    book = OfflineAccounting(tmp_path / 'ledger.db')
    lifecycle = OfflineCaseLifecycle(book); lifecycle.begin(CASES[0])
    owner, gate, wire = setup(book, CASES[0], monkeypatch)
    attempt, url, fingerprint, grant = claim(owner, gate)
    with gate.exchange(url, grant, fingerprint):
        with pytest.raises(TransportFailure):
            wire.exchange('GET', url + '?changed=1')
    assert gate.dispatched == 0
    with pytest.raises(BudgetError):
        with gate.exchange(url, grant, fingerprint):
            pass
    assert book.summary()['fixture_dispatch_count'] == 1
    gate.seal(); wire.close()


def test_gate_refuses_mismatched_ledger_claim_before_dispatch(tmp_path, monkeypatch):
    book = OfflineAccounting(tmp_path / 'ledger.db')
    lifecycle = OfflineCaseLifecycle(book); lifecycle.begin(CASES[0])
    owner, gate, wire = setup(book, CASES[0], monkeypatch)
    attempt, url, fingerprint, grant = claim(owner, gate)
    owner.claims[attempt] = (CASES[1], 'sec/facts', fingerprint)
    with pytest.raises(BudgetError):
        with gate.exchange(url, grant, fingerprint):
            pass
    assert gate.dispatched == book.summary()['fixture_dispatch_count'] == 0
    gate.seal(); wire.close()


@pytest.mark.parametrize('scenario', ['wire_connect_failure', 'wire_redirect', 'wire_read_failure'])
def test_scoped_proxy_faults_consume_once_and_stop_case(tmp_path, monkeypatch, scenario):
    book = OfflineAccounting(tmp_path / 'ledger.db')
    lifecycle = OfflineCaseLifecycle(book); lifecycle.begin(CASES[0])
    owner, gate, wire = setup(book, CASES[0], monkeypatch)
    owner.scenario = scenario
    attempt, url, fingerprint, grant = claim(owner, gate)
    with pytest.raises(TransportFailure):
        with gate.exchange(url, grant, fingerprint):
            wire.exchange('GET', url)
    book.settle(attempt, succeeded=False)
    assert gate.dispatched == book.summary()['fixture_dispatch_count'] == 1
    assert book.summary()['outcomes'] == {'failure': 1}
    with pytest.raises(BudgetError):
        with gate.exchange(url, grant, fingerprint):
            pass
    gate.seal(); wire.close()
    result = lifecycle.finalize()
    assert result['cases'][0]['status'] == 'halted'
    assert all(c['status'] == 'not_run_after_halt' for c in result['cases'][1:])


def test_ordinary_transport_disallows_historic_reviewed_exception(tmp_path, monkeypatch):
    from validation.pilot_live import ReviewedDocumentEnvelope
    book = OfflineAccounting(tmp_path / 'ledger.db')
    lifecycle = OfflineCaseLifecycle(book); lifecycle.begin(CASES[0])
    owner, gate, wire = setup(book, CASES[0], monkeypatch, transport=OrdinaryHTTPTransport)
    url = 'https://www.sec.gov/Archives/edgar/data/123/123/annual.htm'
    envelope = ReviewedDocumentEnvelope('0000000123', url, '10-K', '2026-01-01', 'invented')
    assert wire.authorize_reviewed_document('0000000123', url, '10-K', '2026-01-01') is None
    assert wire.response_limit('GET', url, None) == 16 * 1024 * 1024
    with pytest.raises(BudgetError): wire.response_limit('GET', url, envelope)
    gate.seal(); wire.close()


def test_ordinary_transport_rejects_oversized_fake_response(tmp_path, monkeypatch):
    import validation._pilot_wire_fixtures as fixtures
    book = OfflineAccounting(tmp_path / 'ledger.db')
    lifecycle = OfflineCaseLifecycle(book); lifecycle.begin(CASES[0])
    owner, gate, wire = setup(book, CASES[0], monkeypatch, transport=OrdinaryHTTPTransport)
    monkeypatch.setattr(fixtures, 'sec_fixture', lambda *args: ('application/json', b'x' * (16 * 1024 * 1024 + 1)))
    attempt, url, fingerprint, grant = claim(owner, gate)
    with pytest.raises(TransportFailure) as exc:
        with gate.exchange(url, grant, fingerprint): wire.exchange('GET', url)
    assert exc.value.code == 'response_size'
    assert book.summary()['fixture_dispatch_count'] == 1
    book.settle(attempt, succeeded=False)
    gate.seal(); wire.close()
