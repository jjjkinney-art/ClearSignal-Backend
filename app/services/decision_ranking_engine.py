"""
Decision Ranking Engine — Phase 13 · Slice 3.

Converts decision candidates (from Slice 13.2) into ranked priority results
using one parameterized scoring formula.  Candidate type selects a weight row;
there is no separate engine per type.

Formula
-------
    base_score     = clamp01(attention * w_a  +  urgency * w_u  +  impact * w_i)
    decision_score = clamp01(base_score × confidence_multiplier
                                        × uncertainty_discount
                                        × exposure_multiplier)

where
    w_a + w_u + w_i = 1.0  (per type — weights stored in _WEIGHT_CONFIG)
    confidence_multiplier ∈ [0.30, 1.00]  — weak evidence dampens the score
    uncertainty_discount  ∈ [0.50, 1.00]  — high spread / neutral probability
                                             discount = 1 − λ_u × uncertainty
    exposure_multiplier   ∈ [0.50, 1.50]  — portfolio position weight amplifier;
                                             non-portfolio types receive 1.0

Ranked-result envelope
----------------------
    candidate_type       str
    entity_type          str
    entity_id            str
    ticker               str
    source_type          str
    source_id            str
    decision_score       float — final composite score, [0, 1]
    attention_score      float — [0, 1]
    urgency_score        float — [0, 1]
    impact_score         float — [0, 1]
    confidence_multiplier float — [0.30, 1.00]
    uncertainty_discount  float — [0.50, 1.00]
    exposure_multiplier   float — [0.50, 1.50]
    rank_inputs          dict  — {w_attention, w_urgency, w_impact, base_score}
    candidate            dict  — the original candidate from Slice 13.2

Ordering: descending decision_score; ties broken by source_id ascending
(deterministic).

Safety invariants (SP-5)
------------------------
    - Pure functions only: no session, no DB imports, no writes.
    - No buy/sell/hold/recommend/target-price/position-size/trade field.
    - No import from conviction, recommendation, order, or execution modules.
    - No import from forecast_delivery_service or any delivery write path.
"""

from __future__ import annotations

from typing import Dict, List

# ---------------------------------------------------------------------------
# Candidate type constants (mirrors decision_candidate_builder — import-safe)
# ---------------------------------------------------------------------------

CANDIDATE_TYPE_FORECAST            = "forecast_candidate"
CANDIDATE_TYPE_RISK                = "risk_candidate"
CANDIDATE_TYPE_CATALYST            = "catalyst_candidate"
CANDIDATE_TYPE_WATCHLIST           = "watchlist_candidate"
CANDIDATE_TYPE_PORTFOLIO_EXPOSURE  = "portfolio_exposure_candidate"
CANDIDATE_TYPE_DELIVERY_TRANSITION = "delivery_transition_candidate"
CANDIDATE_TYPE_SIMILARITY          = "similarity_candidate"

# ---------------------------------------------------------------------------
# Per-type weight configuration
# All rows must satisfy w_a + w_u + w_i == 1.00 so base_score ∈ [0, 1]
# when each component score ∈ [0, 1].
# ---------------------------------------------------------------------------

_WEIGHT_CONFIG: Dict[str, Dict[str, float]] = {
    CANDIDATE_TYPE_FORECAST: {
        "w_attention": 0.40,
        "w_urgency":   0.35,
        "w_impact":    0.25,
    },
    CANDIDATE_TYPE_RISK: {
        "w_attention": 0.25,
        "w_urgency":   0.40,
        "w_impact":    0.35,
    },
    CANDIDATE_TYPE_CATALYST: {
        "w_attention": 0.25,
        "w_urgency":   0.40,
        "w_impact":    0.35,
    },
    CANDIDATE_TYPE_WATCHLIST: {
        "w_attention": 0.50,
        "w_urgency":   0.25,
        "w_impact":    0.25,
    },
    CANDIDATE_TYPE_PORTFOLIO_EXPOSURE: {
        "w_attention": 0.25,
        "w_urgency":   0.35,
        "w_impact":    0.40,
    },
    CANDIDATE_TYPE_DELIVERY_TRANSITION: {
        "w_attention": 0.35,
        "w_urgency":   0.45,
        "w_impact":    0.20,
    },
    CANDIDATE_TYPE_SIMILARITY: {
        "w_attention": 0.45,
        "w_urgency":   0.25,
        "w_impact":    0.30,
    },
    "_default": {
        "w_attention": 0.35,
        "w_urgency":   0.35,
        "w_impact":    0.30,
    },
}

# Uncertainty-discount lambda: uncertainty_discount = 1 − λ_u × uncertainty_factor
_LAMBDA_U: float = 0.50

# Exposure multiplier bounds
_EXPOSURE_MIN: float = 0.50
_EXPOSURE_MAX: float = 1.50
_EXPOSURE_DEFAULT: float = 1.00

# Confidence multiplier floor
_CONFIDENCE_MIN: float = 0.30


# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------

def normalize_score(value) -> float:
    """Clamp *value* to [0, 1]. Returns 0.0 for non-numeric inputs."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_float(mapping: dict, key: str, default: float = 0.0) -> float:
    v = mapping.get(key, default)
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _safe_bool(mapping: dict, key: str) -> bool:
    return bool(mapping.get(key, False))


# ---------------------------------------------------------------------------
# Attention score — how noteworthy is this signal right now?
# ---------------------------------------------------------------------------

def compute_attention_score(candidate: dict) -> float:
    """Return attention score ∈ [0, 1] for *candidate*.

    Attention captures how salient and notice-worthy the signal is,
    independent of when it will resolve (urgency) or how large the effect
    would be (impact).
    """
    ctype = candidate.get("candidate_type", "")
    ai = candidate.get("attention_inputs", {}) or {}

    if ctype == CANDIDATE_TYPE_FORECAST:
        direction = ai.get("direction", "")
        ftype = ai.get("forecast_type", "")
        base = 0.55 if direction == "strengthening" else 0.65
        # Downside / risk-related forecast types earn higher attention
        if ftype in ("thesis_weakening", "risk_emergence", "regime_transition"):
            base = min(1.0, base + 0.15)
        return normalize_score(base)

    if ctype == CANDIDATE_TYPE_RISK:
        stage = _safe_float(ai, "stage", 1.0)
        # Stage 1 → 0.36; stage 5 → 1.00
        return normalize_score(min(stage, 5.0) / 5.0 * 0.80 + 0.20)

    if ctype == CANDIDATE_TYPE_CATALYST:
        direction = ai.get("direction", "")
        # Bear triggers deserve more attention (downside-awareness bias)
        return normalize_score(0.75 if direction == "bear_trigger" else 0.60)

    if ctype == CANDIDATE_TYPE_WATCHLIST:
        return 0.50  # symmetric baseline: watched, but no directional signal yet

    if ctype == CANDIDATE_TYPE_PORTFOLIO_EXPOSURE:
        mc = ai.get("membership_class", "watchlist")
        return normalize_score({"owned": 0.80, "watchlist": 0.50, "on_radar": 0.30}.get(mc, 0.50))

    if ctype == CANDIDATE_TYPE_DELIVERY_TRANSITION:
        status = ai.get("status", "")
        return normalize_score(0.70 if status == "failed" else 0.55)

    if ctype == CANDIDATE_TYPE_SIMILARITY:
        return normalize_score(_safe_float(ai, "score", 0.0))

    return 0.50


# ---------------------------------------------------------------------------
# Urgency score — how time-sensitive is this signal?
# ---------------------------------------------------------------------------

def compute_urgency_score(candidate: dict) -> float:
    """Return urgency score ∈ [0, 1] for *candidate*.

    Urgency captures the time-to-resolution horizon: near-term signals
    and recently-matched risks score higher than slow-moving long-term ones.
    """
    ctype = candidate.get("candidate_type", "")
    ui = candidate.get("urgency_inputs", {}) or {}

    if ctype == CANDIDATE_TYPE_FORECAST:
        horizon_days = _safe_float(ui, "horizon_days", 90.0)
        # 30 d → 1.0; 180 d → 0.0; linear
        return normalize_score(1.0 - min(horizon_days, 180.0) / 180.0)

    if ctype == CANDIDATE_TYPE_RISK:
        stage = _safe_float(ui, "sequence_stage", 1.0)
        matched_days = _safe_float(ui, "matched_days_ago", 30.0)
        stage_urgency = min(stage, 5.0) / 5.0
        recency = max(0.0, 1.0 - matched_days / 90.0)
        return normalize_score(0.60 * stage_urgency + 0.40 * recency)

    if ctype == CANDIDATE_TYPE_CATALYST:
        specificity = _safe_float(ui, "specificity", 0.0)
        created_days = _safe_float(ui, "created_days_ago", 0.0)
        recency = max(0.0, 1.0 - created_days / 90.0)
        return normalize_score(0.50 * specificity + 0.50 * recency)

    if ctype == CANDIDATE_TYPE_WATCHLIST:
        added_days = _safe_float(ui, "added_days_ago", 0.0)
        # Recently added items are more salient; never below 0.30
        return normalize_score(max(0.0, 1.0 - added_days / 180.0) * 0.70 + 0.30)

    if ctype == CANDIDATE_TYPE_PORTFOLIO_EXPOSURE:
        mc = ui.get("membership_class", "watchlist")
        return normalize_score({"owned": 0.70, "watchlist": 0.50, "on_radar": 0.30}.get(mc, 0.50))

    if ctype == CANDIDATE_TYPE_DELIVERY_TRANSITION:
        status = ui.get("status", "")
        attempts = _safe_float(ui, "attempts", 0.0)
        severity_rank = _safe_float(ui, "severity_rank", 0.0)
        base = 0.70 if status == "failed" else 0.50
        attempts_boost = min(attempts * 0.05, 0.20)
        severity_boost = severity_rank / 4.0 * 0.20
        return normalize_score(base + attempts_boost + severity_boost)

    if ctype == CANDIDATE_TYPE_SIMILARITY:
        rank = _safe_float(ui, "rank", 10.0)
        built_days = _safe_float(ui, "built_days_ago", 0.0)
        rank_urgency = max(0.0, 1.0 - rank / 10.0)
        recency = max(0.0, 1.0 - built_days / 7.0)
        return normalize_score(0.50 * rank_urgency + 0.50 * recency)

    return 0.50


# ---------------------------------------------------------------------------
# Impact score — how large would the effect be if this signal is correct?
# ---------------------------------------------------------------------------

def compute_impact_score(candidate: dict) -> float:
    """Return impact score ∈ [0, 1] for *candidate*.

    Impact captures the magnitude of consequence if the signal materialises.
    For portfolio exposure candidates this is the intrinsic impact before
    applying the exposure_multiplier — the multiplier is applied later.
    """
    ctype = candidate.get("candidate_type", "")
    ii = candidate.get("impact_inputs", {}) or {}

    if ctype == CANDIDATE_TYPE_FORECAST:
        p_pos = _safe_float(ii, "p_positive", 0.33)
        p_neg = _safe_float(ii, "p_negative", 0.33)
        return normalize_score(max(p_pos, p_neg))

    if ctype == CANDIDATE_TYPE_RISK:
        relevance = _safe_float(ii, "relevance_at_match", 0.0)
        stage = _safe_float(ii, "sequence_stage", 1.0)
        stage_factor = min(stage, 5.0) / 5.0
        return normalize_score(0.60 * relevance + 0.40 * stage_factor)

    if ctype == CANDIDATE_TYPE_CATALYST:
        specificity = _safe_float(ii, "specificity", 0.0)
        conviction_weight = _safe_float(ii, "conviction_weight", 0.0)
        return normalize_score(0.50 * specificity + 0.50 * conviction_weight)

    if ctype == CANDIDATE_TYPE_WATCHLIST:
        return 0.50  # no position data; neutral

    if ctype == CANDIDATE_TYPE_PORTFOLIO_EXPOSURE:
        weight = ii.get("weight")
        mc = ii.get("membership_class", "watchlist")
        if weight is not None:
            # 10 % allocation → 0.30, 33 % → 0.99 — linear scale factor 3×
            return normalize_score(float(weight) * 3.0)
        return normalize_score({"owned": 0.60, "watchlist": 0.40, "on_radar": 0.20}.get(mc, 0.40))

    if ctype == CANDIDATE_TYPE_DELIVERY_TRANSITION:
        severity_rank = _safe_float(ii, "severity_rank", 0.0)
        return normalize_score(severity_rank / 4.0)

    if ctype == CANDIDATE_TYPE_SIMILARITY:
        score = _safe_float(ii, "score", 0.0)
        rank = _safe_float(ii, "rank", 10.0)
        rank_factor = max(0.0, 1.0 - rank / 10.0)
        return normalize_score(0.70 * score + 0.30 * rank_factor)

    return 0.50


# ---------------------------------------------------------------------------
# Confidence multiplier — how much should we trust this signal?
# ---------------------------------------------------------------------------

def compute_confidence_multiplier(candidate: dict) -> float:
    """Return confidence multiplier ∈ [0.30, 1.00] for *candidate*.

    Weak evidence or narrow provenance dampens the composite score.
    A sparse candidate (missing evidence) will receive the minimum floor.
    """
    ctype = candidate.get("candidate_type", "")
    ci = candidate.get("confidence_inputs", {}) or {}

    if ctype == CANDIDATE_TYPE_FORECAST:
        cb_low = _safe_float(ci, "confidence_band_low", 0.0)
        cb_high = _safe_float(ci, "confidence_band_high", 1.0)
        band_width = cb_high - cb_low
        ev_count = _safe_float(ci, "evidence_count", 0.0)
        band_conf = max(0.0, 1.0 - band_width)        # narrow band → high conf
        ev_conf = min(1.0, ev_count / 5.0)            # 5+ evidence items → full
        raw = 0.60 * band_conf + 0.40 * ev_conf
        return _clamp(raw, _CONFIDENCE_MIN, 1.0)

    if ctype == CANDIDATE_TYPE_RISK:
        relevance = _safe_float(ci, "relevance_at_match", 0.0)
        has_label = _safe_bool(ci, "has_analog_label")
        has_ev = _safe_bool(ci, "has_stage_evidence")
        raw = (relevance * 0.50
               + (0.25 if has_label else 0.0)
               + (0.25 if has_ev else 0.0))
        return _clamp(raw, _CONFIDENCE_MIN, 1.0)

    if ctype == CANDIDATE_TYPE_CATALYST:
        spec = _safe_float(ci, "specificity", 0.0)
        has_stmt = _safe_bool(ci, "has_statement")
        has_win = _safe_bool(ci, "has_expected_window")
        raw = (spec * 0.60
               + (0.20 if has_stmt else 0.0)
               + (0.20 if has_win else 0.0))
        return _clamp(raw, _CONFIDENCE_MIN, 1.0)

    if ctype == CANDIDATE_TYPE_WATCHLIST:
        has_name = _safe_bool(ci, "has_company_name")
        return 0.80 if has_name else 0.60

    if ctype == CANDIDATE_TYPE_PORTFOLIO_EXPOSURE:
        has_w = _safe_bool(ci, "has_weight")
        has_cb = _safe_bool(ci, "has_cost_basis")
        raw = 0.60 + (0.20 if has_w else 0.0) + (0.20 if has_cb else 0.0)
        return _clamp(raw, _CONFIDENCE_MIN, 1.0)

    if ctype == CANDIDATE_TYPE_DELIVERY_TRANSITION:
        has_sev = _safe_bool(ci, "has_severity")
        has_ref = _safe_bool(ci, "has_artifact_ref")
        raw = 0.50 + (0.30 if has_sev else 0.0) + (0.20 if has_ref else 0.0)
        return _clamp(raw, _CONFIDENCE_MIN, 1.0)

    if ctype == CANDIDATE_TYPE_SIMILARITY:
        score = _safe_float(ci, "score", 0.0)
        has_contrib = _safe_bool(ci, "has_contributions")
        has_dis = _safe_bool(ci, "has_disanalogy")
        raw = (score * 0.60
               + (0.20 if has_contrib else 0.0)
               + (0.20 if has_dis else 0.0))
        return _clamp(raw, _CONFIDENCE_MIN, 1.0)

    return 0.60


# ---------------------------------------------------------------------------
# Uncertainty discount — penalise high probability spread or neutral mass
# ---------------------------------------------------------------------------

def compute_uncertainty_discount(candidate: dict) -> float:
    """Return uncertainty discount ∈ [0.50, 1.00] for *candidate*.

    discount = clamp([0.50, 1.00],  1 − λ_u × uncertainty_factor)

    A perfectly certain signal returns 1.00; maximum uncertainty returns 0.50.
    λ_u = 0.50 so even the worst case only halves the score — the floor
    ensures highly uncertain but high-intrinsic risks remain visible.
    """
    ctype = candidate.get("candidate_type", "")
    uu = candidate.get("uncertainty_inputs", {}) or {}

    if ctype == CANDIDATE_TYPE_FORECAST:
        band_width = _safe_float(uu, "band_width", 0.50)
        p_neutral = _safe_float(uu, "p_neutral", 0.33)
        uncertainty = 0.50 * band_width + 0.50 * p_neutral
        return _clamp(1.0 - _LAMBDA_U * uncertainty, 0.50, 1.0)

    if ctype == CANDIDATE_TYPE_RISK:
        matched_days = _safe_float(uu, "matched_days_ago", 0.0)
        stage = _safe_float(uu, "sequence_stage", 1.0)
        age_u = min(matched_days / 90.0, 1.0)
        stage_cert = min(stage, 5.0) / 5.0
        uncertainty = 0.50 * age_u + 0.50 * (1.0 - stage_cert)
        return _clamp(1.0 - _LAMBDA_U * uncertainty, 0.50, 1.0)

    if ctype == CANDIDATE_TYPE_CATALYST:
        inv_spec = _safe_float(uu, "inverse_specificity", 0.50)
        created_days = _safe_float(uu, "created_days_ago", 0.0)
        age_u = min(created_days / 90.0, 1.0)
        uncertainty = 0.60 * inv_spec + 0.40 * age_u
        return _clamp(1.0 - _LAMBDA_U * uncertainty, 0.50, 1.0)

    if ctype == CANDIDATE_TYPE_WATCHLIST:
        added_days = _safe_float(uu, "added_days_ago", 0.0)
        uncertainty = min(added_days / 365.0, 1.0)
        return _clamp(1.0 - _LAMBDA_U * uncertainty, 0.50, 1.0)

    if ctype == CANDIDATE_TYPE_PORTFOLIO_EXPOSURE:
        weight = uu.get("weight")
        added_days = _safe_float(uu, "added_days_ago", 0.0)
        w_u = 0.0 if weight is not None else 0.50   # missing weight → uncertain
        age_u = min(added_days / 180.0, 1.0)
        uncertainty = 0.50 * w_u + 0.50 * age_u
        return _clamp(1.0 - _LAMBDA_U * uncertainty, 0.50, 1.0)

    if ctype == CANDIDATE_TYPE_DELIVERY_TRANSITION:
        attempts = _safe_float(uu, "attempts", 0.0)
        created_days = _safe_float(uu, "created_days_ago", 0.0)
        attempt_u = min(attempts * 0.10, 0.50)
        age_u = min(created_days / 30.0, 1.0)
        uncertainty = 0.50 * attempt_u + 0.50 * age_u
        return _clamp(1.0 - _LAMBDA_U * uncertainty, 0.50, 1.0)

    if ctype == CANDIDATE_TYPE_SIMILARITY:
        inv_score = _safe_float(uu, "inverse_score", 0.50)
        built_days = _safe_float(uu, "built_days_ago", 0.0)
        age_u = min(built_days / 7.0, 1.0)
        uncertainty = 0.70 * inv_score + 0.30 * age_u
        return _clamp(1.0 - _LAMBDA_U * uncertainty, 0.50, 1.0)

    return 0.75


# ---------------------------------------------------------------------------
# Exposure multiplier — scale by portfolio position size
# ---------------------------------------------------------------------------

def compute_exposure_multiplier(candidate: dict) -> float:
    """Return exposure multiplier ∈ [0.50, 1.50] for *candidate*.

    Only portfolio_exposure_candidate deviates from the neutral 1.0.
    A 10 % portfolio weight → ~1.30×; 33 % → 1.50× (cap).
    Un-positioned or no-data candidates return exactly 1.0 (no adjustment).
    """
    ctype = candidate.get("candidate_type", "")
    if ctype != CANDIDATE_TYPE_PORTFOLIO_EXPOSURE:
        return _EXPOSURE_DEFAULT

    ii = candidate.get("impact_inputs", {}) or {}
    weight = ii.get("weight")
    mc = ii.get("membership_class", "watchlist")

    if weight is not None:
        # 0 % weight → 1.0; 33 %+ weight → 1.50
        raw = 1.0 + min(float(weight) * 1.50, 0.50)
    else:
        raw = {"owned": 1.20, "watchlist": 1.00, "on_radar": 0.80}.get(mc, 1.00)

    return _clamp(raw, _EXPOSURE_MIN, _EXPOSURE_MAX)


# ---------------------------------------------------------------------------
# Per-candidate ranking
# ---------------------------------------------------------------------------

def rank_candidate(candidate: dict) -> dict:
    """Return a ranked-result dict for a single *candidate*.

    All scoring functions are called here; the formula is applied once.
    No DB access; no writes; no side effects.
    """
    ctype = candidate.get("candidate_type", "")
    weights = _WEIGHT_CONFIG.get(ctype, _WEIGHT_CONFIG["_default"])
    w_a = weights["w_attention"]
    w_u = weights["w_urgency"]
    w_i = weights["w_impact"]

    attention   = compute_attention_score(candidate)
    urgency     = compute_urgency_score(candidate)
    impact      = compute_impact_score(candidate)
    confidence  = compute_confidence_multiplier(candidate)
    uncertainty = compute_uncertainty_discount(candidate)
    exposure    = compute_exposure_multiplier(candidate)

    base_score     = normalize_score(attention * w_a + urgency * w_u + impact * w_i)
    decision_score = normalize_score(base_score * confidence * uncertainty * exposure)

    return {
        "candidate_type":       ctype,
        "entity_type":          candidate.get("entity_type", ""),
        "entity_id":            candidate.get("entity_id", ""),
        "ticker":               candidate.get("ticker", ""),
        "source_type":          candidate.get("source_type", ""),
        "source_id":            candidate.get("source_id", ""),
        "decision_score":       decision_score,
        "attention_score":      attention,
        "urgency_score":        urgency,
        "impact_score":         impact,
        "confidence_multiplier": confidence,
        "uncertainty_discount": uncertainty,
        "exposure_multiplier":  exposure,
        "rank_inputs": {
            "w_attention": w_a,
            "w_urgency":   w_u,
            "w_impact":    w_i,
            "base_score":  base_score,
        },
        "candidate": candidate,
    }


# ---------------------------------------------------------------------------
# Batch ranking
# ---------------------------------------------------------------------------

def rank_candidates(candidates: list) -> list:
    """Rank a list of candidates and return them sorted by decision_score.

    Sort order: decision_score descending (higher = more important).
    Ties broken by source_id ascending — deterministic across calls with
    the same substrate.

    Returns [] for an empty input. Never raises.
    """
    if not candidates:
        return []

    try:
        ranked = [rank_candidate(c) for c in candidates]
        ranked.sort(key=lambda r: (-r["decision_score"], r["source_id"]))
        return ranked
    except Exception:
        return []
