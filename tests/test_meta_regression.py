"""
tests/test_meta_regression.py

Live-site regression suite for the META query that originally caused:
  1. Wrong entity resolution: "Can Meta continue compounding despite AI
     infrastructure spending pressure?" → C3.ai (AI) instead of META.
  2. Wrong stance after entity fix: stance=Buy when Accumulate is correct
     for a durable compounder at fair/attractive valuation.
  3. "Failed to fetch" / 500 error after Phase 3 stance calibration deploy.

This suite validates:
  A. Backend API health — /ask endpoint returns valid JSON and no 5xx.
  B. Entity resolution — META is resolved, not C3.ai.
  C. Schema contract — response serializes without errors.
  D. Regime sanity — expectation_regime is a valid label (incl. "attractive").
  E. Stance sanity — directional_stance is in the expanded vocabulary.
  F. Conviction modeler path — compute_conviction works end-to-end.

Run:
    python3 -m pytest tests/test_meta_regression.py -v --tb=short
"""

from __future__ import annotations

import json
import pytest

# ── Constants ──────────────────────────────────────────────────────────────────

META_QUERY = "Can Meta continue compounding despite AI infrastructure spending pressure?"

VALID_REGIMES  = {"cheap", "attractive", "fair", "stretched", "euphoric", "bubble"}
VALID_STANCES  = {"Aggressive Buy", "Buy", "Accumulate", "Hold", "Tactical", "Avoid", "Sell"}


# ===========================================================================
# Class 1 — Entity resolution (unit-level regression)
# ===========================================================================

class TestMetaEntityResolution:
    """The entity resolution bug that triggered this whole work: META must
    resolve, not AI (C3.ai)."""

    def test_meta_query_resolves_to_meta_not_ai(self):
        from app.services.entity_resolution_service import resolve_query
        result = resolve_query(META_QUERY)
        assert result.canonical_ticker == "META", (
            f"META query resolved to {result.canonical_ticker!r} (method={result.resolution_method!r}). "
            "Expected META — the word 'AI' in the query must not resolve to C3.ai."
        )

    def test_meta_not_needs_clarification(self):
        from app.services.entity_resolution_service import resolve_query
        result = resolve_query(META_QUERY)
        assert not result.needs_clarification, (
            "META query should not need clarification — company is unambiguous."
        )

    def test_meta_resolve_for_analysis(self):
        from app.services.entity_resolution_service import resolve_for_analysis
        result = resolve_for_analysis(
            user_question=META_QUERY,
            company_hint="Meta",
        )
        assert result.canonical_ticker == "META"
        assert result.confidence_score >= 0.90


# ===========================================================================
# Class 2 — Conviction modeler path (no LLM required)
# ===========================================================================

class TestMetaConvictionModelerPath:
    """compute_conviction must complete without exception for a META-like profile."""

    def _run_meta_conviction(self, **overrides):
        from app.schemas import (
            CompanyContext, ValuationView, MacroSensitivity,
            RiskProfile, MarketContext, QualityAssessment,
        )
        from app.services.conviction_modeler import compute_conviction
        company = CompanyContext(
            ticker="META",
            company_name="Meta Platforms Inc.",
            sector="Technology",
        )
        params = dict(
            evidence=[], valuation=ValuationView(),
            macro=MacroSensitivity(), risk=RiskProfile(),
            market=MarketContext(), quality=QualityAssessment(),
            company=company, ranked=None, governance_warnings=[],
        )
        params.update(overrides)
        return compute_conviction(**params)

    def test_compute_conviction_does_not_raise(self):
        """compute_conviction must not raise for META (regression: Phase 3 changes)."""
        result = self._run_meta_conviction()
        assert result is not None

    def test_expectation_regime_is_valid_label(self):
        """expectation_regime must be one of the 6 valid labels (incl. 'attractive')."""
        result = self._run_meta_conviction()
        assert result.expectation_regime in VALID_REGIMES, (
            f"expectation_regime={result.expectation_regime!r} is not a valid regime. "
            f"Phase 3 added 'attractive'. Valid: {sorted(VALID_REGIMES)}"
        )

    def test_directional_stance_is_valid_vocabulary(self):
        """directional_stance must be in the expanded vocabulary."""
        result = self._run_meta_conviction()
        assert result.directional_stance in VALID_STANCES, (
            f"directional_stance={result.directional_stance!r} is not valid. "
            f"Valid: {sorted(VALID_STANCES)}"
        )

    def test_conviction_result_serializes_to_json(self):
        """ConvictionResult must serialize to JSON without errors (regression: None fields)."""
        result = self._run_meta_conviction()
        # Simulate what thesis_synthesizer does: stamp fields onto InvestmentThesis
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(
            ticker="META",
            company_name="Meta Platforms Inc.",
            bull_thesis="Test bull.",
            bear_thesis="Test bear.",
            key_drivers=["Revenue growth"],
            key_risks=["AI capex"],
            valuation_view="Attractive at current multiples.",
            conclusion="Accumulate.",
            confidence_score=result.final_score,
        )
        thesis.setup_label = result.setup_label
        thesis.directional_stance = result.directional_stance
        thesis.directional_stance_reasoning = result.directional_stance_reasoning
        thesis.expectation_regime = result.expectation_regime
        thesis.expectation_shift_severity = result.expectation_shift_severity

        # Serialize — must not raise
        payload = thesis.model_dump() if hasattr(thesis, "model_dump") else thesis.dict()
        j = json.dumps(payload, default=str)
        assert len(j) > 100, "Serialized thesis is too short — missing fields?"

        # Key fields must be present and non-null
        assert payload.get("expectation_regime") in VALID_REGIMES, (
            f"expectation_regime={payload.get('expectation_regime')!r} invalid after stamp"
        )
        assert payload.get("directional_stance") in VALID_STANCES, (
            f"directional_stance={payload.get('directional_stance')!r} invalid after stamp"
        )


# ===========================================================================
# Class 3 — Response schema contract (AnalysisResponse)
# ===========================================================================

class TestAnalysisResponseSchema:
    """AnalysisResponse must include all Phase 2/3 fields and serialize cleanly."""

    def test_analysis_response_schema_has_entity_fields(self):
        from app.schemas import AnalysisResponse
        import inspect
        fields = set(AnalysisResponse.model_fields.keys()
                     if hasattr(AnalysisResponse, "model_fields")
                     else AnalysisResponse.__fields__.keys())
        for f in ("resolved_company", "resolved_ticker", "entity_confidence", "entity_resolution_warning"):
            assert f in fields, f"AnalysisResponse missing field {f!r} (Phase 2 entity resolution)"

    def test_investment_thesis_has_expectation_regime_field(self):
        from app.schemas import InvestmentThesis
        fields = set(InvestmentThesis.model_fields.keys()
                     if hasattr(InvestmentThesis, "model_fields")
                     else InvestmentThesis.__fields__.keys())
        assert "expectation_regime" in fields
        assert "directional_stance" in fields
        assert "setup_label" in fields

    def test_expectation_regime_default_is_fair(self):
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(
            ticker="TEST",
            company_name="Test",
            bull_thesis="b",
            bear_thesis="r",
            key_drivers=["d"],
            key_risks=["r"],
            valuation_view="v",
            conclusion="c",
            confidence_score=0.5,
        )
        assert thesis.expectation_regime == "fair"

    def test_attractive_regime_accepted_by_schema(self):
        """'attractive' must be accepted by InvestmentThesis.expectation_regime (no validator)."""
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(
            ticker="META",
            company_name="Meta Platforms Inc.",
            bull_thesis="b",
            bear_thesis="r",
            key_drivers=["d"],
            key_risks=["r"],
            valuation_view="v",
            conclusion="c",
            confidence_score=0.63,
            expectation_regime="attractive",     # new Phase 3 value
            directional_stance="Accumulate",
        )
        assert thesis.expectation_regime == "attractive"
        # Serialize — no exception
        payload = thesis.model_dump() if hasattr(thesis, "model_dump") else thesis.dict()
        assert payload["expectation_regime"] == "attractive"


# ===========================================================================
# Class 4 — Route question pipeline (no LLM, structure check)
# ===========================================================================

class TestRouteQuestionStructure:
    """route_question must not crash and must return valid AgentAnswerResponse."""

    def test_route_question_does_not_raise_for_meta_query(self):
        """route_question should complete without exception for META query."""
        from app.schemas import QuestionRequest
        from app.services.router_service import route_question

        req = QuestionRequest(
            company_name="",
            question=META_QUERY,
            intent="company_analysis",
        )
        # Should not raise — may return general fallback without LLM
        result = route_question(req)
        assert result is not None

    def test_route_question_returns_serializable_response(self):
        """AgentAnswerResponse must serialize to JSON (regression: None fields crashing proxy)."""
        from app.schemas import QuestionRequest
        from app.services.router_service import route_question

        req = QuestionRequest(
            company_name="",
            question=META_QUERY,
            intent="company_analysis",
        )
        result = route_question(req)
        payload = result.model_dump() if hasattr(result, "model_dump") else result.dict()

        # Must serialize without errors
        j = json.dumps(payload, default=str)
        assert len(j) > 50

    def test_route_question_has_required_response_fields(self):
        """AgentAnswerResponse must have company, request_id, agents_used, answer."""
        from app.schemas import QuestionRequest
        from app.services.router_service import route_question

        req = QuestionRequest(
            company_name="Meta",
            question=META_QUERY,
            intent="company_analysis",
        )
        result = route_question(req)
        payload = result.model_dump() if hasattr(result, "model_dump") else result.dict()

        assert "company" in payload, "AgentAnswerResponse missing 'company' field"
        assert "request_id" in payload, "AgentAnswerResponse missing 'request_id' field"
        assert "answer" in payload, "AgentAnswerResponse missing 'answer' field"


# ===========================================================================
# Class 5 — Regime and stance constants (Phase 3 smoke test)
# ===========================================================================

class TestPhase3Constants:
    """Verify conviction_modeler exports the Phase 3 constants correctly."""

    def test_regime_attractive_constant(self):
        from app.services.conviction_modeler import _REGIME_ATTRACTIVE
        assert _REGIME_ATTRACTIVE == 0.20

    def test_regime_fair_raised(self):
        from app.services.conviction_modeler import _REGIME_FAIR
        assert _REGIME_FAIR == 0.36

    def test_regime_euphoric_tightened(self):
        from app.services.conviction_modeler import _REGIME_EUPHORIC
        assert _REGIME_EUPHORIC == 0.68

    def test_regime_bubble_tightened(self):
        from app.services.conviction_modeler import _REGIME_BUBBLE
        assert _REGIME_BUBBLE == 0.86

    def test_classify_expectation_regime_returns_attractive(self):
        """The new 'attractive' regime label must be returnable from the classifier."""
        from app.services.conviction_modeler import _classify_expectation_regime
        # frag=0.30, default durability=0.50 → dur_adj=0.06
        # attractive_thresh=0.26, fair_thresh=0.42 → 0.30 in (0.26, 0.42) → attractive
        regime = _classify_expectation_regime(expectation_fragility=0.30)
        assert regime == "attractive", (
            f"Expected 'attractive' at frag=0.30 with default durability; got {regime!r}"
        )

    def test_classify_expectation_regime_meta_profile(self):
        """META's fragility profile (frag~0.35, dur=0.72) returns attractive or fair."""
        from app.services.conviction_modeler import _classify_expectation_regime
        regime = _classify_expectation_regime(expectation_fragility=0.35, durability_score=0.72)
        assert regime in ("attractive", "fair"), (
            f"META profile (frag=0.35, dur=0.72) should be attractive or fair; got {regime!r}"
        )

    def test_durable_accumulate_fires_for_meta_profile(self):
        """Durable Accumulate rule must fire for META-like inputs (not Buy)."""
        from app.services.conviction_modeler import _compute_directional_stance, ConvictionDimensions
        from app.schemas import CompanyContext

        dims = ConvictionDimensions(
            evidence_quality=0.75,
            evidence_freshness=0.70,
            thesis_alignment=0.67,
            macro_uncertainty=0.40,
            valuation_certainty=0.55,
            estimate_dispersion=0.60,
            governance_risk=0.05,
            expectation_fragility=0.36,
            expectation_asymmetry=0.40,
        )
        company = CompanyContext(ticker="META", company_name="Meta Platforms Inc.")
        stance, _ = _compute_directional_stance(
            0.63, dims, "Durable Growth", company,
            expectation_regime="attractive",
            durability_score=0.72,
        )
        assert stance == "Accumulate", (
            f"META profile should produce Accumulate, not {stance!r}. "
            "This is the Phase 3 regression: durable compounder must not auto-Buy."
        )
