"""
Tests — Portfolio + Exposure Visual Service, Phase 19 · Slice 7.

Covers all 4 visual types: valid spec, blocked (no data), gate-off,
null-session, tier assignment, explainability enforcement, AST safety,
and the no-dollar-amounts invariant (weight only).
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
_SRC  = _ROOT / "app" / "services" / "portfolio_visual_service.py"

_PORTFOLIO = "pf-1"


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


async def _seed_positions(db, portfolio_id=_PORTFOLIO, tickers=("AAPL", "MSFT", "GOOG")):
    from app.db.models import PortfolioPosition
    for i, t in enumerate(tickers):
        db.add(PortfolioPosition(
            id=str(uuid.uuid4()), portfolio_id=portfolio_id, ticker=t,
            membership_class="owned", weight=0.3 - i * 0.05,
            cost_basis=1000.0, shares=10.0, active=True,
        ))
    await db.flush()


async def _seed_edges(db, pairs):
    from app.db.models import SimilarityEdge
    base = datetime.now(timezone.utc)
    for q, c in pairs:
        db.add(SimilarityEdge(
            id=str(uuid.uuid4()), target_type="company",
            query_key=q, candidate_key=c, score=0.8, rank=0,
            contributions=[{"feature": "sector"}],
            headline="similar", disanalogy="differs", floor_passed=True,
            built_at=base, expires_at=base + timedelta(days=1),
        ))
    await db.flush()


async def _seed_scenarios(db, tickers):
    from app.db.models import ScenarioSnapshot
    base = datetime.now(timezone.utc)
    for t in tickers:
        db.add(ScenarioSnapshot(
            id=str(uuid.uuid4()), scenario_type="company", entity_type="company",
            entity_key=t, scenario_key=f"sk-{t}", condition="c",
            transmission_path=["a", "b"], scenario_impact="moderate_positive",
            plausibility_band="plausible", what_changed="x", why_it_matters="y",
            built_at=base, expires_at=base + timedelta(days=3),
        ))
    await db.flush()


# ===================================================================
# § Valid specs
# ===================================================================

class TestValidSpecs:
    @pytest.mark.asyncio
    async def test_exposure_map_valid(self, db):
        from app.services.portfolio_visual_service import build_exposure_map_spec
        await _seed_positions(db)
        spec = await build_exposure_map_spec(db, portfolio_id=_PORTFOLIO, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "exposure_map"
        assert spec["rendering_tier"] == "json"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["exposure"]) == 3

    @pytest.mark.asyncio
    async def test_concentration_map_valid(self, db):
        from app.services.portfolio_visual_service import build_concentration_map_spec
        await _seed_positions(db)
        spec = await build_concentration_map_spec(db, portfolio_id=_PORTFOLIO, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "concentration_map"
        assert spec["rendering_tier"] == "json"
        assert spec["explanation_valid"] is True
        assert "max_weight" in spec["data"]

    @pytest.mark.asyncio
    async def test_dependency_map_valid(self, db):
        from app.services.portfolio_visual_service import build_dependency_map_spec
        await _seed_positions(db)
        await _seed_edges(db, [("AAPL", "MSFT")])
        spec = await build_dependency_map_spec(db, portfolio_id=_PORTFOLIO, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "dependency_map"
        assert spec["rendering_tier"] == "svg"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["nodes"]) == 3
        assert len(spec["data"]["edges"]) == 1

    @pytest.mark.asyncio
    async def test_scenario_exposure_valid(self, db):
        from app.services.portfolio_visual_service import build_scenario_exposure_spec
        await _seed_positions(db)
        await _seed_scenarios(db, ["AAPL", "MSFT"])
        spec = await build_scenario_exposure_spec(db, portfolio_id=_PORTFOLIO, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "scenario_exposure"
        assert spec["rendering_tier"] == "svg"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["matrix"]) == 2


# ===================================================================
# § No dollar amounts (weight only)
# ===================================================================

class TestNoDollarAmounts:
    @pytest.mark.asyncio
    async def test_exposure_no_cost_basis_or_shares(self, db):
        from app.services.portfolio_visual_service import build_exposure_map_spec
        await _seed_positions(db)
        spec = await build_exposure_map_spec(db, portfolio_id=_PORTFOLIO, run_override=True)
        blob = str(spec["data"]).lower()
        assert "cost_basis" not in blob
        assert "shares" not in blob
        assert "1000.0" not in blob  # cost_basis value
        for item in spec["data"]["exposure"]:
            assert set(item.keys()) == {"ticker", "membership_class", "weight"}

    @pytest.mark.asyncio
    async def test_concentration_no_dollars(self, db):
        from app.services.portfolio_visual_service import build_concentration_map_spec
        await _seed_positions(db)
        spec = await build_concentration_map_spec(db, portfolio_id=_PORTFOLIO, run_override=True)
        for item in spec["data"]["weights"]:
            assert set(item.keys()) == {"ticker", "weight"}


# ===================================================================
# § Blocked specs (no upstream data)
# ===================================================================

class TestBlockedSpecs:
    @pytest.mark.asyncio
    async def test_exposure_no_data_blocked(self, db):
        from app.services.portfolio_visual_service import build_exposure_map_spec
        spec = await build_exposure_map_spec(db, portfolio_id="empty", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False
        assert "supporting_evidence" in spec["blocked_reason"]

    @pytest.mark.asyncio
    async def test_dependency_no_data_blocked(self, db):
        from app.services.portfolio_visual_service import build_dependency_map_spec
        spec = await build_dependency_map_spec(db, portfolio_id="empty", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False

    @pytest.mark.asyncio
    async def test_scenario_exposure_no_data_blocked(self, db):
        from app.services.portfolio_visual_service import build_scenario_exposure_spec
        spec = await build_scenario_exposure_spec(db, portfolio_id="empty", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False


# ===================================================================
# § Gate off → None
# ===================================================================

class TestGateOff:
    @pytest.mark.asyncio
    async def test_exposure_gate_off(self, db):
        from app.services.portfolio_visual_service import build_exposure_map_spec
        await _seed_positions(db)
        spec = await build_exposure_map_spec(db, portfolio_id=_PORTFOLIO, run_override=False)
        assert spec is None

    @pytest.mark.asyncio
    async def test_dependency_gate_off(self, db):
        from app.services.portfolio_visual_service import build_dependency_map_spec
        await _seed_positions(db)
        spec = await build_dependency_map_spec(db, portfolio_id=_PORTFOLIO, run_override=False)
        assert spec is None


# ===================================================================
# § Null session → None
# ===================================================================

class TestNullSession:
    @pytest.mark.asyncio
    async def test_all_functions_null_session(self):
        from app.services import portfolio_visual_service as svc
        fns = [
            svc.build_exposure_map_spec,
            svc.build_concentration_map_spec,
            svc.build_dependency_map_spec,
            svc.build_scenario_exposure_spec,
        ]
        for fn in fns:
            result = await fn(None, portfolio_id=_PORTFOLIO, run_override=True)
            assert result is None, f"{fn.__name__} not null-session safe"


# ===================================================================
# § Tier assignment
# ===================================================================

class TestTierAssignment:
    @pytest.mark.asyncio
    async def test_json_tier(self, db):
        from app.services.portfolio_visual_service import (
            build_exposure_map_spec, build_concentration_map_spec,
        )
        await _seed_positions(db)
        for fn in (build_exposure_map_spec, build_concentration_map_spec):
            spec = await fn(db, portfolio_id=_PORTFOLIO, run_override=True)
            assert spec["rendering_tier"] == "json"

    @pytest.mark.asyncio
    async def test_svg_tier(self, db):
        from app.services.portfolio_visual_service import (
            build_dependency_map_spec, build_scenario_exposure_spec,
        )
        await _seed_positions(db)
        for fn in (build_dependency_map_spec, build_scenario_exposure_spec):
            spec = await fn(db, portfolio_id=_PORTFOLIO, run_override=True)
            assert spec["rendering_tier"] == "svg"


# ===================================================================
# § Explainability enforced
# ===================================================================

class TestExplainabilityEnforced:
    @pytest.mark.asyncio
    async def test_valid_spec_has_all_three_fields(self, db):
        from app.services.portfolio_visual_service import build_exposure_map_spec
        await _seed_positions(db)
        spec = await build_exposure_map_spec(db, portfolio_id=_PORTFOLIO, run_override=True)
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
        import app.services.portfolio_visual_service  # noqa: F401

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

    def test_no_cost_basis_or_shares_read(self):
        # SP-19a: weight only. The service must never *access* cost_basis or
        # shares — neither as an attribute nor as an _attr() column read.
        # (The module docstring may mention them to document the prohibition.)
        tree = self._tree()
        for node in ast.walk(tree):
            # attribute access: p.cost_basis / p.shares
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("cost_basis", "shares"), (
                    f"Must not access .{node.attr} (dollar value)"
                )
            # _attr(p, "cost_basis", ...) / dict key "cost_basis"
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # exclude docstrings
                pass
        # Check string literals that are NOT docstrings.
        exempt_ids: set = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)):
                    exempt_ids.add(id(body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in exempt_ids:
                    continue
                assert "cost_basis" not in node.value, (
                    "Must not reference cost_basis outside the docstring"
                )
                assert "shares" not in node.value, (
                    "Must not reference shares outside the docstring"
                )

    def test_no_mutation_patterns(self):
        source = self._source()
        for pattern in [".update(", ".delete(", "session.add", "DELETE FROM", "UPDATE "]:
            assert pattern not in source, (
                f"Visual service must be read-only — found '{pattern}'"
            )
