"""The threshold-filing contract profile: bound, refused when altered, and honest.

Everything runs against invented SEC responses and invented approvals. The rehearsal
cohort reuses the runs-1-2 questions and is never APPROVED_COHORT. Nothing here is
real-company evidence or authority to run a pilot.

Tests of the profile run in a child process that selects its cohort, because the
cohort is fixed at import. That child also runs every other ordinary test, so each
existing refusal is exercised under the profile.
"""
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

import pytest

from validation.capture_budget import BudgetError, digest
from validation.ordinary_native_boundary import verify_contract_profile
from validation.ordinary_native_ledger import CASE_SECONDS, degraded_stages
from validation.ordinary_pilot_contract import (APPROVED_COHORT, CASES, COHORT, THRESHOLD_FILING_PROFILE,
                                                contract_profile, quota_contract)

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_ONLY = pytest.mark.skipif(COHORT != APPROVED_COHORT, reason='runs in the original-contract process')
PROFILE_ONLY = pytest.mark.skipif(contract_profile() is None, reason='runs in the profile child process')
SLOW, AFTER_CUTOFF = 'threshold_filing_slow', 'threshold_filing_after_cutoff'
NOTICE = 'Incomplete answer: the latest SEC filing could not be read for this answer'


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
    from validation.ordinary_isolated_rehearsal import rehearsal_policy, run_worker
    from validation.ordinary_native_ledger import create_fresh_output
    from validation._ordinary_rehearsal_worker import REHEARSAL_RUNTIME
    output = create_fresh_output(tmp_path / 'run')
    policy = rehearsal_policy(output)
    policy['configuration']['settings']['threshold_filing_explanations_enabled'] = True
    result = run_worker(output, policy, mode='rehearsal', scenario='happy', environment={},
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
    assert profile['name'] == 'threshold_filing_v1' and profile['cohort'] != APPROVED_COHORT
    assert profile['sec_gets_per_case'] == {'core_thesis': 6, 'decision_threshold': 5} and profile['sec_gets'] == 66
    assert profile['switch'] == 'threshold_filing_explanations_enabled'
    assert profile['filing_parse_cutoff_seconds'] < profile['filing_wait_seconds'] < profile['case_seconds']['decision_threshold']
    assert profile['case_seconds'] == CASE_SECONDS
    from app.services import router_service
    assert router_service.THRESHOLD_DOCUMENT_WAIT_SECONDS == profile['filing_wait_seconds']
    assert router_service.THRESHOLD_FILING_PARSE_CUTOFF_SECONDS == profile['filing_parse_cutoff_seconds']


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


@ORIGINAL_ONLY
@pytest.mark.timeout(1800)
def test_the_ordinary_tests_pass_under_the_profile():
    # The native ledger, boundary and contract tests build their own requests against the
    # original quota shape; the profile's limits are proven below and by these suites.
    tests = [f'tests/test_ordinary_{name}.py' for name in
             ('contract_profile', 'live_launcher', 'isolated_worker', 'execution_contract')]
    done = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-o', 'addopts=',
                           '--disable-warnings', '--tb=short', *tests], cwd=ROOT,
                          env={**os.environ, 'ORDINARY_PILOT_COHORT': THRESHOLD_FILING_PROFILE['cohort']},
                          capture_output=True, text=True, timeout=1750)
    assert done.returncode == 0, done.stdout[-6000:] + done.stderr[-2000:]


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
    assert packet['attempt_count'] == 54 and result['worker']['refused_requests'] == []
    routes = {}
    for attempt in packet['attempts']:
        assert attempt['status'] == 'settled'
        routes[attempt['case_id'], attempt['route']] = routes.get((attempt['case_id'], attempt['route']), 0) + 1
    for case in CASES:
        assert routes[case, 'sec/submissions'] == 1
        assert routes[case, 'sec/document'] == (2 if case.endswith(':core_thesis') else 1)


def _degraded_case(packet):
    degraded = [c['case_id'] for c in packet['cases'] if c['status'] == 'answered_degraded_unadjudicated']
    assert len(degraded) == 1 and degraded[0].endswith(':decision_threshold')
    assert packet['outcome_counts']['degraded_answer'] == 1 and packet['quality_pass_rate'] is None
    return degraded[0]


def _assert_filing_gap(packet, case, reason):
    source = packet['answers'][case]['response']['answer']['source_answer']
    assert source['degraded'] is True
    assert source['evidence_gaps'] == [{'source': 'the latest SEC filing', 'task': 'filing_metrics', 'reason': reason}]
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

def _loopback(tmp_path, fault):
    from _ordinary_loopback_sec import LoopbackSEC
    from validation.ordinary_isolated_rehearsal import run_loopback_rehearsal
    base = tmp_path.resolve()
    with LoopbackSEC(base, fault=fault) as sec:
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
    assert packet['attempt_count'] == packet['wire_entries'] == worker['external_dispatches'] == 54
    assert len(sec.connects) == len(sec.requests) == 54 and sec.handshake_failures == 0
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
def test_the_launcher_refuses_the_rehearsal_cohort(tmp_path, monkeypatch):
    from validation import ordinary_approved as launcher
    with pytest.raises(BudgetError, match='rehearsals only'):
        launcher.require_approved_cohort()


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
    lambda p: p['proposal']['contract_profile'].update(cohort=APPROVED_COHORT),
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
