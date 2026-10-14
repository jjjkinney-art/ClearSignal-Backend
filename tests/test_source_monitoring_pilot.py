"""Separate disabled source-monitoring policy; invented bytes, actual bridges."""
from collections import Counter
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import threading

import httpx
import pytest

from validation.capture_budget import AttemptLedger, BudgetError, validate_policy
from validation.pilot_live import LiveAdapterBoundary, OwnedHTTPTransport
from validation.pilot_policy import AUDITED_DEPENDENCIES, MODEL_ROUTES, SEC_ROUTES, policy_for, RUN_DEADLINE_SECONDS
from validation.pilot_rehearsal import run_rehearsal

BINDING = {'revision': 'TEST-ONLY', 'source_sha256': 'TEST-ONLY'}


def policy():
    return policy_for(BINDING, dict(AUDITED_DEPENDENCIES), mode='source_monitoring')


@pytest.fixture
def owner(tmp_path):
    b = LiveAdapterBoundary(AttemptLedger(tmp_path/'ledger.sqlite', policy(), create=True), 'happy')
    b.begin(b.cases[1]); b.stage.set('evidence.sec_metrics')
    yield b
    b.close()


def test_frozen_policy_unchanged_and_separate_zero_model_allocations():
    frozen = policy_for(BINDING, dict(AUDITED_DEPENDENCIES))
    p = policy(); validate_policy(p)
    assert frozen['configuration']['settings']['decision_monitoring_inputs_enabled'] is False
    assert frozen['quotas']['overall'] == {'model': 24, 'sec': 30}
    assert p['configuration']['settings']['decision_monitoring_inputs_enabled'] is True
    assert p['quotas']['overall'] == {'model': 0, 'sec': 33}
    assert p['maximum_attempts'] == 33 and RUN_DEADLINE_SECONDS == 480
    assert not p['execution_allowed'] and not p['spending_authorized']
    assert p['prices'] == frozen['prices']
    unchanged = deepcopy(p['configuration'])
    unchanged['variant'] = frozen['configuration']['variant']
    unchanged['settings']['decision_monitoring_inputs_enabled'] = False
    assert unchanged == frozen['configuration']
    for case, limits in p['quotas']['per_case'].items():
        assert all(limits[r] == 0 for r in MODEL_ROUTES)
        if case.endswith(':core_thesis'):
            assert limits == frozen['quotas']['per_case'][case]
        else:
            assert {r: limits[r] for r in ('sec','sec/directory','sec/submissions','sec/facts','sec/document')} == {
                'sec':3,'sec/directory':1,'sec/submissions':1,'sec/facts':1,'sec/document':0}


@pytest.mark.parametrize('mutate', [
    lambda p:p['configuration']['settings'].update(decision_monitoring_inputs_enabled=False),
    lambda p:p['quotas']['overall'].update(model=1),
    lambda p:p['quotas']['per_case']['ASML:decision_threshold'].update({'sec/document':1}),
    lambda p:p.update(execution_allowed=True),
])
def test_policy_mutation_refused(mutate):
    p=policy();mutate(p)
    with pytest.raises(BudgetError):validate_policy(p)


def test_authority_and_native_network_remain_disabled():
    with pytest.raises(BudgetError):policy_for(BINDING,dict(AUDITED_DEPENDENCIES),mode='source_monitoring',approval={})
    wire=OwnedHTTPTransport()
    try:
        with pytest.raises(BudgetError,match='execution remains disabled'):
            wire.exchange('GET','https://www.sec.gov/files/company_tickers.json')
    finally:wire.close()


@pytest.mark.parametrize('stage', ['valuation','macro','risk','market','quality','question_answerer','synthesis'])
def test_model_dispatch_refused_before_wire(owner, monkeypatch, stage):
    owner.stage.set(stage)
    entered=[]
    monkeypatch.setattr(owner.wire,'exchange',lambda *a,**kw:entered.append(True))
    payload={'model':'gpt-4o-mini','messages':[{'role':'user','content':'Invented question'}],
             'temperature':0,'max_tokens':1536 if stage=='synthesis' else 4096,
             'service_tier':'default','n':1,'stream':False}
    timeout=55.0 if stage=='synthesis' else 15.0
    req=httpx.Request('POST','https://api.openai.com/v1/chat/completions',json=payload,
                      extensions={'timeout':dict.fromkeys(('connect','read','write','pool'),timeout)})
    with pytest.raises(BudgetError):owner.model_request(req)
    assert not entered
    assert owner.ledger.summary()['halted'] == 'rehearsal stage quota exceeded; slots cannot transfer'
    assert owner.ledger.summary()['attempts']==0


def test_facts_route_quota_cannot_borrow_unused_directory_or_other_case(owner):
    url='https://data.sec.gov/api/xbrl/companyfacts/CIK0000937966.json'
    owner.sec_exchange('GET',url,None)
    with pytest.raises(BudgetError):owner.sec_exchange('GET',url,None)
    assert owner.ledger.summary()['halted']
    assert owner.ledger.summary()['attempts']==1
    assert owner.ledger.summary()['unresolved_attempts']==0
    with pytest.raises(BudgetError):owner.begin(owner.cases[3])


def test_threshold_document_zero_quota_before_wire(owner,monkeypatch):
    cik=owner.case['identity']['cik']
    owner.stage.set('evidence.sec')
    owner.sec_exchange('GET',f'https://data.sec.gov/submissions/CIK{cik}.json',None)
    url=next(iter(owner.sec_document_urls()));calls=[]
    monkeypatch.setattr(owner.wire,'exchange',lambda *a,**kw:calls.append(True))
    with pytest.raises(BudgetError):owner.sec_exchange('GET',url,None)
    assert not calls and owner.ledger.summary()['halted']
    assert owner.ledger.summary()['attempts']==1


def test_concurrent_facts_claims_admit_at_most_one(owner):
    barrier=threading.Barrier(2)
    def request():
        owner.stage.set('evidence.sec_metrics');barrier.wait()
        try:owner.sec_exchange('GET','https://data.sec.gov/api/xbrl/companyfacts/CIK0000937966.json',None)
        except BudgetError:pass
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:request(),range(2)))
    assert owner.ledger.summary()['attempts']==1
    assert owner.ledger.summary()['halted']
    reopened = AttemptLedger(owner.ledger.path, policy())
    assert reopened.summary()['halted']
    with pytest.raises(BudgetError):reopened.require_active()


def test_logical_inventory_refuses_unreviewed_callable(owner):
    import concurrent.futures as cf
    owner.install()
    try:
        pool=cf.ThreadPoolExecutor(max_workers=8)
        with pytest.raises(BudgetError):pool.submit(lambda:None)
        assert owner.ledger.summary()['halted']=='configuration_drift'
        assert owner.ledger.summary()['attempts']==0
    finally:
        # Fixture close restores all patches and drains tracked work.
        pass


@pytest.mark.parametrize('scenario', ['happy','monitoring_financial_inputs'])
def test_actual_isolated_inventory_dispatch_and_answer_evidence(tmp_path,scenario):
    result=run_rehearsal(tmp_path/'new',mode='source_monitoring',scenario=scenario)
    assert result['status']=='complete',result
    assert result['artifact_type']=='disabled_source_monitoring_validation'
    assert result['route_counts']=={'sec/directory':6,'sec/submissions':12,'sec/facts':6,'sec/document':5}
    assert result['external_dispatches']==0 and result['network_attempts']==0
    assert result['diagnostics_canary_clean'] and result['netrc_open_attempts']==0
    assert result['ledger']['unresolved_attempts']==0
    inventory=Counter(t['case_id'] for t in result['logical_tasks'])
    for case in result['completed_cases']:
        core=case['case_id'].endswith(':core_thesis')
        assert inventory[case['case_id']]==(10 if core else 8)
        names = [t['function'] for t in result['logical_tasks'] if t['case_id'] == case['case_id']]
        assert names == ['_fetch_fmp', '_fetch_sec', '_fetch_news_company', '_fetch_news_macro',
                         '_fetch_fred_evidence', '_fetch_valuation_ratios', '_fetch_analyst_estimates',
                         '_fetch_sec_metrics'] + (['_fetch_thesis_disclosures', '_fetch_filing_metrics'] if core else [])
        answer=case['answer_and_evidence']
        assert answer['agents_used']==['source_answer']
        if core:continue
        thesis=answer['answer']['investment_thesis']
        assert not thesis['decision_thresholds'] and not thesis['threshold_zones']
        gate=answer['answer']['source_answer']
        if scenario=='happy':
            assert gate['status']=='insufficient_claim_evidence'
            assert not gate.get('monitoring_benchmarks')
        else:
            assert gate['status']=='partial'
            refs={r['id']:r for r in answer['answer']['evidence_references']}
            row=gate['monitoring_benchmarks'][0]
            assert row['benchmark_percent']=='20.0'
            values=row['inputs'];calculated=Decimal(values['operating_income']['raw_value'])/Decimal(values['revenue']['raw_value'])*100
            assert calculated==Decimal(row['benchmark_percent'])
            assert all(ref in refs for ref in row['reference_ids'])
            assert 'not a buy/sell boundary' in row['limitation']


def test_all_33_sec_slots_are_claimable_without_model_or_slot_transfer(tmp_path, monkeypatch):
    tick = iter(range(0, 100_000_000_000, 100_000_000))
    monkeypatch.setattr('validation.capture_budget.time.monotonic_ns', lambda: next(tick))
    book = AttemptLedger(tmp_path / 'all-slots.sqlite', policy(), create=True)
    for case in book.policy['approved_case_ids']:
        run = book.begin_case(case)
        for route in SEC_ROUTES:
            for _ in range(book.policy['quotas']['per_case'][case][route]):
                bound = dict(case_run=run, route=route, request_sha256='a' * 64,
                             input_bound=0, output_bound=0)
                attempt = book.reserve(**bound)
                book.claim_dispatch(attempt, **bound)
                book.settle(attempt, input_tokens=0, output_tokens=0)
        book.finish_case(run)
    summary = book.summary()
    assert summary['attempts'] == 33
    assert summary['unresolved_attempts'] == 0
    assert summary['halted'] is None
