"""
tests/validate_phase6_targeted.py

Targeted validation for Phase 6 — 35 newly profiled companies.
Reports: durability before/after, stance before/after, accuracy gain.

Run:
    python3 tests/validate_phase6_targeted.py
"""
from __future__ import annotations
import sys
sys.path.insert(0, ".")

from datetime import datetime, timezone
from collections import defaultdict
from app.schemas import (
    QualityAssessment, MacroSensitivity, RiskProfile,
    ValuationView, MarketContext, RetrievedEvidence, CompanyContext,
)
from app.services.conviction_modeler import (
    compute_conviction, _compute_business_durability, _classify_expectation_regime,
)
from app.services.company_knowledge import get_knowledge_profile
from tests.test_phase5b_profiles import _compute_layer1
from tests.validate_100_company import build_inputs  # reuse sector-calibrated inputs

TODAY = datetime.now(timezone.utc).isoformat()

# ── 35-company universe with expected stances ────────────────────────────────
TARGETS = {
    # Financials
    "WFC":  ("Wells Fargo",             "Financials",      "Hold",       "H"),
    # Semiconductors
    "QCOM": ("Qualcomm",                "Semiconductors",  "Hold",       "H"),
    "TXN":  ("Texas Instruments",       "Semiconductors",  "Hold",       "H"),
    "MU":   ("Micron Technology",       "Semiconductors",  "Hold",       "H"),
    "AMAT": ("Applied Materials",       "Semiconductors",  "Hold",       "H"),
    "LRCX": ("Lam Research",            "Semiconductors",  "Hold",       "H"),
    # Healthcare
    "MRK":  ("Merck",                   "Healthcare",      "Accumulate", "A"),
    "ABT":  ("Abbott Laboratories",     "Healthcare",      "Accumulate", "A"),
    "TMO":  ("Thermo Fisher",           "Healthcare",      "Accumulate", "A"),
    "PFE":  ("Pfizer",                  "Healthcare",      "Hold",       "H"),
    "MDT":  ("Medtronic",               "Healthcare",      "Hold",       "H"),
    # Consumer
    "HD":   ("Home Depot",              "Consumer",        "Accumulate", "A"),
    "MCD":  ("McDonald's",              "Consumer",        "Hold",       "H"),
    "SBUX": ("Starbucks",               "Consumer",        "Hold",       "H"),
    "TGT":  ("Target",                  "Consumer",        "Hold",       "H"),
    # Industrials
    "ETN":  ("Eaton",                   "Industrials",     "Accumulate", "A"),
    "CAT":  ("Caterpillar",             "Industrials",     "Hold",       "H"),
    "GE":   ("GE Aerospace",            "Industrials",     "Hold",       "H"),
    "LMT":  ("Lockheed Martin",         "Industrials",     "Hold",       "H"),
    # Energy
    "PSX":  ("Phillips 66",             "Energy",          "Hold",       "H"),
    "EOG":  ("EOG Resources",           "Energy",          "Hold",       "H"),
    "DVN":  ("Devon Energy",            "Energy",          "Hold",       "H"),
    "MPC":  ("Marathon Petroleum",      "Energy",          "Hold",       "H"),
    "VLO":  ("Valero Energy",           "Energy",          "Hold",       "H"),
    # Utilities
    "SRE":  ("Sempra",                  "Utilities",       "Hold",       "H"),
    "PCG":  ("PG&E",                    "Utilities",       "Hold",       "H"),
    "WEC":  ("WEC Energy",              "Utilities",       "Hold",       "H"),
    "ED":   ("Con Edison",              "Utilities",       "Hold",       "H"),
    "AWK":  ("American Water Works",    "Utilities",       "Hold",       "H"),
    # Communications
    "TMUS": ("T-Mobile",                "Communications",  "Hold",       "H"),
    # Real Estate
    "PSA":  ("Public Storage",          "Real Estate",     "Hold",       "H"),
    "EQR":  ("Equity Residential",      "Real Estate",     "Hold",       "H"),
    "VICI": ("VICI Properties",         "Real Estate",     "Hold",       "H"),
    "WELL": ("Welltower",               "Real Estate",     "Hold",       "H"),
    "AMH":  ("American Homes 4 Rent",   "Real Estate",     "Hold",       "H"),
}

# Phase 5C baseline durability before profiles (no-profile = base ~0.40-0.52)
BASELINE_DUR = {
    t: 0.44 if tier == "A" else 0.40
    for t, (_, _, _, tier) in TARGETS.items()
}
BASELINE_STANCE = "Buy"   # all no-profile companies got Buy in 100-company validation


def run():
    print(f"\n{'='*72}")
    print(f"Phase 6 Targeted Validation — {len(TARGETS)} newly profiled companies")
    print(f"{'='*72}\n")

    results, correct = [], 0

    for ticker, (company_name, sector, expected, tier) in TARGETS.items():
        profile = get_knowledge_profile(ticker)
        inp     = build_inputs(ticker, sector, tier)
        company = CompanyContext(ticker=ticker, company_name=company_name)

        result  = compute_conviction(
            quality=inp["quality"], macro=inp["macro"], risk=inp["risk"],
            valuation=inp["valuation"], market=inp["market"],
            evidence=inp["evidence"], company=company, profile=profile,
        )
        stance  = result.directional_stance
        frag    = result.dimensions.expectation_fragility
        score   = result.final_score
        dur     = _compute_business_durability(
            quality=inp["quality"], risk=inp["risk"],
            evidence=inp["evidence"], profile=profile,
        )
        l1      = _compute_layer1(profile)
        regime  = _classify_expectation_regime(frag, inp["val_stance"], dur)
        val_s   = inp["val_stance"]
        is_correct = (stance == expected)
        if is_correct:
            correct += 1

        baseline_dur   = BASELINE_DUR[ticker]
        dur_delta      = dur - baseline_dur
        stance_before  = BASELINE_STANCE
        mark = "✅" if is_correct else "〰️" if abs(
            ["Sell","Avoid","Hold","Accumulate","Buy","Aggressive Buy"].index(stance) -
            ["Sell","Avoid","Hold","Accumulate","Buy","Aggressive Buy"].index(expected)
        ) == 1 else "❌"

        results.append(dict(
            ticker=ticker, sector=sector, expected=expected, got=stance,
            tier=tier, l1=l1, dur=dur, frag=frag, score=score,
            regime=regime, val_stance=val_s, correct=is_correct,
            baseline_dur=baseline_dur, dur_delta=dur_delta,
        ))
        print(f"[{ticker:6s}] {company_name:26s} ({sector})")
        print(f"  Before:  stance={stance_before:<12s}  dur={baseline_dur:.3f}")
        print(f"  After:   stance={stance:<12s}  dur={dur:.3f}  L1={l1:.3f}  "
              f"frag={frag:.3f}  score={score:.3f}  {mark}")
        print(f"  Expected:{expected:<12s}  val_stance={val_s}  regime={regime}")
        print()

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"{'='*72}")
    print(f"RESULTS: {correct}/{len(TARGETS)} correct ({correct/len(TARGETS)*100:.0f}%)")
    print(f"{'='*72}")

    print(f"\n{'Ticker':6s}  {'Expected':11s}  {'Got':12s}  {'L1':5s}  "
          f"{'Dur_After':9s}  {'Dur_Delta':9s}  Stance_Before  Result")
    print("-" * 90)
    for r in results:
        dur_delta_s = f"+{r['dur_delta']:.3f}" if r['dur_delta'] >= 0 else f"{r['dur_delta']:.3f}"
        is_ok = r["correct"]
        gap = abs(
            ["Sell","Avoid","Hold","Accumulate","Buy","Aggressive Buy"].index(r["got"]) -
            ["Sell","Avoid","Hold","Accumulate","Buy","Aggressive Buy"].index(r["expected"])
        )
        mark = "✅" if is_ok else ("〰️" if gap == 1 else "❌")
        print(f"{r['ticker']:6s}  {r['expected']:11s}  {r['got']:12s}  "
              f"{r['l1']:.3f}  {r['dur']:9.3f}  {dur_delta_s:9s}  "
              f"{'Buy':<13s}  {mark}")

    # ── Accuracy delta ────────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print(f"ACCURACY GAIN SUMMARY")
    print(f"{'='*72}")
    print(f"  Before (no profiles):   0/{len(TARGETS)} (0%)")
    print(f"  After  (with profiles): {correct}/{len(TARGETS)} ({correct/len(TARGETS)*100:.0f}%)")
    print(f"  Delta:                  +{correct} correct")
    print()

    # Sector breakdown
    sec_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    for r in results:
        sec_stats[r["sector"]]["total"]   += 1
        sec_stats[r["sector"]]["correct"] += int(r["correct"])
    print(f"  Sector breakdown:")
    for sec, s in sec_stats.items():
        print(f"    {sec:16s}: {s['correct']}/{s['total']}")

    # Impact on 100-company validation
    prev_100 = 52  # Phase 5B baseline from validate_100_company.py
    new_100  = prev_100 - 0 + correct   # replaces 0 correct from no-profile
    print(f"\n  100-company validation impact:")
    print(f"    Before Phase 6:  {prev_100}/100 ({prev_100}%)")
    print(f"    After  Phase 6:  ~{new_100}/100 (~{new_100}%)")
    print(f"    (35 no-profile → {correct} correct)")

    # Tier breakdown
    acc_ok   = sum(1 for r in results if r["tier"] == "A" and r["correct"])
    acc_tot  = sum(1 for r in results if r["tier"] == "A")
    hold_ok  = sum(1 for r in results if r["tier"] == "H" and r["correct"])
    hold_tot = sum(1 for r in results if r["tier"] == "H")
    print(f"\n  Accumulate targets: {acc_ok}/{acc_tot}")
    print(f"  Hold targets:       {hold_ok}/{hold_tot}")
    print()


if __name__ == "__main__":
    run()
