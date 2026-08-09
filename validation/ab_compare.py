"""A/B quality comparison between two benchmark runs (Sprint 3B.1).

Compares a control run against a candidate-prompt run so a prompt reduction is
kept or rejected on evidence rather than on token savings alone.

Three layers, deliberately separate:

* **Structural** — did any required field disappear? A prompt reduction that
  drops a field is an immediate reject regardless of latency.
* **Correctness** — did validation findings change? New findings are a reject;
  fewer findings are worth investigating, not celebrating.
* **Semantic** — did the analysis flatten? Character similarity is explicitly
  NOT the test: two theses can share little text and mean the same thing, and
  a generic summary can score highly against a specific one. Instead this
  compares the things that carry meaning — figures cited, risks named,
  thresholds set, confidence and stance — because those are what a reader acts
  on.

Everything here reads saved artifacts. It never issues a request.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Fields whose absence is a hard structural failure.
REQUIRED_FIELDS = (
    "direct_answer", "bull_thesis", "bear_thesis", "valuation_view",
    "conclusion", "confidence", "risks", "catalysts",
    "decision_thresholds", "quantitative_claims", "_integrity",
)

_NUM_RE = re.compile(r"~?\$?\d[\d,]*\.?\d*\s?(?:%|x|bps?|B|M|K)?")
_PROSE_FIELDS = ("direct_answer", "bull_thesis", "bear_thesis",
                 "valuation_view", "macro_sensitivity", "conclusion")


def _thesis(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    answer = raw.get("answer")
    if isinstance(answer, dict) and isinstance(answer.get("investment_thesis"), dict):
        return answer["investment_thesis"]
    return raw if "direct_answer" in raw else {}


def _text_of(thesis: Dict[str, Any]) -> str:
    parts = []
    for f in _PROSE_FIELDS:
        v = thesis.get(f)
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(str(x) for x in v)
    return "\n".join(parts)


def _figures(thesis: Dict[str, Any]) -> Set[str]:
    """Every figure the thesis cites, normalized. Losing one means a concrete
    number stopped being reported."""
    return {m.group(0).strip().lower().replace(" ", "")
            for m in _NUM_RE.finditer(_text_of(thesis)) if m.group(0).strip()}


def _risks(thesis: Dict[str, Any]) -> Set[str]:
    out = set()
    for r in thesis.get("risks") or []:
        text = r.get("risk") if isinstance(r, dict) else r
        if isinstance(text, str) and text.strip():
            out.add(text.strip().lower()[:60])
    return out


def _threshold_metrics(thesis: Dict[str, Any]) -> Set[str]:
    return {str(t.get("metric", "")).strip().lower()
            for t in thesis.get("decision_thresholds") or []
            if isinstance(t, dict) and t.get("metric")}


def compare_thesis(control: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Compare one control/candidate thesis pair."""
    c_t, k_t = _thesis(control), _thesis(candidate)

    missing = [f for f in REQUIRED_FIELDS
               if f in c_t and not k_t.get(f) and c_t.get(f)]

    c_fig, k_fig = _figures(c_t), _figures(k_t)
    c_risk, k_risk = _risks(c_t), _risks(k_t)
    c_thr, k_thr = _threshold_metrics(c_t), _threshold_metrics(k_t)

    c_len, k_len = len(_text_of(c_t)), len(_text_of(k_t))
    # A large unexplained shrink is the signature of flattening into a generic
    # summary — the failure mode a token-savings metric would never catch.
    flattening = bool(c_len and (k_len / c_len) < 0.70)

    c_int = c_t.get("_integrity") or {}
    k_int = k_t.get("_integrity") or {}

    return {
        "structural_ok": not missing,
        "missing_fields": missing,
        "figures_lost": sorted(c_fig - k_fig)[:10],
        "figures_gained": sorted(k_fig - c_fig)[:10],
        "risks_lost": sorted(c_risk - k_risk)[:5],
        "threshold_metrics_lost": sorted(c_thr - k_thr),
        "prose_chars_control": c_len,
        "prose_chars_candidate": k_len,
        "prose_ratio": round(k_len / c_len, 3) if c_len else None,
        "flattening_suspected": flattening,
        "confidence_control": c_t.get("confidence"),
        "confidence_candidate": k_t.get("confidence"),
        "confidence_changed": c_t.get("confidence") != k_t.get("confidence"),
        "integrity_status_control": c_int.get("status"),
        "integrity_status_candidate": k_int.get("status"),
        "integrity_ok_control": c_int.get("ok"),
        "integrity_ok_candidate": k_int.get("ok"),
        "variant_candidate": (candidate.get("_observability") or {}).get(
            "synthesis_variant") if isinstance(candidate, dict) else None,
    }


def verdict(comparison: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Keep/reject/review for one pair, with the reasons that drove it."""
    reasons: List[str] = []
    if not comparison["structural_ok"]:
        reasons.append(f"missing required fields: {comparison['missing_fields']}")
    if comparison["threshold_metrics_lost"]:
        reasons.append(f"threshold metrics lost: {comparison['threshold_metrics_lost']}")
    if comparison["flattening_suspected"]:
        reasons.append(f"prose shrank to {comparison['prose_ratio']} of control")
    if comparison["integrity_ok_candidate"] is False and \
            comparison["integrity_ok_control"] is not False:
        reasons.append("integrity ok regressed to false")
    if reasons:
        return "reject", reasons

    soft: List[str] = []
    if comparison["figures_lost"]:
        soft.append(f"figures no longer cited: {comparison['figures_lost']}")
    if comparison["risks_lost"]:
        soft.append(f"risks no longer named: {comparison['risks_lost']}")
    if comparison["confidence_changed"]:
        soft.append(
            f"confidence {comparison['confidence_control']} -> "
            f"{comparison['confidence_candidate']}"
        )
    if soft:
        return "review", soft
    return "keep", ["structurally and semantically equivalent"]


def compare_runs(control_dir: Path, candidate_dir: Path) -> Dict[str, Any]:
    """Compare every fixture present in both runs' raw_responses/."""
    c_files = {p.stem: p for p in (control_dir / "raw_responses").glob("*.json")}
    k_files = {p.stem: p for p in (candidate_dir / "raw_responses").glob("*.json")}
    shared = sorted(set(c_files) & set(k_files))

    pairs = []
    tally = {"keep": 0, "review": 0, "reject": 0}
    for fid in shared:
        control = json.loads(c_files[fid].read_text())
        candidate = json.loads(k_files[fid].read_text())
        cmp_ = compare_thesis(control, candidate)
        v, reasons = verdict(cmp_)
        tally[v] += 1
        pairs.append({"id": fid, "verdict": v, "reasons": reasons, **cmp_})

    return {
        "control_dir": str(control_dir), "candidate_dir": str(candidate_dir),
        "compared": len(shared), "only_in_control": sorted(set(c_files) - set(k_files)),
        "only_in_candidate": sorted(set(k_files) - set(c_files)),
        "tally": tally, "pairs": pairs,
    }


def ab_report_md(result: Dict[str, Any]) -> str:
    """Human-readable A/B diff artifact."""
    t = result["tally"]
    lines = [
        "# Synthesis Prompt A/B Comparison", "",
        f"- Control:   `{result['control_dir']}`",
        f"- Candidate: `{result['candidate_dir']}`",
        f"- Queries compared: **{result['compared']}**", "",
        f"- keep: **{t['keep']}** · review: **{t['review']}** · reject: **{t['reject']}**",
        "",
    ]
    if t["reject"]:
        lines.append("> **A reject means the candidate prompt must not ship.**")
        lines.append("")

    lines += ["## Per-query verdicts", "",
              "| query | verdict | prose ratio | conf | reasons |",
              "|---|---|---|---|---|"]
    for p in result["pairs"]:
        conf = "same" if not p["confidence_changed"] else \
            f"{p['confidence_control']}→{p['confidence_candidate']}"
        lines.append(
            f"| `{p['id']}` | {p['verdict']} | {p['prose_ratio']} | {conf} | "
            f"{'; '.join(p['reasons'])[:120]} |"
        )
    return "\n".join(lines) + "\n"
