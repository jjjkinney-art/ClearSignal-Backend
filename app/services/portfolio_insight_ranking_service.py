"""
Portfolio insight ranking service — Phase 10D · Slice 6.

Implements the §3.3 ranking formula from PHASE_10D_PORTFOLIO_INTELLIGENCE_SPEC.md:

    rank_score = base_severity_score
               × portfolio_weight_factor
               × novelty_factor
               × recency_factor

Factor definitions
------------------
base_severity_score
    Canonical severity mapped to numeric value:
    CRITICAL=4, HIGH=3, MEDIUM=2, LOW=1, INFO=0
    (matches the existing severity_model.py ladder)

portfolio_weight_factor
    1.0 + (cluster_weight / total_portfolio_weight)
    A cluster covering 60% of portfolio weight → 1.6×.
    When cluster_weight is None (no explicit weights) → fallback of 1.0.
    total_portfolio_weight defaults to 1.0 (weights normalized to 1).

novelty_factor
    1.0  — never delivered
    0.8  — last delivered > 7 days ago
    0.3  — last delivered within the last 7 days (suppresses re-alerting)

recency_factor
    1.0  — created_at < 24 h ago
    Linear decay from 1.0 → 0.5 over days 1–7.
    0.5  — created_at >= 7 days ago (floor).

stale_input modifier (additive spec extension)
    Stale cross-exposure input (stale_input=True) multiplies the score
    by 0.7 to reflect reduced signal reliability.  This does not appear
    in the base spec formula but is consistent with the staleness-handling
    principle in §2.5.

rank_band assignment (spec §3.3 extension)
    "critical" — rank_score >= 10.0  (CRITICAL × full weight × novelty × recency)
    "high"     — rank_score >= 3.0
    "medium"   — rank_score >= 1.0
    "low"      — rank_score < 1.0

Design constraints
------------------
* No writes beyond updating rank_score and rank_band on PortfolioInsight rows.
* Does NOT touch insight body_json, prose, or regulatory_disclaimer.
* No LLM calls, no delivery, no new intelligence generation.
* Null-session safe: returns an empty RankingResult without raising.
* dry_run=True computes scores and returns the ranked list without persisting.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (spec §3.3)
# ---------------------------------------------------------------------------

# Base severity numeric values — mirror severity_model.py
BASE_SEVERITY: Dict[str, float] = {
    "critical": 4.0,
    "high":     3.0,
    "medium":   2.0,
    "low":      1.0,
    "info":     0.0,
}

# Novelty factor thresholds
_NOVELTY_NEVER_DELIVERED   = 1.0
_NOVELTY_STALE_DELIVERY    = 0.8   # last delivered > 7 days ago
_NOVELTY_RECENT_DELIVERY   = 0.3   # last delivered within 7 days
_NOVELTY_REDELIVERY_DAYS   = 7

# Recency factor bounds
_RECENCY_FRESH_HOURS       = 24    # < 24 h → 1.0
_RECENCY_FLOOR             = 0.5   # floor at 7 days
_RECENCY_DECAY_DAYS        = 7     # linear decay window in days

# Stale-input penalty multiplier (spec §2.5 extension)
_STALE_MULTIPLIER          = 0.7

# Rank-band thresholds (descending)
_BAND_CRITICAL_THRESHOLD   = 10.0
_BAND_HIGH_THRESHOLD       = 3.0
_BAND_MEDIUM_THRESHOLD     = 1.0


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RankedInsight:
    """A PortfolioInsight row augmented with its computed ranking metadata."""

    # Original DB row id
    insight_id: str
    portfolio_id: str
    insight_type: str
    cluster_label: str
    severity: str

    # §3.3 formula components (stored for transparency / debugging)
    base_severity_score: float
    portfolio_weight_factor: float
    novelty_factor: float
    recency_factor: float
    stale_multiplier: float

    # Final score
    rank_score: float
    rank_band: str          # "critical" | "high" | "medium" | "low"

    # Preservation: body prose is never modified
    body_json: str
    stale_input: bool

    # Source timestamps
    created_at_iso: str
    last_delivered_at_iso: Optional[str]


@dataclass
class RankingResult:
    """Summary of one ranking run."""

    portfolio_id: str
    ranked_at: str
    # Insights sorted descending by rank_score.
    insights: List[RankedInsight]
    # Count of rows whose rank_score was updated in the DB.
    rows_updated: int
    # Whether this was a dry run (no DB writes).
    dry_run: bool
    # Regulatory disclaimer — never modified by ranking.
    regulatory_disclaimer: str


# ---------------------------------------------------------------------------
# Factor computations (pure functions, no IO)
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def compute_base_severity_score(severity: str) -> float:
    """Map severity string to its numeric base score."""
    return BASE_SEVERITY.get(severity.lower(), 0.0)


def compute_portfolio_weight_factor(
    cluster_weight: Optional[float],
    total_portfolio_weight: float = 1.0,
) -> float:
    """Compute portfolio_weight_factor per spec §3.3.

    1.0 + (cluster_weight / total_portfolio_weight)
    Fallback to 1.0 when cluster_weight is None.
    """
    if cluster_weight is None:
        return 1.0
    if total_portfolio_weight <= 0:
        return 1.0
    return 1.0 + (float(cluster_weight) / float(total_portfolio_weight))


def compute_novelty_factor(last_delivered_at: Optional[datetime]) -> float:
    """Compute novelty_factor per spec §3.3.

    1.0  — never delivered
    0.8  — last delivered > 7 days ago
    0.3  — last delivered within the last 7 days
    """
    if last_delivered_at is None:
        return _NOVELTY_NEVER_DELIVERED

    # Normalise to UTC.
    if last_delivered_at.tzinfo is None:
        last_delivered_at = last_delivered_at.replace(tzinfo=timezone.utc)

    days_since = (_now_utc() - last_delivered_at).total_seconds() / 86400.0
    if days_since > _NOVELTY_REDELIVERY_DAYS:
        return _NOVELTY_STALE_DELIVERY
    return _NOVELTY_RECENT_DELIVERY


def compute_recency_factor(created_at: datetime) -> float:
    """Compute recency_factor per spec §3.3.

    1.0  — created_at < 24 h ago
    Linear decay from 1.0 → 0.5 over days 1–7.
    0.5  — created_at >= 7 days ago (floor).
    """
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    age_hours = (_now_utc() - created_at).total_seconds() / 3600.0

    if age_hours < _RECENCY_FRESH_HOURS:
        return 1.0

    age_days = age_hours / 24.0
    if age_days >= _RECENCY_DECAY_DAYS:
        return _RECENCY_FLOOR

    # Linear interpolation: 1.0 at day 1 → 0.5 at day 7.
    t = (age_days - 1.0) / (_RECENCY_DECAY_DAYS - 1.0)   # 0.0 → 1.0
    return 1.0 - t * (1.0 - _RECENCY_FLOOR)


def compute_rank_score(
    severity: str,
    cluster_weight: Optional[float],
    total_portfolio_weight: float,
    last_delivered_at: Optional[datetime],
    created_at: datetime,
    stale_input: bool,
) -> tuple:
    """Return (rank_score, base_sev, weight_factor, novelty, recency, stale_mult)."""
    base = compute_base_severity_score(severity)
    weight = compute_portfolio_weight_factor(cluster_weight, total_portfolio_weight)
    novelty = compute_novelty_factor(last_delivered_at)
    recency = compute_recency_factor(created_at)
    stale = _STALE_MULTIPLIER if stale_input else 1.0

    score = base * weight * novelty * recency * stale
    return score, base, weight, novelty, recency, stale


def assign_rank_band(rank_score: float) -> str:
    """Assign a rank band label based on the computed score."""
    if rank_score >= _BAND_CRITICAL_THRESHOLD:
        return "critical"
    if rank_score >= _BAND_HIGH_THRESHOLD:
        return "high"
    if rank_score >= _BAND_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _load_insights(session, portfolio_id: str) -> list:
    try:
        from app.db.models import PortfolioInsight
        from sqlalchemy import select
        result = await session.execute(
            select(PortfolioInsight)
            .where(PortfolioInsight.portfolio_id == portfolio_id)
        )
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[portfolio_ranking] load_insights failed: %r", exc)
        return []


async def _load_total_tickers(session, portfolio_id: str) -> int:
    try:
        from app.db.models import PortfolioPosition
        from sqlalchemy import select, func
        result = await session.execute(
            select(func.count(PortfolioPosition.id))
            .where(PortfolioPosition.portfolio_id == portfolio_id)
            .where(PortfolioPosition.active.is_(True))
        )
        return result.scalar() or 0
    except Exception as exc:
        logger.warning("[portfolio_ranking] load_total_tickers failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def rank_portfolio_insights(
    session,
    portfolio_id: str,
    total_portfolio_weight: float = 1.0,
    dry_run: bool = False,
) -> RankingResult:
    """Rank all PortfolioInsight rows for a portfolio and persist rank_score.

    Args:
        session: AsyncSession or None (null-session safe).
        portfolio_id: The portfolio to rank insights for.
        total_portfolio_weight: Total normalised weight denominator for the
            portfolio_weight_factor.  Defaults to 1.0 (weights already
            normalised to sum to 1).
        dry_run: If True, compute scores but do not write to DB.

    Returns a RankingResult with insights sorted descending by rank_score.

    This function NEVER:
      * modifies insight body_json or prose
      * calls an LLM
      * triggers delivery
    """
    from app.services.portfolio_insight_service import REGULATORY_DISCLAIMER

    ranked_at = _now_utc().isoformat()

    if session is None:
        return RankingResult(
            portfolio_id=portfolio_id,
            ranked_at=ranked_at,
            insights=[],
            rows_updated=0,
            dry_run=dry_run,
            regulatory_disclaimer=REGULATORY_DISCLAIMER,
        )

    rows = await _load_insights(session, portfolio_id)
    if not rows:
        return RankingResult(
            portfolio_id=portfolio_id,
            ranked_at=ranked_at,
            insights=[],
            rows_updated=0,
            dry_run=dry_run,
            regulatory_disclaimer=REGULATORY_DISCLAIMER,
        )

    ranked: List[RankedInsight] = []
    rows_updated = 0

    for row in rows:
        # Parse created_at — handle both tz-aware and tz-naive.
        created_at = row.created_at
        if created_at is None:
            created_at = _now_utc()
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # last_delivered_at is None until Slice 7 delivery runs.
        last_delivered = row.last_delivered_at

        score, base, weight_f, novelty, recency, stale_mult = compute_rank_score(
            severity=row.severity,
            cluster_weight=row.cluster_weight,
            total_portfolio_weight=total_portfolio_weight,
            last_delivered_at=last_delivered,
            created_at=created_at,
            stale_input=bool(row.stale_input),
        )

        band = assign_rank_band(score)

        # Build RankedInsight (never mutates body_json).
        last_del_iso = (
            last_delivered.isoformat() if last_delivered is not None else None
        )
        ranked.append(RankedInsight(
            insight_id=row.id,
            portfolio_id=row.portfolio_id,
            insight_type=row.insight_type,
            cluster_label=row.cluster_label,
            severity=row.severity,
            base_severity_score=base,
            portfolio_weight_factor=weight_f,
            novelty_factor=novelty,
            recency_factor=recency,
            stale_multiplier=stale_mult,
            rank_score=score,
            rank_band=band,
            body_json=row.body_json,
            stale_input=bool(row.stale_input),
            created_at_iso=created_at.isoformat(),
            last_delivered_at_iso=last_del_iso,
        ))

        # Persist rank_score back to the DB row (Slice 6 stamps this).
        if not dry_run:
            row.rank_score = score
            rows_updated += 1

    if not dry_run and rows_updated > 0:
        try:
            await session.flush()
        except Exception as exc:
            logger.warning("[portfolio_ranking] flush failed: %r", exc)

    # Sort descending by rank_score, then by insight_id for determinism.
    ranked.sort(key=lambda r: (-r.rank_score, r.insight_id))

    return RankingResult(
        portfolio_id=portfolio_id,
        ranked_at=ranked_at,
        insights=ranked,
        rows_updated=rows_updated,
        dry_run=dry_run,
        regulatory_disclaimer=REGULATORY_DISCLAIMER,
    )


def rank_candidates_in_memory(
    candidates: List[dict],
    total_portfolio_weight: float = 1.0,
) -> List[dict]:
    """Rank a list of candidate dicts (no DB required).

    Each dict must contain:
        severity, cluster_weight (Optional[float]),
        stale_input (bool), created_at (datetime),
        last_delivered_at (Optional[datetime]).

    Returns the list sorted descending by rank_score with 'rank_score'
    and 'rank_band' keys added.  Input dicts are NOT mutated.
    """
    results = []
    for c in candidates:
        score, base, weight_f, novelty, recency, stale_mult = compute_rank_score(
            severity=c.get("severity", "info"),
            cluster_weight=c.get("cluster_weight"),
            total_portfolio_weight=total_portfolio_weight,
            last_delivered_at=c.get("last_delivered_at"),
            created_at=c.get("created_at", _now_utc()),
            stale_input=bool(c.get("stale_input", False)),
        )
        enriched = dict(c)
        enriched["rank_score"] = score
        enriched["rank_band"] = assign_rank_band(score)
        results.append(enriched)

    results.sort(key=lambda x: (-x["rank_score"], str(x.get("cluster_label", ""))))
    return results
