"""
Phase 9G · Phase 0 — Company Dossier persistence layer (head + facets).

Covers all seven writable facet tables:
  company_dossier          — head / single-row-per-ticker
  dossier_core_debate      — versioned 1:1
  dossier_moat_dimension   — versioned 1:N (≤6 axes)
  dossier_catalyst         — lifecycle 1:N (never deleted)
  dossier_variant          — versioned 1:1
  dossier_durability       — non-versioned 1:1 (raw signals)
  dossier_failure_mode     — upsert 1:N (one row per ticker×analog)

The append-only revision + evidence tables live in dossier_revision_repo.py.

Conventions (matching existing repos):
  * session is None → return None or []  (null-object, no branch required in callers)
  * expect_version=None  → skip optimistic check
  * expect_version=N     → require current facet version == N; on mismatch return None + warn
  * await session.flush() only — no commit (caller controls transaction)
  * lazy model imports inside each function to avoid circular imports
  * no business logic: gates / hysteresis / thresholds live in dossier_extraction_service.py
  * never hard-delete any row
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm(ticker: str) -> str:
    """Uppercase + strip — minimal normalisation inside the repo.

    Callers that have access to ticker_normalizer should use that;
    this guard prevents empty/lower-case strings from reaching the DB.
    """
    return ticker.strip().upper()[:20] if ticker else "UNKNOWN"


# ===========================================================================
# HEAD — company_dossier
# ===========================================================================

async def get_head(
    session,
    ticker: str,
) -> Optional[Any]:
    """Return the CompanyDossier head row for *ticker*, or None."""
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        from sqlalchemy import select
        from ..models import CompanyDossier
        stmt = select(CompanyDossier).where(CompanyDossier.ticker == ticker)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[dossier_repo] get_head failed for %s: %r", ticker, exc)
        return None


async def get_or_create_head(
    session,
    ticker: str,
    company_name: str = "",
    session_id: str = "",
    user_id: Optional[str] = None,
) -> Optional[Any]:
    """Return the CompanyDossier head row, creating an empty one if absent.

    The created row has all defaults (stance='', conviction=0.0, etc.) and
    must be populated by a subsequent upsert_head call once facets are known.
    """
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        row = await get_head(session, ticker)
        if row is None:
            from ..models import CompanyDossier
            row = CompanyDossier(
                id=_uuid(),
                ticker=ticker,
                company_name=company_name or ticker,
                session_id=session_id,
                user_id=user_id,
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(row)
            await session.flush()
            logger.debug("[dossier_repo] created head for %s", ticker)
        return row
    except Exception as exc:
        logger.warning("[dossier_repo] get_or_create_head failed for %s: %r", ticker, exc)
        return None


async def upsert_head(
    session,
    ticker: str,
    *,
    company_name: str = "",
    stance: str = "",
    conviction: float = 0.0,
    primary_concern: str = "",
    latest_version_id: Optional[str] = None,
    prior_as_of: Optional[datetime] = None,
    global_confidence: float = 0.0,
    staleness_state: str = "fresh",
    last_full_update_at: Optional[datetime] = None,
    analysis_count: Optional[int] = None,
    row_version: Optional[int] = None,
    session_id: str = "",
    user_id: Optional[str] = None,
) -> Optional[Any]:
    """Create-or-update the CompanyDossier head row.

    Only non-None keyword arguments overwrite the existing value.
    ``row_version`` is bumped unconditionally on every write so injection
    can detect staleness; the caller must pass the value it read
    (optimistic concurrency is at the facet level, not the head).
    """
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        from ..models import CompanyDossier
        row = await get_head(session, ticker)
        now = _now()
        if row is None:
            row = CompanyDossier(
                id=_uuid(),
                ticker=ticker,
                company_name=company_name or ticker,
                stance=stance,
                conviction=conviction,
                primary_concern=primary_concern,
                latest_version_id=latest_version_id,
                prior_as_of=prior_as_of,
                global_confidence=global_confidence,
                staleness_state=staleness_state,
                last_full_update_at=last_full_update_at,
                analysis_count=0 if analysis_count is None else analysis_count,
                row_version=0,
                session_id=session_id,
                user_id=user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            if company_name:
                row.company_name = company_name
            if stance:
                row.stance = stance
            if conviction:
                row.conviction = conviction
            if primary_concern:
                row.primary_concern = primary_concern
            if latest_version_id is not None:
                row.latest_version_id = latest_version_id
            if prior_as_of is not None:
                row.prior_as_of = prior_as_of
            if global_confidence:
                row.global_confidence = global_confidence
            if staleness_state:
                row.staleness_state = staleness_state
            if last_full_update_at is not None:
                row.last_full_update_at = last_full_update_at
            if analysis_count is not None:
                row.analysis_count = analysis_count
            if session_id:
                row.session_id = session_id
            if user_id is not None:
                row.user_id = user_id
            row.row_version = (row.row_version or 0) + 1
            row.updated_at = now

        await session.flush()
        logger.debug("[dossier_repo] upserted head for %s (row_version=%s)", ticker, row.row_version)
        return row
    except Exception as exc:
        logger.warning("[dossier_repo] upsert_head failed for %s: %r", ticker, exc)
        return None


async def get_full_dossier(
    session,
    ticker: str,
) -> Dict[str, Any]:
    """Return all dossier facets for *ticker* in a single dict.

    Used by the injection service (Slice 5) and the read API (Slice 6).
    Returns a dict with None / [] defaults so callers can read without
    checking for missing keys.

    Shape::

        {
            "head":          CompanyDossier | None,
            "debate":        DossierCoreDebate | None,
            "dimensions":    List[DossierMoatDimension],
            "catalysts":     List[DossierCatalyst],   # all statuses
            "variant":       DossierVariant | None,
            "durability":    DossierDurability | None,
            "failure_modes": List[DossierFailureMode],
        }
    """
    if session is None:
        return _empty_dossier()
    ticker = _norm(ticker)
    try:
        from sqlalchemy import select
        from ..models import (
            CompanyDossier, DossierCoreDebate, DossierMoatDimension,
            DossierCatalyst, DossierVariant, DossierDurability, DossierFailureMode,
        )

        async def _one(model, where):
            r = await session.execute(select(model).where(where))
            return r.scalar_one_or_none()

        async def _many(model, where, order_by=None):
            stmt = select(model).where(where)
            if order_by is not None:
                stmt = stmt.order_by(order_by)
            r = await session.execute(stmt)
            return list(r.scalars().all())

        head        = await _one(CompanyDossier,     CompanyDossier.ticker == ticker)
        debate      = await _one(DossierCoreDebate,  DossierCoreDebate.ticker == ticker)
        variant     = await _one(DossierVariant,     DossierVariant.ticker == ticker)
        durability  = await _one(DossierDurability,  DossierDurability.ticker == ticker)
        dimensions  = await _many(DossierMoatDimension, DossierMoatDimension.ticker == ticker,
                                  order_by=DossierMoatDimension.axis)
        catalysts   = await _many(DossierCatalyst, DossierCatalyst.ticker == ticker,
                                  order_by=DossierCatalyst.created_at.desc())
        failure_modes = await _many(DossierFailureMode, DossierFailureMode.ticker == ticker,
                                    order_by=DossierFailureMode.sequence_stage)
        return {
            "head":          head,
            "debate":        debate,
            "dimensions":    dimensions,
            "catalysts":     catalysts,
            "variant":       variant,
            "durability":    durability,
            "failure_modes": failure_modes,
        }
    except Exception as exc:
        logger.warning("[dossier_repo] get_full_dossier failed for %s: %r", ticker, exc)
        return _empty_dossier()


def _empty_dossier() -> Dict[str, Any]:
    return {
        "head": None, "debate": None, "dimensions": [],
        "catalysts": [], "variant": None, "durability": None, "failure_modes": [],
    }


# ===========================================================================
# DEBATE — dossier_core_debate
# ===========================================================================

async def get_debate(session, ticker: str) -> Optional[Any]:
    """Return the DossierCoreDebate row for *ticker*, or None."""
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        from sqlalchemy import select
        from ..models import DossierCoreDebate
        stmt = select(DossierCoreDebate).where(DossierCoreDebate.ticker == ticker)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[dossier_repo] get_debate failed for %s: %r", ticker, exc)
        return None


async def write_debate(
    session,
    ticker: str,
    *,
    question: str = "",
    bull_pole: str = "",
    bear_pole: str = "",
    current_lean: str = "balanced",
    resolution_signal: str = "",
    version: int = 1,
    confidence: float = 0.0,
    session_id: str = "",
    user_id: Optional[str] = None,
    expect_version: Optional[int] = None,
) -> Optional[Any]:
    """Create-or-update the DossierCoreDebate row.

    If *expect_version* is supplied and the existing row's version differs,
    this is an optimistic-lock conflict — the function returns None and the
    caller should re-read and retry.
    """
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        from ..models import DossierCoreDebate
        now = _now()
        row = await get_debate(session, ticker)
        if row is None:
            row = DossierCoreDebate(
                id=_uuid(), ticker=ticker,
                question=question, bull_pole=bull_pole, bear_pole=bear_pole,
                current_lean=current_lean, resolution_signal=resolution_signal,
                version=version, confidence=confidence,
                session_id=session_id, user_id=user_id,
                first_seen_at=now, updated_at=now,
            )
            session.add(row)
        else:
            if expect_version is not None and row.version != expect_version:
                logger.warning(
                    "[dossier_repo] write_debate optimistic conflict for %s: "
                    "expect=%s current=%s", ticker, expect_version, row.version,
                )
                return None
            row.question = question or row.question
            row.bull_pole = bull_pole or row.bull_pole
            row.bear_pole = bear_pole or row.bear_pole
            row.current_lean = current_lean
            row.resolution_signal = resolution_signal or row.resolution_signal
            row.version = version
            row.confidence = confidence
            row.session_id = session_id or row.session_id
            if user_id is not None:
                row.user_id = user_id
            row.updated_at = now

        await session.flush()
        logger.debug("[dossier_repo] write_debate for %s (version=%s)", ticker, row.version)
        return row
    except Exception as exc:
        logger.warning("[dossier_repo] write_debate failed for %s: %r", ticker, exc)
        return None


async def update_debate_lean(
    session,
    ticker: str,
    lean: str,
    session_id: str = "",
) -> Optional[Any]:
    """Non-versioning update of current_lean only.

    Used when a synthesis shifts the lean but does not trigger a full
    debate re-version (spec §4.2 — only lean is updated in place).
    """
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        row = await get_debate(session, ticker)
        if row is None:
            logger.debug("[dossier_repo] update_debate_lean: no debate row for %s", ticker)
            return None
        row.current_lean = lean
        row.updated_at = _now()
        if session_id:
            row.session_id = session_id
        await session.flush()
        return row
    except Exception as exc:
        logger.warning("[dossier_repo] update_debate_lean failed for %s: %r", ticker, exc)
        return None


# ===========================================================================
# MOAT — dossier_moat_dimension
# ===========================================================================

async def get_dimensions(
    session,
    ticker: str,
) -> List[Any]:
    """Return all DossierMoatDimension rows for *ticker* ordered by axis."""
    if session is None:
        return []
    ticker = _norm(ticker)
    try:
        from sqlalchemy import select
        from ..models import DossierMoatDimension
        stmt = (
            select(DossierMoatDimension)
            .where(DossierMoatDimension.ticker == ticker)
            .order_by(DossierMoatDimension.axis)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[dossier_repo] get_dimensions failed for %s: %r", ticker, exc)
        return []


async def upsert_dimension(
    session,
    ticker: str,
    axis: str,
    *,
    strength: str = "moderate",
    trend: str = "stable",
    rationale: str = "",
    vulnerability: str = "",
    version: int = 1,
    confidence: float = 0.0,
    pending_flip: bool = False,
    session_id: str = "",
    user_id: Optional[str] = None,
    expect_version: Optional[int] = None,
) -> Optional[Any]:
    """Create-or-update a single moat axis for *ticker*.

    Respects *expect_version* for optimistic concurrency (same semantics
    as write_debate).
    """
    if session is None:
        return None
    ticker = _norm(ticker)
    axis = axis.strip().lower()[:60]
    try:
        from sqlalchemy import select
        from ..models import DossierMoatDimension
        now = _now()
        stmt = (
            select(DossierMoatDimension)
            .where(
                DossierMoatDimension.ticker == ticker,
                DossierMoatDimension.axis == axis,
            )
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is None:
            row = DossierMoatDimension(
                id=_uuid(), ticker=ticker, axis=axis,
                strength=strength, trend=trend,
                rationale=rationale, vulnerability=vulnerability,
                version=version, confidence=confidence,
                pending_flip=pending_flip,
                session_id=session_id, user_id=user_id,
                last_changed_at=now,
            )
            session.add(row)
        else:
            if expect_version is not None and row.version != expect_version:
                logger.warning(
                    "[dossier_repo] upsert_dimension optimistic conflict for %s/%s: "
                    "expect=%s current=%s", ticker, axis, expect_version, row.version,
                )
                return None
            row.strength = strength
            row.trend = trend
            row.rationale = rationale or row.rationale
            row.vulnerability = vulnerability or row.vulnerability
            row.version = version
            row.confidence = confidence
            row.pending_flip = pending_flip
            row.session_id = session_id or row.session_id
            if user_id is not None:
                row.user_id = user_id
            row.last_changed_at = now

        await session.flush()
        logger.debug("[dossier_repo] upsert_dimension %s/%s (version=%s, pending_flip=%s)",
                     ticker, axis, row.version, row.pending_flip)
        return row
    except Exception as exc:
        logger.warning("[dossier_repo] upsert_dimension failed for %s/%s: %r",
                       ticker, axis, exc)
        return None


async def set_pending_flip(
    session,
    ticker: str,
    axis: str,
    pending: bool,
    session_id: str = "",
) -> Optional[Any]:
    """Toggle the hysteresis pending_flip flag on a moat axis.

    Non-versioning: only the flag and last_changed_at are touched.
    """
    if session is None:
        return None
    ticker = _norm(ticker)
    axis = axis.strip().lower()[:60]
    try:
        from sqlalchemy import select
        from ..models import DossierMoatDimension
        stmt = (
            select(DossierMoatDimension)
            .where(
                DossierMoatDimension.ticker == ticker,
                DossierMoatDimension.axis == axis,
            )
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            logger.debug("[dossier_repo] set_pending_flip: no row for %s/%s", ticker, axis)
            return None
        row.pending_flip = pending
        row.last_changed_at = _now()
        if session_id:
            row.session_id = session_id
        await session.flush()
        return row
    except Exception as exc:
        logger.warning("[dossier_repo] set_pending_flip failed for %s/%s: %r",
                       ticker, axis, exc)
        return None


# ===========================================================================
# CATALYST — dossier_catalyst
# ===========================================================================

async def list_catalysts(
    session,
    ticker: str,
    status: Optional[str] = None,
) -> List[Any]:
    """Return DossierCatalyst rows for *ticker*, optionally filtered by status.

    Ordered by created_at DESC (newest first).
    """
    if session is None:
        return []
    ticker = _norm(ticker)
    try:
        from sqlalchemy import select
        from ..models import DossierCatalyst
        stmt = (
            select(DossierCatalyst)
            .where(DossierCatalyst.ticker == ticker)
        )
        if status is not None:
            stmt = stmt.where(DossierCatalyst.status == status)
        stmt = stmt.order_by(DossierCatalyst.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[dossier_repo] list_catalysts failed for %s: %r", ticker, exc)
        return []


async def append_catalyst(
    session,
    ticker: str,
    *,
    statement: str,
    direction: str = "bull_trigger",
    specificity: float = 0.0,
    expected_window: str = "",
    conviction_weight: float = 0.0,
    source_version_id: Optional[str] = None,
    session_id: str = "",
    user_id: Optional[str] = None,
) -> Optional[Any]:
    """Insert a new DossierCatalyst row.

    UUID is stable for hit/miss tracking — do not deduplicate here;
    the extraction service decides whether a statement is truly new.
    """
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        from ..models import DossierCatalyst
        now = _now()
        row = DossierCatalyst(
            id=_uuid(), ticker=ticker,
            statement=statement, direction=direction,
            specificity=specificity, expected_window=expected_window,
            status="open", conviction_weight=conviction_weight,
            source_version_id=source_version_id,
            session_id=session_id, user_id=user_id,
            created_at=now, resolved_at=None,
        )
        session.add(row)
        await session.flush()
        logger.debug("[dossier_repo] appended catalyst %s for %s", row.id[:8], ticker)
        return row
    except Exception as exc:
        logger.warning("[dossier_repo] append_catalyst failed for %s: %r", ticker, exc)
        return None


# Valid catalyst status transitions (open → {triggered, invalidated, expired})
_VALID_TRANSITIONS = {
    "open":        {"triggered", "invalidated", "expired"},
    "triggered":   set(),
    "invalidated": set(),
    "expired":     set(),
}


async def transition_catalyst(
    session,
    catalyst_id: str,
    new_status: str,
    session_id: str = "",
) -> Optional[Any]:
    """Transition a catalyst to a terminal status.

    Only open catalysts can transition. Returns None and logs a warning
    if the transition is invalid or the row is not found.
    """
    if session is None:
        return None
    try:
        from sqlalchemy import select
        from ..models import DossierCatalyst
        stmt = select(DossierCatalyst).where(DossierCatalyst.id == catalyst_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            logger.warning("[dossier_repo] transition_catalyst: id %s not found", catalyst_id[:8])
            return None
        allowed = _VALID_TRANSITIONS.get(row.status, set())
        if new_status not in allowed:
            logger.warning(
                "[dossier_repo] invalid transition %s → %s for catalyst %s",
                row.status, new_status, catalyst_id[:8],
            )
            return None
        row.status = new_status
        row.resolved_at = _now()
        if session_id:
            row.session_id = session_id
        await session.flush()
        logger.debug("[dossier_repo] catalyst %s → %s", catalyst_id[:8], new_status)
        return row
    except Exception as exc:
        logger.warning("[dossier_repo] transition_catalyst failed for %s: %r",
                       catalyst_id, exc)
        return None


# ===========================================================================
# VARIANT — dossier_variant
# ===========================================================================

async def get_variant(session, ticker: str) -> Optional[Any]:
    """Return the DossierVariant row for *ticker*, or None."""
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        from sqlalchemy import select
        from ..models import DossierVariant
        stmt = select(DossierVariant).where(DossierVariant.ticker == ticker)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[dossier_repo] get_variant failed for %s: %r", ticker, exc)
        return None


async def write_variant(
    session,
    ticker: str,
    *,
    divergences: List[Dict[str, Any]],
    version: int = 1,
    confidence: float = 0.0,
    session_id: str = "",
    user_id: Optional[str] = None,
    expect_version: Optional[int] = None,
) -> Optional[Any]:
    """Create-or-update the DossierVariant row for *ticker*.

    *divergences* is a list of consensus-divergence objects (bounded 2–3 entries
    per spec); stored as JSON, never queried by element.
    """
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        from ..models import DossierVariant
        now = _now()
        row = await get_variant(session, ticker)
        if row is None:
            row = DossierVariant(
                id=_uuid(), ticker=ticker,
                divergences=divergences,
                version=version, confidence=confidence,
                session_id=session_id, user_id=user_id,
                updated_at=now,
            )
            session.add(row)
        else:
            if expect_version is not None and row.version != expect_version:
                logger.warning(
                    "[dossier_repo] write_variant optimistic conflict for %s: "
                    "expect=%s current=%s", ticker, expect_version, row.version,
                )
                return None
            row.divergences = divergences
            row.version = version
            row.confidence = confidence
            row.session_id = session_id or row.session_id
            if user_id is not None:
                row.user_id = user_id
            row.updated_at = now

        await session.flush()
        logger.debug("[dossier_repo] write_variant for %s (version=%s)", ticker, row.version)
        return row
    except Exception as exc:
        logger.warning("[dossier_repo] write_variant failed for %s: %r", ticker, exc)
        return None


# ===========================================================================
# DURABILITY — dossier_durability  (raw signals, non-versioned)
# ===========================================================================

async def get_durability(session, ticker: str) -> Optional[Any]:
    """Return the DossierDurability row for *ticker*, or None."""
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        from sqlalchemy import select
        from ..models import DossierDurability
        stmt = select(DossierDurability).where(DossierDurability.ticker == ticker)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[dossier_repo] get_durability failed for %s: %r", ticker, exc)
        return None


async def write_durability(
    session,
    ticker: str,
    *,
    cycle_position: str = "unknown",
    catalyst_proximity_days: Optional[int] = None,
    analog_time_to_trough_days: Optional[int] = None,
    conviction_trend: str = "stable",
    horizon_hint: str = "investment",
    session_id: str = "",
    user_id: Optional[str] = None,
) -> Optional[Any]:
    """Create-or-overwrite the DossierDurability row for *ticker*.

    No version column — signals are always current values (scoring is a
    pure function at read time, never stored here).
    """
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        from ..models import DossierDurability
        now = _now()
        row = await get_durability(session, ticker)
        if row is None:
            row = DossierDurability(
                id=_uuid(), ticker=ticker,
                cycle_position=cycle_position,
                catalyst_proximity_days=catalyst_proximity_days,
                analog_time_to_trough_days=analog_time_to_trough_days,
                conviction_trend=conviction_trend,
                horizon_hint=horizon_hint,
                session_id=session_id, user_id=user_id,
                updated_at=now,
            )
            session.add(row)
        else:
            row.cycle_position = cycle_position
            row.catalyst_proximity_days = catalyst_proximity_days
            row.analog_time_to_trough_days = analog_time_to_trough_days
            row.conviction_trend = conviction_trend
            row.horizon_hint = horizon_hint
            row.session_id = session_id or row.session_id
            if user_id is not None:
                row.user_id = user_id
            row.updated_at = now

        await session.flush()
        logger.debug("[dossier_repo] write_durability for %s", ticker)
        return row
    except Exception as exc:
        logger.warning("[dossier_repo] write_durability failed for %s: %r", ticker, exc)
        return None


# ===========================================================================
# FAILURE MODE — dossier_failure_mode
# ===========================================================================

async def list_failure_modes(session, ticker: str) -> List[Any]:
    """Return all DossierFailureMode rows for *ticker* ordered by sequence_stage."""
    if session is None:
        return []
    ticker = _norm(ticker)
    try:
        from sqlalchemy import select
        from ..models import DossierFailureMode
        stmt = (
            select(DossierFailureMode)
            .where(DossierFailureMode.ticker == ticker)
            .order_by(DossierFailureMode.sequence_stage)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[dossier_repo] list_failure_modes failed for %s: %r", ticker, exc)
        return []


async def upsert_failure_mode(
    session,
    ticker: str,
    analog_id: str,
    *,
    sequence_stage: int = 1,
    stage_evidence: str = "",
    relevance_at_match: float = 0.0,
    session_id: str = "",
    user_id: Optional[str] = None,
) -> Optional[Any]:
    """Create-or-update a failure-mode row for the ticker × analog pair.

    UNIQUE(ticker, analog_id) — only one row per analog per ticker.
    Stage updates in place (stage can advance as new evidence accrues).
    Never deleted.
    """
    if session is None:
        return None
    ticker = _norm(ticker)
    try:
        from sqlalchemy import select
        from ..models import DossierFailureMode
        now = _now()
        stmt = (
            select(DossierFailureMode)
            .where(
                DossierFailureMode.ticker == ticker,
                DossierFailureMode.analog_id == analog_id,
            )
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is None:
            row = DossierFailureMode(
                id=_uuid(), ticker=ticker, analog_id=analog_id,
                sequence_stage=sequence_stage,
                stage_evidence=stage_evidence,
                relevance_at_match=relevance_at_match,
                session_id=session_id, user_id=user_id,
                matched_at=now,
            )
            session.add(row)
        else:
            row.sequence_stage = sequence_stage
            row.stage_evidence = stage_evidence or row.stage_evidence
            row.relevance_at_match = relevance_at_match
            row.session_id = session_id or row.session_id
            if user_id is not None:
                row.user_id = user_id

        await session.flush()
        logger.debug("[dossier_repo] upsert_failure_mode %s/analog=%s stage=%s",
                     ticker, analog_id[:8], sequence_stage)
        return row
    except Exception as exc:
        logger.warning("[dossier_repo] upsert_failure_mode failed for %s: %r", ticker, exc)
        return None
