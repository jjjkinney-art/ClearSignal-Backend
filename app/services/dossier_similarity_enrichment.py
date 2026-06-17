"""
Dossier Similarity Enrichment — Phase 11 · Slice 7.

Adds a read-only "similarity_context" block to a dossier payload. This
module does NOT modify app/db/repositories/dossier_repo.py — it wraps
get_full_dossier() additively so existing callers (dossier_injection_service,
any future consumer) are completely unaffected unless they explicitly call
the wrapper here.

Hard boundaries:
  - Never writes to any table (delegates entirely to the existing,
    read-only similarity_read_service from Slice 6).
  - Never touches head/debate/dimensions/catalysts/variant/durability/
    failure_modes — those keys pass through get_full_dossier() unchanged.
  - Never influences conviction, stance, verdict, or forecast in any way —
    this module has no import path into synthesis, conviction scoring, or
    forecasting code, and is not wired into dossier_injection_service's
    prompt-construction path. Nothing currently calls this module from any
    live request flow; it exists for explicit, opt-in use only — that is
    what keeps Slice 7 "no user-visible rollout."
  - similarity_context defaults to the safe-empty shape whenever
    similarity_build_enabled or similarity_scoring_enabled is False (the
    production default), regardless of what similarity data might already
    exist in the database — Phase 11 stays invisible until those flags are
    deliberately flipped.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _empty_similarity_context(ticker: str) -> Dict[str, Any]:
    from app.services.similarity_read_service import DISCLAIMER

    return {"has_similarity": False, "ticker": ticker, "matches": [], "disclaimer": DISCLAIMER}


async def build_similarity_context_block(session, ticker: str) -> Dict[str, Any]:
    """Read-only similarity_context block for *ticker*.

    Thin pass-through to similarity_read_service.get_resembles_facet_for_ticker
    (Slice 6) — no new logic, no rebuild, no write. Falls back to the safe
    empty shape on any error.
    """
    try:
        from app.services.similarity_read_service import get_resembles_facet_for_ticker

        return await get_resembles_facet_for_ticker(session, ticker)
    except Exception as exc:
        logger.debug(
            "[dossier_similarity_enrichment] build_similarity_context_block failed for %s: %r",
            ticker, exc,
        )
        return _empty_similarity_context(ticker)


async def get_full_dossier_with_similarity_context(session, ticker: str) -> Dict[str, Any]:
    """get_full_dossier()'s payload plus an additive "similarity_context" key.

    Every other key (head, debate, dimensions, catalysts, variant,
    durability, failure_modes) is returned exactly as get_full_dossier()
    produced it — this function never reads or modifies those fields.

    similarity_context is the safe-empty block whenever
    similarity_build_enabled or similarity_scoring_enabled is False (the
    default), even if session is otherwise valid and similarity data
    happens to exist.
    """
    from app.db.repositories.dossier_repo import get_full_dossier

    dossier = await get_full_dossier(session, ticker)

    try:
        from app.config import settings

        if not (
            getattr(settings, "similarity_build_enabled", False)
            and getattr(settings, "similarity_scoring_enabled", False)
        ):
            dossier["similarity_context"] = _empty_similarity_context(ticker)
            return dossier
    except Exception as exc:
        logger.debug(
            "[dossier_similarity_enrichment] flag check failed for %s: %r", ticker, exc,
        )
        dossier["similarity_context"] = _empty_similarity_context(ticker)
        return dossier

    dossier["similarity_context"] = await build_similarity_context_block(session, ticker)
    return dossier
