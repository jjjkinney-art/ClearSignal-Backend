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
