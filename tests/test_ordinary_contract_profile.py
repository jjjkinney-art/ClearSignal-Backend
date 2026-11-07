"""The threshold-filing contract profile: bound, refused when altered, and honest.

Everything runs against invented SEC responses and invented approvals; the run-6 issuers
are identity only here. Nothing is real-company evidence or authority to run a pilot.

Profile tests run in a child process with verified counts, which also runs every other
approved-path suite. The original contracts are checked in children selecting consumed
cohorts, because the cohort is fixed at import.
"""
import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

import pytest

from _ordinary_child_report import child_counts, child_problems, read_junit
from _ordinary_cohort_expectations import EXPECTED_SEC_EXCHANGES, UNRESOLVED
from validation.capture_budget import BudgetError, digest
from validation.ordinary_native_boundary import verify_contract_profile
from validation.ordinary_native_ledger import CASE_SECONDS, degraded_stages
from validation.ordinary_transport import OrdinaryHTTPTransport
from validation.ordinary_pilot_contract import (APPROVED_COHORT, CASES, COHORT, FAULT_CASE_INDEX, THRESHOLD_FILING_PROFILE,
                                                contract_profile, quota_contract)

ROOT = Path(__file__).resolve().parents[1]
CHILD = os.environ.get('ORDINARY_PROFILE_CHILD') == '1'
ORIGINAL_ONLY = pytest.mark.skipif(contract_profile() is not None, reason='needs a consumed cohort')
PROFILE_ONLY = pytest.mark.skipif(contract_profile() is None or not CHILD, reason='runs in the profile child process')
MAIN_ONLY = pytest.mark.skipif(contract_profile() is None or CHILD, reason='starts the child processes')
# sha256 of each consumed cohort's quota contract before cohort 3 was connected.
ORIGINAL_CONTRACT_DIGESTS = {'run5': 'd663fea486005a05b3a8a5ead195afd57e78f4e941eeb2f5858bae97298489cf', 'run3': 'f3cda6d201e4c01bdce75e5ead08b4b8ac610e3158ab9f3decc667d38cb6b9fe', 'runs-1-2': '4c6dfba55b44665da9bde6e63204a7f9fa2a2af6f442f35b3ddbd121c9f83d1f'}
SLOW, AFTER_CUTOFF = 'threshold_filing_slow', 'threshold_filing_after_cutoff'
NOTICE = 'Incomplete answer: the quarterly report (Form 10-Q) could not be read for this answer'


class Settings:
    def __init__(self, enabled, fallback=False):
        self.threshold_filing_explanations_enabled = enabled
        self.decision_monitoring_filing_fallback_enabled = fallback


class Router:
    THRESHOLD_DOCUMENT_WAIT_SECONDS = THRESHOLD_FILING_PROFILE['filing_wait_seconds']
    THRESHOLD_FILING_PARSE_CUTOFF_SECONDS = THRESHOLD_FILING_PROFILE['filing_parse_cutoff_seconds']


# -- the original contract ---------------------------------------------------------

@ORIGINAL_ONLY
def test_the_original_contract_is_unchanged():
    assert contract_profile() is None
    limits = quota_contract()
    assert limits['sec_gets'] == 66 and limits['execution_authorized'] is False
    for case in CASES:
        core = case.endswith(':core_thesis')
        assert limits['per_case'][case] == {'sec': 8 if core else 3, 'sec/directory': 2 if core else 1,
                                            'sec/submissions': 3 if core else 1, 'sec/facts': 1,
                                            'sec/document': 2 if core else 0}
        assert ('evidence.filing_metrics' in limits['per_stage'][case]) is core


@ORIGINAL_ONLY
def test_the_consumed_contract_is_byte_identical():
    assert digest(quota_contract()) == ORIGINAL_CONTRACT_DIGESTS[COHORT]


@ORIGINAL_ONLY
def test_the_original_policy_and_manifest_carry_no_profile(tmp_path):
    from validation.ordinary_isolated_rehearsal import rehearsal_policy
    policy = rehearsal_policy(tmp_path / 'run')
    assert 'threshold_filing_explanations_enabled' not in policy['configuration']['settings']
    from validation import ordinary_approved as launcher
    assert 'contract_profile' not in launcher.derived_evidence('cost')
    assert not any('contract_profile' in test for test in launcher.ENFORCED_BY)


def test_nothing_patches_the_contract_at_run_time():
    for path in (ROOT / 'validation').glob('*.py'):
        text = path.read_text()
        assert not re.search(r"\.quota_contract\s*=|setattr\([^)]*quota_contract", text), path.name
    assert not (ROOT / 'validation' / 'ordinary_option_b_candidate.py').exists()


@ORIGINAL_ONLY
@pytest.mark.timeout(120)
@pytest.mark.parametrize('scenario', [SLOW, AFTER_CUTOFF])
def test_the_original_cohort_refuses_the_profile_scenarios(tmp_path, scenario):
    from validation.ordinary_isolated_rehearsal import run_rehearsal
    result = run_rehearsal(tmp_path / 'run', scenario=scenario)
    assert result['status'] == 'worker_incomplete' and result['supervisor']['returncode'] == 2
    assert not (tmp_path / 'run' / 'ledger.sqlite').exists()


@ORIGINAL_ONLY
@pytest.mark.timeout(120)
def test_the_original_cohort_refuses_a_policy_with_the_switch(tmp_path):
    from validation.ordinary_isolated_rehearsal import cohort_selection, rehearsal_policy, run_worker
    from validation.ordinary_native_ledger import create_fresh_output
    from validation._ordinary_rehearsal_worker import REHEARSAL_RUNTIME
    output = create_fresh_output(tmp_path / 'run')
    policy = rehearsal_policy(output)
    policy['configuration']['settings']['threshold_filing_explanations_enabled'] = True
    result = run_worker(output, policy, mode='rehearsal', scenario='happy', environment=cohort_selection(),
                        forbidden=tuple(REHEARSAL_RUNTIME.values()), synthetic=True)
    assert result['status'] == 'worker_incomplete' and result['supervisor']['returncode'] == 2
    assert not (output / 'ledger.sqlite').exists()


@pytest.mark.parametrize('profile,settings,router,expected', [
    (None, Settings(False), None, True),
    (None, Settings(True), None, False),
    (None, Settings(False, fallback=True), None, False),
    (THRESHOLD_FILING_PROFILE, Settings(True), Router, True),
    (THRESHOLD_FILING_PROFILE, Settings(False), Router, False),
    (THRESHOLD_FILING_PROFILE, Settings(True, fallback=True), Router, False),
    (THRESHOLD_FILING_PROFILE, Settings(True), type('R', (Router,), {'THRESHOLD_DOCUMENT_WAIT_SECONDS': 20}), False),
    (THRESHOLD_FILING_PROFILE, Settings(True), type('R', (Router,), {'THRESHOLD_FILING_PARSE_CUTOFF_SECONDS': 16}), False),
])
def test_the_running_application_must_match_the_contract(profile, settings, router, expected):
    assert verify_contract_profile(profile, settings, router) is expected


@pytest.mark.parametrize('shared', [True, False])
def test_document_admission_is_case_wide_only_under_the_profile(shared):
    from threading import Lock
    from types import SimpleNamespace
    from validation.ordinary_native_boundary import OrdinaryNativeBoundary
    from validation._ordinary_synthetic_sec import respond
    from validation.ordinary_native_boundary import DOCUMENT_STAGES
    cik = 1581280  # an invented backend registrant
    _, _, content = respond(f'/submissions/CIK{cik:010d}.json')
    owner = SimpleNamespace(case={'identity': {'cik': f'{cik:010d}'}}, lock=Lock(), case_documents={}, admitted={},
                            case_run='case-1', threshold_filing=shared, identities=[])
    OrdinaryNativeBoundary._admit(owner, 'sec/submissions', 'evidence.sec', 'application/json', content)
    urls = owner.admitted['case-1', 'evidence.sec']
    assert urls
    for stage in DOCUMENT_STAGES:
        assert owner.admitted.get(('case-1', stage)) == (urls if shared else None)
    assert not any(run != 'case-1' for run, _ in owner.admitted)


def test_the_profile_binds_every_named_value():
    profile = THRESHOLD_FILING_PROFILE
    assert profile['name'] == 'threshold_filing_v1' and profile['cohort'] == APPROVED_COHORT == 'run6'
    assert profile['sec_gets_per_case'] == {'core_thesis': 6, 'decision_threshold': 5} and profile['sec_gets'] == 66
    assert profile['switch'] == 'threshold_filing_explanations_enabled'
    assert profile['filing_parse_cutoff_seconds'] < profile['filing_wait_seconds'] < profile['case_seconds']['decision_threshold']
    assert profile['case_seconds'] == CASE_SECONDS and profile['wall_seconds'] == quota_contract()['wall_seconds']
    assert profile['read_timeout_seconds'] == inspect.signature(OrdinaryHTTPTransport.exchange).parameters['timeout'].default
    from app.services import router_service
    assert router_service.THRESHOLD_DOCUMENT_WAIT_SECONDS == profile['filing_wait_seconds']
    assert router_service.THRESHOLD_FILING_PARSE_CUTOFF_SECONDS == profile['filing_parse_cutoff_seconds']


def test_the_pre_registered_cohort_is_bound_unchanged():
    records = json.loads((ROOT / 'tests' / 'ordinary_run6_cases.json').read_text())
    assert records == json.loads((ROOT / 'docs' / 'generalization_cohort_3_cases.json').read_text())
    selection = json.loads((ROOT / 'docs' / 'generalization_cohort_3_selection.json').read_text())
    issuers = [row['ticker'] for row in selection['cohort']]
    assert issuers == ['BP', 'MNST', 'CRDO', 'LLYVA', 'DGXX', 'VIRC']
    case_order = [f'{issuer}:{question}' for issuer in issuers for question in ('core_thesis', 'decision_threshold')]
    assert [record['case_id'] for record in records] == case_order == THRESHOLD_FILING_PROFILE['case_order']
    assert {int(record['expected_cik']) for record in records} == {row['cik'] for row in selection['cohort']}
    questions = [record['question'] for record in records]
    assert hashlib.sha256(json.dumps(questions).encode()).hexdigest() == THRESHOLD_FILING_PROFILE['questions_sha256']
    checks = json.loads((ROOT / 'docs' / 'generalization_cohort_3_offline_checks.json').read_text())
    assert checks['questions_sha256'] == THRESHOLD_FILING_PROFILE['questions_sha256']
    assert checks['frontend_commit'] == THRESHOLD_FILING_PROFILE['frontend']['commit']
    assert checks['classifier_sha256'] == THRESHOLD_FILING_PROFILE['frontend']['classifier_sha256']
    assert set(checks['intents'].values()) == {'company_analysis'}
    assert [row['case_id'] for row in checks['identity'] if row['verdict'] == 'no company'] == [
        'LLYVA:core_thesis', 'LLYVA:decision_threshold']


@PROFILE_ONLY
def test_the_frontend_pin_is_bound_to_the_profile():
    from validation.ordinary_frontend_intents import CASE_INTENTS, FRONTEND
    for key, value in THRESHOLD_FILING_PROFILE['frontend'].items():
        assert FRONTEND[key] == value
    assert FRONTEND['questions_sha256'] == THRESHOLD_FILING_PROFILE['questions_sha256']
    assert set(CASE_INTENTS.values()) == {'company_analysis'} and list(CASE_INTENTS) == list(CASES)


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


def _decorated_with(marker):
    """Test functions in this file carrying one module-level marker."""
    tree = ast.parse(Path(__file__).read_text())
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
            and any(isinstance(d, ast.Name) and d.id == marker for d in node.decorator_list)}


def test_child_problems_reject_a_run_that_only_looks_green():
    required = {('m', 'a')}
    assert child_problems([('m', 'a', 'passed')], 0, required=required, allowed_skips=set()) == []
    assert child_problems([], 0, required=set(), allowed_skips=set()) == ['child collected no tests']
    assert child_problems([('m', 'b', 'passed')], 0, required=required, allowed_skips=set()) == [
        "required test missing: ('m', 'a')"]
    assert child_problems([('m', 'a', 'skipped')], 0, required=required, allowed_skips={('m', 'a')})[0].startswith(
        'required test not passed')
    assert child_problems([('m', 'a', 'passed'), ('m', 'c', 'skipped')], 0, required=required, allowed_skips=set()) == [
        "unexpected skip: ('m', 'c')"]
    assert 'child exited 1' in child_problems([('m', 'a', 'passed')], 1, required=required, allowed_skips=set())
    assert any('test failed' in p for p in child_problems(
        [('m', 'a', 'passed'), ('m', 'd', 'failed')], 0, required=required, allowed_skips=set()))


def test_junit_outcomes_are_read_per_test(tmp_path):
    report = tmp_path / 'report.xml'
    report.write_text('<testsuites><testsuite><testcase classname="tests.test_x" name="test_a[p1]"/>'
                      '<testcase classname="tests.test_x" name="test_b"><skipped/></testcase>'
                      '<testcase classname="tests.test_y" name="test_c"><failure/></testcase>'
                      '<testcase classname="tests.test_y" name="test_d"><error/></testcase></testsuite></testsuites>')
    rows = read_junit(report)
    assert rows == [('test_x', 'test_a', 'passed'), ('test_x', 'test_b', 'skipped'),
                    ('test_y', 'test_c', 'failed'), ('test_y', 'test_d', 'error')]
    counts = child_counts(rows, 1)
    assert (counts['collected'], counts['passed'], counts['skipped'], counts['failed'], counts['error']) == (4, 1, 1, 1, 1)


# Under the profile these must have run and passed, not merely not failed.
REQUIRED_APPROVED_PATH_TESTS = {
    ('test_ordinary_live_launcher', name) for name in (
        'test_loopback_run_uses_the_live_code_path_within_every_limit',
        'test_an_unpinned_certificate_halts_before_any_request_is_served',
        'test_the_output_directory_holds_only_the_declared_inventory',
        'test_live_modes_require_an_approval_of_their_own_kind',
        'test_the_worker_refuses_a_live_mode_before_any_ledger_or_socket',
        'test_run_refuses_every_unapproved_or_drifted_input',
        'test_run_without_execute_only_checks',
        'test_an_approval_executes_at_most_once',
        'test_a_worker_that_stops_before_its_ledger_still_records_and_reports_twelve_outcomes',
        'test_prepare_refuses_tampered_or_unfinished_evidence',
        'test_check_refuses_a_ceiling_other_than_the_cost_evidence',
        'test_prepare_refuses_test_only_or_incomplete_inputs',
        'test_prepare_and_check_refuse_any_cohort_selection',
        'test_direct_tls_reaches_only_the_claimed_sec_host_within_every_limit',
        'test_committed_evidence_templates_match_the_code',
    )} | {('test_ordinary_isolated_worker', name) for name in (
        'test_twelve_cases_run_through_the_integrated_native_path',
        'test_an_answer_the_parent_ruled_late_is_never_exported',
        'test_an_abandoned_evidence_request_degrades_one_answer_without_halting',
    )}
def _child_env(**values):
    env = {key: value for key, value in os.environ.items()
           if key not in {'ORDINARY_PILOT_COHORT', 'ORDINARY_PROFILE_CHILD'}}
    return {**env, **values}


@MAIN_ONLY
@pytest.mark.timeout(1800)
def test_the_ordinary_tests_pass_under_the_profile(tmp_path):
    # The native ledger, boundary and contract tests build their own requests against the
    # original quota shape; test_ordinary_historical_cohort verifies them on that contract.
    tests = [f'tests/test_ordinary_{name}.py' for name in
             ('contract_profile', 'live_launcher', 'isolated_worker', 'execution_contract')]
    junit = tmp_path / 'child.xml'
    done = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-o', 'addopts=',
                           '--disable-warnings', '--tb=short', f'--junitxml={junit}', *tests], cwd=ROOT,
                          env=_child_env(ORDINARY_PROFILE_CHILD='1'), capture_output=True, text=True, timeout=1750)
    assert junit.is_file(), done.stdout[-6000:] + done.stderr[-2000:]
    rows = read_junit(junit)
    module = Path(__file__).stem
    required = REQUIRED_APPROVED_PATH_TESTS | {(module, name) for name in _decorated_with('PROFILE_ONLY')}
    allowed = {(module, name) for name in _decorated_with('ORIGINAL_ONLY') | _decorated_with('MAIN_ONLY')}
    counts = child_counts(rows, done.returncode)
    counts.update(required_tests=len(required), required_missing_or_not_passed=[
        problem for problem in child_problems(rows, done.returncode, required=required)
        if problem.startswith('required')], cohort=contract_profile()['cohort'], profile=contract_profile()['name'])
    # CI keeps this file. Written before the checks, so a failing run still leaves its counts.
    destination = os.environ.get('ORDINARY_PROFILE_CHILD_REPORT')
    if destination:
        Path(destination).write_text(json.dumps(counts, indent=1, sort_keys=True))
    problems = child_problems(rows, done.returncode, required=required, allowed_skips=allowed)
    assert problems == [], '\n'.join(problems) + '\n' + done.stdout[-4000:]


@MAIN_ONLY
@pytest.mark.timeout(600)
@pytest.mark.parametrize('cohort', ['run5', 'run3', 'runs-1-2'])
def test_consumed_cohorts_keep_their_original_contracts(tmp_path, cohort):
    junit = tmp_path / 'child.xml'
    done = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-o', 'addopts=',
                           '--disable-warnings', '--tb=short', f'--junitxml={junit}', 'tests/test_ordinary_contract_profile.py',
                           '-k', 'original or consumed_contract'], cwd=ROOT,
                          env=_child_env(ORDINARY_PILOT_COHORT=cohort), capture_output=True, text=True, timeout=580)
    assert junit.is_file(), done.stdout[-4000:] + done.stderr[-2000:]
    module = Path(__file__).stem
    required = {(module, name) for name in _decorated_with('ORIGINAL_ONLY')}
    assert child_problems(read_junit(junit), done.returncode, required=required) == [], done.stdout[-4000:]


# -- the profile -------------------------------------------------------------------

@PROFILE_ONLY
def test_the_quotas_are_six_and_five_within_the_same_ceiling():
    limits = quota_contract()
    assert limits['sec_gets'] == 66 and limits['execution_authorized'] is False
    assert limits['model_attempts'] == limits['paid_provider_attempts'] == 0
    assert sum(limits['per_case'][case]['sec'] for case in CASES) == 66
    for case in CASES:
        assert limits['per_case'][case] == (
            {'sec': 6, 'sec/directory': 2, 'sec/submissions': 1, 'sec/facts': 1, 'sec/document': 2}
            if case.endswith(':core_thesis') else
            {'sec': 5, 'sec/directory': 2, 'sec/submissions': 1, 'sec/facts': 1, 'sec/document': 1})


@PROFILE_ONLY
def test_the_policy_binds_the_switch(tmp_path):
    from validation.ordinary_isolated_rehearsal import rehearsal_policy
    settings = rehearsal_policy(tmp_path / 'run')['configuration']['settings']
    assert settings['threshold_filing_explanations_enabled'] is True
    assert settings['decision_monitoring_filing_fallback_enabled'] is False


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_the_profile_runs_within_its_limits_and_reuses_submissions(tmp_path):
    from validation.ordinary_isolated_rehearsal import run_rehearsal
    result = run_rehearsal(tmp_path / 'run', scenario='happy')
    packet = result['packet']
    assert result['status'] == 'complete' and packet['halt'] is None and packet['first_failure'] is None
    assert packet['attempt_count'] == EXPECTED_SEC_EXCHANGES == 45 and result['worker']['refused_requests'] == []
    routes = {}
    for attempt in packet['attempts']:
        assert attempt['status'] == 'settled'
        routes[attempt['case_id'], attempt['route']] = routes.get((attempt['case_id'], attempt['route']), 0) + 1
    for case in CASES:
        if case in UNRESOLVED:
            assert not any(key[0] == case for key in routes)
            continue
        assert routes[case, 'sec/submissions'] == 1
        assert routes[case, 'sec/document'] == (2 if case.endswith(':core_thesis') else 1)
    statuses = {row['case_id']: row['status'] for row in packet['cases']}
    assert [case for case, status in statuses.items() if status == 'identity_unresolved'] == [
        'LLYVA:core_thesis', 'LLYVA:decision_threshold']


def _degraded_case(packet):
    degraded = [c['case_id'] for c in packet['cases'] if c['status'] == 'answered_degraded_unadjudicated']
    assert len(degraded) == 1 and degraded[0].endswith(':decision_threshold')
    assert packet['outcome_counts']['degraded_answer'] == 1 and packet['quality_pass_rate'] is None
    return degraded[0]


def _assert_filing_gap(packet, case, reason):
    source = packet['answers'][case]['response']['answer']['source_answer']
    assert source['degraded'] is True
    assert source['evidence_gaps'] == [{'source': 'the quarterly report (Form 10-Q)', 'task': 'filing_metrics', 'reason': reason}]
    assert NOTICE in json.dumps(packet['answers'][case]['response'])
    assert packet['abandoned_stages'] == [{'case_id': case, 'stage': 'evidence.filing_metrics'}]


def _assert_recorded(ledger, case):
    with sqlite3.connect(ledger) as db:
        assert db.execute('SELECT c.case_id, s.stage FROM ordinary_stage_abandonments s '
                          'JOIN cases c ON c.id=s.case_run').fetchall() == [(case, 'evidence.filing_metrics')]


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_a_stalled_filing_degrades_one_answer_inside_the_deadline(tmp_path):
    from validation.ordinary_isolated_rehearsal import run_rehearsal
    result = run_rehearsal(tmp_path / 'run', scenario=SLOW)
    packet = result['packet']
    assert result['status'] == 'complete' and packet['halt'] is None and packet['first_failure'] is None
    case = _degraded_case(packet)
    _assert_filing_gap(packet, case, 'time_limit')
    abandoned = [a for a in packet['attempts'] if a['status'] == 'abandoned']
    assert [(a['case_id'], a['route']) for a in abandoned] == [(case, 'sec/document')]
    assert all(a['response'] is None and a['failure']['code'] == 'abandoned' for a in abandoned)
    assert {'case_id': case, 'stage': 'evidence.filing_metrics'} in result['worker']['abandoned_evidence']
    _assert_recorded(tmp_path / 'run' / 'ledger.sqlite', case)


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_a_filing_past_the_cutoff_is_degraded_in_ledger_export_and_packet(tmp_path):
    from validation.ordinary_isolated_rehearsal import run_rehearsal
    result = run_rehearsal(tmp_path / 'run', scenario=AFTER_CUTOFF)
    packet = result['packet']
    assert result['status'] == 'complete' and packet['halt'] is None and packet['first_failure'] is None
    case = _degraded_case(packet)
    # The request finished, so nothing was abandoned on the wire; the case is still degraded.
    assert result['worker']['abandoned_evidence'] == []
    assert all(a['status'] == 'settled' for a in packet['attempts'])
    _assert_filing_gap(packet, case, 'not_read')
    _assert_recorded(tmp_path / 'run' / 'ledger.sqlite', case)


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_export_refuses_a_degraded_answer_without_its_ledger_record(tmp_path):
    from validation.ordinary_isolated_rehearsal import run_rehearsal
    from validation.ordinary_native_export import ExportRefused, export_packet
    from validation._ordinary_rehearsal_worker import REHEARSAL_RUNTIME
    output = tmp_path / 'run'
    run_rehearsal(output, scenario=AFTER_CUTOFF)
    policy = json.loads((output / 'request.json').read_text())['policy']
    with sqlite3.connect(output / 'ledger.sqlite') as db:
        db.execute('DELETE FROM ordinary_stage_abandonments')
    with pytest.raises(ExportRefused, match='degraded answer without its ledger record'):
        export_packet(output / 'ledger.sqlite', policy, forbidden_values=tuple(REHEARSAL_RUNTIME.values()),
                      synthetic=True)


# -- the live code path: real sockets, TLS and the gate, against a loopback server ----

def _loopback(tmp_path, fault, **server):
    from _ordinary_loopback_sec import LoopbackSEC
    from validation.ordinary_isolated_rehearsal import run_loopback_rehearsal
    base = tmp_path.resolve()
    with LoopbackSEC(base, fault=fault, **server) as sec:
        return run_loopback_rehearsal(base / 'run', ca=sec.ca_path), sec, base / 'run'


def _fault(scenario):
    from validation._ordinary_rehearsal_worker import SCENARIO_FAULTS
    return SCENARIO_FAULTS[scenario]


def _needs_port():
    from test_ordinary_live_launcher import _port_free
    if not _port_free():
        pytest.fail('127.0.0.1:8080 is in use; this test must not pass by skipping')


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_the_profile_uses_the_live_code_path_within_every_limit(tmp_path):
    _needs_port()
    result, sec, _ = _loopback(tmp_path, None)
    packet, worker = result['packet'], result['worker']
    assert result['status'] == 'complete' and packet['first_failure'] is None
    assert packet['attempt_count'] == packet['wire_entries'] == worker['external_dispatches'] == 45
    assert len(sec.connects) == len(sec.requests) == 45 and sec.handshake_failures == 0
    assert worker['mode'] == 'loopback' and worker['blocked_external_operations'] == []
    assert worker['refused_requests'] == [] and worker['unfinished_workers'] == 0
    assert 1 <= worker['max_inflight_sec'] <= 4


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_a_late_filing_is_degraded_on_the_live_code_path(tmp_path):
    _needs_port()
    result, _, output = _loopback(tmp_path, _fault(AFTER_CUTOFF))
    packet = result['packet']
    assert result['status'] == 'complete' and packet['first_failure'] is None
    case = _degraded_case(packet)
    _assert_filing_gap(packet, case, 'not_read')
    _assert_recorded(output / 'ledger.sqlite', case)


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_a_stalled_filing_is_degraded_on_the_live_code_path(tmp_path):
    _needs_port()
    result, _, output = _loopback(tmp_path, _fault(SLOW))
    packet = result['packet']
    assert result['status'] == 'complete' and packet['first_failure'] is None
    case = _degraded_case(packet)
    _assert_filing_gap(packet, case, 'time_limit')
    assert [(a['case_id'], a['status']) for a in packet['attempts'] if a['status'] != 'settled'] == [(case, 'abandoned')]
    _assert_recorded(output / 'ledger.sqlite', case)


def _document_fault(kind, nth=1):
    from validation._ordinary_rehearsal_worker import _FAULT_CIK
    return (kind, rf'/Archives/edgar/data/{_FAULT_CIK}/', nth)


def _assert_size_recovered(result, sec, output, kind, *, count=1):
    """One filing over the limit costs one answer its evidence, and nothing else."""
    from _ordinary_cohort_expectations import attempt_reconciliation_problems
    from _ordinary_loopback_sec import OVERSIZE_TOTAL, PARTIAL_MARKER
    packet, worker = result['packet'], result['worker']
    limit = quota_contract()['body_max_bytes']
    assert result['status'] == 'complete' and packet['halt'] is None and packet['first_failure'] is None
    # Stopped and closed by the client, long before the peer had finished sending.
    assert [(s['kind'], s['client_hung_up']) for s in sec.oversize] == [(kind, True)] * count
    assert all(s['sent'] < OVERSIZE_TOTAL for s in sec.oversize)
    # Recorded, sized and charged, with no response of any kind.
    rejections = packet['size_rejections']
    assert len(rejections) == count and worker['size_rejections'] and worker['unfinished_workers'] == 0
    for row in rejections:
        assert row['limit_bytes'] == limit and row['stage'] in {'evidence.thesis_disclosures', 'evidence.filing_metrics'}
        if kind == 'oversize_declared':
            assert (row['declared_bytes'], row['bytes_read']) == (OVERSIZE_TOTAL, 0)
        else:
            assert row['declared_bytes'] is None and limit < row['bytes_read'] <= limit + 65536
    assert attempt_reconciliation_problems(packet, quota_contract()) == []
    rejected = [a for a in packet['attempts'] if a['status'] == 'size_rejected']
    assert len(rejected) == count and all(a['response'] is None and a['route'] == 'sec/document' for a in rejected)
    # The partial body exists nowhere: not the ledger's bytes, the packet or the answers.
    assert PARTIAL_MARKER.strip(b'<p>/') not in (output / 'ledger.sqlite').read_bytes()
    assert PARTIAL_MARKER.decode().strip('<p>/') not in json.dumps(packet)
    # The answer says what it is missing and why, and does not suggest a retry.
    statuses = {c['case_id']: c['status'] for c in packet['cases']}
    for row in rejections:
        assert statuses[row['case_id']] in {'answered_degraded_unadjudicated', 'unanswered_size_rejected'}
        response = packet['answers'][row['case_id']]['response']
        source = response['answer']['source_answer']
        assert source['degraded'] is True
        # The invented filings: the thesis task reads a 10-K, the metrics task its latest 10-Q.
        expected = {'evidence.thesis_disclosures': 'the annual report (Form 10-K)',
                    'evidence.filing_metrics': 'the quarterly report (Form 10-Q)'}[row['stage']]
        assert {'source': expected, 'task': row['stage'].split('.')[1], 'reason': 'too_large'} in source['evidence_gaps']
        assert 'because the document is larger than the size limit' in json.dumps(response)
        assert 'Trying again' not in json.dumps(response)
        assert {'case_id': row['case_id'], 'stage': row['stage']} in packet['abandoned_stages']
    # Every case ran, in order, and only the affected ones lost anything.
    assert len(statuses) == 12 and 'not_run_after_halt' not in statuses.values() and 'halted' not in statuses.values()
    assert [c['status'] for c in packet['cases'] if c['case_id'] in UNRESOLVED] == ['identity_unresolved'] * len(UNRESOLVED)
    affected = {row['case_id'] for row in rejections}
    assert packet['outcome_counts']['operational_failure'] == 0 and packet['quality_pass_rate'] is None
    assert sum(packet['outcome_counts'].values()) == 12
    assert {s for c, s in statuses.items() if c not in affected and c not in UNRESOLVED} <= {
        'answered_unadjudicated', 'answered_degraded_unadjudicated'}
    # Terminal before the next case began.
    with sqlite3.connect(output / 'ledger.sqlite') as db:
        for recorded, started in db.execute(
                'SELECT r.recorded_ns,t.started_ns FROM ordinary_size_rejections r JOIN ordinary_case_times t '
                'ON t.case_run=r.case_run'):
            later = db.execute('SELECT MIN(started_ns) FROM ordinary_case_times WHERE started_ns>?', (started,)).fetchone()[0]
            assert later is None or recorded < later
    return rejections


@PROFILE_ONLY
@pytest.mark.timeout(300)
@pytest.mark.parametrize('kind', ['oversize_declared', 'oversize_chunked', 'oversize_close'])
def test_an_oversized_filing_degrades_one_answer_and_later_cases_run(tmp_path, kind):
    _needs_port()
    result, sec, output = _loopback(tmp_path, _document_fault(kind))
    _assert_size_recovered(result, sec, output, kind)


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_an_oversized_filing_in_the_threshold_case_is_recovered_too(tmp_path):
    _needs_port()
    result, sec, output = _loopback(tmp_path, _document_fault('oversize_chunked', 3))
    rejections = _assert_size_recovered(result, sec, output, 'oversize_chunked')
    assert rejections[0]['case_id'].endswith(':decision_threshold')


def _only_evidence_fault(kind, nth):
    from validation._ordinary_rehearsal_worker import _FAULT_CIK
    return _FAULT_CIK, (kind, rf'/Archives/edgar/data/{_FAULT_CIK}/[0-9]+/[a-z]+-20260630\.htm$', nth)


def _source(packet, case):
    return packet['answers'][case]['response']['answer']['source_answer']


@PROFILE_ONLY
@pytest.mark.timeout(600)
@pytest.mark.parametrize('kind, nth, case', [
    ('oversize_declared', 1, CASES[FAULT_CASE_INDEX]),
    ('oversize_chunked', 1, CASES[FAULT_CASE_INDEX]),
    ('oversize_close', 2, CASES[FAULT_CASE_INDEX + 1]),
], ids=['thesis_declared', 'thesis_chunked', 'threshold_close'])
def test_a_rejected_filing_that_was_the_only_evidence_leaves_the_case_unanswered(tmp_path, kind, nth, case):
    """No stored answer is edited. The issuer's company facts support nothing, so its filing
    alone can support an answer: the control answers from it, the rejected run cannot."""
    _needs_port()
    cik, fault = _only_evidence_fault(kind, nth)
    (tmp_path / 'control').mkdir()
    (tmp_path / 'rejected').mkdir()
    control, _, _ = _loopback(tmp_path / 'control', None, ifrs_only_cik=cik)
    assert control['status'] == 'complete' and control['packet']['size_rejections'] == []
    assert {'case_id': case, 'status': 'answered_unadjudicated'} in control['packet']['cases']
    assert _source(control['packet'], case)['status'] == 'partial' and _source(control['packet'], case)['claims']
    assert {'case_id': case, 'content': 'source_bound_claims'} in control['packet']['answer_content']['cases']

    result, sec, output = _loopback(tmp_path / 'rejected', fault, ifrs_only_cik=cik)
    packet = result['packet']
    # Export: unanswered, not degraded and not a failure; the run completes.
    assert result['status'] == 'complete' and packet['halt'] is None and packet['first_failure'] is None
    statuses = {row['case_id']: row['status'] for row in packet['cases']}
    assert statuses[case] == 'unanswered_size_rejected'
    assert packet['outcome_counts']['unanswered'] == len(UNRESOLVED) + 1
    assert packet['outcome_counts']['operational_failure'] == 0 and packet['quality_pass_rate'] is None
    assert {'case_id': case, 'content': 'insufficient_evidence'} in packet['answer_content']['cases']
    # The answer is the application's own: no claims, and it says why.
    source = _source(packet, case)
    assert source['status'] == 'insufficient_claim_evidence' and source['claims'] == [] and source['degraded'] is True
    assert source['evidence_gaps'] == [{'source': 'the quarterly report (Form 10-Q)', 'task': 'filing_metrics', 'reason': 'too_large'}]
    response = json.dumps(packet['answers'][case]['response'])
    assert 'because the document is larger than the size limit' in response and 'Trying again' not in response
    # Worker: one rejection, every worker finished, and the peer was cut off.
    rejection, = packet['size_rejections']
    assert (rejection['case_id'], rejection['stage']) == (case, 'evidence.filing_metrics')
    assert [(r['case_id'], r['stage']) for r in result['worker']['size_rejections']] == [(case, 'evidence.filing_metrics')]
    assert result['worker']['unfinished_workers'] == 0 and result['worker']['failure_class'] is None
    assert [(s['kind'], s['client_hung_up']) for s in sec.oversize] == [(kind, True)]
    # Ledger: the same outcome durably, with nothing of the body retained, the rejected
    # attempt ended before the next case began, and every later case answered.
    with sqlite3.connect(output / 'ledger.sqlite') as db:
        assert db.execute('SELECT halted FROM policy').fetchone() == (None,)
        assert db.execute('SELECT c.case_id,r.stage,r.bytes_read>0 OR r.declared_bytes>r.limit_bytes FROM ordinary_size_rejections r '
                          'JOIN cases c ON c.id=r.case_run').fetchall() == [(case, 'evidence.filing_metrics', 1)]
        attempt, recorded = db.execute('SELECT attempt_id,recorded_ns FROM ordinary_size_rejections').fetchone()
        assert db.execute('SELECT status FROM attempts WHERE id=?', (attempt,)).fetchone() == ('size_rejected',)
        assert db.execute('SELECT COUNT(*) FROM ordinary_responses WHERE attempt_id=?', (attempt,)).fetchone() == (0,)
        assert db.execute('SELECT COUNT(*) FROM cases').fetchone() == (12,)
        assert db.execute("SELECT COUNT(*) FROM cases WHERE status!='complete'").fetchone() == (0,)
        following = CASES[CASES.index(case) + 1]
        started, = db.execute('SELECT t.started_ns FROM ordinary_case_times t JOIN cases c ON c.id=t.case_run '
                              'WHERE c.case_id=?', (following,)).fetchone()
        assert recorded < started
    # Other cases read their filings as before, including this filing in the sibling
    # case, because nothing is remembered between cases.
    sibling = CASES[FAULT_CASE_INDEX + 1 if nth == 1 else FAULT_CASE_INDEX]
    assert statuses[sibling] == 'answered_unadjudicated' and _source(packet, sibling)['status'] == 'partial'


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_a_completed_insufficient_evidence_response_is_not_counted_as_content(tmp_path):
    """No rejection and no gap: operationally it keeps its historic name, and the separate
    content record says it delivered no answer to the question."""
    from validation._ordinary_rehearsal_worker import _FAULT_CIK
    _needs_port()
    case = CASES[FAULT_CASE_INDEX]
    result, _, _ = _loopback(tmp_path, None, ifrs_only_cik=_FAULT_CIK, inline_filing=False)
    packet = result['packet']
    assert result['status'] == 'complete' and packet['size_rejections'] == []
    # The misleading operational label, preserved.
    assert {'case_id': case, 'status': 'answered_unadjudicated'} in packet['cases']
    assert _source(packet, case)['status'] == 'insufficient_claim_evidence' and _source(packet, case)['claims'] == []
    content = packet['answer_content']
    assert {'case_id': case, 'content': 'insufficient_evidence'} in content['cases']
    counts = content['counts']
    assert counts['insufficient_evidence'] >= 1 and counts['identity_unresolved'] == len(UNRESOLVED)
    assert sum(counts.values()) == 12 and counts['unclassified'] == 0
    assert counts['source_bound_claims'] < packet['outcome_counts']['full_answer']
    assert 'accuracy and usefulness are assessed separately' in content['scope']
    assert packet['quality_pass_rate'] is None


@pytest.mark.parametrize('status, payload, expected', [
    ('not_run_after_halt', None, 'not_run'),
    ('not_run', None, 'not_run'),
    ('halted', None, 'no_answer'),
    ('identity_unresolved', {'company': '', 'answer': {'source_answer': {'status': 'unresolved_company_identity'}}}, 'identity_unresolved'),
    ('answered_unadjudicated', {'answer': {'source_answer': {'status': 'insufficient_claim_evidence', 'claims': []}}}, 'insufficient_evidence'),
    ('answered_degraded_unadjudicated', {'answer': {'source_answer': {'status': 'insufficient_claim_evidence', 'claims': []}}}, 'insufficient_evidence'),
    ('unanswered_size_rejected', {'answer': {'source_answer': {'status': 'insufficient_claim_evidence', 'claims': []}}}, 'insufficient_evidence'),
    ('answered_unadjudicated', {'answer': {'source_answer': {'status': 'partial', 'claims': [{'text': 'x'}]}}}, 'source_bound_claims'),
    ('answered_unadjudicated', {'answer': {'source_answer': {'status': 'attributed', 'claims': [{'text': 'x'}]}}}, 'source_bound_claims'),
    # Never counted as content without source-bound claims, whatever the status says.
    ('answered_unadjudicated', {'answer': {'source_answer': {'status': 'partial', 'claims': []}}}, 'unclassified'),
    ('answered_unadjudicated', {'answer': {}}, 'unclassified'),
])
def test_only_source_bound_claims_count_as_answer_content(status, payload, expected):
    from validation.ordinary_native_export import answer_content
    assert answer_content(status, payload) == expected


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_a_ledger_from_before_the_split_exports_without_the_content_record(tmp_path):
    from validation.ordinary_native_export import export_packet
    from validation._ordinary_rehearsal_worker import REHEARSAL_RUNTIME
    _needs_port()
    result, _, output = _loopback(tmp_path, None)
    policy = json.loads((output / 'request.json').read_text())['policy']
    copy = tmp_path / 'older.sqlite'
    copy.write_bytes((output / 'ledger.sqlite').read_bytes())
    with sqlite3.connect(copy) as db:
        db.execute('DROP TABLE ordinary_size_rejections')
    older = export_packet(copy, policy, forbidden_values=tuple(REHEARSAL_RUNTIME.values()),
                          synthetic=result['packet']['synthetic_sec_backend'])
    new_fields = {'answer_content', 'size_rejections'}
    assert not new_fields & set(older)
    assert {key: value for key, value in result['packet'].items() if key not in new_fields} == older


@PROFILE_ONLY
@pytest.mark.timeout(300)
@pytest.mark.parametrize('route, pattern', [
    ('facts', r'/companyfacts/CIK{cik:010d}\.json$'),
    ('submissions', r'/submissions/CIK{cik:010d}\.json$'),
    ('directory', r'/files/company_tickers\.json$'),
])
def test_oversized_facts_are_not_a_filing_and_still_halt(tmp_path, route, pattern):
    from validation._ordinary_rehearsal_worker import _FAULT_CIK
    _needs_port()
    result, sec, _ = _loopback(tmp_path, ('oversize_close', pattern.format(cik=_FAULT_CIK), 1))
    packet = result['packet']
    assert result['status'] != 'complete' and packet['halt'] == 'post_claim_failure'
    assert packet['first_failure']['code'] == 'response_size' and packet['size_rejections'] == []
    assert not [a for a in packet['attempts'] if a['status'] == 'size_rejected']
    assert 'halted' in {c['status'] for c in packet['cases']}
    assert packet['outcome_counts']['operational_failure'] >= 1


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_oversized_recovery_reaches_the_approved_outcome_record(approved, tmp_path, monkeypatch):
    """Launcher, package, approval and outcome writing, with the same worker on loopback."""
    from validation import ordinary_approved as launcher
    paths, _, output = approved
    seen = {}

    def loopback_worker(out, policy, **kwargs):
        loopback = tmp_path / 'loopback'
        loopback.mkdir()
        result, sec, run = _loopback(loopback, _document_fault('oversize_close'))
        seen.update(sec=sec, run=run, kwargs=kwargs)
        return result

    _needs_port()
    monkeypatch.setattr(launcher, 'run_worker', loopback_worker)
    result = launcher.execute(**paths)
    assert seen['kwargs']['mode'] == 'approved' and seen['kwargs']['synthetic'] is False
    packet = json.loads((output / 'packet.json').read_text())
    rejections = _assert_size_recovered({'status': 'complete', 'packet': packet, 'worker': json.loads(
        (seen['run'] / 'worker.json').read_text())}, seen['sec'], seen['run'], 'oversize_close')
    assert {'case_id': rejections[0]['case_id'], 'status': 'answered_degraded_unadjudicated'} in result['outcomes']
    assert len(result['outcomes']) == 12


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_the_export_refuses_a_size_rejection_that_does_not_reconcile(tmp_path):
    from _ordinary_loopback_sec import PARTIAL_MARKER
    from validation.ordinary_native_export import ExportRefused, export_packet
    from validation._ordinary_rehearsal_worker import REHEARSAL_RUNTIME
    _needs_port()
    result, _, output = _loopback(tmp_path, _document_fault('oversize_close'))
    policy = json.loads((output / 'request.json').read_text())['policy']
    forbidden = tuple(REHEARSAL_RUNTIME.values())
    ledger = output / 'ledger.sqlite'
    attempt = next(a['attempt_id'] for a in result['packet']['attempts'] if a['status'] == 'size_rejected')
    url = result['packet']['size_rejections'][0]['url']
    tampers = {
        'row_deleted': ('DELETE FROM ordinary_size_rejections WHERE attempt_id=?', (attempt,)),
        'status_changed': ("UPDATE attempts SET status='abandoned' WHERE id=?", (attempt,)),
        'failure_changed': ("UPDATE ordinary_exchange_failures SET detail='sec/document' WHERE attempt_id=?", (attempt,)),
        'other_url': ("UPDATE ordinary_size_rejections SET url=url||'x' WHERE attempt_id=?", (attempt,)),
        'other_limit': ('UPDATE ordinary_size_rejections SET limit_bytes=limit_bytes*2 WHERE attempt_id=?', (attempt,)),
        'under_limit': ('UPDATE ordinary_size_rejections SET declared_bytes=NULL,bytes_read=8 WHERE attempt_id=?', (attempt,)),
        'over_read': ('UPDATE ordinary_size_rejections SET declared_bytes=NULL,bytes_read=limit_bytes*2 WHERE attempt_id=?', (attempt,)),
        'never_on_wire': ('DELETE FROM ordinary_wire_entries WHERE attempt_id=?', (attempt,)),
        'partial_retained': ("INSERT INTO ordinary_responses VALUES (?,?,200,'text/html','0',?,1)", (attempt, url, PARTIAL_MARKER)),
        'closed_after_next_case': ('UPDATE ordinary_size_rejections SET recorded_ns=recorded_ns+1000000000000 WHERE attempt_id=?', (attempt,)),
    }
    for name, (sql, values) in tampers.items():
        copy = tmp_path / f'{name}.sqlite'
        copy.write_bytes(ledger.read_bytes())
        with sqlite3.connect(copy) as db:
            db.execute(sql, values)
        with pytest.raises(ExportRefused):
            export_packet(copy, policy, forbidden_values=forbidden, synthetic=False)
    # An answer that stops declaring the rejected filing is refused as well.
    case = result['packet']['size_rejections'][0]['case_id']
    payload = json.loads(json.dumps(result['packet']['answers'][case]['response']))
    payload['answer']['source_answer'].pop('degraded')
    def rewrite(copy, payload):
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        with sqlite3.connect(copy) as db:
            db.execute('UPDATE ordinary_answers SET payload=?,sha256=? WHERE case_id=?',
                       (raw, hashlib.sha256(raw).hexdigest(), case))
    copy = tmp_path / 'undeclared.sqlite'
    copy.write_bytes(ledger.read_bytes())
    rewrite(copy, payload)
    with pytest.raises(ExportRefused):
        export_packet(copy, policy, forbidden_values=forbidden, synthetic=False)
    # The application saying too little evidence remains makes the case unanswered.
    payload = json.loads(json.dumps(result['packet']['answers'][case]['response']))
    payload['answer']['source_answer']['status'] = 'insufficient_claim_evidence'
    copy = tmp_path / 'insufficient.sqlite'
    copy.write_bytes(ledger.read_bytes())
    rewrite(copy, payload)
    packet = export_packet(copy, policy, forbidden_values=forbidden, synthetic=False)
    assert {'case_id': case, 'status': 'unanswered_size_rejected'} in packet['cases']
    assert packet['status'] == 'complete' and packet['outcome_counts']['operational_failure'] == 0
    assert packet['outcome_counts']['unanswered'] == len(UNRESOLVED) + 1


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_a_failed_filing_list_halts_on_the_live_code_path(tmp_path):
    # In a pilot a failed SEC request is never a gap in an answer: the run halts and
    # names the first failure.
    from validation._ordinary_rehearsal_worker import _FAULT_CIK
    _needs_port()
    result, _, _ = _loopback(tmp_path, ('close', rf'/submissions/CIK{_FAULT_CIK:010d}\.json$', 1))
    packet = result['packet']
    assert result['status'] == 'halted' and packet['status'] == 'halted'
    assert packet['first_failure']['route'] == 'sec/submissions'
    assert packet['outcome_counts']['degraded_answer'] == 0
    assert 'not_run_after_halt' in {c['status'] for c in packet['cases']}


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_a_silent_peer_halts_on_the_live_code_path(tmp_path):
    # No bytes inside the transport's 10 s read timeout is a transport failure, which
    # fails closed for the whole run. Only a filing still arriving can degrade one answer.
    _needs_port()
    kind, path, nth = _fault(AFTER_CUTOFF)
    result, _, _ = _loopback(tmp_path, ('silent', path, nth))
    packet = result['packet']
    assert result['status'] == 'halted' and packet['first_failure']['code'] == 'read_timeout'
    assert packet['first_failure']['route'] == 'sec/document'
    assert packet['outcome_counts']['degraded_answer'] == 0


# -- the approved launcher ---------------------------------------------------------

@pytest.fixture
def approved(tmp_path, monkeypatch):
    from test_ordinary_live_launcher import build_approved_inputs
    return build_approved_inputs(tmp_path, monkeypatch, network='proxy')


@PROFILE_ONLY
@pytest.mark.parametrize('selected', ['run5', 'run3', 'runs-1-2'])
def test_a_selected_cohort_is_refused_even_with_a_complete_package(approved, monkeypatch, selected):
    # Consumed cohorts stay exportable through a selection; none can be packaged or run.
    from validation import ordinary_approved as launcher
    paths, files, output = approved
    assert launcher.check(**paths)
    monkeypatch.setenv('ORDINARY_PILOT_COHORT', selected)
    with pytest.raises(BudgetError, match='rehearsals only'):
        launcher.check(**paths)
    with pytest.raises(BudgetError, match='rehearsals only'):
        launcher.execute(**paths)
    with pytest.raises(BudgetError, match='rehearsals only'):
        launcher.prepare(execution_path=files['execution'], cost_path=files['cost'],
                         retention_path=files['retention'], output_dir=output.parent / 'other-run')
    assert not output.exists()


@PROFILE_ONLY
@pytest.mark.timeout(120)
def test_the_approved_worker_itself_refuses_a_selected_cohort(approved):
    from validation import ordinary_approved as launcher
    from validation.ordinary_isolated_rehearsal import run_worker
    from validation.ordinary_native_ledger import create_fresh_output
    paths, _, _ = approved
    policy, runtime = launcher.check(**paths)
    output = create_fresh_output(policy['approval']['output_dir'])
    result = run_worker(output, policy, mode='approved', scenario='approved',
                        environment={**runtime, 'ORDINARY_PILOT_COHORT': 'run5'},
                        forbidden=tuple(runtime.values()), synthetic=False)
    assert result['status'] == 'worker_incomplete' and result['supervisor']['returncode'] == 2
    assert not (output / 'ledger.sqlite').exists()


@PROFILE_ONLY
@pytest.mark.parametrize('change', [
    lambda p: p.update(case_order=list(reversed(p['case_order']))),
    lambda p: p.update(cohort='run5'),
    lambda p: p.update(questions_sha256='0' * 64),
    lambda p: p['frontend'].update(commit='84466b2926c5e231b322db7f6a363763de544a95'),
    lambda p: p['frontend'].update(classifier_sha256='0' * 64),
    lambda p: p['frontend'].update(resolver_sha256='0' * 64),
], ids=['order', 'cohort', 'questions', 'frontend_commit', 'classifier', 'resolver'])
def test_the_launcher_refuses_a_profile_that_differs_from_what_runs(approved, monkeypatch, change):
    from validation import ordinary_approved as launcher, ordinary_pilot_contract as contract
    paths, _, _ = approved
    profile = contract.contract_profile()
    change(profile)
    monkeypatch.setattr(launcher, 'contract_profile', lambda: profile)
    with pytest.raises(BudgetError, match='differs from the running cohort or frontend pin'):
        launcher.require_profile_binding()
    with pytest.raises(BudgetError, match='differs from the running cohort or frontend pin'):
        launcher.check(**paths)


def test_nothing_lifts_the_cohort_check():
    source = (ROOT / 'validation' / 'ordinary_approved.py').read_text()
    definition = re.search(r"def require_approved_cohort\(\):\n(?:    .*\n)+", source)[0]
    assert "COHORT != APPROVED_COHORT or 'ORDINARY_PILOT_COHORT' in os.environ" in definition
    assert source.count('require_approved_cohort()') == 3  # the definition, prepare and check
    for path in (*(ROOT / 'validation').glob('*.py'), *(ROOT / 'app').rglob('*.py'), *(ROOT / 'scripts').glob('*.py'),
                 *(path for path in (ROOT / 'tests').glob('*.py') if path.name != Path(__file__).name)):
        assert "'require_approved_cohort'" not in path.read_text(), path.name


@PROFILE_ONLY
@pytest.mark.parametrize('field,value', [('contract_profile', {'name': 'another'}), ('cohort', 'run5'),
                                         ('selected_cohort', 'run5')])
def test_a_package_cannot_select_a_profile_or_cohort(approved, field, value):
    # Limits, policy and evidence all come from the running code, and check rebuilds the
    # package from them, so no field in a package can choose either.
    from validation import ordinary_approved as launcher
    paths, files, _ = approved
    package = json.loads(files['package'].read_text())
    package['proposal'][field] = value
    files['package'].write_text(json.dumps(package))
    with pytest.raises(BudgetError, match='package differs'):
        launcher.check(**paths)


@PROFILE_ONLY
def test_the_package_and_policy_bind_the_profile(approved):
    from validation import ordinary_approved as launcher
    paths, files, _ = approved
    package = json.loads(files['package'].read_text())
    assert package['proposal']['contract_profile'] == THRESHOLD_FILING_PROFILE
    assert package['proposal']['limits'] == quota_contract()
    assert package['proposal']['case_seconds'] == {'core_thesis': 30, 'decision_threshold': 20}
    policy, _ = launcher.check(**paths)
    assert policy['configuration']['settings']['threshold_filing_explanations_enabled'] is True
    assert policy['stage_quotas'] == quota_contract()['per_stage']
    cost = launcher.derived_evidence('cost')
    assert cost['contract_profile'] == THRESHOLD_FILING_PROFILE
    assert cost['sec_gets_per_case'] == {case: 6 if case.endswith(':core_thesis') else 5 for case in CASES}
    assert all(test in cost['enforced_by'] for test in launcher.PROFILE_ENFORCED_BY)
    for test in launcher.PROFILE_ENFORCED_BY:
        path, name = test.split('::')
        assert f'def {name}(' in (ROOT / path).read_text(), test


@PROFILE_ONLY
@pytest.mark.parametrize('change', [
    lambda p: p['proposal']['contract_profile'].update(filing_wait_seconds=20),
    lambda p: p['proposal']['contract_profile'].update(filing_parse_cutoff_seconds=16),
    lambda p: p['proposal']['contract_profile'].update(switch='another_switch'),
    lambda p: p['proposal']['contract_profile'].update(cohort='run5'),
    lambda p: p['proposal'].pop('contract_profile'),
    lambda p: p['proposal']['limits']['per_case'][CASES[0]].update(sec=8),
    lambda p: p['proposal']['case_seconds'].update(decision_threshold=30),
], ids=['wait', 'cutoff', 'switch', 'cohort', 'no_profile', 'quota', 'deadline'])
def test_check_refuses_a_package_with_a_changed_profile(approved, change):
    from validation import ordinary_approved as launcher
    paths, files, _ = approved
    package = json.loads(files['package'].read_text())
    change(package)
    files['package'].write_text(json.dumps(package))
    with pytest.raises(BudgetError, match='package differs'):
        launcher.check(**paths)


@PROFILE_ONLY
def test_an_approval_for_another_package_is_refused(approved):
    from validation import ordinary_approved as launcher
    paths, files, _ = approved
    approval = json.loads(files['approval'].read_text())
    approval['manifest_sha256'] = digest({'another': 'package'})
    files['approval'].write_text(json.dumps(approval))
    with pytest.raises(BudgetError):
        launcher.check(**paths)


@PROFILE_ONLY
def test_the_separate_approval_check_refuses_a_changed_profile(approved):
    from validation.ordinary_execution_contract import matches_separate_approval
    _, files, _ = approved
    manifest = json.loads(files['package'].read_text())['proposal']
    manifest['contract_profile'] = {**manifest['contract_profile'], 'filing_wait_seconds': 20}
    with pytest.raises(ValueError):
        matches_separate_approval(manifest, {})


@PROFILE_ONLY
@pytest.mark.timeout(300)
def test_degradation_reaches_the_approved_outcome_record(approved, tmp_path, monkeypatch):
    """The real launcher, real package, approval and outcome writing. Only the worker's
    network is substituted: approved mode can reach nothing but the real SEC, so the
    same worker code runs in loopback mode and returns its result to the launcher."""
    from validation import ordinary_approved as launcher
    paths, _, output = approved
    calls = []

    def loopback_worker(out, policy, **kwargs):
        calls.append((out, policy, kwargs))
        loopback = tmp_path / 'loopback'
        loopback.mkdir()
        return _loopback(loopback, _fault(AFTER_CUTOFF))[0]

    _needs_port()
    monkeypatch.setattr(launcher, 'run_worker', loopback_worker)
    result = launcher.execute(**paths)
    (out, policy, kwargs), = calls
    assert out == output and kwargs['mode'] == 'approved' and kwargs['synthetic'] is False
    assert policy['configuration']['settings']['threshold_filing_explanations_enabled'] is True
    assert policy['approval']['reference'] == 'APPROVAL-2026-0001'
    packet = json.loads((output / 'packet.json').read_text())
    case = _degraded_case(packet)
    _assert_filing_gap(packet, case, 'not_read')
    assert {'case_id': case, 'status': 'answered_degraded_unadjudicated'} in result['outcomes']
    assert packet['execution_authorized'] is False
    with pytest.raises(BudgetError):
        launcher.execute(**paths)  # the directory now exists: the approval is spent
