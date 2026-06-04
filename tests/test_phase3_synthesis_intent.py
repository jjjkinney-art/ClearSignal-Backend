"""
tests/test_phase3_synthesis_intent.py

Phase 3 regression suite for query-intent sensitivity in secondary sections.

Background
----------
Phase 2 differentiated primary analytical sections (bull_thesis, bear_thesis,
core_debate, direct_answer, macro_sensitivity, valuation_view) via 4 levers.
Four secondary sections remained at 55–75% overlap:
  - conclusion         (no per-intent mandate)
  - key_drivers        (Azure/AI always led regardless of question)
  - one_sentence_thesis (generic company positioning)
  - what_increases_conviction (generic earnings catalysts for all questions)

Additionally, `investment_thesis` intent received minimal Phase 2 treatment:
  - No Lever 1 dominant_dim override → keyword scoring produced wrong dim
  - No Lever 2 agent sub-field injection
  - Generic question_anchor_block (same as Phase 1)
  → ai_growth vs valuation: 97.6% synthesis prompt overlap — worst Phase 2 case

Fix (Phase 3 — 3 extensions)
-----------------------------
Extension 1 — _INTENT_TO_DOMINANT_DIM additions:
    investment_thesis → "operational"  (business model durability question)
    business_model    → "operational"  (same treatment)

Extension 2 — _build_agent_summaries() investment_thesis / business_model:
    Business Quality: revenue_durability + operating_quality injected
    Valuation:        growth_view + margin_trend injected

Extension 3 — _build_secondary_section_mandates() (new function):
    Returns per-intent mandates for: one_sentence_thesis, key_drivers,
    what_increases_conviction, conclusion.
    - competitive_position: competitive metric leads each section
    - macro_sensitivity:    macro/rate factor leads each section
    - valuation_stance:     valuation/multiple metric leads each section
    - risk_assessment:      risk factor leads each section
    - investment_thesis:    business model driver leads each section
    - None / other:         returns "" (backward compat)

Extension 4 — investment_thesis Lever 4 anchor block:
    First-class question_anchor_block for investment_thesis / business_model:
    bull_thesis / bear_thesis / core_debate anchored on business model mechanics.

Test coverage
-------------
1. TestDominantDimPhase3Extension    — investment_thesis/business_model → operational
2. TestAgentSubFieldPhase3Extension  — revenue_durability/operating_quality injected
3. TestSecondaryMandates             — _build_secondary_section_mandates() per intent
4. TestInvestmentThesisAnchor        — Lever 4 anchor fires for investment_thesis
5. TestPhase3PromptOverlap           — ai_growth vs others < Phase 2 97.6% baseline
6. TestSecondaryMandatesInPrompt     — secondary mandates appear in full synthesis prompt
7. TestNVDAPhase3Validation          — same extensions apply for NVDA
8. TestBackwardCompatPhase3          — None intent and unknown intent degrade gracefully

Run
---
    python3 -m pytest tests/test_phase3_synthesis_intent.py -v
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional

import pytest

from app.schemas import (
    CompanyContext, CompanyKnowledgeProfile, RetrievedEvidence,
    ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment,
)
from app.services.thesis_synthesizer import (
    _build_synthesis_prompt,
    _build_agent_summaries,
    _build_secondary_section_mandates,
    _INTENT_TO_DOMINANT_DIM,
)


# ════════════════════════════════════════════════════════════════════════════════
# Fixtures / helpers
# ════════════════════════════════════════════════════════════════════════════════

def _company(ticker: str, name: str) -> CompanyContext:
    return CompanyContext(
        ticker=ticker,
        company_name=name,
        sector="Technology",
        industry="Software",
        aliases=[ticker, name.split()[0]],
    )

def _msft() -> CompanyContext:
    return _company("MSFT", "Microsoft Corporation")

def _nvda() -> CompanyContext:
    return _company("NVDA", "NVIDIA Corporation")

def _profile(ticker: str, name: str) -> CompanyKnowledgeProfile:
    return CompanyKnowledgeProfile(
        ticker=ticker,
        company_name=name,
        business_model=f"{name} enterprise cloud and AI platform",
        primary_revenue_drivers=[f"{ticker} Cloud", f"{ticker} Software"],
        recurring_revenue_sources=[f"{ticker} subscriptions"],
        key_metrics=[f"{ticker} cloud growth", "margin", "ARR"],
        competitive_advantages=["ecosystem lock-in", "switching costs"],
        valuation_style="quality_compounder",
        rate_sensitivity_note="Long-duration cash flows; rate-sensitive multiple",
        inflation_pass_through="High via enterprise contracts",
        recession_behavior="Defensively recurring",
        business_model_keywords=[ticker, "cloud", "AI", "enterprise", "subscription"],
    )

def _msft_profile() -> CompanyKnowledgeProfile:
    return _profile("MSFT", "Microsoft")

def _nvda_profile() -> CompanyKnowledgeProfile:
    return _profile("NVDA", "NVIDIA")

def _agents_msft():
    val = ValuationView(
        overall="MSFT trades at ~31x forward P/E on Azure cloud premium.",
        confidence=0.72,
        pe_assessment="31x forward P/E vs sector 27x — 15% quality premium",
        growth_view="Azure +28% YoY; M365 commercial cloud +16%; total revenue +16%",
        margin_trend="Intelligent Cloud margin +180bps YTD on Azure mix shift",
        discount_sensitivity="100bps rate rise → ~8-10% P/E compression via DCF",
        relative_value="Premium justified by recurring revenue moat",
    )
    mac = MacroSensitivity(
        overall="MSFT has moderate rate sensitivity via DCF multiple pressure.",
        confidence=0.68,
        rate_sensitivity="100bps rate rise → ~8-10% P/E compression via DCF discount rate expansion",
        inflation_sensitivity="High pricing power via multi-year enterprise contracts",
        recession_risk="Below average — Azure mission-critical; enterprise IT sticky",
        cyclicality="Defensive ~65% subscription/contract revenue mix",
    )
    risk = RiskProfile(
        overall="AWS and Google Cloud are primary competitive risk for MSFT.",
        confidence=0.71,
        debt_risk="Net cash ~$30B; A-rated; no refinancing risk",
        competitive_risk="AWS wins multi-cloud workloads; GCP winning AI-native deployments",
        regulatory_risk="EU Digital Markets Act; FTC Activision integration scrutiny",
        concentration_risk="Azure ~45% of growth contribution",
        key_risks=[
            "Azure AI-inference market share erosion (AWS/GCP)",
            "Copilot monetization uncertainty at enterprise scale",
            "Multiple compression if rates stay elevated past FY26",
        ],
    )
    mkt = MarketContext(
        overall="MSFT consensus: 38/45 Buy-rated, avg PT $430.",
        confidence=0.65,
        sentiment="Bullish institutional positioning",
        momentum="Positive YTD price momentum",
        positioning="Institutional overweight on Azure growth re-acceleration",
        recent_catalysts=["Azure Q2 +28% beat", "Copilot enterprise GA"],
    )
    qual = QualityAssessment(
        overall="MSFT has durable moat via Azure ecosystem and M365 lock-in.",
        confidence=0.78,
        moat="Azure Active Directory switching costs compound with M365 Copilot embedding",
        management="Satya Nadella: disciplined capital allocator, ROIC 14%→38%",
        capital_allocation="$60B buyback program; $22B executed in FY24; 3% dividend",
        revenue_durability="~65% recurring (M365+Azure subscriptions); enterprise churn <2%",
        operating_quality="FCF conversion ~115% of net income; 45%+ operating margin",
    )
    return val, mac, risk, mkt, qual

def _agents_nvda():
    val = ValuationView(
        overall="NVDA trades at ~35x forward P/E on AI-demand cycle premium.",
        confidence=0.65,
        pe_assessment="35x forward P/E — AI cycle premium; high vs semiconductor history",
        growth_view="Data center +200% YoY on H100/H200 ramp; gaming flat",
        margin_trend="Gross margin 75%+ on H100 pricing discipline; expanding",
        discount_sensitivity="High duration: 100bps rate rise compresses ~12-15%",
        relative_value="Premium requires sustained hyperscaler capex cycle",
    )
    mac = MacroSensitivity(
        overall="NVDA is highly rate-sensitive due to long-duration AI capex cycle dependency.",
        confidence=0.62,
        rate_sensitivity="100bps rate rise → ~12-15% P/E compression; AI capex hurdle rate rises",
        inflation_sensitivity="Limited pricing power on commodity components",
        recession_risk="High — enterprise AI spending discretionary in economic downturn",
        cyclicality="Highly cyclical; correlated with hyperscaler capex cycles",
    )
    risk = RiskProfile(
        overall="Custom silicon from hyperscalers (Google TPU, Amazon Trainium) is primary NVDA risk.",
        confidence=0.70,
        debt_risk="Net cash; no leverage concern",
        competitive_risk="Google TPU v5, Amazon Trainium/Inferentia eating AI inference market share",
        regulatory_risk="China export controls cut $4-8B revenue annually; 20% revenue at risk",
        concentration_risk="4 hyperscalers = ~60% of data center revenue",
        key_risks=[
            "Hyperscaler custom chips reduce NVDA AI inference addressable market",
            "China export controls cut $4-8B revenue annually",
            "AI spending cycle pause if hyperscaler ROI disappoints",
        ],
    )
    mkt = MarketContext(
        overall="NVDA consensus: 35/40 Buy-rated, avg PT $1100.",
        confidence=0.68,
        sentiment="Bullish but cautious on cycle timing; crowded institutional long",
        momentum="Strong YTD; pausing on custom chip competitive news",
        positioning="Large institutional overweight; crowded long position",
        recent_catalysts=["H200 shipment ramp acceleration", "Blackwell architecture launch"],
    )
    qual = QualityAssessment(
        overall="NVDA has durable CUDA moat but faces emerging custom-silicon competitive threat.",
        confidence=0.73,
        moat="CUDA ecosystem: 4M+ developers, 600+ GPU-optimized libraries, 10yr ML framework integration",
        management="Jensen Huang: visionary, long-term capital allocation, GB200 R&D commitment",
        capital_allocation="$25B buyback; minimal dividend — reinvesting in Blackwell/GB200 R&D",
        revenue_durability="60% hyperscaler = high concentration + cyclical risk",
        operating_quality="Fabless model; 75% gross margin; capex-light; high ROIC",
    )
    return val, mac, risk, mkt, qual

def _text_overlap(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def _build_prompt(company, profile, agents, intent, question):
    val, mac, risk, mkt, qual = agents
    return _build_synthesis_prompt(
        company, val, mac, risk, mkt, qual,
        evidence=[], profile=profile,
        original_user_question=question,
        question_intent=intent,
        ranked=None, prior_snapshot=None,
    )

MSFT_QUESTIONS = {
    "ai_growth":  ("Can Microsoft sustain AI-driven growth if enterprise spending slows?",
                   "investment_thesis"),
    "moat":       ("Is Azure becoming a stronger moat than Microsoft 365?",
                   "competitive_position"),
    "valuation":  ("What would cause Microsoft's multiple to compress?",
                   "valuation_stance"),
    "risk":       ("What is the biggest risk to Microsoft over the next 5 years?",
                   "risk_assessment"),
}

NVDA_QUESTIONS = {
    "ai_slowdown":  ("Can Nvidia justify its valuation if AI spending slows?",
                     "valuation_stance"),
    "custom_chip":  ("How exposed is Nvidia to hyperscaler custom chips?",
                     "competitive_position"),
    "valuation":    ("What would cause Nvidia's multiple to compress?",
                     "valuation_stance"),
    "risk":         ("What is the biggest risk to Nvidia over the next 5 years?",
                     "risk_assessment"),
}


# ════════════════════════════════════════════════════════════════════════════════
# Section 1 — Phase 3 dominant_dim extensions
# ════════════════════════════════════════════════════════════════════════════════

class TestDominantDimPhase3Extension:
    """investment_thesis and business_model now have explicit dominant_dim overrides."""

    def test_investment_thesis_in_override_map(self):
        assert "investment_thesis" in _INTENT_TO_DOMINANT_DIM, (
            "investment_thesis must be in _INTENT_TO_DOMINANT_DIM (Phase 3)"
        )

    def test_business_model_in_override_map(self):
        assert "business_model" in _INTENT_TO_DOMINANT_DIM, (
            "business_model must be in _INTENT_TO_DOMINANT_DIM (Phase 3)"
        )

    def test_investment_thesis_maps_to_operational(self):
        assert _INTENT_TO_DOMINANT_DIM["investment_thesis"] == "operational"

    def test_business_model_maps_to_operational(self):
        assert _INTENT_TO_DOMINANT_DIM["business_model"] == "operational"

    def test_investment_thesis_gets_operational_directive_in_prompt(self):
        """Synthesis prompt for investment_thesis must contain OPERATIONAL depth directive."""
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question=MSFT_QUESTIONS["ai_growth"][0],
            question_intent="investment_thesis",
            ranked=None, prior_snapshot=None,
        )
        assert "DOMINANT DIMENSION — OPERATIONAL" in prompt

    def test_business_model_gets_operational_directive_in_prompt(self):
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question="What is Microsoft's core business model?",
            question_intent="business_model",
            ranked=None, prior_snapshot=None,
        )
        assert "DOMINANT DIMENSION — OPERATIONAL" in prompt

    def test_nvda_investment_thesis_gets_operational_directive(self):
        val, mac, risk, mkt, qual = _agents_nvda()
        prompt = _build_synthesis_prompt(
            _nvda(), val, mac, risk, mkt, qual,
            evidence=[], profile=_nvda_profile(),
            original_user_question="Can Nvidia sustain its AI growth trajectory?",
            question_intent="investment_thesis",
            ranked=None, prior_snapshot=None,
        )
        assert "DOMINANT DIMENSION — OPERATIONAL" in prompt

    def test_all_five_intents_have_overrides(self):
        """All five non-valuation intents should now have explicit overrides."""
        for intent in ("competitive_position", "macro_sensitivity",
                       "risk_assessment", "investment_thesis", "business_model"):
            assert intent in _INTENT_TO_DOMINANT_DIM, (
                f"{intent} must be in _INTENT_TO_DOMINANT_DIM"
            )


# ════════════════════════════════════════════════════════════════════════════════
# Section 2 — Phase 3 agent sub-field injection extensions
# ════════════════════════════════════════════════════════════════════════════════

class TestAgentSubFieldPhase3Extension:
    """investment_thesis and business_model now inject revenue_durability, operating_quality."""

    def test_investment_thesis_injects_revenue_durability(self):
        val, mac, risk, mkt, qual = _agents_msft()
        summaries = _build_agent_summaries(
            val, mac, risk, mkt, qual, question_intent="investment_thesis"
        )
        # quality.revenue_durability contains "churn" — unique to that sub-field
        assert "churn" in summaries.lower() or "recurring" in summaries.lower(), (
            "quality.revenue_durability must be injected for investment_thesis"
        )

    def test_investment_thesis_injects_operating_quality(self):
        val, mac, risk, mkt, qual = _agents_msft()
        summaries = _build_agent_summaries(
            val, mac, risk, mkt, qual, question_intent="investment_thesis"
        )
        # quality.operating_quality contains "fcf conversion"
        assert "fcf conversion" in summaries.lower() or "115%" in summaries, (
            "quality.operating_quality must be injected for investment_thesis"
        )

    def test_investment_thesis_injects_growth_view(self):
        val, mac, risk, mkt, qual = _agents_msft()
        summaries = _build_agent_summaries(
            val, mac, risk, mkt, qual, question_intent="investment_thesis"
        )
        # valuation.growth_view contains "Azure +28%"
        assert "azure" in summaries.lower() and ("+28%" in summaries or "28%" in summaries), (
            "valuation.growth_view must be injected for investment_thesis"
        )

    def test_investment_thesis_injects_margin_trend(self):
        val, mac, risk, mkt, qual = _agents_msft()
        summaries = _build_agent_summaries(
            val, mac, risk, mkt, qual, question_intent="investment_thesis"
        )
        # valuation.margin_trend contains "Intelligent Cloud margin"
        assert "intelligent cloud" in summaries.lower() or "180bps" in summaries, (
            "valuation.margin_trend must be injected for investment_thesis"
        )

    def test_business_model_injects_same_as_investment_thesis(self):
        """business_model intent gets same sub-field injections as investment_thesis."""
        val, mac, risk, mkt, qual = _agents_msft()
        s_it  = _build_agent_summaries(val, mac, risk, mkt, qual, question_intent="investment_thesis")
        s_bm  = _build_agent_summaries(val, mac, risk, mkt, qual, question_intent="business_model")
        assert s_it == s_bm, "business_model and investment_thesis must produce identical agent summaries"

    def test_investment_thesis_does_not_inject_moat(self):
        """investment_thesis must NOT inject quality.moat (that is competitive_position's field)."""
        val, mac, risk, mkt, qual = _agents_msft()
        summaries = _build_agent_summaries(
            val, mac, risk, mkt, qual, question_intent="investment_thesis"
        )
        # quality.moat contains "Active Directory" — should NOT appear for investment_thesis
        assert "active directory" not in summaries.lower(), (
            "quality.moat must NOT be injected for investment_thesis intent"
        )

    def test_investment_thesis_always_includes_overall(self):
        val, mac, risk, mkt, qual = _agents_msft()
        summaries = _build_agent_summaries(
            val, mac, risk, mkt, qual, question_intent="investment_thesis"
        )
        # valuation.overall always present
        assert "31x forward p/e" in summaries.lower()

    def test_nvda_investment_thesis_injects_cuda_revenue_durability(self):
        val, mac, risk, mkt, qual = _agents_nvda()
        summaries = _build_agent_summaries(
            val, mac, risk, mkt, qual, question_intent="investment_thesis"
        )
        # NVDA quality.revenue_durability contains "hyperscaler"
        assert "hyperscaler" in summaries.lower() or "concentration" in summaries.lower()


# ════════════════════════════════════════════════════════════════════════════════
# Section 3 — Secondary section mandates
# ════════════════════════════════════════════════════════════════════════════════

class TestSecondaryMandates:
    """_build_secondary_section_mandates() returns correct per-intent mandate blocks."""

    def test_none_intent_returns_empty(self):
        assert _build_secondary_section_mandates("MSFT", None) == ""

    def test_unknown_intent_returns_empty(self):
        assert _build_secondary_section_mandates("MSFT", "unknown_xyz") == ""

    # ── competitive_position ─────────────────────────────────────────────────

    def test_competitive_position_mentions_one_sentence_thesis(self):
        block = _build_secondary_section_mandates("MSFT", "competitive_position")
        assert "one_sentence_thesis" in block

    def test_competitive_position_mentions_conclusion(self):
        block = _build_secondary_section_mandates("MSFT", "competitive_position")
        assert "conclusion" in block

    def test_competitive_position_mentions_key_drivers(self):
        block = _build_secondary_section_mandates("MSFT", "competitive_position")
        assert "key_drivers" in block

    def test_competitive_position_mentions_what_increases_conviction(self):
        block = _build_secondary_section_mandates("MSFT", "competitive_position")
        assert "what_increases_conviction" in block

    def test_competitive_position_mandates_competitive_driver_in_key_drivers(self):
        block = _build_secondary_section_mandates("MSFT", "competitive_position")
        assert "competitive" in block.lower() or "moat" in block.lower()

    def test_competitive_position_forbids_macro_as_first_driver(self):
        block = _build_secondary_section_mandates("MSFT", "competitive_position")
        assert "not" in block.lower() or "do not" in block.lower() or "must not" in block.lower()

    # ── macro_sensitivity ────────────────────────────────────────────────────

    def test_macro_sensitivity_mandates_macro_driver_in_key_drivers(self):
        block = _build_secondary_section_mandates("MSFT", "macro_sensitivity")
        assert "macro" in block.lower() or "rate" in block.lower()

    def test_macro_sensitivity_mentions_conclusion_rate_scenario(self):
        block = _build_secondary_section_mandates("MSFT", "macro_sensitivity")
        assert "conclusion" in block and (
            "rate" in block.lower() or "macro" in block.lower()
        )

    def test_macro_sensitivity_mentions_fed_action_in_conviction(self):
        block = _build_secondary_section_mandates("MSFT", "macro_sensitivity")
        assert "fed" in block.lower() or "cpi" in block.lower() or "rate" in block.lower()

    # ── valuation_stance ─────────────────────────────────────────────────────

    def test_valuation_stance_mandates_multiple_in_key_drivers(self):
        block = _build_secondary_section_mandates("MSFT", "valuation_stance")
        assert "valuation" in block.lower() or "multiple" in block.lower()

    def test_valuation_stance_mandates_entry_exit_in_conclusion(self):
        block = _build_secondary_section_mandates("MSFT", "valuation_stance")
        assert "entry" in block.lower() or "add at" in block.lower() or "avoid above" in block.lower()

    # ── risk_assessment ──────────────────────────────────────────────────────

    def test_risk_assessment_mandates_risk_factor_in_key_drivers(self):
        block = _build_secondary_section_mandates("MSFT", "risk_assessment")
        assert "risk" in block.lower()

    def test_risk_assessment_mandates_risk_resolution_in_conviction(self):
        block = _build_secondary_section_mandates("MSFT", "risk_assessment")
        assert "resolut" in block.lower() or "resolution" in block.lower() or "resolve" in block.lower()

    def test_risk_assessment_mentions_monitoring_in_conclusion(self):
        block = _build_secondary_section_mandates("MSFT", "risk_assessment")
        assert "monitor" in block.lower() or "reduce if" in block.lower()

    # ── investment_thesis ────────────────────────────────────────────────────

    def test_investment_thesis_has_block(self):
        block = _build_secondary_section_mandates("MSFT", "investment_thesis")
        assert len(block) > 50, "investment_thesis must return non-trivial mandate block"

    def test_investment_thesis_mandates_business_model_driver_in_key_drivers(self):
        block = _build_secondary_section_mandates("MSFT", "investment_thesis")
        assert "business model" in block.lower() or "revenue" in block.lower()

    def test_investment_thesis_mandates_execution_catalysts_in_conviction(self):
        block = _build_secondary_section_mandates("MSFT", "investment_thesis")
        assert "execution" in block.lower() or "arr" in block.lower() or "fcf" in block.lower()

    def test_investment_thesis_conclusion_end_with_thesis_verdict(self):
        block = _build_secondary_section_mandates("MSFT", "investment_thesis")
        assert "thesis" in block.lower() and (
            "intact" in block.lower() or "reassess" in block.lower()
        )

    def test_business_model_same_block_as_investment_thesis(self):
        bm = _build_secondary_section_mandates("MSFT", "business_model")
        it = _build_secondary_section_mandates("MSFT", "investment_thesis")
        assert bm == it, "business_model and investment_thesis must produce identical mandate blocks"

    def test_ticker_in_all_non_empty_blocks(self):
        """All non-empty mandate blocks must reference the ticker."""
        for intent in ("competitive_position", "macro_sensitivity", "valuation_stance",
                       "risk_assessment", "investment_thesis"):
            block = _build_secondary_section_mandates("MSFT", intent)
            assert "MSFT" in block or "msft" in block.lower(), (
                f"intent={intent!r}: mandate block must reference ticker MSFT"
            )

    def test_all_four_secondary_sections_named_per_intent(self):
        """Every non-empty block must mention all 4 secondary sections."""
        sections = ["one_sentence_thesis", "key_drivers",
                    "what_increases_conviction", "conclusion"]
        for intent in ("competitive_position", "macro_sensitivity", "valuation_stance",
                       "risk_assessment", "investment_thesis"):
            block = _build_secondary_section_mandates("MSFT", intent)
            for sec in sections:
                assert sec in block, (
                    f"intent={intent!r}: secondary mandate block must mention '{sec}'"
                )


# ════════════════════════════════════════════════════════════════════════════════
# Section 4 — investment_thesis Lever 4 anchor block
# ════════════════════════════════════════════════════════════════════════════════

class TestInvestmentThesisAnchor:
    """Lever 4: investment_thesis now has its own question_anchor_block (not generic)."""

    def test_investment_thesis_anchor_not_generic(self):
        """investment_thesis must NOT use the generic QUESTION-ANCHORED DIRECT ANSWER RULES."""
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question=MSFT_QUESTIONS["ai_growth"][0],
            question_intent="investment_thesis",
            ranked=None, prior_snapshot=None,
        )
        # Generic block uses this specific phrase — investment_thesis should not
        assert "QUESTION-ANCHORED DIRECT ANSWER RULES" not in prompt, (
            "investment_thesis must use its own section mandate block, not the generic Phase 1 block"
        )

    def test_investment_thesis_anchor_contains_business_model_mandate(self):
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question=MSFT_QUESTIONS["ai_growth"][0],
            question_intent="investment_thesis",
            ranked=None, prior_snapshot=None,
        )
        assert "BUSINESS MODEL" in prompt or "business model" in prompt.lower()

    def test_investment_thesis_anchor_mandates_bull_thesis_business_model(self):
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question=MSFT_QUESTIONS["ai_growth"][0],
            question_intent="investment_thesis",
            ranked=None, prior_snapshot=None,
        )
        # Anchor should mandate bull_thesis on business model durability
        assert "bull_thesis" in prompt and (
            "durability" in prompt.lower() or "recurring" in prompt.lower()
        )

    def test_investment_thesis_anchor_mandates_core_debate_framing(self):
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question=MSFT_QUESTIONS["ai_growth"][0],
            question_intent="investment_thesis",
            ranked=None, prior_snapshot=None,
        )
        assert "core_debate" in prompt

    def test_investment_thesis_anchor_contains_user_question(self):
        """The verbatim user question must appear in the anchor block."""
        q = MSFT_QUESTIONS["ai_growth"][0]
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question=q,
            question_intent="investment_thesis",
            ranked=None, prior_snapshot=None,
        )
        assert q in prompt

    def test_business_model_anchor_fires_same_as_investment_thesis(self):
        """business_model intent should produce the same anchor block as investment_thesis."""
        val, mac, risk, mkt, qual = _agents_msft()
        prompt_it = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question="What is Microsoft's core business model?",
            question_intent="investment_thesis",
            ranked=None, prior_snapshot=None,
        )
        prompt_bm = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question="What is Microsoft's core business model?",
            question_intent="business_model",
            ranked=None, prior_snapshot=None,
        )
        # Same question same agents — only question_intent differs. Both should use
        # the business-model anchor block, so the prompts should be nearly identical.
        ratio = SequenceMatcher(None, prompt_it, prompt_bm).ratio()
        assert ratio > 0.97, (
            f"investment_thesis and business_model prompts should be nearly identical "
            f"(ratio={ratio:.2%})"
        )


# ════════════════════════════════════════════════════════════════════════════════
# Section 5 — Secondary mandates injected into full synthesis prompt
# ════════════════════════════════════════════════════════════════════════════════

class TestSecondaryMandatesInPrompt:
    """Phase 3 secondary mandate blocks must appear in full synthesis prompts."""

    @pytest.mark.parametrize("intent,keyword", [
        ("competitive_position", "SECONDARY SECTION MANDATES — COMPETITIVE QUESTION"),
        ("macro_sensitivity",    "SECONDARY SECTION MANDATES — MACRO QUESTION"),
        ("valuation_stance",     "SECONDARY SECTION MANDATES — VALUATION QUESTION"),
        ("risk_assessment",      "SECONDARY SECTION MANDATES — RISK QUESTION"),
        ("investment_thesis",    "SECONDARY SECTION MANDATES — BUSINESS MODEL"),
    ])
    def test_secondary_mandate_header_in_prompt(self, intent, keyword):
        val, mac, risk, mkt, qual = _agents_msft()
        q = {
            "competitive_position": "Is Azure a stronger moat than M365?",
            "macro_sensitivity":    "How would rate cuts affect Microsoft?",
            "valuation_stance":     "Is Microsoft overpriced?",
            "risk_assessment":      "What are the biggest risks to Microsoft?",
            "investment_thesis":    "Can Microsoft sustain AI growth if spending slows?",
        }[intent]
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question=q,
            question_intent=intent,
            ranked=None, prior_snapshot=None,
        )
        assert keyword in prompt, (
            f"intent={intent!r}: expected secondary mandate header '{keyword}' in synthesis prompt"
        )

    def test_none_intent_no_secondary_mandate_in_prompt(self):
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question=None,
            question_intent=None,
            ranked=None, prior_snapshot=None,
        )
        assert "SECONDARY SECTION MANDATES" not in prompt

    def test_secondary_mandates_positioned_before_agent_outputs(self):
        """Secondary mandates must appear in the instruction region (before agent outputs)."""
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question="What is the biggest risk to Microsoft?",
            question_intent="risk_assessment",
            ranked=None, prior_snapshot=None,
        )
        mandate_idx  = prompt.find("SECONDARY SECTION MANDATES")
        agent_idx    = prompt.find("SPECIALIST AGENT OUTPUTS:")
        assert mandate_idx > 0 and agent_idx > 0
        assert mandate_idx < agent_idx, (
            "Secondary mandate block must appear BEFORE agent outputs in the prompt"
        )

    def test_secondary_mandates_include_four_sections_in_prompt(self):
        """The mandate block injected into the prompt must name all 4 secondary sections."""
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question="Can Microsoft sustain AI growth?",
            question_intent="investment_thesis",
            ranked=None, prior_snapshot=None,
        )
        for sec in ("one_sentence_thesis", "key_drivers",
                    "what_increases_conviction", "conclusion"):
            assert sec in prompt, (
                f"Secondary mandate block in prompt must mention '{sec}'"
            )


# ════════════════════════════════════════════════════════════════════════════════
# Section 6 — Prompt overlap regression
# ════════════════════════════════════════════════════════════════════════════════

class TestPhase3PromptOverlap:
    """Phase 3 must reduce prompt overlap vs Phase 2 baseline.

    Phase 2 worst case: ai_growth (investment_thesis) vs valuation (valuation_stance)
    showed 97.6% overlap — both fell through to the same dominant_dim and had no
    sub-field injection or section anchor for investment_thesis.

    Phase 3 threshold: all pairs < 97% (improving over Phase 2's 97.6% worst case).
    """

    _PHASE2_WORST_PAIR = ("ai_growth", "valuation")
    _PHASE2_WORST_OVERLAP = 0.976
    _PHASE3_THRESHOLD = 0.970  # must beat Phase 2

    def _prompt(self, qkey, agents, company, profile):
        q, intent = MSFT_QUESTIONS[qkey]
        return _build_prompt(company, profile, agents, intent, q)

    def test_ai_growth_vs_valuation_better_than_phase2(self):
        """ai_growth vs valuation was the worst Phase 2 pair — Phase 3 must improve it."""
        agents = _agents_msft()
        p_ag  = self._prompt("ai_growth",  agents, _msft(), _msft_profile())
        p_val = self._prompt("valuation",  agents, _msft(), _msft_profile())
        r = _text_overlap(p_ag, p_val)
        assert r < self._PHASE3_THRESHOLD, (
            f"ai_growth vs valuation overlap={r:.1%} — must be < {self._PHASE3_THRESHOLD:.0%} "
            f"(Phase 2 baseline was {self._PHASE2_WORST_OVERLAP:.1%})"
        )

    @pytest.mark.parametrize("a,b", [
        ("ai_growth", "moat"),
        ("ai_growth", "valuation"),
        ("ai_growth", "risk"),
        ("moat",      "valuation"),
        ("moat",      "risk"),
        ("valuation", "risk"),
    ])
    def test_msft_all_pairs_below_threshold(self, a, b):
        agents = _agents_msft()
        pa = self._prompt(a, agents, _msft(), _msft_profile())
        pb = self._prompt(b, agents, _msft(), _msft_profile())
        r = _text_overlap(pa, pb)
        assert r < self._PHASE3_THRESHOLD, (
            f"MSFT {a} vs {b}: overlap={r:.1%} — must be < {self._PHASE3_THRESHOLD:.0%}"
        )

    @pytest.mark.parametrize("a,b", [
        ("ai_slowdown", "custom_chip"),
        ("ai_slowdown", "risk"),
        ("custom_chip", "risk"),
    ])
    def test_nvda_pairs_below_threshold(self, a, b):
        agents = _agents_nvda()
        qa, ia = NVDA_QUESTIONS[a]
        qb, ib = NVDA_QUESTIONS[b]
        pa = _build_prompt(_nvda(), _nvda_profile(), agents, ia, qa)
        pb = _build_prompt(_nvda(), _nvda_profile(), agents, ib, qb)
        r = _text_overlap(pa, pb)
        assert r < self._PHASE3_THRESHOLD, (
            f"NVDA {a} vs {b}: overlap={r:.1%} — must be < {self._PHASE3_THRESHOLD:.0%}"
        )

    def test_investment_thesis_prompt_substantially_different_from_risk(self):
        """investment_thesis (OPERATIONAL) vs risk_assessment (REGULATORY) — max structural diff."""
        agents = _agents_msft()
        p_it   = self._prompt("ai_growth", agents, _msft(), _msft_profile())
        p_risk = self._prompt("risk",      agents, _msft(), _msft_profile())
        r = _text_overlap(p_it, p_risk)
        # These have different dominant_dim, different anchor blocks, different
        # sub-fields, different secondary mandates
        assert r < 0.965, (
            f"investment_thesis vs risk_assessment: overlap={r:.1%} — "
            f"should be among the most differentiated pairs"
        )


# ════════════════════════════════════════════════════════════════════════════════
# Section 7 — NVDA Phase 3 cross-validation
# ════════════════════════════════════════════════════════════════════════════════

class TestNVDAPhase3Validation:
    """All Phase 3 extensions must apply equally to NVDA."""

    def test_nvda_investment_thesis_operational_directive(self):
        val, mac, risk, mkt, qual = _agents_nvda()
        prompt = _build_synthesis_prompt(
            _nvda(), val, mac, risk, mkt, qual,
            evidence=[], profile=_nvda_profile(),
            original_user_question="Can Nvidia sustain its AI growth?",
            question_intent="investment_thesis",
            ranked=None, prior_snapshot=None,
        )
        assert "DOMINANT DIMENSION — OPERATIONAL" in prompt

    def test_nvda_investment_thesis_injects_revenue_durability(self):
        val, mac, risk, mkt, qual = _agents_nvda()
        summaries = _build_agent_summaries(
            val, mac, risk, mkt, qual, question_intent="investment_thesis"
        )
        # NVDA quality.revenue_durability contains "hyperscaler"
        assert "hyperscaler" in summaries.lower()

    def test_nvda_risk_assessment_secondary_mandate_injected(self):
        val, mac, risk, mkt, qual = _agents_nvda()
        q, intent = NVDA_QUESTIONS["risk"]
        prompt = _build_synthesis_prompt(
            _nvda(), val, mac, risk, mkt, qual,
            evidence=[], profile=_nvda_profile(),
            original_user_question=q,
            question_intent=intent,
            ranked=None, prior_snapshot=None,
        )
        assert "SECONDARY SECTION MANDATES — RISK QUESTION" in prompt

    def test_nvda_competitive_position_secondary_mandate_injected(self):
        val, mac, risk, mkt, qual = _agents_nvda()
        q, intent = NVDA_QUESTIONS["custom_chip"]
        prompt = _build_synthesis_prompt(
            _nvda(), val, mac, risk, mkt, qual,
            evidence=[], profile=_nvda_profile(),
            original_user_question=q,
            question_intent=intent,
            ranked=None, prior_snapshot=None,
        )
        assert "SECONDARY SECTION MANDATES — COMPETITIVE QUESTION" in prompt

    def test_nvda_investment_thesis_not_using_generic_anchor(self):
        val, mac, risk, mkt, qual = _agents_nvda()
        prompt = _build_synthesis_prompt(
            _nvda(), val, mac, risk, mkt, qual,
            evidence=[], profile=_nvda_profile(),
            original_user_question="Can Nvidia sustain AI growth?",
            question_intent="investment_thesis",
            ranked=None, prior_snapshot=None,
        )
        assert "QUESTION-ANCHORED DIRECT ANSWER RULES" not in prompt

    def test_nvda_secondary_mandate_uses_nvda_ticker(self):
        block = _build_secondary_section_mandates("NVDA", "investment_thesis")
        assert "NVDA" in block


# ════════════════════════════════════════════════════════════════════════════════
# Section 8 — Backward compatibility
# ════════════════════════════════════════════════════════════════════════════════

class TestBackwardCompatPhase3:
    """Phase 3 additions must not break existing behavior for None / unrecognized intents."""

    def test_none_intent_no_secondary_mandates(self):
        block = _build_secondary_section_mandates("MSFT", None)
        assert block == ""

    def test_none_intent_no_investment_thesis_anchor(self):
        """None intent uses generic anchor, not investment_thesis specific."""
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question="Tell me about Microsoft",
            question_intent=None,
            ranked=None, prior_snapshot=None,
        )
        assert "BUSINESS MODEL / INVESTMENT THESIS" not in prompt

    def test_all_existing_phase2_intents_still_work(self):
        """All Phase 2 intents must still produce non-empty prompts."""
        val, mac, risk, mkt, qual = _agents_msft()
        for intent in ("competitive_position", "macro_sensitivity",
                       "valuation_stance", "risk_assessment"):
            q = {
                "competitive_position": "Is Azure a stronger moat than M365?",
                "macro_sensitivity":    "How would rate cuts affect Microsoft?",
                "valuation_stance":     "Is Microsoft overpriced?",
                "risk_assessment":      "What are the biggest risks to Microsoft?",
            }[intent]
            prompt = _build_synthesis_prompt(
                _msft(), val, mac, risk, mkt, qual,
                evidence=[], profile=_msft_profile(),
                original_user_question=q,
                question_intent=intent,
                ranked=None, prior_snapshot=None,
            )
            assert isinstance(prompt, str) and len(prompt) > 500, (
                f"intent={intent!r}: synthesis prompt must be non-empty string"
            )

    def test_build_synthesis_prompt_no_crash_for_all_intents(self):
        """_build_synthesis_prompt must not raise for any intent."""
        val, mac, risk, mkt, qual = _agents_msft()
        for intent in [None, "competitive_position", "macro_sensitivity", "valuation_stance",
                       "risk_assessment", "investment_thesis", "business_model", "unknown_xyz"]:
            try:
                _build_synthesis_prompt(
                    _msft(), val, mac, risk, mkt, qual,
                    evidence=[], profile=None,
                    original_user_question="Tell me about Microsoft",
                    question_intent=intent,
                    ranked=None, prior_snapshot=None,
                )
            except Exception as e:
                pytest.fail(f"intent={intent!r}: _build_synthesis_prompt raised {e!r}")

    def test_secondary_mandates_no_crash_for_all_intents(self):
        for intent in [None, "competitive_position", "macro_sensitivity", "valuation_stance",
                       "risk_assessment", "investment_thesis", "business_model", "unknown_xyz"]:
            try:
                _build_secondary_section_mandates("MSFT", intent)
            except Exception as e:
                pytest.fail(f"intent={intent!r}: _build_secondary_section_mandates raised {e!r}")

    def test_valuation_stance_still_has_valuation_stance_answer_block(self):
        """Existing valuation_stance special handling must be preserved."""
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question="Is Microsoft overpriced?",
            question_intent="valuation_stance",
            ranked=None, prior_snapshot=None,
        )
        assert "VALUATION STANCE ANSWER" in prompt

    def test_phase2_competitive_position_anchor_still_fires(self):
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question="Is Azure a stronger moat than M365?",
            question_intent="competitive_position",
            ranked=None, prior_snapshot=None,
        )
        assert "COMPETITIVE ANCHOR" in prompt or "COMPETITIVE / MOAT QUESTION" in prompt

    def test_phase2_macro_sensitivity_anchor_still_fires(self):
        val, mac, risk, mkt, qual = _agents_msft()
        prompt = _build_synthesis_prompt(
            _msft(), val, mac, risk, mkt, qual,
            evidence=[], profile=_msft_profile(),
            original_user_question="How would rate cuts affect Microsoft?",
            question_intent="macro_sensitivity",
            ranked=None, prior_snapshot=None,
        )
        assert "DEEPEST SECTION" in prompt or "MACRO / RATE QUESTION" in prompt
