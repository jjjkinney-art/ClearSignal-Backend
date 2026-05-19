"""
Thesis memory service — diff engine + signal change detection + alert rules.

Responsibilities
----------------
1. ``snapshot_from_thesis(thesis)`` — convert a live InvestmentThesis into a
   persisted ThesisSnapshot with deterministic fingerprint hashes.

2. ``compare_thesis_snapshots(previous, current)`` — produce a structured
   ThesisDiff capturing what moved, how severely, and which signals drove it.

3. ``detect_material_change(diff, ticker, prev, curr)`` — apply material
   change thresholds and return a MaterialChangeEvent when crossed.

4. ``evaluate_alert_rules(diff, rules)`` — pure-function evaluation of
   AlertRule objects against a ThesisDiff — no production infra required.

5. ``ALERT_RULE_EVALUATORS`` — registry of named condition functions for use
   by AlertRule.condition_key.

Design invariants
-----------------
* All functions are DETERMINISTIC: given the same inputs they return the same
  outputs.  No randomness, no I/O, no side effects except where explicitly
  noted.
* The diff engine does NOT call the language model.  All change detection is
  based on structured fields, signal hashes, and confidence deltas.
* Material change thresholds are defined as module-level constants so they can
  be adjusted without touching logic.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from ..schemas import (
    AlertRule,
    InvestmentThesis,
    MaterialChangeEvent,
    Signal,
    ThesisDiff,
    ThesisSnapshot,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Material change thresholds
# ---------------------------------------------------------------------------

# Confidence delta thresholds (absolute, 0-1 scale)
CONFIDENCE_COLLAPSE_THRESHOLD: float = 0.15   # ≥15pp drop → high severity
CONFIDENCE_MATERIAL_THRESHOLD: float = 0.08   # ≥8pp drop → medium severity
CONFIDENCE_MINOR_THRESHOLD: float = 0.04      # ≥4pp change → flagged but low

# Risk / signal change thresholds
NEW_STRUCTURAL_RISK_COUNT: int = 1    # ≥1 new risk = structural risk event
TOP_SIGNAL_REPLACED_WEIGHT: float = 0.05  # confidence contribution

# Trend flip definition: previous and current trends are polar opposites
_TREND_OPPOSITES: Dict[str, str] = {
    "strengthening": "weakening",
    "weakening":     "strengthening",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _signal_hash(signals: List[Signal]) -> str:
    """Deterministic SHA-256 fingerprint of a ranked signal list.

    Built from the first 80 characters of each signal's text, sorted so
    insertion order doesn't affect the hash.
    """
    parts: List[str] = []
    for s in signals:
        # Signal.signal is the canonical text field; fall back to label/description
        text = (
            getattr(s, "signal", "")
            or getattr(s, "label", "")
            or getattr(s, "description", "")
            or ""
        ).strip()
        parts.append(text[:80])
    parts_sorted = sorted(parts)
    payload = "|".join(parts_sorted)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _risk_hash(risks: List[Signal]) -> str:
    """Deterministic SHA-256 fingerprint of a ranked risk list."""
    return _signal_hash(risks)  # same algorithm, symmetric


def _signal_labels(signals: List[Signal]) -> List[str]:
    """Extract plain-text labels from a Signal list.

    Reads Signal.signal (canonical) falling back to label/description for
    compatibility with test stubs or legacy schemas.
    """
    out = []
    for s in signals:
        text = (
            getattr(s, "signal", "")
            or getattr(s, "label", "")
            or getattr(s, "description", "")
            or ""
        ).strip()
        if text:
            out.append(text)
    return out


def _set_diff_ci(old: List[str], new: List[str]) -> Tuple[List[str], List[str]]:
    """Case-insensitive set difference: returns (added, removed).

    Preserves original casing of items in *new* and *old*.
    """
    old_lower = {x.lower(): x for x in old}
    new_lower = {x.lower(): x for x in new}
    added   = [new_lower[k] for k in new_lower if k not in old_lower]
    removed = [old_lower[k] for k in old_lower if k not in new_lower]
    return added, removed


# ---------------------------------------------------------------------------
# Phase 1: snapshot_from_thesis
# ---------------------------------------------------------------------------

def snapshot_from_thesis(thesis: InvestmentThesis) -> ThesisSnapshot:
    """Convert a live InvestmentThesis into a persisted ThesisSnapshot.

    Computes deterministic signal_hash and risk_hash so downstream diffs
    can detect structural changes without full text comparison.  Timestamp
    is set to UTC-now when the thesis lacks a generated_at value.
    """
    ts = (thesis.generated_at or "").strip() or _now_iso()

    top_signals = list(thesis.top_signals or [])
    top_risks   = list(thesis.top_risks   or [])
    key_risks_text = list(thesis.key_risks or [])

    return ThesisSnapshot(
        ticker               = thesis.ticker.upper(),
        company_name         = thesis.company_name or "",
        timestamp            = ts,
        one_sentence_thesis  = thesis.one_sentence_thesis or "",
        direct_answer        = thesis.direct_answer or "",
        bull_thesis          = thesis.bull_thesis or "",
        bear_thesis          = thesis.bear_thesis or "",
        conclusion           = thesis.conclusion or "",
        top_signals          = top_signals,
        top_risks            = top_risks,
        key_drivers          = list(thesis.key_drivers or []),
        key_risks_text       = key_risks_text,
        confidence_score     = float(thesis.confidence_score or 0.0),
        confidence_reasoning = thesis.confidence_reasoning or "",
        thesis_trend         = thesis.thesis_trend or "unclear",
        change_drivers       = list(thesis.change_drivers or []),
        what_changed         = list(thesis.what_changed or []),
        signal_hash          = _signal_hash(top_signals),
        risk_hash            = _risk_hash(top_risks),
        dominant_dimension   = getattr(thesis, "dominant_dimension", "") or "",
        core_debate          = getattr(thesis, "core_debate", "") or "",
        core_market_debate   = getattr(thesis, "core_market_debate", "") or "",
    )


# ---------------------------------------------------------------------------
# Phase 3: compare_thesis_snapshots — ThesisDiff engine
# ---------------------------------------------------------------------------

def compare_thesis_snapshots(
    previous: ThesisSnapshot,
    current:  ThesisSnapshot,
) -> ThesisDiff:
    """Produce a structured ThesisDiff between two snapshots.

    Algorithm
    ---------
    1. Confidence delta → overall severity seed
    2. Signal fingerprint comparison → top_signal_replaced
    3. Risk set diff → new_risks, removed_risks
    4. Driver set diff → strengthening / weakening signals
    5. Trend direction → thesis_trend label + trend_flipped
    6. Severity aggregation → high/medium/low
    7. Material shift flag

    All comparisons are deterministic and based on structured fields only.
    """
    what_changed: List[str] = []
    change_drivers: List[str] = []

    # ── 1. Confidence delta ───────────────────────────────────────────────────
    conf_delta = float(current.confidence_score) - float(previous.confidence_score)
    if abs(conf_delta) >= CONFIDENCE_MINOR_THRESHOLD:
        direction  = "improved" if conf_delta > 0 else "weakened"
        severity_q = "materially " if abs(conf_delta) >= CONFIDENCE_MATERIAL_THRESHOLD else ""
        what_changed.append(
            f"Thesis conviction {severity_q}{direction} vs prior analysis"
        )
        change_drivers.append(
            f"Conviction {'improvement' if conf_delta > 0 else 'deterioration'}"
        )

    # ── 2. Top signal replaced ────────────────────────────────────────────────
    prev_top   = _signal_labels(previous.top_signals)
    curr_top   = _signal_labels(current.top_signals)
    top_signal_replaced = bool(
        prev_top and curr_top and prev_top[0].lower() != curr_top[0].lower()
    )
    if top_signal_replaced:
        what_changed.append(
            f"Primary signal shifted: '{prev_top[0]}' → '{curr_top[0]}'"
        )
        change_drivers.append(f"Top signal replaced: {curr_top[0]}")

    # ── 3. Risk set diff ──────────────────────────────────────────────────────
    prev_risk_labels = _signal_labels(previous.top_risks) + list(previous.key_risks_text)
    curr_risk_labels = _signal_labels(current.top_risks)  + list(current.key_risks_text)
    new_risks, removed_risks = _set_diff_ci(prev_risk_labels, curr_risk_labels)

    if new_risks:
        what_changed.append(f"New risk(s) surfaced: {', '.join(new_risks[:3])}")
        change_drivers.extend(new_risks[:3])
    if removed_risks:
        what_changed.append(f"Risk(s) resolved or de-ranked: {', '.join(removed_risks[:3])}")

    # ── 4. Signal set diff (strengthening / weakening) ───────────────────────
    prev_sig_labels = _signal_labels(previous.top_signals) + list(previous.key_drivers)
    curr_sig_labels = _signal_labels(current.top_signals)  + list(current.key_drivers)
    sig_added, sig_removed = _set_diff_ci(prev_sig_labels, curr_sig_labels)

    strengthening_signals = sig_added[:4]
    weakening_signals     = sig_removed[:4]

    if strengthening_signals:
        what_changed.append(
            f"Signals gained: {', '.join(strengthening_signals[:2])}"
        )
    if weakening_signals:
        what_changed.append(
            f"Signals weakened/removed: {', '.join(weakening_signals[:2])}"
        )

    # ── 5. Thesis trend + trend flip ─────────────────────────────────────────
    thesis_trend = _classify_thesis_trend(
        conf_delta         = conf_delta,
        new_risks_count    = len(new_risks),
        removed_risks_count= len(removed_risks),
        sig_added_count    = len(sig_added),
        sig_removed_count  = len(sig_removed),
        top_signal_replaced= top_signal_replaced,
        prev_trend         = previous.thesis_trend,
    )

    prev_opp   = _TREND_OPPOSITES.get(previous.thesis_trend, "")
    trend_flipped = bool(
        prev_opp and thesis_trend == prev_opp
    )
    if trend_flipped:
        what_changed.append(
            f"Thesis direction reversed: {previous.thesis_trend} → {thesis_trend}"
        )
        change_drivers.append("Trend reversal detected")

    # ── 6. Severity aggregation ───────────────────────────────────────────────
    severity = _compute_severity(
        conf_delta          = conf_delta,
        new_risks_count     = len(new_risks),
        top_signal_replaced = top_signal_replaced,
        trend_flipped       = trend_flipped,
    )

    # ── 7. Material shift flag ────────────────────────────────────────────────
    material_shift = severity in ("high", "medium")

    if not what_changed:
        what_changed.append("No significant changes detected since prior snapshot.")

    # ── 8. Core debate shift detection ────────────────────────────────────────
    # Compare core_debate text between snapshots using difflib ratio.
    # Ratio < 0.50 → the fulcrum variable changed materially (debate shifted).
    import difflib as _difflib
    prev_debate = (getattr(previous, "core_debate", "") or "").strip().lower()
    curr_debate = (getattr(current, "core_debate", "") or "").strip().lower()
    core_debate_shifted = False
    if prev_debate and curr_debate:
        debate_ratio = _difflib.SequenceMatcher(None, prev_debate, curr_debate).ratio()
        if debate_ratio < 0.50:
            core_debate_shifted = True
            what_changed.append(
                f"Core debate shifted: '{previous.core_debate[:80]}' → '{current.core_debate[:80]}'"
            )
            change_drivers.append("Core market debate changed")
            if not material_shift:
                material_shift = True
                severity = max(severity, "medium") if severity != "high" else severity

    base_diff = ThesisDiff(
        what_changed         = what_changed,
        thesis_trend         = thesis_trend,
        change_drivers       = change_drivers,
        material_shift_detected = material_shift,
        severity             = severity,
        confidence_change    = conf_delta,
        new_risks            = new_risks,
        removed_risks        = removed_risks,
        strengthening_signals= strengthening_signals,
        weakening_signals    = weakening_signals,
        top_signal_replaced  = top_signal_replaced,
        trend_flipped        = trend_flipped,
        previous_snapshot_id = previous.snapshot_id,
        current_snapshot_id  = current.snapshot_id,
        core_debate_shifted  = core_debate_shifted,
        prev_core_debate     = previous.core_debate if core_debate_shifted else "",
        curr_core_debate     = current.core_debate if core_debate_shifted else "",
    )
    # Classify extended drift state (7-state taxonomy)
    base_diff.drift_state = _classify_drift_state(base_diff, previous, current)
    return base_diff


def _classify_thesis_trend(
    conf_delta:          float,
    new_risks_count:     int,
    removed_risks_count: int,
    sig_added_count:     int,
    sig_removed_count:   int,
    top_signal_replaced: bool,
    prev_trend:          str,
) -> str:
    """Classify the thesis trend from structured diff dimensions.

    Hierarchy (first rule that matches wins):
        strengthening — confidence up AND no new structural risks
        weakening     — confidence down significantly OR new risks AND confidence falling
        inflecting    — trend reversed from prior snapshot direction
        stable        — all deltas within noise bounds
        unclear       — default
    """
    # Strengthening: positive conviction, no new downside
    if conf_delta >= CONFIDENCE_MINOR_THRESHOLD and new_risks_count == 0:
        return "strengthening"

    # Strong weakening: confidence collapsed OR new risks + falling confidence
    if conf_delta <= -CONFIDENCE_MATERIAL_THRESHOLD:
        return "weakening"
    if new_risks_count >= NEW_STRUCTURAL_RISK_COUNT and conf_delta < 0:
        return "weakening"

    # Moderate weakening: replaced top signal + any new risk
    if top_signal_replaced and new_risks_count > 0 and conf_delta < 0:
        return "weakening"

    # Inflecting: trend has reversed from prior
    prev_opp = _TREND_OPPOSITES.get(prev_trend, "")
    # Re-check: if new data moves the opposite direction of the prior trend label
    if prev_trend == "strengthening" and conf_delta <= -CONFIDENCE_MINOR_THRESHOLD:
        return "inflecting"
    if prev_trend == "weakening" and conf_delta >= CONFIDENCE_MINOR_THRESHOLD:
        return "inflecting"

    # Stable: minimal movement across all dimensions
    if (
        abs(conf_delta) < CONFIDENCE_MINOR_THRESHOLD
        and new_risks_count == 0
        and not top_signal_replaced
    ):
        return "stable"

    return "unclear"


def _compute_severity(
    conf_delta:          float,
    new_risks_count:     int,
    top_signal_replaced: bool,
    trend_flipped:       bool,
) -> str:
    """Derive change severity from the most significant dimension.

    HIGH:   confidence collapsed (≥15pp) | trend reversed
    MEDIUM: confidence material drop (≥8pp) | new structural risk | top signal replaced
    LOW:    minor confidence shift | signal set noise
    """
    if abs(conf_delta) >= CONFIDENCE_COLLAPSE_THRESHOLD or trend_flipped:
        return "high"

    if (
        abs(conf_delta) >= CONFIDENCE_MATERIAL_THRESHOLD
        or new_risks_count >= NEW_STRUCTURAL_RISK_COUNT
        or top_signal_replaced
    ):
        return "medium"

    if abs(conf_delta) >= CONFIDENCE_MINOR_THRESHOLD or new_risks_count > 0:
        return "low"

    return "low"


def _classify_drift_state(
    diff: ThesisDiff,
    prev: ThesisSnapshot,
    curr: ThesisSnapshot,
) -> str:
    """Classify thesis evolution into a 7-state drift taxonomy.

    States (first match wins):
        strengthening — confidence materially up, no new structural risks
        weakening     — confidence materially down OR new risks + falling conviction
        bifurcating   — new risks emerged while signals also strengthened (asymmetric)
        repricing     — dominant dimension shifted without fundamental change
        transition    — top signal replaced + trend reversal (old thesis breaking)
        unchanged     — all deltas within noise bounds, no signal changes
        unclear       — default when state cannot be determined
    """
    conf_delta = diff.confidence_change
    new_risks_count = len(diff.new_risks)
    sig_added_count = len(diff.strengthening_signals)

    # Strengthening: conviction clearly up, no new downside introduced
    if conf_delta >= CONFIDENCE_MINOR_THRESHOLD and new_risks_count == 0:
        return "strengthening"

    # Weakening: conviction materially down
    if conf_delta <= -CONFIDENCE_MATERIAL_THRESHOLD:
        return "weakening"

    # Bifurcating: bull AND bear both developing — new risks while signals also gained
    if new_risks_count >= 1 and sig_added_count >= 1 and abs(conf_delta) < CONFIDENCE_MATERIAL_THRESHOLD:
        return "bifurcating"

    # Transition: top signal replaced + trend reversal (old thesis breaking, new one forming)
    if diff.top_signal_replaced and diff.trend_flipped:
        return "transition"

    # Repricing: dominant dimension changed without material confidence swing
    prev_dim = getattr(prev, "dominant_dimension", "") or ""
    curr_dim = getattr(curr, "dominant_dimension", "") or ""
    if prev_dim and curr_dim and prev_dim != curr_dim and abs(conf_delta) < CONFIDENCE_MATERIAL_THRESHOLD:
        return "repricing"

    # Unchanged: all within noise bounds
    if (
        abs(conf_delta) < CONFIDENCE_MINOR_THRESHOLD
        and new_risks_count == 0
        and not diff.top_signal_replaced
        and sig_added_count == 0
    ):
        return "unchanged"

    # Weakening (secondary): new risks + any negative delta
    if new_risks_count >= NEW_STRUCTURAL_RISK_COUNT and conf_delta < 0:
        return "weakening"

    return "unclear"


def _is_market_repricing(diff: ThesisDiff, prev: ThesisSnapshot, curr: ThesisSnapshot) -> bool:
    """True when the market moved but the operating thesis is intact.

    Repricing = the dominant dimension rotated (macro/rate/sentiment) without
    fundamental operating deterioration (no new structural risks, no trend flip,
    no confidence collapse).
    """
    drift = _classify_drift_state(diff, prev, curr)
    prev_dim = getattr(prev, "dominant_dimension", "") or ""
    curr_dim = getattr(curr, "dominant_dimension", "") or ""
    dim_rotated = prev_dim and curr_dim and prev_dim != curr_dim

    if drift in ("repricing", "unchanged"):
        return True
    # Dimension rotated to macro without structural breaks → market repriced
    if dim_rotated and curr_dim in ("macro", "rates") and not diff.new_risks and not diff.trend_flipped:
        return True
    # Small confidence move with no new risks → noise-level rerating, not thesis break
    if (
        abs(diff.confidence_change) < CONFIDENCE_MATERIAL_THRESHOLD
        and not diff.new_risks
        and not diff.trend_flipped
        and not diff.top_signal_replaced
    ):
        return True
    return False


def _is_thesis_broke(diff: ThesisDiff) -> bool:
    """True when the thesis mechanism itself deteriorated, not just the market price."""
    return (
        diff.trend_flipped
        or diff.confidence_change <= -CONFIDENCE_COLLAPSE_THRESHOLD
        or (diff.confidence_change <= -CONFIDENCE_MATERIAL_THRESHOLD and len(diff.new_risks) >= 1)
    )


def build_pm_change_narrative(
    diff: ThesisDiff,
    prev: ThesisSnapshot,
    curr: ThesisSnapshot,
) -> str:
    """Generate a PM-quality single-sentence narrative of what changed.

    Uses diff dimensions + snapshot context to produce mechanism-first language.
    Explicitly distinguishes 'market repriced, thesis intact' from 'thesis itself broke'.
    NEVER references internal scoring, agent names, or percentages.

    Design invariant: returns a single sentence ending in '.'.
    """
    drift = _classify_drift_state(diff, prev, curr)
    conf_delta = diff.confidence_change
    prev_dim = getattr(prev, "dominant_dimension", "") or ""
    curr_dim = getattr(curr, "dominant_dimension", "") or ""

    # ── Core debate shifted ───────────────────────────────────────────────────
    # Check FIRST: a debate shift is the most analytically significant event.
    # It means the fulcrum variable changed — not just the risk weighting.
    if getattr(diff, "core_debate_shifted", False):
        prev_debate = getattr(diff, "prev_core_debate", "") or prev_dim.replace("_", " ")
        curr_debate = getattr(diff, "curr_core_debate", "") or curr_dim.replace("_", " ")
        if prev_debate and curr_debate:
            # Compress to 50 chars each
            prev_short = prev_debate[:50].rstrip("?. ")
            curr_short = curr_debate[:50].rstrip("?. ")
            return (
                f"The debate shifted from '{prev_short}' toward '{curr_short}' — "
                f"the fulcrum variable changed, not just the risk weighting."
            )
        return (
            "The core market debate changed — what the market is pricing is no longer "
            "the same question as the prior analysis."
        )

    # ── Market repriced, thesis intact ───────────────────────────────────────
    # Check this FIRST — repricing is the most common case and should produce
    # explicit "operating story unchanged" language, not generic weakening language.
    if _is_market_repricing(diff, prev, curr):
        if prev_dim and curr_dim and prev_dim != curr_dim:
            return (
                f"The operating story is unchanged — the move came from "
                f"{curr_dim.replace('_', ' ')} conditions, not fundamentals."
            )
        if drift == "unchanged":
            return "No material thesis change — the core debate and positioning remain intact."
        return (
            "The operating story held — the repricing came from the market, not the thesis."
        )

    # ── Thesis broke: confidence collapse ────────────────────────────────────
    if _is_thesis_broke(diff):
        if diff.trend_flipped and conf_delta < 0:
            if diff.new_risks:
                risk = diff.new_risks[0].split(":")[0].strip()
                return f"The original bull thesis broke — {risk} is now the dominant constraint, not a secondary risk."
            return "The burden shifted — the original thesis mechanism no longer holds on the current evidence."
        if conf_delta <= -CONFIDENCE_COLLAPSE_THRESHOLD:
            if diff.new_risks:
                risk = diff.new_risks[0].split(":")[0].strip()
                return f"The original assumption no longer holds — {risk} moved to the center of the bear case."
            return "The original thesis mechanism deteriorated — the operating story is no longer intact."
        if diff.new_risks:
            risk = diff.new_risks[0].split(":")[0].strip()
            return f"Thesis conviction weakened on new evidence — {risk} is now a structural constraint, not a tail risk."

    # ── Dimension shift → repricing (with material confidence move) ──────────
    if drift == "repricing" and prev_dim and curr_dim and prev_dim != curr_dim:
        return (
            f"The debate shifted from {prev_dim.replace('_', ' ')} toward "
            f"{curr_dim.replace('_', ' ')} — the original setup no longer frames the risk."
        )

    # ── Transition: old thesis breaking, new one not yet confirmed ───────────
    if drift == "transition":
        return (
            "The original thesis mechanism is breaking before a replacement is confirmed — "
            "the setup is in transition, not repricing."
        )

    # ── Bifurcating: both bull and bear developing simultaneously ────────────
    if drift == "bifurcating":
        if diff.new_risks:
            risk_label = diff.new_risks[0].split(":")[0].strip()
            return (
                f"The bull/bear asymmetry is widening — {risk_label} entered the bear case "
                f"while the upside catalyst remains intact."
            )
        return (
            "Bull/bear asymmetry is widening — both the upside driver and the downside risk "
            "are developing simultaneously."
        )

    # ── Trend flip (positive) ─────────────────────────────────────────────────
    if diff.trend_flipped and conf_delta >= 0:
        return "The setup improved materially — the prior overhang cleared and the thesis is reaccelerating."

    # ── Thesis weakened (no collapse, no flip) ────────────────────────────────
    if drift == "weakening":
        if diff.new_risks and curr_dim:
            return (
                f"{curr_dim.replace('_', ' ').title()} pressure increased — "
                f"{diff.new_risks[0].split(':')[0].strip()} is now the primary constraint."
            )
        if diff.new_risks:
            return (
                f"The risk profile shifted — "
                f"{diff.new_risks[0].split(':')[0].strip()} emerged as a new structural concern."
            )
        if curr_dim == "macro":
            return (
                "Macro conditions now conflict with the original setup — "
                "rate and growth assumptions need revisiting."
            )
        return "Valuation support weakened against the current macro and risk profile."

    # ── Thesis strengthened ───────────────────────────────────────────────────
    if drift == "strengthening":
        if diff.strengthening_signals:
            sig = diff.strengthening_signals[0].split(":")[0].strip()
            return f"The setup improved — {sig} added durability to the thesis."
        return "The core thesis mechanism held — conviction improved as the evidence picture clarified."

    # ── New structural risk (no broad trend shift) ────────────────────────────
    if diff.new_risks:
        risk = diff.new_risks[0].split(":")[0].strip()
        return f"{risk} moved into the risk profile — the market still needs to price this."

    # ── Top signal replaced ───────────────────────────────────────────────────
    if diff.top_signal_replaced:
        return "The primary thesis driver rotated — the original signal no longer leads the investment case."

    # ── Stable / unchanged ────────────────────────────────────────────────────
    return "No material thesis change — the core debate and positioning remain intact."


# ---------------------------------------------------------------------------
# Phase 6: detect_material_change
# ---------------------------------------------------------------------------

def detect_material_change(
    diff:    ThesisDiff,
    ticker:  str,
    prev:    ThesisSnapshot,
    current: ThesisSnapshot,
) -> Optional[MaterialChangeEvent]:
    """Apply material change thresholds and produce a MaterialChangeEvent.

    Returns None when the diff does not cross any material threshold.
    Material thresholds:
        HIGH   — confidence_collapse (≥15pp drop) | trend_flip
        MEDIUM — confidence_material (≥8pp) | new_structural_risk | top_signal_replaced
    """
    if not diff.material_shift_detected:
        return None

    ts = current.timestamp or _now_iso()

    # ── Classify change_type ──────────────────────────────────────────────────
    change_type = _classify_change_type(diff)

    # ── Compute materiality score (0.0–1.0) ────────────────────────────────
    # Drives alert suppression for cosmetic/wording changes:
    #   ≥ 0.70 → high structural change (thesis broke or trend flipped)
    #   0.40–0.69 → medium (new risk, top signal replaced, material confidence drop)
    #   < 0.40 → cosmetic/noise (small moves without mechanism change)
    mat_score = 0.0
    if diff.trend_flipped:
        mat_score += 0.40
    if diff.confidence_change <= -CONFIDENCE_COLLAPSE_THRESHOLD:
        mat_score += 0.35
    elif diff.confidence_change <= -CONFIDENCE_MATERIAL_THRESHOLD:
        mat_score += 0.20
    elif abs(diff.confidence_change) <= CONFIDENCE_MINOR_THRESHOLD:
        mat_score += 0.05
    if diff.new_risks:
        mat_score += min(len(diff.new_risks) * 0.12, 0.25)
    if diff.top_signal_replaced:
        mat_score += 0.15
    if getattr(diff, "core_debate_shifted", False):
        mat_score += 0.25  # debate shift is analytically significant
    mat_score = min(mat_score, 1.0)

    # ── Classify change_category (human-facing) ────────────────────────────
    is_repricing = _is_market_repricing(diff, prev, current)
    is_broke = _is_thesis_broke(diff)
    is_debate_shift = getattr(diff, "core_debate_shifted", False)
    if is_broke and diff.trend_flipped:
        change_category = "thesis_broke"
    elif is_broke:
        change_category = "thesis_broke"
    elif is_debate_shift:
        change_category = "core_debate_shift"
    elif is_repricing and diff.confidence_change >= CONFIDENCE_MINOR_THRESHOLD:
        change_category = "thesis_strengthened"
    elif is_repricing:
        change_category = "market_repriced"
    elif diff.new_risks:
        change_category = "new_risk_emerged"
    elif mat_score < 0.20:
        change_category = "cosmetic"
    else:
        change_category = "market_repriced"

    # ── Build summary ─────────────────────────────────────────────────────────
    summary = _build_event_summary(change_type, diff, ticker)

    return MaterialChangeEvent(
        ticker               = ticker.upper(),
        severity             = diff.severity,
        summary              = summary,
        drivers              = diff.change_drivers[:5],
        timestamp            = ts,
        change_type          = change_type,
        previous_snapshot_id = diff.previous_snapshot_id,
        current_snapshot_id  = diff.current_snapshot_id,
        confidence_change    = diff.confidence_change,
        thesis_trend_changed = diff.trend_flipped,
        materiality_score    = mat_score,
        change_category      = change_category,
    )


def _classify_change_type(diff: ThesisDiff) -> str:
    """Map the most significant diff dimension to a canonical change_type label."""
    # Severity-first, then specific dimension
    if diff.trend_flipped:
        return "trend_flip"
    if diff.confidence_change <= -CONFIDENCE_COLLAPSE_THRESHOLD:
        return "confidence_collapse"
    if diff.confidence_change <= -CONFIDENCE_MATERIAL_THRESHOLD:
        return "thesis_weakened"
    if diff.confidence_change >= CONFIDENCE_MATERIAL_THRESHOLD:
        return "thesis_strengthened"
    if getattr(diff, "core_debate_shifted", False):
        return "core_debate_shift"
    if diff.new_risks:
        return "new_structural_risk"
    if diff.top_signal_replaced:
        return "top_signal_replaced"
    if diff.thesis_trend in ("weakening", "inflecting"):
        return "thesis_weakened"
    if diff.thesis_trend == "strengthening":
        return "thesis_strengthened"
    return "stable"


def _build_event_summary(change_type: str, diff: ThesisDiff, ticker: str) -> str:
    """Build a PM-quality one-sentence alert summary for a MaterialChangeEvent.

    Uses mechanism-first language. No internal scoring references, no agent names.
    """
    top_new_risk = diff.new_risks[0].split(":")[0].strip() if diff.new_risks else ""

    # Build debate-shift summary from prev/curr debate text when available
    prev_debate = getattr(diff, "prev_core_debate", "") or ""
    curr_debate = getattr(diff, "curr_core_debate", "") or ""
    if prev_debate and curr_debate:
        # Compress to first 60 chars each for readability
        prev_short = prev_debate[:60].rstrip("?. ") + "…"
        curr_short = curr_debate[:60].rstrip("?. ") + "…"
        debate_shift_summary = (
            f"{ticker}: The debate shifted — from '{prev_short}' toward '{curr_short}'."
        )
    else:
        debate_shift_summary = (
            f"{ticker}: The core market debate changed — the fulcrum variable rotated between analyses."
        )

    _TEMPLATES: Dict[str, str] = {
        "confidence_collapse":
            f"{ticker}: The original thesis mechanism deteriorated — the operating story no longer supports the prior setup.",
        "thesis_weakened":
            f"{ticker}: Risk/reward narrowed — the burden shifts to execution as the thesis loses valuation support.",
        "thesis_strengthened":
            f"{ticker}: The setup improved — conviction increased as the operating story clarified against the current regime.",
        "trend_flip":
            f"{ticker}: Thesis direction reversed to '{diff.thesis_trend}' — repricing or fundamental break, review the updated analysis.",
        "new_structural_risk":
            f"{ticker}: {top_new_risk + ' entered the primary risk case — the market still needs to price this.' if top_new_risk else 'A new structural risk emerged — the investment bar is now higher.'}",
        "top_signal_replaced":
            f"{ticker}: Primary investment driver rotated — the original thesis anchor is no longer the leading variable.",
        "core_debate_shift": debate_shift_summary,
        "stable":
            f"{ticker}: Core debate stable — no material thesis change on the current evidence.",
    }
    return _TEMPLATES.get(change_type, f"{ticker}: Thesis change detected — review the updated analysis.")


# ---------------------------------------------------------------------------
# Phase 9: Alert rule evaluators + ALERT_RULE_EVALUATORS registry
# ---------------------------------------------------------------------------

# Each evaluator takes (diff: ThesisDiff, threshold: Optional[float]) → bool.
# The threshold parameter is the AlertRule.threshold value (may be None).
AlertRuleEvaluator = Callable[[ThesisDiff, Optional[float]], bool]

def _eval_thesis_weakens(diff: ThesisDiff, threshold: Optional[float]) -> bool:
    """Fires when conviction drops by at least `threshold` pp (default: 8pp)."""
    t = threshold if threshold is not None else CONFIDENCE_MATERIAL_THRESHOLD
    return diff.confidence_change <= -t


def _eval_confidence_collapses(diff: ThesisDiff, threshold: Optional[float]) -> bool:
    """Fires when conviction drops by at least `threshold` pp (default: 15pp)."""
    t = threshold if threshold is not None else CONFIDENCE_COLLAPSE_THRESHOLD
    return diff.confidence_change <= -t


def _eval_new_structural_risk(diff: ThesisDiff, threshold: Optional[float]) -> bool:
    """Fires when at least one new risk surface."""
    count = int(threshold) if threshold is not None else NEW_STRUCTURAL_RISK_COUNT
    return len(diff.new_risks) >= count


def _eval_trend_flip(diff: ThesisDiff, threshold: Optional[float]) -> bool:
    """Fires when the thesis trend direction has reversed."""
    return diff.trend_flipped


def _eval_top_signal_replaced(diff: ThesisDiff, threshold: Optional[float]) -> bool:
    """Fires when the #1 ranked signal changed."""
    return diff.top_signal_replaced


def _eval_thesis_strengthens(diff: ThesisDiff, threshold: Optional[float]) -> bool:
    """Fires when conviction improves by at least `threshold` pp (default: 8pp)."""
    t = threshold if threshold is not None else CONFIDENCE_MATERIAL_THRESHOLD
    return diff.confidence_change >= t


def _eval_core_debate_shift(diff: ThesisDiff, threshold: Optional[float]) -> bool:
    """Fires when the core market debate changed between snapshots.

    The fulcrum variable — the single question investors are debating — rotated.
    This is analytically more significant than confidence moves alone.
    Threshold is unused (debate shift is binary based on text similarity).
    """
    return bool(getattr(diff, "core_debate_shifted", False))


ALERT_RULE_EVALUATORS: Dict[str, AlertRuleEvaluator] = {
    "thesis_weakens":       _eval_thesis_weakens,
    "confidence_collapses": _eval_confidence_collapses,
    "new_structural_risk":  _eval_new_structural_risk,
    "trend_flip":           _eval_trend_flip,
    "top_signal_replaced":  _eval_top_signal_replaced,
    "thesis_strengthens":   _eval_thesis_strengthens,
    "core_debate_shift":    _eval_core_debate_shift,
}

# ── Built-in default rules ─────────────────────────────────────────────────

DEFAULT_ALERT_RULES: List[AlertRule] = [
    AlertRule(
        rule_id       = "default_confidence_collapse",
        name          = "Conviction Collapse",
        description   = "Fires when conviction drops by ≥15pp in a single refresh",
        condition_key = "confidence_collapses",
        threshold     = CONFIDENCE_COLLAPSE_THRESHOLD,
        severity      = "high",
    ),
    AlertRule(
        rule_id       = "default_thesis_weakens",
        name          = "Thesis Weakening",
        description   = "Fires when conviction drops by ≥8pp",
        condition_key = "thesis_weakens",
        threshold     = CONFIDENCE_MATERIAL_THRESHOLD,
        severity      = "medium",
    ),
    AlertRule(
        rule_id       = "default_new_structural_risk",
        name          = "New Structural Risk",
        description   = "Fires when at least one new risk surfaces in the model",
        condition_key = "new_structural_risk",
        threshold     = float(NEW_STRUCTURAL_RISK_COUNT),
        severity      = "medium",
    ),
    AlertRule(
        rule_id       = "default_trend_flip",
        name          = "Thesis Direction Reversed",
        description   = "Fires when the thesis trend flips from strengthening to weakening or vice-versa",
        condition_key = "trend_flip",
        threshold     = None,
        severity      = "high",
    ),
    AlertRule(
        rule_id       = "default_top_signal_replaced",
        name          = "Primary Signal Replaced",
        description   = "Fires when the #1 ranked investment signal changes",
        condition_key = "top_signal_replaced",
        threshold     = None,
        severity      = "medium",
    ),
    AlertRule(
        rule_id       = "default_thesis_strengthens",
        name          = "Thesis Strengthening",
        description   = "Fires when conviction improves by ≥8pp",
        condition_key = "thesis_strengthens",
        threshold     = CONFIDENCE_MATERIAL_THRESHOLD,
        severity      = "low",
    ),
]


def evaluate_alert_rules(
    diff:  ThesisDiff,
    rules: Optional[List[AlertRule]] = None,
) -> List[AlertRule]:
    """Evaluate a list of AlertRules against a ThesisDiff.

    Returns only the rules that fired.  When *rules* is None the module-level
    DEFAULT_ALERT_RULES are used.

    This is a pure function: no I/O, no side effects.
    """
    active_rules = rules if rules is not None else DEFAULT_ALERT_RULES
    fired: List[AlertRule] = []
    for rule in active_rules:
        evaluator = ALERT_RULE_EVALUATORS.get(rule.condition_key)
        if evaluator is None:
            logger.warning(
                "evaluate_alert_rules: unknown condition_key %r — skipping rule %s",
                rule.condition_key, rule.rule_id,
            )
            continue
        try:
            if evaluator(diff, rule.threshold):
                fired.append(rule)
        except Exception as exc:
            logger.warning(
                "evaluate_alert_rules: evaluator error for rule %s: %s",
                rule.rule_id, exc,
            )
    return fired
