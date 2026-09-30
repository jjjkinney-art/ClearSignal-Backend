"""Offline A/B evaluation for account-owned research memory.

The contract compares matched control and treatment runs while keeping private
research out of benchmark artifacts.  Fixtures contain opaque record IDs and
labels only; synthetic data is the default and consented data requires an
explicit consent reference.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .intelligence_benchmark import BenchmarkContractError


class FixtureDataClass(str, Enum):
    SYNTHETIC = "synthetic"
    CONSENTED_BENCHMARK = "consented_benchmark"


class MemoryState(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    DELETED = "deleted"


class Arm(str, Enum):
    CONTROL = "control"
    TREATMENT = "treatment"


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise BenchmarkContractError(f"{field} is required")
    return result


def _aware_iso(value: Any, field: str) -> str:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BenchmarkContractError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BenchmarkContractError(f"{field} must include a timezone")
    return text


def _ratio(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkContractError(f"{field} must be a ratio") from exc
    if not isfinite(result) or not 0.0 <= result <= 1.0:
        raise BenchmarkContractError(f"{field} must be between 0 and 1")
    return result


def _ids(values: Sequence[Any], field: str) -> Tuple[str, ...]:
    result = tuple(sorted(_text(item, field) for item in values))
    if len(set(result)) != len(result):
        raise BenchmarkContractError(f"{field} must be unique")
    return result


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    owner_ref: str
    ticker: str
    recorded_at: str
    state: MemoryState

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "MemoryRecord":
        try:
            state = MemoryState(str(value.get("state", "")))
        except ValueError as exc:
            raise BenchmarkContractError("invalid memory state") from exc
        return MemoryRecord(
            memory_id=_text(value.get("memory_id"), "memory_id"),
            owner_ref=_text(value.get("owner_ref"), "owner_ref"),
            ticker=_text(value.get("ticker"), "ticker").upper(),
            recorded_at=_aware_iso(value.get("recorded_at"), "recorded_at"),
            state=state,
        )


@dataclass(frozen=True)
class MemoryFixture:
    fixture_id: str
    case_id: str
    owner_ref: str
    ticker: str
    as_of: str
    data_class: FixtureDataClass
    consent_reference: Optional[str]
    records: Tuple[MemoryRecord, ...]
    expected_relevant_ids: Tuple[str, ...]

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "MemoryFixture":
        try:
            data_class = FixtureDataClass(str(value.get("data_class", "synthetic")))
        except ValueError as exc:
            raise BenchmarkContractError("invalid fixture data_class") from exc
        consent_reference = str(value.get("consent_reference", "")).strip() or None
        if data_class == FixtureDataClass.CONSENTED_BENCHMARK and not consent_reference:
            raise BenchmarkContractError("consented benchmark data requires consent_reference")
        if data_class == FixtureDataClass.SYNTHETIC and consent_reference:
            raise BenchmarkContractError("synthetic fixtures cannot claim a consent_reference")
        raw_records = value.get("records", ())
        if not isinstance(raw_records, (list, tuple)):
            raise BenchmarkContractError("records must be a list")
        records = tuple(MemoryRecord.from_dict(item) for item in raw_records)
        if len({item.memory_id for item in records}) != len(records):
            raise BenchmarkContractError("memory ids must be unique")
        expected = _ids(value.get("expected_relevant_ids", ()), "expected_relevant_ids")
        by_id = {item.memory_id: item for item in records}
        owner_ref = _text(value.get("owner_ref"), "owner_ref")
        ticker = _text(value.get("ticker"), "ticker").upper()
        as_of = _aware_iso(value.get("as_of"), "as_of")
        boundary = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if any(
            datetime.fromisoformat(item.recorded_at.replace("Z", "+00:00")) > boundary
            for item in records
        ):
            raise BenchmarkContractError("memory record cannot postdate the A/B as-of boundary")
        for memory_id in expected:
            record = by_id.get(memory_id)
            if record is None:
                raise BenchmarkContractError("expected relevant memory is not registered")
            if record.owner_ref != owner_ref or record.ticker != ticker:
                raise BenchmarkContractError("expected memory must belong to the fixture owner and ticker")
            if record.state != MemoryState.ACTIVE:
                raise BenchmarkContractError("expected relevant memory must be active")
        return MemoryFixture(
            fixture_id=_text(value.get("fixture_id"), "fixture_id"),
            case_id=_text(value.get("case_id"), "case_id"),
            owner_ref=owner_ref, ticker=ticker,
            as_of=as_of,
            data_class=data_class, consent_reference=consent_reference,
            records=tuple(sorted(records, key=lambda item: item.memory_id)),
            expected_relevant_ids=expected,
        )


@dataclass(frozen=True)
class MemoryRun:
    run_id: str
    arm: Arm
    memory_enabled: bool
    case_id: str
    question_id: str
    source_snapshot_id: str
    build_commit: str
    model_id: str
    prompt_version: str
    retrieval_version: str
    analytical_quality: float
    factual_integrity: float
    citation_binding: float
    recalled_memory_ids: Tuple[str, ...]
    applied_memory_ids: Tuple[str, ...]
    unsupported_personalization_claims: int

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "MemoryRun":
        try:
            arm = Arm(str(value.get("arm", "")))
        except ValueError as exc:
            raise BenchmarkContractError("arm must be control or treatment") from exc
        recalled = _ids(value.get("recalled_memory_ids", ()), "recalled_memory_ids")
        applied = _ids(value.get("applied_memory_ids", ()), "applied_memory_ids")
        if not set(applied).issubset(recalled):
            raise BenchmarkContractError("applied memory must first be recalled")
        unsupported = value.get("unsupported_personalization_claims", 0)
        if isinstance(unsupported, bool) or not isinstance(unsupported, int) or unsupported < 0:
            raise BenchmarkContractError("unsupported_personalization_claims must be a non-negative integer")
        memory_enabled = value.get("memory_enabled")
        if not isinstance(memory_enabled, bool):
            raise BenchmarkContractError("memory_enabled must be boolean")
        return MemoryRun(
            run_id=_text(value.get("run_id"), "run_id"), arm=arm,
            memory_enabled=memory_enabled,
            case_id=_text(value.get("case_id"), "case_id"),
            question_id=_text(value.get("question_id"), "question_id"),
            source_snapshot_id=_text(value.get("source_snapshot_id"), "source_snapshot_id"),
            build_commit=_text(value.get("build_commit"), "build_commit"),
            model_id=_text(value.get("model_id"), "model_id"),
            prompt_version=_text(value.get("prompt_version"), "prompt_version"),
            retrieval_version=_text(value.get("retrieval_version"), "retrieval_version"),
            analytical_quality=_ratio(value.get("analytical_quality"), "analytical_quality"),
            factual_integrity=_ratio(value.get("factual_integrity"), "factual_integrity"),
            citation_binding=_ratio(value.get("citation_binding"), "citation_binding"),
            recalled_memory_ids=recalled, applied_memory_ids=applied,
            unsupported_personalization_claims=unsupported,
        )

    @property
    def match_key(self) -> Tuple[str, ...]:
        return (
            self.case_id, self.question_id, self.source_snapshot_id,
            self.build_commit, self.model_id, self.prompt_version,
            self.retrieval_version,
        )


@dataclass(frozen=True)
class MemoryABCase:
    fixture: MemoryFixture
    control: MemoryRun
    treatment: MemoryRun

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "MemoryABCase":
        fixture = MemoryFixture.from_dict(value.get("fixture", {}))
        control = MemoryRun.from_dict(value.get("control", {}))
        treatment = MemoryRun.from_dict(value.get("treatment", {}))
        if control.arm != Arm.CONTROL or control.memory_enabled:
            raise BenchmarkContractError("control arm must have memory disabled")
        if treatment.arm != Arm.TREATMENT or not treatment.memory_enabled:
            raise BenchmarkContractError("treatment arm must have memory enabled")
        if control.match_key != treatment.match_key:
            raise BenchmarkContractError("control and treatment must be matched except for memory")
        if control.run_id == treatment.run_id:
            raise BenchmarkContractError("control and treatment require distinct run ids")
        if fixture.case_id != control.case_id:
            raise BenchmarkContractError("fixture case_id must match both runs")
        if control.recalled_memory_ids or control.applied_memory_ids:
            raise BenchmarkContractError("control arm cannot recall or apply memory")
        if control.unsupported_personalization_claims:
            raise BenchmarkContractError("control arm cannot emit personalization claims")
        return MemoryABCase(fixture, control, treatment)


@dataclass(frozen=True)
class MemoryFinding:
    code: str
    fixture_id: str
    message: str
    critical: bool


@dataclass(frozen=True)
class MemoryCaseResult:
    fixture_id: str
    personalization_lift: float
    factual_integrity_delta: float
    citation_binding_delta: float
    relevant_recall: Optional[float]
    recall_precision: Optional[float]
    cross_account_exposures: int
    stale_or_deleted_applied: int
    irrelevant_applied: int
    unsupported_personalization_claims: int
    safe: bool
    finding_codes: Tuple[str, ...]


@dataclass(frozen=True)
class MemoryABScorecard:
    cases: Tuple[MemoryCaseResult, ...]
    findings: Tuple[MemoryFinding, ...]
    case_count: int
    mean_personalization_lift: Optional[float]
    mean_relevant_recall: Optional[float]
    mean_recall_precision: Optional[float]
    cross_account_exposures: int
    critical_failure_count: int
    fully_evaluated: bool
    safe_to_expand: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def score_memory_ab(
    cases: Sequence[MemoryABCase], *, maximum_integrity_regression: float = 0.0,
) -> MemoryABScorecard:
    if not 0.0 <= maximum_integrity_regression <= 1.0:
        raise BenchmarkContractError("maximum_integrity_regression must be between 0 and 1")
    fixture_ids = [case.fixture.fixture_id for case in cases]
    if len(set(fixture_ids)) != len(fixture_ids):
        raise BenchmarkContractError("fixture ids must be unique")
    findings = []
    results = []
    for case in sorted(cases, key=lambda item: item.fixture.fixture_id):
        fixture = case.fixture
        treatment = case.treatment
        records = {item.memory_id: item for item in fixture.records}
        recalled = set(treatment.recalled_memory_ids)
        applied = set(treatment.applied_memory_ids)
        expected = set(fixture.expected_relevant_ids)

        def add(code: str, message: str, critical: bool = True) -> None:
            findings.append(MemoryFinding(code, fixture.fixture_id, message, critical))

        unknown = recalled - set(records)
        if unknown:
            add("unregistered_memory_recalled", "treatment recalled memory outside the frozen fixture")
        cross_account = sum(
            memory_id in records and records[memory_id].owner_ref != fixture.owner_ref
            for memory_id in recalled
        )
        if cross_account:
            add("cross_account_exposure", "treatment recalled another owner's memory")
        wrong_ticker = sum(
            memory_id in records and records[memory_id].ticker != fixture.ticker
            for memory_id in recalled
        )
        if wrong_ticker:
            add("cross_ticker_memory", "treatment recalled memory outside the ticker scope")
        stale_or_deleted = sum(
            memory_id in records and records[memory_id].state != MemoryState.ACTIVE
            for memory_id in applied
        )
        if stale_or_deleted:
            add("stale_or_deleted_memory_applied", "treatment applied stale or deleted memory")
        irrelevant_applied = len(applied - expected)
        if irrelevant_applied:
            add("irrelevant_memory_applied", "treatment applied memory not marked relevant")
        if treatment.unsupported_personalization_claims:
            add("unsupported_personalization", "treatment emitted unsupported personalized claims")

        factual_delta = treatment.factual_integrity - case.control.factual_integrity
        citation_delta = treatment.citation_binding - case.control.citation_binding
        quality_lift = treatment.analytical_quality - case.control.analytical_quality
        if factual_delta + maximum_integrity_regression < -1e-12:
            add("factual_integrity_regression", "memory treatment reduced factual integrity")
        if citation_delta + maximum_integrity_regression < -1e-12:
            add("citation_binding_regression", "memory treatment reduced citation binding")
        if quality_lift < 0:
            add("negative_personalization_lift", "memory treatment reduced analytical quality", False)

        relevant_recall = len(recalled & expected) / len(expected) if expected else None
        recall_precision = len(recalled & expected) / len(recalled) if recalled else None
        if expected and relevant_recall < 1.0:
            add("relevant_memory_missed", "treatment did not recall every expected relevant memory", False)
        case_findings = [item for item in findings if item.fixture_id == fixture.fixture_id]
        safe = not any(item.critical for item in case_findings)
        results.append(MemoryCaseResult(
            fixture_id=fixture.fixture_id,
            personalization_lift=quality_lift,
            factual_integrity_delta=factual_delta,
            citation_binding_delta=citation_delta,
            relevant_recall=relevant_recall, recall_precision=recall_precision,
            cross_account_exposures=cross_account,
            stale_or_deleted_applied=stale_or_deleted,
            irrelevant_applied=irrelevant_applied,
            unsupported_personalization_claims=treatment.unsupported_personalization_claims,
            safe=safe, finding_codes=tuple(item.code for item in case_findings),
        ))

    def mean(values: Sequence[float]) -> Optional[float]:
        return sum(values) / len(values) if values else None

    recalls = [item.relevant_recall for item in results if item.relevant_recall is not None]
    precisions = [item.recall_precision for item in results if item.recall_precision is not None]
    critical = sum(item.critical for item in findings)
    exposures = sum(item.cross_account_exposures for item in results)
    return MemoryABScorecard(
        cases=tuple(results), findings=tuple(findings), case_count=len(cases),
        mean_personalization_lift=mean([item.personalization_lift for item in results]),
        mean_relevant_recall=mean(recalls), mean_recall_precision=mean(precisions),
        cross_account_exposures=exposures, critical_failure_count=critical,
        fully_evaluated=bool(cases),
        safe_to_expand=bool(cases) and critical == 0 and exposures == 0,
    )


def score_payload(payload: Mapping[str, Any]) -> MemoryABScorecard:
    return score_memory_ab(
        [MemoryABCase.from_dict(item) for item in payload.get("cases", ())],
        maximum_integrity_regression=float(payload.get("maximum_integrity_regression", 0.0)),
    )
