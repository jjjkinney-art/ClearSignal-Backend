"""Offline answer retention and read-only terminal verification; no live authority.

The fixture export includes stored bytes and simulated receipts. It does not
establish source authenticity or independently adjudicate citations.
"""
import base64
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import sqlite3
import math
from collections import Counter

from .ordinary_pilot_accounting import AccountingError
from .ordinary_pilot_contract import CASES, quota_contract
from .pilot_policy import reject_runtime_values


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def store_fixture_answer(book, case, payload, *, forbidden_values):
    """Retain the entire serialized response while its case is still active."""
    with book._seal_lock:
        return _store_fixture_answer_locked(book, case, payload, forbidden_values=forbidden_values)


def _store_fixture_answer_locked(book, case, payload, *, forbidden_values):
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
        with book._connect() as db:
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
            with book._connect() as db:
                db.execute("UPDATE state SET halt=CASE WHEN halt='' THEN 'answer_retention_failure' ELSE halt END")
        except sqlite3.Error:
            pass  # unavailable durable storage cannot permit response publication
        raise AccountingError('answer retention refused') from None


def verify_terminal_snapshot(book, *, forbidden_values, require_bound=False, _snapshot=None):
    """Read one consistent sealed snapshot; refuse mismatched or missing records."""
    if not book._locally_sealed or not getattr(book, '_lifecycle_required', False):
        raise AccountingError('sealed lifecycle required')
    if (type(forbidden_values) is not tuple or not forbidden_values
            or any(type(v) is not str or not v for v in forbidden_values)):
        raise AccountingError('screening values required')
    if type(require_bound) is not bool:
        raise AccountingError('invalid binding requirement')
    book._check_identity()
    uri = Path(book.path).as_uri() + '?mode=ro'
    with (sqlite3.connect(uri, uri=True) if _snapshot is None else nullcontext(_snapshot)) as db:
        db.execute('BEGIN')
        halt, = db.execute('SELECT halt FROM state').fetchone()
        cases = db.execute('SELECT case_id,status FROM case_lifecycle ORDER BY position').fetchall()
        if tuple(c for c, s in cases) != CASES or any(s not in {
                'complete', 'partial_gap', 'halted', 'not_run_after_halt'} for c, s in cases):
            raise AccountingError('invalid terminal denominator')
        attempts = db.execute('SELECT id,case_id,stage,route,outcome,request_sha256 FROM attempts ORDER BY rowid').fetchall()
        dispatch_rows = db.execute('SELECT attempt_id,dispatched_at FROM fixture_dispatches ORDER BY rowid').fetchall()
        dispatches = {r[0] for r in dispatch_rows}
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
        receipts = {identifier: (url, media, status) for identifier, url, media, status
                    in db.execute('SELECT attempt_id,url,media_type,http_status FROM fixture_receipts')}
        if set(receipts) - identifiers or set(receipts) - dispatches or set(receipts) - set(bodies):
            raise AccountingError('orphan fixture receipt')
        from .ordinary_wire_rehearsal import _fixture_url_from_db
        case_counts, route_counts, stage_counts = Counter(), Counter(), Counter()
        from .capture_budget import digest as request_digest
        for identifier, case, stage, route, outcome, fingerprint in attempts:
            if case not in CASES or outcome not in {'success', 'failure', 'late', 'pending'}:
                raise AccountingError('invalid attempt record')
            if require_bound and (type(fingerprint) is not str or len(fingerprint) != 64
                                  or any(c not in '0123456789abcdef' for c in fingerprint)):
                raise AccountingError('fixture request binding missing')
            cap = policy['per_stage'][case].get(stage, {}).get(route, 0)
            if not cap or not policy['per_case'][case].get(route, 0):
                raise AccountingError('attempt outside authorized fixture scope')
            case_counts[case] += 1
            route_counts[case, route] += 1
            stage_counts[case, stage, route] += 1
            if (case_counts[case] > policy['per_case'][case]['sec']
                    or route_counts[case, route] > policy['per_case'][case][route]
                    or stage_counts[case, stage, route] > cap):
                raise AccountingError('fixture quota exceeded')
            if statuses[case] == 'not_run_after_halt':
                raise AccountingError('unrun case has attempt')
            if statuses[case] in {'complete', 'partial_gap'} and outcome != 'success':
                raise AccountingError('finished case has unsuccessful attempt')
            if outcome == 'success' and (identifier not in dispatches or identifier not in bodies):
                raise AccountingError('successful attempt missing dispatch or body')
            if outcome == 'success' and identifier not in receipts:
                raise AccountingError('successful attempt missing fixture receipt')
            if identifier in receipts:
                url, media, status = receipts[identifier]
                if (url != _fixture_url_from_db(db, case, stage, route)
                        or media != ('text/html' if route == 'sec/document' else 'application/json')
                        or status != 200 or (fingerprint is not None and fingerprint !=
                            request_digest({'method':'GET', 'url':url, 'route':route, 'stage':stage}))):
                    raise AccountingError('invalid fixture receipt')
            if outcome == 'pending' and not halt:
                raise AccountingError('unresolved attempt without halt')
        times = []
        for _, timestamp in dispatch_rows:
            if (type(timestamp) not in (int, float) or not math.isfinite(timestamp)
                    or timestamp < book.started or timestamp - book.started >= policy['wall_seconds']
                    or (times and timestamp < times[-1])):
                raise AccountingError('invalid fixture dispatch clock')
            if sum(t > timestamp - 1 for t in times) >= 10:
                raise AccountingError('fixture dispatch rate exceeded')
            times.append(timestamp)
        answers = {}
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='retained_answers'").fetchone()
        for case, sha, raw in db.execute('SELECT case_id,sha256,payload FROM retained_answers') if exists else ():
            if case not in CASES or hashlib.sha256(raw).hexdigest() != sha:
                raise AccountingError('answer hash mismatch')
            if statuses[case] == 'not_run_after_halt' or len(raw) > 4 * 1024 * 1024:
                raise AccountingError('invalid retained answer')
            payload = json.loads(raw)
            reject_runtime_values(payload, forbidden_values, raw=raw)
            if (type(payload) is not dict or payload.get('company') != case.split(':')[0]
                    or type(payload.get('answer')) is not dict):
                raise AccountingError('answer issuer mismatch')
            answers[case] = {'sha256': sha, 'response': payload}
        for case, status in cases:
            if status in {'complete', 'partial_gap'} and case not in answers:
                raise AccountingError('finished case missing complete response')
        return {'cases': [{'case_id': c, 'status': s} for c, s in cases],
                'denominator': 12, 'answers': answers, 'bodies': bodies,
                'attempts': [dict(zip(('id','case_id','stage','route','outcome','request_sha256'), a)) for a in attempts],
                'dispatch_count': len(dispatches), 'halt': halt,
                'quality_pass_rate': None, 'launch_ready': False, 'execution_authorized': False}


def export_fixture_packet(book, *, forbidden_values, require_bound=False):
    """Export one verified snapshot in memory; fixture evidence only, never live authority.

    The manifest includes original body bytes (base64), attempts, and observed
    fake-dispatch times and fixture receipts. Failed requests can lack receipts.
    It does not establish authenticity or citation support.
    """
    book._check_identity()
    uri = Path(book.path).as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        report = verify_terminal_snapshot(book, forbidden_values=forbidden_values, require_bound=require_bound, _snapshot=db)
        rows = db.execute('SELECT a.id,a.case_id,a.stage,a.route,a.outcome,d.dispatched_at,'
                          'b.sha256,b.body,r.url,r.media_type,r.http_status,a.request_sha256 FROM attempts a '
                          'LEFT JOIN fixture_dispatches d ON d.attempt_id=a.id '
                          'LEFT JOIN bodies b ON b.attempt_id=a.id '
                          'LEFT JOIN fixture_receipts r ON r.attempt_id=a.id ORDER BY a.rowid').fetchall()
        records = []
        for identifier, case, stage, route, outcome, dispatched, sha, raw, url, media, status, fingerprint in rows:
            records.append({'attempt_id': identifier, 'case_id': case, 'stage': stage,
                            'route': route, 'outcome': outcome,
                            'simulated_dispatched_at': dispatched,
                            'body_sha256': sha,
                            'body_bytes': len(raw) if raw is not None else None,
                            'body_base64': base64.b64encode(raw).decode('ascii') if raw is not None else None,
                            'url': url, 'media_type': media, 'http_status': status,
                            'request_sha256': fingerprint})
        return {'format': 'ordinary-fixture-packet-v1', 'synthetic_only': True,
                'cases': report['cases'], 'denominator': report['denominator'],
                'halt': report['halt'], 'answers': report['answers'], 'attempts': records,
                'request_binding_required': require_bound,
                'quality_pass_rate': None, 'launch_ready': False, 'execution_authorized': False}
