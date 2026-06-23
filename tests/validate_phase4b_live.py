"""
tests/validate_phase4b_live.py

Live production validation for Phase 4B targets: TSM, AMD, AMZN, NEE.

Methodology (production-proxy)
-------------------------------
1. Call the deployed /analyze endpoint to get REAL LLM-generated agent text
   for each company.
2. Map the API response text fields into conviction modeler input schemas:
   - QualityAssessment ← synthesis.bull_case + equity.bull_case content
   - RiskProfile       ← synthesis.key_risks + synthesis.bear_case
   - MacroSensitivity  ← macro.macro_overlay
   - ValuationView     ← equity.bull_case / synthesis valuation content
3. Call compute_conviction() locally with those inputs + the actual
   CompanyKnowledgeProfile from company_knowledge (Fix 4 profiles).
4. _detect_dominant_dimension() runs with the new Fix 3 threshold (0.35),
   so dominant_dim reflects the Phase 4B behavior.

This is the most faithful pre-pipeline-integration validation possible without
wiring the conviction modeler into the /analyze pipeline itself.

Confidence values (quality.confidence, macro.confidence, risk.confidence) are
set by parsing the LLM text quality + synthesis confidence_score — these are
approximations.  The key conviction modeler outputs (durability, fragility,
compression, final_score, directional_stance) are deterministic given the
text inputs, so the validation is accurate for all fields EXCEPT the underlying
agent confidence values (which affect thesis_alignment and macro weighting).

Pre-4B reference (known production scores):
  TSM:  0.377, Avoid  | AMD: 0.419, Avoid | AMZN: 0.421, Hold | NEE: 0.419, Avoid
"""
from __future__ import annotations

import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import urllib.request
import urllib.error

from app.services.conviction_modeler import (
    compute_conviction,
    _compute_business_durability,
    _compute_directional_stance,
    _check_contradiction_compression,
    ConvictionDimensions,
)
from app.services.company_knowledge import get_knowledge_profile
from app.schemas import (
    CompanyContext,
    QualityAssessment,
    ValuationView,
    MacroSensitivity,
    RiskProfile,
    MarketContext,
    RetrievedEvidence,
)

BASE_URL = "https://clearsignal-backend-dlsc.onrender.com"


# ── API caller ────────────────────────────────────────────────────────────────

def call_analyze(company_name: str, question: str) -> dict:
    """Call the /analyze endpoint and return the JSON response."""
    url = f"{BASE_URL}/analyze"
    payload = json.dumps({
        "company_name": company_name,
        "question": question,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode('utf-8')[:200]}")
        raise
    except Exception as e:
        print(f"  Request failed: {e}")
        raise


# ── Text-to-conviction-input mapper ──────────────────────────────────────────

def _join(lst: list, sep: str = ". ") -> str:
    """Join a list of strings into a single text block."""
    return sep.join(str(x) for x in (lst or []) if x)


def _infer_confidence(text: str, fallback: float = 0.50) -> float:
    """Infer an agent confidence value from text quality signals."""
    t = text.lower()
    # Signals suggesting higher confidence
    high_conf = ("strong", "robust", "durable", "compelling", "clear", "significant",
                 "dominant", "mission-critical", "essential", "moat", "pricing power",
                 "secular", "resilient", "subscription", "recurring")
    low_conf = ("uncertain", "unclear", "mixed", "limited", "thin", "speculative",
                "narrative", "binary", "early stage", "unproven", "execution risk",
                "difficult to", "hard to predict", "volatile")
    h = sum(1 for w in high_conf if w in t)
    l = sum(1 for w in low_conf if w in t)
    # Blend: start at fallback, nudge up/down
    conf = fallback + (h - l) * 0.03
    return round(min(0.80, max(0.25, conf)), 3)


def map_response_to_inputs(ticker: str, api_resp: dict) -> dict:
    """Map an /analyze API response to conviction modeler input schemas."""
    synthesis  = api_resp.get("synthesis", {})
    equity     = api_resp.get("equity", {})
    macro_resp = api_resp.get("macro", {})

    # ── Quality text: bull case + competitive advantages ─────────────────────
    bull_text  = _join(synthesis.get("bull_case", []) or equity.get("bull_case", []))
    bear_text  = _join(synthesis.get("bear_case", []) or equity.get("bear_case", []))
    risk_text  = _join(synthesis.get("key_risks", []) or equity.get("key_risks", []))
    macro_text = _join(macro_resp.get("macro_overlay", []))
    # If macro_overlay empty, pull from synthesis
    if not macro_text:
        macro_text = _join(synthesis.get("macro_overlay", []))

    qual_text  = f"{bull_text} {bear_text}"
    llm_conf   = float(synthesis.get("confidence_score") or 0.50)

    # ── QualityAssessment ─────────────────────────────────────────────────────
    quality = QualityAssessment(
        moat               = bull_text[:500],
        revenue_durability = bull_text[:300],
        operating_quality  = bull_text[:300],
        overall            = qual_text[:600],
        confidence         = _infer_confidence(bull_text, fallback=min(0.65, llm_conf + 0.05)),
    )

    # ── MacroSensitivity ──────────────────────────────────────────────────────
    # Confidence: key for Fix 3 validation.  Real macro agents return 0.40-0.60.
    # If macro text exists and is rich → higher confidence; if thin → lower.
    macro_conf = _infer_confidence(macro_text, fallback=0.45) if macro_text else 0.42
    macro = MacroSensitivity(
        rate_sensitivity = macro_text[:200],
        overall          = macro_text[:400] or f"{ticker} has standard macro exposure.",
        confidence       = macro_conf,
    )

    # ── RiskProfile ───────────────────────────────────────────────────────────
    risks_list = (synthesis.get("key_risks") or equity.get("key_risks") or [])
    risk = RiskProfile(
        key_risks       = risks_list[:5],
        competitive_risk = bear_text[:300],
        overall          = risk_text[:400],
        confidence       = _infer_confidence(risk_text, fallback=0.48),
    )

    # ── ValuationView ─────────────────────────────────────────────────────────
    val_text = bull_text  # valuation discussion often in bull case
    # Try to detect valuation stance from text
    v_lower = (val_text + " " + bear_text).lower()
    if any(w in v_lower for w in ("overvalued", "expensive", "stretched", "premium multiple")):
        val_stance = "overpriced"
    elif any(w in v_lower for w in ("undervalued", "cheap", "discount", "attractive")):
        val_stance = "underpriced"
    elif any(w in v_lower for w in ("fairly valued", "fair value", "reasonable")):
        val_stance = "fairly_valued"
    else:
        val_stance = "fairly_valued"

    valuation = ValuationView(
        overall          = val_text[:400],
        valuation_stance = val_stance,
        confidence       = _infer_confidence(val_text, fallback=0.50),
    )

    # ── MarketContext ─────────────────────────────────────────────────────────
    catalysts = (synthesis.get("key_catalysts") or equity.get("key_catalysts") or [])
    market = MarketContext(
        recent_catalysts = catalysts[:3],
        overall          = _join(catalysts),
        confidence       = 0.50,
    )

    return {
        "quality": quality,
        "macro": macro,
        "risk": risk,
        "valuation": valuation,
        "market": market,
        "llm_conf": llm_conf,
        "llm_stance": synthesis.get("stance", ""),
        "llm_verdict": synthesis.get("final_verdict", ""),
        "verdict_reasoning": synthesis.get("verdict_reasoning", ""),
        "bull_text": bull_text,
        "bear_text": bear_text,
        "macro_text": macro_text,
        "macro_conf": macro_conf,
    }


# ── Compression trigger inspector ────────────────────────────────────────────

def get_compression_triggers(dims: ConvictionDimensions, durability: float) -> list:
    """Enumerate which contradiction compression triggers fired."""
    frag = dims.expectation_fragility
    macro = dims.macro_uncertainty
    triggers = []
    if frag >= 0.62:
        triggers.append(f"T6(frag={frag:.2f}≥0.62 → SIGNIFICANT×0.80)")
    if macro >= 0.80:
        triggers.append(f"T8(macro={macro:.2f}≥0.80 → SIGNIFICANT×0.80)")
    if len([t for t in triggers if "SIGNIFICANT" in t]) >= 2:
        triggers.append("→ SEVERE×0.70 (2+ SIGNIFICANT)")
    if durability >= 0.65 and triggers:
        triggers.append(f"DURABLE_FLOOR(dur={durability:.2f}≥0.65 → min×0.82)")
    return triggers or ["none"]


# ── Main validation runner ────────────────────────────────────────────────────

PRE_4B = {
    "TSM":  {"score": 0.377, "stance": "Avoid",  "dur": 0.56, "frag": 0.65},
    "AMD":  {"score": 0.419, "stance": "Avoid",  "dur": 0.44, "frag": 0.55},
    "AMZN": {"score": 0.421, "stance": "Hold",   "dur": 0.58, "frag": 0.40},
    "NEE":  {"score": 0.419, "stance": "Avoid",  "dur": 0.46, "frag": 0.50},
}

COMPANIES = {
    "TSM":  ("Taiwan Semiconductor", "What is the investment thesis for TSMC?"),
    "AMD":  ("AMD",  "What is the investment thesis for AMD?"),
    "AMZN": ("Amazon", "What is the investment thesis for Amazon?"),
    "NEE":  ("NextEra Energy", "What is the investment thesis for NextEra Energy?"),
}


def run_live_validation():
    print(f"\n{'='*100}")
    print(f"PHASE 4B — LIVE PRODUCTION VALIDATION (post-4B deploy: 70f897a)")
    print(f"Backend: {BASE_URL}")
    print(f"Methodology: /analyze → real LLM text → compute_conviction() locally")
    print(f"{'='*100}\n")

    results = {}

    for ticker, (company_name, question) in COMPANIES.items():
        print(f"\n{'─'*80}")
        print(f"  {ticker} ({company_name})")
        print(f"{'─'*80}")

        pre = PRE_4B[ticker]

        # ── Step 1: Live API call ─────────────────────────────────────────────
        print(f"  [1] Calling /analyze ...", end="", flush=True)
        try:
            api_resp = call_analyze(company_name, question)
            print(f" OK  (LLM conf={api_resp.get('synthesis',{}).get('confidence_score','?')}, "
                  f"stance={api_resp.get('synthesis',{}).get('stance','?')})")
        except Exception as e:
            print(f" FAILED: {e}")
            continue

        # ── Step 2: Map to conviction modeler inputs ──────────────────────────
        inputs = map_response_to_inputs(ticker, api_resp)
        profile = get_knowledge_profile(ticker)
        company = CompanyContext(
            ticker=ticker,
            company_name=company_name,
            sector={"TSM": "Technology", "AMD": "Technology",
                    "AMZN": "Consumer Discretionary", "NEE": "Utilities"}.get(ticker, ""),
        )

        # ── Step 3: Run conviction modeler ────────────────────────────────────
        print(f"  [2] Running compute_conviction() ...", end="", flush=True)
        try:
            result = compute_conviction(
                evidence=[],
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
            print(f" OK")
        except Exception as e:
            print(f" FAILED: {e}")
            import traceback; traceback.print_exc()
            continue

        # ── Extract key metrics ───────────────────────────────────────────────
        final_score   = result.final_score
        setup_label   = result.setup_label
        dims          = result.dimensions

        # Recompute durability for display
        durability = _compute_business_durability(
            inputs["quality"], inputs["risk"], [], profile=profile
        )

        # Get directional stance
        directional_stance, stance_reasoning = _compute_directional_stance(
            final_score, dims, setup_label, company,
            expectation_regime="fair",  # conservative default
            durability_score=durability,
        )

        # Compression triggers
        triggers = get_compression_triggers(dims, durability)

        # Dominant dimension (reflects Fix 3 threshold)
        from app.services.thesis_synthesizer import _detect_dominant_dimension
        dom_dim = _detect_dominant_dimension(inputs["macro"], inputs["risk"], inputs["valuation"])

        frag = dims.expectation_fragility
        ta   = dims.thesis_alignment
        macro_unc = dims.macro_uncertainty

        # ── Store results ─────────────────────────────────────────────────────
        results[ticker] = {
            "pre_score":      pre["score"],
            "post_score":     round(final_score, 4),
            "pre_stance":     pre["stance"],
            "post_stance":    directional_stance,
            "pre_dur":        pre["dur"],
            "post_dur":       round(durability, 4),
            "pre_frag":       pre["frag"],
            "post_frag":      round(frag, 4),
            "setup_label":    setup_label,
            "dominant_dim":   dom_dim,
            "macro_conf":     round(inputs["macro_conf"], 3),
            "ta":             round(ta, 4),
            "macro_unc":      round(macro_unc, 4),
            "compression":    triggers,
            "llm_stance":     inputs["llm_stance"],
            "llm_conf":       round(inputs["llm_conf"], 3),
            "verdict_reasoning": inputs["verdict_reasoning"][:120],
        }

        # ── Print summary ─────────────────────────────────────────────────────
        r = results[ticker]
        print(f"\n  ┌── {ticker} LIVE RESULTS ───────────────────────────────────────────")
        print(f"  │  Score:            {r['pre_score']:.3f} (pre-4B) → {r['post_score']:.4f} (post-4B)")
        print(f"  │  Stance:           {r['pre_stance']:10} → {r['post_stance']}")
        print(f"  │  Setup label:      {r['setup_label']}")
        print(f"  │  Dominant dim:     {r['dominant_dim']}")
        print(f"  │  Durability:       {r['pre_dur']:.3f} → {r['post_dur']:.4f}")
        print(f"  │  Fragility:        {r['pre_frag']:.3f} → {r['post_frag']:.4f}")
        print(f"  │  Thesis alignment: {r['ta']:.4f}")
        print(f"  │  Macro uncertainty:{r['macro_unc']:.4f}  (macro_conf={r['macro_conf']:.3f})")
        print(f"  │  Compression:      {', '.join(r['compression'])}")
        print(f"  │  LLM stance:       {r['llm_stance']}  (conf={r['llm_conf']:.3f})")
        print(f"  │  LLM verdict:      {r['verdict_reasoning'][:80]}...")
        print(f"  └─────────────────────────────────────────────────────────────────────")

        time.sleep(2)  # Avoid hammering the API

    # ── Final comparison table ────────────────────────────────────────────────
    print(f"\n\n{'='*100}")
    print(f"PHASE 4B LIVE — BEFORE / AFTER COMPARISON SUMMARY")
    print(f"{'='*100}")

    TARGET_STANCES = {"TSM": "Hold", "AMD": "Hold", "AMZN": "Hold", "NEE": "Hold"}
    ULTIMATE = {"TSM": "Accumulate", "AMD": "Hold", "AMZN": "Accumulate", "NEE": "Hold"}

    header = (f"{'Ticker':<6} {'Pre-Score':>10} {'Post-Score':>10} "
              f"{'Pre-Stance':>11} {'Post-Stance':>12} "
              f"{'Pre-Dur':>9} {'Post-Dur':>9} "
              f"{'Pre-Frag':>9} {'Post-Frag':>9} "
              f"{'Dom-Dim':>12} {'Target':>10} {'Result'}")
    print(header)
    print("─" * 130)

    for ticker in ["TSM", "AMD", "AMZN", "NEE"]:
        if ticker not in results:
            print(f"{ticker}: SKIPPED (API call failed)")
            continue
        r = results[ticker]
        target = TARGET_STANCES[ticker]
        ok = "✓" if r["post_stance"] == target else "✗"
        ultimate = ULTIMATE[ticker]
        note = f"→ {ultimate} needs Fix 5/live Fix 3" if ultimate != target else ""
        print(f"{ticker:<6} {r['pre_score']:>10.3f} {r['post_score']:>10.4f} "
              f"{r['pre_stance']:>11} {r['post_stance']:>12} "
              f"{r['pre_dur']:>9.3f} {r['post_dur']:>9.4f} "
              f"{r['pre_frag']:>9.3f} {r['post_frag']:>9.4f} "
              f"{r['dominant_dim']:>12} {target:>10} {ok} {note}")

    print(f"\n{'='*100}")

    # ── Fix 3 diagnosis ───────────────────────────────────────────────────────
    print(f"\n── Fix 3 Diagnosis (macro dominant_dim threshold) ──────────────────────────────")
    print(f"  Old threshold: macro.confidence < 0.58 → macro boost fires for most companies")
    print(f"  New threshold: macro.confidence < 0.35 → boost fires only for genuinely macro-dominated")
    print()
    for ticker in ["AMZN", "NEE"]:
        if ticker not in results:
            continue
        r = results[ticker]
        mc = r["macro_conf"]
        dom = r["dominant_dim"]
        old_dom = "macro" if mc < 0.58 else dom
        new_dom = "macro" if mc < 0.35 else dom
        changed = old_dom != new_dom
        print(f"  {ticker}: macro_conf={mc:.3f}")
        print(f"    Old threshold → dominant_dim would be: {old_dom}")
        print(f"    New threshold → dominant_dim is now:   {new_dom}  {'← Fix 3 EFFECT' if changed else '(no change; macro_conf >= 0.35 AND >= 0.58)'}")
    print()

    # ── Compression analysis ──────────────────────────────────────────────────
    print(f"── Compression Analysis ────────────────────────────────────────────────────────")
    for ticker in ["TSM", "AMD", "AMZN", "NEE"]:
        if ticker not in results:
            continue
        r = results[ticker]
        print(f"  {ticker}: {', '.join(r['compression'])}")

    print()
    return results


if __name__ == "__main__":
    results = run_live_validation()
