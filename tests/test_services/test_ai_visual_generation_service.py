"""
Tests — AI Visual Generation Service, Phase 19 · Slice 9.

Covers: question classification, prompt construction (no user text), prompt
hashing, generation spec, post-generation validation, deterministic fallback,
orchestration + audit logging, prompt-text-never-stored, and AST safety.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "ai_visual_generation_service.py"

_USER = "u-ai-1"
_ENTITY = "NVDA"

_AI_TYPES = [
    "ecosystem_map", "supply_chain_map",
    "scenario_explainer", "thesis_explainer", "change_explainer",
]


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
# § classify_visual_question
# ===================================================================

class TestClassifyVisualQuestion:
    def test_supply_chain(self):
        from app.services.ai_visual_generation_service import classify_visual_question
        r = classify_visual_question("show me the supply chain for NVDA", entity_key=_ENTITY)
        assert r["visual_type"] == "supply_chain_map"
        assert r["recognized"] is True
        assert "similarity" in r["intelligence_sources"]

    def test_scenario(self):
        from app.services.ai_visual_generation_service import classify_visual_question
        r = classify_visual_question("what if rates rise?", entity_key=_ENTITY)
        assert r["visual_type"] == "scenario_explainer"

    def test_change(self):
        from app.services.ai_visual_generation_service import classify_visual_question
        r = classify_visual_question("what changed since my last visit?")
        assert r["visual_type"] == "change_explainer"

    def test_thesis(self):
        from app.services.ai_visual_generation_service import classify_visual_question
        r = classify_visual_question("explain the thesis", entity_key=_ENTITY)
        assert r["visual_type"] == "thesis_explainer"

    def test_ecosystem(self):
        from app.services.ai_visual_generation_service import classify_visual_question
        r = classify_visual_question("why does NVDA matter?", entity_key=_ENTITY)
        assert r["visual_type"] == "ecosystem_map"

    def test_unrecognized(self):
        from app.services.ai_visual_generation_service import classify_visual_question
        r = classify_visual_question("hello there")
        assert r["recognized"] is False
        assert r["visual_type"] == ""


# ===================================================================
# § build_visual_prompt — no user text
# ===================================================================

class TestBuildVisualPrompt:
    def test_prompt_structure(self):
        from app.services.ai_visual_generation_service import build_visual_prompt
        prompt = build_visual_prompt(
            visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"nodes": ["TSMC", "ASML"]},
            evidence_refs=["similarity_edge:1"],
        )
        assert prompt["prompt_type"] == "ecosystem_map"
        assert prompt["entity"] == _ENTITY
        assert prompt["data"] == {"nodes": ["TSMC", "ASML"]}
        assert prompt["constraints"]
        assert prompt["style"]

    def test_no_user_text_in_prompt(self):
        from app.services.ai_visual_generation_service import build_visual_prompt
        # The raw user question is never an input to the prompt builder.
        prompt = build_visual_prompt(
            visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"nodes": ["TSMC"]}, evidence_refs=["e:1"],
        )
        blob = str(prompt).lower()
        assert "question" not in prompt  # no question key
        assert "ignore all previous" not in blob  # no injected user text path


# ===================================================================
# § prompt hashing
# ===================================================================

class TestPromptHashing:
    def test_deterministic(self):
        from app.services.ai_visual_generation_service import build_visual_generation_spec
        kwargs = dict(
            visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"nodes": ["A", "B"]}, evidence_refs=["e:1"],
        )
        s1 = build_visual_generation_spec(**kwargs)
        s2 = build_visual_generation_spec(**kwargs)
        assert s1["prompt_hash"] == s2["prompt_hash"]
        assert len(s1["prompt_hash"]) == 64  # sha256 hex

    def test_different_data_different_hash(self):
        from app.services.ai_visual_generation_service import build_visual_generation_spec
        s1 = build_visual_generation_spec(
            visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"nodes": ["A"]}, evidence_refs=["e:1"],
        )
        s2 = build_visual_generation_spec(
            visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"nodes": ["B"]}, evidence_refs=["e:1"],
        )
        assert s1["prompt_hash"] != s2["prompt_hash"]


# ===================================================================
# § build_visual_generation_spec
# ===================================================================

class TestBuildGenerationSpec:
    @pytest.mark.parametrize("vt", _AI_TYPES)
    def test_all_categories_valid(self, vt):
        from app.services.ai_visual_generation_service import build_visual_generation_spec
        spec = build_visual_generation_spec(
            visual_type=vt, entity_key=_ENTITY,
            structured_data={"x": 1}, evidence_refs=["e:1"],
        )
        assert spec["rendering_tier"] == "ai_image"
        assert spec["explanation_valid"] is True
        assert spec["prompt_hash"]

    def test_unknown_type_blocked(self):
        from app.services.ai_visual_generation_service import build_visual_generation_spec
        spec = build_visual_generation_spec(
            visual_type="not_an_ai_visual", entity_key=_ENTITY,
            structured_data={}, evidence_refs=["e:1"],
        )
        assert spec["explanation_valid"] is False
        assert "not an AI visual type" in spec["blocked_reason"]
        assert spec["prompt_hash"] == ""

    def test_missing_evidence_blocked(self):
        from app.services.ai_visual_generation_service import build_visual_generation_spec
        spec = build_visual_generation_spec(
            visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"x": 1}, evidence_refs=[],
        )
        assert spec["explanation_valid"] is False

    def test_spec_has_no_prompt_text(self):
        from app.services.ai_visual_generation_service import build_visual_generation_spec
        spec = build_visual_generation_spec(
            visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"secret_marker": "XYZ"}, evidence_refs=["e:1"],
        )
        # Only the hash is carried, never the prompt itself.
        assert "prompt" not in spec
        assert "prompt_hash" in spec


# ===================================================================
# § validate_generated_visual
# ===================================================================

class TestValidateGeneratedVisual:
    def test_valid(self):
        from app.services.ai_visual_generation_service import validate_generated_visual
        ok, reason, banned = validate_generated_visual({
            "title": "NVDA Ecosystem Map",
            "explanation": {
                "what_am_i_looking_at": "Ecosystem map.",
                "why_does_it_matter": "It matters.",
                "supporting_evidence": ["e:1"],
            },
            "text_content": "TSMC ASML clean labels",
        })
        assert ok is True
        assert banned == []

    def test_advisory_language_in_text(self):
        from app.services.ai_visual_generation_service import validate_generated_visual
        ok, reason, banned = validate_generated_visual({
            "title": "NVDA Map",
            "explanation": {
                "what_am_i_looking_at": "Ecosystem map.",
                "why_does_it_matter": "It matters.",
                "supporting_evidence": ["e:1"],
            },
            "text_content": "you should buy this immediately",
        })
        assert ok is False
        assert "buy" in banned

    def test_missing_explanation(self):
        from app.services.ai_visual_generation_service import validate_generated_visual
        ok, reason, banned = validate_generated_visual({
            "title": "X",
            "explanation": {
                "what_am_i_looking_at": "",
                "why_does_it_matter": "It matters.",
                "supporting_evidence": ["e:1"],
            },
        })
        assert ok is False
        assert "what_am_i_looking_at" in reason


# ===================================================================
# § build_visual_fallback
# ===================================================================

class TestBuildFallback:
    def test_fallback_structure(self):
        from app.services.ai_visual_generation_service import build_visual_fallback
        fb = build_visual_fallback(
            visual_type="ecosystem_map", entity_key=_ENTITY,
            evidence_refs=["e:1"], reason="ai_disabled",
        )
        assert fb["is_fallback"] is True
        assert fb["rendering_tier"] == "json"
        assert fb["image_url"] is None
        assert fb["fallback_reason"] == "ai_disabled"
        assert fb["explanation_valid"] is True


# ===================================================================
# § generate_visual_request — orchestration
# ===================================================================

class TestGenerateVisualRequest:
    @pytest.mark.asyncio
    async def test_ai_disabled_returns_fallback(self, db):
        from app.services.ai_visual_generation_service import generate_visual_request
        result = await generate_visual_request(
            db, user_id=_USER, visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"x": 1}, evidence_refs=["e:1"], run_override=False,
        )
        assert result["is_fallback"] is True
        assert result["fallback_reason"] == "ai_disabled"

    @pytest.mark.asyncio
    async def test_session_none_returns_fallback(self):
        from app.services.ai_visual_generation_service import generate_visual_request
        result = await generate_visual_request(
            None, user_id=_USER, visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"x": 1}, evidence_refs=["e:1"], run_override=True,
        )
        assert result["is_fallback"] is True

    @pytest.mark.asyncio
    async def test_valid_request(self, db):
        from app.services.ai_visual_generation_service import generate_visual_request
        result = await generate_visual_request(
            db, user_id=_USER, visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"nodes": ["TSMC"]}, evidence_refs=["similarity_edge:1"],
            generation_model="test-model", run_override=True,
        )
        assert result["is_fallback"] is False
        assert result["rendering_tier"] == "ai_image"
        assert result["explanation_valid"] is True
        assert len(result["prompt_hash"]) == 64
        assert result["image_url"] is None

    @pytest.mark.asyncio
    async def test_valid_request_logs_row(self, db):
        from app.services.ai_visual_generation_service import generate_visual_request
        from app.db.repositories.visual_intelligence_repo import list_ai_visual_logs
        await generate_visual_request(
            db, user_id=_USER, visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"nodes": ["TSMC"]}, evidence_refs=["e:1"],
            generation_model="test-model", run_override=True,
        )
        await db.commit()
        logs = await list_ai_visual_logs(db, user_id=_USER)
        assert len(logs) == 1
        assert logs[0].validation_passed is True
        assert len(logs[0].prompt_hash) == 64

    @pytest.mark.asyncio
    async def test_invalid_type_logs_failure_and_falls_back(self, db):
        from app.services.ai_visual_generation_service import generate_visual_request
        from app.db.repositories.visual_intelligence_repo import list_ai_visual_logs
        result = await generate_visual_request(
            db, user_id=_USER, visual_type="bogus_type", entity_key=_ENTITY,
            structured_data={"x": 1}, evidence_refs=["e:1"], run_override=True,
        )
        await db.commit()
        assert result["is_fallback"] is True
        logs = await list_ai_visual_logs(db, user_id=_USER)
        assert len(logs) == 1
        assert logs[0].validation_passed is False


# ===================================================================
# § Prompt text never stored
# ===================================================================

class TestPromptTextNeverStored:
    @pytest.mark.asyncio
    async def test_log_stores_hash_not_text(self, db):
        from app.services.ai_visual_generation_service import generate_visual_request
        from app.db.repositories.visual_intelligence_repo import list_ai_visual_logs
        marker = "SENSITIVE_PROMPT_MARKER_12345"
        await generate_visual_request(
            db, user_id=_USER, visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"secret": marker}, evidence_refs=["e:1"],
            run_override=True,
        )
        await db.commit()
        logs = await list_ai_visual_logs(db, user_id=_USER)
        row = logs[0]
        # The marker must not appear anywhere in the stored row.
        for col in row.__table__.columns:
            val = getattr(row, col.name)
            assert marker not in str(val), f"prompt content leaked into {col.name}"
        # No prompt_text column exists on the model at all.
        assert "prompt_text" not in {c.name for c in row.__table__.columns}

    @pytest.mark.asyncio
    async def test_request_carries_no_prompt(self, db):
        from app.services.ai_visual_generation_service import generate_visual_request
        result = await generate_visual_request(
            db, user_id=_USER, visual_type="ecosystem_map", entity_key=_ENTITY,
            structured_data={"x": 1}, evidence_refs=["e:1"], run_override=True,
        )
        assert "prompt" not in result
        assert "prompt_hash" in result


# ===================================================================
# § AST safety
# ===================================================================

class TestASTSafety:
    def _source(self) -> str:
        return _SRC.read_text()

    def _tree(self) -> ast.Module:
        return ast.parse(self._source())

    def test_module_importable(self):
        import app.services.ai_visual_generation_service  # noqa: F401

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
        # Exempt the _BANNED_PHRASES safety vocabulary (Assign or AnnAssign).
        for node in ast.walk(tree):
            names = []
            value = None
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id]
                value = node.value
            if "_BANNED_PHRASES" in names and value is not None:
                for sub in ast.walk(value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        exempt_ids.add(id(sub))

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

    def test_no_direct_mutation_patterns(self):
        source = self._source()
        # Writes go through the repo's add_ai_visual_log; no direct ORM mutation.
        for pattern in [".update(", ".delete(", "session.add", "DELETE FROM", "UPDATE "]:
            assert pattern not in source, (
                f"Service must not directly mutate the ORM — found '{pattern}'"
            )

    def test_no_prompt_text_storage_in_log_call(self):
        source = self._source()
        # The audit logger must pass prompt_hash, never a prompt/prompt_text arg.
        assert "prompt_text=" not in source
        assert "prompt=" not in source
