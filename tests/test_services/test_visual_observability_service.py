"""
Tests — Visual Intelligence Observability, Phase 19 · Slice 12.

Covers: snapshot generation, DB-down, safe_state, admin route,
validation script, AST safety.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "visual_observability_service.py"


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


# ===================================================================
# § build_visual_snapshot — with DB
# ===================================================================

class TestBuildSnapshot:
    @pytest.mark.asyncio
    async def test_returns_complete_snapshot(self, db):
        from app.services.visual_observability_service import build_visual_snapshot
        snap = await build_visual_snapshot(db)
        for key in ("flags", "metrics", "safe_state", "schema_version",
                     "generated_at", "disclaimer", "db_available"):
            assert key in snap, f"missing key: {key}"

    @pytest.mark.asyncio
    async def test_flags_section(self, db):
        from app.services.visual_observability_service import build_visual_snapshot
        snap = await build_visual_snapshot(db)
        expected = {
            "visual_json_enabled", "visual_svg_enabled", "visual_ai_enabled",
            "visual_cache_enabled", "visual_shadow", "visual_calibration_enabled",
        }
        assert set(snap["flags"].keys()) == expected

    @pytest.mark.asyncio
    async def test_metrics_section(self, db):
        from app.services.visual_observability_service import build_visual_snapshot
        snap = await build_visual_snapshot(db)
        for key in ("cache_count", "event_count", "ai_log_count",
                     "shadow_event_count", "calibration_event_count"):
            assert key in snap["metrics"], f"missing metric: {key}"

    @pytest.mark.asyncio
    async def test_safe_state_all_true(self, db):
        from app.services.visual_observability_service import build_visual_snapshot
        snap = await build_visual_snapshot(db)
        safe = snap["safe_state"]
        for key in ("shadow_only", "no_live_visual_delivery", "no_truth_mutation",
                     "no_advisory_generation", "no_upstream_mutation",
                     "explainability_gate_active", "overall"):
            assert safe[key] is True, f"{key} is not True"

    @pytest.mark.asyncio
    async def test_schema_version(self, db):
        from app.services.visual_observability_service import build_visual_snapshot
        snap = await build_visual_snapshot(db)
        assert snap["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_disclaimer_present(self, db):
        from app.services.visual_observability_service import build_visual_snapshot
        snap = await build_visual_snapshot(db)
        assert isinstance(snap["disclaimer"], str)
        assert len(snap["disclaimer"]) > 0

    @pytest.mark.asyncio
    async def test_db_available_true(self, db):
        from app.services.visual_observability_service import build_visual_snapshot
        snap = await build_visual_snapshot(db)
        assert snap["db_available"] is True

    @pytest.mark.asyncio
    async def test_metrics_count_rows(self, db):
        from app.services.visual_observability_service import build_visual_snapshot
        from app.db.repositories.visual_intelligence_repo import (
            upsert_visual_spec, add_visual_event, add_ai_visual_log,
        )
        await upsert_visual_spec(
            db, user_id="u1", visual_type="t", entity_key="AAPL", data_hash="h")
        await add_visual_event(db, user_id="u1", run_reason="shadow")
        await add_visual_event(db, user_id="u1", run_reason="calibration")
        await add_ai_visual_log(db, user_id="u1")
        await db.flush()
        snap = await build_visual_snapshot(db)
        assert snap["metrics"]["cache_count"] >= 1
        assert snap["metrics"]["event_count"] >= 2
        assert snap["metrics"]["ai_log_count"] >= 1
        assert snap["metrics"]["shadow_event_count"] >= 1
        assert snap["metrics"]["calibration_event_count"] >= 1


# ===================================================================
# § DB-down safe
# ===================================================================

class TestDBDown:
    @pytest.mark.asyncio
    async def test_db_down_returns_snapshot(self):
        from app.services.visual_observability_service import build_visual_snapshot
        snap = await build_visual_snapshot(None)
        assert snap["db_available"] is False
        assert snap["safe_state"]["overall"] is True
        assert snap["metrics"]["cache_count"] == 0
        assert snap["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_db_down_disclaimer(self):
        from app.services.visual_observability_service import build_visual_snapshot
        snap = await build_visual_snapshot(None)
        disclaimer = snap["disclaimer"].lower()
        for phrase in ["buy", "sell", "recommend", "target price"]:
            assert phrase not in disclaimer


# ===================================================================
# § Admin route
# ===================================================================

class TestAdminRoute:
    def test_route_registered(self):
        api_path = _ROOT / "app" / "api.py"
        src = api_path.read_text()
        assert "/admin/visual-intelligence-status" in src

    def test_handler_calls_build_snapshot(self):
        api_path = _ROOT / "app" / "api.py"
        src = api_path.read_text()
        assert "build_visual_snapshot" in src


# ===================================================================
# § Validation script
# ===================================================================

class TestValidationScript:
    def test_validation_script_exits_zero(self):
        script = str(_ROOT / "tests" / "validate_19_visual_intelligence_shadow.py")
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=30,
            cwd=str(_ROOT),
        )
        assert result.returncode == 0, (
            f"Validation script failed (exit {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )


# ===================================================================
# § AST safety
# ===================================================================

class TestASTSafety:
    def _source(self) -> str:
        return _SRC.read_text()

    def _tree(self) -> ast.Module:
        return ast.parse(self._source())

    def test_module_importable(self):
        import app.services.visual_observability_service  # noqa: F401

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
            "similarity_repo", "conviction", "order",
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
        for pattern in [".update(", ".delete(", "DELETE FROM", "UPDATE "]:
            assert pattern not in source, (
                f"Observability must be read-only — found '{pattern}'"
            )
