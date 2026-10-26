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


def test_close_failure_does_not_mask_original_transport_fault(tmp_path, monkeypatch):
    from validation.pilot_live import OwnedHTTPTransport
    original_close = OwnedHTTPTransport.close
    def failing_close(self):
        original_close(self)
        raise RuntimeError('invented cleanup text must not enter ledger')
    monkeypatch.setattr(OwnedHTTPTransport, 'close', failing_close)
    book = OfflineAccounting(tmp_path / 'offline.db')
    with pytest.raises(TransportFailure) as caught:
        rehearse_facts(book, CASES[0], scenario='wire_read_failure')
    assert caught.value.code == 'read_error'
    assert caught.value.offline_cleanup_codes == ('transport_close',)
    assert not caught.value.offline_cleanup_recording_failed
    summary = book.summary()
    assert summary['halt'] == 'attempt_failure'
    assert summary['outcomes'] == {'failure': 1}
    assert summary['cleanup_failures'] == ['transport_close']
    assert 'invented cleanup text' not in str(summary)


def test_settlement_cleanup_failure_is_durable_and_original_survives(tmp_path, monkeypatch):
    book = OfflineAccounting(tmp_path / 'offline.db')
    def fail_settle(*args, **kwargs):
        raise RuntimeError('invented settlement failure')
    monkeypatch.setattr(book, 'settle', fail_settle)
    with pytest.raises(TransportFailure) as caught:
        rehearse_facts(book, CASES[0], scenario='wire_redirect')
    assert caught.value.code == 'http_redirect'
    assert caught.value.offline_cleanup_codes == ('settlement',)
    assert book.summary()['halt'] == 'cleanup_failure'
    assert book.summary()['outcomes'] == {'pending': 1}
    with pytest.raises(AccountingError):
        rehearse_facts(book, CASES[0])


def test_unavailable_cleanup_storage_does_not_hide_first_failure(tmp_path, monkeypatch):
    book = OfflineAccounting(tmp_path / 'offline.db')
    def unavailable(*args, **kwargs):
        raise OSError('invented disk unavailable')
    monkeypatch.setattr(book, 'settle', unavailable)
    monkeypatch.setattr(book, 'record_cleanup_failure', unavailable)
    with pytest.raises(TransportFailure) as caught:
        rehearse_facts(book, CASES[0], scenario='wire_connect_failure')
    assert caught.value.code == 'connect_error'
    assert caught.value.offline_cleanup_recording_failed is True
    assert caught.value.offline_cleanup_codes == ('settlement',)
    with pytest.raises(AccountingError, match='locally sealed'):
        rehearse_facts(book, CASES[2])


@pytest.mark.parametrize('seam', ['retention', 'settle-before-commit', 'settle-after-commit', 'summary', 'close'])
def test_success_path_io_failure_never_returns_and_seals(tmp_path, monkeypatch, seam):
    from validation.pilot_live import OwnedHTTPTransport
    book = OfflineAccounting(tmp_path / 'offline.db')
    real_settle = book.settle
    real_summary = book.summary
    def fail(*args, **kwargs):
        raise OSError('invented primary I/O failure')
    if seam == 'retention':
        monkeypatch.setattr(book, 'retain_fixture_body', fail)
    elif seam.startswith('settle'):
        def settle(identifier, *, succeeded):
            if succeeded:
                if seam == 'settle-after-commit':
                    real_settle(identifier, succeeded=True)
                fail()
            return real_settle(identifier, succeeded=False)
        monkeypatch.setattr(book, 'settle', settle)
    elif seam == 'summary':
        monkeypatch.setattr(book, 'summary', fail)
    else:
        real_close = OwnedHTTPTransport.close
        def close(wire):
            real_close(wire)
            fail()
        monkeypatch.setattr(OwnedHTTPTransport, 'close', close)
    with pytest.raises(OSError, match='invented primary I/O failure') as caught:
        rehearse_facts(book, CASES[0])
    assert hasattr(caught.value, 'offline_cleanup_codes')
    # No returned receipt constitutes publication; attempts/bodies remain audit
    # records even if success committed before an acknowledgement was lost.
    with pytest.raises(AccountingError, match='locally sealed'):
        rehearse_facts(book, CASES[2])
    assert real_summary()['halt']
    assert real_summary()['outcomes'].get('pending', 0) == 0


def test_all_success_cleanup_storage_failures_keep_primary_and_seal(tmp_path, monkeypatch):
    book = OfflineAccounting(tmp_path / 'offline.db')
    def primary(*args, **kwargs):
        raise OSError('invented primary retention error')
    def cleanup(*args, **kwargs):
        raise OSError('invented cleanup storage error')
    monkeypatch.setattr(book, 'retain_fixture_body', primary)
    monkeypatch.setattr(book, 'settle', cleanup)
    monkeypatch.setattr(book, 'record_cleanup_failure', cleanup)
    with pytest.raises(OSError, match='invented primary retention error') as caught:
        rehearse_facts(book, CASES[0])
    assert caught.value.offline_cleanup_codes == ('settlement',)
    assert caught.value.offline_cleanup_recording_failed
    with pytest.raises(AccountingError, match='locally sealed'):
        rehearse_facts(book, CASES[2])
