"""
Similarity Feature Builder — Phase 11 · Slices 2 & 4.

Builds feature vectors for three similarity targets:
  T4 — failure-mode  (Slice 2)
  T1 — company       (Slice 4)
  T2 — thesis         (Slice 4)

Reads (read-only):
  T4: dossier_failure_mode, historical_analogs
  T1: company_dossier, cross_exposures, dossier_core_debate,
      dossier_moat_dimension, dossier_durability
  T2: thesis_versions, dossier_core_debate, dossier_variant,
      dossier_durability

Writes:
  - similarity_feature_vector  (via app.db.repositories.similarity_repo)

Safety invariants (Phase 11 SP-1 / SP-2):
  - This module NEVER writes to any source table listed above. It only
    reads them and upserts derived rows into similarity_feature_vector.
  - T4 feature fields reuse the same typed taxonomy as evidence_engine's
    SetupFingerprint (sector, business_model, valuation_regime,
    growth_phase, macro_regime, concern_tags) rather than forking new
    categories — this keeps T4 vectors comparable with the existing
    analog-matching substrate without duplicating its scoring logic.
  - No scoring, ranking, or edge creation happens here — that is Slice 3
    (T4 only; T1/T2 scoring is out of scope for Slice 4).

Missing-substrate behavior:
  - The defining row for an entity is absent (no dossier_failure_mode row,
    no company_dossier head, no thesis_versions row) -> None, nothing to
    build, no entity to vectorize.
  - Any joined facet (analog, core_debate, moat_dimension, variant,
    durability, cross_exposures) is missing -> sparse vector built from
    whatever substrate IS present; missing categorical fields default to
    "", missing tag/numeric fields default to [] / 0.0. Never raises.
  - Any other error -> logged at debug level, returns None. Never raises.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Bumped when a target's feature taxonomy changes (independent per target).
FEATURE_VERSION: int = 1          # T4 — failure_mode
COMPANY_FEATURE_VERSION: int = 1  # T1 — company
THESIS_FEATURE_VERSION: int = 1   # T2 — thesis

# strength -> numeric proxy for moat scoring (interpretable, not opaque)
_MOAT_STRENGTH_SCORE = {
    "strong": 1.0,
    "moderate": 0.6,
    "weak": 0.3,
    "absent": 0.0,
}


def _safe_json_list(raw) -> list:
    """Parse a JSON-encoded list column; never raises, defaults to []."""
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _build_text_anchor(fm, analog) -> str:
    label = getattr(analog, "label", "") if analog is not None else ""
    stage = getattr(fm, "sequence_stage", 1)
    ticker = getattr(fm, "ticker", "")
    if label:
        return f'{ticker} is matched to failure-mode analog "{label}" at sequence stage {stage}.'
    return f"{ticker} has an active failure-mode match (analog record unavailable) at sequence stage {stage}."


async def build_failure_mode_feature_vector(session, failure_mode_id: str) -> Optional[object]:
    """Build (or refresh) the T4 feature vector for one DossierFailureMode row.

    entity_key = the DossierFailureMode.id — one feature vector per active
    ticker x analog match.

    Returns the upserted SimilarityFeatureVector ORM row, or None when:
      - session is None
      - failure_mode_id does not resolve to a row
      - an unexpected error occurs (logged at debug level)

    A missing/unlinked analog does NOT cause a None return — a sparse vector
    is built from the dossier_failure_mode fields alone.
    """
    if session is None:
        return None
    try:
        from sqlalchemy import select
        from app.db.models import DossierFailureMode, HistoricalAnalog
        from app.db.repositories.similarity_repo import upsert_feature_vector

        fm = (
            await session.execute(
                select(DossierFailureMode).where(DossierFailureMode.id == failure_mode_id)
            )
        ).scalar_one_or_none()
        if fm is None:
            logger.debug(
                "[similarity_feature_builder] failure_mode_id=%s not found — nothing to build",
                failure_mode_id,
            )
            return None

        analog = None
        if fm.analog_id:
            analog = (
                await session.execute(
                    select(HistoricalAnalog).where(HistoricalAnalog.id == fm.analog_id)
                )
            ).scalar_one_or_none()
            if analog is None:
                logger.debug(
                    "[similarity_feature_builder] analog_id=%s missing for failure_mode_id=%s "
                    "— building sparse vector",
                    fm.analog_id, failure_mode_id,
                )

        categorical = {
            "ticker": fm.ticker,
            "analog_id": fm.analog_id or "",
            "failure_mode_label": getattr(analog, "label", "") if analog else "",
            "mechanism": getattr(analog, "mechanism", "") if analog else "",
            "sector": getattr(analog, "sector", "") if analog else "",
            "business_model": getattr(analog, "business_model", "") if analog else "",
            "valuation_regime": getattr(analog, "valuation_regime", "") if analog else "",
            "growth_phase": getattr(analog, "growth_phase", "") if analog else "",
            "macro_regime": getattr(analog, "macro_regime", "") if analog else "",
            "quality_rating": getattr(analog, "quality_rating", "") if analog else "",
        }
        tag_set = list(getattr(analog, "concern_tags", None) or []) if analog else []
        numeric = {
            "sequence_stage": float(fm.sequence_stage or 0),
            "relevance_at_match": float(fm.relevance_at_match or 0.0),
        }
        text_anchor = _build_text_anchor(fm, analog)
        source_versions = {
            "dossier_failure_mode_id": fm.id,
            "dossier_failure_mode_matched_at": fm.matched_at.isoformat() if fm.matched_at else "",
            "analog_id": fm.analog_id or "",
        }

        row = await upsert_feature_vector(
            session,
            target_type="failure_mode",
            entity_key=fm.id,
            categorical=categorical,
            tag_set=tag_set,
            numeric=numeric,
            text_anchor=text_anchor,
            source_versions=source_versions,
            vector_schema=FEATURE_VERSION,
            user_id=fm.user_id,
        )
        return row
    except Exception as exc:
        logger.debug(
            "[similarity_feature_builder] build_failure_mode_feature_vector failed for %s: %r",
            failure_mode_id, exc,
        )
        return None


async def build_failure_mode_feature_vectors_for_ticker(session, ticker: str) -> List[object]:
    """Build T4 feature vectors for every DossierFailureMode row of *ticker*.

    Returns the list of successfully-built ORM rows. Returns [] when
    session is None, ticker has no failure-mode matches, or on error.
    """
    if session is None:
        return []
    try:
        from app.db.repositories.dossier_repo import list_failure_modes

        fms = await list_failure_modes(session, ticker)
        results: List[object] = []
        for fm in fms:
            built = await build_failure_mode_feature_vector(session, fm.id)
            if built is not None:
                results.append(built)
        return results
    except Exception as exc:
        logger.debug(
            "[similarity_feature_builder] build_failure_mode_feature_vectors_for_ticker "
            "failed for %s: %r", ticker, exc,
        )
        return []


async def build_failure_mode_feature_vectors_for_all(
    session, limit: Optional[int] = None
) -> List[object]:
    """Build T4 feature vectors for every DossierFailureMode row in the system.

    Returns the list of successfully-built ORM rows. Returns [] when
    session is None or on error.
    """
    if session is None:
        return []
    try:
        from sqlalchemy import select
        from app.db.models import DossierFailureMode

        stmt = select(DossierFailureMode.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        ids = (await session.execute(stmt)).scalars().all()

        results: List[object] = []
        for fm_id in ids:
            built = await build_failure_mode_feature_vector(session, fm_id)
            if built is not None:
                results.append(built)
        return results
    except Exception as exc:
        logger.debug(
            "[similarity_feature_builder] build_failure_mode_feature_vectors_for_all failed: %r",
            exc,
        )
        return []


# ===========================================================================
# T1 — COMPANY
# ===========================================================================

def _build_company_text_anchor(head, debate, moat_axes_present) -> str:
    ticker = getattr(head, "ticker", "")
    stance = getattr(head, "stance", "") or "no stated stance"
    lean = getattr(debate, "current_lean", "") if debate is not None else ""
    parts = [f"{ticker} — stance={stance}"]
    if lean:
        parts.append(f"core debate lean={lean}")
    if moat_axes_present:
        parts.append(f"moat axes present: {', '.join(moat_axes_present)}")
    return "; ".join(parts) + "."


async def build_company_feature_vector(session, ticker: str) -> Optional[object]:
    """Build (or refresh) the T1 feature vector for one ticker's company dossier.

    entity_key = ticker. Returns None when:
      - session is None
      - no company_dossier head row exists for this ticker (nothing to vectorize)
      - an unexpected error occurs (logged at debug level)

    Missing core_debate / moat dimensions / durability / cross_exposures do
    NOT cause a None return — a sparse vector is built from whatever facets
    ARE present.
    """
    if session is None:
        return None
    try:
        from sqlalchemy import select
        from app.db.models import CrossExposure
        from app.db.repositories.dossier_repo import (
            get_head, get_debate, get_dimensions, get_durability,
        )
        from app.db.repositories.similarity_repo import upsert_feature_vector

        head = await get_head(session, ticker)
        if head is None:
            logger.debug(
                "[similarity_feature_builder] no company_dossier head for ticker=%s "
                "— nothing to build", ticker,
            )
            return None

        norm_ticker = head.ticker
        debate = await get_debate(session, norm_ticker)
        dimensions = await get_dimensions(session, norm_ticker)
        durability = await get_durability(session, norm_ticker)

        exposures = (
            await session.execute(
                select(CrossExposure).where(
                    (CrossExposure.ticker_a == norm_ticker)
                    | (CrossExposure.ticker_b == norm_ticker)
                )
            )
        ).scalars().all()

        moat_axes_present = sorted(
            d.axis for d in dimensions if (d.strength or "absent") != "absent"
        )
        moat_strength_values = [
            _MOAT_STRENGTH_SCORE.get(d.strength, 0.0) for d in dimensions
        ]
        moat_strength_avg = (
            sum(moat_strength_values) / len(moat_strength_values)
            if moat_strength_values else 0.0
        )

        shared_concern_tags: List[str] = []
        for exp in exposures:
            shared_concern_tags.extend(_safe_json_list(exp.shared_concerns))
        tag_set = sorted(set(shared_concern_tags))

        exposure_strengths = [exp.strength for exp in exposures]
        exposure_avg_strength = (
            sum(exposure_strengths) / len(exposure_strengths)
            if exposure_strengths else 0.0
        )

        categorical = {
            "ticker": norm_ticker,
            "company_name": head.company_name or "",
            "stance": head.stance or "",
            "primary_concern": head.primary_concern or "",
            "staleness_state": head.staleness_state or "",
            "core_debate_lean": getattr(debate, "current_lean", "") if debate else "",
            "durability_cycle_position": getattr(durability, "cycle_position", "") if durability else "",
            "durability_conviction_trend": getattr(durability, "conviction_trend", "") if durability else "",
            "durability_horizon_hint": getattr(durability, "horizon_hint", "") if durability else "",
        }
        numeric = {
            "conviction": float(head.conviction or 0.0),
            "global_confidence": float(head.global_confidence or 0.0),
            "core_debate_confidence": float(getattr(debate, "confidence", 0.0) or 0.0) if debate else 0.0,
            "moat_strength_avg": round(moat_strength_avg, 4),
            "moat_axis_count": float(len(dimensions)),
            "cross_exposure_count": float(len(exposures)),
            "cross_exposure_avg_strength": round(exposure_avg_strength, 4),
        }
        # moat_axes_present is a structural fact about the company, distinct
        # from the concern-tag tag_set above; carried in categorical as a
        # joined string so it stays a typed/interpretable field rather than
        # mixing two different tag vocabularies in one Jaccard-scored set.
        categorical["moat_axes_present"] = ",".join(moat_axes_present)

        text_anchor = _build_company_text_anchor(head, debate, moat_axes_present)
        source_versions = {
            "company_dossier_id": head.id,
            "company_dossier_row_version": head.row_version,
            "dossier_core_debate_version": getattr(debate, "version", None) if debate else None,
        }

        row = await upsert_feature_vector(
            session,
            target_type="company",
            entity_key=norm_ticker,
            categorical=categorical,
            tag_set=tag_set,
            numeric=numeric,
            text_anchor=text_anchor,
            source_versions=source_versions,
            vector_schema=COMPANY_FEATURE_VERSION,
            user_id=head.user_id,
        )
        return row
    except Exception as exc:
        logger.debug(
            "[similarity_feature_builder] build_company_feature_vector failed for %s: %r",
            ticker, exc,
        )
        return None


async def build_company_feature_vectors_for_all(
    session, limit: Optional[int] = None
) -> List[object]:
    """Build T1 feature vectors for every ticker with a company_dossier head row.

    Returns the list of successfully-built ORM rows. Returns [] when
    session is None or on error.
    """
    if session is None:
        return []
    try:
        from sqlalchemy import select
        from app.db.models import CompanyDossier

        stmt = select(CompanyDossier.ticker)
        if limit is not None:
            stmt = stmt.limit(limit)
        tickers = (await session.execute(stmt)).scalars().all()

        results: List[object] = []
        for ticker in tickers:
            built = await build_company_feature_vector(session, ticker)
            if built is not None:
                results.append(built)
        return results
    except Exception as exc:
        logger.debug(
            "[similarity_feature_builder] build_company_feature_vectors_for_all failed: %r",
            exc,
        )
        return []


# ===========================================================================
# T2 — THESIS
# ===========================================================================

def _build_thesis_text_anchor(thesis, debate, divergence_dimensions) -> str:
    ticker = getattr(thesis, "ticker", "")
    stance = getattr(thesis, "directional_stance", "") or "no stated stance"
    lean = getattr(debate, "current_lean", "") if debate is not None else ""
    parts = [f"Thesis snapshot for {ticker}: stance={stance}"]
    if lean:
        parts.append(f"core debate lean={lean}")
    if divergence_dimensions:
        parts.append(f"{len(divergence_dimensions)} divergence(s) from consensus")
    return "; ".join(parts) + "."


async def build_thesis_feature_vector(session, thesis_version_id: str) -> Optional[object]:
    """Build (or refresh) the T2 feature vector for one ThesisVersion row.

    entity_key = the ThesisVersion.id — one feature vector per posited thesis
    snapshot. Returns None when:
      - session is None
      - thesis_version_id does not resolve to a row
      - an unexpected error occurs (logged at debug level)

    Missing core_debate / variant / durability facets do NOT cause a None
    return — a sparse vector is built from the thesis_versions fields alone.
    """
    if session is None:
        return None
    try:
        from sqlalchemy import select
        from app.db.models import ThesisVersion
        from app.db.repositories.dossier_repo import get_debate, get_variant, get_durability
        from app.db.repositories.similarity_repo import upsert_feature_vector

        thesis = (
            await session.execute(
                select(ThesisVersion).where(ThesisVersion.id == thesis_version_id)
            )
        ).scalar_one_or_none()
        if thesis is None:
            logger.debug(
                "[similarity_feature_builder] thesis_version_id=%s not found — nothing to build",
                thesis_version_id,
            )
            return None

        debate = await get_debate(session, thesis.ticker)
        variant = await get_variant(session, thesis.ticker)
        durability = await get_durability(session, thesis.ticker)

        divergences = _safe_json_list(getattr(variant, "divergences", None)) if variant else []
        divergence_dimensions = sorted({
            d.get("dimension", "") for d in divergences
            if isinstance(d, dict) and d.get("dimension")
        })

        key_drivers = _safe_json_list(thesis.key_drivers)
        key_risks = _safe_json_list(thesis.key_risks)

        categorical = {
            "ticker": thesis.ticker,
            "directional_stance": thesis.directional_stance or "",
            "core_debate_lean": getattr(debate, "current_lean", "") if debate else "",
            "durability_cycle_position": getattr(durability, "cycle_position", "") if durability else "",
            "durability_horizon_hint": getattr(durability, "horizon_hint", "") if durability else "",
        }
        tag_set = divergence_dimensions
        numeric = {
            "confidence_score": float(thesis.confidence_score or 0.0),
            "key_drivers_count": float(len(key_drivers)),
            "key_risks_count": float(len(key_risks)),
            "variant_confidence": float(getattr(variant, "confidence", 0.0) or 0.0) if variant else 0.0,
            "core_debate_confidence": float(getattr(debate, "confidence", 0.0) or 0.0) if debate else 0.0,
        }
        text_anchor = _build_thesis_text_anchor(thesis, debate, divergence_dimensions)
        source_versions = {
            "thesis_version_id": thesis.id,
            "thesis_created_at": thesis.created_at.isoformat() if thesis.created_at else "",
            "dossier_variant_version": getattr(variant, "version", None) if variant else None,
        }

        row = await upsert_feature_vector(
            session,
            target_type="thesis",
            entity_key=thesis.id,
            categorical=categorical,
            tag_set=tag_set,
            numeric=numeric,
            text_anchor=text_anchor,
            source_versions=source_versions,
            vector_schema=THESIS_FEATURE_VERSION,
            user_id=thesis.user_id,
        )
        return row
    except Exception as exc:
        logger.debug(
            "[similarity_feature_builder] build_thesis_feature_vector failed for %s: %r",
            thesis_version_id, exc,
        )
        return None


async def build_thesis_feature_vectors_for_all(
    session, limit: Optional[int] = None
) -> List[object]:
    """Build T2 feature vectors for every ThesisVersion row in the system.

    Returns the list of successfully-built ORM rows. Returns [] when
    session is None or on error.
    """
    if session is None:
        return []
    try:
        from sqlalchemy import select
        from app.db.models import ThesisVersion

        stmt = select(ThesisVersion.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        ids = (await session.execute(stmt)).scalars().all()

        results: List[object] = []
        for thesis_id in ids:
            built = await build_thesis_feature_vector(session, thesis_id)
            if built is not None:
                results.append(built)
        return results
    except Exception as exc:
        logger.debug(
            "[similarity_feature_builder] build_thesis_feature_vectors_for_all failed: %r",
            exc,
        )
        return []
