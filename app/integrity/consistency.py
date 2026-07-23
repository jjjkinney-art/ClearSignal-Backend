"""Cross-section content-integrity validator (Sprint 1B, issues #6, #7, #8).

``validate_thesis_integrity(thesis)`` reconciles the valuation fields, checks
economic-materiality language against evidence, checks user-question alignment,
and flags stale precise figures.  It FAILS CLOSED: on a hard contradiction it
returns a qualification (suppress/qualify the offending field) instead of letting
invented precision reach the frontend.

Operates on a plain dict (or a model dumped to dict) and is tolerant of missing
fields, so it can validate both live responses and test fixtures.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .valuation_state import (
    ValuationState, from_regime, from_stance, from_prose, reconcile, label_for,
)
from .memory_consistency import validate_memory

# Severities
HIGH = "high"      # hard contradiction — fail closed
MEDIUM = "medium"  # qualify / caveat
LOW = "low"        # advisory


@dataclass
class IntegrityViolation:
    code: str
    severity: str
    field: str
    message: str


@dataclass
class IntegrityResult:
    ok: bool
    state: str                                   # reconciled ValuationState value
    violations: List[IntegrityViolation] = field(default_factory=list)
    qualifications: Dict[str, Any] = field(default_factory=dict)

    def hard(self) -> List[IntegrityViolation]:
        return [v for v in self.violations if v.severity == HIGH]


def _get(d: Dict[str, Any], *keys: str, default: str = "") -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _as_text(*vals: Any) -> str:
    out = []
    for v in vals:
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, (list, tuple)):
            out.extend(str(x) for x in v)
    return " \n ".join(out)


# Numbers that read as precise current facts.
_PRECISE_NUM = re.compile(r"(\$\s?\d[\d,\.]*\s?[bmk]?|\d[\d,\.]*\s?%|\d[\d,\.]*\s?x)\b", re.I)
_STALE_MARKERS = (
    "limited recent", "no recent earnings", "stale", "dated evidence",
    "limited recent earnings", "outdated", "as of an older", "coverage gap",
)
_ASOF_MARKERS = ("as of", "as-of", "reported ", "q1", "q2", "q3", "q4", "fy20", "fiscal")

# Economic-materiality phrases that assert material economic contribution.
_MATERIALITY_PHRASES = (
    "recurring-revenue engine", "recurring revenue engine", "revenue cushion",
    "meaningful revenue", "thesis offset", "offsets the thesis", "durable revenue stream",
    "material revenue", "revenue backstop",
)
_SWITCHING_PHRASES = ("switching cost", "ecosystem lock", "lock-in", "stickiness")


def _valuation(thesis: Dict[str, Any]) -> IntegrityResult:
    regime = _get(thesis, "expectation_regime", "valuation_regime")
    stance = _get(thesis, "valuation_stance")
    prose = _as_text(
        _get(thesis, "valuation_view", "overall"),
        _get(thesis, "core_takeaway", "conclusion"),
        _get(thesis, "verdict_reasoning"),
    )
    s_regime = from_regime(regime)
    s_stance = from_stance(stance)
    s_prose = from_prose(prose)
    state, contradiction = reconcile(s_regime, s_stance, s_prose)

    res = IntegrityResult(ok=True, state=state.value)
    if contradiction:
        res.ok = False
        res.violations.append(IntegrityViolation(
            code="valuation_contradiction", severity=HIGH, field="expectation_regime",
            message=(
                f"valuation fields disagree — regime={s_regime.value}, "
                f"stance={s_stance.value}, prose={s_prose.value}. Price label "
                "suppressed to avoid a cheap/rich contradiction on the frontend."
            ),
        ))
        # Fail closed: the price chip becomes the undetermined label.
        res.qualifications["expectation_regime"] = ValuationState.UNDETERMINED.value
        res.qualifications["price_label"] = label_for(ValuationState.UNDETERMINED)
    else:
        res.qualifications["price_label"] = label_for(state)
    return res


def _materiality(thesis: Dict[str, Any], res: IntegrityResult) -> None:
    text = _as_text(
        _get(thesis, "bull_case"), _get(thesis, "core_takeaway", "conclusion"),
        _get(thesis, "direct_answer"),
    ).lower()
    for phrase in _MATERIALITY_PHRASES:
        if phrase in text:
            # Require a quantitative anchor near the claim, else it's unsupported.
            if not _PRECISE_NUM.search(text):
                res.violations.append(IntegrityViolation(
                    code="unsupported_materiality", severity=MEDIUM, field="bull_case",
                    message=(
                        f"'{phrase}' asserts material economic contribution without a "
                        "quantitative anchor; qualify or drop the materiality claim"
                    ),
                ))
            # Switching costs are not directly-reported recurring revenue.
            if "recurring" in phrase and any(sw in text for sw in _SWITCHING_PHRASES):
                res.violations.append(IntegrityViolation(
                    code="switching_vs_recurring", severity=MEDIUM, field="bull_case",
                    message=(
                        "'recurring revenue' language is backed by switching-cost / "
                        "ecosystem stickiness, not directly-reported recurring revenue"
                    ),
                ))
            break


def _stale_precision(thesis: Dict[str, Any], res: IntegrityResult) -> None:
    coverage = _as_text(
        _get(thesis, "evidence_coverage", "coverage_note", "limitations"),
        _get(thesis, "data_quality_note"),
    ).lower()
    if not any(m in coverage for m in _STALE_MARKERS):
        return
    prose = _as_text(
        _get(thesis, "direct_answer"), _get(thesis, "core_takeaway", "conclusion"),
        _get(thesis, "valuation_view", "overall"),
    )
    if _PRECISE_NUM.search(prose) and not any(m in prose.lower() for m in _ASOF_MARKERS):
        res.violations.append(IntegrityViolation(
            code="stale_precision", severity=MEDIUM, field="direct_answer",
            message=(
                "evidence coverage is flagged stale/limited but precise current "
                "figures are presented without an as-of date or qualifier"
            ),
        ))
        res.qualifications["stale_precision_caveat"] = (
            "Figures reflect the latest available evidence, which is limited/dated — "
            "treat precise values as indicative, not current."
        )


def _question_alignment(thesis: Dict[str, Any], question: Optional[str],
                        res: IntegrityResult) -> None:
    if not question:
        return
    answer = str(_get(thesis, "direct_answer")).lower()
    if not answer:
        return
    ticker = str(_get(thesis, "ticker", "company")).upper()
    # If the user asked about a specific ticker/company, the answer should mention it.
    q = question.lower()
    if ticker and ticker.lower() not in answer and (
        _get(thesis, "company") and str(_get(thesis, "company")).lower() not in answer
    ) and ticker.lower() in q:
        res.violations.append(IntegrityViolation(
            code="question_alignment", severity=LOW, field="direct_answer",
            message="direct_answer does not reference the company the question named",
        ))


def _structured_claims_and_thresholds(thesis: Dict[str, Any], res: IntegrityResult) -> None:
    """Sprint 1C defense-in-depth: re-validate the STRUCTURED companion payloads
    (quantitative_claims / decision_thresholds) if present.  This is the final
    safety net — source-level generation (claim_extraction/threshold_parsing)
    should already have produced clean data, but the boundary re-checks so a
    generator-level bug can never silently reach the frontend.  No-ops when the
    thesis predates Sprint 1C (fields absent) — Sprint 1B behavior is unchanged.
    """
    ticker = str(_get(thesis, "ticker", "company") or "").strip().upper()

    for claim in thesis.get("quantitative_claims") or []:
        if not isinstance(claim, dict):
            continue
        c_ticker = str(claim.get("ticker") or "").strip().upper()
        if ticker and c_ticker and c_ticker != ticker:
            res.violations.append(IntegrityViolation(
                code="claim_ticker_leak", severity=HIGH, field="quantitative_claims",
                message=f"claim ticker '{c_ticker}' does not match thesis ticker '{ticker}'",
            ))
        prov = claim.get("provenance")
        if prov in ("estimated", "scenario", "heuristic") and not (
            claim.get("assumptions") or claim.get("as_of") or claim.get("confidence")
        ):
            res.violations.append(IntegrityViolation(
                code="unqualified_structured_claim", severity=MEDIUM, field="quantitative_claims",
                message=f"{prov} claim '{claim.get('value_text')}' lacks a qualifier",
            ))
        if claim.get("stale") and not claim.get("as_of"):
            res.violations.append(IntegrityViolation(
                code="unqualified_stale_claim", severity=MEDIUM, field="quantitative_claims",
                message=f"stale claim '{claim.get('value_text')}' has no as-of date",
            ))

    for band in thesis.get("decision_thresholds") or []:
        if not isinstance(band, dict) or band.get("unavailable"):
            continue  # explicit unavailable is the safe, expected fail-closed state
        bull, bear = band.get("bull_boundary"), band.get("bear_boundary")
        direction = band.get("direction")
        if bull is None or bear is None or direction not in ("higher_is_better", "lower_is_better"):
            continue
        incoherent = (
            (direction == "lower_is_better" and bull >= bear) or
            (direction == "higher_is_better" and bull <= bear)
        )
        if incoherent:
            res.violations.append(IntegrityViolation(
                code="threshold_contradiction", severity=HIGH, field="decision_thresholds",
                message=(
                    f"shipped threshold band for '{band.get('metric')}' is incoherent "
                    f"(direction={direction}, bull={bull}, bear={bear})"
                ),
            ))


def validate_thesis_integrity(
    thesis: Dict[str, Any], *, question: Optional[str] = None,
) -> IntegrityResult:
    """Run the full cross-section integrity check.  Never raises."""
    try:
        res = _valuation(thesis)
        _materiality(thesis, res)
        _stale_precision(thesis, res)
        _question_alignment(thesis, question, res)
        _structured_claims_and_thresholds(thesis, res)

        mem_violations = validate_memory(
            _get(thesis, "memory_context_data", default=None) or None,
            thesis_ticker=_get(thesis, "ticker", "company") or None,
            current_stance=_get(thesis, "stance", "final_verdict", "directional_stance") or None,
        )
        for m in mem_violations:
            res.violations.append(IntegrityViolation(
                code="memory_inconsistency", severity=HIGH, field="memory_context_data",
                message=m,
            ))
            res.ok = False

        # ok is false if any HIGH violation exists.
        if res.hard():
            res.ok = False
        return res
    except Exception as exc:  # fail OPEN on internal error — never break the response
        return IntegrityResult(
            ok=True, state=ValuationState.UNDETERMINED.value,
            violations=[IntegrityViolation(
                code="validator_error", severity=LOW, field="",
                message=f"integrity validator errored (non-fatal): {exc!r}",
            )],
        )
