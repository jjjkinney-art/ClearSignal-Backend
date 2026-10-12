"""Synthetic prices only. These tests never authorize or execute provider requests."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import subprocess
import sys

import pytest

from validation.capture_budget import AttemptLedger, BudgetError, money, preflight, setup_binding


@pytest.fixture
def policy():
    return dict(schema_version=1, pilot_id='offline-fixture', approval_reference='synthetic-only',
                configuration_version='fixture-v1', pricing_review_reference='synthetic-only',
                budget_usd='1', maximum_attempts=10,
                approved_case_ids=['ASML:core_thesis', 'NPK:decision_threshold'],
                setup_sha256=setup_binding(), prices={'fixture/model': dict(
                    currency='USD', all_incremental_charges_accounted=True,
                    request_usd='0.1', input_token_usd='0.01', output_token_usd='0.02',
                    maximum_input_tokens=10, maximum_output_tokens=10)})


def ledger(tmp_path, policy):
    return AttemptLedger(tmp_path / 'ledger.db', policy, create=True)


def reserve(book, run, **kw):
    return book.reserve(run, 'fixture/model', input_bound=kw.get('input_bound', 10),
                        output_bound=kw.get('output_bound', 10))


@pytest.mark.parametrize('value', [1, 1.2, True, '-1', 'NaN', 'Infinity', '1e100'])
def test_invalid_money(value):
    with pytest.raises(BudgetError):
        money(value)


def test_rounds_up():
    assert money('0.0000000001') == 1


def test_restart_retains_reservations_and_immutable_prices(tmp_path, policy):
    book = ledger(tmp_path, policy)
    run = book.begin_case('ASML:core_thesis')
    attempt = reserve(book, run)
    policy['prices']['fixture/model']['request_usd'] = '0'
    snapshot = book.policy
    snapshot['prices']['fixture/model']['request_usd'] = '0'
    book.settle(attempt, input_tokens=1, output_tokens=1)
    book.finish_case(run)
    restored = AttemptLedger(book.path, book.policy)
    assert restored.summary()['reserved_nanousd'] == 400_000_000
    assert restored.summary()['known_actual_nanousd'] == 130_000_000
    with pytest.raises(BudgetError, match='already consumed'):
        restored.begin_case('ASML:core_thesis')
    with pytest.raises(BudgetError, match='mismatch'):
        AttemptLedger(book.path, policy)
    with pytest.raises(FileExistsError):
        AttemptLedger(book.path, book.policy, create=True)
    book.path.unlink()
    with pytest.raises(BudgetError, match='missing'):
        AttemptLedger(book.path, book.policy)


def test_parallel_attempts_atomic_shared_limit(tmp_path, policy):
    book = ledger(tmp_path, policy)
    run = book.begin_case('ASML:core_thesis')
    def worker(_):
        local = AttemptLedger(book.path, policy)
        try:
            return reserve(local, run)
        except BudgetError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        attempts = list(pool.map(worker, range(8)))
    assert len([a for a in attempts if a]) == 2
    assert book.summary()['reserved_nanousd'] == 800_000_000
    assert book.summary()['halted']
    # In-flight responses can still settle after another attempt halts the pilot.
    for attempt in filter(None, attempts):
        book.settle(attempt, input_tokens=1, output_tokens=1)
    assert book.summary()['unresolved_attempts'] == 0
    with pytest.raises(BudgetError):
        reserve(book, run)


@pytest.mark.parametrize('usage', [{}, {'input_tokens': True, 'output_tokens': 1},
    {'input_tokens': 11, 'output_tokens': 1}, {'input_tokens': 1, 'output_tokens': -1}])
def test_missing_ambiguous_excess_usage_halts(tmp_path, policy, usage):
    book = ledger(tmp_path, policy)
    run = book.begin_case('ASML:core_thesis')
    attempt = reserve(book, run)
    with pytest.raises(BudgetError):
        book.settle(attempt, **usage)
    assert book.summary()['reserved_nanousd'] == 400_000_000
    assert book.summary()['unresolved_attempts'] == 1
    with pytest.raises(BudgetError):
        reserve(book, run)


@pytest.mark.parametrize('route,inputs', [('unknown/model', 1), ('fixture/model', 11)])
def test_unknown_route_and_oversized_input_refused(tmp_path, policy, route, inputs):
    book = ledger(tmp_path, policy)
    run = book.begin_case('ASML:core_thesis')
    with pytest.raises(BudgetError):
        book.reserve(run, route, input_bound=inputs, output_bound=1)
    assert book.summary()['attempts'] == 0
    assert book.summary()['halted']


def test_timeout_retry_and_one_active_case(tmp_path, policy):
    book = ledger(tmp_path, policy)
    run = book.begin_case('ASML:core_thesis')
    first = reserve(book, run)
    with pytest.raises(BudgetError):
        book.finish_case(run)
    with pytest.raises(BudgetError):
        book.begin_case('NPK:decision_threshold')
    second = reserve(book, run)
    assert first != second
    book.settle(second, input_tokens=2, output_tokens=2)
    # Late completion retains both full reservations.
    book.settle(first, input_tokens=1, output_tokens=1)
    assert book.summary()['reserved_nanousd'] == 800_000_000
    with pytest.raises(BudgetError):
        book.settle(first, input_tokens=1, output_tokens=1)
    book.finish_case(run)
    book.begin_case('NPK:decision_threshold')


@pytest.mark.parametrize('mutation', ['holdout', 'other_development', 'setup', 'charges', 'currency', 'extra_fee', 'noapproval'])
def test_policy_fail_closed(tmp_path, policy, mutation):
    if mutation == 'holdout':
        policy['approved_case_ids'] = ['AJG:core_thesis']
    elif mutation == 'other_development':
        policy['approved_case_ids'] = ['AAPL:core_thesis']
    elif mutation == 'setup':
        policy['setup_sha256'] = {}
    elif mutation == 'noapproval':
        policy['approval_reference'] = ''
    else:
        rates = policy['prices']['fixture/model']
        rates[{'charges': 'all_incremental_charges_accounted', 'currency': 'currency', 'extra_fee': 'extra_fee'}[mutation]] = False
    with pytest.raises(BudgetError):
        ledger(tmp_path, policy)
    assert not (tmp_path / 'ledger.db').exists()


def test_attempt_limit_even_zero_price(tmp_path, policy):
    policy['maximum_attempts'] = 1
    for key in ['request_usd', 'input_token_usd', 'output_token_usd']:
        policy['prices']['fixture/model'][key] = '0'
    book = ledger(tmp_path, policy)
    run = book.begin_case('ASML:core_thesis')
    reserve(book, run)
    with pytest.raises(BudgetError):
        reserve(book, run)


def test_preflight_unique_identity_and_disabled_execution(policy):
    first = preflight(policy, 'ASML:core_thesis')
    second = preflight(policy, 'ASML:core_thesis')
    assert first['artifact_id'] != second['artifact_id']
    assert first['execution_allowed'] is first['hard_usd_cap_established'] is False
    with pytest.raises(BudgetError):
        preflight(policy, 'ACHC:core_thesis')


def test_cli_refuses_overwrite_and_execute(tmp_path, policy):
    source = tmp_path / 'policy.json'
    source.write_text(json.dumps(policy))
    output = tmp_path / 'preflight.json'
    cmd = [sys.executable, '-m', 'validation.capture_budget', '--policy', str(source),
           '--case', 'ASML:core_thesis', '--output', str(output)]
    assert subprocess.run(cmd, capture_output=True).returncode == 0
    original = output.read_bytes()
    assert subprocess.run(cmd, capture_output=True).returncode != 0
    assert subprocess.run(cmd + ['--execute'], capture_output=True).returncode != 0
    assert output.read_bytes() == original


def test_corrupt_restart_never_recreates_accounting_tables(tmp_path, policy):
    book = ledger(tmp_path, policy)
    run = book.begin_case('ASML:core_thesis')
    reserve(book, run)
    with sqlite3.connect(book.path) as db:
        db.execute('DROP TABLE attempts')
    with pytest.raises(sqlite3.DatabaseError):
        AttemptLedger(book.path, policy)
