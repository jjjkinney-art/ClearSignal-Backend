"""
Tests — Personal Experience Visual Service, Phase 19 · Slice 8.

Covers all 4 visual types: valid spec, blocked (no data), gate-off,
null-session, tier assignment, explainability enforcement, AST safety.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "personal_visual_service.py"

_USER = "u-pv-1"
_ENTITY = "AAPL"


@pytest.fixture()
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture()
async def db(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncSessionLocal() as session:
        yield session


async def _seed_events(db, user_id=_USER, entity_key=_ENTITY, count=3):
    from app.db.models import PersonalExperienceEvent
    base = datetime.now(timezone.utc)
    for i in range(count):
        db.add(PersonalExperienceEvent(
            id=str(uuid.uuid4()), user_id=user_id, surface="home",
            entity_type="ticker", entity_key=entity_key,
            attention_priority=0.8 - i * 0.1, personal_relevance=0.5,
            memory_relevance=0.3, explanation_valid=True,
            surfaced_at=base - timedelta(days=i),
        ))
    await db.flush()


async def _seed_cursors(db, user_id=_USER, tickers=("AAPL", "MSFT", "GOOG")):
    from app.db.models import PersonalExperienceCursor
    base = datetime.now(timezone.utc)
    for i, t in enumerate(tickers):
        db.add(PersonalExperienceCursor(
            id=str(uuid.uuid4()), user_id=user_id, entity_type="ticker",
            entity_key=t, last_seen_at=base - timedelta(days=i),
            last_state_hash=f"hash{i}", view_count=5 - i,
        ))
    await db.flush()


# ===================================================================
# § Valid specs
# ===================================================================

class TestValidSpecs:
    @pytest.mark.asyncio
    async def test_attention_timeline_valid(self, db):
        from app.services.personal_visual_service import build_attention_timeline_spec
        await _seed_events(db)
        spec = await build_attention_timeline_spec(db, user_id=_USER, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "attention_timeline"
        assert spec["rendering_tier"] == "json"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["timeline"]) == 3

    @pytest.mark.asyncio
    async def test_change_timeline_valid(self, db):
        from app.services.personal_visual_service import build_change_timeline_spec
        await _seed_cursors(db)
        spec = await build_change_timeline_spec(db, user_id=_USER, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "change_timeline"
        assert spec["rendering_tier"] == "json"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["timeline"]) == 3

    @pytest.mark.asyncio
    async def test_resume_timeline_valid(self, db):
        from app.services.personal_visual_service import build_resume_timeline_spec
        await _seed_cursors(db)
        spec = await build_resume_timeline_spec(db, user_id=_USER, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "resume_timeline"
        assert spec["explanation_valid"] is True
        # Ranked by view_count desc: AAPL(5), MSFT(4), GOOG(3)
        assert spec["data"]["resume_items"][0]["entity_key"] == "AAPL"

    @pytest.mark.asyncio
    async def test_thesis_evolution_valid(self, db):
        from app.services.personal_visual_service import build_thesis_evolution_spec
        await _seed_events(db)
        spec = await build_thesis_evolution_spec(
            db, user_id=_USER, entity_key=_ENTITY, run_override=True,
        )
        assert spec is not None
        assert spec["visual_type"] == "thesis_evolution"
        assert spec["rendering_tier"] == "svg"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["series"]) == 3
        # entity_key appears in the templated explanation
        assert _ENTITY in spec["explanation"]["what_am_i_looking_at"]


# ===================================================================
# § Tenant isolation
# ===================================================================

class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_attention_isolated(self, db):
        from app.services.personal_visual_service import build_attention_timeline_spec
        await _seed_events(db, user_id="user-a")
        await _seed_events(db, user_id="user-b", count=1)
        spec = await build_attention_timeline_spec(db, user_id="user-a", run_override=True)
        assert len(spec["data"]["timeline"]) == 3


# ===================================================================
# § Blocked specs (no upstream data)
# ===================================================================

class TestBlockedSpecs:
    @pytest.mark.asyncio
    async def test_attention_no_data_blocked(self, db):
        from app.services.personal_visual_service import build_attention_timeline_spec
        spec = await build_attention_timeline_spec(db, user_id="nobody", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False
        assert "supporting_evidence" in spec["blocked_reason"]

    @pytest.mark.asyncio
    async def test_change_no_data_blocked(self, db):
        from app.services.personal_visual_service import build_change_timeline_spec
        spec = await build_change_timeline_spec(db, user_id="nobody", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False

    @pytest.mark.asyncio
    async def test_thesis_evolution_no_data_blocked(self, db):
        from app.services.personal_visual_service import build_thesis_evolution_spec
        spec = await build_thesis_evolution_spec(
            db, user_id="nobody", entity_key="NONE", run_override=True,
        )
        assert spec is not None
        assert spec["explanation_valid"] is False


# ===================================================================
# § Gate off → None
# ===================================================================

class TestGateOff:
    @pytest.mark.asyncio
    async def test_attention_gate_off(self, db):
        from app.services.personal_visual_service import build_attention_timeline_spec
        await _seed_events(db)
        spec = await build_attention_timeline_spec(db, user_id=_USER, run_override=False)
        assert spec is None

    @pytest.mark.asyncio
    async def test_thesis_evolution_gate_off(self, db):
        from app.services.personal_visual_service import build_thesis_evolution_spec
        await _seed_events(db)
        spec = await build_thesis_evolution_spec(
            db, user_id=_USER, entity_key=_ENTITY, run_override=False,
        )
        assert spec is None


# ===================================================================
# § Null session → None
# ===================================================================

class TestNullSession:
    @pytest.mark.asyncio
    async def test_user_level_null_session(self):
        from app.services import personal_visual_service as svc
        for fn in (svc.build_attention_timeline_spec,
                   svc.build_change_timeline_spec,
                   svc.build_resume_timeline_spec):
            result = await fn(None, user_id=_USER, run_override=True)
            assert result is None, f"{fn.__name__} not null-session safe"

    @pytest.mark.asyncio
    async def test_thesis_evolution_null_session(self):
        from app.services.personal_visual_service import build_thesis_evolution_spec
        result = await build_thesis_evolution_spec(
            None, user_id=_USER, entity_key=_ENTITY, run_override=True,
        )
        assert result is None


# ===================================================================
# § Tier assignment
# ===================================================================

class TestTierAssignment:
    @pytest.mark.asyncio
    async def test_json_tier(self, db):
        from app.services.personal_visual_service import (
            build_attention_timeline_spec, build_change_timeline_spec,
            build_resume_timeline_spec,
        )
        await _seed_events(db)
        await _seed_cursors(db)
        for fn in (build_attention_timeline_spec, build_change_timeline_spec,
                   build_resume_timeline_spec):
            spec = await fn(db, user_id=_USER, run_override=True)
            assert spec["rendering_tier"] == "json", f"{fn.__name__} wrong tier"

    @pytest.mark.asyncio
    async def test_svg_tier(self, db):
        from app.services.personal_visual_service import build_thesis_evolution_spec
        await _seed_events(db)
        spec = await build_thesis_evolution_spec(
            db, user_id=_USER, entity_key=_ENTITY, run_override=True,
        )
        assert spec["rendering_tier"] == "svg"


# ===================================================================
# § Explainability enforced
# ===================================================================

class TestExplainabilityEnforced:
    @pytest.mark.asyncio
    async def test_valid_spec_has_all_three_fields(self, db):
        from app.services.personal_visual_service import build_attention_timeline_spec
        await _seed_events(db)
        spec = await build_attention_timeline_spec(db, user_id=_USER, run_override=True)
        exp = spec["explanation"]
        assert exp["what_am_i_looking_at"]
        assert exp["why_does_it_matter"]
        assert exp["supporting_evidence"]


# ===================================================================
# § AST safety
# ===================================================================

class TestASTSafety:
    def _source(self) -> str:
        return _SRC.read_text()

    def _tree(self) -> ast.Module:
        return ast.parse(self._source())

    def test_module_importable(self):
        import app.services.personal_visual_service  # noqa: F401

    def test_no_banned_phrases(self):
        tree = self._tree()
        exempt_ids: set = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)):
                    exempt_ids.add(id(body[0].value))

        banned = [
            "buy", "sell",
            "overweight", "underweight", "recommend",
            "target price", "position size",
            "take a position", "enter a trade", "exit a trade",
            "place an order", "execute",
            "short", "long position",
            "go long", "go short",
            "open a position", "close a position",
        ]
        violations: list = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in exempt_ids:
                    continue
                low = node.value.lower()
                for phrase in banned:
                    if phrase in low:
                        violations.append(
                            f"Line ~{getattr(node, 'lineno', '?')}: "
                            f"'{phrase}' in: {node.value[:80]!r}"
                        )
        assert not violations, "\n".join(violations)

    def test_no_upstream_truth_imports(self):
        tree = self._tree()
        banned_modules = [
            "forecast_repo", "decision_repo", "scenario_repo",
            "similarity_repo", "user_learning_repo", "portfolio_repo",
            "personal_experience_repo", "conviction", "order",
            "execution", "stance",
        ]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                for banned in banned_modules:
                    assert banned not in mod, (
                        f"Banned import from {mod} (contains '{banned}')"
                    )

    def test_no_mutation_patterns(self):
        source = self._source()
        for pattern in [".update(", ".delete(", "session.add", "DELETE FROM", "UPDATE "]:
            assert pattern not in source, (
                f"Visual service must be read-only — found '{pattern}'"
            )
