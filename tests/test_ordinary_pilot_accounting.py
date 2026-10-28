from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import pytest
from validation.ordinary_pilot_accounting import OfflineAccounting, AccountingError

CASE = 'NPK:core_thesis'


def test_failure_consumes_claim_and_durably_halts(tmp_path):
    path = tmp_path / 'offline.db'
    book = OfflineAccounting(path)
    attempt = book.claim(CASE, 'evidence.sec', 'sec/submissions')
    book.settle(attempt, succeeded=False)
    with pytest.raises(AccountingError):
        book.claim(CASE, 'evidence.sec_metrics', 'sec/facts')
    assert book.summary()['outcomes'] == {'failure': 1}
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT halt FROM state').fetchone()[0] == 'attempt_failure'
    with pytest.raises(FileExistsError):
        OfflineAccounting(path)


def test_parallel_claims_cannot_exceed_stage_limit(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    def worker(_):
        try:
            return book.claim(CASE, 'evidence.sec_metrics', 'sec/facts')
        except AccountingError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = [a for a in pool.map(worker, range(8)) if a]
    assert len(claimed) == 1
    book.settle(claimed[0], succeeded=True)
    assert book.summary()['outcomes'] == {'late': 1}
    assert book.summary()['halt'] == 'quota'


def test_shared_directory_cap_across_stages(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    for stage in ('evidence.sec', 'evidence.sec_metrics'):
        book.settle(book.claim(CASE, stage, 'sec/directory'), succeeded=True)
    with pytest.raises(AccountingError, match='quota'):
        book.claim(CASE, 'evidence.filing_metrics', 'sec/directory')
    assert book.summary()['outcomes'] == {'success': 2}


def test_deadline_and_duplicate_settlement(tmp_path):
    now = [0]
    book = OfflineAccounting(tmp_path / 'offline.db', clock=lambda: now[0])
    a = book.claim(CASE, 'evidence.sec', 'sec/submissions')
    now[0] = 480
    book.settle(a, succeeded=True)
    assert book.summary()['outcomes'] == {'late': 1}
    with pytest.raises(AccountingError):
        book.settle(a, succeeded=True)
    assert book.summary()['halt'] == 'deadline'


@pytest.mark.parametrize('case,stage,route', [
    ('ASML:core_thesis', 'evidence.sec', 'sec/submissions'),
    ('NPK:decision_threshold', 'evidence.thesis_disclosures', 'sec/document'),
    (CASE, 'unknown', 'sec/facts'), (CASE, 'evidence.sec', 'model'),
])
def test_scope_denied_before_claim(tmp_path, case, stage, route):
    book = OfflineAccounting(tmp_path / 'offline.db')
    with pytest.raises(AccountingError, match='scope'):
        book.claim(case, stage, route)
    assert book.summary()['outcomes'] == {}


def test_ambiguous_outcome_durably_halts_without_settling(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    a = book.claim(CASE, 'evidence.sec', 'sec/submissions')
    with pytest.raises(AccountingError, match='invalid outcome'):
        book.settle(a, succeeded=1)
    assert book.summary()['halt'] == 'invalid_outcome'
    assert book.summary()['outcomes'] == {'pending': 1}
    with pytest.raises(AccountingError):
        book.claim(CASE, 'evidence.sec_metrics', 'sec/facts')
    book.settle(a, succeeded=True)
    assert book.summary()['outcomes'] == {'late': 1}
@pytest.mark.parametrize('mode', ['deleted', 'replaced', 'symlink'])
def test_unavailable_or_replaced_ledger_never_silently_reopens(tmp_path, mode):
    book = OfflineAccounting(tmp_path / 'original.db')
    original = Path(book.path)
    if mode == 'deleted':
        original.unlink()
    else:
        original.rename(tmp_path / 'preserved.db')
        if mode == 'replaced': original.write_bytes(b'replacement')
        else: original.symlink_to(tmp_path / 'preserved.db')
    with pytest.raises(AccountingError): book.claim(CASE, 'evidence.sec_metrics', 'sec/facts')
    assert book._locally_sealed
    if mode == 'deleted': assert not original.exists()
    if mode == 'replaced': assert original.read_bytes() == b'replacement'
