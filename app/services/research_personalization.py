"""Explicit account-owned Intelligence Mode personalization.

Only structured settings selected by the authenticated user are stored here.
No preference is inferred from conversations, analyses, holdings, or legacy
memory, and this service does not prepare model prompt context.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..db.models import ResearchPersonalizationProfile


RESPONSE_DEPTHS = {"concise", "balanced", "deep"}
TIME_HORIZONS = {"near_term", "mixed", "multi_year"}
ANALYSIS_EMPHASES = {"downside_first", "balanced", "opportunity_first"}
EVIDENCE_STYLES = {"primary_sources", "balanced_sources"}
PROFILE_ORIGIN = "explicit_user_setting"

DEFAULT_PROFILE = {
    "enabled": False,
    "response_depth": "balanced",
    "time_horizon": "mixed",
    "analysis_emphasis": "balanced",
    "evidence_style": "primary_sources",
}


def _owner(user_id: str) -> str:
    owner = (user_id or "").strip()
    if not owner:
        raise ValueError("An authenticated owner is required")
    return owner


def _choice(value: str, allowed: set[str], field: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Unsupported {field}")
    return normalized


def _serialize(row: ResearchPersonalizationProfile | None) -> dict:
    if row is None:
        return {
            **DEFAULT_PROFILE,
            "persisted": False,
            "origin": None,
            "created_at": None,
            "updated_at": None,
        }
    return {
        "enabled": bool(row.enabled),
        "response_depth": row.response_depth,
        "time_horizon": row.time_horizon,
        "analysis_emphasis": row.analysis_emphasis,
        "evidence_style": row.evidence_style,
        "persisted": True,
        "origin": row.origin,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def get_profile(session, *, user_id: str) -> dict:
    owner = _owner(user_id)
    row = (await session.execute(
        select(ResearchPersonalizationProfile).where(
            ResearchPersonalizationProfile.user_id == owner
        )
    )).scalar_one_or_none()
    return _serialize(row)


async def upsert_profile(
    session,
    *,
    user_id: str,
    enabled: bool,
    response_depth: str,
    time_horizon: str,
    analysis_emphasis: str,
    evidence_style: str,
) -> dict:
    owner = _owner(user_id)
    values = {
        "enabled": bool(enabled),
        "response_depth": _choice(response_depth, RESPONSE_DEPTHS, "response_depth"),
        "time_horizon": _choice(time_horizon, TIME_HORIZONS, "time_horizon"),
        "analysis_emphasis": _choice(
            analysis_emphasis, ANALYSIS_EMPHASES, "analysis_emphasis"
        ),
        "evidence_style": _choice(evidence_style, EVIDENCE_STYLES, "evidence_style"),
    }
    row = (await session.execute(
        select(ResearchPersonalizationProfile).where(
            ResearchPersonalizationProfile.user_id == owner
        ).with_for_update()
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = ResearchPersonalizationProfile(
            user_id=owner,
            origin=PROFILE_ORIGIN,
            **values,
        )
        session.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
        row.origin = PROFILE_ORIGIN
        row.updated_at = now
    await session.flush()
    return _serialize(row)


async def delete_profile(session, *, user_id: str) -> bool:
    """Hard-delete explicit preferences so defaults resume immediately."""
    owner = _owner(user_id)
    row = (await session.execute(
        select(ResearchPersonalizationProfile).where(
            ResearchPersonalizationProfile.user_id == owner
        ).with_for_update()
    )).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True
