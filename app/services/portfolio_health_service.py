"""
Portfolio health metrics service — Phase 10D · Slice 4.

Computes read-only structural health metrics for a portfolio.

Approved inputs
---------------
* portfolio_positions  — weights, membership_class, active flag
* cross_exposures      — shared_concerns labels for thematic exposure (Slice 3
                         already reads these; here we reuse the concern set)
* thesis_versions      — macro_sensitivity JSON field (latest row per ticker)
* dossier_durability   — cycle_position, conviction_trend, horizon_hint

Prohibited inputs (spec §4 prohibition list)
--------------------------------------------
* price history, price-derived volatility, beta, VaR, Sharpe
* expected return / return forecast
* any composite risk score that wraps a prohibited sub-metric

Weight handling
---------------
If every active position carries a non-None weight the report uses
weight_source="explicit".  If any weight is None the service falls back to
equal-weight (1/N) for all positions and sets weight_source="equal_weight_fallback".
Weights are NEVER inferred from prices.

Design constraints
------------------
* No writes to any table.
* No LLM calls.
* No insight rows, no delivery rows, no notification rows.
* Null-session / empty-portfolio → PortfolioHealthReport with safe empty/zero values.
* All returned types are plain Python dataclasses — no ORM objects escape.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum number of positions reported in top-N concentration.
TOP_N: int = 5


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ConcentrationMetrics:
    """Concentration measures computed from position weights."""

    # Herfindahl-Hirschman Index: sum(w_i^2).  Range [1/N, 1].
    hhi: float

    # Top-1 through top-N cumulative weight (dict keyed by N).
    # e.g. {1: 0.30, 3: 0.65, 5: 0.80}
    top_n_weight: Dict[int, float]

    # 1 / HHI — the number of equally-sized positions with the same HHI.
    effective_n: float

    # Total active positions.
    position_count: int

    # The N used for top_n_weight (min(TOP_N, position_count)).
    top_n_used: int


@dataclass
class DiversificationMetrics:
    """Membership-class breakdown and weight distribution."""

    owned_count: int
    watchlist_count: int
    on_radar_count: int

    # Weight share carried by each membership class (0–1 each).
    owned_weight: float
    watchlist_weight: float
    on_radar_weight: float


@dataclass
class ThemeExposure:
    """A concern/theme label shared across two or more portfolio tickers."""

    concern_label: str
    member_tickers: List[str]
    # Sum of weights for member tickers; None when equal-weight fallback used.
    cumulative_weight: Optional[float]
    # Number of portfolio tickers exposed to this theme.
    ticker_count: int


@dataclass
class RegimeSensitivitySummary:
    """Aggregate regime-sensitivity signals from approved substrate only.

    Built from thesis_versions.macro_sensitivity JSON fields and
    dossier_durability rows.  No price data.  No beta.
    """

    # All distinct macro factors named across position tickers (from macro_sensitivity keys).
    active_macro_factors: List[str]

    # Distribution of cycle_position values across tickers with DossierDurability rows.
    # {cycle_position_value: count}  e.g. {"early": 2, "mid": 1}
    cycle_position_distribution: Dict[str, int]

    # Distribution of conviction_trend values.
    conviction_trend_distribution: Dict[str, int]

    # Distribution of horizon_hint values.
    horizon_hint_distribution: Dict[str, int]

    # Tickers for which no durability row was found.
    tickers_without_durability: List[str]

    # True when NO substrate rows were available (table missing or empty for all tickers).
    substrate_missing: bool


@dataclass
class HealthWarning:
    """A structural health warning surfaced by the health service."""

    code: str           # machine-readable e.g. "HIGH_CONCENTRATION"
    message: str        # human-readable, template-bound (no LLM prose)
    severity: str       # "info" | "medium" | "high"


@dataclass
class PortfolioHealthReport:
    """Full health report for one portfolio.

    All sub-objects are safe defaults when the portfolio is empty or the
    session is None.
    """

    portfolio_id: str
    generated_at: str
    # "explicit" | "equal_weight_fallback"
    weight_source: str

    concentration: ConcentrationMetrics
    diversification: DiversificationMetrics
    theme_exposure: List[ThemeExposure]
    regime_sensitivity: RegimeSensitivitySummary
    warnings: List[HealthWarning]


# ---------------------------------------------------------------------------
# Safe defaults
# ---------------------------------------------------------------------------

def _empty_concentration() -> ConcentrationMetrics:
    return ConcentrationMetrics(
        hhi=0.0,
        top_n_weight={},
        effective_n=0.0,
        position_count=0,
        top_n_used=0,
    )


def _empty_diversification() -> DiversificationMetrics:
    return DiversificationMetrics(
        owned_count=0,
        watchlist_count=0,
        on_radar_count=0,
        owned_weight=0.0,
        watchlist_weight=0.0,
        on_radar_weight=0.0,
    )


def _empty_regime() -> RegimeSensitivitySummary:
    return RegimeSensitivitySummary(
        active_macro_factors=[],
        cycle_position_distribution={},
        conviction_trend_distribution={},
        horizon_hint_distribution={},
        tickers_without_durability=[],
        substrate_missing=True,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# DB loaders — each returns a safe empty on any exception
# ---------------------------------------------------------------------------

async def _load_positions(session, portfolio_id: str) -> list:
    try:
        from app.db.models import PortfolioPosition
        from sqlalchemy import select
        result = await session.execute(
            select(PortfolioPosition)
            .where(PortfolioPosition.portfolio_id == portfolio_id)
            .where(PortfolioPosition.active.is_(True))
        )
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[portfolio_health] load_positions failed: %r", exc)
        return []


async def _load_cross_exposure_concerns(session, tickers: set) -> Dict[str, List[str]]:
    """Return {concern_label: [ticker_a, ticker_b, ...]} for edges within tickers."""
    if len(tickers) < 2:
        return {}
    try:
        from app.db.models import CrossExposure
        from sqlalchemy import select
        result = await session.execute(
            select(CrossExposure)
            .where(CrossExposure.ticker_a.in_(tickers))
        )
        rows = result.scalars().all()
        concern_map: Dict[str, set] = {}
        for row in rows:
            if row.ticker_b not in tickers:
                continue
            concerns = _parse_json_list(row.shared_concerns)
            for c in concerns:
                if c not in concern_map:
                    concern_map[c] = set()
                concern_map[c].add(row.ticker_a)
                concern_map[c].add(row.ticker_b)
        return {k: sorted(v) for k, v in concern_map.items()}
    except Exception as exc:
        logger.warning("[portfolio_health] load_cross_exposure_concerns failed: %r", exc)
        return {}


async def _load_macro_sensitivity(session, tickers: set) -> Dict[str, dict]:
    """Return {ticker: macro_sensitivity_dict} from the latest ThesisVersion per ticker."""
    if not tickers:
        return {}
    try:
        from app.db.models import ThesisVersion
        from sqlalchemy import select
        result = await session.execute(
            select(ThesisVersion.ticker, ThesisVersion.macro_sensitivity)
            .where(ThesisVersion.ticker.in_(tickers))
            .order_by(ThesisVersion.created_at.desc())
        )
        rows = result.all()
        # Latest row per ticker.
        seen: Dict[str, dict] = {}
        for ticker, macro_raw in rows:
            if ticker in seen:
                continue
            try:
                val = json.loads(macro_raw) if isinstance(macro_raw, str) else (macro_raw or {})
                seen[ticker] = val if isinstance(val, dict) else {}
            except Exception:
                seen[ticker] = {}
        return seen
    except Exception as exc:
        logger.warning("[portfolio_health] load_macro_sensitivity failed: %r", exc)
        return {}


async def _load_durability(session, tickers: set) -> Dict[str, object]:
    """Return {ticker: DossierDurability row} for portfolio tickers."""
    if not tickers:
        return {}
    try:
        from app.db.models import DossierDurability
        from sqlalchemy import select
        result = await session.execute(
            select(DossierDurability)
            .where(DossierDurability.ticker.in_(tickers))
        )
        return {row.ticker: row for row in result.scalars().all()}
    except Exception as exc:
        logger.warning("[portfolio_health] load_durability failed: %r", exc)
        return {}


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------

def _parse_json_list(raw) -> List[str]:
    try:
        val = json.loads(raw or "[]")
        if isinstance(val, list):
            return [str(x) for x in val]
    except Exception:
        pass
    return []


def _resolve_weights(positions: list) -> tuple:
    """Return (weights_dict, weight_source) where weights_dict is {ticker: weight}.

    Uses explicit weights when all positions have one; equal-weight fallback otherwise.
    """
    if not positions:
        return {}, "equal_weight_fallback"

    has_all = all(p.weight is not None for p in positions)
    if has_all:
        total = sum(float(p.weight) for p in positions)
        if total > 0:
            # Normalize to ensure they sum to 1.
            return {p.ticker: float(p.weight) / total for p in positions}, "explicit"

    # Equal-weight fallback.
    n = len(positions)
    return {p.ticker: 1.0 / n for p in positions}, "equal_weight_fallback"


def _compute_concentration(positions: list, weights: Dict[str, float]) -> ConcentrationMetrics:
    if not positions:
        return _empty_concentration()

    n = len(positions)
    w_list = sorted([weights.get(p.ticker, 0.0) for p in positions], reverse=True)

    hhi = sum(w * w for w in w_list)
    effective_n = 1.0 / hhi if hhi > 0 else float(n)

    top_n_used = min(TOP_N, n)
    top_n_weight: Dict[int, float] = {}
    cumulative = 0.0
    for i, w in enumerate(w_list[:top_n_used], start=1):
        cumulative += w
        top_n_weight[i] = round(cumulative, 6)

    return ConcentrationMetrics(
        hhi=round(hhi, 6),
        top_n_weight=top_n_weight,
        effective_n=round(effective_n, 4),
        position_count=n,
        top_n_used=top_n_used,
    )


def _compute_diversification(
    positions: list, weights: Dict[str, float]
) -> DiversificationMetrics:
    owned = [p for p in positions if p.membership_class == "owned"]
    watchlist = [p for p in positions if p.membership_class == "watchlist"]
    on_radar = [p for p in positions if p.membership_class == "on_radar"]

    def _wsum(ps) -> float:
        return round(sum(weights.get(p.ticker, 0.0) for p in ps), 6)

    return DiversificationMetrics(
        owned_count=len(owned),
        watchlist_count=len(watchlist),
        on_radar_count=len(on_radar),
        owned_weight=_wsum(owned),
        watchlist_weight=_wsum(watchlist),
        on_radar_weight=_wsum(on_radar),
    )


def _compute_theme_exposure(
    concern_map: Dict[str, List[str]],
    weights: Dict[str, float],
    weight_source: str,
) -> List[ThemeExposure]:
    themes: List[ThemeExposure] = []
    for concern, tickers in concern_map.items():
        if len(tickers) < 2:
            continue
        if weight_source == "explicit":
            cum_weight: Optional[float] = round(
                sum(weights.get(t, 0.0) for t in tickers), 6
            )
        else:
            cum_weight = None
        themes.append(ThemeExposure(
            concern_label=concern,
            member_tickers=sorted(tickers),
            cumulative_weight=cum_weight,
            ticker_count=len(tickers),
        ))
    themes.sort(key=lambda t: (-t.ticker_count, t.concern_label))
    return themes


def _compute_regime_sensitivity(
    tickers: set,
    macro_map: Dict[str, dict],
    durability_map: Dict[str, object],
) -> RegimeSensitivitySummary:
    if not tickers:
        return _empty_regime()

    # Aggregate macro factors across all tickers.
    factor_set: set = set()
    for ticker in tickers:
        m = macro_map.get(ticker, {})
        factor_set.update(m.keys())

    cycle_dist: Dict[str, int] = {}
    trend_dist: Dict[str, int] = {}
    horizon_dist: Dict[str, int] = {}
    missing: List[str] = []

    for ticker in sorted(tickers):
        row = durability_map.get(ticker)
        if row is None:
            missing.append(ticker)
            continue
        cp = row.cycle_position or "unknown"
        ct = row.conviction_trend or "stable"
        hh = row.horizon_hint or "investment"
        cycle_dist[cp] = cycle_dist.get(cp, 0) + 1
        trend_dist[ct] = trend_dist.get(ct, 0) + 1
        horizon_dist[hh] = horizon_dist.get(hh, 0) + 1

    substrate_missing = (not macro_map and not durability_map)

    return RegimeSensitivitySummary(
        active_macro_factors=sorted(factor_set),
        cycle_position_distribution=cycle_dist,
        conviction_trend_distribution=trend_dist,
        horizon_hint_distribution=horizon_dist,
        tickers_without_durability=missing,
        substrate_missing=substrate_missing,
    )


# ---------------------------------------------------------------------------
# Warning generation (template-bound, no LLM)
# ---------------------------------------------------------------------------

_HIGH_HHI_THRESHOLD = 0.25   # equivalent to <4 equal positions
_VERY_HIGH_HHI_THRESHOLD = 0.50  # equivalent to <2 equal positions


def _generate_warnings(
    concentration: ConcentrationMetrics,
    diversification: DiversificationMetrics,
    weight_source: str,
) -> List[HealthWarning]:
    warnings: List[HealthWarning] = []

    if concentration.position_count == 0:
        warnings.append(HealthWarning(
            code="EMPTY_PORTFOLIO",
            message="Portfolio has no active positions.",
            severity="info",
        ))
        return warnings

    if weight_source == "equal_weight_fallback":
        warnings.append(HealthWarning(
            code="EQUAL_WEIGHT_FALLBACK",
            message="Position weights are missing; equal-weight fallback applied.",
            severity="info",
        ))

    if concentration.hhi >= _VERY_HIGH_HHI_THRESHOLD:
        warnings.append(HealthWarning(
            code="VERY_HIGH_CONCENTRATION",
            message=(
                f"HHI={concentration.hhi:.3f} indicates very high concentration "
                f"(effective-N={concentration.effective_n:.1f})."
            ),
            severity="high",
        ))
    elif concentration.hhi >= _HIGH_HHI_THRESHOLD:
        warnings.append(HealthWarning(
            code="HIGH_CONCENTRATION",
            message=(
                f"HHI={concentration.hhi:.3f} indicates elevated concentration "
                f"(effective-N={concentration.effective_n:.1f})."
            ),
            severity="medium",
        ))

    if concentration.position_count == 1:
        warnings.append(HealthWarning(
            code="SINGLE_POSITION",
            message="Portfolio contains only one active position.",
            severity="high",
        ))

    return warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def compute_portfolio_health(
    session,
    portfolio_id: str,
) -> PortfolioHealthReport:
    """Compute and return a read-only health report for the given portfolio.

    Always returns a valid PortfolioHealthReport — never raises.
    On session=None or any DB error, returns safe empty defaults.

    This function NEVER:
      * writes to any table
      * calls an LLM
      * uses price data, beta, volatility, VaR, Sharpe, or return forecasts
    """
    generated_at = _now_iso()

    if session is None:
        return PortfolioHealthReport(
            portfolio_id=portfolio_id,
            generated_at=generated_at,
            weight_source="equal_weight_fallback",
            concentration=_empty_concentration(),
            diversification=_empty_diversification(),
            theme_exposure=[],
            regime_sensitivity=_empty_regime(),
            warnings=[HealthWarning(
                code="NO_SESSION",
                message="No database session available.",
                severity="info",
            )],
        )

    # Load positions.
    positions = await _load_positions(session, portfolio_id)
    ticker_set = {p.ticker for p in positions}

    # Resolve weights.
    weights, weight_source = _resolve_weights(positions)

    # Concentration.
    concentration = _compute_concentration(positions, weights)

    # Diversification.
    diversification = _compute_diversification(positions, weights)

    # Thematic exposure from cross_exposure substrate.
    concern_map = await _load_cross_exposure_concerns(session, ticker_set)
    theme_exposure = _compute_theme_exposure(concern_map, weights, weight_source)

    # Regime sensitivity from approved substrate.
    macro_map = await _load_macro_sensitivity(session, ticker_set)
    durability_map = await _load_durability(session, ticker_set)
    regime_sensitivity = _compute_regime_sensitivity(
        ticker_set, macro_map, durability_map
    )

    # Warnings.
    warnings = _generate_warnings(concentration, diversification, weight_source)

    return PortfolioHealthReport(
        portfolio_id=portfolio_id,
        generated_at=generated_at,
        weight_source=weight_source,
        concentration=concentration,
        diversification=diversification,
        theme_exposure=theme_exposure,
        regime_sensitivity=regime_sensitivity,
        warnings=warnings,
    )
