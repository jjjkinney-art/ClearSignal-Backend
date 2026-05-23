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

_MANAGEMENT_COMMENTARY_KEYWORDS = (
    "earnings call",
    "conference call",
    "management commentary",
    "ceo comments",
    "cfo comments",
    "investor day",
    "analyst day",
    "management guidance",
)

_SEC_FILING_KEYWORDS = (
    "10-k",
    "10-q",
    "8-k",
    "sec filing",
    "edgar",
    "annual report",
    "quarterly report",
)

_MACRO_LINKAGE_KEYWORDS = (
    "federal reserve",
    "fomc",
    "interest rate",
    "inflation",
    "yield curve",
    "gdp",
    "macro",
    "monetary policy",
    "credit",
    "recession",
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


def _newest_evidence_age_days(evidence: List[RetrievedEvidence]) -> Optional[int]:
    """Return the age of the MOST RECENT parseable evidence item (days)."""
    now = datetime.now(timezone.utc)
    min_age: Optional[int] = None
    for ev in evidence:
        ev_dt = _parse_timestamp(getattr(ev, "timestamp", None))
        if ev_dt is None:
            continue
        age = (now - ev_dt).days
        if min_age is None or age < min_age:
            min_age = age
    return min_age


def _has_management_commentary(evidence: List[RetrievedEvidence]) -> bool:
    """Return True if any evidence item contains management commentary / earnings call."""
    for ev in evidence:
        text = f"{ev.title or ''} {ev.source or ''} {ev.summary or ''}".lower()
        if any(kw in text for kw in _MANAGEMENT_COMMENTARY_KEYWORDS):
            return True
    return False


def _has_sec_filing(evidence: List[RetrievedEvidence]) -> bool:
    """Return True if any evidence item is a SEC filing (10-K, 10-Q, 8-K)."""
    for ev in evidence:
        text = f"{ev.title or ''} {ev.source or ''}".lower()
        if any(kw in text for kw in _SEC_FILING_KEYWORDS):
            return True
    return False


def _has_macro_linkage(evidence: List[RetrievedEvidence]) -> bool:
    """Return True if any evidence item has macro context (rates, inflation, Fed)."""
    for ev in evidence:
        text = f"{ev.title or ''} {ev.summary or ''}".lower()
        if any(kw in text for kw in _MACRO_LINKAGE_KEYWORDS):
            return True
    return False


# ── Public API ────────────────────────────────────────────────────────────────

def compute_evidence_coverage_gaps(
    evidence: List[RetrievedEvidence],
) -> Tuple[float, List[str]]:
    """Compute evidence coverage penalty and structured gap taxonomy.

    Parameters
    ----------
    evidence : Full evidence list passed to the synthesis pipeline.

    Returns
    -------
    penalty : Total confidence penalty (0.0 – ~0.38). Subtract from the
              LLM-generated confidence_score; floor at 0.
    gaps    : Institutional-quality descriptions of each coverage gap,
              categorized by gap type. Empty list when all checks pass.

    Gap taxonomy:
      GAP_VALUATION        — no live P/E, EV/EBITDA, FCF yield data
      GAP_ANALYST          — no sell-side estimates or price-target consensus
      GAP_EARNINGS         — no recent earnings transcript or results
      GAP_MGMT_COMMENTARY  — no earnings call or management guidance text
      GAP_SEC_FILING       — no 10-K / 10-Q / 8-K filing evidence
      GAP_STALE            — evidence is >180d old on average
      GAP_VERY_STALE       — evidence is >365d old on average
      GAP_SPARSE           — fewer than 3 evidence items total
    """
    if not evidence:
        return 0.28, [
            "GAP_SPARSE | No evidence retrieved — live valuation ratios, analyst "
            "estimates, management commentary, and recent earnings are all absent; "
            "no directional call can be defended"
        ]

    penalty: float = 0.0
    gaps: List[str] = []
    ev_count = len(evidence)

    # ── Sparse evidence pool ──────────────────────────────────────────────────
    if ev_count < 3:
        gaps.append(
            f"GAP_SPARSE | Evidence pool contains only {ev_count} item"
            f"{'s' if ev_count != 1 else ''} — conclusions drawn from this base "
            "should be treated as directional inference, not grounded analysis"
        )
        # No separate penalty — sparse pool already reduces all downstream checks

    # ── Live valuation ratios ─────────────────────────────────────────────────
    if not _has_live_valuation(evidence):
        penalty += _PENALTY_NO_LIVE_VALUATION
        gaps.append(
            "GAP_VALUATION | No live valuation ratios — P/E, EV/EBITDA, and FCF yield "
            "absent; multiple-based conclusions are unanchored and cannot be stress-tested "
            "against current pricing"
        )

    # ── Analyst estimates / price targets ────────────────────────────────────
    if not _has_analyst_estimates(evidence):
        penalty += _PENALTY_NO_ANALYST_ESTIMATES
        gaps.append(
            "GAP_ANALYST | No analyst estimates or price-target consensus — "
            "forward earnings trajectory and sell-side positioning are absent; "
            "the embedded market expectation cannot be precisely characterized"
        )

    # ── Recent earnings evidence ──────────────────────────────────────────────
    if not _has_recent_earnings(evidence):
        penalty += _PENALTY_NO_RECENT_EARNINGS
        gaps.append(
            f"GAP_EARNINGS | No recent earnings evidence (< {_RECENT_EARNINGS_THRESHOLD_DAYS}d) — "
            "actual results vs guidance, margin trajectory, and beat/miss cadence "
            "are absent from the evidence base"
        )

    # ── Management commentary ─────────────────────────────────────────────────
    if not _has_management_commentary(evidence):
        # Informational only — no additional penalty (earnings already captures this)
        gaps.append(
            "GAP_MGMT_COMMENTARY | No earnings call or management guidance transcript — "
            "qualitative guidance signals and forward-looking language are absent"
        )

    # ── SEC filing evidence ───────────────────────────────────────────────────
    if not _has_sec_filing(evidence):
        # Informational only — no additional penalty
        gaps.append(
            "GAP_SEC_FILING | No SEC filing (10-K / 10-Q / 8-K) — balance sheet, "
            "risk-factor disclosure, and regulatory filings not reflected in the evidence"
        )

    # ── Evidence freshness ────────────────────────────────────────────────────
    oldest = _oldest_evidence_age_days(evidence)
    newest = _newest_evidence_age_days(evidence)
    if oldest is not None:
        age_months = round(oldest / 30)
        if oldest > 365:
            penalty += _PENALTY_STALE_BEYOND_180
            gaps.append(
                f"GAP_VERY_STALE | Oldest evidence is {age_months} months old — "
                "execution assumptions, margin structure, and valuation context "
                "may not reflect any developments since this date; "
                "directional conclusions carry meaningful temporal uncertainty"
            )
        elif oldest > _STALE_THRESHOLD_DAYS:
            penalty += _PENALTY_STALE_BEYOND_180
            gaps.append(
                f"GAP_STALE | Evidence is approximately {age_months} months old — "
                "recent operating data, guidance revisions, and market regime shifts "
                "are not captured; time-sensitive assumptions should be flagged"
            )
        elif oldest > _RECENT_EARNINGS_THRESHOLD_DAYS:
            penalty += _PENALTY_STALE_90_TO_180
            gaps.append(
                f"GAP_STALE | Evidence is approximately {age_months} months old — "
                "some recency risk in execution-sensitive claims"
            )

    return round(penalty, 4), gaps
