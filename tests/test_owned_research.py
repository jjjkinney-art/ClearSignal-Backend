"""Owner isolation for saved analyses, including pre-auth anonymous records."""

import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import api
from app.services.owned_research import get_thesis, list_theses, save_thesis


def test_owned_research_isolated_and_authorized():
    async def scenario():
        from app.db.connection import close_db, get_session_factory, init_db
        from sqlalchemy.ext.asyncio import create_async_engine
        from app.db.models import Base, ThesisVersion

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
            result = SimpleNamespace(company="AAPL", answer={"investment_thesis": {
                "ticker": "AAPL", "direct_answer": "Owner A's research",
            }})
            async with factory() as session:
                assert await save_thesis(session, user_id="owner-a", question="A's question",
                                         company_name="Apple", session_id="first", result=result)
                session.add(ThesisVersion(ticker="AAPL", company_name="Apple", user_id=None,
                                          question="Old anonymous research", direct_answer="shared"))
                await session.commit()

            async with factory() as session:
                a = await list_theses(session, user_id="owner-a")
                assert len(a) == 1 and a[0]["direct_answer"] == "Owner A's research"
                assert await list_theses(session, user_id="owner-b") == []
                assert await get_thesis(session, user_id="owner-b", record_id=a[0]["id"]) is None
                assert await get_thesis(session, user_id="owner-a", record_id=a[0]["id"]) == a[0]
                with pytest.raises(ValueError):
                    await list_theses(session, user_id="")
                with pytest.raises(ValueError):
                    await save_thesis(session, user_id="", question="x", company_name="Apple",
                                      session_id="x", result=result)
            request_a = SimpleNamespace(state=SimpleNamespace(user_id="owner-a"))
            request_b = SimpleNamespace(state=SimpleNamespace(user_id="owner-b"))
            request_none = SimpleNamespace(state=SimpleNamespace(user_id=None))
            assert len(await api.get_owned_research_history(request=request_a, ticker=None, limit=30)) == 1
            assert await api.get_owned_research_history(request=request_b, ticker=None, limit=30) == []
            with pytest.raises(HTTPException) as err:
                await api.get_owned_research_record(a[0]["id"], request_b)
            assert err.value.status_code == 404
            with pytest.raises(HTTPException) as err:
                await api.get_owned_research_history(request=request_none, ticker=None, limit=30)
            assert err.value.status_code == 401
        finally:
            await close_db()
            await engine.dispose()
            os.unlink(path)

    asyncio.run(scenario())
