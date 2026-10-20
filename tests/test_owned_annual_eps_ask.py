"""Offline signed JWT -> actual /ask -> source gate -> owned save/reopen.

Only invented issuer facts/accounts and disposable local databases. The real
verifier, beta admission, owner resolution, streaming handler and persistence
remain in place; unrelated external providers are substituted.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from test_conditional_valuation_account_boundary import (
    boundary, approve, token, bearer, SUBJECT_A, SUBJECT_B, EMAIL_A, EMAIL_B, KEY,
)
from test_source_evidence_latency import isolated_pipeline
from test_annual_eps_research import rows, TICKER, CIK
from app.config import settings
from app.services import verified_sec_metric_service as metrics
from app.services.issuer_identity import parse_directory
from app.db.models import User

REAL_FETCH=metrics.fetch_verified_metric_evidence

@pytest_asyncio.fixture
async def owned_ask(boundary,isolated_pipeline,monkeypatch):
    from app import api
    client,maker,_,observed=boundary
    client._transport.app.include_router(api.router)
    @asynccontextmanager
    async def session():
        async with maker() as db:yield db
    monkeypatch.setattr('app.db.get_session',session)
    monkeypatch.setattr('app.db.connection.get_session_factory',lambda:maker)
    monkeypatch.setattr(settings,'entitlements_enforced',False)
    monkeypatch.setattr(settings,'ask_daily_quota',1000)
    monkeypatch.setattr(metrics,'fetch_verified_metric_evidence',REAL_FETCH)
    monkeypatch.setattr(metrics,'_load_ticker_cik_map',lambda:{TICKER:CIK})
    monkeypatch.setattr('app.services.providers.sec_provider._load_ticker_cik_map',lambda:{TICKER:CIK})
    monkeypatch.setattr('app.services.issuer_identity._load_directory',lambda:parse_directory(
        {'0':{'ticker':TICKER,'title':'Invented Issuer','cik_str':int(CIK)}}))
    data=rows('basic','EUR','20-F')
    calls=[]
    def facts(cik,**kwargs):
        calls.append((cik,kwargs));return deepcopy(data)
    monkeypatch.setattr(metrics,'get_company_fact_records_for_concept_units',facts)
    yield client,maker,calls,isolated_pipeline,data,observed

async def conversation(client,headers,title='Private annual EPS research'):
    r=await client.post('/research/conversations',json={'title':title,'tickers':[TICKER]},headers=headers)
    assert r.status_code==201,r.text
    return r.json()['id']

def question(cid,ref='eps-turn-1',basis='basic'):
    return {'company_name':TICKER,'question':f'What is the latest annual EUR {basis} EPS for {TICKER}?',
        'intent':'company_analysis','research_conversation_id':cid,'research_request_ref':ref}

async def reopen(client,cid,headers):
    r=await client.get('/research/conversations/'+cid,headers=headers)
    assert r.status_code==200,r.text
    return r.json()

async def test_real_ask_stream_reopens_exact_gated_answer_and_citations(owned_ask):
    client,maker,calls,models,_,observed=owned_ask
    from app.db.repositories.account_repo import create_user
    async with maker() as db:
        await create_user(db,user_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',email=EMAIL_A,auth_subject=SUBJECT_A)
        await db.commit()
    await approve(maker)
    headers=bearer(token())
    cid=await conversation(client,headers)
    r=await client.post('/ask',json=question(cid),headers=headers)
    assert r.status_code==200,r.text
    data=r.json();assert 'error' not in data,data
    assert data['routing']['response_mode']=='source_evidence'
    assert data['answer']['source_answer']['status']=='attributed'
    assert data['answer']['investment_thesis']['quantitative_claims'][0]['unit']=='EUR/shares'
    assert not models and len(calls)==1
    saved=await reopen(client,cid,headers)
    messages=saved['messages'];assert [m['role'] for m in messages]==['user','assistant']
    snapshot=messages[1]['displayed_snapshot']['response']
    assert snapshot==data
    text=messages[1]['text']
    assert text==data['answer']['investment_thesis']['direct_answer']
    assert '[E1]' in text and 'basic EPS' in text
    assert snapshot['answer']['evidence_references']==data['answer']['evidence_references']
    async with maker() as db:
        user=(await db.execute(select(User))).scalars().one()
        assert str(user.id)!=SUBJECT_A
        assert observed[0]==(str(user.id),SUBJECT_A,True)
    assert KEY not in r.text and SUBJECT_A not in r.text

@pytest.mark.parametrize('kind',['missing','wrong_key','expired'])
async def test_invalid_jwt_cannot_dispatch_or_write_research(owned_ask,kind):
    from datetime import datetime,timedelta,timezone
    client,maker,calls,models,_,_=owned_ask
    await approve(maker)
    headers=bearer(token());cid=await conversation(client,headers)
    bad={'missing':{},'wrong_key':bearer(token(key='different-test-key-'+'z'*48)),
         'expired':bearer(token(exp=datetime.now(timezone.utc)-timedelta(seconds=5)))}[kind]
    r=await client.post('/ask',json=question(cid),headers=bad)
    assert r.status_code==401 and not calls and not models
    assert (await reopen(client,cid,headers))['messages']==[]

async def test_distinct_real_users_cannot_reopen_or_append_foreign_conversation(owned_ask):
    client,maker,calls,models,_,_=owned_ask
    await approve(maker);await approve(maker,EMAIL_B)
    ha,hb=bearer(token()),bearer(token(SUBJECT_B,EMAIL_B))
    cid=await conversation(client,ha)
    assert (await client.post('/ask',json=question(cid),headers=ha)).status_code==200
    before=await reopen(client,cid,ha)
    assert (await client.get('/research/conversations/'+cid,headers=hb)).status_code==404
    assert (await client.post('/research/conversations/'+cid+'/messages',json={'text':'intrude'},headers=hb)).status_code==404
    # A foreign output id cannot turn this public-fact question into access to
    # the owner's research. It may still receive its own fresh public answer.
    r=await client.post('/ask',json=question(cid,ref='foreign-write'),headers=hb)
    assert r.status_code==200 and 'error' not in r.json()
    assert (await reopen(client,cid,ha))==before
    listing=await client.get('/research/conversations',headers=hb)
    assert listing.status_code==200 and listing.json()==[]
    assert not models

async def test_retried_turn_keeps_first_saved_snapshot(owned_ask):
    client,maker,calls,models,data,_=owned_ask
    await approve(maker);headers=bearer(token());cid=await conversation(client,headers)
    first=(await client.post('/ask',json=question(cid),headers=headers)).json()
    assert 'error' not in first
    saved=await reopen(client,cid,headers)
    data[:]=[replace(row,value=6) if row.concept=='EarningsPerShareBasic' and row.end=='2025-12-31' else row for row in data]
    response=await client.post('/ask',json=question(cid),headers=headers)
    second=response.json()
    assert second==first and not models and len(calls)==1
    assert response.headers['x-research-turn-replayed']=='true'
    assert second['answer']['investment_thesis']['quantitative_claims'][0]['raw_value']==5
    assert (await reopen(client,cid,headers))==saved
    fresh=(await client.post('/ask',json=question(cid,ref='fresh-analysis'),headers=headers)).json()
    assert fresh['answer']['investment_thesis']['quantitative_claims'][0]['raw_value']==6
    assert len(calls)==2 and not models
    messages=(await reopen(client,cid,headers))['messages']
    assert len(messages)==4 and messages[3]['displayed_snapshot']['response']==fresh

async def test_completed_retry_ndjson_uses_original_payload_even_if_question_changes(owned_ask):
    from app.progress import PROGRESS_MEDIA_TYPE
    client,maker,calls,models,_,_=owned_ask
    await approve(maker);headers=bearer(token());cid=await conversation(client,headers)
    first=(await client.post('/ask',json=question(cid),headers=headers)).json()
    retry=question(cid,basis='diluted')
    response=await client.post('/ask',json=retry,headers={**headers,'accept':PROGRESS_MEDIA_TYPE})
    frames=[json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert response.headers['x-research-turn-replayed']=='true'
    assert len(frames)==1 and frames[0]['type']=='final' and frames[0]['data']==first
    assert len(calls)==1 and not models

async def test_same_reference_in_other_owned_conversation_gets_fresh_answer(owned_ask):
    client,maker,calls,models,data,_=owned_ask
    await approve(maker);headers=bearer(token())
    first_id=await conversation(client,headers)
    first=(await client.post('/ask',json=question(first_id),headers=headers)).json()
    data[:]=[replace(row,value=6) if row.concept=='EarningsPerShareBasic' and row.end=='2025-12-31' else row for row in data]
    second_id=await conversation(client,headers)
    response=await client.post('/ask',json=question(second_id),headers=headers)
    assert 'x-research-turn-replayed' not in response.headers
    assert response.json()['answer']['investment_thesis']['quantitative_claims'][0]['raw_value']==6
    assert len(calls)==2 and not models
    assert (await reopen(client,first_id,headers))['messages'][1]['displayed_snapshot']['response']==first

@pytest.mark.parametrize('write_error',[False,True])
async def test_late_existing_turn_wins_over_recomputed_answer(owned_ask,monkeypatch,write_error):
    from app.services import research_conversations as service
    client,maker,calls,models,data,_=owned_ask
    await approve(maker);headers=bearer(token());cid=await conversation(client,headers)
    first=(await client.post('/ask',json=question(cid),headers=headers)).json()
    original=await reopen(client,cid,headers)
    data[:]=[replace(row,value=6) if row.concept=='EarningsPerShareBasic' and row.end=='2025-12-31' else row for row in data]
    actual_read=service.get_completed_response
    reads=[]
    async def first_read_misses(*args,**kwargs):
        reads.append(True)
        if len(reads)==1:return None
        return await actual_read(*args,**kwargs)
    discarded_writes=[]
    async def discarded_thesis(*args,**kwargs):
        discarded_writes.append(True)
    monkeypatch.setattr(service,'get_completed_response',first_read_misses)
    monkeypatch.setattr('app.services.owned_research.save_thesis',discarded_thesis)
    if write_error:
        async def failed_append(*args,**kwargs):
            raise RuntimeError('invented transaction failure')
        monkeypatch.setattr(service,'append_completed_turn',failed_append)
    response=await client.post('/ask',json=question(cid),headers=headers)
    assert response.json()==first and len(reads)==2 and not discarded_writes
    assert len(calls)==2 and not models
    assert (await reopen(client,cid,headers))==original

async def test_missing_diluted_evidence_reopens_as_gap_without_basic_substitution(owned_ask):
    client,maker,calls,models,_,_=owned_ask
    await approve(maker);headers=bearer(token());cid=await conversation(client,headers)
    r=await client.post('/ask',json=question(cid,basis='diluted'),headers=headers)
    result=r.json();assert 'error' not in result,result
    source=result['answer']['source_answer']
    assert source['status']=='insufficient_claim_evidence' and not source['claims']
    assert source['unanswered_parts']==['annual diluted EPS']
    saved=await reopen(client,cid,headers)
    assert saved['messages'][1]['displayed_snapshot']['response']==result
    assert not models

async def test_revoked_account_cannot_append_another_ask_turn(owned_ask):
    from app.services.access_grant_service import revoke_grant
    client,maker,calls,models,_,_=owned_ask
    await approve(maker);headers=bearer(token());cid=await conversation(client,headers)
    assert (await client.post('/ask',json=question(cid),headers=headers)).status_code==200
    before=len(calls)
    async with maker() as db:
        assert await revoke_grant(db,subject=SUBJECT_A)==1
        await db.commit()
    r=await client.post('/ask',json=question(cid,ref='revoked-turn'),headers=headers)
    assert r.status_code==403 and len(calls)==before and not models

async def test_ask_daily_quota_blocks_before_sources_and_second_write(owned_ask,monkeypatch):
    from app.services.usage_tracking import UsageTracker
    from app.security import ask_guard
    client,maker,calls,models,_,_=owned_ask
    tracker=UsageTracker()
    monkeypatch.setattr(ask_guard,'usage_tracker',tracker)
    monkeypatch.setattr(settings,'ask_daily_quota',1)
    await approve(maker);headers=bearer(token());cid=await conversation(client,headers)
    assert (await client.post('/ask',json=question(cid),headers=headers)).status_code==200
    saved=await reopen(client,cid,headers);count=len(calls)
    r=await client.post('/ask',json=question(cid,ref='over-quota'),headers=headers)
    assert r.status_code==429 and len(calls)==count and not models
    assert (await reopen(client,cid,headers))==saved

async def test_owner_preferences_do_not_cross_accounts_or_reweight_source_facts(owned_ask):
    client,maker,calls,models,_,_=owned_ask
    await approve(maker);await approve(maker,EMAIL_B)
    ha,hb=bearer(token()),bearer(token(SUBJECT_B,EMAIL_B))
    p={'enabled':True,'response_depth':'deep','time_horizon':'multi_year',
       'analysis_emphasis':'downside_first','evidence_style':'primary_sources'}
    r=await client.put('/research/personalization',json=p,headers=ha);assert r.status_code==200
    other=await client.get('/research/personalization',headers=hb)
    assert other.status_code==200 and not other.json()['persisted']
    ca=await conversation(client,ha);cb=await conversation(client,hb)
    a=(await client.post('/ask',json=question(ca),headers=ha)).json()
    spoof=question(cb);spoof['personalization_context_data']={'applied':True,**p}
    b=(await client.post('/ask',json=spoof,headers=hb)).json()
    assert 'error' not in a and 'error' not in b
    assert a['routing']['personalization']['applied'] is True
    assert b['routing']['personalization']=={'applied':False}
    assert a['answer']['source_answer']==b['answer']['source_answer']
    assert a['answer']['investment_thesis']['quantitative_claims']==b['answer']['investment_thesis']['quantitative_claims']
    assert (await reopen(client,ca,ha))['messages'][1]['displayed_snapshot']['response']==a
    assert (await reopen(client,cb,hb))['messages'][1]['displayed_snapshot']['response']==b
    assert not models

@pytest.mark.parametrize('invalid',['deleted','foreign','missing','row_version','snapshot_version','shape','error','oversize'])
async def test_saved_response_lookup_rejects_unreplayable_rows(owned_ask,invalid):
    from app.services import research_conversations as service
    from app.db.models import ResearchMessage
    client,maker,_,_,_,_=owned_ask
    await approve(maker);headers=bearer(token());cid=await conversation(client,headers)
    async with maker() as db:
        owner=(await db.execute(select(User.id))).scalar_one()
        original={'answer':{'investment_thesis':{'direct_answer':'Original saved answer'}}}
        assert await service.append_completed_turn(db,user_id=owner,conversation_id=cid,
            question='Original question',response=original,request_ref='one-turn')
        await db.commit()
    async with maker() as db:
        row=(await db.execute(select(ResearchMessage).where(
            ResearchMessage.conversation_id==cid,ResearchMessage.role=='assistant'))).scalar_one()
        if invalid=='deleted':
            assert await service.soft_delete_conversation(db,user_id=owner,conversation_id=cid)
        elif invalid=='row_version':row.snapshot_version=2
        elif invalid=='snapshot_version':row.displayed_snapshot={'response_version':2,'response':original}
        elif invalid=='shape':row.displayed_snapshot={'response_version':1,'response':[]}
        elif invalid=='error':row.displayed_snapshot={'response_version':1,'response':{'error':'failed'}}
        elif invalid=='oversize':row.displayed_snapshot={'response_version':1,'response':{'text':'x'*100001}}
        await db.commit()
        assert await service.get_completed_response(db,user_id='another-owner' if invalid=='foreign' else owner,
            conversation_id=cid,request_ref='absent' if invalid=='missing' else 'one-turn') is None
