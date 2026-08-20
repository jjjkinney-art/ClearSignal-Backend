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


def _available_threshold_metrics(thesis: Dict[str, Any]) -> Set[str]:
    """Normalized metric names for thresholds that are actually usable.

    Sprint 3B.1B: every live candidate failure so far has been a threshold
    failure, so availability is tracked per-metric rather than only in
    aggregate. A metric that is present but unavailable is not an available
    metric, however it is spelled.
    """
    return {normalize_metric(str(t.get("metric", "")))
            for t in thesis.get("decision_thresholds") or []
            if isinstance(t, dict) and t.get("metric") and not t.get("unavailable")}


def _threshold_anchors(thesis: Dict[str, Any]) -> Dict[str, Tuple[Any, Any]]:
    """Bull/bear numeric boundaries per available metric.

    compact_a2 shipped thresholds that kept their metric name and availability
    but lost their numeric boundaries. Comparing anchors catches that class
    directly instead of inferring it from prose.
    """
    out: Dict[str, Tuple[Any, Any]] = {}
    for t in thesis.get("decision_thresholds") or []:
        if not isinstance(t, dict) or t.get("unavailable") or not t.get("metric"):
            continue
        out[normalize_metric(str(t["metric"]))] = (
            t.get("bull_boundary"), t.get("bear_boundary"),
        )
    return out


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


# ── Sprint 3B.3: risk-specific comparison ────────────────────────────────────
# The thesis comparator above already catches lost figures, lost thresholds and
# integrity regressions. A risk-agent experiment adds three failure modes that
# are specific to risk prose and that a thesis-level diff would score as merely
# "shorter": the risk stops naming the company, it stops naming a transmission
# mechanism, or it degenerates into sector boilerplate.
#
# These checks are ADDITIVE and only contribute when the candidate actually
# declares a non-control risk variant, so every existing synthesis A/B verdict
# is bit-for-bit unchanged.

# Phrases the risk prompt itself forbids as generic. Reused here so the
# comparator and the production prompt cannot drift apart.
_GENERIC_RISK_PHRASES = (
    "higher rates hurt growth stocks",
    "the company faces headwinds",
    "like many tech companies",
    "as a growth stock",
    "macroeconomic uncertainty",
    "market volatility",
    "increased competition",
    "regulatory scrutiny",
    "general economic conditions",
)

# Causal connectives. A downside risk that states no mechanism is an assertion,
# not analysis — this is the "missing downside mechanism" reject condition.
# Verified against saved artifacts: `key_risks` entries are terse labels
# ("MSFT-specific: Decline in Azure growth rate") and carry no connective, so
# counting mechanisms over entries alone is inert — it reads 0 on nearly every
# real thesis and could never detect a regression. The mechanism actually lives
# in bear_thesis ("a slowdown in Azure's growth below 25% WOULD COMPRESS the
# valuation multiple"), so that is what is measured.
#
# "as" and "if" are deliberately excluded: as bare substrings they match inside
# ordinary prose constantly and would report a mechanism that is not there.
_MECHANISM_MARKERS = (
    "because", "driven by", "leads to", "leading to", "results in",
    "resulting in", "due to", "causes", "causing", "would reduce",
    "would compress", "compresses", "compressing", "erodes", "eroding",
    "pressures", "pressuring", "impacting", "reducing", "translating",
    "flows through", "exposes", "transmits", "triggers",
)

# The fields mechanism language is measured over.
_MECHANISM_FIELDS = ("bear_thesis", "conclusion", "direct_answer")


# The synthesised thesis emits `key_risks` (and `top_risks` for ranked ones).
# It does NOT emit a field called `risks` — see the note on _risks() below.
# Every field is read defensively so a schema addition cannot silently blind
# this layer the way it blinded _risks().
_RISK_LIST_FIELDS = ("key_risks", "top_risks", "risks")


def _risk_entries(thesis: Dict[str, Any]) -> List[str]:
    """Every risk statement in a thesis, as flat strings."""
    out: List[str] = []
    for field_name in _RISK_LIST_FIELDS:
        for r in thesis.get(field_name) or []:
            if isinstance(r, dict):
                text = r.get("risk") or r.get("signal") or r.get("text") or ""
                if not text:
                    text = " ".join(str(v) for v in r.values() if isinstance(v, str))
            else:
                text = r
            if isinstance(text, str) and text.strip():
                out.append(text.strip())
    return out


def _risk_text(thesis: Dict[str, Any]) -> str:
    """All risk-bearing prose in a thesis, lowercased."""
    parts: List[str] = list(_risk_entries(thesis))
    for f in ("bear_thesis", "conclusion"):
        v = thesis.get(f)
        if isinstance(v, str):
            parts.append(v)
    return " ".join(parts).lower()


def _company_mentions(text: str, ticker: str) -> int:
    if not ticker:
        return 0
    return len(re.findall(rf"\b{re.escape(ticker.lower())}\b", text))


def _mechanism_count(thesis: Dict[str, Any]) -> int:
    """How many DISTINCT causal mechanisms the downside case states.

    Counted over risk entries plus the mechanism-bearing prose fields, since
    the terse `key_risks` labels carry none. Distinct markers rather than total
    occurrences, so restating one mechanism does not inflate the score.
    """
    parts = [t.lower() for t in _risk_entries(thesis)]
    for f in _MECHANISM_FIELDS:
        v = thesis.get(f)
        if isinstance(v, str):
            parts.append(v.lower())
    blob = " ".join(parts)
    return len({m for m in _MECHANISM_MARKERS if m in blob})


def _generic_hits(thesis: Dict[str, Any], ticker: str = "") -> List[str]:
    """Generic boilerplate phrases appearing in an UNQUALIFIED risk entry.

    Sprint 3B.1A's lesson was that a comparator false positive costs a whole
    cycle, so a phrase only counts when the entry carrying it is bare: no
    company reference and no figure. "Increased competition in AI inference
    market" for NVDA is specific and must not be flagged; a naked "Increased
    competition" is exactly the degradation this gate exists to catch.
    """
    tick = (ticker or "").lower()
    hits: Set[str] = set()
    for entry in _risk_entries(thesis):
        low = entry.lower()
        qualified = bool(re.search(r"\d", low)) or (tick and tick in low)
        if qualified:
            continue
        for p in _GENERIC_RISK_PHRASES:
            if p in low:
                hits.add(p)
    return sorted(hits)


# ── Sprint 3B.3.1: risk-agent timeout/failure guard ──────────────────────────
# m2-control-NVDA hit the 16s agent wall cap (see `_AGENT_WALL_CAP_S` in
# app/services/router_service.py). Production recorded a distinct
# `agent.risk` stage entry with status="timeout" and substituted
# RiskProfile(overall="Risk analysis unavailable.") for synthesis — the thread
# is abandoned, not killed, so a second "ok" stage entry can appear later for
# the same request once the late result arrives, but production already
# committed to the fallback by then. Comparing that pair as ordinary risk
# content would score an availability failure as a quality regression (or,
# just as wrong, let a fallback-flattened candidate pass as "keep").
#
# Detection reads the actual recorded status. It deliberately does NOT infer
# failure from duration — a call that is merely slow but genuinely completed
# is not a failure, and inferring from timing would eventually flag a normal
# slow response.
_RISK_FAILURE_STATUSES = frozenset({"timeout", "error"})
_RISK_STATUS_VERB = {"timeout": "timed out", "error": "errored"}


def risk_execution_status(raw: Any) -> str:
    """Production execution status of the risk agent for one response.

    Returns "ok" when a successful `agent.risk` stage is recorded, a failure
    status ("timeout" | "error") when one is recorded, or "unknown" when the
    response carries no observability stages at all — older artifacts and
    synthetic test fixtures fall here and are treated as usable, since there
    is no production signal available to say otherwise.
    """
    if not isinstance(raw, dict):
        return "unknown"
    obs = raw.get("_observability")
    if not isinstance(obs, dict):
        return "unknown"
    stages = obs.get("stages")
    if not isinstance(stages, list):
        return "unknown"
    risk_stages = [s for s in stages
                   if isinstance(s, dict) and s.get("stage") == "agent.risk"]
    if not risk_stages:
        return "unknown"
    for s in risk_stages:
        status = s.get("status")
        if status in _RISK_FAILURE_STATUSES:
            return status
    return "ok"


def risk_parse_ok(raw: Any) -> Optional[bool]:
    """Whether a structured-risk variant parsed and projected successfully.

    Sprint 3B.4 — ``risk_struct_a`` asks the model for a structured object and
    projects it back into RiskProfile. A parse/projection failure degrades the
    response exactly as an LLM error does, so comparing it as ordinary content
    would score an execution failure as a quality regression, the same trap the
    3B.3.1 timeout guard closes.

    Returns ``None`` when the response carries no parse flag at all — control
    runs and every artifact predating this sprint — which is not a failure.
    """
    if not isinstance(raw, dict):
        return None
    obs = raw.get("_observability")
    if not isinstance(obs, dict):
        return None
    meta = obs.get("agent_meta")
    if not isinstance(meta, dict) or "risk_parse_ok" not in meta:
        return None
    return bool(meta.get("risk_parse_ok"))


def risk_ab_validity(control: Dict[str, Any], candidate: Dict[str, Any]) -> List[str]:
    """Reasons this pair cannot be scored as a normal quality comparison.

    Empty when both sides executed successfully (or the artifact predates
    observability, per `risk_execution_status`).
    """
    reasons: List[str] = []
    status_c = risk_execution_status(control)
    status_k = risk_execution_status(candidate)
    if status_c in _RISK_FAILURE_STATUSES:
        reasons.append(f"risk comparison invalid: control risk agent "
                       f"{_RISK_STATUS_VERB[status_c]}")
    if status_k in _RISK_FAILURE_STATUSES:
        reasons.append(f"risk comparison invalid: candidate risk agent "
                       f"{_RISK_STATUS_VERB[status_k]}")
    # Sprint 3B.4 — a structured variant that failed to parse/project served a
    # degraded profile, so its content is not the candidate's real output.
    if risk_parse_ok(control) is False:
        reasons.append("risk comparison invalid: control structured risk "
                       "output failed to parse")
    if risk_parse_ok(candidate) is False:
        reasons.append("risk comparison invalid: candidate structured risk "
                       "output failed to parse")
    return reasons


def compare_risk(control: Dict[str, Any], candidate: Dict[str, Any],
                 ticker: str = "") -> Dict[str, Any]:
    """Risk-specific metrics for one control/candidate pair."""
    c_t, k_t = _thesis(control), _thesis(candidate)
    c_txt, k_txt = _risk_text(c_t), _risk_text(k_t)

    c_generic = _generic_hits(c_t, ticker)
    k_generic = _generic_hits(k_t, ticker)
    c_mech, k_mech = _mechanism_count(c_t), _mechanism_count(k_t)
    c_named = _company_mentions(c_txt, ticker)
    k_named = _company_mentions(k_txt, ticker)

    return {
        "risk_variant_candidate": (candidate.get("_observability") or {}).get(
            "risk_variant") if isinstance(candidate, dict) else None,
        "risk_variant_control": (control.get("_observability") or {}).get(
            "risk_variant") if isinstance(control, dict) else None,
        # Sprint 3B.3.1 — execution status and validity, checked BEFORE any
        # content metric below is trusted. A timed-out/errored side means
        # every content metric here reflects the "Risk analysis unavailable."
        # fallback, not genuine model output.
        "risk_status_control": risk_execution_status(control),
        "risk_status_candidate": risk_execution_status(candidate),
        "risk_parse_ok_control": risk_parse_ok(control),
        "risk_parse_ok_candidate": risk_parse_ok(candidate),
        "risk_invalidity_reasons": risk_ab_validity(control, candidate),
        "risk_entries_control": len(_risk_entries(c_t)),
        "risk_entries_candidate": len(_risk_entries(k_t)),
        "risk_mechanisms_control": c_mech,
        "risk_mechanisms_candidate": k_mech,
        "risk_company_mentions_control": c_named,
        "risk_company_mentions_candidate": k_named,
        "risk_generic_phrases_control": c_generic,
        "risk_generic_phrases_candidate": k_generic,
        "risk_generic_introduced": sorted(set(k_generic) - set(c_generic)),
        "risk_prose_chars_control": len(c_txt),
        "risk_prose_chars_candidate": len(k_txt),
        "risk_prose_ratio": round(len(k_txt) / len(c_txt), 3) if c_txt else None,
    }


def risk_reasons(risk_cmp: Dict[str, Any]) -> List[str]:
    """Reject reasons from the risk-specific layer.

    Only fires for a genuine risk A/B pair — a run with no risk variant, or a
    control-vs-control pair, contributes nothing.
    """
    variant = risk_cmp.get("risk_variant_candidate")
    if not variant or variant == "risk_control":
        return []

    out: List[str] = []
    if risk_cmp["risk_entries_candidate"] < risk_cmp["risk_entries_control"]:
        out.append(
            f"risk entries fell {risk_cmp['risk_entries_control']} -> "
            f"{risk_cmp['risk_entries_candidate']}"
        )
    if risk_cmp["risk_mechanisms_candidate"] < risk_cmp["risk_mechanisms_control"]:
        out.append(
            f"risk downside mechanisms fell "
            f"{risk_cmp['risk_mechanisms_control']} -> "
            f"{risk_cmp['risk_mechanisms_candidate']}"
        )
    if risk_cmp["risk_generic_introduced"]:
        out.append(f"generic risk phrasing introduced: {risk_cmp['risk_generic_introduced']}")
    # Company-specificity is the mandate the risk prompt states explicitly.
    # Losing it entirely is a reject; a partial drop is caught by the ratio.
    if risk_cmp["risk_company_mentions_control"] > 0 and \
            risk_cmp["risk_company_mentions_candidate"] == 0:
        out.append("risk prose no longer names the company")
    ratio = risk_cmp.get("risk_prose_ratio")
    if ratio is not None and ratio < 0.50:
        out.append(f"risk prose shrank to {ratio} of control")
    return out


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

    # Sprint 3B.1B — per-metric threshold quality. Availability, metric-set
    # overlap and numeric anchors are compared separately, because every live
    # candidate failure so far has been one of these three and an aggregate
    # count alone hid which.
    c_avail_m, k_avail_m = _available_threshold_metrics(c_t), _available_threshold_metrics(k_t)
    c_anchor, k_anchor = _threshold_anchors(c_t), _threshold_anchors(k_t)
    became_unavailable = sorted(c_avail_m - k_avail_m)
    substituted = sorted(k_avail_m - c_avail_m)
    anchors_lost = sorted(
        m for m in (c_avail_m & k_avail_m)
        if c_anchor.get(m, (None, None)) != (None, None)
        and k_anchor.get(m, (None, None)) == (None, None)
    )

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
        "available_metrics_control": len(c_avail_m),
        "available_metrics_candidate": len(k_avail_m),
        "metrics_became_unavailable": became_unavailable,
        "metrics_substituted": substituted,
        "threshold_anchors_lost": anchors_lost,
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
        # Sprint 3B.3 — risk layer. Present always so the artifact is uniform;
        # it only influences the verdict for a genuine risk A/B pair.
        "risk": compare_risk(control, candidate,
                             ticker=str(control.get("company") or "")),
    }


def verdict(comparison: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Keep/reject/review/invalid for one pair, with the driving reasons.

    Sprint 3B.3.1 — checked BEFORE every other rule, and short-circuits: if
    the risk agent timed out or errored on either side, the WHOLE pair is not
    a normal quality comparison. A fallback "Risk analysis unavailable." can
    itself trigger the ordinary reject checks below (missing risk content,
    flattened prose) — that would misreport an availability failure as the
    candidate having degraded content, which is exactly the false signal this
    guard exists to prevent. This does not loosen any existing reject
    condition; it only means those conditions do not run for a pair that
    cannot be judged in the first place.
    """
    risk_invalid = (comparison.get("risk") or {}).get("risk_invalidity_reasons") or []
    if risk_invalid:
        return "invalid", risk_invalid

    reasons: List[str] = []
    if not comparison["structural_ok"]:
        reasons.append(f"missing required fields: {comparison['missing_fields']}")
    if comparison["threshold_metrics_lost"]:
        reasons.append(f"threshold metrics lost: {comparison['threshold_metrics_lost']}")
    # Sprint 3B.1B — the three threshold failure modes seen live, each a reject.
    if comparison["available_metrics_candidate"] < comparison["available_metrics_control"]:
        reasons.append(
            f"available thresholds fell "
            f"{comparison['available_metrics_control']} -> "
            f"{comparison['available_metrics_candidate']}"
        )
    if comparison["metrics_became_unavailable"]:
        reasons.append(
            f"metrics no longer available: {comparison['metrics_became_unavailable']}"
        )
    if comparison["metrics_substituted"] and comparison["metrics_became_unavailable"]:
        reasons.append(f"substituted metrics: {comparison['metrics_substituted']}")
    if comparison["threshold_anchors_lost"]:
        reasons.append(
            f"threshold numeric anchors lost: {comparison['threshold_anchors_lost']}"
        )
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
    # Sprint 3B.3 — risk-specific rejects, additive to every check above.
    reasons.extend(risk_reasons(comparison.get("risk") or {}))
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
    # Sprint 3B.3.1 — "invalid" added for a risk-agent timeout/failure pair.
    tally = {"keep": 0, "review": 0, "reject": 0, "invalid": 0}
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
        f"- keep: **{t['keep']}** · review: **{t['review']}** · "
        f"reject: **{t['reject']}** · invalid: **{t.get('invalid', 0)}**",
        "",
    ]
    if t["reject"]:
        lines.append("> **A reject means the candidate prompt must not ship.**")
        lines.append("")
    if t.get("invalid"):
        # Sprint 3B.3.1 — surfaces execution failure, never prompt text or
        # secrets: risk_status is one of "ok" / "timeout" / "error" / "unknown".
        lines.append(
            "> **An invalid pair could not be judged** — the risk agent timed "
            "out or errored on at least one side. Rerun that ticker/category "
            "before using it in any decision. Never compare a successful "
            "response against a timed-out one."
        )
        lines.append("")

    lines += ["## Per-query verdicts", "",
              "| query | verdict | risk status (ctl/cand) | prose ratio | conf | reasons |",
              "|---|---|---|---|---|---|"]
    for p in result["pairs"]:
        conf = "same" if not p["confidence_changed"] else \
            f"{p['confidence_control']}→{p['confidence_candidate']}"
        risk = p.get("risk") or {}
        risk_status = (f"{risk.get('risk_status_control', 'unknown')}/"
                      f"{risk.get('risk_status_candidate', 'unknown')}")
        # Sprint 3B.4 — surface a structured-parse failure alongside the
        # execution status; both invalidate a pair for the same reason.
        if risk.get("risk_parse_ok_candidate") is False:
            risk_status += " parse-fail"
        lines.append(
            f"| `{p['id']}` | {p['verdict']} | {risk_status} | {p['prose_ratio']} | "
            f"{conf} | {'; '.join(p['reasons'])[:120]} |"
        )
    return "\n".join(lines) + "\n"
