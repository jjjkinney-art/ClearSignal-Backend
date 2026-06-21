"""
Tests — Similarity + Precedent Visual Service, Phase 19 · Slice 6.

Covers all 4 visual types: valid spec, blocked (no data), gate-off,
null-session, tier assignment, explainability enforcement, AST safety.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "similarity_visual_service.py"

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


async def _seed_edges(db, query_key=_ENTITY, count=3, floor_passed=True):
    from app.db.models import SimilarityEdge
    base = datetime.now(timezone.utc)
    for i in range(count):
        db.add(SimilarityEdge(
            id=str(uuid.uuid4()), target_type="company",
            query_key=query_key, candidate_key=f"PEER{i}",
            score=0.9 - i * 0.1, rank=i,
            contributions=[{"feature": "sector", "weight": 0.5},
                           {"feature": "growth", "weight": 0.3}],
            headline="similar", disanalogy="differs",
            floor_passed=floor_passed,
            built_at=base, expires_at=base + timedelta(days=1),
        ))
    await db.flush()


async def _seed_analogs(db, entity_ticker=_ENTITY, count=3):
    from app.db.models import HistoricalAnalog
    for i in range(count):
        db.add(HistoricalAnalog(
            id=str(uuid.uuid4()), label=f"Analog {entity_ticker} {i}",
            episode=f"episode {i}", entity_ticker=entity_ticker,
            sector="tech", mechanism="margin_compression",
            disanalogy="differs in scale",
            outcome_summary=f"outcome {i}",
            event_start=date(2020, 1, 1) + timedelta(days=i * 30),
        ))
    await db.flush()


# ===================================================================
# § Valid specs
# ===================================================================

class TestValidSpecs:
    @pytest.mark.asyncio
    async def test_similarity_network_valid(self, db):
        from app.services.similarity_visual_service import build_similarity_network_spec
        await _seed_edges(db)
        spec = await build_similarity_network_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "similarity_network"
        assert spec["rendering_tier"] == "svg"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["edges"]) == 3

    @pytest.mark.asyncio
    async def test_analog_cluster_valid(self, db):
        from app.services.similarity_visual_service import build_analog_cluster_spec
        await _seed_analogs(db)
        spec = await build_analog_cluster_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "analog_cluster"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["clusters"]) >= 1

    @pytest.mark.asyncio
    async def test_precedent_map_valid(self, db):
        from app.services.similarity_visual_service import build_precedent_map_spec
        await _seed_analogs(db)
        spec = await build_precedent_map_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "precedent_map"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["timeline"]) == 3

    @pytest.mark.asyncio
    async def test_relationship_graph_valid(self, db):
        from app.services.similarity_visual_service import build_relationship_graph_spec
        await _seed_edges(db)
        spec = await build_relationship_graph_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "relationship_graph"
        assert spec["explanation_valid"] is True
        assert spec["data"]["edges"][0]["dimensions"] == ["sector", "growth"]


# ===================================================================
# § Floor filtering
# ===================================================================

class TestFloorFiltering:
    @pytest.mark.asyncio
    async def test_below_floor_edges_excluded(self, db):
        from app.services.similarity_visual_service import build_similarity_network_spec
        await _seed_edges(db, floor_passed=False)
        spec = await build_similarity_network_spec(db, entity_key=_ENTITY, run_override=True)
        # No floor-passed edges → no evidence → blocked
        assert spec["explanation_valid"] is False


# ===================================================================
# § Blocked specs (no upstream data)
# ===================================================================

class TestBlockedSpecs:
    @pytest.mark.asyncio
    async def test_similarity_network_no_data_blocked(self, db):
        from app.services.similarity_visual_service import build_similarity_network_spec
        spec = await build_similarity_network_spec(db, entity_key="NODATA", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False
        assert "supporting_evidence" in spec["blocked_reason"]

    @pytest.mark.asyncio
    async def test_analog_cluster_no_data_blocked(self, db):
        from app.services.similarity_visual_service import build_analog_cluster_spec
        spec = await build_analog_cluster_spec(db, entity_key="NODATA", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False

    @pytest.mark.asyncio
    async def test_precedent_map_no_data_blocked(self, db):
        from app.services.similarity_visual_service import build_precedent_map_spec
        spec = await build_precedent_map_spec(db, entity_key="NODATA", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False


# ===================================================================
# § Gate off → None
# ===================================================================

class TestGateOff:
    @pytest.mark.asyncio
    async def test_similarity_network_gate_off(self, db):
        from app.services.similarity_visual_service import build_similarity_network_spec
        await _seed_edges(db)
        spec = await build_similarity_network_spec(db, entity_key=_ENTITY, run_override=False)
        assert spec is None

    @pytest.mark.asyncio
    async def test_precedent_map_gate_off(self, db):
        from app.services.similarity_visual_service import build_precedent_map_spec
        await _seed_analogs(db)
        spec = await build_precedent_map_spec(db, entity_key=_ENTITY, run_override=False)
        assert spec is None


# ===================================================================
# § Null session → None
# ===================================================================

class TestNullSession:
    @pytest.mark.asyncio
    async def test_all_functions_null_session(self):
        from app.services import similarity_visual_service as svc
        fns = [
            svc.build_similarity_network_spec,
            svc.build_analog_cluster_spec,
            svc.build_precedent_map_spec,
            svc.build_relationship_graph_spec,
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
        from app.services.similarity_visual_service import (
            build_similarity_network_spec, build_analog_cluster_spec,
            build_precedent_map_spec, build_relationship_graph_spec,
        )
        await _seed_edges(db)
        await _seed_analogs(db)
        for fn in (build_similarity_network_spec, build_analog_cluster_spec,
                   build_precedent_map_spec, build_relationship_graph_spec):
            spec = await fn(db, entity_key=_ENTITY, run_override=True)
            assert spec["rendering_tier"] == "svg", f"{fn.__name__} wrong tier"


# ===================================================================
# § Explainability enforced
# ===================================================================

class TestExplainabilityEnforced:
    @pytest.mark.asyncio
    async def test_valid_spec_has_all_three_fields(self, db):
        from app.services.similarity_visual_service import build_similarity_network_spec
        await _seed_edges(db)
        spec = await build_similarity_network_spec(db, entity_key=_ENTITY, run_override=True)
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
        import app.services.similarity_visual_service  # noqa: F401

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
