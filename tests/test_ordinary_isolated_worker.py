"""Actual application workers in fresh, socket-denied processes."""
import sqlite3

import pytest

from validation.ordinary_isolated_rehearsal import run_rehearsal
from validation.ordinary_pilot_contract import CASES


@pytest.mark.parametrize('scenario', ['happy', 'wire_connect_failure', 'wire_read_failure'])
def test_fresh_application_worker_retains_answers_and_stops_on_failure(tmp_path, scenario):
    output = tmp_path / scenario
    result = run_rehearsal(output, scenario=scenario)
    assert result.get('status') != 'worker_incomplete'
    assert result['network_attempts'] == result['external_requests'] == result['unfinished_workers'] == 0
    assert not result['execution_authorized']
    packet = result['packet']
    assert packet['denominator'] == 12 and not packet['launch_ready']
    assert packet['quality_pass_rate'] is None and packet['synthetic_only']
    assert [row['case_id'] for row in packet['cases']] == list(CASES)
    assert result['tracked_workers'] > 0
    if scenario == 'happy':
        assert not result['result']['failure_class'] and not packet['halt']
        assert set(packet['answers']) == set(CASES)
        assert len(packet['attempts']) == 60
        assert all(a['outcome'] == 'success' for a in packet['attempts'])
        assert all(c['status'] == 'partial_gap' for c in packet['cases'])
        assert result['tracked_workers'] == 108
    else:
        assert result['result']['failure_class'] and packet['halt']
        assert set(packet['answers']) == set(CASES[:2])
        assert [c['status'] for c in packet['cases']] == ['partial_gap'] * 2 + ['halted'] + ['not_run_after_halt'] * 9
    with sqlite3.connect(output / 'ledger.sqlite') as db:
        assert db.execute("SELECT COUNT(*) FROM attempts WHERE outcome='pending'").fetchone()[0] == 0
        successes = db.execute("SELECT COUNT(*) FROM attempts WHERE outcome='success'").fetchone()[0]
        assert db.execute('SELECT COUNT(*) FROM bodies').fetchone()[0] == successes
        assert db.execute('SELECT COUNT(*) FROM fixture_receipts').fetchone()[0] == successes
    with pytest.raises(FileExistsError):
        run_rehearsal(output, scenario=scenario)


@pytest.mark.parametrize('scenario,index,limit', [('core_deadline', 2, 30), ('threshold_deadline', 3, 20)])
@pytest.mark.timeout(55)
def test_parent_kills_stalled_pipeline_thread_at_case_deadline(tmp_path, scenario, index, limit):
    output = tmp_path / scenario
    result = run_rehearsal(output, scenario=scenario)
    assert result['status'] == 'worker_stopped' and 'packet' not in result
    assert not result['execution_authorized']
    supervisor = result['supervisor']
    assert result['denominator'] == 12 and result['quality_pass_rate'] is None and not result['launch_ready']
    assert [c['status'] for c in result['cases']] == ['partial_gap'] * index + ['halted'] + ['not_run_after_halt'] * (11-index)
    assert supervisor['stop_reason'] == 'case_deadline'
    assert supervisor['interrupted_case'] == CASES[index]
    assert supervisor['finished_case_scopes'] == index
    assert supervisor['returncode'] < 0  # killed and reaped, including its threads
    assert limit <= supervisor['elapsed_seconds'] < limit + 20
    assert limit <= supervisor['case_elapsed_seconds'] < limit + 5
    with sqlite3.connect(output / 'ledger.sqlite') as db:
        answers = {row[0] for row in db.execute('SELECT case_id FROM retained_answers')}
    assert answers == set(CASES[:index])
