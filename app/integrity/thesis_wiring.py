"""Wires structured claims/thresholds into the thesis-synthesis output (Sprint 1C).

``attach_structured_content()`` is called from inside
``thesis_synthesizer.synthesize_thesis`` right before it returns — i.e. at the
generation SOURCE, with access to the full evidence pool (for freshness) and
the per-agent claims already extracted upstream (valuation/macro/risk agents).

Kept as a small, pure, independently-testable function (not inlined in the
4000+ line synthesizer) so this integration can be unit-tested without
invoking the LLM.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from .canonicalization import canonicalize_claims
from .claim_extraction import extract_claims
from .threshold_parsing import build_decision_thresholds

logger = logging.getLogger(__name__)

# thesis text field -> freshness dimension (see freshness_analyzer.py)
_FIELD_DIMENSION = {
    "direct_answer": "earnings",
    "bull_thesis": "estimates",
    "bear_thesis": "estimates",
    "valuation_view": "valuation",
    "macro_sensitivity": "macro",
    "conclusion": "earnings",
}


def attach_structured_content(
    thesis: Any,
    *,
    ticker: str,
    evidence: Optional[List[Any]] = None,
    freshness: Any = None,
    agent_claims: Optional[Sequence[Dict[str, Any]]] = None,
) -> None:
    """Mutate ``thesis`` in place: set quantitative_claims, decision_thresholds,
    and claim_provenance_summary.  Never raises — degrades to empty structures
    on any internal error so synthesis is never broken by this step.

    Parameters
    ----------
    thesis        : the InvestmentThesis being finalized (must already have
                     direct_answer/bull_thesis/bear_thesis/valuation_view/
                     macro_sensitivity/conclusion/what_changed/threshold_zones
                     populated — call this LAST, right before return).
    ticker        : company ticker, for cross-ticker isolation tagging.
    evidence      : full evidence pool; used to compute freshness if
                     ``freshness`` is not already supplied.
    freshness     : optional pre-computed FreshnessProfile (avoids recomputing
                     it if the caller already has one, e.g. thesis_synthesizer's
                     own ``_fp``).
    agent_claims  : claim dicts already produced upstream by the valuation/
                     macro/risk agents (their own ``quantitative_claims``),
                     merged in rather than re-derived from prose.
    """
    try:
        if freshness is None and evidence is not None:
            from ..services.freshness_analyzer import analyze_evidence_freshness
            freshness = analyze_evidence_freshness(evidence)

        # Sprint 3A — sub-stage timings for the structured-content pipeline.
        # `stage` is a no-op context manager when no request trace is active.
        from ..observability import stage as _obs_stage

        claims: List[Dict[str, Any]] = list(agent_claims or [])

        # Claim extraction and provenance classification happen together inside
        # extract_claims(), so they are timed as one span rather than pretending
        # to separate two passes that do not exist.
        with _obs_stage("claim_extraction_and_provenance"):
            for field_name, dimension in _FIELD_DIMENSION.items():
                text = getattr(thesis, field_name, None)
                if isinstance(text, list):
                    text = " ".join(str(t) for t in text)
                if not text:
                    continue
                extracted = extract_claims(
                    text, ticker=ticker, metric=field_name,
                    freshness=freshness, dimension=dimension,
                )
                claims.extend(c.to_dict() for c in extracted)

            what_changed = getattr(thesis, "what_changed", None)
            if what_changed:
                text = " ".join(str(t) for t in what_changed)
                extracted = extract_claims(
                    text, ticker=ticker, metric="what_changed",
                    freshness=freshness, dimension="earnings",
                )
                claims.extend(c.to_dict() for c in extracted)

        as_of = None
        if freshness is not None:
            dom = getattr(freshness, "dominant_stale_dimension", None)
            if dom:
                dim = getattr(freshness, dom, None)
                age = getattr(dim, "age_days", None) if dim else None
                as_of = f"~{age}d old" if age is not None else None

        zones = getattr(thesis, "threshold_zones", None) or []
        with _obs_stage("threshold_parsing", zone_count=len(zones)):
            thresholds = build_decision_thresholds(
                zones, ticker=ticker, freshness_as_of=as_of,
            )

        # Sprint 2B — collapse semantically identical claims (the same figure
        # extracted from an agent's `overall` prose and again from one of its
        # signals) before they reach the response. Runs after extraction and
        # provenance classification so the surviving claim is the most complete
        # member of its group.
        with _obs_stage("canonicalization", claims_in=len(claims)):
            claims = canonicalize_claims(claims)

        summary: Dict[str, int] = {}
        for c in claims:
            prov = c.get("provenance", "heuristic")
            summary[prov] = summary.get(prov, 0) + 1

        if hasattr(thesis, "quantitative_claims"):
            thesis.quantitative_claims = claims
        if hasattr(thesis, "decision_thresholds"):
            thesis.decision_thresholds = thresholds
        if hasattr(thesis, "claim_provenance_summary"):
            thesis.claim_provenance_summary = summary

    except Exception as exc:
        logger.warning(
            "[integrity] attach_structured_content failed for %s (non-fatal): %r",
            ticker, exc,
        )
        for attr, default in (
            ("quantitative_claims", []),
            ("decision_thresholds", []),
            ("claim_provenance_summary", {}),
        ):
            if hasattr(thesis, attr):
                try:
                    setattr(thesis, attr, default)
                except Exception:
                    pass
