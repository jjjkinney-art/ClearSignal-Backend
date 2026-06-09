"""
Evolution repository — Phase 9B.

Provides the read-side queries for:
  - GET /api/ticker/{ticker}/evolution        (list of deltas with summaries)
  - GET /api/ticker/{ticker}/evolution/{id}   (single delta with full text)
  - GET /api/ticker/{ticker}/latest           (most recent version + last delta)
  - GET /api/material-changes                 (cross-ticker material feed)

All functions guard against session=None (persistence disabled) and
swallow internal exceptions so a DB error never crashes a request.

Material change feed deduplication
-----------------------------------
One material delta per ticker per UTC calendar day.  When multiple arrive
on the same day, the one with the largest |conviction_delta| is
``debounce_visible=True``; others are ``False``.

``apply_debounce()`` is called inside ``create_delta_with_debounce()``
(which replaces ``create_delta()`` in persistence.py for 9B).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inline-diff stats helper (no full text transmitted)
# ---------------------------------------------------------------------------

def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text)) if text else 0


def _jaccard(a: str, b: str) -> float:
    wa = set(re.findall(r"\w+", a.lower())) if a else set()
    wb = set(re.findall(r"\w+", b.lower())) if b else set()
    if not wa and not wb:
        return 1.0
    union = len(wa | wb)
    return len(wa & wb) / union if union else 0.0


def _build_inline_diff(from_v: Any, to_v: Any) -> Dict[str, Dict[str, Any]]:
    """Compute word-count + similarity stats for each text field."""
    fields = ["bull_thesis", "bear_thesis", "verdict_rationale", "direct_answer"]
    result: Dict[str, Dict[str, Any]] = {}
    for field in fields:
        f_text = getattr(from_v, field, "") or ""
        t_text = getattr(to_v, field, "") or ""
        result[field] = {
            "similarity": round(_jaccard(f_text, t_text), 4),
            "from_word_count": _word_count(f_text),
            "to_word_count": _word_count(t_text),
        }
    return result


# ---------------------------------------------------------------------------
# Headline generator (pure Python, no LLM)
# ---------------------------------------------------------------------------

def _generate_headline(
    stance_changed: bool,
    from_stance: str,
    to_stance: str,
    conviction_delta: float,
    changed_fields: List[str],
    dominant_concern: str = "",
) -> str:
    """Return a one-line human-readable feed headline."""
    delta_pp = round(conviction_delta * 100)
    sign = "+" if delta_pp >= 0 else ""

    if stance_changed:
        return f"Stance shifted {from_stance or '?'} → {to_stance or '?'}. Conviction {sign}{delta_pp}pp."

    abs_delta = abs(delta_pp)
    if abs_delta >= 10:
        concern_suffix = f" on {dominant_concern}" if dominant_concern else ""
        return f"Conviction revised {sign}{delta_pp}pp{concern_suffix}."

    # Text-heavy change
    n = len(changed_fields)
    if n == 0:
        return "Minor thesis update."
    field_label = changed_fields[0].replace("_", " ")
    suffix = f" (+{n - 1} more)" if n > 1 else ""
    return f"{field_label.title()} revised{suffix}."


# ---------------------------------------------------------------------------
# Debounce: apply within-day deduplication for material deltas
# ---------------------------------------------------------------------------

async def apply_debounce(session, ticker: str, new_delta_id: str) -> None:
    """Mark older same-day material deltas as debounce_visible=False.

    After inserting a new material ThesisDelta, check whether a material
    delta for the same ticker already exists on the same UTC calendar day.
    If one does, suppress whichever has the smaller |conviction_delta|.

    This is called inside ``create_delta_with_debounce()`` after flush.
    """
    if session is None:
        return
    try:
        from sqlalchemy import select, func
        from ..models import ThesisDelta

        today = datetime.now(timezone.utc).date()
        tomorrow_str = f"{today.year}-{today.month:02d}-{today.day + 1:02d}"  # rough bound

        # All material deltas for this ticker today (including the new one)
        stmt = (
            select(ThesisDelta)
            .where(ThesisDelta.ticker == ticker)
            .where(ThesisDelta.magnitude == "material")
            .where(ThesisDelta.created_at >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc))
        )
        result = await session.execute(stmt)
        todays_deltas = list(result.scalars().all())

        if len(todays_deltas) <= 1:
            return  # no duplicates to suppress

        # Sort by |conviction_delta| descending — largest stays visible
        todays_deltas.sort(key=lambda d: abs(d.conviction_delta), reverse=True)
        winner_id = todays_deltas[0].id

        for d in todays_deltas:
            desired = (d.id == winner_id)
            if d.debounce_visible != desired:
                d.debounce_visible = desired

        await session.flush()
        suppressed = [d.id[:8] for d in todays_deltas if not d.debounce_visible]
        if suppressed:
            logger.debug("[evolution_repo] debounce suppressed %s for %s", suppressed, ticker)

    except Exception as exc:
        logger.warning("[evolution_repo] apply_debounce failed for %s: %r", ticker, exc)


# ---------------------------------------------------------------------------
# create_delta_with_debounce  (replaces thesis_repo.create_delta in 9B)
# ---------------------------------------------------------------------------

async def create_delta_with_debounce(session, from_version: Any, to_version: Any) -> Optional[Any]:
    """Create a ThesisDelta and apply within-day debounce for material deltas."""
    if session is None or from_version is None or to_version is None:
        return None

    try:
        from ..repositories.thesis_repo import create_delta
        delta = await create_delta(session=session, from_version=from_version, to_version=to_version)
        if delta is not None and delta.magnitude == "material":
            await apply_debounce(session, to_version.ticker, delta.id)
        return delta
    except Exception as exc:
        logger.warning("[evolution_repo] create_delta_with_debounce failed: %r", exc)
        return None


# ---------------------------------------------------------------------------
# GET /api/ticker/{ticker}/evolution
# ---------------------------------------------------------------------------

async def get_evolution_with_versions(
    session,
    ticker: str,
    limit: int = 20,
    min_magnitude: str = "minor",
    since: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Return EvolutionResponse payload for one ticker.

    Returns None if the ticker has no memory row (404 response).
    Returns dict with empty deltas list if ticker exists but < 2 versions.
    """
    if session is None:
        return None

    try:
        from sqlalchemy import select
        from ..models import ThesisDelta, ThesisVersion, TickerMemory

        # ── Ticker aggregate state ────────────────────────────────────────────
        mem_stmt = select(TickerMemory).where(TickerMemory.ticker == ticker)
        mem_result = await session.execute(mem_stmt)
        mem = mem_result.scalar_one_or_none()
        if mem is None:
            return None  # 404

        # ── Build delta query ─────────────────────────────────────────────────
        MAGNITUDE_ORDER = {"minor": 0, "moderate": 1, "material": 2}
        min_rank = MAGNITUDE_ORDER.get(min_magnitude, 0)

        stmt = (
            select(ThesisDelta)
            .where(ThesisDelta.ticker == ticker)
            .order_by(ThesisDelta.created_at.desc())
            .limit(limit)
        )
        if min_magnitude != "minor":
            allowed = [k for k, v in MAGNITUDE_ORDER.items() if v >= min_rank]
            stmt = stmt.where(ThesisDelta.magnitude.in_(allowed))
        if since is not None:
            stmt = stmt.where(ThesisDelta.created_at > since)

        delta_result = await session.execute(stmt)
        deltas = list(delta_result.scalars().all())

        # ── Bulk-fetch all needed version IDs ─────────────────────────────────
        version_ids: set[str] = set()
        for d in deltas:
            version_ids.add(d.from_version_id)
            version_ids.add(d.to_version_id)

        version_map: Dict[str, Any] = {}
        if version_ids:
            v_stmt = select(ThesisVersion).where(ThesisVersion.id.in_(version_ids))
            v_result = await session.execute(v_stmt)
            for v in v_result.scalars().all():
                version_map[v.id] = v

        # ── Assemble output ───────────────────────────────────────────────────
        delta_list = []
        for d in deltas:
            fv = version_map.get(d.from_version_id)
            tv = version_map.get(d.to_version_id)
            if fv is None or tv is None:
                continue  # orphaned delta — skip
            delta_list.append({
                "delta_id": d.id,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "magnitude": d.magnitude,
                "stance_changed": d.stance_changed,
                "conviction_delta": d.conviction_delta,
                "bull_thesis_similarity": d.bull_thesis_similarity,
                "bear_thesis_similarity": d.bear_thesis_similarity,
                "changed_fields": json.loads(d.changed_fields or "[]"),
                "from_version": {
                    "id": fv.id,
                    "created_at": fv.created_at.isoformat() if fv.created_at else None,
                    "question": fv.question or "",
                    "directional_stance": fv.directional_stance or "",
                    "confidence_score": fv.confidence_score or 0.0,
                    "direct_answer": fv.direct_answer or "",
                    "verdict_rationale": fv.verdict_rationale or "",
                },
                "to_version": {
                    "id": tv.id,
                    "created_at": tv.created_at.isoformat() if tv.created_at else None,
                    "question": tv.question or "",
                    "directional_stance": tv.directional_stance or "",
                    "confidence_score": tv.confidence_score or 0.0,
                    "direct_answer": tv.direct_answer or "",
                    "verdict_rationale": tv.verdict_rationale or "",
                },
            })

        return {
            "ticker": ticker,
            "company_name": mem.company_name or ticker,
            "total_versions": mem.version_count or 0,
            "total_queries": mem.total_queries or 0,
            "last_stance": mem.last_stance or "",
            "last_confidence": mem.last_confidence or 0.0,
            "dominant_concern": mem.dominant_concern or "",
            "deltas": delta_list,
        }

    except Exception as exc:
        logger.warning("[evolution_repo] get_evolution_with_versions failed for %s: %r", ticker, exc)
        return None


# ---------------------------------------------------------------------------
# GET /api/ticker/{ticker}/evolution/{delta_id}
# ---------------------------------------------------------------------------

async def get_delta_full(
    session,
    ticker: str,
    delta_id: str,
) -> Optional[Dict[str, Any]]:
    """Return ThesisDeltaFull payload for one delta including full thesis text."""
    if session is None:
        return None

    try:
        from sqlalchemy import select
        from ..models import ThesisDelta, ThesisVersion

        stmt = (
            select(ThesisDelta)
            .where(ThesisDelta.id == delta_id)
            .where(ThesisDelta.ticker == ticker)
        )
        result = await session.execute(stmt)
        delta = result.scalar_one_or_none()
        if delta is None:
            return None

        # Fetch both versions
        v_stmt = select(ThesisVersion).where(
            ThesisVersion.id.in_([delta.from_version_id, delta.to_version_id])
        )
        v_result = await session.execute(v_stmt)
        versions = {v.id: v for v in v_result.scalars().all()}

        fv = versions.get(delta.from_version_id)
        tv = versions.get(delta.to_version_id)
        if fv is None or tv is None:
            return None

        def _full_version(v: Any) -> Dict[str, Any]:
            return {
                "id": v.id,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "question": v.question or "",
                "directional_stance": v.directional_stance or "",
                "confidence_score": v.confidence_score or 0.0,
                "bull_thesis": v.bull_thesis or "",
                "bear_thesis": v.bear_thesis or "",
                "verdict_rationale": v.verdict_rationale or "",
                "direct_answer": v.direct_answer or "",
                "why_not": v.why_not or "",
                "conclusion": v.conclusion or "",
                "threshold_zones": json.loads(v.threshold_zones or "{}"),
            }

        return {
            "delta_id": delta.id,
            "ticker": ticker,
            "magnitude": delta.magnitude,
            "stance_changed": delta.stance_changed,
            "conviction_delta": delta.conviction_delta,
            "bull_thesis_similarity": delta.bull_thesis_similarity,
            "bear_thesis_similarity": delta.bear_thesis_similarity,
            "changed_fields": json.loads(delta.changed_fields or "[]"),
            "from_version": _full_version(fv),
            "to_version": _full_version(tv),
            "inline_diff": _build_inline_diff(fv, tv),
        }

    except Exception as exc:
        logger.warning("[evolution_repo] get_delta_full failed for %s/%s: %r", ticker, delta_id, exc)
        return None


# ---------------------------------------------------------------------------
# GET /api/ticker/{ticker}/latest
# ---------------------------------------------------------------------------

async def get_latest_change_card(
    session,
    ticker: str,
) -> Optional[Dict[str, Any]]:
    """Return LatestChangeCard payload for one ticker."""
    if session is None:
        return None

    try:
        from sqlalchemy import select
        from ..models import ThesisVersion, ThesisDelta

        # Most recent version
        v_stmt = (
            select(ThesisVersion)
            .where(ThesisVersion.ticker == ticker)
            .order_by(ThesisVersion.created_at.desc())
            .limit(1)
        )
        v_result = await session.execute(v_stmt)
        version = v_result.scalar_one_or_none()
        if version is None:
            return None

        # Most recent delta (may not exist if only one version)
        d_stmt = (
            select(ThesisDelta)
            .where(ThesisDelta.ticker == ticker)
            .where(ThesisDelta.to_version_id == version.id)
            .order_by(ThesisDelta.created_at.desc())
            .limit(1)
        )
        d_result = await session.execute(d_stmt)
        delta = d_result.scalar_one_or_none()

        last_delta = None
        if delta is not None:
            # Compute days_since_prior
            prior_v_stmt = (
                select(ThesisVersion)
                .where(ThesisVersion.id == delta.from_version_id)
            )
            prior_result = await session.execute(prior_v_stmt)
            prior = prior_result.scalar_one_or_none()
            days_since = None
            if prior and prior.created_at and version.created_at:
                diff = version.created_at - prior.created_at
                days_since = diff.days

            last_delta = {
                "magnitude": delta.magnitude,
                "stance_changed": delta.stance_changed,
                "conviction_delta": delta.conviction_delta,
                "days_since_prior": days_since,
                "changed_fields": json.loads(delta.changed_fields or "[]"),
            }

        return {
            "ticker": ticker,
            "company_name": version.company_name or ticker,
            "version_id": version.id,
            "created_at": version.created_at.isoformat() if version.created_at else None,
            "question": version.question or "",
            "directional_stance": version.directional_stance or "",
            "confidence_score": version.confidence_score or 0.0,
            "direct_answer": version.direct_answer or "",
            "verdict_rationale": version.verdict_rationale or "",
            "last_delta": last_delta,
        }

    except Exception as exc:
        logger.warning("[evolution_repo] get_latest_change_card failed for %s: %r", ticker, exc)
        return None


# ---------------------------------------------------------------------------
# GET /api/material-changes
# ---------------------------------------------------------------------------

async def get_material_changes_feed(
    session,
    limit: int = 20,
    since: Optional[datetime] = None,
    tickers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return paginated MaterialChangeFeedResponse payload.

    Applies debounce_visible filter so only the dominant daily delta per
    ticker is surfaced.  Uses cursor-based pagination via ``since`` parameter.
    """
    if session is None:
        return {"feed": [], "next_cursor": None, "has_more": False}

    try:
        from sqlalchemy import select
        from ..models import ThesisDelta, ThesisVersion, TickerMemory

        stmt = (
            select(ThesisDelta)
            .where(ThesisDelta.magnitude == "material")
            .where(ThesisDelta.debounce_visible == True)  # noqa: E712
            .order_by(ThesisDelta.created_at.desc())
            .limit(limit + 1)  # fetch one extra to determine has_more
        )
        if since is not None:
            stmt = stmt.where(ThesisDelta.created_at < since)
        if tickers:
            stmt = stmt.where(ThesisDelta.ticker.in_(tickers))

        result = await session.execute(stmt)
        all_deltas = list(result.scalars().all())

        has_more = len(all_deltas) > limit
        deltas = all_deltas[:limit]
        next_cursor = None
        if has_more and deltas:
            last_ts = deltas[-1].created_at
            next_cursor = last_ts.isoformat() if last_ts else None

        # Bulk-fetch to_versions for question text + stances
        to_ids = [d.to_version_id for d in deltas]
        from_ids = [d.from_version_id for d in deltas]
        all_ids = list(set(to_ids + from_ids))
        version_map: Dict[str, Any] = {}
        if all_ids:
            v_stmt = select(ThesisVersion).where(ThesisVersion.id.in_(all_ids))
            v_result = await session.execute(v_stmt)
            for v in v_result.scalars().all():
                version_map[v.id] = v

        # Bulk-fetch ticker memory for company names
        ticker_set = list({d.ticker for d in deltas})
        mem_map: Dict[str, Any] = {}
        if ticker_set:
            m_stmt = select(TickerMemory).where(TickerMemory.ticker.in_(ticker_set))
            m_result = await session.execute(m_stmt)
            for m in m_result.scalars().all():
                mem_map[m.ticker] = m

        feed_items = []
        for d in deltas:
            tv = version_map.get(d.to_version_id)
            fv = version_map.get(d.from_version_id)
            mem = mem_map.get(d.ticker)

            from_stance = (fv.directional_stance or "") if fv else ""
            to_stance = (tv.directional_stance or "") if tv else ""
            company_name = (mem.company_name if mem else None) or d.ticker
            dominant_concern = (mem.dominant_concern if mem else "") or ""
            question = (tv.question or "") if tv else ""

            changed_fields = json.loads(d.changed_fields or "[]")
            headline = _generate_headline(
                stance_changed=d.stance_changed,
                from_stance=from_stance,
                to_stance=to_stance,
                conviction_delta=d.conviction_delta,
                changed_fields=changed_fields,
                dominant_concern=dominant_concern,
            )

            # Top 2 concern tags for this ticker (live lookup — low row count)
            from .concern_repo import get_tags_for_ticker
            tag_counts = await get_tags_for_ticker(session, d.ticker)
            top_tags = sorted(tag_counts, key=lambda k: tag_counts[k], reverse=True)[:2]

            feed_items.append({
                "ticker": d.ticker,
                "company_name": company_name,
                "delta_id": d.id,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "magnitude": d.magnitude,
                "stance_changed": d.stance_changed,
                "from_stance": from_stance,
                "to_stance": to_stance,
                "conviction_delta": d.conviction_delta,
                "question": question,
                "headline": headline,
                "concern_tags": top_tags,
            })

        return {
            "feed": feed_items,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    except Exception as exc:
        logger.warning("[evolution_repo] get_material_changes_feed failed: %r", exc)
        return {"feed": [], "next_cursor": None, "has_more": False}
