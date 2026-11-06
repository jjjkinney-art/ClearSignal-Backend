"""Parent-side, read-only verification and export of one native ordinary ledger.

Runs only after the worker process has exited or been killed and reaped. The
packet reports all twelve case outcomes, every attempt (including failures,
which carry no fabricated body or receipt), retained body hashes, answers and
the first durable failure. Hashes establish integrity, not SEC authenticity,
citation support or research quality.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

from validation.capture_budget import BudgetError, digest
from validation.ordinary_native_ledger import RUN_SECONDS, case_seconds, screen_body
from validation.ordinary_pilot_contract import CASES, quota_contract


class ExportRefused(BudgetError):
    pass


def record_parent_stop(path, reason):
    """After the child is reaped: durably record why the parent stopped it.

    Opening read-write first also lets SQLite roll back any transaction the
    killed child left in its hot journal. The first durable halt is kept.
    """
    if reason not in {'stage_timeout', 'rehearsal_failure'}:
        raise ExportRefused('unsupported parent stop reason')
    with sqlite3.connect(Path(path).as_uri() + '?mode=rw', uri=True, timeout=10) as db:
        db.execute('UPDATE policy SET halted=COALESCE(halted,?) WHERE id=1', (reason,))


def export_packet(path, policy, *, forbidden_values, synthetic):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ExportRefused('ledger missing')
    limits = quota_contract()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        policy_hash, halted = db.execute('SELECT hash,halted FROM policy WHERE id=1').fetchone()
        if policy_hash != digest(policy):
            raise ExportRefused('ledger policy differs from the bound policy')
        run_started, = db.execute('SELECT started_ns FROM ordinary_run WHERE id=1').fetchone()
        cases = db.execute('SELECT c.id,c.case_id,c.status,t.started_ns FROM cases c '
                           'JOIN ordinary_case_times t ON t.case_run=c.id ORDER BY t.started_ns').fetchall()
        attempts = db.execute('SELECT a.id,a.case_run,a.route,a.status,a.request_sha256,s.stage FROM attempts a '
                              'JOIN stage_reservations s ON s.attempt_id=a.id ORDER BY a.rowid').fetchall()
        entries = dict(db.execute('SELECT attempt_id,entered_ns FROM ordinary_wire_entries'))
        intents = {r[0] for r in db.execute('SELECT attempt_id FROM native_dispatches')} \
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='native_dispatches'").fetchone() else set()
        responses = {r[0]: r[1:] for r in db.execute(
            'SELECT attempt_id,url,http_status,media_type,sha256,body,completed_ns FROM ordinary_responses')}
        failures = {r[0]: r[1:] for r in db.execute(
            'SELECT attempt_id,code,detail,recorded_ns FROM ordinary_exchange_failures')}
        answers = {r[0]: r[1:] for r in db.execute(
            'SELECT case_run,case_id,sha256,payload,recorded_ns FROM ordinary_answers')}
        first_transport = db.execute('SELECT attempt_id,route,stage,code FROM first_transport_failure WHERE id=1').fetchone()
        first_refusal = db.execute('SELECT attempt_id,route,stage,code FROM first_sec_refusal WHERE id=1').fetchone()

    # Stored types first: a value of the wrong SQLite type is never coerced.
    if (type(run_started) is not int or type(halted) not in (str, type(None))
            or any(type(r[0]) is not str or type(r[1]) is not str or type(r[3]) is not int for r in cases)
            or any(type(v) is not int for v in entries.values())
            or any(type(r[1]) is not int or type(r[3]) is not str or type(r[4]) is not bytes or type(r[5]) is not int
                   for r in responses.values())
            or any(type(r[1]) is not str or type(r[2]) is not bytes or type(r[3]) is not int for r in answers.values())):
        raise ExportRefused('ledger record has an unexpected stored type')

    # Case order, deadlines and answers.
    if [row[1] for row in cases] != list(CASES[:len(cases)]):
        raise ExportRefused('case order differs from the fixed cohort')
    if sum(row[2] == 'active' for row in cases) > 1 or (cases and any(r[2] == 'active' for r in cases[:-1])):
        raise ExportRefused('more than one active case')
    by_run = {row[0]: row for row in cases}
    for run, (case_id, sha, raw, recorded) in answers.items():
        row = by_run.get(run)
        if (row is None or row[1] != case_id or row[2] != 'complete'
                or hashlib.sha256(raw).hexdigest() != sha or len(raw) > 4 * 1024 * 1024
                or not row[3] <= recorded < row[3] + case_seconds(case_id) * 1_000_000_000
                or recorded - run_started >= RUN_SECONDS * 1_000_000_000):
            raise ExportRefused('answer outside its completed case or deadline')
        payload = json.loads(raw)
        from validation.pilot_policy import reject_runtime_values
        reject_runtime_values(payload, forbidden_values, raw=raw)
        if payload.get('company') not in {case_id.split(':')[0], ''}:
            raise ExportRefused('answer issuer mismatch')
    if any(row[2] == 'complete' and row[0] not in answers for row in cases):
        raise ExportRefused('completed case without its retained answer')

    # Attempts, quotas, receipts and wire timing.
    case_of = {row[0]: row[1] for row in cases}
    case_start = {row[0]: row[3] for row in cases}
    abandoned_runs = set()
    counts, total, entries_seen, aggregate = Counter(), 0, [], 0
    records = []
    for attempt, run, route, status, request_sha, stage in attempts:
        case_id = case_of.get(run)
        if case_id is None:
            raise ExportRefused('attempt outside a recorded case')
        counts[case_id, route] += 1
        counts[case_id, stage, route] += 1
        counts[case_id] += 1
        total += 1
        per_case = limits['per_case'][case_id]
        if (counts[case_id] > per_case['sec'] or counts[case_id, route] > per_case[route]
                or counts[case_id, stage, route] > limits['per_stage'][case_id].get(stage, {}).get(route, 0)
                or total > limits['sec_gets']):
            raise ExportRefused('attempt exceeds the fixed quota contract')
        response = responses.get(attempt)
        entered = entries.get(attempt)
        if status == 'abandoned':
            # Abandoned by the application at its evidence timeout: terminal only
            # once its exchange ended, closed before the next case began, never
            # retained, and still counted against every quota and limit.
            failure = failures.get(attempt)
            later = [row[3] for row in cases if row[3] > case_start[run]]
            if (response is not None or failure is None or failure[0] != 'abandoned' or failure[1] != route
                    or type(failure[2]) is not int or failure[2] < case_start[run]
                    or (entered is not None and failure[2] < entered)
                    or (later and failure[2] >= min(later))):
                raise ExportRefused('abandoned attempt without its closed terminal record')
            abandoned_runs.add(run)
        if entered is not None:
            ended = response[5] if response else (failures[attempt][2] if status == 'abandoned' else None)
            entries_seen.append((entered, ended))
            if attempt not in intents:
                raise ExportRefused('wire entry without native intent')
        record = {'attempt_id': attempt, 'case_id': case_id, 'stage': stage, 'route': route,
                  'status': status, 'request_sha256': request_sha,
                  'wire_entered_offset_ms': None if entered is None else round((entered - run_started) / 1e6, 3),
                  'response': None, 'failure': None}
        if response is not None:
            url, http_status, media, sha, body, completed = response
            if (status != 'settled' or entered is None or http_status != 200 or len(body) > limits['body_max_bytes']
                    or hashlib.sha256(body).hexdigest() != sha
                    or request_sha != digest({'method': 'GET', 'url': url, 'route': route, 'stage': stage})
                    or media not in ({'text/html', 'text/plain'} if route == 'sec/document' else {'application/json'})
                    or completed < entered):
                raise ExportRefused('retained response does not match its immutable request')
            screen_body(body, media, forbidden_values)
            aggregate += len(body)
            record['response'] = {'url': url, 'http_status': 200, 'media_type': media,
                                  'body_sha256': sha, 'body_bytes': len(body),
                                  'completed_offset_ms': round((completed - run_started) / 1e6, 3)}
        elif status == 'settled':
            raise ExportRefused('settled attempt without retained response')
        if attempt in failures:
            record['failure'] = {'code': failures[attempt][0], 'detail': failures[attempt][1]}
        if status not in ('settled', 'abandoned') and not halted:
            raise ExportRefused('unresolved attempt without a durable halt')
        records.append(record)
    if aggregate > limits['aggregate_raw_body_max_bytes']:
        raise ExportRefused('aggregate retained bodies exceed the contract')
    starts = sorted(start for start, _ in entries_seen)
    for index, start in enumerate(starts):
        if sum(1 for other in starts[:index] if other > start - 1_000_000_000) >= 10:
            raise ExportRefused('wire entries exceed ten per second')
        open_at_entry = sum(1 for s, end in entries_seen if s < start and (end is None or end > start))
        if open_at_entry >= limits['concurrent_sec']:
            raise ExportRefused('wire entries exceed four concurrent requests')

    # Twelve outcomes; a halt never turns gaps into passes.
    outcomes = []
    for index, case_id in enumerate(CASES):
        row = next((r for r in cases if r[1] == case_id), None)
        if row is None:
            status = 'not_run_after_halt' if halted else 'not_run'
        elif row[2] == 'complete':
            # An unresolved company is retained and reported, never a pass. An
            # answer missing evidence the application abandoned is degraded.
            unresolved = json.loads(answers[row[0]][2]).get('company') == ''
            status = ('identity_unresolved' if unresolved else
                      'answered_degraded_unadjudicated' if row[0] in abandoned_runs else 'answered_unadjudicated')
        else:
            status = 'halted'
        outcomes.append({'case_id': case_id, 'status': status})
    complete = not halted and all(o['status'] in {'answered_unadjudicated', 'answered_degraded_unadjudicated',
                                                  'identity_unresolved'} for o in outcomes)
    kinds = {'answered_unadjudicated': 'full_answer', 'answered_degraded_unadjudicated': 'degraded_answer',
             'identity_unresolved': 'unanswered'}
    outcome_counts = Counter(kinds.get(o['status'], 'operational_failure') for o in outcomes)
    first = (dict(zip(('attempt_id', 'route', 'stage', 'code'), first_transport)) if first_transport
             else dict(zip(('attempt_id', 'route', 'stage', 'code'), first_refusal)) if first_refusal else None)
    return {'format': 'ordinary-native-packet-v1', 'synthetic_sec_backend': synthetic,
            'status': 'complete' if complete else 'halted', 'halt': halted,
            'first_failure': first, 'denominator': len(CASES), 'cases': outcomes,
            'outcome_counts': {k: outcome_counts.get(k, 0) for k in
                               ('full_answer', 'degraded_answer', 'unanswered', 'operational_failure')},
            'answers': {answers[run][0]: {'sha256': answers[run][1], 'response': json.loads(answers[run][2])}
                        for run in answers},
            'attempts': records, 'attempt_count': len(records),
            'retained_body_bytes': aggregate, 'wire_entries': len(entries_seen),
            'quality_pass_rate': None, 'launch_ready': False, 'execution_authorized': False,
            'invoice_ceiling_verified': False}
