"""Invented fixture prices and in-memory SDK HTTP only; sockets forbidden."""
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import json
import sqlite3
import socket

import httpx
from openai import OpenAI
import pytest

from validation.benchmark_transport import BenchmarkTransport, FixtureResponse
from validation.capture_budget import AttemptLedger, BudgetError, setup_binding


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail('network attempted')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket.socket, 'sendto', refuse)
    monkeypatch.setattr(socket, 'getaddrinfo', refuse)


@pytest.fixture
def book(tmp_path):
    policy = dict(schema_version=1, pilot_id='offline', approval_reference='synthetic',
                  configuration_version='fixture', pricing_review_reference='synthetic',
                  budget_usd='1', maximum_attempts=10,
                  approved_case_ids=['ASML:core_thesis'], setup_sha256=setup_binding(),
                  prices={'fixture-bytes/model': dict(currency='USD',
                      all_incremental_charges_accounted=True, request_usd='0.01',
                      input_token_usd='0.000001', output_token_usd='0.000001',
                      maximum_input_tokens=10000, maximum_output_tokens=10)})
    ledger = AttemptLedger(tmp_path / 'ledger.db', policy, create=True)
    return ledger, ledger.begin_case('ASML:core_thesis')


def response(status=200, *, inputs=1, outputs=1, location=None):
    body = dict(id='fixture', object='chat.completion', created=0, model='model',
                choices=[dict(index=0, message=dict(role='assistant', content='fixture'),
                              finish_reason='stop')],
                usage=dict(prompt_tokens=inputs, completion_tokens=outputs, total_tokens=2))
    if status >= 400:
        body = {'error': {'message': 'fixture failure', 'type': 'fixture'}}
    return FixtureResponse(status, json.dumps(body).encode(), inputs, outputs, location)


def transport(book, *fixtures):
    ledger, run = book
    return BenchmarkTransport(ledger, run, model='model', responses=tuple(fixtures or [response()]))


def request(**changes):
    payload = dict(model='model', messages=[dict(role='user', content='hello')], max_tokens=2)
    payload.update(changes)
    return httpx.Request('POST', 'https://fixture.invalid/v1/chat/completions', json=payload)


def binding(book):
    return dict(case_run=book[1], route='fixture-bytes/model', input_bound=10,
                output_bound=2, request_sha256='a' * 64)


def claim_worker(path, policy, attempt, bound):
    try:
        AttemptLedger(path, policy).claim_dispatch(attempt, **bound)
        return 1
    except BudgetError:
        return 0


@pytest.mark.parametrize('pool_type', [ThreadPoolExecutor, ProcessPoolExecutor])
def test_exactly_one_claim_across_callers(book, pool_type):
    ledger, _ = book
    bound = binding(book)
    attempt = ledger.reserve(**bound)
    with pool_type(max_workers=4) as pool:
        futures = [pool.submit(claim_worker, ledger.path, ledger.policy, attempt, bound) for _ in range(8)]
        assert sum(f.result() for f in futures) == 1
    assert ledger.summary()['unresolved_attempts'] == 1


def test_real_sdk_retries_each_claim_a_new_reservation(book):
    adapter = transport(book, response(429), response(500), response())
    with OpenAI(api_key='synthetic-fixture-only', base_url='https://fixture.invalid/v1',
                max_retries=2, http_client=httpx.Client(transport=adapter)) as client:
        result = client.chat.completions.create(model='model', messages=[{'role': 'user', 'content': 'hello'}], max_tokens=2)
    assert result.choices[0].message.content == 'fixture'
    summary = book[0].summary()
    assert summary['attempts'] == 3
    assert summary['unresolved_attempts'] == 0
    assert summary['reserved_nanousd'] > summary['known_actual_nanousd']
    assert summary['hard_usd_cap_established'] is False


@pytest.mark.parametrize('mutate', [dict(model='unknown'), dict(stream=True), dict(tools=[]),
                                  dict(max_tokens=11), dict(max_tokens=True),
                                  dict(messages=[dict(role='user', content=[{'type': 'image'}])])])
def test_unknown_routes_units_bounds_refused(book, mutate):
    with pytest.raises(BudgetError):
        transport(book).handle_request(request(**mutate))
    assert book[0].summary()['attempts'] == 0


@pytest.mark.parametrize('inputs,outputs', [(None, 1), (1, None), (True, 1), (1, 3), (10001, 1)])
def test_missing_excess_usage_halts_without_refund(book, inputs, outputs):
    adapter = transport(book, response(inputs=inputs, outputs=outputs), response())
    with pytest.raises(BudgetError):
        adapter.handle_request(request())
    before = book[0].summary()
    with pytest.raises(BudgetError):
        adapter.handle_request(request())
    assert before['attempts'] == book[0].summary()['attempts'] == 1
    assert before['reserved_nanousd'] > 0
    assert before['halted']


@pytest.mark.parametrize('target,expected', [('https://fixture.invalid/v1/chat/completions', 2),
                                            ('https://external.invalid/v1/chat/completions', 1)])
def test_redirect_requires_new_reservation_and_route_check(book, target, expected):
    adapter = transport(book, response(307, location=target), response())
    with httpx.Client(transport=adapter, follow_redirects=True) as client:
        if expected == 1:
            with pytest.raises(BudgetError):
                client.send(request())
        else:
            assert client.send(request()).status_code == 200
    assert book[0].summary()['attempts'] == expected


@pytest.mark.parametrize('field,value', [('request_sha256', 'b'*64), ('case_run', 'other'),
                                       ('route', 'other'), ('input_bound', 9), ('output_bound', 1)])
def test_claim_binding_is_immutable(book, field, value):
    ledger, _ = book
    bound = binding(book)
    attempt = ledger.reserve(**bound)
    changed = dict(bound, **{field: value})
    with pytest.raises(BudgetError):
        ledger.claim_dispatch(attempt, **changed)
    ledger.claim_dispatch(attempt, **bound)
    with pytest.raises(BudgetError):
        ledger.claim_dispatch(attempt, **bound)


def test_freezes_request_before_reservation(book, monkeypatch):
    original = request()
    reserve = book[0].reserve
    def mutate_after_binding(**kwargs):
        original.url = httpx.URL('https://external.invalid')
        original.headers['x-mutated'] = 'yes'
        original._content = b'changed'
        return reserve(**kwargs)
    monkeypatch.setattr(book[0], 'reserve', mutate_after_binding)
    assert transport(book).handle_request(original).status_code == 200
    assert book[0].summary()['attempts'] == 1


def test_crashes_keep_reservation_and_claim_cannot_replay(book):
    ledger, _ = book
    bound = binding(book)
    attempt = ledger.reserve(**bound)  # crash before claim: still reserved
    restored = AttemptLedger(ledger.path, ledger.policy)
    assert restored.summary()['unresolved_attempts'] == 1
    with pytest.raises(BudgetError):
        restored.settle(attempt, input_tokens=1, output_tokens=1)
    restored.claim_dispatch(attempt, **bound)  # crash before send OR before usage
    reopened = AttemptLedger(ledger.path, ledger.policy)
    with pytest.raises(BudgetError):
        reopened.claim_dispatch(attempt, **bound)
    with pytest.raises(BudgetError):
        reopened.finish_case(book[1])
    reopened.settle(attempt, input_tokens=1, output_tokens=1)  # late completion
    assert reopened.summary()['reserved_nanousd'] > 0


def test_previous_schema_refused(book):
    ledger, _ = book
    with sqlite3.connect(ledger.path) as db:
        db.execute('PRAGMA user_version=0')
    with pytest.raises(BudgetError, match='schema'):
        AttemptLedger(ledger.path, ledger.policy)


def test_transport_callback_and_subclasses_have_no_injection_api(book):
    class NetworkMock(httpx.MockTransport):
        pass
    for forbidden in (httpx.HTTPTransport(), httpx.MockTransport(lambda r: httpx.Response(200)),
                      NetworkMock(lambda r: httpx.Response(200)), lambda r: httpx.Response(200), None):
        with pytest.raises(TypeError):
            BenchmarkTransport(*book, model='model', responses=(response(),), transport=forbidden)
        with pytest.raises(BudgetError):
            BenchmarkTransport(*book, model='model', responses=(forbidden,))
    with pytest.raises(BudgetError):
        BenchmarkTransport(*book, model='model', responses=(lambda: response(),))


def test_holdout_and_unapproved_cases_refused(book):
    ledger, _ = book
    metadata = json.loads(__import__('pathlib').Path('validation/company_quality_manifest.v2.metadata.json').read_text())
    for case in [metadata['reserved_holdouts'][0] + ':core_thesis', 'NPK:core_thesis']:
        with pytest.raises(BudgetError):
            ledger.begin_case(case)
    policy = ledger.policy
    policy['approved_case_ids'] = [metadata['reserved_holdouts'][0] + ':core_thesis']
    with pytest.raises(BudgetError, match='holdout'):
        AttemptLedger(ledger.path, policy)


def test_custom_stream_refused_without_invoking_callback(book):
    class DangerousStream(httpx.SyncByteStream):
        def __iter__(self):
            pytest.fail('custom stream invoked')
    req = httpx.Request('POST', 'https://fixture.invalid/v1/chat/completions', stream=DangerousStream())
    with pytest.raises(BudgetError, match='byte stream'):
        transport(book).handle_request(req)
    assert book[0].summary()['attempts'] == 0


def test_input_boundary_and_shared_attempt_limit(book):
    ledger, _ = book
    req = request()
    policy = ledger.policy
    policy['prices']['fixture-bytes/model']['maximum_input_tokens'] = len(req.content)
    policy['maximum_attempts'] = 1
    bounded = AttemptLedger(ledger.path.parent / 'bounded.db', policy, create=True)
    bounded_run = bounded.begin_case('ASML:core_thesis')
    adapter = transport((bounded, bounded_run), response(), response())
    assert adapter.handle_request(req).status_code == 200
    with pytest.raises(BudgetError, match='limit'):
        adapter.handle_request(request())
    assert bounded.summary()['attempts'] == 1
    policy['prices']['fixture-bytes/model']['maximum_input_tokens'] -= 1
    short = AttemptLedger(ledger.path.parent / 'short.db', policy, create=True)
    with pytest.raises(BudgetError, match='bound'):
        transport((short, short.begin_case('ASML:core_thesis'))).handle_request(request())
    assert short.summary()['attempts'] == 0


def test_mock_failure_preserves_claim_and_no_old_attempt_replay(book, monkeypatch):
    adapter = transport(book)
    def fail(request):
        raise RuntimeError('simulated crash after claim')
    monkeypatch.setattr(adapter._mock, 'handle_request', fail)
    with pytest.raises(RuntimeError):
        adapter.handle_request(request())
    assert book[0].summary()['unresolved_attempts'] == 1
    with pytest.raises(BudgetError, match='exhausted'):
        adapter.handle_request(request())
    assert book[0].summary()['attempts'] == 1


def test_unbound_accounting_attempt_cannot_dispatch(book):
    bound = binding(book)
    unbound = dict(bound)
    del unbound['request_sha256']
    attempt = book[0].reserve(**unbound)
    with pytest.raises(BudgetError, match='binding'):
        book[0].claim_dispatch(attempt, **bound)


def test_late_claimed_response_can_settle_after_halt(book):
    ledger, _ = book
    bound = binding(book)
    attempt = ledger.reserve(**bound)
    ledger.claim_dispatch(attempt, **bound)
    with pytest.raises(BudgetError):
        ledger.reserve(**dict(bound, route='unknown'))
    ledger.settle(attempt, input_tokens=1, output_tokens=1)
    assert ledger.summary()['unresolved_attempts'] == 0
    assert ledger.summary()['halted']


def test_multiple_wrappers_share_cost_and_attempt_limits(book):
    ledger, _ = book
    policy = ledger.policy
    policy['maximum_attempts'] = 2
    shared = AttemptLedger(ledger.path.parent / 'shared.db', policy, create=True)
    run = shared.begin_case('ASML:core_thesis')
    def worker(_):
        adapter = transport((AttemptLedger(shared.path, policy), run))
        try:
            return adapter.handle_request(request()).status_code == 200
        except BudgetError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        successes = sum(pool.map(worker, range(8)))
    # A limit violation may halt between another caller's reserve and claim.
    # That caller must not dispatch; its conservative reservation remains.
    assert 0 <= successes <= 2
    assert shared.summary()['attempts'] == 2
    assert shared.summary()['unresolved_attempts'] == 2 - successes
