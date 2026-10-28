"""The integrated ordinary path in fresh, socket-denied worker processes.

Real application pipeline; native ledger, gate, owned transport and retention;
parent deadlines and read-only export. The SEC backend and every source body are
invented, and the approval is an invented TEST-ONLY record. Nothing here is
real-company research evidence or authority to run a live pilot.
"""
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from validation.ordinary_isolated_rehearsal import run_rehearsal
from validation.ordinary_native_export import ExportRefused, export_packet
from validation.ordinary_pilot_contract import CASES, quota_contract
from validation.pilot_live import submission_documents
from validation._ordinary_rehearsal_worker import REHEARSAL_RUNTIME

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
    assert result['status'] == 'complete' and not packet['halt'] and packet['first_failure'] is None
    # The frontend-shaped /ask cannot resolve "NN INC" (NNBR's SEC registrant
    # name) from question text: both cases are retained as explicit gaps.
    unresolved = {'NNBR:core_thesis', 'NNBR:decision_threshold'}
    assert [c['status'] for c in packet['cases']] == [
        'identity_unresolved' if case in unresolved else 'answered_unadjudicated' for case in CASES]
    assert [c['case_id'] for c in packet['cases']] == list(CASES)
    # Every SEC exchange: claimed, entered once, retained with its receipt, settled.
    assert packet['attempt_count'] == packet['wire_entries'] == worker['synthetic_requests'] == 50
    assert all(a['status'] == 'settled' and a['response'] and a['failure'] is None for a in packet['attempts'])
    per_case = {case: sum(a['case_id'] == case for a in packet['attempts']) for case in CASES}
    assert per_case == {case: 0 if case in unresolved else (7 if case.endswith(':core_thesis') else 3)
                        for case in CASES}
    assert sum(per_case.values()) <= quota_contract()['sec_gets']
    # Identity resolution used the routing slot once (first unseen issuer, case
    # one); the pipeline then reused that directory response instead of a GET.
    routing = [a for a in packet['attempts'] if a['stage'] == 'routing']
    assert [(a['case_id'], a['route']) for a in routing] == [('NPK:core_thesis', 'sec/directory')]
    assert not [a for a in packet['attempts'] if a['case_id'] == 'NPK:core_thesis' and a['route'] == 'sec/directory'
                and a['stage'] != 'routing']
    # Real /ask routing, zero models, no external operation, nothing left running.
    assert {(r['pipeline'], r['response_mode']) for r in worker['routing'] if r['case_id'] not in unresolved} == {
        ('investment_thesis', 'source_evidence')}
    assert {(r['company'], r['pipeline']) for r in worker['routing'] if r['case_id'] in unresolved} <= {
        ('', 'entity_suggestion'), ('', 'company_identity_clarification')}
    assert worker['refused_model_requests'] == 0 and worker['blocked_external_operations'] == []
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
    for case in CASES:
        attempts = [a for a in packet['attempts'] if a['case_id'] == case]
        retained = {a['response']['url'] for a in attempts}
        cik = next(c for c in json.loads(Path(__file__).with_name('ordinary_pilot_cases.json').read_text())
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
        if answer['company'] == '':  # identity unresolved: no SEC source was requested
            assert not attempts and case.startswith('NNBR:')
            continue
        assert answer['company'] == case.split(':')[0]
        urls = {ref['url'] for ref in answer['answer']['evidence_references'] if ref.get('url')}
        assert urls and urls <= retained | listed, case
        # Facts reached the answer path (synthetic values; not research evidence).
        assert answer['answer']['verified_sec_facts'], case


@pytest.mark.timeout(120)
@pytest.mark.parametrize('scenario,case,code', [
    ('wire_read_failure', 'INGR:core_thesis', 'read_error'),
    ('wire_redirect', 'INGR:core_thesis', 'http_redirect'),
    ('wire_oversize', 'INGR:core_thesis', 'response_size'),
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
    assert statuses == ['answered_unadjudicated'] * halted + ['halted'] + ['not_run_after_halt'] * (11 - halted)
    assert set(packet['answers']) == set(CASES[:halted])
    failed = [a for a in packet['attempts'] if a['failure']]
    assert failed and all(a['response'] is None and a['status'] != 'settled' for a in failed)
    assert any(a['failure'] == {'code': 'transport', 'detail': code} for a in failed)
    no_runtime_values_written(output)


@pytest.mark.parametrize('scenario,index,limit', [('core_deadline', 4, 30), ('threshold_deadline', 5, 20)])
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
        ['answered_unadjudicated'] * index + ['halted'] + ['not_run_after_halt'] * (11 - index))
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
    assert export_packet(copy, policy, forbidden_values=FORBIDDEN, synthetic=True)['status'] == 'complete'


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
    assert result['supervisor']['returncode'] != 0 and result['supervisor']['finished_case_scopes'] == 0
    assert not (output / 'ledger.sqlite').exists()  # refused before any ledger, gate or request
