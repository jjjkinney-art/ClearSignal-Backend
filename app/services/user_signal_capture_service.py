"""
User Signal Capture Service — Phase 15 · Slice 3.

Normalizes and appends raw behavioral events into user_signal_event.
This is the ONLY write path for user_signal_event rows; all other Phase 15
services read the event stream but never write to it.

Core rule
---------
Capture behavior. Do NOT infer preferences here.
Nothing in this module writes to learned_preference, preference_evidence,
or relevance_adjustment_log. No truth table is touched (SP-7a).

Flag gate
---------
All seven capture functions are gated on learning_capture_enabled (default
False). When the flag is False the function returns None immediately —
no event is stored, no side effect occurs.

Event shape (common to all capture functions)
----------------------------------------------
  user_id                  — mandatory; anonymous behavior is not captured
  signal_type              — typed event name (see SP-7 vocabulary)
  polarity                 — positive | negative | neutral
  entity_type              — company | sector | theme | signal_type | horizon
  entity_key               — ticker / sector_id / theme_key / signal_type_name
  source_surface           — which UI surface emitted the event
  surface_was_personalized — was the surface already personalized?
  pre_personalization_rank — item's rank before any personalization
  interaction_weight       — normalized magnitude [0, 1]
  occurred_at              — event time (defaults to now)

Anti-feedback-loop fields
--------------------------
surface_was_personalized and pre_personalization_rank are mandatory for the
learning pass to distinguish "the user chose this" from "we put this on top"
(risk R2, spec §4.1 principle #10). Callers should always supply them; the
functions accept None/False as safe defaults but those defaults carry
less signal.

Safety invariants (SP-7)
-------------------------
  SP-7a: never writes to forecast_vector, similarity_edge, scenario_snapshot,
         decision_priority, ticker_memory, or any upstream truth table.
  SP-7b: never imports a write function from forecast_repo, decision_repo,
         scenario_repo, similarity_repo, or any dossier/memory write module.
  SP-7f: no buy/sell/hold/target_price/position_size/recommendation/trade/
         execution language in any string constant.
  Null-session contract: returns None when session is None; never raises.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _capture_enabled(override: Optional[bool] = None) -> bool:
    """Return True when learning_capture_enabled flag is set.

    The optional override is for testing only — passes True/False directly
    without reading settings, mirroring the pattern used in Phase 14.
    """
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "learning_capture_enabled", False))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Internal dispatch helper
# ---------------------------------------------------------------------------

async def _capture_event(
    session,
    *,
    user_id: str,
    signal_type: str,
    polarity: str = "neutral",
    entity_type: str = "",
    entity_key: str = "",
    source_surface: str = "",
    surface_was_personalized: bool = False,
    pre_personalization_rank: Optional[int] = None,
    interaction_weight: float = 1.0,
    occurred_at: Optional[datetime] = None,
    run_override: Optional[bool] = None,
) -> Optional[object]:
    """Insert one UserSignalEvent row via the repository.

    Returns the ORM row on success, None when disabled, session is None,
    or an error occurs. Never raises.
    """
    if not _capture_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        from app.db.repositories.user_learning_repo import add_user_signal_event

        return await add_user_signal_event(
            session,
            user_id                  = user_id,
            signal_type              = signal_type,
            polarity                 = polarity,
            entity_type              = entity_type,
            entity_key               = entity_key,
            source_surface           = source_surface,
            surface_was_personalized = surface_was_personalized,
            pre_personalization_rank = pre_personalization_rank,
            interaction_weight       = interaction_weight,
            occurred_at              = occurred_at or _now(),
        )
    except Exception as exc:
        logger.debug("[user_signal_capture] _capture_event(%s) failed: %r", signal_type, exc)
        return None


# ---------------------------------------------------------------------------
# Public capture functions
# ---------------------------------------------------------------------------

async def capture_search_signal(
    session,
    *,
    user_id: str,
    signal_type: str,
    entity_type: str = "company",
    entity_key: str = "",
    source_surface: str = "search",
    surface_was_personalized: bool = False,
    pre_personalization_rank: Optional[int] = None,
    interaction_weight: float = 1.0,
    occurred_at: Optional[datetime] = None,
    run_override: Optional[bool] = None,
) -> Optional[object]:
    """Capture a search behavioral event.

    signal_type examples: search_query | search_click
    Polarity is derived from signal_type:
      search_click   → positive (active selection)
      search_query   → neutral  (ambiguous intent)
    """
    polarity = "positive" if signal_type == "search_click" else "neutral"
    return await _capture_event(
        session,
        user_id                  = user_id,
        signal_type              = signal_type,
        polarity                 = polarity,
        entity_type              = entity_type,
        entity_key               = entity_key,
        source_surface           = source_surface,
        surface_was_personalized = surface_was_personalized,
        pre_personalization_rank = pre_personalization_rank,
        interaction_weight       = interaction_weight,
        occurred_at              = occurred_at,
        run_override             = run_override,
    )


async def capture_analysis_signal(
    session,
    *,
    user_id: str,
    signal_type: str,
    entity_type: str = "company",
    entity_key: str = "",
    source_surface: str = "analysis",
    surface_was_personalized: bool = False,
    pre_personalization_rank: Optional[int] = None,
    interaction_weight: float = 1.0,
    occurred_at: Optional[datetime] = None,
    run_override: Optional[bool] = None,
) -> Optional[object]:
    """Capture an analysis-history behavioral event.

    signal_type examples: analysis_open | section_expand
    Polarity: both are positive (the user actively engaged with analysis content).
    """
    return await _capture_event(
        session,
        user_id                  = user_id,
        signal_type              = signal_type,
        polarity                 = "positive",
        entity_type              = entity_type,
        entity_key               = entity_key,
        source_surface           = source_surface,
        surface_was_personalized = surface_was_personalized,
        pre_personalization_rank = pre_personalization_rank,
        interaction_weight       = interaction_weight,
        occurred_at              = occurred_at,
        run_override             = run_override,
    )


async def capture_forecast_interaction(
    session,
    *,
    user_id: str,
    signal_type: str,
    entity_type: str = "company",
    entity_key: str = "",
    source_surface: str = "forecast",
    surface_was_personalized: bool = False,
    pre_personalization_rank: Optional[int] = None,
    interaction_weight: float = 1.0,
    occurred_at: Optional[datetime] = None,
    run_override: Optional[bool] = None,
) -> Optional[object]:
    """Capture a forecast interaction event.

    signal_type examples: forecast_view | horizon_toggle
    Polarity: positive (all forecast interactions indicate interest).

    This function ONLY captures behavior; it never reads or writes forecast_vector.
    SP-7b: no forecast_repo write function is imported here.
    """
    return await _capture_event(
        session,
        user_id                  = user_id,
        signal_type              = signal_type,
        polarity                 = "positive",
        entity_type              = entity_type,
        entity_key               = entity_key,
        source_surface           = source_surface,
        surface_was_personalized = surface_was_personalized,
        pre_personalization_rank = pre_personalization_rank,
        interaction_weight       = interaction_weight,
        occurred_at              = occurred_at,
        run_override             = run_override,
    )


async def capture_scenario_interaction(
    session,
    *,
    user_id: str,
    signal_type: str,
    entity_type: str = "company",
    entity_key: str = "",
    source_surface: str = "scenario",
    surface_was_personalized: bool = False,
    pre_personalization_rank: Optional[int] = None,
    interaction_weight: float = 1.0,
    occurred_at: Optional[datetime] = None,
    run_override: Optional[bool] = None,
) -> Optional[object]:
    """Capture a scenario interaction event.

    signal_type examples: scenario_expand | scenario_dismiss
    Polarity:
      scenario_expand  → positive  (user opened and engaged)
      scenario_dismiss → negative  (user dismissed — requires repetition to harden,
                                    per spec §5.4 and risk R4)
      all others       → neutral

    This function ONLY captures behavior; it never reads or writes scenario_snapshot.
    SP-7b: no scenario_repo write function is imported here.
    """
    if signal_type == "scenario_expand":
        polarity = "positive"
    elif signal_type == "scenario_dismiss":
        polarity = "negative"
    else:
        polarity = "neutral"
    return await _capture_event(
        session,
        user_id                  = user_id,
        signal_type              = signal_type,
        polarity                 = polarity,
        entity_type              = entity_type,
        entity_key               = entity_key,
        source_surface           = source_surface,
        surface_was_personalized = surface_was_personalized,
        pre_personalization_rank = pre_personalization_rank,
        interaction_weight       = interaction_weight,
        occurred_at              = occurred_at,
        run_override             = run_override,
    )


async def capture_watchlist_interaction(
    session,
    *,
    user_id: str,
    signal_type: str,
    entity_type: str = "company",
    entity_key: str = "",
    source_surface: str = "watchlist",
    surface_was_personalized: bool = False,
    pre_personalization_rank: Optional[int] = None,
    interaction_weight: float = 1.0,
    occurred_at: Optional[datetime] = None,
    run_override: Optional[bool] = None,
) -> Optional[object]:
    """Capture a watchlist behavioral event.

    signal_type examples: watchlist_add | watchlist_remove
    Polarity:
      watchlist_add    → positive  (explicit interest signal)
      watchlist_remove → negative  (explicit disinterest signal)
      all others       → neutral
    """
    if signal_type == "watchlist_add":
        polarity = "positive"
    elif signal_type == "watchlist_remove":
        polarity = "negative"
    else:
        polarity = "neutral"
    return await _capture_event(
        session,
        user_id                  = user_id,
        signal_type              = signal_type,
        polarity                 = polarity,
        entity_type              = entity_type,
        entity_key               = entity_key,
        source_surface           = source_surface,
        surface_was_personalized = surface_was_personalized,
        pre_personalization_rank = pre_personalization_rank,
        interaction_weight       = interaction_weight,
        occurred_at              = occurred_at,
        run_override             = run_override,
    )


async def capture_portfolio_interaction(
    session,
    *,
    user_id: str,
    signal_type: str = "portfolio_view",
    entity_type: str = "company",
    entity_key: str = "",
    source_surface: str = "portfolio",
    surface_was_personalized: bool = False,
    pre_personalization_rank: Optional[int] = None,
    interaction_weight: float = 1.0,
    occurred_at: Optional[datetime] = None,
    run_override: Optional[bool] = None,
) -> Optional[object]:
    """Capture a portfolio behavioral event.

    signal_type examples: portfolio_view
    Polarity: positive (portfolio drill-downs indicate holding attention).

    This function ONLY captures behavioral attention on holdings; it never
    reads portfolio positions for advice or recommendation purposes (SP-7f).
    Holdings inform relevance only — never trade sizing or positioning.
    """
    return await _capture_event(
        session,
        user_id                  = user_id,
        signal_type              = signal_type,
        polarity                 = "positive",
        entity_type              = entity_type,
        entity_key               = entity_key,
        source_surface           = source_surface,
        surface_was_personalized = surface_was_personalized,
        pre_personalization_rank = pre_personalization_rank,
        interaction_weight       = interaction_weight,
        occurred_at              = occurred_at,
        run_override             = run_override,
    )


async def capture_alert_interaction(
    session,
    *,
    user_id: str,
    signal_type: str,
    entity_type: str = "signal_type",
    entity_key: str = "",
    source_surface: str = "alert",
    surface_was_personalized: bool = False,
    pre_personalization_rank: Optional[int] = None,
    interaction_weight: float = 1.0,
    occurred_at: Optional[datetime] = None,
    run_override: Optional[bool] = None,
) -> Optional[object]:
    """Capture an alert interaction event.

    signal_type examples: alert_open | alert_act | alert_dismiss | alert_mute
    Polarity:
      alert_open | alert_act      → positive
      alert_dismiss | alert_mute  → negative
      all others                  → neutral

    entity_type defaults to 'signal_type' (the alert's signal category) because
    alert interactions most strongly inform preferred_signal_type and
    ignored_signal_type dimensions. Callers may override to 'company' or 'sector'
    when entity_key is a ticker or sector id.
    """
    positive_types = frozenset({"alert_open", "alert_act"})
    negative_types = frozenset({"alert_dismiss", "alert_mute"})
    if signal_type in positive_types:
        polarity = "positive"
    elif signal_type in negative_types:
        polarity = "negative"
    else:
        polarity = "neutral"
    return await _capture_event(
        session,
        user_id                  = user_id,
        signal_type              = signal_type,
        polarity                 = polarity,
        entity_type              = entity_type,
        entity_key               = entity_key,
        source_surface           = source_surface,
        surface_was_personalized = surface_was_personalized,
        pre_personalization_rank = pre_personalization_rank,
        interaction_weight       = interaction_weight,
        occurred_at              = occurred_at,
        run_override             = run_override,
    )
