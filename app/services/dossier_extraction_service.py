"""
Phase 9G · Phase 0 — Company Dossier extraction service.

Pure, deterministic reconciliation brain.  No database calls, no LLM calls.

Pipeline context (this module = Stages 1 + 4):
  Stage 1  HARVEST   — harvest_from_thesis() pulls signals directly off
                        InvestmentThesis fields; no LLM required.
  Stage 2  EXTRACT   — (Slice 4 calls the LLM; this module defines the
                        DossierExtractionPayload schema that call must produce.)
  Stage 3  LOAD      — get_full_dossier() in dossier_repo (Slice 2).
  Stage 4  RECONCILE — build_extraction_plan() + per-facet reconcile_*()
                        functions apply all spec update rules and return a list
                        of planned DossierOp objects.
  Stage 5  COMMIT    — Slice 4 executes the plan against the DB.

Design constraints enforced here:
  * Confidence gate   τ_write = 0.55  — below: retain existing, skip write
  * High-conf gate    τ_high  = 0.75  — single-shot override for debate/moat
  * Specificity gate           = 0.50  — below: catalyst discarded
  * Debate re-version = semantic shift AND material delta AND confidence ≥ τ_high
  * Moat flip         = 2 consecutive agreeing syntheses OR 1 with conf ≥ τ_high
  * Append-only revisions — no delete ops ever emitted
  * Skip fallback/wall-cap theses (is_fallback_thesis check)

Exported for testing (all pure):
  is_fallback_thesis()
  harvest_from_thesis()
  build_extraction_plan()
  reconcile_debate()
  reconcile_moat_dimension()
  reconcile_catalysts()
  reconcile_variant()
  reconcile_durability()
  reconcile_failure_modes()
  score_catalyst_specificity()
  debate_text_distance()
  is_material_thesis_delta()
  infer_current_lean()
  claim_hash()
  build_revision_dict()
  build_evidence_dict()
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TAU_WRITE: float = 0.55          # min extraction confidence to write any facet
TAU_HIGH: float = 0.75           # single-shot override for debate versioning + moat
SPECIFICITY_GATE: float = 0.50   # min catalyst specificity to store
DEBATE_SIMILARITY_THRESHOLD: float = 0.60  # difflib ratio below = semantic shift
CATALYST_MATCH_RATIO: float = 0.75         # similarity to consider two statements same

# Fixed moat-axis taxonomy (spec §1.2 — extensible but must be in this set)
MOAT_AXES = frozenset({
    "ecosystem_lockin",
    "supply_chain_control",
    "switching_costs",
    "network_effects",
    "regulatory_ip",
    "management_execution",
})

# Material-delta threshold mirrors thesis_repo._compute_magnitude
MATERIAL_CONVICTION_DELTA: float = 0.15

# Directional stance → current_lean mapping
_STANCE_LEAN: Dict[str, str] = {
    "aggressive buy": "bull",
    "buy":            "bull",
    "accumulate":     "bull",
    "hold":           "balanced",
    "tactical":       "balanced",
    "avoid":          "bear",
    "sell":           "bear",
}

# InvestmentThesis thesis_trend → durability conviction_trend
_THESIS_TREND_MAP: Dict[str, str] = {
    "strengthening": "rising",
    "weakening":     "falling",
    "stable":        "stable",
    "unclear":       "stable",
    "volatile":      "volatile",
}

# setup_label → cycle_position / horizon_hint hints
_SETUP_CYCLE: Dict[str, str] = {
    "high-alignment thesis":  "early",
    "actionable thesis":      "mid",
    "monitoring required":    "mid",
    "expectation-sensitive":  "late",
    "mixed evidence":         "late",
    "fragile setup":          "late",
    "asymmetric setup":       "mid",
    "speculative setup":      "early",
    "insufficient conviction": "unknown",
}

_SETUP_HORIZON: Dict[str, str] = {
    "high-alignment thesis":  "investment",
    "actionable thesis":      "investment",
    "monitoring required":    "investment",
    "expectation-sensitive":  "trade",
    "mixed evidence":         "investment",
    "fragile setup":          "trade",
    "asymmetric setup":       "investment",
    "speculative setup":      "investment",
    "insufficient conviction": "investment",
}

# Valid moat strength and trend enums (guard against hallucinated values)
_VALID_STRENGTH = frozenset({"strong", "moderate", "weak", "absent"})
_VALID_TREND    = frozenset({"strengthening", "stable", "weakening"})
_VALID_LEAN     = frozenset({"bull", "bear", "balanced"})


# ===========================================================================
# Structured extraction payload (what the Slice 4 LLM call must produce)
# ===========================================================================

class MoatAxisExtract(BaseModel):
    """One moat axis as extracted by the structured LLM call in Slice 4."""
    axis:          str   = Field(description="One of MOAT_AXES")
    strength:      str   = Field(description="strong | moderate | weak | absent")
    trend:         str   = Field(description="strengthening | stable | weakening")
    rationale:     str   = Field(default="")
    vulnerability: str   = Field(default="")
    confidence:    float = Field(default=0.0, ge=0.0, le=1.0)


class CatalystExtract(BaseModel):
    """One candidate catalyst as extracted by the structured LLM call."""
    statement:        str   = Field(description="Falsifiable, specific trigger statement")
    direction:        str   = Field(description="bull_trigger | bear_trigger")
    specificity:      float = Field(default=0.0, ge=0.0, le=1.0)
    expected_window:  str   = Field(default="")
    conviction_weight: float = Field(default=0.5, ge=0.0, le=1.0)


class VariantDivergenceExtract(BaseModel):
    """One consensus-divergence item as extracted by the structured LLM call."""
    dimension:       str   = Field(description="revenue_trajectory | moat_durability | competitive_risk | valuation")
    consensus_view:  str   = Field(default="")
    clearsignal_view: str  = Field(default="")
    direction:       str   = Field(description="more_bullish | more_bearish")
    conviction:      float = Field(default=0.0, ge=0.0, le=1.0)


class DossierExtractionPayload(BaseModel):
    """
    Full structured output that the Slice 4 LLM extraction call must produce.

    Slice 3 defines this schema; Slice 4 calls the LLM via app/structured_output.py
    and passes the result into build_extraction_plan().
    """
    # Debate
    debate_question:             str   = Field(default="")
    debate_bull_pole:            str   = Field(default="")
    debate_bear_pole:            str   = Field(default="")
    debate_current_lean:         str   = Field(default="balanced")
    debate_resolution_signal:    str   = Field(default="")
    debate_extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Moat
    moat_axes:                List[MoatAxisExtract]          = Field(default_factory=list)
    moat_extraction_confidence: float                        = Field(default=0.0, ge=0.0, le=1.0)

    # Catalysts
    new_catalysts:               List[CatalystExtract]       = Field(default_factory=list)
    catalyst_extraction_confidence: float                    = Field(default=0.0, ge=0.0, le=1.0)
    # Catalyst resolution signals: existing catalyst IDs that appear fired/invalidated
    triggered_catalyst_ids:      List[str]                   = Field(default_factory=list)
    invalidated_catalyst_ids:    List[str]                   = Field(default_factory=list)

    # Variant perception
    variant_divergences:         List[VariantDivergenceExtract] = Field(default_factory=list)
    variant_extraction_confidence: float                     = Field(default=0.0, ge=0.0, le=1.0)


# ===========================================================================
# Planned operation types (output of this module, input to Slice 4 executor)
# ===========================================================================

@dataclass
class DossierOp:
    """
    A single planned write against the dossier repository.

    ``kind``        — matches a function name in dossier_repo / dossier_revision_repo.
    ``kwargs``      — arguments to pass to that function (excluding ``session``).
    ``revision``    — if not None, also call append_revision(session, **revision).
    ``evidence_refs`` — each item: call append_evidence_ref(session, **item).

    Slice 4 executes::

        row = await REPO_DISPATCH[op.kind](session, **op.kwargs)
        if op.revision:
            await append_revision(session, **op.revision)
        for ev in op.evidence_refs:
            await append_evidence_ref(session, **ev)

    NOTE: ``upsert_failure_mode`` ops carry ``analog_label`` instead of
    ``analog_id`` in kwargs.  Slice 4 must resolve the label to a UUID via
    a ``SELECT id FROM historical_analogs WHERE label = :label`` before
    calling the repo.
    """
    kind:          str
    kwargs:        Dict[str, Any]
    revision:      Optional[Dict[str, Any]]  = field(default=None)
    evidence_refs: List[Dict[str, Any]]      = field(default_factory=list)


@dataclass
class ExtractionPlan:
    """
    The complete planned update for one dossier, ready for Slice 4 to execute.

    ``ops``               — ordered list of DossierOp to execute.
    ``head_update``       — kwargs for a final upsert_head call (head counters /
                             prior_thesis_state refresh).  None if no head exists
                             yet (get_or_create_head is implied on first use).
    ``skipped_low_conf``  — ops dropped below τ_write (telemetry).
    ``skipped_specificity`` — catalyst ops dropped below specificity gate.
    ``is_fallback``       — True when the source thesis was a wall-cap fallback;
                             in this case ops is empty and nothing should run.
    """
    ticker:              str
    source_version_id:   str
    session_id:          str
    user_id:             Optional[str]
    ops:                 List[DossierOp]
    head_update:         Optional[Dict[str, Any]]  = field(default=None)
    skipped_low_conf:    int                        = 0
    skipped_specificity: int                        = 0
    is_fallback:         bool                       = False


# ===========================================================================
# Fallback guard
# ===========================================================================

def is_fallback_thesis(thesis: Any) -> bool:
    """Return True when the thesis is a wall-cap or empty-synthesis fallback.

    Mirrors the guard in ``app/db/persistence.py``.  Any thesis that passes
    this check is skipped entirely — no dossier writes are planned.
    """
    conclusion   = _safe_str(getattr(thesis, "conclusion",    ""))
    bull         = _safe_str(getattr(thesis, "bull_thesis",   ""))
    score_source = _safe_str(getattr(thesis, "score_source",  ""))
    confidence   = float(getattr(thesis, "confidence_score", 0.0) or 0.0)

    return (
        "wall cap exceeded"     in conclusion.lower()
        or "synthesis unavailable" in bull.lower()
        or score_source == "fallback_empty"
        or confidence == 0.0
    )


# ===========================================================================
# Stage 1 — Harvest (no LLM, direct from InvestmentThesis)
# ===========================================================================

def harvest_from_thesis(thesis: Any) -> Dict[str, Any]:
    """Extract directly-readable signals from an InvestmentThesis object.

    Returns a plain dict.  Used by build_extraction_plan to populate head,
    durability, and failure-mode ops — no LLM required.

    Fields returned::

        ticker, company_name,
        stance, conviction, primary_concern,
        latest_version_id, global_confidence,
        current_lean,
        conviction_trend, cycle_position, horizon_hint,
        catalyst_proximity_days,         # from catalyst_calendar if present
        analog_time_to_trough_days,      # from top historical analog if present
        failure_mode_analogs,            # list of {label, relevance_score, drawdown_pct, time_to_trough_days}
        what_changes_the_thesis,         # raw list[str] — candidate catalyst statements
        is_material_delta,               # bool
    """
    def _g(attr, default=""):
        return getattr(thesis, attr, None) or default

    ticker       = _safe_str(_g("ticker"))
    company_name = _safe_str(_g("company_name"))
    stance       = _safe_str(_g("directional_stance", "Hold"))
    conviction   = float(_g("confidence_score", 0.0))
    version_id   = _safe_str(_g("thesis_version_id", ""))
    cv           = _g("change_vector", {}) or {}

    # primary_concern: dominant risk / dimension
    key_risks   = list(_g("key_risks", []) or [])
    dom_dim     = _safe_str(_g("dominant_dimension", ""))
    primary_concern = key_risks[0] if key_risks else dom_dim

    # lean inferred from stance
    current_lean = infer_current_lean(thesis)

    # durability signals
    thesis_trend = _safe_str(_g("thesis_trend", "stable"))
    conviction_trend = _THESIS_TREND_MAP.get(thesis_trend.lower(), "stable")

    setup_label  = _safe_str(_g("setup_label", "actionable thesis")).lower()
    cycle_pos    = _SETUP_CYCLE.get(setup_label, "unknown")
    horizon_hint = _SETUP_HORIZON.get(setup_label, "investment")
    if stance.lower() == "tactical":
        horizon_hint = "trade"

    # catalyst proximity from catalyst_calendar
    cat_cal = _g("catalyst_calendar", None)
    cat_prox_days = None
    if cat_cal is not None:
        days_val = getattr(cat_cal, "days_to_event", None)
        if days_val is not None:
            try:
                cat_prox_days = int(days_val)
            except (TypeError, ValueError):
                pass

    # failure mode analogs from historical_evidence
    hist_ev = _g("historical_evidence", None)
    failure_mode_analogs: List[Dict[str, Any]] = []
    analog_time_to_trough = None
    if hist_ev is not None:
        analogs = list(getattr(hist_ev, "analogs", []) or [])
        for a in analogs:
            label   = _safe_str(getattr(a, "label", ""))
            rel     = float(getattr(a, "relevance_score", 0.0) or 0.0)
            dd_pct  = getattr(a, "drawdown_pct", None)
            trough  = getattr(a, "time_to_trough_days", None)
            if label:
                failure_mode_analogs.append({
                    "label": label,
                    "relevance_score": rel,
                    "drawdown_pct": dd_pct,
                    "time_to_trough_days": trough,
                })
        # top analog's trough -> durability signal
        if failure_mode_analogs:
            analog_time_to_trough = failure_mode_analogs[0].get("time_to_trough_days")

    # candidate catalyst statements
    wct = list(_g("what_changes_the_thesis", []) or [])

    return {
        "ticker":               ticker,
        "company_name":         company_name,
        "stance":               stance,
        "conviction":           conviction,
        "primary_concern":      primary_concern,
        "latest_version_id":    version_id,
        "global_confidence":    conviction,
        "current_lean":         current_lean,
        "conviction_trend":     conviction_trend,
        "cycle_position":       cycle_pos,
        "horizon_hint":         horizon_hint,
        "catalyst_proximity_days":          cat_prox_days,
        "analog_time_to_trough_days":       analog_time_to_trough,
        "failure_mode_analogs":             failure_mode_analogs,
        "what_changes_the_thesis":          wct,
        "is_material_delta":    is_material_thesis_delta(thesis),
    }


# ===========================================================================
# Stage 4 — Main entry point: build the full extraction plan
# ===========================================================================

def build_extraction_plan(
    payload:          DossierExtractionPayload,
    existing_dossier: Dict[str, Any],
    thesis:           Any,
    version_id:       str,
    session_id:       str = "",
    user_id:          Optional[str] = None,
) -> ExtractionPlan:
    """
    Reconcile a DossierExtractionPayload against the existing dossier and
    return a fully planned list of DossierOps.

    Parameters
    ----------
    payload:
        Structured output from the Slice 4 LLM extraction call.
    existing_dossier:
        Dict returned by ``get_full_dossier(session, ticker)`` (Slice 2).
    thesis:
        The InvestmentThesis object for this analysis cycle.
    version_id:
        The thesis_version.id for this cycle (the ``source_version_id``
        stamped on every revision / evidence_ref).
    session_id, user_id:
        Passed through to every op's kwargs.

    Returns
    -------
    ExtractionPlan  — call ``plan.is_fallback`` before executing.
    """
    if is_fallback_thesis(thesis):
        logger.debug("[dossier_extraction] skipping fallback thesis")
        return ExtractionPlan(
            ticker=_safe_str(getattr(thesis, "ticker", "UNKNOWN")),
            source_version_id=version_id,
            session_id=session_id,
            user_id=user_id,
            ops=[],
            is_fallback=True,
        )

    harvested       = harvest_from_thesis(thesis)
    ticker          = harvested["ticker"] or _safe_str(getattr(thesis, "ticker", "UNKNOWN"))
    is_mat_delta    = harvested["is_material_delta"]

    ops: List[DossierOp]   = []
    skip_low_conf:  int    = 0
    skip_specificity: int  = 0

    # ── 1. Core debate ───────────────────────────────────────────────────────
    debate_conf = float(payload.debate_extraction_confidence or 0.0)
    if debate_conf >= TAU_WRITE:
        debate_ops = reconcile_debate(
            debate_question        = payload.debate_question,
            debate_bull_pole       = payload.debate_bull_pole,
            debate_bear_pole       = payload.debate_bear_pole,
            debate_current_lean    = payload.debate_current_lean,
            debate_resolution_signal = payload.debate_resolution_signal,
            existing_debate        = existing_dossier.get("debate"),
            is_material_delta      = is_mat_delta,
            extraction_confidence  = debate_conf,
            version_id             = version_id,
            ticker                 = ticker,
            session_id             = session_id,
            user_id                = user_id,
        )
        ops.extend(debate_ops)
    else:
        skip_low_conf += 1
        logger.debug("[dossier_extraction] debate skipped: conf %.2f < τ_write", debate_conf)

    # ── 2. Moat dimensions ───────────────────────────────────────────────────
    moat_conf = float(payload.moat_extraction_confidence or 0.0)
    existing_dims = {d.axis: d for d in (existing_dossier.get("dimensions") or [])}
    if moat_conf >= TAU_WRITE:
        for ax_extract in payload.moat_axes:
            if ax_extract.axis not in MOAT_AXES:
                logger.debug("[dossier_extraction] ignoring unknown moat axis: %s", ax_extract.axis)
                continue
            if float(ax_extract.confidence or 0.0) < TAU_WRITE:
                skip_low_conf += 1
                continue
            op = reconcile_moat_dimension(
                extract            = ax_extract,
                existing           = existing_dims.get(ax_extract.axis),
                version_id         = version_id,
                ticker             = ticker,
                session_id         = session_id,
                user_id            = user_id,
            )
            if op is not None:
                ops.append(op)
    else:
        skip_low_conf += len(payload.moat_axes)
        logger.debug("[dossier_extraction] moat skipped: conf %.2f < τ_write", moat_conf)

    # ── 3. Catalysts ─────────────────────────────────────────────────────────
    existing_cats = list(existing_dossier.get("catalysts") or [])
    cat_ops, n_skip_spec = reconcile_catalysts(
        new_extracts           = payload.new_catalysts,
        triggered_ids          = payload.triggered_catalyst_ids,
        invalidated_ids        = payload.invalidated_catalyst_ids,
        existing_catalysts     = existing_cats,
        version_id             = version_id,
        ticker                 = ticker,
        session_id             = session_id,
        user_id                = user_id,
    )
    ops.extend(cat_ops)
    skip_specificity += n_skip_spec

    # ── 4. Variant perception ────────────────────────────────────────────────
    var_conf = float(payload.variant_extraction_confidence or 0.0)
    if var_conf >= TAU_WRITE:
        var_op = reconcile_variant(
            divergences            = payload.variant_divergences,
            existing               = existing_dossier.get("variant"),
            extraction_confidence  = var_conf,
            version_id             = version_id,
            ticker                 = ticker,
            session_id             = session_id,
            user_id                = user_id,
        )
        if var_op is not None:
            ops.append(var_op)
    else:
        skip_low_conf += 1

    # ── 5. Durability ────────────────────────────────────────────────────────
    dur_op = reconcile_durability(
        harvested              = harvested,
        ticker                 = ticker,
        session_id             = session_id,
        user_id                = user_id,
    )
    ops.append(dur_op)

    # ── 6. Failure modes ─────────────────────────────────────────────────────
    fm_ops = reconcile_failure_modes(
        failure_mode_analogs   = harvested["failure_mode_analogs"],
        ticker                 = ticker,
        version_id             = version_id,
        session_id             = session_id,
        user_id                = user_id,
    )
    ops.extend(fm_ops)

    # ── 7. Head update (always — refreshes counters + prior_thesis_state) ───
    existing_head = existing_dossier.get("head")
    head_update = {
        "ticker":             ticker,
        "company_name":       harvested["company_name"],
        "stance":             harvested["stance"],
        "conviction":         harvested["conviction"],
        "primary_concern":    harvested["primary_concern"],
        "latest_version_id":  version_id,
        "global_confidence":  harvested["global_confidence"],
        "staleness_state":    "fresh",
        "last_full_update_at": None,   # Slice 4 fills in with datetime.now(utc)
        "analysis_count":     (getattr(existing_head, "analysis_count", 0) or 0) + 1,
        "session_id":         session_id,
        "user_id":            user_id,
    }

    return ExtractionPlan(
        ticker              = ticker,
        source_version_id   = version_id,
        session_id          = session_id,
        user_id             = user_id,
        ops                 = ops,
        head_update         = head_update,
        skipped_low_conf    = skip_low_conf,
        skipped_specificity = skip_specificity,
        is_fallback         = False,
    )


# ===========================================================================
# Per-facet reconciliation  (pure — all exported for tests)
# ===========================================================================

def reconcile_debate(
    debate_question:          str,
    debate_bull_pole:         str,
    debate_bear_pole:         str,
    debate_current_lean:      str,
    debate_resolution_signal: str,
    existing_debate:          Any,
    is_material_delta:        bool,
    extraction_confidence:    float,
    version_id:               str,
    ticker:                   str,
    session_id:               str = "",
    user_id:                  Optional[str] = None,
) -> List[DossierOp]:
    """
    Apply debate update rules (spec §3.4) and return 0–2 ops.

    Decision table (all three conditions required for version bump):

    semantic_shift | material_delta | conf ≥ τ_high | outcome
    ───────────────────────────────────────────────────────────
    F              | any            | any           | lean_update only
    T              | F              | any           | lean_update + candidate revision
    T              | T              | F             | lean_update + candidate revision
    T              | T              | T             | lean_update + version_bump + revision

    Returns
    -------
    List of DossierOp (0–2 items).
    """
    lean      = _validate_lean(debate_current_lean)
    new_text  = f"{debate_question} {debate_bull_pole} {debate_bear_pole}".strip()

    # ── First-write path ─────────────────────────────────────────────────────
    if existing_debate is None:
        return [DossierOp(
            kind = "write_debate",
            kwargs = dict(
                ticker             = ticker,
                question           = debate_question,
                bull_pole          = debate_bull_pole,
                bear_pole          = debate_bear_pole,
                current_lean       = lean,
                resolution_signal  = debate_resolution_signal,
                version            = 1,
                confidence         = extraction_confidence,
                session_id         = session_id,
                user_id            = user_id,
                expect_version     = None,
            ),
            revision = None,
            evidence_refs = [build_evidence_dict(
                ticker      = ticker,
                facet       = "core_debate",
                claim_text  = debate_question,
                source_type = "thesis_version",
                source_id   = version_id,
            )],
        )]

    # ── Subsequent write: check conditions ──────────────────────────────────
    old_text       = f"{existing_debate.question} {existing_debate.bull_pole} {existing_debate.bear_pole}".strip()
    distance       = debate_text_distance(old_text, new_text)
    semantic_shift = distance > (1.0 - DEBATE_SIMILARITY_THRESHOLD)

    ops: List[DossierOp] = []

    # Lean update is always cheap / non-versioning
    existing_lean = getattr(existing_debate, "current_lean", "balanced")
    if lean != existing_lean:
        ops.append(DossierOp(
            kind   = "update_debate_lean",
            kwargs = dict(ticker=ticker, lean=lean, session_id=session_id),
        ))

    if not semantic_shift:
        # No semantic shift → nothing more to do
        return ops

    # Semantic shift detected: check for full version bump
    all_conditions = semantic_shift and is_material_delta and (extraction_confidence >= TAU_HIGH)
    existing_version = getattr(existing_debate, "version", 1)

    if all_conditions:
        # Full version bump
        new_version = existing_version + 1
        ops.append(DossierOp(
            kind = "write_debate",
            kwargs = dict(
                ticker             = ticker,
                question           = debate_question,
                bull_pole          = debate_bull_pole,
                bear_pole          = debate_bear_pole,
                current_lean       = lean,
                resolution_signal  = debate_resolution_signal,
                version            = new_version,
                confidence         = extraction_confidence,
                session_id         = session_id,
                user_id            = user_id,
                expect_version     = existing_version,
            ),
            revision = build_revision_dict(
                ticker          = ticker,
                facet           = "core_debate",
                prev_version    = existing_version,
                new_version     = new_version,
                before          = {"question": existing_debate.question, "version": existing_version},
                after           = {"question": debate_question,          "version": new_version},
                change_summary  = f"Debate reframed: semantic distance {distance:.2f}, "
                                  f"material delta confirmed, conf {extraction_confidence:.2f}",
                confidence      = extraction_confidence,
                source_version_id = version_id,
                session_id      = session_id,
                user_id         = user_id,
            ),
            evidence_refs = [build_evidence_dict(
                ticker      = ticker,
                facet       = "core_debate",
                claim_text  = debate_question,
                source_type = "thesis_version",
                source_id   = version_id,
            )],
        ))
    else:
        # Semantic shift without all conditions — log candidate shift only
        ops.append(DossierOp(
            kind = "write_debate",    # lean + resolution_signal update, no version bump
            kwargs = dict(
                ticker             = ticker,
                question           = existing_debate.question,  # unchanged
                bull_pole          = existing_debate.bull_pole,
                bear_pole          = existing_debate.bear_pole,
                current_lean       = lean,
                resolution_signal  = debate_resolution_signal or existing_debate.resolution_signal,
                version            = existing_version,          # unchanged
                confidence         = extraction_confidence,
                session_id         = session_id,
                user_id            = user_id,
                expect_version     = existing_version,
            ),
            # Log a candidate-shift revision (non-versioning, prev == new)
            revision = build_revision_dict(
                ticker          = ticker,
                facet           = "core_debate",
                prev_version    = existing_version,
                new_version     = existing_version,    # same — candidate only
                before          = {"question": existing_debate.question},
                after           = {"question": debate_question},
                change_summary  = (
                    f"Candidate debate shift (not versioned): "
                    f"semantic distance {distance:.2f}, "
                    f"material_delta={is_material_delta}, "
                    f"conf={extraction_confidence:.2f}"
                ),
                confidence      = extraction_confidence,
                source_version_id = version_id,
                session_id      = session_id,
                user_id         = user_id,
            ),
        ))

    return ops


def reconcile_moat_dimension(
    extract:    MoatAxisExtract,
    existing:   Any,
    version_id: str,
    ticker:     str,
    session_id: str = "",
    user_id:    Optional[str] = None,
) -> Optional[DossierOp]:
    """
    Reconcile one moat axis with hysteresis.

    Hysteresis states:
      1. No existing row → create at version 1; no revision.
      2. Existing, same strength+trend → update rationale/vulnerability only;
         no version bump, no revision.
      3. Existing, different, low conf, pending_flip=False → set_pending_flip=True;
         no version bump.
      4. Existing, different, low conf, pending_flip=True → confirms 2nd consecutive;
         version bump, revision, clear pending_flip.
      5. Existing, different, conf ≥ τ_high → immediate version bump; clear pending_flip.
    """
    strength = _validate_strength(extract.strength)
    trend    = _validate_trend(extract.trend)
    conf     = float(extract.confidence or 0.0)

    # ── First-write ──────────────────────────────────────────────────────────
    if existing is None:
        return DossierOp(
            kind = "upsert_dimension",
            kwargs = dict(
                ticker        = ticker,
                axis          = extract.axis,
                strength      = strength,
                trend         = trend,
                rationale     = extract.rationale,
                vulnerability = extract.vulnerability,
                version       = 1,
                confidence    = conf,
                pending_flip  = False,
                session_id    = session_id,
                user_id       = user_id,
                expect_version = None,
            ),
            evidence_refs = [build_evidence_dict(
                ticker      = ticker,
                facet       = "moat_dimension",
                claim_text  = f"{extract.axis}:{strength}:{trend}",
                source_type = "thesis_version",
                source_id   = version_id,
            )],
        )

    existing_strength = getattr(existing, "strength", "moderate")
    existing_trend    = getattr(existing, "trend",    "stable")
    pending_flip      = bool(getattr(existing, "pending_flip", False))
    existing_version  = int(getattr(existing, "version",  1))
    direction_changed = (strength != existing_strength) or (trend != existing_trend)

    if not direction_changed:
        # Same direction — update prose fields silently (no version bump, no revision)
        # Only emit an op if rationale/vulnerability actually differ
        existing_rat  = _safe_str(getattr(existing, "rationale",     ""))
        existing_vuln = _safe_str(getattr(existing, "vulnerability", ""))
        if (extract.rationale != existing_rat or extract.vulnerability != existing_vuln):
            return DossierOp(
                kind = "upsert_dimension",
                kwargs = dict(
                    ticker        = ticker,
                    axis          = extract.axis,
                    strength      = strength,
                    trend         = trend,
                    rationale     = extract.rationale,
                    vulnerability = extract.vulnerability,
                    version       = existing_version,
                    confidence    = conf,
                    pending_flip  = False,   # clear any stale pending_flip (same direction confirms)
                    session_id    = session_id,
                    user_id       = user_id,
                    expect_version = existing_version,
                ),
            )
        # Also clear a stale pending_flip if we're back to the same direction
        if pending_flip:
            return DossierOp(
                kind = "set_pending_flip",
                kwargs = dict(
                    ticker     = ticker,
                    axis       = extract.axis,
                    pending    = False,
                    session_id = session_id,
                ),
            )
        return None  # truly no change

    # Direction changed — apply hysteresis
    if conf >= TAU_HIGH:
        # State 5: immediate flip regardless of pending_flip
        new_version = existing_version + 1
        return DossierOp(
            kind = "upsert_dimension",
            kwargs = dict(
                ticker        = ticker,
                axis          = extract.axis,
                strength      = strength,
                trend         = trend,
                rationale     = extract.rationale,
                vulnerability = extract.vulnerability,
                version       = new_version,
                confidence    = conf,
                pending_flip  = False,
                session_id    = session_id,
                user_id       = user_id,
                expect_version = existing_version,
            ),
            revision = build_revision_dict(
                ticker    = ticker,
                facet     = "moat_dimension",
                prev_version = existing_version,
                new_version  = new_version,
                before    = {"axis": extract.axis, "strength": existing_strength, "trend": existing_trend},
                after     = {"axis": extract.axis, "strength": strength,          "trend": trend},
                change_summary = (
                    f"{extract.axis}: {existing_strength}/{existing_trend} → "
                    f"{strength}/{trend} (high-conf override, conf={conf:.2f})"
                ),
                confidence      = conf,
                source_version_id = version_id,
                session_id      = session_id,
                user_id         = user_id,
            ),
            evidence_refs = [build_evidence_dict(
                ticker      = ticker,
                facet       = "moat_dimension",
                claim_text  = f"{extract.axis}:{strength}:{trend}",
                source_type = "thesis_version",
                source_id   = version_id,
            )],
        )

    if not pending_flip:
        # State 3: first signal of a direction change — set pending, no version bump
        return DossierOp(
            kind = "set_pending_flip",
            kwargs = dict(
                ticker     = ticker,
                axis       = extract.axis,
                pending    = True,
                session_id = session_id,
            ),
        )

    # State 4: pending_flip=True and direction confirms → commit the flip
    new_version = existing_version + 1
    return DossierOp(
        kind = "upsert_dimension",
        kwargs = dict(
            ticker        = ticker,
            axis          = extract.axis,
            strength      = strength,
            trend         = trend,
            rationale     = extract.rationale,
            vulnerability = extract.vulnerability,
            version       = new_version,
            confidence    = conf,
            pending_flip  = False,   # hysteresis resolved
            session_id    = session_id,
            user_id       = user_id,
            expect_version = existing_version,
        ),
        revision = build_revision_dict(
            ticker    = ticker,
            facet     = "moat_dimension",
            prev_version = existing_version,
            new_version  = new_version,
            before    = {"axis": extract.axis, "strength": existing_strength, "trend": existing_trend},
            after     = {"axis": extract.axis, "strength": strength,          "trend": trend},
            change_summary = (
                f"{extract.axis}: {existing_strength}/{existing_trend} → "
                f"{strength}/{trend} (hysteresis confirmed, conf={conf:.2f})"
            ),
            confidence      = conf,
            source_version_id = version_id,
            session_id      = session_id,
            user_id         = user_id,
        ),
        evidence_refs = [build_evidence_dict(
            ticker      = ticker,
            facet       = "moat_dimension",
            claim_text  = f"{extract.axis}:{strength}:{trend}",
            source_type = "thesis_version",
            source_id   = version_id,
        )],
    )


def reconcile_catalysts(
    new_extracts:       List[CatalystExtract],
    triggered_ids:      List[str],
    invalidated_ids:    List[str],
    existing_catalysts: List[Any],
    version_id:         str,
    ticker:             str,
    session_id:         str = "",
    user_id:            Optional[str] = None,
) -> tuple[List[DossierOp], int]:
    """
    Reconcile catalyst watchlist: append new, transition existing.

    Returns (ops, n_skipped_specificity).

    Rules:
      * Candidates below specificity gate are discarded (never stored).
      * Candidates matching an existing open catalyst by text similarity
        are skipped (not duplicated).
      * ``triggered_ids`` / ``invalidated_ids`` carry existing catalyst IDs
        marked for lifecycle transition (populated by the Slice 4 LLM call).
      * Catalysts are never deleted — only lifecycle-transitioned.
    """
    ops:      List[DossierOp] = []
    n_skip:   int             = 0

    # Build lookup of existing open catalysts
    open_stmts = [
        _safe_str(getattr(c, "statement", ""))
        for c in existing_catalysts
        if getattr(c, "status", "open") == "open"
    ]

    # ── Lifecycle transitions for existing catalysts ──────────────────────
    for cat_id in (triggered_ids or []):
        ops.append(DossierOp(
            kind   = "transition_catalyst",
            kwargs = dict(catalyst_id=cat_id, new_status="triggered",
                          session_id=session_id),
            revision = None,
        ))

    for cat_id in (invalidated_ids or []):
        ops.append(DossierOp(
            kind   = "transition_catalyst",
            kwargs = dict(catalyst_id=cat_id, new_status="invalidated",
                          session_id=session_id),
            revision = None,
        ))

    # ── New catalyst candidates ───────────────────────────────────────────
    for extract in (new_extracts or []):
        stmt  = _safe_str(extract.statement)
        spec  = float(extract.specificity or 0.0)

        if not stmt:
            continue

        # Score specificity heuristically if payload value is 0.0
        eff_spec = spec if spec > 0.0 else score_catalyst_specificity(stmt)

        if eff_spec < SPECIFICITY_GATE:
            n_skip += 1
            logger.debug("[dossier_extraction] catalyst discarded (spec=%.2f): %s",
                         eff_spec, stmt[:60])
            continue

        # Deduplicate against existing open catalysts
        if any(catalysts_match(stmt, existing) for existing in open_stmts):
            logger.debug("[dossier_extraction] catalyst already tracked: %s", stmt[:60])
            continue

        ops.append(DossierOp(
            kind = "append_catalyst",
            kwargs = dict(
                ticker            = ticker,
                statement         = stmt,
                direction         = extract.direction,
                specificity       = eff_spec,
                expected_window   = extract.expected_window,
                conviction_weight = extract.conviction_weight,
                source_version_id = version_id,
                session_id        = session_id,
                user_id           = user_id,
            ),
            evidence_refs = [build_evidence_dict(
                ticker      = ticker,
                facet       = "catalyst",
                claim_text  = stmt,
                source_type = "thesis_version",
                source_id   = version_id,
            )],
        ))
        open_stmts.append(stmt)  # prevent same-cycle duplicates

    return ops, n_skip


def reconcile_variant(
    divergences:           List[VariantDivergenceExtract],
    existing:              Any,
    extraction_confidence: float,
    version_id:            str,
    ticker:                str,
    session_id:            str = "",
    user_id:               Optional[str] = None,
) -> Optional[DossierOp]:
    """
    Reconcile variant_perception.

    Cuts a new version when:
      * a divergence direction flips, OR
      * a new divergence dimension appears.

    Returns None when there is no material change.
    """
    new_divs = [d.model_dump() for d in (divergences or [])]

    if not new_divs:
        return None

    # First write
    if existing is None:
        return DossierOp(
            kind = "write_variant",
            kwargs = dict(
                ticker      = ticker,
                divergences = new_divs,
                version     = 1,
                confidence  = extraction_confidence,
                session_id  = session_id,
                user_id     = user_id,
                expect_version = None,
            ),
            evidence_refs = [build_evidence_dict(
                ticker      = ticker,
                facet       = "variant",
                claim_text  = " ".join(d.get("dimension","") for d in new_divs),
                source_type = "thesis_version",
                source_id   = version_id,
            )],
        )

    existing_divs: List[Dict[str, Any]] = list(getattr(existing, "divergences", []) or [])
    existing_version = int(getattr(existing, "version", 1))

    # Check for direction flip or new dimension
    existing_map = {d.get("dimension", ""): d.get("direction", "") for d in existing_divs}
    new_dims     = {d.get("dimension", "") for d in new_divs}
    material     = False
    for d in new_divs:
        dim = d.get("dimension", "")
        if dim not in existing_map:
            material = True          # new dimension
            break
        if d.get("direction") != existing_map.get(dim):
            material = True          # direction flip
            break

    if not material:
        return None

    new_version = existing_version + 1
    return DossierOp(
        kind = "write_variant",
        kwargs = dict(
            ticker      = ticker,
            divergences = new_divs,
            version     = new_version,
            confidence  = extraction_confidence,
            session_id  = session_id,
            user_id     = user_id,
            expect_version = existing_version,
        ),
        revision = build_revision_dict(
            ticker          = ticker,
            facet           = "variant",
            prev_version    = existing_version,
            new_version     = new_version,
            before          = {"divergences": existing_divs},
            after           = {"divergences": new_divs},
            change_summary  = "Variant perception updated: direction flip or new dimension",
            confidence      = extraction_confidence,
            source_version_id = version_id,
            session_id      = session_id,
            user_id         = user_id,
        ),
        evidence_refs = [build_evidence_dict(
            ticker      = ticker,
            facet       = "variant",
            claim_text  = " ".join(d.get("dimension","") for d in new_divs),
            source_type = "thesis_version",
            source_id   = version_id,
        )],
    )


def reconcile_durability(
    harvested:  Dict[str, Any],
    ticker:     str,
    session_id: str = "",
    user_id:    Optional[str] = None,
) -> DossierOp:
    """
    Build a write_durability op from the harvested thesis signals.

    Durability signals are always overwritten (no versioning); scoring is a
    pure function at read time (spec §1.2).  Returns an op unconditionally.
    """
    return DossierOp(
        kind = "write_durability",
        kwargs = dict(
            ticker                      = ticker,
            cycle_position              = harvested.get("cycle_position", "unknown"),
            catalyst_proximity_days     = harvested.get("catalyst_proximity_days"),
            analog_time_to_trough_days  = harvested.get("analog_time_to_trough_days"),
            conviction_trend            = harvested.get("conviction_trend", "stable"),
            horizon_hint                = harvested.get("horizon_hint", "investment"),
            session_id                  = session_id,
            user_id                     = user_id,
        ),
    )


def reconcile_failure_modes(
    failure_mode_analogs: List[Dict[str, Any]],
    ticker:               str,
    version_id:           str,
    session_id:           str = "",
    user_id:              Optional[str] = None,
) -> List[DossierOp]:
    """
    Produce upsert_failure_mode ops for each live analog.

    NOTE: kwargs contains ``analog_label`` (not ``analog_id``).
    Slice 4 must resolve the label to a UUID before calling the repo:
        SELECT id FROM historical_analogs WHERE label = :label
    The op kind is ``"upsert_failure_mode"`` to match the repo function;
    Slice 4's dispatch table handles the label→id resolution.
    """
    ops: List[DossierOp] = []
    for a in (failure_mode_analogs or []):
        label   = _safe_str(a.get("label", ""))
        rel     = float(a.get("relevance_score", 0.0) or 0.0)
        trough  = a.get("time_to_trough_days")
        dd_pct  = a.get("drawdown_pct")
        if not label:
            continue
        evidence = (
            f"Analog '{label}' matched (relevance={rel:.2f}"
            + (f", drawdown={dd_pct:.0%}" if dd_pct is not None else "")
            + (f", trough={trough}d" if trough is not None else "")
            + ")"
        )
        ops.append(DossierOp(
            kind = "upsert_failure_mode",
            kwargs = dict(
                ticker              = ticker,
                analog_label        = label,    # Slice 4 resolves to analog_id
                sequence_stage      = 1,        # default; Slice 4 LLM may override
                stage_evidence      = evidence,
                relevance_at_match  = rel,
                session_id          = session_id,
                user_id             = user_id,
            ),
            evidence_refs = [build_evidence_dict(
                ticker      = ticker,
                facet       = "failure_mode",
                claim_text  = label,
                source_type = "analog",
                source_id   = None,             # Slice 4 fills after label resolution
            )],
        ))
    return ops


# ===========================================================================
# Helpers — all pure, all exported
# ===========================================================================

def debate_text_distance(old_text: str, new_text: str) -> float:
    """Levenshtein-like distance between two debate texts (0.0 = identical, 1.0 = fully different).

    Uses difflib.SequenceMatcher: distance = 1.0 - ratio.
    Returns 1.0 when either text is empty (maximum distance).
    """
    a = (old_text or "").strip().lower()
    b = (new_text or "").strip().lower()
    if not a or not b:
        return 1.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return round(1.0 - ratio, 4)


def is_material_thesis_delta(thesis: Any) -> bool:
    """Return True when the current thesis represents a material change vs the prior.

    Material = stance changed OR |conviction_delta| > MATERIAL_CONVICTION_DELTA.
    Also returns True when ``thesis_trend`` is "strengthening" or "weakening"
    (i.e. the memory subsystem already classified this as a directional move).

    All fields are null-safe: returns False when thesis is entirely empty.
    """
    cv = getattr(thesis, "change_vector", {}) or {}
    if cv.get("stance_shifted"):
        return True
    conviction_delta = float(cv.get("conviction_delta", 0.0) or 0.0)
    if abs(conviction_delta) >= MATERIAL_CONVICTION_DELTA:
        return True
    trend = _safe_str(getattr(thesis, "thesis_trend", "")).lower()
    return trend in ("strengthening", "weakening")


def infer_current_lean(thesis: Any) -> str:
    """Map directional_stance to 'bull' | 'bear' | 'balanced'."""
    stance = _safe_str(getattr(thesis, "directional_stance", "Hold")).lower().strip()
    return _STANCE_LEAN.get(stance, "balanced")


def score_catalyst_specificity(statement: str) -> float:
    """Heuristic specificity score for a catalyst statement (0.0–1.0).

    High specificity = quantitative threshold + time window + named metric.
    Score = 0 → plain vague statement.
    Score ≥ SPECIFICITY_GATE (0.50) → considered specific enough to store.
    """
    if not statement or len(statement.strip()) < 10:
        return 0.0
    s = statement
    score = 0.0
    if re.search(r"[><$%]\s*[\d]", s):          score += 0.35   # quantitative threshold
    if re.search(r"Q[1-4][-\s]?\d{4}"
                 r"|H[12][-\s]?\d{4}"
                 r"|next\s*[\d]+\s*(?:quarter|earnings|month)"
                 r"|\bquarter\b|\bearnings\b", s, re.I):
        score += 0.25                                            # time window
    if re.search(r"revenue|margin|earnings|capex|eps|fcf"
                 r"|growth|share|multiple|guidance", s, re.I):
        score += 0.20                                            # named metric
    if re.search(r"launch|report|announce|filing|approval"
                 r"|rate\s*cut|fed|upgrade|downgrade", s, re.I):
        score += 0.10                                            # named event
    return min(round(score, 4), 1.0)


def catalysts_match(stmt_a: str, stmt_b: str) -> bool:
    """Return True when two catalyst statements are similar enough to be the same."""
    if not stmt_a or not stmt_b:
        return False
    ratio = difflib.SequenceMatcher(
        None,
        stmt_a.lower().strip(),
        stmt_b.lower().strip(),
    ).ratio()
    return ratio >= CATALYST_MATCH_RATIO


def claim_hash(text: str) -> str:
    """Return a stable 64-char SHA-256 hex digest of *text*."""
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def build_revision_dict(
    ticker:           str,
    facet:            str,
    prev_version:     Optional[int],
    new_version:      int,
    before:           Dict[str, Any],
    after:            Dict[str, Any],
    change_summary:   str,
    confidence:       float,
    source_version_id: str,
    session_id:       str = "",
    user_id:          Optional[str] = None,
) -> Dict[str, Any]:
    """Build a kwargs dict ready for ``append_revision(session, **d)``."""
    return {
        "ticker":             ticker,
        "facet":              facet,
        "prev_version":       prev_version,
        "new_version":        new_version,
        "change_summary":     change_summary,
        "diff_json":          {"before": before, "after": after},
        "confidence":         confidence,
        "source_version_id":  source_version_id,
        "session_id":         session_id,
        "user_id":            user_id,
    }


def build_evidence_dict(
    ticker:      str,
    facet:       str,
    claim_text:  str,
    source_type: str = "inferred",
    source_id:   Optional[str] = None,
) -> Dict[str, Any]:
    """Build a kwargs dict ready for ``append_evidence_ref(session, **d)``."""
    return {
        "ticker":      ticker,
        "facet":       facet,
        "claim_hash":  claim_hash(claim_text),
        "source_type": source_type,
        "source_id":   source_id,
    }


# ===========================================================================
# Internal helpers (not exported)
# ===========================================================================

def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()


def _validate_lean(v: str) -> str:
    lean = _safe_str(v).lower()
    return lean if lean in _VALID_LEAN else "balanced"


def _validate_strength(v: str) -> str:
    s = _safe_str(v).lower()
    return s if s in _VALID_STRENGTH else "moderate"


def _validate_trend(v: str) -> str:
    t = _safe_str(v).lower()
    return t if t in _VALID_TREND else "stable"
