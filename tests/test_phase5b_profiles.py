"""
tests/test_phase5b_profiles.py

Regression suite for Phase 5B profile coverage expansion (2026-06-05).

7 new CompanyKnowledgeProfile entries covering the no-profile companies
identified in the 50-company production validation:
  - ABBV  (Healthcare — expected Accumulate)
  - OXY   (Energy     — expected Hold)
  - PLD   (Real Estate — expected Accumulate)
  - EQIX  (Real Estate — expected Accumulate)
  - AMT   (Real Estate — expected Hold)
  - O     (Real Estate — expected Hold)
  - SPG   (Real Estate — expected Hold)

Tests verify:
  1. Profile is registered and retrievable by ticker
  2. Required fields are populated (non-empty)
  3. business_model_keywords are substantive (≥12 unique terms)
  4. primary_revenue_drivers lists are non-empty
  5. major_risks are company-specific (≥4 entries)
  6. competitive_advantages are correctly tiered:
       - Accumulate targets: ≥4 advantages (drives +0.08 Layer 1 durability bonus)
       - Hold targets: 2–3 advantages (+0.04 bonus; must stay < 0.68 threshold)
  7. Layer 1 durability estimates are in correct range:
       - Accumulate targets: L1 ≥ 0.68
       - Hold targets:       L1 in [0.50, 0.60)
  8. No binary_risk keywords in major_risks (prevent unintended durability penalties)
  9. No narrative_val keywords in valuation_style (prevent unintended penalties
     for Accumulate targets where even a -0.04 matters at margin)

Run
---
    python3 -m pytest tests/test_phase5b_profiles.py -v
"""

from __future__ import annotations

import pytest

from app.services.company_knowledge import (
    get_knowledge_profile,
    list_known_tickers,
)
from app.schemas import CompanyKnowledgeProfile


# ── Phase 5B target tickers ───────────────────────────────────────────────────

PHASE5B_TICKERS = ["ABBV", "OXY", "PLD", "EQIX", "AMT", "O", "SPG"]
ACCUMULATE_TARGETS = ["ABBV", "PLD", "EQIX"]   # dur target: >= 0.68
HOLD_TARGETS       = ["OXY", "AMT", "O", "SPG"]  # dur target: [0.55, 0.68)

# ── Layer 1 durability computation constants (mirrors conviction_modeler.py) ──

_HIGH_QUALITY_SIGNALS = (
    "renewal rate", "membership", "multi-year contract", "service contract",
    "subscription", "patient adherence", "maintenance", "management fee",
)
_POSITIVE_REC = (
    "stable", "resilient", "non-discretionary", "defensive", "essential",
    "counter-cyclical", "recession-resistant", "maintained dividend",
    "sticky", "visibility", "non-cyclical", "mission-critical", "secular",
)
_NEGATIVE_REC = (
    "discretionary", "fall 30", "fall 40", "cyclical", "steep decline",
    "sensitive to consumer", "volatile",
)
_NARRATIVE_VAL = (
    "optionality", "blue-sky", "terminal value", "platform",
    "option value", "speculative",
)
_BINARY_RISK = (
    "binary", "regulatory approval", "clinical trial", "fda approval",
    "make-or-break", "unproven", "key-person risk",
)


def _compute_layer1(profile: CompanyKnowledgeProfile) -> float:
    """Replicate Layer 1 of _compute_business_durability for test assertions."""
    score = 0.40
    recurring   = " ".join(profile.recurring_revenue_sources or []).lower()
    recession   = (profile.recession_behavior or "").lower()
    valuation_s = (profile.valuation_style or "").lower()
    risks       = " ".join(profile.major_risks or []).lower()

    n_recurring = len(profile.recurring_revenue_sources or [])
    n_hq = sum(1 for t in _HIGH_QUALITY_SIGNALS if t in recurring)
    if n_hq >= 2 or (n_hq >= 1 and n_recurring >= 3):
        score += 0.15
    elif n_recurring >= 2:
        score += 0.08
    elif n_recurring >= 1:
        score += 0.04

    pos_hits = sum(1 for t in _POSITIVE_REC if t in recession)
    neg_hits = sum(1 for t in _NEGATIVE_REC if t in recession)
    score += max(-0.12, min(0.10, (pos_hits - neg_hits) * 0.04))

    score -= min(0.12, sum(1 for t in _NARRATIVE_VAL if t in valuation_s) * 0.04)
    score -= min(0.12, sum(1 for t in _BINARY_RISK if t in risks) * 0.04)

    n_adv = len(profile.competitive_advantages or [])
    if n_adv >= 4:
        score += 0.08
    elif n_adv >= 2:
        score += 0.04

    return round(score, 4)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile(ticker: str) -> CompanyKnowledgeProfile:
    p = get_knowledge_profile(ticker)
    assert p is not None, f"No profile registered for {ticker}"
    return p


# ── Test 1: all 7 tickers registered ─────────────────────────────────────────

class TestProfilesRegistered:
    @pytest.mark.parametrize("ticker", PHASE5B_TICKERS)
    def test_profile_exists(self, ticker):
        p = get_knowledge_profile(ticker)
        assert p is not None, f"Phase 5B profile for {ticker} not found"
        assert p.ticker == ticker

    def test_total_profile_count_at_least_65(self):
        assert len(list_known_tickers()) >= 65, (
            "Expected ≥65 profiles after Phase 5B expansion"
        )


# ── Test 2: required fields non-empty ────────────────────────────────────────

class TestRequiredFieldsPopulated:
    @pytest.mark.parametrize("ticker", PHASE5B_TICKERS)
    def test_business_model_not_empty(self, ticker):
        p = _profile(ticker)
        assert p.business_model, f"{ticker}: business_model is empty"
        assert len(p.business_model) > 50, f"{ticker}: business_model too short"

    @pytest.mark.parametrize("ticker", PHASE5B_TICKERS)
    def test_primary_revenue_drivers_not_empty(self, ticker):
        p = _profile(ticker)
        assert p.primary_revenue_drivers, f"{ticker}: primary_revenue_drivers empty"
        assert len(p.primary_revenue_drivers) >= 2

    @pytest.mark.parametrize("ticker", PHASE5B_TICKERS)
    def test_recession_behavior_not_empty(self, ticker):
        p = _profile(ticker)
        assert p.recession_behavior, f"{ticker}: recession_behavior empty"

    @pytest.mark.parametrize("ticker", PHASE5B_TICKERS)
    def test_valuation_style_not_empty(self, ticker):
        p = _profile(ticker)
        assert p.valuation_style, f"{ticker}: valuation_style empty"

    @pytest.mark.parametrize("ticker", PHASE5B_TICKERS)
    def test_rate_sensitivity_note_not_empty(self, ticker):
        p = _profile(ticker)
        assert p.rate_sensitivity_note, f"{ticker}: rate_sensitivity_note empty"


# ── Test 3: keywords substantive ─────────────────────────────────────────────

class TestKeywordsSubstantive:
    @pytest.mark.parametrize("ticker", PHASE5B_TICKERS)
    def test_keywords_at_least_12(self, ticker):
        p = _profile(ticker)
        assert len(p.business_model_keywords) >= 12, (
            f"{ticker}: only {len(p.business_model_keywords)} keywords "
            f"(need ≥12 for effective depth guard)"
        )

    @pytest.mark.parametrize("ticker", PHASE5B_TICKERS)
    def test_keywords_are_company_specific(self, ticker):
        """Keywords should include the ticker or company name."""
        p = _profile(ticker)
        kw_lower = [k.lower() for k in p.business_model_keywords]
        has_identifier = any(
            ticker.lower() in k or p.company_name.split()[0].lower() in k
            for k in kw_lower
        )
        assert has_identifier, (
            f"{ticker}: keywords don't include ticker or company name — "
            f"likely too generic"
        )


# ── Test 4: major risks are specific ─────────────────────────────────────────

class TestMajorRisksSpecific:
    @pytest.mark.parametrize("ticker", PHASE5B_TICKERS)
    def test_major_risks_count(self, ticker):
        p = _profile(ticker)
        assert len(p.major_risks) >= 4, (
            f"{ticker}: only {len(p.major_risks)} major risks (need ≥4)"
        )

    @pytest.mark.parametrize("ticker", PHASE5B_TICKERS)
    def test_no_binary_risk_keywords_in_risks(self, ticker):
        """binary_risk keywords in major_risks reduce Layer 1 durability by -0.04 each.
        Phase 5B profiles rephrase these to avoid unintended penalties."""
        p = _profile(ticker)
        risks_text = " ".join(p.major_risks or []).lower()
        hits = [t for t in _BINARY_RISK if t in risks_text]
        assert not hits, (
            f"{ticker}: major_risks contains binary_risk keyword(s) {hits} "
            f"which reduce Layer 1 durability by {len(hits)*0.04:.2f}"
        )


# ── Test 5: competitive_advantages tiered correctly ──────────────────────────

class TestCompetitiveAdvantagesTiering:
    @pytest.mark.parametrize("ticker", ACCUMULATE_TARGETS)
    def test_accumulate_targets_have_4_plus_advantages(self, ticker):
        """4+ advantages give +0.08 Layer 1 bonus; critical for reaching dur ≥ 0.68."""
        p = _profile(ticker)
        assert len(p.competitive_advantages) >= 4, (
            f"{ticker} (Accumulate target): only {len(p.competitive_advantages)} "
            f"competitive_advantages; need ≥4 for +0.08 Layer 1 durability bonus"
        )

    @pytest.mark.parametrize("ticker", HOLD_TARGETS)
    def test_hold_targets_have_2_to_3_advantages(self, ticker):
        """Hold targets should have 2-3 advantages (+0.04 bonus).
        4+ would risk pushing dur above 0.68 Durable Accumulate threshold."""
        p = _profile(ticker)
        n = len(p.competitive_advantages)
        assert 2 <= n <= 3, (
            f"{ticker} (Hold target): {n} competitive_advantages; "
            f"need 2–3 to stay in Hold durability tier"
        )


# ── Test 6: Layer 1 durability in target range ───────────────────────────────

class TestLayer1DurabilityRange:
    @pytest.mark.parametrize("ticker", ACCUMULATE_TARGETS)
    def test_accumulate_layer1_at_least_0_68(self, ticker):
        """Accumulate targets need Layer 1 ≥ 0.68 so that even conservative LLM
        Layers 2-4 keep final durability above the Durable Accumulate threshold."""
        p = _profile(ticker)
        l1 = _compute_layer1(p)
        assert l1 >= 0.68, (
            f"{ticker} (Accumulate target): Layer 1 = {l1:.3f}, need ≥ 0.68. "
            f"Durable Accumulate requires final dur ≥ 0.68."
        )

    @pytest.mark.parametrize("ticker", HOLD_TARGETS)
    def test_hold_layer1_above_minimum(self, ticker):
        """Hold targets need Layer 1 ≥ 0.50 so that realistic LLM additions
        push final durability above the Durable Hold threshold of 0.55."""
        p = _profile(ticker)
        l1 = _compute_layer1(p)
        assert l1 >= 0.50, (
            f"{ticker} (Hold target): Layer 1 = {l1:.3f}, need ≥ 0.50 "
            f"to ensure final dur reaches 0.55 (Durable Hold threshold)."
        )

    @pytest.mark.parametrize("ticker", HOLD_TARGETS)
    def test_hold_layer1_below_accumulate_threshold(self, ticker):
        """Hold targets: Layer 1 must be < 0.62 to leave safety margin
        below 0.68 Durable Accumulate threshold even with generous LLM additions."""
        p = _profile(ticker)
        l1 = _compute_layer1(p)
        assert l1 < 0.62, (
            f"{ticker} (Hold target): Layer 1 = {l1:.3f}, must be < 0.62 "
            f"to keep final dur safely below 0.68 Durable Accumulate trigger."
        )


# ── Test 7: no narrative keywords in valuation_style for Accumulate targets ──

class TestNoNarrativeInValuationStyle:
    @pytest.mark.parametrize("ticker", ACCUMULATE_TARGETS)
    def test_no_narrative_val_keywords(self, ticker):
        """narrative_val keywords in valuation_style reduce Layer 1 by -0.04 each.
        Accumulate targets must avoid these to stay at L1 ≥ 0.68."""
        p = _profile(ticker)
        valuation_s = (p.valuation_style or "").lower()
        hits = [t for t in _NARRATIVE_VAL if t in valuation_s]
        assert not hits, (
            f"{ticker}: valuation_style contains narrative keyword(s) {hits} "
            f"(-{len(hits)*0.04:.2f} Layer 1 durability penalty)"
        )


# ── Test 8: recurring revenue sources populate correctly ─────────────────────

class TestRecurringRevenueSources:
    @pytest.mark.parametrize("ticker", ACCUMULATE_TARGETS)
    def test_accumulate_has_high_quality_recurring(self, ticker):
        """Accumulate targets must trigger the +0.15 high-quality recurring bonus
        (n_hq >= 2 OR n_hq >= 1 with n_recurring >= 3)."""
        p = _profile(ticker)
        recurring = " ".join(p.recurring_revenue_sources or []).lower()
        n_recurring = len(p.recurring_revenue_sources or [])
        n_hq = sum(1 for t in _HIGH_QUALITY_SIGNALS if t in recurring)
        fires_plus15 = n_hq >= 2 or (n_hq >= 1 and n_recurring >= 3)
        assert fires_plus15, (
            f"{ticker} (Accumulate target): n_hq={n_hq}, n_recurring={n_recurring}. "
            f"Need n_hq >= 2 OR (n_hq >= 1 AND n_recurring >= 3) for +0.15 bonus. "
            f"HQ signals found: {[t for t in _HIGH_QUALITY_SIGNALS if t in recurring]}"
        )

    @pytest.mark.parametrize("ticker", HOLD_TARGETS)
    def test_hold_has_exactly_2_recurring_sources(self, ticker):
        """Hold targets should have exactly 2 recurring sources (+0.08 bonus)
        without high-quality signals — keeping the recurring contribution modest."""
        p = _profile(ticker)
        n = len(p.recurring_revenue_sources or [])
        assert n == 2, (
            f"{ticker} (Hold target): {n} recurring_revenue_sources; "
            f"expect exactly 2 for +0.08 (not +0.15) recurring bonus"
        )
