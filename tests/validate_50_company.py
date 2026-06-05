"""
tests/validate_50_company.py

50-Company Production Validation — Phase 4 Generalization Test
==============================================================

Goal: Determine whether Phase 4 conviction calibration (Phases 4A + 4B)
generalizes beyond the original 20-company validation universe.

Universe: 50 companies across 10 sectors (5 per sector)
  Technology, Semiconductors, Financials, Healthcare, Consumer,
  Industrials, Energy, Utilities, Communications, Real Estate

Methodology: Same as validate_phase4b_production.py
  1. Call /analyze for each company with live LLM
  2. Build synthetic evidence items (FMP + analyst + earnings sources)
  3. Run compute_conviction() locally with evidence + profile
  4. Compare result stance against expected stance

Deliverables:
  - Overall accuracy (correct / 50)
  - Sector accuracy (correct / 5 per sector)
  - Confidence distribution
  - False positives (over-conviction: got Accumulate/Buy, expected Hold/Avoid)
  - False negatives (under-conviction: got Avoid/Hold, expected Accumulate/Buy)
  - Calibration issues (systematic over/under)
  - Remaining systematic weaknesses

Checkpointing: Results saved after each company to
  /tmp/validate_50_company_checkpoint.json
  Resume from checkpoint if script is re-run.
"""
from __future__ import annotations

import sys, os, json, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import urllib.request
import urllib.error

from app.services.conviction_modeler import (
    compute_conviction,
    _compute_business_durability,
    _classify_expectation_regime,
    CONVICTION_SCHEMA_VERSION,
)
from app.services.company_knowledge import get_knowledge_profile
from app.services.thesis_synthesizer import _detect_dominant_dimension
from app.schemas import (
    CompanyContext,
    QualityAssessment,
    ValuationView,
    MacroSensitivity,
    RiskProfile,
    MarketContext,
    RetrievedEvidence,
)

BASE_URL   = "https://clearsignal-backend-dlsc.onrender.com"
CHECKPOINT = "/tmp/validate_50_company_checkpoint.json"
TODAY      = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

# ─────────────────────────────────────────────────────────────────────────────
# 50-COMPANY UNIVERSE
# Format: ticker → (company_name, sector, expected_stance, question)
# Expected stances derived from:
#   - Phase 4A 20-company validated universe (known correct)
#   - Phase 4B 4-company universe (known correct post-fix)
#   - Extension companies: calibrated against business quality / market position
#
# Stance scale: Accumulate | Hold | Avoid | Buy | Sell
# Tolerance: ±1 adjacent step counts as correct (Hold→Accumulate = "close")
# ─────────────────────────────────────────────────────────────────────────────

COMPANIES = {
    # ── TECHNOLOGY (5) ────────────────────────────────────────────────────────
    "MSFT": (
        "Microsoft",
        "Technology",
        "Accumulate",
        "What is the full investment thesis for Microsoft including Azure growth, AI Copilot monetization, and FCF durability?",
    ),
    "AAPL": (
        "Apple",
        "Technology",
        "Accumulate",
        "What is the full investment thesis for Apple including Services revenue, iPhone installed base, and capital return?",
    ),
    "NVDA": (
        "NVIDIA",
        "Technology",
        "Hold",
        "What is the full investment thesis for NVIDIA including AI accelerator demand cycle, valuation, and competition risks?",
    ),
    "CRM": (
        "Salesforce",
        "Technology",
        "Hold",
        "What is the full investment thesis for Salesforce including AI Agentforce opportunity, profitability improvement, and competitive moat?",
    ),
    "PANW": (
        "Palo Alto Networks",
        "Technology",
        "Hold",
        "What is the full investment thesis for Palo Alto Networks including platformization strategy, ARR growth, and valuation?",
    ),

    # ── SEMICONDUCTORS (5) ────────────────────────────────────────────────────
    "TSM": (
        "Taiwan Semiconductor",
        "Semiconductors",
        "Accumulate",
        "What is the full investment thesis for TSMC including advanced node leadership, AI wafer demand, and geopolitical risk?",
    ),
    "AMD": (
        "AMD",
        "Semiconductors",
        "Accumulate",
        "What is the full investment thesis for AMD including data center GPU opportunity, EPYC server share gains, and competitive position vs NVIDIA?",
    ),
    "AVGO": (
        "Broadcom",
        "Semiconductors",
        "Accumulate",
        "What is the full investment thesis for Broadcom including custom AI ASIC opportunity, VMware integration, and FCF generation?",
    ),
    "ASML": (
        "ASML",
        "Semiconductors",
        "Accumulate",
        "What is the full investment thesis for ASML including EUV monopoly, High-NA transition, and semiconductor capex cycle?",
    ),
    "INTC": (
        "Intel",
        "Semiconductors",
        "Avoid",
        "What is the full investment thesis for Intel including foundry strategy, execution risk, market share losses, and turnaround timeline?",
    ),

    # ── FINANCIALS (5) ────────────────────────────────────────────────────────
    "JPM": (
        "JPMorgan Chase",
        "Financials",
        "Accumulate",
        "What is the full investment thesis for JPMorgan Chase including earnings power, investment banking recovery, and capital return?",
    ),
    "BAC": (
        "Bank of America",
        "Financials",
        "Accumulate",
        "What is the full investment thesis for Bank of America including NII sensitivity, consumer banking franchise, and credit quality?",
    ),
    "GS": (
        "Goldman Sachs",
        "Financials",
        "Hold",
        "What is the full investment thesis for Goldman Sachs including investment banking cycle, asset management growth, and valuation?",
    ),
    "V": (
        "Visa",
        "Financials",
        "Accumulate",
        "What is the full investment thesis for Visa including network effects, payment volume growth, and margin durability?",
    ),
    "AXP": (
        "American Express",
        "Financials",
        "Accumulate",
        "What is the full investment thesis for American Express including premium cardholder spend, fee revenue growth, and credit quality?",
    ),

    # ── HEALTHCARE (5) ────────────────────────────────────────────────────────
    "LLY": (
        "Eli Lilly",
        "Healthcare",
        "Hold",
        "What is the full investment thesis for Eli Lilly including GLP-1 obesity drug opportunity, pipeline depth, and premium valuation?",
    ),
    "UNH": (
        "UnitedHealth Group",
        "Healthcare",
        "Hold",
        "What is the full investment thesis for UnitedHealth Group including managed care earnings power, Optum integration, and regulatory risk?",
    ),
    "JNJ": (
        "Johnson & Johnson",
        "Healthcare",
        "Accumulate",
        "What is the full investment thesis for Johnson & Johnson including MedTech segment, pharma pipeline, and dividend durability?",
    ),
    "NVO": (
        "Novo Nordisk",
        "Healthcare",
        "Hold",
        "What is the full investment thesis for Novo Nordisk including GLP-1 market leadership, Ozempic/Wegovy trajectory, and competition risk?",
    ),
    "ABBV": (
        "AbbVie",
        "Healthcare",
        "Accumulate",
        "What is the full investment thesis for AbbVie including Humira successor pipeline, Skyrizi and Rinvoq growth, and dividend sustainability?",
    ),

    # ── CONSUMER (5) ─────────────────────────────────────────────────────────
    "COST": (
        "Costco",
        "Consumer",
        "Accumulate",
        "What is the full investment thesis for Costco including membership model durability, warehouse expansion, and pricing power?",
    ),
    "WMT": (
        "Walmart",
        "Consumer",
        "Accumulate",
        "What is the full investment thesis for Walmart including omnichannel share gains, advertising revenue growth, and international expansion?",
    ),
    "NKE": (
        "Nike",
        "Consumer",
        "Hold",
        "What is the full investment thesis for Nike including brand recovery, DTC strategy, China exposure, and turnaround timeline?",
    ),
    "KO": (
        "Coca-Cola",
        "Consumer",
        "Hold",
        "What is the full investment thesis for Coca-Cola including pricing power, emerging market growth, and dividend compounding?",
    ),
    "DIS": (
        "Walt Disney",
        "Consumer",
        "Hold",
        "What is the full investment thesis for Disney including streaming path to profitability, parks segment, and franchise value?",
    ),

    # ── INDUSTRIALS (5) ──────────────────────────────────────────────────────
    "HON": (
        "Honeywell",
        "Industrials",
        "Hold",
        "What is the full investment thesis for Honeywell including automation software, portfolio restructuring, and defense exposure?",
    ),
    "DE": (
        "Deere",
        "Industrials",
        "Hold",
        "What is the full investment thesis for Deere including precision agriculture, ag cycle timing, and technology differentiation?",
    ),
    "RTX": (
        "RTX",
        "Industrials",
        "Accumulate",
        "What is the full investment thesis for RTX including defense backlog, commercial aerospace recovery, and Pratt & Whitney GTF remediation?",
    ),
    "BA": (
        "Boeing",
        "Industrials",
        "Avoid",
        "What is the full investment thesis for Boeing including 737 MAX production ramp, execution risk, balance sheet, and competitive position?",
    ),
    "EMR": (
        "Emerson Electric",
        "Industrials",
        "Hold",
        "What is the full investment thesis for Emerson including process automation software, AspenTech integration, and industrial cycle exposure?",
    ),

    # ── ENERGY (5) ───────────────────────────────────────────────────────────
    "XOM": (
        "ExxonMobil",
        "Energy",
        "Avoid",
        "What is the full investment thesis for ExxonMobil including oil price sensitivity, Pioneer acquisition integration, and energy transition risk?",
    ),
    "CVX": (
        "Chevron",
        "Energy",
        "Hold",
        "What is the full investment thesis for Chevron including capital discipline, Hess acquisition, and long-cycle project portfolio?",
    ),
    "COP": (
        "ConocoPhillips",
        "Energy",
        "Hold",
        "What is the full investment thesis for ConocoPhillips including low-cost asset base, capital return program, and Marathon Oil integration?",
    ),
    "SLB": (
        "SLB",
        "Energy",
        "Hold",
        "What is the full investment thesis for SLB including oilfield services technology leadership, international growth, and digital/AI offerings?",
    ),
    "OXY": (
        "Occidental Petroleum",
        "Energy",
        "Hold",
        "What is the full investment thesis for Occidental Petroleum including Permian Basin position, carbon capture strategy, and Berkshire backing?",
    ),

    # ── UTILITIES (5) ────────────────────────────────────────────────────────
    "NEE": (
        "NextEra Energy",
        "Utilities",
        "Accumulate",
        "What is the full investment thesis for NextEra Energy including regulated utility earnings, renewable energy growth, and dividend track record?",
    ),
    "DUK": (
        "Duke Energy",
        "Utilities",
        "Hold",
        "What is the full investment thesis for Duke Energy including regulated rate base growth, clean energy transition capex, and dividend sustainability?",
    ),
    "SO": (
        "Southern Company",
        "Utilities",
        "Hold",
        "What is the full investment thesis for Southern Company including regulated utility earnings, nuclear capacity, and data center load growth?",
    ),
    "AEP": (
        "American Electric Power",
        "Utilities",
        "Hold",
        "What is the full investment thesis for American Electric Power including transmission investment program, rate base growth, and regulatory environment?",
    ),
    "EXC": (
        "Exelon",
        "Utilities",
        "Hold",
        "What is the full investment thesis for Exelon including regulated utility operations, nuclear generation value, and grid modernization investment?",
    ),

    # ── COMMUNICATIONS (5) ───────────────────────────────────────────────────
    "GOOGL": (
        "Alphabet",
        "Communications",
        "Accumulate",
        "What is the full investment thesis for Alphabet including Search AI resilience, YouTube monetization, Google Cloud growth, and Waymo optionality?",
    ),
    "META": (
        "Meta Platforms",
        "Communications",
        "Accumulate",
        "What is the full investment thesis for Meta including social media advertising strength, AI infrastructure investment, and Reality Labs trajectory?",
    ),
    "NFLX": (
        "Netflix",
        "Communications",
        "Hold",
        "What is the full investment thesis for Netflix including ad-supported tier monetization, password sharing recovery, and content investment cycle?",
    ),
    "T": (
        "AT&T",
        "Communications",
        "Hold",
        "What is the full investment thesis for AT&T including wireless subscriber trends, fiber buildout, debt reduction, and dividend sustainability?",
    ),
    "VZ": (
        "Verizon",
        "Communications",
        "Hold",
        "What is the full investment thesis for Verizon including wireless network quality, fixed wireless access growth, and balance sheet management?",
    ),

    # ── REAL ESTATE (5) ──────────────────────────────────────────────────────
    "PLD": (
        "Prologis",
        "Real Estate",
        "Accumulate",
        "What is the full investment thesis for Prologis including industrial real estate demand, e-commerce logistics tailwind, and development pipeline?",
    ),
    "EQIX": (
        "Equinix",
        "Real Estate",
        "Accumulate",
        "What is the full investment thesis for Equinix including data center demand, AI infrastructure tailwind, colocation pricing power, and global platform?",
    ),
    "AMT": (
        "American Tower",
        "Real Estate",
        "Hold",
        "What is the full investment thesis for American Tower including tower lease revenue durability, 5G densification, and international growth?",
    ),
    "O": (
        "Realty Income",
        "Real Estate",
        "Hold",
        "What is the full investment thesis for Realty Income including net lease model, monthly dividend track record, and interest rate sensitivity?",
    ),
    "SPG": (
        "Simon Property Group",
        "Real Estate",
        "Hold",
        "What is the full investment thesis for Simon Property Group including Class A mall resilience, redevelopment optionality, and dividend recovery?",
    ),
}

SECTOR_ORDER = [
    "Technology", "Semiconductors", "Financials", "Healthcare", "Consumer",
    "Industrials", "Energy", "Utilities", "Communications", "Real Estate",
]

# Stance adjacency — for "close miss" classification
STANCE_ORDER = ["Sell", "Avoid", "Hold", "Accumulate", "Buy"]


def stance_gap(got: str, expected: str) -> int:
    """Return absolute steps between two stances. 0=correct, 1=close, 2+=wrong."""
    try:
        return abs(STANCE_ORDER.index(got) - STANCE_ORDER.index(expected))
    except ValueError:
        return 99


# ─────────────────────────────────────────────────────────────────────────────
# REUSE HELPERS FROM validate_phase4b_production.py (inline copy)
# ─────────────────────────────────────────────────────────────────────────────

def call_analyze(company_name: str, question: str) -> dict:
    payload = json.dumps({"company_name": company_name, "question": question}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/analyze", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def _ev(title: str, summary: str, source: str = "Financial Modeling Prep") -> RetrievedEvidence:
    return RetrievedEvidence(
        title=title, source=source, summary=summary,
        timestamp=TODAY, relevance_score=0.88,
    )


def build_evidence(ticker: str, api_resp: dict) -> list:
    synth  = api_resp.get("synthesis", {})
    equity = api_resp.get("equity", {})
    items  = []

    items.append(_ev(
        title=f"{ticker} ratios-ttm valuation data — P/E, EV/EBITDA, forward multiples",
        summary=f"Current market valuation metrics for {ticker}.",
        source="Financial Modeling Prep — ratios-ttm",
    ))
    items.append(_ev(
        title=f"{ticker} analyst-estimates consensus — EPS and revenue forecast",
        summary=f"Analyst consensus for {ticker}: forward EPS, revenue, and price targets.",
        source="analyst-estimates consensus",
    ))
    items.append(_ev(
        title=f"{ticker} quarterly earnings — beat/miss vs consensus",
        summary=f"Recent earnings results for {ticker}.",
        source="Earnings Report",
    ))

    for i, pt in enumerate((synth.get("bull_case") or equity.get("bull_case") or [])[:4]):
        items.append(_ev(f"{ticker} — bull case driver {i+1}", str(pt)[:250], "Investment Research"))
    for i, pt in enumerate((synth.get("key_risks") or equity.get("key_risks") or [])[:3]):
        items.append(_ev(f"{ticker} — risk factor {i+1}", str(pt)[:250], "Risk Analysis"))
    for i, pt in enumerate((synth.get("key_catalysts") or equity.get("key_catalysts") or [])[:3]):
        items.append(_ev(f"{ticker} — catalyst {i+1}", str(pt)[:250], "Market Intelligence"))
    for i, pt in enumerate((synth.get("key_drivers_ranked") or [])[:3]):
        items.append(_ev(f"{ticker} — key driver {i+1}", str(pt)[:250], "Equity Research"))

    return items


def _join(lst: list, sep: str = ". ") -> str:
    return sep.join(str(x) for x in (lst or []) if x)


def _conf(text: str, base: float = 0.52) -> float:
    t = text.lower()
    pos = ("strong", "robust", "durable", "compelling", "mission-critical",
           "moat", "pricing power", "resilient", "secular", "subscription",
           "recurring", "dominant", "essential", "sticky", "free cash flow")
    neg = ("uncertain", "execution risk", "disruption", "speculative", "binary",
           "unproven", "early stage", "challenging", "headwind", "volatile",
           "cyclical exposure", "execution dependent")
    score = base + sum(0.03 for w in pos if w in t) - sum(0.025 for w in neg if w in t)
    return round(min(0.82, max(0.28, score)), 3)


def build_inputs(ticker: str, api_resp: dict) -> dict:
    synth   = api_resp.get("synthesis", {})
    equity  = api_resp.get("equity", {})
    macro_r = api_resp.get("macro", {})

    bull      = _join(synth.get("bull_case") or equity.get("bull_case") or [])
    bear      = _join(synth.get("bear_case") or equity.get("bear_case") or [])
    risks_lst = (synth.get("key_risks") or equity.get("key_risks") or [])
    risk_text = _join(risks_lst)
    mac_text  = _join(macro_r.get("macro_overlay") or synth.get("macro_overlay") or [])
    llm_conf  = float(synth.get("confidence_score") or 0.50)
    mac_conf  = _conf(mac_text, base=0.45) if mac_text else 0.43

    quality = QualityAssessment(
        moat=bull[:500], revenue_durability=bull[:300],
        operating_quality=bull[:300], overall=(bull+" "+bear)[:600],
        confidence=_conf(bull, base=min(0.68, llm_conf + 0.08)),
    )
    macro = MacroSensitivity(
        rate_sensitivity=mac_text[:200],
        overall=mac_text[:400] or f"{ticker} macro sensitivity is moderate.",
        confidence=mac_conf,
    )
    risk = RiskProfile(
        key_risks=risks_lst[:5], competitive_risk=bear[:300],
        overall=risk_text[:400], confidence=_conf(risk_text, base=0.50),
    )
    v_lower = (bull + " " + bear).lower()
    if any(w in v_lower for w in ("overvalued", "expensive", "stretched multiple", "premium priced")):
        val_stance = "overpriced"
    elif any(w in v_lower for w in ("undervalued", "cheap", "deep discount", "value")):
        val_stance = "underpriced"
    else:
        val_stance = "fairly_valued"

    valuation = ValuationView(
        overall=bull[:400], valuation_stance=val_stance,
        confidence=_conf(bull, base=0.52),
    )
    catalysts = (synth.get("key_catalysts") or equity.get("key_catalysts") or [])
    market = MarketContext(
        recent_catalysts=catalysts[:3],
        overall=_join(catalysts), confidence=0.52,
    )
    return {
        "quality": quality, "macro": macro, "risk": risk,
        "valuation": valuation, "market": market,
        "mac_conf": mac_conf, "llm_conf": llm_conf,
        "llm_stance": synth.get("stance", ""),
        "val_stance": val_stance,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CHECKPOINT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT):
        try:
            with open(CHECKPOINT) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_checkpoint(results: dict):
    with open(CHECKPOINT, "w") as f:
        json.dump(results, f, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# PER-COMPANY RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_company(ticker: str, company_name: str, sector: str,
                expected: str, question: str) -> dict | None:
    """Run production conviction for one company. Returns result dict or None on error."""

    print(f"  [1/3] /analyze ...", end="", flush=True)
    try:
        api = call_analyze(company_name, question)
        synth = api.get("synthesis", {})
        llm_conf = synth.get("confidence_score", 0)
        llm_st   = synth.get("stance", "")
        print(f" ✓  conf={llm_conf:.3f} stance={llm_st}")
    except Exception as e:
        print(f" ✗ FAILED: {e}")
        return None

    print(f"  [2/3] Building evidence ...", end="", flush=True)
    evidence = build_evidence(ticker, api)
    inputs   = build_inputs(ticker, api)
    print(f" ✓  {len(evidence)} items")

    profile = get_knowledge_profile(ticker)
    company = CompanyContext(ticker=ticker, company_name=company_name, sector=sector)

    print(f"  [3/3] compute_conviction() ...", end="", flush=True)
    try:
        result = compute_conviction(
            evidence=evidence,
            valuation=inputs["valuation"],
            macro=inputs["macro"],
            risk=inputs["risk"],
            market=inputs["market"],
            quality=inputs["quality"],
            company=company,
            ranked=None,
            governance_warnings=[],
            profile=profile,
        )
        print(f" ✓")
    except Exception as e:
        print(f" ✗ FAILED: {e}")
        import traceback; traceback.print_exc()
        return None

    dims       = result.dimensions
    final_score = result.final_score
    frag        = dims.expectation_fragility
    ta          = dims.thesis_alignment
    macro_unc   = dims.macro_uncertainty
    eq          = dims.evidence_quality
    ef          = dims.evidence_freshness
    vc          = dims.valuation_certainty

    durability = _compute_business_durability(
        inputs["quality"], inputs["risk"], evidence, profile=profile
    )
    # Phase 5A: use result.directional_stance directly from compute_conviction()
    # which uses the fully-computed regime (val_stance floor applied) and
    # val_stance gating. Previously this re-called _compute_directional_stance
    # with expectation_regime="fair" hardcoded — that was wrong.
    stance = result.directional_stance
    regime = _classify_expectation_regime(
        frag, inputs["val_stance"], durability
    )
    dom_dim = _detect_dominant_dimension(
        inputs["macro"], inputs["risk"], inputs["valuation"]
    )

    gap    = stance_gap(stance, expected)
    correct = (gap == 0)

    # Root cause heuristic for misclassifications
    root_cause = ""
    if not correct:
        if gap >= 2:
            if final_score < 0.42 and expected in ("Accumulate", "Buy"):
                root_cause = "Score too low — likely low VC or TA"
            elif final_score >= 0.58 and expected in ("Avoid", "Sell"):
                root_cause = "Score too high — over-conviction"
            elif frag >= 0.62:
                root_cause = "High fragility suppressing score"
            else:
                root_cause = f"Score {final_score:.3f} vs expected {expected} — investigate"
        else:
            # Adjacent miss (Hold↔Accumulate, Avoid↔Hold)
            if expected == "Accumulate" and stance == "Hold":
                gap_to_acc = 0.58 - final_score
                root_cause = f"Close miss — {gap_to_acc:.4f} below Accumulate threshold (dur={durability:.3f}, frag={frag:.3f})"
            elif expected == "Avoid" and stance == "Hold":
                root_cause = f"Close miss — score {final_score:.3f} landed in Hold band (expected Avoid)"
            elif expected == "Hold" and stance == "Accumulate":
                root_cause = f"Slight over-conviction — score {final_score:.3f} crossed Accumulate"
            else:
                root_cause = f"Adjacent miss: got {stance}, expected {expected}"

    return {
        "ticker": ticker,
        "company_name": company_name,
        "sector": sector,
        "expected": expected,
        "stance": stance,
        "correct": correct,
        "gap": gap,
        "root_cause": root_cause,
        "final_score": round(final_score, 4),
        "durability": round(durability, 4),
        "frag": round(frag, 4),
        "ta": round(ta, 4),
        "macro_unc": round(macro_unc, 4),
        "eq": round(eq, 4),
        "ef": round(ef, 4),
        "vc": round(vc, 4),
        "dom_dim": dom_dim,
        "setup_label": result.setup_label,
        "regime": regime,
        "llm_conf": round(float(inputs["llm_conf"]), 3),
        "llm_stance": inputs["llm_stance"],
        "val_stance": inputs["val_stance"],
        "has_profile": profile is not None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# REPORT GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def print_report(results: dict):
    all_r = list(results.values())
    n     = len(all_r)
    n_correct = sum(1 for r in all_r if r["correct"])
    n_close   = sum(1 for r in all_r if r.get("gap", 99) == 1)
    n_wrong   = sum(1 for r in all_r if r.get("gap", 0) >= 2)

    print(f"\n\n{'='*110}")
    print(f"50-COMPANY PRODUCTION VALIDATION — FINAL REPORT")
    print(f"Schema: {CONVICTION_SCHEMA_VERSION}  |  Backend: {BASE_URL}")
    print(f"{'='*110}")

    # ── Overall accuracy ──────────────────────────────────────────────────────
    print(f"\n── OVERALL ACCURACY ──────────────────────────────────────────────────────────────")
    print(f"  Companies evaluated : {n}/50")
    print(f"  Correct (exact)     : {n_correct}/{n}  ({100*n_correct/n:.1f}%)")
    print(f"  Close miss (±1 step): {n_close}/{n}  ({100*n_close/n:.1f}%)")
    print(f"  Wrong (≥2 steps)    : {n_wrong}/{n}  ({100*n_wrong/n:.1f}%)")

    # ── Sector accuracy ───────────────────────────────────────────────────────
    print(f"\n── SECTOR ACCURACY ───────────────────────────────────────────────────────────────")
    print(f"  {'Sector':<22} {'Correct':>8} {'Close':>8} {'Wrong':>8} {'Score':>8}")
    print(f"  {'-'*56}")
    sector_results = defaultdict(list)
    for r in all_r:
        sector_results[r["sector"]].append(r)

    for sector in SECTOR_ORDER:
        sr = sector_results.get(sector, [])
        if not sr:
            continue
        sc = sum(1 for r in sr if r["correct"])
        sl = sum(1 for r in sr if r.get("gap") == 1)
        sw = sum(1 for r in sr if r.get("gap", 0) >= 2)
        pct = f"{100*sc/len(sr):.0f}%"
        print(f"  {sector:<22} {sc:>5}/{len(sr)}   {sl:>6}   {sw:>6}   {pct:>7}")

    # ── Per-company results table ─────────────────────────────────────────────
    print(f"\n── PER-COMPANY RESULTS ───────────────────────────────────────────────────────────")
    print(f"  {'Ticker':<6} {'Sector':<16} {'Expected':<12} {'Got':<12} {'Score':>7} "
          f"{'Dur':>6} {'Frag':>6} {'TA':>6} {'Regime':<10} {'✓/?':<5} Notes")
    print(f"  {'-'*120}")
    for sector in SECTOR_ORDER:
        print(f"  ── {sector} ──")
        for r in sector_results.get(sector, []):
            status = "✓" if r["correct"] else ("~" if r.get("gap") == 1 else "✗")
            note   = r.get("root_cause", "")[:40]
            prof   = "" if r["has_profile"] else "(no profile)"
            regime = r.get("regime", "?")
            print(f"  {r['ticker']:<6} {r['sector']:<16} {r['expected']:<12} {r['stance']:<12} "
                  f"{r['final_score']:>7.4f} {r['durability']:>6.3f} {r['frag']:>6.3f} {r['ta']:>6.3f} "
                  f"{regime:<10} {status:<5} {note} {prof}")

    # ── False positives ───────────────────────────────────────────────────────
    fp = [r for r in all_r if r.get("gap", 0) >= 1 and
          STANCE_ORDER.index(r["stance"]) > STANCE_ORDER.index(r["expected"])]
    print(f"\n── FALSE POSITIVES (over-conviction: got higher than expected) ───────────────────")
    if fp:
        for r in fp:
            print(f"  {r['ticker']:<6} expected={r['expected']:<12} got={r['stance']:<12} "
                  f"score={r['final_score']:.4f}  {r.get('root_cause','')}")
    else:
        print(f"  None")

    # ── False negatives ───────────────────────────────────────────────────────
    fn = [r for r in all_r if r.get("gap", 0) >= 1 and
          STANCE_ORDER.index(r["stance"]) < STANCE_ORDER.index(r["expected"])]
    print(f"\n── FALSE NEGATIVES (under-conviction: got lower than expected) ───────────────────")
    if fn:
        for r in fn:
            print(f"  {r['ticker']:<6} expected={r['expected']:<12} got={r['stance']:<12} "
                  f"score={r['final_score']:.4f}  dur={r['durability']:.3f}  frag={r['frag']:.3f}  "
                  f"{r.get('root_cause','')}")
    else:
        print(f"  None")

    # ── Confidence distribution ───────────────────────────────────────────────
    scores = [r["final_score"] for r in all_r]
    buckets = {
        "Avoid zone   (<0.42)":  [s for s in scores if s < 0.42],
        "Hold zone    (0.42–0.58)": [s for s in scores if 0.42 <= s < 0.58],
        "Accum zone   (0.58–0.72)": [s for s in scores if 0.58 <= s < 0.72],
        "Buy zone     (≥0.72)":  [s for s in scores if s >= 0.72],
    }
    print(f"\n── CONFIDENCE DISTRIBUTION ───────────────────────────────────────────────────────")
    for label, bucket in buckets.items():
        if bucket:
            avg = sum(bucket) / len(bucket)
            bar = "█" * len(bucket)
            print(f"  {label}  n={len(bucket):2d}  avg={avg:.3f}  {bar}")

    # ── Calibration issues ────────────────────────────────────────────────────
    print(f"\n── CALIBRATION ISSUES ────────────────────────────────────────────────────────────")

    # No-profile companies
    no_prof = [r for r in all_r if not r["has_profile"]]
    if no_prof:
        np_correct = sum(1 for r in no_prof if r["correct"])
        print(f"  No-profile companies ({len(no_prof)}): {np_correct}/{len(no_prof)} correct")
        for r in no_prof:
            st = "✓" if r["correct"] else "✗"
            print(f"    {st} {r['ticker']:<6} expected={r['expected']:<12} got={r['stance']:<12} score={r['final_score']:.4f}")

    # Systematic over/under by sector
    print(f"\n  Sector-level bias check:")
    for sector in SECTOR_ORDER:
        sr = sector_results.get(sector, [])
        if not sr:
            continue
        over  = sum(1 for r in sr if STANCE_ORDER.index(r["stance"]) > STANCE_ORDER.index(r["expected"]))
        under = sum(1 for r in sr if STANCE_ORDER.index(r["stance"]) < STANCE_ORDER.index(r["expected"]))
        if over >= 2:
            print(f"    {sector:<22}: OVER-CONVICTION bias  ({over}/5 scored higher than expected)")
        elif under >= 2:
            print(f"    {sector:<22}: UNDER-CONVICTION bias ({under}/5 scored lower than expected)")

    # Durability distribution
    dur_vals = [r["durability"] for r in all_r]
    durable   = sum(1 for d in dur_vals if d >= 0.65)
    quality_t = sum(1 for d in dur_vals if 0.55 <= d < 0.65)
    below     = sum(1 for d in dur_vals if d < 0.55)
    print(f"\n  Durability tier distribution:")
    print(f"    Durable    (≥0.65): {durable:2d} companies")
    print(f"    Quality  (0.55–0.65): {quality_t:2d} companies")
    print(f"    Below      (<0.55): {below:2d} companies")

    # ── Systematic weaknesses ─────────────────────────────────────────────────
    print(f"\n── SYSTEMATIC WEAKNESSES ─────────────────────────────────────────────────────────")

    wrong_list = [r for r in all_r if not r["correct"]]
    if not wrong_list:
        print(f"  None detected — all {n} companies classified correctly.")
    else:
        # Group by root cause patterns
        low_vc    = [r for r in wrong_list if "VC" in r.get("root_cause","")]
        low_score = [r for r in wrong_list if "Score too low" in r.get("root_cause","")]
        no_p      = [r for r in wrong_list if not r["has_profile"]]
        close     = [r for r in wrong_list if r.get("gap") == 1]
        hard_miss = [r for r in wrong_list if r.get("gap", 0) >= 2]

        if close:
            print(f"  Close misses (gap=1):   {len(close)} companies — within ±1 step")
            for r in close:
                print(f"    {r['ticker']:<6} {r.get('root_cause','')}")
        if hard_miss:
            print(f"  Hard misses (gap≥2):    {len(hard_miss)} companies — requires investigation")
            for r in hard_miss:
                print(f"    {r['ticker']:<6} expected={r['expected']}, got={r['stance']}, score={r['final_score']:.4f}")
        if no_p:
            print(f"  No-profile misses:      {len(no_p)} — consider adding profiles")
        if low_score:
            print(f"  Low-score false negatives: {len(low_score)} — VC/TA calibration candidate")

    # ── Final verdict ─────────────────────────────────────────────────────────
    print(f"\n── PHASE 4 GENERALIZATION VERDICT ────────────────────────────────────────────────")
    accuracy_pct = 100 * n_correct / n if n > 0 else 0
    if accuracy_pct >= 90:
        verdict = "STRONG GENERALIZATION — Phase 4 calibration holds across the 50-company universe"
    elif accuracy_pct >= 80:
        verdict = "GOOD GENERALIZATION — minor calibration gaps remain"
    elif accuracy_pct >= 70:
        verdict = "PARTIAL GENERALIZATION — targeted fixes warranted"
    else:
        verdict = "WEAK GENERALIZATION — systematic recalibration needed"
    print(f"  Accuracy: {n_correct}/{n} ({accuracy_pct:.1f}%)")
    print(f"  Verdict:  {verdict}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*110}")
    print(f"50-COMPANY PRODUCTION VALIDATION  |  Phase 4 Generalization Test")
    print(f"Backend: {BASE_URL}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*110}\n")

    results = load_checkpoint()
    if results:
        print(f"[Checkpoint] Resuming from {len(results)} saved results\n")

    tickers_ordered = []
    for sector in SECTOR_ORDER:
        for ticker, info in COMPANIES.items():
            if info[1] == sector:
                tickers_ordered.append(ticker)

    total = len(tickers_ordered)
    done  = 0

    for i, ticker in enumerate(tickers_ordered):
        if ticker in results:
            done += 1
            print(f"  [{done:2d}/{total}] {ticker:<6} — SKIPPED (checkpoint)")
            continue

        company_name, sector, expected, question = COMPANIES[ticker]
        done += 1
        print(f"\n{'─'*80}")
        print(f"  [{done:2d}/{total}] {ticker}  ({company_name})  [{sector}]  expected={expected}")
        print(f"{'─'*80}")

        r = run_company(ticker, company_name, sector, expected, question)
        if r is not None:
            status = "✓ CORRECT" if r["correct"] else f"✗ got {r['stance']} (expected {expected})"
            print(f"  → score={r['final_score']:.4f}  stance={r['stance']:<12}  dur={r['durability']:.3f}  frag={r['frag']:.3f}  {status}")
            results[ticker] = r
            save_checkpoint(results)
        else:
            print(f"  → FAILED — skipping")

        # Polite delay between API calls
        if done < total:
            time.sleep(3)

    print(f"\n\n[Validation complete]  {len(results)}/50 companies evaluated\n")
    print_report(results)


if __name__ == "__main__":
    main()
