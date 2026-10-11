import copy
import json

import pytest

from scripts import benchmark_company_quality_review as cli
from validation.company_quality_matrix import build_matrix, capture_matrix
from validation.company_quality_review import reconcile_captures
from validation.intelligence_benchmark import BenchmarkContractError, content_hash


def fixture():
    kwargs = dict(tickers=['AAPL', 'AA', 'ACHC'], families=['core_thesis', 'financial_trends'])
    plan = build_matrix(**kwargs)
    batch = capture_matrix(**kwargs, execute=True, limit=2,
                           runner=lambda *a: {'answer': {'text': 'Unreviewed answer', 'citations': ['source']}})
    return plan, batch


def test_missing_failed_and_unexecuted_cases_stay_in_denominator():
    plan, batch = fixture()
    kwargs = dict(tickers=['AAPL', 'AA', 'ACHC'], families=['core_thesis', 'financial_trends'])
    def failed(*a): raise RuntimeError('private message')
    failures = capture_matrix(**kwargs, execute=True, offset=2, limit=1, runner=failed)
    dry = capture_matrix(**kwargs, offset=3, limit=1)
    result = reconcile_captures(plan, [batch, failures, dry])
    assert result['capture_counts'] == {'captured': 2, 'execution_failed': 1, 'not_executed': 1, 'missing': 2}
    assert result['case_count'] == 6
    assert sum(sum(x.values()) for x in result['capture_by_market_cap'].values()) == 6
    assert sum(sum(x.values()) for x in result['capture_by_question_family'].values()) == 6
    assert result['quality_pass_rate'] is None and result['launch_ready'] is False
    assert all(row['citation_review_status'] == 'pending' for row in result['cases'])
    assert 'private message' not in json.dumps(result)
    assert result['cases'][0]['response'] == batch['cases'][0]['response']
    assert result['provenance_status'] == 'build_and_execution_provenance_unavailable'


def test_identical_overlap_deduplicated_and_conflicting_capture_rejected():
    plan, batch = fixture()
    result = reconcile_captures(plan, [batch, copy.deepcopy(batch)])
    assert result['capture_counts']['captured'] == 2
    assert result['cases'][0]['source_batch_indexes'] == [0, 1]
    changed = copy.deepcopy(batch)
    changed['cases'][0]['response']['answer']['text'] = 'different answer'
    changed['cases'][0]['response_sha256'] = content_hash(changed['cases'][0]['response'])
    with pytest.raises(BenchmarkContractError, match='overlapping'):
        reconcile_captures(plan, [batch, changed])


@pytest.mark.parametrize('key,value', [
    ('offset', True), ('offset', -1), ('offset', 6), ('selected_case_count', True),
    ('selected_case_count', 21), ('selected_case_count', 1), ('next_offset', 3),
    ('batch_complete', 1), ('execution_enabled', 1), ('execution_enabled', False),
    ('registry_sha256', 'bad'), ('matrix_sha256', 'bad'), ('run_id', 'bad'),
    ('quality_pass_rate', 1.0), ('launch_ready', True), ('capture_counts', {}),
    ('capture_by_market_cap', {}), ('capture_by_question_family', {}),
    ('capture_safety', {}), ('quality_status', 'passed'),
    ('active_case', {'issuer_id':'AAPL', 'question_id':'bogus'}),
])
def test_batch_metadata_tampering_rejected(key, value):
    plan, batch = fixture()
    batch[key] = value
    with pytest.raises(BenchmarkContractError): reconcile_captures(plan, [batch])


@pytest.mark.parametrize('key,value', [
    ('question', 'another question'), ('issuer_id', 'MSFT'), ('question_id', 'bogus'),
    ('dimensions', {}), ('response_sha256', 'bad'), ('response', []),
    ('review_status', 'passed'), ('capture_status', 'passed'),
])
def test_case_tampering_rejected(key, value):
    plan, batch = fixture()
    batch['cases'][0][key] = value
    with pytest.raises(BenchmarkContractError): reconcile_captures(plan, [batch])


@pytest.mark.parametrize('change', ['question', 'dimension', 'hash', 'duplicate', 'bool_count'])
def test_full_canonical_plan_required(change):
    plan, batch = fixture()
    if change == 'question': plan['cases'][0]['question'] = 'changed'
    if change == 'dimension': plan['cases'][0]['dimensions']['sector'] = 'invented'
    if change == 'hash': plan['matrix_sha256'] = 'bad'
    if change == 'duplicate': plan['cases'].append(plan['cases'][0])
    if change == 'bool_count': plan['schema_version'] = True
    with pytest.raises(BenchmarkContractError): reconcile_captures(plan, [batch])


def test_empty_batch_list_is_missing_not_passing():
    plan, _ = fixture()
    result = reconcile_captures(plan, [])
    assert result['capture_counts'] == {'missing': 6}
    assert result['launch_ready'] is False


def test_interrupted_checkpoint_preserves_pending_case_as_missing():
    snapshots = []
    plan = build_matrix(tickers=['AAPL'], families=['core_thesis', 'financial_trends'])
    capture_matrix(tickers=['AAPL'], families=['core_thesis', 'financial_trends'], execute=True, limit=2,
                   runner=lambda *a: {}, checkpoint=lambda r: snapshots.append(copy.deepcopy(r)))
    active = next(r for r in snapshots if len(r['cases']) == 1 and r['active_case'])
    result = reconcile_captures(plan, [active])
    assert result['capture_counts'] == {'captured': 1, 'missing': 1}


def test_uncaptured_response_smuggling_rejected():
    plan = build_matrix(tickers=['AAPL'], families=['core_thesis'])
    batch = capture_matrix(tickers=['AAPL'], families=['core_thesis'])
    batch['cases'][0]['response'] = {}
    with pytest.raises(BenchmarkContractError): reconcile_captures(plan, [batch])


def test_cli_offline_hashes_inputs_and_refuses_overwrite(tmp_path, monkeypatch):
    import socket
    def forbidden(*a, **kw): raise AssertionError('network not allowed')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    plan, batch = fixture()
    plan_path, batch_path, out = [tmp_path / name for name in ('plan.json','batch.json','review.json')]
    plan_path.write_text(json.dumps(plan)); batch_path.write_text(json.dumps(batch))
    argv = ['--plan', str(plan_path), '--batch', str(batch_path), '--output', str(out)]
    assert cli.main(argv) == 0
    result = json.loads(out.read_text())
    assert len(result['input_file_sha256']) == 3
    before = out.read_bytes()
    with pytest.raises(SystemExit): cli.main(argv)
    assert out.read_bytes() == before


@pytest.mark.parametrize('bad', ['{"cases":[],"cases":[]}', '{"a":NaN}', '{"a":Infinity}', '{"a":1e999}', '[]'])
def test_cli_rejects_invalid_input_without_output(tmp_path, bad):
    plan, out = tmp_path/'plan.json', tmp_path/'out.json'
    plan.write_text(bad)
    with pytest.raises(SystemExit): cli.main(['--plan', str(plan), '--output', str(out)])
    assert not out.exists()


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), set(), {1: 'nonstring key'}])
def test_direct_api_rejects_non_json_values(bad):
    plan, batch = fixture()
    batch['cases'][0]['response']['bad'] = bad
    with pytest.raises(BenchmarkContractError): reconcile_captures(plan, [batch])


def test_mixed_matrix_batches_are_rejected():
    plan, batch = fixture()
    other = capture_matrix(tickers=['AAPL'], families=['core_thesis'])
    with pytest.raises(BenchmarkContractError): reconcile_captures(plan, [batch, other])
