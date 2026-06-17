"""
Tests — Decision Explainability Service, Phase 13 · Slice 4.

All tests operate on synthetic dicts — no DB, no session.

Covers:
  1.  build_decision_explanation returns all required keys
  2.  all 7 candidate types produce non-empty why_important
  3.  all 7 candidate types produce non-empty why_now
  4.  all 7 candidate types produce non-empty evidence
  5.  all 7 candidate types produce non-empty deprioritizers
  6.  disclaimer always present and non-empty
  7.  disclaimer is fixed text (does not vary per candidate)
  8.  decision_score is echoed through to the envelope
  9.  candidate_type is echoed through to the envelope
  10. sparse candidates (all empty input dicts) — no exception, valid output
  11. validate_decision_explanation returns True for a well-formed explanation
  12. validate_decision_explanation rejects missing why_important
  13. validate_decision_explanation rejects missing why_now
  14. validate_decision_explanation rejects missing evidence
  15. validate_decision_explanation rejects missing deprioritizers
  16. validate_decision_explanation rejects missing disclaimer
  17. validate_decision_explanation rejects unsupported candidate_type
  18. validate_decision_explanation rejects banned phrase "buy"
  19. validate_decision_explanation rejects banned phrase "sell"
  20. validate_decision_explanation rejects banned phrase "recommend"
  21. validate_decision_explanation rejects banned phrase "target price"
  22. validate_decision_explanation rejects banned phrase in disclaimer
  23. banned phrase check is case-insensitive
  24. deterministic output — same inputs → same sentences
  25. build_why_important contains ticker
  26. build_why_now reflects urgency label
  27. build_evidence_summary references source_type and source_id
  28. build_deprioritizers reflects confidence_multiplier
  29. confidence multiplier < 0.60 → caveat in deprioritizers
  30. uncertainty discount < 0.80 → caveat in deprioritizers
  31. portfolio with weight > 0 mentions weight in why_important
  32. portfolio exposure multiplier != 1.0 noted in deprioritizers
  33. forecast neutral probability > 0.25 noted in deprioritizers
  34. risk old match (> 30d) noted in deprioritizers
  35. similarity inverse_score > 0.30 noted in deprioritizers
  36. AST: no DB or session imports
  37. AST: no advice language in module string constants
  38. AST: no session.add / update / delete calls
  39. AST: no conviction/recommendation/order/execution module imports
  40. validate_decision_explanation returns (bool, Optional[str]) tuple
"""

from __future__ import annotations

import ast
import pathlib
from typing import List

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT    = pathlib.Path(__file__).parent.parent.parent
_SVC     = _ROOT / "app" / "services" / "decision_explainability_service.py"

# ---------------------------------------------------------------------------
# Synthetic builders
# ---------------------------------------------------------------------------

def _ranking(*, decision_score=0.55, attention_score=0.60, urgency_score=0.50,
              impact_score=0.55, confidence_multiplier=0.70,
              uncertainty_discount=0.85, exposure_multiplier=1.00) -> dict:
    return {
        "decision_score":        decision_score,
        "attention_score":       attention_score,
        "urgency_score":         urgency_score,
        "impact_score":          impact_score,
        "confidence_multiplier": confidence_multiplier,
        "uncertainty_discount":  uncertainty_discount,
        "exposure_multiplier":   exposure_multiplier,
    }


def _candidate(ctype: str, ticker: str = "NVDA") -> dict:
    """Minimal but complete candidate dict for *ctype*."""
    base = {
        "candidate_type": ctype,
        "entity_type": "company",
        "entity_id": "ent-001",
        "ticker": ticker,
        "source_type": f"{ctype}_source",
        "source_id": "src-001",
        "headline": f"{ticker} signal",
        "summary": "summary text",
        "evidence_refs": ["ref-1"],
        "source_versions": {"schema": "v1"},
        "user_id": None,
    }

    inputs: dict = {}
    if ctype == "forecast_candidate":
        inputs = {
            "urgency_inputs": {"horizon_days": 45, "horizon": "near_term"},
            "impact_inputs": {"p_positive": 0.65, "p_negative": 0.25, "p_neutral": 0.10,
                              "confidence_band_low": 0.55, "confidence_band_high": 0.75,
                              "forecast_type": "thesis_strengthening"},
            "attention_inputs": {"forecast_type": "thesis_strengthening",
                                 "entity_type": "company", "direction": "strengthening"},
            "confidence_inputs": {"confidence_band_low": 0.55, "confidence_band_high": 0.75,
                                  "evidence_count": 3},
            "uncertainty_inputs": {"band_width": 0.20, "p_neutral": 0.10},
        }
    elif ctype == "risk_candidate":
        inputs = {
            "urgency_inputs": {"sequence_stage": 3, "matched_days_ago": 10},
            "impact_inputs": {"relevance_at_match": 0.70, "sequence_stage": 3},
            "attention_inputs": {"ticker": ticker, "analog_id": "analog-001", "stage": 3},
            "confidence_inputs": {"relevance_at_match": 0.70,
                                  "has_analog_label": True, "has_stage_evidence": True},
            "uncertainty_inputs": {"matched_days_ago": 10, "sequence_stage": 3},
        }
    elif ctype == "catalyst_candidate":
        inputs = {
            "urgency_inputs": {"direction": "bull_trigger", "expected_window": "Q3 2026",
                               "specificity": 0.80, "created_days_ago": 5},
            "impact_inputs": {"specificity": 0.80, "conviction_weight": 0.60,
                              "direction": "bull_trigger"},
            "attention_inputs": {"ticker": ticker, "direction": "bull_trigger",
                                 "expected_window": "Q3 2026"},
            "confidence_inputs": {"specificity": 0.80, "has_statement": True,
                                  "has_expected_window": True},
            "uncertainty_inputs": {"inverse_specificity": 0.20, "created_days_ago": 5},
        }
    elif ctype == "watchlist_candidate":
        inputs = {
            "urgency_inputs": {"added_days_ago": 3},
            "impact_inputs": {"ticker": ticker},
            "attention_inputs": {"ticker": ticker, "company_name": "Corp", "added_days_ago": 3},
            "confidence_inputs": {"has_company_name": True, "active": True},
            "uncertainty_inputs": {"added_days_ago": 3},
        }
    elif ctype == "portfolio_exposure_candidate":
        inputs = {
            "urgency_inputs": {"membership_class": "owned", "added_days_ago": 5},
            "impact_inputs": {"weight": 0.12, "shares": 100, "cost_basis": 500.0,
                              "membership_class": "owned", "portfolio_name": "Main"},
            "attention_inputs": {"ticker": ticker, "membership_class": "owned",
                                 "portfolio_id": "port-001"},
            "confidence_inputs": {"has_weight": True, "has_cost_basis": True,
                                  "is_default_portfolio": False},
            "uncertainty_inputs": {"weight": 0.12, "added_days_ago": 5},
        }
    elif ctype == "delivery_transition_candidate":
        inputs = {
            "urgency_inputs": {"status": "pending", "attempts": 2, "created_days_ago": 0,
                               "canonical_severity": "high", "severity_rank": 3},
            "impact_inputs": {"canonical_severity": "high", "severity_rank": 3, "channel": "in_app"},
            "attention_inputs": {"target_key": ticker, "channel": "in_app", "status": "pending"},
            "confidence_inputs": {"has_severity": True, "attempts": 2, "has_artifact_ref": True},
            "uncertainty_inputs": {"attempts": 2, "created_days_ago": 0},
        }
    elif ctype == "similarity_candidate":
        inputs = {
            "urgency_inputs": {"score": 0.82, "rank": 2, "built_days_ago": 1},
            "impact_inputs": {"score": 0.82, "rank": 2, "query_key": ticker,
                              "candidate_key": "AMD", "target_type": "company"},
            "attention_inputs": {"query_key": ticker, "candidate_key": "AMD",
                                 "floor_passed": True, "score": 0.82},
            "confidence_inputs": {"score": 0.82, "has_contributions": True,
                                  "has_disanalogy": True},
            "uncertainty_inputs": {"inverse_score": 0.18, "built_days_ago": 1,
                                   "disanalogy": "revenue mix differs"},
        }

    return {**base, **inputs}


def _sparse(ctype: str) -> dict:
    """Candidate where all *_inputs are empty dicts."""
    return {
        "candidate_type": ctype,
        "entity_type": "company",
        "entity_id": "sparse-001",
        "ticker": "SPARSE",
        "source_type": "unknown",
        "source_id": "sparse-001",
        "headline": "",
        "summary": "",
        "evidence_refs": [],
        "urgency_inputs": {},
        "impact_inputs": {},
        "attention_inputs": {},
        "confidence_inputs": {},
        "uncertainty_inputs": {},
        "source_versions": {},
        "user_id": None,
    }


_ALL_TYPES = [
    "forecast_candidate",
    "risk_candidate",
    "catalyst_candidate",
    "watchlist_candidate",
    "portfolio_exposure_candidate",
    "delivery_transition_candidate",
    "similarity_candidate",
]

# ---------------------------------------------------------------------------
# Helper: build a valid explanation for modification in failure tests
# ---------------------------------------------------------------------------

def _valid_explanation() -> dict:
    from app.services.decision_explainability_service import build_decision_explanation
    c = _candidate("forecast_candidate")
    r = _ranking()
    return build_decision_explanation(c, r)


# ---------------------------------------------------------------------------
# 1. Required output keys
# ---------------------------------------------------------------------------

class TestOutputShape:
    _REQUIRED = {"why_important", "why_now", "evidence", "deprioritizers",
                 "candidate_type", "decision_score", "disclaimer"}

    def test_all_required_keys_present(self):
        from app.services.decision_explainability_service import build_decision_explanation
        c = _candidate("forecast_candidate")
        r = _ranking()
        result = build_decision_explanation(c, r)
        missing = self._REQUIRED - set(result.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_decision_score_is_echoed(self):
        from app.services.decision_explainability_service import build_decision_explanation
        c = _candidate("risk_candidate")
        r = _ranking(decision_score=0.42)
        result = build_decision_explanation(c, r)
        assert abs(result["decision_score"] - 0.42) < 1e-9

    def test_candidate_type_is_echoed(self):
        from app.services.decision_explainability_service import build_decision_explanation
        c = _candidate("watchlist_candidate")
        r = _ranking()
        result = build_decision_explanation(c, r)
        assert result["candidate_type"] == "watchlist_candidate"


# ---------------------------------------------------------------------------
# 2–5. All 7 types — sections non-empty
# ---------------------------------------------------------------------------

class TestAllCandidateTypes:
    @pytest.mark.parametrize("ctype", _ALL_TYPES)
    def test_why_important_non_empty(self, ctype):
        from app.services.decision_explainability_service import build_decision_explanation
        result = build_decision_explanation(_candidate(ctype), _ranking())
        assert result["why_important"], f"why_important empty for {ctype}"

    @pytest.mark.parametrize("ctype", _ALL_TYPES)
    def test_why_now_non_empty(self, ctype):
        from app.services.decision_explainability_service import build_decision_explanation
        result = build_decision_explanation(_candidate(ctype), _ranking())
        assert result["why_now"], f"why_now empty for {ctype}"

    @pytest.mark.parametrize("ctype", _ALL_TYPES)
    def test_evidence_non_empty(self, ctype):
        from app.services.decision_explainability_service import build_decision_explanation
        result = build_decision_explanation(_candidate(ctype), _ranking())
        assert result["evidence"], f"evidence empty for {ctype}"

    @pytest.mark.parametrize("ctype", _ALL_TYPES)
    def test_deprioritizers_non_empty(self, ctype):
        from app.services.decision_explainability_service import build_decision_explanation
        result = build_decision_explanation(_candidate(ctype), _ranking())
        assert result["deprioritizers"], f"deprioritizers empty for {ctype}"


# ---------------------------------------------------------------------------
# 6–7. Disclaimer
# ---------------------------------------------------------------------------

class TestDisclaimer:
    def test_disclaimer_always_present(self):
        from app.services.decision_explainability_service import build_decision_explanation, _DISCLAIMER
        for ctype in _ALL_TYPES:
            result = build_decision_explanation(_candidate(ctype), _ranking())
            assert result["disclaimer"] == _DISCLAIMER

    def test_disclaimer_non_empty(self):
        from app.services.decision_explainability_service import build_decision_explanation
        result = build_decision_explanation(_candidate("forecast_candidate"), _ranking())
        assert result["disclaimer"].strip()


# ---------------------------------------------------------------------------
# 10. Sparse candidates
# ---------------------------------------------------------------------------

class TestSparseCandidates:
    @pytest.mark.parametrize("ctype", _ALL_TYPES)
    def test_sparse_no_exception(self, ctype):
        from app.services.decision_explainability_service import build_decision_explanation, validate_decision_explanation
        result = build_decision_explanation(_sparse(ctype), _ranking())
        # Must return all required sections (may not validate if ctype unknown, but sparse known types are valid)
        assert "why_important" in result
        assert "why_now" in result
        assert "evidence" in result
        assert "deprioritizers" in result

    def test_sparse_unknown_type_no_exception(self):
        from app.services.decision_explainability_service import build_decision_explanation
        c = _sparse("unknown_future_type")
        result = build_decision_explanation(c, _ranking())
        assert "disclaimer" in result


# ---------------------------------------------------------------------------
# 11–17. Validation — success and failure
# ---------------------------------------------------------------------------

class TestValidation:
    def test_valid_explanation_passes(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        expl = _valid_explanation()
        ok, reason = validate_decision_explanation(expl)
        assert ok is True
        assert reason is None

    def test_rejects_missing_why_important(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        expl = _valid_explanation()
        del expl["why_important"]
        ok, reason = validate_decision_explanation(expl)
        assert ok is False
        assert "why_important" in reason

    def test_rejects_empty_why_important(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        expl = _valid_explanation()
        expl["why_important"] = []
        ok, reason = validate_decision_explanation(expl)
        assert ok is False

    def test_rejects_missing_why_now(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        expl = _valid_explanation()
        del expl["why_now"]
        ok, reason = validate_decision_explanation(expl)
        assert ok is False
        assert "why_now" in reason

    def test_rejects_missing_evidence(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        expl = _valid_explanation()
        del expl["evidence"]
        ok, reason = validate_decision_explanation(expl)
        assert ok is False
        assert "evidence" in reason

    def test_rejects_missing_deprioritizers(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        expl = _valid_explanation()
        del expl["deprioritizers"]
        ok, reason = validate_decision_explanation(expl)
        assert ok is False
        assert "deprioritizers" in reason

    def test_rejects_missing_disclaimer(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        expl = _valid_explanation()
        del expl["disclaimer"]
        ok, reason = validate_decision_explanation(expl)
        assert ok is False
        assert "disclaimer" in reason

    def test_rejects_blank_disclaimer(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        expl = _valid_explanation()
        expl["disclaimer"] = "   "
        ok, reason = validate_decision_explanation(expl)
        assert ok is False

    def test_rejects_unsupported_candidate_type(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        expl = _valid_explanation()
        expl["candidate_type"] = "made_up_type"
        ok, reason = validate_decision_explanation(expl)
        assert ok is False
        assert "Unsupported" in reason

    def test_returns_bool_and_optional_str(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        expl = _valid_explanation()
        result = validate_decision_explanation(expl)
        assert isinstance(result, tuple)
        assert len(result) == 2
        ok, reason = result
        assert isinstance(ok, bool)
        assert reason is None or isinstance(reason, str)


# ---------------------------------------------------------------------------
# 18–23. Banned phrase detection
# ---------------------------------------------------------------------------

class TestBannedPhrases:
    def _inject(self, field: str, text: str) -> dict:
        expl = _valid_explanation()
        if isinstance(expl.get(field), list):
            expl[field] = [text]
        else:
            expl[field] = text
        return expl

    def test_rejects_buy_in_why_important(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        ok, reason = validate_decision_explanation(
            self._inject("why_important", "You should buy NVDA shares now.")
        )
        assert ok is False
        assert "buy" in reason

    def test_rejects_sell_in_why_now(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        ok, reason = validate_decision_explanation(
            self._inject("why_now", "Sell before the earnings drop.")
        )
        assert ok is False
        assert "sell" in reason

    def test_rejects_recommend_in_evidence(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        ok, reason = validate_decision_explanation(
            self._inject("evidence", "We recommend this stock.")
        )
        assert ok is False
        assert "recommend" in reason

    def test_rejects_target_price_in_deprioritizers(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        ok, reason = validate_decision_explanation(
            self._inject("deprioritizers", "Target price is $200.")
        )
        assert ok is False
        assert "target price" in reason

    def test_rejects_banned_phrase_in_disclaimer(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        expl = _valid_explanation()
        expl["disclaimer"] = "Hold this security for long-term gains."
        ok, reason = validate_decision_explanation(expl)
        assert ok is False
        assert "hold" in reason

    def test_case_insensitive_detection(self):
        from app.services.decision_explainability_service import validate_decision_explanation
        ok, reason = validate_decision_explanation(
            self._inject("why_important", "SELL everything before it drops.")
        )
        assert ok is False
        assert "sell" in reason


# ---------------------------------------------------------------------------
# 24. Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_inputs_same_output(self):
        from app.services.decision_explainability_service import build_decision_explanation
        c = _candidate("forecast_candidate")
        r = _ranking()
        r1 = build_decision_explanation(c, r)
        r2 = build_decision_explanation(c, r)
        assert r1["why_important"] == r2["why_important"]
        assert r1["why_now"] == r2["why_now"]
        assert r1["evidence"] == r2["evidence"]
        assert r1["deprioritizers"] == r2["deprioritizers"]
        assert r1["decision_score"] == r2["decision_score"]

    def test_different_types_different_why_important(self):
        from app.services.decision_explainability_service import build_decision_explanation
        r = _ranking()
        wf = " ".join(build_decision_explanation(_candidate("forecast_candidate"), r)["why_important"])
        wr = " ".join(build_decision_explanation(_candidate("risk_candidate"), r)["why_important"])
        assert wf != wr


# ---------------------------------------------------------------------------
# 25–28. Content spot-checks
# ---------------------------------------------------------------------------

class TestContentSpotChecks:
    def test_why_important_contains_ticker(self):
        from app.services.decision_explainability_service import build_why_important
        c = _candidate("forecast_candidate", ticker="AAPL")
        r = _ranking()
        result = " ".join(build_why_important(c, r))
        assert "AAPL" in result

    def test_why_now_reflects_urgency_label(self):
        from app.services.decision_explainability_service import build_why_now
        # High urgency (short horizon → near 1.0 urgency_score)
        c = _candidate("forecast_candidate")
        r = _ranking(urgency_score=0.90)
        result = " ".join(build_why_now(c, r))
        assert "high" in result.lower()

    def test_evidence_references_source_type(self):
        from app.services.decision_explainability_service import build_evidence_summary
        c = _candidate("risk_candidate")
        r = _ranking()
        result = " ".join(build_evidence_summary(c, r))
        assert c["source_type"] in result

    def test_evidence_references_source_id(self):
        from app.services.decision_explainability_service import build_evidence_summary
        c = _candidate("similarity_candidate")
        r = _ranking()
        result = " ".join(build_evidence_summary(c, r))
        assert c["source_id"] in result

    def test_deprioritizers_mentions_confidence(self):
        from app.services.decision_explainability_service import build_deprioritizers
        c = _candidate("forecast_candidate")
        r = _ranking(confidence_multiplier=0.45)
        result = " ".join(build_deprioritizers(c, r))
        assert "0.45" in result

    def test_portfolio_weight_in_why_important(self):
        from app.services.decision_explainability_service import build_why_important
        c = _candidate("portfolio_exposure_candidate")
        r = _ranking(impact_score=0.65)
        result = " ".join(build_why_important(c, r))
        # Weight 12% should appear
        assert "12%" in result

    def test_portfolio_exposure_multiplier_noted(self):
        from app.services.decision_explainability_service import build_deprioritizers
        c = _candidate("portfolio_exposure_candidate")
        r = _ranking(exposure_multiplier=1.18)
        result = " ".join(build_deprioritizers(c, r))
        assert "1.18" in result


# ---------------------------------------------------------------------------
# 29–30. Confidence and uncertainty caveats triggered
# ---------------------------------------------------------------------------

class TestCaveatsTriggered:
    def test_low_confidence_triggers_caveat(self):
        from app.services.decision_explainability_service import build_deprioritizers
        c = _candidate("forecast_candidate")
        r = _ranking(confidence_multiplier=0.40)
        result = " ".join(build_deprioritizers(c, r))
        assert "limited evidence" in result.lower() or "confidence" in result.lower()

    def test_high_uncertainty_triggers_caveat(self):
        from app.services.decision_explainability_service import build_deprioritizers
        c = _candidate("forecast_candidate")
        r = _ranking(uncertainty_discount=0.55)
        result = " ".join(build_deprioritizers(c, r))
        assert "uncertainty" in result.lower() or "spread" in result.lower()

    def test_forecast_high_neutral_probability_noted(self):
        from app.services.decision_explainability_service import build_deprioritizers
        # p_neutral = 0.40 stored in impact_inputs (we pass it via the candidate)
        c = _candidate("forecast_candidate")
        c["impact_inputs"]["p_neutral"] = 0.40
        r = _ranking()
        result = " ".join(build_deprioritizers(c, r))
        assert "neutral" in result.lower()

    def test_risk_old_match_noted(self):
        from app.services.decision_explainability_service import build_deprioritizers
        c = _candidate("risk_candidate")
        c["urgency_inputs"]["matched_days_ago"] = 45
        r = _ranking()
        result = " ".join(build_deprioritizers(c, r))
        assert "45" in result

    def test_similarity_high_inverse_score_noted(self):
        from app.services.decision_explainability_service import build_deprioritizers
        c = _candidate("similarity_candidate")
        c["uncertainty_inputs"]["inverse_score"] = 0.55
        r = _ranking()
        result = " ".join(build_deprioritizers(c, r))
        assert "0.55" in result


# ---------------------------------------------------------------------------
# 36–39. AST safety checks
# ---------------------------------------------------------------------------

def _load_tree() -> ast.AST:
    return ast.parse(_SVC.read_text(encoding="utf-8"))


def _get_docstring_values(tree: ast.AST) -> set:
    values: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                values.add(node.body[0].value.value)
    return values


class TestASTSafety:
    def test_no_sqlalchemy_or_session_imports(self):
        tree = _load_tree()
        forbidden_modules = {"sqlalchemy", "asyncio", "aiosqlite", "app.db"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fm in forbidden_modules:
                        assert fm not in part, \
                            f"Forbidden import {part!r} in explainability service"

    def test_no_conviction_or_execution_imports(self):
        tree = _load_tree()
        forbidden = {
            "conviction_modeler", "conviction",
            "recommendation", "order", "execution",
            "forecast_delivery_service",
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fw in forbidden:
                        assert fw not in part.lower(), \
                            f"Forbidden import {part!r} in explainability service"

    def test_no_advice_language_in_string_constants(self):
        tree = _load_tree()
        docstring_values = _get_docstring_values(tree)

        # Collect string values that are elements of _BANNED_PHRASES list literals.
        # Those strings are the ban-list definition itself, not output text.
        # The assignment may be annotated (AnnAssign) or plain (Assign).
        ban_list_values: set = set()
        for node in ast.walk(tree):
            value_node = None
            if isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == "_BANNED_PHRASES"
                       for t in node.targets):
                    value_node = node.value
            elif isinstance(node, ast.AnnAssign):
                if (isinstance(node.target, ast.Name)
                        and node.target.id == "_BANNED_PHRASES"
                        and node.value is not None):
                    value_node = node.value
            if value_node is not None and isinstance(value_node, ast.List):
                for elt in value_node.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        ban_list_values.add(elt.value)

        banned_terms = ["go long", "go short", "open a position", "close a position",
                        "take a position", "enter a trade", "exit a trade", "place an order"]
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if val in docstring_values or val in ban_list_values:
                    continue
                for term in banned_terms:
                    if term in val.lower():
                        offenders.append(repr(term) + " in " + repr(val[:60]))
        assert not offenders, "Advice language in string constants: " + str(offenders)

    def test_no_session_add_or_db_writes(self):
        src = _SVC.read_text(encoding="utf-8")
        assert "session.add(" not in src, "Found session.add() in explainability service"
        assert ".update(" not in src, "Found .update() in explainability service"
        assert ".delete(" not in src, "Found .delete() in explainability service"
