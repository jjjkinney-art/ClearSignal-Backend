import sqlite3
import pytest
from validation.ordinary_pilot_accounting import OfflineAccounting, AccountingError
from validation.ordinary_case_lifecycle import OfflineCaseLifecycle
from validation.ordinary_pilot_contract import CASES
from validation.ordinary_wire_rehearsal import rehearse_facts


def test_attached_lifecycle_denies_claim_before_begin(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    with pytest.raises(AccountingError, match='case_not_active'):
        book.claim(CASES[0], 'evidence.sec_metrics', 'sec/facts')
    assert run.finalize()['halt'] == 'case_not_active'


def test_wrong_case_cannot_borrow_active_scope(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    run.begin(CASES[0])
    with pytest.raises(AccountingError, match='case_not_active'):
        book.claim(CASES[2], 'evidence.sec_metrics', 'sec/facts')
    assert book.summary()['outcomes'] == {}


@pytest.mark.parametrize('operation', ['claim', 'dispatch', 'retain', 'settle'])
@pytest.mark.parametrize('index,deadline', [(0, 30), (1, 20)])
def test_every_operation_checks_case_deadline(tmp_path, operation, index, deadline):
    now = [0]
    book = OfflineAccounting(tmp_path / 'offline.db', clock=lambda: now[0])
    run = OfflineCaseLifecycle(book)
    if index:
        run.begin(CASES[0]); run.finish(CASES[0], status='partial_gap')
    case = CASES[index]
    run.begin(case)
    a = None if operation == 'claim' else book.claim(case, 'evidence.sec_metrics', 'sec/facts')
    now[0] = deadline
    if operation == 'settle':
        book.settle(a, succeeded=True)
        assert book.summary()['outcomes'] == {'late': 1}
    else:
        with pytest.raises(AccountingError, match='case_deadline'):
            if operation == 'claim': book.claim(case, 'evidence.sec_metrics', 'sec/facts')
            elif operation == 'dispatch': book.claim_fixture_dispatch(a)
            else: book.retain_fixture_body(a, b'fixture', forbidden_values=('fixture-secret',))
    assert book.summary()['halt'] == 'case_deadline'
    with sqlite3.connect(book.path) as db:
        assert db.execute('SELECT COUNT(*) FROM bodies').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM fixture_dispatches').fetchone()[0] == 0


def test_complete_twelve_case_wire_rehearsal_preserves_denominator(tmp_path):
    now = [0]
    book = OfflineAccounting(tmp_path / 'offline.db', clock=lambda: now[0])
    run = OfflineCaseLifecycle(book)
    for case in CASES:
        run.begin(case)
        rehearse_facts(book, case, scenario='reported-facts')
        run.finish(case, status='partial_gap')
        now[0] += 2  # invented clock, no sleeping or live requests
    report = run.finalize()
    assert len(report['cases']) == report['denominator'] == 12
    assert all(c['status'] == 'partial_gap' for c in report['cases'])
    assert not report['halt']
    assert book.summary()['fixture_dispatch_count'] == 12
    assert book.summary()['outcomes'] == {'success': 12}
    assert report['quality_pass_rate'] is None


def test_finished_case_cannot_issue_late_work(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    run.begin(CASES[0]); run.finish(CASES[0], status='partial_gap')
    with pytest.raises(AccountingError, match='case_not_active'):
        book.claim(CASES[0], 'evidence.sec_metrics', 'sec/facts')


def test_case_completion_and_new_claim_are_serialized(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    run.begin(CASES[0])
    barrier = Barrier(2)
    def claim():
        barrier.wait()
        try:
            book.claim(CASES[0], 'evidence.sec_metrics', 'sec/facts')
            return True
        except AccountingError:
            return False
    def finish():
        barrier.wait()
        try:
            run.finish(CASES[0], status='partial_gap')
            return True
        except AccountingError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(claim), pool.submit(finish)
        claimed, finished = first.result(), second.result()
    assert claimed != finished
    assert book.summary()['outcomes'] == ({'pending': 1} if claimed else {})
    report = run.finalize()
    assert report['halt']
    assert report['cases'][0]['status'] == ('halted' if claimed else 'partial_gap')
