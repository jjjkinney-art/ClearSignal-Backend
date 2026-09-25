"""Account-owned thesis snapshots. No ticker-wide reads or shared memory writes."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from ..db.models import ThesisVersion


def _owner(user_id: str) -> str:
    if not user_id or not user_id.strip():
        raise ValueError("An authenticated owner is required")
    return user_id


def _present(row: ThesisVersion) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "company_name": row.company_name,
        "question": row.question,
        "direct_answer": row.direct_answer,
        "directional_stance": row.directional_stance,
        "confidence_score": row.confidence_score,
        "created_at": row.created_at.isoformat(),
    }


async def save_thesis(session, *, user_id: str, question: str, company_name: str,
                      session_id: str, result) -> bool:
    """Save a successful company thesis only; caller owns the transaction."""
    _owner(user_id)
    from ..db.persistence import _extract_thesis, _extract_ticker

    thesis = _extract_thesis(result)
    if not thesis:
        return False
    ticker = _extract_ticker(result, company_name)
    if not ticker or ticker == "UNKNOWN":
        return False
    row = ThesisVersion(
        ticker=ticker,
        company_name=(company_name or getattr(result, "company", "") or ticker)[:200],
        session_id=session_id,
        question=question,
        user_id=user_id,
        directional_stance=str(thesis.get("directional_stance") or ""),
        confidence_score=float(thesis.get("confidence_score") or 0),
        bull_thesis=str(thesis.get("bull_thesis") or ""),
        bear_thesis=str(thesis.get("bear_thesis") or ""),
        verdict_rationale=str(thesis.get("verdict_rationale") or ""),
        direct_answer=str(thesis.get("direct_answer") or ""),
        why_not=str(thesis.get("why_not") or ""),
        conclusion=str(thesis.get("conclusion") or ""),
    )
    session.add(row)
    await session.flush()
    return True


async def list_theses(session, *, user_id: str, limit: int = 30, ticker: Optional[str] = None) -> list[dict]:
    _owner(user_id)
    stmt = select(ThesisVersion).where(ThesisVersion.user_id == user_id)
    if ticker:
        stmt = stmt.where(ThesisVersion.ticker == ticker.upper())
    stmt = stmt.order_by(ThesisVersion.created_at.desc(), ThesisVersion.id.desc()).limit(limit)
    return [_present(row) for row in (await session.execute(stmt)).scalars()]


async def get_thesis(session, *, user_id: str, record_id: str) -> Optional[dict]:
    _owner(user_id)
    row = (await session.execute(select(ThesisVersion).where(
        ThesisVersion.user_id == user_id, ThesisVersion.id == record_id,
    ))).scalar_one_or_none()
    return _present(row) if row else None
