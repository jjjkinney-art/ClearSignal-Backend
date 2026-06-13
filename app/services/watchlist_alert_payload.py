"""
Canonical watchlist alert payload — Phase 10B · Slice 4.

Defines ``WatchlistAlertPayload``, the single authoritative alert schema for
the ClearSignal intelligence loop.  Legacy alert types (WatchAlert, Alert,
MaterialChangeEvent, AlertPriority) are preserved unchanged; adapter functions
project each one into the canonical payload without mutation.

Design goals
------------
* One schema, one version counter (payload_version=1).
* Required keys always present; optional keys default to None/empty — adapters
  never raise on missing source fields.
* Severity is normalized to a five-level scale:
    critical → high → medium → low → info
* alert_type is normalized to UPPER_SNAKE_CASE canonical constants.
* Deterministic serialization: to_dict() and to_json() are stable across calls.
* Source identity is preserved in ``source`` (string) and ``raw_refs`` (dict).
* No DB writes, no delivery, no notification rows are created here.

Usage
-----
    from app.services.watchlist_alert_payload import (
        WatchlistAlertPayload,
        from_watch_alert,
        from_alert,
        from_material_change,
        from_priority_summary,
    )

    payload = from_material_change(event)
    d = payload.to_dict()           # stable dict
    j = payload.to_json()           # stable JSON string (sorted keys)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError("pydantic is required for WatchlistAlertPayload")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

PAYLOAD_VERSION: int = 1

# ---------------------------------------------------------------------------
# Severity constants & normalization
# ---------------------------------------------------------------------------

SEV_CRITICAL = "critical"
SEV_HIGH     = "high"
SEV_MEDIUM   = "medium"
SEV_LOW      = "low"
SEV_INFO     = "info"

_SEVERITY_MAP: Dict[str, str] = {
    "critical": SEV_CRITICAL,
    "high":     SEV_HIGH,
    "medium":   SEV_MEDIUM,
    "low":      SEV_LOW,
    "info":     SEV_INFO,
    "ignore":   SEV_INFO,      # AlertPriority "ignore" → info
    "warning":  SEV_MEDIUM,
    "alert":    SEV_HIGH,
    "none":     SEV_INFO,
    "":         SEV_LOW,
}


def normalize_severity(raw: str) -> str:
    """Map any legacy severity string to the canonical five-level scale.

    Unknown values fall back to ``low``.
    """
    return _SEVERITY_MAP.get((raw or "").strip().lower(), SEV_LOW)


# ---------------------------------------------------------------------------
# Alert-type constants & normalization
# ---------------------------------------------------------------------------

# Canonical alert_type strings (UPPER_SNAKE_CASE).  These are the only values
# that should appear in WatchlistAlertPayload.alert_type.

AT_SETUP_DOWNGRADE        = "SETUP_DOWNGRADE"
AT_SETUP_UPGRADE          = "SETUP_UPGRADE"
AT_CONVICTION_DROP        = "CONVICTION_DROP"
AT_CONVICTION_RISE        = "CONVICTION_RISE"
AT_DRIVER_SHIFT           = "DRIVER_SHIFT"
AT_RISK_REGIME_CHANGE     = "RISK_REGIME_CHANGE"
AT_STALE_TO_FRESH         = "STALE_TO_FRESH"
AT_FRESH_TO_STALE         = "FRESH_TO_STALE"
AT_FRAGILITY_ESCALATION   = "FRAGILITY_ESCALATION"
AT_FRAGILITY_DE_ESCALATION = "FRAGILITY_DE_ESCALATION"
AT_STANCE_SHIFT           = "STANCE_SHIFT"
AT_THESIS_BREAK           = "THESIS_BREAK"
AT_THESIS_WEAKENED        = "THESIS_WEAKENED"
AT_THESIS_STRENGTHENED    = "THESIS_STRENGTHENED"
AT_NEW_STRUCTURAL_RISK    = "NEW_STRUCTURAL_RISK"
AT_NEW_RISK               = "NEW_RISK"
AT_TREND_FLIP             = "TREND_FLIP"
AT_MARKET_REPRICED        = "MARKET_REPRICED"
AT_COSMETIC               = "COSMETIC"
AT_STABLE                 = "STABLE"
AT_CRITICAL_PRIORITY      = "CRITICAL_PRIORITY"
AT_HIGH_PRIORITY          = "HIGH_PRIORITY"
AT_MEDIUM_PRIORITY        = "MEDIUM_PRIORITY"
AT_NO_ACTION              = "NO_ACTION"
AT_UNKNOWN                = "UNKNOWN"

# Mapping from legacy / lowercase strings to canonical constants.
_ALERT_TYPE_MAP: Dict[str, str] = {
    # WatchAlert types (already UPPER_CASE — pass-through)
    "setup_downgrade":          AT_SETUP_DOWNGRADE,
    "setup_upgrade":            AT_SETUP_UPGRADE,
    "conviction_drop":          AT_CONVICTION_DROP,
    "conviction_rise":          AT_CONVICTION_RISE,
    "driver_shift":             AT_DRIVER_SHIFT,
    "risk_regime_change":       AT_RISK_REGIME_CHANGE,
    "stale_to_fresh":           AT_STALE_TO_FRESH,
    "fresh_to_stale":           AT_FRESH_TO_STALE,
    "fragility_escalation":     AT_FRAGILITY_ESCALATION,
    "fragility_de_escalation":  AT_FRAGILITY_DE_ESCALATION,
    "stance_shift":             AT_STANCE_SHIFT,
    # MaterialChangeEvent.change_type values
    "confidence_collapse":      AT_CONVICTION_DROP,
    "top_signal_replaced":      AT_DRIVER_SHIFT,
    "trend_flip":               AT_TREND_FLIP,
    "new_structural_risk":      AT_NEW_STRUCTURAL_RISK,
    "thesis_weakened":          AT_THESIS_WEAKENED,
    "thesis_strengthened":      AT_THESIS_STRENGTHENED,
    "stable":                   AT_STABLE,
    # MaterialChangeEvent.change_category values
    "thesis_broke":             AT_THESIS_BREAK,
    "market_repriced":          AT_MARKET_REPRICED,
    "new_risk_emerged":         AT_NEW_RISK,
    "cosmetic":                 AT_COSMETIC,
    # AlertPriority levels
    "critical":                 AT_CRITICAL_PRIORITY,
    "high":                     AT_HIGH_PRIORITY,
    "medium":                   AT_MEDIUM_PRIORITY,
    "ignore":                   AT_NO_ACTION,
    "":                         AT_UNKNOWN,
}


def normalize_alert_type(raw: str) -> str:
    """Map any legacy alert_type string to the canonical UPPER_SNAKE_CASE constant.

    Unknown values are uppercased verbatim (forward-compat for new types).
    """
    key = (raw or "").strip().lower()
    if key in _ALERT_TYPE_MAP:
        return _ALERT_TYPE_MAP[key]
    # If raw is already UPPER_CASE and known, pass through
    upper = (raw or "").strip().upper()
    return upper if upper else AT_UNKNOWN


# ---------------------------------------------------------------------------
# Title generator
# ---------------------------------------------------------------------------

_TITLE_MAP: Dict[str, str] = {
    AT_SETUP_DOWNGRADE:         "Setup downgraded",
    AT_SETUP_UPGRADE:           "Setup upgraded",
    AT_CONVICTION_DROP:         "Conviction dropped",
    AT_CONVICTION_RISE:         "Conviction rose",
    AT_DRIVER_SHIFT:            "Dominant driver shifted",
    AT_RISK_REGIME_CHANGE:      "Risk regime changed",
    AT_STALE_TO_FRESH:          "Evidence freshened",
    AT_FRESH_TO_STALE:          "Evidence went stale",
    AT_FRAGILITY_ESCALATION:    "Fragility escalated",
    AT_FRAGILITY_DE_ESCALATION: "Fragility de-escalated",
    AT_STANCE_SHIFT:            "Stance shifted",
    AT_THESIS_BREAK:            "Thesis break detected",
    AT_THESIS_WEAKENED:         "Thesis weakened",
    AT_THESIS_STRENGTHENED:     "Thesis strengthened",
    AT_NEW_STRUCTURAL_RISK:     "New structural risk identified",
    AT_NEW_RISK:                "New risk identified",
    AT_TREND_FLIP:              "Trend direction flipped",
    AT_MARKET_REPRICED:         "Market repriced",
    AT_COSMETIC:                "Minor narrative change",
    AT_STABLE:                  "No material change",
    AT_CRITICAL_PRIORITY:       "Critical priority alert",
    AT_HIGH_PRIORITY:           "High priority alert",
    AT_MEDIUM_PRIORITY:         "Medium priority alert",
    AT_NO_ACTION:               "No action required",
    AT_UNKNOWN:                 "Alert",
}


def _make_title(alert_type: str, ticker: str) -> str:
    """Build a short human-readable title from normalized alert_type and ticker."""
    canon = normalize_alert_type(alert_type)
    base = _TITLE_MAP.get(canon, canon.replace("_", " ").title())
    return f"{ticker}: {base}" if ticker else base


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_str(v: Any, default: str = "") -> str:
    """Return str(v) or default when v is None/falsy."""
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    """Return float(v) or default when v is None or not numeric."""
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Canonical payload
# ---------------------------------------------------------------------------

class WatchlistAlertPayload(BaseModel):
    """Canonical alert payload schema (payload_version=1).

    All adapters produce this schema.  Required fields are always present.
    Optional fields (thesis_version_id, delta_id, priority_score) are None
    when the source does not supply them — consumers must guard with
    ``if payload.delta_id is not None:``.

    ``raw_refs`` contains source-specific metadata preserved for audit and
    debugging; downstream logic should not depend on raw_refs structure.

    Serialization
    -------------
    ``to_dict()``  — returns a plain dict (Pydantic model_dump).
    ``to_json()``  — returns a compact JSON string with sorted keys for
                     stable content-key hashing.
    """

    payload_version: int = PAYLOAD_VERSION
    ticker: str
    alert_type: str        # UPPER_SNAKE_CASE canonical constant
    severity: str          # critical | high | medium | low | info
    title: str
    summary: str
    source: str            # watch_alert | alert | material_change | priority_summary
    created_at: str        # ISO-8601 UTC
    thesis_version_id: Optional[str] = None
    delta_id: Optional[str] = None
    priority_score: Optional[float] = None
    raw_refs: Dict[str, Any] = Field(default_factory=dict)

    # Pydantic v2 config
    model_config = {"extra": "forbid"}

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain dict; stable across identical instances."""
        return self.model_dump()

    def to_json(self) -> str:
        """Return a compact JSON string with sorted keys for stable hashing."""
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    @property
    def is_actionable(self) -> bool:
        """True when severity is critical, high, or medium."""
        return self.severity in (SEV_CRITICAL, SEV_HIGH, SEV_MEDIUM)


# ---------------------------------------------------------------------------
# Adapter: WatchAlert → WatchlistAlertPayload
# ---------------------------------------------------------------------------

def from_watch_alert(
    alert: Any,
    ticker: Optional[str] = None,
) -> WatchlistAlertPayload:
    """Convert a ``watchlist_monitor.WatchAlert`` to canonical payload.

    Null-safe: missing/None fields use empty strings or sensible defaults.
    """
    t = _safe_str(getattr(alert, "ticker", None) or ticker)
    raw_type = _safe_str(getattr(alert, "alert_type", None))
    raw_sev  = _safe_str(getattr(alert, "severity", None))

    return WatchlistAlertPayload(
        ticker=t,
        alert_type=normalize_alert_type(raw_type),
        severity=normalize_severity(raw_sev),
        title=_make_title(raw_type, t),
        summary=_safe_str(getattr(alert, "message", None)),
        source="watch_alert",
        created_at=_safe_str(getattr(alert, "generated_at", None)) or _now_iso(),
        raw_refs={
            "prior_value":     _safe_str(getattr(alert, "prior_value", None)),
            "current_value":   _safe_str(getattr(alert, "current_value", None)),
            "conviction_delta": _safe_float(getattr(alert, "conviction_delta", None), 0.0),
            "original_alert_type": raw_type,
        },
    )


# ---------------------------------------------------------------------------
# Adapter: Alert (schemas.py) → WatchlistAlertPayload
# ---------------------------------------------------------------------------

def from_alert(
    alert: Any,
    ticker: str = "",
    created_at: Optional[str] = None,
) -> WatchlistAlertPayload:
    """Convert an ``app.schemas.Alert`` to canonical payload.

    ``Alert`` has no ticker field — caller must supply it.
    Null-safe: optional Alert fields are gracefully omitted from summary.
    """
    raw_type = _safe_str(getattr(alert, "alert_type", None))
    raw_sev  = _safe_str(getattr(alert, "severity", None))

    # Build summary from most informative available field
    summary = (
        _safe_str(getattr(alert, "reason", None))
        or _safe_str(getattr(alert, "interpretive_summary", None))
        or _safe_str(getattr(alert, "impact_explanation", None))
        or _safe_str(getattr(alert, "recommended_interpretation", None))
    )

    # Collect non-None alert fields for raw_refs (exclude None to keep clean)
    try:
        raw_dict = {k: v for k, v in alert.model_dump().items() if v is not None}
    except Exception:
        raw_dict = {}

    return WatchlistAlertPayload(
        ticker=_safe_str(ticker),
        alert_type=normalize_alert_type(raw_type),
        severity=normalize_severity(raw_sev),
        title=_make_title(raw_type, _safe_str(ticker)),
        summary=summary,
        source="alert",
        created_at=created_at or _now_iso(),
        raw_refs=raw_dict,
    )


# ---------------------------------------------------------------------------
# Adapter: MaterialChangeEvent → WatchlistAlertPayload
# ---------------------------------------------------------------------------

def from_material_change(event: Any) -> WatchlistAlertPayload:
    """Convert an ``app.schemas.MaterialChangeEvent`` to canonical payload.

    Uses ``change_category`` when it encodes a high-level thesis judgment
    (thesis_broke, new_risk_emerged, market_repriced); falls back to
    ``change_type`` for the specific mechanism.  ``change_category`` and
    ``change_type`` are both preserved in ``raw_refs``.
    """
    ticker        = _safe_str(getattr(event, "ticker", None))
    change_type   = _safe_str(getattr(event, "change_type", None))
    change_cat    = _safe_str(getattr(event, "change_category", None))
    raw_sev       = _safe_str(getattr(event, "severity", None))

    # Prefer change_category for thesis-break cases; use change_type otherwise.
    if change_cat in ("thesis_broke", "new_risk_emerged", "market_repriced"):
        alert_type_raw = change_cat
    else:
        alert_type_raw = change_type or change_cat

    return WatchlistAlertPayload(
        ticker=ticker,
        alert_type=normalize_alert_type(alert_type_raw),
        severity=normalize_severity(raw_sev),
        title=_make_title(alert_type_raw, ticker),
        summary=_safe_str(getattr(event, "summary", None)),
        source="material_change",
        created_at=_safe_str(getattr(event, "timestamp", None)) or _now_iso(),
        delta_id=_safe_str(getattr(event, "event_id", None)) or None,
        thesis_version_id=_safe_str(getattr(event, "current_snapshot_id", None)) or None,
        priority_score=_safe_float(getattr(event, "materiality_score", None)),
        raw_refs={
            "event_id":         _safe_str(getattr(event, "event_id", None)),
            "change_type":      change_type,
            "change_category":  change_cat,
            "confidence_change": _safe_float(getattr(event, "confidence_change", None), 0.0),
            "materiality_score": _safe_float(getattr(event, "materiality_score", None), 0.0),
            "drivers":          list(getattr(event, "drivers", None) or []),
            "previous_snapshot_id": _safe_str(getattr(event, "previous_snapshot_id", None)) or None,
        },
    )


# ---------------------------------------------------------------------------
# Adapter: AlertPriority → WatchlistAlertPayload
# ---------------------------------------------------------------------------

def from_priority_summary(
    priority: Any,
    ticker: Optional[str] = None,
    summary: str = "",
    created_at: Optional[str] = None,
) -> WatchlistAlertPayload:
    """Convert an ``app.schemas.AlertPriority`` to canonical payload.

    ``AlertPriority`` encodes a priority level rather than an event type, so
    ``alert_type`` is set to one of the PRIORITY constants (CRITICAL_PRIORITY,
    HIGH_PRIORITY, MEDIUM_PRIORITY, NO_ACTION).  Severity is derived from the
    priority level.
    """
    t              = _safe_str(getattr(priority, "ticker", None) or ticker)
    priority_level = _safe_str(getattr(priority, "priority", None)) or "ignore"
    reason         = _safe_str(getattr(priority, "reason", None))
    p_score        = _safe_float(getattr(priority, "priority_score", None))
    alert_id       = _safe_str(getattr(priority, "alert_id", None)) or None

    # Map priority level → alert_type
    _prio_to_type = {
        "critical": AT_CRITICAL_PRIORITY,
        "high":     AT_HIGH_PRIORITY,
        "medium":   AT_MEDIUM_PRIORITY,
        "ignore":   AT_NO_ACTION,
    }
    alert_type = _prio_to_type.get(priority_level.lower(), AT_UNKNOWN)

    # Map priority level → severity
    _prio_to_sev = {
        "critical": SEV_CRITICAL,
        "high":     SEV_HIGH,
        "medium":   SEV_MEDIUM,
        "ignore":   SEV_INFO,
    }
    sev = _prio_to_sev.get(priority_level.lower(), SEV_LOW)

    return WatchlistAlertPayload(
        ticker=t,
        alert_type=alert_type,
        severity=sev,
        title=_make_title(alert_type, t),
        summary=summary or reason,
        source="priority_summary",
        created_at=created_at or _now_iso(),
        delta_id=alert_id,
        priority_score=p_score,
        raw_refs={
            "alert_id":      _safe_str(getattr(priority, "alert_id", None)),
            "priority":      priority_level,
            "priority_score": p_score if p_score is not None else 0.0,
            "reason":        reason,
        },
    )
