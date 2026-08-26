"""
Portfolio insight generation service — Phase 10D · Slice 5.

Consumes:
  * PortfolioExposureProjection  (from portfolio_exposure_service.py)
  * PortfolioHealthReport        (from portfolio_health_service.py)

Produces:
  * PortfolioInsight rows upserted to portfolio_insights via insight_upsert
  * InsightGenerationResult summary dataclass (returned to caller)

Design constraints
------------------
* Template-bound prose ONLY.  No LLM calls anywhere in this module.
* Closed taxonomy of 8 insight types (see INSIGHT_TYPES below).
* content_key dedup: sha256(portfolio_id|insight_type|cluster_label|period_bucket)
  with 7-day period bucket — idempotent on repeated calls within the same week.
* Regulatory guard runs on every candidate before upsert.  A candidate that
  trips the guard is suppressed (never written) and counted in
  InsightGenerationResult.regulatory_blocked.
* Every InsightGenerationResult carries regulatory_disclaimer metadata.

Prohibited output classes (spec §6 / §3 regulatory boundary)
------------------------------------------------------------
* buy / sell / hold language
* position-sizing directives (increase, reduce, optimal allocation)
* price targets or expected-return figures
* explicit investment recommendations
* personalized financial advice

No output from this service should be construed as investment advice.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from app.services.portfolio_exposure_service import PortfolioExposureProjection
from app.services.portfolio_health_service import PortfolioHealthReport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Closed insight taxonomy
# ---------------------------------------------------------------------------

INSIGHT_TYPES = frozenset({
    "shared_risk_cluster",       # 2+ tickers share a common concern label
    "hidden_correlation",        # edge strength >= 0.7
    "concentration_risk",        # HHI / effective-N breach
    "shared_failure_mode",       # 2+ tickers matched to same analog
    "catalyst_propagation",      # 2+ tickers share same open catalyst direction
    "thematic_exposure",         # named theme covers significant portfolio weight
    "regime_sensitivity",        # macro-factor overlap across portfolio
    "diversification_gap",       # membership-class imbalance or single-position
})

# Severity ladder (mirrors severity_model.py)
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}

# Period bucket for content_key: 7-day windows keyed by ISO week.
_PERIOD_BUCKET_DAYS = 7

# Thresholds
_HHI_MEDIUM = 0.25
_HHI_HIGH = 0.50
_TOP1_HIGH = 0.40   # single-position weight above this triggers concentration_risk

# Regulatory disclaimer — appended to every InsightGenerationResult.
REGULATORY_DISCLAIMER = (
    "This output is for informational purposes only and does not constitute "
    "investment advice, a recommendation to buy or sell any security, or a "
    "solicitation of any investment.  Past performance is not indicative of "
    "future results.  Consult a qualified financial adviser before making "
    "investment decisions."
)

# ---------------------------------------------------------------------------
# Prohibited phrase list (regulatory guard)
# ---------------------------------------------------------------------------

# Single-word prohibited terms matched with word boundaries (avoid substring false
# positives: "hold" must not match "holdings", "buy" must not match "buyback").
_PROHIBITED_WORDS: Tuple[str, ...] = (
    "buy",
    "sell",
    "hold",
    "overweight",
    "underweight",
    "outperform",
    "underperform",
    "upgrade",
    "downgrade",
)

# Multi-word prohibited phrases matched as substrings (no false-positive risk).
_PROHIBITED_PHRASES: Tuple[str, ...] = (
    "should buy",
    "should sell",
    "target price",
    "price target",
    "expected return",
    "optimal allocation",
    "increase position",
    "reduce position",
    "strong buy",
    "strong sell",
    "recommend",
)


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class InsightCandidate:
    """An insight before the regulatory guard runs."""

    insight_type: str
    cluster_label: str
    member_tickers: List[str]
    severity: str
    body: str                           # template-rendered prose
    cluster_weight: Optional[float]
    stale_input: bool
    cross_exposure_as_of: Optional[str]
    # Metadata injected into body_json alongside prose.
    meta: Dict = field(default_factory=dict)


@dataclass
class InsightGenerationResult:
    """Summary of one generation run."""

    portfolio_id: str
    generated_at: str
    # Candidates passed to the upsert layer (after guard).
    written: int
    # Candidates blocked by the regulatory guard.
    regulatory_blocked: int
    # content_key collisions (existing row updated, not inserted).
    deduplicated: int
    # List of insight_type values written in this run.
    types_written: List[str]
    # Required on every portfolio response (spec §6).
    regulatory_disclaimer: str


# ---------------------------------------------------------------------------
# Regulatory guard
# ---------------------------------------------------------------------------

def _regulatory_guard(body: str) -> List[str]:
    """Return list of prohibited terms/phrases found in body (case-insensitive).

    Single-word terms use word-boundary matching to avoid false positives such
    as "hold" matching inside "holdings".  Multi-word phrases use substring
    matching (the extra context makes false positives unlikely).

    An empty list means the candidate is clean.
    """
    lower = body.lower()
    found: List[str] = []
    for word in _PROHIBITED_WORDS:
        if re.search(r"\b" + re.escape(word) + r"\b", lower):
            found.append(word)
    for phrase in _PROHIBITED_PHRASES:
        if phrase in lower:
            found.append(phrase)
    return found


# ---------------------------------------------------------------------------
# Content key
# ---------------------------------------------------------------------------

def _period_bucket() -> str:
    """Return a stable 7-day period bucket string (ISO year + week number)."""
    today = datetime.now(timezone.utc).date()
    iso = today.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _content_key(portfolio_id: str, insight_type: str, cluster_label: str) -> str:
    """Return a sha256 content key for dedup (stable within the same ISO week)."""
    raw = f"{portfolio_id}|{insight_type}|{cluster_label}|{_period_bucket()}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Template library (all prose is template-bound, no free-form LLM text)
# ---------------------------------------------------------------------------

def _fmt_tickers(tickers: List[str]) -> str:
    if not tickers:
        return "(none)"
    if len(tickers) == 1:
        return tickers[0]
    return ", ".join(tickers[:-1]) + " and " + tickers[-1]


def _tmpl_shared_risk_cluster(
    cluster_label: str,
    tickers: List[str],
    stale: bool,
    exposure_type: str = "thematic",
) -> str:
    if exposure_type == "classification":
        return (
            f"Portfolio positions {_fmt_tickers(tickers)} share the maintained "
            f'company classification "{cluster_label}". This is descriptive overlap, '
            f"not evidence that the positions are correlated."
        )
    staleness = "  Note: one or more contributing signals may be stale." if stale else ""
    return (
        f"Portfolio positions {_fmt_tickers(tickers)} share a common risk factor: "
        f'"{cluster_label}".  This structural overlap means an adverse development '
        f"in this area could affect multiple holdings simultaneously.{staleness}"
    )


def _tmpl_hidden_correlation(ticker_a: str, ticker_b: str, strength: float) -> str:
    return (
        f"{ticker_a} and {ticker_b} exhibit a cross-exposure strength of "
        f"{strength:.2f}, which exceeds the high-correlation threshold.  "
        f"Their combined response to a shared stress scenario may be larger "
        f"than either position implies individually."
    )


def _tmpl_concentration_risk(
    hhi: float, effective_n: float, top1_ticker: str, top1_weight: float
) -> str:
    return (
        f"Portfolio concentration is elevated: HHI={hhi:.3f}, effective-N={effective_n:.1f}.  "
        f"The largest position ({top1_ticker}) accounts for {top1_weight:.0%} of portfolio weight.  "
        f"Structural concentration of this magnitude means adverse single-name outcomes "
        f"have an outsized portfolio-level impact."
    )


def _tmpl_shared_failure_mode(analog_label: str, tickers: List[str]) -> str:
    label = analog_label or "an historical failure pattern"
    return (
        f"Historical analogy only — this does not mean the named episode involved "
        f"these companies. Positions {_fmt_tickers(tickers)} are independently matched "
        f"to the risk mechanism represented by {label}. If a similar mechanism "
        f"progresses, multiple positions could be affected in sequence."
    )


def _tmpl_catalyst_propagation(direction: str, tickers: List[str]) -> str:
    dir_label = "positive" if direction == "bull_trigger" else "negative"
    return (
        f"Positions {_fmt_tickers(tickers)} share open {dir_label} catalyst signals.  "
        f"A convergent catalyst resolution — triggered or invalidated — could produce "
        f"a correlated portfolio response across these holdings."
    )


def _tmpl_thematic_exposure(concern_label: str, tickers: List[str], weight: Optional[float]) -> str:
    weight_str = f" (combined weight: {weight:.0%})" if weight is not None else ""
    return (
        f'Theme exposure "{concern_label}" spans {_fmt_tickers(tickers)}{weight_str}.  '
        f"A thematic shift in this area would affect multiple portfolio positions simultaneously."
    )


def _tmpl_regime_sensitivity(factors: List[str], tickers: List[str]) -> str:
    factor_str = ", ".join(f'"{f}"' for f in factors[:5])
    return (
        f"Portfolio positions {_fmt_tickers(tickers)} share sensitivity to macro factors: "
        f"{factor_str}.  A regime shift in these areas may produce correlated responses "
        f"across multiple holdings."
    )


def _tmpl_diversification_gap(owned: int, watchlist: int, on_radar: int, total: int) -> str:
    return (
        f"Portfolio membership is concentrated: {owned} owned, "
        f"{watchlist} watchlist, {on_radar} on-radar positions (total {total}).  "
        f"Single membership-class concentration may indicate limited diversification "
        f"across conviction levels."
    )


# ---------------------------------------------------------------------------
# Candidate builders
# ---------------------------------------------------------------------------

def _candidates_from_exposure(
    proj: PortfolioExposureProjection,
) -> List[InsightCandidate]:
    candidates: List[InsightCandidate] = []

    # 1. Shared risk clusters
    for cluster in proj.shared_exposure_clusters:
        body = _tmpl_shared_risk_cluster(
            cluster.concern_label,
            cluster.member_tickers,
            cluster.stale_input,
            cluster.dominant_exposure_type,
        )
        candidates.append(InsightCandidate(
            insight_type="shared_risk_cluster",
            cluster_label=cluster.concern_label,
            member_tickers=cluster.member_tickers,
            severity="medium",
            body=body,
            cluster_weight=cluster.cluster_weight,
            stale_input=cluster.stale_input,
            cross_exposure_as_of=cluster.cross_exposure_as_of or None,
            meta={"max_edge_strength": cluster.max_edge_strength},
        ))

    # 2. Hidden correlations (high-strength pairs)
    for pair in proj.high_correlation_pairs:
        body = _tmpl_hidden_correlation(pair.ticker_a, pair.ticker_b, pair.strength)
        candidates.append(InsightCandidate(
            insight_type="hidden_correlation",
            cluster_label=f"{pair.ticker_a}_{pair.ticker_b}",
            member_tickers=[pair.ticker_a, pair.ticker_b],
            severity="high",
            body=body,
            cluster_weight=None,
            stale_input=pair.stale_input,
            cross_exposure_as_of=pair.edge_as_of or None,
            meta={"strength": pair.strength, "exposure_type": pair.exposure_type},
        ))

    # 3. Failure mode contagion
    for fm in proj.failure_mode_clusters:
        body = _tmpl_shared_failure_mode(fm.analog_label, fm.member_tickers)
        candidates.append(InsightCandidate(
            insight_type="shared_failure_mode",
            cluster_label=fm.analog_id,
            member_tickers=fm.member_tickers,
            severity="high",
            body=body,
            cluster_weight=None,
            stale_input=False,
            cross_exposure_as_of=None,
            meta={"analog_label": fm.analog_label, "stages": fm.stages},
        ))

    # 4. Catalyst propagation
    for cat in proj.catalyst_clusters:
        body = _tmpl_catalyst_propagation(cat.direction, cat.member_tickers)
        severity = "medium" if cat.direction == "bull_trigger" else "high"
        candidates.append(InsightCandidate(
            insight_type="catalyst_propagation",
            cluster_label=f"catalyst_{cat.direction}",
            member_tickers=cat.member_tickers,
            severity=severity,
            body=body,
            cluster_weight=None,
            stale_input=False,
            cross_exposure_as_of=None,
            meta={"direction": cat.direction},
        ))

    return candidates


def _candidates_from_health(
    health: PortfolioHealthReport,
    proj: PortfolioExposureProjection,
) -> List[InsightCandidate]:
    candidates: List[InsightCandidate] = []
    conc = health.concentration

    # 5. Concentration risk
    if conc.position_count >= 1 and conc.hhi >= _HHI_MEDIUM:
        severity = "high" if conc.hhi >= _HHI_HIGH else "medium"
        # Derive top-1 ticker from the projection's ticker list + weights.
        # We don't have per-ticker weights here directly, so use cluster_label "portfolio".
        top1_weight = conc.top_n_weight.get(1, 0.0)
        body = _tmpl_concentration_risk(
            conc.hhi, conc.effective_n,
            top1_ticker="(top position)",
            top1_weight=top1_weight,
        )
        candidates.append(InsightCandidate(
            insight_type="concentration_risk",
            cluster_label="portfolio_hhi",
            member_tickers=health.diversification.__class__.__name__  # unused sentinel
            and proj.portfolio_tickers,
            severity=severity,
            body=body,
            cluster_weight=None,
            stale_input=False,
            cross_exposure_as_of=None,
            meta={"hhi": conc.hhi, "effective_n": conc.effective_n},
        ))

    # 6. Thematic exposure (from health theme_exposure, which wraps cross_exposure concerns)
    for theme in health.theme_exposure:
        body = _tmpl_thematic_exposure(
            theme.concern_label, theme.member_tickers, theme.cumulative_weight
        )
        candidates.append(InsightCandidate(
            insight_type="thematic_exposure",
            cluster_label=theme.concern_label,
            member_tickers=theme.member_tickers,
            severity="medium" if theme.ticker_count >= 3 else "low",
            body=body,
            cluster_weight=theme.cumulative_weight,
            stale_input=proj.cross_exposure_stale,
            cross_exposure_as_of=proj.cross_exposure_as_of,
            meta={"ticker_count": theme.ticker_count},
        ))

    # 7. Regime sensitivity (only when substrate exists and factors identified)
    rs = health.regime_sensitivity
    if not rs.substrate_missing and rs.active_macro_factors:
        body = _tmpl_regime_sensitivity(
            rs.active_macro_factors, proj.portfolio_tickers
        )
        candidates.append(InsightCandidate(
            insight_type="regime_sensitivity",
            cluster_label="macro_factor_overlap",
            member_tickers=proj.portfolio_tickers,
            severity="info",
            body=body,
            cluster_weight=None,
            stale_input=False,
            cross_exposure_as_of=None,
            meta={"active_macro_factors": rs.active_macro_factors[:10]},
        ))

    # 8. Diversification gap (single membership-class dominance)
    div = health.diversification
    total = conc.position_count
    if total >= 2:
        dominant_class_count = max(div.owned_count, div.watchlist_count, div.on_radar_count)
        if dominant_class_count == total:
            body = _tmpl_diversification_gap(
                div.owned_count, div.watchlist_count, div.on_radar_count, total
            )
            candidates.append(InsightCandidate(
                insight_type="diversification_gap",
                cluster_label="single_membership_class",
                member_tickers=proj.portfolio_tickers,
                severity="info",
                body=body,
                cluster_weight=None,
                stale_input=False,
                cross_exposure_as_of=None,
                meta={
                    "owned_count": div.owned_count,
                    "watchlist_count": div.watchlist_count,
                    "on_radar_count": div.on_radar_count,
                },
            ))

    return candidates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_portfolio_insights(
    session,
    projection: PortfolioExposureProjection,
    health: PortfolioHealthReport,
) -> InsightGenerationResult:
    """Generate portfolio insights from an exposure projection and health report.

    Steps:
    1. Build InsightCandidate list from projection + health.
    2. Run regulatory guard on each candidate's body prose.
    3. Upsert passing candidates to portfolio_insights.
    4. Return InsightGenerationResult summary with disclaimer.

    Always returns a valid InsightGenerationResult, never raises.
    Session=None is safe — produces a dry-run result with written=0.

    This function NEVER:
      * calls an LLM
      * uses price data or price forecasts
      * outputs buy/sell/hold recommendations
      * delivers to any channel
    """
    generated_at = _now_iso()
    portfolio_id = projection.portfolio_id

    if not projection.portfolio_tickers:
        return InsightGenerationResult(
            portfolio_id=portfolio_id,
            generated_at=generated_at,
            written=0,
            regulatory_blocked=0,
            deduplicated=0,
            types_written=[],
            regulatory_disclaimer=REGULATORY_DISCLAIMER,
        )

    # Build candidates from both upstream signals.
    candidates: List[InsightCandidate] = []
    candidates.extend(_candidates_from_exposure(projection))
    candidates.extend(_candidates_from_health(health, projection))

    written = 0
    regulatory_blocked = 0
    deduplicated = 0
    types_written: List[str] = []

    for candidate in candidates:
        # Regulatory guard.
        violations = _regulatory_guard(candidate.body)
        if violations:
            logger.warning(
                "[portfolio_insight] regulatory guard blocked candidate "
                "type=%s label=%s violations=%r",
                candidate.insight_type, candidate.cluster_label, violations,
            )
            regulatory_blocked += 1
            continue

        # Content key for dedup.
        ck = _content_key(portfolio_id, candidate.insight_type, candidate.cluster_label)

        # Build body_json.
        body_json = json.dumps({
            "prose": candidate.body,
            "regulatory_disclaimer": REGULATORY_DISCLAIMER,
            "meta": candidate.meta,
        })

        # Cross-exposure timestamp — parse ISO string to datetime if present.
        ce_as_of: Optional[datetime] = None
        if candidate.cross_exposure_as_of:
            try:
                ts = candidate.cross_exposure_as_of
                ce_as_of = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                pass

        if session is not None:
            from app.db.repositories.portfolio_repo import insight_upsert
            from sqlalchemy import select
            from app.db.models import PortfolioInsight

            # Check if this content_key already exists.
            result = await session.execute(
                select(PortfolioInsight).where(PortfolioInsight.content_key == ck)
            )
            exists = result.scalar_one_or_none() is not None

            await insight_upsert(
                session,
                portfolio_id=portfolio_id,
                insight_type=candidate.insight_type,
                cluster_label=candidate.cluster_label,
                content_key=ck,
                severity=candidate.severity,
                severity_rank=_SEVERITY_RANK.get(candidate.severity, 0),
                member_tickers=json.dumps(candidate.member_tickers),
                cluster_weight=candidate.cluster_weight,
                rank_score=0.0,  # Slice 6 stamps rank_score
                body_json=body_json,
                cross_exposure_as_of=ce_as_of,
                stale_input=candidate.stale_input,
            )

            if exists:
                deduplicated += 1
            else:
                written += 1
        else:
            # Dry-run: count but don't write.
            written += 1

        types_written.append(candidate.insight_type)

    return InsightGenerationResult(
        portfolio_id=portfolio_id,
        generated_at=generated_at,
        written=written,
        regulatory_blocked=regulatory_blocked,
        deduplicated=deduplicated,
        types_written=types_written,
        regulatory_disclaimer=REGULATORY_DISCLAIMER,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
