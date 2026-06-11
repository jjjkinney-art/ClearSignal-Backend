"""
Phase 9G · Phase 0 — Append-only audit trail for Company Dossier.

Separate from dossier_repo.py so that the immutability contract is
structurally visible in code review: this module exposes **no update or
delete path** for either table it owns.

Tables owned:
  dossier_revision     — every material facet change, one row per event
  dossier_evidence_ref — per-claim provenance spine

Both tables have no onupdate column and no UPDATE/DELETE anywhere in this
module.  If you find yourself wanting to call session.delete() or UPDATE
on these tables, you have the wrong file.

Conventions:
  * session is None → return None / []  (null-object)
  * await session.flush() — caller controls the transaction boundary
  * no business logic
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


# ===========================================================================
# REVISION — dossier_revision  (append-only)
# ===========================================================================

async def append_revision(
    session,
    ticker: str,
    facet: str,
    *,
    prev_version: Optional[int] = None,
    new_version: int,
    change_summary: str = "",
    diff_json: Optional[Dict[str, Any]] = None,
    confidence: float = 0.0,
    source_version_id: Optional[str] = None,
    session_id: str = "",
    user_id: Optional[str] = None,
) -> Optional[Any]:
    """Insert one immutable revision row.

    *prev_version* is None for first-create events (no prior state).
    *diff_json* is a before/after snapshot of the changed facet; defaults
    to empty dict when not provided.

    This function never updates or deletes existing rows.
    """
    if session is None:
        return None
    try:
        from ..models import DossierRevision
        row = DossierRevision(
            id=_uuid(),
            ticker=ticker.strip().upper()[:20],
            facet=facet[:40],
            prev_version=prev_version,
            new_version=new_version,
            change_summary=change_summary,
            diff_json=diff_json if diff_json is not None else {},
            confidence=confidence,
            source_version_id=source_version_id,
            session_id=session_id,
            user_id=user_id,
            created_at=_now(),
        )
        session.add(row)
        await session.flush()
        logger.debug(
            "[dossier_revision_repo] appended revision for %s/%s (v%s→v%s)",
            ticker, facet, prev_version, new_version,
        )
        return row
    except Exception as exc:
        logger.warning("[dossier_revision_repo] append_revision failed for %s/%s: %r",
                       ticker, facet, exc)
        return None


async def get_timeline(
    session,
    ticker: str,
    facet: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return revision history for *ticker*, optionally filtered by *facet*.

    Ordered newest-first.  Returns a list of plain dicts suitable for the
    read API (Slice 6).
    """
    if session is None:
        return []
    ticker = ticker.strip().upper()[:20]
    try:
        from sqlalchemy import select
        from ..models import DossierRevision
        stmt = select(DossierRevision).where(DossierRevision.ticker == ticker)
        if facet is not None:
            stmt = stmt.where(DossierRevision.facet == facet)
        stmt = stmt.order_by(DossierRevision.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "ticker": r.ticker,
                "facet": r.facet,
                "prev_version": r.prev_version,
                "new_version": r.new_version,
                "change_summary": r.change_summary,
                "diff_json": r.diff_json if isinstance(r.diff_json, dict) else {},
                "confidence": r.confidence,
                "source_version_id": r.source_version_id,
                "session_id": r.session_id,
                "user_id": r.user_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("[dossier_revision_repo] get_timeline failed for %s: %r", ticker, exc)
        return []


# ===========================================================================
# EVIDENCE REF — dossier_evidence_ref  (append-only)
# ===========================================================================

async def append_evidence_ref(
    session,
    ticker: str,
    facet: str,
    claim_hash: str,
    *,
    source_type: str = "inferred",
    source_id: Optional[str] = None,
    session_id: str = "",
    user_id: Optional[str] = None,
) -> Optional[Any]:
    """Insert one evidence provenance row.

    *source_id* is None for inferred claims (no backing document).
    *source_type* choices: thesis_version | analog | filing |
                           financial_data | inferred.

    This function never updates or deletes existing rows.
    """
    if session is None:
        return None
    try:
        from ..models import DossierEvidenceRef
        row = DossierEvidenceRef(
            id=_uuid(),
            ticker=ticker.strip().upper()[:20],
            facet=facet[:40],
            claim_hash=claim_hash[:64],
            source_type=source_type[:30],
            source_id=source_id,
            session_id=session_id,
            user_id=user_id,
            as_of=_now(),
        )
        session.add(row)
        await session.flush()
        logger.debug(
            "[dossier_revision_repo] appended evidence_ref for %s/%s (type=%s)",
            ticker, facet, source_type,
        )
        return row
    except Exception as exc:
        logger.warning("[dossier_revision_repo] append_evidence_ref failed for %s/%s: %r",
                       ticker, facet, exc)
        return None


async def get_evidence_refs(
    session,
    ticker: str,
    facet: Optional[str] = None,
) -> List[Any]:
    """Return DossierEvidenceRef rows for *ticker*, optionally filtered by *facet*.

    Returns ORM objects (not dicts) so callers can inspect source_type for
    rendering decisions (inferred claims are visually distinct in the UI).
    """
    if session is None:
        return []
    ticker = ticker.strip().upper()[:20]
    try:
        from sqlalchemy import select
        from ..models import DossierEvidenceRef
        stmt = select(DossierEvidenceRef).where(DossierEvidenceRef.ticker == ticker)
        if facet is not None:
            stmt = stmt.where(DossierEvidenceRef.facet == facet)
        stmt = stmt.order_by(DossierEvidenceRef.as_of.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[dossier_revision_repo] get_evidence_refs failed for %s: %r", ticker, exc)
        return []
