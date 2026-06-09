"""
Thesis repository — CRUD for thesis_versions and thesis_deltas.

All functions accept an optional AsyncSession.  When session is None
(persistence disabled) they return sensible defaults / no-ops so that
callers need not branch on DB availability.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jaccard(text_a: str, text_b: str) -> float:
    """Jaccard similarity between two texts measured on word sets.

    Returns 1.0 when both texts are identical (or both empty).
    Returns 0.0 when there is no word overlap.
    """
    if not text_a and not text_b:
        return 1.0
    words_a = set(re.findall(r"\w+", text_a.lower()))
    words_b = set(re.findall(r"\w+", text_b.lower()))
    if not words_a and not words_b:
        return 1.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union if union > 0 else 0.0


def _compute_magnitude(
    stance_changed: bool,
    conviction_delta: float,
    changed_field_count: int,
) -> str:
    """Classify the magnitude of change between two thesis versions.

    Rules
    -----
    material  — stance changed **or** |conviction_delta| > 0.15
    moderate  — |conviction_delta| > 0.07 **or** > 2 fields changed
    minor     — all other cases
    """
    abs_delta = abs(conviction_delta)
    if stance_changed or abs_delta > 0.15:
        return "material"
    if abs_delta > 0.07 or changed_field_count > 2:
        return "moderate"
    return "minor"


# ---------------------------------------------------------------------------
# thesis_versions
# ---------------------------------------------------------------------------

async def create_version(
    session,
    ticker: str,
    company_name: str,
    session_id: str,
    question: str,
    thesis_data: Dict[str, Any],
    user_id: Optional[str] = None,
) -> Optional[Any]:
    """Insert a new ThesisVersion row and return it.

    Parameters
    ----------
    session:
        AsyncSession or None.
    ticker, company_name, session_id, question:
        Identity fields.
    thesis_data:
        Dict produced by ``InvestmentThesis.model_dump()`` (or similar).

    Returns
    -------
    ThesisVersion ORM object, or None if session is None.
    """
    if session is None:
        return None

    try:
        from ..models import ThesisVersion

        def _safe_json(val, default="[]") -> str:
            if val is None:
                return default
            if isinstance(val, str):
                return val
            return json.dumps(val)

        row = ThesisVersion(
            id=str(uuid.uuid4()),
            ticker=ticker,
            company_name=company_name,
            session_id=session_id,
            question=question,
            directional_stance=str(thesis_data.get("directional_stance") or ""),
            confidence_score=float(thesis_data.get("confidence_score") or 0.0),
            bull_thesis=str(thesis_data.get("bull_thesis") or ""),
            bear_thesis=str(thesis_data.get("bear_thesis") or ""),
            verdict_rationale=str(thesis_data.get("verdict_rationale") or ""),
            direct_answer=str(thesis_data.get("direct_answer") or ""),
            why_not=str(thesis_data.get("why_not") or ""),
            conclusion=str(thesis_data.get("conclusion") or ""),
            key_drivers=_safe_json(thesis_data.get("key_drivers"), "[]"),
            key_risks=_safe_json(thesis_data.get("key_risks"), "[]"),
            macro_sensitivity=_safe_json(thesis_data.get("macro_sensitivity"), "{}"),
            threshold_zones=_safe_json(thesis_data.get("threshold_zones"), "{}"),
            user_id=(user_id or None),
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        logger.debug("[thesis_repo] created version %s for %s", row.id[:8], ticker)
        return row

    except Exception as exc:
        logger.warning("[thesis_repo] create_version failed for %s: %r", ticker, exc)
        return None


async def get_latest_version(session, ticker: str) -> Optional[Any]:
    """Return the most recent ThesisVersion for a ticker, or None."""
    if session is None:
        return None

    try:
        from sqlalchemy import select
        from ..models import ThesisVersion

        stmt = (
            select(ThesisVersion)
            .where(ThesisVersion.ticker == ticker)
            .order_by(ThesisVersion.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    except Exception as exc:
        logger.warning("[thesis_repo] get_latest_version failed for %s: %r", ticker, exc)
        return None


# ---------------------------------------------------------------------------
# thesis_deltas
# ---------------------------------------------------------------------------

async def create_delta(
    session,
    from_version: Any,
    to_version: Any,
) -> Optional[Any]:
    """Compute and insert a ThesisDelta between two ThesisVersion rows.

    Parameters
    ----------
    from_version, to_version:
        ThesisVersion ORM objects.  ``from_version`` is the older snapshot;
        ``to_version`` is the newer snapshot just created.

    Returns
    -------
    ThesisDelta ORM object, or None on failure.
    """
    if session is None or from_version is None or to_version is None:
        return None

    try:
        from ..models import ThesisDelta

        # ── Scalar diffs ──────────────────────────────────────────────────────
        stance_changed = (
            from_version.directional_stance != to_version.directional_stance
        )
        conviction_delta = (
            to_version.confidence_score - from_version.confidence_score
        )

        # ── Text similarity ───────────────────────────────────────────────────
        bull_sim = _jaccard(from_version.bull_thesis, to_version.bull_thesis)
        bear_sim = _jaccard(from_version.bear_thesis, to_version.bear_thesis)

        # ── Changed fields list ───────────────────────────────────────────────
        changed: List[str] = []
        if stance_changed:
            changed.append("directional_stance")
        if abs(conviction_delta) > 0.01:
            changed.append("confidence_score")
        if bull_sim < 0.95:
            changed.append("bull_thesis")
        if bear_sim < 0.95:
            changed.append("bear_thesis")
        for field in ("verdict_rationale", "direct_answer", "why_not", "conclusion"):
            old_val = getattr(from_version, field, "")
            new_val = getattr(to_version, field, "")
            sim = _jaccard(old_val, new_val)
            if sim < 0.90:
                changed.append(field)

        magnitude = _compute_magnitude(stance_changed, conviction_delta, len(changed))

        row = ThesisDelta(
            id=str(uuid.uuid4()),
            ticker=to_version.ticker,
            from_version_id=from_version.id,
            to_version_id=to_version.id,
            stance_changed=stance_changed,
            conviction_delta=round(conviction_delta, 4),
            bull_thesis_similarity=round(bull_sim, 4),
            bear_thesis_similarity=round(bear_sim, 4),
            magnitude=magnitude,
            changed_fields=json.dumps(changed),
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        logger.debug(
            "[thesis_repo] delta %s for %s: magnitude=%s conviction_delta=%.3f",
            row.id[:8], to_version.ticker, magnitude, conviction_delta,
        )
        return row

    except Exception as exc:
        logger.warning("[thesis_repo] create_delta failed: %r", exc)
        return None


async def get_evolution(
    session,
    ticker: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Return the N most-recent thesis deltas for a ticker.

    Each dict contains the delta fields plus ``created_at`` as ISO string.

    Returns an empty list when persistence is disabled or on error.
    """
    if session is None:
        return []

    try:
        from sqlalchemy import select
        from ..models import ThesisDelta

        stmt = (
            select(ThesisDelta)
            .where(ThesisDelta.ticker == ticker)
            .order_by(ThesisDelta.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "from_version_id": r.from_version_id,
                "to_version_id": r.to_version_id,
                "stance_changed": r.stance_changed,
                "conviction_delta": r.conviction_delta,
                "bull_thesis_similarity": r.bull_thesis_similarity,
                "bear_thesis_similarity": r.bear_thesis_similarity,
                "magnitude": r.magnitude,
                "changed_fields": json.loads(r.changed_fields or "[]"),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    except Exception as exc:
        logger.warning("[thesis_repo] get_evolution failed for %s: %r", ticker, exc)
        return []
