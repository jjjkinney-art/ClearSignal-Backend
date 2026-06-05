"""
tests/validate_phase5b_targeted.py

Targeted validation for Phase 5B profile expansion.
Tests the 7 previously no-profile companies against the live /analyze API.

Reports:
  - durability before (Phase 5A baseline: 0.36–0.44 estimated)
  - durability after (with new profiles)
  - stance before (all "Buy" — no profile → Buy-broad)
  - stance after
  - regime and val_stance

Run
---
    python3 tests/validate_phase5b_targeted.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, ".")

from app.schemas import (
    QualityAssessment, MacroSensitivity, RiskProfile,
    ValuationView, MarketContext, RetrievedEvidence, CompanyContext,
)
from app.services.conviction_modeler import (
    compute_conviction,
    _compute_business_durability,
    _classify_expectation_regime,
    _score_expectation_fragility,
    CONVICTION_SCHEMA_VERSION,
)
from app.services.company_knowledge import get_knowledge_profile

BASE_URL = "http://localhost:8000"
TODAY    = datetime.now(timezone.utc).isoformat()

# ── 7 target companies ────────────────────────────────────────────────────────
TARGETS = {
    "ABBV": ("AbbVie",                  "Healthcare",   "Accumulate",
             "What is the full investment thesis for AbbVie including Humira "
             "successor pipeline, Skyrizi and Rinvoq growth, and dividend sustainability?"),
    "OXY":  ("Occidental Petroleum",   "Energy",       "Hold",
             "What is the full investment thesis for Occidental Petroleum including "
             "Permian Basin position, carbon capture strategy, and Berkshire backing?"),
    "PLD":  ("Prologis",               "Real Estate",  "Accumulate",
             "What is the full investment thesis for Prologis including industrial "
             "real estate demand, e-commerce logistics tailwind, and development pipeline?"),
    "EQIX": ("Equinix",               "Real Estate",  "Accumulate",
             "What is the full investment thesis for Equinix including data center demand, "
             "AI infrastructure tailwind, colocation pricing power, and global platform?"),
    "AMT":  ("American Tower",         "Real Estate",  "Hold",
             "What is the full investment thesis for American Tower including tower lease "
             "revenue durability, 5G densification, and international growth?"),
    "O":    ("Realty Income",          "Real Estate",  "Hold",
             "What is the full investment thesis for Realty Income including net lease "
             "model, monthly dividend track record, and interest rate sensitivity?"),
    "SPG":  ("Simon Property Group",   "Real Estate",  "Hold",
             "What is the full investment thesis for Simon Property Group including "
             "Class A mall resilience, redevelopment optionality, and dividend recovery?"),
}

STANCE_ORDER = ["Sell", "Avoid", "Hold", "Accumulate", "Buy", "Aggressive Buy"]


def stance_gap(got: str, expected: str) -> int:
    try:
        return abs(STANCE_ORDER.index(got) - STANCE_ORDER.index(expected))
    except ValueError:
        return 99


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
    items.append(_ev(f"{ticker} ratios-ttm", f"Current market valuation metrics for {ticker}.",
                     "Financial Modeling Prep — ratios-ttm"))
    items.append(_ev(f"{ticker} analyst-estimates", f"Analyst consensus for {ticker}: EPS and revenue.",
                     "analyst-estimates consensus"))
    items.append(_ev(f"{ticker} quarterly earnings", f"Recent earnings results for {ticker}.",
                     "Earnings Report"))
    for i, pt in enumerate((synth.get("bull_case") or equity.get("bull_case") or [])[:4]):
        items.append(_ev(f"{ticker} — bull case {i+1}", str(pt)[:250], "Investment Research"))
    for i, pt in enumerate((synth.get("key_risks") or equity.get("key_risks") or [])[:3]):
        items.append(_ev(f"{ticker} — risk {i+1}", str(pt)[:250], "Risk Analysis"))
    for i, pt in enumerate((synth.get("key_catalysts") or equity.get("key_catalysts") or [])[:3]):
        items.append(_ev(f"{ticker} — catalyst {i+1}", str(pt)[:250], "Market Intelligence"))
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
    return {"quality": quality, "macro": macro, "risk": risk,
            "valuation": valuation, "market": market, "val_stance": val_stance}


def run_targeted_validation():
    print(f"\n{'='*72}")
    print(f"Phase 5B Targeted Validation — {len(TARGETS)} companies")
    print(f"Profiles: ABBV, OXY, PLD, EQIX, AMT, O, SPG (all new)")
    print(f"{'='*72}\n")

    results = []
    correct = 0

    for ticker, (company_name, sector, expected, question) in TARGETS.items():
        print(f"[{ticker}] {company_name} ({sector}) — expected: {expected}")
        print(f"  Calling /analyze...")
        try:
            api_resp  = call_analyze(company_name, question)
            evidence  = build_evidence(ticker, api_resp)
            inputs    = build_inputs(ticker, api_resp)
            company   = CompanyContext(ticker=ticker, company_name=company_name)
            profile   = get_knowledge_profile(ticker)

            result = compute_conviction(
                quality   = inputs["quality"],
                macro     = inputs["macro"],
                risk      = inputs["risk"],
                valuation = inputs["valuation"],
                market    = inputs["market"],
                evidence  = evidence,
                company   = company,
                profile   = profile,   # Phase 5B: pass profile for Layer 1 durability
            )

            stance = result.directional_stance
            frag   = result.dimensions.expectation_fragility
            conf   = result.final_score
            # Compute durability separately using the same internal function
            dur    = _compute_business_durability(
                quality  = inputs["quality"],
                risk     = inputs["risk"],
                evidence = evidence,
                profile  = profile,
            )
            regime = _classify_expectation_regime(frag, inputs["val_stance"], dur)
            val_s     = inputs["val_stance"]
            gap       = stance_gap(stance, expected)
            is_correct = (stance == expected)

            if is_correct:
                correct += 1
                mark = "✅"
            elif gap == 1:
                mark = "〰️"
            else:
                mark = "❌"

            print(f"  {mark} stance={stance!r} (expected={expected!r}, gap={gap})")
            print(f"     dur={dur:.3f}  frag={frag:.3f}  regime={regime}  val_stance={val_s}")
            print(f"     conf={conf:.3f}  profile={'YES' if profile else 'NO'}")

            results.append({
                "ticker": ticker, "expected": expected, "got": stance,
                "dur": dur, "frag": frag, "regime": regime, "val_stance": val_s,
                "conf": conf, "correct": is_correct, "gap": gap,
            })
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"ticker": ticker, "expected": expected, "error": str(e)})
        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"{'='*72}")
    print(f"Phase 5B Results: {correct}/{len(TARGETS)} correct ({correct/len(TARGETS)*100:.0f}%)")
    print(f"{'='*72}")
    print(f"\n{'Ticker':6s}  {'Expected':10s}  {'Got':12s}  {'dur':5s}  {'val_stance':15s}  {'regime':12s}  Result")
    print("-" * 80)
    for r in results:
        if "error" in r:
            print(f"{r['ticker']:6s}  {r['expected']:10s}  {'ERROR':12s}  {'---':5s}  {'---':15s}  {'---':12s}  ❌")
            continue
        mark = "✅" if r["correct"] else ("〰️" if r["gap"]==1 else "❌")
        print(f"{r['ticker']:6s}  {r['expected']:10s}  {r['got']:12s}  "
              f"{r['dur']:.3f}  {r['val_stance']:15s}  {r['regime']:12s}  {mark}")

    # ── Durability summary ─────────────────────────────────────────────────────
    print(f"\n{'Ticker':6s}  {'L1_dur':7s}  {'Final_dur':9s}  {'Delta':6s}  Notes")
    print("-" * 60)
    # Phase 5A baseline: no-profile dur was ~0.40 (baseline) + LLM-only contribution ~0.08-0.12
    BASELINE_DUR = {"ABBV": 0.44, "OXY": 0.40, "PLD": 0.42, "EQIX": 0.41,
                    "AMT": 0.40, "O": 0.40, "SPG": 0.39}
    ACCUMULATE = {"ABBV", "PLD", "EQIX"}

    for r in results:
        if "error" in r:
            continue
        t = r["ticker"]
        baseline = BASELINE_DUR.get(t, 0.40)
        delta = r["dur"] - baseline
        target_tier = ">= 0.68" if t in ACCUMULATE else "[0.55, 0.68)"
        notes = ""
        if t in ACCUMULATE:
            notes = "Durable Accum" if r["dur"] >= 0.68 else "MISS: dur<0.68"
        else:
            if r["dur"] >= 0.55 and r["dur"] < 0.68:
                notes = "Durable Hold range"
            elif r["dur"] >= 0.68:
                notes = "WARN: dur>=0.68 (Accum)"
            else:
                notes = "WARN: dur<0.55 (below Hold)"
        # Estimate L1
        from tests.test_phase5b_profiles import _compute_layer1
        profile = get_knowledge_profile(t)
        l1 = _compute_layer1(profile) if profile else 0.40
        print(f"{t:6s}  {l1:.3f}    {r['dur']:.3f}      {delta:+.3f}  {notes}")

    stance_baseline = "Buy (all 7 before profiles)"
    print(f"\nBaseline stance (Phase 5A, before Phase 5B profiles): {stance_baseline}")
    print(f"Phase 5B improvement:  {correct}/7 correct")
    print(f"Projected 50-company impact: 21 + {correct} = {21+correct}/50  "
          f"({(21+correct)/50*100:.0f}%)")


if __name__ == "__main__":
    run_targeted_validation()
