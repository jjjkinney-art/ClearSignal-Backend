"""Owner-scoped deletion contract for saved thesis snapshots."""

import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest


def test_delete_owned_research_record_isolated_and_fail_closed():
    async def scenario():
        from fastapi import HTTPException
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import create_async_engine

        from app import api
        from app.db.connection import close_db, get_session_factory, init_db
        from app.db.models import Base, ThesisDelta, ThesisVersion
        from app.services.owned_research import delete_thesis, get_thesis

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        url = f"sqlite+aiosqlite:///{path}"
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            await engine.dispose()
            await init_db(url)
            factory = get_session_factory()

            async with factory() as session:
                owned = ThesisVersion(
                    ticker="AAPL", company_name="Apple", user_id="owner-a",
                    question="smoke marker", direct_answer="private",
                )
                foreign = ThesisVersion(
                    ticker="AAPL", company_name="Apple", user_id="owner-b",
                    question="foreign", direct_answer="preserve",
                )
                anonymous = ThesisVersion(
                    ticker="AAPL", company_name="Apple", user_id=None,
                    question="legacy", direct_answer="preserve",
                )
                session.add_all([owned, foreign, anonymous])
                await session.flush()
                session.add(ThesisDelta(
                    ticker="AAPL", from_version_id=owned.id,
                    to_version_id=foreign.id,
                ))
                await session.commit()
                owned_id, foreign_id, anonymous_id = owned.id, foreign.id, anonymous.id

            async with factory() as session:
                assert await delete_thesis(
                    session, user_id="owner-b", record_id=owned_id
                ) is False
                await session.commit()
                assert await get_thesis(
                    session, user_id="owner-a", record_id=owned_id
                ) is not None

            request_a = SimpleNamespace(state=SimpleNamespace(user_id="owner-a"))
            result = await api.delete_owned_research_record(owned_id, request_a)
            assert result == {"deleted": True, "record_id": owned_id}

            async with factory() as session:
                assert await get_thesis(
                    session, user_id="owner-a", record_id=owned_id
                ) is None
                assert await get_thesis(
                    session, user_id="owner-b", record_id=foreign_id
                ) is not None
                anonymous_row = await session.get(ThesisVersion, anonymous_id)
                assert anonymous_row is not None
                deltas = (await session.execute(select(ThesisDelta))).scalars().all()\n                assert deltas == []

            with pytest.raises(HTTPException) as missing:
                await api.delete_owned_research_record(owned_id, request_a)
            assert missing.value.status_code == 404

            request_b = SimpleNamespace(state=SimpleNamespace(user_id="owner-b"))
            with pytest.raises(HTTPException) as foreign:
                await api.delete_owned_research_record(anonymous_id, request_b)
            assert foreign.value.status_code == 404

            request_none = SimpleNamespace(state=SimpleNamespace(user_id=None))
            with pytest.raises(HTTPException) as unauthenticated:
                await api.delete_owned_research_record(foreign_id, request_none)
            assert unauthenticated.value.status_code == 401
        finally:
            await close_db()
            await engine.dispose()
            os.unlink(path)

    asyncio.run(scenario())
