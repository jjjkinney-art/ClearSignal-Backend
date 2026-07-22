"""Decision-threshold invariants (Sprint 1B, issue #2).

A bull/neutral/bear decision band must be non-overlapping and directionally
coherent.  Metrics where *lower is better* (P/E, EV/EBITDA) are handled
separately from metrics where *higher is better* (growth, margins, ROIC).

Observed bug: Visa "bull P/E < 31x" and "bear P/E > 28x" overlap — a 29x P/E is
simultaneously bull and bear.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class MetricDirection(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"   # growth, margin, ROIC
    LOWER_IS_BETTER = "lower_is_better"     # P/E, EV/EBITDA, leverage


@dataclass
class ThresholdBand:
    """A three-way decision band on a single metric.

    Semantics (both directions):
      * ``bull_threshold`` — the metric value at the bull/neutral boundary.
      * ``bear_threshold`` — the metric value at the neutral/bear boundary.

    For LOWER_IS_BETTER (e.g. P/E): bullish = metric <= bull_threshold, bearish =
    metric >= bear_threshold, so coherence requires ``bull_threshold <=
    bear_threshold`` (strictly, to leave a non-empty neutral band, <).

    For HIGHER_IS_BETTER (e.g. growth %): bullish = metric >= bull_threshold,
    bearish = metric <= bear_threshold, so coherence requires ``bull_threshold >=
    bear_threshold``.
    """
    metric: str
    direction: MetricDirection
    bull_threshold: float
    bear_threshold: float

    def classify(self, value: float) -> str:
        if self.direction is MetricDirection.LOWER_IS_BETTER:
            if value <= self.bull_threshold:
                return "bull"
            if value >= self.bear_threshold:
                return "bear"
            return "neutral"
        # higher is better
        if value >= self.bull_threshold:
            return "bull"
        if value <= self.bear_threshold:
            return "bear"
        return "neutral"


def validate_band(band: ThresholdBand) -> List[str]:
    """Return a list of invariant violations for a single band (empty = valid)."""
    v: List[str] = []
    if band.direction is MetricDirection.LOWER_IS_BETTER:
        # bullish region (<= bull) and bearish region (>= bear) must not overlap;
        # need bull < bear for a non-empty neutral interval.
        if band.bull_threshold >= band.bear_threshold:
            v.append(
                f"{band.metric}: lower-is-better band overlaps/inverts — bull "
                f"threshold {band.bull_threshold} must be < bear threshold "
                f"{band.bear_threshold} (values in "
                f"[{band.bear_threshold}, {band.bull_threshold}] are both bull and bear)"
            )
    else:
        if band.bull_threshold <= band.bear_threshold:
            v.append(
                f"{band.metric}: higher-is-better band overlaps/inverts — bull "
                f"threshold {band.bull_threshold} must be > bear threshold "
                f"{band.bear_threshold}"
            )
    return v


def validate_bands(bands: List[ThresholdBand]) -> List[str]:
    out: List[str] = []
    for b in bands:
        out.extend(validate_band(b))
    return out


def infer_direction(metric: str) -> Optional[MetricDirection]:
    """Best-effort direction for a named metric (used when validating raw fixtures)."""
    m = metric.lower()
    lower = ("p/e", "pe", "ev/ebitda", "ev/sales", "price/", "leverage",
             "debt", "multiple", "payback")
    higher = ("growth", "margin", "roic", "roe", "yield", "fcf", "share gain",
              "retention", "attach")
    if any(k in m for k in lower):
        return MetricDirection.LOWER_IS_BETTER
    if any(k in m for k in higher):
        return MetricDirection.HIGHER_IS_BETTER
    return None
