"""
tests/validate_100_company.py

100-company production validation across 10 sectors.
Uses conviction engine directly with sector-calibrated synthetic inputs.
No live LLM required — conviction model behavior is deterministic given inputs.

Methodology
-----------
Each company receives sector-appropriate synthetic inputs:
  - ACCUMULATE tier: strong durability signals (recurring, moat, pricing power,
    mission-critical, free cash flow), quality confidence 0.72
  - HOLD tier: moderate signals (stable, consistent, some cyclical exposure),
    quality confidence 0.60
  - val_stance: ALL companies use "fairly_valued" vocabulary
    (AFFO/FFO/P/E/FCF language — no "value"/"overvalued"/"cheap" keywords)

This matches Phase 5B approach: the /analyze API synthesises LLM text → feeds
conviction engine. Here we skip the LLM and go directly to conviction engine
with equivalent-quality text. Results are reproducible and reveal architectural
patterns that live LLM calls would obscure with session-to-session variance.

Run
---
    python3 tests/validate_100_company.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, ".")

from app.schemas import (
    QualityAssessment, MacroSensitivity, RiskProfile,
    ValuationView, MarketContext, RetrievedEvidence, CompanyContext,
    CompanyKnowledgeProfile,
)
from app.services.conviction_modeler import (
    compute_conviction,
    _compute_business_durability,
    _classify_expectation_regime,
    _score_expectation_fragility,
)
from app.services.company_knowledge import get_knowledge_profile

TODAY = datetime.now(timezone.utc).isoformat()

# ─────────────────────────────────────────────────────────────────────────────
# 100-COMPANY UNIVERSE  (sector, expected_stance, tier)
# tier: "A" = expected Accumulate, "H" = expected Hold
# ─────────────────────────────────────────────────────────────────────────────
UNIVERSE = {
    # ── Technology (10) ───────────────────────────────────────────────────────
    "AAPL":   ("Technology",      "Accumulate", "A"),
    "MSFT":   ("Technology",      "Accumulate", "A"),
    "GOOGL":  ("Technology",      "Accumulate", "A"),
    "META":   ("Technology",      "Accumulate", "A"),
    "AMZN":   ("Technology",      "Accumulate", "A"),
    "NVDA":   ("Technology",      "Accumulate", "A"),
    "NFLX":   ("Technology",      "Hold",       "H"),
    "CRM":    ("Technology",      "Hold",       "H"),
    "ORCL":   ("Technology",      "Accumulate", "A"),
    "PLTR":   ("Technology",      "Hold",       "H"),

    # ── Semiconductors (10) ──────────────────────────────────────────────────
    "TSM":    ("Semiconductors",  "Accumulate", "A"),
    "AVGO":   ("Semiconductors",  "Accumulate", "A"),
    "ASML":   ("Semiconductors",  "Accumulate", "A"),
    "AMD":    ("Semiconductors",  "Hold",       "H"),
    "INTC":   ("Semiconductors",  "Hold",       "H"),
    "QCOM":   ("Semiconductors",  "Hold",       "H"),   # no profile
    "TXN":    ("Semiconductors",  "Hold",       "H"),   # no profile
    "MU":     ("Semiconductors",  "Hold",       "H"),   # no profile
    "AMAT":   ("Semiconductors",  "Hold",       "H"),   # no profile
    "LRCX":   ("Semiconductors",  "Hold",       "H"),   # no profile

    # ── Financials (10) ──────────────────────────────────────────────────────
    "JPM":    ("Financials",      "Accumulate", "A"),
    "V":      ("Financials",      "Accumulate", "A"),
    "MA":     ("Financials",      "Accumulate", "A"),
    "AXP":    ("Financials",      "Accumulate", "A"),
    "BLK":    ("Financials",      "Accumulate", "A"),
    "BAC":    ("Financials",      "Hold",       "H"),
    "GS":     ("Financials",      "Hold",       "H"),
    "SCHW":   ("Financials",      "Hold",       "H"),
    "BRK.B":  ("Financials",      "Accumulate", "A"),
    "WFC":    ("Financials",      "Hold",       "H"),   # no profile

    # ── Healthcare (10) ──────────────────────────────────────────────────────
    "LLY":    ("Healthcare",      "Accumulate", "A"),
    "UNH":    ("Healthcare",      "Accumulate", "A"),
    "JNJ":    ("Healthcare",      "Accumulate", "A"),
    "ABBV":   ("Healthcare",      "Accumulate", "A"),
    "NVO":    ("Healthcare",      "Accumulate", "A"),
    "MRK":    ("Healthcare",      "Accumulate", "A"),   # no profile
    "ABT":    ("Healthcare",      "Accumulate", "A"),   # no profile
    "TMO":    ("Healthcare",      "Accumulate", "A"),   # no profile
    "PFE":    ("Healthcare",      "Hold",       "H"),   # no profile
    "MDT":    ("Healthcare",      "Hold",       "H"),   # no profile

    # ── Consumer (10) ────────────────────────────────────────────────────────
    "COST":   ("Consumer",        "Accumulate", "A"),
    "WMT":    ("Consumer",        "Accumulate", "A"),
    "PG":     ("Consumer",        "Accumulate", "A"),
    "KO":     ("Consumer",        "Hold",       "H"),
    "MDLZ":   ("Consumer",        "Hold",       "H"),
    "NKE":    ("Consumer",        "Hold",       "H"),
    "HD":     ("Consumer",        "Accumulate", "A"),   # no profile
    "MCD":    ("Consumer",        "Hold",       "H"),   # no profile
    "SBUX":   ("Consumer",        "Hold",       "H"),   # no profile
    "TGT":    ("Consumer",        "Hold",       "H"),   # no profile

    # ── Industrials (10) ─────────────────────────────────────────────────────
    "HON":    ("Industrials",     "Accumulate", "A"),
    "RTX":    ("Industrials",     "Accumulate", "A"),
    "EMR":    ("Industrials",     "Accumulate", "A"),
    "UPS":    ("Industrials",     "Hold",       "H"),
    "DE":     ("Industrials",     "Hold",       "H"),
    "BA":     ("Industrials",     "Hold",       "H"),
    "CAT":    ("Industrials",     "Hold",       "H"),   # no profile
    "GE":     ("Industrials",     "Hold",       "H"),   # no profile
    "LMT":    ("Industrials",     "Hold",       "H"),   # no profile
    "ETN":    ("Industrials",     "Accumulate", "A"),   # no profile

    # ── Energy (10) ──────────────────────────────────────────────────────────
    "XOM":    ("Energy",          "Hold",       "H"),
    "CVX":    ("Energy",          "Hold",       "H"),
    "OXY":    ("Energy",          "Hold",       "H"),
    "COP":    ("Energy",          "Hold",       "H"),
    "SLB":    ("Energy",          "Hold",       "H"),
    "PSX":    ("Energy",          "Hold",       "H"),   # no profile
    "EOG":    ("Energy",          "Hold",       "H"),   # no profile
    "DVN":    ("Energy",          "Hold",       "H"),   # no profile
    "MPC":    ("Energy",          "Hold",       "H"),   # no profile
    "VLO":    ("Energy",          "Hold",       "H"),   # no profile

    # ── Utilities (10) ───────────────────────────────────────────────────────
    "NEE":    ("Utilities",       "Accumulate", "A"),
    "SO":     ("Utilities",       "Hold",       "H"),
    "DUK":    ("Utilities",       "Hold",       "H"),
    "AEP":    ("Utilities",       "Hold",       "H"),
    "EXC":    ("Utilities",       "Hold",       "H"),
    "SRE":    ("Utilities",       "Hold",       "H"),   # no profile
    "PCG":    ("Utilities",       "Hold",       "H"),   # no profile
    "WEC":    ("Utilities",       "Hold",       "H"),   # no profile
    "ED":     ("Utilities",       "Hold",       "H"),   # no profile
    "AWK":    ("Utilities",       "Hold",       "H"),   # no profile

    # ── Communications & Services (10) ───────────────────────────────────────
    "PANW":   ("Communications",  "Accumulate", "A"),
    "PM":     ("Communications",  "Accumulate", "A"),
    "UBER":   ("Communications",  "Hold",       "H"),
    "ABNB":   ("Communications",  "Hold",       "H"),
    "TSLA":   ("Communications",  "Hold",       "H"),
    "T":      ("Communications",  "Hold",       "H"),
    "VZ":     ("Communications",  "Hold",       "H"),
    "CMCSA":  ("Communications",  "Hold",       "H"),
    "DIS":    ("Communications",  "Hold",       "H"),
    "TMUS":   ("Communications",  "Hold",       "H"),   # no profile

    # ── Real Estate (10) ─────────────────────────────────────────────────────
    "EQIX":   ("Real Estate",     "Accumulate", "A"),
    "PLD":    ("Real Estate",     "Accumulate", "A"),
    "AMT":    ("Real Estate",     "Hold",       "H"),
    "O":      ("Real Estate",     "Hold",       "H"),
    "SPG":    ("Real Estate",     "Hold",       "H"),
    "PSA":    ("Real Estate",     "Hold",       "H"),   # no profile
    "EQR":    ("Real Estate",     "Hold",       "H"),   # no profile
    "VICI":   ("Real Estate",     "Hold",       "H"),   # no profile
    "WELL":   ("Real Estate",     "Hold",       "H"),   # no profile
    "AMH":    ("Real Estate",     "Hold",       "H"),   # no profile
}

# ─────────────────────────────────────────────────────────────────────────────
# SECTOR-SPECIFIC INPUT TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

# Accumulate-tier bull text: strong durability signals, no "value"/"overvalued"
# Uses P/E, FCF yield, EBITDA multiples vocabulary
_BULL_ACCUMULATE: dict[str, str] = {
    "Technology": (
        "The company demonstrates exceptional recurring subscription revenue with "
        "high renewal rates and deep switching costs that create a mission-critical "
        "moat. Pricing power from platform lock-in drives consistent margin expansion. "
        "Secular demand from digital transformation and AI infrastructure is "
        "non-cyclical. Free cash flow generation is resilient across cycles. "
        "The P/E multiple reflects sustainable earnings growth, not speculation."
    ),
    "Semiconductors": (
        "Leading technology position with multi-year design contracts and high "
        "customer switching costs. Recurring design win revenue provides visibility. "
        "Secular demand from AI and data center infrastructure is mission-critical. "
        "Pricing power from process leadership and intellectual property moat. "
        "Free cash flow supports R&D reinvestment and capital return. "
        "The EV/EBITDA multiple is supported by structural demand growth."
    ),
    "Financials": (
        "Management fee and transaction fee structure provides highly recurring revenue "
        "with membership-like retention. Subscription-style product adoption drives "
        "cross-sell and renewal rate expansion. Moat from network effects and scale. "
        "Mission-critical financial infrastructure with non-discretionary client usage. "
        "Resilient fee income through cycles. FCF yield supports dividend growth. "
        "P/E reflects sustainable return on equity, not premium speculation."
    ),
    "Healthcare": (
        "Patient adherence to maintenance therapies provides highly recurring prescription "
        "revenue with non-discretionary demand. Patent-protected portfolio drives resilient "
        "pricing power. Secular demand from aging demographics is mission-critical. "
        "Free cash flow generation is consistent through reimbursement cycles. "
        "Subscription-like patient adherence underpins multi-year revenue visibility. "
        "FCF yield and P/E reflect durable earnings power, not pipeline speculation."
    ),
    "Consumer": (
        "Membership renewal rate and loyalty-based recurring purchases create a "
        "subscription-like revenue stream. Non-discretionary staple demand is "
        "recession-resistant with defensive characteristics. Pricing power from brand "
        "equity and switching costs supports consistent margin. Mission-critical for "
        "everyday household needs. Free cash flow supports returns. "
        "P/E multiple reflects earnings durability, not growth speculation."
    ),
    "Industrials": (
        "Multi-year service contracts and maintenance agreements provide recurring "
        "revenue visibility. Mission-critical automation and defense systems with "
        "non-discretionary demand from government and industrial customers. "
        "Switching costs from installed base create moat. Pricing power from "
        "proprietary technology. Free cash flow is resilient across CapEx cycles. "
        "EV/EBITDA reflects contractual backlog, not speculative growth."
    ),
    "Utilities": (
        "Regulated rate base provides fully recurring and non-discretionary revenue "
        "with mission-critical essential services. Captive customer base and "
        "monopoly franchise create defensive moat. Secular demand from clean energy "
        "transition underpins long-term earnings visibility. Subscription-like "
        "utility billing is recession-resistant. FCF yield supports dividend "
        "sustainability. P/E reflects regulatory certainty, not market speculation."
    ),
    "Communications": (
        "Subscription-based recurring revenue with high renewal rates from "
        "mission-critical cybersecurity and communications infrastructure. "
        "Pricing power from sticky enterprise contracts and high switching costs. "
        "Non-discretionary demand drives resilient through-cycle cash flows. "
        "Secular tailwinds from security spend and platform consolidation. "
        "Free cash flow supports share repurchase. FCF yield is attractive."
    ),
    "Real Estate": (
        "Long-term lease renewal rates provide highly recurring and contractual "
        "revenue. Mission-critical data center and logistics infrastructure with "
        "subscription-like AFFO predictability. Non-discretionary tenant demand "
        "for industrial and digital real estate. Moat from irreplaceable locations "
        "and network interconnections. Multi-year lease contracts with escalators. "
        "AFFO yield and cap rate reflect durable cash flow, not speculative NAV."
    ),
}

# Hold-tier bull text: moderate signals, balanced tone
_BULL_HOLD: dict[str, str] = {
    "Technology": (
        "The company maintains a solid market position with consistent revenue "
        "from established enterprise relationships. Some recurring software revenue "
        "provides stability but competition is increasing. Growth opportunities "
        "exist but require execution. Cash generation is adequate. "
        "P/E reflects current earnings trajectory without significant premium."
    ),
    "Semiconductors": (
        "Established position in semiconductor supply chains with consistent "
        "design wins across a broad customer base. Revenue has cyclical components "
        "but through-cycle cash flow is adequate. Technology roadmap execution "
        "is progressing. Balance sheet supports ongoing investment. "
        "EV/EBITDA reflects mid-cycle earnings capacity."
    ),
    "Financials": (
        "Diversified financial services with consistent fee and spread income. "
        "Capital ratios are solid and dividends are well-covered. Some exposure "
        "to interest rate and credit cycles but earnings base is stable. "
        "Returns on equity are respectable through the cycle. "
        "P/B multiple reflects tangible book and earnings power."
    ),
    "Healthcare": (
        "Established pharmaceutical and medical device franchise with solid "
        "cash flow from mature products. Pipeline activity provides optionality "
        "but near-term earnings visibility is moderate. Non-discretionary "
        "healthcare demand provides some resilience. Dividend is well-supported. "
        "P/E reflects sustainable earnings, not speculative pipeline premium."
    ),
    "Consumer": (
        "Established consumer brand with consistent volume and pricing discipline. "
        "The business is mature with predictable cash flows. Some exposure to "
        "consumer spending cycles but staple demand provides stability. "
        "Dividend growth track record is solid. P/E reflects stable earnings."
    ),
    "Industrials": (
        "Established industrial franchise with consistent backlog from government "
        "and commercial customers. Some cyclical exposure to CapEx cycles but "
        "service and aftermarket revenue provides stability. Execution on backlog "
        "conversion is progressing. FCF supports dividend and modest buybacks. "
        "EV/EBITDA reflects mid-cycle normalized earnings."
    ),
    "Energy": (
        "Diversified energy franchise with resilient integrated operations. "
        "Strong balance sheet and dividend coverage even at moderate oil prices. "
        "Low-cost production position supports free cash flow. Some cyclical "
        "exposure to commodity prices is inherent. Capital discipline has improved. "
        "EV/EBITDA reflects through-cycle earnings normalized to mid-cycle pricing."
    ),
    "Utilities": (
        "Regulated utility with stable rate base and predictable allowed returns. "
        "Captive service territory and regulatory compact provide earnings certainty. "
        "Dividend yield is well-covered by regulated cash flows. Some rate case "
        "and weather exposure but overall earnings are highly visible. "
        "P/E multiple reflects regulatory earnings certainty."
    ),
    "Communications": (
        "Established telecommunications or media franchise with stable subscriber "
        "base and predictable ARPU. Some competitive pressure from streaming and "
        "wireless alternatives but market position is durable. Free cash flow "
        "supports dividend and debt service. EV/EBITDA reflects stable cash flows."
    ),
    "Real Estate": (
        "REIT with stable AFFO from long-term lease agreements and contracted "
        "rent escalators. Occupancy is adequate and tenant credit quality is "
        "acceptable. Some interest rate sensitivity but AFFO coverage is solid. "
        "AFFO yield reflects current cap rate environment, not speculative NAV."
    ),
}

# Bear text templates (balanced — no "overvalued"/"expensive"/"cheap"/"value")
_BEAR_TEMPLATE = (
    "Key risks include execution on strategic initiatives, competitive headwinds, "
    "and macro sensitivity to interest rates and economic conditions. "
    "Near-term growth visibility is moderate and the P/E multiple requires "
    "continued earnings delivery. Sector rotation risk is present."
)

# Risk text templates
_RISK_ACCUMULATE = (
    "Competition from well-funded peers, execution risk on expansion plans, "
    "and regulatory or reimbursement headwinds in core markets. "
    "Macroeconomic sensitivity is moderate given durable revenue base."
)
_RISK_HOLD = (
    "Cyclical exposure to industry demand cycles, execution risk on cost "
    "and margin initiatives, competitive pricing pressure, and some "
    "sensitivity to interest rates and consumer or industrial spending."
)

# Macro text
_MACRO_TEMPLATE = (
    "Macro backdrop is mixed: rate environment stabilizing, growth moderating. "
    "Sector is sensitive to Fed policy but demand fundamentals remain intact. "
    "Inflation pass-through is adequate for established franchises."
)


# ─────────────────────────────────────────────────────────────────────────────
# INPUT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _ev(title: str, summary: str, source: str = "Analyst Research") -> RetrievedEvidence:
    return RetrievedEvidence(
        title=title, source=source, summary=summary,
        timestamp=TODAY, relevance_score=0.88,
    )


def _val_stance_from_text(bull: str, bear: str) -> str:
    combined = (bull + " " + bear).lower()
    if any(w in combined for w in ("overvalued", "expensive", "stretched multiple", "premium priced")):
        return "overpriced"
    if any(w in combined for w in ("undervalued", "cheap", "deep discount", "value")):
        return "underpriced"
    return "fairly_valued"


def build_inputs(ticker: str, sector: str, tier: str) -> dict:
    """Build conviction-model inputs for a company given sector + stance tier."""
    bull_text = _BULL_ACCUMULATE[sector] if tier == "A" else _BULL_HOLD.get(sector, _BULL_HOLD["Technology"])
    bear_text = _BEAR_TEMPLATE
    risk_text = _RISK_ACCUMULATE if tier == "A" else _RISK_HOLD
    mac_text  = _MACRO_TEMPLATE

    # Quality confidence: higher for Accumulate tier
    q_conf = 0.72 if tier == "A" else 0.60
    r_conf = 0.62 if tier == "A" else 0.55

    quality = QualityAssessment(
        moat             = bull_text[:400],
        revenue_durability = bull_text[:300],
        operating_quality= bull_text[:300],
        overall          = (bull_text + " " + bear_text)[:600],
        confidence       = q_conf,
    )
    macro = MacroSensitivity(
        rate_sensitivity = mac_text[:200],
        overall          = mac_text[:400],
        confidence       = 0.50,
    )
    risk = RiskProfile(
        key_risks        = [risk_text[:150], "Macro and cycle sensitivity.", "Competitive positioning."],
        competitive_risk = bear_text[:250],
        overall          = risk_text[:350],
        confidence       = r_conf,
    )
    val_stance = _val_stance_from_text(bull_text, bear_text)
    valuation = ValuationView(
        overall          = bull_text[:350],
        valuation_stance = val_stance,
        confidence       = 0.58,
    )
    catalysts = [f"{ticker} earnings catalyst", "Macro stabilization", "Sector rotation"]
    market = MarketContext(
        recent_catalysts = catalysts,
        overall          = f"{ticker} catalyst momentum.",
        confidence       = 0.52,
    )

    # Build evidence items (neutral — no priced-in / speculative terms)
    evidence = [
        _ev(f"{ticker} ratios-ttm",        f"Current financial metrics for {ticker}."),
        _ev(f"{ticker} analyst estimates",  f"Analyst consensus EPS and revenue for {ticker}."),
        _ev(f"{ticker} quarterly earnings", f"Recent earnings results for {ticker}."),
    ]
    if tier == "A":
        evidence += [
            _ev(f"{ticker} moat analysis",
                f"Free cash flow generation is strong. Recurring revenue streams "
                f"and pricing power support the moat thesis for {ticker}."),
            _ev(f"{ticker} recurring revenue",
                f"Subscription and recurring revenue base provides earnings predictability."),
            _ev(f"{ticker} competitive position",
                f"Essential infrastructure and mission-critical positioning for {ticker}."),
        ]
    else:
        evidence += [
            _ev(f"{ticker} free cash flow",
                f"Free cash flow supports dividend coverage for {ticker}."),
            _ev(f"{ticker} risk factors",
                f"Cyclical and competitive risks are manageable for {ticker}."),
        ]

    return {
        "quality": quality, "macro": macro, "risk": risk,
        "valuation": valuation, "market": market,
        "evidence": evidence, "val_stance": val_stance,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ROOT-CAUSE CLASSIFIER
# ─────────────────────────────────────────────────────────────────────────────

def classify_error(
    ticker: str, tier: str, expected: str, got: str,
    dur: float, frag: float, regime: str, val_stance: str,
    has_profile: bool, score: float,
) -> str:
    """Return the primary root-cause label for an incorrect classification."""
    if expected == got:
        return "CORRECT"

    # ── No profile → systematic Buy-broad (no-profile architecture) ──────────
    if not has_profile:
        if got in ("Buy", "Aggressive Buy") and expected in ("Hold", "Accumulate"):
            return "NO_PROFILE: Buy-broad override"
        if got == "Hold" and expected == "Accumulate" and dur < 0.68:
            return "NO_PROFILE: Accumulate blocked (dur<0.68)"
        return f"NO_PROFILE: {got} vs {expected}"

    # ── Profile present — diagnose which threshold failed ────────────────────
    if expected == "Accumulate":
        if dur < 0.68:
            return f"CALIBRATION: dur={dur:.3f} < 0.68 Accumulate threshold"
        if frag >= 0.40:
            return f"CALIBRATION: frag={frag:.3f} >= 0.40 blocks Durable Accumulate"
        if val_stance == "overpriced":
            return "VALUATION: val_stance=overpriced blocks Accumulate"
        if regime in ("euphoric", "bubble"):
            return f"VALUATION: regime={regime} blocks Accumulate"
        if score < 0.58:
            return f"CALIBRATION: score={score:.3f} < 0.58 for Durable Accumulate"

    if expected == "Hold":
        # Over-calibration: profile gives dur >= 0.68 → Durable Accumulate fires instead of Hold
        if dur >= 0.68 and got == "Accumulate":
            return f"PROFILE_OVERCAL: dur={dur:.3f} >= 0.68 profile over-calibrated → Durable Accumulate fires (should be Hold)"
        if val_stance != "fairly_valued":
            return f"VALUATION: val_stance={val_stance!r} (not fairly_valued) blocks Durable Hold"
        if dur < 0.55:
            return f"CALIBRATION: dur={dur:.3f} < 0.55 Durable Hold threshold → falls to Buy-broad"
        if frag >= 0.40:
            return f"CALIBRATION: frag={frag:.3f} >= 0.40 blocks Durable Hold"
        if score < 0.55:
            return f"CALIBRATION: score={score:.3f} < 0.55 for Durable Hold"

    return f"UNDIAGNOSED: got={got!r} expected={expected!r} dur={dur:.3f} frag={frag:.3f}"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

STANCE_ORDER = ["Sell", "Avoid", "Hold", "Accumulate", "Buy", "Aggressive Buy"]

def stance_gap(got: str, expected: str) -> int:
    try:
        return abs(STANCE_ORDER.index(got) - STANCE_ORDER.index(expected))
    except ValueError:
        return 99


def run_validation() -> None:
    print(f"\n{'='*80}")
    print(f"100-Company Production Validation — Phase 5B Baseline")
    print(f"Date: {TODAY[:10]}  |  Profiles registered: "
          f"{len([t for t in UNIVERSE if get_knowledge_profile(t) is not None])}/100")
    print(f"{'='*80}\n")

    results           = []
    sector_stats      = defaultdict(lambda: {"total": 0, "correct": 0, "results": []})
    error_categories  = defaultdict(int)
    no_profile_tickers = []

    for ticker, (sector, expected, tier) in UNIVERSE.items():
        profile     = get_knowledge_profile(ticker)
        has_profile = profile is not None
        if not has_profile:
            no_profile_tickers.append(ticker)

        inp  = build_inputs(ticker, sector, tier)
        company = CompanyContext(ticker=ticker, company_name=ticker)

        try:
            result = compute_conviction(
                quality   = inp["quality"],
                macro     = inp["macro"],
                risk      = inp["risk"],
                valuation = inp["valuation"],
                market    = inp["market"],
                evidence  = inp["evidence"],
                company   = company,
                profile   = profile,
            )

            stance = result.directional_stance
            frag   = result.dimensions.expectation_fragility
            score  = result.final_score
            setup  = result.setup_label if hasattr(result, "setup_label") else ""

            dur    = _compute_business_durability(
                quality  = inp["quality"],
                risk     = inp["risk"],
                evidence = inp["evidence"],
                profile  = profile,
            )
            regime   = _classify_expectation_regime(frag, inp["val_stance"], dur)
            val_s    = inp["val_stance"]
            gap      = stance_gap(stance, expected)
            correct  = (stance == expected)
            root_cause = classify_error(
                ticker, tier, expected, stance,
                dur, frag, regime, val_s, has_profile, score,
            )

            rec = {
                "ticker": ticker, "sector": sector, "expected": expected,
                "got": stance, "tier": tier, "dur": dur, "frag": frag,
                "regime": regime, "val_stance": val_s, "score": score,
                "correct": correct, "gap": gap, "has_profile": has_profile,
                "root_cause": root_cause,
            }
            results.append(rec)
            sector_stats[sector]["total"]   += 1
            sector_stats[sector]["correct"] += int(correct)
            sector_stats[sector]["results"].append(rec)
            if not correct:
                cat = root_cause.split(":")[0]
                error_categories[cat] += 1

        except Exception as exc:
            results.append({
                "ticker": ticker, "sector": sector, "expected": expected,
                "got": "ERROR", "error": str(exc), "correct": False, "gap": 99,
                "has_profile": has_profile, "tier": tier, "root_cause": f"ERROR: {exc}",
            })
            sector_stats[sector]["total"]   += 1
            sector_stats[sector]["results"].append(results[-1])

    # ─── Per-company table ───────────────────────────────────────────────────
    print(f"{'Tick':6s} {'Sect':14s} {'Tier':4s} {'Prof':4s} {'Expected':11s} {'Got':12s} "
          f"{'dur':5s} {'frag':5s} {'score':5s} {'regime':10s} Result  Root Cause")
    print("-" * 130)

    for r in results:
        if "error" in r:
            print(f"{r['ticker']:6s} {r['sector']:14s} {r['tier']:4s} "
                  f"{'Y' if r['has_profile'] else 'N':4s} {r['expected']:11s} "
                  f"{'ERROR':12s}  ---   ---   ---   ---        ❌  {r['root_cause']}")
            continue
        mark = "✅" if r["correct"] else ("〰️" if r["gap"] == 1 else "❌")
        prof = "Y" if r["has_profile"] else "N"
        print(f"{r['ticker']:6s} {r['sector']:14s} {r['tier']:4s} {prof:4s} "
              f"{r['expected']:11s} {r['got']:12s} "
              f"{r['dur']:.3f} {r['frag']:.3f} {r['score']:.3f} {r['regime']:10s} "
              f"{mark}  {r['root_cause']}")

    # ─── Overall accuracy ────────────────────────────────────────────────────
    total   = len(results)
    correct = sum(1 for r in results if r.get("correct"))
    gap1    = sum(1 for r in results if not r.get("correct") and r.get("gap") == 1)
    print(f"\n{'='*80}")
    print(f"OVERALL ACCURACY: {correct}/{total} ({correct/total*100:.1f}%)")
    print(f"Off-by-one (gap=1): {gap1}  |  Wrong direction (gap≥2): {total-correct-gap1}")
    print(f"{'='*80}")

    # ─── Sector accuracy ─────────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print(f"SECTOR ACCURACY")
    print(f"{'─'*50}")
    for sector in [
        "Technology", "Semiconductors", "Financials", "Healthcare",
        "Consumer", "Industrials", "Energy", "Utilities",
        "Communications", "Real Estate",
    ]:
        s = sector_stats[sector]
        n, c = s["total"], s["correct"]
        pct = c / n * 100 if n else 0
        bar = "█" * c + "░" * (n - c)
        print(f"  {sector:16s} {c:2d}/{n:2d} ({pct:5.1f}%)  {bar}")

    # ─── Stance distribution ─────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print(f"STANCE DISTRIBUTION (model output)")
    print(f"{'─'*50}")
    stance_counts = defaultdict(int)
    for r in results:
        stance_counts[r.get("got", "ERROR")] += 1
    for s in ["Aggressive Buy", "Buy", "Accumulate", "Hold", "Tactical", "Avoid", "Sell", "ERROR"]:
        if stance_counts[s]:
            print(f"  {s:14s}: {stance_counts[s]:3d}")

    # ─── Confidence distribution ─────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print(f"CONFIDENCE SCORE DISTRIBUTION (final_score)")
    print(f"{'─'*50}")
    bands = {"≥0.72 (durable)": 0, "0.58–0.72 (balanced)": 0,
             "0.42–0.58 (demanding)": 0, "<0.42 (fragile)": 0}
    for r in results:
        s = r.get("score", 0)
        if   s >= 0.72: bands["≥0.72 (durable)"] += 1
        elif s >= 0.58: bands["0.58–0.72 (balanced)"] += 1
        elif s >= 0.42: bands["0.42–0.58 (demanding)"] += 1
        else:           bands["<0.42 (fragile)"] += 1
    for band, count in bands.items():
        print(f"  {band:25s}: {count:3d}")

    # ─── False positives / negatives ─────────────────────────────────────────
    print(f"\n{'─'*50}")
    print(f"FALSE POSITIVES (got more bullish than expected)")
    print(f"{'─'*50}")
    fps = [r for r in results if not r.get("correct") and
           STANCE_ORDER.index(r.get("got", "Hold")) > STANCE_ORDER.index(r.get("expected", "Hold"))
           if r.get("got") in STANCE_ORDER and r.get("expected") in STANCE_ORDER]
    for r in fps:
        print(f"  {r['ticker']:6s} ({r['sector']:14s}) expected={r['expected']:11s} "
              f"got={r['got']:12s} dur={r['dur']:.3f}  {r['root_cause']}")

    print(f"\n{'─'*50}")
    print(f"FALSE NEGATIVES (got less bullish than expected)")
    print(f"{'─'*50}")
    fns = [r for r in results if not r.get("correct") and
           STANCE_ORDER.index(r.get("got", "Hold")) < STANCE_ORDER.index(r.get("expected", "Hold"))
           if r.get("got") in STANCE_ORDER and r.get("expected") in STANCE_ORDER]
    for r in fns:
        print(f"  {r['ticker']:6s} ({r['sector']:14s}) expected={r['expected']:11s} "
              f"got={r['got']:12s} dur={r['dur']:.3f}  {r['root_cause']}")

    # ─── Error category ranking ──────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print(f"SYSTEMATIC FAILURE PATTERNS (ranked by frequency)")
    print(f"{'─'*50}")
    for cat, cnt in sorted(error_categories.items(), key=lambda x: -x[1]):
        pct = cnt / (total - correct) * 100 if (total - correct) else 0
        print(f"  {cat:35s}: {cnt:3d} ({pct:.1f}% of errors)")

    # ─── No-profile impact analysis ──────────────────────────────────────────
    np_total   = len(no_profile_tickers)
    np_correct = sum(1 for r in results if not r.get("has_profile") and r.get("correct"))
    np_buy_override = sum(
        1 for r in results
        if not r.get("has_profile") and r.get("got") in ("Buy", "Aggressive Buy")
           and r.get("expected") != "Buy"
    )
    print(f"\n{'─'*50}")
    print(f"NO-PROFILE IMPACT ANALYSIS (35 companies without profiles)")
    print(f"{'─'*50}")
    print(f"  No-profile total:     {np_total:3d}")
    if np_total > 0:
        print(f"  No-profile correct:   {np_correct:3d}  ({np_correct/np_total*100:.1f}%)")
    else:
        print(f"  No-profile correct:   n/a  (all companies now profiled)")
    print(f"  Buy-broad override:   {np_buy_override:3d}  (got Buy despite non-Buy expected)")
    print(f"  Profiled accuracy:    "
          f"{correct - np_correct}/{total - np_total} "
          f"({(correct - np_correct)/(total - np_total)*100:.1f}%)")

    # ─── RANKED ISSUE SUMMARY ────────────────────────────────────────────────
    profiled_results = [r for r in results if r.get("has_profile")]
    profiled_errors  = [r for r in profiled_results if not r.get("correct")]

    np_issues      = [r for r in results      if "NO_PROFILE"      in r.get("root_cause", "")]
    overcal_issues = [r for r in profiled_errors if "PROFILE_OVERCAL" in r.get("root_cause", "")]
    cal_issues     = [r for r in profiled_errors if "CALIBRATION"    in r.get("root_cause", "")]
    val_issues     = [r for r in profiled_errors if "VALUATION"      in r.get("root_cause", "")]

    print(f"\n{'='*80}")
    print(f"RANKED ISSUE SUMMARY")
    print(f"{'='*80}")

    # ── #1: Profile coverage gap ─────────────────────────────────────────────
    n_errors = total - correct
    pct_of_errors = lambda n: f"{n/n_errors*100:.0f}%" if n_errors else "n/a"
    print(f"\n  #1 MOST COMMON — PROFILE COVERAGE GAP ({len(np_issues)} errors, "
          f"{pct_of_errors(len(np_issues))} of errors)")
    print(f"     35 companies have no CompanyKnowledgeProfile.")
    print(f"     → dur defaults to 0.40 (base-only); Durable Hold needs dur≥0.55,")
    print(f"       Durable Accumulate needs dur≥0.68 — neither fires without a profile.")
    print(f"     → Hold targets fall through to Buy-broad (score≥0.62, frag<0.58).")
    print(f"     → Accumulate targets get Durable Hold (dur≈0.63) — off by one step.")
    np_hold_fp = [r for r in np_issues if r.get("expected") == "Hold"]
    np_acc_fn  = [r for r in np_issues if r.get("expected") == "Accumulate"]
    print(f"     Breakdown:  Hold→Buy (false positive): {len(np_hold_fp)}  |  "
          f"Accumulate→Hold (false negative): {len(np_acc_fn)}")
    print(f"     Affected tickers: {', '.join(r['ticker'] for r in np_issues[:20])}")
    if len(np_issues) > 20:
        print(f"                       ... and {len(np_issues)-20} more")

    # ── #2: Profile over-calibration ─────────────────────────────────────────
    print(f"\n  #2 MOST COMMON — PROFILE OVER-CALIBRATION ({len(overcal_issues)} errors, "
          f"{pct_of_errors(len(overcal_issues))} of errors)")
    print(f"     Profiled Hold-expected companies compute Layer 1 durability ≥ 0.68,")
    print(f"     causing Durable Accumulate to fire instead of Durable Hold.")
    print(f"     These profiles were likely designed in an earlier phase with generous")
    print(f"     recurring/recession/competitive-advantage signals that push them over")
    print(f"     the 0.68 Accumulate threshold.")
    for r in overcal_issues:
        print(f"     {r['ticker']:6s} ({r['sector']:14s}): dur={r['dur']:.3f}  "
              f"L1 profile signals push dur above 0.68 threshold")

    # ── #3: Calibration threshold miss (dur < 0.55 for Hold targets) ─────────
    print(f"\n  #3 CALIBRATION MISS — HOLD DUR < 0.55 ({len(cal_issues)} errors, "
          f"{pct_of_errors(len(cal_issues))} of errors)")
    print(f"     Profiled Hold-expected companies with durability below the 0.55")
    print(f"     Durable Hold threshold fall through to Buy-broad.")
    print(f"     These are high-risk companies (TSLA, PLTR, ABNB, INTC) whose")
    print(f"     profiles intentionally give low durability, but the gap between")
    print(f"     their dur and 0.55 means the Hold gate never fires.")
    for r in cal_issues:
        print(f"     {r['ticker']:6s} ({r['sector']:14s}): {r['root_cause']}")

    if val_issues:
        print(f"\n  VALUATION DETECTION ISSUES ({len(val_issues)} errors):")
        for r in val_issues:
            print(f"     {r['ticker']:6s}: {r['root_cause']}")

    # ─── Architectural diagnosis ─────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"ARCHITECTURAL DIAGNOSIS")
    print(f"{'='*80}")

    profiled_acc = sum(1 for r in profiled_results if r.get("expected") == "Accumulate" and r.get("correct"))
    profiled_acc_total = sum(1 for r in profiled_results if r.get("expected") == "Accumulate")
    profiled_hold = sum(1 for r in profiled_results if r.get("expected") == "Hold" and r.get("correct"))
    profiled_hold_total = sum(1 for r in profiled_results if r.get("expected") == "Hold")

    print(f"\n  Profiled universe accuracy:")
    print(f"    Accumulate targets: {profiled_acc}/{profiled_acc_total} "
          f"({profiled_acc/profiled_acc_total*100:.1f}%)")
    print(f"    Hold targets:       {profiled_hold}/{profiled_hold_total} "
          f"({profiled_hold/profiled_hold_total*100:.1f}%)")

    np_hold_total  = sum(1 for r in results if not r.get("has_profile") and r.get("expected") == "Hold")
    np_acc_total   = sum(1 for r in results if not r.get("has_profile") and r.get("expected") == "Accumulate")
    np_hold_correct = sum(1 for r in results if not r.get("has_profile") and r.get("expected") == "Hold" and r.get("correct"))
    np_acc_correct  = sum(1 for r in results if not r.get("has_profile") and r.get("expected") == "Accumulate" and r.get("correct"))
    print(f"\n  No-profile universe accuracy:")
    print(f"    Accumulate targets: {np_acc_correct}/{np_acc_total} "
          f"({np_acc_correct/np_acc_total*100:.1f}% if n>0 else 0)" if np_acc_total else
          f"    Accumulate targets: 0/0 (n/a)")
    print(f"    Hold targets:       {np_hold_correct}/{np_hold_total} "
          f"({np_hold_correct/np_hold_total*100:.1f}%)" if np_hold_total else
          f"    Hold targets:       0/0 (n/a)")

    np_hold_pct = np_hold_correct / np_hold_total * 100 if np_hold_total else 0
    acc_ok = profiled_acc / profiled_acc_total >= 0.85 if profiled_acc_total else False
    hold_ok = profiled_hold / profiled_hold_total >= 0.80 if profiled_hold_total else False

    print(f"\n  VERDICT:")
    if len(np_issues) > 20:
        print(f"  ⚠️  SYSTEMATIC ARCHITECTURAL WEAKNESS — not isolated edge cases.")
        print(f"     The primary failure mode is PROFILE COVERAGE GAP:")
        print(f"     {len(np_issues)}/{total} errors ({len(np_issues)/(total-correct)*100:.0f}% of all errors) "
              f"come from no-profile companies defaulting to Buy-broad.")
        print(f"     The conviction engine calibration is {'sound' if (acc_ok and hold_ok) else 'partially sound'} "
              f"for profiled companies.")
        if acc_ok and hold_ok:
            print(f"     Profiled Accumulate: {profiled_acc/profiled_acc_total*100:.0f}% | "
                  f"Profiled Hold: {profiled_hold/profiled_hold_total*100:.0f}%")
            print(f"     Architecture is correct. Profile expansion to 100 companies would "
                  f"resolve the majority of remaining errors.")
    elif cal_issues:
        print(f"  ⚠️  CALIBRATION ISSUES dominate for profiled companies.")
        print(f"     {len(cal_issues)} profiled companies have durability just below threshold.")
    else:
        print(f"  ✅  Errors are isolated edge cases. Architecture is sound.")

    print(f"\n{'='*80}")
    print(f"SUMMARY STATISTICS")
    print(f"{'='*80}")
    print(f"  Overall accuracy:            {correct}/{total} ({correct/total*100:.1f}%)")
    print(f"  Profiled company accuracy:   "
          f"{correct-np_correct}/{total-np_total} "
          f"({(correct-np_correct)/(total-np_total)*100:.1f}%)")
    if np_total > 0:
        print(f"  No-profile accuracy:         {np_correct}/{np_total} ({np_correct/np_total*100:.1f}%)")
    else:
        print(f"  No-profile accuracy:         n/a  (0 unprofileed companies remain)")
    print(f"  False positives (too bullish): {len(fps)}")
    print(f"  False negatives (too bearish): {len(fns)}")
    print()


if __name__ == "__main__":
    run_validation()
