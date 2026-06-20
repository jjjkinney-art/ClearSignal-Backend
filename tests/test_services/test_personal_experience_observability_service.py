"""
Tests — Personal Experience Observability, Phase 18 · Slice 10.

Covers:
  1.  build_personal_experience_snapshot: returns complete snapshot
  2.  build_personal_experience_snapshot: flags section present
  3.  build_personal_experience_snapshot: metrics section present
  4.  build_personal_experience_snapshot: safe_state section present
  5.  build_personal_experience_snapshot: safe_state.overall == True at defaults
  6.  build_personal_experience_snapshot: all safe_state sub-checks True
  7.  build_personal_experience_snapshot: schema_version == 1
  8.  build_personal_experience_snapshot: disclaimer present
  9.  build_personal_experience_snapshot: generated_at present
  10. build_personal_experience_snapshot: db_available True with session
  11. build_personal_experience_snapshot: db_available False without session
  12. build_personal_experience_snapshot: DB-down safe (session=None)
  13. build_personal_experience_snapshot: metrics count rows correctly
  14. build_personal_experience_snapshot: no advisory language in disclaimer
  15. Admin route: endpoint registered
  16. Validation script: runs and exits 0
  17. AST: no banned phrases in source
  18. AST: no upstream truth-table imports
  19. AST: module is importable
  20. AST: no mutation patterns
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "personal_experience_observability_service.py"

_USER = "u-obs-test"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
# § build_personal_experience_snapshot — with DB
# ===================================================================

class TestBuildSnapshot:
    @pytest.mark.asyncio
    async def test_returns_complete_snapshot(self, db):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(db)
        assert "flags" in snap
        assert "metrics" in snap
        assert "safe_state" in snap
        assert "schema_version" in snap
        assert "generated_at" in snap
        assert "disclaimer" in snap
        assert "db_available" in snap

    @pytest.mark.asyncio
    async def test_flags_section(self, db):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(db)
        flags = snap["flags"]
        expected_keys = {
            "experience_change_detection_enabled",
            "experience_attention_enabled",
            "experience_composer_enabled",
            "experience_memory_enabled",
            "experience_shadow",
            "experience_brief_enabled",
        }
        assert set(flags.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_metrics_section(self, db):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(db)
        metrics = snap["metrics"]
        for key in (
            "cursor_count", "event_count", "brief_count",
            "shadow_event_count", "calibration_event_count",
            "explainability_valid_count",
            "change_candidate_count", "attention_queue_count",
            "resume_candidate_count",
        ):
            assert key in metrics, f"missing metric: {key}"

    @pytest.mark.asyncio
    async def test_safe_state_section(self, db):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(db)
        safe = snap["safe_state"]
        for key in (
            "shadow_only", "no_live_delivery", "no_truth_mutation",
            "no_advisory_generation", "no_upstream_mutation",
            "explainability_gate_active", "overall",
        ):
            assert key in safe, f"missing safe_state key: {key}"

    @pytest.mark.asyncio
    async def test_safe_state_overall_true(self, db):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(db)
        assert snap["safe_state"]["overall"] is True

    @pytest.mark.asyncio
    async def test_all_safe_state_sub_checks_true(self, db):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(db)
        safe = snap["safe_state"]
        for key in (
            "shadow_only", "no_live_delivery", "no_truth_mutation",
            "no_advisory_generation", "no_upstream_mutation",
            "explainability_gate_active",
        ):
            assert safe[key] is True, f"{key} is not True"

    @pytest.mark.asyncio
    async def test_schema_version(self, db):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(db)
        assert snap["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_disclaimer_present(self, db):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(db)
        assert isinstance(snap["disclaimer"], str)
        assert len(snap["disclaimer"]) > 0

    @pytest.mark.asyncio
    async def test_generated_at_present(self, db):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(db)
        assert "generated_at" in snap
        assert isinstance(snap["generated_at"], str)

    @pytest.mark.asyncio
    async def test_db_available_true(self, db):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(db)
        assert snap["db_available"] is True

    @pytest.mark.asyncio
    async def test_metrics_count_rows(self, db):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        from app.db.repositories.personal_experience_repo import (
            upsert_experience_cursor,
            add_experience_event,
            add_brief_snapshot,
        )
        from datetime import date

        await upsert_experience_cursor(
            db, user_id=_USER, entity_type="ticker", entity_key="AAPL")
        await add_experience_event(
            db, user_id=_USER, surface="shadow", run_reason="shadow")
        await add_experience_event(
            db, user_id=_USER, surface="shadow", run_reason="calibration")
        await add_brief_snapshot(
            db, user_id=_USER, brief_date=date(2026, 6, 20))
        await db.flush()

        snap = await build_personal_experience_snapshot(db)
        assert snap["metrics"]["cursor_count"] >= 1
        assert snap["metrics"]["event_count"] >= 2
        assert snap["metrics"]["brief_count"] >= 1
        assert snap["metrics"]["shadow_event_count"] >= 1
        assert snap["metrics"]["calibration_event_count"] >= 1


# ===================================================================
# § DB-down safe (session=None)
# ===================================================================

class TestDBDown:
    @pytest.mark.asyncio
    async def test_db_down_returns_snapshot(self):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(None)
        assert snap["db_available"] is False
        assert snap["safe_state"]["overall"] is True
        assert snap["metrics"]["cursor_count"] == 0
        assert snap["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_db_down_disclaimer(self):
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snap = await build_personal_experience_snapshot(None)
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
        assert "/admin/personal-experience-status" in src

    def test_handler_calls_build_snapshot(self):
        api_path = _ROOT / "app" / "api.py"
        src = api_path.read_text()
        assert "build_personal_experience_snapshot" in src


# ===================================================================
# § Validation script
# ===================================================================

class TestValidationScript:
    def test_validation_script_exits_zero(self):
        script = str(_ROOT / "tests" / "validate_18_personal_experience_shadow.py")
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
        import app.services.personal_experience_observability_service  # noqa: F401

    def test_no_banned_phrases(self):
        tree = self._tree()

        docstring_node_ids: set = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    docstring_node_ids.add(id(body[0].value))

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
                if id(node) in docstring_node_ids:
                    continue
                val_lower = node.value.lower()
                for phrase in banned:
                    if phrase in val_lower:
                        violations.append(
                            f"Line ~{getattr(node, 'lineno', '?')}: "
                            f"banned phrase '{phrase}' in: {node.value[:80]!r}"
                        )
        assert not violations, "\n".join(violations)

    def test_no_upstream_truth_imports(self):
        tree = self._tree()
        banned_modules = [
            "forecast_repo", "decision_repo", "scenario_repo",
            "similarity_repo", "conviction", "order", "execution",
            "stance",
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
            occurrences = [
                i for i in range(len(source))
                if source[i:i + len(pattern)] == pattern
            ]
            assert not occurrences, (
                f"Found '{pattern}' in source — observability must be read-only"
            )
