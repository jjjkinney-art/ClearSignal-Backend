"""
tests/test_phase6_profiles.py

Regression suite for Phase 6 coverage expansion (35 new profiles).
Tests verify calibration targets, required fields, and keyword engineering.

Run:
    python3 -m pytest tests/test_phase6_profiles.py -v
"""
from __future__ import annotations
import pytest
from app.services.company_knowledge import get_knowledge_profile, list_known_tickers
from app.schemas import CompanyKnowledgeProfile
from tests.test_phase5b_profiles import _compute_layer1   # reuse Layer-1 helper

# ── Tier classification ───────────────────────────────────────────────────────
PHASE6_ALL = [
    "WFC",
    "QCOM","TXN","MU","AMAT","LRCX",
    "MRK","ABT","TMO","PFE","MDT",
    "HD","MCD","SBUX","TGT",
    "ETN","CAT","GE","LMT",
    "PSX","EOG","DVN","MPC","VLO",
    "SRE","PCG","WEC","ED","AWK",
    "TMUS",
    "PSA","EQR","VICI","WELL","AMH",
]
ACCUMULATE_P6 = ["MRK","ABT","TMO","HD","ETN"]
HOLD_P6       = [t for t in PHASE6_ALL if t not in ACCUMULATE_P6]

# ── Keyword constants (mirrors conviction_modeler.py) ────────────────────────
_HQ = (
    "renewal rate","membership","multi-year contract","service contract",
    "subscription","patient adherence","maintenance","management fee",
)
_POS_REC = (
    "stable","resilient","non-discretionary","defensive","essential",
    "counter-cyclical","recession-resistant","maintained dividend",
    "sticky","visibility","non-cyclical","mission-critical","secular",
)
_NEG_REC = (
    "discretionary","fall 30","fall 40","cyclical","steep decline",
    "sensitive to consumer","volatile",
)
_NARRATIVE_VAL = ("optionality","blue-sky","terminal value","platform","option value","speculative")
_BINARY_RISK   = ("binary","regulatory approval","clinical trial","fda approval",
                  "make-or-break","unproven","key-person risk")


def _p(ticker: str) -> CompanyKnowledgeProfile:
    p = get_knowledge_profile(ticker)
    assert p is not None, f"No profile registered for {ticker}"
    return p


# ── Test 1: Registration ──────────────────────────────────────────────────────
class TestPhase6Registration:
    @pytest.mark.parametrize("ticker", PHASE6_ALL)
    def test_profile_exists(self, ticker):
        p = get_knowledge_profile(ticker)
        assert p is not None, f"Phase 6 profile for {ticker} not found"
        assert p.ticker == ticker

    def test_total_count_at_least_100(self):
        assert len(list_known_tickers()) >= 100, "Expected ≥100 profiles after Phase 6"


# ── Test 2: Required fields ───────────────────────────────────────────────────
class TestRequiredFields:
    @pytest.mark.parametrize("ticker", PHASE6_ALL)
    def test_business_model(self, ticker):
        p = _p(ticker)
        assert p.business_model and len(p.business_model) > 50

    @pytest.mark.parametrize("ticker", PHASE6_ALL)
    def test_primary_revenue_drivers(self, ticker):
        assert len(_p(ticker).primary_revenue_drivers) >= 2

    @pytest.mark.parametrize("ticker", PHASE6_ALL)
    def test_recession_behavior(self, ticker):
        assert _p(ticker).recession_behavior

    @pytest.mark.parametrize("ticker", PHASE6_ALL)
    def test_valuation_style(self, ticker):
        assert _p(ticker).valuation_style

    @pytest.mark.parametrize("ticker", PHASE6_ALL)
    def test_rate_sensitivity(self, ticker):
        assert _p(ticker).rate_sensitivity_note


# ── Test 3: Keyword count + company identifier ────────────────────────────────
class TestKeywords:
    @pytest.mark.parametrize("ticker", PHASE6_ALL)
    def test_at_least_12_keywords(self, ticker):
        p = _p(ticker)
        assert len(p.business_model_keywords) >= 12, (
            f"{ticker}: {len(p.business_model_keywords)} keywords, need ≥12"
        )

    @pytest.mark.parametrize("ticker", PHASE6_ALL)
    def test_includes_ticker_or_company_name(self, ticker):
        p = _p(ticker)
        kw_lower = [k.lower() for k in p.business_model_keywords]
        ok = any(ticker.lower() in k or p.company_name.split()[0].lower() in k
                 for k in kw_lower)
        assert ok, f"{ticker}: keywords missing ticker/company identifier"


# ── Test 4: Major risks ───────────────────────────────────────────────────────
class TestMajorRisks:
    @pytest.mark.parametrize("ticker", PHASE6_ALL)
    def test_at_least_4_risks(self, ticker):
        assert len(_p(ticker).major_risks) >= 4, f"{ticker}: need ≥4 major risks"

    @pytest.mark.parametrize("ticker", PHASE6_ALL)
    def test_no_binary_risk_keywords(self, ticker):
        p = _p(ticker)
        text = " ".join(p.major_risks or []).lower()
        hits = [t for t in _BINARY_RISK if t in text]
        assert not hits, f"{ticker}: major_risks contains binary_risk keyword(s) {hits}"


# ── Test 5: Competitive advantages tiering ───────────────────────────────────
class TestAdvantagesTiering:
    @pytest.mark.parametrize("ticker", ACCUMULATE_P6)
    def test_accumulate_has_4plus(self, ticker):
        n = len(_p(ticker).competitive_advantages)
        assert n >= 4, f"{ticker} (Accumulate): {n} advantages, need ≥4"

    @pytest.mark.parametrize("ticker", HOLD_P6)
    def test_hold_has_2_to_3(self, ticker):
        n = len(_p(ticker).competitive_advantages)
        assert 2 <= n <= 3, f"{ticker} (Hold): {n} advantages, need 2–3"


# ── Test 6: Layer-1 durability range ─────────────────────────────────────────
class TestLayer1Range:
    @pytest.mark.parametrize("ticker", ACCUMULATE_P6)
    def test_accumulate_l1_ge_068(self, ticker):
        l1 = _compute_layer1(_p(ticker))
        assert l1 >= 0.68, f"{ticker} (Accumulate): L1={l1:.3f}, need ≥0.68"

    @pytest.mark.parametrize("ticker", HOLD_P6)
    def test_hold_l1_ge_050(self, ticker):
        l1 = _compute_layer1(_p(ticker))
        assert l1 >= 0.50, f"{ticker} (Hold): L1={l1:.3f}, need ≥0.50"

    @pytest.mark.parametrize("ticker", HOLD_P6)
    def test_hold_l1_below_accumulate(self, ticker):
        l1 = _compute_layer1(_p(ticker))
        assert l1 < 0.68, f"{ticker} (Hold): L1={l1:.3f}, must be <0.68"


# ── Test 7: No narrative keywords in valuation_style for Accumulate ───────────
class TestNoNarrativeValuation:
    @pytest.mark.parametrize("ticker", ACCUMULATE_P6)
    def test_no_narrative_keywords(self, ticker):
        vs = (_p(ticker).valuation_style or "").lower()
        hits = [t for t in _NARRATIVE_VAL if t in vs]
        assert not hits, f"{ticker}: valuation_style contains narrative keyword(s) {hits}"


# ── Test 8: Recurring revenue sources calibration ────────────────────────────
class TestRecurringSources:
    @pytest.mark.parametrize("ticker", ACCUMULATE_P6)
    def test_accumulate_hq_signals_fire(self, ticker):
        p = _p(ticker)
        rec = " ".join(p.recurring_revenue_sources or []).lower()
        n_hq = sum(1 for t in _HQ if t in rec)
        n_r  = len(p.recurring_revenue_sources or [])
        fires = n_hq >= 2 or (n_hq >= 1 and n_r >= 3)
        assert fires, (
            f"{ticker}: n_hq={n_hq}, n_r={n_r} — +0.15 bonus not triggered"
        )

    @pytest.mark.parametrize("ticker", HOLD_P6)
    def test_hold_exactly_2_recurring(self, ticker):
        n = len(_p(ticker).recurring_revenue_sources or [])
        assert n == 2, f"{ticker} (Hold): {n} recurring sources, expect exactly 2"

    @pytest.mark.parametrize("ticker", HOLD_P6)
    def test_hold_zero_hq_signals(self, ticker):
        p = _p(ticker)
        rec = " ".join(p.recurring_revenue_sources or []).lower()
        hits = [t for t in _HQ if t in rec]
        assert not hits, (
            f"{ticker} (Hold): recurring_revenue_sources contains HQ signal(s) {hits} "
            f"which would trigger +0.15 instead of +0.08, pushing L1 above Hold range"
        )
