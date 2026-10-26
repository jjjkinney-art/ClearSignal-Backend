import pytest
from validation.ordinary_pilot_accounting import OfflineAccounting, AccountingError
from validation.ordinary_case_lifecycle import OfflineCaseLifecycle
from validation.ordinary_pilot_contract import CASES


def test_fixed_order_preserves_all_case_outcomes(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    for i, case in enumerate(CASES):
        run.begin(case)
        run.finish(case, status='partial_gap' if i % 2 else 'complete')
    report = run.finalize()
    assert len(report['cases']) == report['denominator'] == 12
    assert [r['case_id'] for r in report['cases']] == list(CASES)
    assert not report['halt']
    assert report['quality_pass_rate'] is None and not report['launch_ready']
    with pytest.raises(AccountingError):
        book.claim(CASES[0], 'evidence.sec', 'sec/submissions')


def test_wrong_order_durably_stops_without_skipping(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    with pytest.raises(AccountingError, match='case_order'): run.begin(CASES[1])
    report = run.finalize()
    assert all(r['status'] == 'not_run_after_halt' for r in report['cases'])


@pytest.mark.parametrize('case_index,limit', [(0, 30), (1, 20)])
def test_case_deadline_exact_boundary(tmp_path, case_index, limit):
    now = [0]
    book = OfflineAccounting(tmp_path / 'offline.db', clock=lambda: now[0])
    run = OfflineCaseLifecycle(book)
    if case_index:
        run.begin(CASES[0]); run.finish(CASES[0], status='partial_gap')
    run.begin(CASES[case_index])
    now[0] = limit
    with pytest.raises(AccountingError, match='case_deadline'):
        run.finish(CASES[case_index], status='complete')
    report = run.finalize()
    assert report['cases'][case_index]['status'] == 'halted'
    assert len(report['cases']) == 12


def test_pending_worker_prevents_case_completion(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    run.begin(CASES[0])
    book.claim(CASES[0], 'evidence.sec_metrics', 'sec/facts')
    with pytest.raises(AccountingError, match='unresolved'):
        run.finish(CASES[0], status='complete')
    report = run.finalize()
    assert report['cases'][0]['status'] == 'halted'
    assert all(c['status'] == 'not_run_after_halt' for c in report['cases'][1:])


def test_unfinished_run_is_not_completion(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    run.begin(CASES[0])
    report = run.finalize()
    assert report['halt'] == 'incomplete_run'
    assert report['cases'][0]['status'] == 'halted'
    assert run.finalize() == report


def test_ambiguous_case_outcome_halts(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    run.begin(CASES[0])
    with pytest.raises(AccountingError, match='invalid case outcome'):
        run.finish(CASES[0], status=True)
    assert run.finalize()['halt'] == 'invalid_case_outcome'


def test_only_one_running_case(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    run.begin(CASES[0])
    with pytest.raises(AccountingError, match='case_order'):
        run.begin(CASES[1])
    assert run.finalize()['cases'][0]['status'] == 'halted'


def test_local_seal_prohibits_new_case_even_without_durable_halt(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    book.seal_local()
    with pytest.raises(AccountingError, match='locally sealed'):
        run.begin(CASES[0])
