from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import (
    Base, BenchmarkShadowJob, BenchmarkShadowTransition,
)
from app.services import benchmark_shadow_state_service as service


NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def _reservation(identifier="request-1", account="synthetic:a", issuer="AAPL", cost=1):
    return service.Reservation.build(
        request_id=identifier, account_ref=account, issuer_id=issuer,
        capability="frozen_research", estimated_cost_usd=cost,
    )


async def _database(tmp_path, name="shadow.db"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/{name}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_reservation_is_durable_idempotent_and_content_free(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            first = await service.reserve(session, _reservation(), now=NOW)
        first_id = first.id
    async with factory() as restarted_session:
        async with restarted_session.begin():
            duplicate = await service.reserve(
                restarted_session, _reservation(), now=NOW + timedelta(seconds=1)
            )
        assert duplicate.id == first_id
        assert duplicate.status == "reserved"
        assert duplicate.account_ref == "synthetic:a"
    columns = set(BenchmarkShadowJob.__table__.columns.keys())
    assert not {"prompt", "question", "answer", "evidence", "payload"} & columns
    await engine.dispose()


@pytest.mark.asyncio
async def test_request_identifier_payload_conflict_fails_closed(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            await service.reserve(session, _reservation(), now=NOW)
        with pytest.raises(service.ShadowStateError, match="different payload"):
            async with session.begin():
                await service.reserve(
                    session, _reservation(issuer="MSFT"), now=NOW
                )
    await engine.dispose()


def test_real_accounts_are_rejected_before_persistence():
    with pytest.raises(service.ShadowStateError, match="synthetic"):
        _reservation(account="account:real")


@pytest.mark.asyncio
async def test_claim_fails_closed_until_durable_control_exists(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            job = await service.reserve(session, _reservation(), now=NOW)
        async with session.begin():
            assert await service.claim(
                session, job.id, holder_id="worker-a", now=NOW
            ) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_control_kill_state_persists_and_uses_version_cas(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            state = await service.control_state(session, now=NOW)
            assert state.version == 0
        async with session.begin():
            assert await service.set_kill_state(
                session, expected_version=0, manual_kill=True,
                automatic_kill=False, reason_code="operator_stop",
                actor_id="operator:a", now=NOW,
            ) is True
        async with session.begin():
            assert await service.set_kill_state(
                session, expected_version=0, manual_kill=False,
                automatic_kill=False, reason_code=None,
                actor_id="operator:b", now=NOW,
            ) is False
    async with factory() as restarted_session:
        assert await service.is_killed(restarted_session) is True
        state = await service.control_state(restarted_session)
        assert state.version == 1
        assert state.updated_by == "operator:a"
    await engine.dispose()


@pytest.mark.asyncio
async def test_kill_switch_blocks_claims_and_lease_renewal(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            await service.control_state(session, now=NOW)
            running_job = await service.reserve(session, _reservation("running"), now=NOW)
            waiting_job = await service.reserve(
                session, _reservation("waiting", account="synthetic:b", issuer="MSFT"),
                now=NOW,
            )
        async with session.begin():
            running = await service.claim(
                session, running_job.id, holder_id="worker-a", now=NOW
            )
        async with session.begin():
            assert await service.set_kill_state(
                session, expected_version=0, manual_kill=True,
                automatic_kill=False, reason_code="operator_stop",
                actor_id="operator:a", now=NOW + timedelta(seconds=1),
            )
        async with session.begin():
            assert await service.claim(
                session, waiting_job.id, holder_id="worker-b",
                now=NOW + timedelta(seconds=2),
            ) is None
            assert await service.renew(
                session, running_job.id, holder_id="worker-a",
                fence_token=running.fence_token,
                now=NOW + timedelta(seconds=2),
            ) is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_database_constraints_reject_bypassed_unsafe_rows(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        with pytest.raises(Exception):
            async with session.begin():
                session.add(BenchmarkShadowJob(
                    id="unsafe", request_id="unsafe", request_fingerprint="x" * 64,
                    account_ref="real-account", issuer_id="AAPL",
                    capability="frozen_research", estimated_cost_usd=-1,
                    status="invented", reserved_at=NOW,
                    retention_until=NOW + timedelta(days=1),
                ))
                await session.flush()
    await engine.dispose()


@pytest.mark.asyncio
async def test_fenced_lease_rejects_stale_worker_and_survives_restart(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            await service.control_state(session, now=NOW)
            job = await service.reserve(session, _reservation(), now=NOW)
        async with session.begin():
            running = await service.claim(
                session, job.id, holder_id="worker-a", now=NOW,
                lease_seconds=30,
            )
            assert running.status == "running"
            assert running.fence_token == 1
    async with factory() as restarted_session:
        async with restarted_session.begin():
            assert await service.renew(
                restarted_session, job.id, holder_id="worker-zombie",
                fence_token=1, now=NOW + timedelta(seconds=5),
            ) is False
            assert await service.renew(
                restarted_session, job.id, holder_id="worker-a",
                fence_token=0, now=NOW + timedelta(seconds=5),
            ) is False
            assert await service.renew(
                restarted_session, job.id, holder_id="worker-a",
                fence_token=1, now=NOW + timedelta(seconds=5),
            ) is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_only_one_worker_claims_a_reservation(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            await service.control_state(session, now=NOW)
            job = await service.reserve(session, _reservation(), now=NOW)
    async with factory() as first:
        async with first.begin():
            claimed = await service.claim(
                first, job.id, holder_id="worker-a", now=NOW
            )
            assert claimed is not None
    async with factory() as second:
        async with second.begin():
            assert await service.claim(
                second, job.id, holder_id="worker-b", now=NOW
            ) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_completion_is_idempotent_and_transition_chain_verifies(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            await service.control_state(session, now=NOW)
            job = await service.reserve(session, _reservation(), now=NOW)
        async with session.begin():
            running = await service.claim(
                session, job.id, holder_id="worker-a", now=NOW
            )
        async with session.begin():
            finished = await service.finish(
                session, job.id, holder_id="worker-a",
                fence_token=running.fence_token,
                now=NOW + timedelta(seconds=2), succeeded=True,
                actual_cost_usd=0.75,
            )
            assert finished.status == "succeeded"
        async with session.begin():
            again = await service.finish(
                session, job.id, holder_id="worker-a",
                fence_token=running.fence_token,
                now=NOW + timedelta(seconds=3), succeeded=True,
                actual_cost_usd=0.75,
            )
            assert again.id == job.id
        assert await service.verify_transition_chain(session, job.id) == ()
        transitions = (
            await session.execute(
                select(BenchmarkShadowTransition)
                .where(BenchmarkShadowTransition.job_id == job.id)
            )
        ).scalars().all()
        assert [item.to_status for item in transitions] == [
            "reserved", "running", "succeeded",
        ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_lease_recovers_once_with_conservative_cost(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            await service.control_state(session, now=NOW)
            job = await service.reserve(
                session, _reservation(cost=2.5), now=NOW
            )
        async with session.begin():
            await service.claim(
                session, job.id, holder_id="worker-a", now=NOW,
                lease_seconds=10,
            )
    async with factory() as restarted_session:
        async with restarted_session.begin():
            recovered = await service.recover_expired(
                restarted_session, now=NOW + timedelta(seconds=11)
            )
            assert recovered == (job.id,)
        async with restarted_session.begin():
            assert await service.recover_expired(
                restarted_session, now=NOW + timedelta(seconds=12)
            ) == ()
        restored = await service.repo.job_by_id(restarted_session, job.id)
        assert restored.status == "timed_out"
        assert restored.actual_cost_usd == 2.5
        assert await service.verify_transition_chain(restarted_session, job.id) == ()
    await engine.dispose()


@pytest.mark.asyncio
async def test_transition_tampering_is_detected(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            job = await service.reserve(session, _reservation(), now=NOW)
        await session.execute(
            text("UPDATE benchmark_shadow_transitions SET reason_code='tampered' WHERE job_id=:job_id"),
            {"job_id": job.id},
        )
        await session.commit()
        errors = await service.verify_transition_chain(session, job.id)
        assert any("event hash mismatch" in item for item in errors)
    await engine.dispose()


@pytest.mark.asyncio
async def test_retention_purges_only_expired_terminal_jobs(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            await service.control_state(session, now=NOW)
            expired = await service.reserve(
                session, _reservation("expired"), now=NOW,
                retention_days=1,
            )
            active = await service.reserve(
                session, _reservation("active", account="synthetic:b", issuer="MSFT"),
                now=NOW, retention_days=1,
            )
        async with session.begin():
            running = await service.claim(
                session, expired.id, holder_id="worker-a", now=NOW
            )
        async with session.begin():
            await service.finish(
                session, expired.id, holder_id="worker-a",
                fence_token=running.fence_token, now=NOW, succeeded=True,
                actual_cost_usd=1,
            )
        async with session.begin():
            purged = await service.purge_retained(
                session, now=NOW + timedelta(days=2)
            )
            assert purged == (expired.id,)
        assert await service.repo.job_by_id(session, expired.id) is None
        assert await service.repo.transitions_for_job(session, expired.id) == ()
        assert await service.repo.job_by_id(session, active.id) is not None
    await engine.dispose()


def test_service_has_no_scheduler_provider_or_delivery_imports():
    tree = ast.parse(open(service.__file__, encoding="utf-8").read())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(
        token in name
        for name in imports
        for token in ("scheduler", "provider", "delivery", "notification")
    )
