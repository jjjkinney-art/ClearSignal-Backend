"""The integrated ordinary path in fresh, socket-denied worker processes.

Real application pipeline; native ledger, gate, owned transport and retention;
parent deadlines and read-only export. The SEC backend and every source body are
invented, and the approval is an invented TEST-ONLY record. Nothing here is
real-company research evidence or authority to run a live pilot.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from validation.ordinary_isolated_rehearsal import run_rehearsal
from validation.ordinary_native_export import ExportRefused, export_packet
from validation.ordinary_pilot_contract import contract_profile, CASES, COHORT, COHORT_FILE, FAULT_CASE_INDEX, LAST_CASE, quota_contract
from validation.pilot_live import submission_documents
from validation._ordinary_rehearsal_worker import REHEARSAL_RUNTIME
from _ordinary_cohort_expectations import (REGISTRATION_ONLY_CASES, expected_exchanges, resolved_ticker, attempt_reconciliation_problems, EXPECTED_THESIS_EXCHANGES, EXPECTED_THRESHOLD_EXCHANGES, COMPLETED, EXPECTED_CASE_STATUSES, EXPECTED_HALT, EXPECTED_REFUSED_MODEL_REQUESTS,
                                          EXPECTED_SEC_EXCHANGES, GENERAL_INTENT,
                                          UNRESOLVED)

FORBIDDEN = tuple(REHEARSAL_RUNTIME.values())


@pytest.fixture(scope='module')
def happy(tmp_path_factory):
    output = tmp_path_factory.mktemp('ordinary') / 'happy'
    return run_rehearsal(output, scenario='happy'), output


def no_runtime_values_written(output):
    for path in Path(output).rglob('*'):
        if path.is_file():
            content = path.read_bytes()
            assert not any(value.encode() in content for value in FORBIDDEN), path.name




@pytest.mark.timeout(120)
def test_twelve_cases_run_through_the_integrated_native_path(happy):
    result, output = happy
    packet, worker = result['packet'], result['worker']
    statuses = [c['status'] for c in packet['cases']]
    assert [c['case_id'] for c in packet['cases']] == list(CASES)
    assert packet['first_failure'] is None
    if EXPECTED_HALT is None:
        assert result['status'] == 'complete' and not packet['halt']
        # Every company-analysis question is identified from its text, including
        # "NN INC" (a short registrant name made exact by its legal form); a
        # question the pinned frontend sends as general is counted unresolved.
        assert statuses == EXPECTED_CASE_STATUSES
        assert packet['attempt_count'] == EXPECTED_SEC_EXCHANGES
    else:
        halted_case, reason = EXPECTED_HALT
        assert result['status'] == 'halted' and packet['halt'] == reason
        assert statuses == EXPECTED_CASE_STATUSES and statuses[CASES.index(halted_case)] == 'halted'
        assert packet['attempt_count'] == EXPECTED_SEC_EXCHANGES
        assert halted_case == LAST_CASE and halted_case not in [r['case_id'] for r in worker['routing']]
    # Every SEC exchange: claimed, entered once, retained with its receipt, settled.
    assert packet['attempt_count'] == packet['wire_entries'] == worker['synthetic_requests']
    assert all(a['status'] == 'settled' and a['response'] and a['failure'] is None for a in packet['attempts'])
    per_case = {case: sum(a['case_id'] == case for a in packet['attempts']) for case in COMPLETED}
    assert per_case == {case: expected_exchanges(case) for case in COMPLETED}
    assert packet['attempt_count'] <= quota_contract()['sec_gets']
    # Identity resolution used the routing slot once (first unseen issuer, case
    # one); the pipeline then reused that directory response instead of a GET.
    routing = [a for a in packet['attempts'] if a['stage'] == 'routing']
    assert [(a['case_id'], a['route']) for a in routing] == [(CASES[0], 'sec/directory')]
    assert not [a for a in packet['attempts'] if a['case_id'] == CASES[0] and a['route'] == 'sec/directory'
                and a['stage'] != 'routing']
    # Real /ask routing, zero models, no external operation, nothing left running.
    # Entered with the pinned frontend intent, as production /ask receives it.
    assert [(r['intent'], r['company'], r['pipeline'], r['response_mode']) for r in worker['routing']
            if r['case_id'] in COMPLETED] == [
        ('company_analysis', resolved_ticker(case), 'investment_thesis', 'source_evidence') for case in COMPLETED]
    assert worker['refused_model_requests'] == EXPECTED_REFUSED_MODEL_REQUESTS
    assert worker['blocked_external_operations'] == []
    assert worker['refused_requests'] == [] and worker['unfinished_workers'] == 0
    # Timing-dependent observations: never above four in flight. The export has
    # already re-verified <=10 entries/s and <=4 concurrent from durable times;
    # deterministic slot and pacing behaviour is tested in process.
    assert 1 <= worker['max_inflight_sec'] <= 4
    assert set(worker['pacing']) == {'slot_waits', 'claim_waits', 'wire_entry_waits'}
    assert result['execution_authorized'] is packet['execution_authorized'] is False
    assert packet['quality_pass_rate'] is None and packet['launch_ready'] is False
    assert result['approval'] == 'invented_test_only' and packet['synthetic_sec_backend'] is True
    no_runtime_values_written(output)
    with pytest.raises(FileExistsError):
        run_rehearsal(output, scenario='happy')


@pytest.mark.timeout(120)
def test_every_answer_reference_traces_to_retained_sources_of_its_own_case(happy):
    result, output = happy
    packet = result['packet']
    with sqlite3.connect(output / 'ledger.sqlite') as db:
        bodies = dict(db.execute('SELECT attempt_id,body FROM ordinary_responses'))
    for case in COMPLETED:
        attempts = [a for a in packet['attempts'] if a['case_id'] == case]
        retained = {a['response']['url'] for a in attempts}
        cik = next(c for c in json.loads((Path(__file__).resolve().parents[1] / COHORT_FILE).read_text())
                   if c['case_id'] == case)['expected_cik']
        listed = set()
        for a in attempts:
            if a['route'] == 'sec/submissions':
                data = json.loads(bodies[a['attempt_id']])
                listed |= submission_documents(data, cik)[0]
                # Filing-index pages the application derives from listed accessions.
                listed |= {f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace("-", "")}/{accn}-index.htm'
                           for accn in data['filings']['recent']['accessionNumber']}
        answer = packet['answers'][case]['response']
        assert answer['company'] == resolved_ticker(case)
        urls = {ref['url'] for ref in answer['answer']['evidence_references'] if ref.get('url')}
        if case in REGISTRATION_ONLY_CASES:
            # Nothing was cited and no facts exist: the answer only explains why.
            assert urls <= retained | listed and not answer['answer']['verified_sec_facts'], case
            continue
        assert urls and urls <= retained | listed, case
        # Facts reached the answer path (synthetic values; not research evidence).
        assert answer['answer']['verified_sec_facts'], case


@pytest.mark.timeout(120)
@pytest.mark.parametrize('scenario,case,code', [
    ('wire_read_failure', CASES[FAULT_CASE_INDEX], 'read_error'),
    ('wire_redirect', CASES[FAULT_CASE_INDEX], 'http_redirect'),
    # Under the threshold profile an oversized filing document is recoverable instead:
    # test_ordinary_contract_profile.py::test_an_oversized_filing_degrades_one_answer_and_later_cases_run
    *([] if contract_profile() else [('wire_oversize', CASES[FAULT_CASE_INDEX], 'response_size')]),
    ('wire_oversize_facts', CASES[FAULT_CASE_INDEX], 'response_size'),
    ('wire_connect_failure', None, 'connect_error'),
])
def test_first_failure_halts_and_every_outcome_is_reported(tmp_path, scenario, case, code):
    output = tmp_path / scenario
    result = run_rehearsal(output, scenario=scenario)
    packet = result['packet']
    assert result['status'] == 'halted' and packet['halt'] == 'post_claim_failure'
    assert packet['first_failure']['code'] == code
    statuses = [c['status'] for c in packet['cases']]
    halted = statuses.index('halted')
    if case:
        assert CASES[halted] == case
    assert statuses == EXPECTED_CASE_STATUSES[:halted] + ['halted'] + ['not_run_after_halt'] * (11 - halted)
    assert set(packet['answers']) == set(CASES[:halted])
    failed = [a for a in packet['attempts'] if a['failure']]
    assert failed and all(a['response'] is None and a['status'] != 'settled' for a in failed)
    assert any(a['failure'] == {'code': 'transport', 'detail': code} for a in failed)
    no_runtime_values_written(output)


@pytest.mark.parametrize('scenario,index,limit', [('core_deadline', FAULT_CASE_INDEX, 30),
                                                  ('threshold_deadline', FAULT_CASE_INDEX + 1, 20)])
@pytest.mark.timeout(90)
def test_parent_kills_a_stalled_case_and_exports_from_the_durable_ledger(tmp_path, scenario, index, limit):
    result = run_rehearsal(tmp_path / scenario, scenario=scenario)
    supervisor, packet = result['supervisor'], result['packet']
    assert result['status'] == 'worker_stopped' and result['worker'] is None
    assert supervisor['stop_reason'] == 'case_deadline' and supervisor['returncode'] < 0
    assert supervisor['interrupted_case'] == CASES[index] and supervisor['finished_case_scopes'] == index
    assert limit <= supervisor['case_elapsed_seconds'] < limit + 5
    assert packet['halt'] == 'stage_timeout'
    assert [c['status'] for c in packet['cases']] == (
        EXPECTED_CASE_STATUSES[:index] + ['halted'] + ['not_run_after_halt'] * (11 - index))
    assert set(packet['answers']) == set(CASES[:index])


# -- parent export refuses inconsistent records ------------------------------------

def tampered(happy, tmp_path, sql, *params):
    result, output = happy
    copy = tmp_path / 'ledger.sqlite'
    shutil.copyfile(output / 'ledger.sqlite', copy)
    with sqlite3.connect(copy) as db:
        db.execute(sql, params)
    return copy, json.loads((output / 'request.json').read_text())['policy']


@pytest.mark.timeout(120)
@pytest.mark.parametrize('sql', [
    "UPDATE ordinary_responses SET body=body||x'20' WHERE rowid=1",                       # body re-typed
    "UPDATE ordinary_responses SET body=CAST(body||x'20' AS BLOB) WHERE rowid=1",         # body changed
    "UPDATE attempts SET request_sha256=substr(request_sha256,2)||'0' WHERE rowid=1",      # receipt mismatch
    "DELETE FROM ordinary_wire_entries WHERE rowid=1",                                    # no wire entry
    "DELETE FROM native_dispatches WHERE rowid=1",                                        # no native intent
    "UPDATE ordinary_wire_entries SET entered_ns=(SELECT MIN(entered_ns) FROM ordinary_wire_entries)",  # rate
    "UPDATE ordinary_responses SET completed_ns=completed_ns+60000000000",               # concurrency
    "DELETE FROM ordinary_answers WHERE rowid=1",                                         # answer missing
    "UPDATE ordinary_answers SET payload=CAST('{\"company\":\"NPK\"}' AS BLOB) WHERE rowid=1",  # answer hash
    "UPDATE ordinary_case_times SET started_ns=started_ns-3600000000000 WHERE rowid=2",  # order
    "UPDATE ordinary_responses SET http_status=302 WHERE rowid=1",                       # status
])
def test_parent_export_refuses_inconsistent_ledgers(happy, tmp_path, sql):
    copy, policy = tampered(happy, tmp_path, sql)
    with pytest.raises((ExportRefused, sqlite3.IntegrityError)):
        export_packet(copy, policy, forbidden_values=FORBIDDEN, synthetic=True)


@pytest.mark.timeout(120)
def test_parent_export_refuses_a_different_policy(happy, tmp_path):
    copy, policy = tampered(happy, tmp_path, 'SELECT 1')
    policy['retention_reference'] = 'TEST-ONLY-changed'
    with pytest.raises(ExportRefused):
        export_packet(copy, policy, forbidden_values=FORBIDDEN, synthetic=True)
    policy = json.loads((happy[1] / 'request.json').read_text())['policy']
    expected = 'complete' if EXPECTED_HALT is None else 'halted'
    assert export_packet(copy, policy, forbidden_values=FORBIDDEN, synthetic=True)['status'] == expected


@pytest.mark.timeout(120)
@pytest.mark.parametrize('field', ['source_sha256', 'ca_sha256'])
def test_worker_refuses_a_policy_that_does_not_match_the_running_configuration(tmp_path, monkeypatch, field):
    from validation import ordinary_isolated_rehearsal as launcher
    from validation.ordinary_native_policy import execution_package, policy_for
    from validation.capture_budget import digest
    real = launcher.rehearsal_policy

    def mismatched(output):
        policy = real(output)
        values = dict(cases=policy['case_records'], code_binding=dict(policy['code_binding']),
                      dependencies=policy['dependencies'], execution=json.loads(json.dumps(policy['execution_configuration'])),
                      all_in_usd=policy['budget_usd'], retention_reference=policy['retention_reference'],
                      pricing_review_reference=policy['pricing_review_reference'])
        if field == 'source_sha256':
            values['code_binding']['source_sha256'] = '0' * 64   # not the code that will run
        else:
            values['execution']['ca_identity']['sha256'] = '0' * 64  # not the CA file present
        approval = dict(policy['approval'], manifest_sha256=digest(execution_package(output_dir=str(output), **values)))
        return policy_for(approval=approval, **values)
    monkeypatch.setattr(launcher, 'rehearsal_policy', mismatched)
    output = tmp_path / field
    result = run_rehearsal(output, scenario='happy')
    assert result['status'] == 'worker_incomplete' and result['packet'] is None
    assert result['cases'] == [{'case_id': case, 'status': 'not_run'} for case in CASES]
    assert result['supervisor']['returncode'] != 0 and result['supervisor']['finished_case_scopes'] == 0
    assert not (output / 'ledger.sqlite').exists()  # refused before any ledger, gate or request


# Scenarios that exist only on a fully completing run; run 3 halts at its
# eleventh case by design. They run in the runs-1-2 cohort process
# (tests/test_ordinary_historical_cohort.py), never silently skipped there.
COMPLETING_COHORT_ONLY = pytest.mark.skipif(
    EXPECTED_HALT is not None, reason='needs a completing cohort; run by test_ordinary_historical_cohort.py')


@COMPLETING_COHORT_ONLY
@pytest.mark.timeout(120)
def test_an_answer_the_parent_ruled_late_is_never_exported(tmp_path, monkeypatch):
    """The child may commit a case just after the parent's deadline fired (its
    clock starts after the acknowledgment). The parent's ruling wins."""
    from validation import ordinary_isolated_rehearsal as launcher
    real = launcher.supervise

    def late_at_last_case(*args, **kwargs):
        child = real(*args, **kwargs)
        return dict(child, stop_reason='case_deadline', interrupted_case=CASES[-1], finished_case_scopes=11)
    monkeypatch.setattr(launcher, 'supervise', late_at_last_case)
    result = run_rehearsal(tmp_path / 'late', scenario='happy')
    packet = result['packet']
    assert result['status'] == 'worker_stopped' and packet['status'] == 'halted' and result['worker'] is None
    assert packet['cases'][-1] == {'case_id': CASES[-1], 'status': 'halted'}
    assert CASES[-1] not in packet['answers'] and packet['late_answers_rejected'] == [CASES[-1]]
    assert set(packet['answers']) == set(CASES[:-1])


@pytest.mark.timeout(60)
def test_parent_rolls_back_a_killed_childs_open_transaction_before_export(tmp_path):
    """A child killed inside a write transaction leaves a hot journal. The
    parent's stop record rolls it back; the read-only export never sees the
    uncommitted answer, and the case remains an explicit halted gap."""
    import signal
    import subprocess
    import sys
    from validation.ordinary_isolated_rehearsal import rehearsal_policy
    from validation.ordinary_native_export import record_parent_stop
    from validation.ordinary_native_ledger import OrdinaryNativeLedger, create_fresh_output
    output = tmp_path / 'run'
    create_fresh_output(output)
    policy = rehearsal_policy(output)
    book = OrdinaryNativeLedger(output / 'ledger.sqlite', policy, create=True)
    run = book.begin_case(CASES[0])
    code = (
        'import sqlite3, time\n'
        f'db = sqlite3.connect({str(output / "ledger.sqlite")!r}, isolation_level=None, timeout=10)\n'
        'db.execute("BEGIN IMMEDIATE")\n'
        f'db.execute("INSERT INTO ordinary_answers VALUES (?,?,?,?,?)", ({run!r}, {CASES[0]!r}, "0"*64, b"{{}}", 1))\n'
        f'db.execute("UPDATE cases SET status=\'complete\' WHERE id=?", ({run!r},))\n'
        'db.execute("PRAGMA cache_size=1")\n'
        'for i in range(2000): db.execute("INSERT INTO ordinary_wire_entries VALUES (?,?)", ("pad-%d" % i, i))\n'
        'print("ready", flush=True); time.sleep(60)\n')
    child = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'ready'
        assert (output / 'ledger.sqlite-journal').exists()
    finally:
        child.send_signal(signal.SIGKILL)
        child.wait()
    record_parent_stop(output / 'ledger.sqlite', 'stage_timeout')
    assert not (output / 'ledger.sqlite-journal').exists()
    packet = export_packet(output / 'ledger.sqlite', policy, forbidden_values=FORBIDDEN, synthetic=True)
    assert packet['halt'] == 'stage_timeout' and packet['answers'] == {} and packet['wire_entries'] == 0
    assert packet['cases'][0] == {'case_id': CASES[0], 'status': 'halted'}
    assert [c['status'] for c in packet['cases'][1:]] == ['not_run_after_halt'] * 11


def test_pinned_frontend_intents_cover_the_cohort_and_reach_company_research():
    from app.services.company_detection import intent_allows_company_detection
    from validation.ordinary_frontend_intents import CASE_INTENTS, FRONTEND, FRONTEND_INTENTS, frontend_intent
    cases = json.loads((Path(__file__).resolve().parents[1] / COHORT_FILE).read_text())
    # The intents were classified from exactly these question texts, in this order.
    assert [c['case_id'] for c in cases] == list(CASE_INTENTS) == list(CASES)
    questions = json.dumps([c['question'] for c in cases]).encode()
    assert hashlib.sha256(questions).hexdigest() == FRONTEND['questions_sha256']
    assert set(CASE_INTENTS.values()) <= FRONTEND_INTENTS
    # A general intent is authoritative in the backend and routes away from
    # research. The deployed frontend (138d646, PR #90) sends none for runs 1-5; at
    # 84466b2 it sent BNY:core_thesis as general (run 5), and at 5ee51c3 BWMX:core_thesis (run 3).
    # Cohort 5 (run 10) is bound to the deployed "/ADR" fix; every consumed cohort keeps 138d646.
    commit, classifier = (('77c33bbbb0c530e01f74b0d51502fabdf6d1ce12',
                           '9f8b1e87fc9f9353bc2c53d9ee0768596b9d6fb54d100074d6381e5540dd340a') if COHORT == 'run10' else
                          ('138d6461a7d6822fd9b27c784a410f55b243a40e',
                           '6ef10de383a75628b72bda552b624489992c84730e43ee884f56a4bc6dc1df38'))
    assert FRONTEND['commit'] == commit
    assert FRONTEND['classifier_sha256'] == classifier
    assert FRONTEND['resolver_sha256'] == '6fa4e195816df8c09a6439c86fb4c41d3a9d60990745cb877f492a5d7dd38542'
    general = [case for case in CASES if not intent_allows_company_detection(frontend_intent(case))]
    assert general == []
    # Such a case halts the run (zero-model refusal), so it is ordered last.
    assert general == GENERAL_INTENT and all(CASES.index(case) == len(CASES) - 1 for case in general)
    assert not intent_allows_company_detection('investing_education')


# -- graceful degradation at the application's evidence timeout --------------------

@pytest.fixture(scope='module')
def degraded(tmp_path_factory):
    output = tmp_path_factory.mktemp('ordinary') / 'degraded'
    return run_rehearsal(output, scenario='evidence_abandoned'), output


@COMPLETING_COHORT_ONLY
@pytest.mark.timeout(180)
def test_an_abandoned_evidence_request_degrades_one_answer_without_halting(degraded):
    result, output = degraded
    packet, worker = result['packet'], result['worker']
    assert result['status'] == 'complete' and packet['halt'] is None and packet['first_failure'] is None
    statuses = [c['status'] for c in packet['cases']]
    # The application says whether anything was left to answer with once this evidence was gone.
    fault_source = packet['answers'][CASES[FAULT_CASE_INDEX]]['response']['answer']['source_answer']
    insufficient = fault_source['status'] == 'insufficient_claim_evidence'
    degraded_statuses = {'answered_degraded_unadjudicated', 'unanswered_evidence_abandoned'}
    assert len(statuses) == 12 and statuses[FAULT_CASE_INDEX] == (
        'unanswered_evidence_abandoned' if insufficient else 'answered_degraded_unadjudicated')
    # Other cases are full answers, unless the application's own 10 s window
    # also expired for them under load; then they too are degraded, never failed.
    # A case the pinned frontend sends as general is unanswered, as in production.
    assert [s for s, case in zip(statuses, CASES) if case in UNRESOLVED] == ['identity_unresolved'] * len(UNRESOLVED)
    assert [s for s, case in zip(statuses, CASES) if case in REGISTRATION_ONLY_CASES] == ['unanswered_registration_only'] * len(REGISTRATION_ONLY_CASES)
    assert {s for s, case in zip(statuses, CASES) if case not in UNRESOLVED and case not in REGISTRATION_ONLY_CASES} <= {
        'answered_unadjudicated', *degraded_statuses}
    counts = packet['outcome_counts']
    assert counts['unanswered'] == len(UNRESOLVED) + len(REGISTRATION_ONLY_CASES) + statuses.count('unanswered_evidence_abandoned')
    assert counts['operational_failure'] == 0
    assert sum(counts.values()) == 12
    assert counts['degraded_answer'] == statuses.count('answered_degraded_unadjudicated')
    assert sum(status in degraded_statuses for status in statuses) >= 1
    assert packet['quality_pass_rate'] is None  # a degraded answer is never a pass
    # Every request counted, within quota, with a terminal outcome; abandoned ones never retained.
    # A stage abandoned between reservation and wire entry leaves an attempt with no wire entry.
    assert attempt_reconciliation_problems(packet, quota_contract()) == []
    # Nothing reached the network without a durable wire entry.
    assert worker['synthetic_requests'] <= packet['wire_entries'] <= packet['attempt_count'] <= 66
    abandoned = [a for a in packet['attempts'] if a['status'] == 'abandoned']
    assert (CASES[FAULT_CASE_INDEX], 'evidence.sec_metrics', 'sec/facts') in {
        (a['case_id'], a['stage'], a['route']) for a in abandoned}
    assert all(a['failure'] == {'code': 'abandoned', 'detail': a['route']} and a['response'] is None
               for a in abandoned)
    degraded_cases = {case for case, status in zip(CASES, statuses) if status in degraded_statuses}
    assert {a['case_id'] for a in abandoned} == degraded_cases
    assert {'case_id': CASES[FAULT_CASE_INDEX], 'stage': 'evidence.sec_metrics'} in worker['abandoned_evidence']
    assert worker['blocked_external_operations'] == [] and worker['unfinished_workers'] == 0
    assert 1 <= worker['max_inflight_sec'] <= 4


@pytest.mark.timeout(180)
def test_the_abandoned_response_never_reaches_the_answer_and_closes_before_the_next_case(degraded):
    result, output = degraded
    packet = result['packet']
    cik = next(c for c in json.loads((Path(__file__).resolve().parents[1] / COHORT_FILE).read_text())
               if c['case_id'] == CASES[FAULT_CASE_INDEX])['expected_cik']
    facts_url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
    answer = packet['answers'][CASES[FAULT_CASE_INDEX]]['response']
    assert facts_url not in json.dumps(answer)
    with sqlite3.connect(output / 'ledger.sqlite') as db:
        assert not db.execute('SELECT 1 FROM ordinary_responses r JOIN attempts a ON a.id=r.attempt_id '
                              "JOIN cases c ON c.id=a.case_run WHERE c.case_id=? AND r.url=?",
                              (CASES[FAULT_CASE_INDEX], facts_url)).fetchone()
        closed = db.execute("SELECT c.case_id, f.recorded_ns FROM ordinary_exchange_failures f JOIN attempts a "
                            "ON a.id=f.attempt_id JOIN cases c ON c.id=a.case_run WHERE a.status='abandoned'").fetchall()
        starts = dict(db.execute("SELECT c.case_id, t.started_ns FROM ordinary_case_times t "
                                 "JOIN cases c ON c.id=t.case_run"))
    # Each abandoned request was closed before the next case began.
    assert closed and all(recorded < starts[CASES[CASES.index(case) + 1]]
                          for case, recorded in closed if case != CASES[-1])


@pytest.mark.timeout(180)
@pytest.mark.parametrize('sql', [
    "DELETE FROM ordinary_exchange_failures WHERE code='abandoned'",                       # no terminal record
    "UPDATE ordinary_exchange_failures SET code='interrupted' WHERE code='abandoned'",     # wrong outcome
    "UPDATE ordinary_exchange_failures SET recorded_ns=recorded_ns+3600000000000 WHERE code='abandoned'",  # closed late
])
def test_parent_export_refuses_an_inconsistent_abandonment(degraded, tmp_path, sql):
    copy, policy = tampered(degraded, tmp_path, sql)
    with pytest.raises((ExportRefused, sqlite3.IntegrityError)):
        export_packet(copy, policy, forbidden_values=FORBIDDEN, synthetic=True)


# -- an evidence stage abandoned after its own requests settled ----------------

_STAGE_ABANDONED = ("INSERT INTO ordinary_stage_abandonments SELECT c.id, ?, t.started_ns + {offset} "
                    "FROM cases c JOIN ordinary_case_times t ON t.case_run = c.id WHERE c.case_id = ?")


@pytest.mark.timeout(120)
def test_a_stage_answered_without_degrades_its_case_even_when_its_requests_settled(happy, tmp_path):
    # Run 4: the application gave up on a filing-metrics stage after its 10-Q
    # request had completed; the answer lacked that evidence but counted as full.
    case = next(c for c in COMPLETED if c.endswith(':core_thesis'))
    copy, policy = tampered(happy, tmp_path, _STAGE_ABANDONED.format(offset=1), 'evidence.filing_metrics', case)
    with sqlite3.connect(copy) as db:
        assert not db.execute("SELECT 1 FROM attempts WHERE status='abandoned'").fetchone()
    packet = export_packet(copy, policy, forbidden_values=FORBIDDEN, synthetic=True)
    statuses = {c['case_id']: c['status'] for c in packet['cases']}
    assert statuses[case] == 'answered_degraded_unadjudicated'
    assert packet['abandoned_stages'] == [{'case_id': case, 'stage': 'evidence.filing_metrics'}]
    assert packet['outcome_counts']['degraded_answer'] == 1 and packet['quality_pass_rate'] is None
    # Without the record the same ledger exports the case as a full answer.
    assert happy[0]['packet']['abandoned_stages'] == []


@pytest.mark.timeout(120)
@pytest.mark.parametrize('stage,offset', [
    ('evidence.filing_metrics', -1),                 # recorded before its case began
    ('evidence.filing_metrics', 3600000000000),      # recorded after the next case began
    ('synthesis', 1),                                # not an evidence stage
])
def test_parent_export_refuses_a_stage_abandonment_outside_its_case(happy, tmp_path, stage, offset):
    copy, policy = tampered(happy, tmp_path, _STAGE_ABANDONED.format(offset=offset), stage, COMPLETED[0])
    with pytest.raises(ExportRefused):
        export_packet(copy, policy, forbidden_values=FORBIDDEN, synthetic=True)


def _vbrey_core():
    return 'VBREY:core_thesis'


@pytest.mark.timeout(120)
@pytest.mark.parametrize('sql', [
    # The declared evidence no longer matches what the retained filing list proves.
    "UPDATE ordinary_answers SET payload=CAST(replace(replace(CAST(payload AS TEXT), '\"filings_listed\": 9', '\"filings_listed\": 8'), "
    "'\"filings_listed\":9', '\"filings_listed\":8') AS BLOB) WHERE case_id='VBREY:core_thesis'",
    # The retained filing list itself is altered (no longer a registration-only registrant).
    "UPDATE ordinary_responses SET body=CAST(replace(replace(CAST(body AS TEXT), '\"isXBRL\": [0', '\"isXBRL\": [1'), "
    "'\"isXBRL\":[0', '\"isXBRL\":[1') AS BLOB) WHERE attempt_id IN (SELECT a.id FROM attempts a JOIN cases c ON a.case_run=c.id "
    "WHERE c.case_id='VBREY:core_thesis' AND a.route='sec/submissions')",
])
def test_parent_export_refuses_a_registration_only_declaration_the_retained_evidence_does_not_prove(happy, tmp_path, sql):
    if not REGISTRATION_ONLY_CASES:
        pytest.skip('no registration-only case in this cohort')
    copy, policy = tampered(happy, tmp_path, sql)
    with pytest.raises((ExportRefused, sqlite3.IntegrityError)):
        export_packet(copy, policy, forbidden_values=FORBIDDEN, synthetic=True)
