"""
Forecast Probability Engine — Phase 12 · Slice 3.

Converts forecast feature dicts (from forecast_feature_builder) into
probability distributions.  All functions are pure: no I/O, no DB access,
no side effects.  The output dict is shaped for later forecast_vector storage
but nothing is written here — that is the orchestration layer's job (Slice 5).

Supported forecast types (6)
-----------------------------
  thesis_strengthening  — probability that existing thesis conviction rises
  thesis_weakening      — probability that existing thesis conviction falls
  risk_emergence        — probability that a latent risk materialises
  catalyst_realization  — probability that a near-term catalyst fires
  similarity_outcome    — probability of matching the dominant peer outcome
  regime_transition     — probability of a macro/sector regime shift

Supported horizons
------------------
  30   near_term
  90   medium_term
  180  long_term
  Any other value → ValueError (callers must handle).

Probability framework (spec §5)
--------------------------------
For each forecast type an ensemble blends four component signals:

  P_ensemble = w_base × P_base_rate
             + w_sim  × P_sim_peer
             + w_thesis × P_thesis_signal
             + w_regime × P_regime_signal

  where ∑w = 1.0 (renormalised from the weight table below).

The ensemble gives P(event_direction=positive).  The residual
(1 − P_positive) is then split into P_negative / P_neutral via a
type-specific ratio, and the final triple is renormalised to sum 1.0 with
each component clamped to [0.01, 0.99].

Confidence band
---------------
Half-width of the uncertainty band around p_positive.  Shrinks with
evidence strength, expands for stale substrate and longer horizons.
Clamped so [low, high] ⊆ [0, 1].

Evidence strength
-----------------
A 0–1 scalar summarising how much substrate backs this forecast:
  0.35 × analog_coverage + 0.35 × peer_coverage + 0.30 × thesis_present

Staleness penalty
-----------------
When staleness_indicators.dossier_staleness_state == "stale":
  - probabilities are pulled 25 % toward the conservative prior (0.33/0.33/0.34)
  - confidence band half-width increases by 0.08
  - staleness_penalty_applied = True in output

Safety invariants (Phase 12 spec §0)
--------------------------------------
  - No price target, expected return, buy/sell/hold, advice language anywhere.
  - No DB writes — pure functions only.
  - No imports from forecast_repo, any ORM, or any DB session helper.
  - Dependency direction: engine may read feature objects from
    forecast_feature_builder; nothing in Phase 11 or earlier ever imports
    this module.
"""

from __future__ import annotations

import math
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_FORECAST_TYPES: frozenset[str] = frozenset({
    "thesis_strengthening",
    "thesis_weakening",
    "risk_emergence",
    "catalyst_realization",
    "similarity_outcome",
    "regime_transition",
})

SUPPORTED_HORIZONS: frozenset[int] = frozenset({30, 90, 180})

ENGINE_SCHEMA_VERSION: int = 1

# Conservative uniform prior — used when evidence is fully absent.
_PRIOR_POS: float = 0.33
_PRIOR_NEG: float = 0.33
_PRIOR_NEU: float = 0.34

# Probability clamp bounds (spec: [0.01, 0.99])
_P_MIN: float = 0.01
_P_MAX: float = 0.99

# ---------------------------------------------------------------------------
# Ensemble weights per forecast type
# weights sum to 1.0 per row; renormalised defensively at runtime.
# ---------------------------------------------------------------------------

_WEIGHTS: dict[str, dict[str, float]] = {
    #                              base  sim   thesis  regime
    "thesis_strengthening":  dict(base=0.20, sim=0.20, thesis=0.45, regime=0.15),
    "thesis_weakening":      dict(base=0.25, sim=0.15, thesis=0.40, regime=0.20),
    "risk_emergence":        dict(base=0.30, sim=0.25, thesis=0.25, regime=0.20),
    "catalyst_realization":  dict(base=0.20, sim=0.30, thesis=0.30, regime=0.20),
    "similarity_outcome":    dict(base=0.15, sim=0.55, thesis=0.15, regime=0.15),
    "regime_transition":     dict(base=0.25, sim=0.15, thesis=0.15, regime=0.45),
}

# Residual split: how (1 − p_positive) is divided between negative and neutral.
# Tuple: (neg_fraction, neu_fraction)
_RESIDUAL_SPLIT: dict[str, tuple[float, float]] = {
    "thesis_strengthening": (0.55, 0.45),
    "thesis_weakening":     (0.55, 0.45),
    "risk_emergence":       (0.40, 0.60),
    "catalyst_realization": (0.45, 0.55),
    "similarity_outcome":   (0.50, 0.50),
    "regime_transition":    (0.35, 0.65),
}

# Horizon expansion for confidence half-width
_HORIZON_EXPANSION: dict[int, float] = {30: 0.00, 90: 0.03, 180: 0.07}

# Staleness penalty: pull toward prior by this fraction
_STALENESS_PULL: float = 0.25


# ---------------------------------------------------------------------------
# Public output schema
# ---------------------------------------------------------------------------

def _empty_output(forecast_type: str, horizon_days: int) -> dict:
    """Conservative (max uncertainty) output for sparse/error cases."""
    return {
        "p_positive": _PRIOR_POS,
        "p_negative": _PRIOR_NEG,
        "p_neutral": _PRIOR_NEU,
        "confidence_low": 0.10,
        "confidence_high": 0.56,
        "confidence_label": "low",
        "horizon_days": horizon_days,
        "forecast_type": forecast_type,
        "components": {
            "p_base_rate": _PRIOR_POS,
            "p_sim_peer": _PRIOR_POS,
            "p_thesis_signal": _PRIOR_POS,
            "p_regime_signal": _PRIOR_POS,
            "weights_used": _WEIGHTS.get(forecast_type, {}),
        },
        "evidence_strength": 0.0,
        "staleness_penalty_applied": False,
        "engine_schema": ENGINE_SCHEMA_VERSION,
    }


# ---------------------------------------------------------------------------
# Component signal extractors (pure functions of the feature dict)
# ---------------------------------------------------------------------------

def _resolution_positive_flag(forecast_type: str, resolution: str) -> Optional[bool]:
    """Return True if analog resolution counts as 'positive' for this forecast type.

    Maps analog outcome direction to directional agreement with the forecast event.
    Returns None for 'unknown' resolutions (excluded from base-rate computation).
    """
    if resolution == "unknown":
        return None
    if forecast_type in ("thesis_strengthening", "catalyst_realization"):
        return resolution == "positive"
    if forecast_type in ("thesis_weakening", "risk_emergence"):
        return resolution == "negative"
    if forecast_type == "similarity_outcome":
        # Any non-negative resolution counts as positive peer outcome
        return resolution in ("positive", "neutral")
    if forecast_type == "regime_transition":
        # Regime transition analogs typically resolve neutral (survived change)
        return resolution in ("positive", "neutral")
    return resolution == "positive"


def _p_base_rate(features: dict, forecast_type: str) -> float:
    """Base-rate signal from historical analogs weighted by relevance_weight."""
    analog_set = features.get("analog_set") or []
    if not analog_set:
        return _PRIOR_POS

    weighted_pos = 0.0
    total_weight = 0.0
    for a in analog_set:
        resolution = a.get("resolution", "unknown")
        weight = float(a.get("relevance_weight", 1.0))
        flag = _resolution_positive_flag(forecast_type, resolution)
        if flag is None:
            continue  # skip unknowns
        weighted_pos += weight * (1.0 if flag else 0.0)
        total_weight += weight

    if total_weight < 1e-9:
        return _PRIOR_POS
    return min(1.0, weighted_pos / total_weight)


def _p_sim_peer(features: dict, forecast_type: str) -> float:
    """Similarity peer signal.

    More peers with higher scores → stronger confirmation of the peer pattern.
    For thesis_strengthening/catalyst: high sim score → positive (peers recovered).
    For thesis_weakening/risk_emergence: high sim score → also positive (peers deteriorated).
    For similarity_outcome: sim score is the direct probability proxy.
    """
    peer_count = int(features.get("similarity_peer_count", 0))
    avg_score = float(features.get("similarity_avg_score", 0.0))

    if peer_count == 0 or avg_score < 1e-9:
        return _PRIOR_POS

    # Evidence weight: saturates at 10 peers
    coverage = min(1.0, peer_count / 10.0)
    if forecast_type == "similarity_outcome":
        # Direct use: sim score as probability proxy
        return avg_score * (0.6 + 0.4 * coverage)
    elif forecast_type in ("thesis_strengthening", "catalyst_realization"):
        # High similarity to recovering peers → bullish signal
        return avg_score * (0.5 + 0.5 * coverage)
    elif forecast_type in ("thesis_weakening", "risk_emergence"):
        # High similarity to distressed peers → bearish signal (inverted)
        return avg_score * (0.5 + 0.5 * coverage)
    elif forecast_type == "regime_transition":
        # Peers in transition → moderate signal
        return 0.40 + 0.30 * avg_score * coverage
    else:
        return avg_score * 0.5 + 0.25 * coverage


def _p_thesis_signal(features: dict, forecast_type: str) -> float:
    """Thesis trajectory signal.

    Maps the thesis confidence trajectory, direction, and debate state onto
    a 0–1 probability estimate for the positive outcome of this forecast type.
    """
    traj = features.get("thesis_trajectory") or {}
    debate = features.get("debate_state") or {}
    durability = features.get("durability") or {}

    conf_current = float(traj.get("confidence_current", 0.0))
    direction = traj.get("direction", "flat") or "flat"
    version_count = int(traj.get("version_count", 0))
    lean = debate.get("current_lean", "balanced") or "balanced"

    # Direction adjustment: ±0.08 on confidence scale
    _dir_adj: dict[str, float] = {
        "rising": 0.08, "falling": -0.08, "flat": 0.00, "unknown": 0.00,
    }
    dir_adj = _dir_adj.get(direction, 0.00)

    if version_count == 0:
        # No thesis history → return prior
        return _PRIOR_POS

    if forecast_type == "thesis_strengthening":
        return max(0.0, min(1.0, conf_current + dir_adj))

    if forecast_type == "thesis_weakening":
        return max(0.0, min(1.0, (1.0 - conf_current) - dir_adj))

    if forecast_type == "risk_emergence":
        _lean_score: dict[str, float] = {
            "bearish": 0.72, "balanced": 0.50, "bullish": 0.28,
        }
        lean_s = _lean_score.get(lean, 0.50)
        return max(0.0, min(1.0, lean_s * 0.5 + (1.0 - conf_current) * 0.5))

    if forecast_type == "catalyst_realization":
        prox = durability.get("catalyst_proximity_days", None)
        if prox is not None and prox <= 30:
            prox_signal = 0.80
        elif prox is not None and prox <= 60:
            prox_signal = 0.65
        elif prox is not None and prox <= 120:
            prox_signal = 0.45
        else:
            prox_signal = 0.30
        return max(0.0, min(1.0, conf_current * 0.40 + prox_signal * 0.60))

    if forecast_type == "similarity_outcome":
        # Thesis signal here is secondary; use peer-count proxy from feature
        peer_count = int(features.get("similarity_peer_count", 0))
        avg_score = float(features.get("similarity_avg_score", 0.0))
        if peer_count == 0:
            return _PRIOR_POS
        return max(0.0, min(1.0, avg_score * min(1.0, peer_count / 5.0)))

    if forecast_type == "regime_transition":
        rc = features.get("regime_context") or {}
        trend = rc.get("conviction_trend", "stable") or "stable"
        _trend_s: dict[str, float] = {
            "declining": 0.75, "stable": 0.50, "rising": 0.25, "unknown": 0.45,
        }
        return max(0.0, min(1.0, _trend_s.get(trend, 0.45)))

    return _PRIOR_POS


def _p_regime_signal(features: dict, forecast_type: str) -> float:
    """Regime context signal.

    Maps conviction_trend + cycle_position onto a 0–1 estimate for the
    positive direction of this forecast type.
    """
    rc = features.get("regime_context") or {}
    staleness = rc.get("staleness_state", "fresh") or "fresh"
    trend = rc.get("conviction_trend", "stable") or "stable"
    cycle = rc.get("cycle_position", "unknown") or "unknown"

    if staleness == "stale":
        return _PRIOR_POS  # no usable regime signal from stale data

    _bullish_trend: dict[str, float] = {
        "rising": 0.72, "stable": 0.50, "declining": 0.28, "unknown": 0.44,
    }
    _bearish_trend: dict[str, float] = {
        "declining": 0.72, "stable": 0.50, "rising": 0.28, "unknown": 0.44,
    }
    _bullish_cycle: dict[str, float] = {
        "early_cycle": 0.68, "mid_cycle": 0.55, "late_cycle": 0.32, "unknown": 0.44,
    }
    _bearish_cycle: dict[str, float] = {
        "late_cycle": 0.68, "mid_cycle": 0.52, "early_cycle": 0.32, "unknown": 0.44,
    }

    if forecast_type in ("thesis_strengthening", "catalyst_realization"):
        t = _bullish_trend.get(trend, 0.44)
        c = _bullish_cycle.get(cycle, 0.44)
        return (t + c) / 2.0

    if forecast_type in ("thesis_weakening", "risk_emergence"):
        t = _bearish_trend.get(trend, 0.44)
        c = _bearish_cycle.get(cycle, 0.44)
        return (t + c) / 2.0

    if forecast_type == "regime_transition":
        # Strongest signal when declining trend meets late cycle
        _trans_trend: dict[str, float] = {
            "declining": 0.80, "stable": 0.48, "rising": 0.22, "unknown": 0.44,
        }
        _trans_cycle: dict[str, float] = {
            "late_cycle": 0.80, "mid_cycle": 0.52, "early_cycle": 0.24, "unknown": 0.44,
        }
        t = _trans_trend.get(trend, 0.44)
        c = _trans_cycle.get(cycle, 0.44)
        return (t + c) / 2.0

    if forecast_type == "similarity_outcome":
        # Regime context is a mild modifier; neutral contribution
        t = _bullish_trend.get(trend, 0.44)
        return (t + 0.44) / 2.0

    return 0.44  # default


# ---------------------------------------------------------------------------
# Evidence strength
# ---------------------------------------------------------------------------

def _evidence_strength(features: dict) -> float:
    """Return a 0–1 scalar measuring how much substrate backs this forecast.

    Components:
      0.35 × analog_coverage   (saturates at 5 analogs)
      0.35 × peer_coverage     (saturates at 5 peers)
      0.30 × thesis_present    (1 if ≥1 thesis version exists, else 0)
    """
    analog_count = int(features.get("analog_count", 0))
    peer_count = int(features.get("similarity_peer_count", 0))
    thesis_versions = int(
        (features.get("thesis_trajectory") or {}).get("version_count", 0)
    )

    analog_cov = min(1.0, analog_count / 5.0)
    peer_cov = min(1.0, peer_count / 5.0)
    thesis_present = 1.0 if thesis_versions > 0 else 0.0

    return round(0.35 * analog_cov + 0.35 * peer_cov + 0.30 * thesis_present, 4)


# ---------------------------------------------------------------------------
# Staleness detection
# ---------------------------------------------------------------------------

def _is_stale(features: dict) -> bool:
    staleness = features.get("staleness_indicators") or {}
    regime = features.get("regime_context") or {}
    # Either explicit staleness flag or regime_context saying stale
    return (
        staleness.get("dossier_staleness_state", "fresh") == "stale"
        or regime.get("staleness_state", "fresh") == "stale"
    )


# ---------------------------------------------------------------------------
# Public pure functions
# ---------------------------------------------------------------------------

def normalize_distribution(raw_probs: dict) -> dict:
    """Clamp and renormalise a raw {positive, negative, neutral} dict.

    Clamping to [_P_MIN, _P_MAX] and renormalising ensures:
      - each value ∈ [0.01, 0.99]
      - values sum to 1.0
      - no NaN / infinity survives

    Args:
        raw_probs: dict with keys "positive", "negative", "neutral".
                   Missing keys default to 0.0.

    Returns:
        Normalised dict with the same three keys.

    Raises:
        ValueError: if all three components are zero (degenerate input).
    """
    pos = float(raw_probs.get("positive", 0.0))
    neg = float(raw_probs.get("negative", 0.0))
    neu = float(raw_probs.get("neutral", 0.0))

    # Reject non-finite inputs
    if any(math.isnan(v) or math.isinf(v) for v in (pos, neg, neu)):
        raise ValueError(
            f"normalize_distribution: non-finite inputs pos={pos} neg={neg} neu={neu}"
        )

    # Clamp before normalise
    pos = max(_P_MIN, min(_P_MAX, pos))
    neg = max(_P_MIN, min(_P_MAX, neg))
    neu = max(_P_MIN, min(_P_MAX, neu))

    total = pos + neg + neu
    if total < 1e-9:
        raise ValueError("normalize_distribution: all components are zero")

    return {
        "positive": round(pos / total, 6),
        "negative": round(neg / total, 6),
        "neutral": round(neu / total, 6),
    }


def confidence_band_from_evidence(
    features: dict,
    p_positive: float,
    horizon_days: int,
) -> tuple[float, float]:
    """Return (low, high) confidence band around p_positive.

    Band half-width:
      base = 0.20 − 0.15 × evidence_strength   → range [0.05, 0.20]
      + staleness_expansion (0.08 if stale)
      + horizon_expansion   (0, 0.03, 0.07 for 30, 90, 180)
    Band is clamped to [0, 1].

    More evidence → narrower band.
    Stale substrate → wider band.
    Longer horizon → wider band.
    """
    strength = _evidence_strength(features)
    stale = _is_stale(features)

    base_half = 0.20 - 0.15 * strength          # ∈ [0.05, 0.20]
    stale_exp = 0.08 if stale else 0.0
    horizon_exp = _HORIZON_EXPANSION.get(horizon_days, 0.05)

    half = base_half + stale_exp + horizon_exp

    low = max(0.0, round(p_positive - half, 4))
    high = min(1.0, round(p_positive + half, 4))
    return low, high


def validate_forecast_distribution(distribution: dict) -> bool:
    """Return True iff the distribution is well-formed.

    Checks:
      - p_positive, p_negative, p_neutral all present
      - each ∈ [0, 1]
      - no NaN / infinity
      - sum ∈ [0.999, 1.001]
    """
    try:
        pos = float(distribution.get("p_positive", float("nan")))
        neg = float(distribution.get("p_negative", float("nan")))
        neu = float(distribution.get("p_neutral", float("nan")))
    except (TypeError, ValueError):
        return False

    if any(math.isnan(v) or math.isinf(v) for v in (pos, neg, neu)):
        return False
    if any(v < 0.0 or v > 1.0 for v in (pos, neg, neu)):
        return False
    if not (0.999 <= pos + neg + neu <= 1.001):
        return False
    return True


# ---------------------------------------------------------------------------
# Internal scoring core
# ---------------------------------------------------------------------------

def _renorm_weights(w: dict[str, float]) -> dict[str, float]:
    total = sum(w.values())
    if total < 1e-9:
        # Degenerate: return equal weights
        n = len(w)
        return {k: 1.0 / n for k in w}
    return {k: v / total for k, v in w.items()}


def _confidence_label(strength: float, stale: bool) -> str:
    if stale or strength < 0.30:
        return "low"
    if strength < 0.62:
        return "medium"
    return "high"


def _score_core(
    features: dict,
    forecast_type: str,
    horizon_days: int,
    *,
    stage_modifier: float = 1.0,
) -> dict:
    """Internal shared scoring logic for both T1 and T4.

    stage_modifier: multiplied on p_positive before distribution construction.
    T4 callers pass the failure-mode sequence-stage modifier; T1 passes 1.0.
    """
    if forecast_type not in SUPPORTED_FORECAST_TYPES:
        raise ValueError(
            f"Unsupported forecast_type '{forecast_type}'. "
            f"Supported: {sorted(SUPPORTED_FORECAST_TYPES)}"
        )
    if horizon_days not in SUPPORTED_HORIZONS:
        raise ValueError(
            f"Unsupported horizon_days {horizon_days}. "
            f"Supported: {sorted(SUPPORTED_HORIZONS)}"
        )

    weights = _renorm_weights(_WEIGHTS[forecast_type])

    # Component signals
    p_base = _p_base_rate(features, forecast_type)
    p_sim = _p_sim_peer(features, forecast_type)
    p_thesis = _p_thesis_signal(features, forecast_type)
    p_regime = _p_regime_signal(features, forecast_type)

    # Ensemble
    p_positive_raw = (
        weights["base"]   * p_base
        + weights["sim"]    * p_sim
        + weights["thesis"] * p_thesis
        + weights["regime"] * p_regime
    )

    # Apply stage modifier (T4 only; T1 passes 1.0)
    p_positive_raw = max(0.0, min(1.0, p_positive_raw * stage_modifier))

    # Staleness pull toward prior
    stale = _is_stale(features)
    if stale:
        pull = _STALENESS_PULL
        p_positive_raw = (1.0 - pull) * p_positive_raw + pull * _PRIOR_POS

    # Build 3-way distribution
    neg_frac, neu_frac = _RESIDUAL_SPLIT[forecast_type]
    residual = 1.0 - p_positive_raw
    p_negative_raw = residual * neg_frac
    p_neutral_raw = residual * neu_frac

    normalised = normalize_distribution({
        "positive": p_positive_raw,
        "negative": p_negative_raw,
        "neutral": p_neutral_raw,
    })

    p_pos = normalised["positive"]
    p_neg = normalised["negative"]
    p_neu = normalised["neutral"]

    # Confidence band around p_positive
    conf_low, conf_high = confidence_band_from_evidence(features, p_pos, horizon_days)

    # Evidence strength and label
    strength = _evidence_strength(features)

    distribution = {
        "p_positive": p_pos,
        "p_negative": p_neg,
        "p_neutral": p_neu,
        "confidence_low": conf_low,
        "confidence_high": conf_high,
        "confidence_label": _confidence_label(strength, stale),
        "horizon_days": horizon_days,
        "forecast_type": forecast_type,
        "components": {
            "p_base_rate": round(p_base, 6),
            "p_sim_peer": round(p_sim, 6),
            "p_thesis_signal": round(p_thesis, 6),
            "p_regime_signal": round(p_regime, 6),
            "weights_used": {k: round(v, 4) for k, v in weights.items()},
        },
        "evidence_strength": strength,
        "staleness_penalty_applied": stale,
        "engine_schema": ENGINE_SCHEMA_VERSION,
    }

    assert validate_forecast_distribution(distribution), (
        f"Engine produced invalid distribution: {distribution}"
    )
    return distribution


# ---------------------------------------------------------------------------
# T4 stage modifier
# ---------------------------------------------------------------------------

def _stage_modifier(features: dict) -> float:
    """Return a multiplier on p_positive for T4 failure-mode forecasts.

    Sequence stage captures how far along a failure-mode progression the
    entity is:
      stage 1 (early)    → pull toward prior (0.85×)
      stage 2 (mid)      → no adjustment (1.00×)
      stage 3+ (advanced)→ boost probability (1.12×, max 0.99)
    """
    fm = features.get("failure_mode") or {}
    stage = int(fm.get("sequence_stage", 2))
    if stage <= 1:
        return 0.85
    if stage >= 3:
        return 1.12
    return 1.00


# ---------------------------------------------------------------------------
# Public scoring entry points
# ---------------------------------------------------------------------------

def score_company_forecast(
    features: dict,
    forecast_type: str,
    horizon_days: int,
) -> dict:
    """Score a T1 (company) forecast.

    Args:
        features:      Feature dict from build_company_forecast_features.
                       If None or empty → conservative (prior) output.
        forecast_type: One of SUPPORTED_FORECAST_TYPES.
        horizon_days:  One of SUPPORTED_HORIZONS.

    Returns:
        Output dict with p_positive/p_negative/p_neutral + metadata.
        All values are finite, each probability ∈ [0.01, 0.99], sum = 1.0.

    Raises:
        ValueError: for unsupported forecast_type or horizon_days.
    """
    # Validate type/horizon first (raises on bad input)
    if forecast_type not in SUPPORTED_FORECAST_TYPES:
        raise ValueError(
            f"Unsupported forecast_type '{forecast_type}'. "
            f"Supported: {sorted(SUPPORTED_FORECAST_TYPES)}"
        )
    if horizon_days not in SUPPORTED_HORIZONS:
        raise ValueError(
            f"Unsupported horizon_days {horizon_days}. "
            f"Supported: {sorted(SUPPORTED_HORIZONS)}"
        )

    if not features:
        return _empty_output(forecast_type, horizon_days)

    return _score_core(features, forecast_type, horizon_days, stage_modifier=1.0)


def score_failure_mode_forecast(
    features: dict,
    forecast_type: str,
    horizon_days: int,
) -> dict:
    """Score a T4 (failure_mode) forecast.

    Same semantics as score_company_forecast but additionally applies a
    sequence-stage modifier (§T4 spec): stage 1 pulls toward prior, stage 3+
    boosts the event probability.

    Args:
        features:      Feature dict from build_failure_mode_forecast_features.
                       If None or empty → conservative (prior) output.
        forecast_type: One of SUPPORTED_FORECAST_TYPES.
        horizon_days:  One of SUPPORTED_HORIZONS.

    Returns:
        Output dict with p_positive/p_negative/p_neutral + metadata.

    Raises:
        ValueError: for unsupported forecast_type or horizon_days.
    """
    if forecast_type not in SUPPORTED_FORECAST_TYPES:
        raise ValueError(
            f"Unsupported forecast_type '{forecast_type}'. "
            f"Supported: {sorted(SUPPORTED_FORECAST_TYPES)}"
        )
    if horizon_days not in SUPPORTED_HORIZONS:
        raise ValueError(
            f"Unsupported horizon_days {horizon_days}. "
            f"Supported: {sorted(SUPPORTED_HORIZONS)}"
        )

    if not features:
        return _empty_output(forecast_type, horizon_days)

    modifier = _stage_modifier(features)
    return _score_core(features, forecast_type, horizon_days, stage_modifier=modifier)
