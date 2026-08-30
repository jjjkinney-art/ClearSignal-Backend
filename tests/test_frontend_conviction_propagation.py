"""
tests/test_frontend_conviction_propagation.py
Phase 4 — Frontend/API Propagation Regression Tests

Validates that conviction fields survive the full backend serialization path
and that the frontend extraction/rendering layer is correctly wired.

Tests cover:
1.  API payload contains all conviction fields after model_dump()
2.  what_increases_conviction is non-empty and company-specific
3.  conviction_dimensions has all 7 keys with float values
4.  confidence_score is NOT stuck at 0.65
5.  confidence_reasoning is company-specific (not boilerplate)
6.  router_service serializes thesis_dict with conviction fields
7.  Pre-response logging marker is in router_service source
8.  Frontend type interface includes new fields (source audit)
9.  Frontend extractInvestmentThesis maps all conviction fields (source audit)
10. InvestmentThesisView renders what_increases_conviction (source audit)
"""

from __future__ import annotations

import inspect
import json
import pathlib
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_full_thesis(
    ticker: str = "NVDA",
    confidence_score: float = 0.72,
    what_increases_conviction: str = "",
    conviction_dimensions: dict | None = None,
    confidence_reasoning: str = "",
) -> "Any":
    """Build a fully-populated InvestmentThesis with conviction fields."""
    from app.schemas import InvestmentThesis

    return InvestmentThesis(
        ticker=ticker,
        company_name=f"{ticker} Corp",
        direct_answer="Direct answer text.",
        bull_thesis="Bull thesis text.",
        bear_thesis="Bear thesis text.",
        confidence_score=confidence_score,
        confidence_reasoning=confidence_reasoning or (
            f"{ticker} revenue trajectory is well-evidenced; "
            "hyperscaler CapEx guidance remains the primary unresolved variable."
        ),
        what_increases_conviction=what_increases_conviction or (
            f"Clarity on {ticker} hyperscaler CapEx guidance for H2 2026 would "
            "resolve the primary uncertainty — that data point determines whether "
            "the revenue runway extends or plateaus."
        ),
        conviction_dimensions=conviction_dimensions or {
            "evidence_quality": 0.75,
            "evidence_freshness": 0.80,
            "thesis_alignment": 0.70,
            "macro_uncertainty": 0.40,
            "valuation_certainty": 0.65,
            "estimate_dispersion": 0.35,
            "governance_risk": 0.15,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# Class 1: API payload serialization
# ══════════════════════════════════════════════════════════════════════════════

class TestApiPayloadSerialization:
    """Verify conviction fields survive model_dump() → JSON serialization."""

    def test_model_dump_includes_what_increases_conviction(self):
        """what_increases_conviction must be in model_dump() output."""
        thesis = _make_full_thesis()
        d = thesis.model_dump()
        assert "what_increases_conviction" in d, (
            "what_increases_conviction missing from model_dump() — "
            "field will not appear in API response"
        )

    def test_model_dump_includes_conviction_dimensions(self):
        """conviction_dimensions must be in model_dump() output."""
        thesis = _make_full_thesis()
        d = thesis.model_dump()
        assert "conviction_dimensions" in d, (
            "conviction_dimensions missing from model_dump()"
        )

    def test_model_dump_conviction_dimensions_has_7_keys(self):
        """Serialized conviction_dimensions must have exactly 7 keys."""
        thesis = _make_full_thesis()
        d = thesis.model_dump()
        dims = d["conviction_dimensions"]
        assert len(dims) == 7, f"Expected 7 dimension keys, got {len(dims)}: {list(dims.keys())}"

    def test_model_dump_what_increases_conviction_is_non_empty(self):
        """what_increases_conviction must not be empty string in serialized output."""
        thesis = _make_full_thesis()
        d = thesis.model_dump()
        assert d["what_increases_conviction"], (
            "what_increases_conviction is empty string in model_dump()"
        )

    def test_json_roundtrip_preserves_conviction_fields(self):
        """Conviction fields survive json.dumps/loads (simulating HTTP response)."""
        thesis = _make_full_thesis(confidence_score=0.74)
        d = thesis.model_dump()
        # Simulate HTTP serialization
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        assert "what_increases_conviction" in deserialized
        assert "conviction_dimensions" in deserialized
        assert deserialized["confidence_score"] == pytest.approx(0.74)
        assert len(deserialized["conviction_dimensions"]) == 7

    def test_confidence_score_not_stuck_at_0_65(self):
        """confidence_score in payload must not always be 0.65."""
        # Test several scenarios
        scores = [0.45, 0.62, 0.74, 0.81]
        for score in scores:
            thesis = _make_full_thesis(confidence_score=score)
            d = thesis.model_dump()
            assert abs(d["confidence_score"] - 0.65) > 0.01 or abs(score - 0.65) < 0.01, (
                f"confidence_score {score} was corrupted to {d['confidence_score']} in model_dump()"
            )
            assert d["confidence_score"] == pytest.approx(score, abs=0.001), (
                f"Expected {score:.3f}, got {d['confidence_score']:.3f}"
            )

    def test_all_conviction_dimension_values_are_floats(self):
        """All conviction_dimensions values in payload must be floats."""
        thesis = _make_full_thesis()
        d = thesis.model_dump()
        for key, val in d["conviction_dimensions"].items():
            assert isinstance(val, float), f"{key} is {type(val)}, expected float"
            assert 0.0 <= val <= 1.0, f"{key}={val} out of [0,1]"


# ══════════════════════════════════════════════════════════════════════════════
# Class 2: Router service serialization
# ══════════════════════════════════════════════════════════════════════════════

class TestRouterServiceSerialization:
    """Verify router_service includes conviction fields in the thesis_dict it returns."""

    def test_pre_response_logging_in_router_source(self):
        """router_service must have BACKEND_FINAL_RESPONSE log marker at serialization point."""
        import app.services.router_service as rs
        src = inspect.getsource(rs)
        assert "BACKEND_FINAL_RESPONSE" in src, (
            "[BACKEND_FINAL_RESPONSE] log marker not found in router_service — "
            "Phase 5g renamed from PRE_RESPONSE_CONFIDENCE to BACKEND_FINAL_RESPONSE"
        )

    def test_pre_response_log_includes_conviction_fields(self):
        """BACKEND_FINAL_RESPONSE log must include conviction fields for truth-path verification."""
        import app.services.router_service as rs
        src = inspect.getsource(rs)
        assert "conviction_dims" in src or "has_conviction_dimensions" in src, (
            "conviction_dims field not found in router_service — "
            "required for BACKEND_FINAL_RESPONSE truth-path logging"
        )
        assert "setup_label" in src, (
            "setup_label not logged in router_service BACKEND_FINAL_RESPONSE"
        )
        assert "fragility_mult" in src or "fragility_multiplier_applied" in src, (
            "fragility multiplier not logged in router_service BACKEND_FINAL_RESPONSE"
        )

    def test_thesis_dict_built_from_model_dump(self):
        """router_service must serialize thesis via model_dump()."""
        import app.services.router_service as rs
        src = inspect.getsource(rs._run_investment_pipeline)
        assert "model_dump" in src, (
            "thesis_dict not built via model_dump() — conviction fields may be lost"
        )

    def test_answer_key_is_investment_thesis(self):
        """Response must nest thesis_dict under 'investment_thesis' key."""
        import app.services.router_service as rs
        src = inspect.getsource(rs._run_investment_pipeline)
        assert '"investment_thesis"' in src or "'investment_thesis'" in src, (
            "answer key 'investment_thesis' not found in _run_investment_pipeline"
        )

    def test_thesis_dict_simulation_has_conviction_fields(self):
        """Simulated thesis_dict (as router returns it) includes all conviction fields."""
        thesis = _make_full_thesis()
        try:
            thesis_dict = thesis.model_dump()
        except Exception:
            thesis_dict = thesis.dict()

        answer = {"investment_thesis": thesis_dict}
        investment_thesis = answer["investment_thesis"]
        assert "what_increases_conviction" in investment_thesis
        assert "conviction_dimensions" in investment_thesis
        assert investment_thesis["what_increases_conviction"], "what_increases_conviction is empty"
        assert investment_thesis["conviction_dimensions"], "conviction_dimensions is empty"


# ══════════════════════════════════════════════════════════════════════════════
# Class 3: Frontend type interface audit (source inspection)
# ══════════════════════════════════════════════════════════════════════════════

class TestFrontendTypeInterface:
    """Verify the frontend TypeScript interface includes conviction fields."""

    def _get_frontend_source(self) -> str:
        path = (
            pathlib.Path(__file__).parent.parent
            / "Ai-Intelligence-interface/frontend_cinematic/app/(product)/analyze/page.tsx"
        )
        if not path.is_file():
            pytest.skip("frontend repository is tested independently and is not checked out")
        return path.read_text()

    def test_investment_thesis_state_has_what_increases_conviction(self):
        """InvestmentThesisState interface must declare whatIncreasesConviction."""
        src = self._get_frontend_source()
        assert "whatIncreasesConviction" in src, (
            "whatIncreasesConviction not in InvestmentThesisState — "
            "frontend type is missing the conviction field"
        )

    def test_investment_thesis_state_has_conviction_dimensions(self):
        """InvestmentThesisState interface must declare convictionDimensions."""
        src = self._get_frontend_source()
        assert "convictionDimensions" in src, (
            "convictionDimensions not in InvestmentThesisState"
        )

    def test_extract_reads_what_increases_conviction(self):
        """extractInvestmentThesis must read t.what_increases_conviction from the API response."""
        src = self._get_frontend_source()
        assert "what_increases_conviction" in src, (
            "Frontend never reads what_increases_conviction from API response"
        )

    def test_extract_reads_conviction_dimensions(self):
        """extractInvestmentThesis must read t.conviction_dimensions from the API response."""
        src = self._get_frontend_source()
        assert "conviction_dimensions" in src, (
            "Frontend never reads conviction_dimensions from API response"
        )

    def test_frontend_logs_live_confidence_audit(self):
        """Frontend must emit [LIVE_CONFIDENCE_AUDIT] devLog for end-to-end observability."""
        src = self._get_frontend_source()
        assert "LIVE_CONFIDENCE_AUDIT" in src, (
            "Frontend does not log [LIVE_CONFIDENCE_AUDIT] — "
            "Phase 5f end-to-end confidence truth path observability missing"
        )

    def test_frontend_logs_conviction_dims_count(self):
        """Frontend devLog must record dims_count / conviction dimensions."""
        src = self._get_frontend_source()
        # Phase 5f renamed the log field from conviction_dims_count to dims_count
        assert "dims_count" in src or "conviction_dims_count" in src, (
            "Frontend devLog does not record conviction dimension count"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 4: Frontend rendering audit
# ══════════════════════════════════════════════════════════════════════════════

class TestFrontendRendering:
    """Verify InvestmentThesisView renders conviction fields."""

    def _get_frontend_source(self) -> str:
        path = (
            pathlib.Path(__file__).parent.parent
            / "Ai-Intelligence-interface/frontend_cinematic/app/(product)/analyze/page.tsx"
        )
        if not path.is_file():
            pytest.skip("frontend repository is tested independently and is not checked out")
        return path.read_text()

    def test_what_increases_conviction_rendered_in_view(self):
        """InvestmentThesisView must render data.whatIncreasesConviction."""
        src = self._get_frontend_source()
        assert "data.whatIncreasesConviction" in src, (
            "InvestmentThesisView does not render whatIncreasesConviction — "
            "field is extracted but never displayed"
        )

    def test_what_increases_conviction_section_has_label(self):
        """UI must show a readable label for the conviction section."""
        src = self._get_frontend_source()
        assert "What Would Increase Conviction" in src, (
            "No 'What Would Increase Conviction' section label found in frontend"
        )

    def test_conviction_debug_panel_in_dev_mode(self):
        """Dev-mode conviction debug panel must be present (gated by DEV flag)."""
        src = self._get_frontend_source()
        assert "Conviction Debug" in src, (
            "Dev-mode conviction debug panel not found in InvestmentThesisView"
        )

    def test_conviction_debug_shows_dimension_scores(self):
        """Dev conviction panel must render dimension scores from convictionDimensions."""
        src = self._get_frontend_source()
        assert "convictionDimensions" in src, (
            "Conviction debug panel does not render convictionDimensions"
        )

    def test_pm_catalyst_badge_on_conviction_section(self):
        """What Would Increase Conviction section must have PM Catalyst badge."""
        src = self._get_frontend_source()
        assert "PM Catalyst" in src, (
            "PM Catalyst badge missing from conviction section"
        )

    def test_confidence_score_displayed_as_percentage(self):
        """Frontend must display confidence_score as a percentage (not raw float)."""
        src = self._get_frontend_source()
        # ConfidenceMeter uses pct = Math.round(score * 100)
        assert "Math.round" in src and "* 100" in src, (
            "Frontend does not convert confidence_score to percentage"
        )

    def test_conviction_source_indicator_in_debug(self):
        """Dev panel must show conviction_modeler vs fallback source indicator."""
        src = self._get_frontend_source()
        assert "conviction_modeler" in src, (
            "Conviction source indicator not in dev debug panel"
        )
        # Phase 5f: renamed from "legacy_fallback" to "llm_raw_preserved" for clarity
        assert "llm_raw_preserved" in src or "legacy_fallback" in src, (
            "Fallback source indicator not in dev debug panel"
        )

    def test_no_hardcoded_65_percent_confidence(self):
        """Frontend must not have any hardcoded '65%' confidence string."""
        src = self._get_frontend_source()
        # Check that 65% never appears as a literal fallback in the rendering
        # (it's fine in comments or conditional thresholds, but not as a display value)
        import re
        # Look for '65%' as a display string (inside JSX or a string literal)
        hardcoded = re.findall(r'["\']65%["\']|>\s*65%\s*<', src)
        assert not hardcoded, (
            f"Hardcoded '65%' confidence string found in frontend: {hardcoded}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 5: End-to-end conviction field round-trip
# ══════════════════════════════════════════════════════════════════════════════

class TestConvictionFieldRoundTrip:
    """Verify that conviction fields survive the full backend→frontend data path."""

    def test_full_roundtrip_conviction_fields_preserved(self):
        """thesis → model_dump() → answer dict → simulated frontend extraction."""
        thesis = _make_full_thesis(
            ticker="NVDA",
            confidence_score=0.73,
            what_increases_conviction=(
                "Clarity on hyperscaler CapEx guidance for H2 2026 would be the single "
                "biggest conviction driver — that data point determines whether the "
                "data-center revenue runway extends or plateaus."
            ),
            conviction_dimensions={
                "evidence_quality": 0.75,
                "evidence_freshness": 0.82,
                "thesis_alignment": 0.71,
                "macro_uncertainty": 0.38,
                "valuation_certainty": 0.64,
                "estimate_dispersion": 0.33,
                "governance_risk": 0.12,
            },
        )

        # 1. Backend serializes via model_dump
        thesis_dict = thesis.model_dump()

        # 2. Router wraps in AgentAnswerResponse.answer
        answer = {"investment_thesis": thesis_dict}

        # 3. Frontend extracts from answer["investment_thesis"]
        it = answer["investment_thesis"]

        # 4. Verify all conviction fields are present and correct
        assert it["confidence_score"] == pytest.approx(0.73)
        assert abs(it["confidence_score"] - 0.65) > 0.05, "confidence_score stuck at 0.65!"
        assert it["what_increases_conviction"] != "", "what_increases_conviction is empty"
        assert "hyperscaler" in it["what_increases_conviction"].lower(), (
            "Company-specific content lost in round-trip"
        )
        assert len(it["conviction_dimensions"]) == 7, (
            f"Expected 7 dims, got {len(it['conviction_dimensions'])}"
        )
        assert it["conviction_dimensions"]["evidence_quality"] == pytest.approx(0.75)

    def test_different_tickers_produce_different_conviction_scores(self):
        """Different conviction inputs must produce different serialized confidence_scores."""
        thesis_high = _make_full_thesis(ticker="NVDA", confidence_score=0.78)
        thesis_low = _make_full_thesis(ticker="XYZ", confidence_score=0.38)

        d_high = thesis_high.model_dump()
        d_low = thesis_low.model_dump()

        assert d_high["confidence_score"] > d_low["confidence_score"], (
            "High and low confidence theses produce identical scores in payload"
        )
        assert abs(d_high["confidence_score"] - d_low["confidence_score"]) > 0.20, (
            f"Score spread too narrow: {d_high['confidence_score']:.2f} vs {d_low['confidence_score']:.2f}"
        )

    def test_conviction_reasoning_is_company_specific_not_boilerplate(self):
        """confidence_reasoning in payload should reference company context, not generic text."""
        from app.services.thesis_synthesizer import _check_generic_confidence_reasoning
        from app.schemas import InvestmentThesis

        # Simulate what conviction modeler produces for NVDA
        specific_reasoning = (
            "NVDA data-center revenue trajectory is well-evidenced by FMP valuation data; "
            "hyperscaler CapEx guidance for H2 2026 remains the primary unresolved variable."
        )
        thesis = InvestmentThesis(
            ticker="NVDA",
            company_name="NVIDIA Corp",
            direct_answer="x",
            bull_thesis="x",
            bear_thesis="x",
            confidence_reasoning=specific_reasoning,
        )
        from unittest.mock import MagicMock
        company = MagicMock()
        company.ticker = "NVDA"
        company.company_name = "NVIDIA Corp"

        warnings = _check_generic_confidence_reasoning(thesis, company)
        assert len(warnings) == 0, (
            f"Company-specific reasoning was flagged as generic: {warnings}"
        )

    def test_empty_what_increases_conviction_triggers_no_render(self):
        """When what_increases_conviction is empty, frontend should not render the section."""
        # This is a source audit — verify the conditional guard exists
        path = (
            pathlib.Path(__file__).parent.parent
            / "Ai-Intelligence-interface/frontend_cinematic/app/(product)/analyze/page.tsx"
        )
        if not path.is_file():
            pytest.skip("frontend repository is tested independently and is not checked out")
        src = path.read_text()

        # The render block must guard against empty string
        import re
        # Look for length check on whatIncreasesConviction
        guard_patterns = [
            r"whatIncreasesConviction\.length\s*>\s*\d+",
            r"whatIncreasesConviction\s*&&",
        ]
        found = any(re.search(p, src) for p in guard_patterns)
        assert found, (
            "No guard found for empty whatIncreasesConviction — "
            "empty string may render a blank section"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 6: Phase 5d — Setup quality field propagation (new schema fields)
# ══════════════════════════════════════════════════════════════════════════════

class TestSetupQualityFieldPropagation:
    """Phase 5d: setup_label, fragility_multiplier_applied, asymmetry_multiplier_applied
    must be declared on InvestmentThesis and survive model_dump() serialization.

    Without these, the frontend always gets null and defaults to 'actionable thesis' /
    Balanced for every ticker regardless of the modeler's actual output.
    """

    def _make_conviction_thesis(
        self,
        ticker: str = "NVDA",
        setup_label: str = "actionable thesis",
        frag_mult: float = 0.87,
        asym_mult: float = 0.91,
        confidence_score: float = 0.72,
    ):
        from app.schemas import InvestmentThesis
        return InvestmentThesis(
            ticker=ticker,
            company_name=f"{ticker} Corp",
            confidence_score=confidence_score,
            setup_label=setup_label,
            fragility_multiplier_applied=frag_mult,
            asymmetry_multiplier_applied=asym_mult,
        )

    def test_setup_label_in_schema(self):
        """InvestmentThesis must declare setup_label field."""
        from app.schemas import InvestmentThesis
        assert "setup_label" in InvestmentThesis.model_fields, (
            "setup_label is not a declared field on InvestmentThesis — "
            "frontend will always get null and default to 'actionable thesis'"
        )

    def test_fragility_multiplier_in_schema(self):
        """InvestmentThesis must declare fragility_multiplier_applied field."""
        from app.schemas import InvestmentThesis
        assert "fragility_multiplier_applied" in InvestmentThesis.model_fields, (
            "fragility_multiplier_applied is not declared on InvestmentThesis"
        )

    def test_asymmetry_multiplier_in_schema(self):
        """InvestmentThesis must declare asymmetry_multiplier_applied field."""
        from app.schemas import InvestmentThesis
        assert "asymmetry_multiplier_applied" in InvestmentThesis.model_fields, (
            "asymmetry_multiplier_applied is not declared on InvestmentThesis"
        )

    def test_model_dump_includes_setup_label(self):
        """setup_label must appear in model_dump() output."""
        thesis = self._make_conviction_thesis(setup_label="speculative setup")
        d = thesis.model_dump()
        assert "setup_label" in d
        assert d["setup_label"] == "speculative setup", (
            f"setup_label was '{d['setup_label']}', expected 'speculative setup'"
        )

    def test_model_dump_includes_fragility_multiplier(self):
        """fragility_multiplier_applied must appear in model_dump() with correct value."""
        thesis = self._make_conviction_thesis(frag_mult=0.78)
        d = thesis.model_dump()
        assert "fragility_multiplier_applied" in d
        assert d["fragility_multiplier_applied"] == pytest.approx(0.78)

    def test_model_dump_includes_asymmetry_multiplier(self):
        """asymmetry_multiplier_applied must appear in model_dump() with correct value."""
        thesis = self._make_conviction_thesis(asym_mult=0.80)
        d = thesis.model_dump()
        assert "asymmetry_multiplier_applied" in d
        assert d["asymmetry_multiplier_applied"] == pytest.approx(0.80)

    def test_speculative_label_serializes_correctly(self):
        """Speculative setup must serialize and deserialize correctly."""
        import json
        thesis = self._make_conviction_thesis(
            ticker="TSLA",
            setup_label="speculative setup",
            frag_mult=0.78,
            asym_mult=0.80,
            confidence_score=0.32,
        )
        payload = json.loads(json.dumps(thesis.model_dump()))
        assert payload["setup_label"] == "speculative setup"
        assert payload["fragility_multiplier_applied"] == pytest.approx(0.78)
        assert payload["asymmetry_multiplier_applied"] == pytest.approx(0.80)
        assert payload["confidence_score"] == pytest.approx(0.32)

    def test_durable_label_serializes_correctly(self):
        """Durable (high-alignment) label must serialize correctly."""
        import json
        thesis = self._make_conviction_thesis(
            ticker="MSFT",
            setup_label="high-alignment thesis",
            frag_mult=0.98,
            asym_mult=0.97,
            confidence_score=0.82,
        )
        payload = json.loads(json.dumps(thesis.model_dump()))
        assert payload["setup_label"] == "high-alignment thesis"
        assert payload["confidence_score"] == pytest.approx(0.82)

    def test_thesis_synthesizer_stamps_setup_label_from_conviction(self):
        """thesis_synthesizer source must contain setup_label stamping line."""
        import inspect
        from app.services import thesis_synthesizer
        src = inspect.getsource(thesis_synthesizer)
        assert "thesis.setup_label = conviction.setup_label" in src, (
            "thesis_synthesizer does not stamp setup_label onto thesis — "
            "frontend will always get the schema default ('actionable thesis')"
        )

    def test_thesis_synthesizer_stamps_fragility_multiplier(self):
        """thesis_synthesizer must stamp fragility_multiplier_applied from conviction."""
        import inspect
        from app.services import thesis_synthesizer
        src = inspect.getsource(thesis_synthesizer)
        assert "thesis.fragility_multiplier_applied = conviction.fragility_multiplier_applied" in src, (
            "thesis_synthesizer does not stamp fragility_multiplier_applied"
        )

    def test_thesis_synthesizer_stamps_asymmetry_multiplier(self):
        """thesis_synthesizer must stamp asymmetry_multiplier_applied from conviction."""
        import inspect
        from app.services import thesis_synthesizer
        src = inspect.getsource(thesis_synthesizer)
        assert "thesis.asymmetry_multiplier_applied = conviction.asymmetry_multiplier_applied" in src, (
            "thesis_synthesizer does not stamp asymmetry_multiplier_applied"
        )

    def test_confidence_pipeline_telemetry_in_synthesizer_source(self):
        """thesis_synthesizer must include [CONFIDENCE_PIPELINE] telemetry."""
        import inspect
        from app.services import thesis_synthesizer
        src = inspect.getsource(thesis_synthesizer)
        assert "[CONFIDENCE_PIPELINE]" in src, (
            "thesis_synthesizer missing [CONFIDENCE_PIPELINE] telemetry — "
            "cannot trace live confidence through the pipeline"
        )

    def test_fallback_trigger_logging_in_synthesizer_source(self):
        """thesis_synthesizer must log [FALLBACK_REASONING_TRIGGER] when fallback fires."""
        import inspect
        from app.services import thesis_synthesizer
        src = inspect.getsource(thesis_synthesizer)
        assert "[FALLBACK_REASONING_TRIGGER]" in src, (
            "thesis_synthesizer missing [FALLBACK_REASONING_TRIGGER] log — "
            "cannot detect when LLM fallback path activates"
        )

    def test_score_source_field_in_schema(self):
        """InvestmentThesis must declare score_source field (Phase 5g provenance)."""
        from app.schemas import InvestmentThesis
        assert "score_source" in InvestmentThesis.model_fields, (
            "score_source is not declared on InvestmentThesis — "
            "frontend forensic overlay cannot distinguish conviction_modeler from llm_raw_preserved"
        )

    def test_score_source_serializes_in_model_dump(self):
        """score_source must appear in model_dump() with its default value."""
        from app.schemas import InvestmentThesis
        t = InvestmentThesis(ticker="NVDA", company_name="NVIDIA")
        d = t.model_dump()
        assert "score_source" in d, "score_source absent from model_dump()"
        assert d["score_source"] == "llm_raw_preserved", (
            f"score_source default should be 'llm_raw_preserved', got {d['score_source']!r}"
        )

    def test_score_source_conviction_modeler_value(self):
        """score_source='conviction_modeler' must serialize correctly."""
        from app.schemas import InvestmentThesis
        import json
        t = InvestmentThesis(
            ticker="NVDA",
            company_name="NVIDIA Corp",
            score_source="conviction_modeler",
            setup_label="high-alignment thesis",
            fragility_multiplier_applied=0.87,
            asymmetry_multiplier_applied=0.91,
        )
        payload = json.loads(json.dumps(t.model_dump()))
        assert payload["score_source"] == "conviction_modeler", (
            f"Expected 'conviction_modeler', got {payload['score_source']!r}"
        )

    def test_conviction_propagation_failure_log_in_synthesizer_source(self):
        """thesis_synthesizer must log [CONVICTION_PROPAGATION_FAILURE] when conviction dims absent."""
        import inspect
        from app.services import thesis_synthesizer
        src = inspect.getsource(thesis_synthesizer)
        assert "[CONVICTION_PROPAGATION_FAILURE]" in src, (
            "thesis_synthesizer missing [CONVICTION_PROPAGATION_FAILURE] log — "
            "cannot identify the exact exception that prevents conviction propagation"
        )

    def test_synthesizer_stamps_score_source(self):
        """thesis_synthesizer source must stamp score_source onto thesis before return."""
        import inspect
        from app.services import thesis_synthesizer
        src = inspect.getsource(thesis_synthesizer)
        assert "thesis.score_source = _score_source" in src, (
            "thesis_synthesizer does not stamp score_source onto thesis — "
            "frontend cannot distinguish conviction_modeler from llm_raw_preserved"
        )

    def test_traceback_logging_in_conviction_except_block(self):
        """The conviction modeler except block must log a full traceback."""
        import inspect
        from app.services import thesis_synthesizer
        src = inspect.getsource(thesis_synthesizer)
        assert "format_exc" in src or "_traceback" in src, (
            "thesis_synthesizer conviction_modeler except block does not log a full traceback — "
            "exc_type alone is insufficient to diagnose the exception source"
        )


class TestLegacyConfidenceLayerRegression:
    """Phase 5g Reg 7 — Regression tests against legacy confidence layer artifacts.

    These tests assert that the visible confidence/conviction layer does NOT contain
    legacy placeholders when the conviction modeler is available.

    Fixtures tested: TSLA robotaxi valuation scenario (speculative setup),
    plus schema/source audits for the three legacy artifacts:
    1. "[moderate conviction, 65%]" in one_sentence_thesis
    2. "Limited evidence coverage…" in confidence_reasoning
    3. "65%" as a hardcoded confidence_score default

    All tests are deterministic (no live LLM calls).
    """

    def test_compressed_thesis_sync_source_code(self):
        """thesis_synthesizer must sync compressed_thesis.one_sentence_thesis after polishing.

        Root cause: compress_hero_thesis() strips the conviction bracket from
        thesis.one_sentence_thesis (top-level) but does NOT update
        thesis.compressed_thesis.one_sentence_thesis. The frontend reads
        compressed_thesis first and would see the unpolished bracket.
        This test verifies the sync code is present.
        """
        import inspect
        from app.services import thesis_synthesizer
        src = inspect.getsource(thesis_synthesizer)
        assert "compressed_thesis.one_sentence_thesis" in src, (
            "thesis_synthesizer does not sync compressed_thesis.one_sentence_thesis after polishing — "
            "frontend will see stale [moderate conviction, 65%] bracket from compressed_thesis"
        )
        assert "Sync compressed_thesis" in src or "synced after polishing" in src or "compressed_thesis sync" in src, (
            "thesis_synthesizer is missing the compressed_thesis sync block comment — "
            "the sync may be missing or was removed"
        )

    def test_one_sentence_thesis_bracket_stripped_by_polisher(self):
        """compress_hero_thesis() must strip the [conviction, pct%] bracket."""
        from app.services.thesis_polisher import compress_hero_thesis

        # Simulate what compress_thesis() produces before polishing
        test_cases = [
            "Tesla's FSD optionality drives the bull case. [moderate conviction, 65%]",
            "NVDA data-center dominance continues. [high conviction, 78%]",
            "PLTR growth requires continued government expansion. [low conviction, 38%]",
        ]
        for text in test_cases:
            result = compress_hero_thesis(text)
            assert "[moderate conviction" not in result, (
                f"compress_hero_thesis did not strip [moderate conviction] from: {text!r} → {result!r}"
            )
            assert "[high conviction" not in result, (
                f"compress_hero_thesis did not strip [high conviction] from: {text!r} → {result!r}"
            )
            assert "[low conviction" not in result, (
                f"compress_hero_thesis did not strip [low conviction] from: {text!r} → {result!r}"
            )

    def test_tsla_speculative_conf_qualifier_from_setup_label(self):
        """When setup_label is speculative, conf_qualifier must NOT produce 'moderate conviction'."""
        from app.schemas import InvestmentThesis
        from app.services.signal_ranker import compress_thesis, RankedSignalSet

        # Simulate TSLA thesis after conviction modeler ran (speculative setup)
        thesis = InvestmentThesis(
            ticker="TSLA",
            company_name="Tesla Inc",
            confidence_score=0.34,  # conviction modeler output, not LLM raw 0.65
            setup_label="speculative setup",
            bull_thesis=(
                "Tesla's autonomous vehicle optionality represents the largest single "
                "variable in the investment case — but it requires near-perfect execution "
                "over a multi-year horizon."
            ),
            conviction_dimensions={
                "evidence_quality": 0.55, "evidence_freshness": 0.80,
                "thesis_alignment": 0.45, "macro_uncertainty": 0.30,
                "valuation_certainty": 0.40, "estimate_dispersion": 0.45,
                "governance_risk": 0.05, "expectation_fragility": 0.88,
                "expectation_asymmetry": 0.78,
            },
        )

        # Build a minimal ranked set
        from unittest.mock import MagicMock
        ranked = MagicMock()
        ranked.top_signals = []
        ranked.top_risks = []
        ranked.all_ranked = []

        ct = compress_thesis(thesis, ranked)
        one_sent = ct.one_sentence_thesis

        # MUST NOT contain "moderate conviction" when setup_label says speculative
        assert "moderate conviction" not in one_sent.lower(), (
            f"compress_thesis produced 'moderate conviction' for speculative TSLA thesis: {one_sent!r}"
        )
        # MUST NOT contain "65%" when conviction modeler ran and produced 0.34
        assert "65%" not in one_sent, (
            f"compress_thesis produced '65%' for TSLA with conviction modeler score 0.34: {one_sent!r}"
        )

    def test_legacy_confidence_reasoning_replaced_in_fallback_path(self):
        """When conviction modeler fails, hard-fail phrases in confidence_reasoning must be replaced.

        The exception handler in synthesize_thesis() must detect _HARD_FAIL_CONFIDENCE_PHRASES
        and replace them with a company-specific fallback — NOT silently preserve boilerplate.
        """
        import inspect
        from app.services import thesis_synthesizer
        src = inspect.getsource(thesis_synthesizer)

        # The hard-fail phrase detection must happen in the except block
        assert "_HARD_FAIL_CONFIDENCE_PHRASES" in src, (
            "thesis_synthesizer conviction_modeler except block does not check "
            "_HARD_FAIL_CONFIDENCE_PHRASES — legacy 'Limited evidence coverage...' "
            "phrase will leak into the API response when conviction modeler fails"
        )
        assert "_has_hard_fail" in src or "hard_fail" in src, (
            "thesis_synthesizer conviction_modeler except block does not replace "
            "hard-fail phrases — boilerplate will survive to the API response"
        )

    def test_headline_confidence_source_log_present(self):
        """thesis_synthesizer must emit [HEADLINE_CONFIDENCE_SOURCE] before returning."""
        import inspect
        from app.services import thesis_synthesizer
        src = inspect.getsource(thesis_synthesizer)
        assert "[HEADLINE_CONFIDENCE_SOURCE]" in src, (
            "thesis_synthesizer does not emit [HEADLINE_CONFIDENCE_SOURCE] log — "
            "cannot audit which formatter produced the visible confidence layer"
        )
        assert "used_legacy_formatter" in src, (
            "[HEADLINE_CONFIDENCE_SOURCE] log must include used_legacy_formatter field"
        )

    def test_router_service_headline_confidence_source_log(self):
        """router_service must also echo [HEADLINE_CONFIDENCE_SOURCE] at serialization."""
        import inspect
        from app.services import router_service
        src = inspect.getsource(router_service)
        assert "[HEADLINE_CONFIDENCE_SOURCE]" in src, (
            "router_service does not echo [HEADLINE_CONFIDENCE_SOURCE] — "
            "cannot verify which formatter produced the response at the proxy boundary"
        )

    def test_confidence_score_not_hardcoded_default(self):
        """InvestmentThesis.confidence_score default must be 0.0, NOT 0.65."""
        from app.schemas import InvestmentThesis
        thesis = InvestmentThesis(ticker="TSLA", company_name="Tesla")
        assert thesis.confidence_score == 0.0, (
            f"InvestmentThesis.confidence_score default is {thesis.confidence_score}, not 0.0 — "
            "any LLM output of 0.65 must come from the LLM, not a hardcoded default"
        )

    def test_setup_label_aware_conf_qualifier_in_signal_ranker_source(self):
        """signal_ranker.compress_thesis must use setup_label when available."""
        import inspect
        from app.services import signal_ranker
        src = inspect.getsource(signal_ranker)
        assert "setup_label" in src, (
            "signal_ranker.compress_thesis does not consult setup_label — "
            "conf_qualifier will always use raw pct-band, not conviction modeler output"
        )
        # The legacy fallback path must still exist for backward compatibility
        assert "moderate conviction" in src or "conf_qualifier" in src, (
            "signal_ranker.compress_thesis is missing conf_qualifier logic entirely"
        )
