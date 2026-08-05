"""Structured decision-threshold construction from free-form LLM output (Sprint 1C).

The synthesis LLM emits ``ThresholdZone`` objects with free-form strings like
``bull_threshold=">25%"`` / ``bear_threshold="<15%"`` (schemas.py:1020). This
module parses those strings into a numeric, direction-aware, validated
``ThresholdBand`` (app/integrity/thresholds.py, unchanged/frozen) or returns an
explicit "unavailable" result — it NEVER invents a coherent threshold when the
LLM's output cannot be safely parsed or is internally contradictory (e.g. the
Visa bull<31x / bear>28x overlap).

Kept separate from ``thresholds.py`` so Sprint 1B's tested ThresholdBand /
validate_band logic is not touched.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .thresholds import ThresholdBand, MetricDirection, validate_band, infer_direction

_NUM_RE = re.compile(
    r"(?P<op><=|>=|<|>)?\s*\$?\s?(?P<val>\d[\d,]*\.?\d*)\s?(?P<unit>%|x|bp|bps|B|M|K)?",
    re.IGNORECASE,
)

# ── Sprint 2B — unit inference from metric semantics ─────────────────────────
# Sprint 2A shipped 7 thresholds with a null unit ("Vehicle Deliveries",
# "Brent Crude Price", "737 MAX Monthly Production Rate", ...). The LLM writes
# thresholds like ">1.8M" or ">$70" where the unit is implied by the METRIC
# NAME, not the value string. These patterns recover that implied unit.
#
# Ordered most-specific first; the first match wins. A metric that matches
# nothing keeps ``unit=None`` — inventing a unit for a genuinely ambiguous
# metric would be worse than admitting it is missing.
_UNIT_INFERENCE = tuple(
    (re.compile(pattern, re.IGNORECASE), unit)
    for pattern, unit in (
        # Commodity prices — priced per barrel by universal convention.
        (r"\b(?:brent|wti)\b|crude\s*oil|\bcrude\b", "USD/bbl"),
        (r"\bnatural\s*gas\b|\bhenry\s*hub\b", "USD/mmbtu"),
        # Average selling price — a currency amount per unit sold.
        (r"\basp\b|average\s+selling\s+price", "USD"),
        # Production rate — rate metrics carry a period in the metric name.
        (r"production\s+rate", "aircraft/month"),
        # Shipments of capital equipment (ASML EUV/DUV systems).
        (r"\b(?:euv|duv)\b.*shipment|shipment.*\b(?:euv|duv)\b", "systems"),
        # Vehicle deliveries.
        (r"vehicle\s+deliver|deliveries", "vehicles"),
        # Generic unit shipments/volumes.
        (r"\bshipments?\b|\bunit\s+volume", "units"),
        (r"\bsubscribers?\b|\bmau\b|\bdau\b", "users"),
        (r"\bstore\s+count\b|\bstores\b", "stores"),
    )
)

# Period qualifiers in a metric name, appended to a countable inferred unit so
# "Quarterly EUV Shipments" reads "systems/quarter" rather than bare "systems".
_PERIOD_PATTERNS = tuple(
    (re.compile(pattern, re.IGNORECASE), period)
    for pattern, period in (
        (r"\bper\s+quarter\b|\bquarterly\b|\bq/q\b", "quarter"),
        (r"\bper\s+month\b|\bmonthly\b|\bper\s+mo\b", "month"),
        (r"\bper\s+year\b|\bannual\b|\byearly\b|\bper\s+annum\b", "year"),
        (r"\bper\s+week\b|\bweekly\b", "week"),
    )
)

# Units that are already rates (contain a slash) or are currency amounts must
# not have a period appended.
_COUNTABLE_UNITS = {"vehicles", "systems", "units", "users", "stores"}


def infer_unit(metric: str) -> Optional[str]:
    """Infer a threshold's unit from its metric name, or None when the metric
    is genuinely ambiguous.

    Only semantics that are unambiguous by industry convention are encoded —
    "Brent Crude Price" is always USD per barrel; "Vehicle Deliveries" is
    always a vehicle count. Anything else returns None so the caller can mark
    the unit explicitly missing rather than fabricate one.
    """
    if not metric:
        return None
    for pattern, unit in _UNIT_INFERENCE:
        if pattern.search(metric):
            if unit in _COUNTABLE_UNITS:
                for period_pattern, period in _PERIOD_PATTERNS:
                    if period_pattern.search(metric):
                        return f"{unit}/{period}"
            return unit
    return None


def _parse_side(text: str) -> Optional[Dict[str, Any]]:
    """Parse one threshold side (e.g. '<31x', '>$40B', '>25%') into
    {op, value, unit}. Returns None if unparseable."""
    if not text:
        return None
    m = _NUM_RE.search(text.strip())
    if not m or not m.group("val"):
        return None
    try:
        value = float(m.group("val").replace(",", ""))
    except ValueError:
        return None
    op = m.group("op") or ("<" if text.strip().startswith("<") else
                           ">" if text.strip().startswith(">") else None)
    unit = (m.group("unit") or "").lower() or None
    return {"op": op, "value": value, "unit": unit}


def parse_threshold_zone(
    zone: Any, *, ticker: str, freshness_as_of: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse one ThresholdZone (object or dict) into a structured, VALIDATED
    decision-threshold dict, or an explicit unavailable dict with a reason.

    Never raises; never returns a silently-invented coherent band when the
    input cannot be safely parsed or is contradictory.
    """
    metric = (getattr(zone, "metric", None) or (zone.get("metric") if isinstance(zone, dict) else None) or "").strip()
    bull_raw = getattr(zone, "bull_threshold", None) or (zone.get("bull_threshold") if isinstance(zone, dict) else None) or ""
    bear_raw = getattr(zone, "bear_threshold", None) or (zone.get("bear_threshold") if isinstance(zone, dict) else None) or ""
    rationale = getattr(zone, "rationale", None) or (zone.get("rationale") if isinstance(zone, dict) else None) or ""

    def _unavailable(reason: str) -> Dict[str, Any]:
        return {
            "metric": metric or "unknown metric",
            "ticker": ticker,
            "unavailable": True,
            "reason": reason,
            "display": "Threshold unavailable",
            "raw_bull": bull_raw,
            "raw_bear": bear_raw,
        }

    if not metric:
        return _unavailable("no metric name supplied")

    bull = _parse_side(bull_raw)
    bear = _parse_side(bear_raw)
    if bull is None or bear is None:
        return _unavailable(
            f"could not parse numeric threshold from bull={bull_raw!r} / bear={bear_raw!r}"
        )

    if bull["unit"] != bear["unit"]:
        return _unavailable(
            f"unit mismatch between bull ({bull['unit']!r}) and bear ({bear['unit']!r})"
        )
    unit = bull["unit"]
    # Sprint 2B — the LLM often encodes the unit in the metric name rather than
    # the threshold string (">1.8M" for "Vehicle Deliveries"). Recover it, but
    # never override a unit the threshold string stated explicitly.
    unit_inferred = False
    if not unit:
        inferred = infer_unit(metric)
        if inferred:
            unit, unit_inferred = inferred, True

    direction = infer_direction(metric)
    if direction is None:
        # Fall back to inferring direction from the comparison operators used.
        if bull["op"] == "<" and bear["op"] == ">":
            direction = MetricDirection.LOWER_IS_BETTER
        elif bull["op"] == ">" and bear["op"] == "<":
            direction = MetricDirection.HIGHER_IS_BETTER
        else:
            return _unavailable(
                f"cannot infer metric direction for {metric!r} from operators "
                f"bull={bull['op']!r} bear={bear['op']!r}"
            )

    band = ThresholdBand(
        metric=metric, direction=direction,
        bull_threshold=bull["value"], bear_threshold=bear["value"],
    )
    violations = validate_band(band)
    if violations:
        return _unavailable("; ".join(violations))

    lo, hi = sorted((bull["value"], bear["value"]))
    # Symbolic units ("%", "x") abut the number; word units ("vehicles",
    # "USD/bbl") need a separating space to stay readable.
    suffix = "" if not unit else (unit if unit in ("%", "x") else f" {unit}")
    return {
        "metric": metric,
        "ticker": ticker,
        "unavailable": False,
        "unit": unit,
        "unit_inferred": unit_inferred,
        "unit_missing_reason": (
            None if unit else
            f"no unit in the threshold text and none inferable from metric {metric!r}"
        ),
        "direction": direction.value,
        "bull_boundary": bull["value"],
        "bear_boundary": bear["value"],
        "neutral_interval": [lo, hi],
        # Free-form LLM rationale becomes the derivation/assumptions text —
        # DERIVED when it states a mechanism, HEURISTIC otherwise (conservative).
        "provenance": "derived" if rationale else "heuristic",
        "assumptions": rationale or None,
        "confidence": "medium" if rationale else "low",
        "as_of": freshness_as_of,
        "display": f"Bull >{bull['value']}{suffix} · Bear <{bear['value']}{suffix}"
                   if direction is MetricDirection.HIGHER_IS_BETTER
                   else f"Bull <{bull['value']}{suffix} · Bear >{bear['value']}{suffix}",
    }


def build_decision_thresholds(
    zones: Any, *, ticker: str, freshness_as_of: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Parse a list of ThresholdZone objects/dicts into structured thresholds.
    Never raises; each entry is either a valid band or an explicit unavailable dict."""
    if not zones:
        return []
    out = []
    for z in zones:
        try:
            out.append(parse_threshold_zone(z, ticker=ticker, freshness_as_of=freshness_as_of))
        except Exception as exc:
            out.append({
                "metric": getattr(z, "metric", "unknown"),
                "ticker": ticker, "unavailable": True,
                "reason": f"parse error: {exc!r}", "display": "Threshold unavailable",
            })
    return out
