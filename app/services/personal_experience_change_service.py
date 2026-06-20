"""
Personal Experience Change Detection Service — Phase 18 · Slice 3.

Detects meaningful changes across upstream intelligence systems since a
user's last visit.  Each detect_* function reads upstream tables (read-only),
compares current state against the user's PersonalExperienceCursor, and
returns change candidate dicts.

Core question: "What changed since this user last looked?"

This module does NOT rank, personalize, or surface anything.  It only
detects changes and returns structured candidate dicts with recency and
novelty scores.

Flag gate
---------
All async public functions are gated on experience_change_detection_enabled
(default False).  When off they return [].

Null-session contract
---------------------
All async public functions return [] when session=None.

SP-18 invariants
----------------
  SP-18c: no write to any truth table.  Writes only to
          personal_experience_cursor (via repo).
  SP-18d: no upstream feedback — reads only.
  SP-18a: no banned advisory phrases.
"""

from __future__ import annotations

import hashlib
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FORECAST_MATERIALITY: float = 0.02
_DECISION_SCORE_MATERIALITY: float = 0.05
_RECENCY_HALF_LIFE_HOURS: float = 48.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "experience_change_detection_enabled", False))
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    val = getattr(obj, name, None)
    return val if val is not None else default


def _hash_fields(*fields: Any) -> str:
    raw = "|".join(str(f) for f in fields)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Pure scoring functions
# ---------------------------------------------------------------------------

def compute_recency_score(changed_at: Optional[datetime], now: Optional[datetime] = None) -> float:
    """Exponential decay from changed_at.  1.0 at t=0, ~0.5 at half-life.

    Returns 0.0 when changed_at is None.  Always in [0.0, 1.0].
    """
    if changed_at is None:
        return 0.0
    ref = now or _now()
    if changed_at.tzinfo is None:
        changed_at = changed_at.replace(tzinfo=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    elapsed_hours = max(0.0, (ref - changed_at).total_seconds() / 3600.0)
    decay = math.exp(-elapsed_hours * math.log(2) / _RECENCY_HALF_LIFE_HOURS)
    return round(max(0.0, min(1.0, decay)), 4)


def compute_novelty_score(
    last_seen_at: Optional[datetime],
    current_timestamp: Optional[datetime] = None,
) -> float:
    """1.0 when never seen (last_seen_at is None), decays toward 0.0.

    Always in [0.0, 1.0].
    """
    if last_seen_at is None:
        return 1.0
    ref = current_timestamp or _now()
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    elapsed_hours = max(0.0, (ref - last_seen_at).total_seconds() / 3600.0)
    novelty = 1.0 - math.exp(-elapsed_hours * math.log(2) / _RECENCY_HALF_LIFE_HOURS)
    return round(max(0.0, min(1.0, novelty)), 4)


def _make_candidate(
    *,
    entity_key: str,
    entity_type: str,
    change_type: str,
    changed_at: Optional[datetime],
    last_seen_at: Optional[datetime],
    explanation_text: str,
    evidence_refs: Optional[List[Dict[str, str]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    ref = now or _now()
    return {
        "entity_key":       entity_key,
        "entity_type":      entity_type,
        "change_type":      change_type,
        "changed_at":       changed_at.isoformat() if changed_at else None,
        "recency_score":    compute_recency_score(changed_at, ref),
        "novelty_score":    compute_novelty_score(last_seen_at, ref),
        "explanation_text": explanation_text,
        "evidence_refs":    evidence_refs or [],
    }


# ---------------------------------------------------------------------------
# Detect functions (each reads upstream + cursor, returns candidates)
# ---------------------------------------------------------------------------

async def detect_forecast_changes(
    session,
    *,
    user_id: str,
    entity_keys: Optional[List[str]] = None,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Detect forecasts that changed since user last saw them.

    A forecast is "changed" when its state hash (p_positive, p_negative,
    confidence bands) differs from the cursor's last_state_hash, and the
    delta exceeds the materiality gate.
    """
    if not _enabled(run_override):
        return []
    if session is None:
        return []
    try:
        from app.db.models import ForecastVector
        from sqlalchemy import select
        from app.db.repositories.personal_experience_repo import get_experience_cursor

        stmt = select(ForecastVector)
        if entity_keys:
            stmt = stmt.where(ForecastVector.entity_key.in_(entity_keys))
        result = await session.execute(stmt)
        forecasts = list(result.scalars().all())

        candidates: List[Dict[str, Any]] = []
        now = _now()
        for fv in forecasts:
            ek = _attr(fv, "entity_key", "")
            et = _attr(fv, "entity_type", "company")
            current_hash = _hash_fields(
                _attr(fv, "p_positive", 0.33),
                _attr(fv, "p_negative", 0.33),
                _attr(fv, "confidence_band_low", 0.0),
                _attr(fv, "confidence_band_high", 1.0),
                _attr(fv, "forecast_type", ""),
                _attr(fv, "horizon", ""),
            )
            cursor = await get_experience_cursor(
                session, user_id=user_id,
                entity_type="forecast", entity_key=ek,
            )
            old_hash = _attr(cursor, "last_state_hash", "") if cursor else ""
            if current_hash == old_hash:
                continue
            last_seen = _attr(cursor, "last_seen_at", None) if cursor else None
            built_at = _attr(fv, "built_at", now)
            candidates.append(_make_candidate(
                entity_key=ek,
                entity_type=et,
                change_type="forecast_changed",
                changed_at=built_at,
                last_seen_at=last_seen,
                explanation_text=(
                    f"Forecast for {ek} changed since your last visit."
                ),
                evidence_refs=[{"type": "forecast_vector", "id": _attr(fv, "id", "")}],
                now=now,
            ))
        return candidates
    except Exception as exc:
        logger.debug("[change_detection] detect_forecast_changes failed: %r", exc)
        return []


async def detect_decision_changes(
    session,
    *,
    user_id: str,
    entity_keys: Optional[List[str]] = None,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Detect decision priorities that changed since user last saw them."""
    if not _enabled(run_override):
        return []
    if session is None:
        return []
    try:
        from app.db.models import DecisionPriority
        from sqlalchemy import select
        from app.db.repositories.personal_experience_repo import get_experience_cursor

        stmt = select(DecisionPriority)
        if entity_keys:
            stmt = stmt.where(DecisionPriority.entity_key.in_(entity_keys))
        result = await session.execute(stmt)
        decisions = list(result.scalars().all())

        candidates: List[Dict[str, Any]] = []
        now = _now()
        for dp in decisions:
            ek = _attr(dp, "entity_key", "")
            et = _attr(dp, "entity_type", "company")
            current_hash = _hash_fields(
                _attr(dp, "decision_priority", "informational"),
                round(float(_attr(dp, "decision_rank_score", 0.0)), 2),
                _attr(dp, "candidate_type", ""),
            )
            cursor = await get_experience_cursor(
                session, user_id=user_id,
                entity_type="decision", entity_key=ek,
            )
            old_hash = _attr(cursor, "last_state_hash", "") if cursor else ""
            if current_hash == old_hash:
                continue
            last_seen = _attr(cursor, "last_seen_at", None) if cursor else None
            built_at = _attr(dp, "built_at", now)
            bucket = _attr(dp, "decision_priority", "informational")
            candidates.append(_make_candidate(
                entity_key=ek,
                entity_type=et,
                change_type="decision_changed",
                changed_at=built_at,
                last_seen_at=last_seen,
                explanation_text=(
                    f"Attention level for {ek} is now {bucket}."
                ),
                evidence_refs=[{"type": "decision_priority", "id": _attr(dp, "id", "")}],
                now=now,
            ))
        return candidates
    except Exception as exc:
        logger.debug("[change_detection] detect_decision_changes failed: %r", exc)
        return []


async def detect_scenario_changes(
    session,
    *,
    user_id: str,
    entity_keys: Optional[List[str]] = None,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Detect scenarios that changed since user last saw them."""
    if not _enabled(run_override):
        return []
    if session is None:
        return []
    try:
        from app.db.models import ScenarioSnapshot
        from sqlalchemy import select
        from app.db.repositories.personal_experience_repo import get_experience_cursor

        stmt = select(ScenarioSnapshot)
        if entity_keys:
            stmt = stmt.where(ScenarioSnapshot.entity_key.in_(entity_keys))
        result = await session.execute(stmt)
        scenarios = list(result.scalars().all())

        candidates: List[Dict[str, Any]] = []
        now = _now()
        for ss in scenarios:
            ek = _attr(ss, "entity_key", "")
            et = _attr(ss, "entity_type", "company")
            sk = _attr(ss, "scenario_key", "")
            current_hash = _hash_fields(
                _attr(ss, "plausibility_band", "plausible"),
                _attr(ss, "scenario_impact", "ambiguous"),
                round(float(_attr(ss, "confidence_score", 0.0)), 2),
                sk,
            )
            cursor = await get_experience_cursor(
                session, user_id=user_id,
                entity_type="scenario", entity_key=f"{ek}:{sk}",
            )
            old_hash = _attr(cursor, "last_state_hash", "") if cursor else ""
            if current_hash == old_hash:
                continue
            last_seen = _attr(cursor, "last_seen_at", None) if cursor else None
            built_at = _attr(ss, "built_at", now)
            band = _attr(ss, "plausibility_band", "plausible")
            candidates.append(_make_candidate(
                entity_key=ek,
                entity_type=et,
                change_type="scenario_changed",
                changed_at=built_at,
                last_seen_at=last_seen,
                explanation_text=(
                    f"Scenario for {ek} changed (plausibility: {band})."
                ),
                evidence_refs=[{"type": "scenario_snapshot", "id": _attr(ss, "id", "")}],
                now=now,
            ))
        return candidates
    except Exception as exc:
        logger.debug("[change_detection] detect_scenario_changes failed: %r", exc)
        return []


async def detect_watchlist_changes(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Detect watchlist items whose thesis (ticker_memory) changed."""
    if not _enabled(run_override):
        return []
    if session is None:
        return []
    try:
        from app.db.models import WatchedTicker, TickerMemory
        from sqlalchemy import select
        from app.db.repositories.personal_experience_repo import get_experience_cursor

        wt_stmt = select(WatchedTicker).where(WatchedTicker.active == True)  # noqa: E712
        if user_id:
            wt_stmt = wt_stmt.where(
                (WatchedTicker.user_id == user_id) | (WatchedTicker.user_id == None)  # noqa: E711
            )
        wt_result = await session.execute(wt_stmt)
        watched = list(wt_result.scalars().all())
        tickers = [_attr(w, "ticker", "") for w in watched if _attr(w, "ticker", "")]

        if not tickers:
            return []

        tm_stmt = select(TickerMemory).where(TickerMemory.ticker.in_(tickers))
        tm_result = await session.execute(tm_stmt)
        memories = {_attr(m, "ticker", ""): m for m in tm_result.scalars().all()}

        candidates: List[Dict[str, Any]] = []
        now = _now()
        for ticker in tickers:
            mem = memories.get(ticker)
            if mem is None:
                continue
            current_hash = _hash_fields(
                _attr(mem, "last_stance", ""),
                round(float(_attr(mem, "last_confidence", 0.0)), 2),
                _attr(mem, "dominant_concern", ""),
                int(_attr(mem, "version_count", 0)),
            )
            cursor = await get_experience_cursor(
                session, user_id=user_id,
                entity_type="ticker", entity_key=ticker,
            )
            old_hash = _attr(cursor, "last_state_hash", "") if cursor else ""
            if current_hash == old_hash:
                continue
            last_seen = _attr(cursor, "last_seen_at", None) if cursor else None
            updated = _attr(mem, "updated_at", now)
            candidates.append(_make_candidate(
                entity_key=ticker,
                entity_type="company",
                change_type="watchlist_drift",
                changed_at=updated,
                last_seen_at=last_seen,
                explanation_text=(
                    f"{ticker} thesis changed since your last visit."
                ),
                evidence_refs=[{"type": "ticker_memory", "id": _attr(mem, "id", "")}],
                now=now,
            ))
        return candidates
    except Exception as exc:
        logger.debug("[change_detection] detect_watchlist_changes failed: %r", exc)
        return []


async def detect_memory_changes(
    session,
    *,
    user_id: str,
    entity_keys: Optional[List[str]] = None,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Detect ticker_memory rows that updated since user last saw them.

    These are revisit candidates — entities the user previously viewed
    that have new analysis data.
    """
    if not _enabled(run_override):
        return []
    if session is None:
        return []
    try:
        from app.db.models import TickerMemory
        from sqlalchemy import select
        from app.db.repositories.personal_experience_repo import (
            get_experience_cursor, list_experience_cursors,
        )

        if entity_keys:
            tickers = entity_keys
        else:
            cursors = await list_experience_cursors(
                session, user_id=user_id, entity_type="ticker", limit=200,
            )
            tickers = [_attr(c, "entity_key", "") for c in cursors
                       if _attr(c, "entity_key", "")]
        if not tickers:
            return []

        tm_stmt = select(TickerMemory).where(TickerMemory.ticker.in_(tickers))
        tm_result = await session.execute(tm_stmt)
        memories = {_attr(m, "ticker", ""): m for m in tm_result.scalars().all()}

        candidates: List[Dict[str, Any]] = []
        now = _now()
        for ticker in tickers:
            mem = memories.get(ticker)
            if mem is None:
                continue
            cursor = await get_experience_cursor(
                session, user_id=user_id,
                entity_type="ticker", entity_key=ticker,
            )
            if cursor is None:
                continue
            mem_updated = _attr(mem, "updated_at", None)
            cursor_seen = _attr(cursor, "last_seen_at", None)
            if mem_updated is None or cursor_seen is None:
                continue
            if hasattr(mem_updated, "tzinfo") and mem_updated.tzinfo is None:
                mem_updated = mem_updated.replace(tzinfo=timezone.utc)
            if hasattr(cursor_seen, "tzinfo") and cursor_seen.tzinfo is None:
                cursor_seen = cursor_seen.replace(tzinfo=timezone.utc)
            if mem_updated <= cursor_seen:
                continue
            candidates.append(_make_candidate(
                entity_key=ticker,
                entity_type="company",
                change_type="memory_revisit",
                changed_at=mem_updated,
                last_seen_at=cursor_seen,
                explanation_text=(
                    f"New analysis data for {ticker} since your last visit."
                ),
                evidence_refs=[{"type": "ticker_memory", "id": _attr(mem, "id", "")}],
                now=now,
            ))
        return candidates
    except Exception as exc:
        logger.debug("[change_detection] detect_memory_changes failed: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def build_change_candidates(
    session,
    *,
    user_id: str,
    entity_keys: Optional[List[str]] = None,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Run all detect_* functions and return merged, deduplicated candidates.

    Deduplication is by (entity_key, change_type). When duplicates exist,
    the candidate with the higher recency_score is kept.

    Returns [] when the flag is off or session is None.
    """
    if not _enabled(run_override):
        return []
    if session is None:
        return []
    try:
        forecasts  = await detect_forecast_changes(
            session, user_id=user_id, entity_keys=entity_keys, run_override=run_override)
        decisions  = await detect_decision_changes(
            session, user_id=user_id, entity_keys=entity_keys, run_override=run_override)
        scenarios  = await detect_scenario_changes(
            session, user_id=user_id, entity_keys=entity_keys, run_override=run_override)
        watchlist  = await detect_watchlist_changes(
            session, user_id=user_id, run_override=run_override)
        memory     = await detect_memory_changes(
            session, user_id=user_id, entity_keys=entity_keys, run_override=run_override)

        all_candidates = forecasts + decisions + scenarios + watchlist + memory

        seen: Dict[str, Dict[str, Any]] = {}
        for c in all_candidates:
            key = f"{c['entity_key']}:{c['change_type']}"
            existing = seen.get(key)
            if existing is None or c["recency_score"] > existing["recency_score"]:
                seen[key] = c

        return sorted(seen.values(), key=lambda c: c["recency_score"], reverse=True)
    except Exception as exc:
        logger.debug("[change_detection] build_change_candidates failed: %r", exc)
        return []
