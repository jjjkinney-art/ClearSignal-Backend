"""
Tests — Scenario + Transmission Visual Service, Phase 19 · Slice 5.

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
_SRC  = _ROOT / "app" / "services" / "scenario_visual_service.py"

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


async def _seed_scenario(
    db, entity_key=_ENTITY, count=1, *,
    transmission_path=None, affected_entities=None, scenario_id=None,
):
    from app.db.models import ScenarioSnapshot
    base = datetime.now(timezone.utc)
    ids = []
    for i in range(count):
        sid = scenario_id if (scenario_id and count == 1) else str(uuid.uuid4())
        ids.append(sid)
        db.add(ScenarioSnapshot(
            id=sid, scenario_type="company", entity_type="company",
            entity_key=entity_key, scenario_key=f"sk-{i}",
            condition=f"condition {i}",
            transmission_path=transmission_path or ["trigger", "intermediate", "impact"],
            scenario_impact="moderate_positive", plausibility_band="plausible",
            what_changed=f"what changed {i}",
            why_it_matters="it matters",
            affected_entities=affected_entities or ["MSFT", "GOOG"],
            built_at=base - timedelta(days=i),
            expires_at=base + timedelta(days=3),
        ))
    await db.flush()
    return ids


async def _seed_scenario_evidence(db, scenario_id, count=2):
    from app.db.models import ScenarioEvidence
    for i in range(count):
        db.add(ScenarioEvidence(
            id=str(uuid.uuid4()), scenario_id=scenario_id,
            source_phase="forecast", source_ref=f"ref-{i}",
        ))
    await db.flush()


# ===================================================================
# § Valid specs
# ===================================================================

class TestValidSpecs:
    @pytest.mark.asyncio
    async def test_what_changed_map_valid(self, db):
        from app.services.scenario_visual_service import build_what_changed_map_spec
        await _seed_scenario(db, count=2)
        spec = await build_what_changed_map_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "what_changed_map"
        assert spec["rendering_tier"] == "svg"
        assert spec["explanation_valid"] is True
        assert spec["data"]["before"] is not None

    @pytest.mark.asyncio
    async def test_transmission_path_valid(self, db):
        from app.services.scenario_visual_service import build_transmission_path_spec
        ids = await _seed_scenario(db)
        await _seed_scenario_evidence(db, ids[0])
        spec = await build_transmission_path_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "transmission_path"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["nodes"]) == 3
        assert len(spec["data"]["edges"]) == 2

    @pytest.mark.asyncio
    async def test_scenario_tree_valid(self, db):
        from app.services.scenario_visual_service import build_scenario_tree_spec
        await _seed_scenario(db, count=3)
        spec = await build_scenario_tree_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "scenario_tree"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["branches"]) == 3

    @pytest.mark.asyncio
    async def test_impact_map_valid(self, db):
        from app.services.scenario_visual_service import build_impact_map_spec
        await _seed_scenario(db, affected_entities=["MSFT", "GOOG", "AMZN"])
        spec = await build_impact_map_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "impact_map"
        assert spec["explanation_valid"] is True
        # root node + 3 affected
        assert len(spec["data"]["nodes"]) == 4
        assert len(spec["data"]["edges"]) == 3


# ===================================================================
# § Transmission path by scenario_id
# ===================================================================

class TestScenarioIdLookup:
    @pytest.mark.asyncio
    async def test_transmission_path_by_scenario_id(self, db):
        from app.services.scenario_visual_service import build_transmission_path_spec
        sid = "fixed-scenario-id"
        await _seed_scenario(db, scenario_id=sid)
        spec = await build_transmission_path_spec(
            db, entity_key=_ENTITY, scenario_id=sid, run_override=True,
        )
        assert spec is not None
        assert spec["explanation_valid"] is True


# ===================================================================
# § Blocked specs (no upstream data)
# ===================================================================

class TestBlockedSpecs:
    @pytest.mark.asyncio
    async def test_what_changed_no_data_blocked(self, db):
        from app.services.scenario_visual_service import build_what_changed_map_spec
        spec = await build_what_changed_map_spec(db, entity_key="NODATA", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False
        assert "supporting_evidence" in spec["blocked_reason"]

    @pytest.mark.asyncio
    async def test_transmission_no_data_blocked(self, db):
        from app.services.scenario_visual_service import build_transmission_path_spec
        spec = await build_transmission_path_spec(db, entity_key="NODATA", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False

    @pytest.mark.asyncio
    async def test_impact_map_no_data_blocked(self, db):
        from app.services.scenario_visual_service import build_impact_map_spec
        spec = await build_impact_map_spec(db, entity_key="NODATA", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False


# ===================================================================
# § Gate off → None
# ===================================================================

class TestGateOff:
    @pytest.mark.asyncio
    async def test_what_changed_gate_off(self, db):
        from app.services.scenario_visual_service import build_what_changed_map_spec
        await _seed_scenario(db)
        spec = await build_what_changed_map_spec(db, entity_key=_ENTITY, run_override=False)
        assert spec is None

    @pytest.mark.asyncio
    async def test_scenario_tree_gate_off(self, db):
        from app.services.scenario_visual_service import build_scenario_tree_spec
        await _seed_scenario(db)
        spec = await build_scenario_tree_spec(db, entity_key=_ENTITY, run_override=False)
        assert spec is None


# ===================================================================
# § Null session → None
# ===================================================================

class TestNullSession:
    @pytest.mark.asyncio
    async def test_all_functions_null_session(self):
        from app.services import scenario_visual_service as svc
        fns = [
            svc.build_what_changed_map_spec,
            svc.build_transmission_path_spec,
            svc.build_scenario_tree_spec,
            svc.build_impact_map_spec,
        ]
        for fn in fns:
            result = await fn(None, entity_key=_ENTITY, run_override=True)
            assert result is None, f"{fn.__name__} not null-session safe"


# ===================================================================
# § Tier assignment
# ===================================================================

class TestTierAssignment:
    @pytest.mark.asyncio
    async def test_all_svg_tier(self, db):
        from app.services.scenario_visual_service import (
            build_what_changed_map_spec, build_transmission_path_spec,
            build_scenario_tree_spec, build_impact_map_spec,
        )
        await _seed_scenario(db, count=2)
        for fn in (build_what_changed_map_spec, build_transmission_path_spec,
                   build_scenario_tree_spec, build_impact_map_spec):
            spec = await fn(db, entity_key=_ENTITY, run_override=True)
            assert spec["rendering_tier"] == "svg", f"{fn.__name__} wrong tier"


# ===================================================================
# § Explainability enforced
# ===================================================================

class TestExplainabilityEnforced:
    @pytest.mark.asyncio
    async def test_valid_spec_has_all_three_fields(self, db):
        from app.services.scenario_visual_service import build_scenario_tree_spec
        await _seed_scenario(db, count=2)
        spec = await build_scenario_tree_spec(db, entity_key=_ENTITY, run_override=True)
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
        import app.services.scenario_visual_service  # noqa: F401

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
            "similarity_repo", "user_learning_repo",
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
