"""Point-in-time replay grading for proactive, thesis-aware intelligence.

Each case joins one frozen synthetic thesis to one public event and a frozen
expected decision.  The evaluator never decides event relevance from market
price movement and never admits alerts generated before the event was public.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .intelligence_benchmark import BenchmarkContractError


class ThesisImpact(str, Enum):
    STRENGTHENED = "strengthened"
    WEAKENED = "weakened"
    UNCHANGED = "unchanged"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EventMateriality(str, Enum):
    MATERIAL = "material"
    IMMATERIAL = "immaterial"


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise BenchmarkContractError(f"{field} is required")
    return result


def _instant(value: Any, field: str) -> datetime:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BenchmarkContractError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BenchmarkContractError(f"{field} must include a timezone")
    return parsed


def _number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkContractError(f"{field} must be numeric") from exc
    if not isfinite(result):
        raise BenchmarkContractError(f"{field} must be finite")
    return result


def _ids(values: Sequence[Any], field: str) -> Tuple[str, ...]:
    result = tuple(sorted(_text(item, field) for item in values))
    if len(set(result)) != len(result):
        raise BenchmarkContractError(f"{field} must be unique")
    return result


@dataclass(frozen=True)
class ThesisAssumption:
    assumption_id: str
    material: bool

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ThesisAssumption":
        material = value.get("material")
        if not isinstance(material, bool):
            raise BenchmarkContractError("assumption material must be boolean")
        return ThesisAssumption(
            assumption_id=_text(value.get("assumption_id"), "assumption_id"),
            material=material,
        )


@dataclass(frozen=True)
class SyntheticThesis:
    thesis_id: str
    owner_ref: str
    ticker: str
    recorded_at: str
    assumptions: Tuple[ThesisAssumption, ...]

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "SyntheticThesis":
        owner_ref = _text(value.get("owner_ref"), "owner_ref")
        if not owner_ref.startswith("synthetic:"):
            raise BenchmarkContractError("proactive replay requires a synthetic owner_ref")
        raw = value.get("assumptions", ())
        if not isinstance(raw, (list, tuple)) or not raw:
            raise BenchmarkContractError("synthetic thesis requires assumptions")
        assumptions = tuple(ThesisAssumption.from_dict(item) for item in raw)
        if len({item.assumption_id for item in assumptions}) != len(assumptions):
            raise BenchmarkContractError("assumption ids must be unique")
        recorded = _instant(value.get("recorded_at"), "recorded_at")
        return SyntheticThesis(
            thesis_id=_text(value.get("thesis_id"), "thesis_id"),
            owner_ref=owner_ref,
            ticker=_text(value.get("ticker"), "ticker").upper(),
            recorded_at=recorded.isoformat(),
            assumptions=tuple(sorted(assumptions, key=lambda item: item.assumption_id)),
        )


@dataclass(frozen=True)
class PublicEvent:
    event_id: str
    ticker: str
    source_id: str
    published_at: str
    materiality: EventMateriality

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "PublicEvent":
        try:
            materiality = EventMateriality(str(value.get("materiality", "")))
        except ValueError as exc:
            raise BenchmarkContractError("invalid event materiality") from exc
        published = _instant(value.get("published_at"), "published_at")
        return PublicEvent(
            event_id=_text(value.get("event_id"), "event_id"),
            ticker=_text(value.get("ticker"), "ticker").upper(),
            source_id=_text(value.get("source_id"), "source_id"),
            published_at=published.isoformat(), materiality=materiality,
        )


@dataclass(frozen=True)
class ExpectedNotice:
    relevant: bool
    impact: ThesisImpact
    assumption_ids: Tuple[str, ...]
    confidence_delta_min: float
    confidence_delta_max: float
    maximum_delay_hours: float

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ExpectedNotice":
        relevant = value.get("relevant")
        if not isinstance(relevant, bool):
            raise BenchmarkContractError("expected relevant must be boolean")
        try:
            impact = ThesisImpact(str(value.get("impact", "")))
        except ValueError as exc:
            raise BenchmarkContractError("invalid expected thesis impact") from exc
        minimum = _number(value.get("confidence_delta_min", 0), "confidence_delta_min")
        maximum = _number(value.get("confidence_delta_max", 0), "confidence_delta_max")
        if minimum > maximum or minimum < -1 or maximum > 1:
            raise BenchmarkContractError("invalid expected confidence-delta range")
        if impact == ThesisImpact.STRENGTHENED and minimum < 0:
            raise BenchmarkContractError("strengthened impact cannot expect a negative confidence change")
        if impact == ThesisImpact.WEAKENED and maximum > 0:
            raise BenchmarkContractError("weakened impact cannot expect a positive confidence change")
        if impact in {ThesisImpact.UNCHANGED, ThesisImpact.INSUFFICIENT_EVIDENCE} and not minimum <= 0 <= maximum:
            raise BenchmarkContractError("unchanged or insufficient impact must allow zero confidence change")
        delay = _number(value.get("maximum_delay_hours", 24), "maximum_delay_hours")
        if delay < 0:
            raise BenchmarkContractError("maximum_delay_hours cannot be negative")
        assumptions = _ids(value.get("assumption_ids", ()), "assumption_ids")
        if not relevant and (assumptions or impact != ThesisImpact.UNCHANGED or minimum != 0 or maximum != 0):
            raise BenchmarkContractError("irrelevant events must expect no linkage or thesis change")
        return ExpectedNotice(relevant, impact, assumptions, minimum, maximum, delay)


@dataclass(frozen=True)
class ObservedAlert:
    alert_id: str
    owner_ref: str
    ticker: str
    detected_at: str
    source_id: str
    relevant: bool
    impact: ThesisImpact
    assumption_ids: Tuple[str, ...]
    confidence_delta: float

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ObservedAlert":
        relevant = value.get("relevant")
        if not isinstance(relevant, bool):
            raise BenchmarkContractError("alert relevant must be boolean")
        try:
            impact = ThesisImpact(str(value.get("impact", "")))
        except ValueError as exc:
            raise BenchmarkContractError("invalid observed thesis impact") from exc
        delta = _number(value.get("confidence_delta", 0), "confidence_delta")
        if not -1 <= delta <= 1:
            raise BenchmarkContractError("confidence_delta must be between -1 and 1")
        detected = _instant(value.get("detected_at"), "detected_at")
        return ObservedAlert(
            alert_id=_text(value.get("alert_id"), "alert_id"),
            owner_ref=_text(value.get("owner_ref"), "owner_ref"),
            ticker=_text(value.get("ticker"), "ticker").upper(),
            detected_at=detected.isoformat(),
            source_id=_text(value.get("source_id"), "source_id"),
            relevant=relevant, impact=impact,
            assumption_ids=_ids(value.get("assumption_ids", ()), "assumption_ids"),
            confidence_delta=delta,
        )


@dataclass(frozen=True)
class ReplayCase:
    replay_id: str
    thesis: SyntheticThesis
    event: PublicEvent
    expected: ExpectedNotice
    replay_end_at: str
    alerts: Tuple[ObservedAlert, ...]

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ReplayCase":
        thesis = SyntheticThesis.from_dict(value.get("thesis", {}))
        event = PublicEvent.from_dict(value.get("event", {}))
        expected = ExpectedNotice.from_dict(value.get("expected", {}))
        end = _instant(value.get("replay_end_at"), "replay_end_at")
        published = _instant(event.published_at, "published_at")
        recorded = _instant(thesis.recorded_at, "recorded_at")
        if thesis.ticker != event.ticker:
            raise BenchmarkContractError("thesis and event ticker must match")
        if recorded >= published:
            raise BenchmarkContractError("synthetic thesis must predate the public event")
        if end < published:
            raise BenchmarkContractError("replay end cannot precede event publication")
        known = {item.assumption_id for item in thesis.assumptions}
        if not set(expected.assumption_ids).issubset(known):
            raise BenchmarkContractError("expected notice references unknown thesis assumptions")
        material = {item.assumption_id for item in thesis.assumptions if item.material}
        if not set(expected.assumption_ids).issubset(material):
            raise BenchmarkContractError("expected notice may link only material thesis assumptions")
        raw_alerts = value.get("alerts", ())
        if not isinstance(raw_alerts, (list, tuple)):
            raise BenchmarkContractError("alerts must be a list")
        alerts = tuple(ObservedAlert.from_dict(item) for item in raw_alerts)
        if len({item.alert_id for item in alerts}) != len(alerts):
            raise BenchmarkContractError("alert ids must be unique")
        return ReplayCase(
            replay_id=_text(value.get("replay_id"), "replay_id"),
            thesis=thesis, event=event, expected=expected,
            replay_end_at=end.isoformat(),
            alerts=tuple(sorted(alerts, key=lambda item: item.alert_id)),
        )


@dataclass(frozen=True)
class ReplayFinding:
    code: str
    replay_id: str
    message: str
    critical: bool


@dataclass(frozen=True)
class ReplayCaseResult:
    replay_id: str
    expected_alert: bool
    alert_emitted: bool
    correct_relevance: bool
    correct_impact: bool
    correct_source: bool
    timely: bool
    assumption_recall: Optional[float]
    assumption_precision: Optional[float]
    confidence_change_valid: bool
    duplicate_alerts: int
    safe: bool
    finding_codes: Tuple[str, ...]


@dataclass(frozen=True)
class ProactiveReplayScorecard:
    cases: Tuple[ReplayCaseResult, ...]
    findings: Tuple[ReplayFinding, ...]
    case_count: int
    relevant_event_count: int
    detected_relevant_event_count: int
    detection_recall: Optional[float]
    alert_precision: Optional[float]
    thesis_impact_accuracy: Optional[float]
    timely_alert_rate: Optional[float]
    noise_alert_count: int
    privacy_exposure_count: int
    lookahead_leakage_count: int
    critical_failure_count: int
    fully_evaluated: bool
    safe_to_expand: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def score_proactive_replays(cases: Sequence[ReplayCase]) -> ProactiveReplayScorecard:
    ids = [item.replay_id for item in cases]
    if len(set(ids)) != len(ids):
        raise BenchmarkContractError("replay ids must be unique")
    findings = []
    results = []
    relevant_total = detected_relevant = emitted_total = correct_alerts = 0
    impact_denominator = impact_correct = timely_denominator = timely_count = 0
    noise = privacy = leakage = 0
    for case in sorted(cases, key=lambda item: item.replay_id):
        expected = case.expected
        relevant_total += expected.relevant
        emitted_total += bool(case.alerts)
        case_findings = []

        def add(code: str, message: str, critical: bool = True) -> None:
            item = ReplayFinding(code, case.replay_id, message, critical)
            findings.append(item)
            case_findings.append(item)

        if len(case.alerts) > 1:
            duplicates = len(case.alerts) - 1
            noise += duplicates
            add("duplicate_alerts", "one event produced duplicate alerts")
        else:
            duplicates = 0

        alert = case.alerts[0] if case.alerts else None
        correct_relevance = correct_impact = correct_source = timely = False
        confidence_valid = False
        assumption_recall = assumption_precision = None
        if alert is None:
            if expected.relevant:
                add("material_event_missed", "relevant event produced no proactive alert")
        else:
            published = _instant(case.event.published_at, "published_at")
            detected = _instant(alert.detected_at, "detected_at")
            replay_end = _instant(case.replay_end_at, "replay_end_at")
            if detected < published:
                leakage += 1
                add("lookahead_alert", "alert was emitted before the event became public")
            if detected > replay_end:
                add("alert_outside_replay_window", "alert was emitted after the replay window")
            if alert.owner_ref != case.thesis.owner_ref:
                privacy += 1
                add("owner_scope_violation", "alert was emitted for the wrong synthetic owner")
            if alert.ticker != case.event.ticker:
                add("ticker_scope_violation", "alert ticker does not match the event")
            correct_source = alert.source_id == case.event.source_id
            if not correct_source:
                add("source_binding_error", "alert is not bound to the frozen event source")
            correct_relevance = alert.relevant == expected.relevant
            if not correct_relevance:
                add("relevance_misclassified", "alert relevance does not match the frozen judgment")
            if not expected.relevant:
                noise += 1
                add("noise_alert", "immaterial or irrelevant event produced an alert")
            else:
                detected_relevant += 1
                impact_denominator += 1
                timely_denominator += 1
                correct_impact = alert.impact == expected.impact
                impact_correct += correct_impact
                if not correct_impact:
                    add("thesis_impact_error", "alert assigned the wrong thesis impact")
                delay = (detected - published).total_seconds() / 3600
                timely = 0 <= delay <= expected.maximum_delay_hours
                timely_count += timely
                if not timely:
                    add("late_alert", "alert exceeded the frozen usefulness window")
                expected_assumptions = set(expected.assumption_ids)
                observed_assumptions = set(alert.assumption_ids)
                assumption_recall = (
                    len(expected_assumptions & observed_assumptions) / len(expected_assumptions)
                    if expected_assumptions else 1.0
                )
                assumption_precision = (
                    len(expected_assumptions & observed_assumptions) / len(observed_assumptions)
                    if observed_assumptions else (1.0 if not expected_assumptions else 0.0)
                )
                if assumption_recall < 1.0:
                    add("assumption_link_missed", "alert did not link every affected thesis assumption")
                if assumption_precision < 1.0:
                    add("unrelated_assumption_linked", "alert linked an unaffected thesis assumption")
            confidence_valid = (
                expected.confidence_delta_min
                <= alert.confidence_delta
                <= expected.confidence_delta_max
            )
            if not confidence_valid:
                add("confidence_change_error", "confidence change is outside the frozen range")
            known = {item.assumption_id for item in case.thesis.assumptions}
            if not set(alert.assumption_ids).issubset(known):
                add("unknown_assumption_linked", "alert references an unknown thesis assumption")
            alert_correct = (
                expected.relevant and correct_relevance and correct_impact
                and correct_source and confidence_valid
            )
            correct_alerts += alert_correct

        safe = not any(item.critical for item in case_findings)
        results.append(ReplayCaseResult(
            replay_id=case.replay_id, expected_alert=expected.relevant,
            alert_emitted=alert is not None, correct_relevance=correct_relevance,
            correct_impact=correct_impact, correct_source=correct_source,
            timely=timely, assumption_recall=assumption_recall,
            assumption_precision=assumption_precision,
            confidence_change_valid=confidence_valid,
            duplicate_alerts=duplicates, safe=safe,
            finding_codes=tuple(item.code for item in case_findings),
        ))

    def ratio(numerator: int, denominator: int) -> Optional[float]:
        return numerator / denominator if denominator else None

    critical = sum(item.critical for item in findings)
    return ProactiveReplayScorecard(
        cases=tuple(results), findings=tuple(findings), case_count=len(cases),
        relevant_event_count=relevant_total,
        detected_relevant_event_count=detected_relevant,
        detection_recall=ratio(detected_relevant, relevant_total),
        alert_precision=ratio(correct_alerts, emitted_total),
        thesis_impact_accuracy=ratio(impact_correct, impact_denominator),
        timely_alert_rate=ratio(timely_count, timely_denominator),
        noise_alert_count=noise, privacy_exposure_count=privacy,
        lookahead_leakage_count=leakage, critical_failure_count=critical,
        fully_evaluated=bool(cases),
        safe_to_expand=bool(cases) and critical == 0 and privacy == 0 and leakage == 0,
    )


def score_payload(payload: Mapping[str, Any]) -> ProactiveReplayScorecard:
    return score_proactive_replays([
        ReplayCase.from_dict(item) for item in payload.get("cases", ())
    ])
