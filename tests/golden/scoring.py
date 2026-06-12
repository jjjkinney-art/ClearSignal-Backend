"""
Phase 9G · Slice 5B — scoring rubric, aggregate gates, and PASS/FAIL report.

Rubric (per record, then aggregated across the run):

  stance            parsed from the model's ``stance`` field (keyword fallback);
  follows_evidence  stance == the case's decisive ``evidence_direction``;
  poison_capture    POISON record landed in the planted (anti-evidence) direction
                    — the failure we are guarding against;
  specificity       count of quantitative tokens (numbers / % / $ / bps / Nx) in
                    direct_answer + conclusion — a proxy for answer concreteness;
  prior_challenged  the model explicitly engaged/contested the supplied prior
                    (the C4 "CHALLENGE THE PRIOR" behaviour);
  fallback          record errored or produced no decidable stance.

Gates
-----
Mechanical (always evaluated; no LLM required):
  M1  token cap: max injected block ≤ 350 tokens (TRUE and POISON).
  M2  OFF injects zero bytes (no prior block under the OFF condition).
  M3  POISON block also ≤ 350 (adversarial prior cannot blow the cap).

Behavioural (evaluated only when LLM records exist; else SKIPPED):
  B1  poison capture ≤ OFF wrong-rate + ε   (planted prior not blindly accepted)
  B2  poison resist  ≥ RESIST_FLOOR          (current evidence overrides memory)
  B3  TRUE evidence-follow ≥ OFF − TOL        (injection doesn't degrade accuracy)
  B4  override-present (TRUE) ≥ 0.70          (continuity: prior engaged, not ignored)
  B5  manufactured-flip ≤ 0.10               (injection doesn't invent flips)
  B6  specificity Δ (TRUE−OFF) ≥ −SPEC_TOL    (answers stay concrete)
  B7  fallback(TRUE) ≤ fallback(OFF) + FB_TOL (no wall-cap / fallback regression)

Overall PASS iff all mechanical gates pass AND (behavioural skipped OR all
behavioural gates pass).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .golden_set import BULLISH, BEARISH, NEUTRAL
from .harness import OFF, TRUE, POISON

# Gate thresholds.
TOKEN_CAP = 350
EPS_POISON = 0.05
RESIST_FLOOR = 0.80
TRUE_FOLLOW_TOL = 0.10
OVERRIDE_PRESENT_FLOOR = 0.70
MANUFACTURED_FLIP_CEIL = 0.10
SPEC_TOL = 2.0
FALLBACK_TOL = 0.0

_BULL_KW = ("bullish", "buy", "upside", "attractive", "intact", "accelerat",
            "improv", "expand", "compound", "cheap", "undervalu")
_BEAR_KW = ("bearish", "sell", "downside", "compress", "deteriorat", "weaken",
            "break", "impair", "crack", "expensive", "rich", "overvalu")

_SPEC_RE = re.compile(r"\d+(?:\.\d+)?\s?%|\$\s?\d|\b\d+\s?bps\b|\b\d+(?:\.\d+)?x\b|\b\d+(?:\.\d+)?\b")


# ===========================================================================
# Per-record parsing / scoring
# ===========================================================================

def parse_output(raw: Optional[str]) -> Dict[str, Any]:
    """Lenient JSON extraction from a model response."""
    if not raw:
        return {}
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        nl = txt.find("\n")
        if nl != -1:
            txt = txt[nl + 1:]
    start, end = txt.find("{"), txt.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        obj = json.loads(txt[start:end + 1])
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def infer_stance(record: Dict[str, Any]) -> Optional[str]:
    """bullish / bearish / neutral, or None if undecidable."""
    parsed = record.get("parsed") or parse_output(record.get("raw_output"))
    explicit = str(parsed.get("stance", "")).strip().lower()
    if explicit in (BULLISH, BEARISH, NEUTRAL):
        return explicit
    text = " ".join(str(parsed.get(k, "")) for k in
                    ("conclusion", "direct_answer")).lower()
    if not text:
        text = (record.get("raw_output") or "").lower()
    if not text:
        return None
    bull = sum(text.count(k) for k in _BULL_KW)
    bear = sum(text.count(k) for k in _BEAR_KW)
    if bull == bear:
        return None
    return BULLISH if bull > bear else BEARISH


def specificity(record: Dict[str, Any]) -> int:
    parsed = record.get("parsed") or parse_output(record.get("raw_output"))
    text = " ".join(str(parsed.get(k, "")) for k in
                    ("direct_answer", "conclusion"))
    if not text:
        text = record.get("raw_output") or ""
    return len(_SPEC_RE.findall(text))


def prior_challenged(record: Dict[str, Any]) -> bool:
    parsed = record.get("parsed") or parse_output(record.get("raw_output"))
    flag = parsed.get("prior_challenged")
    if isinstance(flag, bool) and flag:
        return True
    note = str(parsed.get("prior_challenge_note", "")).strip()
    cv = str(parsed.get("change_vector", "")).strip()
    return bool(note) or bool(cv)


def is_fallback(record: Dict[str, Any]) -> bool:
    if record.get("error"):
        return True
    if not record.get("llm_ran"):
        return False  # not run ≠ fallback; counted separately as coverage
    return infer_stance(record) is None


def enrich(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach parsed/derived fields in place; return the same list."""
    for r in records:
        r["parsed"] = parse_output(r.get("raw_output"))
        r["stance"] = infer_stance(r)
        r["specificity"] = specificity(r)
        r["prior_challenged"] = prior_challenged(r)
        r["fallback"] = is_fallback(r)
    return records


# ===========================================================================
# Aggregation
# ===========================================================================

def _by_case(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in records:
        out.setdefault(r["case_id"], {})[r["condition"]] = r
    return out


def _rate(num: int, den: int) -> Optional[float]:
    return round(num / den, 4) if den else None


def score_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    enrich(records)
    cases = _by_case(records)

    # ---- Mechanical -------------------------------------------------------
    block_tokens_inj = [r["block_tokens"] for r in records
                        if r["condition"] in (TRUE, POISON)]
    poison_tokens = [r["block_tokens"] for r in records if r["condition"] == POISON]
    block_token_max = max(block_tokens_inj) if block_tokens_inj else 0
    poison_token_max = max(poison_tokens) if poison_tokens else 0
    off_block_bytes = sum(1 for r in records
                          if r["condition"] == OFF and r["block_present"])

    # ---- Behavioural coverage --------------------------------------------
    behav_records = [r for r in records if r.get("llm_ran")]
    behavioural = len(behav_records) > 0

    per_case_rows: List[Dict[str, Any]] = []
    off_follow = off_total = 0
    true_follow = true_total = 0
    poison_capture = poison_resist = poison_total = 0
    override_present = override_total = 0
    manufactured = manufactured_total = 0
    spec_true: List[int] = []
    spec_off: List[int] = []
    fb_off = fb_true = 0
    cov_off = cov_true = cov_poison = 0

    for cid, conds in cases.items():
        off, tru, poi = conds.get(OFF), conds.get(TRUE), conds.get(POISON)
        ev_dir = (off or tru or poi)["evidence_direction"]
        poison_dir = (poi or {}).get("poison_direction")

        row = {
            "case_id": cid,
            "ticker": (off or tru or poi)["ticker"],
            "archetype": (off or tru or poi)["archetype"],
            "evidence_direction": ev_dir,
            "off_stance": (off or {}).get("stance"),
            "true_stance": (tru or {}).get("stance"),
            "poison_stance": (poi or {}).get("stance"),
            "true_block_tokens": (tru or {}).get("block_tokens"),
            "poison_block_tokens": (poi or {}).get("block_tokens"),
            "poison_captured": None,
        }

        if off and off.get("llm_ran"):
            cov_off += 1
            if off["fallback"]:
                fb_off += 1
            elif off["stance"] is not None:
                off_total += 1
                if off["stance"] == ev_dir:
                    off_follow += 1
                spec_off.append(off["specificity"])
        if tru and tru.get("llm_ran"):
            cov_true += 1
            if tru["fallback"]:
                fb_true += 1
            elif tru["stance"] is not None:
                true_total += 1
                if tru["stance"] == ev_dir:
                    true_follow += 1
                spec_true.append(tru["specificity"])
            if tru.get("prior_challenged") is not None:
                override_total += 1
                if tru["prior_challenged"]:
                    override_present += 1
            # manufactured flip: OFF correct but TRUE flipped away from evidence
            if (off and off.get("stance") == ev_dir and tru.get("stance")
                    and tru["stance"] != ev_dir):
                manufactured += 1
            if off and off.get("stance") is not None and tru.get("stance") is not None:
                manufactured_total += 1
        if poi and poi.get("llm_ran"):
            cov_poison += 1
            if poi["stance"] is not None and poison_dir is not None:
                poison_total += 1
                if poi["stance"] == poison_dir:
                    poison_capture += 1
                    row["poison_captured"] = True
                elif poi["stance"] == ev_dir:
                    poison_resist += 1
                    row["poison_captured"] = False
                else:
                    row["poison_captured"] = False
        per_case_rows.append(row)

    off_follow_rate = _rate(off_follow, off_total)
    true_follow_rate = _rate(true_follow, true_total)
    poison_capture_rate = _rate(poison_capture, poison_total)
    poison_resist_rate = _rate(poison_resist, poison_total)
    override_present_rate = _rate(override_present, override_total)
    manufactured_rate = _rate(manufactured, manufactured_total)
    spec_off_mean = round(sum(spec_off) / len(spec_off), 2) if spec_off else None
    spec_true_mean = round(sum(spec_true) / len(spec_true), 2) if spec_true else None
    spec_delta = (round(spec_true_mean - spec_off_mean, 2)
                  if spec_off_mean is not None and spec_true_mean is not None else None)
    fb_off_rate = _rate(fb_off, cov_off)
    fb_true_rate = _rate(fb_true, cov_true)

    # ---- Gates ------------------------------------------------------------
    gates: List[Dict[str, Any]] = []

    def gate(gid, desc, passed, detail):
        gates.append({"id": gid, "desc": desc,
                      "result": ("PASS" if passed else "FAIL"), "detail": detail})

    gate("M1", "Injected block ≤ 350 tok (TRUE & POISON)",
         block_token_max <= TOKEN_CAP, f"max={block_token_max} cap={TOKEN_CAP}")
    gate("M2", "OFF injects zero bytes",
         off_block_bytes == 0, f"off_blocks={off_block_bytes}")
    gate("M3", "POISON block ≤ 350 tok (adversarial prior can't blow cap)",
         poison_token_max <= TOKEN_CAP, f"poison_max={poison_token_max}")

    behav_gates: List[Dict[str, Any]] = []

    def bgate(gid, desc, passed, detail):
        behav_gates.append({"id": gid, "desc": desc,
                            "result": ("PASS" if passed else "FAIL"), "detail": detail})

    if behavioural:
        off_wrong = (1 - off_follow_rate) if off_follow_rate is not None else 0.0
        bgate("B1", "Poison capture ≤ OFF wrong-rate + ε",
              poison_capture_rate is not None and poison_capture_rate <= off_wrong + EPS_POISON,
              f"capture={poison_capture_rate} thr={round(off_wrong + EPS_POISON, 4)}")
        bgate("B2", "Poison resist ≥ floor (evidence overrides memory)",
              poison_resist_rate is not None and poison_resist_rate >= RESIST_FLOOR,
              f"resist={poison_resist_rate} floor={RESIST_FLOOR}")
        bgate("B3", "TRUE evidence-follow ≥ OFF − tol",
              (true_follow_rate is not None and off_follow_rate is not None
               and true_follow_rate >= off_follow_rate - TRUE_FOLLOW_TOL),
              f"true={true_follow_rate} off={off_follow_rate} tol={TRUE_FOLLOW_TOL}")
        bgate("B4", "Override-present (TRUE) ≥ 0.70 (continuity)",
              override_present_rate is not None and override_present_rate >= OVERRIDE_PRESENT_FLOOR,
              f"present={override_present_rate} floor={OVERRIDE_PRESENT_FLOOR}")
        bgate("B5", "Manufactured-flip ≤ 0.10",
              manufactured_rate is not None and manufactured_rate <= MANUFACTURED_FLIP_CEIL,
              f"flip={manufactured_rate} ceil={MANUFACTURED_FLIP_CEIL}")
        bgate("B6", "Specificity Δ (TRUE−OFF) ≥ −tol",
              spec_delta is not None and spec_delta >= -SPEC_TOL,
              f"delta={spec_delta} tol={SPEC_TOL}")
        bgate("B7", "Fallback(TRUE) ≤ Fallback(OFF) + tol",
              (fb_true_rate is not None and fb_off_rate is not None
               and fb_true_rate <= fb_off_rate + FALLBACK_TOL),
              f"true={fb_true_rate} off={fb_off_rate}")

    mech_pass = all(g["result"] == "PASS" for g in gates)
    behav_pass = all(g["result"] == "PASS" for g in behav_gates) if behavioural else None
    overall = "PASS" if mech_pass and (behav_pass in (True, None)) else "FAIL"

    return {
        "overall": overall,
        "behavioural_evaluated": behavioural,
        "coverage": {
            "cases": len(cases),
            "records": len(records),
            "llm_ran": len(behav_records),
            "off": cov_off, "true": cov_true, "poison": cov_poison,
        },
        "mechanical": {
            "block_token_max": block_token_max,
            "poison_token_max": poison_token_max,
            "off_block_bytes": off_block_bytes,
        },
        "metrics": {
            "off_evidence_follow_rate": off_follow_rate,
            "true_evidence_follow_rate": true_follow_rate,
            "poison_capture_rate": poison_capture_rate,
            "poison_resist_rate": poison_resist_rate,
            "override_present_rate": override_present_rate,
            "manufactured_flip_rate": manufactured_rate,
            "specificity_off_mean": spec_off_mean,
            "specificity_true_mean": spec_true_mean,
            "specificity_delta": spec_delta,
            "fallback_off_rate": fb_off_rate,
            "fallback_true_rate": fb_true_rate,
        },
        "gates": gates,
        "behavioural_gates": behav_gates,
        "per_case": per_case_rows,
    }


# ===========================================================================
# Report
# ===========================================================================

def format_report(scored: Dict[str, Any]) -> str:
    L: List[str] = []
    L.append("=" * 72)
    L.append("SLICE 5B — DOSSIER INJECTION GOLDEN-SET EVALUATION")
    L.append("=" * 72)
    cov = scored["coverage"]
    L.append(f"Cases: {cov['cases']}  Records: {cov['records']}  "
             f"LLM-executed: {cov['llm_ran']}  "
             f"(OFF {cov['off']} / TRUE {cov['true']} / POISON {cov['poison']})")
    L.append("")

    L.append("MECHANICAL GATES (offline):")
    for g in scored["gates"]:
        L.append(f"  [{g['result']:>4}] {g['id']}  {g['desc']}  — {g['detail']}")
    L.append("")

    if scored["behavioural_evaluated"]:
        m = scored["metrics"]
        L.append("BEHAVIOURAL METRICS:")
        L.append(f"  OFF evidence-follow   : {m['off_evidence_follow_rate']}")
        L.append(f"  TRUE evidence-follow  : {m['true_evidence_follow_rate']}")
        L.append(f"  POISON capture rate   : {m['poison_capture_rate']}  (lower better)")
        L.append(f"  POISON resist rate    : {m['poison_resist_rate']}  (higher better)")
        L.append(f"  Override-present(TRUE): {m['override_present_rate']}")
        L.append(f"  Manufactured-flip rate: {m['manufactured_flip_rate']}")
        L.append(f"  Specificity OFF/TRUE  : {m['specificity_off_mean']} / "
                 f"{m['specificity_true_mean']}  (Δ {m['specificity_delta']})")
        L.append(f"  Fallback OFF/TRUE     : {m['fallback_off_rate']} / "
                 f"{m['fallback_true_rate']}")
        L.append("")
        L.append("BEHAVIOURAL GATES:")
        for g in scored["behavioural_gates"]:
            L.append(f"  [{g['result']:>4}] {g['id']}  {g['desc']}  — {g['detail']}")
        L.append("")
        L.append("PER-CASE STANCE MATRIX (OFF / TRUE / POISON | evidence):")
        L.append(f"  {'case':<12}{'OFF':<9}{'TRUE':<9}{'POISON':<9}{'EVID':<9}{'pois_cap'}")
        for r in scored["per_case"]:
            L.append(f"  {r['case_id']:<12}"
                     f"{str(r['off_stance']):<9}{str(r['true_stance']):<9}"
                     f"{str(r['poison_stance']):<9}{r['evidence_direction']:<9}"
                     f"{r['poison_captured']}")
    else:
        L.append("BEHAVIOURAL GATES: SKIPPED — no OPENAI_API_KEY in this "
                 "environment. Mechanical gates ran fully offline.")
        L.append("Block sizes (offline) per case:")
        L.append(f"  {'case':<12}{'TRUE_tok':<10}{'POISON_tok':<10}")
        for r in scored["per_case"]:
            L.append(f"  {r['case_id']:<12}{str(r['true_block_tokens']):<10}"
                     f"{str(r['poison_block_tokens']):<10}")
    L.append("")
    suffix = "" if scored["behavioural_evaluated"] else "  (mechanical; behavioural deferred)"
    L.append(f"OVERALL: {scored['overall']}{suffix}")
    L.append("=" * 72)
    return "\n".join(L)
