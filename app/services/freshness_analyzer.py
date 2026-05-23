"""
Evidence freshness analyzer — structured per-dimension freshness metadata.

Inspects an evidence pool and returns a FreshnessProfile that records the
age of each institutional evidence category (earnings, filings, estimates,
valuation, macro).  Downstream consumers — conviction_modeler._build_reasoning
and watchlist_monitor — use the profile to produce specific staleness language
and asymmetric conviction compression.

Design constraints
------------------
- No LLM calls.  All logic is deterministic keyword + timestamp matching.
- Returns a FreshnessProfile dataclass (not a Pydantic model) so it can be
  constructed and inspected without serialization overhead.
- Conservative: when timestamps are absent, the dimension is treated as
  "unknown age" rather than fresh, so callers must explicitly handle None.

Dimension classification
------------------------
earnings    — quarterly results, EPS, revenue beat/miss, guidance statements
filing      — 10-K, 10-Q, 8-K, SEC EDGAR, annual/quarterly reports
estimates   — analyst estimates, price targets, consensus, sell-side
valuation   — FMP ratios-ttm, key-metrics, P/E, EV/EBITDA, FCF yield
macro       — Fed, FOMC, CPI, interest rates, GDP, yield curve, inflation

Freshness thresholds
--------------------
Dimension    Fresh    Moderate    Stale    Very stale
---------    -----    --------    -----    ----------
earnings     ≤45d     46–90d      91–180d  >180d
filing       ≤90d     91–180d     181–365d >365d
estimates    ≤30d     31–60d      61–120d  >120d
valuation    ≤14d     15–30d      31–90d   >90d
macro        ≤7d      8–14d       15–30d   >30d

Dominant stale dimension
------------------------
When multiple dimensions are stale the function picks the one most likely
to affect conviction, using a priority order:
  valuation > estimates > earnings > filing > macro

Usage
-----
    from app.services.freshness_analyzer import analyze_evidence_freshness

    fp = analyze_evidence_freshness(evidence)
    # fp.earnings_age_days  → int | None
    # fp.dominant_stale_dimension → "earnings" | "filing" | "estimates" | "valuation" | "macro" | None
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..schemas import RetrievedEvidence


# ── Evidence keyword fingerprints ─────────────────────────────────────────────

_EARNINGS_KEYWORDS = (
    "earnings", "eps", "quarterly results", "q1 ", "q2 ", "q3 ", "q4 ",
    "fiscal year", "revenue beat", "revenue miss", "guidance",
    "net income", "earnings call", "conference call",
)
_FILING_KEYWORDS = (
    "10-k", "10-q", "8-k", "sec filing", "edgar", "annual report",
    "quarterly report", "proxy statement", "form 10",
)
_ESTIMATE_KEYWORDS = (
    "analyst-estimates", "analyst estimates", "price-target", "price target",
    "consensus", "sell-side", "analyst forecast", "estimate revision",
    "eps estimate", "revenue estimate",
)
_VALUATION_KEYWORDS = (
    "ratios-ttm", "key-metrics-ttm", "valuation_ratios", "fmp-ratios",
    "pe ratio", "pe-ratio", "ev/ebitda", "price-to-earnings",
    "p/e", "fcf yield", "free cash flow yield", "valuation ratios",
)
_MACRO_KEYWORDS = (
    "federal reserve", "fomc", "interest rate", "inflation", "cpi", "ppi",
    "yield curve", "gdp", "macro", "monetary policy", "credit spread",
    "recession", "unemployment", "jobs report", "nonfarm", "treasury yield",
)


# ── Freshness thresholds (days) ───────────────────────────────────────────────

_THRESHOLDS: Dict[str, Tuple[int, int, int]] = {
    # dimension → (fresh_max, moderate_max, stale_max; >stale_max = very_stale)
    "earnings":  (45,  90,  180),
    "filing":    (90,  180, 365),
    "estimates": (30,  60,  120),
    "valuation": (14,  30,   90),
    "macro":     ( 7,  14,   30),
}

# Priority order for dominant stale dimension selection
_STALENESS_PRIORITY = ("valuation", "estimates", "earnings", "filing", "macro")


# ── Freshness tier labels ─────────────────────────────────────────────────────

TIER_FRESH      = "fresh"
TIER_MODERATE   = "moderate"
TIER_STALE      = "stale"
TIER_VERY_STALE = "very_stale"
TIER_UNKNOWN    = "unknown"


# ── Data structures ───────────────────────────────────────────────────────────

@dataclasses.dataclass
class DimensionFreshness:
    """Freshness state for a single evidence dimension."""
    age_days:  Optional[int]   # None when no timestamps are parseable
    tier:      str             # TIER_* constant
    item_count: int            # number of matching evidence items


@dataclasses.dataclass
class FreshnessProfile:
    """Structured freshness metadata computed from an evidence pool.

    Attributes
    ----------
    earnings   : Freshness of quarterly results / guidance evidence.
    filing     : Freshness of SEC filing evidence.
    estimates  : Freshness of analyst estimate / price-target evidence.
    valuation  : Freshness of live valuation ratio evidence.
    macro      : Freshness of macro / rate environment evidence.

    dominant_stale_dimension : The dimension with the most conviction-relevant
        staleness.  None when no dimension is stale.
    has_any_evidence : True when at least one evidence item was analysed.
    """
    earnings:  DimensionFreshness
    filing:    DimensionFreshness
    estimates: DimensionFreshness
    valuation: DimensionFreshness
    macro:     DimensionFreshness

    dominant_stale_dimension: Optional[str]   # "earnings" | "filing" | ... | None
    has_any_evidence: bool

    # Convenience aliases for backward compat with downstream callers
    @property
    def earnings_age_days(self) -> Optional[int]:
        return self.earnings.age_days

    @property
    def filing_age_days(self) -> Optional[int]:
        return self.filing.age_days

    @property
    def estimate_age_days(self) -> Optional[int]:
        return self.estimates.age_days

    @property
    def valuation_age_days(self) -> Optional[int]:
        return self.valuation.age_days

    @property
    def macro_age_days(self) -> Optional[int]:
        return self.macro.age_days

    def to_dict(self) -> Dict[str, Optional[int]]:
        """Serializable form for API responses and test assertions."""
        return {
            "earnings_age_days":  self.earnings_age_days,
            "filing_age_days":    self.filing_age_days,
            "estimate_age_days":  self.estimate_age_days,
            "valuation_age_days": self.valuation_age_days,
            "macro_age_days":     self.macro_age_days,
            "dominant_stale_dimension": self.dominant_stale_dimension,
        }

    def stale_dimensions(self) -> List[str]:
        """Return all dimensions currently at TIER_STALE or TIER_VERY_STALE."""
        dims = [
            ("earnings",  self.earnings),
            ("filing",    self.filing),
            ("estimates", self.estimates),
            ("valuation", self.valuation),
            ("macro",     self.macro),
        ]
        return [name for name, d in dims if d.tier in (TIER_STALE, TIER_VERY_STALE)]

    def is_dimension_stale(self, dimension: str) -> bool:
        """Return True when the named dimension is stale or very stale."""
        dim = getattr(self, dimension, None)
        if dim is None:
            return False
        return dim.tier in (TIER_STALE, TIER_VERY_STALE)


# ── Timestamp parsing ─────────────────────────────────────────────────────────

_TS_FORMATS = [
    ("%Y-%m-%dT%H:%M:%SZ", 20),
    ("%Y-%m-%dT%H:%M:%S",  19),
    ("%Y-%m-%dT%H:%M",     16),
    ("%Y-%m-%d",            10),
    ("%Y-%m",                7),
]


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    ts_clean = ts.strip()
    for fmt, ln in _TS_FORMATS:
        try:
            return datetime.strptime(ts_clean[:ln], fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _age(ts: Optional[str]) -> Optional[int]:
    dt = _parse_ts(ts)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).days


# ── Keyword matching ──────────────────────────────────────────────────────────

def _matches(ev: RetrievedEvidence, keywords: Tuple[str, ...]) -> bool:
    haystack = " ".join([
        getattr(ev, "title",   "") or "",
        getattr(ev, "source",  "") or "",
        getattr(ev, "summary", "") or "",
    ]).lower()
    return any(kw in haystack for kw in keywords)


# ── Freshness tier classification ─────────────────────────────────────────────

def _tier(age_days: Optional[int], dimension: str) -> str:
    if age_days is None:
        return TIER_UNKNOWN
    fresh_max, moderate_max, stale_max = _THRESHOLDS[dimension]
    if age_days <= fresh_max:
        return TIER_FRESH
    if age_days <= moderate_max:
        return TIER_MODERATE
    if age_days <= stale_max:
        return TIER_STALE
    return TIER_VERY_STALE


# ── Per-dimension analysis ────────────────────────────────────────────────────

def _analyze_dimension(
    evidence: List[RetrievedEvidence],
    keywords: Tuple[str, ...],
    dimension: str,
) -> DimensionFreshness:
    """Find matching items and return the freshness of the MOST RECENT one."""
    now = datetime.now(timezone.utc)
    matching = [ev for ev in evidence if _matches(ev, keywords)]
    if not matching:
        return DimensionFreshness(age_days=None, tier=TIER_UNKNOWN, item_count=0)

    # Take the youngest (smallest age) of the matching items
    ages = [_age(getattr(ev, "timestamp", None)) for ev in matching]
    known = [a for a in ages if a is not None]

    if not known:
        # Items exist but no parseable timestamps — benefit of the doubt: treat as fresh
        return DimensionFreshness(age_days=None, tier=TIER_FRESH, item_count=len(matching))

    min_age = min(known)
    return DimensionFreshness(
        age_days=min_age,
        tier=_tier(min_age, dimension),
        item_count=len(matching),
    )


# ── Dominant stale dimension ──────────────────────────────────────────────────

def _dominant_stale(profile_dict: Dict[str, DimensionFreshness]) -> Optional[str]:
    """Pick the highest-priority dimension that is stale or very stale."""
    for dim in _STALENESS_PRIORITY:
        d = profile_dict.get(dim)
        if d and d.tier in (TIER_STALE, TIER_VERY_STALE):
            return dim
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_evidence_freshness(
    evidence: List[RetrievedEvidence],
) -> FreshnessProfile:
    """Compute a per-dimension freshness profile from an evidence pool.

    Parameters
    ----------
    evidence : Full evidence list from the synthesis pipeline.

    Returns
    -------
    FreshnessProfile with per-dimension age_days, tier, and item_count,
    plus the dominant_stale_dimension for reasoning-language selection.
    """
    dims = {
        "earnings":  _analyze_dimension(evidence, _EARNINGS_KEYWORDS,  "earnings"),
        "filing":    _analyze_dimension(evidence, _FILING_KEYWORDS,     "filing"),
        "estimates": _analyze_dimension(evidence, _ESTIMATE_KEYWORDS,   "estimates"),
        "valuation": _analyze_dimension(evidence, _VALUATION_KEYWORDS,  "valuation"),
        "macro":     _analyze_dimension(evidence, _MACRO_KEYWORDS,      "macro"),
    }
    return FreshnessProfile(
        earnings=dims["earnings"],
        filing=dims["filing"],
        estimates=dims["estimates"],
        valuation=dims["valuation"],
        macro=dims["macro"],
        dominant_stale_dimension=_dominant_stale(dims),
        has_any_evidence=len(evidence) > 0,
    )


# ── Reasoning language helpers ────────────────────────────────────────────────

def freshness_reasoning_clause(profile: FreshnessProfile, ticker: str) -> Optional[str]:
    """Return a specific staleness clause for the conviction reasoning string.

    Returns None when no dimension is stale (no clause needed).

    Examples
    --------
    "Consensus expectations are outdated relative to the current execution environment."
    "The valuation framework still relies on pre-earnings assumptions."
    "Recent filing evidence is absent — balance sheet assumptions may be stale."
    """
    dim = profile.dominant_stale_dimension
    if dim is None:
        return None

    d = getattr(profile, dim)
    age_str = f"{round(d.age_days / 30)} months" if d.age_days is not None else "several months"
    very_stale = d.tier == TIER_VERY_STALE

    if dim == "valuation":
        if very_stale:
            return (
                f"The valuation framework for {ticker} relies on data that is "
                f"approximately {age_str} old — current multiple assumptions are "
                "difficult to anchor without live ratio data."
            )
        return (
            f"The valuation framework still relies on pre-earnings assumptions — "
            f"live ratio data on {ticker} is {age_str} old and may not reflect "
            "recent price action or estimate revisions."
        )

    if dim == "estimates":
        if very_stale:
            return (
                f"Consensus expectations for {ticker} are significantly outdated "
                f"({age_str} old) — the forward earnings trajectory and sell-side "
                "positioning cannot be precisely characterized."
            )
        return (
            f"Consensus expectations are outdated relative to the current execution "
            f"environment — analyst estimates on {ticker} are {age_str} old and "
            "may not reflect the most recent guidance cycle."
        )

    if dim == "earnings":
        if very_stale:
            return (
                f"Quarterly results for {ticker} are approximately {age_str} old — "
                "beat/miss cadence, margin trajectory, and forward guidance are "
                "absent from the evidence base."
            )
        return (
            f"The most recent earnings evidence on {ticker} is {age_str} old — "
            "execution-sensitive assumptions may not reflect the latest results "
            "or management commentary."
        )

    if dim == "filing":
        if very_stale:
            return (
                f"SEC filing evidence for {ticker} is {age_str} old — balance sheet "
                "assumptions, risk factor disclosures, and capital structure may "
                "not reflect the current regulatory picture."
            )
        return (
            f"Recent filing evidence is absent for {ticker} — balance sheet and "
            "risk-factor assumptions may be based on {age_str}-old data."
        )

    if dim == "macro":
        return (
            f"Macro context embedded in the {ticker} thesis may not reflect the "
            "current rate environment — macro evidence is {age_str} old."
        )

    return None
