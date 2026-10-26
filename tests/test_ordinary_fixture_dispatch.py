from concurrent.futures import ThreadPoolExecutor
import pytest
from validation.ordinary_pilot_accounting import OfflineAccounting, AccountingError
from validation.ordinary_wire_rehearsal import rehearse_facts
from validation.pilot_live import TransportFailure

CASE = 'NPK:core_thesis'


def test_parallel_duplicate_dispatches_are_one_shot(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    a = book.claim(CASE, 'evidence.sec_metrics', 'sec/facts')
    def dispatch(_):
        try:
            book.claim_fixture_dispatch(a)
            return True
        except AccountingError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(dispatch, range(8))) == 1
    assert book.summary()['fixture_dispatch_count'] == 1
    assert book.summary()['halt'] == 'unclaimed_or_consumed_dispatch'


@pytest.mark.parametrize('kind', ['unknown', 'settled', 'expired'])
def test_dispatch_requires_pending_unexpired_claim(tmp_path, kind):
    now = [0]
    book = OfflineAccounting(tmp_path / 'offline.db', clock=lambda: now[0])
    a = book.claim(CASE, 'evidence.sec_metrics', 'sec/facts')
    if kind == 'unknown': a = 'not-a-claim'
    elif kind == 'settled': book.settle(a, succeeded=True)
    else: now[0] = 480
    with pytest.raises(AccountingError): book.claim_fixture_dispatch(a)
    assert book.summary()['fixture_dispatch_count'] == 0


@pytest.mark.parametrize('advance', [False, True])
def test_rate_limit_is_global_and_consumption_not_refunded(tmp_path, advance):
    now = [0]
    book = OfflineAccounting(tmp_path / 'offline.db', clock=lambda: now[0])
    slots = [('evidence.sec', 'sec/directory'), ('evidence.sec', 'sec/submissions'),
             ('evidence.sec_metrics', 'sec/directory'), ('evidence.sec_metrics', 'sec/facts'),
             ('evidence.filing_metrics', 'sec/submissions'), ('evidence.filing_metrics', 'sec/document'),
             ('evidence.thesis_disclosures', 'sec/submissions'), ('evidence.thesis_disclosures', 'sec/document')]
    for ticker, entries in [('NPK', slots), ('GOOGL', slots[:2])]:
        for stage, route in entries:
            a = book.claim(ticker + ':core_thesis', stage, route)
            book.claim_fixture_dispatch(a)
            book.settle(a, succeeded=True)
    a = book.claim('GOOGL:core_thesis', 'evidence.sec_metrics', 'sec/facts')
    if advance:
        now[0] = 1
        book.claim_fixture_dispatch(a)
        assert book.summary()['fixture_dispatch_count'] == 11
        assert not book.summary()['halt']
    else:
        with pytest.raises(AccountingError, match='dispatch_rate'):
            book.claim_fixture_dispatch(a)
        assert book.summary()['fixture_dispatch_count'] == 10
    assert book.summary()['outcomes'] == {'pending': 1, 'success': 10}


def test_failed_connection_consumes_dispatch(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    with pytest.raises(TransportFailure):
        rehearse_facts(book, CASE, scenario='wire_connect_failure')
    assert book.summary()['fixture_dispatch_count'] == 1
    assert book.summary()['outcomes'] == {'failure': 1}


def test_clock_reversal_refuses_dispatch(tmp_path):
    now = [2]
    book = OfflineAccounting(tmp_path / 'offline.db', clock=lambda: now[0])
    a = book.claim(CASE, 'evidence.sec_metrics', 'sec/facts')
    now[0] = 1
    with pytest.raises(AccountingError, match='clock_drift'):
        book.claim_fixture_dispatch(a)
    assert book.summary()['fixture_dispatch_count'] == 0
