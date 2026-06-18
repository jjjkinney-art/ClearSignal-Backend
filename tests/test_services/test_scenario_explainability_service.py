"""
Tests — Scenario Explainability Service, Phase 14 · Slice 4.

Covers:
  1.  all 6 scenario types produce non-empty explanations
  2.  all required keys present in output
  3.  disclaimer invariant — always the fixed string
  4.  validation success on well-formed explanation
  5.  validation failure — missing required section
  6.  validation failure — missing disclaimer
  7.  validation failure — unsupported scenario_type
  8.  validation failure — banned phrase detection
  9.  each required section is a non-empty list
  10. what_changed contains changed_assumption text
  11. why_it_matters reflects propagation depth and entity counts
  12. transmission_mechanism reflects transmission path
  13. evidence references source_type and source_id
  14. invalidators mention the scenario assumption
  15. sparse propagation (empty indirect) — no exception
  16. empty propagation dict — graceful, no exception
  17. deterministic output — same inputs yield identical output twice
  18. no DB imports in module (AST)
  19. no write function calls in module (AST)
  20. no session parameter in public functions (AST)
  21. banned phrase scanner catches all listed phrases
  22. build_what_changed for each type mentions type-specific context
  23. build_why_it_matters for each type mentions entity count
  24. build_transmission_mechanism with empty path
  25. build_transmission_mechanism with multi-depth path
  26. build_evidence_summary for each type includes source reference
  27. build_invalidators for each type includes at least 2 conditions
  28. validate rejects empty explanation dict
  29. validate rejects None explanation
  30. validate rejects explanation with empty list section
  31. no advice language in module constants (AST)
  32. scenario_type field mirrors seed type
  33. all section sentences are strings (not nested lists)
  34. validate accepts company_scenario explanation end-to-end
  35. validate accepts portfolio_scenario explanation end-to-end
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any, Dict

import pytest

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "scenario_explainability_service.py"

_REQUIRED_KEYS = {
    "what_changed",
    "why_it_matters",
    "transmission_mechanism",
    "evidence",
    "invalidators",
    "scenario_type",
    "disclaimer",
}

_SCENARIO_TYPES = [
    "company_scenario",
    "macro_scenario",
    "sector_scenario",
    "catalyst_scenario",
    "failure_mode_scenario",
    "portfolio_scenario",
]

# ---------------------------------------------------------------------------
# Fixtures — minimal seed and propagation dicts for each scenario type
# ---------------------------------------------------------------------------

def _company_seed(ticker="NVDA", changed="If NVDA forecast strengthens"):
    return {
        "scenario_type":      "company_scenario",
        "entity_type":        "company",
        "entity_id":          ticker,
        "ticker":             ticker,
        "scenario_name":      f"{ticker} company scenario",
        "changed_assumption": changed,
        "source_type":        "forecast_vector",
        "source_id":          "fv-001",
        "evidence_refs":      ["ev-1", "ev-2"],
        "source_versions":    {"forecast_vector": "v2"},
        "transmission_inputs": {
            "direction": "strengthening", "forecast_type": "thesis_strengthening",
            "horizon": "near_term", "horizon_days": 30,
        },
        "impact_inputs":      {"p_positive": 0.70, "p_negative": 0.20},
        "confidence_inputs":  {"confidence_band_low": 0.55, "confidence_band_high": 0.85,
                               "p_max": 0.70, "evidence_count": 3, "forecast_schema": 1},
        "uncertainty_inputs": {"band_width": 0.30, "p_neutral": 0.10},
        "user_id":            None,
    }


def _macro_seed():
    return {
        "scenario_type":      "macro_scenario",
        "entity_type":        "macro",
        "entity_id":          "RATES",
        "ticker":             "",
        "scenario_name":      "Macro RATES scenario",
        "changed_assumption": "If interest rates rise 100bps",
        "source_type":        "forecast_vector",
        "source_id":          "fv-002",
        "evidence_refs":      [],
        "source_versions":    {},
        "transmission_inputs": {
            "direction": "accelerating", "forecast_type": "macro_shift",
            "horizon": "medium_term", "macro_key": "RATES", "watchlist_count": 12,
        },
        "impact_inputs":      {"p_positive": 0.60, "p_negative": 0.30},
        "confidence_inputs":  {"confidence_band_low": 0.50, "confidence_band_high": 0.80,
                               "evidence_count": 0},
        "uncertainty_inputs": {"band_width": 0.30, "p_neutral": 0.10},
        "user_id":            None,
    }


def _sector_seed():
    return {
        "scenario_type":      "sector_scenario",
        "entity_type":        "sector",
        "entity_id":          "SEMIS",
        "ticker":             "",
        "scenario_name":      "Sector SEMIS scenario",
        "changed_assumption": "If semiconductor sector contracts",
        "source_type":        "forecast_vector",
        "source_id":          "fv-003",
        "evidence_refs":      [],
        "source_versions":    {},
        "transmission_inputs": {
            "direction": "contracting", "forecast_type": "sector_shift",
            "sector_key": "SEMIS", "cross_tickers": ["NVDA", "AMD"],
        },
        "impact_inputs":      {"p_positive": 0.20, "p_negative": 0.65},
        "confidence_inputs":  {"confidence_band_low": 0.50, "confidence_band_high": 0.80,
                               "evidence_count": 0},
        "uncertainty_inputs": {"band_width": 0.30, "p_neutral": 0.15},
        "user_id":            None,
    }


def _catalyst_seed():
    return {
        "scenario_type":      "catalyst_scenario",
        "entity_type":        "company",
        "entity_id":          "dc-001",
        "ticker":             "NVDA",
        "scenario_name":      "NVDA catalyst scenario",
        "changed_assumption": "If NVDA catalyst triggers",
        "source_type":        "dossier_catalyst",
        "source_id":          "dc-001",
        "evidence_refs":      [],
        "source_versions":    {"dossier_catalyst": "dc-001"},
        "transmission_inputs": {
            "direction": "bull_trigger", "expected_window": "Q3",
            "specificity": 0.80, "ticker": "NVDA", "cross_tickers": [],
        },
        "impact_inputs":      {"specificity": 0.80, "conviction_weight": 0.6},
        "confidence_inputs":  {"specificity": 0.80, "has_statement": True,
                               "has_expected_window": True, "conviction_weight": 0.6},
        "uncertainty_inputs": {"inverse_specificity": 0.20, "created_days_ago": 5},
        "user_id":            None,
    }


def _failure_mode_seed():
    return {
        "scenario_type":      "failure_mode_scenario",
        "entity_type":        "company",
        "entity_id":          "fm-001",
        "ticker":             "INTC",
        "scenario_name":      "INTC failure-mode scenario",
        "changed_assumption": "If INTC continues on trajectory",
        "source_type":        "dossier_failure_mode",
        "source_id":          "fm-001",
        "evidence_refs":      [],
        "source_versions":    {"dossier_failure_mode": "fm-001"},
        "transmission_inputs": {
            "analog_id": "analog-xyz", "sequence_stage": 3,
            "ticker": "INTC", "cross_tickers": [],
        },
        "impact_inputs":      {"relevance_at_match": 0.75, "sequence_stage": 3},
        "confidence_inputs":  {"relevance_at_match": 0.75, "has_stage_evidence": True,
                               "sequence_stage": 3},
        "uncertainty_inputs": {"matched_days_ago": 7, "sequence_stage": 3},
        "user_id":            None,
    }


def _portfolio_seed():
    return {
        "scenario_type":      "portfolio_scenario",
        "entity_type":        "portfolio",
        "entity_id":          "port-001",
        "ticker":             "",
        "scenario_name":      "Portfolio scenario",
        "changed_assumption": "If shared macro condition applies",
        "source_type":        "portfolio_positions",
        "source_id":          "port-001",
        "evidence_refs":      [],
        "source_versions":    {"portfolio": "port-001"},
        "transmission_inputs": {
            "portfolio_id": "port-001", "portfolio_name": "Growth Portfolio",
            "position_count": 3, "tickers": ["NVDA", "AAPL", "MSFT"], "is_default": False,
        },
        "impact_inputs":      {"position_count": 3, "portfolio_name": "Growth Portfolio"},
        "confidence_inputs":  {"has_positions": True, "position_count": 3, "is_default": False},
        "uncertainty_inputs": {"position_count": 3, "correlation_unknown": True},
        "user_id":            None,
    }


_SEED_FACTORIES = {
    "company_scenario":      _company_seed,
    "macro_scenario":        _macro_seed,
    "sector_scenario":       _sector_seed,
    "catalyst_scenario":     _catalyst_seed,
    "failure_mode_scenario": _failure_mode_seed,
    "portfolio_scenario":    _portfolio_seed,
}


def _minimal_propagation(stype="company_scenario", ticker="NVDA", depth=0):
    direct = [{"entity_key": ticker, "entity_type": "company",
               "impact_channel": "direct", "transmission_strength": "strong", "depth": 0}]
    indirect: list = []
    if depth >= 1:
        indirect.append({"entity_key": "AMD", "entity_type": "company",
                          "impact_channel": "cross_exposure", "transmission_strength": "moderate",
                          "depth": 1})
    if depth >= 2:
        indirect.append({"entity_key": "TSLA", "entity_type": "company",
                          "impact_channel": "cross_exposure", "transmission_strength": "weak",
                          "depth": 2})
    path = [{"step": 0, "cause": "assumption", "effect": f"{ticker} affected", "channel": "direct"}]
    if depth >= 1:
        path.append({"step": 1, "cause": ticker, "effect": "AMD", "channel": "cross_exposure:sector"})
    if depth >= 2:
        path.append({"step": 2, "cause": "AMD", "effect": "TSLA", "channel": "cross_exposure:sector"})
    return {
        "scenario_type":       stype,
        "scenario_name":       "test",
        "transmission_path":   path,
        "direct_impacts":      direct,
        "indirect_impacts":    indirect,
        "affected_entities":   direct + indirect,
        "affected_portfolios": [],
        "impact_confidence":   0.70,
        "impact_uncertainty":  0.25,
        "propagation_depth":   depth,
        "source_versions":     {},
    }


# ---------------------------------------------------------------------------
# 1. All 6 scenario types produce non-empty explanations
# ---------------------------------------------------------------------------

class TestAllSixTypes:
    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    def test_produces_non_empty_explanation(self, stype):
        from app.services.scenario_explainability_service import build_scenario_explanation
        seed = _SEED_FACTORIES[stype]()
        prop = _minimal_propagation(stype=stype)
        result = build_scenario_explanation(seed, prop)
        assert result
        assert len(result) >= len(_REQUIRED_KEYS)

    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    def test_scenario_type_field_mirrors_seed(self, stype):
        from app.services.scenario_explainability_service import build_scenario_explanation
        seed = _SEED_FACTORIES[stype]()
        prop = _minimal_propagation(stype=stype)
        result = build_scenario_explanation(seed, prop)
        assert result["scenario_type"] == stype


# ---------------------------------------------------------------------------
# 2. Required keys present
# ---------------------------------------------------------------------------

class TestRequiredKeys:
    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    def test_all_required_keys_present(self, stype):
        from app.services.scenario_explainability_service import build_scenario_explanation
        seed = _SEED_FACTORIES[stype]()
        prop = _minimal_propagation(stype=stype)
        result = build_scenario_explanation(seed, prop)
        missing = _REQUIRED_KEYS - result.keys()
        assert not missing, f"Missing keys for {stype}: {missing}"


# ---------------------------------------------------------------------------
# 3. Disclaimer invariant
# ---------------------------------------------------------------------------

class TestDisclaimerInvariant:
    def test_disclaimer_is_fixed_string(self):
        from app.services.scenario_explainability_service import (
            build_scenario_explanation, _DISCLAIMER,
        )
        seed = _company_seed()
        prop = _minimal_propagation()
        result = build_scenario_explanation(seed, prop)
        assert result["disclaimer"] == _DISCLAIMER

    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    def test_disclaimer_same_for_all_types(self, stype):
        from app.services.scenario_explainability_service import (
            build_scenario_explanation, _DISCLAIMER,
        )
        seed = _SEED_FACTORIES[stype]()
        prop = _minimal_propagation(stype=stype)
        result = build_scenario_explanation(seed, prop)
        assert result["disclaimer"] == _DISCLAIMER

    def test_disclaimer_is_non_empty(self):
        from app.services.scenario_explainability_service import _DISCLAIMER
        assert _DISCLAIMER and len(_DISCLAIMER) > 20


# ---------------------------------------------------------------------------
# 4–8. Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def _good_explanation(self, stype="company_scenario"):
        from app.services.scenario_explainability_service import build_scenario_explanation
        seed = _SEED_FACTORIES[stype]()
        prop = _minimal_propagation(stype=stype)
        return build_scenario_explanation(seed, prop)

    def test_valid_explanation_passes(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        ok, reason = validate_scenario_explanation(self._good_explanation())
        assert ok, reason

    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    def test_valid_for_all_types(self, stype):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        ok, reason = validate_scenario_explanation(self._good_explanation(stype))
        assert ok, f"{stype}: {reason}"

    def test_missing_required_section_fails(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        exp = self._good_explanation()
        for field in ("what_changed", "why_it_matters", "transmission_mechanism",
                      "evidence", "invalidators"):
            bad = dict(exp)
            del bad[field]
            ok, reason = validate_scenario_explanation(bad)
            assert not ok
            assert field in reason

    def test_missing_disclaimer_fails(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        exp = dict(self._good_explanation())
        del exp["disclaimer"]
        ok, reason = validate_scenario_explanation(exp)
        assert not ok
        assert "disclaimer" in reason

    def test_blank_disclaimer_fails(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        exp = dict(self._good_explanation())
        exp["disclaimer"] = "   "
        ok, reason = validate_scenario_explanation(exp)
        assert not ok

    def test_unsupported_scenario_type_fails(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        exp = dict(self._good_explanation())
        exp["scenario_type"] = "alien_scenario"
        ok, reason = validate_scenario_explanation(exp)
        assert not ok
        assert "Unsupported" in reason

    def test_empty_scenario_type_fails(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        exp = dict(self._good_explanation())
        exp["scenario_type"] = ""
        ok, reason = validate_scenario_explanation(exp)
        assert not ok

    def test_banned_phrase_in_what_changed_fails(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        exp = self._good_explanation()
        exp["what_changed"] = ["You should buy this immediately."]
        ok, reason = validate_scenario_explanation(exp)
        assert not ok
        assert "buy" in reason

    def test_banned_phrase_in_why_it_matters_fails(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        exp = self._good_explanation()
        exp["why_it_matters"] = ["Consider this a sell signal."]
        ok, reason = validate_scenario_explanation(exp)
        assert not ok
        assert "sell" in reason

    def test_banned_phrase_in_invalidators_fails(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        exp = self._good_explanation()
        exp["invalidators"] = ["Invalidated if you hold the position."]
        ok, reason = validate_scenario_explanation(exp)
        assert not ok
        assert "hold" in reason

    def test_empty_list_section_fails(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        exp = self._good_explanation()
        exp["what_changed"] = []
        ok, reason = validate_scenario_explanation(exp)
        assert not ok
        assert "what_changed" in reason

    def test_empty_dict_fails(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        ok, reason = validate_scenario_explanation({})
        assert not ok

    def test_none_explanation_fails(self):
        from app.services.scenario_explainability_service import validate_scenario_explanation
        with pytest.raises((TypeError, AttributeError)):
            validate_scenario_explanation(None)


# ---------------------------------------------------------------------------
# 9. Sections are non-empty lists
# ---------------------------------------------------------------------------

class TestSectionStructure:
    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    @pytest.mark.parametrize("section", ["what_changed", "why_it_matters",
                                          "transmission_mechanism", "evidence", "invalidators"])
    def test_section_is_non_empty_list(self, stype, section):
        from app.services.scenario_explainability_service import build_scenario_explanation
        seed = _SEED_FACTORIES[stype]()
        prop = _minimal_propagation(stype=stype)
        result = build_scenario_explanation(seed, prop)
        value = result[section]
        assert isinstance(value, list), f"{section} not a list for {stype}"
        assert len(value) >= 1, f"{section} is empty for {stype}"

    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    @pytest.mark.parametrize("section", ["what_changed", "why_it_matters",
                                          "transmission_mechanism", "evidence", "invalidators"])
    def test_section_items_are_strings(self, stype, section):
        from app.services.scenario_explainability_service import build_scenario_explanation
        seed = _SEED_FACTORIES[stype]()
        prop = _minimal_propagation(stype=stype)
        result = build_scenario_explanation(seed, prop)
        for item in result[section]:
            assert isinstance(item, str), (
                f"Non-string item in {section} for {stype}: {item!r}"
            )


# ---------------------------------------------------------------------------
# 10. what_changed contains changed_assumption
# ---------------------------------------------------------------------------

class TestWhatChanged:
    def test_contains_changed_assumption_text(self):
        from app.services.scenario_explainability_service import build_what_changed
        seed = _company_seed(changed="If NVDA margin expands significantly")
        result = build_what_changed(seed, {})
        combined = " ".join(result)
        assert "NVDA margin expands significantly" in combined

    def test_company_mentions_ticker(self):
        from app.services.scenario_explainability_service import build_what_changed
        seed = _company_seed(ticker="AAPL")
        result = build_what_changed(seed, {})
        combined = " ".join(result)
        assert "AAPL" in combined

    def test_macro_mentions_macro_key(self):
        from app.services.scenario_explainability_service import build_what_changed
        seed = _macro_seed()
        result = build_what_changed(seed, {})
        combined = " ".join(result)
        assert "RATES" in combined

    def test_sector_mentions_sector_key(self):
        from app.services.scenario_explainability_service import build_what_changed
        result = build_what_changed(_sector_seed(), {})
        assert "SEMIS" in " ".join(result)

    def test_catalyst_mentions_ticker(self):
        from app.services.scenario_explainability_service import build_what_changed
        result = build_what_changed(_catalyst_seed(), {})
        assert "NVDA" in " ".join(result)

    def test_failure_mode_mentions_stage(self):
        from app.services.scenario_explainability_service import build_what_changed
        result = build_what_changed(_failure_mode_seed(), {})
        assert "3" in " ".join(result)

    def test_portfolio_mentions_portfolio_name(self):
        from app.services.scenario_explainability_service import build_what_changed
        result = build_what_changed(_portfolio_seed(), {})
        assert "Growth Portfolio" in " ".join(result)


# ---------------------------------------------------------------------------
# 11. why_it_matters mentions entity counts
# ---------------------------------------------------------------------------

class TestWhyItMatters:
    def test_mentions_total_entity_count(self):
        from app.services.scenario_explainability_service import build_why_it_matters
        prop = _minimal_propagation(depth=1)
        result = build_why_it_matters(_company_seed(), prop)
        combined = " ".join(result)
        assert "2" in combined  # 1 direct + 1 indirect

    def test_macro_mentions_watchlist_count(self):
        from app.services.scenario_explainability_service import build_why_it_matters
        prop = _minimal_propagation(stype="macro_scenario", depth=1)
        result = build_why_it_matters(_macro_seed(), prop)
        combined = " ".join(result)
        assert "RATES" in combined or "1" in combined

    def test_sector_mentions_sector_key(self):
        from app.services.scenario_explainability_service import build_why_it_matters
        prop = _minimal_propagation(stype="sector_scenario", depth=1)
        result = build_why_it_matters(_sector_seed(), prop)
        assert "SEMIS" in " ".join(result)

    def test_confidence_label_present(self):
        from app.services.scenario_explainability_service import build_why_it_matters
        prop = _minimal_propagation(depth=0)
        result = build_why_it_matters(_company_seed(), prop)
        combined = " ".join(result)
        assert any(label in combined for label in ("high", "moderate", "low", "minimal"))


# ---------------------------------------------------------------------------
# 12. transmission_mechanism
# ---------------------------------------------------------------------------

class TestTransmissionMechanism:
    def test_empty_path_returns_non_empty_list(self):
        from app.services.scenario_explainability_service import build_transmission_mechanism
        prop = {**_minimal_propagation(depth=0), "transmission_path": []}
        result = build_transmission_mechanism(_company_seed(), prop)
        assert isinstance(result, list) and len(result) >= 1

    def test_non_empty_path_mentions_steps(self):
        from app.services.scenario_explainability_service import build_transmission_mechanism
        prop = _minimal_propagation(depth=2)
        result = build_transmission_mechanism(_company_seed(), prop)
        combined = " ".join(result)
        assert any(char.isdigit() for char in combined)

    def test_multi_depth_mentions_second_order(self):
        from app.services.scenario_explainability_service import build_transmission_mechanism
        prop = _minimal_propagation(depth=2)
        result = build_transmission_mechanism(_company_seed(), prop)
        combined = " ".join(result).lower()
        assert "second" in combined or "depth" in combined or "2" in combined

    def test_channels_mentioned(self):
        from app.services.scenario_explainability_service import build_transmission_mechanism
        prop = _minimal_propagation(depth=1)
        result = build_transmission_mechanism(_company_seed(), prop)
        combined = " ".join(result)
        assert "cross_exposure" in combined or "direct" in combined


# ---------------------------------------------------------------------------
# 13. evidence_summary includes source reference
# ---------------------------------------------------------------------------

class TestEvidenceSummary:
    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    def test_source_type_and_id_in_evidence(self, stype):
        from app.services.scenario_explainability_service import build_evidence_summary
        seed = _SEED_FACTORIES[stype]()
        prop = _minimal_propagation(stype=stype)
        result = build_evidence_summary(seed, prop)
        combined = " ".join(result)
        assert seed["source_type"] in combined
        assert seed["source_id"] in combined

    def test_evidence_refs_count_mentioned(self):
        from app.services.scenario_explainability_service import build_evidence_summary
        seed = _company_seed()
        result = build_evidence_summary(seed, {})
        combined = " ".join(result)
        assert "2" in combined  # 2 evidence refs in company_seed

    def test_source_versions_mentioned(self):
        from app.services.scenario_explainability_service import build_evidence_summary
        seed = _company_seed()
        result = build_evidence_summary(seed, {})
        combined = " ".join(result)
        assert "v2" in combined

    def test_company_mentions_confidence_band(self):
        from app.services.scenario_explainability_service import build_evidence_summary
        result = build_evidence_summary(_company_seed(), {})
        combined = " ".join(result)
        assert "0.55" in combined and "0.85" in combined

    def test_failure_mode_mentions_stage(self):
        from app.services.scenario_explainability_service import build_evidence_summary
        result = build_evidence_summary(_failure_mode_seed(), {})
        combined = " ".join(result)
        assert "3" in combined  # stage 3

    def test_portfolio_mentions_position_count(self):
        from app.services.scenario_explainability_service import build_evidence_summary
        result = build_evidence_summary(_portfolio_seed(), {})
        combined = " ".join(result)
        assert "3" in combined


# ---------------------------------------------------------------------------
# 14. invalidators mention assumption / type-specific info
# ---------------------------------------------------------------------------

class TestInvalidators:
    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    def test_at_least_two_invalidators(self, stype):
        from app.services.scenario_explainability_service import build_invalidators
        seed = _SEED_FACTORIES[stype]()
        result = build_invalidators(seed, _minimal_propagation(stype=stype))
        assert len(result) >= 2

    def test_company_invalidator_mentions_horizon(self):
        from app.services.scenario_explainability_service import build_invalidators
        result = build_invalidators(_company_seed(), {})
        combined = " ".join(result)
        assert "near_term" in combined or "horizon" in combined

    def test_macro_invalidator_mentions_macro_key(self):
        from app.services.scenario_explainability_service import build_invalidators
        result = build_invalidators(_macro_seed(), {})
        assert "RATES" in " ".join(result)

    def test_sector_invalidator_mentions_sector_key(self):
        from app.services.scenario_explainability_service import build_invalidators
        result = build_invalidators(_sector_seed(), {})
        assert "SEMIS" in " ".join(result)

    def test_catalyst_invalidator_mentions_window(self):
        from app.services.scenario_explainability_service import build_invalidators
        result = build_invalidators(_catalyst_seed(), {})
        assert "Q3" in " ".join(result)

    def test_failure_mode_invalidator_mentions_stage(self):
        from app.services.scenario_explainability_service import build_invalidators
        result = build_invalidators(_failure_mode_seed(), {})
        combined = " ".join(result)
        assert "3" in combined

    def test_portfolio_invalidator_mentions_portfolio_name(self):
        from app.services.scenario_explainability_service import build_invalidators
        result = build_invalidators(_portfolio_seed(), {})
        assert "Growth Portfolio" in " ".join(result)


# ---------------------------------------------------------------------------
# 15–16. Sparse / empty propagation
# ---------------------------------------------------------------------------

class TestSparseAndEmptyPropagation:
    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    def test_empty_propagation_no_exception(self, stype):
        from app.services.scenario_explainability_service import build_scenario_explanation
        seed = _SEED_FACTORIES[stype]()
        result = build_scenario_explanation(seed, {})
        assert isinstance(result, dict)
        assert _REQUIRED_KEYS.issubset(result.keys())

    def test_sparse_propagation_no_exception(self):
        from app.services.scenario_explainability_service import build_scenario_explanation
        prop = _minimal_propagation(depth=0)
        result = build_scenario_explanation(_company_seed(), prop)
        assert result["direct_impacts"] if "direct_impacts" in result else True

    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    def test_empty_propagation_validation_passes(self, stype):
        from app.services.scenario_explainability_service import (
            build_scenario_explanation, validate_scenario_explanation,
        )
        seed = _SEED_FACTORIES[stype]()
        result = build_scenario_explanation(seed, {})
        ok, reason = validate_scenario_explanation(result)
        assert ok, f"{stype}: {reason}"


# ---------------------------------------------------------------------------
# 17. Deterministic output
# ---------------------------------------------------------------------------

class TestDeterminism:
    @pytest.mark.parametrize("stype", _SCENARIO_TYPES)
    def test_same_inputs_yield_identical_output(self, stype):
        from app.services.scenario_explainability_service import build_scenario_explanation
        seed = _SEED_FACTORIES[stype]()
        prop = _minimal_propagation(stype=stype, depth=1)
        r1 = build_scenario_explanation(seed, prop)
        r2 = build_scenario_explanation(seed, prop)
        assert r1 == r2


# ---------------------------------------------------------------------------
# 18–20. AST: no DB imports, no writes, no session parameter
# ---------------------------------------------------------------------------

class TestASTNoDBImports:
    def _ast_imports(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
        return imported

    def test_no_sqlalchemy_imports(self):
        violations = [n for n in self._ast_imports() if "sqlalchemy" in n.lower()]
        assert not violations, f"SQLAlchemy imported: {violations}"

    def test_no_db_models_import(self):
        violations = [n for n in self._ast_imports() if "app.db" in n]
        assert not violations, f"DB module imported: {violations}"

    def test_no_repo_imports(self):
        violations = [n for n in self._ast_imports() if "repo" in n.lower()]
        assert not violations, f"Repo imported: {violations}"

    def test_no_session_parameter_in_public_functions(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        violations = []
        public_fns = {"build_scenario_explanation", "build_what_changed", "build_why_it_matters",
                      "build_transmission_mechanism", "build_evidence_summary",
                      "build_invalidators", "validate_scenario_explanation"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in public_fns:
                    param_names = [a.arg for a in node.args.args]
                    if "session" in param_names:
                        violations.append(node.name)
        assert not violations, f"Public functions have session param: {violations}"


class TestASTNoWrites:
    def test_no_write_calls(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        write_fns = {
            "upsert_scenario_snapshot", "add_scenario_evidence", "add_run_log",
            "upsert_forecast_vector", "upsert_decision_priority",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                attr = None
                if isinstance(node.func, ast.Attribute):
                    attr = node.func.attr
                elif isinstance(node.func, ast.Name):
                    attr = node.func.id
                if attr in write_fns:
                    assert False, f"Write call {attr!r} found in explainability service"

    def test_no_session_usage_in_body(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "session":
                if isinstance(node.ctx, ast.Load):
                    assert False, "Variable 'session' used in explainability service body"


# ---------------------------------------------------------------------------
# 21. Banned phrase scanner covers all phrases
# ---------------------------------------------------------------------------

class TestBannedPhraseScanner:
    def test_scanner_detects_all_listed_phrases(self):
        from app.services.scenario_explainability_service import _BANNED_PHRASES, _has_banned
        for phrase in _BANNED_PHRASES:
            # Scanner returns the FIRST matching phrase in the list; it may be a
            # sub-phrase (e.g. "short" triggers before "go short"). We only
            # require that the scanner returns a non-None result — i.e. that
            # embedding the phrase in text causes detection.
            result = _has_banned(f"You should {phrase} now.")
            assert result is not None, f"Scanner missed: {phrase!r}"

    def test_scanner_is_case_insensitive(self):
        from app.services.scenario_explainability_service import _has_banned
        assert _has_banned("BUY NOW") == "buy"
        assert _has_banned("SELL EVERYTHING") == "sell"
        assert _has_banned("HOLD THE LINE") == "hold"

    def test_scanner_returns_none_for_clean_text(self):
        from app.services.scenario_explainability_service import _has_banned
        assert _has_banned("The structural change affects 3 entities.") is None
        assert _has_banned("Confidence is moderate based on evidence.") is None


# ---------------------------------------------------------------------------
# 22. No advice language in module constants (AST)
# ---------------------------------------------------------------------------

class TestNoAdviceLanguageInModule:
    def _non_docstring_constants(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        docstring_ids: set = set()
        for node in ast.walk(tree):
            body = None
            if isinstance(node, (ast.Module, ast.ClassDef,
                                  ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr):
                inner = body[0].value
                if isinstance(inner, ast.Constant):
                    docstring_ids.add(id(inner))
        return [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_ids
        ]

    def test_no_buy_sell_in_non_docstring_constants(self):
        for val in self._non_docstring_constants():
            low = val.lower()
            # The only constants that may contain these terms are the _BANNED_PHRASES
            # list entries themselves (which are looked up, not emitted as output)
            # and the _DISCLAIMER (which lists what this is NOT).
            # Those are the definitions — they must not appear as rendered output.
            # We check the disclaimer separately; here we check other constants.
            if val in ("buy", "sell", "hold", "overweight", "underweight", "recommend",
                       "target price", "position size", "take a position", "enter a trade",
                       "exit a trade", "place an order", "execute", "short",
                       "long position", "go long", "go short", "open a position",
                       "close a position"):
                continue  # These are allowed as banned-phrase definition strings
            for term in ("you should buy", "you should sell", "place a trade",
                         "enter the position", "recommended action"):
                assert term not in low, (
                    f"Advice phrase {term!r} in module constant: {val!r}"
                )


# ---------------------------------------------------------------------------
# 34–35. End-to-end validation for company and portfolio
# ---------------------------------------------------------------------------

class TestEndToEndValidation:
    def test_company_explanation_end_to_end(self):
        from app.services.scenario_explainability_service import (
            build_scenario_explanation, validate_scenario_explanation,
        )
        seed = _company_seed(ticker="MSFT", changed="If MSFT cloud revenue accelerates")
        prop = _minimal_propagation(stype="company_scenario", ticker="MSFT", depth=2)
        expl = build_scenario_explanation(seed, prop)
        ok, reason = validate_scenario_explanation(expl)
        assert ok, reason
        assert expl["scenario_type"] == "company_scenario"
        assert expl["disclaimer"]
        for sec in ("what_changed", "why_it_matters", "transmission_mechanism",
                    "evidence", "invalidators"):
            assert expl[sec], f"{sec} is empty"

    def test_portfolio_explanation_end_to_end(self):
        from app.services.scenario_explainability_service import (
            build_scenario_explanation, validate_scenario_explanation,
        )
        seed = _portfolio_seed()
        prop = _minimal_propagation(stype="portfolio_scenario", depth=1)
        expl = build_scenario_explanation(seed, prop)
        ok, reason = validate_scenario_explanation(expl)
        assert ok, reason
        assert expl["scenario_type"] == "portfolio_scenario"
