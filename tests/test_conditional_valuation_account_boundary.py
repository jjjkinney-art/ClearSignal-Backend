"""Offline signed-JWT -> DB admission -> middleware -> scenario HTTP acceptance.

Only test keys/accounts, a disposable SQLite database and invented SEC records.
No identity resolver, cryptographic verifier or admission service is substituted.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Base, User
from app.middleware.auth_middleware import AuthMiddleware
from app.routers.conditional_valuation import router
from app.security.rate_limit import rate_limiter
from app.services import conditional_valuation_service as svc
from app.services.access_grant_service import create_invite_grant, revoke_grant
from app.services.issuer_identity import parse_directory
from test_conditional_valuation_api import payload, records

KEY='invented-offline-signing-key-not-a-production-secret-000000000000'
SUBJECT_A='11111111-1111-1111-1111-111111111111'
SUBJECT_B='22222222-2222-2222-2222-222222222222'
EMAIL_A='scenario.one@example.test'
EMAIL_B='scenario.two@example.test'
PATH='/research/valuation-scenarios'


def token(subject=SUBJECT_A,email=EMAIL_A,*,key=KEY,algorithm='HS256',**overrides):
    now=datetime.now(timezone.utc)
    claims={'sub':subject,'aud':'authenticated','exp':now+timedelta(minutes=5),
        'email':email,'email_verified':True,'app_metadata':{'provider':'google','providers':['google']},
        'user_metadata':{}}
    claims.update(overrides)
    return jwt.encode(claims,key,algorithm=algorithm)


def bearer(value):
    return {'authorization':'Bearer '+value} if value is not None else {}


@pytest_asyncio.fixture
async def boundary(monkeypatch,tmp_path):
    for name,value in {'auth_enabled':True,'supabase_jwt_secret':KEY,'supabase_audience':'authenticated',
        'beta_admission_mode':'enforce','beta_admission_pepper':'offline-only-pepper-'+'z'*48,
        'conditional_valuation_scenarios_enabled':True,'enable_data_retrieval':True,
        'rate_limit_enabled':False}.items():monkeypatch.setattr(settings,name,value)
    engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'accounts.sqlite'))
    async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
    maker=sessionmaker(engine,class_=AsyncSession,expire_on_commit=False)
    @asynccontextmanager
    async def get_session():
        async with maker() as session:yield session
    monkeypatch.setattr('app.db.connection.get_session',get_session)
    monkeypatch.setattr(svc,'_current_date',lambda:date(2026,3,2))
    monkeypatch.setattr(svc,'_load_directory',lambda:parse_directory({'0':{'ticker':'ZQXB','title':'Invented Issuer','cik_str':1234567}}))
    calls=[]
    def fetch(*args,**kwargs):
        calls.append((args,kwargs));return records()
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',fetch)
    app=FastAPI();app.include_router(router)
    observed=[]
    @app.middleware('http')
    async def observe(request,call_next):
        # Observe only: real AuthMiddleware supplies every identity field.
        observed.append((request.state.user_id,request.state.auth_subject,request.state.is_authenticated))
        return await call_next(request)
    app.add_middleware(AuthMiddleware)
    rate_limiter.reset()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://offline.invalid') as client:
        yield client,maker,calls,observed
    rate_limiter.reset()
    await engine.dispose()


async def approve(maker,email=EMAIL_A,*,expires_at=None):
    async with maker() as session:
        await create_invite_grant(session,raw_email=email,expires_at=expires_at)
        await session.commit()


async def users(maker):
    async with maker() as session:return (await session.execute(select(User))).scalars().all()


@pytest.mark.parametrize('kind',['missing','malformed','expired','wrong_audience','wrong_key','wrong_algorithm','missing_subject'])
async def test_invalid_credentials_never_provision_or_fetch(boundary,kind):
    client,maker,calls,observed=boundary
    await approve(maker)
    variants={'missing':None,'malformed':'not-a-token','expired':token(exp=datetime.now(timezone.utc)-timedelta(seconds=10)),
        'wrong_audience':token(aud='some-other-service'),'wrong_key':token(key='wrong-test-key-'+'x'*48),
        'wrong_algorithm':token(algorithm='HS512'),'missing_subject':token(sub=None)}
    response=await client.post(PATH,json=payload(),headers=bearer(variants[kind]))
    assert response.status_code==401
    assert not calls and not observed and await users(maker)==[]
    assert KEY not in response.text and EMAIL_A not in response.text


@pytest.mark.parametrize('kind',['uninvited','expired_invite','wrong_provider','metadata_email','anonymous'])
async def test_signed_but_unadmitted_identities_do_not_reach_sources(boundary,kind):
    client,maker,calls,observed=boundary
    if kind!='uninvited':
        await approve(maker,expires_at=datetime.now(timezone.utc)-timedelta(seconds=10) if kind=='expired_invite' else None)
    values={'uninvited':token(),'expired_invite':token(),'wrong_provider':token(app_metadata={'provider':'untrusted','providers':['untrusted']}),
        'metadata_email':token(email=None,user_metadata={'email':EMAIL_A}), 'anonymous':token(is_anonymous=True)}
    response=await client.post(PATH,json=payload(),headers=bearer(values[kind]))
    assert response.status_code==403
    assert not calls and not observed and await users(maker)==[]
    assert response.json()=={'detail':'This account does not have access to the controlled beta.'}


async def test_real_verification_and_grant_redemption_reach_the_scenario(boundary):
    client,maker,calls,observed=boundary
    await approve(maker)
    response=await client.post(PATH,json=payload(),headers=bearer(token()))
    assert response.status_code==200 and response.json()['available']
    assert response.headers['cache-control']=='no-store'
    rows=await users(maker);assert len(rows)==1
    assert rows[0].auth_subject==SUBJECT_A
    assert observed==[(str(rows[0].id),SUBJECT_A,True)]
    assert len(calls)==1 and not response.json()['admitted'] and not response.json()['launch_ready']
    assert SUBJECT_A not in response.text and str(rows[0].id) not in response.text


async def test_revocation_denies_an_already_provisioned_account_before_new_fetch(boundary):
    client,maker,calls,observed=boundary
    await approve(maker)
    assert (await client.post(PATH,json=payload(),headers=bearer(token()))).status_code==200
    async with maker() as session:
        assert await revoke_grant(session,subject=SUBJECT_A)==1
        await session.commit()
    response=await client.post(PATH,json=payload(),headers=bearer(token()))
    assert response.status_code==403 and len(calls)==1 and len(observed)==1
    assert len(await users(maker))==1


async def test_same_email_cannot_transfer_an_existing_local_account(boundary):
    client,maker,calls,observed=boundary
    await approve(maker)
    assert (await client.post(PATH,json=payload(),headers=bearer(token()))).status_code==200
    response=await client.post(PATH,json=payload(),headers=bearer(token(subject=SUBJECT_B)))
    assert response.status_code==403 and len(calls)==1 and len(observed)==1
    rows=await users(maker);assert len(rows)==1 and rows[0].auth_subject==SUBJECT_A


async def test_two_admitted_accounts_do_not_share_assumptions_or_identity(boundary):
    client,maker,calls,observed=boundary
    await approve(maker);await approve(maker,EMAIL_B)
    a=payload();b=payload();b['assumptions']['price']['value']='200'
    first=await client.post(PATH,json=a,headers=bearer(token()))
    second=await client.post(PATH,json=b,headers=bearer(token(SUBJECT_B,EMAIL_B)))
    again=await client.post(PATH,json=a,headers=bearer(token()))
    assert all(r.status_code==200 and r.json()['available'] for r in (first,second,again))
    assert first.json()==again.json() and first.json()['scenario']!=second.json()['scenario']
    rows=await users(maker);assert len(rows)==2
    assert observed[0][0]==observed[2][0] and observed[0][0]!=observed[1][0]
    assert len(calls)==3


async def test_expensive_user_budget_uses_resolved_local_identity(boundary,monkeypatch):
    client,maker,calls,observed=boundary
    from app.db.repositories.account_repo import create_user
    from app.services.access_grant_service import create_subject_grant
    local_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    async with maker() as session:
        await create_user(session,user_id=local_id,email=EMAIL_A,auth_subject=SUBJECT_A)
        await create_subject_grant(session,subject=SUBJECT_A)
        await session.commit()
    monkeypatch.setattr(settings,'rate_limit_enabled',True)
    monkeypatch.setattr(settings,'rate_limit_expensive_per_ip_per_min',100)
    monkeypatch.setattr(settings,'rate_limit_expensive_per_user_per_min',1)
    monkeypatch.setattr(settings,'rate_limit_per_user_per_min',100)
    first=await client.post(PATH,json=payload(),headers={**bearer(token()),'x-forwarded-for':'203.0.113.1'})
    second=await client.post(PATH,json=payload(),headers={**bearer(token()),'x-forwarded-for':'203.0.113.2'})
    assert first.status_code==200 and second.status_code==429
    assert int(second.headers['retry-after'])>=1 and len(calls)==1 and len(observed)==1
    row=(await users(maker))[0]
    assert str(row.id)==local_id and observed[0][0]==local_id
    assert rate_limiter.peek('expensive:user:'+str(row.id),settings.rate_limit_window_s)==1
    assert rate_limiter.peek('expensive:user:'+SUBJECT_A,settings.rate_limit_window_s)==0


async def test_no_database_fails_closed_despite_valid_signed_invited_identity(boundary,monkeypatch):
    client,maker,calls,observed=boundary
    await approve(maker)
    @asynccontextmanager
    async def unavailable():yield None
    monkeypatch.setattr('app.db.connection.get_session',unavailable)
    response=await client.post(PATH,json=payload(),headers=bearer(token()))
    assert response.status_code==401 and not calls and not observed and await users(maker)==[]


@pytest.mark.parametrize('kind',['valid','wrong_issuer','wrong_audience','expired','unknown_key_id','wrong_signature','symmetric_algorithm'])
async def test_real_es256_verification_and_jwks_key_selection(boundary,monkeypatch,kind):
    """Only JWKS document delivery is substituted; selection/crypto remain real."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from app.middleware import auth_middleware as auth
    import json
    client,maker,calls,observed=boundary
    await approve(maker)
    project='https://offline-project.invalid'
    issuer=project+'/auth/v1'
    key=ec.derive_private_key(17,ec.SECP256R1())
    jwk=json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid='offline-key',use='sig',alg='ES256')
    jwks_client=jwt.PyJWKClient(issuer+'/.well-known/jwks.json')
    deliveries=[]
    def deliver():
        deliveries.append(True);return {'keys':[jwk]}
    monkeypatch.setattr(jwks_client,'fetch_data',deliver)
    monkeypatch.setattr(auth,'_jwks_clients',{issuer+'/.well-known/jwks.json':jwks_client})
    monkeypatch.setattr(settings,'supabase_jwt_secret','')
    monkeypatch.setattr(settings,'supabase_project_url',project)
    claims=jwt.decode(token(),KEY,algorithms=['HS256'],audience='authenticated')
    claims['iss']=issuer
    if kind=='wrong_issuer':claims['iss']='https://other.invalid/auth/v1'
    if kind=='wrong_audience':claims['aud']='another-service'
    if kind=='expired':claims['exp']=int((datetime.now(timezone.utc)-timedelta(seconds=10)).timestamp())
    signature_key=ec.derive_private_key(19,ec.SECP256R1()) if kind=='wrong_signature' else key
    signed=token() if kind=='symmetric_algorithm' else jwt.encode(claims,signature_key,algorithm='ES256',
        headers={'kid':'unknown-key' if kind=='unknown_key_id' else 'offline-key'})
    response=await client.post(PATH,json=payload(),headers=bearer(signed))
    if kind=='valid':
        assert response.status_code==200 and response.json()['available']
        assert len(calls)==1 and len(observed)==1 and len(await users(maker))==1
    else:
        assert response.status_code==401 and not calls and not observed and await users(maker)==[]
    assert bool(deliveries)==(kind!='symmetric_algorithm')


async def test_scenario_does_not_create_research_memory_snapshot_or_alert(boundary):
    from sqlalchemy import func
    client,maker,calls,observed=boundary
    await approve(maker)
    response=await client.post(PATH,json=payload(),headers=bearer(token()))
    assert response.status_code==200 and response.json()['available']
    # Account provisioning/admission audits are expected. Scenario persistence is not.
    async with maker() as session:
        for name in ('research_conversations','research_messages','thesis_versions','scenario_snapshot','memory_entries','notifications'):
            assert (await session.execute(select(func.count()).select_from(Base.metadata.tables[name]))).scalar_one()==0


async def test_concurrent_admitted_accounts_keep_hypotheses_separate(boundary,monkeypatch):
    import threading
    client,maker,calls,observed=boundary
    await approve(maker);await approve(maker,EMAIL_B)
    # Establish identities first so this checks simultaneous scenario processing,
    # not concurrent first-login invitation redemption (covered by admission tests).
    assert (await client.post(PATH,json=payload(),headers=bearer(token()))).status_code==200
    assert (await client.post(PATH,json=payload(),headers=bearer(token(SUBJECT_B,EMAIL_B)))).status_code==200
    gate=threading.Barrier(2,timeout=10)
    original=svc.get_company_fact_records_for_concept_units
    def simultaneous(*args,**kwargs):
        gate.wait();return original(*args,**kwargs)
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',simultaneous)
    a=payload();b=payload()
    a['assumptions']['price']['provenance']['reference']='private-user-A-hypothesis'
    b['assumptions']['price']['provenance']['reference']='private-user-B-hypothesis'
    b['assumptions']['price']['value']='200'
    first,second=await asyncio.wait_for(asyncio.gather(
        client.post(PATH,json=a,headers=bearer(token())),
        client.post(PATH,json=b,headers=bearer(token(SUBJECT_B,EMAIL_B)))),timeout=20)
    assert all(r.status_code==200 and r.json()['available'] for r in (first,second))
    assert 'private-user-A-hypothesis' in first.text and 'private-user-B-hypothesis' not in first.text
    assert 'private-user-B-hypothesis' in second.text and 'private-user-A-hypothesis' not in second.text
    assert first.json()['scenario']['values']!=second.json()['scenario']['values']
    assert len(calls)==4 and len(await users(maker))==2


async def test_disabled_endpoint_never_fetches_after_real_authentication(boundary,monkeypatch):
    client,maker,calls,observed=boundary
    await approve(maker)
    monkeypatch.setattr(settings,'conditional_valuation_scenarios_enabled',False)
    response=await client.post(PATH,json=payload(),headers=bearer(token()))
    assert response.status_code==404 and not calls
    # Global authentication still runs before the handler's feature gate.
    assert len(await users(maker))==1 and observed[0][2] is True


async def test_provider_failure_after_real_admission_does_not_leak_inputs(boundary,monkeypatch,caplog):
    client,maker,calls,observed=boundary
    await approve(maker)
    signed=token()
    def fail(*args,**kwargs):
        raise RuntimeError('SECRET_CANARY '+signed+' '+EMAIL_A)
    monkeypatch.setattr(svc,'get_company_fact_records_for_concept_units',fail)
    response=await client.post(PATH,json=payload(),headers=bearer(signed))
    assert response.status_code==200 and response.json()['stage']=='source_unavailable'
    assert not response.json()['available'] and response.json()['source_claims']==[]
    assert response.json()['evidence_references']==[]
    for private in ('SECRET_CANARY',signed,EMAIL_A,KEY):
        assert private not in response.text and private not in caplog.text
