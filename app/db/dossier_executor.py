"""
Phase 9G · Phase 0 — Company Dossier extraction executor.

Applies an ExtractionPlan (produced by dossier_extraction_service.py) to
an AsyncSession.  This is the ONLY place in the codebase that translates
DossierOp objects into actual repository calls.

Design constraints:
  * A failed individual op is caught, logged, and skipped — other ops continue.
  * This module NEVER commits the session; the caller controls the transaction.
  * upsert_failure_mode ops carry ``analog_label`` in kwargs; this module
    resolves the label to an ``analog_id`` via ``SELECT id FROM historical_analogs
    WHERE label = :label`` before calling the repo.
  * Returns a telemetry summary dict.  Never raises.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def execute_extraction_plan(session, plan: Any) -> Dict[str, Any]:
    """Apply plan.ops to *session*, then write plan.head_update.

    Parameters
    ----------
    session:
        AsyncSession (or None — all ops become no-ops when None).
    plan:
        ExtractionPlan from dossier_extraction_service.build_extraction_plan().

    Returns
    -------
    Summary dict with ops_total / ops_succeeded / ops_failed /
    revisions_written / evidence_refs_written / skipped_* counters.
    """
    if session is None:
        return _empty_summary(plan)

    from .repositories.dossier_repo import (
        write_debate,
        update_debate_lean,
        upsert_dimension,
        set_pending_flip,
        append_catalyst,
        transition_catalyst,
        write_variant,
        write_durability,
        upsert_failure_mode,
        upsert_head,
    )
    from .repositories.dossier_revision_repo import append_revision, append_evidence_ref

    ops_succeeded = 0
    ops_failed    = 0
    revisions     = 0
    evidence_refs = 0

    for op in plan.ops:
        try:
            row = await _dispatch_op(
                session, op, plan.ticker,
                write_debate, update_debate_lean,
                upsert_dimension, set_pending_flip,
                append_catalyst, transition_catalyst,
                write_variant, write_durability,
                upsert_failure_mode,
            )

            # row=None from the repo means optimistic-lock conflict or row-not-found.
            # Count as failed/skipped — do NOT write revision for a no-op.
            if row is None and op.kind not in ("set_pending_flip", "transition_catalyst",
                                               "update_debate_lean"):
                ops_failed += 1
                continue

            ops_succeeded += 1

            # Append revision if this op carries one
            if op.revision:
                r = await append_revision(session, **op.revision)
                if r is not None:
                    revisions += 1

            # Append evidence refs
            for ev in (op.evidence_refs or []):
                er = await append_evidence_ref(
                    session,
                    ticker      = ev.get("ticker", plan.ticker),
                    facet       = ev.get("facet", ""),
                    claim_hash  = ev.get("claim_hash", ""),
                    source_type = ev.get("source_type", "inferred"),
                    source_id   = ev.get("source_id"),
                    session_id  = plan.session_id,
                    user_id     = plan.user_id,
                )
                if er is not None:
                    evidence_refs += 1

        except Exception as exc:
            ops_failed += 1
            logger.warning("[dossier_executor] op %s failed: %r", op.kind, exc)

    # Head update — always last, so facet writes are visible
    if plan.head_update:
        try:
            hu     = dict(plan.head_update)
            ticker = hu.pop("ticker", plan.ticker)
            await upsert_head(session, ticker, **hu)
        except Exception as exc:
            logger.warning("[dossier_executor] head_update failed: %r", exc)

    return {
        "ticker":                plan.ticker,
        "ops_total":             len(plan.ops),
        "ops_succeeded":         ops_succeeded,
        "ops_failed":            ops_failed,
        "revisions_written":     revisions,
        "evidence_refs_written": evidence_refs,
        "skipped_low_conf":      plan.skipped_low_conf,
        "skipped_specificity":   plan.skipped_specificity,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _dispatch_op(
    session, op, fallback_ticker: str,
    write_debate, update_debate_lean,
    upsert_dimension, set_pending_flip,
    append_catalyst, transition_catalyst,
    write_variant, write_durability,
    upsert_failure_mode,
) -> Optional[Any]:
    """Route one DossierOp to the correct repository function."""
    kw     = dict(op.kwargs)
    ticker = kw.pop("ticker", fallback_ticker)

    if op.kind == "write_debate":
        return await write_debate(session, ticker, **kw)

    if op.kind == "update_debate_lean":
        lean = kw.pop("lean")
        return await update_debate_lean(session, ticker, lean, **kw)

    if op.kind == "upsert_dimension":
        axis = kw.pop("axis")
        return await upsert_dimension(session, ticker, axis, **kw)

    if op.kind == "set_pending_flip":
        axis    = kw.pop("axis")
        pending = kw.pop("pending")
        return await set_pending_flip(session, ticker, axis, pending, **kw)

    if op.kind == "append_catalyst":
        return await append_catalyst(session, ticker, **kw)

    if op.kind == "transition_catalyst":
        # transition_catalyst has no ticker arg
        catalyst_id = kw.pop("catalyst_id")
        new_status  = kw.pop("new_status")
        return await transition_catalyst(session, catalyst_id, new_status, **kw)

    if op.kind == "write_variant":
        return await write_variant(session, ticker, **kw)

    if op.kind == "write_durability":
        return await write_durability(session, ticker, **kw)

    if op.kind == "upsert_failure_mode":
        analog_label = kw.pop("analog_label", None)
        if not analog_label:
            logger.debug("[dossier_executor] upsert_failure_mode skipped: no analog_label")
            return None
        analog_id = await _resolve_analog_id(session, analog_label)
        if analog_id is None:
            logger.debug("[dossier_executor] analog label not found in DB: %s", analog_label)
            return None
        return await upsert_failure_mode(session, ticker, analog_id, **kw)

    logger.warning("[dossier_executor] unknown op kind: %s", op.kind)
    return None


async def _resolve_analog_id(session, label: str) -> Optional[str]:
    """SELECT id FROM historical_analogs WHERE label = :label."""
    if not label:
        return None
    try:
        from sqlalchemy import select
        from .models import HistoricalAnalog
        stmt = select(HistoricalAnalog.id).where(HistoricalAnalog.label == label)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return str(row) if row else None
    except Exception as exc:
        logger.warning("[dossier_executor] _resolve_analog_id failed for %r: %r", label, exc)
        return None


def _empty_summary(plan: Any) -> Dict[str, Any]:
    return {
        "ticker":                getattr(plan, "ticker", "UNKNOWN"),
        "ops_total":             len(getattr(plan, "ops", [])),
        "ops_succeeded":         0,
        "ops_failed":            0,
        "revisions_written":     0,
        "evidence_refs_written": 0,
        "skipped_low_conf":      getattr(plan, "skipped_low_conf", 0),
        "skipped_specificity":   getattr(plan, "skipped_specificity", 0),
    }
