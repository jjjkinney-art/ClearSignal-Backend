"""The Option B candidate: separate from every approved contract, and rehearsed.

Rehearsals use the invented SEC backend, the invented approval and the historical
completing cohort, each in a fresh process. Nothing here is real-company evidence
or authority to run a pilot.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from validation.capture_budget import BudgetError
from validation.ordinary_option_b_candidate import candidate_limits, candidate_quota_contract, validate_candidate
from validation import ordinary_native_ledger, ordinary_pilot_contract
from validation.ordinary_native_ledger import degraded_stages
from validation.ordinary_pilot_contract import CASES, quota_contract

ROOT = Path(__file__).resolve().parents[1]


def rehearse(tmp_path, scenario):
    code = ('import json,sys; sys.path.insert(0, %r); '
            'from validation.ordinary_option_b_candidate import run_candidate_rehearsal as r; '
            'print("RESULT"+json.dumps(r(sys.argv[1], scenario=sys.argv[2]), default=str))' % str(ROOT))
    done = subprocess.run([sys.executable, '-c', code, str(tmp_path / scenario), scenario], cwd=ROOT,
                          env={**os.environ, 'ORDINARY_PILOT_COHORT': 'runs-1-2'},
                          capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(next(line[6:] for line in done.stdout.splitlines() if line.startswith('RESULT')))


def rehearse_and_tamper(tmp_path, scenario, sql):
    """A rehearsal, then one ledger edit, then the parent export, in one fresh process."""
    code = ("import json,shutil,sqlite3,sys; sys.path.insert(0, %r); "
            "from pathlib import Path; "
            "from validation.ordinary_option_b_candidate import candidate_limits, run_candidate_rehearsal as r; "
            "from validation.ordinary_native_export import ExportRefused, export_packet; "
            "from validation.ordinary_isolated_rehearsal import rehearsal_policy; "
            "from validation._ordinary_rehearsal_worker import REHEARSAL_RUNTIME; "
            "out=Path(sys.argv[1]); r(out, scenario=sys.argv[2]); "
            "policy=json.loads((out/'request.json').read_text())['policy']; "
            "db=sqlite3.connect(out/'ledger.sqlite'); db.execute(sys.argv[3]); db.commit(); db.close(); "
            "\nwith candidate_limits():\n"
            " try:\n  export_packet(out/'ledger.sqlite', policy, forbidden_values=tuple(REHEARSAL_RUNTIME.values()), synthetic=True); print('RESULTexported')\n"
            " except ExportRefused as exc:\n  print('RESULT'+str(exc))\n" % str(ROOT))
    done = subprocess.run([sys.executable, '-c', code, str(tmp_path / scenario), scenario, sql], cwd=ROOT,
                          env={**os.environ, 'ORDINARY_PILOT_COHORT': 'runs-1-2'},
                          capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stderr[-2000:]
    return next(line[6:] for line in done.stdout.splitlines() if line.startswith('RESULT'))


def test_the_approved_contract_is_unchanged():
    limits = quota_contract()
    assert limits['sec_gets'] == 66 and limits['execution_authorized'] is False
    for case in CASES:
        core = case.endswith(':core_thesis')
        assert limits['per_case'][case] == {'sec': 8 if core else 3, 'sec/directory': 2 if core else 1,
                                            'sec/submissions': 3 if core else 1, 'sec/facts': 1,
                                            'sec/document': 2 if core else 0}
        assert ('evidence.filing_metrics' in limits['per_stage'][case]) is core


def test_the_candidate_is_six_and_five_within_the_same_ceiling():
    limits = validate_candidate(candidate_quota_contract())
    assert limits['sec_gets'] == 66 and limits['execution_authorized'] is False
    assert limits['model_attempts'] == limits['paid_provider_attempts'] == 0
    assert sum(limits['per_case'][case]['sec'] for case in CASES) == 66
    for case in CASES:
        expected = ({'sec': 6, 'sec/directory': 2, 'sec/submissions': 1, 'sec/facts': 1, 'sec/document': 2}
                    if case.endswith(':core_thesis') else
                    {'sec': 5, 'sec/directory': 2, 'sec/submissions': 1, 'sec/facts': 1, 'sec/document': 1})
        assert limits['per_case'][case] == expected
    for other in ('wall_seconds', 'concurrent_sec', 'concurrent_cases', 'body_max_bytes'):
        assert limits[other] == quota_contract()[other]


@pytest.mark.parametrize('change', [lambda l: l.update(execution_authorized=True), lambda l: l.update(sec_gets=67),
                                    lambda l: l['per_case'][CASES[0]].update({'sec/submissions': 3})])
def test_an_altered_candidate_is_refused(change):
    limits = candidate_quota_contract()
    change(limits)
    with pytest.raises(BudgetError):
        validate_candidate(limits)


def test_the_candidate_limits_are_scoped():
    with candidate_limits():
        assert ordinary_native_ledger.quota_contract() == candidate_quota_contract()
    assert ordinary_native_ledger.quota_contract is quota_contract
    assert ordinary_pilot_contract.quota_contract is quota_contract


@pytest.mark.timeout(900)
def test_the_candidate_runs_within_its_limits_and_reuses_submissions(tmp_path):
    result = rehearse(tmp_path, 'happy')
    packet = result['packet']
    assert result['status'] == 'complete' and packet['halt'] is None and packet['first_failure'] is None
    routes = {}
    for attempt in packet['attempts']:
        key = attempt['case_id'], attempt['route']
        routes[key] = routes.get(key, 0) + 1
        assert attempt['status'] == 'settled'
    for case in {a['case_id'] for a in packet['attempts']}:
        assert routes.get((case, 'sec/submissions'), 0) == 1
        assert sum(n for (c, _), n in routes.items() if c == case) <= (6 if case.endswith(':core_thesis') else 5)
    threshold_documents = [k for k in routes if k[1] == 'sec/document' and k[0].endswith(':decision_threshold')]
    assert threshold_documents, 'threshold cases must read the filing'
    assert packet['attempt_count'] <= 66
    assert result['worker']['refused_requests'] == []


@pytest.mark.timeout(900)
def test_a_slow_filing_degrades_the_threshold_answer_inside_its_deadline(tmp_path):
    result = rehearse(tmp_path, 'threshold_filing_slow')
    packet, worker = result['packet'], result['worker']
    assert result['status'] == 'complete' and packet['halt'] is None and packet['first_failure'] is None
    degraded = [c for c in packet['cases'] if c['status'] == 'answered_degraded_unadjudicated']
    target = [c for c in degraded if c['case_id'].endswith(':decision_threshold')]
    assert len(target) >= 1
    case = target[0]['case_id']
    assert {'case_id': case, 'stage': 'evidence.filing_metrics'} in worker['abandoned_evidence']
    abandoned = [a for a in packet['attempts'] if a['case_id'] == case and a['status'] == 'abandoned']
    assert [a['route'] for a in abandoned] == ['sec/document']
    assert all(a['response'] is None and a['failure']['code'] == 'abandoned' for a in abandoned)
    response = packet['answers'][case]['response']
    source = response['answer']['source_answer'] if 'source_answer' in response['answer'] else None
    text = json.dumps(response)
    assert 'Incomplete answer: the latest SEC filing could not be read for this answer' in text
    assert source is None or source['degraded'] is True
    assert packet['quality_pass_rate'] is None


def _cutoff_case(packet):
    degraded = [c['case_id'] for c in packet['cases'] if c['status'] == 'answered_degraded_unadjudicated']
    assert len(degraded) == 1 and degraded[0].endswith(':decision_threshold')
    return degraded[0]


@pytest.mark.timeout(900)
def test_a_filing_past_the_cutoff_is_degraded_in_ledger_export_and_packet(tmp_path):
    result = rehearse(tmp_path, 'threshold_filing_after_cutoff')
    packet, worker = result['packet'], result['worker']
    assert result['status'] == 'complete' and packet['halt'] is None and packet['first_failure'] is None
    case = _cutoff_case(packet)
    # The request finished, so nothing was abandoned on the wire...
    assert worker['abandoned_evidence'] == []
    assert all(a['status'] == 'settled' for a in packet['attempts'])
    assert [a['route'] for a in packet['attempts'] if a['case_id'] == case and a['stage'] == 'evidence.filing_metrics'
            ] == ['sec/document']
    # ...and the case is still degraded everywhere it is reported.
    assert packet['abandoned_stages'] == [{'case_id': case, 'stage': 'evidence.filing_metrics'}]
    assert packet['outcome_counts']['degraded_answer'] == 1 and packet['quality_pass_rate'] is None
    source = packet['answers'][case]['response']['answer']['source_answer']
    assert source['degraded'] is True
    assert source['evidence_gaps'] == [{'source': 'the latest SEC filing', 'task': 'filing_metrics', 'reason': 'not_read'}]
    assert 'Incomplete answer: the latest SEC filing' in json.dumps(packet['answers'][case]['response'])
    with sqlite3.connect(tmp_path / 'threshold_filing_after_cutoff' / 'ledger.sqlite') as db:
        assert db.execute('SELECT c.case_id, s.stage FROM ordinary_stage_abandonments s JOIN cases c ON c.id=s.case_run'
                          ).fetchall() == [(case, 'evidence.filing_metrics')]


@pytest.mark.timeout(900)
def test_export_refuses_a_degraded_answer_without_its_ledger_record(tmp_path):
    assert rehearse_and_tamper(tmp_path, 'threshold_filing_after_cutoff',
                               'DELETE FROM ordinary_stage_abandonments') == 'degraded answer without its ledger record'


def test_an_answer_without_the_declaration_records_nothing():
    # Every answer of every consumed run has this shape.
    for payload in ({'answer': {'source_answer': {'status': 'partial', 'claims': []}}}, {'answer': {}}, {},
                    {'answer': {'source_answer': None}}, {'answer': {'source_answer': {'degraded': False}}}):
        assert degraded_stages(payload) == ()


def test_declared_gaps_map_to_their_stages():
    gaps = [{'task': 'filing_metrics'}, {'task': 'sec_submissions'}, {'task': 'sec'}]
    assert degraded_stages({'answer': {'source_answer': {'degraded': True, 'evidence_gaps': gaps}}}) == (
        'evidence.filing_metrics', 'evidence.sec')


@pytest.mark.parametrize('source', [{'degraded': True}, {'degraded': True, 'evidence_gaps': []},
                                    {'degraded': True, 'evidence_gaps': [{'task': 'invented'}]},
                                    {'degraded': True, 'evidence_gaps': ['filing_metrics']}])
def test_a_malformed_declaration_is_refused(source):
    with pytest.raises(BudgetError):
        degraded_stages({'answer': {'source_answer': source}})
