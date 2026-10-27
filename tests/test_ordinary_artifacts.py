import sqlite3
import pytest
from validation.ordinary_artifacts import store_fixture_answer, verify_terminal_snapshot, export_fixture_packet
from validation.ordinary_pilot_accounting import OfflineAccounting, AccountingError
from validation.ordinary_case_lifecycle import OfflineCaseLifecycle
from validation.ordinary_pilot_contract import CASES
from validation.ordinary_wire_rehearsal import rehearse_facts

SECRET = ('invented-secret-value',)


def finished(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book)
    run.begin(CASES[0])
    rehearse_facts(book, CASES[0])
    payload = {'company':'NPK','answer':{'text':'Complete fixture narrative', 'citations':[]}}
    store_fixture_answer(book, CASES[0], payload, forbidden_values=SECRET)
    run.finish(CASES[0], status='partial_gap')
    run.finalize()
    return book, payload


def test_complete_answer_and_sources_verified_without_ledger_mutation(tmp_path):
    book, payload = finished(tmp_path)
    before = open(book.path, 'rb').read()
    report = verify_terminal_snapshot(book, forbidden_values=SECRET)
    assert len(report['cases']) == report['denominator'] == 12
    assert report['answers'][CASES[0]]['response'] == payload
    assert report['dispatch_count'] == len(report['bodies']) == 1
    assert report['quality_pass_rate'] is None and not report['launch_ready']
    assert open(book.path, 'rb').read() == before


@pytest.mark.parametrize('mutation', ['body', 'answer', 'missing-answer', 'missing-dispatch'])
def test_corrupted_or_missing_records_refused(tmp_path, mutation):
    book, _ = finished(tmp_path)
    with sqlite3.connect(book.path) as db:
        if mutation == 'body': db.execute("UPDATE bodies SET body=x'00'")
        elif mutation == 'answer': db.execute("UPDATE retained_answers SET payload=x'00'")
        elif mutation == 'missing-answer': db.execute('DELETE FROM retained_answers')
        else: db.execute('DELETE FROM fixture_dispatches')
    with pytest.raises(AccountingError):
        verify_terminal_snapshot(book, forbidden_values=SECRET)


def test_secret_answer_refused_before_storage(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book); run.begin(CASES[0])
    with pytest.raises(AccountingError):
        store_fixture_answer(book, CASES[0], {'company':'NPK','answer':{'text':SECRET[0]}}, forbidden_values=SECRET)
    assert book.summary()['halt'] == 'answer_retention_failure'
    assert book._locally_sealed


def test_unsealed_snapshot_refused(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    OfflineCaseLifecycle(book)
    with pytest.raises(AccountingError): verify_terminal_snapshot(book, forbidden_values=SECRET)


def test_all_twelve_answers_and_bodies_remain_in_verified_snapshot(tmp_path):
    now = [0]
    book = OfflineAccounting(tmp_path / 'offline.db', clock=lambda: now[0])
    run = OfflineCaseLifecycle(book)
    for case in CASES:
        run.begin(case)
        rehearse_facts(book, case, scenario='reported-facts')
        store_fixture_answer(book, case, {'company':case.split(':')[0],
            'answer':{'text':'Entire invented answer for ' + case}}, forbidden_values=SECRET)
        run.finish(case, status='partial_gap')
        now[0] += 2
    run.finalize()
    report = verify_terminal_snapshot(book, forbidden_values=SECRET)
    assert len(report['answers']) == len(report['bodies']) == report['dispatch_count'] == 12
    assert list(report['answers']) != []
    assert set(report['answers']) == set(CASES)
    assert report['halt'] == '' and report['quality_pass_rate'] is None


def test_duplicate_answer_cannot_overwrite_original(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    run = OfflineCaseLifecycle(book); run.begin(CASES[0])
    original = {'company':'NPK','answer':{'text':'First complete fixture answer'}}
    store_fixture_answer(book, CASES[0], original, forbidden_values=SECRET)
    with pytest.raises(AccountingError):
        store_fixture_answer(book, CASES[0], {'company':'NPK','answer':{'text':'Replacement'}}, forbidden_values=SECRET)
    with sqlite3.connect(book.path) as db:
        raw = db.execute('SELECT payload FROM retained_answers').fetchone()[0]
    import json
    assert json.loads(raw) == original
    assert book.summary()['halt'] == 'answer_retention_failure'


@pytest.mark.parametrize('mutation', ['stage', 'route', 'stage_quota', 'unrun_attempt', 'clock'])
def test_terminal_verifier_independently_refuses_scope_and_clock_corruption(tmp_path, mutation):
    book, _ = finished(tmp_path)
    with sqlite3.connect(book.path) as db:
        if mutation == 'stage':
            db.execute("UPDATE attempts SET stage='unapproved'")
        elif mutation == 'route':
            db.execute("UPDATE attempts SET route='sec/document'")
        elif mutation == 'stage_quota':
            db.execute("INSERT INTO attempts SELECT 'extra',case_id,stage,route,'failure' FROM attempts")
        elif mutation == 'unrun_attempt':
            db.execute("INSERT INTO attempts VALUES ('extra',?,'evidence.sec_metrics','sec/facts','pending')", (CASES[1],))
        else:
            db.execute('UPDATE fixture_dispatches SET dispatched_at=?', (book.started - 1,))
    with pytest.raises(AccountingError):
        verify_terminal_snapshot(book, forbidden_values=SECRET)


def test_export_contains_original_bytes_and_attempt_scope_without_mutation(tmp_path):
    import base64
    import hashlib
    book, payload = finished(tmp_path)
    before = open(book.path, 'rb').read()
    packet = export_fixture_packet(book, forbidden_values=SECRET)
    item, = packet['attempts']
    raw = base64.b64decode(item['body_base64'], validate=True)
    with sqlite3.connect(book.path) as db:
        original, = db.execute('SELECT body FROM bodies').fetchone()
    assert raw == original and hashlib.sha256(raw).hexdigest() == item['body_sha256']
    assert item['body_bytes'] == len(raw)
    assert (item['case_id'], item['stage'], item['route'], item['outcome']) == (
        CASES[0], 'evidence.sec_metrics', 'sec/facts', 'success')
    assert item['simulated_dispatched_at'] is not None
    assert item['url'] is item['media_type'] is item['http_status'] is None
    assert packet['answers'][CASES[0]]['response'] == payload
    assert packet['denominator'] == 12 and packet['synthetic_only']
    assert not packet['execution_authorized'] and not packet['launch_ready']
    assert open(book.path, 'rb').read() == before


def test_export_rejects_corrupt_body_and_unsealed_ledger(tmp_path):
    book, _ = finished(tmp_path)
    with sqlite3.connect(book.path) as db:
        db.execute("UPDATE bodies SET body=x'00'")
    with pytest.raises(AccountingError):
        export_fixture_packet(book, forbidden_values=SECRET)
    other = OfflineAccounting(tmp_path / 'other.db')
    OfflineCaseLifecycle(other)
    with pytest.raises(AccountingError):
        export_fixture_packet(other, forbidden_values=SECRET)
