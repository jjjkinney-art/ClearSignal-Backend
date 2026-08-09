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

# Sprint 3B.1A — the original pattern split a range into halves: "~25-30x"
# tokenised as "~25" + "30x", so a candidate rewording one range produced two
# phantom "lost figures". NVDA's five reported losses were really two ranges
# and one figure. A range is one quantity and is matched as one.
_NUM_RE = re.compile(
    r"~?\$?\d[\d,]*\.?\d*"                       # leading number
    r"(?:\s?[-–]\s?\$?\d[\d,]*\.?\d*)?"          # optional range partner
    r"\s?(?:%|x|bps?|B|M|K)?"                    # optional unit
)

# Sprint 3B.1A — a number inside a product name is not a figure. MSFT's
# reported loss of "365" came from "Microsoft 365", which Sprint 2B already
# established is an identifier, not a quantitative claim. The backend's own
# identifier table is reused so the two never drift apart.
try:  # pragma: no cover - exercised indirectly
    from app.integrity.identifiers import identifier_label_at, identifier_spans
except Exception:  # pragma: no cover - harness must not hard-depend on app/
    identifier_spans = None  # type: ignore[assignment]
    identifier_label_at = None  # type: ignore[assignment]
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
    number stopped being reported.

    Numbers belonging to a product/model/index identifier are excluded — they
    are names, not measurements, so their disappearance says nothing about
    analytical specificity.
    """
    text = _text_of(thesis)
    spans = identifier_spans(text) if identifier_spans else []
    out: Set[str] = set()
    for m in _NUM_RE.finditer(text):
        token = m.group(0).strip()
        if not token:
            continue
        if spans and identifier_label_at(spans, m.start(), m.end()):
            continue
        out.add(token.lower().replace(" ", "").rstrip(".,;:"))
    return out


def _risks(thesis: Dict[str, Any]) -> Set[str]:
    out = set()
    for r in thesis.get("risks") or []:
        text = r.get("risk") if isinstance(r, dict) else r
        if isinstance(text, str) and text.strip():
            out.add(text.strip().lower()[:60])
    return out


# Sprint 3B.1A — noise words that do not change which metric is meant.
# "EUV System Shipments" and "EUV System Shipments per Quarter" are the same
# metric at a different cadence; "Credit Card Net Charge-Off Rate" and "Net
# Charge-Off Rate" are the same measure. Stripping these avoids reporting a
# rename as a loss. Words that would change the METRIC (income vs margin,
# return vs multiple) are deliberately NOT stripped.
_METRIC_NOISE = re.compile(
    r"\b(?:per\s+(?:quarter|month|year|annum)|quarterly|monthly|annual|yearly|"
    r"total|overall|percentage|pct|ratio|rate\s+of|credit\s+card|blended|"
    r"consolidated|company|reported)\b",
    re.IGNORECASE,
)
# Abbreviations the model uses interchangeably with their expansion.
_METRIC_ALIASES = (
    (re.compile(r"\bnet\s+interest\s+margin\b|\bnim\b", re.I), "nim"),
    (re.compile(r"\breturn\s+on\s+tangible\s+common\s+equity\b|\brotce\b", re.I), "rotce"),
    (re.compile(r"\bfree\s+cash\s+flow\b|\bfcf\b", re.I), "fcf"),
    (re.compile(r"\bearnings\s+per\s+share\b|\beps\b", re.I), "eps"),
    (re.compile(r"\bforward\s+p/?e\b|\bp/?e\s+ratio\b|\bp/?e\b", re.I), "pe"),
)


def normalize_metric(metric: str) -> str:
    """Canonical form of a threshold metric name for equivalence comparison.

    Only cosmetic and cadence wording is removed. Two metrics that measure
    different things — net interest *income* versus net interest *margin* —
    normalize differently and are still reported as a substitution.
    """
    text = (metric or "").lower()
    text = re.sub(r"\(([^)]*)\)", r" \1 ", text)   # unwrap "(NIM)" style suffixes
    for pattern, canon in _METRIC_ALIASES:
        text = pattern.sub(canon, text)
    text = _METRIC_NOISE.sub(" ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(sorted(set(text.split())))


def _threshold_metrics(thesis: Dict[str, Any]) -> Set[str]:
    return {normalize_metric(str(t.get("metric", "")))
            for t in thesis.get("decision_thresholds") or []
            if isinstance(t, dict) and t.get("metric")}


def _unavailable_thresholds(thesis: Dict[str, Any]) -> int:
    """Count thresholds shipped as unusable.

    Sprint 3B.1A found this to be the sharpest quality signal in the whole
    comparison: compact_a degraded 14/15 available thresholds to 12/15, and
    both REJECT verdicts had a metric that survived by NAME but arrived
    unavailable. A renamed-but-usable threshold is fine; a threshold that
    stopped being actionable is a regression whatever it is called.
    """
    return sum(1 for t in thesis.get("decision_thresholds") or []
               if isinstance(t, dict) and t.get("unavailable"))


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

    c_unavail, k_unavail = _unavailable_thresholds(c_t), _unavailable_thresholds(k_t)

    c_int = c_t.get("_integrity") or {}
    k_int = k_t.get("_integrity") or {}

    return {
        "structural_ok": not missing,
        "missing_fields": missing,
        "figures_lost": sorted(c_fig - k_fig)[:10],
        "figures_gained": sorted(k_fig - c_fig)[:10],
        "risks_lost": sorted(c_risk - k_risk)[:5],
        "threshold_metrics_lost": sorted(c_thr - k_thr),
        "threshold_metrics_gained": sorted(k_thr - c_thr),
        "thresholds_unavailable_control": c_unavail,
        "thresholds_unavailable_candidate": k_unavail,
        "thresholds_degraded": max(k_unavail - c_unavail, 0),
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
    if comparison["thresholds_degraded"]:
        reasons.append(
            f"{comparison['thresholds_degraded']} threshold(s) became unavailable "
            f"({comparison['thresholds_unavailable_control']} -> "
            f"{comparison['thresholds_unavailable_candidate']})"
        )
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
