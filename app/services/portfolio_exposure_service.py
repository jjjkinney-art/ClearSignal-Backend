"""
Portfolio cross-exposure projection service — Phase 10D · Slice 3.

Projects the existing cross_exposures graph, DossierCatalyst rows, and
DossierFailureMode rows onto a specific portfolio.

Design constraints (spec §0 principle #1)
-----------------------------------------
* No new company-level intelligence is computed here.
* Every signal surfaced is already stored in cross_exposures, dossier_catalyst,
  or dossier_failure_mode.  This service only reads, filters, and groups.
* No LLM calls, no synthesis, no writes to any table.
* Returns dataclasses.  All fields are plain Python values — no ORM objects
  escape the service boundary.

Graceful degradation
--------------------
Every DB read is wrapped in try/except.  If the session is None, a table is
empty, or a query fails, the corresponding section returns an empty list and
sets the appropriate stale/missing flag.  The caller always gets a valid
PortfolioExposureProjection, never an exception.

Staleness rule (spec §2.5)
--------------------------
A CrossExposure edge is stale when its created_at is older than
STALE_EDGE_DAYS (default 7).  Stale edges still appear in the output —
the caller sees them flagged — but the overall projection marks
cross_exposure_stale=True so the delivery layer can cap severity.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Number of days after which a CrossExposure edge is considered stale.
STALE_EDGE_DAYS: int = 7

# Correlation threshold: pairs with strength >= this surface as hidden-correlation alerts.
CORRELATION_THRESHOLD: float = 0.7


# ---------------------------------------------------------------------------
# Output dataclasses (spec §2 / plan PART 3)
# ---------------------------------------------------------------------------

@dataclass
class ExposurePair:
    """A pairwise cross-exposure relationship between two portfolio tickers.

    Corresponds directly to one CrossExposure DB row filtered to portfolio
    members.
    """
    ticker_a: str
    ticker_b: str
    exposure_type: str
    strength: float
    shared_concerns: List[str]
    # ISO-8601 string of the edge's created_at (freshness reference).
    edge_as_of: str
    stale_input: bool
    # Source row id for traceability (never a live ORM object).
    source_ref: str


@dataclass
class SharedExposureCluster:
    """A group of portfolio tickers sharing a common concern/theme label.

    Built by inverting the ExposurePair list: for each concern label that
    appears in two or more edges, collect the member tickers.
    """
    concern_label: str
    member_tickers: List[str]
    # Sum of weight for member tickers (None when positions carry no weights).
    cluster_weight: Optional[float]
    # Highest strength value across contributing edges.
    max_edge_strength: float
    # Dominant exposure_type across contributing edges (mode).
    dominant_exposure_type: str
    stale_input: bool
    # ISO-8601 timestamp of the oldest contributing edge.
    cross_exposure_as_of: str
    # Edge source_refs that contributed to this cluster.
    source_refs: List[str]


@dataclass
class FailureModeCluster:
    """Portfolio tickers sharing the same failure-mode analog.

    Built from DossierFailureMode rows where analog_id matches across two or
    more portfolio tickers.  Only tickers in the portfolio are included.
    """
    analog_id: str
    # analog_label from historical_analogs (empty string when analog not found).
    analog_label: str
    member_tickers: List[str]
    # Sequence stages per ticker: {ticker: stage}.
    stages: Dict[str, int]
    source_refs: List[str]


@dataclass
class CatalystCluster:
    """Portfolio tickers sharing the same catalyst direction and open status.

    Built from DossierCatalyst rows for portfolio tickers.  Only 'open'
    catalysts are grouped; resolved catalysts are excluded.
    """
    direction: str          # "bull_trigger" | "bear_trigger"
    member_tickers: List[str]
    # Sample statement (highest-specificity open catalyst from any member).
    sample_statement: str
    source_refs: List[str]


@dataclass
class PortfolioExposureProjection:
    """Full cross-exposure projection for one portfolio.

    All list fields are empty when the portfolio has zero or one positions,
    when the substrate tables are empty, or when DB access fails.
    """
    portfolio_id: str
    # ISO-8601 UTC timestamp of when this projection was computed.
    generated_at: str

    # Active tickers in the portfolio at projection time.
    portfolio_tickers: List[str]

    # All pairwise edges where both endpoints are portfolio members.
    exposure_pairs: List[ExposurePair]

    # Pairs with strength >= CORRELATION_THRESHOLD (hidden-correlation alerts).
    high_correlation_pairs: List[ExposurePair]

    # Concern-label clusters built from exposure_pairs.
    shared_exposure_clusters: List[SharedExposureCluster]

    # Failure-mode clusters built from DossierFailureMode rows.
    failure_mode_clusters: List[FailureModeCluster]

    # Catalyst clusters built from DossierCatalyst open rows.
    catalyst_clusters: List[CatalystCluster]

    # True when any contributing CrossExposure edge is older than STALE_EDGE_DAYS.
    cross_exposure_stale: bool

    # min(created_at) across all contributing edges; None when no edges found.
    cross_exposure_as_of: Optional[str]

    # True when the failure_mode or catalyst tables could not be read.
    substrate_missing: bool


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json_list(raw: str) -> List[str]:
    """Parse a JSON-array string into a list of strings; empty list on failure."""
    try:
        val = json.loads(raw or "[]")
        if isinstance(val, list):
            return [str(x) for x in val]
    except Exception:
        pass
    return []


def _is_stale(edge_created_at: datetime) -> bool:
    """Return True if the edge is older than STALE_EDGE_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_EDGE_DAYS)
    # Handle tz-naive datetimes from SQLite.
    if edge_created_at.tzinfo is None:
        edge_created_at = edge_created_at.replace(tzinfo=timezone.utc)
    return edge_created_at < cutoff


def _dominant(values: List[str]) -> str:
    """Return the most-common string in values, or '' if empty."""
    if not values:
        return ""
    return max(set(values), key=values.count)


def _min_iso(timestamps: List[str]) -> str:
    """Return the lexicographically smallest ISO timestamp string."""
    valid = [t for t in timestamps if t]
    return min(valid) if valid else ""


# ---------------------------------------------------------------------------
# DB readers — each returns a safe empty result on any exception
# ---------------------------------------------------------------------------

async def _load_active_tickers(session, portfolio_id: str) -> List[str]:
    """Return active ticker strings for the portfolio."""
    try:
        from app.db.models import PortfolioPosition
        from sqlalchemy import select
        result = await session.execute(
            select(PortfolioPosition.ticker)
            .where(PortfolioPosition.portfolio_id == portfolio_id)
            .where(PortfolioPosition.active.is_(True))
        )
        return [row[0] for row in result.all()]
    except Exception as exc:
        logger.warning("[portfolio_exposure] load_active_tickers failed: %r", exc)
        return []


async def _load_position_weights(session, portfolio_id: str) -> Dict[str, Optional[float]]:
    """Return {ticker: weight} for active positions; weight may be None."""
    try:
        from app.db.models import PortfolioPosition
        from sqlalchemy import select
        result = await session.execute(
            select(PortfolioPosition.ticker, PortfolioPosition.weight)
            .where(PortfolioPosition.portfolio_id == portfolio_id)
            .where(PortfolioPosition.active.is_(True))
        )
        return {row[0]: row[1] for row in result.all()}
    except Exception as exc:
        logger.warning("[portfolio_exposure] load_position_weights failed: %r", exc)
        return {}


async def _load_cross_exposure_edges(
    session, tickers: Set[str]
) -> List[object]:
    """Return CrossExposure rows where BOTH ticker_a and ticker_b are in tickers."""
    if len(tickers) < 2:
        return []
    try:
        from app.db.models import CrossExposure
        from sqlalchemy import select
        # Fetch all edges where ticker_a is in the portfolio set.
        result = await session.execute(
            select(CrossExposure)
            .where(CrossExposure.ticker_a.in_(tickers))
        )
        rows = result.scalars().all()
        # Filter to edges where ticker_b is also in the portfolio set.
        return [r for r in rows if r.ticker_b in tickers]
    except Exception as exc:
        logger.warning("[portfolio_exposure] load_cross_exposure_edges failed: %r", exc)
        return []


async def _load_failure_modes(
    session, tickers: Set[str]
) -> List[object]:
    """Return DossierFailureMode rows for portfolio tickers."""
    if not tickers:
        return []
    try:
        from app.db.models import DossierFailureMode
        from sqlalchemy import select
        result = await session.execute(
            select(DossierFailureMode)
            .where(DossierFailureMode.ticker.in_(tickers))
        )
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[portfolio_exposure] load_failure_modes failed: %r", exc)
        return []


async def _load_analog_labels(
    session, analog_ids: Set[str]
) -> Dict[str, str]:
    """Return {analog_id: label} for the given analog_ids."""
    if not analog_ids:
        return {}
    try:
        from app.db.models import HistoricalAnalog
        from sqlalchemy import select
        result = await session.execute(
            select(HistoricalAnalog.id, HistoricalAnalog.label)
            .where(HistoricalAnalog.id.in_(analog_ids))
        )
        return {row[0]: row[1] for row in result.all()}
    except Exception as exc:
        logger.warning("[portfolio_exposure] load_analog_labels failed: %r", exc)
        return {}


async def _load_open_catalysts(
    session, tickers: Set[str]
) -> List[object]:
    """Return open DossierCatalyst rows for portfolio tickers."""
    if not tickers:
        return []
    try:
        from app.db.models import DossierCatalyst
        from sqlalchemy import select
        result = await session.execute(
            select(DossierCatalyst)
            .where(DossierCatalyst.ticker.in_(tickers))
            .where(DossierCatalyst.status == "open")
            .order_by(DossierCatalyst.specificity.desc())
        )
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[portfolio_exposure] load_open_catalysts failed: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _build_exposure_pairs(
    edge_rows: list,
) -> List[ExposurePair]:
    """Convert DB edge rows into ExposurePair dataclasses."""
    pairs: List[ExposurePair] = []
    for row in edge_rows:
        stale = _is_stale(row.created_at)
        pairs.append(ExposurePair(
            ticker_a=row.ticker_a,
            ticker_b=row.ticker_b,
            exposure_type=row.exposure_type or "thematic",
            strength=float(row.strength or 0.0),
            shared_concerns=_parse_json_list(row.shared_concerns),
            edge_as_of=row.created_at.isoformat() if row.created_at else "",
            stale_input=stale,
            source_ref=str(row.id),
        ))
    return pairs


def _build_shared_clusters(
    pairs: List[ExposurePair],
    weights: Dict[str, Optional[float]],
) -> List[SharedExposureCluster]:
    """Group exposure pairs by shared concern label into clusters.

    A cluster is created for each concern label that appears in at least
    two ExposurePair.shared_concerns lists (i.e. connects at least two tickers).
    """
    # concern_label → {tickers, max_strength, exposure_types, stale flags, as_of ts, refs}
    concern_map: Dict[str, dict] = {}

    for pair in pairs:
        for concern in pair.shared_concerns:
            if not concern:
                continue
            if concern not in concern_map:
                concern_map[concern] = {
                    "tickers": set(),
                    "max_strength": 0.0,
                    "exposure_types": [],
                    "stale": False,
                    "as_of_list": [],
                    "refs": [],
                }
            entry = concern_map[concern]
            entry["tickers"].add(pair.ticker_a)
            entry["tickers"].add(pair.ticker_b)
            entry["max_strength"] = max(entry["max_strength"], pair.strength)
            entry["exposure_types"].append(pair.exposure_type)
            if pair.stale_input:
                entry["stale"] = True
            entry["as_of_list"].append(pair.edge_as_of)
            entry["refs"].append(pair.source_ref)

    clusters: List[SharedExposureCluster] = []
    for concern, entry in concern_map.items():
        tickers = sorted(entry["tickers"])
        if len(tickers) < 2:
            continue

        # Compute cluster_weight: sum of weights for member tickers.
        # None if any member has no weight.
        member_weights = [weights.get(t) for t in tickers]
        if any(w is None for w in member_weights):
            cluster_weight = None
        else:
            cluster_weight = sum(w for w in member_weights if w is not None)

        clusters.append(SharedExposureCluster(
            concern_label=concern,
            member_tickers=tickers,
            cluster_weight=cluster_weight,
            max_edge_strength=entry["max_strength"],
            dominant_exposure_type=_dominant(entry["exposure_types"]),
            stale_input=entry["stale"],
            cross_exposure_as_of=_min_iso(entry["as_of_list"]),
            source_refs=list(set(entry["refs"])),
        ))

    # Sort by member count desc, then concern label for determinism.
    clusters.sort(key=lambda c: (-len(c.member_tickers), c.concern_label))
    return clusters


def _build_failure_clusters(
    failure_rows: list,
    analog_labels: Dict[str, str],
    portfolio_tickers: Set[str],
) -> List[FailureModeCluster]:
    """Group DossierFailureMode rows by analog_id.

    Only analog_ids that appear for two or more portfolio tickers are
    surfaced as clusters (single-ticker failure modes are company-level
    signals, not portfolio-level ones).
    """
    # analog_id → {tickers, stages, refs}
    analog_map: Dict[str, dict] = {}

    for row in failure_rows:
        if row.ticker not in portfolio_tickers:
            continue
        aid = row.analog_id
        if aid not in analog_map:
            analog_map[aid] = {"tickers": [], "stages": {}, "refs": []}
        entry = analog_map[aid]
        if row.ticker not in entry["tickers"]:
            entry["tickers"].append(row.ticker)
        entry["stages"][row.ticker] = row.sequence_stage
        entry["refs"].append(str(row.id))

    clusters: List[FailureModeCluster] = []
    for aid, entry in analog_map.items():
        if len(entry["tickers"]) < 2:
            continue
        clusters.append(FailureModeCluster(
            analog_id=aid,
            analog_label=analog_labels.get(aid, ""),
            member_tickers=sorted(entry["tickers"]),
            stages=entry["stages"],
            source_refs=entry["refs"],
        ))

    clusters.sort(key=lambda c: (-len(c.member_tickers), c.analog_id))
    return clusters


def _build_catalyst_clusters(
    catalyst_rows: list,
    portfolio_tickers: Set[str],
) -> List[CatalystCluster]:
    """Group open DossierCatalyst rows by direction.

    Groups are only surfaced when two or more portfolio tickers share the same
    direction.  The sample_statement is taken from the highest-specificity
    catalyst (the DB query already ordered by specificity desc).
    """
    # direction → {tickers, sample_statement, refs}
    direction_map: Dict[str, dict] = {}

    for row in catalyst_rows:
        if row.ticker not in portfolio_tickers:
            continue
        d = row.direction or "bull_trigger"
        if d not in direction_map:
            direction_map[d] = {
                "tickers": [],
                "sample_statement": row.statement or "",
                "refs": [],
            }
        entry = direction_map[d]
        if row.ticker not in entry["tickers"]:
            entry["tickers"].append(row.ticker)
            # Keep the first (highest-specificity) statement.
        entry["refs"].append(str(row.id))

    clusters: List[CatalystCluster] = []
    for direction, entry in direction_map.items():
        if len(entry["tickers"]) < 2:
            continue
        clusters.append(CatalystCluster(
            direction=direction,
            member_tickers=sorted(entry["tickers"]),
            sample_statement=entry["sample_statement"],
            source_refs=entry["refs"],
        ))

    clusters.sort(key=lambda c: (-len(c.member_tickers), c.direction))
    return clusters


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def project_portfolio_exposure(
    session,
    portfolio_id: str,
) -> PortfolioExposureProjection:
    """Compute the cross-exposure projection for a portfolio.

    Always returns a valid PortfolioExposureProjection.  On session=None or
    any DB error the projection has empty lists and appropriate flags set.

    This function NEVER:
      * issues an LLM call
      * writes to any table
      * computes new company-level analysis
    """
    generated_at = _now_iso()

    # Null-session fast path.
    if session is None:
        return PortfolioExposureProjection(
            portfolio_id=portfolio_id,
            generated_at=generated_at,
            portfolio_tickers=[],
            exposure_pairs=[],
            high_correlation_pairs=[],
            shared_exposure_clusters=[],
            failure_mode_clusters=[],
            catalyst_clusters=[],
            cross_exposure_stale=False,
            cross_exposure_as_of=None,
            substrate_missing=False,
        )

    # Step 1 — active tickers and their weights.
    tickers = await _load_active_tickers(session, portfolio_id)
    ticker_set: Set[str] = set(tickers)
    weights = await _load_position_weights(session, portfolio_id)

    # Step 2 — cross_exposure edges.
    edge_rows = await _load_cross_exposure_edges(session, ticker_set)
    pairs = _build_exposure_pairs(edge_rows)

    high_corr = [p for p in pairs if p.strength >= CORRELATION_THRESHOLD]

    clusters = _build_shared_clusters(pairs, weights)

    # Compute aggregate freshness fields.
    any_stale = any(p.stale_input for p in pairs)
    as_of: Optional[str] = None
    if pairs:
        all_ts = [p.edge_as_of for p in pairs if p.edge_as_of]
        as_of = _min_iso(all_ts) if all_ts else None

    # Step 3 — failure mode clusters.
    substrate_missing = False
    failure_rows: list = []
    analog_labels: Dict[str, str] = {}
    try:
        failure_rows = await _load_failure_modes(session, ticker_set)
        analog_ids = {r.analog_id for r in failure_rows}
        analog_labels = await _load_analog_labels(session, analog_ids)
    except Exception as exc:
        logger.warning("[portfolio_exposure] failure_mode load failed: %r", exc)
        substrate_missing = True

    failure_clusters = _build_failure_clusters(failure_rows, analog_labels, ticker_set)

    # Step 4 — catalyst clusters.
    catalyst_rows: list = []
    try:
        catalyst_rows = await _load_open_catalysts(session, ticker_set)
    except Exception as exc:
        logger.warning("[portfolio_exposure] catalyst load failed: %r", exc)
        substrate_missing = True

    cat_clusters = _build_catalyst_clusters(catalyst_rows, ticker_set)

    return PortfolioExposureProjection(
        portfolio_id=portfolio_id,
        generated_at=generated_at,
        portfolio_tickers=sorted(tickers),
        exposure_pairs=pairs,
        high_correlation_pairs=high_corr,
        shared_exposure_clusters=clusters,
        failure_mode_clusters=failure_clusters,
        catalyst_clusters=cat_clusters,
        cross_exposure_stale=any_stale,
        cross_exposure_as_of=as_of,
        substrate_missing=substrate_missing,
    )
