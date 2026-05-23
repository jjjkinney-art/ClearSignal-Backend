"""
Thesis drift detection — InvestmentThesis native.

Compares two InvestmentThesis objects (current vs prior) and returns a
structured InvestmentThesisDrift describing what materially changed.
Unlike the legacy ``thesis_change_logic.py`` (which targets SynthesisOutput),
this module operates directly on the conviction-modeler pipeline output.

Design constraints
------------------
- No LLM calls.  All logic is deterministic comparison.
- Noise suppression: minor wording changes that do not cross a structural
  threshold are NOT flagged.
- Produces institutional-quality prose in thesis_drift_summary.

Drift taxonomy
--------------
STANCE_SHIFT          valuation_stance changed (e.g. "fairly_valued" → "overpriced")
SETUP_DOWNGRADE       setup_label moved toward lower conviction
SETUP_UPGRADE         setup_label moved toward higher conviction
CONVICTION_DROP       confidence_score fell by ≥ CONVICTION_THRESHOLD
CONVICTION_RISE       confidence_score rose by ≥ CONVICTION_THRESHOLD
DRIVER_SHIFT          dominant_driver changed materially
RISK_REGIME_CHANGE    dominant risk characterization changed
DIMENSION_SHIFT       conviction_dimensions: a key sub-score moved by ≥ DIM_THRESHOLD

Noise suppression rules
-----------------------
- confidence_score delta < 0.06 → no CONVICTION_DROP/RISE
- dominant_driver edits < 40% token difference → no DRIVER_SHIFT
- wording-only dimension changes < 0.08 → no DIMENSION_SHIFT

Usage
-----
    from app.services.thesis_drift import detect_investment_thesis_drift

    drift = detect_investment_thesis_drift(current_thesis, prior_thesis)
    if drift.has_drift:
        print(drift.thesis_drift_summary)
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

from ..schemas import InvestmentThesis


# ── Noise suppression thresholds ──────────────────────────────────────────────

_CONVICTION_THRESHOLD: float = 0.06   # min delta to flag conviction change
_DIM_THRESHOLD:        float = 0.08   # min delta to flag dimension shift
_DRIVER_JACCARD_MAX:   float = 0.60   # above this → strings are similar → no flag


# ── Setup label ordering ──────────────────────────────────────────────────────
# Lower index = higher conviction.  Used to determine upgrade vs downgrade.

_SETUP_LABEL_ORDER = [
    "high-alignment thesis",   # 0 — best
    "actionable thesis",       # 1
    "monitoring required",     # 2
    "expectation-sensitive",   # 3
    "mixed evidence",          # 4
    "fragile setup",           # 5
    "low-conviction setup",    # 6
    "speculative setup",       # 7
    "speculative",             # 8
    "data-limited",            # 9
    "structurally impaired",   # 10 — worst
    "insufficient conviction", # 11
]

_SETUP_RANK: Dict[str, int] = {label: i for i, label in enumerate(_SETUP_LABEL_ORDER)}


# ── Drift type constants ──────────────────────────────────────────────────────

DRIFT_STANCE_SHIFT      = "STANCE_SHIFT"
DRIFT_SETUP_DOWNGRADE   = "SETUP_DOWNGRADE"
DRIFT_SETUP_UPGRADE     = "SETUP_UPGRADE"
DRIFT_CONVICTION_DROP   = "CONVICTION_DROP"
DRIFT_CONVICTION_RISE   = "CONVICTION_RISE"
DRIFT_DRIVER_SHIFT      = "DRIVER_SHIFT"
DRIFT_RISK_REGIME       = "RISK_REGIME_CHANGE"
DRIFT_DIMENSION_SHIFT   = "DIMENSION_SHIFT"


# ── Data structure ────────────────────────────────────────────────────────────

@dataclasses.dataclass
class InvestmentThesisDrift:
    """Structured delta between two InvestmentThesis objects.

    Attributes
    ----------
    has_drift        : True when at least one material change was detected.
    drift_types      : List of DRIFT_* constants for each detected change.
    conviction_delta : Signed delta (current − prior) confidence_score.
    setup_label_prior   : setup_label of the prior thesis.
    setup_label_current : setup_label of the current thesis.
    prior_dominant_driver   : dominant_driver from the prior thesis.
    current_dominant_driver : dominant_driver from the current thesis.
    dimension_shifts : Dict mapping dimension name → (prior_val, current_val, delta).
    thesis_drift_summary : Institutional-quality prose description of the drift.
    drift_severity   : "low" | "medium" | "high"
    changed_fields   : List of field names that changed (for API consumers).
    """
    has_drift:              bool
    drift_types:            List[str]
    conviction_delta:       float
    setup_label_prior:      str
    setup_label_current:    str
    prior_dominant_driver:  str
    current_dominant_driver: str
    dimension_shifts:       Dict[str, tuple]   # name → (prior, current, delta)
    thesis_drift_summary:   str
    drift_severity:         str                # "low" | "medium" | "high"
    changed_fields:         List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_drift":              self.has_drift,
            "drift_types":            self.drift_types,
            "conviction_delta":       round(self.conviction_delta, 4),
            "setup_label_prior":      self.setup_label_prior,
            "setup_label_current":    self.setup_label_current,
            "prior_dominant_driver":  self.prior_dominant_driver,
            "current_dominant_driver": self.current_dominant_driver,
            "dimension_shifts":       {k: list(v) for k, v in self.dimension_shifts.items()},
            "thesis_drift_summary":   self.thesis_drift_summary,
            "drift_severity":         self.drift_severity,
            "changed_fields":         self.changed_fields,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _jaccard(a: str, b: str) -> float:
    """Token-level Jaccard similarity between two strings."""
    sa, sb = set(a.lower().split()), set(b.lower().split())
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _setup_rank(label: str) -> int:
    """Return rank of a setup label (lower = stronger conviction)."""
    return _SETUP_RANK.get(label.lower().strip(), 5)  # default = middle tier


def _stance_label(stance: str) -> str:
    """Normalise valuation_stance for comparison."""
    return (stance or "").lower().strip().replace("_", " ")


# ── Core detection logic ──────────────────────────────────────────────────────

def detect_investment_thesis_drift(
    current: InvestmentThesis,
    prior:   InvestmentThesis,
) -> InvestmentThesisDrift:
    """Compare current and prior InvestmentThesis and return drift analysis.

    Parameters
    ----------
    current : The newly generated InvestmentThesis.
    prior   : The previously stored InvestmentThesis for the same ticker.

    Returns
    -------
    InvestmentThesisDrift with structured delta and institutional summary.
    Raises no exceptions — defaults to has_drift=False on any error.
    """
    drift_types:   List[str] = []
    changed_fields: List[str] = []
    summary_parts:  List[str] = []

    ticker = (current.ticker or "the company").upper()

    # ── 1. Conviction delta ───────────────────────────────────────────────────
    conviction_delta = (current.confidence_score or 0.0) - (prior.confidence_score or 0.0)
    if abs(conviction_delta) >= _CONVICTION_THRESHOLD:
        if conviction_delta < 0:
            drift_types.append(DRIFT_CONVICTION_DROP)
            changed_fields.append("confidence_score")
            summary_parts.append(
                f"Conviction on {ticker} weakened by {abs(conviction_delta):.0%} — "
                "the evidence base or setup quality deteriorated materially."
            )
        else:
            drift_types.append(DRIFT_CONVICTION_RISE)
            changed_fields.append("confidence_score")
            summary_parts.append(
                f"Conviction on {ticker} strengthened by {conviction_delta:.0%} — "
                "improved evidence quality or a more favorable setup."
            )

    # ── 2. Setup label change ─────────────────────────────────────────────────
    prior_label   = (prior.setup_label or "actionable thesis").lower().strip()
    current_label = (current.setup_label or "actionable thesis").lower().strip()
    prior_rank    = _setup_rank(prior_label)
    current_rank  = _setup_rank(current_label)

    if prior_label != current_label:
        changed_fields.append("setup_label")
        if current_rank > prior_rank:
            drift_types.append(DRIFT_SETUP_DOWNGRADE)
            summary_parts.append(
                f"Setup downgraded from '{prior_label}' to '{current_label}' — "
                f"the analytical framework for {ticker} is now less actionable."
            )
        else:
            drift_types.append(DRIFT_SETUP_UPGRADE)
            summary_parts.append(
                f"Setup upgraded from '{prior_label}' to '{current_label}' — "
                f"the {ticker} thesis is now more defensible."
            )

    # ── 3. Valuation stance shift ─────────────────────────────────────────────
    prior_stance   = _stance_label(getattr(prior, "valuation_stance", "") or "")
    current_stance = _stance_label(getattr(current, "valuation_stance", "") or "")
    if prior_stance and current_stance and prior_stance != current_stance:
        drift_types.append(DRIFT_STANCE_SHIFT)
        changed_fields.append("valuation_stance")
        summary_parts.append(
            f"Valuation stance shifted from '{prior_stance}' to '{current_stance}' — "
            f"the market regime or earnings trajectory for {ticker} materially changed."
        )

    # ── 4. Dominant driver shift ──────────────────────────────────────────────
    prior_driver   = (getattr(prior, "dominant_driver", "") or "").strip()
    current_driver = (getattr(current, "dominant_driver", "") or "").strip()
    if prior_driver and current_driver:
        sim = _jaccard(prior_driver, current_driver)
        if sim < (1.0 - _DRIVER_JACCARD_MAX):
            drift_types.append(DRIFT_DRIVER_SHIFT)
            changed_fields.append("dominant_driver")
            summary_parts.append(
                f"Primary debate shifted from '{prior_driver}' "
                f"toward '{current_driver}'."
            )

    # ── 5. Conviction dimension shifts ────────────────────────────────────────
    prior_dims   = getattr(prior, "conviction_dimensions", None) or {}
    current_dims = getattr(current, "conviction_dimensions", None) or {}
    dimension_shifts: Dict[str, tuple] = {}

    _DIM_LABELS = {
        "evidence_freshness": "evidence freshness",
        "valuation_certainty": "valuation certainty",
        "macro_uncertainty": "macro uncertainty",
        "expectation_fragility": "expectation fragility",
        "thesis_alignment": "thesis alignment",
        "estimate_dispersion": "estimate dispersion",
    }

    for dim_key, dim_label in _DIM_LABELS.items():
        p_val = float(prior_dims.get(dim_key, 0.0) or 0.0)
        c_val = float(current_dims.get(dim_key, 0.0) or 0.0)
        delta = c_val - p_val
        if abs(delta) >= _DIM_THRESHOLD:
            dimension_shifts[dim_key] = (p_val, c_val, delta)
            if dim_key not in [f.split(".")[0] for f in changed_fields]:
                changed_fields.append(f"conviction_dimensions.{dim_key}")
            if DRIFT_DIMENSION_SHIFT not in drift_types:
                drift_types.append(DRIFT_DIMENSION_SHIFT)

    # Build dimension shift prose (only the two largest movers)
    if dimension_shifts:
        top_shifts = sorted(dimension_shifts.items(), key=lambda x: abs(x[1][2]), reverse=True)[:2]
        for dim_key, (p_val, c_val, delta) in top_shifts:
            label = _DIM_LABELS.get(dim_key, dim_key)
            direction = "increased" if delta > 0 else "decreased"
            summary_parts.append(
                f"{label.title()} {direction} materially ({p_val:.2f} → {c_val:.2f}) — "
                f"the {ticker} setup shifted on this dimension."
            )

    # ── 6. Risk regime detection via key_risks comparison ────────────────────
    prior_risks   = [r.lower() for r in (getattr(prior, "key_risks", []) or [])]
    current_risks = [r.lower() for r in (getattr(current, "key_risks", []) or [])]
    if prior_risks and current_risks:
        # New dominant risks that weren't in the prior top 2
        prior_top = set(prior_risks[:2])
        current_top = set(current_risks[:2])
        # Check if top risk changed — use Jaccard on top-risk tokens
        prior_top_str   = " ".join(sorted(prior_top))
        current_top_str = " ".join(sorted(current_top))
        if prior_top_str and current_top_str and _jaccard(prior_top_str, current_top_str) < 0.30:
            drift_types.append(DRIFT_RISK_REGIME)
            changed_fields.append("key_risks")
            summary_parts.append(
                f"Risk regime shifted for {ticker} — the dominant risk characterization "
                "is materially different from the prior assessment."
            )

    # ── 7. Compose institutional drift summary ────────────────────────────────
    has_drift = bool(drift_types)

    if not has_drift:
        thesis_drift_summary = (
            f"No material drift detected for {ticker} — the setup, conviction level, "
            "and primary debate remain consistent with the prior assessment."
        )
        drift_severity = "none"
    else:
        thesis_drift_summary = " ".join(summary_parts)

        # Severity scoring
        score = 0.0
        if DRIFT_STANCE_SHIFT in drift_types:    score += 3.0
        if DRIFT_SETUP_DOWNGRADE in drift_types: score += 2.5
        if DRIFT_SETUP_UPGRADE in drift_types:   score += 1.5
        if DRIFT_CONVICTION_DROP in drift_types: score += 2.0 + abs(conviction_delta) * 5
        if DRIFT_CONVICTION_RISE in drift_types: score += 1.0
        if DRIFT_DRIVER_SHIFT in drift_types:    score += 2.0
        if DRIFT_RISK_REGIME in drift_types:     score += 2.5
        if DRIFT_DIMENSION_SHIFT in drift_types: score += 0.5 * len(dimension_shifts)

        if score >= 6.0:
            drift_severity = "high"
        elif score >= 2.0:   # setup changes (2.5) and minor conviction moves qualify
            drift_severity = "medium"
        else:
            drift_severity = "low"

    return InvestmentThesisDrift(
        has_drift=has_drift,
        drift_types=drift_types,
        conviction_delta=conviction_delta,
        setup_label_prior=prior_label,
        setup_label_current=current_label,
        prior_dominant_driver=prior_driver,
        current_dominant_driver=current_driver,
        dimension_shifts=dimension_shifts,
        thesis_drift_summary=thesis_drift_summary,
        drift_severity=drift_severity if has_drift else "none",
        changed_fields=changed_fields,
    )
