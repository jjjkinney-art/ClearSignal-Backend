import base64
import hashlib

import pytest

from validation.ordinary_offline_runner import run_fixture_cohort
from validation.ordinary_pilot_contract import CASES


def test_twelve_case_fixture_run_exports_every_body_and_preserves_gaps(tmp_path):
    result = run_fixture_cohort(tmp_path / 'fresh.db')
    packet = result['packet']
    assert result['fixture_only'] and not result['application_answers']
    assert result['failure_class'] is None and packet['denominator'] == 12
    assert [r['case_id'] for r in packet['cases']] == list(CASES)
    assert all(r['status'] == 'partial_gap' for r in packet['cases'])
    assert len(packet['answers']) == len(packet['attempts']) == 12
    for record in packet['attempts']:
        raw = base64.b64decode(record['body_base64'], validate=True)
        assert hashlib.sha256(raw).hexdigest() == record['body_sha256']
        assert record['http_status'] == 200 and record['route'] == 'sec/facts'
    assert packet['quality_pass_rate'] is None and not packet['launch_ready']


@pytest.mark.parametrize('fault', ['wire_connect_failure', 'wire_redirect', 'wire_read_failure'])
def test_fault_stops_cohort_and_preserves_all_denominator_rows(tmp_path, fault):
    result = run_fixture_cohort(tmp_path / 'fresh.db', fault_case=CASES[2], fault=fault)
    packet = result['packet']; statuses = [r['status'] for r in packet['cases']]
    assert statuses == ['partial_gap', 'partial_gap', 'halted'] + ['not_run_after_halt'] * 9
    assert len(packet['attempts']) == 3 and len(packet['answers']) == 2
    assert packet['attempts'][-1]['outcome'] == 'failure'
    assert packet['attempts'][-1]['http_status'] is None
    assert result['failure_class'] and not result['execution_authorized']


def test_reuse_refused_and_fault_validation_precedes_file_creation(tmp_path):
    path = tmp_path / 'fresh.db'
    with pytest.raises(ValueError): run_fixture_cohort(path, fault_case='unknown')
    assert not path.exists()
    run_fixture_cohort(path)
    with pytest.raises(FileExistsError): run_fixture_cohort(path)
