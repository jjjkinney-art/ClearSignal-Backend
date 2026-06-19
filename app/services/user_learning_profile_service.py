"""
User Learning Profile Service — Phase 15 · Slice 7.

Builds read-only user learning profiles from learned preferences.

Core rule
---------
Profile summarizes learned relevance.  It does not alter ranking yet.

This module is strictly read-only.  It reads from:
  - learned_preference  (via user_learning_repo)
  - preference_evidence (via user_learning_repo)
  - user_signal_event   (via user_learning_repo)

It never writes to any table, never calls upsert/insert/delete, and never
imports any write function from any repository.

Flag gate
---------
All public functions are gated on learning_inference_enabled (default False).
When the flag is off every function returns an empty profile dict or [].

Null-session contract
---------------------
Every public function returns an empty result when session=None — never raises.

Profile structure (get_user_interest_profile)
----------------------------------------------
{
  "user_id":                str,
  "companies_of_interest":  [PreferenceEntry, ...],
  "sectors_of_interest":    [PreferenceEntry, ...],
  "recurring_themes":       [PreferenceEntry, ...],
  "preferred_horizons":     [PreferenceEntry, ...],
  "preferred_signal_types": [PreferenceEntry, ...],
  "ignored_signal_types":   [PreferenceEntry, ...],
  "portfolio_sensitivities":[PreferenceEntry, ...],
  "confidence_summary":     ConfidenceSummary,
  "evidence_summary":       EvidenceSummary,
  "profile_schema":         int,       # 1
  "generated_at":           str,       # ISO-8601 UTC
}

Each PreferenceEntry is:
{
  "entity_key":            str,
  "affinity":              float,
  "confidence":            float,
  "signal_strength_label": str,   # "strong" | "moderate" | "tentative"
  "evidence_count":        int,
  "status":                str,
  "dimension":             str,
}

ConfidenceSummary:
{
  "strong_count":    int,
  "moderate_count":  int,
  "tentative_count": int,
  "total_count":     int,
  "mean_confidence": float,
}

EvidenceSummary:
{
  "total_evidence_count":    int,
  "dimensions_with_evidence": int,
}

SP-7 invariants
---------------
  SP-7a / SP-7b: no writes, no truth-table imports.
  SP-7f: no banned advisory language in any generated string.
  SP-7h: no relevance adjustments, no ranking changes.
  This service is purely observational — it describes what was learned.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROFILE_SCHEMA: int = 1

# Minimum signal_strength_label required to include an entry in high-priority views.
# "weak" preferences (tentative) are included in the full profile but not priorities.
_PRIORITY_MIN_STRENGTH: str = "moderate"
_STRENGTH_RANK: Dict[str, int] = {"strong": 2, "moderate": 1, "tentative": 0}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _inference_enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "learning_inference_enabled", False))
    except Exception:
        return False


def _preference_entry(pref: Any) -> Dict[str, Any]:
    """Convert a LearnedPreference ORM row (or dict) to a plain PreferenceEntry dict."""
    def g(key: str, default: Any = "") -> Any:
        if isinstance(pref, dict):
            return pref.get(key, default)
        return getattr(pref, key, default)

    return {
        "entity_key":            g("entity_key", ""),
        "affinity":              float(g("affinity", 0.0) or 0.0),
        "confidence":            float(g("confidence", 0.0) or 0.0),
        "signal_strength_label": g("signal_strength_label", "tentative"),
        "evidence_count":        int(g("evidence_count", 0) or 0),
        "status":                g("status", "unresolved"),
        "dimension":             g("dimension", ""),
    }


def _empty_confidence_summary() -> Dict[str, Any]:
    return {
        "strong_count":    0,
        "moderate_count":  0,
        "tentative_count": 0,
        "total_count":     0,
        "mean_confidence": 0.0,
    }


def _build_confidence_summary(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    strong    = sum(1 for e in entries if e.get("signal_strength_label") == "strong")
    moderate  = sum(1 for e in entries if e.get("signal_strength_label") == "moderate")
    tentative = sum(1 for e in entries if e.get("signal_strength_label") == "tentative")
    total     = len(entries)
    mean_conf = (
        sum(e.get("confidence", 0.0) for e in entries) / total
        if total > 0 else 0.0
    )
    return {
        "strong_count":    strong,
        "moderate_count":  moderate,
        "tentative_count": tentative,
        "total_count":     total,
        "mean_confidence": round(mean_conf, 4),
    }


def _build_evidence_summary(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_ev = sum(e.get("evidence_count", 0) for e in entries)
    dims_with = sum(1 for e in entries if e.get("evidence_count", 0) > 0)
    return {
        "total_evidence_count":     total_ev,
        "dimensions_with_evidence": dims_with,
    }


def _sort_by_confidence(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort entries by confidence descending, then entity_key for determinism."""
    return sorted(
        entries,
        key=lambda e: (-e.get("confidence", 0.0), e.get("entity_key", "")),
    )


def _filter_active(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Exclude falsified preferences from the profile output."""
    return [e for e in entries if e.get("status") != "falsified"]


async def _fetch_preferences_by_dimension(
    session,
    *,
    user_id: str,
    dimension: str,
) -> List[Dict[str, Any]]:
    """Fetch LearnedPreference rows for one dimension, mapped to entry dicts."""
    try:
        from app.db.repositories.user_learning_repo import list_learned_preferences

        rows = await list_learned_preferences(
            session, user_id=user_id, dimension=dimension,
        )
        entries = [_preference_entry(r) for r in rows]
        return _filter_active(entries)
    except Exception as exc:
        logger.debug("[profile] _fetch_preferences_by_dimension(%s) failed: %r",
                     dimension, exc)
        return []


async def _fetch_all_preferences(
    session,
    *,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Fetch all LearnedPreference rows for the user, mapped to entry dicts."""
    try:
        from app.db.repositories.user_learning_repo import list_learned_preferences

        rows = await list_learned_preferences(session, user_id=user_id)
        entries = [_preference_entry(r) for r in rows]
        return _filter_active(entries)
    except Exception as exc:
        logger.debug("[profile] _fetch_all_preferences failed: %r", exc)
        return []


async def _count_evidence_for_user(session, *, user_id: str) -> int:
    """Total preference_evidence rows across all preferences for user_id."""
    try:
        from app.db.repositories.user_learning_repo import (
            list_learned_preferences,
            count_preference_evidence,
        )

        prefs = await list_learned_preferences(session, user_id=user_id)
        total = 0
        for p in prefs:
            pref_id = (
                p.get("id") if isinstance(p, dict) else getattr(p, "id", None)
            )
            if pref_id:
                total += await count_preference_evidence(session, preference_id=pref_id)
        return total
    except Exception as exc:
        logger.debug("[profile] _count_evidence_for_user failed: %r", exc)
        return 0


def _empty_profile(user_id: str) -> Dict[str, Any]:
    return {
        "user_id":                user_id,
        "companies_of_interest":  [],
        "sectors_of_interest":    [],
        "recurring_themes":       [],
        "preferred_horizons":     [],
        "preferred_signal_types": [],
        "ignored_signal_types":   [],
        "portfolio_sensitivities": [],
        "confidence_summary":     _empty_confidence_summary(),
        "evidence_summary":       {"total_evidence_count": 0, "dimensions_with_evidence": 0},
        "profile_schema":         _PROFILE_SCHEMA,
        "generated_at":           _now_iso(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_user_interest_profile(
    session,
    *,
    user_id: str,
    include_tentative: bool = True,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Build a full read-only interest profile for user_id.

    Reads all LearnedPreference rows grouped by dimension.  Excludes rows with
    status='falsified'.  When include_tentative=False, tentative-strength entries
    are omitted from per-dimension lists (they still count toward the
    confidence_summary and evidence_summary totals).

    Returns an empty profile when the flag is off, session is None, or no
    preferences exist.  Never raises.
    """
    if not _inference_enabled(run_override):
        return _empty_profile(user_id)
    if session is None:
        return _empty_profile(user_id)
    try:
        # Fetch per dimension for clean grouping
        companies  = _sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="company_interest")
        )
        sectors    = _sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="sector_interest")
        )
        themes     = _sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="theme_interest")
        )
        horizons   = _sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="preferred_horizon")
        )
        sig_types  = _sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="preferred_signal_type")
        )
        ignored    = _sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="ignored_signal_type")
        )
        portfolio  = _sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="portfolio_sensitivity")
        )

        all_entries = companies + sectors + themes + horizons + sig_types + ignored + portfolio
        conf_summary = _build_confidence_summary(all_entries)
        ev_summary   = _build_evidence_summary(all_entries)

        def _maybe_filter(entries: List[Dict]) -> List[Dict]:
            if include_tentative:
                return entries
            return [e for e in entries if e.get("signal_strength_label") != "tentative"]

        return {
            "user_id":                user_id,
            "companies_of_interest":  _maybe_filter(companies),
            "sectors_of_interest":    _maybe_filter(sectors),
            "recurring_themes":       _maybe_filter(themes),
            "preferred_horizons":     _maybe_filter(horizons),
            "preferred_signal_types": _maybe_filter(sig_types),
            "ignored_signal_types":   _maybe_filter(ignored),
            "portfolio_sensitivities": _maybe_filter(portfolio),
            "confidence_summary":     conf_summary,
            "evidence_summary":       ev_summary,
            "profile_schema":         _PROFILE_SCHEMA,
            "generated_at":           _now_iso(),
        }
    except Exception as exc:
        logger.debug("[profile] get_user_interest_profile failed: %r", exc)
        return _empty_profile(user_id)


async def get_learned_priorities(
    session,
    *,
    user_id: str,
    min_strength: str = _PRIORITY_MIN_STRENGTH,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return high-priority learned interests filtered to strong/moderate strength.

    Excludes tentative-strength entries by default (min_strength='moderate').
    Callers may pass min_strength='strong' to restrict to strong-only or
    min_strength='tentative' to include all active entries.

    Returns:
    {
      "user_id":                  str,
      "high_priority_companies":  [PreferenceEntry, ...],   # company_interest
      "high_priority_sectors":    [PreferenceEntry, ...],   # sector_interest
      "high_priority_themes":     [PreferenceEntry, ...],   # theme_interest
      "portfolio_attention":      [PreferenceEntry, ...],   # portfolio_sensitivity
      "attention_signal_types":   [PreferenceEntry, ...],   # preferred_signal_type
      "min_strength_applied":     str,
      "generated_at":             str,
    }
    """
    if not _inference_enabled(run_override):
        return {
            "user_id": user_id,
            "high_priority_companies":  [],
            "high_priority_sectors":    [],
            "high_priority_themes":     [],
            "portfolio_attention":      [],
            "attention_signal_types":   [],
            "min_strength_applied":     min_strength,
            "generated_at":             _now_iso(),
        }
    if session is None:
        return {
            "user_id": user_id,
            "high_priority_companies":  [],
            "high_priority_sectors":    [],
            "high_priority_themes":     [],
            "portfolio_attention":      [],
            "attention_signal_types":   [],
            "min_strength_applied":     min_strength,
            "generated_at":             _now_iso(),
        }
    try:
        min_rank = _STRENGTH_RANK.get(min_strength, 0)

        def _qualify(entries: List[Dict]) -> List[Dict]:
            return [
                e for e in entries
                if _STRENGTH_RANK.get(e.get("signal_strength_label", "tentative"), 0) >= min_rank
            ]

        companies = _qualify(_sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="company_interest")
        ))
        sectors = _qualify(_sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="sector_interest")
        ))
        themes = _qualify(_sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="theme_interest")
        ))
        portfolio = _qualify(_sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="portfolio_sensitivity")
        ))
        sig_types = _qualify(_sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="preferred_signal_type")
        ))

        return {
            "user_id":                 user_id,
            "high_priority_companies": companies,
            "high_priority_sectors":   sectors,
            "high_priority_themes":    themes,
            "portfolio_attention":     portfolio,
            "attention_signal_types":  sig_types,
            "min_strength_applied":    min_strength,
            "generated_at":            _now_iso(),
        }
    except Exception as exc:
        logger.debug("[profile] get_learned_priorities failed: %r", exc)
        return {
            "user_id": user_id,
            "high_priority_companies": [],
            "high_priority_sectors":   [],
            "high_priority_themes":    [],
            "portfolio_attention":     [],
            "attention_signal_types":  [],
            "min_strength_applied":    min_strength,
            "generated_at":            _now_iso(),
        }


async def get_attention_preferences(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return the user's attention-shaping preferences: horizons, signal types, ignored.

    These three dimensions govern presentation and feed filtering preferences
    (which time horizons and signal categories the user favours or deprioritises).
    They are distinct from entity interests (company/sector/theme) which represent
    named-entity attention.

    Returns:
    {
      "user_id":                str,
      "preferred_horizons":     [PreferenceEntry, ...],
      "preferred_signal_types": [PreferenceEntry, ...],
      "ignored_signal_types":   [PreferenceEntry, ...],
      "generated_at":           str,
    }
    """
    if not _inference_enabled(run_override):
        return {
            "user_id":                user_id,
            "preferred_horizons":     [],
            "preferred_signal_types": [],
            "ignored_signal_types":   [],
            "generated_at":           _now_iso(),
        }
    if session is None:
        return {
            "user_id":                user_id,
            "preferred_horizons":     [],
            "preferred_signal_types": [],
            "ignored_signal_types":   [],
            "generated_at":           _now_iso(),
        }
    try:
        horizons  = _sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="preferred_horizon")
        )
        sig_types = _sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="preferred_signal_type")
        )
        ignored   = _sort_by_confidence(
            await _fetch_preferences_by_dimension(session, user_id=user_id, dimension="ignored_signal_type")
        )
        return {
            "user_id":                user_id,
            "preferred_horizons":     horizons,
            "preferred_signal_types": sig_types,
            "ignored_signal_types":   ignored,
            "generated_at":           _now_iso(),
        }
    except Exception as exc:
        logger.debug("[profile] get_attention_preferences failed: %r", exc)
        return {
            "user_id":                user_id,
            "preferred_horizons":     [],
            "preferred_signal_types": [],
            "ignored_signal_types":   [],
            "generated_at":           _now_iso(),
        }


async def get_personalization_context(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Assemble a combined personalization context for downstream read consumers.

    Combines the full interest profile with the attention preferences into a
    single dict keyed for downstream access.  This context is READ-ONLY — it
    describes what the user has signalled, not what action to take.

    No relevance adjustments or ranking changes are made here (that is Slice 15.8+).

    Returns:
    {
      "user_id":      str,
      "interests":    <get_user_interest_profile result>,
      "priorities":   <get_learned_priorities result>,
      "attention":    <get_attention_preferences result>,
      "generated_at": str,
    }
    """
    if not _inference_enabled(run_override):
        return {
            "user_id":      user_id,
            "interests":    _empty_profile(user_id),
            "priorities":   {},
            "attention":    {},
            "generated_at": _now_iso(),
        }
    if session is None:
        return {
            "user_id":      user_id,
            "interests":    _empty_profile(user_id),
            "priorities":   {},
            "attention":    {},
            "generated_at": _now_iso(),
        }
    try:
        interests  = await get_user_interest_profile(
            session, user_id=user_id, run_override=run_override,
        )
        priorities = await get_learned_priorities(
            session, user_id=user_id, run_override=run_override,
        )
        attention  = await get_attention_preferences(
            session, user_id=user_id, run_override=run_override,
        )
        return {
            "user_id":      user_id,
            "interests":    interests,
            "priorities":   priorities,
            "attention":    attention,
            "generated_at": _now_iso(),
        }
    except Exception as exc:
        logger.debug("[profile] get_personalization_context failed: %r", exc)
        return {
            "user_id":      user_id,
            "interests":    _empty_profile(user_id),
            "priorities":   {},
            "attention":    {},
            "generated_at": _now_iso(),
        }


async def summarize_user_learning_profile(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return a concise text summary of what the system has learned about the user.

    Produces a flat dict of human-readable summary strings plus the underlying
    counts.  Suitable for logging, debugging, and audit endpoints.

    No banned advisory language is used: the summary describes observations only
    (what the user has engaged with, not what they should do).

    Returns:
    {
      "user_id":              str,
      "total_preferences":    int,
      "strong_preferences":   int,
      "most_engaged_company": str | None,
      "most_engaged_sector":  str | None,
      "top_signal_type":      str | None,
      "first_ignored_type":   str | None,
      "horizon_focus":        str | None,
      "confidence_summary":   ConfidenceSummary,
      "evidence_summary":     EvidenceSummary,
      "has_portfolio_sensitivity": bool,
      "generated_at":         str,
    }
    """
    if not _inference_enabled(run_override):
        return {
            "user_id":              user_id,
            "total_preferences":    0,
            "strong_preferences":   0,
            "most_engaged_company": None,
            "most_engaged_sector":  None,
            "top_signal_type":      None,
            "first_ignored_type":   None,
            "horizon_focus":        None,
            "confidence_summary":   _empty_confidence_summary(),
            "evidence_summary":     {"total_evidence_count": 0, "dimensions_with_evidence": 0},
            "has_portfolio_sensitivity": False,
            "generated_at":         _now_iso(),
        }
    if session is None:
        return {
            "user_id":              user_id,
            "total_preferences":    0,
            "strong_preferences":   0,
            "most_engaged_company": None,
            "most_engaged_sector":  None,
            "top_signal_type":      None,
            "first_ignored_type":   None,
            "horizon_focus":        None,
            "confidence_summary":   _empty_confidence_summary(),
            "evidence_summary":     {"total_evidence_count": 0, "dimensions_with_evidence": 0},
            "has_portfolio_sensitivity": False,
            "generated_at":         _now_iso(),
        }
    try:
        profile = await get_user_interest_profile(
            session, user_id=user_id, run_override=run_override,
        )

        all_entries: List[Dict] = (
            profile["companies_of_interest"]
            + profile["sectors_of_interest"]
            + profile["recurring_themes"]
            + profile["preferred_horizons"]
            + profile["preferred_signal_types"]
            + profile["ignored_signal_types"]
            + profile["portfolio_sensitivities"]
        )

        conf_summary = profile["confidence_summary"]
        ev_summary   = profile["evidence_summary"]

        # Highest-confidence entity per category
        def _top_key(entries: List[Dict]) -> Optional[str]:
            return entries[0]["entity_key"] if entries else None

        companies = profile["companies_of_interest"]
        sectors   = profile["sectors_of_interest"]
        sig_types = profile["preferred_signal_types"]
        ignored   = profile["ignored_signal_types"]
        horizons  = profile["preferred_horizons"]
        portfolio = profile["portfolio_sensitivities"]

        return {
            "user_id":              user_id,
            "total_preferences":    len(all_entries),
            "strong_preferences":   conf_summary.get("strong_count", 0),
            "most_engaged_company": _top_key(companies),
            "most_engaged_sector":  _top_key(sectors),
            "top_signal_type":      _top_key(sig_types),
            "first_ignored_type":   _top_key(ignored),
            "horizon_focus":        _top_key(horizons),
            "confidence_summary":   conf_summary,
            "evidence_summary":     ev_summary,
            "has_portfolio_sensitivity": len(portfolio) > 0,
            "generated_at":         _now_iso(),
        }
    except Exception as exc:
        logger.debug("[profile] summarize_user_learning_profile failed: %r", exc)
        return {
            "user_id":              user_id,
            "total_preferences":    0,
            "strong_preferences":   0,
            "most_engaged_company": None,
            "most_engaged_sector":  None,
            "top_signal_type":      None,
            "first_ignored_type":   None,
            "horizon_focus":        None,
            "confidence_summary":   _empty_confidence_summary(),
            "evidence_summary":     {"total_evidence_count": 0, "dimensions_with_evidence": 0},
            "has_portfolio_sensitivity": False,
            "generated_at":         _now_iso(),
        }
