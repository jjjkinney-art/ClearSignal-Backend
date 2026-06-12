"""
Phase 10A · Slice 7 — Drift signal reader and materiality gate.

Core principle
--------------
    Timer decides WHEN to check.
    Drift decides WHETHER to spend.

Before dispatching a producer the scheduler calls `should_run_job`.  The
gate reads three substrate tables and decides whether enough has changed
since the last successful run to justify executing the producer:

  DossierRevision  — a dossier facet was updated by a synthesis session.
                     Score = max(0.5, revision.confidence).  Any revision
                     always clears the materiality threshold.
  ThesisDelta      — the investment thesis changed.
                     material delta  → 1.0 (stance_changed) or 0.9
                     moderate delta  → 0.6
                     minor delta     — NOT queried (too noisy)
  TickerMemory     — any analysis ran for the ticker (updated_at bumped).
                     Score = 0.3, intentionally BELOW the default threshold
                     so that a query-only session never triggers a full run.

Materiality threshold (configurable via `loop_drift_materiality_min`):
    Default = 0.4.  A score < threshold suppresses the job with reason
    "signal_below_threshold".  A score >= threshold allows dispatch.

target_key semantics
--------------------
    "global"   — watchlist_scan / morning_brief jobs; queries all tickers.
    <ticker>   — ticker-specific jobs (timeline_rollup); queries only that
                 ticker's substrate rows.

Bypass cases (always should_run=True, no substrate query)
----------------------------------------------------------
    - last_success_at is None  → first-ever run; always execute.
    - force_run=True           → admin override or payload_json.force_run.
    - gate_disabled            → loop_drift_gate_enabled=False in settings.

Null-object safety
------------------
    session=None → DriftSignal(should_run=True, reason="no_session") so the
    scheduler continues safely without DB access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal scores
# ---------------------------------------------------------------------------

_SCORE_DOSSIER_REVISION_MIN     = 0.5   # floor; actual = max(0.5, confidence)
_SCORE_THESIS_DELTA_MATERIAL    = 0.9   # + 0.1 if stance_changed → 1.0
_SCORE_THESIS_DELTA_MODERATE    = 0.6
_SCORE_TICKER_MEMORY            = 0.3   # below default threshold on purpose


# ---------------------------------------------------------------------------
# Public return type
# ---------------------------------------------------------------------------

@dataclass
class DriftSignal:
    """Decision record from one should_run_job evaluation.

    Attributes
    ----------
    should_run       : True  → proceed to producer dispatch.
                       False → skip this tick (outcome=skipped_stale).
    reason           : One of the REASON_* constants (see below).
    signals          : Human-readable descriptions of the substrate signals
                       found (empty when no signals or bypass path used).
    latest_signal_at : ISO-8601 UTC of the most recent substrate event, or None.
    materiality_score: Max materiality score across all found signals (0.0–1.0).
                       0.0 when no signals found.
    """
    should_run:         bool
    reason:             str
    signals:            List[str] = field(default_factory=list)
    latest_signal_at:   Optional[str] = None
    materiality_score:  float = 0.0


# Reason constants
REASON_NO_PRIOR_RUN        = "no_prior_run"
REASON_FORCE_RUN           = "force_run"
REASON_GATE_DISABLED       = "gate_disabled"
REASON_NO_SESSION          = "no_session"
REASON_NEW_DOSSIER_REVISION = "new_dossier_revision"
REASON_NEW_THESIS_DELTA    = "new_thesis_delta"
REASON_TICKER_MEMORY_UPDATED = "ticker_memory_updated"
REASON_NO_MATERIAL_CHANGE  = "no_material_change"
REASON_SIGNAL_BELOW_THRESHOLD = "signal_below_threshold"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _to_naive_utc(dt: datetime) -> datetime:
    """Strip tzinfo for SQLite-safe datetime comparisons."""
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def _latest_ts(*dts: Optional[datetime]) -> Optional[str]:
    """Return ISO-8601 string of the most recent non-None datetime."""
    candidates = [d for d in dts if d is not None]
    if not candidates:
        return None
    latest = max(candidates, key=lambda d: d.replace(tzinfo=None) if d.tzinfo else d)
    return latest.isoformat() if latest else None


def _get_threshold() -> float:
    try:
        from app.config import settings
        return settings.loop_drift_materiality_min
    except Exception:
        return 0.4


def _gate_enabled() -> bool:
    try:
        from app.config import settings
        return settings.loop_drift_gate_enabled
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Substrate queries
# ---------------------------------------------------------------------------

async def _query_dossier_revisions(
    session,
    ticker: Optional[str],
    since: datetime,
) -> List[Any]:
    """Return DossierRevision rows created after *since* (newest first, limit 3)."""
    try:
        from sqlalchemy import select
        from app.db.models import DossierRevision

        naive_since = _to_naive_utc(since)
        stmt = (
            select(DossierRevision)
            .where(DossierRevision.created_at > naive_since)
            .order_by(DossierRevision.created_at.desc())
            .limit(3)
        )
        if ticker:
            stmt = stmt.where(DossierRevision.ticker == ticker.strip().upper())
        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[drift] _query_dossier_revisions failed: %r", exc)
        return []


async def _query_thesis_deltas(
    session,
    ticker: Optional[str],
    since: datetime,
) -> List[Any]:
    """Return ThesisDelta rows (magnitude moderate/material) after *since*."""
    try:
        from sqlalchemy import select
        from app.db.models import ThesisDelta

        naive_since = _to_naive_utc(since)
        stmt = (
            select(ThesisDelta)
            .where(ThesisDelta.magnitude.in_(["moderate", "material"]))
            .where(ThesisDelta.created_at > naive_since)
            .order_by(ThesisDelta.created_at.desc())
            .limit(3)
        )
        if ticker:
            stmt = stmt.where(ThesisDelta.ticker == ticker.strip().upper())
        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[drift] _query_thesis_deltas failed: %r", exc)
        return []


async def _query_ticker_memory_updated(
    session,
    ticker: Optional[str],
    since: datetime,
) -> List[Any]:
    """Return TickerMemory rows updated after *since* (limit 3)."""
    try:
        from sqlalchemy import select
        from app.db.models import TickerMemory

        naive_since = _to_naive_utc(since)
        stmt = (
            select(TickerMemory)
            .where(TickerMemory.updated_at > naive_since)
            .limit(3)
        )
        if ticker:
            stmt = stmt.where(TickerMemory.ticker == ticker.strip().upper())
        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[drift] _query_ticker_memory_updated failed: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Signal scoring
# ---------------------------------------------------------------------------

def _score_dossier_revision(row: Any) -> float:
    """Score a DossierRevision row."""
    conf = float(getattr(row, "confidence", 0.0) or 0.0)
    return max(_SCORE_DOSSIER_REVISION_MIN, conf)


def _score_thesis_delta(row: Any) -> float:
    """Score a ThesisDelta row."""
    magnitude = getattr(row, "magnitude", "minor") or "minor"
    if magnitude == "material":
        stance_changed = bool(getattr(row, "stance_changed", False))
        return 1.0 if stance_changed else _SCORE_THESIS_DELTA_MATERIAL
    if magnitude == "moderate":
        return _SCORE_THESIS_DELTA_MODERATE
    return 0.0  # minor — not queried, but defensive


def _created_at(row: Any) -> Optional[datetime]:
    val = getattr(row, "created_at", None)
    if isinstance(val, datetime):
        return val
    return None


def _updated_at(row: Any) -> Optional[datetime]:
    val = getattr(row, "updated_at", None)
    if isinstance(val, datetime):
        return val
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def should_run_job(
    session,
    job_type: str,
    target_key: str,
    period_bucket: str,
    last_success_at: Optional[datetime],
    *,
    force_run: bool = False,
) -> DriftSignal:
    """
    Evaluate whether a scheduled job should execute this tick.

    Parameters
    ----------
    session         : AsyncSession or None.
    job_type        : Registered job type string (e.g. "watchlist_scan").
    target_key      : "global" for watchlist/brief jobs; ticker symbol for
                      ticker-specific jobs.
    period_bucket   : ISO-date or drift bucket string (informational only).
    last_success_at : Timestamp of the last succeeded JobRun for this job's
                      work_key (== ScheduledJob.last_generated_at).
                      None means no prior successful run → always run.
    force_run       : If True, bypasses the gate regardless of substrate state.

    Returns
    -------
    DriftSignal — always returns, never raises.
    """

    # ── Null session ──────────────────────────────────────────────────────────
    if session is None:
        logger.debug("[drift] no session → bypass gate")
        return DriftSignal(should_run=True, reason=REASON_NO_SESSION)

    # ── No prior run ─────────────────────────────────────────────────────────
    if last_success_at is None:
        logger.debug("[drift] no_prior_run for %s/%s", job_type, target_key)
        return DriftSignal(should_run=True, reason=REASON_NO_PRIOR_RUN)

    # ── Force run ─────────────────────────────────────────────────────────────
    if force_run:
        logger.debug("[drift] force_run for %s/%s", job_type, target_key)
        return DriftSignal(should_run=True, reason=REASON_FORCE_RUN)

    # ── Gate disabled ────────────────────────────────────────────────────────
    if not _gate_enabled():
        logger.debug("[drift] gate_disabled for %s/%s", job_type, target_key)
        return DriftSignal(should_run=True, reason=REASON_GATE_DISABLED)

    # ── Substrate queries ────────────────────────────────────────────────────
    # For target_key="global", query across all tickers (no ticker filter).
    # For ticker-specific keys, restrict to that ticker.
    ticker_filter: Optional[str] = None if target_key.lower() == "global" else target_key

    signals: List[str]       = []
    max_score: float         = 0.0
    ts_candidates: List[Optional[datetime]] = []

    # ── DossierRevision ───────────────────────────────────────────────────────
    dr_rows = await _query_dossier_revisions(session, ticker_filter, last_success_at)
    for row in dr_rows:
        score = _score_dossier_revision(row)
        ticker_label = getattr(row, "ticker", "?") or "?"
        facet_label  = getattr(row, "facet",  "?") or "?"
        signals.append(f"dossier_revision:{ticker_label}:{facet_label}:score={score:.2f}")
        max_score = max(max_score, score)
        ts_candidates.append(_created_at(row))

    # ── ThesisDelta (moderate/material) ──────────────────────────────────────
    td_rows = await _query_thesis_deltas(session, ticker_filter, last_success_at)
    for row in td_rows:
        score = _score_thesis_delta(row)
        ticker_label = getattr(row, "ticker",    "?") or "?"
        magnitude    = getattr(row, "magnitude", "?") or "?"
        stance_tag   = ":stance_changed" if getattr(row, "stance_changed", False) else ""
        signals.append(f"thesis_delta:{ticker_label}:{magnitude}{stance_tag}:score={score:.2f}")
        max_score = max(max_score, score)
        ts_candidates.append(_created_at(row))

    # ── TickerMemory ──────────────────────────────────────────────────────────
    mem_rows = await _query_ticker_memory_updated(session, ticker_filter, last_success_at)
    for row in mem_rows:
        score = _SCORE_TICKER_MEMORY
        ticker_label = getattr(row, "ticker", "?") or "?"
        signals.append(f"ticker_memory_updated:{ticker_label}:score={score:.2f}")
        max_score = max(max_score, score)
        ts_candidates.append(_updated_at(row))

    latest_signal_at = _latest_ts(*ts_candidates)
    threshold = _get_threshold()

    # ── No signals at all ────────────────────────────────────────────────────
    if not signals:
        logger.debug(
            "[drift] no_material_change for %s/%s (since %s)",
            job_type, target_key,
            last_success_at.isoformat() if last_success_at else "—",
        )
        return DriftSignal(
            should_run=False,
            reason=REASON_NO_MATERIAL_CHANGE,
            signals=[],
            latest_signal_at=None,
            materiality_score=0.0,
        )

    # ── Below materiality threshold ───────────────────────────────────────────
    if max_score < threshold:
        logger.debug(
            "[drift] signal_below_threshold for %s/%s (score=%.2f < threshold=%.2f)",
            job_type, target_key, max_score, threshold,
        )
        return DriftSignal(
            should_run=False,
            reason=REASON_SIGNAL_BELOW_THRESHOLD,
            signals=signals,
            latest_signal_at=latest_signal_at,
            materiality_score=max_score,
        )

    # ── Material change found — determine primary reason ─────────────────────
    if any("dossier_revision:" in s for s in signals):
        primary_reason = REASON_NEW_DOSSIER_REVISION
    elif any("thesis_delta:" in s for s in signals):
        primary_reason = REASON_NEW_THESIS_DELTA
    else:
        primary_reason = REASON_TICKER_MEMORY_UPDATED

    logger.info(
        "[drift] should_run=True for %s/%s — %s (score=%.2f, signals=%d)",
        job_type, target_key, primary_reason, max_score, len(signals),
    )
    return DriftSignal(
        should_run=True,
        reason=primary_reason,
        signals=signals,
        latest_signal_at=latest_signal_at,
        materiality_score=max_score,
    )
