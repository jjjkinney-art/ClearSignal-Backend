from __future__ import annotations

import asyncio
import ast
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, BenchmarkShadowCancellation
from app.services import benchmark_provider_cancellation as cancellation
from app.services import benchmark_shadow_state_service as state


NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
OPERATION_REFERENCE = "provider-operation-secret-123"


class Canceller:
    def __init__(self, result=None, *, delay=0, error=None):
        self.result = result
        self.delay = delay
        self.error = error
        self.calls = []

    async def cancel(self, operation_reference):
        self.calls.append(operation_reference)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


async def _database(tmp_path, name="cancel.db"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/{name}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _running_job(session):
    await state.control_state(session, now=NOW)
    job = await state.reserve(
        session,
        state.Reservation.build(
            request_id="request-1", account_ref="synthetic:benchmark",
            issuer_id="AAPL", capability="frozen_research",
            estimated_cost_usd=2.5,
        ),
        now=NOW,
    )
    return await state.claim(
        session, job.id, holder_id="worker-a", now=NOW,
    )


@pytest.mark.asyncio
async def test_local_fence_is_committed_before_provider_call_and_blocks_late_result(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            running = await _running_job(session)
        async with session.begin():
            attempt = await cancellation.request_cancellation(
                session, job_id=running.id, fence_token=running.fence_token,
                provider_name="synthetic-provider",
                operation_reference=OPERATION_REFERENCE,
                reason_code="operator_stop", actor_id="operator-a", now=NOW,
            )

    async with factory() as restarted:
        job = await state.repo.job_by_id(restarted, running.id)
        assert job.status == "cancelled"
        assert job.actual_cost_usd == 2.5
        await restarted.rollback()
        with pytest.raises(state.ShadowStateError, match="terminal"):
            async with restarted.begin():
                await state.finish(
                    restarted, running.id, holder_id="worker-a",
                    fence_token=running.fence_token,
                    now=NOW + timedelta(seconds=1), succeeded=True,
                    actual_cost_usd=0.5,
                )
        persisted = await state.repo.cancellation_by_id(restarted, attempt.id)
        assert persisted.outcome == "pending"
        assert persisted.operation_ref_hash != OPERATION_REFERENCE
        assert OPERATION_REFERENCE not in str(persisted.__dict__)
    await engine.dispose()


@pytest.mark.asyncio
async def test_acknowledged_cancellation_is_durable_and_idempotent(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            running = await _running_job(session)
        async with session.begin():
            attempt = await cancellation.request_cancellation(
                session, job_id=running.id, fence_token=running.fence_token,
                provider_name="synthetic-provider",
                operation_reference=OPERATION_REFERENCE,
                reason_code="operator_stop", actor_id="operator-a", now=NOW,
            )
    adapter = Canceller(cancellation.ProviderCancellationResult(True, "accepted"))
    async with factory() as session:
        async with session.begin():
            result = await cancellation.complete_provider_cancellation(
                session, cancellation_id=attempt.id,
                operation_reference=OPERATION_REFERENCE, canceller=adapter,
                timeout_seconds=1, now=NOW + timedelta(seconds=1),
            )
        assert result.outcome == "acknowledged"
        assert result.automatic_kill is False
        async with session.begin():
            duplicate = await cancellation.complete_provider_cancellation(
                session, cancellation_id=attempt.id,
                operation_reference=OPERATION_REFERENCE, canceller=adapter,
                timeout_seconds=1, now=NOW + timedelta(seconds=2),
            )
        assert duplicate.outcome == "acknowledged"
        assert adapter.calls == [OPERATION_REFERENCE]
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter,expected",
    [
        (Canceller(cancellation.ProviderCancellationResult(False, "denied")), "rejected"),
        (Canceller(error=RuntimeError("provider unavailable")), "error"),
        (Canceller(cancellation.ProviderCancellationResult(True, "late"), delay=0.05), "timed_out"),
    ],
)
async def test_unconfirmed_cancellation_engages_automatic_kill(
    tmp_path, adapter, expected,
):
    engine, factory = await _database(tmp_path, f"{expected}.db")
    async with factory() as session:
        async with session.begin():
            running = await _running_job(session)
        async with session.begin():
            attempt = await cancellation.request_cancellation(
                session, job_id=running.id, fence_token=running.fence_token,
                provider_name="synthetic-provider",
                operation_reference=OPERATION_REFERENCE,
                reason_code="operator_stop", actor_id="operator-a", now=NOW,
            )
    async with factory() as session:
        async with session.begin():
            result = await cancellation.complete_provider_cancellation(
                session, cancellation_id=attempt.id,
                operation_reference=OPERATION_REFERENCE, canceller=adapter,
                timeout_seconds=0.01 if expected == "timed_out" else 1,
                now=NOW + timedelta(seconds=1),
            )
        assert result.outcome == expected
        assert result.automatic_kill is True
        control = await state.control_state(session)
        assert control.automatic_kill is True
        assert control.reason_code == "provider_cancellation_unconfirmed"
    await engine.dispose()


@pytest.mark.asyncio
async def test_operation_reference_mismatch_never_calls_provider(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            running = await _running_job(session)
        async with session.begin():
            attempt = await cancellation.request_cancellation(
                session, job_id=running.id, fence_token=running.fence_token,
                provider_name="synthetic-provider",
                operation_reference=OPERATION_REFERENCE,
                reason_code="operator_stop", actor_id="operator-a", now=NOW,
            )
    adapter = Canceller(cancellation.ProviderCancellationResult(True, "accepted"))
    async with factory() as session:
        with pytest.raises(state.ShadowStateError, match="reference mismatch"):
            async with session.begin():
                await cancellation.complete_provider_cancellation(
                    session, cancellation_id=attempt.id,
                    operation_reference="wrong-reference", canceller=adapter,
                    timeout_seconds=1, now=NOW,
                )
        assert adapter.calls == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_failed_provider_cancellation_can_retry_without_reopening_job(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            running = await _running_job(session)
        async with session.begin():
            first = await cancellation.request_cancellation(
                session, job_id=running.id, fence_token=running.fence_token,
                provider_name="synthetic-provider",
                operation_reference=OPERATION_REFERENCE,
                reason_code="operator_stop", actor_id="operator-a", now=NOW,
            )
    async with factory() as session:
        async with session.begin():
            rejected = await cancellation.complete_provider_cancellation(
                session, cancellation_id=first.id,
                operation_reference=OPERATION_REFERENCE,
                canceller=Canceller(
                    cancellation.ProviderCancellationResult(False, "denied")
                ),
                timeout_seconds=1, now=NOW + timedelta(seconds=1),
            )
        assert rejected.automatic_kill is True
        async with session.begin():
            second = await cancellation.request_cancellation(
                session, job_id=running.id, fence_token=running.fence_token,
                provider_name="synthetic-provider",
                operation_reference=OPERATION_REFERENCE,
                reason_code="operator_retry", actor_id="operator-a",
                now=NOW + timedelta(seconds=2),
            )
        assert second.attempt_number == 2
        async with session.begin():
            acknowledged = await cancellation.complete_provider_cancellation(
                session, cancellation_id=second.id,
                operation_reference=OPERATION_REFERENCE,
                canceller=Canceller(
                    cancellation.ProviderCancellationResult(True, "accepted")
                ),
                timeout_seconds=1, now=NOW + timedelta(seconds=3),
            )
        assert acknowledged.outcome == "acknowledged"
        # Provider acknowledgement never auto-clears an existing safety stop.
        control = await state.control_state(session)
        assert control.automatic_kill is True
        job = await state.repo.job_by_id(session, running.id)
        assert job.status == "cancelled"
        transitions = await state.repo.transitions_for_job(session, running.id)
        assert [item.to_status for item in transitions] == [
            "reserved", "running", "cancelled",
        ]
        snapshot = await state.build_operator_snapshot(
            session, now=NOW + timedelta(seconds=4)
        )
        assert snapshot["cancellation_counts"] == {
            "acknowledged": 1, "rejected": 1,
        }
        assert snapshot["unacknowledged_cancellations"] == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_provider_call_is_single_flight_and_recovers_expired_claim(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            running = await _running_job(session)
        async with session.begin():
            attempt = await cancellation.request_cancellation(
                session, job_id=running.id, fence_token=running.fence_token,
                provider_name="synthetic-provider",
                operation_reference=OPERATION_REFERENCE,
                reason_code="operator_stop", actor_id="operator-a", now=NOW,
            )
        async with session.begin():
            assert await state.repo.claim_cancellation_call_cas(
                session, cancellation_id=attempt.id,
                call_token="11111111-1111-4111-8111-111111111111",
                call_deadline=NOW + timedelta(seconds=5), now=NOW,
            )

    adapter = Canceller(cancellation.ProviderCancellationResult(True, "accepted"))
    async with factory() as session:
        async with session.begin():
            held = await cancellation.complete_provider_cancellation(
                session, cancellation_id=attempt.id,
                operation_reference=OPERATION_REFERENCE, canceller=adapter,
                timeout_seconds=5, now=NOW + timedelta(seconds=1),
            )
        assert held.outcome == "calling"
        assert adapter.calls == []
        async with session.begin():
            recovered = await cancellation.complete_provider_cancellation(
                session, cancellation_id=attempt.id,
                operation_reference=OPERATION_REFERENCE, canceller=adapter,
                timeout_seconds=5, now=NOW + timedelta(seconds=6),
            )
        assert recovered.outcome == "acknowledged"
        assert adapter.calls == [OPERATION_REFERENCE]
    await engine.dispose()


@pytest.mark.asyncio
async def test_retention_removes_cancellation_audit_with_terminal_job(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        async with session.begin():
            await state.control_state(session, now=NOW)
            job = await state.reserve(
                session,
                state.Reservation.build(
                    request_id="request-retention",
                    account_ref="synthetic:benchmark", issuer_id="MSFT",
                    capability="frozen_research", estimated_cost_usd=1,
                ),
                now=NOW, retention_days=1,
            )
            running = await state.claim(
                session, job.id, holder_id="worker-a", now=NOW,
            )
        async with session.begin():
            await cancellation.request_cancellation(
                session, job_id=running.id, fence_token=running.fence_token,
                provider_name="synthetic-provider",
                operation_reference=OPERATION_REFERENCE,
                reason_code="operator_stop", actor_id="operator-a", now=NOW,
            )
        async with session.begin():
            assert await state.purge_retained(
                session, now=NOW + timedelta(days=2)
            ) == (job.id,)
        rows = (await session.execute(select(BenchmarkShadowCancellation))).scalars().all()
        assert rows == []
    await engine.dispose()


def test_cancellation_boundary_has_no_live_provider_or_scheduler_imports():
    tree = ast.parse(open(cancellation.__file__, encoding="utf-8").read())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(
        token in module
        for module in imports
        for token in ("providers", "scheduler", "delivery", "notification")
    )
