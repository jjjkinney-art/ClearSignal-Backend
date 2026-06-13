"""
Intelligence Ranking / Triage — Phase 10C · Slice 3.

THE pure ranking engine that decides which intelligence items deserve delivery,
batching, or suppression.  It composes signals that already exist (canonical
severity, alert priority score, materiality, recency, watchlist relevance,
novelty/duplicate risk) into a single ``priority_score`` and a ``delivery_class``.

Hard boundaries (this module is pure and inert)
-----------------------------------------------
* No DB reads or writes.  No delivery.  No notifications.  No digest rows.
* No LLM calls.  No network.  No clock dependence except an injectable ``now``.
* Deterministic: identical inputs → identical output, every time.

It only DECIDES.  Acting on the decision (push, batch, suppress) is later slices.

Inputs
------
Accepts any of, without special-casing the type:
  * ``WatchlistAlertPayload`` (pydantic model, Slice 1/10B)
  * briefing item payloads (plain dicts)
  * future portfolio relevance payloads (plain dicts)
Anything that exposes the probed fields — as attributes or dict keys — is
ranked uniformly.  See ``_extract_signals``.

Severity translation goes through ``severity_model`` (Slice 1) — the single
sanctioned translator.  This module defines no severity vocabulary of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services import severity_model

# ---------------------------------------------------------------------------
# Tunable constants (calibration owned by a later slice; safe initial values)
# ---------------------------------------------------------------------------

# Composite-score weights.  Sum to 1.0 so priority_score ∈ [0, 1].
_W_SEVERITY   = 0.35   # canonical severity rank (always present — the anchor)
_W_PRIORITY   = 0.20   # alert_prioritizer priority_score (0..1)
_W_MATERIALITY = 0.20  # thesis-delta / materiality magnitude (0..1)
_W_RELEVANCE  = 0.10   # watchlist / portfolio relevance (0..1)
_W_RECENCY    = 0.10   # recency decay (0..1, fresh == 1)
_W_NOVELTY    = 0.05   # 1 - duplicate risk (0..1)

# Decision thresholds.
PUSH_SCORE_THRESHOLD       = 0.50   # a HIGH item needs composite ≥ this to push;
                                    # CRITICAL bypasses this gate.
NOVELTY_SUPPRESS_THRESHOLD = 0.15   # novelty below this → suppress as duplicate.
STALE_AFTER_HOURS          = 48.0   # older than this → stale (demote one class).
RECENCY_HALF_LIFE_HOURS    = 24.0   # recency score halves every this many hours.

# Neutral priors for absent optional signals (keep the formula total & stable).
_DEFAULT_RELEVANCE = 0.70   # on-watchlist neutral
_DEFAULT_RECENCY   = 0.50   # unknown age → neither fresh nor stale
_DEFAULT_NOVELTY   = 1.00   # assume novel unless a duplicate signal says otherwise


# ---------------------------------------------------------------------------
# Delivery-class decisions
# ---------------------------------------------------------------------------

class RankingDecision:
    """The four mutually-exclusive delivery classes a ranked item resolves to."""

    PUSH_NOW = "push_now"
    DIGEST = "digest"
    PULL_ONLY = "pull_only"
    SUPPRESS = "suppress"

    ALL: Tuple[str, ...] = (PUSH_NOW, DIGEST, PULL_ONLY, SUPPRESS)

    # Staleness demotes one rung; it never demotes to SUPPRESS.
    _DEMOTE: Dict[str, str] = {
        PUSH_NOW: DIGEST,
        DIGEST: PULL_ONLY,
        PULL_ONLY: PULL_ONLY,
        SUPPRESS: SUPPRESS,
    }

    @classmethod
    def demote(cls, decision: str) -> str:
        return cls._DEMOTE.get(decision, decision)


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RankedIntelligenceItem:
    """The immutable result of ranking one intelligence item."""

    target: str                       # ticker / portfolio_id / target_key
    source: str                       # provenance of the input payload
    canonical_severity: str           # severity_model canonical value
    severity_rank: int                # 0..4
    priority_score: float             # composite, 0..1, rounded to 6dp
    delivery_class: str               # one of RankingDecision.ALL
    reason_codes: Tuple[str, ...]     # decisive reasons, ordered
    components: Dict[str, float] = field(default_factory=dict)  # score breakdown (audit)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "source": self.source,
            "canonical_severity": self.canonical_severity,
            "severity_rank": self.severity_rank,
            "priority_score": self.priority_score,
            "delivery_class": self.delivery_class,
            "reason_codes": list(self.reason_codes),
            "components": dict(self.components),
        }


# ---------------------------------------------------------------------------
# Input signal extraction (type-agnostic: pydantic model OR dict)
# ---------------------------------------------------------------------------

@dataclass
class _Signals:
    target: str
    severity_raw: str
    priority_score: Optional[float]
    materiality: Optional[float]
    relevance: Optional[float]
    created_at: Optional[str]
    novelty: Optional[float]
    is_duplicate: bool
    content_key: str
    source: str


def _field(item: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a dict or an object, returning ``default`` if absent."""
    if isinstance(item, dict):
        return item.get(name, default)
    if hasattr(item, name):
        return getattr(item, name)
    return default


def _raw_refs(item: Any) -> Dict[str, Any]:
    rr = _field(item, "raw_refs", None)
    return rr if isinstance(rr, dict) else {}


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _content_key(item: Any, target: str, severity_raw: str) -> str:
    """Stable identity for novelty/duplicate detection.

    Prefers an explicit content_key; else a delta_id; else a deterministic
    composite of (target, alert_type, summary/title).
    """
    explicit = _field(item, "content_key", None)
    if explicit:
        return str(explicit)
    delta = _field(item, "delta_id", None)
    if delta:
        return f"delta:{delta}"
    alert_type = str(_field(item, "alert_type", "") or "")
    summary = str(_field(item, "summary", "") or _field(item, "title", "") or "")
    return f"{target.upper()}|{alert_type}|{summary}".strip().lower()


def _extract_signals(item: Any) -> _Signals:
    """Project any supported payload onto the common signal set.

    No type checks: portfolio payloads, briefing dicts, and WatchlistAlertPayload
    all flow through the same field-probing path.  Materiality and relevance are
    probed both at top level and inside ``raw_refs`` so existing payloads (which
    stash materiality_score in raw_refs) work unchanged.
    """
    rr = _raw_refs(item)

    target = str(
        _field(item, "ticker", None)
        or _field(item, "target", None)
        or _field(item, "target_key", None)
        or rr.get("ticker", "")
        or ""
    )

    severity_raw = str(_field(item, "severity", "") or rr.get("severity", "") or "")

    priority_score = _as_float(_field(item, "priority_score", None))
    if priority_score is None:
        priority_score = _as_float(rr.get("priority_score"))

    materiality = _as_float(_field(item, "materiality", None))
    if materiality is None:
        materiality = _as_float(
            rr.get("materiality_score", rr.get("materiality"))
        )

    relevance = _as_float(_field(item, "relevance", None))
    if relevance is None:
        # portfolio payloads may express relevance as portfolio_weight
        relevance = _as_float(
            _field(item, "portfolio_weight", None) or rr.get("relevance")
        )

    created_at = _field(item, "created_at", None) or rr.get("created_at")
    created_at = str(created_at) if created_at else None

    novelty = _as_float(_field(item, "novelty", None))
    is_duplicate = bool(_field(item, "is_duplicate", False))

    content_key = _content_key(item, target, severity_raw)
    source = str(_field(item, "source", "") or "unknown")

    return _Signals(
        target=target,
        severity_raw=severity_raw,
        priority_score=priority_score,
        materiality=materiality,
        relevance=relevance,
        created_at=created_at,
        novelty=novelty,
        is_duplicate=is_duplicate,
        content_key=content_key,
        source=source,
    )


# ---------------------------------------------------------------------------
# Component scoring
# ---------------------------------------------------------------------------

def _recency_score(created_at: Optional[str], now: datetime) -> Tuple[float, float]:
    """Return (recency_score, age_hours).

    recency_score decays from 1.0 (fresh) by half every RECENCY_HALF_LIFE_HOURS.
    Unparseable / missing timestamp → neutral default, age_hours = -1 (unknown).
    """
    if not created_at:
        return _DEFAULT_RECENCY, -1.0
    ts = _parse_iso(created_at)
    if ts is None:
        return _DEFAULT_RECENCY, -1.0
    age_hours = (now - ts).total_seconds() / 3600.0
    if age_hours <= 0:
        return 1.0, 0.0
    score = 0.5 ** (age_hours / RECENCY_HALF_LIFE_HOURS)
    return _clamp01(score), age_hours


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def _compute_components(
    sig: _Signals,
    severity_rank: int,
    now: datetime,
) -> Tuple[Dict[str, float], float, bool]:
    """Compute the weighted components, the composite priority_score, and the
    stale flag.  Absent optional signals fall back to neutral / severity-implied
    priors so the formula is total and deterministic.
    """
    sev_component = severity_rank / 4.0  # 0..1

    # Missing alert priority / materiality fall back to the severity-implied score.
    priority = sig.priority_score if sig.priority_score is not None else sev_component
    materiality = sig.materiality if sig.materiality is not None else sev_component
    relevance = sig.relevance if sig.relevance is not None else _DEFAULT_RELEVANCE

    recency, age_hours = _recency_score(sig.created_at, now)

    if sig.novelty is not None:
        novelty = sig.novelty
    elif sig.is_duplicate:
        novelty = 0.0
    else:
        novelty = _DEFAULT_NOVELTY

    components = {
        "severity":    _clamp01(sev_component),
        "priority":    _clamp01(priority),
        "materiality": _clamp01(materiality),
        "relevance":   _clamp01(relevance),
        "recency":     _clamp01(recency),
        "novelty":     _clamp01(novelty),
    }

    composite = (
        _W_SEVERITY    * components["severity"]
        + _W_PRIORITY   * components["priority"]
        + _W_MATERIALITY * components["materiality"]
        + _W_RELEVANCE  * components["relevance"]
        + _W_RECENCY    * components["recency"]
        + _W_NOVELTY    * components["novelty"]
    )
    composite = round(_clamp01(composite), 6)

    stale = age_hours >= STALE_AFTER_HOURS
    return components, composite, stale


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

def _decide(
    sig: _Signals,
    canonical: str,
    severity_rank: int,
    composite: float,
    components: Dict[str, float],
    stale: bool,
    min_severity_rank: int,
) -> Tuple[str, List[str]]:
    """Resolve the delivery class + reason codes.

    Precedence:
      1. duplicate / low novelty  → SUPPRESS
      2. below user min_severity  → SUPPRESS
      3. base class from severity (HIGH gated by push score)
      4. staleness demotes one class
    """
    reasons: List[str] = [f"severity_{canonical}"]

    # 1. Duplicate / low-novelty suppression.
    if sig.is_duplicate or components["novelty"] < NOVELTY_SUPPRESS_THRESHOLD:
        reasons.append("duplicate" if sig.is_duplicate else "low_novelty")
        reasons.append("suppressed")
        return RankingDecision.SUPPRESS, reasons

    # 2. Below user minimum severity.
    if severity_rank < min_severity_rank:
        reasons.append("below_min_severity")
        reasons.append("suppressed")
        return RankingDecision.SUPPRESS, reasons

    # 3. Base class from severity.
    if canonical == severity_model.CRITICAL:
        decision = RankingDecision.PUSH_NOW
        reasons.append("pushed")
    elif canonical == severity_model.HIGH:
        if composite >= PUSH_SCORE_THRESHOLD:
            decision = RankingDecision.PUSH_NOW
            reasons.append("pushed")
        else:
            decision = RankingDecision.DIGEST
            reasons.append("high_below_push_threshold")
            reasons.append("digested")
    elif canonical == severity_model.MEDIUM:
        decision = RankingDecision.DIGEST
        reasons.append("digested")
    else:  # LOW, INFO
        decision = RankingDecision.PULL_ONLY
        reasons.append("pull_only")

    # 4. Staleness demotion (delivered, but lower class — never suppressed).
    if stale and decision in (RankingDecision.PUSH_NOW, RankingDecision.DIGEST):
        decision = RankingDecision.demote(decision)
        reasons.append("stale_demoted")

    return decision, reasons


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rank_item(
    item: Any,
    *,
    user_min_severity: str = severity_model.INFO,
    now: Optional[datetime] = None,
) -> RankedIntelligenceItem:
    """Rank a single intelligence item.  Pure function; writes nothing.

    Parameters
    ----------
    item:
        A WatchlistAlertPayload, a briefing item dict, or a portfolio payload.
    user_min_severity:
        The user's canonical minimum severity floor.  Items below it suppress.
    now:
        Reference time for recency/staleness.  Injectable for determinism;
        defaults to ``datetime.now(timezone.utc)``.
    """
    now = now or datetime.now(timezone.utc)
    min_rank = severity_model.severity_rank(
        severity_model.to_canonical_severity(user_min_severity)
    )

    sig = _extract_signals(item)
    canonical = severity_model.to_canonical_severity(sig.severity_raw)
    sev_rank = severity_model.severity_rank(canonical)

    components, composite, stale = _compute_components(sig, sev_rank, now)
    decision, reasons = _decide(
        sig, canonical, sev_rank, composite, components, stale, min_rank
    )

    return RankedIntelligenceItem(
        target=sig.target,
        source=sig.source,
        canonical_severity=canonical,
        severity_rank=sev_rank,
        priority_score=composite,
        delivery_class=decision,
        reason_codes=tuple(reasons),
        components=components,
    )


def rank_items(
    items: Sequence[Any],
    *,
    user_min_severity: str = severity_model.INFO,
    now: Optional[datetime] = None,
) -> List[RankedIntelligenceItem]:
    """Rank a batch, returning items sorted by priority_score descending.

    Within-batch duplicate detection: the first occurrence of a content_key is
    novel; later occurrences are marked duplicates and suppress (spec §4.4).
    Sort is stable and deterministic — ties break by (target, canonical_severity).
    """
    now = now or datetime.now(timezone.utc)
    seen: set = set()
    ranked: List[RankedIntelligenceItem] = []

    for item in items:
        sig = _extract_signals(item)
        if sig.content_key in seen and not sig.is_duplicate:
            # Repeat of an already-seen item within this batch → mark duplicate.
            ranked.append(
                rank_item(
                    _with_duplicate(item),
                    user_min_severity=user_min_severity,
                    now=now,
                )
            )
        else:
            seen.add(sig.content_key)
            ranked.append(
                rank_item(item, user_min_severity=user_min_severity, now=now)
            )

    ranked.sort(
        key=lambda r: (-r.priority_score, r.target, r.canonical_severity)
    )
    return ranked


def _with_duplicate(item: Any) -> Dict[str, Any]:
    """Return a dict view of ``item`` with is_duplicate=True, without mutating
    the original (determinism / no side effects)."""
    if isinstance(item, dict):
        d = dict(item)
    else:
        to_dict = getattr(item, "to_dict", None)
        d = to_dict() if callable(to_dict) else {
            k: getattr(item, k) for k in dir(item)
            if not k.startswith("_") and not callable(getattr(item, k))
        }
    d["is_duplicate"] = True
    return d
