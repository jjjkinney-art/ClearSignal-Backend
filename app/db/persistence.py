"""
Persistence orchestrator — Phase 9A/9B.

Entry point: ``persist_analysis_result()``.

This function is called as a fire-and-forget asyncio task from the /ask
endpoint after the JSON body has been yielded to the client.  It must:

  1. Never raise to the caller — all errors are logged and swallowed.
  2. Never block the response — it runs after ``yield`` in the generator.
  3. Degrade gracefully — when DATABASE_URL is empty, every call is a no-op.

Persistence sequence for one /ask call
---------------------------------------
  1. Open a DB session via ``get_session()``.
  2. Extract InvestmentThesis fields from AgentAnswerResponse.
  3. Create a ThesisVersion row.
  4. Fetch the previous ThesisVersion for this ticker (if any) and compute delta.
  5. Get-or-create TickerMemory; update its aggregate fields.
  6. Append a MemoryEntry of type "analysis".
  7. Extract concern tags from question + thesis text; upsert ConcernTag rows.
  8. Compute dominant_concern from current tag counts; update TickerMemory.
  9. Session commit (handled by get_session context manager).

If any step raises an exception it is caught and logged; remaining steps
continue where possible so a single bad field does not block all writes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_thesis(result: Any) -> Optional[Dict[str, Any]]:
    """Extract investment_thesis dict from an AgentAnswerResponse.

    The answer field is a dict whose 'investment_thesis' key holds either:
      - A nested dict (when already model_dump'd)
      - An InvestmentThesis Pydantic object

    Returns None when no thesis is found.
    """
    try:
        answer = getattr(result, "answer", None)
        if not answer:
            return None

        thesis = answer.get("investment_thesis")
        if thesis is None:
            return None

        # If it's a Pydantic model, dump it
        if hasattr(thesis, "model_dump"):
            return thesis.model_dump()
        if hasattr(thesis, "dict"):
            return thesis.dict()
        if isinstance(thesis, dict):
            return thesis

        return None

    except Exception as exc:
        logger.debug("[persistence] _extract_thesis failed: %r", exc)
        return None


def _extract_ticker(result: Any, company_name: str) -> str:
    """Extract and canonicalize ticker from the thesis or company_name.

    Phase 9B: routes through ticker_normalizer to prevent fragmented history
    when the model returns 'Nvidia' vs 'NVDA' vs 'NVIDIA Corporation'.
    """
    try:
        from .ticker_normalizer import canonical_ticker_for_thesis
        thesis = _extract_thesis(result)
        if thesis:
            return canonical_ticker_for_thesis(thesis, company_name)
    except Exception:
        pass
    # Hard fallback — should rarely be reached
    from .ticker_normalizer import normalize_ticker
    return normalize_ticker(company_name) if company_name else "UNKNOWN"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def persist_analysis_result(
    question: str,
    company_name: str,
    session_id: str,
    result: Any,
    user_id: Optional[str] = None,
) -> None:
    """Persist one /ask analysis result.

    Designed to be called as ``asyncio.create_task(persist_analysis_result(...))``
    so it runs concurrently with the response being streamed to the client.

    All exceptions are caught and logged.  This function is guaranteed to
    return without raising.

    Parameters
    ----------
    question:
        The user's original question string.
    company_name:
        The company_name field from QuestionRequest.
    session_id:
        HTTP session / request ID (max 64 chars, truncated if longer).
    result:
        The AgentAnswerResponse returned by route_question().
    user_id:
        Optional stable UUID for the authenticated user (Phase 9C).
        Pass None for anonymous sessions.
    """
    try:
        await _persist_inner(question, company_name, session_id, result, user_id)
    except Exception as exc:
        logger.warning("[persistence] unhandled error in persist_analysis_result: %r", exc)


async def _persist_inner(
    question: str,
    company_name: str,
    session_id: str,
    result: Any,
    user_id: Optional[str] = None,
) -> None:
    """Inner implementation — may raise; wrapped by persist_analysis_result."""
    from .connection import get_session
    from .concern_extractor import extract_concerns, dominant_concern
    from .repositories.thesis_repo import create_version, get_latest_version
    from .repositories.evolution_repo import create_delta_with_debounce  # Phase 9B
    from .repositories.memory_repo import get_or_create_memory, append_entry, update_memory
    from .repositories.concern_repo import upsert_tags, get_tags_for_ticker

    # Truncate session_id to 64 chars (column width)
    session_id = (session_id or "")[:64]

    # Step 1: extract thesis dict
    thesis = _extract_thesis(result)
    if thesis is None:
        logger.debug("[persistence] no investment_thesis in result — skipping")
        return

    ticker = _extract_ticker(result, company_name)

    # Guard: never persist wall-cap fallback theses.  The fallback object
    # has confidence_score=0.0 and a sentinel conclusion set by router_service.
    # Saving it would inject a synthetic 0.0 into the conviction_trend which
    # shows up in the banner as "42% → 0%" on the next analysis.
    _conclusion = thesis.get("conclusion", "") or ""
    _bull = thesis.get("bull_thesis", "") or ""
    if "wall cap exceeded" in _conclusion or "Synthesis unavailable" in _bull:
        logger.debug("[persistence] skipping wall-cap fallback thesis for %s (not a real analysis)", ticker)
        return

    async with get_session() as session:
        if session is None:
            return  # persistence disabled

        # ── Step 2: create ThesisVersion ──────────────────────────────────────
        version = await create_version(
            session=session,
            ticker=ticker,
            company_name=company_name or thesis.get("company_name") or ticker,
            session_id=session_id,
            question=question,
            thesis_data=thesis,
            user_id=user_id,
        )

        # ── Step 3: compute delta vs previous version (with debounce) ─────────
        if version is not None:
            prev = await get_latest_version_excluding(session, ticker, version.id)
            if prev is not None:
                await create_delta_with_debounce(
                    session=session, from_version=prev, to_version=version
                )

        # ── Step 4: get-or-create TickerMemory ───────────────────────────────
        await get_or_create_memory(
            session=session,
            ticker=ticker,
            company_name=company_name or ticker,
        )

        # ── Step 5: append MemoryEntry ────────────────────────────────────────
        entry_content = (
            f"Q: {question[:200]}\n"
            f"Stance: {thesis.get('directional_stance', '')}\n"
            f"Conviction: {thesis.get('confidence_score', 0.0):.2f}"
        )
        await append_entry(
            session=session,
            ticker=ticker,
            session_id=session_id,
            entry_type="analysis",
            content=entry_content,
            metadata={
                "directional_stance": thesis.get("directional_stance", ""),
                "confidence_score": thesis.get("confidence_score", 0.0),
                "company_name": company_name,
            },
        )

        # ── Step 6: extract and upsert concern tags ───────────────────────────
        tags = extract_concerns(
            question=question,
            bull_thesis=str(thesis.get("bull_thesis") or ""),
            bear_thesis=str(thesis.get("bear_thesis") or ""),
            verdict_rationale=str(thesis.get("verdict_rationale") or ""),
            direct_answer=str(thesis.get("direct_answer") or ""),
        )
        if tags:
            await upsert_tags(session=session, ticker=ticker, tag_names=tags)

        # ── Step 7: compute dominant concern and update TickerMemory ─────────
        tag_counts = await get_tags_for_ticker(session=session, ticker=ticker)
        dom_concern = dominant_concern(tag_counts)

        await update_memory(
            session=session,
            ticker=ticker,
            stance=str(thesis.get("directional_stance") or ""),
            confidence=float(thesis.get("confidence_score") or 0.0),
            dominant_concern=dom_concern,
            increment_queries=True,
            increment_versions=(version is not None),
        )

        logger.info(
            "[persistence] saved ticker=%s session=%s tags=%s magnitude=N/A",
            ticker, session_id[:8] if session_id else "?", sorted(tags),
        )


async def get_latest_version_excluding(session, ticker: str, exclude_id: str):
    """Return the most recent ThesisVersion for ticker, excluding exclude_id.

    Used to find the *previous* version after the current one was just inserted.
    """
    if session is None:
        return None
    try:
        from sqlalchemy import select
        from .models import ThesisVersion

        stmt = (
            select(ThesisVersion)
            .where(ThesisVersion.ticker == ticker)
            .where(ThesisVersion.id != exclude_id)
            .order_by(ThesisVersion.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[persistence] get_latest_version_excluding failed: %r", exc)
        return None
