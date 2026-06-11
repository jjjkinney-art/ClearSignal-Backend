"""
Phase 9G · Phase 0 — Company Dossier fire-and-forget extraction task.

Entry point: ``run_dossier_extraction_task()``.

Called from the /ask post-dispatch path as::

    asyncio.create_task(run_dossier_extraction_task(...))

Design rules (identical to persistence.py):
  1. Never raise to the caller — all errors are logged and swallowed.
  2. Never block the response — runs after the JSON body has been yielded.
  3. Degrade gracefully — no-op when DATABASE_URL is empty or session is None.
  4. Skip fallback / wall-cap theses via is_fallback_thesis().
  5. Respects the dossier_extraction_enabled feature flag (caller must check
     before creating the task, but also guarded here for defence-in-depth).

Pipeline sequence for one /ask call:
  1. Convert serialised thesis dict → SimpleNamespace for attribute access.
  2. HARVEST stage — harvest_from_thesis(thesis_ns): extract durability signals,
     failure-mode analogs, cycle hints, and material-delta flag directly from
     the thesis without an LLM call.
  3. EXTRACT stage — _build_payload_from_thesis(): build a DossierExtractionPayload
     from thesis fields (debate from core_debate + core_market_debate, catalysts
     from what_changes_the_thesis, moat and variant left empty for Slice 5).
  4. LOAD stage — get_full_dossier(): read current facet state from DB.
  5. RECONCILE stage — build_extraction_plan(): apply all spec update rules.
  6. COMMIT stage — execute_extraction_plan(): write ops to DB under one session.

The full LLM-based moat/variant extraction (Stage 3 structured call) is NOT
implemented in Slice 4.  Those axes remain empty in the payload; Slice 5 will
add the structured LLM call.
"""

from __future__ import annotations

import logging
import types
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Module-level import of get_session so tests can patch it via
#   patch("app.db.dossier_extraction_task.get_session", ...)
# The deferred import inside _run_inner is replaced by a reference here.
try:
    from .connection import get_session
except Exception:  # pragma: no cover — graceful if connection not yet initialised
    get_session = None  # type: ignore[assignment]


# ===========================================================================
# Public entry point
# ===========================================================================

async def run_dossier_extraction_task(
    ticker:       str,
    company_name: str,
    thesis_dict:  Dict[str, Any],
    version_id:   str,
    session_id:   str = "",
    user_id:      Optional[str] = None,
) -> None:
    """Persist dossier facets for one /ask analysis cycle.

    Designed to be called as ``asyncio.create_task(run_dossier_extraction_task(...))``.

    All exceptions are caught and logged — this function is guaranteed to
    return without raising.

    Parameters
    ----------
    ticker:
        Normalised ticker symbol (e.g. "NVDA").
    company_name:
        Display company name from the analysis request.
    thesis_dict:
        The serialised ``InvestmentThesis`` dict from the /ask result
        (post 9C memory stamp, post 9F evidence stamp).
    version_id:
        Stable UUID for this extraction cycle — used as ``source_version_id``
        on every revision and evidence_ref row.  Distinct from ThesisVersion.id
        (generated independently to avoid the race with persist_analysis_result).
    session_id:
        HTTP session / request ID for audit trail.
    user_id:
        Optional authenticated user UUID (Phase 9C).
    """
    try:
        await _run_inner(ticker, company_name, thesis_dict, version_id, session_id, user_id)
    except Exception as exc:
        logger.warning(
            "[dossier_extraction_task] unhandled error for %s: %r", ticker, exc
        )


# ===========================================================================
# Inner implementation
# ===========================================================================

async def _run_inner(
    ticker:       str,
    company_name: str,
    thesis_dict:  Dict[str, Any],
    version_id:   str,
    session_id:   str,
    user_id:      Optional[str],
) -> None:
    # get_session is a module-level name (patchable in tests)
    import app.db.dossier_extraction_task as _self
    _get_session = _self.get_session
    from .repositories.dossier_repo import get_or_create_head, get_full_dossier
    from .dossier_executor import execute_extraction_plan
    from ..services.dossier_extraction_service import (
        is_fallback_thesis,
        harvest_from_thesis,
        build_extraction_plan,
    )

    # Step 1: convert dict → namespace
    thesis_ns = _thesis_ns_from_dict(thesis_dict)

    # Step 2: fallback guard (defence-in-depth; caller also checks)
    if is_fallback_thesis(thesis_ns):
        logger.debug(
            "[dossier_extraction_task] skipping fallback thesis for %s", ticker
        )
        return

    # Step 3: harvest + build payload (no LLM calls)
    harvested = harvest_from_thesis(thesis_ns)
    payload   = _build_payload_from_thesis(thesis_ns, harvested)

    async with _get_session() as session:
        if session is None:
            return

        # Step 4: ensure head row exists, then load full dossier
        await get_or_create_head(
            session,
            ticker,
            company_name = company_name or harvested.get("company_name", ""),
            session_id   = session_id,
            user_id      = user_id,
        )
        existing = await get_full_dossier(session, ticker)

        # Step 5: build plan (pure — no DB calls)
        plan = build_extraction_plan(
            payload          = payload,
            existing_dossier = existing,
            thesis           = thesis_ns,
            version_id       = version_id,
            session_id       = session_id,
            user_id          = user_id,
        )

        if plan.is_fallback:
            return

        # Step 6: execute (writes inside the session; get_session commits on exit)
        summary = await execute_extraction_plan(session, plan)
        logger.info(
            "[dossier_extraction_task] %s: ops=%d/%d rev=%d ev=%d skip_conf=%d skip_spec=%d",
            ticker,
            summary["ops_succeeded"], summary["ops_total"],
            summary["revisions_written"],
            summary["evidence_refs_written"],
            summary["skipped_low_conf"],
            summary["skipped_specificity"],
        )


# ===========================================================================
# Thesis dict → SimpleNamespace helpers
# ===========================================================================

def _thesis_ns_from_dict(d: Dict[str, Any]) -> Any:
    """Convert a serialised InvestmentThesis dict to a SimpleNamespace.

    Rules:
      * Top-level scalars and lists pass through unchanged.
      * ``historical_evidence`` (dict with ``analogs`` list) → SimpleNamespace
        with ``analogs`` as a list of SimpleNamespaces so that
        ``harvest_from_thesis`` can do ``getattr(analog, "label")``.
      * ``catalyst_calendar`` (dict or None) → SimpleNamespace or None.
      * ``change_vector`` stays as a plain dict so ``.get()`` calls work.
      * ``conviction_dimensions`` stays as a plain dict.
    """
    kwargs: Dict[str, Any] = {}

    for k, v in (d or {}).items():
        if k == "historical_evidence":
            kwargs[k] = _historical_evidence_ns(v)
        elif k == "catalyst_calendar" and isinstance(v, dict):
            kwargs[k] = types.SimpleNamespace(**v)
        else:
            kwargs[k] = v

    return types.SimpleNamespace(**kwargs)


def _historical_evidence_ns(he: Any) -> Optional[Any]:
    """Convert the historical_evidence dict to a namespace for attribute access."""
    if he is None:
        return None
    if not isinstance(he, dict):
        return he  # already a model object (shouldn't happen in serialised form)
    analogs_raw = he.get("analogs") or []
    analog_nses = [
        types.SimpleNamespace(**a) if isinstance(a, dict) else a
        for a in analogs_raw
    ]
    return types.SimpleNamespace(
        analogs      = analog_nses,
        retrieval_note = he.get("retrieval_note"),
    )


# ===========================================================================
# Payload builder (Stages 1+2 approximation — no LLM for Slice 4)
# ===========================================================================

def _build_payload_from_thesis(thesis_ns: Any, harvested: Dict[str, Any]) -> Any:
    """Build a DossierExtractionPayload from harvested thesis fields.

    This is the best-effort Stage 1+2 approximation used by the Slice 4
    fire-and-forget path.  It populates:

      * debate fields      — from core_debate / core_market_debate / bull_thesis /
                             bear_thesis / directional_stance / confidence_score.
      * catalyst list      — from what_changes_the_thesis (specificity-scored).
      * moat_axes          — empty list (Slice 5 adds the LLM structured call).
      * variant_divergences — empty list (Slice 5 adds the LLM structured call).

    Confidence for debate and catalysts = thesis confidence_score so that
    low-confidence analyses are properly filtered by the τ_write gate.
    """
    from ..services.dossier_extraction_service import (
        DossierExtractionPayload,
        CatalystExtract,
        score_catalyst_specificity,
        infer_current_lean,
    )

    def _s(attr: str, default: str = "") -> str:
        return str(getattr(thesis_ns, attr, None) or default)

    conf = float(getattr(thesis_ns, "confidence_score", 0.0) or 0.0)
    lean = infer_current_lean(thesis_ns)

    # Debate: prefer core_debate; fall back to core_market_debate; then conclusion
    debate_question = (
        _s("core_debate")
        or _s("core_market_debate")
        or _s("conclusion")[:300]
    )
    bull_pole = _s("bull_thesis")[:600]
    bear_pole = _s("bear_thesis")[:600]

    # Catalysts from what_changes_the_thesis list
    new_catalysts: List[CatalystExtract] = []
    wct = list(getattr(thesis_ns, "what_changes_the_thesis", []) or [])
    for stmt in wct:
        stmt_str = str(stmt or "").strip()
        if not stmt_str:
            continue
        spec = score_catalyst_specificity(stmt_str)
        new_catalysts.append(CatalystExtract(
            statement         = stmt_str,
            direction         = "bull_trigger",   # directional hint not available here
            specificity       = spec,
            expected_window   = "",
            conviction_weight = conf,
        ))

    return DossierExtractionPayload(
        # Debate
        debate_question               = debate_question,
        debate_bull_pole              = bull_pole,
        debate_bear_pole              = bear_pole,
        debate_current_lean           = lean,
        debate_resolution_signal      = "",
        debate_extraction_confidence  = conf,
        # Moat (empty — Slice 5 adds LLM structured call)
        moat_axes                     = [],
        moat_extraction_confidence    = 0.0,
        # Catalysts
        new_catalysts                 = new_catalysts,
        catalyst_extraction_confidence = conf,
        triggered_catalyst_ids        = [],
        invalidated_catalyst_ids      = [],
        # Variant (empty — Slice 5 adds LLM structured call)
        variant_divergences           = [],
        variant_extraction_confidence = 0.0,
    )
