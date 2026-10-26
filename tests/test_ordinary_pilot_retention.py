from concurrent.futures import ThreadPoolExecutor
import hashlib
import sqlite3
import pytest
from validation.ordinary_pilot_accounting import OfflineAccounting, AccountingError

CASE = 'NPK:core_thesis'
SECRET = ('FIXTURE_SECRET_DO_NOT_RETAIN',)


def attempt(book, stage='evidence.sec', route='sec/submissions'):
    return book.claim(CASE, stage, route)


def test_complete_bytes_and_hash_are_durable(tmp_path):
    b = OfflineAccounting(tmp_path / 'offline.db')
    a = attempt(b)
    body = b'<html>entire fixture source</html>\n'
    receipt = b.retain_fixture_body(a, body, forbidden_values=SECRET)
    assert receipt['body_sha256'] == hashlib.sha256(body).hexdigest()
    assert receipt['body_bytes'] == len(body)
    with sqlite3.connect(b.path) as db:
        assert db.execute('SELECT body FROM bodies').fetchone()[0] == body
    with pytest.raises(AccountingError):
        b.retain_fixture_body(a, body, forbidden_values=SECRET)


@pytest.mark.parametrize('body', [b'FIXTURE_SECRET_DO_NOT_RETAIN',
    b'{"value":"FIXTURE_SECRET_DO_NOT_RETAIN"}', b'\xff', b'x' * 16777217],
    ids=['raw-secret', 'json-secret', 'invalid-utf8', 'oversized-body'])
def test_rejected_body_never_stored(tmp_path, body):
    b = OfflineAccounting(tmp_path / 'offline.db')
    a = attempt(b)
    with pytest.raises(AccountingError):
        b.retain_fixture_body(a, body, forbidden_values=SECRET)
    with sqlite3.connect(b.path) as db:
        assert db.execute('SELECT COUNT(*) FROM bodies').fetchone()[0] == 0
    assert b.summary()['halt']


def test_aggregate_cap_is_atomic_under_concurrency(tmp_path):
    b = OfflineAccounting(tmp_path / 'offline.db')
    # Smaller private fixture envelope; actual contract remains immutable to callers.
    b._policy['aggregate_raw_body_max_bytes'] = 7
    a = attempt(b)
    c = attempt(b, 'evidence.sec_metrics', 'sec/facts')
    def save(identifier):
        try:
            return b.retain_fixture_body(identifier, b'12345', forbidden_values=SECRET)
        except AccountingError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(save, [a, c]))
    assert sum(r is not None for r in receipts) == 1
    with sqlite3.connect(b.path) as db:
        assert db.execute('SELECT SUM(length(body)) FROM bodies').fetchone()[0] == 5
    assert b.summary()['halt'] == 'aggregate_body_size'


def test_late_and_settled_attempts_cannot_publish_body(tmp_path):
    now = [0]
    b = OfflineAccounting(tmp_path / 'offline.db', clock=lambda: now[0])
    a = attempt(b)
    now[0] = 480
    with pytest.raises(AccountingError, match='deadline'):
        b.retain_fixture_body(a, b'fixture', forbidden_values=SECRET)
    assert b.summary()['halt'] == 'deadline'
