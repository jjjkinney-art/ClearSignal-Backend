"""
Evidence coverage gap detector and confidence calibrator.

Computes a penalty score based on what evidence types are missing from the
evidence pool, then returns a downward adjustment to be subtracted from the
LLM-generated confidence score.  This ensures the API never returns high
confidence when live valuation data, analyst estimates, or recent earnings
are absent — a signal-to-noise problem that inflates apparent certainty.

Penalty schedule
----------------
Gap                                    Penalty
-----                                  -------
No live valuation ratios (FMP)         −0.08
No analyst estimates / price targets   −0.05
No recent earnings evidence (< 90d)    −0.08
Evidence stale: oldest > 180d          −0.12
Evidence moderately stale: oldest      −0.05
  90–180d (mutually exclusive with ↑)

Total max penalty: ~0.38

Usage
-----
    from app.services.confidence_calibrator import compute_evidence_coverage_gaps

    penalty, gaps = compute_evidence_coverage_gaps(evidence)
    adjusted_conf = max(0.0, thesis.confidence_score - penalty)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from ..schemas import RetrievedEvidence

# ── Evidence-source fingerprints ──────────────────────────────────────────────
_FMP_VALUATION_FINGERPRINTS = (
    "ratios-ttm",
    "key-metrics-ttm",
    "valuation_ratios",
    "fmp-ratios",
    "pe ratio",
    "ev/ebitda",
    "price-to-earnings",
)

_FMP_ANALYST_FINGERPRINTS = (
    "analyst-estimates",
    "price-target",
    "analyst_estimates",
    "price target consensus",
    "analyst estimates",
    "consensus",
)

_EARNINGS_KEYWORDS = (
    "earnings",
    "eps",
    "quarterly results",
    "q1 ", "q2 ", "q3 ", "q4 ",
    "fiscal year",
    "revenue beat",
    "revenue miss",
    "guidance",
    "net income",
)

# ── Penalty constants ─────────────────────────────────────────────────────────
_PENALTY_NO_LIVE_VALUATION: float = 0.08
_PENALTY_NO_ANALYST_ESTIMATES: float = 0.05
_PENALTY_NO_RECENT_EARNINGS: float = 0.08
_PENALTY_STALE_BEYOND_180: float = 0.12
_PENALTY_STALE_90_TO_180: float = 0.05

_RECENT_EARNINGS_THRESHOLD_DAYS: int = 90
_STALE_THRESHOLD_DAYS: int = 180


# ── Timestamp parsing ─────────────────────────────────────────────────────────

# Map format strings to the expected length of the date string they match.
# This allows us to slice the input string to exactly the right number of
# characters before attempting to parse — critical because format codes like
# "%Y" are 2 chars but expand to 4-char values in the actual date string.
_TS_FORMAT_LENGTHS: "list[tuple[str, int]]" = [
    ("%Y-%m-%dT%H:%M:%SZ", 20),  # "2026-01-15T10:30:00Z"
    ("%Y-%m-%dT%H:%M:%S",  19),  # "2026-01-15T10:30:00"
    ("%Y-%m-%dT%H:%M",     16),  # "2026-01-15T10:30"
    ("%Y-%m-%d",            10),  # "2026-01-15"
    ("%Y-%m",                7),  # "2026-01"
]


def _parse_timestamp(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-ish timestamp string into an aware datetime.

    Returns None when the string is absent or unparseable.
    Tries each format from most-specific to least-specific, slicing the
    input string to the expected output length (not the format-string length).
    """
    if not ts:
        return None
    ts_clean = ts.strip()
    for fmt, expected_len in _TS_FORMAT_LENGTHS:
        try:
            return datetime.strptime(ts_clean[:expected_len], fmt).replace(
                tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            continue
    return None


# ── Coverage detectors ────────────────────────────────────────────────────────

def _has_live_valuation(evidence: List[RetrievedEvidence]) -> bool:
    """Return True if any evidence item came from an FMP valuation/ratios endpoint."""
    for ev in evidence:
        haystack = f"{ev.source or ''} {ev.title or ''}".lower()
        if any(fp in haystack for fp in _FMP_VALUATION_FINGERPRINTS):
            return True
    return False


def _has_analyst_estimates(evidence: List[RetrievedEvidence]) -> bool:
    """Return True if any evidence item contains analyst estimates / price targets."""
    for ev in evidence:
        haystack = f"{ev.source or ''} {ev.title or ''}".lower()
        if any(fp in haystack for fp in _FMP_ANALYST_FINGERPRINTS):
            return True
    return False


def _has_recent_earnings(
    evidence: List[RetrievedEvidence],
    threshold_days: int = _RECENT_EARNINGS_THRESHOLD_DAYS,
) -> bool:
    """Return True if any earnings evidence is within *threshold_days* of today.

    When an earnings item exists but has no parseable timestamp, it is
    accepted (benefit of the doubt — assume it is recent).
    """
    now = datetime.now(timezone.utc)
    for ev in evidence:
        text = f"{ev.title or ''} {ev.summary or ''}".lower()
        if not any(kw in text for kw in _EARNINGS_KEYWORDS):
            continue
        ev_dt = _parse_timestamp(getattr(ev, "timestamp", None))
        if ev_dt is None:
            return True  # undated earnings evidence — assume fresh
        if (now - ev_dt).days <= threshold_days:
            return True
    return False


def _oldest_evidence_age_days(evidence: List[RetrievedEvidence]) -> Optional[int]:
    """Return the age in calendar days of the OLDEST parseable evidence item.

    Returns None when no timestamps are parseable.
    """
    now = datetime.now(timezone.utc)
    max_age: Optional[int] = None
    for ev in evidence:
        ev_dt = _parse_timestamp(getattr(ev, "timestamp", None))
        if ev_dt is None:
            continue
        age = (now - ev_dt).days
        if max_age is None or age > max_age:
            max_age = age
    return max_age


# ── Public API ────────────────────────────────────────────────────────────────

def compute_evidence_coverage_gaps(
    evidence: List[RetrievedEvidence],
) -> Tuple[float, List[str]]:
    """Compute evidence coverage penalty and list of gap descriptions.

    Parameters
    ----------
    evidence : Full evidence list passed to the synthesis pipeline.

    Returns
    -------
    penalty : Total confidence penalty (0.0 – ~0.38). Subtract from the
              LLM-generated confidence_score; floor at 0.
    gaps    : Human-readable descriptions of each detected coverage gap.
              Empty list when all checks pass.
    """
    if not evidence:
        return 0.28, [
            "No evidence available — live valuation, analyst estimates, and "
            "recent earnings coverage all absent"
        ]

    penalty: float = 0.0
    gaps: List[str] = []

    # ── Live valuation ratios ─────────────────────────────────────────────────
    if not _has_live_valuation(evidence):
        penalty += _PENALTY_NO_LIVE_VALUATION
        gaps.append(
            "No live valuation ratios (FMP) — P/E, EV/EBITDA, and FCF yield "
            "coverage absent; multiple-based conclusions are unanchored"
        )

    # ── Analyst estimates / price targets ────────────────────────────────────
    if not _has_analyst_estimates(evidence):
        penalty += _PENALTY_NO_ANALYST_ESTIMATES
        gaps.append(
            "No analyst estimates or price-target consensus — forward earnings "
            "and sell-side positioning absent"
        )

    # ── Recent earnings evidence ──────────────────────────────────────────────
    if not _has_recent_earnings(evidence):
        penalty += _PENALTY_NO_RECENT_EARNINGS
        gaps.append(
            f"No recent earnings evidence (< {_RECENT_EARNINGS_THRESHOLD_DAYS}d) — "
            "actual vs guidance comparison and management commentary absent"
        )

    # ── Evidence freshness ────────────────────────────────────────────────────
    oldest = _oldest_evidence_age_days(evidence)
    if oldest is not None:
        if oldest > _STALE_THRESHOLD_DAYS:
            penalty += _PENALTY_STALE_BEYOND_180
            gaps.append(
                f"Evidence stale: oldest item is {oldest}d old "
                f"(> {_STALE_THRESHOLD_DAYS}d threshold) — conclusions may not "
                "reflect current market conditions"
            )
        elif oldest > _RECENT_EARNINGS_THRESHOLD_DAYS:
            penalty += _PENALTY_STALE_90_TO_180
            gaps.append(
                f"Evidence moderately stale: oldest item is {oldest}d old — "
                "some recency risk in time-sensitive claims"
            )

    return round(penalty, 4), gaps
