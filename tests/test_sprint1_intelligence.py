"""
tests/test_sprint1_intelligence.py

Sprint 1 regression suite (2026-06-08)

Covers three intelligence improvements:

  P1 — Question-Aware Direct Answer Generation
       Regression test: "How will the latest jobs report impact tech stocks
       generally but specifically Nvidia stock?" must classify as
       macro_cross_company, NOT macro_sensitivity.  The DA sequence must be:
       macro mechanism → company valuation sensitivity → company offset → verdict.

  P2 — Why-Not-X Risk Analysis
       InvestmentThesis must carry a non-empty why_not field.
       Why-not must be structurally distinct from bear_thesis.
       Polisher must cap it at 3 sentences.

  P3 — Threshold Zone Generation
       InvestmentThesis.threshold_zones must be a list of ThresholdZone objects.
       Each zone must have: metric, bull_threshold, bear_threshold, rationale.
       At least one valuation metric and one fundamental metric.

Constraints
-----------
- Do not change Q-First.
- Do not change conviction scoring.
- Do not change profiles.
- No new engineering beyond what Sprint 1 specifies.

Run
---
    python3 -m pytest tests/test_sprint1_intelligence.py -v
"""

from __future__ import annotations

import pytest

from app.schemas import InvestmentThesis, ThresholdZone
from app.services.router_service import _detect_question_intent, _is_macro_cross_company
from app.services.thesis_polisher import polish_thesis


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_thesis(**kwargs) -> InvestmentThesis:
    """Build a minimal InvestmentThesis, overriding any fields via kwargs."""
    defaults = dict(
        ticker="NVDA",
        company_name="NVIDIA Corporation",
        bull_thesis="AI infrastructure demand drives strong data center revenue.",
        bear_thesis="Valuation is stretched at current multiples.",
        conclusion="Constructive, but the market already prices in strong execution.",
        direct_answer="Strong jobs report implies rate expectations rise, compressing tech multiples.",
        why_not="",
        threshold_zones=[],
    )
    defaults.update(kwargs)
    return InvestmentThesis(**defaults)


# ── P1: Question-Aware Direct Answer — intent detection ──────────────────────

class TestMacroCrossCompanyIntentDetection:
    """The macro_cross_company intent must fire for the regression test question."""

    def test_jobs_report_nvidia_is_macro_cross_company(self):
        """Primary regression: jobs report + specifically Nvidia → macro_cross_company."""
        q = "How will the latest jobs report impact tech stocks generally but specifically Nvidia stock?"
        intent = _detect_question_intent(q)
        assert intent == "macro_cross_company", (
            f"Expected 'macro_cross_company', got {intent!r}. "
            "This is the Sprint 1 P1 primary regression case."
        )

    def test_is_macro_cross_company_true_for_nvda(self):
        """Helper gate: _is_macro_cross_company returns True for jobs+Nvidia query."""
        q = "How will the latest jobs report impact tech stocks generally but specifically Nvidia stock?"
        assert _is_macro_cross_company(q) is True

    def test_cpi_impact_for_nvda_stock(self):
        """CPI report + specifically for NVDA → macro_cross_company."""
        q = "What does the CPI report mean for tech stocks but specifically for NVDA?"
        intent = _detect_question_intent(q)
        assert intent == "macro_cross_company", (
            f"Expected 'macro_cross_company', got {intent!r}."
        )

    def test_fed_decision_impact_on_nvidia(self):
        """Fed decision + impact on Nvidia → macro_cross_company."""
        q = "How will the Fed rate decision affect tech multiples, and what does that mean for Nvidia?"
        assert _is_macro_cross_company(q) is True

    def test_payroll_report_for_apple_stock(self):
        """Payroll report + for Apple stock → macro_cross_company."""
        q = "The payroll report came in hot — what does this mean for Apple stock specifically?"
        assert _is_macro_cross_company(q) is True


class TestMacroCrossCompanyDoesNotFireForPureMarco:
    """Pure macro questions without company-specific framing → macro_sensitivity, NOT macro_cross_company."""

    def test_fed_bank_stocks_no_specific_company(self):
        """'How will the Fed decision affect bank stocks?' has no company signal."""
        q = "How will the Fed decision affect bank stocks?"
        assert _is_macro_cross_company(q) is False, (
            "Fed + bank stocks is macro_sensitivity, not macro_cross_company — "
            "no company-specific signal present."
        )

    def test_jobs_report_tech_sector_general(self):
        """General sector impact without naming a specific company."""
        q = "How will the jobs report impact tech stocks generally?"
        assert _is_macro_cross_company(q) is False, (
            "General tech sector question — no specific company named."
        )

    def test_cpi_and_rates_no_company(self):
        """Macro-only: CPI + rate impact without company specificity."""
        q = "If CPI comes in hot, how will interest rates respond and what happens to tech multiples?"
        assert _is_macro_cross_company(q) is False


class TestMacroCrossCompanyIntentPrecedence:
    """macro_cross_company must fire BEFORE macro_sensitivity in priority order."""

    def test_macro_cross_company_before_macro_sensitivity(self):
        """macro_sensitivity would also match the jobs report query — cross-company wins."""
        # "how will" matches _MACRO_SENSITIVITY_PATTERNS
        # "but specifically Nvidia" matches _MACRO_CROSS_COMPANY_SIGNALS
        # macro_cross_company should win
        q = "How will the jobs report impact tech stocks but specifically for Nvidia?"
        intent = _detect_question_intent(q)
        assert intent == "macro_cross_company", (
            f"macro_cross_company should take priority over macro_sensitivity. Got {intent!r}."
        )

    def test_implied_growth_rate_still_wins_over_macro_cross(self):
        """Phase 4 intents still take priority when their patterns match."""
        # "implied growth rate" is a Phase 4 intent checked BEFORE macro_cross_company
        q = "What is the implied growth rate priced into Nvidia given the jobs report?"
        intent = _detect_question_intent(q)
        assert intent == "implied_growth_rate", (
            f"Phase 4 implied_growth_rate should win. Got {intent!r}."
        )


# ── P1: Intent routes to macro_cross_company template ────────────────────────

class TestMacroCrossCompanyTemplateRegistered:
    """The macro_cross_company template must be registered in the question answerer."""

    def test_template_exists(self):
        """macro_cross_company template must be in _INTENT_PROMPTS."""
        from app.investment_agents.question_answerer_agent import _INTENT_PROMPTS
        assert "macro_cross_company" in _INTENT_PROMPTS, (
            "macro_cross_company template not registered in _INTENT_PROMPTS."
        )

    def test_template_contains_macro_first_constraint(self):
        """Template must contain the MACRO MECHANISM FIRST constraint."""
        from app.investment_agents.question_answerer_agent import _INTENT_PROMPTS
        template = _INTENT_PROMPTS["macro_cross_company"]
        assert "MACRO MECHANISM FIRST" in template or "Sentence 1" in template, (
            "Template does not enforce macro-first sequencing."
        )

    def test_template_sentence_1_prohibits_company_opener(self):
        """Sentence 1 in template must prohibit opening with the company."""
        from app.investment_agents.question_answerer_agent import _INTENT_PROMPTS
        template = _INTENT_PROMPTS["macro_cross_company"]
        # The template must contain a prohibition on opening with the company
        assert "Do NOT" in template and ("CUDA" in template or "company" in template.lower()), (
            "Template does not prohibit company-first opening in Sentence 1."
        )


# ── P2: Why-Not-X Risk Analysis ───────────────────────────────────────────────

class TestSchemaWhyNotField:
    """InvestmentThesis must have a why_not field with correct defaults."""

    def test_why_not_field_exists(self):
        thesis = InvestmentThesis(ticker="NVDA", company_name="NVIDIA")
        assert hasattr(thesis, "why_not"), "why_not field missing from InvestmentThesis"

    def test_why_not_default_is_empty_string(self):
        thesis = InvestmentThesis(ticker="NVDA", company_name="NVIDIA")
        assert thesis.why_not == "", f"why_not default should be '', got {thesis.why_not!r}"

    def test_why_not_accepts_prose(self):
        prose = (
            "The bull case rests on the assumption that AI demand is structural. "
            "The counter-thesis: if hyperscaler CapEx pauses in Q3, data center revenue misses. "
            "The tell: data center growth below 15% for two quarters confirms front-loading."
        )
        thesis = InvestmentThesis(ticker="NVDA", company_name="NVIDIA", why_not=prose)
        assert thesis.why_not == prose


class TestPolisherHandlesWhyNot:
    """thesis_polisher.polish_thesis must handle why_not correctly."""

    def test_polisher_preserves_short_why_not(self):
        """why_not with 3 sentences must survive polish_thesis unchanged."""
        prose = (
            "The bull case rests on the assumption that hyperscaler CapEx is structural. "
            "The counter-thesis: a one-quarter CapEx pause would miss the implied $40B run rate. "
            "The tell: data center growth below 15% YoY for two consecutive quarters signals the break."
        )
        thesis = _make_thesis(why_not=prose)
        polished = polish_thesis(thesis)
        assert polished.why_not, "why_not should not be empty after polish_thesis"
        # 3 sentences is within the 3-sentence cap — should be preserved
        from app.services.thesis_polisher import _split_sentences
        sentences = _split_sentences(polished.why_not)
        assert len(sentences) <= 3, (
            f"why_not should have ≤3 sentences after polish, got {len(sentences)}"
        )

    def test_polisher_truncates_verbose_why_not(self):
        """why_not with >3 sentences must be truncated to 3."""
        verbose = (
            "The bull case rests on AI demand. "
            "The counter-thesis: CapEx pause kills the thesis. "
            "The tell: data center growth below 15% is the signal. "
            "Also important: margin compression would further pressure the stock. "
            "Furthermore, competition from custom silicon could erode CUDA's moat."
        )
        thesis = _make_thesis(why_not=verbose)
        polished = polish_thesis(thesis)
        from app.services.thesis_polisher import _split_sentences
        sentences = _split_sentences(polished.why_not)
        assert len(sentences) <= 3, (
            f"Verbose why_not must be truncated to 3 sentences. Got {len(sentences)}."
        )

    def test_polisher_does_not_affect_empty_why_not(self):
        """Empty why_not must remain empty through polish_thesis."""
        thesis = _make_thesis(why_not="")
        polished = polish_thesis(thesis)
        assert polished.why_not == "", "Empty why_not should stay empty after polish"


class TestWhyNotDistinctFromBearThesis:
    """why_not and bear_thesis must serve distinct analytical roles."""

    def test_why_not_and_bear_thesis_can_coexist(self):
        """A thesis can have both bear_thesis and why_not with different content."""
        thesis = _make_thesis(
            bear_thesis=(
                "Valuation at ~35x forward earnings embeds multiple compression risk "
                "if rate expectations shift. Competition from custom silicon is the "
                "structural risk to CUDA's monopoly on AI training workloads."
            ),
            why_not=(
                "The bull case rests on the assumption that hyperscaler CapEx is structural "
                "and not front-loaded. The counter-thesis: if AWS/Azure guidance signals a "
                "CapEx pause, Nvidia's data center revenue would miss consensus by 20%+. "
                "The tell: data center revenue growth below 15% YoY for two quarters."
            ),
        )
        polished = polish_thesis(thesis)
        assert polished.bear_thesis, "bear_thesis should not be empty"
        assert polished.why_not, "why_not should not be empty"
        # They must contain different content (not one suppressing the other)
        assert polished.bear_thesis != polished.why_not, (
            "bear_thesis and why_not should not be identical"
        )


# ── P3: Threshold Zone Generation ────────────────────────────────────────────

class TestThresholdZoneSchema:
    """ThresholdZone model must validate correctly."""

    def test_threshold_zone_creation(self):
        zone = ThresholdZone(
            metric="Data Center Revenue Growth YoY",
            bull_threshold=">25%",
            bear_threshold="<15%",
            rationale="Growth above 25% validates structural demand; below 15% signals front-loading.",
        )
        assert zone.metric == "Data Center Revenue Growth YoY"
        assert zone.bull_threshold == ">25%"
        assert zone.bear_threshold == "<15%"
        assert zone.rationale

    def test_threshold_zone_requires_metric(self):
        """metric and bull/bear thresholds are required fields."""
        with pytest.raises(Exception):  # pydantic ValidationError
            ThresholdZone(bull_threshold=">25%", bear_threshold="<15%")  # missing metric

    def test_threshold_zone_rationale_optional(self):
        """rationale has a default empty string."""
        zone = ThresholdZone(metric="Forward P/E", bull_threshold=">30x", bear_threshold="<22x")
        assert zone.rationale == ""


class TestInvestmentThesisThresholdZones:
    """InvestmentThesis.threshold_zones must accept a list of ThresholdZone objects."""

    def test_threshold_zones_default_empty(self):
        thesis = InvestmentThesis(ticker="NVDA", company_name="NVIDIA")
        assert thesis.threshold_zones == []

    def test_threshold_zones_accepts_zone_list(self):
        zones = [
            ThresholdZone(
                metric="Data Center Revenue Growth YoY",
                bull_threshold=">25%",
                bear_threshold="<15%",
                rationale="Validates hyperscaler CapEx cycle is intact.",
            ),
            ThresholdZone(
                metric="Forward P/E",
                bull_threshold=">30x",
                bear_threshold="<25x",
                rationale="Multiple above 30x only justified by sustained >25% growth.",
            ),
        ]
        thesis = InvestmentThesis(
            ticker="NVDA",
            company_name="NVIDIA",
            threshold_zones=zones,
        )
        assert len(thesis.threshold_zones) == 2
        assert thesis.threshold_zones[0].metric == "Data Center Revenue Growth YoY"
        assert thesis.threshold_zones[1].metric == "Forward P/E"

    def test_threshold_zones_survive_polish_thesis(self):
        """polish_thesis must not destroy threshold_zones."""
        zones = [
            ThresholdZone(
                metric="Data Center Revenue Growth YoY",
                bull_threshold=">25%",
                bear_threshold="<15%",
                rationale="Core driver of the AI infrastructure thesis.",
            ),
        ]
        thesis = _make_thesis(threshold_zones=zones)
        polished = polish_thesis(thesis)
        assert len(polished.threshold_zones) == 1
        assert polished.threshold_zones[0].metric == "Data Center Revenue Growth YoY"

    def test_threshold_zones_from_dict_list(self):
        """Pydantic should coerce a list of dicts into ThresholdZone objects."""
        raw_zones = [
            {
                "metric": "Forward P/E",
                "bull_threshold": ">30x",
                "bear_threshold": "<22x",
                "rationale": "Multiple above 30x requires >25% growth to be defensible.",
            }
        ]
        if hasattr(InvestmentThesis, "model_validate"):
            thesis = InvestmentThesis.model_validate({
                "ticker": "NVDA",
                "company_name": "NVIDIA",
                "threshold_zones": raw_zones,
            })
        else:
            thesis = InvestmentThesis.parse_obj({
                "ticker": "NVDA",
                "company_name": "NVIDIA",
                "threshold_zones": raw_zones,
            })
        assert len(thesis.threshold_zones) == 1
        assert isinstance(thesis.threshold_zones[0], ThresholdZone)
        assert thesis.threshold_zones[0].metric == "Forward P/E"


# ── End-to-end: intent → synthesis field registration ────────────────────────

class TestSynthesizerFieldRegistration:
    """Verify Sprint 1 fields are registered in the synthesizer's field list."""

    def test_why_not_in_thesis_fields(self):
        from app.services.thesis_synthesizer import _THESIS_FIELDS
        assert "why_not" in _THESIS_FIELDS, (
            "why_not must be in _THESIS_FIELDS so the LLM prompt includes it."
        )

    def test_threshold_zones_in_thesis_fields(self):
        from app.services.thesis_synthesizer import _THESIS_FIELDS
        assert "threshold_zones" in _THESIS_FIELDS, (
            "threshold_zones must be in _THESIS_FIELDS so the LLM prompt includes it."
        )


# ── P1: DA sequencing contract ────────────────────────────────────────────────

class TestDASequencingContract:
    """The DA for macro_cross_company questions must lead with macro mechanism, not company.

    These are unit tests for the contract, not live LLM tests. They verify:
    - The template structure enforces the correct sentence order.
    - The intent detection correctly routes the regression question.

    Live validation against the deployed /ask endpoint is done in the
    production regression suite (validate_phase*.py).
    """

    def test_template_sentence_1_is_macro(self):
        """Sentence 1 in the macro_cross_company template must describe the macro mechanism."""
        from app.investment_agents.question_answerer_agent import _INTENT_PROMPTS
        template = _INTENT_PROMPTS["macro_cross_company"]
        # Check that Sentence 1 instructions describe macro, not company
        # The template uses "MACRO MECHANISM FIRST" or explicit prohibition
        has_macro_first = (
            "MACRO MECHANISM FIRST" in template
            or "not the company" in template
            or "THE MACRO MECHANISM FIRST" in template
        )
        assert has_macro_first, (
            "Template Sentence 1 must enforce macro mechanism first, not company."
        )

    def test_template_company_products_forbidden_in_s1(self):
        """Template must explicitly forbid CUDA / AI demand / company products in S1."""
        from app.investment_agents.question_answerer_agent import _INTENT_PROMPTS
        template = _INTENT_PROMPTS["macro_cross_company"]
        assert "CUDA" in template, (
            "Template should name CUDA as an example of company-first (forbidden in S1)."
        )

    def test_template_company_analysis_in_s3_s4(self):
        """Company-specific analysis must be pushed to Sentences 3-4."""
        from app.investment_agents.question_answerer_agent import _INTENT_PROMPTS
        template = _INTENT_PROMPTS["macro_cross_company"]
        assert "Sentences 3" in template or "Sentence 3" in template, (
            "Company-specific analysis must be restricted to Sentences 3-4 in template."
        )
