"""Core data models for the Sprint 2A production-validation harness.

Pure dataclasses — no network, no I/O. Kept dependency-light so the checks and
report modules can be unit tested without any live backend.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Ordering for sorting/aggregation (lower index = more severe).
_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


def severity_rank(s: Severity) -> int:
    return _SEVERITY_ORDER.get(s, 99)


@dataclass
class Finding:
    """One validation finding against a single query's response."""
    code: str
    severity: Severity
    message: str
    field: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class QueryFixture:
    """One benchmark question."""
    id: str
    ticker: str
    company: str
    category: str
    question: str
    requires: List[str] = field(default_factory=list)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "QueryFixture":
        return QueryFixture(
            id=str(d["id"]), ticker=str(d["ticker"]), company=str(d["company"]),
            category=str(d["category"]), question=str(d["question"]),
            requires=list(d.get("requires", [])),
        )


@dataclass
class QueryOutcome:
    """The full result of running one fixture: request metadata, raw response,
    and the normalized validation findings."""
    fixture: QueryFixture
    status: str  # "completed" | "http_error" | "timeout" | "network_error" | "malformed" | "skipped"
    elapsed_s: float = 0.0
    attempts: int = 1
    http_status: Optional[int] = None
    error: str = ""
    raw_response: Optional[Dict[str, Any]] = None
    thesis: Optional[Dict[str, Any]] = None
    findings: List[Finding] = field(default_factory=list)
    field_presence: Dict[str, bool] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    def worst_severity(self) -> Optional[Severity]:
        if not self.findings:
            return None
        return min((f.severity for f in self.findings), key=severity_rank)

    def passed(self) -> bool:
        """A query 'passes' if it completed and has no CRITICAL or HIGH findings."""
        if self.status != "completed":
            return False
        worst = self.worst_severity()
        return worst not in (Severity.CRITICAL, Severity.HIGH)

    def to_dict(self, include_raw: bool = True) -> Dict[str, Any]:
        return {
            "id": self.fixture.id,
            "ticker": self.fixture.ticker,
            "company": self.fixture.company,
            "category": self.fixture.category,
            "question": self.fixture.question,
            "status": self.status,
            "elapsed_s": round(self.elapsed_s, 3),
            "attempts": self.attempts,
            "http_status": self.http_status,
            "error": self.error,
            "passed": self.passed(),
            "worst_severity": self.worst_severity().value if self.worst_severity() else None,
            "field_presence": self.field_presence,
            "findings": [f.to_dict() for f in self.findings],
            "raw_response_file": None,  # populated by the runner if raw responses are persisted
            **({"raw_response": self.raw_response} if include_raw else {}),
        }
