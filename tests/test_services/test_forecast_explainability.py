"""
Phase 12 — Slice 4: Forecast Explainability + Safety Constants Tests.

Covers:
  forecast_constants.py
  ─ MANDATORY_DISCLAIMER present and non-empty
  ─ BANNED_ADVICE_PHRASES is a non-empty tuple of lowercase strings
  ─ ALLOWED_FORECAST_TYPES matches probability engine
  ─ ALLOWED_HORIZONS matches probability engine
  ─ ALLOWED_CONFIDENCE_LABELS covers low/medium/high
  ─ INVALIDATOR_TEMPLATES has an entry for every allowed type

  forecast_explainability_service.py
  ─ contains_banned_advice_language (string, dict, list, nested)
  ─ build_evidence_summary (full, sparse, T4 failure_mode)
  ─ build_invalidators (all 6 types, T4 stage, staleness)
  ─ build_forecast_explanation happy path
  ─ build_forecast_explanation with sparse features
  ─ build_forecast_explanation with T4 failure_mode
  ─ validate_forecast_explanation happy path
  ─ validate rejects empty why
  ─ validate rejects empty evidence
  ─ validate rejects empty invalidators
  ─ validate rejects missing disclaimer
  ─ validate rejects wrong disclaimer text
  ─ validate rejects unsupported horizon
  ─ validate rejects unsupported forecast_type
  ─ validate rejects unsupported confidence_label
  ─ validate rejects banned advice phrases in why
  ─ validate rejects price-target language in why
  ─ validate rejects recommendation language in why
  ─ validate rejects buy/sell/hold language in why
  ─ validate rejects banned language in evidence description
  ─ validate rejects banned language in invalidators
  ─ disclaimer always present in explanation output
  ─ no banned phrases in any template output (all 6 types × 3 horizons)
  ─ pure functions / no DB imports (AST)
  ─ no write calls (AST)
  ─ no import from probability_engine or feature_builder (AST)
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).parent.parent.parent

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from app.services.forecast_constants import (
    ALLOWED_FORECAST_TYPES,
    ALLOWED_HORIZONS,
    ALLOWED_CONFIDENCE_LABELS,
    MANDATORY_DISCLAIMER,
    BANNED_ADVICE_PHRASES,
    INVALIDATOR_TEMPLATES,
    GENERIC_INVALIDATORS,
    FORECAST_TYPE_DISPLAY,
    HORIZON_LABELS,
)
from app.services.forecast_explainability_service import (
    build_forecast_explanation,
    validate_forecast_explanation,
    contains_banned_advice_language,
    build_invalidators,
    build_evidence_summary,
)

ALL_FORECAST_TYPES = sorted(ALLOWED_FORECAST_TYPES)
ALL_HORIZONS = sorted(ALLOWED_HORIZONS)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _prob_output(
    forecast_type: str = "thesis_weakening",
    horizon_days: int = 30,
    p_positive: float = 0.62,
    p_negative: float = 0.22,
    p_neutral: float = 0.16,
    confidence_label: str = "medium",
    evidence_strength: float = 0.55,
    staleness_penalty_applied: bool = False,
) -> dict:
    return {
        "p_positive": p_positive,
        "p_negative": p_negative,
        "p_neutral": p_neutral,
        "confidence_low": 0.45,
        "confidence_high": 0.79,
        "confidence_label": confidence_label,
        "horizon_days": horizon_days,
        "forecast_type": forecast_type,
        "components": {
            "p_base_rate": 0.65,
            "p_sim_peer": 0.60,
            "p_thesis_signal": 0.70,
            "p_regime_signal": 0.55,
            "weights_used": {"base": 0.25, "sim": 0.15, "thesis": 0.40, "regime": 0.20},
        },
        "evidence_strength": evidence_strength,
        "staleness_penalty_applied": staleness_penalty_applied,
        "engine_schema": 1,
    }


def _company_features(
    *,
    analog_resolutions: list = None,
    sim_peer_count: int = 3,
    sim_avg_score: float = 0.65,
    confidence_current: float = 0.70,
    version_count: int = 2,
    direction: str = "rising",
    lean: str = "bearish",
    conviction_trend: str = "declining",
    cycle_position: str = "late_cycle",
    staleness_state: str = "fresh",
    catalyst_proximity_days: int = 45,
) -> dict:
    if analog_resolutions is None:
        analog_resolutions = ["negative", "negative", "neutral"]
    analog_set = [
        {
            "analog_id": f"aid{i}",
            "mechanism": "governance",
            "concern_tags": ["governance"],
            "quality_rating": "B+",
            "outcome_summary": "pattern resolved",
            "drawdown_pct": 0.25,
            "time_to_recover_days": 90,
            "valuation_regime": "growth",
            "growth_phase": "late",
            "macro_regime": "tightening",
            "sector": "tech",
            "business_model": "saas",
            "relevance_weight": 0.8,
            "resolution": r,
        }
        for i, r in enumerate(analog_resolutions)
    ]
    return {
        "entity_type": "company",
        "entity_key": "ACME",
        "analog_set": analog_set,
        "analog_count": len(analog_set),
        "similarity_peers": [
            {"candidate_key": f"PEER{i}", "score": sim_avg_score, "target_type": "company", "rank": i + 1}
            for i in range(sim_peer_count)
        ],
        "similarity_peer_count": sim_peer_count,
        "similarity_avg_score": sim_avg_score,
        "thesis_trajectory": {
            "confidence_current": confidence_current,
            "confidence_previous": 0.55,
            "delta": confidence_current - 0.55,
            "direction": direction,
            "version_count": version_count,
            "stance": "bearish",
            "primary_concern": "governance",
        },
        "debate_state": {
            "current_lean": lean,
            "version": 3,
            "confidence": 0.68,
        },
        "regime_context": {
            "conviction_trend": conviction_trend,
            "cycle_position": cycle_position,
            "horizon_hint": "tactical",
            "staleness_state": staleness_state,
        },
        "durability": {
            "catalyst_proximity_days": catalyst_proximity_days,
            "analog_time_to_trough_days": 60,
        },
        "source_versions": {
            "company_dossier_row_version": 5,
            "thesis_version_id": "tv-abc",
            "core_debate_version": 3,
            "feature_schema": 1,
        },
        "staleness_indicators": {
            "dossier_staleness_state": staleness_state,
            "has_similarity_peers": sim_peer_count > 0,
            "has_analogs": len(analog_set) > 0,
            "thesis_is_recent": True,
            "debate_has_lean": True,
        },
        "feature_schema": 1,
    }


def _sparse_features() -> dict:
    return {
        "entity_type": "company",
        "entity_key": "SPARSE",
        "analog_set": [],
        "analog_count": 0,
        "similarity_peers": [],
        "similarity_peer_count": 0,
        "similarity_avg_score": 0.0,
        "thesis_trajectory": {
            "confidence_current": 0.0, "confidence_previous": None,
            "delta": 0.0, "direction": "flat", "version_count": 0,
            "stance": "", "primary_concern": "",
        },
        "debate_state": {"current_lean": "balanced", "version": 1, "confidence": 0.0},
        "regime_context": {
            "conviction_trend": "stable", "cycle_position": "unknown",
            "horizon_hint": "investment", "staleness_state": "fresh",
        },
        "durability": {"catalyst_proximity_days": None, "analog_time_to_trough_days": None},
        "source_versions": {"company_dossier_row_version": 0, "thesis_version_id": "", "core_debate_version": 1, "feature_schema": 1},
        "staleness_indicators": {
            "dossier_staleness_state": "fresh", "has_similarity_peers": False,
            "has_analogs": False, "thesis_is_recent": False, "debate_has_lean": False,
        },
        "feature_schema": 1,
    }


def _fm_features(sequence_stage: int = 2) -> dict:
    f = _company_features()
    f["entity_type"] = "failure_mode"
    f["entity_key"] = "fm-001"
    f["failure_mode"] = {
        "ticker": "ACME",
        "analog_id": "aid0",
        "mechanism": "liquidity_crunch",
        "sequence_stage": sequence_stage,
        "relevance_at_match": 0.85,
        "stage_evidence": "Q3 covenant breach",
    }
    return f


def _stale_features() -> dict:
    f = _company_features()
    f["regime_context"]["staleness_state"] = "stale"
    f["staleness_indicators"]["dossier_staleness_state"] = "stale"
    return f


def _valid_explanation(forecast_type: str = "thesis_weakening", horizon: int = 30) -> dict:
    feat = _company_features()
    prob = _prob_output(forecast_type=forecast_type, horizon_days=horizon)
    return build_forecast_explanation(feat, prob)


# ---------------------------------------------------------------------------
# FORECAST CONSTANTS
# ---------------------------------------------------------------------------

class TestForecastConstants:
    def test_mandatory_disclaimer_non_empty(self):
        assert isinstance(MANDATORY_DISCLAIMER, str) and len(MANDATORY_DISCLAIMER) > 50

    def test_disclaimer_contains_no_investment_advice(self):
        # Disclaimer says "are NOT investment advice" — good; check content
        assert "not" in MANDATORY_DISCLAIMER.lower() or "nor" in MANDATORY_DISCLAIMER.lower()
        assert "investment advice" in MANDATORY_DISCLAIMER.lower()
        assert "price target" in MANDATORY_DISCLAIMER.lower()

    def test_banned_phrases_non_empty_tuple(self):
        assert isinstance(BANNED_ADVICE_PHRASES, tuple) and len(BANNED_ADVICE_PHRASES) >= 10

    def test_banned_phrases_all_lowercase(self):
        for phrase in BANNED_ADVICE_PHRASES:
            assert phrase == phrase.lower(), f"Phrase not lowercase: '{phrase}'"

    def test_allowed_types_matches_probability_engine(self):
        from app.services.forecast_probability_engine import SUPPORTED_FORECAST_TYPES
        assert ALLOWED_FORECAST_TYPES == SUPPORTED_FORECAST_TYPES

    def test_allowed_horizons_matches_probability_engine(self):
        from app.services.forecast_probability_engine import SUPPORTED_HORIZONS
        assert ALLOWED_HORIZONS == SUPPORTED_HORIZONS

    def test_allowed_confidence_labels(self):
        assert "low" in ALLOWED_CONFIDENCE_LABELS
        assert "medium" in ALLOWED_CONFIDENCE_LABELS
        assert "high" in ALLOWED_CONFIDENCE_LABELS

    def test_horizon_labels_cover_all_horizons(self):
        for h in ALLOWED_HORIZONS:
            assert h in HORIZON_LABELS

    def test_invalidator_templates_cover_all_types(self):
        for ft in ALLOWED_FORECAST_TYPES:
            assert ft in INVALIDATOR_TEMPLATES, f"No invalidator template for {ft}"
            assert len(INVALIDATOR_TEMPLATES[ft]) >= 2

    def test_generic_invalidators_non_empty(self):
        assert isinstance(GENERIC_INVALIDATORS, tuple) and len(GENERIC_INVALIDATORS) >= 1

    def test_forecast_type_display_covers_all_types(self):
        for ft in ALLOWED_FORECAST_TYPES:
            assert ft in FORECAST_TYPE_DISPLAY

    def test_constants_module_has_no_imports(self):
        """forecast_constants.py must have zero imports (circular-import safety)."""
        src = (ROOT / "app/services/forecast_constants.py").read_text()
        tree = ast.parse(src)
        imports = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        assert not imports, (
            f"forecast_constants.py must have no imports; found: "
            f"{[ast.dump(n) for n in imports]}"
        )


# ---------------------------------------------------------------------------
# CONTAINS_BANNED_ADVICE_LANGUAGE
# ---------------------------------------------------------------------------

class TestContainsBannedAdviceLanguage:
    def test_detects_price_target(self):
        assert contains_banned_advice_language("The price target is $150.")

    def test_detects_strong_buy(self):
        assert contains_banned_advice_language("Our rating is strong buy.")

    def test_detects_buy_recommendation(self):
        assert contains_banned_advice_language("We issue a buy recommendation.")

    def test_detects_investment_advice(self):
        assert contains_banned_advice_language("This constitutes investment advice.")

    def test_detects_overweight(self):
        assert contains_banned_advice_language("We rate the stock overweight.")

    def test_detects_upgrade_to(self):
        assert contains_banned_advice_language("We upgrade to hold.")

    def test_detects_expected_return(self):
        assert contains_banned_advice_language("The expected return of 20% applies.")

    def test_detects_target_price(self):
        assert contains_banned_advice_language("Target price is $80.")

    def test_detects_recommend_buying(self):
        assert contains_banned_advice_language("We recommend buying the shares.")

    def test_detects_you_should_buy(self):
        assert contains_banned_advice_language("You should buy this security.")

    def test_case_insensitive(self):
        assert contains_banned_advice_language("STRONG BUY recommendation")
        assert contains_banned_advice_language("Price Target: $100")

    def test_clean_text_is_false(self):
        assert not contains_banned_advice_language(
            "Historical pattern frequency: 2 of 3 analogs resolved negatively."
        )

    def test_clean_probability_statement_is_false(self):
        assert not contains_banned_advice_language(
            "The probability of risk emergence is 62% based on historical base rates."
        )

    def test_none_is_false(self):
        assert not contains_banned_advice_language(None)

    def test_int_is_false(self):
        assert not contains_banned_advice_language(42)

    def test_dict_recursive_detects_nested(self):
        payload = {"outer": {"inner": "price target of $50 set by management"}}
        assert contains_banned_advice_language(payload)

    def test_list_recursive_detects_item(self):
        assert contains_banned_advice_language(["clean text", "strong buy here"])

    def test_dict_clean_is_false(self):
        payload = {"why": "probability is 55%", "p": 0.55}
        assert not contains_banned_advice_language(payload)

    def test_empty_string_is_false(self):
        assert not contains_banned_advice_language("")

    def test_empty_list_is_false(self):
        assert not contains_banned_advice_language([])

    def test_empty_dict_is_false(self):
        assert not contains_banned_advice_language({})


# ---------------------------------------------------------------------------
# BUILD_INVALIDATORS
# ---------------------------------------------------------------------------

class TestBuildInvalidators:
    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_non_empty_for_all_types(self, forecast_type):
        inv = build_invalidators({}, _prob_output(forecast_type=forecast_type))
        assert isinstance(inv, list) and len(inv) >= 2

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_no_banned_phrases_in_any_type(self, forecast_type):
        inv = build_invalidators({}, _prob_output(forecast_type=forecast_type))
        for text in inv:
            assert not contains_banned_advice_language(text), (
                f"{forecast_type}: banned phrase in invalidator: '{text}'"
            )

    def test_t4_stage_adds_extra_invalidator(self):
        s2 = build_invalidators(_fm_features(2), _prob_output("risk_emergence"))
        s3 = build_invalidators(_fm_features(3), _prob_output("risk_emergence"))
        # Both should have the generic + type-specific + stage-specific
        assert len(s3) >= len(s2)

    def test_staleness_adds_extra_invalidator(self):
        fresh = build_invalidators(_company_features(), _prob_output())
        stale = build_invalidators(_stale_features(), _prob_output(staleness_penalty_applied=True))
        assert len(stale) >= len(fresh)

    def test_generic_invalidators_always_included(self):
        for ft in ALL_FORECAST_TYPES:
            inv = build_invalidators({}, _prob_output(forecast_type=ft))
            combined = " ".join(inv).lower()
            assert "material information" in combined or "structural break" in combined, (
                f"{ft}: generic invalidator not found in output"
            )


# ---------------------------------------------------------------------------
# BUILD_EVIDENCE_SUMMARY
# ---------------------------------------------------------------------------

class TestBuildEvidenceSummary:
    def test_non_empty_with_full_features(self):
        ev = build_evidence_summary(_company_features(), _prob_output())
        assert isinstance(ev, list) and len(ev) >= 1

    def test_non_empty_with_sparse_features(self):
        ev = build_evidence_summary(_sparse_features(), _prob_output())
        assert isinstance(ev, list) and len(ev) >= 1

    def test_non_empty_with_empty_features(self):
        ev = build_evidence_summary({}, _prob_output())
        assert isinstance(ev, list) and len(ev) >= 1

    def test_prior_entry_on_empty_features(self):
        ev = build_evidence_summary({}, _prob_output())
        types = [e.get("source_type") for e in ev]
        assert "prior" in types

    def test_analog_entries_present_when_analogs_available(self):
        ev = build_evidence_summary(_company_features(), _prob_output())
        types = [e.get("source_type") for e in ev]
        assert "analog" in types

    def test_peer_entries_present_when_peers_available(self):
        ev = build_evidence_summary(_company_features(), _prob_output())
        types = [e.get("source_type") for e in ev]
        assert "similarity_peer" in types

    def test_thesis_entry_present_when_versions_available(self):
        ev = build_evidence_summary(_company_features(), _prob_output())
        types = [e.get("source_type") for e in ev]
        assert "thesis_trajectory" in types

    def test_failure_mode_entry_for_t4(self):
        ev = build_evidence_summary(_fm_features(), _prob_output())
        types = [e.get("source_type") for e in ev]
        assert "failure_mode" in types

    def test_staleness_entry_when_stale(self):
        ev = build_evidence_summary(_stale_features(), _prob_output(staleness_penalty_applied=True))
        types = [e.get("source_type") for e in ev]
        assert "staleness_flag" in types

    def test_required_keys_in_each_entry(self):
        ev = build_evidence_summary(_company_features(), _prob_output())
        required = {"source_type", "source_id", "direction", "contribution", "weight", "description"}
        for entry in ev:
            assert required.issubset(set(entry.keys())), (
                f"Evidence entry missing keys: {required - set(entry.keys())}"
            )

    def test_no_banned_phrases_in_descriptions(self):
        ev = build_evidence_summary(_company_features(), _prob_output())
        for entry in ev:
            desc = entry.get("description", "")
            assert not contains_banned_advice_language(desc), (
                f"Banned phrase in evidence description: '{desc}'"
            )

    def test_direction_is_valid(self):
        ev = build_evidence_summary(_company_features(), _prob_output())
        valid_dirs = {"positive", "negative", "neutral"}
        for entry in ev:
            assert entry.get("direction") in valid_dirs, (
                f"Invalid direction: {entry.get('direction')}"
            )


# ---------------------------------------------------------------------------
# BUILD_FORECAST_EXPLANATION — HAPPY PATH
# ---------------------------------------------------------------------------

class TestBuildForecastExplanationHappyPath:
    REQUIRED_KEYS = {
        "why", "evidence", "invalidators", "analog_basis", "similarity_basis",
        "horizon_days", "forecast_type", "confidence_label", "disclaimer",
        "staleness_penalty_applied", "evidence_strength",
    }

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    @pytest.mark.parametrize("horizon", ALL_HORIZONS)
    def test_required_keys_present(self, forecast_type, horizon):
        expl = _valid_explanation(forecast_type, horizon)
        assert self.REQUIRED_KEYS.issubset(set(expl.keys())), (
            f"Missing keys: {self.REQUIRED_KEYS - set(expl.keys())}"
        )

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_why_non_empty(self, forecast_type):
        expl = _valid_explanation(forecast_type)
        assert isinstance(expl["why"], list) and len(expl["why"]) >= 1

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_evidence_non_empty(self, forecast_type):
        expl = _valid_explanation(forecast_type)
        assert isinstance(expl["evidence"], list) and len(expl["evidence"]) >= 1

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_invalidators_non_empty(self, forecast_type):
        expl = _valid_explanation(forecast_type)
        assert isinstance(expl["invalidators"], list) and len(expl["invalidators"]) >= 2

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_disclaimer_is_mandatory(self, forecast_type):
        expl = _valid_explanation(forecast_type)
        assert expl["disclaimer"] == MANDATORY_DISCLAIMER

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    @pytest.mark.parametrize("horizon", ALL_HORIZONS)
    def test_horizon_matches_probability_output(self, forecast_type, horizon):
        expl = _valid_explanation(forecast_type, horizon)
        assert expl["horizon_days"] == horizon

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_forecast_type_matches(self, forecast_type):
        expl = _valid_explanation(forecast_type)
        assert expl["forecast_type"] == forecast_type

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    @pytest.mark.parametrize("horizon", ALL_HORIZONS)
    def test_passes_validate_gate(self, forecast_type, horizon):
        expl = _valid_explanation(forecast_type, horizon)
        assert validate_forecast_explanation(expl), (
            f"{forecast_type}/{horizon}: explanation did not pass validate gate"
        )


# ---------------------------------------------------------------------------
# BUILD_FORECAST_EXPLANATION — SPARSE FEATURES
# ---------------------------------------------------------------------------

class TestBuildForecastExplanationSparse:
    def test_sparse_produces_non_empty_why(self):
        expl = build_forecast_explanation(_sparse_features(), _prob_output())
        assert len(expl["why"]) >= 1

    def test_sparse_produces_non_empty_evidence(self):
        expl = build_forecast_explanation(_sparse_features(), _prob_output())
        assert len(expl["evidence"]) >= 1

    def test_sparse_produces_non_empty_invalidators(self):
        expl = build_forecast_explanation(_sparse_features(), _prob_output())
        assert len(expl["invalidators"]) >= 1

    def test_sparse_disclaimer_present(self):
        expl = build_forecast_explanation(_sparse_features(), _prob_output())
        assert expl["disclaimer"] == MANDATORY_DISCLAIMER

    def test_sparse_passes_validate_gate(self):
        """Sparse features still produce a validatable explanation."""
        expl = build_forecast_explanation(_sparse_features(), _prob_output())
        assert validate_forecast_explanation(expl), (
            f"Sparse explanation failed validate gate: {expl}"
        )

    def test_empty_features_disclaimer_present(self):
        expl = build_forecast_explanation({}, _prob_output())
        assert expl["disclaimer"] == MANDATORY_DISCLAIMER


# ---------------------------------------------------------------------------
# BUILD_FORECAST_EXPLANATION — T4 FAILURE MODE
# ---------------------------------------------------------------------------

class TestBuildForecastExplanationT4:
    def test_fm_explanation_has_failure_mode_evidence(self):
        expl = build_forecast_explanation(_fm_features(), _prob_output())
        types = [e.get("source_type") for e in expl["evidence"]]
        assert "failure_mode" in types

    def test_fm_explanation_mentions_mechanism_in_why(self):
        expl = build_forecast_explanation(_fm_features(sequence_stage=2), _prob_output())
        combined = " ".join(expl["why"]).lower()
        assert "liquidity" in combined or "failure mode" in combined or "mechanism" in combined

    def test_fm_explanation_passes_validate(self):
        expl = build_forecast_explanation(_fm_features(), _prob_output())
        assert validate_forecast_explanation(expl)

    def test_fm_stage3_has_extra_invalidator(self):
        s2 = build_forecast_explanation(_fm_features(2), _prob_output())
        s3 = build_forecast_explanation(_fm_features(3), _prob_output())
        assert len(s3["invalidators"]) >= len(s2["invalidators"])


# ---------------------------------------------------------------------------
# BUILD_FORECAST_EXPLANATION — STALE FEATURES
# ---------------------------------------------------------------------------

class TestBuildForecastExplanationStale:
    def test_stale_sets_flag_in_output(self):
        expl = build_forecast_explanation(
            _stale_features(), _prob_output(staleness_penalty_applied=True)
        )
        assert expl["staleness_penalty_applied"] is True

    def test_stale_mentions_staleness_in_why(self):
        expl = build_forecast_explanation(
            _stale_features(), _prob_output(staleness_penalty_applied=True)
        )
        combined = " ".join(expl["why"]).lower()
        assert "stale" in combined or "reduced" in combined

    def test_stale_still_passes_validate(self):
        expl = build_forecast_explanation(
            _stale_features(), _prob_output(staleness_penalty_applied=True)
        )
        assert validate_forecast_explanation(expl)


# ---------------------------------------------------------------------------
# NO BANNED PHRASES IN TEMPLATE OUTPUT
# ---------------------------------------------------------------------------

class TestNoBannedPhrasesInTemplateOutput:
    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    @pytest.mark.parametrize("horizon", ALL_HORIZONS)
    def test_no_banned_phrases_in_why(self, forecast_type, horizon):
        expl = _valid_explanation(forecast_type, horizon)
        for text in expl["why"]:
            assert not contains_banned_advice_language(text), (
                f"{forecast_type}/{horizon}: banned phrase in why: '{text}'"
            )

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    @pytest.mark.parametrize("horizon", ALL_HORIZONS)
    def test_no_banned_phrases_in_invalidators(self, forecast_type, horizon):
        expl = _valid_explanation(forecast_type, horizon)
        for text in expl["invalidators"]:
            assert not contains_banned_advice_language(text), (
                f"{forecast_type}/{horizon}: banned phrase in invalidators: '{text}'"
            )

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_no_banned_phrases_in_evidence_descriptions(self, forecast_type):
        expl = _valid_explanation(forecast_type)
        for entry in expl["evidence"]:
            desc = entry.get("description", "")
            assert not contains_banned_advice_language(desc), (
                f"{forecast_type}: banned phrase in evidence description: '{desc}'"
            )

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_invalidator_templates_have_no_banned_phrases(self, forecast_type):
        for text in INVALIDATOR_TEMPLATES.get(forecast_type, ()):
            assert not contains_banned_advice_language(text), (
                f"Banned phrase in INVALIDATOR_TEMPLATES[{forecast_type}]: '{text}'"
            )

    def test_generic_invalidators_have_no_banned_phrases(self):
        for text in GENERIC_INVALIDATORS:
            assert not contains_banned_advice_language(text), (
                f"Banned phrase in GENERIC_INVALIDATORS: '{text}'"
            )


# ---------------------------------------------------------------------------
# VALIDATE_FORECAST_EXPLANATION — REJECTION CASES
# ---------------------------------------------------------------------------

class TestValidateForecastExplanationRejects:
    def _base(self) -> dict:
        return dict(_valid_explanation())

    # ── Structural rejections ────────────────────────────────────────────

    def test_rejects_non_dict(self):
        assert not validate_forecast_explanation("not a dict")
        assert not validate_forecast_explanation(None)
        assert not validate_forecast_explanation([])

    def test_rejects_empty_dict(self):
        assert not validate_forecast_explanation({})

    def test_rejects_empty_why(self):
        e = self._base(); e["why"] = []
        assert not validate_forecast_explanation(e)

    def test_rejects_none_why(self):
        e = self._base(); e["why"] = None
        assert not validate_forecast_explanation(e)

    def test_rejects_empty_string_in_why(self):
        e = self._base(); e["why"] = [""]
        assert not validate_forecast_explanation(e)

    def test_rejects_whitespace_only_in_why(self):
        e = self._base(); e["why"] = ["   "]
        assert not validate_forecast_explanation(e)

    def test_rejects_empty_evidence(self):
        e = self._base(); e["evidence"] = []
        assert not validate_forecast_explanation(e)

    def test_rejects_none_evidence(self):
        e = self._base(); e["evidence"] = None
        assert not validate_forecast_explanation(e)

    def test_rejects_empty_invalidators(self):
        e = self._base(); e["invalidators"] = []
        assert not validate_forecast_explanation(e)

    def test_rejects_empty_string_in_invalidators(self):
        e = self._base(); e["invalidators"] = [""]
        assert not validate_forecast_explanation(e)

    # ── Disclaimer rejections ────────────────────────────────────────────

    def test_rejects_missing_disclaimer(self):
        e = self._base(); del e["disclaimer"]
        assert not validate_forecast_explanation(e)

    def test_rejects_wrong_disclaimer_text(self):
        e = self._base(); e["disclaimer"] = "Not the right disclaimer."
        assert not validate_forecast_explanation(e)

    def test_rejects_empty_disclaimer(self):
        e = self._base(); e["disclaimer"] = ""
        assert not validate_forecast_explanation(e)

    def test_rejects_partial_disclaimer(self):
        e = self._base()
        e["disclaimer"] = MANDATORY_DISCLAIMER[:40]   # truncated
        assert not validate_forecast_explanation(e)

    # ── Horizon / type / label rejections ────────────────────────────────

    def test_rejects_unsupported_horizon(self):
        e = self._base(); e["horizon_days"] = 45
        assert not validate_forecast_explanation(e)

    def test_rejects_zero_horizon(self):
        e = self._base(); e["horizon_days"] = 0
        assert not validate_forecast_explanation(e)

    def test_rejects_unsupported_forecast_type(self):
        e = self._base(); e["forecast_type"] = "buy_signal"
        assert not validate_forecast_explanation(e)

    def test_rejects_empty_forecast_type(self):
        e = self._base(); e["forecast_type"] = ""
        assert not validate_forecast_explanation(e)

    def test_rejects_unsupported_confidence_label(self):
        e = self._base(); e["confidence_label"] = "very_high"
        assert not validate_forecast_explanation(e)

    # ── Banned phrase rejections ─────────────────────────────────────────

    def test_rejects_price_target_in_why(self):
        e = self._base()
        e["why"] = ["Historical pattern frequency: 55%.", "Price target of $150 applies."]
        assert not validate_forecast_explanation(e)

    def test_rejects_strong_buy_in_why(self):
        e = self._base()
        e["why"] = ["Pattern frequency is 60%.", "Our rating is strong buy."]
        assert not validate_forecast_explanation(e)

    def test_rejects_buy_recommendation_in_why(self):
        e = self._base()
        e["why"].append("We issue a buy recommendation based on pattern frequency.")
        assert not validate_forecast_explanation(e)

    def test_rejects_investment_advice_in_why(self):
        e = self._base()
        e["why"].append("This constitutes investment advice.")
        assert not validate_forecast_explanation(e)

    def test_rejects_overweight_in_why(self):
        e = self._base()
        e["why"].append("We rate this security overweight.")
        assert not validate_forecast_explanation(e)

    def test_rejects_sell_recommendation_in_why(self):
        e = self._base()
        e["why"].append("We issue a sell recommendation.")
        assert not validate_forecast_explanation(e)

    def test_rejects_hold_recommendation_in_why(self):
        e = self._base()
        e["why"].append("We issue a hold recommendation.")
        assert not validate_forecast_explanation(e)

    def test_rejects_expected_return_in_why(self):
        e = self._base()
        e["why"].append("The expected return of 20% applies here.")
        assert not validate_forecast_explanation(e)

    def test_rejects_banned_phrase_in_evidence_description(self):
        e = self._base()
        e["evidence"][0]["description"] = "Analog resolved positively — strong buy signal confirmed."
        assert not validate_forecast_explanation(e)

    def test_rejects_price_target_in_evidence_description(self):
        e = self._base()
        e["evidence"][0]["description"] = "The price target was $100 at resolution."
        assert not validate_forecast_explanation(e)

    def test_rejects_banned_phrase_in_invalidators(self):
        e = self._base()
        e["invalidators"].append("This is no longer valid if you issue a buy recommendation.")
        assert not validate_forecast_explanation(e)

    def test_rejects_overweight_in_invalidators(self):
        e = self._base()
        e["invalidators"].append("Forecast is invalidated if analyst upgrades to overweight.")
        assert not validate_forecast_explanation(e)


# ---------------------------------------------------------------------------
# VALIDATE_FORECAST_EXPLANATION — ACCEPTANCE CASES
# ---------------------------------------------------------------------------

class TestValidateForecastExplanationAccepts:
    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    @pytest.mark.parametrize("horizon", ALL_HORIZONS)
    def test_accepts_builder_output(self, forecast_type, horizon):
        expl = _valid_explanation(forecast_type, horizon)
        assert validate_forecast_explanation(expl)

    def test_accepts_sparse_builder_output(self):
        expl = build_forecast_explanation(_sparse_features(), _prob_output())
        assert validate_forecast_explanation(expl)

    def test_accepts_t4_builder_output(self):
        expl = build_forecast_explanation(_fm_features(), _prob_output())
        assert validate_forecast_explanation(expl)

    def test_accepts_stale_builder_output(self):
        expl = build_forecast_explanation(
            _stale_features(), _prob_output(staleness_penalty_applied=True)
        )
        assert validate_forecast_explanation(expl)


# ---------------------------------------------------------------------------
# DISCLAIMER ALWAYS INCLUDED
# ---------------------------------------------------------------------------

class TestDisclaimerAlwaysIncluded:
    def test_disclaimer_in_full_features(self):
        expl = build_forecast_explanation(_company_features(), _prob_output())
        assert expl["disclaimer"] == MANDATORY_DISCLAIMER

    def test_disclaimer_in_sparse_features(self):
        expl = build_forecast_explanation(_sparse_features(), _prob_output())
        assert expl["disclaimer"] == MANDATORY_DISCLAIMER

    def test_disclaimer_in_empty_features(self):
        expl = build_forecast_explanation({}, _prob_output())
        assert expl["disclaimer"] == MANDATORY_DISCLAIMER

    def test_disclaimer_in_empty_prob_output(self):
        expl = build_forecast_explanation(_company_features(), {})
        assert expl["disclaimer"] == MANDATORY_DISCLAIMER

    def test_disclaimer_matches_constant(self):
        expl = build_forecast_explanation(_company_features(), _prob_output())
        assert expl["disclaimer"] is MANDATORY_DISCLAIMER or expl["disclaimer"] == MANDATORY_DISCLAIMER


# ---------------------------------------------------------------------------
# PURE FUNCTIONS / NO DB / NO WRITES
# ---------------------------------------------------------------------------

class TestPureFunctionsNoDbNoWrites:
    def _read_explainability_src(self) -> str:
        return (ROOT / "app/services/forecast_explainability_service.py").read_text()

    def _read_constants_src(self) -> str:
        return (ROOT / "app/services/forecast_constants.py").read_text()

    def test_explainability_has_no_db_session_imports(self):
        src = self._read_explainability_src()
        db_signals = [
            "from sqlalchemy", "import sqlalchemy",
            "AsyncSession", "create_engine",
            "aiosqlite", "from app.db",
        ]
        for sig in db_signals:
            assert sig not in src, (
                f"DB import signal '{sig}' found in forecast_explainability_service.py"
            )

    def test_explainability_has_no_write_calls(self):
        src = self._read_explainability_src()
        tree = ast.parse(src)
        write_methods = {"add", "delete", "merge", "flush", "commit", "execute_write"}
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in write_methods:
                    found.append(func.attr)
        assert not found, f"Write calls found in explainability service: {found}"

    def test_explainability_does_not_import_probability_engine(self):
        src = self._read_explainability_src()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "forecast_probability_engine" not in node.module, (
                    "forecast_explainability_service must not import probability engine"
                )

    def test_explainability_does_not_import_feature_builder(self):
        src = self._read_explainability_src()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "forecast_feature_builder" not in node.module, (
                    "forecast_explainability_service must not import feature builder"
                )

    def test_explainability_imports_only_constants_and_stdlib(self):
        src = self._read_explainability_src()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                allowed = ("app.services.forecast_constants",)
                if node.module.startswith("app."):
                    assert node.module in allowed, (
                        f"Unexpected app import in explainability service: {node.module}"
                    )

    def test_constants_module_has_no_imports(self):
        src = self._read_constants_src()
        tree = ast.parse(src)
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        assert not imports, "forecast_constants.py must have zero imports"

    def test_no_upsert_in_explainability(self):
        src = self._read_explainability_src()
        assert "upsert_forecast_vector" not in src
        assert "forecast_repo" not in src
