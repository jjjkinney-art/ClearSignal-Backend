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
from validation.ordinary_native_ledger import (DIRECTORY_URL, RUN_SECONDS, answer_names_issuer, case_seconds, degraded_stages,
                                                screen_body, valid_size_rejection)
from validation.ordinary_pilot_contract import CASES, quota_contract
from validation.ordinary_registration_only import declaration_supported, declared_not_applicable, submissions_url


# Three kinds of delivered content, never pooled:
#   source_bound_claims            financial claims (and any other bound claims) - counts toward the
#                                  approved "source-bound claims" target
#   source_bound_disclosures_only  quoted business, competition or risk statements with NO financial
#                                  analysis - source-backed, but excluded from that target
#   everything else                no substantive answer (insufficient evidence, unresolved identity, ...)
DISCLOSURES_ONLY = 'source_bound_disclosures_only'
ANSWER_CONTENT_KINDS = ('source_bound_claims', DISCLOSURES_ONLY, 'insufficient_evidence', 'identity_unresolved',
                        'no_answer', 'not_run', 'unclassified')
# Kept equal to app.services.disclosure_only_answer.DISCLOSURE_ONLY_KINDS by a test.
DISCLOSURE_ONLY_CLAIM_KINDS = frozenset({'issuer_business_description', 'issuer_competition_description',
                                         'issuer_disclosed_risk'})


def content_coverage(tally, denominator):
    """Both coverage counts, so a disclosure-only answer cannot be read as financial analysis.

    total_source_backed: every case that delivered any source-bound content.
    toward_source_bound_claims_target: the count the existing "at least 8 of 12" target uses;
    disclosure-only cases are excluded from it.
    """
    claims, disclosures = tally.get('source_bound_claims', 0), tally.get(DISCLOSURES_ONLY, 0)
    return {'denominator': denominator,
            'total_source_backed': claims + disclosures,
            'toward_source_bound_claims_target': claims,
            'disclosure_only_excluded_from_target': disclosures,
            'no_substantive_answer': denominator - claims - disclosures}


class ExportRefused(BudgetError):
    pass


def _insufficient(payload):
    """The application itself says too little evidence remains to answer."""
    answer = payload.get('answer') if type(payload) is dict else None
    source = answer.get('source_answer') if type(answer) is dict else None
    return type(source) is dict and source.get('status') == 'insufficient_claim_evidence'


def answer_content(case_status, payload):
    """What a case delivered, separate from whether it completed operationally.

    Only an answer carrying source-bound claims counts as having content, and even
    that says nothing about accuracy or usefulness, which are assessed separately.
    Anything else, including a completed insufficient-evidence response, does not.
    """
    if case_status in {'not_run', 'not_run_after_halt'}:
        return 'not_run'
    if payload is None:
        return 'no_answer'
    if case_status == 'identity_unresolved':
        return 'identity_unresolved'
    answer = payload.get('answer') if type(payload) is dict else None
    source = answer.get('source_answer') if type(answer) is dict else None
    status = source.get('status') if type(source) is dict else None
    if status == 'insufficient_claim_evidence':
        return 'insufficient_evidence'
    if status in {'attributed', 'partial'} and source.get('claims'):
        kinds = {claim.get('claim_kind') if type(claim) is dict else None for claim in source['claims']}
        if source.get('content_scope') == 'disclosures_only' and kinds <= DISCLOSURE_ONLY_CLAIM_KINDS:
            return DISCLOSURES_ONLY
        return 'source_bound_claims'
    return 'unclassified'


def _entity_scope(cases_content, registration_case_ids):
    """Registration-only entities and every other case, reported apart and never dropped:
    each case is in exactly one stratum and the strata sum to the denominator. The approved
    targets are still read on the whole denominator (answer_content.coverage)."""
    registration = set(registration_case_ids)
    strata = {}
    for name, rows in (('registration_only', [r for r in cases_content if r['case_id'] in registration]),
                       ('operating_or_other', [r for r in cases_content if r['case_id'] not in registration])):
        tally = Counter(row['content'] for row in rows)
        strata[name] = {'cases': [row['case_id'] for row in rows], 'count': len(rows),
                        'coverage': content_coverage(tally, len(rows))}
    return {'denominator': len(cases_content), 'strata': strata,
            'note': 'every case is in exactly one stratum; the approved targets are read on the whole denominator'}


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
        # Absent from ledgers created before stage abandonments were recorded.
        stage_abandonments = db.execute('SELECT case_run,stage,recorded_ns FROM ordinary_stage_abandonments '
                                        'ORDER BY recorded_ns').fetchall() \
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='ordinary_stage_abandonments'").fetchone() else []
        # Absent from ledgers created before size rejections were recoverable.
        has_size_rejections = bool(db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='ordinary_size_rejections'").fetchone())
        size_rejections = {r[0]: r[1:] for r in db.execute(
            'SELECT attempt_id,case_run,stage,url,limit_bytes,declared_bytes,bytes_read,recorded_ns '
            'FROM ordinary_size_rejections')} if has_size_rejections else {}
        # Absent from ledgers created before stages were timed.
        has_stage_timings = bool(db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='ordinary_stage_timings'").fetchone())
        stage_timings = db.execute('SELECT case_run,task,stage,recorded_ns,thread_cpu_ns FROM ordinary_stage_timings '
                                   'ORDER BY id').fetchall() if has_stage_timings else []
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
    registration_runs = set()  # answers whose declared absence of company facts the run's own evidence proves
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
        # The same rule the ledger applied: own ticker, none, or another ticker the directory this
        # run retained lists under the case's registered CIK.
        retained = sorted((r[5], r[4]) for r in responses.values() if r[0] == DIRECTORY_URL)
        expected = next((r.get('expected_cik') for r in policy.get('case_records', ()) if r.get('case_id') == case_id), None)
        if not answer_names_issuer(case_id, payload.get('company'), expected, retained[0][1] if retained else None):
            raise ExportRefused('answer issuer mismatch')
        try:
            declared = declared_not_applicable(payload)
        except BudgetError:
            raise ExportRefused('malformed not-applicable declaration') from None
        if declared:
            # Re-proved from this case's own retained submissions response, for the CIK it registered,
            # with no facts request ever made; otherwise the export refuses, as the ledger would have halted.
            body = next((responses[a][4] for a, r, route, *_ in attempts if r == run and route == 'sec/submissions'
                         and a in responses and responses[a][0] == submissions_url(expected)), None) if expected else None
            facts = sum(1 for a in attempts if a[1] == run and a[2] == 'sec/facts')
            if not declaration_supported(declared, expected, body, facts):
                raise ExportRefused('registration-only declaration not supported by its own retained evidence')
            registration_runs.add(run)
    if any(row[2] == 'complete' and row[0] not in answers for row in cases):
        raise ExportRefused('completed case without its retained answer')

    # Attempts, quotas, receipts and wire timing.
    case_of = {row[0]: row[1] for row in cases}
    case_start = {row[0]: row[3] for row in cases}
    abandoned_runs, rejected_runs, rejection_records = set(), set(), []
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
        rejection = size_rejections.get(attempt)
        if (status == 'size_rejected') is not (rejection is not None):
            raise ExportRefused('size rejection without its matching attempt')
        if rejection is not None:
            # Stopped at the limit: charged to every quota, closed before the next
            # case began, and nothing of the body retained.
            failure = failures.get(attempt)
            later = [row[3] for row in cases if row[3] > case_start[run]]
            rejected_run, rejected_stage, url, limit_bytes, declared, read, recorded = rejection
            if (response is not None or entered is None or route != 'sec/document' or rejected_run != run
                    or rejected_stage != stage or failure is None or failure[:2] != ('size_rejected', 'response_size')
                    or request_sha != digest({'method': 'GET', 'url': url, 'route': route, 'stage': stage})
                    or not valid_size_rejection(limit_bytes, declared, read, limits)
                    or type(recorded) is not int or recorded < entered or failure[2] != recorded
                    or (later and recorded >= min(later))):
                raise ExportRefused('size rejection without its closed terminal record')
            rejected_runs.add(run)
            rejection_records.append({'case_id': case_id, 'stage': stage, 'url': url, 'limit_bytes': limit_bytes,
                                      'declared_bytes': declared, 'bytes_read': read})
        if entered is not None:
            ended = response[5] if response else (failures[attempt][2] if status in ('abandoned', 'size_rejected') else None)
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
        if status not in ('settled', 'abandoned', 'size_rejected') and not halted:
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

    # A stage the application answered without degrades its case even when the
    # stage's own requests settled; the record must fall inside that case.
    abandoned_stages = []
    for run, stage, recorded in stage_abandonments:
        later = [row[3] for row in cases if run in case_start and row[3] > case_start[run]]
        if (run not in case_start or type(stage) is not str or not stage.startswith('evidence.')
                or type(recorded) is not int or recorded < case_start[run] or (later and recorded >= min(later))):
            raise ExportRefused('stage abandonment outside its recorded case')
        abandoned_runs.add(run)
        abandoned_stages.append({'case_id': case_of[run], 'stage': stage})

    # Every timed stage ended inside its own case: nothing ran on into the next one.
    timing_records = []
    for run, task, stage, recorded, cpu in stage_timings:
        later = [row[3] for row in cases if run in case_start and row[3] > case_start[run]]
        if (run not in case_start or type(recorded) is not int or type(cpu) is not int
                or recorded < case_start[run] or (later and recorded >= min(later))):
            raise ExportRefused('stage timing outside its recorded case')
        timing_records.append({'case_id': case_of[run], 'task': task, 'stage': stage,
                               'offset_ms': round((recorded - run_started) / 1e6, 3),
                               'thread_cpu_ms': round(cpu / 1e6, 3)})

    # An answer that declares itself degraded must have the matching durable
    # record. Answers of consumed runs never declare it, so they are unaffected.
    recorded_stages = {(row['case_id'], row['stage']) for row in abandoned_stages}
    for run, (case_id, _, raw, _) in answers.items():
        try:
            declared = degraded_stages(json.loads(raw))
        except BudgetError:
            raise ExportRefused('degraded answer has invalid evidence gaps') from None
        if any((case_id, stage) not in recorded_stages for stage in declared):
            raise ExportRefused('degraded answer without its ledger record')
        if any(row['case_id'] == case_id and row['stage'] not in declared for row in rejection_records):
            raise ExportRefused('answer does not declare its rejected filing')

    # Twelve outcomes; a halt never turns gaps into passes.
    outcomes = []
    for index, case_id in enumerate(CASES):
        row = next((r for r in cases if r[1] == case_id), None)
        if row is None:
            status = 'not_run_after_halt' if halted else 'not_run'
        elif row[2] == 'complete':
            # An unresolved company is retained and reported, never a pass. An
            # answer missing evidence the application abandoned is degraded.
            payload = json.loads(answers[row[0]][2])
            unresolved = payload.get('company') == ''
            status = ('identity_unresolved' if unresolved else
                      'unanswered_registration_only' if row[0] in registration_runs and _insufficient(payload) else
                      'unanswered_size_rejected' if row[0] in rejected_runs and _insufficient(payload) else
                      'unanswered_evidence_abandoned' if (has_stage_timings and row[0] in abandoned_runs
                                                          and _insufficient(payload)) else
                      'answered_degraded_unadjudicated' if row[0] in abandoned_runs | rejected_runs
                      else 'answered_unadjudicated')
        else:
            status = 'halted'
        outcomes.append({'case_id': case_id, 'status': status})
    complete = not halted and all(o['status'] in {'answered_unadjudicated', 'answered_degraded_unadjudicated',
                                                  'identity_unresolved', 'unanswered_size_rejected',
                                                  'unanswered_evidence_abandoned',
                                                  'unanswered_registration_only'} for o in outcomes)
    kinds = {'answered_unadjudicated': 'full_answer', 'answered_degraded_unadjudicated': 'degraded_answer',
             'identity_unresolved': 'unanswered', 'unanswered_size_rejected': 'unanswered',
             'unanswered_evidence_abandoned': 'unanswered', 'unanswered_registration_only': 'unanswered'}
    outcome_counts = Counter(kinds.get(o['status'], 'operational_failure') for o in outcomes)
    # New ledgers only, so a consumed run's export stays exactly as it was. Its names
    # predate this split: 'answered_unadjudicated' and 'full_answer' mean a case finished
    # operationally with no recorded evidence gap, not that it answered the question.
    content = {}
    if has_size_rejections:
        payloads = {answers[run][0]: json.loads(answers[run][2]) for run in answers}
        cases_content = [{'case_id': o['case_id'], 'content': answer_content(o['status'], payloads.get(o['case_id']))}
                         for o in outcomes]
        tally = Counter(row['content'] for row in cases_content)
        content = {'size_rejections': rejection_records,
                   'answer_content': {'scope': 'delivered content only; accuracy and usefulness are assessed separately',
                                      'cases': cases_content,
                                      'counts': {key: tally.get(key, 0) for key in ANSWER_CONTENT_KINDS},
                                      'coverage': content_coverage(tally, len(cases_content)),
                                      # Only when a case declared (and proved) it: a consumed run's export is unchanged.
                                      **({'entity_scope': _entity_scope(cases_content, [by_run[r][1] for r in registration_runs])}
                                         if registration_runs else {})}}
    first = (dict(zip(('attempt_id', 'route', 'stage', 'code'), first_transport)) if first_transport
             else dict(zip(('attempt_id', 'route', 'stage', 'code'), first_refusal)) if first_refusal else None)
    return {'format': 'ordinary-native-packet-v1', 'synthetic_sec_backend': synthetic,
            'status': 'complete' if complete else 'halted', 'halt': halted,
            'first_failure': first, 'denominator': len(CASES), 'cases': outcomes,
            'outcome_counts': {k: outcome_counts.get(k, 0) for k in
                               ('full_answer', 'degraded_answer', 'unanswered', 'operational_failure')},
            'answers': {answers[run][0]: {'sha256': answers[run][1], 'response': json.loads(answers[run][2])}
                        for run in answers},
            'attempts': records, 'attempt_count': len(records), 'abandoned_stages': abandoned_stages,
            **content, **({'stage_timings': timing_records} if has_stage_timings else {}),
            'retained_body_bytes': aggregate, 'wire_entries': len(entries_seen),
            'quality_pass_rate': None, 'launch_ready': False, 'execution_authorized': False,
            'invoice_ceiling_verified': False}
