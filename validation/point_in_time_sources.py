"""Point-in-time source normalization and look-ahead leakage auditing.

Historical benchmark cases may only admit the exact document/data version that
was publicly available by the case boundary.  Retrieval time is not treated as
publication time, and an original publication date cannot authorize content
from a later amendment or revision.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .intelligence_benchmark import (
    BenchmarkContractError,
    SourceSnapshot,
    _aware_iso,
)


class SourceKind(str, Enum):
    SEC_FILING = "sec_filing"
    ISSUER_RELEASE = "issuer_release"
    TRANSCRIPT = "transcript"
    NEWS = "news"
    MARKET_DATA = "market_data"
    CONSENSUS = "analyst_consensus"
    OTHER = "other"


class LeakageSeverity(str, Enum):
    STOP_SHIP = "stop_ship"
    REVIEW = "review"


_TIMESTAMP_FIELDS = {
    SourceKind.SEC_FILING: "accepted_at",
    SourceKind.ISSUER_RELEASE: "published_at",
    SourceKind.TRANSCRIPT: "published_at",
    SourceKind.NEWS: "published_at",
    SourceKind.MARKET_DATA: "observed_at",
    SourceKind.CONSENSUS: "observed_at",
    SourceKind.OTHER: "available_at",
}


@dataclass(frozen=True)
class PointInTimeSource:
    source_id: str
    source_kind: SourceKind
    document_url: str
    version_available_at: str
    retrieved_at: str
    content_sha256: str
    timestamp_basis: str
    original_published_at: Optional[str] = None
    revision_id: Optional[str] = None
    authoritative: bool = False

    def to_snapshot(self) -> SourceSnapshot:
        """Convert only normalized exact-version metadata to the core contract."""
        return SourceSnapshot(
            source_id=self.source_id,
            source_type=self.source_kind.value,
            document_url=self.document_url,
            # SourceSnapshot.published_at means the admitted bytes became public.
            # It deliberately does not use an earlier original-publication date.
            published_at=self.version_available_at,
            retrieved_at=self.retrieved_at,
            content_sha256=self.content_sha256,
            authoritative=self.authoritative,
        )


@dataclass(frozen=True)
class LeakageFinding:
    code: str
    severity: LeakageSeverity
    source_id: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "source_id": self.source_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class PointInTimeAudit:
    as_of: str
    admitted: Tuple[SourceSnapshot, ...]
    rejected_source_ids: Tuple[str, ...]
    findings: Tuple[LeakageFinding, ...]

    @property
    def passed(self) -> bool:
        return not any(
            finding.severity == LeakageSeverity.STOP_SHIP
            for finding in self.findings
        )

    @property
    def lookahead_leakage_count(self) -> int:
        return sum(
            finding.code in {"future_source_version", "future_retrieval_dependency"}
            for finding in self.findings
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of,
            "passed": self.passed,
            "lookahead_leakage_count": self.lookahead_leakage_count,
            "admitted": [asdict(source) for source in self.admitted],
            "rejected_source_ids": list(self.rejected_source_ids),
            "findings": [finding.to_dict() for finding in self.findings],
        }


def normalize_source(record: Mapping[str, Any]) -> PointInTimeSource:
    """Normalize source-specific public timestamps without unsafe fallbacks.

    A later revision must supply ``revision_published_at``.  When present, that
    timestamp is always the exact-version availability boundary even if the
    original document was public earlier.
    """
    source_id = str(record.get("source_id", "")).strip()
    if not source_id:
        raise BenchmarkContractError("source_id is required")
    try:
        kind = SourceKind(str(record.get("source_type", "")))
    except ValueError as exc:
        raise BenchmarkContractError(
            f"source {source_id} has an unsupported source_type"
        ) from exc
    basis = _TIMESTAMP_FIELDS[kind]
    original = record.get(basis)
    if not original:
        raise BenchmarkContractError(
            f"source {source_id} requires explicit {basis}"
        )
    version_available_at = record.get("revision_published_at") or original
    timestamp_basis = "revision_published_at" if record.get("revision_published_at") else basis
    retrieved_at = record.get("retrieved_at")
    if not retrieved_at:
        raise BenchmarkContractError(
            f"source {source_id} requires explicit retrieved_at"
        )
    _aware_iso(str(original), field_name=basis)
    _aware_iso(str(version_available_at), field_name=timestamp_basis)
    _aware_iso(str(retrieved_at), field_name="retrieved_at")
    return PointInTimeSource(
        source_id=source_id,
        source_kind=kind,
        document_url=str(record.get("document_url", "")),
        version_available_at=str(version_available_at),
        retrieved_at=str(retrieved_at),
        content_sha256=str(record.get("content_sha256", "")),
        timestamp_basis=timestamp_basis,
        original_published_at=str(original),
        revision_id=(str(record["revision_id"]) if record.get("revision_id") else None),
        authoritative=bool(record.get("authoritative", False)),
    )


def audit_point_in_time_sources(
    *, as_of: str, records: Sequence[Mapping[str, Any]],
) -> PointInTimeAudit:
    boundary = _aware_iso(as_of, field_name="as_of")
    findings = []
    admitted = []
    rejected = []
    seen_ids = set()

    for index, record in enumerate(records):
        fallback_id = str(record.get("source_id") or f"source-index-{index}")
        try:
            source = normalize_source(record)
        except BenchmarkContractError as exc:
            rejected.append(fallback_id)
            findings.append(LeakageFinding(
                code="unverifiable_availability",
                severity=LeakageSeverity.STOP_SHIP,
                source_id=fallback_id,
                message=str(exc),
            ))
            continue
        if source.source_id in seen_ids:
            rejected.append(source.source_id)
            findings.append(LeakageFinding(
                code="duplicate_source_id",
                severity=LeakageSeverity.STOP_SHIP,
                source_id=source.source_id,
                message="source_id is duplicated within the case",
            ))
            continue
        seen_ids.add(source.source_id)
        available = _aware_iso(
            source.version_available_at, field_name=source.timestamp_basis
        )
        retrieved = _aware_iso(source.retrieved_at, field_name="retrieved_at")
        source_findings = []
        if available > boundary:
            source_findings.append(LeakageFinding(
                code="future_source_version",
                severity=LeakageSeverity.STOP_SHIP,
                source_id=source.source_id,
                message=(
                    f"exact source version became public at "
                    f"{source.version_available_at}, after {as_of}"
                ),
            ))
        if retrieved < available:
            source_findings.append(LeakageFinding(
                code="impossible_retrieval_order",
                severity=LeakageSeverity.STOP_SHIP,
                source_id=source.source_id,
                message="retrieved_at precedes exact-version public availability",
            ))
        # A historical snapshot may be retrieved later if its exact bytes are
        # version-addressed.  Without a hash, later retrieval could silently
        # depend on revised content and is treated as leakage, not a warning.
        valid_hash = len(source.content_sha256) == 64
        if valid_hash:
            try:
                int(source.content_sha256, 16)
            except ValueError:
                valid_hash = False
        if not valid_hash:
            code = (
                "future_retrieval_dependency"
                if retrieved > boundary else "unverifiable_content_version"
            )
            source_findings.append(LeakageFinding(
                code=code,
                severity=LeakageSeverity.STOP_SHIP,
                source_id=source.source_id,
                message="exact historical bytes require a valid SHA-256 content hash",
            ))
        if not source.document_url.strip():
            source_findings.append(LeakageFinding(
                code="missing_document_identity",
                severity=LeakageSeverity.STOP_SHIP,
                source_id=source.source_id,
                message="document_url is required to identify the admitted source",
            ))
        if source.source_kind in {SourceKind.NEWS, SourceKind.TRANSCRIPT, SourceKind.CONSENSUS} and not source.authoritative:
            source_findings.append(LeakageFinding(
                code="secondary_source_requires_review",
                severity=LeakageSeverity.REVIEW,
                source_id=source.source_id,
                message="secondary-source use requires provenance and entailment review",
            ))
        findings.extend(source_findings)
        if any(item.severity == LeakageSeverity.STOP_SHIP for item in source_findings):
            rejected.append(source.source_id)
        else:
            admitted.append(source.to_snapshot())

    return PointInTimeAudit(
        as_of=as_of,
        admitted=tuple(sorted(admitted, key=lambda item: item.source_id)),
        rejected_source_ids=tuple(rejected),
        findings=tuple(findings),
    )


def require_point_in_time_sources(
    *, as_of: str, records: Sequence[Mapping[str, Any]],
) -> Tuple[SourceSnapshot, ...]:
    audit = audit_point_in_time_sources(as_of=as_of, records=records)
    if not audit.passed:
        codes = ", ".join(sorted({finding.code for finding in audit.findings if finding.severity == LeakageSeverity.STOP_SHIP}))
        raise BenchmarkContractError(f"point-in-time source gate failed: {codes}")
    return audit.admitted

