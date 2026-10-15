"""Separate freshness policy/authority, synthetic ledger and isolated worker tests."""
from copy import deepcopy
from collections import Counter
import json
import sqlite3

import pytest
from validation.capture_budget import AttemptLedger, BudgetError, digest, validate_policy
from validation.pilot_policy import policy_for, AUDITED_DEPENDENCIES, RUN_DEADLINE_SECONDS
from validation.pilot_approved import manifest_for, validate_approval
from validation.pilot_rehearsal import run_rehearsal
from tests.test_pilot_approved import CONFIG

BINDING={'revision':'TEST-ONLY','source_sha256':'TEST-ONLY'}


def policy():return policy_for(BINDING,dict(AUDITED_DEPENDENCIES),mode='freshness')


def approval(output='/tmp/TEST-ONLY-freshness'):
    return {'reference':'TEST-ONLY-NO-AUTHORITY','run_id':'TEST-ONLY-freshness',
        'manifest_sha256':digest(manifest_for(BINDING,CONFIG,output,monitoring=True,freshness=True)),
        'output_dir':output,'execution_allowed':True,'spending_authorized':True}


def test_separate_scope_old_quotas_and_deadlines_preserved():
    old=policy_for(BINDING,dict(AUDITED_DEPENDENCIES),mode='source_monitoring')
    control=policy_for(BINDING,dict(AUDITED_DEPENDENCIES))
    p=policy();validate_policy(p)
    assert old['quotas']['overall']=={'model':0,'sec':33}
    assert control['quotas']['overall']=={'model':24,'sec':30}
    assert 'stage_quotas' not in old and 'stage_quotas' not in control
    assert 'decision_monitoring_filing_fallback_enabled' not in old['configuration']['settings']
    assert p['quotas']['overall']=={'model':0,'sec':39} and p['maximum_attempts']==39
    assert p['configuration']['settings']['decision_monitoring_filing_fallback_enabled'] is True
    assert RUN_DEADLINE_SECONDS==480 and not p['execution_allowed']
    for case,limits in p['quotas']['per_case'].items():
        if case.endswith(':decision_threshold'):
            assert (limits['sec'],limits['sec/submissions'],limits['sec/document'])==(5,2,1)
            assert p['stage_quotas'][case]['evidence.sec']['sec/document']==0
            assert p['stage_quotas'][case]['evidence.filing_metrics']['sec/document']==1


@pytest.mark.parametrize('mutate',[
    lambda p:p['quotas']['overall'].update(sec=40),
    lambda p:p['configuration']['settings'].update(decision_monitoring_filing_fallback_enabled=False),
    lambda p:p['stage_quotas']['ACHC:decision_threshold']['evidence.sec'].update({'sec/document':1}),
    lambda p:p.update(execution_allowed=True),
])
def test_fixed_policy_mutations_refused(mutate):
    p=policy();mutate(p)
    with pytest.raises(BudgetError):validate_policy(p)


def test_old_approval_never_authorizes_new_variant():
    old=approval();old['manifest_sha256']=digest(manifest_for(BINDING,CONFIG,old['output_dir'],monitoring=True))
    with pytest.raises(BudgetError):
        policy_for(BINDING,dict(AUDITED_DEPENDENCIES),mode='approved_freshness',approval=old,execution=CONFIG)
    p=policy_for(BINDING,dict(AUDITED_DEPENDENCIES),mode='approved_freshness',approval=approval(),execution=CONFIG)
    validate_policy(p)
    assert p['purpose']=='approved_monitoring_freshness_pilot'


def test_stage_reservation_is_durable_and_nontransferable(tmp_path):
    ledger=AttemptLedger(tmp_path/'book.sqlite',policy(),create=True)
    case=ledger.begin_case('ACHC:decision_threshold')
    fp=digest({'invented':'request'})
    ledger.reserve(case,'sec/submissions',input_bound=0,output_bound=0,request_sha256=fp,stage='evidence.sec')
    with pytest.raises(BudgetError,match='stage quota'):
        ledger.reserve(case,'sec/submissions',input_bound=0,output_bound=0,request_sha256=fp,stage='evidence.sec')
    with sqlite3.connect(tmp_path/'book.sqlite') as db:
        assert db.execute('SELECT stage FROM stage_reservations').fetchall()==[('evidence.sec',)]
    assert ledger.summary()['halted']


def test_unbound_stage_cannot_reserve(tmp_path):
    ledger=AttemptLedger(tmp_path/'book.sqlite',policy(),create=True)
    case=ledger.begin_case('ACHC:decision_threshold')
    with pytest.raises(BudgetError):
        ledger.reserve(case,'sec/document',input_bound=0,output_bound=0,request_sha256='a'*64)
    assert ledger.summary()['attempts']==0


def test_actual_isolated_freshness_pipeline(tmp_path):
    output=tmp_path/'run'
    r=run_rehearsal(output,mode='freshness',scenario='freshness_financial_inputs')
    assert r['status']=='complete',r
    assert len(r['completed_cases'])==6 and r['ledger']['unresolved_attempts']==0
    assert not r['ledger']['halted'] and r['external_dispatches']==0
    assert not any(c['route'].startswith('model/') for c in r['claims'])
    assert r['ledger']['attempts']<=39
    # Every routed source task is the actual audited router closure.
    for ticker in ('ASML','ACHC','NPK'):
        assert any(t['case_id']==ticker+':decision_threshold' and t['stage']=='evidence.filing_metrics' for t in r['logical_tasks'])
    for case in r['completed_cases']:
        if case['case_id'] in {'ACHC:decision_threshold','NPK:decision_threshold'}:
            answer=case['answer_and_evidence']['answer']
            refs=[e for e in answer['evidence_references'] if e.get('claim_type')=='reported_fact']
            assert len(refs)==4 and all(e['reporting_period_end']=='2025-12-31' for e in refs)
            assert all(e['url'].endswith('/issuer-20251231.htm') for e in refs)
            assert answer['source_answer']['monitoring_benchmarks']
            assert answer['source_answer']['reporting_period_coverage'] is None
    with sqlite3.connect(output/'ledger.sqlite') as db:
        rows=db.execute('SELECT c.case_id,s.stage,a.route,COUNT(*) FROM stage_reservations s JOIN attempts a ON a.id=s.attempt_id JOIN cases c ON c.id=a.case_run GROUP BY c.case_id,s.stage,a.route').fetchall()
        for case,stage,route,count in rows:assert count<=policy()['stage_quotas'][case][stage][route]


def test_wrong_stage_cannot_spend_new_document_slot(tmp_path,monkeypatch):
    from tests.test_pilot_approved import RUNTIME
    from validation.pilot_approved import ApprovedBoundary
    from validation._pilot_wire_fixtures import SyntheticProxyBackend
    for k,v in {'OPENAI_API_KEY':RUNTIME['bearer_placeholder'],'SEC_USER_AGENT':RUNTIME['sec_contact'],
                **{k:CONFIG['proxy'] for k in CONFIG['proxy_selectors']},
                **{k:CONFIG['ca_identity']['path'] for k in CONFIG['ca_selectors']}}.items():
        monkeypatch.setenv(k,v)
    p=policy_for(BINDING,dict(AUDITED_DEPENDENCIES),mode='approved_freshness',approval=approval(),execution=CONFIG)
    owner=ApprovedBoundary(AttemptLedger(tmp_path/'book.sqlite',p,create=True))
    owner.wire._wire._pool._network_backend.backend=SyntheticProxyBackend(owner)
    owner.begin(owner.cases[3]);owner.stage.set('evidence.sec')
    try:
        cik=owner.case['identity']['cik']
        owner.sec_exchange('GET',f'https://data.sec.gov/submissions/CIK{cik}.json',None)
        document=next(iter(owner.sec_document_urls()))
        with pytest.raises(BudgetError):owner.sec_exchange('GET',document,None)
        assert owner.gate.dispatched==1
        assert owner.ledger.summary()['attempts']==1 and owner.ledger.summary()['halted']
    finally:owner.close()


def test_approved_cli_missing_approval_never_launches(tmp_path,monkeypatch):
    from validation.pilot_freshness_approved import main
    from validation import pilot_rehearsal
    monkeypatch.setattr(pilot_rehearsal,'run_rehearsal',lambda *a,**k:pytest.fail('must not launch'))
    with pytest.raises(SystemExit) as exc:main(['--manifest',str(tmp_path/'missing'),'--output-dir',str(tmp_path/'run')])
    assert exc.value.code==2 and not (tmp_path/'run').exists()


@pytest.mark.parametrize('scenario',['evidence_timeout','wire_redirect'])
def test_faults_halt_without_model_calls(tmp_path,scenario):
    r=run_rehearsal(tmp_path/'run',mode='freshness',scenario=scenario)
    assert r['status']=='halted'
    assert r['ledger']['halted']
    if scenario=='wire_redirect':
        assert r['ledger']['unresolved_attempts']>=1
        assert r['ledger']['first_transport_failure']['code']=='http_redirect'
    else:
        assert r['ledger']['halted']=='stage_timeout'
    assert not any(c['route'].startswith('model/') for c in r['claims'])


@pytest.mark.parametrize('stage',[None,'evidence.unknown',[]])
def test_invalid_stage_cannot_consume_any_dispatch(tmp_path,stage):
    ledger=AttemptLedger(tmp_path/'book.sqlite',policy(),create=True)
    case=ledger.begin_case('ACHC:decision_threshold')
    with pytest.raises(BudgetError):
        ledger.reserve(case,'sec/document',input_bound=0,output_bound=0,request_sha256='a'*64,stage=stage)
    assert ledger.summary()['attempts']==0 and ledger.summary()['halted']
