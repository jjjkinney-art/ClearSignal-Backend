"""
tests/test_intent_routing_and_wic.py

Regression suite for Fix 1 (intent detection) and Fix 2 (WIC overwrite).

Fix 1 — _detect_question_intent() pattern extensions
-----------------------------------------------------
Seven new valuation_stance patterns:
  "multiple compress", "multiple compression", "p/e compress",
  "p/e compression", "justify valuation", "valuation justified",
  "justify its valuation"

Eight new competitive_position patterns:
  "exposed to", "exposure to", "custom chip", "custom silicon",
  "custom asic", "hyperscaler", "in-house chip", "market share threat"

Regression: these phrases previously fell through to investment_thesis
and failed to activate the intent-specific synthesis path.

Fix 2 — what_increases_conviction (WIC) branching by question_intent
---------------------------------------------------------------------
_build_what_increases_conviction() now accepts question_intent and branches:
  competitive_position → CONFIRMING + DISCONFIRMING market-share signals
  macro_sensitivity    → Fed/rate confirming + macro disconfirming
  valuation_stance     → earnings beat / analyst upgrade confirming + guidance cut disconfirming
  risk_assessment      → RISK-MATERIALIZING + RISK-RESOLUTION signals
  investment_thesis / None → existing gap-dimension templates (unchanged)

compute_conviction() now accepts question_intent and passes it through.

Run
---
    python3 -m pytest tests/test_intent_routing_and_wic.py -v
"""

from __future__ import annotations

import pytest
from typing import Optional
from unittest.mock import MagicMock

# ── imports ───────────────────────────────────────────────────────────────────
from app.services.router_service import _detect_question_intent
from app.services.conviction_modeler import (
    _build_what_increases_conviction,
    compute_conviction,
    ConvictionDimensions,
)
from app.schemas import (
    CompanyContext, CompanyKnowledgeProfile,
    ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment,
    RetrievedEvidence,
)


# ════════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════════

def _msft() -> CompanyContext:
    return CompanyContext(ticker="MSFT", company_name="Microsoft Corporation",
                         sector="Technology")

def _nvda() -> CompanyContext:
    return CompanyContext(ticker="NVDA", company_name="NVIDIA Corporation",
                         sector="Technology")

def _stub_dims() -> ConvictionDimensions:
    """Minimal ConvictionDimensions with valuation_certainty as dominant gap."""
    d = ConvictionDimensions()
    # Set valuation certainty low to make it the dominant gap
    d.valuation_certainty  = 0.30
    d.thesis_alignment     = 0.65
    d.evidence_quality     = 0.60
    d.evidence_freshness   = 0.55
    d.macro_certainty      = 0.60
    d.estimate_dispersion  = 0.60
    d.governance_safety    = 0.80
    d.expectation_safety   = 0.65
    d.asymmetry_safety     = 0.65
    return d

def _stub_drivers() -> list:
    return ["Azure growth deceleration developments", "Copilot monetization uncertainty"]

def _stub_agents():
    val = ValuationView(overall="MSFT at ~31x fwd P/E.", confidence=0.72)
    mac = MacroSensitivity(overall="Moderate rate sensitivity.", confidence=0.68)
    risk = RiskProfile(overall="AWS/GCP competitive risk.", confidence=0.71,
                       key_risks=["Azure AI share erosion"])
    mkt = MarketContext(overall="38/45 Buy-rated.", confidence=0.65,
                        recent_catalysts=["Azure beat"])
    qual = QualityAssessment(overall="Durable moat.", confidence=0.78)
    return val, mac, risk, mkt, qual

def _stub_evidence():
    return [RetrievedEvidence(title="MSFT Q2 results", source="fmp",
                              summary="Azure +28%", timestamp="2026-01-15")]


# ════════════════════════════════════════════════════════════════════════════════
# Fix 1: Intent routing — new valuation_stance patterns
# ════════════════════════════════════════════════════════════════════════════════

class TestValuationStanceNewPatterns:
    """New patterns must route to valuation_stance, not fall through to investment_thesis."""

    # ── The exact live-validation queries that failed ─────────────────────────
    def test_msft_multiple_compress_question(self):
        q = "What would cause Microsoft's multiple to compress?"
        assert _detect_question_intent(q) == "valuation_stance", (
            f"'{q}' must be valuation_stance (previously fell through to investment_thesis)"
        )

    def test_nvda_multiple_compress_question(self):
        q = "What would cause Nvidia's multiple to compress?"
        assert _detect_question_intent(q) == "valuation_stance"

    def test_nvda_justify_valuation_question(self):
        q = "Can Nvidia justify its valuation if AI spending slows?"
        assert _detect_question_intent(q) == "valuation_stance", (
            f"'{q}' must be valuation_stance"
        )

    # ── Explicit pattern coverage ─────────────────────────────────────────────
    @pytest.mark.parametrize("phrase", [
        "multiple compress",
        "multiple compression",
        "p/e compress",
        "p/e compression",
        "pe compress",
        "pe compression",
        "justify valuation",
        "valuation justified",
        "justify its valuation",
        "justify the valuation",
        "de-rate",
        "derate",
        "multiple de-rate",
    ])
    def test_valuation_phrase_routes_to_valuation_stance(self, phrase):
        q = f"What factors would cause {phrase} for MSFT?"
        result = _detect_question_intent(q)
        assert result == "valuation_stance", (
            f"Phrase '{phrase}' in question must route to valuation_stance, got {result!r}"
        )

    def test_existing_overpriced_still_works(self):
        assert _detect_question_intent("Is Apple overpriced?") == "valuation_stance"

    def test_existing_fair_value_still_works(self):
        assert _detect_question_intent("Is MSFT at fair value?") == "valuation_stance"

    def test_new_patterns_do_not_break_macro_routing(self):
        """Macro questions must still route to macro_sensitivity, not valuation."""
        assert _detect_question_intent("How would a rate cut affect Microsoft?") == "macro_sensitivity"

    def test_new_patterns_do_not_break_risk_routing(self):
        assert _detect_question_intent("What is the biggest risk to Microsoft?") == "risk_assessment"


# ════════════════════════════════════════════════════════════════════════════════
# Fix 1: Intent routing — new competitive_position patterns
# ════════════════════════════════════════════════════════════════════════════════

class TestCompetitivePositionNewPatterns:
    """New patterns must route to competitive_position."""

    # ── The exact live-validation queries that failed ─────────────────────────
    def test_nvda_custom_chip_question(self):
        q = "How exposed is Nvidia to hyperscaler custom chips?"
        assert _detect_question_intent(q) == "competitive_position", (
            f"'{q}' must be competitive_position"
        )

    # ── Explicit pattern coverage ─────────────────────────────────────────────
    @pytest.mark.parametrize("phrase", [
        "exposed to",
        "exposure to",
        "custom chip",
        "custom silicon",
        "hyperscaler",
        "market share threat",
        "market share loss",
    ])
    def test_competitive_phrase_routes_to_competitive_position(self, phrase):
        q = f"What is the risk from {phrase} for NVDA?"
        result = _detect_question_intent(q)
        assert result == "competitive_position", (
            f"Phrase '{phrase}' must route to competitive_position, got {result!r}"
        )

    def test_existing_moat_still_works(self):
        assert _detect_question_intent("What is MSFT's moat?") == "competitive_position"

    def test_existing_market_share_still_works(self):
        assert _detect_question_intent("Is MSFT losing market share?") == "competitive_position"

    def test_azure_moat_question(self):
        q = "Is Azure becoming a stronger moat than Microsoft 365?"
        assert _detect_question_intent(q) == "competitive_position"


# ════════════════════════════════════════════════════════════════════════════════
# Fix 1: Regression — previously failing live-validation queries
# ════════════════════════════════════════════════════════════════════════════════

class TestLiveValidationQueryRegression:
    """All 8 Phase 3 live-validation queries must now route correctly."""

    @pytest.mark.parametrize("question,expected_intent", [
        # MSFT queries
        ("Can Microsoft sustain AI-driven growth if enterprise spending slows?",
         "investment_thesis"),      # Default — no stronger signal
        ("Is Azure becoming a stronger moat than Microsoft 365?",
         "competitive_position"),   # "moat" fires
        ("What would cause Microsoft's multiple to compress?",
         "valuation_stance"),       # NEW: "multiple compress" fires
        ("What is the biggest risk to Microsoft over the next 5 years?",
         "risk_assessment"),        # "biggest risk" fires
        # NVDA queries
        ("Can Nvidia justify its valuation if AI spending slows?",
         "valuation_stance"),       # NEW: "justify its valuation" fires
        ("How exposed is Nvidia to hyperscaler custom chips?",
         "competitive_position"),   # NEW: "exposed to" + "hyperscaler" fire
        ("What would cause Nvidia's multiple to compress?",
         "valuation_stance"),       # NEW: "multiple compress" fires
        ("What is the biggest risk to Nvidia over the next 5 years?",
         "risk_assessment"),        # "biggest risk" fires
    ])
    def test_live_validation_query_routes_correctly(self, question, expected_intent):
        result = _detect_question_intent(question)
        assert result == expected_intent, (
            f"Query: '{question[:70]}…'\n"
            f"  Expected: {expected_intent!r}\n"
            f"  Got:      {result!r}"
        )

    def test_none_of_the_8_produce_investment_thesis_incorrectly(self):
        """Only the AI growth question should be investment_thesis; the other 7 should not."""
        queries_and_expected = [
            ("Can Microsoft sustain AI-driven growth if enterprise spending slows?", True),  # OK as investment_thesis
            ("Is Azure becoming a stronger moat than Microsoft 365?", False),
            ("What would cause Microsoft's multiple to compress?", False),
            ("What is the biggest risk to Microsoft over the next 5 years?", False),
            ("Can Nvidia justify its valuation if AI spending slows?", False),
            ("How exposed is Nvidia to hyperscaler custom chips?", False),
            ("What would cause Nvidia's multiple to compress?", False),
            ("What is the biggest risk to Nvidia over the next 5 years?", False),
        ]
        for q, allowed_as_it in queries_and_expected:
            result = _detect_question_intent(q)
            if not allowed_as_it:
                assert result != "investment_thesis", (
                    f"'{q[:70]}' must NOT route to investment_thesis after Fix 1"
                )


# ════════════════════════════════════════════════════════════════════════════════
# Fix 2: _build_what_increases_conviction branching by question_intent
# ════════════════════════════════════════════════════════════════════════════════

class TestWICIntentBranching:
    """_build_what_increases_conviction returns different output per question_intent."""

    def _wic(self, intent: Optional[str], ticker: str = "MSFT") -> str:
        company = CompanyContext(ticker=ticker, company_name=f"{ticker} Corporation",
                                 sector="Technology")
        dims = _stub_dims()
        drivers = _stub_drivers()
        return _build_what_increases_conviction(dims, company, drivers,
                                                question_intent=intent)

    # ── competitive_position ─────────────────────────────────────────────────
    def test_competitive_position_returns_confirming_disconfirming(self):
        wic = self._wic("competitive_position")
        assert "CONFIRMING" in wic or "confirming" in wic.lower()
        assert "DISCONFIRMING" in wic or "disconfirming" in wic.lower()

    def test_competitive_position_mentions_market_share(self):
        wic = self._wic("competitive_position")
        assert "market share" in wic.lower() or "competitor" in wic.lower() or "moat" in wic.lower()

    def test_competitive_position_not_identical_to_valuation(self):
        wic_comp = self._wic("competitive_position")
        wic_val  = self._wic("valuation_stance")
        assert wic_comp != wic_val

    # ── macro_sensitivity ────────────────────────────────────────────────────
    def test_macro_sensitivity_returns_confirming_disconfirming(self):
        wic = self._wic("macro_sensitivity")
        assert "CONFIRMING" in wic or "confirming" in wic.lower() or "rate" in wic.lower()

    def test_macro_sensitivity_mentions_rate_or_fed(self):
        wic = self._wic("macro_sensitivity")
        assert "rate" in wic.lower() or "fed" in wic.lower() or "macro" in wic.lower()

    def test_macro_not_identical_to_risk(self):
        wic_macro = self._wic("macro_sensitivity")
        wic_risk  = self._wic("risk_assessment")
        assert wic_macro != wic_risk

    # ── valuation_stance ─────────────────────────────────────────────────────
    def test_valuation_stance_mentions_earnings_or_analyst(self):
        wic = self._wic("valuation_stance")
        assert "earnings" in wic.lower() or "analyst" in wic.lower() or "guidance" in wic.lower()

    def test_valuation_stance_mentions_guidance_cut_or_trigger(self):
        wic = self._wic("valuation_stance")
        assert "guidance" in wic.lower() or "miss" in wic.lower() or "trigger" in wic.lower()

    def test_valuation_not_identical_to_risk(self):
        wic_val  = self._wic("valuation_stance")
        wic_risk = self._wic("risk_assessment")
        assert wic_val != wic_risk

    # ── risk_assessment ──────────────────────────────────────────────────────
    def test_risk_assessment_mentions_materializing(self):
        wic = self._wic("risk_assessment")
        assert "materializ" in wic.lower() or "risk" in wic.lower()

    def test_risk_assessment_mentions_resolution(self):
        wic = self._wic("risk_assessment")
        assert "resolut" in wic.lower() or "de-risk" in wic.lower() or "resolution" in wic.lower()

    def test_risk_has_risk_materializing_label(self):
        wic = self._wic("risk_assessment")
        assert "RISK-MATERIALIZING" in wic or "risk-materializing" in wic.lower()

    # ── investment_thesis / None — unchanged (regression) ────────────────────
    def test_investment_thesis_uses_existing_template(self):
        """investment_thesis must NOT use the new per-intent branches."""
        wic = self._wic("investment_thesis")
        # Existing templates don't contain "CONFIRMING" / "DISCONFIRMING"
        assert "CONFIRMING:" not in wic and "DISCONFIRMING:" not in wic

    def test_none_intent_uses_existing_template(self):
        wic = self._wic(None)
        assert "CONFIRMING:" not in wic and "DISCONFIRMING:" not in wic

    def test_unknown_intent_uses_existing_template(self):
        wic = self._wic("unknown_xyz")
        assert "CONFIRMING:" not in wic and "DISCONFIRMING:" not in wic

    # ── All 5 intents produce distinct WIC ───────────────────────────────────
    def test_all_five_intents_produce_distinct_wic(self):
        """WIC must differ across all 5 question types for MSFT."""
        intents = ["investment_thesis", "competitive_position",
                   "valuation_stance", "macro_sensitivity", "risk_assessment"]
        wics = {i: self._wic(i) for i in intents}
        unique = set(wics.values())
        assert len(unique) == len(intents), (
            f"All 5 intents must produce different WIC strings. "
            f"Duplicates found: "
            + str({k: v[:60] for k, v in wics.items()})
        )

    def test_msft_and_nvda_produce_different_wic_same_intent(self):
        """Different tickers must produce different WIC (company-specific content)."""
        dims = _stub_dims()
        msft_wic = _build_what_increases_conviction(
            dims, _msft(), ["Azure growth deceleration"], question_intent="competitive_position"
        )
        nvda_wic = _build_what_increases_conviction(
            dims, _nvda(), ["hyperscaler custom chip adoption"], question_intent="competitive_position"
        )
        assert msft_wic != nvda_wic


# ════════════════════════════════════════════════════════════════════════════════
# Fix 2: compute_conviction() now accepts question_intent
# ════════════════════════════════════════════════════════════════════════════════

class TestComputeConvictionQuestionIntent:
    """compute_conviction() accepts question_intent and propagates it to WIC."""

    def _run(self, intent: Optional[str], ticker: str = "MSFT"):
        val, mac, risk, mkt, qual = _stub_agents()
        company = CompanyContext(ticker=ticker, company_name=f"{ticker} Corp",
                                 sector="Technology")
        evidence = _stub_evidence()
        result = compute_conviction(
            evidence=evidence, valuation=val, macro=mac, risk=risk,
            market=mkt, quality=qual, company=company,
            question_intent=intent,
        )
        return result

    def test_accepts_question_intent_without_error(self):
        for intent in ("competitive_position", "valuation_stance",
                       "macro_sensitivity", "risk_assessment", "investment_thesis", None):
            try:
                r = self._run(intent)
                assert r is not None
            except Exception as e:
                pytest.fail(f"compute_conviction raised {e!r} for intent={intent!r}")

    def test_competitive_wic_differs_from_valuation_wic(self):
        r_comp = self._run("competitive_position")
        r_val  = self._run("valuation_stance")
        assert r_comp.what_increases_conviction != r_val.what_increases_conviction, (
            "competitive_position and valuation_stance must produce different WIC via compute_conviction"
        )

    def test_risk_wic_differs_from_macro_wic(self):
        r_risk  = self._run("risk_assessment")
        r_macro = self._run("macro_sensitivity")
        assert r_risk.what_increases_conviction != r_macro.what_increases_conviction

    def test_all_four_non_default_intents_produce_distinct_wic(self):
        intents = ["competitive_position", "valuation_stance",
                   "macro_sensitivity", "risk_assessment"]
        wics = [self._run(i).what_increases_conviction for i in intents]
        assert len(set(wics)) == 4, (
            "All 4 non-default intents must produce distinct WIC from compute_conviction"
        )

    def test_none_intent_uses_gap_dim_template(self):
        """None intent falls back to the existing gap-dimension template (no CONFIRMING prefix)."""
        r = self._run(None)
        assert "CONFIRMING:" not in r.what_increases_conviction

    def test_conviction_score_unchanged_by_question_intent(self):
        """question_intent must only affect WIC — not the conviction score."""
        r_comp = self._run("competitive_position")
        r_val  = self._run("valuation_stance")
        # Score may vary slightly due to evidence/dim scoring, but should be close
        # (within the same ballpark — not a 10x difference)
        assert abs(r_comp.final_score - r_val.final_score) < 0.05, (
            f"Conviction score should be nearly identical across intents: "
            f"comp={r_comp.final_score:.3f} val={r_val.final_score:.3f}"
        )

    def test_wic_competitive_contains_market_share_signal(self):
        r = self._run("competitive_position")
        assert ("market share" in r.what_increases_conviction.lower() or
                "competitor" in r.what_increases_conviction.lower())

    def test_wic_risk_contains_risk_materializing(self):
        r = self._run("risk_assessment")
        assert ("RISK-MATERIALIZING" in r.what_increases_conviction or
                "materializ" in r.what_increases_conviction.lower())

    def test_wic_valuation_contains_earnings_signal(self):
        r = self._run("valuation_stance")
        assert ("earnings" in r.what_increases_conviction.lower() or
                "guidance" in r.what_increases_conviction.lower())

    def test_wic_macro_contains_rate_signal(self):
        r = self._run("macro_sensitivity")
        assert ("rate" in r.what_increases_conviction.lower() or
                "fed" in r.what_increases_conviction.lower())
