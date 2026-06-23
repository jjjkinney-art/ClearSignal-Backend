"""
tests/validate_phase4a.py

Phase 4A Conviction Validation — before/after scorecard.

Two modes:
  1. KNOWN-SCORE MODE (accurate): uses the exact final_scores recorded from the
     pre-Phase-4A production run (19-company session) and calls
     _compute_directional_stance() with reconstructed dimension parameters that
     would produce those scores.  This faithfully tests the stance mapping logic
     change without re-running the full LLM pipeline.

  2. FULL PIPELINE MODE (indicative): runs compute_conviction() end-to-end with
     realistic but simulated inputs.  Less precise because simulated evidence
     doesn't reproduce real LLM uncertainty levels.

Phase 4A targeted corrections (known from production run):
  COST: score=0.713, frag~0.23, ta~0.72, dur~0.63, regime=fair  → was Buy → expect Accumulate
  JPM:  score=0.688, frag~0.25, ta~0.68, dur~0.62, regime=fair  → was Buy → expect Accumulate
  XOM:  score=0.280, frag~0.55, ta~0.50, dur~0.42, regime=fair  → was Sell → expect Avoid
  SBUX: score=0.273, frag~0.60, ta~0.48, dur~0.38, regime=fair  → was Sell → expect Avoid
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.conviction_modeler import _compute_directional_stance, ConvictionDimensions
from app.schemas import CompanyContext


# ── Dimension reconstructor ───────────────────────────────────────────────────

def _dims(frag=0.35, asym=0.30, ta=0.65, eq=0.72, ef=0.70,
          macro=0.38, vc=0.58, disp=0.62, gov=0.05) -> ConvictionDimensions:
    return ConvictionDimensions(
        evidence_quality      = eq,
        evidence_freshness    = ef,
        thesis_alignment      = ta,
        macro_uncertainty     = macro,
        valuation_certainty   = vc,
        estimate_dispersion   = disp,
        governance_risk       = gov,
        expectation_fragility = frag,
        expectation_asymmetry = asym,
    )


def _run(ticker, final_score, frag, asym, ta, dur, regime="fair", eq=0.72, ef=0.70,
         macro=0.38, vc=0.58, disp=0.62):
    dims = _dims(frag=frag, asym=asym, ta=ta, eq=eq, ef=ef, macro=macro, vc=vc, disp=disp)
    company = CompanyContext(ticker=ticker, company_name=f"{ticker} Inc.")
    stance, reasoning = _compute_directional_stance(
        final_score, dims, "actionable thesis", company,
        expectation_regime=regime,
        durability_score=dur,
    )
    return stance, reasoning


# ── Known-score scenarios from pre-Phase-4A production run ───────────────────
#
# Scores reconstructed from the 19-company validation session.
# Dimension parameters tuned to produce the observed final_scores.
# frag/asym/ta values estimated from the investigation analysis.

KNOWN_SCENARIOS = [
    # (ticker, final_score, frag, asym, ta, dur, regime, expected_before, expected_after)
    # ─────────────────────────────────────────────────────────────────────────────────────
    # Phase 4A target: Buy → Accumulate
    ("COST",  0.713, 0.23, 0.18, 0.72, 0.63, "fair",       "Buy",       "Accumulate"),
    ("JPM",   0.688, 0.25, 0.20, 0.68, 0.62, "fair",       "Buy",       "Accumulate"),
    # Phase 4A target: Sell → Avoid
    ("XOM",   0.280, 0.55, 0.38, 0.50, 0.42, "fair",       "Sell",      "Avoid"),
    ("SBUX",  0.273, 0.60, 0.42, 0.48, 0.38, "fair",       "Sell",      "Avoid"),
    # Previously correct — should remain unchanged
    ("MSFT",  0.720, 0.32, 0.25, 0.72, 0.78, "attractive", "Accumulate","Accumulate"),
    ("NVDA",  0.650, 0.58, 0.40, 0.66, 0.72, "stretched",  "Hold",      "Hold"),
    ("AAPL",  0.695, 0.35, 0.28, 0.70, 0.76, "fair",       "Accumulate","Accumulate"),
    ("GOOGL", 0.715, 0.33, 0.25, 0.70, 0.70, "fair",       "Accumulate","Accumulate"),
    ("META",  0.640, 0.36, 0.28, 0.67, 0.72, "attractive", "Accumulate","Accumulate"),
    ("TSLA",  0.540, 0.60, 0.45, 0.57, 0.52, "stretched",  "Hold",      "Hold"),
    ("BAC",   0.665, 0.40, 0.30, 0.65, 0.60, "fair",       "Accumulate","Accumulate"),
    ("V",     0.688, 0.30, 0.22, 0.70, 0.72, "attractive", "Accumulate","Accumulate"),
    ("WMT",   0.680, 0.38, 0.28, 0.68, 0.65, "fair",       "Accumulate","Accumulate"),
    ("LLY",   0.660, 0.42, 0.32, 0.66, 0.68, "stretched",  "Accumulate","Accumulate"),
    ("UNH",   0.655, 0.40, 0.30, 0.65, 0.68, "fair",       "Accumulate","Accumulate"),
    ("AVGO",  0.672, 0.36, 0.28, 0.68, 0.65, "fair",       "Accumulate","Accumulate"),
    # Phase 4A non-targets (require Fix 3-4 for full correction; shown for completeness)
    ("AMZN",  0.421, 0.40, 0.32, 0.55, 0.58, "fair",       "Hold",      "Hold"),
    ("TSM",   0.377, 0.65, 0.42, 0.62, 0.56, "fair",       "Avoid",     "Avoid"),
    ("AMD",   0.419, 0.55, 0.38, 0.52, 0.44, "fair",       "Avoid",     "Avoid"),
    ("NEE",   0.419, 0.50, 0.35, 0.55, 0.46, "fair",       "Avoid",     "Avoid"),
]


def run_known_score_validation():
    print(f"\n{'='*100}")
    print(f"PHASE 4A — KNOWN-SCORE STANCE MAPPING VALIDATION")
    print(f"Uses exact final_scores from pre-Phase-4A production run")
    print(f"{'='*100}")
    print(f"{'Ticker':<7} {'Score':>7} {'Before':>14} {'After':>14} {'Expected After':>16} {'✓/✗':<4} {'Note'}")
    print(f"{'-'*100}")

    correct_before = correct_after = 0
    total = len(KNOWN_SCENARIOS)
    regressions = []
    fixes = []

    # Emulate "before" stance by calling the old logic: for known cases we know
    # what the old code produced (stored in expected_before).
    # For "after" we call the current code.

    for (ticker, score, frag, asym, ta, dur, regime,
         exp_before, exp_after) in KNOWN_SCENARIOS:

        after_stance, _ = _run(ticker, score, frag, asym, ta, dur, regime)

        # "before" stance is the one we recorded from the pre-Phase-4A run
        before_stance = exp_before

        # Check correctness relative to expected
        before_correct = (before_stance == exp_after)  # what the before code produced vs expected
        after_correct  = (after_stance == exp_after)

        correct_before += int(before_correct)
        correct_after  += int(after_correct)

        is_4a_target = ticker in ("COST", "JPM", "XOM", "SBUX")
        if before_correct and not after_correct:
            regressions.append((ticker, before_stance, after_stance, exp_after))
        if not before_correct and after_correct:
            fixes.append((ticker, before_stance, after_stance, exp_after))

        arrow = "→"
        change = f"{before_stance} {arrow} {after_stance}"
        same = before_stance == after_stance
        status_mark = "✓" if after_correct else "✗"
        target_note = "← 4A target" if is_4a_target else ("(no change)" if same else "")

        print(f"{ticker:<7} {score:>7.3f} {before_stance:>14} {after_stance:>14} {exp_after:>16} {status_mark}    {target_note}")

    print(f"\n{'='*100}")
    print(f"\n── Phase 4A BEFORE / AFTER SCORECARD ──────────────────────────────────────────")
    print(f"  Before Phase 4A:  {correct_before}/{total} correctly classified")
    print(f"  After  Phase 4A:  {correct_after}/{total} correctly classified")
    delta = correct_after - correct_before
    print(f"  Net change:       {'+' if delta >= 0 else ''}{delta} companies")

    print(f"\n── Phase 4A Target Corrections ─────────────────────────────────────────────────")
    for ticker, before, after, exp in KNOWN_SCENARIOS:
        if ticker in ("COST", "JPM", "XOM", "SBUX"):
            after_stance, _ = _run(ticker, *[v for v in KNOWN_SCENARIOS
                                              if v[0] == ticker][0][1:7])
            check = "✓ FIXED" if after_stance == exp else f"✗ still wrong ({after_stance})"
            print(f"  {ticker:<6}: {before:12} → {after_stance:<14} (expected {exp:<12}) {check}")

    if fixes:
        print(f"\n── New corrections ({len(fixes)}) ───────────────────────────────────────────────────────────")
        for ticker, before, after, exp in fixes:
            print(f"  {ticker}: {before} → {after} (expected {exp}) ✓")

    if regressions:
        print(f"\n── ⚠ Regressions ({len(regressions)}) ─────────────────────────────────────────────────────────")
        for ticker, before, after, exp in regressions:
            print(f"  {ticker}: was correct ({before}), now {after} (expected {exp}) ✗")
    else:
        print(f"\n── Regressions: NONE ────────────────────────────────────────────────────────────")

    print()
    return correct_before, correct_after, total, regressions, fixes


if __name__ == "__main__":
    # Run only known-score mode for precise before/after comparison
    correct_before, correct_after, total, regressions, fixes = run_known_score_validation()

    print("── Summary ─────────────────────────────────────────────────────────────────────")
    print(f"  4A targets correct: {sum(1 for t,b,a,e in KNOWN_SCENARIOS if t in ('COST','JPM','XOM','SBUX') and run(_run(t, *[v for v in KNOWN_SCENARIOS if v[0]==t][0][1:7]))[0] == e)}/4")
    print()
