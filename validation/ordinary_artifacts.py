"""Offline answer retention and read-only terminal verification; no live authority.

The returned manifest locates original bodies in the private rehearsal ledger.
It is not yet a source-body export or independent source/citation adjudication.
"""
import hashlib
import json
from pathlib import Path
import sqlite3

from .ordinary_pilot_accounting import AccountingError
from .ordinary_pilot_contract import CASES, quota_contract
from .pilot_policy import reject_runtime_values


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def store_fixture_answer(book, case, payload, *, forbidden_values):
    """Retain the entire serialized response while its case is still active."""
    try:
        if (case not in CASES or not getattr(book, '_lifecycle_required', False)
                or book._locally_sealed or type(payload) is not dict
                or payload.get('company') != case.split(':')[0]
                or type(payload.get('answer')) is not dict
                or type(forbidden_values) is not tuple or not forbidden_values
                or any(type(v) is not str or not v for v in forbidden_values)):
            raise AccountingError('invalid answer retention input')
        raw = _bytes(payload)
        if len(raw) > 4 * 1024 * 1024:
            raise AccountingError('answer envelope exceeded')
        reject_runtime_values(payload, forbidden_values, raw=raw)
        with sqlite3.connect(book.path, timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            halt = db.execute('SELECT halt FROM state').fetchone()[0]
            reason = halt or book._case_reason(db, case, book.clock())
            if reason:
                raise AccountingError(reason)
            db.execute('CREATE TABLE IF NOT EXISTS retained_answers '
                       '(case_id TEXT PRIMARY KEY, sha256 TEXT, payload BLOB NOT NULL)')
            db.execute('INSERT INTO retained_answers VALUES (?,?,?)',
                       (case, hashlib.sha256(raw).hexdigest(), raw))
    except BaseException:
        book.seal_local()
        try:
            with sqlite3.connect(book.path, timeout=10) as db:
                db.execute("UPDATE state SET halt=CASE WHEN halt='' THEN 'answer_retention_failure' ELSE halt END")
        except sqlite3.Error:
            pass  # unavailable durable storage cannot permit response publication
        raise AccountingError('answer retention refused') from None


def verify_terminal_snapshot(book, *, forbidden_values):
    """Read one consistent sealed snapshot; refuse mismatched or missing records."""
    if not book._locally_sealed or not getattr(book, '_lifecycle_required', False):
        raise AccountingError('sealed lifecycle required')
    if (type(forbidden_values) is not tuple or not forbidden_values
            or any(type(v) is not str or not v for v in forbidden_values)):
        raise AccountingError('screening values required')
    uri = Path(book.path).resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        db.execute('BEGIN')
        halt, = db.execute('SELECT halt FROM state').fetchone()
        cases = db.execute('SELECT case_id,status FROM case_lifecycle ORDER BY position').fetchall()
        if tuple(c for c, s in cases) != CASES or any(s not in {
                'complete', 'partial_gap', 'halted', 'not_run_after_halt'} for c, s in cases):
            raise AccountingError('invalid terminal denominator')
        attempts = db.execute('SELECT id,case_id,stage,route,outcome FROM attempts ORDER BY rowid').fetchall()
        dispatches = {r[0] for r in db.execute('SELECT attempt_id FROM fixture_dispatches')}
        bodies = {}
        for identifier, sha, raw in db.execute('SELECT attempt_id,sha256,body FROM bodies'):
            if hashlib.sha256(raw).hexdigest() != sha:
                raise AccountingError('body hash mismatch')
            reject_runtime_values(raw.decode('utf-8'), forbidden_values, raw=raw)
            bodies[identifier] = {'sha256': sha, 'bytes': len(raw)}
        policy = quota_contract()
        if (len(attempts) > policy['sec_gets']
                or sum(v['bytes'] for v in bodies.values()) > policy['aggregate_raw_body_max_bytes']
                or any(v['bytes'] > policy['body_max_bytes'] for v in bodies.values())):
            raise AccountingError('artifact envelopes exceeded')
        statuses = dict(cases)
        if not halt and any(s in {'halted', 'not_run_after_halt'} for c, s in cases):
            raise AccountingError('terminal halt missing')
        identifiers = {a[0] for a in attempts}
        if dispatches - identifiers or set(bodies) - identifiers:
            raise AccountingError('orphan transport record')
        for identifier, case, stage, route, outcome in attempts:
            if case not in CASES or outcome not in {'success', 'failure', 'late', 'pending'}:
                raise AccountingError('invalid attempt record')
            if statuses[case] in {'complete', 'partial_gap'} and outcome != 'success':
                raise AccountingError('finished case has unsuccessful attempt')
            if outcome == 'success' and (identifier not in dispatches or identifier not in bodies):
                raise AccountingError('successful attempt missing dispatch or body')
            if outcome == 'pending' and not halt:
                raise AccountingError('unresolved attempt without halt')
        answers = {}
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='retained_answers'").fetchone()
        for case, sha, raw in db.execute('SELECT case_id,sha256,payload FROM retained_answers') if exists else ():
            if case not in CASES or hashlib.sha256(raw).hexdigest() != sha:
                raise AccountingError('answer hash mismatch')
            payload = json.loads(raw)
            reject_runtime_values(payload, forbidden_values, raw=raw)
            if payload.get('company') != case.split(':')[0]:
                raise AccountingError('answer issuer mismatch')
            answers[case] = {'sha256': sha, 'response': payload}
        for case, status in cases:
            if status in {'complete', 'partial_gap'} and case not in answers:
                raise AccountingError('finished case missing complete response')
        return {'cases': [{'case_id': c, 'status': s} for c, s in cases],
                'denominator': 12, 'answers': answers, 'bodies': bodies,
                'attempts': [dict(zip(('id','case_id','stage','route','outcome'), a)) for a in attempts],
                'dispatch_count': len(dispatches), 'halt': halt,
                'quality_pass_rate': None, 'launch_ready': False, 'execution_authorized': False}
