from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.config import settings
from app.db.models import AuditLog, Base
from app.routers import benchmark_shadow_admin as admin
from app.services import benchmark_shadow_state_service as state


NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
ADMIN_ID = "11111111-1111-4111-8111-111111111111"
MEMBER_ID = "22222222-2222-4222-8222-222222222222"


async def _database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/admin.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _request(user_id: str | None, *, authenticated: bool = True) -> Request:
    request = Request({
        "type": "http", "method": "GET", "path": "/", "headers": [
            (b"user-agent", b"operator-console"),
            (b"x-forwarded-for", b"203.0.113.7, 10.0.0.1"),
        ], "client": ("127.0.0.1", 1234),
    })
    request.state.user_id = user_id
    request.state.is_authenticated = authenticated
    request.state.auth_subject = f"subject:{user_id}" if authenticated else None
    return request


def _install_session(monkeypatch, factory):
    @asynccontextmanager
    async def session_context():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(admin, "get_session", session_context)


@pytest.fixture(autouse=True)
def _authenticated_admin(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_user_ids", ADMIN_ID)


@pytest.mark.asyncio
async def test_status_is_admin_only_and_contains_aggregate_state(tmp_path, monkeypatch):
    engine, factory = await _database(tmp_path)
    _install_session(monkeypatch, factory)
    async with factory() as session:
        async with session.begin():
            await state.reserve(
                session,
                state.Reservation.build(
                    request_id="request-1", account_ref="synthetic:hidden-owner",
                    issuer_id="AAPL", capability="frozen_research",
                    estimated_cost_usd=1.25,
                ),
                now=NOW,
            )

    snapshot = await admin.benchmark_shadow_status(_request(ADMIN_ID))
    assert snapshot["job_count"] == 1
    assert snapshot["status_counts"] == {"reserved": 1}
    assert snapshot["estimated_cost_usd"] == 1.25
    assert snapshot["effective_killed"] is True
    assert snapshot["scheduler_present"] is False
    assert snapshot["execution_enabled"] is False
    serialized = str(snapshot)
    assert "hidden-owner" not in serialized
    assert "request-1" not in serialized
    assert "AAPL" not in serialized

    with pytest.raises(HTTPException) as forbidden:
        await admin.benchmark_shadow_status(_request(MEMBER_ID))
    assert forbidden.value.status_code == 403
    with pytest.raises(HTTPException) as unauthenticated:
        await admin.benchmark_shadow_status(_request(None, authenticated=False))
    assert unauthenticated.value.status_code == 401
    await engine.dispose()


@pytest.mark.asyncio
async def test_rehearsal_is_admin_only_aggregate_and_inert():
    result = await admin.benchmark_shadow_rehearsal(_request(ADMIN_ID))
    assert result["passed"] is True
    assert result["issuer_count"] == 7
    assert result["sector_count"] == 6
    assert result["decision_counts"] == {"dry_run": 7}
    assert result["active_jobs"] == 0
    assert result["reserved_cost_usd"] == 0
    assert result["execution_enabled"] is False
    assert all(result["checks"].values())
    serialized = str(result)
    for private_detail in (
        "synthetic:", "shadow-v1", "v1-aapl", "account_ref", "issuer_id",
    ):
        assert private_detail not in serialized

    with pytest.raises(HTTPException) as forbidden:
        await admin.benchmark_shadow_rehearsal(_request(MEMBER_ID))
    assert forbidden.value.status_code == 403
    with pytest.raises(HTTPException) as unauthenticated:
        await admin.benchmark_shadow_rehearsal(
            _request(None, authenticated=False)
        )
    assert unauthenticated.value.status_code == 401


@pytest.mark.asyncio
async def test_rehearsal_failure_is_redacted_and_fails_closed(monkeypatch):
    def unavailable(**_kwargs):
        raise RuntimeError("secret provider detail")

    monkeypatch.setattr(admin, "run_rehearsal", unavailable)
    with pytest.raises(HTTPException) as failure:
        await admin.benchmark_shadow_rehearsal(_request(ADMIN_ID))
    assert failure.value.status_code == 503
    assert failure.value.detail == (
        "Benchmark shadow rehearsal unavailable: RuntimeError"
    )
    assert "secret" not in failure.value.detail


@pytest.mark.asyncio
async def test_kill_is_versioned_idempotent_and_audited(tmp_path, monkeypatch):
    engine, factory = await _database(tmp_path)
    _install_session(monkeypatch, factory)

    result = await admin.benchmark_shadow_kill(
        admin.KillRequest(expected_version=0, reason_code="operator_stop"),
        _request(ADMIN_ID),
    )
    assert result["manual_kill"] is True
    assert result["automatic_kill"] is False
    assert result["control_version"] == 1
    assert result["reason_code"] == "operator_stop"

    duplicate = await admin.benchmark_shadow_kill(
        admin.KillRequest(expected_version=1, reason_code="maintenance"),
        _request(ADMIN_ID),
    )
    assert duplicate["control_version"] == 1
    assert duplicate["reason_code"] == "operator_stop"

    async with factory() as session:
        audits = (await session.execute(select(AuditLog))).scalars().all()
        assert len(audits) == 1
        assert audits[0].user_id == ADMIN_ID
        assert audits[0].action == "benchmark_shadow_kill"
        assert audits[0].resource == "benchmark_shadow_control"
        assert audits[0].ip_address == "203.0.113.7"
        assert "operator_stop" not in str(audits[0].__dict__)
    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_version_is_rejected_without_mutation_or_audit(tmp_path, monkeypatch):
    engine, factory = await _database(tmp_path)
    _install_session(monkeypatch, factory)
    await admin.benchmark_shadow_kill(
        admin.KillRequest(expected_version=0, reason_code="operator_stop"),
        _request(ADMIN_ID),
    )

    with pytest.raises(HTTPException) as conflict:
        await admin.benchmark_shadow_restore(
            admin.RestoreRequest(expected_version=0), _request(ADMIN_ID)
        )
    assert conflict.value.status_code == 409

    async with factory() as session:
        control = await state.control_state(session)
        audits = (await session.execute(select(AuditLog))).scalars().all()
        assert control.version == 1
        assert control.manual_kill is True
        assert len(audits) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_restore_preserves_automatic_safety_halt(tmp_path, monkeypatch):
    engine, factory = await _database(tmp_path)
    _install_session(monkeypatch, factory)
    async with factory() as session:
        async with session.begin():
            await state.control_state(session, actor_id=ADMIN_ID, now=NOW)
            assert await state.set_kill_state(
                session, expected_version=0, manual_kill=True,
                automatic_kill=True, reason_code="integrity_violation",
                actor_id=ADMIN_ID, now=NOW,
            )

    result = await admin.benchmark_shadow_restore(
        admin.RestoreRequest(expected_version=1), _request(ADMIN_ID)
    )
    assert result["manual_kill"] is False
    assert result["automatic_kill"] is True
    assert result["effective_killed"] is True
    assert result["reason_code"] == "integrity_violation"
    assert result["control_version"] == 2

    async with factory() as session:
        audits = (await session.execute(select(AuditLog))).scalars().all()
        assert len(audits) == 1
        assert audits[0].action == "benchmark_shadow_restore"
    await engine.dispose()


@pytest.mark.asyncio
async def test_disabled_database_fails_closed(monkeypatch):
    @asynccontextmanager
    async def unavailable():
        yield None

    monkeypatch.setattr(admin, "get_session", unavailable)
    status = await admin.benchmark_shadow_status(_request(ADMIN_ID))
    assert status["db_available"] is False
    assert status["effective_killed"] is True
    assert status["safe_state"] is True
    with pytest.raises(HTTPException) as unavailable_mutation:
        await admin.benchmark_shadow_kill(
            admin.KillRequest(expected_version=0, reason_code="operator_stop"),
            _request(ADMIN_ID),
        )
    assert unavailable_mutation.value.status_code == 503


def test_operator_router_has_no_live_execution_or_delivery_dependencies():
    source = open(admin.__file__, encoding="utf-8").read()
    forbidden = ("provider", "deliver", "notification", "research")
    imports = tuple(
        node.module or ""
        for node in __import__("ast").walk(__import__("ast").parse(source))
        if isinstance(node, __import__("ast").ImportFrom)
    )
    assert not any(term in module for module in imports for term in forbidden)
