"""Fixed rehearsal accounting only: invented identities, no app or providers."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3

import pytest

from validation.capture_budget import AttemptLedger, BudgetError, RateLimitDelay, validate_policy
from validation.pilot_fixtures import model_fixture
from validation.pilot_policy import (
    AUDITED_DEPENDENCIES, MODEL_ROUTES, SEC_ROUTES, policy_for,
    response_usage, validate_model_payload,
)


@pytest.fixture
def policy():
    return policy_for({'revision': 'unit-fixture', 'source_sha256': 'unit-fixture'},
                      dict(AUDITED_DEPENDENCIES))


@pytest.fixture
def book(tmp_path, policy):
    return AttemptLedger(tmp_path / 'ledger.sqlite', policy, create=True)


def binding(book, run, route):
    price = book.policy['prices'][route]
    return {'case_run': run, 'route': route, 'request_sha256': 'a' * 64,
            'input_bound': price['maximum_input_tokens'],
            'output_bound': price['maximum_output_tokens']}


def claimed(book, run, route):
    bound = binding(book, run, route)
    attempt = book.reserve(**bound)
    book.claim_dispatch(attempt, **bound)
    return attempt


def payload():
    return {'model': 'gpt-4o-mini', 'messages': [{'role': 'user', 'content': 'Synthetic input'}],
            'temperature': 0.0, 'max_tokens': 4096, 'service_tier': 'default', 'n': 1, 'stream': False}


@pytest.mark.parametrize('change', [
    lambda p: p.update(execution_allowed=True),
    lambda p: p.update(budget_usd='1'),
    lambda p: p.update(maximum_attempts=55),
    lambda p: p['quotas']['overall'].update(model=25),
    lambda p: p['quotas']['per_case']['ASML:core_thesis'].update(model=1),
    lambda p: p['prices']['model/valuation'].update(input_token_usd='0'),
    lambda p: p['configuration'].update(sdk_max_retries=1),
    lambda p: p['dependencies'].update(openai='unknown'),
    lambda p: p.update(quotas=None),
    lambda p: p.update(unreviewed_extra=True),
])
def test_policy_cannot_be_relaxed_or_repriced(policy, change):
    change(policy)
    with pytest.raises(BudgetError):
        validate_policy(policy)


def test_complete_fixed_allocation_is_24_model_30_sec_and_illustrative(book, monkeypatch):
    tick = iter(range(0, 10_000_000_000, 100_000_000))
    monkeypatch.setattr('validation.capture_budget.time.monotonic_ns', lambda: next(tick))
    counts = {'model': 0, 'sec': 0}
    for case in book.policy['approved_case_ids']:
        run = book.begin_case(case)
        limits = book.policy['quotas']['per_case'][case]
        for route in (*MODEL_ROUTES, *SEC_ROUTES):
            for _ in range(limits[route]):
                attempt = claimed(book, run, route)
                counts[route.split('/')[0]] += 1
                book.settle(attempt, input_tokens=0, output_tokens=0)
        book.finish_case(run)
    summary = book.summary()
    assert counts == {'model': 24, 'sec': 30}
    assert summary['attempts'] == 54
    assert summary['reserved_nanousd'] == 510_566_400
    assert summary['known_actual_nanousd'] == 0
    assert summary['halted'] is None
    assert summary['hard_usd_cap_established'] is False


def test_core_cannot_borrow_any_model_slot(book):
    run = book.begin_case('ASML:core_thesis')
    with pytest.raises(BudgetError):
        claimed(book, run, 'model/valuation')
    assert book.summary()['attempts'] == 0
    assert book.summary()['halted']


def test_stages_cannot_borrow_each_others_unused_slots(book):
    run = book.begin_case('NPK:decision_threshold')
    attempt = claimed(book, run, 'model/valuation')
    with pytest.raises(BudgetError):
        claimed(book, run, 'model/valuation')
    before = book.summary()
    book.settle(attempt, input_tokens=100, output_tokens=32)
    assert book.summary()['reserved_nanousd'] == before['reserved_nanousd']
    assert book.summary()['unresolved_attempts'] == 0
    with pytest.raises(BudgetError):
        claimed(book, run, 'model/synthesis')


def test_reserve_and_claim_both_fenced_after_halt(book):
    run = book.begin_case('ASML:decision_threshold')
    bound = binding(book, run, 'model/valuation')
    pending = book.reserve(**bound)
    late = claimed(book, run, 'model/macro')
    book.halt('stage_timeout')
    with pytest.raises(BudgetError):
        book.reserve(**bound)
    with pytest.raises(BudgetError):
        book.claim_dispatch(pending, **bound)
    book.settle(late, input_tokens=100, output_tokens=32)
    assert book.summary()['attempts'] == 2
    assert book.summary()['unresolved_attempts'] == 1
    assert book.summary()['halted'] == 'stage_timeout'


def test_atomic_claim_competition_is_one_shot_and_durable(book):
    run = book.begin_case('ASML:decision_threshold')
    bound = binding(book, run, 'model/valuation')
    attempt = book.reserve(**bound)
    def claim(_):
        try:
            book.claim_dispatch(attempt, **bound)
            return 1
        except BudgetError:
            return 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(claim, range(12))) == 1
    assert book.summary()['halted']
    book.settle(attempt, input_tokens=100, output_tokens=32)
    assert book.summary()['unresolved_attempts'] == 0


def test_restart_delete_replace_never_resume_or_reset(book):
    run = book.begin_case('ASML:decision_threshold')
    attempt = claimed(book, run, 'model/valuation')
    old = book.summary()['reserved_nanousd']
    reopened = AttemptLedger(book.path, book.policy)
    assert reopened.summary()['halted'] == 'reopen_requires_review'
    with pytest.raises(BudgetError):
        claimed(reopened, run, 'model/macro')
    reopened.settle(attempt, input_tokens=100, output_tokens=32)
    assert reopened.summary()['reserved_nanousd'] == old
    with pytest.raises(FileExistsError):
        AttemptLedger(book.path, book.policy, create=True)
    moved = book.path.with_suffix('.old')
    book.path.rename(moved)
    with pytest.raises(BudgetError):
        book.require_active()
    book.path.write_bytes(moved.read_bytes())
    with pytest.raises(BudgetError):
        book.summary()


@pytest.mark.parametrize('change', [
    {'input_bound': 100}, {'output_bound': 1}, {'request_sha256': None},
    {'request_sha256': 'invalid'}, {'route': 'unknown'}, {'input_bound': True},
])
def test_cannot_underreserve_or_omit_binding(book, change):
    run = book.begin_case('ASML:decision_threshold')
    bound = binding(book, run, 'model/valuation')
    bound.update(change)
    with pytest.raises(BudgetError):
        book.reserve(**bound)
    assert book.summary()['halted']
    assert book.summary()['attempts'] == 0


def test_sec_rate_limit_wait_does_not_hold_transaction_or_repeat_reservation(book, monkeypatch):
    clock = [1_000_000_000]
    monkeypatch.setattr('validation.capture_budget.time.monotonic_ns', lambda: clock[0])
    for case in ('ASML:core_thesis', 'ASML:decision_threshold'):
        run = book.begin_case(case)
        for route in SEC_ROUTES:
            for _ in range(book.policy['quotas']['per_case'][case][route]):
                attempt = claimed(book, run, route)
                book.settle(attempt, input_tokens=0, output_tokens=0)
        book.finish_case(run)
    run = book.begin_case('ACHC:core_thesis')
    bound = binding(book, run, 'sec/directory')
    pending = book.reserve(**bound)
    with pytest.raises(RateLimitDelay):
        book.claim_dispatch(pending, **bound)
    with sqlite3.connect(book.path, timeout=0.01) as db:
        db.execute('BEGIN IMMEDIATE')  # Previous claim released its DB lock.
    assert book.summary()['attempts'] == 11
    assert book.summary()['halted'] is None
    clock[0] += 1_000_000_000
    book.claim_dispatch(pending, **bound)
    assert book.summary()['attempts'] == 11


def test_input_reservation_is_full_context_tokens_not_body_bytes():
    small = payload()
    larger = deepcopy(small)
    larger['messages'][0]['content'] *= 100
    assert validate_model_payload(small, 'valuation') == (128_000, 4096)
    assert validate_model_payload(larger, 'valuation') == (128_000, 4096)
    larger['messages'][0]['content'] = 'x' * 128_000
    with pytest.raises(BudgetError):
        validate_model_payload(larger, 'valuation')


@pytest.mark.parametrize('change', [
    {'model': 'unreviewed'}, {'service_tier': 'priority'}, {'stream': True}, {'n': True},
    {'tools': []}, {'max_tokens': 4097}, {'temperature': True},
    {'messages': [{'role': 'user', 'content': [{'type': 'image_url'}]}]},
])
def test_unknown_chargeable_request_semantics_rejected(change):
    value = payload()
    value.update(change)
    with pytest.raises(BudgetError):
        validate_model_payload(value, 'valuation')


@pytest.mark.parametrize('change', [
    lambda p: p.pop('usage'),
    lambda p: p.update(model='unknown'),
    lambda p: p.update(service_tier='priority'),
    lambda p: p['usage'].update(total_tokens=999),
    lambda p: p['usage'].update(prompt_tokens=True),
    lambda p: p['usage'].update(extra_units=0),
    lambda p: p['usage'].update(completion_tokens_details={'audio_tokens': 1}),
    lambda p: p['usage'].update(prompt_tokens_details={'cached_tokens': 101}),
    lambda p: p['choices'].append(deepcopy(p['choices'][0])),
    lambda p: p['choices'][0]['message'].update(tool_calls=[]),
])
def test_ambiguous_usage_model_tier_or_nontext_response_rejected(change):
    value = model_fixture('valuation', {'ticker': 'NPK'})
    assert response_usage(value, 4096) == (100, 32)
    change(value)
    with pytest.raises(BudgetError):
        response_usage(value, 4096)
