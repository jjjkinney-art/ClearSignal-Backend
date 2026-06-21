"""
Tests — Visual Spec Builder + Validation, Phase 19 · Slice 3.

Covers:
  1.  build_visual_spec: valid spec passes
  2.  build_visual_spec: spec includes all required fields
  3.  build_visual_spec: missing evidence → blocked
  4.  build_visual_spec: missing explanation (unknown type) → blocked
  5.  build_visual_spec: explicit what/why override templates
  6.  build_visual_spec: banned phrase in label → blocked
  7.  build_visual_spec: deterministic
  8.  select_rendering_tier: json types
  9.  select_rendering_tier: svg types
  10. select_rendering_tier: ai_image types
  11. select_rendering_tier: unknown defaults to json
  12. validate_visual_explainability: all fields present → ok
  13. validate_visual_explainability: missing what → fail
  14. validate_visual_explainability: missing why → fail
  15. validate_visual_explainability: missing evidence → fail
  16. validate_visual_labels: clean labels → ok
  17. validate_visual_labels: banned phrase → fail
  18. validate_visual_spec: valid → ok
  19. validate_visual_spec: invalid → fail with reason
  20. build_market_visual_spec: valid type
  21. build_market_visual_spec: wrong type → blocked
  22. build_forecast_visual_spec: valid type
  23. build_scenario_visual_spec: valid type
  24. build_similarity_visual_spec: valid type
  25. build_portfolio_visual_spec: valid type
  26. build_personal_visual_spec: valid type
  27. category builder: wrong category → blocked_reason set
  28. rendering_tier reflected in spec
  29. AST: module importable
  30. AST: no banned phrases (excluding safety vocabulary)
  31. AST: no upstream truth-table imports
  32. AST: no mutation patterns
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "visual_spec_builder_service.py"


# ===================================================================
# § build_visual_spec
# ===================================================================

class TestBuildVisualSpec:
    def test_valid_spec_passes(self):
        from app.services.visual_spec_builder_service import build_visual_spec
        spec = build_visual_spec(
            visual_type="forecast_distribution", entity_key="AAPL",
            data={"bull": 0.3}, evidence_refs=["forecast_vector:AAPL"],
            template_params={"as_of_date": "2026-06-21"},
        )
        assert spec["explanation_valid"] is True
        assert spec["blocked_reason"] == ""

    def test_spec_includes_required_fields(self):
        from app.services.visual_spec_builder_service import build_visual_spec
        spec = build_visual_spec(
            visual_type="price_chart", entity_key="MSFT",
            evidence_refs=["memory:MSFT"],
        )
        for field in ("visual_type", "rendering_tier", "entity_key", "title",
                       "explanation", "evidence_refs", "explanation_valid",
                       "blocked_reason"):
            assert field in spec, f"missing field: {field}"
        exp = spec["explanation"]
        assert "what_am_i_looking_at" in exp
        assert "why_does_it_matter" in exp
        assert "supporting_evidence" in exp

    def test_missing_evidence_blocked(self):
        from app.services.visual_spec_builder_service import build_visual_spec
        spec = build_visual_spec(
            visual_type="forecast_distribution", entity_key="AAPL",
            evidence_refs=[],
        )
        assert spec["explanation_valid"] is False
        assert "supporting_evidence" in spec["blocked_reason"]

    def test_missing_explanation_blocked(self):
        from app.services.visual_spec_builder_service import build_visual_spec
        spec = build_visual_spec(
            visual_type="totally_unknown_visual", entity_key="AAPL",
            evidence_refs=["some:ref"],
        )
        assert spec["explanation_valid"] is False
        assert "what_am_i_looking_at" in spec["blocked_reason"]

    def test_explicit_what_why_override(self):
        from app.services.visual_spec_builder_service import build_visual_spec
        spec = build_visual_spec(
            visual_type="unknown_type", entity_key="AAPL",
            evidence_refs=["ref:1"],
            what_am_i_looking_at="A custom visual.",
            why_does_it_matter="It is relevant.",
        )
        assert spec["explanation_valid"] is True
        assert spec["explanation"]["what_am_i_looking_at"] == "A custom visual."

    def test_banned_phrase_in_label_blocked(self):
        from app.services.visual_spec_builder_service import build_visual_spec
        spec = build_visual_spec(
            visual_type="price_chart", entity_key="AAPL",
            evidence_refs=["ref:1"],
            what_am_i_looking_at="You should buy this stock now.",
        )
        assert spec["explanation_valid"] is False
        assert "banned phrase" in spec["blocked_reason"]

    def test_deterministic(self):
        from app.services.visual_spec_builder_service import build_visual_spec
        kwargs = dict(
            visual_type="forecast_distribution", entity_key="AAPL",
            evidence_refs=["ref:1"], template_params={"as_of_date": "2026-06-21"},
        )
        s1 = build_visual_spec(**kwargs)
        s2 = build_visual_spec(**kwargs)
        assert s1 == s2


# ===================================================================
# § select_rendering_tier
# ===================================================================

class TestSelectRenderingTier:
    @pytest.mark.parametrize("vt", [
        "price_chart", "forecast_distribution", "exposure_map",
        "attention_timeline", "confidence_band",
    ])
    def test_json_types(self, vt):
        from app.services.visual_spec_builder_service import select_rendering_tier
        assert select_rendering_tier(vt) == "json"

    @pytest.mark.parametrize("vt", [
        "similarity_network", "scenario_tree", "transmission_path",
        "dependency_map", "thesis_evolution",
    ])
    def test_svg_types(self, vt):
        from app.services.visual_spec_builder_service import select_rendering_tier
        assert select_rendering_tier(vt) == "svg"

    @pytest.mark.parametrize("vt", [
        "ecosystem_map", "supply_chain_map", "ai_change_explanation",
        "ai_risk_map", "ai_commonality_diagram",
    ])
    def test_ai_types(self, vt):
        from app.services.visual_spec_builder_service import select_rendering_tier
        assert select_rendering_tier(vt) == "ai_image"

    def test_unknown_defaults_json(self):
        from app.services.visual_spec_builder_service import select_rendering_tier
        assert select_rendering_tier("nonexistent_visual") == "json"


# ===================================================================
# § validate_visual_explainability
# ===================================================================

class TestValidateExplainability:
    def test_all_fields_ok(self):
        from app.services.visual_spec_builder_service import validate_visual_explainability
        ok, reason = validate_visual_explainability({
            "what_am_i_looking_at": "A chart.",
            "why_does_it_matter": "It matters.",
            "supporting_evidence": ["ref:1"],
        })
        assert ok is True
        assert reason == ""

    def test_missing_what(self):
        from app.services.visual_spec_builder_service import validate_visual_explainability
        ok, reason = validate_visual_explainability({
            "what_am_i_looking_at": "",
            "why_does_it_matter": "It matters.",
            "supporting_evidence": ["ref:1"],
        })
        assert ok is False
        assert "what_am_i_looking_at" in reason

    def test_missing_why(self):
        from app.services.visual_spec_builder_service import validate_visual_explainability
        ok, reason = validate_visual_explainability({
            "what_am_i_looking_at": "A chart.",
            "why_does_it_matter": "",
            "supporting_evidence": ["ref:1"],
        })
        assert ok is False
        assert "why_does_it_matter" in reason

    def test_missing_evidence(self):
        from app.services.visual_spec_builder_service import validate_visual_explainability
        ok, reason = validate_visual_explainability({
            "what_am_i_looking_at": "A chart.",
            "why_does_it_matter": "It matters.",
            "supporting_evidence": [],
        })
        assert ok is False
        assert "supporting_evidence" in reason


# ===================================================================
# § validate_visual_labels
# ===================================================================

class TestValidateLabels:
    def test_clean_labels_ok(self):
        from app.services.visual_spec_builder_service import validate_visual_labels
        ok, reason = validate_visual_labels({
            "title": "AAPL Forecast Distribution",
            "what_am_i_looking_at": "Probability distribution for AAPL.",
        })
        assert ok is True

    def test_banned_phrase_fails(self):
        from app.services.visual_spec_builder_service import validate_visual_labels
        ok, reason = validate_visual_labels({
            "title": "Recommend buy AAPL",
        })
        assert ok is False
        assert "banned phrase" in reason


# ===================================================================
# § validate_visual_spec
# ===================================================================

class TestValidateVisualSpec:
    def test_valid_spec(self):
        from app.services.visual_spec_builder_service import validate_visual_spec
        ok, reason = validate_visual_spec({
            "title": "AAPL Chart",
            "explanation": {
                "what_am_i_looking_at": "A chart.",
                "why_does_it_matter": "It matters.",
                "supporting_evidence": ["ref:1"],
            },
        })
        assert ok is True

    def test_invalid_spec(self):
        from app.services.visual_spec_builder_service import validate_visual_spec
        ok, reason = validate_visual_spec({
            "title": "X",
            "explanation": {
                "what_am_i_looking_at": "",
                "why_does_it_matter": "It matters.",
                "supporting_evidence": ["ref:1"],
            },
        })
        assert ok is False
        assert reason != ""


# ===================================================================
# § Category builders
# ===================================================================

class TestCategoryBuilders:
    def test_market_valid(self):
        from app.services.visual_spec_builder_service import build_market_visual_spec
        spec = build_market_visual_spec(
            visual_type="price_chart", entity_key="AAPL",
            evidence_refs=["memory:AAPL"],
        )
        assert spec["explanation_valid"] is True
        assert spec["visual_type"] == "price_chart"

    def test_market_wrong_type_blocked(self):
        from app.services.visual_spec_builder_service import build_market_visual_spec
        spec = build_market_visual_spec(
            visual_type="forecast_distribution", entity_key="AAPL",
            evidence_refs=["ref:1"],
        )
        assert spec["explanation_valid"] is False
        assert "not valid for market visuals" in spec["blocked_reason"]

    def test_forecast_valid(self):
        from app.services.visual_spec_builder_service import build_forecast_visual_spec
        spec = build_forecast_visual_spec(
            visual_type="forecast_distribution", entity_key="AAPL",
            evidence_refs=["forecast:AAPL"],
            template_params={"as_of_date": "2026-06-21"},
        )
        assert spec["explanation_valid"] is True

    def test_scenario_valid(self):
        from app.services.visual_spec_builder_service import build_scenario_visual_spec
        spec = build_scenario_visual_spec(
            visual_type="transmission_path", entity_key="AAPL",
            evidence_refs=["scenario:AAPL"],
        )
        assert spec["explanation_valid"] is True
        assert spec["rendering_tier"] == "svg"

    def test_similarity_valid(self):
        from app.services.visual_spec_builder_service import build_similarity_visual_spec
        spec = build_similarity_visual_spec(
            visual_type="similarity_network", entity_key="AAPL",
            evidence_refs=["similarity:AAPL"],
            template_params={"edge_count": 12},
        )
        assert spec["explanation_valid"] is True

    def test_portfolio_valid(self):
        from app.services.visual_spec_builder_service import build_portfolio_visual_spec
        spec = build_portfolio_visual_spec(
            visual_type="exposure_map",
            evidence_refs=["portfolio:p1"],
        )
        assert spec["explanation_valid"] is True

    def test_personal_valid(self):
        from app.services.visual_spec_builder_service import build_personal_visual_spec
        spec = build_personal_visual_spec(
            visual_type="attention_timeline",
            evidence_refs=["experience:event"],
        )
        assert spec["explanation_valid"] is True

    def test_wrong_category_blocked_reason(self):
        from app.services.visual_spec_builder_service import build_portfolio_visual_spec
        spec = build_portfolio_visual_spec(
            visual_type="price_chart",
            evidence_refs=["ref:1"],
        )
        assert spec["explanation_valid"] is False
        assert "not valid for portfolio visuals" in spec["blocked_reason"]


# ===================================================================
# § Rendering tier in spec
# ===================================================================

class TestRenderingTierInSpec:
    def test_tier_reflected(self):
        from app.services.visual_spec_builder_service import build_visual_spec
        json_spec = build_visual_spec(
            visual_type="forecast_distribution", entity_key="AAPL",
            evidence_refs=["ref:1"],
        )
        svg_spec = build_visual_spec(
            visual_type="similarity_network", entity_key="AAPL",
            evidence_refs=["ref:1"], template_params={"edge_count": 5},
        )
        ai_spec = build_visual_spec(
            visual_type="ecosystem_map", entity_key="NVDA",
            evidence_refs=["ref:1"],
        )
        assert json_spec["rendering_tier"] == "json"
        assert svg_spec["rendering_tier"] == "svg"
        assert ai_spec["rendering_tier"] == "ai_image"


# ===================================================================
# § AST safety
# ===================================================================

class TestASTSafety:
    def _source(self) -> str:
        return _SRC.read_text()

    def _tree(self) -> ast.Module:
        return ast.parse(self._source())

    def test_module_importable(self):
        import app.services.visual_spec_builder_service  # noqa: F401

    def test_no_banned_phrases(self):
        tree = self._tree()

        # Exempt docstrings.
        exempt_ids: set = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)):
                    exempt_ids.add(id(body[0].value))

        # Exempt the _BANNED_PHRASES safety vocabulary constant — it is the
        # enforcement allowlist, not a violation.  Handles both Assign and
        # AnnAssign (the constant is declared `_BANNED_PHRASES: Tuple[...] = (...)`).
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
                f"Spec builder must be pure — found '{pattern}'"
            )
