import json

import pytest
from validation.company_quality_matrix import build_matrix, capture_matrix, QUESTION_FAMILIES
from validation.intelligence_benchmark import BenchmarkContractError
from scripts import benchmark_company_quality as cli


def test_plan_covers_all_six_families_per_registry_issuer_and_interleaves_sizes():
    plan = build_matrix()
    assert plan['issuer_count'] == 18
    assert plan['case_count'] == 108
    assert len({(c['issuer_id'],c['question_id']) for c in plan['cases']}) == 108
    assert set(c['question_id'] for c in plan['cases']) == set(QUESTION_FAMILIES)
    assert {c['dimensions']['market_cap_tier'] for c in plan['cases'][:3]} == {'mega_large','mid','small_micro'}
    assert plan['coverage_targets']['issuer_count'] == 100
    assert plan['market_cap_counts'] == {'mega_large':12,'mid':3,'small_micro':3}


@pytest.mark.parametrize('kwargs', [
    {'tickers':[]}, {'tickers':['BOGUS']}, {'tickers':['aapl','AAPL']},
    {'families':['bogus']}, {'families':[]}, {'families':['core_thesis','core_thesis']},
])
def test_invalid_scope_cannot_silently_shrink_or_duplicate_benchmark(kwargs):
    with pytest.raises(BenchmarkContractError): build_matrix(**kwargs)


@pytest.mark.parametrize('kwargs', [
    {'limit':0}, {'limit':21}, {'limit':True}, {'offset':-1}, {'offset':108}, {'offset':True},
])
def test_batch_bounds_are_enforced(kwargs):
    with pytest.raises(BenchmarkContractError): capture_matrix(**kwargs)


def test_dry_run_never_executes_and_never_claims_quality_pass():
    def forbidden(*args): raise AssertionError('executed providers')
    report = capture_matrix(runner=forbidden,limit=3)
    assert report['capture_counts'] == {'not_executed':3}
    assert report['quality_pass_rate'] is None
    assert report['launch_ready'] is False
    assert report['capture_safety']['authenticated_api_tested'] is False
    assert not any(report['capture_safety'].values())


def test_failed_capture_continues_checkpoints_and_cannot_be_a_useful_answer():
    calls=[]; checkpoints=[]
    def runner(ticker,question,request):
        calls.append(ticker)
        if len(calls)==2: raise RuntimeError('secret must not appear in report')
        return {'answer':{'investment_thesis':{'direct_answer':'A generated answer.'}}}
    report=capture_matrix(execute=True,limit=3,runner=runner,
        checkpoint=lambda r: checkpoints.append(json.loads(json.dumps(r))))
    assert len(calls)==3
    assert report['capture_counts']=={'captured':2,'execution_failed':1}
    assert report['batch_complete'] is True
    assert report['next_offset']==3
    assert [len(r['cases']) for r in checkpoints]==[0,0,1,1,2,2,3]
    assert report['active_case'] is None
    assert [r['active_case']['issuer_id'] for r in checkpoints if r['active_case']] == calls
    assert 'secret' not in json.dumps(report)
    assert report['cases'][1]['error_class']=='RuntimeError'
    assert report['quality_status']=='not_adjudicated'
    assert report['quality_pass_rate'] is None
    assert report['launch_ready'] is False
    assert len(report['cases'][0]['response_sha256'])==64
    assert sum(sum(v.values()) for v in report['capture_by_market_cap'].values())==3


def test_offset_batches_preserve_issuer_question_identity_without_overlap():
    a=capture_matrix(limit=20)
    b=capture_matrix(offset=a['next_offset'],limit=20)
    keys=lambda r: {(c['issuer_id'],c['question_id']) for c in r['cases']}
    assert not keys(a)&keys(b)
    assert len(keys(a)|keys(b))==40


def test_cli_requires_execution_gate_and_checkpoint_path(monkeypatch):
    monkeypatch.delenv('CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED',raising=False)
    with pytest.raises(SystemExit) as error: cli.main(['--execute'])
    assert error.value.code==2
    monkeypatch.setenv('CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED','true')
    with pytest.raises(SystemExit) as error: cli.main(['--execute'])
    assert error.value.code==2


def test_cli_writes_complete_dry_report_atomically(tmp_path,capsys):
    path=tmp_path/'report.json'
    assert cli.main(['--ticker','ACHC','--limit','6','--output',str(path)])==0
    report=json.loads(path.read_text())
    assert report['capture_counts']=={'not_executed':6}
    assert report['launch_ready'] is False
    assert len(list(tmp_path.iterdir()))==1
    assert json.loads(capsys.readouterr().out)['output']==str(path)


def test_cli_cannot_overwrite_existing_execution_result(tmp_path,monkeypatch):
    monkeypatch.setenv('CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED','true')
    path=tmp_path/'captured.json'
    path.write_text('previous capture')
    with pytest.raises(SystemExit) as error:
        cli.main(['--execute','--output',str(path)])
    assert error.value.code==2
    assert path.read_text()=='previous capture'


def test_matrix_hash_tracks_question_scope_and_order():
    a=build_matrix(tickers=['AAPL'],families=['core_thesis'])
    b=build_matrix(tickers=['AAPL'],families=['financial_trends'])
    assert a['matrix_sha256']!=b['matrix_sha256']
    assert a['run_id']!=b['run_id']


def test_inflight_checkpoint_preserves_resume_offset_without_claiming_capture_or_quality():
    checkpoints = []
    def checkpoint(report):
        checkpoints.append(json.loads(json.dumps(report)))
    def runner(ticker, question, request):
        latest = checkpoints[-1]
        assert latest['active_case']['issuer_id'] == ticker
        assert latest['active_case']['question_id'] == 'core_thesis'
        assert latest['active_case']['started_at']
        assert latest['next_offset'] == 0
        assert latest['capture_counts'] == {}
        assert latest['batch_complete'] is False
        assert latest['launch_ready'] is False
        return {'answer': {'source_answer': {'status': 'partial'}}}
    report = capture_matrix(execute=True, limit=1, runner=runner, checkpoint=checkpoint)
    assert report['active_case'] is None
    assert report['next_offset'] == 1 and report['batch_complete'] is True
    assert report['quality_pass_rate'] is None
