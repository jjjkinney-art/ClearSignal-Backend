"""
Tests — User Learning Explainability Gate, Phase 15 · Slice 4.

Covers:
  1.  service importable; no DB imports
  2.  build_preference_explanation produces required 4 fields for every dimension
  3.  build_why_we_believe_this: sufficient-evidence path per dimension
  4.  build_why_we_believe_this: insufficient-evidence fallback
  5.  build_evidence_summary: populated events
  6.  build_evidence_summary: empty events returns non-empty placeholder
  7.  build_signal_strength: strong / moderate / tentative thresholds
  8.  build_signal_strength: tentative when evidence_count < minimum
  9.  build_falsifier: returns non-empty list per dimension
  10. validate_preference_explanation: success path
  11. validate_preference_explanation: missing required field
  12. validate_preference_explanation: blank required field
  13. validate_preference_explanation: unsupported dimension
  14. validate_preference_explanation: invalid signal_strength
  15. validate_preference_explanation: banned phrase in why_we_believe_this
  16. validate_preference_explanation: banned phrase in evidence
  17. validate_preference_explanation: banned phrase in falsifier
  18. validate_preference_explanation: missing disclaimer
  19. disclaimer invariant: always present and non-blank
  20. disclaimer invariant: does not contain banned phrases
  21. deterministic output: same inputs → same output
  22. no writes, no DB session in any function
  23. AST: no DB imports anywhere in the module
  24. AST: no advice language in non-docstring string constants
  25. all seven supported dimensions produce valid explanations
"""

from __future__ import annotations

import ast
import inspect

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pref(
    dimension: str = "sector_interest",
    entity_key: str = "semiconductors",
    affinity: float = 0.7,
    confidence: float = 0.8,
    evidence_count: int = 10,
) -> dict:
    return {
        "dimension":      dimension,
        "entity_key":     entity_key,
        "affinity":       affinity,
        "confidence":     confidence,
        "evidence_count": evidence_count,
    }


def _events(n: int = 5, polarity: str = "positive") -> list:
    return [
        {
            "signal_type":    "analysis_open",
            "entity_key":     "NVDA",
            "polarity":       polarity,
            "source_surface": "feed",
        }
        for _ in range(n)
    ]


# ---------------------------------------------------------------------------
# 1. Service importable; no DB imports
# ---------------------------------------------------------------------------

class TestImport:
    def test_service_importable(self):
        import app.services.user_learning_explainability_service  # noqa: F401

    def test_all_public_functions_importable(self):
        from app.services.user_learning_explainability_service import (
            build_preference_explanation,
            build_why_we_believe_this,
            build_evidence_summary,
            build_signal_strength,
            build_falsifier,
            validate_preference_explanation,
        )
        for fn in (
            build_preference_explanation, build_why_we_believe_this,
            build_evidence_summary, build_signal_strength,
            build_falsifier, validate_preference_explanation,
        ):
            assert callable(fn)

    def test_no_db_import_in_service(self):
        import app.services.user_learning_explainability_service as mod
        src  = inspect.getsource(mod)
        tree = ast.parse(src)
        imported: list = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
        db_imports = [m for m in imported if "app.db" in m or "sqlalchemy" in m or "session" in m.lower()]
        assert not db_imports, f"Service must not import DB/SQLAlchemy: {db_imports}"


# ---------------------------------------------------------------------------
# 2. build_preference_explanation: required fields for every dimension
# ---------------------------------------------------------------------------

class TestBuildPreferenceExplanation:
    def test_returns_required_fields(self):
        from app.services.user_learning_explainability_service import (
            build_preference_explanation,
        )
        result = build_preference_explanation(_pref(), _events())
        for field in ("why_we_believe_this", "evidence", "signal_strength",
                      "falsifier", "dimension", "disclaimer"):
            assert field in result, f"Missing field: {field!r}"

    def test_why_we_believe_is_non_empty_list(self):
        from app.services.user_learning_explainability_service import build_preference_explanation
        result = build_preference_explanation(_pref(), _events())
        assert isinstance(result["why_we_believe_this"], list)
        assert len(result["why_we_believe_this"]) >= 1

    def test_evidence_is_non_empty_list(self):
        from app.services.user_learning_explainability_service import build_preference_explanation
        result = build_preference_explanation(_pref(), _events())
        assert isinstance(result["evidence"], list)
        assert len(result["evidence"]) >= 1

    def test_falsifier_is_non_empty_list(self):
        from app.services.user_learning_explainability_service import build_preference_explanation
        result = build_preference_explanation(_pref(), _events())
        assert isinstance(result["falsifier"], list)
        assert len(result["falsifier"]) >= 1

    def test_dimension_matches_input(self):
        from app.services.user_learning_explainability_service import build_preference_explanation
        result = build_preference_explanation(_pref(dimension="company_interest"), _events())
        assert result["dimension"] == "company_interest"

    def test_no_events_still_produces_valid_shape(self):
        from app.services.user_learning_explainability_service import build_preference_explanation
        result = build_preference_explanation(_pref())
        for field in ("why_we_believe_this", "evidence", "signal_strength",
                      "falsifier", "dimension", "disclaimer"):
            assert field in result


# ---------------------------------------------------------------------------
# 3. build_why_we_believe_this: per-dimension content
# ---------------------------------------------------------------------------

class TestBuildWhyWeBelieveThis:
    def _call(self, dimension, entity_key="NVDA", evidence_count=10, **kw):
        from app.services.user_learning_explainability_service import build_why_we_believe_this
        return build_why_we_believe_this(
            {"dimension": dimension, "entity_key": entity_key,
             "evidence_count": evidence_count, "affinity": 0.7, **kw},
            _events(evidence_count),
        )

    def test_sector_interest(self):
        sentences = self._call("sector_interest", entity_key="semiconductors")
        text = " ".join(sentences).lower()
        assert "semiconductor" in text or "sector" in text

    def test_company_interest(self):
        sentences = self._call("company_interest", entity_key="NVDA")
        text = " ".join(sentences).lower()
        assert "nvda" in text.lower() or "analys" in text

    def test_theme_interest(self):
        sentences = self._call("theme_interest", entity_key="ai_infrastructure")
        text = " ".join(sentences).lower()
        assert "theme" in text or "ai_infrastructure" in text.lower()

    def test_preferred_horizon(self):
        sentences = self._call("preferred_horizon", entity_key="long")
        text = " ".join(sentences).lower()
        assert "horizon" in text or "long" in text

    def test_preferred_signal_type(self):
        sentences = self._call("preferred_signal_type", entity_key="scenario")
        text = " ".join(sentences).lower()
        assert "signal" in text or "scenario" in text

    def test_ignored_signal_type(self):
        sentences = self._call("ignored_signal_type", entity_key="forecast",
                                evidence_count=7, affinity=-0.6)
        text = " ".join(sentences).lower()
        assert "dismiss" in text or "mute" in text or "forecast" in text

    def test_portfolio_sensitivity(self):
        sentences = self._call("portfolio_sensitivity", entity_key="AAPL")
        text = " ".join(sentences).lower()
        assert "portfolio" in text or "aapl" in text.lower()

    def test_returns_list_of_strings(self):
        sentences = self._call("sector_interest")
        assert isinstance(sentences, list)
        assert all(isinstance(s, str) for s in sentences)


# ---------------------------------------------------------------------------
# 4. build_why_we_believe_this: insufficient-evidence fallback
# ---------------------------------------------------------------------------

class TestInsufficientEvidence:
    def test_below_minimum_returns_insufficient_note(self):
        from app.services.user_learning_explainability_service import build_why_we_believe_this
        result = build_why_we_believe_this(
            {"dimension": "sector_interest", "entity_key": "semis",
             "affinity": 0.5, "evidence_count": 1},
        )
        text = " ".join(result).lower()
        assert "insufficient" in text or "minimum" in text

    def test_exactly_at_minimum_does_not_trigger_fallback(self):
        from app.services.user_learning_explainability_service import (
            build_why_we_believe_this, _MIN_EVIDENCE,
        )
        min_ev = _MIN_EVIDENCE["company_interest"]
        result = build_why_we_believe_this(
            {"dimension": "company_interest", "entity_key": "NVDA",
             "affinity": 0.7, "evidence_count": min_ev},
        )
        text = " ".join(result).lower()
        assert "insufficient" not in text

    def test_ignored_signal_type_has_higher_minimum(self):
        from app.services.user_learning_explainability_service import _MIN_EVIDENCE
        assert _MIN_EVIDENCE["ignored_signal_type"] > _MIN_EVIDENCE["preferred_signal_type"]


# ---------------------------------------------------------------------------
# 5. build_evidence_summary: populated events
# ---------------------------------------------------------------------------

class TestBuildEvidenceSummary:
    def test_returns_list_of_strings(self):
        from app.services.user_learning_explainability_service import build_evidence_summary
        result = build_evidence_summary(_events(3))
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)
        assert len(result) >= 3

    def test_includes_signal_type(self):
        from app.services.user_learning_explainability_service import build_evidence_summary
        events = [{"signal_type": "analysis_open", "entity_key": "NVDA",
                   "polarity": "positive", "source_surface": "feed"}]
        result = build_evidence_summary(events)
        combined = " ".join(result)
        assert "analysis_open" in combined

    def test_includes_entity_key_when_present(self):
        from app.services.user_learning_explainability_service import build_evidence_summary
        events = [{"signal_type": "watchlist_add", "entity_key": "AAPL",
                   "polarity": "positive", "source_surface": "watchlist"}]
        result = build_evidence_summary(events)
        assert "AAPL" in " ".join(result)

    def test_max_items_respected(self):
        from app.services.user_learning_explainability_service import build_evidence_summary
        events = _events(20)
        result = build_evidence_summary(events, max_items=5)
        # At most 5 event lines + 1 overflow note = 6 total; must be <= 6
        assert len(result) <= 6

    def test_overflow_note_added(self):
        from app.services.user_learning_explainability_service import build_evidence_summary
        events = _events(20)
        result = build_evidence_summary(events, max_items=5)
        combined = " ".join(result)
        assert "additional" in combined.lower() or "…" in combined


# ---------------------------------------------------------------------------
# 6. build_evidence_summary: empty events
# ---------------------------------------------------------------------------

class TestBuildEvidenceSummaryEmpty:
    def test_empty_events_returns_placeholder(self):
        from app.services.user_learning_explainability_service import build_evidence_summary
        result = build_evidence_summary([])
        assert result  # non-empty list
        assert isinstance(result[0], str)

    def test_none_events_returns_placeholder(self):
        from app.services.user_learning_explainability_service import build_evidence_summary
        result = build_evidence_summary(None)
        assert result
        assert isinstance(result[0], str)


# ---------------------------------------------------------------------------
# 7 & 8. build_signal_strength
# ---------------------------------------------------------------------------

class TestBuildSignalStrength:
    def test_high_confidence_is_strong(self):
        from app.services.user_learning_explainability_service import build_signal_strength
        assert build_signal_strength(0.9, 20, "sector_interest") == "strong"

    def test_medium_confidence_is_moderate(self):
        from app.services.user_learning_explainability_service import build_signal_strength
        assert build_signal_strength(0.55, 10, "sector_interest") == "moderate"

    def test_low_confidence_is_tentative(self):
        from app.services.user_learning_explainability_service import build_signal_strength
        assert build_signal_strength(0.2, 10, "sector_interest") == "tentative"

    def test_below_minimum_evidence_is_tentative(self):
        from app.services.user_learning_explainability_service import (
            build_signal_strength, _MIN_EVIDENCE,
        )
        dim = "sector_interest"
        # Even with high confidence, below min evidence → tentative
        assert build_signal_strength(0.95, _MIN_EVIDENCE[dim] - 1, dim) == "tentative"

    def test_at_strong_threshold_is_strong(self):
        from app.services.user_learning_explainability_service import (
            build_signal_strength, _STRONG_CONFIDENCE_THRESHOLD,
        )
        assert build_signal_strength(_STRONG_CONFIDENCE_THRESHOLD, 20) == "strong"

    def test_at_moderate_threshold_is_moderate(self):
        from app.services.user_learning_explainability_service import (
            build_signal_strength, _MODERATE_CONFIDENCE_THRESHOLD,
        )
        assert build_signal_strength(_MODERATE_CONFIDENCE_THRESHOLD, 20) == "moderate"

    def test_zero_confidence_is_tentative(self):
        from app.services.user_learning_explainability_service import build_signal_strength
        assert build_signal_strength(0.0, 20) == "tentative"


# ---------------------------------------------------------------------------
# 9. build_falsifier: non-empty per dimension
# ---------------------------------------------------------------------------

class TestBuildFalsifier:
    def _call(self, dimension, entity_key="test_entity", affinity=0.7):
        from app.services.user_learning_explainability_service import build_falsifier
        return build_falsifier({"dimension": dimension, "entity_key": entity_key,
                                 "affinity": affinity})

    def test_sector_interest_falsifier(self):
        result = self._call("sector_interest", "semiconductors")
        assert result
        assert any("day" in s.lower() or "session" in s.lower() for s in result)

    def test_company_interest_falsifier(self):
        result = self._call("company_interest", "NVDA")
        assert result
        assert any("day" in s.lower() or "analysis" in s.lower() for s in result)

    def test_theme_interest_falsifier(self):
        result = self._call("theme_interest", "ai_infra")
        assert result

    def test_preferred_horizon_falsifier(self):
        result = self._call("preferred_horizon", "long")
        assert len(result) >= 1

    def test_preferred_signal_type_falsifier(self):
        result = self._call("preferred_signal_type", "scenario")
        assert result

    def test_ignored_signal_type_falsifier_mentions_positive_interaction(self):
        result = self._call("ignored_signal_type", "forecast", affinity=-0.7)
        text = " ".join(result).lower()
        assert "positive" in text or "interaction" in text

    def test_portfolio_sensitivity_falsifier(self):
        result = self._call("portfolio_sensitivity", "AAPL")
        assert result

    def test_unknown_dimension_still_returns_falsifier(self):
        result = self._call("unknown_dimension_xyz")
        assert result

    def test_all_items_are_strings(self):
        for dim in (
            "sector_interest", "company_interest", "theme_interest",
            "preferred_horizon", "preferred_signal_type",
            "ignored_signal_type", "portfolio_sensitivity",
        ):
            result = self._call(dim)
            assert all(isinstance(s, str) for s in result), f"Non-string in {dim} falsifier"


# ---------------------------------------------------------------------------
# 10–14. validate_preference_explanation: success and failure paths
# ---------------------------------------------------------------------------

class TestValidatePreferenceExplanation:
    def _valid(self, dimension="sector_interest"):
        from app.services.user_learning_explainability_service import build_preference_explanation
        return build_preference_explanation(_pref(dimension=dimension), _events())

    def test_valid_explanation_passes(self):
        from app.services.user_learning_explainability_service import (
            validate_preference_explanation,
        )
        ok, reason = validate_preference_explanation(self._valid())
        assert ok is True
        assert reason is None

    def test_missing_field_fails(self):
        from app.services.user_learning_explainability_service import (
            validate_preference_explanation,
        )
        explanation = self._valid()
        del explanation["why_we_believe_this"]
        ok, reason = validate_preference_explanation(explanation)
        assert ok is False
        assert "why_we_believe_this" in reason

    def test_empty_list_field_fails(self):
        from app.services.user_learning_explainability_service import (
            validate_preference_explanation,
        )
        explanation = self._valid()
        explanation["evidence"] = []
        ok, reason = validate_preference_explanation(explanation)
        assert ok is False
        assert "evidence" in reason

    def test_blank_string_field_fails(self):
        from app.services.user_learning_explainability_service import (
            validate_preference_explanation,
        )
        explanation = self._valid()
        explanation["signal_strength"] = "   "
        ok, reason = validate_preference_explanation(explanation)
        assert ok is False

    def test_unsupported_dimension_fails(self):
        from app.services.user_learning_explainability_service import (
            validate_preference_explanation,
        )
        explanation = self._valid()
        explanation["dimension"] = "profit_motive"
        ok, reason = validate_preference_explanation(explanation)
        assert ok is False
        assert "dimension" in reason.lower() or "profit_motive" in reason

    def test_invalid_signal_strength_fails(self):
        from app.services.user_learning_explainability_service import (
            validate_preference_explanation,
        )
        explanation = self._valid()
        explanation["signal_strength"] = "definitive"
        ok, reason = validate_preference_explanation(explanation)
        assert ok is False
        assert "signal_strength" in reason


# ---------------------------------------------------------------------------
# 15–17. validate: banned phrase detection
# ---------------------------------------------------------------------------

class TestBannedPhraseDetection:
    def _valid(self):
        from app.services.user_learning_explainability_service import build_preference_explanation
        return build_preference_explanation(_pref(), _events())

    def test_banned_phrase_in_why_fails(self):
        from app.services.user_learning_explainability_service import (
            validate_preference_explanation,
        )
        explanation = self._valid()
        explanation["why_we_believe_this"] = [
            "You should consider whether to buy this name."
        ]
        ok, reason = validate_preference_explanation(explanation)
        assert ok is False
        assert "buy" in reason.lower() or "banned" in reason.lower()

    def test_banned_phrase_in_evidence_fails(self):
        from app.services.user_learning_explainability_service import (
            validate_preference_explanation,
        )
        explanation = self._valid()
        explanation["evidence"] = ["Event implies a sell signal was observed."]
        ok, reason = validate_preference_explanation(explanation)
        assert ok is False

    def test_banned_phrase_in_falsifier_fails(self):
        from app.services.user_learning_explainability_service import (
            validate_preference_explanation,
        )
        explanation = self._valid()
        explanation["falsifier"] = [
            "If the user decides to hold the position this would overturn it."
        ]
        ok, reason = validate_preference_explanation(explanation)
        assert ok is False

    def test_each_banned_phrase_detected(self):
        from app.services.user_learning_explainability_service import (
            validate_preference_explanation, _BANNED_PHRASES,
        )
        base = self._valid()
        for phrase in _BANNED_PHRASES:
            explanation = dict(base)
            explanation["why_we_believe_this"] = [
                f"This text contains the phrase: {phrase} here in a long enough string."
            ]
            ok, _ = validate_preference_explanation(explanation)
            assert ok is False, f"Banned phrase {phrase!r} not caught by validator"


# ---------------------------------------------------------------------------
# 18. validate: missing disclaimer fails
# ---------------------------------------------------------------------------

class TestMissingDisclaimer:
    def test_missing_disclaimer_fails(self):
        from app.services.user_learning_explainability_service import (
            build_preference_explanation, validate_preference_explanation,
        )
        explanation = build_preference_explanation(_pref(), _events())
        del explanation["disclaimer"]
        ok, reason = validate_preference_explanation(explanation)
        assert ok is False
        assert "disclaimer" in reason

    def test_blank_disclaimer_fails(self):
        from app.services.user_learning_explainability_service import (
            build_preference_explanation, validate_preference_explanation,
        )
        explanation = build_preference_explanation(_pref(), _events())
        explanation["disclaimer"] = ""
        ok, reason = validate_preference_explanation(explanation)
        assert ok is False


# ---------------------------------------------------------------------------
# 19 & 20. Disclaimer invariant
# ---------------------------------------------------------------------------

class TestDisclaimerInvariant:
    def test_disclaimer_always_present(self):
        from app.services.user_learning_explainability_service import build_preference_explanation
        for dim in (
            "sector_interest", "company_interest", "theme_interest",
            "preferred_horizon", "preferred_signal_type",
            "ignored_signal_type", "portfolio_sensitivity",
        ):
            result = build_preference_explanation(_pref(dimension=dim), _events())
            assert "disclaimer" in result
            assert result["disclaimer"].strip()

    def test_disclaimer_does_not_contain_banned_phrases(self):
        from app.services.user_learning_explainability_service import (
            _DISCLAIMER, _BANNED_PHRASES,
        )
        lower = _DISCLAIMER.lower()
        for phrase in _BANNED_PHRASES:
            assert phrase not in lower, (
                f"Banned phrase {phrase!r} found in _DISCLAIMER constant"
            )

    def test_disclaimer_is_consistent(self):
        from app.services.user_learning_explainability_service import (
            build_preference_explanation, _DISCLAIMER,
        )
        for dim in ("sector_interest", "company_interest"):
            result = build_preference_explanation(_pref(dimension=dim), _events())
            assert result["disclaimer"] == _DISCLAIMER


# ---------------------------------------------------------------------------
# 21. Deterministic output
# ---------------------------------------------------------------------------

class TestDeterministicOutput:
    def test_same_inputs_same_output(self):
        from app.services.user_learning_explainability_service import build_preference_explanation
        pref = _pref(dimension="company_interest", entity_key="NVDA",
                     affinity=0.8, confidence=0.75, evidence_count=12)
        evts = _events(5)
        r1 = build_preference_explanation(pref, evts)
        r2 = build_preference_explanation(pref, evts)
        assert r1 == r2

    def test_same_falsifier_for_same_inputs(self):
        from app.services.user_learning_explainability_service import build_falsifier
        pref = {"dimension": "sector_interest", "entity_key": "semis", "affinity": 0.7}
        assert build_falsifier(pref) == build_falsifier(pref)


# ---------------------------------------------------------------------------
# 22. No writes, no DB session
# ---------------------------------------------------------------------------

class TestNoWrites:
    def test_build_explanation_accepts_no_session(self):
        from app.services.user_learning_explainability_service import build_preference_explanation
        # Must work without any session argument — pure computation
        result = build_preference_explanation(_pref(), _events())
        assert result is not None

    def test_validate_explanation_accepts_no_session(self):
        from app.services.user_learning_explainability_service import (
            build_preference_explanation, validate_preference_explanation,
        )
        explanation = build_preference_explanation(_pref(), _events())
        ok, _ = validate_preference_explanation(explanation)
        assert ok is True

    def test_no_session_parameter_in_any_function(self):
        import app.services.user_learning_explainability_service as mod
        src  = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = [a.arg for a in node.args.args]
                assert "session" not in params, (
                    f"Function {node.name!r} has a 'session' parameter — "
                    "explainability service must be DB-free"
                )


# ---------------------------------------------------------------------------
# 23. AST: no DB imports
# ---------------------------------------------------------------------------

class TestASTNoDBImports:
    def test_no_sqlalchemy_import(self):
        import app.services.user_learning_explainability_service as mod
        src  = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "sqlalchemy" not in alias.name.lower(), \
                        "SQLAlchemy import found in explainability service"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "sqlalchemy" not in node.module.lower(), \
                    "SQLAlchemy import found in explainability service"
                assert "app.db" not in node.module, \
                    f"DB import found in explainability service: {node.module}"

    def test_no_repo_imports(self):
        import app.services.user_learning_explainability_service as mod
        src  = inspect.getsource(mod)
        assert "_repo" not in src, "Repository import found in explainability service"


# ---------------------------------------------------------------------------
# 24. AST: no advice language in non-docstring string constants
# ---------------------------------------------------------------------------

class TestASTNoAdviceLanguage:
    _ADVICE_PHRASES = [
        "buy", "sell", "hold", "overweight", "underweight",
        "recommend", "target price", "position size",
    ]

    def test_no_advice_in_non_docstring_constants(self):
        import app.services.user_learning_explainability_service as mod
        src  = inspect.getsource(mod)
        tree = ast.parse(src)

        docstring_nodes: set = set()

        def _mark(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Module)):
                body = node.body
                if body and isinstance(body[0], ast.Expr):
                    val = body[0].value
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        docstring_nodes.add(id(val))
            for child in ast.iter_child_nodes(node):
                _mark(child)

        _mark(tree)

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstring_nodes:
                    continue
                val = node.value.lower()
                # The _BANNED_PHRASES list itself is a sentinel — skip short items
                if len(val) > 60:
                    for phrase in self._ADVICE_PHRASES:
                        if phrase in val:
                            violations.append((phrase, node.value[:80]))
        assert not violations, (
            f"Advice phrases in non-docstring string constants: {violations}"
        )


# ---------------------------------------------------------------------------
# 25. All seven supported dimensions produce valid explanations
# ---------------------------------------------------------------------------

class TestAllDimensionsValid:
    @pytest.mark.parametrize("dimension", [
        "sector_interest",
        "company_interest",
        "theme_interest",
        "preferred_horizon",
        "preferred_signal_type",
        "ignored_signal_type",
        "portfolio_sensitivity",
    ])
    def test_valid_explanation_for_dimension(self, dimension):
        from app.services.user_learning_explainability_service import (
            build_preference_explanation, validate_preference_explanation,
        )
        # Use enough evidence to clear the minimum threshold for each dimension
        explanation = build_preference_explanation(
            _pref(dimension=dimension, evidence_count=20, confidence=0.8),
            _events(20),
        )
        ok, reason = validate_preference_explanation(explanation)
        assert ok is True, (
            f"Valid explanation for {dimension!r} did not pass validation: {reason}"
        )
