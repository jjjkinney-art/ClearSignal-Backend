"""
Phase 9F — Historical Evidence repository.

Two public coroutines:
  seed_analogs(session)   — idempotent: load JSON seed file and upsert by label.
  get_all_analogs(session) — return all HistoricalAnalog rows (used by retrieval engine).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HistoricalAnalog

logger = logging.getLogger(__name__)

_SEED_FILE = Path(__file__).parent.parent / "data" / "historical_analogs.json"


async def seed_analogs(session: Optional[AsyncSession]) -> int:
    """Load historical_analogs.json and insert any records not already present.

    Returns the number of rows inserted (0 if all already seeded).
    Idempotent: uses label UNIQUE constraint — ON CONFLICT is handled by
    checking existence before insert so this works identically on both
    PostgreSQL and SQLite.
    """
    if session is None:
        return 0

    try:
        raw = _SEED_FILE.read_text(encoding="utf-8")
        records = json.loads(raw)
    except Exception as exc:
        logger.error("[evidence_repo] could not load seed file %s: %s", _SEED_FILE, exc)
        return 0

    inserted = 0
    for rec in records:
        label = rec.get("label", "")
        if not label:
            continue

        # Check if already exists (idempotent)
        stmt = select(HistoricalAnalog).where(HistoricalAnalog.label == label)
        existing = (await session.execute(stmt)).scalars().first()
        if existing is not None:
            continue

        analog = HistoricalAnalog(
            id=rec.get("id") or None,
            label=label,
            episode=rec.get("episode", ""),
            entity_ticker=rec.get("entity_ticker"),
            sector=rec.get("sector", ""),
            business_model=rec.get("business_model", ""),
            quality_rating=rec.get("quality_rating", "moderate"),
            mechanism=rec.get("mechanism", ""),
            concern_tags=rec.get("concern_tags", []),
            valuation_regime=rec.get("valuation_regime", ""),
            growth_phase=rec.get("growth_phase", ""),
            macro_regime=rec.get("macro_regime", ""),
            event_start=_parse_date(rec.get("event_start")),
            event_end=_parse_date(rec.get("event_end")),
            drawdown_pct=rec.get("drawdown_pct"),
            time_to_trough_days=rec.get("time_to_trough_days"),
            time_to_recover_days=rec.get("time_to_recover_days"),
            outcome_summary=rec.get("outcome_summary", ""),
            reaction_series=rec.get("reaction_series", []),
            why_relevant=rec.get("why_relevant", ""),
            disanalogy=rec.get("disanalogy", ""),
            base_rate_note=rec.get("base_rate_note", ""),
            data_confidence=rec.get("data_confidence", "moderate"),
            source_note=rec.get("source_note", ""),
        )
        session.add(analog)
        inserted += 1

    if inserted:
        await session.flush()

    logger.info("[evidence_repo] seed complete: %d inserted, %d already present",
                inserted, len(records) - inserted)
    return inserted


async def get_all_analogs(session: Optional[AsyncSession]) -> List[HistoricalAnalog]:
    """Return all HistoricalAnalog rows ordered by quality_rating desc, id asc."""
    if session is None:
        return []

    stmt = (
        select(HistoricalAnalog)
        .order_by(HistoricalAnalog.quality_rating.desc(), HistoricalAnalog.id.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_date(value):
    """Parse ISO date string to Python date; return None on failure."""
    if not value:
        return None
    try:
        from datetime import date
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
