import sqlite3
import pytest
from validation.ordinary_pilot_accounting import OfflineAccounting, AccountingError
from validation.ordinary_pilot_contract import CASES
from validation.ordinary_wire_rehearsal import rehearse_facts
from validation.pilot_live import TransportFailure


@pytest.mark.parametrize('case', CASES)
def test_all_twelve_case_facts_use_owned_protocol_and_retention(tmp_path, case):
    book = OfflineAccounting(tmp_path / 'offline.db')
    result = rehearse_facts(book, case)
    assert result['simulated_connections'] == 1
    assert result['external_requests'] == 0
    assert result['execution_authorized'] is False
    assert book.summary()['outcomes'] == {'success': 1}
    with sqlite3.connect(book.path) as db:
        assert db.execute('SELECT COUNT(*) FROM bodies').fetchone()[0] == 1
    with pytest.raises(AccountingError, match='quota'):
        rehearse_facts(book, case)
    assert book.summary()['outcomes'] == {'success': 1}


@pytest.mark.parametrize('scenario,code', [
    ('wire_redirect', 'http_redirect'), ('wire_read_failure', 'read_error'),
    ('wire_connect_failure', 'connect_error')])
def test_wire_fault_consumes_one_attempt_and_halts_without_body(tmp_path, scenario, code):
    book = OfflineAccounting(tmp_path / 'offline.db')
    with pytest.raises(TransportFailure) as failure:
        rehearse_facts(book, CASES[0], scenario=scenario)
    assert failure.value.code == code
    assert book.summary()['outcomes'] == {'failure': 1}
    assert book.summary()['halt'] == 'attempt_failure'
    with sqlite3.connect(book.path) as db:
        assert db.execute('SELECT COUNT(*) FROM bodies').fetchone()[0] == 0
    with pytest.raises(AccountingError):
        rehearse_facts(book, CASES[0])


def test_real_backend_cannot_be_used_without_approved_gate():
    from validation.pilot_live import OwnedHTTPTransport
    from validation.capture_budget import BudgetError
    wire = OwnedHTTPTransport()
    try:
        with pytest.raises(BudgetError, match='real provider execution remains disabled'):
            wire.exchange('GET', 'https://data.sec.gov/api/xbrl/companyfacts/CIK0000080172.json')
    finally:
        wire.close()


def test_transport_constructor_failure_keeps_attempt_consumed(tmp_path, monkeypatch):
    import validation.pilot_live as live
    def fail():
        raise RuntimeError('invented constructor failure')
    monkeypatch.setattr(live, 'OwnedHTTPTransport', fail)
    book = OfflineAccounting(tmp_path / 'offline.db')
    with pytest.raises(RuntimeError, match='invented constructor failure'):
        rehearse_facts(book, CASES[0])
    assert book.summary()['outcomes'] == {'failure': 1}
    assert book.summary()['halt'] == 'attempt_failure'


@pytest.mark.parametrize('scenario', ['wire_redirect', 'wire_read_failure', 'wire_connect_failure'])
def test_wire_fault_never_retries_connection(tmp_path, monkeypatch, scenario):
    from validation._pilot_wire_fixtures import SyntheticNetworkBackend
    original = SyntheticNetworkBackend.connect_tcp
    calls = []
    def counted(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(SyntheticNetworkBackend, 'connect_tcp', counted)
    book = OfflineAccounting(tmp_path / 'offline.db')
    with pytest.raises(TransportFailure):
        rehearse_facts(book, CASES[0], scenario=scenario)
    assert len(calls) == 1
