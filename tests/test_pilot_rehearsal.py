"""Actual pipeline in fresh invented-credential children; all sockets blocked."""
from collections import Counter
import json
from pathlib import Path
import sqlite3

import pytest

from validation.capture_budget import AttemptLedger, BudgetError
from validation.pilot_fixtures import SCENARIOS, SECRET_CANARIES
from validation.pilot_preflight import preflight
from validation.pilot_rehearsal import run_rehearsal


@pytest.fixture(scope='module')
def rehearsals(tmp_path_factory):
    root = tmp_path_factory.mktemp('integrated-pilot')
    results = {}
    def run(scenario):
        if scenario not in results:
            output = root / scenario
            results[scenario] = (run_rehearsal(output, scenario=scenario), output)
        return results[scenario]
    return run


@pytest.mark.parametrize('scenario', ['happy', 'concurrency', 'sdk_copy_valid'])
def test_actual_six_case_pipeline_completes_with_zero_network(rehearsals, scenario):
    result, output = rehearsals(scenario)
    assert result['status'] == 'complete'
    assert result['network_attempts'] == result['external_dispatches'] == 0
    assert result['diagnostics_canary_clean']
    assert result['sec_configured_contact_applied']
    assert all(count > 0 for count in result['transport_entries'].values())
    assert result['ledger']['unresolved_attempts'] == 0
    assert result['ledger']['halted'] is None
    assert [case['case_id'] for case in result['completed_cases']] == [
        case['case_id'] for case in preflight()['cases']]
    npk = [case for case in result['completed_cases'] if case['identity']['ticker'] == 'NPK']
    assert len(npk) == 2
    assert all(case['identity']['cik'] == '0000080172' for case in npk)
    counts = Counter(event['route'].split('/')[0] for event in result['claims'])
    assert counts == {'model': 16, 'sec': 27}
    for case in preflight()['cases']:
        case_id = case['case_id']
        limits = result['quotas']['per_case'][case_id]
        claims = [event for event in result['claims'] if event['case_id'] == case_id]
        by_route = Counter(event['route'] for event in claims)
        assert all(count <= limits[route] for route, count in by_route.items())
        if case_id.endswith(':core_thesis'):
            assert not any(event['route'].startswith('model/') for event in claims)
        for event in claims:
            if event['route'].startswith('model/'):
                assert event['input_reservation_tokens'] == 128_000
                assert event['output_bound_tokens'] == (1536 if event['route'] == 'model/synthesis' else 4096)
    assert result['excluded_providers'] == ['fmp', 'newsapi', 'fred']
    assert len(result['coverage_gaps']) == 3
    assert result['quality_status'] == 'not_adjudicated'
    for flag in ('execution_allowed', 'spending_authorized', 'tariffs_verified',
                 'all_incremental_charges_accounted', 'hard_usd_cap_established', 'launch_ready'):
        assert result[flag] is False
    assert result['configuration']['token_framing_verified_for_live'] is False
    if scenario == 'concurrency':
        assert result['max_concurrent_claims'] >= 6
    # SQL, artifacts and import-created state must never contain fixture keys,
    # contact strings, echoed secrets or request-header material.
    for path in output.rglob('*'):
        if path.is_file():
            contents = path.read_bytes()
            assert not any(value.encode() in contents for value in SECRET_CANARIES)
    with sqlite3.connect(output / 'ledger.sqlite') as db:
        times = [row[0] for row in db.execute('SELECT claimed_ns FROM sec_claims ORDER BY claimed_ns')]
    assert all(times[i + 10] - times[i] >= 1_000_000_000 for i in range(len(times) - 10))


FAULTS = sorted(SCENARIOS - {'happy', 'concurrency', 'sdk_copy_valid', 'crash_after_claim'})


@pytest.mark.parametrize('scenario', FAULTS)
def test_integrated_faults_halt_without_fallback_dispatch_or_refund(rehearsals, scenario):
    result, output = rehearsals(scenario)
    assert result['status'] == 'halted'
    assert result['ledger']['halted']
    assert result['external_dispatches'] == 0
    assert result['network_attempts'] == (1 if scenario in {'socket_attempt', 'unknown_dns'} else 0)
    assert result['diagnostics_canary_clean']
    assert result['execution_allowed'] is False
    assert result['ledger']['attempts'] == len(result['claims'])
    assert len(result['completed_cases']) < 6
    before = result['ledger']
    policy = json.loads((output / 'request.json').read_text())['policy']
    reopened = AttemptLedger(output / 'ledger.sqlite', policy)
    assert reopened.summary()['reserved_nanousd'] == before['reserved_nanousd']
    with pytest.raises(BudgetError):
        reopened.begin_case('NPK:decision_threshold')
    assert reopened.summary()['attempts'] == before['attempts']
    models = [event for event in result['claims'] if event['route'].startswith('model/')]
    if scenario in {'model_429', 'model_500', 'missing_usage', 'excess_usage',
                    'model_mismatch', 'tier_mismatch', 'unknown_usage', 'secret_reflection', 'duplicate_stage'}:
        assert len(models) == 1  # No SDK or application retry can claim again.
    if scenario in {'oversize_input', 'unknown_model_route', 'sdk_copy_retry',
                    'sdk_retry_drift', 'configuration_drift', 'request_secret',
                    'custom_request_header', 'sec_post', 'sec_body'}:
        assert len(models) == 0
    if scenario in {'evidence_timeout', 'partial_pool_failure'}:
        assert before['attempts'] == 1
        assert before['unresolved_attempts'] == 0  # Late claimed SEC result settled after halt.
        assert result['blocked_after_halt'] > 0
    if scenario == 'agent_timeout':
        assert len(models) == 1
        assert before['unresolved_attempts'] == 0
        assert not any(event['route'] == 'model/synthesis' for event in models)
    if scenario == 'synthesis_timeout':
        assert sum(event['route'] == 'model/synthesis' for event in models) == 1
        assert before['unresolved_attempts'] == 0  # No second synthesis after timeout.
    if scenario == 'concurrent_usage_failure':
        assert result['max_concurrent_claims'] >= 6
        assert before['unresolved_attempts'] == 1
        assert sum(event['case_id'] == 'ACHC:decision_threshold' for event in models) == 6
        assert not any(event['case_id'] == 'ACHC:decision_threshold'
                       and event['route'] == 'model/synthesis' for event in models)
    for path in output.rglob('*'):
        if path.is_file():
            assert not any(value.encode() in path.read_bytes() for value in SECRET_CANARIES)


def test_hard_process_crash_retains_claim_and_cannot_restart(rehearsals):
    result, output = rehearsals('crash_after_claim')
    assert result['status'] == 'worker_incomplete'
    assert result['network_attempts'] is None  # No invented completed audit after a crash.
    assert result['ledger']['halted'] == 'reopen_requires_review'
    assert result['ledger']['unresolved_attempts'] == 1
    assert result['ledger']['reserved_nanousd'] > 0
    assert result['execution_allowed'] is False
    with pytest.raises(FileExistsError):
        run_rehearsal(output)
    with sqlite3.connect(output / 'ledger.sqlite') as db:
        assert db.execute("SELECT COUNT(*) FROM attempts WHERE status='claimed'").fetchone()[0] == 1


def test_parent_configuration_and_credentials_are_not_inherited(tmp_path, monkeypatch):
    # Invented parent values stand in for credentials; never read real values.
    parent_canary = 'invented-parent-environment-must-not-enter-worker'
    for key in ('OPENAI_API_KEY', 'SEC_USER_AGENT', 'FMP_API_KEY', 'NEWS_API_KEY', 'FRED_API_KEY',
                'HTTPS_PROXY', 'OPENAI_BASE_URL', 'OPENAI_LOG', 'AGENT_MODEL', 'SYNTHESIS_MODEL'):
        monkeypatch.setenv(key, parent_canary)
    monkeypatch.setenv('CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED', 'true')
    (tmp_path / '.env').write_text('OPENAI_API_KEY=' + parent_canary)
    monkeypatch.chdir(tmp_path)
    result = run_rehearsal(tmp_path / 'new-isolated-child')
    assert result['status'] == 'complete'
    assert result['network_attempts'] == 0
    for path in (tmp_path / 'new-isolated-child').rglob('*'):
        if path.is_file():
            assert parent_canary.encode() not in path.read_bytes()


def test_no_unreviewed_scenario_or_output_overwrite(tmp_path):
    with pytest.raises(BudgetError):
        run_rehearsal(tmp_path / 'not-created', scenario='live')
    assert not (tmp_path / 'not-created').exists()
    output = tmp_path / 'existing'
    output.mkdir()
    with pytest.raises(FileExistsError):
        run_rehearsal(output)
    assert not list(output.iterdir())
