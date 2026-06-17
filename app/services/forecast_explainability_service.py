"""
Forecast Explainability Service — Phase 12 · Slice 4.

Turns probability outputs (from forecast_probability_engine) and feature
inputs (from forecast_feature_builder) into human-readable, safety-gated
forecast explanations.

All functions are pure: no I/O, no DB access, no session parameters,
no side effects.  This module imports only from forecast_constants and
the Python standard library.

Gate contract (spec §6)
-----------------------
A forecast explanation MUST pass validate_forecast_explanation before it
may be written to forecast_vector or delivered to any consumer.

Validation rejects explanations that have:
  - empty why, evidence, or invalidators
  - missing or wrong disclaimer text
  - unsupported horizon_days or forecast_type
  - any banned advice phrase in prose fields
  - any price-target or recommendation language in prose fields

Prose generation rules
-----------------------
  - why strings describe historical pattern frequencies and observed signals.
    They never predict future prices, returns, or outcomes directly.
  - invalidators are factual conditions — not advice — that would negate the
    forecast if they occurred.
  - evidence entries cite the substrate used (analog IDs, peer keys, thesis
    versions) with direction and contribution weight.
  - Every explanation includes the MANDATORY_DISCLAIMER verbatim.

Safety invariants
-----------------
  - No import from forecast_probability_engine, forecast_feature_builder,
    or any DB / ORM module.
  - No write calls anywhere in this module.
  - MANDATORY_DISCLAIMER from forecast_constants is the only disclaimer text
    allowed; it is never modified.
  - contains_banned_advice_language is called on all prose fields before
    validate_forecast_explanation returns True.
"""

from __future__ import annotations

from app.services.forecast_constants import (
    ALLOWED_FORECAST_TYPES,
    ALLOWED_HORIZONS,
    ALLOWED_CONFIDENCE_LABELS,
    MANDATORY_DISCLAIMER,
    BANNED_ADVICE_PHRASES,
    FORECAST_TYPE_DISPLAY,
    INVALIDATOR_TEMPLATES,
    GENERIC_INVALIDATORS,
)

# ---------------------------------------------------------------------------
# Banned-phrase scanner
# ---------------------------------------------------------------------------

def contains_banned_advice_language(text_or_payload) -> bool:
    """Return True if text_or_payload (or any nested value) contains a banned phrase.

    Performs case-insensitive substring matching against BANNED_ADVICE_PHRASES.
    Recurses into dict values and list/tuple items.

    Args:
        text_or_payload: str, dict, list, tuple, or any other value.
                         Non-string scalars (int, float, bool, None) → False.

    Returns:
        True  — at least one banned phrase found.
        False — no banned phrase found.
    """
    if isinstance(text_or_payload, str):
        lower = text_or_payload.lower()
        return any(phrase in lower for phrase in BANNED_ADVICE_PHRASES)
    if isinstance(text_or_payload, dict):
        return any(contains_banned_advice_language(v) for v in text_or_payload.values())
    if isinstance(text_or_payload, (list, tuple)):
        return any(contains_banned_advice_language(item) for item in text_or_payload)
    return False


# ---------------------------------------------------------------------------
# Evidence summary builder
# ---------------------------------------------------------------------------

def build_evidence_summary(features: dict, probability_output: dict) -> list:
    """Build a list of evidence dicts from the feature object.

    Each entry has:
      source_type  — "analog" | "similarity_peer" | "thesis_trajectory" |
                     "debate_state" | "regime_context" | "prior"
      source_id    — identifier within its source type (analog_id, peer key, etc.)
      direction    — "positive" | "negative" | "neutral"
      contribution — float, proportion of evidence weight carried by this item
      weight       — float, raw relevance weight from source
      description  — human-readable prose (must not contain banned phrases)

    Always returns at least one item (falls back to a conservative prior entry
    when substrate is empty).
    """
    evidence: list = []
    analog_set = (features.get("analog_set") or [])[:5]   # cap at 5 for readability
    peers = (features.get("similarity_peers") or [])[:5]
    traj = features.get("thesis_trajectory") or {}
    version_count = int(traj.get("version_count", 0))
    debate = features.get("debate_state") or {}
    rc = features.get("regime_context") or {}

    forecast_type = probability_output.get("forecast_type", "")
    comps = probability_output.get("components") or {}

    # Analogs
    total_analog_weight = sum(float(a.get("relevance_weight", 1.0)) for a in analog_set) or 1.0
    for a in analog_set:
        rw = float(a.get("relevance_weight", 1.0))
        resolution = a.get("resolution", "unknown")
        mechanism = a.get("mechanism", "")
        drawdown = a.get("drawdown_pct")
        tags = a.get("concern_tags") or []

        parts = []
        if mechanism:
            parts.append(f"mechanism: {mechanism}")
        if tags:
            parts.append(f"concern tags: {', '.join(str(t) for t in tags[:3])}")
        if drawdown is not None:
            parts.append(f"drawdown: {abs(float(drawdown) * 100):.0f}%")

        desc = f"Historical analog (ID: {a.get('analog_id', 'n/a')}) — {'; '.join(parts) or 'pattern match'}. Resolution: {resolution}."
        evidence.append({
            "source_type": "analog",
            "source_id": a.get("analog_id", ""),
            "direction": resolution if resolution in ("positive", "negative", "neutral") else "neutral",
            "contribution": round(rw / total_analog_weight * float(comps.get("p_base_rate", 0.33)) * 0.35, 4),
            "weight": round(rw, 4),
            "description": desc,
        })

    # Similarity peers
    for peer in peers:
        score = float(peer.get("score", 0.0))
        direction = "positive" if score >= 0.65 else "neutral"
        desc = (
            f"Similarity peer '{peer.get('candidate_key', 'unknown')}' — "
            f"floor-passed score {score:.2f} (rank {peer.get('rank', '?')})."
        )
        evidence.append({
            "source_type": "similarity_peer",
            "source_id": peer.get("candidate_key", ""),
            "direction": direction,
            "contribution": round(score * float(comps.get("p_sim_peer", 0.33)) * 0.35 / max(1, len(peers)), 4),
            "weight": round(score, 4),
            "description": desc,
        })

    # Thesis trajectory
    if version_count > 0:
        conf_current = float(traj.get("confidence_current", 0.0))
        direction_str = traj.get("direction", "flat") or "flat"
        _dir_to_dir = {"rising": "positive", "falling": "negative", "flat": "neutral", "unknown": "neutral"}
        ev_direction = _dir_to_dir.get(direction_str, "neutral")
        desc = (
            f"Thesis trajectory over {version_count} version(s): "
            f"conviction is {direction_str} (current confidence {int(conf_current * 100)}%)."
        )
        evidence.append({
            "source_type": "thesis_trajectory",
            "source_id": (features.get("source_versions") or {}).get("thesis_version_id", ""),
            "direction": ev_direction,
            "contribution": round(float(comps.get("p_thesis_signal", 0.33)) * 0.30, 4),
            "weight": round(conf_current, 4),
            "description": desc,
        })

    # Core debate
    lean = debate.get("current_lean", "balanced") or "balanced"
    if lean != "balanced":
        _lean_dir = {"bearish": "negative", "bullish": "positive"}
        ev_dir = _lean_dir.get(lean, "neutral")
        desc = (
            f"Core debate leans {lean} "
            f"(debate confidence {int(float(debate.get('confidence', 0.0)) * 100)}%)."
        )
        evidence.append({
            "source_type": "debate_state",
            "source_id": f"debate_v{debate.get('version', 1)}",
            "direction": ev_dir,
            "contribution": round(float(comps.get("p_thesis_signal", 0.33)) * 0.10, 4),
            "weight": round(float(debate.get("confidence", 0.0)), 4),
            "description": desc,
        })

    # Regime context
    trend = rc.get("conviction_trend", "stable") or "stable"
    cycle = rc.get("cycle_position", "unknown") or "unknown"
    if trend != "stable" or (cycle != "unknown" and cycle != ""):
        _trend_dir = {"declining": "negative", "rising": "positive", "stable": "neutral"}
        ev_dir = _trend_dir.get(trend, "neutral")
        parts = []
        if trend != "stable":
            parts.append(f"conviction trend {trend}")
        if cycle != "unknown":
            parts.append(f"cycle position {cycle.replace('_', ' ')}")
        desc = f"Regime context: {'; '.join(parts) or 'stable regime'}."
        evidence.append({
            "source_type": "regime_context",
            "source_id": "regime",
            "direction": ev_dir,
            "contribution": round(float(comps.get("p_regime_signal", 0.33)) * 0.25, 4),
            "weight": 1.0,
            "description": desc,
        })

    # T4 failure mode
    fm = features.get("failure_mode")
    if fm:
        stage = int(fm.get("sequence_stage", 1))
        mechanism = fm.get("mechanism", "") or ""
        mech_str = f" (mechanism: {mechanism})" if mechanism else ""
        desc = f"Failure mode at sequence stage {stage}{mech_str}."
        evidence.append({
            "source_type": "failure_mode",
            "source_id": features.get("entity_key", ""),
            "direction": "negative" if stage >= 2 else "neutral",
            "contribution": round(0.10, 4),
            "weight": round(float(fm.get("relevance_at_match", 0.5)), 4),
            "description": desc,
        })

    # Staleness marker
    if probability_output.get("staleness_penalty_applied"):
        evidence.append({
            "source_type": "staleness_flag",
            "source_id": "staleness",
            "direction": "neutral",
            "contribution": 0.0,
            "weight": 0.0,
            "description": "Dossier substrate is flagged as stale — staleness penalty applied.",
        })

    # Conservative prior fallback — always ensures evidence is non-empty
    if not evidence:
        evidence.append({
            "source_type": "prior",
            "source_id": "conservative_prior",
            "direction": "neutral",
            "contribution": round(1.0 / 3.0, 4),
            "weight": 1.0,
            "description": (
                "Conservative prior distribution — insufficient analog or "
                "similarity substrate available. Probability reflects base rates only."
            ),
        })

    return evidence


# ---------------------------------------------------------------------------
# Why-narrative builder
# ---------------------------------------------------------------------------

def _build_why(features: dict, probability_output: dict) -> list:
    """Construct the list of why-strings for an explanation.

    Strings describe observed pattern frequencies and signals.
    They never predict prices, returns, or assert future outcomes.

    Always returns at least one string.
    """
    why: list = []

    forecast_type = probability_output.get("forecast_type", "")
    type_display = FORECAST_TYPE_DISPLAY.get(forecast_type, forecast_type)
    comps = probability_output.get("components") or {}
    p_base = float(comps.get("p_base_rate", 0.33))
    staleness = bool(probability_output.get("staleness_penalty_applied", False))
    evidence_strength = float(probability_output.get("evidence_strength", 0.0))
    p_positive = float(probability_output.get("p_positive", 0.33))

    analog_set = features.get("analog_set") or []
    analog_count = int(features.get("analog_count", 0))
    peer_count = int(features.get("similarity_peer_count", 0))
    avg_score = float(features.get("similarity_avg_score", 0.0))
    traj = features.get("thesis_trajectory") or {}
    version_count = int(traj.get("version_count", 0))
    direction = traj.get("direction", "flat") or "flat"
    conf_current = float(traj.get("confidence_current", 0.0))
    debate = features.get("debate_state") or {}
    lean = debate.get("current_lean", "balanced") or "balanced"
    rc = features.get("regime_context") or {}
    trend = rc.get("conviction_trend", "stable") or "stable"
    cycle = rc.get("cycle_position", "unknown") or "unknown"

    # --- Analog base rate ------------------------------------------------
    if analog_count > 0:
        pos_count = sum(1 for a in analog_set if a.get("resolution") == "positive")
        neg_count = sum(1 for a in analog_set if a.get("resolution") == "negative")
        neu_count = analog_count - pos_count - neg_count
        why.append(
            f"Historical analog base rate for {type_display}: "
            f"{int(round(p_base * 100))}% event frequency across {analog_count} "
            f"comparable analog(s) ({pos_count} positive, {neg_count} negative, "
            f"{neu_count} neutral resolution)."
        )

    # --- Similarity peers -------------------------------------------------
    if peer_count > 0:
        why.append(
            f"Pattern similarity: {peer_count} similar entity/entities identified "
            f"(average floor-passed similarity score {avg_score:.2f})."
        )

    # --- Thesis trajectory ------------------------------------------------
    if version_count > 0:
        why.append(
            f"Thesis trajectory over {version_count} version(s): "
            f"conviction is {direction} "
            f"(current confidence level {int(round(conf_current * 100))}%)."
        )

    # --- Core debate lean -------------------------------------------------
    if lean != "balanced":
        why.append(f"Core debate leans {lean}.")

    # --- Regime context ---------------------------------------------------
    if trend != "stable" and trend != "unknown":
        why.append(f"Conviction trend: {trend}.")
    if cycle != "unknown" and cycle:
        why.append(f"Cycle position: {cycle.replace('_', ' ')}.")

    # --- T4 failure mode --------------------------------------------------
    fm = features.get("failure_mode")
    if fm:
        stage = int(fm.get("sequence_stage", 1))
        mechanism = fm.get("mechanism", "") or ""
        rel = float(fm.get("relevance_at_match", 0.5))
        if mechanism:
            why.append(f"Failure mode mechanism: {mechanism} (relevance at match: {rel:.2f}).")
        why.append(f"Failure mode at sequence stage {stage}.")

    # --- Staleness notice -------------------------------------------------
    if staleness:
        why.append(
            "Note: dossier substrate is flagged as stale — "
            "probability confidence is reduced and a staleness penalty has been applied."
        )

    # --- Probability summary line (always included) -----------------------
    why.append(
        f"Ensemble probability of {type_display} event: "
        f"{int(round(p_positive * 100))}% "
        f"(evidence strength {int(round(evidence_strength * 100))}%, "
        f"based on historical pattern frequencies only)."
    )

    # --- Sparse fallback --------------------------------------------------
    if analog_count == 0 and peer_count == 0 and version_count == 0:
        why.insert(0,
            "Limited substrate available — probability reflects a conservative "
            f"prior based on {analog_count} historical analog(s) and "
            f"{peer_count} similarity peer(s). Treat with low confidence."
        )

    return why


# ---------------------------------------------------------------------------
# Invalidator builder
# ---------------------------------------------------------------------------

def build_invalidators(features: dict, probability_output: dict) -> list:
    """Build a list of invalidator strings for the given forecast type.

    Invalidators describe factual conditions under which the forecast would
    no longer hold.  They are template-based, factual, and contain no advice.

    Always returns at least two strings (type-specific + one generic).
    """
    forecast_type = probability_output.get("forecast_type", "")

    type_specific = list(INVALIDATOR_TEMPLATES.get(forecast_type, ()))
    generic = list(GENERIC_INVALIDATORS)

    # T4 failure mode adds stage-specific conditions
    fm = features.get("failure_mode")
    if fm:
        stage = int(fm.get("sequence_stage", 1))
        if stage >= 3:
            type_specific.append(
                "Failure mode progression halts — company addresses the stage-"
                f"{stage} risk before the forecast horizon."
            )
        else:
            type_specific.append(
                "Failure mode does not progress beyond the current sequence stage "
                "within the forecast horizon."
            )

    # Staleness adds an explicit caveat invalidator
    if probability_output.get("staleness_penalty_applied"):
        generic.append(
            "Refreshed dossier data changes the substrate materially, "
            "requiring a full re-score of this forecast."
        )

    combined = type_specific + generic
    # Guarantee at least one item even for unknown types
    if not combined:
        combined = [
            "New material information fundamentally changes the risk profile.",
            "The forecast horizon elapses without the event pattern materialising.",
        ]
    return combined


# ---------------------------------------------------------------------------
# Analog basis + similarity basis builders (for forecast_vector storage)
# ---------------------------------------------------------------------------

def _build_analog_basis(features: dict) -> list:
    """Return a list of analog citation dicts suitable for forecast_vector.analog_basis."""
    result = []
    for a in (features.get("analog_set") or []):
        result.append({
            "analog_id": a.get("analog_id", ""),
            "mechanism": a.get("mechanism", ""),
            "resolution": a.get("resolution", "unknown"),
            "relevance_weight": float(a.get("relevance_weight", 1.0)),
        })
    return result


def _build_similarity_basis(features: dict) -> list:
    """Return a list of similarity peer citation dicts for forecast_vector.similarity_basis."""
    result = []
    for p in (features.get("similarity_peers") or []):
        result.append({
            "candidate_key": p.get("candidate_key", ""),
            "score": float(p.get("score", 0.0)),
            "rank": int(p.get("rank", 0)),
        })
    return result


# ---------------------------------------------------------------------------
# Main explanation builder
# ---------------------------------------------------------------------------

def build_forecast_explanation(features: dict, probability_output: dict) -> dict:
    """Build a complete forecast explanation dict.

    Combines why-narrative, evidence summary, invalidators, analog/similarity
    basis citations, and the mandatory disclaimer into a single explanation
    object ready for gate-checking by validate_forecast_explanation.

    Args:
        features:          Feature dict from build_company_forecast_features or
                           build_failure_mode_forecast_features.  May be empty
                           or sparse; builder falls back to conservative content.
        probability_output: Output dict from score_company_forecast or
                           score_failure_mode_forecast.  Must contain at least
                           forecast_type, horizon_days, and p_positive to produce
                           a useful explanation.

    Returns:
        Explanation dict with keys:
          why, evidence, invalidators, analog_basis, similarity_basis,
          horizon_days, forecast_type, confidence_label, disclaimer,
          staleness_penalty_applied, evidence_strength.

        Does NOT raise.  If inputs are degenerate, returns a conservative
        explanation that will fail validate_forecast_explanation (e.g. due
        to missing/wrong horizon_days or forecast_type).
    """
    features = features or {}
    probability_output = probability_output or {}

    why = _build_why(features, probability_output)
    evidence = build_evidence_summary(features, probability_output)
    invalidators = build_invalidators(features, probability_output)
    analog_basis = _build_analog_basis(features)
    similarity_basis = _build_similarity_basis(features)

    return {
        "why": why,
        "evidence": evidence,
        "invalidators": invalidators,
        "analog_basis": analog_basis,
        "similarity_basis": similarity_basis,
        "horizon_days": probability_output.get("horizon_days", 0),
        "forecast_type": probability_output.get("forecast_type", ""),
        "confidence_label": probability_output.get("confidence_label", "low"),
        "disclaimer": MANDATORY_DISCLAIMER,
        "staleness_penalty_applied": bool(probability_output.get("staleness_penalty_applied", False)),
        "evidence_strength": float(probability_output.get("evidence_strength", 0.0)),
    }


# ---------------------------------------------------------------------------
# Validation gate
# ---------------------------------------------------------------------------

def validate_forecast_explanation(explanation: dict) -> bool:
    """Return True iff the explanation passes all safety and completeness gates.

    Gate checks (all must pass):
      1. explanation is a non-empty dict
      2. why    — non-empty list of non-empty strings
      3. evidence — non-empty list of dicts
      4. invalidators — non-empty list of non-empty strings
      5. disclaimer  — present and equals MANDATORY_DISCLAIMER verbatim
      6. horizon_days — in ALLOWED_HORIZONS
      7. forecast_type — in ALLOWED_FORECAST_TYPES
      8. confidence_label — in ALLOWED_CONFIDENCE_LABELS
      9. No banned advice phrase in any why string
     10. No banned advice phrase in any evidence description
     11. No banned advice phrase in any invalidator string

    Args:
        explanation: dict returned by build_forecast_explanation (or manually
                     constructed — either way, must pass all gates).

    Returns:
        True — explanation is complete and safe to store / deliver.
        False — at least one gate failed.
    """
    if not isinstance(explanation, dict) or not explanation:
        return False

    # ── Completeness gates ─────────────────────────────────────────────────
    why = explanation.get("why")
    if not isinstance(why, list) or not why:
        return False
    if not all(isinstance(s, str) and s.strip() for s in why):
        return False

    evidence = explanation.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False

    invalidators = explanation.get("invalidators")
    if not isinstance(invalidators, list) or not invalidators:
        return False
    if not all(isinstance(s, str) and s.strip() for s in invalidators):
        return False

    # ── Disclaimer gate ────────────────────────────────────────────────────
    disclaimer = explanation.get("disclaimer")
    if disclaimer != MANDATORY_DISCLAIMER:
        return False

    # ── Type / horizon gate ───────────────────────────────────────────────
    if explanation.get("horizon_days") not in ALLOWED_HORIZONS:
        return False

    if explanation.get("forecast_type") not in ALLOWED_FORECAST_TYPES:
        return False

    # ── Confidence label gate ──────────────────────────────────────────────
    if explanation.get("confidence_label") not in ALLOWED_CONFIDENCE_LABELS:
        return False

    # ── Banned-phrase gate (prose fields only, not disclaimer) ────────────
    for text in why:
        if contains_banned_advice_language(text):
            return False

    for item in evidence:
        if isinstance(item, dict):
            desc = item.get("description", "")
            if contains_banned_advice_language(str(desc)):
                return False

    for text in invalidators:
        if contains_banned_advice_language(text):
            return False

    return True
