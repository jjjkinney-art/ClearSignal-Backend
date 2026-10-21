"""Real signed local /ask -> scenario evaluator -> owned SQLite snapshot/retry.

No providers, models, production credentials or live-run ledgers are accessed.
"""
from copy import deepcopy
import json
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

from test_conditional_valuation_account_boundary import boundary, approve, token, bearer, SUBJECT_B, EMAIL_B, KEY
from test_conditional_valuation_api import payload, records
from test_source_anchored_valuation import assumptions
from app.config import settings
from app.db.models import ResearchMessage
from app.services import conditional_valuation_service as svc
from app.services import research_conversations as conversations


@pytest_asyncio.fixture
async def owned_scenarios(boundary, monkeypatch):
    from app import api
    client, maker, calls, observed = boundary
    client._transport.app.include_router(api.router)
    monkeypatch.setattr('app.db.connection.get_session_factory', lambda: maker)
    monkeypatch.setattr(settings, 'owned_research_scenarios_enabled', True)
    monkeypatch.setattr(settings, 'entitlements_enforced', False)
    monkeypatch.setattr(settings, 'ask_daily_quota', 1000)
    models = []
    def forbidden(*a, **kw):
        models.append('unexpected normal pipeline')
        raise AssertionError('normal pipeline must not run for explicit scenario turns')
    monkeypatch.setattr(api, 'route_question', forbidden)
    await approve(maker)
    yield client, maker, calls, models, observed


async def thread(client, headers, tickers=None):
    r = await client.post('/research/conversations', json={
        'title': 'Explicit hypothetical scenario', 'tickers': ['ZQXB'] if tickers is None else tickers}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()['id']


def question(cid, ref='scenario-1', *, loss=False):
    return {'company_name': 'ZQXB', 'question': 'Explain this explicit hypothetical scenario.',
        'research_conversation_id': cid, 'research_request_ref': ref,
        'conditional_valuation': payload(loss=loss)}


async def reopen(client, cid, headers):
    r = await client.get('/research/conversations/' + cid, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize('mode', ['growth', 'required', 'recovery'])
async def test_signed_ask_preserves_explicit_inputs_citations_and_exact_reopened_answer(owned_scenarios, monkeypatch, mode):
    client, maker, calls, models, observed = owned_scenarios
    if mode == 'recovery':
        def fetch(*a, **kw):
            calls.append((a, kw)); return records(-2)
        monkeypatch.setattr(svc, 'get_company_fact_records_for_concept_units', fetch)
    headers = bearer(token()); cid = await thread(client, headers)
    q = question(cid, loss=mode == 'recovery')
    if mode == 'required':
        q['conditional_valuation']['assumptions'] = assumptions('solve_required_earnings_growth')
    before = deepcopy(q)
    r = await client.post('/ask', json=q, headers=headers)
    assert r.status_code == 200, r.text
    data = r.json(); answer = data['answer']; result = answer['conditional_valuation']['result']
    assert result['available'] and result['status'] == 'partial'
    assert data['routing']['response_mode'] == 'conditional_scenario'
    assert answer['conditional_valuation']['request'] == q['conditional_valuation']
    assert answer['evidence_references'] == result['evidence_references']
    assert '[E1]' in answer['direct_answer']
    assert answer['general']['answer'] == answer['direct_answer']
    assert result['explanation']['direct_answer'] in answer['direct_answer']
    assert 'investment_thesis' not in answer
    assert not result['admitted'] and not result['launch_ready']
    assert len(calls) == 1 and models == [] and q == before
    assert r.headers['cache-control'] == 'no-store'
    saved = await reopen(client, cid, headers)
    messages = saved['messages']
    assert [m['role'] for m in messages] == ['user', 'assistant']
    assert messages[1]['displayed_snapshot']['response'] == data
    assert messages[1]['text'] == answer['direct_answer']
    assert messages[1]['displayed_snapshot']['thesis_memory_artifact']['status'] == 'unavailable'
    assert KEY not in r.text and observed[-1][2] is True


async def test_retry_replays_original_inputs_even_after_utc_rollover_without_source_work(owned_scenarios, monkeypatch):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers)
    q = question(cid)
    first = await client.post('/ask', json=q, headers=headers)
    assert first.status_code == 200 and len(calls) == 1
    q['question'] = 'Different question must not overwrite the original turn'
    q['conditional_valuation']['assumptions']['price']['value'] = '999'
    monkeypatch.setattr(svc, '_current_date', lambda: date(2026, 3, 3))
    retry = await client.post('/ask', json=q, headers=headers)
    assert retry.json() == first.json() and len(calls) == 1 and not models
    assert retry.headers['x-research-turn-replayed'] == 'true'
    assert len((await reopen(client, cid, headers))['messages']) == 2
    ndjson = await client.post('/ask', json=q, headers={**headers, 'accept': 'application/x-ndjson'})
    frame = json.loads(ndjson.text)
    assert frame['type'] == 'final' and frame['data'] == first.json()
    assert len(calls) == 1


async def test_new_reference_computes_new_explicit_scenario_without_overwriting_saved_inputs(owned_scenarios):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers)
    q = question(cid)
    first = (await client.post('/ask', json=q, headers=headers)).json()
    q['research_request_ref'] = 'scenario-2'
    q['conditional_valuation']['assumptions']['price']['value'] = '200'
    second = (await client.post('/ask', json=q, headers=headers)).json()
    assert first['answer']['conditional_valuation']['request']['assumptions']['price']['value'] == '100'
    assert second['answer']['conditional_valuation']['request']['assumptions']['price']['value'] == '200'
    saved = await reopen(client, cid, headers)
    assert len(saved['messages']) == 4 and len(calls) == 2 and not models
    assert saved['messages'][1]['displayed_snapshot']['response'] == first
    assert saved['messages'][3]['displayed_snapshot']['response'] == second


async def test_foreign_missing_and_deleted_conversations_never_fetch_or_replay(owned_scenarios):
    client, maker, calls, models, _ = owned_scenarios
    a = bearer(token()); cid = await thread(client, a)
    await approve(maker, EMAIL_B)
    b = bearer(token(SUBJECT_B, EMAIL_B))
    foreign = await client.post('/ask', json=question(cid), headers=b)
    missing = await client.post('/ask', json=question('missing'), headers=b)
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()
    first = await client.post('/ask', json=question(cid), headers=a)
    assert first.status_code == 200 and len(calls) == 1
    assert (await client.get('/research/conversations/' + cid, headers=b)).status_code == 404
    assert (await client.delete('/research/conversations/' + cid, headers=a)).status_code == 200
    deleted = await client.post('/ask', json=question(cid), headers=a)
    assert deleted.status_code == 404 and len(calls) == 1 and not models


@pytest.mark.parametrize('flag', ['owned_research_scenarios_enabled', 'conditional_valuation_scenarios_enabled'])
async def test_both_feature_flags_are_required_before_provider_work(owned_scenarios, monkeypatch, flag):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers)
    monkeypatch.setattr(settings, flag, False)
    r = await client.post('/ask', json=question(cid), headers=headers)
    assert r.status_code == 404 and not calls and not models


@pytest.mark.parametrize('kind', ['missing', 'wrong_key', 'expired', 'uninvited'])
async def test_real_auth_and_beta_admission_precede_scenario_dispatch(owned_scenarios, kind):
    client, maker, calls, models, _ = owned_scenarios
    from datetime import datetime, timedelta, timezone
    variants = {'missing': {}, 'wrong_key': bearer(token(key='incorrect-'+'x'*48)),
        'expired': bearer(token(exp=datetime.now(timezone.utc)-timedelta(seconds=10))),
        'uninvited': bearer(token(SUBJECT_B, EMAIL_B))}
    r = await client.post('/ask', json=question('missing'), headers=variants[kind])
    assert r.status_code == (403 if kind == 'uninvited' else 401)
    assert not calls and not models and KEY not in r.text


@pytest.mark.parametrize('key', ['price', 'exit_pe', 'horizon', 'eps_growth_rate', 'eps_basis', 'distributions'])
async def test_missing_assumptions_are_not_invented_or_sent_to_models(owned_scenarios, key):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers); q = question(cid)
    del q['conditional_valuation']['assumptions'][key]
    r = await client.post('/ask', json=q, headers=headers)
    assert r.status_code == 400 and not calls and not models
    assert (await reopen(client, cid, headers))['messages'] == []


@pytest.mark.parametrize('kind', ['company', 'active', 'as_of', 'memory', 'context', 'extra', 'empty_scope', 'wrong_scope', 'missing_ref', 'missing_conversation', 'null'])
async def test_ambiguous_scope_and_implicit_context_fail_before_sources(owned_scenarios, kind):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers,
        tickers=[] if kind == 'empty_scope' else ['OTHER'] if kind == 'wrong_scope' else None)
    q = question(cid)
    if kind == 'company': q['company_name'] = 'OTHER'
    if kind == 'active': q['active_ticker'] = 'OTHER'
    if kind == 'as_of': q['as_of'] = '2025-01-01'
    if kind == 'memory': q['research_memory_conversation_id'] = cid
    if kind == 'context': q['context'] = {'company': 'ZQXB'}
    if kind == 'extra': q['conditional_valuation']['cik'] = '1234567'
    if kind == 'missing_ref': del q['research_request_ref']
    if kind == 'missing_conversation': del q['research_conversation_id']
    if kind == 'null': q['conditional_valuation'] = None
    r = await client.post('/ask', json=q, headers=headers)
    assert r.status_code == 400, r.text
    assert not calls and not models


@pytest.mark.parametrize('kind', ['duplicate', 'float', 'nonfinite', 'oversize'])
async def test_original_json_contract_not_pydantic_dictionary_is_checked(owned_scenarios, kind):
    client, maker, calls, models, _ = owned_scenarios
    headers = {**bearer(token()), 'content-type': 'application/json'}
    cid = await thread(client, headers); q = question(cid)
    raw = json.dumps(q)
    if kind == 'duplicate': raw = raw.replace('"price": {', '"price": {}, "price": {')
    if kind == 'float': raw = raw.replace('"100"', '100.0')
    if kind == 'nonfinite': raw = raw.replace('"100"', 'NaN')
    if kind == 'oversize':
        q['conditional_valuation']['assumptions']['price']['provenance']['reference'] = 'x' * 17000
        raw = json.dumps(q)
    r = await client.post('/ask', content=raw, headers=headers)
    assert r.status_code == (413 if kind == 'oversize' else 400), r.text
    assert not calls and not models


async def test_source_gap_is_saved_with_inputs_and_no_invented_eps_or_citations(owned_scenarios):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers); q = question(cid)
    q['conditional_valuation']['assumptions']['eps_basis']['share_basis'] = 'basic'
    r = await client.post('/ask', json=q, headers=headers)
    assert r.status_code == 200, r.text
    result = r.json()['answer']['conditional_valuation']['result']
    assert not result['available'] and not result['evidence_references']
    assert 'remains unverified' in r.json()['answer']['direct_answer']
    assert r.json()['answer']['conditional_valuation']['request'] == q['conditional_valuation']
    assert (await reopen(client, cid, headers))['messages'][1]['displayed_snapshot']['response'] == r.json()
    assert len(calls) == 1 and not models


@pytest.mark.parametrize('kind', ['storage_absent', 'storage_raises', 'evaluation_raises', 'save_raises'])
async def test_failure_is_sanitized_and_never_returns_an_unsaved_completed_answer(owned_scenarios, monkeypatch, kind):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers)
    def error(*a, **kw): raise RuntimeError('CANARY credentials and raw source')
    async def async_error(*a, **kw): error()
    if kind == 'storage_absent': monkeypatch.setattr('app.db.connection.get_session_factory', lambda: None)
    if kind == 'storage_raises': monkeypatch.setattr('app.db.connection.get_session_factory', error)
    if kind == 'evaluation_raises': monkeypatch.setattr(svc, 'evaluate_requested_scenario', error)
    if kind == 'save_raises': monkeypatch.setattr(conversations, 'append_completed_turn', async_error)
    r = await client.post('/ask', json=question(cid), headers=headers)
    assert r.status_code == 503 and 'CANARY' not in r.text
    assert 'answer' not in r.json() and not models
    assert len(calls) == (1 if kind == 'save_raises' else 0)
    async with maker() as db:
        assert (await db.execute(select(ResearchMessage))).scalars().all() == []


async def test_ambiguous_save_recovers_the_committed_snapshot_without_a_second_dispatch(owned_scenarios, monkeypatch):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers)
    real = conversations.append_completed_turn
    async def committed_then_error(session, **kwargs):
        await real(session, **kwargs)
        await session.commit()
        raise RuntimeError('CANARY ambiguous post-commit failure')
    monkeypatch.setattr(conversations, 'append_completed_turn', committed_then_error)
    r = await client.post('/ask', json=question(cid), headers=headers)
    assert r.status_code == 200 and r.headers['x-research-turn-replayed'] == 'true'
    assert 'CANARY' not in r.text and len(calls) == 1 and not models
    saved = await reopen(client, cid, headers)
    assert len(saved['messages']) == 2 and saved['messages'][1]['displayed_snapshot']['response'] == r.json()


async def test_existing_daily_quota_still_prevents_new_scenario_dispatch(owned_scenarios, monkeypatch):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers)
    monkeypatch.setattr(settings, 'ask_daily_quota', 1)
    first = await client.post('/ask', json=question(cid), headers=headers)
    second = await client.post('/ask', json=question(cid, ref='second'), headers=headers)
    assert first.status_code == 200 and second.status_code == 429
    assert len(calls) == 1 and not models
    assert len((await reopen(client, cid, headers))['messages']) == 2


async def test_retrieval_off_fails_before_sources_and_writes(owned_scenarios, monkeypatch):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers)
    monkeypatch.setattr(settings, 'enable_data_retrieval', False)
    r = await client.post('/ask', json=question(cid), headers=headers)
    assert r.status_code == 503 and not calls and not models
    assert (await reopen(client, cid, headers))['messages'] == []


async def test_disabled_auth_cannot_use_system_bypass_for_scenario_storage(owned_scenarios, monkeypatch):
    client, maker, calls, models, _ = owned_scenarios
    monkeypatch.setattr(settings, 'auth_enabled', False)
    r = await client.post('/ask', json=question('missing'))
    assert r.status_code == 401 and not calls and not models


def test_separate_ask_activation_is_off_by_default():
    from app.config import Settings
    assert Settings.model_fields['owned_research_scenarios_enabled'].default is False


def test_internal_router_cannot_infer_or_execute_explicit_scenario_inputs():
    from app.schemas import QuestionRequest
    from app.services.router_service import route_question
    with pytest.raises(ValueError, match='authenticated owned'):
        route_question(QuestionRequest(**question('not-used')))


async def test_normal_saved_turn_retry_can_reopen_original_scenario_without_recomputing(owned_scenarios):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers); q = question(cid)
    first = await client.post('/ask', json=q, headers=headers)
    del q['conditional_valuation']
    retry = await client.post('/ask', json=q, headers=headers)
    assert retry.status_code == 200 and retry.json() == first.json()
    assert retry.headers['x-research-turn-replayed'] == 'true'
    assert len(calls) == 1 and not models


@pytest.mark.parametrize('kind', ['duplicate', 'malformed', 'declared_oversize'])
async def test_declared_length_contract_is_checked_in_addition_to_observed_bytes(owned_scenarios, kind):
    client, maker, calls, models, _ = owned_scenarios
    headers = bearer(token()); cid = await thread(client, headers)
    lengths = [('content-length', '1'), ('content-length', '2')] if kind == 'duplicate' else [
        ('content-length', 'invalid' if kind == 'malformed' else '20000')]
    r = await client.post('/ask', content=json.dumps(question(cid)),
        headers=[*headers.items(), ('content-type', 'application/json'), *lengths])
    assert r.status_code == (413 if kind == 'declared_oversize' else 400)
    assert not calls and not models
